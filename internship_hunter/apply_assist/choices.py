"""Standing answers for the dropdown / radio-button questions that show up
on nearly every application ("Are you legally authorized to work in the
US?", "Will you require sponsorship?", "Country").

These are decided by fixed rules, never by the model: each one is a legal
or factual statement about the student, so it has to come out the same,
true way every time. A rule only fires on phrasings whose yes/no direction
is unambiguous; anything else is left for him. Every answer picked here is
shown on the Telegram card before he approves, and he still reviews the
real form and presses Submit himself.

Facts the default rules rely on (all from profile/about_me.md): US citizen,
15 years old, no security clearance, never employed by these companies,
still in high school (class of 2029), willing to work on-site in Colorado
or Virginia.

His own answers live in profile/my_answers.md (see my_answers.py) and are
checked before the defaults -- that's where personal choices such as the
optional demographic questions belong, since nobody should guess those.
"""

from __future__ import annotations

import re
from typing import Optional

from internship_hunter import config

YES = ["Yes"]
NO = ["No"]
LEAVE: list[str] = []  # an explicit "never answer this for him"

# First matching rule wins. A rule matches when the question contains one
# of `any`, all of `all`, and none of `none` (all lowercase). `exact` means
# the whole label, minus its required-field asterisk, must equal the text.
DEFAULT_RULES: list[dict] = [
    # Whether a 15-year-old can obtain a clearance is not ours to assert.
    {"all": ["clearance"], "any": ["eligib", "obtain", "able to", "willing"], "answers": LEAVE},
    {"any": ["clearance"], "answers": ["No", "None", "No clearance", "N/A", "Not applicable"]},
    {"any": ["export control", "itar", "u.s. person", "us person"], "answers": LEAVE},
    {"any": ["sponsorship", "sponsor"], "none": ["without"], "answers": NO},
    {
        "any": ["authorized to work", "legally authorized", "authorization to work", "eligible to work",
                "work authorization", "legally eligible", "legal right to work"],
        "answers": ["Yes", "I am authorized", "U.S. Citizen", "US Citizen"],
    },
    {"any": ["at least 18", "18 years of age or older", "18 or older", "over 18", "over the age of 18"],
     "none": ["under"], "answers": NO},
    {"exact": ["country"], "answers": ["United States", "United States of America", "USA", "US"]},
    {"exact": ["degree"], "answers": ["High School", "High School Diploma"]},
    {"any": ["non-compete", "noncompete", "non compete"], "answers": NO},
    {"any": ["current or former", "have you worked for", "previously worked", "previously been employed",
             "have you ever worked", "have you ever been employed"], "answers": NO},
    {"any": ["how did you hear"], "answers": ["Company Website", "Careers Page", "Company Careers Page", "Website", "Other"]},
    {"all": ["are you"], "any": ["willing to relocate", "in-person", "in person", "on-site", "onsite", "hybrid"],
     "answers": YES},
]


def load_user_rules() -> list[dict]:
    """The student's own answers from profile/my_answers.md as rules, or []
    if the file can't be read (a typo there must not stop applications)."""
    from internship_hunter.apply_assist import my_answers

    try:
        return my_answers.rules()
    except (OSError, ValueError):
        return []


LOCATION_CHOICE_WORDS = (
    "location preference", "preferred location", "preferred office", "office preference",
    "which office", "which location", "top location", "desired location", "work location",
)


def location_candidates(question: str, posting_location: str) -> list[str]:
    """For "which office do you prefer?" questions: this posting's own
    Colorado/Virginia offices, in the wordings a form might list them
    ("Broomfield, Colorado, United States", "Broomfield, CO", "Broomfield")."""
    from internship_hunter.scanner import filters

    if not any(word in _normalize(question) for word in LOCATION_CHOICE_WORDS):
        return []
    candidates: list[str] = []
    for office in filters.offices_in_preferred_states(posting_location):
        city = office.split(",")[0].strip()
        for wording in (office, re.sub(r",\s*United States.*$", "", office), city):
            if wording and wording not in candidates:
                candidates.append(wording)
    return candidates


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _bare_label(question: str) -> str:
    return _normalize(question).rstrip("*✱ ").strip()


def rule_matches(rule: dict, question: str) -> bool:
    q = _normalize(question)
    if "exact" in rule:
        return _bare_label(question) in rule["exact"]
    if any(word in q for word in rule.get("none", [])):
        return False
    if not all(word in q for word in rule.get("all", [])):
        return False
    return any(word in q for word in rule["any"]) if rule.get("any") else bool(rule.get("all"))


def candidates_for(question: str, rules: Optional[list[dict]] = None, posting_location: str = "") -> list[str]:
    """Acceptable answers for this question, best first -- or [] to leave
    it for him. `rules` defaults to his own answers followed by the defaults."""
    for rule in (load_user_rules() + DEFAULT_RULES) if rules is None else rules:
        if rule_matches(rule, question):
            return list(rule["answers"])
    return location_candidates(question, posting_location)


def pick_option(options: list[str], candidates: list[str]) -> Optional[str]:
    """The option on the form that means one of our acceptable answers: an
    exact match first, else an option that begins with it as a whole word
    ("Yes, I am authorized" for "Yes" -- but never "Not sure" for "No")."""
    for candidate in candidates:
        wanted = _normalize(candidate)
        for option in options:
            if _normalize(option) == wanted:
                return option
        for option in options:
            if re.match(rf"{re.escape(wanted)}\b", _normalize(option)):
                return option
    return None


def plan_choices(
    questions: list[dict], rules: Optional[list[dict]] = None, posting_location: str = ""
) -> tuple[dict[str, str], list[str]]:
    """Preview for the Telegram card. `questions` come from playwright_fill.
    extract_choice_questions. Returns (question -> answer that will be
    selected, questions left for him). A search-style dropdown doesn't list
    its options until it's opened, so its preview is the answer that will
    be looked for."""
    planned, left = {}, []
    rules = (load_user_rules() + DEFAULT_RULES) if rules is None else rules
    for q in questions:
        question = q["question"]
        if not question or question in planned or question in left:
            continue
        candidates = candidates_for(question, rules, posting_location)
        if q.get("options") is None:
            picked = candidates[0] if candidates else None
        else:
            picked = pick_option(q["options"], candidates)
        if picked:
            planned[question] = picked
        else:
            left.append(question)
    return planned, left
