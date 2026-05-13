from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import FinanceDataReader as fdr
import pandas as pd

from app.core.config import get_settings
from app.services.ai_report import send_daily_signal_report
from app.services.broker_credentials import list_telegram_recipients
from app.services.company_profile import company_profile_from_row, enrich_company_profile
from app.services.supabase_rest import SupabaseRest
from app.services.telegram import send_telegram_message, send_telegram_message_with_bot


logger = logging.getLogger(__name__)
TOP_N = 30
SCAN_CHUNK_SIZE = 100
MIN_VOLUME_20D = 20000
MIN_PRICE = 1000
MIN_TRADING_VALUE_20D = 300_000_000
KOSPI_MARKET_CAP_LIMIT = 1000
SCAN_UNIVERSE_LIMITED = "limited"
SCAN_UNIVERSE_ALL = "all"
RSI_MIN = 30
RSI_MAX_EXCLUSIVE = 56
CLOUD_RSI_MIN = 35
CLOUD_RSI_MAX_EXCLUSIVE = 72
MIN_RET_20D = 3
MAX_RET_20D = 25
DEFAULT_STOP_PCT = 4.0
MAX_STOP_PCT = 10.0
MIN_BB_WIDTH_EXPANSION_PCT = 5.0
MIN_BB_WIDTH_EXPANSION_HARD_PCT = 0.0
MIN_VOLUME_RATIO_HARD = 1.0
MIN_VOLUME_SPIKE_RATIO = 1.2
STRONG_VOLUME_SPIKE_RATIO = 1.5
MIN_TRADING_VALUE_SPIKE_RATIO = 1.2
GAP_UP_PENALTY_PCT = 5.0
MAX_PREV_DAY_RETURN_PCT = 12.0
MAX_INTRADAY_DROP_PCT = -5.0
MAX_PULLBACK_FROM_DAY_HIGH_PCT = 10.0
UPPER_SHADOW_PENALTY_RATIO = 0.5
MIN_ATR_PCT_BONUS = 2.0
MAX_ATR_PCT_BONUS = 12.0
MIN_RELATIVE_STRENGTH_20D = 3.0
MAX_DAYS_AFTER_ICHIMOKU_CROSS = 5
CLOUD_SUPPORT_TOLERANCE_PCT = 3.0
CLOUD_BREAKOUT_DISTANCE_PCT = 3.0
HOLD_MIN_DAYS = 3
HOLD_PREFERRED_DAYS = 7
HOLD_MAX_DAYS = 15
FORWARD_RETURN_HORIZONS = (3, 5, 7, 15)
FORWARD_RETURN_UPDATE_LIMIT = 300
EXCLUDED_NAME_KEYWORDS = ("스팩", "리츠")
PREFERRED_SHARE_SUFFIXES = ("우", "우B", "우C")


def get_scan_market_status(today: date | None = None) -> dict:
    base_date = today or datetime.now(ZoneInfo(get_settings().timezone)).date()
    if base_date.weekday() >= 5:
        return {
            "is_open": False,
            "trade_date": base_date.isoformat(),
            "reason": "weekend",
            "message": "주말은 국내 증시 휴장일이라 시그널 스캔을 실행하지 않습니다.",
        }

    start = (datetime.combine(base_date, datetime.min.time()) - timedelta(days=10)).strftime("%Y-%m-%d")
    try:
        frame = fdr.DataReader("KS11", start=start)
    except Exception as exc:
        logger.warning("Market open check failed: date=%s error=%s", base_date.isoformat(), exc)
        return {
            "is_open": False,
            "trade_date": base_date.isoformat(),
            "reason": "market_data_unavailable",
            "message": "KOSPI 지수 데이터를 확인하지 못해 시그널 스캔을 보류합니다.",
        }

    if frame is None or frame.empty:
        return {
            "is_open": False,
            "trade_date": base_date.isoformat(),
            "reason": "market_data_empty",
            "message": "오늘 KOSPI 지수 데이터가 없어 시그널 스캔을 실행하지 않습니다.",
        }

    latest_date = pd.Timestamp(frame.index[-1]).date()
    if latest_date != base_date:
        return {
            "is_open": False,
            "trade_date": base_date.isoformat(),
            "latest_market_date": latest_date.isoformat(),
            "reason": "market_closed",
            "message": "오늘 장이 열리지 않았거나 아직 KOSPI 지수 데이터가 없어 시그널 스캔을 실행하지 않습니다.",
        }

    return {
        "is_open": True,
        "trade_date": base_date.isoformat(),
        "latest_market_date": latest_date.isoformat(),
        "reason": "market_open",
        "message": "오늘 국내 증시 거래가 확인되어 시그널 스캔을 실행할 수 있습니다.",
    }


def is_excluded_name(name: str) -> bool:
    normalized = str(name or "").strip()
    if any(keyword in normalized for keyword in EXCLUDED_NAME_KEYWORDS):
        return True
    return normalized.endswith(PREFERRED_SHARE_SUFFIXES)


