"""Notes the student sends some other way -- channel "other" in the tracker.

Two cases, both ending in a message he copies and sends himself:

  - The fallback. He couldn't find someone on LinkedIn and nobody has
    published an email for them, so the note goes through the company's
    website contact form, or wherever else he can reach them.
  - People he already knows (/warm): a relative in Colorado, a robotics
    mentor, a parent's colleague. A referral nearly always comes from
    someone who can vouch for you, so these go first. They aren't asked for
    a job -- they're asked who he should talk to.

Like linkedin_assist, this module only writes text. It sends nothing.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from internship_hunter import anthropic_client, config, db
from internship_hunter.models import Company, Contact, Message

CHANNEL = "other"

FALLBACK_SYSTEM_PROMPT = """You are helping a 15-year-old high school student write a short note to \
someone at a tech/defense-tech company. He could not find a direct way to reach them, so he will \
paste this into the company's website contact form himself. Follow these rules exactly:

1. Under {max_words} words. Open with "For <their name>" so whoever reads the form can pass it on.
2. Say plainly that he is 15 and in high school. Never imply he is older or in college.
2a. Say why he is writing: he is looking for a year-long internship so he can LEARN, and name what \
he wants to learn -- the kind of work this person or company does.
3. Mention ONE specific thing about this person's or company's work, taken only from the facts \
below. Never add anything that isn't written there.
4. Include exactly ONE link to one of his real projects, copied character-for-character from the \
profile. Never invent or alter a URL. Then add one short clause saying he has built other projects too and would be glad \
to show them -- once, without listing them.
5. Do NOT mention work-hour limits, labor rules for his age, part-time or full-time, or when he \
turns 16. He asked for this himself: that is for a conversation, not a first message. Still say \
plainly that he is 15, and never say or imply anything about when he can work that contradicts \
the "Background only" fact below.
6. End with ONE ask: a 15-minute call to ask about their work. He says he is looking for an \
internship, but he does not ask this person to give him one or to refer him.
7. His voice: direct, specific, a little technical. No buzzwords, no exclamation marks.
8. Plain text only, no placeholders like [Name]."""

WARM_SYSTEM_PROMPT = """You are helping a 15-year-old high school student write a short, friendly \
message to someone he ALREADY KNOWS personally. He will send it himself (text, email, or in person). \
Follow these rules exactly:

