"""Phase 0 tests for ``ContinuousRungHoldStrategy``."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.common.component import TestClock
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import BookOrder, OrderBookDepth10
from nautilus_trader.model.enums import LiquiditySide, OmsType, OrderSide
from nautilus_trader.model.events import OrderFilled
from nautilus_trader.model.identifiers import (
    AccountId,
    ClientOrderId,
    PositionId,
    TradeId,
    TraderId,
    VenueOrderId,
)
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.model.position import Position
from nautilus_trader.portfolio import Portfolio
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.adapters.polymarket_us.exec.client import BUDGET_EXHAUSTED_KEY_PREFIX
from breezy.adapters.polymarket_us.operator_controls import utc_day_for_ns
from breezy.adapters.polymarket_us.parsing import DEPTH10_LEVELS
from breezy.domain.station_observation import StationObservation
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import CURRENT_INTENT_KEY, open_submit_intent_latch
from breezy.strategy.current_rung_hold import continuous_strategy as continuous_strategy_module
from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
from breezy.strategy.current_rung_hold.continuous_strategy import (
    ContinuousRungHoldStrategy,
    Phase0PermitForbiddenError,
)
from breezy.strategy.current_rung_hold.offer_tape import OfferTape
from breezy.strategy.current_rung_hold.shadow_rest_store import ShadowRestSummary
from breezy.strategy.current_rung_hold.trial_day_latch import (
    CONTINUOUS_TRIAL_KEY_PREFIX,
    TrialDayLatch,
    open_trial_day_latch,
)
from breezy.strategy.weather_common.refusals import RefusalAlerter
from tests.unit.test_current_rung_hold_strategy import (
    _WAIT_VOCABULARY,
    CLIMATE_DAY,
    ICAO,
    INTERIOR_ID,
    NS_PER_MIN,
    OPEN_UPPER_ID,
    STATION,
    WINDOW_OPEN_NS,
    _instrument,
    _observation,
    _quote,
    _RecordingSink,
    _SpyClock,
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


#: EDGE-3 (AM-3, class B): every continuous latch opened for a halt-reaching
#: test binds a family id -- an arbitrary but fixed non-v4 test id, since
#: none of these tests exercise v4's legacy attribution specifically.
TEST_CONT_FAMILY_ID = "pm_us_crh_test"


@contextmanager
def _open_cont_latch(
    store_path: Path, *, family_id: str = TEST_CONT_FAMILY_ID,
) -> Iterator[TrialDayLatch]:
    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
        yield open_trial_day_latch(
            intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX, family_id=family_id,
        )


def _cont_latch_factory(
    store_path: Path, *, family_id: str = TEST_CONT_FAMILY_ID,
) -> Callable[[], AbstractContextManager[TrialDayLatch]]:
    return lambda: _open_cont_latch(store_path, family_id=family_id)


def _register(
    *,
    store_path: Path,
    instruments: tuple[BinaryOption, ...],
    clock: TestClock | None = None,
    offer_tape: OfferTape | None = None,
    position_evidence_reader: Any | None = None,
    shadow_rest_summary_dir: Path | None = None,
    fee_verified_check: Callable[[int], bool] | None = None,
) -> ContinuousRungHoldStrategy:
    cfg = CurrentRungHoldConfig(
        instrument_ids=tuple(instrument.id for instrument in instruments),
        # Post-decision NO gates (admission, shadow, submit) are only
        # reachable once the calibration gate is explicit. Production
        # composition leaves it false; these tests are not that path.
        no_side_calibration_gate_cleared=True,
    )
    strategy = ContinuousRungHoldStrategy(
        cfg,
        trial_day_latch_factory=_cont_latch_factory(store_path),
        offer_tape=offer_tape,
        position_evidence_reader=position_evidence_reader,
        shadow_rest_summary_dir=shadow_rest_summary_dir,
        fee_verified_check=fee_verified_check,
    )
    used_clock = TestClock() if clock is None else clock
    used_clock.set_time(WINDOW_OPEN_NS)
    msgbus = TestComponentStubs.msgbus()
    cache = TestComponentStubs.cache()
    for instrument in instruments:
        cache.add_instrument(instrument)
    portfolio = Portfolio(msgbus=msgbus, cache=cache, clock=used_clock)
    strategy.register(
        trader_id=TraderId("BACKTEST-001"),
        portfolio=portfolio,
        msgbus=msgbus,
        cache=cache,
        clock=used_clock,
    )
    return strategy


def _register_and_start(
    *,
    store_path: Path,
    instruments: tuple[BinaryOption, ...],
    clock: TestClock | None = None,
    offer_tape: OfferTape | None = None,
    position_evidence_reader: Any | None = None,
    shadow_rest_summary_dir: Path | None = None,
    fee_verified_check: Callable[[int], bool] | None = None,
) -> ContinuousRungHoldStrategy:
    strategy = _register(
        store_path=store_path,
        instruments=instruments,
        clock=clock,
        offer_tape=offer_tape,
        position_evidence_reader=position_evidence_reader,
        shadow_rest_summary_dir=shadow_rest_summary_dir,
        fee_verified_check=fee_verified_check,
    )
    strategy.start()
    return strategy


#: A `position_evidence_reader` that always permits arming, flat on the
#: shared `INTERIOR_ID` fixture slug -- the "green" default most fill-
#: wiring/re-arm tests want, so `on_start`'s never-arm walk does not itself
#: halt the strategy. R-8 (2026-09-12, docs/core/PROGRESS.md, supersedes
#: three-seam Slice 4 review item 5): an eof-complete page ABSENT the slug
#: now arms too, for a candidate instrument, PROVIDED the record is fresh
#: (`ts_ns` within the ceiling) and Nautilus's reconciled portfolio agrees
#: (Option B). This fixture carries no `ts_ns`, so it EXPLICITLY lists
#: `INTERIOR_ID`'s own slug at "0" (present branch, freshness-independent)
#: rather than relying on the absent branch -- an empty `positions` list
#: here would halt on a missing/stale `ts_ns`, not arm.
_PERMISSIVE_EVIDENCE: dict[str, object] = {
    "v": 1,
    "eof_complete": True,
    "position_read_refused": False,
    "fill_walk_complete": True,
    "positions": [{"slug": str(INTERIOR_ID.symbol.value), "net_position": "0"}],
    # RESTING_BID_HUNT Rev 2 §4.3: the never-arm gate now also requires a
    # SUCCESSFUL open-order enumeration that came back EMPTY. Additive --
    # every prior key and value is unchanged; a fixture without these two
    # keys would (correctly) halt every boot walk, fail closed.
    "open_orders_read_refused": False,
    "open_orders": [],
}


def _pad(
    side: OrderSide,
    levels: tuple[tuple[str, int], ...],
) -> tuple[list[BookOrder], list[int]]:
    """Ten-level Depth10 side, padded with the size-0 Arrow filler (matches
    `parse_order_book_depth10`'s own padding at the instrument's precision)."""
    filler = BookOrder(side, Price(0, 2), Quantity(0, 0), 0)
    orders = [BookOrder(side, Price.from_str(px), Quantity(size, 0), 0) for px, size in levels]
    counts = [1] * len(orders)
    while len(orders) < DEPTH10_LEVELS:
        orders.append(filler)
        counts.append(0)
    return orders, counts


def _depth(
    instrument_id: object,
    *,
    bids: tuple[tuple[str, int], ...],
    asks: tuple[tuple[str, int], ...],
    ts_event: int,
) -> OrderBookDepth10:
    bid_orders, bid_counts = _pad(OrderSide.BUY, bids)
    ask_orders, ask_counts = _pad(OrderSide.SELL, asks)
    return OrderBookDepth10(
        instrument_id=instrument_id,
        bids=bid_orders,
        asks=ask_orders,
        bid_counts=bid_counts,
        ask_counts=ask_counts,
        flags=0,
        sequence=0,
        ts_event=ts_event,
        ts_init=ts_event,
    )


def test_refuse_does_not_write_trial(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    # ask=0.80: executable but p_hold_lower 0.6982 does not clear BE.
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.80", ts_event=WINDOW_OPEN_NS))
    assert strategy._latch is not None
    assert (
        strategy._latch.is_consumed(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
        )
        is False
    )
    assert strategy.refusals.count("edge_below_break_even") == 1
    assert any(rec.reason == "edge_below_break_even" for rec in strategy.offer_tape.records())


def test_illegal_cell_counted_once_visible_on_stop(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    # 87F METAR → m_code = 1 on interior [86, 87] → illegal_cell.
    strategy.on_data(_observation(temp_c_tenths=306, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))
    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + NS_PER_MIN),
    )
    assert strategy.refusals.count("illegal_cell") == 1
    assert strategy._latch is not None
    assert (
        strategy._latch.is_consumed(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
        )
        is False
    )
    message = strategy._illegal_cell_snapshot_message()
    assert message == "continuous_rung_hold illegal_cell once-count: 1"
    strategy.stop()
    assert "illegal_cell once-count: 1" in strategy._illegal_cell_snapshot_message()


def test_two_current_rungs_at_one_station_day_both_reach_a_decision(
    store_path: Path,
    interior_instrument: BinaryOption,
    open_upper_instrument: BinaryOption,
) -> None:
    """RED (plan S1, operator ruling 2026-09-14): "I never wanted a limit
    of 1 contract per station." A trial already consumed for ONE instrument
    on a station-day must never block a DIFFERENT instrument's tick on the
    SAME station-day from reaching its own decision point.
    """
    strategy = _register_and_start(
        store_path=store_path, instruments=(interior_instrument, open_upper_instrument),
    )
    assert strategy._latch is not None
    strategy._latch.consume(
        STATION,
        CLIMATE_DAY.isoformat(),
        latched_at_ns=WINDOW_OPEN_NS,
        instrument_id=str(INTERIOR_ID),
        ask=Decimal("0.40"),
        reason="taken",
        key_instrument_id=str(INTERIOR_ID),
    )
    # INTERIOR_ID's own instrument-day is consumed -- its tick is a silent
    # no-op (no diagnostic, `is_consumed` short-circuits before any is
    # recorded).
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))
    assert strategy.diagnostics.count("in_window_no_running_max_yet") == 0
    # OPEN_UPPER_ID, a DIFFERENT rung on the SAME station-day, still reaches
    # its own decision point -- this diagnostic only fires once `_hunt_tick`
    # has passed the `is_consumed` guard for OPEN_UPPER_ID's OWN
    # instrument-day key.
    strategy.on_quote_tick(_quote(OPEN_UPPER_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))
    assert strategy.diagnostics.count("in_window_no_running_max_yet") == 1


def test_inflight_commits_before_arm(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    order: list[str] = []
    assert strategy._latch is not None
    orig_set = strategy._latch.set_inflight
    orig_maybe = strategy._maybe_submit

    def spy_set(*args: object, **kwargs: object) -> None:
        order.append("inflight")
        orig_set(*args, **kwargs)
        assert strategy._latch is not None
        assert (
            strategy._latch.is_inflight(
                STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
            )
            is True
        )

    def spy_maybe(*args: object, **kwargs: object) -> None:
        order.append("maybe_submit")
        assert strategy._latch is not None
        assert (
            strategy._latch.is_inflight(
                STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
            )
            is True
        )
        return orig_maybe(*args, **kwargs)

    strategy._latch.set_inflight = spy_set  # type: ignore[method-assign]
    strategy._maybe_submit = spy_maybe  # type: ignore[method-assign]
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))
    assert order == ["inflight", "maybe_submit"]
    assert (
        strategy._latch.is_consumed(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
        )
        is False
    )


def test_on_data_skips_stale_or_future_last_tick(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    obs = _observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1)
    future = _quote(
        INTERIOR_ID,
        ask="0.40",
        ts_event=obs.received_at_ns + NS_PER_MIN,
    )
    strategy.cache.add_quote_tick(future)
    strategy.on_data(obs)
    assert len(strategy.offer_tape) == 0

    stale = _quote(
        INTERIOR_ID,
        ask="0.40",
        ts_event=obs.received_at_ns - 51 * NS_PER_MIN,
    )
    strategy.cache.add_quote_tick(stale)
    strategy.on_data(obs)
    assert len(strategy.offer_tape) == 0

    fresh = _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS)
    strategy.cache.add_quote_tick(fresh)
    later = StationObservation(
        station=ICAO,
        observed_at_ns=WINDOW_OPEN_NS - 1,
        received_at_ns=WINDOW_OPEN_NS,
        temp_c_tenths=300,
        precision_c_tenths=5,
        is_metar=True,
        source_channel="iem_asos_metar",
        assumed_publication_lag_ns=1,
    )
    strategy.on_data(later)
    # GAP fix 2026-09-15: `fresh` has no bid, so `_evaluate_no_side_shadow`
    # ALSO appends its own (side="NO") `not_executable` row -- 2 total.
    assert len(strategy.offer_tape) == 2
    yes_record = next(rec for rec in strategy.offer_tape.records() if rec.side == "YES")
    assert yes_record.trigger == "on_data"


def test_timer_calls_empty(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    clock = _SpyClock()
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        clock=clock,
    )
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))
    assert clock.timer_calls == []
    assert clock.alert_calls == []


def test_constructing_with_a_non_none_permit_raises_phase0_error(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """Phase 0 seal: `ContinuousRungHoldStrategy.__init__` refuses a
    non-None `order_submission_permit`, naming Phase 0 in the error."""
    cfg = CurrentRungHoldConfig(instrument_ids=(interior_instrument.id,))
    with pytest.raises(Phase0PermitForbiddenError, match="Phase 0"):
        ContinuousRungHoldStrategy(
            cfg,
            trial_day_latch_factory=_cont_latch_factory(store_path),
            order_submission_permit=object(),  # type: ignore[arg-type]
        )


def test_a_take_decision_with_permit_none_never_calls_submit_order(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """With `order_submission_permit=None`, a Take-equivalent decision (ask
    clears break-even) must leave `submit_order` uncalled -- asserted
    directly on the spy, never via an `... or ...` fallback that would pass
    vacuously."""
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    assert strategy._order_submission_permit is None
    submitted: list[object] = []
    strategy.submit_order = submitted.append
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    # ask=0.40 clears break-even (same fixture as test_inflight_commits_before_arm).
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))
    assert submitted == []


# ---------------------------------------------------------------------------
# EDGE-1 (r2/AM-1..4): the entry-only "fee unverified" staleness veto.
# Placed immediately after the existing `is_family_halted()`/`self._fee_halt`
# checks in `_hunt_tick`, ahead of every other entry gate -- reachable even
# on a minimal/unregistered instrument, since it fires before `iid`/`facts`
# are ever looked up.
# ---------------------------------------------------------------------------


def test_hunt_tick_refuses_a_new_entry_while_fee_unverified_and_records_the_diagnostic(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        fee_verified_check=lambda now_ns: False,
    )
    submitted: list[object] = []
    strategy.submit_order = submitted.append

    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))

    assert submitted == []
    assert strategy.diagnostics.count(continuous_strategy_module._DIAG_FEE_UNVERIFIED) == 1


def test_a_verified_check_never_refuses_an_otherwise_eligible_entry(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """A non-None check that returns `True` must be behaviourally inert --
    proves the gate is a pure veto, never a second, redundant admission
    requirement."""
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        fee_verified_check=lambda now_ns: True,
    )
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))

    assert strategy.diagnostics.count(continuous_strategy_module._DIAG_FEE_UNVERIFIED) == 0
    assert strategy.takes == 1, "a verified check must never block an otherwise-eligible take"


def test_fee_staleness_is_computed_on_the_strategy_clock_not_market_data_time(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """AM-1 (security, binding): the staleness comparison MUST use the
    strategy's own `self.clock.timestamp_ns()`, never `snapshot.ts_event` --
    market-data time can lag wall time under feed backlog, which would
    understate elapsed time and fail OPEN. Feeds a snapshot whose `ts_event`
    is stale while the strategy clock has advanced well past it, and proves
    the check received the CLOCK's time, not the snapshot's."""
    received_now_ns: list[int] = []

    def _check(now_ns: int) -> bool:
        received_now_ns.append(now_ns)
        return False

    clock = TestClock()
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        clock=clock,
        fee_verified_check=_check,
    )
    stale_ts_event = WINDOW_OPEN_NS
    advanced_now_ns = WINDOW_OPEN_NS + 999_000_000_000
    clock.set_time(advanced_now_ns)

    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=stale_ts_event))

    assert received_now_ns == [advanced_now_ns], (
        "the staleness check must be called with the strategy's own clock time, "
        "never snapshot.ts_event"
    )
    assert strategy.diagnostics.count(continuous_strategy_module._DIAG_FEE_UNVERIFIED) == 1


def test_offer_tape_records_eligible_nonfills_and_is_bounded(
    store_path: Path,
    interior_instrument: BinaryOption,
    tmp_path: Path,
) -> None:
    tape = OfferTape(tmp_path / "offer.jsonl", maxlen=3)
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        offer_tape=tape,
    )
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    for i in range(10):
        strategy.on_quote_tick(
            _quote(
                INTERIOR_ID,
                ask="0.80",
                ts_event=WINDOW_OPEN_NS + i * NS_PER_MIN,
            ),
        )
    # GAP fix 2026-09-15: every tick ALSO gets its own (side="NO")
    # `not_executable` row (no bid on this fixture) -- 2 rows/tick, so the
    # bounded deque (still exactly `maxlen`) now mixes YES/NO reasons, and
    # twice as many lines land in the JSONL sidecar.
    assert len(tape) == 3
    assert tape.maxlen == 3
    assert all(
        rec.reason in ("edge_below_break_even", "not_executable") for rec in tape.records()
    )
    assert any(
        rec.side == "YES" and rec.reason == "edge_below_break_even" for rec in tape.records()
    )
    lines = (tmp_path / "offer.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 20
    assert strategy._latch is not None
    assert (
        strategy._latch.is_consumed(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
        )
        is False
    )
    assert Decimal("0.80") == Decimal(tape.records()[-1].ask)


def test_a_take_appends_an_offer_tape_row_with_decision_inputs_populated(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """GAP fix 2026-09-15 RED: a genuine Take (same fixture as
    ``test_inflight_commits_before_arm``) must leave one offer-tape row
    behind carrying every postmortem-reconstruction field -- exactly what
    the 2026-09-15 SFO take's own row was missing.

    ADM-1 fix (2026-09-15): ``admission_reason`` is now populated for every
    YES Take row (never bare ``None`` -- that was the ADM-1 defect's own
    observability symptom: a station-day admission check that never ran
    left every YES row's ``admission_reason`` unconditionally ``None``,
    admitted or not). A lone candidate on an otherwise-empty station-day
    always admits (R3-7), so this row reads ``"admitted"``."""
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))
    # `_evaluate_no_side_shadow` ALSO appends its own (side="NO") row for
    # this tick (no bid on this frame -> NO refuses `not_executable`) --
    # filter to the YES row this test is about.
    records = [rec for rec in strategy.offer_tape.records() if rec.side == "YES"]
    assert len(records) == 1
    record = records[0]
    assert record.decision == "take"
    assert record.side == "YES"
    assert record.p_bound == Decimal("0.6982")
    assert record.break_even == Decimal("0.41")
    assert record.running_max_lower == Decimal(86)
    assert record.running_max_upper == Decimal(86)
    assert record.running_max_exact is True
    assert record.staleness_ns is not None
    assert record.fee_coefficient == Decimal("0.06")
    assert record.observed_at_ns is not None
    assert record.admission_reason == "admitted"


def test_a_break_even_refusal_appends_the_numeric_p_bound_and_be_that_produced_it(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """GAP fix 2026-09-15 RED: `edge_below_break_even` (same fixture as
    ``test_refuse_does_not_write_trial``) must leave the ACTUAL numbers that
    produced the refusal on the row, not just the reason string."""
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.80", ts_event=WINDOW_OPEN_NS))
    # Filter to the YES row -- `_evaluate_no_side_shadow` also appends its
    # own (side="NO") row for this tick.
    record = next(rec for rec in strategy.offer_tape.records() if rec.side == "YES")
    assert record.decision == "refuse"
    assert record.reason == "edge_below_break_even"
    assert record.p_bound == Decimal("0.6982")
    assert record.break_even == Decimal("0.81")
    assert not (record.p_bound > record.break_even)


def test_a_no_side_evaluation_appends_an_offer_tape_row_with_side_no(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """GAP fix 2026-09-15 RED: the NO shadow path (same admitted fixture as
    ``test_a_clearing_no_frame_logs_exactly_one_shadow_line_and_submits_
    nothing``) must ALSO leave an offer-tape row, distinct from the YES
    row for the same tick, carrying `side="NO"` and its own admission
    outcome."""
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.90", bid="0.85", ts_event=WINDOW_OPEN_NS)
    )
    no_records = [rec for rec in strategy.offer_tape.records() if rec.side == "NO"]
    assert len(no_records) == 1
    no_record = no_records[0]
    assert no_record.decision == "take"
    assert no_record.admission_reason == "admitted"
    assert no_record.p_bound is not None
    assert no_record.break_even is not None


def test_a_wait_tick_before_any_observation_appends_no_offer_tape_row(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """GAP fix 2026-09-15 RED: a tick that bails out before an evaluable
    frame exists (no running max yet -- `_DIAG_NO_RUNNING_MAX_YET`) must
    never append -- the offer tape would grow unbounded if every WAIT tick
    logged a row."""
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))
    assert strategy.offer_tape.records() == ()


def test_a_take_logs_one_info_line_mirroring_no_take_shadow(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """GAP fix 2026-09-15 RED (brief item 4): a YES take logs a `take:` INFO
    line, once per finalized take -- never once per tick."""
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    logged: list[str] = []
    strategy._emit_take_log = logged.append  # type: ignore[method-assign]
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + NS_PER_MIN))
    assert len(logged) == 1
    assert logged[0].startswith("take: ")
    assert str(INTERIOR_ID) in logged[0]
    assert "p_bound=" in logged[0]
    assert "be=" in logged[0]
    assert "R=[" in logged[0]
    assert "staleness_s=" in logged[0]
    assert "cell=(" in logged[0]


def test_an_unwritable_offer_tape_jsonl_path_never_raises_from_hunt_tick(
    store_path: Path,
    interior_instrument: BinaryOption,
    tmp_path: Path,
) -> None:
    """A disk error on `OfferTape.append`'s optional JSONL write must never
    propagate out of `on_quote_tick`/`on_data` -- the in-memory deque still
    records regardless."""
    unwritable_dir = tmp_path / "unwritable"
    unwritable_dir.mkdir(mode=0o500)
    try:
        tape = OfferTape(unwritable_dir / "offer.jsonl")
        strategy = _register_and_start(
            store_path=store_path,
            instruments=(interior_instrument,),
            offer_tape=tape,
        )
        strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
        strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.80", ts_event=WINDOW_OPEN_NS))
        # GAP fix 2026-09-15: this tick ALSO gets its own (side="NO")
        # `not_executable` row (no bid on this fixture) -- 2 total.
        assert len(tape) == 2
        assert not (unwritable_dir / "offer.jsonl").exists()
    finally:
        unwritable_dir.chmod(0o700)


# ---------------------------------------------------------------------------
# Phase 0b: hunt on Depth10 asks (shadow, permit None)
# ---------------------------------------------------------------------------


def test_on_start_subscribes_order_book_depth_for_each_resolved_instrument(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    strategy = _register(store_path=store_path, instruments=(interior_instrument,))
    subscribed: list[object] = []
    strategy.subscribe_order_book_depth = subscribed.append

    strategy.on_start()

    assert subscribed == [interior_instrument.id]


def test_on_stop_unsubscribes_order_book_depth(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    unsubscribed: list[object] = []
    strategy.unsubscribe_order_book_depth = unsubscribed.append

    strategy.stop()

    assert unsubscribed == [interior_instrument.id]


def test_on_stop_completes_and_clears_the_latch_when_the_summary_write_raises(
    store_path: Path,
    interior_instrument: BinaryOption,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Domain review of 87446c2, finding 3: `_flush_shadow_rest_summaries`
    used to catch only `OSError`, and `close_all_windows`'s own loop ran
    unguarded -- a store whose write raised e.g. `ValueError` would have
    propagated out of `on_stop`, skipping `exit_stack.close()` and leaving
    `self._latch` set. Contained now: `on_stop` always completes."""
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        shadow_rest_summary_dir=tmp_path / "shadow_rest",
    )
    strategy._shadow_rest_summaries["SFO|2026-09-16|YES"] = ShadowRestSummary(
        station="SFO", climate_day="2026-09-16", leg="YES", ticks_evaluated=1,
    )

    def _raise(*_args: object, **_kwargs: object) -> None:
        raise ValueError("store exploded")

    monkeypatch.setattr(continuous_strategy_module, "write_shadow_rest_summaries", _raise)

    strategy.stop()

    assert strategy._latch is None
    assert strategy._exit_stack is None


