from urllib.parse import quote

from app.config import get_settings


def build_vless_url(user_uuid: str, user_name: str) -> str:
    settings = get_settings()
    remark = quote(f"{settings.remark_prefix}-{user_name}")
    host = settings.domain
    return (
        f"vless://{user_uuid}@{host}:{settings.server_port}"
        f"?encryption=none&security=tls&sni={host}&type=tcp&headerType=none"
        f"#{remark}"
    )
