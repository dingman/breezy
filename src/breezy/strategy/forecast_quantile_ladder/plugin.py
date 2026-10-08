"""FQ's C6 node plug-in entry (plan r12 section 3.1; ARCH C6).

``FqNodePlugin`` is the full plug-in for ``forecast_quantile_ladder``: it declares ``refusing``
False and carries the ``CaptureAdapter`` AUT-1 owns. The other members belong to other plans
(AUT-2 labels, AUT-4 evaluators, AUT-3 refit, AUT-6 detectors) and refuse until those plans land
them.

LIBRARY ONLY in WP2: it is built per family from an adapter (the adapter holds the family identity),
and it is NOT registered in ``NODE_PLUGINS``, which still binds every kind to ``RefusingPlugin``.
Registering it is the change that admits the kind (ARCH C6), which WP7/WP8 make.
"""

from typing import Any, ClassVar, Final

from breezy.persistence.autonomy.detector_catalog import CATALOG
from breezy.persistence.autonomy.plugin import Detector, PluginRefused
from breezy.strategy.forecast_quantile_ladder.capture_adapter import (
    CaptureContext,
    FqCaptureAdapter,
)
from breezy.strategy.forecast_quantile_ladder.decision import Decision

__all__ = ["FQ_COMPOSITION_KIND", "FqNodePlugin", "build_fq_node_plugin"]

FQ_COMPOSITION_KIND: Final[str] = "forecast_quantile_ladder"


#: The NODE_LOCAL ids the catalogue declares: the only detectors a composition may hand the plug-in.
_NODE_LOCAL_IDS: Final[frozenset[str]] = frozenset(
    row.id for row in CATALOG if row.kind == "NODE_LOCAL"
)


def _not_provided(member: str) -> PluginRefused:
    return PluginRefused(f"{FQ_COMPOSITION_KIND} does not yet provide {member} (another plan's)")


class FqNodePlugin:
    refusing: ClassVar[bool] = False

    def __init__(
        self,
        capture_adapter: FqCaptureAdapter,
        node_detectors: tuple[Detector, ...] | None = None,
    ) -> None:
        self._capture_adapter = capture_adapter
        self._node_detectors = _checked_node_detectors(node_detectors)

    @property
    def capture_adapter(self) -> FqCaptureAdapter:
        return self._capture_adapter

    def decision_record(self, decision: Decision, ctx: CaptureContext) -> Any:
        return self._capture_adapter.decision_record(decision, ctx)

    def order_tags(self, decision_id: str) -> tuple[str, ...]:
        return self._capture_adapter.order_tags(decision_id)

    def label(self, capture_day: Any, exec_fills: Any, settlements: Any) -> Any:
        raise _not_provided("label")

    def offline(self, candidate: Any, champion: Any) -> Any:
        raise _not_provided("offline")

    def forward_shadow(self, candidate: Any, champion: Any, tape: Any) -> Any:
        raise _not_provided("forward_shadow")

    def live(self, labels: Any) -> Any:
        raise _not_provided("live")

    @property
    def detectors(self) -> tuple[Detector, ...]:
        """The NODE_LOCAL detectors composition handed in (AUT-6); refuses until it does.

        VERDICT detectors are evaluated by the AUT-6 producers from the catalogue, not here.
        """
        if self._node_detectors is None:
            raise _not_provided("detectors")
        return self._node_detectors

    def refit(self, windows: Any) -> Any:
        raise _not_provided("refit")


def _checked_node_detectors(
    detectors: tuple[Detector, ...] | None,
) -> tuple[Detector, ...] | None:
    if detectors is None:
        return None
    seen: set[str] = set()
    for detector in detectors:
        if detector.id not in _NODE_LOCAL_IDS:
            raise PluginRefused(f"{detector.id} is not a catalogued NODE_LOCAL detector")
        if detector.id in seen:
            raise PluginRefused(f"duplicate detector {detector.id}")
        seen.add(detector.id)
    return detectors


def build_fq_node_plugin(
    capture_adapter: FqCaptureAdapter, node_detectors: tuple[Detector, ...] | None = None
) -> FqNodePlugin:
    return FqNodePlugin(capture_adapter, node_detectors)
