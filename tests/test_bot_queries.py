from datetime import timedelta

import pytest

from app.errors import AppError, NotFoundError
from bot import queries as q
from tests.conftest import at, book


def test_get_or_create_client_is_idempotent(db):
    first = q.get_or_create_client(db, telegram_id=555, name="Асель")
    second = q.get_or_create_client(db, telegram_id=555, name="Другое имя")

    assert first == second


def test_existing_client_is_found_by_telegram_id(db, shop):
    # Клиент из фикстуры shop создан с telegram_id=222.
    assert q.get_or_create_client(db, telegram_id=222, name="Данияр") == shop["client_id"]


def test_available_days_are_only_working_days(db, shop):
    days = q.available_days(db, shop["barber_id"], shop["service_id"])

    assert days, "в ближайшие 2 недели есть хотя бы один понедельник"
    assert all(d.weekday() == 0 for d in days)
    assert shop["day"] in days


def test_upcoming_appointments_skip_cancelled(client, db, shop):
    kept = book(client, shop, at(shop["day"], 12)).json()
    cancelled = book(client, shop, at(shop["day"], 14)).json()
    client.patch(f"/appointments/{cancelled['id']}/status", json={"status": "cancelled"})

    upcoming = q.upcoming_appointments(db, shop["client_id"])

    assert [a.id for a in upcoming] == [kept["id"]]
    assert upcoming[0].service_name == "Стрижка"
    assert upcoming[0].barber_name == "Арман"


def test_client_can_cancel_own_appointment(client, db, shop):
    appointment = book(client, shop, at(shop["day"], 12)).json()

    q.cancel_appointment(db, appointment["id"], shop["client_id"])

    assert q.upcoming_appointments(db, shop["client_id"]) == []


def test_client_cannot_cancel_foreign_appointment(client, db, shop):
    appointment = book(client, shop, at(shop["day"], 12)).json()
    stranger = q.get_or_create_client(db, telegram_id=999, name="Чужой")

    with pytest.raises(NotFoundError):
        q.cancel_appointment(db, appointment["id"], stranger)


def test_past_appointment_cannot_be_cancelled(client, db, shop):
    appointment = book(client, shop, at(shop["day"], 12)).json()
    # Переносим запись в прошлое напрямую в базе (через API так нельзя).
    from app.models import Appointment

    row = db.get(Appointment, appointment["id"])
    row.start_at -= timedelta(days=30)
    row.end_at -= timedelta(days=30)
    db.commit()

    with pytest.raises(AppError):
        q.cancel_appointment(db, appointment["id"], shop["client_id"])
