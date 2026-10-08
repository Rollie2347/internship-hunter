import pytest

from internship_hunter import config
from internship_hunter.apply_assist import choices

RULES = choices.DEFAULT_RULES


@pytest.mark.parametrize("question,expected_first", [
    ("Are you legally authorized to work in the United States?*", "Yes"),
    ("Will you now or in the future require sponsorship for employment visa status?", "No"),
    ("Are you authorized to work in the US without sponsorship?", "Yes"),
    ("Country*", "United States"),
    ("Are you at least 18 years of age or older?", "No"),
    ("Do you hold an ACTIVE U.S. Government issued clearance?", "No"),
    ("Security Clearance *", "No"),
    ("Are you currently bound by any non-compete agreement?", "No"),
    ("Have you worked for Two Six Technologies before?", "No"),
    ("Are you willing to work in-person for 12 weeks?", "Yes"),
    ("Degree*", "High School"),
])
def test_standing_answers(question, expected_first):
    assert choices.candidates_for(question, RULES)[0] == expected_first


@pytest.mark.parametrize("question", [
    "Gender", "Are you Hispanic/Latino?", "Veteran Status", "Disability status",
    "Are you eligible for a DoD security clearance?",
    "This role requires US citizenship and eligibility to obtain a US security clearance, do you meet that requirement?",
    "EXPORT CONTROLS - This position requires access to ITAR data. Are you a U.S. person?",
    "Are you under 18?", "Desired Salary*", "Will you be returning to school at the end of this internship?",
    "School*", "What is your earliest available start date?",
])
def test_personal_and_ambiguous_questions_are_left_for_him(question):
    assert choices.candidates_for(question, RULES) == []


def test_pick_option_matches_exactly_or_by_leading_word_only():
    assert choices.pick_option(["Select...", "Yes", "No"], ["Yes"]) == "Yes"
    assert choices.pick_option(["Yes, I am authorized to work", "No, I am not"], ["Yes"]) == "Yes, I am authorized to work"
    assert choices.pick_option(["Not sure", "Maybe"], ["No"]) is None
    assert choices.pick_option(["None", "Secret", "Top Secret"], ["No", "None"]) == "None"
    assert choices.pick_option(["Canada", "United States +1"], ["United States"]) == "United States +1"


def test_plan_choices_previews_selections_and_leaves_the_rest():
    planned, left = choices.plan_choices([
        {"question": "Are you legally authorized to work in the United States?", "options": ["Yes", "No"]},
        {"question": "Country*", "options": None},
        {"question": "Gender", "options": ["Male", "Female", "Decline To Self Identify"]},
        {"question": "Will you require sponsorship?", "options": ["Maybe later"]},
    ], RULES)
    assert planned == {"Are you legally authorized to work in the United States?": "Yes", "Country*": "United States"}
    assert left == ["Gender", "Will you require sponsorship?"]


def test_location_preference_uses_this_postings_colorado_or_virginia_offices(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "MY_ANSWERS_PATH", tmp_path / "my_answers.md")
    location = "Atlanta, Georgia, United States; Broomfield, Colorado, United States; Reston, Virginia, United States"
    candidates = choices.candidates_for("What is your top location preference? *", posting_location=location)
    assert candidates[:3] == ["Broomfield, Colorado, United States", "Broomfield, Colorado", "Broomfield"]
    assert "Reston" in candidates and not any("Atlanta" in c for c in candidates)
    assert choices.candidates_for("Current location", posting_location=location) == []
