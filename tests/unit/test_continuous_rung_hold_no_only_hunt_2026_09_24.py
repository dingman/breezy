"""RED-first tests for F-1a (plan ``STALL_FOLLOWUPS_F1_F4_2026-09-24.md``,
Rev 3.1): the NO-only branch that runs when the YES ask is outside the
executable band (or too thin) but the NO leg (``1 - bid``) is independently
executable.

Harness: built on ``test_continuous_rung_hold_no_side_shadow_2026_09_14.py``'s
pattern (a REAL ``TrialDayLatch`` over a temp-path ``SqliteStateStore``), but
with a LOCAL ``_register``/``_register_and_start`` that accepts an explicit
``config`` -- ``tests.unit.test_continuous_rung_hold_strategy``'s own
``_register_and_start`` hard-pins ``no_side_calibration_gate_cleared=True``
and is on the "must stay green, unedited" list, so it cannot grow a
``config`` override here.

Shared fixture facts (``tests.unit.test_current_rung_hold_strategy``):
``STATION="LAX"``, ``CLIMATE_DAY=2026-09-04`` -> ``season_for == "SON"``,
``WINDOW_OPEN_NS`` local hour 12. ``INTERIOR_ID`` is ``[86, 87]``
(``width_code=0``). A ``temp_c_tenths=300`` observation resolves
``m_code=0`` -> key ``("LAX", "SON", 12, 0, 0)``, whose
``P_HOLD_LOWER=0.6982`` / ``P_HOLD_UPPER=0.7789``. ``bid="0.85"`` ->
``NO_ask=1-0.85=0.15``, fee ``round(0.06*0.15*0.85, 2)=0.01`` -> break-even
``0.16``; ``p_miss_lower=1-0.7789=0.2211 > 0.16`` clears the NO break-even
once the calibration gate is explicitly cleared.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.common.component import TestClock
from nautilus_trader.model.data import BookOrder, OrderBookDepth10
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId, TraderId
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.portfolio import Portfolio
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.adapters.polymarket_us.exec.client import BUDGET_EXHAUSTED_KEY_PREFIX
from breezy.adapters.polymarket_us.exec.no_side_keys import is_no_side_pending
from breezy.adapters.polymarket_us.operator_controls import utc_day_for_ns
from breezy.adapters.polymarket_us.symbology import sibling_instrument_id
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import open_submit_intent_latch
from breezy.strategy.current_rung_hold import continuous_strategy as continuous_strategy_module
from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
from breezy.strategy.current_rung_hold.continuous_strategy import (
    _DIAG_DAY_BUDGET_EXHAUSTED,
    _DIAG_FAMILY_HALT,
    _DIAG_NO_ONLY_HUNT_ERROR,
    _DIAG_OPEN_INTENT_WAIT,
    _DIAG_REARM_WAIT,
    _OUTSIDE_DECISION_WINDOW,
    ContinuousRungHoldStrategy,
)
from breezy.strategy.current_rung_hold.decision import REFUSAL_REASONS, Decision, Refuse
from breezy.strategy.current_rung_hold.trial_day_latch import (
    CONTINUOUS_TRIAL_KEY_PREFIX,
    TrialDayLatch,
    TrialDayRecord,
    TrialDayRecordCorrupt,
    open_trial_day_latch,
)
from tests.unit.test_continuous_rung_hold_strategy import (
    _PERMISSIVE_EVIDENCE,
    _register_phase1_and_start,
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

_NS_PER_HOUR = 3_600_000_000_000
_DEPTH10_LEVELS = 10


def _pad_depth_side(
    side: OrderSide, levels: tuple[tuple[str, int], ...],
) -> list[BookOrder]:
    """Ten-level Depth10 side, padded with the size-0 Arrow filler -- mirrors
    ``test_continuous_rung_hold_strategy.py``'s own ``_pad`` verbatim."""
    filler = BookOrder(side, Price(0, 2), Quantity(0, 0), 0)
    orders = [BookOrder(side, Price.from_str(px), Quantity(size, 0), 0) for px, size in levels]
    while len(orders) < _DEPTH10_LEVELS:
        orders.append(filler)
    return orders


def _depth(
    instrument_id: InstrumentId,
    *,
    bids: tuple[tuple[str, int], ...] = (),
    asks: tuple[tuple[str, int], ...] = (),
    ts_event: int,
) -> OrderBookDepth10:
    bid_orders = _pad_depth_side(OrderSide.BUY, bids)
    ask_orders = _pad_depth_side(OrderSide.SELL, asks)
    return OrderBookDepth10(
        instrument_id=instrument_id,
        bids=bid_orders,
        asks=ask_orders,
        bid_counts=[1 if o.size.as_double() > 0 else 0 for o in bid_orders],
        ask_counts=[1 if o.size.as_double() > 0 else 0 for o in ask_orders],
        flags=0,
        sequence=0,
        ts_event=ts_event,
        ts_init=ts_event,
    )


