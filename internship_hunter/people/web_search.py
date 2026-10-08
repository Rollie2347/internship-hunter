"""A second source of people: what's been written ABOUT a company elsewhere
-- blog posts, press releases, funding announcements, podcasts, conference
talks. A team page gives a name and a title; these give the specific thing
a good note opens with ("spoke about swarm autonomy on the X podcast").

It works in two steps, so nothing a model merely remembers or guesses can
reach the database:
  1. find_pages() asks Claude, with Anthropic's web search tool, which
     pages name this company's founders, CTO and engineers. Only URLs the
     search tool itself returned are kept -- a URL the model typed that
     isn't among the real results is dropped.
  2. Each of those pages is then downloaded by our own code
     (people_finder.fetch_page_text) and people are extracted from that
     text. The stored source_url is the page we read, and a person whose
     name isn't literally in it is thrown away.

LinkedIn is blocked at both steps: the search tool is told not to search
it, and fetch_page_text refuses any linkedin.com URL (CLAUDE.md constraint 4).

Cost: unlike the team-page reader this is not pennies. One company is one
search request (up to WEB_SEARCH_MAX_USES searches, billed per search, plus
the result text as input tokens) and one small extraction call per page. So
each company is only ever searched once, and the bot never runs this by
itself unless WEB_PEOPLE_SEARCH_PER_DAY is set in .env.
"""

from __future__ import annotations

import re

from internship_hunter import anthropic_client, config, db
from internship_hunter.models import Company, Contact
from internship_hunter.people import dedupe, people_finder
from internship_hunter.people.email_finder import _letters, company_key, name_parts

MAX_ARTICLE_CHARS = 20000
MAX_CONTINUATIONS = 3
URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")

SEARCH_PROMPT = """Find web pages that name specific people who work at {name} ({website}), a company \
that builds: {what}.

I'm looking for its founders, CTO, and engineering leads or engineers, in places like the company's \
blog, press releases, funding announcements, podcast episodes and conference talks -- pages that say \
something specific a person did, built or said, not just a list of names.

Search, then finish with the {pages} best page URLs, one per line, best first, and nothing after \
them. Only list URLs that appeared in your search results. If you find nothing useful, say so and \
list no URLs."""

EXTRACT_PROMPT = """You are helping a 15-year-old high school student find real people at {name} to \
write a short, honest note to. You will be given the visible text of one web page about the company \
(an article, announcement, podcast page or talk listing). Follow these rules exactly:

1. ONLY extract a person if the text itself says they work at or founded {name}, and states their \
name AND role. Investors, customers, journalists, podcast hosts and people at other companies are \
not who we want -- leave them out.
2. Prefer founders, CTOs, engineering leads and engineers. At most 5 people.
3. For each person write one short "fact": the single most specific thing THIS text says they did, \
built or said (for example "spoke about swarm autonomy on the X podcast"). It must be something a \
reader could find in the text. Never add anything from your own knowledge.
4. Leave email blank unless that literal address appears in the text.
5. If the text names nobody at {name} with a role, return an empty list. That is a normal answer."""


def is_linkedin(url: str) -> bool:
    return "linkedin.com" in (url or "").lower()


def search_tool() -> dict:
    return {
        "type": "web_search_20260209",
        "name": "web_search",
        "max_uses": config.WEB_SEARCH_MAX_USES,
        "blocked_domains": list(config.WEB_SEARCH_BLOCKED_DOMAINS),
    }


def returned_urls(content) -> list[str]:
    """Every URL the search tool actually returned, in order. A failed
    search comes back as an error object instead of a list -- skipped."""
    urls: list[str] = []
    for block in content:
        if getattr(block, "type", "") != "web_search_tool_result":
            continue
        results = getattr(block, "content", None)
        if not isinstance(results, list):
            continue
        for result in results:
            url = getattr(result, "url", None)
            if url and url not in urls:
                urls.append(url)
    return urls


def recommended_urls(content) -> list[str]:
    """URLs the model wrote in its answer, in order."""
    urls: list[str] = []
    for block in content:
        if getattr(block, "type", "") != "text":
            continue
        for url in URL_RE.findall(getattr(block, "text", "") or ""):
            url = url.rstrip(".,;")
            if url not in urls:
                urls.append(url)
    return urls


