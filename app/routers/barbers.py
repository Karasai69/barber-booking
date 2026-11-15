from datetime import date, datetime

from fastapi import APIRouter, Depends, status
from sqlalchemy import select

from app import booking
from app.auth import require_admin
from app.database import DbSession
from app.errors import NotFoundError, commit_or_conflict, get_or_404
from app.models import Barber, Schedule
from app.schemas import BarberCreate, BarberRead, BarberUpdate, ScheduleCreate, ScheduleRead

router = APIRouter(prefix="/barbers", tags=["barbers"])

ADMIN = [Depends(require_admin)]

BARBER_NOT_FOUND = "Мастер не найден"
TELEGRAM_TAKEN = "Мастер с таким telegram_id уже есть"


@router.post("", response_model=BarberRead, status_code=status.HTTP_201_CREATED, dependencies=ADMIN)
def create_barber(data: BarberCreate, db: DbSession):
    barber = Barber(**data.model_dump())
    db.add(barber)
    commit_or_conflict(db, TELEGRAM_TAKEN)
    db.refresh(barber)
    return barber


@router.get("", response_model=list[BarberRead])
def list_barbers(db: DbSession, include_inactive: bool = False):
    stmt = select(Barber).order_by(Barber.id)
    if not include_inactive:
        stmt = stmt.where(Barber.is_active)
    return db.scalars(stmt).all()


@router.get("/{barber_id}", response_model=BarberRead)
def get_barber(barber_id: int, db: DbSession):
    return get_or_404(db, Barber, barber_id, BARBER_NOT_FOUND)


@router.patch("/{barber_id}", response_model=BarberRead, dependencies=ADMIN)
def update_barber(barber_id: int, data: BarberUpdate, db: DbSession):
    barber = get_or_404(db, Barber, barber_id, BARBER_NOT_FOUND)
    for field, value in data.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(barber, field, value)
    commit_or_conflict(db, TELEGRAM_TAKEN)
    db.refresh(barber)
    return barber


@router.post(
    "/{barber_id}/schedules",
    response_model=ScheduleRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=ADMIN,
)
def add_schedule(barber_id: int, data: ScheduleCreate, db: DbSession):
    get_or_404(db, Barber, barber_id, BARBER_NOT_FOUND)
    schedule = Schedule(barber_id=barber_id, **data.model_dump())
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return schedule


@router.get("/{barber_id}/schedules", response_model=list[ScheduleRead])
def list_schedules(barber_id: int, db: DbSession):
    get_or_404(db, Barber, barber_id, BARBER_NOT_FOUND)
    stmt = (
        select(Schedule)
        .where(Schedule.barber_id == barber_id)
        .order_by(Schedule.weekday, Schedule.start_time)
    )
    return db.scalars(stmt).all()


@router.delete("/{barber_id}/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=ADMIN)
def delete_schedule(barber_id: int, schedule_id: int, db: DbSession):
    schedule = db.get(Schedule, schedule_id)
    if schedule is None or schedule.barber_id != barber_id:
        raise NotFoundError("Смена не найдена")
    db.delete(schedule)
    db.commit()


@router.get("/{barber_id}/slots", response_model=list[datetime])
def free_slots(barber_id: int, service_id: int, day: date, db: DbSession):
    """Свободное время начала записи на выбранный день."""
    return booking.get_free_slots(db, barber_id, service_id, day)
