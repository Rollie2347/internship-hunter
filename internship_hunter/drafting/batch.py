"""Outreach in batches -- the referral side of the tool, and the route most
likely to work: almost no startup posts a high-school internship, so a
short, personal note to a named person is the real way in.

Each run picks the next real people who haven't been written to yet,
composes one email each, and saves every one as a Gmail DRAFT (never sent
-- see gmail_client.py). Emails that were sent 7+ days ago with no reply
get one short follow-up draft. Only companies based in Colorado or Virginia
are pitched (config.PREFERRED_STATES).

Shares the daily budget with application cards (see daily_cap.py).
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from internship_hunter import config, db
from internship_hunter.dashboard import followups
from internship_hunter.drafting import compose, daily_cap, gmail_client
from internship_hunter.models import Company, Contact, Message, Posting
from internship_hunter.outreach import priority


def read_profile() -> tuple[str, str]:
    """(about_me text, resume text). Raises FileNotFoundError if about_me.md
    is missing -- nothing may be drafted without the real profile."""
    if not config.ABOUT_ME_PATH.exists():
        raise FileNotFoundError(f"{config.ABOUT_ME_PATH} doesn't exist -- fill it in first.")
    resume = config.RESUME_PATH_TXT.read_text(encoding="utf-8") if config.RESUME_PATH_TXT.exists() else ""
    return config.ABOUT_ME_PATH.read_text(encoding="utf-8"), resume


def to_address(company: Company, contact: Optional[Contact]) -> Optional[str]:
    """Where a draft is addressed: the person's own published email if we
    have one, else an inbox the company publishes (careers@, info@), else
    blank for the student to fill in. Never a guessed address."""
    if contact is not None and contact.email:
        return contact.email
    return company.contact_email or None


def next_contacts(conn, limit: int, any_state: bool = False) -> list[tuple[Company, Contact]]:
    """People to email next, in outreach/priority.py's order. Only where
    there is a real, published address to send to:
      - a person whose own email is published;
      - a person he couldn't find on LinkedIn, at a company that publishes
        an inbox (careers@, info@);
      - ONE email per company to its published inbox, when nobody there
        has an address of their own and that inbox hasn't been written to
        yet. It is addressed to the best-placed person on file (so whoever
        reads the inbox can pass it on), or to the team if nobody is on
        file -- the Contact in the returned pair is then None. Added
        2026-10-08, when he ran out of free LinkedIn notes and asked for
        more email. One per company because five notes to the same info@
        would be spam.
    Everyone else is reached by LinkedIn (linkedin_assist) -- a draft with a
    blank "To" helps nobody. Only Colorado/Virginia companies unless
    any_state."""
    # One channel per person: anyone with a LinkedIn card is left alone here
    # too -- unless he couldn't find them on LinkedIn, when email is what's left.
    already_written = {
        m.contact_id for m in db.list_messages(conn)
        if m.contact_id and not (m.channel == "linkedin" and m.status == "not_found")
    }
    not_on_linkedin = {
        m.contact_id for m in db.list_messages(conn) if m.channel == "linkedin" and m.status == "not_found"
    }
    inboxes_used = {m.to_email for m in db.list_messages(conn) if m.channel == "email" and m.to_email}
    per_company = []
    for company in priority.companies_in_order(conn, any_state):
        if company.name == config.NETWORK_COMPANY_NAME:
            continue
        everyone = db.list_contacts(conn, company_id=company.id)
        picks = priority.by_role([
            c for c in everyone
            if c.id not in already_written and (c.email or (c.id in not_on_linkedin and company.contact_email))
        ])
        if not picks and company.contact_email and company.contact_email not in inboxes_used \
                and not any(c.email for c in everyone):
            free = priority.by_role([c for c in everyone if c.id not in already_written])
            if free:
                picks = [free[0]]
            elif not everyone:
                picks = [None]   # nobody on file: a note to the team
        per_company.append((company, picks))
    return priority.round_robin(per_company, limit)


def draft_one(
    conn,
    client,
    service,
    profile_text: str,
    resume_text: str,
    company: Company,
    contact: Optional[Contact] = None,
    posting: Optional[Posting] = None,
    ask_type: str = "auto",
    follow_up_context: Optional[str] = None,
) -> tuple[Message, list[str]]:
    """Compose one email, save it as a Gmail draft, record it in the
    tracker. Returns (message, warnings). Enforces the daily cap first."""
    daily_cap.enforce_daily_cap(conn)
    draft = compose.compose_email(
        client, profile_text, resume_text, company, contact=contact, posting=posting,
        ask_type=ask_type, follow_up_context=follow_up_context,
    )
    to_email = to_address(company, contact)
    draft_id = gmail_client.create_draft(service, draft.subject, draft.body, to_email=to_email)
    message = Message(
        company_id=company.id,
        contact_id=contact.id if contact else None,
        posting_id=posting.id if posting else None,
        channel="email",
        subject=draft.subject,
        body=draft.body,
        gmail_draft_id=draft_id,
        status="drafted",
        to_email=to_email,
    )
    message.id = db.insert_message(conn, message)
    return message, compose.validate_draft(draft)


def due_follow_ups(conn, today: Optional[date] = None) -> list[Message]:
    """Sent emails with no reply after 7 days that haven't had a follow-up
    drafted yet. One follow-up per person, ever -- a second nudge to someone
    who didn't answer two emails is pestering, not persistence."""
    messages = db.list_messages(conn)
    due = []
    for message in followups.filter_needing_follow_up(messages, today):
        later = [
            m for m in messages
            if m.id > message.id and m.company_id == message.company_id and m.contact_id == message.contact_id
        ]
        earlier = [
            m for m in messages
            if m.id < message.id and m.company_id == message.company_id and m.contact_id == message.contact_id
        ]
        if not later and not earlier:
            due.append(message)
    return due


def draft_batch(conn, client, service, limit: int, today: Optional[date] = None) -> list[dict]:
    """Draft up to `limit` emails (never more than today's remaining
    budget): follow-ups that are due first, then new cold pitches. Returns
    one dict per draft: company, contact, message, warnings, kind."""
    profile_text, resume_text = read_profile()
    limit = min(limit, daily_cap.remaining_today(conn))
    created: list[dict] = []
    companies = {c.id: c for c in db.list_companies(conn)}
    contacts = {c.id: c for c in db.list_contacts(conn)}

    for original in due_follow_ups(conn, today)[:limit]:
        company, contact = companies[original.company_id], contacts.get(original.contact_id)
        message, warnings = draft_one(
            conn, client, service, profile_text, resume_text, company, contact=contact,
            follow_up_context=followups.build_follow_up_context(original, today),
        )
        created.append(dict(company=company, contact=contact, message=message, warnings=warnings, kind="follow-up"))

    for company, contact in next_contacts(conn, limit - len(created)):
        # A first note asks for a short call, never a job: the aim is to turn a
        # stranger into someone who knows him well enough to refer him.
        message, warnings = draft_one(
            conn, client, service, profile_text, resume_text, company, contact=contact, ask_type="call",
        )
        created.append(dict(company=company, contact=contact, message=message, warnings=warnings, kind="pitch"))
    return created
