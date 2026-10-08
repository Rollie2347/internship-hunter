from pathlib import Path

import pytest

from internship_hunter import config, db
from internship_hunter.models import Company, Contact
from internship_hunter.people import hunter


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HUNTER_API_KEY", "test-key")
    monkeypatch.setattr(config, "HUNTER_MONTHLY_LIMIT", 25)
    connection = db.get_connection(tmp_path / "test_tracker.db")
    db.init_db(connection)
    yield connection
    connection.close()


def add_company(conn, name="Foo Robotics", website="https://www.foo.example", state="CO", tier=1) -> Company:
    company = Company(
        name=name, website=website, state=state, city="X", stage="seed", what_they_build="drones",
        why_fit="x", careers_url=website, priority_tier=tier,
    )
    company.id = db.insert_company(conn, company)
    return company


def entry(value, first="Jane", last="Doe", position="CTO", kind="personal", sources=None, **extra):
    if sources is None:
        sources = [{"domain": "foo.example", "uri": "https://foo.example/press/launch", "still_on_page": True}]
    return {"value": value, "type": kind, "first_name": first, "last_name": last, "position": position,
            "department": "engineering", "sources": sources, **extra}


class FakeResponse:
    def __init__(self, data=None, status_code=200):
        self._data, self.status_code = data or {}, status_code

    def json(self):
        return {"data": self._data}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeGet:
    def __init__(self, data=None, status_code=200):
        self.response, self.calls = FakeResponse(data, status_code), []

    def __call__(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params, headers))
        return self.response


# --- only the allowed endpoint, never a guess ------------------------------

def test_the_module_can_only_reach_domain_search_and_never_reads_the_pattern():
    source = Path(hunter.__file__).read_text(encoding="utf-8")
    code = source.split('"""', 2)[2]     # everything after the module docstring
    assert "email-finder" not in code and "email-verifier" not in code
    assert code.count("api.hunter.io") == 1 and "/v2/domain-search" in code
    assert '"pattern"' not in code and "'pattern'" not in code


def test_an_address_with_no_source_page_is_dropped():
    data = {"pattern": "{first}.{last}", "emails": [
        entry("jane.doe@foo.example"),
        entry("sam.roe@foo.example", first="Sam", last="Roe", sources=[]),                    # no source: a guess
        entry("al.poe@foo.example", first="Al", last="Poe", sources=[{"uri": ""}]),
        entry("li.moe@foo.example", first="Li", last="Moe", sources=[{"uri": "https://www.linkedin.com/in/li-moe"}]),
        entry("pat@other.example", first="Pat", last="Lee"),                                  # not the company's domain
    ]}
    kept = hunter.sourced_emails(data, "foo.example")
    assert [(e["email"], e["source"]) for e in kept] == [("jane.doe@foo.example", "https://foo.example/press/launch")]


def test_the_source_stored_is_a_page_that_still_shows_the_address():
    sources = [{"uri": "https://old.example/gone", "still_on_page": False}, {"uri": "https://foo.example/team", "still_on_page": True}]
    assert hunter.source_uri(entry("jane.doe@foo.example", sources=sources)) == "https://foo.example/team"


# --- cache and monthly limit -----------------------------------------------

def test_a_domain_is_only_ever_searched_once_and_the_key_stays_out_of_the_url(conn):
    get = FakeGet({"emails": [entry("jane.doe@foo.example")]})

    first = hunter.domain_search(conn, "foo.example", get)
    second = hunter.domain_search(conn, "foo.example", get)

    assert first == second and len(get.calls) == 1
    url, params, headers = get.calls[0]
    assert url == "https://api.hunter.io/v2/domain-search"
    assert params == {"domain": "foo.example", "limit": 10} and headers == {"X-API-KEY": "test-key"}
    assert hunter.searches_this_month(conn) == 1


