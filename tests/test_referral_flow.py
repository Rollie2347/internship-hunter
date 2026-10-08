"""The referral-first redesign (2026-10-08): five people a day, the right
channel for each, people he knows first, and applications only on demand."""

from datetime import date
from types import SimpleNamespace

import pytest

from internship_hunter import config, db
from internship_hunter.approvals import bot, queue
from internship_hunter.drafting import batch, daily_cap
from internship_hunter.drafting.compose import DraftEmail
from internship_hunter.linkedin_assist import assist as linkedin
from internship_hunter.models import Application, Company, Contact, Message, Posting
from internship_hunter.outreach import paste, priority


@pytest.fixture
def conn(tmp_path):
    connection = db.get_connection(tmp_path / "test_tracker.db")
    db.init_db(connection)
    yield connection
    connection.close()


@pytest.fixture
def profile(tmp_path, monkeypatch):
    about = tmp_path / "about_me.md"
    about.write_text("**Name:** Test Student\n**Contact:** t@example.com\nProjects: Argus - https://example.com/argus\n", encoding="utf-8")
    monkeypatch.setattr(config, "ABOUT_ME_PATH", about)
    monkeypatch.setattr(config, "RESUME_PATH_TXT", tmp_path / "missing.txt")
    monkeypatch.setattr(config, "RESUME_PATH_PDF", tmp_path / "missing.pdf")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "42")


@pytest.fixture
def gmail(monkeypatch):
    """No real Claude or Gmail for emails: a fixed draft, and a record of
    who each was addressed to and what ask was requested."""
    seen = SimpleNamespace(to=[], asks=[])

    def fake_compose(*args, **kwargs):
        seen.asks.append(kwargs.get("ask_type"))
        return DraftEmail(subject="15-year-old who builds drones", body="I'm 15. https://example.com/argus")

    def fake_create_draft(service, subject, body, to_email=None):
        seen.to.append(to_email)
        return f"draft-{len(seen.to)}"

    monkeypatch.setattr(batch.compose, "compose_email", fake_compose)
    monkeypatch.setattr(batch.gmail_client, "create_draft", fake_create_draft)
    monkeypatch.setattr(bot, "_gmail_service", lambda: object())
    return seen


def add_company(conn, name="Foo Robotics", tier=1, state="CO") -> Company:
    company = Company(
        name=name, website="https://foo.example", state=state, city="X", stage="seed",
        what_they_build="drone autonomy software", why_fit="x", careers_url="https://foo.example", priority_tier=tier,
    )
    company.id = db.insert_company(conn, company)
    return company


def add_contact(conn, company, name, email=None) -> Contact:
    contact = Contact(company_id=company.id, name=name, title="CTO", source_url="https://foo.example/team", fact="Is the CTO.", email=email)
    contact.id = db.insert_contact(conn, contact)
    return contact


def add_posting(conn, company, external_id="a", **overrides) -> Posting:
    fields = dict(
        company_id=company.id, external_id=external_id, title="Software Engineer", location="Denver, CO",
        url=f"https://jobs.example/foo/{external_id}", ats_source="greenhouse", is_software_role=True,
    )
    fields.update(overrides)
    posting = Posting(**fields)
    posting.id, _ = db.upsert_posting(conn, posting)
    return posting


class NoteClient:
    """Answers both kinds of note: the short LinkedIn one and the longer pasted one."""

    def __init__(self):
        self.calls = []
        self.messages = self

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["output_format"] is linkedin.DraftNote:
            return SimpleNamespace(parsed_output=linkedin.DraftNote(note="I'm 15 and built Argus. Could I ask you about your work?"))
        return SimpleNamespace(parsed_output=paste.DraftMessage(
            message="I'm 15, in high school, and built Argus (https://example.com/argus). Who should I talk to?",
        ))


class Outbox:
    def __init__(self):
        self.sent = []

    def __call__(self, text, reply_markup=None):
        self.sent.append((text, reply_markup))
        return {"result": {"message_id": 100 + len(self.sent)}}