def record_reject(reject_counts: dict[str, int] | None, reason: str) -> None:
    if reject_counts is not None:
        reject_counts[reason] = int(reject_counts.get(reason) or 0) + 1


def latest_frame_date(frame: pd.DataFrame) -> date | None:
    if frame.empty:
        return None
    try:
        return pd.Timestamp(frame.index[-1]).date()
    except Exception:
        return None


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
    frame["TradingValue"] = frame["Close"] * frame["Volume"]
    frame["TradingValue20"] = frame["TradingValue"].rolling(20).mean()
    frame["Tenkan"] = (frame["High"].rolling(9).max() + frame["Low"].rolling(9).min()) / 2
    frame["Kijun"] = (frame["High"].rolling(26).max() + frame["Low"].rolling(26).min()) / 2
    frame["TenkanPrev"] = frame["Tenkan"].shift(1)
    frame["KijunPrev"] = frame["Kijun"].shift(1)
    frame["IchimokuBullCross"] = (frame["Tenkan"] > frame["Kijun"]) & (frame["TenkanPrev"] <= frame["KijunPrev"])
    senkou_base_b = (frame["High"].rolling(52).max() + frame["Low"].rolling(52).min()) / 2
    frame["SenkouSpanA"] = ((frame["Tenkan"] + frame["Kijun"]) / 2).shift(26)
    frame["SenkouSpanB"] = senkou_base_b.shift(26)
    frame["CloudUpper"] = frame[["SenkouSpanA", "SenkouSpanB"]].max(axis=1)
    frame["CloudLower"] = frame[["SenkouSpanA", "SenkouSpanB"]].min(axis=1)
    frame["CloudBullish"] = frame["SenkouSpanA"] > frame["SenkouSpanB"]
    frame["CloudBearish"] = frame["SenkouSpanA"] < frame["SenkouSpanB"]
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
    frame["UpperShadowRatio"] = (frame["High"] - frame[["Open", "Close"]].max(axis=1)) / candle_range
    frame["GapPct"] = (frame["Open"] / frame["Close"].shift(1) - 1) * 100
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
    market_ret_20d: float = 0.0,
    company_profile: dict | None = None,
    core_universe: bool = False,
    core_universe_type: str = "",
    trade_date: date | None = None,
    reject_counts: dict[str, int] | None = None,
) -> dict | None:
    if frame is None or len(frame) < 260:
        record_reject(reject_counts, "data_short")
        return None
    if is_excluded_name(name):
        record_reject(reject_counts, "excluded_name")
        return None

    frame = prepare_frame(frame).dropna()
    if frame.empty:
        record_reject(reject_counts, "indicator_na")
        return None
    if trade_date and latest_frame_date(frame) != trade_date:
        record_reject(reject_counts, "stale_market_data")
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
    trading_value = float(last["TradingValue"])
    trading_value20 = float(last["TradingValue20"])
    atr14 = float(last["ATR14"])
    prev_close = float(prev["Close"])
    ma20_prev5 = float(last["MA20_prev5"])
    tenkan = float(last["Tenkan"])
    kijun = float(last["Kijun"])
    bb_upper = float(last["BBUpper"])
    bb_lower = float(last["BBLower"])
    bb_width = float(last["BBWidthPct"])
    bb_expansion = float(last["BBExpansionPct"])
    senkou_a = float(last["SenkouSpanA"])
    senkou_b = float(last["SenkouSpanB"])
    cloud_upper = float(last["CloudUpper"])
    cloud_lower = float(last["CloudLower"])
    cloud_bullish = bool(last["CloudBullish"])
    cloud_bearish = bool(last["CloudBearish"])
    low_52w = float(last["Low52W"])
    body_ratio = float(last["BodyRatioPct"])
    upper_shadow_ratio = float(last["UpperShadowRatio"])
    gap_pct = float(last["GapPct"])
    prev_day_return_pct = (prev_close / float(frame.iloc[-3]["Close"]) - 1) * 100 if len(frame) >= 3 and float(frame.iloc[-3]["Close"]) > 0 else 0
    intraday_return_pct = (close / open_ - 1) * 100 if open_ > 0 else 0
    pullback_from_day_high_pct = (close / high - 1) * 100 if high > 0 else 0

    if ma20 <= 0 or ma60 <= 0 or vol20 <= 0 or vol_prev5 <= 0 or kijun <= 0 or low_52w <= 0:
        record_reject(reject_counts, "invalid_indicator")
        return None
    if open_ <= 0 or close <= 0 or high <= 0 or low <= 0:
        record_reject(reject_counts, "invalid_ohlc")
        return None
    if float(last["Volume"]) <= 0 or trading_value <= 0:
        record_reject(reject_counts, "invalid_volume_or_value")
        return None
    if close < MIN_PRICE:
        record_reject(reject_counts, "price_too_low")
        return None
    trading_value_20d = close * vol20
    if trading_value_20d < MIN_TRADING_VALUE_20D:
        record_reject(reject_counts, "trading_value_too_low")
        return None
    if intraday_return_pct <= MAX_INTRADAY_DROP_PCT:
        record_reject(reject_counts, "intraday_drop")
        return None
    if pullback_from_day_high_pct <= -MAX_PULLBACK_FROM_DAY_HIGH_PCT:
        record_reject(reject_counts, "pullback_from_day_high")
        return None

    atr_pct = atr14 / close * 100
    relative_strength_20d = ret_20d - market_ret_20d
    trading_value_spike_ratio = trading_value / trading_value20 if trading_value20 > 0 else 0
    distance_to_ma20 = (close - ma20) / ma20 * 100
    distance_to_kijun = (close - kijun) / kijun * 100
    distance_to_cloud_upper = (close - cloud_upper) / cloud_upper * 100 if cloud_upper > 0 else 0
    distance_to_cloud_lower = (close - cloud_lower) / cloud_lower * 100 if cloud_lower > 0 else 0
    cloud_pullback_support = (
        cloud_upper > 0
        and cloud_bullish
        and close > cloud_upper
        and low <= cloud_upper * (1 + CLOUD_SUPPORT_TOLERANCE_PCT / 100)
        and close >= prev_close
    )
    bearish_cloud_breakout_pressure = (
        cloud_upper > 0
        and cloud_lower > 0
        and cloud_bearish
        and cloud_lower <= close <= cloud_upper * (1 + CLOUD_BREAKOUT_DISTANCE_PCT / 100)
        and high >= cloud_upper * (1 - CLOUD_BREAKOUT_DISTANCE_PCT / 100)
        and float(last["Volume"]) >= vol_prev5 * STRONG_VOLUME_SPIKE_RATIO
        and trading_value_spike_ratio >= MIN_TRADING_VALUE_SPIKE_RATIO
    )
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
        (core_universe, 2, core_universe_type or "Core universe"),
        (relative_strength_20d >= MIN_RELATIVE_STRENGTH_20D, 2, "Market relative strength"),
        (trading_value_spike_ratio >= MIN_TRADING_VALUE_SPIKE_RATIO, 1, "Trading value spike"),
        (MIN_ATR_PCT_BONUS <= atr_pct <= MAX_ATR_PCT_BONUS, 1, "ATR in swing range"),
        (cloud_pullback_support, 3, "Bull cloud pullback support"),
        (bearish_cloud_breakout_pressure, 3, "Bear cloud breakout pressure"),
    ]
    for passed, points, reason in scoring_rules:
        if passed:
            score += points
            reasons.append(reason)

    penalty_reasons: list[str] = []
    penalty = 0
    if gap_pct >= GAP_UP_PENALTY_PCT:
        penalty += 2
        penalty_reasons.append("Gap up penalty")
    if prev_day_return_pct >= MAX_PREV_DAY_RETURN_PCT:
        penalty += 2
        penalty_reasons.append("Previous day surge penalty")
    if upper_shadow_ratio >= UPPER_SHADOW_PENALTY_RATIO:
        penalty += 2
        penalty_reasons.append("Upper shadow penalty")
    if atr_pct > MAX_ATR_PCT_BONUS:
        penalty += 2
        penalty_reasons.append("ATR too high")
    if penalty:
        score -= penalty
        reasons.extend(penalty_reasons)

    is_cloud_pattern = cloud_pullback_support or bearish_cloud_breakout_pressure
    rsi_ok = RSI_MIN <= rsi < RSI_MAX_EXCLUSIVE
    cloud_rsi_ok = CLOUD_RSI_MIN <= rsi < CLOUD_RSI_MAX_EXCLUSIVE

    if tenkan <= kijun and not bearish_cloud_breakout_pressure:
        record_reject(reject_counts, "ichimoku_filter")
        return None
    if bb_expansion < MIN_BB_WIDTH_EXPANSION_HARD_PCT:
        record_reject(reject_counts, "bb_expansion_filter")
        return None
    if not (rsi_ok or (is_cloud_pattern and cloud_rsi_ok)):
        record_reject(reject_counts, "rsi_filter")
        return None
    if vol20 < MIN_VOLUME_20D:
        record_reject(reject_counts, "volume_20d_too_low")
        return None
    if float(last["Volume"]) < vol_prev5 * MIN_VOLUME_RATIO_HARD:
        record_reject(reject_counts, "volume_ratio_too_low")
        return None

    swing_low = float(frame["Low"].tail(10).min())
    technical_stop_loss = min(swing_low, ma60) * 0.99
    default_stop_loss = close * (1 - DEFAULT_STOP_PCT / 100)
    stop_loss = min(technical_stop_loss, default_stop_loss)
    risk = max(close - stop_loss, 0.01)
    stop_pct = risk / close * 100
    if stop_pct > MAX_STOP_PCT:
        record_reject(reject_counts, "stop_pct_too_wide")
        return None

    take_profit_1 = close + risk
    take_profit_2 = close + risk * 2
    ma20_trail = ma20 * 0.995
    atr_trail = close - max(atr14 * 1.5, risk * 0.8)
    trailing_stop = max(stop_loss, ma20_trail, atr_trail)

    return {
        "Code": code,
        "Name": name,
        "CompanyProfile": company_profile or {},
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
        "ATR(%)": round(atr_pct, 2),
        "Tenkan": round(tenkan, 2),
        "Kijun": round(kijun, 2),
        "SenkouSpanA": round(senkou_a, 2),
        "SenkouSpanB": round(senkou_b, 2),
        "CloudUpper": round(cloud_upper, 2),
        "CloudLower": round(cloud_lower, 2),
        "CloudType": "bullish" if cloud_bullish else "bearish" if cloud_bearish else "neutral",
        "DistanceToCloudUpper(%)": round(distance_to_cloud_upper, 2),
        "DistanceToCloudLower(%)": round(distance_to_cloud_lower, 2),
        "CloudPullbackSupport": bool(cloud_pullback_support),
        "BearCloudBreakoutPressure": bool(bearish_cloud_breakout_pressure),
        "SignalPatterns": ", ".join(
            pattern
            for pattern, active in [
                ("양운 위 눌림목", cloud_pullback_support),
                ("음운 돌파 직전 수급", bearish_cloud_breakout_pressure),
            ]
            if active
        ),
        "DaysAfterIchimokuCross": days_after_cross,
        "DistanceToKijun(%)": round(distance_to_kijun, 2),
        "BBUpper": round(bb_upper, 2),
        "BBLower": round(bb_lower, 2),
        "BBWidth(%)": round(bb_width, 2),
        "BBExpansion(%)": round(bb_expansion, 2),
        "VolumeSpikeRatio": round(float(last["Volume"]) / vol_prev5, 2),
        "BodyRatio(%)": round(body_ratio, 2),
        "UpperShadowRatio": round(upper_shadow_ratio, 2),
        "Gap(%)": round(gap_pct, 2),
        "PrevDayReturn(%)": round(prev_day_return_pct, 2),
        "IntradayReturn(%)": round(intraday_return_pct, 2),
        "PullbackFromDayHigh(%)": round(pullback_from_day_high_pct, 2),
        "Low52W": round(low_52w, 2),
        "DistanceFrom52WLow(%)": round((close / low_52w - 1) * 100, 2),
        "MarketFilter": "KOSPI close > MA5",
        "MarketFilterPassed": bool(market_filter_ok),
        "Universe": universe,
        "CoreUniverse": bool(core_universe),
        "CoreUniverseType": core_universe_type,
        "Ret_5D(%)": round(ret_5d, 2),
        "Ret_20D(%)": round(ret_20d, 2),
        "MarketRet_20D(%)": round(market_ret_20d, 2),
        "RelativeStrength_20D(%)": round(relative_strength_20d, 2),
        "TradingValueSpikeRatio": round(trading_value_spike_ratio, 2),
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


def market_return_20d(base_date: date) -> float:
    start = (datetime.combine(base_date, datetime.min.time()) - timedelta(days=60)).strftime("%Y-%m-%d")
    frame = fdr.DataReader("KS11", start=start)
    if frame is None or len(frame) < 21:
        return 0.0
    close = frame["Close"]
    return float(close.iloc[-1] / close.iloc[-21] - 1) * 100


def top_market_cap_universe(limit: int = 10) -> list[dict]:
    listing = fdr.StockListing("KOSPI")
    if listing is None or listing.empty:
        return []
    frame = listing.copy()
    if "Code" not in frame.columns and "Symbol" in frame.columns:
        frame["Code"] = frame["Symbol"]
    if "Name" not in frame.columns:
        frame["Name"] = frame["Code"]
    if "Marcap" not in frame.columns:
        frame["Marcap"] = 0
    frame["Code"] = frame["Code"].astype(str).str.zfill(6)
    frame = frame.sort_values("Marcap", ascending=False).head(limit)
    return [
        {
            "rank": index + 1,
            "code": str(row.get("Code") or "").zfill(6),
            "name": row.get("Name"),
            "market_cap": int(float(row.get("Marcap") or 0)),
        }
        for index, (_, row) in enumerate(frame.iterrows())
    ]


def _indicator_snapshot(frame: pd.DataFrame, market_ret_20d: float) -> dict:
    prepared = prepare_frame(frame).dropna()
    if prepared.empty:
        return {}
    last = prepared.iloc[-1]
    prev = prepared.iloc[-2] if len(prepared) >= 2 else last
    close = float(last["Close"])
    open_ = float(last["Open"])
    high = float(last["High"])
    vol_prev5 = float(last["VolPrev5"])
    trading_value = float(last["TradingValue"])
    trading_value20 = float(last["TradingValue20"])
    tenkan = float(last["Tenkan"])
    kijun = float(last["Kijun"])
    ret_20d = float(last["Ret_20D"])
    return {
        "latest_date": pd.Timestamp(prepared.index[-1]).date().isoformat(),
        "close": round(close, 2),
        "score": None,
        "rsi": round(float(last["RSI14"]), 2),
        "ret_5d_pct": round(float(last["Ret_5D"]), 2),
        "ret_20d_pct": round(ret_20d, 2),
        "market_ret_20d_pct": round(market_ret_20d, 2),
        "relative_strength_20d_pct": round(ret_20d - market_ret_20d, 2),
        "tenkan": round(tenkan, 2),
        "kijun": round(kijun, 2),
        "tenkan_above_kijun": tenkan > kijun,
        "distance_to_kijun_pct": round((close - kijun) / kijun * 100, 2) if kijun > 0 else None,
        "bb_expansion_pct": round(float(last["BBExpansionPct"]), 2),
        "volume_spike_ratio": round(float(last["Volume"]) / vol_prev5, 2) if vol_prev5 > 0 else None,
        "trading_value_spike_ratio": round(trading_value / trading_value20, 2) if trading_value20 > 0 else None,
        "intraday_return_pct": round((close / open_ - 1) * 100, 2) if open_ > 0 else None,
        "pullback_from_day_high_pct": round((close / high - 1) * 100, 2) if high > 0 else None,
        "prev_close": round(float(prev["Close"]), 2),
    }


def analyze_top_market_cap_stocks(trade_date: date, limit: int = 10) -> list[dict]:
    market_ok = kospi_market_filter_ok(trade_date)
    market_ret = market_return_20d(trade_date)
    start = (datetime.combine(trade_date, datetime.min.time()) - timedelta(days=420)).strftime("%Y-%m-%d")
    end = (trade_date + timedelta(days=1)).strftime("%Y-%m-%d")
    rows: list[dict] = []
    for item in top_market_cap_universe(limit):
        code = item["code"]
        name = str(item.get("name") or code)
        reject_counts: dict[str, int] = {}
        try:
            frame = fdr.DataReader(code, start=start, end=end)
            result = score_swing_setup(
                frame,
                code,
                name,
                market_filter_ok=market_ok,
                universe="KOSPI_TOP10",
                market_ret_20d=market_ret,
                core_universe=True,
                core_universe_type="KOSPI_TOP10",
                trade_date=trade_date,
                reject_counts=reject_counts,
            )
            snapshot = _indicator_snapshot(frame, market_ret)
            if result:
                snapshot.update(
                    {
                        "close": result.get("Entry"),
                        "score": result.get("Score"),
                        "rsi": result.get("RSI14"),
                        "ret_5d_pct": result.get("Ret_5D(%)"),
                        "ret_20d_pct": result.get("Ret_20D(%)"),
                        "market_ret_20d_pct": result.get("MarketRet_20D(%)"),
                        "relative_strength_20d_pct": result.get("RelativeStrength_20D(%)"),
                        "tenkan": result.get("Tenkan"),
                        "kijun": result.get("Kijun"),
                        "tenkan_above_kijun": bool(float(result.get("Tenkan") or 0) > float(result.get("Kijun") or 0)),
                        "distance_to_kijun_pct": result.get("DistanceToKijun(%)"),
                        "bb_expansion_pct": result.get("BBExpansion(%)"),
                        "volume_spike_ratio": result.get("VolumeSpikeRatio"),
                        "trading_value_spike_ratio": result.get("TradingValueSpikeRatio"),
                        "intraday_return_pct": result.get("IntradayReturn(%)"),
                        "pullback_from_day_high_pct": result.get("PullbackFromDayHigh(%)"),
                        "stop_pct": result.get("StopPct"),
                        "reasons": result.get("Reasons"),
                    }
                )
            reason_code = next(iter(reject_counts), None)
            rows.append(
                {
                    **item,
                    **snapshot,
                    "passed": bool(result),
                    "reject_reason_code": reason_code,
                    "reject_reason": reason_code,
                    "market_filter_passed": market_ok,
                }
            )
        except Exception as exc:
            rows.append({**item, "passed": False, "reject_reason_code": "data_error", "reject_reason": "data_error", "error": str(exc)[:300]})
    return rows


def _company_profile_from_row(row: pd.Series, universe: str) -> dict:
    return company_profile_from_row(row, universe)


def _code_set(listing: pd.DataFrame) -> set[str]:
    if listing is None or listing.empty:
        return set()
    frame = listing.copy()
    if "Code" not in frame.columns and "Symbol" in frame.columns:
        frame["Code"] = frame["Symbol"]
    if "Code" not in frame.columns:
        return set()
    return set(frame["Code"].astype(str).str.zfill(6).tolist())


def _truthy(value: object) -> bool:
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _normalize_listing(
    listing: pd.DataFrame,
    universe: str,
    *,
    core_codes: set[str] | None = None,
    core_universe_type: str = "",
) -> pd.DataFrame:
    frame = listing.copy()
    if "Code" not in frame.columns and "Symbol" in frame.columns:
        frame["Code"] = frame["Symbol"]
    if "Name" not in frame.columns:
        frame["Name"] = frame["Code"]
    frame["Code"] = frame["Code"].astype(str).str.zfill(6)
    frame["Universe"] = universe
    core_codes = core_codes or set()
    frame["CoreUniverse"] = frame["Code"].isin(core_codes)
    frame["CoreUniverseType"] = frame["CoreUniverse"].map(lambda passed: core_universe_type if passed else "")
    frame["CompanyProfile"] = frame.apply(lambda row: _company_profile_from_row(row, universe), axis=1)
    return frame[["Code", "Name", "Universe", "CoreUniverse", "CoreUniverseType", "CompanyProfile"]].drop_duplicates("Code")


def load_scan_universe(scope: str = SCAN_UNIVERSE_LIMITED) -> pd.DataFrame:
    full_scan = scope == SCAN_UNIVERSE_ALL
    logger.warning("Loading scan universe: scope=%s", scope)
    kospi = fdr.StockListing("KOSPI")
    kospi_core = kospi.sort_values("Marcap", ascending=False).head(KOSPI_MARKET_CAP_LIMIT) if "Marcap" in kospi.columns else kospi.head(KOSPI_MARKET_CAP_LIMIT)
    kospi_core_codes = _code_set(kospi_core)
    if not full_scan and "Marcap" in kospi.columns:
        kospi = kospi_core
    elif not full_scan:
        kospi = kospi_core
    frames = [
        _normalize_listing(
            kospi,
            "KOSPI_ALL" if full_scan else "KOSPI_TOP1000",
            core_codes=kospi_core_codes,
            core_universe_type="KOSPI_TOP1000",
        )
    ]

    try:
        kosdaq = fdr.StockListing("KOSDAQ" if full_scan else "KOSDAQ150")
        kosdaq150_codes = _code_set(kosdaq)
        if full_scan:
            try:
                kosdaq150_codes = _code_set(fdr.StockListing("KOSDAQ150"))
            except Exception:
                logger.warning("KOSDAQ150 core universe load failed; continuing without KOSDAQ150 marks", exc_info=True)
        frames.append(
            _normalize_listing(
                kosdaq,
                "KOSDAQ_ALL" if full_scan else "KOSDAQ150",
                core_codes=kosdaq150_codes,
                core_universe_type="KOSDAQ150",
            )
        )
    except Exception:
        pass

    universe = pd.concat(frames, ignore_index=True).drop_duplicates("Code")
    universe["CompanyProfile"] = universe.apply(
        lambda row: enrich_company_profile(row["Code"], row.get("CompanyProfile") or {}),
        axis=1,
    )
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


def prepare_chunked_scan_state_sync(today: date | None = None, universe_scope: str = SCAN_UNIVERSE_ALL) -> dict:
    base_date = today or datetime.now(ZoneInfo(get_settings().timezone)).date()
    market_status = get_scan_market_status(base_date)
    if not market_status["is_open"]:
        raise RuntimeError(market_status["message"])
    scope = SCAN_UNIVERSE_ALL if universe_scope == SCAN_UNIVERSE_ALL else SCAN_UNIVERSE_LIMITED
    logger.warning("Signal scan universe load started: date=%s scope=%s", base_date.isoformat(), scope)
    universe = load_scan_universe(scope)
    logger.warning("Signal scan market filter started")
    market_ok = kospi_market_filter_ok(base_date)
    market_ret_20d = market_return_20d(base_date)
    logger.warning("Signal scan market filter completed: market_ok=%s market_ret_20d=%.2f", market_ok, market_ret_20d)
    start = (datetime.combine(base_date, datetime.min.time()) - timedelta(days=420)).strftime("%Y-%m-%d")
    return {
        "trade_date": base_date.isoformat(),
        "market_status": market_status,
        "universe_scope": scope,
        "universe": universe.to_dict("records"),
        "market_ok": market_ok,
        "market_ret_20d": market_ret_20d,
        "start": start,
        "offset": 0,
        "total": len(universe),
        "candidates": [],
        "reject_counts": {},
        "data_error_count": 0,
        "done": False,
    }


async def prepare_chunked_scan_state(today: date | None = None, universe_scope: str = SCAN_UNIVERSE_ALL) -> dict:
    return await asyncio.to_thread(prepare_chunked_scan_state_sync, today, universe_scope)


def process_scan_chunk_sync(state: dict, chunk_size: int = SCAN_CHUNK_SIZE) -> dict:
    universe = state.get("universe") or []
    offset = int(state.get("offset") or 0)
    total = len(universe)
    end = min(offset + chunk_size, total)
    results: list[dict] = list(state.get("candidates") or [])
    reject_counts: dict[str, int] = dict(state.get("reject_counts") or {})
    data_error_count = int(state.get("data_error_count") or 0)

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
                market_ret_20d=float(state.get("market_ret_20d") or 0),
                company_profile=row.get("CompanyProfile") or {},
                core_universe=_truthy(row.get("CoreUniverse")),
                core_universe_type=str(row.get("CoreUniverseType") or ""),
                trade_date=date.fromisoformat(state["trade_date"]),
                reject_counts=reject_counts,
            )
            if result:
                results.append(result)
        except Exception:
            data_error_count += 1
            record_reject(reject_counts, "data_error")
            logger.debug("Signal scan skipped code=%s", row.get("Code"), exc_info=True)
            continue

    done = end >= total
    next_state = {
        **state,
        "offset": end,
        "total": total,
        "candidates": results,
        "reject_counts": reject_counts,
        "data_error_count": data_error_count,
        "done": done,
    }
    logger.warning("Signal scan chunk completed: offset=%s/%s candidates=%s done=%s", end, total, len(results), done)
    return next_state


