"""SP-4 increment B: `ContinuousRungHoldBacktestStrategy` -- the v3
paper-replay driver's ONLY continuous-hunt subclass.

Reuses the real-store harness from `test_continuous_rung_hold_strategy.py`
(itself reusing `test_current_rung_hold_strategy.py`'s fixtures), the same
pattern `test_current_rung_hold_backtest_only.py` uses for the v2 subclass.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.common.component import TestClock
from nautilus_trader.model.identifiers import TraderId
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.portfolio import Portfolio
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

import breezy.strategy.current_rung_hold.continuous_backtest_only as continuous_backtest_only_module
from breezy.adapters.polymarket_us.exec import submit_chain
from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
from breezy.strategy.current_rung_hold.continuous_backtest_only import (
    ContinuousNotABacktestClockError,
    ContinuousRungHoldBacktestStrategy,
)
from breezy.strategy.current_rung_hold.continuous_strategy import _REARM_MIN_DELAY_NS
from breezy.strategy.current_rung_hold.offer_tape import OfferTape
from tests.unit.test_continuous_rung_hold_strategy import (
    _PERMISSIVE_EVIDENCE,
    _cont_latch_factory,
    _depth,
    _order_denied,
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


# ---------------------------------------------------------------------------
# B-1: the AST exact-set method pin (L-12 widen-never-relax)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# on_start: the TestClock barrier, the never-arm walk, L-24 negatives
# ---------------------------------------------------------------------------


def test_on_start_refuses_a_non_testclock(
    store_path: Path,
    interior_instrument: BinaryOption,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """NB-2: asserts BOTH the raise AND the `log.error` call -- one line
    strictly more visible than the v2 precedent, defence in depth.
    `Strategy.log` is a Nautilus Cython `Logger` (an immutable extension
    type -- `strategy.log.error = ...` raises `AttributeError: ... is
    read-only`), so the ERROR line is observed at the OS file-descriptor
    level (`capfd`), the same layer Nautilus's own logger writes to."""
    strategy = _register_backtest(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    monkeypatch.setattr(continuous_backtest_only_module, "TestClock", str)
    capfd.readouterr()  # drain anything buffered from registration
    with pytest.raises(ContinuousNotABacktestClockError):
        strategy.on_start()
    # Nautilus's Rust-backed logger writes on its own background thread --
    # a short, bounded wait for the flush, never a retry loop on content.
    time.sleep(0.1)
    captured = capfd.readouterr()
    assert "ERROR" in captured.err
    assert _TARGET_NAME in captured.err


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
    strategy.stop = lambda: stopped.append(True)  # type: ignore[method-assign]
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
    strategy.stop = lambda: stopped.append(True)  # type: ignore[method-assign]
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
    strategy.submit_order = submitted.append  # type: ignore[method-assign]
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


def test_one_station_day_submits_at_most_one_order_across_many_eligible_depth_frames(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """INVARIANT: IN_FLIGHT is never auto-cleared on the armed branch (site
    :734), so many later eligible frames on the SAME station-day must never
    produce a second `submit_order` absent a WAIT-class deny."""
    strategy = _register_backtest_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    submitted: list[object] = []
    strategy.submit_order = submitted.append  # type: ignore[method-assign]
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    for i in range(10):
        depth = _depth(
            INTERIOR_ID,
            bids=(),
            asks=(("0.40", 10),),
            ts_event=WINDOW_OPEN_NS + i * NS_PER_MIN,
        )
        strategy.on_order_book_depth(depth)
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
    strategy.submit_order = submitted.append  # type: ignore[method-assign]

    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))
    assert strategy._latch is not None
    assert strategy._latch.attempt_state(STATION, CLIMATE_DAY.isoformat()) == (
        1,
        WINDOW_OPEN_NS,
    )
    assert len(submitted) == 1
    assert strategy._latch.is_inflight(STATION, CLIMATE_DAY.isoformat()) is True

    # The clear itself is pinned by the shipped `:459` test; this is the
    # precondition for the next step, not the assertion under test here.
    strategy.on_order_denied(
        _order_denied(strategy, reason=submit_chain.OPEN_INTENT_WAIT_REASON),
    )
    assert strategy._latch.is_inflight(STATION, CLIMATE_DAY.isoformat()) is False

    second_ts = WINDOW_OPEN_NS + _REARM_MIN_DELAY_NS + 1
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=second_ts))
    assert strategy._latch.attempt_state(STATION, CLIMATE_DAY.isoformat()) == (
        2,
        second_ts,
    )
    assert len(submitted) == 2


@pytest.mark.xfail(
    reason=(
        "AM-8 (F0 row 6, R11): SimulatedExchange.process-vs-next-depth-frame "
        "ordering was not measured in this implementation pass (no real "
        "BacktestEngine harness was built here to observe it) -- marked "
        "UNSETTLED per the plan's own escape hatch rather than asserted on "
        "unmeasured ground. The at-most-one INVARIANT test above already "
        "covers the safety property regardless of the interleave order."
    ),
    strict=True,
)
def test_a_fill_is_delivered_before_the_next_depth_frame_is_handled_is_UNSETTLED() -> None:
    raise NotImplementedError(
        "ordering probe requires a real BacktestEngine/SimulatedExchange run; "
        "not built in this pass (see the xfail reason)",
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
