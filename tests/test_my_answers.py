from internship_hunter import config
from internship_hunter.apply_assist import choices, my_answers


def test_file_is_created_with_starter_questions_and_no_personal_answers():
    entries = my_answers.load()
    assert config.MY_ANSWERS_PATH.exists()
    by_id = {e.id: e for e in entries}
    assert by_id["grad_year"].answer == "2029"
    assert by_id["gender"].answer == "" and by_id["school"].answer == ""
    assert my_answers.rules(entries) == [{"exact": ["end date year", "graduation year"], "answers": ["2029"]}]


def test_what_he_types_in_the_file_becomes_a_standing_answer():
    entries = my_answers.load()
    for entry in entries:
        if entry.id == "school":
            entry.answer = "Example Online High School"
        if entry.id == "gender":
            entry.answer = "Decline To Self Identify | Decline to self-identify"
    my_answers.save(entries)

    assert choices.candidates_for("School*") == ["Example Online High School"]
    assert choices.candidates_for("Gender") == ["Decline To Self Identify", "Decline to self-identify"]
    assert choices.candidates_for("Do you identify as transgender?") == []
    # Round trip: nothing is lost by saving and re-reading.
    assert my_answers.parse(my_answers.render(my_answers.load())) == my_answers.load()


def test_new_form_questions_are_asked_once_with_their_options():
    added = my_answers.add_questions([
        ("Will you be returning to school after the internship?*", ["Select...", "Yes", "No"]),
        ("What is your favorite editor?", ["Vim", "Emacs"]),
        ("LinkedIn Profile", None),
        ("Name", None),
        ("School*", None),
    ], "Foo Corp")
    assert added == ["What is your favorite editor?"]   # the rest are starter questions or never asked
    entry = next(e for e in my_answers.load() if e.question == "What is your favorite editor?")
    assert entry.options == "Vim | Emacs" and entry.seen_on == "Foo Corp" and entry.answer == ""
    assert my_answers.add_questions([("What is your favorite editor?", None)], "Bar Inc") == []


def test_a_form_question_matches_only_that_exact_question():
    my_answers.add_questions([("Are you a U.S. person under ITAR?", ["Yes", "No"])], "Foo Corp")
    entries = my_answers.load()
    next(e for e in entries if e.question.startswith("Are you a U.S. person")).answer = "Yes"
    my_answers.save(entries)
    assert choices.candidates_for("Are you a U.S. person under ITAR?*") == ["Yes"]
    assert choices.candidates_for("Are you a foreign person under ITAR?") == []


def test_answers_he_picks_in_the_browser_are_remembered_but_never_overwrite_his_own():
    entries = my_answers.load()
    next(e for e in entries if e.id == "veteran").answer = "I am not a protected veteran"
    my_answers.save(entries)
    observed = {
        "Gender": "Male",
        "Veteran Status": "Something else",
        "Will this be your final internship before graduating?": "No",
        "Are you legally authorized to work in the United States?": "Yes",
        "School*": "Select...",
        "Name": "Rollie",
    }
    learned = my_answers.record_answers(
        observed, "Foo Corp", has_answer=lambda q: bool(choices.candidates_for(q)),
    )
    assert learned == ["Gender -> Male", "Will this be your final internship before graduating? -> No"]
    by_question = {e.question: e for e in my_answers.load()}
    assert next(e for e in my_answers.load() if e.id == "gender").answer == "Male"
    assert next(e for e in my_answers.load() if e.id == "veteran").answer == "I am not a protected veteran"
    assert by_question["Will this be your final internship before graduating?"].learned_from.endswith("Foo Corp form")
    assert choices.candidates_for("Will this be your final internship before graduating?") == ["No"]
