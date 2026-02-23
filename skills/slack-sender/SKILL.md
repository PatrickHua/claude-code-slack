---
name: slack-sender
description: Send Slack messages for notifications, reminders, or alerts. Use for proactive messaging. Triggers on "send slack", "message me", "notify me", "remind me".
---

# Slack Sender

Send messages to a Slack channel. Useful for:
- Notifications when long tasks complete
- Scheduled reminders (combine with cron)
- Alerts from automated workflows

## Usage

```bash
./skills/slack-sender/scripts/send.sh "Your message here"
```

## Examples

**Send a simple message:**
```bash
./skills/slack-sender/scripts/send.sh "Task completed!"
```

**With mrkdwn formatting:**
```bash
./skills/slack-sender/scripts/send.sh "*Alert:* Build failed"
```

## For Scheduled Reminders

Combine with cron for scheduled messages:

```bash
# Remind at 7pm daily
0 19 * * * /path/to/skills/slack-sender/scripts/send.sh "Time for evening routine"

# Remind at 3pm on weekdays
0 15 * * 1-5 /path/to/skills/slack-sender/scripts/send.sh "Take a break"
```

## Supported Formatting

Slack mrkdwn:
- `*bold*`
- `_italic_`
- `` `monospace` ``
- ` ```code block``` `
- `~strikethrough~`

## Requirements

Set these in your `.env` file:
- `SLACK_BOT_TOKEN` - Your bot token (starts with xoxb-)
- `SLACK_CHANNEL_ID` - Target channel ID
