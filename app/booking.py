"""Бизнес-логика записи: свободные слоты, создание записи, смена статуса."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.errors import AppError, ConflictError, NotFoundError, get_or_404
from app.models import Appointment, AppointmentStatus, Barber, Client, Schedule, Service

SLOT_STEP = timedelta(minutes=15)
OVERLAP_CONSTRAINT = "ex_appointments_no_overlap"

# Из «записан» можно перейти в любой итоговый статус. Итоговые статусы не меняются.
ALLOWED_TRANSITIONS = {
    AppointmentStatus.BOOKED: {
        AppointmentStatus.CANCELLED,
        AppointmentStatus.COMPLETED,
        AppointmentStatus.NO_SHOW,
    },
}


def shop_tz() -> ZoneInfo:
    return ZoneInfo(settings.TIMEZONE)


def now_local() -> datetime:
    return datetime.now(shop_tz())


def day_bounds(day: date) -> tuple[datetime, datetime]:
    """Начало и конец дня в часовом поясе барбершопа."""
    start = datetime.combine(day, time.min, tzinfo=shop_tz())
    return start, start + timedelta(days=1)


def _get_active_barber(db: Session, barber_id: int) -> Barber:
    barber = db.get(Barber, barber_id)
    if barber is None or not barber.is_active:
        raise NotFoundError("Мастер не найден")
    return barber


def _fits_schedule(db: Session, barber_id: int, start: datetime, end: datetime) -> bool:
    """Попадает ли интервал целиком в одну смену мастера."""
    local_start = start.astimezone(shop_tz())
    local_end = end.astimezone(shop_tz())
    if local_start.date() != local_end.date():
        return False
    stmt = select(Schedule.id).where(
        Schedule.barber_id == barber_id,
        Schedule.weekday == local_start.weekday(),
        Schedule.start_time <= local_start.time(),
        Schedule.end_time >= local_end.time(),
    )
    return db.scalar(stmt.limit(1)) is not None


def get_free_slots(db: Session, barber_id: int, service_id: int, day: date) -> list[datetime]:
    _get_active_barber(db, barber_id)
    service = get_or_404(db, Service, service_id, "Услуга не найдена")
    duration = timedelta(minutes=service.duration_min)
    day_start, day_end = day_bounds(day)

    shifts = db.scalars(
        select(Schedule).where(
            Schedule.barber_id == barber_id,
            Schedule.weekday == day.weekday(),
        )
    ).all()
    busy = db.execute(
        select(Appointment.start_at, Appointment.end_at).where(
            Appointment.barber_id == barber_id,
            Appointment.status == AppointmentStatus.BOOKED,
            Appointment.start_at < day_end,
            Appointment.end_at > day_start,
        )
    ).all()

    now = now_local()
    slots: set[datetime] = set()
    for shift in shifts:
        slot_start = datetime.combine(day, shift.start_time, tzinfo=shop_tz())
        shift_end = datetime.combine(day, shift.end_time, tzinfo=shop_tz())
        while slot_start + duration <= shift_end:
            slot_end = slot_start + duration
            is_free = all(slot_end <= b_start or slot_start >= b_end for b_start, b_end in busy)
            if slot_start > now and is_free:
                slots.add(slot_start)
            slot_start += SLOT_STEP
    return sorted(slots)


def create_appointment(
    db: Session, barber_id: int, client_id: int, service_id: int, start_at: datetime
) -> Appointment:
    _get_active_barber(db, barber_id)
    get_or_404(db, Client, client_id, "Клиент не найден")
    service = get_or_404(db, Service, service_id, "Услуга не найдена")

    if start_at <= now_local():
        raise AppError("Нельзя записаться на прошедшее время")
    end_at = start_at + timedelta(minutes=service.duration_min)
    if not _fits_schedule(db, barber_id, start_at, end_at):
        raise AppError("Мастер не работает в это время")

    appointment = Appointment(
        barber_id=barber_id,
        client_id=client_id,
        service_id=service_id,
        start_at=start_at,
        end_at=end_at,
        price=service.price,
    )
    db.add(appointment)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # Занятость проверяет ограничение в БД, а не Python: так два одновременных
        # запроса не смогут оба пройти проверку и записаться на одно время.
        if getattr(exc.orig.diag, "constraint_name", None) == OVERLAP_CONSTRAINT:
            raise ConflictError("Это время уже занято") from exc
        raise
    db.refresh(appointment)
    return appointment


def cancel_by_client(db: Session, appointment_id: int, client_id: int) -> Appointment:
    """Клиент отменяет свою будущую запись."""
    appointment = db.get(Appointment, appointment_id)
    # Чужая запись выглядит как несуществующая: не раскрываем, что такой id есть.
    if appointment is None or appointment.client_id != client_id:
        raise NotFoundError("Запись не найдена")
    if appointment.start_at <= now_local():
        raise AppError("Эта запись уже прошла, отменить её нельзя")
    return change_status(db, appointment_id, AppointmentStatus.CANCELLED)


def change_status(db: Session, appointment_id: int, new_status: AppointmentStatus) -> Appointment:
    appointment = get_or_404(db, Appointment, appointment_id, "Запись не найдена")
    if new_status not in ALLOWED_TRANSITIONS.get(appointment.status, set()):
        raise AppError(
            f"Нельзя сменить статус {appointment.status.value} на {new_status.value}"
        )
    appointment.status = new_status
    db.commit()
    db.refresh(appointment)
    return appointment