def test_a_second_flush_never_rewrites_the_already_flushed_summaries(
    store_path: Path,
    interior_instrument: BinaryOption,
    tmp_path: Path,
) -> None:
    """Domain review of 87446c2, finding 4: a successful flush must clear
    `_shadow_rest_summaries`, so a second `on_stop`/flush call writes
    nothing rather than re-writing a stale run."""
    summary_dir = tmp_path / "shadow_rest"
    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        shadow_rest_summary_dir=summary_dir,
    )
    strategy._shadow_rest_summaries["SFO|2026-09-16|YES"] = ShadowRestSummary(
        station="SFO", climate_day="2026-09-16", leg="YES", ticks_evaluated=1,
    )

    strategy._flush_shadow_rest_summaries()
    written = sorted(summary_dir.glob("*.parquet"))
    assert len(written) == 1
    assert strategy._shadow_rest_summaries == {}

    strategy._flush_shadow_rest_summaries()
    still_written = sorted(summary_dir.glob("*.parquet"))
    assert still_written == written


def test_a_one_sided_depth10_ask_drives_the_same_decision_as_the_equivalent_quote_tick(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """A recorded one-sided window (bids all size-0 pad, asks populated) still
    reaches the SAME hunt path a two-sided QuoteTick would, via
    `on_order_book_depth` -> `best_order(depth.asks)`."""
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    depth = _depth(INTERIOR_ID, bids=(), asks=(("0.40", 10),), ts_event=WINDOW_OPEN_NS)

    strategy.on_order_book_depth(depth)

    # Phase 0 (`order_submission_permit=None`) clears IN_FLIGHT synchronously
    # inside `_hunt_tick` itself (see `test_a_take_decision_with_permit_none_
    # never_calls_submit_order`), so the durable proof of "same decision
    # path as a QuoteTick" is the offer-tape record, not a post-hoc
    # `is_inflight` read. GAP fix 2026-09-15: this one-sided depth frame has
    # no real bid, so `_evaluate_no_side_shadow` ALSO appends its own
    # (side="NO") `not_executable` row for the same tick -- 2 total.
    assert len(strategy.offer_tape) == 2
    record = next(rec for rec in strategy.offer_tape.records() if rec.side == "YES")
    assert record.reason == "taken"
    assert record.source == "depth"
    # M1 review finding (commit 309dab6): the NO row's `ask` is `None` for a
    # no-bid frame -- there is no `1 - bid` price to report -- never the
    # empty-string sentinel the pre-fix code wrote.
    no_record = next(rec for rec in strategy.offer_tape.records() if rec.side == "NO")
    assert no_record.ask is None


def test_a_two_sided_frame_delivered_as_both_quote_and_depth_evaluates_once(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """The SAME WS frame yields a QuoteTick and a Depth10 with identical
    (instrument_id, ts_event, ask, size) -- whichever arrives second must be
    a no-op, not a second offer-tape entry. `ask=0.80` is a REFUSE decision
    (`edge_below_break_even`), which does not set inflight, so only de-dupe
    -- not the inflight guard -- can be responsible for a single record."""
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    quote = _quote(INTERIOR_ID, ask="0.80", ts_event=WINDOW_OPEN_NS)
    depth = _depth(
        INTERIOR_ID,
        bids=(("0.01", 10),),
        asks=(("0.80", 10),),
        ts_event=WINDOW_OPEN_NS,
    )

    strategy.on_quote_tick(quote)
    strategy.on_order_book_depth(depth)

    # GAP fix 2026-09-15: `_evaluate_no_side_shadow` ALSO appends its own
    # (side="NO") row for this (deduped, evaluated-once) tick -- 2 total,
    # never 4 (the de-dupe this test actually pins still holds).
    assert len(strategy.offer_tape) == 2
    yes_record = next(rec for rec in strategy.offer_tape.records() if rec.side == "YES")
    assert yes_record.reason == "edge_below_break_even"


def _order_denied(strategy: ContinuousRungHoldStrategy, *, reason: str) -> Any:
    from nautilus_trader.core.uuid import UUID4
    from nautilus_trader.model.events import OrderDenied
    from nautilus_trader.model.identifiers import ClientOrderId

    return OrderDenied(
        trader_id=strategy.trader_id,
        strategy_id=strategy.id,
        instrument_id=INTERIOR_ID,
        client_order_id=ClientOrderId("O-RACE-TEST-1"),
        reason=reason,
        event_id=UUID4(),
        ts_init=WINDOW_OPEN_NS,
    )


def test_on_order_denied_with_the_wait_reason_clears_inflight(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """SAFETY C1 (plan rev 6.1): a WAIT-class deny (the pre-arm re-check
    inside ``_submit_order``) frees the station-day to re-hunt on a later
    tick -- it is not a refusal and must not leave IN_FLIGHT stuck."""
    from breezy.adapters.polymarket_us.exec import submit_chain

    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    assert strategy._latch is not None
    strategy._latch.set_inflight(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
    )
    assert (
        strategy._latch.is_inflight(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
        )
        is True
    )

    strategy.on_order_denied(
        _order_denied(strategy, reason=submit_chain.OPEN_INTENT_WAIT_REASON),
    )

    assert (
        strategy._latch.is_inflight(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
        )
        is False
    )


def test_on_order_denied_with_any_other_reason_leaves_inflight_set(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """A standing refusal (not the WAIT sentinel) is NOT cleared here -- a
    narrower match would risk silently waving off a real refusal."""
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    assert strategy._latch is not None
    strategy._latch.set_inflight(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
    )

    strategy.on_order_denied(_order_denied(strategy, reason="some other denial reason"))

    assert (
        strategy._latch.is_inflight(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
        )
        is True
    )


def _arm_and_release_stale_intent(store_path: Path) -> None:
    """Simulate a crash-left OPEN singleton: arm it, then release the flock
    without retiring -- exactly the durable shape a crash leaves, and
    exactly what `_register_and_start`'s own factory will re-open next."""
    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as latch:
        latch.arm("a" * 64, now_ns=1)


def test_hunt_tick_waits_while_the_account_wide_intent_is_open(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """Resolution B (plan rev 6.1): a stale/crash-left OPEN singleton is seen
    by `_hunt_tick` BEFORE `set_inflight`/`_maybe_submit` -- no task hop, no
    offer-tape entry, no IN_FLIGHT ever set, counted as a WAIT diagnostic."""
    _arm_and_release_stale_intent(store_path)
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    calls: list[str] = []
    orig_maybe = strategy._maybe_submit

    def spy_maybe(*args: object, **kwargs: object) -> None:
        calls.append("maybe_submit")
        return orig_maybe(*args, **kwargs)

    strategy._maybe_submit = spy_maybe  # type: ignore[method-assign]

    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))

    assert calls == []
    assert strategy._latch is not None
    assert (
        strategy._latch.is_inflight(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
        )
        is False
    )
    assert (
        strategy._latch.is_consumed(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
        )
        is False
    )
    assert strategy.diagnostics.count("open_intent_wait") == 1
    assert len(strategy.offer_tape) == 0


def test_repeated_ticks_while_open_never_loop_and_the_alert_is_throttled(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """No hunt -> WAIT-deny -> clear -> hunt loop: with the Resolution B
    pre-filter in place, repeated ticks while the singleton stays OPEN never
    reach `_maybe_submit`/IN_FLIGHT at all, and the diagnostics alert
    renotifies on the existing `AlertState` cadence, not on every tick."""
    _arm_and_release_stale_intent(store_path)
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    calls: list[str] = []
    orig_maybe = strategy._maybe_submit

    def spy_maybe(*args: object, **kwargs: object) -> None:
        calls.append("maybe_submit")
        return orig_maybe(*args, **kwargs)

    strategy._maybe_submit = spy_maybe  # type: ignore[method-assign]
    sink = _RecordingSink()
    strategy.diagnostics_alerter = RefusalAlerter(
        strategy.diagnostics,
        site=str(strategy.id),
        sink=sink,
        **_WAIT_VOCABULARY,
    )
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))
    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + NS_PER_MIN),
    )

    assert calls == []
    assert strategy.diagnostics.count("open_intent_wait") == 2
    assert len(sink.payloads) == 1
    assert strategy._latch is not None
    assert (
        strategy._latch.is_inflight(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
        )
        is False
    )


