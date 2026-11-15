from datetime import timedelta
from decimal import Decimal

import pytest

from app import tasks
from app.booking import now_local
from app.config import settings
from app.models import Appointment, AppointmentStatus
from app.reports import build_daily_report, format_report
from app.telegram import TelegramError
from tests.conftest import at

CLIENT_TELEGRAM_ID = 222  # из фикстуры shop


@pytest.fixture
def sent(monkeypatch):
    """Вместо настоящей отправки в Telegram складываем сообщения в список."""
    messages: list[tuple[int, str]] = []
    monkeypatch.setattr(
        tasks, "send_message", lambda chat_id, text: messages.append((chat_id, text))
    )
    return messages


def add_appointment(
    db,
    shop,
    start,
    *,
    created_ago=timedelta(days=1),
    status=AppointmentStatus.BOOKED,
    price="5000",
):
    """Создаёт запись напрямую в базе: так можно задать любое время и дату создания."""
    appointment = Appointment(
        barber_id=shop["barber_id"],
        client_id=shop["client_id"],
        service_id=shop["service_id"],
        start_at=start,
        end_at=start + timedelta(minutes=60),
        price=Decimal(price),
        status=status,
        created_at=now_local() - created_ago,
    )
    db.add(appointment)
    db.commit()
    return appointment.id


# --- Напоминания ---


def test_due_reminder_is_sent_once(db, shop, sent):
    add_appointment(db, shop, now_local() + timedelta(hours=1))

    assert tasks.send_reminders() == 1
    assert sent[0][0] == CLIENT_TELEGRAM_ID
    assert "Напоминание" in sent[0][1]
    # Следующий запуск через 5 минут не должен прислать повтор.
    assert tasks.send_reminders() == 0


@pytest.mark.parametrize(
    ("start_in", "kwargs"),
    [
        (timedelta(hours=3), {}),  # ещё рано
        (timedelta(minutes=-10), {}),  # уже началась
        (timedelta(hours=1), {"status": AppointmentStatus.CANCELLED}),
        (timedelta(hours=1), {"created_ago": timedelta(minutes=30)}),  # записался недавно
    ],
    ids=["too-early", "already-started", "cancelled", "booked-recently"],
)
def test_reminder_not_sent(db, shop, sent, start_in, kwargs):
    add_appointment(db, shop, now_local() + start_in, **kwargs)

    assert tasks.send_reminders() == 0
    assert sent == []


def test_transient_error_is_retried(db, shop, sent, monkeypatch):
    add_appointment(db, shop, now_local() + timedelta(hours=1))

    def fail(chat_id, text):
        raise TelegramError("Сетевая ошибка")

    monkeypatch.setattr(tasks, "send_message", fail)
    assert tasks.send_reminders() == 0

    monkeypatch.setattr(tasks, "send_message", lambda chat_id, text: sent.append((chat_id, text)))
    assert tasks.send_reminders() == 1


def test_permanent_error_is_not_retried(db, shop, sent, monkeypatch):
    add_appointment(db, shop, now_local() + timedelta(hours=1))

    def blocked(chat_id, text):
        raise TelegramError("Telegram 403: bot was blocked by the user", permanent=True)

    monkeypatch.setattr(tasks, "send_message", blocked)
    assert tasks.send_reminders() == 0

    monkeypatch.setattr(tasks, "send_message", lambda chat_id, text: sent.append((chat_id, text)))
    assert tasks.send_reminders() == 0


# --- Ежедневный отчёт ---


@pytest.fixture
def busy_day(db, shop):
    day = shop["day"]
    add_appointment(db, shop, at(day, 10), status=AppointmentStatus.COMPLETED, price="5000")
    add_appointment(db, shop, at(day, 11), status=AppointmentStatus.COMPLETED, price="6000")
    add_appointment(db, shop, at(day, 12), status=AppointmentStatus.NO_SHOW)
    add_appointment(db, shop, at(day, 13), status=AppointmentStatus.CANCELLED)
    add_appointment(db, shop, at(day, 14))  # мастер не отметил
    add_appointment(db, shop, at(day + timedelta(days=1), 10), status=AppointmentStatus.COMPLETED)
    return day


def test_daily_report_counts_and_revenue(db, busy_day):
    report = build_daily_report(db, busy_day)

    assert report.total == 5  # запись следующего дня не попала
    assert report.revenue == Decimal("11000")  # только «пришёл»
    assert report.statuses[AppointmentStatus.NO_SHOW] == 1
    assert report.statuses[AppointmentStatus.BOOKED] == 1

    text = format_report(report)
    assert "11 000 ₸" in text
    assert "без отметки: 1" in text


def test_empty_day_report(db, shop):
    assert "Записей не было" in format_report(build_daily_report(db, shop["day"]))


def test_daily_report_task_sends_to_admin(busy_day, sent, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_TELEGRAM_ID", 42)

    tasks.send_daily_report(busy_day.isoformat())

    assert sent[0][0] == 42
    assert "Выручка" in sent[0][1]


def test_daily_report_skipped_without_admin(busy_day, sent, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_TELEGRAM_ID", None)

    tasks.send_daily_report(busy_day.isoformat())

    assert sent == []