async def process_scan_chunk(state: dict, chunk_size: int = SCAN_CHUNK_SIZE) -> dict:
    return await asyncio.to_thread(process_scan_chunk_sync, state, chunk_size)


async def finalize_chunked_scan(user_id: str, state: dict, telegram_chat_id: str | None = None) -> dict:
    trade_date = date.fromisoformat(state["trade_date"])
    signals = sort_top_signals(list(state.get("candidates") or []))
    shared_saved = await save_shared_signals(signals, trade_date)
    telegram_sent = await send_shared_signal_message(format_top_signals_message(signals, trade_date), telegram_chat_id)
    report_queued = await send_daily_signal_report(signals, trade_date)
    return {
        "trade_date": trade_date.isoformat(),
        "signals": len(signals),
        "saved": 0,
        "shared_saved": shared_saved,
        "telegram_sent": telegram_sent,
        "ai_report_queued": report_queued,
    }


def scan_kospi_signals_sync(today: date | None = None) -> list[dict]:
    state = scan_kospi_signal_state_sync(today)
    return sort_top_signals(list(state.get("candidates") or []))


def scan_kospi_signal_state_sync(today: date | None = None) -> dict:
    state = prepare_chunked_scan_state_sync(today)
    results: list[dict] = []
    reject_counts: dict[str, int] = {}

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
                market_ret_20d=float(state.get("market_ret_20d") or 0),
                company_profile=row.get("CompanyProfile") or {},
                core_universe=_truthy(row.get("CoreUniverse")),
                core_universe_type=str(row.get("CoreUniverseType") or ""),
                trade_date=date.fromisoformat(state["trade_date"]),
                reject_counts=reject_counts,
            )
            if result:
                results.append(result)
        except Exception:
            record_reject(reject_counts, "data_error")
            logger.debug("Signal scan skipped code=%s", row.get("Code"), exc_info=True)
            continue

    logger.warning("Signal scan scoring completed: scanned=%s candidates=%s rejects=%s", total, len(results), reject_counts)
    return {
        **state,
        "offset": total,
        "total": total,
        "candidates": results,
        "reject_counts": reject_counts,
        "data_error_count": int(reject_counts.get("data_error") or 0),
        "done": True,
    }


