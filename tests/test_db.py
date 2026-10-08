import sqlite3

import pytest

from internship_hunter import db
from internship_hunter.models import Company, Contact, Message


@pytest.fixture
def conn(tmp_path):
    """A fresh, throwaway SQLite database for each test, so tests never touch
    the real data/tracker.db."""
    test_db_path = tmp_path / "test_tracker.db"
    connection = db.get_connection(test_db_path)
    db.init_db(connection)
    yield connection
    connection.close()


def make_company(**overrides) -> Company:
    defaults = dict(
        name="Test Co",
        website="https://test.co",
        state="VA",
        city="Arlington",
        stage="seed",
        what_they_build="Test things",
        why_fit="Testing fit",
        careers_url="https://test.co/careers",
        priority_tier=1,
    )
    defaults.update(overrides)
    return Company(**defaults)


def test_init_db_creates_all_tables(conn):
    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"companies", "postings", "contacts", "messages"} <= tables


def test_init_db_is_safe_to_call_twice(conn):
    db.init_db(conn)  # should not raise
    db.init_db(conn)


def test_insert_and_get_company_by_name(conn):
    company_id = db.insert_company(conn, make_company(name="Anduril Industries"))
    assert company_id > 0

    fetched = db.get_company_by_name(conn, "Anduril Industries")
    assert fetched is not None
    assert fetched.name == "Anduril Industries"
    assert fetched.priority_tier == 1
    assert fetched.id == company_id


def test_get_company_by_name_returns_none_when_missing(conn):
    assert db.get_company_by_name(conn, "Nonexistent Co") is None


def test_duplicate_company_name_raises_integrity_error(conn):
    db.insert_company(conn, make_company(name="Duplicate Co"))
    with pytest.raises(sqlite3.IntegrityError):
        db.insert_company(conn, make_company(name="Duplicate Co"))


def test_company_rejects_invalid_priority_tier():
    with pytest.raises(ValueError):
        make_company(priority_tier=5)


def test_list_companies_filters_by_tier_and_state(conn):
    db.insert_company(conn, make_company(name="VA Tier1", state="VA", priority_tier=1))
    db.insert_company(conn, make_company(name="CO Tier2", state="CO", priority_tier=2))
    db.insert_company(conn, make_company(name="WI Tier1", state="WI", priority_tier=1))

    tier1 = db.list_companies(conn, tier=1)
    assert {c.name for c in tier1} == {"VA Tier1", "WI Tier1"}

    va_only = db.list_companies(conn, state="VA")
    assert {c.name for c in va_only} == {"VA Tier1"}

    all_companies = db.list_companies(conn)
    assert len(all_companies) == 3


def test_list_companies_does_not_rank_one_state_over_another(conn):
    # Same tier, different states -- order should be alphabetical by name,
    # not grouped/boosted by state, since states are weighted equally.
    db.insert_company(conn, make_company(name="Wisco Widget", state="WI", priority_tier=1))
    db.insert_company(conn, make_company(name="Alpha Aero", state="VA", priority_tier=1))
    db.insert_company(conn, make_company(name="Colorado Co", state="CO", priority_tier=1))

    names_in_order = [c.name for c in db.list_companies(conn)]
    assert names_in_order == sorted(names_in_order)


def test_delete_company(conn):
    db.insert_company(conn, make_company(name="To Delete"))
    assert db.delete_company(conn, "To Delete") is True
    assert db.get_company_by_name(conn, "To Delete") is None
    assert db.delete_company(conn, "To Delete") is False


def test_update_company_tier(conn):
    db.insert_company(conn, make_company(name="Promote Me", priority_tier=3))
    assert db.update_company_tier(conn, "Promote Me", 1) is True
    assert db.get_company_by_name(conn, "Promote Me").priority_tier == 1


def test_update_company_tier_rejects_invalid_tier(conn):
    db.insert_company(conn, make_company(name="Whatever"))
    with pytest.raises(ValueError):
        db.update_company_tier(conn, "Whatever", 9)


# --- Contacts ---

def test_insert_and_list_contacts(conn):
    company_id = db.insert_company(conn, make_company(name="Contact Co"))
    contact = Contact(
        company_id=company_id,
        name="Jane Doe",
        title="CTO",
        source_url="https://contactco.com/about",
        fact="Co-founded the company.",
    )
    contact_id = db.insert_contact(conn, contact)
    assert contact_id > 0

    contacts = db.list_contacts(conn, company_id=company_id)
    assert len(contacts) == 1
    assert contacts[0].name == "Jane Doe"
    assert contacts[0].source_url == "https://contactco.com/about"


def test_insert_contact_requires_source_url(conn):
    company_id = db.insert_company(conn, make_company(name="No Source Co"))
    contact = Contact(company_id=company_id, name="Jane Doe", title="CTO", source_url="", fact="x")
    with pytest.raises(ValueError):
        db.insert_contact(conn, contact)


def test_get_contact_by_name_returns_none_when_missing(conn):
    company_id = db.insert_company(conn, make_company(name="Empty Co"))
    assert db.get_contact_by_name(conn, company_id, "Nobody") is None