def _bid_only_depth(
    *, bid: str, bid_size: int = 10, ts_event: int,
) -> OrderBookDepth10:
    return _depth(INTERIOR_ID, bids=((bid, bid_size),), asks=(), ts_event=ts_event)

_NO_INTERIOR_ID = sibling_instrument_id(INTERIOR_ID)
_BAND_CLEARING_BID = "0.85"


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "state.db"


@pytest.fixture
def interior_instrument() -> BinaryOption:
    return _instrument(INTERIOR_ID, lower_f=86, upper_f=87)


@contextmanager
def _open_cont_latch(store_path: Path) -> Iterator[TrialDayLatch]:
    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
        yield open_trial_day_latch(intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)


def _cont_latch_factory(
    store_path: Path,
) -> Callable[[], AbstractContextManager[TrialDayLatch]]:
    return lambda: _open_cont_latch(store_path)


def _register(
    *,
    store_path: Path,
    instruments: tuple[BinaryOption, ...],
    config: CurrentRungHoldConfig | None = None,
    clock: TestClock | None = None,
) -> ContinuousRungHoldStrategy:
    """Mirrors ``test_continuous_rung_hold_strategy._register`` exactly,
    except ``config`` defaults to the PRODUCTION default (calibration gate
    CLOSED), never the shared harness's hard-pinned cleared gate -- F-1a's
    own acceptance criteria need both states.
    """
    cfg = config or CurrentRungHoldConfig(
        instrument_ids=tuple(instrument.id for instrument in instruments),
    )
    strategy = ContinuousRungHoldStrategy(
        cfg, trial_day_latch_factory=_cont_latch_factory(store_path),
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
    config: CurrentRungHoldConfig | None = None,
    clock: TestClock | None = None,
) -> ContinuousRungHoldStrategy:
    strategy = _register(
        store_path=store_path, instruments=instruments, config=config, clock=clock,
    )
    strategy.start()
    return strategy


def _gate_cleared_config(*, instruments: tuple[BinaryOption, ...]) -> CurrentRungHoldConfig:
    return CurrentRungHoldConfig(
        instrument_ids=tuple(instrument.id for instrument in instruments),
        no_side_calibration_gate_cleared=True,
    )


def _spy_no_side_shadow(
    strategy: ContinuousRungHoldStrategy,
) -> list[dict[str, Any]]:
    """Records every call to ``_evaluate_no_side_shadow`` (args as kwargs),
    then delegates to the real method -- never changes behaviour."""
    calls: list[dict[str, Any]] = []
    original = strategy._evaluate_no_side_shadow

    def _spy(**kwargs: Any) -> None:
        calls.append(kwargs)
        original(**kwargs)

    strategy._evaluate_no_side_shadow = _spy  # type: ignore[method-assign]
    return calls


# ---------------------------------------------------------------------------
# AC1 / AC2: the core NO-only branch.
# ---------------------------------------------------------------------------


def test_yes_out_of_band_with_executable_no_leg_evaluates_no_side(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    calls = _spy_no_side_shadow(strategy)

    diag_before = dict(strategy.diagnostics.counts)
    refusals_before = dict(strategy.refusals.counts)
    snap_before = dict(strategy._eligible_snap_counts)

    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.97", bid=_BAND_CLEARING_BID, ts_event=WINDOW_OPEN_NS)
    )

    assert len(calls) == 1
    assert diag_before.get("in_window_not_executable", 0) + 1 == strategy.diagnostics.count(
        "in_window_not_executable"
    )
    expected_not_executable = diag_before.get("in_window_not_executable", 0) + 1
    assert strategy.diagnostics.counts == {
        **diag_before, "in_window_not_executable": expected_not_executable,
    }
    assert strategy.refusals.counts == refusals_before
    assert strategy._eligible_snap_counts == snap_before
    assert not any(rec.side == "YES" for rec in strategy.offer_tape.records())


