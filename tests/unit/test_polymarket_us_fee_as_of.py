"""AUD-13b: the taker fee coefficient AS OF a fill's ``ts_event``.

Ruling ``docs/evidence/RULING_venue_reconciliation_R1_R2_2026-09-21.md`` R-1 = O4
(Revision 3): ``ts_event < 2026-09-17T00:00:00Z`` -> 0.06; ``>= 17:00:00Z`` ->
0.0695; the window between is AMBIGUOUS and refuses (``None``), as does any
time before the earliest pinned date (2026-08-25, the docs snapshot the 0.06
pin is sourced from). Evidence: ``FEE_SCHEDULE_PIN_2026-09-18.md``.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.objects import Money

from breezy.adapters.polymarket_us import fees
from breezy.adapters.polymarket_us.fees import (
    DOCUMENTED_TAKER_FEE_COEFFICIENT,
    fee_schedule_bucket,
    taker_fee_at_fill,
)

EARLIEST_NS = 1_787_616_000_000_000_000  # 2026-08-25T00:00:00Z
AMBIGUOUS_START_NS = 1_789_603_200_000_000_000  # 2026-09-17T00:00:00Z
AMBIGUOUS_END_NS = 1_789_664_400_000_000_000  # 2026-09-17T17:00:00Z


def test_the_boundaries_are_the_evidence_pinned_instants() -> None:
    assert fees._FEE_SCHEDULE_EARLIEST_PINNED_NS == EARLIEST_NS
    assert fees._FEE_DRIFT_AMBIGUOUS_START_NS == AMBIGUOUS_START_NS
    assert fees._FEE_DRIFT_AMBIGUOUS_END_NS == AMBIGUOUS_END_NS


@pytest.mark.parametrize(
    ("ts_event", "expected", "bucket"),
    [
        (EARLIEST_NS - 1, None, "UNPINNED"),
        (EARLIEST_NS, DOCUMENTED_TAKER_FEE_COEFFICIENT, "PRE_DRIFT"),
        (AMBIGUOUS_START_NS - 1, DOCUMENTED_TAKER_FEE_COEFFICIENT, "PRE_DRIFT"),
        (AMBIGUOUS_START_NS, None, "AMBIGUOUS"),
        (AMBIGUOUS_END_NS - 1, None, "AMBIGUOUS"),
        (AMBIGUOUS_END_NS, Decimal("0.0695"), "POST_DRIFT"),
    ],
)
def test_the_coefficient_as_of_each_boundary(
    ts_event: int, expected: Decimal | None, bucket: str,
) -> None:
    assert fees._fee_coefficient_as_of(ts_event) == expected
    assert fee_schedule_bucket(ts_event) == bucket


def test_a_record_carrying_its_own_coefficient_wins_over_the_schedule() -> None:
    fee = taker_fee_at_fill(
        quantity=Decimal(1),
        price=Decimal("0.44"),
        ts_event_ns=AMBIGUOUS_START_NS,
        fee_coefficient_at_fill=Decimal("0.06"),
    )
    assert fee == Money(Decimal("0.01"), USD)


def test_the_ambiguous_window_refuses_rather_than_defaulting() -> None:
    assert taker_fee_at_fill(
        quantity=Decimal(1),
        price=Decimal("0.44"),
        ts_event_ns=AMBIGUOUS_START_NS,
        fee_coefficient_at_fill=None,
    ) is None


def test_the_two_coefficients_differ_at_the_cent_at_0_44_and_round_bankers() -> None:
    pre = taker_fee_at_fill(
        quantity=Decimal(1), price=Decimal("0.44"),
        ts_event_ns=AMBIGUOUS_START_NS - 1, fee_coefficient_at_fill=None,
    )
    post = taker_fee_at_fill(
        quantity=Decimal(1), price=Decimal("0.44"),
        ts_event_ns=AMBIGUOUS_END_NS, fee_coefficient_at_fill=None,
    )
    assert (pre, post) == (Money(Decimal("0.01"), USD), Money(Decimal("0.02"), USD))


@pytest.mark.parametrize("price", ["-0.01", "1.01"])
def test_a_price_outside_the_binary_range_is_refused(price: str) -> None:
    with pytest.raises(ValueError, match="outside"):
        taker_fee_at_fill(
            quantity=Decimal(1), price=Decimal(price),
            ts_event_ns=AMBIGUOUS_END_NS, fee_coefficient_at_fill=None,
        )
