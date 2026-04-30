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


class StrategySettingsOut(StrategySettingsIn):
    user_id: str | None = None
