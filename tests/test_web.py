from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.booking import now_local
from app.database import SessionLocal
from app.main import app
from app.models import Appointment, AppointmentStatus, Service
from tests.conftest import ADMIN_PASSWORD, BARBER_PASSWORD
from tests.test_auth import add_appointment, create_barber_user


@pytest.fixture
def browser():
    """Как браузер: хранит cookie и не переходит по редиректам сам."""
    with TestClient(app, follow_redirects=False) as c:
        yield c


def web_login(browser, username, password):
    return browser.post("/web/login", data={"username": username, "password": password})


@pytest.fixture
def admin_browser(browser, admin_headers):
    assert web_login(browser, "admin", ADMIN_PASSWORD).status_code == 303
    return browser


@pytest.fixture
def barber_browser(browser, shop):
    create_barber_user(shop["barber_id"])
    assert web_login(browser, "arman", BARBER_PASSWORD).status_code == 303
    return browser


def test_pages_require_login(browser):
    response = browser.get("/web/schedule")

    assert response.status_code == 303
    assert response.headers["location"] == "/web/login"


def test_wrong_password_shows_error(browser, admin_headers):
    response = web_login(browser, "admin", "wrong-password")

    assert response.status_code == 401
    assert "Неверный логин или пароль" in response.text


def test_login_sets_httponly_cookie(browser, admin_headers):
    response = web_login(browser, "admin", ADMIN_PASSWORD)

    cookie = response.headers["set-cookie"].lower()
    assert "access_token=" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie


def test_logout_clears_session(admin_browser):
    admin_browser.post("/web/logout")

    assert admin_browser.get("/web/schedule").status_code == 303


@pytest.mark.parametrize(
    "url", ["/web/admin", "/web/admin/barbers", "/web/admin/services", "/web/schedule"]
)
def test_admin_pages_render(admin_browser, shop, url):
    response = admin_browser.get(url)

    assert response.status_code == 200
    assert "<html" in response.text


def test_admin_redirect_after_login(admin_browser):
    assert admin_browser.get("/web").headers["location"] == "/web/admin"


def test_barber_cannot_open_admin_pages(barber_browser):
    response = barber_browser.get("/web/admin")

    assert response.status_code == 303
    assert response.headers["location"] == "/web/schedule"


def test_barber_schedule_shows_only_own(barber_browser, client, db, shop):
    other = client.post("/barbers", json={"name": "Ерлан"}).json()["id"]
    start = now_local() - timedelta(minutes=30)
    add_appointment(db, shop, start)
    add_appointment(db, shop, start, barber_id=other)

    page = barber_browser.get("/web/schedule", params={"day": start.date()})

    assert page.text.count("data-appointment=") == 1  # только своя запись
    assert 'class="timeline"' in page.text
    assert "Пришёл" in page.text


def test_admin_sees_one_barber_timeline_or_all_barbers_list(admin_browser, client, db, shop):
    other = client.post("/barbers", json={"name": "Ерлан"}).json()["id"]
    start = now_local() + timedelta(minutes=30)
    add_appointment(db, shop, start)
    add_appointment(db, shop, start, barber_id=other)
    day = start.date()

    one = admin_browser.get("/web/schedule", params={"day": day, "barber_id": other})
    everyone = admin_browser.get("/web/schedule", params={"day": day, "barber_id": "all"})

    assert one.text.count("data-appointment=") == 1
    assert 'class="timeline"' in one.text
    assert everyone.text.count("data-appointment=") == 2
    assert 'class="timeline"' not in everyone.text


def test_barber_marks_visit_from_page(barber_browser, db, shop):
    start = now_local() - timedelta(minutes=30)
    appointment_id = add_appointment(db, shop, start)

    response = barber_browser.post(
        f"/web/appointments/{appointment_id}/status",
        data={"status": "no_show", "day": start.date().isoformat()},
    )

    assert response.status_code == 303
    assert "msg=" in response.headers["location"]
    with SessionLocal() as session:
        assert session.get(Appointment, appointment_id).status == AppointmentStatus.NO_SHOW


def test_admin_adds_service_from_page(admin_browser):
    response = admin_browser.post(
        "/web/admin/services",
        data={"name": "Камуфляж седины", "price": "4 500", "duration_min": "45"},
    )

    assert "msg=" in response.headers["location"]
    with SessionLocal() as session:
        service = session.query(Service).filter_by(name="Камуфляж седины").one()
        assert service.price == 4500


def test_invalid_form_shows_error(admin_browser):
    response = admin_browser.post(
        "/web/admin/services", data={"name": "X", "price": "abc", "duration_min": "45"}
    )

    assert "error=" in response.headers["location"]


def test_admin_creates_barber_account_from_page(admin_browser, shop):
    admin_browser.post(
        f"/web/admin/barbers/{shop['barber_id']}/account",
        data={"username": "arman", "password": BARBER_PASSWORD},
    )
    admin_browser.post("/web/logout")

    response = web_login(admin_browser, "arman", BARBER_PASSWORD)

    assert response.status_code == 303
    assert admin_browser.get("/web").headers["location"] == "/web/schedule"
