"""Keyword-based classification of a single job posting.

Everything here works on plain text (title + description), so it's fast,
has no external dependencies, and is trivial to unit test -- no network,
no API calls. It's deliberately simple: keyword matching will sometimes be
wrong (a posting that says "no clearance required" would still trip the
clearance keyword), so treat these as flags to double-check, not ground
truth. The docstring on each function says which direction a false
positive/negative is safer to err on.

Two correctness traps this module specifically guards against (both found
by actually running the scanner against real postings, not hypothetically):
  1. Plain substring matching false-triggers on unrelated words that happen
     to contain a keyword -- "V-BAT **Internal** Training Instructor" would
     match "intern", and "ro**bust** software" would match "rust". Every
     check here uses regex word boundaries instead.
  2. A long job description can mention an unrelated technology in passing
     (e.g. a Manufacturing Engineering posting that happens to say
     "familiarity with CAD software") -- if that one word in a 2,000-word
     description could flip the classification, a hardware role would get
     misread as software. So is_software_role() checks the TITLE first and
     lets a clear title verdict win outright; full text is only a
     tie-breaker when the title itself is ambiguous (e.g. just "Intern").
"""

from __future__ import annotations

import re

from internship_hunter import config


def _normalize(*parts: str) -> str:
    return " ".join(p or "" for p in parts).lower()


def _contains_any(text: str, keywords: set[str]) -> bool:
    """Word-boundary keyword search -- "rust" won't match inside "robust",
    "intern" won't match inside "internal"."""
    return any(re.search(rf"\b{re.escape(kw)}\b", text) for kw in keywords)


def is_software_role(title: str, description: str = "") -> bool:
    """True if this looks like a software-flavored role at all (CLAUDE.md:
    'software only'). The title is authoritative when it's clear either way
    (a Manufacturing Engineering Intern role doesn't become "software" just
    because its description mentions some CAD software in passing); the
    full text is only consulted when the title alone is ambiguous."""
    title_lower = _normalize(title)
    if _contains_any(title_lower, config.SOFTWARE_EXCLUDE_KEYWORDS):
        return False
    if _contains_any(title_lower, config.SOFTWARE_ROLE_KEYWORDS):
        return True

    full_text = _normalize(title, description)
    if _contains_any(full_text, config.SOFTWARE_EXCLUDE_KEYWORDS):
        return False
    return _contains_any(full_text, config.SOFTWARE_ROLE_KEYWORDS)


def is_intern_or_junior(title: str) -> bool:
    """True if the title itself reads as intern/co-op/junior/entry-level."""
    return _contains_any(_normalize(title), config.INTERN_OR_JUNIOR_KEYWORDS)


def requires_clearance(description: str, title: str = "") -> bool:
    """True if the posting text mentions a security clearance. Errs toward
    flagging (a false positive just means double-checking one posting;
    per CLAUDE.md, clearance roles must never reach outreach)."""
    return _contains_any(_normalize(title, description), config.CLEARANCE_KEYWORDS)


def requires_citizenship(description: str, title: str = "") -> bool:
    """True if the posting text requires US citizenship. This is fine for
    the student (he's a US citizen) -- just flagged, never filtered out."""
    return _contains_any(_normalize(title, description), config.CITIZENSHIP_KEYWORDS)


def classify_skill_match(title: str, description: str = "") -> str:
    """Tag a posting 'strong' / 'stretch' / 'gap' / 'unclear' against the
    student's actual, resume-verified skill set (see config.py for sources
    and reasoning). Priority: any 'strong' keyword wins outright (a Python
    role that also mentions Kubernetes is still a real fit); 'gap' only wins
    when nothing familiar shows up at all.
    """
    text = _normalize(title, description)
    if _contains_any(text, config.STUDENT_SKILL_STRONG):
        return "strong"
    if _contains_any(text, config.STUDENT_SKILL_STRETCH):
        return "stretch"
    if _contains_any(text, config.STUDENT_SKILL_GAP):
        return "gap"
    return "unclear"


def worth_notifying(
    is_software: bool,
    is_intern: bool,
    clearance_required: bool,
    skill_match: str,
) -> bool:
    """Whether a newly-seen posting is worth pushing to Telegram, vs. just
    being quietly stored. Still stored either way -- see db.upsert_posting --
    this only controls the notification/CLI 'worth your time' view."""
    if not is_software or not is_intern:
        return False
    if clearance_required:
        return False
    if skill_match == "gap":
        return False
    return True
