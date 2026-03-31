from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import qrcode
from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from telegram_bot.client import SmartLockerTelegramApiClient
from telegram_bot.config import TelegramBotSettings, load_telegram_bot_settings


class GuestFlow(StatesGroup):
    waiting_for_binding_name = State()
    waiting_for_face_photo = State()


@dataclass
class TelegramBotRuntime:
    settings: TelegramBotSettings
    bot: Bot
    dispatcher: Dispatcher


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Мои QR-коды", callback_data="menu:qr"),
                InlineKeyboardButton(text="Привязать бронь", callback_data="menu:bind"),
            ],
            [
                InlineKeyboardButton(text="Фото лица", callback_data="menu:face"),
                InlineKeyboardButton(text="Помощь", callback_data="menu:help"),
            ],
        ]
    )


def back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Назад в меню", callback_data="menu:home")],
        ]
    )


def build_qr_image(payload: str) -> BufferedInputFile:
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(payload)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return BufferedInputFile(buffer.getvalue(), filename="smartlocker_qr.png")


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


def help_text() -> str:
    return (
        "Как пользоваться ботом:\n"
        "1. Нажмите «Привязать бронь» и введите ФИО.\n"
        "2. Выберите свою бронь кнопкой.\n"
        "3. Потом получите QR через «Мои QR-коды».\n"
        "4. Фото для биометрии можно отправить через «Фото лица».\n\n"
        "Каждый QR-код действует 1 час с момента выдачи."
    )


