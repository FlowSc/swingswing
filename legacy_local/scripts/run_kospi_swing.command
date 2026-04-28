#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

mkdir -p output

echo "Project folder: $SCRIPT_DIR"
echo "Results folder: $SCRIPT_DIR/output"

if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  if command -v python3 >/dev/null 2>&1; then
    python3 -m venv .venv
  else
    python -m venv .venv
  fi
fi

source ".venv/bin/activate"

echo "Upgrading pip..."
python -m pip install --upgrade pip

echo "Installing required packages..."
python -m pip install finance-datareader pandas openpyxl

echo "Running kospi_swing.py..."
python kospi_swing.py

echo
echo "Done. Excel files are saved in the output folder."
echo "Press Enter to close."
read -r _
