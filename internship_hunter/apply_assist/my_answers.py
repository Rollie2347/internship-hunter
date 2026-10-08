"""profile/my_answers.md -- the student's own answers to application
questions, built up over time so each form needs less of him.

It grows three ways:
  1. A starter list of things nearly every form asks (school, graduation
     date, city, the optional demographic questions). He fills in the ones
     he wants answered for him.
  2. When a form has a question nothing can answer yet, the bot adds it to
     the file with its options listed, so he can answer it once.
  3. When he answers a dropdown or radio question himself in the browser,
     the bot records what he picked (see playwright_fill.wait_until_closed)
     and uses it the next time that exact question comes up.

An entry looks like:

    ### Will you be returning to school after the internship?
    seen on: Anduril Industries
    options: Yes | No
    answer: Yes

A blank `answer:` means "keep leaving this one to me". Starter entries
carry an `id:` line that ties them to the matching rule in STANDARD below;
entries collected from forms have none and match that exact question only,
so an answer can never leak onto a differently-worded question.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from internship_hunter import config

HEADER = """# My answers for application forms

The bot fills these in for me. Rules of the file:
- Type after `answer:`. Leave it empty to keep answering that question myself.
- For a dropdown, use the wording of the option I want. Several acceptable
  wordings can be separated with ` | ` (the first one a form offers is used).
- Everything here must be true. Each application card in Telegram shows what
  will be selected before I approve it.
- New questions the bot couldn't answer get added at the bottom, and so do
  answers it saw me pick in the browser (marked "learned from").
