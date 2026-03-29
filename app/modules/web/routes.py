from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db import get_db
from app.modules.auth.service import AuthService
from app.modules.pms.connection_service import TravelLineConnectionService
from app.modules.pms.schemas.travelline import TravelLineConnectionConfig, TravelLineSyncRequest
from app.modules.pms.services import TravelLineSyncService
from app.modules.properties.service import PropertyService
from app.services.encryption import EncryptionService
from app.web import get_templates

router = APIRouter(include_in_schema=False)


def get_auth_service(request: Request) -> AuthService:
    return request.app.state.auth_service


def get_encryption_service(request: Request) -> EncryptionService:
    return request.app.state.encryption_service


def get_current_user(request: Request):
    auth_service: AuthService = request.app.state.auth_service
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


def get_travelline_connection_service(
    db: Session = Depends(get_db),
    encryption: EncryptionService = Depends(get_encryption_service),
) -> TravelLineConnectionService:
    return TravelLineConnectionService(db=db, encryption=encryption)


def render(request: Request, template_name: str, context: dict):
    templates = get_templates()
    return templates.TemplateResponse(request=request, name=template_name, context=context)


def form_state(**values: str) -> dict[str, str]:
    return {key: value for key, value in values.items()}


def _build_public_news() -> list[dict[str, str]]:
    return [
        {
            "title": "TravelLine уже подключён",
            "text": "Платформа получает реальные бронирования и готовит выдачу доступов по схеме Дом -> Дверь -> Замок.",
        },
        {
            "title": "Личный кабинет стал рабочим",
            "text": "Пользователь может подключить свой TravelLine, строить структуру объектов и получать Access Grants по найденным броням.",
        },
        {
            "title": "Следующий этап",
            "text": "Усиливаем защиту данных, переносим критичные связи в БД и готовим API-контракт для замка на ESP8266 / Arduino Nano / ESP32-CAM.",
        },
    ]


async def _load_dashboard_data(
    *,
    user_email: str,
    settings: Settings,
    property_service: PropertyService,
    travelline_connection_service: TravelLineConnectionService,
) -> dict[str, object]:
    reservations = []
    travelline_error = None
    connection = travelline_connection_service.get_connection(user_email)
    connection_view = travelline_connection_service.export_view(user_email)

    if connection is not None:
        try:
            sync_service = TravelLineSyncService(settings=settings)
            for property_id in travelline_connection_service.decrypt_property_ids(connection):
                result = await sync_service.sync_reservations(
                    TravelLineSyncRequest(limit=100),
                    connection=TravelLineConnectionConfig(
                        client_id=connection.client_id,
                        client_secret=travelline_connection_service.decrypt_secret(connection),
                        property_id=property_id,
                        auth_url=connection.auth_url,
                        api_base_url=connection.api_base_url,
                        timeout_seconds=settings.travelline_timeout_seconds,
                    ),
                )
                reservations.extend(result.reservations)
            property_service.sync_access_grants(owner_email=user_email, reservations=reservations)
        except Exception as exc:
            travelline_error = str(exc)

    houses = [property_service.export_house_view(item) for item in property_service.list_houses(user_email)]
    mapped_doors: dict[str, dict[str, str]] = {}
    total_doors = 0
    for house in houses:
        total_doors += len(house["doors"])
        for door in house["doors"]:
            unit_id = door["travelline_unit_id"] or ""
            if unit_id:
                mapped_doors[unit_id] = {
                    "house_name": str(house["name"]),
                    "door_name": str(door["name"]),
                    "door_uid": str(door["door_uid"]),
                    "lock_label": str(door["lock_label"]),
                }

    reservation_cards = [
        {"reservation": reservation, "mapping": mapped_doors.get(reservation.unit_external_id or "")}
        for reservation in reservations
    ]

    return {
        "houses": houses,
        "total_doors": total_doors,
        "reservation_cards": reservation_cards,
        "travelline_error": travelline_error,
        "travelline_connection": connection_view,
        "access_grants": property_service.list_access_grants(user_email),
    }


@router.get("/")
async def project_page(request: Request):
    return render(request, "project.html", {"title": "SmartLocker", "news": _build_public_news()})


@router.get("/about")
async def about_page(request: Request):
    return render(request, "about.html", {"title": "О проекте"})


@router.get("/features")
async def features_page(request: Request):
    return render(request, "features.html", {"title": "Возможности"})


@router.get("/news")
async def news_page(request: Request):
    return render(request, "news.html", {"title": "Новости", "news": _build_public_news()})


