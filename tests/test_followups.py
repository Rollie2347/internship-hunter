from datetime import date

from internship_hunter.dashboard import followups
from internship_hunter.models import Message


def make_message(**overrides) -> Message:
    defaults = dict(
        company_id=1, channel="email", subject="Quick question",
        body="Hi...", status="drafted", sent_at=None,
    )
    defaults.update(overrides)
    return Message(**defaults)


def test_days_since_sent_returns_none_when_never_sent():
    assert followups.days_since_sent(make_message(sent_at=None)) is None


def test_days_since_sent_computes_whole_days():
    msg = make_message(sent_at="2026-09-27 10:00:00")
    assert followups.days_since_sent(msg, today=date(2026, 10, 4)) == 7


def test_needs_follow_up_false_when_never_sent():
    msg = make_message(status="drafted", sent_at=None)
    assert followups.needs_follow_up(msg, today=date(2026, 10, 4)) is False


def test_needs_follow_up_false_when_sent_but_under_7_days():
    msg = make_message(status="sent", sent_at="2026-10-01 10:00:00")
    assert followups.needs_follow_up(msg, today=date(2026, 10, 4)) is False


def test_needs_follow_up_true_at_exactly_7_days():
    msg = make_message(status="sent", sent_at="2026-09-27 10:00:00")
    assert followups.needs_follow_up(msg, today=date(2026, 10, 4)) is True


def test_needs_follow_up_true_well_past_7_days():
    msg = make_message(status="sent", sent_at="2026-09-01 10:00:00")
    assert followups.needs_follow_up(msg, today=date(2026, 10, 4)) is True


def test_needs_follow_up_false_once_replied():
    # Already got a reply -- must not keep nagging for a follow-up.
    msg = make_message(status="replied", sent_at="2026-09-01 10:00:00")
    assert followups.needs_follow_up(msg, today=date(2026, 10, 4)) is False


def test_needs_follow_up_false_once_rejected_or_interviewing():
    rejected = make_message(status="rejected", sent_at="2026-09-01 10:00:00")
    interviewing = make_message(status="interviewing", sent_at="2026-09-01 10:00:00")
    assert followups.needs_follow_up(rejected, today=date(2026, 10, 4)) is False
    assert followups.needs_follow_up(interviewing, today=date(2026, 10, 4)) is False


def test_filter_needing_follow_up_returns_only_matching_messages():
    due = make_message(status="sent", sent_at="2026-09-01 10:00:00")
    not_due = make_message(status="sent", sent_at="2026-10-03 10:00:00")
    replied = make_message(status="replied", sent_at="2026-09-01 10:00:00")
    result = followups.filter_needing_follow_up([due, not_due, replied], today=date(2026, 10, 4))
    assert result == [due]


def test_build_follow_up_context_mentions_subject_and_day_count():
    msg = make_message(subject="Quick question about Zarf", sent_at="2026-09-27 10:00:00")
    context = followups.build_follow_up_context(msg, today=date(2026, 10, 4))
    assert "Quick question about Zarf" in context
    assert "7 days" in context
