#!/usr/bin/env python3
"""
Slack bot that connects to Claude Code CLI.

Setup:
1. pip install -r requirements.txt
2. Create a Slack app at https://api.slack.com/apps
3. Enable Socket Mode and get an App-Level Token
4. Add Bot Token Scopes and install to workspace
5. Copy .env.example to .env and fill in values
6. Run: python slack-bot.py
"""

import subprocess
import json
import os
import re
import uuid
import mimetypes
import time
import logging
import threading
import urllib.request
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
from slack_bolt import App, Assistant
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slackify_markdown import slackify_markdown

# Load env file: --env <path> or default .env
import sys
_env_path = None
for i, arg in enumerate(sys.argv[1:], 1):
    if arg == "--env" and i < len(sys.argv) - 1:
        _env_path = Path(sys.argv[i + 1])
        break
    if arg.startswith("--env="):
        _env_path = Path(arg.split("=", 1)[1])
        break

ENV_FILE = _env_path or (Path(__file__).parent / ".env")
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip()
else:
    print(f"Error: env file not found: {ENV_FILE}")
    sys.exit(1)

# Silence all library DEBUG noise
logging.basicConfig(level=logging.WARNING)
for _lg in ("slack_bolt", "slack_sdk", "slack", "markdown_it", "urllib3", "asyncio"):
    logging.getLogger(_lg).setLevel(logging.WARNING)

# ── Structured event log ─────────────────────────────────────────────────────
EVENT_LOG = Path(__file__).parent / f".bot-events-{ENV_FILE.stem}.jsonl"

