from datetime import timedelta
from decimal import Decimal

import pytest

from app import accounts
from app.booking import now_local
from app.database import SessionLocal
from app.models import Appointment, AppointmentStatus, User, UserRole
from tests.conftest import ADMIN_PASSWORD, BARBER_PASSWORD, at, bearer, book


def create_barber_user(barber_id: int, username: str = "arman") -> int:
    with SessionLocal() as session:
        return accounts.create_user(
            session, username, BARBER_PASSWORD, UserRole.BARBER, barber_id
        ).id


def add_appointment(db, shop, start, *, barber_id=None, status=AppointmentStatus.BOOKED):
    appointment = Appointment(
        barber_id=barber_id or shop["barber_id"],
        client_id=shop["client_id"],
        service_id=shop["service_id"],
        start_at=start,
        end_at=start + timedelta(hours=1),
        price=Decimal("5000"),
        status=status,
    )
    db.add(appointment)
    db.commit()
    return appointment.id


@pytest.fixture
def other_barber(client):
    return client.post("/barbers", json={"name": "Ерлан"}).json()["id"]


@pytest.fixture
def barber_headers(shop):
    return bearer(create_barber_user(shop["barber_id"]))


# --- Вход ---


def test_login_returns_working_token(anon_client, admin_headers):
    response = anon_client.post(
        "/auth/token", data={"username": "admin", "password": ADMIN_PASSWORD}
    )

    assert response.status_code == 200
    token = response.json()["access_token"]
    me = anon_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["role"] == "admin"


def test_username_is_case_insensitive(anon_client, admin_headers):
    response = anon_client.post(
        "/auth/token", data={"username": " Admin ", "password": ADMIN_PASSWORD}
    )

    assert response.status_code == 200


@pytest.mark.parametrize(
    ("username", "password"),
    [("admin", "wrong-password"), ("nobody", ADMIN_PASSWORD)],
    ids=["wrong-password", "unknown-user"],
)
def test_login_fails(anon_client, admin_headers, username, password):
    response = anon_client.post("/auth/token", data={"username": username, "password": password})

    assert response.status_code == 401
    assert response.json()["detail"] == "Неверный логин или пароль"


def test_fake_token_is_rejected(anon_client):
    response = anon_client.get("/auth/me", headers={"Authorization": "Bearer not-a-jwt"})

    assert response.status_code == 401


def test_disabled_user_loses_access(client, anon_client, shop, barber_headers):
    barber_user_id = 2  # админ создан первым
    assert anon_client.get("/auth/me", headers=barber_headers).status_code == 200

    client.patch(f"/users/{barber_user_id}", json={"is_active": False})

    assert anon_client.get("/auth/me", headers=barber_headers).status_code == 401


# --- Права ---


def test_anonymous_can_read_but_not_write(anon_client):
    assert anon_client.get("/services").status_code == 200
    assert anon_client.post("/services", json={}).status_code == 401
    assert anon_client.get("/appointments").status_code == 401


@pytest.mark.parametrize(
    ("method", "url", "body"),
    [
        ("post", "/services", {"name": "X", "price": "1", "duration_min": 10}),
        ("post", "/barbers", {"name": "X"}),
        ("post", "/users", {"username": "xx", "password": "12345678", "role": "admin"}),
        ("get", "/stats?date_from=2026-01-01&date_to=2026-01-02", None),
        ("get", "/clients/1", None),
    ],
)
def test_barber_cannot_use_admin_endpoints(anon_client, barber_headers, method, url, body):
    response = anon_client.request(method, url, json=body, headers=barber_headers)

    assert response.status_code == 403


def test_barber_sees_only_own_appointments(
    client, anon_client, db, shop, other_barber, barber_headers
):
    own = book(client, shop, at(shop["day"], 12)).json()["id"]
    foreign = add_appointment(db, shop, at(shop["day"], 12), barber_id=other_barber)

    response = anon_client.get(
        "/appointments", params={"barber_id": other_barber}, headers=barber_headers
    )

    assert [a["id"] for a in response.json()] == [own]
    assert anon_client.get(f"/appointments/{foreign}", headers=barber_headers).status_code == 404


