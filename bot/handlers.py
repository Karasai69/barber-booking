from datetime import date
from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from app.booking import now_local
from app.errors import AppError
from app.reminders import REMIND_BEFORE
from bot import keyboards as kbs
from bot import queries as q
from bot.keyboards import BarberCb, CancelCb, ConfirmCb, DayCb, MenuCb, ServiceCb, SlotCb
from bot.queries import run_db

router = Router()

MENU_TEXT = "Выберите действие:"


async def show(
    callback: CallbackQuery,
    text: str,
    markup: InlineKeyboardMarkup,
    alert: str | None = None,
) -> None:
    """Заменяет текст сообщения с кнопками (или шлёт новое, если старое недоступно).
    alert — всплывающее окно; на нажатие кнопки Telegram разрешает ответить один раз."""
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text(text, reply_markup=markup)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc):
                raise
    else:
        await callback.bot.send_message(callback.from_user.id, text, reply_markup=markup)
    await callback.answer(alert, show_alert=alert is not None)


async def client_id_of(callback: CallbackQuery | Message) -> int:
    user = callback.from_user
    return await run_db(q.get_or_create_client, user.id, user.full_name)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await client_id_of(message)
    name = escape(message.from_user.first_name)
    await message.answer(
        f"Привет, {name}! Я помогу записаться в барбершоп.\n\n{MENU_TEXT}",
        reply_markup=kbs.main_menu(),
    )


@router.message(Command("myid"))
async def cmd_myid(message: Message) -> None:
    """Показывает Telegram id — нужен для ADMIN_TELEGRAM_ID и id мастера."""
    await message.answer(f"Ваш Telegram id: <code>{message.from_user.id}</code>")


@router.callback_query(MenuCb.filter(F.action == "home"))
async def on_home(callback: CallbackQuery) -> None:
    await show(callback, MENU_TEXT, kbs.main_menu())


@router.callback_query(MenuCb.filter(F.action == "book"))
async def on_book(callback: CallbackQuery) -> None:
    services = await run_db(q.list_services)
    if not services:
        await show(callback, "Пока нет доступных услуг.", kbs.home_button())
        return
    await show(callback, "Выберите услугу:", kbs.services_kb(services))


@router.callback_query(ServiceCb.filter())
async def on_service(callback: CallbackQuery, callback_data: ServiceCb) -> None:
    barbers = await run_db(q.list_active_barbers)
    if not barbers:
        await show(callback, "Сейчас нет доступных мастеров.", kbs.home_button())
        return
    await show(callback, "Выберите мастера:", kbs.barbers_kb(callback_data.service_id, barbers))


@router.callback_query(BarberCb.filter())
async def on_barber(callback: CallbackQuery, callback_data: BarberCb) -> None:
    days = await run_db(q.available_days, callback_data.barber_id, callback_data.service_id)
    if not days:
        await show(
            callback,
            "У этого мастера нет свободного времени в ближайшие 2 недели.",
            kbs.barbers_kb(callback_data.service_id, await run_db(q.list_active_barbers)),
        )
        return
    await show(
        callback,
        "Выберите день:",
        kbs.days_kb(callback_data.service_id, callback_data.barber_id, days),
    )


@router.callback_query(DayCb.filter())
async def on_day(callback: CallbackQuery, callback_data: DayCb, alert: str | None = None) -> None:
    day = date.fromisoformat(callback_data.day)
    slots = await run_db(q.free_slots, callback_data.barber_id, callback_data.service_id, day)
    if not slots:
        days = await run_db(q.available_days, callback_data.barber_id, callback_data.service_id)
        await show(
            callback,
            "На этот день время уже разобрали. Выберите другой:",
            kbs.days_kb(callback_data.service_id, callback_data.barber_id, days),
            alert,
        )
        return
    await show(
        callback,
        f"{kbs.format_day(day)}. Выберите время:",
        kbs.slots_kb(callback_data.service_id, callback_data.barber_id, slots),
        alert,
    )


@router.callback_query(SlotCb.filter())
async def on_slot(callback: CallbackQuery, callback_data: SlotCb) -> None:
    service = await run_db(q.get_service, callback_data.service_id)
    barber = await run_db(q.get_barber, callback_data.barber_id)
    if service is None or barber is None:
        await show(callback, "Услуга или мастер больше недоступны.", kbs.home_button())
        return
    text = (
        "<b>Проверьте запись</b>\n\n"
        f"Услуга: {escape(service.name)}\n"
        f"Мастер: {escape(barber.name)}\n"
        f"Когда: {kbs.format_dt(kbs.from_ts(callback_data.ts))}\n"
        f"Длительность: {service.duration_min} мин\n"
        f"Цена: {service.price:.0f} ₸"
    )
    await show(
        callback,
        text,
        kbs.confirm_kb(callback_data.service_id, callback_data.barber_id, callback_data.ts),
    )


@router.callback_query(ConfirmCb.filter())
async def on_confirm(callback: CallbackQuery, callback_data: ConfirmCb) -> None:
    client_id = await client_id_of(callback)
    start_at = kbs.from_ts(callback_data.ts)
    try:
        await run_db(
            q.create_appointment,
            client_id,
            callback_data.barber_id,
            callback_data.service_id,
            start_at,
        )
    except AppError as exc:
        day = DayCb(
            service_id=callback_data.service_id,
            barber_id=callback_data.barber_id,
            day=start_at.date().isoformat(),
        )
        # Например, время только что занял другой клиент — показываем свежие слоты.
        await on_day(callback, day, alert=exc.message)
        return
    text = f"✅ Вы записаны на {kbs.format_dt(start_at)}."
    if start_at - now_local() > REMIND_BEFORE:
        text += "\nНапомню за 2 часа до визита."
    await show(callback, text, kbs.main_menu())


@router.callback_query(MenuCb.filter(F.action == "my"))
async def on_my(callback: CallbackQuery, notice: str = "") -> None:
    client_id = await client_id_of(callback)
    appointments = await run_db(q.upcoming_appointments, client_id)
    if not appointments:
        await show(callback, f"{notice}У вас нет предстоящих записей.", kbs.main_menu())
        return
    lines = [
        f"• {kbs.format_dt(a.start_at)} — {escape(a.service_name)}, мастер {escape(a.barber_name)}"
        for a in appointments
    ]
    await show(
        callback,
        f"{notice}<b>Ваши записи:</b>\n" + "\n".join(lines),
        kbs.my_appointments_kb(appointments),
    )


@router.callback_query(CancelCb.filter())
async def on_cancel(callback: CallbackQuery, callback_data: CancelCb) -> None:
    client_id = await client_id_of(callback)
    try:
        await run_db(q.cancel_appointment, callback_data.appointment_id, client_id)
    except AppError as exc:
        await callback.answer(exc.message, show_alert=True)
        return
    await on_my(callback, notice="Запись отменена.\n\n")
