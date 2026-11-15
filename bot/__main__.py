"""Запуск бота: python -m bot"""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import settings
from bot.handlers import router


async def main() -> None:
    if settings.TELEGRAM_BOT_TOKEN is None:
        raise SystemExit("TELEGRAM_BOT_TOKEN не задан в .env")
    bot = Bot(
        settings.TELEGRAM_BOT_TOKEN.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
