# Internship Hunter

A personal tool to help a 15-year-old high schooler find, and apply to, a
year-long tech/defense-tech internship in Virginia, Colorado, or Wisconsin.
See `CLAUDE.md` for the full rules this tool follows (honesty about age,
child-labor-law hour limits, no LinkedIn automation, human-reviewed outreach
only, etc.).

Built in phases -- see `C:\Users\rro\.claude\plans\rustling-inventing-petal.md`
for the full plan. **Phases 1-4 (target company list, job scanner, people finder, drafting) are done.**

## One-time setup (PowerShell)

```powershell
# From the internship-hunter folder:
cd C:\Users\rro\Documents\internship-hunter

# Create and activate a virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Create your real secrets file from the template, then edit it
Copy-Item .env.example .env
notepad .env
```

Fill in `profile/about_me.md` honestly and put your resume at
`profile/resume.pdf` -- Phase 4 (drafting) will refuse to write anything until
that's done, since it's not allowed to invent experience.

## Phase 1: Target company list

The database lives at `data/tracker.db` (created automatically, gitignored).

```powershell
# Load the curated starter list of ~20 real defense-tech/dual-use startups,
# larger defense-tech companies, strong tech companies, and government/lab
# programs with a presence in VA, CO, or WI:
python -m internship_hunter.companies.cli load-seed

# See everything:
python -m internship_hunter.companies.cli list

# Filter by tier (1 = early/mid-stage defense-tech & dual-use startup, per
# CLAUDE.md's priority order) or by state:
python -m internship_hunter.companies.cli list --tier 1
python -m internship_hunter.companies.cli list --state WI

# Full detail on one company:
python -m internship_hunter.companies.cli show "Anduril Industries"

# Add one by hand:
python -m internship_hunter.companies.cli add --name "Some Startup" `
    --website "https://example.com" --state VA --city Arlington `
    --stage seed --what "What they build" --why "Why it fits me" `
    --careers-url "https://example.com/careers" --tier 1

# Remove one, or change its tier:
python -m internship_hunter.companies.cli remove "Some Startup"
python -m internship_hunter.companies.cli set-tier "Some Startup" 2
```

A few seeded companies are marked `needs_verification` (shown as `verify` in
the `!` column of `list`) -- these are smaller companies where I could not
fully confirm the current careers page or hiring status from public sources.
Double check those before spending outreach effort on them.

## Phase 2: Job scanner

Scans every company's public Greenhouse/Lever/Ashby feed, flags software
intern/junior postings, skips clearance-required ones, and tells you only
what's new since the last run. The first time it sees a company it tries a
few safe slug guesses against all three vendors and caches whichever one(s)
actually belong to that company (see `scanner/ats_feeds.py`); if none match,
it flags the company `manual_check_needed` instead of guessing further --
seen in testing, a generic single-word guess once pulled in a *different*
company's postings by mistake, so the scanner only ever caches a match it's
confident is really that company.

```powershell
# Run the scan -- prints new postings and pushes a Telegram digest:
python -m internship_hunter.scanner.scan

# Same, but skip the Telegram push (useful for testing):
python -m internship_hunter.scanner.scan --no-telegram

# Browse everything ever stored (not just today's new postings):
python -m internship_hunter.scanner.cli list
python -m internship_hunter.scanner.cli list --company "Anduril Industries"
python -m internship_hunter.scanner.cli list --skill-match strong

# If a company's ATS slug is too generic to auto-detect safely, pin it by
# hand once you've found the real one (check a job URL on their careers page):
python -m internship_hunter.companies.cli set-ats "Some Company" greenhouse some-slug
```

**Skill-fit tagging.** Every software posting gets tagged `strong` /
`stretch` / `gap` / `unclear` against your actual skills, read from
`profile/resume.txt`, https://rollieo.xyz, and your GitHub repos on
2026-10-04: strong fit means Python, JavaScript/TypeScript, React, Node.js,
Firebase, Docker, PyTorch, or LLM/agent work (what Argus, Relio, and your
MIT coursework actually used); gap means the posting is firmware/embedded
C++, Rust, Kubernetes/DevOps-at-scale, cybersecurity, or native
iOS/Android -- nothing in your resume or repos touches those yet. A `gap`
posting is still saved in the database, just left out of the Telegram
digest and the "worth your time" table, so it's never truly lost -- `scanner
cli list` shows everything. The keyword lists live in `config.py` as
`STUDENT_SKILL_STRONG` / `_STRETCH` / `_GAP` -- edit them directly as your
skills grow (e.g. once you've shipped something in a new language).

Clearance-required postings are **excluded** from the digest per CLAUDE.md
(never worth outreach time); citizenship-required postings are stored and
shown normally since that's fine for you.

## Phase 3: People finder

Finds 1-3 real, publicly-listed people (founders, CTOs, engineering leads,
recruiters) per **tier-1** company, from that company's own website only --
never LinkedIn (CLAUDE.md bans it outright; `people_finder.fetch_page_text`
hard-refuses any `linkedin.com` URL before it would even make the request).
Every stored fact carries the exact URL it came from.

Needs a real Anthropic API key in `.env` (`ANTHROPIC_API_KEY=...`, from
https://console.anthropic.com) -- this is the first phase that spends money,
and it's genuinely small: roughly a page of text in, a few names out, per
company. Running it against all tier-1 companies costs well under $1 total.

```powershell
# Find people at every tier-1 company:
python -m internship_hunter.people.cli run

