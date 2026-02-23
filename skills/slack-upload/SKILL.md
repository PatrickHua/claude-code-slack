---
name: slack-upload
description: Upload and share files to Slack channels or DM threads. Use when asked to send a file, share a document, upload an image, or deliver a report.
---

# Slack Upload

Upload files to a Slack channel or DM thread. Supports any file type.

## Usage

```bash
./skills/slack-upload/scripts/upload.sh <file_path> <channel_id> [thread_ts] [message]
```

## Parameters

| Param | Description | Default |
|-------|-------------|---------|
| file_path | Path to the file to upload (required) | — |
| channel_id | Target Slack channel or DM ID (required) | SLACK_CHANNEL_ID from .env |
| thread_ts | Thread timestamp — pass this to upload inside an existing thread instead of as a new message | — |
| message | Optional message to accompany the file | — |

## Examples

```bash
# Upload to a channel (new top-level message)
./skills/slack-upload/scripts/upload.sh report.pdf C0AGFTKMR8S

# Upload inside a DM thread (IMPORTANT for DMs to avoid breaking the conversation)
./skills/slack-upload/scripts/upload.sh results.png D0AGC3X3VLM 1771804892.383019

# Upload with a message
./skills/slack-upload/scripts/upload.sh analysis.csv C0AGFTKMR8S "" "Here's the analysis"

# Upload into a thread with a message
./skills/slack-upload/scripts/upload.sh data.csv D0AGC3X3VLM 1771804892.383019 "Here you go"
```

## Important

When uploading to a DM, ALWAYS pass the thread_ts from the slack context metadata.
Without it, the file creates a new top-level message that disrupts the conversation view.

## Requirements

Set `SLACK_BOT_TOKEN` in your `.env` file. The bot needs `files:write` scope.
