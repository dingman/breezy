"""decision.evaluate -- SL-12 pure decision math, latch, permit and D+1 rules.

Plan §3.3: first-executable-snapshot latch per (station-day, rung, side);
qty always 1; a decision outside the permit is NOT_EXECUTABLE, never latched.
Ruling A-6 (RULING_forecast_nbp_reopen_2026-09-29.md §12): forecast-mode
margin, no n_cell; a side's ask must be quoted from that side's own native
instrument; D+1 is enforced in code.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Callable, Sequence
from typing import Literal

import pytest

from breezy.strategy.forecast_quantile_ladder.bounds import RungBounds
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import CalibrationArtefact
from breezy.strategy.forecast_quantile_ladder.decision import (
    AskSideMismatchError,
    Decision,
    NotDPlus1,
    NotExecutable,
    Refuse,
    SidedAsk,
    Take,
    evaluate,
)
from breezy.strategy.forecast_quantile_ladder.latch import QuantileLadderLatch
from breezy.strategy.ladder_ev.config import LadderEvConfig
from breezy.strategy.ladder_ev.forecast_state import ForecastQuantileVector
from breezy.strategy.ladder_ev.quantile_density import (
    CdfMethod,
    EmosParams,
    Rung,
    rung_probabilities,
)
from breezy.strategy.weather_common.costs import venue_fee_prob

_DAY = dt.date(2026, 10, 1)
_STATION = "KMIA"
_KMIA_OFFSET = -5.0
_KLAX_OFFSET = -8.0
_INSTRUMENT = "KMIA-2026-10-01-i1.POLY_US"

_LADDER = (
    Rung("lt", None, 77),
    Rung("i0", 78, 79),
    Rung("i1", 80, 81),
    Rung("i2", 82, 83),
    Rung("i3", 84, 85),
    Rung("gte", 86, None),
)

# 2026-09-30T12:00:00Z: LST for KMIA (-5) is 07:00 on 2026-09-30, so D+1 is
# 2026-10-01 (= _DAY). Chosen as the suite default so every non-D+1-focused
# test needs no date arithmetic of its own.
_NOW_NS = int(dt.datetime(2026, 9, 30, 12, 0, 0, tzinfo=dt.UTC).timestamp() * 1_000_000_000)


def _ns(y: int, m: int, d: int, h: int = 0, mi: int = 0) -> int:
    return int(dt.datetime(y, m, d, h, mi, 0, tzinfo=dt.UTC).timestamp() * 1_000_000_000)


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


def _artefact() -> CalibrationArtefact:
    return CalibrationArtefact(
        sha256="a" * 64,
        cdf_method=CdfMethod.NORMAL,
        emos=EmosParams(a=0.0, gamma=0.0, delta=1.0),
    )


def _fixed_haircut_bounds(haircut: float = 0.03) -> Callable[..., RungBounds]:
    """A test double satisfying ``BoundsProvider`` -- the ONLY place a
    haircut is computed anywhere in this suite; decision.py itself never
    computes one (item 4)."""

    def _provider(
        *, cdf: Callable[[float], float], ladder: Sequence[Rung], rung_id: str
    ) -> RungBounds:
        p_hat = rung_probabilities(cdf, ladder)[rung_id]
        return RungBounds(
            p_hat=p_hat,
            p_lower=max(0.0, p_hat - haircut),
            p_upper=min(1.0, p_hat + haircut),
        )

    return _provider


def _yes_ask(price: float, *, instrument_id: str = _INSTRUMENT) -> SidedAsk:
    return SidedAsk(side="yes", instrument_id=instrument_id, price=price)


def _no_ask(price: float, *, instrument_id: str = _INSTRUMENT + ".NO") -> SidedAsk:
    return SidedAsk(side="no", instrument_id=instrument_id, price=price)


_DEFAULT_VECTOR = _vector()
_DEFAULT_ARTEFACT = _artefact()
_DEFAULT_LADDER_CFG = LadderEvConfig()
_DEFAULT_BOUNDS = _fixed_haircut_bounds()


def _run(
    *,
    now_ns: int = _NOW_NS,
    std_utc_offset_hours: float = _KMIA_OFFSET,
    permit_covers: bool = True,
    vector: ForecastQuantileVector | None = _DEFAULT_VECTOR,
    station: str = _STATION,
    climate_day: dt.date = _DAY,
    ladder: tuple[Rung, ...] = _LADDER,
    rung_id: str = "i1",
    side: Literal["yes", "no"] = "yes",
    ask: SidedAsk | None = None,
    fee_coefficient: float = 0.0695,
    slippage_floor_prob: float = 0.01,
    h_hours: float = 6.0,
    cfg: LadderEvConfig = _DEFAULT_LADDER_CFG,
    artefact: CalibrationArtefact = _DEFAULT_ARTEFACT,
    bounds_provider: Callable[..., RungBounds] = _DEFAULT_BOUNDS,
    latch: QuantileLadderLatch | None = None,
) -> Decision:
    """Thin, fully-typed wrapper around ``evaluate`` -- avoids a
    ``**dict[str, object]`` call, which mypy cannot check against
    ``evaluate``'s real keyword signature."""
    resolved_ask = ask if ask is not None else (_yes_ask(0.30) if side == "yes" else _no_ask(0.30))
    return evaluate(
        now_ns=now_ns,
        std_utc_offset_hours=std_utc_offset_hours,
        permit_covers=permit_covers,
        vector=vector,
        station=station,
        climate_day=climate_day,
        ladder=ladder,
        rung_id=rung_id,
        side=side,
        ask=resolved_ask,
        fee_coefficient=fee_coefficient,
        slippage_floor_prob=slippage_floor_prob,
        h_hours=h_hours,
        cfg=cfg,
        artefact=artefact,
        bounds_provider=bounds_provider,
        latch=latch if latch is not None else QuantileLadderLatch(),
    )


