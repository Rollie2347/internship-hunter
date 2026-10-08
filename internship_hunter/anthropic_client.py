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


class NoAnswer(RuntimeError):
    """Claude returned no usable answer (it ran out of output tokens, or declined)."""


def parsed(response):
    """The structured answer from client.messages.parse(), or a clear error
    saying why there isn't one -- instead of an AttributeError on None
    somewhere further down."""
    answer = getattr(response, "parsed_output", None)
    if answer is None:
        reason = getattr(response, "stop_reason", None) or "unknown reason"
        raise NoAnswer(f"Claude returned no answer ({reason}). Nothing was drafted; try again.")
    return answer