def test_yes_thin_ask_in_band_with_executable_no_leg_evaluates_no_side(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """A2: the YES price is in band but ``size < minimum_displayed_size``."""
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    calls = _spy_no_side_shadow(strategy)

    strategy.on_quote_tick(
        _quote(
            INTERIOR_ID, ask="0.50", size=0, bid=_BAND_CLEARING_BID, bid_size=10,
            ts_event=WINDOW_OPEN_NS,
        )
    )

    assert len(calls) == 1
    assert strategy.diagnostics.count("in_window_not_executable") == 1


# ---------------------------------------------------------------------------
# The 3x5 sweep (A2): NO is evaluated exactly when the NO leg's own band
# passes AND the book is not crossed; diagnostics delta always equals
# baseline regardless.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ask", ["0.02", "0.96", "0.99"])
@pytest.mark.parametrize("bid", ["0.04", "0.06", "0.50", "0.94", "0.96"])
def test_no_only_sweep(
    store_path: Path, interior_instrument: BinaryOption, ask: str, bid: str,
) -> None:
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    calls: list[Decision] = []
    original = strategy._evaluate_no_side_shadow

    def _spy(*, no_decision: Decision, **kwargs: Any) -> None:
        calls.append(no_decision)
        original(no_decision=no_decision, **kwargs)

    strategy._evaluate_no_side_shadow = _spy  # type: ignore[method-assign]

    diag_before = dict(strategy.diagnostics.counts)
    refusals_before = dict(strategy.refusals.counts)

    strategy.on_quote_tick(_quote(INTERIOR_ID, ask=ask, bid=bid, ts_event=WINDOW_OPEN_NS))

    ask_d, bid_d = Decimal(ask), Decimal(bid)
    no_ask = Decimal(1) - bid_d
    band_ok = Decimal("0.05") < no_ask < Decimal("0.95")
    genuinely_evaluated = band_ok and bid_d < ask_d

    if not band_ok:
        assert calls == []
    else:
        assert len(calls) == 1
        decision = calls[0]
        assert isinstance(decision, Refuse)
        if genuinely_evaluated:
            assert decision.reason == "no_side_calibration_unsafe"
        else:
            assert decision.reason == "not_executable"

    expected_not_executable = diag_before.get("in_window_not_executable", 0) + 1
    assert strategy.diagnostics.counts == {
        **diag_before, "in_window_not_executable": expected_not_executable,
    }
    assert strategy.refusals.counts == refusals_before


# ---------------------------------------------------------------------------
# AC3: both legs out of band -- byte-identical, no tape row at all.
# ---------------------------------------------------------------------------


def test_both_legs_out_of_band_writes_no_tape_row(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    calls = _spy_no_side_shadow(strategy)

    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.97", bid="0.04", ts_event=WINDOW_OPEN_NS))

    assert calls == []
    assert strategy.offer_tape.records() == ()
    assert strategy.diagnostics.count("in_window_not_executable") == 1


# ---------------------------------------------------------------------------
# AC4: gate closed -- appends one refuse row, never arms/submits/writes the
# first-order key.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bid", ["0.06", "0.30", "0.50", "0.70", "0.94"])
def test_no_only_gate_closed_never_submits_sets_inflight_or_writes_first_order_key(
    store_path: Path, interior_instrument: BinaryOption, bid: str,
) -> None:
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    submitted: list[object] = []
    strategy.submit_order = submitted.append  # type: ignore[method-assign]

    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.97", bid=bid, ts_event=WINDOW_OPEN_NS))

    assert submitted == []
    assert strategy._latch is not None
    assert (
        strategy._latch.is_inflight(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(_NO_INTERIOR_ID)
        )
        is False
    )
    assert is_no_side_pending(strategy._latch._store) is False
    rows = [rec for rec in strategy.offer_tape.records() if rec.side == "NO"]
    assert len(rows) == 1
    assert rows[0].reason == "no_side_calibration_unsafe"


# ---------------------------------------------------------------------------
# AC5: gate cleared, test config only -- reaches the arm tail. Proves the
# tail is reachable; it enables nothing (Phase 0 holds no real permit, so
# `_maybe_submit` never actually submits and inflight self-clears).
# ---------------------------------------------------------------------------


def test_no_only_gate_cleared_reaches_no_arm_tail(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    config = _gate_cleared_config(instruments=(interior_instrument,))
    strategy = _register_and_start(
        store_path=store_path, instruments=(interior_instrument,), config=config,
    )
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    assert strategy._latch is not None
    attempts_before, _ = strategy._latch.attempt_state(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(_NO_INTERIOR_ID)
    )

    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.97", bid=_BAND_CLEARING_BID, ts_event=WINDOW_OPEN_NS)
    )

    attempts_after, _ = strategy._latch.attempt_state(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(_NO_INTERIOR_ID)
    )
    assert attempts_after == attempts_before + 1
    assert is_no_side_pending(strategy._latch._store) is True


# ---------------------------------------------------------------------------
# AC1 quiet upstream gates.
# ---------------------------------------------------------------------------


def test_no_only_rung_not_current_is_quiet(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=0, observed_at_ns=WINDOW_OPEN_NS - 1))
    calls = _spy_no_side_shadow(strategy)

    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.97", bid=_BAND_CLEARING_BID, ts_event=WINDOW_OPEN_NS)
    )

    assert calls == []
    assert strategy.offer_tape.records() == ()


def test_no_only_no_running_max_is_quiet(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    calls = _spy_no_side_shadow(strategy)

    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.97", bid=_BAND_CLEARING_BID, ts_event=WINDOW_OPEN_NS)
    )

    assert calls == []
    assert strategy.offer_tape.records() == ()


# ---------------------------------------------------------------------------
# AC6: a crossed book on a NO-only tick is refused not_executable.
# ---------------------------------------------------------------------------


