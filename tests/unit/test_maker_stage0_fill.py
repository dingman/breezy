"""MAKER-S2 WP4 RED tests: the pure Stage 0 fill simulator (synthetic events only).

Plan: docs/plans/backlog/MAKER_2026-10-12/S2_stage0_replay_plan_r3.md WP4 (L148-172) + r4 delta.
Rule source: docs/strategies/SPEC_pm_us_no_ladder_maker_2026-10-12.md section 6.1 (:232-247).

Geometry: bid b = 78 cents (NO space). YES asks (21c x4, 22c x6, 25c x10) are NO bids
at 79 / 78 / 75, so A_gt = 4, A_eq = 6, Q0 = 4 + 6 + 1 = 11 and the stress Q0' = 22, G' = 8. A YES
BUYER print at YES price p has NO price 100 - p: p = 21 is strictly better than b, p >= 22 is at or
below b.
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from scripts.analysis import maker_stage0_fill as fill
from scripts.analysis import maker_stage0_fill_events as ev

SEC = 1_000_000_000
T = 1_000 * SEC
ASKS: tuple[ev.Level, ...] = ((21, 4), (22, 6), (25, 10))
BIDS: tuple[ev.Level, ...] = ((3, 10),)
BID = 78
Selector = Callable[[fill.DecisionContext], fill.Decision]


class Tape:
    def __init__(self) -> None:
        self._raw: list[ev.Event] = []

    @property
    def events(self) -> list[ev.Event]:
        """Canonical order: the simulator rejects unsorted input rather than sorting it."""
        return sorted(self._raw)

    def _add(self, ts: int, kind: ev.Kind, payload: ev.Payload) -> None:
        self._raw.append(ev.Event(ts, kind, len(self._raw), payload))

    def release(
        self, ts: int, p: float = 0.02, sha: str = "sha1", rungs: tuple[str, ...] = ("R1",)
    ) -> None:
        vec = ev.ForecastVector(
            available_at_ns=ts,
            p_yes_point={r: p for r in rungs},
            p_yes_upper={r: p + 0.02 for r in rungs},
            cycle_runtime_ns=ts - 5 * SEC,
            raw_sha256=sha,
            nbm_era="v5",
        )
        self._add(ts, ev.Kind.FORECAST_RELEASE, vec)

    def depth(
        self,
        ts: int,
        rung: str = "R1",
        asks: tuple[ev.Level, ...] = ASKS,
        bids: tuple[ev.Level, ...] = BIDS,
        asks_truncated: bool = False,
        bids_truncated: bool = False,
        instance: str = "i1",
        frame_ts: int | None = None,
    ) -> None:
        frame = ev.DepthFrame(
            rung_id=rung,
            ts_ns=ts if frame_ts is None else frame_ts,
            yes_bids=bids,
            yes_asks=asks,
            asks_truncated=asks_truncated,
            bids_truncated=bids_truncated,
            instance_id=instance,
        )
        self._add(ts, ev.Kind.DEPTH, frame)

    def buy(
        self,
        ts: int,
        price: int,
        size: int,
        rung: str = "R1",
        aggressor: str = ev.BUYER,
        instance: str = "i1",
    ) -> None:
        self._add(ts, ev.Kind.PRINT, ev.Print(rung, price, size, aggressor, instance))

    def gap(self, start: int, end: int, rung: str | None = None) -> None:
        self._add(start, ev.Kind.GAP_START, ev.GapMark(rung))
        self._add(end, ev.Kind.GAP_END, ev.GapMark(rung))

    def cut(self, ts: int, reason: str = "CANCEL_PROCESS", resume: bool = False) -> None:
        self._add(ts, ev.Kind.CANCEL, ev.Cut(reason, resume))


def fixed(bids: Mapping[str, int]) -> Selector:
    """Rank order = mapping order; abstains until a forecast vector is in force."""

    def select(ctx: fill.DecisionContext) -> fill.Decision:
        if ctx.vector is None:
            return fill.Decision()
        return fill.Decision(
            tuple(fill.Desired(r, b) for r, b in bids.items()), forecast_valid=True
        )

    return select


def base_tape() -> Tape:
    tape = Tape()
    tape.release(T)
    tape.depth(T + 10 * SEC)
    return tape


def run(
    tape: Tape,
    selector: Selector | None = None,
    delta: int = 0,
    live_from: int = T,
    max_rungs: int = 2,
) -> fill.StationDayResult:
    return fill.simulate_station_day(
        tape.events,
        selector or fixed({"R1": BID}),
        station="KSFO",
        climate_day="2026-10-10",
        unit_hypothesis="RESOLVED",
        live_from_ns=live_from,
        delta_ns=delta,
        max_rungs=max_rungs,
    )


def only(result: fill.StationDayResult) -> fill.Episode:
    assert len(result.episodes) == 1, result.episodes
    return result.episodes[0]


# ---- ordering, t0 and aggressor ------------------------------------------------------------------


def test_event_order_is_ts_then_priority_then_seq() -> None:
    tape = Tape()
    tape.buy(T, 22, 1)
    tape.cut(T)
    tape.depth(T)
    tape.release(T)
    tape.gap(T, T)
    kinds = [e.kind for e in sorted(tape.events)]
    assert kinds == sorted(kinds)
    assert (
        kinds[0] is ev.Kind.GAP_START and kinds[1] is ev.Kind.CANCEL and kinds[2] is ev.Kind.PRINT
    )


def test_equal_timestamp_cancel_precedes_print() -> None:
    tape = base_tape()
    tape.buy(T + 20 * SEC, 22, 11)  # would fill
    tape.cut(T + 20 * SEC)  # same instant: the cancel is processed first
    tape.depth(T + 30 * SEC)
    ep = only(run(tape))
    assert ep.end_reason == "CANCEL_PROCESS"
    assert ep.filled_ns_base is None and ep.filled_ns_stress is None


def test_print_at_t0_is_never_credited() -> None:
    tape = base_tape()
    tape.buy(T + 10 * SEC, 22, 50)  # same instant as the t0 frame
    tape.cut(T + 100 * SEC)
    ep = only(run(tape))
    assert ep.t0_ns == T + 10 * SEC
    assert ep.filled_ns_base is None


def test_yes_seller_print_never_counts() -> None:
    tape = base_tape()
    tape.buy(T + 20 * SEC, 22, 500, aggressor=ev.SELLER)
    tape.buy(T + 21 * SEC, 22, 500, aggressor=ev.NO_AGGRESSOR)
    tape.cut(T + 100 * SEC)
    assert only(run(tape)).filled_ns_base is None


# ---- price priority ------------------------------------------------------------------------------


def test_better_priced_buyer_print_reduces_q0() -> None:
    tape = base_tape()
    tape.buy(T + 20 * SEC, 21, 4)  # consumed the 4 better-priced NO bids: R 11 -> 7
    tape.buy(T + 21 * SEC, 22, 6)  # R 7 -> 1: not yet
    tape.buy(T + 22 * SEC, 22, 1)  # R 1 -> 0: filled
    tape.cut(T + 100 * SEC)
    ep = only(run(tape))
    assert ep.a_gt == 4 and ep.a_eq == 6
    assert ep.filled_ns_base == T + 22 * SEC


def test_print_at_or_below_b_consumes_remaining_q0() -> None:
    tape = base_tape()
    tape.buy(T + 20 * SEC, 30, 10)  # NO price 70 <= 78: R 11 -> 1
    tape.buy(T + 21 * SEC, 22, 1)
    tape.cut(T + 100 * SEC)
    assert only(run(tape)).filled_ns_base == T + 21 * SEC


def test_better_priced_reduction_capped_at_size_strictly_better() -> None:
    tape = base_tape()
    tape.buy(T + 20 * SEC, 21, 100)  # reduces R by min(100, G=4) only: R = 7
    tape.cut(T + 100 * SEC)
    assert only(run(tape)).filled_ns_base is None


def test_fill_when_own_unit_consumed() -> None:
    tape = Tape()
    tape.release(T)
    tape.depth(T + 10 * SEC, asks=((22, 5),))  # A_gt 0, A_eq 5, Q0 = 6
    tape.buy(T + 20 * SEC, 22, 5)
    tape.buy(T + 21 * SEC, 22, 1)
    tape.cut(T + 100 * SEC)
    ep = only(run(tape))
    assert ep.filled_ns_base == T + 21 * SEC


def test_stress_needs_twice_size_ahead_plus_one() -> None:
    tape = base_tape()
    tape.buy(T + 20 * SEC, 22, 11)  # base Q0 = 11 reached
    tape.buy(T + 21 * SEC, 22, 11)  # stress Q0' = 22 reached
    tape.cut(T + 100 * SEC)
    ep = only(run(tape))
    assert ep.filled_ns_base == T + 20 * SEC
    assert ep.filled_ns_stress == T + 21 * SEC


def test_stress_doubles_queue_ahead_plus_one() -> None:
    tape = base_tape()
    tape.buy(
        T + 20 * SEC, 21, 8
    )  # G' = 2*4 = 8 : stress R' 22 -> 14 (base: capped at 4, R 11 -> 7)
    tape.buy(T + 21 * SEC, 22, 13)  # stress R' 14 -> 1 (not filled); base R 7 -> -6 (filled)
    tape.buy(T + 22 * SEC, 22, 1)
    tape.cut(T + 100 * SEC)
    ep = only(run(tape))
    assert ep.filled_ns_base == T + 21 * SEC
    assert ep.filled_ns_stress == T + 22 * SEC


# ---- episode boundaries --------------------------------------------------------------------------


def test_replace_resets_queue() -> None:
    def select(ctx: fill.DecisionContext) -> fill.Decision:
        if ctx.vector is None:
            return fill.Decision()
        bid = BID if ctx.now_ns < T + 30 * SEC else BID - 1
        return fill.Decision((fill.Desired("R1", bid),), forecast_valid=True)

    tape = base_tape()
    tape.buy(T + 20 * SEC, 22, 10)  # R 11 -> 1 on the first episode
    tape.depth(T + 40 * SEC)  # new price: cancel-replace, new episode, queue reset
    tape.buy(T + 50 * SEC, 23, 1)  # NO price 77 <= 77 : consumes 1 of the fresh queue only
    tape.cut(T + 100 * SEC)
    first, second = run(tape, select).episodes
    assert first.end_reason == "REPLACED" and first.end_ns == T + 40 * SEC
    assert second.t0_ns == T + 40 * SEC and second.bid_cents == 77
    assert second.filled_ns_base is None


def test_process_cut_starts_new_episode_and_resets_queue() -> None:
    tape = base_tape()
    tape.buy(T + 20 * SEC, 22, 10)
    tape.cut(T + 30 * SEC, "CANCEL_PROCESS", resume=True)
    tape.depth(T + 30 * SEC)
    tape.buy(T + 40 * SEC, 22, 1)  # would fill the OLD queue
    tape.cut(T + 100 * SEC)
    first, second = run(tape).episodes
    assert first.end_reason == "CANCEL_PROCESS"
    assert second.t0_ns == T + 30 * SEC
    assert second.filled_ns_base is None


def test_utc_midnight_gtd_cut_starts_new_episode() -> None:
    tape = base_tape()
    tape.cut(T + 50 * SEC, "GTD_EXPIRY", resume=True)
    tape.depth(T + 50 * SEC)
    tape.cut(T + 100 * SEC)
    result = run(tape)
    first, second = result.episodes
    assert first.end_reason == "GTD_EXPIRY" and first.end_ns == T + 50 * SEC
    assert second.t0_ns == T + 50 * SEC  # re-posted at the same instant (r4 delta (i)10)
    assert result.summary.n_gtd_cuts == 1


def test_episode_ends_on_process_cut_and_gtd_cut() -> None:
    tape = base_tape()
    tape.cut(T + 50 * SEC, "GTD_EXPIRY", resume=True)
    tape.depth(T + 60 * SEC)
    tape.cut(T + 100 * SEC, "CANCEL_PROCESS", resume=False)
    tape.depth(T + 110 * SEC)  # after the stop: no decision, no episode
    result = run(tape)
    assert [e.end_reason for e in result.episodes] == ["GTD_EXPIRY", "CANCEL_PROCESS"]
    assert (result.summary.n_gtd_cuts, result.summary.n_process_cuts) == (1, 1)


def test_unfilled_episode_records_last_live_p() -> None:
    tape = base_tape()
    tape.buy(T + 15 * SEC, 30, 1)  # irrelevant consumption
    tape.release(T + 50 * SEC, p=0.03, sha="sha2")
    tape.depth(T + 60 * SEC)  # same price: the episode continues under the new vector
    tape.cut(T + 100 * SEC)
    ep = only(run(tape))
    assert ep.filled_ns_base is None
    assert ep.p_yes_point_live == 0.03 and ep.raw_sha256 == "sha2"
    assert ep.available_at_ns == T + 50 * SEC


def test_filled_episode_records_vector_in_force_at_fill() -> None:
    tape = base_tape()
    tape.buy(T + 20 * SEC, 22, 11)
    tape.release(T + 50 * SEC, p=0.03, sha="sha2")
    tape.depth(T + 60 * SEC)
    tape.cut(T + 100 * SEC)
    ep = only(run(tape))
    assert ep.p_yes_point_live == 0.02 and ep.raw_sha256 == "sha1"
    assert ep.depth_ts_used_ns == T + 10 * SEC


# ---- gaps and the marketability guard ------------------------------------------------------------


def test_gap_interval_is_subtracted_episode_continues() -> None:
    tape = base_tape()
    tape.gap(T + 20 * SEC, T + 120 * SEC)
    tape.buy(T + 60 * SEC, 22, 500)  # inside the gap: never credited
    tape.buy(T + 130 * SEC, 22, 11)  # after the gap: fills
    tape.cut(T + 200 * SEC)
    ep = only(run(tape))
    assert ep.gap_ns_subtracted == 100 * SEC
    assert ep.filled_ns_base == T + 130 * SEC


def test_gapped_frame_never_fills() -> None:
    tape = Tape()
    tape.depth(T + 5 * SEC)  # no vector yet: nothing placed before the gap
    tape.gap(T + 6 * SEC, T + 100 * SEC)
    tape.release(T + 7 * SEC)
    tape.release(T + 10 * SEC, sha="sha2")  # decision inside the gap on a frame the gap covers
    tape.buy(T + 20 * SEC, 22, 500)
    tape.cut(T + 200 * SEC)
    result = run(tape)
    assert all(e.filled_ns_base is None for e in result.episodes)
    assert [e.refused_reason for e in result.episodes] == ["STALE_FRAME", "STALE_FRAME"]


def test_stale_or_truncated_frame_refuses_episode() -> None:
    tape = Tape()
    tape.release(T)
    tape.depth(T + 10 * SEC, asks=((21, 4),), asks_truncated=True)  # level 22 beyond deepest ask
    tape.depth(T + 20 * SEC)  # fresh frame: the retry places
    tape.cut(T + 100 * SEC)
    refused, placed = run(tape).episodes
    assert refused.end_reason == "REFUSED" and refused.refused_reason == "TRUNCATED_FRAME"
    assert placed.refused_reason is None and placed.t0_ns == T + 20 * SEC


def test_frame_from_an_earlier_recorder_instance_refuses() -> None:
    tape = Tape()
    tape.depth(T + 5 * SEC, instance="i1")
    tape.buy(T + 6 * SEC, 99, 1, instance="i2")  # the recorder restarted: the frame predates it
    tape.release(T + 20 * SEC)  # decision instant
    tape.cut(T + 100 * SEC)
    refused = [e for e in run(tape).episodes if e.end_reason == "REFUSED"]
    assert [e.refused_reason for e in refused] == ["STALE_FRAME"]


def test_marketable_bid_is_refused() -> None:
    tape = Tape()
    tape.release(T)
    tape.depth(T + 10 * SEC, bids=((80, 5),))  # NO ask = 20 <= 78
    tape.cut(T + 100 * SEC)
    ep = only(run(tape))
    assert ep.refused_reason == "MARKETABLE"


# ---- clock ---------------------------------------------------------------------------------------


def test_clock_shift_delays_forecast_and_advances_cancels() -> None:
    tape = Tape()
    tape.release(T)
    tape.cut(T + 100 * SEC)
    shifted = ev.apply_clock_shift(tape.events, -20 * SEC)  # magnitude: sign is irrelevant
    by_kind = {e.kind: e.ts_ns for e in shifted}
    assert by_kind[ev.Kind.FORECAST_RELEASE] == T + 20 * SEC
    assert by_kind[ev.Kind.CANCEL] == T + 80 * SEC


def test_clock_shift_hides_a_vector_until_delta_after_release() -> None:
    tape = base_tape()  # release T, frame T+10
    tape.depth(T + 25 * SEC)
    tape.cut(T + 100 * SEC)
    ep = only(run(tape, delta=20 * SEC))
    # the vector is hidden until shifted release + 1 ns, then the decision uses the T+10 frame
    assert ep.t0_ns == T + 20 * SEC + 1 and ep.depth_ts_used_ns == T + 10 * SEC


def test_delta_is_per_instance_day_max_over_instances_and_over_10min_aborts_before_scoring_s7() -> (
    None
):
    samples = [
        ev.OffsetSample("i1", T + 1, -3 * SEC),
        ev.OffsetSample("i1", T + 2, 7 * SEC),
        ev.OffsetSample("i2", T + 3, 9 * SEC),
        ev.OffsetSample("i2", T + 10_000 * SEC, 900 * SEC),  # outside the process-live window
    ]
    window = (T, T + 1_000 * SEC)
    assert ev.instance_day_deltas(samples, *window) == {"i1": 7 * SEC, "i2": 9 * SEC}
    assert ev.station_day_delta_ns(samples, *window) == 9 * SEC
    assert ev.station_day_delta_ns([], *window) == 0
    scored: list[str] = []
    deltas = [3 * SEC, 601 * SEC]
    with pytest.raises(ev.DeltaBoundExceeded, match="S-7"):
        ev.assert_delta_within_bound(deltas)
        scored.append("scoring started")  # unreachable: the pre-pass aborts first
    assert scored == []
    assert ev.assert_delta_within_bound([600 * SEC, -5 * SEC]) == 600 * SEC


def test_leak_asserts_raise() -> None:
    ok = {
        "available_at_ns": 10,
        "delta_ns": 2,
        "t0_ns": 13,
        "depth_ts_used_ns": 13,
        "filled_ns": 14,
    }
    ev.assert_leak_free(**ok)
    for patch in ({"t0_ns": 12}, {"depth_ts_used_ns": 14}, {"filled_ns": 13}):
        with pytest.raises(ev.LeakageError):
            ev.assert_leak_free(**{**ok, **patch})


# ---- summary fields ------------------------------------------------------------------------------


def test_k1_rung_is_first_attempt_rung_held_for_day_with_stressed_pass() -> None:
    def select(ctx: fill.DecisionContext) -> fill.Decision:
        if ctx.vector is None:
            return fill.Decision()
        order = ("R2", "R1") if ctx.now_ns < T + 90 * SEC else ("R1", "R2")
        return fill.Decision(tuple(fill.Desired(r, BID) for r in order), forecast_valid=True)

    tape = Tape()
    tape.release(T, rungs=("R1", "R2"))
    tape.depth(T + 10 * SEC, rung="R1")
    tape.depth(T + 11 * SEC, rung="R2")
    tape.buy(T + 20 * SEC, 22, 11, rung="R2")  # base fills R2, stress does not
    tape.buy(T + 21 * SEC, 22, 22, rung="R1")  # fills R1 under both rules
    tape.depth(T + 100 * SEC, rung="R1")  # rank order has flipped by now
    tape.cut(T + 200 * SEC)
    s = run(tape, select).summary
    assert s.k1_rung_id == "R2"  # first-ranked at the first attempt, held for the day
    assert (s.k1_filled_base, s.k1_filled_stress) == (1, 0)
    assert (s.filled_pairs_base, s.filled_pairs_stress) == (2, 1)
    assert (s.rung_trials_posted, s.rung_trials_filled_base, s.rung_trials_filled_stress) == (
        2,
        2,
        1,
    )
    assert s.bid_median_fills_stress == 0.78


def test_bid_counts_and_median_none_without_fills() -> None:
    tape = base_tape()
    tape.cut(T + 100 * SEC)
    s = run(tape).summary
    assert s.bid_median_fills_stress is None and s.k1_filled_base == 0
    assert s.bid_bearing is True and s.guard_refused_only is False


def test_bid_bearing_counts_guard_refused_attempts() -> None:
    tape = Tape()
    tape.release(T)
    tape.depth(T + 10 * SEC, asks=((21, 4),), asks_truncated=True)
    tape.depth(T + 20 * SEC, asks=((21, 4),), asks_truncated=True)
    tape.cut(T + 100 * SEC)
    s = run(tape).summary
    assert s.bid_bearing is True and s.guard_refused_only is True
    assert (s.n_attempts, s.n_refused, s.n_episodes, s.rung_trials_posted) == (2, 2, 0, 0)
    assert s.rung_trials_attempted == 1
    assert s.k1_rung_id == "R1"


def test_no_attempt_is_not_bid_bearing() -> None:
    tape = Tape()
    tape.depth(T + 10 * SEC)  # no vector in force: the selector abstains
    tape.cut(T + 100 * SEC)
    s = run(tape).summary
    assert s.bid_bearing is False and s.guard_refused_only is False and s.k1_rung_id is None


def test_hours_fields_and_to_dict_carry_every_required_key() -> None:
    tape = base_tape()
    tape.gap(T + 100 * SEC, T + 700 * SEC)
    tape.cut(T + 3600 * SEC)
    s = run(tape).summary
    assert s.process_live_h == pytest.approx(1.0)
    assert s.gap_h == pytest.approx(600 / 3600)
    assert s.covered_live_h == pytest.approx(1.0 - 600 / 3600)
    assert 0 < s.forecast_valid_h <= s.process_live_h
    assert s.gap_share == pytest.approx(s.gap_h / s.forecast_valid_h)
    d = s.to_dict()
    required = {
        "n_attempts",
        "n_episodes",
        "n_refused",
        "n_process_cuts",
        "n_gtd_cuts",
        "rung_trials_posted",
        "rung_trials_filled_base",
        "rung_trials_filled_stress",
        "filled_pairs_base",
        "filled_pairs_stress",
        "k1_rung_id",
        "k1_filled_base",
        "k1_filled_stress",
        "bid_median_fills_stress",
        "delta_ns",
        "process_live_h",
        "forecast_valid_h",
        "gap_h",
        "covered_live_h",
        "gap_share",
        "bid_bearing",
        "guard_refused_only",
        "station",
        "climate_day",
        "unit_hypothesis",
    }
    assert required <= d.keys()
    assert run(tape, delta=5 * SEC).summary.delta_ns == 5 * SEC


def test_episode_to_dict_has_the_plan_record_fields() -> None:
    tape = base_tape()
    tape.cut(T + 100 * SEC)
    d = only(run(tape)).to_dict()
    for key in (
        "station",
        "climate_day",
        "rung_id",
        "t0_ns",
        "end_ns",
        "end_reason",
        "bid",
        "a_gt",
        "a_eq",
        "refused_reason",
        "filled_ns_base",
        "filled_ns_stress",
        "gap_ns_subtracted",
        "p_yes_point_live",
        "p_yes_upper_live",
        "cycle_runtime_ns",
        "raw_sha256",
        "nbm_era",
        "available_at_ns",
        "depth_ts_used_ns",
        "unit_hypothesis",
    ):
        assert key in d
    assert d["bid"] == 0.78


def test_unfinished_episode_closes_at_end_of_data() -> None:
    tape = base_tape()
    assert only(run(tape)).end_reason == "END_OF_DATA"


# ---- review fixes: truncation rule --------------------------------------------------------------


def test_truncated_asks_with_level_inside_displayed_range_place() -> None:
    tape = Tape()
    tape.release(T)
    tape.depth(T + 10 * SEC, asks_truncated=True)  # level 22 <= deepest displayed ask 25
    tape.cut(T + 100 * SEC)
    ep = only(run(tape))
    assert ep.refused_reason is None and (ep.a_gt, ep.a_eq) == (4, 6)


def test_truncated_asks_with_level_beyond_deepest_ask_refuse() -> None:
    tape = Tape()
    tape.release(T)
    tape.depth(T + 10 * SEC, asks=((21, 4),), asks_truncated=True)  # level 22 > 21
    tape.cut(T + 100 * SEC)
    assert only(run(tape)).refused_reason == "TRUNCATED_FRAME"


def test_bid_side_only_truncation_places() -> None:
    tape = Tape()
    tape.release(T)
    tape.depth(T + 10 * SEC, asks=((21, 4),), bids_truncated=True)
    tape.cut(T + 100 * SEC)
    assert only(run(tape)).refused_reason is None


def test_truncation_refused_share_and_first_refusal_to_first_placement() -> None:
    tape = Tape()
    tape.release(T)
    tape.depth(T + 10 * SEC, asks=((21, 4),), asks_truncated=True)
    tape.depth(T + 20 * SEC, asks=((21, 4),), asks_truncated=True)
    tape.depth(T + 30 * SEC)
    tape.cut(T + 100 * SEC)
    s = run(tape).summary
    assert s.n_attempts == 3 and s.truncation_refused_share == pytest.approx(2 / 3)
    assert s.first_refusal_to_first_placement_s == pytest.approx(20.0)


def test_truncation_fields_are_none_without_truncation_refusals() -> None:
    tape = base_tape()
    tape.cut(T + 100 * SEC)
    s = run(tape).summary
    assert s.truncation_refused_share == 0.0 and s.first_refusal_to_first_placement_s is None


# ---- review fixes: forecast release is a decision instant ----------------------------------------


def _cancel_when_p_high(ctx: fill.DecisionContext) -> fill.Decision:
    if ctx.vector is None:
        return fill.Decision()
    if ctx.vector.p_yes_point["R1"] > 0.05:
        return fill.Decision(dropped={"R1": ev.CANCEL_PMIN}, forecast_valid=True)
    return fill.Decision((fill.Desired("R1", BID),), forecast_valid=True)


def test_release_cancels_a_rest_before_a_later_print_can_fill_it() -> None:
    tape = base_tape()
    tape.release(T + 50 * SEC, p=0.30, sha="sha2")  # the new vector fails p_min
    tape.buy(T + 51 * SEC, 22, 500)  # no frame follows; would fill the surviving rest
    tape.cut(T + 100 * SEC)
    ep = only(run(tape, _cancel_when_p_high))
    assert ep.end_reason == ev.CANCEL_PMIN and ep.end_ns == T + 50 * SEC + 1
    assert ep.filled_ns_base is None and ep.filled_ns_stress is None


def test_clock_shift_emits_a_decide_event_one_ns_after_the_shifted_release() -> None:
    tape = Tape()
    tape.release(T)
    shifted = ev.apply_clock_shift(tape.events, 20 * SEC)
    decides = [e.ts_ns for e in shifted if e.kind is ev.Kind.DECIDE]
    assert decides == [T + 20 * SEC + 1]


def test_decision_with_no_vector_in_force_raises() -> None:
    tape = Tape()
    tape.depth(T + 10 * SEC)
    tape.cut(T + 100 * SEC)

    def eager(ctx: fill.DecisionContext) -> fill.Decision:
        return fill.Decision((fill.Desired("R1", BID),), forecast_valid=True)

    with pytest.raises(ev.LeakageError):
        run(tape, eager)


# ---- review fixes: stress rows carry stress fields -----------------------------------------------


def test_stress_row_has_its_own_end_fill_instant_and_vector() -> None:
    tape = base_tape()
    tape.buy(T + 20 * SEC, 22, 11)  # base fills
    tape.release(T + 50 * SEC, p=0.03, sha="sha2")
    tape.buy(T + 60 * SEC, 22, 11)  # stress fills later, under the newer vector
    tape.cut(T + 100 * SEC)
    ep = only(run(tape))
    assert (ep.filled_ns_base, ep.end_ns, ep.end_reason) == (T + 20 * SEC, T + 20 * SEC, "FILLED")
    assert ep.raw_sha256 == "sha1" and ep.p_yes_point_live == 0.02
    assert ep.filled_ns_stress == T + 60 * SEC and ep.end_ns_stress == T + 60 * SEC
    assert ep.end_reason_stress == "FILLED"
    assert ep.filled_ns_stress <= ep.end_ns_stress
    assert ep.raw_sha256_stress == "sha2" and ep.p_yes_point_live_stress == 0.03
    assert ep.available_at_ns_stress == T + 50 * SEC


def test_unfilled_stress_ends_at_its_own_cut() -> None:
    tape = base_tape()
    tape.buy(T + 20 * SEC, 22, 11)  # base fills only
    tape.cut(T + 100 * SEC)
    ep = only(run(tape))
    assert ep.filled_ns_stress is None
    assert (ep.end_ns_stress, ep.end_reason_stress) == (T + 100 * SEC, "CANCEL_PROCESS")


# ---- review fixes: real depth timestamps and leak asserts ----------------------------------------


def test_depth_ts_used_is_the_frame_ts_not_t0() -> None:
    tape = Tape()
    tape.depth(T + 5 * SEC)
    tape.release(T + 50 * SEC)  # the release decision uses the 45 s old frame
    tape.cut(T + 100 * SEC)
    ep = only(run(tape))
    assert ep.depth_ts_used_ns == T + 5 * SEC and ep.depth_ts_used_ns < ep.t0_ns


def test_frame_stamped_after_t0_raises_leakage_error() -> None:
    tape = Tape()
    tape.release(T)
    tape.depth(T + 10 * SEC, frame_ts=T + 99 * SEC)
    tape.cut(T + 100 * SEC)
    with pytest.raises(ev.LeakageError, match="depth"):
        run(tape)


# ---- review fixes: denominators, delta bound, caps -----------------------------------------------


def test_refused_only_rung_stays_in_the_attempted_denominator() -> None:
    def two(ctx: fill.DecisionContext) -> fill.Decision:
        if ctx.vector is None:
            return fill.Decision()
        return fill.Decision(
            (fill.Desired("R1", BID), fill.Desired("R2", BID)), forecast_valid=True
        )

    tape = Tape()
    tape.release(T, rungs=("R1", "R2"))
    tape.depth(T + 10 * SEC, rung="R1")
    tape.depth(T + 11 * SEC, rung="R2", asks=((21, 4),), asks_truncated=True)
    tape.cut(T + 100 * SEC)
    s = run(tape, two).summary
    assert (s.rung_trials_attempted, s.rung_trials_posted) == (2, 1)


def test_delta_above_the_s7_bound_raises_inside_the_simulator() -> None:
    tape = base_tape()
    with pytest.raises(ev.DeltaBoundExceeded):
        run(tape, delta=601 * SEC)
    run(tape, delta=600 * SEC)


def _three_rungs() -> Tape:
    tape = Tape()
    tape.release(T, rungs=("R1", "R2", "R3"))
    for i, rung in enumerate(("R1", "R2", "R3")):
        tape.depth(T + (10 + i) * SEC, rung=rung)
    tape.buy(T + 20 * SEC, 22, 11, rung="R1")  # R1 fills (base)
    tape.depth(T + 30 * SEC, rung="R1")
    tape.depth(T + 31 * SEC, rung="R2")
    tape.depth(T + 32 * SEC, rung="R3")
    tape.cut(T + 100 * SEC)
    return tape


def _backfilling(ctx: fill.DecisionContext) -> fill.Decision:
    if ctx.vector is None:
        return fill.Decision()
    ranked = tuple(fill.Desired(r, BID) for r in ("R1", "R2", "R3") if r not in ctx.held)
    return fill.Decision(ranked, forecast_valid=True)


def test_backfilling_selector_cannot_exceed_the_position_cap_in_either_pass() -> None:
    result = run(_three_rungs(), _backfilling, max_rungs=2)
    assert {e.rung_id for e in result.episodes} == {"R1", "R2"}
    assert result.summary.rungs_ever_posted == 2


def test_cap_is_a_parameter() -> None:
    result = run(_three_rungs(), _backfilling, max_rungs=3)
    assert {e.rung_id for e in result.episodes} == {"R1", "R2", "R3"}


def test_rungs_ever_posted_counts_rotation() -> None:
    def rotate(ctx: fill.DecisionContext) -> fill.Decision:
        if ctx.vector is None:
            return fill.Decision()
        if ctx.now_ns < T + 30 * SEC:
            return fill.Decision(
                (fill.Desired("R1", BID),), dropped={"R2": ev.CANCEL_PMIN}, forecast_valid=True
            )
        return fill.Decision(
            (fill.Desired("R2", BID),), dropped={"R1": ev.CANCEL_PMIN}, forecast_valid=True
        )

    tape = Tape()
    tape.release(T, rungs=("R1", "R2"))
    tape.depth(T + 10 * SEC, rung="R1")
    tape.depth(T + 11 * SEC, rung="R2")
    tape.depth(T + 40 * SEC, rung="R2")
    tape.cut(T + 100 * SEC)
    assert run(tape, rotate).summary.rungs_ever_posted == 2


# ---- review fixes: Decision shape ----------------------------------------------------------------


def test_decision_defaults_fail_closed() -> None:
    d = fill.Decision()
    assert d.forecast_valid is False and d.drop_reason is None and not d.dropped


def test_forecast_valid_default_does_not_accrue_valid_hours() -> None:
    def abstain(ctx: fill.DecisionContext) -> fill.Decision:
        return fill.Decision()

    tape = base_tape()
    tape.cut(T + 3600 * SEC)
    s = run(tape, abstain).summary
    assert s.forecast_valid_h == 0 and s.gap_share is None


def test_per_rung_drop_reasons_distinguish_stale_from_day_mismatch() -> None:
    def select(ctx: fill.DecisionContext) -> fill.Decision:
        if ctx.vector is None:
            return fill.Decision()
        if ctx.now_ns < T + 30 * SEC:
            return fill.Decision(
                (fill.Desired("R1", BID), fill.Desired("R2", BID)), forecast_valid=True
            )
        return fill.Decision(
            dropped={"R1": ev.CANCEL_STALE, "R2": ev.CANCEL_DAYMISMATCH}, forecast_valid=True
        )

    tape = Tape()
    tape.release(T, rungs=("R1", "R2"))
    tape.depth(T + 10 * SEC, rung="R1")
    tape.depth(T + 11 * SEC, rung="R2")
    tape.depth(T + 40 * SEC, rung="R1")
    tape.cut(T + 100 * SEC)
    reasons = {e.rung_id: e.end_reason for e in run(tape, select).episodes}
    assert reasons == {"R1": ev.CANCEL_STALE, "R2": ev.CANCEL_DAYMISMATCH}


def test_dropping_a_live_rung_without_a_reason_raises() -> None:
    def forgetful(ctx: fill.DecisionContext) -> fill.Decision:
        if ctx.vector is None:
            return fill.Decision()
        if ctx.now_ns < T + 30 * SEC:
            return fill.Decision((fill.Desired("R1", BID),), forecast_valid=True)
        return fill.Decision(forecast_valid=True)

    tape = base_tape()
    tape.depth(T + 40 * SEC)
    tape.cut(T + 100 * SEC)
    with pytest.raises(ValueError, match="reason"):
        run(tape, forgetful)


def test_unknown_drop_reason_and_duplicate_rungs_and_bad_bids_raise() -> None:
    tape = base_tape()
    tape.cut(T + 100 * SEC)

    def bad(d: fill.Decision) -> Selector:
        return lambda ctx: d if ctx.vector is not None else fill.Decision()

    dup = fill.Decision((fill.Desired("R1", BID), fill.Desired("R1", 70)), forecast_valid=True)
    out = fill.Decision((fill.Desired("R1", 100),), forecast_valid=True)
    for decision in (dup, out):
        with pytest.raises(ValueError):
            run(tape, bad(decision))
    with pytest.raises(ValueError, match="reason"):
        fill.Decision(dropped={"R1": "BOGUS"}, forecast_valid=True)


# ---- review fixes: integer queues, on-tick median ------------------------------------------------


def test_queue_arithmetic_is_exact_integer() -> None:
    tape = base_tape()
    tape.buy(T + 20 * SEC, 22, 10)  # R 11 -> 1
    tape.buy(T + 21 * SEC, 22, 1)  # R 1 -> 0 exactly
    tape.cut(T + 100 * SEC)
    ep = only(run(tape))
    assert ep.filled_ns_base == T + 21 * SEC
    assert isinstance(ep.a_gt, int) and isinstance(ep.a_eq, int)


def test_fractional_sizes_are_rejected_at_the_boundary() -> None:
    tape = base_tape()
    tape.buy(T + 20 * SEC, 22, 0.5)  # type: ignore[arg-type]
    with pytest.raises(ev.EventError, match="integer"):
        run(tape)


def test_bid_median_is_the_on_tick_lower_median() -> None:
    def two_bids(ctx: fill.DecisionContext) -> fill.Decision:
        if ctx.vector is None:
            return fill.Decision()
        return fill.Decision((fill.Desired("R1", 78), fill.Desired("R2", 77)), forecast_valid=True)

    tape = Tape()
    tape.release(T, rungs=("R1", "R2"))
    tape.depth(T + 10 * SEC, rung="R1")
    tape.depth(T + 11 * SEC, rung="R2")
    tape.buy(T + 20 * SEC, 30, 1000, rung="R1")
    tape.buy(T + 21 * SEC, 30, 1000, rung="R2")
    tape.cut(T + 100 * SEC)
    s = run(tape, two_bids).summary
    assert s.filled_pairs_stress == 2 and s.bid_median_fills_stress == 0.77


# ---- review fixes: validation, determinism, keyword-only records ---------------------------------


def test_unsorted_or_duplicate_events_are_rejected_with_a_reason() -> None:
    tape = base_tape()
    tape.cut(T + 100 * SEC)
    events = tape.events
    with pytest.raises(ev.EventError, match="out of order"):
        fill.simulate_station_day(
            events[::-1],
            fixed({"R1": BID}),
            station="K",
            climate_day="d",
            unit_hypothesis="RESOLVED",
            live_from_ns=T,
        )
    with pytest.raises(ev.EventError, match="duplicate"):
        fill.simulate_station_day(
            [events[0], events[0]],
            fixed({"R1": BID}),
            station="K",
            climate_day="d",
            unit_hypothesis="RESOLVED",
            live_from_ns=T,
        )


def test_same_events_twice_give_identical_results() -> None:
    tape = _three_rungs()
    assert run(tape, _backfilling) == run(tape, _backfilling)
    gen = fill.simulate_station_day(
        (e for e in tape.events),
        _backfilling,
        station="KSFO",
        climate_day="2026-10-10",
        unit_hypothesis="RESOLVED",
        live_from_ns=T,
    )
    assert gen == run(tape, _backfilling)


def test_records_are_keyword_only() -> None:
    with pytest.raises(TypeError):
        positional: Any = ev.Episode
        positional("KSFO", "d")
    with pytest.raises(TypeError):
        positional2: Any = ev.StationDaySummary
        positional2("KSFO", "d")


def test_filled_rung_stays_held_in_both_passes() -> None:
    tape = base_tape()
    tape.buy(T + 20 * SEC, 22, 11)  # base fills
    tape.buy(T + 21 * SEC, 22, 11)  # stress fills
    tape.depth(T + 30 * SEC)
    tape.cut(T + 40 * SEC, "GTD_EXPIRY", resume=True)
    tape.depth(T + 41 * SEC)
    tape.cut(T + 100 * SEC)
    result = run(tape)
    assert len(result.episodes) == 1  # no new episode after the fill, in either pass
    assert result.summary.rung_trials_posted == 1


def test_marketable_boundary_b_equal_to_no_ask() -> None:
    def placed(bids: tuple[ev.Level, ...]) -> bool:
        tape = Tape()
        tape.release(T)
        tape.depth(T + 10 * SEC, bids=bids)
        tape.cut(T + 100 * SEC)
        return only(run(tape)).refused_reason is None

    assert placed(((21, 5),)) is True  # NO ask 79 > b
    assert placed(((22, 5),)) is False  # NO ask 78 == b : marketable
    assert placed(((23, 5),)) is False  # NO ask 77 < b


def test_frame_at_gap_end_ts_is_still_stale_and_next_frame_places() -> None:
    tape = Tape()
    tape.release(T)
    tape.gap(T + 5 * SEC, T + 100 * SEC)
    tape.depth(T + 100 * SEC)  # DEPTH precedes GAP_END at an equal ts: still inside the gap
    tape.depth(T + 101 * SEC)
    tape.cut(T + 200 * SEC)
    first, second = run(tape).episodes
    assert first.refused_reason == "STALE_FRAME" and first.t0_ns == T + 100 * SEC
    assert second.refused_reason is None and second.t0_ns == T + 101 * SEC


def test_print_at_gap_end_ts_is_not_credited() -> None:
    tape = base_tape()
    tape.gap(T + 20 * SEC, T + 100 * SEC)
    tape.buy(T + 100 * SEC, 22, 500)  # inside the gap by event priority
    tape.buy(T + 101 * SEC, 22, 11)
    tape.cut(T + 200 * SEC)
    assert only(run(tape)).filled_ns_base == T + 101 * SEC


def test_overlapping_gaps_on_one_key_end_at_the_last_end() -> None:
    tape = base_tape()
    tape.gap(T + 20 * SEC, T + 60 * SEC)
    tape.gap(T + 30 * SEC, T + 100 * SEC)
    tape.buy(T + 70 * SEC, 22, 500)  # inside the second gap
    tape.buy(T + 110 * SEC, 22, 11)
    tape.cut(T + 200 * SEC)
    ep = only(run(tape))
    assert ep.filled_ns_base == T + 110 * SEC and ep.gap_ns_subtracted == 80 * SEC


def test_selector_cancel_runs_after_same_ts_print_is_credited() -> None:
    tape = base_tape()
    tape.release(T + 50 * SEC, p=0.30, sha="sha2")
    tape.buy(T + 50 * SEC + 1, 22, 11)  # same instant as the DECIDE: credited first
    tape.cut(T + 100 * SEC)
    ep = only(run(tape, _cancel_when_p_high))
    assert ep.filled_ns_base == T + 50 * SEC + 1


def test_empty_event_list_yields_an_empty_day() -> None:
    result = fill.simulate_station_day(
        [],
        fixed({"R1": BID}),
        station="K",
        climate_day="d",
        unit_hypothesis="RESOLVED",
        live_from_ns=T,
    )
    assert result.episodes == () and result.summary.bid_bearing is False


# ---- purity: the simulator never sees truth ------------------------------------------------------

REPO = Path(__file__).resolve().parents[2]
SIM_MODULES = (
    "scripts.analysis.maker_stage0_fill",
    "scripts.analysis.maker_stage0_fill_events",
    "scripts.analysis.maker_stage0_fill_pass",
)
FORBIDDEN = ("truth", "settlement")


def _resolve(node: ast.ImportFrom, package: str) -> str:
    """Absolute dotted base of an ``ImportFrom``, resolving relative levels against ``package``."""
    if node.level == 0:
        return node.module or ""
    parts = package.split(".")
    base = parts[: len(parts) - (node.level - 1)]
    return ".".join([*base, *([node.module] if node.module else [])])


def _imports(path: Path, package: str) -> list[str]:
    names: list[str] = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = _resolve(node, package)
            names.append(base)
            names += [f"{base}.{a.name}" for a in node.names]
    return names


def _module_path(name: str) -> Path | None:
    if not name.startswith(("scripts.", "breezy.")):
        return None
    root = REPO / "src" if name.startswith("breezy.") else REPO
    candidate = root.joinpath(*name.split("."))
    for p in (candidate.with_suffix(".py"), candidate / "__init__.py"):
        if p.exists():
            return p
    return None


def _package_of(name: str, path: Path) -> str:
    return name if path.name == "__init__.py" else name.rpartition(".")[0]


def _closure() -> set[str]:
    seen: set[str] = set()
    todo = list(SIM_MODULES)
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        parts = name.split(".")
        todo += [".".join(parts[:i]) for i in range(1, len(parts))]  # parent __init__ executes
        path = _module_path(name)
        if path is not None:
            todo += _imports(path, _package_of(name, path))
    return seen


def test_simulator_module_does_not_import_truth() -> None:
    for mod in SIM_MODULES:
        path = _module_path(mod)
        assert path is not None
        offenders = [
            n
            for n in _imports(path, _package_of(mod, path))
            if any(f in n.lower() for f in FORBIDDEN)
        ]
        assert offenders == [], offenders


def test_simulator_transitive_import_closure_excludes_truth() -> None:
    seen = _closure()
    assert "scripts.analysis.maker_stage0_fill_pass" in seen
    assert [n for n in seen if any(f in n.lower() for f in FORBIDDEN)] == []


def test_import_resolver_follows_relative_imports() -> None:
    node = ast.parse("from .truth_store import x").body[0]
    assert isinstance(node, ast.ImportFrom)
    assert _resolve(node, "scripts.analysis") == "scripts.analysis.truth_store"
    node = ast.parse("from .. import y").body[0]
    assert isinstance(node, ast.ImportFrom)
    assert _resolve(node, "scripts.analysis") == "scripts"
