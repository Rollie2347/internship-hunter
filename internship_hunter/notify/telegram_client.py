"""Thin wrapper around the Telegram Bot API, used only to push status
updates TO the student (new postings, follow-up reminders, the weekly
"other routes" digest). This never contacts companies or anyone else --
that stays on Gmail drafts (see drafting/gmail_client.py, Phase 4).

Telegram's Bot HTTP API doesn't need a library: it's plain JSON over HTTPS,
so `requests` is all we need.
"""

from __future__ import annotations

import requests

from internship_hunter import config

API_BASE = "https://api.telegram.org"


class TelegramNotConfigured(RuntimeError):
    """Raised when TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing from .env."""


def _require_token() -> str:
    if not config.TELEGRAM_BOT_TOKEN:
        raise TelegramNotConfigured(
            "TELEGRAM_BOT_TOKEN is not set in .env. Create a bot with @BotFather "
            "on Telegram and paste the token it gives you into .env."
        )
    return config.TELEGRAM_BOT_TOKEN


def fetch_latest_chat_id(bot_token: str | None = None) -> int:
    """Call getUpdates and return the chat_id of the most recent message sent
    TO the bot. The student must send the bot at least one message first
    (e.g. "hi") -- Telegram bots can't message a user who hasn't started a
    chat with them."""
    token = bot_token or _require_token()
    response = requests.get(f"{API_BASE}/bot{token}/getUpdates", timeout=10)
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram getUpdates failed: {payload}")
    results = payload.get("result", [])
    if not results:
        raise RuntimeError(
            "No messages found. Open your bot in Telegram and send it any "
            "message (e.g. 'hi'), then try again."
        )
    latest = results[-1]
    message = latest.get("message") or latest.get("channel_post")
    if not message:
        raise RuntimeError(f"Unexpected Telegram update shape: {latest}")
    return message["chat"]["id"]


def send_message(text: str, chat_id: str | int | None = None, bot_token: str | None = None) -> dict:
    """Send a plain-text message to the student's Telegram chat. Returns the
    parsed JSON response from Telegram."""
    token = bot_token or _require_token()
    target_chat_id = chat_id or config.TELEGRAM_CHAT_ID
    if not target_chat_id:
        raise TelegramNotConfigured(
            "TELEGRAM_CHAT_ID is not set in .env. Run "
            "'python -m internship_hunter.notify.cli fetch-chat-id' first."
        )
    response = requests.post(
        f"{API_BASE}/bot{token}/sendMessage",
        json={"chat_id": target_chat_id, "text": text},
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram sendMessage failed: {payload}")
    return payload
