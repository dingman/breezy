"""Calibrated-probability mean-reversion trading strategy.

Public surface: :class:`CalibrationMeanReversionConfig` and
:class:`CalibrationMeanReversionStrategy`. See ``strategy.py`` for the module
docstring covering the data seam, the forecast-injection requirement, the
removed settlement clock, and what changed from the operator-supplied bundle
this package replaces.

The offline calibration helpers that shipped in the same bundle section
(``ForecastErrorRecord`` / ``fit_error_model``) are NOT re-exported here: they
fit a ``ForecastErrorModel`` from realized outcomes and must run on a train
window that ends before any backtest start date. See
``breezy.strategy.weather_common.calibration``.
"""

from __future__ import annotations

from breezy.strategy.calibration_mean_reversion.config import CalibrationMeanReversionConfig
from breezy.strategy.calibration_mean_reversion.strategy import CalibrationMeanReversionStrategy

__all__ = ["CalibrationMeanReversionConfig", "CalibrationMeanReversionStrategy"]
