from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    app_name: str = "НарядAI API"
    app_timezone: str = "Asia/Qostanay"
    public_base_url: str = "http://localhost:5173"
    database_url: SecretStr | None = None
    session_secret: SecretStr | None = None
    session_cookie_secure: bool = False
    telegram_bot_token: SecretStr | None = None
    telegram_bot_username: str | None = None
    telegram_webhook_secret: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    ai_model: str | None = None
    photo_storage_path: Path = REPO_ROOT / "data" / "photos"


settings = Settings()
