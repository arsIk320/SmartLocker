from fastapi import APIRouter, Depends, HTTPException, status

from app.core.config import Settings, get_settings
from app.modules.pms.schemas.travelline import (
    TravelLineConfigStatus,
    TravelLineSyncRequest,
    TravelLineSyncResponse,
)
from app.modules.pms.services import TravelLineSyncService

router = APIRouter(prefix="/travelline")


def get_travelline_service(
    settings: Settings = Depends(get_settings),
) -> TravelLineSyncService:
    return TravelLineSyncService(settings=settings)


@router.get("/config-status", response_model=TravelLineConfigStatus)
async def get_travelline_config_status(
    settings: Settings = Depends(get_settings),
) -> TravelLineConfigStatus:
    return TravelLineConfigStatus(
        configured=bool(
            settings.travelline_client_id
            and settings.travelline_client_secret
            and settings.travelline_property_id
        ),
        api_base_url=settings.travelline_api_base_url,
        auth_url=settings.travelline_auth_url,
        has_client_id=bool(settings.travelline_client_id),
        has_client_secret=bool(settings.travelline_client_secret),
        has_property_id=bool(settings.travelline_property_id),
    )


@router.post("/sync", response_model=TravelLineSyncResponse)
async def sync_travelline_reservations(
    payload: TravelLineSyncRequest,
    service: TravelLineSyncService = Depends(get_travelline_service),
) -> TravelLineSyncResponse:
    try:
        return await service.sync_reservations(payload=payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
