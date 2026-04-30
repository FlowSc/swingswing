from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.services.kis import (
    client_from_credentials,
    extract_cash,
    extract_total_equity,
    kis_holding_codes,
    parse_holdings,
    parse_current_price,
    parse_order_identifiers,
    parse_quote,
)
from app.services.sizing import (
    DEFAULT_CAPITAL,
    calculate_order_qty,
)
from app.services.strategy_settings import get_strategy_settings
from app.services.supabase_rest import SupabaseRest
from app.services.telegram import send_telegram_message_with_bot


logger = logging.getLogger(__name__)
ENTRY_START = time(14, 30)
ENTRY_END = time(15, 20)
MANAGE_START = time(9, 20)
MANAGE_END = time(15, 20)
QUOTE_DELAY_SECONDS = 1.0
QUOTE_ERROR_BACKOFF_SECONDS = 3.0
OPEN_PENDING_STATUSES = {"OPEN", "CANCEL_FAILED"}
REASON_LABELS = {
    "IntradayEntry": "장중 진입 조건 충족",
    "StopLoss": "손절가 도달",
    "TrailingStop": "추적 손절가 도달",
    "TimeExit": "최대 보유기간 도달",
    "TakeProfit1": "1차 익절가 도달",
    "TakeProfit2": "2차 익절가 도달",
    "BreakEvenStop": "1차 익절 후 본전 손절",
    "KijunExit": "일목 기준선 이탈",
    "AlreadyHeld": "이미 보유 중인 종목",
    "ScoreBelowMinimum": "전략 최소 점수 미달",
    "BelowEntryBand": "현재가가 진입 허용 하단보다 낮음",
    "AboveEntryBand": "현재가가 진입 허용 상단보다 높음",
    "BelowKijun": "현재가가 일목 기준선 아래",
    "AboveBBUpper": "현재가가 볼린저 상단 위",
    "PulledBackFromDayHigh": "당일 고점 대비 과도하게 밀림",
    "PendingOrderExists": "미체결 주문 대기 중",
    "OrderPending": "주문 접수 후 체결 대기",
    "OrderFilled": "계좌 잔고 기준 체결 확인",
    "OrderCanceled": "장마감 전 미체결 주문 취소",
    "OrderCancelFailed": "미체결 주문 취소 실패",
    "PositionSynced": "계좌 잔고 기준 포지션 수량 동기화",
    "PositionClosedByBalance": "계좌 잔고 기준 포지션 종료",
    "QuoteFailed": "현재가 조회 실패",
    "InvalidQuote": "현재가 값 비정상",
    "SizingRejected": "수량/리스크/최소주문금액 조건 미충족",
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


def passes_intraday_entry_filter(signal: dict, quote: dict[str, int], strategy: dict) -> tuple[bool, str]:
    raw = signal.get("raw") or {}
    current_price = quote["current_price"]
    day_high = quote.get("day_high") or current_price
    entry = float(signal["entry"])
    kijun = float(raw.get("Kijun") or 0)
    bb_upper = float(raw.get("BBUpper") or entry * 1.1)

    if current_price < entry * float(strategy["min_entry_discount"]):
        return False, "BelowEntryBand"
    if current_price > entry * float(strategy["max_entry_premium"]):
        return False, "AboveEntryBand"
    if strategy.get("use_kijun_filter", True) and kijun > 0 and current_price < kijun:
        return False, "BelowKijun"
    if strategy.get("use_bb_upper_filter", True) and current_price > bb_upper:
        return False, "AboveBBUpper"
    if strategy.get("use_day_candle_filter", False) and day_high > 0 and current_price < day_high * (1 - float(strategy["max_pullback_from_day_high"])):
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


async def insert_decision_log(
    user_id: str,
    broker_account_id: str | None,
    decision: str,
    signal: dict,
    reason: str,
    *,
    price: int | None = None,
    raw: dict | None = None,
) -> None:
    today = now_kst().date().isoformat()
    try:
        await SupabaseRest().upsert(
            "trade_decision_logs",
            {
                "decision_date": today,
                "user_id": user_id,
                "broker_account_id": broker_account_id,
                "decision": decision,
                "code": signal["code"],
                "name": signal.get("name"),
                "price": price,
                "score": signal.get("score"),
                "reason_code": reason,
                "reason": reason_label(reason),
                "raw": {
                    **(raw or {}),
                    "reason_code": reason,
                    "reason_ko": reason_label(reason),
                    "logged_at": now_kst().isoformat(),
                },
            },
            on_conflict="decision_date,user_id,broker_account_id,code,reason_code",
        )
    except RuntimeError as exc:
        logger.warning("Failed to insert trade decision log: code=%s reason=%s error=%s", signal.get("code"), reason, exc)


async def open_positions(user_id: str, broker_account_id: str | None) -> list[dict]:
    filters = {"user_id": f"eq.{user_id}", "status": "eq.OPEN"}
    if broker_account_id:
        filters["broker_account_id"] = f"eq.{broker_account_id}"
    return await SupabaseRest().select(
        "positions",
        filters=filters,
        order="created_at.asc",
    )


async def today_signals() -> list[dict]:
    return await SupabaseRest().select(
        "shared_signals",
        filters={"trade_date": f"eq.{now_kst().date().isoformat()}"},
        order="score.desc",
    )


async def open_pending_orders(user_id: str, broker_account_id: str | None) -> list[dict]:
    filters = {"user_id": f"eq.{user_id}"}
    if broker_account_id:
        filters["broker_account_id"] = f"eq.{broker_account_id}"
    orders = await SupabaseRest().select("pending_orders", filters=filters, order="created_at.asc")
    return [order for order in orders if order.get("status") in OPEN_PENDING_STATUSES]


async def insert_pending_order(
    user_id: str,
    broker_account_id: str | None,
    *,
    side: str,
    source: dict,
    qty: int,
    price: int,
    response: dict,
    reason: str,
    raw: dict | None = None,
) -> None:
    identifiers = parse_order_identifiers(response)
    await SupabaseRest().insert(
        "pending_orders",
        {
            "user_id": user_id,
            "broker_account_id": broker_account_id,
            "side": side,
            "code": source["code"],
            "name": source.get("name"),
            "qty": qty,
            "price": price,
            "order_no": identifiers.get("order_no"),
            "order_org_no": identifiers.get("order_org_no"),
            "status": "OPEN",
            "reason": reason_label(reason),
            "raw": {
                **(raw or {}),
                "reason_code": reason,
                "reason_ko": reason_label(reason),
                "order": response,
                "order_identifiers": identifiers,
            },
        },
    )


async def mark_pending_order(order_id: int, status: str, raw: dict | None = None) -> None:
    payload = {"status": status, "updated_at": now_kst().isoformat()}
    if raw is not None:
        payload["raw"] = raw
    await SupabaseRest().patch("pending_orders", filters={"id": f"eq.{order_id}"}, payload=payload)


async def sync_positions_with_balance(user_id: str, broker_account_id: str | None, positions: list[dict], balance: dict) -> list[dict]:
    holdings = parse_holdings(balance)
    actions: list[dict] = []
    rest = SupabaseRest()
    for position in positions:
        code = position["code"]
        holding = holdings.get(code)
        expected_qty = int(position.get("remaining_qty") or 0)
        actual_qty = int((holding or {}).get("qty") or 0)
        if actual_qty == expected_qty:
            continue

        patch = {"remaining_qty": actual_qty, "updated_at": now_kst().isoformat()}
        if actual_qty <= 0:
            patch["status"] = "CLOSED"
        await rest.patch("positions", filters={"id": f"eq.{position['id']}"}, payload=patch)

        reason = "PositionClosedByBalance" if actual_qty <= 0 else "PositionSynced"
        await insert_trade_log(
            user_id,
            broker_account_id,
            "SYNC",
            position,
            int((holding or {}).get("current_price") or position.get("entry_price") or 0),
            actual_qty,
            reason,
            {"holding": holding, "previous_remaining_qty": expected_qty, "patch": patch},
        )
        actions.append({"action": "SYNC", "code": code, "qty": actual_qty, "price": int((holding or {}).get("current_price") or 0), "reason": reason_label(reason)})
    return actions


async def reconcile_pending_orders(
    user_id: str,
    broker_account_id: str | None,
    client,
    balance: dict,
    *,
    test_mode: bool,
    dry_run: bool,
) -> list[dict]:
    pending_orders = await open_pending_orders(user_id, broker_account_id)
    if not pending_orders:
        return []

    holdings = parse_holdings(balance)
    positions = await open_positions(user_id, broker_account_id)
    open_codes = {position["code"] for position in positions}
    actions: list[dict] = []
    rest = SupabaseRest()
    should_cancel = not test_mode and now_kst().time() >= ENTRY_END

    for order in pending_orders:
        raw = order.get("raw") or {}
        code = order["code"]
        side = order["side"]
        holding = holdings.get(code)
        previous_qty = int((raw.get("previous_remaining_qty") if isinstance(raw, dict) else 0) or 0)
        is_filled = (side == "BUY" and holding and int(holding.get("qty") or 0) > 0) or (
            side == "SELL" and (not holding or (previous_qty > 0 and int(holding.get("qty") or 0) < previous_qty))
        )

        if is_filled:
            raw = {**raw, "filled_at": now_kst().isoformat(), "holding": holding}
            await mark_pending_order(int(order["id"]), "FILLED", raw)
            if side == "BUY" and code not in open_codes:
                expected = raw.get("expected_position") or {}
                signal = raw.get("signal") or {}
                qty = int((holding or {}).get("qty") or order.get("qty") or 0)
                entry_price = int((holding or {}).get("avg_price") or order.get("price") or 0)
                await rest.insert(
                    "positions",
                    {
                        **expected,
                        "entry_price": entry_price,
                        "qty": qty,
                        "remaining_qty": qty,
                        "raw": {
                            **(expected.get("raw") or {}),
                            "filled_by_balance": True,
                            "holding": holding,
                            "pending_order_id": order["id"],
                        },
                    },
                )
                await insert_trade_log(user_id, broker_account_id, "BUY", signal or order, entry_price, qty, "OrderFilled", raw)
                open_codes.add(code)
            actions.append({"action": "FILL", "code": code, "qty": int(order.get("qty") or 0), "price": int(order.get("price") or 0), "reason": reason_label("OrderFilled")})
            continue

        if not should_cancel:
            continue

        try:
            if dry_run:
                cancel_response = {"dry_run": True, "order_no": order.get("order_no")}
            else:
                cancel_response = await client.cancel_order(
                    order_org_no=order.get("order_org_no") or "",
                    order_no=order.get("order_no") or "",
                    qty=int(order.get("qty") or 0),
                    price=int(float(order.get("price") or 0)),
                )
            raw = {**raw, "cancel_response": cancel_response, "canceled_at": now_kst().isoformat()}
            await mark_pending_order(int(order["id"]), "CANCELED", raw)
            await insert_trade_log(user_id, broker_account_id, side, order, int(float(order.get("price") or 0)), int(order.get("qty") or 0), "OrderCanceled", raw)
            actions.append({"action": "CANCEL", "code": code, "qty": int(order.get("qty") or 0), "price": int(float(order.get("price") or 0)), "reason": reason_label("OrderCanceled")})
        except Exception as exc:
            raw = {**raw, "cancel_error": str(exc), "cancel_failed_at": now_kst().isoformat()}
            await mark_pending_order(int(order["id"]), "CANCEL_FAILED", raw)
            await insert_trade_log(user_id, broker_account_id, side, order, int(float(order.get("price") or 0)), int(order.get("qty") or 0), "OrderCancelFailed", raw)
            actions.append({"action": "CANCEL_FAILED", "code": code, "qty": int(order.get("qty") or 0), "price": int(float(order.get("price") or 0)), "reason": reason_label("OrderCancelFailed")})

    return actions


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
    strategy = await get_strategy_settings(user_id)
    pending_sells = {order["code"] for order in await open_pending_orders(user_id, broker_account_id) if order.get("side") == "SELL"}
    for position in positions:
        if position["code"] in pending_sells:
            continue

        current_price = await get_price_safe(client, position["code"])
        if current_price is None:
            continue

        remaining_qty = int(position.get("remaining_qty") or 0)
        if remaining_qty <= 0:
            await rest.patch("positions", filters={"id": f"eq.{position['id']}"}, payload={"status": "CLOSED", "remaining_qty": 0})
            continue

        stop_loss = float(position["stop_loss"])
        entry_price = float(position["entry_price"])
        tp1 = float(position["take_profit_1"])
        tp2 = float(position["take_profit_2"])
        trailing_stop = float(position["trailing_stop"])
        raw = position.get("raw") or {}
        hold_max_days = int(raw.get("HoldMaxDays", 15))
        kijun = float(raw.get("Kijun") or 0)
        held_days = days_held(position.get("entry_date"))
        reason: str | None = None
        sell_qty = 0
        patch: dict = {}

        if current_price <= stop_loss:
            reason = "StopLoss"
            sell_qty = remaining_qty
            patch = {"remaining_qty": 0, "status": "CLOSED"}
        elif strategy.get("use_breakeven_after_tp1", False) and position.get("take_profit_1_done") and current_price <= entry_price:
            reason = "BreakEvenStop"
            sell_qty = remaining_qty
            patch = {"remaining_qty": 0, "status": "CLOSED"}
        elif strategy.get("use_kijun_exit", False) and kijun > 0 and current_price < kijun:
            reason = "KijunExit"
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
            if strategy.get("use_breakeven_after_tp1", False):
                patch["stop_loss"] = max(stop_loss, entry_price)
        elif not position.get("take_profit_2_done") and current_price >= tp2:
            reason = "TakeProfit2"
            sell_qty = min(max(1, int(int(position["qty"]) * 0.3)), remaining_qty)
            patch = {"remaining_qty": remaining_qty - sell_qty, "take_profit_2_done": True}

        if not reason or sell_qty <= 0:
            continue

        response = await place_sell(client, position, sell_qty, current_price, reason=reason, dry_run=dry_run)
        if patch.get("remaining_qty", remaining_qty) <= 0:
            patch["status"] = "CLOSED"
        if dry_run:
            await rest.patch("positions", filters={"id": f"eq.{position['id']}"}, payload=patch)
            await insert_trade_log(user_id, broker_account_id, "SELL", position, current_price, sell_qty, reason, {"order": response, "strategy": strategy, "patch": patch})
            actions.append({"action": "SELL", "code": position["code"], "qty": sell_qty, "price": current_price, "reason": reason_label(reason)})
        else:
            await insert_pending_order(
                user_id,
                broker_account_id,
                side="SELL",
                source=position,
                qty=sell_qty,
                price=current_price,
                response=response,
                reason=reason,
                raw={"position": position, "patch": patch, "strategy": strategy, "previous_remaining_qty": remaining_qty},
            )
            await insert_trade_log(user_id, broker_account_id, "SELL", position, current_price, sell_qty, "OrderPending", {"order": response, "strategy": strategy, "exit_reason": reason, "patch": patch})
            actions.append({"action": "SELL_ORDER", "code": position["code"], "qty": sell_qty, "price": current_price, "reason": f"{reason_label(reason)} 주문 접수"})

    return actions


async def enter_positions(user_id: str, broker_account_id: str | None, client, positions: list[dict], balance: dict, *, test_mode: bool, dry_run: bool) -> list[dict]:
    if not in_window(ENTRY_START, ENTRY_END, test_mode=test_mode):
        return []

    signals = await today_signals()
    if not signals:
        return []

    cash = extract_cash(balance)
    total_equity = extract_total_equity(balance)
    strategy = await get_strategy_settings(user_id)
    kis_codes = kis_holding_codes(balance)
    open_codes = {position["code"] for position in positions}
    pending_orders = await open_pending_orders(user_id, broker_account_id)
    pending_codes = {order["code"] for order in pending_orders}
    pending_buy_count = len([order for order in pending_orders if order.get("side") == "BUY"])
    blocked_codes = open_codes | kis_codes | pending_codes
    available_slots = max(0, int(strategy["max_open_positions"]) - len(open_codes) - len(kis_codes) - pending_buy_count)
    daily_slots = min(int(strategy["max_new_positions_per_day"]), available_slots)
    if daily_slots <= 0:
        return []

    actions: list[dict] = []
    rest = SupabaseRest()
    for signal in signals:
        if len(actions) >= daily_slots:
            break

        score = float(signal.get("score") or 0)
        if signal["code"] in blocked_codes:
            reason = "PendingOrderExists" if signal["code"] in pending_codes else "AlreadyHeld"
            await insert_decision_log(user_id, broker_account_id, "SKIP", signal, reason, raw={"strategy": strategy})
            continue
        if score < float(strategy["min_score"]):
            await insert_decision_log(user_id, broker_account_id, "SKIP", signal, "ScoreBelowMinimum", raw={"strategy": strategy})
            continue

        quote = await get_quote_safe(client, signal["code"])
        if quote is None:
            await insert_decision_log(user_id, broker_account_id, "SKIP", signal, "QuoteFailed", raw={"strategy": strategy})
            continue
        if quote["current_price"] <= 0:
            await insert_decision_log(user_id, broker_account_id, "SKIP", signal, "InvalidQuote", raw={"quote": quote, "strategy": strategy})
            continue
        current_price = quote["current_price"]
        raw = signal.get("raw") or {}
        passed, reason = passes_intraday_entry_filter(signal, quote, strategy)
        if not passed:
            await insert_decision_log(user_id, broker_account_id, "SKIP", signal, reason, price=current_price, raw={"quote": quote, "strategy": strategy})
            continue

        sizing_signal = {**signal, "entry": current_price}
        qty, sizing = calculate_order_qty(
            sizing_signal,
            cash=cash,
            total_equity=max(total_equity, DEFAULT_CAPITAL),
            available_slots=daily_slots,
            position_capital_pct=float(strategy["position_capital_pct"]),
            risk_per_trade_pct=float(strategy["risk_per_trade_pct"]),
            min_order_amount=int(strategy["min_order_amount"]),
        )
        if qty <= 0:
            await insert_decision_log(user_id, broker_account_id, "SKIP", signal, "SizingRejected", price=current_price, raw={"quote": quote, "sizing": sizing, "strategy": strategy})
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
        if dry_run:
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
        else:
            await insert_pending_order(
                user_id,
                broker_account_id,
                side="BUY",
                source=signal,
                qty=qty,
                price=current_price,
                response=response,
                reason=reason,
                raw={"signal": signal, "quote": quote, "signal_raw": raw, "sizing": sizing, "expected_position": position_payload},
            )
            await insert_trade_log(
                user_id,
                broker_account_id,
                "BUY",
                signal,
                current_price,
                qty,
                "OrderPending",
                {"quote": quote, "order": response, "signal_raw": raw, "entry_reason": reason},
            )
            actions.append({"action": "BUY_ORDER", "code": signal["code"], "qty": qty, "price": current_price, "reason": reason_label("OrderPending")})
        blocked_codes.add(signal["code"])

    return actions


async def run_watch_tick_for_user(credentials: dict, *, test_mode: bool = False, dry_run: bool = False) -> dict:
    user_id = credentials["user_id"]
    broker_account_id = credentials.get("id")
    settings = get_settings()
    is_live = (credentials.get("mode") or "paper") == "live"
    allow_live_orders = bool(credentials.get("live_order_enabled")) and settings.allow_live_trading
    client = client_from_credentials(credentials, enable_orders=not dry_run, allow_live_orders=allow_live_orders)
    actions: list[dict] = []
    balance = await client.get_balance()

    actions.extend(await reconcile_pending_orders(user_id, broker_account_id, client, balance, test_mode=test_mode, dry_run=dry_run))
    positions = await open_positions(user_id, broker_account_id)
    actions.extend(await sync_positions_with_balance(user_id, broker_account_id, positions, balance))
    positions = await open_positions(user_id, broker_account_id)
    actions.extend(await manage_positions(user_id, broker_account_id, client, positions, test_mode=test_mode, dry_run=dry_run))
    balance = await client.get_balance()
    actions.extend(await reconcile_pending_orders(user_id, broker_account_id, client, balance, test_mode=test_mode, dry_run=dry_run))
    positions = await open_positions(user_id, broker_account_id)
    actions.extend(await sync_positions_with_balance(user_id, broker_account_id, positions, balance))
    positions = await open_positions(user_id, broker_account_id)
    actions.extend(await enter_positions(user_id, broker_account_id, client, positions, balance, test_mode=test_mode, dry_run=dry_run))

    if actions:
        lines = [f"KOSPI bot actions: {len(actions)}"]
        lines.extend(f"{item['action']} {item['code']} qty {item['qty']} @ {item['price']:,} {item['reason']}" for item in actions)
        await send_telegram_message_with_bot(credentials.get("telegram_bot_token"), credentials.get("telegram_chat_id"), "\n".join(lines))

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
