"""ARM D1: the pure harm-stop evaluator (plan r2 delta D5, verbatim rule text).

Every case is a fixture. The evaluator takes settled fills; nothing here reads a store.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
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


# -- review K1: W, L and n are counted per STATION-DAY ---------------------------------------------


def test_k1_a_two_fill_win_day_is_one_win_and_t2_trips_at_w_star_875() -> None:
    # day A: two winning fills; days B and C: one loss each. Per STATION-DAY that is W1 L2 n3
    # (per fill it would be W2 L2 n4 and the 95% bound 0.97 would clear w*). w* is per fill.
    fills = [
        _fill(1, WIN, cost="0.875"),
        _fill(1, WIN, cost="0.875"),
        _fill(2, LOSS, cost="0.875"),
        _fill(3, LOSS, cost="0.875"),
    ]
    result = _run(fills)
    assert (result.wins, result.losses, result.n) == (1, 2, 3)
    assert result.w_star == Decimal("0.875")
    assert result.cp_upper == pytest.approx(0.8646496378284161, abs=1e-12)
    assert result.triggers == ("T2",)
    assert result.verdict is HarmVerdict.FAIL
    assert result.fills == 4


def test_k1_a_day_is_a_win_only_if_every_fill_on_it_won() -> None:
    mixed = _run([_fill(1, WIN), _fill(1, LOSS)])
    assert (mixed.wins, mixed.losses, mixed.n) == (0, 1, 1)
    unresolved = _run([_fill(1, WIN), _fill(1, UNRES)])
    assert (unresolved.wins, unresolved.losses) == (0, 1)


def test_k1_pnl_stays_per_fill_and_the_t3_gate_counts_station_days() -> None:
    # four fills on THREE station-days: n = 3 < 4, so T3 is not armed even though the per-fill
    # cumulative PnL (2 * 0.13 - 2 * 0.87 = -1.48) is below -w*
    fills = [
        _fill(1, WIN, cost="0.87"),
        _fill(1, WIN, cost="0.87"),
        _fill(2, LOSS, cost="0.87"),
        _fill(3, LOSS, cost="0.87"),
    ]
    result = _run(fills)
    assert result.n == 3 and result.cum_pnl == Decimal("-1.48")
    assert "T3" not in result.triggers
    # one more distinct day arms it
    assert "T3" in _run([*fills, _fill(4, LOSS, cost="0.87")]).triggers


# -- review J2: PENDING settlement ---------------------------------------------------------------


PENDING = FillOutcome.PENDING


def test_j2_pending_fills_are_excluded_from_every_count() -> None:
    result = _run([_fill(1, WIN), _fill(2, PENDING, cost="0.99"), _fill(3, PENDING, cost="0.99")])
    assert (result.wins, result.losses, result.n, result.fills) == (1, 0, 1, 1)
    assert result.pending == 2
    assert result.w_star == Decimal("0.86")
    assert result.cum_pnl == Decimal("0.14")
    assert result.verdict is HarmVerdict.PASS


def test_j2_only_pending_fills_is_a_pass_with_no_w_star() -> None:
    result = _run([_fill(1, PENDING), _fill(1, PENDING), _fill(1, PENDING)])
    assert result.verdict is HarmVerdict.PASS
    assert (result.n, result.fills, result.pending, result.w_star) == (0, 0, 3, None)


def test_j2_the_settlement_deadline_is_48h_after_the_end_of_the_local_day() -> None:
    assert hs.SETTLEMENT_PENDING_WINDOW == timedelta(hours=48)
    # climate day 2026-09-10 at LAX (std offset -8): the day ends 2026-09-11 08:00Z
    deadline = hs.settlement_deadline(date(2026, 9, 10), std_utc_offset_hours=-8.0)
    assert deadline == datetime(2026, 9, 13, 8, 0, tzinfo=UTC)
    nyc = hs.settlement_deadline(date(2026, 9, 10), std_utc_offset_hours=-5.0)
    assert nyc == datetime(2026, 9, 13, 5, 0, tzinfo=UTC)


def _settle(*, venue: bool | None, cli: bool | None, pending: bool) -> hs.SettledFill:
    return hs.settle_fill(
        station_day="nyc|2026-09-10",
        cost=Decimal("0.87"),
        quantity=Decimal(1),
        venue_yes_resolved=venue,
        cli_yes=cli,
        pending=pending,
    )


def test_j2_settle_fill_is_pending_only_while_unresolved_and_before_the_deadline() -> None:
    pending = _settle(venue=None, cli=None, pending=True)
    assert pending.outcome is PENDING and pending.cause == "venue_settlement_missing"
    assert _settle(venue=None, cli=None, pending=False).outcome is FillOutcome.UNRESOLVED
    # a resolved fill is scored at once, before the deadline: a known loss is never hidden
    assert _settle(venue=True, cli=True, pending=True).outcome is FillOutcome.LOSS
    mismatch = _settle(venue=False, cli=True, pending=True)
    assert mismatch.outcome is PENDING and mismatch.cause == "settlement_mismatch"
    missing_cli = _settle(venue=False, cli=None, pending=True)
    assert missing_cli.outcome is PENDING and missing_cli.cause == "cli_final_missing"
