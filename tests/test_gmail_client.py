import base64
from email.mime.text import MIMEText
from pathlib import Path

from internship_hunter.drafting import gmail_client


def test_source_never_calls_a_send_endpoint():
    # CLAUDE.md constraint 5: this module must never send mail, only draft
    # it. There's no Gmail scope that allows drafts but blocks sending, so
    # the only real enforcement is "the code never calls it" -- this test
    # makes that a hard failure if it ever creeps in, instead of relying on
    # someone remembering the rule during a future edit.
    source = Path(gmail_client.__file__).read_text(encoding="utf-8")
    assert "drafts().send(" not in source
    assert "messages().send(" not in source


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
