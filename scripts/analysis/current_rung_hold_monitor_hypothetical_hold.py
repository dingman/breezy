"""INC-8 -- the hypothetical-hold corpus for the intra-day position monitor.

Spec: ``docs/plans/INTRADAY_POSITION_MONITOR_2026-09-15.md`` Rev 2 sec 0/6
(INC-8 row) and the Rev 2.1 addendum (A4, P5, P6). Offline analysis only --
BUILD-TIME, never touches the live node or strategy (D7: "Evaluation via the
v3 backtest subclass / paper replay under TestClock, no look-ahead; plus a
hypothetical-hold corpus over the archived tape" -- this module is that
second leg).

WHAT THIS IS
------------
For every (station, climate_day) in a requested window, this module replays
the ARCHIVED Depth10 + NWS-observation tape in ``ts_init`` order and asks two
questions:

1. Would the live strategy's OWN entry rule (``evaluate_decision``,
   unmodified, imported -- never re-derived) have taken a position that day,
   and at what snapshot? (:func:`select_hypothetical_holds`, reusing the
   study's own "first executable snapshot is the trial" selection rule --
   ``mb_current_rung_edge_study.first_executable_trial`` -- L-34: the
   trigger selects the estimand, so this is the SAME first-snapshot rule the
   live strategy is pinned to, never a re-look.)
2. From that instant forward, what would the SHADOW MONITOR
   (``monitor_evidence.build_monitor_evidence`` +
   ``monitor_decision.evaluate_monitor``, both imported unmodified) have
   said, evaluated against every LATER observation and Depth10 frame with
   ``ts_init > take.ts_ns`` only -- never a look-ahead peek?
   (:func:`replay_monitor`.)

Every take is joined against NWS CLI FINAL settlement truth
(``settlement_truth_dataset.bucket_facts``/``settles_yes`` -- PRELIMINARY
records are never used, matching the live scorer) to produce
``settled_pnl``/``settled_held``, and the whole corpus is written in the
SAME ``PositionMonitorSummary`` schema as the live monitor
(``monitor_store.write_monitor_summaries``) with ``entry_context=
"hypothetical"`` and ``trial_id`` prefixed ``hypo:`` -- so INC-6's nightly
report can join this corpus exactly the way it joins the live one, and can
never confuse a hypothetical row for a real trial (the prefix is a second,
independent barrier alongside ``entry_context``).

L-1 (native vs authored): this module is a pure GAP-FILLER glue layer. Every
piece of real machinery it needs already exists and is imported unmodified:
``evaluate_decision``/``DecisionInputs`` (the live entry rule),
``RunningExtremeAccumulator`` (the live running-max accumulator),
``build_monitor_evidence``/``evaluate_monitor`` (the shadow monitor, built by
a concurrent agent for this same plan), ``bucket_facts``/``settles_yes`` (the
settlement predicate), ``discover_station_days``/``instrument_ids_for``/
``parse_ladder`` (the study's own station-day/ladder discovery), and
``iem_asos_rows_to_station_observations`` (the archive observation parser).
Nothing here reimplements any of those; this module's only original content
is the REPLAY LOOP that drives them together and the descriptive
``CorpusReport`` aggregation.

Streaming and memory (plan CLI note): the CLI processes ONE station-day at a
time, mirroring ``mb_current_rung_edge_study.py``'s per-day loop -- an ASOS
archive fetch is cached once per STATION (a single multi-year text blob) and
sliced per day before feeding a station-day's own, freshly-constructed
``RunningExtremeAccumulator`` (the accumulator resets its held rows on every
climate-day change, so it is NOT reusable bulk-loaded across days -- see
``RunningExtremeAccumulator.push``'s day-boundary reset). Depth10 frames are
read per station-day via ``ParquetDataCatalog.query(OrderBookDepth10,
identifiers=...)``, never the whole catalog at once.
"""

from __future__ import annotations

import argparse
import datetime as dt
import inspect
import json
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Final, Literal

sys.path.insert(0, str(Path(__file__).resolve().parent))

from h4_preliminary_economic_read import Rung, parse_ladder
from ma_prelock_winner_ask_study import (
    DEFAULT_QUOTE_TAPE_CATALOG,
    DEFAULT_SETTLEMENT_CATALOG,
    discover_station_days,
    instrument_ids_for,
    load_settled_tmax_for_day,
)
from nautilus_trader.model.data import BookOrder, OrderBookDepth10
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from settlement_alignment_cache import DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR
from settlement_alignment_study import (
    SiteSpec,
    asos_url,
    cache_path_for_url,
    load_sites,
    parse_asos_rows,
)
from settlement_truth_dataset import bucket_facts, settles_yes

from breezy.domain.climate_day import climate_day_for_instant
from breezy.domain.season import season_for
from breezy.ingest.iem_observations import iem_asos_rows_to_station_observations
from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
from breezy.strategy.current_rung_hold.decision import (
    DecisionInputs,
    RungBounds,
    Take,
    evaluate_decision,
)
from breezy.strategy.current_rung_hold.decision import (
    _fee as _entry_fee,
)
from breezy.strategy.current_rung_hold.monitor_decision import (
    MonitorHistory,
    ThesisState,
    Verdict,
    evaluate_monitor,
)
from breezy.strategy.current_rung_hold.monitor_evidence import (
    Leg,
    build_monitor_evidence,
)
from breezy.strategy.current_rung_hold.monitor_records import PositionMonitorSummary
from breezy.strategy.current_rung_hold.monitor_store import write_monitor_summaries
from breezy.strategy.current_rung_hold.strategy import _local_hour
from breezy.strategy.current_rung_hold.tick_eval import (
    instrument_rung_is_current,
    width_and_m,
)
from breezy.strategy.weather_common.running_extreme import RunningExtremeAccumulator

