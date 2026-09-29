"""BoundsProvider -- the seam a later calibration slice fills with bootstrap-
draw intervals via ``rung_probability_interval(...)`` (plan A-6). SL-12 ships
only the Protocol, ``RungBounds``, and a test double; decision.py never
computes a bound itself.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from breezy.strategy.ladder_ev.quantile_density import Rung, rung_probabilities


def test_rung_bounds_holds_p_hat_lower_and_upper() -> None:
    from breezy.strategy.forecast_quantile_ladder.bounds import RungBounds

    bounds = RungBounds(p_hat=0.3, p_lower=0.27, p_upper=0.33)

    assert bounds.p_hat == 0.3
    assert bounds.p_lower == 0.27
    assert bounds.p_upper == 0.33


def test_a_fixed_haircut_bounds_provider_satisfies_the_protocol() -> None:
    from breezy.strategy.forecast_quantile_ladder.bounds import BoundsProvider, RungBounds

    def fixed_haircut_bounds(
        *, cdf: Callable[[float], float], ladder: Sequence[Rung], rung_id: str
    ) -> RungBounds:
        p_hat = rung_probabilities(cdf, ladder)[rung_id]
        return RungBounds(
            p_hat=p_hat,
            p_lower=max(0.0, p_hat - 0.03),
            p_upper=min(1.0, p_hat + 0.03),
        )

    assert isinstance(fixed_haircut_bounds, BoundsProvider)

    ladder = (Rung("lt", None, 79), Rung("gte", 80, None))
    bounds = fixed_haircut_bounds(
        cdf=lambda x: 0.0 if x < 80.5 else 1.0, ladder=ladder, rung_id="gte",
    )

    assert bounds.p_hat == 1.0
    assert bounds.p_lower == 0.97
    assert bounds.p_upper == 1.0
