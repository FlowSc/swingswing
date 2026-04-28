from pydantic import BaseModel, Field


class BrokerCredentialIn(BaseModel):
    kis_app_key: str = Field(min_length=1)
    kis_app_secret: str = Field(min_length=1)
    kis_account_no: str = Field(min_length=8, max_length=16)
    kis_account_product_code: str = "01"
    mode: str = "paper"
    telegram_chat_id: str | None = None


class BrokerCredentialOut(BaseModel):
    user_id: str
    kis_account_no: str
    kis_account_product_code: str
    mode: str
    telegram_chat_id: str | None = None
    enabled: bool


class BrokerStatusOut(BaseModel):
    configured: bool
    mode: str | None = None
    account_no: str | None = None
    account_product_code: str | None = None
    telegram_chat_id: str | None = None
    enabled: bool = False
