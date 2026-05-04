from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import FinanceDataReader as fdr

from app.core.config import get_settings
from app.services.kis import (
    client_from_credentials,
    extract_cash,
    extract_total_equity,
    extract_unrealized_pnl,
    kis_holding_codes,
    find_order_execution,
    parse_holdings,
    parse_current_price,
    parse_order_identifiers,
    parse_quote,
)
from app.services.sizing import (
    DEFAULT_CAPITAL,
    calculate_order_qty,
)
from app.services.realtime_risk import check_realtime_entry_risk, collect_realtime_prices
from app.services.strategy_settings import get_strategy_settings
from app.services.supabase_rest import SupabaseRest
from app.services.telegram import send_telegram_message_with_bot


logger = logging.getLogger(__name__)
ENTRY_START = time(14, 30)
ENTRY_END = time(15, 20)
MANAGE_START = time(9, 0)
MANAGE_END = time(15, 20)
QUOTE_DELAY_SECONDS = 1.0
QUOTE_ERROR_BACKOFF_SECONDS = 3.0
OPEN_PENDING_STATUSES = {"OPEN", "PARTIAL", "CANCEL_FAILED"}
STRATEGY_SELL_COOLDOWN_MINUTES = 30
STOP_LOSS_AGGRESSIVE_TICKS = 3
STOP_LOSS_REORDER_EXTRA_TICKS = 2
STOP_LOSS_REORDER_MAX_ATTEMPTS = 3
BUY_ORDER_CASH_BUFFER = 0.995
REASON_LABELS = {
    "IntradayEntry": "장중 진입 조건 충족",
    "StopLoss": "손절가 도달",
    "StopLossRepriced": "손절 미체결 재주문",
    "StopLossMarketExit": "손절 최종 시장가 탈출",
    "TrailingStop": "추적 손절가 도달",
    "TimeExit": "최대 보유기간 도달",
    "TakeProfit1": "1차 익절가 도달",
    "TakeProfit2": "2차 익절가 도달",
    "BreakEvenStop": "1차 익절 후 본전 손절",
    "KijunExit": "일목 기준선 이탈",
    "KijunExitedToday": "당일 기준선 이탈 매도 종목 재진입 금지",
    "AlreadyHeld": "이미 보유 중인 종목",
    "ScoreBelowMinimum": "전략 최소 점수 미달",
    "BelowEntryBand": "현재가가 진입 허용 하단보다 낮음",
    "AboveEntryBand": "현재가가 진입 허용 상단보다 높음",
    "BelowKijun": "현재가가 일목 기준선 아래",
    "AboveBBUpper": "현재가가 볼린저 상단 위",
    "PulledBackFromDayHigh": "당일 고점 대비 과도하게 밀림",
    "StoppedOutToday": "당일 손절 종목 재매수 금지",
    "VolatilityInterruption": "VI 발동 종목 매수 차단",
    "PendingOrderExists": "미체결 주문 대기 중",
    "OrderPending": "주문 접수 후 체결 대기",
    "OrderFilled": "주문/계좌 기준 체결 확인",
    "OrderCanceled": "장마감 전 미체결 주문 취소",
    "OrderCancelFailed": "미체결 주문 취소 실패",
    "PartialFillUpdated": "부분체결 추가 반영",
    "PositionSynced": "계좌 잔고 기준 포지션 수량 동기화",
    "PositionClosedByBalance": "계좌 잔고 기준 포지션 종료",
    "QuoteFailed": "현재가 조회 실패",
    "InvalidQuote": "현재가 값 비정상",
    "SizingRejected": "수량/리스크/최소주문금액 조건 미충족",
    "SizingRiskBudgetTooSmall": "리스크 1회 허용손실이 너무 작음",
    "SizingCapitalTooSmall": "현금/종목당 배정금액이 부족함",
    "SizingBelowMinOrder": "계산된 주문금액이 최소 주문금액보다 작음",
    "SizingInvalidPrice": "진입가 또는 손절가가 비정상",
    "OrderableCashExceeded": "주문가능금액 초과",
    "StrategySellCooldown": "매수 직후 전략 매도 쿨다운",
    "DailyLossLimit": "하루 손실 한도 도달",
    "UnrealizedLossLimit": "미실현손실 한도 도달",
    "MarketCrashFilter": "시장 급락 신규 매수 차단",
    "RealtimeStrengthWeak": "실시간 체결강도 약함",
    "RealtimeBidDepthWeak": "실시간 매수 호가잔량 약함",
    "RealtimeSpreadWide": "실시간 호가 스프레드 과다",
    "RealtimeCheckFailed": "실시간 체결/호가 확인 실패",
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


def parse_kst_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.replace(" ", "T")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=ZoneInfo(get_settings().timezone))
    return parsed.astimezone(ZoneInfo(get_settings().timezone))


def in_strategy_sell_cooldown(position: dict) -> bool:
    created_at = parse_kst_datetime(str(position.get("created_at") or ""))
    if not created_at:
        return False
    return now_kst() - created_at < timedelta(minutes=STRATEGY_SELL_COOLDOWN_MINUTES)


def reason_label(reason_code: str) -> str:
    return REASON_LABELS.get(reason_code, reason_code)


def sizing_reject_reason_code(sizing: dict) -> str:
    reason = sizing.get("reject_reason")
    if reason == "risk_budget_too_small":
        return "SizingRiskBudgetTooSmall"
    if reason == "cash_or_position_capital_too_small":
        return "SizingCapitalTooSmall"
    if reason == "below_min_order_amount":
        return "SizingBelowMinOrder"
    if reason == "invalid_price_or_stop":
        return "SizingInvalidPrice"
    return "SizingRejected"


def sizing_reject_detail(sizing: dict) -> str:
    reason = sizing.get("reject_reason")
    price = int(float(sizing.get("price") or 0))
    per_share_risk = int(float(sizing.get("per_share_risk") or 0))
    max_risk = int(float(sizing.get("max_risk_capital") or 0))
    usable = int(float(sizing.get("usable_capital") or 0))
    qty_by_risk = int(float(sizing.get("qty_by_risk") or 0))
    qty_by_capital = int(float(sizing.get("qty_by_capital") or 0))
    candidate_amount = int(float(sizing.get("candidate_order_amount") or 0))
    min_order = int(float(sizing.get("min_order_amount") or 0))
    risk_pct = float(sizing.get("risk_per_trade_pct") or 0) * 100
    position_pct = float(sizing.get("position_capital_pct") or 0) * 100

    if reason == "risk_budget_too_small":
        return f"1회 리스크 허용손실 {max_risk:,}원이 주당 손실위험 {per_share_risk:,}원보다 작아 1주도 살 수 없습니다. 현재 리스크 설정은 {risk_pct:.2f}%입니다."
    if reason == "cash_or_position_capital_too_small":
        cash = int(float(sizing.get("cash") or 0))
        max_position = int(float(sizing.get("max_position_capital") or 0))
        return f"주문 기준가 {price:,}원 대비 봇이 확인한 주문가능현금 {cash:,}원, 종목당 배정한도 {max_position:,}원, 실제 사용 가능 배정금액 {usable:,}원이라 1주도 살 수 없습니다. 프론트 예수금과 다르면 KIS 주문가능현금 또는 미체결 주문을 확인해야 합니다."
    if reason == "below_min_order_amount":
        return f"리스크/현금 기준 계산 수량이 리스크 {qty_by_risk}주, 자금 {qty_by_capital}주라 주문금액 {candidate_amount:,}원에 그칩니다. 최소 주문금액 {min_order:,}원보다 작습니다."
    if reason == "invalid_price_or_stop":
        return f"진입가 {price:,}원 또는 주당 손실위험 {per_share_risk:,}원이 비정상이라 수량 계산을 중단했습니다."
    return f"주문 기준가 {price:,}원, 주당 손실위험 {per_share_risk:,}원, 리스크 가능수량 {qty_by_risk}주, 자금 가능수량 {qty_by_capital}주 기준으로 매수 수량이 나오지 않았습니다."


