from internship_hunter.scanner import filters


def test_is_software_role_true_for_obvious_titles():
    assert filters.is_software_role("Software Engineer Intern")
    assert filters.is_software_role("Full Stack Developer Intern")
    assert filters.is_software_role("Machine Learning Engineer Intern")


def test_is_software_role_false_for_hardware_titles():
    assert not filters.is_software_role("Mechanical Engineer Intern")
    assert not filters.is_software_role("Business Development Associate")


def test_is_software_role_false_when_ambiguous():
    assert not filters.is_software_role("Summer Intern")


def test_is_intern_or_junior():
    assert filters.is_intern_or_junior("Software Engineering Intern")
    assert filters.is_intern_or_junior("Junior Backend Developer")
    assert filters.is_intern_or_junior("Software Engineer Co-op")
    assert not filters.is_intern_or_junior("Staff Software Engineer")
    assert not filters.is_intern_or_junior("Senior Director of Engineering")


def test_requires_clearance_detects_common_phrasing():
    assert filters.requires_clearance("Must have an active TS/SCI clearance.")
    assert filters.requires_clearance("Eligibility for a security clearance is required.")
    assert not filters.requires_clearance("No clearance needed, remote friendly.")


def test_requires_citizenship_detects_common_phrasing():
    assert filters.requires_citizenship("Must be a U.S. Citizen to apply.")
    assert not filters.requires_citizenship("Open to all applicants worldwide.")


def test_skill_match_strong_for_known_stack():
    assert filters.classify_skill_match("Software Engineer Intern", "You'll write Python and JavaScript.") == "strong"
    assert filters.classify_skill_match("Full Stack Intern", "React, Node.js, Firebase") == "strong"


def test_skill_match_strong_wins_even_with_a_gap_keyword_present():
    # Real postings often list one nice-to-have outside his stack --
    # that shouldn't sink an otherwise-good match.
    text = "Build backend services in Python and deploy with some Kubernetes exposure a plus."
    assert filters.classify_skill_match("Backend Intern", text) == "strong"


def test_skill_match_gap_for_pure_firmware_role():
    assert filters.classify_skill_match("Embedded Firmware Engineer Intern", "C++ and RTOS experience required.") == "gap"


def test_skill_match_stretch_for_partial_overlap():
    assert filters.classify_skill_match("Data Engineering Intern", "SQL and data pipelines.") == "stretch"


def test_skill_match_unclear_when_nothing_matches():
    assert filters.classify_skill_match("Intern", "General office duties.") == "unclear"


def test_worth_notifying_requires_software_and_intern():
    assert filters.worth_notifying(is_software=True, is_intern=True, clearance_required=False, skill_match="strong")
    assert not filters.worth_notifying(is_software=False, is_intern=True, clearance_required=False, skill_match="strong")
    assert not filters.worth_notifying(is_software=True, is_intern=False, clearance_required=False, skill_match="strong")


def test_worth_notifying_excludes_clearance_and_gap():
    assert not filters.worth_notifying(is_software=True, is_intern=True, clearance_required=True, skill_match="strong")
    assert not filters.worth_notifying(is_software=True, is_intern=True, clearance_required=False, skill_match="gap")


def test_worth_notifying_includes_citizenship_required_roles():
    # Citizenship-required is fine for the student -- worth_notifying doesn't
    # even take it as a parameter, since CLAUDE.md says flag, not filter.
    assert filters.worth_notifying(is_software=True, is_intern=True, clearance_required=False, skill_match="stretch")


def test_is_intern_or_junior_does_not_false_match_substring():
    # Regression: "V-BAT Internal Training Instructor" is a real posting
    # that was wrongly flagged because "intern" is a substring of "Internal".
    assert not filters.is_intern_or_junior("V-BAT Internal Training Instructor (R5031)")
    assert not filters.is_intern_or_junior("International Sales Manager")


def test_is_software_role_title_veto_beats_description_mention():
    # Regression: a real "Manufacturing Engineering Intern" posting whose
    # long description happened to mention software in passing was wrongly
    # classified as a software role. The title should win.
    title = "Manufacturing Engineering Intern"
    description = "You'll work closely with our software team and use CAD software daily."
    assert not filters.is_software_role(title, description)


def test_is_software_role_falls_back_to_description_when_title_is_ambiguous():
    assert filters.is_software_role("Summer Intern", "You'll do full-stack web development daily.")


def test_classify_skill_match_does_not_false_match_rust_inside_robust():
    text = "We value robust, well-tested software and clean Python code."
    assert filters.classify_skill_match("Software Engineer Intern", text) == "strong"
    # Specifically: "robust" alone (no real "rust"/C++/etc mention) must not
    # get misread as a Rust-language posting and downgraded to 'gap'.
    text_no_strong_kw = "We build robust systems with careful testing."
    assert filters.classify_skill_match("Systems Intern", text_no_strong_kw) != "gap"
