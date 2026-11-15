from fastapi import APIRouter, status
from sqlalchemy import select

from app.database import DbSession
from app.errors import commit_or_conflict, get_or_404
from app.models import Service
from app.schemas import ServiceCreate, ServiceRead, ServiceUpdate

router = APIRouter(prefix="/services", tags=["services"])

SERVICE_NOT_FOUND = "Услуга не найдена"
NAME_TAKEN = "Услуга с таким названием уже есть"


@router.post("", response_model=ServiceRead, status_code=status.HTTP_201_CREATED)
def create_service(data: ServiceCreate, db: DbSession):
    service = Service(**data.model_dump())
    db.add(service)
    commit_or_conflict(db, NAME_TAKEN)
    db.refresh(service)
    return service


@router.get("", response_model=list[ServiceRead])
def list_services(db: DbSession):
    return db.scalars(select(Service).order_by(Service.name)).all()


@router.get("/{service_id}", response_model=ServiceRead)
def get_service(service_id: int, db: DbSession):
    return get_or_404(db, Service, service_id, SERVICE_NOT_FOUND)


@router.patch("/{service_id}", response_model=ServiceRead)
def update_service(service_id: int, data: ServiceUpdate, db: DbSession):
    service = get_or_404(db, Service, service_id, SERVICE_NOT_FOUND)
    for field, value in data.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(service, field, value)
    commit_or_conflict(db, NAME_TAKEN)
    db.refresh(service)
    return service
