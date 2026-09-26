"""RED-first tests for the intra-day position monitor orchestrator (INC-5).

Per ``docs/plans/INTRADAY_POSITION_MONITOR_2026-09-15.md`` §2 (strategy
diff items 1-6), §3, §6 INC-5, §7, and the Rev 2.1 addendum items A1/A3,
plus the 2026-09-15 REQUIRED ADJUSTMENT (DEAD confirmation keyed on the
observation's own ``observed_at_ns``, never the evaluation ``ts_ns``).

Two layers: isolated ``PositionMonitor`` unit tests driven with plain stub
callables (fast, precise -- exercises the M7 D3 pin directly), and a few
integration tests wiring a real ``PositionMonitor`` onto a real
``ContinuousRungHoldStrategy`` the same way ``composition.py`` does.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from nautilus_trader.model.data import BookOrder, OrderBookDepth10
from nautilus_trader.model.enums import OmsType, OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.model.position import Position
from nautilus_trader.test_kit.stubs.events import TestEventStubs

from breezy.adapters.polymarket_us.symbology import sibling_instrument_id
from breezy.strategy.current_rung_hold.monitor_decision import (
    MonitorDecision,
    MonitorHistory,
    ThesisState,
    Verdict,
    evaluate_monitor,
)
from breezy.strategy.current_rung_hold.monitor_evidence import MonitorEvidence, walk_exit_vwap
from breezy.strategy.current_rung_hold.monitor_store import (
    MarkBuffer,
    read_monitor_summaries,
)
from breezy.strategy.current_rung_hold.monitor_wiring import build_monitor_callables
from breezy.strategy.current_rung_hold.position_monitor import PositionMonitor
from breezy.strategy.current_rung_hold.trial_day_latch import (
    CONTINUOUS_TRIAL_KEY_PREFIX,
    trial_id_for,
)
from tests.unit.test_continuous_rung_hold_fill_wiring import _fill
from tests.unit.test_continuous_rung_hold_strategy import (
    _register,
    _register_and_start,
)
from tests.unit.test_current_rung_hold_strategy import (
    CLIMATE_DAY,
    INTERIOR_ID,
    STATION,
    WINDOW_OPEN_NS,
    _instrument,
    _observation,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from breezy.persistence.family_manifest import FamilyManifest

_MINUTE_NS = 60_000_000_000
_STALE_BOUND_NS = 50 * _MINUTE_NS
_IID = str(INTERIOR_ID)


# ---------------------------------------------------------------------------
# Stub building blocks for the isolated `PositionMonitor` tests
# ---------------------------------------------------------------------------


@dataclass
class _FakePosition:
    instrument_id: str
    avg_px_open: float
    quantity: int
    #: INC-E3: additive -- `PositionMonitor._register` reads `position.id`
    #: (a real Nautilus `Position` always has one) to populate
    #: `_MonitoredPosition.position_id` for the exit decider/`submit_exit`.
    #: Every existing call site omits this and gets the default, unchanged.
    id: str = "P-FAKE-1"


@dataclass
class _FakeFacts:
    lower_f: int | None
    upper_f: int | None


@dataclass
class _FakeRunningMax:
    lower_f: int
    upper_f: int
    source_observed_at_ns: int


class _RecordingAccumulator:
    """Exposes ONLY `value_at`/`staleness_ns` -- the M7 D3 pin's allowlist."""

    def __init__(self, running_max: _FakeRunningMax | None, staleness: int | None = 0) -> None:
        self._running_max = running_max
        self._staleness = staleness
        self.value_at_calls = 0
        self.staleness_calls = 0

    def value_at(self, now_ns: int) -> _FakeRunningMax | None:
        self.value_at_calls += 1
        return self._running_max

    def staleness_ns(self, now_ns: int) -> int | None:
        self.staleness_calls += 1
        return self._staleness


class _StrictAccumulator(_RecordingAccumulator):
    """Raises on any attribute the monitor is not allowed to touch."""

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"PositionMonitor touched disallowed accumulator attribute: {name}")


class _PositionsOpenStub:
    def __init__(self) -> None:
        self.by_iid: dict[str, list[_FakePosition]] = {}

    def set(self, iid: str, positions: list[_FakePosition]) -> None:
        self.by_iid[iid] = positions

    def __call__(self, iid: str) -> Sequence[_FakePosition]:
        return self.by_iid.get(iid, [])


def _build_monitor(
    tmp_path: Path,
    *,
    positions_open: Callable[[str], Sequence[object]],
    accumulators: Mapping[str, object],
    latch_record: Callable[..., object | None] = lambda *a, **k: None,
    rung_geometry: Callable[[str], object | None] = lambda iid: _FakeFacts(
        lower_f=86, upper_f=87,
    ),
    fee_coefficient_for: Callable[[str], Decimal] = lambda iid: Decimal("0.06"),
    leg_for: Callable[[str], str] = lambda iid: "YES",
    station_for: Callable[[str], str] = lambda iid: STATION,
    climate_day_for: Callable[[str], str] = lambda iid: CLIMATE_DAY.isoformat(),
    hour_lst_for: Callable[[str, int], int] = lambda station, now_ns: 14,
    report: Callable[[str, Mapping[str, object]], None] | None = None,
    clock_ns: Callable[[], int] = lambda: WINDOW_OPEN_NS,
    sibling_for: Callable[[str], str | None] | None = None,
    buffer: MarkBuffer | None = None,
    exit_decider: Callable[..., object] | None = None,
    exit_manifest: object | None = None,
    exit_family_id: str | None = None,
    exit_client_order_id_factory: Callable[[], str] | None = None,
    submit_exit: Callable[..., None] | None = None,
    record_exit_offer: Callable[..., None] | None = None,
) -> tuple[PositionMonitor, list[tuple[str, Mapping[str, object]]]]:
    reports: list[tuple[str, Mapping[str, object]]] = []

    def _default_report(event: str, detail: Mapping[str, object]) -> None:
        reports.append((event, detail))

    monitor = PositionMonitor(
        clock_ns=clock_ns,
        positions_open=positions_open,  # type: ignore[arg-type]
        accumulators=accumulators,  # type: ignore[arg-type]
        latch_record=latch_record,
        rung_geometry=rung_geometry,  # type: ignore[arg-type]
        fee_coefficient_for=fee_coefficient_for,
        leg_for=leg_for,  # type: ignore[arg-type]
        station_for=station_for,
        climate_day_for=climate_day_for,
        hour_lst_for=hour_lst_for,
        stale_observation_bound_ns=_STALE_BOUND_NS,
        trial_id_prefix=CONTINUOUS_TRIAL_KEY_PREFIX,
        buffer=buffer if buffer is not None else MarkBuffer(),
        catalog_root=tmp_path / "monitor",
        summaries_dir=tmp_path / "monitor" / "summaries",
        report=report if report is not None else _default_report,
        sibling_for=sibling_for,
        exit_decider=exit_decider,  # type: ignore[arg-type]
        exit_manifest=exit_manifest,  # type: ignore[arg-type]
        exit_family_id=exit_family_id,
        exit_client_order_id_factory=exit_client_order_id_factory,
        submit_exit=submit_exit,
        record_exit_offer=record_exit_offer,
    )
    return monitor, reports


class _FakeDepth:
    """Only `instrument_id`/`ts_event` are read by `PositionMonitor.on_depth`
    before it hands the object straight through to `build_monitor_evidence`
    (which is exercised end to end by the INC-2 test suite, not here)."""

    def __init__(self, instrument_id: str, ts_event: int) -> None:
        self.instrument_id = instrument_id
        self.ts_event = ts_event
        self.bids: list[object] = []
        self.asks: list[object] = []


def _book_order(side: OrderSide, price: str, size: str) -> BookOrder:
    return BookOrder(side, Price(float(price), 2), Quantity(float(size), 2), 0)


