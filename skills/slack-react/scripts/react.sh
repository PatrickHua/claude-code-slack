#!/bin/bash
# Add an emoji reaction to a Slack message
# Usage: react.sh <channel_id> <message_timestamp> <emoji_name>
# Example: react.sh C0AGFTKMR8S 1771820094.793999 thumbsup

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/../../../.env"

if [ -f "$ENV_FILE" ]; then
    SLACK_BOT_TOKEN=$(grep "^SLACK_BOT_TOKEN=" "$ENV_FILE" | cut -d'=' -f2)
fi

SLACK_BOT_TOKEN="${SLACK_BOT_TOKEN:-}"

if [ -z "$SLACK_BOT_TOKEN" ]; then
    echo "Error: SLACK_BOT_TOKEN not set in .env or environment"
    exit 1
fi

CHANNEL="$1"
TIMESTAMP="$2"
EMOJI="$3"

if [ -z "$CHANNEL" ] || [ -z "$TIMESTAMP" ] || [ -z "$EMOJI" ]; then
    echo "Usage: react.sh <channel_id> <message_timestamp> <emoji_name>"
    echo "Example: react.sh C0AGFTKMR8S 1771820094.793999 thumbsup"
    exit 1
fi

RESPONSE=$(curl -s -X POST "https://slack.com/api/reactions.add" \
    -H "Authorization: Bearer ${SLACK_BOT_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"channel\": \"${CHANNEL}\", \"timestamp\": \"${TIMESTAMP}\", \"name\": \"${EMOJI}\"}")

OK=$(echo "$RESPONSE" | python3 -c "import json,sys; print(json.loads(sys.stdin.read()).get('ok', False))" 2>/dev/null)

if [ "$OK" = "True" ]; then
    echo "Reacted with :${EMOJI}: to message ${TIMESTAMP} in ${CHANNEL}"
else
    ERROR=$(echo "$RESPONSE" | python3 -c "import json,sys; print(json.loads(sys.stdin.read()).get('error', 'unknown'))" 2>/dev/null)
    echo "Error: ${ERROR}"
    exit 1
fi
