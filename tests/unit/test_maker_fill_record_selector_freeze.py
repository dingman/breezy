"""ARM maker-sharp plan r2 delta D1 / r3 R6: FREEZE the fill-record selector the harm stop reads.

The harm stop (WP-D1, a later producer) judges the maker family on its BOOKED MAKER fills.
It reads ``DurableFillRecord`` rows, which cannot gain a key (S4 r4 row K1: the exact key set
and ``golden_exec_par_wp4_k1.json`` stay unedited), so the selector must be expressible on the
keys that exist. This file freezes it at the FIXTURE level, with no D1 producer code:

* the MAKER MARKER is the ``trade_id`` prefix ``POLL-``
  (``submit_chain.MAKER_POLL_TRADE_ID_PREFIX``, ``submit_chain.is_maker_poll_fill``):
  the resting-order poll is the ONLY writer of that prefix. The create path stores the
  venue's own trade id and the resolver stores ``GET-<id>`` (both TAKER, "counted
  separately", never in the maker win rate);
* the FAMILY is the set of base slugs / stations the family trades. The durable record has no
  family key; the family is a SCOPE the D1 caller supplies (from the family manifest) and applies
  to ``instrument_id``'s base slug. The selector is therefore ``marker AND side == BUY AND
  base slug in family scope``.

Any change to the marker, to who may write it, or to the record keys the selector reads is a
red here, in the commit that makes it, which is the point of freezing the selector with B6.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pytest
from nautilus_trader.model.identifiers import InstrumentId

from tests.unit.ambig_latch_rig import (
    client_module,
    gate_env,  # noqa: F401 -- used via usefixtures
    submit_chain,
    write_canonical_verified,  # noqa: F401 -- reused as a fixture
)
from tests.unit.test_polymarket_us_resting_cancel import _rig
from tests.unit.test_polymarket_us_resting_query import _fill, _query, _records, _rested
from tests.unit.test_polymarket_us_resting_submit import _id_n

FAMILY_STATIONS: Final[frozenset[str]] = frozenset({"nyc"})
SLUG_TEMPLATE: Final[str] = "tc-temp-{city}high-2026-08-25-lt79f"
GOLDEN_KEYS: Final[frozenset[str]] = frozenset(
    {
        "venueOrderId",
        "clientOrderId",
        "instrumentId",
        "orderSide",
        "cumulativeQty",
        "cumulativeCost",
        "cumulativeFee",
        "feeReconciled",
        "tsEvent",
        "venueFeeRaw",
        "tradeId",
        "orderQty",
        "feeCoefficientAtFill",
        "feeSource",
    }
)


def _station_of(instrument_id: str) -> str:
    """The station (city) segment of a daily-high slug: ``tc-temp-<city>high-...``."""
    slug = InstrumentId.from_str(instrument_id).symbol.value.removesuffix("^no")
    return slug.split("-")[2].removesuffix("high")


def select_maker_fills(records: list[Any], *, family_stations: frozenset[str]) -> list[Any]:
    """THE FROZEN SELECTOR (fixture-level reference; D1 must reproduce it exactly)."""
    return [
        r
        for r in records
        if submit_chain.is_maker_poll_fill(r.trade_id)
        and r.order_side == client_module.LONG_ONLY_SIDE
        and _station_of(r.instrument_id) in family_stations
    ]


def _record(
    venue_order_id: str, *, trade_id: str | None, city: str = "nyc", side: str = "BUY"
) -> Any:
    return client_module.DurableFillRecord(
        venue_order_id=venue_order_id,
        client_order_id=f"O-{venue_order_id}",
        instrument_id=f"{SLUG_TEMPLATE.format(city=city)}^no.POLYMARKET_US",
        order_side=side,
        cumulative_qty=Decimal(1),
        cumulative_cost=Decimal("0.40"),
        cumulative_fee=Decimal("0.01"),
        fee_reconciled=True,
        ts_event=1_800_000_000_000_000_000,
        venue_fee_raw="0.01",
        trade_id=trade_id,
        order_qty=Decimal(1),
    )


def test_the_maker_marker_is_the_poll_trade_id_prefix() -> None:
    assert submit_chain.MAKER_POLL_TRADE_ID_PREFIX == "POLL-"
    assert submit_chain.is_maker_poll_fill("POLL-ABC123")
    for not_maker in (None, "", "GET-ABC123", "7d9a1c52-venue-trade-id", "poll-ABC123", " POLL-1"):
        assert not submit_chain.is_maker_poll_fill(not_maker), not_maker


def test_the_poll_trade_id_is_deterministic_visibly_synthetic_and_fits_a_native_trade_id() -> None:
    short = submit_chain.maker_poll_trade_id("ABCDEF123456")
    assert short == "POLL-ABCDEF123456"
    long_id = "A" * 64
    first = submit_chain.maker_poll_trade_id(long_id)
    assert first == submit_chain.maker_poll_trade_id(long_id), "same input, same output"
    assert first != submit_chain.maker_poll_trade_id("B" * 64)
    assert len(first) <= 36 and submit_chain.is_maker_poll_fill(first)


def test_the_selector_picks_only_in_family_poll_booked_buys() -> None:
    records = [
        _record("MAKER-NYC", trade_id="POLL-MAKER-NYC"),
        _record("MAKER-LAX", trade_id="POLL-MAKER-LAX", city="lax"),
        _record("RESOLVER-NYC", trade_id="GET-RESOLVER-NYC"),
        _record("CREATE-NYC", trade_id="7d9a1c52-0000-4000-8000-000000000001"),
        _record("LEGACY-NYC", trade_id=None),
        _record("SELL-NYC", trade_id="POLL-SELL-NYC", side="SELL"),
    ]
    chosen = select_maker_fills(records, family_stations=FAMILY_STATIONS)
    assert [r.venue_order_id for r in chosen] == ["MAKER-NYC"]
    both = select_maker_fills(records, family_stations=frozenset({"nyc", "lax"}))
    assert [r.venue_order_id for r in both] == ["MAKER-NYC", "MAKER-LAX"]
    assert select_maker_fills(records, family_stations=frozenset()) == []


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_a_real_poll_booked_fill_satisfies_the_frozen_selector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fixture selector is tied to the REAL writer: the record the poll booking stores is
    selected, with no key beyond the K1 set."""
    rig, (command,) = await _rested(tmp_path, monkeypatch)
    _fill(rig, 0, commission="0.01")
    await rig.client._query_order(_query(rig, command))
    records = list(_records(rig))
    assert [
        r.venue_order_id for r in select_maker_fills(records, family_stations=FAMILY_STATIONS)
    ] == [_id_n(0)]
    assert select_maker_fills(records, family_stations=frozenset({"lax"})) == []
    stored = rig.client._store_get(f"{client_module.FILL_KEY_PREFIX}{_id_n(0)}")
    assert stored is not None and set(json.loads(stored)) == GOLDEN_KEYS
    await rig.client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_a_fill_booked_by_the_cancel_path_or_the_sweep_carries_the_same_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every maker booking goes through the one winner, so the marker cannot depend on which
    path observed the fill first."""
    from tests.unit.test_polymarket_us_resting_cancel import _cancel_cmd
    from tests.unit.test_polymarket_us_resting_submit import _submit_rest

    rig = await _rig(tmp_path, monkeypatch)
    command = await _submit_rest(rig, 0)
    _fill(rig, 0)
    await rig.client._cancel_order(_cancel_cmd(rig, command))
    records = list(_records(rig))
    assert [
        r.venue_order_id for r in select_maker_fills(records, family_stations=FAMILY_STATIONS)
    ] == [_id_n(0)]
    await rig.client._disconnect()


def test_no_other_src_module_writes_the_maker_marker() -> None:
    """The marker has ONE writer: ``maker_poll_trade_id`` (called by the poll booking). A
    resolver or create-path record carrying ``POLL-`` would pollute the maker win rate."""
    repo = Path(__file__).resolve().parents[2]
    writers = sorted(
        path.relative_to(repo).as_posix()
        for path in (repo / "src").rglob("*.py")
        if "maker_poll_trade_id" in path.read_text(encoding="utf-8")
    )
    assert writers == [
        "src/breezy/adapters/polymarket_us/exec/client.py",
        "src/breezy/adapters/polymarket_us/exec/submit_chain.py",
    ]
    client_text = (repo / "src/breezy/adapters/polymarket_us/exec/client.py").read_text(
        encoding="utf-8"
    )
    # inside the client the marker is produced from the booking helpers only
    assert client_text.count("submit_chain.maker_poll_trade_id(") == 2