1. Under {max_words} words, in the tone you'd use with someone you know -- warm, not formal.
2. How he knows them is given below in his own words. Don't add any shared history that isn't there.
3. Say what he is looking for: a year-long, in-person software internship at a defense-tech, \
robotics or AI company in Colorado or Virginia, where he has family to live with -- and that the \
point of it is to learn from people doing that work.
4. Do NOT mention work-hour limits, labor rules for his age, part-time or full-time, or when he \
turns 16. He asked for this himself: that is for a conversation, not a first message. Still say \
plainly that he is 15, and never say or imply anything about when he can work that contradicts \
the "Background only" fact below.
5. Mention ONE of his real projects in a few words, with its link copied character-for-character \
from the profile. Never invent a project or a URL. Then add one short clause saying he has built other projects too and would be glad \
to show them -- once, without listing them.
6. The ask is NOT for a job. Ask ONE thing: whether they know anyone working in that world he \
should talk to, and if so whether they'd be willing to introduce him.
7. Plain text only, no placeholders like [Name]."""


class DraftMessage(BaseModel):
    message: str


def draft_message(client, profile_text: str, resume_text: str, company: Company, contact: Contact, warm: bool = False) -> str:
    if warm:
        who = f"Name: {contact.name}\nHow he knows them (his own words): {contact.fact}\n"
        if contact.title:
            who += f"Where they work / what they do: {contact.title}\n"
    else:
        who = (
            f"Name: {contact.name}\nTitle: {contact.title}\nCompany: {company.name}\n"
            f"What the company builds: {company.what_they_build}\n"
            f"Fact about them: {contact.fact or '(none on file -- use what the company builds)'}\n"
        )
    content = (
        f"=== His profile (about_me.md) ===\n{profile_text}\n\n"
        f"=== His resume ===\n{resume_text}\n\n"
        f"=== Who it is for ===\n{who}\n"
        f"=== Background only -- never put any of this in the message ===\n{config.availability_statement()}"
    )
    system = (WARM_SYSTEM_PROMPT if warm else FALLBACK_SYSTEM_PROMPT).format(max_words=config.PASTE_MESSAGE_MAX_WORDS)
    response = client.messages.parse(
        model=config.DRAFTING_MODEL, max_tokens=config.MAX_OUTPUT_TOKENS, system=system,
        messages=[{"role": "user", "content": content}], output_format=DraftMessage,
    )
    return anthropic_client.parsed(response).message.strip()


def validate_message(text: str) -> list[str]:
    warnings = []
    words = len(text.split())
    if words > config.PASTE_MESSAGE_MAX_WORDS:
        warnings.append(f"{words} words, over the {config.PASTE_MESSAGE_MAX_WORDS}-word target.")
    if "15" not in text and "fifteen" not in text.lower():
        warnings.append("Doesn't mention that you're 15 - add it before sending.")
    return warnings


def new_message(conn, company: Company, contact: Contact, text: str, warm: bool = False) -> Message:
    message = Message(
        company_id=company.id, contact_id=contact.id, channel=CHANNEL,
        subject=("Note to someone you know: " if warm else "Contact-form note to ") + contact.name,
        body=text, status="drafted",
    )
    message.id = db.insert_message(conn, message)
    return message


def buttons(message_id: int) -> list[list[tuple[str, str]]]:
    # The same taps as a LinkedIn card: the handler works on either channel.
    return [[("✅ I sent it", f"li_sent:{message_id}"), ("Skip", f"li_skip:{message_id}")]]


def build_fallback_card_text(message_id: int, company: Company, contact: Contact, text: str, warnings: list[str]) -> str:
    lines = [
        f"✉️ Note #{message_id} - another way to reach {contact.name} ({contact.title or 'title unknown'}, {company.name})",
        "Nobody has published an email for them, so this one is for the company's contact form "
        f"(or anywhere else you can reach them): {company.website or 'no website on file'}",
        "",
        text,
        "",
    ]
    lines += [f"⚠️ {w}" for w in warnings]
    lines.append("Paste it and send it yourself, then tap below.")
    return "\n".join(lines)


def build_warm_card_text(message_id: int, contact: Contact, text: str, warnings: list[str]) -> str:
    lines = [
        f"\U0001F44B Note #{message_id} - for {contact.name}, someone you know ({contact.fact})",
        "People who know you are where referrals come from. This asks who you should talk to, not for a job.",
        "",
        text,
        "",
    ]
    lines += [f"⚠️ {w}" for w in warnings]
    lines.append("Change it until it sounds like you, send it however you'd normally reach them, then tap below.")
    return "\n".join(lines)


# --- /warm: someone he already knows ----------------------------------------

WARM_USAGE = (
    "Add someone you already know who might point you to people:\n"
    "/warm Name, how you know them, where they work (optional)\n\n"
    "Example:\n"
    "/warm Tom Reyes, my uncle in Denver, engineer at a satellite company"
)


class WarmPerson(BaseModel):
    name: str
    relationship: str
    works_at: str = ""


def parse_warm_command(text: str) -> Optional[WarmPerson]:
    _, _, rest = (text or "").strip().partition(" ")
    fields = [f.strip() for f in rest.split(",")]
    if len(fields) < 2 or not fields[0] or not fields[1]:
        return None
    return WarmPerson(name=fields[0], relationship=fields[1], works_at=", ".join(f for f in fields[2:] if f))


def network_company(conn) -> Company:
    """The placeholder "company" that people he knows are filed under. It
    is outside Colorado/Virginia on purpose, so none of the pickers ever
    treat these people as cold contacts."""
    company = db.get_company_by_name(conn, config.NETWORK_COMPANY_NAME)
    if company is None:
        company = Company(
            name=config.NETWORK_COMPANY_NAME, website="", state="Other", city="", stage="",
            what_they_build="", why_fit="People I already know", careers_url="", priority_tier=3,
        )
        company.id = db.insert_company(conn, company)
    return company
