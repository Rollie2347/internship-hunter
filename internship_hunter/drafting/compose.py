"""Phase 4: compose a short, honest outreach email from the student's real
profile -- never invented experience, never a fabricated project link,
never a hidden age or hours. See CLAUDE.md constraints 1, 2, and 5.

The model never decides the hours-availability framing (compose it wrong
once and a message states an inaccurate legal fact) -- config.availability_
statement() computes that from the real date and STUDENT_TURNS_16, and gets
handed to the model as a fact to use, the same pattern as Phase 3 attaching
source_url itself rather than trusting the model to report it.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from internship_hunter import config
from internship_hunter.models import Company, Contact, Posting


class DraftEmail(BaseModel):
    subject: str
    body: str


SYSTEM_PROMPT = """You are helping a 15-year-old high school student write a short, honest \
cold email or application note to someone at a tech/defense-tech company, based on his real \
profile below. Follow these rules exactly:

1. State plainly that he is a 15-year-old high school student. This is the hook, not something \
to hide or soften -- never imply he is older, in college, or already working professionally.
2. Keep the body under 150 words total.
3. Mention one specific, real detail about the company or person's work (from the context \
given below) -- not a generic compliment like "I love what you're building."
4. Link exactly ONE project from the "Projects" section of the profile as proof of real work. \
Copy its URL character-for-character from the profile text. If the most relevant project has \
no real URL in the profile text (e.g. marked TODO), pick a different project that does have a \
real URL instead -- never invent, guess, or alter a URL.
5. Include the exact "Availability" sentence given to you below, almost verbatim (light \
rewording for flow is fine, but never change the hours, dates, or age it states).
6. End with exactly ONE clear, low-commitment ask. An "Ask type" is given to you below -- honor \
it exactly: "call" means ask for a brief 15-minute call; "resume" means ask if he can send his \
resume; "referral" means ask if they could refer him internally or point him to whoever handles \
internship hiring; "auto" means pick whichever of those three fits this specific message best. \
Never combine more than one ask.
7. Write in his voice: direct, specific, a little technical, not salesy. No corporate buzzwords, \
no exclamation-point enthusiasm, no "I'd love the opportunity to..." filler.
8. Return a subject line (short, specific, not clickbait) and the email body separately."""


def build_target_context(
    company: Company,
    contact: Optional[Contact] = None,
    posting: Optional[Posting] = None,
) -> str:
    """Describe who/what this email is about, from facts already on file --
    nothing here is left for the model to look up or guess."""
    lines = [f"Company: {company.name}", f"What they build: {company.what_they_build}", f"Why it fits him: {company.why_fit}"]
    if contact is not None:
        lines.append(f"Writing to: {contact.name}, {contact.title}")
        lines.append(f"A specific, sourced fact about them: {contact.fact}")
    if posting is not None:
        lines.append(f"Specific open posting: {posting.title} ({posting.location})")
        lines.append(f"Posting URL: {posting.url}")
    if contact is None and posting is None:
        lines.append("No specific contact or posting -- write a general introduction to the team.")
    return "\n".join(lines)


VALID_ASK_TYPES = ("auto", "call", "resume", "referral")


def build_user_content(profile_text: str, resume_text: str, target_context: str, ask_type: str = "auto") -> str:
    return (
        f"=== His profile (about_me.md) ===\n{profile_text}\n\n"
        f"=== His resume ===\n{resume_text}\n\n"
        f"=== Who this email is for ===\n{target_context}\n\n"
        f"=== Availability (use this fact, don't recompute it) ===\n{config.availability_statement()}\n\n"
        f"=== Ask type ===\n{ask_type}"
    )


def compose_email(
    client,
    profile_text: str,
    resume_text: str,
    company: Company,
    contact: Optional[Contact] = None,
    posting: Optional[Posting] = None,
    ask_type: str = "auto",
) -> DraftEmail:
    if ask_type not in VALID_ASK_TYPES:
        raise ValueError(f"ask_type must be one of {VALID_ASK_TYPES}, got {ask_type!r}")
    target_context = build_target_context(company, contact, posting)
    user_content = build_user_content(profile_text, resume_text, target_context, ask_type)
    response = client.messages.parse(
        model=config.DRAFTING_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
        output_format=DraftEmail,
    )
    return response.parsed_output


def validate_draft(draft: DraftEmail) -> list[str]:
    """Return a list of human-readable warnings -- never blocks creating
    the draft (CLAUDE.md already requires a human review every draft before
    sending), just flags anything worth double-checking before you do."""
    warnings = []
    word_count = len(draft.body.split())
    if word_count > config.MAX_DRAFT_WORDS:
        warnings.append(f"Body is {word_count} words, over the {config.MAX_DRAFT_WORDS}-word target.")
    lowered = draft.body.lower()
    if "15" not in draft.body and "fifteen" not in lowered:
        warnings.append("Doesn't seem to mention his age (15) -- check honesty requirement.")
    if "http" not in lowered and "github.com" not in lowered:
        warnings.append("Doesn't seem to include a project link.")
    return warnings
