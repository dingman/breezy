"""Pure core for the offline "exit window" study
(``docs/plans/POSITION_EXIT_EXECUTION_2026-09-16.md``).

For a single filled live position, purely from already-loaded facts (no I/O,
no Nautilus runtime state, no wall clock), this module: (1) replays the
shadow monitor (``monitor_decision.evaluate_monitor`` + ``monitor_evidence
.build_monitor_evidence``, both imported UNMODIFIED) to find when it reached
THREATENED / DEAD (:func:`build_exit_timeline`); (2) at every evaluated
instant after the fill, walks the executable 1-lot exit (``monitor_evidence
.walk_exit_vwap`` on the latest Depth10 frame at/before that instant,
leg-aware) and its recoverable value after fee (:class:`ExitEvaluation`);
(3) tracks when the exit side emptied FOR GOOD -- the last instant with a
non-None walked price (:attr:`ExitTimeline.last_executable_ts_ns`); (4)
scores three counterfactual exit rules against hold-to-settlement -- R-DEAD
(sell at first DEAD confirmation if executable), R-THREAT (sell at first
REDUCE_RECOMMENDED/EXIT_RECOMMENDED if executable), R-BEST (oracle: the best
executable exit ever offered post-fill, an upper bound;
:func:`r_dead_outcome`, :func:`r_threat_outcome`, :func:`r_best_outcome`).

L-1 (native vs authored): GAP-FILLER glue only, same discipline as
``monitor_hypothetical_core.py`` (INC-8). Every piece of real machinery
(``build_monitor_evidence``/``evaluate_monitor``, ``RunningExtremeAccumulator``
-- supplied by the caller, never constructed here --, ``bucket_facts``/
``WeatherBucketFacts.contains``, ``width_and_m``/``p_hold_at``) is imported
unmodified; this module's own content is the replay loop joining them for
THIS study (an after-the-fact exit-window audit, distinct from INC-8's
hypothetical-entry corpus) plus the three counterfactual-rule helpers. Row
assembly, corpus summary and Markdown rendering live in the sibling
``exit_window_report.py`` (same split as ``monitor_hypothetical_core.py``/
``monitor_hypothetical_report.py``, to stay under the per-module line
guidance).

PnL convention: every position was booked as a plain LONG in its own leg's
price domain (``monitor_evidence`` module docstring's NO-leg sign-convention
note) -- ``fill_px``/``mark_vwap`` are directly comparable, no sign flip for
either leg. ``entry_cost = fill_px * qty + fee * qty`` (``fee`` is
per-contract, entry leg only -- ``FilledTrial.fee``'s docstring).
Hold-to-settlement payoff is ``qty`` if the leg won, else ``0``. An exit's
proceeds are exactly ``MonitorEvidence.recoverable_value`` (``mark_vwap *
qty - exit_fee``). Every rule's PnL is ``proceeds - entry_cost``; when a
rule's signal never becomes executable (or never fires), the position rides
to settlement and that rule's PnL degenerates to the hold PnL -- never zero,
never fabricated.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal

from nautilus_trader.model.data import OrderBookDepth10
from settlement_truth_dataset import bucket_facts

from breezy.domain.weather_bucket_facts import WeatherBucketFacts
from breezy.strategy.current_rung_hold.decision import RungBounds
from breezy.strategy.current_rung_hold.monitor_decision import (
    MonitorHistory,
    ThesisState,
    Verdict,
    evaluate_monitor,
)
from breezy.strategy.current_rung_hold.monitor_evidence import (
    Leg,
    build_monitor_evidence,
    p_hold_at,
)
from breezy.strategy.current_rung_hold.strategy import _local_hour
from breezy.strategy.current_rung_hold.tick_eval import width_and_m
from breezy.strategy.weather_common.running_extreme import RunningExtremeAccumulator, RunningMax

__all__ = [
    "ExitEvaluation",
    "ExitTimeline",
    "FilledPosition",
    "RuleOutcome",
    "build_exit_timeline",
    "entry_cost",
    "hold_pnl",
    "infer_preliminary_settlement",
    "r_best_outcome",
    "r_dead_outcome",
    "r_threat_outcome",
]

_ZERO: Final[Decimal] = Decimal(0)
_MINUTE_NS: Final[int] = 60_000_000_000
_NON_ALIVE_VERDICTS: Final[tuple[Verdict, ...]] = (
    Verdict.REDUCE_RECOMMENDED,
    Verdict.EXIT_RECOMMENDED,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class FilledPosition:
    """One filled live position: identity plus entry economics, everything
    the replay needs that is NOT computed from the tape. ``rung``/``leg``
    are resolved by the caller from the persisted instrument definition and
    ``breezy.domain.instrument_leg.leg_of_symbol`` -- never parsed here."""

    trial_id: str
    station: str
    climate_day: str  # ISO-8601 date, matching FilledTrial.climate_day
    season: str
    instrument_id: str
    leg: Leg
    rung: RungBounds
    fill_px: Decimal
    fee: Decimal  # per-contract, entry leg only
    held_qty: int
    filled_at_ns: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ExitEvaluation:
    """One shadow-monitor evaluation after the fill."""

    ts_ns: int
    state: ThesisState
    verdict: Verdict
    reason_codes: tuple[str, ...]
    mark_vwap: Decimal | None
    mark_source: Literal["depth_walk", "missing"]
    depth_sufficient: bool
    book_staleness_ns: int | None
    recoverable_value: Decimal | None
    running_max_lower: int
    running_max_upper: int

    @property
    def executable(self) -> bool:
        return self.mark_vwap is not None and self.depth_sufficient


@dataclass(frozen=True, slots=True, kw_only=True)
class ExitTimeline:
    position: FilledPosition
    p_hold_at_entry: Decimal | None
    evaluations: tuple[ExitEvaluation, ...]
    first_threatened_ts_ns: int | None
    first_dead_ts_ns: int | None
    last_executable_ts_ns: int | None


@dataclass(frozen=True, slots=True, kw_only=True)
class _DepthEvent:
    depth: OrderBookDepth10


@dataclass(frozen=True, slots=True, kw_only=True)
class _ObsEvent:
    ts_ns: int


def _entry_p_hold(
    *, position: FilledPosition, facts: WeatherBucketFacts, accumulator: RunningExtremeAccumulator,
    std_utc_offset_hours: float,
) -> Decimal | None:
    entry_running_max = accumulator.value_at(position.filled_at_ns)
    if entry_running_max is None:
        return None
    entry_hour = _local_hour(position.filled_at_ns, std_utc_offset_hours)
    entry_width, entry_m = width_and_m(facts, entry_running_max)
    return p_hold_at(
        station=position.station, season=position.season, hour_lst=entry_hour,
        width_code=entry_width, m_code=entry_m, leg=position.leg,
    )


def build_exit_timeline(
    *,
    position: FilledPosition,
    accumulator: RunningExtremeAccumulator,
    std_utc_offset_hours: float,
    fee_coefficient: Decimal,
    stale_observation_bound_ns: int,
    depth_frames: Sequence[OrderBookDepth10],
    observation_ts_ns: Sequence[int],
) -> ExitTimeline:
    """Replay the shadow monitor from the fill forward. ``depth_frames``/
    ``observation_ts_ns`` may include instants at or before the fill -- they
    are filtered here (never the caller's job), unlike
    ``monitor_hypothetical_core.replay_monitor``'s hard look-ahead refusal:
    this study replays an ALREADY-FILLED live position, so an at-fill-instant
    frame is simply outside the post-fill window, not a defect to raise on.
    """
    facts = bucket_facts(
        lower_f=position.rung[0], upper_f=position.rung[1], station=position.station,
        climate_day=dt.date.fromisoformat(position.climate_day),
    )
    p_hold_at_entry = _entry_p_hold(
        position=position, facts=facts, accumulator=accumulator,
        std_utc_offset_hours=std_utc_offset_hours,
    )

    later_depth = tuple(f for f in depth_frames if f.ts_init > position.filled_at_ns)
    later_obs_ts = tuple(sorted({ts for ts in observation_ts_ns if ts > position.filled_at_ns}))

    events: list[tuple[int, int, object]] = [
        (frame.ts_init, 1, _DepthEvent(depth=frame)) for frame in later_depth
    ]
    events.extend((ts, 0, _ObsEvent(ts_ns=ts)) for ts in later_obs_ts)
    events.sort(key=lambda item: (item[0], item[1]))

    history = MonitorHistory.EMPTY
    last_depth: OrderBookDepth10 | None = None
    last_depth_ts_ns: int | None = None
    evaluations: list[ExitEvaluation] = []
    first_threatened_ts_ns: int | None = None
    first_dead_ts_ns: int | None = None
    last_executable_ts_ns: int | None = None

    for ts_ns, _tiebreak, event in events:
        book_staleness_ns: int | None
        if isinstance(event, _DepthEvent):
            last_depth = event.depth
            last_depth_ts_ns = ts_ns
            depth = event.depth
            book_staleness_ns = 0
        else:
            depth = last_depth
            book_staleness_ns = None if last_depth_ts_ns is None else ts_ns - last_depth_ts_ns

        running_max: RunningMax | None = accumulator.value_at(ts_ns)
        if running_max is None:
            continue
        staleness_ns = accumulator.staleness_ns(ts_ns)
        hour_lst = _local_hour(ts_ns, std_utc_offset_hours)
        width_code, m_code = width_and_m(facts, running_max)

        evidence = build_monitor_evidence(
            ts_ns=ts_ns,
            instrument_id=position.instrument_id,
            station=position.station,
            climate_day=position.climate_day,
            season=position.season,
            hour_lst=hour_lst,
            width_code=width_code,
            m_code=m_code,
            leg=position.leg,
            entry_context="exit_window_study",
            fill_px=position.fill_px,
            held_qty=position.held_qty,
            running_max_lower=running_max.lower_f,
            running_max_upper=running_max.upper_f,
            staleness_ns=staleness_ns,
            book_staleness_ns=book_staleness_ns,
            rung_low=position.rung[0],
            rung_high=position.rung[1],
            depth=depth,
            fee_coefficient=fee_coefficient,
            p_hold_at_entry=p_hold_at_entry,
            observed_at_ns=running_max.source_observed_at_ns,
        )
        decision, history = evaluate_monitor(
            evidence, history, stale_observation_bound_ns=stale_observation_bound_ns,
        )

        evaluation = ExitEvaluation(
            ts_ns=ts_ns,
            state=decision.state,
            verdict=decision.verdict,
            reason_codes=decision.reason_codes,
            mark_vwap=evidence.mark_vwap,
            mark_source=evidence.mark_source,
            depth_sufficient=evidence.depth_sufficient,
            book_staleness_ns=evidence.book_staleness_ns,
            recoverable_value=evidence.recoverable_value,
            running_max_lower=evidence.running_max_lower,
            running_max_upper=evidence.running_max_upper,
        )
        evaluations.append(evaluation)

        if evaluation.executable:
            last_executable_ts_ns = ts_ns
        if first_threatened_ts_ns is None and decision.state is ThesisState.THREATENED:
            first_threatened_ts_ns = ts_ns
        if first_dead_ts_ns is None and decision.state is ThesisState.DEAD_BY_OBSERVATION:
            first_dead_ts_ns = ts_ns

    return ExitTimeline(
        position=position,
        p_hold_at_entry=p_hold_at_entry,
        evaluations=tuple(evaluations),
        first_threatened_ts_ns=first_threatened_ts_ns,
        first_dead_ts_ns=first_dead_ts_ns,
        last_executable_ts_ns=last_executable_ts_ns,
    )


# ---------------------------------------------------------------------------
# PnL: entry cost, hold-to-settlement, and the three counterfactual rules
# ---------------------------------------------------------------------------


def entry_cost(position: FilledPosition) -> Decimal:
    """Total cost booked at entry: fill price plus per-contract fee, times qty."""
    qty = Decimal(position.held_qty)
    return position.fill_px * qty + position.fee * qty


def hold_pnl(position: FilledPosition, *, settled_held: bool | None) -> Decimal | None:
    """Hold-to-settlement PnL, or ``None`` when the outcome is unknown."""
    if settled_held is None:
        return None
    payoff = Decimal(position.held_qty) if settled_held else _ZERO
    return payoff - entry_cost(position)


@dataclass(frozen=True, slots=True, kw_only=True)
class RuleOutcome:
    """One counterfactual exit rule's outcome for one position. ``status`` is
    ``"exited"`` (signal fired and was executable), ``"unfillable"`` (signal
    fired but the exit side had no executable price -- rides to settlement,
    ``pnl`` degenerates to the hold PnL), or ``"no_signal"`` (trigger never
    occurred -- also rides to settlement)."""

    rule: str
    status: Literal["exited", "unfillable", "no_signal"]
    signal_ts_ns: int | None
    exit_ts_ns: int | None
    exit_price: Decimal | None
    pnl: Decimal | None


def _held_outcome(
    *, rule: str, status: Literal["unfillable", "no_signal"], signal_ts_ns: int | None,
    hold_pnl_value: Decimal | None,
) -> RuleOutcome:
    return RuleOutcome(
        rule=rule, status=status, signal_ts_ns=signal_ts_ns, exit_ts_ns=None, exit_price=None,
        pnl=hold_pnl_value,
    )


def _outcome_for_signal(
    *, rule: str, timeline: ExitTimeline, signal_ts_ns: int | None, hold_pnl_value: Decimal | None,
) -> RuleOutcome:
    if signal_ts_ns is None:
        return _held_outcome(
            rule=rule, status="no_signal", signal_ts_ns=None, hold_pnl_value=hold_pnl_value,
        )
    evaluation = next(e for e in timeline.evaluations if e.ts_ns == signal_ts_ns)
    if not evaluation.executable:
        return _held_outcome(
            rule=rule, status="unfillable", signal_ts_ns=signal_ts_ns,
            hold_pnl_value=hold_pnl_value,
        )
    assert evaluation.recoverable_value is not None
    pnl = evaluation.recoverable_value - entry_cost(timeline.position)
    return RuleOutcome(
        rule=rule, status="exited", signal_ts_ns=signal_ts_ns, exit_ts_ns=signal_ts_ns,
        exit_price=evaluation.mark_vwap, pnl=pnl,
    )


def r_dead_outcome(timeline: ExitTimeline, *, hold_pnl_value: Decimal | None) -> RuleOutcome:
    """Sell at the first DEAD confirmation, if executable there."""
    return _outcome_for_signal(
        rule="R-DEAD", timeline=timeline, signal_ts_ns=timeline.first_dead_ts_ns,
        hold_pnl_value=hold_pnl_value,
    )


def r_threat_outcome(timeline: ExitTimeline, *, hold_pnl_value: Decimal | None) -> RuleOutcome:
    """Sell at the first REDUCE_RECOMMENDED/EXIT_RECOMMENDED verdict, if executable there."""
    signal_ts_ns = next(
        (e.ts_ns for e in timeline.evaluations if e.verdict in _NON_ALIVE_VERDICTS), None,
    )
    return _outcome_for_signal(
        rule="R-THREAT", timeline=timeline, signal_ts_ns=signal_ts_ns,
        hold_pnl_value=hold_pnl_value,
    )


def r_best_outcome(timeline: ExitTimeline, *, hold_pnl_value: Decimal | None) -> RuleOutcome:
    """Oracle upper bound, never a real strategy: the single best executable
    exit ever offered after the fill -- whichever evaluation maximises
    ``recoverable_value``, which may be an EARLIER, cheaper-priced frame than
    a later one if the later one is worse (or unfillable)."""
    executable = [e for e in timeline.evaluations if e.executable]
    if not executable:
        return _held_outcome(
            rule="R-BEST", status="no_signal", signal_ts_ns=None, hold_pnl_value=hold_pnl_value,
        )
    best = max(executable, key=lambda e: e.recoverable_value)  # type: ignore[arg-type,return-value]
    assert best.recoverable_value is not None
    pnl = best.recoverable_value - entry_cost(timeline.position)
    return RuleOutcome(
        rule="R-BEST", status="exited", signal_ts_ns=best.ts_ns, exit_ts_ns=best.ts_ns,
        exit_price=best.mark_vwap, pnl=pnl,
    )


# ---------------------------------------------------------------------------
# Settlement resolution: scored trial store, else PRELIMINARY inference
# ---------------------------------------------------------------------------


def infer_preliminary_settlement(
    *, facts: WeatherBucketFacts, final_running_max: RunningMax | None, leg: Leg,
) -> bool | None:
    """Best-effort, PRELIMINARY settlement guess from the running max alone,
    used only when no scored-trial row exists yet (the day has not settled
    FINAL). Prefers ``exact_f`` (a genuine METAR reading); otherwise falls
    back to the running-max interval's own relationship to the rung --
    ``None`` when it straddles the boundary (ambiguous, never guessed).

    L-44 correction (2026-09-16): rung bounds are CLOSED everywhere in this
    repo and at the venue (``docs/evidence/venue/polymarket_us/THRESHOLD_
    SEMANTICS_2026-08-25.md`` "INCLUSIVE PROVEN"; ``WeatherBucketFacts
    .contains`` uses ``<=``), and ``facts.contains(...)`` answers the YES
    leg's own win condition. A NO leg wins iff the settled value lands
    OUTSIDE the rung -- the exact COMPLEMENT of YES's answer, never
    ``contains(...)`` taken directly. The "straddles the boundary" ambiguous
    case stays ``None`` for BOTH legs (never negated -- "unknown" has no
    complement)."""
    if final_running_max is None:
        return None
    if final_running_max.exact_f is not None:
        yes_wins = facts.contains(final_running_max.exact_f)
        return yes_wins if leg == "YES" else not yes_wins
    lower_inside = facts.contains(final_running_max.lower_f)
    upper_inside = facts.contains(final_running_max.upper_f)
    if lower_inside and upper_inside:
        yes_wins = True
    elif not lower_inside and not upper_inside:
        yes_wins = False
    else:
        return None
    return yes_wins if leg == "YES" else not yes_wins