def test_list_contacts_without_company_id_returns_all(conn):
    c1 = db.insert_company(conn, make_company(name="Co A"))
    c2 = db.insert_company(conn, make_company(name="Co B"))
    db.insert_contact(conn, Contact(company_id=c1, name="A Person", title="CTO", source_url="https://a.com", fact="x"))
    db.insert_contact(conn, Contact(company_id=c2, name="B Person", title="CEO", source_url="https://b.com", fact="x"))
    assert len(db.list_contacts(conn)) == 2


def test_set_company_team_url(conn):
    company_id = db.insert_company(conn, make_company(name="Team URL Co"))
    db.set_company_team_url(conn, company_id, "https://teamurlco.com/about")
    refreshed = db.get_company_by_name(conn, "Team URL Co")
    assert refreshed.team_url == "https://teamurlco.com/about"


def test_init_db_migrates_a_column_added_after_table_creation(tmp_path):
    # Simulate a database created before team_url existed, then confirm
    # init_db adds it on a later run instead of throwing IndexError on read.
    path = tmp_path / "pre_migration.db"
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            website TEXT NOT NULL DEFAULT '',
            state TEXT NOT NULL DEFAULT '',
            city TEXT NOT NULL DEFAULT '',
            stage TEXT NOT NULL DEFAULT '',
            what_they_build TEXT NOT NULL DEFAULT '',
            why_fit TEXT NOT NULL DEFAULT '',
            careers_url TEXT NOT NULL DEFAULT '',
            priority_tier INTEGER NOT NULL CHECK (priority_tier IN (1, 2, 3, 4)),
            needs_verification INTEGER NOT NULL DEFAULT 0,
            notes TEXT NOT NULL DEFAULT '',
            ats_type TEXT,
            ats_slug TEXT,
            manual_check_needed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()

    conn = db.get_connection(path)
    db.init_db(conn)  # should migrate in the missing column, not raise
    company_id = db.insert_company(conn, make_company(name="Migrated Co"))
    fetched = db.get_company_by_name(conn, "Migrated Co")
    assert fetched.team_url is None
    assert fetched.id == company_id


# --- Messages ---

def test_insert_and_get_message(conn):
    company_id = db.insert_company(conn, make_company(name="Message Co"))
    message = Message(company_id=company_id, channel="email", subject="Hi", body="Body text")
    message_id = db.insert_message(conn, message)
    assert message_id > 0

    fetched = db.get_message(conn, message_id)
    assert fetched.subject == "Hi"
    assert fetched.status == "drafted"
    assert fetched.sent_at is None


def test_get_message_returns_none_when_missing(conn):
    assert db.get_message(conn, 99999) is None


def test_list_messages_filters_by_status_and_company(conn):
    c1 = db.insert_company(conn, make_company(name="Msg Co A"))
    c2 = db.insert_company(conn, make_company(name="Msg Co B"))
    db.insert_message(conn, Message(company_id=c1, channel="email", subject="A1", body="x", status="drafted"))
    db.insert_message(conn, Message(company_id=c1, channel="email", subject="A2", body="x", status="sent"))
    db.insert_message(conn, Message(company_id=c2, channel="email", subject="B1", body="x", status="sent"))

    assert len(db.list_messages(conn)) == 3
    assert len(db.list_messages(conn, status="sent")) == 2
    assert len(db.list_messages(conn, company_id=c1)) == 2
    assert len(db.list_messages(conn, status="sent", company_id=c1)) == 1


def test_update_message_status_sets_status_and_sent_at(conn):
    company_id = db.insert_company(conn, make_company(name="Status Co"))
    message_id = db.insert_message(conn, Message(company_id=company_id, channel="email", subject="Hi", body="x"))

    assert db.update_message_status(conn, message_id, "sent", sent_at="2026-10-04 12:00:00") is True
    fetched = db.get_message(conn, message_id)
    assert fetched.status == "sent"
    assert fetched.sent_at == "2026-10-04 12:00:00"


def test_update_message_status_without_sent_at_leaves_it_unchanged(conn):
    company_id = db.insert_company(conn, make_company(name="Status Co 2"))
    message_id = db.insert_message(conn, Message(company_id=company_id, channel="email", subject="Hi", body="x"))
    db.update_message_status(conn, message_id, "sent", sent_at="2026-10-04 12:00:00")

    db.update_message_status(conn, message_id, "replied")
    fetched = db.get_message(conn, message_id)
    assert fetched.status == "replied"
    assert fetched.sent_at == "2026-10-04 12:00:00"  # untouched


def test_update_message_status_rejects_invalid_status(conn):
    company_id = db.insert_company(conn, make_company(name="Status Co 3"))
    message_id = db.insert_message(conn, Message(company_id=company_id, channel="email", subject="Hi", body="x"))
    with pytest.raises(ValueError):
        db.update_message_status(conn, message_id, "ghosted")


def test_update_message_status_returns_false_for_missing_message(conn):
    assert db.update_message_status(conn, 99999, "sent") is False
