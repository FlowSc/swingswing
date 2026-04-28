#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

mkdir -p output

if [ ! -f "kis_config.local.env" ]; then
  echo "Missing kis_config.local.env"
  echo "Run ./setup_kis_config.command first."
  echo "Press Enter to close."
  read -r _
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  if command -v python3 >/dev/null 2>&1; then
    python3 -m venv .venv
  else
    python -m venv .venv
  fi
fi

source ".venv/bin/activate"

echo "Installing required packages..."
python -m pip install requests pandas openpyxl finance-datareader

echo "Running KIS intraday watcher..."
python kis_intraday_watcher.py

echo
echo "Done. Check output/positions.json and output/trade_log.csv."
echo "Press Enter to close."
read -r _
