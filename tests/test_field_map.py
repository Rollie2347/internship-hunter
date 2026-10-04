from internship_hunter.apply_assist import field_map
from internship_hunter.apply_assist.profile_fields import ApplicantInfo

# Modeled directly on real labels pulled from a live Greenhouse posting
# (Defense Unicorns) during Phase 5 build/research.
GREENHOUSE_FIXTURE_HTML = """
<form>
  <label for="first_name">First Name*</label><input id="first_name">
  <label for="last_name">Last Name*</label><input id="last_name">
  <label for="email">Email*</label><input id="email">
  <label for="phone">Phone</label><input id="phone">
  <label>Attach</label><label>Enter manually</label><input id="resume" type="file">
  <label>GitHub</label><input id="question_1">
  <label>Website</label><input id="question_2">
  <label>How did you hear about us?</label><input id="question_3">
</form>
"""

# Modeled on real labels pulled from Lever's /apply page (Palantir posting).
LEVER_FIXTURE_HTML = """
<form>
  <label>Resume/CV &#9985; ATTACH RESUME/CV</label><input name="resume" type="file">
  <label>Full name &#9985;</label><input name="name">
  <label>Email &#9985;</label><input name="email">
  <label>Phone</label><input name="phone">
  <label>Current location &#9985;</label><input name="location">
  <label>Current company</label><input name="org">
  <label>LinkedIn URL</label><input name="urls[LinkedIn]">
  <label>GitHub URL</label><input name="urls[GitHub]">
  <label>Portfolio URL</label><input name="urls[Portfolio]">
</form>
"""


def make_applicant(**overrides) -> ApplicantInfo:
    defaults = dict(
        first_name="Jane", last_name="Doe", full_name="Jane Doe",
        email="jane@example.com", phone="555-123-4567",
        github_url="https://github.com/janedoe", portfolio_url="https://janedoe.dev",
        location="Wisconsin",
    )
    defaults.update(overrides)
    return ApplicantInfo(**defaults)


def test_extract_labels_from_greenhouse_style_fixture():
    labels = field_map.extract_labels_from_html(GREENHOUSE_FIXTURE_HTML)
    assert "First Name*" in labels
    assert "Email*" in labels
    assert "GitHub" in labels


def test_extract_labels_from_lever_style_fixture():
    labels = field_map.extract_labels_from_html(LEVER_FIXTURE_HTML)
    assert any("Full name" in l for l in labels)
    assert any("Portfolio URL" in l for l in labels)


def test_classify_label_matches_expected_fields():
    assert field_map.classify_label("First Name*") == "first_name"
    assert field_map.classify_label("Last Name*") == "last_name"
    assert field_map.classify_label("Full name \u2731") == "full_name"
    assert field_map.classify_label("Email*") == "email"
    assert field_map.classify_label("Phone") == "phone"
    assert field_map.classify_label("GitHub URL") == "github_url"
    assert field_map.classify_label("Portfolio URL") == "portfolio_url"
    assert field_map.classify_label("Website") == "portfolio_url"
    assert field_map.classify_label("Current location \u2731") == "location"
    assert field_map.classify_label("Resume/CV") == field_map.RESUME_SENTINEL


def test_classify_label_does_not_match_screening_questions():
    assert field_map.classify_label("How did you hear about us?") is None
    assert field_map.classify_label("Do you require visa sponsorship?") is None
    assert field_map.classify_label("LinkedIn URL") is None  # he has none -- never auto-filled


def test_build_fill_plan_fills_only_known_fields_with_real_values():
    applicant = make_applicant()
    labels = field_map.extract_labels_from_html(GREENHOUSE_FIXTURE_HTML)
    plan = field_map.build_fill_plan(labels, applicant)
    plan_dict = dict(plan)
    assert plan_dict["First Name*"] == "Jane"
    assert plan_dict["Email*"] == "jane@example.com"
    assert plan_dict["GitHub"] == "https://github.com/janedoe"
    assert "How did you hear about us?" not in plan_dict


def test_build_fill_plan_skips_the_resume_sentinel():
    applicant = make_applicant()
    labels = field_map.extract_labels_from_html(GREENHOUSE_FIXTURE_HTML)
    plan = field_map.build_fill_plan(labels, applicant)
    labels_in_plan = [label for label, _ in plan]
    assert "Attach" not in labels_in_plan


def test_build_fill_plan_skips_fields_with_no_value():
    applicant = make_applicant(portfolio_url="")
    labels = field_map.extract_labels_from_html(GREENHOUSE_FIXTURE_HTML)
    plan = field_map.build_fill_plan(labels, applicant)
    assert "Website" not in dict(plan)


def test_build_fill_plan_on_lever_fixture_fills_expected_fields():
    applicant = make_applicant()
    labels = field_map.extract_labels_from_html(LEVER_FIXTURE_HTML)
    plan = field_map.build_fill_plan(labels, applicant)
    plan_dict = {k.split("\n")[0]: v for k, v in plan}
    assert any("Full name" in k for k in plan_dict)
    assert any("Current location" in k for k in plan_dict)
    # LinkedIn is a real, known label here but must never be auto-filled.
    assert not any("LinkedIn" in k for k in plan_dict)


def test_unmatched_labels_reports_screening_questions():
    labels = field_map.extract_labels_from_html(GREENHOUSE_FIXTURE_HTML)
    unmatched = field_map.unmatched_labels(labels)
    assert "How did you hear about us?" in unmatched
    assert "First Name*" not in unmatched