def _tap(conn, data, outbox, monkeypatch):
    monkeypatch.setattr(bot.telegram_client, "answer_callback_query", lambda *a, **k: None)
    monkeypatch.setattr(bot.telegram_client, "edit_message_buttons", lambda *a, **k: None)
    bot.handle_update(conn, {"update_id": 1, "callback_query": {
        "id": "q", "data": data, "message": {"message_id": 5, "chat": {"id": 42}},
    }}, send=outbox)


# --- who comes first -------------------------------------------------------

def test_tier_comes_first_then_companies_hiring_software_people_now(conn):
    quiet = add_company(conn, "A Quiet Startup", tier=1)
    hiring = add_company(conn, "B Hiring Startup", tier=1)
    big_hiring = add_company(conn, "A Big Hiring Co", tier=2, state="VA")
    add_company(conn, "Elsewhere", tier=1, state="Other")
    add_company(conn, "A Lab", tier=4, state="VA")
    add_posting(conn, hiring, title="Backend Engineer")
    add_posting(conn, big_hiring)
    add_posting(conn, quiet, title="Mechanical Engineer", is_software_role=False)   # not a software signal

    assert [c.id for c in priority.companies_in_order(conn)] == [hiring.id, quiet.id, big_hiring.id]
    signals = priority.hiring_now(conn)
    assert "Backend Engineer" in priority.hiring_line(hiring, signals) and "not something to apply to" in priority.hiring_line(hiring, signals)
    assert priority.hiring_line(quiet, signals) == ""


def test_a_company_already_written_to_waits_behind_ones_that_have_not_been(conn):
    first, second = add_company(conn, "A First"), add_company(conn, "B Second")
    done = add_contact(conn, first, "A Done")
    waiting, other = add_contact(conn, first, "B Waiting"), add_contact(conn, second, "C Other")
    db.insert_message(conn, Message(company_id=first.id, contact_id=done.id, channel="linkedin", subject="s", body="b", status="sent"))
    assert [c.id for _, c in linkedin.next_contacts(conn, 10)] == [other.id, waiting.id]


@pytest.mark.parametrize("title,rank", [
    ("CTO", 0), ("Staff Software Engineer", 0), ("VP, Engineering", 0), ("Head of Autonomy", 0),
    ("Co-Founder & CEO", 1), ("Founder and CTO", 0),
    ("Technical Recruiter", 0), ("Head of Talent", 2),
    ("Chief of Staff", 3), ("VP Marketing", 3), ("", 3),
])
def test_role_rank(title, rank):
    assert priority.role_rank(title) == rank


def test_inside_a_company_the_engineer_gets_the_card_before_the_chief_of_staff(conn):
    company = add_company(conn)
    for name, title in [("Amy Staff", "Chief of Staff"), ("Bob Boss", "CEO"), ("Zed Coder", "Software Engineer")]:
        contact = add_contact(conn, company, name)
        conn.execute("UPDATE contacts SET title = ? WHERE id = ?", (title, contact.id))
    conn.commit()
    assert [c.name for _, c in linkedin.next_contacts(conn, 10)] == ["Zed Coder", "Bob Boss", "Amy Staff"]


def test_a_posting_not_seen_lately_is_no_longer_a_signal(conn):
    company = add_company(conn)
    posting = add_posting(conn, company)
    conn.execute("UPDATE postings SET last_seen_date = date('now', '-30 days') WHERE id = ?", (posting.id,))
    conn.commit()
    assert priority.hiring_now(conn) == {}


# --- five a day, the right channel for each ----------------------------------

def test_the_daily_batch_is_five_people_email_where_published_linkedin_otherwise(conn, profile, gmail, monkeypatch):
    company = add_company(conn)
    add_contact(conn, company, "A Email", email="a.email@foo.example")
    for i in range(8):
        add_contact(conn, company, f"Person{i} Last{i}")
    outbox, client = Outbox(), NoteClient()
    monkeypatch.setattr(bot, "_anthropic_client", lambda: client)

    assert bot.send_daily_outreach(conn, outbox) == 5

    by_channel = [m.channel for m in db.list_messages(conn)]
    assert by_channel.count("email") == 1 and by_channel.count("linkedin") == 4
    assert gmail.to == ["a.email@foo.example"]          # never a blank "To"
    assert gmail.asks == ["call"]                        # a first note asks for a call, not a job
    assert daily_cap.outreach_remaining(conn) == 0
    assert bot.send_daily_outreach(conn, outbox) == 0    # nothing more arrives on its own today

    # ...but he can still ask for more himself, up to the hard caps.
    assert bot.send_linkedin_cards(conn, 2, send=outbox, client=client) == 2


