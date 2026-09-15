"""Pure hypothetical-hold selection and shadow-monitor replay for INC-8.

Split out of ``current_rung_hold_monitor_hypothetical_hold.py`` (behaviour-
preserving; see that module's docstring for the full INC-8 spec context and
the L-1 native/gap verdict -- unchanged by this split). This module carries
the two pure functions the corpus builds on:

1. :func:`select_hypothetical_holds` -- would the live strategy's OWN entry
   rule (``evaluate_decision``, unmodified, imported -- never re-derived)
   have taken a position that day, and at what snapshot?
2. :func:`replay_monitor` -- from that instant forward, what would the SHADOW
   MONITOR (``monitor_evidence.build_monitor_evidence`` +
   ``monitor_decision.evaluate_monitor``, both imported unmodified) have
   said, evaluated against every LATER observation and Depth10 frame with
   ``ts_init > take.ts_ns`` only -- never a look-ahead peek?

Report aggregation (``CorpusReport``/``build_corpus_report``) and all real
I/O live in the sibling modules ``monitor_hypothetical_report.py`` and
``current_rung_hold_monitor_hypothetical_hold.py`` respectively; nothing here
touches a catalog, a cache file, or the live node or strategy.
"""

from __future__ import annotations

import datetime as dt
import inspect
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from nautilus_trader.model.data import BookOrder, OrderBookDepth10
from settlement_truth_dataset import bucket_facts, settles_yes

from breezy.domain.season import season_for
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
from breezy.strategy.current_rung_hold.strategy import _local_hour
from breezy.strategy.current_rung_hold.tick_eval import (
    instrument_rung_is_current,
    width_and_m,
)
from breezy.strategy.weather_common.running_extreme import RunningExtremeAccumulator

#: Same set the live strategy and every archive study condition on
#: (``mb_current_rung_edge_study.ARCHIVE_HOURS``, ``config.py``'s window).
ARCHIVE_HOURS: Final[tuple[int, ...]] = (12, 13, 14, 15, 16)
WINDOW_START_HOUR_LST: Final[int] = 12
WINDOW_END_HOUR_LST: Final[int] = 17  # exclusive

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
    """Extra per-trial facts :func:`~monitor_hypothetical_report
    .build_corpus_report` aggregates -- everything ``PositionMonitorSummary``
    has no column for."""

    archive_covered_evaluations: int
    threatened_evaluations: int
    dead_evaluations: int
    missing_stop_evaluations: int
    reason_code_counts: Mapping[str, int]
    dead_confirmation_spans_ns: tuple[int, ...]
    threatened_confirmation_spans_ns: tuple[int, ...]
    exit_recommended_recoverable_values: tuple[Decimal, ...]


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
