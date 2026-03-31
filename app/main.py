from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import api_router
from app.core.config import get_settings
from app.db import create_session_factory, init_db
from app.modules.auth.service import AuthService
from app.services.encryption import EncryptionService
from app.modules.web.routes import router as web_router
from app.modules.web.lock_routes import router as lock_router
from app.web import STATIC_DIR
from telegram_bot.main import create_runtime, shutdown_runtime


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = app.state.settings
    telegram_runtime = None
    webhook_base_url = (settings.telegram_bot_webhook_base_url or "").strip().rstrip("/")
    if settings.telegram_bot_token and webhook_base_url:
        telegram_runtime = await create_runtime()
        app.state.telegram_bot_runtime = telegram_runtime
        webhook_url = f"{webhook_base_url}{settings.api_v1_prefix}/telegram/webhook"
        await telegram_runtime.bot.set_webhook(
            webhook_url,
            secret_token=settings.telegram_bot_webhook_secret or None,
            allowed_updates=telegram_runtime.dispatcher.resolve_used_update_types(),
        )
    else:
        app.state.telegram_bot_runtime = None
    try:
        yield
    finally:
        if telegram_runtime is not None:
            try:
                await telegram_runtime.bot.delete_webhook(drop_pending_updates=False)
            finally:
                await shutdown_runtime(telegram_runtime)


def create_app() -> FastAPI:
    settings = get_settings()
    engine, session_factory = create_session_factory(settings.database_url)
    init_db(engine, settings.database_url)
    encryption_service = EncryptionService(settings=settings)
    app = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.encryption_service = encryption_service
    app.state.auth_service = AuthService(
        settings=settings,
        session_factory=session_factory,
        encryption=encryption_service,
    )
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    app.include_router(web_router)
    app.include_router(lock_router)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/health", tags=["health"])
    async def healthcheck() -> dict[str, str]:
        return {"status": "ok", "environment": settings.app_env}

    return app


app = create_app()