def emit_event(event_type: str, **kw):
    """Append a structured JSON event to the log file and print a one-liner."""
    entry = {"ts": datetime.now(timezone.utc).isoformat(), "event": event_type, **kw}
    try:
        with open(EVENT_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass
    # Compact console line
    detail = ""
    if event_type == "msg_in":
        src = "DM" if kw.get("is_dm") else f"#{kw.get('channel','?')}"
        detail = f"{kw.get('user','?')} in {src}: {kw.get('text','')[:80]}"
    elif event_type == "claude_start":
        detail = f"session={kw.get('session_key','?')}"
    elif event_type == "claude_done":
        detail = f"{kw.get('elapsed_s',0):.1f}s session={kw.get('session_key','?')}"
    elif event_type == "reply_sent":
        detail = f"{len(kw.get('text',''))} chars → {kw.get('channel','?')}"
    elif event_type == "error":
        detail = kw.get("msg", "")
    elif event_type == "bang_cmd":
        detail = f"{kw.get('cmd','')} by {kw.get('user','?')}"
    else:
        detail = str(kw) if kw else ""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {event_type:14s} {detail}", flush=True)

# Core config
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN")
WORKSPACE = os.environ.get("CLAUDE_WORKSPACE", str(Path.home()))
CLAUDE_PATH = os.environ.get("CLAUDE_PATH", "claude")
_agent_name = ENV_FILE.stem  # e.g. "research-agent" from envs/research-agent.env
SESSION_FILE = Path.home() / f".slack-claude-sessions-{_agent_name}.json"

# Access control - global gate (applies to all message types)
ALLOWED_USERS = [x.strip() for x in os.environ.get("ALLOWED_USERS", "").split(",") if x.strip()]

# DM policy
DM_ENABLED = os.environ.get("DM_ENABLED", "true").lower() == "true"
DM_POLICY = os.environ.get("DM_POLICY", "open")  # open, allowlist
DM_ALLOW_FROM = [x.strip() for x in os.environ.get("DM_ALLOW_FROM", "").split(",") if x.strip()]

# Channel/group policy
GROUP_POLICY = os.environ.get("GROUP_POLICY", "mention")  # mention, open, allowlist
GROUP_ALLOW_FROM = [x.strip() for x in os.environ.get("GROUP_ALLOW_FROM", "").split(",") if x.strip()]

# Behavior
REACT_EMOJI = os.environ.get("REACT_EMOJI", "thinking_face")
REPLY_IN_THREAD = os.environ.get("REPLY_IN_THREAD", "true").lower() == "true"

# Media handling
TEMP_DIR = Path(WORKSPACE) / ".slack-tmp"
SLACK_FILE_SIZE_LIMIT = 20 * 1024 * 1024  # 20MB practical limit

# Mime types Claude can read directly with its Read tool
READABLE_MIME_PREFIXES = ("image/", "text/")
READABLE_MIME_TYPES = (
    "application/pdf",
    "application/json",
    "application/xml",
    "application/javascript",
    "application/x-yaml",
    "application/x-python",
)

def build_context_prompt() -> str:
    identity = f"You are {BOT_NAME}, a Slack bot assistant." if BOT_NAME else "You are a Slack bot assistant."
    return f"""{identity} Respond in the same language the user writes in. Be helpful and concise.

RULES:
1. Just return plain text. The bot framework posts your reply to Slack automatically.
2. NEVER use Bash to send messages, reply, or post. There is no slack-reply skill.
3. Only use tools when the user explicitly asks (e.g. "react to my message", "upload a file", "search the web").
4. Each message starts with a context line like: [slack type=dm channel=D123 msg_ts=... thread_ts=...]
   - "type" tells you if this is a DM or channel message.
   - "channel" is the Slack channel/DM ID — pass it to skills like slack-upload or slack-react.
   - "msg_ts" is the message timestamp — use it for slack-react.
   - Do NOT use these to send messages. Only for react/upload skills when asked.

"""

# Resolved at startup via auth_test() + users_info()
BOT_USER_ID: str | None = None
BOT_NAME: str | None = None

# Cache for Slack user display names: user_id -> display_name
_USER_NAME_CACHE: dict[str, str] = {}


def get_display_name(client, user_id: str) -> str:
    """Resolve a Slack user ID to a display name, with caching."""
    if user_id in _USER_NAME_CACHE:
        return _USER_NAME_CACHE[user_id]
    try:
        info = client.users_info(user=user_id)
        profile = info["user"]["profile"]
        name = profile.get("display_name") or profile.get("real_name") or user_id
        _USER_NAME_CACHE[user_id] = name
        return name
    except Exception:
        return user_id


def make_session_key(user_id: str, channel: str, is_dm: bool) -> str:
    """DMs get per-user sessions; channels get shared sessions for group brainstorm."""
    if is_dm:
        return f"dm:{user_id}:{channel}"
    return f"channel:{channel}"


def build_slack_context(channel: str, is_dm: bool, ts: str = None, thread_ts: str = None) -> str:
    """Build a metadata line so Claude knows the Slack context for skill usage."""
    kind = "dm" if is_dm else "channel"
    parts = [f"[slack type={kind} channel={channel}"]
    if ts:
        parts.append(f"msg_ts={ts}")
    if thread_ts:
        parts.append(f"thread_ts={thread_ts}")
    return " ".join(parts) + "]"


# Markdown table pattern
_TABLE_RE = re.compile(
    r"(\|.+\|\n)((?:\|[-:| ]+\|\n))(\|.+\|\n)+",
    re.MULTILINE,
)


# ── Session management ────────────────────────────────────────────────────────

def load_sessions() -> dict:
    if SESSION_FILE.exists():
        return json.loads(SESSION_FILE.read_text())
    return {}


def save_sessions(sessions: dict):
    SESSION_FILE.write_text(json.dumps(sessions, indent=2))


def migrate_sessions():
    """Remove old-format session keys that lack dm:/channel: prefix."""
    sessions = load_sessions()
    stale = [k for k in sessions if not k.startswith("dm:") and not k.startswith("channel:")]
    if stale:
        for k in stale:
            del sessions[k]
        save_sessions(sessions)
        emit_event("migrate", removed=len(stale))


# ── Session locks & message batching ─────────────────────────────────────────
# One lock per session key: ensures Claude calls are sequential, not parallel.
# Messages that arrive while a session is busy get batched into the next call.

_session_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
_pending_messages: dict[str, list[str]] = defaultdict(list)
_pending_lock = threading.Lock()

BATCH_WAIT_SECONDS = 1.5


def send_with_lock(session_key: str, prompt: str, slack_ctx: str = "") -> str:
    """Send prompt to Claude, serialized per session. Batches rapid messages."""
    lock = _session_locks[session_key]

    if not lock.acquire(blocking=False):
        with _pending_lock:
            _pending_messages[session_key].append(prompt)
        emit_event("queued", session_key=session_key)
        return None

    try:
        time.sleep(BATCH_WAIT_SECONDS)
        with _pending_lock:
            queued = _pending_messages.pop(session_key, [])

        all_prompts = [prompt] + queued
        if len(all_prompts) > 1:
            combined = "\n\n".join(all_prompts)
            emit_event("batched", session_key=session_key, count=len(all_prompts))
        else:
            combined = prompt

        emit_event("claude_start", session_key=session_key)
        t0 = time.monotonic()
        result = send_to_claude_with_session(session_key, combined, slack_ctx)
        elapsed = time.monotonic() - t0
        emit_event("claude_done", session_key=session_key, elapsed_s=round(elapsed, 1),
                    response_len=len(result) if result else 0)
        return result
    finally:
        lock.release()


# ── Access control ────────────────────────────────────────────────────────────

def is_dm_allowed(user_id: str) -> bool:
    """Check if a user is allowed to send DMs to the bot."""
    if not DM_ENABLED:
        return False
    if ALLOWED_USERS and user_id not in ALLOWED_USERS:
        return False
    if DM_POLICY == "allowlist":
        return user_id in DM_ALLOW_FROM
    return True


def is_channel_allowed(user_id: str, channel_id: str) -> bool:
    """Check if a user/channel is allowed for group/channel messages."""
    if ALLOWED_USERS and user_id not in ALLOWED_USERS:
        return False
    if GROUP_POLICY == "allowlist":
        return channel_id in GROUP_ALLOW_FROM
    return True


def should_respond_in_channel(event_type: str, text: str) -> bool:
    """Check if the bot should respond to this channel message based on group policy."""
    if GROUP_POLICY == "open":
        return True
    if GROUP_POLICY == "mention":
        if event_type == "app_mention":
            return True
        return BOT_USER_ID is not None and f"<@{BOT_USER_ID}>" in text
    if GROUP_POLICY == "allowlist":
        return True  # channel check already done in is_channel_allowed
    return False


# ── Utilities ─────────────────────────────────────────────────────────────────

def cleanup_temp_dir():
    """Create temp dir and remove stale files older than 1 hour."""
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - 3600
    for f in TEMP_DIR.iterdir():
        if f.is_file() and f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)


