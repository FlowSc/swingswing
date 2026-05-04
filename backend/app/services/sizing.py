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
        return 0, {"reject_reason": "invalid_price_or_stop", "price": float(price), "stop_loss": stop_loss, "per_share_risk": per_share_risk}

    max_position_capital = total_equity * position_capital_pct
    max_risk_capital = total_equity * risk_per_trade_pct
    slot_cash_capital = cash / max(available_slots, 1)
    usable_capital = min(max_position_capital, slot_cash_capital, cash)

    qty_by_capital = int(usable_capital // price)
    qty_by_risk = int(max_risk_capital // per_share_risk)
    qty = min(qty_by_capital, qty_by_risk)
    reject_reason = ""
    if qty_by_risk <= 0:
        reject_reason = "risk_budget_too_small"
    elif qty_by_capital <= 0:
        reject_reason = "cash_or_position_capital_too_small"
    elif qty * price < min_order_amount:
        reject_reason = "below_min_order_amount"
    if qty * price < min_order_amount:
        return 0, {
            "reject_reason": reject_reason or "below_min_order_amount",
            "price": float(price),
            "stop_loss": stop_loss,
            "per_share_risk": per_share_risk,
            "cash": float(cash),
            "total_equity": float(total_equity),
            "usable_capital": usable_capital,
            "max_position_capital": max_position_capital,
            "max_risk_capital": max_risk_capital,
            "slot_cash_capital": slot_cash_capital,
            "qty_by_capital": float(qty_by_capital),
            "qty_by_risk": float(qty_by_risk),
            "candidate_qty": float(qty),
            "candidate_order_amount": float(qty * price),
            "min_order_amount": float(min_order_amount),
            "risk_per_trade_pct": float(risk_per_trade_pct),
            "position_capital_pct": float(position_capital_pct),
        }

    return qty, {
        "reject_reason": "",
        "price": float(price),
        "stop_loss": stop_loss,
        "per_share_risk": per_share_risk,
        "cash": float(cash),
        "total_equity": float(total_equity),
        "usable_capital": usable_capital,
        "max_position_capital": max_position_capital,
        "max_risk_capital": max_risk_capital,
        "slot_cash_capital": slot_cash_capital,
        "qty_by_capital": float(qty_by_capital),
        "qty_by_risk": float(qty_by_risk),
        "min_order_amount": float(min_order_amount),
        "risk_per_trade_pct": float(risk_per_trade_pct),
        "position_capital_pct": float(position_capital_pct),
        "order_amount": float(qty * price),
        "risk_amount": float(qty * per_share_risk),
    }
