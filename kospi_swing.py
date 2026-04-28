# ============================================================
#  KOSPI Swing Screener
#  Strategy: uptrend + Ichimoku cross + Bollinger expansion + risk filter
# ============================================================

from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import warnings

try:
    import FinanceDataReader as fdr
    import pandas as pd
    import openpyxl  # noqa: F401
except ImportError as exc:
    print("Required packages are missing.")
    print(f"Import error: {exc}")
    print("Install them with:")
    print("  python -m pip install finance-datareader pandas openpyxl")
    raise SystemExit(1) from exc

warnings.filterwarnings("ignore")


# ============================================================
# Configuration
# ============================================================
TOP_N = 30
MIN_VOLUME_20D = 20000
MIN_PRICE = 1000
MIN_TRADING_VALUE_20D = 300_000_000
KOSPI_MARKET_CAP_LIMIT = 1000
RSI_MIN = 30
RSI_MAX_EXCLUSIVE = 56
MIN_RET_5D = 0
MIN_RET_20D = 3
MAX_RET_20D = 25
MAX_STOP_PCT = 10.0
MIN_BB_WIDTH_EXPANSION_PCT = 5.0
MIN_BB_WIDTH_EXPANSION_HARD_PCT = 0.0
MIN_VOLUME_RATIO_HARD = 1.0
MIN_VOLUME_SPIKE_RATIO = 1.2
STRONG_VOLUME_SPIKE_RATIO = 1.5
MAX_DAYS_AFTER_ICHIMOKU_CROSS = 5
SAVE_EXCEL = True
SAVE_JSON = True
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
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(0)


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
    days_after_ichimoku_cross = None
    recent_cross = frame["IchimokuBullCross"].tail(MAX_DAYS_AFTER_ICHIMOKU_CROSS + 1)
    if bool(recent_cross.any()):
        reversed_flags = list(reversed(recent_cross.tolist()))
        days_after_ichimoku_cross = reversed_flags.index(True)

    score = 0
    reasons: list[str] = []

    # Market and trend context
    if ma20 > ma60:
        score += 2
        reasons.append("MA20 > MA60")
    if ma20_prev5 > 0 and ma20 > ma20_prev5:
        score += 1
        reasons.append("MA20 rising")
    if tenkan > kijun:
        score += 2
        reasons.append("Tenkan > Kijun")
    if days_after_ichimoku_cross is not None:
        score += 3
        reasons.append("Ichimoku cross")

    if close >= prev_close:
        score += 1
        reasons.append("Bullish close")
    if 0 <= distance_to_kijun <= 10:
        score += 1
        reasons.append("Near Kijun")

    # Momentum / mean reversion balance
    if RSI_MIN <= rsi < RSI_MAX_EXCLUSIVE:
        score += 3
        reasons.append("RSI rebound zone")
    if MIN_RET_5D <= ret_5d <= 10:
        score += 1
        reasons.append("5D momentum ok")
    if MIN_RET_20D <= ret_20d <= MAX_RET_20D:
        score += 1
        reasons.append("20D momentum ok")
    if bb_expansion >= MIN_BB_WIDTH_EXPANSION_PCT:
        score += 3
        reasons.append("BB expanding")
    if vol20 >= MIN_VOLUME_20D:
        score += 1
        reasons.append("Enough liquidity")
    if trading_value_20d >= MIN_TRADING_VALUE_20D:
        score += 2
        reasons.append("Enough trading value")
    if float(last["Volume"]) >= vol_prev5 * MIN_VOLUME_SPIKE_RATIO:
        score += 2
        reasons.append("Volume spike")
    if float(last["Volume"]) >= vol_prev5 * STRONG_VOLUME_SPIKE_RATIO:
        score += 1
        reasons.append("Strong volume spike")
    if market_filter_ok:
        score += 2
        reasons.append("KOSPI above MA5")
    if universe in {"KOSPI_TOP500", "KOSDAQ150"}:
        score += 2
        reasons.append(universe)

    # Hard filters to avoid weak setups
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
    entry_rule = "Buy early bottom reversal: RSI 30-55, Tenkan above Kijun, non-contracting Bollinger width, market filter"
    exit_rule = f"Scale out at +1R and +2R, trail the remainder, or exit after {HOLD_MAX_DAYS} trading days"
    hold_rule = f"Hold usually {HOLD_MIN_DAYS}-{HOLD_MAX_DAYS} trading days, aim around {HOLD_PREFERRED_DAYS} days"
    position_plan = "Sell 30% at +1R, 30% at +2R, and trail the remaining 40% using MA20/ATR rules"

    return {
        "Code": code,
        "Name": name,
        "Entry": round(close, 2),
        "StopLoss": round(stop_loss, 2),
        "TakeProfit1": round(take_profit_1, 2),
        "TakeProfit2": round(take_profit_2, 2),
        "TrailingStop": round(trailing_stop, 2),
        "MA20Trail": round(ma20_trail, 2),
        "RiskPct": round(risk / close * 100, 2),
        "StopPct": round(stop_pct, 2),
        "TakeProfit1Pct": round((take_profit_1 - close) / close * 100, 2),
        "TakeProfit2Pct": round((take_profit_2 - close) / close * 100, 2),
        "HoldMinDays": HOLD_MIN_DAYS,
        "HoldPreferredDays": HOLD_PREFERRED_DAYS,
        "HoldMaxDays": HOLD_MAX_DAYS,
        "EntryRule": entry_rule,
        "ExitRule": exit_rule,
        "HoldRule": hold_rule,
        "PositionPlan": position_plan,
        "Ret_5D(%)": round(ret_5d, 2),
        "Ret_20D(%)": round(ret_20d, 2),
        "RSI14": round(rsi, 1),
        "ATR14": round(atr14, 2),
        "Tenkan": round(tenkan, 2),
        "Kijun": round(kijun, 2),
        "DaysAfterIchimokuCross": days_after_ichimoku_cross,
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
        "DistanceToMA20(%)": round(distance_to_ma20, 2),
        "Vol20": int(vol20),
        "TradingValue20D": int(trading_value_20d),
        "Score": score,
        "Reasons": ", ".join(reasons[:8]),
    }