def format_file_size(size_bytes: int | None) -> str:
    """Human-readable file size."""
    if not size_bytes:
        return "unknown size"
    if size_bytes < 1024:
        return f"{size_bytes}B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    return f"{size_bytes / (1024 * 1024):.1f}MB"


def _is_mime_readable(mime_type: str | None) -> bool:
    """Check if Claude can read this mime type directly."""
    if not mime_type:
        return False
    if any(mime_type.startswith(p) for p in READABLE_MIME_PREFIXES):
        return True
    return mime_type in READABLE_MIME_TYPES


def download_slack_file(url: str, dest_path: str):
    """Download a file from Slack using bot token for auth."""
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {SLACK_BOT_TOKEN}")
    with urllib.request.urlopen(req) as response:
        with open(dest_path, "wb") as f:
            f.write(response.read())


def build_file_prompt(file_name: str, mime_type: str | None, file_size: int | None, file_path: str) -> str:
    """Build the prompt to send to Claude for a file attachment."""
    size_str = format_file_size(file_size)

    if mime_type and mime_type.startswith("image/"):
        return f"The user sent an image: {file_name}. Use the Read tool to view the image at {file_path} and describe or respond to what you see."

    if _is_mime_readable(mime_type):
        return f"The user sent a file: {file_name} ({mime_type}, {size_str}). Use the Read tool to open {file_path} and respond based on its contents."

    if mime_type and (mime_type.startswith("video/") or mime_type.startswith("audio/")):
        return f"The user sent a media file: {file_name} ({mime_type}, {size_str}). The file is at {file_path}. Use Bash with ffprobe/ffmpeg to analyze it."

    return f"The user sent a file: {file_name} ({mime_type or 'unknown type'}, {size_str}). The file is saved at {file_path}. Use Bash tools to inspect or process it as appropriate."


