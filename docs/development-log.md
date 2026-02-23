# Development Log — claude-code-slack

Chronicle of the build-out session that turned a basic Slack-to-Claude-CLI bridge into a
production-quality bot with skills, structured logging, and a TUI monitor.

---

## Starting Point

The repo was a simple Python bot (`slack-bot.py`) that:
- Connected to Slack via Socket Mode (Bolt framework)
- Forwarded messages to `claude -p` via subprocess
- Returned Claude's text response to the channel

It worked, but had no access control, no DM/channel distinction, no session management,
and no observability.

---

## Features Implemented

### 1. Nanobot-inspired Slack features

Ported from a separate `nanobot` project that used OpenRouter API keys.
We kept the architecture but swapped the backend to Claude Code CLI.

- **Configurable access control**: `ALLOWED_USERS`, `DM_POLICY`, `DM_ALLOW_FROM`,
  `GROUP_POLICY`, `GROUP_ALLOW_FROM` (env vars in `.env`)
- **Bot identity resolution**: At startup, resolve `BOT_USER_ID` and `BOT_NAME` via
  `auth_test()` + `users_info()` so the bot knows its own name
- **Reaction emoji**: Configurable `REACT_EMOJI` (default: `thinking_face`) shown while
  Claude is processing
- **Thread control**: `REPLY_IN_THREAD` for channels; DMs are never threaded
- **Markdown → mrkdwn conversion**: Using `slackify-markdown` + custom table handler

### 2. Session management — DM vs channel

- **DM sessions**: keyed `dm:{user_id}:{channel}` — each user gets a private context
- **Channel sessions**: keyed `channel:{channel_id}` — shared group brainstorm mode
- Session UUIDs stored in `~/.slack-claude-sessions.json`
- Claude CLI `--resume <session_id>` maintains conversation continuity
- `migrate_sessions()` cleans up old-format keys on startup

### 3. Concurrency control & message batching

Multiple Slack messages can arrive while Claude is processing. Without protection,
parallel `subprocess.run()` calls would race.

- **Per-session locks** (`threading.Lock` via `defaultdict`): only one Claude call
  per session at a time
- **Message batching**: if messages arrive while a session is locked, they queue up
  and get combined into the next prompt (`BATCH_WAIT_SECONDS = 1.5`)

### 4. Bang commands

- `!clear` — delete session, next message starts fresh
- `!compact` — ask Claude to summarize the session, start a new session seeded with it
- `!context` — read the Claude session `.jsonl` file directly, display truncated
  message history (no LLM call)

### 5. Slack skills for Claude

Claude Code discovers skills from `~/.claude/skills/`. We built:

| Skill | Script | Purpose |
|---|---|---|
| **slack-react** | `react.sh <channel> <ts> <emoji>` | Add emoji reactions |
| **slack-upload** | `upload.sh <file> <channel> [thread_ts] [msg]` | Upload files to channels/DMs |

A `slack-reply` skill was initially created but **deleted** — it conflicted with the
bot's own message posting, causing Claude to double-post via Bash.

### 6. Slack context metadata

Each message sent to Claude is prefixed with a context line:

```
[slack type=dm channel=D0AGC3X3VLM msg_ts=1771824297.713739 thread_ts=1771804892.383019]
```

This lets Claude know:
- Whether it's a DM or channel message
- The channel/DM ID (for skills like upload, react)
- The message timestamp (for react)
- The thread timestamp (for uploading files in-thread)

### 7. Structured event logging

Replaced verbose Slack Bolt `DEBUG` output with a structured JSON event log
(`.bot-events.jsonl`) and clean one-liner console output:

```
[21:36:48] identity       ai-research-agent (U0AH9Q8FTC0)
[21:36:48] startup        group=open dm=open
[21:37:02] msg_in         U05RDJ in DM: hi
[21:37:04] claude_start   session=dm:U05RDJ:D0AGC
[21:37:18] claude_done    14.2s session=dm:U05RDJ:D0AGC
```

Events: `identity`, `startup`, `ready`, `msg_in`, `claude_start`, `claude_done`,
`queued`, `batched`, `bang_cmd`, `error`

### 8. TUI monitor (`monitor.py`)

A `rich`-based live dashboard that tails `.bot-events.jsonl`:

```bash
.venv/bin/python monitor.py
```

Four panels:
- **Header** — bot name, total messages, claude calls, avg response time, errors
- **Sessions** — active DM and channel sessions with message counts
- **Active Claude Calls** — live timer per session (green/yellow/red by elapsed time)
- **Event Log** — scrolling tail of recent events

---

## Bugs Found & Fixed

### Multiple bot instances stealing events

Slack Socket Mode load-balances events across all active WebSocket connections from the
same app. Having multiple bot processes (from restarts, or `claude-code-telegram` sharing
the same tokens) meant messages were randomly routed to the wrong process.

