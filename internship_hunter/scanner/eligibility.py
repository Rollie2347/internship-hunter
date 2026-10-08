"""Reads a posting's actual requirements and decides whether a 15-year-old
high school student can truthfully apply, BEFORE it is put in front of him.

Why this exists: the title "Flight Software Intern" says nothing about who
may apply. Rocket Lab's posting reads "Must be enrolled in a bachelor's,
master's or doctorate degree program", so the only honest answer on its
form was "No, I don't meet the qualifications" -- a wasted card.

Three verdicts:
  eligible      -- nothing in the posting rules him out
  long_shot     -- it prefers things he lacks, but doesn't require them
  not_eligible  -- it REQUIRES something he can't truthfully claim: college
                   enrollment or a degree, age 18+, years of professional
                   experience, a clearance, or full-time work before he
                   turns 16

Two passes, cheapest first:
  1. screen_text(): plain patterns for the common hard requirements. Free,
     deterministic, and it quotes the sentence that decided it.
  2. assess_with_model(): only for postings that passed (1), Claude reads
     the text for requirements phrased some other way. Its "not eligible"
     only counts if the sentence it quotes is really in the posting --
     verified in code -- otherwise the posting is kept as a long shot, so
     a model mistake can't silently hide a real opportunity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Optional

from pydantic import BaseModel

from internship_hunter import anthropic_client, config
from internship_hunter.models import Company, Posting

VERDICTS = ("eligible", "long_shot", "not_eligible")
MAX_POSTING_CHARS = 12000


@dataclass
class Verdict:
    verdict: str
    reason: str = ""


# A posting that says it is FOR high schoolers is eligible outright.
# ("high school diploma" is the opposite signal, and is excluded.)
HIGH_SCHOOL_WELCOME = re.compile(
    r"high[\s-]?school(ers| (students?|interns?|internships?|juniors?|seniors?|sophomores?|program|apprentice))",
    re.IGNORECASE,
)

# Whole words only, and the abbreviations (BS, M.S.) only in capitals: a
# looser version matched the "ms" in "systems required to support it" on a
# live Striveworks posting and called that a degree requirement.
DEGREE_WORDS = (
    r"(\bbachelor|\bmaster[’']?s\b|\bdoctora|\bph\.?\s?d\b|\bundergraduate\b|\bgraduate (program|student|degree)|"
    r"\bdegree\b|\bcollege\b|\buniversity\b|(?-i:\b(B\.?S|M\.?S|B\.?A)\.?(?![A-Za-z])))"
)
# (pattern, what it means). Each is a requirement he can't truthfully meet.
HARD_REQUIREMENTS: list[tuple[re.Pattern, str]] = [
    (re.compile(rf"(enrolled|pursuing|working towards?|matriculated|studying)[^.;\n]{{0,90}}{DEGREE_WORDS}", re.I),
     "requires being enrolled in a college degree program"),
    (re.compile(r"(rising|current|incoming)\s+(college\s+)?(freshm[ae]n|sophomores?|juniors?|seniors?)\b(?![^.;\n]{0,25}high school)", re.I),
     "is for college students by class year"),
    (re.compile(r"(graduat\w+)[^.;\n]{0,60}\b(between|by|in|no later than)\b[^.;\n]{0,40}\b20(2[6-9]|3[01])\b[^.;\n]{0,60}"
                rf"|{DEGREE_WORDS}[^.;\n]{{0,40}}graduation date", re.I),
     "requires a college graduation date"),
    (re.compile(rf"{DEGREE_WORDS}[^.;\n]{{0,60}}\b(is required|required|or equivalent experience)\b"
                rf"|\b(requires?|must have|must hold|minimum)[^.;\n]{{0,40}}{DEGREE_WORDS}", re.I),
     "requires a college degree"),
    (re.compile(r"\b(at least|minimum( age)?( of)?|must be|be)\s+(18|eighteen)\b|\b18 years (of age|old)|\b18\+", re.I),
     "requires being 18 or older"),
    (re.compile(r"\b([2-9]|1\d)\+?\s*(-\s*\d+\s*)?years?[’']? (of )?(professional|industry|relevant|work|full[- ]time|hands[- ]on)?\s*(software |engineering |development )?experience", re.I),
     "requires years of professional experience"),
    (re.compile(r"\bGPA\b[^.;\n]{0,30}\b[23]\.\d\b[^.;\n]{0,30}\b(required|or above|or higher|minimum)\b|\bminimum\b[^.;\n]{0,20}\bGPA\b", re.I),
     "requires a college GPA"),
]


def _sentence_around(text: str, start: int, end: int) -> str:
    left = max(text.rfind(".", 0, start), text.rfind("\n", 0, start)) + 1
    right_candidates = [i for i in (text.find(".", end), text.find("\n", end)) if i != -1]
    right = min(right_candidates) if right_candidates else len(text)
    return re.sub(r"\s+", " ", text[left:right]).strip()[:220]


def welcomes_high_schoolers(text: str) -> bool:
    return any("diploma" not in text[m.end():m.end() + 12].lower() for m in HIGH_SCHOOL_WELCOME.finditer(text or ""))


def screen_text(text: str) -> Optional[Verdict]:
    """Pass 1. Returns a decided Verdict, or None if the patterns found
    nothing either way and the posting needs a closer read."""
    if not (text or "").strip():
        return None
    if welcomes_high_schoolers(text):
        return Verdict("eligible", "The posting says it is open to high school students.")
    for pattern, meaning in HARD_REQUIREMENTS:
        match = pattern.search(text)
        if match:
            return Verdict("not_eligible", f'It {meaning}: "{_sentence_around(text, match.start(), match.end())}"')
    return None


class ModelAssessment(BaseModel):
    verdict: Literal["eligible", "long_shot", "not_eligible"]
    reason: str
    quote: str


SYSTEM_PROMPT = """You screen job postings for one specific applicant, so he is only shown postings \
he can truthfully apply to. Facts about him, all of which he states honestly on every application:
- He is 15 years old and in high school (class of 2029). He is NOT enrolled in any college or \
university and has no degree.
- He is a US citizen with no security clearance.
- He has never had a paid job. His experience is self-directed projects, completed MIT/edX \
coursework, and a varsity robotics team.
- {availability}

