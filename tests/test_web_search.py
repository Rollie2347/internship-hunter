from types import SimpleNamespace

import pytest

from internship_hunter import config, db
from internship_hunter.models import Company, Contact
from internship_hunter.people import people_finder, web_search


@pytest.fixture
def conn(tmp_path):
    connection = db.get_connection(tmp_path / "test_tracker.db")
    db.init_db(connection)
    yield connection
    connection.close()


def add_company(conn, name="Foo Robotics", tier=1, state="CO", **overrides) -> Company:
    fields = dict(
        name=name, website="https://foo.example", state=state, city="X", stage="seed",
        what_they_build="drone autonomy software", why_fit="x", careers_url="https://foo.example/careers",
        priority_tier=tier,
    )
    fields.update(overrides)
    company = Company(**fields)
    company.id = db.insert_company(conn, company)
    return company


def search_results(*urls):
    return SimpleNamespace(type="web_search_tool_result", content=[SimpleNamespace(url=u, title="t") for u in urls])


def text(body):
    return SimpleNamespace(type="text", text=body)


class FakeClient:
    """Stands in for the Anthropic client: `create` plays back the search
    turns it was given, `parse` returns the people it was given."""

    def __init__(self, turns=(), people=()):
        self.turns, self.people = list(turns), list(people)
        self.create_calls, self.parse_calls = [], []
        self.messages = self

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        stop_reason, content = self.turns.pop(0)
        return SimpleNamespace(stop_reason=stop_reason, content=content)

    def parse(self, **kwargs):
        self.parse_calls.append(kwargs)
        return SimpleNamespace(parsed_output=people_finder.ExtractionResult(people=self.people))


# --- step 1: which pages to read -------------------------------------------

def test_the_search_tool_is_told_never_to_search_linkedin():
    tool = web_search.search_tool()
    assert "linkedin.com" in tool["blocked_domains"]
    assert tool["max_uses"] == config.WEB_SEARCH_MAX_USES and tool["name"] == "web_search"


def test_choose_pages_drops_urls_the_search_never_returned():
    returned = ["https://news.example/funding", "https://podcast.example/ep-12"]
    recommended = ["https://podcast.example/ep-12", "https://made-up.example/profile"]
    assert web_search.choose_pages(recommended, returned) == ["https://podcast.example/ep-12"]


def test_choose_pages_never_picks_linkedin_or_a_page_already_read():
    returned = ["https://www.linkedin.com/in/jane", "https://foo.example/team/", "https://news.example/a"]
    assert web_search.choose_pages(returned, returned, skip=("https://foo.example/team",)) == ["https://news.example/a"]


def test_choose_pages_falls_back_to_top_results_and_respects_the_limit():
    returned = [f"https://news.example/{i}" for i in range(6)]
    assert web_search.choose_pages([], returned, limit=2) == returned[:2]


def test_a_failed_search_block_is_ignored():
    failed = SimpleNamespace(type="web_search_tool_result", content=SimpleNamespace(error_code="max_uses_exceeded"))
    assert web_search.returned_urls([failed, search_results("https://news.example/a")]) == ["https://news.example/a"]


def test_find_pages_resumes_a_paused_turn_and_reads_both_halves(conn):
    company = add_company(conn)
    client = FakeClient(turns=[
        ("pause_turn", [search_results("https://news.example/funding")]),
        ("end_turn", [search_results("https://podcast.example/ep-12"),
                      text("Best pages:\nhttps://podcast.example/ep-12\nhttps://news.example/funding.")]),
    ])

    pages = web_search.find_pages(client, company)

    assert pages == ["https://podcast.example/ep-12", "https://news.example/funding"]
    assert len(client.create_calls) == 2
    # The resume sends the paused turn's own content back.
    assert client.create_calls[1]["messages"][1]["role"] == "assistant"
    assert client.create_calls[0]["tools"][0]["type"] == "web_search_20260209"
    assert company.name in client.create_calls[0]["messages"][0]["content"]


# --- step 2: reading a page ourselves --------------------------------------

ARTICLE = ("Foo Robotics raised a seed round. Jane Doe, CTO of Foo Robotics, spoke about swarm autonomy "
           "on the Hard Tech podcast. The round was led by Big Ventures partner Sam Money.")