# ---------------------------------------------------------------------------
# Item 1: NO-side ask binding
# ---------------------------------------------------------------------------


def test_a_yes_ask_passed_for_a_no_evaluation_raises() -> None:
    with pytest.raises(AskSideMismatchError):
        _run(side="no", ask=_yes_ask(0.10))


def test_a_no_ask_passed_for_a_yes_evaluation_raises() -> None:
    with pytest.raises(AskSideMismatchError):
        _run(side="yes", ask=_no_ask(0.10))


def test_a_matching_yes_ask_is_accepted() -> None:
    result = _run(side="yes", ask=_yes_ask(0.10))
    assert isinstance(result, Take)
    assert result.instrument_id == _INSTRUMENT


def test_a_matching_no_ask_is_accepted() -> None:
    result = _run(side="no", rung_id="lt", ask=_no_ask(0.10))
    assert isinstance(result, Take | Refuse)


# ---------------------------------------------------------------------------
# Item 3: D+1 enforced in code (hand-computed dates, KLAX and KMIA)
# ---------------------------------------------------------------------------


def test_klax_before_d_plus_1_is_refused() -> None:
    """now=2026-09-30T06:00Z; KLAX (-8) LST = 2026-09-29T22:00 -> today=09-29,
    D+1=09-30. climate_day=09-29 (=D0) must be refused."""
    now_ns = _ns(2026, 9, 30, 6, 0)
    result = _run(
        now_ns=now_ns,
        std_utc_offset_hours=_KLAX_OFFSET,
        station="KLAX",
        climate_day=dt.date(2026, 9, 29),
    )
    assert isinstance(result, NotDPlus1)


def test_klax_at_d_plus_1_is_accepted() -> None:
    """Same instant: KLAX's D+1 is 2026-09-30."""
    now_ns = _ns(2026, 9, 30, 6, 0)
    result = _run(
        now_ns=now_ns,
        std_utc_offset_hours=_KLAX_OFFSET,
        station="KLAX",
        climate_day=dt.date(2026, 9, 30),
        ask=_yes_ask(0.10),
    )
    assert isinstance(result, Take)


def test_klax_d_plus_2_is_refused() -> None:
    now_ns = _ns(2026, 9, 30, 6, 0)
    result = _run(
        now_ns=now_ns,
        std_utc_offset_hours=_KLAX_OFFSET,
        station="KLAX",
        climate_day=dt.date(2026, 10, 1),
    )
    assert isinstance(result, NotDPlus1)


