from pathlib import Path

from internship_hunter.apply_assist import playwright_fill
from internship_hunter.models import Posting


def make_posting(**overrides) -> Posting:
    defaults = dict(
        company_id=1, external_id="1", title="Software Engineer Intern",
        location="Remote", url="https://jobs.lever.co/foo/abc123", ats_source="lever",
    )
    defaults.update(overrides)
    return Posting(**defaults)


def test_source_clicks_only_through_the_guarded_helper():
    # CLAUDE.md constraint 4: never auto-submit. The file contains exactly
    # one real click call, inside _safe_click, which first checks
    # click_allowed -- so there is no way to click anything else.
    source = Path(playwright_fill.__file__).read_text(encoding="utf-8")
    assert source.count(".click(") == 1
    guarded = source.split("def _safe_click")[1].split("\ndef ")[0]
    assert "click_allowed(" in guarded and ".click(" in guarded
    assert ".press(" not in source.replace("keyboard.press(\"Escape\")", "")


def test_click_allowed_only_for_dropdowns_and_their_options():
    assert playwright_fill.click_allowed("INPUT", "text", "combobox")
    assert playwright_fill.click_allowed("DIV", "", "option")
    # Never a button or a submit control, whatever role it claims.
    assert not playwright_fill.click_allowed("BUTTON", "submit", "")
    assert not playwright_fill.click_allowed("BUTTON", "", "option")
    assert not playwright_fill.click_allowed("INPUT", "submit", "combobox")
    assert not playwright_fill.click_allowed("A", "", "")
    assert not playwright_fill.click_allowed("DIV", "", "button")


def test_resolve_apply_url_appends_apply_for_lever():
    posting = make_posting(ats_source="lever", url="https://jobs.lever.co/foo/abc123")
    assert playwright_fill.resolve_apply_url(posting) == "https://jobs.lever.co/foo/abc123/apply"


def test_resolve_apply_url_does_not_double_append():
    posting = make_posting(ats_source="lever", url="https://jobs.lever.co/foo/abc123/apply")
    assert playwright_fill.resolve_apply_url(posting) == "https://jobs.lever.co/foo/abc123/apply"


def test_resolve_apply_url_leaves_greenhouse_url_unchanged():
    posting = make_posting(ats_source="greenhouse", url="https://boards.greenhouse.io/foo/jobs/123")
    assert playwright_fill.resolve_apply_url(posting) == "https://boards.greenhouse.io/foo/jobs/123"


def test_resolve_apply_url_leaves_ashby_url_unchanged():
    posting = make_posting(ats_source="ashby", url="https://jobs.ashbyhq.com/foo/abc")
    assert playwright_fill.resolve_apply_url(posting) == "https://jobs.ashbyhq.com/foo/abc"


def test_label_for_locator_strips_required_marker_asterisk():
    # Regression: get_by_label("First Name*") never matched Greenhouse's
    # real form live -- the "*" is visible in the label but not part of
    # the input's actual accessible name. Confirmed by hand against a real
    # posting: stripping it made the lookup succeed immediately.
    assert playwright_fill._label_for_locator("First Name*") == "First Name"
    assert playwright_fill._label_for_locator("Current location \u2731") == "Current location"


def test_label_for_locator_leaves_plain_labels_unchanged():
    assert playwright_fill._label_for_locator("Phone") == "Phone"
    assert playwright_fill._label_for_locator("GitHub") == "GitHub"
