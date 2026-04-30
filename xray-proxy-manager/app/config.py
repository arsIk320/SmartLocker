from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="/etc/xray-manager.env", env_prefix="XRAY_MANAGER_")

    domain: str = "vpn.example.com"
    server_port: int = 443
    ui_host: str = "127.0.0.1"
    ui_port: int = 8080
    database_url: str = "sqlite:////etc/xray/manager.sqlite3"
    xray_config_path: str = "/etc/xray/config.json"
    domains_path: str = "/etc/xray/domains.json"
    cert_path: str = "/etc/letsencrypt/live/vpn.example.com/fullchain.pem"
    key_path: str = "/etc/letsencrypt/live/vpn.example.com/privkey.pem"
    access_log_path: str = "/var/log/xray/access.log"
    error_log_path: str = "/var/log/xray/error.log"
    remark_prefix: str = "smartlocker"
    xray_service: str = "xray"


@lru_cache
def get_settings() -> Settings:
    return Settings()
