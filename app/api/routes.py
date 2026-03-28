from fastapi import APIRouter

from app.modules.pms.routes import router as pms_router

api_router = APIRouter()
api_router.include_router(pms_router, prefix="/pms", tags=["pms"])
