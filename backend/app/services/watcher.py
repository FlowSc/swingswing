from __future__ import annotations

import asyncio
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.services.kis import (
    client_from_credentials,
    extract_cash,
    extract_total_equity,
    kis_holding_codes,
    parse_current_price,
    parse_quote,
)
from app.services.sizing import (
    DEFAULT_CAPITAL,
    MAX_NEW_POSITIONS_PER_DAY,
    MAX_OPEN_POSITIONS,
    MIN_SCORE,
    calculate_order_qty,
)
from app.services.supabase_rest import SupabaseRest
from app.services.telegram import send_telegram_message


ENTRY_START = time(14, 30)
ENTRY_END = time(15, 20)
MANAGE_START = time(9, 20)
MANAGE_END = time(15, 20)
QUOTE_DELAY_SECONDS = 1.0
QUOTE_ERROR_BACKOFF_SECONDS = 3.0
MAX_ENTRY_PREMIUM = 1.02
MIN_ENTRY_DISCOUNT = 0.995
MAX_PULLBACK_FROM_DAY_HIGH = 0.03
REASON_LABELS = {
    "IntradayEntry": "장중 진입 조건 충족",
    "StopLoss": "손절가 도달",
    "TrailingStop": "추적 손절가 도달",
    "TimeExit": "최대 보유기간 도달",
    "TakeProfit1": "1차 익절가 도달",
    "TakeProfit2": "2차 익절가 도달",
}


def now_kst() -> datetime:
    return datetime.now(ZoneInfo(get_settings().timezone))


def in_window(start: time, end: time, *, test_mode: bool) -> bool:
    if test_mode:
        return True
    current = now_kst().time()
    return start <= current <= end


def days_held(entry_date: str | None) -> int:
    if not entry_date:
        return 0
    try:
        start = date.fromisoformat(entry_date)
    except ValueError:
        return 0
    return max(0, (now_kst().date() - start).days)


def reason_label(reason_code: str) -> str:
    return REASON_LABELS.get(reason_code, reason_code)


def exit_plan_from_source(source: dict) -> dict:
    raw = source.get("raw") or {}
    return {
        "entry_price": source.get("entry_price") or source.get("entry"),
        "stop_loss": source.get("stop_loss"),
        "take_profit_1": source.get("take_profit_1"),
        "take_profit_2": source.get("take_profit_2"),
        "trailing_stop": source.get("trailing_stop"),
        "hold_min_days": raw.get("HoldMinDays"),
        "hold_preferred_days": raw.get("HoldPreferredDays"),
        "hold_max_days": raw.get("HoldMaxDays", 15),
        "planned_entry_window": "14:30-15:20",
        "planned_manage_window": "09:20-15:20",
    }


async def get_price_safe(client, code: str) -> int | None:
    try:
        payload = await client.get_current_price(code)
        await asyncio.sleep(QUOTE_DELAY_SECONDS)
        return parse_current_price(payload)
    except Exception:
        await asyncio.sleep(QUOTE_ERROR_BACKOFF_SECONDS)
        return None


async def get_quote_safe(client, code: str) -> dict[str, int] | None:
    try:
        payload = await client.get_current_price(code)
        await asyncio.sleep(QUOTE_DELAY_SECONDS)
        return parse_quote(payload)
    except Exception:
        await asyncio.sleep(QUOTE_ERROR_BACKOFF_SECONDS)
        return None


def passes_intraday_entry_filter(signal: dict, quote: dict[str, int]) -> tuple[bool, str]:
    raw = signal.get("raw") or {}
    current_price = quote["current_price"]
    day_high = quote.get("day_high") or current_price
    entry = float(signal["entry"])
    kijun = float(raw.get("Kijun") or 0)
    bb_upper = float(raw.get("BBUpper") or entry * 1.1)

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


async def insert_trade_log(
    user_id: str,
    broker_account_id: str | None,
    action: str,
    position_or_signal: dict,
    price: int,
    qty: int,
    reason: str,
    raw: dict | None = None,
) -> None:
    logged_at = now_kst().isoformat()
    payload_raw = {
        **(raw or {}),
        "reason_code": reason,
        "reason_ko": reason_label(reason),
        "logged_at": logged_at,
        "exit_plan": exit_plan_from_source(position_or_signal),
    }
    await SupabaseRest().insert(
        "trade_logs",
        {
            "user_id": user_id,
            "broker_account_id": broker_account_id,
            "action": action,
            "code": position_or_signal["code"],
            "name": position_or_signal.get("name"),
            "price": price,
            "qty": qty,
            "reason": reason_label(reason),
            "raw": payload_raw,
        },
    )


