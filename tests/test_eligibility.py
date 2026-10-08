import pytest

from internship_hunter import db
from internship_hunter.approvals import bot, queue
from internship_hunter.models import Company, Posting
from internship_hunter.scanner import eligibility
from internship_hunter.scanner.eligibility import Verdict

ROCKET_LAB = (
    "QUALIFICATIONS Ideal candidates will thrive in ambiguity. Must be enrolled in a bachelor's, master's or "
    "doctorate degree program in Computer science, computer engineering, or software engineering and have at "
    "least one semester of school remaining post internship. GPA of 3.0 or above."
)


@pytest.mark.parametrize("text,meaning", [
    (ROCKET_LAB, "enrolled in a college degree program"),
    ("We are hiring. Currently pursuing a B.S. in Computer Science or related field.", "enrolled in a college degree program"),
    ("Open to rising juniors and seniors with strong Python.", "college students by class year"),
    ("Bachelor's degree in Computer Science is required.", "requires a college degree"),
    ("Requires a BS or MS in a technical field.", "requires a college degree"),
    ("You must be at least 18 years old to apply.", "18 or older"),
    ("Requirements: 3+ years of professional software experience.", "years of professional experience"),
])
def test_hard_requirements_rule_a_posting_out_and_quote_the_sentence(text, meaning):
    verdict = eligibility.screen_text(text)
    assert verdict.verdict == "not_eligible" and meaning in verdict.reason
    assert '"' in verdict.reason  # the deciding sentence is quoted back


@pytest.mark.parametrize("text", [
    "This summer program is open to high school students aged 15 and up. A bachelor's degree is not required.",
    "Paid internship for high schoolers interested in robotics.",
    "We welcome high-school interns on our software team.",
])
def test_postings_for_high_schoolers_are_eligible_outright(text):
    assert eligibility.screen_text(text).verdict == "eligible"


@pytest.mark.parametrize("text", [
    "Build flight software in Python with a small team. Curiosity matters more than credentials.",
    "High school diploma or equivalent. Operate machinery on the production floor.",
    "Nice to have: experience with Docker. You will work with rising stars across the company.",
    # Live false positive: the "ms" in "systems" once read as an M.S. degree.
    "The government's demand for AI is growing far faster than the systems required to support it.",
    "Our platforms and programs required a redesign. Learn about our college outreach on the blog.",
    "",
])
def test_unclear_postings_are_left_for_the_closer_read(text):
    assert eligibility.screen_text(text) is None


def test_model_cannot_rule_a_posting_out_without_a_real_quote():
    text = "Build things with us. Applicants should be enrolled at an institution of higher learning this fall."
    trusted = eligibility.check_assessment(
        "not_eligible", "It requires college enrollment.",
        "Applicants should be enrolled at an institution of higher learning this fall.", text,
    )
    assert trusted.verdict == "not_eligible" and "institution of higher learning" in trusted.reason
    # A quote that isn't in the posting: keep it, flagged, rather than hide it.
    made_up = eligibility.check_assessment("not_eligible", "It requires a degree.", "Must hold a PhD in physics.", text)
    assert made_up.verdict == "long_shot" and "couldn't confirm" in made_up.reason
    assert eligibility.check_assessment("eligible", "Fine.", "", text) == Verdict("eligible", "Fine.")


COMPANY = Company(
    name="Foo", website="https://foo.example", state="CO", city="Denver", stage="seed", what_they_build="x",
    why_fit="x", careers_url="https://foo.example", priority_tier=1, ats_type="greenhouse", ats_slug="foo", id=1,
)
POSTING = Posting(company_id=1, external_id="9", title="Software Intern", location="Denver, CO", url="u", ats_source="greenhouse")


def test_screen_posting_skips_the_model_when_patterns_decide(no_live_requirement_reading):
    screen = no_live_requirement_reading  # the real function

    class ExplodingClient:
        @property
        def messages(self):
            raise AssertionError("the model should not be called")

    verdict = screen(ExplodingClient(), COMPANY, POSTING, fetch_text=lambda *a: ROCKET_LAB)
    assert verdict.verdict == "not_eligible"
    unreadable = screen(ExplodingClient(), COMPANY, POSTING, fetch_text=lambda *a: "")
    assert unreadable.verdict == "long_shot"  # never dropped unseen


@pytest.fixture
def conn(tmp_path):
    connection = db.get_connection(tmp_path / "t.db")
    db.init_db(connection)
    yield connection
    connection.close()


def test_ineligible_postings_never_become_cards_and_cost_no_budget(conn, monkeypatch, tmp_path):
    from internship_hunter import config

    about = tmp_path / "about_me.md"
    about.write_text("**Name:** Test Student\n", encoding="utf-8")
    monkeypatch.setattr(config, "ABOUT_ME_PATH", about)
    monkeypatch.setattr(config, "RESUME_PATH_TXT", tmp_path / "none.txt")
    monkeypatch.setattr(config, "RESUME_PATH_PDF", tmp_path / "none.pdf")
    company = COMPANY
    company.id = db.insert_company(conn, company)
    ids = {}
    for key in ("college", "open", "stretch"):
        ids[key], _ = db.upsert_posting(conn, Posting(
            company_id=company.id, external_id=key, title=f"Software Intern {key}", location="Denver, CO",
            url=f"https://x/{key}", ats_source="greenhouse", is_software_role=True, is_intern_or_junior=True,
            skill_match="strong",
        ))
    verdicts = {
        "college": Verdict("not_eligible", "It requires college enrollment."),
        "open": Verdict("eligible", ""),
        "stretch": Verdict("long_shot", "It is aimed at college students."),
    }
    monkeypatch.setattr(bot.eligibility, "screen_posting", lambda client, company, posting: verdicts[posting.external_id])
    sent = []

    def send(text, reply_markup=None):
        sent.append(text)
        return {"result": {"message_id": len(sent)}}

    assert bot.propose_batch(conn, object(), 10, send=send, fetch_form=lambda p: ([], [])) == 2

    assert {a.posting_id for a in db.list_applications(conn)} == {ids["open"], ids["stretch"]}
    assert db.get_posting(conn, ids["college"]).eligibility == "not_eligible"
    assert any("Long shot: It is aimed at college students." in text for text in sent)
    # Ruled out for good: it is not offered again, and the status says so.
    assert queue.next_postings(conn, 10) == []
    assert "1 ruled out after reading the requirements" in queue.build_status_text(conn)
