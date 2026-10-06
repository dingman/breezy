"""FQ evaluator: the C6 scorer plug-in and the pure forward-shadow e-process evaluation (F7b-core).

``FqEvaluator`` defines ONLY ``label`` and ``has_scorer`` (F7B-R7/R26): it stays a refusing plug-in
(``is_complete`` is false) and the inherited ``forward_shadow`` still raises ``PluginRefused``. The
evaluation itself is the pure module-level :func:`evaluate_e_process`, behind the module-level
guard chain :func:`check_forward_shadow_inputs`. The chain refuses every path in production because
``REGISTERED_FORWARD_SHADOW_SOURCES`` is empty until an F5 ruling registers a forward-only source
(E-25 rule 6b).

Evaluation rules:

* PASS needs ``min(e_a, e_b) >= 1/alpha_k`` at ``n >= earliest_look_n`` AND the calibration guard OK
  on the same settled day (F7B-R11). The guard is optional in the design; unpinned it reports
  ``INSUFFICIENT(guard_unpinned)`` and PASS is unreachable (fail closed).
* FAIL is the KILL test (``confidence_sequence``) at a look. The days are processed in order and the
  FIRST terminal event is final; a same-day PASS and KILL is FAIL (F7B-R12). A guard-blocked
  crossing is not terminal.
* ``INCONCLUSIVE(window_end_no_crossing)`` once ``last_settled_day >= window_end`` with no terminal
  event. Days after ``window_end`` are never processed.
* Backtest evidence is refused outright (F7B-R17); ``_cap_backtest_outcome`` (rule 8: a backtest can
  only reject) is the second line.
* ``bss_all_decisions`` needs ``market_baseline`` (not yet in ``analysis/stats``) and is reported as
  ``UNAVAILABLE(market_baseline_absent)``; the per-rung PIT has no pinned spec.
"""

from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, ClassVar, Final, NamedTuple

from breezy.analysis.autonomy.confidence_sequence import (
    BssResult,
    TakeScore,
    bss_on_takes,
    kill_bar,
    kill_crossed,
    kill_log_capitals,
)
from breezy.analysis.autonomy.eprocess import (
    EProcessDesign,
    GuardThresholds,
    TakeInput,
    build_day_stats,
    crossed,
    pass_bar,
    run_eprocess,
)
from breezy.analysis.autonomy.evidence_row import (
    EvidenceClass,
    EvidenceRefused,
    EvidenceRow,
    LoadedEvidence,
    StoreKind,
    require_loaded_evidence,
)
from breezy.analysis.brier_decomposition import bin_by_edges, murphy_decomposition
from breezy.analysis.labeling.fq_scorer import ForecastQuantileLadderScorer
from breezy.analysis.labeling.scoring_batch import ScoredBatch, require_scoring_batch
from breezy.analysis.stats.scoring_core import BOOTSTRAP_ITERATIONS, RELIABILITY_BUCKET_EDGES
from breezy.persistence.autonomy.plugin import PluginRefused, RefusingPlugin
from breezy.persistence.autonomy.verdict import VerdictOutcome

__all__ = [
    "BSS_ALL_DECISIONS_UNAVAILABLE",
    "PIT_PER_RUNG_UNAVAILABLE",
    "REGISTERED_FORWARD_SHADOW_SOURCES",
    "ForwardShadowRefused",
    "FqEvaluator",
    "FqShadowEvaluation",
    "check_forward_shadow_inputs",
    "evaluate_e_process",
]

BSS_ALL_DECISIONS_UNAVAILABLE: Final = "UNAVAILABLE(market_baseline_absent)"
PIT_PER_RUNG_UNAVAILABLE: Final = "UNAVAILABLE(pit_spec_absent)"
GUARD_UNPINNED: Final = "INSUFFICIENT(guard_unpinned)"
GUARD_NOT_EVALUATED: Final = "NOT_EVALUATED"
GUARD_OK: Final = "OK"
_DEFAULT_BIN_EDGES: Final = (0.0, *RELIABILITY_BUCKET_EDGES, 1.0)
_MIN_VARIANCE: Final = 1e-12

