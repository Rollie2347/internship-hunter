import pytest

from internship_hunter import db
from internship_hunter.models import Company, Contact, Message
from internship_hunter.people import dedupe


@pytest.fixture
def conn(tmp_path):
    connection = db.get_connection(tmp_path / "test_tracker.db")
    db.init_db(connection)
    yield connection
    connection.close()


def add_company(conn, name="Foo Corp") -> Company:
    company = Company(
        name=name, website="https://foo.example", state="VA", city="X", stage="seed",
        what_they_build="drones", why_fit="x", careers_url="https://foo.example", priority_tier=1,
    )
    company.id = db.insert_company(conn, company)
    return company


def person(company, name, **overrides) -> Contact:
    fields = dict(company_id=company.id, name=name, title="CTO", source_url="https://foo.example/team", fact="Is the CTO.")
    fields.update(overrides)
    return Contact(**fields)


@pytest.mark.parametrize("a,b,same", [
    ("Jane Doe", "Jane Doe", True),
    ("Jane Doe", "jane  doe", True),
    ("Dr. Jane Doe", "Jane Doe", True),
    ("Jane Q. Doe", "Jane Doe", True),          # a middle initial doesn't matter
    ("J. Doe", "Jane Doe", True),               # an initial
    ("Chris Poe", "Christopher Poe", True),     # a shortening
    ("Mike Smith", "Michael Smith", True),      # a nickname
    ("Jane Doe", "John Doe", False),            # same family name, different person
    ("Jane Doe", "Jane Roe", False),
    ("Al Doe", "Alan Doe", False),              # two letters is too little to go on
    ("Cher", "Cher", False),                    # no last name: never merged
])
def test_same_person(a, b, same):
    assert dedupe.same_person(a, b) is same


def test_store_contact_inserts_someone_new(conn):
    company = add_company(conn)
    stored, is_new = dedupe.store_contact(conn, person(company, "Jane Doe"))
    assert is_new and stored.id and db.list_contacts(conn)[0].name == "Jane Doe"


def test_a_second_source_merges_into_the_same_row_and_its_fact_keeps_its_own_source(conn):
    company = add_company(conn)
    first, _ = dedupe.store_contact(conn, person(company, "Jane Doe"))

    merged, is_new = dedupe.store_contact(conn, person(
        company, "Jane Q. Doe", title="Chief Technology Officer", source_kind="web",
        source_url="https://podcast.example/ep-12", fact="Spoke about swarm autonomy on the X podcast.",
    ))

    assert not is_new and merged.id == first.id and len(db.list_contacts(conn)) == 1
    # The more specific web fact wins, and brings its own URL with it.
    assert merged.fact == "Spoke about swarm autonomy on the X podcast."
    assert merged.source_url == "https://podcast.example/ep-12" and merged.source_kind == "web"
    assert merged.name == "Jane Doe" and merged.title == "CTO"   # the original name/title stay


def test_a_weaker_source_does_not_overwrite_a_better_fact(conn):
    company = add_company(conn)
    dedupe.store_contact(conn, person(company, "Jane Doe", source_kind="web", source_url="https://news.example/a", fact="Built the autopilot."))
    merged, _ = dedupe.store_contact(conn, person(company, "Jane Doe"))
    assert merged.fact == "Built the autopilot." and merged.source_url == "https://news.example/a"


def test_merge_fills_in_a_missing_email_with_its_source(conn):
    company = add_company(conn)
    dedupe.store_contact(conn, person(company, "Jane Doe"))
    merged, _ = dedupe.store_contact(conn, person(
        company, "Jane Doe", email="jane.doe@foo.example", source_url="https://foo.example/press",
    ))
    assert merged.email == "jane.doe@foo.example" and merged.email_source_url == "https://foo.example/press"


def test_same_name_at_two_companies_stays_two_people(conn):
    one, two = add_company(conn, "Foo Corp"), add_company(conn, "Bar Corp")
    dedupe.store_contact(conn, person(one, "Jane Doe"))
    _, is_new = dedupe.store_contact(conn, person(two, "Jane Doe"))
    assert is_new and len(db.list_contacts(conn)) == 2


def test_merge_existing_duplicates_keeps_the_older_row_and_its_messages(conn):
    company = add_company(conn)
    older = db.insert_contact(conn, person(company, "Jane Doe"))
    newer = db.insert_contact(conn, person(
        company, "Jane Q. Doe", source_kind="web", source_url="https://news.example/a", fact="Built the autopilot.",
    ))
    db.insert_contact(conn, person(company, "John Doe"))
    message_id = db.insert_message(conn, Message(company_id=company.id, contact_id=newer, channel="email", subject="s", body="b"))

    assert dedupe.merge_existing_duplicates(conn) == 1

    assert sorted(c.name for c in db.list_contacts(conn)) == ["Jane Doe", "John Doe"]
    assert db.get_message(conn, message_id).contact_id == older
    assert db.get_contact(conn, older).fact == "Built the autopilot."
    assert dedupe.merge_existing_duplicates(conn) == 0
