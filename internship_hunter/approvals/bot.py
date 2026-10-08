"""The Telegram approval bot. Runs on the student's own PC (it has to: the
filled-in form opens in a browser there, and he presses Submit himself).

    python -m internship_hunter.approvals.cli bot

Redesigned 2026-10-08 around referrals: the aim is no longer to apply to
postings but to turn the right people into people who will vouch for him.

What it does, in a loop:
  1. Once a day: at 6 AM reads the job boards (only as a "who is hiring"
     signal) and looks for people at companies it hasn't checked yet; at
     7 AM (DAILY_RUN_HOUR) puts OUTREACH_PER_DAY (10) people in front of him -- follow-ups that are
     due first, then an email draft for anyone with a published address,
     then LinkedIn cards (a search link + a note he pastes himself; the
     bot never touches linkedin.com -- see linkedin_assist/) -- then the
     status update. Application cards are no longer sent daily: only when
     he asks (/more, /apply).
  1b. Every few minutes: checks the threads of emails he has sent for a
     reply or a bounce (only if he granted Gmail read access).
  2. Waits for a button tap or a command (long polling -- see
     telegram_client.get_updates).
  3. For every approved application, opens the real form with everything
     filled in, and watches until the window is closed. It never clicks
     Submit (CLAUDE.md constraint 4); if it sees the confirmation page it
     records the application as submitted, otherwise it asks.

Only messages from TELEGRAM_CHAT_ID are obeyed -- anyone else who finds the
bot is ignored.
"""

from __future__ import annotations

import re
import time
import traceback
from datetime import date, datetime

import requests

from internship_hunter import config, db
from internship_hunter.apply_assist import answers as answers_mod
from internship_hunter.apply_assist import choices, my_answers, playwright_fill, profile_fields
from internship_hunter.approvals import queue
from internship_hunter.drafting import batch, daily_cap
from internship_hunter.linkedin_assist import assist as linkedin
from internship_hunter.models import Application, Message
from internship_hunter.notify import telegram_client
from internship_hunter.outreach import paste, priority
from internship_hunter.scanner import eligibility

MAX_SCREENED_PER_RUN = 60  # postings whose requirements may be read in one go

HELP_TEXT = (
    "Every day I send you 5 people to write to. Extra, when you want it:\n\n"
    "People:\n"
    "/warm Name, how you know them, where they work - someone you already know; I draft a note asking who you should talk to\n"
    "/li <profile link> Name, Title, Company - someone you found on LinkedIn yourself\n"
    "/linkedin [n] - n more LinkedIn cards (default 5)\n"
    "/pitch [n] - n more emails: follow-ups due, then people with a published address (default 5)\n"
    "/to <draft id> <email> - put an address on an email draft that has none\n"
    "/status - the pipeline: contacted, replied, calls, referrals\n\n"
    "Applications (only when you ask):\n"
    "/apply <posting link> - someone told you to apply through a link: I fill the form in, you press Submit\n"
    "/more [n] - show n Colorado/Virginia postings as application cards (default 5)\n"
    "/open <id> - reopen an application's filled-in form\n"
    "/referral <id> - draft a referral email to someone at that company\n"
    "/result <id> interviewing|rejected - record what happened"
)


def _anthropic_client():
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not set in .env, so nothing can be drafted.")
    import anthropic

    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def _resume_path():
    return config.RESUME_PATH_PDF if config.RESUME_PATH_PDF.exists() else None


