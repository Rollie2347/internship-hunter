"""Phase 5: open a real application page, fill the fields we have real
values for, attach the resume if one exists, and then STOP -- never clicks
a Submit button, and never calls a click method on anything at all. The
student reviews everything in the still-open browser window and submits
it himself. See CLAUDE.md constraint 4.

Vendor quirk handled here (found by actually loading real postings, not
assumed): Lever's apply form lives at <posting-url>/apply, a separate page
from the posting description -- the fields are NOT on the page the scanner
stored the URL for.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright

from internship_hunter.apply_assist import field_map
from internship_hunter.apply_assist.profile_fields import ApplicantInfo
from internship_hunter.models import Posting


def resolve_apply_url(posting: Posting) -> str:
    """Lever postings describe the role at one URL but host the actual
    application form at <that-url>/apply -- confirmed by inspecting a real
    live Palantir/Lever posting, where the main page has zero form fields
    at all until you follow its "Apply" link to that second page."""
    if posting.ats_source == "lever" and not posting.url.rstrip("/").endswith("/apply"):
        return posting.url.rstrip("/") + "/apply"
    return posting.url


def extract_live_labels(page) -> list[str]:
    return page.eval_on_selector_all(
        "label", "els => els.map(e => e.innerText.trim()).filter(Boolean)"
    )


# Required-field markers (a trailing "*" or similar) are part of the visible
# label text but NOT part of the input's actual accessible name on at least
# Greenhouse's forms -- found live: get_by_label("First Name*") timed out
# and never matched, while get_by_label("First Name") (no marker) matched
# immediately. Strip these before using a label to locate its input;
# field_map's classification logic is unaffected since its keyword checks
# already tolerate trailing junk via substring matching.
REQUIRED_MARKER_CHARS = "*✱☆✪ \t\n"


def _label_for_locator(label_text: str) -> str:
    return label_text.rstrip(REQUIRED_MARKER_CHARS)


def fill_resume(page, resume_path: Path) -> bool:
    """Try each known resume-upload selector in turn; return True on the
    first one that exists and accepts the file."""
    for selector in field_map.RESUME_FILE_SELECTORS:
        locator = page.locator(selector).first
        if locator.count() == 0:
            continue
        try:
            locator.set_input_files(str(resume_path))
            return True
        except Exception:
            continue
    return False


def fill_application(
    posting: Posting,
    applicant: ApplicantInfo,
    resume_path: Optional[Path] = None,
    headless: bool = False,
) -> dict:
    """Open the real application page, fill what we can, and pause for
    human review. Returns a summary dict (filled/skipped/resume_attached)
    for the CLI to print -- never submits anything itself."""
    url = resolve_apply_url(posting)
    summary = {"url": url, "filled": [], "skipped": [], "resume_attached": False}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1000)  # let any late-rendering JS widgets settle

        labels = extract_live_labels(page)
        plan = field_map.build_fill_plan(labels, applicant)
        for label_text, value in plan:
            try:
                page.get_by_label(_label_for_locator(label_text), exact=False).first.fill(value, timeout=5000)
                summary["filled"].append(label_text)
            except Exception:
                summary["skipped"].append(label_text)

        summary["skipped"].extend(field_map.unmatched_labels(labels))

        if resume_path and resume_path.exists():
            summary["resume_attached"] = fill_resume(page, resume_path)

        print(f"\nFilled: {summary['filled']}")
        if summary["resume_attached"]:
            print(f"Resume attached: {resume_path}")
        elif resume_path:
            print(f"Could not find a resume upload field to attach {resume_path} to.")
        if summary["skipped"]:
            print(f"\nLeft for you to answer/review: {summary['skipped']}")
        input(
            "\nThe browser window is open with the form filled in as far as it safely could be. "
            "This script will NEVER click Submit for you -- review everything yourself, answer "
            "anything left blank, and submit it in the browser if you're ready.\n"
            "Press Enter here once you're done (the browser will close) ..."
        )
        try:
            browser.close()
        except Exception:
            pass

    return summary