__all__ = [
    "ARCHIVE_HOURS",
    "CALIBRATION_FLOOR_STATION_DAYS",
    "TRIAL_ID_PREFIX",
    "WINDOW_END_HOUR_LST",
    "WINDOW_START_HOUR_LST",
    "CorpusReport",
    "HypotheticalTake",
    "InstrumentTape",
    "LookAheadError",
    "ObservationRow",
    "ReplayDiagnostics",
    "SkippedStationDay",
    "build_corpus_report",
    "replay_monitor",
    "select_hypothetical_holds",
]

#: Same set the live strategy and every archive study condition on
#: (``mb_current_rung_edge_study.ARCHIVE_HOURS``, ``config.py``'s window).
ARCHIVE_HOURS: Final[tuple[int, ...]] = (12, 13, 14, 15, 16)
WINDOW_START_HOUR_LST: Final[int] = 12
WINDOW_END_HOUR_LST: Final[int] = 17  # exclusive

#: A4: below this many usable station-days, firing rates are UNCALIBRATED.
#: Mirrors the kill-sentence floor (``mb_current_rung_edge_study.py``'s
#: docstring: ">= 15 afternoon-covered station-days").
CALIBRATION_FLOOR_STATION_DAYS: Final[int] = 15

#: Never a real live trial id: an independent barrier from ``entry_context``.
TRIAL_ID_PREFIX: Final[str] = "hypo:"

_ONE: Final[Decimal] = Decimal(1)
_ZERO: Final[Decimal] = Decimal(0)

#: 2026-09-15 correction landed by a concurrent agent on this same plan:
#: `MonitorEvidence`/`build_monitor_evidence` gained an optional
#: `observed_at_ns` param (the accumulator's last-observation instant, NOT
#: the evaluation's own `ts_ns`) so `monitor_decision._dead_confirm_key` can
#: tell a genuinely NEW confirming observation apart from a depth-only tick
#: re-evaluating the SAME unchanged observation. This module's replay loop
#: evaluates on BOTH triggers (M1 dual triggers), so it must thread this
#: through -- checked once, at import, so a future signature (with or
#: without the param) is never a hard `TypeError` here.
_SUPPORTS_OBSERVED_AT_NS: Final[bool] = (
    "observed_at_ns" in inspect.signature(build_monitor_evidence).parameters
)


class LookAheadError(ValueError):
    """A caller handed :func:`replay_monitor` an event at or before the take.

    The no-look-ahead pin (module docstring, plan D3/L-34): every event fed
    to a replay must carry ``ts_ns`` strictly after the take it replays --
    enforced here, not merely documented, so a caller cannot silently leak a
    future-stamped record into a "past" evaluation.
    """