def test_no_only_crossed_book_refuses_not_executable(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    calls: list[Decision] = []
    original = strategy._evaluate_no_side_shadow

    def _spy(*, no_decision: Decision, **kwargs: Any) -> None:
        calls.append(no_decision)
        original(no_decision=no_decision, **kwargs)

    strategy._evaluate_no_side_shadow = _spy  # type: ignore[method-assign]

    # ask=0.02 is out of band (raises F-1a); bid=0.94 makes NO_ask=0.06 (in
    # band) but bid(0.94) >= ask(0.02) -- crossed.
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.02", bid="0.94", ts_event=WINDOW_OPEN_NS))

    assert len(calls) == 1
    assert calls[0] == Refuse("not_executable")


# ---------------------------------------------------------------------------
# AC7: a YES-ask-in-band tick is byte-identical to the pre-F-1a baseline.
# ---------------------------------------------------------------------------


def test_yes_in_band_tick_is_byte_identical(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    calls = _spy_no_side_shadow(strategy)
    submitted: list[object] = []
    strategy.submit_order = submitted.append  # type: ignore[method-assign]

    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))

    assert submitted == []
    rows = strategy.offer_tape.records()
    yes_rows = [rec for rec in rows if rec.side == "YES"]
    assert len(yes_rows) == 1
    assert yes_rows[0].reason == "taken"
    assert strategy.diagnostics.counts == {}
    assert strategy.refusals.counts == {}
    # The default bid ("0.01") makes NO_ask=0.99 -- outside the band -- so
    # `evaluate_both_sides` still runs the NO shadow (unaffected by F-1a,
    # since raw_executable is True and this branch never runs at all), and
    # it is called exactly once, exactly as before this slice.
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# Silent-failure-hunter finding (2026-09-25): `_hunt_no_only` must contain a
# raising store dependency the same way `_evaluate_shadow_rest` contains its
# decider -- never raise into `_hunt_tick`, count every fault, log at ERROR
# at most once per station-day, and never leave `is_inflight`/the bounded
# first-order key half-written without a submit.
# ---------------------------------------------------------------------------