def _book_depth10(
    *,
    instrument_id: InstrumentId,
    bids: tuple[tuple[str, str], ...],
    asks: tuple[tuple[str, str], ...],
    ts_ns: int,
) -> OrderBookDepth10:
    """A REAL `OrderBookDepth10` (never `_FakeDepth`'s empty stub), for the
    FU-1d sibling-routing tests below that actually walk `depth.bids`/
    `depth.asks` through `walk_exit_vwap`. Same zero-size-filler shape as
    `test_current_rung_hold_monitor_evidence.py`'s own `_depth` helper --
    Nautilus requires equal bid/ask lengths."""
    bid_orders = [_book_order(OrderSide.BUY, p, s) for p, s in bids]
    ask_orders = [_book_order(OrderSide.SELL, p, s) for p, s in asks]
    n = max(len(bid_orders), len(ask_orders))
    while len(bid_orders) < n:
        bid_orders.append(_book_order(OrderSide.BUY, "0", "0"))
    while len(ask_orders) < n:
        ask_orders.append(_book_order(OrderSide.SELL, "0", "0"))
    return OrderBookDepth10(
        instrument_id=instrument_id,
        bids=bid_orders,
        asks=ask_orders,
        bid_counts=[1] * len(bid_orders),
        ask_counts=[1] * len(ask_orders),
        flags=0,
        sequence=0,
        ts_event=ts_ns,
        ts_init=ts_ns,
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_on_position_opened_registers_and_a_later_depth_evaluates(tmp_path: Path) -> None:
    positions = _PositionsOpenStub()
    positions.set(_IID, [_FakePosition(instrument_id=_IID, avg_px_open=0.40, quantity=1)])
    accumulator = _RecordingAccumulator(
        _FakeRunningMax(lower_f=85, upper_f=85, source_observed_at_ns=WINDOW_OPEN_NS),
    )
    monitor, _reports = _build_monitor(
        tmp_path, positions_open=positions, accumulators={STATION: accumulator},
    )

    fake_position = _FakePosition(instrument_id=_IID, avg_px_open=0.40, quantity=1)
    monitor.on_position_opened(fake_position, WINDOW_OPEN_NS)  # type: ignore[arg-type]
    assert monitor.counters["monitor_errors"] == 0

    monitor.on_depth(_FakeDepth(_IID, WINDOW_OPEN_NS + _MINUTE_NS), WINDOW_OPEN_NS + _MINUTE_NS)  # type: ignore[arg-type]

    assert monitor.counters["monitor_errors"] == 0
    assert monitor.counters["evaluations"] == 1


def test_a_boot_inherited_position_lazily_registers_as_reconciled_no_record(
    tmp_path: Path,
) -> None:
    """B3: no `on_position_opened` ever fires for this instrument -- the
    FIRST depth frame must lazily register it, with no `TrialDayRecord` on
    record, as `reconciled_no_record` (never crash, never `p_hold_at_entry`
    fabricated)."""
    positions = _PositionsOpenStub()
    positions.set(_IID, [_FakePosition(instrument_id=_IID, avg_px_open=0.40, quantity=1)])
    accumulator = _RecordingAccumulator(
        _FakeRunningMax(lower_f=85, upper_f=85, source_observed_at_ns=WINDOW_OPEN_NS),
    )
    monitor, _reports = _build_monitor(
        tmp_path, positions_open=positions, accumulators={STATION: accumulator},
    )

    monitor.on_depth(_FakeDepth(_IID, WINDOW_OPEN_NS), WINDOW_OPEN_NS)  # type: ignore[arg-type]
    monitor.on_stop(WINDOW_OPEN_NS + _MINUTE_NS)

    summaries = read_monitor_summaries(tmp_path / "monitor" / "summaries")
    assert len(summaries) == 1
    assert summaries[0].entry_context == "reconciled_no_record"
    assert summaries[0].trial_id == trial_id_for(
        CONTINUOUS_TRIAL_KEY_PREFIX, STATION, CLIMATE_DAY.isoformat(), _IID,
    )


def test_negative_trial_day_record_lookup_is_cached_per_instrument_climate_day(
    tmp_path: Path,
) -> None:
    """A3 (Rev 2.1 addendum): a genuine "no record" answer is cached for the
    process lifetime -- a SECOND registration attempt for the same
    (instrument, climate_day) must never re-consult `latch_record`."""
    calls: list[tuple[str, str]] = []

    def _latch_record(station: str, climate_day: str, *, key_instrument_id: str | None = None):
        calls.append((station, climate_day))

    positions = _PositionsOpenStub()
    positions.set(_IID, [_FakePosition(instrument_id=_IID, avg_px_open=0.40, quantity=1)])
    accumulator = _RecordingAccumulator(
        _FakeRunningMax(lower_f=85, upper_f=85, source_observed_at_ns=WINDOW_OPEN_NS),
    )
    monitor, _reports = _build_monitor(
        tmp_path,
        positions_open=positions,
        accumulators={STATION: accumulator},
        latch_record=_latch_record,
    )

    monitor._ensure_registered(_IID, WINDOW_OPEN_NS)  # first registration: one lookup
    assert calls == [(STATION, CLIMATE_DAY.isoformat())]

    # Simulate a hypothetical SECOND registration attempt for the same
    # instrument-day (the live call pattern never re-registers an already
    # -tracked instrument; this directly characterises the cache itself).
    monitor._positions.pop(_IID)
    monitor._ensure_registered(_IID, WINDOW_OPEN_NS)
    assert calls == [(STATION, CLIMATE_DAY.isoformat())]  # never a second lookup


def test_accumulator_access_is_limited_to_value_at_and_staleness_ns(tmp_path: Path) -> None:
    """M7 D3 pin: `PositionMonitor` must never call `push`/`coverage`/
    `earliest_observed_ns` on an injected accumulator -- only the two
    read-only queries. A stub that raises on any other attribute must see
    ZERO monitor errors across a realistic drive (registration + several
    depth/observation evaluations)."""
    positions = _PositionsOpenStub()
    positions.set(_IID, [_FakePosition(instrument_id=_IID, avg_px_open=0.40, quantity=1)])
    accumulator = _StrictAccumulator(
        _FakeRunningMax(lower_f=85, upper_f=85, source_observed_at_ns=WINDOW_OPEN_NS),
    )
    monitor, reports = _build_monitor(
        tmp_path, positions_open=positions, accumulators={STATION: accumulator},
    )

    monitor.on_depth(_FakeDepth(_IID, WINDOW_OPEN_NS), WINDOW_OPEN_NS)  # type: ignore[arg-type]
    monitor.on_observation(STATION, WINDOW_OPEN_NS + _MINUTE_NS)
    monitor.on_depth(  # type: ignore[arg-type]
        _FakeDepth(_IID, WINDOW_OPEN_NS + 2 * _MINUTE_NS), WINDOW_OPEN_NS + 2 * _MINUTE_NS,
    )

    assert monitor.counters["monitor_errors"] == 0, reports
    assert accumulator.value_at_calls > 0
    assert accumulator.staleness_calls > 0


def test_held_qty_is_read_fresh_on_every_evaluation(tmp_path: Path) -> None:
    positions = _PositionsOpenStub()
    positions.set(_IID, [_FakePosition(instrument_id=_IID, avg_px_open=0.40, quantity=1)])
    accumulator = _RecordingAccumulator(
        _FakeRunningMax(lower_f=85, upper_f=85, source_observed_at_ns=WINDOW_OPEN_NS),
    )
    monitor, _reports = _build_monitor(
        tmp_path, positions_open=positions, accumulators={STATION: accumulator},
    )
    monitor.on_depth(_FakeDepth(_IID, WINDOW_OPEN_NS), WINDOW_OPEN_NS)  # type: ignore[arg-type]

    # MP-A style qty bump: a second leg fills before the next evaluation.
    positions.set(_IID, [_FakePosition(instrument_id=_IID, avg_px_open=0.40, quantity=2)])
    monitor.on_depth(  # type: ignore[arg-type]
        _FakeDepth(_IID, WINDOW_OPEN_NS + _MINUTE_NS), WINDOW_OPEN_NS + _MINUTE_NS,
    )
    monitor.on_stop(WINDOW_OPEN_NS + 2 * _MINUTE_NS)

    summaries = read_monitor_summaries(tmp_path / "monitor" / "summaries")
    assert summaries[0].held_qty == Decimal(2)


def test_emission_happens_only_on_state_change_or_heartbeat(tmp_path: Path) -> None:
    positions = _PositionsOpenStub()
    positions.set(_IID, [_FakePosition(instrument_id=_IID, avg_px_open=0.40, quantity=1)])
    accumulator = _RecordingAccumulator(
        _FakeRunningMax(lower_f=85, upper_f=85, source_observed_at_ns=WINDOW_OPEN_NS),
    )
    monitor, _reports = _build_monitor(
        tmp_path, positions_open=positions, accumulators={STATION: accumulator},
    )
    monitor.on_depth(_FakeDepth(_IID, WINDOW_OPEN_NS), WINDOW_OPEN_NS)  # type: ignore[arg-type]
    assert monitor.counters["emitted"] == 1  # first evaluation always emits

    # An immediate second evaluation with an unchanged state/verdict and no
    # heartbeat elapsed must NOT emit a second mark.
    monitor.on_depth(  # type: ignore[arg-type]
        _FakeDepth(_IID, WINDOW_OPEN_NS + 1_000), WINDOW_OPEN_NS + 1_000,
    )
    assert monitor.counters["evaluations"] == 2
    assert monitor.counters["emitted"] == 1


def test_on_stop_flushes_marks_and_writes_a_summary(tmp_path: Path) -> None:
    positions = _PositionsOpenStub()
    positions.set(_IID, [_FakePosition(instrument_id=_IID, avg_px_open=0.40, quantity=1)])
    accumulator = _RecordingAccumulator(
        _FakeRunningMax(lower_f=85, upper_f=85, source_observed_at_ns=WINDOW_OPEN_NS),
    )
    monitor, _reports = _build_monitor(
        tmp_path, positions_open=positions, accumulators={STATION: accumulator},
    )
    monitor.on_depth(_FakeDepth(_IID, WINDOW_OPEN_NS), WINDOW_OPEN_NS)  # type: ignore[arg-type]

    monitor.on_stop(WINDOW_OPEN_NS + _MINUTE_NS)

    assert monitor.counters["flush_errors"] == 0
    summaries = read_monitor_summaries(tmp_path / "monitor" / "summaries")
    assert len(summaries) == 1
    assert summaries[0].monitor_seq == 1
    assert summaries[0].total_frames == 1


# ---------------------------------------------------------------------------
# DEAD confirmation keyed on `observed_at_ns` (the 2026-09-15 correction)
# ---------------------------------------------------------------------------


def _dead_candidate_evidence(*, ts_ns: int, observed_at_ns: int | None) -> MonitorEvidence:
    return MonitorEvidence(
        ts_ns=ts_ns,
        instrument_id=_IID,
        station=STATION,
        climate_day=CLIMATE_DAY.isoformat(),
        leg="YES",
        cell_key=(STATION, "DJF", 14, 0, 0),
        p_hold_at_entry=Decimal("0.70"),
        p_hold_at_t=Decimal("0.70"),
        fill_px=Decimal("0.40"),
        held_qty=1,
        mark_vwap=None,
        mark_source="missing",
        spread=None,
        depth_sufficient=False,
        staleness_ns=0,
        book_staleness_ns=0,
        running_max_lower=90,
        running_max_upper=90,
        rung_low=84,
        rung_high=87,
        exit_fee_at_mark=None,
        unrealized_pnl=None,
        recoverable_value=None,
        hour_lst=14,
        entry_context="live",
        observed_at_ns=observed_at_ns,
    )


def test_two_depth_only_evaluations_with_the_same_observed_at_ns_never_confirm_dead() -> None:
    """The 2026-09-15 REQUIRED ADJUSTMENT: two evaluations minutes apart,
    driven only by depth frames (no NEW station observation between them --
    `observed_at_ns` unchanged), must never "confirm" DEAD off a single
    observation."""
    history = MonitorHistory.EMPTY
    first = _dead_candidate_evidence(ts_ns=0, observed_at_ns=1_000)
    decision, history = evaluate_monitor(
        first, history, stale_observation_bound_ns=_STALE_BOUND_NS,
    )
    assert decision.state is not ThesisState.DEAD_BY_OBSERVATION

    second = _dead_candidate_evidence(
        ts_ns=10 * _MINUTE_NS, observed_at_ns=1_000,  # SAME observed_at_ns
    )
    decision, history = evaluate_monitor(
        second, history, stale_observation_bound_ns=_STALE_BOUND_NS,
    )
    assert decision.state is not ThesisState.DEAD_BY_OBSERVATION
    assert decision.reason_codes == ("dead_candidate",)


def test_two_distinct_observed_at_ns_spanning_the_bound_confirm_dead() -> None:
    history = MonitorHistory.EMPTY
    first = _dead_candidate_evidence(ts_ns=0, observed_at_ns=0)
    decision, history = evaluate_monitor(
        first, history, stale_observation_bound_ns=_STALE_BOUND_NS,
    )
    assert decision.state is not ThesisState.DEAD_BY_OBSERVATION

    second = _dead_candidate_evidence(
        ts_ns=5 * _MINUTE_NS, observed_at_ns=5 * _MINUTE_NS,  # distinct instant, span >= 5 min
    )
    decision, history = evaluate_monitor(
        second, history, stale_observation_bound_ns=_STALE_BOUND_NS,
    )
    assert decision.state is ThesisState.DEAD_BY_OBSERVATION
    assert decision.verdict is Verdict.MISSING_STOP  # no executable book in this evidence


# ---------------------------------------------------------------------------
# Integration: a real PositionMonitor wired onto a real strategy
# ---------------------------------------------------------------------------


def _wire_monitor(
    strategy,
    *,
    tmp_path: Path,
    report: Callable[[str, Mapping[str, object]], None] | None = None,
    exit_decider: Callable[..., object] | None = None,
    exit_manifest: object | None = None,
    exit_family_id: str | None = None,
    exit_client_order_id_factory: Callable[[], str] | None = None,
    submit_exit: Callable[..., None] | None = None,
    record_exit_offer: Callable[..., None] | None = None,
    sibling_for: Callable[[str], str | None] | None = None,
) -> PositionMonitor:
    """Test-only DRY (file-by-file item 2, F1): builds the eight closures
    from the PRODUCTION `build_monitor_callables` factory instead of hand-
    copying them a fourth time -- byte-identical behaviour to the three
    call sites it already unifies (`monitor_wiring.py`'s own docstring), so
    every existing assertion below is unchanged.

    FU-1d: `sibling_for` defaults to `None`, so every existing call site
    (and its assertions) stays byte-unedited -- only the new NO-leg-routing
    tests pass `sibling_for=callables.sibling_for` explicitly."""
    callables = build_monitor_callables(strategy)

    return PositionMonitor(
        clock_ns=strategy.clock.timestamp_ns,
        positions_open=callables.positions_open,
        accumulators=strategy._accumulators,
        latch_record=callables.latch_record,
        rung_geometry=callables.rung_geometry,
        fee_coefficient_for=callables.fee_coefficient_for,
        leg_for=callables.leg_for,
        station_for=callables.station_for,
        climate_day_for=callables.climate_day_for,
        hour_lst_for=callables.hour_lst_for,
        stale_observation_bound_ns=strategy._config.stale_observation_minutes * _MINUTE_NS,
        trial_id_prefix=CONTINUOUS_TRIAL_KEY_PREFIX,
        buffer=MarkBuffer(),
        catalog_root=tmp_path / "monitor",
        summaries_dir=tmp_path / "monitor" / "summaries",
        report=report if report is not None else (lambda event, detail: None),
        exit_decider=exit_decider,  # type: ignore[arg-type]
        exit_manifest=exit_manifest,  # type: ignore[arg-type]
        exit_family_id=exit_family_id,
        exit_client_order_id_factory=exit_client_order_id_factory,
        submit_exit=submit_exit,
        record_exit_offer=record_exit_offer,
        sibling_for=sibling_for,
    )


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "state.db"


@pytest.fixture
def interior_instrument() -> BinaryOption:
    return _instrument(INTERIOR_ID, lower_f=86, upper_f=87)


def test_attached_monitor_produces_identical_latch_state_to_no_monitor(
    store_path: Path, interior_instrument: BinaryOption, tmp_path: Path,
) -> None:
    """The attached-vs-None characterisation test: driving the SAME
    observation/depth/fill sequence through a strategy with a real
    `PositionMonitor` attached must leave the `TrialDayRecord`/latch state
    byte-identical to the unattached (`None`) baseline (M7 D3 pin -- the
    monitor is READ-ONLY w.r.t. trial selection, L-34)."""

    def _drive(strategy) -> None:
        strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
        strategy.on_order_filled(
            _fill(strategy, instrument_id=INTERIOR_ID, venue_order_id="ord-mon-1"),
        )
        opened = TestEventStubs.position_opened(
            Position(
                interior_instrument,
                _fill(strategy, instrument_id=INTERIOR_ID, venue_order_id="ord-mon-1"),
            ),
        )
        strategy.on_position_opened(opened)

    baseline = _register_and_start(
        store_path=store_path / "baseline.db", instruments=(interior_instrument,),
    )
    _drive(baseline)
    baseline_record = baseline._latch.record(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID),
    )

    attached = _register(store_path=store_path / "attached.db", instruments=(interior_instrument,))
    attached._position_monitor = _wire_monitor(attached, tmp_path=tmp_path)
    attached.start()
    _drive(attached)
    attached_record = attached._latch.record(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID),
    )

    assert baseline_record == attached_record
    assert (
        baseline._latch.is_inflight(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID),
        )
        == attached._latch.is_inflight(
            STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID),
        )
    )


