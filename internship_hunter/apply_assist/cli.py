"""Phase 5 entrypoint: prefill a real application and pause for review.

Run with (from the internship-hunter folder, PowerShell):
    python -m internship_hunter.apply_assist.cli fill 44

Opens a real, visible browser window. Never clicks Submit -- you review
and submit it yourself.
"""

from __future__ import annotations

import argparse
import sys

from rich.console import Console

from internship_hunter import config, db
from internship_hunter.apply_assist import playwright_fill, profile_fields

console = Console(width=120)


def cmd_fill(args: argparse.Namespace) -> None:
    conn = db.get_connection()
    db.init_db(conn)

    row = conn.execute("SELECT * FROM postings WHERE id = ?", (args.posting_id,)).fetchone()
    if row is None:
        console.print(f"[red]No posting #{args.posting_id} found.[/red]")
        sys.exit(1)
    posting = db.posting_from_row(row)
    company = next((c for c in db.list_companies(conn) if c.id == posting.company_id), None)

    if not config.ABOUT_ME_PATH.exists():
        console.print(f"[red]{config.ABOUT_ME_PATH} doesn't exist -- fill it in first.[/red]")
        sys.exit(1)
    about_me_text = config.ABOUT_ME_PATH.read_text(encoding="utf-8")
    resume_text = config.RESUME_PATH_TXT.read_text(encoding="utf-8") if config.RESUME_PATH_TXT.exists() else ""
    applicant = profile_fields.build_applicant_info(about_me_text, resume_text)

    resume_path = config.RESUME_PATH_PDF if config.RESUME_PATH_PDF.exists() else None
    if resume_path is None:
        console.print(
            f"[yellow]No PDF resume at {config.RESUME_PATH_PDF} -- skipping the resume upload step. "
            "Add one there if you want it attached automatically.[/yellow]"
        )

    company_label = company.name if company else f"company #{posting.company_id}"
    console.print(f"[bold]Opening:[/bold] {posting.title} at {company_label}\n{posting.url}")

    summary = playwright_fill.fill_application(posting, applicant, resume_path=resume_path, headless=args.headless)
    console.print(f"\n[green]Done.[/green] {len(summary['filled'])} field(s) filled, {len(summary['skipped'])} left for you.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prefill a real application in a real browser, then pause for review.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_fill = sub.add_parser("fill", help="Open and prefill one posting's application.")
    p_fill.add_argument("posting_id", type=int)
    p_fill.add_argument("--headless", action="store_true", help="Run without a visible window (not the point of this phase, but useful for a quick check).")
    p_fill.set_defaults(func=cmd_fill)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
