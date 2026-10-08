from datetime import date

import pytest

from internship_hunter import config, db
from internship_hunter.approvals import bot, queue
from internship_hunter.models import Application, Company, Contact, Posting
from internship_hunter.scanner import filters


@pytest.fixture
def conn(tmp_path):
    connection = db.get_connection(tmp_path / "test_tracker.db")
    db.init_db(connection)
    yield connection
    connection.close()


def add_company(conn, name="Foo Corp", tier=1, state="VA") -> Company:
    company = Company(
        name=name, website="https://foo.example", state=state, city="X", stage="seed",
        what_they_build="drones", why_fit="x", careers_url="https://foo.example", priority_tier=tier,
    )
    company.id = db.insert_company(conn, company)
    return company


def add_posting(conn, company, external_id, location, **overrides) -> Posting:
    fields = dict(
        company_id=company.id, external_id=external_id, title="Software Engineer Intern",
        location=location, url=f"https://jobs.example/{external_id}", ats_source="greenhouse",
        is_software_role=True, is_intern_or_junior=True, skill_match="strong",
    )
    fields.update(overrides)
    posting = Posting(**fields)
    posting.id, _ = db.upsert_posting(conn, posting)
    return posting


# --- location ranking ------------------------------------------------------

@pytest.mark.parametrize("location,rank", [
    ("Reston, Virginia, United States", 0),
    ("Denver, CO", 0),
    ("Washington, D.C.", 1),
    ("Costa Mesa, California, United States; Broomfield, Colorado, United States", 0),
    ("New York, NY", 1),
    ("San Francisco", 1),
    ("Pittsburgh", 1),
    ("Denver", 0),
    ("San Diego, California", 1),
    ("Remote, United States", 2),
    ("", 2),
    ("Madison, WI", 3),
    ("Paris, France", 4),
    ("London, United Kingdom", 4),
    ("Seoul, South Korea", 4),
])
def test_location_rank(location, rank):
    assert filters.location_rank(location) == rank


def test_location_rank_ignores_lowercase_words_that_look_like_state_codes():
    # "in" and "or" are Indiana's/Oregon's postal codes only in capitals.
    assert filters.location_rank("Based in Lyon or Paris") == 4


# --- queue order -----------------------------------------------------------

def test_next_postings_keeps_only_colorado_and_virginia_in_tier_order(conn):
    startup, big = add_company(conn, "Startup", tier=1), add_company(conn, "BigCo", tier=2)
    big_virginia = add_posting(conn, big, "c", "Reston, VA")
    colorado = add_posting(conn, startup, "b", "Denver, CO")
    multi = add_posting(conn, startup, "m", "Costa Mesa, California, United States; Broomfield, Colorado, United States")
    for external_id, elsewhere in enumerate(["Madison, WI", "Austin, TX", "Washington, D.C.", "Remote", "Paris, France"]):
        add_posting(conn, startup, f"x{external_id}", elsewhere)

    assert [p.id for p in queue.next_postings(conn, 10)] == [colorado.id, multi.id, big_virginia.id]
    assert queue.count_skipped_for_location(conn) == 5


def test_next_postings_excludes_clearance_gap_and_already_proposed(conn):
    company = add_company(conn)
    add_posting(conn, company, "s", "Denver, CO", title="SkillBridge Intern - Platform Engineer")
    add_posting(conn, company, "g", "Denver, CO", title="PhD Software Engineer Intern")
    add_posting(conn, company, "h", "Denver, CO", title="Electrical Engineering Intern")
    add_posting(conn, company, "a", "Denver, CO", clearance_required=True)
    add_posting(conn, company, "b", "Denver, CO", skill_match="gap")
    add_posting(conn, company, "c", "Denver, CO", is_intern_or_junior=False)
    proposed = add_posting(conn, company, "d", "Denver, CO")
    fresh = add_posting(conn, company, "e", "Denver, CO")
    db.insert_application(conn, Application(posting_id=proposed.id))

    assert [p.id for p in queue.next_postings(conn, 10)] == [fresh.id]


# --- cards and buttons -----------------------------------------------------

