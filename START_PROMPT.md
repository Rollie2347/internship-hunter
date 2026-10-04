# Paste this into Claude Code (run it from this folder)

Read CLAUDE.md and everything in profile/ first. Then help me build "Internship Hunter," a
Python tool on Windows that helps me land a year-long internship at a defense-tech startup
(or similar tech company) in Virginia, Colorado, or Wisconsin. I'm 15 and do online school at
night.

Start in plan mode. Before writing code, ask me any questions you need answered (for example
which accounts and API keys I have, my birthday month, and whether I'm a US citizen). Then
propose a plan and wait for my OK.

Build it in these phases. Each phase should run end to end and have tests before we move on:

**Phase 1: Target list.** Build a database of companies: name, website, location/office,
stage, what they build, why they fit me, and careers page URL. Seed it by searching the web
for defense-tech and dual-use startups with offices in VA, CO, and WI (Northern Virginia,
Denver/Boulder, Colorado Springs, Madison, Milwaukee), plus investor portfolio pages of
defense-focused VCs. Let me add or remove companies by hand. Tag each one with a priority tier
from CLAUDE.md.

**Phase 2: Job scanner.** For each company, detect its applicant tracking system and pull
postings from the public job-board feeds (Greenhouse, Lever, Ashby JSON endpoints), falling
back to the careers page. Flag intern, apprentice, co-op, and high-school roles, along with
any junior role in my target locations. Mark roles that require a clearance (skip these) and
roles that require US citizenship (flag these). Store everything in SQLite and only show me
new postings each day.

**Phase 3: People finder.** For each top-tier company, find 1–3 relevant people (founders,
CTO, engineering leads, recruiters) from public, professional sources only, such as company
team pages, blog posts, podcasts, GitHub, and conference talks. Record where each fact came
from. Find a work email only if it's publicly listed, or use the company's careers/general
address. No LinkedIn scraping.

**Phase 4: Drafting.** Use the Anthropic API to write a tailored application answer, cover
note, or cold email for each opportunity or person, based on my profile/about_me.md and
resume. Every message must be short (under 150 words), mention something specific about
their work, say honestly that I'm 15, link one project as proof, and make one clear ask (a
15-minute call, or "can I send you my resume?"). It should also be honest about hours:
full-time in summer, and year-round once I'm 16. Save the results as Gmail drafts through the
Gmail API. Never send automatically. Cap it at 10 drafts per day.

**Phase 5: Apply assist.** For a posting I pick, open it in a Playwright browser, prefill the
fields from my profile, attach my resume, and then stop and wait for me to review and click
Submit myself.

**Phase 6: Tracker and follow-ups.** Build a simple dashboard (Streamlit) that shows every
company, posting, contact, and message with its status (found, drafted, sent, replied,
interviewing, rejected). Remind me to follow up 7 days after a message with no reply, and draft
the follow-up for me.

Also add a weekly "other routes" report that finds programs and events where I could meet
people in person: DoD STEM and service-lab programs for high schoolers, hackathons, defense
tech meetups and conferences in my states, and robotics competitions.

Rules: follow every constraint in CLAUDE.md. Keep secrets in .env. Write Windows-friendly
code and give me PowerShell commands. Explain what you're doing in plain language as you go,
because I want to understand the code, not just run it.
