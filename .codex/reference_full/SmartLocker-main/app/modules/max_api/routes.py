from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db import get_db
from app.modules.locks.qr_service import QrAccessService
from app.modules.max_api.service import MaxGuestService
from app.modules.pms.grant_sync_service import TravelLineGrantSyncService
from app.services.encryption import EncryptionService

router = APIRouter(prefix="/max", tags=["max"])


def get_encryption_service(request: Request) -> EncryptionService:
    return request.app.state.encryption_service


def get_qr_access_service(
    db: Session = Depends(get_db),
    encryption: EncryptionService = Depends(get_encryption_service),
) -> QrAccessService:
    return QrAccessService(db=db, encryption=encryption)


def get_max_guest_service(
    db: Session = Depends(get_db),
    encryption: EncryptionService = Depends(get_encryption_service),
    qr_service: QrAccessService = Depends(get_qr_access_service),
) -> MaxGuestService:
    return MaxGuestService(db=db, encryption=encryption, qr_service=qr_service)


def get_travelline_grant_sync_service(
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
    encryption: EncryptionService = Depends(get_encryption_service),
) -> TravelLineGrantSyncService:
    return TravelLineGrantSyncService(settings=settings, db=db, encryption=encryption)


def require_bot_api_key(
    request: Request,
    x_bot_api_key: str | None = Header(default=None),
) -> None:
    expected = request.app.state.settings.max_bot_api_key
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MAX bot API key is not configured.",
        )
    if not x_bot_api_key or x_bot_api_key != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bot API key.",
        )


@router.post("/guest/bookings")
async def search_guest_bookings(
    guest_query: str = Form(...),
    _: None = Depends(require_bot_api_key),
    grant_sync_service: TravelLineGrantSyncService = Depends(get_travelline_grant_sync_service),
    guest_service: MaxGuestService = Depends(get_max_guest_service),
):
    await grant_sync_service.sync_all_connections()
    try:
        results = guest_service.search_guest_accesses(guest_query=guest_query)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return {
        "bookings": [guest_service.serialize_lookup(item) for item in results],
    }


@router.post("/guest/bindings")
async def list_bound_guest_bookings(
    max_user_id: str = Form(...),
    _: None = Depends(require_bot_api_key),
    grant_sync_service: TravelLineGrantSyncService = Depends(get_travelline_grant_sync_service),
    guest_service: MaxGuestService = Depends(get_max_guest_service),
):
    await grant_sync_service.sync_all_connections()
    results = guest_service.get_bound_guest_accesses(max_user_id=max_user_id)
    return {
        "bookings": [guest_service.serialize_lookup(item) for item in results],
    }


@router.post("/guest/bind")
async def bind_guest_booking(
    reservation_code: str = Form(...),
    max_user_id: str = Form(...),
    _: None = Depends(require_bot_api_key),
    guest_service: MaxGuestService = Depends(get_max_guest_service),
):
    try:
        result = guest_service.bind_guest_booking(
            reservation_code=reservation_code,
            max_user_id=max_user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return result


@router.post("/guest/access")
async def lookup_guest_access(
    reservation_code: str = Form(...),
    _: None = Depends(require_bot_api_key),
    guest_service: MaxGuestService = Depends(get_max_guest_service),
):
    try:
        access = guest_service.lookup_guest_access_by_reservation(
            reservation_code=reservation_code,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return guest_service.serialize_lookup(access)


@router.post("/guest/face-photo")
async def upload_face_photo(
    reservation_code: str = Form(...),
    guest_query: str = Form(...),
    max_user_id: str = Form(...),
    photo: UploadFile = File(...),
    _: None = Depends(require_bot_api_key),
    guest_service: MaxGuestService = Depends(get_max_guest_service),
):
    payload = await photo.read()
    if not payload:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Photo file is empty.")
    try:
        result = guest_service.save_face_photo(
            reservation_code=reservation_code,
            guest_query=guest_query,
            max_user_id=max_user_id,
            photo_bytes=payload,
            content_type=photo.content_type or "application/octet-stream",
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return result