@router.get("/go")
async def redirect_to_panel(request: Request):
    user = get_current_user(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    return RedirectResponse(
        url="/admin/dashboard" if user.role == "admin" else "/dashboard",
        status_code=status.HTTP_302_FOUND,
    )


@router.get("/login")
async def login_page(request: Request):
    return render(request, "login.html", {"title": "Вход", "error": None, "form": form_state(email="", password="")})


@router.post("/login")
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    auth_service: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings),
):
    try:
        user = auth_service.authenticate(email=email, password=password)
    except ValueError as exc:
        return render(
            request,
            "login.html",
            {"title": "Вход", "error": str(exc), "form": form_state(email=email, password=password)},
        )

    response = RedirectResponse(
        url="/admin/dashboard" if user.role == "admin" else "/dashboard",
        status_code=status.HTTP_302_FOUND,
    )
    response.set_cookie(
        key=settings.session_cookie_name,
        value=auth_service.create_session_token(user),
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,
        max_age=settings.session_persist_days * 24 * 60 * 60,
        expires=settings.session_persist_days * 24 * 60 * 60,
    )
    return response


@router.get("/register")
async def register_page(request: Request):
    return render(
        request,
        "register.html",
        {
            "title": "Регистрация",
            "error": None,
            "form": form_state(full_name="", phone="", email="", birth_date="", password=""),
        },
    )


@router.post("/register")
async def register_submit(
    request: Request,
    full_name: str = Form(...),
    phone: str = Form(...),
    birth_date: date = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    auth_service: AuthService = Depends(get_auth_service),
):
    try:
        user = auth_service.register_user(
            full_name=full_name,
            phone=phone,
            birth_date=birth_date,
            email=email,
            password=password,
        )
    except (ValueError, RuntimeError) as exc:
        return render(
            request,
            "register.html",
            {
                "title": "Регистрация",
                "error": str(exc),
                "form": form_state(
                    full_name=full_name,
                    phone=phone,
                    email=email,
                    birth_date=birth_date.isoformat(),
                    password=password,
                ),
            },
        )
    except Exception as exc:
        return render(
            request,
            "register.html",
            {
                "title": "Регистрация",
                "error": f"Ошибка регистрации: {exc}",
                "form": form_state(
                    full_name=full_name,
                    phone=phone,
                    email=email,
                    birth_date=birth_date.isoformat(),
                    password=password,
                ),
            },
        )

    return RedirectResponse(url=f"/verify?email={quote(user.email)}", status_code=status.HTTP_302_FOUND)


@router.get("/verify")
async def verify_page(request: Request, email: str = ""):
    return render(
        request,
        "verify.html",
        {"title": "Подтверждение email", "error": None, "form": form_state(email=email, code="")},
    )


@router.post("/verify")
async def verify_submit(
    request: Request,
    email: str = Form(...),
    code: str = Form(...),
    auth_service: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings),
):
    try:
        user = auth_service.verify_user(email=email, code=code)
    except ValueError as exc:
        return render(
            request,
            "verify.html",
            {"title": "Подтверждение email", "error": str(exc), "form": form_state(email=email, code=code)},
        )

    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=auth_service.create_session_token(user),
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,
        max_age=settings.session_persist_days * 24 * 60 * 60,
        expires=settings.session_persist_days * 24 * 60 * 60,
    )
    return response


@router.get("/forgot-password")
async def forgot_password_page(request: Request):
    return render(
        request,
        "forgot_password.html",
        {"title": "Сброс пароля", "error": None, "success": None, "form": form_state(email="")},
    )


@router.post("/forgot-password")
async def forgot_password_submit(
    request: Request,
    email: str = Form(...),
    auth_service: AuthService = Depends(get_auth_service),
):
    try:
        auth_service.request_password_reset(email=email)
    except (ValueError, RuntimeError) as exc:
        return render(
            request,
            "forgot_password.html",
            {
                "title": "Сброс пароля",
                "error": str(exc),
                "success": None,
                "form": form_state(email=email),
            },
        )

    return render(
        request,
        "forgot_password.html",
        {
            "title": "Сброс пароля",
            "error": None,
            "success": "Код отправлен на вашу почту. Теперь можно задать новый пароль.",
            "form": form_state(email=email),
        },
    )


@router.get("/reset-password")
async def reset_password_page(request: Request, email: str = ""):
    return render(
        request,
        "reset_password.html",
        {"title": "Новый пароль", "error": None, "form": form_state(email=email, code="", new_password="")},
    )


@router.post("/reset-password")
async def reset_password_submit(
    request: Request,
    email: str = Form(...),
    code: str = Form(...),
    new_password: str = Form(...),
    auth_service: AuthService = Depends(get_auth_service),
):
    try:
        auth_service.confirm_password_reset(email=email, code=code, new_password=new_password)
    except ValueError as exc:
        return render(
            request,
            "reset_password.html",
            {
                "title": "Новый пароль",
                "error": str(exc),
                "form": form_state(email=email, code=code, new_password=new_password),
            },
        )
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)


@router.get("/logout")
async def logout(settings: Settings = Depends(get_settings)):
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(
        settings.session_cookie_name,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,
    )
    return response


