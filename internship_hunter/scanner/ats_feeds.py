"""Fetches postings from the public JSON feeds of the three applicant
tracking systems CLAUDE.md allows (Greenhouse, Lever, Ashby) -- never from
scraping a logged-in view, and never submitting anything.

Companies don't publish which ATS they use, and their "board slug" on that
ATS doesn't always match their public name. So this module tries a handful
of reasonable slug guesses against all three vendors, keeps every one that
comes back valid, and the scanner caches whichever one(s) worked on the
company record so future runs skip straight to the known endpoint.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import requests

GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
LEVER_URL = "https://api.lever.co/v0/postings/{slug}?mode=json"
ASHBY_URL = "https://api.ashbyhq.com/posting-api/job-board/{slug}"

REQUEST_TIMEOUT = 10


@dataclass
class RawPosting:
    external_id: str
    title: str
    location: str
    url: str
    text: str  # title + location + description, for keyword filtering
    ats_source: str


def slug_candidates(company_name: str) -> list[str]:
    """Generate plausible ATS board-slug guesses for a company name, ordered
    most-to-least likely based on empirical testing against real companies
    (e.g. 'Anduril Industries' -> 'andurilindustries' matched on the first
    try; keeping corporate suffixes attached tends to work better than
    stripping them).

    Deliberately does NOT include a bare-first-word guess (e.g. just
    "sierra" for "Sierra Space") -- that was tried and it actually matched a
    *different* company's real board on Ashby (an unrelated "Sierra" with
    open roles in SF/Singapore), silently mixing a stranger's job postings
    into Sierra Space's record. A missed company is far cheaper than wrong
    data, so every remaining candidate here is still distinctive enough to
    plausibly belong to this company specifically."""
    lower = company_name.lower()
    alnum_only = re.sub(r"[^a-z0-9]+", "", lower)
    hyphenated = re.sub(r"[^a-z0-9]+", "-", lower).strip("-")

    # A few common corporate-suffix-stripped variants, in case the full name
    # doesn't match (e.g. "Foo Inc" -> "foo").
    stripped = lower
    for suffix in (" inc", " llc", " corp", " corporation", " co", " technologies", " systems"):
        if stripped.endswith(suffix):
            stripped = stripped[: -len(suffix)]
    stripped_alnum = re.sub(r"[^a-z0-9]+", "", stripped)

    candidates = [alnum_only, hyphenated, stripped_alnum]
    # De-dupe while preserving order.
    seen = set()
    ordered = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            ordered.append(c)
    return ordered


def _try_greenhouse(slug: str) -> list[RawPosting] | None:
    try:
        resp = requests.get(GREENHOUSE_URL.format(slug=slug), timeout=REQUEST_TIMEOUT)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    try:
        jobs = resp.json().get("jobs", [])
    except ValueError:
        return None
    postings = []
    for job in jobs:
        location = (job.get("location") or {}).get("name", "")
        content = job.get("content", "") or ""
        postings.append(
            RawPosting(
                external_id=str(job.get("id")),
                title=job.get("title", ""),
                location=location,
                url=job.get("absolute_url", ""),
                text=f"{job.get('title', '')} {location} {content}",
                ats_source="greenhouse",
            )
        )
    return postings


def _try_lever(slug: str) -> list[RawPosting] | None:
    try:
        resp = requests.get(LEVER_URL.format(slug=slug), timeout=REQUEST_TIMEOUT)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    try:
        jobs = resp.json()
    except ValueError:
        return None
    if not isinstance(jobs, list):
        return None
    postings = []
    for job in jobs:
        categories = job.get("categories", {}) or {}
        location = categories.get("location", "")
        description = job.get("descriptionPlain", "") or job.get("description", "") or ""
        # Lever splits requirement bullets (where clearance/citizenship text
        # usually lives) into a separate "lists" field -- e.g. a "What We
        # Require" block -- rather than folding them into the description.
        # Missing this meant a clearance-required posting's own clearance
        # sentence was invisible to requires_clearance(). Found by actually
        # inspecting a real Palantir "US Government" posting's JSON.
        list_text = " ".join(
            f"{item.get('text', '')} {item.get('content', '')}" for item in (job.get("lists") or [])
        )
        postings.append(
            RawPosting(
                external_id=str(job.get("id")),
                title=job.get("text", ""),
                location=location,
                url=job.get("hostedUrl", ""),
                text=f"{job.get('text', '')} {location} {description} {list_text}",
                ats_source="lever",
            )
        )
    return postings


def _try_ashby(slug: str) -> list[RawPosting] | None:
    try:
        resp = requests.get(ASHBY_URL.format(slug=slug), timeout=REQUEST_TIMEOUT)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    try:
        jobs = resp.json().get("jobs", [])
    except ValueError:
        return None
    postings = []
    for job in jobs:
        location = job.get("location", "") or job.get("locationName", "")
        description = job.get("descriptionPlain", "") or ""
        postings.append(
            RawPosting(
                external_id=str(job.get("id")),
                title=job.get("title", ""),
                location=location,
                url=job.get("jobUrl", "") or job.get("applyUrl", ""),
                text=f"{job.get('title', '')} {location} {description}",
                ats_source="ashby",
            )
        )
    return postings


_FETCHERS = {
    "greenhouse": _try_greenhouse,
    "lever": _try_lever,
    "ashby": _try_ashby,
}


def fetch_known(ats_type: str, ats_slug: str) -> list[RawPosting]:
    """Fetch postings for a company whose ATS vendor+slug are already known
    (cached on the company record). Returns [] if the feed errors out."""
    fetcher = _FETCHERS.get(ats_type)
    if fetcher is None:
        return []
    return fetcher(ats_slug) or []


def detect_and_fetch(company_name: str) -> tuple[list[RawPosting], list[tuple[str, str]]]:
    """Try every slug candidate against every vendor. Returns
    (all postings found, [(ats_type, slug), ...] of every vendor+slug that
    came back valid -- usually just one, but merged if a company happens to
    have more than one live board)."""
    all_postings: list[RawPosting] = []
    confirmed: list[tuple[str, str]] = []
    for slug in slug_candidates(company_name):
        for ats_type, fetcher in _FETCHERS.items():
            result = fetcher(slug)
            if result is not None:
                confirmed.append((ats_type, slug))
                all_postings.extend(result)
    return all_postings, confirmed
