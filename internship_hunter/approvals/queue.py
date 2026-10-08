"""The approval queue: which postings to put in front of the student next,
what each Telegram card says, and the status summary. Everything in this
file is plain logic over the database -- no Telegram, browser, or Claude
calls -- so it's all unit-testable (see tests/test_approval_queue.py).

The flow, end to end:
    proposed  -> a card is sent to Telegram with Approve / Skip buttons
    approved  -> the bot opens the real form in a browser, already filled in
    submitted -> the student pressed Submit himself; the 7-day clock starts
See approvals/bot.py for the part that talks to Telegram.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from internship_hunter import config, db
from internship_hunter.apply_assist import field_map
from internship_hunter.dashboard import followups
from internship_hunter.models import Application, Company, Posting
from internship_hunter.scanner import filters

SKILL_ORDER = {"strong": 0, "stretch": 1, "unclear": 2}
MAX_ANSWER_PREVIEW_CHARS = 600


def next_postings(conn, limit: int) -> list[Posting]:
    """The next `limit` postings to propose, best first: company tier
    (defense startups first), then skill fit, then newest. Only postings
    with an office in Colorado or Virginia qualify -- see
    config.QUEUE_MAX_LOCATION_RANK."""
    tiers = {c.id: c.priority_tier for c in db.list_companies(conn)}
    candidates = [
        p for p in db.list_postings_not_yet_proposed(conn)
        if filters.location_rank(p.location) <= config.QUEUE_MAX_LOCATION_RANK
        and not filters.is_closed_to_high_schoolers(p.title)
        and not filters.title_is_non_software(p.title)
    ]
    candidates.sort(
        key=lambda p: (
            tiers.get(p.company_id, 9),
            filters.location_rank(p.location),
            SKILL_ORDER.get(p.skill_match, 3),
        )
    )
    return candidates[:limit]


def count_skipped_for_location(conn) -> int:
    return sum(
        1 for p in db.list_postings_not_yet_proposed(conn)
        if filters.location_rank(p.location) > config.QUEUE_MAX_LOCATION_RANK
    )


def display_location(location: str, max_len: int = 120) -> str:
    """What the card shows as the location: just the Colorado/Virginia
    offices, with a count of the rest. A posting that lists nine cities used
    to show the first few -- Atlanta, Boston -- and look like the wrong place."""
    offices = filters.offices_in_preferred_states(location)
    total = len([p for p in location.replace("|", ";").split(";") if p.strip()])
    if offices:
        shown = "; ".join(o.replace(", United States", "") for o in offices)
        others = total - len(offices)
        text = shown + (f" (also offered in {others} other cities, which I ignore)" if others > 0 else "")
    else:
        text = location
    return text if len(text) <= max_len else text[: max_len - 1].rstrip() + "..."


def build_card_text(
    application_id: int,
    company: Company,
    posting: Posting,
    filled_labels: list[str],
    answers: dict[str, str],
    left_for_you: list[str],
    resume_available: bool,
    warnings: Optional[list[str]] = None,
    selections: Optional[dict[str, str]] = None,
    new_questions: int = 0,
) -> str:
    """The Telegram message for one proposed application: what will be
    typed into the form if he approves, word for word, and what he still
    has to answer himself in the browser."""
    lines = [
        f"\U0001F4DD Application #{application_id}",
        f"{company.name} — {posting.title}",
        f"\U0001F4CD {display_location(posting.location) or 'location not listed'}",
        posting.url,
        "",
        "Will be filled in: " + (", ".join(filled_labels) if filled_labels else "nothing recognized")
        + (" + resume attached" if resume_available else " (no resume.pdf on file to attach)"),
    ]
    if selections:
        lines += ["", "Will be selected:"]
        lines += [f"  • {question[:70]} → {answer}" for question, answer in selections.items()]
    for question, answer in answers.items():
        preview = answer if len(answer) <= MAX_ANSWER_PREVIEW_CHARS else answer[:MAX_ANSWER_PREVIEW_CHARS] + "…"
        lines += ["", f"Q: {question}", f"A: {preview}"]
    if left_for_you:
        shown = left_for_you[:12]
        more = f" (+{len(left_for_you) - len(shown)} more)" if len(left_for_you) > len(shown) else ""
        lines += ["", "You answer in the browser: " + "; ".join(l[:60] for l in shown) + more]
    for warning in warnings or []:
        lines.append(f"⚠️ {warning}")
    if new_questions:
        lines.append(
            f"{new_questions} of these are new to me. I added them to profile/my_answers.md - answer them "
            "there (or just pick them in the browser once) and I'll fill them in from then on."
        )
    lines += ["", "Approve opens the filled-in form on your PC. You press Submit."]
    return "\n".join(lines)


def card_buttons(application_id: int) -> list[list[tuple[str, str]]]:
    return [[("✅ Approve", f"approve:{application_id}"), ("❌ Skip", f"skip:{application_id}")]]


def submitted_buttons(application_id: int) -> list[list[tuple[str, str]]]:
    return [[("✅ I submitted it", f"submitted:{application_id}"), ("Not yet", f"notyet:{application_id}")]]


# approve/skip/submitted/notyet/referral carry an application id;
# send/sent/replied carry an outreach message id (see drafting/batch.py);
# li_* carry the message id of a LinkedIn card (see linkedin_assist/assist.py).
LINKEDIN_ACTIONS = ("li_sent", "li_skip", "li_nf", "li_replied")
# st_* carry the message id of any outreach that got a reply: what happened next.
STAGE_ACTIONS = ("st_call", "st_ref", "st_no")
CALLBACK_ACTIONS = (
    ("approve", "skip", "submitted", "notyet", "referral", "send", "sent", "replied") + LINKEDIN_ACTIONS + STAGE_ACTIONS
)


def stage_buttons(message_id: int, after_call: bool = False) -> list[list[tuple[str, str]]]:
    """Under anything that got a reply: record how far it went."""
    row = [] if after_call else [("\U0001F4DE Call booked", f"st_call:{message_id}")]
    return [row + [("\U0001F91D They referred me", f"st_ref:{message_id}")], [("It went nowhere", f"st_no:{message_id}")]]


# How far one person has got, across every channel. Each stage includes the
# ones after it: someone who referred him also "replied".
STAGE_RANK = {"sent": 1, "replied": 2, "rejected": 2, "call": 3, "interviewing": 3, "referred": 4}
OUTREACH_CHANNELS = ("email", "linkedin", "other")


def funnel(messages) -> dict[str, int]:
    """The referral pipeline in four numbers: people contacted, who
    replied, calls, referrals."""
    furthest: dict = {}
    for m in messages:
        if m.channel not in OUTREACH_CHANNELS:
            continue
        person = m.contact_id if m.contact_id else ("message", m.id)
        furthest[person] = max(furthest.get(person, 0), STAGE_RANK.get(m.status, 0))
    reached = lambda rank: sum(1 for r in furthest.values() if r >= rank)
    return {"contacted": reached(1), "replied": reached(2), "calls": reached(3), "referrals": reached(4)}


def draft_buttons(message_id: int) -> list[list[tuple[str, str]]]:
    """Under an outreach draft: Send it now from Telegram, or say it was
    sent by hand from Gmail."""
    return [[("Send now", f"send:{message_id}")], [("I sent it from Gmail myself", f"sent:{message_id}")]]


def reply_buttons(message_id: int) -> list[list[tuple[str, str]]]:
    return [[("\U0001F4AC They replied", f"replied:{message_id}")]]


def referral_buttons(application_id: int) -> list[list[tuple[str, str]]]:
    return [[("✉️ Draft a referral email", f"referral:{application_id}")]]


def parse_callback(data: str) -> Optional[tuple[str, int]]:
    """'approve:12' -> ('approve', 12). None for anything malformed, so a
    stray or stale button press can never crash the bot."""
    action, _, raw_id = (data or "").partition(":")
    if action not in CALLBACK_ACTIONS or not raw_id.isdigit():
        return None
    return action, int(raw_id)


def days_since_submitted(application: Application, today: Optional[date] = None) -> Optional[int]:
    if not application.submitted_at:
        return None
    today = today or date.today()
    submitted = datetime.strptime(application.submitted_at.split(" ")[0], "%Y-%m-%d").date()
    return (today - submitted).days


def waiting_too_long(applications: list[Application], today: Optional[date] = None) -> list[Application]:
    """Submitted 7+ days ago and still no interview or rejection recorded
    -- time to nudge a real person at that company."""
    return [
        a for a in applications
        if a.status == "submitted" and (days_since_submitted(a, today) or 0) >= config.FOLLOW_UP_AFTER_DAYS
    ]


def build_status_text(conn, today: Optional[date] = None) -> str:
    """The update pushed to Telegram each morning and on /status."""
    from internship_hunter.drafting import batch, daily_cap
    from internship_hunter.linkedin_assist import assist as linkedin

    applications = db.list_applications(conn)
    counts = {status: 0 for status in config.APPLICATION_STATUSES}
    for a in applications:
        counts[a.status] = counts.get(a.status, 0) + 1
    all_messages = db.list_messages(conn)
    messages = [m for m in all_messages if m.channel == "email"]
    cards = [m for m in all_messages if m.channel in linkedin.MANUAL_CHANNELS]
    steps = funnel(all_messages)
    people_left = len(batch.next_contacts(conn, 10_000)) + len(linkedin.next_contacts(conn, 10_000))
    emails_due = batch.due_follow_ups(conn, today)
    stale = waiting_too_long(applications, today)
    ruled_out = conn.execute("SELECT COUNT(*) AS n FROM postings WHERE eligibility = 'not_eligible'").fetchone()["n"]

    lines = [
        "\U0001F4CA Internship Hunter - the referral pipeline",
        f"People contacted: {steps['contacted']} \u2192 replied: {steps['replied']} \u2192 "
        f"calls: {steps['calls']} \u2192 referrals: {steps['referrals']}",
        f"Today: {daily_cap.outreach_today(conn)} of {config.OUTREACH_PER_DAY} sent to you. "
        f"{people_left} more people on file to write to.",
        f"Waiting on you: {sum(1 for m in messages if m.status == 'drafted' and m.to_email)} email draft(s) to send, "
        f"{sum(1 for m in cards if m.status == 'drafted')} LinkedIn card(s)/note(s) to act on",
        f"Waiting on them: {sum(1 for m in messages if m.status == 'sent')} email(s), "
        f"{sum(1 for m in cards if m.status == 'sent')} LinkedIn request(s)/note(s) with no answer yet",
        "",
        f"Applications (only when you ask - /more, /apply): {counts['submitted']} submitted, "
        f"{counts['interviewing']} interviewing, {counts['rejected']} rejected; "
        f"{counts['proposed']} to approve/skip, {counts['approved'] + counts['opened']} approved but not submitted",
        f"Postings: {len(next_postings(conn, 10_000))} Colorado/Virginia posting(s) you could ask for, "
        f"{ruled_out} ruled out after reading the requirements",
    ]
    if stale:
        lines.append(f"\n⏰ {len(stale)} application(s) submitted 7+ days ago with no word:")
        for a in stale[:10]:
            posting = db.get_posting(conn, a.posting_id)
            company = db.get_company(conn, posting.company_id) if posting else None
            lines.append(f"  #{a.id} {company.name if company else '?'} — {posting.title if posting else '?'} "
                         f"({days_since_submitted(a, today)} days) → /referral {a.id}")
    if emails_due:
        lines.append(f"\n⏰ {len(emails_due)} sent email(s) with no reply after 7 days — a follow-up comes with the next daily batch (or /pitch).")
    return "\n".join(lines)


def expected_filled_labels(labels: list[str], applicant) -> list[str]:
    return [label for label, _ in field_map.build_fill_plan(labels, applicant)]
