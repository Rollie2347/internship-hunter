"""Phase 2 entrypoint: scan every company's job feed, store what's found,
and report only what's new today.

Run with (from the internship-hunter folder, PowerShell):
    python -m internship_hunter.scanner.scan
    python -m internship_hunter.scanner.scan --no-telegram
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from rich.console import Console
from rich.table import Table

from internship_hunter import config, db
from internship_hunter.models import Company, Posting
from internship_hunter.notify import telegram_client
from internship_hunter.scanner import ats_feeds, careers_fallback, filters

console = Console(width=120)

MAX_TELEGRAM_ITEMS = 15  # keep the push notification short; full list is always in the DB/CLI


@dataclass
class NewPosting:
    company: Company
    posting: Posting
    worth_notifying: bool


def scan_company(conn, company: Company) -> list[NewPosting]:
    """Fetch, classify, and store postings for one company. Returns the
    postings that are new as of today (not every posting fetched)."""
    if company.ats_type:
        raw_postings = ats_feeds.fetch_known(company.ats_type, company.ats_slug)
    else:
        raw_postings, confirmed = ats_feeds.detect_and_fetch(company.name)
        if confirmed:
            ats_type, ats_slug = confirmed[0]
            db.set_company_ats(conn, company.id, ats_type, ats_slug)
        else:
            careers_fallback.careers_url_is_reachable(company.careers_url)
            db.set_company_manual_check_needed(conn, company.id, True)

    new_postings: list[NewPosting] = []
    for raw in raw_postings:
        is_software = filters.is_software_role(raw.title, raw.text)
        is_intern = filters.is_intern_or_junior(raw.title)
        clearance = filters.requires_clearance(raw.text, raw.title)
        citizenship = filters.requires_citizenship(raw.text, raw.title)
        skill_match = filters.classify_skill_match(raw.title, raw.text)

        posting = Posting(
            company_id=company.id,
            external_id=raw.external_id,
            title=raw.title,
            location=raw.location,
            url=raw.url,
            ats_source=raw.ats_source,
            is_software_role=is_software,
            is_intern_or_junior=is_intern,
            clearance_required=clearance,
            citizenship_required=citizenship,
            skill_match=skill_match,
        )
        posting_id, is_new = db.upsert_posting(conn, posting)
        if is_new:
            posting.id = posting_id
            worth = filters.worth_notifying(is_software, is_intern, clearance, skill_match)
            new_postings.append(NewPosting(company=company, posting=posting, worth_notifying=worth))
    return new_postings


def run_scan(conn) -> list[NewPosting]:
    all_new: list[NewPosting] = []
    companies = db.list_companies(conn)
    for company in companies:
        all_new.extend(scan_company(conn, company))
    return all_new


def print_report(all_new: list[NewPosting], conn) -> None:
    notify = [n for n in all_new if n.worth_notifying]
    skipped = [n for n in all_new if not n.worth_notifying]

    if notify:
        table = Table(title="New postings worth your time")
        table.add_column("Company")
        table.add_column("Title")
        table.add_column("Location")
        table.add_column("Skill fit")
        table.add_column("URL", overflow="fold")
        for n in notify:
            table.add_row(n.company.name, n.posting.title, n.posting.location, n.posting.skill_match, n.posting.url)
        console.print(table)
    else:
        console.print("[yellow]No new software intern/junior postings today.[/yellow]")

    if skipped:
        console.print(
            f"\n[dim]{len(skipped)} other new posting(s) seen today but not surfaced "
            "(not software, not intern/junior-level, needs a clearance, or outside your "
            "current skill set) -- still saved in the database.[/dim]"
        )

    manual_check = [c for c in db.list_companies(conn) if c.manual_check_needed]
    if manual_check:
        names = ", ".join(c.name for c in manual_check)
        console.print(f"\n[yellow]No public ATS feed found for:[/yellow] {names} -- check their careers page by hand.")


def build_telegram_digest(all_new: list[NewPosting]) -> str | None:
    notify = [n for n in all_new if n.worth_notifying]
    skipped_count = len(all_new) - len(notify)
    if not notify:
        return None

    lines = [f"\U0001F50E {len(notify)} new software posting(s) worth a look:"]
    for n in notify[:MAX_TELEGRAM_ITEMS]:
        tag = {"strong": "\u2705 strong fit", "stretch": "\U0001F7E1 stretch", "unclear": "\u2753 unclear fit"}.get(
            n.posting.skill_match, n.posting.skill_match
        )
        lines.append(f"\n{n.company.name} -- {n.posting.title} ({n.posting.location})\n{tag}\n{n.posting.url}")
    if len(notify) > MAX_TELEGRAM_ITEMS:
        lines.append(f"\n...and {len(notify) - MAX_TELEGRAM_ITEMS} more. Run the scanner CLI to see the full list.")
    if skipped_count:
        lines.append(f"\n({skipped_count} other new posting(s) filtered out -- clearance, non-software, or outside your current skills.)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Scan company job feeds for new software postings.")
    parser.add_argument("--no-telegram", action="store_true", help="Skip sending a Telegram digest.")
    args = parser.parse_args(argv)

    conn = db.get_connection()
    db.init_db(conn)

    all_new = run_scan(conn)
    print_report(all_new, conn)

    if not args.no_telegram:
        digest = build_telegram_digest(all_new)
        if digest:
            try:
                telegram_client.send_message(digest)
                console.print("\n[green]Telegram digest sent.[/green]")
            except Exception as exc:  # noqa: BLE001 -- don't let a Telegram hiccup hide the scan results above
                console.print(f"\n[red]Could not send Telegram digest: {exc}[/red]")


if __name__ == "__main__":
    main()
