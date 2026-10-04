"""SQLite access layer. Every other module reads/writes the tracker through
these functions instead of writing its own SQL, so the schema only lives in
one place.

SQLite is a single file (data/tracker.db) -- there's no server to run, which
is why CLAUDE.md picked it for a personal tool like this.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from internship_hunter import config
from internship_hunter.models import Company, Posting

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    website TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL DEFAULT '',
    stage TEXT NOT NULL DEFAULT '',
    what_they_build TEXT NOT NULL DEFAULT '',
    why_fit TEXT NOT NULL DEFAULT '',
    careers_url TEXT NOT NULL DEFAULT '',
    priority_tier INTEGER NOT NULL CHECK (priority_tier IN (1, 2, 3, 4)),
    needs_verification INTEGER NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT '',
    ats_type TEXT,
    ats_slug TEXT,
    manual_check_needed INTEGER NOT NULL DEFAULT 0,
    team_url TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS postings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    external_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    ats_source TEXT NOT NULL DEFAULT 'manual',
    is_software_role INTEGER NOT NULL DEFAULT 0,
    is_intern_or_junior INTEGER NOT NULL DEFAULT 0,
    clearance_required INTEGER NOT NULL DEFAULT 0,
    citizenship_required INTEGER NOT NULL DEFAULT 0,
    skill_match TEXT NOT NULL DEFAULT 'unclear',
    status TEXT NOT NULL DEFAULT 'new',
    first_seen_date TEXT NOT NULL DEFAULT (date('now')),
    last_seen_date TEXT NOT NULL DEFAULT (date('now')),
    UNIQUE (company_id, external_id)
);

CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL,
    fact TEXT NOT NULL DEFAULT '',
    email TEXT,
    found_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
    posting_id INTEGER REFERENCES postings(id) ON DELETE SET NULL,
    channel TEXT NOT NULL DEFAULT 'email',
    subject TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    gmail_draft_id TEXT,
    status TEXT NOT NULL DEFAULT 'drafted',
    sent_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Open a connection with dict-like row access and foreign keys enforced."""
    path = db_path or config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# Columns added to a table after its CREATE TABLE IF NOT EXISTS was already
# shipped -- CREATE TABLE IF NOT EXISTS silently no-ops on an existing table,
# so a new column never actually reaches a database created before this
# line was added, and every read of it throws IndexError at runtime (hit
# live with team_url). Listed here once; init_db applies whichever of these
# a given database is still missing, every run, so this class of bug can't
# recur as the schema keeps growing.
COLUMN_MIGRATIONS = [
    ("companies", "team_url", "TEXT"),
]


def init_db(conn: sqlite3.Connection) -> None:
    """Create all tables if they don't exist yet, then apply any pending
    column migrations. Safe to call every run."""
    conn.executescript(SCHEMA)
    conn.commit()
    for table, column, col_type in COLUMN_MIGRATIONS:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
    conn.commit()


# --- Companies -----------------------------------------------------------