def test_a_raising_position_monitor_never_reaches_the_hunt_path(
    store_path: Path, interior_instrument: BinaryOption, tmp_path: Path,
) -> None:
    """D8: a monitor whose `on_depth` raises DIRECTLY (bypassing its own
    internal guard entirely -- a broken external object, not a normal
    evaluation failure) must never block `_hunt_tick`; the strategy-level
    `_forward_to_monitor` boundary (plan §2/§7) is the second containment
    layer."""

    class _BrokenMonitor:
        def on_observation(self, *a: object, **k: object) -> None:
            raise RuntimeError("boom")

        def on_depth(self, *a: object, **k: object) -> None:
            raise RuntimeError("boom")

        def on_position_opened(self, *a: object, **k: object) -> None:
            raise RuntimeError("boom")

        def on_stop(self, *a: object, **k: object) -> None:
            raise RuntimeError("boom")

    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy._position_monitor = _BrokenMonitor()  # type: ignore[assignment]

    from tests.unit.test_current_rung_hold_strategy import _quote

    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(  # never raises despite the broken monitor
        _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS),
    )

    assert strategy.position_events.count("monitor_error") >= 1
    # The hunt path itself ran: a decision was recorded on the offer tape.
    assert len(strategy.offer_tape.records()) >= 1


def test_an_unresolved_position_opened_event_is_counted_and_the_position_still_registers_lazily(
    store_path: Path, interior_instrument: BinaryOption, tmp_path: Path,
) -> None:
    """Review finding F3: `on_position_opened`'s `self.cache.position(event.
    position_id)` lookup can return `None` (the cache has not yet reflected
    the position this event names) -- previously a silent skip. This proves
    (1) that branch is now counted, never silently dropped, and (2) the
    position is not lost: `PositionMonitor._ensure_registered`'s own
    `positions_open` read still registers it the next time a Depth10 frame
    for the same instrument arrives, once the cache DOES know about it.
    """
    from tests.unit.test_continuous_rung_hold_strategy import _depth

    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy._position_monitor = _wire_monitor(strategy, tmp_path=tmp_path)
    monitor = strategy._position_monitor

    fill = _fill(strategy, instrument_id=INTERIOR_ID, venue_order_id="ord-f3-1")
    position = Position(interior_instrument, fill)
    unresolved_event = TestEventStubs.position_opened(position)

    # (1) The cache does NOT yet know this position -- `cache.position(...)`
    # returns `None`, so the handler must count, not silently return.
    strategy.on_position_opened(unresolved_event)
    assert strategy.position_events.count("position_opened_event_unresolved") == 1
    assert _IID not in monitor._positions  # nothing registered yet

    # (2) The cache now reflects the position (a later reconciliation read,
    # e.g. the strategy's own fill/position bookkeeping catching up) -- the
    # NEXT Depth10 frame must still register it, lazily, via
    # `_ensure_registered`'s own `positions_open` read.
    strategy.cache.add_position(position, OmsType.NETTING)
    depth = _depth(
        INTERIOR_ID, bids=(("0.01", 10),), asks=(("0.40", 10),), ts_event=WINDOW_OPEN_NS,
    )
    strategy.on_order_book_depth(depth)

    assert _IID in monitor._positions
    assert strategy.position_events.count("position_opened_event_unresolved") == 1  # unchanged


# ---------------------------------------------------------------------------
# INC-E3 (plan §3, PREREG v4 §3b/§12): exit-decider wiring.
#
# These tests drive the REAL `PositionMonitor` pipeline (real
# `RunningExtremeAccumulator`, real `evaluate_monitor`/`build_monitor_
# evidence`) exactly like `test_attached_monitor_...` above, through the
# LIGHTWEIGHT `_register_and_start` harness (no `BacktestEngine`, no real
# order submission) -- `submit_exit`/`record_exit_offer` are injected SPY
# callables here, never the strategy's own `submit_exit` (that method's
# OWN order-construction behaviour is covered by
# `test_current_rung_hold_exit_wiring.py`'s full-backtest-harness tests).
# ---------------------------------------------------------------------------

_DEAD_TEMP_C_TENTHS = 320  # 32.0C -> 90F, strictly above rung_high=87
_DEAD_CONFIRM_SPAN_MIN = 6  # >= monitor_decision._DEAD_MIN_CONFIRM_SPAN_NS (5 min)


def _manifest_for_exit_test(
    *, exit_rule: str | None, no_leg_exit: bool = False,
) -> FamilyManifest:
    from breezy.persistence.family_manifest import FamilyManifest

    return FamilyManifest(
        family_id="pm_us_crh_exit_v4",
        venue="polymarket_us",
        taker_fee_coefficient=Decimal("0.06"),
        trial_id_prefix="current_rung_hold_exit_v4/trial/",
        d0_climate_day="2099-01-01",
        boundary_artefact_path=Path("deploy/families/gs_boundary_pm_us_crh_v2.json"),
        boundary_inputs_sha256="a" * 64,
        composition_kind="continuous_rung_hold",
        density_artefact_path=Path("deploy/families/artefacts/not_applicable_density.json"),
        density_artefact_sha256="247f636350685b38966251703c47d10531913367fbcca175b086a2c298421a65",
        stations=("SFO",),
        status="REGISTERED" if exit_rule is not None else "DRAFT_NOT_REGISTERED",
        manifest_sha256="b" * 64,
        exit_rule=exit_rule,
        no_leg_exit=no_leg_exit,
    )


def _drive_to_dead(
    strategy, interior_instrument: BinaryOption, *, monitor: PositionMonitor,
) -> None:
    """Entry fill + position-opened + two DEAD-confirming observations/
    depth frames -- the SAME geometry
    `test_a_dead_scenario_in_replay_yields_an_exit_or_missing_stop_mark`
    (backtest_only test file) drives, reused here at the lightweight
    (non-engine) `_register_and_start` layer."""
    from tests.unit.test_continuous_rung_hold_strategy import _depth

    interior_instrument.info["fee_coefficient"] = "0.06"
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    fill = _fill(strategy, instrument_id=INTERIOR_ID, venue_order_id="ord-e3-1")
    strategy.on_order_filled(fill)
    position = Position(interior_instrument, fill)
    strategy.cache.add_position(position, OmsType.NETTING)
    strategy.on_position_opened(TestEventStubs.position_opened(position))

    def _fresh_depth(now_ns: int) -> None:
        # Re-pushed at each evaluation instant so `book_staleness_ns` (measured
        # from `monitored.last_book_ts_ns`) stays inside the 180s bound --
        # unlike the full-engine backtest harness, this lightweight harness
        # has no continuous market-data stream keeping the book fresh for free.
        strategy.on_order_book_depth(
            _depth(
                INTERIOR_ID, bids=(("0.30", 10),), asks=(("0.90", 10),), ts_event=now_ns,
            ),
        )

    _fresh_depth(WINDOW_OPEN_NS)

    first_ts_ns = WINDOW_OPEN_NS + 2 * _MINUTE_NS
    first_dead = _observation(temp_c_tenths=_DEAD_TEMP_C_TENTHS, observed_at_ns=first_ts_ns)
    strategy.on_data(first_dead)
    _fresh_depth(first_ts_ns)
    monitor.on_observation(STATION, first_ts_ns)

    second_ts_ns = WINDOW_OPEN_NS + (2 + _DEAD_CONFIRM_SPAN_MIN) * _MINUTE_NS
    second_dead = _observation(temp_c_tenths=_DEAD_TEMP_C_TENTHS, observed_at_ns=second_ts_ns)
    strategy.on_data(second_dead)
    _fresh_depth(second_ts_ns)
    monitor.on_observation(STATION, second_ts_ns)


