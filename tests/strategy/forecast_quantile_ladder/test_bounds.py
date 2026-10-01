"""BoundsProvider -- the seam a later calibration slice fills with bootstrap-
draw intervals via ``rung_probability_interval(...)`` (plan A-6). SL-13 S2
widens the Protocol to take the vector's own ``percentiles`` and the
calibration's era-resolved ``draws`` directly (never a ``cdf`` callable, never
a ``percentiles_fn`` closure -- ``decision.py`` never computes a bound itself).
"""

from __future__ import annotations

from collections.abc import Sequence

from breezy.strategy.ladder_ev.quantile_density import (
    CdfMethod,
    EmosParams,
    Percentiles,
    Rung,
    apply_emos,
    build_cdf,
    rung_probabilities,
)


def test_rung_bounds_holds_p_hat_lower_and_upper() -> None:
    from breezy.strategy.forecast_quantile_ladder.bounds import RungBounds

    bounds = RungBounds(p_hat=0.3, p_lower=0.27, p_upper=0.33)

    assert bounds.p_hat == 0.3
    assert bounds.p_lower == 0.27
    assert bounds.p_upper == 0.33


def test_a_fixed_haircut_bounds_provider_satisfies_the_protocol() -> None:
    from breezy.strategy.forecast_quantile_ladder.bounds import BoundsProvider, RungBounds

    def fixed_haircut_bounds(
        *,
        percentiles: Percentiles,
        draws: Sequence[EmosParams],
        ladder: Sequence[Rung],
        rung_id: str,
    ) -> RungBounds:
        del draws
        cdf = apply_emos(
            build_cdf(CdfMethod.NORMAL, percentiles), percentiles, EmosParams(0.0, 0.0, 1.0),
        )
        p_hat = rung_probabilities(cdf, ladder)[rung_id]
        return RungBounds(
            p_hat=p_hat,
            p_lower=max(0.0, p_hat - 0.03),
            p_upper=min(1.0, p_hat + 0.03),
        )

    assert isinstance(fixed_haircut_bounds, BoundsProvider)

    ladder = (Rung("lt", None, 79), Rung("gte", 80, None))
    percentiles = Percentiles(q10=76, q25=78, q50=80.4, q75=82, q90=84, mean=80.4, sd=3)
    bounds = fixed_haircut_bounds(
        percentiles=percentiles, draws=(EmosParams(0.0, 0.0, 1.0),), ladder=ladder, rung_id="gte",
    )

    assert 0.0 <= bounds.p_lower <= bounds.p_hat <= bounds.p_upper <= 1.0
