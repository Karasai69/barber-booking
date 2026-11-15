import logging
from datetime import date
from html import escape

from app.booking import now_local, shop_tz
from app.celery_app import celery_app
from app.config import settings
from app.database import SessionLocal
from app.reminders import Reminder, claim_due_reminders, release_reminder
from app.reports import build_daily_report, format_report
from app.telegram import TelegramError, send_message

logger = logging.getLogger(__name__)


def reminder_text(r: Reminder) -> str:
    local = r.start_at.astimezone(shop_tz())
    return (
        "⏰ <b>Напоминание</b>\n\n"
        f"Ждём вас {local:%d.%m} в {local:%H:%M} — {escape(r.service_name)}, "
        f"мастер {escape(r.barber_name)}.\n\n"
        "Если не получается прийти, отмените запись в разделе «Мои записи»."
    )


@celery_app.task
def send_reminders() -> int:
    """Отправляет напоминания за 2 часа до визита. Возвращает число отправленных."""
    with SessionLocal() as db:
        reminders = claim_due_reminders(db)
        sent = 0
        for r in reminders:
            try:
                send_message(r.telegram_id, reminder_text(r))
                sent += 1
            except TelegramError as exc:
                logger.warning("Напоминание для записи %s не отправлено: %s", r.appointment_id, exc)
                if not exc.permanent:
                    release_reminder(db, r.appointment_id)
    return sent


@celery_app.task
def send_daily_report(day: str | None = None) -> None:
    """Отчёт админу за день (по умолчанию — за сегодня)."""
    if settings.ADMIN_TELEGRAM_ID is None:
        logger.warning("ADMIN_TELEGRAM_ID не задан, отчёт не отправлен")
        return
    report_day = date.fromisoformat(day) if day else now_local().date()
    with SessionLocal() as db:
        report = build_daily_report(db, report_day)
    send_message(settings.ADMIN_TELEGRAM_ID, format_report(report))
