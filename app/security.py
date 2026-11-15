"""Хэширование паролей и JWT."""

from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash

from app.config import settings

ALGORITHM = "HS256"

# Argon2 — рекомендуемый алгоритм: медленный и требует много памяти,
# поэтому подбирать пароли по украденной базе очень дорого.
_password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _password_hash.verify(password, password_hash)


def create_access_token(user_id: int) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=settings.ACCESS_TOKEN_MINUTES)
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, settings.JWT_SECRET.get_secret_value(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> int | None:
    """id пользователя из токена или None, если токен поддельный или истёк."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET.get_secret_value(), algorithms=[ALGORITHM])
        return int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError):
        return None
