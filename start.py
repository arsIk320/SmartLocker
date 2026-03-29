import os
from getpass import getpass
from pathlib import Path

import uvicorn

LOCAL_ENV_FILE = Path(".local.env")


def load_local_env_file() -> None:
    if not LOCAL_ENV_FILE.exists():
        return
    for raw_line in LOCAL_ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def save_local_env(values: dict[str, str]) -> None:
    lines = ["# Local SmartLocker settings"]
    for key, value in values.items():
        lines.append(f"{key}={value}")
    LOCAL_ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def apply_local_defaults() -> None:
    defaults = {
        "APP_NAME": "SmartLocker API",
        "APP_ENV": "development",
        "API_V1_PREFIX": "/api/v1",
        "DEBUG": "true",
        "HOST": "127.0.0.1",
        "PORT": "8000",
        "DATABASE_URL": "sqlite:///./smartlocker.db",
        "SMARTLOCKER_API_BASE_URL": "",
        "JWT_SECRET_KEY": "local-dev-insecure-secret-change-before-production",
        "JWT_ALGORITHM": "HS256",
        "JWT_ACCESS_TOKEN_EXPIRE_MINUTES": "30",
        "TRAVELLINE_AUTH_URL": "https://partner.tlintegration.com/auth/token",
        "TRAVELLINE_API_BASE_URL": "https://partner.tlintegration.com",
        "TRAVELLINE_TIMEOUT_SECONDS": "20",
        "SESSION_COOKIE_NAME": "smartlocker_session",
        "SESSION_PERSIST_DAYS": "30",
        "ADMIN_EMAIL": "admin@smartlocker.local",
        "ADMIN_PASSWORD": "Admin123!",
        "EMAIL_DELIVERY_MODE": "console",
        "EMAIL_FROM_NAME": "SmartLocker",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


def prompt_value(label: str, current: str = "", secret: bool = False) -> str:
    suffix = f" [{current}]" if current else ""
    prompt = f"{label}{suffix}: "
    if secret:
        value = getpass(prompt)
    else:
        value = input(prompt).strip()
    return value or current


def run_setup_wizard() -> None:
    print("\nSmartLocker setup wizard")
    print("Нажимайте Enter, чтобы оставить текущее значение.\n")

    configure_database = (
        input("Настроить общую базу данных сейчас? [Y/n]: ").strip().lower()
        not in {"n", "no", "нет"}
    )
    configure_email = (
        input("Настроить отправку email сейчас? [y/N]: ").strip().lower()
        in {"y", "yes", "да"}
    )
    configure_travelline = (
        input("Настроить TravelLine сейчас? [y/N]: ").strip().lower()
        in {"y", "yes", "да"}
    )

    values: dict[str, str] = {}

    if configure_database:
        provider = (
            input("База данных (supabase/sqlite/custom) [supabase]: ").strip().lower()
            or "supabase"
        )
        if provider == "sqlite":
            values["DATABASE_URL"] = prompt_value(
                "DATABASE_URL",
                os.getenv("DATABASE_URL", "sqlite:///./smartlocker.db"),
            )
        else:
            default_supabase = (
                "postgresql+psycopg://postgres.PROJECT_REF:DB_PASSWORD@"
                "aws-0-REGION.pooler.supabase.com:5432/postgres?sslmode=require"
            )
            values["DATABASE_URL"] = prompt_value(
                "DATABASE_URL",
                os.getenv("DATABASE_URL", default_supabase),
            )

    if configure_email:
        provider = (
            input("Провайдер отправки (brevo/console/custom-smtp) [console]: ")
            .strip()
            .lower()
            or "console"
        )
        values["EMAIL_FROM_NAME"] = prompt_value(
            "EMAIL_FROM_NAME",
            os.getenv("EMAIL_FROM_NAME", "SmartLocker"),
        )
        if provider == "brevo":
            values["EMAIL_DELIVERY_MODE"] = "brevo"
            values["BREVO_API_KEY"] = prompt_value(
                "BREVO_API_KEY",
                os.getenv("BREVO_API_KEY", ""),
                secret=True,
            )
            values["SMTP_FROM_EMAIL"] = prompt_value(
                "SMTP_FROM_EMAIL",
                os.getenv("SMTP_FROM_EMAIL", ""),
            )
        elif provider == "custom-smtp":
            values["EMAIL_DELIVERY_MODE"] = "smtp"
            values["SMTP_HOST"] = prompt_value("SMTP_HOST", os.getenv("SMTP_HOST", ""))
            values["SMTP_PORT"] = prompt_value("SMTP_PORT", os.getenv("SMTP_PORT", "587"))
            values["SMTP_USERNAME"] = prompt_value(
                "SMTP_USERNAME",
                os.getenv("SMTP_USERNAME", ""),
            )
            values["SMTP_PASSWORD"] = prompt_value(
                "SMTP_PASSWORD",
                os.getenv("SMTP_PASSWORD", ""),
                secret=True,
            )
            values["SMTP_FROM_EMAIL"] = prompt_value(
                "SMTP_FROM_EMAIL",
                os.getenv("SMTP_FROM_EMAIL", values.get("SMTP_USERNAME", "")),
            )
            values["SMTP_USE_TLS"] = prompt_value(
                "SMTP_USE_TLS",
                os.getenv("SMTP_USE_TLS", "true"),
            )
        else:
            values["EMAIL_DELIVERY_MODE"] = "console"

    if configure_travelline:
        values["TRAVELLINE_CLIENT_ID"] = prompt_value(
            "TRAVELLINE_CLIENT_ID",
            os.getenv("TRAVELLINE_CLIENT_ID", ""),
        )
        values["TRAVELLINE_CLIENT_SECRET"] = prompt_value(
            "TRAVELLINE_CLIENT_SECRET",
            os.getenv("TRAVELLINE_CLIENT_SECRET", ""),
            secret=True,
        )
        values["TRAVELLINE_PROPERTY_ID"] = prompt_value(
            "TRAVELLINE_PROPERTY_ID",
            os.getenv("TRAVELLINE_PROPERTY_ID", ""),
        )

    if values:
        save_local_env(values)
        for key, value in values.items():
            os.environ[key] = value
        print(f"\nНастройки сохранены в {LOCAL_ENV_FILE.resolve()}")
        print("И сервер, и desktop теперь будут читать эти значения автоматически.\n")
    else:
        print("\nНовые настройки не были сохранены.\n")


def print_startup_info() -> None:
    host = os.environ["HOST"]
    port = os.environ["PORT"]
    print("SmartLocker startup configuration")
    print(f"- URL: http://{host}:{port}")
    print(f"- Swagger: http://{host}:{port}/docs")
    print(f"- Admin: {os.environ['ADMIN_EMAIL']} / {os.environ['ADMIN_PASSWORD']}")
    print(f"- Database: {os.environ['DATABASE_URL']}")
    if os.getenv("SMARTLOCKER_API_BASE_URL"):
        print(f"- Remote API for desktop: {os.environ['SMARTLOCKER_API_BASE_URL']}")
    else:
        print("- Desktop mode: direct access to shared database")
    print(f"- Email mode: {os.environ.get('EMAIL_DELIVERY_MODE', 'console')}")
    if os.getenv("TRAVELLINE_CLIENT_ID") and os.getenv("TRAVELLINE_PROPERTY_ID"):
        print("- TravelLine: credentials detected")
    else:
        print("- TravelLine: optional global credentials not fully set")


def main() -> None:
    if "--reset-env" in os.sys.argv and LOCAL_ENV_FILE.exists():
        LOCAL_ENV_FILE.unlink()
        print(f"Удалён файл локальных настроек: {LOCAL_ENV_FILE.resolve()}")
    load_local_env_file()
    apply_local_defaults()
    if "--setup" in os.sys.argv or not LOCAL_ENV_FILE.exists():
        run_setup_wizard()
    print_startup_info()
    uvicorn.run(
        "app.main:app",
        host=os.environ["HOST"],
        port=int(os.environ["PORT"]),
        reload=True,
    )


if __name__ == "__main__":
    main()