def test_a_shadow_monitor_never_calls_submit_exit_or_record_exit_offer_even_on_dead(
    store_path: Path, interior_instrument: BinaryOption, tmp_path: Path,
) -> None:
    """Module docstring (INC-E3): `exit_decider=None` (the default) is
    byte-identical shadow behaviour -- neither `submit_exit` nor
    `record_exit_offer` is EVER called, even on a confirmed DEAD scenario
    with `EXIT_RECOMMENDED`."""
    submit_calls: list[object] = []
    offer_calls: list[object] = []
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    monitor = _wire_monitor(
        strategy,
        tmp_path=tmp_path,
        submit_exit=submit_calls.append,
        record_exit_offer=offer_calls.append,
    )
    strategy._position_monitor = monitor

    _drive_to_dead(strategy, interior_instrument, monitor=monitor)

    assert submit_calls == []
    assert offer_calls == []


def test_a_gate_refused_family_evaluates_but_submits_nothing(
    store_path: Path, interior_instrument: BinaryOption, tmp_path: Path,
) -> None:
    """A decider IS installed, but the manifest is `pm_us_crh_cont`-shaped
    (no `exit_rule`) -- `decide_exit`'s own family gate refuses every
    evaluation, so `record_exit_offer` sees only refusals and
    `submit_exit` is NEVER called."""
    from breezy.strategy.current_rung_hold.exit_decider import ExitProposal, decide_exit

    submit_calls: list[object] = []
    offer_calls: list[object] = []
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    monitor = _wire_monitor(
        strategy,
        tmp_path=tmp_path,
        exit_decider=decide_exit,
        exit_manifest=_manifest_for_exit_test(exit_rule=None),
        exit_family_id="pm_us_crh_cont",
        exit_client_order_id_factory=lambda: "exit-coid-shadow",
        submit_exit=submit_calls.append,
        record_exit_offer=offer_calls.append,
    )
    strategy._position_monitor = monitor

    _drive_to_dead(strategy, interior_instrument, monitor=monitor)

    assert submit_calls == []
    assert offer_calls, "at least one refusal row must still be persisted"
    assert not any(isinstance(call, ExitProposal) for call in offer_calls)


def test_an_armed_family_fires_and_calls_submit_exit_with_a_proposal(
    store_path: Path, interior_instrument: BinaryOption, tmp_path: Path,
) -> None:
    """The mirror case: a manifest that DOES declare `exit_rule` for the
    registered family fires R_DEAD once DEAD confirms with an executable
    book, and the decision is persisted (`record_exit_offer`) BEFORE
    `submit_exit` is called."""
    from breezy.strategy.current_rung_hold.exit_decider import ExitProposal, decide_exit

    call_order: list[str] = []
    submitted: list[ExitProposal] = []

    def _submit_exit(proposal: ExitProposal) -> None:
        call_order.append("submit_exit")
        submitted.append(proposal)

    def _record_exit_offer(record: object) -> None:
        call_order.append("record_exit_offer")

    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    monitor = _wire_monitor(
        strategy,
        tmp_path=tmp_path,
        exit_decider=decide_exit,
        exit_manifest=_manifest_for_exit_test(
            exit_rule="crh_exit_v4:R_THREAT_PRIMARY+R_DEAD_BACKSTOP",
        ),
        exit_family_id="pm_us_crh_exit_v4",
        exit_client_order_id_factory=lambda: "exit-coid-fired",
        submit_exit=_submit_exit,
        record_exit_offer=_record_exit_offer,
    )
    strategy._position_monitor = monitor

    _drive_to_dead(strategy, interior_instrument, monitor=monitor)

    assert len(submitted) == 1
    assert submitted[0].authorization.rule.value == "R_DEAD"
    assert submitted[0].authorization.client_order_id == "exit-coid-fired"
    assert "record_exit_offer" in call_order
    assert "submit_exit" in call_order
    assert call_order.index("record_exit_offer") < call_order.index("submit_exit"), (
        "the decision must be persisted BEFORE submit_exit is called (hard invariant)"
    )


# ---------------------------------------------------------------------------
# FU-1d S1 (RULING_FU-1b_no_leg_marks_2026-09-26.md re-open item 1,
# FU-1d-reopen plan r1): the per-station-day exit-fire counter
# (`PositionMonitor._station_day_exit_counts`) is keyed by `(station,
# climate_day)` ONLY -- deliberately SHARED across a station-day's YES and
# NO legs, matching PREREG v4 section3b's per-station-day cap (the trial
# unit is the station-day, L-40). Characterisation test (L-33): no RED,
# since this is the pre-existing keying; mutation evidence (keying by
# `(station, climate_day, monitored.leg)` instead) is attached in the
# commit body and makes this test fail.
# ---------------------------------------------------------------------------


def _s1_shared_cap_evidence(*, iid: str, leg: str) -> MonitorEvidence:
    return MonitorEvidence(
        ts_ns=WINDOW_OPEN_NS,
        instrument_id=iid,
        station=STATION,
        climate_day=CLIMATE_DAY.isoformat(),
        leg=leg,  # type: ignore[arg-type]
        cell_key=(STATION, "DJF", 14, 0, 0),
        p_hold_at_entry=Decimal("0.70"),
        p_hold_at_t=Decimal("0.05"),
        fill_px=Decimal("0.40"),
        held_qty=1,
        mark_vwap=Decimal("0.05"),
        mark_source="depth_walk",
        spread=Decimal("0.01"),
        depth_sufficient=True,
        staleness_ns=0,
        book_staleness_ns=0,
        running_max_lower=90,
        running_max_upper=90,
        rung_low=84,
        rung_high=87,
        exit_fee_at_mark=Decimal("0.01"),
        unrealized_pnl=Decimal(0),
        recoverable_value=Decimal("0.04"),
        hour_lst=14,
        entry_context="live",
    )


def test_station_day_exit_count_is_shared_across_yes_and_no_legs_of_one_station_day(
    tmp_path: Path,
) -> None:
    """Drive a YES DEAD-confirmed evaluation, then a NO one, for the SAME
    station-day, through a stub `exit_decider` that records
    `(evidence.leg, station_day_exit_count)` and always fires (returns a
    real `ExitProposal`). The NO leg must see the YES leg's fired exit
    already reflected as `station_day_exit_count == 1`."""
    from breezy.strategy.current_rung_hold.exit_authorization import (
        ExitAuthorization,
        ExitRule,
    )
    from breezy.strategy.current_rung_hold.exit_decider import ExitProposal

    calls: list[tuple[str, int]] = []

    def _stub_decider(
        decision, evidence, *,
        manifest, family_id, position_id, client_order_id_factory,
        last_exit_decided_at_ns_for_position, station_day_exit_count,
        fee_coefficient, now_ns,
    ):
        calls.append((evidence.leg, station_day_exit_count))
        return ExitProposal(
            instrument_id=evidence.instrument_id,
            authorization=ExitAuthorization(
                family_id=family_id,
                position_id=position_id,
                client_order_id=client_order_id_factory(),
                leg="yes" if evidence.leg == "YES" else "no",
                attributed_net_long=1,
                working_sell_qty=0,
                quantity=1,
                limit_price=Decimal("0.05"),
                rule=ExitRule.R_DEAD,
                expected_settlement_value=Decimal(0),
                fee_coefficient=Decimal(0),
                decided_at_ns=now_ns,
                book_staleness_ns=0,
            ),
            decided_at_ns=now_ns,
        )

    submit_calls: list[object] = []
    strategy = _FakeStrategyForCallables(
        cache=_FakeCacheForCallables(positions_by_iid={}),
        _latch=_FakeLatchForCallables(record=None),
        _facts=_no_leg_facts(),
        _std_utc_offset_hours_by_station={STATION: -8.0},
    )
    monitor = _build_position_monitor_via_callables(
        strategy,
        tmp_path=tmp_path,
        accumulators={},
        exit_decider=_stub_decider,
        exit_manifest=_manifest_for_exit_test(
            exit_rule="crh_exit_v4:R_THREAT_PRIMARY+R_DEAD_BACKSTOP",
        ),
        exit_family_id="pm_us_crh_exit_v4",
        exit_client_order_id_factory=lambda: "exit-coid-s1",
        submit_exit=submit_calls.append,
    )
    monitor.on_position_opened(  # type: ignore[arg-type]
        _FakePosition(instrument_id=_IID, avg_px_open=0.40, quantity=1, id="P-YES"),
        WINDOW_OPEN_NS,
    )
    monitor.on_position_opened(  # type: ignore[arg-type]
        _FakePosition(instrument_id=_NO_IID, avg_px_open=0.40, quantity=1, id="P-NO"),
        WINDOW_OPEN_NS,
    )
    monitored_yes = monitor._positions[_IID]
    monitored_no = monitor._positions[_NO_IID]
    assert (monitored_yes.station, monitored_yes.climate_day) == (
        monitored_no.station, monitored_no.climate_day,
    ), "both legs of one market must share one station-day"

    decision = MonitorDecision(
        state=ThesisState.DEAD_BY_OBSERVATION,
        verdict=Verdict.EXIT_RECOMMENDED,
        reason_codes=(),
        confirmations=3,
        ts_ns=WINDOW_OPEN_NS,
    )
    monitor._maybe_decide_exit(
        monitored_yes, _s1_shared_cap_evidence(iid=_IID, leg="YES"), decision, WINDOW_OPEN_NS,
    )
    monitor._maybe_decide_exit(
        monitored_no, _s1_shared_cap_evidence(iid=_NO_IID, leg="NO"), decision, WINDOW_OPEN_NS + 1,
    )

    assert calls == [("YES", 0), ("NO", 1)]
    assert len(submit_calls) == 2


# ---------------------------------------------------------------------------
# FU-1: `PositionMonitor` resolves a `^no` position's facts via the YES
# sibling (`monitor_wiring.build_monitor_callables`'s FU-1 fix), driven
# through the REAL `build_monitor_callables` factory over a duck-typed,
# YES-only fake strategy -- never the isolated `_build_monitor` stub harness
# above, so these tests actually exercise the production wiring seam the fix
# lives in, not a bespoke test double that would paper over the bug.
# ---------------------------------------------------------------------------

_NO_IID = str(sibling_instrument_id(INTERIOR_ID))


@dataclass
class _NoLegFakeFacts:
    settlement_station: str
    climate_day: date
    lower_f: int | None
    upper_f: int | None


class _FakeCacheForCallables:
    """Exposes only `positions_open`/`instrument`, mirroring
    `test_current_rung_hold_monitor_wiring.py`'s `_StrictCache` shape."""

    def __init__(
        self, *, positions_by_iid: dict[str, list[_FakePosition]], instrument: object = None,
    ) -> None:
        self._positions_by_iid = positions_by_iid
        self._instrument = instrument

    def positions_open(self, *, instrument_id: object) -> Sequence[_FakePosition]:
        return self._positions_by_iid.get(str(instrument_id), [])

    def instrument(self, instrument_id: object) -> object:
        return self._instrument


@dataclass
class _FakeLatchForCallables:
    record: object | None = None

    def record_with_legacy_fallback(
        self, station: str, climate_day: str, *, key_instrument_id: str | None = None,
    ) -> object | None:
        return self.record