def test_people_from_page_stores_the_url_we_fetched_and_marks_the_source_web(conn):
    company = add_company(conn)
    client = FakeClient(people=[people_finder.ExtractedPerson(
        name="Jane Doe", title="CTO", fact="Spoke about swarm autonomy on the Hard Tech podcast.",
    )])

    contacts = web_search.people_from_page(client, company, "https://news.example/funding", fetch=lambda url, n: ARTICLE)

    assert [(c.name, c.source_url, c.source_kind) for c in contacts] == [
        ("Jane Doe", "https://news.example/funding", "web"),
    ]
    assert "swarm autonomy" in contacts[0].fact
    assert "Investors" in client.parse_calls[0]["system"]   # told who NOT to extract


def test_a_person_the_page_does_not_name_is_thrown_away(conn):
    company = add_company(conn)
    client = FakeClient(people=[
        people_finder.ExtractedPerson(name="Jane Doe", title="CTO", fact="x"),
        people_finder.ExtractedPerson(name="Invented Person", title="CEO", fact="from the model's memory"),
    ])
    contacts = web_search.people_from_page(client, company, "https://news.example/a", fetch=lambda url, n: ARTICLE)
    assert [c.name for c in contacts] == ["Jane Doe"]


def test_a_page_about_a_different_company_is_not_read_by_the_model(conn):
    company = add_company(conn)
    client = FakeClient(people=[people_finder.ExtractedPerson(name="Jane Doe", title="CTO", fact="x")])
    other = "Bar Aerospace hired Jane Doe as CTO."
    assert web_search.people_from_page(client, company, "https://news.example/a", fetch=lambda url, n: other) == []
    assert client.parse_calls == []


def test_a_linkedin_url_is_never_fetched(conn, monkeypatch):
    # The real fetch_page_text, with the network forbidden: it must refuse
    # before trying.
    def no_network(*args, **kwargs):
        raise AssertionError("tried to fetch a LinkedIn page")

    monkeypatch.setattr(people_finder.requests, "get", no_network)
    assert web_search.people_from_page(FakeClient(), add_company(conn), "https://www.linkedin.com/in/jane-doe") == []


# --- the whole run ---------------------------------------------------------

def test_run_for_company_merges_with_the_team_page_contact_and_is_only_paid_for_once(conn):
    company = add_company(conn)
    db.insert_contact(conn, Contact(
        company_id=company.id, name="Jane Doe", title="CTO", source_url="https://foo.example/team", fact="Is the CTO.",
    ))
    client = FakeClient(
        turns=[("end_turn", [search_results("https://news.example/funding"), text("https://news.example/funding")])],
        people=[
            people_finder.ExtractedPerson(name="Jane Doe", title="CTO", fact="Spoke about swarm autonomy on the Hard Tech podcast."),
        ],
    )

    stored = web_search.run_for_company(client, conn, company, fetch=lambda url, n: ARTICLE)

    assert [(c.name, is_new) for c, is_new in stored] == [("Jane Doe", False)]
    everyone = db.list_contacts(conn)
    assert len(everyone) == 1 and everyone[0].source_url == "https://news.example/funding"
    assert web_search.companies_to_search(conn) == []


def test_companies_to_search_is_tier_one_in_colorado_and_virginia_only(conn):
    wanted = add_company(conn, "CO Startup", tier=1, state="CO")
    add_company(conn, "Big Defense", tier=2, state="VA")
    elsewhere = add_company(conn, "TX Startup", tier=1, state="Other")
    assert [c.id for c in web_search.companies_to_search(conn)] == [wanted.id]
    assert [c.id for c in web_search.companies_to_search(conn, any_state=True)] == [wanted.id, elsewhere.id]


def test_the_bot_never_searches_the_web_unless_it_is_turned_on(conn, monkeypatch):
    from internship_hunter.approvals import bot

    add_company(conn)
    monkeypatch.setattr(bot, "_anthropic_client", lambda: (_ for _ in ()).throw(AssertionError("spent money")))
    monkeypatch.setattr(config, "WEB_PEOPLE_SEARCH_PER_DAY", 0)
    assert bot.find_people_on_the_web(conn) == 0
