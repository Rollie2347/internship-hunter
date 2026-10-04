"""Gmail API wrapper -- creates drafts ONLY. CLAUDE.md constraint 5 is a
hard rule: this module must never call a send endpoint. There is no Gmail
scope that permits drafts but blocks sending, so the enforcement here is
architectural (this file never calls a send method on drafts or messages)
plus a regression test (tests/test_gmail_client.py) that greps this file's
source for the send call pattern and fails the suite if it ever appears.

Scope used: gmail.compose (create/read/update/delete drafts). The narrower
gmail.send scope would be wrong here -- it can't create drafts at all, only
send already-composed messages directly.
"""

from __future__ import annotations

import base64
from email.mime.text import MIMEText
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from internship_hunter import config

SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]
TOKEN_PATH = config.PROJECT_ROOT / "token.json"  # gitignored -- cached OAuth token


def get_credentials() -> Credentials:
    """Load a cached token, refreshing it if expired; otherwise run the
    interactive OAuth consent flow (opens a browser) once and cache the
    result. Authenticates as whichever Google account approves the
    consent screen -- that should be GMAIL_DRAFT_ACCOUNT."""
    creds: Optional[Credentials] = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not config.GOOGLE_OAUTH_CLIENT_SECRET_PATH:
            raise RuntimeError(
                "GOOGLE_OAUTH_CLIENT_SECRET_PATH is not set in .env -- download a Desktop app "
                "OAuth client from Google Cloud Console and point .env at the credentials.json file."
            )
        flow = InstalledAppFlow.from_client_secrets_file(config.GOOGLE_OAUTH_CLIENT_SECRET_PATH, SCOPES)
        creds = flow.run_local_server(port=0)

    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    return creds


def get_service():
    return build("gmail", "v1", credentials=get_credentials())


def build_raw_message(subject: str, body: str, to_email: Optional[str] = None) -> str:
    message = MIMEText(body)
    message["Subject"] = subject
    if to_email:
        message["To"] = to_email
    return base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")


def create_draft(service, subject: str, body: str, to_email: Optional[str] = None) -> str:
    """Create a Gmail draft and return its draft id. Never sends anything --
    this calls drafts().create() only."""
    raw = build_raw_message(subject, body, to_email)
    draft = service.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
    return draft["id"]
