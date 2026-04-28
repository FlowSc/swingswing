# ============================================================
#  Paper trader for KOSPI swing signals
#  Reads output/swing_signals_YYYYMMDD.json and manages mock positions.
# ============================================================

from __future__ import annotations

import csv
from datetime import datetime
import json
from pathlib import Path


OUTPUT_DIR = Path("output")
POSITIONS_FILE = OUTPUT_DIR / "positions.json"
TRADE_LOG_FILE = OUTPUT_DIR / "trade_log.csv"

MAX_NEW_POSITIONS_PER_DAY = 2
MAX_OPEN_POSITIONS = 5
DEFAULT_CAPITAL = 10_000_000
POSITION_CAPITAL_PCT = 0.18
RISK_PER_TRADE_PCT = 0.01
MIN_ORDER_AMOUNT = 100_000
MIN_SCORE = 12


def today_text() -> str:
    return datetime.today().strftime("%Y-%m-%d")


def today_compact() -> str:
    return datetime.today().strftime("%Y%m%d")


def load_json(path: Path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_json(path: Path, payload) -> None:
    path.parent.mkdir(exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


def load_positions() -> dict:
    return load_json(POSITIONS_FILE, {"positions": []})


def save_positions(positions: dict) -> None:
    save_json(POSITIONS_FILE, positions)


def latest_signal_file() -> Path:
    dated_file = OUTPUT_DIR / f"swing_signals_{today_compact()}.json"
    if dated_file.exists():
        return dated_file

    signal_files = sorted(OUTPUT_DIR.glob("swing_signals_*.json"))
    if not signal_files:
        raise FileNotFoundError("No swing signal JSON file found in output/. Run kospi_swing.py first.")
    return signal_files[-1]


def load_signals(path: Path) -> list[dict]:
    payload = load_json(path, {})
    return payload.get("signals", [])


def append_trade_log(rows: list[dict]) -> None:
    if not rows:
        return

    TRADE_LOG_FILE.parent.mkdir(exist_ok=True)
    fieldnames = [
        "Date",
        "Action",
        "Code",
        "Name",
        "Price",
        "Qty",
        "Reason",
        "StopLoss",
        "TakeProfit1",
        "TakeProfit2",
        "TrailingStop",
        "Score",
    ]
    file_exists = TRADE_LOG_FILE.exists()
    with TRADE_LOG_FILE.open("a", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def make_position(signal: dict, qty: int, capital_used: float) -> dict:
    return {
        "Code": signal["Code"],
        "Name": signal["Name"],
        "EntryDate": today_text(),
        "Entry": signal["Entry"],
        "Qty": qty,
        "RemainingQty": qty,
        "CapitalUsed": round(capital_used, 2),
        "StopLoss": signal["StopLoss"],
        "TakeProfit1": signal["TakeProfit1"],
        "TakeProfit2": signal["TakeProfit2"],
        "TrailingStop": signal["TrailingStop"],
        "HoldMaxDays": signal["HoldMaxDays"],
        "Score": signal["Score"],
        "TakeProfit1Done": False,
        "TakeProfit2Done": False,
        "Status": "OPEN",
        "Source": "paper_trader",
    }


def select_new_positions(signals: list[dict], positions: dict) -> tuple[list[dict], list[dict]]:
    open_positions = [position for position in positions["positions"] if position.get("Status") == "OPEN"]
    open_codes = {position["Code"] for position in open_positions}
    available_slots = max(0, MAX_OPEN_POSITIONS - len(open_positions))
    daily_slots = min(MAX_NEW_POSITIONS_PER_DAY, available_slots)

    selected = []
    logs = []
    if daily_slots <= 0:
        return selected, logs

    candidates = [
        signal
        for signal in signals
        if signal.get("Code") not in open_codes and float(signal.get("Score", 0)) >= MIN_SCORE
    ]
    candidates.sort(key=lambda item: (item.get("Score", 0), item.get("BBExpansion(%)", 0)), reverse=True)

    capital_per_position = DEFAULT_CAPITAL * POSITION_CAPITAL_PCT
    for signal in candidates[:daily_slots]:
        entry = float(signal["Entry"])
        qty = int(capital_per_position // entry)
        if qty <= 0:
            continue

        capital_used = qty * entry
        position = make_position(signal, qty, capital_used)
        selected.append(position)
        logs.append(
            {
                "Date": today_text(),
                "Action": "PAPER_BUY",
                "Code": signal["Code"],
                "Name": signal["Name"],
                "Price": entry,
                "Qty": qty,
                "Reason": "New swing signal",
                "StopLoss": signal["StopLoss"],
                "TakeProfit1": signal["TakeProfit1"],
                "TakeProfit2": signal["TakeProfit2"],
                "TrailingStop": signal["TrailingStop"],
                "Score": signal["Score"],
            }
        )

    return selected, logs


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    signal_file = latest_signal_file()
    signals = load_signals(signal_file)
    positions = load_positions()

    selected, logs = select_new_positions(signals, positions)
    positions["positions"].extend(selected)
    positions["UpdatedAt"] = datetime.now().isoformat(timespec="seconds")

    save_positions(positions)
    append_trade_log(logs)

    print("=" * 64)
    print("  KOSPI Swing Paper Trader")
    print("=" * 64)
    print(f"Signal file: {signal_file}")
    print(f"Signals loaded: {len(signals)}")
    print(f"New paper positions: {len(selected)}")
    print(f"Open positions: {sum(1 for item in positions['positions'] if item.get('Status') == 'OPEN')}")
    print(f"Positions file: {POSITIONS_FILE}")
    print(f"Trade log: {TRADE_LOG_FILE}")


if __name__ == "__main__":
    main()
