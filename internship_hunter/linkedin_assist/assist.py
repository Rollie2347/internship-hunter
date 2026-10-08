"""LinkedIn assist: everything short of touching LinkedIn.

LinkedIn's terms ban automation, so this module never logs into, requests,
or reads linkedin.com (CLAUDE.md constraint 4) -- it has no HTTP library
imported at all, and a test fails if one ever appears. What it does:

  - builds a people-search LINK from a contact's name + company. It is
    only text in a Telegram message; the student is the one who opens it.
  - drafts a connection note (under 200 characters, config.LINKEDIN_NOTE_MAX_CHARS) from his real profile
    and the one sourced fact on file about the person.
  - keeps the tracker: a card is a `messages` row with channel "linkedin".
        drafted   -> card sent to Telegram
        sent      -> he tapped "Sent on LinkedIn" (the 7-day clock starts)
        replied   -> he tapped "Replied"; a short follow-up is drafted
        skipped / not_found -> he passed, or couldn't find the profile
  - picks who gets a card, at most LINKEDIN_DAILY_CAP (10) a day -- a
    budget of its own, separate from the email/application cap.

The Telegram side (sending cards, handling taps, /li) is in approvals/bot.py.
"""

from __future__ import annotations

import difflib
import re
from datetime import date
from typing import Optional
from urllib.parse import quote_plus, urlparse

from pydantic import BaseModel

from internship_hunter import anthropic_client, config, db
from internship_hunter.dashboard import followups
from internship_hunter.models import Company, Contact, Message
from internship_hunter.outreach import priority

CHANNEL = "linkedin"
REPLY_CHANNEL = "linkedin_reply"  # the follow-up he pastes after they accept/reply
# Channels where he does the sending and tells the bot with a button: a
# LinkedIn card, or a note pasted somewhere else (outreach/paste.py).
MANUAL_CHANNELS = (CHANNEL, "other")
SEARCH_URL = "https://www.linkedin.com/search/results/people/?keywords="
# A personal profile link, e.g. https://www.linkedin.com/in/jane-doe-123/
PROFILE_PATH_RE = re.compile(r"^/in/[^/]+/?$")


# --- Links (strings only -- nothing here is ever requested) ----------------

def search_url(name: str, company_name: str) -> str:
    # "Dr." and ", PhD" aren't part of how LinkedIn lists a name, and make the search miss.
    plain = re.sub(r"^(dr|mr|mrs|ms|prof)\.?\s+", "", name.strip(), flags=re.IGNORECASE)
    plain = re.sub(r",?\s+(ph\.?d\.?|jr\.?|sr\.?)$", "", plain, flags=re.IGNORECASE)
    return SEARCH_URL + quote_plus(f"{plain} {company_name}".strip())


def clean_profile_url(text: str) -> Optional[str]:
    """A pasted LinkedIn profile URL, tidied (no tracking query string), or
    None if it isn't one."""
    raw = (text or "").strip().strip("<>")
    parsed = urlparse(raw if "//" in raw else f"https://{raw}")
    host = parsed.netloc.lower()
    if host != "linkedin.com" and not host.endswith(".linkedin.com"):
        return None
    if not PROFILE_PATH_RE.match(parsed.path):
        return None
    return f"https://www.linkedin.com{parsed.path.rstrip('/')}"


def link_for(contact: Contact, company: Company) -> str:
    """His own pasted profile link if there is one, else a search link."""
    return contact.linkedin_url or search_url(contact.name, company.name)


# --- The daily cap ---------------------------------------------------------

def cards_today(conn) -> int:
    return conn.execute(
        "SELECT COUNT(*) AS n FROM messages WHERE channel = ? AND date(created_at) = date('now')", (CHANNEL,)
    ).fetchone()["n"]


def remaining_today(conn, cap: Optional[int] = None) -> int:
    cap = cap if cap is not None else config.LINKEDIN_DAILY_CAP
    return max(0, cap - cards_today(conn))


# --- Who gets a card -------------------------------------------------------

def _free_for_linkedin(messages: list[Message]) -> bool:
    """One channel per person: someone who has been emailed, or has a draft
    with an address on it waiting, doesn't also get a LinkedIn request. An
    email draft with a blank "To" can't go anywhere, so it doesn't count."""
    return all(m.channel == "email" and m.status == "drafted" and not m.to_email for m in messages)


