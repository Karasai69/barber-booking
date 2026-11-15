from decimal import Decimal


def money(value: Decimal | int) -> str:
    """6000 -> «6 000 ₸». Один формат цены для бота, кабинета и отчётов."""
    return f"{value:,.0f}".replace(",", " ") + " ₸"
