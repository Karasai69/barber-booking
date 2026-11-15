"""Запросы к базе для бота.

Функции синхронные и возвращают простые данные, а не ORM-объекты: бот вызывает
их в отдельном потоке, и после закрытия сессии объекты были бы уже недоступны.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Concatenate

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import booking
from app.database import SessionLocal
from app.models import Appointment, AppointmentStatus, Barber, Client, Service

BOOKING_HORIZON_DAYS = 14


@dataclass(frozen=True)
class ServiceView:
    id: int
    name: str
    price: Decimal
    duration_min: int


@dataclass(frozen=True)
class BarberView:
    id: int
    name: str


@dataclass(frozen=True)
class AppointmentView:
    id: int
    start_at: datetime
    service_name: str
    barber_name: str


async def run_db[**P, T](
    func: Callable[Concatenate[Session, P], T], *args: P.args, **kwargs: P.kwargs
) -> T:
    """Выполняет синхронную функцию с сессией в отдельном потоке,
    чтобы не блокировать event loop бота."""

    def call() -> T:
        with SessionLocal() as db:
            return func(db, *args, **kwargs)

    return await asyncio.to_thread(call)


def get_or_create_client(db: Session, telegram_id: int, name: str) -> int:
    stmt = select(Client.id).where(Client.telegram_id == telegram_id)
    client_id = db.scalar(stmt)
    if client_id is not None:
        return client_id
    client = Client(telegram_id=telegram_id, name=name[:100] or "Клиент")
    db.add(client)
    try:
        db.commit()
    except IntegrityError:
        # Два сообщения пришли одновременно и клиента уже создали — берём его.
        db.rollback()
        return db.scalar(stmt)
    return client.id


def list_services(db: Session) -> list[ServiceView]:
    services = db.scalars(select(Service).order_by(Service.name))
    return [ServiceView(s.id, s.name, s.price, s.duration_min) for s in services]


def get_service(db: Session, service_id: int) -> ServiceView | None:
    s = db.get(Service, service_id)
    return ServiceView(s.id, s.name, s.price, s.duration_min) if s else None


def list_active_barbers(db: Session) -> list[BarberView]:
    barbers = db.scalars(select(Barber).where(Barber.is_active).order_by(Barber.name))
    return [BarberView(b.id, b.name) for b in barbers]


def get_barber(db: Session, barber_id: int) -> BarberView | None:
    b = db.get(Barber, barber_id)
    return BarberView(b.id, b.name) if b and b.is_active else None


def available_days(db: Session, barber_id: int, service_id: int) -> list[date]:
    """Дни в ближайшие две недели, где есть хотя бы один свободный слот."""
    today = booking.now_local().date()
    days = (today + timedelta(days=i) for i in range(BOOKING_HORIZON_DAYS))
    return [d for d in days if booking.get_free_slots(db, barber_id, service_id, d)]


def free_slots(db: Session, barber_id: int, service_id: int, day: date) -> list[datetime]:
    return booking.get_free_slots(db, barber_id, service_id, day)


def create_appointment(
    db: Session, client_id: int, barber_id: int, service_id: int, start_at: datetime
) -> int:
    appointment = booking.create_appointment(db, barber_id, client_id, service_id, start_at)
    return appointment.id


def upcoming_appointments(db: Session, client_id: int) -> list[AppointmentView]:
    stmt = (
        select(Appointment.id, Appointment.start_at, Service.name, Barber.name)
        .join(Service, Appointment.service_id == Service.id)
        .join(Barber, Appointment.barber_id == Barber.id)
        .where(
            Appointment.client_id == client_id,
            Appointment.status == AppointmentStatus.BOOKED,
            Appointment.start_at > booking.now_local(),
        )
        .order_by(Appointment.start_at)
    )
    return [AppointmentView(*row) for row in db.execute(stmt)]


def cancel_appointment(db: Session, appointment_id: int, client_id: int) -> None:
    booking.cancel_by_client(db, appointment_id, client_id)
