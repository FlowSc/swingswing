# ============================================================
#  KIS intraday watcher for swing paper trading
#  Watches signals and open positions during market hours.
# ============================================================

from __future__ import annotations

import argparse
from datetime import date, datetime, time
import time as time_module
from typing import Any

from kis_client import KisClient, load_config_from_env
import kis_paper_trader
import paper_trader
from telegram_notifier import send_status, send_trade_events, telegram_configured


ENTRY_START = time(9, 20)
ENTRY_END = time(10, 30)
MANAGE_START = time(9, 20)
MANAGE_END = time(15, 10)
FORCE_STOP_TIME = time(15, 20)
DEFAULT_INTERVAL_SECONDS = 300
QUOTE_REQUEST_DELAY_SECONDS = 1.0
QUOTE_ERROR_BACKOFF_SECONDS = 3.0
MAX_ENTRY_PREMIUM = 1.02
MIN_ENTRY_DISCOUNT = 0.995
MAX_PULLBACK_FROM_DAY_HIGH = 0.03
TEST_MODE = False
ALLOW_TEST_ORDERS = False


def now_time() -> time:
    return datetime.now().time()


def in_time_range(start: time, end: time) -> bool:
    if TEST_MODE:
        return True
    current = now_time()
    return start <= current <= end


def parse_price(payload: dict[str, Any]) -> int:
    output = payload.get("output", {})
    raw_value = output.get("stck_prpr") or output.get("STCK_PRPR") or "0"
    return int(float(str(raw_value).replace(",", "")))


