#!/bin/bash
# Send a Slack message
# Usage: send.sh "Your message here"

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/../../../.env"

# Load env vars
if [ -f "$ENV_FILE" ]; then
    SLACK_BOT_TOKEN=$(grep "^SLACK_BOT_TOKEN=" "$ENV_FILE" | cut -d'=' -f2)
    SLACK_CHANNEL_ID=$(grep "^SLACK_CHANNEL_ID=" "$ENV_FILE" | cut -d'=' -f2)
fi

# Fall back to environment variables
SLACK_BOT_TOKEN="${SLACK_BOT_TOKEN:-}"
SLACK_CHANNEL_ID="${SLACK_CHANNEL_ID:-}"

if [ -z "$SLACK_BOT_TOKEN" ]; then
    echo "Error: SLACK_BOT_TOKEN not set in .env or environment"
    exit 1
fi

if [ -z "$SLACK_CHANNEL_ID" ]; then
    echo "Error: SLACK_CHANNEL_ID not set in .env or environment"
    echo "Right-click a channel in Slack → Copy link → ID is at the end of the URL"
    exit 1
fi

MESSAGE="$1"

if [ -z "$MESSAGE" ]; then
    echo "Usage: send.sh \"message\""
    exit 1
fi

curl -s -X POST "https://slack.com/api/chat.postMessage" \
    -H "Authorization: Bearer ${SLACK_BOT_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"channel\": \"${SLACK_CHANNEL_ID}\", \"text\": $(echo "$MESSAGE" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')}" > /dev/null

echo "Sent: $MESSAGE"