def test_searching_stops_at_the_monthly_limit(conn, monkeypatch):
    monkeypatch.setattr(config, "HUNTER_MONTHLY_LIMIT", 2)
    for i in range(4):
        add_company(conn, f"Co {i}", f"https://co{i}.example")
    get = FakeGet({"emails": []})

    assert len(hunter.run(conn, 10, get=get)) == 2
    assert len(get.calls) == 2 and hunter.remaining_this_month(conn) == 0
    assert hunter.run(conn, 10, get=get) == [] and len(get.calls) == 2
    with pytest.raises(hunter.HunterLimitReached):
        hunter.domain_search(conn, "new.example", get)


def test_run_stops_when_hunter_says_the_quota_is_gone(conn):
    add_company(conn, "Co 1", "https://co1.example")
    add_company(conn, "Co 2", "https://co2.example")
    get = FakeGet(status_code=429)
    assert hunter.run(conn, 10, get=get) == [] and len(get.calls) == 1
    assert hunter.searches_this_month(conn) == 0     # nothing cached, so it's retried next month


def test_no_key_means_no_request(conn, monkeypatch):
    monkeypatch.setattr(config, "HUNTER_API_KEY", "")
    get = FakeGet()
    with pytest.raises(hunter.HunterNotConfigured):
        hunter.domain_search(conn, "foo.example", get)
    assert get.calls == []


def test_only_colorado_and_virginia_companies_are_looked_up(conn):
    wanted = add_company(conn, "CO Startup", "https://co.example", state="CO")
    add_company(conn, "TX Startup", "https://tx.example", state="Other")
    add_company(conn, "A Lab", "https://lab.example", state="VA", tier=4)
    assert [c.id for c in hunter.companies_to_search(conn)] == [wanted.id]


# --- storing ---------------------------------------------------------------

def test_apply_fills_an_existing_contact_adds_a_new_one_and_sets_the_inbox(conn):
    company = add_company(conn)
    existing = db.insert_contact(conn, Contact(
        company_id=company.id, name="Jane Q. Doe", title="CTO", source_url="https://foo.example/team", fact="Is the CTO.",
    ))
    data = {"pattern": "{first}", "emails": [
        entry("jane.doe@foo.example", phone_number="555-0100", linkedin="https://linkedin.com/in/jane"),
        entry("sam.roe@foo.example", first="Sam", last="Roe", position="Software Engineer"),
        entry("no.title@foo.example", first="No", last="Title", position=None),
        entry("careers@foo.example", first=None, last=None, position=None, kind="generic"),
        entry("press@foo.example", first=None, last=None, position=None, kind="generic"),
    ]}

    stored = hunter.apply_to_company(conn, company, data)

    jane = db.get_contact(conn, existing)
    assert (jane.email, jane.email_source_url) == ("jane.doe@foo.example", "https://foo.example/press/launch")
    assert jane.fact == "Is the CTO." and jane.linkedin_url is None      # nothing else of Hunter's is taken
    people = {c.name: c for c in db.list_contacts(conn)}
    assert set(people) == {"Jane Q. Doe", "Sam Roe"}                      # merged, not duplicated; no-title person skipped
    sam = people["Sam Roe"]
    assert (sam.email, sam.email_source_url, sam.source_kind, sam.title) == (
        "sam.roe@foo.example", "https://foo.example/press/launch", "hunter", "Software Engineer",
    )
    assert db.get_company(conn, company.id).contact_email == "careers@foo.example"   # press@ is not an inbox to pitch
    assert len(stored) == 3


def test_apply_never_replaces_an_email_already_on_file(conn):
    company = add_company(conn)
    contact_id = db.insert_contact(conn, Contact(
        company_id=company.id, name="Jane Doe", title="CTO", source_url="https://foo.example/team", fact="x",
    ))
    db.set_contact_email(conn, contact_id, "jane@foo.example", "https://foo.example/team")
    assert hunter.apply_to_company(conn, company, {"emails": [entry("jane.doe@foo.example")]}) == []
    assert db.get_contact(conn, contact_id).email == "jane@foo.example"
