import json
import os
import subprocess
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ProxyUser


def ensure_runtime_files() -> None:
    settings = get_settings()
    Path(settings.xray_config_path).parent.mkdir(parents=True, exist_ok=True)
    Path(settings.domains_path).parent.mkdir(parents=True, exist_ok=True)
    Path(settings.access_log_path).parent.mkdir(parents=True, exist_ok=True)
    Path(settings.error_log_path).parent.mkdir(parents=True, exist_ok=True)

    if not Path(settings.domains_path).exists():
        write_domains([])

    for file_path in (settings.domains_path,):
        os.chmod(file_path, 0o600)


def read_domains() -> list[str]:
    settings = get_settings()
    path = Path(settings.domains_path)
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    domains = payload.get("domains", [])
    cleaned = sorted({domain.strip().lower() for domain in domains if domain and domain.strip()})
    return cleaned


def write_domains(domains: list[str]) -> None:
    settings = get_settings()
    normalized = sorted({domain.strip().lower() for domain in domains if domain and domain.strip()})
    payload = {"domains": normalized}
    Path(settings.domains_path).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.chmod(settings.domains_path, 0o600)


def render_xray_config(users: list[ProxyUser], domains: list[str]) -> dict:
    settings = get_settings()
    return {
        "log": {
            "loglevel": "warning",
            "access": settings.access_log_path,
            "error": settings.error_log_path,
        },
        "inbounds": [
            {
                "tag": "vless-in",
                "port": settings.server_port,
                "protocol": "vless",
                "settings": {
                    "clients": [{"id": user.uuid, "email": user.name} for user in users if user.enabled],
                    "decryption": "none",
                },
                "streamSettings": {
                    "network": "tcp",
                    "security": "tls",
                    "tlsSettings": {
                        "alpn": ["http/1.1"],
                        "certificates": [
                            {
                                "certificateFile": settings.cert_path,
                                "keyFile": settings.key_path,
                            }
                        ],
                    },
                },
                "sniffing": {
                    "enabled": True,
                    "destOverride": ["http", "tls", "quic"],
                },
            }
        ],
        "outbounds": [
            {"tag": "direct-out", "protocol": "freedom", "settings": {"domainStrategy": "UseIP"}},
            {"tag": "proxy-out", "protocol": "freedom", "settings": {}},
            {"tag": "blocked-out", "protocol": "blackhole", "settings": {}},
        ],
        "routing": {
            "domainStrategy": "AsIs",
            "rules": [
                {
                    "type": "field",
                    "domain": [f"domain:{domain}" for domain in domains],
                    "outboundTag": "proxy-out",
                }
            ]
            if domains
            else [],
        },
    }


def validate_xray_config(config_path: str | None = None) -> bool:
    settings = get_settings()
    path = config_path or settings.xray_config_path
    try:
        result = subprocess.run(
            ["/usr/local/bin/xray", "run", "-test", "-config", path],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0


def write_xray_config(config: dict) -> None:
    settings = get_settings()
    Path(settings.xray_config_path).write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    os.chmod(settings.xray_config_path, 0o600)


def sync_xray(db: Session) -> None:
    users = list(db.query(ProxyUser).order_by(ProxyUser.created_at.asc()))
    domains = read_domains()
    config = render_xray_config(users, domains)
    write_xray_config(config)
    if not validate_xray_config():
        raise RuntimeError("generated Xray configuration failed validation")
    reload_xray()


def reload_xray() -> None:
    settings = get_settings()
    is_active = subprocess.run(
        ["systemctl", "is-active", "--quiet", settings.xray_service],
        check=False,
    )
    if is_active.returncode == 0:
        subprocess.run(["systemctl", "reload", settings.xray_service], check=True)
