"""Enforces the daily approval budget (default 25, DAILY_DRAFT_CAP in .env):
outreach Gmail drafts plus application cards sent to Telegram, counted
together, so one day never asks the student to review more than he can
actually read."""

from __future__ import annotations

from internship_hunter import config


class DailyCapReached(RuntimeError):
    pass


def drafts_created_today(conn) -> int:
    emails = conn.execute(
        "SELECT COUNT(*) AS n FROM messages WHERE channel = 'email' AND date(created_at, 'localtime') = date('now', 'localtime')"
    ).fetchone()
    cards = conn.execute(
        "SELECT COUNT(*) AS n FROM applications WHERE date(proposed_at, 'localtime') = date('now', 'localtime')"
    ).fetchone()
    return emails["n"] + cards["n"]


def outreach_today(conn) -> int:
    """People put in front of him today: email drafts plus LinkedIn cards."""
    return conn.execute(
        "SELECT COUNT(*) AS n FROM messages WHERE channel IN ('email', 'linkedin') AND date(created_at, 'localtime') = date('now', 'localtime')"
    ).fetchone()["n"]


def outreach_remaining(conn) -> int:
    """How many more the bot may send on its own today (OUTREACH_PER_DAY,
    default 5). Commands he types himself aren't held to this -- only to
    the hard caps below."""
    return max(0, config.OUTREACH_PER_DAY - outreach_today(conn))


def remaining_today(conn, cap: int | None = None) -> int:
    cap = cap if cap is not None else config.DAILY_DRAFT_CAP
    return max(0, cap - drafts_created_today(conn))


def enforce_daily_cap(conn, cap: int | None = None) -> None:
    """Raises DailyCapReached if today's cap is already hit. Call this
    BEFORE composing/creating a draft, not after -- no point spending an API
    call or creating a Gmail draft that then gets rejected."""
    if remaining_today(conn, cap) <= 0:
        cap = cap if cap is not None else config.DAILY_DRAFT_CAP
        raise DailyCapReached(
            f"Already sent you {drafts_created_today(conn)} thing(s) to approve today (cap is {cap})."
        )
