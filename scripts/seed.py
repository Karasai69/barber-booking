"""Демо-данные для разработки: python -m scripts.seed

Ничего не делает, если услуги уже есть.
"""

from datetime import time
from decimal import Decimal

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Barber, Schedule, Service

SERVICES = [
    ("Мужская стрижка", Decimal("6000"), 60),
    ("Стрижка бороды", Decimal("3500"), 30),
    ("Стрижка + борода", Decimal("8500"), 90),
]
BARBERS = ["Арман", "Ерлан"]
WORK_DAYS = range(0, 6)  # пн–сб
WORK_HOURS = (time(10, 0), time(20, 0))


def main() -> None:
    with SessionLocal() as db:
        if db.scalar(select(Service.id).limit(1)) is not None:
            print("Данные уже есть, ничего не меняю.")
            return
        db.add_all(Service(name=n, price=p, duration_min=d) for n, p, d in SERVICES)
        for name in BARBERS:
            barber = Barber(name=name)
            barber.schedules = [
                Schedule(weekday=day, start_time=WORK_HOURS[0], end_time=WORK_HOURS[1])
                for day in WORK_DAYS
            ]
            db.add(barber)
        db.commit()
        print(f"Добавлено: {len(SERVICES)} услуги, {len(BARBERS)} мастера с графиком пн–сб.")


if __name__ == "__main__":
    main()
