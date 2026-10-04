# Internship Hunter — project context for Claude Code

## What this is
A personal tool that helps a 15-year-old high school student land a **year-long tech internship**,
preferably at a **defense-tech startup**, by finding opportunities and people, drafting
personalized applications and outreach, and tracking everything. Volume is not the goal.
Getting the resume in front of the *right* person with a message they actually read is the goal.

## The student
- Age 15, taking online school in the evenings so days are free.
- **US citizen** (citizenship-required defense roles are OK; clearance roles still are not, since clearances need age 18).
- **Turns 16 in April 2027.** Wants to start ASAP. The pitch is: "part-time now (after
  local school hours and on weekends, up to 18 hrs/week), then full-time year-round from
  April 2027." Target start dates should be now through April 2027.
- Possible exception to check: a school-supervised work-experience (WECEP) or work-study
  program run by the student's school can allow work during school hours at 14–15
  (29 CFR 570.36–570.37). Ask the student whether the online school offers one.
- Fill in `profile/about_me.md` and put the resume at `profile/resume.pdf`. Read both before
  drafting anything, and never invent experience, skills, or credentials.
- Owner email for tooling: set in `.env`, never hard-coded.

## Targets
- **Locations:** Virginia, Colorado, or Wisconsin (in person or hybrid). Remote roles are a bonus tier.
  All three states are weighted equally -- the student can relocate to any of them (family in
  Northern Virginia and Colorado; currently based in Wisconsin), so don't rank one above another.
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
   **never automate LinkedIn** (no scraping, no auto-messaging). Do not auto-submit forms on
   applicant tracking systems (Greenhouse, Lever, Ashby, Workday). Use their **public job-board
   APIs/JSON feeds** to read postings, and stop before the final "Submit" click so a human
   reviews and submits.
5. **Human in the loop for everything outbound.** The tool creates *drafts* (Gmail drafts,
   prefilled forms). The student reviews, edits, and sends. Keep a daily cap (default
   10 outreach drafts/day) so every message is personal.
6. **Contacts.** Use only professional, publicly listed info (company team pages, published
   work emails, conference/podcast bios, GitHub). No personal addresses, phone numbers, or
   anything about people's private lives.
7. **Secrets.** API keys go in `.env` (gitignored). Never print or commit them.

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
