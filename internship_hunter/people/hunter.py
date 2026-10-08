"""Hunter.io as a source of PUBLISHED emails -- its Domain Search endpoint
and nothing else.

Hunter does two different things, and only one is allowed here:
  - Domain Search lists addresses its crawler actually saw on the public
    web, each with the pages ("sources") it saw them on. Allowed -- but an
    address is kept only if Hunter gives at least one source page for it,
    and that page's URL is stored as the email's source.
  - Email Finder, and the "pattern" field in a Domain Search answer
    ("{first}.{last}"), are Hunter's GUESS at an address nobody published.
    CLAUDE.md constraint 6 forbids guessed addresses, so this module never
    calls that endpoint and never reads that field (a test checks both).

Phone numbers and social links in Hunter's answer are ignored too.

The free plan allows a small number of searches a month, so:
  - every answer is cached in the tracker (`hunter_cache`), and a domain
    is only ever looked up once;
  - searches are counted per calendar month and stop at
    HUNTER_MONTHLY_LIMIT (default 25 -- check your plan on hunter.io);
  - if Hunter itself says the quota is used up, the run stops.
"""

from __future__ import annotations

import json
from typing import Optional

import requests

from internship_hunter import config, db
from internship_hunter.models import Company, Contact
from internship_hunter.people import dedupe, people_finder

DOMAIN_SEARCH_URL = "https://api.hunter.io/v2/domain-search"
FREE_PLAN_RESULTS = 10  # the free plan rejects limit + offset above 10
# Who is worth keeping when Hunter lists more people than we store per company.
DEPARTMENT_ORDER = ("it", "engineering", "executive", "management", "hr")


class HunterNotConfigured(RuntimeError):
    pass


class HunterLimitReached(RuntimeError):
    pass


# --- the monthly budget and the cache --------------------------------------

def searches_this_month(conn) -> int:
    return conn.execute(
        "SELECT COUNT(*) AS n FROM hunter_cache WHERE strftime('%Y-%m', fetched_at) = strftime('%Y-%m', 'now')"
    ).fetchone()["n"]


def remaining_this_month(conn) -> int:
    return max(0, config.HUNTER_MONTHLY_LIMIT - searches_this_month(conn))


def cached(conn, domain: str) -> Optional[dict]:
    row = conn.execute("SELECT response_json FROM hunter_cache WHERE domain = ?", (domain,)).fetchone()
    return json.loads(row["response_json"]) if row else None


def domain_search(conn, domain: str, get=requests.get) -> dict:
    """Hunter's answer for one domain: from the cache if we've ever asked,
    otherwise one real search (which uses one of the month's searches)."""
    hit = cached(conn, domain)
    if hit is not None:
        return hit
    if not config.HUNTER_API_KEY:
        raise HunterNotConfigured("HUNTER_API_KEY is not set in .env.")
    if remaining_this_month(conn) <= 0:
        raise HunterLimitReached(f"This month's {config.HUNTER_MONTHLY_LIMIT} Hunter searches are used up.")
    # The key goes in a header, not the URL, so it can't end up in a log line.
    response = get(
        DOMAIN_SEARCH_URL,
        params={"domain": domain, "limit": FREE_PLAN_RESULTS},
        headers={"X-API-KEY": config.HUNTER_API_KEY},
        timeout=people_finder.REQUEST_TIMEOUT,
    )
    if response.status_code == 429:
        raise HunterLimitReached("Hunter says this month's searches are used up.")
    if response.status_code == 401:
        raise HunterNotConfigured("Hunter rejected HUNTER_API_KEY -- check it in .env.")
    response.raise_for_status()
    data = response.json().get("data") or {}
    conn.execute(
        "INSERT OR REPLACE INTO hunter_cache (domain, fetched_at, response_json) VALUES (?, datetime('now'), ?)",
        (domain, json.dumps(data)),
    )
    conn.commit()
    return data


# --- which addresses may be kept -------------------------------------------

