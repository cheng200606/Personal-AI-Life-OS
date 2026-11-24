"""Typed application settings with production safety checks."""

from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables or an optional .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Literal["development", "test", "production"] = "development"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    database_url: str = "sqlite+pysqlite:///./data/lifeos.db"
    data_dir: Path = Path("./data")
    auto_create_schema: bool = True

    access_token_secret: str = "development-only-change-this-secret"
    access_token_ttl_hours: int = 12
    registration_mode: Literal["open", "invitation", "closed"] = "open"
    signup_invite_code: str | None = None
    metrics_token: str | None = None

    max_text_upload_bytes: int = 5 * 1024 * 1024
    max_photo_upload_bytes: int = 20 * 1024 * 1024
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    object_store_backend: Literal["local", "s3"] = "local"
    s3_bucket: str | None = None
    s3_region: str | None = None
    s3_endpoint_url: str | None = None

    model_provider: Literal["none", "openai"] = "none"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    model_disclosure_version: str = "openai-chat-completions-v1"
    model_max_output_tokens: int = 1600
    model_disclosure_data: str = "Selected timeline item dates, titles, source-item IDs, and text for a requested review. A sanitized photo image is sent only when you explicitly request an image description."
    model_disclosure_retention: str = "Review the configured provider's current privacy and retention terms before consenting."
    model_privacy_url: str | None = None
    model_input_cost_per_million_usd: Decimal = Decimal(0)
    model_output_cost_per_million_usd: Decimal = Decimal(0)
    model_max_cost_per_call_usd: Decimal = Decimal("0.10")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @model_validator(mode="after")
    def validate_production_configuration(self) -> "Settings":
        if self.app_env != "production":
            return self
        if self.access_token_secret == "development-only-change-this-secret":
            raise ValueError("ACCESS_TOKEN_SECRET must be set to a unique secret in production.")
        if len(self.access_token_secret) < 32:
            raise ValueError("ACCESS_TOKEN_SECRET must contain at least 32 characters.")
        if self.auto_create_schema:
            raise ValueError("AUTO_CREATE_SCHEMA must be false in production; run Alembic migrations.")
        if self.registration_mode == "open":
            raise ValueError("Open self-registration is not allowed in production.")
        if self.registration_mode == "invitation" and not self.signup_invite_code:
            raise ValueError("SIGNUP_INVITE_CODE is required for invitation registration.")
        if not self.cors_origin_list or any("localhost" in origin or "127.0.0.1" in origin for origin in self.cors_origin_list):
            raise ValueError("CORS_ORIGINS must contain only the deployed HTTPS web origin in production.")
        if not self.metrics_token or len(self.metrics_token) < 32:
            raise ValueError("METRICS_TOKEN must be set to a unique value of at least 32 characters in production.")
        if self.object_store_backend != "s3" or not self.s3_bucket:
            raise ValueError("Production requires a private S3-compatible object store and S3_BUCKET.")
        if self.model_provider == "openai" and not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when MODEL_PROVIDER=openai.")
        if self.model_provider == "openai" and (not self.model_privacy_url or len(self.model_disclosure_retention) < 20):
            raise ValueError("Production external model use requires a privacy URL and explicit retention disclosure.")
        if self.model_provider == "openai" and (
            self.model_input_cost_per_million_usd <= 0
            or self.model_output_cost_per_million_usd <= 0
            or self.model_max_cost_per_call_usd <= 0
        ):
            raise ValueError("Production external model use requires current per-token pricing and a positive per-call budget.")
        return self


settings = Settings()
