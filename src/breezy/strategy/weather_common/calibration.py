"""Offline fitting of a :class:`ForecastErrorModel` from realized outcomes.

Carried over from the ``calibration_mean_reversion.py`` section of the
operator's bundle. It lives in ``weather_common`` rather than inside the
calibration strategy package because it is plain Python with no Nautilus object
in scope, and because any weather strategy may consume a fitted model.

LOOKAHEAD WARNING -- THIS IS THE WHOLE POINT OF "OFFLINE"
---------------------------------------------------------
``ForecastErrorRecord.realized_high_f`` is the official climate observation,
which is only knowable AFTER the day it describes has settled. Fitting a model
on records that overlap the evaluation window leaks the answer into the
predictor. :func:`fit_error_model` must therefore be called on a train window
that ENDS BEFORE the backtest start date, and the resulting model must be
treated as frozen for the duration of the run. Nothing in this module enforces
that -- it cannot, because it never sees the run -- so it is the caller's
obligation. Do not call it from inside a strategy's event handlers.

One dead statement from the bundle is not reproduced: it constructed a
``WeatherProbabilityEngine(model)`` into a local named ``helper`` and then
discarded it with ``_ = helper`` and a comment saying it documented which
engine consumes the model. It had no effect on the returned model. The comment
survives as this paragraph.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from breezy.strategy.weather_common.probability import ForecastErrorModel

__all__ = ["ForecastErrorRecord", "fit_error_model"]


@dataclass(frozen=True, slots=True)
class ForecastErrorRecord:
    """One historical (issued forecast, realized high) pair.

    ``horizon_hours`` must be the horizon of the forecast AS ISSUED, and
    ``realized_high_f`` the official climate-observation high for
    ``target_date`` -- see the module docstring on why that makes this an
    offline-only input.
    """

    location_id: str
    target_date: date
    horizon_hours: float
    forecast_high_f: float
    realized_high_f: float


def fit_error_model(
    records: Iterable[ForecastErrorRecord],
    base: ForecastErrorModel | None = None,
    min_samples: int = 40,
) -> ForecastErrorModel:
    """Fit per-key bias and sigma overrides from realized forecast errors.

    Bins each error under every key ``ForecastErrorModel.lookup_keys`` would
    consult (station/month/horizon, and the coarser fallbacks up to ``"*"``),
    then writes a bias (mean error) and sigma (sample standard deviation,
    floored at 0.4F) for every key with enough samples. The ``"*"`` catch-all
    is always written regardless of count, so the model is never left with no
    override at all.

    Mutates and returns ``base`` when given one.
    """
    model = base or ForecastErrorModel(min_samples_for_local=min_samples)
    buckets: dict[str, list[float]] = {}
    for rec in records:
        err = rec.realized_high_f - rec.forecast_high_f
        for key in model.lookup_keys(rec.location_id, rec.target_date, rec.horizon_hours):
            buckets.setdefault(key, []).append(err)

    bias: dict[str, float] = {}
    sigma: dict[str, float] = {}
    counts: dict[str, int] = {}
    for key, errs in buckets.items():
        n = len(errs)
        counts[key] = n
        if n < max(8, min_samples // 4) and key != "*":
            continue
        mu = sum(errs) / n
        var = sum((e - mu) ** 2 for e in errs) / max(n - 1, 1)
        bias[key] = mu
        sigma[key] = max(var**0.5, 0.4)

    model.bias_by_key.update(bias)
    model.sigma_by_key.update(sigma)
    model.sample_size_by_key.update(counts)
    return model