def source_uri(entry: dict) -> Optional[str]:
    """The page Hunter saw this address on -- one that still shows it if
    there is one. None means Hunter has no page for it, so it isn't kept."""
    sources = [
        s for s in entry.get("sources") or []
        if str(s.get("uri") or "").startswith(("http://", "https://")) and "linkedin.com" not in s["uri"].lower()
    ]
    if not sources:
        return None
    sources.sort(key=lambda s: not s.get("still_on_page"))
    return sources[0]["uri"]


def sourced_emails(data: dict, domain: str) -> list[dict]:
    """The addresses in a Domain Search answer that may be stored: on the
    company's own domain, with a source page. Each is
    {email, source, kind, name, title, department}."""
    kept = []
    for entry in data.get("emails") or []:
        email = str(entry.get("value") or "").strip().lower()
        uri = source_uri(entry)
        host = email.partition("@")[2]
        if not email or uri is None or (host != domain and not host.endswith("." + domain)):
            continue
        name = " ".join(p for p in (entry.get("first_name"), entry.get("last_name")) if p).strip()
        kept.append({
            "email": email, "source": uri, "kind": entry.get("type") or "",
            "name": name, "title": (entry.get("position") or "").strip(),
            "department": (entry.get("department") or "").lower(),
        })
    return kept


# --- storing ---------------------------------------------------------------

def apply_to_company(conn, company: Company, data: dict) -> list[tuple[str, str, str]]:
    """Store what a Domain Search answer gives for one company. Returns
    [(who, email, source)] for everything stored.

    - A person already on file with no email gets theirs.
    - A named person with a job title who isn't on file is added (up to
      MAX_CONTACTS_PER_COMPANY new people, engineering and leadership first).
    - A general inbox (careers@, info@) becomes the company's contact
      address if it has none."""
    domain = people_finder.company_domain(company.website)
    stored: list[tuple[str, str, str]] = []
    emails = sourced_emails(data, domain)
    rank = lambda e: DEPARTMENT_ORDER.index(e["department"]) if e["department"] in DEPARTMENT_ORDER else len(DEPARTMENT_ORDER)
    added = 0
    for entry in sorted(emails, key=rank):
        if people_finder.is_general_inbox(entry["email"]):
            if not company.contact_email:
                db.set_company_contact_email(conn, company.id, entry["email"])
                company.contact_email = entry["email"]
                stored.append((f"{company.name} (general inbox)", entry["email"], entry["source"]))
            continue
        if entry["kind"] != "personal" or len(entry["name"].split()) < 2:
            continue
        existing = dedupe.find_existing(conn, company.id, entry["name"])
        if existing is not None:
            if not existing.email:
                db.set_contact_email(conn, existing.id, entry["email"], entry["source"])
                stored.append((existing.name, entry["email"], entry["source"]))
            continue
        if not entry["title"] or added >= config.MAX_CONTACTS_PER_COMPANY:
            continue
        contact = Contact(
            company_id=company.id, name=entry["name"], title=entry["title"], source_url=entry["source"],
            fact="", email=entry["email"], email_source_url=entry["source"], source_kind="hunter",
        )
        contact.id = db.insert_contact(conn, contact)
        db.set_contact_email(conn, contact.id, entry["email"], entry["source"])
        added += 1
        stored.append((entry["name"], entry["email"], entry["source"]))
    return stored


def companies_to_search(conn, any_state: bool = False) -> list[Company]:
    """Companies with a website whose domain has never been looked up, best
    tier first -- Colorado/Virginia only unless any_state."""
    return [
        c for c in db.list_companies(conn)
        if c.priority_tier != 4 and c.website
        and (any_state or c.state in config.PREFERRED_STATES)
        and cached(conn, people_finder.company_domain(c.website)) is None
    ]


def run(conn, limit: int, any_state: bool = False, get=requests.get) -> list[tuple[Company, list]]:
    """Look up to `limit` new companies (never more than the month has
    left). Returns [(company, what was stored)]. Stops quietly when the
    month's searches run out."""
    results = []
    for company in companies_to_search(conn, any_state)[: min(limit, remaining_this_month(conn))]:
        try:
            data = domain_search(conn, people_finder.company_domain(company.website), get)
        except HunterLimitReached:
            break
        results.append((company, apply_to_company(conn, company, data)))
    return results