@dataclass
class _FakeStrategyForCallables:
    """Minimal duck-typed stand-in for `ContinuousRungHoldStrategy` --
    `_facts` is YES-only, exactly as `continuous_strategy.py:842` leaves it
    in production (depth is subscribed only for YES instrument ids)."""

    cache: object
    _latch: object
    _facts: dict[str, _NoLegFakeFacts] = field(default_factory=dict)
    _std_utc_offset_hours_by_station: dict[str, float] = field(default_factory=dict)
    _fee: Decimal | None = Decimal("0.06")

    def _guarded_fee_coefficient(self, instrument: object) -> Decimal | None:
        return self._fee


def _build_position_monitor_via_callables(
    strategy: _FakeStrategyForCallables,
    *,
    tmp_path: Path,
    accumulators: Mapping[str, object],
    report: Callable[[str, Mapping[str, object]], None] | None = None,
    exit_decider: Callable[..., object] | None = None,
    exit_manifest: object | None = None,
    exit_family_id: str | None = None,
    exit_client_order_id_factory: Callable[[], str] | None = None,
    submit_exit: Callable[..., None] | None = None,
    record_exit_offer: Callable[..., None] | None = None,
    sibling_for: Callable[[str], str | None] | None = None,
) -> PositionMonitor:
    """The production `build_monitor_callables` factory, wired into a real
    `PositionMonitor` -- the FU-1-relevant twin of `_wire_monitor` above,
    over a duck-typed fake rather than a real `ContinuousRungHoldStrategy`.

    FU-1d: `sibling_for` defaults to `None` (see `_wire_monitor`'s own
    docstring note)."""
    callables = build_monitor_callables(strategy)  # type: ignore[arg-type]
    return PositionMonitor(
        clock_ns=lambda: WINDOW_OPEN_NS,
        positions_open=callables.positions_open,
        accumulators=accumulators,  # type: ignore[arg-type]
        latch_record=callables.latch_record,
        rung_geometry=callables.rung_geometry,
        fee_coefficient_for=callables.fee_coefficient_for,
        leg_for=callables.leg_for,
        station_for=callables.station_for,
        climate_day_for=callables.climate_day_for,
        hour_lst_for=callables.hour_lst_for,
        stale_observation_bound_ns=_STALE_BOUND_NS,
        trial_id_prefix=CONTINUOUS_TRIAL_KEY_PREFIX,
        buffer=MarkBuffer(),
        catalog_root=tmp_path / "monitor",
        summaries_dir=tmp_path / "monitor" / "summaries",
        report=report if report is not None else (lambda event, detail: None),
        exit_decider=exit_decider,  # type: ignore[arg-type]
        exit_manifest=exit_manifest,  # type: ignore[arg-type]
        exit_family_id=exit_family_id,
        exit_client_order_id_factory=exit_client_order_id_factory,
        submit_exit=submit_exit,
        record_exit_offer=record_exit_offer,
        sibling_for=sibling_for,
    )


def _no_leg_facts(*, station: str = STATION, climate_day: date = CLIMATE_DAY) -> dict:
    return {_IID: _NoLegFakeFacts(
        settlement_station=station, climate_day=climate_day, lower_f=86, upper_f=87,
    )}


def test_no_leg_position_opened_registers_with_sibling_station_day_and_no_monitor_error(
    tmp_path: Path,
) -> None:
    strategy = _FakeStrategyForCallables(
        cache=_FakeCacheForCallables(
            positions_by_iid={
                _NO_IID: [_FakePosition(instrument_id=_NO_IID, avg_px_open=0.40, quantity=1)],
            },
        ),
        _latch=_FakeLatchForCallables(record=None),
        _facts=_no_leg_facts(),
        _std_utc_offset_hours_by_station={STATION: -8.0},
    )
    accumulator = _RecordingAccumulator(
        _FakeRunningMax(lower_f=85, upper_f=85, source_observed_at_ns=WINDOW_OPEN_NS),
    )
    monitor = _build_position_monitor_via_callables(
        strategy, tmp_path=tmp_path, accumulators={STATION: accumulator},
    )

    fake_position = _FakePosition(instrument_id=_NO_IID, avg_px_open=0.40, quantity=1)
    monitor.on_position_opened(fake_position, WINDOW_OPEN_NS)  # type: ignore[arg-type]

    assert monitor.counters["monitor_errors"] == 0
    assert _NO_IID in monitor._positions
    registered = monitor._positions[_NO_IID]
    assert registered.leg == "NO"
    assert registered.station == STATION
    assert registered.climate_day == CLIMATE_DAY.isoformat()


def test_no_leg_position_is_evaluated_on_observation_with_mark_source_missing(
    tmp_path: Path,
) -> None:
    strategy = _FakeStrategyForCallables(
        cache=_FakeCacheForCallables(
            positions_by_iid={
                _NO_IID: [_FakePosition(instrument_id=_NO_IID, avg_px_open=0.40, quantity=1)],
            },
        ),
        _latch=_FakeLatchForCallables(record=None),
        _facts=_no_leg_facts(),
        _std_utc_offset_hours_by_station={STATION: -8.0},
    )
    accumulator = _RecordingAccumulator(
        _FakeRunningMax(lower_f=85, upper_f=85, source_observed_at_ns=WINDOW_OPEN_NS),
    )
    monitor = _build_position_monitor_via_callables(
        strategy, tmp_path=tmp_path, accumulators={STATION: accumulator},
    )
    fake_position = _FakePosition(instrument_id=_NO_IID, avg_px_open=0.40, quantity=1)
    monitor.on_position_opened(fake_position, WINDOW_OPEN_NS)  # type: ignore[arg-type]

    monitor.on_observation(STATION, WINDOW_OPEN_NS + _MINUTE_NS)

    assert monitor.counters["monitor_errors"] == 0
    assert monitor.counters["evaluations"] == 1

    monitor.on_stop(WINDOW_OPEN_NS + 2 * _MINUTE_NS)
    summaries = read_monitor_summaries(tmp_path / "monitor" / "summaries")
    assert len(summaries) == 1
    assert summaries[0].mark_missing_frames == 1


def test_no_leg_recovered_p_hold_at_entry_is_one_minus_p_hold_upper(tmp_path: Path) -> None:
    from breezy.strategy.current_rung_hold.archive_table import P_HOLD_UPPER

    #: A real, populated cell (`tests/unit/test_current_rung_hold_monitor_evidence.py`'s
    #: own `_KEY`) -- never a fabricated golden value.
    station = "SFO"
    season_climate_day = date(2026, 1, 15)  # January -> DJF
    hour_lst = 14
    key = (station, "DJF", hour_lst, 0, 0)
    expected_p_hold = Decimal(1) - P_HOLD_UPPER[key]

    yes_iid_obj = InstrumentId.from_str("sfo-86-87.POLYMARKET_US")
    yes_iid = str(yes_iid_obj)
    no_iid = str(sibling_instrument_id(yes_iid_obj))

    hour_ns = 3_600_000_000_000
    latched_at_ns = WINDOW_OPEN_NS + 2 * hour_ns  # 12:00 LST + 2h == 14:00 LST

    @dataclass
    class _FakeTrialDayRecord:
        latched_at_ns: int

    strategy = _FakeStrategyForCallables(
        cache=_FakeCacheForCallables(
            positions_by_iid={
                no_iid: [_FakePosition(instrument_id=no_iid, avg_px_open=0.40, quantity=1)],
            },
        ),
        _latch=_FakeLatchForCallables(record=_FakeTrialDayRecord(latched_at_ns=latched_at_ns)),
        _facts={yes_iid: _NoLegFakeFacts(
            settlement_station=station, climate_day=season_climate_day, lower_f=86, upper_f=87,
        )},
        _std_utc_offset_hours_by_station={station: -8.0},
    )
    accumulator = _RecordingAccumulator(
        _FakeRunningMax(lower_f=86, upper_f=87, source_observed_at_ns=latched_at_ns),
    )
    monitor = _build_position_monitor_via_callables(
        strategy, tmp_path=tmp_path, accumulators={station: accumulator},
    )

    fake_position = _FakePosition(instrument_id=no_iid, avg_px_open=0.40, quantity=1)
    monitor.on_position_opened(fake_position, latched_at_ns)  # type: ignore[arg-type]

    assert monitor.counters["monitor_errors"] == 0
    assert monitor._positions[no_iid].p_hold_at_entry == expected_p_hold


# ---------------------------------------------------------------------------
# FU-1: the NO leg's DEAD/LOCKED swap at the pure `evaluate_monitor` layer
# (`monitor_decision._evaluate_no`) -- neither test needs a `PositionMonitor`
# at all; both drive the SAME "inside the rung, past the peak hour" geometry
# through the real classifier, mirroring
# `test_two_distinct_observed_at_ns_spanning_the_bound_confirm_dead` above.
# ---------------------------------------------------------------------------


def _locked_geometry_evidence(
    *, leg: str, ts_ns: int, observed_at_ns: int | None,
) -> MonitorEvidence:
    return MonitorEvidence(
        ts_ns=ts_ns,
        instrument_id=_IID if leg == "YES" else _NO_IID,
        station=STATION,
        climate_day=CLIMATE_DAY.isoformat(),
        leg=leg,  # type: ignore[arg-type]
        cell_key=(STATION, "SON", 18, 0, 0),
        p_hold_at_entry=Decimal("0.70") if leg == "YES" else None,
        p_hold_at_t=Decimal("0.70") if leg == "YES" else None,
        fill_px=Decimal("0.40"),
        held_qty=1,
        mark_vwap=None,
        mark_source="missing",
        spread=None,
        depth_sufficient=False,
        staleness_ns=0,
        book_staleness_ns=0,
        running_max_lower=86,
        running_max_upper=87,
        rung_low=86,
        rung_high=87,
        exit_fee_at_mark=None,
        unrealized_pnl=None,
        recoverable_value=None,
        hour_lst=18,  # >= monitor_decision._LOCKED_HOUR_LST
        entry_context="live",
        observed_at_ns=observed_at_ns,
    )


def test_no_leg_inside_rung_after_peak_reaches_dead_by_observation() -> None:
    history = MonitorHistory.EMPTY
    first = _locked_geometry_evidence(leg="NO", ts_ns=0, observed_at_ns=0)
    decision, history = evaluate_monitor(
        first, history, stale_observation_bound_ns=_STALE_BOUND_NS,
    )
    assert decision.state is not ThesisState.DEAD_BY_OBSERVATION

    second = _locked_geometry_evidence(
        leg="NO", ts_ns=6 * _MINUTE_NS, observed_at_ns=6 * _MINUTE_NS,
    )
    decision, history = evaluate_monitor(
        second, history, stale_observation_bound_ns=_STALE_BOUND_NS,
    )
    assert decision.state is ThesisState.DEAD_BY_OBSERVATION
    assert decision.reason_codes == ("no_leg_inside_rung_after_peak",)