def strip_bot_mention(text: str) -> str:
    """Remove bot @mention from text."""
    if not text:
        return text
    if BOT_USER_ID:
        return re.sub(rf"<@{re.escape(BOT_USER_ID)}>\s*", "", text).strip()
    return re.sub(r"<@[A-Z0-9]+>\s*", "", text).strip()


def _convert_table(match: re.Match) -> str:
    """Convert a Markdown table to a Slack-readable list."""
    lines = [ln.strip() for ln in match.group(0).strip().splitlines() if ln.strip()]
    if len(lines) < 2:
        return match.group(0)
    headers = [h.strip() for h in lines[0].strip("|").split("|")]
    start = 2 if re.fullmatch(r"[|\s:\-]+", lines[1]) else 1
    rows: list[str] = []
    for line in lines[start:]:
        cells = [c.strip() for c in line.strip("|").split("|")]
        cells = (cells + [""] * len(headers))[: len(headers)]
        parts = [f"*{headers[i]}*: {cells[i]}" for i in range(len(headers)) if cells[i]]
        if parts:
            rows.append(" · ".join(parts))
    return "\n".join(rows)


def markdown_to_slack_mrkdwn(text: str) -> str:
    """Convert Markdown to Slack mrkdwn format, including tables."""
    if not text:
        return text
    text = _TABLE_RE.sub(_convert_table, text)
    return slackify_markdown(text)


# ── Bang commands (!clear, !compact, !context) ───────────────────────────────

COMPACT_PROMPT = (
    "Provide a concise summary of our entire conversation so far. "
    "Include key decisions, context, and any important details. "
    "This summary will be used to seed a fresh session, so make it complete enough "
    "that you can pick up where we left off."
)

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
CONTEXT_PREVIEW_CHARS = 300


def _find_session_file(session_id: str) -> Path | None:
    """Locate the JSONL file for a Claude session."""
    if not CLAUDE_PROJECTS_DIR.exists():
        return None
    for project_dir in CLAUDE_PROJECTS_DIR.iterdir():
        candidate = project_dir / f"{session_id}.jsonl"
        if candidate.exists():
            return candidate
    return None


def _read_session_messages(path: Path) -> list[dict]:
    """Read user/assistant message pairs from a session JSONL file."""
    messages = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") not in ("user", "assistant"):
            continue
        msg = entry.get("message", {})
        role = msg.get("role", entry.get("type"))
        content = msg.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                block.get("text", "") for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
        if content:
            messages.append({"role": role, "text": content})
    return messages


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def _format_context_preview(messages: list[dict]) -> str:
    """Show first few and last few messages, truncated."""
    n = CONTEXT_PREVIEW_CHARS
    lines = []

    show_head = messages[:3]
    show_tail = messages[-3:] if len(messages) > 6 else messages[3:]
    skipped = len(messages) - len(show_head) - len(show_tail)

    for msg in show_head:
        prefix = "*user:*" if msg["role"] == "user" else "*assistant:*"
        lines.append(f"{prefix} {_truncate(msg['text'], n)}")

    if skipped > 0:
        lines.append(f"\n_... {skipped} messages omitted ..._\n")

    for msg in show_tail:
        prefix = "*user:*" if msg["role"] == "user" else "*assistant:*"
        lines.append(f"{prefix} {_truncate(msg['text'], n)}")

    return "\n".join(lines)


