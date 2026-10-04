"""Phase 3 entrypoint: find people at top-tier (tier 1) companies.

Run with (from the internship-hunter folder, PowerShell):
    python -m internship_hunter.people.cli run
    python -m internship_hunter.people.cli run --company "Vannevar Labs"
    python -m internship_hunter.people.cli list
    python -m internship_hunter.people.cli list --company "Vannevar Labs"

Each run against a company makes one Claude API call (a few cents at most
across the whole tier-1 list) -- see README.md for the cost note.
"""

from __future__ import annotations

import argparse
import sys

import anthropic
from rich.console import Console
from rich.table import Table

from internship_hunter import anthropic_client, config, db
from internship_hunter.people import people_finder

console = Console(width=120)


def run_for_company(client, conn, company) -> list:
    """Find and store contacts for one company. Returns newly-inserted
    Contact rows (empty if none found or nothing new)."""
    url = company.team_url
    if not url:
        url = people_finder.find_team_page_url(company.website, company.careers_url)
        if url:
            db.set_company_team_url(conn, company.id, url)

    if not url:
        return []

    page_text = people_finder.fetch_page_text(url)
    if not page_text:
        return []

    people = people_finder.extract_people(client, company.name, url, page_text)
    contacts = people_finder.to_contacts(people, company.id, url)

    inserted = []
    for contact in contacts:
        if db.get_contact_by_name(conn, company.id, contact.name) is not None:
            continue  # already have this person on file
        contact_id = db.insert_contact(conn, contact)
        contact.id = contact_id
        inserted.append(contact)
    return inserted


def cmd_run(args: argparse.Namespace) -> None:
    conn = db.get_connection()
    db.init_db(conn)
    client = anthropic_client.build_client(console)

    if args.company:
        company = db.get_company_by_name(conn, args.company)
        if company is None:
            console.print(f"[red]No company named '{args.company}' found.[/red]")
            sys.exit(1)
        companies = [company]
    else:
        companies = db.list_companies(conn, tier=1)

    no_page_found = []
    total_new = 0
    for company in companies:
        try:
            new_contacts = run_for_company(client, conn, company)
        except anthropic.APIStatusError as exc:
            console.print(f"[red]{company.name}: Claude API error -- {exc}[/red]")
            continue
        if not company.team_url and not people_finder.find_team_page_url(
            company.website, company.careers_url
        ):
            no_page_found.append(company.name)
        if new_contacts:
            total_new += len(new_contacts)
            for c in new_contacts:
                console.print(f"[green]{company.name}:[/green] {c.name} -- {c.title}")
        else:
            console.print(f"[dim]{company.name}: nothing new[/dim]")

    console.print(f"\n[bold]{total_new}[/bold] new contact(s) found across {len(companies)} company(ies).")
    if no_page_found:
        console.print(f"[yellow]No team/about page found for:[/yellow] {', '.join(no_page_found)}")


def cmd_list(args: argparse.Namespace) -> None:
    conn = db.get_connection()
    db.init_db(conn)

    company_id = None
    if args.company:
        company = db.get_company_by_name(conn, args.company)
        if company is None:
            console.print(f"[red]No company named '{args.company}' found.[/red]")
            sys.exit(1)
        company_id = company.id

    contacts = db.list_contacts(conn, company_id=company_id)
    if not contacts:
        console.print("[yellow]No contacts stored yet.[/yellow]")
        return

    companies_by_id = {c.id: c.name for c in db.list_companies(conn)}
    table = Table(show_lines=False)
    table.add_column("Company")
    table.add_column("Name")
    table.add_column("Title")
    table.add_column("Fact")
    table.add_column("Email")
    table.add_column("Source", overflow="fold")
    for c in contacts:
        table.add_row(
            companies_by_id.get(c.company_id, "?"),
            c.name,
            c.title,
            c.fact,
            c.email or "",
            c.source_url,
        )
    console.print(table)
    console.print(f"\n[bold]{len(contacts)}[/bold] contact(s) shown.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Find and browse people at tier-1 companies.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Find people at tier-1 companies (or one company).")
    p_run.add_argument("--company", default=None)
    p_run.set_defaults(func=cmd_run)

    p_list = sub.add_parser("list", help="Browse stored contacts.")
    p_list.add_argument("--company", default=None)
    p_list.set_defaults(func=cmd_list)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
