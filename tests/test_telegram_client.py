import pytest

from internship_hunter.notify import telegram_client


class FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json_data = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json_data


def test_send_message_requires_a_bot_token(monkeypatch):
    monkeypatch.setattr(telegram_client.config, "TELEGRAM_BOT_TOKEN", "")
    with pytest.raises(telegram_client.TelegramNotConfigured):
        telegram_client.send_message("hello")


def test_send_message_requires_a_chat_id(monkeypatch):
    monkeypatch.setattr(telegram_client.config, "TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setattr(telegram_client.config, "TELEGRAM_CHAT_ID", "")
    with pytest.raises(telegram_client.TelegramNotConfigured):
        telegram_client.send_message("hello")


def test_send_message_posts_text_and_chat_id(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse({"ok": True, "result": {"message_id": 1}})

    monkeypatch.setattr(telegram_client.requests, "post", fake_post)

    result = telegram_client.send_message("hello there", chat_id="12345", bot_token="tok")

    assert captured["url"] == "https://api.telegram.org/bottok/sendMessage"
    assert captured["json"] == {"chat_id": "12345", "text": "hello there", "disable_web_page_preview": True}
    assert result["ok"] is True


def test_send_message_raises_when_telegram_reports_not_ok(monkeypatch):
    monkeypatch.setattr(
        telegram_client.requests,
        "post",
        lambda url, json, timeout: FakeResponse({"ok": False, "description": "bad chat id"}),
    )
    with pytest.raises(RuntimeError, match="bad chat id"):
        telegram_client.send_message("hello", chat_id="bad", bot_token="tok")


def test_fetch_latest_chat_id_returns_chat_id_of_most_recent_message(monkeypatch):
    fake_updates = {
        "ok": True,
        "result": [
            {"message": {"chat": {"id": 111}, "text": "hi"}},
            {"message": {"chat": {"id": 222}, "text": "hi again"}},
        ],
    }
    monkeypatch.setattr(
        telegram_client.requests,
        "get",
        lambda url, timeout: FakeResponse(fake_updates),
    )
    assert telegram_client.fetch_latest_chat_id(bot_token="tok") == 222


def test_fetch_latest_chat_id_raises_when_no_messages_yet(monkeypatch):
    monkeypatch.setattr(
        telegram_client.requests,
        "get",
        lambda url, timeout: FakeResponse({"ok": True, "result": []}),
    )
    with pytest.raises(RuntimeError, match="send it any"):
        telegram_client.fetch_latest_chat_id(bot_token="tok")


class _Ok:
    def raise_for_status(self):
        pass

    def json(self):
        return {"ok": True, "result": {"message_id": 1}}


def test_send_message_retries_a_dropped_connection_but_never_a_timeout(monkeypatch):
    import requests

    monkeypatch.setattr(telegram_client, "RETRY_PAUSE_SECONDS", 0)
    calls = []

    def flaky(url, json=None, timeout=None):
        calls.append(json["text"])
        if len(calls) < 3:
            raise requests.exceptions.ConnectionError("connection reset")
        return _Ok()

    monkeypatch.setattr(telegram_client.requests, "post", flaky)
    assert telegram_client.send_message("hi", chat_id=1, bot_token="t")["ok"] is True
    assert calls == ["hi", "hi", "hi"]

    # A timeout may have been delivered, so it is not sent again.
    calls.clear()

    def slow(url, json=None, timeout=None):
        calls.append(json["text"])
        raise requests.exceptions.ReadTimeout("slow")

    monkeypatch.setattr(telegram_client.requests, "post", slow)
    try:
        telegram_client.send_message("hi", chat_id=1, bot_token="t")
    except requests.exceptions.Timeout:
        pass
    assert calls == ["hi"]
