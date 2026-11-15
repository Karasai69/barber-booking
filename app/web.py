"""HTML-кабинет мастера и админа (Jinja2).

Вход хранится в cookie с JWT: HttpOnly (недоступна JavaScript) и SameSite=Lax
(браузер не отправит её с POST-формы чужого сайта — защита от CSRF).
"""

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import select

from app import accounts, booking
from app.auth import user_from_token
from app.booking import now_local, shop_tz
from app.config import settings
from app.database import DbSession
from app.errors import AppError, commit_or_conflict, get_or_404
from app.formatting import money
from app.models import AppointmentStatus, Barber, Schedule, Service, User, UserRole
from app.routers.appointments import own_barber_id
from app.schemas import BarberCreate, ScheduleCreate, ServiceCreate, ServiceUpdate
from app.security import create_access_token
from app.stats import day_appointments, period_stats, summarize
from app.timeline import build_timeline, summarize_day

router = APIRouter(prefix="/web", include_in_schema=False)
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

COOKIE_NAME = "access_token"
WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
WEEKDAYS_FULL = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
MONTHS_GENITIVE = [
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
]
ALL_BARBERS = "all"  # значение barber_id в адресе для вида «Все мастера»
STATUS_LABELS = {
    AppointmentStatus.BOOKED: "Записан",
    AppointmentStatus.CANCELLED: "Отменил",
    AppointmentStatus.COMPLETED: "Пришёл",
    AppointmentStatus.NO_SHOW: "Не пришёл",
}


templates.env.filters["money"] = money
templates.env.filters["hm"] = lambda dt: dt.astimezone(shop_tz()).strftime("%H:%M")
templates.env.globals.update(
    WEEKDAYS=WEEKDAYS,
    WEEKDAYS_FULL=WEEKDAYS_FULL,
    MONTHS_GENITIVE=MONTHS_GENITIVE,
    STATUS_LABELS=STATUS_LABELS,
    Status=AppointmentStatus,
)

Text = Annotated[str, Form()]
OptionalText = Annotated[str, Form()]


# --- Вспомогательное ---


def redirect(url: str, **params: object) -> RedirectResponse:
    query = urlencode({k: v for k, v in params.items() if v is not None})
    return RedirectResponse(
        f"{url}?{query}" if query else url, status_code=status.HTTP_303_SEE_OTHER
    )


def render(request: Request, name: str, user: User | None, status_code: int = 200, **ctx):
    context = {
        "user": user,
        "msg": request.query_params.get("msg"),
        "error": request.query_params.get("error"),
        **ctx,
    }
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def validation_message(exc: ValidationError) -> str:
    err = exc.errors()[0]
    field = err["loc"][-1] if err["loc"] else ""
    return f"{field}: {err['msg']}" if field else err["msg"]


def web_user(request: Request, db: DbSession) -> User:
    user = user_from_token(db, request.cookies.get(COOKIE_NAME))
    if user is None:
        raise HTTPException(status.HTTP_303_SEE_OTHER, headers={"Location": "/web/login"})
    return user


WebUser = Annotated[User, Depends(web_user)]


def web_admin(user: WebUser) -> User:
    if user.role != UserRole.ADMIN:
        raise HTTPException(status.HTTP_303_SEE_OTHER, headers={"Location": "/web/schedule"})
    return user


WebAdmin = Annotated[User, Depends(web_admin)]


# --- Вход ---


@router.get("")
def home(user: WebUser):
    return redirect("/web/admin" if user.role == UserRole.ADMIN else "/web/schedule")


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: DbSession):
    if user_from_token(db, request.cookies.get(COOKIE_NAME)) is not None:
        return redirect("/web")
    return render(request, "login.html", None)


@router.post("/login")
def login(request: Request, db: DbSession, username: Text, password: Text):
    user = accounts.authenticate(db, username, password)
    if user is None:
        return render(
            request,
            "login.html",
            None,
            status_code=401,
            error="Неверный логин или пароль",
            username=username,
        )
    response = redirect("/web")
    response.set_cookie(
        COOKIE_NAME,
        create_access_token(user.id),
        max_age=settings.ACCESS_TOKEN_MINUTES * 60,
        httponly=True,
        samesite="lax",
        secure=settings.COOKIE_SECURE,
    )
    return response


@router.post("/logout")
def logout():
    response = redirect("/web/login")
    response.delete_cookie(COOKIE_NAME)
    return response


# --- Расписание (мастер и админ) ---