def handle_bang_command(text: str, session_key: str, say, reply_kwargs: dict) -> bool:
    """Handle !commands. Returns True if a command was handled."""
    cmd = text.strip().lower()

    if cmd == "!clear":
        sessions = load_sessions()
        if session_key in sessions:
            del sessions[session_key]
            save_sessions(sessions)
        emit_event("bang_cmd", cmd="!clear", session_key=session_key)
        say(text="Session cleared. Next message starts fresh.", **reply_kwargs)
        return True

    if cmd == "!context":
        sessions = load_sessions()
        session_id = sessions.get(session_key)
        if not session_id:
            say(text="No active session.", **reply_kwargs)
            return True

        # Find the session JSONL file under ~/.claude/projects/
        session_file = _find_session_file(session_id)
        if not session_file:
            say(text=f"Session `{session_id}` exists but file not found.", **reply_kwargs)
            return True

        messages = _read_session_messages(session_file)
        if not messages:
            say(text="Session file is empty.", **reply_kwargs)
            return True

        total = len(messages)
        preview = _format_context_preview(messages)
        size_kb = session_file.stat().st_size / 1024
        header = f"*Session:* `{session_id}`\n*Messages:* {total} | *File size:* {size_kb:.1f}KB\n\n"
        say(text=header + preview, **reply_kwargs)
        return True

    if cmd == "!compact":
        sessions = load_sessions()
        session_id = sessions.get(session_key)
        if not session_id:
            say(text="No active session to compact.", **reply_kwargs)
            return True

        say(text="Compacting session...", **reply_kwargs)

        summary, _ = run_claude(COMPACT_PROMPT, session_id)
        if summary is None:
            del sessions[session_key]
            save_sessions(sessions)
            say(text="Session expired. Next message starts fresh.", **reply_kwargs)
            return True

        # Start a new session seeded with the summary
        del sessions[session_key]
        save_sessions(sessions)
        seed_prompt = build_context_prompt() + (
            f"Here is a summary of our previous conversation:\n\n{summary}\n\n"
            "Confirm you've absorbed this context with a brief acknowledgment."
        )
        response, new_session_id = run_claude(seed_prompt)
        if new_session_id:
            sessions = load_sessions()
            sessions[session_key] = new_session_id
            save_sessions(sessions)

        response = markdown_to_slack_mrkdwn(response or "Session compacted.")
        say(text=response, **reply_kwargs)
        return True

    return False


# ── Claude integration ────────────────────────────────────────────────────────

def run_claude(message: str, session_id: str = None) -> tuple[str, str]:
    """Run Claude and return (response, new_session_id). Handles expired sessions."""
    cmd = [
        CLAUDE_PATH, "-p", message,
        "--output-format", "json",
        "--max-turns", "10",
        "--allowedTools", "Bash,Read,Write,Edit,MultiEdit,WebFetch,WebSearch,Glob,Grep,LS,TodoRead,TodoWrite"
    ]

    if session_id:
        cmd.extend(["--resume", session_id])

    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=WORKSPACE, env=env, timeout=300)
    except subprocess.TimeoutExpired:
        return "Claude timed out after 5 minutes.", None

    try:
        data = json.loads(result.stdout)
        response = data.get("result") or ""
        new_session_id = data.get("session_id")
        subtype = data.get("subtype", "")
        if subtype == "error_max_turns" and not response:
            response = "(Claude used all turns on tool calls without producing a final answer. Try again or use !clear.)"
        return response or "No response", new_session_id
    except json.JSONDecodeError:
        error_text = result.stdout or result.stderr or ""
        if "No conversation found" in error_text or "session" in error_text.lower():
            return None, None
        return error_text or "Error running Claude", None


def send_to_claude_with_session(session_key: str, prompt: str, slack_ctx: str = "") -> str:
    """Send prompt to Claude with session management. Returns response text."""
    sessions = load_sessions()
    session_id = sessions.get(session_key)

    ctx_prefix = f"{slack_ctx}\n" if slack_ctx else ""

    if session_id:
        response, new_session_id = run_claude(ctx_prefix + prompt, session_id)
        if response is None:
            del sessions[session_key]
            save_sessions(sessions)
            session_id = None

    if not session_id:
        response, new_session_id = run_claude(build_context_prompt() + ctx_prefix + prompt)

    if new_session_id:
        sessions[session_key] = new_session_id
        save_sessions(sessions)

    response = markdown_to_slack_mrkdwn(response)

    if not response or not response.strip():
        response = "(No response from Claude)"

    # Slack message limit is ~40,000 chars but keep it reasonable
    if len(response) > 4000:
        response = response[:4000] + "\n\n... (truncated)"

    return response


