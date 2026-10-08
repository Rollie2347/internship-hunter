"""Who to write to next. Both the email picker (drafting/batch.py) and the
LinkedIn picker (linkedin_assist/assist.py) order people the same way, so
"today's five" is one list, not two competing ones:

  1. company tier (defense startups first),
  1b. within a tier, companies where the fewest people have been written to
     -- on the first live day three people at one company got cards, which
     from their side looks like spam,
  2. then companies that are hiring software people right now --
     the job scanner still reads every public feed each day, but its
     postings are no longer something to apply to. They're a signal that
     a team is growing, which is the best moment to write to someone on it,
  3. one person per company before a second at any company,
  4. inside a company, the people closest to the software: engineers and
     technical leaders, then founders, then recruiters, then everyone else
     (a first live card went to a Chief of Staff -- a real person, but not
     someone who can say what the software team needs).

Only companies based in Colorado or Virginia, and never tier 4 (government
and lab programs have their own application process).
"""

from __future__ import annotations

from internship_hunter import config, db
from internship_hunter.models import Company, Contact, Posting


def hiring_now(conn) -> dict[int, list[Posting]]:
    """company id -> software postings seen on its job board in the last
    HIRING_SIGNAL_DAYS days."""
    rows = conn.execute(
        "SELECT * FROM postings WHERE is_software_role = 1 AND last_seen_date >= date('now', ?) ORDER BY last_seen_date DESC",
        (f"-{config.HIRING_SIGNAL_DAYS} days",),
    ).fetchall()
    signals: dict[int, list[Posting]] = {}
    for row in rows:
        signals.setdefault(row["company_id"], []).append(db.posting_from_row(row))
    return signals


def companies_in_order(conn, any_state: bool = False) -> list[Company]:
    hiring = hiring_now(conn)
    eligible = [
        c for c in db.list_companies(conn)
        if c.priority_tier != 4 and (any_state or c.state in config.PREFERRED_STATES)
    ]
    written_to: dict[int, set] = {}
    for m in db.list_messages(conn):
        if m.contact_id and m.status not in ("skipped", "not_found"):
            written_to.setdefault(m.company_id, set()).add(m.contact_id)
    return sorted(
        eligible,
        key=lambda c: (c.priority_tier, len(written_to.get(c.id, ())), c.id not in hiring, c.name),
    )


# Checked in order; the first group with a matching word wins.
ROLE_GROUPS = (
    ("cto", "chief technology", "technical", "engineer", "software", "developer", "autonomy", "robotics",
     "architect", "scientist", "research", "machine learning", " ai", "data"),
    ("founder", "ceo", "chief executive", "president"),
    ("recruit", "talent", "people", "human resources"),
)


def role_rank(title: str) -> int:
    """0 = technical, 1 = founder/CEO, 2 = recruiting, 3 = anyone else."""
    lowered = f" {(title or '').lower()}"
    for rank, words in enumerate(ROLE_GROUPS):
        if any(word in lowered for word in words):
            return rank
    return len(ROLE_GROUPS)


def by_role(contacts: list[Contact]) -> list[Contact]:
    return sorted(contacts, key=lambda c: (role_rank(c.title), c.name))


def round_robin(per_company: list[tuple[Company, list[Contact]]], limit: int) -> list[tuple[Company, Contact]]:
    """One person from each company in turn, so a batch spreads across
    companies instead of sending five notes into one."""
    picked: list[tuple[Company, Contact]] = []
    round_index = 0
    while len(picked) < limit and any(len(contacts) > round_index for _, contacts in per_company):
        for company, contacts in per_company:
            if len(contacts) > round_index and len(picked) < limit:
                picked.append((company, contacts[round_index]))
        round_index += 1
    return picked


def hiring_line(company: Company, signals: dict[int, list[Posting]]) -> str:
    """One line for a card, or "" if the company has no open software roles."""
    postings = signals.get(company.id) or []
    if not postings:
        return ""
    more = f" and {len(postings) - 1} more" if len(postings) > 1 else ""
    return f"Hiring software people now: {postings[0].title}{more} (a signal, not something to apply to)."
