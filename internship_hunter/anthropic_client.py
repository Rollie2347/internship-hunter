"""Builds the shared Anthropic client, with one friendly error message
instead of each phase's CLI repeating the same check."""

from __future__ import annotations

import sys

import anthropic

from internship_hunter import config


def build_client(console=None) -> anthropic.Anthropic:
    if not config.ANTHROPIC_API_KEY:
        message = (
            "ANTHROPIC_API_KEY is not set in .env -- get a key from "
            "https://console.anthropic.com and add it before running this."
        )
        if console is not None:
            console.print(f"[red]{message}[/red]")
        else:
            print(message)
        sys.exit(1)
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
