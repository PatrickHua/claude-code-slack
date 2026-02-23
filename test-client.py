#!/usr/bin/env python3
"""
Test client for the Slack Claude bot.
Send messages and see responses without leaving your terminal.

Setup (one-time):
  1. Go to https://api.slack.com/apps → Your App → OAuth & Permissions
  2. Under "User Token Scopes", add:  chat:write, im:write
  3. Click "Reinstall to Workspace" and approve
  4. Copy the "User OAuth Token" (starts with xoxp-)
  5. Add to .env:  SLACK_USER_TOKEN=xoxp-your-token-here

Usage:
  python test-client.py              # interactive REPL
  python test-client.py "hello"      # single message, print response, exit
  echo "hello" | python test-client.py  # pipe mode
"""

import os
import sys
import time
import readline  # noqa: F401 – enables arrow-key history in input()
from pathlib import Path
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from rich.console import Console
from rich.markdown import Markdown

console = Console()

# ── Load .env (same loader as slack-bot.py) ──────────────────────────────────

ENV_FILE = Path(__file__).parent / ".env"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
USER_TOKEN = os.environ.get("SLACK_USER_TOKEN")

if not BOT_TOKEN:
    console.print("[red]SLACK_BOT_TOKEN not set in .env[/red]")
    sys.exit(1)

if not USER_TOKEN:
    console.print("[red]SLACK_USER_TOKEN not set in .env[/red]")
    console.print()
    console.print("[dim]One-time setup:[/dim]")
    console.print("  1. Go to https://api.slack.com/apps → Your App → OAuth & Permissions")
    console.print("  2. Under [bold]User Token Scopes[/bold], add: [cyan]chat:write[/cyan], [cyan]im:write[/cyan]")
    console.print("  3. Click [bold]Reinstall to Workspace[/bold] and approve")
    console.print("  4. Copy the [bold]User OAuth Token[/bold] (starts with xoxp-)")
    console.print("  5. Add to .env:  [green]SLACK_USER_TOKEN=xoxp-your-token-here[/green]")
    sys.exit(1)

# ── Connect ──────────────────────────────────────────────────────────────────

bot = WebClient(token=BOT_TOKEN)
user = WebClient(token=USER_TOKEN)

try:
    bot_auth = bot.auth_test()
    user_auth = user.auth_test()
except SlackApiError as e:
    console.print(f"[red]Auth failed: {e.response['error']}[/red]")
    sys.exit(1)

bot_user_id = bot_auth["user_id"]
bot_name = bot_auth.get("user", "bot")
my_user_id = user_auth["user_id"]

try:
    dm = user.conversations_open(users=[bot_user_id])
    channel_id = dm["channel"]["id"]
except SlackApiError as e:
    if "missing_scope" in str(e):
        console.print("[red]Missing scope: add [bold]im:write[/bold] to User Token Scopes and reinstall.[/red]")
    else:
        console.print(f"[red]Could not open DM with bot: {e.response['error']}[/red]")
    sys.exit(1)

console.print(f"[dim]Bot:[/dim] {bot_name}  [dim]Channel:[/dim] {channel_id}")

# ── Core ─────────────────────────────────────────────────────────────────────

def send_and_wait(text: str, timeout: int = 300) -> str | None:
    """Send a message as the user and wait for the bot's reply."""
    try:
        result = user.chat_postMessage(channel=channel_id, text=text)
    except SlackApiError as e:
        if "missing_scope" in str(e):
            console.print("[red]Missing scope: add [bold]chat:write[/bold] to User Token Scopes and reinstall.[/red]")
        else:
            console.print(f"[red]Send failed: {e.response['error']}[/red]")
        return None

    sent_ts = result["ts"]
    deadline = time.time() + timeout

    while time.time() < deadline:
        time.sleep(2)
        try:
            history = bot.conversations_history(
                channel=channel_id, oldest=sent_ts, limit=10, inclusive=False
            )
        except SlackApiError:
            continue
        for msg in history.get("messages", []):
            if msg.get("user") == bot_user_id or msg.get("bot_id"):
                return msg.get("text", "(empty response)")
    return None


def display_response(text: str):
    """Pretty-print a bot response."""
    console.print()
    console.print(Markdown(text))
    console.print()


# ── Modes ────────────────────────────────────────────────────────────────────

def run_single(text: str):
    """Send one message, print response, exit."""
    console.print(f"[cyan]>[/cyan] {text}")
    with console.status("Waiting for bot response..."):
        response = send_and_wait(text)
    if response:
        display_response(response)
    else:
        console.print("[red]No response (timed out after 5 min)[/red]")
        sys.exit(1)


def run_repl():
    """Interactive read-eval-print loop."""
    console.print("[dim]Type a message and press Enter. Ctrl+C to quit.[/dim]\n")
    try:
        while True:
            try:
                text = console.input("[cyan]> [/cyan]")
            except EOFError:
                break
            if not text.strip():
                continue
            with console.status(""):
                response = send_and_wait(text)
            if response:
                display_response(response)
            else:
                console.print("[red]No response (timed out after 5 min)[/red]\n")
    except KeyboardInterrupt:
        console.print("\n[dim]Done.[/dim]")


# ── Main ─────────────────────────────────────────────────────────────────────

if len(sys.argv) > 1:
    run_single(" ".join(sys.argv[1:]))
elif not sys.stdin.isatty():
    text = sys.stdin.read().strip()
    if text:
        run_single(text)
else:
    run_repl()
