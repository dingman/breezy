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
4. ``LOCKED_BY_OBSERVATION`` (PLATEAU confirmation mode, 2026-09-16
   correction -- see the "Confirmation modes" note below; previously
   mechanistic/immediate, which is what let a same-instant repush "confirm"
   on the very first qualifying reading): the running-max interval sits
   fully inside ``[rung_low, rung_high]`` AND ``hour_lst >= _LOCKED_HOUR_LST``
   is the QUALIFYING condition; CONFIRMED once the run has spanned
   >= ``_DEAD_MIN_CONFIRM_SPAN_NS`` of EVALUATION time (``ts_ns``) since the
   first qualifying reading AND >= 1 reading in the run carried a genuine
   observation (``observed_at_ns is not None``) -> verdict ``HOLD``. Until
   confirmed, the reported state/verdict stay whatever they were before this
   reading, reason ``lock_candidate`` (mirrors rule 2's ``dead_candidate``
   shape).
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

Confirmation modes (2026-09-16 correction, L-44): two distinct confirmation
shapes exist for structural (non-``p_hold``) conditions, and the two must
never be conflated. RISING (``_update_dead_confirmation``, keyed on distinct
``observed_at_ns`` instants via :func:`_dead_confirm_key`) is correct when
the qualifying fact is a value CLIMBING past a threshold -- each fresh
confirming instant necessarily carries a NEW ``observed_at_ns`` because the
running max just changed to produce it. PLATEAU
(``_update_plateau_confirmation``, keyed on elapsed EVALUATION-time span
(``ts_ns``) since the first qualifying reading, gated on >= 1 reading in the
run carrying a genuine observation) is correct when the qualifying fact is a
value HOLDING STILL -- the running max has STOPPED moving, so no new
distinct ``observed_at_ns`` ever arrives and the RISING gate is structurally
unsatisfiable (this was exactly the 2026-09-16 defect: a NO position stuck
inside its rung past the peak hour reported ``dead_candidate conf=1``
forever, because ``_update_dead_confirmation``'s >= 2-distinct-instant gate
can never be satisfied by a frozen instant). Rule 2 (YES DEAD) and the NO
win-lock bullet below are RISING; rule 4 (LOCKED, both legs) and the NO
inside-rung-after-peak DEAD bullet below are PLATEAU. A stale reading resets
BOTH modes' progress identically (``evaluate_monitor``'s stale branch clears
every confirmation buffer before either mode is ever consulted).

Leg semantics (2026-09-15 correction, plan Rev 2.1 addendum P6 follow-up --
the classifier above was YES-shaped; rules 1-5 describe the YES leg only and
stay UNCHANGED for it). A NO leg pays iff the settled high lands OUTSIDE the
rung, so the two geometric facts rules 2-4 key on INVERT their meaning and
are evaluated by a separate ``_evaluate_no`` path:

* ``running_max_lower > rung_high`` (rule 2's structural DEAD condition for
  YES -- the running max has already cleared the rung) is the NO leg's
  WIN-LOCKED state instead: once true it cannot lose. Still gated behind the
  SAME RISING >= 2-distinct-observation, >= ``_DEAD_MIN_CONFIRM_SPAN_NS``
  confirmation rule as YES's DEAD (a single reading can be noise even for a
  locked win, and the max clearing the rung is itself a RISING event) --
  confirmed -> ``LOCKED_BY_OBSERVATION``/``HOLD``, reason
  ``no_leg_win_locked``; unconfirmed -> reason ``dead_candidate`` (shared with
  YES's own unconfirmed-DEAD candidate tag; both describe "a structural
  terminal condition is building but not yet confirmed").
* The running-max interval sitting fully inside ``[rung_low, rung_high]``
  with the peak passed (rule 4's ``_is_locked`` predicate, PLATEAU-confirmed
  for BOTH legs) is the NO leg's LOSING terminal state instead -- the high is
  captured inside the rung after the day's peak, so the NO leg is
  economically dead. This NO-leg DEAD condition is confirmation-gated by the
  PLATEAU mode (:func:`_update_plateau_confirmation`, tracked in
  ``MonitorHistory.locked_confirm_progress`` -- shared with YES's own rule-4
  LOCKED plateau progress, safe because a position's leg never changes
  mid-flight, so only one of ``_evaluate_yes``/``_evaluate_no`` ever touches
  it for a given history) because declaring a leg dead is a stronger claim
  than declaring it informationally locked. Confirmed -> ``DEAD_BY_OBSERVATION``
  -> the same executable-exit test as YES's rule 3 (``mark_source ==
  "depth_walk"``, ``depth_sufficient``, ``book_staleness_ns <=
  _BOOK_STALE_NS``; the NO leg's own walk already prices off ``depth.asks``
  per ``monitor_evidence.walk_exit_vwap``) -> ``EXIT_RECOMMENDED``/
  ``MISSING_STOP``, reason ``no_leg_inside_rung_after_peak``; unconfirmed ->
  ``dead_candidate``.