def test_card_shows_every_drafted_answer_and_what_is_left(conn):
    company = add_company(conn)
    posting = add_posting(conn, company, "a", "Denver, CO")
    text = queue.build_card_text(
        7, company, posting, ["First Name*", "Email*"],
        {"Why us?": "Because of the drones."}, ["Gender", "Are you authorized to work?"],
        resume_available=True,
    )
    assert "Application #7" in text and posting.url in text
    assert "Q: Why us?" in text and "A: Because of the drones." in text
    assert "Gender" in text and "resume attached" in text
    assert "You press Submit" in text


@pytest.mark.parametrize("data,expected", [
    ("approve:12", ("approve", 12)),
    ("skip:3", ("skip", 3)),
    ("submit_for_me:3", None),
    ("approve:abc", None),
    ("", None),
])
def test_parse_callback(data, expected):
    assert queue.parse_callback(data) == expected


# --- status / 7-day clock --------------------------------------------------

def test_waiting_too_long_only_flags_submitted_after_seven_days():
    old = Application(posting_id=1, status="submitted", submitted_at="2026-10-01 09:00:00")
    recent = Application(posting_id=2, status="submitted", submitted_at="2026-10-06 09:00:00")
    interviewing = Application(posting_id=3, status="interviewing", submitted_at="2026-09-01 09:00:00")
    assert queue.waiting_too_long([old, recent, interviewing], today=date(2026, 10, 8)) == [old]


def test_status_text_counts_each_stage(conn):
    company = add_company(conn)
    for i, status in enumerate(["proposed", "submitted", "submitted", "rejected"]):
        posting = add_posting(conn, company, str(i), "Denver, CO")
        app_id = db.insert_application(conn, Application(posting_id=posting.id))
        db.update_application_status(conn, app_id, status)
    text = queue.build_status_text(conn)
    assert "2 submitted, 0 interviewing, 1 rejected" in text
    assert "1 to approve/skip" in text


# --- bot: proposing, tapping buttons, opening forms ------------------------

class FakeParsed:
    def __init__(self, answers):
        self.parsed_output = type("Out", (), {"answers": answers})()


class FakeClient:
    """Stands in for the Anthropic client: answers the first question,
    and tries to sneak in an answer to a question that was never asked."""

    def __init__(self):
        self.calls = 0
        self.messages = self

    def parse(self, **kwargs):
        from internship_hunter.apply_assist.answers import DraftedAnswer

        self.calls += 1
        return FakeParsed([
            DraftedAnswer(question="Why do you want to work here?", answer="I'm 15 and I build drones."),
            DraftedAnswer(question="Gender", answer="made up"),
        ])


@pytest.fixture
def profile(tmp_path, monkeypatch):
    about = tmp_path / "about_me.md"
    about.write_text("**Name:** Test Student\n**Contact:** t@example.com · example.com\n", encoding="utf-8")
    monkeypatch.setattr(config, "ABOUT_ME_PATH", about)
    monkeypatch.setattr(config, "RESUME_PATH_TXT", tmp_path / "missing.txt")
    monkeypatch.setattr(config, "RESUME_PATH_PDF", tmp_path / "missing.pdf")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "42")


class Outbox:
    def __init__(self):
        self.sent = []

    def __call__(self, text, reply_markup=None):
        self.sent.append((text, reply_markup))
        return {"result": {"message_id": 100 + len(self.sent)}}


FORM_CHOICES = [
    {"question": "Are you legally authorized to work in the United States?*", "kind": "select",
     "target": "c0", "options": ["Select...", "Yes", "No"]},
    {"question": "Country*", "kind": "combobox", "target": "c1", "options": None},
    {"question": "Gender", "kind": "select", "target": "c2", "options": ["Male", "Female", "Decline To Self Identify"]},
]
FORM_FIELDS = [("First Name*", "text"), ("Email*", "email"), ("Why do you want to work here?", "textarea"), ("Gender", "select")]


