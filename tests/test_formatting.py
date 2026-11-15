from decimal import Decimal

import pytest

from app.formatting import money


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("6000"), "6 000 ₸"),
        (Decimal("3500.00"), "3 500 ₸"),
        (Decimal("570000"), "570 000 ₸"),
        (Decimal("500"), "500 ₸"),
        (0, "0 ₸"),
    ],
)
def test_money(value, expected):
    assert money(value) == expected
