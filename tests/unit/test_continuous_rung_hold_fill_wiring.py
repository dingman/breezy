"""Slice 4 items A1/A2/B1/E1 (plan rev 6.1): TRIAL-on-fill, the duplicate-
fill family halt, the never-arm startup walk, and the re-arm gate --
``ContinuousRungHoldStrategy`` (``continuous_strategy.py``).

Reuses the real-store harness from ``test_continuous_rung_hold_strategy.py``
(itself reusing ``test_current_rung_hold_strategy.py``'s fixtures).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import pytest
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import LiquiditySide, OrderSide
from nautilus_trader.model.events import OrderFilled
from nautilus_trader.model.identifiers import (
    AccountId,
    ClientOrderId,
    InstrumentId,
    PositionId,
    Symbol,
    TradeId,
    Venue,
    VenueOrderId,
)
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Money, Price, Quantity

from breezy.adapters.polymarket_us.exec.client import (
    FILL_INDEX_KEY_PREFIX,
    FILL_KEY_PREFIX,
    DurableFillRecord,
)
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import open_submit_intent_latch
from breezy.strategy.current_rung_hold.continuous_strategy import ContinuousRungHoldStrategy
from breezy.strategy.current_rung_hold.trial_day_latch import (
    FAMILY_HALT_KEY,
    TrialDayLatch,
    open_trial_day_latch,
)
from tests.unit.test_continuous_rung_hold_strategy import (
    _PERMISSIVE_EVIDENCE,
    _register,
    _register_and_start,
)
from tests.unit.test_current_rung_hold_strategy import (
    CLIMATE_DAY,
    INTERIOR_ID,
    NS_PER_MIN,
    STATION,
    WINDOW_OPEN_NS,
    _instrument,
    _observation,
    _quote,
)


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "state.db"


@pytest.fixture
def interior_instrument() -> BinaryOption:
    return _instrument(INTERIOR_ID, lower_f=86, upper_f=87)


def _fill(
    strategy: ContinuousRungHoldStrategy,
    *,
    instrument_id: InstrumentId,
    venue_order_id: str,
    last_qty: int = 1,
    last_px: str = "0.40",
    ts_event: int = WINDOW_OPEN_NS,
) -> OrderFilled:
    return OrderFilled(
        trader_id=strategy.trader_id,
        strategy_id=strategy.id,
        instrument_id=instrument_id,
        client_order_id=ClientOrderId(f"C-{venue_order_id}"),
        venue_order_id=VenueOrderId(venue_order_id),
        account_id=AccountId("POLYMARKET_US-001"),
        trade_id=TradeId(f"T-{venue_order_id}"),
        position_id=PositionId(f"P-{venue_order_id}"),
        order_side=OrderSide.BUY,
        order_type=strategy.order_factory.limit(
            instrument_id=instrument_id,
            order_side=OrderSide.BUY,
            quantity=Quantity.from_int(1),
            price=Price.from_str("0.40"),
        ).order_type,
        last_qty=Quantity.from_int(last_qty),
        last_px=Price.from_str(last_px),
        currency=USD,
        commission=Money(0, USD),
        liquidity_side=LiquiditySide.TAKER,
        event_id=UUID4(),
        ts_event=ts_event,
        ts_init=ts_event,
    )


# ---------------------------------------------------------------------------
# A1: TRIAL-on-fill, join, replay idempotency, unjoinable halt
# ---------------------------------------------------------------------------


def test_a_genuine_fill_consumes_the_trial_via_the_facts_join(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    strategy.on_order_filled(
        _fill(strategy, instrument_id=INTERIOR_ID, venue_order_id="ord-1"),
    )
    assert strategy._latch is not None
    record = strategy._latch.record(STATION, CLIMATE_DAY.isoformat())
    assert record is not None
    assert record.reason == "taken"
    assert record.venue_order_id == "ord-1"
    assert record.ask == Decimal("0.40")


def test_a_replayed_fill_with_the_same_venue_order_id_is_idempotent(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    event = _fill(strategy, instrument_id=INTERIOR_ID, venue_order_id="ord-1")
    strategy.on_order_filled(event)
    strategy.on_order_filled(event)  # replay: same venue_order_id
    assert strategy._latch is not None
    assert strategy._latch.is_family_halted() is False
    record = strategy._latch.record(STATION, CLIMATE_DAY.isoformat())
    assert record is not None and record.venue_order_id == "ord-1"


def test_a_second_genuine_fill_with_a_different_id_halts_the_family(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    strategy.on_order_filled(
        _fill(strategy, instrument_id=INTERIOR_ID, venue_order_id="ord-1"),
    )
    strategy.on_order_filled(
        _fill(strategy, instrument_id=INTERIOR_ID, venue_order_id="ord-2"),
    )
    assert strategy._latch is not None
    assert strategy._latch.is_family_halted() is True
    assert strategy.diagnostics.count("family_halt_duplicate_fill") == 1

    # `_hunt_tick` checks the halt FIRST -- no arm anywhere, on any station.
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + NS_PER_MIN))
    assert len(strategy.offer_tape) == 0


def test_a_corrupt_existing_trial_record_fails_closed_never_raises(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """Three-seam Slice 4 review item 1 [CRITICAL]: a corrupt latch record
    reached via `consume_if_absent`/`record` inside `on_order_filled` must
    never propagate -- `Strategy.handle_event` (installed Nautilus)
    re-raises a handler exception, which would kill the strategy right
    after a real fill."""
    from breezy.strategy.current_rung_hold.trial_day_latch import CONTINUOUS_TRIAL_KEY_PREFIX

    key = f"{CONTINUOUS_TRIAL_KEY_PREFIX}{STATION}/{CLIMATE_DAY.isoformat()}"
    store = SqliteStateStore(store_path)
    store.set(key, b"not json")
    store.close()

    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )

    strategy.on_order_filled(  # must not raise
        _fill(strategy, instrument_id=INTERIOR_ID, venue_order_id="ord-1"),
    )

    assert str(INTERIOR_ID) in strategy._unjoinable_fill_instruments
    assert strategy.position_events.count("fill_join_error") == 1
    # The process-local halt is enforced: a later hunt on this instrument
    # never reaches the offer tape.
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + NS_PER_MIN))
    assert len(strategy.offer_tape) == 0


def test_a_legacy_record_with_no_venue_order_id_never_halts_the_family(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """Three-seam Slice 4 review item 2 [HIGH]: a pre-Slice-4 record decodes
    `venue_order_id` as `None` -- that is not evidence of a duplicate."""
    from breezy.strategy.current_rung_hold.trial_day_latch import (
        CONTINUOUS_TRIAL_KEY_PREFIX,
        TrialDayRecord,
    )

    key = f"{CONTINUOUS_TRIAL_KEY_PREFIX}{STATION}/{CLIMATE_DAY.isoformat()}"
    legacy = TrialDayRecord(
        latched_at_ns=WINDOW_OPEN_NS,
        instrument_id=str(INTERIOR_ID),
        ask=Decimal("0.40"),
        reason="taken",
        # venue_order_id defaults to None -- a genuine pre-Slice-4 record.
    )
    store = SqliteStateStore(store_path)
    store.set(key, legacy.to_bytes())
    store.close()

    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )

    strategy.on_order_filled(
        _fill(strategy, instrument_id=INTERIOR_ID, venue_order_id="ord-real"),
    )

    assert strategy._latch is not None
    assert strategy._latch.is_family_halted() is False
    # The legacy record is untouched -- no overwrite, no duplicate bucket.
    record = strategy._latch.record(STATION, CLIMATE_DAY.isoformat())
    assert record == legacy


def test_decision_ask_not_fill_price_is_recorded_on_fill(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """Three-seam Slice 4 review item 3 [HIGH]: the durable TRIAL records
    the ask `_hunt_tick` actually decided against, not the fill price --
    otherwise the scorer's L-25 `fill_below_ask` guard is inert."""
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))
    assert strategy._decision_ask_by_station_day[(STATION, CLIMATE_DAY.isoformat())] == (
        Decimal("0.40")
    )

    strategy.on_order_filled(
        _fill(
            strategy, instrument_id=INTERIOR_ID, venue_order_id="ord-1",
            last_px="0.35",  # a DIFFERENT, worse fill price than the decision ask
        ),
    )

    assert strategy._latch is not None
    record = strategy._latch.record(STATION, CLIMATE_DAY.isoformat())
    assert record is not None
    assert record.ask == Decimal("0.40")  # the DECISION ask, not the fill price
    # Popped on read -- never grows unbounded.
    assert (STATION, CLIMATE_DAY.isoformat()) not in strategy._decision_ask_by_station_day