# ---------------------------------------------------------------------------
# SP-4 increment A1 (plan rev 4): characterisation of the ARMED branch at the
# five `_order_submission_permit` read sites. No source under test changes
# in this increment -- these assertions exist to PROVE, by mutation, which
# sites a perturbation of the CURRENT source already breaks an existing test
# for and which do not. Site references are SYMBOL names, never line
# numbers (line numbers shift as the module changes -- see the
# python-reviewer M5 finding below, which caught a docstring still citing
# a stale pre-extraction line number). AM-7/NB-1: no assertion below reads
# `_order_submission_permit`/`_submission_armed()` as its own observable --
# only `submit_order` calls, `diagnostics`/`refusals` counts, and
# `latch.is_inflight`/`attempt_state`.
#
# COVERAGE_MATRIX (five ARMED-branch read sites x {invert, remove}):
#   M1  `on_start`'s never-arm-walk guard, inverted (helper -> True
#       unconditionally): 16 failures (pre-existing on_start/fill-wiring
#       tests already pin this site).
#   M2  same site, removed (helper -> False unconditionally): 2 failures.
#   M3  `_hunt_tick`'s in-flight-clear guard (the UNARMED-only clear),
#       inverted: 4 failures, including
#       `test_an_unarmed_strategy_clears_in_flight_after_maybe_submit`.
#   M4  `_maybe_submit`'s guard, removed: 16 failures (pre-existing
#       fill-wiring tests already submit through this site).
#   M5  `_hunt_tick`'s re-arm-gate guard (the one this file's
#       `test_an_armed_strategy_consults_the_rearm_gate_after_the_first_
#       attempt` exercises), removed in ISOLATION: NONE -- EQUIVALENT
#       mutant, not a coverage hole. `attempts` can only ever become
#       nonzero via the SEPARATE guard at the attempt-record site (the
#       same predicate, a different call site), so an unarmed strategy's
#       `attempt_state` cannot observably diverge whether THIS guard is
#       present or not. Previously unpinned; now pinned directly by
#       `test_an_unarmed_strategy_never_records_an_attempt_across_many_
#       eligible_depth_frames` below (python-reviewer M5, blocking).
#
# Coordinator rulings on file (all ACCEPTED, none a weakened test):
#   D4 -- `test_paper_latch_is_throwaway_not_exec_state_db` inverted to a
#         stronger AST-scoped pin (the exec-state-db module import is now
#         REQUIRED, but ONLY inside the increment-E guard function body).
#   D5 -- `exec_importing_test_modules()`'s exact-set pin widened by the
#         new increment-B test file, `==` comparison kept as-is; the
#         plan's "no firewall test changed" clause was unsatisfiable given
#         AM-1 (a genuinely new exec-importing test file).
#   E's Layer-4 marker provenance -- the unit file supplies the live-store
#         path only via `EnvironmentFile`, not inline, so the marker was
#         derived from the documented live-store-root convention instead.
#   B's one-importer AST pin, deferred from B (xfail) to C (real pass) --
#         a plan sequencing defect, not a test weakening.
# ---------------------------------------------------------------------------


