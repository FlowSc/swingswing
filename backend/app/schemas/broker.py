from pydantic import BaseModel, Field


class BrokerCredentialIn(BaseModel):
    kis_app_key: str = Field(min_length=1)
    kis_app_secret: str = Field(min_length=1)
    kis_account_no: str = Field(min_length=8, max_length=16)
    kis_account_product_code: str = "01"
    mode: str = "paper"
    live_order_enabled: bool = False


class TelegramSettingsIn(BaseModel):
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None


class BrokerCredentialOut(BaseModel):
    id: str | None = None
    user_id: str
    label: str | None = None
    kis_account_no: str
    kis_account_product_code: str
    mode: str
    telegram_configured: bool = False
    telegram_chat_id: str | None = None
    enabled: bool
    live_order_enabled: bool = False
    server_live_trading_allowed: bool = False
    is_active: bool = True


class BrokerAccountOut(BrokerCredentialOut):
    pass


class BrokerStatusOut(BaseModel):
    configured: bool
    id: str | None = None
    label: str | None = None
    mode: str | None = None
    account_no: str | None = None
    account_product_code: str | None = None
    telegram_configured: bool = False
    telegram_chat_id: str | None = None
    enabled: bool = False
    live_order_enabled: bool = False
    server_live_trading_allowed: bool = False
    is_active: bool = False


class KisHoldingOut(BaseModel):
    code: str
    name: str | None = None
    qty: int
    avg_price: int | None = None
    current_price: int | None = None
    evaluation_amount: int | None = None
    profit_loss: int | None = None
    profit_loss_rate: float | None = None


class KisAccountOut(BaseModel):
    ok: bool
    error: str | None = None
    account: str
    mode: str
    cash: int | None = None
    orderable_cash: int | None = None
    total_equity: int | None = None
    holdings_count: int = 0
    holdings: list[KisHoldingOut] = Field(default_factory=list)
