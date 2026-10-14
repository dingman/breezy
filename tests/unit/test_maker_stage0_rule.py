"""RED-first tests for MAKER-S2 WP3, the pure spec v0.3 section 3 rule.

Source: `docs/strategies/SPEC_pm_us_no_ladder_maker_2026-10-12.md` lines 69-136 and
`docs/plans/backlog/MAKER_2026-10-12/S2_stage0_replay_plan_r3.md` WP3. No I/O.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Mapping
from pathlib import Path

import pytest

from scripts.analysis import maker_stage0_rule as rule

THETA = 0.0695
NS_H = 3_600 * 1_000_000_000
SPEC_PATH = (
    Path(__file__).resolve().parents[2] / "docs/strategies/SPEC_pm_us_no_ladder_maker_2026-10-12.md"
)
# A spec edit must fail loudly here: re-read the constants block, then re-pin.
SPEC_SHA256 = "7d154314165fbae8349272ed54160fd20a636405beb65d09efa1108d9e250136"


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


def test_constants_match_spec_text_and_pinned_sha() -> None:
    raw = SPEC_PATH.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SPEC_SHA256
    spec = raw.decode()
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
    assert res.reason == rule.REASON_B_MAX_BELOW_FLOOR
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
    assert res.reason == rule.REASON_BID_BELOW_FLOOR


def test_empty_no_bid_side_uses_no_ask_clamp_only() -> None:
    assert rule.bid_price(0.99, None, 0.78, THETA) == pytest.approx(0.77)


def test_empty_yes_bid_side_has_no_ask_clamp() -> None:
    assert rule.bid_price(0.99, 0.72, None, THETA) == pytest.approx(0.73)
    assert rule.bid_price(0.99, None, None, THETA) == pytest.approx(0.80)


def test_p_no_below_p_min_refused() -> None:
    res = rule.decide_bid(0.93, best_no_bid=0.75, no_ask=0.90, theta=THETA)
    assert res.bid is None
    assert res.reason == rule.REASON_P_NO_BELOW_P_MIN


@pytest.mark.parametrize("bad", [float("nan"), -0.1, 1.1])
def test_invalid_p_no_is_rejected(bad: float) -> None:
    with pytest.raises(ValueError):
        rule.decide_bid(bad, best_no_bid=0.75, no_ask=0.90, theta=THETA)


def test_p_no_exactly_p_min_is_accepted_and_just_below_refused() -> None:
    assert rule.decide_bid(0.94, best_no_bid=0.75, no_ask=0.90, theta=THETA).bid == 0.76
    res = rule.decide_bid(0.9399, best_no_bid=0.75, no_ask=0.90, theta=THETA)
    assert res.reason == rule.REASON_P_NO_BELOW_P_MIN


def test_bid_exactly_at_floor_accepted_and_one_cent_below_refused() -> None:
    assert rule.decide_bid(0.99, 0.69, None, THETA).bid == pytest.approx(0.70)
    res = rule.decide_bid(0.99, 0.68, None, THETA)
    assert (res.bid, res.reason) == (None, rule.REASON_BID_BELOW_FLOOR)


def test_b_max_equal_to_b_floor_is_kept_and_below_is_none() -> None:
    assert rule.b_max(0.80, 0.0) == pytest.approx(0.70)
    assert rule.b_max(0.7999, 0.0) is None
    # theta 0.65 at p_no 0.94: 0.70 fits (0.8365 <= 0.84), 0.71 does not.
    assert rule.b_max(0.94, 0.65) == pytest.approx(0.70)
    assert rule.decide_bid(0.94, None, None, 0.65).bid == pytest.approx(0.70)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.0695])
def test_invalid_theta_is_rejected(bad: float) -> None:
    with pytest.raises(ValueError, match="theta"):
        rule.b_max(0.99, bad)
    with pytest.raises(ValueError, match="theta"):
        rule.decide_bid(0.99, 0.75, 0.90, bad)


def test_zero_theta_is_valid() -> None:
    assert rule.b_max(0.99, 0.0) == 0.80


def test_negative_forecast_age_is_not_fresh() -> None:
    day = dt.date(2026, 9, 20)
    assert rule.forecast_gate(day, day, -1) == rule.REASON_FORECAST_NOT_YET_AVAILABLE
    assert rule.forecast_gate(dt.date(2026, 9, 21), day, -1) == rule.REASON_FORECAST_DAY_MISMATCH


def test_reason_constants_are_distinct_strings() -> None:
    reasons = {
        rule.REASON_P_NO_BELOW_P_MIN,
        rule.REASON_B_MAX_BELOW_FLOOR,
        rule.REASON_BID_BELOW_FLOOR,
        rule.REASON_FORECAST_DAY_MISMATCH,
        rule.REASON_FORECAST_STALE,
        rule.REASON_FORECAST_NOT_YET_AVAILABLE,
    }
    assert len(reasons) == 6
    assert all(isinstance(r, str) and r for r in reasons)


def test_stale_forecast_no_attempt() -> None:
    day = dt.date(2026, 9, 20)
    assert rule.forecast_gate(day, day, 8 * NS_H + 1) == rule.REASON_FORECAST_STALE
    assert rule.forecast_gate(day, day, 8 * NS_H) is None
    assert rule.forecast_gate(day, day, 0) is None


def test_forecast_for_another_day_abstains() -> None:
    day = dt.date(2026, 9, 20)
    assert rule.forecast_gate(dt.date(2026, 9, 21), day, 0) == rule.REASON_FORECAST_DAY_MISMATCH
    assert rule.forecast_gate(None, day, 0) == rule.REASON_FORECAST_DAY_MISMATCH


def _ladder() -> dict[str, float]:
    # ascending rung order; modal is r3 (p_yes 0.50)
    return {"r0": 0.01, "r1": 0.03, "r2": 0.20, "r3": 0.50, "r4": 0.20, "r5": 0.04, "r6": 0.02}


def _bids(ladder: Mapping[str, float]) -> dict[str, float | None]:
    return dict.fromkeys(ladder, 0.75)


def _edges(ladder: Mapping[str, float]) -> dict[str, float]:
    # Lower edge of the i-th key's rung, 2 F apart, in the mapping's own order.
    return {rung: 60.0 + 2.0 * i for i, rung in enumerate(ladder)}


def _select(
    ladder: Mapping[str, float],
    bids: Mapping[str, float | None] | None = None,
    edges: Mapping[str, float] | None = None,
) -> tuple[str, ...]:
    return rule.select_rungs(
        ladder,
        _bids(ladder) if bids is None else bids,
        lower_edges_f=_edges(ladder) if edges is None else edges,
    )


def test_select_rungs_ranks_lowest_p_yes_non_modal_non_adjacent() -> None:
    # r2,r4 adjacent to modal; r3 modal. Eligible: r0 .01 r1 .03 r5 .04 r6 .02
    assert _select(_ladder()) == ("r0", "r6")


def test_two_rung_bound_and_modal_adjacency() -> None:
    got = _select(_ladder())
    assert len(got) <= rule.MAX_RUNGS
    assert not {"r2", "r3", "r4"} & set(got)


def test_select_rungs_skips_p_yes_failing_p_min() -> None:
    ladder = {"a": 0.07, "b": 0.50, "c": 0.30, "d": 0.20, "e": 0.03}
    # a: p_no .93 fails; modal b, adjacent a,c excluded; d .20 fails; e .03 passes.
    assert _select(ladder) == ("e",)


def test_select_rungs_requires_bid_at_floor() -> None:
    ladder = _ladder()
    bids = _bids(ladder)
    bids["r0"] = None
    bids["r6"] = 0.69
    assert _select(ladder, bids) == ("r1", "r5")


def test_no_rung_passes_p_min_returns_empty() -> None:
    ladder = {"a": 0.30, "b": 0.40, "c": 0.30}
    assert _select(ladder) == ()
    assert _select({}, {}, {}) == ()


def test_select_rungs_missing_bid_entry_is_ineligible() -> None:
    assert _select(_ladder(), {"r5": 0.75}) == ("r5",)


def test_k1_rung_is_first_ranked_selected_rung() -> None:
    selected = _select(_ladder())
    assert rule.k1_rung(selected) == selected[0] == "r0"
    assert rule.k1_rung(()) is None


def test_select_rungs_is_deterministic_and_insertion_order_independent() -> None:
    ladder = _ladder()
    first = _select(ladder)
    assert _select(ladder) == first
    reversed_ladder = dict(reversed(list(ladder.items())))
    assert _select(reversed_ladder, edges=_edges(ladder)) == first
    assert rule.k1_rung(_select(reversed_ladder, edges=_edges(ladder))) == rule.k1_rung(first)


def test_select_rungs_orders_by_lower_edge_not_key_text() -> None:
    # Keys are not alphabetical; adjacency must follow the edges.
    ladder = {"z": 0.01, "y": 0.50, "x": 0.02, "w": 0.03}
    edges = {"z": 60.0, "y": 62.0, "x": 64.0, "w": 66.0}
    # modal y; z and x adjacent; only w eligible.
    assert _select(ladder, edges=edges) == ("w",)


@pytest.mark.parametrize(
    "edges",
    [
        {"r0": 60.0, "r1": 60.0, "r2": 64.0},  # duplicate edge
        {"r0": 60.0, "r1": float("nan"), "r2": 64.0},  # NaN edge
        {"r0": 60.0, "r1": 62.0},  # key missing
        {"r0": 60.0, "r1": 62.0, "r2": 64.0, "r9": 66.0},  # extra key
    ],
)
def test_select_rungs_rejects_unorderable_ladder(edges: dict[str, float]) -> None:
    ladder = {"r0": 0.01, "r1": 0.50, "r2": 0.02}
    with pytest.raises(ValueError, match="lower_edges_f"):
        rule.select_rungs(ladder, _bids(ladder), lower_edges_f=edges)


def test_select_rungs_modal_at_first_index() -> None:
    ladder = {"r0": 0.50, "r1": 0.20, "r2": 0.01, "r3": 0.02}
    assert _select(ladder) == ("r2", "r3")


def test_select_rungs_modal_at_last_index() -> None:
    ladder = {"r0": 0.01, "r1": 0.02, "r2": 0.20, "r3": 0.50}
    assert _select(ladder) == ("r0", "r1")


def test_select_rungs_modal_tie_first_index_wins() -> None:
    ladder = {"r0": 0.01, "r1": 0.50, "r2": 0.02, "r3": 0.03, "r4": 0.50, "r5": 0.04}
    # modal = r1 (first): r0,r1,r2 excluded -> r3 .03, r5 .04. (Last-wins would give r0,r2.)
    assert _select(ladder) == ("r3", "r5")


def test_select_rungs_equal_p_yes_tie_breaks_by_ladder_index() -> None:
    ladder = {"r0": 0.02, "r1": 0.02, "r2": 0.02, "r3": 0.02, "r4": 0.90}
    assert _select(ladder) == ("r0", "r1")


def test_select_rungs_p_yes_exactly_at_p_min_boundary() -> None:
    at = {"m": 0.90, "n": 0.05, "x": 0.06}
    assert _select(at) == ("x",)  # p_no == 0.94 passes (n is modal-adjacent)
    over = {"m": 0.90, "n": 0.05, "x": 0.0600000001}
    assert _select(over) == ()


def test_select_rungs_bid_exactly_at_floor_is_eligible() -> None:
    ladder = {"m": 0.90, "n": 0.05, "x": 0.01}
    assert _select(ladder, {"x": 0.70}) == ("x",)
    assert _select(ladder, {"x": 0.69}) == ()


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.1, 1.1])
def test_select_rungs_rejects_invalid_p_yes(bad: float) -> None:
    ladder = {"a": 0.01, "b": 0.50, "c": 0.02, "d": bad}
    with pytest.raises(ValueError, match="p_yes"):
        _select(ladder)


def test_selected_rung_is_never_refused_for_p_min() -> None:
    # M4: select_rungs and decide_bid share one P_MIN comparison.
    grid = [i / 1000 for i in range(101)] + [0.0600000000005, 0.0599999999995, 0.06]
    for p_yes in grid:
        ladder = {"m": 0.90, "n": 0.05, "x": p_yes}
        if "x" in _select(ladder):
            res = rule.decide_bid(1.0 - p_yes, best_no_bid=0.75, no_ask=0.90, theta=THETA)
            assert res.reason != rule.REASON_P_NO_BELOW_P_MIN, p_yes


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
