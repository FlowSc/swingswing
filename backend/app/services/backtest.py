from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

import FinanceDataReader as fdr
import pandas as pd

from app.core.config import get_settings
from app.services.scanner import (
    SCAN_UNIVERSE_LIMITED,
    load_scan_universe,
    score_swing_setup,
    shared_signal_to_record,
    sort_top_signals,
)


logger = logging.getLogger(__name__)
LOOKBACK_DAYS = 430
FORWARD_DAYS = 35
MAX_DAILY_SIGNALS = 10
ProgressCallback = Callable[[dict], None]


async def run_shared_signal_backtest(days: int = 120, max_signals: int = 200) -> dict:
    return await asyncio.to_thread(run_historical_rescan_backtest_sync, days, max_signals)


async def prepare_backtest_state(days: int = 120, max_signals: int = 200) -> dict:
    return await asyncio.to_thread(prepare_backtest_state_sync, days, max_signals)


def prepare_backtest_state_sync(days: int = 120, max_signals: int = 200) -> dict:
    end = datetime.now(ZoneInfo(get_settings().timezone)).date()
    start = end - timedelta(days=days)
    fetch_start = start - timedelta(days=LOOKBACK_DAYS)
    fetch_end = end + timedelta(days=FORWARD_DAYS)
    universe = load_scan_universe(SCAN_UNIVERSE_LIMITED)
    market_frame = load_market_frame(fetch_start, end)
    if market_frame.empty:
        raise RuntimeError("Market data is empty.")

    trading_dates = [
        item.date().isoformat()
        for item in market_frame.loc[str(start):str(end)].index
        if item.date() < end
    ]
    return {
        "source": "historical_rescan",
        "strategy_key": "swing_default",
        "strategy_version": "2026-05-04",
        "days": days,
        "max_signals": max_signals,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "fetch_start": fetch_start.isoformat(),
        "fetch_end": fetch_end.isoformat(),
        "universe_scope": SCAN_UNIVERSE_LIMITED,
        "offset": 0,
        "total": len(universe),
        "chunk_size": 50,
        "trading_dates": trading_dates,
        "market_filter_by_date": {key.isoformat(): value for key, value in build_market_filter_map(market_frame).items()},
        "market_return_by_date": {key.isoformat(): value for key, value in build_market_return_map(market_frame).items()},
        "universe": universe.to_dict("records"),
        "candidates": [],
        "skipped": 0,
        "done": False,
    }


async def process_backtest_chunk(state: dict) -> dict:
    return await asyncio.to_thread(process_backtest_chunk_sync, state)


def process_backtest_chunk_sync(state: dict) -> dict:
    offset = int(state.get("offset") or 0)
    chunk_size = int(state.get("chunk_size") or 50)
    universe = state.get("universe") or []
    total = len(universe)
    fetch_start = str(state["fetch_start"])
    fetch_end = str(state["fetch_end"])
    trading_dates = [date.fromisoformat(value) for value in state.get("trading_dates") or []]
    market_filter_by_date = state.get("market_filter_by_date") or {}
    market_return_by_date = state.get("market_return_by_date") or {}
    candidates = list(state.get("candidates") or [])
    skipped = int(state.get("skipped") or 0)

    logger.warning("Historical backtest chunk started: %s-%s/%s candidates=%s", offset + 1, min(offset + chunk_size, total), total, len(candidates))
    for row in universe[offset : offset + chunk_size]:
        try:
            frame = fdr.DataReader(row["Code"], start=fetch_start, end=fetch_end)
            if frame is None or frame.empty:
                skipped += 1
                continue
            for trade_date in trading_dates:
                history = frame.loc[:trade_date.isoformat()]
                if len(history) < 260:
                    continue
                signal = score_swing_setup(
                    history,
                    row["Code"],
                    row["Name"],
                    market_filter_ok=bool(market_filter_by_date.get(trade_date.isoformat(), False)),
                    universe=row["Universe"],
                    market_ret_20d=float(market_return_by_date.get(trade_date.isoformat(), 0.0)),
                    company_profile=row.get("CompanyProfile") or {},
                    core_universe=truthy(row.get("CoreUniverse")),
                    core_universe_type=str(row.get("CoreUniverseType") or ""),
                )
                if signal:
                    candidates.append(shared_signal_to_record(trade_date, signal))
        except Exception as exc:
            skipped += 1
            logger.debug("Historical backtest chunk skipped code=%s error=%s", row.get("Code"), exc, exc_info=True)

    next_offset = min(offset + chunk_size, total)
    state = {
        **state,
        "offset": next_offset,
        "total": total,
        "candidates": candidates,
        "skipped": skipped,
        "done": next_offset >= total,
    }
    logger.warning("Historical backtest chunk completed: offset=%s/%s candidates=%s done=%s", next_offset, total, len(candidates), state["done"])
    return state


