"""Pulls the handful of structured fields an application form actually
needs (name, email, phone, GitHub/portfolio links) out of the real profile
files, instead of maintaining a separate data file that could drift out of
sync with about_me.md/resume.txt -- same "one source of truth" principle as
Phase 3/4.

Deliberately does NOT parse or fill: LinkedIn (he doesn't have one -- under
LinkedIn's own 16+ minimum, see CLAUDE.md), current employer (none), or any
judgment/screening question (clearance, work authorization, EEO/demographic
questions) -- those are left for the student to answer himself. See
field_map.py for the full allow-list of what gets auto-filled.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class ApplicantInfo:
    first_name: str = ""
    last_name: str = ""
    full_name: str = ""
    email: str = ""
    phone: str = ""
    github_url: str = ""
    portfolio_url: str = ""
    location: str = ""


EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")
GITHUB_RE = re.compile(r"github\.com/[\w-]+", re.IGNORECASE)


def _first_email(text: str) -> str:
    match = EMAIL_RE.search(text)
    return match.group(0) if match else ""


def _first_phone(text: str) -> str:
    match = PHONE_RE.search(text)
    return match.group(0) if match else ""


def _first_github(text: str) -> str:
    match = GITHUB_RE.search(text)
    return f"https://{match.group(0)}" if match else ""


def _name_from_about_me(about_me_text: str) -> tuple[str, str, str]:
    match = re.search(r"\*\*Name:\*\*\s*(.+)", about_me_text)
    if not match:
        return "", "", ""
    full_name = match.group(1).strip()
    parts = full_name.split()
    first = parts[0] if parts else ""
    last = parts[-1] if len(parts) > 1 else ""
    return first, last, full_name


def _location_from_about_me(about_me_text: str) -> str:
    match = re.search(r"\*\*Home:\*\*\s*([^.(]+)", about_me_text)
    return match.group(1).strip() if match else ""


def _portfolio_from_about_me(about_me_text: str) -> str:
    # The "Contact:" line lists email . website . github, separated by "·".
    match = re.search(r"\*\*Contact:\*\*\s*(.+)", about_me_text)
    if not match:
        return ""
    for part in re.split(r"[·|]", match.group(1)):
        part = part.strip()
        if part and "@" not in part and "github.com" not in part.lower():
            return part if part.startswith("http") else f"https://{part}"
    return ""


def build_applicant_info(about_me_text: str, resume_text: str = "") -> ApplicantInfo:
    """Build an ApplicantInfo from whichever of the two source texts has
    each fact. resume_text is checked FIRST for phone/email -- about_me.md's
    "Projects" section describes a demo AI receptionist with its own phone
    number in the text, and a naive combined search picked that up instead
    of his real number from resume.txt's contact header. Order matters here,
    not just presence."""
    first, last, full_name = _name_from_about_me(about_me_text)
    phone = _first_phone(resume_text) or _first_phone(about_me_text)
    email = _first_email(about_me_text) or _first_email(resume_text)
    github = _first_github(about_me_text) or _first_github(resume_text)
    return ApplicantInfo(
        first_name=first,
        last_name=last,
        full_name=full_name,
        email=email,
        phone=phone,
        github_url=github,
        portfolio_url=_portfolio_from_about_me(about_me_text),
        location=_location_from_about_me(about_me_text),
    )
