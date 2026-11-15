"""Создать аккаунт администратора: python -m scripts.create_admin <логин>

Пароль спрашивается в терминале и не попадает в историю команд.
"""

import argparse
import getpass
import sys

from app import accounts
from app.database import SessionLocal
from app.errors import AppError
from app.models import UserRole


def main() -> None:
    parser = argparse.ArgumentParser(description="Создать администратора кабинета")
    parser.add_argument("username")
    args = parser.parse_args()

    password = getpass.getpass("Пароль: ")
    if password != getpass.getpass("Повторите пароль: "):
        sys.exit("Пароли не совпадают")

    with SessionLocal() as db:
        try:
            user = accounts.create_user(db, args.username, password, UserRole.ADMIN)
        except AppError as exc:
            sys.exit(f"Ошибка: {exc.message}")
    print(f"Админ «{user.username}» создан. Вход: http://127.0.0.1:8000/web/login")


if __name__ == "__main__":
    main()
