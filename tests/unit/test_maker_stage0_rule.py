"""RED-first tests for MAKER-S2 WP3, the pure spec v0.3 section 3 rule.

Source: `docs/strategies/SPEC_pm_us_no_ladder_maker_2026-10-12.md` lines 69-136 and
`docs/plans/backlog/MAKER_2026-10-12/S2_stage0_replay_plan_r3.md` WP3. No I/O.
"""

from __future__ import annotations

import datetime as dt

import pytest

from scripts.analysis import maker_stage0_rule as rule

THETA = 0.0695
NS_H = 3_600 * 1_000_000_000


def _ns(y: int, mo: int, d: int, h: int = 0, mi: int = 0) -> int:
    stamp = dt.datetime(y, mo, d, h, mi, tzinfo=dt.UTC)
    return int(stamp.timestamp()) * 1_000_000_000


def test_rule_constants_match_spec_v03() -> None:
    assert rule.P_MIN == 0.94
    assert rule.B_CAP == 0.80
    assert rule.E_MIN == 0.10
    assert rule.B_FLOOR == 0.70
    assert rule.STALE_H == 8
    assert rule.MAX_RUNGS == 2
    assert rule.CANCEL_LST == dt.time(9, 0)


def test_constants_match_spec_text() -> None:
    from pathlib import Path

    spec = Path("docs/strategies/SPEC_pm_us_no_ladder_maker_2026-10-12.md").read_text()
    assert "constants: P_MIN = 0.94, B_CAP = 0.80, E_MIN = 0.10, B_FLOOR = 0.70," in spec
    assert "STALE_H = 8, MAX_RUNGS = 2, CANCEL_LST = 09:00" in spec


def test_b_max_is_largest_cent_under_cap_and_edge() -> None:
    # p_no 0.99: cap 0.80 binds.
    assert rule.b_max(0.99, THETA) == 0.80
    # p_no 0.90: need b + theta*b*(1-b) <= 0.80 -> 0.73 ok, 0.74 not.
    got = rule.b_max(0.90, THETA)
    assert got is not None
    assert got + THETA * got * (1 - got) <= 0.80 + 1e-9
    assert got + 0.01 + THETA * (got + 0.01) * (1 - got - 0.01) > 0.80


def test_b_max_below_floor_cancels() -> None:
    res = rule.decide_bid(0.95, best_no_bid=0.70, no_ask=0.90, theta=2.0)
    assert res.bid is None
    assert res.reason == "b_max_below_floor"
    assert rule.bid_price(0.95, 0.70, 0.90, 2.0) is None


def test_bid_is_best_plus_one_cent_capped_at_b_max() -> None:
    assert rule.bid_price(0.99, 0.72, 0.90, THETA) == pytest.approx(0.73)
    # best+1c above the cap -> capped at b_max (0.80)
    assert rule.bid_price(0.99, 0.80, 0.95, THETA) == pytest.approx(0.80)


def test_bid_never_crosses_no_ask() -> None:
    assert rule.bid_price(0.99, 0.75, 0.77, THETA) == pytest.approx(0.76)
    assert rule.bid_price(0.99, 0.78, 0.77, THETA) == pytest.approx(0.76)


def test_bid_below_floor_after_clamp_cancels() -> None:
    res = rule.decide_bid(0.99, best_no_bid=0.60, no_ask=0.70, theta=THETA)
    assert res.bid is None
    assert res.reason == "bid_below_floor"


def test_empty_no_bid_side_uses_no_ask_clamp_only() -> None:
    assert rule.bid_price(0.99, None, 0.78, THETA) == pytest.approx(0.77)


def test_empty_yes_bid_side_has_no_ask_clamp() -> None:
    assert rule.bid_price(0.99, 0.72, None, THETA) == pytest.approx(0.73)
    assert rule.bid_price(0.99, None, None, THETA) == pytest.approx(0.80)


def test_p_no_below_p_min_refused() -> None:
    res = rule.decide_bid(0.93, best_no_bid=0.75, no_ask=0.90, theta=THETA)
    assert res.bid is None
    assert res.reason == "p_no_below_p_min"


@pytest.mark.parametrize("bad", [float("nan"), -0.1, 1.1])
def test_invalid_p_no_is_rejected(bad: float) -> None:
    with pytest.raises(ValueError):
        rule.decide_bid(bad, best_no_bid=0.75, no_ask=0.90, theta=THETA)


def test_stale_forecast_no_attempt() -> None:
    day = dt.date(2026, 9, 20)
    assert rule.forecast_gate(day, day, 8 * NS_H + 1) == "forecast_stale"
    assert rule.forecast_gate(day, day, 8 * NS_H) is None
    assert rule.forecast_gate(day, day, 0) is None


def test_forecast_for_another_day_abstains() -> None:
    day = dt.date(2026, 9, 20)
    assert rule.forecast_gate(dt.date(2026, 9, 21), day, 0) == "forecast_day_mismatch"
    assert rule.forecast_gate(None, day, 0) == "forecast_day_mismatch"