def propose_batch(
    conn,
    client,
    limit: int,
    send=telegram_client.send_message,
    fetch_form=playwright_fill.fetch_form,
    postings=None,
) -> int:
    """Draft and send up to `limit` application cards (never more than
    today's remaining budget). Returns how many were sent. `postings` is
    for /apply: those exact postings, even one the screening ruled out --
    if someone at the company told him to apply, that's their call.

    Every posting's own requirements are read first (scanner/eligibility.py).
    One he can't truthfully apply to -- "must be enrolled in a bachelor's
    program" -- is recorded as such and never becomes a card; that costs
    none of the day's budget."""
    profile_text, resume_text = batch.read_profile()
    applicant = profile_fields.build_applicant_info(profile_text, resume_text)
    limit = min(limit, daily_cap.remaining_today(conn))
    sent = 0
    asked_for = postings is not None
    for posting in (postings if asked_for else queue.next_postings(conn, MAX_SCREENED_PER_RUN)):
        if sent >= limit:
            break
        company = db.get_company(conn, posting.company_id)
        warnings = []
        if posting.eligibility is None:
            verdict = eligibility.screen_posting(client, company, posting)
            db.set_posting_eligibility(conn, posting.id, verdict.verdict, verdict.reason)
            posting.eligibility, posting.eligibility_reason = verdict.verdict, verdict.reason
        if posting.eligibility == "not_eligible" and not asked_for:
            continue
        if posting.eligibility == "not_eligible" and posting.eligibility_reason:
            warnings.append(f"The posting itself says: {posting.eligibility_reason}")
        if posting.eligibility == "long_shot" and posting.eligibility_reason:
            warnings.append(f"Long shot: {posting.eligibility_reason}")
        try:
            fields, choice_questions = fetch_form(posting)
        except Exception:  # noqa: BLE001 -- a posting that was taken down shouldn't stop the batch
            fields, choice_questions = [], []
            warnings.append("Couldn't read this form (the posting may have closed) -- check the link first.")
        # Standing answers first (choices.py + profile/my_answers.md): one-line
        # boxes like graduation year, then dropdowns / radio buttons. Whatever
        # those cover is not sent to the model at all.
        typed = {
            label: candidates[0]
            for label, kind in fields
            if kind in playwright_fill.TYPED_KINDS
            and (candidates := choices.candidates_for(label, posting_location=posting.location))
        }
        selections, unanswered = choices.plan_choices(choice_questions, posting_location=posting.location)
        answers, left = answers_mod.draft_answers(
            client, profile_text, resume_text, company, posting, fields, skip=tuple(typed),
        )
        warnings += answers_mod.validate_answers(answers)
        selections = {**typed, **selections}
        left = [l for l in left if l not in selections] + [q for q in unanswered if q not in left]
        # Anything still unanswered goes into his questions file, once.
        options_by_question = {q["question"]: q.get("options") for q in choice_questions}
        new_questions = my_answers.add_questions([(l, options_by_question.get(l)) for l in left], company.name)

        application_id = db.insert_application(
            conn, Application(posting_id=posting.id, answers=answers, left_for_you=left)
        )
        text = queue.build_card_text(
            application_id, company, posting,
            queue.expected_filled_labels([label for label, _ in fields], applicant), answers, left,
            resume_available=_resume_path() is not None, warnings=warnings, selections=selections,
            new_questions=len(new_questions),
        )
        try:
            response = send(text, reply_markup=telegram_client.inline_keyboard(queue.card_buttons(application_id)))
        except Exception:
            # No card reached him, so don't leave a "proposed" row he can never act on.
            conn.execute("DELETE FROM applications WHERE id = ?", (application_id,))
            conn.commit()
            raise
        db.set_application_telegram_message_id(conn, application_id, response["result"]["message_id"])
        sent += 1
    return sent


def _describe(conn, application: Application) -> str:
    posting = db.get_posting(conn, application.posting_id)
    company = db.get_company(conn, posting.company_id) if posting else None
    return f"#{application.id} {company.name if company else '?'} - {posting.title if posting else '?'}"


def _after_submitted(conn, application: Application, send) -> None:
    db.update_application_status(conn, application.id, "submitted")
    posting = db.get_posting(conn, application.posting_id)
    has_contacts = bool(posting and db.list_contacts(conn, company_id=posting.company_id))
    send(
        f"Recorded as submitted: {_describe(conn, application)}\n"
        f"I'll flag it if there's no word in {config.FOLLOW_UP_AFTER_DAYS} days."
        + ("\nA note to a real person there makes it far more likely someone reads it:" if has_contacts else ""),
        reply_markup=telegram_client.inline_keyboard(queue.referral_buttons(application.id)) if has_contacts else None,
    )


def open_application(conn, application: Application, send=telegram_client.send_message, fill=playwright_fill.fill_application) -> None:
    """Open one approved application's form, filled in, and wait for the
    student to close the window."""
    posting = db.get_posting(conn, application.posting_id)
    profile_text, resume_text = batch.read_profile()
    applicant = profile_fields.build_applicant_info(profile_text, resume_text)
    # Mark it opened BEFORE the browser launches: if the browser crashes, the
    # main loop must not keep relaunching the same form forever.
    db.update_application_status(conn, application.id, "opened")
    try:
        summary = fill(
            posting, applicant, resume_path=_resume_path(),
            extra_answers=application.answers, wait_for_human=playwright_fill.wait_until_closed,
        )
    except Exception as exc:  # noqa: BLE001
        send(f"Couldn't open {_describe(conn, application)}: {exc}\nTry /open {application.id}, or apply by hand: {posting.url}")
        return
    company = db.get_company(conn, posting.company_id)
    learned = my_answers.record_answers(
        summary.get("observed") or {}, company.name if company else "a",
        has_answer=lambda question: bool(choices.candidates_for(question, posting_location=posting.location)),
    )
    if learned:
        send(
            f"Remembered {len(learned)} answer(s) you picked, for next time (edit them in profile/my_answers.md):\n"
            + "\n".join(f"  {line}" for line in learned[:15])
        )
    if summary["confirmation_seen"]:
        _after_submitted(conn, application, send)
    else:
        send(
            f"Did you submit {_describe(conn, application)}?",
            reply_markup=telegram_client.inline_keyboard(queue.submitted_buttons(application.id)),
        )


# --- Outreach drafts ---------------------------------------------------

DRAFT_TITLES = {"follow-up": "Follow-up", "referral": "Referral ask", "pitch": "Cold pitch"}


