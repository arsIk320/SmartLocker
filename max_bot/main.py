from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

import httpx
import qrcode

from max_bot.client import SmartLockerMaxApiClient
from max_bot.config import load_max_bot_settings
from max_bot.platform import MaxPlatformClient, RecipientRef

logger = logging.getLogger(__name__)

LABEL_QR = "Мои QR-коды"
LABEL_BIND = "Привязать бронь"
LABEL_FACE = "Фото лица"
LABEL_UNBIND = "Отвязать бронь"
LABEL_HELP = "Помощь"
LABEL_HOME = "Назад в меню"

STATE_IDLE = "idle"
STATE_WAITING_FOR_BINDING_NAME = "waiting_for_binding_name"
STATE_WAITING_FOR_BIND_SELECTION = "waiting_for_bind_selection"
STATE_WAITING_FOR_QR_SELECTION = "waiting_for_qr_selection"
STATE_WAITING_FOR_FACE_SELECTION = "waiting_for_face_selection"
STATE_WAITING_FOR_FACE_PHOTO = "waiting_for_face_photo"
STATE_WAITING_FOR_UNBIND_SELECTION = "waiting_for_unbind_selection"


@dataclass
class UserSession:
    state: str = STATE_IDLE
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class IncomingMessage:
    user_id: str
    recipient: RecipientRef
    text: str
    attachments: list[dict[str, Any]]


def help_text() -> str:
    return (
        "Как пользоваться ботом:\n"
        "1. Нажмите «Привязать бронь» и выберите нужную бронь.\n"
        "2. Получайте QR-коды через «Мои QR-коды».\n"
        "3. Загружайте фото через «Фото лица».\n"
        "4. Ненужные брони удаляйте через «Отвязать бронь»."
    )


def guest_summary(data: dict) -> str:
    qr = data["qr_payload"]
    return (
        f"Бронь: {data['reservation_external_id']}\n"
        f"Гость: {data['guest_name']}\n"
        f"Объект: {data['house_name']}\n"
        f"Дверь: {data['door_name']}\n"
        f"UID двери: {data['door_uid']}\n"
        f"Метод доступа: {data['method']}\n"
        f"Создан: {qr['issued_at']}\n"
        f"Действует до: {qr['expires_at']}\n"
        f"Осталось: {qr['ttl_seconds']} сек.\n"
        f"Код: {qr['code']}"
    )


def face_status_label(status: str | None) -> str:
    normalized = str(status or "missing").strip().lower()
    if normalized in {"processed", "processing", "failed", "missing"}:
        return normalized
    return "missing"


def face_status_summary(booking: dict, index: int) -> str:
    status = face_status_label(booking.get("face_profile_status"))
    summary = (
        f"{index}. {booking['reservation_external_id']}\n"
        f"   {booking['house_name']} / {booking['door_name']} - {status}"
    )
    quality = booking.get("face_profile_quality_score")
    if quality is not None and status == "processed":
        summary += f" (quality={float(quality):.2f})"
    error = str(booking.get("face_profile_error") or "").strip()
    if error and status == "failed":
        summary += f"\n   error: {error}"
    return summary


def build_qr_png(payload: str) -> bytes:
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(payload)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def build_message_button(text: str) -> dict[str, str]:
    return {
        "type": "message",
        "text": text,
    }


def build_keyboard(rows: list[list[str]]) -> list[dict[str, Any]]:
    return [
        {
            "type": "inline_keyboard",
            "payload": {
                "buttons": [[build_message_button(text) for text in row] for row in rows],
            },
        }
    ]


def main_menu_attachments() -> list[dict[str, Any]]:
    return build_keyboard(
        [
            [LABEL_QR, LABEL_BIND],
            [LABEL_FACE, LABEL_UNBIND],
            [LABEL_HELP],
        ]
    )


def back_to_menu_attachments() -> list[dict[str, Any]]:
    return build_keyboard([[LABEL_HOME]])


