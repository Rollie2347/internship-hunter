"""Command-line tool for managing the company target list.

Run with (from the internship-hunter folder, PowerShell):
    python -m internship_hunter.companies.cli load-seed
    python -m internship_hunter.companies.cli list
    python -m internship_hunter.companies.cli list --tier 1
    python -m internship_hunter.companies.cli list --state VA
    python -m internship_hunter.companies.cli show "Anduril Industries"
    python -m internship_hunter.companies.cli add --name "..." --website "https://..." ^
        --state VA --city Arlington --stage seed --what "..." --why "..." ^
        --careers-url "https://.../careers" --tier 1
    python -m internship_hunter.companies.cli remove "Some Company"
    python -m internship_hunter.companies.cli set-tier "Some Company" 2

(The ^ is PowerShell's line-continuation character, same idea as \\ in bash.)
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from internship_hunter import config, db
from internship_hunter.models import Company

SEED_DATA_PATH = Path(__file__).resolve().parent / "seed_data.json"

console = Console(width=120)


def _truncate(text: str, max_len: int = 40) -> str:
    return text if len(text) <= max_len else text[: max_len - 1].rstrip() + "…"


def load_seed(conn: sqlite3.Connection, seed_path: Path = SEED_DATA_PATH) -> tuple[int, int]:
    """Load companies from the seed JSON file. Skips any company whose name
    already exists in the DB (so re-running this is always safe). Returns
    (num_added, num_skipped)."""
    entries = json.loads(seed_path.read_text(encoding="utf-8"))
    added = 0
    skipped = 0
    for entry in entries:
        if db.get_company_by_name(conn, entry["name"]) is not None:
            skipped += 1
            continue
        company = Company(**entry)
        db.insert_company(conn, company)
        added += 1
    return added, skipped


def print_companies(companies: list[Company]) -> None:
    if not companies:
        console.print("[yellow]No companies match those filters.[/yellow]")
        return
    table = Table(show_lines=False)
    table.add_column("Tier")
    table.add_column("Name", style="bold")
    table.add_column("State/City")
    table.add_column("What they build")
    table.add_column("!", style="red")
    for c in companies:
        flag = "verify" if c.needs_verification else ""
        table.add_row(
            str(c.priority_tier),
            _truncate(c.name, 28),
            _truncate(f"{c.state} / {c.city}", 24),
            _truncate(c.what_they_build, 48),
            flag,
        )
    console.print(table)
    console.print("[dim]Use 'show \"<name>\"' for full details including the careers URL.[/dim]")


def cmd_load_seed(args: argparse.Namespace) -> None:
    conn = db.get_connection()
    db.init_db(conn)
    added, skipped = load_seed(conn)
    console.print(f"[green]Added {added} companies.[/green] Skipped {skipped} already in the database.")


def cmd_list(args: argparse.Namespace) -> None:
    conn = db.get_connection()
    db.init_db(conn)
    companies = db.list_companies(conn, tier=args.tier, state=args.state)
    print_companies(companies)
    console.print(f"\n[bold]{len(companies)}[/bold] company(ies) shown.")


def cmd_show(args: argparse.Namespace) -> None:
    conn = db.get_connection()
    db.init_db(conn)
    company = db.get_company_by_name(conn, args.name)
    if company is None:
        console.print(f"[red]No company named '{args.name}' found.[/red]")
        sys.exit(1)
    for field_name, value in company.__dict__.items():
        console.print(f"[bold]{field_name}:[/bold] {value}")


def cmd_add(args: argparse.Namespace) -> None:
    conn = db.get_connection()
    db.init_db(conn)
    company = Company(
        name=args.name,
        website=args.website,
        state=args.state,
        city=args.city,
        stage=args.stage,
        what_they_build=args.what,
        why_fit=args.why,
        careers_url=args.careers_url,
        priority_tier=args.tier,
        needs_verification=args.needs_verification,
        notes=args.notes or "",
    )
    try:
        db.insert_company(conn, company)
    except sqlite3.IntegrityError:
        console.print(f"[red]A company named '{args.name}' already exists.[/red]")
        sys.exit(1)
    console.print(f"[green]Added '{args.name}'.[/green]")


def cmd_remove(args: argparse.Namespace) -> None:
    conn = db.get_connection()
    db.init_db(conn)
    if db.delete_company(conn, args.name):
        console.print(f"[green]Removed '{args.name}'.[/green]")
    else:
        console.print(f"[red]No company named '{args.name}' found.[/red]")
        sys.exit(1)


def cmd_set_tier(args: argparse.Namespace) -> None:
    conn = db.get_connection()
    db.init_db(conn)
    if db.update_company_tier(conn, args.name, args.tier):
        console.print(f"[green]Set '{args.name}' to tier {args.tier}.[/green]")
    else:
        console.print(f"[red]No company named '{args.name}' found.[/red]")
        sys.exit(1)


def cmd_set_ats(args: argparse.Namespace) -> None:
    """Manually pin a company's ATS vendor+slug, for cases the scanner's
    automatic slug-guessing can't safely try on its own (e.g. the real slug
    is a short/generic word that would risk matching a different company --
    see scanner/ats_feeds.py's slug_candidates docstring). Find the real
    slug by opening the company's careers page and checking the job-listing
    URLs for boards.greenhouse.io/<slug>, jobs.lever.co/<slug>, or
    jobs.ashbyhq.com/<slug>."""
    conn = db.get_connection()
    db.init_db(conn)
    company = db.get_company_by_name(conn, args.name)
    if company is None:
        console.print(f"[red]No company named '{args.name}' found.[/red]")
        sys.exit(1)
    db.set_company_ats(conn, company.id, args.ats_type, args.slug)
    console.print(f"[green]Pinned '{args.name}' to {args.ats_type}:{args.slug}.[/green]")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage the Internship Hunter target company list.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_load = sub.add_parser("load-seed", help="Load the curated starter companies into the database.")
    p_load.set_defaults(func=cmd_load_seed)

    p_list = sub.add_parser("list", help="List companies, optionally filtered.")
    p_list.add_argument("--tier", type=int, choices=[1, 2, 3, 4], default=None)
    p_list.add_argument("--state", type=str, default=None, help="e.g. VA, CO, WI")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="Show full details for one company.")
    p_show.add_argument("name")
    p_show.set_defaults(func=cmd_show)

    p_add = sub.add_parser("add", help="Add a company by hand.")
    p_add.add_argument("--name", required=True)
    p_add.add_argument("--website", required=True)
    p_add.add_argument("--state", required=True, help="e.g. VA, CO, WI, Remote, Other")
    p_add.add_argument("--city", required=True)
    p_add.add_argument("--stage", required=True)
    p_add.add_argument("--what", required=True, help="What they build")
    p_add.add_argument("--why", required=True, help="Why it fits you")
    p_add.add_argument("--careers-url", required=True, dest="careers_url")
    p_add.add_argument("--tier", type=int, choices=[1, 2, 3, 4], required=True)
    p_add.add_argument("--needs-verification", action="store_true", dest="needs_verification")
    p_add.add_argument("--notes", default="")
    p_add.set_defaults(func=cmd_add)

    p_remove = sub.add_parser("remove", help="Remove a company by name.")
    p_remove.add_argument("name")
    p_remove.set_defaults(func=cmd_remove)

    p_tier = sub.add_parser("set-tier", help="Change a company's priority tier.")
    p_tier.add_argument("name")
    p_tier.add_argument("tier", type=int, choices=[1, 2, 3, 4])
    p_tier.set_defaults(func=cmd_set_tier)

    p_ats = sub.add_parser(
        "set-ats",
        help="Manually pin a company's ATS vendor+slug (for slugs too generic to auto-detect safely).",
    )
    p_ats.add_argument("name")
    p_ats.add_argument("ats_type", choices=["greenhouse", "lever", "ashby"])
    p_ats.add_argument("slug")
    p_ats.set_defaults(func=cmd_set_ats)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
