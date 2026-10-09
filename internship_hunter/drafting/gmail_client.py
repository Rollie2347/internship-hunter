"""Gmail API wrapper: creates drafts, sends ONE draft when the student taps
Send on it, and (if he has granted read access) checks whether a sent
email got a reply.

CLAUDE.md constraint 5 -- a human approves everything outbound -- is kept
like this: the only code that sends mail is the send_draft function below, it sends
exactly one existing draft by id, and its only caller is the Telegram
"Send" button handler in approvals/bot.py, which runs when the student
himself taps that button under the full text of that draft. Nothing sends
on a timer or in a loop. tests/test_gmail_client.py fails the suite if a
second send call ever appears in this file or if anything else calls it.

Scopes:
  gmail.compose  -- create/update/send drafts (required)
  gmail.readonly -- read threads, only used to notice replies (optional;
                    granted by running `python -m internship_hunter.drafting.cli auth`)
"""

from __future__ import annotations

import base64
import json
from email.mime.text import MIMEText
from email.utils import parseaddr
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from internship_hunter import config

COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
READ_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
SCOPES = [COMPOSE_SCOPE]
ALL_SCOPES = [COMPOSE_SCOPE, READ_SCOPE]
TOKEN_PATH = config.PROJECT_ROOT / "token.json"  # gitignored -- cached OAuth token


def granted_scopes() -> set[str]:
    """Scopes the cached token actually carries (empty if there's no token)."""
    if not TOKEN_PATH.exists():
        return set()
    try:
        scopes = json.loads(TOKEN_PATH.read_text(encoding="utf-8")).get("scopes") or []
    except ValueError:
        return set()
    return set(scopes.split() if isinstance(scopes, str) else scopes)


def has_read_access() -> bool:
    return READ_SCOPE in granted_scopes()


def run_consent_flow(scopes: list[str]) -> Credentials:
    """Open the browser for Google's consent screen and cache the result.
    Authenticates as whichever account approves it -- that should be
    GMAIL_DRAFT_ACCOUNT."""
    if not config.GOOGLE_OAUTH_CLIENT_SECRET_PATH:
        raise RuntimeError(
            "GOOGLE_OAUTH_CLIENT_SECRET_PATH is not set in .env -- download a Desktop app "
            "OAuth client from Google Cloud Console and point .env at the credentials.json file."
        )
    flow = InstalledAppFlow.from_client_secrets_file(config.GOOGLE_OAUTH_CLIENT_SECRET_PATH, scopes)
    creds = flow.run_local_server(port=0)
    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    return creds


def get_credentials() -> Credentials:
    """Load the cached token with whatever scopes it was granted, refreshing
    it if expired; run the consent flow only if there is no usable token.
    Never silently asks for MORE access than the token already has -- read
    access is only ever added by the explicit `auth` command."""
    creds: Optional[Credentials] = None
    scopes = sorted(granted_scopes()) or SCOPES
    if TOKEN_PATH.exists() and COMPOSE_SCOPE in scopes:
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), scopes)

    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        return creds
    return run_consent_flow(SCOPES)


def get_service():
    return build("gmail", "v1", credentials=get_credentials())


def build_raw_message(subject: str, body: str, to_email: Optional[str] = None) -> str:
    message = MIMEText(body)
    message["Subject"] = subject
    if to_email:
        message["To"] = to_email
    return base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")


def create_draft(service, subject: str, body: str, to_email: Optional[str] = None) -> str:
    """Create a Gmail draft and return its draft id. Sends nothing."""
    raw = build_raw_message(subject, body, to_email)
    draft = service.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
    return draft["id"]


def replace_draft(service, draft_id: str, subject: str, body: str, to_email: Optional[str] = None) -> None:
    """Rewrite an existing draft in place (used to add a "To" address).
    Sends nothing."""
    raw = build_raw_message(subject, body, to_email)
    service.users().drafts().update(userId="me", id=draft_id, body={"message": {"raw": raw}}).execute()


def draft_recipient(service, draft_id: str) -> str:
    """The "To" address currently on a draft in Gmail -- which may differ
    from what we created if he edited the draft there. '' if none."""
    # drafts.get takes no metadataHeaders argument (messages.get does) -- passing
    # one raised a TypeError that made Send now refuse every draft. Found live
    # on 2026-10-08; the tests had only ever faked this function.
    draft = service.users().drafts().get(userId="me", id=draft_id, format="metadata").execute()
    headers = draft.get("message", {}).get("payload", {}).get("headers", [])
    return next((parseaddr(h["value"])[1] for h in headers if h["name"].lower() == "to"), "")


def send_draft(service, draft_id: str) -> dict:
    """Send ONE existing draft, exactly as it currently stands in Gmail
    (including any edits he made there). Returns {"id", "threadId"}.
    Only ever called from the Telegram Send button -- see the module docstring."""
    sent = service.users().drafts().send(userId="me", body={"id": draft_id}).execute()
    return {"id": sent.get("id"), "threadId": sent.get("threadId")}


# --- Noticing replies (needs read access) ------------------------------------

BOUNCE_SENDERS = ("mailer-daemon", "postmaster")


def classify_thread(messages: list[dict], own_address: str) -> tuple[str, str]:
    """Given a thread's messages (each {"from": ..., "snippet": ...}),
    return ("replied" | "bounced" | "waiting", snippet of the message that
    decided it). Anything from someone other than the student counts as a
    reply, except a delivery-failure notice, which is a bounce."""
    own = (own_address or "").lower()
    for message in messages:
        sender = parseaddr(message.get("from", ""))[1].lower()
        if not sender or sender == own:
            continue
        if any(sender.startswith(prefix) for prefix in BOUNCE_SENDERS):
            return "bounced", message.get("snippet", "")
        return "replied", message.get("snippet", "")
    return "waiting", ""


def thread_status(service, thread_id: str, own_address: str) -> tuple[str, str]:
    thread = service.users().threads().get(
        userId="me", id=thread_id, format="metadata", metadataHeaders=["From"]
    ).execute()
    messages = []
    for message in thread.get("messages", []):
        headers = message.get("payload", {}).get("headers", [])
        sender = next((h["value"] for h in headers if h["name"].lower() == "from"), "")
        messages.append({"from": sender, "snippet": message.get("snippet", "")})
    return classify_thread(messages, own_address)


def find_sent_thread(service, subject: str) -> Optional[str]:
    """Thread id of an email he sent from Gmail himself, looked up by its
    exact subject. None if it isn't in Sent."""
    safe_subject = subject.replace('"', " ")
    found = service.users().messages().list(userId="me", q=f'in:sent subject:"{safe_subject}"', maxResults=1).execute()
    messages = found.get("messages", [])
    return messages[0]["threadId"] if messages else None
