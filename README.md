# claude-code-slack

A personal AI assistant you can message from anywhere via Slack.

## What is this?

You know how Claude Code runs in your terminal and can read files, run commands, search the web, etc? This lets you talk to it from Slack instead of being tied to your computer.

**Message the bot → it runs Claude Code → sends back the response.**

Some things you can do:
- "What's on my calendar today?"
- "Search the web for the latest news on X"
- "Read my notes and summarize them"
- "Send me a daily briefing every morning at 7am"

It also works the other way - Claude can message YOU via Slack (notifications when tasks finish, scheduled briefings, alerts, etc).

**The key is skills.** Out of the box, Claude Code can read files and search the web. But to make it truly YOUR assistant, create skills that give it access to your stuff:
- Google Calendar (read your schedule)
- Gmail (read-only access to emails)
- Notes app (Obsidian, Apple Notes, etc.)
- Weather for your location
- Whatever else you want

The `skills/` folder has examples to get you started.

## Quick Start

Open Claude Code and paste:

```
Help me set up this Slack bot at ~/claude-code-slack
```

Claude will walk you through:
1. Creating a Slack app
2. Configuring permissions and Socket Mode
3. Setting up the `.env` file
4. Installing the slack-sender skill globally
5. Running the bot

---

## What's Included

| File | Purpose |
|------|---------|
| `slack-bot.py` | Receives messages from Slack → sends to Claude Code |
| `skills/slack-sender/` | Lets Claude send messages TO you |
| `skills/daily-brief/` | Example scheduled skill using slack-sender |
| `systemd/` | Templates for running bot as a Linux service |

## How It Works

**Inbound (you → Claude):**
```
Slack → slack-bot.py → claude -p "message" → response → Slack
```

**Outbound (Claude → you):**
```
Claude skill → slack-sender/send.sh → Slack API → you
```

## Manual Setup

### 1. Prerequisites
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated
- Python 3.10+

### 2. Create a Slack App

1. Go to [https://api.slack.com/apps](https://api.slack.com/apps)
2. Click **Create New App** → **From scratch**
3. Name it (e.g., "Claude") and select your workspace

### 3. Enable Socket Mode

1. Go to **Settings → Socket Mode**
2. Toggle **Enable Socket Mode** on
3. Create an App-Level Token with `connections:write` scope
4. Copy the token (starts with `xapp-`)

### 4. Add Bot Permissions

Go to **Features → OAuth & Permissions → Scopes → Bot Token Scopes** and add:

| Scope | Purpose |
|-------|---------|
| `app_mentions:read` | Respond to @mentions in channels |
| `chat:write` | Send messages |
| `im:history` | Read DMs |
| `im:read` | Access DM channels |
| `im:write` | Send DMs |
| `files:read` | Download shared files |

### 5. Enable Events

Go to **Features → Event Subscriptions** → toggle on, then under **Subscribe to bot events** add:
- `app_mention`
- `message.im`

### 6. Add Slash Commands (Optional)

Go to **Features → Slash Commands** and create:
- `/new` - Clear current Claude session
- `/status` - Show bot status

### 7. Install App to Workspace

Go to **Settings → Install App** → **Install to Workspace** and copy the Bot Token (starts with `xoxb-`).

### 8. Configure

```bash
cp .env.example .env
# Edit .env with your tokens and settings
```

### 9. Install Dependencies

```bash
pip install -r requirements.txt
```

### 10. Install Skill Globally

```bash
cp -r skills/slack-sender ~/.claude/skills/
```

### 11. Run Bot (Manual)

```bash
python slack-bot.py
```

### 12. Run Bot (systemd - Recommended for Linux)

```bash
# Edit systemd/claude-slack-bot.service with your paths
sudo cp systemd/claude-slack-bot.service /etc/systemd/system/
sudo systemctl enable --now claude-slack-bot
```

## Bot Features

- **DMs** - Message the bot directly for private conversations
- **@mentions** - Mention the bot in channels for public responses (replies in thread)
- **File uploads** - Send images, documents, code files, etc.
- **Session persistence** - Conversations maintain context across messages
- **Slash commands** - `/new` to start fresh, `/status` for info

## Security

### ALLOWED_USERS is critical

**Always set `ALLOWED_USERS` in your `.env` file.** If left empty, anyone in your workspace can message the bot and run Claude with full tool access on your machine.

```bash
# .env - always set this
ALLOWED_USERS=U0123456789
```

Find your user ID: click your profile picture in Slack → click the three dots → **Copy member ID**.

### Understand the tool access

The bot runs Claude with these tools enabled:
- `Read` / `Write` / `Edit` - file system access
- `Bash` - shell command execution
- `Glob` / `Grep` - file search
- `WebFetch` / `WebSearch` - internet access
- `Task` / `Skill` - agent spawning and skill execution

This is powerful and intentional for a personal assistant, but understand that messages can trigger real actions on your system.

### Protect your tokens

- Never commit `.env` (already in `.gitignore`)
- Your bot token lets anyone impersonate your bot
- Your app token enables Socket Mode connections

### Session file

Sessions are stored in `~/.slack-claude-sessions.json`. Default file permissions apply. On shared systems, consider restricting access:

```bash
chmod 600 ~/.slack-claude-sessions.json
```

## License

MIT
