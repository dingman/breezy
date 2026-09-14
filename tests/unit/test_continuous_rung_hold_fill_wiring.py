"""Slice 4 items A1/A2/B1/E1 (plan rev 6.1): TRIAL-on-fill, the duplicate-
fill family halt, the never-arm startup walk, and the re-arm gate --
``ContinuousRungHoldStrategy`` (``continuous_strategy.py``).

Reuses the real-store harness from ``test_continuous_rung_hold_strategy.py``
(itself reusing ``test_current_rung_hold_strategy.py``'s fixtures).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import pytest
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import LiquiditySide, OmsType, OrderSide
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
from nautilus_trader.model.position import Position

from breezy.adapters.polymarket_us.exec.client import (
    FILL_INDEX_KEY_PREFIX,
    FILL_KEY_PREFIX,
    DurableFillRecord,
)
from breezy.runtime.paper_replay import EXPIRATION_LEG_PREFIX
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import open_submit_intent_latch
from breezy.strategy.current_rung_hold.continuous_strategy import ContinuousRungHoldStrategy
from breezy.strategy.current_rung_hold.trial_day_latch import (
    DUPLICATE_FILL_KEY_PREFIX,
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
    OPEN_UPPER_ID,
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


@pytest.fixture
def open_upper_instrument() -> BinaryOption:
    return _instrument(OPEN_UPPER_ID, lower_f=88, upper_f=None)


def _fill(
    strategy: ContinuousRungHoldStrategy,
    *,
    instrument_id: InstrumentId,
    venue_order_id: str,
    last_qty: int = 1,
    last_px: str = "0.40",
    ts_event: int = WINDOW_OPEN_NS,
    client_order_id: str | None = None,
) -> OrderFilled:
    return OrderFilled(
        trader_id=strategy.trader_id,
        strategy_id=strategy.id,
        instrument_id=instrument_id,
        client_order_id=ClientOrderId(client_order_id or f"C-{venue_order_id}"),
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
    store_path: Path,
    interior_instrument: BinaryOption,
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
    record = strategy._latch.record(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
    )
    assert record is not None
    assert record.reason == "taken"
    assert record.venue_order_id == "ord-1"
    assert record.ask == Decimal("0.40")


def test_a_replayed_fill_with_the_same_venue_order_id_is_idempotent(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """(C-a) Also characterises `continuous_strategy.py`'s replay
    idempotence at `_consume_or_flag_duplicate`'s own equality check
    (`existing.venue_order_id == venue_order_id`): a replayed fill writes
    NO duplicate-fill bucket and sets NO family halt. This is a SYNTHETIC
    `on_order_filled` call, not an engine-driven reconciliation of a
    CLAIMED instrument, and does NOT settle ruling R2-B (Rev 2 REVISE-7);
    that engine-driven evidence is C-b, deferred with B1/B2."""
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
    record = strategy._latch.record(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
    )
    assert record is not None and record.venue_order_id == "ord-1"
    assert strategy._latch._store.get(f"{DUPLICATE_FILL_KEY_PREFIX}ord-1") is None
    assert strategy._latch._store.get(FAMILY_HALT_KEY) is None


def test_a_second_genuine_fill_with_a_different_id_halts_the_family(
    store_path: Path,
    interior_instrument: BinaryOption,
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


def test_the_engines_synthetic_expiration_leg_fill_never_trips_the_duplicate_halt(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """A genuine fill consumes the TRIAL; the `BacktestEngine`'s own
    end-of-tape settlement-close fill (`check_instrument_expiration`,
    `client_order_id` stamped `EXPIRATION-LEG-<uuid4>`) is NOT a second
    genuine fill and must never reach `_consume_or_flag_duplicate` --
    counting it would present a harness artefact as a market fact and
    family-halt every station-day on every backtest run (measured: this
    was firing on every SP-4 F replay before this fix)."""
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    strategy.on_order_filled(
        _fill(strategy, instrument_id=INTERIOR_ID, venue_order_id="ord-1"),
    )
    strategy.on_order_filled(
        _fill(
            strategy,
            instrument_id=INTERIOR_ID,
            venue_order_id="expiration-leg-order",
            client_order_id=f"{EXPIRATION_LEG_PREFIX}00000000-0000-0000-0000-000000000000",
        ),
    )
    assert strategy._latch is not None
    assert strategy._latch.is_family_halted() is False
    assert strategy.diagnostics.count("family_halt_duplicate_fill") == 0
    record = strategy._latch.record(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
    )
    assert record is not None and record.venue_order_id == "ord-1"


def test_a_second_genuine_fill_with_a_different_id_STILL_halts_after_the_expiration_leg_fix(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """Regression guard for the fix above (§5 bucket 1, never weakened): a
    SECOND fill that does NOT carry the expiration-leg prefix is still a
    genuine duplicate and must still trip the family halt."""
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


def test_a_second_fill_on_the_same_instrument_day_is_still_a_duplicate(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """RED (plan S1, operator ruling 2026-09-14): re-keying TRIAL by
    instrument-day must NOT weaken the duplicate-fill family halt for the
    SAME instrument -- a second genuine fill on the SAME instrument-day is
    still exactly one contract too many and still trips the halt."""
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


def test_a_fill_on_a_different_rung_of_the_same_station_day_is_not_a_duplicate(
    store_path: Path,
    interior_instrument: BinaryOption,
    open_upper_instrument: BinaryOption,
) -> None:
    """RED (plan S1, operator ruling 2026-09-14): "I never wanted a limit
    of 1 contract per station." A genuine fill on a DIFFERENT rung of the
    SAME station-day is a SECOND, independent trial -- never a duplicate,
    never a family halt."""
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument, open_upper_instrument),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    strategy.on_order_filled(
        _fill(strategy, instrument_id=INTERIOR_ID, venue_order_id="ord-1"),
    )
    strategy.on_order_filled(
        _fill(strategy, instrument_id=OPEN_UPPER_ID, venue_order_id="ord-2"),
    )
    assert strategy._latch is not None
    assert strategy._latch.is_family_halted() is False
    assert strategy.diagnostics.count("family_halt_duplicate_fill") == 0
    interior_record = strategy._latch.record(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID),
    )
    upper_record = strategy._latch.record(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(OPEN_UPPER_ID),
    )
    assert interior_record is not None and interior_record.venue_order_id == "ord-1"
    assert upper_record is not None and upper_record.venue_order_id == "ord-2"


def test_a_fill_clears_the_inflight_marker_for_that_instrument_day(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """RED (plan S1): live evidence 09-13 --
    `continuous_rung_hold/inflight/MIA/2026-09-13` stayed `open` after the
    fill. A genuine fill must clear IN_FLIGHT for its own instrument-day,
    ONLY after the durable trial write has already committed."""
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    assert strategy._latch is not None
    strategy._latch.set_inflight(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID),
    )
    assert (
        strategy._latch.is_inflight(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID),
        )
        is True
    )
    strategy.on_order_filled(
        _fill(strategy, instrument_id=INTERIOR_ID, venue_order_id="ord-1"),
    )
    record = strategy._latch.record(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID),
    )
    assert record is not None and record.venue_order_id == "ord-1"  # write committed
    assert (
        strategy._latch.is_inflight(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID),
        )
        is False
    )


def test_a_corrupt_existing_trial_record_fails_closed_never_raises(
    store_path: Path,
    interior_instrument: BinaryOption,
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
    store_path: Path,
    interior_instrument: BinaryOption,
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
    # `record_with_legacy_fallback` (the shim), not the literal `record`
    # lookup: this fill never wrote a NEW instrument-day key (the legacy
    # row already matched INTERIOR_ID, so `_consume_or_flag_duplicate`
    # warns and returns without writing anything).
    record = strategy._latch.record_with_legacy_fallback(
        STATION,
        CLIMATE_DAY.isoformat(),
        key_instrument_id=str(INTERIOR_ID),
    )
    assert record == legacy


def test_decision_ask_not_fill_price_is_recorded_on_fill(
    store_path: Path,
    interior_instrument: BinaryOption,
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
            strategy,
            instrument_id=INTERIOR_ID,
            venue_order_id="ord-1",
            last_px="0.35",  # a DIFFERENT, worse fill price than the decision ask
        ),
    )

    assert strategy._latch is not None
    record = strategy._latch.record(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
    )
    assert record is not None
    assert record.ask == Decimal("0.40")  # the DECISION ask, not the fill price
    # Popped on read -- never grows unbounded.
    assert (STATION, CLIMATE_DAY.isoformat()) not in strategy._decision_ask_by_station_day


def test_fill_walk_consumed_trial_uses_the_walk_reason(
    store_path: Path,
    interior_instrument: BinaryOption,
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
    record = strategy._latch.record(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
    )
    assert record is not None
    assert record.reason == TAKEN_FROM_FILL_WALK_REASON


def test_an_unjoinable_fill_halts_that_instrument_and_never_raises(
    store_path: Path,
    interior_instrument: BinaryOption,
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
    assert (
        strategy._latch.is_consumed(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
        )
        is False
    )


def test_a_nyc_fill_is_unjoinable_via_the_slug_fallback(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """NYC is never one of the four supported stations -- the slug fallback
    must refuse to join it, same as `on_start`'s primary join would."""
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    nyc_id = InstrumentId(
        Symbol("tc-temp-nychigh-2026-09-04-gte86lt87f"),
        Venue("POLYMARKET_US"),
    )
    strategy.on_order_filled(
        _fill(strategy, instrument_id=nyc_id, venue_order_id="ord-nyc"),
    )
    assert str(nyc_id) in strategy._unjoinable_fill_instruments


