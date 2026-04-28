# ============================================================
#  KIS paper order trader for KOSPI swing signals
#  Places paper buy orders from output/swing_signals_YYYYMMDD.json.
# ============================================================

from __future__ import annotations

from datetime import datetime
from typing import Any

from kis_client import KisClient, load_config_from_env
import paper_trader


def extract_cash(balance: dict[str, Any]) -> int:
    output2 = balance.get("output2", [])
    if not output2:
        return paper_trader.DEFAULT_CAPITAL
    raw_value = output2[0].get("dnca_tot_amt") or output2[0].get("ord_psbl_cash") or "0"
    try:
        return int(float(str(raw_value).replace(",", "")))
    except ValueError:
        return paper_trader.DEFAULT_CAPITAL


def extract_total_equity(balance: dict[str, Any]) -> int:
    output2 = balance.get("output2", [])
    if not output2:
        return paper_trader.DEFAULT_CAPITAL
    raw_value = output2[0].get("tot_evlu_amt") or output2[0].get("dnca_tot_amt") or "0"
    try:
        value = int(float(str(raw_value).replace(",", "")))
    except ValueError:
        value = paper_trader.DEFAULT_CAPITAL
    return max(value, 1)


def kis_holding_codes(balance: dict[str, Any]) -> set[str]:
    codes = set()
    for item in balance.get("output1", []):
        code = item.get("pdno") or item.get("PDNO")
        qty = item.get("hldg_qty") or item.get("HLDG_QTY") or "0"
        try:
            qty_value = int(float(str(qty).replace(",", "")))
        except ValueError:
            qty_value = 0
        if code and qty_value > 0:
            codes.add(str(code).zfill(6))
    return codes


def order_price(signal: dict) -> int:
    return int(round(float(signal["Entry"])))


def calculate_order_qty(signal: dict, *, cash: int, total_equity: int, available_slots: int) -> tuple[int, dict[str, float]]:
    price = order_price(signal)
    stop_loss = float(signal["StopLoss"])
    per_share_risk = max(price - stop_loss, 0)
    if price <= 0 or per_share_risk <= 0:
        return 0, {}

    max_position_capital = total_equity * paper_trader.POSITION_CAPITAL_PCT
    max_risk_capital = total_equity * paper_trader.RISK_PER_TRADE_PCT
    slot_cash_capital = cash / max(available_slots, 1)
    usable_capital = min(max_position_capital, slot_cash_capital, cash)

    qty_by_capital = int(usable_capital // price)
    qty_by_risk = int(max_risk_capital // per_share_risk)
    qty = min(qty_by_capital, qty_by_risk)
    if qty * price < paper_trader.MIN_ORDER_AMOUNT:
        return 0, {
            "price": price,
            "per_share_risk": per_share_risk,
            "usable_capital": usable_capital,
            "max_risk_capital": max_risk_capital,
        }

    sizing = {
        "price": price,
        "per_share_risk": per_share_risk,
        "usable_capital": usable_capital,
        "max_position_capital": max_position_capital,
        "max_risk_capital": max_risk_capital,
        "qty_by_capital": qty_by_capital,
        "qty_by_risk": qty_by_risk,
        "order_amount": qty * price,
        "risk_amount": qty * per_share_risk,
    }
    return qty, sizing


def select_order_candidates(signals: list[dict], positions: dict, kis_codes: set[str], cash: int) -> list[dict]:
    open_positions = [position for position in positions["positions"] if position.get("Status") == "OPEN"]
    open_codes = {position["Code"] for position in open_positions}
    blocked_codes = open_codes | kis_codes
    available_slots = max(0, paper_trader.MAX_OPEN_POSITIONS - len(open_positions) - len(kis_codes))
    daily_slots = min(paper_trader.MAX_NEW_POSITIONS_PER_DAY, available_slots)
    if daily_slots <= 0:
        return []

    candidates = [
        signal
        for signal in signals
        if signal.get("Code") not in blocked_codes and float(signal.get("Score", 0)) >= paper_trader.MIN_SCORE
    ]
    candidates.sort(key=lambda item: (item.get("Score", 0), item.get("BBExpansion(%)", 0)), reverse=True)

    total_equity = max(cash, paper_trader.DEFAULT_CAPITAL)
    selected = []
    for signal in candidates:
        qty, sizing = calculate_order_qty(signal, cash=cash, total_equity=total_equity, available_slots=daily_slots)
        if qty <= 0:
            continue
        selected.append({**signal, "OrderPrice": int(sizing["price"]), "OrderQty": qty, "Sizing": sizing})
        if len(selected) >= daily_slots:
            break
    return selected


def main() -> None:
    config = load_config_from_env()
    if config.env != "paper":
        raise RuntimeError("kis_paper_trader.py only runs with KIS_ENV=paper.")
    if not config.enable_orders:
        raise RuntimeError("Set KIS_ENABLE_ORDERS=true in kis_config.local.env to place paper orders.")

    client = KisClient(config)
    signal_file = paper_trader.latest_signal_file()
    signals = paper_trader.load_signals(signal_file)
    positions = paper_trader.load_positions()
    balance = client.get_balance()
    cash = extract_cash(balance)
    total_equity = extract_total_equity(balance)
    kis_codes = kis_holding_codes(balance)
    candidates = select_order_candidates(signals, positions, kis_codes, cash)

    new_positions = []
    logs = []
    for signal in candidates:
        response = client.buy_limit(signal["Code"], signal["OrderQty"], signal["OrderPrice"])
        order_no = ""
        output = response.get("output", {})
        if isinstance(output, dict):
            order_no = output.get("ODNO", "") or output.get("odno", "")

        capital_used = signal["OrderQty"] * signal["OrderPrice"]
        position = paper_trader.make_position(signal, signal["OrderQty"], capital_used)
        position["Entry"] = signal["OrderPrice"]
        position["Source"] = "kis_paper_trader"
        position["KisOrderNo"] = order_no
        position["KisOrderResponse"] = response
        position["Sizing"] = signal.get("Sizing", {})
        new_positions.append(position)
        logs.append(
            {
                "Date": paper_trader.today_text(),
                "Action": "KIS_PAPER_BUY",
                "Code": signal["Code"],
                "Name": signal["Name"],
                "Price": signal["OrderPrice"],
                "Qty": signal["OrderQty"],
                "Reason": f"KIS paper order placed. order_no={order_no}",
                "StopLoss": signal["StopLoss"],
                "TakeProfit1": signal["TakeProfit1"],
                "TakeProfit2": signal["TakeProfit2"],
                "TrailingStop": signal["TrailingStop"],
                "Score": signal["Score"],
            }
        )

    positions["positions"].extend(new_positions)
    positions["UpdatedAt"] = datetime.now().isoformat(timespec="seconds")
    paper_trader.save_positions(positions)
    paper_trader.append_trade_log(logs)

    print("=" * 64)
    print("  KIS Paper Trader")
    print("=" * 64)
    print(f"Signal file: {signal_file}")
    print(f"Signals loaded: {len(signals)}")
    print(f"KIS holdings: {len(kis_codes)}")
    print(f"Available cash: {cash:,}")
    print(f"Total equity: {total_equity:,}")
    print(f"Paper orders placed: {len(new_positions)}")
    print(f"Positions file: {paper_trader.POSITIONS_FILE}")
    print(f"Trade log: {paper_trader.TRADE_LOG_FILE}")


if __name__ == "__main__":
    main()