def test_a_raising_store_dependency_is_contained_and_clears_half_written_inflight(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """Exercises the REAL arm tail up through `set_inflight`/`record_attempt`
    /the durable ``NO_SIDE_FIRST_LIVE_ORDER_KEY`` write, then injects the
    fault at `_maybe_submit` -- exactly the "state could be half-written"
    ordering the finding names. `is_inflight` (read by no other gate) is
    defensively cleared; the bounded first-order key (which DOES gate future
    arms) is left set, fail-closed, matching `_evaluate_no_side_shadow`'s
    own documented stance."""
    config = _gate_cleared_config(instruments=(interior_instrument,))
    strategy = _register_and_start(
        store_path=store_path, instruments=(interior_instrument,), config=config,
    )
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

    def _raise(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("simulated submit-path fault")

    strategy._maybe_submit = _raise  # type: ignore[method-assign]

    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.97", bid=_BAND_CLEARING_BID, ts_event=WINDOW_OPEN_NS)
    )

    assert strategy.is_running
    assert strategy.diagnostics.count("no_only_hunt_error") == 1
    assert strategy.last_no_only_hunt_error is not None
    assert strategy._latch is not None
    assert (
        strategy._latch.is_inflight(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(_NO_INTERIOR_ID)
        )
        is False
    )
    # Fail-closed, deliberately: the pending flag was durably written before
    # the injected fault and is never cleared by the containment handler.
    assert is_no_side_pending(strategy._latch._store) is True


def test_a_second_raise_in_the_same_station_day_does_not_log_again(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

    def _raise(**kwargs: Any) -> None:
        raise RuntimeError("simulated store fault")

    strategy._evaluate_no_side_shadow = _raise  # type: ignore[method-assign]

    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.97", bid=_BAND_CLEARING_BID, ts_event=WINDOW_OPEN_NS)
    )
    assert len(strategy._no_only_hunt_error_notice) == 1
    assert strategy.diagnostics.count("no_only_hunt_error") == 1

    strategy.on_quote_tick(
        _quote(
            INTERIOR_ID, ask="0.97", bid=_BAND_CLEARING_BID,
            ts_event=WINDOW_OPEN_NS + NS_PER_MIN,
        )
    )

    assert strategy.is_running
    # Counted both times -- a persistent fault is never silently invisible.
    assert strategy.diagnostics.count("no_only_hunt_error") == 2
    # But the notice set (and therefore the ERROR log it guards) never grows
    # past the first entry for this station-day.
    assert len(strategy._no_only_hunt_error_notice) == 1


# ---------------------------------------------------------------------------
# F-1b (plan STALL_FOLLOWUPS_F1_F4_2026-09-24.md, Rev 3.1): a bid-only
# Depth10 book (a YES book with a real bid but no real ask -- the venue's
# own book, not derivable from any QuoteTick) reaches NO evaluation.
# ---------------------------------------------------------------------------


def test_bid_only_depth_evaluates_no_side(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """AC1: a bid-only book with an executable NO leg evaluates NO exactly
    once, and records no YES diagnostic (the frame carries no ask)."""
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    calls = _spy_no_side_shadow(strategy)

    strategy.on_order_book_depth(
        _bid_only_depth(bid=_BAND_CLEARING_BID, ts_event=WINDOW_OPEN_NS)
    )

    assert len(calls) == 1
    assert strategy.diagnostics.counts == {}
    assert not any(rec.side == "YES" for rec in strategy.offer_tape.records())


def test_bid_only_depth_no_leg_out_of_band_is_silent(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """AC2: a bid-only book whose NO leg is outside the band writes no row
    and causes no ``not_executable``/``refusals`` delta."""
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    calls = _spy_no_side_shadow(strategy)

    # bid=0.99 -> NO_ask = 0.01, outside (0.05, 0.95).
    strategy.on_order_book_depth(_bid_only_depth(bid="0.99", ts_event=WINDOW_OPEN_NS))

    assert calls == []
    assert strategy.diagnostics.counts == {}
    assert strategy.refusals.counts == {}
    assert strategy.offer_tape.records() == ()


def test_empty_depth_returns_early(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """AC3: a book with neither an ask nor a bid returns early, unchanged."""
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    calls = _spy_no_side_shadow(strategy)

    strategy.on_order_book_depth(_depth(INTERIOR_ID, bids=(), asks=(), ts_event=WINDOW_OPEN_NS))

    assert calls == []
    assert strategy.diagnostics.counts == {}
    assert strategy.refusals.counts == {}
    assert strategy.offer_tape.records() == ()


def test_bid_only_dedupe_distinguishes_bids_at_same_ts(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """The dedupe key for an ask-less frame is ``(ts_event, None, bid,
    bid_size)`` -- a DIFFERENT bid at the identical ``ts_event`` is not
    swallowed, but the identical bid at the identical ``ts_event`` is."""
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    calls = _spy_no_side_shadow(strategy)

    strategy.on_order_book_depth(
        _bid_only_depth(bid=_BAND_CLEARING_BID, ts_event=WINDOW_OPEN_NS)
    )
    strategy.on_order_book_depth(_bid_only_depth(bid="0.90", ts_event=WINDOW_OPEN_NS))
    assert len(calls) == 2

    strategy.on_order_book_depth(_bid_only_depth(bid="0.90", ts_event=WINDOW_OPEN_NS))
    assert len(calls) == 2


def test_bid_only_gate_closed_never_submits(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """AC4: gate closed -- no order, no inflight, no first-order key."""
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    submitted: list[object] = []
    strategy.submit_order = submitted.append  # type: ignore[method-assign]

    strategy.on_order_book_depth(
        _bid_only_depth(bid=_BAND_CLEARING_BID, ts_event=WINDOW_OPEN_NS)
    )

    assert submitted == []
    assert strategy._latch is not None
    assert (
        strategy._latch.is_inflight(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(_NO_INTERIOR_ID)
        )
        is False
    )
    assert is_no_side_pending(strategy._latch._store) is False
    rows = [rec for rec in strategy.offer_tape.records() if rec.side == "NO"]
    assert len(rows) == 1
    assert rows[0].reason == "no_side_calibration_unsafe"


def test_quote_tick_path_unchanged(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """AC5: the QuoteTick path (`_snapshot_from_quote` always sets an ask)
    is byte-identical to the pre-F-1b baseline."""
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    submitted: list[object] = []
    strategy.submit_order = submitted.append  # type: ignore[method-assign]

    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))

    rows = strategy.offer_tape.records()
    yes_rows = [rec for rec in rows if rec.side == "YES"]
    assert len(yes_rows) == 1
    assert yes_rows[0].reason == "taken"
    assert strategy.diagnostics.counts == {}
    assert strategy.refusals.counts == {}


# ---------------------------------------------------------------------------
# R1: every upstream gate above the ask/bid branch runs identically for a
# bid-only frame as for any other trigger -- named per the F-1b delta table.
# ---------------------------------------------------------------------------


def _family_halt_strategy(
    store_path: Path, interior_instrument: BinaryOption,
) -> ContinuousRungHoldStrategy:
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    assert strategy._latch is not None
    strategy._latch.record_policy_halt(
        reason="test halt", evidence_sha256="a" * 64, ts_ns=WINDOW_OPEN_NS,
    )
    return strategy


def _day_budget_exhausted_strategy(
    store_path: Path, interior_instrument: BinaryOption,
) -> ContinuousRungHoldStrategy:
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    assert strategy._latch is not None
    utc_day = utc_day_for_ns(WINDOW_OPEN_NS).isoformat()
    strategy._latch._store.set(f"{BUDGET_EXHAUSTED_KEY_PREFIX}{utc_day}", b"1")
    return strategy


def _intent_open_strategy(
    store_path: Path, interior_instrument: BinaryOption,
) -> ContinuousRungHoldStrategy:
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    assert strategy._latch is not None
    intent_latch = strategy._latch._intent_latch
    assert intent_latch is not None
    intent_latch.arm("a" * 64, now_ns=WINDOW_OPEN_NS)
    return strategy


def _rearm_wait_strategy(
    store_path: Path, interior_instrument: BinaryOption,
) -> ContinuousRungHoldStrategy:
    strategy = _register_phase1_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    assert strategy._latch is not None
    strategy._latch.record_attempt(
        STATION, CLIMATE_DAY.isoformat(), ts_ns=WINDOW_OPEN_NS, key_instrument_id=str(INTERIOR_ID),
    )
    return strategy


@pytest.mark.parametrize(
    ("build_strategy", "expected_diag_key"),
    [
        (_family_halt_strategy, _DIAG_FAMILY_HALT),
        (_day_budget_exhausted_strategy, _DIAG_DAY_BUDGET_EXHAUSTED),
        (_intent_open_strategy, _DIAG_OPEN_INTENT_WAIT),
        (_rearm_wait_strategy, _DIAG_REARM_WAIT),
    ],
    ids=["family_halt", "day_budget_exhausted", "intent_open", "rearm_wait"],
)
def test_bid_only_frame_counter_deltas_per_upstream_state(
    store_path: Path,
    interior_instrument: BinaryOption,
    build_strategy: Callable[[Path, BinaryOption], ContinuousRungHoldStrategy],
    expected_diag_key: str,
) -> None:
    """R1: each pre-decision gate above the ask/bid branch runs identically
    for a bid-only Depth10 frame as for any other trigger -- the F-1b delta
    table names each one explicitly as an accepted delta, and `refusals`
    stays empty for every one of these (none of them is a refusal)."""
    strategy = build_strategy(store_path, interior_instrument)

    strategy.on_order_book_depth(
        _bid_only_depth(bid=_BAND_CLEARING_BID, ts_event=WINDOW_OPEN_NS)
    )

    assert strategy.diagnostics.counts == {expected_diag_key: 1}
    assert strategy.refusals.counts == {}


def test_bid_only_frame_outside_window_is_silent(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """R1: a bid-only frame outside the decision window returns BEFORE
    `refusals.record(_OUTSIDE_DECISION_WINDOW)` and before
    `_observe_halt(trading_expected=False)` -- `refusals` stays
    byte-identical, unlike an ask-bearing out-of-window frame."""
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

    strategy.on_order_book_depth(
        _bid_only_depth(bid=_BAND_CLEARING_BID, ts_event=WINDOW_OPEN_NS - 30 * NS_PER_MIN)
    )

    assert strategy.refusals.counts == {}
    assert strategy.diagnostics.counts == {}
    assert strategy.offer_tape.records() == ()
    assert _OUTSIDE_DECISION_WINDOW not in strategy.refusals.counts


def test_release_stale_inflight_is_trigger_independent(
    interior_instrument: BinaryOption, tmp_path: Path,
) -> None:
    """R1: `_release_stale_inflight`'s conditions (intent CLOSED, the
    same-burst delay floor elapsed) do not depend on the trigger -- a quote
    tick, an ask-bearing Depth10 frame and a bid-only Depth10 frame release
    the SAME stale IN_FLIGHT marker identically (same `clear_inflight`
    outcome, same `inflight_released` count, same `rearm:` summary)."""
    release_ts = WINDOW_OPEN_NS + 121_000_000_000  # past `_REARM_MIN_DELAY_NS` (120s)

    def _prime(store_path: Path) -> ContinuousRungHoldStrategy:
        strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
        strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
        assert strategy._latch is not None
        strategy._latch.record_attempt(
            STATION,
            CLIMATE_DAY.isoformat(),
            ts_ns=WINDOW_OPEN_NS,
            key_instrument_id=str(INTERIOR_ID),
        )
        strategy._latch.set_inflight(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID),
        )
        return strategy

    def _outcome(strategy: ContinuousRungHoldStrategy) -> tuple[bool, int, str | None]:
        assert strategy._latch is not None
        return (
            strategy._latch.is_inflight(
                STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID)
            ),
            strategy.diagnostics.count("inflight_released"),
            strategy.last_rearm_decision,
        )

    quote_strategy = _prime(tmp_path / "quote.db")
    quote_strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.97", ts_event=release_ts))
    quote_outcome = _outcome(quote_strategy)

    ask_depth_strategy = _prime(tmp_path / "ask_depth.db")
    ask_depth_strategy.on_order_book_depth(
        _depth(
            INTERIOR_ID,
            bids=((_BAND_CLEARING_BID, 10),),
            asks=(("0.97", 10),),
            ts_event=release_ts,
        )
    )
    ask_depth_outcome = _outcome(ask_depth_strategy)

    bid_only_strategy = _prime(tmp_path / "bid_only.db")
    bid_only_strategy.on_order_book_depth(
        _bid_only_depth(bid=_BAND_CLEARING_BID, ts_event=release_ts)
    )
    bid_only_outcome = _outcome(bid_only_strategy)

    assert quote_outcome == (False, 1, quote_outcome[2])
    assert quote_outcome == ask_depth_outcome == bid_only_outcome


# ---------------------------------------------------------------------------
# F-1c (plan STALL_FOLLOWUPS_F1_F4_2026-09-24.md, Rev 3.1): a YES instrument-
# day that is consumed but not FILLED still evaluates NO. YES IN_FLIGHT and
# rearm_wait stay fail-closed (unmodified, existing behaviour -- documented
# here as this slice's own acceptance criteria). A positive (filled) cache
# result fails closed on a miss/eviction: it always re-derives from the
# durable store, never assumes "not filled".
#
# Writer proof (R3 AC5, codegraph `_callers` on `consume`/`consume_if_absent`
# in `trial_day_latch.py`, `projectPath=/home/jon/breezy`): the ONLY two
# production writers of a YES `TrialDayRecord` anywhere in
# `continuous_strategy.py` are `_consume_trial_from_fill_record`
# (`reason=TAKEN_FROM_FILL_WALK_REASON`) and `_consume_or_flag_duplicate`
# (`reason="taken"`) -- both members of `_FILLED_REASONS`. No live path in
# this module ever writes a non-fill YES record today, so AC2 below is
# dormant in production; it is exercised here via a DIRECT latch write, the
# same harness idiom every IN_FLIGHT/rearm/intent-open test in this file
# already uses. No "treat as filled" skip-set entry is needed: the new
# branch already fails closed on anything it cannot positively prove filled.
# ---------------------------------------------------------------------------


def _consume_yes(
    strategy: ContinuousRungHoldStrategy, *, reason: str, ts_ns: int = WINDOW_OPEN_NS,
) -> None:
    assert strategy._latch is not None
    wrote = strategy._latch.consume_if_absent(
        STATION,
        CLIMATE_DAY.isoformat(),
        TrialDayRecord(
            latched_at_ns=ts_ns,
            instrument_id=str(INTERIOR_ID),
            ask=Decimal("0.40"),
            reason=reason,
        ),
        key_instrument_id=str(INTERIOR_ID),
    )
    assert wrote is True


def test_yes_consumed_filled_skips_no(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    _consume_yes(strategy, reason="taken")
    calls = _spy_no_side_shadow(strategy)

    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.97", bid=_BAND_CLEARING_BID, ts_event=WINDOW_OPEN_NS)
    )

    assert calls == []
    assert strategy.diagnostics.counts == {}
    assert strategy.refusals.counts == {}
    assert strategy.offer_tape.records() == ()


def test_yes_consumed_filled_result_is_cached(
    store_path: Path,
    interior_instrument: BinaryOption,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC1: the second and later ticks do no store read (they hit the
    cache) -- proxied by counting calls to `refuse_if_sibling_leg_traded`,
    the ONLY store read this branch's cache shields."""
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    _consume_yes(strategy, reason="taken")

    calls: list[Any] = []
    original = continuous_strategy_module.refuse_if_sibling_leg_traded

    def _spy(*args: Any, **kwargs: Any) -> Any:
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(continuous_strategy_module, "refuse_if_sibling_leg_traded", _spy)

    for i in range(5):
        strategy.on_quote_tick(
            _quote(
                INTERIOR_ID, ask="0.97", bid=_BAND_CLEARING_BID,
                ts_event=WINDOW_OPEN_NS + i * NS_PER_MIN,
            )
        )

    assert len(calls) == 1


@pytest.mark.parametrize("reason", sorted(REFUSAL_REASONS))
def test_yes_consumed_unfilled_evaluates_no(
    store_path: Path, interior_instrument: BinaryOption, reason: str,
) -> None:
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    _consume_yes(strategy, reason=reason)
    calls = _spy_no_side_shadow(strategy)

    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.97", bid=_BAND_CLEARING_BID, ts_event=WINDOW_OPEN_NS)
    )

    assert len(calls) == 1
    rows = [rec for rec in strategy.offer_tape.records() if rec.side == "NO"]
    assert len(rows) == 1
    assert rows[0].reason == "no_side_calibration_unsafe"


def test_consumed_unfilled_with_open_ambiguous_intent_is_silent(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    _consume_yes(strategy, reason="not_executable")
    assert strategy._latch is not None
    intent_latch = strategy._latch._intent_latch
    assert intent_latch is not None
    intent_latch.arm("a" * 64, now_ns=WINDOW_OPEN_NS)
    calls = _spy_no_side_shadow(strategy)

    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.97", bid=_BAND_CLEARING_BID, ts_event=WINDOW_OPEN_NS)
    )

    assert calls == []
    assert strategy.diagnostics.counts == {}
    assert strategy.refusals.counts == {}
    assert strategy.offer_tape.records() == ()


def test_yes_inflight_skips_no(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """AC3: an unreleased IN_FLIGHT YES marker -- distinct from consumed --
    still skips NO. Existing, unmodified behaviour; pinned here as an F-1c
    acceptance criterion (the risk register's fail-closed row)."""
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    assert strategy._latch is not None
    strategy._latch.set_inflight(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID),
    )
    calls = _spy_no_side_shadow(strategy)

    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.97", bid=_BAND_CLEARING_BID, ts_event=WINDOW_OPEN_NS)
    )

    assert calls == []


def test_yes_rearm_wait_skips_no(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """AC3: a YES re-arm wait -- distinct from consumed -- still skips NO.
    Existing, unmodified behaviour; pinned here as an F-1c acceptance
    criterion."""
    strategy = _register_phase1_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    assert strategy._latch is not None
    strategy._latch.record_attempt(
        STATION, CLIMATE_DAY.isoformat(), ts_ns=WINDOW_OPEN_NS, key_instrument_id=str(INTERIOR_ID),
    )
    calls = _spy_no_side_shadow(strategy)

    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.97", bid=_BAND_CLEARING_BID, ts_event=WINDOW_OPEN_NS)
    )

    assert calls == []
    assert strategy.diagnostics.count(_DIAG_REARM_WAIT) == 1


def test_consumed_path_outside_window_records_nothing(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    _consume_yes(strategy, reason="not_executable")
    calls = _spy_no_side_shadow(strategy)

    outside_ts = WINDOW_OPEN_NS - 30 * NS_PER_MIN
    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.97", bid=_BAND_CLEARING_BID, ts_event=outside_ts)
    )

    assert calls == []
    assert strategy.diagnostics.counts == {}
    assert strategy.refusals.counts == {}
    assert strategy.offer_tape.records() == ()
    assert _OUTSIDE_DECISION_WINDOW not in strategy.refusals.counts


def test_cache_eviction_or_miss_reconsults_the_durable_store_never_assumes_not_filled(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """Fail-closed proof (coordinator brief): clearing the cache (the same
    empty shape a real eviction, or a fresh process, would leave) never
    flips the outcome -- the very next tick re-derives "filled" from the
    DURABLE store and re-populates the cache; an absent cache entry is
    never treated as "not filled"."""
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    _consume_yes(strategy, reason="taken")
    calls = _spy_no_side_shadow(strategy)

    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.97", bid=_BAND_CLEARING_BID, ts_event=WINDOW_OPEN_NS)
    )
    station_day = (STATION, CLIMATE_DAY.isoformat())
    cache_key = (station_day, str(INTERIOR_ID))
    assert cache_key in strategy._yes_fill_blocks_no

    strategy._yes_fill_blocks_no.clear()

    strategy.on_quote_tick(
        _quote(
            INTERIOR_ID, ask="0.97", bid=_BAND_CLEARING_BID,
            ts_event=WINDOW_OPEN_NS + NS_PER_MIN,
        )
    )

    assert calls == []
    assert strategy.offer_tape.records() == ()
    assert cache_key in strategy._yes_fill_blocks_no


def test_sibling_check_fault_is_contained_and_does_not_cache(
    store_path: Path, interior_instrument: BinaryOption, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MEDIUM (coordinator review of 10d46cf): a raising
    `refuse_if_sibling_leg_traded` -- e.g. a corrupt durable sibling record
    -- inside `_hunt_no_only_after_yes_consumed`'s own gate must be
    CONTAINED exactly like `_hunt_no_only`'s own store dependency: no NO
    evaluation, no cache write (fail closed -- a later, healthy tick must
    still re-derive the true answer), counted every time (a persistent
    fault is never silently invisible), and logged at most once per
    station-day."""
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    _consume_yes(strategy, reason="taken")
    calls = _spy_no_side_shadow(strategy)

    def _raise(*args: Any, **kwargs: Any) -> Any:
        raise TrialDayRecordCorrupt()

    monkeypatch.setattr(continuous_strategy_module, "refuse_if_sibling_leg_traded", _raise)

    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.97", bid=_BAND_CLEARING_BID, ts_event=WINDOW_OPEN_NS)
    )

    assert calls == []
    assert strategy.diagnostics.count(_DIAG_NO_ONLY_HUNT_ERROR) == 1
    station_day = (STATION, CLIMATE_DAY.isoformat())
    cache_key = (station_day, str(INTERIOR_ID))
    assert cache_key not in strategy._yes_fill_blocks_no

    # A second tick in the same station-day: the fault is counted again
    # (persistent faults stay visible) but the ERROR log's dedupe notice
    # does not grow past its first entry.
    strategy.on_quote_tick(
        _quote(
            INTERIOR_ID, ask="0.97", bid=_BAND_CLEARING_BID,
            ts_event=WINDOW_OPEN_NS + NS_PER_MIN,
        )
    )

    assert calls == []
    assert strategy.diagnostics.count(_DIAG_NO_ONLY_HUNT_ERROR) == 2
    assert cache_key not in strategy._yes_fill_blocks_no
    assert len(strategy._no_only_hunt_error_notice) == 1
