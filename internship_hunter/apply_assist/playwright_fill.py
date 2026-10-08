"""Phase 5: open a real application page, fill the fields we have real
values for, attach the resume if one exists, and then STOP -- never clicks
a Submit button. The student reviews everything in the still-open browser
window and submits it himself. See CLAUDE.md constraint 4.

Clicking is confined to one function, _safe_click, which refuses anything
that isn't a dropdown or one of its options (see click_allowed) -- that's
what lets dropdowns be answered without any path to a Submit button.

Vendor quirk handled here (found by actually loading real postings, not
assumed): Lever's apply form lives at <posting-url>/apply, a separate page
from the posting description -- the fields are NOT on the page the scanner
stored the URL for.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright

from internship_hunter.apply_assist import choices, field_map
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


# For each <label>, what kind of control it belongs to. This matters because
# a real form's labels are mostly NOT questions: on a live Palantir/Lever
# form 58 of 82 labels were checkbox options ("Spanish (SPA)", "Yes", "No")
# and two were the "Name"/"Date" boxes of a signature block. Only a label
# sitting on a typeable box can be an open-ended question. A text input
# with role="combobox" is Greenhouse's dropdown widget, so it counts as a
# select, not as something to type an answer into.
_FIELD_KINDS_JS = """els => els.map(e => {
    const c = e.control;
    let kind = 'none';
    if (c) {
        if (c.tagName === 'TEXTAREA') kind = 'textarea';
        else if (c.tagName === 'SELECT' || c.getAttribute('role') === 'combobox') kind = 'select';
        else kind = (c.type || 'text').toLowerCase();
    }
    return {text: e.innerText.trim(), kind};
}).filter(d => d.text)"""


def _open_form(page, url: str) -> None:
    """Navigate and wait for the form to render. Waiting for the network
    to go fully quiet is only best-effort: a live Shield AI/Lever page kept
    a background request open forever and timed out a plain
    wait_until="networkidle" navigation, though its form had long since
    loaded."""
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass
    page.wait_for_timeout(1000)  # let any late-rendering JS widgets settle


def extract_live_fields(page) -> list[tuple[str, str]]:
    return [(d["text"], d["kind"]) for d in page.eval_on_selector_all("label", _FIELD_KINDS_JS)]


# Every multiple-choice question on the page, in three shapes:
#   select   -- a native <select>; its options are right there in the HTML
#   combobox -- Greenhouse's search-style dropdown; its options only exist
#               once it has been opened, so `options` is null
#   radio    -- a group of radio buttons sharing a name; the question text
#               is the group's heading (Lever: ".application-label")
# Each control gets a data-ih attribute so the filler can find exactly the
# element this script saw, instead of re-guessing it from label text.
_CHOICE_QUESTIONS_JS = """() => {
    const text = e => ((e && e.innerText) || '').trim();
    const out = [];
    let n = 0;
    document.querySelectorAll('label').forEach(label => {
        const c = label.control;
        if (!c) return;
        const isSelect = c.tagName === 'SELECT';
        if (!isSelect && c.getAttribute('role') !== 'combobox') return;
        const id = 'c' + (n++);
        c.setAttribute('data-ih', id);
        out.push({
            question: text(label).split('\\n')[0].trim(),
            kind: isSelect ? 'select' : 'combobox',
            target: id,
            options: isSelect ? [...c.options].map(o => o.text.trim()).filter(Boolean) : null,
        });
    });
    const groups = new Map();
    document.querySelectorAll('input[type=radio]').forEach(input => {
        if (!input.name) return;
        if (!groups.has(input.name)) groups.set(input.name, []);
        groups.get(input.name).push(input);
    });
    groups.forEach(inputs => {
        // Lever wraps each OPTION in its own <li>, so look for the question's
        // container first; a bare closest('li') would return the option itself.
        const box = inputs[0].closest('.application-question')
            || inputs[0].closest('fieldset, [role=radiogroup], [role=group]')
            || inputs[0].closest('li');
        const head = box && box.querySelector('legend, .application-label');
        const question = (text(head) || text(box)).split('\\n')[0].trim();
        const options = [], targets = [];
        inputs.forEach(input => {
            const id = 'c' + (n++);
            input.setAttribute('data-ih', id);
            const own = input.closest('label') || (input.id && document.querySelector('label[for="' + input.id + '"]'));
            options.push(text(own) || input.value);
            targets.push(id);
        });
        out.push({question, kind: 'radio', targets, options});
    });
    return out;
}"""


def extract_choice_questions(page) -> list[dict]:
    return page.evaluate(_CHOICE_QUESTIONS_JS)


def fetch_form(posting: Posting) -> tuple[list[tuple[str, str]], list[dict]]:
    """Load the application page in a hidden browser just long enough to
    read its fields -- (label, kind) pairs plus its multiple-choice
    questions -- then close it. Used when a posting is first put in the
    approval queue, so the card can show what will be filled in. Fills
    nothing."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            _open_form(page, resolve_apply_url(posting))
            return extract_live_fields(page), extract_choice_questions(page)
        finally:
            browser.close()