def next_contacts(conn, limit: int) -> list[tuple[Company, Contact]]:
    """The next people to make cards for, in outreach/priority.py's order.
    Someone whose own email is published is left to the email side -- a
    direct email beats a connection request."""
    by_contact: dict[int, list[Message]] = {}
    for message in db.list_messages(conn):
        if message.contact_id:
            by_contact.setdefault(message.contact_id, []).append(message)
    per_company = [
        (company, priority.by_role([
            c for c in db.list_contacts(conn, company_id=company.id)
            if not c.email and _free_for_linkedin(by_contact.get(c.id, []))
        ]))
        for company in priority.companies_in_order(conn)
    ]
    return priority.round_robin(per_company, limit)


def has_card(conn, contact_id: int) -> bool:
    return any(m.contact_id == contact_id and m.channel == CHANNEL for m in db.list_messages(conn))


# --- Drafting --------------------------------------------------------------

class DraftNote(BaseModel):
    note: str


NOTE_SYSTEM_PROMPT = """You are helping a 15-year-old high school student write the note that goes \
with a LinkedIn connection request to someone at a tech/defense-tech company. He will read it and \
send it himself. Follow these rules exactly:

1. HARD LIMIT: the whole note is under {max_chars} characters, counting spaces. Aim for about \
{target} so there is room to spare. LinkedIn cuts off anything longer. That is only two or \
three short sentences, so every word has to earn its place: no greeting, no "I'm reaching out".
2. Say plainly that he is 15 and in high school. Never imply he is older, in college, or working \
professionally. This is the hook, not something to soften.
3. Say why he is writing: he is looking for an internship so he can LEARN -- and name what he \
wants to learn, which should be the kind of work this person does. He asked for this himself: it \
must be clear he wants an internship, and that the point of it is learning.
4. Mention ONE specific thing about this person's work, taken only from the "fact about them" \
below. Don't just repeat their job title back to them ("You're the CTO at X") -- say what about \
their work he wants to learn from. If no fact is given, use one specific thing the company builds. \
Never add anything about the person that isn't written below.
5. Name ONE of his real projects from the profile that fits this person's work, in a few words, as \
proof he already builds things. Never invent a project, a result, or a skill. No links -- there is \
no room.
6. End with ONE soft ask, e.g. whether he could ask them a question or two. He says he is looking \
for an internship, but he does not ask this person to give him one or to refer him -- not yet.
If all of that will not fit, keep in this order: his age, internship-to-learn, the specific thing, \
the ask, then the project in as few words as it takes.
7. His voice: direct, specific, a little technical. No buzzwords, no exclamation marks, no emoji, \
no "I'd love to".
8. Plain text only: no greeting line break, no signature, no placeholders like [Name]."""

REPLY_SYSTEM_PROMPT = """You are helping a 15-year-old high school student write a short \
message to someone who just accepted his LinkedIn connection request or replied to a note he sent. \
He will paste it himself. Follow these rules exactly:

1. Under {max_chars} characters in total, counting spaces.
2. Thank them briefly, then say what he is after: a year-long, in-person software internship so \
he can learn from people doing this work, and that he is 15 and in high school.
3. Use the exact "Availability" fact given below (light rewording for flow is fine, but never \
change the hours, dates or age it states).
4. Include exactly ONE link to one of his real projects, copied character-for-character from the \
profile. Never invent or alter a URL.
5. End with ONE clear, low-pressure ask: whether they'd be open to a 15-minute call, or could point \
him to whoever handles internships. Not both.
6. Only use what is written below about the person and company. His voice: direct and specific, \
no buzzwords, no exclamation marks, no emoji.
7. Plain text only, no placeholders like [Name]."""


def build_note_context(profile_text: str, resume_text: str, company: Company, contact: Contact) -> str:
    fact = contact.fact.strip() or "(none on file -- use what the company builds instead)"
    return (
        f"=== His profile (about_me.md) ===\n{profile_text}\n\n"
        f"=== His resume ===\n{resume_text}\n\n"
        f"=== Who the note is for ===\n"
        f"Name: {contact.name}\nTitle: {contact.title}\nCompany: {company.name}\n"
        f"What the company builds: {company.what_they_build}\n"
        f"Fact about them (the only thing known about this person): {fact}"
    )


