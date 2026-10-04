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
    assert captured["json"] == {"chat_id": "12345", "text": "hello there"}
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
