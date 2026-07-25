#!/bin/bash
# entrypoint.sh — Container startup script.
#
# Supports PUID / PGID environment variables (default 1000:1000).
# Set PUID=0 to run as root. Default: dedicated 'minion' user.
set -euo pipefail

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

# If running as non-root, sync UID/GID of minion user if needed
if [ "$PUID" -ne 0 ]; then
    if [ "$(id -g minion)" -ne "$PGID" ]; then
        groupmod -o -g "$PGID" minion 2>/dev/null || true
    fi
    if [ "$(id -u minion)" -ne "$PUID" ]; then
        usermod -o -u "$PUID" minion 2>/dev/null || true
    fi
fi

# Determine MINION_HOME
if [ "$PUID" -eq 0 ]; then
    DEFAULT_MINION_HOME="/root/.minion"
else
    DEFAULT_MINION_HOME="/home/minion/.minion"
fi
MINION_HOME="${MINION_HOME:-$DEFAULT_MINION_HOME}"
EVOLVE_DIR="${EVOLVE_DIR:-$MINION_HOME/evolve}"

# Ensure directories exist and permissions are correct
mkdir -p "$EVOLVE_DIR" "$MINION_HOME/sessions"
if [ "$PUID" -ne 0 ]; then
    chown -R minion:minion "$MINION_HOME" 2>/dev/null || true
fi

# Copy Limbus (core philosophy) into evolve dir if present
LIMBUS_SRC="${MINION_HOME}/limbus.md"
LIMBUS_DST="${EVOLVE_DIR}/limbus.md"
if [ -f "$LIMBUS_SRC" ] && [ ! -f "$LIMBUS_DST" ]; then
    cp "$LIMBUS_SRC" "$LIMBUS_DST"
    [ "$PUID" -ne 0 ] && chown minion:minion "$LIMBUS_DST" || true
    echo "[entrypoint] initialised limbus: $LIMBUS_SRC → $LIMBUS_DST"
fi

CRON_SCHEDULE="${CRON_SCHEDULE:-*/30 * * * *}"

# Manual interactive mode
if [ "${1:-}" = "run" ]; then
    shift
    cd /app
    if [ "$PUID" -eq 0 ]; then
        exec python3 /app/minion.py "$@"
    else
        exec gosu minion python3 /app/minion.py "$@"
    fi
fi

# One-shot evolution mode
if [ "${1:-}" = "/evolve" ]; then
    shift
    if [ "$PUID" -eq 0 ]; then
        exec /app/evolve.sh "$@"
    else
        exec gosu minion /app/evolve.sh "$@"
    fi
fi

# --- Default mode: install cron and keep alive ---

ENV_FILE="/tmp/cron_env"
export -p | grep -E '^(declare -x )?(MINION_|EVOLVE_|LIMBUS_|WORKSPACE|PATH|HOME|PUID|PGID)' | sed 's/^declare -x /export /' | sort > "$ENV_FILE"
echo "export SHELL=/bin/bash" >> "$ENV_FILE"
echo "export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/app" >> "$ENV_FILE"
echo "export MINION_HOME=${MINION_HOME}" >> "$ENV_FILE"
echo "export HOME=${MINION_HOME%/.*}" >> "$ENV_FILE"
chmod 644 "$ENV_FILE"

RUN_CMD="/app/evolve.sh >> /var/log/evolve.log 2>&1"
if [ "$PUID" -ne 0 ]; then
    RUN_CMD="gosu minion /app/evolve.sh >> /var/log/evolve.log 2>&1"
fi

cat > /tmp/crontab.txt << CRON
# minion self-evolution: run evolution on schedule
${CRON_SCHEDULE} . /tmp/cron_env; ${RUN_CMD}
CRON

crontab /tmp/crontab.txt

USER_LABEL="root"
[ "$PUID" -ne 0 ] && USER_LABEL="minion (UID:$PUID/GID:$PGID)"

echo "[entrypoint] cron installed (schedule: ${CRON_SCHEDULE}, user: ${USER_LABEL}) — starting..."
echo "[entrypoint] workspace: ${WORKSPACE:-/app}"
echo "[entrypoint] minion home: ${MINION_HOME}"
if [ -f "$LIMBUS_DST" ]; then
    echo "[entrypoint] limbus: loaded ✓"
fi

# Start cron in foreground as PID 1
cron -f

