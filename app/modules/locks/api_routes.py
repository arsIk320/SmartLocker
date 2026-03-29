from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.modules.locks.qr_service import QrAccessService
from app.modules.locks.service import LockDeviceService
from app.services.encryption import EncryptionService
router = APIRouter(prefix="/locks", tags=["locks"])


def get_encryption_service(request: Request) -> EncryptionService:
    return request.app.state.encryption_service


def get_qr_access_service(
    db: Session = Depends(get_db),
    encryption: EncryptionService = Depends(get_encryption_service),
) -> QrAccessService:
    return QrAccessService(db=db, encryption=encryption)


def get_lock_device_service(
    db: Session = Depends(get_db),
    encryption: EncryptionService = Depends(get_encryption_service),
) -> LockDeviceService:
    return LockDeviceService(db=db, encryption=encryption)


def require_lock_device(
    x_lock_id: str | None = Header(default=None, alias="X-Lock-Id"),
    x_lock_api_key: str | None = Header(default=None, alias="X-Lock-Api-Key"),
    lock_service: LockDeviceService = Depends(get_lock_device_service),
):
    if not x_lock_id or not x_lock_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing lock authentication headers.")
    try:
        return lock_service.authenticate_device(lock_id=x_lock_id, api_key=x_lock_api_key)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@router.get("/qr/current")
async def get_current_qr_for_lock(
    device=Depends(require_lock_device),
    qr_service: QrAccessService = Depends(get_qr_access_service),
):
    if device.door is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Замок не привязан к двери.")
    return qr_service.get_current_qr_payload(device.door)


@router.post("/face/verify")
async def verify_face_for_lock(
    booking_code: str = Form(""),
    image: UploadFile | None = File(default=None),
    device=Depends(require_lock_device),
):
    return {
        "open_door": False,
        "booking_code": booking_code,
        "door_uid": device.door.door_uid if device.door else None,
        "reason": "face_verification_not_configured",
        "image_received": image is not None,
    }