def announce_draft(send, company, contact, message, warnings, kind: str = "pitch") -> None:
    """Tell the student about one new Gmail draft, with the full text and a
    button to record that he sent it (which starts the 7-day reply clock)."""
    who = f"{contact.name} ({contact.title})" if contact else "the team"
    to = message.to_email
    if not to:
        to_line = f"To: BLANK - nobody has published an address for them. Add one with: /to {message.id} name@company.com"
    elif contact is not None and contact.email == to:
        to_line = f"To: {to}"
    else:
        to_line = f"To: {to} (the company's published inbox, not a personal address)"
    send(
        f"Draft #{message.id} - {DRAFT_TITLES.get(kind, 'Email')}: {company.name} - {who}\n{to_line}\n"
        f"Subject: {message.subject}\n\n{message.body}\n\n"
        + "".join(f"Check: {w}\n" for w in warnings)
        + "Read it. Send now sends it from your Gmail exactly as it stands there "
        "(edit the draft in Gmail first if anything is off).",
        reply_markup=telegram_client.inline_keyboard(queue.draft_buttons(message.id)),
    )


def send_drafts(conn, limit: int, send=telegram_client.send_message, client=None, service=None) -> int:
    """Create up to `limit` outreach drafts (due follow-ups first, then new
    cold pitches) and announce each one. Returns how many were made."""
    if limit <= 0 or daily_cap.remaining_today(conn) <= 0:
        return 0
    if not batch.due_follow_ups(conn) and not batch.next_contacts(conn, 1):
        return 0  # nothing to write -- don't even open the Gmail connection
    if service is None:
        from internship_hunter.drafting import gmail_client

        service = gmail_client.get_service()
    created = batch.draft_batch(conn, client or _anthropic_client(), service, limit)
    for d in created:
        announce_draft(send, d["company"], d["contact"], d["message"], d["warnings"], d["kind"])
    return len(created)


def draft_referral(conn, application: Application, send=telegram_client.send_message) -> None:
    from internship_hunter.drafting import gmail_client

    posting = db.get_posting(conn, application.posting_id)
    company = db.get_company(conn, posting.company_id)
    picked = [c for comp, c in batch.next_contacts(conn, 10_000, any_state=True) if comp.id == company.id]
    if not picked:
        send(
            f"No one at {company.name} left to write to (no contacts on file, or all already drafted).\n"
            f'Find people: python -m internship_hunter.people.cli run --company "{company.name}"'
        )
        return
    contact = picked[0]
    profile_text, resume_text = batch.read_profile()
    message, warnings = batch.draft_one(
        conn, _anthropic_client(), gmail_client.get_service(), profile_text, resume_text,
        company, contact=contact, posting=posting, ask_type="referral",
    )
    announce_draft(send, company, contact, message, warnings, kind="referral")


# --- LinkedIn assist ---------------------------------------------------
# Nothing below opens, requests or reads linkedin.com. A card is a search
# link (plain text) and a note; he opens the link and sends the request.

def send_linkedin_card(conn, client, company, contact, send, profile=None) -> bool:
    """Draft one connection note and send it as a card. Returns False (and
    makes no API call) once today's LinkedIn cap is used up."""
    if linkedin.remaining_today(conn) <= 0:
        return False
    profile_text, resume_text = profile or batch.read_profile()
    note = linkedin.draft_note(client, profile_text, resume_text, company, contact)
    message = linkedin.new_card(conn, company, contact, note)
    try:
        send(linkedin.build_card_text(
            message.id, company, contact, note, linkedin.validate_note(note),
            hiring=priority.hiring_line(company, priority.hiring_now(conn)),
        ))
        # The note alone, so copying it is one press-and-hold; buttons sit under it.
        send(note, reply_markup=telegram_client.inline_keyboard(
            linkedin.card_buttons(message.id, link=linkedin.link_for(contact, company), name=contact.name)
        ))
    except Exception:
        # No card reached him, so don't leave a row he can never act on.
        conn.execute("DELETE FROM messages WHERE id = ?", (message.id,))
        conn.commit()
        raise
    return True


def send_linkedin_cards(conn, limit: int, send=telegram_client.send_message, client=None) -> int:
    """Send up to `limit` LinkedIn cards (never more than today's LinkedIn
    cap allows) for people already on file. Returns how many were sent."""
    limit = min(limit, linkedin.remaining_today(conn))
    picked = linkedin.next_contacts(conn, limit) if limit > 0 else []
    if not picked:
        return 0
    client = client or _anthropic_client()
    profile = batch.read_profile()
    return sum(send_linkedin_card(conn, client, company, contact, send, profile) for company, contact in picked)


def add_linkedin_person(conn, text: str, send=telegram_client.send_message, client=None) -> None:
    """/li <profile link> Name, Title, Company: store someone he found
    himself as a contact (the link is saved, never opened) and draft a note."""
    from internship_hunter.models import Contact
    from internship_hunter.people import dedupe

    person = linkedin.parse_li_command(text)
    if person is None:
        send(linkedin.LI_USAGE)
        return
    company, suggestions = linkedin.find_company(conn, person.company)
    if company is None:
        hint = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
        send(
            f'"{person.company}" isn\'t on the company list.{hint}\n'
            "Add it first: python -m internship_hunter.companies.cli add --name ... (see README), then send /li again."
        )
        return
    contact, is_new = dedupe.store_contact(conn, Contact(
        company_id=company.id, name=person.name, title=person.title, source_url=person.profile_url,
        fact=person.fact, source_kind="manual", linkedin_url=person.profile_url,
    ))
    added = "Added" if is_new else "Already on file - updated"
    if linkedin.has_card(conn, contact.id):
        send(f"{added} {contact.name} at {company.name}. They already have a LinkedIn card, so no second one.")
    elif linkedin.remaining_today(conn) <= 0:
        send(f"{added} {contact.name} at {company.name}. Today's {config.LINKEDIN_DAILY_CAP} LinkedIn cards are "
             "used up, so their card comes with tomorrow's batch.")
    else:
        send_linkedin_card(conn, client or _anthropic_client(), company, contact, send)


