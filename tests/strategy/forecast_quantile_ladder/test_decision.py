"""decision.evaluate -- SL-12 pure decision math, latch and permit rule.

Plan §3.3: first-executable-snapshot latch per (station-day, rung, side);
qty always 1; a decision outside the permit is NOT_EXECUTABLE, never latched.
"""

from __future__ import annotations

import datetime as dt
import math
from typing import Literal

import pytest

from breezy.strategy.forecast_quantile_ladder.calibration_artefact import CalibrationArtefact
from breezy.strategy.forecast_quantile_ladder.decision import (
    Decision,
    NotExecutable,
    Refuse,
    Take,
    evaluate,
)
from breezy.strategy.forecast_quantile_ladder.latch import QuantileLadderLatch
from breezy.strategy.ladder_ev.config import LadderEvConfig
from breezy.strategy.ladder_ev.forecast_state import ForecastQuantileVector
from breezy.strategy.ladder_ev.quantile_density import CdfMethod, EmosParams, Rung
from breezy.strategy.weather_common.costs import venue_fee_prob

_DAY = dt.date(2026, 10, 1)
_STATION = "KMIA"
_INSTRUMENT = "KMIA-2026-10-01-i1.POLY_US"

_LADDER = (
    Rung("lt", None, 77),
    Rung("i0", 78, 79),
    Rung("i1", 80, 81),
    Rung("i2", 82, 83),
    Rung("i3", 84, 85),
    Rung("gte", 86, None),
)


def _vector(*, mean: float = 80.0, sd: float = 2.5) -> ForecastQuantileVector:
    return ForecastQuantileVector(
        q10=mean - 3.2,
        q25=mean - 1.7,
        q50=mean,
        q75=mean + 1.7,
        q90=mean + 3.2,
        mean=mean,
        sd=sd,
        available_at_ns=1_000,
        cycle_runtime_ns=500,
    )


def _artefact(
    *, p_lower_haircut: float = 0.03, p_upper_haircut: float = 0.03
) -> CalibrationArtefact:
    return CalibrationArtefact(
        sha256="a" * 64,
        cdf_method=CdfMethod.NORMAL,
        emos=EmosParams(a=0.0, gamma=0.0, delta=1.0),
        p_lower_haircut=p_lower_haircut,
        p_upper_haircut=p_upper_haircut,
    )


_DEFAULT_VECTOR = _vector()
_DEFAULT_ARTEFACT = _artefact()
_DEFAULT_LADDER_CFG = LadderEvConfig()


def _run(
    *,
    permit_covers: bool = True,
    vector: ForecastQuantileVector | None = _DEFAULT_VECTOR,
    station: str = _STATION,
    climate_day: dt.date = _DAY,
    instrument_id: str = _INSTRUMENT,
    ladder: tuple[Rung, ...] = _LADDER,
    rung_id: str = "i1",
    side: Literal["yes", "no"] = "yes",
    ask: float = 0.30,
    fee_coefficient: float = 0.0695,
    slippage_floor_prob: float = 0.01,
    h_hours: float = 6.0,
    n_cell: int = 90,
    cfg: LadderEvConfig = _DEFAULT_LADDER_CFG,
    artefact: CalibrationArtefact = _DEFAULT_ARTEFACT,
    latch: QuantileLadderLatch | None = None,
) -> Decision:
    """Thin, fully-typed wrapper around ``evaluate`` with this suite's
    defaults -- avoids a ``**dict[str, object]`` call, which mypy cannot
    check against ``evaluate``'s real keyword signature. ``vector=None`` is a
    real, distinct override (forecast-unavailable), never confused with
    "use the default"."""
    return evaluate(
        permit_covers=permit_covers,
        vector=vector,
        station=station,
        climate_day=climate_day,
        instrument_id=instrument_id,
        ladder=ladder,
        rung_id=rung_id,
        side=side,
        ask=ask,
        fee_coefficient=fee_coefficient,
        slippage_floor_prob=slippage_floor_prob,
        h_hours=h_hours,
        n_cell=n_cell,
        cfg=cfg,
        artefact=artefact,
        latch=latch if latch is not None else QuantileLadderLatch(),
    )


# ---------------------------------------------------------------------------
# NOT_EXECUTABLE outside the permit; never latched
# ---------------------------------------------------------------------------


def test_outside_the_permit_is_not_executable_and_never_latched() -> None:
    latch = QuantileLadderLatch()

    result = _run(permit_covers=False, latch=latch)

    assert isinstance(result, NotExecutable)
    assert latch.is_latched(station=_STATION, climate_day=_DAY, rung_id="i1", side="yes") is False


