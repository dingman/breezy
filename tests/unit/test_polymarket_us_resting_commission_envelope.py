"""ARM maker-sharp B6 review H1: the resting commission envelope across the price range.

The bound on a resting fill's commission is ``max(modelled cent fee, exact unrounded
theta*q*p*(1-p), that exact fee rounded UP to the next cent) + COMMISSION_ENVELOPE_SLACK_USD``.
The modelled fee alone banker's-rounds to 0.01 across the whole 0.75-0.89 band and to 0.00
below ~0.07 / above ~0.93, so a venue that charges the unrounded or a round-up figure would
latch ``resting_commission_out_of_envelope`` after the first ordinary fill.

Every sender and private read is a local double: no network, no venue contact.
No ``exec`` import here (barrier X1): everything goes through ``ambig_latch_rig``.
"""

from __future__ import annotations

from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Final

import pytest

from breezy.adapters.polymarket_us.fees import taker_fee_coefficient_of
from tests.unit.ambig_latch_rig import (
    gate_env,  # noqa: F401 -- used via usefixtures
    submit_chain,
    write_canonical_verified,  # noqa: F401 -- reused as a fixture
)
from tests.unit.polymarket_us_exec_shapes import build_no_leg_instrument
from tests.unit.test_polymarket_us_resting_query import (
    _fill,
    _query,
    _reasons,
    _records,
    _rested,
)
from tests.unit.test_polymarket_us_resting_submit import _id_n

LATCH: Final[str] = submit_chain.RESTING_COMMISSION_OUT_OF_ENVELOPE_REASON
CENT: Final[Decimal] = Decimal("0.01")
PRICES: Final[tuple[str, ...]] = ("0.03", "0.75", "0.89", "0.97")


def _exact(price: str) -> Decimal:
    theta = taker_fee_coefficient_of(build_no_leg_instrument())
    assert theta is not None
    p = Decimal(price)
    return theta * p * (1 - p)


def _round_up(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_CEILING)


async def _latched_at(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, price: str, raw: Decimal
) -> bool:
    rig, _commands = await _rested(tmp_path, monkeypatch)
    client = rig.client
    target = client._resting_target_of(_id_n(0))
    assert target is not None
    ts_ns = client._clock.timestamp_ns()
    within = client._commission_in_envelope(
        taker_fee_coefficient_of(build_no_leg_instrument()), raw, Decimal(price), Decimal(1), ts_ns
    )
    client._check_commission_envelope(target, within)
    latched = LATCH in _reasons(rig)
    await client._disconnect()
    return latched


@pytest.mark.parametrize("price", PRICES)
def test_the_bound_covers_the_unrounded_and_the_rounded_up_fee_at_every_price(price: str) -> None:
    exact = _exact(price)
    modelled = exact.quantize(CENT)
    bound = submit_chain.commission_envelope_bound(modelled=modelled, exact=exact)
    assert exact <= bound and _round_up(exact) <= bound
    assert (
        bound == max(modelled, exact, _round_up(exact)) + submit_chain.COMMISSION_ENVELOPE_SLACK_USD
    )


def test_the_slack_is_half_a_cent_and_the_bound_is_never_below_the_modelled_fee() -> None:
    assert submit_chain.COMMISSION_ENVELOPE_SLACK_USD == Decimal("0.005")
    assert submit_chain.commission_envelope_bound(
        modelled=Decimal("0.05"), exact=Decimal("0.001")
    ) == Decimal("0.055")


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
@pytest.mark.parametrize("price", PRICES)
@pytest.mark.parametrize("shape", ["unrounded", "rounded_up", "zero"])
async def test_a_realistic_venue_fee_never_latches_at_any_price(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, price: str, shape: str
) -> None:
    exact = _exact(price)
    raw = {"unrounded": exact, "rounded_up": _round_up(exact), "zero": Decimal(0)}[shape]
    assert await _latched_at(tmp_path, monkeypatch, price=price, raw=raw) is False


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_three_cents_at_0_75_still_latches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert await _latched_at(tmp_path, monkeypatch, price="0.75", raw=Decimal("0.03")) is True


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
@pytest.mark.parametrize("price", PRICES)
async def test_a_fee_well_above_the_bound_latches_at_every_price(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, price: str
) -> None:
    raw = _round_up(_exact(price)) + Decimal("0.02")
    assert await _latched_at(tmp_path, monkeypatch, price=price, raw=raw) is True


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_an_out_of_envelope_fill_books_the_venue_figure_but_never_reconciled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B6 review S9: the venue figure is kept (conservative), but a commission outside the
    envelope is not a reconciled fee: it must stay out of the reconciled population."""
    rig, (command,) = await _rested(tmp_path, monkeypatch)
    _fill(rig, 0, commission="0.50")
    await rig.client._query_order(_query(rig, command))
    (record,) = _records(rig)
    assert record.cumulative_fee == Decimal("0.50") and record.venue_fee_raw == "0.50"
    assert record.fee_reconciled is False
    assert LATCH in _reasons(rig)
    await rig.client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_an_in_envelope_fill_stays_reconciled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, (command,) = await _rested(tmp_path, monkeypatch)
    _fill(rig, 0, commission="0.01")
    await rig.client._query_order(_query(rig, command))
    (record,) = _records(rig)
    assert record.fee_reconciled is True
    await rig.client._disconnect()
