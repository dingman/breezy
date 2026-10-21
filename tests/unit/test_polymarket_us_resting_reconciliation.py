"""S4 WP5 (ARM maker-sharp B6), CC-1: the reconciliation-fill carve-out in
``calculate_commission`` for a MAKER fill of one of our own bound rests.

Plan: ``docs/plans/backlog/MAKER_2026-10-12/S4_exec_resting_order_path_plan_r4_delta.md``
section 2 WP5 ("Reconciliation carve-out", the stricter of arch N-7 and sec E1) and section 3
row CC-1. Today a MAKER reconciliation fill is priced at TAKER and REFUSES (Breezy was
taker-only). With a resting-order path a maker fill of our own rest is expected, so the
refusal is skipped ONLY when all of: the instrument is the bound rest's, the fill is for
quantity 1, the price EQUALS that rest's limit price (Decimal equality), and the rest is
unretired (still in the ``resting:`` index). Default OFF: an unreadable or unavailable ledger
refuses, and the method NEVER raises. The price is always the taker figure.

Every sender and private read is a local double: no network, no venue contact.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pytest
from nautilus_trader.model.enums import LiquiditySide
from nautilus_trader.model.objects import Price, Quantity

from tests.unit.ambig_latch_rig import (
    client_module,
    gate_env,  # noqa: F401 -- used via usefixtures
    submit_chain,
    write_canonical_verified,  # noqa: F401 -- reused as a fixture
)
from tests.unit.polymarket_us_exec_shapes import build_instrument, build_no_leg_instrument
from tests.unit.test_polymarket_us_resting_cancel import (
    _auto_cancel,
    _cancel_cmd,
    _rig,
)
from tests.unit.test_polymarket_us_resting_submit import _id_n, _Rig, _submit_rest

_INDEX_KEY: Final[str] = client_module.RESTING_INDEX_KEY
#: The fixture rest's limit price on the NO leg (the shared helper posts 0.40).
REST_PX: Final[str] = "0.40"


def _maker_commission(
    rig: _Rig, *, qty: int = 1, price: str = REST_PX, yes_leg: bool = False
) -> Any:
    instrument = build_instrument() if yes_leg else build_no_leg_instrument()
    return rig.client.calculate_commission(
        instrument,
        Quantity(qty, instrument.size_precision),
        Price(Decimal(price), instrument.price_precision),
        LiquiditySide.MAKER,
    )


def _refusals(rig: _Rig) -> list[str]:
    return [r.reason for r in rig.client._trading_refusals if "MAKER" in r.reason]


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_maker_reconciliation_commission_does_not_refuse_bound_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    await _submit_rest(rig, 0)
    taker = rig.client.calculate_commission(
        build_no_leg_instrument(),
        Quantity(1, build_no_leg_instrument().size_precision),
        Price(Decimal(REST_PX), build_no_leg_instrument().price_precision),
        LiquiditySide.TAKER,
    )
    commission = _maker_commission(rig)
    assert commission == taker, "the carve-out prices at the taker figure"
    assert _refusals(rig) == [], "no MAKER refusal for our own bound rest"
    warnings = rig.client.log_lines("warning", "carve-out")
    assert len(warnings) == 1
    assert "tc-temp-nychigh" in warnings[0], "the slug is named"
    assert REST_PX not in warnings[0] and _id_n(0) not in warnings[0], "slug only"
    await rig.client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
@pytest.mark.parametrize(
    ("qty", "price"),
    [(2, REST_PX), (1, "0.41"), (1, "0.39"), (3, "0.55")],
)
async def test_maker_fill_on_ledger_slug_with_foreign_price_or_qty_still_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qty: int, price: str
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    await _submit_rest(rig, 0)
    commission = _maker_commission(rig, qty=qty, price=price)
    assert commission is not None, "still priced (at taker)"
    assert len(_refusals(rig)) == 1, "a foreign price or quantity is an alarm"
    assert rig.client.log_lines("warning", "carve-out") == []
    await rig.client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_unbound_maker_reconciliation_fill_still_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[CHAR] No bound rest at all: exactly today's refusal."""
    rig = await _rig(tmp_path, monkeypatch)
    assert _maker_commission(rig) is not None
    assert len(_refusals(rig)) == 1
    await rig.client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_a_retired_rest_no_longer_carves_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    command = await _submit_rest(rig, 0)
    _auto_cancel(rig)
    await rig.client._cancel_order(_cancel_cmd(rig, command))
    assert json.loads(rig.client._store_get(_INDEX_KEY)) == []
    assert _maker_commission(rig) is not None
    assert len(_refusals(rig)) == 1, "the row is retired: the fill is no longer ours to expect"
    await rig.client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_the_yes_leg_of_the_same_slug_does_not_carve_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    await _submit_rest(rig, 0)
    assert _maker_commission(rig, yes_leg=True) is not None
    assert len(_refusals(rig)) == 1
    await rig.client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_unavailable_index_carve_out_is_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The carve-out half of ``test_unavailable_index_issues_zero_posts_and_carve_out_off``:
    with the index UNREADABLE the carve-out is OFF (default OFF) and the fill refuses."""
    rig = await _rig(tmp_path, monkeypatch)
    await _submit_rest(rig, 0)
    rig.client._store_set(_INDEX_KEY, b"{not json")
    assert _maker_commission(rig) is not None
    assert any("MAKER" in r for r in _refusals(rig))
    await rig.client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_calculate_commission_never_raises_with_store_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[CHAR] With the store closed or any enumeration error the method REFUSES (maps to
    "not in the ledger"), never raises: a raise here is a node that does not start."""
    rig = await _rig(tmp_path, monkeypatch)
    await _submit_rest(rig, 0)
    client = rig.client

    def boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("store closed")

    monkeypatch.setattr(client, "_enumerate_resting_ledger", boom)
    assert _maker_commission(rig) is not None
    assert len(_refusals(rig)) == 1
    await client._disconnect()
    # and truly closed: the store handle is gone after _disconnect
    again = _maker_commission(rig)
    assert again is not None


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_taker_and_sideless_reconciliation_fills_are_unchanged_by_the_carve_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    await _submit_rest(rig, 0)
    instrument = build_no_leg_instrument()
    for side in (LiquiditySide.TAKER, LiquiditySide.NO_LIQUIDITY_SIDE):
        priced = rig.client.calculate_commission(
            instrument,
            Quantity(1, instrument.size_precision),
            Price(Decimal(REST_PX), instrument.price_precision),
            side,
        )
        assert priced is not None
    assert _refusals(rig) == []
    assert submit_chain.MAKER_COMMISSION_SIGN_VERIFIED is False
    await rig.client._disconnect()