async def scan_kospi_signals(today: date | None = None) -> list[dict]:
    return await asyncio.to_thread(scan_kospi_signals_sync, today)


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


async def save_shared_signals(signals: list[dict], trade_date: date | None = None) -> int:
    today = trade_date or datetime.now(ZoneInfo(get_settings().timezone)).date()
    rest = SupabaseRest()
    count = 0
    for signal in signals:
        await rest.upsert("shared_signals", shared_signal_to_record(today, signal), on_conflict="trade_date,code")
        count += 1
    return count


def calculate_forward_return_record(signal: dict, as_of: date) -> dict | None:
    trade_date = date.fromisoformat(str(signal["trade_date"]))
    entry = float(signal.get("entry") or 0)
    if entry <= 0:
        return None

    end_date = min(as_of, trade_date + timedelta(days=14))
    frame = fdr.DataReader(str(signal["code"]).zfill(6), start=trade_date.strftime("%Y-%m-%d"), end=end_date.strftime("%Y-%m-%d"))
    if frame is None or frame.empty:
        return None
    frame = frame.dropna()
    if len(frame) <= 1:
        return None

    evaluated_at = datetime.now(ZoneInfo(get_settings().timezone)).isoformat()
    raw: dict = {
        "evaluated_at": evaluated_at,
        "available_trading_days": len(frame) - 1,
    }
    payload: dict = {
        "trade_date": trade_date.isoformat(),
        "code": str(signal["code"]).zfill(6),
        "name": signal.get("name"),
        "entry": entry,
        "evaluated_at": evaluated_at,
    }
    for horizon in FORWARD_RETURN_HORIZONS:
        if len(frame) <= horizon:
            continue
        window = frame.iloc[1 : horizon + 1]
        close_price = float(frame.iloc[horizon]["Close"])
        high_price = float(window["High"].max())
        low_price = float(window["Low"].min())
        payload[f"close_{horizon}d"] = round(close_price, 2)
        payload[f"return_{horizon}d_pct"] = round((close_price / entry - 1) * 100, 2)
        payload[f"max_runup_{horizon}d_pct"] = round((high_price / entry - 1) * 100, 2)
        payload[f"max_drawdown_{horizon}d_pct"] = round((low_price / entry - 1) * 100, 2)
        raw[f"{horizon}d"] = {
            "close": round(close_price, 2),
            "high": round(high_price, 2),
            "low": round(low_price, 2),
        }
    if not any(f"return_{horizon}d_pct" in payload for horizon in FORWARD_RETURN_HORIZONS):
        return None
    payload["raw"] = raw
    return payload