async def open_positions(user_id: str, broker_account_id: str | None) -> list[dict]:
    filters = {"user_id": f"eq.{user_id}", "status": "eq.OPEN"}
    if broker_account_id:
        filters["broker_account_id"] = f"eq.{broker_account_id}"
    return await SupabaseRest().select(
        "positions",
        filters=filters,
        order="created_at.asc",
    )


async def today_signals(user_id: str) -> list[dict]:
    return await SupabaseRest().select(
        "signals",
        filters={"user_id": f"eq.{user_id}", "trade_date": f"eq.{now_kst().date().isoformat()}"},
        order="score.desc",
    )


async def place_sell(client, position: dict, qty: int, price: int, *, reason: str, dry_run: bool) -> dict:
    if dry_run:
        return {"dry_run": True, "side": "sell", "code": position["code"], "qty": qty, "price": price, "reason": reason}
    return await client.sell_limit(position["code"], qty, price)


async def place_buy(client, signal: dict, qty: int, price: int, *, dry_run: bool) -> dict:
    if dry_run:
        return {"dry_run": True, "side": "buy", "code": signal["code"], "qty": qty, "price": price}
    return await client.buy_limit(signal["code"], qty, price)


async def manage_positions(user_id: str, broker_account_id: str | None, client, positions: list[dict], *, test_mode: bool, dry_run: bool) -> list[dict]:
    if not in_window(MANAGE_START, MANAGE_END, test_mode=test_mode):
        return []

    actions: list[dict] = []
    rest = SupabaseRest()
    for position in positions:
        current_price = await get_price_safe(client, position["code"])
        if current_price is None:
            continue

        remaining_qty = int(position.get("remaining_qty") or 0)
        if remaining_qty <= 0:
            await rest.patch("positions", filters={"id": f"eq.{position['id']}"}, payload={"status": "CLOSED", "remaining_qty": 0})
            continue

        stop_loss = float(position["stop_loss"])
        tp1 = float(position["take_profit_1"])
        tp2 = float(position["take_profit_2"])
        trailing_stop = float(position["trailing_stop"])
        hold_max_days = int((position.get("raw") or {}).get("HoldMaxDays", 15))
        held_days = days_held(position.get("entry_date"))
        reason: str | None = None
        sell_qty = 0
        patch: dict = {}

        if current_price <= stop_loss:
            reason = "StopLoss"
            sell_qty = remaining_qty
            patch = {"remaining_qty": 0, "status": "CLOSED"}
        elif current_price <= trailing_stop and (position.get("take_profit_1_done") or position.get("take_profit_2_done")):
            reason = "TrailingStop"
            sell_qty = remaining_qty
            patch = {"remaining_qty": 0, "status": "CLOSED"}
        elif held_days >= hold_max_days:
            reason = "TimeExit"
            sell_qty = remaining_qty
            patch = {"remaining_qty": 0, "status": "CLOSED"}
        elif not position.get("take_profit_1_done") and current_price >= tp1:
            reason = "TakeProfit1"
            sell_qty = min(max(1, int(int(position["qty"]) * 0.3)), remaining_qty)
            patch = {"remaining_qty": remaining_qty - sell_qty, "take_profit_1_done": True}
        elif not position.get("take_profit_2_done") and current_price >= tp2:
            reason = "TakeProfit2"
            sell_qty = min(max(1, int(int(position["qty"]) * 0.3)), remaining_qty)
            patch = {"remaining_qty": remaining_qty - sell_qty, "take_profit_2_done": True}

        if not reason or sell_qty <= 0:
            continue

        response = await place_sell(client, position, sell_qty, current_price, reason=reason, dry_run=dry_run)
        if patch.get("remaining_qty", remaining_qty) <= 0:
            patch["status"] = "CLOSED"
        await rest.patch("positions", filters={"id": f"eq.{position['id']}"}, payload=patch)
        await insert_trade_log(user_id, broker_account_id, "SELL", position, current_price, sell_qty, reason, {"order": response})
        actions.append({"action": "SELL", "code": position["code"], "qty": sell_qty, "price": current_price, "reason": reason_label(reason)})

    return actions


