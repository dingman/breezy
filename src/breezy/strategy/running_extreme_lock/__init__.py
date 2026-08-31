"""Running-extreme open-tail lock trading strategy.

Public surface: :class:`RunningExtremeLockConfig` and
:class:`RunningExtremeLockStrategy`. See ``strategy.py`` for the module
docstring covering the data seam, the v1 open-tail-only scope, and the
observation-freshness wiring contract this strategy is bound by.
"""

from __future__ import annotations

from breezy.strategy.running_extreme_lock.config import RunningExtremeLockConfig
from breezy.strategy.running_extreme_lock.strategy import RunningExtremeLockStrategy

__all__ = ["RunningExtremeLockConfig", "RunningExtremeLockStrategy"]
