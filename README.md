# Internship Hunter

A personal tool to help a 15-year-old high schooler get **referred** into a
year-long tech/defense-tech internship in Colorado or Virginia. See
`CLAUDE.md` for the full rules this tool follows (honesty about age,
child-labor-law hour limits, no LinkedIn automation, human-reviewed outreach
only, etc.).

## How to use it (redesigned 2026-10-08 around referrals)

Almost no posting is open to a high schooler, so the tool no longer pushes
applications. It works one pipeline:

**contacted -> replied -> call -> referred**

Leave the bot running: in a PowerShell window, `cd C:\Users\rro\Documents\internship-hunter`
then `.\start_bot.ps1` (see "Keeping the bot running").
Every day at **7 AM** (`DAILY_RUN_HOUR` in `.env`) it sends you **up to ten people** to email (`OUTREACH_PER_DAY` in `.env`), about
20-30 minutes of work. Since 2026-10-09 the daily batch is **email only**, so it is smaller
(or empty, with a message saying so) when few people on file have a published address --
Hunter.io, below, finds more. It prepares them on its own; nothing goes out until you tap or paste:

| What arrives | When | What you do |
|---|---|---|
| Email draft | the person has a published email, or their company publishes an inbox (one email per company inbox) | read it, tap **Send now** |
| LinkedIn card | only when you send `/linkedin` or `/li` | open the link, paste the note, tap **Sent on LinkedIn** |
| Contact-form note | you tapped **Not found** and the company publishes no inbox | paste it into the company's contact form, tap **I sent it** |
| Follow-up draft | an email got no reply in 7 days | read it, tap **Send now** (one per person, ever) |

When someone answers, tap **Replied** (email replies are noticed for you).
The bot drafts your next message and then asks how it went: **Call booked**,
**They referred me**, or **It went nowhere**. `/status` shows the four
pipeline numbers.

Who comes first: defense startups (tier 1), then companies whose job board
shows software roles in the last 14 days (a sign the team is growing, not
something to apply to), one person per company before a second.

Things you start yourself:

- `/warm Name, how you know them, where they work` -- someone you already
  know. These matter most: the note asks who you should talk to, not for a
  job. Example: `/warm Tom Reyes, my uncle in Denver, engineer at a satellite company`
- `/li <profile link> Name, Title, Company` -- someone you found yourself.
- `/linkedin 3`, `/pitch 3` -- more than today's five.
- `/apply <posting link>` -- a contact told you to apply through a link:
  the bot fills in the form, you press Submit.
- `/more 3` -- application cards for queued postings, if you want them.

Every note and email says you're looking for an internship so you can
learn, and what you want to learn from them. The ask itself stays small: a
15-minute call or a question about their work. Asking them to refer you
comes after they've replied.

`OUTREACH_PER_DAY` in `.env` changes the ten. The sections below describe
each part in the order it was built; where they talk about daily
application cards, that is now on demand only.

Built in phases -- see `C:\Users\rro\.claude\plans\rustling-inventing-petal.md`
for the full plan. **Phases 1-6 (target company list, job scanner, people finder,
drafting, apply assist, Telegram approvals) are done**, plus a GitHub Actions workflow that runs
the daily scan even when your laptop is off (see below).

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

### More sources: web search, and one row per person

```powershell
# Search the web for people at tier-1 Colorado/Virginia companies that have
# never been searched (3 companies per run unless you pass --limit):
python -m internship_hunter.people.cli web --limit 3
python -m internship_hunter.people.cli web --company "Vannevar Labs"

# Merge anyone who is on file twice at the same company:
python -m internship_hunter.people.cli dedupe
```

`people/web_search.py` looks for founders, CTOs and engineers in blog
posts, press releases, funding announcements, podcasts and conference
talks -- the places that give a note something specific to open with
("spoke about swarm autonomy on the X podcast") instead of just a title.
It works in two steps so nothing the model merely remembers can be stored:

1. Claude, with Anthropic's web search tool, picks up to 3 pages. Only URLs
   the search tool really returned are kept.
2. Our own code downloads each page and extracts people from that text. A
   person whose name isn't literally on the page is dropped, a page that
   never mentions the company is skipped, and the page's URL is stored as
   the source.

**Cost:** this is the most expensive thing in the tool. Each company is one
search request (up to 4 searches at $10 per 1,000, plus the search results
as input tokens) and up to 3 small extraction calls. Run it on 3 companies
and look at the usage page in the Anthropic console before doing all of
them. Each company is only ever searched once, and the bot never runs it on
its own unless you set `WEB_PEOPLE_SEARCH_PER_DAY` in `.env` (default 0).

