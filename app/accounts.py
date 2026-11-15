"""Аккаунты веб-кабинета: создание и проверка логина/пароля."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError, commit_or_conflict, get_or_404
from app.models import Barber, User, UserRole
from app.security import hash_password, verify_password

MIN_PASSWORD_LENGTH = 8

# Если логина нет, всё равно проверяем пароль против фиктивного хэша.
# Иначе по времени ответа можно понять, какие логины существуют.
_DUMMY_HASH = hash_password("dummy-password-for-timing")


def normalize_username(username: str) -> str:
    return username.strip().lower()


def authenticate(db: Session, username: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.username == normalize_username(username)))
    if user is None:
        verify_password(password, _DUMMY_HASH)
        return None
    if not verify_password(password, user.password_hash) or not user.is_active:
        return None
    return user


def _check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AppError(f"Пароль должен быть не короче {MIN_PASSWORD_LENGTH} символов")


def create_user(
    db: Session,
    username: str,
    password: str,
    role: UserRole,
    barber_id: int | None = None,
) -> User:
    username = normalize_username(username)
    if not username:
        raise AppError("Логин не может быть пустым")
    _check_password(password)
    if role == UserRole.BARBER:
        if barber_id is None:
            raise AppError("Для аккаунта мастера нужен barber_id")
        get_or_404(db, Barber, barber_id, "Мастер не найден")
    elif barber_id is not None:
        raise AppError("Аккаунт админа не привязывается к мастеру")

    user = User(
        username=username,
        password_hash=hash_password(password),
        role=role,
        barber_id=barber_id,
    )
    db.add(user)
    commit_or_conflict(db, "Логин уже занят или у этого мастера уже есть аккаунт")
    db.refresh(user)
    return user


def set_password(db: Session, user: User, password: str) -> None:
    _check_password(password)
    user.password_hash = hash_password(password)
    db.commit()
