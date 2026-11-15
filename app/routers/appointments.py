from datetime import date

from fastapi import APIRouter, status
from sqlalchemy import select

from app import booking
from app.database import DbSession
from app.errors import get_or_404
from app.models import Appointment
from app.schemas import AppointmentCreate, AppointmentRead, AppointmentStatusUpdate

router = APIRouter(prefix="/appointments", tags=["appointments"])


@router.post("", response_model=AppointmentRead, status_code=status.HTTP_201_CREATED)
def create_appointment(data: AppointmentCreate, db: DbSession):
    return booking.create_appointment(db, **data.model_dump())


@router.get("", response_model=list[AppointmentRead])
def list_appointments(
    db: DbSession,
    barber_id: int | None = None,
    client_id: int | None = None,
    day: date | None = None,
):
    stmt = select(Appointment).order_by(Appointment.start_at)
    if barber_id is not None:
        stmt = stmt.where(Appointment.barber_id == barber_id)
    if client_id is not None:
        stmt = stmt.where(Appointment.client_id == client_id)
    if day is not None:
        day_start, day_end = booking.day_bounds(day)
        stmt = stmt.where(Appointment.start_at >= day_start, Appointment.start_at < day_end)
    return db.scalars(stmt).all()


@router.get("/{appointment_id}", response_model=AppointmentRead)
def get_appointment(appointment_id: int, db: DbSession):
    return get_or_404(db, Appointment, appointment_id, "Запись не найдена")


@router.patch("/{appointment_id}/status", response_model=AppointmentRead)
def update_status(appointment_id: int, data: AppointmentStatusUpdate, db: DbSession):
    """Отмена записи, отметка «пришёл» или «не пришёл»."""
    return booking.change_status(db, appointment_id, data.status)