**Hunter.io** (`people/hunter.py`, optional): put a free-plan key in `.env`
as `HUNTER_API_KEY`, then

```powershell
python -m internship_hunter.people.cli hunter --limit 5
```

It uses Hunter's **Domain Search** only, which lists addresses Hunter's
crawler saw on real pages. An address is kept only if Hunter names a page
it was seen on, and that page's URL is stored as the source. Hunter's Email
Finder and its "pattern" guess are never used (a test checks the code can't
reach either). Every answer is cached, each domain is looked up once, and
searches stop at `HUNTER_MONTHLY_LIMIT` a month (default 25 -- set it to
what your plan allows). This sends your target companies' domain names to
Hunter, nothing else. With a key set, the bot also looks up to 5 companies a
day on its own at 6 AM, until ten people are waiting to be emailed. Hunter
matches by domain, so now and then it returns someone who never worked
there -- look at the source page if a name seems off.

**Deduplication** (`people/dedupe.py`): every source stores people through
one function. Inside one company, two names are the same person when the
last names match and the first names are equal, an initial, a shortening
("Chris"/"Christopher") or a common nickname ("Mike"/"Michael"). The row
already on file is kept; a more specific fact replaces a vaguer one and
always brings its own source URL with it.

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
- **Daily cap** (`drafting/daily_cap.py`, default 25/day from
  `DAILY_DRAFT_CAP` in `.env`, shared with application cards) -- checked
  *before* spending an API call or creating a draft, so one past the cap
  fails fast.
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
ban automation entirely, and it requires users to be 16+). Nothing in this
tool logs into, fetches or reads LinkedIn. The LinkedIn assist cards (see
Phase 6) only hand you a link and a note; you do everything on LinkedIn
yourself.

## Phase 5: Apply assist