async def enter_positions(user_id: str, broker_account_id: str | None, client, positions: list[dict], balance: dict, *, test_mode: bool, dry_run: bool) -> list[dict]:
    if not in_window(ENTRY_START, ENTRY_END, test_mode=test_mode):
        return []

    signals = await today_signals(user_id)
    if not signals:
        return []

    cash = extract_cash(balance)
    total_equity = extract_total_equity(balance)
    kis_codes = kis_holding_codes(balance)
    open_codes = {position["code"] for position in positions}
    blocked_codes = open_codes | kis_codes
    available_slots = max(0, MAX_OPEN_POSITIONS - len(open_codes) - len(kis_codes))
    daily_slots = min(MAX_NEW_POSITIONS_PER_DAY, available_slots)
    if daily_slots <= 0:
        return []

    candidates = [
        signal
        for signal in signals
        if signal["code"] not in blocked_codes and float(signal.get("score") or 0) >= MIN_SCORE
    ]

    actions: list[dict] = []
    rest = SupabaseRest()
    for signal in candidates:
        if len(actions) >= daily_slots:
            break

        quote = await get_quote_safe(client, signal["code"])
        if quote is None or quote["current_price"] <= 0:
            continue
        current_price = quote["current_price"]
        raw = signal.get("raw") or {}
        passed, reason = passes_intraday_entry_filter(signal, quote)
        if not passed:
            continue

        sizing_signal = {**signal, "entry": current_price}
        qty, sizing = calculate_order_qty(
            sizing_signal,
            cash=cash,
            total_equity=max(total_equity, DEFAULT_CAPITAL),
            available_slots=daily_slots,
        )
        if qty <= 0:
            continue

        response = await place_buy(client, signal, qty, current_price, dry_run=dry_run)
        position_payload = {
            "user_id": user_id,
            "broker_account_id": broker_account_id,
            "code": signal["code"],
            "name": signal["name"],
            "entry_date": now_kst().date().isoformat(),
            "entry_price": current_price,
            "qty": qty,
            "remaining_qty": qty,
            "stop_loss": signal["stop_loss"],
            "take_profit_1": signal["take_profit_1"],
            "take_profit_2": signal["take_profit_2"],
            "trailing_stop": signal["trailing_stop"],
            "status": "OPEN",
            "take_profit_1_done": False,
            "take_profit_2_done": False,
            "raw": {**raw, "intraday_quote": quote, "kis_order_response": response, "sizing": sizing},
        }
        await rest.insert("positions", position_payload)
        await insert_trade_log(
            user_id,
            broker_account_id,
            "BUY",
            signal,
            current_price,
            qty,
            reason,
            {"quote": quote, "order": response, "signal_raw": raw},
        )
        actions.append({"action": "BUY", "code": signal["code"], "qty": qty, "price": current_price, "reason": reason_label(reason)})

    return actions


async def run_watch_tick_for_user(credentials: dict, *, test_mode: bool = False, dry_run: bool = False) -> dict:
    user_id = credentials["user_id"]
    broker_account_id = credentials.get("id")
    settings = get_settings()
    is_live = (credentials.get("mode") or "paper") == "live"
    allow_live_orders = bool(credentials.get("live_order_enabled")) and settings.allow_live_trading
    client = client_from_credentials(credentials, enable_orders=not dry_run, allow_live_orders=allow_live_orders)
    positions = await open_positions(user_id, broker_account_id)
    actions: list[dict] = []
    actions.extend(await manage_positions(user_id, broker_account_id, client, positions, test_mode=test_mode, dry_run=dry_run))
    balance = await client.get_balance()
    positions = await open_positions(user_id, broker_account_id)
    actions.extend(await enter_positions(user_id, broker_account_id, client, positions, balance, test_mode=test_mode, dry_run=dry_run))

    if actions:
        lines = [f"KOSPI bot actions: {len(actions)}"]
        lines.extend(f"{item['action']} {item['code']} qty {item['qty']} @ {item['price']:,} {item['reason']}" for item in actions)
        await send_telegram_message(credentials.get("telegram_chat_id"), "\n".join(lines))

    return {
        "user_id": user_id,
        "broker_account_id": broker_account_id,
        "actions": actions,
        "action_count": len(actions),
        "mode": credentials.get("mode") or "paper",
        "live_order_enabled": bool(credentials.get("live_order_enabled")),
        "server_live_trading_allowed": settings.allow_live_trading,
        "orders_allowed": not dry_run and (not is_live or allow_live_orders),
    }