# ---------------------------------------------------------------------------
# Pure data shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class ObservationRow:
    """One parsed archive observation, already at ``RunningExtremeAccumulator
    .push``'s parameter shape. ``received_at_ns`` is always ``observed_at_ns``
    here (module docstring: "reproduce the archive, which has no separate
    receipt instant" -- ``running_extreme.py``'s own guidance for this exact
    use case).
    """

    observed_at_ns: int
    temp_c_tenths: int
    precision_c_tenths: int
    is_metar: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class InstrumentTape:
    """One rung's already-loaded, ``ts_init``-ascending Depth10 frames."""

    instrument_id: str
    rung: RungBounds
    depth_frames: tuple[OrderBookDepth10, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class HypotheticalTake:
    """The FIRST executable snapshot a station-day's ladder produced --
    the same estimand-selecting event the live strategy's trial-day latch
    would have consumed (L-34)."""

    station: str
    climate_day: dt.date
    season: str
    instrument_id: str
    leg: Leg
    ts_ns: int
    hour_lst: int
    rung: RungBounds
    ask: Decimal
    size: int
    p_hold_at_entry: Decimal
    held_qty: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplayDiagnostics:
    """Extra per-trial facts :func:`build_corpus_report` aggregates --
    everything ``PositionMonitorSummary`` has no column for."""

    archive_covered_evaluations: int
    threatened_evaluations: int
    dead_evaluations: int
    missing_stop_evaluations: int
    reason_code_counts: Mapping[str, int]
    dead_confirmation_spans_ns: tuple[int, ...]
    threatened_confirmation_spans_ns: tuple[int, ...]
    exit_recommended_recoverable_values: tuple[Decimal, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class SkippedStationDay:
    """One station-day this corpus could not use, and why (tape-coverage
    caveat, plan completion criterion)."""

    station: str
    climate_day: dt.date
    reason: str


@dataclass(frozen=True, slots=True, kw_only=True)
class CorpusReport:
    """The INC-8 headline artefact (plan completion criterion, A4/P5/P6)."""

    generated_at_ns: int
    window_start: str
    window_end: str
    stations: tuple[str, ...]
    usable_station_days: int
    calibration_status: Literal["CALIBRATED", "UNCALIBRATED"]
    n_trials: int
    dead_precision: Decimal | None
    dead_precision_numerator: int
    dead_precision_denominator: int
    threatened_base_rate: Decimal | None
    threatened_evaluations: int
    archive_covered_evaluations: int
    missing_stop_rate: Decimal | None
    missing_stop_numerator: int
    missing_stop_denominator: int
    recoverable_value_p10: Decimal | None
    recoverable_value_p50: Decimal | None
    recoverable_value_p90: Decimal | None
    recoverable_value_n: int
    provisional_constant_firing_rates: Mapping[str, Decimal]
    inter_confirmation_span_ns_p10: int | None
    inter_confirmation_span_ns_p50: int | None
    inter_confirmation_span_ns_p90: int | None
    inter_confirmation_span_n: int
    per_station_trial_counts: Mapping[str, int]
    per_leg_trial_counts: Mapping[str, int]
    skipped_station_days: tuple[SkippedStationDay, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "generated_at_ns": self.generated_at_ns,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "stations": list(self.stations),
            "usable_station_days": self.usable_station_days,
            "calibration_status": self.calibration_status,
            "n_trials": self.n_trials,
            "dead_precision": _decimal_or_none(self.dead_precision),
            "dead_precision_numerator": self.dead_precision_numerator,
            "dead_precision_denominator": self.dead_precision_denominator,
            "threatened_base_rate": _decimal_or_none(self.threatened_base_rate),
            "threatened_evaluations": self.threatened_evaluations,
            "archive_covered_evaluations": self.archive_covered_evaluations,
            "missing_stop_rate": _decimal_or_none(self.missing_stop_rate),
            "missing_stop_numerator": self.missing_stop_numerator,
            "missing_stop_denominator": self.missing_stop_denominator,
            "recoverable_value_p10": _decimal_or_none(self.recoverable_value_p10),
            "recoverable_value_p50": _decimal_or_none(self.recoverable_value_p50),
            "recoverable_value_p90": _decimal_or_none(self.recoverable_value_p90),
            "recoverable_value_n": self.recoverable_value_n,
            "provisional_constant_firing_rates": {
                key: str(value) for key, value in self.provisional_constant_firing_rates.items()
            },
            "inter_confirmation_span_ns_p10": self.inter_confirmation_span_ns_p10,
            "inter_confirmation_span_ns_p50": self.inter_confirmation_span_ns_p50,
            "inter_confirmation_span_ns_p90": self.inter_confirmation_span_ns_p90,
            "inter_confirmation_span_n": self.inter_confirmation_span_n,
            "per_station_trial_counts": dict(self.per_station_trial_counts),
            "per_leg_trial_counts": dict(self.per_leg_trial_counts),
            "skipped_station_days": [
                {
                    "station": row.station,
                    "climate_day": row.climate_day.isoformat(),
                    "reason": row.reason,
                }
                for row in self.skipped_station_days
            ],
        }


def _decimal_or_none(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


# ---------------------------------------------------------------------------
# Selection: the first executable snapshot (L-34 -- the trigger IS the estimand)
# ---------------------------------------------------------------------------


def select_hypothetical_holds(
    *,
    station: str,
    climate_day: dt.date,
    std_utc_offset_hours: float,
    config: CurrentRungHoldConfig,
    fee_coefficient: Decimal,
    ladder: Sequence[RungBounds],
    instruments: Sequence[InstrumentTape],
    accumulator: RunningExtremeAccumulator,
) -> HypotheticalTake | None:
    """The FIRST executable Depth10 snapshot across the WHOLE ladder,
    time-ascending -- one trial per station-day (mirrors
    ``mb_current_rung_edge_study.first_executable_trial``: never the
    afternoon's cheapest ask, never a re-look after the first hit).

    ``accumulator`` must already hold every observation for this
    ``climate_day`` (pushed by the caller) -- :meth:`RunningExtremeAccumulator
    .value_at` itself gates on ``observed_at_ns <= now_ns``, so bulk-loading
    the day's rows up front is provably no-look-ahead; only ``now_ns`` at
    each evaluated frame ever controls what is visible.
    """
    season = season_for(climate_day)
    frames: list[tuple[int, InstrumentTape, OrderBookDepth10]] = [
        (frame.ts_init, tape, frame)
        for tape in instruments
        for frame in tape.depth_frames
    ]
    frames.sort(key=lambda item: item[0])

    for ts_ns, tape, frame in frames:
        hour_lst = _local_hour(ts_ns, std_utc_offset_hours)
        if not (WINDOW_START_HOUR_LST <= hour_lst < WINDOW_END_HOUR_LST):
            continue
        running_max = accumulator.value_at(ts_ns)
        if running_max is None:
            continue
        facts = bucket_facts(
            lower_f=tape.rung[0], upper_f=tape.rung[1], station=station, climate_day=climate_day,
        )
        if not instrument_rung_is_current(facts, running_max):
            continue
        ask, size = _top_of_book(frame.asks)
        if ask is None or size is None:
            continue
        width_code, m_code = width_and_m(facts, running_max)
        staleness_ns = accumulator.staleness_ns(ts_ns)
        inputs = DecisionInputs(
            station=station,
            climate_day=climate_day,
            now_ns=ts_ns,
            ladder=ladder,
            fee_coefficient=fee_coefficient,
            ask=ask,
            size=size,
            running_max=running_max,
            staleness_ns=staleness_ns,
            config=config,
            season=season,
            hour_lst=hour_lst,
            width_code=width_code,
            m_code=m_code,
            latch_consumed=False,
        )
        decision = evaluate_decision(inputs)
        if isinstance(decision, Take):
            return HypotheticalTake(
                station=station,
                climate_day=climate_day,
                season=season,
                instrument_id=tape.instrument_id,
                leg="YES",
                ts_ns=ts_ns,
                hour_lst=hour_lst,
                rung=tape.rung,
                ask=decision.limit_price,
                size=size,
                p_hold_at_entry=decision.p_hold_lower,
                held_qty=decision.quantity,
            )
    return None


def _top_of_book(levels: Sequence[BookOrder]) -> tuple[Decimal | None, int | None]:
    """First non-zero-size level's ``(price, size)``, or ``(None, None)``.

    Mirrors ``monitor_evidence.walk_exit_vwap``'s own zero-size skip, but
    reads only the TOP level (the executable-ask gate is a top-of-book
    check, never a walked VWAP -- ``decision.py``'s ``_finalize_take``).
    """
    for level in levels:
        size = level.size.as_decimal()
        if size > _ZERO:
            return level.price.as_decimal(), int(size)
    return None, None


# ---------------------------------------------------------------------------
# Replay: the shadow monitor over every LATER event, no look-ahead
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class _ObservationEvent:
    ts_ns: int


@dataclass(frozen=True, slots=True, kw_only=True)
class _DepthEvent:
    depth: OrderBookDepth10


def replay_monitor(
    *,
    take: HypotheticalTake,
    accumulator: RunningExtremeAccumulator,
    std_utc_offset_hours: float,
    fee_coefficient: Decimal,
    stale_observation_bound_ns: int,
    subsequent_depth_frames: Sequence[OrderBookDepth10],
    subsequent_observation_ts_ns: Sequence[int],
    tmax_f: int | None,
) -> tuple[PositionMonitorSummary, ReplayDiagnostics]:
    """Replay the shadow monitor from ``take`` forward.

    ``subsequent_depth_frames``/``subsequent_observation_ts_ns`` must each
    carry ``ts`` strictly after ``take.ts_ns`` (:class:`LookAheadError`
    otherwise) -- the no-look-ahead pin. ``accumulator`` must already hold
    every observation for the day (see :func:`select_hypothetical_holds`);
    this function only ever queries it at each event's own ``ts_ns``.
    """
    for frame in subsequent_depth_frames:
        if frame.ts_init <= take.ts_ns:
            raise LookAheadError(
                f"depth frame ts_init={frame.ts_init} is not strictly after "
                f"take.ts_ns={take.ts_ns}",
            )
    for ts_ns in subsequent_observation_ts_ns:
        if ts_ns <= take.ts_ns:
            raise LookAheadError(
                f"observation ts_ns={ts_ns} is not strictly after take.ts_ns={take.ts_ns}",
            )

    facts = bucket_facts(
        lower_f=take.rung[0], upper_f=take.rung[1], station=take.station,
        climate_day=take.climate_day,
    )
    events: list[tuple[int, int, object]] = [
        (frame.ts_init, 1, _DepthEvent(depth=frame)) for frame in subsequent_depth_frames
    ]
    events.extend(
        (ts_ns, 0, _ObservationEvent(ts_ns=ts_ns)) for ts_ns in subsequent_observation_ts_ns
    )
    events.sort(key=lambda item: (item[0], item[1]))

    history = MonitorHistory.EMPTY
    last_depth: OrderBookDepth10 | None = None
    last_depth_ts_ns: int | None = None

    total_frames = 0
    mark_missing_frames = 0
    archive_covered_evaluations = 0
    threatened_evaluations = 0
    dead_evaluations = 0
    missing_stop_evaluations = 0
    reason_code_counts: Counter[str] = Counter()
    dead_confirmation_spans_ns: list[int] = []
    threatened_confirmation_spans_ns: list[int] = []
    exit_recommended_recoverable_values: list[Decimal] = []
    mae = _ZERO
    mfe = _ZERO
    first_signal_ts_ns: int | None = None
    first_signal_hour_lst: int | None = None
    first_signal_state: str | None = None
    verdict_at_signal: str | None = None
    recoverable_value_at_signal: Decimal | None = None
    last_ts_ns = take.ts_ns

    for ts_ns, _tiebreak, event in events:
        book_staleness_ns: int | None
        if isinstance(event, _DepthEvent):
            last_depth = event.depth
            last_depth_ts_ns = ts_ns
            depth = event.depth
            book_staleness_ns = 0
        else:
            depth = last_depth
            book_staleness_ns = (
                None if last_depth_ts_ns is None else ts_ns - last_depth_ts_ns
            )

        running_max = accumulator.value_at(ts_ns)
        if running_max is None:
            continue
        staleness_ns = accumulator.staleness_ns(ts_ns)
        hour_lst = _local_hour(ts_ns, std_utc_offset_hours)
        width_code, m_code = width_and_m(facts, running_max)

        # The accumulator's OWN last-observation instant, never this
        # evaluation's `ts_ns` -- two depth-only ticks between the same pair
        # of observations must key on the SAME observed instant, or
        # `_dead_confirm_key` would double-count one observation as two
        # independent confirmations. Threaded through only when the
        # (concurrently-landed) parameter exists -- see
        # `_SUPPORTS_OBSERVED_AT_NS`.
        if _SUPPORTS_OBSERVED_AT_NS:
            evidence = build_monitor_evidence(
                ts_ns=ts_ns,
                instrument_id=take.instrument_id,
                station=take.station,
                climate_day=take.climate_day.isoformat(),
                season=take.season,
                hour_lst=hour_lst,
                width_code=width_code,
                m_code=m_code,
                leg=take.leg,
                entry_context="hypothetical",
                fill_px=take.ask,
                held_qty=take.held_qty,
                running_max_lower=running_max.lower_f,
                running_max_upper=running_max.upper_f,
                staleness_ns=staleness_ns,
                book_staleness_ns=book_staleness_ns,
                rung_low=take.rung[0],
                rung_high=take.rung[1],
                depth=depth,
                fee_coefficient=fee_coefficient,
                p_hold_at_entry=take.p_hold_at_entry,
                observed_at_ns=running_max.source_observed_at_ns,
            )
        else:
            evidence = build_monitor_evidence(
                ts_ns=ts_ns,
                instrument_id=take.instrument_id,
                station=take.station,
                climate_day=take.climate_day.isoformat(),
                season=take.season,
                hour_lst=hour_lst,
                width_code=width_code,
                m_code=m_code,
                leg=take.leg,
                entry_context="hypothetical",
                fill_px=take.ask,
                held_qty=take.held_qty,
                running_max_lower=running_max.lower_f,
                running_max_upper=running_max.upper_f,
                staleness_ns=staleness_ns,
                book_staleness_ns=book_staleness_ns,
                rung_low=take.rung[0],
                rung_high=take.rung[1],
                depth=depth,
                fee_coefficient=fee_coefficient,
                p_hold_at_entry=take.p_hold_at_entry,
            )
        decision, new_history = evaluate_monitor(
            evidence, history, stale_observation_bound_ns=stale_observation_bound_ns,
        )

        total_frames += 1
        last_ts_ns = ts_ns
        if evidence.mark_source == "missing":
            mark_missing_frames += 1
        if hour_lst in ARCHIVE_HOURS:
            archive_covered_evaluations += 1
        reason_code_counts.update(decision.reason_codes)
        if evidence.unrealized_pnl is not None:
            mae = min(mae, evidence.unrealized_pnl)
            mfe = max(mfe, evidence.unrealized_pnl)

        if decision.state is ThesisState.THREATENED:
            threatened_evaluations += 1
        if decision.state is ThesisState.DEAD_BY_OBSERVATION:
            dead_evaluations += 1
            if (
                history.last_state is not ThesisState.DEAD_BY_OBSERVATION
                and len(new_history.dead_confirm_observed_ns) >= 2
            ):
                span = max(new_history.dead_confirm_observed_ns) - min(
                    new_history.dead_confirm_observed_ns,
                )
                dead_confirmation_spans_ns.append(span)
            if decision.verdict is Verdict.MISSING_STOP:
                missing_stop_evaluations += 1
        if decision.verdict is Verdict.EXIT_RECOMMENDED and evidence.recoverable_value is not None:
            exit_recommended_recoverable_values.append(evidence.recoverable_value)

        if (
            decision.state != history.last_state
            and decision.state in (ThesisState.ALIVE, ThesisState.THREATENED)
            and history.candidate_first_ts_ns is not None
        ):
            threatened_confirmation_spans_ns.append(ts_ns - history.candidate_first_ts_ns)

        if first_signal_ts_ns is None and decision.state is not ThesisState.ALIVE:
            first_signal_ts_ns = ts_ns
            first_signal_hour_lst = hour_lst
            first_signal_state = decision.state.value
            verdict_at_signal = decision.verdict.value
            recoverable_value_at_signal = evidence.recoverable_value

        history = new_history

    settled_held = None if tmax_f is None else settles_yes(
        tmax_f, lower_f=facts.lower_f, upper_f=facts.upper_f,
    )
    settled_pnl = (
        None
        if settled_held is None
        else (_ONE if settled_held else _ZERO) - take.ask - _entry_fee(take.ask, fee_coefficient)
    )

    trial_id = (
        f"{TRIAL_ID_PREFIX}{take.station}:{take.climate_day.isoformat()}:{take.instrument_id}"
    )
    summary = PositionMonitorSummary(
        trial_id=trial_id,
        instrument_id=take.instrument_id,
        station=take.station,
        climate_day=take.climate_day.isoformat(),
        leg=take.leg,
        entry_context="hypothetical",
        monitor_seq=1,
        fill_px=take.ask,
        held_qty=Decimal(take.held_qty),
        mae=mae,
        mfe=mfe,
        first_signal_ts_ns=first_signal_ts_ns,
        first_signal_hour_lst=first_signal_hour_lst,
        first_signal_state=first_signal_state,
        verdict_at_signal=verdict_at_signal,
        recoverable_value_at_signal=recoverable_value_at_signal,
        held_duration_ns=last_ts_ns - take.ts_ns,
        total_frames=total_frames,
        mark_missing_frames=mark_missing_frames,
        settled_pnl=settled_pnl,
        settled_held=settled_held,
    )
    diagnostics = ReplayDiagnostics(
        archive_covered_evaluations=archive_covered_evaluations,
        threatened_evaluations=threatened_evaluations,
        dead_evaluations=dead_evaluations,
        missing_stop_evaluations=missing_stop_evaluations,
        reason_code_counts=dict(reason_code_counts),
        dead_confirmation_spans_ns=tuple(dead_confirmation_spans_ns),
        threatened_confirmation_spans_ns=tuple(threatened_confirmation_spans_ns),
        exit_recommended_recoverable_values=tuple(exit_recommended_recoverable_values),
    )
    return summary, diagnostics


# ---------------------------------------------------------------------------
# Report aggregation
# ---------------------------------------------------------------------------


def _percentile(sorted_values: Sequence[Decimal], q: Decimal) -> Decimal:
    if not sorted_values:
        raise ValueError("cannot take a percentile of an empty sequence")
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = q * (len(sorted_values) - 1)
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(sorted_values) - 1)
    fraction = position - lower_index
    return sorted_values[lower_index] + (
        sorted_values[upper_index] - sorted_values[lower_index]
    ) * fraction


_P10: Final[Decimal] = Decimal("0.10")
_P50: Final[Decimal] = Decimal("0.50")
_P90: Final[Decimal] = Decimal("0.90")


def build_corpus_report(
    *,
    results: Sequence[tuple[HypotheticalTake, PositionMonitorSummary, ReplayDiagnostics]],
    skipped_station_days: Sequence[SkippedStationDay],
    window_start: dt.date,
    window_end: dt.date,
    stations: Sequence[str],
    generated_at_ns: int,
) -> CorpusReport:
    """Aggregate every trial's replay into the headline descriptive report
    (A4/P5/P6). Below :data:`CALIBRATION_FLOOR_STATION_DAYS` usable
    station-days, the rate fields are reported ``None`` (UNCALIBRATED) even
    though the raw numerator/denominator counts are always populated.
    """
    usable_station_days = len({(take.station, take.climate_day) for take, _, _ in results})
    calibrated = usable_station_days >= CALIBRATION_FLOOR_STATION_DAYS

    dead_denominator = sum(1 for _, _, diag in results if diag.dead_evaluations > 0)
    dead_numerator = sum(
        1
        for _, summary, diag in results
        if diag.dead_evaluations > 0
        and summary.settled_pnl is not None
        and summary.settled_pnl < _ZERO
    )
    threatened_evaluations = sum(diag.threatened_evaluations for _, _, diag in results)
    archive_covered_evaluations = sum(
        diag.archive_covered_evaluations for _, _, diag in results
    )
    missing_stop_numerator = sum(diag.missing_stop_evaluations for _, _, diag in results)
    missing_stop_denominator = sum(diag.dead_evaluations for _, _, diag in results)

    recoverable_values = sorted(
        value
        for _, _, diag in results
        for value in diag.exit_recommended_recoverable_values
    )
    spans = sorted(
        span
        for _, _, diag in results
        for span in (*diag.dead_confirmation_spans_ns, *diag.threatened_confirmation_spans_ns)
    )

    reason_totals: Counter[str] = Counter()
    total_evaluations = 0
    for _, summary, diag in results:
        reason_totals.update(diag.reason_code_counts)
        total_evaluations += summary.total_frames
    firing_rates = (
        {
            reason: Decimal(count) / Decimal(total_evaluations)
            for reason, count in sorted(reason_totals.items())
        }
        if total_evaluations > 0
        else {}
    )

    per_station: Counter[str] = Counter(take.station for take, _, _ in results)
    per_leg: Counter[str] = Counter(take.leg for take, _, _ in results)

    span_decimals = [Decimal(span) for span in spans]

    return CorpusReport(
        generated_at_ns=generated_at_ns,
        window_start=window_start.isoformat(),
        window_end=window_end.isoformat(),
        stations=tuple(stations),
        usable_station_days=usable_station_days,
        calibration_status="CALIBRATED" if calibrated else "UNCALIBRATED",
        n_trials=len(results),
        dead_precision=(
            Decimal(dead_numerator) / Decimal(dead_denominator)
            if calibrated and dead_denominator > 0
            else None
        ),
        dead_precision_numerator=dead_numerator,
        dead_precision_denominator=dead_denominator,
        threatened_base_rate=(
            Decimal(threatened_evaluations) / Decimal(archive_covered_evaluations)
            if calibrated and archive_covered_evaluations > 0
            else None
        ),
        threatened_evaluations=threatened_evaluations,
        archive_covered_evaluations=archive_covered_evaluations,
        missing_stop_rate=(
            Decimal(missing_stop_numerator) / Decimal(missing_stop_denominator)
            if calibrated and missing_stop_denominator > 0
            else None
        ),
        missing_stop_numerator=missing_stop_numerator,
        missing_stop_denominator=missing_stop_denominator,
        recoverable_value_p10=(
            _percentile(recoverable_values, _P10) if calibrated and recoverable_values else None
        ),
        recoverable_value_p50=(
            _percentile(recoverable_values, _P50) if calibrated and recoverable_values else None
        ),
        recoverable_value_p90=(
            _percentile(recoverable_values, _P90) if calibrated and recoverable_values else None
        ),
        recoverable_value_n=len(recoverable_values),
        provisional_constant_firing_rates=firing_rates if calibrated else {},
        inter_confirmation_span_ns_p10=(
            int(_percentile(span_decimals, _P10)) if calibrated and span_decimals else None
        ),
        inter_confirmation_span_ns_p50=(
            int(_percentile(span_decimals, _P50)) if calibrated and span_decimals else None
        ),
        inter_confirmation_span_ns_p90=(
            int(_percentile(span_decimals, _P90)) if calibrated and span_decimals else None
        ),
        inter_confirmation_span_n=len(spans),
        per_station_trial_counts=dict(sorted(per_station.items())),
        per_leg_trial_counts=dict(sorted(per_leg.items())),
        skipped_station_days=tuple(skipped_station_days),
    )


# ---------------------------------------------------------------------------
# I/O -- real catalog and archive reads (never exercised by the unit tests)
# ---------------------------------------------------------------------------


def _load_observations_for_station(
    *, cache_dir: Path, spec: SiteSpec, start: dt.date, end: dt.date,
) -> tuple[ObservationRow, ...]:
    """Every archive observation for one station across ``[start, end]``,
    parsed ONCE per station (never per day) -- the CLI slices this per
    climate day before pushing into a fresh accumulator (module docstring).
    """
    raw_path = cache_path_for_url(cache_dir, asos_url(spec.iem_asos_id, start, end), ".txt")
    if not raw_path.exists():
        raise SystemExit(f"ASOS cache miss for {spec.city}; expected: {raw_path}")
    rows = parse_asos_rows(raw_path.read_text(encoding="utf-8", errors="replace"))
    _placeholder_received_at_ns: Final[int] = 2**62
    parsed, _drops = iem_asos_rows_to_station_observations(
        station=spec.iem_asos_id,
        rows=rows,
        source_channel="iem_asos_metar_hypothetical_hold",
        assumed_publication_lag_ns=1,
        received_at_ns=_placeholder_received_at_ns,
    )
    return tuple(
        ObservationRow(
            observed_at_ns=record.observed_at_ns,
            temp_c_tenths=record.temp_c_tenths,
            precision_c_tenths=record.precision_c_tenths,
            is_metar=record.is_metar,
        )
        for record in parsed
    )


def _accumulator_for_day(
    *,
    observations: Sequence[ObservationRow],
    climate_day: dt.date,
    std_utc_offset_hours: float,
) -> RunningExtremeAccumulator:
    accumulator = RunningExtremeAccumulator(std_utc_offset_hours=std_utc_offset_hours)
    for row in observations:
        day = climate_day_for_instant(
            dt.datetime.fromtimestamp(row.observed_at_ns / 1_000_000_000, tz=dt.UTC),
            std_utc_offset_hours,
        )
        if day != climate_day:
            continue
        accumulator.push(
            row.observed_at_ns,
            row.temp_c_tenths,
            row.precision_c_tenths,
            row.is_metar,
            row.observed_at_ns,
        )
    return accumulator


def _load_depth_frames(
    *, catalog_root: Path, instrument_ids: Sequence[str],
) -> dict[str, tuple[OrderBookDepth10, ...]]:
    catalog = ParquetDataCatalog(str(catalog_root))
    rows = catalog.query(OrderBookDepth10, identifiers=list(instrument_ids))
    grouped: dict[str, list[OrderBookDepth10]] = {}
    for row in rows:
        grouped.setdefault(str(row.instrument_id), []).append(row)
    return {
        instrument_id: tuple(sorted(frames, key=lambda frame: frame.ts_init))
        for instrument_id, frames in grouped.items()
    }


def _ladder_for(instrument_ids: Sequence[str]) -> tuple[Rung, ...]:
    return parse_ladder(instrument_ids)


def run_hypothetical_hold_corpus(
    *,
    catalog_root: Path,
    nws_root: Path,
    settlement_catalog: Path,
    start: dt.date,
    end: dt.date,
    stations: Sequence[str],
) -> tuple[
    tuple[tuple[HypotheticalTake, PositionMonitorSummary, ReplayDiagnostics], ...],
    tuple[SkippedStationDay, ...],
]:
    """The real, streaming, per-station-day I/O driver (never called by the
    unit tests -- see the module docstring's memory note).
    """
    config = CurrentRungHoldConfig(stations=tuple(stations))
    fee_coefficient = config.required_fee_coefficient
    stale_observation_bound_ns = config.stale_observation_minutes * 60_000_000_000

    specs_by_city = {spec.city: spec for spec in load_sites() if spec.city in stations}
    depth_root = catalog_root / "data" / "order_book_depths"
    if not depth_root.is_dir():
        raise SystemExit(f"no depth catalog at {depth_root}")

    station_days = discover_station_days(
        depth_root=depth_root, cities=stations, fetch_start=start, fetch_end=end,
    )

    observations_by_station: dict[str, tuple[ObservationRow, ...]] = {}
    results: list[tuple[HypotheticalTake, PositionMonitorSummary, ReplayDiagnostics]] = []
    skipped: list[SkippedStationDay] = []

    for city, climate_day in station_days:
        spec = specs_by_city[city]
        if city not in observations_by_station:
            observations_by_station[city] = _load_observations_for_station(
                cache_dir=nws_root, spec=spec, start=start, end=end,
            )
        accumulator = _accumulator_for_day(
            observations=observations_by_station[city],
            climate_day=climate_day,
            std_utc_offset_hours=spec.std_utc_offset_hours,
        )

        instrument_ids = instrument_ids_for(
            depth_root=depth_root, city=city, climate_day=climate_day,
        )
        if not instrument_ids:
            skipped.append(
                SkippedStationDay(station=city, climate_day=climate_day, reason="no_depth10"),
            )
            continue
        ladder_rungs = _ladder_for(instrument_ids)
        ladder_bounds: tuple[RungBounds, ...] = tuple(
            (rung.lower_f, rung.upper_f) for rung in ladder_rungs
        )
        depth_by_id = _load_depth_frames(catalog_root=catalog_root, instrument_ids=instrument_ids)
        instruments = tuple(
            InstrumentTape(
                instrument_id=rung.instrument_id,
                rung=(rung.lower_f, rung.upper_f),
                depth_frames=depth_by_id.get(rung.instrument_id, ()),
            )
            for rung in ladder_rungs
        )
        if not any(tape.depth_frames for tape in instruments):
            skipped.append(
                SkippedStationDay(station=city, climate_day=climate_day, reason="no_depth10"),
            )
            continue

        take = select_hypothetical_holds(
            station=city,
            climate_day=climate_day,
            std_utc_offset_hours=spec.std_utc_offset_hours,
            config=config,
            fee_coefficient=fee_coefficient,
            ladder=ladder_bounds,
            instruments=instruments,
            accumulator=accumulator,
        )
        if take is None:
            skipped.append(
                SkippedStationDay(
                    station=city, climate_day=climate_day, reason="no_executable_snapshot",
                ),
            )
            continue

        tmax_f, _count, _provenance = load_settled_tmax_for_day(
            catalog_base=settlement_catalog, city=city, climate_day=climate_day,
        )
        if tmax_f is None:
            skipped.append(
                SkippedStationDay(
                    station=city, climate_day=climate_day, reason="no_settlement_truth",
                ),
            )
            continue

        taken_tape = next(tape for tape in instruments if tape.instrument_id == take.instrument_id)
        subsequent_depth = tuple(
            frame for frame in taken_tape.depth_frames if frame.ts_init > take.ts_ns
        )
        subsequent_observation_ts_ns = tuple(
            sorted(
                {
                    row.observed_at_ns
                    for row in observations_by_station[city]
                    if row.observed_at_ns > take.ts_ns
                    and climate_day_for_instant(
                        dt.datetime.fromtimestamp(row.observed_at_ns / 1_000_000_000, tz=dt.UTC),
                        spec.std_utc_offset_hours,
                    )
                    == climate_day
                },
            )
        )
        summary, diagnostics = replay_monitor(
            take=take,
            accumulator=accumulator,
            std_utc_offset_hours=spec.std_utc_offset_hours,
            fee_coefficient=fee_coefficient,
            stale_observation_bound_ns=stale_observation_bound_ns,
            subsequent_depth_frames=subsequent_depth,
            subsequent_observation_ts_ns=subsequent_observation_ts_ns,
            tmax_f=tmax_f,
        )
        results.append((take, summary, diagnostics))

    return tuple(results), tuple(skipped)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog-root", type=Path, default=DEFAULT_QUOTE_TAPE_CATALOG)
    parser.add_argument("--nws-root", type=Path, default=DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR)
    parser.add_argument("--settlement-catalog", type=Path, default=DEFAULT_SETTLEMENT_CATALOG)
    parser.add_argument("--start", required=True, type=str)
    parser.add_argument("--end", required=True, type=str)
    parser.add_argument(
        "--stations", nargs="+", default=list(CurrentRungHoldConfig().stations),
    )
    parser.add_argument("--out-dir", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    start = dt.date.fromisoformat(args.start)
    end = dt.date.fromisoformat(args.end)
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    results, skipped = run_hypothetical_hold_corpus(
        catalog_root=args.catalog_root,
        nws_root=args.nws_root,
        settlement_catalog=args.settlement_catalog,
        start=start,
        end=end,
        stations=tuple(args.stations),
    )
    now_ns = int(dt.datetime.now(tz=dt.UTC).timestamp() * 1_000_000_000)
    if results:
        write_monitor_summaries(out_dir, [summary for _, summary, _ in results], now_ns=now_ns)
    report = build_corpus_report(
        results=results,
        skipped_station_days=skipped,
        window_start=start,
        window_end=end,
        stations=tuple(args.stations),
        generated_at_ns=now_ns,
    )
    report_path = out_dir / f"hypothetical_hold_corpus_report_{now_ns}.json"
    report_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    print(f"[hypothetical-hold] {len(results)} trial(s); wrote {report_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