# Just one company:
python -m internship_hunter.people.cli run --company "Vannevar Labs"

# Browse everyone found so far:
python -m internship_hunter.people.cli list
python -m internship_hunter.people.cli list --company "Vannevar Labs"
```

**How it avoids fabricating people.** Claude is given the plain text of one
page and told, in `people/people_finder.py`'s `SYSTEM_PROMPT`: only extract
a name+title that's literally stated, never guess an email, and return an
empty list rather than invent someone -- an empty list is a normal, expected
result for a lot of pages. On top of that, the code never trusts Claude to
report its own source: `to_contacts()` always attaches the exact URL the
code itself fetched, and refuses to store anything without one.

**How it finds the page to read.** `find_team_page_url()` tries a handful of
common paths (`/team`, `/about`, `/leadership`, ...) on the company's *own*
domain -- unlike the ATS slug guessing in Phase 2, this never risks pulling
in a different company's page, since every candidate is rooted at that
company's own website. The first one that resolves gets cached on the
company record (`team_url`) so later runs skip straight to it. If nothing
resolves, that company is skipped and listed at the end of the run.

People-finder returns up to 5 people per company now, not 3 -- a
rank-and-file engineer is often a better referral source than a CEO is a
15-minute-call source, so it's worth keeping a few more names on file than
just the most senior ones.

## Phase 4: Drafting + Gmail drafts

Composes a short, honest email from the real profile/resume, and saves it
as a **Gmail draft only** -- `drafting/gmail_client.py` never calls a send
endpoint (there's no Gmail scope that allows drafts but blocks sending, so
this is enforced by the code never calling it, backed by a test that greps
the file's source for that call pattern). You review and send every draft
yourself.

Needs two things in `.env`/the filesystem:
- `ANTHROPIC_API_KEY` (same key as Phase 3)
- A Gmail OAuth client: in Google Cloud Console, enable the **Gmail API**,
  then **APIs & Services -> Credentials -> Create Credentials -> OAuth
  client ID -> Desktop app**, download the JSON, save it as
  `credentials.json` in the project root, and set
  `GOOGLE_OAUTH_CLIENT_SECRET_PATH` to that path. First run opens a browser
  for one-time consent as `GMAIL_DRAFT_ACCOUNT`; after that it's cached in
  `token.json` (gitignored).

```powershell
# Draft to a specific contact found in Phase 3:
python -m internship_hunter.drafting.cli draft --company "Caliola Engineering" --contact "Ryan Biondo"

# Explicitly ask for a referral instead of a call/resume ask:
python -m internship_hunter.drafting.cli draft --company "Caliola Engineering" --contact "Ryan Biondo" --ask referral

# Draft a general cover note about a specific posting (no named contact):
python -m internship_hunter.drafting.cli draft --company "Anduril Industries" --posting-id 42

# See every draft created so far, and how many are left today:
python -m internship_hunter.drafting.cli list
```

`--ask` takes `auto` (default -- the model picks), `call`, `resume`, or
`referral`. If a contact has no email on file (most won't -- team pages
rarely list one), the Gmail draft's "To" field is left blank rather than
guessing one; fill it in yourself before sending.

**Hard limits, enforced in code, not just the prompt:**
- **Daily cap** (`drafting/daily_cap.py`, default 10/day from
  `DAILY_DRAFT_CAP` in `.env`) -- checked *before* spending an API call or
  creating a draft, so the 11th attempt in a day fails fast.
- **Honest hours** -- `config.availability_statement()` computes the exact
  part-time/full-time framing from today's date vs. turning 16 in April
  2027, and hands it to the model as a fact to state, not something it
  works out itself.
- **Real project links only** -- the model is told to copy a URL
  character-for-character from `about_me.md`/resume text, never invent one;
  `validate_draft()` then flags (doesn't block, since you're reviewing it
  anyway) a draft that's missing a link, over 150 words, or doesn't mention
  his age.

**On LinkedIn:** CLAUDE.md bans automating LinkedIn outright (its terms
ban automation entirely, and it requires users to be 16+) -- this tool only
ever messages through Gmail drafts you review and send by hand, and the
only data sources are each company's own website (Phase 3) and whatever
you add by hand. Nothing here touches LinkedIn, logged in or not.

## Running tests

```powershell
pytest
```

## Project layout

```
internship_hunter/
  config.py        # secrets + constants (tiers, states, hour-limit rules) from CLAUDE.md
  db.py             # SQLite schema + CRUD helpers
  models.py         # Company / Posting / Contact / Message dataclasses
  companies/        # Phase 1: target list + CLI
  scanner/          # Phase 2: job scanner (ats_feeds, filters, scan, cli)
  notify/           # Telegram status pushes (new postings, reminders, weekly digest)
  people/           # Phase 3: people finder (people_finder.py, cli.py)
  drafting/         # Phase 4: outreach drafting + Gmail drafts (compose.py, daily_cap.py, gmail_client.py, cli.py)
  apply_assist/      # Phase 5: Playwright prefill (not built yet)
  routes/            # Phase 7: weekly "other routes" report (not built yet)
  dashboard/         # Phase 6: Streamlit tracker (not built yet)
tests/               # pytest, one file per module
```