Opens a real, visible browser (Playwright) on a posting's actual
application page, fills in the fields we have real values for, attaches a
resume if one exists, and then **pauses** -- `apply_assist/playwright_fill.py`
never calls a click method on anything at all (enforced by a test that
greps the file's source), so it can never hit Submit. You review everything
in the still-open window and submit it yourself.

```powershell
# One-time: install the Chromium browser Playwright drives (~200MB download)
playwright install chromium

python -m internship_hunter.apply_assist.cli fill 44
```

Only fills a short allow-list of unambiguous fields -- first/last/full name,
email, phone, GitHub, portfolio/website, current location -- pulled live
from `about_me.md`/`resume.txt`, never a second copy of that data. It
**never** touches LinkedIn fields (he doesn't have one), "current company"
(he has none), cover letters, or any screening/EEO/clearance/work-
authorization question -- those need real judgment, so they're left for you
to answer, and get listed in the output so nothing is silently skipped.
Put a PDF resume at `profile/resume.pdf` to enable the attach-resume step;
without one, that step is skipped with a clear message.

Two vendor quirks this handles (found by inspecting real live postings, not
assumed): Greenhouse's required-field asterisk ("First Name*") is part of
the visible label but not the input's actual accessible name, so the lookup
strips it; Lever's application form lives at a separate `<posting-url>/apply`
page, not the posting page itself.

## Phase 6: Approve applications from Telegram

This is the main way to use the tool now. Leave one window running:

```powershell
python -m internship_hunter.approvals.cli bot
```

**Since 2026-10-08 the daily run no longer sends application cards** (see
"How to use it" at the top): item 1 below now happens only when you send
`/more` or `/apply <link>`, and outreach is five people a day.

Originally, once a day the bot did two things, sharing one budget of 25 items
(`DAILY_DRAFT_CAP` in `.env`):

1. **Application cards.** For each new posting in **Colorado or Virginia**
   it reads the real form, drafts answers to the open-ended questions from
   `about_me.md`/`resume.txt`, works out the dropdown answers, and sends a
   Telegram card showing exactly what will be entered, with **Approve** and
   **Skip** buttons.
2. **Outreach drafts** with whatever budget is left -- usually most of it,
   since few CO/VA postings appear on any one day. This is the route most
   likely to work: follow-ups that are due first, then cold pitches to
   named people at Colorado/Virginia companies. Each is saved as a Gmail
   draft and shown in Telegram in full, with a **Send now** button.

Before both, it runs the people finder on up to five Colorado/Virginia
companies it has never checked (each company is only ever checked once).

Between the two it sends **LinkedIn cards** -- up to 10 a day, a budget of
their own (`LINKEDIN_DAILY_CAP`). See "LinkedIn assist" below.

Then it sends the status update.

- **Approve** opens the real form on this PC with your details, drafted
  answers, dropdown answers and resume in place. You finish what's left and
  **you press Submit**. When the bot sees the confirmation page it records
  the application as submitted; if you just close the window it asks you.
- After a submit it offers a referral email to a real person at that company.
- **Send now** sends that one draft from your Gmail, exactly as it stands
  there -- so if something is off, fix the draft in Gmail first, then tap
  Send. Nothing is ever sent without that tap: the only code that sends
  mail is `gmail_client.send_draft`, its only caller is the Send button
  handler, and a test fails if that ever changes.
- A draft with no address can't be sent. Add one you found yourself with
  `/to <draft id> name@company.com`.
- Once sent, the bot checks that Gmail thread every 10 minutes. A reply
  pings you in Telegram and cancels the follow-up; a bounce marks the
  address as bad. No reply after 7 days gets one short follow-up draft (one
  per person, ever). This needs read access to Gmail, granted once with:

  ```powershell
  python -m internship_hunter.drafting.cli auth
  ```

  Without it everything else still works and you tap **They replied**.

Commands in Telegram: `/more 5`, `/pitch 5`, `/linkedin 5`, `/li ...`,
`/status`, `/open <id>`, `/referral <id>`, `/to <draft id> <email>`,
`/result <id> interviewing|rejected`, `/help`.

### LinkedIn assist

The bot never logs into, opens, or reads LinkedIn -- its terms ban
automation. `linkedin_assist/assist.py` doesn't import an HTTP library at
all, and a test fails if one is ever added. What you get is a card:

- **The person** and **why them** (the stored fact, with its source link).
- **A "Connect with ... on LinkedIn" button** (and the same link as text),
  built from their name + company. It opens LinkedIn at that person; you
  check it's the right one and press LinkedIn's own Connect.
- **A note** under 200 characters (your account's limit), sent as its own message so that pressing
  and holding it copies exactly the note: that you're 15, one specific thing about
  their work from the stored fact, one of your projects, and a soft ask.
  The card shows the character count and warns if a note runs long or
  doesn't mention your age.
- Buttons: **Sent on LinkedIn** (logs it in the tracker with channel
  `linkedin` and starts a 7-day clock), **Skip**, **Not found**.

After **Sent on LinkedIn** the card gets a **Replied** button. Tap it when
they accept or write back, and the bot drafts a short next message (your
real availability, one project link, one ask) for you to paste. If 7 days
pass with nothing, you get one reminder, once.

**Out of free notes?** A free LinkedIn account only gets a few connection
notes a month. When LinkedIn says "You're out of free custom notes", send
`/notes off`. Cards then tell you to connect *without* a note (no note is
drafted), and when the person accepts you tap **Accepted or replied** and
the bot drafts your first real message, which can be much longer than a
200-character note. Send `/notes on` when the month resets.

Someone you found yourself:

```
/li https://www.linkedin.com/in/jane-doe Jane Doe, Staff Engineer, Foo Robotics
Wrote the post about their drone autonomy stack
```

The second line is optional: one thing you noticed about their work, in
your own words. The company has to be on the company list already. The
link is saved and shown back to you on the card; it is never opened.

`/linkedin 5` sends five more cards from people already on file. Cards go
to people at Colorado/Virginia companies, those with no published email
first. One channel per person: someone with a card isn't also cold-emailed
(unless you tapped **Not found**), and someone you've emailed gets no card.
The dashboard has a **LinkedIn** tab with every card and its status.

Two things to know. LinkedIn's minimum age is 16, so an account before
April 2027 is against its rules and could be closed -- that's a decision
for you and your parents. And free accounts are, as far as I know, limited
to a handful of personalised notes a month; check what your account allows.
Notes are capped at 200 characters, your account's limit
(`LINKEDIN_NOTE_MAX_CHARS` in `config.py`; paid accounts get 300).

```powershell
# See what's next in the queue without sending or spending anything:
python -m internship_hunter.approvals.cli preview
```

**What gets filled in.** Checked on live Anduril, Rocket Lab, Two Six
(Greenhouse) and Palantir, Shield AI (Lever) forms:

- Typed fields: name, email, phone, GitHub, website, location, resume, and
  free-text questions (drafted by Claude from your profile).
- Dropdowns and radio buttons that have a **standing answer** in
  `apply_assist/choices.py`: work authorization (Yes), visa sponsorship
  (No), country (United States), "at least 18?" (No), active clearance
  (No), degree (High School), non-compete (No), worked here before (No),
  willing to work on-site (Yes), how did you hear (Company Website/Other).
  These are fixed rules, not the model, because each is a factual or legal
  statement about you that must come out the same true way every time.

**Your answers file: `profile/my_answers.md`.** Everything else on a form
is something only you know, so the tool builds that knowledge up:

- The file starts with questions nearly every form asks (school,
  graduation month, city, the optional demographic questions). Type after
  `answer:`; leave one empty to keep answering it yourself.
- When a form has a question nothing can answer, the bot adds it to the
  bottom of the file (with the dropdown's options, when the form lists
  them) and says so on the card.
- When you pick an answer in the browser yourself, the bot notices and
  writes it into the file, marked "learned from". It never overwrites
  something you typed.

Answers to starter questions apply to any form that asks them; an answer
to a collected question applies only to that exact wording, so it can't
leak onto a differently-phrased (possibly opposite) question.

**Always yours:** "select all that apply" checkbox lists, consent boxes,
and signature Name/Date boxes. And some college-internship forms ask
things with no true answer for a high schooler (bachelor's graduation
date, university GPA) -- those stay blank for you to decide on.

**How it clicks without being able to submit.** Opening a dropdown needs
a click, so `playwright_fill.py` has exactly one click call, inside
`_safe_click`, which refuses anything that isn't a dropdown or one of its
options (`click_allowed`). Buttons and submit inputs are always refused,
and a test fails if a second click call ever appears in that file.

**It reads the requirements first** (`scanner/eligibility.py`). A title
like "Flight Software Intern" says nothing about who may apply, so before a
posting becomes a card the bot fetches its full text and checks it:

- *not eligible* -- it requires something you can't truthfully claim
  (enrolled in a college degree program, a degree, a college class year,
  age 18+, years of professional experience, full-time dates before you
  turn 16). Never shown, costs none of the day's budget, and `/status`
  counts how many were ruled out.
- *long shot* -- nothing is strictly required that you lack, but it's
  clearly aimed higher. Shown, with the reason on the card.
- *eligible* -- shown normally. A posting that says it's open to high
  school students is eligible outright, and the scanner now picks those up
  even when the title never says "intern".

Plain patterns decide the obvious cases for free and quote the sentence
that decided it. Claude reads the rest, and its "not eligible" only counts
if the sentence it quotes is really in the posting (checked in code) --
otherwise the posting is kept as a long shot, so a model mistake can't
quietly hide a real opening.

Expect this to rule out most postings: nearly every "intern" role on these
boards is a college internship. That is the point -- it's why outreach to
people is the main route.

**The bot also scans.** Its daily run starts by reading every company's
public job feed, so the queue stays current without running the scanner
by hand.

**What is queued** (`approvals/queue.py`): only postings with an office in
Colorado or Virginia, defense startups first (company tier), then skill
fit. A posting that lists many cities shows only its Colorado/Virginia
offices on the card, and "which office do you prefer?" is answered with
one of those. Never queued: clearance-required roles, hardware-only titles, skill
gaps, and programs a high schooler can't join (SkillBridge, PhD, MBA). To
allow another place, add its code to `PREFERRED_STATES` in `config.py`.

**Growing the outreach list** (the limiting factor for referrals):

```powershell
# Find people at Colorado/Virginia companies that have nobody on file yet.
# One API call per company; also saves any inbox the company publishes
# (careers@, info@) to use when a person has no published email.
python -m internship_hunter.people.cli run
# Draft the next 10 outreach emails right now, as Gmail drafts:
python -m internship_hunter.drafting.cli batch --limit 10
```

A draft's "To" is the person's own published email if there is one, else
the company's published inbox (careers@, info@), else blank until you add
one with `/to`. Addresses are never guessed or built from a pattern.

```powershell
# Search public sources for emails of people who have none: the company's
# own contact/about/team/press pages, and public GitHub profiles (a profile
# only counts if both the name and the listed company match).
python -m internship_hunter.people.cli emails
```

Expect this to find a minority -- most people publish no address at all.
An optional `GITHUB_TOKEN` in `.env` (no scopes needed) just raises
GitHub's rate limit.

`companies/seed_expansion.json` adds about 105 companies and 7
government/lab programs for high schoolers. Every one is marked
`needs_verification`: they came from general knowledge, not a checked
source, so confirm the details before relying on them. Companies outside
Colorado/Virginia stay on the list only so their CO/VA postings are caught.

## Keeping the bot running

The bot has to run on your PC: approved applications open in a browser
there, and it uses your Gmail sign-in.

```powershell
# Start it (restarts itself if it ever stops; log in data\bot.log):
cd C:\Users\rro\Documents\internship-hunter
.\start_bot.ps1
# If it says scripts are disabled, run this once in the same window, then try again:
#   Set-ExecutionPolicy -Scope Process Bypass
```

`start_bot.ps1` has the three lines to register it as a Windows scheduled
task so it starts whenever you sign in.

**The bot only runs while the laptop is awake.** A sleeping laptop sends
nothing at 7 AM; the batch arrives whenever it next wakes up. To keep it
awake around the clock, leave it plugged in and run these once:

```powershell
# (the full path, because plain "powercfg" isn't found on this laptop)
$p = "$env:SystemRoot\System32\powercfg.exe"
& $p /change standby-timeout-ac 0      # never sleep while plugged in
& $p /change hibernate-timeout-ac 0    # never hibernate while plugged in
# Closing the lid does nothing while plugged in (the screen still turns off):
& $p /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0
& $p /setactive SCHEME_CURRENT
```

These were applied on 2026-10-09. On battery it still sleeps as before. To undo:
`& $p /change standby-timeout-ac 5` and the `LIDACTION` line with `1` instead of `0`. Don't leave a closed,
running laptop in a bag or on a bed -- it needs air.

## Moving the bot to another PC

The code travels through GitHub. Five things never go into git, because
they are secrets or private, and have to be copied by hand (USB stick, or
your own private cloud drive -- not email, not a public link):

| File | What it is |
|---|---|
| `.env` | your API keys and settings |
| `credentials.json` | the Google OAuth client for Gmail |
| `token.json` | your saved Gmail sign-in |
| `data	racker.db` | everyone you've contacted and every message |
| `profileesume.pdf`, `profileesume.txt` | your resume |

On the new PC (PowerShell; needs Python 3.11+ and Git installed):

```powershell
git clone https://github.com/Rollie2347/internship-hunter.git
cd internship-hunter
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium        # only needed for /apply and /open

# Now copy the five things above into this folder, in the same places.
# In .env, fix GOOGLE_OAUTH_CLIENT_SECRET_PATH if the folder path is different.

pytest                              # everything should pass
.\start_bot.ps1                     # start the bot
```

Then make it start by itself at sign-in (the three lines are at the top of
`start_bot.ps1`), and set that PC never to sleep (Settings > System >
Power).

**Only one PC may run the bot.** Two copies fight over Telegram's messages
and would each send the daily batch. On the old PC, stop the bot and remove
its sign-in task before starting the new one:

```powershell
Unregister-ScheduledTask -TaskName "Internship Hunter bot"
```

The repository must stay **private**: `CLAUDE.md` and `profile/` describe
you (age, school, city), and older commits contain a copy of the tracker.

## Cloud scan (GitHub Actions)

`.github/workflows/daily-scan.yml` also scans every morning in GitHub
Actions and sends a Telegram digest of new Colorado/Virginia postings that
pass the pattern check, so you hear about them even with the PC off. It
can't draft or open anything -- that needs the bot above.

The cloud run keeps its **own** database, `data/cloud_tracker.db`, which it
commits back after each run to remember what it has already seen. Your PC's
`data/tracker.db` (applications, contacts, sent emails, your queue) is not
in git at all. They used to be one committed file, which meant every cloud
run conflicted with the local one.

Secrets (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) are stored as encrypted
repository secrets; `.env`, `credentials.json`, `token.json` and
`profile/resume.*` stay out of git entirely. To change a secret, pipe the
value from `python -c "from internship_hunter import config;
print(config.TELEGRAM_CHAT_ID)"` into `gh secret set TELEGRAM_CHAT_ID`
rather than grepping `.env` (a raw grep copies dotenv's quote characters,
which Telegram rejects with a silent 400).

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
  scanner/          # Phase 2: job scanner (ats_feeds, filters, eligibility, scan, cli)
  notify/           # Telegram status pushes (new postings, reminders, weekly digest)
  people/           # Phase 3: people finder (people_finder.py, web_search.py, email_finder.py, dedupe.py, cli.py)
  outreach/         # who to write to next (priority.py) and notes pasted elsewhere / people you know (paste.py)
  linkedin_assist/  # LinkedIn cards: search link + note to paste (assist.py) -- never touches linkedin.com
  drafting/         # Phase 4: outreach drafting + Gmail drafts (compose.py, daily_cap.py, gmail_client.py, cli.py)
  apply_assist/      # Phase 5: Playwright prefill (profile_fields.py, field_map.py, playwright_fill.py, cli.py)
  approvals/         # Phase 6: Telegram approve/skip bot (queue.py, bot.py, cli.py)
  routes/            # weekly "other routes" report (not built yet)
  dashboard/         # Streamlit tracker: streamlit run internship_hunter/dashboard/app.py
tests/               # pytest, one file per module
```
