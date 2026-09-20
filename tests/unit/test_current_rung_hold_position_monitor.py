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
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from nautilus_trader.model.enums import OmsType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.position import Position
from nautilus_trader.test_kit.stubs.events import TestEventStubs

from breezy.strategy.current_rung_hold.monitor_decision import (
    MonitorHistory,
    ThesisState,
    Verdict,
    evaluate_monitor,
)
from breezy.strategy.current_rung_hold.monitor_evidence import MonitorEvidence
from breezy.strategy.current_rung_hold.monitor_store import (
    MarkBuffer,
    read_monitor_summaries,
)
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
        buffer=MarkBuffer(),
        catalog_root=tmp_path / "monitor",
        summaries_dir=tmp_path / "monitor" / "summaries",
        report=report if report is not None else _default_report,
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
) -> PositionMonitor:
    from breezy.adapters.polymarket_us.symbology import leg_of
    from breezy.strategy.current_rung_hold.strategy import _local_hour

    def _positions_open(iid: str):
        return strategy.cache.positions_open(instrument_id=InstrumentId.from_str(iid))

    def _latch_record(station: str, climate_day: str, *, key_instrument_id: str | None = None):
        if strategy._latch is None:
            return None
        return strategy._latch.record_with_legacy_fallback(
            station, climate_day, key_instrument_id=key_instrument_id,
        )

    def _rung_geometry(iid: str):
        return strategy._facts.get(iid)

    def _fee_coefficient_for(iid: str) -> Decimal:
        instrument = strategy.cache.instrument(InstrumentId.from_str(iid))
        fee = strategy._guarded_fee_coefficient(instrument)
        if fee is None:
            raise ValueError(f"unknown fee schedule for {iid}")
        return fee

    def _leg_for(iid: str) -> str:
        return "NO" if leg_of(InstrumentId.from_str(iid)) == "no" else "YES"

    def _station_for(iid: str) -> str:
        return strategy._facts[iid].settlement_station

    def _climate_day_for(iid: str) -> str:
        return strategy._facts[iid].climate_day.isoformat()

    def _hour_lst_for(station: str, now_ns: int) -> int:
        offset = strategy._std_utc_offset_hours_by_station[station]
        return _local_hour(now_ns, offset)

    return PositionMonitor(
        clock_ns=strategy.clock.timestamp_ns,
        positions_open=_positions_open,  # type: ignore[arg-type]
        accumulators=strategy._accumulators,
        latch_record=_latch_record,  # type: ignore[arg-type]
        rung_geometry=_rung_geometry,  # type: ignore[arg-type]
        fee_coefficient_for=_fee_coefficient_for,
        leg_for=_leg_for,  # type: ignore[arg-type]
        station_for=_station_for,
        climate_day_for=_climate_day_for,
        hour_lst_for=_hour_lst_for,
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


def _manifest_for_exit_test(*, exit_rule: str | None) -> FamilyManifest:
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