def test_propose_batch_sends_cards_with_buttons_and_never_answers_eeo(conn, profile):
    company = add_company(conn)
    posting = add_posting(conn, company, "a", "Denver, CO")
    outbox, client = Outbox(), FakeClient()

    sent = bot.propose_batch(conn, client, 5, send=outbox, fetch_form=lambda p: (FORM_FIELDS, FORM_CHOICES))

    assert sent == 1
    application = db.list_applications(conn)[0]
    assert application.posting_id == posting.id and application.status == "proposed"
    assert application.answers == {"Why do you want to work here?": "I'm 15 and I build drones."}
    assert "Gender" in application.left_for_you
    # Standing answers are previewed on the card; personal questions are not answered.
    assert "legally authorized to work in the United States?* \u2192 Yes" in outbox.sent[0][0]
    assert "Country* \u2192 United States" in outbox.sent[0][0]
    assert "Gender \u2192" not in outbox.sent[0][0]
    assert application.telegram_message_id == 101
    text, markup = outbox.sent[0]
    buttons = markup["inline_keyboard"][0]
    assert [b["callback_data"] for b in buttons] == [f"approve:{application.id}", f"skip:{application.id}"]
    # Proposing the same posting twice is impossible.
    assert bot.propose_batch(conn, client, 5, send=outbox, fetch_form=lambda p: (FORM_FIELDS, FORM_CHOICES)) == 0


def test_propose_batch_stops_at_the_daily_cap(conn, profile, monkeypatch):
    monkeypatch.setattr(config, "DAILY_DRAFT_CAP", 2)
    company = add_company(conn)
    for i in range(5):
        add_posting(conn, company, str(i), "Denver, CO")
    assert bot.propose_batch(conn, FakeClient(), 10, send=Outbox(), fetch_form=lambda p: ([], [])) == 2


def test_failed_send_leaves_no_orphan_application(conn, profile):
    company = add_company(conn)
    add_posting(conn, company, "a", "Denver, CO")

    def broken_send(text, reply_markup=None):
        raise RuntimeError("telegram down")

    with pytest.raises(RuntimeError):
        bot.propose_batch(conn, FakeClient(), 5, send=broken_send, fetch_form=lambda p: ([], []))
    assert db.list_applications(conn) == []


def _tap(conn, data, outbox, monkeypatch, chat_id=42):
    monkeypatch.setattr(bot.telegram_client, "answer_callback_query", lambda *a, **k: None)
    monkeypatch.setattr(bot.telegram_client, "edit_message_buttons", lambda *a, **k: None)
    bot.handle_update(conn, {"update_id": 1, "callback_query": {
        "id": "q", "data": data, "message": {"message_id": 5, "chat": {"id": chat_id}},
    }}, send=outbox)


def test_approve_and_skip_taps_change_status(conn, profile, monkeypatch):
    company = add_company(conn)
    first = db.insert_application(conn, Application(posting_id=add_posting(conn, company, "a", "Denver, CO").id))
    second = db.insert_application(conn, Application(posting_id=add_posting(conn, company, "b", "Denver, CO").id))
    outbox = Outbox()

    _tap(conn, f"approve:{first}", outbox, monkeypatch)
    _tap(conn, f"skip:{second}", outbox, monkeypatch)
    _tap(conn, f"approve:{second}", outbox, monkeypatch)  # a second tap can't un-skip it

    assert db.get_application(conn, first).status == "approved"
    assert db.get_application(conn, second).status == "skipped"


def test_taps_from_a_stranger_are_ignored(conn, profile, monkeypatch):
    company = add_company(conn)
    app_id = db.insert_application(conn, Application(posting_id=add_posting(conn, company, "a", "Denver, CO").id))
    _tap(conn, f"approve:{app_id}", Outbox(), monkeypatch, chat_id=999)
    assert db.get_application(conn, app_id).status == "proposed"


def test_open_application_marks_submitted_when_confirmation_page_was_seen(conn, profile):
    company = add_company(conn)
    db.insert_contact(conn, Contact(company_id=company.id, name="A B", title="CTO", source_url="https://foo.example/team", fact="x"))
    app_id = db.insert_application(conn, Application(
        posting_id=add_posting(conn, company, "a", "Denver, CO").id, answers={"Why?": "Because."},
    ))
    outbox, seen = Outbox(), {}

    def fake_fill(posting, applicant, resume_path=None, extra_answers=None, wait_for_human=None):
        seen["answers"] = extra_answers
        return {"confirmation_seen": True}

    bot.open_application(conn, db.get_application(conn, app_id), send=outbox, fill=fake_fill)

    assert seen["answers"] == {"Why?": "Because."}
    assert db.get_application(conn, app_id).status == "submitted"
    text, markup = outbox.sent[0]
    assert "Recorded as submitted" in text
    assert markup["inline_keyboard"][0][0]["callback_data"] == f"referral:{app_id}"