def choose_pages(recommended: list[str], returned: list[str], skip: tuple = (), limit: int | None = None) -> list[str]:
    """The pages to read: the model's picks, but only those the search tool
    really returned -- then, if it picked none, the top results. Never
    LinkedIn, and never a page already read (`skip`)."""
    limit = limit if limit is not None else config.WEB_PAGES_PER_COMPANY
    real = set(returned)
    skip_set = {u.rstrip("/") for u in skip if u}
    ordered = [u for u in recommended if u in real] or returned
    chosen: list[str] = []
    for url in ordered:
        if is_linkedin(url) or url.rstrip("/") in skip_set or url in chosen:
            continue
        chosen.append(url)
    return chosen[:limit]


def find_pages(client, company: Company) -> list[str]:
    """Step 1: one search request. Returns the URLs worth reading."""
    prompt = SEARCH_PROMPT.format(
        name=company.name, website=company.website or "no website on file",
        what=company.what_they_build or "not recorded", pages=config.WEB_PAGES_PER_COMPANY,
    )
    messages = [{"role": "user", "content": prompt}]
    content: list = []
    for _ in range(MAX_CONTINUATIONS + 1):
        response = client.messages.create(
            model=config.PEOPLE_FINDER_MODEL, max_tokens=config.MAX_OUTPUT_TOKENS, tools=[search_tool()], messages=messages,
        )
        content += list(response.content)
        if response.stop_reason != "pause_turn":
            break
        # The server paused a long search turn; sending its own content back resumes it.
        messages = [{"role": "user", "content": prompt}, {"role": "assistant", "content": response.content}]
    return choose_pages(recommended_urls(content), returned_urls(content), skip=(company.team_url,))


def extract_people(client, company: Company, url: str, page_text: str) -> list[people_finder.ExtractedPerson]:
    response = client.messages.parse(
        model=config.PEOPLE_FINDER_MODEL,
        max_tokens=config.MAX_OUTPUT_TOKENS,
        system=EXTRACT_PROMPT.format(name=company.name),
        messages=[{"role": "user", "content": people_finder.build_user_content(company.name, url, page_text)}],
        output_format=people_finder.ExtractionResult,
    )
    return anthropic_client.parsed(response).people[: config.MAX_CONTACTS_PER_COMPANY]


def named_in_text(person_name: str, page_text: str) -> bool:
    """True only if the person's last name is literally on the page."""
    _, last = name_parts(person_name)
    return bool(last) and last in _letters(page_text)


def people_from_page(client, company: Company, url: str, fetch=None) -> list[Contact]:
    """Step 2 for one page: download it ourselves, extract, and keep only
    people the page really names. The source is the URL we fetched."""
    page_text = (fetch or people_finder.fetch_page_text)(url, MAX_ARTICLE_CHARS)
    # A page that never mentions the company is about someone else.
    if not page_text or company_key(company.name) not in _letters(page_text):
        return []
    people = [p for p in extract_people(client, company, url, page_text) if named_in_text(p.name, page_text)]
    contacts = people_finder.to_contacts(people, company.id, url)
    for contact in contacts:
        contact.source_kind = "web"
    return contacts


def run_for_company(client, conn, company: Company, fetch=None) -> list[tuple[Contact, bool]]:
    """Search for one company and store what's found, merged with anyone
    already on file. Returns [(contact, was_new)]."""
    # Recorded first, so a company is never paid for twice.
    db.mark_web_people_checked(conn, company.id)
    stored: list[tuple[Contact, bool]] = []
    for url in find_pages(client, company):
        for contact in people_from_page(client, company, url, fetch):
            stored.append(dedupe.store_contact(conn, contact))
    return stored


def companies_to_search(conn, any_state: bool = False) -> list[Company]:
    """Tier-1 companies (defense startups) never searched before -- based
    in Colorado/Virginia unless any_state."""
    return [
        c for c in db.list_companies_never_web_searched(conn)
        if c.priority_tier == 1 and (any_state or c.state in config.PREFERRED_STATES)
    ]
