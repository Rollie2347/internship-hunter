from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from internship_hunter import config, db
from internship_hunter.approvals import bot, queue
from internship_hunter.drafting import batch, daily_cap
from internship_hunter.linkedin_assist import assist as linkedin
from internship_hunter.models import Company, Contact, Message


@pytest.fixture
def conn(tmp_path):
    connection = db.get_connection(tmp_path / "test_tracker.db")
    db.init_db(connection)
    yield connection
    connection.close()


@pytest.fixture
def profile(tmp_path, monkeypatch):
    about = tmp_path / "about_me.md"
    about.write_text("**Name:** Test Student\nProjects: Argus - https://example.com/argus\n", encoding="utf-8")
    monkeypatch.setattr(config, "ABOUT_ME_PATH", about)
    monkeypatch.setattr(config, "RESUME_PATH_TXT", tmp_path / "missing.txt")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "42")


def add_company(conn, name="Foo Robotics", tier=1, state="CO") -> Company:
    company = Company(
        name=name, website="https://foo.example", state=state, city="X", stage="seed",
        what_they_build="drone autonomy software", why_fit="x", careers_url="https://foo.example", priority_tier=tier,
    )
    company.id = db.insert_company(conn, company)
    return company


def add_contact(conn, company, name="Jane Doe", **overrides) -> Contact:
    fields = dict(
        company_id=company.id, name=name, title="CTO", source_url="https://podcast.example/ep-12",
        fact="Spoke about swarm autonomy on the Hard Tech podcast.",
    )
    fields.update(overrides)
    contact = Contact(**fields)
    contact.id = db.insert_contact(conn, contact)
    return contact


GOOD_NOTE = ("I'm 15, in high school. Your Hard Tech episode on swarm autonomy is why I'm writing. "
             "I built Argus, a real-time voice AI app. Could I ask you a question about your work?")


class FakeClient:
    """Stands in for the Anthropic client; hands back the notes it was given, in order."""

    def __init__(self, *notes):
        self.notes = list(notes) or [GOOD_NOTE]
        self.calls = []
        self.messages = self

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        note = self.notes.pop(0) if len(self.notes) > 1 else self.notes[0]
        return SimpleNamespace(parsed_output=linkedin.DraftNote(note=note))


class FakeMessageClient:
    """For the longer notes (outreach/paste.py)."""

    def __init__(self, text="For Jane Doe: I'm 15 and built Argus (https://example.com/argus). Could we talk for 15 minutes?"):
        self.text, self.calls = text, []
        self.messages = self

    def parse(self, **kwargs):
        from internship_hunter.outreach import paste

        self.calls.append(kwargs)
        return SimpleNamespace(parsed_output=paste.DraftMessage(message=self.text))


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


# --- no automation ---------------------------------------------------------

def test_the_linkedin_module_cannot_make_a_web_request():
    # CLAUDE.md constraint 4: never automate LinkedIn. This module builds
    # links as text and nothing else, so it must not even import an HTTP
    # library or a browser.
    source = Path(linkedin.__file__).read_text(encoding="utf-8")
    for forbidden in ("import requests", "urllib.request", "httpx", "playwright", "selenium", "webbrowser"):
        assert forbidden not in source


def test_search_url_is_a_people_search_for_name_and_company():
    url = linkedin.search_url("Jane O'Doe", "Foo Robotics")
    assert url == "https://www.linkedin.com/search/results/people/?keywords=Jane+O%27Doe+Foo+Robotics"


@pytest.mark.parametrize("text,expected", [
    ("https://www.linkedin.com/in/jane-doe-123/", "https://www.linkedin.com/in/jane-doe-123"),
    ("linkedin.com/in/jane-doe?utm_source=share", "https://www.linkedin.com/in/jane-doe"),
    ("https://www.linkedin.com/company/foo", None),       # a company page, not a person
    ("https://evil.example/in/jane-doe", None),
    ("https://notlinkedin.com/in/jane-doe", None),
    ("jane doe", None),
])
def test_clean_profile_url(text, expected):
    assert linkedin.clean_profile_url(text) == expected


# --- drafting --------------------------------------------------------------

