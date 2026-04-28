#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
export PYTHONPATH="$SCRIPT_DIR"
export PYTHONNOUSERSITE=1
export PYTHONPYCACHEPREFIX="$SCRIPT_DIR/output/pycache"

VENV_DIR=".venv-swingbot"
if [ ! -d "$VENV_DIR" ]; then
  /usr/bin/python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"
python -m pip install requests pandas openpyxl finance-datareader
python telegram_notifier.py

echo
echo "Press Enter to close."
read -r _
