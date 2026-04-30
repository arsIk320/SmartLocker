import subprocess

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ProxyUser
from app.services.xray import read_domains, validate_xray_config


def is_service_active(service_name: str) -> bool:
    result = subprocess.run(
        ["systemctl", "is-active", "--quiet", service_name],
        check=False,
    )
    return result.returncode == 0


def system_health(db: Session) -> dict:
    settings = get_settings()
    users = db.query(ProxyUser).count()
    domains = len(read_domains())
    return {
        "xray_active": is_service_active(settings.xray_service),
        "manager_active": is_service_active("xray-manager"),
        "config_ok": validate_xray_config(),
        "users": users,
        "domains": domains,
    }
