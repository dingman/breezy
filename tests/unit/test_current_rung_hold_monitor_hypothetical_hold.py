"""RED-first tests for the INC-8 hypothetical-hold corpus (offline analysis
only, build-time -- ``docs/plans/INTRADAY_POSITION_MONITOR_2026-09-15.md``
§6 INC-8, Rev 2.1 addendum A4/P5/P6).

``scripts/analysis/`` carries no ``__init__.py`` and is not on the default
import path, so the module under test is loaded dynamically -- the SAME
pattern ``test_mb_current_rung_edge_study.py``/
``test_current_rung_hold_paper_replay.py`` use for their own sibling
scripts.

Every frame below is hand-built and obviously synthetic (no venue capture is
read) -- see ``tests/support/synthetic_binary_tape.py`` for the repo's
standing rationale on why synthetic market data is used here instead of a
capture.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from nautilus_trader.model.data import BookOrder, OrderBookDepth10
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity

from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
from breezy.strategy.current_rung_hold.decision import DecisionInputs, Take, evaluate_decision
from breezy.strategy.current_rung_hold.monitor_decision import Verdict
from breezy.strategy.current_rung_hold.monitor_records import PositionMonitorSummary
from breezy.strategy.weather_common.running_extreme import RunningExtremeAccumulator

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"

_STD_UTC_OFFSET_HOURS = -8.0  # Pacific standard time, matches SFO
_STATION = "SFO"
_SEASON = "DJF"  # January
_CLIMATE_DAY = dt.date(2026, 1, 15)
_FEE_COEFFICIENT = Decimal("0.06")
_TZ = dt.timezone(dt.timedelta(hours=_STD_UTC_OFFSET_HOURS))
_RUNG = (86, 87)
_LADDER = ((86, 87),)
_INSTRUMENT_ID = "sfo-86-87.POLYMARKET_US"
_STALE_BOUND_NS = CurrentRungHoldConfig().stale_observation_minutes * 60_000_000_000


def _load_module() -> ModuleType:
    if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))
    path = _SCRIPTS_ANALYSIS_DIR / "current_rung_hold_monitor_hypothetical_hold.py"
    spec = importlib.util.spec_from_file_location(
        "current_rung_hold_monitor_hypothetical_hold", path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def hh() -> ModuleType:
    return _load_module()


def _ns_at(hour: int, minute: int = 0) -> int:
    local_dt = dt.datetime(
        _CLIMATE_DAY.year, _CLIMATE_DAY.month, _CLIMATE_DAY.day, hour, minute, tzinfo=_TZ,
    )
    return int(local_dt.timestamp() * 1_000_000_000)


def _push_metar(accumulator: RunningExtremeAccumulator, ts_ns: int, fahrenheit: int) -> None:
    """Push an EXACT (METAR) reading at ``fahrenheit``, ``received_at_ns ==
    observed_at_ns`` -- reproduces the archive oracle (``running_extreme.py``'s
    own guidance for this exact use case)."""
    c_tenths = round((fahrenheit - 32) * 5 / 9 * 10)
    accumulator.push(ts_ns, c_tenths, 5, True, ts_ns)


def _order(side: OrderSide, price: str, size: str) -> BookOrder:
    return BookOrder(side, Price(float(price), 2), Quantity(float(size), 2), 0)


def _depth(
    *, bids: tuple[tuple[str, str], ...], asks: tuple[tuple[str, str], ...], ts_ns: int,
    instrument_id: str = _INSTRUMENT_ID,
) -> OrderBookDepth10:
    """A real ``OrderBookDepth10`` -- equal bid/ask lengths, zero-size filler
    on the shorter side (mirrors ``test_current_rung_hold_monitor_evidence.py
    ::_depth``)."""
    iid = InstrumentId.from_str(instrument_id)
    bid_orders = [_order(OrderSide.BUY, p, s) for p, s in bids]
    ask_orders = [_order(OrderSide.SELL, p, s) for p, s in asks]
    n = max(len(bid_orders), len(ask_orders), 1)
    while len(bid_orders) < n:
        bid_orders.append(_order(OrderSide.BUY, "0", "0"))
    while len(ask_orders) < n:
        ask_orders.append(_order(OrderSide.SELL, "0", "0"))
    return OrderBookDepth10(
        instrument_id=iid,
        bids=bid_orders,
        asks=ask_orders,
        bid_counts=[1] * len(bid_orders),
        ask_counts=[1] * len(ask_orders),
        flags=0,
        sequence=0,
        ts_event=ts_ns,
        ts_init=ts_ns,
    )


def _accumulator_with_entry_reading() -> RunningExtremeAccumulator:
    accumulator = RunningExtremeAccumulator(std_utc_offset_hours=_STD_UTC_OFFSET_HOURS)
    # Within the 50-min `stale_observation_minutes` bound of every 14:xx
    # evaluation instant used below (`decision.py`'s staleness gate).
    _push_metar(accumulator, _ns_at(13, 30), 86)
    return accumulator


def _config() -> CurrentRungHoldConfig:
    return CurrentRungHoldConfig(stations=(_STATION,))


def _take_at(hh: ModuleType, ts_ns: int) -> Any:
    return hh.HypotheticalTake(
        station=_STATION,
        climate_day=_CLIMATE_DAY,
        season=_SEASON,
        instrument_id=_INSTRUMENT_ID,
        leg="YES",
        ts_ns=ts_ns,
        hour_lst=14,
        rung=_RUNG,
        ask=Decimal("0.40"),
        size=5,
        p_hold_at_entry=Decimal("0.6293"),
        held_qty=1,
    )


# ---------------------------------------------------------------------------
# Selection: first-executable-snapshot parity with evaluate_decision (L-34)
# ---------------------------------------------------------------------------


def test_selection_picks_the_first_executable_snapshot_not_a_later_cheaper_one(
    hh: ModuleType,
) -> None:
    # Arrange: frame 1 (14:00) is unexecutable (ask above the band); frame 2
    # (14:05) is executable and a later cheaper snapshot is never searched
    # for beyond it.
    accumulator = _accumulator_with_entry_reading()
    refused_frame = _depth(bids=(), asks=(("0.97", "5"),), ts_ns=_ns_at(14, 0))
    taken_frame = _depth(bids=(), asks=(("0.40", "5"),), ts_ns=_ns_at(14, 5))
    later_cheaper_frame = _depth(bids=(), asks=(("0.10", "5"),), ts_ns=_ns_at(14, 10))
    tape = hh.InstrumentTape(
        instrument_id=_INSTRUMENT_ID,
        rung=_RUNG,
        depth_frames=(refused_frame, taken_frame, later_cheaper_frame),
    )

    # Act
    take = hh.select_hypothetical_holds(
        station=_STATION,
        climate_day=_CLIMATE_DAY,
        std_utc_offset_hours=_STD_UTC_OFFSET_HOURS,
        config=_config(),
        fee_coefficient=_FEE_COEFFICIENT,
        ladder=_LADDER,
        instruments=(tape,),
        accumulator=accumulator,
    )

    # Assert
    assert take is not None
    assert take.ts_ns == _ns_at(14, 5)
    assert take.ask == Decimal("0.40")

    # Parity: replaying the SAME snapshot through evaluate_decision directly
    # must agree on the exact Take.
    running_max = accumulator.value_at(_ns_at(14, 5))
    assert running_max is not None
    inputs = DecisionInputs(
        station=_STATION,
        climate_day=_CLIMATE_DAY,
        now_ns=_ns_at(14, 5),
        ladder=_LADDER,
        fee_coefficient=_FEE_COEFFICIENT,
        ask=Decimal("0.40"),
        size=5,
        running_max=running_max,
        staleness_ns=accumulator.staleness_ns(_ns_at(14, 5)),
        config=_config(),
        season=_SEASON,
        hour_lst=14,
        width_code=0,
        m_code=0,
        latch_consumed=False,
    )
    decision = evaluate_decision(inputs)
    assert isinstance(decision, Take)
    assert decision.limit_price == take.ask
    assert decision.p_hold_lower == take.p_hold_at_entry


def test_selection_returns_none_when_no_snapshot_is_executable(hh: ModuleType) -> None:
    accumulator = _accumulator_with_entry_reading()
    tape = hh.InstrumentTape(
        instrument_id=_INSTRUMENT_ID,
        rung=_RUNG,
        depth_frames=(_depth(bids=(), asks=(("0.97", "5"),), ts_ns=_ns_at(14, 0)),),
    )

    take = hh.select_hypothetical_holds(
        station=_STATION,
        climate_day=_CLIMATE_DAY,
        std_utc_offset_hours=_STD_UTC_OFFSET_HOURS,
        config=_config(),
        fee_coefficient=_FEE_COEFFICIENT,
        ladder=_LADDER,
        instruments=(tape,),
        accumulator=accumulator,
    )

    assert take is None


def test_selection_ignores_frames_outside_the_decision_window(hh: ModuleType) -> None:
    accumulator = _accumulator_with_entry_reading()
    # 18:00 LST is outside [12, 17) -- an otherwise-executable ask must never
    # be taken there.
    tape = hh.InstrumentTape(
        instrument_id=_INSTRUMENT_ID,
        rung=_RUNG,
        depth_frames=(_depth(bids=(), asks=(("0.40", "5"),), ts_ns=_ns_at(18, 0)),),
    )

    take = hh.select_hypothetical_holds(
        station=_STATION,
        climate_day=_CLIMATE_DAY,
        std_utc_offset_hours=_STD_UTC_OFFSET_HOURS,
        config=_config(),
        fee_coefficient=_FEE_COEFFICIENT,
        ladder=_LADDER,
        instruments=(tape,),
        accumulator=accumulator,
    )

    assert take is None


# ---------------------------------------------------------------------------
# replay_monitor: no-look-ahead pin
# ---------------------------------------------------------------------------


def test_replay_monitor_refuses_a_depth_frame_at_or_before_the_take(hh: ModuleType) -> None:
    accumulator = _accumulator_with_entry_reading()
    take = _take_at(hh, _ns_at(14, 5))
    same_instant_frame = _depth(bids=(("0.10", "5"),), asks=(("0.40", "5"),), ts_ns=take.ts_ns)

    with pytest.raises(hh.LookAheadError):
        hh.replay_monitor(
            take=take,
            accumulator=accumulator,
            std_utc_offset_hours=_STD_UTC_OFFSET_HOURS,
            fee_coefficient=_FEE_COEFFICIENT,
            stale_observation_bound_ns=_STALE_BOUND_NS,
            subsequent_depth_frames=(same_instant_frame,),
            subsequent_observation_ts_ns=(),
            tmax_f=90,
        )


def test_replay_monitor_refuses_an_observation_at_or_before_the_take(hh: ModuleType) -> None:
    accumulator = _accumulator_with_entry_reading()
    take = _take_at(hh, _ns_at(14, 5))

    with pytest.raises(hh.LookAheadError):
        hh.replay_monitor(
            take=take,
            accumulator=accumulator,
            std_utc_offset_hours=_STD_UTC_OFFSET_HOURS,
            fee_coefficient=_FEE_COEFFICIENT,
            stale_observation_bound_ns=_STALE_BOUND_NS,
            subsequent_depth_frames=(),
            subsequent_observation_ts_ns=(take.ts_ns,),
            tmax_f=90,
        )


def test_a_future_stamped_observation_never_changes_the_selected_take(hh: ModuleType) -> None:
    """The no-look-ahead pin at selection time: `RunningExtremeAccumulator
    .value_at`/`.staleness_ns` gate on `now_ns`, so a row observed AFTER
    every evaluated frame must never change which snapshot is taken."""
    tape = hh.InstrumentTape(
        instrument_id=_INSTRUMENT_ID,
        rung=_RUNG,
        depth_frames=(_depth(bids=(), asks=(("0.40", "5"),), ts_ns=_ns_at(14, 5)),),
    )

    without_future_row = _accumulator_with_entry_reading()
    take_without = hh.select_hypothetical_holds(
        station=_STATION, climate_day=_CLIMATE_DAY, std_utc_offset_hours=_STD_UTC_OFFSET_HOURS,
        config=_config(), fee_coefficient=_FEE_COEFFICIENT, ladder=_LADDER,
        instruments=(tape,), accumulator=without_future_row,
    )

    with_future_row = _accumulator_with_entry_reading()
    # A future reading that would (if consulted) blow the running max past
    # the rung and make this snapshot ambiguous/DEAD -- it must be invisible.
    _push_metar(with_future_row, _ns_at(16, 0), 95)
    take_with = hh.select_hypothetical_holds(
        station=_STATION, climate_day=_CLIMATE_DAY, std_utc_offset_hours=_STD_UTC_OFFSET_HOURS,
        config=_config(), fee_coefficient=_FEE_COEFFICIENT, ladder=_LADDER,
        instruments=(tape,), accumulator=with_future_row,
    )

    assert take_without is not None
    assert take_with is not None
    assert take_without.ts_ns == take_with.ts_ns
    assert take_without.ask == take_with.ask


# ---------------------------------------------------------------------------
# replay_monitor: DEAD / MISSING_STOP / recovery / settlement join
# ---------------------------------------------------------------------------


def test_a_dead_scenario_with_no_fillable_exit_is_missing_stop_and_counts_as_settled_loss(
    hh: ModuleType,
) -> None:
    # Arrange: running max drifts from 86 (the entry rung) to 95 -- well past
    # rung_high=87 -- confirmed over two distinct instants 10 minutes apart
    # (>= the 5 min DEAD span guard). No bid ever appears -- MISSING_STOP.
    accumulator = _accumulator_with_entry_reading()
    take = _take_at(hh, _ns_at(14, 5))
    _push_metar(accumulator, _ns_at(14, 10), 95)
    _push_metar(accumulator, _ns_at(14, 20), 95)
    obs_ts = (_ns_at(14, 10), _ns_at(14, 20))
    empty_book_frame = _depth(bids=(), asks=(), ts_ns=_ns_at(14, 25))

    # Act
    summary, diagnostics = hh.replay_monitor(
        take=take,
        accumulator=accumulator,
        std_utc_offset_hours=_STD_UTC_OFFSET_HOURS,
        fee_coefficient=_FEE_COEFFICIENT,
        stale_observation_bound_ns=_STALE_BOUND_NS,
        subsequent_depth_frames=(empty_book_frame,),
        subsequent_observation_ts_ns=obs_ts,
        tmax_f=95,  # settles YES on the 95F rung, i.e. NOT on the held [86,87] rung
    )

    # Assert
    assert diagnostics.dead_evaluations >= 1
    assert diagnostics.missing_stop_evaluations >= 1
    assert summary.entry_context == "hypothetical"
    assert summary.trial_id.startswith(hh.TRIAL_ID_PREFIX)
    assert summary.settled_held is False
    assert summary.settled_pnl is not None
    assert summary.settled_pnl < 0
    assert len(diagnostics.dead_confirmation_spans_ns) == 1
    assert diagnostics.dead_confirmation_spans_ns[0] == _ns_at(14, 20) - _ns_at(14, 10)


def test_a_dead_scenario_with_a_fillable_exit_is_exit_recommended(hh: ModuleType) -> None:
    accumulator = _accumulator_with_entry_reading()
    take = _take_at(hh, _ns_at(14, 5))
    _push_metar(accumulator, _ns_at(14, 10), 95)
    _push_metar(accumulator, _ns_at(14, 20), 95)
    # Arrives 1 minute before the CONFIRMING observation (well inside the
    # 3-min `_BOOK_STALE_NS` bound), so the confirming evaluation itself
    # already sees a fresh, fillable book.
    fillable_frame = _depth(bids=(("0.05", "5"),), asks=(), ts_ns=_ns_at(14, 19))

    summary, diagnostics = hh.replay_monitor(
        take=take,
        accumulator=accumulator,
        std_utc_offset_hours=_STD_UTC_OFFSET_HOURS,
        fee_coefficient=_FEE_COEFFICIENT,
        stale_observation_bound_ns=_STALE_BOUND_NS,
        subsequent_depth_frames=(fillable_frame,),
        subsequent_observation_ts_ns=(_ns_at(14, 10), _ns_at(14, 20)),
        tmax_f=95,
    )

    assert diagnostics.dead_evaluations >= 1
    assert len(diagnostics.exit_recommended_recoverable_values) >= 1
    assert summary.recoverable_value_at_signal is not None


def test_two_depth_only_ticks_on_one_unchanged_observation_never_confirm_dead(
    hh: ModuleType,
) -> None:
    """2026-09-15 correction pin: DEAD confirmation is keyed on the
    OBSERVATION's own instant (``MonitorEvidence.observed_at_ns`` /
    ``monitor_decision._dead_confirm_key``), never the evaluation's own
    ``ts_ns``. A SINGLE observation that qualifies as a dead-candidate,
    re-evaluated by two depth-only ticks minutes apart with no NEW
    observation in between, must never look like two independent confirming
    readings."""
    accumulator = _accumulator_with_entry_reading()
    take = _take_at(hh, _ns_at(14, 5))
    # ONE observation qualifies dead_candidate (running max at 95F, past
    # rung_high=87) -- no second, distinct observation ever arrives.
    _push_metar(accumulator, _ns_at(14, 10), 95)
    depth_a = _depth(bids=(), asks=(("0.40", "5"),), ts_ns=_ns_at(14, 12))
    depth_b = _depth(bids=(), asks=(("0.40", "5"),), ts_ns=_ns_at(14, 20))

    summary, diagnostics = hh.replay_monitor(
        take=take,
        accumulator=accumulator,
        std_utc_offset_hours=_STD_UTC_OFFSET_HOURS,
        fee_coefficient=_FEE_COEFFICIENT,
        stale_observation_bound_ns=_STALE_BOUND_NS,
        subsequent_depth_frames=(depth_a, depth_b),
        subsequent_observation_ts_ns=(_ns_at(14, 10),),
        tmax_f=86,
    )

    # The single observation is a dead CANDIDATE (reason "dead_candidate"),
    # but with only one distinct observed instant ever recorded, DEAD can
    # never be CONFIRMED (requires >= 2 distinct observed instants).
    assert diagnostics.dead_evaluations == 0
    assert diagnostics.reason_code_counts.get("dead_candidate", 0) >= 1
    assert summary.verdict_at_signal != Verdict.EXIT_RECOMMENDED.value


def test_a_recovering_p_hold_dip_never_reaches_dead_or_exit(hh: ModuleType) -> None:
    """A temporary p_hold drop that recovers before confirmation must never
    fire DEAD/EXIT -- only THREATENED-candidate reason codes, then a return
    to ALIVE."""
    accumulator = _accumulator_with_entry_reading()
    take = _take_at(hh, _ns_at(14, 5))
    # Running max nudges the cell's m_code by one degree (a `p_hold` DROP
    # candidate, per the archive table), then returns -- never past the rung.
    _push_metar(accumulator, _ns_at(14, 10), 87)
    _push_metar(accumulator, _ns_at(14, 15), 86)
    frame = _depth(bids=(("0.10", "5"),), asks=(("0.40", "5"),), ts_ns=_ns_at(14, 20))

    summary, diagnostics = hh.replay_monitor(
        take=take,
        accumulator=accumulator,
        std_utc_offset_hours=_STD_UTC_OFFSET_HOURS,
        fee_coefficient=_FEE_COEFFICIENT,
        stale_observation_bound_ns=_STALE_BOUND_NS,
        subsequent_depth_frames=(frame,),
        subsequent_observation_ts_ns=(_ns_at(14, 10), _ns_at(14, 15)),
        tmax_f=86,
    )

    assert diagnostics.dead_evaluations == 0
    assert diagnostics.missing_stop_evaluations == 0
    assert summary.verdict_at_signal != Verdict.EXIT_RECOMMENDED.value


def test_archive_covered_evaluations_denominator_excludes_hours_outside_12_16(
    hh: ModuleType,
) -> None:
    """P5: the THREATENED/DEAD denominator is archive-covered EVALUATIONS
    (hours 12-16), never wall-clock hold duration."""
    accumulator = _accumulator_with_entry_reading()
    take = _take_at(hh, _ns_at(14, 5))
    inside_hours_frame = _depth(bids=(("0.10", "5"),), asks=(("0.40", "5"),), ts_ns=_ns_at(14, 30))
    outside_hours_frame = _depth(bids=(("0.10", "5"),), asks=(("0.40", "5"),), ts_ns=_ns_at(20, 0))

    summary, diagnostics = hh.replay_monitor(
        take=take,
        accumulator=accumulator,
        std_utc_offset_hours=_STD_UTC_OFFSET_HOURS,
        fee_coefficient=_FEE_COEFFICIENT,
        stale_observation_bound_ns=_STALE_BOUND_NS,
        subsequent_depth_frames=(inside_hours_frame, outside_hours_frame),
        subsequent_observation_ts_ns=(),
        tmax_f=86,
    )

    assert summary.total_frames == 2
    assert diagnostics.archive_covered_evaluations == 1


def test_summary_carries_hypothetical_entry_context_and_prefixed_trial_id(
    hh: ModuleType,
) -> None:
    accumulator = _accumulator_with_entry_reading()
    take = _take_at(hh, _ns_at(14, 5))
    frame = _depth(bids=(("0.10", "5"),), asks=(("0.40", "5"),), ts_ns=_ns_at(14, 30))

    summary, _diagnostics = hh.replay_monitor(
        take=take,
        accumulator=accumulator,
        std_utc_offset_hours=_STD_UTC_OFFSET_HOURS,
        fee_coefficient=_FEE_COEFFICIENT,
        stale_observation_bound_ns=_STALE_BOUND_NS,
        subsequent_depth_frames=(frame,),
        subsequent_observation_ts_ns=(),
        tmax_f=86,
    )

    assert summary.entry_context == "hypothetical"
    assert summary.trial_id == (
        f"{hh.TRIAL_ID_PREFIX}{_STATION}:{_CLIMATE_DAY.isoformat()}:{_INSTRUMENT_ID}"
    )
    assert summary.leg == "YES"
    assert summary.monitor_intervened is False


def test_replay_with_no_subsequent_events_still_produces_a_valid_summary(hh: ModuleType) -> None:
    accumulator = _accumulator_with_entry_reading()
    take = _take_at(hh, _ns_at(14, 5))

    summary, diagnostics = hh.replay_monitor(
        take=take,
        accumulator=accumulator,
        std_utc_offset_hours=_STD_UTC_OFFSET_HOURS,
        fee_coefficient=_FEE_COEFFICIENT,
        stale_observation_bound_ns=_STALE_BOUND_NS,
        subsequent_depth_frames=(),
        subsequent_observation_ts_ns=(),
        tmax_f=86,
    )

    assert summary.total_frames == 0
    assert summary.held_duration_ns == 0
    assert summary.first_signal_ts_ns is None
    assert diagnostics.dead_evaluations == 0


# ---------------------------------------------------------------------------
# build_corpus_report: A4 calibration gate, zero-usable-days path
# ---------------------------------------------------------------------------


def _diagnostics(hh: ModuleType, **overrides: object) -> object:
    base: dict[str, object] = {
        "archive_covered_evaluations": 1,
        "threatened_evaluations": 0,
        "dead_evaluations": 0,
        "missing_stop_evaluations": 0,
        "reason_code_counts": {},
        "dead_confirmation_spans_ns": (),
        "threatened_confirmation_spans_ns": (),
        "exit_recommended_recoverable_values": (),
    }
    base.update(overrides)
    return hh.ReplayDiagnostics(**base)


def _result_for(
    hh: ModuleType, *, station: str, climate_day: dt.date, settled_pnl: Decimal | None,
    dead_evaluations: int = 0,
) -> tuple[object, PositionMonitorSummary, object]:
    take = hh.HypotheticalTake(
        station=station, climate_day=climate_day, season=_SEASON,
        instrument_id=_INSTRUMENT_ID, leg="YES", ts_ns=_ns_at(14, 5), hour_lst=14,
        rung=_RUNG, ask=Decimal("0.40"), size=5, p_hold_at_entry=Decimal("0.6293"), held_qty=1,
    )
    summary = PositionMonitorSummary(
        trial_id=f"{hh.TRIAL_ID_PREFIX}{station}:{climate_day.isoformat()}:{_INSTRUMENT_ID}",
        instrument_id=_INSTRUMENT_ID, station=station, climate_day=climate_day.isoformat(),
        leg="YES", entry_context="hypothetical", monitor_seq=1, fill_px=Decimal("0.40"),
        held_qty=Decimal(1), mae=Decimal(0), mfe=Decimal(0), first_signal_ts_ns=None,
        first_signal_hour_lst=None, first_signal_state=None, verdict_at_signal=None,
        recoverable_value_at_signal=None, held_duration_ns=0, total_frames=1,
        mark_missing_frames=0, settled_pnl=settled_pnl, settled_held=None,
    )
    diagnostics = _diagnostics(hh, dead_evaluations=dead_evaluations)
    return take, summary, diagnostics


def test_build_corpus_report_emits_a_report_for_zero_usable_station_days(hh: ModuleType) -> None:
    report = hh.build_corpus_report(
        results=(),
        skipped_station_days=(
            hh.SkippedStationDay(station=_STATION, climate_day=_CLIMATE_DAY, reason="no_depth10"),
        ),
        window_start=_CLIMATE_DAY,
        window_end=_CLIMATE_DAY,
        stations=(_STATION,),
        generated_at_ns=0,
    )

    assert report.n_trials == 0
    assert report.usable_station_days == 0
    assert report.calibration_status == "UNCALIBRATED"
    assert report.dead_precision is None
    assert report.threatened_base_rate is None
    assert report.missing_stop_rate is None
    assert len(report.skipped_station_days) == 1


def test_build_corpus_report_is_uncalibrated_below_the_floor_but_still_counts(
    hh: ModuleType,
) -> None:
    results = [
        _result_for(
            hh, station=_STATION, climate_day=_CLIMATE_DAY + dt.timedelta(days=i),
            settled_pnl=Decimal("-0.40"), dead_evaluations=1,
        )
        for i in range(3)
    ]
    assert len(results) < hh.CALIBRATION_FLOOR_STATION_DAYS

    report = hh.build_corpus_report(
        results=results, skipped_station_days=(), window_start=_CLIMATE_DAY,
        window_end=_CLIMATE_DAY, stations=(_STATION,), generated_at_ns=0,
    )

    assert report.calibration_status == "UNCALIBRATED"
    assert report.n_trials == 3
    assert report.dead_precision is None  # never published below the floor
    assert report.dead_precision_numerator == 3
    assert report.dead_precision_denominator == 3


def test_build_corpus_report_publishes_dead_precision_once_calibrated(hh: ModuleType) -> None:
    losing = [
        _result_for(
            hh, station=_STATION, climate_day=_CLIMATE_DAY + dt.timedelta(days=i),
            settled_pnl=Decimal("-0.40"), dead_evaluations=1,
        )
        for i in range(hh.CALIBRATION_FLOOR_STATION_DAYS)
    ]

    report = hh.build_corpus_report(
        results=losing, skipped_station_days=(), window_start=_CLIMATE_DAY,
        window_end=_CLIMATE_DAY, stations=(_STATION,), generated_at_ns=0,
    )

    assert report.usable_station_days == hh.CALIBRATION_FLOOR_STATION_DAYS
    assert report.calibration_status == "CALIBRATED"
    assert report.dead_precision == Decimal(1)
    assert report.dead_precision_numerator == hh.CALIBRATION_FLOOR_STATION_DAYS
    assert report.dead_precision_denominator == hh.CALIBRATION_FLOOR_STATION_DAYS


def test_build_corpus_report_to_dict_is_json_serializable(hh: ModuleType) -> None:
    report = hh.build_corpus_report(
        results=(), skipped_station_days=(), window_start=_CLIMATE_DAY,
        window_end=_CLIMATE_DAY, stations=(_STATION,), generated_at_ns=0,
    )

    json.dumps(report.to_dict())  # must not raise


def test_archive_hours_constant_matches_the_window(hh: ModuleType) -> None:
    assert hh.ARCHIVE_HOURS == (12, 13, 14, 15, 16)