async def update_signal_forward_returns(as_of: date | None = None, limit: int = FORWARD_RETURN_UPDATE_LIMIT) -> int:
    today = as_of or datetime.now(ZoneInfo(get_settings().timezone)).date()
    cutoff = today - timedelta(days=min(FORWARD_RETURN_HORIZONS))
    rest = SupabaseRest()
    try:
        rows = await rest.select(
            "shared_signals",
            filters={"trade_date": f"lte.{cutoff.isoformat()}"},
            order="trade_date.desc",
            limit=limit,
        )
    except RuntimeError as exc:
        logger.warning("Forward return update skipped: failed to load shared signals: %s", exc)
        return 0

    updated = 0
    for signal in rows:
        try:
            record = await asyncio.to_thread(calculate_forward_return_record, signal, today)
            if not record:
                continue
            await rest.upsert("signal_forward_returns", record, on_conflict="trade_date,code")
            updated += 1
        except RuntimeError as exc:
            logger.warning("Forward return update skipped for code=%s date=%s error=%s", signal.get("code"), signal.get("trade_date"), exc)
        except Exception:
            logger.debug("Forward return update failed for code=%s date=%s", signal.get("code"), signal.get("trade_date"), exc_info=True)
    return updated


async def send_shared_signal_message(text: str, fallback_chat_id: str | None = None) -> int:
    settings = get_settings()
    sent = 0
    sent_keys: set[tuple[str, str]] = set()
    common_chat_id = settings.telegram_chat_id or fallback_chat_id
    if settings.telegram_bot_token and common_chat_id:
        if await send_telegram_message(common_chat_id, text):
            sent += 1
            sent_keys.add((settings.telegram_bot_token, str(common_chat_id)))

    for recipient in await list_telegram_recipients():
        bot_token = recipient.get("telegram_bot_token")
        chat_id = recipient.get("telegram_chat_id")
        if not bot_token or not chat_id:
            continue
        key = (str(bot_token), str(chat_id))
        if key in sent_keys:
            continue
        if await send_telegram_message_with_bot(str(bot_token), str(chat_id), text):
            sent += 1
            sent_keys.add(key)
    return sent