* Before the peak hour, the SAME "fully inside the rung" geometry is merely
  THREATENED-shaped for NO -- the high may still climb out and save the
  leg -- so it drives the SAME 3-confirmation/``_THREATENED_MIN_SPAN_NS``
  symmetric hysteresis machinery as YES's rule 5 (shared via
  ``_evaluate_hysteresis``), just keyed on this geometric boolean instead of
  a ``p_hold`` drop: building candidate -> reason ``no_inside_rung``;
  building recovery (leaving the rung again) -> reason ``no_leg_recovering``.
  The NO leg never consults ``p_hold_at_entry``/``p_hold_at_t`` at all --
  its thesis is purely a function of the running-max interval's geometric
  relationship to the rung and the clock, never the probability table.
* Otherwise (interval below the rung, or rung geometry undefined) -> plain
  ``ALIVE``/``HOLD``, same as YES's "nothing is happening" fallback.

Invariant: a NO leg never reports ``LOCKED_BY_OBSERVATION`` while the
interval sits inside the rung (LOCKED requires the interval to be entirely
above it) -- see
``test_no_leg_never_reports_locked_while_the_interval_is_inside_the_rung``.
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
class _PlateauProgress:
    """PLATEAU-mode confirmation progress (module docstring's "Confirmation
    modes" note) for one in-progress structural candidacy.

    Unlike the RISING mode's ``tuple[int, ...]`` of distinct
    ``observed_at_ns`` instants, a plateau's qualifying evidence is that a
    value has STOPPED changing -- so ``observed_at_ns`` freezes at whatever
    instant last set it and never contributes a second distinct value.
    Progress is instead an elapsed EVALUATION-time span (``ts_ns``) since the
    first qualifying reading, gated on ``has_observation`` so a run that
    never carried a single genuine observation (``observed_at_ns`` always
    ``None``) can never confirm purely off evaluation-clock ticks.
    """

    first_ts_ns: int | None
    qualifying_count: int
    has_observation: bool

    EMPTY: ClassVar[_PlateauProgress]


_PlateauProgress.EMPTY = _PlateauProgress(
    first_ts_ns=None,
    qualifying_count=0,
    has_observation=False,
)


