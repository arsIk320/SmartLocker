import io

import qrcode
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.schemas import UserConnection, UserCreate, UserRead
from app.services.links import build_vless_url
from app.services.users import create_user, delete_user, get_user, list_users
from app.services.xray import sync_xray


router = APIRouter(prefix="/api/users", tags=["users"])
settings = get_settings()


@router.get("", response_model=list[UserRead])
def get_users(db: Session = Depends(get_db)):
    users = list_users(db)
    return [
        UserRead(
            uuid=user.uuid,
            name=user.name,
            enabled=user.enabled,
            created_at=user.created_at,
            vless_url=build_vless_url(user.uuid, user.name),
        )
        for user in users
    ]


@router.post("", response_model=UserRead, status_code=201)
def add_user(payload: UserCreate, db: Session = Depends(get_db)):
    try:
        user = create_user(db, payload.name)
        sync_xray(db)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return UserRead(
        uuid=user.uuid,
        name=user.name,
        enabled=user.enabled,
        created_at=user.created_at,
        vless_url=build_vless_url(user.uuid, user.name),
    )


@router.delete("/{user_uuid}", status_code=204)
def remove_user(user_uuid: str, db: Session = Depends(get_db)):
    if not delete_user(db, user_uuid):
        raise HTTPException(status_code=404, detail="user not found")
    sync_xray(db)


@router.get("/{user_uuid}/connection", response_model=UserConnection)
def user_connection(user_uuid: str, db: Session = Depends(get_db)):
    user = get_user(db, user_uuid)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")

    url = build_vless_url(user.uuid, user.name)
    return UserConnection(
        uuid=user.uuid,
        name=user.name,
        server=settings.domain,
        port=settings.server_port,
        vless_url=url,
    )


@router.get("/{user_uuid}/qrcode")
def user_qrcode(user_uuid: str, db: Session = Depends(get_db)):
    user = get_user(db, user_uuid)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")

    image = qrcode.make(build_vless_url(user.uuid, user.name))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return StreamingResponse(buffer, media_type="image/png")
