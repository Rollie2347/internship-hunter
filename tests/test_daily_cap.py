import pytest

from internship_hunter import db
from internship_hunter.drafting import daily_cap
from internship_hunter.models import Company


@pytest.fixture
def conn(tmp_path):
    connection = db.get_connection(tmp_path / "test_tracker.db")
    db.init_db(connection)
    yield connection
    connection.close()


def make_company_id(conn) -> int:
    company = Company(
        name="Foo Corp", website="https://foo.example", state="VA", city="Arlington",
        stage="seed", what_they_build="x", why_fit="x", careers_url="https://foo.example/careers",
        priority_tier=1,
    )
    return db.insert_company(conn, company)


def insert_email_message(conn, company_id):
    conn.execute(
        "INSERT INTO messages (company_id, channel, subject, body) VALUES (?, 'email', 'x', 'x')",
        (company_id,),
    )
    conn.commit()


def test_drafts_created_today_counts_only_email_messages(conn):
    company_id = make_company_id(conn)
    insert_email_message(conn, company_id)
    insert_email_message(conn, company_id)
    conn.execute(
        "INSERT INTO messages (company_id, channel, subject, body) VALUES (?, 'application', 'x', 'x')",
        (company_id,),
    )
    conn.commit()
    assert daily_cap.drafts_created_today(conn) == 2


def test_remaining_today_subtracts_count_from_cap(conn):
    company_id = make_company_id(conn)
    insert_email_message(conn, company_id)
    assert daily_cap.remaining_today(conn, cap=10) == 9


def test_remaining_today_never_goes_negative(conn):
    company_id = make_company_id(conn)
    for _ in range(5):
        insert_email_message(conn, company_id)
    assert daily_cap.remaining_today(conn, cap=3) == 0


def test_enforce_daily_cap_raises_when_cap_reached(conn):
    company_id = make_company_id(conn)
    for _ in range(3):
        insert_email_message(conn, company_id)
    with pytest.raises(daily_cap.DailyCapReached):
        daily_cap.enforce_daily_cap(conn, cap=3)


def test_enforce_daily_cap_does_not_raise_when_under_cap(conn):
    company_id = make_company_id(conn)
    insert_email_message(conn, company_id)
    daily_cap.enforce_daily_cap(conn, cap=3)  # should not raise


def test_enforce_daily_cap_blocks_the_eleventh_draft_with_default_cap(conn):
    company_id = make_company_id(conn)
    for _ in range(10):
        insert_email_message(conn, company_id)
    with pytest.raises(daily_cap.DailyCapReached):
        daily_cap.enforce_daily_cap(conn)  # uses config.DAILY_DRAFT_CAP default (10)
