from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "KOSPI Swing Bot API"
    environment: str = "local"
    timezone: str = "Asia/Seoul"

    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str

    broker_encryption_key: str

    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    openai_api_key: str | None = None
    ai_report_model: str = "gpt-5"
    ai_report_top_n: int = 3
    ai_report_worker_enabled: bool = True
    ai_report_worker_interval_minutes: int = 5
    admin_report_email: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None

    scheduler_enabled: bool = False
    allow_live_trading: bool = False
    scan_admin_email: str = "zelatool@gmail.com"
    kis_realtime_filter_timeout_seconds: float = 3.0
    kis_position_realtime_watch_seconds: float = 50.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