def test_draft_note_gives_the_model_only_the_stored_fact_and_the_character_limit(conn, profile):
    company = add_company(conn)
    contact = add_contact(conn, company)
    client = FakeClient()

    note = linkedin.draft_note(client, "PROFILE", "RESUME", company, contact)

    assert note == GOOD_NOTE and len(note) < 200 and linkedin.validate_note(note) == []
    call = client.calls[0]
    assert "under 200 characters" in call["system"] and "15" in call["system"]
    assert "looking for an internship so he can LEARN" in call["system"]   # he asked for this
    assert "Spoke about swarm autonomy" in call["messages"][0]["content"]
    assert "PROFILE" in call["messages"][0]["content"]


def test_a_note_that_is_too_long_gets_one_retry_and_is_never_cut_short(conn, profile):
    company = add_company(conn)
    contact = add_contact(conn, company)
    client = FakeClient("I'm 15. " + "x" * 320, GOOD_NOTE)
    assert linkedin.draft_note(client, "P", "R", company, contact) == GOOD_NOTE
    assert len(client.calls) == 2 and "328 characters" in client.calls[1]["messages"][-1]["content"]

    stubborn = FakeClient("I'm 15. " + "x" * 320)
    note = linkedin.draft_note(stubborn, "P", "R", company, contact)
    assert len(note) == 328 and len(stubborn.calls) == 2
    assert "trim it" in linkedin.validate_note(note)[0]


def test_validate_note_flags_a_note_that_hides_his_age():
    assert "15" in linkedin.validate_note("Hi Jane, I'm a student who builds drones.")[0]


# --- who gets a card -------------------------------------------------------

def test_next_contacts_is_colorado_virginia_only_and_skips_anyone_already_contacted(conn):
    company = add_company(conn)
    fresh = add_contact(conn, company, "A Fresh")
    has_email = add_contact(conn, company, "B Email", email="b@foo.example")
    emailed = add_contact(conn, company, "C Emailed")
    blank_draft = add_contact(conn, company, "D Blank")
    carded = add_contact(conn, company, "E Carded")
    add_contact(conn, add_company(conn, "TX Startup", state="Other"), "F Texas")
    add_contact(conn, add_company(conn, "A Lab", tier=4, state="VA"), "G Government")
    db.insert_message(conn, Message(company_id=company.id, contact_id=emailed.id, channel="email", subject="s", body="b", status="sent"))
    db.insert_message(conn, Message(company_id=company.id, contact_id=blank_draft.id, channel="email", subject="s", body="b"))
    db.insert_message(conn, Message(company_id=company.id, contact_id=carded.id, channel="linkedin", subject="s", body="b", status="skipped"))

    picked = [contact.id for _, contact in linkedin.next_contacts(conn, 10)]

    # Someone with a published email is emailed instead; a blank-address draft doesn't block a card.
    assert has_email.id not in picked
    assert picked == [fresh.id, blank_draft.id]


def test_someone_with_a_linkedin_card_is_not_also_cold_emailed_unless_not_found(conn):
    company = add_company(conn)
    carded, missing = add_contact(conn, company, "A Carded"), add_contact(conn, company, "B Missing")
    db.insert_message(conn, Message(company_id=company.id, contact_id=carded.id, channel="linkedin", subject="s", body="b", status="sent"))
    db.insert_message(conn, Message(company_id=company.id, contact_id=missing.id, channel="linkedin", subject="s", body="b", status="not_found"))
    # Not found, and the company publishes no inbox: there is no address to email either.
    assert batch.next_contacts(conn, 10) == []
    db.set_company_contact_email(conn, company.id, "careers@foo.example")
    assert [contact.id for _, contact in batch.next_contacts(conn, 10)] == [missing.id]


# --- cards, the cap, taps --------------------------------------------------

