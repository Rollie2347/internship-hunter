# Internship Hunter — project context for Claude Code

## What this is
A personal tool that helps a 15-year-old high school student land a **year-long tech internship**,
preferably at a **defense-tech startup**, by getting **referred**: finding the right people,
drafting a short honest note to each, and tracking every conversation from first note to
referral. Volume is not the goal. Getting in front of the *right* person with a message they
actually read is the goal.

## How it works now (redesigned 2026-10-08: referrals, not applications)
The student decided the application route doesn't work for a high schooler (nearly every
posting requires college enrollment) and that the tool should be built around referrals.
- **The pipeline is: contacted -> replied -> call -> referred.** `/status` and the dashboard
  lead with those four numbers. Applications are a side tool.
- **Up to ten people a day, at 7 AM** -- or as soon after as the laptop is awake; it has to be
  plugged in with sleep turned off to hit 7 AM (README, "Keeping the bot running") -- (`DAILY_RUN_HOUR`; the slow scan and people search run at 6 AM so the drafts arrive on time) (`OUTREACH_PER_DAY`; the student set 5, then 10, on 2026-10-08). The
  bot *prepares* ten on its own -- it never sends one: an email goes out only on his Send now
  tap, and a LinkedIn request only when he pastes it himself (constraints 4 and 5). Beyond the ten, `/pitch`, `/linkedin`, `/li` and `/warm` add more when he asks, up to the hard caps.
- **Email only in the daily run** (the student asked for this on 2026-10-09: he has no
  LinkedIn Premium, so no connection notes; on 2026-10-08 he had asked for "more email").
  The 7 AM batch is email drafts and nothing else. **The target is ten emails every day**
  (the student asked for this on 2026-10-09); a day falls short (with a message saying
  why) only when fewer than ten people on file have a published address, so keeping that
  supply up is part of the job: the 6 AM prep spends up to 5 Hunter lookups a day until
  ten people are waiting (`find_emails_with_hunter`). Hunter matches by domain and can
  return someone who was never at the company (a previous owner of the domain, a
  placeholder name from an unrelated PDF) -- check the source page before trusting a row.
  When Hunter's month runs out, tell him; a paid plan or the paid web search is his and
  his parents' decision. A person with a
  published email gets an email draft; a company that publishes an inbox (careers@, info@)
  gets ONE email to it, addressed to the best-placed person on file or to the team, when
  nobody there has an address of their own. LinkedIn cards are made only when he asks
  (`/linkedin`, `/li`); if he then can't find the person on LinkedIn
  the bot drafts an email to the company's published inbox, or, if there is none, a note for
  the company's contact form (channel `other`). Never an email draft with a blank "To".
  One channel per person still holds.
- **People he already knows go first.** `/warm Name, how he knows them, where they work`
  stores them under the placeholder company "My network" and drafts a note asking who he
  should talk to -- not for a job.
- **No hours talk in messages** (the student asked for this on 2026-10-08). Emails and notes
  do not mention work-hour limits, labor rules, part-time vs full-time, or turning 16 -- that
  is for a conversation. They still say plainly that he is 15 (constraint 1), and must never
  say or imply he can work more than constraint 2 allows; before any offer is accepted he has
  to tell the company his real hours. Each message also says, in one clause, that he has
  other projects he'd be glad to show.
- **The ask ladder.** Every note and email says plainly that he is looking for an internship
  **so he can learn** (the student asked for this on 2026-10-08) and names what he wants to
  learn. The ask itself stays small: a 15-minute call or a question about their work. He
  doesn't ask the person to give him the internship or to refer him until after a reply.
- **Order** (`outreach/priority.py`): company tier, then companies with software postings
  seen in the last 14 days, then one person per company before a second.
- **Applications are on demand only.** No application cards in the daily run. `/apply <link>`
  is for when a contact says "apply through this link"; `/more` shows queued postings. The
  scanner still runs daily, as the hiring signal above and to keep `/apply` working.

## The student
- Age 15, taking online school in the evenings so days are free.
- **US citizen** (citizenship-required defense roles are OK; clearance roles still are not, since clearances need age 18).
- **Turns 16 in April 2027.** Wants to start ASAP. The pitch is: "part-time now (after
  local school hours and on weekends, up to 18 hrs/week), then full-time year-round from
  April 2027." Target start dates should be now through April 2027.