def test_the_same_evidence_on_the_yes_leg_is_locked_never_dead() -> None:
    from breezy.strategy.current_rung_hold.monitor_decision import (
        _DEAD_MIN_CONFIRM_SPAN_NS,
        _LOCKED_HOUR_LST,
    )

    assert 18 >= _LOCKED_HOUR_LST
    assert 6 * _MINUTE_NS >= _DEAD_MIN_CONFIRM_SPAN_NS

    history = MonitorHistory.EMPTY
    first = _locked_geometry_evidence(leg="YES", ts_ns=0, observed_at_ns=0)
    decision, history = evaluate_monitor(
        first, history, stale_observation_bound_ns=_STALE_BOUND_NS,
    )
    assert decision.state is not ThesisState.LOCKED_BY_OBSERVATION

    second = _locked_geometry_evidence(
        leg="YES", ts_ns=6 * _MINUTE_NS, observed_at_ns=6 * _MINUTE_NS,
    )
    decision, history = evaluate_monitor(
        second, history, stale_observation_bound_ns=_STALE_BOUND_NS,
    )
    assert decision.state is ThesisState.LOCKED_BY_OBSERVATION
    assert decision.state is not ThesisState.DEAD_BY_OBSERVATION


# ---------------------------------------------------------------------------
# FU-1: a DEAD/THREATENED NO leg reaches the (shadow) exit decider exactly
# like a YES leg does -- INC-E3's `_maybe_decide_exit` is leg-agnostic, but
# before FU-1 a NO leg never registered at all, so it never reached here.
# ---------------------------------------------------------------------------

_HOUR_NS = 3_600_000_000_000


def _drive_no_leg_to_dead(monitor: PositionMonitor, *, station: str, start_ns: int) -> None:
    """Two observations spanning >= `_DEAD_MIN_CONFIRM_SPAN_NS` (5 min), both
    at/after `_LOCKED_HOUR_LST` (18:00 LST) with the running max fixed inside
    the rung -- the NO leg's `_evaluate_no` "inside rung after peak" DEAD
    path (mirrors `_drive_to_dead`'s YES-leg geometry above)."""
    monitor.on_observation(station, start_ns)
    monitor.on_observation(station, start_ns + 6 * _MINUTE_NS)


def _drive_no_leg_to_threatened(monitor: PositionMonitor, *, station: str, start_ns: int) -> None:
    """Three observations spanning >= `_THREATENED_MIN_SPAN_NS` (10 min),
    all BEFORE `_LOCKED_HOUR_LST` with the running max fixed inside the rung
    -- the NO leg's pre-peak "inside rung" THREATENED hysteresis path."""
    monitor.on_observation(station, start_ns)
    monitor.on_observation(station, start_ns + 5 * _MINUTE_NS)
    monitor.on_observation(station, start_ns + 10 * _MINUTE_NS)


def test_no_leg_dead_with_gated_false_manifest_writes_only_refusal_rows_and_never_submits(
    tmp_path: Path,
) -> None:
    from breezy.strategy.current_rung_hold.exit_decider import decide_exit

    submit_calls: list[object] = []
    offer_calls: list[object] = []
    start_ns = WINDOW_OPEN_NS + 6 * _HOUR_NS  # 18:00 LST -- at `_LOCKED_HOUR_LST`

    strategy = _FakeStrategyForCallables(
        cache=_FakeCacheForCallables(
            positions_by_iid={
                _NO_IID: [_FakePosition(instrument_id=_NO_IID, avg_px_open=0.40, quantity=1)],
            },
        ),
        _latch=_FakeLatchForCallables(record=None),
        _facts=_no_leg_facts(),
        _std_utc_offset_hours_by_station={STATION: -8.0},
    )
    accumulator = _RecordingAccumulator(
        _FakeRunningMax(lower_f=86, upper_f=87, source_observed_at_ns=start_ns),
    )
    monitor = _build_position_monitor_via_callables(
        strategy,
        tmp_path=tmp_path,
        accumulators={STATION: accumulator},
        exit_decider=decide_exit,
        exit_manifest=_manifest_for_exit_test(exit_rule=None),
        exit_family_id="pm_us_crh_cont",
        exit_client_order_id_factory=lambda: "exit-coid-no-leg-shadow",
        submit_exit=submit_calls.append,
        record_exit_offer=offer_calls.append,
    )
    fake_position = _FakePosition(instrument_id=_NO_IID, avg_px_open=0.40, quantity=1)
    monitor.on_position_opened(fake_position, start_ns)  # type: ignore[arg-type]

    _drive_no_leg_to_dead(monitor, station=STATION, start_ns=start_ns)

    assert submit_calls == []
    assert offer_calls, "at least one refusal row must still be persisted"
    assert all(
        getattr(call, "exit_reason_code", None) == "family_not_exit_registered"
        for call in offer_calls
    )
    assert all(getattr(call, "side", None) == "NO" for call in offer_calls)


def test_no_leg_threatened_with_an_armed_family_refuses_no_leg_exit_not_declared(
    tmp_path: Path,
) -> None:
    """FU-1d retarget (was `..._refuses_book_not_executable_while_no_marks_
    exist`): an ARMED family (`exit_rule` set, family registered) but one
    that does NOT declare `no_leg_exit` now refuses at the NEW, earlier
    NO-leg declaration gate -- `no_leg_exit_not_declared` -- before
    `decide_exit`'s own `_book_is_executable` check is ever reached (no
    depth is pushed here either, so the book check would ALSO refuse, but
    the new gate fires first per its placement directly after the family
    gate). `submit_exit` is still never called. (f), in
    `test_current_rung_hold_exit_decider.py`, keeps the old book-gate
    assertion covered for a family that DOES declare `no_leg_exit`."""
    from breezy.strategy.current_rung_hold.exit_decider import decide_exit

    submit_calls: list[object] = []
    offer_calls: list[object] = []
    start_ns = WINDOW_OPEN_NS + 2 * _HOUR_NS  # 14:00 LST -- before `_LOCKED_HOUR_LST`

    strategy = _FakeStrategyForCallables(
        cache=_FakeCacheForCallables(
            positions_by_iid={
                _NO_IID: [_FakePosition(instrument_id=_NO_IID, avg_px_open=0.40, quantity=1)],
            },
        ),
        _latch=_FakeLatchForCallables(record=None),
        _facts=_no_leg_facts(),
        _std_utc_offset_hours_by_station={STATION: -8.0},
    )
    accumulator = _RecordingAccumulator(
        _FakeRunningMax(lower_f=86, upper_f=87, source_observed_at_ns=start_ns),
    )
    monitor = _build_position_monitor_via_callables(
        strategy,
        tmp_path=tmp_path,
        accumulators={STATION: accumulator},
        exit_decider=decide_exit,
        exit_manifest=_manifest_for_exit_test(
            exit_rule="crh_exit_v4:R_THREAT_PRIMARY+R_DEAD_BACKSTOP",
        ),
        exit_family_id="pm_us_crh_exit_v4",
        exit_client_order_id_factory=lambda: "exit-coid-no-leg-armed",
        submit_exit=submit_calls.append,
        record_exit_offer=offer_calls.append,
    )
    fake_position = _FakePosition(instrument_id=_NO_IID, avg_px_open=0.40, quantity=1)
    monitor.on_position_opened(fake_position, start_ns)  # type: ignore[arg-type]

    _drive_no_leg_to_threatened(monitor, station=STATION, start_ns=start_ns)

    assert submit_calls == []
    assert offer_calls, "at least one refusal row must still be persisted"
    assert all(
        getattr(call, "exit_reason_code", None) == "no_leg_exit_not_declared"
        for call in offer_calls
    )


# ---------------------------------------------------------------------------
# FU-1d (RULING_FU-1b_no_leg_marks_2026-09-26.md, plan
# FU-1d_derived_no_marks_plan_r1_2026-09-26.md): a YES `OrderBookDepth10`
# frame is also routed to a registered NO-leg sibling, marked via
# `walk_exit_vwap(..., leg="NO", ...)`. Driven through the isolated
# `_build_monitor` stub harness (never `_build_position_monitor_via_
# callables`'s duck-typed strategy, and never the production `_sibling_for`
# closure) with plain lambda stubs standing in for `sibling_for` -- the
# production `monitor_wiring._sibling_for` closure itself is covered by
# `test_current_rung_hold_monitor_wiring.py`.
# ---------------------------------------------------------------------------

def _leg_for_yes_no(iid: str) -> str:
    return "NO" if iid == _NO_IID else "YES"


def _sibling_for_stub(iid: str) -> str | None:
    """Production shape: routes ONLY the YES id forward, never a NO id
    (edge case table: "a NO-leg frame is never re-routed")."""
    return _NO_IID if iid == _IID else None


def test_no_leg_position_receives_a_mark_from_its_yes_siblings_depth_frame(
    tmp_path: Path,
) -> None:
    """RED without the fix: the NO position stays `mark_source="missing"`
    forever because nothing ever routes a depth frame to it."""
    positions = _PositionsOpenStub()
    positions.set(_NO_IID, [_FakePosition(instrument_id=_NO_IID, avg_px_open=0.40, quantity=1)])
    accumulator = _RecordingAccumulator(
        _FakeRunningMax(lower_f=85, upper_f=85, source_observed_at_ns=WINDOW_OPEN_NS),
    )
    monitor, _reports = _build_monitor(
        tmp_path,
        positions_open=positions,
        accumulators={STATION: accumulator},
        leg_for=_leg_for_yes_no,
        sibling_for=_sibling_for_stub,
    )
    monitor.on_position_opened(
        _FakePosition(instrument_id=_NO_IID, avg_px_open=0.40, quantity=1), WINDOW_OPEN_NS,
    )  # type: ignore[arg-type]
    assert monitor._buffer.records() == ()  # registration alone never evaluates

    depth = _book_depth10(
        instrument_id=InstrumentId.from_str(_IID),
        bids=(("0.90", "5"),),
        asks=(("0.30", "5"),),
        ts_ns=WINDOW_OPEN_NS,
    )
    monitor.on_depth(depth, WINDOW_OPEN_NS)  # type: ignore[arg-type]

    assert monitor.counters["monitor_errors"] == 0
    no_records = [r for r in monitor._buffer.records() if r.leg == "NO"]
    assert len(no_records) == 1
    assert no_records[0].mark_source == "depth_walk"


def test_no_leg_mark_equals_one_minus_walked_yes_ask_vwap(tmp_path: Path) -> None:
    """(b): asks (0.30x2, 0.34x3), qty 4 -> walked ask VWAP 0.32, NO mark
    `Decimal("0.68")` -- computed through the real `walk_exit_vwap`, never
    hand-written. Bids at 0.90 are a decoy: NO must never touch them."""
    positions = _PositionsOpenStub()
    positions.set(_NO_IID, [_FakePosition(instrument_id=_NO_IID, avg_px_open=0.40, quantity=4)])
    accumulator = _RecordingAccumulator(
        _FakeRunningMax(lower_f=85, upper_f=85, source_observed_at_ns=WINDOW_OPEN_NS),
    )
    monitor, _reports = _build_monitor(
        tmp_path,
        positions_open=positions,
        accumulators={STATION: accumulator},
        leg_for=_leg_for_yes_no,
        sibling_for=_sibling_for_stub,
    )
    monitor.on_position_opened(
        _FakePosition(instrument_id=_NO_IID, avg_px_open=0.40, quantity=4), WINDOW_OPEN_NS,
    )  # type: ignore[arg-type]

    depth = _book_depth10(
        instrument_id=InstrumentId.from_str(_IID),
        bids=(("0.90", "10"),),
        asks=(("0.30", "2"), ("0.34", "3")),
        ts_ns=WINDOW_OPEN_NS,
    )
    monitor.on_depth(depth, WINDOW_OPEN_NS)  # type: ignore[arg-type]

    expected_vwap, sufficient = walk_exit_vwap(depth, "NO", 4)
    assert sufficient
    assert expected_vwap == Decimal("0.68")
    no_records = [r for r in monitor._buffer.records() if r.leg == "NO"]
    assert len(no_records) == 1
    assert no_records[0].mark_vwap == expected_vwap


