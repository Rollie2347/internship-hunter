"""Phase 4 entrypoint: compose a draft email and save it to Gmail as a
draft only -- never sent automatically (CLAUDE.md constraint 5).

Run with (from the internship-hunter folder, PowerShell):
    python -m internship_hunter.drafting.cli draft --company "Hidden Level" --contact "Jeff Cole"
    python -m internship_hunter.drafting.cli draft --company "Anduril Industries" --posting-id 42
    python -m internship_hunter.drafting.cli list

Each draft is one Claude API call (a few cents) plus one Gmail draft
creation (free). The daily cap (default 10, see .env DAILY_DRAFT_CAP) is
enforced before either happens.
"""

from __future__ import annotations

import argparse
import sys

from rich.console import Console
from rich.table import Table

from internship_hunter import anthropic_client, config, db
from internship_hunter.drafting import compose, daily_cap, gmail_client
from internship_hunter.models import Message

console = Console(width=120)


def load_profile_text() -> str:
    if not config.ABOUT_ME_PATH.exists():
        console.print(f"[red]{config.ABOUT_ME_PATH} doesn't exist -- fill it in first.[/red]")
        sys.exit(1)
    return config.ABOUT_ME_PATH.read_text(encoding="utf-8")


def load_resume_text() -> str:
    for path in (config.RESUME_PATH_TXT, config.RESUME_PATH_PDF):
        if path.exists() and path.suffix == ".txt":
            return path.read_text(encoding="utf-8")
    console.print(
        f"[yellow]No readable resume found at {config.RESUME_PATH_TXT} -- continuing with "
        "profile text only. (A .pdf resume isn't read as text yet; add a .txt version too "
        "if you want its content considered.)[/yellow]"
    )
    return ""


def cmd_draft(args: argparse.Namespace) -> None:
    conn = db.get_connection()
    db.init_db(conn)

    try:
        daily_cap.enforce_daily_cap(conn)
    except daily_cap.DailyCapReached as exc:
        console.print(f"[red]{exc}[/red]")
        sys.exit(1)

    company = db.get_company_by_name(conn, args.company)
    if company is None:
        console.print(f"[red]No company named '{args.company}' found.[/red]")
        sys.exit(1)

    contact = None
    if args.contact:
        contact = db.get_contact_by_name(conn, company.id, args.contact)
        if contact is None:
            console.print(f"[red]No contact named '{args.contact}' at '{args.company}' found.[/red]")
            sys.exit(1)

    posting = None
    if args.posting_id:
        row = conn.execute("SELECT * FROM postings WHERE id = ? AND company_id = ?", (args.posting_id, company.id)).fetchone()
        if row is None:
            console.print(f"[red]No posting #{args.posting_id} found at '{args.company}'.[/red]")
            sys.exit(1)
        posting = db.posting_from_row(row)

    profile_text = load_profile_text()
    resume_text = load_resume_text()

    client = anthropic_client.build_client(console)
    draft = compose.compose_email(client, profile_text, resume_text, company, contact=contact, posting=posting, ask_type=args.ask)

    warnings = compose.validate_draft(draft)
    console.print(f"[bold]Subject:[/bold] {draft.subject}\n")
    console.print(draft.body)
    if warnings:
        console.print("\n[yellow]Warnings (draft was still created -- review before sending):[/yellow]")
        for w in warnings:
            console.print(f"  - {w}")

    service = gmail_client.get_service()
    draft_id = gmail_client.create_draft(service, draft.subject, draft.body, to_email=(contact.email if contact else None))

    message = Message(
        company_id=company.id,
        contact_id=contact.id if contact else None,
        posting_id=posting.id if posting else None,
        channel="email",
        subject=draft.subject,
        body=draft.body,
        gmail_draft_id=draft_id,
        status="drafted",
    )
    db.insert_message(conn, message)

    console.print(f"\n[green]Saved as a Gmail draft (id {draft_id}). Go review and send it yourself in Gmail.[/green]")
    console.print(f"[dim]{daily_cap.remaining_today(conn)} draft(s) left today.[/dim]")


def cmd_batch(args: argparse.Namespace) -> None:
    """Cold-pitch the next N people who haven't been written to yet."""
    from internship_hunter.drafting import batch

    conn = db.get_connection()
    db.init_db(conn)
    if not batch.next_contacts(conn, 1) and not batch.due_follow_ups(conn):
        console.print(
            "[yellow]Every Colorado/Virginia contact on file already has a draft.[/yellow] Find more people first:\n"
            "  python -m internship_hunter.people.cli run"
        )
        return
    client = anthropic_client.build_client(console)
    created = batch.draft_batch(conn, client, gmail_client.get_service(), args.limit)
    for d in created:
        company, contact, message = d["company"], d["contact"], d["message"]
        to = batch.to_address(company, contact)
        to_note = f" [dim](To: {to})[/dim]" if to else " [yellow](To: blank -- no published address on file)[/yellow]"
        who = contact.name if contact else "the team"
        console.print(f"[green]{company.name}[/green] -- {who} [{d['kind']}]: {message.subject}{to_note}")
    console.print(
        f"\n[bold]{len(created)}[/bold] Gmail draft(s) created. Review and send each one yourself. "
        f"{daily_cap.remaining_today(conn)} left today."
    )


def cmd_auth(args: argparse.Namespace) -> None:
    """Sign in to Google again, this time also granting read access, so the
    bot can notice replies by itself. Opens a browser window."""
    gmail_client.run_consent_flow(gmail_client.ALL_SCOPES)
    console.print(
        "[green]Done.[/green] The bot can now send drafts you approve and watch those threads for replies. "
        "Restart the bot if it's running."
    )


def cmd_list(args: argparse.Namespace) -> None:
    conn = db.get_connection()
    db.init_db(conn)
    messages = db.list_messages(conn)
    if not messages:
        console.print("[yellow]No drafts created yet.[/yellow]")
        return
    companies_by_id = {c.id: c.name for c in db.list_companies(conn)}
    table = Table(show_lines=False)
    table.add_column("Created")
    table.add_column("Company")
    table.add_column("Subject")
    table.add_column("Status")
    table.add_column("Gmail draft id")
    for m in messages:
        table.add_row(
            m.created_at,
            companies_by_id.get(m.company_id, "?"),
            m.subject,
            m.status,
            m.gmail_draft_id or "",
        )
    console.print(table)
    console.print(f"\n[bold]{len(messages)}[/bold] draft(s) shown. {daily_cap.remaining_today(conn)} left today.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compose outreach emails and save them as Gmail drafts.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_draft = sub.add_parser("draft", help="Compose one draft and save it to Gmail.")
    p_draft.add_argument("--company", required=True)
    p_draft.add_argument("--contact", default=None, help="Contact name on file at that company.")
    p_draft.add_argument("--posting-id", type=int, default=None, dest="posting_id")
    p_draft.add_argument(
        "--ask", choices=list(compose.VALID_ASK_TYPES), default="auto",
        help="'referral' explicitly asks the contact to refer you or point you to the right person.",
    )
    p_draft.set_defaults(func=cmd_draft)

    p_batch = sub.add_parser("batch", help="Draft cold pitches to the next N people not yet written to.")
    p_batch.add_argument("--limit", type=int, default=5)
    p_batch.set_defaults(func=cmd_batch)

    p_auth = sub.add_parser("auth", help="Re-authorize Gmail with read access so replies are detected automatically.")
    p_auth.set_defaults(func=cmd_auth)

    p_list = sub.add_parser("list", help="List drafts created so far.")
    p_list.set_defaults(func=cmd_list)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