# ── Slack app ─────────────────────────────────────────────────────────────────

app = App(token=SLACK_BOT_TOKEN)
assistant = Assistant()


@assistant.thread_started
def handle_thread_started(say, set_suggested_prompts):
    """Called when a user opens a new assistant thread."""
    say("How can I help?")
    set_suggested_prompts(
        prompts=[
            {"title": "Search the web", "message": "Search the web for the latest news"},
            {"title": "Read files", "message": "What files are in my workspace?"},
        ]
    )


@assistant.user_message
def handle_user_message(say, set_status, payload, client, context):
    """Called when a user sends a message in an assistant thread."""
    user_id = context.get("user_id", payload.get("user"))
    if not is_dm_allowed(user_id):
        say("Not authorized.")
        return

    text = payload.get("text", "").strip()
    channel = payload.get("channel", "assistant")
    msg_ts = payload.get("ts")
    thread_ts = payload.get("thread_ts")
    session_key = make_session_key(user_id, channel, is_dm=True)
    slack_ctx = build_slack_context(channel, is_dm=True, ts=msg_ts, thread_ts=thread_ts)

    if handle_bang_command(text, session_key, say, {}):
        return

    files = payload.get("files", [])
    if files:
        set_status("Processing files...")
        cleanup_temp_dir()
        prompts = []
        for file_info in files:
            file_name = file_info.get("name", "unknown")
            mime_type = file_info.get("mimetype")
            file_size = file_info.get("size")
            download_url = file_info.get("url_private_download") or file_info.get("url_private")
            if not download_url:
                prompts.append(f"The user shared a file '{file_name}' but it could not be downloaded.")
                continue
            ext = Path(file_name).suffix
            if not ext and mime_type:
                ext = mimetypes.guess_extension(mime_type) or ""
            temp_path = TEMP_DIR / f"{uuid.uuid4()}{ext}"
            try:
                download_slack_file(download_url, str(temp_path))
                prompt = build_file_prompt(file_name, mime_type, file_size, str(temp_path))
                prompts.append(prompt)
            except Exception as e:
                prompts.append(f"Failed to download '{file_name}': {e}")
        full_prompt = "\n\n".join(prompts)
        if text:
            full_prompt += f"\n\nThe user also said: {text}"
        response = send_with_lock(session_key, full_prompt, slack_ctx)
        if response:
            say(response)
        return

    if not text:
        return

    emit_event("msg_in", user=user_id, channel=channel, text=text[:100], is_dm=True, handler="assistant")
    set_status("Thinking...")

    response = send_with_lock(session_key, text, slack_ctx)
    if response:
        say(response)


@assistant.thread_context_changed
def handle_context_changed(save_thread_context, payload):
    """Called when assistant thread context changes."""
    save_thread_context(payload.get("assistant_thread", {}).get("context", {}))


app.use(assistant)


