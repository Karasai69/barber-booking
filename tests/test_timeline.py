"""Раскладка записей на шкале времени. База не нужна: функции получают готовые данные."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.models import AppointmentStatus
from app.stats import DayAppointment
from app.timeline import (
    CANCELLED,
    DONE,
    MIN_BLOCK_PX,
    NOW,
    OVERDUE,
    PX_PER_MINUTE,
    UPCOMING,
    build_timeline,
    summarize_day,
)

TZ = ZoneInfo("Asia/Almaty")
DAY = date(2026, 11, 16)
SHIFT = [(time(10, 0), time(20, 0))]


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(DAY.year, DAY.month, DAY.day, hour, minute, tzinfo=TZ)


def appt(start: datetime, minutes: int, status=AppointmentStatus.BOOKED, price="5000"):
    return DayAppointment(
        id=int(start.timestamp()) + minutes,
        start_at=start,
        end_at=start + timedelta(minutes=minutes),
        status=status,
        price=Decimal(price),
        client_name="Данияр",
        client_phone=None,
        service_name="Стрижка",
        barber_id=1,
        barber_name="Арман",
    )


def test_axis_covers_shift_and_marks_hours():
    timeline = build_timeline([], SHIFT, DAY, at(9))

    assert timeline.height == pytest.approx(600 * PX_PER_MINUTE)
    assert [h.label for h in timeline.hours] == [f"{h}:00" for h in range(10, 21)]
    assert timeline.off == []
    assert timeline.now_top is None  # 9:00 — до начала шкалы


def test_no_shift_and_no_appointments_gives_nothing():
    assert build_timeline([], [], DAY, at(12)) is None


def test_block_position_follows_time():
    timeline = build_timeline([appt(at(11, 30), 60)], SHIFT, DAY, at(9))

    block = timeline.blocks[0]
    assert block.top == pytest.approx(90 * PX_PER_MINUTE)
    assert block.height == pytest.approx(60 * PX_PER_MINUTE - 4)
    assert (block.left, block.width) == (0, 100)


def test_kind_depends_on_status_and_time():
    rows = [
        appt(at(10), 60, AppointmentStatus.COMPLETED),
        appt(at(11), 60),  # время вышло, визит не отмечен
        appt(at(12), 60),  # идёт сейчас
        appt(at(14), 60),  # впереди
        appt(at(15), 60, AppointmentStatus.CANCELLED),
    ]

    timeline = build_timeline(rows, SHIFT, DAY, at(12, 30))

    assert [b.kind for b in timeline.blocks] == [DONE, OVERDUE, NOW, UPCOMING, CANCELLED]


def test_cancelled_and_new_booking_on_same_time_stand_side_by_side():
    rows = [appt(at(16), 30, AppointmentStatus.CANCELLED), appt(at(16), 90)]

    timeline = build_timeline(rows, SHIFT, DAY, at(9))

    first, second = timeline.blocks
    assert (first.left, first.width) == (0, 50)
    assert (second.left, second.width) == (50, 50)


def test_short_appointment_stays_readable():
    timeline = build_timeline([appt(at(10), 10)], SHIFT, DAY, at(9))

    assert timeline.blocks[0].height == MIN_BLOCK_PX


def test_axis_grows_for_appointment_outside_shift_and_shows_time_off():
    timeline = build_timeline([appt(at(8, 30), 30)], [(time(12, 0), time(18, 0))], DAY, at(9))

    assert timeline.hours[0].label == "8:00"
    assert timeline.hours[-1].label == "18:00"
    assert [(z.top, z.height) for z in timeline.off] == [(0, pytest.approx(240 * PX_PER_MINUTE))]


def test_now_marker_only_for_today_and_hides_hour_label_under_it():
    today = build_timeline([], SHIFT, DAY, at(15, 5))
    other_day = build_timeline([], SHIFT, DAY + timedelta(days=1), at(15, 5))

    assert today.now_top == pytest.approx(305 * PX_PER_MINUTE)
    assert today.now_label == "15:05"
    assert [h.label for h in today.hours if h.hidden] == ["15:00"]
    assert other_day.now_top is None


def test_summary_counts_revenue_only_for_completed():
    rows = [
        appt(at(10), 60, AppointmentStatus.COMPLETED, price="6000"),
        appt(at(11), 60, AppointmentStatus.NO_SHOW, price="4000"),
        appt(at(12), 60),
        appt(at(14), 60),
    ]

    summary = summarize_day(build_timeline(rows, SHIFT, DAY, at(12, 30)).blocks)

    assert (summary.done, summary.upcoming) == (1, 1)
    assert summary.revenue == Decimal("6000")
    assert [b.kind for b in summary.attention] == [NOW]
    assert summary.next_up.appt.start_at == at(14)
