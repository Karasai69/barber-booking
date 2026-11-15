"""Ежедневный отчёт: записи и выручка за день."""

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from html import escape

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.booking import day_bounds
from app.models import Appointment, AppointmentStatus, Barber

WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


@dataclass
class BarberStats:
    name: str
    statuses: Counter = field(default_factory=Counter)
    revenue: Decimal = Decimal("0")

    @property
    def total(self) -> int:
        return sum(self.statuses.values())


@dataclass
class DailyReport:
    day: date
    barbers: list[BarberStats]

    @property
    def statuses(self) -> Counter:
        return sum((b.statuses for b in self.barbers), Counter())

    @property
    def revenue(self) -> Decimal:
        return sum((b.revenue for b in self.barbers), Decimal("0"))

    @property
    def total(self) -> int:
        return sum(b.total for b in self.barbers)


def build_daily_report(db: Session, day: date) -> DailyReport:
    day_start, day_end = day_bounds(day)
    # Выручка — только с тех, кто пришёл.
    revenue = func.sum(Appointment.price).filter(
        Appointment.status == AppointmentStatus.COMPLETED
    )
    rows = db.execute(
        select(Barber.id, Barber.name, Appointment.status, func.count(), revenue)
        .join(Barber, Appointment.barber_id == Barber.id)
        .where(Appointment.start_at >= day_start, Appointment.start_at < day_end)
        .group_by(Barber.id, Barber.name, Appointment.status)
        .order_by(Barber.name)
    )
    by_barber: dict[int, BarberStats] = {}
    for barber_id, name, status, count, money in rows:
        stats = by_barber.setdefault(barber_id, BarberStats(name))
        stats.statuses[status] = count
        stats.revenue += money or Decimal("0")
    return DailyReport(day, list(by_barber.values()))


def _money(value: Decimal) -> str:
    return f"{value:,.0f}".replace(",", " ") + " ₸"


def format_report(report: DailyReport) -> str:
    title = f"📊 <b>Отчёт за {WEEKDAYS[report.day.weekday()]} {report.day:%d.%m.%Y}</b>"
    if report.total == 0:
        return f"{title}\n\nЗаписей не было."
    s = report.statuses
    lines = [
        title,
        "",
        f"Записей: {report.total}",
        f"✅ пришли: {s[AppointmentStatus.COMPLETED]}",
        f"🚫 не пришли: {s[AppointmentStatus.NO_SHOW]}",
        f"↩️ отменили: {s[AppointmentStatus.CANCELLED]}",
    ]
    if s[AppointmentStatus.BOOKED]:
        lines.append(f"❔ без отметки: {s[AppointmentStatus.BOOKED]}")
    lines += ["", f"💰 Выручка: <b>{_money(report.revenue)}</b>", ""]
    for b in report.barbers:
        lines.append(f"{escape(b.name)}: {b.total} зап., {_money(b.revenue)}")
    return "\n".join(lines)