def test_fill_walk_consumed_trial_uses_the_walk_reason(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """Three-seam Slice 4 review item 3: a fill-walk-consumed trial has no
    decision ask -- it is written with the DISTINCT
    `TAKEN_FROM_FILL_WALK_REASON`, never `"taken"`, so the scorer can skip
    the ask guard by reason instead of by a vacuous equality."""
    from breezy.strategy.current_rung_hold.trial_day_latch import TAKEN_FROM_FILL_WALK_REASON

    store = SqliteStateStore(store_path)
    with open_submit_intent_latch(store, store_path):
        fill_record = DurableFillRecord(
            venue_order_id="ord-durable",
            client_order_id="C-ord-durable",
            instrument_id=str(INTERIOR_ID),
            order_side="BUY",
            cumulative_qty=Decimal(1),
            cumulative_cost=Decimal("0.40"),
            cumulative_fee=Decimal(0),
            fee_reconciled=True,
            ts_event=WINDOW_OPEN_NS,
        )
        store.set(
            f"{FILL_INDEX_KEY_PREFIX}{INTERIOR_ID}",
            json.dumps(["ord-durable"]).encode("utf-8"),
        )
        store.set(f"{FILL_KEY_PREFIX}ord-durable", fill_record.to_bytes())
    store.close()

    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    assert strategy._run_never_arm_walk() is True

    assert strategy._latch is not None
    record = strategy._latch.record(STATION, CLIMATE_DAY.isoformat())
    assert record is not None
    assert record.reason == TAKEN_FROM_FILL_WALK_REASON


def test_an_unjoinable_fill_halts_that_instrument_and_never_raises(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    foreign_id = InstrumentId(Symbol("not-a-weather-slug"), Venue("POLYMARKET_US"))
    strategy.on_order_filled(
        _fill(strategy, instrument_id=foreign_id, venue_order_id="ord-x"),
    )
    assert str(foreign_id) in strategy._unjoinable_fill_instruments
    assert strategy.position_events.count("unjoinable_fill_halt") == 1
    assert strategy._latch is not None
    assert strategy._latch.is_consumed(STATION, CLIMATE_DAY.isoformat()) is False


def test_a_nyc_fill_is_unjoinable_via_the_slug_fallback(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """NYC is never one of the four supported stations -- the slug fallback
    must refuse to join it, same as `on_start`'s primary join would."""
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    nyc_id = InstrumentId(
        Symbol("tc-temp-nychigh-2026-09-04-gte86lt87f"), Venue("POLYMARKET_US"),
    )
    strategy.on_order_filled(
        _fill(strategy, instrument_id=nyc_id, venue_order_id="ord-nyc"),
    )
    assert str(nyc_id) in strategy._unjoinable_fill_instruments


def test_slug_fallback_joins_a_fill_for_an_instrument_missing_from_facts(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """An instrument that resolved into the cache/config AFTER `on_start`
    ran (simulated: present in config, then popped from `_facts`) still
    joins via the slug -- `station in config.stations` decides scope."""
    slug_instrument = _instrument(
        InstrumentId(Symbol("tc-temp-laxhigh-2026-09-04-gte86lt87f"), Venue("POLYMARKET_US")),
        lower_f=86, upper_f=87,
    )
    strategy = _register(
        store_path=store_path,
        instruments=(interior_instrument, slug_instrument),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    strategy.start()
    slug_iid = str(slug_instrument.id)
    assert slug_iid in strategy._facts
    del strategy._facts[slug_iid]  # simulate late resolution -- not in _facts

    strategy.on_order_filled(
        _fill(strategy, instrument_id=slug_instrument.id, venue_order_id="ord-slug"),
    )
    assert strategy._latch is not None
    record = strategy._latch.record(STATION, "2026-09-04")
    assert record is not None
    assert record.venue_order_id == "ord-slug"


# ---------------------------------------------------------------------------
# A2: never-arm startup walk (`_run_never_arm_walk`, exercised directly --
# Phase 0 forbids a real permit at construction, so the gate is dormant end
# to end until a Phase 1 composition threads one through).
# ---------------------------------------------------------------------------


def test_never_arm_walk_halts_when_evidence_is_absent(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: None,
    )
    assert strategy._run_never_arm_walk() is False
    assert strategy.position_events.count("startup_evidence_missing") == 1


@pytest.mark.parametrize(
    "evidence",
    [
        {**_PERMISSIVE_EVIDENCE, "position_read_refused": True},
        {**_PERMISSIVE_EVIDENCE, "eof_complete": False},
        {**_PERMISSIVE_EVIDENCE, "fill_walk_complete": False},
    ],
)
def test_never_arm_walk_halts_on_every_incomplete_evidence_mode(
    store_path: Path, interior_instrument: BinaryOption, evidence: dict[str, object],
) -> None:
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: evidence,
    )
    assert strategy._run_never_arm_walk() is False
    assert strategy.position_events.count("startup_evidence_missing") == 1


def test_never_arm_walk_halts_when_the_family_is_already_halted(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    assert strategy._latch is not None
    strategy._latch.record_duplicate_fill(
        STATION, CLIMATE_DAY.isoformat(), venue_order_id="ord-x",
        qty=Decimal(1), fill_px=Decimal("0.4"), fee=Decimal(0), ts_ns=WINDOW_OPEN_NS,
    )
    assert strategy._run_never_arm_walk() is False
    assert strategy.position_events.count("family_halt_at_start") == 1


def test_never_arm_walk_consumes_a_durable_fill_with_no_trial(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    store = SqliteStateStore(store_path)
    with open_submit_intent_latch(store, store_path):
        fill_record = DurableFillRecord(
            venue_order_id="ord-durable",
            client_order_id="C-ord-durable",
            instrument_id=str(INTERIOR_ID),
            order_side="BUY",
            cumulative_qty=Decimal(1),
            cumulative_cost=Decimal("0.40"),
            cumulative_fee=Decimal(0),
            fee_reconciled=True,
            ts_event=WINDOW_OPEN_NS,
        )
        store.set(
            f"{FILL_INDEX_KEY_PREFIX}{INTERIOR_ID}",
            json.dumps(["ord-durable"]).encode("utf-8"),
        )
        store.set(f"{FILL_KEY_PREFIX}ord-durable", fill_record.to_bytes())
    store.close()

    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    assert strategy._run_never_arm_walk() is True
    assert strategy._latch is not None
    record = strategy._latch.record(STATION, CLIMATE_DAY.isoformat())
    assert record is not None
    assert record.venue_order_id == "ord-durable"
    assert record.ask == Decimal("0.40")


def test_never_arm_walk_halts_on_a_venue_long_with_no_durable_fill(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    evidence = {
        **_PERMISSIVE_EVIDENCE,
        "positions": [
            {"slug": str(INTERIOR_ID.symbol.value), "net_position": "1"},
        ],
    }
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: evidence,
    )
    assert strategy._run_never_arm_walk() is False
    assert strategy.position_events.count("unreconciled_long_no_fill") == 1


def test_never_arm_walk_arms_when_an_eof_complete_page_omits_the_slug(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """R-8 (2026-09-12): SUPERSEDES three-seam Slice 4 review item 5. The
    producer (`PolymarketUSExecutionClient._write_startup_position_evidence`)
    emits only slugs the venue's `eof: true` page names, so a never-traded
    market is ABSENT by construction -- item 5's PASS state was unreachable
    for any first trade. An absent slug on a fresh, eof-complete,
    non-refused, fill-walk-complete page is confirmed FLAT, not UNKNOWN."""
    evidence = {**_PERMISSIVE_EVIDENCE, "positions": [], "ts_ns": WINDOW_OPEN_NS}
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: evidence,
    )
    assert strategy._run_never_arm_walk() is True
    assert strategy.position_events.count("unreconciled_long_no_fill") == 0


def test_never_arm_walk_halts_when_net_position_is_null(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """Three-seam Slice 4 review item 5: `"net_position": null` is the
    client's own "this row was unreadable" signal -- UNKNOWN, never flat."""
    evidence = {
        **_PERMISSIVE_EVIDENCE,
        "positions": [{"slug": str(INTERIOR_ID.symbol.value), "net_position": None}],
    }
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: evidence,
    )
    assert strategy._run_never_arm_walk() is False
    assert strategy.position_events.count("unreconciled_long_no_fill") == 1


def test_rearm_permitted_when_an_eof_complete_page_omits_the_slug(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """R-8 (2026-09-12): the re-arm gate applies the SAME rule as the
    never-arm walk (site 1), through the same helper and the same
    freshness ceiling -- an absent slug on a fresh eof-complete page is
    confirmed FLAT, not UNKNOWN. Supersedes three-seam Slice 4 review
    item 5 for the re-arm gate (HB7)."""
    evidence = {**_PERMISSIVE_EVIDENCE, "positions": [], "ts_ns": WINDOW_OPEN_NS}
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: evidence,
    )
    permitted = strategy._rearm_permitted(
        STATION, CLIMATE_DAY.isoformat(), str(INTERIOR_ID),
        attempts=1, last_attempt_ns=0, now_ns=10 * 365 * 24 * 3600 * 1_000_000_000,
    )
    assert permitted is True


def test_rearm_denied_when_an_omitting_page_is_stale(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """R2-B1/AC-6 (C2, HB7-2): the same freshness bound as the never-arm
    walk, applied to the re-arm gate."""
    evidence = {
        **_PERMISSIVE_EVIDENCE,
        "positions": [],
        "ts_ns": WINDOW_OPEN_NS - 601 * 1_000_000_000,
    }
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: evidence,
    )
    permitted = strategy._rearm_permitted(
        STATION, CLIMATE_DAY.isoformat(), str(INTERIOR_ID),
        attempts=1, last_attempt_ns=0, now_ns=10 * 365 * 24 * 3600 * 1_000_000_000,
    )
    assert permitted is False


def test_rearm_denied_when_a_lagging_ts_event_would_have_extended_the_ceiling(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """R2-B1/R3-B1 (HB7-4): the freshness clause must read the WALL clock
    (`self.clock.timestamp_ns()`) INSIDE `_rearm_permitted`, never the
    venue EVENT time passed in as `now_ns` (which keeps its only existing
    use, the delay-floor comparison). A lagging `ts_event` must NOT be
    able to extend the 600s ceiling: evidence is 900s stale by wall
    clock, but only 300s stale by the (wrongly lagging) event-time
    `now_ns` -- an event-time subtraction would wrongly PERMIT; the
    wall-clock read must DENY. Signature unchanged (R3-B1): same
    six-argument shape the floor tests use."""
    from nautilus_trader.common.component import TestClock

    wall = WINDOW_OPEN_NS  # `_register(clock=...)` sets the clock to this.
    clock = TestClock()
    evidence = {
        **_PERMISSIVE_EVIDENCE,
        "positions": [],
        "ts_ns": wall - 900 * 1_000_000_000,
    }
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        clock=clock,
        position_evidence_reader=lambda: evidence,
    )
    lagging_event_time_now_ns = wall - 600 * 1_000_000_000
    permitted = strategy._rearm_permitted(
        STATION, CLIMATE_DAY.isoformat(), str(INTERIOR_ID),
        attempts=1, last_attempt_ns=0, now_ns=lagging_event_time_now_ns,
    )
    assert permitted is False


def test_on_start_with_a_permit_arms_and_subscribes_when_the_page_omits_the_slug(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """N5: drives the incident's actual entry path end to end -- `on_start`
    with a real (non-None) `order_submission_permit`, `phase0_permit_guard=
    False` (existing idiom, `test_phase0_permit_guard_false_...` below), and
    an eof-complete page that omits every candidate slug. Before R-8 this
    halted every family on its first live boot (2026-09-12 16:50:33Z, all
    four families, 294 microseconds after subscribing); after R-8 the walk
    arms and `on_start` reaches `subscribe_data` without stopping."""
    from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig

    evidence = {**_PERMISSIVE_EVIDENCE, "positions": [], "ts_ns": WINDOW_OPEN_NS}
    cfg = CurrentRungHoldConfig(instrument_ids=(interior_instrument.id,))
    strategy = ContinuousRungHoldStrategy(
        cfg,
        trial_day_latch_factory=lambda: _cont_latch_context_for(store_path),
        order_submission_permit=object(),  # type: ignore[arg-type]
        phase0_permit_guard=False,
        position_evidence_reader=lambda: evidence,
    )
    _register_bare(strategy, instruments=(interior_instrument,))
    strategy.start()
    assert strategy.is_running
    assert strategy.position_events.total() == 0


def test_never_arm_walk_halts_when_an_omitting_page_is_stale(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """R2-B1/AC-6 (C2): an eof-complete page omitting the candidate slug,
    but written more than the freshness ceiling ago, must NOT be read as
    flat -- absence only carries meaning while the record is fresh."""
    evidence = {
        **_PERMISSIVE_EVIDENCE,
        "positions": [],
        "ts_ns": WINDOW_OPEN_NS - 601 * 1_000_000_000,
    }
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: evidence,
    )
    assert strategy._run_never_arm_walk() is False
    assert strategy.position_events.count("unreconciled_long_no_fill") == 1


def test_never_arm_walk_unreadable_fill_index_halts(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    store = SqliteStateStore(store_path)
    with open_submit_intent_latch(store, store_path):
        store.set(f"{FILL_INDEX_KEY_PREFIX}{INTERIOR_ID}", b"not json")
    store.close()

    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    assert strategy._run_never_arm_walk() is False
    assert strategy.position_events.count("fill_walk_unreadable") == 1


# ---------------------------------------------------------------------------
# E1: the re-arm gate (`_rearm_permitted`), exercised directly for the same
# Phase-0-construction-guard reason as A2 above.
# ---------------------------------------------------------------------------


def test_rearm_denied_once_attempts_reach_the_cap(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    permitted = strategy._rearm_permitted(
        STATION, CLIMATE_DAY.isoformat(), str(INTERIOR_ID),
        attempts=3, last_attempt_ns=0, now_ns=10 * 365 * 24 * 3600 * 1_000_000_000,
    )
    assert permitted is False


def test_rearm_denied_before_the_delay_floor_elapses(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    permitted = strategy._rearm_permitted(
        STATION, CLIMATE_DAY.isoformat(), str(INTERIOR_ID),
        attempts=1, last_attempt_ns=WINDOW_OPEN_NS, now_ns=WINDOW_OPEN_NS + 1,
    )
    assert permitted is False


def test_rearm_denied_without_fresh_no_refusal_evidence(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: None,
    )
    permitted = strategy._rearm_permitted(
        STATION, CLIMATE_DAY.isoformat(), str(INTERIOR_ID),
        attempts=1, last_attempt_ns=0, now_ns=10 * 365 * 24 * 3600 * 1_000_000_000,
    )
    assert permitted is False


def test_rearm_denied_on_a_fresh_long(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    evidence = {
        **_PERMISSIVE_EVIDENCE,
        "positions": [{"slug": str(INTERIOR_ID.symbol.value), "net_position": "1"}],
    }
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: evidence,
    )
    permitted = strategy._rearm_permitted(
        STATION, CLIMATE_DAY.isoformat(), str(INTERIOR_ID),
        attempts=1, last_attempt_ns=0, now_ns=10 * 365 * 24 * 3600 * 1_000_000_000,
    )
    assert permitted is False


def test_rearm_permitted_once_every_gate_clears(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    permitted = strategy._rearm_permitted(
        STATION, CLIMATE_DAY.isoformat(), str(INTERIOR_ID),
        attempts=1, last_attempt_ns=0, now_ns=10 * 365 * 24 * 3600 * 1_000_000_000,
    )
    assert permitted is True


def test_a_genuine_fill_freezes_the_attempt_counter(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    assert strategy._latch is not None
    strategy._latch.record_attempt(STATION, CLIMATE_DAY.isoformat(), ts_ns=WINDOW_OPEN_NS)
    strategy.on_order_filled(
        _fill(strategy, instrument_id=INTERIOR_ID, venue_order_id="ord-fill"),
    )
    assert strategy._latch.is_consumed(STATION, CLIMATE_DAY.isoformat()) is True
    # `_hunt_tick` returns before the attempt gate is ever consulted again.
    before = strategy._latch.attempt_state(STATION, CLIMATE_DAY.isoformat())
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + NS_PER_MIN))
    assert strategy._latch.attempt_state(STATION, CLIMATE_DAY.isoformat()) == before


def test_family_halt_key_literal(store_path: Path) -> None:
    assert FAMILY_HALT_KEY == "continuous_rung_hold/halt"


# ---------------------------------------------------------------------------
# Coordinator addendum: `phase0_permit_guard` -- the Phase 1, continuous-only
# opt-in a composition root may pass to accept a real, sealed permit.
# ---------------------------------------------------------------------------


def test_phase0_permit_guard_true_still_raises_on_a_real_permit(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """RED (unchanged behaviour): the default keeps Phase 0's seal."""
    from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
    from breezy.strategy.current_rung_hold.continuous_strategy import (
        ContinuousRungHoldStrategy,
        Phase0PermitForbiddenError,
    )

    cfg = CurrentRungHoldConfig(instrument_ids=(interior_instrument.id,))
    with pytest.raises(Phase0PermitForbiddenError, match="Phase 0"):
        ContinuousRungHoldStrategy(
            cfg,
            trial_day_latch_factory=lambda: None,  # type: ignore[arg-type,return-value]
            order_submission_permit=object(),  # type: ignore[arg-type]
        )


def test_phase0_permit_guard_false_accepts_a_real_permit_and_submits_once(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """RED->GREEN: with the guard lifted, a Take-equivalent decision reaches
    `submit_order` exactly once."""
    from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
    from breezy.strategy.current_rung_hold.continuous_strategy import ContinuousRungHoldStrategy

    cfg = CurrentRungHoldConfig(instrument_ids=(interior_instrument.id,))
    strategy = ContinuousRungHoldStrategy(
        cfg,
        trial_day_latch_factory=lambda: _cont_latch_context_for(store_path),
        order_submission_permit=object(),  # type: ignore[arg-type]
        phase0_permit_guard=False,
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    assert strategy._order_submission_permit is not None
    _register_bare(strategy, instruments=(interior_instrument,))
    strategy.start()
    submitted: list[object] = []
    strategy.submit_order = submitted.append

    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))

    assert len(submitted) == 1


@contextmanager
def _cont_latch_context_for(store_path: Path) -> Iterator[TrialDayLatch]:
    from breezy.strategy.current_rung_hold.trial_day_latch import CONTINUOUS_TRIAL_KEY_PREFIX

    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
        yield open_trial_day_latch(intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)


def _register_bare(
    strategy: ContinuousRungHoldStrategy, *, instruments: tuple[BinaryOption, ...],
) -> None:
    from nautilus_trader.common.component import TestClock
    from nautilus_trader.model.identifiers import TraderId
    from nautilus_trader.portfolio import Portfolio
    from nautilus_trader.test_kit.stubs.component import TestComponentStubs

    clock = TestClock()
    clock.set_time(WINDOW_OPEN_NS)
    msgbus = TestComponentStubs.msgbus()
    cache = TestComponentStubs.cache()
    for instrument in instruments:
        cache.add_instrument(instrument)
    portfolio = Portfolio(msgbus=msgbus, cache=cache, clock=clock)
    strategy.register(
        trader_id=TraderId("BACKTEST-001"),
        portfolio=portfolio,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
    )