def decision_reason_detail(reason: str, signal: dict, *, price: int | None = None, raw: dict | None = None) -> str:
    raw = raw or {}
    quote = raw.get("quote") if isinstance(raw.get("quote"), dict) else {}
    strategy = raw.get("strategy") if isinstance(raw.get("strategy"), dict) else {}
    sizing = raw.get("sizing") if isinstance(raw.get("sizing"), dict) else {}
    realtime = raw.get("realtime") if isinstance(raw.get("realtime"), dict) else {}
    current_price = int(price or quote.get("current_price") or 0)
    entry = int(float(signal.get("entry") or 0))

    if raw.get("sizing_detail"):
        return str(raw["sizing_detail"])
    if reason == "ScoreBelowMinimum":
        return f"시그널 점수 {float(signal.get('score') or 0):.2f}점이 전략 최소 점수 {float(strategy.get('min_score') or 0):.2f}점보다 낮아서 제외했습니다."
    if reason == "BelowEntryBand":
        threshold = int(entry * float(strategy.get("min_entry_discount") or 0))
        return f"현재가 {current_price:,}원이 진입가 {entry:,}원 × 하단 허용배율 {float(strategy.get('min_entry_discount') or 0):.3f} = {threshold:,}원보다 낮아서 제외했습니다."
    if reason == "AboveEntryBand":
        threshold = int(entry * float(strategy.get("max_entry_premium") or 0))
        return f"현재가 {current_price:,}원이 진입가 {entry:,}원 × 상단 허용배율 {float(strategy.get('max_entry_premium') or 0):.3f} = {threshold:,}원보다 높아서 제외했습니다."
    if reason == "BelowKijun":
        kijun = int(float((signal.get("raw") or {}).get("Kijun") or 0))
        return f"현재가 {current_price:,}원이 일목 기준선 {kijun:,}원보다 낮아서 제외했습니다."
    if reason == "AboveBBUpper":
        bb_upper = int(float((signal.get("raw") or {}).get("BBUpper") or 0))
        return f"현재가 {current_price:,}원이 볼린저 상단 {bb_upper:,}원보다 높아서 제외했습니다."
    if reason == "PulledBackFromDayHigh":
        day_high = int(quote.get("day_high") or 0)
        limit_pct = float(strategy.get("max_pullback_from_day_high") or 0)
        threshold = int(day_high * (1 - limit_pct))
        return f"당일 고점 {day_high:,}원에서 허용 하락폭 {limit_pct * 100:.2f}% 기준선은 {threshold:,}원인데, 현재가가 {current_price:,}원이라 제외했습니다."
    if reason == "OrderableCashExceeded":
        cash = int(float(raw.get("cash") or sizing.get("cash") or 0))
        order_price = int(float(raw.get("order_price") or sizing.get("price") or current_price or 0))
        qty = int(float(raw.get("qty") or sizing.get("original_qty") or sizing.get("candidate_qty") or 0))
        max_qty = int(float(raw.get("max_orderable_qty") or 0))
        attempted_amount = qty * order_price
        max_amount = max_qty * order_price
        return f"KIS 주문가능현금 {cash:,}원 기준 최대 {max_qty}주({max_amount:,}원)까지 가능한데, 주문 시도 수량 {qty}주({attempted_amount:,}원)가 더 커서 제외했습니다."
    if reason.startswith("Realtime"):
        return f"실시간 필터 결과 체결강도 {realtime.get('strength', '-')}, 매수/매도 호가잔량 비율 {realtime.get('bid_ask_ratio', '-')}, 스프레드 {realtime.get('spread_pct', '-')} 기준으로 제외했습니다."
    if reason == "AlreadyHeld":
        return "DB 포지션 또는 KIS 잔고에 이미 보유 중인 종목이라 중복 매수를 막았습니다."
    if reason == "PendingOrderExists":
        return "동일 종목의 미체결 주문이 남아 있어 추가 주문을 막았습니다."
    if reason == "StoppedOutToday":
        return "오늘 손절로 매도된 종목이라 당일 재매수를 막았습니다."
    if reason == "KijunExitedToday":
        return "오늘 일목 기준선 이탈로 매도된 종목이라 당일 재진입을 막았습니다."
    if reason == "QuoteFailed":
        return "KIS 현재가 조회가 실패해 주문 가격과 리스크를 계산할 수 없어 제외했습니다."
    if reason == "InvalidQuote":
        return f"KIS 현재가 값이 {current_price:,}원으로 비정상이라 제외했습니다."
    if reason == "VolatilityInterruption":
        return "KIS 현재가 응답에서 VI 발동 상태로 확인되어 신규 매수를 막았습니다."
    return reason_label(reason)


def realtime_reason_code(reason: str) -> str:
    return {
        "realtime_strength_weak": "RealtimeStrengthWeak",
        "realtime_bid_depth_weak": "RealtimeBidDepthWeak",
        "realtime_spread_wide": "RealtimeSpreadWide",
        "realtime_check_failed": "RealtimeCheckFailed",
    }.get(reason, "RealtimeCheckFailed")


def display_name(item: dict) -> str:
    return str(item.get("name") or item.get("Name") or item.get("code") or item.get("Code") or "종목명 확인 불가")


def _float_value(value) -> float | None:
    if value in {None, ""}:
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def pct_from_entry(target, entry) -> float | None:
    target_value = _float_value(target)
    entry_value = _float_value(entry)
    if target_value is None or entry_value is None or entry_value <= 0:
        return None
    return round((target_value / entry_value - 1) * 100, 2)


def format_pct(value: float | None) -> str:
    if value is None:
        return "-"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def exit_plan_from_source(source: dict) -> dict:
    raw = source.get("raw") or {}
    entry_price = source.get("entry_price") or source.get("entry")
    stop_loss = source.get("stop_loss")
    take_profit_1 = source.get("take_profit_1")
    take_profit_2 = source.get("take_profit_2")
    trailing_stop = source.get("trailing_stop")
    return {
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "stop_loss_pct": pct_from_entry(stop_loss, entry_price),
        "take_profit_1": take_profit_1,
        "take_profit_1_pct": pct_from_entry(take_profit_1, entry_price),
        "take_profit_2": take_profit_2,
        "take_profit_2_pct": pct_from_entry(take_profit_2, entry_price),
        "trailing_stop": trailing_stop,
        "trailing_stop_pct": pct_from_entry(trailing_stop, entry_price),
        "hold_min_days": raw.get("HoldMinDays"),
        "hold_preferred_days": raw.get("HoldPreferredDays"),
        "hold_max_days": raw.get("HoldMaxDays", 15),
        "planned_entry_window": "14:30-15:20",
        "planned_manage_window": "09:00-15:20",
    }


def action_plan_summary(source: dict) -> str:
    plan = exit_plan_from_source(source)
    return (
        f"손절 {format_pct(plan.get('stop_loss_pct'))} / "
        f"1차 {format_pct(plan.get('take_profit_1_pct'))} / "
        f"2차 {format_pct(plan.get('take_profit_2_pct'))}"
    )


