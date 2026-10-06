"""The offline-side C6 plug-in registry (ARCH-0 AC 26; AUT-2 FQ-R41).

Exactly the four composition kinds (``family_manifest._COMPOSITION_KINDS``). Three of them carry a
real C6 ``Scorer`` (ARCH C6, AUTONOMY_ARCHITECTURE.md:756-760: the CRH kinds keep a real Scorer even
when retired): ``forecast_quantile_ladder`` the FQ scorer and the two CRH kinds the legacy CRH
scorer. Each of those plug-ins is a ``RefusingPlugin`` subclass that overrides ``label`` ONLY: it
stays ``refusing`` (so ``is_complete`` is false), and the capture, evaluator, detector and refit
members, which is where a family is minted and composed, still raise ``PluginRefused``.
``forecast_ladder`` has no fills and no scorer: it stays the plain ``RefusingPlugin``.

``label`` takes a :class:`ScoringBatch` in the ``exec_fills`` position (the C6 signature has no
clock or prior-run argument) and returns a :class:`ScoredBatch`. Building the per-fill inputs (C1
attribution, the legacy trial join) is the label run's planner, not the scorer seam.
"""

from types import MappingProxyType
from typing import Any, ClassVar, Final

from breezy.analysis.labeling.fq_scorer import ForecastQuantileLadderScorer
from breezy.analysis.labeling.legacy_crh_scorer import LegacyCrhScorer
from breezy.analysis.labeling.scoring_batch import ScoredBatch, ScoringBatch
from breezy.persistence.autonomy.plugin import RefusingPlugin

__all__ = [
    "OFFLINE_PLUGINS",
    "ContinuousRungHoldOfflinePlugin",
    "CurrentRungHoldOfflinePlugin",
    "FqOfflinePlugin",
]


def _batch(exec_fills: Any) -> ScoringBatch:
    if not isinstance(exec_fills, ScoringBatch):
        raise TypeError("label() takes a ScoringBatch in the exec_fills position")
    return exec_fills


class FqOfflinePlugin(RefusingPlugin):
    """FQ: a real ``label``; every other member refuses and the plug-in stays incomplete."""

    has_scorer: ClassVar[bool] = True

    def label(self, capture_day: Any, exec_fills: Any, settlements: Any) -> ScoredBatch:
        batch = _batch(exec_fills)
        scorer = ForecastQuantileLadderScorer(now_ns=batch.now_ns, prior=batch.prior)
        result = scorer.label_with_alerts(capture_day, list(batch.inputs), settlements)
        return ScoredBatch(
            rows=result.rows,
            p_null_count=result.p_null_count,
            non_c1_post_epoch_count=result.non_c1_post_epoch_count,
        )


class _LegacyCrhOfflinePlugin(RefusingPlugin):
    """A CRH kind keeps a real Scorer (ARCH C6): the legacy CRH scorer, which labels every fill
    ``unattributed`` and never admissible."""

    has_scorer: ClassVar[bool] = True

    def label(self, capture_day: Any, exec_fills: Any, settlements: Any) -> ScoredBatch:
        batch = _batch(exec_fills)
        scorer = LegacyCrhScorer(now_ns=batch.now_ns, prior=batch.prior)
        result = scorer.label_with_counts(capture_day, list(batch.inputs), settlements)
        return ScoredBatch(rows=result.rows, legacy_sell_rows=result.legacy_sell_rows)


class CurrentRungHoldOfflinePlugin(_LegacyCrhOfflinePlugin):
    """``current_rung_hold``."""


class ContinuousRungHoldOfflinePlugin(_LegacyCrhOfflinePlugin):
    """``continuous_rung_hold``."""


OFFLINE_PLUGINS: Final[MappingProxyType[str, RefusingPlugin]] = MappingProxyType(
    {
        "current_rung_hold": CurrentRungHoldOfflinePlugin(),
        "continuous_rung_hold": ContinuousRungHoldOfflinePlugin(),
        "forecast_ladder": RefusingPlugin(),
        "forecast_quantile_ladder": FqOfflinePlugin(),
    }
)
