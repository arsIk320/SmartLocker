from dataclasses import dataclass

from app.core.config import get_settings


@dataclass
class TelegramBotSettings:
    token: str
    api_key: str
    api_base_url: str
    proxy_url: str | None


def load_telegram_bot_settings() -> TelegramBotSettings:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required for telegram bot.")
    if not settings.telegram_bot_api_key:
        raise RuntimeError("TELEGRAM_BOT_API_KEY is required for telegram bot.")
    api_base_url = ""
    if settings.telegram_bot_webhook_base_url:
        if settings.telegram_bot_api_internal_host and settings.telegram_bot_api_internal_port:
            api_base_url = (
                f"http://{settings.telegram_bot_api_internal_host}:{settings.telegram_bot_api_internal_port}"
            )
        else:
            api_base_url = f"http://127.0.0.1:{settings.port}"
    else:
        api_base_url = (settings.telegram_bot_api_base_url or "").strip()
        if not api_base_url:
            if settings.telegram_bot_api_internal_host and settings.telegram_bot_api_internal_port:
                api_base_url = (
                    f"http://{settings.telegram_bot_api_internal_host}:{settings.telegram_bot_api_internal_port}"
                )
            else:
                raise RuntimeError(
                    "TELEGRAM_BOT_API_BASE_URL or TELEGRAM_BOT_API_INTERNAL_HOST/PORT is required for telegram bot."
                )
    return TelegramBotSettings(
        token=settings.telegram_bot_token,
        api_key=settings.telegram_bot_api_key,
        api_base_url=api_base_url.rstrip("/"),
        proxy_url=settings.telegram_proxy_url,
    )