def send_linkedin_reminders(conn, send=telegram_client.send_message, today: date | None = None) -> int:
    """One nudge, once, for each request sent 7+ days ago with no answer."""
    due = linkedin.due_reminders(conn, today)
    for message in due:
        contact = db.get_contact(conn, message.contact_id) if message.contact_id else None
        company = db.get_company(conn, message.company_id)
        who = f"{contact.name} at {company.name}" if contact else company.name
        label = "LinkedIn" if message.channel == linkedin.CHANNEL else "Note"
        send(
            f"{label} #{message.id}: no answer from {who} in {config.FOLLOW_UP_AFTER_DAYS} days. "
            "If they accepted or wrote back, tap Replied and I'll draft your next message. "
            "Otherwise leave it - this is the only reminder.",
            reply_markup=telegram_client.inline_keyboard(linkedin.replied_buttons(message.id)),
        )
        db.mark_message_reminded(conn, message.id)
    return len(due)


def _handle_linkedin_tap(conn, action: str, message_id: int, callback_query: dict, acknowledge, send) -> None:
    """Sent / Skip / Not found / Replied, under a LinkedIn card or a note
    he pastes somewhere else (outreach/paste.py)."""
    message = db.get_message(conn, message_id)
    if message is None or message.channel not in linkedin.MANUAL_CHANNELS:
        acknowledge("That button is out of date.")
        return
    telegram_message_id = (callback_query.get("message") or {}).get("message_id")

    def swap_buttons(rows) -> None:
        try:
            telegram_client.edit_message_buttons(telegram_message_id, telegram_client.inline_keyboard(rows) if rows else None)
        except Exception:  # noqa: BLE001
            pass

    if action == "li_replied":
        if message.status != "sent":
            acknowledge(f"Already {message.status}.")
            return
        db.update_message_status(conn, message.id, "replied")
        acknowledge("Drafting your next message...")
        swap_buttons(None)
        contact = db.get_contact(conn, message.contact_id) if message.contact_id else None
        company = db.get_company(conn, message.company_id)
        profile_text, resume_text = batch.read_profile()
        reply = linkedin.draft_reply(_anthropic_client(), profile_text, resume_text, company, contact, message.body)
        db.insert_message(conn, Message(
            company_id=company.id, contact_id=message.contact_id, channel=f"{message.channel}_reply",
            subject=f"Follow-up to {contact.name if contact else company.name}", body=reply,
        ))
        where = "into the LinkedIn chat" if message.channel == linkedin.CHANNEL else "into your reply"
        send(
            f"Next message for {contact.name if contact else company.name} ({len(reply)} characters). "
            f"Read it, change what you like, and paste it {where} yourself:\n\n{reply}\n\n"
            "Tap below when you know how it went.",
            reply_markup=telegram_client.inline_keyboard(queue.stage_buttons(message.id)),
        )
        return
    if message.status != "drafted":
        acknowledge(f"Already {message.status.replace('_', ' ')}.")
        return
    if action == "li_sent":
        db.mark_message_sent(conn, message.id)
        acknowledge("Logged.")
        swap_buttons(linkedin.replied_buttons(message.id))
    elif action == "li_skip" or message.channel != linkedin.CHANNEL:
        db.update_message_status(conn, message.id, "skipped")
        acknowledge("Skipped.")
        swap_buttons(None)
    else:
        db.update_message_status(conn, message.id, "not_found")
        acknowledge("Marked not found - trying another way.")
        swap_buttons(None)
        try:
            offer_another_way(conn, message, send)
        except Exception as exc:  # noqa: BLE001 -- the tap is recorded either way
            send(f"Couldn't draft another way to reach them: {exc}")


def offer_another_way(conn, message, send, client=None, service=None) -> None:
    """After "Not found": if the company publishes an inbox, an email
    draft to it; otherwise a note for its website contact form."""
    contact = db.get_contact(conn, message.contact_id) if message.contact_id else None
    company = db.get_company(conn, message.company_id)
    if contact is None:
        return
    profile_text, resume_text = batch.read_profile()
    client = client or _anthropic_client()
    if company.contact_email:
        drafted, warnings = batch.draft_one(
            conn, client, service or _gmail_service(), profile_text, resume_text, company, contact=contact, ask_type="call",
        )
        announce_draft(send, company, contact, drafted, warnings, kind="pitch")
        return
    text = paste.draft_message(client, profile_text, resume_text, company, contact)
    note = paste.new_message(conn, company, contact, text)
    send(
        paste.build_fallback_card_text(note.id, company, contact, text, paste.validate_message(text)),
        reply_markup=telegram_client.inline_keyboard(paste.buttons(note.id)),
    )


