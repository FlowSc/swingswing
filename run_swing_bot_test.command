#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
export PYTHONPATH="$SCRIPT_DIR"
export PYTHONNOUSERSITE=1
export PYTHONPYCACHEPREFIX="$SCRIPT_DIR/output/pycache"

mkdir -p output

if [ ! -f "kis_config.local.env" ]; then
  echo "Missing kis_config.local.env"
  echo "Run ./setup_kis_config.command first."
  echo "Press Enter to close."
  read -r _
  exit 1
fi

PYTHON_BIN="/usr/bin/python3"
VENV_DIR=".venv-swingbot"

if [ ! -d "$VENV_DIR" ]; then
  echo "Creating virtual environment with $PYTHON_BIN..."
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

DEPS_MARKER="$VENV_DIR/.deps-installed"
if [ ! -f "$DEPS_MARKER" ] || [ "requirements.txt" -nt "$DEPS_MARKER" ]; then
  echo "Installing required packages..."
  python -m pip install -r requirements.txt
  touch "$DEPS_MARKER"
else
  echo "Required packages already installed."
fi

echo "Running unified swing bot in test mode..."
python run_swing_bot.py --once --test-mode

echo
echo "Done. Test mode does not place KIS paper orders unless --allow-test-orders is used."
echo "Check output/positions.json and output/trade_log.csv."
echo "Press Enter to close."
read -r _
