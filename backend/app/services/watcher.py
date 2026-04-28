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


ENTRY_START = time(9, 20)
ENTRY_END = time(10, 30)
MANAGE_START = time(9, 20)
MANAGE_END = time(15, 10)
QUOTE_DELAY_SECONDS = 1.0
QUOTE_ERROR_BACKOFF_SECONDS = 3.0
MAX_ENTRY_PREMIUM = 1.02
MIN_ENTRY_DISCOUNT = 0.995
MAX_PULLBACK_FROM_DAY_HIGH = 0.03


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


async def insert_trade_log(user_id: str, action: str, position_or_signal: dict, price: int, qty: int, reason: str, raw: dict | None = None) -> None:
    await SupabaseRest().insert(
        "trade_logs",
        {
            "user_id": user_id,
            "action": action,
            "code": position_or_signal["code"],
            "name": position_or_signal.get("name"),
            "price": price,
            "qty": qty,
            "reason": reason,
            "raw": raw or {},
        },
    )


async def open_positions(user_id: str) -> list[dict]:
    return await SupabaseRest().select(
        "positions",
        filters={"user_id": f"eq.{user_id}", "status": "eq.OPEN"},
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


async def manage_positions(user_id: str, client, positions: list[dict], *, test_mode: bool, dry_run: bool) -> list[dict]:
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
        await insert_trade_log(user_id, "SELL", position, current_price, sell_qty, reason, response)
        actions.append({"action": "SELL", "code": position["code"], "qty": sell_qty, "price": current_price, "reason": reason})

    return actions


async def enter_positions(user_id: str, client, positions: list[dict], balance: dict, *, test_mode: bool, dry_run: bool) -> list[dict]:
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
        await insert_trade_log(user_id, "BUY", signal, current_price, qty, reason, {"quote": quote, "order": response})
        actions.append({"action": "BUY", "code": signal["code"], "qty": qty, "price": current_price, "reason": reason})

    return actions


async def run_watch_tick_for_user(credentials: dict, *, test_mode: bool = False, dry_run: bool = False) -> dict:
    user_id = credentials["user_id"]
    client = client_from_credentials(credentials, enable_orders=not dry_run)
    positions = await open_positions(user_id)
    actions: list[dict] = []
    actions.extend(await manage_positions(user_id, client, positions, test_mode=test_mode, dry_run=dry_run))
    balance = await client.get_balance()
    positions = await open_positions(user_id)
    actions.extend(await enter_positions(user_id, client, positions, balance, test_mode=test_mode, dry_run=dry_run))

    if actions and credentials.get("telegram_chat_id"):
        lines = [f"KOSPI bot actions: {len(actions)}"]
        lines.extend(f"{item['action']} {item['code']} qty {item['qty']} @ {item['price']:,} {item['reason']}" for item in actions)
        await send_telegram_message(credentials["telegram_chat_id"], "\n".join(lines))

    return {"user_id": user_id, "actions": actions, "action_count": len(actions)}