- Possible exception to check: a school-supervised work-experience (WECEP) or work-study
  program run by the student's school can allow work during school hours at 14–15
  (29 CFR 570.36–570.37). Ask the student whether the online school offers one.
- `profile/my_answers.md` holds the student's own answers to application-form questions.
  It is his file: add new questions to it, record answers he picks himself, never overwrite
  an answer he typed, and never invent one.
- Fill in `profile/about_me.md` and put the resume at `profile/resume.pdf`. Read both before
  drafting anything, and never invent experience, skills, or credentials.
- Owner email for tooling: set in `.env`, never hard-coded.

## Targets
- **Locations (updated 2026-10-07):** **Colorado and Virginia only** (family there to live
  with; the student wants a year out of Wisconsin). Don't queue postings or pitch companies
  anywhere else, including remote roles.
- **Fields the student cares about:** AI, ML, robotics and defense. A defense company is the
  first choice; the others are welcome.
- **Referrals, not cold applications.** Outreach to real people is the route (see "How it
  works now"). Spend effort on finding people, drafting notes, and tracking replies, calls
  and referrals -- not on postings.
- **Only postings he can truthfully apply to.** Read a posting's requirements before showing
  it (`scanner/eligibility.py`). One that requires college enrollment, a degree, age 18+ or
  professional experience is never queued -- the student asked for this on 2026-10-07 after
  being shown college internships.
- **Role focus: software only.** Software engineering, full-stack, backend/frontend, ML/AI,
  data, firmware/embedded software, DevOps, and cybersecurity-engineering roles. Skip
  mechanical/hardware-only, business, sales, and ops roles, even at a target company -- a
  company can stay on the target list for its software team while its hardware/field roles
  get filtered out at the job-posting level.
- **Company types (in priority order):**
  1. Early/mid-stage defense-tech and dual-use startups (drones/autonomy, space, sensing,
     EW/RF, simulation, defense software)
  2. Larger defense-tech companies (Anduril, Palantir, Shield AI, etc.)
  3. AI labs and other strong tech companies
  4. Government/lab programs open to high schoolers (DoD STEM programs, national/service labs)
- **Duration:** about 12 months, daytime hours.

## Hard constraints the tool must respect
1. **Honesty about age.** Every application and message says plainly that the student is a
   15-year-old high schooler. Being unusually young is the hook, not something to hide.
2. **Child labor rules (US federal FLSA, ages 14–15).** No work during local public-school
   hours, even for online/homeschool students. On school days, max 3 hrs/day and 18 hrs/week,
   between 7am and 7pm (9pm from June 1 to Labor Day). In non-school weeks, up to 8 hrs/day and
   40 hrs/week. **These federal hour limits end at 16.** Virginia and Wisconsin also require a
   work permit for workers under 16. The pitch should be framed realistically, e.g. "full-time
   this summer, and continuing year-round once I turn 16," or part-time after school.
   Unpaid work at for-profit companies is generally still treated as employment.
3. **Defense specifics.** The student is a US citizen, so ITAR/citizenship-required roles
   are fine. Security clearances require age 18, so filter out clearance-required roles.
4. **Platform rules.** LinkedIn requires users to be 16+, and its terms ban automation, so
   **never automate LinkedIn** (no scraping, no auto-messaging, no logging in, no fetching
   any linkedin.com page -- see "LinkedIn assist" below for what is allowed). Do not auto-submit forms on
   applicant tracking systems (Greenhouse, Lever, Ashby, Workday). Use their **public job-board
   APIs/JSON feeds** to read postings, and stop before the final "Submit" click so a human
   reviews and submits. The Telegram approval bot (`approvals/`) follows this: Approve opens
   the prefilled form, and the student presses Submit. Dropdowns and radio buttons may be
   answered from the fixed rules in `apply_assist/choices.py`; the only click allowed is the
   guarded `_safe_click` (a dropdown or its option, never a button).
5. **Human in the loop for everything outbound.** The tool creates *drafts* (Gmail drafts,
   prefilled forms). The student reviews each one and sends it. As of 2026-10-07 he may send
   an outreach draft by tapping **Send now** under its full text in Telegram; that tap is the
   only thing that may ever send mail (one draft per tap -- never on a timer, in a loop, or in
   bulk). Keep a daily cap (25/day, shared between application cards and outreach drafts) so
   every message is still read before it goes out. LinkedIn cards have their own cap of
   10/day (`LINKEDIN_DAILY_CAP`), counted separately. Both are ceilings for what he asks
   for; on its own the bot prepares only `OUTREACH_PER_DAY` (10) people a day in total.
6. **Contacts.** Use only professional, publicly listed info (company team pages, published
   work emails, conference/podcast bios, GitHub). No personal addresses, phone numbers, or
   anything about people's private lives. Email addresses must be published somewhere and
   stored with that source URL -- never guessed or built from a company's address pattern
   (the student chose this on 2026-10-07). Hunter.io (approved 2026-10-08) may be used for
   its **Domain Search endpoint only**: an address is kept only if Hunter returns a source
   page for it, and that page's URL is stored as the source. Never use Hunter's Email Finder
   or the `pattern` field -- both are guesses. Cache every answer and stay inside the free
   monthly limit (`people/hunter.py`). People come from three sources, all stored
   through `people/dedupe.py` so one person is one row: the company's own team page, a web
   search of what's published about the company (`people/web_search.py` -- only pages our
   own code then downloads and reads count, and the page's URL is the source), and people
   the student adds himself with `/li`.
7. **Secrets.** API keys go in `.env` (gitignored). Never print or commit them.

## LinkedIn assist (added 2026-10-08)
The tool helps the student use LinkedIn by hand. It never uses LinkedIn itself.
- **Allowed:** building a people-search link from a contact's name + company (a string in
  a Telegram message, never requested by the tool); drafting a connection note; storing a
  profile URL the student pasted with `/li` (stored, never opened); tracking what he says
  he did.
