import os

# Тесты работают с отдельной базой, чтобы не трогать данные разработки.
# Переменная окружения важнее .env, поэтому задаём её до импорта приложения.
os.environ["POSTGRES_DB"] = "barber_booking_test"

from datetime import date, datetime, time, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo(settings.TIMEZONE)


def _create_test_database() -> None:
    admin_url = settings.database_url.rsplit("/", 1)[0] + "/postgres"
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        exists = conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": settings.POSTGRES_DB},
        )
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{settings.POSTGRES_DB}"'))
    admin_engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def database():
    _create_test_database()
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_tables():
    yield
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE appointments, schedules, clients, services, barbers "
                "RESTART IDENTITY CASCADE"
            )
        )


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


def next_weekday(weekday: int) -> date:
    """Ближайший такой день недели в будущем (не сегодня)."""
    today = datetime.now(TZ).date()
    days_ahead = (weekday - today.weekday()) % 7 or 7
    return today + timedelta(days=days_ahead)


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=TZ)


@pytest.fixture
def shop(client):
    """Мастер с графиком пн 10:00–18:00, услуга на 60 минут и клиент."""
    barber = client.post("/barbers", json={"name": "Арман", "telegram_id": 111}).json()
    client.post(
        f"/barbers/{barber['id']}/schedules",
        json={"weekday": 0, "start_time": "10:00", "end_time": "18:00"},
    )
    service = client.post(
        "/services", json={"name": "Стрижка", "price": "5000", "duration_min": 60}
    ).json()
    customer = client.post("/clients", json={"name": "Данияр", "telegram_id": 222}).json()
    return {
        "barber_id": barber["id"],
        "service_id": service["id"],
        "client_id": customer["id"],
        "day": next_weekday(0),
    }


def book(client, shop, start: datetime, **overrides):
    payload = {
        "barber_id": shop["barber_id"],
        "client_id": shop["client_id"],
        "service_id": shop["service_id"],
        "start_at": start.isoformat(),
    }
    payload.update(overrides)
    return client.post("/appointments", json=payload)
