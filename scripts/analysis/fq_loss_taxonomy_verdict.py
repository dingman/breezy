"""TE-2 loss taxonomy: verdict rules, downgrade rule, footer (pure). Plan section 2."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from scripts.analysis.fq_loss_taxonomy_stats import Status

MATERIAL_DELTA_P: Final = 0.01
POWER_FLOOR: Final = 0.8


class VerdictLabel(StrEnum):
    FIXABLE_DEFECT = "FIXABLE_DEFECT"
    MODEL_LIMITATION = "MODEL_LIMITATION"
    MODEL_MISCALIBRATED_UNATTRIBUTED = "MODEL_MISCALIBRATED_UNATTRIBUTED"
    VARIANCE = "VARIANCE"
    INCONCLUSIVE = "INCONCLUSIVE"


class Sublabel(StrEnum):
    ARTEFACT = "ARTEFACT"
    SOURCE = "SOURCE"
    ARTEFACT_AND_SOURCE = "ARTEFACT+SOURCE"


class Qualifier(StrEnum):
    WEAK = "weak"
    SINGLE_CLUSTER_DRIVEN = "single-cluster-driven"
    SECONDARIES_NOT_TESTABLE = "secondaries NOT-TESTABLE"


@dataclass(frozen=True)
class HypothesisOutcome:
    name: str
    status: Status
    rejects: bool
    p_value: float | None = None
    power: float | None = None


@dataclass(frozen=True)
class VerdictInputs:
    t_win: HypothesisOutcome
    loo_rejects: bool
    t_loc: HypothesisOutcome
    t_spread: HypothesisOutcome
    t_art: HypothesisOutcome
    has_k4: bool = False
    material_k1a: bool = False
    k3_present: bool = False
    k1b_present: bool = False


@dataclass(frozen=True)
class Verdict:
    label: VerdictLabel
    sublabel: Sublabel | None
    qualifiers: tuple[Qualifier, ...]
    reason: str | None
    notes: tuple[str, ...]


@dataclass(frozen=True)
class DowngradeResult:
    decisions: Mapping[str, bool]
    range_notes: tuple[str, ...]
    scope_sensitive: tuple[str, ...]


@dataclass(frozen=True)
class TieReevaluation:
    downgraded: tuple[str, ...]
    variance_eligible: Mapping[str, bool]


_RANK: Final[Mapping[str, int]] = {"NOT-TESTABLE": 0, "TESTABLE-CONDITIONAL": 1, "TESTABLE": 2}
_FOOTER_ROUTES: Final = (
    "T1 (M1-v3 CONFIRM, read on or after 12-07), T2 (new family and prereg), "
    "T3 (new US source, F13), per RULING_FQ-v2-NO-TRADE_2026-10-08."
)


def is_material_k1a(delta_p: float, flips_decision: bool) -> bool:
    """Material iff it flips the take/no-take decision or |delta p-hat| > 0.01."""
    return flips_decision or abs(delta_p) > MATERIAL_DELTA_P


def _valid_rejection(outcome: HypothesisOutcome, other_holm: HypothesisOutcome | None) -> bool:
    """A rejection that stands: TESTABLE, or CONDITIONAL after the other Holm member rejected at
    step 1 (TESTABLE and rejecting). NOT-TESTABLE never qualifies."""
    if not outcome.rejects:
        return False
    if outcome.status == "TESTABLE":
        return True
    return (
        outcome.status == "TESTABLE-CONDITIONAL"
        and other_holm is not None
        and other_holm.status == "TESTABLE"
        and other_holm.rejects
    )


def _statistical_label(inputs: VerdictInputs) -> Verdict:
    """Rules 2-5, ignoring the K flags (rule 1 is applied by the caller)."""
    notes: list[str] = []
    if inputs.t_loc.rejects:
        notes.append("T-LOC rejection is INDICATIVE only and never qualifies a label")
    art_ok = _valid_rejection(inputs.t_art, None)
    spread_ok = _valid_rejection(inputs.t_spread, inputs.t_loc)
    if art_ok or spread_ok:
        sub = (
            Sublabel.ARTEFACT_AND_SOURCE
            if art_ok and spread_ok
            else Sublabel.ARTEFACT
            if art_ok
            else Sublabel.SOURCE
        )
        return Verdict(VerdictLabel.MODEL_LIMITATION, sub, (), None, tuple(notes))
    secondaries = (inputs.t_spread, inputs.t_art)
    if inputs.t_win.rejects:
        qualifiers = []
        if not inputs.loo_rejects:
            qualifiers.append(Qualifier.SINGLE_CLUSTER_DRIVEN)
        if all(s.status == "NOT-TESTABLE" for s in secondaries):
            qualifiers.append(Qualifier.SECONDARIES_NOT_TESTABLE)
        label = VerdictLabel.MODEL_MISCALIBRATED_UNATTRIBUTED
        return Verdict(label, None, tuple(qualifiers), None, tuple(notes))
    return _variance_or_inconclusive(inputs, secondaries, notes)


def _variance_or_inconclusive(
    inputs: VerdictInputs, secondaries: tuple[HypothesisOutcome, ...], notes: list[str]
) -> Verdict:
    reasons: list[str] = []
    win = inputs.t_win
    if inputs.loo_rejects:
        reasons.append(
            "leave-one-out rejects while the full-sample T-WIN does not (blocks VARIANCE)"
        )
    if win.status != "TESTABLE":
        reasons.append(f"T-WIN is {win.status}")
    elif win.power is None or win.power < POWER_FLOOR:
        reasons.append(f"T-WIN cluster power {win.power} is below {POWER_FLOOR}")
    solid = [s for s in secondaries if s.status == "TESTABLE"]
    if not solid:
        reasons.append("no unconditionally TESTABLE secondary (T-SPREAD, T-ART)")
    if reasons:
        return Verdict(VerdictLabel.INCONCLUSIVE, None, (), "; ".join(reasons), tuple(notes))
    weak = any(s.power is None or s.power < POWER_FLOOR for s in solid)
    qualifiers = (Qualifier.WEAK,) if weak else ()
    return Verdict(VerdictLabel.VARIANCE, None, qualifiers, None, tuple(notes))


def decide_verdict(inputs: VerdictInputs) -> Verdict:
    """The deterministic verdict, precedence FIXABLE, MODEL_LIMITATION, MISCALIBRATED, VARIANCE,
    INCONCLUSIVE. K3, K1b and an indicative T-LOC rejection never produce FIXABLE."""
    statistical = _statistical_label(inputs)
    if inputs.has_k4 or inputs.material_k1a:
        note = f"statistical label alongside: {statistical.label.value}"
        return Verdict(VerdictLabel.FIXABLE_DEFECT, None, (), None, (note, *statistical.notes))
    return statistical


def apply_downgrade(
    cluster_level: Mapping[str, bool],
    station_day_level: Mapping[str, bool],
    six_cluster_sensitivity: Mapping[str, bool],
) -> DowngradeResult:
    """The cluster-level decision stands; a differing station-day decision is a reported range
    and a differing 10-06-excluded decision is labelled scope-sensitive."""
    ranges = tuple(
        f"{name}: station-day level {station_day_level[name]} differs from cluster level "
        f"{decision}; the verdict uses the cluster level"
        for name, decision in cluster_level.items()
        if name in station_day_level and station_day_level[name] != decision
    )
    scope = tuple(
        name
        for name, decision in cluster_level.items()
        if name in six_cluster_sensitivity and six_cluster_sensitivity[name] != decision
    )
    return DowngradeResult(dict(cluster_level), ranges, scope)


def render_footer(n_station_days: int, n_clusters: int) -> str:
    return "\n".join(
        (
            (
                f"diagnostic, post-hoc, n = {n_station_days} station-days in "
                f"{n_clusters} clusters, non-confirmatory"
            ),
            f"This verdict is NOT permission to re-arm. Re-open routes are {_FOOTER_ROUTES}",
            "VARIANCE does not imply positive EV.",
        )
    )


def report_phrase(outcome: HypothesisOutcome) -> str:
    """NOT-TESTABLE and CONDITIONAL are reported as such, never as "did not reject"."""
    p = "n/a" if outcome.p_value is None else f"{outcome.p_value:.4g}"
    if outcome.status == "NOT-TESTABLE":
        return (
            f"{outcome.name}: NOT-TESTABLE (minimum attainable p exceeds alpha; not a null result)"
        )
    if outcome.status == "TESTABLE-CONDITIONAL" and not outcome.rejects:
        return (
            f"{outcome.name}: TESTABLE-CONDITIONAL (can reject only at a later Holm step), p = {p}"
        )
    verb = "rejected" if outcome.rejects else "did not reject"
    return f"{outcome.name}: {verb} (p = {p}, {outcome.status})"


def reevaluate_after_ties(
    before: Mapping[str, Status], after: Mapping[str, Status]
) -> TieReevaluation:
    """A test that drops to a weaker status is reported so; only TESTABLE may feed VARIANCE."""
    rank_after = {name: _RANK[after.get(name, "NOT-TESTABLE")] for name in before}
    downgraded = tuple(name for name in before if rank_after[name] < _RANK[before[name]])
    eligible = {name: rank_after[name] == _RANK["TESTABLE"] for name in before}
    return TieReevaluation(downgraded, eligible)
