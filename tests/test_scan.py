import pytest

from internship_hunter import db
from internship_hunter.models import Company
from internship_hunter.scanner import ats_feeds, scan


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


def fake_raw_posting(**overrides):
    defaults = dict(
        external_id="1",
        title="Software Engineering Intern",
        location="Arlington, VA",
        url="https://foo.example/jobs/1",
        text="Software Engineering Intern Arlington, VA Python and JavaScript, no clearance needed.",
        ats_source="greenhouse",
    )
    defaults.update(overrides)
    return ats_feeds.RawPosting(**defaults)


def test_scan_company_marks_first_run_postings_as_new(conn, monkeypatch):
    company = make_company(conn)
    monkeypatch.setattr(
        ats_feeds, "detect_and_fetch", lambda name: ([fake_raw_posting()], [("greenhouse", "foocorp")])
    )

    new_postings = scan.scan_company(conn, company)

    assert len(new_postings) == 1
    assert new_postings[0].posting.title == "Software Engineering Intern"
    assert new_postings[0].worth_notifying is True

    # ATS got cached on the company record.
    refreshed = db.get_company_by_name(conn, "Foo Corp")
    assert refreshed.ats_type == "greenhouse"
    assert refreshed.ats_slug == "foocorp"


def test_scan_company_does_not_resurface_already_seen_postings(conn, monkeypatch):
    company = make_company(conn, ats_type="greenhouse", ats_slug="foocorp")
    monkeypatch.setattr(ats_feeds, "fetch_known", lambda ats_type, slug: [fake_raw_posting()])

    first_run = scan.scan_company(conn, company)
    second_run = scan.scan_company(conn, company)

    assert len(first_run) == 1
    assert len(second_run) == 0  # same external_id, already stored


def test_scan_company_flags_manual_check_when_no_ats_found(conn, monkeypatch):
    company = make_company(conn)
    monkeypatch.setattr(ats_feeds, "detect_and_fetch", lambda name: ([], []))
    monkeypatch.setattr("internship_hunter.scanner.careers_fallback.careers_url_is_reachable", lambda url: True)

    scan.scan_company(conn, company)

    refreshed = db.get_company_by_name(conn, "Foo Corp")
    assert refreshed.manual_check_needed is True


def test_scan_company_does_not_notify_for_clearance_or_hardware_roles(conn, monkeypatch):
    company = make_company(conn)
    clearance_role = fake_raw_posting(
        external_id="2",
        title="Software Engineer Intern",
        text="Software Engineer Intern. Active TS/SCI clearance required.",
    )
    hardware_role = fake_raw_posting(
        external_id="3",
        title="Mechanical Engineer Intern",
        text="Mechanical Engineer Intern. CAD and manufacturing.",
    )
    monkeypatch.setattr(
        ats_feeds, "detect_and_fetch", lambda name: ([clearance_role, hardware_role], [("greenhouse", "foocorp")])
    )

    new_postings = scan.scan_company(conn, company)

    assert len(new_postings) == 2
    assert all(not n.worth_notifying for n in new_postings)


def test_build_telegram_digest_returns_none_when_nothing_worth_notifying(conn):
    company = make_company(conn)
    posting_new = scan.NewPosting(
        company=company,
        posting=db.posting_from_row(
            conn.execute(
                "INSERT INTO postings (company_id, external_id, title, skill_match) "
                "VALUES (?, '1', 'x', 'gap') RETURNING *",
                (company.id,),
            ).fetchone()
        ),
        worth_notifying=False,
    )
    assert scan.build_telegram_digest([posting_new]) is None


def test_build_telegram_digest_includes_company_title_and_skill_tag(conn):
    company = make_company(conn)
    row = conn.execute(
        "INSERT INTO postings (company_id, external_id, title, location, url, skill_match) "
        "VALUES (?, '1', 'Software Engineering Intern', 'Arlington, VA', 'https://x', 'strong') RETURNING *",
        (company.id,),
    ).fetchone()
    posting_new = scan.NewPosting(company=company, posting=db.posting_from_row(row), worth_notifying=True)

    digest = scan.build_telegram_digest([posting_new])

    assert "Foo Corp" in digest
    assert "Software Engineering Intern" in digest
    assert "strong fit" in digest