def _update_plateau_confirmation(
    progress: _PlateauProgress,
    ts_ns: int,
    observed_at_ns: int | None,
    *,
    qualifies: bool,
) -> tuple[_PlateauProgress, bool]:
    """Fold one reading into a PLATEAU confirmation window.

    A non-qualifying reading resets progress to :attr:`_PlateauProgress.EMPTY`
    (same reset semantics as :func:`_update_dead_confirmation`). A stale
    reading resets it too, for free -- ``evaluate_monitor``'s stale branch
    already clears every confirmation buffer before either mode is
    consulted. Confirmed once the run has spanned
    >= ``_DEAD_MIN_CONFIRM_SPAN_NS`` of evaluation time since the first
    qualifying reading AND at least one reading in the run carried a genuine
    observation.
    """
    if not qualifies:
        return _PlateauProgress.EMPTY, False
    first_ts_ns = progress.first_ts_ns if progress.first_ts_ns is not None else ts_ns
    has_observation = progress.has_observation or observed_at_ns is not None
    new_progress = _PlateauProgress(
        first_ts_ns=first_ts_ns,
        qualifying_count=progress.qualifying_count + 1,
        has_observation=has_observation,
    )
    confirmed = has_observation and (ts_ns - first_ts_ns) >= _DEAD_MIN_CONFIRM_SPAN_NS
    return new_progress, confirmed


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
    #: Distinct ``ts_ns`` values at which the ``running_max_lower >
    #: rung_high`` structural condition has held, consecutively, with no
    #: intervening non-qualifying reading. Reset to ``()`` the instant a
    #: reading fails to qualify. YES: confirms DEAD. NO: confirms the
    #: win-locked state (module docstring's leg semantics section).
    dead_confirm_observed_ns: tuple[int, ...]
    #: PLATEAU confirmation progress (module docstring's "Confirmation
    #: modes" note) for the SEPARATE "interval fully inside the rung past
    #: the peak hour" (``_is_locked``) structural condition -- kept apart
    #: from ``dead_confirm_observed_ns`` (the RISING-mode buffer) so the two
    #: never share progress (the two conditions are mutually exclusive per
    #: reading, but a position can oscillate between candidacies across
    #: readings). Shared between YES's rule-4 LOCKED and the NO leg's
    #: inside-rung-after-peak DEAD -- safe because a position's leg never
    #: changes mid-flight, so only one of ``_evaluate_yes``/``_evaluate_no``
    #: ever advances it for a given history.
    locked_confirm_progress: _PlateauProgress
    last_emitted_ts_ns: int | None

    EMPTY: ClassVar[MonitorHistory]


