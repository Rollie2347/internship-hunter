"""Central configuration: secrets from .env, and the constants that encode the
rules in CLAUDE.md so every module agrees on them instead of re-typing them.

Nothing in here should be a surprise if you've read CLAUDE.md -- this file just
turns that document into values Python can use.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# --- Paths -------------------------------------------------------------
# PROJECT_ROOT is the internship-hunter/ folder, regardless of where a script
# is run from. Using pathlib (not raw strings) is what makes this work the
# same on Windows and everywhere else.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
# TRACKER_DB_PATH lets the GitHub Actions scanner keep its own database
# (data/cloud_tracker.db, committed) while this PC's tracker -- which holds
# your applications, contacts and sent emails -- stays local and out of git.
DB_PATH = Path(os.environ["TRACKER_DB_PATH"]) if os.environ.get("TRACKER_DB_PATH") else DATA_DIR / "tracker.db"
PROFILE_DIR = PROJECT_ROOT / "profile"
ABOUT_ME_PATH = PROFILE_DIR / "about_me.md"
# The plan called for resume.pdf, but the student's actual file is a plain
# .txt resume -- support either, preferring .txt since that's what's there.
RESUME_PATH_TXT = PROFILE_DIR / "resume.txt"
RESUME_PATH_PDF = PROFILE_DIR / "resume.pdf"
# The student's own answers to application questions, built up over time --
# see apply_assist/my_answers.py.
MY_ANSWERS_PATH = PROFILE_DIR / "my_answers.md"

# Load .env (if present) into os.environ before we read any secrets below.
load_dotenv(PROJECT_ROOT / ".env")

# --- Secrets / per-student settings (from .env) -------------------------
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GOOGLE_OAUTH_CLIENT_SECRET_PATH = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET_PATH", "")
GMAIL_DRAFT_ACCOUNT = os.environ.get("GMAIL_DRAFT_ACCOUNT", "")
OWNER_EMAIL = os.environ.get("OWNER_EMAIL", "")
# One shared daily budget for everything that lands in front of the student
# for approval: application cards on Telegram AND outreach Gmail drafts.
DAILY_DRAFT_CAP = int(os.environ.get("DAILY_DRAFT_CAP", "25"))

# Telegram bot for status updates TO the student (new postings, follow-up
# reminders, the weekly "other routes" digest). Never used to contact
# companies/contacts -- that stays on Gmail drafts, see GMAIL_DRAFT_ACCOUNT.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Optional. Only used to look up PUBLIC GitHub profiles when searching for
# a contact's published email; a token just raises GitHub's rate limit.
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

# How many people a day the bot puts in front of the student on its own
# (emails + LinkedIn cards together). He chose 5 on 2026-10-08, then raised
# it to 10 the same day once the cards were quick to send. /pitch, /linkedin
# and /li can ask for more, up to the hard caps (DAILY_DRAFT_CAP,
# LINKEDIN_DAILY_CAP).
OUTREACH_PER_DAY = int(os.environ.get("OUTREACH_PER_DAY", "10"))
# The hour (this PC's clock, 0-23) the day's people are sent: 7 = 7 AM. The
# slow preparation -- reading every job board, looking for new people --
# runs an hour earlier, so the cards themselves arrive on time. If the PC
# was off or asleep then, both happen as soon as it's back.
DAILY_RUN_HOUR = int(os.environ.get("DAILY_RUN_HOUR", "7"))

# Optional. Hunter.io Domain Search only (people/hunter.py) -- never its
# Email Finder, which guesses. The free plan allows few searches a month.
HUNTER_API_KEY = os.environ.get("HUNTER_API_KEY", "")
HUNTER_MONTHLY_LIMIT = int(os.environ.get("HUNTER_MONTHLY_LIMIT", "25"))

# LinkedIn assist cards per day -- its own budget, separate from
# DAILY_DRAFT_CAP. The bot only ever writes a note and a link; the student
# opens LinkedIn and sends the request himself (see linkedin_assist/).
LINKEDIN_DAILY_CAP = int(os.environ.get("LINKEDIN_DAILY_CAP", "10"))
# How many companies a day the bot may run a web search for people on. 0 =
# never on its own (the default): unlike reading a team page, a web search
# costs real money per company, so it stays off until the student turns it on.
WEB_PEOPLE_SEARCH_PER_DAY = int(os.environ.get("WEB_PEOPLE_SEARCH_PER_DAY", "0"))

# --- Rules from CLAUDE.md, as data -------------------------------------

# Priority tiers, in the order CLAUDE.md ranks them. Lower number = higher
# priority. Every company in the database must have one of these.
PRIORITY_TIERS = {
    1: "Early/mid-stage defense-tech & dual-use startup",
    2: "Larger defense-tech company",
    3: "AI lab or other strong tech company",
    4: "Government/lab program open to high schoolers",
}

# Target states. The student is based in Wisconsin with family options in
# Northern Virginia and Colorado, and chose to weight all three equally --
# so this is a set to filter by, not a ranked list.
TARGET_STATES = {"VA", "CO", "WI"}

# Updated 2026-10-07 (twice): the student wants ONLY Colorado and Virginia,
# where he has family to live with. filters.location_rank() still sorts
# every location into a bucket --
#   0 = an office in Virginia or Colorado
#   1 = elsewhere in the US (incl. Washington D.C.)
#   2 = remote, or no location given
#   3 = Wisconsin
#   4 = outside the US / unrecognized
# -- but only buckets up to QUEUE_MAX_LOCATION_RANK are ever sent for
# approval, and only companies based in PREFERRED_STATES get cold pitches.
# To let D.C. back in, add "DC" to PREFERRED_STATES.
PREFERRED_STATES = {"VA", "CO"}
QUEUE_MAX_LOCATION_RANK = 0
HOME_STATE = "WI"
LOCATION_RANK_NOT_QUEUED = 4
# Job boards often give a bare city with no state ("San Francisco",
# "Pittsburgh") -- seen live on 8 real intern postings that would otherwise
# have been dropped as "outside the US".
US_CITY_STATES = {
    "san francisco": "CA", "los angeles": "CA", "san diego": "CA", "el segundo": "CA",
    "mountain view": "CA", "palo alto": "CA", "san mateo": "CA", "san jose": "CA",
    "new york city": "NY", "nyc": "NY", "boston": "MA", "seattle": "WA", "austin": "TX",
    "chicago": "IL", "atlanta": "GA", "pittsburgh": "PA", "huntsville": "AL", "dayton": "OH",
    "denver": "CO", "boulder": "CO", "arlington": "VA", "reston": "VA", "herndon": "VA",
    "mclean": "VA", "chantilly": "VA", "madison": "WI", "milwaukee": "WI",
}
US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}

# A location outside TARGET_STATES is still worth keeping if the role is
# remote-friendly -- CLAUDE.md calls remote a "bonus tier", not excluded.
REMOTE_OK_LABEL = "Remote"

# Child-labor-law facts (29 CFR 570.35 / 570.37, FLSA ages 14-15) that other
# modules (mainly the weekly report and drafting prompts) need to state
# honestly. These are federal; VA and WI also require a work permit under 16.
FEDERAL_HOUR_LIMITS_END_AGE = 16
MINOR_HOUR_LIMITS = {
    "school_day_max_hours": 3,
    "school_week_max_hours": 18,
    "non_school_week_max_hours": 40,
    "non_school_day_max_hours": 8,
    "earliest_start_hour": 7,  # 7am
    "latest_end_hour_default": 19,  # 7pm, Labor Day to June 1
    "latest_end_hour_summer": 21,  # 9pm, June 1 to Labor Day
}

STUDENT_TURNS_16 = "2027-04"  # year-month, per CLAUDE.md

# Role-focus keywords (CLAUDE.md: "software only"). A posting title/description
# matching one of these is in scope; matching one of SOFTWARE_EXCLUDE_KEYWORDS
# without also matching a SOFTWARE_ROLE_KEYWORDS term is treated as out of scope.
SOFTWARE_ROLE_KEYWORDS = {
    "software", "swe", "full stack", "full-stack", "backend", "back-end",
    "frontend", "front-end", "firmware", "embedded software", "devops",
    "site reliability", "data engineer", "machine learning", "ml engineer",
    "ai engineer", "cybersecurity", "security engineer", "computer vision",
    "platform engineer", "web developer", "app developer", "cloud engineer",
    "qa engineer", "test engineer", "data scientist",
    # A posting naming a specific language is a strong software signal even
    # if it never says the word "software" (e.g. just "Python Intern").
    "python", "javascript", "typescript", "java developer", "c# developer",
}
SOFTWARE_EXCLUDE_KEYWORDS = {
    "mechanical", "electrical engineer", "electrical engineering", "structural", "propulsion",
    "manufacturing", "sales", "business development", "account executive",
    "recruiter", "operations", "supply chain", "program manager",
    "technician", "machinist", "welder",
}

# --- Skill-match tiers (Phase 2), derived from profile/resume.txt,
# https://rollieo.xyz, and https://github.com/Rollie2347 on 2026-10-04 ---
#
# These do NOT gate whether a posting is stored -- every software posting is
# kept. They control whether a posting gets surfaced to the student as
# "worth your time right now" vs. quietly kept out of the Telegram digest.
# Presence of ANY "strong" keyword wins (a Python/JS backend role that also
# mentions Kubernetes is still a real fit) -- "gap" only wins when nothing
# familiar shows up at all.
#
# strong: Python, JavaScript/Node, React, Firebase, Docker, PyTorch, and
#   LLM/agent integration are exactly what he's shipped (Argus, Relio, the AI
#   receptionist) and used in MIT coursework. Java comes from FRC robotics.
# stretch: adjacent skills with partial exposure (SQL course, Dockerized
#   deploys that touched a cloud box) but no dedicated project yet.
# gap: no evidence anywhere in the resume/site/GitHub repos -- no C/C++,
#   Rust, Go, embedded/firmware, Kubernetes-at-scale, formal DevOps/SRE,
#   cybersecurity, or native iOS/Android (Swift/Kotlin) work.
STUDENT_SKILL_STRONG = {
    "python", "javascript", "typescript", "node", "node.js", "react",
    "full stack", "full-stack", "backend", "back-end", "frontend",
    "front-end", "web developer", "web development", "web app",
    "machine learning", "ml engineer", "ai engineer", "llm", "generative ai",
    "agent", "agentic", "chatbot", "pytorch", "firebase", "docker",
    "rest api", "api integration", "automation", "robotics software", "java",
    "websocket", "oauth",
}
STUDENT_SKILL_STRETCH = {
    "data engineer", "data science", "data scientist", "sql",
    "computer vision", "cloud", "aws", "gcp", "azure", "mobile app",
    "react native", "ios", "android",
}
STUDENT_SKILL_GAP = {
    "embedded", "firmware", "c++", "rust", "golang", "kubernetes",
    "site reliability", "sre", "devops", "cybersecurity",
    "security engineer", "penetration test", "swift", "kotlin", "rtos",
    "fpga", "verilog", "vhdl", "low-level", "device driver", "kernel",
    "network engineer", "systems administrator", "mechanical", "electrical",
}

# Keywords for flagging clearance/citizenship requirements on a posting's
# own text (separate from the company-level tier). Per CLAUDE.md: clearance
# -> skip from outreach candidates; citizenship -> fine, just flag.
CLEARANCE_KEYWORDS = {
    "security clearance", "active clearance", "ts/sci", "top secret",
    "secret clearance", "polygraph", "must be able to obtain a clearance",
    "eligibility for a security clearance", "clearance required",
    "must possess an active",
}
CITIZENSHIP_KEYWORDS = {
    "u.s. citizen", "us citizen", "united states citizen",
    "citizenship required", "must be a u.s. citizen", "must be a us citizen",
}

# Keywords that mark a posting as intern/junior/high-school-accessible.
# Deliberately excludes "new grad" and "entry level" -- both of those
# normally require a completed bachelor's degree, which rules them out for
# a 15-year-old even though the job board treats them as "junior" roles.
INTERN_OR_JUNIOR_KEYWORDS = {
    "intern", "internship", "co-op", "co op", "apprentice", "apprenticeship",
    "junior", "high school", "high-school", "student",
}

# Programs that say "intern" but are closed to a high schooler by definition.
INELIGIBLE_PROGRAM_KEYWORDS = {
    "skillbridge", "phd", "ph.d", "doctoral", "postdoc", "mba", "masters", "master's", "graduate",
}

# Outreach safety rails
MAX_DRAFTS_PER_DAY_DEFAULT = 25
NEVER_AUTOMATE_PLATFORMS = {"linkedin"}

# --- People finder (Phase 3) ---
# Common paths tried against each company's website root to self-detect a
# team/about/leadership page, same self-learning approach as the ATS slug
# detection in scanner/ats_feeds.py -- but lower-risk here, since these are
# all paths on the company's OWN domain rather than a third-party board
# that could belong to someone else.
TEAM_PAGE_PATHS = ("/team", "/about", "/about-us", "/leadership", "/company", "/our-team")

# 5, not 3 -- referrals are often easier to get from a rank-and-file
# engineer than a 15-minute call is from a CEO, so it's worth keeping more
# than just the 3 most senior names on file per company.
MAX_CONTACTS_PER_COMPANY = 5
PEOPLE_FINDER_MODEL = "claude-opus-5"

# Web search for people (people/web_search.py). One company = one search
# request (at most WEB_SEARCH_MAX_USES searches inside it) plus one small
# extraction call per page that's then read.
WEB_SEARCH_MAX_USES = 4
WEB_PAGES_PER_COMPANY = 3
# Never searched, never fetched (CLAUDE.md constraint 4).
WEB_SEARCH_BLOCKED_DOMAINS = ["linkedin.com"]

# --- LinkedIn assist ---
# The student's LinkedIn account allows 200 characters in a connection note
# (he checked on 2026-10-08; paid accounts get 300).
LINKEDIN_NOTE_MAX_CHARS = 200
# What the model is asked to aim for, to leave a little room.
LINKEDIN_NOTE_TARGET_CHARS = LINKEDIN_NOTE_MAX_CHARS - 20
LINKEDIN_REPLY_MAX_CHARS = 600

# Output limit for every Claude call. The model thinks before it answers and
# that thinking counts against this limit: at the old value of 1024 a hard
# request (a 200-character LinkedIn note) used the whole allowance thinking
# and returned no answer at all -- found on the first live run, 2026-10-08.
# You pay for tokens actually used, not for the limit.
MAX_OUTPUT_TOKENS = 16000

# --- Drafting (Phase 4) ---
DRAFTING_MODEL = "claude-opus-5"
MAX_DRAFT_WORDS = 150


def availability_statement(today=None) -> str:
    """A factual, honest hours statement for the drafting prompt -- computed
    here, not left for the model to reason about, since getting a child-
    labor-law date wrong is exactly the kind of thing CLAUDE.md requires we
    get right every time. STUDENT_TURNS_16 is "YYYY-MM"; `today` is injected
    in tests, defaults to the real date otherwise."""
    from datetime import date

    today = today or date.today()
    turns_16_year, turns_16_month = (int(x) for x in STUDENT_TURNS_16.split("-"))
    turns_16_date = date(turns_16_year, turns_16_month, 1)

    if today >= turns_16_date:
        return "I'm 16 now, so federal hour limits for minors no longer apply to me -- I'm available full-time, year-round."

    turns_16_label = turns_16_date.strftime("%B %Y")
    weekly_cap = MINOR_HOUR_LIMITS["school_week_max_hours"]
    return (
        f"Right now I'm 15, so I'm available part-time -- after school and on weekends, up to "
        f"{weekly_cap} hours/week, per federal rules for my age. Starting {turns_16_label}, when "
        f"I turn 16, those limits end and I'm available full-time, year-round."
    )

# --- Tracker / follow-ups (Phase 6) ---
# bounced = the address didn't exist (Gmail returned a delivery failure)
# skipped / not_found = LinkedIn cards only: he passed on the person, or
# couldn't find their profile
# call / referred = the steps after a reply: a call is booked, then they
# refer or introduce him (the goal of the whole tool)
MESSAGE_STATUSES = (
    "drafted", "sent", "replied", "call", "referred", "interviewing", "rejected", "bounced", "skipped", "not_found",
)
# A software posting seen this recently means the company is hiring now --
# used to decide who to write to first, not as something to apply to.
HIRING_SIGNAL_DAYS = 14
# Notes he pastes somewhere himself (a contact form, or to someone he knows).
PASTE_MESSAGE_MAX_WORDS = 120
# The placeholder company that people he already knows are filed under.
NETWORK_COMPANY_NAME = "My network"
FOLLOW_UP_AFTER_DAYS = 7

# --- Approval queue (Telegram) ---
# proposed  = card sent to Telegram, waiting on Approve/Skip
# approved  = student tapped Approve; the bot opens the prefilled form next
# opened    = form was opened and closed without a confirmation page being seen
# submitted = the student submitted it (confirmation page seen, or he said so)
APPLICATION_STATUSES = ("proposed", "approved", "skipped", "opened", "submitted", "interviewing", "rejected")
MAX_ANSWER_WORDS = 120
