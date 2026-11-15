"""Зависимости FastAPI для проверки входа и прав."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.database import DbSession
from app.models import User, UserRole
from app.security import decode_access_token

# auto_error=False: без токена вернём свою понятную 401, а не стандартную.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)


def user_from_token(db: Session, token: str | None) -> User | None:
    """Пользователь по токену. Каждый раз берём его из базы, чтобы
    отключённый аккаунт сразу терял доступ, даже с ещё живым токеном."""
    if not token:
        return None
    user_id = decode_access_token(token)
    if user_id is None:
        return None
    user = db.get(User, user_id)
    return user if user is not None and user.is_active else None


def get_current_user(
    db: DbSession, token: Annotated[str | None, Depends(oauth2_scheme)]
) -> User:
    user = user_from_token(db, token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Нужно войти",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_admin(user: CurrentUser) -> User:
    if user.role != UserRole.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нужны права администратора")
    return user


AdminUser = Annotated[User, Depends(require_admin)]