def test_slug_fallback_joins_a_fill_for_an_instrument_missing_from_facts(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """An instrument that resolved into the cache/config AFTER `on_start`
    ran (simulated: present in config, then popped from `_facts`) still
    joins via the slug -- `station in config.stations` decides scope."""
    slug_instrument = _instrument(
        InstrumentId(Symbol("tc-temp-laxhigh-2026-09-04-gte86lt87f"), Venue("POLYMARKET_US")),
        lower_f=86,
        upper_f=87,
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
    record = strategy._latch.record(
        STATION,
        "2026-09-04",
        key_instrument_id=str(slug_instrument.id),
    )
    assert record is not None
    assert record.venue_order_id == "ord-slug"


# ---------------------------------------------------------------------------
# A2: never-arm startup walk (`_run_never_arm_walk`, exercised directly --
# Phase 0 forbids a real permit at construction, so the gate is dormant end
# to end until a Phase 1 composition threads one through).
# ---------------------------------------------------------------------------


def test_never_arm_walk_halts_when_evidence_is_absent(
    store_path: Path,
    interior_instrument: BinaryOption,
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
    store_path: Path,
    interior_instrument: BinaryOption,
    evidence: dict[str, object],
) -> None:
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: evidence,
    )
    assert strategy._run_never_arm_walk() is False
    assert strategy.position_events.count("startup_evidence_missing") == 1


def test_never_arm_walk_halts_when_the_family_is_already_halted(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    assert strategy._latch is not None
    strategy._latch.record_duplicate_fill(
        STATION,
        CLIMATE_DAY.isoformat(),
        venue_order_id="ord-x",
        qty=Decimal(1),
        fill_px=Decimal("0.4"),
        fee=Decimal(0),
        ts_ns=WINDOW_OPEN_NS,
    )
    assert strategy._run_never_arm_walk() is False
    assert strategy.position_events.count("family_halt_at_start") == 1


def test_never_arm_walk_consumes_a_durable_fill_with_no_trial(
    store_path: Path,
    interior_instrument: BinaryOption,
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
    record = strategy._latch.record(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
    )
    assert record is not None
    assert record.venue_order_id == "ord-durable"
    assert record.ask == Decimal("0.40")


def test_the_fill_walk_consumes_per_instrument_day(
    store_path: Path,
    interior_instrument: BinaryOption,
    open_upper_instrument: BinaryOption,
) -> None:
    """RED (plan S1): the never-arm fill-record join site
    (`_consume_trial_from_fill_record`) writes the durable TRIAL under the
    fill's OWN instrument-day key -- a sibling instrument with no fill on
    the SAME station-day is completely unaffected."""
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

    evidence = {**_PERMISSIVE_EVIDENCE, "ts_ns": WINDOW_OPEN_NS}
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument, open_upper_instrument),
        position_evidence_reader=lambda: evidence,
    )
    assert strategy._run_never_arm_walk() is True
    assert strategy._latch is not None
    interior_record = strategy._latch.record(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID),
    )
    assert interior_record is not None and interior_record.venue_order_id == "ord-durable"
    assert (
        strategy._latch.is_consumed(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(OPEN_UPPER_ID),
        )
        is False
    )