def bookings_keyboard(bookings: list[dict], action: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index, booking in enumerate(bookings):
        label = f"{booking['house_name']} • {booking['door_name']}"
        rows.append([InlineKeyboardButton(text=label[:64], callback_data=f"{action}:{index}")])
    rows.append([InlineKeyboardButton(text="Назад в меню", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send_menu(message: Message, text: str) -> None:
    await message.answer(text, reply_markup=main_menu())


async def send_menu_from_callback(callback: CallbackQuery, text: str) -> None:
    await callback.message.answer(text, reply_markup=main_menu())
    await callback.answer()


async def show_bound_bookings(
    *,
    target_message: Message,
    state: FSMContext,
    api_client: SmartLockerTelegramApiClient,
    action: str,
) -> None:
    result = await api_client.get_bound_bookings(telegram_chat_id=str(target_message.chat.id))
    bookings = result["bookings"]
    if not bookings:
        await target_message.answer(
            "У вас пока нет привязанных броней. Сначала нажмите «Привязать бронь».",
            reply_markup=main_menu(),
        )
        return

    await state.update_data(bound_bookings=bookings)
    prompt = (
        "Выберите бронь для QR-кода:"
        if action == "qr"
        else "Выберите бронь для отправки фото:"
    )
    await target_message.answer(prompt, reply_markup=bookings_keyboard(bookings, action))


async def send_access_card(message: Message, access_data: dict) -> None:
    qr_file = build_qr_image(access_data["qr_payload"]["code"])
    await message.answer(guest_summary(access_data), reply_markup=back_to_menu())
    await message.answer_photo(qr_file, caption="Ваш QR-код для двери", reply_markup=main_menu())


async def create_dispatcher(api_client: SmartLockerTelegramApiClient) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())

    @dp.message(CommandStart())
    @dp.message(Command("start"))
    async def start(message: Message, state: FSMContext) -> None:
        await state.clear()
        await send_menu(
            message,
            "Добро пожаловать в SmartLocker.\nВыберите нужное действие кнопкой ниже.",
        )

    @dp.message(Command("help"))
    async def help_handler(message: Message) -> None:
        await message.answer(help_text(), reply_markup=main_menu())

    @dp.callback_query(F.data == "menu:home")
    async def menu_home(callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        await send_menu_from_callback(
            callback,
            "Главное меню SmartLocker. Выберите действие.",
        )

    @dp.callback_query(F.data == "menu:help")
    async def menu_help(callback: CallbackQuery) -> None:
        await callback.message.answer(help_text(), reply_markup=main_menu())
        await callback.answer()

    @dp.callback_query(F.data == "menu:bind")
    async def menu_bind(callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        await state.set_state(GuestFlow.waiting_for_binding_name)
        await callback.message.answer(
            "Введите ФИО, как в брони.\nПодойдёт полное ФИО или фамилия с именем.",
            reply_markup=back_to_menu(),
        )
        await callback.answer()

    @dp.callback_query(F.data == "menu:qr")
    async def menu_qr(callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        try:
            await show_bound_bookings(
                target_message=callback.message,
                state=state,
                api_client=api_client,
                action="qr",
            )
        except Exception as exc:
            await callback.message.answer(
                f"Не удалось получить список броней: {exc}",
                reply_markup=main_menu(),
            )
        await callback.answer()

    @dp.callback_query(F.data == "menu:face")
    async def menu_face(callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        try:
            await show_bound_bookings(
                target_message=callback.message,
                state=state,
                api_client=api_client,
                action="face",
            )
        except Exception as exc:
            await callback.message.answer(
                f"Не удалось получить список броней: {exc}",
                reply_markup=main_menu(),
            )
        await callback.answer()

    @dp.message(GuestFlow.waiting_for_binding_name)
    async def full_name(message: Message, state: FSMContext) -> None:
        guest_query = (message.text or "").strip()
        if not guest_query:
            await message.answer("Нужно ввести ФИО текстом.", reply_markup=back_to_menu())
            return

        try:
            result = await api_client.search_guest_bookings(guest_query=guest_query)
        except Exception as exc:
            await message.answer(f"Не удалось найти брони: {exc}", reply_markup=main_menu())
            await state.clear()
            return

        bookings = result["bookings"]
        await state.update_data(search_bookings=bookings, guest_query=guest_query)
        await message.answer(
            "Выберите вашу бронь:",
            reply_markup=bookings_keyboard(bookings, "bind"),
        )

    @dp.callback_query(F.data.startswith("bind:"))
    async def bind_callback(callback: CallbackQuery, state: FSMContext) -> None:
        data = await state.get_data()
        bookings = data.get("search_bookings", [])
        if not bookings:
            await callback.answer("Список броней устарел. Начните заново.", show_alert=True)
            return

        index = int(callback.data.split(":")[1])
        if index >= len(bookings):
            await callback.answer("Эта бронь недоступна.", show_alert=True)
            return

        booking = bookings[index]
        try:
            await api_client.bind_booking(
                reservation_code=booking["reservation_external_id"],
                telegram_chat_id=str(callback.message.chat.id),
            )
        except Exception as exc:
            await callback.message.answer(
                f"Не удалось привязать бронь: {exc}",
                reply_markup=main_menu(),
            )
            await state.clear()
            await callback.answer()
            return

        await state.clear()
        await callback.message.answer(
            f"Бронь {booking['reservation_external_id']} привязана к вашему Telegram.",
            reply_markup=main_menu(),
        )
        await callback.answer("Бронь привязана")

    @dp.callback_query(F.data.startswith("qr:"))
    async def qr_callback(callback: CallbackQuery, state: FSMContext) -> None:
        data = await state.get_data()
        bookings = data.get("bound_bookings", [])
        index = int(callback.data.split(":")[1])
        if index >= len(bookings):
            await callback.answer("Эта бронь недоступна.", show_alert=True)
            return

        booking = bookings[index]
        try:
            access_data = await api_client.lookup_guest_access(
                reservation_code=booking["reservation_external_id"],
            )
        except Exception as exc:
            await callback.message.answer(
                f"Не удалось получить доступ: {exc}",
                reply_markup=main_menu(),
            )
            await state.clear()
            await callback.answer()
            return

        await state.clear()
        await send_access_card(callback.message, access_data)
        await callback.answer()

    @dp.callback_query(F.data.startswith("face:"))
    async def face_callback(callback: CallbackQuery, state: FSMContext) -> None:
        data = await state.get_data()
        bookings = data.get("bound_bookings", [])
        index = int(callback.data.split(":")[1])
        if index >= len(bookings):
            await callback.answer("Эта бронь недоступна.", show_alert=True)
            return

        booking = bookings[index]
        await state.update_data(
            reservation_code=booking["reservation_external_id"],
            guest_query=booking["guest_name"],
        )
        await state.set_state(GuestFlow.waiting_for_face_photo)
        await callback.message.answer(
            "Отправьте одно фото лица сообщением Telegram.",
            reply_markup=back_to_menu(),
        )
        await callback.answer()

    @dp.message(GuestFlow.waiting_for_face_photo, F.photo)
    async def face_photo(message: Message, state: FSMContext, bot: Bot) -> None:
        data = await state.get_data()
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        content = await bot.download_file(file.file_path)
        try:
            result = await api_client.upload_face_photo(
                reservation_code=data["reservation_code"],
                guest_query=data["guest_query"],
                telegram_chat_id=str(message.chat.id),
                content=content.read(),
            )
        except Exception as exc:
            await message.answer(
                f"Не удалось отправить фото: {exc}",
                reply_markup=main_menu(),
            )
            await state.clear()
            return

        await message.answer(
            f"Фото получено и сохранено.\nID заявки: {result['submission_id']}\nСтатус: {result['status']}",
            reply_markup=main_menu(),
        )
        await state.clear()

    @dp.message(GuestFlow.waiting_for_face_photo)
    async def face_photo_invalid(message: Message) -> None:
        await message.answer(
            "Нужно отправить именно фото сообщением Telegram.",
            reply_markup=back_to_menu(),
        )

    return dp


def create_bot(settings: TelegramBotSettings) -> Bot:
    session = AiohttpSession(proxy=settings.proxy_url) if settings.proxy_url else AiohttpSession()
    return Bot(token=settings.token, session=session)


async def create_runtime(settings: TelegramBotSettings | None = None) -> TelegramBotRuntime:
    resolved_settings = settings or load_telegram_bot_settings()
    bot = create_bot(resolved_settings)
    api_client = SmartLockerTelegramApiClient(
        api_base_url=resolved_settings.api_base_url,
        api_key=resolved_settings.api_key,
    )
    dispatcher = await create_dispatcher(api_client)
    return TelegramBotRuntime(
        settings=resolved_settings,
        bot=bot,
        dispatcher=dispatcher,
    )


async def shutdown_runtime(runtime: TelegramBotRuntime) -> None:
    await runtime.bot.session.close()


async def run_polling() -> None:
    runtime = await create_runtime()
    try:
        await runtime.dispatcher.start_polling(runtime.bot)
    finally:
        await shutdown_runtime(runtime)


async def main() -> None:
    await run_polling()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