def booking_label(index: int, booking: dict) -> str:
    reservation = str(booking["reservation_external_id"])
    short_reservation = reservation if len(reservation) <= 18 else reservation[-18:]
    return f"{index + 1}. {short_reservation} - {booking['door_name']}"[:128]


def booking_lines(bookings: list[dict]) -> list[str]:
    return [booking_label(index, booking) for index, booking in enumerate(bookings)]


def bookings_attachments(bookings: list[dict]) -> list[dict[str, Any]]:
    rows = [[booking_label(index, booking)] for index, booking in enumerate(bookings)]
    rows.append([LABEL_HOME])
    return build_keyboard(rows)


def normalize_text(value: str) -> str:
    return " ".join(value.strip().lower().split())


def is_home_command(text: str) -> bool:
    return normalize_text(text) in {
        normalize_text("/start"),
        normalize_text("start"),
        normalize_text(LABEL_HOME),
        normalize_text("главное меню"),
    }


def is_help_command(text: str) -> bool:
    return normalize_text(text) in {
        normalize_text("/help"),
        normalize_text("help"),
        normalize_text(LABEL_HELP),
    }


def is_bind_command(text: str) -> bool:
    return normalize_text(text) == normalize_text(LABEL_BIND)


def is_qr_command(text: str) -> bool:
    return normalize_text(text) == normalize_text(LABEL_QR)


def is_face_command(text: str) -> bool:
    return normalize_text(text) == normalize_text(LABEL_FACE)


def is_unbind_command(text: str) -> bool:
    return normalize_text(text) == normalize_text(LABEL_UNBIND)


def parse_selection_index(text: str, total: int) -> int | None:
    match = re.match(r"^\s*(\d+)", text)
    if not match:
        return None
    index = int(match.group(1)) - 1
    if 0 <= index < total:
        return index
    return None


