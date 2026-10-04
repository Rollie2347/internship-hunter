"""Inspect everything the scanner has stored so far (not just today's new
postings -- see scanner/scan.py for that).

Run with (from the internship-hunter folder, PowerShell):
    python -m internship_hunter.scanner.cli list
    python -m internship_hunter.scanner.cli list --company "Anduril Industries"
    python -m internship_hunter.scanner.cli list --skill-match strong
"""

from __future__ import annotations

import argparse

from rich.console import Console
from rich.table import Table

from internship_hunter import db

console = Console(width=120)


def cmd_list(args: argparse.Namespace) -> None:
    conn = db.get_connection()
    db.init_db(conn)

    company_id = None
    if args.company:
        company = db.get_company_by_name(conn, args.company)
        if company is None:
            console.print(f"[red]No company named '{args.company}' found.[/red]")
            return
        company_id = company.id

    postings = db.list_postings(conn, company_id=company_id, software_only=args.software_only)
    if args.skill_match:
        postings = [p for p in postings if p.skill_match == args.skill_match]

    companies_by_id = {c.id: c.name for c in db.list_companies(conn)}

    if not postings:
        console.print("[yellow]No postings match those filters.[/yellow]")
        return

    table = Table(show_lines=False)
    table.add_column("First seen")
    table.add_column("Company")
    table.add_column("Title")
    table.add_column("Software?")
    table.add_column("Intern/jr?")
    table.add_column("Skill fit")
    table.add_column("Clearance?")
    table.add_column("Citizenship?")
    for p in postings:
        # Skill fit only means something for an actual software posting --
        # shown here even when is_software_role is False so a non-software
        # "strong" match (e.g. a technician posting whose blurb happens to
        # mention Python in passing) doesn't read as a real recommendation.
        table.add_row(
            p.first_seen_date,
            companies_by_id.get(p.company_id, "?"),
            p.title,
            "yes" if p.is_software_role else "",
            "yes" if p.is_intern_or_junior else "",
            p.skill_match,
            "yes" if p.clearance_required else "",
            "yes" if p.citizenship_required else "",
        )
    console.print(table)
    console.print(f"\n[bold]{len(postings)}[/bold] posting(s) shown.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect stored job postings.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="List stored postings.")
    p_list.add_argument("--company", default=None)
    p_list.add_argument("--skill-match", choices=["strong", "stretch", "gap", "unclear"], default=None)
    p_list.add_argument("--software-only", action="store_true")
    p_list.set_defaults(func=cmd_list)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
