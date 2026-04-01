from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db import get_db
from app.modules.properties.service import PropertyService
from app.services.encryption import EncryptionService

router = APIRouter(include_in_schema=False)


def get_encryption_service(request: Request) -> EncryptionService:
    return request.app.state.encryption_service


def get_current_user(request: Request):
    auth_service = request.app.state.auth_service
    settings: Settings = request.app.state.settings
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        return None
    return auth_service.decode_session_token(token)


def get_property_service(
    db: Session = Depends(get_db),
    encryption: EncryptionService = Depends(get_encryption_service),
) -> PropertyService:
    return PropertyService(db=db, encryption=encryption)


@router.post("/dashboard/doors/{door_id}/bind-lock")
async def bind_lock_to_door(
    request: Request,
    door_id: str,
    lock_uid: str = Form(...),
    property_service: PropertyService = Depends(get_property_service),
):
    user = get_current_user(request)
    if user is None or user.role == "admin":
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    try:
        property_service.bind_lock_uid(user.email, door_id=door_id, lock_uid=lock_uid)
    except ValueError as exc:
        return RedirectResponse(
            url=f"/objects?error={quote(str(exc))}",
            status_code=status.HTTP_302_FOUND,
        )

    return RedirectResponse(
        url="/objects?success=%D0%97%D0%B0%D0%BC%D0%BE%D0%BA%20%D1%83%D1%81%D0%BF%D0%B5%D1%88%D0%BD%D0%BE%20%D0%BF%D1%80%D0%B8%D0%B2%D1%8F%D0%B7%D0%B0%D0%BD.",
        status_code=status.HTTP_302_FOUND,
    )
