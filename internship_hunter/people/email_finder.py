"""Finds PUBLISHED email addresses for people already on file. Nothing here
ever builds an address from a pattern ("first.last@company.com"): an
address is only stored if a real page shows it, and the URL of that page
is stored next to it (db.set_contact_email refuses one without a source).

Two public sources, both allowed by CLAUDE.md constraint 6:
  1. The company's own website -- its contact / about / team / leadership /
     press pages sometimes print a person's address. An address on the
     company's domain is matched to a contact by their name.
  2. GitHub -- a public profile may list an email. A profile only counts
     as that person if its name matches AND its "company" field names the
     same company, so a same-named stranger is never picked up.

Honest expectation: most people at these companies publish no address
anywhere, so this fills in a minority. The rest stay blank for the student
to fill in with /to.
"""

from __future__ import annotations

import re
import time
from typing import Optional

import requests

from internship_hunter import config
from internship_hunter.models import Company, Contact
from internship_hunter.people import people_finder

SITE_PATHS = ("", "/contact", "/contact-us", "/about", "/about-us", "/team", "/leadership", "/company", "/press", "/news")
GITHUB_API = "https://api.github.com"
# Words too common in company names to identify a company by themselves.
SUFFIX_WORDS = ("inc", "llc", "corp", "corporation", "co", "industries", "technologies", "technology", "systems", "labs")


class GitHubRateLimited(RuntimeError):
    pass


def _letters(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def name_parts(full_name: str) -> tuple[str, str]:
    """(first, last) in lowercase letters only, ignoring titles like "Dr."."""
    words = [w for w in re.split(r"\s+", full_name.strip()) if _letters(w) and _letters(w) not in ("dr", "mr", "ms", "mrs", "phd")]
    if len(words) < 2:
        return (_letters(words[0]) if words else "", "")
    return _letters(words[0]), _letters(words[-1])


def email_belongs_to(email: str, full_name: str) -> bool:
    """True if the mailbox is recognisably this person's: it contains their
    last name, or is their first name plus last initial. A bare first name
    ("chris@") is not enough -- it could be anyone called Chris there."""
    first, last = name_parts(full_name)
    mailbox = _letters(email.split("@")[0])
    if not first or not last or len(last) < 3:
        return False
    return last in mailbox or mailbox == first + last[0]


def match_emails_to_contacts(emails: list[str], contacts: list[Contact]) -> dict[int, str]:
    """contact id -> email, only where exactly one contact fits an address."""
    matched: dict[int, str] = {}
    for email in emails:
        if people_finder.is_general_inbox(email):
            continue
        owners = [c for c in contacts if email_belongs_to(email, c.name)]
        if len(owners) == 1 and owners[0].id not in matched:
            matched[owners[0].id] = email
    return matched


def find_on_company_site(company: Company, contacts: list[Contact], get=requests.get) -> dict[int, tuple[str, str]]:
    """contact id -> (email, page it was published on), from the company's own site."""
    found: dict[int, tuple[str, str]] = {}
    if not company.website:
        return found
    root = company.website.rstrip("/")
    urls = [f"{root}{path}" for path in SITE_PATHS] + [u for u in (company.team_url,) if u]
    for url in dict.fromkeys(urls):
        if "linkedin.com" in url.lower():
            continue
        try:
            resp = get(url, timeout=people_finder.REQUEST_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
        except requests.RequestException:
            continue
        if resp.status_code >= 400:
            continue
        emails = people_finder.find_published_emails(resp.text, company.website)
        for contact_id, email in match_emails_to_contacts(emails, contacts).items():
            found.setdefault(contact_id, (email, url))
    return found


def company_key(company_name: str) -> str:
    """The company's name as letters only, minus a trailing "Inc"/"Labs"
    style word -- what a GitHub profile's company field must contain."""
    words = [w for w in re.split(r"[^A-Za-z0-9]+", company_name.lower()) if w]
    while len(words) > 1 and words[-1] in SUFFIX_WORDS:
        words.pop()
    return "".join(words)


def profile_is_this_person(profile: dict, contact_name: str, company_name: str) -> bool:
    first, last = name_parts(contact_name)
    profile_first, profile_last = name_parts(profile.get("name") or "")
    if not last or (profile_first, profile_last) != (first, last):
        return False
    return company_key(company_name) in _letters(profile.get("company") or "")


def find_on_github(contact_name: str, company_name: str, get=requests.get, max_profiles: int = 2) -> Optional[tuple[str, str]]:
    """(email, profile URL) if a GitHub profile that is clearly this person
    lists a public email; else None. Raises GitHubRateLimited when GitHub
    says to slow down, so the caller can stop for now."""
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "internship-hunter"}
    if config.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {config.GITHUB_TOKEN}"

    def fetch(url: str, params: Optional[dict] = None) -> dict:
        resp = get(url, params=params, headers=headers, timeout=people_finder.REQUEST_TIMEOUT)
        if resp.status_code in (403, 429):
            raise GitHubRateLimited("GitHub rate limit reached")
        return resp.json() if resp.status_code == 200 else {}

    results = fetch(f"{GITHUB_API}/search/users", {"q": f'fullname:"{contact_name}"', "per_page": max_profiles})
    for item in (results.get("items") or [])[:max_profiles]:
        profile = fetch(f"{GITHUB_API}/users/{item['login']}")
        if profile.get("email") and profile_is_this_person(profile, contact_name, company_name):
            return profile["email"].strip().lower(), profile.get("html_url") or f"https://github.com/{item['login']}"
    return None


def find_for_company(conn, company: Company, use_github: bool = True, pause: float = 6.5) -> list[tuple[Contact, str, str]]:
    """Look for published emails for everyone at `company` who has none.
    Stores what it finds; returns [(contact, email, source_url)]."""
    from internship_hunter import db

    missing = [c for c in db.list_contacts(conn, company_id=company.id) if not c.email]
    if not missing:
        return []
    stored = []
    on_site = find_on_company_site(company, missing)
    for contact in missing:
        hit = on_site.get(contact.id)
        if hit is None and use_github:
            try:
                hit = find_on_github(contact.name, company.name)
            except GitHubRateLimited:
                use_github = False
            except requests.RequestException:
                hit = None
            else:
                # GitHub allows ~10 searches a minute without a token.
                time.sleep(0 if config.GITHUB_TOKEN else pause)
        if hit:
            db.set_contact_email(conn, contact.id, hit[0], hit[1])
            stored.append((contact, hit[0], hit[1]))
    return stored