def insert_company(conn: sqlite3.Connection, company: Company) -> int:
    """Insert a company and return its new id. Raises sqlite3.IntegrityError
    if a company with that name already exists (names are unique)."""
    cur = conn.execute(
        """
        INSERT INTO companies
            (name, website, state, city, stage, what_they_build, why_fit,
             careers_url, priority_tier, needs_verification, notes,
             ats_type, ats_slug, manual_check_needed, team_url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            company.name,
            company.website,
            company.state,
            company.city,
            company.stage,
            company.what_they_build,
            company.why_fit,
            company.careers_url,
            company.priority_tier,
            int(company.needs_verification),
            company.notes,
            company.ats_type,
            company.ats_slug,
            int(company.manual_check_needed),
            company.team_url,
        ),
    )
    conn.commit()
    return cur.lastrowid


def company_from_row(row: sqlite3.Row) -> Company:
    return Company(
        id=row["id"],
        name=row["name"],
        website=row["website"],
        state=row["state"],
        city=row["city"],
        stage=row["stage"],
        what_they_build=row["what_they_build"],
        why_fit=row["why_fit"],
        careers_url=row["careers_url"],
        priority_tier=row["priority_tier"],
        needs_verification=bool(row["needs_verification"]),
        notes=row["notes"],
        ats_type=row["ats_type"],
        ats_slug=row["ats_slug"],
        manual_check_needed=bool(row["manual_check_needed"]),
        team_url=row["team_url"],
        created_at=row["created_at"],
    )


def get_company_by_name(conn: sqlite3.Connection, name: str) -> Optional[Company]:
    row = conn.execute("SELECT * FROM companies WHERE name = ?", (name,)).fetchone()
    return company_from_row(row) if row else None


def list_companies(
    conn: sqlite3.Connection,
    tier: Optional[int] = None,
    state: Optional[str] = None,
) -> list[Company]:
    """List companies, optionally filtered by tier and/or state. No implicit
    state ranking is applied -- VA/CO/WI are weighted equally per the
    student's choice, so results are just sorted by tier then name."""
    query = "SELECT * FROM companies WHERE 1=1"
    params: list = []
    if tier is not None:
        query += " AND priority_tier = ?"
        params.append(tier)
    if state is not None:
        query += " AND state = ?"
        params.append(state)
    query += " ORDER BY priority_tier ASC, name ASC"
    rows = conn.execute(query, params).fetchall()
    return [company_from_row(r) for r in rows]


def delete_company(conn: sqlite3.Connection, name: str) -> bool:
    """Delete a company by name. Returns True if a row was deleted."""
    cur = conn.execute("DELETE FROM companies WHERE name = ?", (name,))
    conn.commit()
    return cur.rowcount > 0


def update_company_tier(conn: sqlite3.Connection, name: str, new_tier: int) -> bool:
    if new_tier not in (1, 2, 3, 4):
        raise ValueError(f"priority_tier must be 1-4, got {new_tier!r}")
    cur = conn.execute(
        "UPDATE companies SET priority_tier = ? WHERE name = ?", (new_tier, name)
    )
    conn.commit()
    return cur.rowcount > 0


def set_company_ats(conn: sqlite3.Connection, company_id: int, ats_type: str, ats_slug: str) -> None:
    """Cache a confirmed ATS vendor+slug for a company so future scans hit it
    directly instead of re-running slug detection every time."""
    conn.execute(
        "UPDATE companies SET ats_type = ?, ats_slug = ?, manual_check_needed = 0 WHERE id = ?",
        (ats_type, ats_slug, company_id),
    )
    conn.commit()


def set_company_manual_check_needed(conn: sqlite3.Connection, company_id: int, needed: bool = True) -> None:
    conn.execute(
        "UPDATE companies SET manual_check_needed = ? WHERE id = ?",
        (int(needed), company_id),
    )
    conn.commit()


def set_company_team_url(conn: sqlite3.Connection, company_id: int, team_url: str) -> None:
    """Cache a confirmed team/about page URL so future people-finder runs
    skip straight to it instead of re-probing candidate paths every time."""
    conn.execute(
        "UPDATE companies SET team_url = ? WHERE id = ?",
        (team_url, company_id),
    )
    conn.commit()


# --- Postings --------------------------------------------------------------

def posting_from_row(row: sqlite3.Row) -> Posting:
    return Posting(
        id=row["id"],
        company_id=row["company_id"],
        external_id=row["external_id"],
        title=row["title"],
        location=row["location"],
        url=row["url"],
        ats_source=row["ats_source"],
        is_software_role=bool(row["is_software_role"]),
        is_intern_or_junior=bool(row["is_intern_or_junior"]),
        clearance_required=bool(row["clearance_required"]),
        citizenship_required=bool(row["citizenship_required"]),
        skill_match=row["skill_match"],
        status=row["status"],
        first_seen_date=row["first_seen_date"],
        last_seen_date=row["last_seen_date"],
    )


def upsert_posting(conn: sqlite3.Connection, posting: Posting) -> tuple[int, bool]:
    """Insert a posting, or if (company_id, external_id) already exists, just
    bump its last_seen_date. Returns (posting_id, is_new_today).

    This is the heart of "only show new postings each day" -- a posting is
    "new" exactly when this is the first time we've ever seen that
    (company, external_id) pair.
    """
    existing = conn.execute(
        "SELECT id FROM postings WHERE company_id = ? AND external_id = ?",
        (posting.company_id, posting.external_id),
    ).fetchone()
    if existing is not None:
        conn.execute(
            "UPDATE postings SET last_seen_date = date('now'), title = ?, location = ?, url = ? WHERE id = ?",
            (posting.title, posting.location, posting.url, existing["id"]),
        )
        conn.commit()
        return existing["id"], False

    cur = conn.execute(
        """
        INSERT INTO postings
            (company_id, external_id, title, location, url, ats_source,
             is_software_role, is_intern_or_junior, clearance_required,
             citizenship_required, skill_match)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            posting.company_id,
            posting.external_id,
            posting.title,
            posting.location,
            posting.url,
            posting.ats_source,
            int(posting.is_software_role),
            int(posting.is_intern_or_junior),
            int(posting.clearance_required),
            int(posting.citizenship_required),
            posting.skill_match,
        ),
    )
    conn.commit()
    return cur.lastrowid, True


def list_postings_first_seen_today(conn: sqlite3.Connection) -> list[Posting]:
    rows = conn.execute(
        "SELECT * FROM postings WHERE first_seen_date = date('now') ORDER BY company_id"
    ).fetchall()
    return [posting_from_row(r) for r in rows]


def list_postings(
    conn: sqlite3.Connection,
    company_id: Optional[int] = None,
    software_only: bool = False,
) -> list[Posting]:
    query = "SELECT * FROM postings WHERE 1=1"
    params: list = []
    if company_id is not None:
        query += " AND company_id = ?"
        params.append(company_id)
    if software_only:
        query += " AND is_software_role = 1"
    query += " ORDER BY first_seen_date DESC"
    rows = conn.execute(query, params).fetchall()
    return [posting_from_row(r) for r in rows]


# --- Contacts --------------------------------------------------------------

def contact_from_row(row: sqlite3.Row) -> "Contact":
    from internship_hunter.models import Contact

    return Contact(
        id=row["id"],
        company_id=row["company_id"],
        name=row["name"],
        title=row["title"],
        source_url=row["source_url"],
        fact=row["fact"],
        email=row["email"],
        found_at=row["found_at"],
    )


def insert_contact(conn: sqlite3.Connection, contact: "Contact") -> int:
    """Insert a contact. Every contact must carry a source_url -- this is
    what lets a human verify the fact before trusting it (CLAUDE.md: a
    source for every fact). The schema enforces NOT NULL; this also rejects
    an empty string, which the schema alone would allow through."""
    if not contact.source_url:
        raise ValueError("Contact must have a non-empty source_url")
    cur = conn.execute(
        """
        INSERT INTO contacts (company_id, name, title, source_url, fact, email)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (contact.company_id, contact.name, contact.title, contact.source_url, contact.fact, contact.email),
    )
    conn.commit()
    return cur.lastrowid


def get_contact_by_name(conn: sqlite3.Connection, company_id: int, name: str) -> Optional["Contact"]:
    row = conn.execute(
        "SELECT * FROM contacts WHERE company_id = ? AND name = ?", (company_id, name)
    ).fetchone()
    return contact_from_row(row) if row else None


def list_contacts(conn: sqlite3.Connection, company_id: Optional[int] = None) -> list:
    query = "SELECT * FROM contacts WHERE 1=1"
    params: list = []
    if company_id is not None:
        query += " AND company_id = ?"
        params.append(company_id)
    query += " ORDER BY company_id, name"
    rows = conn.execute(query, params).fetchall()
    return [contact_from_row(r) for r in rows]