def _ladder() -> dict[str, float]:
    # ascending rung order; modal is r3 (p_yes 0.50)
    return {"r0": 0.01, "r1": 0.03, "r2": 0.20, "r3": 0.50, "r4": 0.20, "r5": 0.04, "r6": 0.02}


def _bids(ladder: dict[str, float]) -> dict[str, float | None]:
    return dict.fromkeys(ladder, 0.75)


def test_select_rungs_ranks_lowest_p_yes_non_modal_non_adjacent() -> None:
    ladder = _ladder()
    # r2,r4 adjacent to modal; r3 modal. Eligible: r0 .01 r1 .03 r5 .04 r6 .02
    assert rule.select_rungs(ladder, _bids(ladder)) == ("r0", "r6")


def test_two_rung_bound_and_modal_adjacency() -> None:
    ladder = _ladder()
    got = rule.select_rungs(ladder, _bids(ladder))
    assert len(got) <= rule.MAX_RUNGS
    assert not {"r2", "r3", "r4"} & set(got)


def test_select_rungs_skips_p_yes_failing_p_min() -> None:
    ladder = {"a": 0.07, "b": 0.50, "c": 0.30, "d": 0.20, "e": 0.03}
    # a: p_no .93 fails; modal b, adjacent a,c excluded; d .20 fails; e .03 passes.
    assert rule.select_rungs(ladder, dict.fromkeys(ladder, 0.75)) == ("e",)


def test_select_rungs_requires_bid_at_floor() -> None:
    ladder = _ladder()
    bids = _bids(ladder)
    bids["r0"] = None
    bids["r6"] = 0.69
    assert rule.select_rungs(ladder, bids) == ("r1", "r5")


def test_no_rung_passes_p_min_returns_empty() -> None:
    ladder = {"a": 0.30, "b": 0.40, "c": 0.30}
    assert rule.select_rungs(ladder, dict.fromkeys(ladder, 0.75)) == ()
    assert rule.select_rungs({}, {}) == ()


def test_select_rungs_missing_bid_entry_is_ineligible() -> None:
    ladder = _ladder()
    assert rule.select_rungs(ladder, {"r5": 0.75}) == ("r5",)


def test_k1_rung_is_first_ranked_at_first_attempt() -> None:
    ladder = _ladder()
    selected = rule.select_rungs(ladder, _bids(ladder))
    assert rule.k1_rung(selected) == selected[0] == "r0"
    assert rule.k1_rung(()) is None


def test_max_rungs_1_subset_is_lowest_p_yes() -> None:
    ladder = _ladder()
    assert rule.k1_rung(rule.select_rungs(ladder, _bids(ladder))) == "r0"


def test_hard_cancel_is_0900_lst_in_ns() -> None:
    day = dt.date(2026, 9, 20)
    assert rule.hard_cancel_ns(day, -8) == _ns(2026, 9, 20, 17)
    assert rule.hard_cancel_ns(day, -5) == _ns(2026, 9, 20, 14)


def test_gtd_expire_is_min_of_lst_permit_and_utc_midnight() -> None:
    now = _ns(2026, 9, 19, 18)
    hard = _ns(2026, 9, 20, 17)
    midnight = _ns(2026, 9, 20, 0)
    assert rule.gtd_expire_ns(now, hard, _ns(2026, 9, 20, 2, 50)) == midnight
    assert rule.gtd_expire_ns(now, hard, _ns(2026, 9, 19, 20)) == _ns(2026, 9, 19, 20)
    assert rule.gtd_expire_ns(now, _ns(2026, 9, 19, 19), _ns(2026, 9, 19, 20)) == _ns(
        2026, 9, 19, 19
    )


def test_gtd_midnight_cut_at_exact_midnight_rolls_forward() -> None:
    now = _ns(2026, 9, 20, 0)
    got = rule.gtd_expire_ns(now, _ns(2026, 9, 21, 17), _ns(2026, 9, 21, 2))
    assert got == _ns(2026, 9, 21, 0)


def test_obs_cancel_within_two_degrees_of_lower_edge() -> None:
    assert rule.obs_cancel(upper_f=78.0, lower_edge_f=80.0) is True
    assert rule.obs_cancel(upper_f=77.9, lower_edge_f=80.0) is False


def test_obs_cancel_integer_c_widens_by_1_8_f() -> None:
    assert rule.obs_cancel(upper_f=76.1, lower_edge_f=80.0, integer_c=True) is False
    assert rule.obs_cancel(upper_f=76.3, lower_edge_f=80.0, integer_c=True) is True


def test_listing_deadline_is_noon_utc_day_before() -> None:
    day = dt.date(2026, 9, 20)
    assert rule.listed_in_time(_ns(2026, 9, 19, 12), day) is True
    assert rule.listed_in_time(_ns(2026, 9, 19, 12, 1), day) is False
    assert rule.listed_in_time(None, day) is False
