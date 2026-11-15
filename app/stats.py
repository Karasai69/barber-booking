"""Данные для кабинета: расписание на день, загрузка и выручка за период."""

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.booking import day_bounds, now_local
from app.errors import AppError
from app.models import Appointment, AppointmentStatus, Barber, Client, Schedule, Service

MAX_PERIOD_DAYS = 93


# --- Расписание на день ---


@dataclass(frozen=True)
class DayAppointment:
    id: int
    start_at: datetime
    end_at: datetime
    status: AppointmentStatus
    price: Decimal
    client_name: str
    client_phone: str | None
    service_name: str
    barber_id: int
    barber_name: str

    @property
    def started(self) -> bool:
        return self.start_at <= now_local()


def day_appointments(db: Session, day: date, barber_id: int | None = None) -> list[DayAppointment]:
    day_start, day_end = day_bounds(day)
    stmt = (
        select(
            Appointment.id,
            Appointment.start_at,
            Appointment.end_at,
            Appointment.status,
            Appointment.price,
            Client.name,
            Client.phone,
            Service.name,
            Barber.id,
            Barber.name,
        )
        .join(Client, Appointment.client_id == Client.id)
        .join(Service, Appointment.service_id == Service.id)
        .join(Barber, Appointment.barber_id == Barber.id)
        .where(Appointment.start_at >= day_start, Appointment.start_at < day_end)
        .order_by(Appointment.start_at, Barber.name)
    )
    if barber_id is not None:
        stmt = stmt.where(Appointment.barber_id == barber_id)
    return [DayAppointment(*row) for row in db.execute(stmt)]


# --- Загрузка и выручка за период ---


@dataclass
class BarberStats:
    barber_id: int | None
    name: str
    total: int = 0
    completed: int = 0
    no_show: int = 0
    cancelled: int = 0
    pending: int = 0  # «записан», но визит ещё не отмечен
    revenue: Decimal = Decimal("0")
    busy_minutes: int = 0  # время всех неотменённых записей
    work_minutes: int = 0  # время смен по графику

    @property
    def load_percent(self) -> int | None:
        if not self.work_minutes:
            return None
        return round(self.busy_minutes * 100 / self.work_minutes)


def _shift_minutes(schedule: Schedule) -> int:
    start = datetime.combine(date.min, schedule.start_time)
    end = datetime.combine(date.min, schedule.end_time)
    return int((end - start).total_seconds() // 60)


def period_stats(db: Session, date_from: date, date_to: date) -> list[BarberStats]:
    """Статистика по мастерам за период (обе даты включительно).

    Рабочее время считается по текущему графику: истории изменений графика
    мы не храним, поэтому для прошлых периодов это приближение.
    """
    days = (date_to - date_from).days + 1
    if days < 1:
        raise AppError("Дата начала позже даты конца")
    if days > MAX_PERIOD_DAYS:
        raise AppError(f"Период не может быть длиннее {MAX_PERIOD_DAYS} дней")

    period_start, _ = day_bounds(date_from)
    _, period_end = day_bounds(date_to)

    barbers = db.scalars(select(Barber).order_by(Barber.name)).all()
    stats = {b.id: BarberStats(b.id, b.name) for b in barbers}
    active = {b.id for b in barbers if b.is_active}

    minutes = func.sum(func.extract("epoch", Appointment.end_at - Appointment.start_at)) / 60
    rows = db.execute(
        select(
            Appointment.barber_id,
            Appointment.status,
            func.count(),
            func.sum(Appointment.price),
            minutes,
        )
        .where(Appointment.start_at >= period_start, Appointment.start_at < period_end)
        .group_by(Appointment.barber_id, Appointment.status)
    )
    for barber_id, status, count, money, mins in rows:
        s = stats[barber_id]
        s.total += count
        if status == AppointmentStatus.CANCELLED:
            s.cancelled = count
            continue
        s.busy_minutes += int(mins)
        if status == AppointmentStatus.COMPLETED:
            s.completed = count
            s.revenue = money
        elif status == AppointmentStatus.NO_SHOW:
            s.no_show = count
        else:
            s.pending = count

    weekday_count = Counter((date_from + timedelta(days=i)).weekday() for i in range(days))
    for schedule in db.scalars(select(Schedule)):
        stats[schedule.barber_id].work_minutes += (
            _shift_minutes(schedule) * weekday_count[schedule.weekday]
        )

    # Уволенных мастеров показываем, только если у них были записи за период.
    return [s for s in stats.values() if s.barber_id in active or s.total]


def summarize(rows: list[BarberStats]) -> BarberStats:
    total = BarberStats(None, "Всего")
    for r in rows:
        for name in (
            "total",
            "completed",
            "no_show",
            "cancelled",
            "pending",
            "revenue",
            "busy_minutes",
            "work_minutes",
        ):
            setattr(total, name, getattr(total, name) + getattr(r, name))
    return total
