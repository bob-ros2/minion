#!/bin/bash
# entrypoint.sh — Container startup script.
#
# Two modes:
#   DEFAULT: start cron + keep the container alive (cron -f as PID 1)
#   When /evolve is passed: run evolve.sh once and exit (for manual/one-shot use)
set -euo pipefail

CRON_SCHEDULE="${CRON_SCHEDULE:-*/30 * * * *}"

# If "run" was passed, exec minion interactively (for debugging / manual use)
if [ "${1:-}" = "run" ]; then
    shift
    cd /app
    exec python3 /app/minion.py "$@"
fi

# If "/evolve" was passed, do one evolution pass and exit
if [ "${1:-}" = "/evolve" ]; then
    shift
    exec /app/evolve.sh "$@"
fi

# --- Default mode: install cron and keep alive ---

# Initialize the evolve directory
EVOLVE_DIR="${EVOLVE_DIR:-/root/.minion/evolve}"
mkdir -p "$EVOLVE_DIR"

# Copy the Limbus (core philosophy) into the evolve dir if it exists
# at the top level of MINION_HOME. This makes it available to evolve.sh
# even though the file lives at ~/.minion/limbus.md on the host.
LIMBUS_SRC="${MINION_HOME:-/root/.minion}/limbus.md"
LIMBUS_DST="${EVOLVE_DIR}/limbus.md"
if [ -f "$LIMBUS_SRC" ] && [ ! -f "$LIMBUS_DST" ]; then
    cp "$LIMBUS_SRC" "$LIMBUS_DST"
    echo "[entrypoint] initialised limbus: $LIMBUS_SRC → $LIMBUS_DST"
fi

# Write cron env file with all relevant variables
export -p | grep -E '^(declare -x )?(MINION_|EVOLVE_|LIMBUS_|WORKSPACE|PATH|HOME)' | sed 's/^declare -x /export /' | sort > /tmp/cron_env
echo "export SHELL=/bin/bash" >> /tmp/cron_env
echo "export PATH=/usr/local/bin:/usr/bin:/bin:/app" >> /tmp/cron_env

# Install crontab
cat > /tmp/crontab.txt << CRON
# minion self-evolution: run evolution on schedule
${CRON_SCHEDULE} . /tmp/cron_env; /app/evolve.sh >> /var/log/evolve.log 2>&1
CRON

crontab /tmp/crontab.txt

echo "[entrypoint] cron installed (schedule: ${CRON_SCHEDULE}) — starting..."
echo "[entrypoint] workspace: ${WORKSPACE:-/app}"
echo "[entrypoint] evolve dir: ${EVOLVE_DIR}"
if [ -f "$LIMBUS_DST" ]; then
    echo "[entrypoint] limbus: loaded ✓"
fi

# Start cron in foreground as PID 1 (keeps container alive)
cron -f
