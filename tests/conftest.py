import pytest

from internship_hunter import config


@pytest.fixture(autouse=True)
def isolated_answers_file(tmp_path, monkeypatch):
    """profile/my_answers.md is the student's real, hand-edited file, and
    reading it creates it. Every test gets a throwaway copy instead, so
    running the suite can never touch or depend on his answers."""
    monkeypatch.setattr(config, "MY_ANSWERS_PATH", tmp_path / "my_answers.md")


@pytest.fixture(autouse=True)
def no_live_email_search(monkeypatch):
    """The published-email search hits company websites and GitHub (with
    rate-limit pauses). No test may do that by accident."""
    from internship_hunter.people import cli as people_cli

    monkeypatch.setattr(people_cli.email_finder, "find_for_company", lambda *a, **k: [])


@pytest.fixture(autouse=True)
def no_live_requirement_reading(monkeypatch):
    """Screening a posting fetches its text from the job board. Tests that
    aren't about screening treat every posting as eligible."""
    from internship_hunter.approvals import bot
    from internship_hunter.scanner import eligibility

    real = eligibility.screen_posting
    monkeypatch.setattr(bot.eligibility, "screen_posting", lambda *a, **k: eligibility.Verdict("eligible"))
    yield real


@pytest.fixture(autouse=True)
def no_live_claude_or_gmail(monkeypatch):
    """The bot builds its own Claude client and Gmail service when a test
    doesn't hand it one -- and .env on this PC holds real keys. Any test
    that gets that far without supplying a fake fails loudly instead of
    spending money or touching the real mailbox."""
    from internship_hunter.approvals import bot

    def refuse(*args, **kwargs):
        raise RuntimeError("a test tried to use the real Claude API / Gmail")

    monkeypatch.setattr(bot, "_anthropic_client", refuse)
    monkeypatch.setattr(bot, "_gmail_service", refuse)


@pytest.fixture(autouse=True)
def fixed_daily_limits(monkeypatch):
    """The daily limits come from .env on this PC, which the student changes.
    Tests pin their own so a new setting can't break (or quietly weaken) them."""
    monkeypatch.setattr(config, "OUTREACH_PER_DAY", 5)
    monkeypatch.setattr(config, "LINKEDIN_DAILY_CAP", 10)
    monkeypatch.setattr(config, "DAILY_DRAFT_CAP", 25)
