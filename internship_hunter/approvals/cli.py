"""Entrypoint for the Telegram approval flow.

Run with (from the internship-hunter folder, PowerShell):
    python -m internship_hunter.approvals.cli bot          # leave this running
    python -m internship_hunter.approvals.cli propose --limit 5
    python -m internship_hunter.approvals.cli status
    python -m internship_hunter.approvals.cli preview

`bot` is the one you normally want: it sends the daily batch, listens for
your Approve/Skip taps, and opens approved forms on this PC. `preview`
shows what's next in the queue without sending or spending anything.
"""

from __future__ import annotations

import argparse

from rich.console import Console
from rich.table import Table

from internship_hunter import anthropic_client, db
from internship_hunter.approvals import bot, queue
from internship_hunter.scanner import filters

console = Console(width=120)

LOCATION_LABELS = {0: "VA/CO/DC", 1: "other US", 2: "remote/unlisted", 3: "Wisconsin"}


def _conn():
    conn = db.get_connection()
    db.init_db(conn)
    return conn


def cmd_bot(args: argparse.Namespace) -> None:
    console.print("[green]Approval bot running.[/green] Send it /help in Telegram. Ctrl+C here to stop.")
    try:
        bot.run_forever(_conn())
    except KeyboardInterrupt:
        console.print("\nStopped.")


def cmd_propose(args: argparse.Namespace) -> None:
    conn = _conn()
    sent = bot.propose_batch(conn, anthropic_client.build_client(console), args.limit)
    console.print(f"[green]Sent {sent} application card(s) to Telegram.[/green] Run the bot to act on them.")


def cmd_status(args: argparse.Namespace) -> None:
    console.print(queue.build_status_text(_conn()))


def cmd_preview(args: argparse.Namespace) -> None:
    conn = _conn()
    postings = queue.next_postings(conn, args.limit)
    if not postings:
        console.print("[yellow]Nothing in the queue.[/yellow]")
    else:
        table = Table(title="Next up for approval")
        for column in ("Company", "Title", "Where", "Skill fit", "Location"):
            table.add_column(column, overflow="fold")
        for p in postings:
            company = db.get_company(conn, p.company_id)
            table.add_row(
                company.name, p.title, LOCATION_LABELS[filters.location_rank(p.location)],
                p.skill_match, p.location[:60],
            )
        console.print(table)
    skipped = queue.count_skipped_for_location(conn)
    if skipped:
        console.print(f"[dim]{skipped} matching posting(s) left out for being outside the US.[/dim]")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Approve prefilled applications from Telegram.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("bot", help="Run the approval bot (leave it running).").set_defaults(func=cmd_bot)

    p_propose = sub.add_parser("propose", help="Send the next application cards to Telegram once, then exit.")
    p_propose.add_argument("--limit", type=int, default=5)
    p_propose.set_defaults(func=cmd_propose)

    sub.add_parser("status", help="Print the status summary.").set_defaults(func=cmd_status)

    p_preview = sub.add_parser("preview", help="Show what's next in the queue (sends nothing, costs nothing).")
    p_preview.add_argument("--limit", type=int, default=25)
    p_preview.set_defaults(func=cmd_preview)

    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
