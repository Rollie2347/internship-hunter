"""Thin wrapper around the Telegram Bot API, used only to push status
updates TO the student (new postings, follow-up reminders, the weekly
"other routes" digest). This never contacts companies or anyone else --
that stays on Gmail drafts (see drafting/gmail_client.py, Phase 4).

Telegram's Bot HTTP API doesn't need a library: it's plain JSON over HTTPS,
so `requests` is all we need.
"""

from __future__ import annotations

import time

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


MAX_MESSAGE_CHARS = 4096  # Telegram rejects anything longer outright
SEND_ATTEMPTS = 3
RETRY_PAUSE_SECONDS = 2


def inline_keyboard(rows: list[list[tuple[str, str]]]) -> dict:
    """Build the tappable buttons under a message. Each button is
    (label, callback_data); Telegram sends callback_data back to the bot
    when it's tapped (see get_updates). A button whose data is a web
    address is a link button instead: tapping it opens that page on his
    phone and tells the bot nothing."""
    def button(label: str, data: str) -> dict:
        if data.startswith(("https://", "http://")):
            return {"text": label, "url": data}
        return {"text": label, "callback_data": data}

    return {"inline_keyboard": [[button(label, data) for label, data in row] for row in rows]}


def _post(method: str, payload: dict, bot_token: str | None = None, timeout: int = 10) -> dict:
    token = bot_token or _require_token()
    response = requests.post(f"{API_BASE}/bot{token}/{method}", json=payload, timeout=timeout)
    response.raise_for_status()
    body = response.json()
    if not body.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {body}")
    return body


def get_updates(offset: int | None = None, timeout: int = 25, bot_token: str | None = None) -> list[dict]:
    """Long-poll for new messages and button taps. Telegram holds the
    request open for up to `timeout` seconds and answers the moment
    something arrives, so the bot reacts instantly without hammering the
    API. Pass offset = last update_id + 1 to acknowledge what's been handled."""
    payload: dict = {"timeout": timeout, "allowed_updates": ["message", "callback_query"]}
    if offset is not None:
        payload["offset"] = offset
    return _post("getUpdates", payload, bot_token, timeout=timeout + 10)["result"]


def answer_callback_query(callback_query_id: str, text: str = "", bot_token: str | None = None) -> None:
    """Acknowledge a button tap (stops the button's loading spinner)."""
    _post("answerCallbackQuery", {"callback_query_id": callback_query_id, "text": text}, bot_token)


def edit_message_buttons(message_id: int, reply_markup: dict | None, chat_id: str | int | None = None, bot_token: str | None = None) -> None:
    """Swap (or, with None, remove) the buttons under a message already sent,
    so a card that's been decided can't be tapped a second time."""
    _post(
        "editMessageReplyMarkup",
        {
            "chat_id": chat_id or config.TELEGRAM_CHAT_ID,
            "message_id": message_id,
            "reply_markup": reply_markup or {"inline_keyboard": []},
        },
        bot_token,
    )


def send_message(
    text: str,
    chat_id: str | int | None = None,
    bot_token: str | None = None,
    reply_markup: dict | None = None,
) -> dict:
    """Send a plain-text message to the student's Telegram chat. Returns the
    parsed JSON response from Telegram."""
    token = bot_token or _require_token()
    target_chat_id = chat_id or config.TELEGRAM_CHAT_ID
    if not target_chat_id:
        raise TelegramNotConfigured(
            "TELEGRAM_CHAT_ID is not set in .env. Run "
            "'python -m internship_hunter.notify.cli fetch-chat-id' first."
        )
    payload: dict = {"chat_id": target_chat_id, "text": text[:MAX_MESSAGE_CHARS], "disable_web_page_preview": True}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    # A dropped connection ("forcibly closed by the remote host", seen live
    # twice on 2026-10-08) means the message never left, so it's safe to try
    # again. A timeout is NOT retried: Telegram may have delivered it, and a
    # retry would send the card twice.
    for attempt in range(SEND_ATTEMPTS):
        try:
            response = requests.post(
                f"{API_BASE}/bot{token}/sendMessage",
                json=payload,
                timeout=30,  # 10s timed out once on a live send that Telegram answered fine seconds later
            )
            break
        except requests.exceptions.Timeout:
            raise
        except requests.exceptions.ConnectionError:
            if attempt == SEND_ATTEMPTS - 1:
                raise
            time.sleep(RETRY_PAUSE_SECONDS)
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram sendMessage failed: {payload}")
    return payload
