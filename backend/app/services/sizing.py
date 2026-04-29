from __future__ import annotations


MAX_OPEN_POSITIONS = 5
MAX_NEW_POSITIONS_PER_DAY = 2
POSITION_CAPITAL_PCT = 0.18
RISK_PER_TRADE_PCT = 0.01
MIN_ORDER_AMOUNT = 100_000
MIN_SCORE = 12
DEFAULT_CAPITAL = 10_000_000


def calculate_order_qty(
    signal: dict,
    *,
    cash: int,
    total_equity: int,
    available_slots: int,
    position_capital_pct: float = POSITION_CAPITAL_PCT,
    risk_per_trade_pct: float = RISK_PER_TRADE_PCT,
    min_order_amount: int = MIN_ORDER_AMOUNT,
) -> tuple[int, dict[str, float]]:
    price = int(round(float(signal["entry"])))
    stop_loss = float(signal["stop_loss"])
    per_share_risk = max(price - stop_loss, 0)
    if price <= 0 or per_share_risk <= 0:
        return 0, {}

    max_position_capital = total_equity * position_capital_pct
    max_risk_capital = total_equity * risk_per_trade_pct
    slot_cash_capital = cash / max(available_slots, 1)
    usable_capital = min(max_position_capital, slot_cash_capital, cash)

    qty_by_capital = int(usable_capital // price)
    qty_by_risk = int(max_risk_capital // per_share_risk)
    qty = min(qty_by_capital, qty_by_risk)
    if qty * price < min_order_amount:
        return 0, {
            "price": float(price),
            "per_share_risk": per_share_risk,
            "usable_capital": usable_capital,
            "max_risk_capital": max_risk_capital,
        }

    return qty, {
        "price": float(price),
        "per_share_risk": per_share_risk,
        "usable_capital": usable_capital,
        "max_position_capital": max_position_capital,
        "max_risk_capital": max_risk_capital,
        "qty_by_capital": float(qty_by_capital),
        "qty_by_risk": float(qty_by_risk),
        "order_amount": float(qty * price),
        "risk_amount": float(qty * per_share_risk),
    }