@router.get("/dashboard")
async def user_dashboard(
    request: Request,
    settings: Settings = Depends(get_settings),
    property_service: PropertyService = Depends(get_property_service),
    travelline_connection_service: TravelLineConnectionService = Depends(get_travelline_connection_service),
):
    user = get_current_user(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    if user.role == "admin":
        return RedirectResponse(url="/admin/dashboard", status_code=status.HTTP_302_FOUND)

    dashboard_data = await _load_dashboard_data(
        user_email=user.email,
        settings=settings,
        property_service=property_service,
        travelline_connection_service=travelline_connection_service,
    )
    connection_view = dashboard_data["travelline_connection"]
    return render(
        request,
        "dashboard_user.html",
        {
            "title": "Кабинет пользователя",
            "user": user,
            **dashboard_data,
            "travelline_form": form_state(
                client_id=connection_view["client_id"] if connection_view else "",
                property_ids=connection_view["property_ids"] if connection_view else "",
            ),
        },
    )


@router.get("/objects")
async def objects_page(
    request: Request,
    settings: Settings = Depends(get_settings),
    property_service: PropertyService = Depends(get_property_service),
    travelline_connection_service: TravelLineConnectionService = Depends(get_travelline_connection_service),
):
    user = get_current_user(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    if user.role == "admin":
        return RedirectResponse(url="/admin/dashboard", status_code=status.HTTP_302_FOUND)

    dashboard_data = await _load_dashboard_data(
        user_email=user.email,
        settings=settings,
        property_service=property_service,
        travelline_connection_service=travelline_connection_service,
    )
    return render(
        request,
        "objects.html",
        {
            "title": "Объекты",
            "user": user,
            **dashboard_data,
            "house_form": form_state(name="", address=""),
            "door_form": form_state(house_id="", name="", lock_label="", travelline_unit_id=""),
        },
    )


@router.post("/dashboard/houses")
async def create_house(
    request: Request,
    name: str = Form(...),
    address: str = Form(...),
    property_service: PropertyService = Depends(get_property_service),
):
    user = get_current_user(request)
    if user is None or user.role == "admin":
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    property_service.add_house(user.email, name=name, address=address)
    return RedirectResponse(url="/objects", status_code=status.HTTP_302_FOUND)


@router.post("/dashboard/doors")
async def create_door(
    request: Request,
    house_id: str = Form(...),
    name: str = Form(...),
    lock_label: str = Form(...),
    travelline_unit_id: str = Form(""),
    property_service: PropertyService = Depends(get_property_service),
):
    user = get_current_user(request)
    if user is None or user.role == "admin":
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    property_service.add_door(
        user.email,
        house_id=house_id,
        name=name,
        lock_label=lock_label,
        travelline_unit_id=travelline_unit_id,
    )
    return RedirectResponse(url="/objects", status_code=status.HTTP_302_FOUND)


@router.post("/dashboard/travelline")
async def save_travelline_connection(
    request: Request,
    client_id: str = Form(...),
    client_secret: str = Form(...),
    property_ids: str = Form(""),
    travelline_connection_service: TravelLineConnectionService = Depends(get_travelline_connection_service),
    property_service: PropertyService = Depends(get_property_service),
    settings: Settings = Depends(get_settings),
):
    user = get_current_user(request)
    if user is None or user.role == "admin":
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    sync_service = TravelLineSyncService(settings=settings)
    base_connection = TravelLineConnectionConfig(
        client_id=client_id.strip(),
        client_secret=client_secret.strip(),
        property_id="bootstrap",
        auth_url=settings.travelline_auth_url,
        api_base_url=settings.travelline_api_base_url,
        timeout_seconds=settings.travelline_timeout_seconds,
    )

    catalog = await sync_service.fetch_properties_catalog(base_connection)
    fetched_property_ids = [str(item.get("id", "")).strip() for item in catalog if str(item.get("id", "")).strip()]
    selected_property_ids = [item.strip() for item in property_ids.split(",") if item.strip()]
    final_property_ids = selected_property_ids or fetched_property_ids

    travelline_connection_service.save_connection(
        owner_email=user.email,
        client_id=client_id,
        client_secret=client_secret,
        property_ids=final_property_ids,
        auth_url=settings.travelline_auth_url,
        api_base_url=settings.travelline_api_base_url,
    )
    property_service.sync_houses_from_travelline(owner_email=user.email, properties=catalog)
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)


@router.get("/admin/dashboard")
async def admin_dashboard(request: Request):
    user = get_current_user(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    if user.role != "admin":
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)

    auth_service: AuthService = request.app.state.auth_service
    all_users = [auth_service.export_user_view(item) for item in auth_service.list_users()]
    return render(
        request,
        "dashboard_admin.html",
        {"title": "Админ-панель", "user": user, "users": all_users},
    )