def test_open_application_asks_when_no_confirmation_was_seen(conn, profile):
    company = add_company(conn)
    app_id = db.insert_application(conn, Application(posting_id=add_posting(conn, company, "a", "Denver, CO").id))
    outbox = Outbox()
    bot.open_application(
        conn, db.get_application(conn, app_id), send=outbox,
        fill=lambda *a, **k: {"confirmation_seen": False},
    )
    assert db.get_application(conn, app_id).status == "opened"
    assert outbox.sent[0][0].startswith("Did you submit")


def test_run_daily_runs_once_per_day(conn, profile, monkeypatch):
    monkeypatch.setattr(bot, "_anthropic_client", lambda: FakeClient())
    monkeypatch.setattr(bot, "propose_batch", lambda *a, **k: 0)
    monkeypatch.setattr(bot, "send_drafts", lambda *a, **k: 0)
    outbox = Outbox()
    assert bot.run_daily(conn, send=outbox, today=date(2026, 10, 7)) is True
    assert bot.run_daily(conn, send=outbox, today=date(2026, 10, 7)) is False
    assert bot.run_daily(conn, send=outbox, today=date(2026, 10, 8)) is True


# --- outreach drafts ("the referral side") ---------------------------------

from internship_hunter.drafting import batch  # noqa: E402
from internship_hunter.drafting.compose import DraftEmail  # noqa: E402
from internship_hunter.models import Message  # noqa: E402


@pytest.fixture
def outreach(monkeypatch):
    """No real Claude or Gmail: composing returns a fixed draft, and saving
    a draft just records where it was addressed."""
    saved = []
    monkeypatch.setattr(batch.compose, "compose_email", lambda *a, **k: DraftEmail(
        subject="15-year-old who builds drones", body="I'm 15. https://example.com/project",
    ))

    def fake_create_draft(service, subject, body, to_email=None):
        saved.append(to_email)
        return f"draft-{len(saved)}"

    monkeypatch.setattr(batch.gmail_client, "create_draft", fake_create_draft)
    return saved


def add_contact(conn, company, name, email=None) -> Contact:
    contact = Contact(company_id=company.id, name=name, title="CTO", source_url="https://foo.example/team", fact="x", email=email)
    contact.id = db.insert_contact(conn, contact)
    return contact


def test_next_contacts_only_pitches_colorado_and_virginia_one_person_per_company_first(conn):
    virginia, colorado = add_company(conn, "VA Defense", tier=2, state="VA"), add_company(conn, "CO Startup", tier=1, state="CO")
    texas = add_company(conn, "TX Startup", tier=1, state="Other")
    first = add_contact(conn, colorado, "A One", email="a@co.example")
    second = add_contact(conn, colorado, "B Two", email="b@co.example")
    third = add_contact(conn, virginia, "C Three", email="c@va.example")
    add_contact(conn, texas, "D Four", email="d@tx.example")
    add_contact(conn, colorado, "E NoEmail")   # nobody to send to: LinkedIn's job, not email's

    picked = [contact.id for _, contact in batch.next_contacts(conn, 10)]
    assert picked == [first.id, third.id, second.id]


def test_to_address_prefers_the_person_then_the_company_inbox_and_never_guesses(conn):
    company = add_company(conn)
    assert batch.to_address(company, add_contact(conn, company, "Has Email", email="p@foo.example")) == "p@foo.example"
    nobody = add_contact(conn, company, "No Email")
    assert batch.to_address(company, nobody) is None
    company.contact_email = "careers@foo.example"
    assert batch.to_address(company, nobody) == "careers@foo.example"


def test_send_drafts_announces_each_draft_with_a_sent_button(conn, profile, outreach):
    company = add_company(conn, state="CO")
    db.set_company_contact_email(conn, company.id, "careers@foo.example")
    add_contact(conn, company, "A One", email="a.one@foo.example")
    add_contact(conn, company, "B NoEmail")    # no address of their own: gets a LinkedIn card instead
    outbox = Outbox()

    assert bot.send_drafts(conn, 5, send=outbox, client=object(), service=object()) == 1

    message = db.list_messages(conn)[0]
    assert message.status == "drafted" and outreach == ["a.one@foo.example"]
    text, markup = outbox.sent[0]
    assert f"Draft #{message.id} - Cold pitch" in text and "To: a.one@foo.example" in text
    assert message.to_email == "a.one@foo.example"
    assert [row[0]["callback_data"] for row in markup["inline_keyboard"]] == [f"send:{message.id}", f"sent:{message.id}"]
    # Everyone has a draft now, so a second run makes nothing.
    assert bot.send_drafts(conn, 5, send=outbox, client=object(), service=object()) == 0