def add_warm_person(conn, text: str, send=telegram_client.send_message, client=None) -> None:
    """/warm Name, how you know them, where they work: someone he already
    knows. Stored, and a note asking who he should talk to is drafted."""
    from internship_hunter.models import Contact
    from internship_hunter.people import dedupe

    person = paste.parse_warm_command(text)
    if person is None:
        send(paste.WARM_USAGE)
        return
    company = paste.network_company(conn)
    contact, is_new = dedupe.store_contact(conn, Contact(
        company_id=company.id, name=person.name, title=person.works_at, fact=person.relationship,
        source_url="told to the bot by the student (/warm)", source_kind="manual",
    ))
    if not is_new and any(m.contact_id == contact.id for m in db.list_messages(conn)):
        send(f"{contact.name} is already on your list and already has a note.")
        return
    profile_text, resume_text = batch.read_profile()
    note_text = paste.draft_message(client or _anthropic_client(), profile_text, resume_text, company, contact, warm=True)
    note = paste.new_message(conn, company, contact, note_text, warm=True)
    send(
        paste.build_warm_card_text(note.id, contact, note_text, paste.validate_message(note_text)),
        reply_markup=telegram_client.inline_keyboard(paste.buttons(note.id)),
    )


def _handle_stage_tap(conn, action: str, message_id: int, callback_query: dict, acknowledge, send) -> None:
    """Call booked / They referred me / It went nowhere, after a reply."""
    message = db.get_message(conn, message_id)
    if message is None:
        acknowledge("That button is out of date.")
        return
    telegram_message_id = (callback_query.get("message") or {}).get("message_id")

    def swap_buttons(rows) -> None:
        try:
            telegram_client.edit_message_buttons(telegram_message_id, telegram_client.inline_keyboard(rows) if rows else None)
        except Exception:  # noqa: BLE001
            pass

    if action == "st_call":
        db.update_message_status(conn, message.id, "call")
        acknowledge("Call recorded.")
        swap_buttons(queue.stage_buttons(message.id, after_call=True))
        send("Call recorded. Before it: have one project open and running, know your hours cold, and have one "
             "thing you could build for them in two weeks. At the end, ask who else you should talk to.")
    elif action == "st_ref":
        db.update_message_status(conn, message.id, "referred")
        acknowledge("Referral recorded.")
        swap_buttons(None)
        send("Referral recorded - that's what all of this is for. If they gave you a link to apply through, "
             "send it to me: /apply <link>")
    else:
        db.update_message_status(conn, message.id, "rejected")
        acknowledge("Recorded.")
        swap_buttons(None)


# --- Handling taps and commands ------------------------------------------

def _gmail_service():
    from internship_hunter.drafting import gmail_client

    return gmail_client.get_service()


def send_approved_draft(conn, message, send, service=None) -> bool:
    """The Send button: send this one draft from his Gmail, now. This is
    the only place the tool sends email, and it only runs on his own tap
    under the full text of the draft. Returns True if it went out."""
    from internship_hunter.drafting import gmail_client

    if message.status != "drafted":
        send(f"Draft #{message.id} was already {message.status}.")
        return False
    service = service or _gmail_service()
    try:
        recipient = gmail_client.draft_recipient(service, message.gmail_draft_id)
    except Exception:  # noqa: BLE001 -- the draft is gone: sent or deleted by hand in Gmail
        send(f"Draft #{message.id} isn't in Gmail any more. If you sent it yourself, tap 'I sent it from Gmail myself'.")
        return False
    if not recipient:
        send(f"Draft #{message.id} has no address yet. Add one with: /to {message.id} name@company.com - then tap Send now.")
        return False
    sent = gmail_client.send_draft(service, message.gmail_draft_id)
    db.set_message_to_email(conn, message.id, recipient)
    db.mark_message_sent(conn, message.id, sent.get("threadId"))
    watching = "I'm watching the thread for a reply." if gmail_client.has_read_access() else (
        "Tap 'They replied' when they do (or let me watch for replies: "
        "python -m internship_hunter.drafting.cli auth)."
    )
    send(f"Sent draft #{message.id} to {recipient}. {watching} No reply in "
         f"{config.FOLLOW_UP_AFTER_DAYS} days gets one follow-up draft.")
    return True


def _handle_draft_tap(conn, action: str, message_id: int, callback_query: dict, acknowledge, send) -> None:
    """Send now / I sent it from Gmail / They replied, under an outreach draft."""
    from internship_hunter.drafting import gmail_client

    message = db.get_message(conn, message_id)
    if message is None:
        acknowledge("That button is out of date.")
        return
    telegram_message_id = (callback_query.get("message") or {}).get("message_id")

    def swap_buttons(rows) -> None:
        try:
            telegram_client.edit_message_buttons(telegram_message_id, telegram_client.inline_keyboard(rows) if rows else None)
        except Exception:  # noqa: BLE001
            pass

    after_sending = None if gmail_client.has_read_access() else queue.reply_buttons(message.id)
    if action == "send":
        acknowledge("Sending...")
        if send_approved_draft(conn, message, send):
            swap_buttons(after_sending)
    elif action == "sent":
        thread_id = None
        if gmail_client.has_read_access():
            try:
                thread_id = gmail_client.find_sent_thread(_gmail_service(), message.subject)
            except Exception:  # noqa: BLE001
                thread_id = None
        db.mark_message_sent(conn, message.id, thread_id)
        acknowledge("Recorded as sent.")
        swap_buttons(after_sending)
    else:
        db.update_message_status(conn, message.id, "replied")
        acknowledge("Recorded.")
        send(
            f'Reply recorded for "{message.subject}". No follow-up will be drafted for it. Tap below when you know how it went.',
            reply_markup=telegram_client.inline_keyboard(queue.stage_buttons(message.id)),
        )


