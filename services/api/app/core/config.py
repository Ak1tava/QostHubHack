from pathlib import Path

from pydantic import Field, SecretStr
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
    ai_model: str = "gpt-6.1-sol"
    ai_light_model: str = "gpt-6-luna"
    ai_complex_model: str = "gpt-6-astra"
    ai_reasoning_effort: str = "medium"
    ai_light_reasoning_effort: str = "low"
    ai_complex_reasoning_effort: str = "medium"
    ai_request_timeout_seconds: float = Field(default=90, gt=0, le=120)
    ai_max_output_tokens: int = Field(default=4096, ge=256, le=16384)
    ai_complex_max_output_tokens: int = Field(default=8192, ge=256, le=16384)
    ai_review_lease_seconds: int = Field(default=180, ge=150)
    ai_review_snapshot_restarts: int = Field(default=2, ge=0, le=5)
    ai_review_poll_seconds: float = Field(default=1, ge=0.1)
    photo_storage_path: Path = REPO_ROOT / "data" / "photos"
    speech_service_url: str | None = None
    speech_service_token: SecretStr | None = None
    speech_request_timeout_seconds: float = Field(default=90, gt=0, le=120)
    speech_model_path: Path | None = None
    speech_device: str = "cpu"
    speech_compute_type: str = "int8"


settings = Settings()
