"""The offline-side C6 plug-in registry (ARCH-0 AC 26).

Exactly the four composition kinds (``family_manifest._COMPOSITION_KINDS``), each bound to
``RefusingPlugin`` until the kind's owner lands a real plug-in in the same change that admits
the kind to ``LIVE_GATE_ROUTED_KINDS``.
"""

from types import MappingProxyType
from typing import Final

from breezy.persistence.autonomy.plugin import RefusingPlugin

OFFLINE_PLUGINS: Final[MappingProxyType[str, RefusingPlugin]] = MappingProxyType(
    {
        "current_rung_hold": RefusingPlugin(),
        "continuous_rung_hold": RefusingPlugin(),
        "forecast_ladder": RefusingPlugin(),
        "forecast_quantile_ladder": RefusingPlugin(),
    }
)
