from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha1

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session
from starlette.requests import ClientDisconnect

from app.core.config import Settings, get_settings
from app.modules.access_logs.service import AccessAttemptLogService
from app.modules.biometrics.face_map import FaceMapError
from app.modules.biometrics.service import FaceVerificationService
from app.db import get_db
from app.db.models import AccessGrantModel
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


def get_face_verification_service(
    db: Session = Depends(get_db),
    encryption: EncryptionService = Depends(get_encryption_service),
) -> FaceVerificationService:
    return FaceVerificationService(db=db, encryption=encryption)


def get_access_attempt_log_service(
    db: Session = Depends(get_db),
    encryption: EncryptionService = Depends(get_encryption_service),
) -> AccessAttemptLogService:
    return AccessAttemptLogService(db=db, encryption=encryption)


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


@router.post("/debug/upload")
async def debug_upload_image(request: Request):
    try:
        payload = await request.body()
    except ClientDisconnect:
        return {
            "ok": False,
            "reason": "client_disconnected",
            "content_type": request.headers.get("content-type", ""),
            "content_length": 0,
            "sha1": "",
        }
    return {
        "ok": True,
        "content_type": request.headers.get("content-type", ""),
        "content_length": len(payload),
        "sha1": sha1(payload).hexdigest() if payload else "",
    }


@router.post("/face/verify")
async def verify_face_for_lock(
    request: Request,
    x_booking_code: str | None = Header(default=None, alias="X-Booking-Code"),
    device=Depends(require_lock_device),
    db: Session = Depends(get_db),
    verification_service: FaceVerificationService = Depends(get_face_verification_service),
    access_log_service: AccessAttemptLogService = Depends(get_access_attempt_log_service),
    settings: Settings = Depends(get_settings),
):
    if device.door is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Lock is not bound to a door.")

    content_type = (request.headers.get("content-type") or "").lower()
    reservation_external_id = (x_booking_code or "").strip()
    image_bytes = b""

    if content_type.startswith("image/jpeg") or content_type.startswith("image/jpg"):
        try:
            image_bytes = await request.body()
        except ClientDisconnect:
            return {
                "open_door": False,
                "door_uid": device.door.door_uid,
                "reason": "client_disconnected",
                "booking_code": reservation_external_id,
                "image_received": False,
            }
    elif content_type.startswith("multipart/form-data"):
        form = await request.form()
        reservation_external_id = reservation_external_id or str(form.get("booking_code", "")).strip()
        image = form.get("image")
        if image is not None and hasattr(image, "read"):
            try:
                image_bytes = await image.read()
            except ClientDisconnect:
                return {
                    "open_door": False,
                    "door_uid": device.door.door_uid,
                    "reason": "client_disconnected",
                    "booking_code": reservation_external_id,
                    "image_received": False,
                }
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing image payload.")

    if not image_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Image payload is empty.")

    if not reservation_external_id:
        now = datetime.now(UTC)
        active_grant = (
            db.query(AccessGrantModel)
            .filter(
                AccessGrantModel.door_id == device.door.id,
                AccessGrantModel.status == "active",
                AccessGrantModel.valid_from <= now,
                AccessGrantModel.valid_to >= now,
            )
            .order_by(AccessGrantModel.valid_from.desc())
            .first()
        )
        if active_grant is None:
            access_log_service.record_attempt(
                owner_email=device.owner_email,
                method="face",
                source="lock_face",
                result="denied",
                reason="no_active_reservation",
                door_uid=device.door.door_uid,
            )
            return {
                "open_door": False,
                "door_uid": device.door.door_uid,
                "reason": "no_active_reservation",
                "booking_code": "",
                "image_received": True,
            }
        reservation_external_id = active_grant.reservation_external_id

    try:
        result = verification_service.compare_probe(
            owner_email=device.owner_email,
            reservation_external_id=reservation_external_id,
            image_bytes=image_bytes,
            threshold_override=settings.face_unlock_distance_threshold,
            min_probe_quality_score=settings.face_unlock_min_probe_quality_score,
        )
    except FaceMapError as exc:
        access_log_service.record_attempt(
            owner_email=device.owner_email,
            method="face",
            source="lock_face",
            result="denied",
            reason="face_map_error",
            reservation_external_id=reservation_external_id,
            door_uid=device.door.door_uid,
        )
        return {
            "open_door": False,
            "door_uid": device.door.door_uid,
            "reason": "face_map_error",
            "booking_code": reservation_external_id,
            "error": str(exc),
            "image_received": True,
        }
    except ValueError as exc:
        access_log_service.record_attempt(
            owner_email=device.owner_email,
            method="face",
            source="lock_face",
            result="denied",
            reason="face_verification_unavailable",
            reservation_external_id=reservation_external_id,
            door_uid=device.door.door_uid,
        )
        return {
            "open_door": False,
            "door_uid": device.door.door_uid,
            "reason": "face_verification_unavailable",
            "booking_code": reservation_external_id,
            "error": str(exc),
            "image_received": True,
        }

    access_log_service.record_attempt(
        owner_email=device.owner_email,
        method="face",
        source="lock_face",
        result="granted" if result.match else "denied",
        reason="face_match" if result.match else "face_mismatch",
        reservation_external_id=result.reservation_external_id,
        door_uid=device.door.door_uid,
        guest_name=result.guest_name,
        distance=result.distance,
        confidence=result.confidence,
        threshold=result.threshold,
        probe_quality_score=result.probe_quality_score,
    )

    return {
        "open_door": result.match,
        "reason": "face_match" if result.match else "face_mismatch",
        "booking_code": reservation_external_id,
        "reservation_external_id": result.reservation_external_id,
        "guest_name": result.guest_name,
        "door_uid": device.door.door_uid,
        "distance": result.distance,
        "confidence": result.confidence,
        "threshold": result.threshold,
        "stored_quality_score": result.stored_quality_score,
        "probe_quality_score": result.probe_quality_score,
        "image_received": True,
    }