async def finalize_backtest_state(state: dict) -> dict:
    return await asyncio.to_thread(finalize_backtest_state_sync, state)


def finalize_backtest_state_sync(state: dict) -> dict:
    ranked = rank_daily_signal_records(state.get("candidates") or [])
    ranked_for_test = sorted(ranked, key=lambda item: item["trade_date"], reverse=True)[: int(state.get("max_signals") or 200)]
    trades = [trade for row in ranked_for_test if (trade := simulate_signal_safe(row))]
    return summarize_trades(
        int(state.get("days") or 120),
        trades,
        source="historical_rescan",
        generated_signals=len(ranked),
        skipped_symbols=int(state.get("skipped") or 0),
    )


def run_historical_rescan_backtest_sync(
    days: int = 120,
    max_signals: int = 200,
    progress_callback: ProgressCallback | None = None,
) -> dict:
    end = datetime.now(ZoneInfo(get_settings().timezone)).date()
    start = end - timedelta(days=days)
    fetch_start = start - timedelta(days=LOOKBACK_DAYS)
    fetch_end = end + timedelta(days=FORWARD_DAYS)

    logger.warning("Historical backtest started: start=%s end=%s max_signals=%s", start, end, max_signals)
    universe = load_scan_universe(SCAN_UNIVERSE_LIMITED)
    market_frame = load_market_frame(fetch_start, end)
    if market_frame.empty:
        return empty_result(days, "historical_rescan", "Market data is empty.")

    trading_dates = [
        item.date()
        for item in market_frame.loc[str(start):str(end)].index
        if item.date() < end
    ]
    market_filter_by_date = build_market_filter_map(market_frame)
    market_return_by_date = build_market_return_map(market_frame)

    signals: list[dict] = []
    skipped = 0
    for index, row in enumerate(universe.to_dict("records"), start=1):
        try:
            frame = fdr.DataReader(row["Code"], start=fetch_start.strftime("%Y-%m-%d"), end=fetch_end.strftime("%Y-%m-%d"))
            if frame is None or frame.empty:
                skipped += 1
                continue
            for trade_date in trading_dates:
                history = frame.loc[:trade_date.isoformat()]
                if len(history) < 260:
                    continue
                signal = score_swing_setup(
                    history,
                    row["Code"],
                    row["Name"],
                    market_filter_ok=market_filter_by_date.get(trade_date, False),
                    universe=row["Universe"],
                    market_ret_20d=market_return_by_date.get(trade_date, 0.0),
                    company_profile=row.get("CompanyProfile") or {},
                    core_universe=truthy(row.get("CoreUniverse")),
                    core_universe_type=str(row.get("CoreUniverseType") or ""),
                )
                if not signal:
                    continue
                signals.append(
                    {
                        "trade_date": trade_date,
                        "signal": signal,
                        "forward_frame": frame.loc[trade_date.isoformat() : (trade_date + timedelta(days=FORWARD_DAYS)).isoformat()],
                    }
                )
        except Exception as exc:
            skipped += 1
            logger.debug("Historical backtest skipped code=%s error=%s", row.get("Code"), exc, exc_info=True)
            continue
        if index == 1 or index % 50 == 0:
            logger.warning("Historical backtest progress: %s/%s signals=%s skipped=%s", index, len(universe), len(signals), skipped)
            if progress_callback:
                progress_callback(
                    {
                        "processed": index,
                        "total": len(universe),
                        "signals": len(signals),
                        "skipped": skipped,
                    }
                )

    daily_ranked = rank_daily_signals(signals)
    ranked_for_test = sorted(daily_ranked, key=lambda item: item["trade_date"], reverse=True)[:max_signals]
    trades = [trade for item in ranked_for_test if (trade := simulate_generated_signal_safe(item))]
    result = summarize_trades(days, trades, source="historical_rescan", generated_signals=len(daily_ranked), skipped_symbols=skipped)
    if progress_callback:
        progress_callback(
            {
                "processed": len(universe),
                "total": len(universe),
                "signals": len(signals),
                "skipped": skipped,
                "tested": len(trades),
            }
        )
    return result


