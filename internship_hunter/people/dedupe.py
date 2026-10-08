"""One person, one row -- however many sources turned them up.

The team-page reader, the web search and /li can all find the same CTO.
Every source stores people through store_contact() here, which either
inserts a new contact or folds what's new into the one already on file.

Two names count as the same person only inside ONE company, and only when
the last names match and the first names are the same, an initial of each
other ("J. Doe" / "Jane Doe"), a shortening ("Chris" / "Christopher") or a
common nickname ("Mike" / "Michael"). Anything less certain stays two rows:
a duplicate card is a small annoyance, but merging two different people
would put one person's fact in a note to the other.
"""

from __future__ import annotations

from internship_hunter import db
from internship_hunter.models import Contact
from internship_hunter.people.email_finder import name_parts

NICKNAMES = {
    "mike": "michael", "bill": "william", "will": "william", "bob": "robert", "rob": "robert",
    "jim": "james", "tom": "thomas", "dave": "david", "dan": "daniel", "matt": "matthew",
    "nick": "nicholas", "tony": "anthony", "joe": "joseph", "ben": "benjamin", "sam": "samuel",
    "alex": "alexander", "andy": "andrew", "drew": "andrew", "steve": "steven", "jeff": "jeffrey",
    "greg": "gregory", "kate": "katherine", "katie": "katherine", "liz": "elizabeth", "beth": "elizabeth",
    "jen": "jennifer", "jenny": "jennifer", "meg": "margaret", "pat": "patrick", "ed": "edward",
    "ted": "theodore", "rick": "richard", "rich": "richard", "dick": "richard", "chuck": "charles",
    "charlie": "charles", "jon": "jonathan", "zach": "zachary", "josh": "joshua", "tim": "timothy",
}

# Which source's fact wins when the same person turns up twice. A web find
# ("spoke about swarm autonomy on the X podcast") says more than a team
# page ("is the CTO"); something the student wrote himself beats both.
SOURCE_RANK = {"hunter": 0, "team_page": 0, "web": 1, "manual": 2}


def same_first_name(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b or NICKNAMES.get(a, a) == NICKNAMES.get(b, b):
        return True
    short, long_ = sorted((a, b), key=len)
    # An initial ("j" / "jane"), or a shortening of at least three letters.
    return long_.startswith(short) and (len(short) == 1 or len(short) >= 3)


def same_person(name_a: str, name_b: str) -> bool:
    first_a, last_a = name_parts(name_a)
    first_b, last_b = name_parts(name_b)
    if not last_a or last_a != last_b:
        return False
    return same_first_name(first_a, first_b)


def find_existing(conn, company_id: int, name: str):
    for contact in db.list_contacts(conn, company_id=company_id):
        if same_person(contact.name, name):
            return contact
    return None


def store_contact(conn, contact: Contact) -> tuple[Contact, bool]:
    """Insert `contact`, or merge it into the same person already on file
    at that company. Returns (the stored contact, was_new)."""
    existing = find_existing(conn, contact.company_id, contact.name)
    if existing is None:
        contact.id = db.insert_contact(conn, contact)
        return contact, True

    # A fact only ever moves together with the URL it was read from.
    better_source = SOURCE_RANK.get(contact.source_kind, 0) > SOURCE_RANK.get(existing.source_kind, 0)
    if contact.fact and (not existing.fact or better_source):
        db.set_contact_fact(conn, existing.id, contact.fact, contact.source_url, contact.source_kind)
    if contact.email and not existing.email:
        db.set_contact_email(conn, existing.id, contact.email, contact.email_source_url or contact.source_url)
    if contact.linkedin_url and not existing.linkedin_url:
        db.set_contact_linkedin_url(conn, existing.id, contact.linkedin_url)
    return db.get_contact(conn, existing.id), False


def merge_existing_duplicates(conn) -> int:
    """Fold together people who are already on file twice at one company
    (found before deduplication existed). The older row is kept, and the
    duplicate's messages move to it. Returns how many rows were removed."""
    removed = 0
    for company in db.list_companies(conn):
        kept: list[Contact] = []
        for contact in sorted(db.list_contacts(conn, company_id=company.id), key=lambda c: c.id):
            original = next((k for k in kept if same_person(k.name, contact.name)), None)
            if original is None:
                kept.append(contact)
                continue
            db.delete_contact_into(conn, contact.id, original.id)
            store_contact(conn, contact)  # folds its fact/email into the one kept
            removed += 1
    return removed
