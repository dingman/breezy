"""ARM D1: the pure harm-stop evaluator (plan r2 delta D5, verbatim rule text).

Every case is a fixture. The evaluator takes settled fills; nothing here reads a store.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

import pytest
from scipy.stats import binom

from breezy.runtime.exec_par_stage_types import FEE_THETA
from breezy.strategy.no_ladder_maker import harm_stop as hs
from breezy.strategy.no_ladder_maker.harm_stop import (
    FamilyFillClassification,
    FillOutcome,
    HarmVerdict,
    SettledFill,
    cp_upper_bound,
    evaluate_harm_stop,
)

CLEAR: Final = FamilyFillClassification(
    maker_fills=(), get_fills=(), open_ambiguous_family_intent=False
)


def _fill(
    day: int,
    outcome: FillOutcome,
    *,
    cost: str = "0.86",
    station: str = "nyc",
) -> SettledFill:
    return SettledFill(
        station_day=f"{station}|2026-09-{day:02d}",
        cost=Decimal(cost),
        outcome=outcome,
        cause="fixture",
    )


WIN, LOSS, UNRES = FillOutcome.WIN, FillOutcome.LOSS, FillOutcome.UNRESOLVED


def _run(fills: list[SettledFill], *, blocked: bool = False) -> hs.HarmStopResult:
    return evaluate_harm_stop(fills, blocked_reasons=("get_fill",) if blocked else ())


def test_zero_fills_is_pass() -> None:
    result = _run([])
    assert result.verdict is HarmVerdict.PASS
    assert (result.wins, result.losses, result.n, result.triggers) == (0, 0, 0, ())
    assert result.w_star is None


def test_the_third_distinct_station_day_loss_is_fail_t1() -> None:
    two = [_fill(1, WIN), _fill(2, LOSS), _fill(3, LOSS)]
    assert "T1" not in _run(two).triggers
    three = [*two, _fill(4, LOSS)]
    result = _run(three)
    assert result.verdict is HarmVerdict.FAIL
    assert "T1" in result.triggers
    assert result.losses == 3


def test_two_legs_on_one_station_day_lose_at_most_once() -> None:
    fills = [_fill(1, LOSS), _fill(1, LOSS, cost="0.80"), _fill(2, LOSS), _fill(3, WIN)]
    result = _run(fills)
    assert result.losses == 2, "day 1 counts once"
    assert "T1" not in result.triggers
    # the same loss on three DISTINCT days is the third loss
    assert "T1" in _run([_fill(1, LOSS), _fill(2, LOSS), _fill(3, LOSS)]).triggers


def test_distinct_means_station_and_day_not_day_alone() -> None:
    fills = [
        _fill(1, LOSS, station="nyc"),
        _fill(1, LOSS, station="lax"),
        _fill(1, LOSS, station="sfo"),
    ]
    assert _run(fills).losses == 3


def test_t2_clopper_pearson_boundary_at_n_3() -> None:
    # 1 win, 2 losses: the one-sided 95% upper bound on W/n is 0.86465
    just_below = [
        _fill(1, WIN, cost="0.87"),
        _fill(2, LOSS, cost="0.87"),
        _fill(3, LOSS, cost="0.87"),
    ]
    result = _run(just_below)
    assert result.w_star == Decimal("0.87")
    assert result.cp_upper is not None and result.cp_upper < 0.87
    assert result.verdict is HarmVerdict.FAIL and "T2" in result.triggers
    just_above = [
        _fill(1, WIN, cost="0.86"),
        _fill(2, LOSS, cost="0.86"),
        _fill(3, LOSS, cost="0.86"),
    ]
    result = _run(just_above)
    assert result.cp_upper is not None and result.cp_upper > 0.86
    assert "T2" not in result.triggers
    assert result.verdict is HarmVerdict.PASS


def test_t2_needs_n_at_least_3() -> None:
    result = _run([_fill(1, LOSS, cost="0.99"), _fill(2, LOSS, cost="0.99")])
    assert result.cp_upper is None
    assert result.triggers == ()
    assert result.verdict is HarmVerdict.PASS


def test_t3_cumulative_pnl_at_or_below_minus_w_star() -> None:
    # 2 wins + 2 losses at 0.87: pnl = 2*0.13 - 2*0.87 = -1.48 <= -0.87; T1 and T2 do not fire
    fills = [
        _fill(1, WIN, cost="0.87"),
        _fill(2, WIN, cost="0.87"),
        _fill(3, LOSS, cost="0.87"),
        _fill(4, LOSS, cost="0.87"),
    ]
    result = _run(fills)
    assert result.cum_pnl == Decimal("-1.48")
    assert result.triggers == ("T3",)
    assert result.verdict is HarmVerdict.FAIL


def test_t3_needs_n_at_least_4() -> None:
    three = [_fill(1, LOSS, cost="0.50"), _fill(2, LOSS, cost="0.50"), _fill(3, LOSS, cost="0.50")]
    assert _run(three).cum_pnl <= -_run(three).w_star  # type: ignore[operator]
    assert "T3" not in _run(three).triggers, "n=3 is below the T3 look"


def test_t3_is_inclusive_at_equality() -> None:
    # n=4, W=3, L=1 at cost 1.00: pnl = 0 + 0 + 0 - 1.00 == -w*
    fills = [
        _fill(1, WIN, cost="1.00"),
        _fill(2, WIN, cost="1.00"),
        _fill(3, WIN, cost="1.00"),
        _fill(4, LOSS, cost="1.00"),
    ]
    result = _run(fills)
    assert result.cum_pnl == Decimal("-1.00") == -result.w_star  # type: ignore[operator]
    assert "T3" in result.triggers
    just_inside = [_fill(i, WIN, cost="0.99") for i in (1, 2, 3)] + [_fill(4, LOSS, cost="0.99")]
    result = _run(just_inside)
    assert result.cum_pnl == Decimal("-0.96") > -result.w_star  # type: ignore[operator]
    assert "T3" not in result.triggers


def test_an_unresolved_fill_counts_as_a_loss_until_resolved() -> None:
    fills = [_fill(1, WIN), _fill(2, UNRES), _fill(3, UNRES), _fill(4, UNRES)]
    result = _run(fills)
    assert result.losses == 3 and "T1" in result.triggers
    assert result.unresolved == 3
    resolved = [_fill(1, WIN), _fill(2, WIN), _fill(3, WIN), _fill(4, WIN)]
    assert _run(resolved).verdict is HarmVerdict.PASS


def test_a_blocked_classification_holds_and_never_passes() -> None:
    result = _run([_fill(1, WIN)], blocked=True)
    assert result.verdict is HarmVerdict.HOLD
    assert result.hold_reasons == ("get_fill",)
    assert _run([], blocked=True).verdict is HarmVerdict.HOLD


def test_fail_outranks_hold() -> None:
    fills = [_fill(1, LOSS), _fill(2, LOSS), _fill(3, LOSS)]
    result = _run(fills, blocked=True)
    assert result.verdict is HarmVerdict.FAIL
    assert result.hold_reasons == ("get_fill",)


@pytest.mark.parametrize(
    ("n", "k", "expected"),
    [
        (3, 0, 0.6315968501359612),
        (3, 1, 0.8646496378284161),
        (3, 2, 0.9830475724915585),
        (4, 3, 0.9872585449014338),
        (10, 9, 0.9948838031081763),
        (30, 29, 0.9982916843555343),
    ],
)
def test_cp_upper_bound_matches_known_values(n: int, k: int, expected: float) -> None:
    assert cp_upper_bound(k, n) == pytest.approx(expected, abs=1e-12)


def test_cp_upper_bound_closed_forms() -> None:
    assert cp_upper_bound(3, 3) == 1.0
    assert cp_upper_bound(17, 17) == 1.0
    for n in (1, 2, 5, 17, 40):
        assert cp_upper_bound(0, n) == pytest.approx(1 - 0.05 ** (1 / n), abs=1e-12)


def test_cp_upper_bound_defining_property_and_monotonicity() -> None:
    for n in range(1, 41):
        previous = -1.0
        for k in range(n):
            bound = cp_upper_bound(k, n)
            assert binom.cdf(k, n, bound) == pytest.approx(0.05, abs=1e-9)
            assert bound >= k / n
            assert bound > previous
            previous = bound
        assert cp_upper_bound(n, n) == 1.0


@pytest.mark.parametrize(("k", "n"), [(-1, 3), (4, 3), (0, 0), (1, -2)])
def test_cp_upper_bound_refuses_impossible_counts(k: int, n: int) -> None:
    with pytest.raises(ValueError, match="counts"):
        cp_upper_bound(k, n)


def test_theta_is_the_d5_constant_and_agrees_with_the_runtime_fee_theta() -> None:
    assert hs.TAKER_THETA == Decimal("0.0695") == FEE_THETA
