from pathlib import Path

from internship_hunter.apply_assist import answers, playwright_fill
from internship_hunter.apply_assist.answers import DraftedAnswer

FIELDS = [
    ("First Name*", "text"), ("Email*", "email"), ("Resume/CV*", "file"),
    ("Why do you want to work at Foo?", "textarea"), ("What programming languages do you know?", "text"),
    ("Additional information", "textarea"),
    ("Gender", "select"), ("Are you a veteran?", "select"), ("Do you require visa sponsorship?", "text"),
    ("Will you now or in the future require a security clearance?", "textarea"),
    ("LinkedIn Profile", "text"), ("Are you at least 18 years of age?", "text"), ("Desired salary", "text"),
    ("Is this role a good fit?", "select"),
    # Lifted from a live Palantir/Lever form: answer options and a signature block.
    ("Spanish (SPA)", "checkbox"), ("Yes", "radio"), ("No", "radio"), ("Name", "text"), ("Date", "text"),
]


def test_sort_questions_never_drafts_eeo_legal_pay_or_linkedin():
    to_draft, left = answers.sort_questions(FIELDS)
    assert to_draft == [
        "Why do you want to work at Foo?", "What programming languages do you know?", "Additional information",
    ]
    assert "Gender" in left and "Desired salary" in left and "LinkedIn Profile" in left
    assert "Are you at least 18 years of age?" in left
    assert "Will you now or in the future require a security clearance?" in left
    # Fields the allow-list already fills are in neither bucket.
    assert "First Name*" not in to_draft + left


def test_sort_questions_never_types_a_signature_or_treats_options_as_questions():
    to_draft, left = answers.sort_questions(FIELDS)
    assert "Name" in left and "Date" in left  # signature block: his to sign
    assert "Is this role a good fit?" in left  # a dropdown, even though it's phrased as a question
    assert not {"Spanish (SPA)", "Yes", "No"} & set(to_draft + left)


def test_keep_valid_answers_drops_unasked_and_empty():
    drafted = [
        DraftedAnswer(question="Why us?", answer="  Real answer.  "),
        DraftedAnswer(question="Gender", answer="never asked"),
        DraftedAnswer(question="Anything else?", answer="   "),
    ]
    assert answers.keep_valid_answers(drafted, ["Why us?", "Anything else?"]) == {"Why us?": "Real answer."}


def test_draft_answers_makes_no_api_call_when_nothing_is_draftable():
    class ExplodingClient:
        @property
        def messages(self):
            raise AssertionError("should not be called")

    drafted, left = answers.draft_answers(ExplodingClient(), "", "", None, None, [("First Name*", "text"), ("Gender", "select")])
    assert drafted == {} and left == ["Gender"]


def test_prompt_demands_honesty_about_age():
    assert "15-year-old high school student" in answers.SYSTEM_PROMPT
    assert "Never invent" in answers.SYSTEM_PROMPT


def test_looks_like_confirmation():
    assert playwright_fill.looks_like_confirmation("https://boards.greenhouse.io/foo/jobs/1/confirmation", "")
    assert playwright_fill.looks_like_confirmation("https://jobs.lever.co/foo/abc/thanks?x=1", "")
    assert playwright_fill.looks_like_confirmation("https://x.example/apply", "Thank you for applying to Foo!")
    assert not playwright_fill.looks_like_confirmation("https://jobs.lever.co/foo/abc/apply", "Submit application")


def test_bot_and_queue_never_click_or_send():
    # CLAUDE.md constraints 4 and 5: nothing in the approval flow may click
    # a page element or send an email. Same source-grep guarantee as
    # test_playwright_fill.test_source_never_calls_click.
    root = Path(answers.__file__).resolve().parent.parent
    for relative in ("approvals/bot.py", "approvals/queue.py", "apply_assist/answers.py", "drafting/batch.py"):
        source = (root / relative).read_text(encoding="utf-8")
        assert ".click(" not in source and ".press(" not in source
        assert ".send(" not in source and "messages().send" not in source
