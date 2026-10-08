"""SQLite access layer. Every other module reads/writes the tracker through
these functions instead of writing its own SQL, so the schema only lives in
one place.

SQLite is a single file (data/tracker.db) -- there's no server to run, which
is why CLAUDE.md picked it for a personal tool like this.
"""

from __future__ import annotations

import json
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
    contact_email TEXT,
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

CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    posting_id INTEGER NOT NULL UNIQUE REFERENCES postings(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'proposed',
    answers_json TEXT NOT NULL DEFAULT '{}',
    left_for_you_json TEXT NOT NULL DEFAULT '[]',
    telegram_message_id INTEGER,
    proposed_at TEXT NOT NULL DEFAULT (datetime('now')),
    decided_at TEXT,
    submitted_at TEXT
);

CREATE TABLE IF NOT EXISTS hunter_cache (
    domain TEXT PRIMARY KEY,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
    response_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
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
    ("companies", "contact_email", "TEXT"),
    ("companies", "people_checked_at", "TEXT"),
    ("postings", "eligibility", "TEXT"),
    ("postings", "eligibility_reason", "TEXT NOT NULL DEFAULT ''"),
    ("contacts", "email_source_url", "TEXT"),
    ("messages", "to_email", "TEXT"),
    ("messages", "gmail_thread_id", "TEXT"),
    ("contacts", "source_kind", "TEXT NOT NULL DEFAULT 'team_page'"),
    ("contacts", "linkedin_url", "TEXT"),
    ("companies", "web_people_checked_at", "TEXT"),
    ("messages", "reminded_at", "TEXT"),
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
        contact_email=row["contact_email"],
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


def set_company_contact_email(conn: sqlite3.Connection, company_id: int, email: str) -> None:
    """Store an inbox the company publishes on its own website, used as the
    "To" address when a named contact has no published email of their own."""
    conn.execute("UPDATE companies SET contact_email = ? WHERE id = ?", (email, company_id))
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
        eligibility=row["eligibility"],
        eligibility_reason=row["eligibility_reason"],
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
        # The classification flags are refreshed too: they're recomputed from
        # the posting's current text on every scan, so a rule added later
        # (e.g. recognising "open to high school students") reaches postings
        # that were first stored before the rule existed.
        conn.execute(
            """
            UPDATE postings SET last_seen_date = date('now'), title = ?, location = ?, url = ?,
                is_software_role = ?, is_intern_or_junior = ?, clearance_required = ?,
                citizenship_required = ?, skill_match = ?
            WHERE id = ?
            """,
            (
                posting.title, posting.location, posting.url,
                int(posting.is_software_role), int(posting.is_intern_or_junior), int(posting.clearance_required),
                int(posting.citizenship_required), posting.skill_match, existing["id"],
            ),
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
        email_source_url=row["email_source_url"],
        source_kind=row["source_kind"],
        linkedin_url=row["linkedin_url"],
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
        INSERT INTO contacts (company_id, name, title, source_url, fact, email, source_kind, linkedin_url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            contact.company_id, contact.name, contact.title, contact.source_url, contact.fact, contact.email,
            contact.source_kind, contact.linkedin_url,
        ),
    )
    conn.commit()
    return cur.lastrowid


def get_contact_by_name(conn: sqlite3.Connection, company_id: int, name: str) -> Optional["Contact"]:
    row = conn.execute(
        "SELECT * FROM contacts WHERE company_id = ? AND name = ?", (company_id, name)
    ).fetchone()
    return contact_from_row(row) if row else None


def get_contact(conn: sqlite3.Connection, contact_id: int) -> Optional["Contact"]:
    row = conn.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,)).fetchone()
    return contact_from_row(row) if row else None


def set_contact_fact(conn: sqlite3.Connection, contact_id: int, fact: str, source_url: str, source_kind: str) -> None:
    """Replace what we know about a person, together with where it came
    from -- a fact and its source only ever change as a pair."""
    if not source_url:
        raise ValueError("A fact about a contact must come with the URL it was read from")
    conn.execute(
        "UPDATE contacts SET fact = ?, source_url = ?, source_kind = ? WHERE id = ?",
        (fact, source_url, source_kind, contact_id),
    )
    conn.commit()


def set_contact_linkedin_url(conn: sqlite3.Connection, contact_id: int, linkedin_url: str) -> None:
    conn.execute("UPDATE contacts SET linkedin_url = ? WHERE id = ?", (linkedin_url, contact_id))
    conn.commit()


def delete_contact_into(conn: sqlite3.Connection, duplicate_id: int, keep_id: int) -> None:
    """Remove a duplicate contact, moving its messages to the one kept so
    no outreach history is lost."""
    conn.execute("UPDATE messages SET contact_id = ? WHERE contact_id = ?", (keep_id, duplicate_id))
    conn.execute("DELETE FROM contacts WHERE id = ?", (duplicate_id,))
    conn.commit()


