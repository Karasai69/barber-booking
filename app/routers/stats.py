from datetime import date

from fastapi import APIRouter, Depends

from app.auth import require_admin
from app.database import DbSession
from app.schemas import PeriodStatsRead
from app.stats import period_stats, summarize

router = APIRouter(prefix="/stats", tags=["stats"], dependencies=[Depends(require_admin)])


@router.get("", response_model=PeriodStatsRead)
def get_stats(date_from: date, date_to: date, db: DbSession):
    """Загрузка и выручка по мастерам за период (обе даты включительно)."""
    rows = period_stats(db, date_from, date_to)
    return PeriodStatsRead(
        date_from=date_from,
        date_to=date_to,
        barbers=rows,
        total=summarize(rows),
    )
