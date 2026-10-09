import pytest

from internship_hunter.drafting import compose
from internship_hunter.models import Company, Contact, Posting


def make_company(**overrides) -> Company:
    defaults = dict(
        name="Foo Corp",
        website="https://foo.example",
        state="VA",
        city="Arlington",
        stage="seed",
        what_they_build="Autonomous drone software",
        why_fit="Defense-tech software startup",
        careers_url="https://foo.example/careers",
        priority_tier=1,
    )
    defaults.update(overrides)
    return Company(**defaults)


def test_build_target_context_with_contact():
    company = make_company()
    contact = Contact(company_id=1, name="Jane Doe", title="CTO", source_url="https://foo.example/about", fact="Leads engineering.")
    context = compose.build_target_context(company, contact=contact)
    assert "Jane Doe" in context
    assert "CTO" in context
    assert "Leads engineering." in context
    assert "Autonomous drone software" in context


def test_build_target_context_with_posting():
    company = make_company()
    posting = Posting(company_id=1, external_id="1", title="Software Engineer Intern", location="Arlington, VA", url="https://foo.example/jobs/1", ats_source="greenhouse")
    context = compose.build_target_context(company, posting=posting)
    assert "Software Engineer Intern" in context
    assert "https://foo.example/jobs/1" in context


def test_build_target_context_with_neither_notes_general_intro():
    company = make_company()
    context = compose.build_target_context(company)
    assert "general introduction" in context.lower()


def test_build_user_content_includes_all_sections():
    content = compose.build_user_content("PROFILE_TEXT_MARKER", "RESUME_TEXT_MARKER", "TARGET_CONTEXT_MARKER", ask_type="referral")
    assert "PROFILE_TEXT_MARKER" in content
    assert "RESUME_TEXT_MARKER" in content
    assert "TARGET_CONTEXT_MARKER" in content
    assert "Background only" in content and "Availability (use this fact" not in content
    assert "referral" in content


def test_build_user_content_defaults_ask_type_to_auto():
    content = compose.build_user_content("p", "r", "t")
    assert "auto" in content


class FakeParseResponse:
    def __init__(self, draft):
        self.parsed_output = draft


class FakeMessages:
    def __init__(self, draft, capture):
        self._draft = draft
        self._capture = capture

    def parse(self, **kwargs):
        self._capture.update(kwargs)
        return FakeParseResponse(self._draft)


class FakeAnthropicClient:
    def __init__(self, draft):
        self.capture = {}
        self.messages = FakeMessages(draft, self.capture)


def test_compose_email_calls_claude_with_expected_model_and_system_prompt():
    fake_draft = compose.DraftEmail(subject="Quick question about your drone software", body="Hi, I'm 15...")
    client = FakeAnthropicClient(fake_draft)
    company = make_company()

    result = compose.compose_email(client, "profile text", "resume text", company)

    assert result == fake_draft
    assert client.capture["model"] == compose.config.DRAFTING_MODEL
    assert "150 words" in client.capture["system"]
    assert "15-year-old" in client.capture["system"]
    assert "internship so he can LEARN" in client.capture["system"]   # he asked for this
    # Also his: no work-hour talk in the email, and a mention that he has other projects.
    assert "Do NOT mention work-hour limits" in client.capture["system"]
    assert "he has built other projects too" in client.capture["system"]
    assert "Include the exact" not in client.capture["system"]
    assert client.capture["output_format"] is compose.DraftEmail


def test_compose_email_passes_through_ask_type():
    fake_draft = compose.DraftEmail(subject="x", body="Hi, I'm 15... http://x.com")
    client = FakeAnthropicClient(fake_draft)
    company = make_company()

    compose.compose_email(client, "profile", "resume", company, ask_type="referral")

    assert "referral" in client.capture["messages"][0]["content"]


def test_compose_email_rejects_invalid_ask_type():
    client = FakeAnthropicClient(compose.DraftEmail(subject="x", body="x"))
    company = make_company()
    with pytest.raises(ValueError):
        compose.compose_email(client, "profile", "resume", company, ask_type="not-a-real-type")


def test_validate_draft_flags_long_body():
    draft = compose.DraftEmail(subject="x", body=" ".join(["word"] * 200) + " I'm 15 see http://x.com")
    warnings = compose.validate_draft(draft)
    assert any("150-word" in w for w in warnings)


def test_validate_draft_flags_missing_age_mention():
    draft = compose.DraftEmail(subject="x", body="Hello, check out my project at http://x.com")
    warnings = compose.validate_draft(draft)
    assert any("age" in w.lower() for w in warnings)


def test_validate_draft_flags_missing_link():
    draft = compose.DraftEmail(subject="x", body="Hi, I'm 15 and interested in your work.")
    warnings = compose.validate_draft(draft)
    assert any("link" in w.lower() for w in warnings)


def test_validate_draft_passes_a_compliant_draft():
    draft = compose.DraftEmail(
        subject="x",
        body="Hi, I'm a 15-year-old high schooler. Check out my project: http://x.com. Can I send my resume?",
    )
    warnings = compose.validate_draft(draft)
    assert warnings == []


def test_build_user_content_includes_follow_up_context_when_given():
    content = compose.build_user_content("p", "r", "t", follow_up_context="FOLLOW_UP_MARKER")
    assert "FOLLOW_UP_MARKER" in content
    assert "Follow-up context" in content


def test_build_user_content_omits_follow_up_section_when_not_given():
    content = compose.build_user_content("p", "r", "t")
    assert "Follow-up context" not in content


def test_compose_email_passes_through_follow_up_context():
    fake_draft = compose.DraftEmail(subject="x", body="Hi, I'm 15... http://x.com")
    client = FakeAnthropicClient(fake_draft)
    company = make_company()

    compose.compose_email(client, "profile", "resume", company, follow_up_context="Sent 7 days ago, no reply.")

    assert "Sent 7 days ago, no reply." in client.capture["messages"][0]["content"]