def test_sent_and_replied_taps_update_the_message(conn, profile, monkeypatch):
    company = add_company(conn)
    message_id = db.insert_message(conn, Message(company_id=company.id, channel="email", subject="s", body="b"))
    outbox = Outbox()

    _tap(conn, f"sent:{message_id}", outbox, monkeypatch)
    sent = db.get_message(conn, message_id)
    assert sent.status == "sent" and sent.sent_at

    _tap(conn, f"replied:{message_id}", outbox, monkeypatch)
    assert db.get_message(conn, message_id).status == "replied"


def test_one_follow_up_is_drafted_after_seven_days_and_never_a_second(conn, profile, outreach):
    company = add_company(conn, state="VA")
    contact = add_contact(conn, company, "A One")
    original = db.insert_message(conn, Message(
        company_id=company.id, contact_id=contact.id, channel="email", subject="first", body="b",
        status="sent", sent_at="2026-09-20 09:00:00",
    ))
    today = date(2026, 10, 7)
    assert [m.id for m in batch.due_follow_ups(conn, today)] == [original]

    created = batch.draft_batch(conn, object(), object(), 5, today=today)
    assert [d["kind"] for d in created] == ["follow-up"]

    # Mark the follow-up sent long ago too: still no third email to the same person.
    db.update_message_status(conn, created[0]["message"].id, "sent", sent_at="2026-09-21 09:00:00")
    assert batch.due_follow_ups(conn, today) == []


# --- Send button, /to, reply detection -------------------------------------

class FakeGmail:
    """Just enough of gmail_client's functions to follow one draft around."""

    def __init__(self, recipient="jane@foo.example", read_access=True, thread=("waiting", "")):
        self.recipient, self.read_access, self.thread = recipient, read_access, thread
        self.sent, self.replaced = [], []

    def install(self, monkeypatch):
        from internship_hunter.drafting import gmail_client

        monkeypatch.setattr(gmail_client, "draft_recipient", lambda service, draft_id: self.recipient)
        monkeypatch.setattr(gmail_client, "send_draft", lambda service, draft_id: self.sent.append(draft_id) or {"threadId": "t1"})
        monkeypatch.setattr(gmail_client, "replace_draft", lambda service, draft_id, s, b, to: self.replaced.append(to))
        monkeypatch.setattr(gmail_client, "has_read_access", lambda: self.read_access)
        monkeypatch.setattr(gmail_client, "thread_status", lambda service, thread_id, own: self.thread)
        monkeypatch.setattr(gmail_client, "find_sent_thread", lambda service, subject: "t-manual")
        monkeypatch.setattr(bot, "_gmail_service", lambda: object())
        return self


def add_draft(conn, company, to_email=None) -> int:
    return db.insert_message(conn, Message(
        company_id=company.id, channel="email", subject="s", body="b", gmail_draft_id="d1", to_email=to_email,
    ))


def test_send_button_sends_that_one_draft_and_starts_watching(conn, profile, monkeypatch):
    gmail = FakeGmail().install(monkeypatch)
    message_id = add_draft(conn, add_company(conn))
    outbox = Outbox()

    _tap(conn, f"send:{message_id}", outbox, monkeypatch)

    message = db.get_message(conn, message_id)
    assert gmail.sent == ["d1"]
    assert message.status == "sent" and message.gmail_thread_id == "t1" and message.to_email == "jane@foo.example"
    assert "Sent draft" in outbox.sent[0][0]
    # A second tap can't send it twice.
    _tap(conn, f"send:{message_id}", outbox, monkeypatch)
    assert gmail.sent == ["d1"]


def test_send_button_refuses_a_draft_with_no_address(conn, profile, monkeypatch):
    gmail = FakeGmail(recipient="").install(monkeypatch)
    message_id = add_draft(conn, add_company(conn))
    outbox = Outbox()
    _tap(conn, f"send:{message_id}", outbox, monkeypatch)
    assert gmail.sent == [] and db.get_message(conn, message_id).status == "drafted"
    assert f"/to {message_id}" in outbox.sent[0][0]


