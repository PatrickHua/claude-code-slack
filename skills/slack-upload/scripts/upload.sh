#!/bin/bash
# Upload a file to a Slack channel or DM thread
# Usage: upload.sh <file_path> [channel_id] [thread_ts] [message]
# If channel_id is omitted, uses SLACK_CHANNEL_ID from .env

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/../../../.env"

if [ -f "$ENV_FILE" ]; then
    SLACK_BOT_TOKEN=$(grep "^SLACK_BOT_TOKEN=" "$ENV_FILE" | cut -d'=' -f2)
    DEFAULT_CHANNEL=$(grep "^SLACK_CHANNEL_ID=" "$ENV_FILE" | cut -d'=' -f2)
fi

SLACK_BOT_TOKEN="${SLACK_BOT_TOKEN:-}"
DEFAULT_CHANNEL="${DEFAULT_CHANNEL:-}"

if [ -z "$SLACK_BOT_TOKEN" ]; then
    echo "Error: SLACK_BOT_TOKEN not set in .env or environment"
    exit 1
fi

FILE_PATH="$1"
CHANNEL="${2:-$DEFAULT_CHANNEL}"
THREAD_TS="${3:-}"
MESSAGE="${4:-}"

if [ -z "$FILE_PATH" ]; then
    echo "Usage: upload.sh <file_path> [channel_id] [thread_ts] [message]"
    exit 1
fi

if [ ! -f "$FILE_PATH" ]; then
    echo "Error: File not found: $FILE_PATH"
    exit 1
fi

if [ -z "$CHANNEL" ]; then
    echo "Error: No channel specified and SLACK_CHANNEL_ID not set in .env"
    exit 1
fi

FILE_NAME=$(basename "$FILE_PATH")
FILE_SIZE=$(stat -c%s "$FILE_PATH" 2>/dev/null || stat -f%z "$FILE_PATH" 2>/dev/null)

# Step 1: Get upload URL
UPLOAD_RESPONSE=$(curl -s -X POST "https://slack.com/api/files.getUploadURLExternal" \
    -H "Authorization: Bearer ${SLACK_BOT_TOKEN}" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "filename=${FILE_NAME}&length=${FILE_SIZE}")

UPLOAD_URL=$(echo "$UPLOAD_RESPONSE" | python3 -c "import json,sys; print(json.loads(sys.stdin.read()).get('upload_url', ''))" 2>/dev/null)
FILE_ID=$(echo "$UPLOAD_RESPONSE" | python3 -c "import json,sys; print(json.loads(sys.stdin.read()).get('file_id', ''))" 2>/dev/null)

if [ -z "$UPLOAD_URL" ] || [ -z "$FILE_ID" ]; then
    echo "Error: Failed to get upload URL"
    echo "$UPLOAD_RESPONSE"
    exit 1
fi

# Step 2: Upload the file
curl -s -X POST "$UPLOAD_URL" \
    -F "file=@${FILE_PATH}" > /dev/null

# Step 3: Complete the upload (with optional thread_ts to keep it in-thread)
COMPLETE_BODY="{\"files\": [{\"id\": \"${FILE_ID}\", \"title\": \"${FILE_NAME}\"}], \"channel_id\": \"${CHANNEL}\""
if [ -n "$THREAD_TS" ]; then
    COMPLETE_BODY="${COMPLETE_BODY}, \"thread_ts\": \"${THREAD_TS}\""
fi
if [ -n "$MESSAGE" ]; then
    ESCAPED_MSG=$(echo "$MESSAGE" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().strip()))')
    COMPLETE_BODY="${COMPLETE_BODY}, \"initial_comment\": ${ESCAPED_MSG}"
fi
COMPLETE_BODY="${COMPLETE_BODY}}"

COMPLETE_RESPONSE=$(curl -s -X POST "https://slack.com/api/files.completeUploadExternal" \
    -H "Authorization: Bearer ${SLACK_BOT_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "$COMPLETE_BODY")

OK=$(echo "$COMPLETE_RESPONSE" | python3 -c "import json,sys; print(json.loads(sys.stdin.read()).get('ok', False))" 2>/dev/null)

if [ "$OK" = "True" ]; then
    echo "Uploaded ${FILE_NAME} to ${CHANNEL}"
else
    ERROR=$(echo "$COMPLETE_RESPONSE" | python3 -c "import json,sys; print(json.loads(sys.stdin.read()).get('error', 'unknown'))" 2>/dev/null)
    echo "Error: ${ERROR}"
    exit 1
fi