def test_the_boot_walk_skips_only_the_filled_rung_not_the_whole_station_day(
    store_path: Path,
    interior_instrument: BinaryOption,
    open_upper_instrument: BinaryOption,
) -> None:
    """RED (plan S1, operator ruling 2026-09-14): a durable fill on ONE
    instrument, consumed by the fill walk, must skip only THAT instrument's
    boot-walk decision -- a sibling instrument on the SAME station-day with
    no fill still gets its OWN independent decision, never silently skipped
    as if the whole station-day were already done."""
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

    evidence = {**_PERMISSIVE_EVIDENCE, "ts_ns": WINDOW_OPEN_NS}
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument, open_upper_instrument),
        position_evidence_reader=lambda: evidence,
    )
    assert strategy._run_never_arm_walk() is True
    assert strategy.last_startup_evidence_summary is not None
    # INTERIOR_ID's fill-walk consumption skips it from the decisions loop
    # entirely (no key in `decisions`); OPEN_UPPER_ID -- absent from the
    # page, fresh, Nautilus-reconciled-flat -- is independently decided
    # "absent-flat", proving the SIBLING instrument was evaluated on its
    # own, never silently skipped alongside INTERIOR_ID.
    assert f"'{OPEN_UPPER_ID}': 'absent-flat'" in strategy.last_startup_evidence_summary
    assert f"'{INTERIOR_ID}':" not in strategy.last_startup_evidence_summary


