from __future__ import annotations

from app.services.supabase_rest import SupabaseRest


TABLE = "strategy_settings"

PRESETS: dict[str, dict] = {
    "conservative": {
        "preset": "conservative",
        "min_score": 13,
        "max_open_positions": 4,
        "max_new_positions_per_day": 1,
        "position_capital_pct": 0.12,
        "risk_per_trade_pct": 0.007,
        "min_order_amount": 100_000,
        "min_entry_discount": 0.995,
        "max_entry_premium": 1.015,
        "max_pullback_from_day_high": 0.02,
        "use_kijun_filter": True,
        "use_bb_upper_filter": True,
        "use_day_candle_filter": False,
        "use_breakeven_after_tp1": False,
        "use_kijun_exit": False,
    },
    "balanced": {
        "preset": "balanced",
        "min_score": 12,
        "max_open_positions": 5,
        "max_new_positions_per_day": 2,
        "position_capital_pct": 0.18,
        "risk_per_trade_pct": 0.01,
        "min_order_amount": 100_000,
        "min_entry_discount": 0.995,
        "max_entry_premium": 1.02,
        "max_pullback_from_day_high": 0.03,
        "use_kijun_filter": True,
        "use_bb_upper_filter": True,
        "use_day_candle_filter": False,
        "use_breakeven_after_tp1": False,
        "use_kijun_exit": False,
    },
    "aggressive": {
        "preset": "aggressive",
        "min_score": 10,
        "max_open_positions": 7,
        "max_new_positions_per_day": 3,
        "position_capital_pct": 0.25,
        "risk_per_trade_pct": 0.015,
        "min_order_amount": 100_000,
        "min_entry_discount": 0.99,
        "max_entry_premium": 1.03,
        "max_pullback_from_day_high": 0.04,
        "use_kijun_filter": True,
        "use_bb_upper_filter": True,
        "use_day_candle_filter": False,
        "use_breakeven_after_tp1": False,
        "use_kijun_exit": False,
    },
}


def default_strategy_settings() -> dict:
    return PRESETS["balanced"].copy()


def normalize_strategy_settings(row: dict | None) -> dict:
    settings = default_strategy_settings()
    if row:
        settings.update({key: value for key, value in row.items() if value is not None})
    return settings


async def get_strategy_settings(user_id: str) -> dict:
    try:
        rows = await SupabaseRest().select(TABLE, filters={"user_id": f"eq.{user_id}"}, limit=1)
    except RuntimeError:
        return default_strategy_settings()
    return normalize_strategy_settings(rows[0] if rows else None)


async def save_strategy_settings(user_id: str, payload: dict) -> dict:
    preset = payload.get("preset") or "balanced"
    base = PRESETS.get(preset, PRESETS["balanced"]).copy()
    base.update({key: value for key, value in payload.items() if value is not None})
    base["user_id"] = user_id
    rows = await SupabaseRest().upsert(TABLE, base, on_conflict="user_id")
    return normalize_strategy_settings(rows[0])
