from internship_hunter import config


def test_priority_tiers_are_1_through_4():
    assert set(config.PRIORITY_TIERS.keys()) == {1, 2, 3, 4}


def test_target_states_are_weighted_equally_as_a_set():
    # A set (not a list) is the point: no state should be treated as ranked
    # above another, per the student's explicit choice.
    assert config.TARGET_STATES == {"VA", "CO", "WI"}


def test_daily_draft_cap_has_a_sane_default():
    assert isinstance(config.DAILY_DRAFT_CAP, int)
    assert config.DAILY_DRAFT_CAP > 0


def test_linkedin_is_in_never_automate_list():
    assert "linkedin" in config.NEVER_AUTOMATE_PLATFORMS


def test_availability_statement_before_turning_16():
    from datetime import date
    statement = config.availability_statement(today=date(2026, 10, 4))
    assert "15" in statement
    assert "part-time" in statement
    assert "April 2027" in statement
    assert "18 hours/week" in statement or "18" in statement


def test_availability_statement_after_turning_16():
    from datetime import date
    statement = config.availability_statement(today=date(2027, 5, 1))
    assert "16" in statement
    assert "full-time" in statement
    assert "part-time" not in statement


def test_availability_statement_on_exact_turn_16_date():
    from datetime import date
    statement = config.availability_statement(today=date(2027, 4, 1))
    assert "full-time" in statement
