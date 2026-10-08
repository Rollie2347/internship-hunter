import base64
from email.mime.text import MIMEText
from pathlib import Path

from internship_hunter.drafting import gmail_client


def test_the_only_send_call_is_send_draft_and_only_the_send_button_reaches_it():
    # CLAUDE.md constraint 5: a human approves everything outbound. There's
    # no Gmail scope that allows drafts but blocks sending, so the real
    # enforcement is structural, checked here:
    #   1. gmail_client sends in exactly one place, send_draft, and never
    #      composes-and-sends a message directly;
    #   2. send_draft is called in exactly one place in the whole package,
    #      bot.send_approved_draft;
    #   3. send_approved_draft is called in exactly one place, the handler
    #      for the "send" button the student taps himself.
    source = Path(gmail_client.__file__).read_text(encoding="utf-8")
    assert source.count("drafts().send(") == 1
    assert "drafts().send(" in source.split("def send_draft")[1].split("\ndef ")[0]
    assert "messages().send(" not in source

    package = Path(gmail_client.__file__).resolve().parent.parent
    callers = {
        path.relative_to(package).as_posix(): path.read_text(encoding="utf-8").count("send_draft(")
        for path in package.rglob("*.py")
        if "send_draft(" in path.read_text(encoding="utf-8")
    }
    assert callers == {"drafting/gmail_client.py": 1, "approvals/bot.py": 1}

    bot_source = (package / "approvals" / "bot.py").read_text(encoding="utf-8")
    assert bot_source.count("send_approved_draft(") == 2  # its definition + the one call
    tap_handler = bot_source.split("def _handle_draft_tap")[1].split("\ndef ")[0]
    assert 'if action == "send":' in tap_handler and "send_approved_draft(" in tap_handler


def test_classify_thread_tells_replies_from_bounces_from_silence():
    me = "me@example.com"
    mine = {"from": "Me <me@example.com>", "snippet": "hi"}
    assert gmail_client.classify_thread([mine], me) == ("waiting", "")
    assert gmail_client.classify_thread([mine, {"from": "Jane <jane@foo.com>", "snippet": "Sure, call me"}], me) == ("replied", "Sure, call me")
    assert gmail_client.classify_thread(
        [mine, {"from": "Mail Delivery Subsystem <mailer-daemon@googlemail.com>", "snippet": "Address not found"}], me
    ) == ("bounced", "Address not found")


def test_granted_scopes_reads_the_cached_token(tmp_path, monkeypatch):
    token = tmp_path / "token.json"
    monkeypatch.setattr(gmail_client, "TOKEN_PATH", token)
    assert gmail_client.granted_scopes() == set() and not gmail_client.has_read_access()
    token.write_text('{"scopes": ["%s"]}' % gmail_client.COMPOSE_SCOPE, encoding="utf-8")
    assert not gmail_client.has_read_access()
    token.write_text('{"scopes": ["%s", "%s"]}' % (gmail_client.COMPOSE_SCOPE, gmail_client.READ_SCOPE), encoding="utf-8")
    assert gmail_client.has_read_access()


def test_build_raw_message_includes_subject_and_to():
    raw = gmail_client.build_raw_message("Hello", "Body text", to_email="jane@foo.com")
    decoded = base64.urlsafe_b64decode(raw).decode("utf-8")
    assert "Subject: Hello" in decoded
    assert "jane@foo.com" in decoded
    assert "Body text" in decoded


def test_build_raw_message_omits_to_when_none():
    raw = gmail_client.build_raw_message("Hello", "Body text", to_email=None)
    decoded = base64.urlsafe_b64decode(raw).decode("utf-8")
    assert "To:" not in decoded


class FakeDraftsResource:
    def __init__(self):
        self.created_with = None

    def create(self, userId, body):
        self.created_with = (userId, body)
        return self

    def execute(self):
        return {"id": "draft-123"}


class FakeUsersResource:
    def __init__(self):
        self.drafts_resource = FakeDraftsResource()

    def drafts(self):
        return self.drafts_resource


class FakeGmailService:
    def __init__(self):
        self.users_resource = FakeUsersResource()

    def users(self):
        return self.users_resource


def test_create_draft_calls_drafts_create_and_returns_id():
    service = FakeGmailService()
    draft_id = gmail_client.create_draft(service, "Subject", "Body", to_email="jane@foo.com")
    assert draft_id == "draft-123"
    user_id, body = service.users_resource.drafts_resource.created_with
    assert user_id == "me"
    assert "raw" in body["message"]
