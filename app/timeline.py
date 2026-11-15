"""Раскладка расписания мастера на шкале времени («столб времени» в кабинете).

Здесь только расчёты: в какую высоту и на какой отступ поставить каждую запись,
какие часы подписать, где линия «сейчас». Модуль не ходит в базу и не знает про
HTML, поэтому его легко проверить тестами.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

PX_PER_MINUTE = 1.4  # час на экране = 84 px
MIN_BLOCK_PX = 34.0  # ниже этого текст записи не читается
BLOCK_GAP_PX = 4.0  # зазор между соседними записями
DEFAULT_DAY = (10 * 60, 20 * 60)  # если нет ни смен, ни записей
HOUR_LABEL_CLEARANCE_PX = 16.0  # подпись часа прячем, если на неё наезжает «сейчас»

# Вид записи на шкале. Цвета столба: белый — прошло, красный — сейчас, синий — впереди.
DONE = "done"  # пришёл
NOW = "now"  # идёт сейчас, визит не отмечен
OVERDUE = "overdue"  # время вышло, а визит так и не отмечен
UPCOMING = "upcoming"  # ещё не начался
NO_SHOW = "no_show"
CANCELLED = "cancelled"

KIND_LABELS = {
    DONE: "пришёл",
    NOW: "в кресле",
    OVERDUE: "отметьте визит",
    UPCOMING: "",
    NO_SHOW: "не пришёл",
    CANCELLED: "отмена",
}


@dataclass(frozen=True)
class Block:
    appt: Any  # app.stats.DayAppointment
    kind: str
    top: float  # px от начала шкалы
    height: float  # px
    left: float  # % ширины: записи, которые пересекаются на экране, стоят рядом
    width: float  # %

    @property
    def label(self) -> str:
        return KIND_LABELS[self.kind]


@dataclass(frozen=True)
class HourMark:
    label: str
    top: float
    hidden: bool = False


@dataclass(frozen=True)
class Zone:
    """Нерабочее время внутри шкалы."""

    top: float
    height: float


@dataclass(frozen=True)
class Timeline:
    height: float
    hours: list[HourMark]
    blocks: list[Block]
    off: list[Zone]
    now_top: float | None
    now_label: str


@dataclass(frozen=True)
class DaySummary:
    done: int
    upcoming: int
    revenue: Decimal
    attention: list[Block]  # записи, которые ждут отметки «пришёл / не пришёл»
    next_up: Block | None


def appointment_kind(appt: Any, now: datetime) -> str:
    status = appt.status.value
    if status == "completed":
        return DONE
    if status == "no_show":
        return NO_SHOW
    if status == "cancelled":
        return CANCELLED
    if now < appt.start_at:
        return UPCOMING
    return NOW if now < appt.end_at else OVERDUE


def _minutes(value: time) -> int:
    return value.hour * 60 + value.minute


def _day_minutes(moment: datetime, day: date, tz) -> int:
    """Минуты от полуночи выбранного дня; запись, уходящая за полночь, обрезается."""
    local = moment.astimezone(tz)
    if local.date() > day:
        return 24 * 60
    if local.date() < day:
        return 0
    return _minutes(local.time())


def _merge(intervals: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _assign_lanes(rects: Sequence[tuple[float, float]]) -> list[tuple[int, int]]:
    """Для каждой записи: (номер колонки, сколько колонок в её группе).

    У одного мастера активные записи не пересекаются (это гарантирует база), но
    отменённая запись и новая на то же время пересекаются. Короткая запись на экране
    выше своего времени и тоже может наехать на следующую. Такие записи ставим рядом.
    `rects` — (верх, низ) в px, отсортированные по верху.
    """
    result: list[tuple[int, int]] = [(0, 1)] * len(rects)
    group: list[tuple[int, int]] = []  # (индекс записи, колонка)
    lane_ends: list[float] = []
    group_end = 0.0

    def flush() -> None:
        for index, lane in group:
            result[index] = (lane, len(lane_ends))

    for index, (top, bottom) in enumerate(rects):
        if group and top >= group_end:
            flush()
            group, lane_ends = [], []
        for lane, end in enumerate(lane_ends):
            if end <= top:
                lane_ends[lane] = bottom
                break
        else:
            lane = len(lane_ends)
            lane_ends.append(bottom)
        group.append((index, lane))
        group_end = max(group_end, bottom) if len(group) > 1 else bottom
    flush()
    return result


def build_timeline(
    appointments: Sequence[Any],
    shifts: Iterable[tuple[time, time]],
    day: date,
    now: datetime,
) -> Timeline | None:
    """Шкала дня одного мастера. None — в этот день нет ни смен, ни записей."""
    tz = now.tzinfo
    work = _merge((_minutes(start), _minutes(end)) for start, end in shifts)
    spans = [
        (_day_minutes(a.start_at, day, tz), _day_minutes(a.end_at, day, tz)) for a in appointments
    ]
    if not work and not spans:
        return None

    starts = [s for s, _ in work] + [s for s, _ in spans]
    ends = [e for _, e in work] + [e for _, e in spans]
    axis_start = min(starts) // 60 * 60
    axis_end = min(-(-max(ends) // 60) * 60, 24 * 60)
    if axis_end <= axis_start:
        axis_start, axis_end = DEFAULT_DAY
    height = (axis_end - axis_start) * PX_PER_MINUTE

    def y(minute: int) -> float:
        return round((minute - axis_start) * PX_PER_MINUTE, 1)

    now_top = None
    if now.date() == day and axis_start <= _minutes(now.time()) <= axis_end:
        now_top = y(_minutes(now.time()))

    hours = []
    for minute in range(axis_start, axis_end + 1, 60):
        top = y(minute)
        covered = now_top is not None and abs(top - now_top) < HOUR_LABEL_CLEARANCE_PX
        hours.append(HourMark(f"{minute // 60}:00", top, hidden=covered))

    off: list[Zone] = []
    if work:
        cursor = axis_start
        for start, end in work + [(axis_end, axis_end)]:
            if start > cursor:
                off.append(Zone(y(cursor), round((start - cursor) * PX_PER_MINUTE, 1)))
            cursor = max(cursor, end)

    order = sorted(range(len(appointments)), key=lambda i: (spans[i][0], spans[i][1]))
    rects = []
    for i in order:
        start, end = spans[i]
        block_height = max((end - start) * PX_PER_MINUTE - BLOCK_GAP_PX, MIN_BLOCK_PX)
        rects.append((y(start), y(start) + block_height))
    lanes = _assign_lanes(rects)

    blocks = []
    for i, (top, bottom), (lane, lane_count) in zip(order, rects, lanes, strict=True):
        blocks.append(
            Block(
                appt=appointments[i],
                kind=appointment_kind(appointments[i], now),
                top=top,
                height=round(bottom - top, 1),
                left=round(100 * lane / lane_count, 2),
                width=round(100 / lane_count, 2),
            )
        )

    return Timeline(
        height=round(height, 1),
        hours=hours,
        blocks=blocks,
        off=off,
        now_top=now_top,
        now_label=now.strftime("%H:%M"),
    )


def summarize_day(blocks: Sequence[Block]) -> DaySummary:
    upcoming = [b for b in blocks if b.kind == UPCOMING]
    done = [b for b in blocks if b.kind == DONE]
    return DaySummary(
        done=len(done),
        upcoming=len(upcoming),
        revenue=sum((b.appt.price for b in done), Decimal("0")),
        attention=[b for b in blocks if b.kind in (NOW, OVERDUE)],
        next_up=upcoming[0] if upcoming else None,
    )
