from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.modules.auth.service import AuthService
from app.modules.locks.service import LockDeviceService
from app.modules.locks.qr_service import QrAccessService
from app.modules.properties.service import PropertyService
from app.services.encryption import EncryptionService

router = APIRouter(prefix="/client", tags=["client"])


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict[str, str | bool]


class HouseCreateRequest(BaseModel):
    name: str
    address: str


class DoorCreateRequest(BaseModel):
    house_id: str
    name: str
    lock_label: str
    travelline_unit_id: str | None = None


class BindLockRequest(BaseModel):
    lock_uid: str


class SaveLockRequest(BaseModel):
    device_id: str | None = None
    lock_id: str
    device_name: str
    wifi_ssid: str
    wifi_password: str
    port_name: str = ""
    door_id: str | None = None
    esp8266_uid: str = ""
    esp32_uid: str = ""


class RotateQrResponse(BaseModel):
    code: str
    door_uid: str
    issued_at: str
    expires_at: str
    ttl_seconds: int
    valid_for_seconds: int
    rotated: int | None = None


def get_auth_service(request: Request) -> AuthService:
    return request.app.state.auth_service


def get_encryption_service(request: Request) -> EncryptionService:
    return request.app.state.encryption_service


def get_property_service(
    db: Session = Depends(get_db),
    encryption: EncryptionService = Depends(get_encryption_service),
) -> PropertyService:
    return PropertyService(db=db, encryption=encryption)


def get_lock_device_service(
    db: Session = Depends(get_db),
    encryption: EncryptionService = Depends(get_encryption_service),
) -> LockDeviceService:
    return LockDeviceService(db=db, encryption=encryption)


def get_qr_access_service(
    db: Session = Depends(get_db),
    encryption: EncryptionService = Depends(get_encryption_service),
) -> QrAccessService:
    return QrAccessService(db=db, encryption=encryption)


def require_api_user(
    authorization: str | None = Header(default=None),
    auth_service: AuthService = Depends(get_auth_service),
):
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Authorization header.")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Authorization header.")

    user = auth_service.decode_session_token(token.strip())
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token.")
    return user


def export_user_payload(auth_service: AuthService, user) -> dict[str, str | bool]:
    payload = auth_service.export_user_view(user)
    payload["email"] = user.email
    payload["role"] = user.role
    payload["is_verified"] = user.is_verified
    return payload


@router.post("/auth/login", response_model=LoginResponse)
async def client_login(payload: LoginRequest, auth_service: AuthService = Depends(get_auth_service)):
    try:
        user = auth_service.authenticate(email=payload.email, password=payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    return LoginResponse(
        access_token=auth_service.create_session_token(user),
        user=export_user_payload(auth_service, user),
    )


@router.get("/auth/me")
async def client_me(
    user=Depends(require_api_user),
    auth_service: AuthService = Depends(get_auth_service),
):
    return {"user": export_user_payload(auth_service, user)}


@router.get("/objects")
async def list_objects(
    user=Depends(require_api_user),
    property_service: PropertyService = Depends(get_property_service),
):
    houses = [property_service.export_house_view(item) for item in property_service.list_houses(user.email)]
    return {"houses": houses}


@router.post("/objects/houses")
async def create_house(
    payload: HouseCreateRequest,
    user=Depends(require_api_user),
    property_service: PropertyService = Depends(get_property_service),
):
    house = property_service.add_house(user.email, name=payload.name, address=payload.address)
    return {"house": property_service.export_house_view(house)}


@router.post("/objects/doors")
async def create_door(
    payload: DoorCreateRequest,
    user=Depends(require_api_user),
    property_service: PropertyService = Depends(get_property_service),
):
    door = property_service.add_door(
        user.email,
        house_id=payload.house_id,
        name=payload.name,
        lock_label=payload.lock_label,
        travelline_unit_id=payload.travelline_unit_id,
    )
    return {
        "door": {
            "id": door.id,
            "door_uid": door.door_uid,
            "name": door.name,
            "travelline_unit_id": door.travelline_unit_id,
        }
    }


@router.post("/doors/{door_id}/bind-lock")
async def bind_lock(
    door_id: str,
    payload: BindLockRequest,
    user=Depends(require_api_user),
    property_service: PropertyService = Depends(get_property_service),
):
    try:
        door = property_service.bind_lock_uid(user.email, door_id=door_id, lock_uid=payload.lock_uid)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return {"door_id": door.id, "door_uid": door.door_uid, "lock_uid_bound": True}


@router.get("/doors/{door_id}/qr/current", response_model=RotateQrResponse)
async def get_current_qr_code(
    door_id: str,
    user=Depends(require_api_user),
    property_service: PropertyService = Depends(get_property_service),
    qr_service: QrAccessService = Depends(get_qr_access_service),
):
    door = property_service._get_door(owner_email=user.email, door_id=door_id)
    return qr_service.get_current_qr_payload(door)


@router.post("/doors/{door_id}/qr/rotate", response_model=RotateQrResponse)
async def rotate_qr_code(
    door_id: str,
    user=Depends(require_api_user),
    property_service: PropertyService = Depends(get_property_service),
    qr_service: QrAccessService = Depends(get_qr_access_service),
):
    door = property_service._get_door(owner_email=user.email, door_id=door_id)
    return qr_service.rotate_qr_secret(door)


@router.get("/locks")
async def list_locks(
    user=Depends(require_api_user),
    lock_device_service: LockDeviceService = Depends(get_lock_device_service),
):
    return {"devices": lock_device_service.list_devices(user.email)}


@router.post("/locks")
async def save_lock(
    request: Request,
    payload: SaveLockRequest,
    user=Depends(require_api_user),
    lock_device_service: LockDeviceService = Depends(get_lock_device_service),
):
    try:
        device = lock_device_service.save_device(
            user.email,
            device_id=payload.device_id,
            lock_id=payload.lock_id,
            device_name=payload.device_name,
            wifi_ssid=payload.wifi_ssid,
            wifi_password=payload.wifi_password,
            port_name=payload.port_name,
            door_id=payload.door_id,
            esp8266_uid=payload.esp8266_uid,
            esp32_uid=payload.esp32_uid,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    settings = request.app.state.settings
    api_base_url = (
        str(settings.smartlocker_api_base_url).rstrip("/")
        if settings.smartlocker_api_base_url
        else str(request.base_url).rstrip("/")
    )
    return {
        "device": lock_device_service.export_view(device),
        "provisioning": lock_device_service.export_provisioning_view(device, api_base_url=api_base_url),
    }


@router.delete("/locks/{device_id}")
async def delete_lock(
    device_id: str,
    user=Depends(require_api_user),
    lock_device_service: LockDeviceService = Depends(get_lock_device_service),
):
    try:
        lock_device_service.delete_device(user.email, device_id=device_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"ok": True, "deleted": True, "device_id": device_id}


@router.get("/admin/users")
async def admin_users(
    user=Depends(require_api_user),
    auth_service: AuthService = Depends(get_auth_service),
):
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")
    return {"users": [auth_service.export_user_view(item) for item in auth_service.list_users()]}