TYPED_KINDS = ("text", "number")  # one-line boxes a standing answer may be typed into


class RefusedClick(RuntimeError):
    pass


def click_allowed(tag: str, input_type: str, role: str) -> bool:
    """The ONLY things this module may ever click: a dropdown's own input
    (to open it) and one of the options it then lists. Buttons and submit
    inputs are refused outright, so no code path here can submit a form
    (CLAUDE.md constraint 4)."""
    if tag.upper() == "BUTTON" or input_type.lower() in ("submit", "button", "image", "reset"):
        return False
    return role in ("combobox", "option")


def _safe_click(locator) -> None:
    info = locator.evaluate(
        "e => ({tag: e.tagName, type: e.getAttribute('type') || '', role: e.getAttribute('role') || ''})"
    )
    if not click_allowed(info["tag"], info["type"], info["role"]):
        raise RefusedClick(f"refusing to click a {info['tag']} (type={info['type']!r}, role={info['role']!r})")
    locator.click(timeout=3000)


def _options_of(page, box):
    """The options listed by THIS dropdown. A dropdown names its own list in
    aria-controls; reading every [role=option] on the page instead can pick
    up another dropdown's list that is still open (seen live: the phone
    country list showing up as the options of every later question)."""
    listbox_id = box.get_attribute("aria-controls")
    if listbox_id:
        return page.locator(f'[id="{listbox_id}"] [role="option"]')
    return page.locator('[role="option"]')


def _pick_from_combobox(page, box, candidates: list[str]) -> Optional[str]:
    """Open a search-style dropdown, type each acceptable answer in turn,
    and choose the listed option that matches. Leaves it empty if none does."""
    _safe_click(box)
    for candidate in candidates:
        box.fill(candidate)
        page.wait_for_timeout(500)
        listed = _options_of(page, box)
        texts = [t.strip() for t in listed.all_inner_texts()]
        picked = choices.pick_option(texts, [candidate])
        if picked:
            _safe_click(listed.nth(texts.index(picked)))
            return picked
    box.fill("")
    page.keyboard.press("Escape")
    return None


def fill_choices(page, decide) -> list[str]:
    """Answer the multiple-choice questions that `decide(question)` has a
    standing answer for (see apply_assist/choices.py). Returns
    "question -> answer" strings for what was actually selected."""
    selected = []
    for q in extract_choice_questions(page):
        candidates = decide(q["question"])
        if not candidates:
            continue
        try:
            if q["kind"] == "select":
                picked = choices.pick_option(q["options"], candidates)
                if picked:
                    page.locator(f'[data-ih="{q["target"]}"]').select_option(label=picked, timeout=3000)
            elif q["kind"] == "radio":
                picked = choices.pick_option(q["options"], candidates)
                if picked:
                    target = q["targets"][q["options"].index(picked)]
                    page.locator(f'[data-ih="{target}"]').check(timeout=3000, force=True)
            else:
                picked = _pick_from_combobox(page, page.locator(f'[data-ih="{q["target"]}"]'), candidates)
        except Exception:
            continue  # one stubborn widget shouldn't stop the rest; it's left for him
        if picked:
            selected.append(f"{q['question']} -> {picked}")
    return selected


# What an ATS shows once an application has really gone through. Greenhouse
# lands on a ".../confirmation" URL and Lever on ".../thanks"; the phrases
# cover boards that keep the same URL and just swap the page content.
CONFIRMATION_URL_HINTS = ("/confirmation", "/thanks")
CONFIRMATION_TEXT_HINTS = (
    "thank you for applying", "thanks for applying", "application has been submitted",
    "application was submitted", "application submitted", "received your application",
    "application has been received",
)


def looks_like_confirmation(url: str, page_text: str) -> bool:
    lowered_url = (url or "").lower().split("?")[0].rstrip("/")
    if any(lowered_url.endswith(hint) for hint in CONFIRMATION_URL_HINTS):
        return True
    lowered_text = (page_text or "").lower()
    return any(hint in lowered_text for hint in CONFIRMATION_TEXT_HINTS)


# What each multiple-choice question is currently set to. Read while he
# works on the form, so the answers he picks himself can be remembered
# (apply_assist/my_answers.py) and filled in for him next time.
_CURRENT_ANSWERS_JS = """() => {
    const text = e => ((e && e.innerText) || '').trim();
    const out = {};
    document.querySelectorAll('label').forEach(label => {
        const c = label.control;
        if (!c) return;
        const question = text(label).split('\\n')[0].trim();
        if (c.tagName === 'SELECT') {
            const chosen = c.options[c.selectedIndex];
            out[question] = chosen && chosen.value ? chosen.text.trim() : '';
        } else if (c.getAttribute('role') === 'combobox') {
            const control = c.closest('[class*="control"]');
            out[question] = text(control && control.querySelector('[class*="single-value"], [class*="singleValue"]'));
        }
    });
    const groups = new Map();
    document.querySelectorAll('input[type=radio]').forEach(input => {
        if (!input.name) return;
        if (!groups.has(input.name)) groups.set(input.name, []);
        groups.get(input.name).push(input);
    });
    groups.forEach(inputs => {
        const box = inputs[0].closest('.application-question')
            || inputs[0].closest('fieldset, [role=radiogroup], [role=group]')
            || inputs[0].closest('li');
        const head = box && box.querySelector('legend, .application-label');
        const question = (text(head) || text(box)).split('\\n')[0].trim();
        const picked = inputs.find(i => i.checked);
        const own = picked && (picked.closest('label') || (picked.id && document.querySelector('label[for="' + picked.id + '"]')));
        out[question] = picked ? (text(own) || picked.value) : '';
    });
    return out;
}"""


