<div align="center">

<img src="app/static/icon.svg" width="72" alt="">

# Barber Booking

**Онлайн-запись в барбершоп.** Клиент записывается через Telegram-бота, мастер отмечает визиты в веб-кабинете, админ видит загрузку и выручку. Две записи на одно время база данных не пропустит.

[![CI](https://github.com/Karasai69/barber-booking/actions/workflows/ci.yml/badge.svg)](https://github.com/Karasai69/barber-booking/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.13-1c2340)
![FastAPI](https://img.shields.io/badge/FastAPI-Jinja2-1c2340)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17-1c2340)
![Celery](https://img.shields.io/badge/Celery-Redis-c8202f)
![aiogram](https://img.shields.io/badge/aiogram-3-1b3d8f)

<img src="docs/screenshots/admin-schedule.png" alt="Расписание мастера на шкале времени у барбер-пола" width="860">

<sub>День мастера у барбер-пола: белый — визит прошёл, красный — клиент сейчас в кресле, синий — запись впереди.</sub>

</div>

## Возможности

| Роль | Где | Что может |
|---|---|---|
| Клиент | Telegram-бот | выбрать услугу, мастера, день и свободное время; записаться; посмотреть и отменить свои записи; получить напоминание за 2 часа |
| Мастер | веб-кабинет | видеть своё расписание по дням, отмечать «пришёл» / «не пришёл» |
| Админ | веб-кабинет и API | мастера, их график и аккаунты, услуги и цены; загрузка и выручка за период; ежедневный отчёт в Telegram |

## Скриншоты

**Админ: загрузка и выручка по мастерам**

![Статистика](docs/screenshots/admin-stats.png)

<table>
  <tr>
    <td width="32%" valign="top"><b>Мастер с телефона</b><br><br><img src="docs/screenshots/barber-schedule-mobile.png" alt="Кабинет мастера на телефоне"></td>
    <td valign="top"><b>Админ: график и аккаунт мастера</b><br><br><img src="docs/screenshots/admin-barber.png" alt="График мастера"></td>
  </tr>
</table>

**Клиент: запись через Telegram-бота**

<table>
  <tr>
    <td width="50%" valign="top" rowspan="2"><b>Свободное время мастера</b><br><br><img src="docs/screenshots/bot-slots.png" alt="Выбор времени в боте"></td>
    <td valign="top"><b>Подтверждение</b><br><br><img src="docs/screenshots/bot-confirm.png" alt="Подтверждение записи"></td>
  </tr>
  <tr>
    <td valign="top"><b>Мои записи и отмена</b><br><br><img src="docs/screenshots/bot-my.png" alt="Список записей клиента"></td>
  </tr>
</table>

<sub>Данные на скриншотах — сгенерированные демо-данные.</sub>

## Стек

FastAPI · SQLAlchemy 2.0 · Alembic · PostgreSQL 17 · Redis · Celery (worker + beat) · aiogram 3 · Jinja2 · JWT (PyJWT) + Argon2 · pytest · Ruff · Docker Compose · GitHub Actions

## Архитектура

```mermaid
flowchart LR
    client([Клиент]) --> tg[Telegram]
    tg <--> bot[bot<br/>aiogram]
    staff([Мастер / админ]) --> api[api<br/>FastAPI + Jinja2]
    bot --> logic[app/booking.py<br/>бизнес-логика]
    api --> logic
    logic --> db[(PostgreSQL)]
    beat[beat<br/>расписание] --> redis[(Redis)]
    redis --> worker[worker<br/>Celery]
    worker --> db
    worker --> tg
```

Бот и API вызывают одну и ту же бизнес-логику. Celery Beat раз в 5 минут ставит задачу напоминаний, worker отправляет сообщения через Telegram Bot API.

## Интересные места

- **Защита от двойной записи на уровне БД.** Ограничение `EXCLUDE USING gist (barber_id WITH =, tstzrange(start_at, end_at) WITH &&) WHERE status = 'booked'`: PostgreSQL сама не даст записать к мастеру две пересекающиеся записи, даже если запросы придут одновременно. Тест отправляет 10 параллельных запросов на одно время, успешен ровно один (`tests/test_booking.py`).
- **Напоминания без дублей.** Задача помечает записи одним `UPDATE ... WHERE reminder_sent_at IS NULL RETURNING`, поэтому два одновременных запуска не отправят одно напоминание дважды. Временная ошибка Telegram приводит к повтору, «бот заблокирован» — нет.
- **Роли и права.** JWT для API, тот же JWT в `HttpOnly` + `SameSite=Lax` cookie для веб-кабинета. Ограничения мастера (только свои записи, только отметка визита) проверяются в бизнес-логике, а не только в роутере.
- **Шкала дня считается на сервере, а не в шаблоне.** `app/timeline.py` переводит время записей в отступы и высоты, ставит рядом записи, которые пересекаются на экране, и отмечает нерабочие часы. Модуль не знает ни про базу, ни про HTML, поэтому покрыт обычными тестами (`tests/test_timeline.py`).
- **Цена хранится в записи.** Если услуга подорожает, выручка за прошлые периоды не изменится.

Все решения с альтернативами описаны в [DECISIONS.md](DECISIONS.md).

## Запуск в Docker

```bash
cp .env.example .env        # заполнить TELEGRAM_BOT_TOKEN, JWT_SECRET, пароль БД
docker compose up -d --build
docker compose run --rm api python -m scripts.create_admin admin   # первый админ
docker compose run --rm api python -m scripts.seed                 # демо-данные (необязательно)
```

- Веб-кабинет: http://localhost:8000
- API и Swagger: http://localhost:8000/docs (кнопка **Authorize** — вход по логину и паролю)

Сервисы: `db`, `redis`, `migrate` (применяет миграции и завершается), `api`, `bot`, `worker`, `beat`.

## Локальная разработка (Windows / PowerShell)

```powershell
python -m venv venv
.\venv\Scripts\pip install -r requirements-dev.txt
docker compose up -d db redis
.\venv\Scripts\alembic upgrade head

.\venv\Scripts\uvicorn app.main:app --reload                          # API
.\venv\Scripts\python -m bot                                          # бот
.\venv\Scripts\celery -A app.celery_app worker --pool=solo -l info    # worker (solo — только для Windows)
.\venv\Scripts\celery -A app.celery_app beat -l info                  # расписание
```

Бот в Docker и бот, запущенный локально, с одним токеном мешают друг другу — запускайте что-то одно.

## Тесты и проверки

```powershell
.\venv\Scripts\pytest        # нужен запущенный db: тесты создают базу barber_booking_test
.\venv\Scripts\ruff check .
.\venv\Scripts\ruff format --check .
```

CI (GitHub Actions) на каждый push: линтер, `alembic check` (модели совпадают с миграциями), тесты на PostgreSQL 17, сборка Docker-образа.

## Структура

```
app/
  models.py        таблицы SQLAlchemy
  booking.py       запись, свободные слоты, статусы, правила
  reminders.py     выбор записей для напоминаний
  stats.py         расписание на день, загрузка и выручка
  timeline.py      раскладка дня мастера на шкале времени
  reports.py       ежедневный отчёт
  tasks.py         задачи Celery
  auth.py          проверка JWT и ролей
  routers/         эндпоинты API
  web.py           веб-кабинет (Jinja2)
  templates/, static/   страницы кабинета, стили, иконка
bot/               Telegram-бот (aiogram)
alembic/           миграции
scripts/           создание админа, демо-данные
tests/             pytest
```

## Автор

Студент 4 курса КазНУ, «Компьютерная инженерия» — [github.com/Karasai69](https://github.com/Karasai69). Первый проект — [AI Finance Tracker](https://github.com/Karasai69/ai-finance-tracker).
