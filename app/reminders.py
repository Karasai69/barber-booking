"""Выбор записей, которым пора отправить напоминание."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.booking import now_local
from app.models import Appointment, AppointmentStatus, Barber, Client, Service

REMIND_BEFORE = timedelta(hours=2)


@dataclass(frozen=True)
class Reminder:
    appointment_id: int
    telegram_id: int
    start_at: datetime
    service_name: str
    barber_name: str


def claim_due_reminders(db: Session, now: datetime | None = None) -> list[Reminder]:
    """Помечает записи «напоминание отправлено» и возвращает их.

    Отметка ставится одним UPDATE ... WHERE reminder_sent_at IS NULL RETURNING.
    Если две задачи запустятся одновременно, PostgreSQL отдаст каждую запись
    только одной из них, и клиент не получит два напоминания.
    """
    now = now or now_local()
    has_telegram = select(Client.id).where(Client.telegram_id.is_not(None))
    stmt = (
        update(Appointment)
        .where(
            Appointment.status == AppointmentStatus.BOOKED,
            Appointment.reminder_sent_at.is_(None),
            Appointment.start_at > now,
            Appointment.start_at <= now + REMIND_BEFORE,
            # Кто записался меньше чем за 2 часа, и так помнит о визите.
            Appointment.created_at < Appointment.start_at - REMIND_BEFORE,
            Appointment.client_id.in_(has_telegram),
        )
        .values(reminder_sent_at=now)
        .returning(Appointment.id)
    )
    ids = list(db.scalars(stmt))
    db.commit()
    if not ids:
        return []

    rows = db.execute(
        select(Appointment.id, Client.telegram_id, Appointment.start_at, Service.name, Barber.name)
        .join(Client, Appointment.client_id == Client.id)
        .join(Service, Appointment.service_id == Service.id)
        .join(Barber, Appointment.barber_id == Barber.id)
        .where(Appointment.id.in_(ids))
        .order_by(Appointment.start_at)
    )
    return [Reminder(*row) for row in rows]


def release_reminder(db: Session, appointment_id: int) -> None:
    """Снимает отметку, чтобы следующий запуск попробовал отправить ещё раз."""
    db.execute(
        update(Appointment)
        .where(Appointment.id == appointment_id)
        .values(reminder_sent_at=None)
    )
    db.commit()