def draft_note(client, profile_text: str, resume_text: str, company: Company, contact: Contact) -> str:
    """One connection note. If the first try is too long the model is told
    by how much and gets one more go; the result is returned either way,
    never cut short here -- a note chopped mid-sentence is worse than one
    he trims himself (validate_note flags it on the card)."""
    limit = config.LINKEDIN_NOTE_MAX_CHARS
    system = NOTE_SYSTEM_PROMPT.format(max_chars=limit, target=config.LINKEDIN_NOTE_TARGET_CHARS)
    messages = [{"role": "user", "content": build_note_context(profile_text, resume_text, company, contact)}]
    note = ""
    for _ in range(2):
        response = client.messages.parse(
            model=config.DRAFTING_MODEL, max_tokens=config.MAX_OUTPUT_TOKENS, system=system, messages=messages, output_format=DraftNote,
        )
        note = " ".join(anthropic_client.parsed(response).note.split())
        if len(note) < limit:
            break
        messages = messages[:1] + [
            {"role": "assistant", "content": note},
            {"role": "user", "content": f"That is {len(note)} characters. Rewrite it to be under {config.LINKEDIN_NOTE_TARGET_CHARS}, keeping "
                                        "his age, the one specific thing about them, the one project and the ask."},
        ]
    return note


def validate_note(note: str) -> list[str]:
    """Warnings shown on the card. Never blocks: he reads every note anyway."""
    warnings = []
    limit = config.LINKEDIN_NOTE_MAX_CHARS
    if len(note) >= limit:
        warnings.append(f"{len(note)} characters - LinkedIn stops at {limit}, so trim it before sending.")
    if "15" not in note and "fifteen" not in note.lower():
        warnings.append("Doesn't mention that you're 15 - add it before sending.")
    return warnings


def draft_reply(client, profile_text: str, resume_text: str, company: Company, contact: Optional[Contact], note: str) -> str:
    """The short message to paste once they've accepted or replied."""
    who = f"Name: {contact.name}\nTitle: {contact.title}\n" if contact else ""
    content = (
        f"=== His profile (about_me.md) ===\n{profile_text}\n\n"
        f"=== His resume ===\n{resume_text}\n\n"
        f"=== Who it is for ===\n{who}Company: {company.name}\nWhat the company builds: {company.what_they_build}\n"
        + (f"Fact about them: {contact.fact}\n" if contact and contact.fact else "")
        + f"\n=== The connection note he already sent them ===\n{note}\n\n"
        f"=== Availability (use this fact, don't recompute it) ===\n{config.availability_statement()}"
    )
    response = client.messages.parse(
        model=config.DRAFTING_MODEL, max_tokens=config.MAX_OUTPUT_TOKENS,
        system=REPLY_SYSTEM_PROMPT.format(max_chars=config.LINKEDIN_REPLY_MAX_CHARS),
        messages=[{"role": "user", "content": content}], output_format=DraftNote,
    )
    return anthropic_client.parsed(response).note.strip()


# --- Cards and buttons ----------------------------------------------------

def card_buttons(message_id: int, link: str = "", name: str = "") -> list[list[tuple[str, str]]]:
    """Under the note. The first button is a plain link to the LinkedIn
    search (or the profile he pasted): he taps it and his phone opens it.
    The bot itself still never requests that address."""
    rows = [
        [("✅ Sent on LinkedIn", f"li_sent:{message_id}")],
        [("Skip", f"li_skip:{message_id}"), ("Not found", f"li_nf:{message_id}")],
    ]
    if link:
        rows.insert(0, [(f"\U0001F50E Find {name or 'them'} on LinkedIn", link)])
    return rows


def replied_buttons(message_id: int) -> list[list[tuple[str, str]]]:
    return [[("\U0001F4AC Replied", f"li_replied:{message_id}")]]


