#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

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
python -m pip install requests

if [ ! -f "kis_config.local.env" ]; then
  echo
  echo "Missing kis_config.local.env. Run ./setup_kis_config.command first."
  echo "Press Enter to close."
  read -r _
  exit 1
fi

echo
echo "Running KIS paper connection test..."
python kis_test_connection.py

echo
echo "Press Enter to close."
read -r _
