import pytest

from internship_hunter.models import Contact
from internship_hunter.people import people_finder


class FakeHttpResponse:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


def test_fetch_page_text_refuses_linkedin_urls():
    # Hard guard, not a preference -- CLAUDE.md bans LinkedIn automation
    # outright. No monkeypatching requests here on purpose: this must never
    # even attempt the network call.
    assert people_finder.fetch_page_text("https://www.linkedin.com/company/foo") is None


def test_fetch_page_text_strips_scripts_and_styles(monkeypatch):
    html = """
    <html><body>
      <script>var x = 1;</script>
      <style>.a { color: red; }</style>
      <h1>About Us</h1>
      <p>Jane Doe is our CTO.</p>
    </body></html>
    """
    monkeypatch.setattr(
        people_finder.requests, "get", lambda url, timeout, headers: FakeHttpResponse(text=html)
    )
    text = people_finder.fetch_page_text("https://example.com/about")
    assert "var x = 1" not in text
    assert "color: red" not in text
    assert "Jane Doe is our CTO" in text


def test_fetch_page_text_truncates_to_max_chars(monkeypatch):
    html = "<p>" + ("word " * 5000) + "</p>"
    monkeypatch.setattr(
        people_finder.requests, "get", lambda url, timeout, headers: FakeHttpResponse(text=html)
    )
    text = people_finder.fetch_page_text("https://example.com/about", max_chars=100)
    assert len(text) <= 100


def test_fetch_page_text_returns_none_on_http_error(monkeypatch):
    monkeypatch.setattr(
        people_finder.requests, "get", lambda url, timeout, headers: FakeHttpResponse(status_code=404)
    )
    assert people_finder.fetch_page_text("https://example.com/about") is None


def test_build_user_content_includes_company_url_and_text():
    content = people_finder.build_user_content("Foo Corp", "https://foo.com/about", "Jane is CTO.")
    assert "Foo Corp" in content
    assert "https://foo.com/about" in content
    assert "Jane is CTO." in content


def test_find_team_page_url_returns_first_working_candidate(monkeypatch):
    def fake_head(url, timeout, allow_redirects):
        if url == "https://foo.com/about":
            return FakeHttpResponse(status_code=200)
        return FakeHttpResponse(status_code=404)

    # HEAD 404/405 triggers a GET fallback (some servers don't support HEAD)
    # -- mock both, or an unmocked candidate silently hits the real network.
    monkeypatch.setattr(people_finder.requests, "head", fake_head)
    monkeypatch.setattr(
        people_finder.requests, "get", lambda url, timeout, allow_redirects: FakeHttpResponse(status_code=404)
    )
    url = people_finder.find_team_page_url("https://foo.com")
    assert url == "https://foo.com/about"


def test_find_team_page_url_falls_back_to_careers_url(monkeypatch):
    def fake_head(url, timeout, allow_redirects):
        if url == "https://foo.com/careers":
            return FakeHttpResponse(status_code=200)
        return FakeHttpResponse(status_code=404)

    monkeypatch.setattr(people_finder.requests, "head", fake_head)
    monkeypatch.setattr(
        people_finder.requests, "get", lambda url, timeout, allow_redirects: FakeHttpResponse(status_code=404)
    )
    url = people_finder.find_team_page_url("https://foo.com", careers_url="https://foo.com/careers")
    assert url == "https://foo.com/careers"


def test_find_team_page_url_returns_none_when_nothing_resolves(monkeypatch):
    monkeypatch.setattr(
        people_finder.requests, "head", lambda url, timeout, allow_redirects: FakeHttpResponse(status_code=404)
    )
    monkeypatch.setattr(
        people_finder.requests, "get", lambda url, timeout, allow_redirects: FakeHttpResponse(status_code=404)
    )
    assert people_finder.find_team_page_url("https://foo.com") is None


def test_find_team_page_url_returns_none_for_empty_website():
    assert people_finder.find_team_page_url("") is None


def test_to_contacts_requires_a_source_url():
    person = people_finder.ExtractedPerson(name="Jane Doe", title="CTO", fact="Leads engineering.")
    with pytest.raises(ValueError):
        people_finder.to_contacts([person], company_id=1, source_url="")


def test_to_contacts_attaches_the_given_source_url_not_anything_from_the_model():
    person = people_finder.ExtractedPerson(name="Jane Doe", title="CTO", fact="Leads engineering.")
    contacts = people_finder.to_contacts([person], company_id=1, source_url="https://real-source.com/about")
    assert len(contacts) == 1
    assert contacts[0].source_url == "https://real-source.com/about"
    assert isinstance(contacts[0], Contact)


def test_to_contacts_skips_people_missing_name_or_title():
    good = people_finder.ExtractedPerson(name="Jane Doe", title="CTO", fact="x")
    no_title = people_finder.ExtractedPerson(name="John Smith", title="", fact="x")
    contacts = people_finder.to_contacts([good, no_title], company_id=1, source_url="https://x.com")
    assert len(contacts) == 1
    assert contacts[0].name == "Jane Doe"


def test_to_contacts_only_includes_email_when_present():
    with_email = people_finder.ExtractedPerson(name="A", title="CTO", fact="x", email="a@foo.com")
    without_email = people_finder.ExtractedPerson(name="B", title="CEO", fact="x")
    contacts = people_finder.to_contacts([with_email, without_email], company_id=1, source_url="https://x.com")
    assert contacts[0].email == "a@foo.com"
    assert contacts[1].email is None


class FakeParseResponse:
    def __init__(self, people):
        self.parsed_output = people_finder.ExtractionResult(people=people)


class FakeMessages:
    def __init__(self, people, capture):
        self._people = people
        self._capture = capture

    def parse(self, **kwargs):
        self._capture.update(kwargs)
        return FakeParseResponse(self._people)


class FakeAnthropicClient:
    def __init__(self, people):
        self.capture = {}
        self.messages = FakeMessages(people, self.capture)


def test_extract_people_calls_claude_with_expected_model_and_system_prompt():
    fake_person = people_finder.ExtractedPerson(name="Jane Doe", title="Founder", fact="Founded the company.")
    client = FakeAnthropicClient([fake_person])

    result = people_finder.extract_people(client, "Foo Corp", "https://foo.com/about", "Jane Doe is the founder.")

    assert result == [fake_person]
    assert client.capture["model"] == people_finder.config.PEOPLE_FINDER_MODEL
    assert "LinkedIn" in client.capture["system"]
    assert client.capture["output_format"] is people_finder.ExtractionResult


def test_extract_people_caps_at_max_contacts_per_company():
    many_people = [
        people_finder.ExtractedPerson(name=f"Person {i}", title="Engineer", fact="x") for i in range(10)
    ]
    client = FakeAnthropicClient(many_people)
    result = people_finder.extract_people(client, "Foo Corp", "https://foo.com/about", "text")
    assert len(result) == people_finder.config.MAX_CONTACTS_PER_COMPANY