def build_card_text(
    message_id: int, company: Company, contact: Contact, note: str, warnings: list[str], hiring: str = "",
) -> str:
    """The first of a card's two Telegram messages: the person, why them,
    the link. The note follows as a message of its own (with the buttons),
    so that pressing and holding it copies the note and nothing else --
    the bot may not paste it into LinkedIn for him, but it can make the
    copying one move."""
    own_link = bool(contact.linkedin_url)
    if contact.fact:
        why = f"Why them: {contact.fact}\nSource: {contact.source_url}"
    else:
        why = f"Why them: you found them yourself. {company.name} builds {company.what_they_build}"
    lines = [
        f"\U0001F91D LinkedIn #{message_id}",
        f"{contact.name} — {contact.title or 'title unknown'}, {company.name}",
        why,
        *([hiring] if hiring else []),
        "",
        ("Their profile (the link you gave me):" if own_link else "Find them (a search link - I never open it):"),
        link_for(contact, company),
        "",
    ]
    lines += [f"⚠️ {w}" for w in warnings]
    if company.state not in config.PREFERRED_STATES:
        lines.append(f"⚠️ {company.name} isn't based in Colorado or Virginia.")
    lines.append(
        f"The note is the next message ({len(note)} of {config.LINKEDIN_NOTE_MAX_CHARS} characters). Press and hold it "
        "to copy, open the link, check it's the right person, send the request yourself, then tap a button."
    )
    return "\n".join(lines)


def new_card(conn, company: Company, contact: Contact, note: str) -> Message:
    """Record a card in the tracker. Raises if today's cap is already used."""
    if remaining_today(conn) <= 0:
        raise RuntimeError(f"Already sent you {cards_today(conn)} LinkedIn card(s) today (cap is {config.LINKEDIN_DAILY_CAP}).")
    message = Message(
        company_id=company.id, contact_id=contact.id, channel=CHANNEL,
        subject=f"LinkedIn note to {contact.name}", body=note, status="drafted",
    )
    message.id = db.insert_message(conn, message)
    return message


# --- The 7-day reminder ----------------------------------------------------

def due_reminders(conn, today: Optional[date] = None) -> list[Message]:
    """Requests marked sent 7+ days ago, with no reply recorded, that he
    hasn't been reminded about. Each is only ever returned until
    db.mark_message_reminded is called -- one reminder, once."""
    due = []
    for message in db.list_messages(conn, status="sent"):
        if message.channel not in MANUAL_CHANNELS or message.reminded_at:
            continue
        days = followups.days_since_sent(message, today)
        if days is not None and days >= config.FOLLOW_UP_AFTER_DAYS:
            due.append(message)
    return due


# --- /li: someone he found himself ----------------------------------------

class ManualPerson(BaseModel):
    profile_url: str
    name: str
    title: str
    company: str
    fact: str = ""


LI_USAGE = (
    "Add someone you found yourself:\n"
    "/li <their LinkedIn profile link> Name, Title, Company\n"
    "Optional second line: one thing you noticed about their work (in your own words).\n\n"
    "Example:\n"
    "/li https://www.linkedin.com/in/jane-doe Jane Doe, Staff Engineer, Foo Robotics\n"
    "Wrote the post about their drone autonomy stack\n\n"
    "/linkedin [n] sends the next n cards from people already on file."
)


def parse_li_command(text: str) -> Optional[ManualPerson]:
    """'/li <url> Name, Title, Company' (+ optional second line: a fact in
    his own words). The first comma ends the name and the last one starts
    the company, so a title like "VP, Engineering" survives. None if it
    doesn't fit."""
    first_line, _, rest = (text or "").strip().partition("\n")
    parts = first_line.split(maxsplit=2)
    if len(parts) < 3:
        return None
    profile_url = clean_profile_url(parts[1])
    fields = [f.strip() for f in parts[2].split(",")]
    if profile_url is None or len(fields) < 3 or not fields[0] or not fields[-1]:
        return None
    return ManualPerson(
        profile_url=profile_url, name=fields[0], title=", ".join(f for f in fields[1:-1] if f),
        company=fields[-1], fact=" ".join(rest.split()),
    )


def find_company(conn, name: str) -> tuple[Optional[Company], list[str]]:
    """(the company on the target list with that name, ignoring case; or
    None plus up to three close names to suggest)."""
    companies = db.list_companies(conn)
    wanted = name.strip().lower()
    for company in companies:
        if company.name.lower() == wanted:
            return company, []
    by_lower = {c.name.lower(): c.name for c in companies}
    close = difflib.get_close_matches(wanted, list(by_lower), n=3, cutoff=0.6)
    contains = [original for lower, original in by_lower.items() if wanted and wanted in lower]
    return None, list(dict.fromkeys(contains + [by_lower[c] for c in close]))[:3]
