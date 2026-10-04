"""Pure field-mapping logic: given the label texts found on a real
application form, decide which ones to fill and with what. No Playwright
or network access in this file at all -- that's what makes it unit-
testable against plain fixture HTML (see tests/test_field_map.py).

The keyword lists below come from actually inspecting three real,
currently-live postings (one Greenhouse new-UI, one Greenhouse legacy-UI,
one Lever) with Playwright, not from guessing -- see the Phase 5 build
notes. Deliberately a short allow-list, not a catch-all: anything not on
it (EEO/demographic questions, clearance/work-authorization questions,
cover letters, "how did you hear about us") is left for the student to
answer, because those need his judgment, not a guess.
"""

from __future__ import annotations

from typing import Optional

from bs4 import BeautifulSoup

from internship_hunter.apply_assist.profile_fields import ApplicantInfo

RESUME_SENTINEL = "__resume_file__"

# Ordered most-specific-first so "full name" doesn't get shadowed by a
# broader rule, and so a label never matches more than one field.
LABEL_KEYWORD_MAP: list[tuple[tuple[str, ...], str]] = [
    (("first name",), "first_name"),
    (("last name",), "last_name"),
    (("full name", "your name"), "full_name"),
    (("email",), "email"),
    (("phone",), "phone"),
    (("github",), "github_url"),
    (("portfolio", "personal site", "personal website"), "portfolio_url"),
    (("website",), "portfolio_url"),
    (("current location", "location"), "location"),
    (("resume", "cv"), RESUME_SENTINEL),
]

# Common selectors for the resume file input, tried in order -- Greenhouse
# consistently uses id="resume" (confirmed on two different postings);
# Lever uses name="resume". Neither has real <label> text pointing at it
# (Greenhouse's visible text is just "Attach"/"Enter manually" toggle
# buttons), so this can't be done through label matching at all.
RESUME_FILE_SELECTORS = ["#resume", "input[name='resume']", "input[type='file']"]


def classify_label(label_text: str) -> Optional[str]:
    """Map one label's text to an ApplicantInfo field name, or
    RESUME_SENTINEL, or None if it's not something we auto-fill."""
    text = label_text.lower()
    for keywords, field in LABEL_KEYWORD_MAP:
        if any(kw in text for kw in keywords):
            return field
    return None


def build_fill_plan(labels: list[str], applicant: ApplicantInfo) -> list[tuple[str, str]]:
    """Given every label found on the form, return (label_text, value)
    pairs worth filling -- skips the resume sentinel (handled separately by
    selector, not label), fields we don't recognize, and fields we
    recognize but have no value for (e.g. no LinkedIn, no current employer
    -- left blank rather than guessed)."""
    plan = []
    seen_fields = set()
    for label in labels:
        field = classify_label(label)
        if field is None or field == RESUME_SENTINEL or field in seen_fields:
            continue
        value = getattr(applicant, field, "")
        if value:
            plan.append((label, value))
            seen_fields.add(field)
    return plan


def unmatched_labels(labels: list[str]) -> list[str]:
    """Labels that aren't on the auto-fill allow-list at all -- screening
    questions, EEO/demographic questions, cover letters, etc. Reported to
    the student so nothing is silently skipped without them knowing."""
    return [label for label in labels if classify_label(label) is None]


def extract_labels_from_html(html: str) -> list[str]:
    """Pull every <label> element's text out of a page's HTML. Used both
    by tests (against fixture HTML, no browser) and conceptually mirrors
    what the live Playwright driver does against a real page's DOM."""
    soup = BeautifulSoup(html, "html.parser")
    return [label.get_text(strip=True) for label in soup.find_all("label") if label.get_text(strip=True)]
