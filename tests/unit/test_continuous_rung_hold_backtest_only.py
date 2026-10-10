"""SP-4 increment B: `ContinuousRungHoldBacktestStrategy` -- the v3
paper-replay driver's ONLY continuous-hunt subclass.

Reuses the real-store harness from `test_continuous_rung_hold_strategy.py`
(itself reusing `test_current_rung_hold_strategy.py`'s fixtures), the same
pattern `test_current_rung_hold_backtest_only.py` uses for the v2 subclass.
"""

from __future__ import annotations

import ast
import importlib.util
import itertools
import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from nautilus_trader.common.component import TestClock
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import CustomData, OrderBookDepth10
from nautilus_trader.model.events import OrderFilled
from nautilus_trader.model.identifiers import TraderId
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Money
from nautilus_trader.portfolio import Portfolio
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

import breezy.strategy.current_rung_hold.continuous_backtest_only as continuous_backtest_only_module
from breezy.adapters.polymarket_us.exec import submit_chain
from breezy.runtime.backtest_feed import as_backtest_data
from breezy.runtime.backtest_harness import backtest
from breezy.runtime.paper_replay import (
    UNSCOPED_FAMILY_ID,
    ReplayEntryContext,
    build_paper_replay_config,
    filled_trials_from_engine,
)
from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
from breezy.strategy.current_rung_hold.continuous_backtest_only import (
    ContinuousNotABacktestClockError,
    ContinuousRungHoldBacktestStrategy,
)
from breezy.strategy.current_rung_hold.continuous_strategy import (
    _MAX_STATION_DAY_ATTEMPTS,
    _REARM_MIN_DELAY_NS,
)
from breezy.strategy.current_rung_hold.monitor_records import PositionMarkRecord
from breezy.strategy.current_rung_hold.monitor_store import (
    open_monitor_catalog,
    read_monitor_summaries,
)
from breezy.strategy.current_rung_hold.offer_tape import OfferTape
from breezy.strategy.current_rung_hold.trial_day_latch import CONTINUOUS_TRIAL_KEY_PREFIX
from tests.support.nautilus_log_capture import capture_nautilus_logs, wait_for_logged
from tests.unit.test_continuous_rung_hold_strategy import (
    _PERMISSIVE_EVIDENCE,
    _cont_latch_factory,
    _depth,
    _order_denied,
    _order_filled_for_position,
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

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TARGET_MODULE = "breezy.strategy.current_rung_hold.continuous_backtest_only"
_TARGET_NAME = "ContinuousRungHoldBacktestStrategy"
_TARGET_FILE = (
    _REPO_ROOT / "src/breezy/strategy/current_rung_hold/continuous_backtest_only.py"
)
#: The ONE non-test importer this module is authorised to gain -- landed by
#: increment C, not here. AM-5's literal scan (below) is written so it
#: stays GREEN both BEFORE and AFTER that wiring lands (a subset check,
#: never a hand-edited exact match).
_EXPECTED_IMPORTER = "scripts/analysis/current_rung_hold_paper_replay.py"
_DRIVER_FILE = _REPO_ROOT / "scripts/analysis/current_rung_hold_paper_replay.py"
_BASELINE_DYNAMIC_IMPORT_CALL_SITES = 0
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"


def _load_paper_replay_driver() -> ModuleType:
    """INC-7: dynamically loads the driver module, mirroring
    `test_current_rung_hold_paper_replay.py::_load_driver` exactly --
    `scripts/` is unimportable as a package from `src/breezy`."""
    if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))
    path = _SCRIPTS_ANALYSIS_DIR / "current_rung_hold_paper_replay.py"
    spec = importlib.util.spec_from_file_location("current_rung_hold_paper_replay", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def paper_replay_driver() -> ModuleType:
    return _load_paper_replay_driver()


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "state.db"


@pytest.fixture
def interior_instrument() -> BinaryOption:
    return _instrument(INTERIOR_ID, lower_f=86, upper_f=87)


def _register_backtest(
    *,
    store_path: Path,
    instruments: tuple[BinaryOption, ...],
    clock: TestClock | None = None,
    offer_tape: OfferTape | None = None,
    position_evidence_reader: Any | None = None,
) -> ContinuousRungHoldBacktestStrategy:
    cfg = CurrentRungHoldConfig(
        instrument_ids=tuple(instrument.id for instrument in instruments),
    )
    strategy = ContinuousRungHoldBacktestStrategy(
        cfg,
        trial_day_latch_factory=_cont_latch_factory(store_path),
        offer_tape=offer_tape,
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


def _register_backtest_and_start(
    *,
    store_path: Path,
    instruments: tuple[BinaryOption, ...],
    clock: TestClock | None = None,
    offer_tape: OfferTape | None = None,
    position_evidence_reader: Any | None = None,
) -> ContinuousRungHoldBacktestStrategy:
    strategy = _register_backtest(
        store_path=store_path,
        instruments=instruments,
        clock=clock,
        offer_tape=offer_tape,
        position_evidence_reader=position_evidence_reader,
    )
    strategy.start()
    return strategy


def test_backtest_only_forwards_diagnostics_summary_and_build_sha(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """R9 (STALL_FOLLOWUPS_F1_F4_2026-09-24.md, F-2): both new kwargs reach
    the parent's own fields unchanged -- this subclass adds no new
    behaviour of its own around them, only forwards."""
    from breezy.strategy.current_rung_hold.diagnostics_summary import DiagnosticsSummarySink

    sink = DiagnosticsSummarySink(None)
    cfg = CurrentRungHoldConfig(instrument_ids=(interior_instrument.id,))

    strategy = ContinuousRungHoldBacktestStrategy(
        cfg,
        trial_day_latch_factory=_cont_latch_factory(store_path),
        diagnostics_summary=sink,
        build_sha="deadbeef0001",
    )

    assert strategy._diagnostics_summary is sink
    assert strategy._build_sha == "deadbeef0001"


# ---------------------------------------------------------------------------
# B-1: the AST exact-set method pin (L-12 widen-never-relax)
# ---------------------------------------------------------------------------


def _imports_the_subclass(path: Path) -> bool:
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == _TARGET_MODULE
            and any(alias.name == _TARGET_NAME for alias in node.names)
        ):
            return True
        if isinstance(node, ast.Import) and any(
            alias.name == _TARGET_MODULE for alias in node.names
        ):
            return True
    return False


def test_the_continuous_backtest_only_subclass_has_exactly_one_importer() -> None:
    """Landed once increment C wires the driver -- see B's commit message:
    this assertion requires the driver to already import this class, which
    is C's job, not B's."""
    importers = []
    for root_dir in ("src", "scripts"):
        base = _REPO_ROOT / root_dir
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if path == _TARGET_FILE:
                continue
            if _imports_the_subclass(path):
                importers.append(str(path.relative_to(_REPO_ROOT)))
    assert importers == [_EXPECTED_IMPORTER], (
        f"{_TARGET_NAME} must have exactly one non-test importer "
        f"({_EXPECTED_IMPORTER!r}); found {importers!r}"
    )


def test_the_subclass_defines_exactly_three_methods() -> None:
    """The subclass's OWN `ClassDef` body defines EXACTLY
    `{__init__, on_start, _submission_armed}` -- the falsifier for "none of
    the twelve byte-inherited methods appears here"."""
    tree = ast.parse(_TARGET_FILE.read_text(), filename=str(_TARGET_FILE))
    class_node = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == _TARGET_NAME
    )
    method_names = {
        node.name for node in class_node.body if isinstance(node, ast.FunctionDef)
    }
    assert method_names == {"__init__", "on_start", "_submission_armed"}


def test_the_backtest_subclass_never_exposes_a_fee_verified_check_parameter() -> None:
    """EDGE-1 (AM-2): paper replay must never be able to pass a non-None
    `fee_verified_check` -- this subclass's own `__init__` does not even
    expose the parameter, so it always inherits the parent's `None`
    default, byte-identical to every construction site before this
    parameter existed."""
    import inspect

    sig = inspect.signature(ContinuousRungHoldBacktestStrategy.__init__)
    assert "fee_verified_check" not in sig.parameters


# ---------------------------------------------------------------------------
# on_start: the TestClock barrier, the never-arm walk, L-24 negatives
# ---------------------------------------------------------------------------


def test_on_start_refuses_a_non_testclock(
    store_path: Path,
    interior_instrument: BinaryOption,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NB-2: asserts BOTH the raise AND the `log.error` call -- one line
    strictly more visible than the v2 precedent, defence in depth.
    `Strategy.log` is a Nautilus Cython `Logger` (an immutable extension
    type -- `strategy.log.error = ...` raises `AttributeError: ... is
    read-only`), so the ERROR line is observed at the OS file-descriptor
    level, read back from the Nautilus log file capture."""
    strategy = _register_backtest(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    monkeypatch.setattr(continuous_backtest_only_module, "TestClock", str)
    read_logs = capture_nautilus_logs()
    with pytest.raises(ContinuousNotABacktestClockError):
        strategy.on_start()
    # Nautilus's Rust-backed logger writes on its own background thread --
    # bounded wait for delivery of the same lines, assertions unchanged.
    logged = wait_for_logged(read_logs, "ERROR", _TARGET_NAME)
    assert "ERROR" in logged
    assert _TARGET_NAME in logged


def test_on_start_succeeds_against_a_real_testclock_with_flat_startup_evidence(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    strategy = _register_backtest(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    strategy.on_start()  # must not raise
    assert strategy._latch is not None
    assert str(interior_instrument.id) in strategy._facts


def test_on_start_still_stops_when_startup_evidence_is_absent(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """L-24 NEGATIVE: an absent reader (`None` evidence) still halts before
    any subscription -- the armed branch never trusts a fixture that always
    satisfies the invariant."""
    strategy = _register_backtest(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: None,
    )
    stopped: list[bool] = []
    strategy.stop = lambda: stopped.append(True)
    strategy.on_start()
    assert stopped == [True]
    assert strategy.position_events.count("startup_evidence_missing") == 1


def test_on_start_still_stops_when_one_candidate_slug_is_missing_from_evidence(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """L-24 NEGATIVE. HF-1 OWNS any change to this ruling: an ABSENT slug is
    UNKNOWN, never flat -- an otherwise-complete evidence dict that omits
    THIS instrument's own slug still halts."""
    evidence = {**_PERMISSIVE_EVIDENCE, "positions": []}
    strategy = _register_backtest(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: evidence,
    )
    stopped: list[bool] = []
    strategy.stop = lambda: stopped.append(True)
    strategy.on_start()
    assert stopped == [True]
    assert strategy.position_events.count("unreconciled_long_no_fill") == 1


# ---------------------------------------------------------------------------
# The one deliberate behaviour change: `_submission_armed` reaches
# `submit_order`, and PERMIT ISOLATION holds throughout.
# ---------------------------------------------------------------------------


def test_the_armed_subclass_reaches_submit_order_where_the_parent_only_logs(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    strategy = _register_backtest_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    submitted: list[object] = []
    strategy.submit_order = submitted.append
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))
    assert len(submitted) == 1


def test_the_subclass_never_holds_an_order_submission_permit(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """PERMIT ISOLATION: the subclass is armed via a private backtest-only
    flag, never a real `OrderSubmissionPermit` -- `__init__` does not even
    expose that parameter."""
    strategy = _register_backtest(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    assert strategy._order_submission_permit is None
    assert strategy._submission_armed() is True
    assert (
        "order_submission_permit"
        not in ContinuousRungHoldBacktestStrategy.__init__.__code__.co_varnames
    )


def test_one_station_day_submits_at_most_max_station_day_attempts_orders_spaced_by_the_rearm_floor(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """R-10 / PREREG Sec5: this replaces the pre-HF-4
    "at most one order" pin, which encoded the pre-HF-4 UNREACHABILITY of
    re-arm, not a genuine safety invariant -- HF-4's stale-IN_FLIGHT
    release makes attempts 2 and 3 reachable by design (Decision 1,
    HF-4.rev2.md), including for this always-armed backtest harness, whose
    `submit_order` stub never opens a real submit intent (`is_intent_open()`
    is trivially False here, so release is floor-only -- see the
    `ContinuousRungHoldBacktestStrategy` class docstring).

    The restated invariant (HD-9, R-10): at most `_MAX_STATION_DAY_ATTEMPTS`
    submissions for this station-day, each one at least `_REARM_MIN_DELAY_NS`
    (event time) after the previous, and never a fourth no matter how many
    further eligible frames arrive.
    """
    strategy = _register_backtest_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    submitted: list[object] = []
    submission_ts_events: list[int] = []
    strategy.submit_order = submitted.append
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    for i in range(16):  # well past the 3rd attempt (~240s) + another 120s
        depth = _depth(
            INTERIOR_ID,
            bids=(),
            asks=(("0.40", 10),),
            ts_event=WINDOW_OPEN_NS + i * NS_PER_MIN,
        )
        before = len(submitted)
        strategy.on_order_book_depth(depth)
        if len(submitted) > before:
            submission_ts_events.append(depth.ts_event)

    assert len(submitted) == _MAX_STATION_DAY_ATTEMPTS
    assert len(submission_ts_events) == _MAX_STATION_DAY_ATTEMPTS
    for earlier, later in itertools.pairwise(submission_ts_events):
        assert later - earlier >= _REARM_MIN_DELAY_NS


def test_a_fill_freezes_the_station_day_against_further_submission(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """R-10 / PREREG Sec5: once a genuine fill lands on this station-day,
    `is_consumed` freezes it for the rest of this process's life -- no
    further `_hunt_tick` may ever reach `submit_order` again, no matter how
    many more eligible frames arrive."""
    strategy = _register_backtest_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    submitted: list[object] = []
    strategy.submit_order = submitted.append
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_order_book_depth(
        _depth(INTERIOR_ID, bids=(), asks=(("0.40", 10),), ts_event=WINDOW_OPEN_NS),
    )
    assert len(submitted) == 1

    strategy.on_order_filled(_order_filled_for_position(strategy, venue_order_id="V-1"))
    assert strategy._latch is not None
    assert strategy._latch.is_consumed(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID),
    ) is True

    for i in range(1, 16):
        strategy.on_order_book_depth(
            _depth(
                INTERIOR_ID,
                bids=(),
                asks=(("0.40", 10),),
                ts_event=WINDOW_OPEN_NS + i * NS_PER_MIN,
            ),
        )
    assert len(submitted) == 1


def test_a_wait_class_deny_lets_a_later_frame_produce_a_SECOND_attempt(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """AM-1, rescoped per NB-1: the clear itself is already pinned by the
    shipped pair `test_continuous_rung_hold_strategy.py::
    test_on_order_denied_with_the_wait_reason_clears_inflight` (:459) and
    `::test_on_order_denied_with_any_other_reason_leaves_inflight_set`
    (:479). The uncovered part -- the SECOND attempt after the clear -- is
    the only new assertion here, driven through the real armed subclass."""
    strategy = _register_backtest_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    submitted: list[object] = []
    strategy.submit_order = submitted.append

    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))
    assert strategy._latch is not None
    assert strategy._latch.attempt_state(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID),
    ) == (
        1,
        WINDOW_OPEN_NS,
    )
    assert len(submitted) == 1
    assert strategy._latch.is_inflight(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID),
    ) is True

    # The clear itself is pinned by the shipped `:459` test; this is the
    # precondition for the next step, not the assertion under test here.
    strategy.on_order_denied(
        _order_denied(strategy, reason=submit_chain.OPEN_INTENT_WAIT_REASON),
    )
    assert strategy._latch.is_inflight(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID),
    ) is False

    second_ts = WINDOW_OPEN_NS + _REARM_MIN_DELAY_NS + 1
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=second_ts))
    assert strategy._latch.attempt_state(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID),
    ) == (
        2,
        second_ts,
    )
    assert len(submitted) == 2