def handle_callback(conn, callback_query: dict, send=telegram_client.send_message) -> None:
    def acknowledge(text: str = "") -> None:
        try:
            telegram_client.answer_callback_query(callback_query["id"], text)
        except Exception:  # noqa: BLE001 -- a tap that sat unanswered while a form was open has expired; harmless
            pass

    parsed = queue.parse_callback(callback_query.get("data", ""))
    if parsed and parsed[0] in ("send", "sent", "replied"):
        _handle_draft_tap(conn, parsed[0], parsed[1], callback_query, acknowledge, send)
        return
    if parsed and parsed[0] in queue.LINKEDIN_ACTIONS:
        _handle_linkedin_tap(conn, parsed[0], parsed[1], callback_query, acknowledge, send)
        return
    if parsed and parsed[0] in queue.STAGE_ACTIONS:
        _handle_stage_tap(conn, parsed[0], parsed[1], callback_query, acknowledge, send)
        return
    application = db.get_application(conn, parsed[1]) if parsed else None
    if application is None:
        acknowledge("That button is out of date.")
        return
    action = parsed[0]
    message_id = (callback_query.get("message") or {}).get("message_id")

    def clear_buttons() -> None:
        if message_id:
            try:
                telegram_client.edit_message_buttons(message_id, None)
            except Exception:  # noqa: BLE001
                pass

    if action in ("approve", "skip"):
        if application.status != "proposed":
            acknowledge(f"Already {application.status}.")
        else:
            db.update_application_status(conn, application.id, "approved" if action == "approve" else "skipped")
            acknowledge("Approved - opening on your PC." if action == "approve" else "Skipped.")
        clear_buttons()
    elif action == "submitted":
        acknowledge("Recorded.")
        clear_buttons()
        if application.status != "submitted":
            _after_submitted(conn, application, send)
    elif action == "notyet":
        acknowledge()
        clear_buttons()
        send(f"OK. /open {application.id} reopens it whenever you're ready.")
    elif action == "referral":
        acknowledge("Drafting...")
        clear_buttons()
        draft_referral(conn, application, send)


EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def set_draft_address(conn, parts: list[str], send, service=None) -> None:
    """/to <draft id> <email>: put an address he found himself on a draft."""
    from internship_hunter.drafting import gmail_client

    message = db.get_message(conn, _int_arg(parts, 1, -1))
    email = parts[2].strip("<>") if len(parts) > 2 else ""
    if message is None or not EMAIL_RE.match(email):
        send("Usage: /to <draft id> name@company.com")
        return
    if message.status != "drafted":
        send(f"Draft #{message.id} was already {message.status}.")
        return
    gmail_client.replace_draft(service or _gmail_service(), message.gmail_draft_id, message.subject, message.body, email)
    db.set_message_to_email(conn, message.id, email)
    send(
        f"Draft #{message.id} is now addressed to {email}.",
        reply_markup=telegram_client.inline_keyboard(queue.draft_buttons(message.id)),
    )


def check_replies(conn, send=telegram_client.send_message, service=None) -> int:
    """Look at the Gmail thread of every email that's been sent and is
    still waiting. A reply stops its follow-up and pings him; a delivery
    failure marks the address bad. Does nothing without read access.
    Returns how many changed."""
    from internship_hunter.drafting import gmail_client

    waiting = [m for m in db.list_messages(conn, status="sent") if m.gmail_thread_id]
    if not waiting or (service is None and not gmail_client.has_read_access()):
        return 0
    service = service or _gmail_service()
    changed = 0
    for message in waiting:
        try:
            status, snippet = gmail_client.thread_status(service, message.gmail_thread_id, config.GMAIL_DRAFT_ACCOUNT)
        except Exception:  # noqa: BLE001 -- one unreadable thread shouldn't stop the rest
            continue
        if status == "waiting":
            continue
        company = db.get_company(conn, message.company_id)
        db.update_message_status(conn, message.id, status)
        changed += 1
        if status == "replied":
            send(
                f"You got a reply from {company.name} to \"{message.subject}\":\n\n{snippet}\n\n"
                "Open Gmail and answer it today. Tap below when you know how it went.",
                reply_markup=telegram_client.inline_keyboard(queue.stage_buttons(message.id)),
            )
        else:
            send(f"The email to {message.to_email} at {company.name} bounced - that address doesn't exist. "
                 "No follow-up will be drafted for it.")
    return changed


def find_new_people(conn, send=telegram_client.send_message, limit: int = 5) -> int:
    """Run the people finder (and the published-email search) on Colorado/
    Virginia companies it has never been run on, a few per day. Each
    company is only ever checked once. Returns how many people were added."""
    from internship_hunter.people import cli as people_cli

    todo = [
        c for c in db.list_companies_never_people_checked(conn)
        if c.state in config.PREFERRED_STATES and c.priority_tier != 4
    ][:limit]
    if not todo:
        return 0
    client = _anthropic_client()
    found = 0
    for company in todo:
        try:
            found += len(people_cli.run_for_company(client, conn, company))
        except Exception:  # noqa: BLE001 -- a site that won't load shouldn't stop the others
            continue
    return found


