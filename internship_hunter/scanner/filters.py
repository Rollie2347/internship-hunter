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


def title_is_non_software(title: str) -> bool:
    """True if the title itself names a hardware/business discipline. The
    scanner's stored flag can't be trusted alone for old rows: "Electrical
    Engineering Intern" got through because the keyword was "electrical
    engineer", which a word-boundary match doesn't find inside "engineering"."""
    return _contains_any(_normalize(title), config.SOFTWARE_EXCLUDE_KEYWORDS)


def is_closed_to_high_schoolers(title: str) -> bool:
    """True for "intern" postings whose title names a program he can't be
    in at all -- e.g. SkillBridge is for military members leaving the
    service, which the plain intern filter let through on a live Defense
    Unicorns posting. Still stored; just never queued for approval."""
    return _contains_any(_normalize(title), config.INELIGIBLE_PROGRAM_KEYWORDS)


def _us_states_in(location: str) -> set[str]:
    """Two-letter codes of every US state named in a location string, by
    full name ("Colorado") or by postal code ("CO"). Postal codes are
    matched case-sensitively so the ordinary words "in"/"or"/"me" inside a
    location never count as Indiana/Oregon/Maine."""
    found = set()
    lowered = location.lower()
    for code, name in config.US_STATES.items():
        if re.search(rf"\b{re.escape(name.lower())}\b", lowered) or re.search(rf"\b{code}\b", location):
            found.add(code)
    if re.search(r"\bD\.C\.", location):
        found.add("DC")
    for city, code in config.US_CITY_STATES.items():
        if re.search(rf"\b{re.escape(city)}\b", lowered):
            found.add(code)
    return found


def offices_in_preferred_states(location: str) -> list[str]:
    """The individual offices in a (possibly multi-city) location string
    that are in Colorado or Virginia. An Anduril posting listed nine cities
    in one string; only two of them were places he'd actually work."""
    parts = [p.strip() for p in re.split(r"[;|]", location or "") if p.strip()]
    return [p for p in parts if _us_states_in(p) & config.PREFERRED_STATES]


def location_rank(location: str) -> int:
    """Where a posting sits in the approval queue by location -- see the
    table next to config.PREFERRED_STATES. A posting listing several
    offices gets the rank of its best one."""
    location = location or ""
    states = _us_states_in(location)
    if states & config.PREFERRED_STATES:
        return 0
    if states - {config.HOME_STATE}:
        return 1
    if config.HOME_STATE in states:
        return 3
    lowered = location.lower()
    if not lowered.strip() or "remote" in lowered:
        return 2
    if "united states" in lowered:
        return 1
    return config.LOCATION_RANK_NOT_QUEUED