def kospi_market_filter_ok(base_date: datetime) -> bool:
    start = (base_date - timedelta(days=40)).strftime("%Y-%m-%d")
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

    return pd.concat(frames, ignore_index=True).drop_duplicates("Code")


def write_signal_json(df: pd.DataFrame, output_dir: Path, today: datetime) -> Path:
    signal_columns = [
        "Code",
        "Name",
        "Entry",
        "StopLoss",
        "TakeProfit1",
        "TakeProfit2",
        "TrailingStop",
        "Score",
        "Tenkan",
        "Kijun",
        "DaysAfterIchimokuCross",
        "BBUpper",
        "BBLower",
        "BBWidth(%)",
        "BBExpansion(%)",
        "VolumeSpikeRatio",
        "TradingValue20D",
        "BodyRatio(%)",
        "Low52W",
        "DistanceFrom52WLow(%)",
        "Universe",
        "RSI14",
        "ATR14",
        "StopPct",
        "HoldMaxDays",
        "PositionPlan",
        "Reasons",
    ]
    available_columns = [column for column in signal_columns if column in df.columns]
    signals = df[available_columns].head(TOP_N).to_dict(orient="records")
    payload = {
        "date": today.strftime("%Y-%m-%d"),
        "strategy": "swing_bottom_reversal_ichimoku_bollinger_v3",
        "top_n": TOP_N,
        "signals": signals,
    }
    filename = output_dir / f"swing_signals_{today.strftime('%Y%m%d')}.json"
    with filename.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
    return filename


