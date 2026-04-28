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

    scheduler_enabled: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
