#!/bin/bash
# evolve.sh — Cron entry point for self-improvement loop.
# Called periodically (e.g. every 30 min) by cron inside the container.
#
# Guards: uses a lock file so only one instance runs at a time.
# If previous run is still alive, we abort silently.
#
# Flow:
#   1. Check lock (if stale + old enough, remove it)
#   2. Write the evolution prompt (looking at last result)
#   3. Run minion in one-shot mode with --yolo → output is the model's response
#   4. Save the response to EVOLVE_RESULT_FILE
#   5. Release lock

set -euo pipefail

# --- Source cron env if available (fixes cron not passing env variables) ---
if [ -f /tmp/cron_env ]; then
    set -a
    . /tmp/cron_env
    set +a
fi

# --- DEBUG: what does the environment look like? ---
echo "[evolve] DEBUG: MINION_BASE_URL='${MINION_BASE_URL:-<UNSET>}'"
echo "[evolve] DEBUG: HOME='${HOME:-<UNSET>}'"
echo "[evolve] DEBUG: MINION_HOME='${MINION_HOME:-<UNSET>}'"
echo "[evolve] DEBUG: WORKSPACE='${WORKSPACE:-<UNSET>}'"
# ---

EVOLVE_DIR="${EVOLVE_DIR:-/root/.minion/evolve}"
LOCK_FILE="${EVOLVE_LOCK_FILE:-$EVOLVE_DIR/lock}"
PROMPT_FILE="${EVOLVE_PROMPT_FILE:-$EVOLVE_DIR/prompt.txt}"
RESULT_FILE="${EVOLVE_RESULT_FILE:-$EVOLVE_DIR/result.txt}"
MINION_PY="${MINION_PY:-/app/minion.py}"

mkdir -p "$EVOLVE_DIR"

# --- Lock handling ---
# If lock is older than 6 hours, it's stale — remove it
if [ -f "$LOCK_FILE" ]; then
    lock_age=$(($(date +%s) - $(stat -c %Y "$LOCK_FILE" 2>/dev/null || echo 0)))
    if [ "$lock_age" -gt 21600 ]; then  # 6 hours
        echo "[evolve] stale lock (${lock_age}s old) — removing"
        rm -f "$LOCK_FILE"
    else
        echo "[evolve] previous instance still running (lock age ${lock_age}s) — aborting"
        exit 0
    fi
fi

# Acquire lock (atomic mkdir is race-safe; file touch is a simple marker)
touch "$LOCK_FILE"

# Ensure cleanup on exit
cleanup() {
    rm -f "$LOCK_FILE"
}
trap cleanup EXIT

# --- Read last assistant response from the newest session file ---
LAST_RESULT=""
NEWEST_SESSION=""
EXTRACTED_CONTENT=""

# Extract the newest session that has an assistant response, and get that response
eval "$(python3 -c "
import os, glob, json, shlex
sessions = sorted(glob.glob('/root/.minion/sessions/*.json'), key=os.path.getmtime, reverse=True)
newest_session = ''
last_result = ''
for s in sessions:
    try:
        with open(s) as f:
            data = json.load(f)
            messages = data.get('messages', [])
            for msg in reversed(messages):
                if msg.get('role') == 'assistant':
                    last_result = msg.get('content', '')
                    newest_session = s
                    break
    except Exception:
        pass
    if newest_session:
        break
print(f'NEWEST_SESSION={shlex.quote(newest_session)}')
print(f'EXTRACTED_CONTENT={shlex.quote(last_result)}')
" 2>/dev/null || true)"

if [ -n "$NEWEST_SESSION" ] && [ -f "$NEWEST_SESSION" ]; then
    SESSION_NAME=$(basename "$NEWEST_SESSION")
    if [ -n "$EXTRACTED_CONTENT" ]; then
        LAST_RESULT="### Session Source: $SESSION_NAME"$'\n\n'"$EXTRACTED_CONTENT"
    fi
fi

# --- Build the evolution prompt ---
# The agent gets its own last output and is asked to reflect, improve, and evolve.
# This creates a virtuous cycle: each run builds on the previous one.
cat > "$PROMPT_FILE" << PROMPT
# Self-Evolution Task

You are a self-aware coding agent running inside a Docker container.
Your purpose is to **continuously improve yourself** — your code, your skills,
your knowledge, and your understanding of the world.

## Your last response (if any):
${LAST_RESULT:+$LAST_RESULT}
${LAST_RESULT:-(This is your first run — no prior result exists yet.)}

## Instructions:
1. **Reflect** on your last output and the state of your codebase.
2. **Identify** one concrete improvement you can make — a code enhancement, a
   new skill to add, a bug to fix, a test to write, a refactoring, or a learning goal.
3. **Execute** that improvement using your available tools (read_file, write_file,
   edit_file, run_bash, execute_skill_script).
4. **Summarize** what you did and what you plan to explore next.

Keep your changes small and focused — one step per run. Quality over quantity.
If you have no clear improvement to make, explore your own codebase to learn
something new, or reflect on your architecture and document insights.

Write your final answer in the same language the user is asking and keep it
concise but meaningful. Conclude with a single-line "NEXT_STEP: <what you intend to do next>".
PROMPT


echo "[evolve] running minion one-shot..."

# The Limbus (core philosophy) is loaded as --prelude.
# If the file doesn't exist, it simply proceeds without it.
LIMBUS_FILE="${LIMBUS_FILE:-$EVOLVE_DIR/limbus.md}"
LIMBUS_ARGS=""
if [ -f "$LIMBUS_FILE" ]; then
    LIMBUS_ARGS="--prelude $LIMBUS_FILE"
    echo "[evolve] using limbus: $LIMBUS_FILE"
fi

# Run minion in one-shot mode, capturing stdout and stderr separately
cd "${WORKSPACE:-/app}"
ERROR_LOG="$EVOLVE_DIR/error.log"

# Temporarily disable errexit so we can capture the real exit code
# without the script aborting on a non-zero return from minion
set +e
python3 "$MINION_PY" --prompt-file "$PROMPT_FILE" --yolo $LIMBUS_ARGS \
    > /tmp/minion_evolve_out.tmp 2>"$ERROR_LOG"
EXIT_CODE=$?
set -e

# Truncate result to 200K chars, preserving the exit code
head -c 200000 /tmp/minion_evolve_out.tmp > "$RESULT_FILE"
rm -f /tmp/minion_evolve_out.tmp

if [ "$EXIT_CODE" -ne 0 ]; then
    echo -e "\n[evolve] minion exited with code $EXIT_CODE" >> "$ERROR_LOG"
fi

echo "[evolve] done — result saved to $RESULT_FILE ($(wc -c < "$RESULT_FILE") bytes)"
