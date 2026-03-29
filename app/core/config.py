import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".local.env", "SmartLocker.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = os.getenv("APP_NAME", "SmartLocker API")
    app_env: str = os.getenv("APP_ENV", "development")
    api_v1_prefix: str = os.getenv("API_V1_PREFIX", "/api/v1")
    debug: bool = os.getenv("DEBUG", "false").lower() == "true"
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8000"))
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./smartlocker.db")
    smartlocker_api_base_url: str | None = os.getenv("SMARTLOCKER_API_BASE_URL")

    # Local fallback only. Replace with a real secret in production.
    jwt_secret_key: str = os.getenv(
        "JWT_SECRET_KEY",
        "local-dev-insecure-secret-change-before-production",
    )
    jwt_algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")
    jwt_access_token_expire_minutes: int = int(
        os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30")
    )

    travelline_auth_url: str = os.getenv(
        "TRAVELLINE_AUTH_URL",
        "https://partner.tlintegration.com/auth/token",
    )
    travelline_api_base_url: str = os.getenv(
        "TRAVELLINE_API_BASE_URL",
        "https://partner.tlintegration.com",
    )
    travelline_client_id: str | None = os.getenv("TRAVELLINE_CLIENT_ID")
    travelline_client_secret: str | None = os.getenv("TRAVELLINE_CLIENT_SECRET")
    travelline_property_id: str | None = os.getenv("TRAVELLINE_PROPERTY_ID")
    travelline_timeout_seconds: int = int(os.getenv("TRAVELLINE_TIMEOUT_SECONDS", "20"))

    session_cookie_name: str = os.getenv("SESSION_COOKIE_NAME", "smartlocker_session")
    session_persist_days: int = int(os.getenv("SESSION_PERSIST_DAYS", "30"))
    session_cookie_secure: bool = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"
    session_cookie_samesite: str = os.getenv("SESSION_COOKIE_SAMESITE", "lax")
    admin_email: str = os.getenv("ADMIN_EMAIL", "admin@smartlocker.local")
    admin_password: str = os.getenv("ADMIN_PASSWORD", "Admin123!")
    data_encryption_key: str | None = os.getenv("DATA_ENCRYPTION_KEY")
    smtp_host: str | None = os.getenv("SMTP_HOST")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_username: str | None = os.getenv("SMTP_USERNAME")
    smtp_password: str | None = os.getenv("SMTP_PASSWORD")
    smtp_from_email: str | None = os.getenv("SMTP_FROM_EMAIL")
    smtp_use_tls: bool = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
    email_delivery_mode: str = os.getenv("EMAIL_DELIVERY_MODE", "auto").lower()
    email_from_name: str = os.getenv("EMAIL_FROM_NAME", "SmartLocker")
    brevo_api_key: str | None = os.getenv("BREVO_API_KEY")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
