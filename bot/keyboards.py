"""Inline-клавиатуры и данные кнопок.

Всё состояние выбора (услуга, мастер, день, время) едет внутри callback_data
кнопок, поэтому боту не нужно хранить шаги диалога и перезапуск ничего не ломает.
"""

from datetime import date, datetime

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.booking import shop_tz
from bot.queries import AppointmentView, BarberView, ServiceView

WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


class MenuCb(CallbackData, prefix="menu"):
    action: str  # home | book | my


class ServiceCb(CallbackData, prefix="svc"):
    service_id: int


class BarberCb(CallbackData, prefix="brb"):
    service_id: int
    barber_id: int


class DayCb(CallbackData, prefix="day"):
    service_id: int
    barber_id: int
    day: str  # YYYY-MM-DD


class SlotCb(CallbackData, prefix="slot"):
    service_id: int
    barber_id: int
    ts: int  # unix-время начала


class ConfirmCb(CallbackData, prefix="cfm"):
    service_id: int
    barber_id: int
    ts: int


class CancelCb(CallbackData, prefix="cnl"):
    appointment_id: int


def format_day(day: date) -> str:
    return f"{WEEKDAYS[day.weekday()]} {day:%d.%m}"


def format_dt(value: datetime) -> str:
    local = value.astimezone(shop_tz())
    return f"{format_day(local.date())} в {local:%H:%M}"


def from_ts(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, shop_tz())


def main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✂️ Записаться", callback_data=MenuCb(action="book"))
    kb.button(text="📋 Мои записи", callback_data=MenuCb(action="my"))
    kb.adjust(1)
    return kb.as_markup()


def home_button() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="« В меню", callback_data=MenuCb(action="home"))
    return kb.as_markup()


def services_kb(services: list[ServiceView]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for s in services:
        kb.button(
            text=f"{s.name} — {s.price:.0f} ₸, {s.duration_min} мин",
            callback_data=ServiceCb(service_id=s.id),
        )
    kb.button(text="« В меню", callback_data=MenuCb(action="home"))
    kb.adjust(1)
    return kb.as_markup()


def barbers_kb(service_id: int, barbers: list[BarberView]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for b in barbers:
        kb.button(text=b.name, callback_data=BarberCb(service_id=service_id, barber_id=b.id))
    kb.button(text="« Назад", callback_data=MenuCb(action="book"))
    kb.adjust(1)
    return kb.as_markup()


def days_kb(service_id: int, barber_id: int, days: list[date]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for d in days:
        kb.button(
            text=format_day(d),
            callback_data=DayCb(service_id=service_id, barber_id=barber_id, day=d.isoformat()),
        )
    kb.adjust(3)
    kb.row()
    kb.button(text="« Назад", callback_data=ServiceCb(service_id=service_id))
    return kb.as_markup()


def slots_kb(service_id: int, barber_id: int, slots: list[datetime]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for slot in slots:
        kb.button(
            text=f"{slot.astimezone(shop_tz()):%H:%M}",
            callback_data=SlotCb(
                service_id=service_id, barber_id=barber_id, ts=int(slot.timestamp())
            ),
        )
    kb.adjust(4)
    kb.row()
    kb.button(
        text="« Другой день",
        callback_data=BarberCb(service_id=service_id, barber_id=barber_id),
    )
    return kb.as_markup()


def confirm_kb(service_id: int, barber_id: int, ts: int) -> InlineKeyboardMarkup:
    day = from_ts(ts).date().isoformat()
    kb = InlineKeyboardBuilder()
    kb.button(
        text="✅ Записаться",
        callback_data=ConfirmCb(service_id=service_id, barber_id=barber_id, ts=ts),
    )
    kb.button(
        text="« Другое время",
        callback_data=DayCb(service_id=service_id, barber_id=barber_id, day=day),
    )
    kb.adjust(1)
    return kb.as_markup()


def my_appointments_kb(appointments: list[AppointmentView]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for a in appointments:
        kb.button(
            text=f"❌ Отменить {format_dt(a.start_at)}",
            callback_data=CancelCb(appointment_id=a.id),
        )
    kb.button(text="« В меню", callback_data=MenuCb(action="home"))
    kb.adjust(1)
    return kb.as_markup()