def _register_armed(
    *,
    store_path: Path,
    instruments: tuple[BinaryOption, ...],
    clock: TestClock | None = None,
    position_evidence_reader: Any | None = None,
) -> ContinuousRungHoldStrategy:
    """ARMED construction (`phase0_permit_guard=False` + a real test-double
    permit), mirroring `test_continuous_rung_hold_fill_wiring.py::
    test_phase0_permit_guard_false_accepts_a_real_permit_and_submits_once`.
    A1 is characterisation-only -- this helper never touches source."""
    cfg = CurrentRungHoldConfig(
        instrument_ids=tuple(instrument.id for instrument in instruments),
        # Same as ``_register``: arm the calibration gate so submit stays
        # reachable. Production composition leaves the flag false.
        no_side_calibration_gate_cleared=True,
    )
    strategy = ContinuousRungHoldStrategy(
        cfg,
        trial_day_latch_factory=_cont_latch_factory(store_path),
        order_submission_permit=object(),  # type: ignore[arg-type]
        phase0_permit_guard=False,
        position_evidence_reader=position_evidence_reader,
    )
    used_clock = TestClock() if clock is None else clock
    used_clock.set_time(WINDOW_OPEN_NS)
    msgbus = TestComponentStubs.msgbus()
    cache = TestComponentStubs.cache()
    for instrument in instruments:
        cache.add_instrument(instrument)
    portfolio = Portfolio(msgbus=msgbus, cache=cache, clock=used_clock)
    strategy.register(
        trader_id=TraderId("BACKTEST-001"),
        portfolio=portfolio,
        msgbus=msgbus,
        cache=cache,
        clock=used_clock,
    )
    return strategy


