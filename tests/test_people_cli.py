import pytest

from internship_hunter import db
from internship_hunter.models import Company
from internship_hunter.people import cli, people_finder


@pytest.fixture
def conn(tmp_path):
    connection = db.get_connection(tmp_path / "test_tracker.db")
    db.init_db(connection)
    yield connection
    connection.close()


def make_company(conn, **overrides) -> Company:
    defaults = dict(
        name="Foo Corp",
        website="https://foo.example",
        state="VA",
        city="Arlington",
        stage="seed",
        what_they_build="Software things",
        why_fit="Testing",
        careers_url="https://foo.example/careers",
        priority_tier=1,
    )
    defaults.update(overrides)
    company = Company(**defaults)
    company_id = db.insert_company(conn, company)
    company.id = company_id
    return company


def test_run_for_company_finds_and_stores_new_contact(conn, monkeypatch):
    company = make_company(conn)
    monkeypatch.setattr(people_finder, "find_team_page_url", lambda website, careers_url: "https://foo.example/about")
    monkeypatch.setattr(people_finder, "fetch_page_text", lambda url: "Jane Doe is our CTO.")
    monkeypatch.setattr(
        people_finder,
        "extract_people",
        lambda client, name, url, text: [
            people_finder.ExtractedPerson(name="Jane Doe", title="CTO", fact="Leads engineering.")
        ],
    )

    inserted = cli.run_for_company(client=object(), conn=conn, company=company)

    assert len(inserted) == 1
    assert inserted[0].name == "Jane Doe"
    # Team URL got cached on the company record for next time.
    refreshed = db.get_company_by_name(conn, "Foo Corp")
    assert refreshed.team_url == "https://foo.example/about"


def test_run_for_company_does_not_recreate_already_known_contact(conn, monkeypatch):
    company = make_company(conn, team_url="https://foo.example/about")
    monkeypatch.setattr(people_finder, "fetch_page_text", lambda url: "Jane Doe is our CTO.")
    monkeypatch.setattr(
        people_finder,
        "extract_people",
        lambda client, name, url, text: [
            people_finder.ExtractedPerson(name="Jane Doe", title="CTO", fact="Leads engineering.")
        ],
    )

    first = cli.run_for_company(client=object(), conn=conn, company=company)
    second = cli.run_for_company(client=object(), conn=conn, company=company)

    assert len(first) == 1
    assert len(second) == 0  # same person already on file


def test_run_for_company_returns_empty_when_no_team_page_found(conn, monkeypatch):
    company = make_company(conn)
    monkeypatch.setattr(people_finder, "find_team_page_url", lambda website, careers_url: None)

    inserted = cli.run_for_company(client=object(), conn=conn, company=company)

    assert inserted == []


def test_run_for_company_returns_empty_when_page_fetch_fails(conn, monkeypatch):
    company = make_company(conn, team_url="https://foo.example/about")
    monkeypatch.setattr(people_finder, "fetch_page_text", lambda url: None)

    inserted = cli.run_for_company(client=object(), conn=conn, company=company)

    assert inserted == []