def test_no_leg_registers_from_sibling_frame_when_yes_is_not_held(tmp_path: Path) -> None:
    """AC2: NO is held (in the cache) but YES is NOT -- the YES
    `_ensure_registered` returns `None` and must no longer return early;
    routing to the NO sibling still runs and lazily registers it."""
    positions = _PositionsOpenStub()
    positions.set(_NO_IID, [_FakePosition(instrument_id=_NO_IID, avg_px_open=0.40, quantity=1)])

    @dataclass
    class _FakeRecord:
        latched_at_ns: int

    accumulator = _RecordingAccumulator(
        _FakeRunningMax(lower_f=85, upper_f=85, source_observed_at_ns=WINDOW_OPEN_NS),
    )
    monitor, _reports = _build_monitor(
        tmp_path,
        positions_open=positions,
        accumulators={STATION: accumulator},
        leg_for=_leg_for_yes_no,
        sibling_for=_sibling_for_stub,
        latch_record=lambda *a, **k: _FakeRecord(latched_at_ns=WINDOW_OPEN_NS),
    )

    depth = _book_depth10(
        instrument_id=InstrumentId.from_str(_IID),
        bids=(),
        asks=(("0.30", "5"),),
        ts_ns=WINDOW_OPEN_NS,
    )
    monitor.on_depth(depth, WINDOW_OPEN_NS)  # type: ignore[arg-type]

    assert monitor.counters["monitor_errors"] == 0
    assert _IID not in monitor._positions  # YES was never held; never registered
    assert _NO_IID in monitor._positions
    assert monitor._positions[_NO_IID].entry_context == "reconciled"


def test_no_leg_registers_from_sibling_frame_reconciled_after_restart(tmp_path: Path) -> None:
    """AC2, restart shape: BOTH legs are already open at the venue but
    `PositionMonitor._positions` starts empty (a fresh process) -- the
    first YES depth frame must lazily register BOTH, exactly as a solo YES
    restart already does (`test_a_boot_inherited_position_lazily_registers_
    as_reconciled_no_record`)."""
    positions = _PositionsOpenStub()
    positions.set(_IID, [_FakePosition(instrument_id=_IID, avg_px_open=0.40, quantity=1)])
    positions.set(_NO_IID, [_FakePosition(instrument_id=_NO_IID, avg_px_open=0.40, quantity=1)])
    accumulator = _RecordingAccumulator(
        _FakeRunningMax(lower_f=85, upper_f=85, source_observed_at_ns=WINDOW_OPEN_NS),
    )
    monitor, _reports = _build_monitor(
        tmp_path,
        positions_open=positions,
        accumulators={STATION: accumulator},
        leg_for=_leg_for_yes_no,
        sibling_for=_sibling_for_stub,
    )

    depth = _book_depth10(
        instrument_id=InstrumentId.from_str(_IID),
        bids=(("0.90", "5"),),
        asks=(("0.30", "5"),),
        ts_ns=WINDOW_OPEN_NS,
    )
    monitor.on_depth(depth, WINDOW_OPEN_NS)  # type: ignore[arg-type]

    assert monitor.counters["monitor_errors"] == 0
    assert monitor._positions[_IID].entry_context == "reconciled_no_record"
    assert monitor._positions[_NO_IID].entry_context == "reconciled_no_record"


def test_both_legs_held_are_each_marked_from_one_frame(tmp_path: Path) -> None:
    positions = _PositionsOpenStub()
    positions.set(_IID, [_FakePosition(instrument_id=_IID, avg_px_open=0.40, quantity=1)])
    positions.set(_NO_IID, [_FakePosition(instrument_id=_NO_IID, avg_px_open=0.40, quantity=1)])
    accumulator = _RecordingAccumulator(
        _FakeRunningMax(lower_f=85, upper_f=85, source_observed_at_ns=WINDOW_OPEN_NS),
    )
    monitor, _reports = _build_monitor(
        tmp_path,
        positions_open=positions,
        accumulators={STATION: accumulator},
        leg_for=_leg_for_yes_no,
        sibling_for=_sibling_for_stub,
    )
    monitor.on_position_opened(
        _FakePosition(instrument_id=_IID, avg_px_open=0.40, quantity=1), WINDOW_OPEN_NS,
    )  # type: ignore[arg-type]
    monitor.on_position_opened(
        _FakePosition(instrument_id=_NO_IID, avg_px_open=0.40, quantity=1), WINDOW_OPEN_NS,
    )  # type: ignore[arg-type]

    depth = _book_depth10(
        instrument_id=InstrumentId.from_str(_IID),
        bids=(("0.30", "5"),),
        asks=(("0.35", "5"),),
        ts_ns=WINDOW_OPEN_NS,
    )
    monitor.on_depth(depth, WINDOW_OPEN_NS)  # type: ignore[arg-type]

    assert monitor.counters["monitor_errors"] == 0
    assert monitor.counters["evaluations"] == 2
    records = monitor._buffer.records()
    assert {r.leg for r in records} == {"YES", "NO"}
    yes_record = next(r for r in records if r.leg == "YES")
    no_record = next(r for r in records if r.leg == "NO")
    assert yes_record.mark_source == "depth_walk"
    assert no_record.mark_source == "depth_walk"
    assert monitor._positions[_IID].last_book_ts_ns == WINDOW_OPEN_NS
    assert monitor._positions[_NO_IID].last_book_ts_ns == WINDOW_OPEN_NS


def test_bid_only_frame_leaves_no_leg_missing(tmp_path: Path) -> None:
    positions = _PositionsOpenStub()
    positions.set(_IID, [_FakePosition(instrument_id=_IID, avg_px_open=0.40, quantity=1)])
    positions.set(_NO_IID, [_FakePosition(instrument_id=_NO_IID, avg_px_open=0.40, quantity=1)])
    accumulator = _RecordingAccumulator(
        _FakeRunningMax(lower_f=85, upper_f=85, source_observed_at_ns=WINDOW_OPEN_NS),
    )
    monitor, _reports = _build_monitor(
        tmp_path,
        positions_open=positions,
        accumulators={STATION: accumulator},
        leg_for=_leg_for_yes_no,
        sibling_for=_sibling_for_stub,
    )
    monitor.on_position_opened(
        _FakePosition(instrument_id=_IID, avg_px_open=0.40, quantity=1), WINDOW_OPEN_NS,
    )  # type: ignore[arg-type]
    monitor.on_position_opened(
        _FakePosition(instrument_id=_NO_IID, avg_px_open=0.40, quantity=1), WINDOW_OPEN_NS,
    )  # type: ignore[arg-type]

    depth = _book_depth10(
        instrument_id=InstrumentId.from_str(_IID),
        bids=(("0.30", "5"),),
        asks=(),
        ts_ns=WINDOW_OPEN_NS,
    )
    monitor.on_depth(depth, WINDOW_OPEN_NS)  # type: ignore[arg-type]

    records = monitor._buffer.records()
    yes_record = next(r for r in records if r.leg == "YES")
    no_record = next(r for r in records if r.leg == "NO")
    assert yes_record.mark_source == "depth_walk"  # nobody is selling YES: bids still mark it
    assert no_record.mark_source == "missing"


def test_no_leg_qty_beyond_displayed_asks_is_missing_never_partial(tmp_path: Path) -> None:
    positions = _PositionsOpenStub()
    positions.set(_NO_IID, [_FakePosition(instrument_id=_NO_IID, avg_px_open=0.40, quantity=10)])
    accumulator = _RecordingAccumulator(
        _FakeRunningMax(lower_f=85, upper_f=85, source_observed_at_ns=WINDOW_OPEN_NS),
    )
    monitor, _reports = _build_monitor(
        tmp_path,
        positions_open=positions,
        accumulators={STATION: accumulator},
        leg_for=_leg_for_yes_no,
        sibling_for=_sibling_for_stub,
    )
    monitor.on_position_opened(
        _FakePosition(instrument_id=_NO_IID, avg_px_open=0.40, quantity=10), WINDOW_OPEN_NS,
    )  # type: ignore[arg-type]

    depth = _book_depth10(
        instrument_id=InstrumentId.from_str(_IID),
        bids=(),
        asks=(("0.30", "5"),),  # only 5 displayed; held qty is 10
        ts_ns=WINDOW_OPEN_NS,
    )
    monitor.on_depth(depth, WINDOW_OPEN_NS)  # type: ignore[arg-type]

    no_records = [r for r in monitor._buffer.records() if r.leg == "NO"]
    assert len(no_records) == 1
    assert no_records[0].mark_source == "missing"
    assert no_records[0].mark_vwap is None


def test_stale_cached_sibling_book_refuses_book_stale_for_no(tmp_path: Path) -> None:
    """Edge case table: `last_book_ts_ns` is stamped from the routed frame
    like YES already gets; a LATER `on_observation` (no new depth) re-uses
    the cached book, so `book_staleness_ns` keeps growing -- the same
    staleness-accrual behaviour YES already has."""
    positions = _PositionsOpenStub()
    positions.set(_NO_IID, [_FakePosition(instrument_id=_NO_IID, avg_px_open=0.40, quantity=1)])
    accumulator = _RecordingAccumulator(
        _FakeRunningMax(lower_f=85, upper_f=85, source_observed_at_ns=WINDOW_OPEN_NS),
    )
    monitor, _reports = _build_monitor(
        tmp_path,
        positions_open=positions,
        accumulators={STATION: accumulator},
        leg_for=_leg_for_yes_no,
        sibling_for=_sibling_for_stub,
    )
    monitor.on_position_opened(
        _FakePosition(instrument_id=_NO_IID, avg_px_open=0.40, quantity=1), WINDOW_OPEN_NS,
    )  # type: ignore[arg-type]

    depth = _book_depth10(
        instrument_id=InstrumentId.from_str(_IID),
        bids=(("0.90", "5"),),
        asks=(("0.30", "5"),),
        ts_ns=WINDOW_OPEN_NS,
    )
    monitor.on_depth(depth, WINDOW_OPEN_NS)  # type: ignore[arg-type]
    assert monitor._positions[_NO_IID].last_book_ts_ns == WINDOW_OPEN_NS

    later_ns = WINDOW_OPEN_NS + 5 * _MINUTE_NS
    monitor.on_observation(STATION, later_ns)

    assert monitor._positions[_NO_IID].last_book_ts_ns == WINDOW_OPEN_NS  # never refreshed
    no_records = [r for r in monitor._buffer.records() if r.leg == "NO"]
    assert no_records[-1].book_staleness_ns == 5 * _MINUTE_NS