def test_kmia_at_the_same_instant_has_a_different_d_plus_1() -> None:
    """Same instant as the KLAX cases above, but KMIA (-5) LST = 01:00 on
    2026-09-30 -> today=09-30, D+1=10-01 -- one UTC day later than KLAX's,
    because the two stations' standard-time offsets differ by 3 hours across
    the UTC midnight boundary this instant sits near."""
    now_ns = _ns(2026, 9, 30, 6, 0)
    result = _run(
        now_ns=now_ns,
        std_utc_offset_hours=_KMIA_OFFSET,
        station="KMIA",
        climate_day=dt.date(2026, 9, 30),
    )
    assert isinstance(result, NotDPlus1)

    accepted = _run(
        now_ns=now_ns,
        std_utc_offset_hours=_KMIA_OFFSET,
        station="KMIA",
        climate_day=dt.date(2026, 10, 1),
        ask=_yes_ask(0.10),
    )
    assert isinstance(accepted, Take)


def test_a_non_d_plus_1_evaluation_never_latches() -> None:
    latch = QuantileLadderLatch()
    now_ns = _ns(2026, 9, 30, 6, 0)

    _run(
        now_ns=now_ns,
        std_utc_offset_hours=_KLAX_OFFSET,
        station="KLAX",
        climate_day=dt.date(2026, 9, 29),
        latch=latch,
    )

    is_latched = latch.is_latched(
        station="KLAX", climate_day=dt.date(2026, 9, 29), rung_id="i1", side="yes",
    )
    assert is_latched is False


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
    result = _run(permit_covers=False, ask=_yes_ask(0.05))

    assert isinstance(result, NotExecutable)


# ---------------------------------------------------------------------------
# Latch: first qualifying snapshot only; a new cycle never re-opens it
# ---------------------------------------------------------------------------


def test_the_first_qualifying_snapshot_latches_the_rung() -> None:
    latch = QuantileLadderLatch()

    result = _run(ask=_yes_ask(0.10), latch=latch)

    assert isinstance(result, Take)
    assert latch.is_latched(station=_STATION, climate_day=_DAY, rung_id="i1", side="yes") is True


def test_a_second_snapshot_after_the_latch_is_refused_even_if_it_would_also_qualify() -> None:
    latch = QuantileLadderLatch()
    first = _run(ask=_yes_ask(0.10), latch=latch)
    assert isinstance(first, Take)

    second = _run(ask=_yes_ask(0.05), latch=latch)

    assert isinstance(second, Refuse)
    assert second.reason == "already_latched"


def test_a_new_forecast_cycle_never_re_opens_an_already_latched_rung() -> None:
    latch = QuantileLadderLatch()
    _run(ask=_yes_ask(0.10), latch=latch)

    later_vector = _vector(mean=82.0)
    result = _run(ask=_yes_ask(0.05), vector=later_vector, latch=latch)

    assert isinstance(result, Refuse)
    assert result.reason == "already_latched"


# ---------------------------------------------------------------------------
# qty is always 1
# ---------------------------------------------------------------------------


def test_qty_is_always_1() -> None:
    result = _run(ask=_yes_ask(0.10))

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
# Margin (item 2: forecast_margin, no n_cell)
# ---------------------------------------------------------------------------


def test_ev_net_at_or_below_margin_is_refused() -> None:
    result = _run(ask=_yes_ask(0.95))

    assert isinstance(result, Refuse)
    assert result.reason == "below_margin"


def test_evaluate_has_no_n_cell_parameter() -> None:
    """A-6: the archive-cell gate is dropped for this family."""
    import inspect

    params = inspect.signature(evaluate).parameters
    assert "n_cell" not in params


# ---------------------------------------------------------------------------
# Decision math matches a hand-computed ev_net for one rung (item 2's take
# rule, A-6): YES: p_lower - ask - fee(ask) > margin. slippage is 0 so the
# shared DepthAwareTradeCost path collapses to exactly A-6's literal formula.
# ---------------------------------------------------------------------------


def _hand_computed_normal_cdf(x: float, *, mean: float, sd: float) -> float:
    return 0.5 * (1.0 + math.erf((x - mean) / (sd * math.sqrt(2.0))))