def _register_armed_and_start(
    *,
    store_path: Path,
    instruments: tuple[BinaryOption, ...],
    clock: TestClock | None = None,
    position_evidence_reader: Any | None = None,
) -> ContinuousRungHoldStrategy:
    strategy = _register_armed(
        store_path=store_path,
        instruments=instruments,
        clock=clock,
        position_evidence_reader=position_evidence_reader,
    )
    strategy.start()
    return strategy


def test_an_armed_strategy_consults_the_rearm_gate_after_the_first_attempt(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """A1, site :579: once armed and already attempted this station-day up
    to the cap, `_hunt_tick` must consult `_rearm_permitted` and REFUSE a
    second `submit_order` -- it must never fall straight through to
    `_maybe_submit` the way the Phase-0-only (unarmed) branch does."""
    strategy = _register_armed_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    assert strategy._latch is not None
    for _ in range(3):  # _MAX_STATION_DAY_ATTEMPTS
        strategy._latch.record_attempt(
            STATION,
            CLIMATE_DAY.isoformat(),
            ts_ns=WINDOW_OPEN_NS - NS_PER_MIN,
            key_instrument_id=str(INTERIOR_ID),
        )
    submitted: list[object] = []
    strategy.submit_order = submitted.append

    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))

    assert submitted == []
    assert strategy.diagnostics.count("rearm_wait") == 1
    assert (
        strategy._latch.is_inflight(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
        )
        is False
    )
    assert (
        strategy._latch.attempt_state(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
        )[0]
        == 3
    )


def test_an_armed_strategy_records_an_attempt_and_holds_in_flight(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """A1, site :731: the FIRST armed attempt on a station-day must
    durably record it (`record_attempt`) and leave IN_FLIGHT set -- the
    armed branch never auto-clears (that is site :734's job, and only for
    the UNARMED shadow path, per the next test)."""
    strategy = _register_armed_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    assert strategy._latch is not None
    submitted: list[object] = []
    strategy.submit_order = submitted.append

    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))

    assert len(submitted) == 1
    attempts, last_attempt_ns = strategy._latch.attempt_state(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
    )
    assert attempts == 1
    assert last_attempt_ns == WINDOW_OPEN_NS
    assert (
        strategy._latch.is_inflight(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
        )
        is True
    )


def test_an_unarmed_strategy_clears_in_flight_after_maybe_submit(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """A1, site :734: the UNARMED (Phase 0) branch is SHADOW-ONLY and must
    clear IN_FLIGHT immediately after `_maybe_submit` returns -- the
    polarity trap NOTE-2 warns a blind swap here silently breaks (a
    permit-not-None guard would leave shadow-mode IN_FLIGHT stuck for
    good, since nothing else ever clears it in Phase 0)."""
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    assert strategy._order_submission_permit is None
    assert strategy._latch is not None

    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))

    assert (
        strategy._latch.is_inflight(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
        )
        is False
    )


