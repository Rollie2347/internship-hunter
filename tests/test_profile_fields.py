from internship_hunter.apply_assist import profile_fields


ABOUT_ME_FIXTURE = """
**Name:** Jane Q. Doe
**Home:** Wisconsin (262 area code). Targets: Wisconsin, Colorado, Virginia.
**Contact:** jane@example.com · janedoe.dev · github.com/janedoe

## Projects
- AI Receptionist. Live demo phone number: 414-441-9149.
"""

RESUME_FIXTURE = """
Jane Q. Doe
United States | 262-555-1234
jane@example.com | github.com/janedoe
"""


def test_build_applicant_info_parses_name():
    info = profile_fields.build_applicant_info(ABOUT_ME_FIXTURE, RESUME_FIXTURE)
    assert info.first_name == "Jane"
    assert info.last_name == "Doe"
    assert info.full_name == "Jane Q. Doe"


def test_build_applicant_info_parses_email_and_github():
    info = profile_fields.build_applicant_info(ABOUT_ME_FIXTURE, RESUME_FIXTURE)
    assert info.email == "jane@example.com"
    assert info.github_url == "https://github.com/janedoe"


def test_build_applicant_info_parses_portfolio_from_contact_line():
    info = profile_fields.build_applicant_info(ABOUT_ME_FIXTURE, RESUME_FIXTURE)
    assert info.portfolio_url == "https://janedoe.dev"


def test_build_applicant_info_parses_location():
    info = profile_fields.build_applicant_info(ABOUT_ME_FIXTURE, RESUME_FIXTURE)
    assert info.location == "Wisconsin"


def test_build_applicant_info_prefers_resume_phone_over_demo_phone_in_projects():
    # Regression: about_me.md's Projects section describes a demo AI
    # receptionist with its OWN phone number (414-441-9149). A naive search
    # of the combined text picked that up instead of the real contact
    # number from resume.txt's header (262-555-1234). Order matters.
    info = profile_fields.build_applicant_info(ABOUT_ME_FIXTURE, RESUME_FIXTURE)
    assert info.phone == "262-555-1234"
    assert info.phone != "414-441-9149"


def test_build_applicant_info_falls_back_to_about_me_phone_if_resume_has_none():
    # A fixture with no demo-phone-in-Projects confusion, isolating the
    # "resume has nothing, fall back to about_me" path specifically.
    about_me_clean = "**Name:** Jane Doe\n**Phone:** 555-000-1111\n"
    info = profile_fields.build_applicant_info(about_me_clean, resume_text="")
    assert info.phone == "555-000-1111"


def test_build_applicant_info_handles_missing_fields_gracefully():
    info = profile_fields.build_applicant_info("No structured data here.", "")
    assert info.email == ""
    assert info.phone == ""
    assert info.github_url == ""
    assert info.first_name == ""