def test_a_failure_in_the_email_half_does_not_stop_the_linkedin_cards(conn, profile, monkeypatch):
    company = add_company(conn)
    add_contact(conn, company, "A One")
    monkeypatch.setattr(bot, "_anthropic_client", lambda: NoteClient())
    monkeypatch.setattr(bot, "send_drafts", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("gmail down")))
    outbox = Outbox()

    assert bot.send_daily_outreach(conn, outbox) == 1

    assert "Couldn't prepare today's emails: gmail down" in outbox.sent[0][0]
    assert [m.channel for m in db.list_messages(conn)] == ["linkedin"]


def test_the_daily_run_sends_people_and_no_application_cards(conn, profile, gmail, monkeypatch):
    company = add_company(conn)
    add_contact(conn, company, "A One")
    add_posting(conn, company, is_intern_or_junior=True, skill_match="strong")   # would have been a card before
    monkeypatch.setattr(bot, "_anthropic_client", lambda: NoteClient())
    monkeypatch.setattr(bot, "find_new_people", lambda *a, **k: 0)
    from internship_hunter.scanner import scan
    monkeypatch.setattr(scan, "run_scan", lambda conn: [])
    monkeypatch.setattr(bot, "propose_batch", lambda *a, **k: (_ for _ in ()).throw(AssertionError("application card sent")))
    outbox = Outbox()

    assert bot.run_daily(conn, send=outbox, today=date(2026, 10, 8)) is True

    assert db.list_applications(conn) == []
    assert [m.channel for m in db.list_messages(conn)] == ["linkedin"]
    assert "the referral pipeline" in outbox.sent[-1][0]


# --- Not found -> another way ----------------------------------------------

def linkedin_card(conn, company, contact) -> int:
    return db.insert_message(conn, Message(company_id=company.id, contact_id=contact.id, channel="linkedin", subject="s", body="note"))


def test_not_found_with_no_published_inbox_gives_a_contact_form_note(conn, profile, monkeypatch):
    company = add_company(conn)
    contact = add_contact(conn, company, "Jane Doe")
    card_id = linkedin_card(conn, company, contact)
    client = NoteClient()
    monkeypatch.setattr(bot, "_anthropic_client", lambda: client)
    outbox = Outbox()

    _tap(conn, f"li_nf:{card_id}", outbox, monkeypatch)

    assert db.get_message(conn, card_id).status == "not_found"
    note = next(m for m in db.list_messages(conn) if m.channel == "other")
    text, markup = outbox.sent[0]
    assert f"Note #{note.id}" in text and "contact form" in text and "https://foo.example" in text and note.body in text
    assert config.availability_statement() in client.calls[0]["messages"][0]["content"]
    assert [b["callback_data"] for b in markup["inline_keyboard"][0]] == [f"li_sent:{note.id}", f"li_skip:{note.id}"]
    assert daily_cap.outreach_today(conn) == 1          # the second try at the same person is free

    _tap(conn, f"li_sent:{note.id}", outbox, monkeypatch)
    assert db.get_message(conn, note.id).status == "sent"


def test_not_found_with_a_published_inbox_gives_an_email_draft_to_it(conn, profile, gmail, monkeypatch):
    company = add_company(conn)
    db.set_company_contact_email(conn, company.id, "careers@foo.example")
    contact = add_contact(conn, company, "Jane Doe")
    card_id = linkedin_card(conn, company, contact)
    monkeypatch.setattr(bot, "_anthropic_client", lambda: NoteClient())
    outbox = Outbox()

    _tap(conn, f"li_nf:{card_id}", outbox, monkeypatch)

    assert gmail.to == ["careers@foo.example"]
    assert "the company's published inbox, not a personal address" in outbox.sent[0][0]


