"""``ArtefactBoundsProvider`` (SL-13 S2) -- the real ``BoundsProvider``
implementation ``bounds.py`` names as a seam.

SL-13 S2: this provider no longer reads or hashes a file itself (the
duplicate loader, ``load_bounds_artefact_draws``, is removed -- the sha-pin,
fit-status, per-version pooling and location-correction logic all live in
``calibration_artefact.load_live_calibration``/``LiveCalibration.resolve``,
tested in ``test_calibration_artefact.py``). This suite only exercises the
provider's own job: turning already-resolved ``percentiles``/``draws`` into
``RungBounds`` via ``rung_probability_interval``.
"""

from __future__ import annotations

import pytest

from breezy.strategy.forecast_quantile_ladder.artefact_bounds import ArtefactBoundsProvider
from breezy.strategy.ladder_ev.quantile_density import CdfMethod, EmosParams, Percentiles, Rung

_LADDER = (
    Rung("lt", None, 79),
    Rung("i0", 80, 81),
    Rung("gte", 82, None),
)

_PERCENTILES = Percentiles(q10=76, q25=78, q50=80, q75=82, q90=84, mean=80, sd=3)

_DRAWS = (
    EmosParams(a=0.0, gamma=0.0, delta=1.0),
    EmosParams(a=0.1, gamma=0.05, delta=1.0),
    EmosParams(a=-0.1, gamma=-0.02, delta=1.0),
)


def test_provider_returns_rung_bounds_from_percentiles() -> None:
    provider = ArtefactBoundsProvider(cdf_method=CdfMethod.NORMAL)

    bounds = provider(percentiles=_PERCENTILES, draws=_DRAWS, ladder=_LADDER, rung_id="i0")

    assert 0.0 <= bounds.p_lower <= bounds.p_hat <= bounds.p_upper <= 1.0


def test_provider_call_refuses_zero_draws() -> None:
    provider = ArtefactBoundsProvider(cdf_method=CdfMethod.NORMAL)

    with pytest.raises(ValueError, match="at least one draw"):
        provider(percentiles=_PERCENTILES, draws=(), ladder=_LADDER, rung_id="i0")
