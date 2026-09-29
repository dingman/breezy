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
    _FILL_TS_EVENT_MAX_SKEW_NS,
    _MULTI_FILL_PENDING_SENTINEL,
    _POSITION_LAG_PENDING_TTL_NS,
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
from tests.unit.polymarket_us_exec_shapes import build_position
from tests.unit.test_polymarket_us_exec_client import (
    ACCOUNT_NUMBER,
    CLIENT_ID,
    TRADER_ID,
    _balances_payload,
    _build_rig,
    _clean_exec_fault_latch,  # noqa: F401 -- reused as a fixture
    _no_leg_instrument,
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
    rig.read._payloads[PORTFOLIO_POSITIONS_PATH] = {
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

    rig.read._payloads[PORTFOLIO_POSITIONS_PATH] = {
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
    rig.read._payloads[OPEN_ORDERS_PATH] = {"orders": [{"id": "x"}]}
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
    rig.read._payloads[OPEN_ORDERS_PATH] = _one_resting_order()
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


# ---------------------------------------------------------------------------
# R-7-IMPL (RULING R-7, plan `docs/plans/backlog/R-7-IMPL_plan_r1_2026-09-26.md`):
# `_match_position_lag`'s confirming half, driven directly with seeded
# pending entries -- deterministic, no dependency on wall-clock skew.
# ---------------------------------------------------------------------------

_SEND_NS = 10_000_000_000_000
_RECV_NS = _SEND_NS + 500_000_000
_FILL_TS_EVENT = _SEND_NS + 50_000_000


def _seed(client: PolymarketUSExecutionClient, instrument_id: Any, entry: tuple[Any, ...]) -> None:
    client._position_lag_pending = {instrument_id: entry}


@pytest.mark.asyncio
async def test_r7_a_confirming_long_read_emits_and_pops_the_pending_entry(
    tmp_path: Path,
) -> None:
    """T2 (matcher half): the confirming read pops the entry and records the
    instrument as last-known-long."""
    rig = _build_rig(tmp_path)
    slug = str(rig.instrument.raw_symbol)
    _seed(rig.client, rig.instrument.id, (_FILL_TS_EVENT, _SEND_NS, _RECV_NS, "coid-1", 0))

    rig.client._match_position_lag({slug: build_position(slug)}, _RECV_NS + 5_000_000_000)

    assert rig.client._position_lag_pending == {}
    assert rig.client._position_lag_last_long == frozenset({rig.instrument.id})


@pytest.mark.asyncio
async def test_r7_a_no_leg_confirming_long_read_emits_and_pops_the_pending_entry(
    tmp_path: Path,
) -> None:
    """T3 (NO leg): the same confirmation works for a NO-leg instrument id,
    keyed against the shared base slug, with a NO-shaped position payload."""
    rig = _build_rig(tmp_path)
    no_instrument = _no_leg_instrument()
    rig.client._cache.add_instrument(no_instrument)
    slug = str(rig.instrument.raw_symbol)
    no_position = build_position(slug)
    no_position["netPosition"] = "-4"
    no_position["marketMetadata"] = {"slug": slug, "outcome": "No"}
    _seed(rig.client, no_instrument.id, (_FILL_TS_EVENT, _SEND_NS, _RECV_NS, "coid-1", 0))

    rig.client._match_position_lag({slug: no_position}, _RECV_NS + 5_000_000_000)

    assert rig.client._position_lag_pending == {}
    assert rig.client._position_lag_last_long == frozenset({no_instrument.id})


@pytest.mark.asyncio
async def test_r7_a_zero_or_negative_fill_ts_event_is_rejected_and_dropped(
    tmp_path: Path,
) -> None:
    """T4 (second defence): `fill_ts_event <= 0` is rejected as
    `TS_EVENT_ABSENT` and never produces a record."""
    rig = _build_rig(tmp_path)
    slug = str(rig.instrument.raw_symbol)
    _seed(rig.client, rig.instrument.id, (0, _SEND_NS, _RECV_NS, "coid-1", 0))

    rig.client._match_position_lag({slug: build_position(slug)}, _RECV_NS + 5_000_000_000)

    assert rig.client._position_lag_pending == {}
    assert rig.client._position_lag_last_long == frozenset()


@pytest.mark.asyncio
@pytest.mark.parametrize("absent_fill_ts_event", [0, -1])
async def test_r7_ts_event_absent_is_rejected_even_when_a_local_now_fallback_would_pass_skew(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    absent_fill_ts_event: int,
) -> None:
    """T4 (ISOLATED): the test above shares `_RECV_NS + 5_000_000_000` as its
    confirming read, which lands `TS_EVENT_SKEW_FUTURE`-rejected too if a
    regression dropped the `<= 0` guard and fell back to that same local
    `now_ns` -- the two guards mask each other, and the old test cannot tell
    which one actually fired (mutation evidence gap, L-33).

    Here the confirming read is chosen at `_RECV_NS + 1`: *inside* the skew
    window a local-`now_ns` fallback would land in (mutation M-b: drop the
    `<= 0` guard, substitute `now_ns` for the absent `fill_ts_event`). Under
    M-b this fixture would pass both skew checks and confirm the read as
    LONG. Only `TS_EVENT_ABSENT` firing on its own -- independent of skew --
    keeps it pending-cleared with NO record ever constructed and the
    instrument NEVER marked long."""
    from breezy.adapters.polymarket_us.exec import client as client_module
    from breezy.domain.position_reporting_lag import PositionReportingLag as real_record_cls

    captured: list[Any] = []

    def _capturing(*args: Any, **kwargs: Any) -> Any:
        record = real_record_cls(*args, **kwargs)
        captured.append(record)
        return record

    monkeypatch.setattr(client_module, "PositionReportingLag", _capturing)

    rig = _build_rig(tmp_path)
    slug = str(rig.instrument.raw_symbol)
    _seed(
        rig.client,
        rig.instrument.id,
        (absent_fill_ts_event, _SEND_NS, _RECV_NS, "coid-1", 0),
    )

    confirming_read_ts = _RECV_NS + 1  # inside the fallback's skew window

    rig.client._match_position_lag({slug: build_position(slug)}, confirming_read_ts)

    assert rig.client._position_lag_pending == {}
    assert rig.client._position_lag_last_long == frozenset()
    assert captured == []


def test_r7_the_skew_bound_is_pinned_to_two_seconds() -> None:
    """T5 (magnitude pin): the plan
    (`docs/plans/backlog/R-7-IMPL_plan_r1_2026-09-26.md:48`,
    `_FILL_TS_EVENT_MAX_SKEW_NS: Final[int] = 2 * 1_000_000_000`) fixes the
    skew bound at exactly 2s. The boundary tests around this one compute
    their own fixtures FROM the live constant, so they self-adjust if its
    magnitude ever changes and would keep passing against a materially
    widened bound (mutation M-c: widen to 100s) -- only a literal pin like
    this one catches that."""
    assert _FILL_TS_EVENT_MAX_SKEW_NS == 2_000_000_000


@pytest.mark.asyncio
async def test_r7_a_fill_two_point_five_seconds_before_send_is_rejected_literal(
    tmp_path: Path,
) -> None:
    """T5 (literal boundary): independent of the live constant's magnitude,
    a fill whose venue `tsEvent` lands 2.5s before `send_ns` -- comfortably
    past the plan's registered 2s bound -- must be rejected as
    `TS_EVENT_SKEW_PAST`, even though the read IS long. A bound mutated to
    100s (M-c) would accept this fixture and confirm it LONG instead."""
    rig = _build_rig(tmp_path)
    slug = str(rig.instrument.raw_symbol)
    fill_ts_event = _SEND_NS - 2_500_000_000
    _seed(rig.client, rig.instrument.id, (fill_ts_event, _SEND_NS, _RECV_NS, "coid-1", 0))

    rig.client._match_position_lag({slug: build_position(slug)}, _RECV_NS + 5_000_000_000)

    assert rig.client._position_lag_pending == {}
    assert rig.client._position_lag_last_long == frozenset()


@pytest.mark.asyncio
async def test_r7_exactly_the_past_skew_bound_is_accepted(tmp_path: Path) -> None:
    """T5: `fill_ts_event == send_ns - bound` is the boundary -- accepted."""
    rig = _build_rig(tmp_path)
    slug = str(rig.instrument.raw_symbol)
    fill_ts_event = _SEND_NS - _FILL_TS_EVENT_MAX_SKEW_NS
    _seed(rig.client, rig.instrument.id, (fill_ts_event, _SEND_NS, _RECV_NS, "coid-1", 0))

    rig.client._match_position_lag({slug: build_position(slug)}, _RECV_NS + 5_000_000_000)

    assert rig.client._position_lag_pending == {}
    assert rig.client._position_lag_last_long == frozenset({rig.instrument.id})


@pytest.mark.asyncio
async def test_r7_one_nanosecond_past_the_past_skew_bound_is_rejected(tmp_path: Path) -> None:
    """T5: `fill_ts_event == send_ns - bound - 1` is rejected as
    `TS_EVENT_SKEW_PAST`, even though the position IS long."""
    rig = _build_rig(tmp_path)
    slug = str(rig.instrument.raw_symbol)
    fill_ts_event = _SEND_NS - _FILL_TS_EVENT_MAX_SKEW_NS - 1
    _seed(rig.client, rig.instrument.id, (fill_ts_event, _SEND_NS, _RECV_NS, "coid-1", 0))

    rig.client._match_position_lag({slug: build_position(slug)}, _RECV_NS + 5_000_000_000)

    assert rig.client._position_lag_pending == {}
    assert rig.client._position_lag_last_long == frozenset()


@pytest.mark.asyncio
async def test_r7_exactly_the_future_skew_bound_is_accepted(tmp_path: Path) -> None:
    """T5: `fill_ts_event == recv_ns + bound` is the boundary -- accepted."""
    rig = _build_rig(tmp_path)
    slug = str(rig.instrument.raw_symbol)
    fill_ts_event = _RECV_NS + _FILL_TS_EVENT_MAX_SKEW_NS
    _seed(rig.client, rig.instrument.id, (fill_ts_event, _SEND_NS, _RECV_NS, "coid-1", 0))

    rig.client._match_position_lag({slug: build_position(slug)}, fill_ts_event + 5_000_000_000)

    assert rig.client._position_lag_pending == {}
    assert rig.client._position_lag_last_long == frozenset({rig.instrument.id})


@pytest.mark.asyncio
async def test_r7_one_nanosecond_past_the_future_skew_bound_is_rejected(tmp_path: Path) -> None:
    """T5: `fill_ts_event == recv_ns + bound + 1` is rejected as
    `TS_EVENT_SKEW_FUTURE`, even though the position IS long."""
    rig = _build_rig(tmp_path)
    slug = str(rig.instrument.raw_symbol)
    fill_ts_event = _RECV_NS + _FILL_TS_EVENT_MAX_SKEW_NS + 1
    _seed(rig.client, rig.instrument.id, (fill_ts_event, _SEND_NS, _RECV_NS, "coid-1", 0))

    rig.client._match_position_lag({slug: build_position(slug)}, fill_ts_event + 5_000_000_000)

    assert rig.client._position_lag_pending == {}
    assert rig.client._position_lag_last_long == frozenset()


@pytest.mark.asyncio
async def test_r7_a_read_timestamped_at_or_before_recv_is_not_consumed(tmp_path: Path) -> None:
    """T6: a read taken at (or before) `recv_ns` is not a confirming read --
    the entry is left completely unchanged, including its `reads_without_long`."""
    rig = _build_rig(tmp_path)
    slug = str(rig.instrument.raw_symbol)
    entry = (_FILL_TS_EVENT, _SEND_NS, _RECV_NS, "coid-1", 0)
    _seed(rig.client, rig.instrument.id, entry)

    rig.client._match_position_lag({slug: build_position(slug)}, _RECV_NS)

    assert rig.client._position_lag_pending == {rig.instrument.id: entry}
    assert rig.client._position_lag_last_long == frozenset()


@pytest.mark.asyncio
async def test_r7_reads_without_long_increments_on_each_non_confirming_pass(
    tmp_path: Path,
) -> None:
    """T7: a determined-not-long pass (here, the slug absent from the page --
    a confirmed-flat read) increments `reads_without_long` and keeps the
    entry pending."""
    rig = _build_rig(tmp_path)
    _seed(rig.client, rig.instrument.id, (_FILL_TS_EVENT, _SEND_NS, _RECV_NS, "coid-1", 0))

    now_ns_1 = _RECV_NS + 1_000_000_000
    rig.client._match_position_lag({}, now_ns_1)
    assert rig.client._position_lag_pending[rig.instrument.id][4] == 1

    now_ns_2 = now_ns_1 + 1_000_000_000
    rig.client._match_position_lag({}, now_ns_2)
    assert rig.client._position_lag_pending[rig.instrument.id][4] == 2
    assert rig.client._position_lag_last_long == frozenset()


@pytest.mark.asyncio
async def test_r7_an_instrument_already_known_long_rejects_as_prior_long(
    tmp_path: Path,
) -> None:
    """T8 (PRIOR_LONG): an instrument already flagged long as of the LAST
    pass is dropped without ever reaching the position check -- a SECOND
    fill's confirmation on an already-open LONG is not attributable."""
    rig = _build_rig(tmp_path)
    slug = str(rig.instrument.raw_symbol)
    _seed(rig.client, rig.instrument.id, (_FILL_TS_EVENT, _SEND_NS, _RECV_NS, "coid-1", 0))
    rig.client._position_lag_last_long = frozenset({rig.instrument.id})

    rig.client._match_position_lag({slug: build_position(slug)}, _RECV_NS + 5_000_000_000)

    assert rig.client._position_lag_pending == {}


@pytest.mark.asyncio
async def test_r7_a_multi_fill_poisoned_entry_rejects_at_match_time(tmp_path: Path) -> None:
    """T8 (MULTI_FILL_PENDING): a poisoned entry is dropped without ever
    confirming, regardless of what the positions page shows."""
    rig = _build_rig(tmp_path)
    slug = str(rig.instrument.raw_symbol)
    _seed(
        rig.client,
        rig.instrument.id,
        (_FILL_TS_EVENT, _SEND_NS, _RECV_NS, _MULTI_FILL_PENDING_SENTINEL, 0),
    )

    rig.client._match_position_lag({slug: build_position(slug)}, _RECV_NS + 5_000_000_000)

    assert rig.client._position_lag_pending == {}
    assert rig.client._position_lag_last_long == frozenset()


@pytest.mark.asyncio
async def test_r7_an_entry_past_the_ttl_is_dropped_as_unconfirmed(tmp_path: Path) -> None:
    """T8 (UNCONFIRMED_TTL): an entry that never confirms LONG ages out and
    is dropped once the TTL floor is crossed."""
    rig = _build_rig(tmp_path)
    _seed(rig.client, rig.instrument.id, (_FILL_TS_EVENT, _SEND_NS, _RECV_NS, "coid-1", 5))

    now_ns = _RECV_NS + _POSITION_LAG_PENDING_TTL_NS + 1
    rig.client._match_position_lag({}, now_ns)

    assert rig.client._position_lag_pending == {}


@pytest.mark.asyncio
async def test_r7_a_raising_match_pass_is_contained_and_evidence_stays_correct(
    tmp_path: Path,
) -> None:
    """T10: a malformed pending entry makes `_match_position_lag` raise
    during unpacking; `_write_startup_position_evidence`'s own broad
    `except` contains it -- the evidence row it already wrote is unaffected,
    and the caller (`_connect`, standing in for the resolver's identical
    call site) completes normally rather than propagating the exception."""
    slug = "tc-temp-nyc-h-2026-09-11-70-72"
    rig = _build_rig(tmp_path, positions=_positions(slug, "3"))
    # Deliberately the wrong arity -- `_match_position_lag`'s tuple-unpack
    # raises `ValueError` before any guard/read logic runs.
    rig.client._position_lag_pending = {rig.instrument.id: (1, 2, 3)}  # type: ignore[dict-item]

    await rig.client._connect()

    evidence = rig.client.read_startup_position_evidence()
    assert evidence is not None
    assert evidence.eof_complete is True
    assert evidence.position_read_refused is False
    assert evidence.positions == (StartupPositionSnapshot(slug=slug, net_position="3"),)
    await rig.client._disconnect()