- **Never:** logging in, fetching or scraping any linkedin.com page, sending or accepting
  anything, or opening the link for him. `linkedin_assist/assist.py` imports no HTTP or
  browser library and a test fails if one appears; `people_finder.fetch_page_text` refuses
  linkedin.com URLs; the web search tool is told to block the domain.
- **The note:** under 200 characters (his account's limit; `LINKEDIN_NOTE_MAX_CHARS`), says
  plainly that he is 15 and looking for an internship to learn, one specific thing about the
  person taken only from the stored fact (or what the company builds, if there is no fact),
  one real project of his, one soft ask. Never invented details.
- **The flow:** a Telegram card (person, why them, link, note) with "Sent on LinkedIn",
  "Skip" and "Not found". "Sent on LinkedIn" logs a `messages` row with channel
  `linkedin`. "Replied" drafts a short follow-up for him to paste. No answer after 7 days
  gets one reminder, once -- never an automatic email follow-up.
- **One channel per person:** someone with a LinkedIn card isn't also cold-emailed (unless
  he marked them "Not found"), and someone already emailed gets no card.
- **Cap:** at most 10 cards/day. Since 2026-10-09 the bot makes no cards on its own; only
  `/linkedin` and `/li` do.
- **Out of free notes:** a free account gets only a few connection notes a month (he ran
  out on 2026-10-08). `/notes off` makes cards say "connect without a note" and drafts
  nothing until the person accepts; then "Accepted or replied" drafts his first full message.
  `/notes on` switches back. Don't suggest extra accounts or other ways around LinkedIn's
  limit; paying for Premium is a decision for him and his parents.
- **Age:** LinkedIn's own minimum age is 16 and the student is 15 until April 2027. Whether
  he uses an account before then is his and his parents' decision, not the tool's; don't
  suggest ways around LinkedIn's sign-up age check.

## Preferred stack
- Python 3.11+, runs on **Windows** (use `pathlib`, no bash-only scripts; give PowerShell commands).
- SQLite for tracking (`data/tracker.db`), Playwright for browser prefill, Anthropic API for
  drafting, Gmail API for creating drafts, and a simple local dashboard (Streamlit or a CLI
  with `rich`).
- Small, readable modules with a test for each core function. Keep a `README.md` with setup steps.

## Notifications
- Daily/weekly status updates (new postings found, 7-day follow-up reminders, the weekly
  "other routes" digest) go to the student's **Telegram**, via a bot, instead of email.
  `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` live in `.env`, never hard-coded or printed.
- This does **not** change constraint 5 above: outbound messages *to companies/contacts*
  (cold emails, application answers) are still created as Gmail drafts only, in the Gmail
  account set by `GMAIL_DRAFT_ACCOUNT` in `.env`, and still require the student to review and
  send them by hand. Telegram is for pinging the student, not for contacting anyone else.

## Working style
- Build in phases and get each one running before starting the next.
- Ask the student before adding a new external service or anything that costs money.
- Explain code choices in plain language, because the student wants to learn, not just ship.