def extract_url(value: Any) -> str | None:
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return value
    if isinstance(value, dict):
        for key in ("url", "download_url", "file_url", "src", "href", "preview_url"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
                return candidate
        for nested in value.values():
            candidate = extract_url(nested)
            if candidate:
                return candidate
    if isinstance(value, list):
        for item in value:
            candidate = extract_url(item)
            if candidate:
                return candidate
    return None


class MaxBotApplication:
    def __init__(
        self,
        *,
        api_client: SmartLockerMaxApiClient,
        platform_client: MaxPlatformClient,
    ) -> None:
        self._api_client = api_client
        self._platform_client = platform_client
        self._sessions: dict[str, UserSession] = {}

    def _get_session(self, user_id: str) -> UserSession:
        return self._sessions.setdefault(user_id, UserSession())

    async def send_menu(self, recipient: RecipientRef, text: str) -> None:
        await self._platform_client.send_message(
            recipient=recipient,
            text=text,
            attachments=main_menu_attachments(),
        )

    async def show_bound_bookings(
        self,
        *,
        incoming: IncomingMessage,
        target_state: str,
    ) -> None:
        session = self._get_session(incoming.user_id)
        result = await self._api_client.get_bound_bookings(max_user_id=incoming.user_id)
        bookings = result["bookings"]
        if not bookings:
            session.state = STATE_IDLE
            session.data.clear()
            await self.send_menu(
                incoming.recipient,
                "У вас пока нет привязанных броней. Сначала нажмите «Привязать бронь».",
            )
            return

        session.state = target_state
        session.data = {"bound_bookings": bookings}
        if target_state == STATE_WAITING_FOR_QR_SELECTION:
            prompt = "Выберите бронь для QR-кода:"
        elif target_state == STATE_WAITING_FOR_UNBIND_SELECTION:
            prompt = "Выберите бронь для отвязки:"
        else:
            prompt = "Выберите бронь для отправки фото:"

        text = prompt + "\n\n" + "\n".join(booking_lines(bookings))
        if target_state == STATE_WAITING_FOR_FACE_SELECTION:
            status_lines = [face_status_summary(booking, index + 1) for index, booking in enumerate(bookings)]
            text += "\n\nТекущий статус face profile:\n" + "\n".join(status_lines)
        text += "\n\nМожно нажать кнопку или отправить номер."

        await self._platform_client.send_message(
            recipient=incoming.recipient,
            text=text,
            attachments=bookings_attachments(bookings),
        )

    async def send_access_card(self, recipient: RecipientRef, access_data: dict) -> None:
        qr_png = build_qr_png(access_data["qr_payload"]["code"])
        upload_payload = await self._platform_client.upload_image(
            content=qr_png,
            filename="smartlocker_qr.png",
            content_type="image/png",
        )
        await self._platform_client.send_message(
            recipient=recipient,
            text=guest_summary(access_data),
            attachments=main_menu_attachments(),
        )
        await self._platform_client.send_message(
            recipient=recipient,
            text="Ваш QR-код для двери",
            attachments=[{"type": "image", "payload": upload_payload}],
        )

    async def extract_photo_bytes(self, attachments: list[dict[str, Any]]) -> bytes | None:
        for attachment in attachments:
            attachment_type = str(attachment.get("type", "")).lower()
            if attachment_type not in {"image", "photo", "file"}:
                continue
            url = extract_url(attachment)
            if not url:
                continue
            return await self._platform_client.download_binary(url)
        return None

    async def handle_message(self, incoming: IncomingMessage) -> None:
        session = self._get_session(incoming.user_id)
        text = incoming.text.strip()

        if is_home_command(text):
            session.state = STATE_IDLE
            session.data.clear()
            await self.send_menu(
                incoming.recipient,
                "Главное меню SmartLocker. Выберите действие.",
            )
            return

        if is_help_command(text):
            await self._platform_client.send_message(
                recipient=incoming.recipient,
                text=help_text(),
                attachments=main_menu_attachments(),
            )
            return

        if is_bind_command(text):
            session.state = STATE_WAITING_FOR_BINDING_NAME
            session.data.clear()
            await self._platform_client.send_message(
                recipient=incoming.recipient,
                text="Введите ФИО, как в брони.\nПодойдёт полное ФИО или фамилия с именем.",
                attachments=back_to_menu_attachments(),
            )
            return

        if is_qr_command(text):
            try:
                await self.show_bound_bookings(
                    incoming=incoming,
                    target_state=STATE_WAITING_FOR_QR_SELECTION,
                )
            except Exception as exc:
                await self.send_menu(incoming.recipient, f"Не удалось получить список броней: {exc}")
            return

        if is_face_command(text):
            try:
                await self.show_bound_bookings(
                    incoming=incoming,
                    target_state=STATE_WAITING_FOR_FACE_SELECTION,
                )
            except Exception as exc:
                await self.send_menu(incoming.recipient, f"Не удалось получить список броней: {exc}")
            return

        if is_unbind_command(text):
            try:
                await self.show_bound_bookings(
                    incoming=incoming,
                    target_state=STATE_WAITING_FOR_UNBIND_SELECTION,
                )
            except Exception as exc:
                await self.send_menu(incoming.recipient, f"Не удалось получить список броней: {exc}")
            return

        if session.state == STATE_WAITING_FOR_BINDING_NAME:
            guest_query = text
            if not guest_query:
                await self._platform_client.send_message(
                    recipient=incoming.recipient,
                    text="Нужно ввести ФИО текстом.",
                    attachments=back_to_menu_attachments(),
                )
                return

            try:
                result = await self._api_client.search_guest_bookings(guest_query=guest_query)
            except Exception as exc:
                session.state = STATE_IDLE
                session.data.clear()
                await self.send_menu(incoming.recipient, f"Не удалось найти брони: {exc}")
                return

            bookings = result["bookings"]
            session.state = STATE_WAITING_FOR_BIND_SELECTION
            session.data = {
                "guest_query": guest_query,
                "search_bookings": bookings,
            }
            await self._platform_client.send_message(
                recipient=incoming.recipient,
                text="Выберите вашу бронь:\n\n" + "\n".join(booking_lines(bookings)) + "\n\nМожно нажать кнопку или отправить номер.",
                attachments=bookings_attachments(bookings),
            )
            return

        if session.state in {
            STATE_WAITING_FOR_BIND_SELECTION,
            STATE_WAITING_FOR_QR_SELECTION,
            STATE_WAITING_FOR_FACE_SELECTION,
            STATE_WAITING_FOR_UNBIND_SELECTION,
        }:
            bookings = session.data.get("search_bookings") or session.data.get("bound_bookings") or []
            index = parse_selection_index(text, len(bookings))
            if index is None:
                await self._platform_client.send_message(
                    recipient=incoming.recipient,
                    text="Нужно выбрать бронь кнопкой или отправить номер из списка.",
                    attachments=back_to_menu_attachments(),
                )
                return

            booking = bookings[index]
            if session.state == STATE_WAITING_FOR_BIND_SELECTION:
                try:
                    await self._api_client.bind_booking(
                        reservation_code=booking["reservation_external_id"],
                        max_user_id=incoming.user_id,
                    )
                except Exception as exc:
                    session.state = STATE_IDLE
                    session.data.clear()
                    await self.send_menu(incoming.recipient, f"Не удалось привязать бронь: {exc}")
                    return

                session.state = STATE_IDLE
                session.data.clear()
                await self.send_menu(
                    incoming.recipient,
                    f"Бронь {booking['reservation_external_id']} привязана к вашему MAX.",
                )
                return

            if session.state == STATE_WAITING_FOR_QR_SELECTION:
                try:
                    access_data = await self._api_client.lookup_guest_access(
                        reservation_code=booking["reservation_external_id"],
                    )
                except Exception as exc:
                    session.state = STATE_IDLE
                    session.data.clear()
                    await self.send_menu(incoming.recipient, f"Не удалось получить доступ: {exc}")
                    return

                session.state = STATE_IDLE
                session.data.clear()
                await self.send_access_card(incoming.recipient, access_data)
                return

            if session.state == STATE_WAITING_FOR_UNBIND_SELECTION:
                try:
                    await self._api_client.unbind_booking(
                        reservation_code=booking["reservation_external_id"],
                        max_user_id=incoming.user_id,
                    )
                except Exception as exc:
                    session.state = STATE_IDLE
                    session.data.clear()
                    await self.send_menu(incoming.recipient, f"Не удалось отвязать бронь: {exc}")
                    return

                session.state = STATE_IDLE
                session.data.clear()
                await self.send_menu(
                    incoming.recipient,
                    f"Бронь {booking['reservation_external_id']} отвязана.",
                )
                return

            current_status = face_status_label(booking.get("face_profile_status"))
            current_error = str(booking.get("face_profile_error") or "").strip()
            session.state = STATE_WAITING_FOR_FACE_PHOTO
            session.data = {
                "reservation_code": booking["reservation_external_id"],
                "guest_query": booking["guest_name"],
            }
            response_text = (
                f"Бронь: {booking['reservation_external_id']}\n"
                f"Текущий статус face profile: {current_status}\n\n"
                "Отправьте одно фото лица сообщением MAX."
            )
            if current_error and current_status == "failed":
                response_text += f"\nПоследняя ошибка обработки: {current_error}"
            await self._platform_client.send_message(
                recipient=incoming.recipient,
                text=response_text,
                attachments=back_to_menu_attachments(),
            )
            return

        if session.state == STATE_WAITING_FOR_FACE_PHOTO:
            try:
                content = await self.extract_photo_bytes(incoming.attachments)
            except Exception as exc:
                await self.send_menu(incoming.recipient, f"Не удалось загрузить фото из MAX: {exc}")
                session.state = STATE_IDLE
                session.data.clear()
                return

            if not content:
                await self._platform_client.send_message(
                    recipient=incoming.recipient,
                    text="Нужно отправить именно фото сообщением MAX.",
                    attachments=back_to_menu_attachments(),
                )
                return

            try:
                result = await self._api_client.upload_face_photo(
                    reservation_code=session.data["reservation_code"],
                    guest_query=session.data["guest_query"],
                    max_user_id=incoming.user_id,
                    content=content,
                )
            except Exception as exc:
                session.state = STATE_IDLE
                session.data.clear()
                await self.send_menu(incoming.recipient, f"Не удалось отправить фото: {exc}")
                return

            session.state = STATE_IDLE
            session.data.clear()
            status_text = str(result.get("face_profile_status") or result.get("status") or "unknown")
            response_text = (
                "Фото получено и сохранено.\n"
                f"ID заявки: {result['submission_id']}\n"
                f"Статус: {status_text}"
            )
            error_text = str(result.get("processing_error") or "").strip()
            if error_text:
                response_text += f"\nОшибка: {error_text}"
            await self.send_menu(incoming.recipient, response_text)
            return

        await self.send_menu(
            incoming.recipient,
            "Добро пожаловать в SmartLocker.\nВыберите нужное действие кнопкой ниже.",
        )

    async def handle_bot_started(self, update: dict[str, Any]) -> None:
        user = update.get("user") or {}
        user_id = user.get("user_id") or user.get("id")
        if user_id is None:
            return
        recipient = RecipientRef(
            user_id=str(user_id),
            chat_id=str(update["chat_id"]) if update.get("chat_id") is not None else None,
        )
        session = self._get_session(str(user_id))
        session.state = STATE_IDLE
        session.data.clear()
        await self.send_menu(
            recipient,
            "Добро пожаловать в SmartLocker.\nВыберите нужное действие кнопкой ниже.",
        )

    async def handle_update(self, update: dict[str, Any]) -> None:
        update_type = update.get("update_type") or update.get("type")
        if update_type == "bot_started":
            await self.handle_bot_started(update)
            return
        if update_type != "message_created":
            return

        message = update.get("message") or {}
        sender = message.get("sender") or {}
        if sender.get("is_bot"):
            return

        user_id = sender.get("user_id") or sender.get("id")
        if user_id is None:
            return

        recipient_payload = message.get("recipient") or {}
        recipient = RecipientRef(
            user_id=str(user_id),
            chat_id=str(recipient_payload["chat_id"]) if recipient_payload.get("chat_id") is not None else None,
        )
        body = message.get("body") or {}
        incoming = IncomingMessage(
            user_id=str(user_id),
            recipient=recipient,
            text=str(body.get("text") or ""),
            attachments=list(body.get("attachments") or []),
        )
        await self.handle_message(incoming)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    settings = load_max_bot_settings()
    api_client = SmartLockerMaxApiClient(
        api_base_url=settings.api_base_url,
        api_key=settings.api_key,
    )
    platform_client = MaxPlatformClient(
        token=settings.token,
        base_url=settings.platform_api_base_url,
    )
    app = MaxBotApplication(
        api_client=api_client,
        platform_client=platform_client,
    )

    marker: int | None = None
    while True:
        try:
            payload = await platform_client.get_updates(
                marker=marker,
                timeout=settings.poll_timeout,
            )
            updates = payload.get("updates") or []
            next_marker = payload.get("marker")
            for update in updates:
                try:
                    await app.handle_update(update)
                except Exception:
                    logger.exception("Failed to handle MAX update")
            if next_marker is not None:
                marker = int(next_marker)
        except httpx.HTTPError:
            logger.exception("MAX polling request failed")
            await asyncio.sleep(5)
        except Exception:
            logger.exception("Unexpected MAX bot error")
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