def parse_int_field(output: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = output.get(key)
        if value not in {None, ""}:
            return int(float(str(value).replace(",", "")))
    return 0


def parse_quote(payload: dict[str, Any]) -> dict[str, int]:
    output = payload.get("output", {})
    return {
        "current_price": parse_int_field(output, "stck_prpr", "STCK_PRPR"),
        "day_high": parse_int_field(output, "stck_hgpr", "STCK_HGPR"),
        "day_low": parse_int_field(output, "stck_lwpr", "STCK_LWPR"),
        "accumulated_volume": parse_int_field(output, "acml_vol", "ACML_VOL"),
    }


def get_current_price_safe(client: KisClient, code: str) -> int | None:
    try:
        payload = client.get_current_price(code)
        time_module.sleep(QUOTE_REQUEST_DELAY_SECONDS)
        return parse_price(payload)
    except Exception as exc:
        print(f"quote failed: {code} {exc}")
        time_module.sleep(QUOTE_ERROR_BACKOFF_SECONDS)
        return None


def get_quote_safe(client: KisClient, code: str) -> dict[str, int] | None:
    try:
        payload = client.get_current_price(code)
        time_module.sleep(QUOTE_REQUEST_DELAY_SECONDS)
        return parse_quote(payload)
    except Exception as exc:
        print(f"quote failed: {code} {exc}")
        time_module.sleep(QUOTE_ERROR_BACKOFF_SECONDS)
        return None


def passes_intraday_entry_filter(signal: dict, quote: dict[str, int]) -> tuple[bool, str]:
    current_price = quote["current_price"]
    day_high = quote.get("day_high") or current_price
    entry = float(signal["Entry"])
    kijun = float(signal.get("Kijun") or 0)
    bb_upper = float(signal.get("BBUpper") or entry * 1.1)

    if current_price < entry * MIN_ENTRY_DISCOUNT:
        return False, "BelowEntryBand"
    if current_price > entry * MAX_ENTRY_PREMIUM:
        return False, "AboveEntryBand"
    if kijun > 0 and current_price < kijun:
        return False, "BelowKijun"
    if current_price > bb_upper:
        return False, "AboveBBUpper"
    if day_high > 0 and current_price < day_high * (1 - MAX_PULLBACK_FROM_DAY_HIGH):
        return False, "PulledBackFromDayHigh"
    return True, "IntradayEntry"


def trading_days_held(entry_date: str) -> int:
    try:
        start = date.fromisoformat(entry_date)
    except ValueError:
        return 0
    return max(0, (date.today() - start).days)


def place_sell_all(client: KisClient, position: dict, price: int, reason: str) -> dict:
    qty = int(position.get("RemainingQty", 0))
    if qty <= 0:
        return {}
    if TEST_MODE and not ALLOW_TEST_ORDERS:
        return {"test_mode": True, "side": "sell", "code": position["Code"], "qty": qty, "price": price}
    response = client.sell_limit(position["Code"], qty, price)
    position["RemainingQty"] = 0
    position["Status"] = "CLOSED"
    position["ClosedAt"] = datetime.now().isoformat(timespec="seconds")
    position["CloseReason"] = reason
    return response


def place_partial_sell(client: KisClient, position: dict, ratio: float, price: int, reason: str) -> dict:
    remaining_qty = int(position.get("RemainingQty", 0))
    qty = max(1, int(int(position.get("Qty", 0)) * ratio))
    qty = min(qty, remaining_qty)
    if qty <= 0:
        return {}
    if TEST_MODE and not ALLOW_TEST_ORDERS:
        return {"test_mode": True, "side": "sell", "code": position["Code"], "qty": qty, "price": price}
    response = client.sell_limit(position["Code"], qty, price)
    position["RemainingQty"] = remaining_qty - qty
    if position["RemainingQty"] <= 0:
        position["Status"] = "CLOSED"
        position["ClosedAt"] = datetime.now().isoformat(timespec="seconds")
        position["CloseReason"] = reason
    return response


def log_order(action: str, position: dict, price: int, qty: int, reason: str) -> dict:
    return {
        "Date": paper_trader.today_text(),
        "Action": action,
        "Code": position["Code"],
        "Name": position["Name"],
        "Price": price,
        "Qty": qty,
        "Reason": reason,
        "StopLoss": position.get("StopLoss", ""),
        "TakeProfit1": position.get("TakeProfit1", ""),
        "TakeProfit2": position.get("TakeProfit2", ""),
        "TrailingStop": position.get("TrailingStop", ""),
        "Score": position.get("Score", ""),
    }


def manage_open_positions(client: KisClient, positions: dict) -> list[dict]:
    if not in_time_range(MANAGE_START, MANAGE_END):
        return []

    logs = []
    for position in positions.get("positions", []):
        if position.get("Status") != "OPEN":
            continue

        current_price = get_current_price_safe(client, position["Code"])
        if current_price is None:
            continue
        remaining_before = int(position.get("RemainingQty", 0))
        if remaining_before <= 0:
            position["Status"] = "CLOSED"
            continue

        stop_loss = float(position["StopLoss"])
        take_profit_1 = float(position["TakeProfit1"])
        take_profit_2 = float(position["TakeProfit2"])
        trailing_stop = float(position["TrailingStop"])
        hold_max_days = int(position.get("HoldMaxDays", 15))
        held_days = trading_days_held(position.get("EntryDate", paper_trader.today_text()))

        if current_price <= stop_loss:
            place_sell_all(client, position, current_price, "StopLoss")
            logs.append(log_order("KIS_PAPER_SELL_ALL", position, current_price, remaining_before, "StopLoss"))
            continue

        if current_price <= trailing_stop and (position.get("TakeProfit1Done") or position.get("TakeProfit2Done")):
            place_sell_all(client, position, current_price, "TrailingStop")
            logs.append(log_order("KIS_PAPER_SELL_ALL", position, current_price, remaining_before, "TrailingStop"))
            continue

        if held_days >= hold_max_days:
            place_sell_all(client, position, current_price, "TimeExit")
            logs.append(log_order("KIS_PAPER_SELL_ALL", position, current_price, remaining_before, "TimeExit"))
            continue

        if not position.get("TakeProfit1Done") and current_price >= take_profit_1:
            sell_qty = min(max(1, int(int(position.get("Qty", 0)) * 0.3)), remaining_before)
            place_partial_sell(client, position, 0.3, current_price, "TakeProfit1")
            position["TakeProfit1Done"] = True
            logs.append(log_order("KIS_PAPER_SELL_PARTIAL", position, current_price, sell_qty, "TakeProfit1"))
            continue

        if not position.get("TakeProfit2Done") and current_price >= take_profit_2:
            sell_qty = min(max(1, int(int(position.get("Qty", 0)) * 0.3)), remaining_before)
            place_partial_sell(client, position, 0.3, current_price, "TakeProfit2")
            position["TakeProfit2Done"] = True
            logs.append(log_order("KIS_PAPER_SELL_PARTIAL", position, current_price, sell_qty, "TakeProfit2"))

    return logs


def enter_new_positions(client: KisClient, positions: dict) -> list[dict]:
    if not in_time_range(ENTRY_START, ENTRY_END):
        return []

    signal_file = paper_trader.latest_signal_file()
    signals = paper_trader.load_signals(signal_file)
    try:
        balance = client.get_balance()
    except Exception as exc:
        print(f"balance failed: {exc}")
        return []
    cash = kis_paper_trader.extract_cash(balance)
    kis_codes = kis_paper_trader.kis_holding_codes(balance)
    candidates = kis_paper_trader.select_order_candidates(signals, positions, kis_codes, cash)
    if TEST_MODE and not ALLOW_TEST_ORDERS:
        candidates = candidates[:1]

    new_positions = []
    logs = []
    for signal in candidates:
        quote = get_quote_safe(client, signal["Code"])
        if quote is None or quote["current_price"] <= 0:
            continue
        current_price = quote["current_price"]
        passed, reason = passes_intraday_entry_filter(signal, quote)
        if not passed:
            continue

        signal_for_sizing = {**signal, "Entry": current_price}
        qty, sizing = kis_paper_trader.calculate_order_qty(
            signal_for_sizing,
            cash=cash,
            total_equity=max(cash, paper_trader.DEFAULT_CAPITAL),
            available_slots=max(1, len(candidates)),
        )
        if qty <= 0:
            continue
        if TEST_MODE and not ALLOW_TEST_ORDERS:
            response = {"test_mode": True, "side": "buy", "code": signal["Code"], "qty": qty, "price": current_price}
        else:
            response = client.buy_limit(signal["Code"], qty, current_price)
        position = paper_trader.make_position(signal, qty, qty * current_price)
        position["Entry"] = current_price
        position["Source"] = "kis_intraday_watcher"
        position["KisOrderResponse"] = response
        position["IntradayQuote"] = quote
        position["Sizing"] = sizing
        new_positions.append(position)
        logs.append(log_order("KIS_PAPER_BUY", position, current_price, qty, reason))

    positions["positions"].extend(new_positions)
    return logs


def run_once(client: KisClient) -> None:
    positions = paper_trader.load_positions()
    logs = []
    logs.extend(manage_open_positions(client, positions))
    logs.extend(enter_new_positions(client, positions))
    positions["UpdatedAt"] = datetime.now().isoformat(timespec="seconds")
    paper_trader.save_positions(positions)
    paper_trader.append_trade_log(logs)
    if logs and telegram_configured():
        send_trade_events(logs)

    print(
        f"{datetime.now().strftime('%H:%M:%S')} "
        f"actions={len(logs)} open={sum(1 for item in positions['positions'] if item.get('Status') == 'OPEN')}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run KIS intraday swing watcher.")
    parser.add_argument("--once", action="store_true", help="Run one watcher tick and exit.")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_SECONDS, help="Loop interval in seconds.")
    parser.add_argument("--test-mode", action="store_true", help="Ignore market time windows and do not place orders by default.")
    parser.add_argument("--allow-test-orders", action="store_true", help="Allow paper orders even in test mode.")
    args = parser.parse_args()
    global TEST_MODE, ALLOW_TEST_ORDERS
    TEST_MODE = args.test_mode
    ALLOW_TEST_ORDERS = args.allow_test_orders

    config = load_config_from_env()
    if config.env != "paper":
        raise RuntimeError("kis_intraday_watcher.py only runs with KIS_ENV=paper.")
    if not config.enable_orders:
        raise RuntimeError("Set KIS_ENABLE_ORDERS=true in kis_config.local.env to place paper orders.")

    client = KisClient(config)
    print("=" * 64)
    print("  KIS Intraday Swing Watcher")
    print("=" * 64)
    print(f"Entry window: {ENTRY_START.strftime('%H:%M')} - {ENTRY_END.strftime('%H:%M')}")
    print(f"Manage window: {MANAGE_START.strftime('%H:%M')} - {MANAGE_END.strftime('%H:%M')}")
    print(f"Interval: {args.interval}s")
    print(f"Test mode: {TEST_MODE}")
    print(f"Allow test orders: {ALLOW_TEST_ORDERS}")
    if telegram_configured():
        send_status(
            "Watcher online\n"
            f"Test mode: {TEST_MODE}\n"
            f"Allow test orders: {ALLOW_TEST_ORDERS}"
        )

    if args.once:
        run_once(client)
        return

    while now_time() <= FORCE_STOP_TIME:
        run_once(client)
        time_module.sleep(args.interval)

    print("Watcher stopped after market management window.")
    if telegram_configured():
        send_status("Watcher stopped after market management window.")


if __name__ == "__main__":
    main()
