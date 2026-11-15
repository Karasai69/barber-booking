"""Отправка сообщений в Telegram из синхронного кода (задачи Celery).

Бот (aiogram) асинхронный, а задачам Celery достаточно одного HTTP-запроса
к Bot API, поэтому здесь обычный синхронный httpx.
"""

import httpx

from app.config import settings

API_URL = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramError(Exception):
    """Не удалось отправить. permanent=True — повторять бессмысленно
    (например, пользователь заблокировал бота)."""

    def __init__(self, message: str, permanent: bool = False):
        super().__init__(message)
        self.permanent = permanent


def send_message(chat_id: int, text: str) -> None:
    if settings.TELEGRAM_BOT_TOKEN is None:
        raise TelegramError("TELEGRAM_BOT_TOKEN не задан", permanent=True)
    url = API_URL.format(token=settings.TELEGRAM_BOT_TOKEN.get_secret_value())
    try:
        response = httpx.post(
            url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=10
        )
    except httpx.HTTPError as exc:
        # Сообщение исключения может содержать URL с токеном — не выводим его.
        raise TelegramError(f"Сетевая ошибка: {type(exc).__name__}") from None
    if response.status_code == 200:
        return
    description = response.json().get("description", "") if response.content else ""
    # 400 (чат не найден) и 403 (бот заблокирован) не исправятся повтором.
    raise TelegramError(
        f"Telegram {response.status_code}: {description}",
        permanent=response.status_code in (400, 403),
    )