def load_market_frame(start: date, end: date) -> pd.DataFrame:
    frame = fdr.DataReader("KS11", start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"))
    if frame is None or frame.empty:
        return pd.DataFrame()
    return frame.copy()


def build_market_filter_map(frame: pd.DataFrame) -> dict[date, bool]:
    close = frame["Close"]
    ma5 = close.rolling(5).mean()
    return {idx.date(): bool(close.loc[idx] > ma5.loc[idx]) for idx in frame.index if not pd.isna(ma5.loc[idx])}


def build_market_return_map(frame: pd.DataFrame) -> dict[date, float]:
    close = frame["Close"]
    returns = close / close.shift(20) - 1
    return {
        idx.date(): float(returns.loc[idx] * 100)
        for idx in frame.index
        if not pd.isna(returns.loc[idx])
    }


def rank_daily_signals(items: list[dict]) -> list[dict]:
    by_date: dict[date, list[dict]] = {}
    for item in items:
        by_date.setdefault(item["trade_date"], []).append(item)

    ranked: list[dict] = []
    for trade_date in sorted(by_date):
        day_signals = [item["signal"] for item in by_date[trade_date]]
        top_signals = sort_top_signals(day_signals)[:MAX_DAILY_SIGNALS]
        top_codes = {signal["Code"] for signal in top_signals}
        ranked.extend(item for item in by_date[trade_date] if item["signal"]["Code"] in top_codes)
    return ranked


def rank_daily_signal_records(items: list[dict]) -> list[dict]:
    by_date: dict[str, list[dict]] = {}
    for item in items:
        by_date.setdefault(str(item["trade_date"]), []).append(item)

    ranked: list[dict] = []
    for trade_date in sorted(by_date):
        day_signals = sorted(by_date[trade_date], key=lambda item: float(item.get("score") or 0), reverse=True)
        ranked.extend(day_signals[:MAX_DAILY_SIGNALS])
    return ranked


def simulate_signal_safe(row: dict) -> dict | None:
    try:
        return simulate_signal(row)
    except Exception as exc:
        logger.warning("Backtest skipped signal: code=%s trade_date=%s error=%s", row.get("code"), row.get("trade_date"), exc)
        return None


def simulate_signal(row: dict) -> dict | None:
    entry_date = date.fromisoformat(str(row["trade_date"]))
    start = entry_date.strftime("%Y-%m-%d")
    end = (entry_date + timedelta(days=FORWARD_DAYS)).strftime("%Y-%m-%d")
    frame = fdr.DataReader(str(row["code"]).zfill(6), start=start, end=end)
    return simulate_signal_with_frame(row, frame)


def simulate_generated_signal_safe(item: dict) -> dict | None:
    try:
        return simulate_generated_signal(item)
    except Exception as exc:
        signal = item.get("signal") or {}
        logger.warning("Backtest skipped generated signal: code=%s trade_date=%s error=%s", signal.get("Code"), item.get("trade_date"), exc)
        return None


def simulate_generated_signal(item: dict) -> dict | None:
    trade_date: date = item["trade_date"]
    signal: dict = item["signal"]
    row = shared_signal_to_record(trade_date, signal)
    return simulate_signal_with_frame(row, item["forward_frame"])


def simulate_signal_with_frame(row: dict, frame: pd.DataFrame) -> dict | None:
    if frame is None or frame.empty:
        return None

    entry = float(row["entry"])
    stop_loss = float(row["stop_loss"])
    take_profit_1 = float(row["take_profit_1"])
    take_profit_2 = float(row["take_profit_2"])
    raw = row.get("raw") or {}
    hold_max_days = int(raw.get("HoldMaxDays") or 15)

    remaining = 1.0
    realized = 0.0
    tp1_done = False
    tp2_done = False
    close_reason = "DataEnd"
    last_close = entry
    hold_days = 0
    event_log: list[dict] = []
    target_exit_price = entry

    for index, (_, candle) in enumerate(frame.iterrows()):
        if index == 0:
            continue
        hold_days = index
        high = float(candle["High"])
        low = float(candle["Low"])
        last_close = float(candle["Close"])

        if low <= stop_loss:
            realized += remaining * ((stop_loss / entry - 1) * 100)
            target_exit_price = stop_loss
            remaining = 0
            close_reason = "StopLossAfterTakeProfit" if tp1_done or tp2_done else "StopLoss"
            event_log.append({"day": hold_days, "event": close_reason, "price": round(stop_loss, 2), "remaining": 0})
            break
        if not tp1_done and high >= take_profit_1:
            realized += 0.3 * ((take_profit_1 / entry - 1) * 100)
            remaining -= 0.3
            tp1_done = True
            event_log.append({"day": hold_days, "event": "TakeProfit1", "price": round(take_profit_1, 2), "sold": 0.3, "remaining": round(remaining, 2)})
        if not tp2_done and high >= take_profit_2:
            sell_part = min(0.3, remaining)
            realized += sell_part * ((take_profit_2 / entry - 1) * 100)
            remaining -= sell_part
            tp2_done = True
            event_log.append({"day": hold_days, "event": "TakeProfit2", "price": round(take_profit_2, 2), "sold": round(sell_part, 2), "remaining": round(remaining, 2)})
            if remaining <= 0:
                target_exit_price = take_profit_2
                close_reason = "TakeProfit2"
                break
        if hold_days >= hold_max_days:
            close_reason = "MaxHoldAfterTakeProfit" if tp1_done or tp2_done else "MaxHold"
            event_log.append({"day": hold_days, "event": close_reason, "price": round(last_close, 2), "remaining": round(remaining, 2)})
            break

    if remaining > 0:
        realized += remaining * ((last_close / entry - 1) * 100)
        target_exit_price = last_close
        if close_reason == "DataEnd":
            event_log.append({"day": hold_days, "event": "DataEnd", "price": round(last_close, 2), "remaining": round(remaining, 2)})

    return {
        "trade_date": row["trade_date"],
        "entry_date": row["trade_date"],
        "code": row["code"],
        "name": row.get("name"),
        "score": row.get("score"),
        "entry": round(entry, 2),
        "exit_price": round(target_exit_price, 2),
        "return_pct": round(realized, 2),
        "hold_days": hold_days,
        "exit_reason": close_reason,
        "tp1_done": tp1_done,
        "tp2_done": tp2_done,
        "remaining_qty_ratio": round(remaining, 2),
        "events": event_log,
    }


def summarize_trades(days: int, trades: list[dict], *, source: str, generated_signals: int, skipped_symbols: int) -> dict:
    wins = [trade for trade in trades if trade["return_pct"] > 0]
    losses = [trade for trade in trades if trade["return_pct"] <= 0]
    total_return = sum(trade["return_pct"] for trade in trades)
    return {
        "source": source,
        "days": days,
        "generated_signals": generated_signals,
        "skipped_symbols": skipped_symbols,
        "signals_tested": len(trades),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": round(len(wins) / len(trades) * 100, 2) if trades else 0,
        "avg_return_pct": round(total_return / len(trades), 2) if trades else 0,
        "avg_win_pct": round(sum(item["return_pct"] for item in wins) / len(wins), 2) if wins else 0,
        "avg_loss_pct": round(sum(item["return_pct"] for item in losses) / len(losses), 2) if losses else 0,
        "best_return_pct": round(max((item["return_pct"] for item in trades), default=0), 2),
        "worst_return_pct": round(min((item["return_pct"] for item in trades), default=0), 2),
        "avg_hold_days": round(sum(item["hold_days"] for item in trades) / len(trades), 2) if trades else 0,
        "trades": sorted(trades, key=lambda item: item["entry_date"], reverse=True)[:50],
    }


def empty_result(days: int, source: str, error: str) -> dict:
    result = summarize_trades(days, [], source=source, generated_signals=0, skipped_symbols=0)
    result["error"] = error
    return result


def truthy(value: object) -> bool:
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "y"}
    return bool(value)
