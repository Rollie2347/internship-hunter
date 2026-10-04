"""Command-line tool for setting up and testing Telegram notifications.

Run with (from the internship-hunter folder, PowerShell):
    python -m internship_hunter.notify.cli fetch-chat-id
    python -m internship_hunter.notify.cli test
    python -m internship_hunter.notify.cli send "Some message"
"""

from __future__ import annotations

import argparse
import sys

from dotenv import set_key
from rich.console import Console

from internship_hunter import config
from internship_hunter.notify import telegram_client

console = Console()


def cmd_fetch_chat_id(args: argparse.Namespace) -> None:
    console.print(
        "[dim]Looking for a message you've sent the bot... "
        "(open the bot in Telegram and send it 'hi' first if this fails)[/dim]"
    )
    try:
        chat_id = telegram_client.fetch_latest_chat_id()
    except Exception as exc:  # noqa: BLE001 -- surface any Telegram/network error plainly
        console.print(f"[red]{exc}[/red]")
        sys.exit(1)
    # quote_mode="never" -- the default quotes the value (e.g. '8421163775'),
    # which python-dotenv/config.py parse correctly either way, but a naive
    # `grep | cut` read of .env (e.g. when wiring up a CI secret by hand)
    # copies the quote characters along with it, producing an invalid value
    # downstream. Found live: that exact mistake broke the chat_id GitHub
    # Actions was using, and Telegram's API rejected it with a 400.
    set_key(str(config.PROJECT_ROOT / ".env"), "TELEGRAM_CHAT_ID", str(chat_id), quote_mode="never")
    console.print(f"[green]Found chat id {chat_id} and saved it to .env.[/green]")


def cmd_test(args: argparse.Namespace) -> None:
    try:
        telegram_client.send_message("\u2705 Internship Hunter is connected to your Telegram.")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]{exc}[/red]")
        sys.exit(1)
    console.print("[green]Test message sent -- check Telegram.[/green]")


def cmd_send(args: argparse.Namespace) -> None:
    try:
        telegram_client.send_message(args.text)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]{exc}[/red]")
        sys.exit(1)
    console.print("[green]Message sent.[/green]")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Set up and test Telegram notifications.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser(
        "fetch-chat-id",
        help="Find your Telegram chat id from a message you sent the bot, and save it to .env.",
    )
    p_fetch.set_defaults(func=cmd_fetch_chat_id)

    p_test = sub.add_parser("test", help="Send a canned test message.")
    p_test.set_defaults(func=cmd_test)

    p_send = sub.add_parser("send", help="Send a custom message.")
    p_send.add_argument("text")
    p_send.set_defaults(func=cmd_send)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
