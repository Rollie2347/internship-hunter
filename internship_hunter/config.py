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
DB_PATH = DATA_DIR / "tracker.db"
PROFILE_DIR = PROJECT_ROOT / "profile"
ABOUT_ME_PATH = PROFILE_DIR / "about_me.md"
# The plan called for resume.pdf, but the student's actual file is a plain
# .txt resume -- support either, preferring .txt since that's what's there.
RESUME_PATH_TXT = PROFILE_DIR / "resume.txt"
RESUME_PATH_PDF = PROFILE_DIR / "resume.pdf"

# Load .env (if present) into os.environ before we read any secrets below.
load_dotenv(PROJECT_ROOT / ".env")

# --- Secrets / per-student settings (from .env) -------------------------
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GOOGLE_OAUTH_CLIENT_SECRET_PATH = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET_PATH", "")
GMAIL_DRAFT_ACCOUNT = os.environ.get("GMAIL_DRAFT_ACCOUNT", "")
OWNER_EMAIL = os.environ.get("OWNER_EMAIL", "")
DAILY_DRAFT_CAP = int(os.environ.get("DAILY_DRAFT_CAP", "10"))

# Telegram bot for status updates TO the student (new postings, follow-up
# reminders, the weekly "other routes" digest). Never used to contact
# companies/contacts -- that stays on Gmail drafts, see GMAIL_DRAFT_ACCOUNT.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

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
    "mechanical", "electrical engineer", "structural", "propulsion",
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

# Outreach safety rails
MAX_DRAFTS_PER_DAY_DEFAULT = 10
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