def _selected_barber(raw: str | None, barbers: list[Barber]) -> int | None:
    """Какого мастера показывает админ. None — вид «Все мастера».

    Без параметра открываем первого работающего мастера: у одного мастера расписание
    рисуется шкалой времени, а общий список остаётся отдельным видом.
    """
    if raw is None:
        active = [b for b in barbers if b.is_active] or barbers
        return active[0].id if active else None
    if raw.isdigit() and int(raw) in {b.id for b in barbers}:
        return int(raw)
    return None


@router.get("/schedule", response_class=HTMLResponse)
def schedule(
    request: Request,
    db: DbSession,
    user: WebUser,
    day: date | None = None,
    barber_id: str | None = None,
):
    now = now_local()
    day = day or now.date()
    own = own_barber_id(user)
    if own is not None:
        barbers = []
        selected = own
        barber_name = db.get(Barber, own).name
        barber_param = ""
    else:
        barbers = list(db.scalars(select(Barber).order_by(Barber.name)))
        selected = _selected_barber(barber_id, barbers)
        barber_name = next((b.name for b in barbers if b.id == selected), None)
        barber_param = str(selected) if selected is not None else ALL_BARBERS

    rows = day_appointments(db, day, selected)
    timeline = None
    if selected is not None:
        shifts = db.execute(
            select(Schedule.start_time, Schedule.end_time).where(
                Schedule.barber_id == selected, Schedule.weekday == day.weekday()
            )
        ).all()
        timeline = build_timeline(rows, [tuple(shift) for shift in shifts], day, now)
    return render(
        request,
        "schedule.html",
        user,
        day=day,
        today=now.date(),
        prev_day=day - timedelta(days=1),
        next_day=day + timedelta(days=1),
        rows=rows,
        barbers=barbers,
        barber_id=selected,
        barber_name=barber_name,
        barber_param=barber_param,
        single_barber=selected is not None,
        timeline=timeline,
        summary=summarize_day(timeline.blocks) if timeline else None,
    )


@router.post("/appointments/{appointment_id}/status")
def set_status(
    appointment_id: int,
    db: DbSession,
    user: WebUser,
    new_status: Annotated[AppointmentStatus, Form(alias="status")],
    day: Text,
    barber_id: Annotated[str, Form()] = "",
):
    back = {"day": day, "barber_id": barber_id or None}
    try:
        booking.change_status(db, appointment_id, new_status, barber_id=own_barber_id(user))
    except AppError as exc:
        return redirect("/web/schedule", **back, error=exc.message)
    return redirect("/web/schedule", **back, msg=f"Статус: {STATUS_LABELS[new_status]}")


# --- Админ: статистика ---


@router.get("/admin", response_class=HTMLResponse)
def admin_stats(
    request: Request,
    db: DbSession,
    user: WebAdmin,
    date_from: date | None = None,
    date_to: date | None = None,
):
    date_to = date_to or now_local().date()
    date_from = date_from or date_to - timedelta(days=6)
    try:
        rows = period_stats(db, date_from, date_to)
        error = None
    except AppError as exc:
        rows, error = [], exc.message
    return render(
        request,
        "admin_stats.html",
        user,
        date_from=date_from,
        date_to=date_to,
        rows=rows,
        total=summarize(rows),
        **({"error": error} if error else {}),
    )


# --- Админ: мастера ---


@router.get("/admin/barbers", response_class=HTMLResponse)
def admin_barbers(request: Request, db: DbSession, user: WebAdmin):
    barbers = db.scalars(select(Barber).order_by(Barber.is_active.desc(), Barber.name)).all()
    accounts_by_barber = {
        u.barber_id: u for u in db.scalars(select(User).where(User.barber_id.is_not(None)))
    }
    return render(request, "admin_barbers.html", user, barbers=barbers, accounts=accounts_by_barber)


@router.post("/admin/barbers")
def admin_create_barber(db: DbSession, user: WebAdmin, name: Text, telegram_id: OptionalText = ""):
    try:
        data = BarberCreate(name=name.strip(), telegram_id=telegram_id.strip() or None)
    except ValidationError as exc:
        return redirect("/web/admin/barbers", error=validation_message(exc))
    barber = Barber(**data.model_dump())
    db.add(barber)
    try:
        commit_or_conflict(db, "Мастер с таким telegram_id уже есть")
    except AppError as exc:
        return redirect("/web/admin/barbers", error=exc.message)
    return redirect(f"/web/admin/barbers/{barber.id}", msg="Мастер добавлен. Задайте график.")


@router.post("/admin/barbers/{barber_id}/toggle")
def admin_toggle_barber(barber_id: int, db: DbSession, user: WebAdmin):
    barber = get_or_404(db, Barber, barber_id, "Мастер не найден")
    barber.is_active = not barber.is_active
    db.commit()
    state = "снова принимает записи" if barber.is_active else "больше не принимает записи"
    return redirect("/web/admin/barbers", msg=f"{barber.name} {state}")


