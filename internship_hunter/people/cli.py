"""Phase 3 entrypoint: find people at top-tier (tier 1) companies.

Run with (from the internship-hunter folder, PowerShell):
    python -m internship_hunter.people.cli run
    python -m internship_hunter.people.cli run --company "Vannevar Labs"
    python -m internship_hunter.people.cli list
    python -m internship_hunter.people.cli list --company "Vannevar Labs"
    python -m internship_hunter.people.cli web --limit 3     # web search (costs more -- see below)
    python -m internship_hunter.people.cli dedupe
    python -m internship_hunter.people.cli hunter --limit 5  # Hunter.io Domain Search (needs HUNTER_API_KEY)

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
from internship_hunter.people import dedupe, email_finder, hunter, people_finder, web_search

console = Console(width=120)


def run_for_company(client, conn, company) -> list:
    """Find and store contacts for one company. Returns newly-inserted
    Contact rows (empty if none found or nothing new)."""
    # Recorded up front so the daily run never spends a second API call on
    # a company whose site simply lists nobody.
    db.mark_people_checked(conn, company.id)
    if not company.contact_email:
        inbox = people_finder.fetch_published_email(company.website, (company.team_url, company.careers_url))
        if inbox:
            db.set_company_contact_email(conn, company.id, inbox)

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
        # Merged into the same person if another source already found them.
        stored, is_new = dedupe.store_contact(conn, contact)
        if is_new:
            inserted.append(stored)
    if inserted:
        email_finder.find_for_company(conn, company)
    return inserted


def cmd_emails(args: argparse.Namespace) -> None:
    """Search public sources for emails of everyone on file who has none."""
    conn = db.get_connection()
    db.init_db(conn)
    total = 0
    for company in db.list_companies(conn):
        if not args.everywhere and company.state not in config.PREFERRED_STATES:
            continue
        for contact, email, source in email_finder.find_for_company(conn, company, use_github=not args.no_github):
            total += 1
            console.print(f"[green]{company.name}:[/green] {contact.name} -- {email} [dim]({source})[/dim]")
    console.print(f"\n[bold]{total}[/bold] published address(es) found.")


def cmd_web(args: argparse.Namespace) -> None:
    """Web search for people at tier-1 companies never searched before."""
    conn = db.get_connection()
    db.init_db(conn)
    if args.company:
        company = db.get_company_by_name(conn, args.company)
        if company is None:
            console.print(f"[red]No company named '{args.company}' found.[/red]")
            sys.exit(1)
        companies = [company]
    else:
        companies = web_search.companies_to_search(conn, any_state=args.everywhere)[: args.limit]
    if not companies:
        console.print("[yellow]Every tier-1 Colorado/Virginia company has already been searched.[/yellow]")
        return
    client = anthropic_client.build_client(console)
    new_total = 0
    for company in companies:
        try:
            stored = web_search.run_for_company(client, conn, company)
        except anthropic.APIStatusError as exc:
            console.print(f"[red]{company.name}: Claude API error -- {exc}[/red]")
            continue
        if not stored:
            console.print(f"[dim]{company.name}: nothing found[/dim]")
        for contact, is_new in stored:
            new_total += is_new
            label = "new" if is_new else "already on file, merged"
            console.print(f"[green]{company.name}:[/green] {contact.name} -- {contact.title} [dim]({label})[/dim]")
            console.print(f"    {contact.fact} [dim]{contact.source_url}[/dim]")
    console.print(f"\n[bold]{new_total}[/bold] new contact(s) across {len(companies)} company(ies) searched.")


def cmd_hunter(args: argparse.Namespace) -> None:
    """Published emails from Hunter.io's Domain Search, for companies never looked up."""
    conn = db.get_connection()
    db.init_db(conn)
    if not config.HUNTER_API_KEY:
        console.print("[red]HUNTER_API_KEY is not set in .env.[/red]")
        sys.exit(1)
    try:
        results = hunter.run(conn, args.limit, any_state=args.everywhere)
    except hunter.HunterNotConfigured as exc:
        console.print(f"[red]{exc}[/red]")
        sys.exit(1)
    for company, stored in results:
        if not stored:
            console.print(f"[dim]{company.name}: nothing with a source page[/dim]")
        for who, email, source in stored:
            console.print(f"[green]{company.name}:[/green] {who} -- {email} [dim]({source})[/dim]")
    console.print(
        f"\n{len(results)} company(ies) looked up. "
        f"[bold]{hunter.remaining_this_month(conn)}[/bold] of {config.HUNTER_MONTHLY_LIMIT} Hunter searches left this month."
    )


def cmd_dedupe(args: argparse.Namespace) -> None:
    conn = db.get_connection()
    db.init_db(conn)
    console.print(f"[bold]{dedupe.merge_existing_duplicates(conn)}[/bold] duplicate contact(s) merged.")


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
        # Companies with nobody on file yet -- re-reading a team page we've
        # already read would just spend an API call to find nobody new. By
        # default only companies based in Colorado/Virginia, since those are
        # the only ones that get cold pitches (config.PREFERRED_STATES).
        companies = [
            c for c in db.list_companies(conn)
            if not db.list_contacts(conn, company_id=c.id)
            and (args.all_tiers or c.state in config.PREFERRED_STATES)
        ]

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
    p_run.add_argument(
        "--all-tiers", action="store_true", dest="all_tiers",
        help="Every company with no contacts on file yet, in any state (default: Colorado/Virginia only).",
    )
    p_run.set_defaults(func=cmd_run)

    p_emails = sub.add_parser("emails", help="Look for published emails of contacts that have none.")
    p_emails.add_argument("--everywhere", action="store_true", help="All companies, not just Colorado/Virginia.")
    p_emails.add_argument("--no-github", action="store_true", dest="no_github", help="Company websites only.")
    p_emails.set_defaults(func=cmd_emails)

    p_web = sub.add_parser("web", help="Web search for people at tier-1 companies (each company once).")
    p_web.add_argument("--company", default=None, help="Search this one company, even if searched before.")
    p_web.add_argument("--limit", type=int, default=3, help="How many companies to search this run (default 3).")
    p_web.add_argument("--everywhere", action="store_true", help="Tier-1 companies in any state, not just Colorado/Virginia.")
    p_web.set_defaults(func=cmd_web)

    p_hunter = sub.add_parser("hunter", help="Published emails from Hunter.io Domain Search (each domain once).")
    p_hunter.add_argument("--limit", type=int, default=5, help="How many companies to look up this run (default 5).")
    p_hunter.add_argument("--everywhere", action="store_true", help="Companies in any state, not just Colorado/Virginia.")
    p_hunter.set_defaults(func=cmd_hunter)

    p_dedupe = sub.add_parser("dedupe", help="Merge people who are on file twice at the same company.")
    p_dedupe.set_defaults(func=cmd_dedupe)

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