"""

# Starter questions: id -> (question shown in the file, how it matches form labels).
# "exact" compares the whole label (minus the required-field asterisk);
# "any"/"none" are words the label must / must not contain.
STANDARD: dict[str, tuple[str, dict]] = {
    "school": ("What school do you attend? (the exact name to put on applications)",
               {"exact": ["school", "school name", "university", "college/university", "school or university"]}),
    "discipline": ("What should go under Discipline / Major / Field of study?",
                   {"exact": ["discipline", "major", "field of study"]}),
    "grad_month": ("Which month do you graduate high school?",
                   {"exact": ["end date month", "graduation month"]}),
    "grad_year": ("Which year do you graduate high school?",
                  {"exact": ["end date year", "graduation year"]}),
    "gpa": ("GPA (leave empty if you would rather not share it)", {"any": ["gpa"]}),
    "city": ("City you live in", {"exact": ["city", "please provide your city", "current city"]}),
    "state": ("State you live in", {"exact": ["state", "please select your state", "state/province", "current state"]}),
    "zip": ("Zip code", {"any": ["zip code", "postal code"]}),
    "start_date": ("Earliest date you can start",
                   {"any": ["start date", "available to start", "earliest you can start"]}),
    "returning": ("Will you return to school after the internship? (Yes / No)", {"any": ["returning to school"]}),
    "pay": ("Desired pay, for forms that insist on a number", {"any": ["salary", "desired pay", "pay expectation", "compensation expectation"]}),
    "gender": ("Gender (optional on forms; e.g. Male, Female, Decline To Self Identify)",
               {"any": ["gender"], "none": ["transgender"]}),
    "hispanic": ("Are you Hispanic/Latino? (optional; Yes, No, Decline To Self Identify)", {"any": ["hispanic", "latino"]}),
    "race": ("Race / ethnicity (optional)", {"any": ["race", "racial", "ethnic"], "none": ["hispanic", "latino"]}),
    "veteran": ("Veteran status (optional; e.g. I am not a protected veteran)", {"any": ["veteran"]}),
    "disability": ("Disability status (optional)", {"any": ["disability"]}),
}
PREFILLED = {"grad_year": "2029"}  # about_me.md: "high school class of 2029"

FORMS_SECTION = "## Questions from application forms"
ABOUT_SECTION = "## About me"

# Never collected or learned: not real questions, or answers that go stale
# or that only he may give each time (signatures, consent).
NEVER_ASK = ("linkedin", "attach", "enter manually", "signature", "consent", "agree", "acknowledge", "certify", "captcha")
NEVER_ASK_EXACT = ("name", "date", "legal name", "please provide your legal name", "yes", "no", "other")
PLACEHOLDERS = ("", "select", "select...", "select…", "please select", "choose", "--", "-")


@dataclass
class Entry:
    question: str
    answer: str = ""
    id: str = ""
    options: str = ""
    seen_on: str = ""
    learned_from: str = ""
    extra: list[str] = field(default_factory=list)


def _bare(question: str) -> str:
    return re.sub(r"\s+", " ", question or "").strip().lower().rstrip("*✱ ").strip()


def starter_entries() -> list[Entry]:
    return [Entry(question=text, id=key, answer=PREFILLED.get(key, "")) for key, (text, _) in STANDARD.items()]


def parse(text: str) -> list[Entry]:
    entries: list[Entry] = []
    current: Optional[Entry] = None
    for line in text.splitlines():
        if line.startswith("### "):
            current = Entry(question=line[4:].strip())
            entries.append(current)
        elif line.startswith("#"):
            current = None
        elif current is not None and ":" in line:
            key, _, value = line.partition(":")
            key, value = key.strip().lower(), value.strip()
            if key == "answer":
                current.answer = value
            elif key == "id":
                current.id = value
            elif key == "options":
                current.options = value
            elif key == "seen on":
                current.seen_on = value
            elif key == "learned from":
                current.learned_from = value
    return entries


def render(entries: list[Entry]) -> str:
    def block(entry: Entry) -> list[str]:
        lines = [f"### {entry.question}"]
        if entry.id:
            lines.append(f"id: {entry.id}")
        if entry.seen_on:
            lines.append(f"seen on: {entry.seen_on}")
        if entry.options:
            lines.append(f"options: {entry.options}")
        if entry.learned_from:
            lines.append(f"learned from: {entry.learned_from}")
        lines += [f"answer: {entry.answer}".rstrip(), ""]
        return lines

    lines = [HEADER, ABOUT_SECTION, ""]
    for entry in (e for e in entries if e.id):
        lines += block(entry)
    lines += [FORMS_SECTION, ""]
    for entry in (e for e in entries if not e.id):
        lines += block(entry)
    return "\n".join(lines).rstrip() + "\n"


def load() -> list[Entry]:
    """Entries from the file, creating it with the starter questions the
    first time. Starter questions added in a later version are appended."""
    path = config.MY_ANSWERS_PATH
    entries = parse(path.read_text(encoding="utf-8")) if path.exists() else []
    have = {e.id for e in entries if e.id}
    missing = [e for e in starter_entries() if e.id not in have]
    if missing or not path.exists():
        entries = [e for e in entries if e.id] + missing + [e for e in entries if not e.id]
        save(entries)
    return entries


def save(entries: list[Entry]) -> None:
    config.MY_ANSWERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.MY_ANSWERS_PATH.write_text(render(entries), encoding="utf-8")


def _answers(entry: Entry) -> list[str]:
    return [part.strip() for part in entry.answer.split("|") if part.strip()]


def rules(entries: Optional[list[Entry]] = None) -> list[dict]:
    """His answered entries as choices.py rules: exact form questions first
    (most specific), then the starter ones."""
    entries = load() if entries is None else entries
    answered = [e for e in entries if _answers(e)]
    out = [{"exact": [_bare(e.question)], "answers": _answers(e)} for e in answered if not e.id]
    out += [{**STANDARD[e.id][1], "answers": _answers(e)} for e in answered if e.id in STANDARD]
    return out


def _covered_by_starter(question: str) -> bool:
    from internship_hunter.apply_assist import choices

    return any(choices.rule_matches(spec, question) for _, spec in STANDARD.values())


def worth_asking(question: str) -> bool:
    bare = _bare(question)
    return bool(bare) and bare not in NEVER_ASK_EXACT and not any(word in bare for word in NEVER_ASK)


def add_questions(items: list[tuple[str, Optional[list[str]]]], company_name: str) -> list[str]:
    """Append form questions nobody can answer yet, so he can answer them
    once in the file. Returns the questions actually added."""
    entries = load()
    known = {_bare(e.question) for e in entries}
    added = []
    for question, options in items:
        if not worth_asking(question) or _bare(question) in known or _covered_by_starter(question):
            continue
        shown = " | ".join(o for o in (options or []) if _bare(o) not in PLACEHOLDERS)
        entries.append(Entry(question=question.strip(), options=shown, seen_on=company_name))
        known.add(_bare(question))
        added.append(question)
    if added:
        save(entries)
    return added


def record_answers(observed: dict[str, str], company_name: str, has_answer: Callable[[str], bool]) -> list[str]:
    """Remember what he picked in the browser for questions that had no
    standing answer. Returns "question -> answer" lines for what was learned."""
    entries = load()
    by_question = {_bare(e.question): e for e in entries}
    learned = []
    for question, value in observed.items():
        value = (value or "").strip()
        if _bare(value) in PLACEHOLDERS or not worth_asking(question) or has_answer(question):
            continue
        starter = next((e for e in entries if e.id in STANDARD and _matches_starter(e.id, question)), None)
        entry = starter or by_question.get(_bare(question))
        if entry is None:
            entry = Entry(question=question.strip(), seen_on=company_name)
            entries.append(entry)
            by_question[_bare(question)] = entry
        if entry.answer:
            continue  # he already wrote an answer here; never overwrite his own words
        entry.answer = value
        entry.learned_from = f"what you picked on the {company_name} form"
        learned.append(f"{question.strip()[:60]} -> {value}")
    if learned:
        save(entries)
    return learned


def _matches_starter(starter_id: str, question: str) -> bool:
    from internship_hunter.apply_assist import choices

    return choices.rule_matches(STANDARD[starter_id][1], question)