def test_an_unarmed_strategy_never_records_an_attempt_across_many_eligible_depth_frames(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """python-reviewer M5 (blocking): `_hunt_tick`'s re-arm-gate guard --
    the `_submission_armed()` predicate consulted immediately before the
    attempt-state read, right above the attempt-record guard -- is an
    EQUIVALENT mutant when removed in isolation. `attempts` can only ever
    become nonzero via the SEPARATE guard at the attempt-record site (the
    same predicate, a different call site), so an unarmed strategy's
    `attempt_state` cannot observably diverge whether the re-arm-gate
    guard is present or not; removing ONLY that guard fails zero tests.
    This test pins the invariant the two guards jointly protect, directly
    and independent of which one is read: across many eligible depth
    frames, an unarmed (Phase 0) strategy must never durably record an
    attempt and must never leave IN_FLIGHT set.

    MUTATION_RED_EVIDENCE: temporarily removing the attempt-record site's
    OWN guard (the one true source of a nonzero `attempts`, so that
    `record_attempt` fires unconditionally) makes this test FAIL -- see
    this increment's commit body for the verbatim RED/GREEN transcript.
    """
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    assert strategy._order_submission_permit is None
    assert strategy._latch is not None
    submitted: list[object] = []
    strategy.submit_order = submitted.append
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

    for i in range(5):
        depth = _depth(
            INTERIOR_ID,
            bids=(),
            asks=(("0.40", 10),),
            ts_event=WINDOW_OPEN_NS + i * NS_PER_MIN,
        )
        strategy.on_order_book_depth(depth)

    # GAP fix 2026-09-15: no bid on any of these 5 frames, so
    # `_evaluate_no_side_shadow` ALSO appends its own (side="NO")
    # `not_executable` row per frame -- 10 total, 5 YES + 5 NO.
    yes_records = [rec for rec in strategy.offer_tape.records() if rec.side == "YES"]
    no_records = [rec for rec in strategy.offer_tape.records() if rec.side == "NO"]
    assert len(strategy.offer_tape) == 10
    assert len(yes_records) == 5
    assert all(record.reason == "taken" for record in yes_records)
    assert all(record.reason == "not_executable" for record in no_records)
    assert submitted == []  # unarmed `_maybe_submit` never calls `submit_order`
    assert strategy._latch.attempt_state(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
    ) == (0, None)
    assert (
        strategy._latch.is_inflight(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
        )
        is False
    )


# ---------------------------------------------------------------------------
# HF-4 (post-take re-arm reachability): C1 -- release a stale IN_FLIGHT
# marker once the account-wide submit intent has closed, so attempts 2/3
# become reachable (PREREG v3 SS5). `submit_order` is stubbed to a no-op in
# every test below -- the real submit-intent flock is therefore never armed
# by these tests, so `is_intent_open()` stays False throughout unless a
# test explicitly arms it via `_arm_and_release_stale_intent` (already
# defined above) or writes a corrupt singleton directly.
# ---------------------------------------------------------------------------

_S: int = 1_000_000_000  # one second, in nanoseconds


def _register_phase1_and_start(
    *,
    store_path: Path,
    instruments: tuple[BinaryOption, ...],
    clock: TestClock | None = None,
    position_evidence_reader: Any | None = None,
) -> ContinuousRungHoldStrategy:
    """Phase 1 (real, non-None permit) registration -- mirrors `_register`/
    `_register_and_start` above, plus the `phase0_permit_guard=False` +
    `order_submission_permit=object()` idiom already used by
    `test_continuous_rung_hold_fill_wiring.py`'s
    `test_phase0_permit_guard_false_accepts_a_real_permit_and_submits_once`.
    `submit_order` is replaced with a no-op: these tests exercise the
    release/re-arm GATE, never the real order-submission chain.
    """
    cfg = CurrentRungHoldConfig(
        instrument_ids=tuple(instrument.id for instrument in instruments),
        # Same as ``_register``: arm the calibration gate so a NO decision
        # can still reach this gate. Production composition leaves it false.
        no_side_calibration_gate_cleared=True,
    )
    strategy = ContinuousRungHoldStrategy(
        cfg,
        trial_day_latch_factory=_cont_latch_factory(store_path),
        order_submission_permit=object(),  # type: ignore[arg-type]
        phase0_permit_guard=False,
        position_evidence_reader=position_evidence_reader,
    )
    used_clock = TestClock() if clock is None else clock
    used_clock.set_time(WINDOW_OPEN_NS)
    msgbus = TestComponentStubs.msgbus()
    cache = TestComponentStubs.cache()
    for instrument in instruments:
        cache.add_instrument(instrument)
    portfolio = Portfolio(msgbus=msgbus, cache=cache, clock=used_clock)
    strategy.register(
        trader_id=TraderId("BACKTEST-001"),
        portfolio=portfolio,
        msgbus=msgbus,
        cache=cache,
        clock=used_clock,
    )
    strategy.start()
    strategy.submit_order = lambda order: None
    return strategy


def _arm_one_attempt(strategy: ContinuousRungHoldStrategy, *, ts_ns: int) -> None:
    assert strategy._latch is not None
    strategy._latch.set_inflight(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
    )
    strategy._latch.record_attempt(
        STATION, CLIMATE_DAY.isoformat(), ts_ns=ts_ns, key_instrument_id=str(INTERIOR_ID)
    )


def _order_filled_for_position(
    strategy: ContinuousRungHoldStrategy,
    *,
    venue_order_id: str,
) -> OrderFilled:
    """A minimal `OrderFilled` for seeding a REAL reconciled Nautilus
    position via `cache.add_position` + `portfolio.initialize_positions()`
    -- the same idiom `test_continuous_rung_hold_fill_wiring.py`'s own
    `_fill` helper uses, inlined here to avoid a cross-test-module import
    cycle (that module imports FROM this one)."""
    return OrderFilled(
        trader_id=strategy.trader_id,
        strategy_id=strategy.id,
        instrument_id=INTERIOR_ID,
        client_order_id=ClientOrderId(f"C-{venue_order_id}"),
        venue_order_id=VenueOrderId(venue_order_id),
        account_id=AccountId("POLYMARKET_US-001"),
        trade_id=TradeId(f"T-{venue_order_id}"),
        position_id=PositionId(f"P-{venue_order_id}"),
        order_side=OrderSide.BUY,
        order_type=strategy.order_factory.limit(
            instrument_id=INTERIOR_ID,
            order_side=OrderSide.BUY,
            quantity=Quantity.from_int(1),
            price=Price.from_str("0.40"),
        ).order_type,
        last_qty=Quantity.from_int(1),
        last_px=Price.from_str("0.40"),
        currency=USD,
        commission=Money(0, USD),
        liquidity_side=LiquiditySide.TAKER,
        event_id=UUID4(),
        ts_event=WINDOW_OPEN_NS,
        ts_init=WINDOW_OPEN_NS,
    )


def test_a_closed_intent_and_an_elapsed_delay_floor_release_a_stale_inflight_marker(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """AC-1: a closed intent + an elapsed 120s delay floor releases the
    stale IN_FLIGHT marker, and the SAME tick reaches `evaluate_eligible_
    snapshot` and arms attempt 2."""
    strategy = _register_phase1_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    _arm_one_attempt(strategy, ts_ns=WINDOW_OPEN_NS)
    assert strategy._latch is not None
    assert strategy._latch.is_intent_open() is False

    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + 120 * _S),
    )

    assert strategy.diagnostics.count("inflight_released") == 1
    assert (
        strategy._latch.is_inflight(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
        )
        is True
    )
    assert strategy._latch.attempt_state(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
    ) == (
        2,
        WINDOW_OPEN_NS + 120 * _S,
    )


def test_a_second_attempt_arms_after_a_resolver_terminal_zero_refreshes_evidence(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """AC-1, integration-shaped: a first re-arm-eligible tick against STALE
    evidence releases IN_FLIGHT but is denied (no attempt 2 yet); a resolver
    terminal-zero resolution's own evidence rewrite (simulated here by
    updating the reader's return value, exactly as `_write_startup_position_
    evidence` would) makes the VERY NEXT tick's read fresh, and attempt 2
    then arms -- the re-arm gate reads the CURRENT evidence, never a value
    cached from an earlier tick."""
    evidence_state: dict[str, object] = {"value": _PERMISSIVE_EVIDENCE}
    strategy = _register_phase1_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: evidence_state["value"],
    )
    # Now stale, absent-slug -- the boot walk above already ran (and
    # passed) against the fresh permissive evidence.
    evidence_state["value"] = {
        **_PERMISSIVE_EVIDENCE,
        "positions": [],
        "ts_ns": WINDOW_OPEN_NS - 10_000 * _S,
    }
    _arm_one_attempt(strategy, ts_ns=WINDOW_OPEN_NS)
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + 120 * _S),
    )
    assert strategy._latch is not None
    # Released, but denied -- stale evidence -- so attempt 2 did NOT arm.
    assert (
        strategy._latch.is_inflight(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
        )
        is False
    )
    assert strategy._latch.attempt_state(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
    ) == (1, WINDOW_OPEN_NS)

    # The resolver's own rewrite: fresh, absent-slug evidence.
    evidence_state["value"] = {
        **_PERMISSIVE_EVIDENCE,
        "positions": [],
        "ts_ns": WINDOW_OPEN_NS,
    }
    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + 121 * _S),
    )

    assert (
        strategy._latch.is_inflight(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
        )
        is True
    )
    assert strategy._latch.attempt_state(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
    ) == (
        2,
        WINDOW_OPEN_NS + 121 * _S,
    )


def test_a_third_attempt_arms_and_a_fourth_never_does(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """AC-2, AC-3: with two attempts already burned, a closed intent past
    the floor releases and arms attempt 3; the NEXT such release finds
    `attempts == 3` and the re-arm gate denies forever."""
    strategy = _register_phase1_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    assert strategy._latch is not None
    strategy._latch.record_attempt(
        STATION, CLIMATE_DAY.isoformat(), ts_ns=WINDOW_OPEN_NS, key_instrument_id=str(INTERIOR_ID)
    )
    strategy._latch.record_attempt(
        STATION, CLIMATE_DAY.isoformat(), ts_ns=WINDOW_OPEN_NS, key_instrument_id=str(INTERIOR_ID)
    )
    strategy._latch.set_inflight(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
    )
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + 120 * _S),
    )
    assert strategy._latch.attempt_state(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
    ) == (
        3,
        WINDOW_OPEN_NS + 120 * _S,
    )
    assert (
        strategy._latch.is_inflight(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
        )
        is True
    )

    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + 240 * _S),
    )
    # Attempt 4 never arms: released, then denied by the attempt cap.
    assert (
        strategy._latch.is_inflight(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
        )
        is False
    )
    assert strategy._latch.attempt_state(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
    ) == (
        3,
        WINDOW_OPEN_NS + 120 * _S,
    )


