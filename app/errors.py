from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


class AppError(Exception):
    """Ошибка бизнес-логики. Обработчик в main.py превращает её в HTTP-ответ."""

    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotFoundError(AppError):
    status_code = 404


class ForbiddenError(AppError):
    status_code = 403


class ConflictError(AppError):
    status_code = 409


def get_or_404[T](db: Session, model: type[T], obj_id: int, message: str) -> T:
    obj = db.get(model, obj_id)
    if obj is None:
        raise NotFoundError(message)
    return obj


def commit_or_conflict(db: Session, message: str) -> None:
    """Сохраняет изменения; нарушение UNIQUE превращает в 409."""
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(message) from exc