MonitorHistory.EMPTY = MonitorHistory(
    last_state=None,
    last_verdict=None,
    candidate_state=None,
    candidate_count=0,
    candidate_first_ts_ns=None,
    dead_confirm_observed_ns=(),
    locked_confirm_progress=_PlateauProgress.EMPTY,
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


def _fully_inside_rung(evidence: MonitorEvidence) -> bool:
    """Geometric-only twin of :func:`_is_locked`, without the hour gate."""
    if evidence.rung_low is None or evidence.rung_high is None:
        return False
    return (
        evidence.running_max_lower >= evidence.rung_low
        and evidence.running_max_upper <= evidence.rung_high
    )


def _evaluate_hysteresis(
    is_candidate: bool,
    history: MonitorHistory,
    ts_ns: int,
    *,
    toward_threatened_reason: str,
    toward_alive_reason: str,
) -> tuple[ThesisState, Verdict, tuple[str, ...], int, MonitorHistory]:
    """Shared ALIVE<->THREATENED symmetric hysteresis (module docstring
    rule 5): ``_THREATENED_CONFIRMATIONS`` CONSECUTIVE ``is_candidate``
    readings spanning >= ``_THREATENED_MIN_SPAN_NS`` flip the state; a
    single reading in the "wrong" direction resets any in-progress run.
    Driven by an arbitrary boolean signal -- the YES leg's ``p_hold`` drop,
    or the NO leg's "fully inside the rung before the peak hour" geometry
    (module docstring's leg semantics section) -- so both legs share one
    confirmation implementation.
    """
    currently_threatened = history.last_state is ThesisState.THREATENED
    relevant = (not currently_threatened and is_candidate) or (
        currently_threatened and not is_candidate
    )
    label = _TOWARD_THREATENED if not currently_threatened else _TOWARD_ALIVE

    if not relevant:
        new_history = dataclasses.replace(
            history,
            candidate_state=None,
            candidate_count=0,
            candidate_first_ts_ns=None,
        )
        state = ThesisState.THREATENED if currently_threatened else ThesisState.ALIVE
        verdict = Verdict.REDUCE_RECOMMENDED if currently_threatened else Verdict.HOLD
        return state, verdict, (), 0, new_history

    if history.candidate_state == label and history.candidate_first_ts_ns is not None:
        count = history.candidate_count + 1
        first_ts = history.candidate_first_ts_ns
    else:
        count = 1
        first_ts = ts_ns

    span_ns = ts_ns - first_ts
    flips = count >= _THREATENED_CONFIRMATIONS and span_ns >= _THREATENED_MIN_SPAN_NS

    if flips:
        state = ThesisState.ALIVE if currently_threatened else ThesisState.THREATENED
        new_history = dataclasses.replace(
            history,
            candidate_state=None,
            candidate_count=0,
            candidate_first_ts_ns=None,
        )
        return (
            state,
            (Verdict.REDUCE_RECOMMENDED if state is ThesisState.THREATENED else Verdict.HOLD),
            (),
            0,
            new_history,
        )

    state = ThesisState.THREATENED if currently_threatened else ThesisState.ALIVE
    verdict = Verdict.REDUCE_RECOMMENDED if currently_threatened else Verdict.HOLD
    reason = toward_alive_reason if label == _TOWARD_ALIVE else toward_threatened_reason
    new_history = dataclasses.replace(
        history,
        candidate_state=label,
        candidate_count=count,
        candidate_first_ts_ns=first_ts,
    )
    return state, verdict, (reason,), count, new_history


def _evaluate_threatened_alive(
    evidence: MonitorEvidence, history: MonitorHistory
) -> tuple[ThesisState, Verdict, tuple[str, ...], int, MonitorHistory]:
    """YES leg only (module docstring rule 5) -- UNCHANGED behaviour."""
    currently_threatened = history.last_state is ThesisState.THREATENED

    if evidence.p_hold_at_entry is None or evidence.p_hold_at_t is None:
        state = ThesisState.THREATENED if currently_threatened else ThesisState.ALIVE
        verdict = Verdict.REDUCE_RECOMMENDED if currently_threatened else Verdict.HOLD
        new_history = dataclasses.replace(
            history,
            candidate_state=None,
            candidate_count=0,
            candidate_first_ts_ns=None,
        )
        return state, verdict, ("p_hold_undefined",), 0, new_history

    drop = evidence.p_hold_at_entry - evidence.p_hold_at_t
    is_candidate = drop >= _P_HOLD_DROP_MARGIN
    return _evaluate_hysteresis(
        is_candidate,
        history,
        evidence.ts_ns,
        toward_threatened_reason="p_hold_drop_candidate",
        toward_alive_reason="p_hold_recovery_candidate",
    )


def _evaluate_no_leg_threat(
    evidence: MonitorEvidence, history: MonitorHistory
) -> tuple[ThesisState, Verdict, tuple[str, ...], int, MonitorHistory]:
    """NO leg's THREATENED-shaped case (module docstring's leg semantics
    section): the running-max interval sits fully inside the rung before
    the peak hour -- the high may still climb out and save the leg, so this
    is geometric-only and never consults ``p_hold``.
    """
    is_candidate = _fully_inside_rung(evidence) and evidence.hour_lst < _LOCKED_HOUR_LST
    return _evaluate_hysteresis(
        is_candidate,
        history,
        evidence.ts_ns,
        toward_threatened_reason="no_inside_rung",
        toward_alive_reason="no_leg_recovering",
    )


def _evaluate_yes(
    evidence: MonitorEvidence,
    history: MonitorHistory,
) -> tuple[MonitorDecision, MonitorHistory]:
    """YES leg (module docstring rules 2-5). Rule 2 (DEAD) stays RISING-mode,
    UNCHANGED. Rule 4 (LOCKED) is now PLATEAU-mode (2026-09-16 correction --
    previously mechanistic/immediate).
    """
    dead_qualifies = (
        evidence.rung_high is not None and evidence.running_max_lower > evidence.rung_high
    )
    dead_confirm_ns, dead_confirmed = _update_dead_confirmation(
        history.dead_confirm_observed_ns,
        _dead_confirm_key(evidence),
        qualifies=dead_qualifies,
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
            locked_confirm_progress=_PlateauProgress.EMPTY,
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
        new_history = dataclasses.replace(
            history,
            dead_confirm_observed_ns=dead_confirm_ns,
            locked_confirm_progress=_PlateauProgress.EMPTY,
        )
        decision = MonitorDecision(
            state=prev_state,
            verdict=prev_verdict,
            reason_codes=("dead_candidate",),
            confirmations=len(dead_confirm_ns),
            ts_ns=evidence.ts_ns,
        )
        return decision, new_history

    lock_qualifies = _is_locked(evidence)
    lock_progress, lock_confirmed = _update_plateau_confirmation(
        history.locked_confirm_progress,
        evidence.ts_ns,
        evidence.observed_at_ns,
        qualifies=lock_qualifies,
    )

    if lock_confirmed:
        new_history = dataclasses.replace(
            history,
            last_state=ThesisState.LOCKED_BY_OBSERVATION,
            last_verdict=Verdict.HOLD,
            candidate_state=None,
            candidate_count=0,
            candidate_first_ts_ns=None,
            dead_confirm_observed_ns=dead_confirm_ns,
            locked_confirm_progress=lock_progress,
        )
        decision = MonitorDecision(
            state=ThesisState.LOCKED_BY_OBSERVATION,
            verdict=Verdict.HOLD,
            reason_codes=("locked",),
            confirmations=lock_progress.qualifying_count,
            ts_ns=evidence.ts_ns,
        )
        return decision, new_history

    if lock_qualifies:
        prev_state = history.last_state if history.last_state is not None else ThesisState.ALIVE
        prev_verdict = history.last_verdict if history.last_verdict is not None else Verdict.HOLD
        new_history = dataclasses.replace(
            history,
            dead_confirm_observed_ns=dead_confirm_ns,
            locked_confirm_progress=lock_progress,
        )
        decision = MonitorDecision(
            state=prev_state,
            verdict=prev_verdict,
            reason_codes=("lock_candidate",),
            confirmations=lock_progress.qualifying_count,
            ts_ns=evidence.ts_ns,
        )
        return decision, new_history

    state, verdict, reason_codes, confirmations, ta_history = _evaluate_threatened_alive(
        evidence,
        history,
    )
    new_history = dataclasses.replace(
        ta_history,
        last_state=state,
        last_verdict=verdict,
        dead_confirm_observed_ns=dead_confirm_ns,
        locked_confirm_progress=_PlateauProgress.EMPTY,
    )
    decision = MonitorDecision(
        state=state,
        verdict=verdict,
        reason_codes=reason_codes,
        confirmations=confirmations,
        ts_ns=evidence.ts_ns,
    )
    return decision, new_history


def _evaluate_no(
    evidence: MonitorEvidence,
    history: MonitorHistory,
) -> tuple[MonitorDecision, MonitorHistory]:
    """NO leg (module docstring's leg semantics section): the two geometric
    facts YES uses for DEAD/LOCKED swap outcomes (win-lock stays RISING-mode,
    inside-rung-after-peak is PLATEAU-mode -- 2026-09-16 correction), and the
    pre-peak "inside the rung" geometry becomes THREATENED instead of running
    through YES's p_hold-driven hysteresis.
    """
    win_lock_qualifies = (
        evidence.rung_high is not None and evidence.running_max_lower > evidence.rung_high
    )
    win_lock_ns, win_lock_confirmed = _update_dead_confirmation(
        history.dead_confirm_observed_ns,
        _dead_confirm_key(evidence),
        qualifies=win_lock_qualifies,
    )

    if win_lock_confirmed:
        new_history = dataclasses.replace(
            history,
            last_state=ThesisState.LOCKED_BY_OBSERVATION,
            last_verdict=Verdict.HOLD,
            candidate_state=None,
            candidate_count=0,
            candidate_first_ts_ns=None,
            dead_confirm_observed_ns=win_lock_ns,
            locked_confirm_progress=_PlateauProgress.EMPTY,
        )
        decision = MonitorDecision(
            state=ThesisState.LOCKED_BY_OBSERVATION,
            verdict=Verdict.HOLD,
            reason_codes=("no_leg_win_locked",),
            confirmations=len(win_lock_ns),
            ts_ns=evidence.ts_ns,
        )
        return decision, new_history

    if win_lock_qualifies:
        prev_state = history.last_state if history.last_state is not None else ThesisState.ALIVE
        prev_verdict = history.last_verdict if history.last_verdict is not None else Verdict.HOLD
        new_history = dataclasses.replace(
            history,
            dead_confirm_observed_ns=win_lock_ns,
            locked_confirm_progress=_PlateauProgress.EMPTY,
        )
        decision = MonitorDecision(
            state=prev_state,
            verdict=prev_verdict,
            reason_codes=("dead_candidate",),
            confirmations=len(win_lock_ns),
            ts_ns=evidence.ts_ns,
        )
        return decision, new_history

    dead_lock_qualifies = _is_locked(evidence)
    dead_lock_progress, dead_lock_confirmed = _update_plateau_confirmation(
        history.locked_confirm_progress,
        evidence.ts_ns,
        evidence.observed_at_ns,
        qualifies=dead_lock_qualifies,
    )

    if dead_lock_confirmed:
        verdict = _dead_verdict(evidence)
        new_history = dataclasses.replace(
            history,
            last_state=ThesisState.DEAD_BY_OBSERVATION,
            last_verdict=verdict,
            candidate_state=None,
            candidate_count=0,
            candidate_first_ts_ns=None,
            dead_confirm_observed_ns=(),
            locked_confirm_progress=dead_lock_progress,
        )
        decision = MonitorDecision(
            state=ThesisState.DEAD_BY_OBSERVATION,
            verdict=verdict,
            reason_codes=("no_leg_inside_rung_after_peak",),
            confirmations=dead_lock_progress.qualifying_count,
            ts_ns=evidence.ts_ns,
        )
        return decision, new_history

    if dead_lock_qualifies:
        prev_state = history.last_state if history.last_state is not None else ThesisState.ALIVE
        prev_verdict = history.last_verdict if history.last_verdict is not None else Verdict.HOLD
        new_history = dataclasses.replace(
            history,
            dead_confirm_observed_ns=(),
            locked_confirm_progress=dead_lock_progress,
        )
        decision = MonitorDecision(
            state=prev_state,
            verdict=prev_verdict,
            reason_codes=("dead_candidate",),
            confirmations=dead_lock_progress.qualifying_count,
            ts_ns=evidence.ts_ns,
        )
        return decision, new_history

    state, verdict, reason_codes, confirmations, ta_history = _evaluate_no_leg_threat(
        evidence,
        history,
    )
    new_history = dataclasses.replace(
        ta_history,
        last_state=state,
        last_verdict=verdict,
        dead_confirm_observed_ns=(),
        locked_confirm_progress=_PlateauProgress.EMPTY,
    )
    decision = MonitorDecision(
        state=state,
        verdict=verdict,
        reason_codes=reason_codes,
        confirmations=confirmations,
        ts_ns=evidence.ts_ns,
    )
    return decision, new_history


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
    on what "stale" means. Dispatches on ``evidence.leg`` -- see the module
    docstring's leg semantics section for why NO cannot share YES's DEAD/
    LOCKED/THREATENED mapping.
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
            locked_confirm_progress=_PlateauProgress.EMPTY,
        )
        decision = MonitorDecision(
            state=ThesisState.UNKNOWN,
            verdict=Verdict.UNKNOWN,
            reason_codes=("stale_observation",),
            confirmations=0,
            ts_ns=evidence.ts_ns,
        )
        return decision, new_history

    if evidence.leg == "NO":
        return _evaluate_no(evidence, history)
    return _evaluate_yes(evidence, history)


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