def _same_posting_url(a: str, b: str) -> bool:
    clean = lambda u: (u or "").split("?")[0].split("#")[0].rstrip("/").lower().removesuffix("/apply").removesuffix("/application")
    return bool(clean(a)) and clean(a) == clean(b)


def apply_through_link(conn, url: str, send=telegram_client.send_message, client=None) -> None:
    """/apply <posting link>: someone told him to apply through a link.
    If it's a posting the scanner has seen, send its application card (the
    usual Approve -> filled-in form -> he presses Submit)."""
    if not url.startswith("http"):
        send("Usage: /apply <the posting link they sent you>")
        return
    posting = next((p for p in db.list_postings(conn) if _same_posting_url(p.url, url)), None)
    if posting is None:
        send("That link isn't a posting I've seen on a company's job board, so I can't fill it in - apply by hand:\n"
             f"{url}\nYour standing answers are in profile/my_answers.md.")
        return
    existing = next((a for a in db.list_applications(conn) if a.posting_id == posting.id), None)
    if existing is not None:
        send(f"You already have application #{existing.id} for that posting ({existing.status}). /open {existing.id} reopens the form.")
        return
    if propose_batch(conn, client or _anthropic_client(), 1, send, postings=[posting]) == 0:
        send("Couldn't make that card - today's limit is used up. Try again tomorrow, or apply by hand.")


def send_daily_outreach(conn, send=telegram_client.send_message) -> int:
    """Today's people: OUTREACH_PER_DAY (5) in all. Email follow-ups that
    are due and anyone with a published address first, then LinkedIn cards
    for the rest. Returns how many were sent."""
    sent = 0
    # Each half on its own: on the first live run something in the email
    # half failed after one draft and took the LinkedIn cards down with it.
    for label, step in (("emails", send_drafts), ("LinkedIn cards", send_linkedin_cards)):
        try:
            sent += step(conn, daily_cap.outreach_remaining(conn), send)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()  # lands in data/bot.log
            send(f"Couldn't prepare today's {label}: {exc}")
    return sent


def find_emails_with_hunter(conn, limit: int = 1) -> int:
    """One Hunter.io domain lookup a day, if a key is set -- slow enough to
    stay inside the free plan's month. Returns how many addresses were stored."""
    from internship_hunter.people import hunter

    if not config.HUNTER_API_KEY:
        return 0
    return sum(len(stored) for _, stored in hunter.run(conn, limit))


def find_people_on_the_web(conn, limit: int | None = None) -> int:
    """Web search for people at tier-1 Colorado/Virginia companies never
    searched before. Off unless WEB_PEOPLE_SEARCH_PER_DAY is set in .env,
    because each company costs real money. Returns how many were new."""
    from internship_hunter.people import web_search

    limit = config.WEB_PEOPLE_SEARCH_PER_DAY if limit is None else limit
    todo = web_search.companies_to_search(conn)[:limit] if limit > 0 else []
    if not todo:
        return 0
    client = _anthropic_client()
    found = 0
    for company in todo:
        try:
            found += sum(is_new for _, is_new in web_search.run_for_company(client, conn, company))
        except Exception:  # noqa: BLE001 -- one failed search shouldn't stop the others
            continue
    return found


def _int_arg(parts: list[str], index: int, default: int | None = None) -> int | None:
    return int(parts[index]) if len(parts) > index and parts[index].isdigit() else default


def handle_command(conn, text: str, send=telegram_client.send_message) -> None:
    parts = text.strip().split()
    command = parts[0].split("@")[0].lower() if parts else ""

    if command == "/status":
        send(queue.build_status_text(conn))
    elif command == "/more":
        sent = propose_batch(conn, _anthropic_client(), _int_arg(parts, 1, 5), send)
        if sent == 0:
            reason = "today's limit is used up" if daily_cap.remaining_today(conn) == 0 else "no Colorado/Virginia postings are waiting"
            send(f"Nothing sent - {reason}. That's normal: almost no posting is open to a high schooler, "
                 "which is why the daily five are people, not postings.")
    elif command == "/pitch":
        if send_drafts(conn, _int_arg(parts, 1, 5), send) == 0:
            send("No drafts made - no follow-up is due and nobody left on file has a published email address "
                 "(or today's limit is used up). /linkedin sends cards for the people who have none.\n"
                 "Find more addresses: python -m internship_hunter.people.cli hunter")
    elif command == "/to":
        set_draft_address(conn, parts, send)
    elif command == "/li":
        add_linkedin_person(conn, text, send)
    elif command == "/warm":
        add_warm_person(conn, text, send)
    elif command == "/apply":
        apply_through_link(conn, parts[1] if len(parts) > 1 else "", send)
    elif command == "/linkedin":
        if send_linkedin_cards(conn, _int_arg(parts, 1, 5), send) == 0:
            reason = (
                f"today's {config.LINKEDIN_DAILY_CAP} LinkedIn cards are used up" if linkedin.remaining_today(conn) == 0
                else "everyone on file at a Colorado/Virginia company already has a card or an email"
            )
            send(f"No LinkedIn cards sent - {reason}.\nAdd someone yourself with /li, or find more people: "
                 "python -m internship_hunter.people.cli run")
    elif command in ("/open", "/referral", "/result"):
        application = db.get_application(conn, _int_arg(parts, 1, -1))
        if application is None:
            send(f"Usage: {command} <application id> - /status lists them.")
        elif command == "/open":
            db.update_application_status(conn, application.id, "approved")  # main loop opens approved ones
            send(f"Opening {_describe(conn, application)} on your PC.")
        elif command == "/referral":
            draft_referral(conn, application, send)
        elif len(parts) > 2 and parts[2].lower() in ("interviewing", "rejected"):
            db.update_application_status(conn, application.id, parts[2].lower())
            send(f"Recorded {parts[2].lower()}: {_describe(conn, application)}")
        else:
            send("Usage: /result <application id> interviewing|rejected")
    else:
        send(HELP_TEXT)