def test_barber_marks_own_visit(anon_client, db, shop, barber_headers):
    appointment_id = add_appointment(db, shop, now_local() - timedelta(minutes=30))
    url = f"/appointments/{appointment_id}/status"

    response = anon_client.patch(url, json={"status": "completed"}, headers=barber_headers)

    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_barber_cannot_cancel(anon_client, db, shop, barber_headers):
    appointment_id = add_appointment(db, shop, now_local() - timedelta(minutes=30))
    url = f"/appointments/{appointment_id}/status"

    response = anon_client.patch(url, json={"status": "cancelled"}, headers=barber_headers)

    assert response.status_code == 403


def test_barber_cannot_mark_foreign_visit(anon_client, db, shop, other_barber, barber_headers):
    appointment_id = add_appointment(
        db, shop, now_local() - timedelta(minutes=30), barber_id=other_barber
    )
    url = f"/appointments/{appointment_id}/status"

    response = anon_client.patch(url, json={"status": "completed"}, headers=barber_headers)

    assert response.status_code == 404


# --- Пользователи ---


def test_admin_creates_barber_account(client, anon_client, shop):
    response = client.post(
        "/users",
        json={
            "username": "arman",
            "password": BARBER_PASSWORD,
            "role": "barber",
            "barber_id": shop["barber_id"],
        },
    )
    assert response.status_code == 201

    login = anon_client.post("/auth/token", data={"username": "arman", "password": BARBER_PASSWORD})
    assert login.status_code == 200


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"username": "arman", "password": BARBER_PASSWORD, "role": "barber"}, 400),
        ({"username": "admin", "password": BARBER_PASSWORD, "role": "admin"}, 409),
        ({"username": "bob", "password": "short", "role": "admin"}, 422),
    ],
    ids=["barber-without-barber_id", "duplicate-username", "short-password"],
)
def test_invalid_user_creation(client, payload, code):
    assert client.post("/users", json=payload).status_code == code


def test_one_account_per_barber(client, shop):
    create_barber_user(shop["barber_id"], "first")

    response = client.post(
        "/users",
        json={
            "username": "second",
            "password": BARBER_PASSWORD,
            "role": "barber",
            "barber_id": shop["barber_id"],
        },
    )

    assert response.status_code == 409


def test_admin_cannot_disable_self(client):
    assert client.patch("/users/1", json={"is_active": False}).status_code == 400


def test_password_is_stored_hashed(admin_headers, db):
    user = db.get(User, 1)

    assert user.password_hash != ADMIN_PASSWORD
    assert user.password_hash.startswith("$argon2")


# --- Статистика ---


def test_stats_load_and_revenue(client, db, shop):
    day = shop["day"]  # смена 10:00–18:00 = 480 минут
    add_appointment(db, shop, at(day, 10), status=AppointmentStatus.COMPLETED)
    add_appointment(db, shop, at(day, 11), status=AppointmentStatus.CANCELLED)
    book(client, shop, at(day, 12))

    response = client.get("/stats", params={"date_from": day, "date_to": day})

    assert response.status_code == 200
    barber = response.json()["barbers"][0]
    assert barber["total"] == 3
    assert barber["completed"] == 1
    assert barber["cancelled"] == 1
    assert barber["pending"] == 1
    assert Decimal(barber["revenue"]) == Decimal("5000")
    assert barber["busy_minutes"] == 120  # отменённая не считается
    assert barber["work_minutes"] == 480
    assert barber["load_percent"] == 25


def test_stats_period_is_limited(client):
    response = client.get("/stats", params={"date_from": "2026-01-01", "date_to": "2026-12-31"})

    assert response.status_code == 400