def test_to_command_addresses_a_draft_and_rejects_junk(conn, profile, monkeypatch):
    gmail = FakeGmail().install(monkeypatch)
    message_id = add_draft(conn, add_company(conn))
    outbox = Outbox()

    bot.handle_command(conn, f"/to {message_id} not-an-email", outbox)
    assert gmail.replaced == [] and "Usage" in outbox.sent[-1][0]

    bot.handle_command(conn, f"/to {message_id} chris@foo.example", outbox)
    assert gmail.replaced == ["chris@foo.example"]
    assert db.get_message(conn, message_id).to_email == "chris@foo.example"
    assert outbox.sent[-1][1]["inline_keyboard"][0][0]["callback_data"] == f"send:{message_id}"


def test_check_replies_records_replies_and_bounces_and_pings_him(conn, profile, monkeypatch):
    company = add_company(conn)
    message_id = add_draft(conn, company, to_email="jane@foo.example")
    db.mark_message_sent(conn, message_id, "t1")
    outbox = Outbox()

    FakeGmail(thread=("waiting", "")).install(monkeypatch)
    assert bot.check_replies(conn, outbox) == 0 and db.get_message(conn, message_id).status == "sent"

    FakeGmail(thread=("replied", "Sure, send your resume")).install(monkeypatch)
    assert bot.check_replies(conn, outbox) == 1
    assert db.get_message(conn, message_id).status == "replied"
    assert "Sure, send your resume" in outbox.sent[-1][0]

    bounced_id = add_draft(conn, company, to_email="nobody@foo.example")
    db.mark_message_sent(conn, bounced_id, "t2")
    FakeGmail(thread=("bounced", "")).install(monkeypatch)
    assert bot.check_replies(conn, outbox) == 1
    assert db.get_message(conn, bounced_id).status == "bounced"


def test_check_replies_does_nothing_without_read_access(conn, profile, monkeypatch):
    message_id = add_draft(conn, add_company(conn))
    db.mark_message_sent(conn, message_id, "t1")
    FakeGmail(read_access=False, thread=("replied", "x")).install(monkeypatch)
    assert bot.check_replies(conn, Outbox()) == 0


# --- cards: location, standing answers, the questions file ------------------

def test_card_shows_only_the_colorado_and_virginia_offices():
    location = ("Atlanta, Georgia, United States; Boston, Massachusetts, United States; "
                "Broomfield, Colorado, United States; Reston, Virginia, United States")
    shown = queue.display_location(location)
    assert shown.startswith("Broomfield, Colorado; Reston, Virginia")
    assert "2 other cities" in shown and "Atlanta" not in shown
    assert queue.display_location("Littleton, CO") == "Littleton, CO"


def test_propose_uses_his_answers_file_and_adds_what_it_cannot_answer(conn, profile):
    from internship_hunter.apply_assist import my_answers

    entries = my_answers.load()
    next(e for e in entries if e.id == "gender").answer = "Decline To Self Identify"
    my_answers.save(entries)
    company = add_company(conn)
    add_posting(conn, company, "a", "Denver, CO")
    fields = FORM_FIELDS + [("End date year*", "number"), ("School*", "select")]
    choice_questions = FORM_CHOICES + [
        {"question": "School*", "kind": "combobox", "target": "c3", "options": None},
        {"question": "Will you be returning to school after the internship?*", "kind": "select", "target": "c4",
         "options": ["Select...", "Yes", "No"]},
        {"question": "Do you have a favorite color?", "kind": "select", "target": "c5", "options": ["Red", "Blue"]},
    ]
    outbox = Outbox()

    bot.propose_batch(conn, FakeClient(), 5, send=outbox, fetch_form=lambda p: (fields, choice_questions))

    text = outbox.sent[0][0]
    assert "Gender \u2192 Decline To Self Identify" in text     # his own answer from the file
    assert "End date year* \u2192 2029" in text                 # typed standing answer
    saved = {e.question: e for e in my_answers.load()}
    assert saved["Do you have a favorite color?"].options == "Red | Blue"   # new question, asked once
    assert "School*" not in saved                                # already a starter question
    assert "1 of these are new to me" in text