def test_a_failure_drafting_the_other_way_still_records_not_found(conn, profile, monkeypatch):
    company = add_company(conn)
    card_id = linkedin_card(conn, company, add_contact(conn, company, "Jane Doe"))
    outbox = Outbox()
    _tap(conn, f"li_nf:{card_id}", outbox, monkeypatch)   # the conftest guard makes the Claude call fail
    assert db.get_message(conn, card_id).status == "not_found"
    assert "Couldn't draft another way" in outbox.sent[0][0]


def test_a_pasted_note_gets_its_one_reminder_too(conn, profile):
    company = add_company(conn)
    contact = add_contact(conn, company, "Jane Doe")
    note_id = db.insert_message(conn, Message(
        company_id=company.id, contact_id=contact.id, channel="other", subject="s", body="b",
        status="sent", sent_at="2026-09-28 09:00:00",
    ))
    outbox = Outbox()
    assert bot.send_linkedin_reminders(conn, outbox, date(2026, 10, 8)) == 1
    assert outbox.sent[0][0].startswith(f"Note #{note_id}")


# --- people he already knows -------------------------------------------------

def test_parse_warm_command():
    person = paste.parse_warm_command("/warm Tom Reyes, my uncle in Denver, engineer at a satellite company, Boulder")
    assert (person.name, person.relationship) == ("Tom Reyes", "my uncle in Denver")
    assert person.works_at == "engineer at a satellite company, Boulder"
    assert paste.parse_warm_command("/warm Tom Reyes") is None and paste.parse_warm_command("/warm") is None


def test_warm_adds_someone_he_knows_and_asks_who_to_talk_to_not_for_a_job(conn, profile):
    outbox, client = Outbox(), NoteClient()

    bot.add_warm_person(conn, "/warm Tom Reyes, my uncle in Denver, engineer at a satellite company", outbox, client)

    network = db.get_company_by_name(conn, config.NETWORK_COMPANY_NAME)
    contact = db.list_contacts(conn, company_id=network.id)[0]
    assert (contact.name, contact.fact, contact.title) == ("Tom Reyes", "my uncle in Denver", "engineer at a satellite company")
    call = client.calls[0]
    assert "ALREADY KNOWS" in call["system"] and "NOT for a job" in call["system"]
    assert "my uncle in Denver" in call["messages"][0]["content"]
    note = db.list_messages(conn)[0]
    assert note.channel == "other" and "someone you know (my uncle in Denver)" in outbox.sent[0][0]

    # Asking twice doesn't draft a second note.
    bot.add_warm_person(conn, "/warm Tom Reyes, my uncle in Denver", outbox, client)
    assert len(db.list_messages(conn)) == 1 and "already" in outbox.sent[-1][0]


def test_people_he_knows_are_never_picked_as_cold_contacts_or_scanned(conn, profile, monkeypatch):
    bot.add_warm_person(conn, "/warm Tom Reyes, my uncle in Denver", Outbox(), NoteClient())
    conn.execute("DELETE FROM messages")
    conn.commit()
    assert linkedin.next_contacts(conn, 10) == [] and batch.next_contacts(conn, 10) == []

    from internship_hunter.scanner import scan
    scanned = []
    monkeypatch.setattr(scan, "scan_company", lambda conn, company: scanned.append(company.name) or [])
    add_company(conn)
    scan.run_scan(conn)
    assert scanned == ["Foo Robotics"]


def test_warm_with_junk_shows_usage(conn, profile):
    outbox = Outbox()
    bot.handle_command(conn, "/warm", outbox)
    assert outbox.sent[0][0] == paste.WARM_USAGE


# --- after a reply: call, referral -------------------------------------------

def test_stage_taps_walk_a_reply_to_a_call_to_a_referral(conn, profile, monkeypatch):
    company = add_company(conn)
    message_id = db.insert_message(conn, Message(
        company_id=company.id, contact_id=add_contact(conn, company, "Jane Doe").id, channel="email",
        subject="s", body="b", status="replied",
    ))
    outbox = Outbox()

    _tap(conn, f"st_call:{message_id}", outbox, monkeypatch)
    assert db.get_message(conn, message_id).status == "call" and "who else you should talk to" in outbox.sent[-1][0]

    _tap(conn, f"st_ref:{message_id}", outbox, monkeypatch)
    assert db.get_message(conn, message_id).status == "referred" and "/apply <link>" in outbox.sent[-1][0]