def test_a_fill_is_delivered_before_the_next_depth_frame_is_handled(
    store_path: Path, interior_instrument: BinaryOption, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F0 row 6 (AM-8), MEASURED through a REAL `BacktestEngine` +
    `SimulatedExchange` run -- the at-most-one-submission COUNT invariant
    (`test_one_station_day_submits_at_most_one_order_...` above) is proven
    at the unit level with a stubbed `submit_order` and never exercises a
    real fill; this is the ORDER claim AM-8 distinguishes from it, over a
    REAL matching engine.

    Geometry (all real market data, no stubbing): a pre-window
    `OrderBookDepth10` populates the exchange's own book without arming a
    hunt attempt (`outside_decision_window`, no `IN_FLIGHT`); an in-window
    `QuoteTick` at the window's opening instant drives `_hunt_tick` to
    submit an IOC that fills SYNCHRONOUSLY inside the engine's processing
    of that one data point (`BacktestEngine._process_and_settle_venues`
    drains the exchange's command queue on every `ts_init`, not on a
    deferred tick); a SECOND `OrderBookDepth10` frame just ONE nanosecond
    later probes the tightest boundary the engine can express. The
    strategy's own `IN_FLIGHT` flag (set at `:730`, before the order is
    even sent) already makes double-submission structurally impossible
    regardless of this ordering -- what this test measures is whether the
    fill's OWN delivery is visible (i.e. `on_order_filled` has already run)
    by the time that immediately-following frame is dispatched, which the
    measurement below confirms it is.

    Spies on the class methods (the strategy instance is constructed
    inside `backtest()`, so there is no instance to patch beforehand).

    Two dead ends measured en route to this geometry, kept here because
    each is a real engine fact worth not re-discovering (LOW finding #3):
    (1) a depth frame whose OWN just-arrived ask is the ONLY liquidity in
    the book NEVER fills when `_hunt_tick` reacts to that SAME frame -- the
    resulting IOC is CANCELED every time, regardless of whether an earlier,
    separate, out-of-window depth frame had already announced the identical
    price/size. Same-tick self-liquidity does not fill. (2) a genuinely
    one-sided `OrderBookDepth10` (`bids=()`, the pad-only shape every
    direct-call unit test above uses) also never fills through a REAL
    `SimulatedExchange`, even when fed as a separate, earlier, book-
    populating frame -- the direct-call tests never notice because they
    stub `submit_order` and never reach real matching. Neither is an AM-8
    ordering finding; both are prerequisites this test's final geometry
    (two-sided book, quote-triggered fill) had to route around to measure
    the actual question: whether the fill is visible before the very next
    frame."""
    interior_instrument.info["fee_coefficient"] = "0.06"
    call_order: list[str] = []
    original_on_filled = ContinuousRungHoldBacktestStrategy.on_order_filled
    original_on_depth = ContinuousRungHoldBacktestStrategy.on_order_book_depth

    def _spy_on_filled(self: ContinuousRungHoldBacktestStrategy, event: OrderFilled) -> None:
        call_order.append("on_order_filled")
        original_on_filled(self, event)

    def _spy_on_depth(
        self: ContinuousRungHoldBacktestStrategy, depth: OrderBookDepth10,
    ) -> None:
        call_order.append(f"on_order_book_depth:{depth.ts_event}")
        original_on_depth(self, depth)

    monkeypatch.setattr(ContinuousRungHoldBacktestStrategy, "on_order_filled", _spy_on_filled)
    monkeypatch.setattr(
        ContinuousRungHoldBacktestStrategy, "on_order_book_depth", _spy_on_depth,
    )

    depth_pre_ts = WINDOW_OPEN_NS - 1_000
    quote_ts = WINDOW_OPEN_NS
    depth_post_ts = WINDOW_OPEN_NS + 1
    depth_pre = _depth(
        INTERIOR_ID, bids=(("0.01", 10),), asks=(("0.40", 10),), ts_event=depth_pre_ts,
    )
    quote = _quote(INTERIOR_ID, ask="0.40", ts_event=quote_ts)
    depth_post = _depth(
        INTERIOR_ID, bids=(("0.01", 10),), asks=(("0.40", 10),), ts_event=depth_post_ts,
    )
    observation = _observation(
        temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 5 * NS_PER_MIN,
    )
    config = build_paper_replay_config(
        instruments=[interior_instrument],
        market_data=[depth_pre, quote, depth_post],
        weather_data=as_backtest_data([observation]),
        starting_balances=(Money(10_000, USD),),
        capture_window_ns=(depth_pre_ts, depth_post_ts),
        instruments_without_close=frozenset({interior_instrument.id}),
    )
    strategy = ContinuousRungHoldBacktestStrategy(
        CurrentRungHoldConfig(instrument_ids=(interior_instrument.id,)),
        trial_day_latch_factory=_cont_latch_factory(store_path),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    with backtest(
        config, strategies=(strategy,), allow_idle_strategies=True, allow_open_positions=True,
    ) as engine:
        ctx = ReplayEntryContext(
            station=STATION,
            climate_day=CLIMATE_DAY.isoformat(),
            bucket=None,
            entry_ask=Decimal("0.40"),
            scheduled_release_at_ns=WINDOW_OPEN_NS + 7 * 24 * 3_600_000_000_000,
        )
        trials = filled_trials_from_engine(
            engine,
            {str(interior_instrument.id): ctx},
            family_id=UNSCOPED_FAMILY_ID,
            trial_id_prefix=CONTINUOUS_TRIAL_KEY_PREFIX,
        )

    assert len(trials) == 1
    assert call_order == [
        f"on_order_book_depth:{depth_pre_ts}",
        "on_order_filled",
        f"on_order_book_depth:{depth_post_ts}",
    ], (
        "MEASURED interleave differs from the expected fill-before-next-"
        f"frame order -- call_order={call_order!r}"
    )


# ---------------------------------------------------------------------------
# AM-5: the literal-name scan and the dynamic-import exact-set count
# ---------------------------------------------------------------------------


def _literal_target_hit(path: Path) -> bool:
    """AST-based, like `CX-B4`'s executable-construction check: a docstring
    or comment mentioning the class/module by name (e.g. this module's own
    docstring, or `continuous_strategy.py::_submission_armed`'s docstring
    pointing forward to it) is prose, not code, and must NOT count -- only
    a real `Name` reference or a non-docstring string `Constant` (the shape
    a smuggled `getattr`/dynamic-import call site would take) counts."""
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except SyntaxError:
        return False
    docstring_ids = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == _TARGET_NAME:
            return True
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstring_ids
            and node.value in (_TARGET_NAME, _TARGET_MODULE)
        ):
            return True
    return False


def test_the_subclass_name_and_module_appear_in_no_other_source_file() -> None:
    """A subset-of-allowlist check (never a hand-edited exact match) so this
    stays GREEN both before increment C wires the driver (0 hits) and after
    (exactly the one authorised importer, per acceptance item 7's "2-file
    allowlist": this module's own file plus the driver)."""
    hits = []
    for root_dir in ("src", "scripts"):
        base = _REPO_ROOT / root_dir
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if path == _TARGET_FILE:
                continue
            if _literal_target_hit(path):
                hits.append(str(path.relative_to(_REPO_ROOT)))
    assert set(hits) <= {_EXPECTED_IMPORTER}, (
        f"{_TARGET_NAME}/{_TARGET_MODULE} referenced outside the allowlist: {hits!r}"
    )


def _dynamic_import_call_site_count(path: Path) -> int:
    tree = ast.parse(path.read_text(), filename=str(path))
    count = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "__import__" or (
            isinstance(func, ast.Attribute)
            and func.attr == "import_module"
            and isinstance(func.value, ast.Name)
            and func.value.id == "importlib"
        ):
            count += 1
    return count


def test_the_dynamic_import_call_site_count_is_unchanged() -> None:
    """AM-5/L-12: increment C selects `strategy_cls` via an explicit
    `if strategy_cls is ContinuousRungHoldBacktestStrategy:` branch, never
    `getattr`/dynamic-import duck-typing -- the driver's own dynamic-import
    call-site count (measured now, at B, as zero) must stay exactly what it
    is today through every later increment."""
    assert (
        _dynamic_import_call_site_count(_DRIVER_FILE)
        == _BASELINE_DYNAMIC_IMPORT_CALL_SITES
    )


# ---------------------------------------------------------------------------
# INC-7: `install_position_monitor` runs the shadow monitor inside the v3
# paper-replay harness, under a REAL BacktestEngine `TestClock` (plan §6
# INC-7, Rev 2.1 addendum M3).
# ---------------------------------------------------------------------------

#: 32.0C -> 89.6F, round-half-up to 90F -- strictly above the fixture rung's
#: `upper_f=87`, so two readings at this value confirm DEAD (>= 5 min apart).
_DEAD_TEMP_C_TENTHS = 320
_DEAD_CONFIRM_SPAN_MIN = 6  # >= monitor_decision._DEAD_MIN_CONFIRM_SPAN_NS (5 min)


def _query_mark_rows(catalog: Any) -> list[PositionMarkRecord]:
    """Unwraps `CustomData`, mirroring `quote_tape_gaps.py::_query_gap_rows`
    -- a `ParquetDataCatalog.query(data_cls=...)` call for a hand-written
    `Data` subclass returns `CustomData` wrappers, not the bare record."""
    rows: list[PositionMarkRecord] = []
    for item in catalog.query(data_cls=PositionMarkRecord):
        if isinstance(item, PositionMarkRecord):
            rows.append(item)
        elif isinstance(item, CustomData) and isinstance(item.data, PositionMarkRecord):
            rows.append(item.data)
        else:  # pragma: no cover - defensive against Nautilus API drift
            raise TypeError(
                "expected PositionMarkRecord rows from Nautilus catalog query, "
                f"got {type(item).__name__}"
            )
    return rows


def _run_fill_then_monitor(
    *,
    store_path: Path,
    interior_instrument: BinaryOption,
    driver: ModuleType | None,
    out_dir: Path | None,
    extra_weather_observations: tuple[Any, ...] = (),
) -> tuple[ContinuousRungHoldBacktestStrategy, tuple[Any, ...], int]:
    """The exact fill geometry from
    `test_a_fill_is_delivered_before_the_next_depth_frame_is_handled`
    (pre-window depth, an in-window quote that triggers the fill, then a
    post-window depth), optionally with `out_dir`'s `PositionMonitor`
    installed via `driver.install_position_monitor` and extra post-fill
    weather rows appended. Returns the stopped strategy, the filled trials,
    and `final_ts` -- the latest `ts_event`/`observed_at_ns` fed to the
    engine across every market and weather record, i.e. the true upper
    bound no mark may look ahead of.
    """
    interior_instrument.info["fee_coefficient"] = "0.06"
    depth_pre_ts = WINDOW_OPEN_NS - 1_000
    quote_ts = WINDOW_OPEN_NS
    depth_post_ts = WINDOW_OPEN_NS + 1
    depth_pre = _depth(
        INTERIOR_ID, bids=(("0.01", 10),), asks=(("0.40", 10),), ts_event=depth_pre_ts,
    )
    quote = _quote(INTERIOR_ID, ask="0.40", ts_event=quote_ts)
    depth_post = _depth(
        INTERIOR_ID, bids=(("0.01", 10),), asks=(("0.40", 10),), ts_event=depth_post_ts,
    )
    observation = _observation(
        temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 5 * NS_PER_MIN,
    )
    weather = (observation, *extra_weather_observations)
    final_ts = max(
        depth_pre_ts,
        quote_ts,
        depth_post_ts,
        *(row.observed_at_ns for row in weather),
        *(row.received_at_ns for row in weather),
    )
    config = build_paper_replay_config(
        instruments=[interior_instrument],
        market_data=[depth_pre, quote, depth_post],
        weather_data=as_backtest_data(list(weather)),
        starting_balances=(Money(10_000, USD),),
        capture_window_ns=(depth_pre_ts, depth_post_ts),
        instruments_without_close=frozenset({interior_instrument.id}),
    )
    strategy = ContinuousRungHoldBacktestStrategy(
        CurrentRungHoldConfig(instrument_ids=(interior_instrument.id,)),
        trial_day_latch_factory=_cont_latch_factory(store_path),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    if out_dir is not None:
        assert driver is not None
        driver.install_position_monitor(
            strategy, out_dir=out_dir, clock_ns=lambda: strategy.clock.timestamp_ns(),
        )
    with backtest(
        config, strategies=(strategy,), allow_idle_strategies=True, allow_open_positions=True,
    ) as engine:
        ctx = ReplayEntryContext(
            station=STATION,
            climate_day=CLIMATE_DAY.isoformat(),
            bucket=None,
            entry_ask=Decimal("0.40"),
            scheduled_release_at_ns=WINDOW_OPEN_NS + 7 * 24 * 3_600_000_000_000,
        )
        trials = filled_trials_from_engine(
            engine,
            {str(interior_instrument.id): ctx},
            family_id=UNSCOPED_FAMILY_ID,
            trial_id_prefix=CONTINUOUS_TRIAL_KEY_PREFIX,
        )
    assert len(trials) == 1
    return strategy, trials, final_ts


def test_a_fill_with_the_monitor_installed_emits_a_queryable_mark_and_summary(
    store_path: Path, interior_instrument: BinaryOption, tmp_path: Path,
    paper_replay_driver: ModuleType,
) -> None:
    out_dir = tmp_path / "monitor_out"
    _strategy, _trials, final_ts = _run_fill_then_monitor(
        store_path=store_path,
        interior_instrument=interior_instrument,
        driver=paper_replay_driver,
        out_dir=out_dir,
    )

    catalog = open_monitor_catalog(out_dir / "monitor", CLIMATE_DAY.isoformat())
    marks = _query_mark_rows(catalog)
    assert len(marks) >= 1

    summaries = read_monitor_summaries(out_dir / "monitor_summaries")
    assert len(summaries) >= 1

    ts_inits = [mark.ts_init for mark in marks]
    assert ts_inits == sorted(ts_inits), f"ts_init not non-decreasing: {ts_inits!r}"
    assert all(mark.ts_event <= final_ts for mark in marks), (
        f"a mark's ts_event exceeds final_ts={final_ts}: "
        f"{[mark.ts_event for mark in marks]!r}"
    )


def test_the_monitor_installed_or_not_yields_identical_fills_and_latch_state(
    tmp_path: Path, paper_replay_driver: ModuleType,
) -> None:
    """D3 (plan §2): installing the shadow monitor must never change what
    the strategy actually does -- same fill, same latch state, whether or
    not `out_dir` is passed."""
    with_monitor_instrument = _instrument(INTERIOR_ID, lower_f=86, upper_f=87)
    without_monitor_instrument = _instrument(INTERIOR_ID, lower_f=86, upper_f=87)
    with_store = tmp_path / "with_monitor" / "state.db"
    without_store = tmp_path / "without_monitor" / "state.db"

    _with_strategy, with_trials, _ = _run_fill_then_monitor(
        store_path=with_store,
        interior_instrument=with_monitor_instrument,
        driver=paper_replay_driver,
        out_dir=tmp_path / "monitor_out",
    )
    _without_strategy, without_trials, _ = _run_fill_then_monitor(
        store_path=without_store,
        interior_instrument=without_monitor_instrument,
        driver=None,
        out_dir=None,
    )

    assert len(with_trials) == len(without_trials) == 1
    assert with_trials[0].entry_ask == without_trials[0].entry_ask
    assert with_trials[0].fill_px == without_trials[0].fill_px

    with _cont_latch_factory(with_store)() as with_latch:
        with_state = with_latch.attempt_state(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID),
        )
        with_consumed = with_latch.is_consumed(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID),
        )
    with _cont_latch_factory(without_store)() as without_latch:
        without_state = without_latch.attempt_state(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID),
        )
        without_consumed = without_latch.is_consumed(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID),
        )
    assert with_state == without_state
    assert with_consumed == without_consumed is True