@app.event("app_mention")
def handle_mention(event, say, client):
    """Handle @bot mentions in channels."""
    user_id = event.get("user")
    channel = event.get("channel")

    if not is_channel_allowed(user_id, channel):
        say("Not authorized.", thread_ts=event.get("ts"))
        return

    if not should_respond_in_channel("app_mention", event.get("text", "")):
        return

    text = strip_bot_mention(event.get("text", ""))
    if not text:
        say("Send me a message and I'll respond via Claude.", thread_ts=event.get("ts"))
        return

    thread_ts = event.get("thread_ts")
    if REPLY_IN_THREAD and not thread_ts:
        thread_ts = event.get("ts")

    reply_kwargs = {"thread_ts": thread_ts} if thread_ts else {}
    session_key = make_session_key(user_id, channel, is_dm=False)
    if handle_bang_command(text, session_key, say, reply_kwargs):
        return

    emit_event("msg_in", user=user_id, channel=channel, text=text[:100], is_dm=False, handler="mention")

    try:
        client.reactions_add(channel=channel, timestamp=event.get("ts"), name=REACT_EMOJI)
    except Exception:
        pass

    display_name = get_display_name(client, user_id)
    slack_ctx = build_slack_context(channel, is_dm=False, ts=event.get("ts"), thread_ts=thread_ts)
    response = send_with_lock(session_key, f"[{display_name}]: {text}", slack_ctx)

    try:
        client.reactions_remove(channel=channel, timestamp=event.get("ts"), name=REACT_EMOJI)
    except Exception:
        pass

    if response:
        say(text=response, thread_ts=thread_ts)


@app.event("message")
def handle_direct_message(event, say, client):
    """Handle direct messages and channel messages to the bot."""
    if event.get("subtype"):
        return

    user_id = event.get("user")
    if not user_id:
        return

    channel = event.get("channel")
    channel_type = event.get("channel_type", "")
    text = event.get("text", "").strip()

    if channel_type == "im":
        if not is_dm_allowed(user_id):
            say("Not authorized.")
            return
    else:
        # Avoid double-processing: app_mention fires separately for @mentions
        if BOT_USER_ID and f"<@{BOT_USER_ID}>" in text:
            return
        if not is_channel_allowed(user_id, channel):
            return
        if not should_respond_in_channel("message", text):
            return

    files = event.get("files", [])
    if files:
        handle_files(event, say, client, files, text, channel_type)
        return

    if not text:
        return

    is_dm = channel_type == "im"

    thread_ts = None
    if not is_dm:
        existing_thread = event.get("thread_ts")
        if existing_thread:
            thread_ts = existing_thread
        elif REPLY_IN_THREAD:
            thread_ts = event.get("ts")

    reply_kwargs = {"thread_ts": thread_ts} if thread_ts else {}
    session_key = make_session_key(user_id, channel, is_dm)
    if handle_bang_command(text, session_key, say, reply_kwargs):
        return

    emit_event("msg_in", user=user_id, channel=channel, text=text[:100], is_dm=is_dm, handler="message")

    try:
        client.reactions_add(channel=channel, timestamp=event.get("ts"), name=REACT_EMOJI)
    except Exception:
        pass

    slack_ctx = build_slack_context(channel, is_dm=is_dm, ts=event.get("ts"), thread_ts=thread_ts)
    if is_dm:
        prompt = text
    else:
        display_name = get_display_name(client, user_id)
        prompt = f"[{display_name}]: {text}"
    response = send_with_lock(session_key, prompt, slack_ctx)

    try:
        client.reactions_remove(channel=channel, timestamp=event.get("ts"), name=REACT_EMOJI)
    except Exception:
        pass

    if response:
        say(text=response, thread_ts=thread_ts)


