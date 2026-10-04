"""Enforces CLAUDE.md's daily outreach cap (default 10) so every draft
stays personal instead of turning this into a volume play."""

from __future__ import annotations

from internship_hunter import config


class DailyCapReached(RuntimeError):
    pass


def drafts_created_today(conn) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM messages WHERE channel = 'email' AND date(created_at) = date('now')"
    ).fetchone()
    return row["n"]


def remaining_today(conn, cap: int | None = None) -> int:
    cap = cap if cap is not None else config.DAILY_DRAFT_CAP
    return max(0, cap - drafts_created_today(conn))


def enforce_daily_cap(conn, cap: int | None = None) -> None:
    """Raises DailyCapReached if today's cap is already hit. Call this
    BEFORE composing/creating a draft, not after -- no point spending an API
    call or creating a Gmail draft that then gets rejected."""
    if remaining_today(conn, cap) <= 0:
        cap = cap if cap is not None else config.DAILY_DRAFT_CAP
        raise DailyCapReached(f"Already created {drafts_created_today(conn)} draft(s) today (cap is {cap}).")
