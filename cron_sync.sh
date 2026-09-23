#!/usr/bin/env bash
# Wrapper for cron — sets up environment and runs incremental load.
# Logs to loco_loader/cron.log

set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/cron.log"
VENV="$DIR/.venv/bin/python3"

echo "--- $(date) ---" >> "$LOG"

if [ ! -f "$VENV" ]; then
    echo "ERROR: venv not found at $VENV" >> "$LOG"
    exit 1
fi

# Source brew so cortex CLI is on PATH
eval "$(/opt/homebrew/bin/brew shellenv zsh 2>/dev/null || true)"
export PATH="/Users/samdillard/.local/bin:$PATH"
export SNOWFLAKE_CONNECTION="${SNOWFLAKE_CONNECTION:-demo-account-admin-sdillard}"

"$VENV" "$DIR/incremental_load.py" >> "$LOG" 2>&1
echo "Exit: $?" >> "$LOG"
