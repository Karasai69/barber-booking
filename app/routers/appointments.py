from datetime import date

from fastapi import APIRouter, Depends, status
from sqlalchemy import select

from app import booking
from app.auth import CurrentUser, require_admin
from app.database import DbSession
from app.errors import NotFoundError
from app.models import Appointment, User, UserRole
from app.schemas import AppointmentCreate, AppointmentRead, AppointmentStatusUpdate

router = APIRouter(prefix="/appointments", tags=["appointments"])


def own_barber_id(user: User) -> int | None:
    """Для мастера — id его профиля (видит только свои записи), для админа — None."""
    return user.barber_id if user.role == UserRole.BARBER else None


@router.post(
    "",
    response_model=AppointmentRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def create_appointment(data: AppointmentCreate, db: DbSession):
    """Запись от имени клиента (например, по звонку). Клиенты записываются через бота."""
    return booking.create_appointment(db, **data.model_dump())


@router.get("", response_model=list[AppointmentRead])
def list_appointments(
    db: DbSession,
    user: CurrentUser,
    barber_id: int | None = None,
    client_id: int | None = None,
    day: date | None = None,
):
    """Админ видит все записи, мастер — только свои (фильтр barber_id для него игнорируется)."""
    own = own_barber_id(user)
    if own is not None:
        barber_id = own
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
def get_appointment(appointment_id: int, db: DbSession, user: CurrentUser):
    appointment = db.get(Appointment, appointment_id)
    own = own_barber_id(user)
    if appointment is None or (own is not None and appointment.barber_id != own):
        raise NotFoundError("Запись не найдена")
    return appointment


@router.patch("/{appointment_id}/status", response_model=AppointmentRead)
def update_status(
    appointment_id: int, data: AppointmentStatusUpdate, db: DbSession, user: CurrentUser
):
    """Админ: отмена или отметка визита. Мастер: только «пришёл» / «не пришёл» в своих записях."""
    return booking.change_status(db, appointment_id, data.status, barber_id=own_barber_id(user))