async def get_price_safe(client, code: str) -> int | None:
    try:
        payload = await client.get_current_price(code)
        await asyncio.sleep(QUOTE_DELAY_SECONDS)
        return parse_current_price(payload)
    except Exception:
        await asyncio.sleep(QUOTE_ERROR_BACKOFF_SECONDS)
        return None


def tick_size(price: int) -> int:
    if price < 2_000:
        return 1
    if price < 5_000:
        return 5
    if price < 20_000:
        return 10
    if price < 50_000:
        return 50
    if price < 200_000:
        return 100
    if price < 500_000:
        return 500
    return 1_000


def buy_order_price(quote: dict[str, int]) -> int:
    current_price = int(quote.get("current_price") or 0)
    ask_price = int(quote.get("ask_price") or 0)
    if ask_price > 0:
        return ask_price
    return current_price + tick_size(current_price)


def sell_order_price(quote: dict[str, int]) -> int:
    current_price = int(quote.get("current_price") or 0)
    bid_price = int(quote.get("bid_price") or 0)
    if bid_price > 0:
        return bid_price
    return max(tick_size(current_price), current_price - tick_size(current_price))


def price_ticks_below(price: int, ticks: int) -> int:
    result = max(0, int(price))
    for _ in range(max(0, ticks)):
        result = max(tick_size(result), result - tick_size(result))
    return result


def stop_loss_order_price(quote: dict[str, int], ticks: int = STOP_LOSS_AGGRESSIVE_TICKS) -> int:
    current_price = int(quote.get("current_price") or 0)
    bid_price = int(quote.get("bid_price") or 0)
    base_price = bid_price if bid_price > 0 else current_price
    if base_price <= 0:
        return 0
    return price_ticks_below(base_price, ticks)


def sell_order_policy(reason: str, quote: dict[str, int], ticks: int = STOP_LOSS_AGGRESSIVE_TICKS) -> dict[str, int | str]:
    if reason == "StopLoss":
        return {
            "type": "aggressive_stop_limit",
            "base": "best_bid" if int(quote.get("bid_price") or 0) > 0 else "current_price",
            "slippage_ticks": ticks,
        }
    return {"type": "best_bid_limit", "base": "best_bid_or_current_minus_one_tick", "slippage_ticks": 0}


def exit_order_price(reason: str, quote: dict[str, int]) -> int:
    if reason == "StopLoss":
        return stop_loss_order_price(quote)
    return sell_order_price(quote)


def estimate_exit_cost_pct(strategy: dict) -> float:
    return max(0.0, float(strategy.get("commission_tax_pct") or 0))


def realized_loss_today(logs: list[dict]) -> int:
    loss = 0
    for row in logs:
        if row.get("action") != "SELL":
            continue
        raw = row.get("raw") or {}
        if not isinstance(raw, dict):
            continue
        if raw.get("reason_code") == "OrderPending":
            continue
        realized_pnl = raw.get("realized_pnl")
        try:
            value = int(float(str(realized_pnl)))
        except (TypeError, ValueError):
            continue
        if value < 0:
            loss += abs(value)
    return loss


async def today_trade_logs(user_id: str, broker_account_id: str | None) -> list[dict]:
    start_at = datetime.combine(now_kst().date(), time.min, tzinfo=ZoneInfo(get_settings().timezone)).isoformat()
    filters = {"user_id": f"eq.{user_id}", "created_at": f"gte.{start_at}"}
    if broker_account_id:
        filters["broker_account_id"] = f"eq.{broker_account_id}"
    return await SupabaseRest().select("trade_logs", filters=filters, order="created_at.desc", limit=300)


async def today_stopped_out_codes(user_id: str, broker_account_id: str | None) -> set[str]:
    return await today_exit_reason_codes(user_id, broker_account_id, {"StopLoss"})


async def today_kijun_exit_codes(user_id: str, broker_account_id: str | None) -> set[str]:
    return await today_exit_reason_codes(user_id, broker_account_id, {"KijunExit"})


async def today_exit_reason_codes(user_id: str, broker_account_id: str | None, reasons: set[str]) -> set[str]:
    logs = await today_trade_logs(user_id, broker_account_id)
    codes: set[str] = set()
    for row in logs:
        if row.get("action") != "SELL":
            continue
        raw = row.get("raw") or {}
        if not isinstance(raw, dict):
            continue
        if raw.get("reason_code") in reasons or raw.get("exit_reason") in reasons:
            code = row.get("code")
            if code:
                codes.add(str(code).zfill(6))
    return codes


async def daily_loss_limit_reached(user_id: str, broker_account_id: str | None, total_equity: int, strategy: dict, diagnostics: dict | None = None) -> bool:
    if not strategy.get("use_daily_loss_limit", True):
        return False
    limit = int(max(total_equity, 1) * float(strategy.get("daily_loss_limit_pct") or 0))
    if limit <= 0:
        return False
    loss = realized_loss_today(await today_trade_logs(user_id, broker_account_id))
    if diagnostics is not None:
        diagnostics["daily_realized_loss"] = loss
        diagnostics["daily_loss_limit_amount"] = limit
    return loss >= limit


async def unrealized_loss_limit_reached(balance: dict, total_equity: int, strategy: dict, diagnostics: dict | None = None) -> bool:
    if not strategy.get("use_unrealized_loss_limit", True):
        return False
    limit = int(max(total_equity, 1) * float(strategy.get("unrealized_loss_limit_pct") or 0))
    if limit <= 0:
        return False
    unrealized_pnl = await asyncio.to_thread(extract_unrealized_pnl, balance)
    unrealized_loss = abs(min(unrealized_pnl, 0))
    if diagnostics is not None:
        diagnostics["unrealized_pnl"] = unrealized_pnl
        diagnostics["unrealized_loss"] = unrealized_loss
        diagnostics["unrealized_loss_limit_amount"] = limit
    return unrealized_loss >= limit


def market_intraday_return_pct() -> float | None:
    start = now_kst().date() - timedelta(days=7)
    try:
        frame = fdr.DataReader("KS11", start=start)
    except Exception as exc:
        logger.warning("Market crash filter skipped: failed to load KS11: %s", exc)
        return None
    if frame is None or frame.empty:
        return None
    last = frame.dropna().iloc[-1]
    open_price = float(last.get("Open") or 0)
    close_price = float(last.get("Close") or 0)
    if open_price <= 0 or close_price <= 0:
        return None
    return close_price / open_price - 1


async def market_crash_filter_triggered(strategy: dict, diagnostics: dict | None = None) -> bool:
    if not strategy.get("use_market_crash_filter", True):
        return False
    market_return = await asyncio.to_thread(market_intraday_return_pct)
    if diagnostics is not None:
        diagnostics["market_intraday_return_pct"] = market_return
        diagnostics["market_crash_limit_pct"] = float(strategy.get("market_crash_limit_pct") or 0)
    if market_return is None:
        return False
    return market_return <= float(strategy.get("market_crash_limit_pct") or -0.02)


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
    if strategy.get("use_vi_filter", True) and int(quote.get("vi_active") or 0) > 0:
        return False, "VolatilityInterruption"
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
    payload_raw = {
        **(raw or {}),
        "reason_code": reason,
        "reason_ko": reason_label(reason),
        "reason_detail": decision_reason_detail(reason, signal, price=price, raw=raw or {}),
        "logged_at": now_kst().isoformat(),
    }
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
                "raw": payload_raw,
                "created_at": now_kst().isoformat(),
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