def main() -> None:
    today = datetime.today()
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    print("=" * 64)
    print("  KOSPI Swing Screener")
    print(f"  Date: {today.strftime('%Y-%m-%d')}")
    print("=" * 64)

    print("\n1) Loading scan universe...")
    try:
        universe = load_scan_universe()
        market_filter_ok = kospi_market_filter_ok(today)
    except Exception as exc:
        print("Failed to load scan universe or KOSPI market filter.")
        print("This usually means KRX/FinanceDataReader network access failed.")
        print(f"Error: {exc}")
        raise SystemExit(1) from exc
    print(f"   -> {len(universe)} stocks")
    print(f"   -> KOSPI market filter: {'PASS' if market_filter_ok else 'FAIL'}")

    print("\n2) Scanning swing setups...")
    results = []
    total = len(universe)
    start = (today - timedelta(days=420)).strftime("%Y-%m-%d")

    for i, row in universe.iterrows():
        try:
            raw = fdr.DataReader(row["Code"], start=start)
            result = score_swing_setup(
                raw,
                row["Code"],
                row["Name"],
                market_filter_ok=market_filter_ok,
                universe=row["Universe"],
            )
            if result:
                results.append(result)
        except Exception:
            pass

        if (i + 1) % 100 == 0:
            pct = round((i + 1) / total * 100, 1)
            print(f"   progress: {i+1}/{total} ({pct}%) | candidates: {len(results)}")

    df = pd.DataFrame(results)
    if df.empty:
        print("\nNo swing candidates found.")
        return

    df = df.sort_values(
        ["Score", "BBExpansion(%)", "Ret_20D(%)", "DistanceToMA20(%)"],
        ascending=[False, False, False, True],
    ).reset_index(drop=True)

    print(f"\n   -> candidates found: {len(df)}")
    print()
    print("=" * 96)
    print(f"  Top {TOP_N} Swing Candidates")
    print("=" * 96)
    print(
        f"{'Rank':<4} {'Code':<8} {'Name':<18} {'Entry':>10} {'Stop':>10} {'TP2':>10} "
        f"{'Score':>6} {'Cross':>6} {'BBExp':>7} {'RSI':>6} {'VolX':>6}"
    )
    print("-" * 96)

    for i, row in df.head(TOP_N).iterrows():
        print(
            f"{i+1:<4} {row['Code']:<8} {row['Name']:<18} "
            f"{row['Entry']:>10,.0f} {row['StopLoss']:>10,.0f} {row['TakeProfit2']:>10,.0f} "
            f"{row['Score']:>6} {row['DaysAfterIchimokuCross']:>6} {row['BBExpansion(%)']:>7.1f} "
            f"{row['RSI14']:>6.1f} {row['VolumeSpikeRatio']:>6.1f}"
        )

    print("=" * 96)
    print("  Strategy: bottom reversal + Ichimoku cross + Bollinger expansion + volume spike")
    print("=" * 96)

    if SAVE_EXCEL:
        filename = output_dir / f"kospi_swing_{today.strftime('%Y%m%d')}.xlsx"
        with pd.ExcelWriter(filename, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Swing_Overall", index=False)
            df.head(TOP_N).to_excel(writer, sheet_name=f"TOP{TOP_N}", index=False)
            pd.DataFrame(
                [
                    {"Item": "Entry rule", "Detail": "RSI 30-55, Tenkan above Kijun, Bollinger width not contracting, and KOSPI market filter"},
                    {"Item": "Hold period", "Detail": f"Usually {HOLD_MIN_DAYS}-{HOLD_MAX_DAYS} trading days, target around {HOLD_PREFERRED_DAYS} days"},
                    {"Item": "Exit rule", "Detail": f"Sell 30% at +1R, 30% at +2R, trail the rest, or exit after {HOLD_MAX_DAYS} trading days"},
                    {"Item": "Stop rule", "Detail": "Exit immediately if the close breaks the stop-loss"},
                    {"Item": "Trailing stop", "Detail": "Use the tighter of the MA20-based trail and the ATR-based trail"},
                    {"Item": "Risk rule", "Detail": f"Skip setups with stop-loss wider than {MAX_STOP_PCT:.1f}%"},
                    {"Item": "Ichimoku rule", "Detail": f"Tenkan must be above Kijun and the bullish cross must be within {MAX_DAYS_AFTER_ICHIMOKU_CROSS} trading days"},
                    {"Item": "Bollinger rule", "Detail": f"Bollinger Band width must not be contracting; expansion above {MIN_BB_WIDTH_EXPANSION_PCT:.1f}% gets score"},
                    {"Item": "RSI rule", "Detail": "RSI(14) must be at least 30 and below 56"},
                    {"Item": "Volume rule", "Detail": f"Today's volume at least {MIN_VOLUME_SPIKE_RATIO:.1f}x previous 5-day average gets score; {STRONG_VOLUME_SPIKE_RATIO:.1f}x gets extra score"},
                    {"Item": "Volume hard rule", "Detail": f"Today's volume must be at least {MIN_VOLUME_RATIO_HARD:.1f}x previous 5-day average"},
                    {"Item": "Liquidity rule", "Detail": f"Exclude stocks below {MIN_PRICE:,} KRW or 20-day average trading value below {MIN_TRADING_VALUE_20D:,} KRW"},
                    {"Item": "Name exclusion rule", "Detail": f"Exclude names containing {', '.join(EXCLUDED_NAME_KEYWORDS)}"},
                    {"Item": "Market rule", "Detail": "KOSPI index close must be above its 5-day moving average"},
                    {"Item": "Universe rule", "Detail": f"KOSPI top {KOSPI_MARKET_CAP_LIMIT} by market cap plus KOSDAQ150 when FinanceDataReader supports it"},
                ]
            ).to_excel(writer, sheet_name="Rules", index=False)
        print(f"\nSaved: {filename}")

    if SAVE_JSON:
        signal_file = write_signal_json(df, output_dir, today)
        print(f"Saved signals: {signal_file}")


if __name__ == "__main__":
    main()