def test_never_arm_walk_halts_on_a_venue_long_with_no_durable_fill(
    store_path: Path,
    interior_instrument: BinaryOption,
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
    store_path: Path,
    interior_instrument: BinaryOption,
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
    store_path: Path,
    interior_instrument: BinaryOption,
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
    store_path: Path,
    interior_instrument: BinaryOption,
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
        STATION,
        CLIMATE_DAY.isoformat(),
        str(INTERIOR_ID),
        attempts=1,
        last_attempt_ns=0,
        now_ns=10 * 365 * 24 * 3600 * 1_000_000_000,
    )
    assert permitted is True


def test_rearm_denied_when_an_omitting_page_is_stale(
    store_path: Path,
    interior_instrument: BinaryOption,
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
        STATION,
        CLIMATE_DAY.isoformat(),
        str(INTERIOR_ID),
        attempts=1,
        last_attempt_ns=0,
        now_ns=10 * 365 * 24 * 3600 * 1_000_000_000,
    )
    assert permitted is False


def test_rearm_denied_when_a_lagging_ts_event_would_have_extended_the_ceiling(
    store_path: Path,
    interior_instrument: BinaryOption,
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
        STATION,
        CLIMATE_DAY.isoformat(),
        str(INTERIOR_ID),
        attempts=1,
        last_attempt_ns=0,
        now_ns=lagging_event_time_now_ns,
    )
    assert permitted is False


def test_rearm_denied_when_the_reconciled_portfolio_is_long(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """Option B (HB7-3): the same Nautilus cross-check as the never-arm
    walk (T3), applied to the re-arm gate."""
    evidence = {**_PERMISSIVE_EVIDENCE, "positions": [], "ts_ns": WINDOW_OPEN_NS}
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: evidence,
    )
    fill = _fill(strategy, instrument_id=INTERIOR_ID, venue_order_id="ord-reconciled-long-2")
    position = Position(interior_instrument, fill)
    strategy.cache.add_position(position, OmsType.NETTING)
    strategy.portfolio.initialize_positions()

    permitted = strategy._rearm_permitted(
        STATION,
        CLIMATE_DAY.isoformat(),
        str(INTERIOR_ID),
        attempts=1,
        last_attempt_ns=0,
        now_ns=10 * 365 * 24 * 3600 * 1_000_000_000,
    )
    assert permitted is False


