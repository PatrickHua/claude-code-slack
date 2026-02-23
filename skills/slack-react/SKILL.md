---
name: slack-react
description: Add emoji reactions to Slack messages. Use when asked to react, express emotion, or acknowledge a message with an emoji.
---

# Slack React

Add emoji reactions to messages in Slack.

## Usage

```bash
./skills/slack-react/scripts/react.sh <channel_id> <message_timestamp> <emoji_name>
```

## Parameters

| Param | Description | Example |
|-------|-------------|---------|
| channel_id | The Slack channel ID | C0AGFTKMR8S |
| message_timestamp | The `ts` of the message to react to | 1771820094.793999 |
| emoji_name | Emoji name without colons | thumbsup, heart, eyes, fire |

## Examples

```bash
# Thumbs up
./skills/slack-react/scripts/react.sh C0AGFTKMR8S 1771820094.793999 thumbsup

# Heart
./skills/slack-react/scripts/react.sh C0AGFTKMR8S 1771820094.793999 heart

# Fire
./skills/slack-react/scripts/react.sh C0AGFTKMR8S 1771820094.793999 fire
```

## Common Emoji Names

| Emoji | Name |
|-------|------|
| 👍 | thumbsup |
| ❤️ | heart |
| 🔥 | fire |
| 👀 | eyes |
| ✅ | white_check_mark |
| 🎉 | tada |
| 🚀 | rocket |
| 💯 | 100 |
| 👋 | wave |
| 🤔 | thinking_face |

## Requirements

Set `SLACK_BOT_TOKEN` in your `.env` file. The bot needs `reactions:write` scope.
