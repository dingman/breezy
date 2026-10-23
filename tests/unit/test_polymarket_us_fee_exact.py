"""ARM maker-sharp B6 review H1: the UNROUNDED modelled taker fee (``taker_fee_exact_at_fill``).

The exec package may not carry complement arithmetic (barrier X3), so the resting commission
envelope takes the exact ``theta * q * p * (1 - p)`` from the fee module, which already owns that
arithmetic. ``taker_fee_at_fill`` is its banker's-rounded cent form and must not change.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from breezy.adapters.polymarket_us.fees import taker_fee_at_fill, taker_fee_exact_at_fill

AMBIGUOUS_START_NS = 1_789_603_200_000_000_000  # 2026-09-17T00:00:00Z
THETA = Decimal("0.06")


@pytest.mark.parametrize(
    ("price", "quantity", "expected"),
    [
        ("0.75", "1", "0.01125"),
        ("0.89", "1", "0.005874"),
        ("0.03", "1", "0.001746"),
        ("0.97", "1", "0.001746"),
        ("0.40", "2", "0.0288"),
        ("0", "1", "0"),
        ("1", "1", "0"),
    ],
)
def test_the_exact_fee_is_theta_q_p_one_minus_p_unrounded(
    price: str, quantity: str, expected: str
) -> None:
    exact = taker_fee_exact_at_fill(
        quantity=Decimal(quantity),
        price=Decimal(price),
        ts_event_ns=AMBIGUOUS_START_NS,
        fee_coefficient_at_fill=THETA,
    )
    assert exact == Decimal(expected)


@pytest.mark.parametrize("price", ["0.03", "0.40", "0.75", "0.89", "0.97"])
def test_the_cent_fee_is_the_exact_fee_rounded_bankers(price: str) -> None:
    exact = taker_fee_exact_at_fill(
        quantity=Decimal(1),
        price=Decimal(price),
        ts_event_ns=AMBIGUOUS_START_NS,
        fee_coefficient_at_fill=THETA,
    )
    cents = taker_fee_at_fill(
        quantity=Decimal(1),
        price=Decimal(price),
        ts_event_ns=AMBIGUOUS_START_NS,
        fee_coefficient_at_fill=THETA,
    )
    assert exact is not None and cents is not None
    assert cents.as_decimal() == exact.quantize(Decimal("0.01"))


def test_an_unpinned_schedule_has_no_exact_fee() -> None:
    assert (
        taker_fee_exact_at_fill(
            quantity=Decimal(1),
            price=Decimal("0.44"),
            ts_event_ns=AMBIGUOUS_START_NS,
            fee_coefficient_at_fill=None,
        )
        is None
    )


@pytest.mark.parametrize("price", ["-0.01", "1.01"])
def test_a_price_outside_the_binary_range_is_refused(price: str) -> None:
    with pytest.raises(ValueError, match="outside"):
        taker_fee_exact_at_fill(
            quantity=Decimal(1),
            price=Decimal(price),
            ts_event_ns=AMBIGUOUS_START_NS,
            fee_coefficient_at_fill=THETA,
        )