def test_decision_math_matches_a_hand_computed_ev_net_for_one_rung() -> None:
    mean, sd = 80.0, 2.5
    ask_price = 0.20
    fee_coefficient = 0.0695
    haircut = 0.03

    p_hat = _hand_computed_normal_cdf(
        81.5, mean=mean, sd=sd
    ) - _hand_computed_normal_cdf(79.5, mean=mean, sd=sd)
    p_lower = p_hat - haircut
    fee_prob = venue_fee_prob(executable_price=ask_price, fee_coefficient=fee_coefficient)
    expected_ev_net = p_lower - ask_price - fee_prob
    expected_margin = 0.02  # forecast_margin(6.0, LadderEvConfig()) == m0

    result = _run(
        ask=_yes_ask(ask_price),
        fee_coefficient=fee_coefficient,
        slippage_floor_prob=0.0,
        bounds_provider=_fixed_haircut_bounds(haircut),
        vector=_vector(mean=mean, sd=sd),
    )

    assert isinstance(result, Take)
    assert result.p_hat == pytest.approx(p_hat, abs=1e-12)
    assert result.ev_net == pytest.approx(expected_ev_net, abs=1e-12)
    assert expected_ev_net > expected_margin  # sanity: this snapshot DOES qualify


def test_the_no_side_take_rule_matches_a_hand_computed_value() -> None:
    """A-6: NO take if (1 - p_upper) - no_ask - fee(no_ask) > margin(h)."""
    mean, sd = 80.0, 2.5
    ask_price = 0.05
    fee_coefficient = 0.0695
    haircut = 0.03

    # rung "lt" (lo=None, hi=77): P = F(77.5).
    p_hat = _hand_computed_normal_cdf(77.5, mean=mean, sd=sd)
    p_upper = min(1.0, p_hat + haircut)
    expected_model_p = 1.0 - p_upper
    fee_prob = venue_fee_prob(executable_price=ask_price, fee_coefficient=fee_coefficient)
    expected_ev_net = expected_model_p - ask_price - fee_prob

    result = _run(
        side="no",
        rung_id="lt",
        ask=_no_ask(ask_price),
        fee_coefficient=fee_coefficient,
        slippage_floor_prob=0.0,
        bounds_provider=_fixed_haircut_bounds(haircut),
        vector=_vector(mean=mean, sd=sd),
    )

    assert isinstance(result, Take)
    assert result.ev_net == pytest.approx(expected_ev_net, abs=1e-12)


def test_an_unknown_rung_id_raises() -> None:
    with pytest.raises(ValueError, match="rung_id"):
        _run(rung_id="not_a_rung")


def test_no_side_uses_one_minus_p_upper() -> None:
    """NO leg buys the native NO instrument long -- p_upper, not p_lower (plan §8)."""
    result = _run(side="no", rung_id="lt", ask=_no_ask(0.10))

    assert isinstance(result, Take | Refuse)


# ---------------------------------------------------------------------------
# Item 4: bounds come ONLY from the injected BoundsProvider
# ---------------------------------------------------------------------------


def test_decisions_depend_only_on_the_supplied_bounds() -> None:
    """Two providers returning DIFFERENT bounds for the SAME cdf/ladder/rung
    must produce different ev_net -- decision.py never recomputes a bound
    itself."""

    def generous(
        *, cdf: Callable[[float], float], ladder: Sequence[Rung], rung_id: str
    ) -> RungBounds:
        p_hat = rung_probabilities(cdf, ladder)[rung_id]
        return RungBounds(p_hat=p_hat, p_lower=min(1.0, p_hat + 0.5), p_upper=1.0)

    def stingy(
        *, cdf: Callable[[float], float], ladder: Sequence[Rung], rung_id: str
    ) -> RungBounds:
        p_hat = rung_probabilities(cdf, ladder)[rung_id]
        return RungBounds(p_hat=p_hat, p_lower=max(0.0, p_hat - 0.5), p_upper=1.0)

    generous_result = _run(ask=_yes_ask(0.10), bounds_provider=generous)
    stingy_result = _run(ask=_yes_ask(0.10), bounds_provider=stingy)

    assert isinstance(generous_result, Take)
    assert isinstance(stingy_result, Refuse)


def test_calibration_artefact_has_no_haircut_fields() -> None:
    """Item 4: the haircut fields are removed from the artefact entirely."""
    artefact = _artefact()
    assert not hasattr(artefact, "p_lower_haircut")
    assert not hasattr(artefact, "p_upper_haircut")
