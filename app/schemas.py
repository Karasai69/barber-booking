from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.models import AppointmentStatus, UserRole

Name = Annotated[str, Field(min_length=1, max_length=100)]
TelegramId = Annotated[int, Field(gt=0)]
Price = Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2)]
Duration = Annotated[int, Field(gt=0, le=600)]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Мастера ---

class BarberCreate(BaseModel):
    name: Name
    telegram_id: TelegramId | None = None


class BarberUpdate(BaseModel):
    name: Name | None = None
    telegram_id: TelegramId | None = None
    is_active: bool | None = None


class BarberRead(ORMModel):
    id: int
    name: str
    telegram_id: int | None
    is_active: bool


# --- Услуги ---

class ServiceCreate(BaseModel):
    name: Name
    price: Price
    duration_min: Duration


class ServiceUpdate(BaseModel):
    name: Name | None = None
    price: Price | None = None
    duration_min: Duration | None = None


class ServiceRead(ORMModel):
    id: int
    name: str
    price: Decimal
    duration_min: int


# --- График ---

class ScheduleCreate(BaseModel):
    weekday: Annotated[int, Field(ge=0, le=6, description="0 = понедельник")]
    start_time: time
    end_time: time

    @model_validator(mode="after")
    def check_times(self) -> "ScheduleCreate":
        if self.end_time <= self.start_time:
            raise ValueError("end_time должен быть позже start_time")
        return self


class ScheduleRead(ORMModel):
    id: int
    barber_id: int
    weekday: int
    start_time: time
    end_time: time


# --- Клиенты ---

class ClientCreate(BaseModel):
    name: Name
    phone: Annotated[str, Field(min_length=5, max_length=20)] | None = None
    telegram_id: TelegramId | None = None


class ClientRead(ORMModel):
    id: int
    name: str
    phone: str | None
    telegram_id: int | None


# --- Записи ---

class AppointmentCreate(BaseModel):
    barber_id: int
    client_id: int
    service_id: int
    start_at: AwareDatetime


class AppointmentStatusUpdate(BaseModel):
    status: AppointmentStatus


class AppointmentRead(ORMModel):
    id: int
    barber_id: int
    client_id: int
    service_id: int
    start_at: datetime
    end_at: datetime
    price: Decimal
    status: AppointmentStatus
    created_at: datetime


# --- Вход и пользователи кабинета ---

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserCreate(BaseModel):
    username: Annotated[str, Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_.-]+$")]
    password: Annotated[str, Field(min_length=8, max_length=128)]
    role: UserRole
    barber_id: int | None = None


class UserUpdate(BaseModel):
    password: Annotated[str, Field(min_length=8, max_length=128)] | None = None
    is_active: bool | None = None


class UserRead(ORMModel):
    id: int
    username: str
    role: UserRole
    barber_id: int | None
    is_active: bool


# --- Статистика ---

class BarberStatsRead(ORMModel):
    barber_id: int | None
    name: str
    total: int
    completed: int
    no_show: int
    cancelled: int
    pending: int
    revenue: Decimal
    busy_minutes: int
    work_minutes: int
    load_percent: int | None


class PeriodStatsRead(BaseModel):
    date_from: date
    date_to: date
    barbers: list[BarberStatsRead]
    total: BarberStatsRead
