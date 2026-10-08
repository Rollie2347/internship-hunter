"""Plain dataclasses mirroring the SQLite tables in db.py.

Why dataclasses instead of just passing dicts around? Mostly so your editor
can autocomplete field names and catch typos (`company.citys` would be a
caught error; `company["citys"]` would just silently return None).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Company:
    name: str
    website: str
    state: str  # "VA", "CO", "WI", "Remote", or "Other"
    city: str
    stage: str  # e.g. "seed", "series B", "public", "government"
    what_they_build: str
    why_fit: str
    careers_url: str
    priority_tier: int  # 1-4, see config.PRIORITY_TIERS
    needs_verification: bool = False
    notes: str = ""
    ats_type: Optional[str] = None  # "greenhouse", "lever", "ashby", or None if undetected
    ats_slug: Optional[str] = None
    manual_check_needed: bool = False  # no ATS feed found -- check careers_url by hand
    team_url: Optional[str] = None  # self-detected team/about page, see people/people_finder.py
    contact_email: Optional[str] = None  # an inbox published on the company's own site (careers@, info@)
    id: Optional[int] = None
    created_at: Optional[str] = None

    def __post_init__(self) -> None:
        if self.priority_tier not in (1, 2, 3, 4):
            raise ValueError(
                f"priority_tier must be 1-4 (see config.PRIORITY_TIERS), got {self.priority_tier!r}"
            )


@dataclass
class Posting:
    company_id: int
    external_id: str
    title: str
    location: str
    url: str
    ats_source: str  # "greenhouse", "lever", "ashby", or "manual"
    is_software_role: bool = False
    is_intern_or_junior: bool = False
    clearance_required: bool = False
    citizenship_required: bool = False
    skill_match: str = "unclear"  # "strong", "stretch", "gap", or "unclear"
    status: str = "new"
    eligibility: Optional[str] = None  # None = not screened yet; see scanner/eligibility.py
    eligibility_reason: str = ""
    first_seen_date: Optional[str] = None
    last_seen_date: Optional[str] = None
    id: Optional[int] = None


@dataclass
class Contact:
    company_id: int
    name: str
    title: str
    source_url: str
    fact: str
    email: Optional[str] = None
    email_source_url: Optional[str] = None  # the public page the email was read from
    source_kind: str = "team_page"  # "team_page", "web" (people/web_search.py), "hunter" or "manual" (/li)
    linkedin_url: Optional[str] = None  # only ever one the student pasted himself; never fetched
    id: Optional[int] = None
    found_at: Optional[str] = None


@dataclass
class Message:
    company_id: int
    channel: str  # "email", "application", "linkedin" (connection note) or "linkedin_reply"
    subject: str
    body: str
    contact_id: Optional[int] = None
    posting_id: Optional[int] = None
    gmail_draft_id: Optional[str] = None
    status: str = "drafted"  # drafted -> sent -> replied/interviewing/rejected
    sent_at: Optional[str] = None
    to_email: Optional[str] = None  # address on the draft; None = still blank
    gmail_thread_id: Optional[str] = None  # set once sent; used to notice replies
    reminded_at: Optional[str] = None  # LinkedIn only: when the one 7-day reminder went out
    id: Optional[int] = None
    created_at: Optional[str] = None


@dataclass
class Application:
    posting_id: int
    status: str = "proposed"  # see config.APPLICATION_STATUSES
    answers: dict = field(default_factory=dict)  # form label -> drafted answer
    left_for_you: list = field(default_factory=list)  # form labels the student answers himself
    telegram_message_id: Optional[int] = None
    proposed_at: Optional[str] = None
    decided_at: Optional[str] = None
    submitted_at: Optional[str] = None
    id: Optional[int] = None
