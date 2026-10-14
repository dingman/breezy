"""MAKER-S2 WP6: the WP3 -> WP4 adapter (plan r4 delta (e)). Fixture store only; no real data."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.analysis import maker_stage0_adapter as ad
from scripts.analysis import maker_stage0_rule as rule
from scripts.analysis.maker_stage0_fill_events import (
    CANCEL_BFLOOR,
    CANCEL_DAYMISMATCH,
    CANCEL_PMIN,
    CANCEL_STALE,
    DROP_REASONS,
    NOT_YET_AVAILABLE,
    DecisionContext,
    DepthFrame,
    Desired,
)
from scripts.analysis.maker_stage0_pno import classify_p_no
from tests.unit import test_maker_stage0_pno as pno_fx

THETA = 0.0695
NS_H = 3_600 * 10**9
DAY = pno_fx.DAY
EDGES = {"lt80": float("-inf"), "r80": 80.0, "r82": 82.0, "r84": 84.0, "ge86": 86.0}
AFTER_19Z = pno_fx._ns(DAY, 0, 0) - 3 * NS_H  # 21:00Z on D-1: the 19Z vector is in force


def _frame(rung: str, *, ask: int = 25, bid: int = 15) -> DepthFrame:
    return DepthFrame(
        rung_id=rung, ts_ns=AFTER_19Z - 1, yes_bids=((bid, 10),), yes_asks=((ask, 10),)
    )


def _books(**over: DepthFrame) -> dict[str, DepthFrame]:
    out = {r: _frame(r) for r in EDGES}
    out.update(over)
    return out


def _selector(tmp_path: Path, *, delta_ns: int = 0, tracker: ad.WantTracker | None = None):  # type: ignore[no-untyped-def]
    root = pno_fx._build_root(tmp_path)
    store = pno_fx._store(root, day=DAY, stations=("SFO",))
    cfg = ad.SelectorConfig(
        store=store, station="SFO", day=DAY, stress="none", delta_ns=delta_ns, theta=THETA,
        lower_edges_f=EDGES,
    )  # fmt: skip
    return ad.build_selector(cfg, tracker), store


def _ctx(books: dict[str, DepthFrame], now: int = AFTER_19Z, **kw: object) -> DecisionContext:
    return DecisionContext(
        now_ns=now,
        vector=None,
        books=books,
        live_bids=dict(kw.get("live_bids", {})),  # type: ignore[call-overload]
        held=frozenset(kw.get("held", ())),  # type: ignore[call-overload]
    )


def test_adapter_maps_wp3_reasons_to_wp4_drop_reasons_and_passes_max_rungs() -> None:
    assert ad.drop_reason_for(rule.REASON_P_NO_BELOW_P_MIN) == CANCEL_PMIN
    assert ad.drop_reason_for(rule.REASON_B_MAX_BELOW_FLOOR) == CANCEL_BFLOOR
    assert ad.drop_reason_for(rule.REASON_BID_BELOW_FLOOR) == CANCEL_BFLOOR
    assert ad.drop_reason_for(rule.REASON_FORECAST_DAY_MISMATCH) == CANCEL_DAYMISMATCH
    assert ad.drop_reason_for(rule.REASON_FORECAST_STALE) == CANCEL_STALE
    assert ad.drop_reason_for(rule.REASON_FORECAST_NOT_YET_AVAILABLE) == NOT_YET_AVAILABLE
    assert set(ad.DROP_REASON_FOR.values()) <= DROP_REASONS
    every_wp3_reason = {value for name, value in vars(rule).items() if name.startswith("REASON_")}
    assert every_wp3_reason <= set(ad.DROP_REASON_FOR)
    assert ad.MAX_RUNGS_PASSED == rule.MAX_RUNGS
    with pytest.raises(ValueError, match="no drop reason"):
        ad.drop_reason_for("made_up_reason")


def test_selector_places_lowest_p_yes_rungs_first_at_best_no_bid_plus_one_cent(
    tmp_path: Path,
) -> None:
    selector, _ = _selector(tmp_path)
    decision = selector(_ctx(_books()))
    assert decision.forecast_valid is True
    # SFO 19Z vector: p_yes ge86 .0036 < r84 .0168 (both pass P_MIN); lt80 is modal, r80 adjacent.
    assert decision.desired == (Desired("ge86", 76), Desired("r84", 76))


def test_adapter_returns_invalid_decision_on_abstain(tmp_path: Path) -> None:
    selector, store = _selector(tmp_path)
    early = pno_fx._ns(DAY, 0, 0) - 20 * NS_H  # before any released vector
    assert not hasattr(classify_p_no(store, "SFO", DAY, early, stress="none"), "vector")
    decision = selector(_ctx(_books(), now=early, live_bids={"ge86": 76}))
    assert decision.desired == ()
    assert decision.forecast_valid is False
    assert decision.reason_for("ge86") == NOT_YET_AVAILABLE  # live rungs always get a reason


def test_stale_forecast_drops_live_rungs_with_cancel_stale(tmp_path: Path) -> None:
    selector, _ = _selector(tmp_path)
    late = pno_fx._ns(DAY, 0, 0) + 11 * NS_H  # > 8 h after the 02:04Z vector, no newer release
    decision = selector(_ctx(_books(), now=late, live_bids={"r84": 76}))
    assert decision.forecast_valid is False and decision.desired == ()
    assert decision.reason_for("r84") == CANCEL_STALE


def test_live_rung_below_p_min_or_bid_floor_is_dropped_with_mapped_reason(tmp_path: Path) -> None:
    selector, _ = _selector(tmp_path)
    squeezed = _frame("r84", ask=25, bid=35)  # no_ask 65 -> bid <= 64 < B_FLOOR
    decision = selector(_ctx(_books(r84=squeezed), live_bids={"r82": 76, "r84": 70, "ge86": 76}))
    assert decision.dropped["r82"] == CANCEL_PMIN  # p_yes .0601 -> p_no < .94
    assert decision.dropped["r84"] == CANCEL_BFLOOR
    assert [d.rung_id for d in decision.desired] == ["ge86"]


def test_live_rung_that_stays_individually_eligible_is_kept_when_outranked(tmp_path: Path) -> None:
    selector, _ = _selector(tmp_path)
    decision = selector(_ctx(_books(), live_bids={"r84": 76}, held=frozenset({"ge86"})))
    assert [d.rung_id for d in decision.desired] == ["r84"]  # held ge86 never re-bid


def test_held_rung_is_ineligible_but_still_counts_for_modal_adjacency(tmp_path: Path) -> None:
    selector, _ = _selector(tmp_path)
    decision = selector(_ctx(_books(), held=frozenset({"ge86", "r84"})))
    assert decision.desired == ()  # lt80 modal, r80 adjacent, r82 below P_MIN


def test_k1_rung_leads_the_desired_order(tmp_path: Path) -> None:
    selector, _ = _selector(tmp_path)
    decision = selector(_ctx(_books()))
    assert decision.desired[0].rung_id == rule.k1_rung(("ge86", "r84"))


def test_delta_shift_hides_a_vector_until_strictly_after_release_plus_delta(
    tmp_path: Path,
) -> None:
    delta = 5 * 60 * 10**9
    first_release = pno_fx._ns(DAY, 0) - 24 * NS_H + 14 * NS_H + 4 * 60 * 10**9  # 13Z cycle, 14:04Z
    selector, _ = _selector(tmp_path, delta_ns=delta)
    hidden = selector(_ctx(_books(), now=first_release + delta))
    visible = selector(_ctx(_books(), now=first_release + delta + 1))
    assert hidden.forecast_valid is False and hidden.desired == ()
    assert visible.forecast_valid is True and visible.desired


def test_wanted_rung_without_a_book_is_tracked_not_dropped(tmp_path: Path) -> None:
    tracker = ad.WantTracker()
    selector, _ = _selector(tmp_path, tracker=tracker)
    books = _books()
    del books["ge86"]
    decision = selector(_ctx(books))
    assert "ge86" in {d.rung_id for d in decision.desired}
    assert tracker.wanted_without_book == {"ge86"}


def test_book_helpers_read_best_no_bid_and_no_ask() -> None:
    frame = DepthFrame(
        rung_id="x", ts_ns=1, yes_bids=((10, 5), (15, 0), (12, 3)), yes_asks=((30, 4), (25, 2))
    )
    assert ad.best_no_bid(frame) == pytest.approx(0.75)
    assert ad.no_ask(frame) == pytest.approx(0.88)
    empty = DepthFrame(rung_id="x", ts_ns=1, yes_bids=(), yes_asks=())
    assert ad.best_no_bid(empty) is None and ad.no_ask(empty) is None
