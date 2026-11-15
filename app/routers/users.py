from fastapi import APIRouter, Depends, status
from sqlalchemy import select

from app import accounts
from app.auth import AdminUser, require_admin
from app.database import DbSession
from app.errors import AppError, get_or_404
from app.models import User
from app.schemas import UserCreate, UserRead, UserUpdate

router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(require_admin)])


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(data: UserCreate, db: DbSession):
    return accounts.create_user(db, data.username, data.password, data.role, data.barber_id)


@router.get("", response_model=list[UserRead])
def list_users(db: DbSession):
    return db.scalars(select(User).order_by(User.id)).all()


@router.patch("/{user_id}", response_model=UserRead)
def update_user(user_id: int, data: UserUpdate, db: DbSession, admin: AdminUser):
    user = get_or_404(db, User, user_id, "Пользователь не найден")
    if data.is_active is False and user.id == admin.id:
        raise AppError("Нельзя отключить свой собственный аккаунт")
    if data.password is not None:
        accounts.set_password(db, user, data.password)
    if data.is_active is not None:
        user.is_active = data.is_active
        db.commit()
    db.refresh(user)
    return user