def handle_update(conn, update: dict, send=telegram_client.send_message) -> None:
    """Route one Telegram update. Anything not from the student's own chat
    is dropped without a reply."""
    callback_query = update.get("callback_query")
    message = update.get("message")
    chat = ((callback_query or {}).get("message") or message or {}).get("chat", {})
    if str(chat.get("id")) != str(config.TELEGRAM_CHAT_ID):
        return
    if callback_query:
        handle_callback(conn, callback_query, send)
    elif message and message.get("text"):
        handle_command(conn, message["text"], send)


def _local_now(now: datetime | None) -> datetime:
    return now or datetime.now()


def run_daily_prep(conn, send=telegram_client.send_message, now: datetime | None = None) -> bool:
    """Once per calendar day, from an hour before DAILY_RUN_HOUR: read
    every job board (the hiring signal) and look for new people and
    published emails. It takes several minutes and the bot can't answer
    taps meanwhile, which is why it is done before the cards go out, not
    after. Returns True if it ran."""
    now = _local_now(now)
    today_text = now.date().isoformat()
    if now.hour < max(0, config.DAILY_RUN_HOUR - 1) or db.get_meta(conn, "last_prep_run") == today_text:
        return False
    db.set_meta(conn, "last_prep_run", today_text)
    try:
        from internship_hunter.scanner import scan

        scan.run_scan(conn)
    except Exception as exc:  # noqa: BLE001
        send(f"Couldn't scan the job boards today: {exc}")
    try:
        find_new_people(conn, send)
    except Exception as exc:  # noqa: BLE001
        send(f"Couldn't look for new people today: {exc}")
    try:
        find_people_on_the_web(conn)
    except Exception as exc:  # noqa: BLE001
        send(f"Couldn't run today's web search for people: {exc}")
    try:
        find_emails_with_hunter(conn)
    except Exception as exc:  # noqa: BLE001
        send(f"Couldn't look up emails with Hunter today: {exc}")
    return True


def run_daily(conn, send=telegram_client.send_message, today: date | None = None, now: datetime | None = None) -> bool:
    """Once per calendar day, at DAILY_RUN_HOUR (7 AM) or as soon after as
    the PC is on: reminders, today's people to write to, then the status
    update. Returns True if it ran. The date is recorded first so a
    failure partway can't trigger a second batch the same day. (`today`
    alone, as tests pass it, skips the clock check.)"""
    if today is None:
        now = _local_now(now)
        if now.hour < config.DAILY_RUN_HOUR:
            return False
        today = now.date()
    today_text = today.isoformat()
    if db.get_meta(conn, "last_daily_run") == today_text:
        return False
    db.set_meta(conn, "last_daily_run", today_text)
    # No application cards here any more: he asks for those (/more, /apply).
    try:
        send_linkedin_reminders(conn, send, today)
    except Exception as exc:  # noqa: BLE001
        send(f"Couldn't check for reminders today: {exc}")
    try:
        send_daily_outreach(conn, send)
    except Exception as exc:  # noqa: BLE001
        send(f"Couldn't prepare today's people: {exc}")
    send(queue.build_status_text(conn))
    return True


REPLY_CHECK_EVERY_SECONDS = 600


def run_forever(conn) -> None:
    offset = None
    last_reply_check = 0.0
    while True:
        if time.monotonic() - last_reply_check > REPLY_CHECK_EVERY_SECONDS:
            last_reply_check = time.monotonic()
            try:
                check_replies(conn)
            except Exception:  # noqa: BLE001 -- e.g. offline; try again next round
                pass
        try:
            run_daily_prep(conn)
            run_daily(conn)
            updates = telegram_client.get_updates(offset)
        except requests.RequestException:
            time.sleep(10)  # offline or Telegram hiccup -- try again shortly
            continue
        for update in updates:
            offset = update["update_id"] + 1
            try:
                handle_update(conn, update)
            except Exception as exc:  # noqa: BLE001 -- one bad update must not kill the bot
                try:
                    telegram_client.send_message(f"That didn't work: {exc}")
                except Exception:  # noqa: BLE001
                    pass
        for application in db.list_applications(conn, status="approved"):
            open_application(conn, application)
