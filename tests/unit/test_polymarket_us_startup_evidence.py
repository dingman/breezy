"""C1/C2 (plan rev 6.1): durable startup position evidence.

Written by :meth:`PolymarketUSExecutionClient._refresh_startup_position_evidence`
at the END of ``_connect`` -- after reconciliation and this client's own
positions read -- and read back via
:meth:`PolymarketUSExecutionClient.read_startup_position_evidence`. The
strategy's never-arm/re-arm gate (another seam) reads this key at ``on_start``
and FAILS CLOSED if it is absent, refused, or incomplete: every flag recorded
here must be exactly right, because nothing downstream double-checks it.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.accounting.factory import AccountFactory
from nautilus_trader.cache.cache import Cache
from nautilus_trader.cache.config import CacheConfig
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.common.providers import InstrumentProvider

from breezy.adapters.polymarket_us.exec.client import (
    FILL_INDEX_KEY_PREFIX,
    STARTUP_EVIDENCE_KEY,
    PolymarketUSExecutionClient,
    StartupPositionEvidence,
    StartupPositionSnapshot,
)
from breezy.adapters.polymarket_us.exec.endpoints import (
    ACCOUNT_BALANCES_PATH,
    OPEN_ORDERS_PATH,
    PORTFOLIO_POSITIONS_PATH,
)
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE
from breezy.runtime.sqlite_store import SqliteStateStore
from tests.unit.test_polymarket_us_exec_client import (
    ACCOUNT_NUMBER,
    CLIENT_ID,
    TRADER_ID,
    _balances_payload,
    _build_rig,
    _clean_exec_fault_latch,  # noqa: F401 -- reused as a fixture
    _PrivateReadStub,
)


def _positions(instrument_slug: str, net_position: str) -> dict[str, Any]:
    return {instrument_slug: {"netPosition": net_position}}


@pytest.mark.asyncio
async def test_connect_writes_startup_evidence_with_the_fresh_positions_listed(
    tmp_path: Path,
) -> None:
    rig = _build_rig(tmp_path, positions=_positions("tc-temp-nyc-h-2026-09-11-70-72", "3"))

    await rig.client._connect()

    evidence = rig.client.read_startup_position_evidence()
    assert evidence is not None
    assert evidence.eof_complete is True
    assert evidence.position_read_refused is False
    assert evidence.fill_walk_complete is True
    assert evidence.positions == (
        StartupPositionSnapshot(slug="tc-temp-nyc-h-2026-09-11-70-72", net_position="3"),
    )
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_a_5xx_positions_read_at_connect_is_recorded_as_refused(tmp_path: Path) -> None:
    rig = _build_rig(tmp_path)
    rig.read.raises[PORTFOLIO_POSITIONS_PATH] = RuntimeError("venue read failed")

    await rig.client._connect()

    evidence = rig.client.read_startup_position_evidence()
    assert evidence is not None
    assert evidence.position_read_refused is True
    assert evidence.eof_complete is False
    assert evidence.positions == ()
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_a_non_eof_complete_page_at_connect_is_recorded_as_refused(tmp_path: Path) -> None:
    rig = _build_rig(tmp_path)
    rig.read._payloads[PORTFOLIO_POSITIONS_PATH] = {  # type: ignore[attr-defined]
        "positions": {},
        "eof": False,
    }

    await rig.client._connect()

    evidence = rig.client.read_startup_position_evidence()
    assert evidence is not None
    assert evidence.eof_complete is False
    assert evidence.position_read_refused is True
    assert evidence.positions == ()
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_evidence_is_overwritten_not_accumulated_across_connects(tmp_path: Path) -> None:
    """Exactly one row, the most recent evidence, never a history."""
    slug = "tc-temp-nyc-h-2026-09-11-70-72"
    rig = _build_rig(tmp_path, positions=_positions(slug, "1"))
    await rig.client._connect()
    first = rig.client.read_startup_position_evidence()
    assert first is not None and first.positions == (
        StartupPositionSnapshot(slug=slug, net_position="1"),
    )
    await rig.client._disconnect()

    rig.read._payloads[PORTFOLIO_POSITIONS_PATH] = {  # type: ignore[attr-defined]
        "positions": {},
        "eof": True,
    }
    await rig.client._connect()

    second = rig.client.read_startup_position_evidence()
    assert second is not None
    assert second.positions == ()
    assert second.ts_ns >= first.ts_ns
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_read_startup_position_evidence_is_none_before_any_write(tmp_path: Path) -> None:
    """The store is open but `_connect` has never completed -- absent, not
    a malformed record and not an empty-but-present one."""
    rig = _build_rig(tmp_path)
    rig.client._open_state_store()

    assert rig.client.read_startup_position_evidence() is None


# ---------------------------------------------------------------------------
# C2: the fill walk
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fill_walk_is_complete_when_no_instrument_has_ever_filled(
    tmp_path: Path,
) -> None:
    """An absent fill index reads back `[]` -- success, not absence."""
    rig = _build_rig(tmp_path)

    await rig.client._connect()

    evidence = rig.client.read_startup_position_evidence()
    assert evidence is not None
    assert evidence.fill_walk_complete is True
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_a_corrupt_fill_index_marks_the_walk_incomplete(tmp_path: Path) -> None:
    rig = _build_rig(tmp_path)
    await rig.client._connect()
    assert rig.client.read_startup_position_evidence().fill_walk_complete is True  # type: ignore[union-attr]

    rig.client._store_set(f"{FILL_INDEX_KEY_PREFIX}{rig.instrument.id}", b"not valid json")
    await rig.client._refresh_startup_position_evidence()

    evidence = rig.client.read_startup_position_evidence()
    assert evidence is not None
    assert evidence.fill_walk_complete is False
    await rig.client._disconnect()


class _EmptyInstrumentsCache(Cache):
    """Round-2 RED test double: `instruments()` is unconditionally `[]`,
    regardless of what was ever added to the cache.

    `_build_rig` (`test_polymarket_us_exec_client.py`) always calls
    `cache.add_instrument(...)`, so `self._cache.instruments(self.venue)`
    is never empty through that fixture -- this is the only way to reach
    `_fill_walk_complete`'s empty-enumeration branch. `Cache.instruments` is
    a native `cpdef` method (`cache/cache.pyx`), overridable from a Python
    subclass but NOT reassignable on an instance or the class itself
    (`AttributeError: ... is not writable` / `TypeError: cannot set ...
    attribute of immutable type`, both verified directly against the
    installed native class) -- subclassing at construction time is the only
    seam available.
    """

    def instruments(self, *args: Any, **kwargs: Any) -> list[Any]:
        return []


class _RaisingInstrumentsCache(Cache):
    """Round-2 RED test double: `instruments()` unconditionally raises. The
    REAL `Cache.instruments()` (a pure filtered list comprehension over an
    in-memory dict, no I/O) cannot raise under any real `Venue` input, so
    this is the only way to reach `_fill_walk_complete`'s enumeration-failed
    branch."""

    def instruments(self, *args: Any, **kwargs: Any) -> list[Any]:
        raise RuntimeError("cache instruments() unavailable")


def _build_client_with_cache(tmp_path: Path, cache: Cache) -> PolymarketUSExecutionClient:
    """Mirrors `_build_rig` (`test_polymarket_us_exec_client.py`), except the
    caller supplies the `Cache` -- needed for the two fail-closed
    `_fill_walk_complete` branches `_build_rig` itself cannot reach (see the
    two test-double docstrings above). No instrument is loaded into the
    provider either: neither test needs one, and `_wait_for_instruments`
    only latches a non-fatal refusal on an empty provider, never aborts
    `_connect`.
    """
    loop = asyncio.get_running_loop()
    clock = LiveClock()
    msgbus = MessageBus(trader_id=TRADER_ID, clock=clock)
    provider = InstrumentProvider()

    read = _PrivateReadStub(
        {
            ACCOUNT_BALANCES_PATH: _balances_payload(),
            PORTFOLIO_POSITIONS_PATH: {"positions": {}, "eof": True},
            OPEN_ORDERS_PATH: {"orders": []},
        },
    )

    def _on_account_state(state: Any) -> None:
        if cache.account(state.account_id) is None:
            cache.add_account(AccountFactory.create(state))
        else:
            cache.account(state.account_id).apply(state)

    msgbus.register(endpoint="Portfolio.update_account", handler=_on_account_state)

    return PolymarketUSExecutionClient(
        loop=loop,
        client_id=CLIENT_ID,
        venue=POLYMARKET_US_VENUE,
        instrument_provider=provider,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
        private_read=read,
        state_store_opener=lambda: SqliteStateStore(tmp_path / "exec_state.db"),
        account_number=ACCOUNT_NUMBER,
        instrument_wait_timeout_s=1.0,
        account_registration_timeout_s=1.0,
    )


@pytest.mark.asyncio
async def test_an_empty_instrument_enumeration_marks_the_fill_walk_incomplete(
    tmp_path: Path,
) -> None:
    """Item 3 (slice 4 review, round 2): a cache reporting ZERO instruments
    is fail-closed, not vacuously complete -- `_wait_for_instruments`
    already ran earlier in `_connect`, so this shape is exactly as
    suspicious as a corrupt fill index, never a real CRH trading day."""
    cache = _EmptyInstrumentsCache(
        database=None, config=CacheConfig(database=None, flush_on_start=False),
    )
    client = _build_client_with_cache(tmp_path, cache)

    await client._connect()

    evidence = client.read_startup_position_evidence()
    assert evidence is not None
    assert evidence.fill_walk_complete is False
    await client._disconnect()


@pytest.mark.asyncio
async def test_instrument_enumeration_raising_marks_the_fill_walk_incomplete(
    tmp_path: Path,
) -> None:
    """Item 3 (slice 4 review, round 2): the enumeration itself failing is
    fail-closed the same way -- caught, recorded, never propagated out of
    `_connect`."""
    cache = _RaisingInstrumentsCache(
        database=None, config=CacheConfig(database=None, flush_on_start=False),
    )
    client = _build_client_with_cache(tmp_path, cache)

    await client._connect()

    evidence = client.read_startup_position_evidence()
    assert evidence is not None
    assert evidence.fill_walk_complete is False
    await client._disconnect()


def test_startup_position_evidence_round_trips_through_bytes() -> None:
    evidence = StartupPositionEvidence(
        ts_ns=123,
        eof_complete=True,
        position_read_refused=False,
        fill_walk_complete=True,
        positions=(StartupPositionSnapshot(slug="a-slug", net_position="2.5"),),
    )

    round_tripped = StartupPositionEvidence.from_bytes(evidence.to_bytes())

    assert round_tripped == evidence


def test_startup_evidence_key_is_namespaced_under_this_venue_only() -> None:
    assert STARTUP_EVIDENCE_KEY == "exec/polymarket_us/startup_evidence"


# ---------------------------------------------------------------------------
# RESTING_BID_HUNT Rev 2 §4.3 -- open-order evidence in the durable record
# ---------------------------------------------------------------------------


def _one_resting_order(slug: str = "tc-temp-sfohigh-2026-09-16-gte70lt71f") -> dict[str, Any]:
    return {
        "orders": [
            {
                "id": "RESTING0001A",
                "marketSlug": slug,
                "side": "ORDER_SIDE_BUY",
                "type": "ORDER_TYPE_LIMIT",
                "price": {"value": "0.01", "currency": "USD"},
                "quantity": 1,
                "cumQuantity": 0,
                "leavesQuantity": 1,
                "tif": "TIME_IN_FORCE_GOOD_TILL_CANCEL",
                "state": "ORDER_STATE_NEW",
                "createTime": "2026-09-16T16:50:00.000000000Z",
            }
        ]
    }


@pytest.mark.asyncio
async def test_connect_records_an_empty_open_order_set_as_read_not_refused(
    tmp_path: Path,
) -> None:
    rig = _build_rig(tmp_path)
    await rig.client._connect()
    evidence = rig.client.read_startup_position_evidence()
    await rig.client._disconnect()

    assert evidence is not None
    assert OPEN_ORDERS_PATH in rig.read.paths
    assert evidence.open_orders_read_refused is False
    assert evidence.open_orders == ()


@pytest.mark.asyncio
async def test_a_5xx_open_orders_read_at_connect_is_recorded_as_refused(tmp_path: Path) -> None:
    """Fail closed: an enumeration error is a refusal, never an assumed-empty book."""
    rig = _build_rig(tmp_path)
    rig.read.raises[OPEN_ORDERS_PATH] = RuntimeError("venue read failed")
    await rig.client._connect()
    evidence = rig.client.read_startup_position_evidence()
    await rig.client._disconnect()

    assert evidence is not None
    assert evidence.open_orders_read_refused is True
    assert evidence.open_orders == ()
    # The positions read is independent and still succeeded.
    assert evidence.position_read_refused is False


@pytest.mark.asyncio
async def test_a_malformed_open_orders_body_at_connect_is_recorded_as_refused(
    tmp_path: Path,
) -> None:
    rig = _build_rig(tmp_path)
    rig.read._payloads[OPEN_ORDERS_PATH] = {"orders": [{"id": "x"}]}  # type: ignore[attr-defined]
    await rig.client._connect()
    evidence = rig.client.read_startup_position_evidence()
    await rig.client._disconnect()

    assert evidence is not None
    assert evidence.open_orders_read_refused is True


@pytest.mark.asyncio
async def test_one_resting_order_at_connect_is_enumerated_into_the_evidence(
    tmp_path: Path,
) -> None:
    rig = _build_rig(tmp_path)
    rig.read._payloads[OPEN_ORDERS_PATH] = _one_resting_order()  # type: ignore[attr-defined]
    await rig.client._connect()
    evidence = rig.client.read_startup_position_evidence()
    await rig.client._disconnect()

    assert evidence is not None
    assert evidence.open_orders_read_refused is False
    assert [o.venue_order_id for o in evidence.open_orders] == ["RESTING0001A"]
    assert evidence.open_orders[0].market_slug == "tc-temp-sfohigh-2026-09-16-gte70lt71f"
    assert evidence.open_orders[0].state == "ORDER_STATE_NEW"
    # The strategy-side predicate reads the SAME bytes and refuses.
    from breezy.strategy.current_rung_hold.trial_day_latch import (
        STARTUP_OPEN_ORDERS_PRESENT_REASON,
        startup_evidence_refusal_reason,
    )

    decoded = json.loads(evidence.to_bytes())
    assert startup_evidence_refusal_reason(decoded) == STARTUP_OPEN_ORDERS_PRESENT_REASON


def test_startup_position_evidence_round_trips_open_orders_through_bytes() -> None:
    from breezy.adapters.polymarket_us.exec.client import StartupOpenOrderSnapshot

    evidence = StartupPositionEvidence(
        ts_ns=123,
        eof_complete=True,
        position_read_refused=False,
        fill_walk_complete=True,
        positions=(),
        open_orders_read_refused=False,
        open_orders=(
            StartupOpenOrderSnapshot(
                venue_order_id="RESTING0001A",
                market_slug="a-slug",
                state="ORDER_STATE_NEW",
            ),
        ),
    )
    assert StartupPositionEvidence.from_bytes(evidence.to_bytes()) == evidence


def test_a_pre_open_order_record_decodes_as_open_orders_refused() -> None:
    """A durable record written before §4.3 carries no open-order fields;
    it decodes (never raises -- the boot rewrites it) as REFUSED, so nothing
    reading the old bytes can mistake 'unrecorded' for 'none open'."""
    legacy = json.dumps(
        {
            "v": 1,
            "ts_ns": 5,
            "eof_complete": True,
            "position_read_refused": False,
            "fill_walk_complete": True,
            "positions": [],
        }
    ).encode("utf-8")
    decoded = StartupPositionEvidence.from_bytes(legacy)
    assert decoded.open_orders_read_refused is True
    assert decoded.open_orders == ()