Decide:
- "not_eligible": the posting REQUIRES something he cannot truthfully claim -- enrollment in a \
college/university degree program, a completed degree, a college class year or graduation date, \
being 18 or older, years of professional experience, an existing clearance, or full-time work on \
dates before he turns 16.
- "long_shot": nothing is strictly required that he lacks, but the posting clearly expects more \
(e.g. "preferred" qualifications, or it is obviously aimed at college students without saying so).
- "eligible": nothing rules him out.

Rules:
1. Judge only from the posting text given. "Preferred" or "nice to have" items are never a \
reason for not_eligible.
2. For not_eligible, `quote` MUST be one sentence copied character-for-character from the \
posting that states the requirement. If you cannot quote such a sentence, the verdict is not \
not_eligible.
3. `reason` is one short plain sentence addressed to him ("It requires...")."""


def assess_with_model(client, company: Company, posting: Posting, text: str) -> Verdict:
    """Pass 2: one Claude call. A not_eligible verdict is only trusted if
    its quote is really in the posting."""
    response = client.messages.parse(
        model=config.DRAFTING_MODEL,
        max_tokens=config.MAX_OUTPUT_TOKENS,
        system=SYSTEM_PROMPT.format(availability=config.availability_statement()),
        messages=[{
            "role": "user",
            "content": f"Company: {company.name}\nTitle: {posting.title}\nLocation: {posting.location}\n\n"
                       f"Posting text:\n{text[:MAX_POSTING_CHARS]}",
        }],
        output_format=ModelAssessment,
    )
    assessment = anthropic_client.parsed(response)
    return check_assessment(assessment.verdict, assessment.reason, assessment.quote, text)


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def check_assessment(verdict: str, reason: str, quote: str, text: str) -> Verdict:
    """Never trust "not eligible" without proof: the quoted sentence must
    appear in the posting. If it doesn't, keep the posting as a long shot."""
    if verdict == "not_eligible":
        if len(_squash(quote)) >= 15 and _squash(quote) in _squash(text):
            return Verdict("not_eligible", f'{reason.strip()} "{quote.strip()[:220]}"')
        return Verdict("long_shot", f"{reason.strip()} (I couldn't confirm that in the posting text, so check it.)")
    return Verdict(verdict if verdict in VERDICTS else "long_shot", reason.strip())


def screen_posting(client, company: Company, posting: Posting, fetch_text=None) -> Verdict:
    """Fetch the posting's text and run both passes. If the text can't be
    fetched the posting is kept as a long shot rather than dropped unseen."""
    from internship_hunter.scanner import ats_feeds

    fetch_text = fetch_text or ats_feeds.fetch_posting_text
    text = fetch_text(posting.ats_source, company.ats_slug, posting.external_id) if company.ats_slug else ""
    if not text.strip():
        return Verdict("long_shot", "I couldn't read this posting's requirements, so check them before applying.")
    decided = screen_text(text)
    if decided is not None:
        return decided
    if client is None:
        return Verdict("eligible", "")
    return assess_with_model(client, company, posting, text)