def test_a_stale_inflight_marker_is_never_released_while_the_intent_is_open(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """AC-4: a crash-left OPEN singleton (`_arm_and_release_stale_intent`,
    defined above) blocks the release regardless of how far past the delay
    floor the tick lands."""
    _arm_and_release_stale_intent(store_path)
    strategy = _register_phase1_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    assert strategy._latch is not None
    assert strategy._latch.is_intent_open() is True
    _arm_one_attempt(strategy, ts_ns=WINDOW_OPEN_NS)
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + 1_000 * _S),
    )

    assert strategy.diagnostics.count("inflight_released") == 0
    assert (
        strategy._latch.is_inflight(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
        )
        is True
    )
    assert strategy._latch.attempt_state(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
    ) == (1, WINDOW_OPEN_NS)


def test_a_corrupt_intent_singleton_leaves_the_inflight_marker_set(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """AC-5: `is_latched()` treats a corrupt singleton as `True` (fail
    closed) -- the release must never fire against one."""
    store = SqliteStateStore(store_path)
    with open_submit_intent_latch(store, store_path):
        pass
    store.set(CURRENT_INTENT_KEY, b"not json")
    store.close()

    strategy = _register_phase1_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    assert strategy._latch is not None
    assert strategy._latch.is_intent_open() is True
    _arm_one_attempt(strategy, ts_ns=WINDOW_OPEN_NS)
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + 1_000 * _S),
    )

    assert (
        strategy._latch.is_inflight(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
        )
        is True
    )
    assert strategy._latch.attempt_state(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
    ) == (1, WINDOW_OPEN_NS)


def test_a_release_inside_the_delay_floor_never_happens(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """AC-6: the same-burst race guard -- a tick inside the 120s floor
    never releases, even with the intent closed."""
    strategy = _register_phase1_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    _arm_one_attempt(strategy, ts_ns=WINDOW_OPEN_NS)
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + 1))

    assert strategy.diagnostics.count("inflight_released") == 0
    assert strategy._latch is not None
    assert (
        strategy._latch.is_inflight(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
        )
        is True
    )
    assert strategy._latch.attempt_state(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
    ) == (1, WINDOW_OPEN_NS)


def test_a_released_marker_still_cannot_arm_on_stale_absent_slug_evidence(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """AC-8: the release never bypasses `_rearm_permitted` -- evidence far
    outside EITHER the pre-HF-4 600s ceiling or HF-4's own 180s re-arm
    ceiling still denies. Re-run after C3 (still denied, a fortiori)."""
    evidence_state: dict[str, object] = {"value": _PERMISSIVE_EVIDENCE}
    strategy = _register_phase1_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: evidence_state["value"],
    )
    # Now stale, absent-slug -- the boot walk above already ran (and
    # passed) against the fresh permissive evidence.
    evidence_state["value"] = {
        **_PERMISSIVE_EVIDENCE,
        "positions": [],
        "ts_ns": WINDOW_OPEN_NS - 10_000 * _S,
    }
    _arm_one_attempt(strategy, ts_ns=WINDOW_OPEN_NS)
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + 120 * _S),
    )

    assert strategy._latch is not None
    assert (
        strategy._latch.is_inflight(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
        )
        is False
    )
    assert strategy._latch.attempt_state(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
    ) == (1, WINDOW_OPEN_NS)
    assert len(strategy.offer_tape) == 0


def test_a_released_marker_still_cannot_arm_when_nautilus_reports_a_long(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """AC-8, R9: the release never bypasses the Nautilus cross-check --
    fresh absent-slug evidence still denies when the reconciled portfolio
    shows a LONG."""
    evidence = {**_PERMISSIVE_EVIDENCE, "positions": [], "ts_ns": WINDOW_OPEN_NS}
    strategy = _register_phase1_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: evidence,
    )
    fill = _order_filled_for_position(strategy, venue_order_id="ord-hf4-long")
    position = Position(interior_instrument, fill)
    strategy.cache.add_position(position, OmsType.NETTING)
    strategy.portfolio.initialize_positions()
    _arm_one_attempt(strategy, ts_ns=WINDOW_OPEN_NS)
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + 120 * _S),
    )

    assert strategy._latch is not None
    assert (
        strategy._latch.is_inflight(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
        )
        is False
    )
    assert strategy._latch.attempt_state(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
    ) == (1, WINDOW_OPEN_NS)
    assert len(strategy.offer_tape) == 0


def test_the_release_and_the_rearm_decision_each_record_exactly_one_decision_line(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """AC-17 (B3): the release and a successful re-arm each emit exactly
    ONE `rearm:`-prefixed decision line, recorded on `last_rearm_decision`
    -- asserted on the recorded value, never via log capture (L-27)."""
    strategy = _register_phase1_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    emitted: list[str] = []
    strategy._emit_rearm_decision = emitted.append  # type: ignore[method-assign,assignment]
    _arm_one_attempt(strategy, ts_ns=WINDOW_OPEN_NS)
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + 120 * _S),
    )

    assert len(emitted) == 2
    assert "rearm:" in emitted[0] and "released" in emitted[0]
    assert "rearm:" in emitted[1] and "re-armed" in emitted[1]
    assert strategy.last_rearm_decision == emitted[-1]


def test_a_consumed_station_day_never_reaches_the_inflight_release(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """AC-7 (N3, mutation-regression authored with C1): `is_consumed` short-
    circuits `_hunt_tick` BEFORE the release path is ever consulted -- a
    genuine fill freezes the station-day regardless of any IN_FLIGHT
    residue. Mutation evidence (commit message): moving the release above
    `is_consumed` makes this RED; reverted before commit."""
    strategy = _register_phase1_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    assert strategy._latch is not None
    strategy._latch.consume(
        STATION,
        CLIMATE_DAY.isoformat(),
        latched_at_ns=WINDOW_OPEN_NS,
        instrument_id=str(INTERIOR_ID),
        ask=Decimal("0.40"),
        reason="taken",
    )
    # A residual IN_FLIGHT marker that should never be consulted.
    _arm_one_attempt(strategy, ts_ns=WINDOW_OPEN_NS)
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + 120 * _S),
    )

    assert strategy.diagnostics.count("inflight_released") == 0
    assert (
        strategy._latch.is_inflight(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
        )
        is True
    )
    assert strategy._latch.attempt_state(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
    ) == (1, WINDOW_OPEN_NS)
    assert len(strategy.offer_tape) == 0


def test_a_standing_pre_arm_refusal_burns_three_attempts_and_then_stops_forever(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """N2, AC-3: a standing pre-`arm()` refusal (the real submit-intent
    flock is never armed by these tests -- `submit_order` is stubbed) burns
    exactly three attempts, 120s apart, and then stops FOREVER -- a later
    tick keeps denying, never re-arming a fourth time."""
    strategy = _register_phase1_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    assert strategy._latch is not None
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

    for i in range(3):
        strategy.on_quote_tick(
            _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + i * 120 * _S),
        )
        assert strategy._latch.attempt_state(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
        ) == (
            i + 1,
            WINDOW_OPEN_NS + i * 120 * _S,
        )
        assert (
            strategy._latch.is_inflight(
                STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
            )
            is True
        )

    # A fourth re-arm-eligible tick: released, then denied forever by the
    # attempt cap.
    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + 3 * 120 * _S),
    )
    assert (
        strategy._latch.is_inflight(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
        )
        is False
    )
    assert strategy._latch.attempt_state(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
    ) == (
        3,
        WINDOW_OPEN_NS + 2 * 120 * _S,
    )
    # GAP fix 2026-09-15: each of the 3 loop ticks has no bid, so
    # `_evaluate_no_side_shadow` ALSO appends its own (side="NO")
    # `not_executable` row per tick -- 6 total (3 YES + 3 NO); the 4th/5th
    # denied-forever ticks never reach the offer-tape append point at all.
    assert len(strategy.offer_tape) == 6

    # And a fifth, far later: still denied, still no fourth arm.
    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + 10 * 120 * _S),
    )
    assert (
        strategy._latch.is_inflight(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
        )
        is False
    )
    assert strategy._latch.attempt_state(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
    ) == (
        3,
        WINDOW_OPEN_NS + 2 * 120 * _S,
    )
    # GAP fix 2026-09-15: each of the 3 loop ticks has no bid, so
    # `_evaluate_no_side_shadow` ALSO appends its own (side="NO")
    # `not_executable` row per tick -- 6 total (3 YES + 3 NO); the 4th/5th
    # denied-forever ticks never reach the offer-tape append point at all.
    assert len(strategy.offer_tape) == 6