async def today_entry_codes(user_id: str, broker_account_id: str | None) -> set[str]:
    filters = {"user_id": f"eq.{user_id}", "entry_date": f"eq.{now_kst().date().isoformat()}"}
    if broker_account_id:
        filters["broker_account_id"] = f"eq.{broker_account_id}"
    rows = await SupabaseRest().select("positions", columns="code", filters=filters, limit=200)
    return {str(row.get("code") or "").zfill(6) for row in rows if row.get("code")}


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


async def insert_watcher_run(user_id: str, broker_account_id: str | None, payload: dict) -> None:
    try:
        await SupabaseRest().insert(
            "watcher_runs",
            {
                "user_id": user_id,
                "broker_account_id": broker_account_id,
                "mode": payload.get("mode"),
                "orders_allowed": bool(payload.get("orders_allowed")),
                "entry_window_open": bool(payload.get("entry_window_open")),
                "manage_window_open": bool(payload.get("manage_window_open")),
                "cash": payload.get("cash"),
                "total_equity": payload.get("total_equity"),
                "signals_count": int(payload.get("signals_count") or 0),
                "open_positions_count": int(payload.get("open_positions_count") or 0),
                "kis_holdings_count": int(payload.get("kis_holdings_count") or 0),
                "pending_orders_count": int(payload.get("pending_orders_count") or 0),
                "today_entry_count": int(payload.get("today_entry_count") or 0),
                "today_pending_buy_count": int(payload.get("today_pending_buy_count") or 0),
                "remaining_daily_slots": payload.get("remaining_daily_slots"),
                "available_slots": payload.get("available_slots"),
                "affordable_slots": payload.get("affordable_slots"),
                "daily_slots": payload.get("daily_slots"),
                "action_count": int(payload.get("action_count") or 0),
                "buy_order_count": int(payload.get("buy_order_count") or 0),
                "sell_order_count": int(payload.get("sell_order_count") or 0),
                "cooldown_skip_count": int(payload.get("cooldown_skip_count") or 0),
                "skip_reason": payload.get("skip_reason"),
                "raw": payload,
            },
        )
    except RuntimeError as exc:
        logger.warning("Failed to insert watcher run: user_id=%s account_id=%s error=%s", user_id, broker_account_id, exc)


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
        actions.append({"action": "SYNC", "code": code, "name": display_name(position), "qty": actual_qty, "price": int((holding or {}).get("current_price") or 0), "reason": reason_label(reason), "plan": action_plan_summary(position)})
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
    order_payload: dict | None = None
    order_inquiry_error: str | None = None
    if not dry_run:
        try:
            order_payload = await client.inquire_daily_orders_all()
        except Exception as exc:
            order_inquiry_error = str(exc)
            logger.warning("KIS order inquiry failed. Falling back to balance reconciliation: %s", exc)

    for order in pending_orders:
        raw = order.get("raw") or {}
        code = order["code"]
        side = order["side"]
        holding = holdings.get(code)
        previous_qty = int((raw.get("previous_remaining_qty") if isinstance(raw, dict) else 0) or 0)
        execution = find_order_execution(order_payload or {}, order_no=order.get("order_no"), code=code) if order_payload else None
        is_filled = bool(execution and execution.get("fully_filled")) or (side == "BUY" and holding and int(holding.get("qty") or 0) > 0) or (
            side == "SELL" and (not holding or (previous_qty > 0 and int(holding.get("qty") or 0) < previous_qty))
        )

        if execution and execution.get("partially_filled"):
            was_already_partial = order.get("status") == "PARTIAL"
            previous_filled_qty = int((raw.get("filled_qty") if isinstance(raw, dict) else 0) or 0)
            filled_qty = int(execution.get("filled_qty") or 0)
            remaining_qty = int(execution.get("remaining_qty") or 0)
            avg_price = int(execution.get("avg_price") or order.get("price") or 0)
            raw = {
                **raw,
                "execution": execution,
                "filled_qty": filled_qty,
                "remaining_qty": remaining_qty,
                "avg_price": avg_price,
                "partially_filled_at": now_kst().isoformat(),
            }
            await mark_pending_order(int(order["id"]), "PARTIAL", raw)
            if side == "BUY" and holding and code not in open_codes:
                expected = raw.get("expected_position") or {}
                signal = raw.get("signal") or {}
                qty = int((holding or {}).get("qty") or filled_qty or 0)
                entry_price = int((holding or {}).get("avg_price") or avg_price or 0)
                if qty > 0:
                    await rest.insert(
                        "positions",
                        {
                            **expected,
                            "entry_price": entry_price,
                            "qty": qty,
                            "remaining_qty": qty,
                            "raw": {
                                **(expected.get("raw") or {}),
                                "partially_filled": True,
                                "holding": holding,
                                "pending_order_id": order["id"],
                            },
                        },
                    )
                    await insert_trade_log(user_id, broker_account_id, "BUY", signal or order, entry_price, qty, "OrderFilled", raw)
                    open_codes.add(code)
            elif filled_qty > previous_filled_qty:
                delta_qty = filled_qty - previous_filled_qty
                await insert_trade_log(user_id, broker_account_id, side, order, avg_price, delta_qty, "PartialFillUpdated", raw)
            if not was_already_partial:
                actions.append({"action": "PARTIAL", "code": code, "name": display_name(order), "qty": filled_qty, "price": avg_price, "reason": "부분체결 확인", "plan": action_plan_summary((raw.get("expected_position") if isinstance(raw, dict) else None) or order)})
            continue

        if is_filled:
            raw = {
                **raw,
                "filled_at": now_kst().isoformat(),
                "holding": holding,
                "execution": execution,
                "order_inquiry_error": order_inquiry_error,
                "filled_qty": int((execution or {}).get("filled_qty") or (holding or {}).get("qty") or order.get("qty") or 0),
                "remaining_qty": int((execution or {}).get("remaining_qty") or 0),
                "avg_price": int((execution or {}).get("avg_price") or (holding or {}).get("avg_price") or order.get("price") or 0),
            }
            await mark_pending_order(int(order["id"]), "FILLED", raw)
            if side == "BUY" and code not in open_codes:
                expected = raw.get("expected_position") or {}
                signal = raw.get("signal") or {}
                qty = int((holding or {}).get("qty") or (execution or {}).get("filled_qty") or order.get("qty") or 0)
                entry_price = int((holding or {}).get("avg_price") or (execution or {}).get("avg_price") or order.get("price") or 0)
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
            elif side == "SELL":
                position = (raw.get("position") if isinstance(raw, dict) else None) or order
                await insert_trade_log(user_id, broker_account_id, "SELL", position, int(raw.get("avg_price") or order.get("price") or 0), int(raw.get("filled_qty") or order.get("qty") or 0), "OrderFilled", raw)
            actions.append({"action": "FILL", "code": code, "name": display_name(order), "qty": int(order.get("qty") or 0), "price": int(order.get("price") or 0), "reason": reason_label("OrderFilled"), "plan": action_plan_summary((raw.get("expected_position") if isinstance(raw, dict) else None) or order)})
            continue

        reason_code = raw.get("reason_code") if isinstance(raw, dict) else None
        reprice_attempts = int((raw.get("stop_loss_reprice_attempts") if isinstance(raw, dict) else 0) or 0)
        if (
            side == "SELL"
            and reason_code == "StopLoss"
            and not dry_run
            and order.get("order_no")
        ):
            cancel_response = None
            try:
                quote = await get_quote_safe(client, code)
                if not quote:
                    raise RuntimeError("quote unavailable for stop-loss reprice")
                cancel_response = await client.cancel_order(
                    order_org_no=order.get("order_org_no") or "",
                    order_no=order.get("order_no") or "",
                    qty=int(order.get("qty") or 0),
                    price=int(float(order.get("price") or 0)),
                )
                source = (raw.get("position") if isinstance(raw, dict) else None) or order
                if reprice_attempts >= STOP_LOSS_REORDER_MAX_ATTEMPTS:
                    response = await place_market_sell(client, source, int(order.get("qty") or 0), reason="StopLossMarketExit", dry_run=False)
                    final_raw = {
                        **raw,
                        "quote": quote,
                        "previous_order_id": order["id"],
                        "previous_order_no": order.get("order_no"),
                        "previous_price": int(float(order.get("price") or 0)),
                        "stop_loss_reprice_attempts": reprice_attempts,
                        "order_policy": {"type": "market_exit_after_reprice_exhausted", "max_reprice_attempts": STOP_LOSS_REORDER_MAX_ATTEMPTS},
                        "market_exit_at": now_kst().isoformat(),
                    }
                    await mark_pending_order(
                        int(order["id"]),
                        "REPLACED",
                        {**raw, "cancel_response": cancel_response, "replacement_order_type": "market", "replaced_at": now_kst().isoformat()},
                    )
                    await insert_pending_order(
                        user_id,
                        broker_account_id,
                        side="SELL",
                        source=source,
                        qty=int(order.get("qty") or 0),
                        price=0,
                        response=response,
                        reason="StopLoss",
                        raw=final_raw,
                    )
                    await insert_trade_log(user_id, broker_account_id, "ORDER", source, 0, int(order.get("qty") or 0), "StopLossMarketExit", {"old_order": order, "cancel_response": cancel_response, "new_order": response, **final_raw})
                    actions.append({"action": "MARKET_EXIT", "code": code, "name": display_name(order), "qty": int(order.get("qty") or 0), "price": 0, "reason": reason_label("StopLossMarketExit"), "plan": action_plan_summary(source)})
                    continue

                reprice_ticks = STOP_LOSS_AGGRESSIVE_TICKS + ((reprice_attempts + 1) * STOP_LOSS_REORDER_EXTRA_TICKS)
                new_price = stop_loss_order_price(quote, reprice_ticks)
                if new_price <= 0:
                    raise RuntimeError("invalid stop-loss reprice")
                new_raw = {
                    **raw,
                    "quote": quote,
                    "previous_order_id": order["id"],
                    "previous_order_no": order.get("order_no"),
                    "previous_price": int(float(order.get("price") or 0)),
                    "stop_loss_reprice_attempts": reprice_attempts + 1,
                    "order_policy": sell_order_policy("StopLoss", quote, reprice_ticks),
                    "repriced_at": now_kst().isoformat(),
                }
                response = await place_sell(client, source, int(order.get("qty") or 0), new_price, reason="StopLoss", dry_run=False)
                await mark_pending_order(
                    int(order["id"]),
                    "REPLACED",
                    {**raw, "cancel_response": cancel_response, "replacement_price": new_price, "replaced_at": now_kst().isoformat()},
                )
                await insert_pending_order(
                    user_id,
                    broker_account_id,
                    side="SELL",
                    source=source,
                    qty=int(order.get("qty") or 0),
                    price=new_price,
                    response=response,
                    reason="StopLoss",
                    raw=new_raw,
                )
                await insert_trade_log(user_id, broker_account_id, "ORDER", source, new_price, int(order.get("qty") or 0), "StopLossRepriced", {"old_order": order, "cancel_response": cancel_response, "new_order": response, **new_raw})
                actions.append({"action": "REPRICE", "code": code, "name": display_name(order), "qty": int(order.get("qty") or 0), "price": new_price, "reason": reason_label("StopLossRepriced"), "plan": action_plan_summary(source)})
                continue
            except Exception as exc:
                raw = {**raw, "stop_loss_reprice_error": str(exc), "stop_loss_reprice_failed_at": now_kst().isoformat()}
                if cancel_response:
                    raw = {**raw, "cancel_response": cancel_response}
                    await mark_pending_order(int(order["id"]), "CANCELED", raw)
                else:
                    await mark_pending_order(int(order["id"]), "CANCEL_FAILED", raw)
                await insert_trade_log(user_id, broker_account_id, "ORDER", order, int(float(order.get("price") or 0)), int(order.get("qty") or 0), "OrderCancelFailed", raw)
                actions.append({"action": "REPRICE_FAILED", "code": code, "name": display_name(order), "qty": int(order.get("qty") or 0), "price": int(float(order.get("price") or 0)), "reason": reason_label("OrderCancelFailed"), "plan": action_plan_summary(order)})
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
            actions.append({"action": "CANCEL", "code": code, "name": display_name(order), "qty": int(order.get("qty") or 0), "price": int(float(order.get("price") or 0)), "reason": reason_label("OrderCanceled"), "plan": action_plan_summary((raw.get("expected_position") if isinstance(raw, dict) else None) or order)})
        except Exception as exc:
            raw = {**raw, "cancel_error": str(exc), "cancel_failed_at": now_kst().isoformat()}
            await mark_pending_order(int(order["id"]), "CANCEL_FAILED", raw)
            await insert_trade_log(user_id, broker_account_id, side, order, int(float(order.get("price") or 0)), int(order.get("qty") or 0), "OrderCancelFailed", raw)
            actions.append({"action": "CANCEL_FAILED", "code": code, "name": display_name(order), "qty": int(order.get("qty") or 0), "price": int(float(order.get("price") or 0)), "reason": reason_label("OrderCancelFailed"), "plan": action_plan_summary((raw.get("expected_position") if isinstance(raw, dict) else None) or order)})

    return actions


