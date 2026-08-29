"""Forecast-revision / momentum trading strategy.

Public surface: :class:`ForecastRevisionConfig` and
:class:`ForecastRevisionStrategy`. See ``strategy.py`` for the module docstring
covering the data seam, the forecast-injection requirement, the removed
settlement clock, and what changed from the operator-supplied bundle this
package replaces -- in particular the push-to-pull adaptation of revision
detection, documented in ``decision.py``.
"""

from __future__ import annotations

from breezy.strategy.forecast_revision.config import ForecastRevisionConfig
from breezy.strategy.forecast_revision.strategy import ForecastRevisionStrategy

__all__ = ["ForecastRevisionConfig", "ForecastRevisionStrategy"]