# ---------------------------------------------------------------------------
# Operator ruling 2026-09-14: the daily-budget day stop
# ---------------------------------------------------------------------------


def _mark_budget_exhausted(strategy: ContinuousRungHoldStrategy, utc_day: str) -> None:
    assert strategy._latch is not None
    strategy._latch._store.set(
        f"{BUDGET_EXHAUSTED_KEY_PREFIX}{utc_day}", b"1",
    )


def test_a_marked_day_refuses_to_arm_and_leaves_inflight_and_the_attempt_counter_untouched(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """The load-bearing test: a day-budget marker for the tick's UTC day
    stops `_hunt_tick` BEFORE `is_consumed`/`attempt_state`/`is_inflight` are
    ever read -- IN_FLIGHT and the attempt counter stay exactly where they
    started, and no armed submission is attempted."""
    strategy = _register_armed_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    assert strategy._latch is not None
    utc_day = utc_day_for_ns(WINDOW_OPEN_NS).isoformat()
    _mark_budget_exhausted(strategy, utc_day)
    submitted: list[object] = []
    strategy.submit_order = submitted.append

    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))

    assert submitted == []
    assert strategy.diagnostics.count("day_budget_exhausted") == 1
    assert (
        strategy._latch.is_inflight(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
        )
        is False
    )
    assert strategy._latch.attempt_state(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
    ) == (0, None)
    assert (
        strategy._latch.is_consumed(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
        )
        is False
    )


def test_the_budget_stop_line_is_logged_once_per_station_per_day_across_many_ticks(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    assert strategy._latch is not None
    utc_day = utc_day_for_ns(WINDOW_OPEN_NS).isoformat()
    _mark_budget_exhausted(strategy, utc_day)

    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    for offset in range(5):
        strategy.on_quote_tick(
            _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + offset * NS_PER_MIN),
        )

    assert strategy.diagnostics.count("day_budget_exhausted") == 5
    assert strategy._budget_stop_notice == {(STATION, utc_day)}


def test_the_next_utc_day_arms_again_with_no_clear_step(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """The marker self-expires at UTC midnight: a tick on the NEXT UTC day
    never even consults the prior day's marker key -- no operator clear
    step exists or is needed."""
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    assert strategy._latch is not None
    utc_day = utc_day_for_ns(WINDOW_OPEN_NS).isoformat()
    _mark_budget_exhausted(strategy, utc_day)

    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))
    assert strategy.diagnostics.count("day_budget_exhausted") == 1

    _NS_PER_DAY = 86_400 * 1_000_000_000
    next_day_ts = WINDOW_OPEN_NS + _NS_PER_DAY
    next_utc_day = utc_day_for_ns(next_day_ts).isoformat()
    assert next_utc_day != utc_day
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=next_day_ts))

    # Still exactly one -- the next-day tick never re-triggers the diagnostic
    # for the (unmarked) new UTC day.
    assert strategy.diagnostics.count("day_budget_exhausted") == 1


def test_the_first_budget_denied_orders_inflight_record_is_orphaned_and_inert(
    store_path: Path,
    interior_instrument: BinaryOption,
) -> None:
    """D4 (Rev 2 dispositions): `on_order_denied` clears IN_FLIGHT only on
    the open-intent-wait reason -- a budget denial leaves the instrument-
    day's IN_FLIGHT marker set. That marker is INERT: once the day is
    marked exhausted, the day-budget read gates every later tick before
    `is_inflight` is ever consulted again, so the orphaned marker can never
    cause a stale-inflight release loop."""
    strategy = _register_armed_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    assert strategy._latch is not None
    # Simulate the orphaned state a real budget denial would leave: armed,
    # IN_FLIGHT set, no attempt recorded release -- then the day is marked.
    strategy._latch.set_inflight(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID),
    )
    strategy._latch.record_attempt(
        STATION, CLIMATE_DAY.isoformat(), ts_ns=WINDOW_OPEN_NS - NS_PER_MIN,
        key_instrument_id=str(INTERIOR_ID),
    )
    utc_day = utc_day_for_ns(WINDOW_OPEN_NS).isoformat()
    _mark_budget_exhausted(strategy, utc_day)
    submitted: list[object] = []
    strategy.submit_order = submitted.append

    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))

    assert submitted == []
    assert strategy.diagnostics.count("day_budget_exhausted") == 1
    # The orphaned marker from before the mark is untouched -- never
    # released, never re-armed, never consulted this tick.
    assert (
        strategy._latch.is_inflight(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
        )
        is True
    )
    assert strategy._latch.attempt_state(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
    )[0] == 1


def _spy(obj: object, name: str) -> list[tuple[tuple[object, ...], dict[str, object]]]:
    """Wrap ``obj``'s bound method ``name`` to record every call while still
    delegating to the original -- mirrors the inline spies used above
    (``test_hunt_tick_waits_while_the_account_wide_intent_is_open``)."""
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    orig = getattr(obj, name)

    def _wrapped(*args: object, **kwargs: object) -> object:
        calls.append((args, kwargs))
        return orig(*args, **kwargs)

    setattr(obj, name, _wrapped)
    return calls


class TestOpenIntentWaitObservability:
    """F-4 (STALL_FOLLOWUPS_F1_F4_2026-09-24.md): observability ONLY over
    the pre-existing account-wide ``open_intent_wait`` WAIT gate -- never
    changes the gate outcome, never adds a diagnostic/refusal key.
    """

    def test_open_intent_read_once_per_event_minute(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        _arm_and_release_stale_intent(store_path)
        strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
        assert strategy._latch is not None
        read_calls = _spy(strategy._latch, "current_open_submit_intent")
        strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

        strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))
        strategy.on_quote_tick(
            _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + 1_000_000_000),
        )

        assert len(read_calls) == 1
        assert strategy.diagnostics.count("open_intent_wait") == 2

    def test_open_intent_logged_once_per_intent_id_then_hourly(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        _arm_and_release_stale_intent(store_path)
        strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
        strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

        strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))
        first_line = strategy.last_open_intent_wait
        assert first_line is not None
        assert "intent_id=" in first_line

        # A later minute, well under an hour since the last log: no re-log.
        strategy.on_quote_tick(
            _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + NS_PER_MIN),
        )
        assert strategy.last_open_intent_wait == first_line

        # An hour later: re-logs, same intent_id, a fresh age.
        strategy.on_quote_tick(
            _quote(
                INTERIOR_ID,
                ask="0.40",
                ts_event=WINDOW_OPEN_NS + 3600 * 1_000_000_000 + NS_PER_MIN,
            ),
        )
        second_line = strategy.last_open_intent_wait
        assert second_line is not None
        assert second_line != first_line
        assert "intent_id=" in second_line

    def test_open_intent_log_omits_fingerprint(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        _arm_and_release_stale_intent(store_path)
        strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
        strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

        strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))

        assert strategy.last_open_intent_wait is not None
        assert "fingerprint" not in strategy.last_open_intent_wait
        assert "a" * 64 not in strategy.last_open_intent_wait

    def test_open_intent_age_from_ts_event(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        _arm_and_release_stale_intent(store_path)  # created_ns=1
        strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
        strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

        strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))

        expected_age_s = (WINDOW_OPEN_NS - 1) / 1_000_000_000
        assert strategy.last_open_intent_wait is not None
        assert f"age_s={expected_age_s}" in strategy.last_open_intent_wait

    def test_intent_read_failure_contained(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        _arm_and_release_stale_intent(store_path)
        strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
        assert strategy._latch is not None

        def _boom() -> None:
            raise RuntimeError("simulated store fault")

        strategy._latch.current_open_submit_intent = _boom  # type: ignore[method-assign]
        submitted: list[object] = []
        strategy.submit_order = submitted.append
        strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

        strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))

        assert submitted == []
        assert strategy.diagnostics.count("open_intent_wait") == 1
        assert strategy.last_open_intent_wait is None