async def place_sell(client, position: dict, qty: int, price: int, *, reason: str, dry_run: bool) -> dict:
    if dry_run:
        return {"dry_run": True, "side": "sell", "code": position["code"], "qty": qty, "price": price, "reason": reason}
    return await client.sell_limit(position["code"], qty, price)


async def place_market_sell(client, position: dict, qty: int, *, reason: str, dry_run: bool) -> dict:
    if dry_run:
        return {"dry_run": True, "side": "sell", "order_type": "market", "code": position["code"], "qty": qty, "price": 0, "reason": reason}
    return await client.sell_market(position["code"], qty)


async def place_buy(client, signal: dict, qty: int, price: int, *, dry_run: bool) -> dict:
    if dry_run:
        return {"dry_run": True, "side": "buy", "code": signal["code"], "qty": qty, "price": price}
    return await client.buy_limit(signal["code"], qty, price)


async def manage_positions(
    user_id: str,
    broker_account_id: str | None,
    client,
    positions: list[dict],
    *,
    test_mode: bool,
    dry_run: bool,
    quote_overrides: dict[str, dict] | None = None,
    diagnostics: dict | None = None,
) -> list[dict]:
    manage_window_open = in_window(MANAGE_START, MANAGE_END, test_mode=test_mode)
    if diagnostics is not None:
        diagnostics["manage_window_open"] = manage_window_open
        diagnostics.setdefault("cooldown_skip_count", 0)
    if not manage_window_open:
        return []

    actions: list[dict] = []
    rest = SupabaseRest()
    strategy = await get_strategy_settings(user_id)
    pending_sells = {order["code"] for order in await open_pending_orders(user_id, broker_account_id) if order.get("side") == "SELL"}
    for position in positions:
        if position["code"] in pending_sells:
            continue

        quote = (quote_overrides or {}).get(str(position["code"]).zfill(6))
        if quote is None:
            quote = await get_quote_safe(client, position["code"])
        if quote is None:
            continue
        current_price = quote["current_price"]
        if current_price <= 0:
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
        elif in_strategy_sell_cooldown(position):
            if diagnostics is not None:
                diagnostics["cooldown_skip_count"] = int(diagnostics.get("cooldown_skip_count") or 0) + 1
            continue
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

        order_price = exit_order_price(reason, quote)
        order_policy = sell_order_policy(reason, quote)
        gross_pnl = (order_price - entry_price) * sell_qty
        cost_amount = order_price * sell_qty * estimate_exit_cost_pct(strategy)
        realized_pnl = gross_pnl - cost_amount
        response = await place_sell(client, position, sell_qty, order_price, reason=reason, dry_run=dry_run)
        if patch.get("remaining_qty", remaining_qty) <= 0:
            patch["status"] = "CLOSED"
        action_reason = reason_label(reason)
        if order_policy.get("type") == "aggressive_stop_limit":
            action_reason = f"{action_reason} (공격적 지정가 {order_policy['slippage_ticks']}틱)"
        if dry_run:
            await rest.patch("positions", filters={"id": f"eq.{position['id']}"}, payload=patch)
            await insert_trade_log(user_id, broker_account_id, "SELL", position, order_price, sell_qty, reason, {"quote": quote, "trigger_price": current_price, "order": response, "order_policy": order_policy, "strategy": strategy, "patch": patch, "gross_pnl": gross_pnl, "cost_amount": cost_amount, "realized_pnl": realized_pnl})
            actions.append({"action": "SELL", "code": position["code"], "name": display_name(position), "qty": sell_qty, "price": order_price, "reason": action_reason, "plan": action_plan_summary(position)})
        else:
            await insert_pending_order(
                user_id,
                broker_account_id,
                side="SELL",
                source=position,
                qty=sell_qty,
                price=order_price,
                response=response,
                reason=reason,
                raw={"position": position, "quote": quote, "trigger_price": current_price, "order_policy": order_policy, "patch": patch, "strategy": strategy, "previous_remaining_qty": remaining_qty, "gross_pnl": gross_pnl, "cost_amount": cost_amount, "realized_pnl": realized_pnl},
            )
            await insert_trade_log(user_id, broker_account_id, "SELL", position, order_price, sell_qty, "OrderPending", {"quote": quote, "trigger_price": current_price, "order": response, "order_policy": order_policy, "strategy": strategy, "exit_reason": reason, "patch": patch, "gross_pnl": gross_pnl, "cost_amount": cost_amount, "realized_pnl": realized_pnl})
            actions.append({"action": "SELL_ORDER", "code": position["code"], "name": display_name(position), "qty": sell_qty, "price": order_price, "reason": f"{action_reason} 주문 접수", "plan": action_plan_summary(position)})

    return actions


