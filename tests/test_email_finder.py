from internship_hunter.models import Company, Contact
from internship_hunter.people import email_finder


class FakeResponse:
    def __init__(self, status_code=200, text="", payload=None):
        self.status_code, self.text, self._payload = status_code, text, payload or {}

    def json(self):
        return self._payload


def contact(contact_id, name):
    return Contact(id=contact_id, company_id=1, name=name, title="Engineer", source_url="https://foo.example/team", fact="x")


COMPANY = Company(
    name="Foo Defense Labs", website="https://foo.example", state="CO", city="Denver", stage="seed",
    what_they_build="x", why_fit="x", careers_url="https://foo.example", priority_tier=1, id=1,
)


def test_email_belongs_to_needs_the_last_name_not_just_a_first_name():
    assert email_finder.email_belongs_to("jane.doe@foo.example", "Jane Doe")
    assert email_finder.email_belongs_to("jdoe@foo.example", "Dr. Jane Doe")
    assert email_finder.email_belongs_to("janed@foo.example", "Jane Doe")
    assert not email_finder.email_belongs_to("jane@foo.example", "Jane Doe")
    assert not email_finder.email_belongs_to("john.smith@foo.example", "Jane Doe")


def test_site_emails_are_matched_to_the_right_person_with_their_source_page():
    pages = {
        "https://foo.example/team": "Reach Jane at jane.doe@foo.example or careers@foo.example. press@foo.example",
        "https://foo.example/about": "Contact smith@foo.example",
    }

    def fake_get(url, timeout=None, headers=None):
        return FakeResponse(text=pages[url]) if url in pages else FakeResponse(status_code=404)

    people = [contact(1, "Jane Doe"), contact(2, "Al Smith"), contact(3, "Bo Smith"), contact(4, "Cy Young")]
    found = email_finder.find_on_company_site(COMPANY, people, get=fake_get)
    # smith@ fits two people, so it's given to neither; nobody gets the careers inbox.
    assert found == {1: ("jane.doe@foo.example", "https://foo.example/team")}


def github(profiles):
    def fake_get(url, params=None, headers=None, timeout=None):
        if url.endswith("/search/users"):
            return FakeResponse(payload={"items": [{"login": login} for login in profiles]})
        return FakeResponse(payload=profiles[url.rsplit("/", 1)[1]])
    return fake_get


def test_github_email_only_when_name_and_company_both_match():
    right = {"name": "Jane Doe", "company": "@foo-defense", "email": "Jane@Personal.dev", "html_url": "https://github.com/janedoe"}
    assert email_finder.find_on_github("Jane Doe", "Foo Defense Labs", get=github({"janedoe": right})) == (
        "jane@personal.dev", "https://github.com/janedoe",
    )
    stranger = dict(right, company="Some Other Co")
    assert email_finder.find_on_github("Jane Doe", "Foo Defense Labs", get=github({"janedoe": stranger})) is None
    other_name = dict(right, name="Janet Doe")
    assert email_finder.find_on_github("Jane Doe", "Foo Defense Labs", get=github({"janedoe": other_name})) is None
    no_email = dict(right, email=None)
    assert email_finder.find_on_github("Jane Doe", "Foo Defense Labs", get=github({"janedoe": no_email})) is None


def test_github_rate_limit_is_raised_not_swallowed():
    import pytest

    with pytest.raises(email_finder.GitHubRateLimited):
        email_finder.find_on_github("Jane Doe", "Foo", get=lambda *a, **k: FakeResponse(status_code=403))
