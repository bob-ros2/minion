#!/usr/bin/env bash
# chat_minion.sh — Pauses the evolution cronjob inside the container,
# starts an interactive chat session, and re-enables cron afterwards.

set -euo pipefail

MINION_HOME="${MINION_HOME:-/home/minion/.minion}"
SESSIONS_DIR="$MINION_HOME/sessions"
CRON_BACKUP="/tmp/crontab.txt"

# Guard: Ensure we are running inside the container
if [ ! -f "/app/minion.py" ]; then
    echo "❌ Error: This script must be executed INSIDE the container!"
    echo "Please run: docker exec -it minion /app/chat_minion.sh"
    exit 1
fi

# Back up the current crontab
crontab -l > "$CRON_BACKUP" 2>/dev/null || true

# Cleanup/Trap: Always restore crontab when the script exits (even on Ctrl+C)
cleanup() {
    echo -e "\n🔄 Restoring evolution cronjob..."
    if [ -f "$CRON_BACKUP" ] && [ -s "$CRON_BACKUP" ]; then
        crontab "$CRON_BACKUP"
        echo "✅ Cronjob restored successfully."
    else
        echo "ℹ️ No cronjob backup found or backup was empty. Skipping crontab restoration."
    fi
}
trap cleanup EXIT INT TERM

echo "⏸️  Pausing evolution cronjob (clearing crontab)..."
crontab -r || true

# Helper function to run python commands as minion user if PUID != 0
run_as_user() {
    if [ "$(id -u)" -eq 0 ] && [ "${PUID:-1000}" -ne 0 ]; then
        gosu minion "$@"
    else
        "$@"
    fi
}

# Prepare the latest session by injecting the latest evolution cronjob context
echo "🔄 Preparing session context with latest evolution status..."
LATEST_SESSION=$(run_as_user python3 /app/prepare_chat_session.py 2>/dev/null || true)

if [ -z "$LATEST_SESSION" ]; then
    echo "⚠️  Failed to prepare/resume session. Starting a fresh session..."
    run_as_user python3 /app/minion.py
else
    echo "💬 Resuming session: $LATEST_SESSION"
    echo "--------------------------------------------------"
    run_as_user python3 /app/minion.py --resume "$LATEST_SESSION"
fi
