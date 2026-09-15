"""Pure thesis classifier for the intra-day shadow position monitor (INC-3).

L-1: GAP. Nautilus has no position-thesis state machine at all -- this
module is the authored piece
(``docs/plans/INTRADAY_POSITION_MONITOR_2026-09-15.md`` §3, Rev 2.1 addendum
P6). PURE: takes a :class:`~breezy.strategy.current_rung_hold.monitor_evidence.MonitorEvidence`
and the prior :class:`MonitorHistory`, returns a new
:class:`MonitorDecision` and a NEW (never mutated) :class:`MonitorHistory`.
No Nautilus import, no I/O, no clock read.

Every hysteresis/threshold constant below is ``Final`` and PROVISIONAL until
INC-8 (the archived-tape hypothetical-hold corpus) calibrates it (plan §0,
§8) -- do not treat any of them as tuned.

Rule order (plan §3, Rev 2.1 addendum P6):

1. Stale observation (``evidence.staleness_ns`` unavailable or beyond the
   caller-supplied bound) -> ``UNKNOWN``/``UNKNOWN``, reason
   ``stale_observation``. UNKNOWN never maps to an EXIT verdict.
2. DEAD_BY_OBSERVATION is a CLASSIFIER, not a one-shot trigger: it requires
   ``running_max_lower > rung_high`` on >= 2 observations at DISTINCT
   ``ts_ns`` spanning >= ``_DEAD_MIN_CONFIRM_SPAN_NS`` (P6: symmetric with
   THREATENED's own span guard). A same-instant re-push of the same ``ts_ns``
   never counts twice. Until confirmed, the reported state/verdict stay
   whatever they were before this reading, tagged reason ``dead_candidate``.
3. Once DEAD is CONFIRMED, the verdict is an executable-exit test: a fresh,
   sufficient, leg-aware Depth10 walk (``mark_source == "depth_walk"``,
   ``depth_sufficient``, ``book_staleness_ns <= _BOOK_STALE_NS``) ->
   ``EXIT_RECOMMENDED``; otherwise ``MISSING_STOP`` (L-38: an exit whose leg
   cannot fill is a MISSING stop, never silently absorbed as HOLD).
4. ``LOCKED_BY_OBSERVATION`` (mechanistic, informational): the running-max
   interval sits fully inside ``[rung_low, rung_high]`` AND
   ``hour_lst >= _LOCKED_HOUR_LST`` -> verdict ``HOLD``.
5. Otherwise, THESIS is decided from the same-cell ``p_hold_at_t`` re-lookup
   against ``p_hold_at_entry``: a drop >= ``_P_HOLD_DROP_MARGIN`` is a
   THREATENED candidate; ``_THREATENED_CONFIRMATIONS`` CONSECUTIVE candidates
   spanning >= ``_THREATENED_MIN_SPAN_NS`` flips ALIVE -> THREATENED.
   Recovery is symmetric: the same confirmation/span pattern on the
   OPPOSITE direction flips THREATENED back to ALIVE (hysteresis both ways).
   A single reading in the "wrong" direction resets any in-progress run
   (M6): ``p_hold_at_t is None`` (undefined cell -- an hour outside the
   table's coverage, or an under-powered cell) means membership-only logic:
   no candidate run advances either way, the prior ALIVE/THREATENED
   classification is simply repeated, tagged reason ``p_hold_undefined``.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, ClassVar, Final

if TYPE_CHECKING:  # pragma: no cover - typing only
    from breezy.strategy.current_rung_hold.monitor_evidence import MonitorEvidence

__all__ = [
    "MonitorDecision",
    "MonitorHistory",
    "ThesisState",
    "Verdict",
    "evaluate_monitor",
    "should_emit",
]

#: PROVISIONAL (plan §0/§8) -- calibrated by INC-8, not before.
_P_HOLD_DROP_MARGIN: Final[Decimal] = Decimal("0.10")
_THREATENED_CONFIRMATIONS: Final[int] = 3
_THREATENED_MIN_SPAN_NS: Final[int] = 10 * 60 * 1_000_000_000
_DEAD_CONFIRMATIONS: Final[int] = 2
#: P6 addendum: symmetric with ``_THREATENED_MIN_SPAN_NS``, also PROVISIONAL.
_DEAD_MIN_CONFIRM_SPAN_NS: Final[int] = 5 * 60 * 1_000_000_000
_LOCKED_HOUR_LST: Final[int] = 18
#: Same order as HF-4's ``_REARM_EVIDENCE_MAX_AGE_NS`` (plan §3).
_BOOK_STALE_NS: Final[int] = 180 * 1_000_000_000
_HEARTBEAT_NS: Final[int] = 60 * 1_000_000_000

_TOWARD_THREATENED: Final[str] = "toward_threatened"
_TOWARD_ALIVE: Final[str] = "toward_alive"


class ThesisState(str, Enum):
    ALIVE = "ALIVE"
    THREATENED = "THREATENED"
    DEAD_BY_OBSERVATION = "DEAD_BY_OBSERVATION"
    LOCKED_BY_OBSERVATION = "LOCKED_BY_OBSERVATION"
    UNKNOWN = "UNKNOWN"


class Verdict(str, Enum):
    HOLD = "HOLD"
    REDUCE_RECOMMENDED = "REDUCE_RECOMMENDED"
    EXIT_RECOMMENDED = "EXIT_RECOMMENDED"
    MISSING_STOP = "MISSING_STOP"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True, kw_only=True)
class MonitorDecision:
    state: ThesisState
    verdict: Verdict
    reason_codes: tuple[str, ...]
    confirmations: int
    ts_ns: int


@dataclass(frozen=True, slots=True, kw_only=True)
class MonitorHistory:
    """Immutable carry-forward state between two :func:`evaluate_monitor`
    calls for the SAME held position. Never mutated -- every transition
    returns a brand-new instance via :func:`dataclasses.replace`.
    """

    last_state: ThesisState | None
    last_verdict: Verdict | None
    #: One of ``_TOWARD_THREATENED``/``_TOWARD_ALIVE``, or ``None`` when no
    #: hysteresis run is in progress.
    candidate_state: str | None
    candidate_count: int
    candidate_first_ts_ns: int | None
    #: Distinct ``ts_ns`` values at which the DEAD structural condition
    #: (``running_max_lower > rung_high``) has held, consecutively, with no
    #: intervening non-qualifying reading. Reset to ``()`` the instant a
    #: reading fails to qualify.
    dead_confirm_observed_ns: tuple[int, ...]
    last_emitted_ts_ns: int | None

    EMPTY: ClassVar[MonitorHistory]


MonitorHistory.EMPTY = MonitorHistory(
    last_state=None,
    last_verdict=None,
    candidate_state=None,
    candidate_count=0,
    candidate_first_ts_ns=None,
    dead_confirm_observed_ns=(),
    last_emitted_ts_ns=None,
)


def _dead_confirm_key(evidence: MonitorEvidence) -> int:
    """The instant a DEAD-confirming reading is keyed on.

    2026-09-15 correction (INC-3 author's open question): keying on
    ``evidence.ts_ns`` (the EVALUATION timestamp) let two depth-only
    evaluations of the SAME station observation, minutes apart, "confirm"
    DEAD on a single observation. The correct key is the OBSERVATION's own
    ``observed_at_ns`` -- distinct observation instants only. Falls back to
    ``ts_ns`` when ``observed_at_ns`` is ``None`` (evidence built before this
    field existed, or a caller that never threads it through), which
    reproduces the exact prior behaviour for those callers.
    """
    return evidence.ts_ns if evidence.observed_at_ns is None else evidence.observed_at_ns


def _update_dead_confirmation(
    observed: tuple[int, ...], observed_key: int, *, qualifies: bool
) -> tuple[tuple[int, ...], bool]:
    """Fold one reading into the DEAD confirmation window.

    A non-qualifying reading resets the window to empty. A qualifying
    reading at an ``observed_key`` (see :func:`_dead_confirm_key`) already
    present is a same-instant re-push and never counts twice (module
    docstring rule 2). Confirmed once the window holds
    >= ``_DEAD_CONFIRMATIONS`` distinct instants spanning
    >= ``_DEAD_MIN_CONFIRM_SPAN_NS``.
    """
    if not qualifies:
        return (), False
    new_observed = observed if observed_key in observed else (*observed, observed_key)
    confirmed = (
        len(new_observed) >= _DEAD_CONFIRMATIONS
        and (max(new_observed) - min(new_observed)) >= _DEAD_MIN_CONFIRM_SPAN_NS
    )
    return new_observed, confirmed


def _is_locked(evidence: MonitorEvidence) -> bool:
    if evidence.rung_low is None or evidence.rung_high is None:
        return False
    return (
        evidence.running_max_lower >= evidence.rung_low
        and evidence.running_max_upper <= evidence.rung_high
        and evidence.hour_lst >= _LOCKED_HOUR_LST
    )


def _dead_verdict(evidence: MonitorEvidence) -> Verdict:
    fillable = (
        evidence.mark_source == "depth_walk"
        and evidence.depth_sufficient
        and evidence.book_staleness_ns is not None
        and evidence.book_staleness_ns <= _BOOK_STALE_NS
    )
    return Verdict.EXIT_RECOMMENDED if fillable else Verdict.MISSING_STOP


def _evaluate_threatened_alive(
    evidence: MonitorEvidence, history: MonitorHistory
) -> tuple[ThesisState, Verdict, tuple[str, ...], int, MonitorHistory]:
    currently_threatened = history.last_state is ThesisState.THREATENED

    if evidence.p_hold_at_entry is None or evidence.p_hold_at_t is None:
        state = ThesisState.THREATENED if currently_threatened else ThesisState.ALIVE
        verdict = Verdict.REDUCE_RECOMMENDED if currently_threatened else Verdict.HOLD
        new_history = dataclasses.replace(
            history, candidate_state=None, candidate_count=0, candidate_first_ts_ns=None,
        )
        return state, verdict, ("p_hold_undefined",), 0, new_history

    drop = evidence.p_hold_at_entry - evidence.p_hold_at_t
    is_candidate = drop >= _P_HOLD_DROP_MARGIN
    relevant = (not currently_threatened and is_candidate) or (
        currently_threatened and not is_candidate
    )
    label = _TOWARD_THREATENED if not currently_threatened else _TOWARD_ALIVE

    if not relevant:
        new_history = dataclasses.replace(
            history, candidate_state=None, candidate_count=0, candidate_first_ts_ns=None,
        )
        state = ThesisState.THREATENED if currently_threatened else ThesisState.ALIVE
        verdict = Verdict.REDUCE_RECOMMENDED if currently_threatened else Verdict.HOLD
        return state, verdict, (), 0, new_history

    if history.candidate_state == label and history.candidate_first_ts_ns is not None:
        count = history.candidate_count + 1
        first_ts = history.candidate_first_ts_ns
    else:
        count = 1
        first_ts = evidence.ts_ns

    span_ns = evidence.ts_ns - first_ts
    flips = count >= _THREATENED_CONFIRMATIONS and span_ns >= _THREATENED_MIN_SPAN_NS

    if flips:
        state = ThesisState.ALIVE if currently_threatened else ThesisState.THREATENED
        new_history = dataclasses.replace(
            history, candidate_state=None, candidate_count=0, candidate_first_ts_ns=None,
        )
        return state, (
            Verdict.REDUCE_RECOMMENDED if state is ThesisState.THREATENED else Verdict.HOLD
        ), (), 0, new_history

    state = ThesisState.THREATENED if currently_threatened else ThesisState.ALIVE
    verdict = Verdict.REDUCE_RECOMMENDED if currently_threatened else Verdict.HOLD
    reason = "p_hold_recovery_candidate" if label == _TOWARD_ALIVE else "p_hold_drop_candidate"
    new_history = dataclasses.replace(
        history, candidate_state=label, candidate_count=count, candidate_first_ts_ns=first_ts,
    )
    return state, verdict, (reason,), count, new_history


def evaluate_monitor(
    evidence: MonitorEvidence,
    history: MonitorHistory,
    *,
    stale_observation_bound_ns: int,
) -> tuple[MonitorDecision, MonitorHistory]:
    """Classify one evaluation. ``stale_observation_bound_ns`` is the SAME
    bound ``evaluate_decision`` uses
    (``config.stale_observation_minutes * 60_000_000_000``) -- taken as a
    parameter here rather than re-declared, so the two paths never disagree
    on what "stale" means.
    """
    if evidence.staleness_ns is None or evidence.staleness_ns > stale_observation_bound_ns:
        new_history = dataclasses.replace(
            history,
            last_state=ThesisState.UNKNOWN,
            last_verdict=Verdict.UNKNOWN,
            candidate_state=None,
            candidate_count=0,
            candidate_first_ts_ns=None,
            dead_confirm_observed_ns=(),
        )
        decision = MonitorDecision(
            state=ThesisState.UNKNOWN,
            verdict=Verdict.UNKNOWN,
            reason_codes=("stale_observation",),
            confirmations=0,
            ts_ns=evidence.ts_ns,
        )
        return decision, new_history

    dead_qualifies = (
        evidence.rung_high is not None and evidence.running_max_lower > evidence.rung_high
    )
    dead_confirm_ns, dead_confirmed = _update_dead_confirmation(
        history.dead_confirm_observed_ns, _dead_confirm_key(evidence), qualifies=dead_qualifies,
    )

    if dead_confirmed:
        verdict = _dead_verdict(evidence)
        new_history = dataclasses.replace(
            history,
            last_state=ThesisState.DEAD_BY_OBSERVATION,
            last_verdict=verdict,
            candidate_state=None,
            candidate_count=0,
            candidate_first_ts_ns=None,
            dead_confirm_observed_ns=dead_confirm_ns,
        )
        decision = MonitorDecision(
            state=ThesisState.DEAD_BY_OBSERVATION,
            verdict=verdict,
            reason_codes=("dead_confirmed",),
            confirmations=len(dead_confirm_ns),
            ts_ns=evidence.ts_ns,
        )
        return decision, new_history

    if dead_qualifies:
        prev_state = history.last_state if history.last_state is not None else ThesisState.ALIVE
        prev_verdict = history.last_verdict if history.last_verdict is not None else Verdict.HOLD
        new_history = dataclasses.replace(history, dead_confirm_observed_ns=dead_confirm_ns)
        decision = MonitorDecision(
            state=prev_state,
            verdict=prev_verdict,
            reason_codes=("dead_candidate",),
            confirmations=len(dead_confirm_ns),
            ts_ns=evidence.ts_ns,
        )
        return decision, new_history

    if _is_locked(evidence):
        new_history = dataclasses.replace(
            history,
            last_state=ThesisState.LOCKED_BY_OBSERVATION,
            last_verdict=Verdict.HOLD,
            candidate_state=None,
            candidate_count=0,
            candidate_first_ts_ns=None,
            dead_confirm_observed_ns=dead_confirm_ns,
        )
        decision = MonitorDecision(
            state=ThesisState.LOCKED_BY_OBSERVATION,
            verdict=Verdict.HOLD,
            reason_codes=("locked",),
            confirmations=0,
            ts_ns=evidence.ts_ns,
        )
        return decision, new_history

    state, verdict, reason_codes, confirmations, ta_history = _evaluate_threatened_alive(
        evidence, history,
    )
    new_history = dataclasses.replace(
        ta_history,
        last_state=state,
        last_verdict=verdict,
        dead_confirm_observed_ns=dead_confirm_ns,
    )
    decision = MonitorDecision(
        state=state,
        verdict=verdict,
        reason_codes=reason_codes,
        confirmations=confirmations,
        ts_ns=evidence.ts_ns,
    )
    return decision, new_history


def should_emit(decision: MonitorDecision, history: MonitorHistory, now_ns: int) -> bool:
    """Change-or-heartbeat emission gate (plan §4, M2).

    ``history`` must be the PRE-evaluation history (the one passed INTO
    :func:`evaluate_monitor`, before its update) -- comparing against the
    POST-evaluation history would always see ``decision.state ==
    new_history.last_state`` and never detect a change.
    """
    if history.last_state is None or history.last_verdict is None:
        return True
    if decision.state != history.last_state or decision.verdict != history.last_verdict:
        return True
    if history.last_emitted_ts_ns is None:
        return True
    return now_ns - history.last_emitted_ts_ns >= _HEARTBEAT_NS