#: E-25 rule 6b: the forward-only sources the evaluator may read. EMPTY until an F5 ruling
#: registers one, so no production input yields a verdict input.
REGISTERED_FORWARD_SHADOW_SOURCES: Final[frozenset[StoreKind]] = frozenset()


class ForwardShadowRefused(PluginRefused):
    """A named refusal of forward-shadow evidence; ``reason`` is the machine-checkable cause."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _require_shadow(tape: object) -> LoadedEvidence:
    try:
        loaded = require_loaded_evidence(tape)
    except EvidenceRefused as exc:
        raise ForwardShadowRefused("evidence_not_loaded") from exc
    if loaded.evidence_class is not EvidenceClass.SHADOW:
        raise ForwardShadowRefused("store_kind_not_accepted")
    return loaded


def check_forward_shadow_inputs(tape: object) -> LoadedEvidence:
    """The guard chain: sealed evidence, shadow only, from a registered forward-only source."""
    loaded = _require_shadow(tape)
    if loaded.store_kind not in REGISTERED_FORWARD_SHADOW_SOURCES:
        raise ForwardShadowRefused("no_registered_forward_shadow_source")
    return loaded


def _cap_backtest_outcome(outcome: VerdictOutcome, evidence_class: EvidenceClass) -> VerdictOutcome:
    """Rule 8: a backtest can only reject, so a PASS is capped to UNDERPOWERED."""
    if evidence_class is EvidenceClass.BACKTEST and outcome is VerdictOutcome.PASS:
        return VerdictOutcome.UNDERPOWERED
    return outcome


class _Scored(NamedTuple):
    day: dt.date
    side: str
    p: float
    h: int
    raw_ask: float
    be: float


@dataclass(frozen=True, slots=True)
class _GuardResult:
    status: str
    z: float | None
    slope: float | None


def _spiegelhalter_z(scored: Sequence[_Scored]) -> float | None:
    den = math.sqrt(sum((1 - 2 * s.p) ** 2 * s.p * (1 - s.p) for s in scored))
    if den <= 0.0:
        return None
    return sum((s.h - s.p) * (1 - 2 * s.p) for s in scored) / den


def _reliability_slope(scored: Sequence[_Scored], edges: Sequence[float]) -> float | None:
    key = bin_by_edges(edges)
    bins: dict[Any, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    for s in scored:
        cell = bins[key(s.p)]
        cell[0] += 1.0
        cell[1] += s.p
        cell[2] += s.h
    if len(bins) < 2:
        return None
    n = sum(c[0] for c in bins.values())
    mean_p = sum(c[1] for c in bins.values()) / n
    mean_y = sum(c[2] for c in bins.values()) / n
    sxx = sum(c[0] * (c[1] / c[0] - mean_p) ** 2 for c in bins.values())
    sxy = sum(c[0] * (c[1] / c[0] - mean_p) * (c[2] / c[0] - mean_y) for c in bins.values())
    return None if sxx <= _MIN_VARIANCE else sxy / sxx


def _group_status(scored: Sequence[_Scored], th: GuardThresholds) -> _GuardResult:
    z = _spiegelhalter_z(scored)
    slope = _reliability_slope(scored, th.bin_edges)
    if len(scored) < th.n_guard_min:
        return _GuardResult("INSUFFICIENT(n_guard_min)", z, slope)
    if z is None:
        return _GuardResult("INSUFFICIENT(spiegelhalter_undefined)", z, slope)
    if abs(z) > th.spiegelhalter_abs_z_max:
        return _GuardResult("FAIL(spiegelhalter_z)", z, slope)
    if slope is None:
        return _GuardResult("INSUFFICIENT(slope_undefined)", z, slope)
    low, high = th.slope_band
    if not low <= slope <= high:
        return _GuardResult("FAIL(reliability_slope)", z, slope)
    return _GuardResult(GUARD_OK, z, slope)


def _guard(scored: Sequence[_Scored], th: GuardThresholds | None) -> _GuardResult:
    """The calibration guard on the takes settled so far (F7B-R11, R18)."""
    if th is None:
        return _GuardResult(GUARD_UNPINNED, _spiegelhalter_z(scored), None)
    if th.pooling == "pooled":
        return _group_status(scored, th)
    results = [
        _group_status([s for s in scored if s.side == side], th)
        for side in sorted({s.side for s in scored})
    ]
    bad = [r for r in results if r.status != GUARD_OK]
    return bad[0] if bad else _GuardResult(GUARD_OK, _spiegelhalter_z(scored), None)


def _guard_reason(status: str) -> str:
    if status == GUARD_UNPINNED:
        return "guard_unpinned"
    return "guard_failing" if status.startswith("FAIL") else "guard_insufficient"


@dataclass(frozen=True, slots=True)
class FqShadowEvaluation:
    """The evaluation of one FS e-process window. Not a verdict: nothing here writes one."""

    outcome: VerdictOutcome
    reason: str | None
    terminal_day: dt.date | None
    days: int
    n_cum: int
    eprocess_uncounted_takes: int
    log_e_a: float
    log_e_b: float
    pass_crossing_n: int | None
    kill_n: int | None
    guard_status: str
    spiegelhalter_z: float | None
    reliability_slope: float | None
    murphy_reliability: float | None
    net_pnl_per_day: float | None
    bss_on_takes: BssResult | None
    bss_all_decisions: str = BSS_ALL_DECISIONS_UNAVAILABLE
    pit_per_rung: str = PIT_PER_RUNG_UNAVAILABLE


def _to_take(row: EvidenceRow) -> TakeInput:
    return TakeInput(
        climate_day=row.climate_day,
        decision_ts_ns=row.decision_ts_ns,
        station=row.station,
        rung_id=row.rung_id,
        side=row.side,
        be=float(row.be),
        raw_ask=float(row.raw_ask),
        p_model=float(row.p_model),
        h=row.h,
        void=row.void,
    )


def _scored_by_day(rows: Sequence[EvidenceRow]) -> dict[dt.date, list[_Scored]]:
    out: dict[dt.date, list[_Scored]] = defaultdict(list)
    for r in rows:
        if r.void or r.h is None:
            continue
        out[r.climate_day].append(
            _Scored(r.climate_day, r.side, float(r.p_model), r.h, float(r.raw_ask), float(r.be))
        )
    return out


def evaluate_e_process(
    loaded: LoadedEvidence,
    *,
    design: EProcessDesign,
    alpha_k: Decimal,
    alpha_kill: Decimal,
    first_day: dt.date,
    window_end: dt.date,
    last_settled_day: dt.date,
    bss_iterations: int = BOOTSTRAP_ITERATIONS,
) -> FqShadowEvaluation:
    """Walk the settled days of one window and return the first terminal event, else the state."""
    evidence = _require_shadow(loaded)
    end_day = min(last_settled_day, window_end)
    stats = build_day_stats(
        [_to_take(r) for r in evidence.rows],
        covered_days=evidence.covered_days,
        first_day=first_day,
        last_settled_day=end_day,
        design=design,
    )
    states = run_eprocess(stats, design)
    kill_rows = kill_log_capitals([s.y for s in stats], x_max=design.x_max)
    pass_b, kill_b = pass_bar(alpha_k), kill_bar(alpha_kill)
    by_day = _scored_by_day(evidence.rows)

    scored: list[_Scored] = []
    pass_crossing_n: int | None = None
    kill_n: int | None = None
    last_guard = _GuardResult(
        GUARD_UNPINNED if design.guard is None else GUARD_NOT_EVALUATED, None, None
    )
    terminal: int | None = None
    outcome: VerdictOutcome | None = None
    for i, state in enumerate(states):
        scored.extend(by_day.get(state.climate_day, ()))
        look = state.n_cum >= design.earliest_look_n
        kill_hit = look and kill_crossed(kill_rows[i], kill_b)
        cross = look and crossed(state.log_min, pass_b)
        pass_hit = False
        if cross:
            pass_crossing_n = state.n_cum if pass_crossing_n is None else pass_crossing_n
            last_guard = _guard(scored, design.guard)
            pass_hit = last_guard.status == GUARD_OK
        if kill_hit:  # F7B-R12: a same-day PASS and KILL is FAIL
            terminal, outcome, kill_n = i, VerdictOutcome.FAIL, state.n_cum
            break
        if pass_hit:
            terminal, outcome = i, VerdictOutcome.PASS
            break

    used = states if terminal is None else states[: terminal + 1]
    reason: str | None = None
    if outcome is None:
        outcome, reason = _non_terminal(
            used[-1].n_cum if used else 0,
            design.earliest_look_n,
            window_passed=last_settled_day >= window_end,
            crossed_ever=pass_crossing_n is not None,
            guard_status=last_guard.status,
        )
    outcome = _cap_backtest_outcome(outcome, evidence.evidence_class)
    return _build(
        used,
        outcome,
        reason,
        terminal,
        pass_crossing_n,
        kill_n,
        scored,
        last_guard,
        design,
        evidence,
        bss_iterations,
    )


def _non_terminal(
    n_cum: int,
    earliest_look_n: int,
    *,
    window_passed: bool,
    crossed_ever: bool,
    guard_status: str,
) -> tuple[VerdictOutcome, str]:
    if window_passed:
        reason = "window_end_guard_blocked" if crossed_ever else "window_end_no_crossing"
        return VerdictOutcome.INCONCLUSIVE, reason
    if crossed_ever:
        return VerdictOutcome.UNDERPOWERED, _guard_reason(guard_status)
    if n_cum < earliest_look_n:
        return VerdictOutcome.UNDERPOWERED, "below_earliest_look_n"
    return VerdictOutcome.UNDERPOWERED, "no_crossing_yet"


def _build(
    used: Sequence[Any],
    outcome: VerdictOutcome,
    reason: str | None,
    terminal: int | None,
    pass_crossing_n: int | None,
    kill_n: int | None,
    scored: Sequence[_Scored],
    guard: _GuardResult,
    design: EProcessDesign,
    evidence: LoadedEvidence,
    bss_iterations: int,
) -> FqShadowEvaluation:
    last = used[-1] if used else None
    edges = design.guard.bin_edges if design.guard else _DEFAULT_BIN_EDGES
    murphy = (
        murphy_decomposition(
            [s.p for s in scored], [bool(s.h) for s in scored], bin_by_edges(edges)
        ).reliability
        if scored
        else None
    )
    pnl = sum(s.h - s.be for s in scored) / len(used) if used else None
    bss = (
        bss_on_takes(
            [TakeScore(s.day, s.raw_ask, s.p, s.h) for s in scored], iterations=bss_iterations
        )
        if scored
        else None
    )
    return FqShadowEvaluation(
        outcome=outcome,
        reason=reason,
        terminal_day=None if terminal is None else used[terminal].climate_day,
        days=len(used),
        n_cum=last.n_cum if last else 0,
        eprocess_uncounted_takes=last.uncounted_cum if last else 0,
        log_e_a=last.log_e_a if last else 0.0,
        log_e_b=last.log_e_b if last else 0.0,
        pass_crossing_n=pass_crossing_n,
        kill_n=kill_n,
        guard_status=guard.status,
        spiegelhalter_z=_spiegelhalter_z(scored) if scored else None,
        reliability_slope=_reliability_slope(scored, edges) if scored else None,
        murphy_reliability=murphy,
        net_pnl_per_day=pnl,
        bss_on_takes=bss,
    )


class FqEvaluator(RefusingPlugin):
    """FQ: a real ``label``; every other member refuses and the plug-in stays incomplete."""

    has_scorer: ClassVar[bool] = True

    def label(self, capture_day: Any, exec_fills: Any, settlements: Any) -> ScoredBatch:
        batch = require_scoring_batch(exec_fills)
        scorer = ForecastQuantileLadderScorer(now_ns=batch.now_ns, prior=batch.prior)
        result = scorer.label_with_alerts(capture_day, list(batch.inputs), settlements)
        return ScoredBatch(
            rows=result.rows,
            p_null_count=result.p_null_count,
            non_c1_post_epoch_count=result.non_c1_post_epoch_count,
        )
