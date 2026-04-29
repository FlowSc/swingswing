from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import FinanceDataReader as fdr
import pandas as pd

from app.core.config import get_settings
from app.services.supabase_rest import SupabaseRest
from app.services.telegram import send_telegram_message


logger = logging.getLogger(__name__)
TOP_N = 30
SCAN_CHUNK_SIZE = 100
MIN_VOLUME_20D = 20000
MIN_PRICE = 1000
MIN_TRADING_VALUE_20D = 300_000_000
KOSPI_MARKET_CAP_LIMIT = 1000
RSI_MIN = 30
RSI_MAX_EXCLUSIVE = 56
MIN_RET_20D = 3
MAX_RET_20D = 25
MAX_STOP_PCT = 10.0
MIN_BB_WIDTH_EXPANSION_PCT = 5.0
MIN_BB_WIDTH_EXPANSION_HARD_PCT = 0.0
MIN_VOLUME_RATIO_HARD = 1.0
MIN_VOLUME_SPIKE_RATIO = 1.2
STRONG_VOLUME_SPIKE_RATIO = 1.5
MAX_DAYS_AFTER_ICHIMOKU_CROSS = 5
HOLD_MIN_DAYS = 3
HOLD_PREFERRED_DAYS = 7
HOLD_MAX_DAYS = 15
EXCLUDED_NAME_KEYWORDS = ("스팩", "리츠", "우")


def is_excluded_name(name: str) -> bool:
    return any(keyword in name for keyword in EXCLUDED_NAME_KEYWORDS)


def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    return (100 - (100 / (1 + rs))).fillna(0)


def prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    frame = df.copy()
    frame["MA5"] = frame["Close"].rolling(5).mean()
    frame["MA20"] = frame["Close"].rolling(20).mean()
    frame["MA60"] = frame["Close"].rolling(60).mean()
    frame["MA20_prev5"] = frame["MA20"].shift(5)
    frame["RSI14"] = calc_rsi(frame["Close"], 14)
    frame["Ret_5D"] = frame["Close"].pct_change(5) * 100
    frame["Ret_20D"] = frame["Close"].pct_change(20) * 100
    frame["Vol20"] = frame["Volume"].rolling(20).mean()
    frame["Vol5"] = frame["Volume"].rolling(5).mean()
    frame["VolPrev5"] = frame["Volume"].shift(1).rolling(5).mean()
    frame["Tenkan"] = (frame["High"].rolling(9).max() + frame["Low"].rolling(9).min()) / 2
    frame["Kijun"] = (frame["High"].rolling(26).max() + frame["Low"].rolling(26).min()) / 2
    frame["TenkanPrev"] = frame["Tenkan"].shift(1)
    frame["KijunPrev"] = frame["Kijun"].shift(1)
    frame["IchimokuBullCross"] = (frame["Tenkan"] > frame["Kijun"]) & (frame["TenkanPrev"] <= frame["KijunPrev"])
    frame["BBMiddle"] = frame["Close"].rolling(20).mean()
    bb_std = frame["Close"].rolling(20).std()
    frame["BBUpper"] = frame["BBMiddle"] + bb_std * 2
    frame["BBLower"] = frame["BBMiddle"] - bb_std * 2
    frame["BBWidthPct"] = (frame["BBUpper"] - frame["BBLower"]) / frame["BBMiddle"] * 100
    frame["BBWidthPrev5"] = frame["BBWidthPct"].shift(5)
    frame["BBExpansionPct"] = (frame["BBWidthPct"] - frame["BBWidthPrev5"]) / frame["BBWidthPrev5"] * 100
    frame["Low52W"] = frame["Low"].rolling(252).min()
    candle_range = (frame["High"] - frame["Low"]).replace(0, pd.NA)
    frame["BodyRatioPct"] = (frame["Close"] - frame["Open"]).abs() / candle_range * 100
    prev_close = frame["Close"].shift(1)
    true_range = pd.concat(
        [
            frame["High"] - frame["Low"],
            (frame["High"] - prev_close).abs(),
            (frame["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    frame["ATR14"] = true_range.rolling(14).mean()
    return frame


def score_swing_setup(
    frame: pd.DataFrame,
    code: str,
    name: str,
    *,
    market_filter_ok: bool,
    universe: str,
) -> dict | None:
    if frame is None or len(frame) < 260:
        return None
    if is_excluded_name(name):
        return None

    frame = prepare_frame(frame).dropna()
    if frame.empty:
        return None

    last = frame.iloc[-1]
    prev = frame.iloc[-2]

    close = float(last["Close"])
    open_ = float(last["Open"])
    high = float(last["High"])
    low = float(last["Low"])
    ma5 = float(last["MA5"])
    ma20 = float(last["MA20"])
    ma60 = float(last["MA60"])
    rsi = float(last["RSI14"])
    ret_5d = float(last["Ret_5D"])
    ret_20d = float(last["Ret_20D"])
    vol20 = float(last["Vol20"])
    vol_prev5 = float(last["VolPrev5"])
    atr14 = float(last["ATR14"])
    prev_close = float(prev["Close"])
    ma20_prev5 = float(last["MA20_prev5"])
    tenkan = float(last["Tenkan"])
    kijun = float(last["Kijun"])
    bb_upper = float(last["BBUpper"])
    bb_lower = float(last["BBLower"])
    bb_width = float(last["BBWidthPct"])
    bb_expansion = float(last["BBExpansionPct"])
    low_52w = float(last["Low52W"])
    body_ratio = float(last["BodyRatioPct"])

    if ma20 <= 0 or ma60 <= 0 or vol20 <= 0 or vol_prev5 <= 0 or kijun <= 0 or low_52w <= 0:
        return None
    if close < MIN_PRICE:
        return None
    trading_value_20d = close * vol20
    if trading_value_20d < MIN_TRADING_VALUE_20D:
        return None

    distance_to_ma20 = (close - ma20) / ma20 * 100
    distance_to_kijun = (close - kijun) / kijun * 100
    days_after_cross = None
    recent_cross = frame["IchimokuBullCross"].tail(MAX_DAYS_AFTER_ICHIMOKU_CROSS + 1)
    if bool(recent_cross.any()):
        days_after_cross = list(reversed(recent_cross.tolist())).index(True)

    score = 0
    reasons: list[str] = []
    scoring_rules = [
        (ma20 > ma60, 2, "MA20 > MA60"),
        (ma20_prev5 > 0 and ma20 > ma20_prev5, 1, "MA20 rising"),
        (tenkan > kijun, 2, "Tenkan > Kijun"),
        (days_after_cross is not None, 3, "Ichimoku cross"),
        (close >= prev_close, 1, "Bullish close"),
        (0 <= distance_to_kijun <= 10, 1, "Near Kijun"),
        (RSI_MIN <= rsi < RSI_MAX_EXCLUSIVE, 3, "RSI rebound zone"),
        (0 <= ret_5d <= 10, 1, "5D momentum ok"),
        (MIN_RET_20D <= ret_20d <= MAX_RET_20D, 1, "20D momentum ok"),
        (bb_expansion >= MIN_BB_WIDTH_EXPANSION_PCT, 3, "BB expanding"),
        (trading_value_20d >= MIN_TRADING_VALUE_20D, 2, "Enough trading value"),
        (float(last["Volume"]) >= vol_prev5 * MIN_VOLUME_SPIKE_RATIO, 2, "Volume spike"),
        (float(last["Volume"]) >= vol_prev5 * STRONG_VOLUME_SPIKE_RATIO, 1, "Strong volume spike"),
        (market_filter_ok, 2, "KOSPI above MA5"),
        (universe in {"KOSPI_TOP500", "KOSDAQ150"}, 2, universe),
    ]
    for passed, points, reason in scoring_rules:
        if passed:
            score += points
            reasons.append(reason)

    if tenkan <= kijun:
        return None
    if bb_expansion < MIN_BB_WIDTH_EXPANSION_HARD_PCT:
        return None
    if not (RSI_MIN <= rsi < RSI_MAX_EXCLUSIVE):
        return None
    if not market_filter_ok:
        return None
    if vol20 < MIN_VOLUME_20D:
        return None
    if float(last["Volume"]) < vol_prev5 * MIN_VOLUME_RATIO_HARD:
        return None

    swing_low = float(frame["Low"].tail(10).min())
    stop_loss = min(swing_low, ma60) * 0.99
    risk = max(close - stop_loss, 0.01)
    stop_pct = risk / close * 100
    if stop_pct > MAX_STOP_PCT:
        return None

    take_profit_1 = close + risk
    take_profit_2 = close + risk * 2
    ma20_trail = ma20 * 0.995
    atr_trail = close - max(atr14 * 1.5, risk * 0.8)
    trailing_stop = max(stop_loss, ma20_trail, atr_trail)

    return {
        "Code": code,
        "Name": name,
        "Entry": round(close, 2),
        "StopLoss": round(stop_loss, 2),
        "TakeProfit1": round(take_profit_1, 2),
        "TakeProfit2": round(take_profit_2, 2),
        "TrailingStop": round(trailing_stop, 2),
        "RiskPct": round(risk / close * 100, 2),
        "StopPct": round(stop_pct, 2),
        "HoldMinDays": HOLD_MIN_DAYS,
        "HoldPreferredDays": HOLD_PREFERRED_DAYS,
        "HoldMaxDays": HOLD_MAX_DAYS,
        "RSI14": round(rsi, 1),
        "ATR14": round(atr14, 2),
        "Tenkan": round(tenkan, 2),
        "Kijun": round(kijun, 2),
        "DaysAfterIchimokuCross": days_after_cross,
        "DistanceToKijun(%)": round(distance_to_kijun, 2),
        "BBUpper": round(bb_upper, 2),
        "BBLower": round(bb_lower, 2),
        "BBWidth(%)": round(bb_width, 2),
        "BBExpansion(%)": round(bb_expansion, 2),
        "VolumeSpikeRatio": round(float(last["Volume"]) / vol_prev5, 2),
        "BodyRatio(%)": round(body_ratio, 2),
        "Low52W": round(low_52w, 2),
        "DistanceFrom52WLow(%)": round((close / low_52w - 1) * 100, 2),
        "MarketFilter": "KOSPI close > MA5",
        "Universe": universe,
        "Ret_5D(%)": round(ret_5d, 2),
        "Ret_20D(%)": round(ret_20d, 2),
        "DistanceToMA20(%)": round(distance_to_ma20, 2),
        "Vol20": int(vol20),
        "TradingValue20D": int(trading_value_20d),
        "Score": score,
        "Reasons": ", ".join(reasons[:8]),
    }


def kospi_market_filter_ok(base_date: date) -> bool:
    start = (datetime.combine(base_date, datetime.min.time()) - timedelta(days=40)).strftime("%Y-%m-%d")
    frame = fdr.DataReader("KS11", start=start)
    if frame is None or len(frame) < 5:
        return False
    close = frame["Close"]
    return bool(float(close.iloc[-1]) > float(close.rolling(5).mean().iloc[-1]))


def _normalize_listing(listing: pd.DataFrame, universe: str) -> pd.DataFrame:
    frame = listing.copy()
    if "Code" not in frame.columns and "Symbol" in frame.columns:
        frame["Code"] = frame["Symbol"]
    if "Name" not in frame.columns:
        frame["Name"] = frame["Code"]
    frame["Code"] = frame["Code"].astype(str).str.zfill(6)
    frame["Universe"] = universe
    return frame[["Code", "Name", "Universe"]].drop_duplicates("Code")


def load_scan_universe() -> pd.DataFrame:
    logger.warning("Loading scan universe")
    kospi = fdr.StockListing("KOSPI")
    if "Marcap" in kospi.columns:
        kospi = kospi.sort_values("Marcap", ascending=False).head(KOSPI_MARKET_CAP_LIMIT)
    else:
        kospi = kospi.head(KOSPI_MARKET_CAP_LIMIT)
    frames = [_normalize_listing(kospi, "KOSPI_TOP500")]

    try:
        kosdaq150 = fdr.StockListing("KOSDAQ150")
        frames.append(_normalize_listing(kosdaq150, "KOSDAQ150"))
    except Exception:
        pass

    universe = pd.concat(frames, ignore_index=True).drop_duplicates("Code")
    logger.warning("Loaded scan universe: %s symbols", len(universe))
    return universe


def sort_top_signals(results: list[dict]) -> list[dict]:
    results.sort(
        key=lambda item: (
            item.get("Score", 0),
            item.get("BBExpansion(%)", 0),
            item.get("Ret_20D(%)", 0),
            -item.get("DistanceToMA20(%)", 999),
        ),
        reverse=True,
    )
    return results[:TOP_N]


def prepare_chunked_scan_state_sync(today: date | None = None) -> dict:
    base_date = today or datetime.now(ZoneInfo(get_settings().timezone)).date()
    logger.warning("Signal scan universe load started: date=%s", base_date.isoformat())
    universe = load_scan_universe()
    logger.warning("Signal scan market filter started")
    market_ok = kospi_market_filter_ok(base_date)
    logger.warning("Signal scan market filter completed: market_ok=%s", market_ok)
    start = (datetime.combine(base_date, datetime.min.time()) - timedelta(days=420)).strftime("%Y-%m-%d")
    return {
        "trade_date": base_date.isoformat(),
        "universe": universe.to_dict("records"),
        "market_ok": market_ok,
        "start": start,
        "offset": 0,
        "total": len(universe),
        "candidates": [],
        "done": False,
    }


async def prepare_chunked_scan_state(today: date | None = None) -> dict:
    return await asyncio.to_thread(prepare_chunked_scan_state_sync, today)


def process_scan_chunk_sync(state: dict, chunk_size: int = SCAN_CHUNK_SIZE) -> dict:
    universe = state.get("universe") or []
    offset = int(state.get("offset") or 0)
    total = len(universe)
    end = min(offset + chunk_size, total)
    results: list[dict] = list(state.get("candidates") or [])

    logger.warning("Signal scan chunk started: %s-%s/%s candidates=%s", offset + 1, end, total, len(results))
    for index, row in enumerate(universe[offset:end], start=offset + 1):
        try:
            if index == offset + 1 or index % 25 == 0:
                logger.warning("Signal scan chunk progress: %s/%s candidates=%s", index, total, len(results))
            raw = fdr.DataReader(row["Code"], start=state["start"])
            result = score_swing_setup(
                raw,
                row["Code"],
                row["Name"],
                market_filter_ok=bool(state["market_ok"]),
                universe=row["Universe"],
            )
            if result:
                results.append(result)
        except Exception:
            logger.debug("Signal scan skipped code=%s", row.get("Code"), exc_info=True)
            continue

    done = end >= total
    next_state = {
        **state,
        "offset": end,
        "total": total,
        "candidates": results,
        "done": done,
    }
    logger.warning("Signal scan chunk completed: offset=%s/%s candidates=%s done=%s", end, total, len(results), done)
    return next_state


async def process_scan_chunk(state: dict, chunk_size: int = SCAN_CHUNK_SIZE) -> dict:
    return await asyncio.to_thread(process_scan_chunk_sync, state, chunk_size)


async def finalize_chunked_scan(user_id: str, state: dict, telegram_chat_id: str | None = None) -> dict:
    trade_date = date.fromisoformat(state["trade_date"])
    signals = sort_top_signals(list(state.get("candidates") or []))
    saved = await save_user_signals(user_id, signals, trade_date)
    shared_saved = await save_shared_signals(signals, trade_date)
    await send_telegram_message(telegram_chat_id, format_top_signals_message(signals, trade_date))
    return {"trade_date": trade_date.isoformat(), "signals": len(signals), "saved": saved, "shared_saved": shared_saved}


def scan_kospi_signals_sync(today: date | None = None) -> list[dict]:
    state = prepare_chunked_scan_state_sync(today)
    results: list[dict] = []

    total = len(state["universe"])
    for index, row in enumerate(state["universe"], start=1):
        try:
            if index == 1 or index % 50 == 0:
                logger.warning("Signal scan progress: %s/%s candidates=%s", index, total, len(results))
            raw = fdr.DataReader(row["Code"], start=state["start"])
            result = score_swing_setup(
                raw,
                row["Code"],
                row["Name"],
                market_filter_ok=bool(state["market_ok"]),
                universe=row["Universe"],
            )
            if result:
                results.append(result)
        except Exception:
            logger.debug("Signal scan skipped code=%s", row.get("Code"), exc_info=True)
            continue

    logger.warning("Signal scan scoring completed: scanned=%s candidates=%s", total, len(results))
    return sort_top_signals(results)


async def scan_kospi_signals(today: date | None = None) -> list[dict]:
    return await asyncio.to_thread(scan_kospi_signals_sync, today)


def signal_to_record(user_id: str, trade_date: date, signal: dict) -> dict:
    return {
        "user_id": user_id,
        "trade_date": trade_date.isoformat(),
        "code": signal["Code"],
        "name": signal["Name"],
        "entry": signal["Entry"],
        "stop_loss": signal["StopLoss"],
        "take_profit_1": signal["TakeProfit1"],
        "take_profit_2": signal["TakeProfit2"],
        "trailing_stop": signal["TrailingStop"],
        "score": signal["Score"],
        "raw": signal,
    }


def shared_signal_to_record(trade_date: date, signal: dict) -> dict:
    return {
        "trade_date": trade_date.isoformat(),
        "code": signal["Code"],
        "name": signal["Name"],
        "entry": signal["Entry"],
        "stop_loss": signal["StopLoss"],
        "take_profit_1": signal["TakeProfit1"],
        "take_profit_2": signal["TakeProfit2"],
        "trailing_stop": signal["TrailingStop"],
        "score": signal["Score"],
        "raw": signal,
    }


async def save_user_signals(user_id: str, signals: list[dict], trade_date: date | None = None) -> int:
    today = trade_date or datetime.now(ZoneInfo(get_settings().timezone)).date()
    rest = SupabaseRest()
    count = 0
    for signal in signals:
        await rest.upsert("signals", signal_to_record(user_id, today, signal), on_conflict="trade_date,user_id,code")
        count += 1
    return count


async def save_shared_signals(signals: list[dict], trade_date: date | None = None) -> int:
    today = trade_date or datetime.now(ZoneInfo(get_settings().timezone)).date()
    rest = SupabaseRest()
    count = 0
    for signal in signals:
        await rest.upsert("shared_signals", shared_signal_to_record(today, signal), on_conflict="trade_date,code")
        count += 1
    return count


def format_top_signals_message(signals: list[dict], trade_date: date) -> str:
    lines = [f"KOSPI Swing Top {min(5, len(signals))} - {trade_date.isoformat()}"]
    if not signals:
        lines.append("No candidates today.")
        return "\n".join(lines)
    for index, signal in enumerate(signals[:5], start=1):
        lines.append(
            f"{index}. {signal['Name']}({signal['Code']}) "
            f"entry {signal['Entry']:,.0f} stop {signal['StopLoss']:,.0f} "
            f"tp2 {signal['TakeProfit2']:,.0f} score {signal['Score']}"
        )
    return "\n".join(lines)


async def scan_and_store_for_user(user_id: str, telegram_chat_id: str | None = None) -> dict:
    trade_date = datetime.now(ZoneInfo(get_settings().timezone)).date()
    signals = await scan_kospi_signals(trade_date)
    saved = await save_user_signals(user_id, signals, trade_date)
    shared_saved = await save_shared_signals(signals, trade_date)
    await send_telegram_message(telegram_chat_id, format_top_signals_message(signals, trade_date))
    return {"trade_date": trade_date.isoformat(), "signals": len(signals), "saved": saved, "shared_saved": shared_saved}
