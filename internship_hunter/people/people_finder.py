"""Phase 3: find 1-3 real, publicly-listed people per top-tier company, from
a single page of that company's own website -- never LinkedIn, never
invented.

How a fact gets from a webpage into the database, in order:
  1. find_team_page_url() tries a few common paths on the company's OWN
     domain (never a third-party board, so there's no risk of attributing
     another company's page to this one -- unlike the ATS slug lookup in
     scanner/ats_feeds.py, which had exactly that failure mode).
  2. fetch_page_text() downloads it and strips it to visible text.
  3. extract_people() sends that text to Claude with strict instructions:
     only extract a name+title that is literally stated, write a fact
     grounded in the text, include an email only if it's literally present,
     and return an empty list rather than guess.
  4. to_contacts() attaches the URL we actually fetched as source_url
     ourselves -- Claude is never asked to report its own source, so there
     is nothing for it to get wrong there.
"""

from __future__ import annotations

from typing import Optional

import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel

from internship_hunter import config
from internship_hunter.models import Contact

REQUEST_TIMEOUT = 10
MAX_PAGE_CHARS = 8000

SYSTEM_PROMPT = """You are helping a 15-year-old high school student find real, publicly \
listed people (founders, CTOs, engineering leads, recruiters) at a tech company, so he can \
send a short, honest, specific outreach message later. You will be given the visible text of \
one webpage. Follow these rules exactly:

1. ONLY extract a person if their name AND a role/title are literally stated in the given \
text. Never invent, infer, or guess a name, title, or fact that isn't actually there.
2. Return at most 5 people -- prefer founders, CTOs, engineering leads/managers, individual \
software engineers, and recruiters/talent people over unrelated roles. Don't only pick the \
most senior names: a rank-and-file engineer is often a better person to ask for a referral \
than a CEO is to ask for a 15-minute call, so include a mix of seniority when the page lists one.
3. For each person, write one short, specific "fact" grounded in the text (e.g. their stated \
role, or something specific the text says they work on) -- not speculation or a generic \
compliment.
4. Only fill in an email if that literal email address string appears in the given text. \
Otherwise leave it blank -- never guess at a likely email format.
5. If the text doesn't clearly name any real people with roles, return an empty list. An \
empty list is a correct, expected answer for many pages -- do not stretch to fill one in.
6. You are only given this one page's text, not LinkedIn or any other source -- never treat \
a LinkedIn mention in the text as something you looked up."""


class ExtractedPerson(BaseModel):
    name: str
    title: str
    fact: str
    email: Optional[str] = None


class ExtractionResult(BaseModel):
    people: list[ExtractedPerson]


def find_team_page_url(website: str, careers_url: str = "") -> Optional[str]:
    """Try a few common about/team paths on the company's own domain, in
    order, and return the first one that resolves. Returns None (not a
    guess) if nothing resolves -- the caller should fall back to careers_url
    or flag the company for a manual look."""
    if not website:
        return None
    root = website.rstrip("/")
    candidates = [f"{root}{path}" for path in config.TEAM_PAGE_PATHS]
    if careers_url:
        candidates.append(careers_url)
    for url in candidates:
        try:
            resp = requests.head(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            if resp.status_code >= 400 or resp.status_code == 405:
                # Some servers don't support HEAD -- confirm with a real GET.
                resp = requests.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        except requests.RequestException:
            continue
        if resp.status_code < 400:
            return url
    return None


def fetch_page_text(url: str, max_chars: int = MAX_PAGE_CHARS) -> Optional[str]:
    """Download a page and return its visible text, truncated. Returns None
    on any network error or if the URL is LinkedIn -- CLAUDE.md bans
    LinkedIn automation outright, so this is a hard guard, not a preference."""
    if "linkedin.com" in url.lower():
        return None
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
    except requests.RequestException:
        return None
    if resp.status_code >= 400:
        return None
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = " ".join(soup.get_text(separator=" ").split())
    return text[:max_chars]


def build_user_content(company_name: str, url: str, page_text: str) -> str:
    return f"Company: {company_name}\nSource URL: {url}\n\nPage text:\n{page_text}"


def extract_people(client, company_name: str, url: str, page_text: str) -> list[ExtractedPerson]:
    """Call Claude to extract people from already-fetched page text. Pure
    wrapper around one API call -- kept separate from fetching/storing so it
    can be tested by injecting a fake client."""
    response = client.messages.parse(
        model=config.PEOPLE_FINDER_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_user_content(company_name, url, page_text)}],
        output_format=ExtractionResult,
    )
    return response.parsed_output.people[: config.MAX_CONTACTS_PER_COMPANY]


def to_contacts(people: list[ExtractedPerson], company_id: int, source_url: str) -> list[Contact]:
    """Convert extracted people into storable Contact records, attaching
    source_url ourselves (never trusting the model to report its own
    source). Rejects the whole batch if source_url is missing -- a fact
    with no source is exactly what CLAUDE.md requires we never store."""
    if not source_url:
        raise ValueError("Cannot store contacts without a source_url")
    contacts = []
    for person in people:
        if not person.name or not person.title:
            continue  # incomplete extraction -- skip rather than store a half-fact
        contacts.append(
            Contact(
                company_id=company_id,
                name=person.name,
                title=person.title,
                source_url=source_url,
                fact=person.fact,
                email=person.email or None,
            )
        )
    return contacts