def test_it_went_nowhere_is_recorded(conn, profile, monkeypatch):
    company = add_company(conn)
    message_id = db.insert_message(conn, Message(company_id=company.id, channel="linkedin", subject="s", body="b", status="replied"))
    _tap(conn, f"st_no:{message_id}", Outbox(), monkeypatch)
    assert db.get_message(conn, message_id).status == "rejected"


def test_an_email_reply_tap_offers_the_stage_buttons(conn, profile, monkeypatch):
    company = add_company(conn)
    message_id = db.insert_message(conn, Message(company_id=company.id, channel="email", subject="s", body="b", status="sent"))
    from internship_hunter.drafting import gmail_client
    monkeypatch.setattr(gmail_client, "has_read_access", lambda: False)
    outbox = Outbox()
    _tap(conn, f"replied:{message_id}", outbox, monkeypatch)
    assert outbox.sent[0][1]["inline_keyboard"][0][0]["callback_data"] == f"st_call:{message_id}"


def test_funnel_counts_each_person_once_at_the_furthest_stage_they_reached():
    def m(id, contact_id, channel, status):
        return Message(id=id, company_id=1, contact_id=contact_id, channel=channel, subject="s", body="b", status=status)

    messages = [
        m(1, 10, "linkedin", "not_found"), m(2, 10, "other", "sent"),      # one person, two tries
        m(3, 11, "email", "replied"),
        m(4, 12, "linkedin", "call"),
        m(5, 13, "email", "referred"), m(6, 13, "linkedin_reply", "drafted"),
        m(7, 14, "email", "drafted"),                                      # not sent yet: not contacted
        m(8, 15, "email", "rejected"),                                     # they answered, it went nowhere
    ]
    assert queue.funnel(messages) == {"contacted": 5, "replied": 4, "calls": 2, "referrals": 1}


# --- applications: only when he asks -----------------------------------------

def test_apply_sends_the_card_for_a_posting_someone_pointed_him_to_even_if_screening_ruled_it_out(conn, profile):
    company = add_company(conn)
    posting = add_posting(conn, company)
    db.set_posting_eligibility(conn, posting.id, "not_eligible", "It requires college enrollment.")
    outbox = Outbox()

    class NoAnswers:
        messages = None

    posting = db.get_posting(conn, posting.id)   # as /apply reads it: with the screening verdict
    sent = bot.propose_batch(conn, NoAnswers(), 1, send=outbox, fetch_form=lambda p: ([], []), postings=[posting])

    assert sent == 1 and db.list_applications(conn)[0].posting_id == posting.id
    assert "The posting itself says: It requires college enrollment." in outbox.sent[0][0]
    # /more still never offers it.
    assert queue.next_postings(conn, 10) == []


def test_apply_matches_the_link_ignoring_tracking_and_a_trailing_apply(conn, profile, monkeypatch):
    company = add_company(conn)
    posting = add_posting(conn, company)
    asked = []
    monkeypatch.setattr(bot, "propose_batch", lambda conn, client, limit, send, postings=None: asked.append(postings) or 1)

    bot.apply_through_link(conn, posting.url + "/apply?utm_source=email", Outbox(), client=object())
    assert [p.id for p in asked[0]] == [posting.id]


def test_apply_with_an_unknown_link_or_an_existing_application_makes_no_card(conn, profile, monkeypatch):
    company = add_company(conn)
    posting = add_posting(conn, company)
    monkeypatch.setattr(bot, "propose_batch", lambda *a, **k: (_ for _ in ()).throw(AssertionError("card made")))
    outbox = Outbox()

    bot.apply_through_link(conn, "https://careers.example/unknown/123", outbox, client=object())
    assert "apply by hand" in outbox.sent[-1][0]

    app_id = db.insert_application(conn, Application(posting_id=posting.id))
    bot.apply_through_link(conn, posting.url, outbox, client=object())
    assert f"/open {app_id}" in outbox.sent[-1][0]

    bot.handle_command(conn, "/apply", outbox)
    assert "Usage: /apply" in outbox.sent[-1][0]
