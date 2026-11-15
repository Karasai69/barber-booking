from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery_app = Celery("barber_booking", broker=settings.REDIS_URL, include=["app.tasks"])

celery_app.conf.update(
    timezone=settings.TIMEZONE,  # crontab ниже считается по времени барбершопа
    enable_utc=True,
    task_ignore_result=True,  # результаты задач нам не нужны, backend не настраиваем
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "send-reminders": {
            "task": "app.tasks.send_reminders",
            "schedule": 5 * 60,  # каждые 5 минут
        },
        "daily-report": {
            "task": "app.tasks.send_daily_report",
            "schedule": crontab(hour=21, minute=0),
        },
    },
)
