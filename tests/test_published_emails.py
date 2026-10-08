from internship_hunter.people import people_finder

HTML = """
<a href="mailto:Careers@foo-defense.com">Join us</a> press@foo-defense.com privacy@foo-defense.com
info@foo-defense.com jane.doe@foo-defense.com someone@gmail.com hello@other-company.com
<img src="logo@2x.png">
"""


def test_only_addresses_on_the_companys_own_domain_best_inbox_first():
    found = people_finder.find_published_emails(HTML, "https://www.foo-defense.com/")
    assert found == ["careers@foo-defense.com", "info@foo-defense.com", "jane.doe@foo-defense.com"]


def test_nothing_is_invented_when_the_page_publishes_no_address():
    assert people_finder.find_published_emails("<p>Contact us through the form.</p>", "https://foo-defense.com") == []


def test_company_domain_strips_scheme_and_www():
    assert people_finder.company_domain("https://www.foo-defense.com/careers") == "foo-defense.com"
    assert people_finder.company_domain("foo-defense.com") == "foo-defense.com"