**Fix**: Always kill all `slack-bot.py` processes before starting. Check with
`ps aux | grep slack-bot.py`. The `claude-code-telegram` repo had identical Slack tokens
in its `.env` — another source of event theft.

### `--max-turns 3` too low

Claude Code CLI's `--max-turns` limits agentic tool-use rounds. With 3 turns and tools
available (`Bash,Read,Write,...`), Claude would burn all turns on file reads and get
cut off (`subtype: "error_max_turns"`) without producing a text response.

**Fix**: `--max-turns 10` — enough room for tool use AND a final text response.

### System prompt caused Claude to use skills for every reply

The prompt said "Use these values when invoking Slack skills" — Claude interpreted this
as "reply to every message via the slack-reply skill using Bash." Result: 4 tool turns,
response text = "Replied in the thread.", $0.05/message.

**Fix**: Deleted `slack-reply` skill. Rewrote prompt with explicit rules:
"Just return plain text. NEVER use Bash to send messages."

### "Read CLAUDE.md" instruction caused exploration

The original prompt told Claude to "First, silently read CLAUDE.md for context."
No `CLAUDE.md` existed, but Claude would spend turns trying to find it.

**Fix**: Removed the instruction entirely.

### Upload skill posted files as top-level messages in DMs

`upload.sh` called `files.completeUploadExternal` without `thread_ts`. In Slack's
Assistant UI, DM conversations live in threads. A top-level file post resets the
conversation view, making previous messages disappear.

**Fix**: Added `thread_ts` as 3rd parameter to `upload.sh`. The SKILL.md instructs
Claude to always pass `thread_ts` for DMs. The bot injects `thread_ts` into the
slack context metadata on every message.

### Stale global skill cache

`cp -r` to `~/.claude/skills/` didn't overwrite existing files. Claude kept reading
the old 3-parameter SKILL.md even after the local copy was updated.

**Fix**: `rm -rf` the destination before `cp -r`.

### Persistent "老公" persona from MEMORY.md

Claude Code's per-project memory file
(`~/.claude/projects/-home-patrick-claude-code-slack/memory/MEMORY.md`) contained
persona instructions in Chinese. Even after `!clear`, Claude would reload them.

**Fix**: Cleared the memory file contents.

---

## Architecture

```
Slack (Socket Mode)
  │
  ├── @assistant.user_message  (DM assistant threads)
  ├── @app.event("app_mention") (channel @mentions)
  ├── @app.event("message")     (DMs + open-policy channels)
  │
  └── send_with_lock(session_key, prompt, slack_ctx)
        │
        ├── Per-session threading.Lock (serializes Claude calls)
        ├── Message batching (BATCH_WAIT_SECONDS)
        │
        └── send_to_claude_with_session()
              │
              ├── New session: build_context_prompt() + slack_ctx + prompt
              ├── Resumed:     slack_ctx + prompt  (with --resume session_id)
              │
              └── run_claude()
                    │
                    └── subprocess.run([claude, -p, ..., --output-format, json,
                                        --max-turns, 10, --allowedTools, ...],
                                       timeout=300)
```

---

## Key Configuration

| Env var | Purpose | Default |
|---|---|---|
| `SLACK_BOT_TOKEN` | Bot OAuth token (xoxb-) | required |
| `SLACK_APP_TOKEN` | App-level token (xapp-) for Socket Mode | required |
| `CLAUDE_WORKSPACE` | Working directory for Claude CLI | `$HOME` |
| `CLAUDE_PATH` | Path to `claude` binary | `claude` |
| `ALLOWED_USERS` | Comma-separated user IDs | everyone |
| `DM_ENABLED` | Allow DMs | `true` |
| `DM_POLICY` | `open` or `allowlist` | `open` |
| `GROUP_POLICY` | `mention`, `open`, or `allowlist` | `mention` |
| `REACT_EMOJI` | Emoji while thinking | `thinking_face` |
| `REPLY_IN_THREAD` | Thread replies in channels | `true` |

---

## File Structure

```
claude-code-slack/
├── slack-bot.py          # Main bot (941 lines)
├── monitor.py            # Rich TUI dashboard
├── requirements.txt      # slack-bolt, slack-sdk, slackify-markdown, rich
├── .env                  # Secrets (gitignored)
├── .env.example          # Template with documentation
├── .bot-events.jsonl     # Structured event log (gitignored)
├── .gitignore
├── docs/
│   └── development-log.md  # This file
├── skills/
│   ├── slack-react/
│   │   ├── SKILL.md
│   │   └── scripts/react.sh
│   └── slack-upload/
│       ├── SKILL.md
│       └── scripts/upload.sh
├── systemd/              # Service files for production
└── README.md
```