def list_contacts(conn: sqlite3.Connection, company_id: Optional[int] = None) -> list:
    query = "SELECT * FROM contacts WHERE 1=1"
    params: list = []
    if company_id is not None:
        query += " AND company_id = ?"
        params.append(company_id)
    query += " ORDER BY company_id, name"
    rows = conn.execute(query, params).fetchall()
    return [contact_from_row(r) for r in rows]


# --- Messages ----------------------------------------------------------

def message_from_row(row: sqlite3.Row) -> "Message":
    from internship_hunter.models import Message

    return Message(
        id=row["id"],
        company_id=row["company_id"],
        contact_id=row["contact_id"],
        posting_id=row["posting_id"],
        channel=row["channel"],
        subject=row["subject"],
        body=row["body"],
        gmail_draft_id=row["gmail_draft_id"],
        status=row["status"],
        sent_at=row["sent_at"],
        to_email=row["to_email"],
        gmail_thread_id=row["gmail_thread_id"],
        reminded_at=row["reminded_at"],
        created_at=row["created_at"],
    )


def insert_message(conn: sqlite3.Connection, message: "Message") -> int:
    cur = conn.execute(
        """
        INSERT INTO messages (company_id, contact_id, posting_id, channel, subject, body, gmail_draft_id, status, sent_at, to_email)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            message.company_id, message.contact_id, message.posting_id, message.channel,
            message.subject, message.body, message.gmail_draft_id, message.status, message.sent_at,
            message.to_email,
        ),
    )
    conn.commit()
    return cur.lastrowid


def get_message(conn: sqlite3.Connection, message_id: int) -> Optional["Message"]:
    row = conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
    return message_from_row(row) if row else None


def list_messages(conn: sqlite3.Connection, status: Optional[str] = None, company_id: Optional[int] = None) -> list:
    query = "SELECT * FROM messages WHERE 1=1"
    params: list = []
    if status is not None:
        query += " AND status = ?"
        params.append(status)
    if company_id is not None:
        query += " AND company_id = ?"
        params.append(company_id)
    query += " ORDER BY created_at DESC"
    rows = conn.execute(query, params).fetchall()
    return [message_from_row(r) for r in rows]


def update_message_status(conn: sqlite3.Connection, message_id: int, new_status: str, sent_at: Optional[str] = None) -> bool:
    """Update a message's status. Pass sent_at (a datetime('now')-style
    string) when moving to 'sent' -- the 7-day follow-up clock (see
    dashboard/followups.py) runs off that, not created_at, since a draft
    can sit unsent for a while before the student actually sends it."""
    if new_status not in config.MESSAGE_STATUSES:
        raise ValueError(f"status must be one of {config.MESSAGE_STATUSES}, got {new_status!r}")
    if sent_at is not None:
        cur = conn.execute(
            "UPDATE messages SET status = ?, sent_at = ? WHERE id = ?", (new_status, sent_at, message_id)
        )
    else:
        cur = conn.execute("UPDATE messages SET status = ? WHERE id = ?", (new_status, message_id))
    conn.commit()
    return cur.rowcount > 0


def set_message_to_email(conn: sqlite3.Connection, message_id: int, to_email: str) -> None:
    conn.execute("UPDATE messages SET to_email = ? WHERE id = ?", (to_email, message_id))
    conn.commit()


def mark_message_sent(conn: sqlite3.Connection, message_id: int, thread_id: Optional[str] = None) -> None:
    """Record that an email went out now, and the Gmail thread to watch for
    a reply in (None if he sent it from Gmail and we couldn't find it)."""
    conn.execute(
        "UPDATE messages SET status = 'sent', sent_at = datetime('now', 'localtime'), "
        "gmail_thread_id = COALESCE(?, gmail_thread_id) WHERE id = ?",
        (thread_id, message_id),
    )
    conn.commit()


def set_contact_email(conn: sqlite3.Connection, contact_id: int, email: str, source_url: str) -> None:
    """Store an email for a contact, with the public page it was read from
    (same rule as every other fact about a person: no source, no storage)."""
    if not source_url:
        raise ValueError("A contact's email must come with the URL it was published at")
    conn.execute("UPDATE contacts SET email = ?, email_source_url = ? WHERE id = ?", (email, source_url, contact_id))
    conn.commit()


def mark_message_reminded(conn: sqlite3.Connection, message_id: int) -> None:
    conn.execute("UPDATE messages SET reminded_at = datetime('now', 'localtime') WHERE id = ?", (message_id,))
    conn.commit()


def mark_web_people_checked(conn: sqlite3.Connection, company_id: int) -> None:
    conn.execute("UPDATE companies SET web_people_checked_at = datetime('now') WHERE id = ?", (company_id,))
    conn.commit()


def list_companies_never_web_searched(conn: sqlite3.Connection) -> list[Company]:
    """Companies the web people search has never been run on -- each one
    is only ever paid for once."""
    rows = conn.execute(
        "SELECT * FROM companies WHERE web_people_checked_at IS NULL ORDER BY priority_tier, name"
    ).fetchall()
    return [company_from_row(r) for r in rows]


def mark_people_checked(conn: sqlite3.Connection, company_id: int) -> None:
    conn.execute("UPDATE companies SET people_checked_at = datetime('now') WHERE id = ?", (company_id,))
    conn.commit()


def list_companies_never_people_checked(conn: sqlite3.Connection) -> list[Company]:
    """Companies the people finder has never been run on -- so the daily
    run only ever spends an API call on a company once."""
    rows = conn.execute(
        "SELECT * FROM companies WHERE people_checked_at IS NULL ORDER BY priority_tier, name"
    ).fetchall()
    return [company_from_row(r) for r in rows]


# --- Applications (the Telegram approval queue) ----------------------------

def application_from_row(row: sqlite3.Row) -> "Application":
    from internship_hunter.models import Application

    return Application(
        id=row["id"],
        posting_id=row["posting_id"],
        status=row["status"],
        answers=json.loads(row["answers_json"]),
        left_for_you=json.loads(row["left_for_you_json"]),
        telegram_message_id=row["telegram_message_id"],
        proposed_at=row["proposed_at"],
        decided_at=row["decided_at"],
        submitted_at=row["submitted_at"],
    )


def insert_application(conn: sqlite3.Connection, application: "Application") -> int:
    """Insert an application. posting_id is UNIQUE, so a posting can only
    ever be put in front of the student once -- a second attempt raises
    sqlite3.IntegrityError instead of sending a duplicate card."""
    cur = conn.execute(
        """
        INSERT INTO applications (posting_id, status, answers_json, left_for_you_json, telegram_message_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            application.posting_id, application.status, json.dumps(application.answers),
            json.dumps(application.left_for_you), application.telegram_message_id,
        ),
    )
    conn.commit()
    return cur.lastrowid


def get_application(conn: sqlite3.Connection, application_id: int) -> Optional["Application"]:
    row = conn.execute("SELECT * FROM applications WHERE id = ?", (application_id,)).fetchone()
    return application_from_row(row) if row else None


def list_applications(conn: sqlite3.Connection, status: Optional[str] = None) -> list:
    query = "SELECT * FROM applications"
    params: list = []
    if status is not None:
        query += " WHERE status = ?"
        params.append(status)
    query += " ORDER BY id"
    return [application_from_row(r) for r in conn.execute(query, params).fetchall()]


def set_application_telegram_message_id(conn: sqlite3.Connection, application_id: int, message_id: int) -> None:
    conn.execute("UPDATE applications SET telegram_message_id = ? WHERE id = ?", (message_id, application_id))
    conn.commit()


def update_application_status(conn: sqlite3.Connection, application_id: int, new_status: str) -> bool:
    """Move an application to a new status, stamping decided_at on
    approve/skip and submitted_at on submit (the 7-day "no word yet" clock
    runs off submitted_at)."""
    if new_status not in config.APPLICATION_STATUSES:
        raise ValueError(f"status must be one of {config.APPLICATION_STATUSES}, got {new_status!r}")
    stamp = {"approved": "decided_at", "skipped": "decided_at", "submitted": "submitted_at"}.get(new_status)
    if stamp:
        cur = conn.execute(
            f"UPDATE applications SET status = ?, {stamp} = datetime('now') WHERE id = ?",
            (new_status, application_id),
        )
    else:
        cur = conn.execute("UPDATE applications SET status = ? WHERE id = ?", (new_status, application_id))
    conn.commit()
    return cur.rowcount > 0


def get_posting(conn: sqlite3.Connection, posting_id: int) -> Optional[Posting]:
    row = conn.execute("SELECT * FROM postings WHERE id = ?", (posting_id,)).fetchone()
    return posting_from_row(row) if row else None


def set_posting_eligibility(conn: sqlite3.Connection, posting_id: int, verdict: str, reason: str) -> None:
    conn.execute(
        "UPDATE postings SET eligibility = ?, eligibility_reason = ? WHERE id = ?", (verdict, reason, posting_id)
    )
    conn.commit()


def get_company(conn: sqlite3.Connection, company_id: int) -> Optional[Company]:
    row = conn.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
    return company_from_row(row) if row else None


def list_postings_not_yet_proposed(conn: sqlite3.Connection) -> list[Posting]:
    """Software intern/junior postings with no clearance requirement and no
    skill gap (the same bar as the Telegram digest, see
    filters.worth_notifying) that have never been put in the approval queue."""
    rows = conn.execute(
        """
        SELECT p.* FROM postings p
        WHERE p.is_software_role = 1 AND p.is_intern_or_junior = 1
          AND p.clearance_required = 0 AND p.skill_match != 'gap'
          AND COALESCE(p.eligibility, '') != 'not_eligible'
          AND p.id NOT IN (SELECT posting_id FROM applications)
        ORDER BY p.first_seen_date DESC, p.id
        """
    ).fetchall()
    return [posting_from_row(r) for r in rows]


# --- Meta (tiny key/value store, e.g. the last day the bot ran its daily batch) ---

def get_meta(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()
