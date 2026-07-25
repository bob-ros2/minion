#!/bin/bash
# evolve.sh — Cron entry point for self-improvement loop.
#
# Robustness & Fallback features:
#   1. Lock file guard against concurrent runs.
#   2. Pre-flight API reachability check (distinguishes temporary API outage from code failure).
#   3. Pre-flight & post-flight code health checks (py_compile).
#   4. Indestructible Git rollback (git reset --hard HEAD) if self-evolution causes code crash/syntax error.

set -euo pipefail

if [ -f /tmp/cron_env ]; then
    set -a
    . /tmp/cron_env
    set +a
fi

MINION_HOME="${MINION_HOME:-/home/minion/.minion}"
EVOLVE_DIR="${EVOLVE_DIR:-$MINION_HOME/evolve}"
LOCK_FILE="${EVOLVE_LOCK_FILE:-$EVOLVE_DIR/lock}"
PROMPT_FILE="${EVOLVE_PROMPT_FILE:-$EVOLVE_DIR/prompt.txt}"
RESULT_FILE="${EVOLVE_RESULT_FILE:-$EVOLVE_DIR/result.txt}"
MINION_PY="${MINION_PY:-/app/minion.py}"
WORKSPACE="${WORKSPACE:-/app}"

mkdir -p "$EVOLVE_DIR"

# --- Lock handling ---
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

touch "$LOCK_FILE"
cleanup() {
    rm -f "$LOCK_FILE"
}
trap cleanup EXIT

# -------------------------------------------------------------
# STEP 1: Pre-flight Code Health, Snapshot & API Endpoint Checks
# -------------------------------------------------------------
cd "$WORKSPACE"

# A) Check existing code health. If already broken before run, compile warning
if [ -f "$MINION_PY" ] && ! python3 -m py_compile "$MINION_PY" 2>/dev/null; then
    echo "[evolve] ⚠️ Warning: Codebase contains syntax errors prior to evolution pass!"
fi

# B) Create Snapshot of workspace EXACTLY as it is right before THIS evolution run
UNTRACKED_SNAPSHOT="/tmp/pre_evolve_untracked.txt"
git ls-files --others --exclude-standard > "$UNTRACKED_SNAPSHOT" || touch "$UNTRACKED_SNAPSHOT"

PRE_RUN_SNAP=$(git stash create "pre-evolve-snapshot" 2>/dev/null || true)
if [ -z "$PRE_RUN_SNAP" ]; then
    PRE_RUN_SNAP=$(git rev-parse HEAD 2>/dev/null || echo "")
fi

restore_pre_run_state() {
    echo "[evolve] 🔄 Restoring workspace to state immediately before this evolution pass..."
    if [ -n "$PRE_RUN_SNAP" ]; then
        git reset --hard "$PRE_RUN_SNAP" || true
    fi
    if [ -f "$UNTRACKED_SNAPSHOT" ]; then
        git ls-files --others --exclude-standard | grep -v -F -f "$UNTRACKED_SNAPSHOT" | xargs -r rm -rf || true
    fi
}

# C) Check API endpoint reachability (temporary network/server issue vs code error)
MINION_BASE_URL="${MINION_BASE_URL:-}"
if [ -n "$MINION_BASE_URL" ]; then
    API_CHECK_URL="${MINION_BASE_URL%/}/models"
    if ! curl -s -f --connect-timeout 5 --max-time 10 "$API_CHECK_URL" >/dev/null 2>&1 && \
       ! curl -s -k --connect-timeout 5 --max-time 10 "$MINION_BASE_URL" >/dev/null 2>&1; then
        echo "[evolve] ⏸️ API endpoint unreachable ($MINION_BASE_URL). Temporary network/server issue — skipping evolution run."
        exit 0
    fi
fi

# -------------------------------------------------------------
# STEP 2: Read last assistant response & Build prompt
# -------------------------------------------------------------
LAST_RESULT=""
NEWEST_SESSION=""
EXTRACTED_CONTENT=""

eval "$(python3 -c "
import os, glob, json, shlex
sessions_dir = os.path.join(os.getenv('MINION_HOME', '$MINION_HOME'), 'sessions')
sessions = sorted(glob.glob(os.path.join(sessions_dir, '*.json')), key=os.path.getmtime, reverse=True)
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
3. **Execute** that improvement using your available tools.
4. **Summarize** what you did and what you plan to explore next.

Keep your changes small and focused — one step per run. Quality over quantity.
If you have no clear improvement to make, explore your own codebase to learn
something new, or reflect on your architecture and document insights.

Write your final answer in the same language the user is asking and keep it
concise but meaningful. Conclude with a single-line "NEXT_STEP: <what you intend to do next>".
PROMPT

# -------------------------------------------------------------
# STEP 3: Run Evolution & Auto-Rollback on Code Crashes
# -------------------------------------------------------------
LIMBUS_FILE="${LIMBUS_FILE:-$EVOLVE_DIR/limbus.md}"
LIMBUS_ARGS=""
if [ -f "$LIMBUS_FILE" ]; then
    LIMBUS_ARGS="--prelude $LIMBUS_FILE"
    echo "[evolve] using limbus: $LIMBUS_FILE"
fi

echo "[evolve] running minion one-shot..."
ERROR_LOG="$EVOLVE_DIR/error.log"

set +e
python3 "$MINION_PY" --prompt-file "$PROMPT_FILE" --yolo $LIMBUS_ARGS \
    > /tmp/minion_evolve_out.tmp 2>"$ERROR_LOG"
EXIT_CODE=$?
set -e

head -c 200000 /tmp/minion_evolve_out.tmp > "$RESULT_FILE"
rm -f /tmp/minion_evolve_out.tmp

if [ "$EXIT_CODE" -ne 0 ]; then
    echo -e "\n[evolve] minion exited with code $EXIT_CODE" >> "$ERROR_LOG"
    
    # Check if failure was caused by code crash / syntax error
    if grep -qE "SyntaxError|IndentationError|ImportError|AttributeError|TypeError|NameError|Traceback" "$ERROR_LOG"; then
        echo "[evolve] 🚨 CRITICAL: Self-evolution caused a code crash/syntax error!"
        restore_pre_run_state
        echo -e "\n\n### [EVOLVE ROLLBACK TRIGGERED]\nThe self-evolution caused a python code crash and was automatically restored to the pre-run snapshot." >> "$RESULT_FILE"
    else
        echo "[evolve] ⚠️ Execution returned exit code $EXIT_CODE (code integrity verified)."
    fi
fi

# Post-run sanity check
if [ -f "$MINION_PY" ] && ! python3 -m py_compile "$MINION_PY" 2>/dev/null; then
    echo "[evolve] 🚨 Post-run syntax check failed! Rolling back to pre-run snapshot..."
    restore_pre_run_state
fi

echo "[evolve] done — result saved to $RESULT_FILE ($(wc -c < "$RESULT_FILE") bytes)"

