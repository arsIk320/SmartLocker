from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env.example", "SmartLocker.env", ".local.env", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "SmartLocker API"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000
    database_url: str = "sqlite:///./smartlocker.db"
    smartlocker_api_base_url: str | None = None

    jwt_secret_key: str = "local-dev-insecure-secret-change-before-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30

    travelline_auth_url: str = "https://partner.tlintegration.com/auth/token"
    travelline_api_base_url: str = "https://partner.tlintegration.com"
    travelline_client_id: str | None = None
    travelline_client_secret: str | None = None
    travelline_property_id: str | None = None
    travelline_timeout_seconds: int = 20

    session_cookie_name: str = "smartlocker_session"
    session_persist_days: int = 30
    session_cookie_secure: bool = False
    session_cookie_samesite: str = "lax"
    admin_email: str = "admin@smartlocker.local"
    admin_password: str = "Admin123!"
    data_encryption_key: str | None = None
    data_encryption_key_legacy: str | None = None
    face_match_distance_threshold: float = 0.92
    face_unlock_distance_threshold: float = 0.68
    face_unlock_min_probe_quality_score: float = 0.55
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    smtp_use_tls: bool = True
    email_delivery_mode: str = "auto"
    email_from_name: str = "SmartLocker"
    brevo_api_key: str | None = None
    telegram_bot_token: str | None = None
    telegram_bot_api_key: str | None = None
    telegram_bot_api_base_url: str = "http://127.0.0.1:8000"
    telegram_bot_api_internal_host: str | None = None
    telegram_bot_api_internal_port: int | None = None
    telegram_bot_webhook_base_url: str | None = None
    telegram_bot_webhook_secret: str | None = None
    telegram_proxy_url: str | None = None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
