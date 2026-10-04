import pytest

from internship_hunter.scanner import ats_feeds


class FakeResponse:
    def __init__(self, json_data=None, status_code=200):
        self._json_data = json_data
        self.status_code = status_code

    def json(self):
        if self._json_data is None:
            raise ValueError("no json")
        return self._json_data


def test_slug_candidates_keeps_full_name_variant_first():
    candidates = ats_feeds.slug_candidates("Anduril Industries")
    assert "andurilindustries" in candidates
    assert "anduril-industries" in candidates


def test_slug_candidates_does_not_include_a_bare_first_word():
    # Regression test: a bare first-word guess ("sierra" for "Sierra Space")
    # actually matched a different, unrelated company's real Ashby board
    # during a live run -- see slug_candidates' docstring. Multi-word
    # company names should only produce distinctive, full-name-derived
    # candidates, never a generic single word.
    candidates = ats_feeds.slug_candidates("Sierra Space")
    assert "sierra" not in candidates
    assert "sierraspace" in candidates


def test_slug_candidates_has_no_duplicates():
    candidates = ats_feeds.slug_candidates("Shield AI")
    assert len(candidates) == len(set(candidates))


def test_try_greenhouse_parses_jobs(monkeypatch):
    fake_payload = {
        "jobs": [
            {
                "id": 123,
                "title": "Software Engineering Intern",
                "location": {"name": "Arlington, VA"},
                "absolute_url": "https://boards.greenhouse.io/foo/jobs/123",
                "content": "Write Python and JavaScript.",
            }
        ]
    }
    monkeypatch.setattr(
        ats_feeds.requests, "get", lambda url, timeout: FakeResponse(fake_payload)
    )
    postings = ats_feeds._try_greenhouse("foo")
    assert len(postings) == 1
    p = postings[0]
    assert p.external_id == "123"
    assert p.title == "Software Engineering Intern"
    assert p.location == "Arlington, VA"
    assert p.ats_source == "greenhouse"
    assert "Python" in p.text


def test_try_greenhouse_returns_none_on_404(monkeypatch):
    monkeypatch.setattr(
        ats_feeds.requests, "get", lambda url, timeout: FakeResponse(status_code=404)
    )
    assert ats_feeds._try_greenhouse("nonexistent") is None


def test_try_lever_parses_jobs(monkeypatch):
    fake_payload = [
        {
            "id": "abc",
            "text": "Full Stack Intern",
            "categories": {"location": "Denver, CO"},
            "hostedUrl": "https://jobs.lever.co/foo/abc",
            "descriptionPlain": "React and Node.js.",
        }
    ]
    monkeypatch.setattr(
        ats_feeds.requests, "get", lambda url, timeout: FakeResponse(fake_payload)
    )
    postings = ats_feeds._try_lever("foo")
    assert len(postings) == 1
    assert postings[0].title == "Full Stack Intern"
    assert postings[0].location == "Denver, CO"
    assert postings[0].ats_source == "lever"


def test_try_lever_includes_requirement_lists_in_text(monkeypatch):
    # Regression: a real Palantir "US Government" posting stated its
    # clearance requirement only inside a Lever "lists" block (a "What We
    # Require" section), not in descriptionPlain -- requires_clearance()
    # would have silently missed it without this.
    fake_payload = [
        {
            "id": "gov1",
            "text": "Deployment Strategist - US Government",
            "categories": {"location": "New York, NY"},
            "hostedUrl": "https://jobs.lever.co/palantir/gov1",
            "descriptionPlain": "Work with government customers.",
            "lists": [
                {
                    "text": "What We Require",
                    "content": "<li>Active US Security clearance or eligibility.</li>",
                }
            ],
        }
    ]
    monkeypatch.setattr(
        ats_feeds.requests, "get", lambda url, timeout: FakeResponse(fake_payload)
    )
    postings = ats_feeds._try_lever("palantir")
    assert "clearance" in postings[0].text.lower()


def test_try_lever_returns_none_when_not_a_list(monkeypatch):
    monkeypatch.setattr(
        ats_feeds.requests, "get", lambda url, timeout: FakeResponse({"not": "a list"})
    )
    assert ats_feeds._try_lever("foo") is None


def test_try_ashby_parses_jobs(monkeypatch):
    fake_payload = {
        "jobs": [
            {
                "id": "xyz",
                "title": "Backend Intern",
                "location": "Remote",
                "jobUrl": "https://jobs.ashbyhq.com/foo/xyz",
                "descriptionPlain": "Python backend work.",
            }
        ]
    }
    monkeypatch.setattr(
        ats_feeds.requests, "get", lambda url, timeout: FakeResponse(fake_payload)
    )
    postings = ats_feeds._try_ashby("foo")
    assert len(postings) == 1
    assert postings[0].title == "Backend Intern"
    assert postings[0].ats_source == "ashby"


def test_fetch_known_returns_empty_list_for_unknown_ats_type():
    assert ats_feeds.fetch_known("workday", "foo") == []


def test_detect_and_fetch_merges_all_confirmed_vendors(monkeypatch):
    def fake_get(url, timeout):
        if "boards-api.greenhouse.io" in url and "foocorp" in url:
            return FakeResponse({"jobs": [{"id": 1, "title": "SWE Intern", "location": {"name": "VA"}, "absolute_url": "u", "content": ""}]})
        return FakeResponse(status_code=404)

    monkeypatch.setattr(ats_feeds.requests, "get", fake_get)
    postings, confirmed = ats_feeds.detect_and_fetch("Foo Corp")
    assert len(postings) == 1
    assert ("greenhouse", "foocorp") in confirmed
