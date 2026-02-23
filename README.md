# claude-code-slack

**Claude Code in your pocket.** Message it from Slack, get back answers, files, web searches — from anywhere, on any device.

## One-command setup

```bash
python setup.py
```

That's it. The wizard opens your browser, walks you through the Slack app creation step by step, copies the manifest to your clipboard, and writes the `.env` for you.

No manual token hunting. No YAML wrestling. Done in under 5 minutes.

---

## What you get

**Talk to Claude from Slack:**
- "Summarize the emails I forwarded you"
- "Search the web for X and send me a summary"
- "What's in my notes about Y?"
- DMs, @mentions in channels, file uploads — all work out of the box

**Claude can reach YOU:**
- Task-complete notifications
- Scheduled briefings
- Alerts from automated workflows

**Extend it with skills** — drop scripts into `skills/` to give Claude access to your calendar, email, notes, or anything else.

---

## What's included

| File | Purpose |
|------|---------|
| `setup.py` | One-command setup wizard |
| `slack-bot.py` | Core bot — bridges Slack ↔ Claude Code |
| `skills/slack-sender/` | Lets Claude message you proactively |
| `skills/slack-upload/` | Lets Claude send files to Slack |
| `skills/daily-brief/` | Example scheduled briefing skill |
| `systemd/` | Linux service templates |

## How it works

```
You → Slack → slack-bot.py → claude -p "…" → Slack → You
```

```
Claude skill → slack-sender/send.sh → Slack API → You
```

---

## Security

**Set `ALLOWED_USERS` in your `.env`.** If left blank, anyone in your workspace can run Claude with full tool access on your machine.

```bash
ALLOWED_USERS=U0123456789   # your Slack member ID
```

Find your member ID: click your profile picture → three dots → **Copy member ID**.

Claude runs with `Read`, `Write`, `Bash`, `WebSearch`, and more. Intentionally powerful for a personal assistant — just make sure only you can reach it.

Never commit `.env` (already in `.gitignore`).

---

## Manual setup (if you prefer)

<details>
<summary>Expand manual instructions</summary>

### Prerequisites
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated
- Python 3.10+

### 1. Create a Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From an app manifest**
2. Paste the JSON from `setup.py`'s `generate_manifest()` (or run `python -c "from setup import *; print(generate_manifest('Claude','Claude','Your assistant'))"`)
3. Select your workspace and create the app

### 2. Generate an App-Level Token

**Basic Information** → **App-Level Tokens** → **Generate Token and Scopes**
- Name: `socket-mode`
- Scope: `connections:write`
- Copy the `xapp-…` token

### 3. Install to workspace

**Install App** → **Install to Workspace** → copy the `xoxb-…` Bot Token

### 4. Configure

```bash
cp .env.example .env
# Fill in SLACK_BOT_TOKEN, SLACK_APP_TOKEN, ALLOWED_USERS
```

### 5. Install dependencies & run

```bash
pip install -r requirements.txt
python slack-bot.py --env envs/your-bot.env
```

### 6. Run as a service (Linux)

```bash
# Edit systemd/claude-slack-bot.service with your paths
sudo cp systemd/claude-slack-bot.service /etc/systemd/system/
sudo systemctl enable --now claude-slack-bot
```

</details>

---

## License

MIT