async def enter_positions(
    user_id: str,
    broker_account_id: str | None,
    client,
    positions: list[dict],
    balance: dict,
    *,
    test_mode: bool,
    dry_run: bool,
    diagnostics: dict | None = None,
) -> list[dict]:
    entry_window_open = in_window(ENTRY_START, ENTRY_END, test_mode=test_mode)
    if diagnostics is not None:
        diagnostics["entry_window_open"] = entry_window_open
    if not entry_window_open:
        if diagnostics is not None:
            diagnostics["skip_reason"] = "outside_entry_window"
        logger.warning("Watcher enter skipped: outside entry window user_id=%s account_id=%s", user_id, broker_account_id)
        return []

    signals = await today_signals()
    if diagnostics is not None:
        diagnostics["signals_count"] = len(signals)
    if not signals:
        if diagnostics is not None:
            diagnostics["skip_reason"] = "no_shared_signals"
        logger.warning("Watcher enter skipped: no shared signals user_id=%s account_id=%s", user_id, broker_account_id)
        return []

    cash = extract_cash(balance)
    total_equity = extract_total_equity(balance)
    strategy = await get_strategy_settings(user_id)
    if await daily_loss_limit_reached(user_id, broker_account_id, total_equity, strategy, diagnostics):
        if diagnostics is not None:
            diagnostics["skip_reason"] = "daily_loss_limit"
        logger.warning("Watcher enter skipped: daily loss limit reached user_id=%s account_id=%s", user_id, broker_account_id)
        return []
    if await unrealized_loss_limit_reached(balance, total_equity, strategy, diagnostics):
        if diagnostics is not None:
            diagnostics["skip_reason"] = "unrealized_loss_limit"
        logger.warning("Watcher enter skipped: unrealized loss limit reached user_id=%s account_id=%s", user_id, broker_account_id)
        return []
    if await market_crash_filter_triggered(strategy, diagnostics):
        if diagnostics is not None:
            diagnostics["skip_reason"] = "market_crash_filter"
        logger.warning("Watcher enter skipped: market crash filter triggered user_id=%s account_id=%s", user_id, broker_account_id)
        return []
    kis_codes = kis_holding_codes(balance)
    open_codes = {position["code"] for position in positions}
    pending_orders = await open_pending_orders(user_id, broker_account_id)
    pending_codes = {order["code"] for order in pending_orders}
    pending_buy_codes = {order["code"] for order in pending_orders if order.get("side") == "BUY"}
    today_codes = await today_entry_codes(user_id, broker_account_id)
    stopped_out_codes = await today_stopped_out_codes(user_id, broker_account_id) if strategy.get("use_stoploss_reentry_block", True) else set()
    kijun_exit_codes = await today_kijun_exit_codes(user_id, broker_account_id) if strategy.get("use_kijun_reentry_block", True) else set()
    today_used_codes = today_codes | pending_buy_codes
    blocked_codes = open_codes | kis_codes | pending_codes
    held_or_pending_codes = open_codes | kis_codes | pending_codes
    available_slots = max(0, int(strategy["max_open_positions"]) - len(held_or_pending_codes))
    affordable_slots = int(cash // max(int(strategy["min_order_amount"]), 1))
    remaining_daily_slots = max(0, int(strategy["max_new_positions_per_day"]) - len(today_used_codes))
    daily_slots = min(remaining_daily_slots, available_slots, affordable_slots)
    if diagnostics is not None:
        diagnostics.update(
            {
                "cash": cash,
                "total_equity": total_equity,
                "open_positions_count": len(open_codes),
                "kis_holdings_count": len(kis_codes),
                "pending_orders_count": len(pending_codes),
                "today_entry_count": len(today_codes),
                "today_pending_buy_count": len(pending_buy_codes),
                "today_stopped_out_count": len(stopped_out_codes),
                "today_kijun_exit_count": len(kijun_exit_codes),
                "remaining_daily_slots": remaining_daily_slots,
                "available_slots": available_slots,
                "affordable_slots": affordable_slots,
                "daily_slots": daily_slots,
                "strategy": strategy,
            }
        )
    logger.warning(
        "Watcher enter summary: user_id=%s account_id=%s cash=%s equity=%s signals=%s open=%s kis=%s pending=%s today_entries=%s pending_buys=%s remaining_daily_slots=%s available_slots=%s affordable_slots=%s daily_slots=%s min_order=%s max_new=%s position_pct=%s risk_pct=%s",
        user_id,
        broker_account_id,
        cash,
        total_equity,
        len(signals),
        len(open_codes),
        len(kis_codes),
        len(pending_codes),
        len(today_codes),
        len(pending_buy_codes),
        remaining_daily_slots,
        available_slots,
        affordable_slots,
        daily_slots,
        strategy["min_order_amount"],
        strategy["max_new_positions_per_day"],
        strategy["position_capital_pct"],
        strategy["risk_per_trade_pct"],
    )
    if daily_slots <= 0:
        if diagnostics is not None:
            diagnostics["skip_reason"] = "no_buy_slots"
        logger.warning("Watcher enter skipped: no buy slots user_id=%s account_id=%s", user_id, broker_account_id)
        return []

    actions: list[dict] = []
    rest = SupabaseRest()
    for signal in signals:
        if len(actions) >= daily_slots:
            break

        score = float(signal.get("score") or 0)
        if signal["code"] in stopped_out_codes:
            await insert_decision_log(user_id, broker_account_id, "SKIP", signal, "StoppedOutToday", raw={"strategy": strategy})
            continue
        if signal["code"] in kijun_exit_codes:
            await insert_decision_log(user_id, broker_account_id, "SKIP", signal, "KijunExitedToday", raw={"strategy": strategy})
            continue
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
        order_price = buy_order_price(quote)
        raw = signal.get("raw") or {}
        passed, reason = passes_intraday_entry_filter(signal, quote, strategy)
        if not passed:
            await insert_decision_log(user_id, broker_account_id, "SKIP", signal, reason, price=current_price, raw={"quote": quote, "strategy": strategy})
            continue

        realtime_result = await check_realtime_entry_risk(client, signal["code"], strategy)
        realtime_raw = {
            "reason": realtime_result.reason,
            "strength": realtime_result.strength,
            "bid_ask_ratio": realtime_result.bid_ask_ratio,
            "spread_pct": realtime_result.spread_pct,
            "samples": realtime_result.samples,
            "raw": realtime_result.raw,
        }
        if realtime_result.reason == "realtime_check_failed":
            logger.warning("Realtime filter failed open: code=%s result=%s", signal["code"], realtime_raw)
        elif not realtime_result.ok:
            reason_code = realtime_reason_code(realtime_result.reason)
            await insert_decision_log(user_id, broker_account_id, "SKIP", signal, reason_code, price=current_price, raw={"quote": quote, "realtime": realtime_raw, "strategy": strategy})
            continue

        sizing_signal = {**signal, "entry": order_price}
        effective_total_equity = total_equity if total_equity > 0 else DEFAULT_CAPITAL
        qty, sizing = calculate_order_qty(
            sizing_signal,
            cash=cash,
            total_equity=effective_total_equity,
            available_slots=1,
            position_capital_pct=float(strategy["position_capital_pct"]),
            risk_per_trade_pct=float(strategy["risk_per_trade_pct"]),
            min_order_amount=int(strategy["min_order_amount"]),
        )
        if qty <= 0:
            sizing_reason = sizing_reject_reason_code(sizing)
            await insert_decision_log(
                user_id,
                broker_account_id,
                "SKIP",
                signal,
                sizing_reason,
                price=current_price,
                raw={"quote": quote, "sizing": sizing, "sizing_detail": sizing_reject_detail(sizing), "strategy": strategy},
            )
            continue
        max_orderable_qty = int((cash * BUY_ORDER_CASH_BUFFER) // max(order_price, 1))
        if max_orderable_qty <= 0 or max_orderable_qty * order_price < int(strategy["min_order_amount"]):
            await insert_decision_log(
                user_id,
                broker_account_id,
                "SKIP",
                signal,
                "OrderableCashExceeded",
                price=current_price,
                raw={"quote": quote, "sizing": sizing, "strategy": strategy, "cash": cash, "order_price": order_price, "max_orderable_qty": max_orderable_qty},
            )
            continue
        if qty > max_orderable_qty:
            sizing = {**sizing, "original_qty": qty, "cash_buffer": BUY_ORDER_CASH_BUFFER, "max_orderable_qty": max_orderable_qty}
            qty = max_orderable_qty

        try:
            response = await place_buy(client, signal, qty, order_price, dry_run=dry_run)
        except RuntimeError as exc:
            if "APBK0952" in str(exc) or "주문가능금액" in str(exc):
                await insert_decision_log(
                    user_id,
                    broker_account_id,
                    "SKIP",
                    signal,
                    "OrderableCashExceeded",
                    price=current_price,
                    raw={"quote": quote, "sizing": sizing, "strategy": strategy, "cash": cash, "order_price": order_price, "qty": qty, "error": str(exc)},
                )
                cash = max(0, cash - int(qty * order_price))
                continue
            raise
        position_payload = {
            "user_id": user_id,
            "broker_account_id": broker_account_id,
            "code": signal["code"],
            "name": signal["name"],
            "entry_date": now_kst().date().isoformat(),
            "entry_price": order_price,
            "qty": qty,
            "remaining_qty": qty,
            "stop_loss": signal["stop_loss"],
            "take_profit_1": signal["take_profit_1"],
            "take_profit_2": signal["take_profit_2"],
            "trailing_stop": signal["trailing_stop"],
            "status": "OPEN",
            "take_profit_1_done": False,
            "take_profit_2_done": False,
            "raw": {**raw, "intraday_quote": quote, "realtime": realtime_raw, "trigger_price": current_price, "kis_order_response": response, "sizing": sizing},
        }
        if dry_run:
            await rest.insert("positions", position_payload)
            await insert_trade_log(
                user_id,
                broker_account_id,
                "BUY",
                signal,
                order_price,
                qty,
                reason,
                {"quote": quote, "realtime": realtime_raw, "trigger_price": current_price, "order": response, "signal_raw": raw},
            )
            actions.append({"action": "BUY", "code": signal["code"], "name": display_name(signal), "qty": qty, "price": order_price, "reason": reason_label(reason), "plan": action_plan_summary(position_payload)})
        else:
            await insert_pending_order(
                user_id,
                broker_account_id,
                side="BUY",
                source=signal,
                qty=qty,
                price=order_price,
                response=response,
                reason=reason,
                raw={"signal": signal, "quote": quote, "realtime": realtime_raw, "trigger_price": current_price, "signal_raw": raw, "sizing": sizing, "expected_position": position_payload},
            )
            await insert_trade_log(
                user_id,
                broker_account_id,
                "BUY",
                signal,
                order_price,
                qty,
                "OrderPending",
                {"quote": quote, "realtime": realtime_raw, "trigger_price": current_price, "order": response, "signal_raw": raw, "entry_reason": reason},
            )
            actions.append({"action": "BUY_ORDER", "code": signal["code"], "name": display_name(signal), "qty": qty, "price": order_price, "reason": reason_label("OrderPending"), "plan": action_plan_summary(position_payload)})
        blocked_codes.add(signal["code"])
        cash = max(0, cash - int(qty * order_price))

    if diagnostics is not None:
        diagnostics["skip_reason"] = "completed" if actions else diagnostics.get("skip_reason") or "no_buy_order_created"
        diagnostics["buy_order_count"] = len([item for item in actions if str(item.get("action", "")).startswith("BUY")])

    return actions


async def run_watch_tick_for_user(credentials: dict, *, test_mode: bool = False, dry_run: bool = False) -> dict:
    user_id = credentials["user_id"]
    broker_account_id = credentials.get("id")
    settings = get_settings()
    is_live = (credentials.get("mode") or "paper") == "live"
    allow_live_orders = bool(credentials.get("live_order_enabled")) and settings.allow_live_trading
    client = client_from_credentials(credentials, enable_orders=not dry_run, allow_live_orders=allow_live_orders)
    actions: list[dict] = []
    diagnostics: dict = {
        "run_at": now_kst().isoformat(),
        "mode": credentials.get("mode") or "paper",
        "test_mode": test_mode,
        "dry_run": dry_run,
        "live_order_enabled": bool(credentials.get("live_order_enabled")),
        "server_live_trading_allowed": settings.allow_live_trading,
        "orders_allowed": not dry_run and (not is_live or allow_live_orders),
        "entry_window_open": in_window(ENTRY_START, ENTRY_END, test_mode=test_mode),
        "manage_window_open": in_window(MANAGE_START, MANAGE_END, test_mode=test_mode),
    }
    try:
        diagnostics["stage"] = "initial_balance"
        balance = await client.get_balance()
        diagnostics["cash"] = extract_cash(balance)
        diagnostics["total_equity"] = extract_total_equity(balance)
        diagnostics["kis_holdings_count"] = len(kis_holding_codes(balance))

        diagnostics["stage"] = "reconcile_pending_before_manage"
        actions.extend(await reconcile_pending_orders(user_id, broker_account_id, client, balance, test_mode=test_mode, dry_run=dry_run))
        positions = await open_positions(user_id, broker_account_id)
        diagnostics["open_positions_count"] = len(positions)

        diagnostics["stage"] = "sync_positions_before_manage"
        actions.extend(await sync_positions_with_balance(user_id, broker_account_id, positions, balance))
        positions = await open_positions(user_id, broker_account_id)
        diagnostics["open_positions_count"] = len(positions)

        diagnostics["stage"] = "manage_positions"
        actions.extend(await manage_positions(user_id, broker_account_id, client, positions, test_mode=test_mode, dry_run=dry_run, diagnostics=diagnostics))

        diagnostics["stage"] = "post_manage_balance"
        balance = await client.get_balance()
        diagnostics["cash"] = extract_cash(balance)
        diagnostics["total_equity"] = extract_total_equity(balance)
        diagnostics["kis_holdings_count"] = len(kis_holding_codes(balance))

        diagnostics["stage"] = "reconcile_pending_after_manage"
        actions.extend(await reconcile_pending_orders(user_id, broker_account_id, client, balance, test_mode=test_mode, dry_run=dry_run))
        positions = await open_positions(user_id, broker_account_id)

        diagnostics["stage"] = "sync_positions_after_manage"
        actions.extend(await sync_positions_with_balance(user_id, broker_account_id, positions, balance))
        positions = await open_positions(user_id, broker_account_id)
        diagnostics["open_positions_count"] = len(positions)

        diagnostics["stage"] = "enter_positions"
        actions.extend(await enter_positions(user_id, broker_account_id, client, positions, balance, test_mode=test_mode, dry_run=dry_run, diagnostics=diagnostics))
        diagnostics["stage"] = "completed"
    except Exception as exc:
        diagnostics["skip_reason"] = "watcher_error"
        diagnostics["error"] = str(exc)
        logger.exception("Watcher tick failed: user_id=%s account_id=%s stage=%s", user_id, broker_account_id, diagnostics.get("stage"))
        raise
    finally:
        diagnostics["action_count"] = len(actions)
        diagnostics["buy_order_count"] = len([item for item in actions if str(item.get("action", "")).startswith("BUY")])
        diagnostics["sell_order_count"] = len([item for item in actions if str(item.get("action", "")).startswith("SELL")])
        diagnostics["actions"] = actions
        await insert_watcher_run(user_id, broker_account_id, diagnostics)

    if actions:
        lines = [f"KOSPI bot actions: {len(actions)}"]
        lines.extend(f"{item['action']} {item.get('name') or item['code']} qty {item['qty']} @ {item['price']:,} {item['reason']} ({item.get('plan') or '-'})" for item in actions)
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


async def run_realtime_position_watch_for_user(credentials: dict, *, dry_run: bool = False) -> dict:
    settings = get_settings()
    user_id = credentials["user_id"]
    broker_account_id = credentials.get("id")
    is_live = (credentials.get("mode") or "paper") == "live"
    allow_live_orders = bool(credentials.get("live_order_enabled")) and settings.allow_live_trading
    client = client_from_credentials(credentials, enable_orders=not dry_run, allow_live_orders=allow_live_orders)
    actions: list[dict] = []
    diagnostics: dict = {
        "run_at": now_kst().isoformat(),
        "mode": credentials.get("mode") or "paper",
        "dry_run": dry_run,
        "realtime_position_watch": True,
        "orders_allowed": not dry_run and (not is_live or allow_live_orders),
        "manage_window_open": in_window(MANAGE_START, MANAGE_END, test_mode=False),
    }
    if not diagnostics["manage_window_open"]:
        return {"user_id": user_id, "broker_account_id": broker_account_id, "actions": [], "action_count": 0, "diagnostics": diagnostics}

    try:
        positions = await open_positions(user_id, broker_account_id)
        diagnostics["open_positions_count"] = len(positions)
        if not positions:
            diagnostics["skip_reason"] = "no_open_positions"
            return {"user_id": user_id, "broker_account_id": broker_account_id, "actions": [], "action_count": 0, "diagnostics": diagnostics}

        codes = [str(position["code"]).zfill(6) for position in positions]
        quote_overrides = await collect_realtime_prices(client, codes, settings.kis_position_realtime_watch_seconds)
        diagnostics["realtime_codes"] = codes
        diagnostics["realtime_quotes_count"] = len(quote_overrides)
        if not quote_overrides:
            diagnostics["skip_reason"] = "no_realtime_quotes"
            return {"user_id": user_id, "broker_account_id": broker_account_id, "actions": [], "action_count": 0, "diagnostics": diagnostics}

        actions.extend(await manage_positions(user_id, broker_account_id, client, positions, test_mode=False, dry_run=dry_run, quote_overrides=quote_overrides, diagnostics=diagnostics))
        diagnostics["stage"] = "completed"
    except Exception as exc:
        diagnostics["skip_reason"] = "realtime_position_watch_error"
        diagnostics["error"] = str(exc)
        logger.exception("Realtime position watch failed: user_id=%s account_id=%s", user_id, broker_account_id)
        raise
    finally:
        diagnostics["action_count"] = len(actions)
        diagnostics["sell_order_count"] = len([item for item in actions if str(item.get("action", "")).startswith("SELL")])
        diagnostics["actions"] = actions
        if actions:
            await insert_watcher_run(user_id, broker_account_id, diagnostics)

    if actions:
        lines = [f"KOSPI realtime position actions: {len(actions)}"]
        lines.extend(f"{item['action']} {item.get('name') or item['code']} qty {item['qty']} @ {item['price']:,} {item['reason']} ({item.get('plan') or '-'})" for item in actions)
        await send_telegram_message_with_bot(credentials.get("telegram_bot_token"), credentials.get("telegram_chat_id"), "\n".join(lines))

    return {
        "user_id": user_id,
        "broker_account_id": broker_account_id,
        "actions": actions,
        "action_count": len(actions),
        "diagnostics": diagnostics,
    }
