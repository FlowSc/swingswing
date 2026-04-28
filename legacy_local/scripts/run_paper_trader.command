#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

mkdir -p output

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
python -m pip install finance-datareader pandas openpyxl

echo "Running paper_trader.py..."
python paper_trader.py

echo
echo "Done. Check output/positions.json and output/trade_log.csv."
echo "Press Enter to close."
read -r _