def test_card_shows_the_person_why_the_link_the_note_and_three_buttons(conn, profile):
    company = add_company(conn)
    contact = add_contact(conn, company)
    outbox = Outbox()

    assert bot.send_linkedin_cards(conn, 5, send=outbox, client=FakeClient()) == 1

    message = db.list_messages(conn)[0]
    assert (message.channel, message.status, message.body, message.contact_id) == ("linkedin", "drafted", GOOD_NOTE, contact.id)
    text = outbox.sent[0][0]
    assert f"LinkedIn #{message.id}" in text and "Jane Doe" in text and "CTO, Foo Robotics" in text
    assert "Why them: Spoke about swarm autonomy" in text and "https://podcast.example/ep-12" in text
    assert linkedin.search_url("Jane Doe", "Foo Robotics") in text
    assert "send the request yourself" in text
    # The note is a message of its own -- nothing but the note -- so one press-and-hold copies it.
    note_text, markup = outbox.sent[1]
    assert note_text == GOOD_NOTE and GOOD_NOTE not in text
    rows = markup["inline_keyboard"]
    # First button: a plain link he taps to open the search. Then the three taps the bot hears.
    assert rows[0] == [{"text": "\U0001F50E Find Jane Doe on LinkedIn", "url": linkedin.search_url("Jane Doe", "Foo Robotics")}]
    assert [b["callback_data"] for row in rows[1:] for b in row] == [
        f"li_sent:{message.id}", f"li_skip:{message.id}", f"li_nf:{message.id}",
    ]
    # Everyone has a card now, so a second run makes nothing.
    assert bot.send_linkedin_cards(conn, 5, send=outbox, client=FakeClient()) == 0


def test_the_linkedin_cap_is_ten_a_day_and_separate_from_the_email_cap(conn, profile, monkeypatch):
    company = add_company(conn)
    for i in range(13):
        add_contact(conn, company, f"Person{i:02d} Last{i:02d}")
    before = daily_cap.remaining_today(conn)
    outbox, client = Outbox(), FakeClient()

    assert bot.send_linkedin_cards(conn, 50, send=outbox, client=client) == 10
    assert linkedin.remaining_today(conn) == 0
    assert bot.send_linkedin_cards(conn, 50, send=outbox, client=client) == 0
    assert len(client.calls) == 10                       # nothing drafted past the cap
    assert daily_cap.remaining_today(conn) == before     # the email/application budget is untouched
    with pytest.raises(RuntimeError):
        linkedin.new_card(conn, company, db.list_contacts(conn)[0], "note")

    # An exhausted email budget doesn't stop LinkedIn cards either.
    monkeypatch.setattr(config, "DAILY_DRAFT_CAP", 0)
    monkeypatch.setattr(config, "LINKEDIN_DAILY_CAP", 11)
    assert bot.send_linkedin_cards(conn, 50, send=outbox, client=client) == 1


def test_a_card_that_never_reached_him_leaves_no_row(conn, profile):
    add_contact(conn, add_company(conn))

    def broken_send(text, reply_markup=None):
        raise RuntimeError("telegram down")

    with pytest.raises(RuntimeError):
        bot.send_linkedin_cards(conn, 5, send=broken_send, client=FakeClient())
    assert db.list_messages(conn) == []


def card(conn, company=None, contact=None, **overrides) -> int:
    company = company or add_company(conn)
    contact = contact or add_contact(conn, company)
    fields = dict(company_id=company.id, contact_id=contact.id, channel="linkedin", subject="s", body=GOOD_NOTE)
    fields.update(overrides)
    return db.insert_message(conn, Message(**fields))


def test_sent_skip_and_not_found_taps_are_logged_in_the_tracker(conn, profile, monkeypatch):
    company = add_company(conn)
    sent, skipped, missing = (card(conn, company, add_contact(conn, company, n)) for n in ("A One", "B Two", "C Three"))
    outbox = Outbox()
    monkeypatch.setattr(bot, "_anthropic_client", lambda: FakeMessageClient())

    _tap(conn, f"li_sent:{sent}", outbox, monkeypatch)
    _tap(conn, f"li_skip:{skipped}", outbox, monkeypatch)
    _tap(conn, f"li_nf:{missing}", outbox, monkeypatch)
    _tap(conn, f"li_sent:{skipped}", outbox, monkeypatch)   # a second tap can't un-skip it

    logged = db.get_message(conn, sent)
    assert (logged.channel, logged.status) == ("linkedin", "sent") and logged.sent_at
    assert db.get_message(conn, skipped).status == "skipped"
    assert db.get_message(conn, missing).status == "not_found"