def test_a_dead_scenario_in_replay_yields_an_exit_or_missing_stop_mark(
    store_path: Path, interior_instrument: BinaryOption, tmp_path: Path,
    paper_replay_driver: ModuleType,
) -> None:
    """Two post-fill observations pushing the running max past `rung_high`
    (87), spaced >= the 5-minute DEAD confirmation guard, must confirm
    `DEAD_BY_OBSERVATION` and emit a verdict of `EXIT_RECOMMENDED` or
    `MISSING_STOP` -- never silently absorbed as `HOLD` (L-38)."""
    out_dir = tmp_path / "monitor_out"
    first_dead = _observation(
        temp_c_tenths=_DEAD_TEMP_C_TENTHS, observed_at_ns=WINDOW_OPEN_NS + 2 * NS_PER_MIN,
    )
    second_dead = _observation(
        temp_c_tenths=_DEAD_TEMP_C_TENTHS,
        observed_at_ns=WINDOW_OPEN_NS + (2 + _DEAD_CONFIRM_SPAN_MIN) * NS_PER_MIN,
    )
    _strategy, _trials, _final_ts = _run_fill_then_monitor(
        store_path=store_path,
        interior_instrument=interior_instrument,
        driver=paper_replay_driver,
        out_dir=out_dir,
        extra_weather_observations=(first_dead, second_dead),
    )

    catalog = open_monitor_catalog(out_dir / "monitor", CLIMATE_DAY.isoformat())
    marks = _query_mark_rows(catalog)
    dead_marks = [mark for mark in marks if mark.thesis_state == "DEAD_BY_OBSERVATION"]
    assert dead_marks, f"no DEAD_BY_OBSERVATION mark among {[m.thesis_state for m in marks]!r}"
    assert all(mark.verdict in ("EXIT_RECOMMENDED", "MISSING_STOP") for mark in dead_marks)


def test_a_stable_scenario_in_replay_yields_only_hold_marks(
    store_path: Path, interior_instrument: BinaryOption, tmp_path: Path,
    paper_replay_driver: ModuleType,
) -> None:
    """No post-fill temperature ever leaves the rung -- every emitted mark
    must stay `ALIVE`/`HOLD`, never a THREATENED/DEAD reason code."""
    out_dir = tmp_path / "monitor_out"
    _strategy, _trials, _final_ts = _run_fill_then_monitor(
        store_path=store_path,
        interior_instrument=interior_instrument,
        driver=paper_replay_driver,
        out_dir=out_dir,
    )

    catalog = open_monitor_catalog(out_dir / "monitor", CLIMATE_DAY.isoformat())
    marks = _query_mark_rows(catalog)
    assert len(marks) >= 1
    assert all(mark.thesis_state == "ALIVE" for mark in marks)
    assert all(mark.verdict == "HOLD" for mark in marks)
