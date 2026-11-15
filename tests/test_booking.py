from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.main import app
from app.models import Appointment
from tests.conftest import TZ, at, book


def test_booking_success(client, shop):
    response = book(client, shop, at(shop["day"], 12))

    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "booked"
    assert datetime.fromisoformat(data["end_at"]) == at(shop["day"], 13)


def test_same_time_is_rejected(client, shop):
    assert book(client, shop, at(shop["day"], 12)).status_code == 201

    response = book(client, shop, at(shop["day"], 12))

    assert response.status_code == 409
    assert response.json()["detail"] == "Это время уже занято"


def test_partial_overlap_is_rejected(client, shop):
    assert book(client, shop, at(shop["day"], 12)).status_code == 201

    assert book(client, shop, at(shop["day"], 12, 30)).status_code == 409
    assert book(client, shop, at(shop["day"], 11, 30)).status_code == 409


def test_back_to_back_is_allowed(client, shop):
    assert book(client, shop, at(shop["day"], 12)).status_code == 201

    assert book(client, shop, at(shop["day"], 13)).status_code == 201
    assert book(client, shop, at(shop["day"], 11)).status_code == 201


def test_cancelled_slot_can_be_booked_again(client, shop):
    first = book(client, shop, at(shop["day"], 12)).json()
    client.patch(f"/appointments/{first['id']}/status", json={"status": "cancelled"})

    assert book(client, shop, at(shop["day"], 12)).status_code == 201


def test_other_barber_same_time_is_allowed(client, shop):
    other = client.post("/barbers", json={"name": "Ерлан"}).json()
    client.post(
        f"/barbers/{other['id']}/schedules",
        json={"weekday": 0, "start_time": "10:00", "end_time": "18:00"},
    )
    assert book(client, shop, at(shop["day"], 12)).status_code == 201

    response = book(client, shop, at(shop["day"], 12), barber_id=other["id"])

    assert response.status_code == 201


@pytest.mark.parametrize(
    ("hour", "minute"),
    [(9, 0), (17, 30), (18, 0)],  # до начала смены; не влезает до конца; после конца
)
def test_outside_schedule_is_rejected(client, shop, hour, minute):
    response = book(client, shop, at(shop["day"], hour, minute))

    assert response.status_code == 400
    assert response.json()["detail"] == "Мастер не работает в это время"


def test_day_off_is_rejected(client, shop):
    tuesday = shop["day"] + timedelta(days=1)

    assert book(client, shop, at(tuesday, 12)).status_code == 400


def test_past_time_is_rejected(client, shop):
    past = datetime.now(TZ) - timedelta(hours=1)

    assert book(client, shop, past).status_code == 400


def test_inactive_barber_cannot_be_booked(client, shop):
    client.patch(f"/barbers/{shop['barber_id']}", json={"is_active": False})

    assert book(client, shop, at(shop["day"], 12)).status_code == 404


def test_naive_datetime_is_rejected(client, shop):
    naive = at(shop["day"], 12).replace(tzinfo=None)

    assert book(client, shop, naive).status_code == 422


def test_free_slots_exclude_booked_time(client, shop):
    book(client, shop, at(shop["day"], 12))

    response = client.get(
        f"/barbers/{shop['barber_id']}/slots",
        params={"service_id": shop["service_id"], "day": shop["day"].isoformat()},
    )

    slots = [datetime.fromisoformat(s) for s in response.json()]
    assert slots[0] == at(shop["day"], 10)
    assert slots[-1] == at(shop["day"], 17)  # последний час смены
    assert at(shop["day"], 11) in slots  # 11:00–12:00 ещё свободно
    assert at(shop["day"], 13) in slots
    for busy in (at(shop["day"], 11, 15), at(shop["day"], 12), at(shop["day"], 12, 45)):
        assert busy not in slots


def test_status_transitions(client, shop):
    appointment = book(client, shop, at(shop["day"], 12)).json()
    url = f"/appointments/{appointment['id']}/status"

    assert client.patch(url, json={"status": "completed"}).status_code == 200
    # Итоговый статус больше не меняется.
    assert client.patch(url, json={"status": "cancelled"}).status_code == 400


def test_database_rejects_overlap_directly(db, shop):
    """Даже если обойти API, база не даст сохранить пересекающиеся записи."""
    common = {
        "barber_id": shop["barber_id"],
        "client_id": shop["client_id"],
        "service_id": shop["service_id"],
    }
    db.add(Appointment(**common, start_at=at(shop["day"], 12), end_at=at(shop["day"], 13)))
    db.commit()

    db.add(
        Appointment(**common, start_at=at(shop["day"], 12, 30), end_at=at(shop["day"], 13, 30))
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_concurrent_requests_only_one_wins(shop):
    """Десять одновременных запросов на одно время: успешен ровно один."""
    start = at(shop["day"], 12)

    def attempt(_):
        with TestClient(app) as c:
            return book(c, shop, start).status_code

    with ThreadPoolExecutor(max_workers=10) as pool:
        codes = list(pool.map(attempt, range(10)))

    assert codes.count(201) == 1
    assert codes.count(409) == 9