def format_top_signals_message(signals: list[dict], trade_date: date) -> str:
    lines = [f"KOSPI Swing Top {min(5, len(signals))} - {trade_date.isoformat()}"]
    if not signals:
        lines.append("No candidates today.")
        return "\n".join(lines)
    for index, signal in enumerate(signals[:5], start=1):
        lines.append(
            f"{index}. {signal['Name']} "
            f"entry {signal['Entry']:,.0f} stop {signal['StopLoss']:,.0f} "
            f"tp2 {signal['TakeProfit2']:,.0f} score {signal['Score']}"
        )
    return "\n".join(lines)


async def scan_and_store_for_user(user_id: str, telegram_chat_id: str | None = None) -> dict:
    trade_date = datetime.now(ZoneInfo(get_settings().timezone)).date()
    started_at = datetime.now(ZoneInfo(get_settings().timezone)).isoformat()
    market_status = get_scan_market_status(trade_date)
    if not market_status["is_open"]:
        logger.warning("Signal scan skipped: %s", market_status)
        return {
            "skipped": True,
            "reason": market_status["reason"],
            "message": market_status["message"],
            "trade_date": trade_date.isoformat(),
            "market_status": market_status,
        }
    state = await asyncio.to_thread(scan_kospi_signal_state_sync, trade_date)
    signals = sort_top_signals(list(state.get("candidates") or []))
    shared_saved = await save_shared_signals(signals, trade_date)
    telegram_sent = await send_shared_signal_message(format_top_signals_message(signals, trade_date), telegram_chat_id)
    report_queued = await send_daily_signal_report(signals, trade_date)
    final_result = {
        "trade_date": trade_date.isoformat(),
        "signals": len(signals),
        "saved": 0,
        "shared_saved": shared_saved,
        "telegram_sent": telegram_sent,
        "ai_report_queued": report_queued,
    }
    await SupabaseRest().insert(
        "scan_runs",
        {
            "requested_by": user_id,
            "status": "completed",
            "trade_date": trade_date.isoformat(),
            "signals_count": len(signals),
            "shared_saved": shared_saved,
            "result": {**state, "candidates": signals, "final": final_result},
            "universe_scope": state.get("universe_scope"),
            "started_at": started_at,
            "finished_at": datetime.now(ZoneInfo(get_settings().timezone)).isoformat(),
        },
    )
    return final_result
