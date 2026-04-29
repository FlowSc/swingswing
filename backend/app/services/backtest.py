from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import FinanceDataReader as fdr

from app.core.config import get_settings
from app.services.supabase_rest import SupabaseRest


logger = logging.getLogger(__name__)


async def run_shared_signal_backtest(days: int = 120, max_signals: int = 200) -> dict:
    return await asyncio.to_thread(run_shared_signal_backtest_sync, days, max_signals)


def run_shared_signal_backtest_sync(days: int = 120, max_signals: int = 200) -> dict:
    end = datetime.now(ZoneInfo(get_settings().timezone)).date()
    start = end - timedelta(days=days)
    rows = asyncio.run(_load_signal_rows(start.isoformat(), max_signals))
    trades = [trade for row in rows if (trade := simulate_signal_safe(row))]
    wins = [trade for trade in trades if trade["return_pct"] > 0]
    losses = [trade for trade in trades if trade["return_pct"] <= 0]
    total_return = sum(trade["return_pct"] for trade in trades)
    return {
        "days": days,
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


async def _load_signal_rows(start_date: str, max_signals: int) -> list[dict]:
    return await SupabaseRest().select(
        "shared_signals",
        filters={"trade_date": f"gte.{start_date}"},
        order="trade_date.desc,score.desc",
        limit=max_signals,
    )


def simulate_signal_safe(row: dict) -> dict | None:
    try:
        return simulate_signal(row)
    except Exception as exc:
        logger.warning("Backtest skipped signal: code=%s trade_date=%s error=%s", row.get("code"), row.get("trade_date"), exc)
        return None


def simulate_signal(row: dict) -> dict | None:
    entry_date = date.fromisoformat(row["trade_date"])
    start = entry_date.strftime("%Y-%m-%d")
    end = (entry_date + timedelta(days=30)).strftime("%Y-%m-%d")
    frame = fdr.DataReader(str(row["code"]).zfill(6), start=start, end=end)
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
    last_close = entry
    exit_reason = "MaxHold"
    hold_days = 0

    for index, (_, candle) in enumerate(frame.iterrows()):
        if index == 0:
            continue
        hold_days = index
        high = float(candle["High"])
        low = float(candle["Low"])
        last_close = float(candle["Close"])

        if low <= stop_loss:
            realized += remaining * ((stop_loss / entry - 1) * 100)
            remaining = 0
            exit_reason = "StopLoss"
            break
        if not tp1_done and high >= take_profit_1:
            realized += 0.3 * ((take_profit_1 / entry - 1) * 100)
            remaining -= 0.3
            tp1_done = True
        if not tp2_done and high >= take_profit_2:
            sell_part = min(0.3, remaining)
            realized += sell_part * ((take_profit_2 / entry - 1) * 100)
            remaining -= sell_part
            tp2_done = True
        if hold_days >= hold_max_days:
            exit_reason = "MaxHold"
            break

    if remaining > 0:
        realized += remaining * ((last_close / entry - 1) * 100)

    return {
        "trade_date": row["trade_date"],
        "entry_date": row["trade_date"],
        "code": row["code"],
        "name": row.get("name"),
        "score": row.get("score"),
        "entry": round(entry, 2),
        "exit_price": round(last_close, 2),
        "return_pct": round(realized, 2),
        "hold_days": hold_days,
        "exit_reason": exit_reason,
    }
