"""Pure follow-up logic -- no Streamlit, no network, so it's unit-testable
with fixed dates instead of depending on "today" or a running dashboard.

A message is due for a follow-up when it's actually been sent (not just
drafted) and 7+ days have passed with no reply recorded. The clock runs off
sent_at, not created_at, since a draft can sit unsent in Gmail for a while
before the student actually sends it -- see db.update_message_status.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from internship_hunter import config
from internship_hunter.models import Message


def _parse_date(value: str) -> date:
    # Stored as sqlite datetime('now') -- "YYYY-MM-DD HH:MM:SS".
    return datetime.strptime(value.split(" ")[0], "%Y-%m-%d").date()


def days_since_sent(message: Message, today: Optional[date] = None) -> Optional[int]:
    if not message.sent_at:
        return None
    today = today or date.today()
    return (today - _parse_date(message.sent_at)).days


def needs_follow_up(message: Message, today: Optional[date] = None) -> bool:
    """True only for a 'sent' message that's old enough with no reply yet.
    Anything else (still drafted, or already replied/interviewing/rejected)
    is explicitly not a follow-up candidate."""
    # Email only: a LinkedIn request that went unanswered gets one reminder
    # in Telegram (linkedin_assist/assist.py), never a follow-up email.
    if message.status != "sent" or message.channel != "email":
        return False
    days = days_since_sent(message, today)
    return days is not None and days >= config.FOLLOW_UP_AFTER_DAYS


def filter_needing_follow_up(messages: list[Message], today: Optional[date] = None) -> list[Message]:
    return [m for m in messages if needs_follow_up(m, today)]


def build_follow_up_context(message: Message, today: Optional[date] = None) -> str:
    days = days_since_sent(message, today)
    return (
        f"The original email (subject: \"{message.subject}\") was sent {days} days ago "
        "and hasn't gotten a reply yet."
    )