def test_a_linkedin_button_cannot_touch_an_email_draft(conn, profile, monkeypatch):
    company = add_company(conn)
    email_id = db.insert_message(conn, Message(company_id=company.id, channel="email", subject="s", body="b"))
    _tap(conn, f"li_sent:{email_id}", Outbox(), monkeypatch)
    assert db.get_message(conn, email_id).status == "drafted"


def test_replied_drafts_a_follow_up_to_paste_using_the_real_availability_fact(conn, profile, monkeypatch):
    company = add_company(conn)
    message_id = card(conn, company, add_contact(conn, company), status="sent", sent_at="2026-10-01 09:00:00")
    client = FakeClient("Thanks for connecting. I'm 15 and looking for a year-long software internship. https://example.com/argus")
    monkeypatch.setattr(bot, "_anthropic_client", lambda: client)
    outbox = Outbox()

    _tap(conn, f"li_replied:{message_id}", outbox, monkeypatch)

    assert db.get_message(conn, message_id).status == "replied"
    assert "paste it into the LinkedIn chat yourself" in outbox.sent[0][0] and "Thanks for connecting" in outbox.sent[0][0]
    # ...and asks how it went: call booked / referred / went nowhere.
    assert [b["callback_data"] for row in outbox.sent[0][1]["inline_keyboard"] for b in row] == [
        f"st_call:{message_id}", f"st_ref:{message_id}", f"st_no:{message_id}",
    ]
    assert config.availability_statement() in client.calls[0]["messages"][0]["content"]
    follow_up = [m for m in db.list_messages(conn) if m.channel == "linkedin_reply"]
    assert len(follow_up) == 1 and follow_up[0].contact_id
    assert linkedin.cards_today(conn) == 1     # the follow-up doesn't use up a card
    # Tapping Replied again drafts nothing more.
    _tap(conn, f"li_replied:{message_id}", outbox, monkeypatch)
    assert len(client.calls) == 1


# --- the one reminder ------------------------------------------------------

def test_one_reminder_after_seven_days_and_never_an_email_follow_up(conn, profile):
    company = add_company(conn)
    old = card(conn, company, add_contact(conn, company, "A Old"), status="sent", sent_at="2026-09-28 09:00:00")
    card(conn, company, add_contact(conn, company, "B Recent"), status="sent", sent_at="2026-10-05 09:00:00")
    card(conn, company, add_contact(conn, company, "C Replied"), status="replied", sent_at="2026-09-01 09:00:00")
    today, outbox = date(2026, 10, 8), Outbox()

    assert bot.send_linkedin_reminders(conn, outbox, today) == 1
    text, markup = outbox.sent[0]
    assert f"LinkedIn #{old}" in text and "A Old at Foo Robotics" in text
    assert markup["inline_keyboard"][0][0]["callback_data"] == f"li_replied:{old}"
    assert db.get_message(conn, old).reminded_at

    assert bot.send_linkedin_reminders(conn, outbox, today) == 0     # once only
    assert batch.due_follow_ups(conn, today) == []                   # and no email gets drafted for it


# --- /li -------------------------------------------------------------------

def test_parse_li_command_keeps_a_title_with_a_comma_and_an_optional_fact():
    person = linkedin.parse_li_command(
        "/li https://www.linkedin.com/in/jane-doe/ Jane Doe, VP, Engineering, Foo Robotics\nWrote their autonomy blog post"
    )
    assert (person.name, person.title, person.company) == ("Jane Doe", "VP, Engineering", "Foo Robotics")
    assert person.profile_url == "https://www.linkedin.com/in/jane-doe" and person.fact == "Wrote their autonomy blog post"


@pytest.mark.parametrize("text", [
    "/li",
    "/li Jane Doe, CTO, Foo Robotics",                               # no link
    "/li https://example.com/in/jane Jane Doe, CTO, Foo Robotics",    # not LinkedIn
    "/li https://www.linkedin.com/in/jane Jane Doe, Foo Robotics",    # no title
])
def test_parse_li_command_rejects_what_does_not_fit(text):
    assert linkedin.parse_li_command(text) is None


