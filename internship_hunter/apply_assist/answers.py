"""Drafts answers to an application form's open-ended questions ("Why do
you want to work here?", a cover-letter box) from the student's real
profile, so the form is already written when he approves it.

Three layers keep this honest, same pattern as people_finder.py and
compose.py:
  1. sort_questions() decides in plain code -- not the model -- which
     labels may be drafted at all. Demographic/EEO, clearance, pay, legal
     yes/no and LinkedIn questions are never sent to the model.
  2. The prompt forbids inventing anything and tells the model to return an
     empty answer when the profile doesn't contain one.
  3. keep_valid_answers() throws away any answer whose question isn't
     word-for-word one we asked, so the model can't answer a field it
     wasn't given.
Nothing is submitted here: answers are shown on the Telegram card first,
typed into the form only after Approve, and the student still presses
Submit himself.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from internship_hunter import anthropic_client, config
from internship_hunter.apply_assist import field_map
from internship_hunter.models import Company, Posting

# Any label containing one of these is left for the student, always.
LEAVE_FOR_STUDENT_KEYWORDS = (
    # demographic / EEO self-identification
    "gender", "race", "ethnic", "hispanic", "latino", "veteran", "disability", "pronoun",
    "sexual orientation", "transgender", "self-identif",
    # legal / eligibility attestations -- he answers these himself, truthfully
    "clearance", "authorized to work", "authorization", "sponsorship", "visa", "citizen",
    "18 years", "at least 18", "over 18", "your age", "how old", "export control", "itar", "felony",
    "convicted", "background check", "non-compete", "agree", "consent", "acknowledge",
    "certify", "privacy", "terms",
    # things he doesn't have or shouldn't guess
    "linkedin", "salary", "compensation", "pay expectation", "current company",
    "current employer", "current title", "school", "university", "degree", "gpa",
    "graduation", "start date", "how did you hear", "referred", "referral",
)

# Upload-widget buttons that happen to be <label>s -- not fields at all.
WIDGET_LABELS = ("attach", "upload", "dropbox", "google drive", "enter manually", "paste")


class DraftedAnswer(BaseModel):
    question: str
    answer: str


class DraftedAnswers(BaseModel):
    answers: list[DraftedAnswer]


CHOICE_KINDS = ("checkbox", "radio")  # these labels are answer options, not questions
TYPEABLE_KINDS = ("text", "textarea")


def sort_questions(fields: list[tuple[str, str]], skip: tuple = ()) -> tuple[list[str], list[str]]:
    """Split a form's (label, kind) pairs -- see playwright_fill.
    extract_live_fields -- into (to_draft, left_for_student).

    Drafted: a big text box, or a one-line box whose label is phrased as a
    question. Everything else the student handles: dropdowns, anything on
    the keyword list above, and short one-line boxes like the "Name"/"Date"
    of a signature block, which must never be typed for him. Labels the
    allow-list in field_map already fills (name, email, ...) and individual
    checkbox/radio options are in neither list."""
    to_draft, left = [], []
    for label, kind in fields:
        lowered = label.lower()
        if field_map.classify_label(label) is not None or kind in CHOICE_KINDS or lowered.strip() in WIDGET_LABELS:
            continue
        if label in skip:  # already has a standing answer (choices.py / my_answers.md)
            continue
        blocked = any(kw in lowered for kw in LEAVE_FOR_STUDENT_KEYWORDS)
        open_ended = kind == "textarea" or (kind == "text" and "?" in label)
        bucket = to_draft if (open_ended and not blocked) else left
        if label not in bucket:
            bucket.append(label)
    return to_draft, left


SYSTEM_PROMPT = f"""You are helping a 15-year-old high school student fill in the open-ended \
text questions on a job application, using only his real profile below. You are given the \
exact label text of each question. Follow these rules exactly:

1. Use only facts stated in his profile and resume. Never invent or stretch experience, \
skills, numbers, schools, or links. Copy any URL character-for-character from the profile.
2. Never imply he is older than 15, in college, or a graduate. Where his age or availability \
is relevant to a question (cover letters, "tell us about yourself", "anything else"), say \
plainly that he is a 15-year-old high school student and include the Availability fact given \
below without changing its hours or dates.
3. If a label is not an open-ended question he can answer in his own words -- a yes/no or \
dropdown choice, a checkbox, a button, a section heading -- or his profile does not contain \
the answer, return an empty string for it. An empty answer is a normal, expected result; he \
fills those in himself.
4. Keep each answer under {config.MAX_ANSWER_WORDS} words, specific, and in his voice: direct, \
a little technical, no buzzwords, no exclamation marks.
5. Return every question exactly as given, character-for-character, paired with its answer."""


def build_user_content(profile_text: str, resume_text: str, company: Company, posting: Posting, questions: list[str]) -> str:
    numbered = "\n".join(f"{i}. {q}" for i, q in enumerate(questions, 1))
    return (
        f"=== His profile (about_me.md) ===\n{profile_text}\n\n"
        f"=== His resume ===\n{resume_text}\n\n"
        f"=== The role ===\nCompany: {company.name}\nWhat they build: {company.what_they_build}\n"
        f"Posting: {posting.title} ({posting.location})\n\n"
        f"=== Availability (use this fact, don't recompute it) ===\n{config.availability_statement()}\n\n"
        f"=== Questions on the form ===\n{numbered}"
    )


def keep_valid_answers(drafted: list[DraftedAnswer], questions: list[str]) -> dict[str, str]:
    """Only non-empty answers to questions we actually asked, keyed by the
    exact label text (which is what the form filler looks fields up by)."""
    asked = set(questions)
    return {d.question: d.answer.strip() for d in drafted if d.question in asked and d.answer.strip()}


def draft_answers(
    client,
    profile_text: str,
    resume_text: str,
    company: Company,
    posting: Posting,
    fields: list[tuple[str, str]],
    skip: tuple = (),
) -> tuple[dict[str, str], list[str]]:
    """Returns (answers by label, labels left for the student). Makes no
    API call at all when the form has nothing draftable. Labels in `skip`
    already have a standing answer and are left out of both."""
    to_draft, left = sort_questions(fields, skip)
    if not to_draft:
        return {}, left
    response = client.messages.parse(
        model=config.DRAFTING_MODEL,
        max_tokens=config.MAX_OUTPUT_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_user_content(profile_text, resume_text, company, posting, to_draft)}],
        output_format=DraftedAnswers,
    )
    answers = keep_valid_answers(anthropic_client.parsed(response).answers, to_draft)
    return answers, left + [q for q in to_draft if q not in answers]


def validate_answers(answers: dict[str, str]) -> list[str]:
    """Human-readable warnings shown on the card -- never blocks, since the
    student reviews every answer before approving."""
    warnings = []
    for question, answer in answers.items():
        words = len(answer.split())
        if words > config.MAX_ANSWER_WORDS:
            warnings.append(f'"{question[:40]}" answer is {words} words (target {config.MAX_ANSWER_WORDS}).')
    return warnings
