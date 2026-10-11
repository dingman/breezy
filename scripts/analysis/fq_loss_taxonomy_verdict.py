"""TE-2 loss taxonomy: verdict rules, downgrade rule, footer (pure). WP0 stub."""

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


def is_material_k1a(delta_p: float, flips_decision: bool) -> bool:
    raise NotImplementedError


def decide_verdict(inputs: VerdictInputs) -> Verdict:
    raise NotImplementedError


def apply_downgrade(
    cluster_level: Mapping[str, bool],
    station_day_level: Mapping[str, bool],
    six_cluster_sensitivity: Mapping[str, bool],
) -> DowngradeResult:
    raise NotImplementedError


def render_footer(n_station_days: int, n_clusters: int) -> str:
    raise NotImplementedError


def report_phrase(outcome: HypothesisOutcome) -> str:
    raise NotImplementedError


def reevaluate_after_ties(
    before: Mapping[str, Status], after: Mapping[str, Status]
) -> TieReevaluation:
    raise NotImplementedError