def test_li_adds_the_person_and_sends_a_card_with_their_own_link(conn, profile):
    company = add_company(conn)
    outbox, client = Outbox(), FakeClient()

    bot.add_linkedin_person(
        conn, "/li https://www.linkedin.com/in/sam-roe Sam Roe, Staff Engineer, foo robotics\nWrote the autonomy blog post",
        outbox, client,
    )

    contact = db.list_contacts(conn, company_id=company.id)[0]
    assert (contact.name, contact.title, contact.source_kind) == ("Sam Roe", "Staff Engineer", "manual")
    assert contact.linkedin_url == contact.source_url == "https://www.linkedin.com/in/sam-roe"
    text = outbox.sent[0][0]
    assert "https://www.linkedin.com/in/sam-roe" in text and "search/results" not in text
    assert "Wrote the autonomy blog post" in client.calls[0]["messages"][0]["content"]
    assert db.list_messages(conn)[0].channel == "linkedin"

    # Pasting the same person again doesn't duplicate them or their card.
    bot.add_linkedin_person(conn, "/li https://www.linkedin.com/in/sam-roe Sam Roe, Staff Engineer, Foo Robotics", outbox, client)
    assert len(db.list_contacts(conn)) == 1 and len(db.list_messages(conn)) == 1
    assert "already have a LinkedIn card" in outbox.sent[-1][0]


def test_li_without_a_fact_tells_the_model_there_is_none(conn, profile):
    add_company(conn)
    client = FakeClient()
    bot.add_linkedin_person(conn, "/li https://www.linkedin.com/in/sam-roe Sam Roe, Engineer, Foo Robotics", Outbox(), client)
    assert "none on file" in client.calls[0]["messages"][0]["content"]


def test_li_for_an_unknown_company_suggests_close_names_and_stores_nothing(conn, profile):
    add_company(conn)
    outbox = Outbox()
    bot.add_linkedin_person(conn, "/li https://www.linkedin.com/in/sam-roe Sam Roe, Engineer, Foo Robotic", outbox, FakeClient())
    assert "Did you mean: Foo Robotics" in outbox.sent[0][0] and db.list_contacts(conn) == []


def test_li_past_the_cap_still_adds_the_person_and_defers_the_card(conn, profile, monkeypatch):
    add_company(conn)
    monkeypatch.setattr(config, "LINKEDIN_DAILY_CAP", 0)
    outbox, client = Outbox(), FakeClient()
    bot.add_linkedin_person(conn, "/li https://www.linkedin.com/in/sam-roe Sam Roe, Engineer, Foo Robotics", outbox, client)
    assert len(db.list_contacts(conn)) == 1 and db.list_messages(conn) == [] and client.calls == []
    assert "tomorrow" in outbox.sent[0][0]


def test_li_command_with_junk_shows_usage(conn, profile):
    outbox = Outbox()
    bot.handle_command(conn, "/li hello", outbox)
    assert outbox.sent[0][0] == linkedin.LI_USAGE


# --- status ----------------------------------------------------------------

def test_status_reports_linkedin_separately_from_email(conn, profile):
    company = add_company(conn)
    card(conn, company, add_contact(conn, company, "A One"), status="sent", sent_at="2026-10-07 09:00:00")
    card(conn, company, add_contact(conn, company, "B Two"))
    text = queue.build_status_text(conn)
    assert "People contacted: 1 \u2192 replied: 0 \u2192 calls: 0 \u2192 referrals: 0" in text
    assert "Today: 2 of 5 sent to you." in text
    assert "0 email draft(s) to send, 1 LinkedIn card(s)/note(s) to act on" in text
    assert "0 email(s), 1 LinkedIn request(s)/note(s) with no answer yet" in text


@pytest.mark.parametrize("data,expected", [
    ("li_sent:4", ("li_sent", 4)), ("li_skip:4", ("li_skip", 4)),
    ("li_nf:4", ("li_nf", 4)), ("li_replied:4", ("li_replied", 4)), ("li_connect:4", None),
])
def test_linkedin_callbacks_parse(data, expected):
    assert queue.parse_callback(data) == expected