def handle_files(event, say, client, files, caption, channel_type="im"):
    """Handle file uploads from Slack."""
    user_id = event.get("user")
    channel = event.get("channel")

    try:
        client.reactions_add(channel=channel, timestamp=event.get("ts"), name=REACT_EMOJI)
    except Exception:
        pass

    cleanup_temp_dir()
    prompts = []

    for file_info in files:
        file_name = file_info.get("name", "unknown")
        mime_type = file_info.get("mimetype")
        file_size = file_info.get("size")
        download_url = file_info.get("url_private_download") or file_info.get("url_private")

        if not download_url:
            prompts.append(f"The user shared a file '{file_name}' but it could not be downloaded.")
            continue

        if file_size and file_size > SLACK_FILE_SIZE_LIMIT:
            prompts.append(f"The user shared a file '{file_name}' ({format_file_size(file_size)}) but it's too large to process.")
            continue

        ext = Path(file_name).suffix
        if not ext and mime_type:
            ext = mimetypes.guess_extension(mime_type) or ""

        temp_path = TEMP_DIR / f"{uuid.uuid4()}{ext}"

        try:
            download_slack_file(download_url, str(temp_path))
            prompt = build_file_prompt(file_name, mime_type, file_size, str(temp_path))
            prompts.append(prompt)
        except Exception as e:
            prompts.append(f"Failed to download '{file_name}': {e}")

    is_dm = channel_type == "im"

    full_prompt = "\n\n".join(prompts)
    if caption:
        full_prompt += f"\n\nThe user also said: {caption}"

    if not is_dm:
        display_name = get_display_name(client, user_id)
        full_prompt = f"[{display_name}]: {full_prompt}"

    thread_ts = None
    if not is_dm:
        existing_thread = event.get("thread_ts")
        if existing_thread:
            thread_ts = existing_thread
        elif REPLY_IN_THREAD:
            thread_ts = event.get("ts")

    session_key = make_session_key(user_id, channel, is_dm)
    slack_ctx = build_slack_context(channel, is_dm=is_dm, ts=event.get("ts"), thread_ts=thread_ts)
    response = send_with_lock(session_key, full_prompt, slack_ctx)

    try:
        client.reactions_remove(channel=channel, timestamp=event.get("ts"), name=REACT_EMOJI)
    except Exception:
        pass

    if response:
        say(text=response, thread_ts=thread_ts)


@app.command("/new")
def handle_new_command(ack, command, respond):
    """Clear the current Claude session for this channel."""
    ack()
    user_id = command.get("user_id")
    channel_id = command.get("channel_id", "")
    sessions = load_sessions()
    cleared = []
    # Clear both possible session keys (DM and channel)
    for key in [f"dm:{user_id}:{channel_id}", f"channel:{channel_id}"]:
        if key in sessions:
            del sessions[key]
            cleared.append(key)
    if cleared:
        save_sessions(sessions)
    respond("Session cleared. Next message starts fresh.")


@app.command("/status")
def handle_status_command(ack, command, respond):
    """Show bot status."""
    ack()
    user_id = command.get("user_id")
    channel_id = command.get("channel_id", "")
    sessions = load_sessions()
    dm_key = f"dm:{user_id}:{channel_id}"
    channel_key = f"channel:{channel_id}"
    has_dm_session = dm_key in sessions
    has_channel_session = channel_key in sessions
    respond(
        f"User ID: {user_id}\n"
        f"DM allowed: {'Yes' if is_dm_allowed(user_id) else 'No'}\n"
        f"DM session: {'Yes' if has_dm_session else 'No'}\n"
        f"Channel session (shared): {'Yes' if has_channel_session else 'No'}\n"
        f"Group policy: {GROUP_POLICY}\n"
        f"Workspace: {WORKSPACE}"
    )


def main():
    global BOT_USER_ID, BOT_NAME

    if not SLACK_BOT_TOKEN:
        emit_event("error", msg="Set SLACK_BOT_TOKEN in .env file")
        return
    if not SLACK_APP_TOKEN:
        emit_event("error", msg="Set SLACK_APP_TOKEN in .env file")
        return

    cleanup_temp_dir()
    migrate_sessions()

    # Resolve bot identity for mention detection and self-awareness
    try:
        auth = app.client.auth_test()
        BOT_USER_ID = auth.get("user_id")
        if BOT_USER_ID:
            BOT_NAME = get_display_name(app.client, BOT_USER_ID)
        emit_event("identity", name=BOT_NAME, user_id=BOT_USER_ID)
    except Exception as e:
        emit_event("error", msg=f"Could not resolve bot identity: {e}")

    emit_event("startup", workspace=WORKSPACE,
               allowed_users=ALLOWED_USERS or ["*"],
               group_policy=GROUP_POLICY, dm_policy=DM_POLICY,
               reply_in_thread=REPLY_IN_THREAD, react_emoji=REACT_EMOJI)

    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    emit_event("ready", msg="Bot running. Send messages on Slack.")
    handler.start()


if __name__ == "__main__":
    main()
