from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

import FinanceDataReader as fdr

from kospi_swing import (
    MAX_PRICE_TO_MA20_RATIO,
    MIN_BB_WIDTH_EXPANSION_PCT,
    MIN_BODY_RATIO_PCT,
    MIN_DISTANCE_FROM_52W_LOW,
    MIN_VOLUME_SPIKE_RATIO,
    RSI_MAX_EXCLUSIVE,
    RSI_MIN,
    kospi_market_filter_ok,
    load_scan_universe,
    prepare_frame,
)


def main() -> None:
    today = datetime.today()
    universe = load_scan_universe()
    market_ok = kospi_market_filter_ok(today)
    start = (today - timedelta(days=420)).strftime("%Y-%m-%d")
    counts = Counter()
    total = 0

    for _, row in universe.iterrows():
        total += 1
        try:
            raw = fdr.DataReader(row["Code"], start=start)
            if raw is None or len(raw) < 260:
                counts["data_short"] += 1
                continue
            frame = prepare_frame(raw).dropna()
            if frame.empty:
                counts["indicator_na"] += 1
                continue
            last = frame.iloc[-1]
            prev5_volume = float(last["VolPrev5"])
            close = float(last["Close"])
            open_ = float(last["Open"])
            ma20 = float(last["MA20"])
            tenkan = float(last["Tenkan"])
            kijun = float(last["Kijun"])
            rsi = float(last["RSI14"])
            bb_expansion = float(last["BBExpansionPct"])
            body_ratio = float(last["BodyRatioPct"])
            low_52w = float(last["Low52W"])
            volume = float(last["Volume"])

            if not market_ok:
                counts["market_filter_fail"] += 1
            if not (RSI_MIN <= rsi < RSI_MAX_EXCLUSIVE):
                counts["rsi_fail"] += 1
            if not tenkan > kijun:
                counts["ichimoku_fail"] += 1
            if bb_expansion < MIN_BB_WIDTH_EXPANSION_PCT:
                counts["bb_expansion_fail"] += 1
            if prev5_volume <= 0 or volume < prev5_volume * MIN_VOLUME_SPIKE_RATIO:
                counts["volume_spike_fail"] += 1
            if close <= open_ or body_ratio < MIN_BODY_RATIO_PCT:
                counts["candle_fail"] += 1
            if close > ma20 * MAX_PRICE_TO_MA20_RATIO:
                counts["ma20_zone_fail"] += 1
            if close < low_52w * MIN_DISTANCE_FROM_52W_LOW:
                counts["low_52w_fail"] += 1

            hard_pass = (
                market_ok
                and RSI_MIN <= rsi < RSI_MAX_EXCLUSIVE
                and tenkan > kijun
                and bb_expansion >= MIN_BB_WIDTH_EXPANSION_PCT
                and prev5_volume > 0
                and volume >= prev5_volume * MIN_VOLUME_SPIKE_RATIO
                and close > open_
                and body_ratio >= MIN_BODY_RATIO_PCT
                and close <= ma20 * MAX_PRICE_TO_MA20_RATIO
                and close >= low_52w * MIN_DISTANCE_FROM_52W_LOW
            )
            if hard_pass:
                counts["hard_pass_before_risk"] += 1
        except Exception:
            counts["data_error"] += 1

    print(f"total={total}")
    print(f"market_filter={'PASS' if market_ok else 'FAIL'}")
    for key, value in counts.most_common():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