def test_a_no_leg_frame_is_never_rerouted(tmp_path: Path) -> None:
    """Edge case table: a Depth10 frame keyed by a `^no` id should never
    happen in production (the subscribe path never produces one), but even
    if it did, `sibling_for` returns `None` for a NO id -- no YES<->NO
    ping-pong. (The primary `_on_depth` path still evaluates the NO
    position directly off this frame, generically, exactly as it would for
    any other registered instrument id -- that is pre-existing, unrelated
    behaviour; the only thing under test here is that routing never sends
    it BACK to `_IID`.)"""
    positions = _PositionsOpenStub()
    positions.set(_NO_IID, [_FakePosition(instrument_id=_NO_IID, avg_px_open=0.40, quantity=1)])
    accumulator = _RecordingAccumulator(
        _FakeRunningMax(lower_f=85, upper_f=85, source_observed_at_ns=WINDOW_OPEN_NS),
    )
    calls: list[str] = []

    def _recording_sibling_for(iid: str) -> str | None:
        calls.append(iid)
        return _sibling_for_stub(iid)

    monitor, _reports = _build_monitor(
        tmp_path,
        positions_open=positions,
        accumulators={STATION: accumulator},
        leg_for=_leg_for_yes_no,
        sibling_for=_recording_sibling_for,
    )
    monitor.on_position_opened(
        _FakePosition(instrument_id=_NO_IID, avg_px_open=0.40, quantity=1), WINDOW_OPEN_NS,
    )  # type: ignore[arg-type]

    depth = _book_depth10(
        instrument_id=InstrumentId.from_str(_NO_IID),  # malformed in production: never happens
        bids=(("0.90", "5"),),
        asks=(("0.30", "5"),),
        ts_ns=WINDOW_OPEN_NS,
    )
    monitor.on_depth(depth, WINDOW_OPEN_NS)  # type: ignore[arg-type]

    assert calls == [_NO_IID]
    assert monitor.counters["monitor_errors"] == 0
    assert _IID not in monitor._positions  # never re-routed back to YES


def test_sibling_evaluation_error_is_counted_and_yes_record_is_unchanged(
    tmp_path: Path,
) -> None:
    positions = _PositionsOpenStub()
    positions.set(_IID, [_FakePosition(instrument_id=_IID, avg_px_open=0.40, quantity=1)])

    def _raising_positions_open(iid: str) -> Sequence[_FakePosition]:
        if iid == _NO_IID:
            raise RuntimeError("boom")
        return positions(iid)

    accumulator = _RecordingAccumulator(
        _FakeRunningMax(lower_f=85, upper_f=85, source_observed_at_ns=WINDOW_OPEN_NS),
    )
    monitor, reports = _build_monitor(
        tmp_path,
        positions_open=_raising_positions_open,
        accumulators={STATION: accumulator},
        leg_for=_leg_for_yes_no,
        sibling_for=_sibling_for_stub,
    )

    depth = _book_depth10(
        instrument_id=InstrumentId.from_str(_IID),
        bids=(("0.90", "5"),),
        asks=(("0.30", "5"),),
        ts_ns=WINDOW_OPEN_NS,
    )
    monitor.on_depth(depth, WINDOW_OPEN_NS)  # type: ignore[arg-type]

    assert monitor.counters["monitor_errors"] == 1, reports
    assert monitor.counters["evaluations"] == 1  # YES only -- the NO eval never ran
    records = monitor._buffer.records()
    assert {r.leg for r in records} == {"YES"}
    assert _NO_IID not in monitor._positions


def _run_e_scenario(
    *, tmp_path: Path, sibling_for: Callable[[str], str | None] | None,
) -> dict[str, object]:
    """Shared driver for `test_yes_leg_evidence_is_unchanged_by_no_sibling_
    routing`: the IDENTICAL script (one YES position registration, two YES
    depth pushes 6 minutes apart with the running max fixed above the rung
    -- confirming YES DEAD on the second push, RISING mode) run once with
    `sibling_for=None` and once with it set. NO is deliberately registered
    ONLY via the depth-routing path (never `on_position_opened`), so its
    presence in the second run is entirely attributable to `sibling_for`,
    never to shared test setup."""
    from breezy.strategy.current_rung_hold.exit_decider import decide_exit

    positions = _PositionsOpenStub()
    positions.set(_IID, [_FakePosition(instrument_id=_IID, avg_px_open=0.40, quantity=1)])
    positions.set(_NO_IID, [_FakePosition(instrument_id=_NO_IID, avg_px_open=0.40, quantity=1)])
    accumulator = _RecordingAccumulator(
        _FakeRunningMax(lower_f=90, upper_f=90, source_observed_at_ns=WINDOW_OPEN_NS),
    )
    submit_calls: list[object] = []
    offer_calls: list[object] = []
    monitor, _reports = _build_monitor(
        tmp_path,
        positions_open=positions,
        accumulators={STATION: accumulator},
        leg_for=_leg_for_yes_no,
        sibling_for=sibling_for,
        exit_decider=decide_exit,
        exit_manifest=_manifest_for_exit_test(
            exit_rule="crh_exit_v4:R_THREAT_PRIMARY+R_DEAD_BACKSTOP",
        ),
        exit_family_id="pm_us_crh_exit_v4",
        exit_client_order_id_factory=lambda: "exit-coid-e",
        submit_exit=submit_calls.append,
        record_exit_offer=offer_calls.append,
    )
    monitor.on_position_opened(
        _FakePosition(instrument_id=_IID, avg_px_open=0.40, quantity=1), WINDOW_OPEN_NS,
    )  # type: ignore[arg-type]

    depth1 = _book_depth10(
        instrument_id=InstrumentId.from_str(_IID),
        bids=(("0.30", "5"),),
        asks=(("0.90", "5"),),
        ts_ns=WINDOW_OPEN_NS,
    )
    monitor.on_depth(depth1, WINDOW_OPEN_NS)  # type: ignore[arg-type]

    later_ns = WINDOW_OPEN_NS + 6 * _MINUTE_NS
    accumulator._running_max = _FakeRunningMax(
        lower_f=90, upper_f=90, source_observed_at_ns=later_ns,
    )
    depth2 = _book_depth10(
        instrument_id=InstrumentId.from_str(_IID),
        bids=(("0.30", "5"),),
        asks=(("0.90", "5"),),
        ts_ns=later_ns,
    )
    monitor.on_depth(depth2, later_ns)  # type: ignore[arg-type]

    return {
        "yes_records": tuple(r for r in monitor._buffer.records() if r.leg == "YES"),
        "no_records": tuple(r for r in monitor._buffer.records() if r.leg == "NO"),
        # `PositionMarkRecord` is a Nautilus `Data` subclass with NO value
        # `__eq__` (identity only) -- project through its own `to_dict()`
        # for a real field-by-field comparison across the two separately
        # -constructed runs.
        "yes_record_dicts": tuple(
            r.to_dict() for r in monitor._buffer.records() if r.leg == "YES"
        ),
        "yes_offer_calls": tuple(c for c in offer_calls if getattr(c, "side", None) == "YES"),
        "counters": dict(monitor.counters),
        "yes_summary": (
            monitor._positions[_IID].history.last_state,
            monitor._positions[_IID].last_book_ts_ns,
            monitor._positions[_IID].last_held_qty,
        ),
    }


def test_yes_leg_evidence_is_unchanged_by_no_sibling_routing(tmp_path: Path) -> None:
    """(e), r1.2/r1.3 redesign: BOTH legs are potentially in play in BOTH
    runs (`sibling_for=None` and `sibling_for` set) -- the YES-only mark
    rows, YES-only offer-tape rows, and the YES position's own tracked
    summary must be byte-identical either way, and the ONLY counter delta
    is exactly the NO-driven rows `sibling_for` adds."""
    run_a = _run_e_scenario(tmp_path=tmp_path / "a", sibling_for=None)
    run_b = _run_e_scenario(tmp_path=tmp_path / "b", sibling_for=_sibling_for_stub)

    # Positive controls (r1.3 architect fix): the scenario actually fired.
    assert run_a["yes_records"], "YES mark rows must be non-empty"
    assert run_a["yes_offer_calls"], "YES offer-tape rows must be non-empty"
    assert run_a["no_records"] == ()  # sibling_for=None: NO never even registers
    assert len(run_b["no_records"]) >= 1, "at least 1 NO row once sibling_for is set"

    # The YES-only facts are byte-identical regardless of sibling routing.
    assert run_a["yes_record_dicts"] == run_b["yes_record_dicts"]
    assert run_a["yes_offer_calls"] == run_b["yes_offer_calls"]
    assert run_a["yes_summary"] == run_b["yes_summary"]

    # r1.3 counter semantics: the ONLY delta is exactly the NO-driven rows.
    no_evaluations = len(run_b["no_records"])  # every NO eval here emits
    a_counters, b_counters = run_a["counters"], run_b["counters"]
    assert b_counters["evaluations"] - a_counters["evaluations"] == no_evaluations
    assert b_counters["emitted"] - a_counters["emitted"] == len(run_b["no_records"])
    assert a_counters["monitor_errors"] == 0
    assert b_counters["monitor_errors"] == 0


def test_shared_mark_buffer_eviction_with_no_rows_is_counted(tmp_path: Path) -> None:
    """r1.2/r1.3: once both legs share ONE `MarkBuffer`, a NO row can evict
    a YES row (and vice versa). States and bounds the coupling with a tiny
    `maxlen=3` (production `maxlen` is 2048, headroom at the live
    instrument count) -- eviction is COUNTED, never a raise."""
    positions = _PositionsOpenStub()
    positions.set(_IID, [_FakePosition(instrument_id=_IID, avg_px_open=0.40, quantity=1)])
    positions.set(_NO_IID, [_FakePosition(instrument_id=_NO_IID, avg_px_open=0.40, quantity=1)])
    accumulator = _RecordingAccumulator(
        _FakeRunningMax(lower_f=85, upper_f=85, source_observed_at_ns=WINDOW_OPEN_NS),
    )
    monitor, _reports = _build_monitor(
        tmp_path,
        positions_open=positions,
        accumulators={STATION: accumulator},
        leg_for=_leg_for_yes_no,
        sibling_for=_sibling_for_stub,
        buffer=MarkBuffer(maxlen=3),
    )
    monitor.on_position_opened(
        _FakePosition(instrument_id=_IID, avg_px_open=0.40, quantity=1), WINDOW_OPEN_NS,
    )  # type: ignore[arg-type]
    monitor.on_position_opened(
        _FakePosition(instrument_id=_NO_IID, avg_px_open=0.40, quantity=1), WINDOW_OPEN_NS,
    )  # type: ignore[arg-type]

    def _push(ts_ns: int) -> None:
        depth = _book_depth10(
            instrument_id=InstrumentId.from_str(_IID),
            bids=(("0.30", "5"),),
            asks=(("0.90", "5"),),
            ts_ns=ts_ns,
        )
        monitor.on_depth(depth, ts_ns)  # type: ignore[arg-type]

    _push(WINDOW_OPEN_NS)  # 2 emits (YES + NO)
    _push(WINDOW_OPEN_NS + 61_000_000_000)  # heartbeat elapsed -> 2 more emits, 1 must evict

    assert monitor.counters["monitor_errors"] == 0
    assert monitor.counters["monitor_marks_dropped"] > 0
    assert len(monitor._buffer.records()) == 3  # capped at maxlen