@router.get("/admin/barbers/{barber_id}", response_class=HTMLResponse)
def admin_barber(barber_id: int, request: Request, db: DbSession, user: WebAdmin):
    barber = get_or_404(db, Barber, barber_id, "Мастер не найден")
    schedules = db.scalars(
        select(Schedule)
        .where(Schedule.barber_id == barber_id)
        .order_by(Schedule.weekday, Schedule.start_time)
    ).all()
    account = db.scalar(select(User).where(User.barber_id == barber_id))
    return render(
        request,
        "admin_barber.html",
        user,
        barber=barber,
        schedules=schedules,
        account=account,
    )


@router.post("/admin/barbers/{barber_id}/schedules")
def admin_add_schedule(
    barber_id: int,
    db: DbSession,
    user: WebAdmin,
    weekday: Text,
    start_time: Text,
    end_time: Text,
):
    back = f"/web/admin/barbers/{barber_id}"
    get_or_404(db, Barber, barber_id, "Мастер не найден")
    try:
        data = ScheduleCreate(weekday=weekday, start_time=start_time, end_time=end_time)
    except ValidationError as exc:
        return redirect(back, error=validation_message(exc))
    db.add(Schedule(barber_id=barber_id, **data.model_dump()))
    db.commit()
    return redirect(back, msg="Смена добавлена")


@router.post("/admin/barbers/{barber_id}/schedules/{schedule_id}/delete")
def admin_delete_schedule(barber_id: int, schedule_id: int, db: DbSession, user: WebAdmin):
    schedule_row = db.get(Schedule, schedule_id)
    if schedule_row is not None and schedule_row.barber_id == barber_id:
        db.delete(schedule_row)
        db.commit()
    return redirect(f"/web/admin/barbers/{barber_id}", msg="Смена удалена")


@router.post("/admin/barbers/{barber_id}/account")
def admin_create_account(
    barber_id: int, db: DbSession, user: WebAdmin, username: Text, password: Text
):
    back = f"/web/admin/barbers/{barber_id}"
    try:
        accounts.create_user(db, username, password, UserRole.BARBER, barber_id)
    except AppError as exc:
        return redirect(back, error=exc.message)
    return redirect(back, msg="Аккаунт создан. Передайте мастеру логин и пароль.")


@router.post("/admin/users/{user_id}/password")
def admin_reset_password(user_id: int, db: DbSession, user: WebAdmin, password: Text):
    target = get_or_404(db, User, user_id, "Пользователь не найден")
    back = f"/web/admin/barbers/{target.barber_id}" if target.barber_id else "/web/admin/barbers"
    try:
        accounts.set_password(db, target, password)
    except AppError as exc:
        return redirect(back, error=exc.message)
    return redirect(back, msg="Пароль изменён")


# --- Админ: услуги ---


@router.get("/admin/services", response_class=HTMLResponse)
def admin_services(request: Request, db: DbSession, user: WebAdmin):
    services = db.scalars(select(Service).order_by(Service.name)).all()
    return render(request, "admin_services.html", user, services=services)


def _parse_price(value: str) -> Decimal | str:
    try:
        return Decimal(value.replace(" ", "").replace(",", "."))
    except InvalidOperation:
        return value  # пусть ошибку покажет валидация схемы


@router.post("/admin/services")
def admin_create_service(
    db: DbSession, user: WebAdmin, name: Text, price: Text, duration_min: Text
):
    try:
        data = ServiceCreate(
            name=name.strip(), price=_parse_price(price), duration_min=duration_min
        )
    except ValidationError as exc:
        return redirect("/web/admin/services", error=validation_message(exc))
    db.add(Service(**data.model_dump()))
    try:
        commit_or_conflict(db, "Услуга с таким названием уже есть")
    except AppError as exc:
        return redirect("/web/admin/services", error=exc.message)
    return redirect("/web/admin/services", msg="Услуга добавлена")


@router.post("/admin/services/{service_id}")
def admin_update_service(
    service_id: int, db: DbSession, user: WebAdmin, price: Text, duration_min: Text
):
    service = get_or_404(db, Service, service_id, "Услуга не найдена")
    try:
        data = ServiceUpdate(price=_parse_price(price), duration_min=duration_min)
    except ValidationError as exc:
        return redirect("/web/admin/services", error=validation_message(exc))
    service.price = data.price
    service.duration_min = data.duration_min
    db.commit()
    return redirect("/web/admin/services", msg=f"«{service.name}» обновлена")
