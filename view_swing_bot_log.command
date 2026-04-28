#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="$SCRIPT_DIR/output/swing_bot_app.log"

mkdir -p "$SCRIPT_DIR/output"
touch "$LOG_FILE"

echo "KOSPI Swing Bot live log"
echo "Log file: $LOG_FILE"
echo "Press Ctrl+C to stop viewing the log. The bot process will keep running."
echo

tail -f "$LOG_FILE"