def wait_until_closed(page, summary: Optional[dict] = None) -> bool:
    """Block until the student closes the browser window, watching (never
    touching) the page meanwhile. Returns True if a submission-confirmation
    page showed up at any point, i.e. he submitted it himself. If `summary`
    is given, summary["observed"] ends up holding what each multiple-choice
    question was set to the last time the form was still on screen."""
    confirmed = False
    while True:
        try:
            if page.is_closed():
                break
            if summary is not None:
                current = page.evaluate(_CURRENT_ANSWERS_JS)
                if current:  # the confirmation page has no form; keep the last real reading
                    summary["observed"] = current
            if looks_like_confirmation(page.url, page.inner_text("body", timeout=2000)):
                confirmed = True
            page.wait_for_timeout(1500)
        except Exception:
            break  # window or whole browser was closed mid-check
    return confirmed


def _wait_for_enter(page, summary: Optional[dict] = None) -> bool:
    input(
        "\nThe browser window is open with the form filled in as far as it safely could be. "
        "This script will NEVER click Submit for you -- review everything yourself, answer "
        "anything left blank, and submit it in the browser if you're ready.\n"
        "Press Enter here once you're done (the browser will close) ..."
    )
    return False


def fill_application(
    posting: Posting,
    applicant: ApplicantInfo,
    resume_path: Optional[Path] = None,
    headless: bool = False,
    extra_answers: Optional[dict] = None,
    wait_for_human=_wait_for_enter,
    decide_choice=choices.candidates_for,
) -> dict:
    """Open the real application page, fill what we can, and pause for
    human review. Returns a summary dict (filled/skipped/resume_attached/
    confirmation_seen) -- never submits anything itself.

    extra_answers maps a form label to a drafted answer the student already
    approved (see apply_assist/answers.py). wait_for_human decides how the
    pause ends: the CLI waits for Enter, the Telegram bot passes
    wait_until_closed so it can run with no terminal attached."""
    url = resolve_apply_url(posting)
    summary = {"url": url, "filled": [], "skipped": [], "resume_attached": False, "confirmation_seen": False}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        page = browser.new_page()
        _open_form(page, url)

        def decide(question: str) -> list[str]:
            return decide_choice(question, posting_location=posting.location)

        labels = extract_live_labels(page)
        plan = field_map.build_fill_plan(labels, applicant)
        for label_text, value in plan:
            try:
                page.get_by_label(_label_for_locator(label_text), exact=False).first.fill(value, timeout=5000)
                summary["filled"].append(label_text)
            except Exception:
                summary["skipped"].append(label_text)

        answered = set()
        for label_text, answer in (extra_answers or {}).items():
            try:
                page.get_by_label(_label_for_locator(label_text), exact=False).first.fill(answer, timeout=5000)
                summary["filled"].append(label_text)
                answered.add(label_text)
            except Exception:
                pass  # not a typeable field on this visit -- stays in "skipped" below

        # One-line boxes with a standing answer (graduation year, city, zip...).
        for label_text, kind in extract_live_fields(page):
            if kind not in TYPED_KINDS or label_text in answered or field_map.classify_label(label_text) is not None:
                continue
            candidates = decide(label_text)
            if not candidates:
                continue
            try:
                page.get_by_label(_label_for_locator(label_text), exact=False).first.fill(candidates[0], timeout=5000)
                summary["filled"].append(label_text)
                answered.add(label_text)
            except Exception:
                pass

        # Dropdowns and radio buttons with a standing answer (choices.py).
        summary["selected"] = fill_choices(page, decide)
        chosen = {line.split(" -> ")[0] for line in summary["selected"]}

        summary["skipped"].extend(
            l for l in field_map.unmatched_labels(labels) if l not in answered and l not in chosen
        )

        if resume_path and resume_path.exists():
            summary["resume_attached"] = fill_resume(page, resume_path)

        print(f"\nFilled: {summary['filled']}")
        print(f"Selected: {summary['selected']}")
        if summary["resume_attached"]:
            print(f"Resume attached: {resume_path}")
        elif resume_path:
            print(f"Could not find a resume upload field to attach {resume_path} to.")
        if summary["skipped"]:
            print(f"\nLeft for you to answer/review: {summary['skipped']}")
        summary["confirmation_seen"] = bool(wait_for_human(page, summary))
        try:
            browser.close()
        except Exception:
            pass

    return summary