def test_on_start_with_a_permit_arms_and_subscribes_when_the_page_omits_the_slug(
    store_path: Path,
    interior_instrument: BinaryOption,
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
    store_path: Path,
    interior_instrument: BinaryOption,
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


def test_never_arm_walk_halts_when_the_reconciled_portfolio_is_long(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """Option B (T3, N-T3): a candidate slug ABSENT from a fresh, complete
    page must still halt if Nautilus's OWN reconciled portfolio shows a
    LONG on the instrument -- B is an AND on the arming side (AC-7/AC-11),
    never a substitute for the absence-confirms-flat read. Seeds a REAL
    reconciled position the same way sibling weather tests do:
    `Position(instrument, fill)` -> `cache.add_position(..., NETTING)` ->
    `portfolio.initialize_positions()` (reads `cache.positions_open()`)."""
    evidence = {**_PERMISSIVE_EVIDENCE, "positions": [], "ts_ns": WINDOW_OPEN_NS}
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: evidence,
    )
    fill = _fill(strategy, instrument_id=INTERIOR_ID, venue_order_id="ord-reconciled-long")
    position = Position(interior_instrument, fill)
    strategy.cache.add_position(position, OmsType.NETTING)
    strategy.portfolio.initialize_positions()

    assert strategy._run_never_arm_walk() is False
    assert strategy.position_events.count("unreconciled_long_no_fill") == 1


def test_a_present_zero_row_arms_even_when_the_reconciled_portfolio_is_long(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """CHARACTERISATION (P1c, HB1 pin, L-33): Option B is scoped to the
    ABSENCE branch only -- a PRESENT row at "0" arms exactly as it does
    today (byte-equivalent to `net is not None and net <= 0`), even when
    Nautilus's reconciled portfolio disagrees. No input that arms today
    newly halts (AC-9(i)). No RED at any named git state; see the HF-1
    return's MUTATION_RED_EVIDENCE (HB1's own mistake -- applying B to the
    present branch too -- makes this pin fail, then is reverted)."""
    evidence = {
        **_PERMISSIVE_EVIDENCE,
        "positions": [{"slug": str(INTERIOR_ID.symbol.value), "net_position": "0"}],
    }
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: evidence,
    )
    fill = _fill(strategy, instrument_id=INTERIOR_ID, venue_order_id="ord-present-zero-anomaly")
    position = Position(interior_instrument, fill)
    strategy.cache.add_position(position, OmsType.NETTING)
    strategy.portfolio.initialize_positions()

    assert strategy._run_never_arm_walk() is True


def test_never_arm_walk_unreadable_fill_index_halts(
    store_path: Path,
    interior_instrument: BinaryOption,
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
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    permitted = strategy._rearm_permitted(
        STATION,
        CLIMATE_DAY.isoformat(),
        str(INTERIOR_ID),
        attempts=3,
        last_attempt_ns=0,
        now_ns=10 * 365 * 24 * 3600 * 1_000_000_000,
    )
    assert permitted is False


def test_rearm_denied_before_the_delay_floor_elapses(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    permitted = strategy._rearm_permitted(
        STATION,
        CLIMATE_DAY.isoformat(),
        str(INTERIOR_ID),
        attempts=1,
        last_attempt_ns=WINDOW_OPEN_NS,
        now_ns=WINDOW_OPEN_NS + 1,
    )
    assert permitted is False


def test_rearm_denied_without_fresh_no_refusal_evidence(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: None,
    )
    permitted = strategy._rearm_permitted(
        STATION,
        CLIMATE_DAY.isoformat(),
        str(INTERIOR_ID),
        attempts=1,
        last_attempt_ns=0,
        now_ns=10 * 365 * 24 * 3600 * 1_000_000_000,
    )
    assert permitted is False


def test_rearm_denied_on_a_fresh_long(
    store_path: Path,
    interior_instrument: BinaryOption,
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
        STATION,
        CLIMATE_DAY.isoformat(),
        str(INTERIOR_ID),
        attempts=1,
        last_attempt_ns=0,
        now_ns=10 * 365 * 24 * 3600 * 1_000_000_000,
    )
    assert permitted is False


def test_rearm_permitted_once_every_gate_clears(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    permitted = strategy._rearm_permitted(
        STATION,
        CLIMATE_DAY.isoformat(),
        str(INTERIOR_ID),
        attempts=1,
        last_attempt_ns=0,
        now_ns=10 * 365 * 24 * 3600 * 1_000_000_000,
    )
    assert permitted is True


# ---------------------------------------------------------------------------
# HF-4 (post-take re-arm reachability): C3 -- a 180s re-arm evidence
# ceiling (B4 ii, site 2 only) and a symmetric Nautilus cross-check on the
# present-row branch (B5, security HIGH).
# ---------------------------------------------------------------------------


def test_rearm_denied_on_a_present_zero_row_when_the_reconciled_portfolio_is_long(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """B5 (security HIGH, HF-4 rev2), AC-10: the present-row branch at site
    2 is no longer trusted alone once HF-4 makes attempts 2-3 reachable --
    a page slug listed at "0" must ALSO clear the Nautilus cross-check,
    symmetric with the absent branch (`test_rearm_denied_when_the_
    reconciled_portfolio_is_long` above). No existing green test pins this
    case (the nine pre-HF-4 `_rearm_permitted` tests are :547, 568, 590,
    625, 770, 785, 800, 815, 834 -- :625 is the ABSENT branch); the site-1
    analogue (`test_a_present_zero_row_arms_even_when_the_reconciled_
    portfolio_is_long`, an HF-1 pin) stays green and untouched -- B5 is
    deliberately site-2 only."""
    evidence = {
        **_PERMISSIVE_EVIDENCE,
        "positions": [{"slug": str(INTERIOR_ID.symbol.value), "net_position": "0"}],
    }
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: evidence,
    )
    fill = _fill(strategy, instrument_id=INTERIOR_ID, venue_order_id="ord-present-zero-long")
    position = Position(interior_instrument, fill)
    strategy.cache.add_position(position, OmsType.NETTING)
    strategy.portfolio.initialize_positions()

    permitted = strategy._rearm_permitted(
        STATION,
        CLIMATE_DAY.isoformat(),
        str(INTERIOR_ID),
        attempts=1,
        last_attempt_ns=0,
        now_ns=10 * 365 * 24 * 3600 * 1_000_000_000,
    )
    assert permitted is False


def test_a_three_hundred_second_absent_page_denies_rearm_but_still_arms_the_boot_walk(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """B4(ii)/AC-11 (R-9a): one test proving both halves of the split
    ceiling in one shot -- an absent-slug page aged 300s is fresh under
    the boot walk's UNCHANGED 600s ceiling (site 1) but stale under the
    re-arm gate's own NEW 180s ceiling (site 2)."""
    evidence = {
        **_PERMISSIVE_EVIDENCE,
        "positions": [],
        "ts_ns": WINDOW_OPEN_NS - 300 * 1_000_000_000,
    }
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: evidence,
    )

    assert strategy._run_never_arm_walk() is True

    permitted = strategy._rearm_permitted(
        STATION,
        CLIMATE_DAY.isoformat(),
        str(INTERIOR_ID),
        attempts=1,
        last_attempt_ns=0,
        now_ns=10 * 365 * 24 * 3600 * 1_000_000_000,
    )
    assert permitted is False


def test_a_genuine_fill_freezes_the_attempt_counter(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    assert strategy._latch is not None
    strategy._latch.record_attempt(
        STATION, CLIMATE_DAY.isoformat(), ts_ns=WINDOW_OPEN_NS, key_instrument_id=str(INTERIOR_ID)
    )
    strategy.on_order_filled(
        _fill(strategy, instrument_id=INTERIOR_ID, venue_order_id="ord-fill"),
    )
    assert (
        strategy._latch.is_consumed(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
        )
        is True
    )
    # `_hunt_tick` returns before the attempt gate is ever consulted again.
    before = strategy._latch.attempt_state(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
    )
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + NS_PER_MIN))
    assert (
        strategy._latch.attempt_state(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
        )
        == before
    )


def test_startup_evidence_summary_names_completeness_age_and_each_decision() -> None:
    """AC-13/N2 (S1): the pure summary renderer names eof_complete,
    position_read_refused, fill_walk_complete, the page's slug count, the
    evidence age in seconds, and each candidate's decision. Accepts
    `evidence=None` (the evidence-missing return path, N2)."""
    from breezy.strategy.current_rung_hold.continuous_strategy import (
        _startup_evidence_summary,
    )

    evidence: dict[str, object] = {
        "v": 1,
        "ts_ns": WINDOW_OPEN_NS - 5 * 1_000_000_000,
        "eof_complete": True,
        "position_read_refused": False,
        "fill_walk_complete": True,
        "positions": [{"slug": "x", "net_position": "0"}],
    }
    summary = _startup_evidence_summary(
        evidence,
        now_ns=WINDOW_OPEN_NS,
        decisions={"a.POLYMARKET_US": "absent-flat", "b.POLYMARKET_US": "LONG"},
    )
    assert "eof_complete=True" in summary
    assert "position_read_refused=False" in summary
    assert "fill_walk_complete=True" in summary
    assert "page_slug_count=1" in summary
    assert "age_secs=5.0" in summary
    assert "absent-flat" in summary
    assert "LONG" in summary

    none_summary = _startup_evidence_summary(None, now_ns=WINDOW_OPEN_NS, decisions={})
    assert "absent" in none_summary


def _s2_family_halt(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> ContinuousRungHoldStrategy:
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    assert strategy._latch is not None
    strategy._latch.record_duplicate_fill(
        STATION,
        CLIMATE_DAY.isoformat(),
        venue_order_id="ord-s2-halt",
        qty=Decimal(1),
        fill_px=Decimal("0.4"),
        fee=Decimal(0),
        ts_ns=WINDOW_OPEN_NS,
    )
    return strategy


def _s2_evidence_missing(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> ContinuousRungHoldStrategy:
    return _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: None,
    )


def _s2_fill_walk_unreadable(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> ContinuousRungHoldStrategy:
    store = SqliteStateStore(store_path)
    with open_submit_intent_latch(store, store_path):
        store.set(f"{FILL_INDEX_KEY_PREFIX}{INTERIOR_ID}", b"not json")
    store.close()
    return _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )


def _s2_per_slug_halt(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> ContinuousRungHoldStrategy:
    evidence = {
        **_PERMISSIVE_EVIDENCE,
        "positions": [{"slug": str(INTERIOR_ID.symbol.value), "net_position": "1"}],
    }
    return _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: evidence,
    )


def _s2_success(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> ContinuousRungHoldStrategy:
    return _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )


@pytest.mark.parametrize(
    "make_strategy",
    [
        pytest.param(_s2_family_halt, id="family_halt"),
        pytest.param(_s2_evidence_missing, id="evidence_missing"),
        pytest.param(_s2_fill_walk_unreadable, id="fill_walk_unreadable"),
        pytest.param(_s2_per_slug_halt, id="per_slug_halt"),
        pytest.param(_s2_success, id="success"),
    ],
)
def test_every_never_arm_walk_exit_path_records_a_startup_evidence_summary(
    store_path: Path,
    interior_instrument: BinaryOption,
    make_strategy: Callable[[Path, BinaryOption], ContinuousRungHoldStrategy],
) -> None:
    """N2/S2 (L-27): every one of `_run_never_arm_walk`'s FIVE return paths
    sets `self.last_startup_evidence_summary` to a non-None string --
    asserted by presence, never via log capture."""
    strategy = make_strategy(store_path, interior_instrument)
    strategy._run_never_arm_walk()
    assert strategy.last_startup_evidence_summary is not None


@pytest.mark.parametrize(
    "make_strategy",
    [
        pytest.param(_s2_family_halt, id="family_halt"),
        pytest.param(_s2_evidence_missing, id="evidence_missing"),
        pytest.param(_s2_fill_walk_unreadable, id="fill_walk_unreadable"),
        pytest.param(_s2_per_slug_halt, id="per_slug_halt"),
        pytest.param(_s2_success, id="success"),
    ],
)
def test_every_never_arm_walk_exit_path_emits_the_startup_evidence_summary_at_info(
    store_path: Path,
    interior_instrument: BinaryOption,
    make_strategy: Callable[[Path, BinaryOption], ContinuousRungHoldStrategy],
) -> None:
    """C5 (code-reviewer HIGH on 8ae97be): AC-13/N2 requires the summary to
    be EMITTED at INFO on every one of the FIVE return paths, not merely
    stored -- `self.last_startup_evidence_summary` alone leaves nothing in
    `journalctl`/the node log for first-boot verification. A Breezy-owned
    seam, `_emit_startup_evidence_summary`, is overridden here to record
    calls (never Nautilus internals, never log capture, L-27). Exactly ONE
    emission per walk invocation on every path, and its content matches
    the stored summary exactly."""
    strategy = make_strategy(store_path, interior_instrument)
    emitted: list[str] = []
    strategy._emit_startup_evidence_summary = emitted.append  # type: ignore[method-assign,assignment]
    strategy._run_never_arm_walk()
    assert emitted == [strategy.last_startup_evidence_summary]


def test_family_halt_key_literal(store_path: Path) -> None:
    assert FAMILY_HALT_KEY == "continuous_rung_hold/halt"


# ---------------------------------------------------------------------------
# Coordinator addendum: `phase0_permit_guard` -- the Phase 1, continuous-only
# opt-in a composition root may pass to accept a real, sealed permit.
# ---------------------------------------------------------------------------


def test_phase0_permit_guard_true_still_raises_on_a_real_permit(
    store_path: Path,
    interior_instrument: BinaryOption,
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
    store_path: Path,
    interior_instrument: BinaryOption,
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
    strategy: ContinuousRungHoldStrategy,
    *,
    instruments: tuple[BinaryOption, ...],
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