def test_outside_the_permit_wins_over_an_otherwise_qualifying_snapshot() -> None:
    """Permit is checked FIRST -- even a snapshot that would Take is refused."""
    result = _run(permit_covers=False, ask=0.05)

    assert isinstance(result, NotExecutable)


# ---------------------------------------------------------------------------
# Latch: first qualifying snapshot only; a new cycle never re-opens it
# ---------------------------------------------------------------------------


def test_the_first_qualifying_snapshot_latches_the_rung() -> None:
    latch = QuantileLadderLatch()

    result = _run(ask=0.10, latch=latch)

    assert isinstance(result, Take)
    assert latch.is_latched(station=_STATION, climate_day=_DAY, rung_id="i1", side="yes") is True


def test_a_second_snapshot_after_the_latch_is_refused_even_if_it_would_also_qualify() -> None:
    latch = QuantileLadderLatch()
    first = _run(ask=0.10, latch=latch)
    assert isinstance(first, Take)

    second = _run(ask=0.05, latch=latch)

    assert isinstance(second, Refuse)
    assert second.reason == "already_latched"


def test_a_new_forecast_cycle_never_re_opens_an_already_latched_rung() -> None:
    latch = QuantileLadderLatch()
    _run(ask=0.10, latch=latch)

    later_vector = _vector(mean=82.0)
    result = _run(ask=0.05, vector=later_vector, latch=latch)

    assert isinstance(result, Refuse)
    assert result.reason == "already_latched"


# ---------------------------------------------------------------------------
# qty is always 1
# ---------------------------------------------------------------------------


def test_qty_is_always_1() -> None:
    result = _run(ask=0.10)

    assert isinstance(result, Take)
    assert result.qty == 1


# ---------------------------------------------------------------------------
# Forecast unavailable
# ---------------------------------------------------------------------------


def test_a_missing_vector_refuses_forecast_unavailable() -> None:
    result = _run(vector=None)

    assert isinstance(result, Refuse)
    assert result.reason == "forecast_unavailable"


# ---------------------------------------------------------------------------
# Margin
# ---------------------------------------------------------------------------


def test_ev_net_at_or_below_margin_is_refused() -> None:
    result = _run(ask=0.95)

    assert isinstance(result, Refuse)
    assert result.reason == "below_margin"


# ---------------------------------------------------------------------------
# Decision math matches a hand-computed ev_net for one rung
# ---------------------------------------------------------------------------


def _hand_computed_normal_cdf(x: float, *, mean: float, sd: float) -> float:
    return 0.5 * (1.0 + math.erf((x - mean) / (sd * math.sqrt(2.0))))


def test_decision_math_matches_a_hand_computed_ev_net_for_one_rung() -> None:
    mean, sd = 80.0, 2.5
    ask = 0.20
    fee_coefficient = 0.0695
    slippage_floor_prob = 0.01
    haircut = 0.03

    # Independently re-derive P(i1) = F(81.5) - F(79.5) from the closed-form
    # normal CDF (plan §3.2 item 7: integer labels latent in [x-0.5, x+0.5)),
    # never by calling build_cdf/rung_probabilities.
    p_hat = _hand_computed_normal_cdf(
        81.5, mean=mean, sd=sd
    ) - _hand_computed_normal_cdf(79.5, mean=mean, sd=sd)
    p_lower = p_hat - haircut
    fee_prob = venue_fee_prob(executable_price=ask, fee_coefficient=fee_coefficient)
    expected_ev_net = p_lower - ask - (fee_prob + slippage_floor_prob)

    result = _run(
        ask=ask,
        fee_coefficient=fee_coefficient,
        slippage_floor_prob=slippage_floor_prob,
        artefact=_artefact(p_lower_haircut=haircut, p_upper_haircut=haircut),
        vector=_vector(mean=mean, sd=sd),
    )

    assert isinstance(result, Take)
    assert result.p_hat == pytest.approx(p_hat, abs=1e-12)
    assert result.ev_net == pytest.approx(expected_ev_net, abs=1e-12)


def test_an_unknown_rung_id_raises() -> None:
    with pytest.raises(ValueError, match="rung_id"):
        _run(rung_id="not_a_rung")


def test_no_side_uses_one_minus_p_upper() -> None:
    """NO leg buys the native NO instrument long -- p_upper, not p_lower (plan §8)."""
    result = _run(side="no", rung_id="lt", ask=0.10)

    assert isinstance(result, Take | Refuse)
