from dataclasses import dataclass

from app.core.config import get_settings


@dataclass
class MaxBotSettings:
    token: str
    api_key: str
    api_base_url: str
    platform_api_base_url: str
    poll_timeout: int


def load_max_bot_settings() -> MaxBotSettings:
    settings = get_settings()
    if not settings.max_bot_token:
        raise RuntimeError("MAX_BOT_TOKEN is required for max bot.")
    if not settings.max_bot_api_key:
        raise RuntimeError("MAX_BOT_API_KEY is required for max bot.")
    api_base_url = ""
    if settings.max_bot_webhook_base_url:
        if settings.max_bot_api_internal_host and settings.max_bot_api_internal_port:
            api_base_url = f"http://{settings.max_bot_api_internal_host}:{settings.max_bot_api_internal_port}"
        else:
            api_base_url = f"http://127.0.0.1:{settings.port}"
    else:
        api_base_url = (settings.max_bot_api_base_url or "").strip()
        if not api_base_url:
            if settings.max_bot_api_internal_host and settings.max_bot_api_internal_port:
                api_base_url = f"http://{settings.max_bot_api_internal_host}:{settings.max_bot_api_internal_port}"
            else:
                raise RuntimeError(
                    "MAX_BOT_API_BASE_URL or MAX_BOT_API_INTERNAL_HOST/PORT is required for max bot."
                )
    return MaxBotSettings(
        token=settings.max_bot_token,
        api_key=settings.max_bot_api_key,
        api_base_url=api_base_url.rstrip("/"),
        platform_api_base_url=settings.max_platform_api_base_url.rstrip("/"),
        poll_timeout=max(1, min(settings.max_bot_poll_timeout, 90)),
    )
