from fastapi import APIRouter, status

from app.database import DbSession
from app.errors import commit_or_conflict, get_or_404
from app.models import Client
from app.schemas import ClientCreate, ClientRead

router = APIRouter(prefix="/clients", tags=["clients"])


@router.post("", response_model=ClientRead, status_code=status.HTTP_201_CREATED)
def create_client(data: ClientCreate, db: DbSession):
    client = Client(**data.model_dump())
    db.add(client)
    commit_or_conflict(db, "Клиент с таким telegram_id уже есть")
    db.refresh(client)
    return client


@router.get("/{client_id}", response_model=ClientRead)
def get_client(client_id: int, db: DbSession):
    return get_or_404(db, Client, client_id, "Клиент не найден")
