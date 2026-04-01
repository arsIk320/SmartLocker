from fastapi import APIRouter

from app.modules.locks.api_routes import router as locks_router
from app.modules.client_api.routes import router as client_router
from app.modules.max_api.routes import router as max_router
from app.modules.pms.routes import router as pms_router
from app.modules.telegram_api.routes import router as telegram_router

api_router = APIRouter()
api_router.include_router(client_router)
api_router.include_router(locks_router)
api_router.include_router(max_router)
api_router.include_router(telegram_router)
api_router.include_router(pms_router, prefix="/pms", tags=["pms"])
