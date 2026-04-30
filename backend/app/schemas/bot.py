from pydantic import BaseModel, Field


class BotControlIn(BaseModel):
    enabled: bool


class BotControlOut(BaseModel):
    user_id: str
    enabled: bool


class WatchTickIn(BaseModel):
    test_mode: bool = False
    dry_run: bool = False


class StrategySettingsIn(BaseModel):
    preset: str = "balanced"
    min_score: float = Field(ge=0, le=30)
    max_open_positions: int = Field(ge=1, le=20)
    max_new_positions_per_day: int = Field(ge=1, le=10)
    position_capital_pct: float = Field(gt=0, le=1)
    risk_per_trade_pct: float = Field(gt=0, le=0.1)
    min_order_amount: int = Field(ge=0)
    min_entry_discount: float = Field(gt=0, le=1)
    max_entry_premium: float = Field(ge=1, le=2)
    max_pullback_from_day_high: float = Field(ge=0, le=0.3)
    use_kijun_filter: bool = True
    use_bb_upper_filter: bool = True
    use_day_candle_filter: bool = False
    use_breakeven_after_tp1: bool = False
    use_kijun_exit: bool = False
    use_kijun_reentry_block: bool = True
    use_daily_loss_limit: bool = True
    daily_loss_limit_pct: float = Field(ge=0, le=0.3)
    use_unrealized_loss_limit: bool = True
    unrealized_loss_limit_pct: float = Field(ge=0, le=0.5)
    use_market_crash_filter: bool = True
    market_crash_limit_pct: float = Field(ge=-0.2, le=0)
    commission_tax_pct: float = Field(ge=0, le=0.02)
    use_realtime_liquidity_filter: bool = True
    min_realtime_strength: float = Field(ge=0, le=500)
    min_bid_ask_ratio: float = Field(ge=0, le=10)
    max_realtime_spread_pct: float = Field(ge=0, le=0.2)
    use_stoploss_reentry_block: bool = True
    use_vi_filter: bool = True


class StrategySettingsOut(StrategySettingsIn):
    user_id: str | None = None
