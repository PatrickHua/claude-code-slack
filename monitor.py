#!/usr/bin/env python3
"""Live TUI monitor for the Slack bot. Tails .bot-events.jsonl and renders a dashboard."""

import json
import time
import sys
from pathlib import Path
from datetime import datetime, timezone
from collections import deque

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

def _resolve_event_log() -> Path:
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--env" and i < len(sys.argv) - 1:
            return Path(__file__).parent / f".bot-events-{Path(sys.argv[i + 1]).stem}.jsonl"
        if arg.startswith("--env="):
            return Path(__file__).parent / f".bot-events-{Path(arg.split('=', 1)[1]).stem}.jsonl"
    return Path(__file__).parent / ".bot-events-.env.jsonl"

EVENT_LOG = _resolve_event_log()
MAX_EVENTS = 40
REFRESH_HZ = 4


class BotMonitor:
    def __init__(self):
        self.events: deque = deque(maxlen=MAX_EVENTS)
        self.active_calls: dict[str, dict] = {}
        self.sessions: dict[str, dict] = {}
        self.stats = {"messages": 0, "claude_calls": 0, "errors": 0, "total_claude_s": 0.0}
        self.bot_info: dict = {}
        self.startup_info: dict = {}
        self.last_size = 0

    def poll(self):
        if not EVENT_LOG.exists():
            return
        size = EVENT_LOG.stat().st_size
        if size == self.last_size:
            return
        with open(EVENT_LOG) as f:
            if self.last_size > 0:
                f.seek(self.last_size)
            new_data = f.read()
        self.last_size = size
        for line in new_data.strip().split("\n"):
            if not line:
                continue
            try:
                ev = json.loads(line)
                self._process(ev)
            except json.JSONDecodeError:
                pass

    def _process(self, ev: dict):
        self.events.append(ev)
        etype = ev.get("event", "")

        if etype == "msg_in":
            self.stats["messages"] += 1
            sk = ev.get("session_key", "")
            if not sk:
                ch = ev.get("channel", "?")
                uid = ev.get("user", "?")
                sk = f"dm:{uid}:{ch}" if ev.get("is_dm") else f"channel:{ch}"
            self.sessions.setdefault(sk, {"msgs": 0, "last_text": "", "last_ts": ""})
            self.sessions[sk]["msgs"] += 1
            self.sessions[sk]["last_text"] = ev.get("text", "")[:60]
            self.sessions[sk]["last_ts"] = ev.get("ts", "")

        elif etype == "claude_start":
            sk = ev.get("session_key", "?")
            self.active_calls[sk] = {"start": ev.get("ts", ""), "start_mono": time.monotonic()}

        elif etype == "claude_done":
            sk = ev.get("session_key", "?")
            self.active_calls.pop(sk, None)
            self.stats["claude_calls"] += 1
            elapsed = ev.get("elapsed_s", 0)
            self.stats["total_claude_s"] += elapsed

        elif etype == "error":
            self.stats["errors"] += 1

        elif etype == "identity":
            self.bot_info = ev

        elif etype == "startup":
            self.startup_info = ev

    def render(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body"),
            Layout(name="log", size=16),
        )
        layout["body"].split_row(
            Layout(name="sessions", ratio=1),
            Layout(name="active", ratio=1),
        )

        # Header
        name = self.bot_info.get("name", "?")
        uid = self.bot_info.get("user_id", "?")
        gp = self.startup_info.get("group_policy", "?")
        dp = self.startup_info.get("dm_policy", "?")
        avg = (self.stats["total_claude_s"] / self.stats["claude_calls"]
               if self.stats["claude_calls"] else 0)
        header_text = (
            f"[bold cyan]{name}[/] ({uid})  "
            f"msgs:[bold]{self.stats['messages']}[/]  "
            f"claude_calls:[bold]{self.stats['claude_calls']}[/]  "
            f"avg:[bold]{avg:.1f}s[/]  "
            f"errors:[bold red]{self.stats['errors']}[/]  "
            f"group:[bold]{gp}[/] dm:[bold]{dp}[/]"
        )
        layout["header"].update(Panel(Text.from_markup(header_text), title="Slack Bot Monitor"))

        # Sessions panel
        st = Table(title="Sessions", expand=True, show_lines=False)
        st.add_column("Key", style="cyan", max_width=30)
        st.add_column("Msgs", justify="right", style="green", width=5)
        st.add_column("Last message", style="white")
        for sk, info in sorted(self.sessions.items()):
            label = sk
            if sk.startswith("dm:"):
                parts = sk.split(":")
                label = f"DM {parts[1][:8]}"
            elif sk.startswith("channel:"):
                label = f"#{sk.split(':')[1][:10]}"
            st.add_row(label, str(info["msgs"]), info["last_text"][:40])
        layout["sessions"].update(Panel(st))

        # Active Claude calls
        at = Table(title="Active Claude Calls", expand=True, show_lines=False)
        at.add_column("Session", style="yellow", max_width=25)
        at.add_column("Elapsed", justify="right", style="bold red", width=8)
        now = time.monotonic()
        if self.active_calls:
            for sk, info in self.active_calls.items():
                elapsed = now - info["start_mono"]
                label = sk.split(":")[-1][:12] if ":" in sk else sk[:12]
                color = "red" if elapsed > 30 else "yellow" if elapsed > 10 else "green"
                at.add_row(label, f"[{color}]{elapsed:.0f}s[/]")
        else:
            at.add_row("[dim]idle[/]", "[dim]-[/]")
        layout["active"].update(Panel(at))

        # Event log
        lt = Table(title="Event Log", expand=True, show_lines=False, show_header=True)
        lt.add_column("Time", style="dim", width=8)
        lt.add_column("Event", style="cyan", width=14)
        lt.add_column("Details", style="white")
        for ev in list(self.events)[-12:]:
            ts_str = ev.get("ts", "")
            try:
                dt = datetime.fromisoformat(ts_str)
                t = dt.astimezone().strftime("%H:%M:%S")
            except Exception:
                t = "?"
            etype = ev.get("event", "?")
            detail = self._event_detail(ev)
            style = "bold red" if etype == "error" else ""
            lt.add_row(t, f"[{style}]{etype}[/]" if style else etype, detail)
        layout["log"].update(Panel(lt))

        return layout

    @staticmethod
    def _event_detail(ev: dict) -> str:
        etype = ev.get("event", "")
        if etype == "msg_in":
            src = "DM" if ev.get("is_dm") else f"#{ev.get('channel', '?')[:8]}"
            return f"{ev.get('user', '?')[:8]} → {src}: {ev.get('text', '')[:50]}"
        if etype == "claude_start":
            return ev.get("session_key", "")[:30]
        if etype == "claude_done":
            return f"{ev.get('elapsed_s', 0):.1f}s  {ev.get('response_len', 0)} chars"
        if etype == "reply_sent":
            return f"{ev.get('text', '')[:40]} → {ev.get('channel', '?')}"
        if etype == "error":
            return ev.get("msg", "")[:60]
        if etype == "bang_cmd":
            return f"{ev.get('cmd', '')} session={ev.get('session_key', '')[:20]}"
        if etype == "startup":
            return f"group={ev.get('group_policy')} dm={ev.get('dm_policy')}"
        if etype == "identity":
            return f"{ev.get('name')} ({ev.get('user_id')})"
        if etype == "ready":
            return ev.get("msg", "")
        if etype == "queued":
            return f"batched → {ev.get('session_key', '')[:20]}"
        return str({k: v for k, v in ev.items() if k not in ("ts", "event")})[:60]


def main():
    console = Console()
    monitor = BotMonitor()

    if EVENT_LOG.exists():
        with open(EVENT_LOG) as f:
            for line in f:
                try:
                    monitor._process(json.loads(line))
                except Exception:
                    pass
        monitor.last_size = EVENT_LOG.stat().st_size

    console.print("[bold]Starting monitor... press Ctrl+C to quit[/]\n")

    with Live(monitor.render(), console=console, refresh_per_second=REFRESH_HZ, screen=True) as live:
        try:
            while True:
                monitor.poll()
                live.update(monitor.render())
                time.sleep(1 / REFRESH_HZ)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
