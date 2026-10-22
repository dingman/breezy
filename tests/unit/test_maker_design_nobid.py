"""MAKER design driver (cards 1 and 2): config fence, arm table, rule override, day selection,
the Stage 0 positive-control comparison and the output writers. No capture, no NBP, no truth."""

from __future__ import annotations

import csv
import datetime as dt
import json
from pathlib import Path

import pytest

from breezy.analysis.maker_tape_census import CensusedDay
from scripts.analysis import maker_design_config as cfgm
from scripts.analysis import maker_design_nobid as nb
from scripts.analysis import maker_stage0_adapter as adapter
from scripts.analysis import maker_stage0_events_build as events_build
from scripts.analysis import maker_stage0_fill_pass as fill_pass
from scripts.analysis import maker_stage0_rule as rule
from scripts.analysis.maker_stage0_catalog_read import StationDayPlan
from scripts.analysis.maker_stage0_fill_events import BUYER, ForecastVector, Print

DAY = dt.date(2026, 10, 2)


def _raw(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "from": "2026-09-18",
        "to": "2026-10-13",
        "stations": ["LAX", "MDW", "MIA", "SFO"],
        "arms": ["control", "control_noabst", "nbp_deep", "spike_bid"],
        "theta": [0.0695, 0.08],
        "slip": [0.01, 0.02],
        "catalog_root": "~/cat",
        "nbp_root": "~/nbp",
        "census_days": "~/census.jsonl",
        "trade_unit": "~/unit.json",
        "truth": "~/truth.csv",
        "calibration": "~/cal.json",
        "calibration_sha256": "ab" * 32,
        "work_root": "~/.cache/breezy/maker_design_work/run1",
    }
    base.update(over)
    return base


@pytest.fixture(autouse=True)
def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))


def _census(
    station: str, day: dt.date, *, reason: str = "COVERED", bidlive: bool = True,
    first_seen_ns: int | None = 1,
) -> CensusedDay:  # fmt: skip
    return CensusedDay.from_dict(
        {
            "buyer_by_bucket": [0, 0, 0, 0], "buyer_by_bucket_bidlive": [0, 0, 0, 0],
            "climate_day": day.isoformat(), "covered_bidlive": bidlive,
            "coverage_fraction": 1.0, "firewall_class": "SEARCH_DECLARED",
            "first_seen_ns": first_seen_ns, "instances_clean": 1, "instances_corrupt_unread": 0,
            "instances_live_unread": 0, "longest_hole_min": 0, "n_prints": 0,
            "n_prints_bidlive": 0, "prints_no_aggressor": 0, "prints_seller": 0,
            "reason": reason, "rungs_with_qualifying_buyer": 0, "station": station,
            "tail_span_only": False,
        }
    )  # fmt: skip


# --- config and the read fence ---------------------------------------------------------------


def test_valid_config_parses_to_a_frozen_value_with_expanded_paths(tmp_path: Path) -> None:
    cfg = cfgm.parse_config(_raw())
    assert (cfg.day_from, cfg.day_to) == (dt.date(2026, 9, 18), dt.date(2026, 10, 13))
    assert cfg.stations == ("LAX", "MDW", "MIA", "SFO")
    assert cfg.arms == ("control", "control_noabst", "nbp_deep", "spike_bid")
    assert cfg.theta == (0.0695, 0.08)
    assert cfg.slip == (0.01, 0.02)
    assert cfg.catalog_root == tmp_path / "cat"
    assert cfg.reference is None
    assert cfg.plan_cache is None
    assert cfg.workers == 1
    with pytest.raises(AttributeError):
        cfg.arms = ()  # type: ignore[misc]


def test_load_config_reads_json_from_disk(tmp_path: Path) -> None:
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps(_raw()), encoding="utf-8")
    assert cfgm.load_config(path) == cfgm.parse_config(_raw())


@pytest.mark.parametrize(
    ("over", "match"),
    [
        ({"to": "2026-10-14"}, "fence"),  # the S2 second-look block starts here
        ({"to": "2026-11-01"}, "fence"),
        ({"from": "2026-10-05", "to": "2026-10-02"}, "empty"),
        ({"stations": ["LAX", "NYC"]}, "station"),  # NYC is not a maker station
        ({"stations": ["LAX", "BOS"]}, "station"),
        ({"stations": []}, "station"),
        ({"arms": ["control", "turbo"]}, "arm"),
        ({"arms": []}, "arm"),
        ({"theta": [0.0695, float("nan")]}, "theta"),
        ({"theta": []}, "theta"),
        ({"theta": [0.0695]}, "theta"),  # a base value and a stressed value are both required
        ({"slip": [0.01]}, "slip"),
        ({"slip": [-0.01]}, "slip"),
        ({"calibration_sha256": "xyz"}, "sha256"),
        ({"work_root": "~/.local/share/breezy/derived/maker_stage0/work"}, "work_root"),
        ({"work_root": "~/.cache/breezy/maker_design_work"}, "work_root"),  # must be a child
        ({"work_root": "~/.cache/breezy/maker_stage0_work/x"}, "work_root"),
        ({"workers": 0}, "workers"),
        ({"workers": 9}, "workers"),
        ({"workers": "two"}, "workers"),
        ({"plan_cache": "~/plans.json"}, "plan_cache"),  # a cache outside the design work base
        ({"plan_cache": "~/.cache/breezy/maker_design_work"}, "plan_cache"),
    ],
)
def test_config_refuses_anything_outside_the_fence(over: dict[str, object], match: str) -> None:
    with pytest.raises(cfgm.DesignRefused, match=match):
        cfgm.parse_config(_raw(**over))


def test_config_refuses_unknown_and_missing_keys() -> None:
    with pytest.raises(cfgm.DesignRefused, match="unknown"):
        cfgm.parse_config(_raw(extra=1))
    raw = _raw()
    del raw["slip"]
    with pytest.raises(cfgm.DesignRefused, match="slip"):
        cfgm.parse_config(raw)


def test_out_dir_must_be_a_fresh_child_of_the_design_root(tmp_path: Path) -> None:
    root = tmp_path / ".local/share/breezy/derived/replay/design"
    fresh = root / "maker_nobid"
    assert cfgm.check_out_dir(fresh) == fresh
    for bad in (
        tmp_path / "elsewhere",
        root,  # the shared root itself
        tmp_path / ".local/share/breezy/derived/maker_stage0/run",  # production Stage 0 outputs
        tmp_path / ".local/share/breezy/derived/replay/design/../replay_results.jsonl",
    ):
        with pytest.raises(cfgm.DesignRefused, match="out_dir"):
            cfgm.check_out_dir(bad)
    (root / "taken").mkdir(parents=True)
    (root / "taken" / "file").write_text("x", encoding="utf-8")
    with pytest.raises(cfgm.DesignRefused, match="not empty"):
        cfgm.check_out_dir(root / "taken")


# --- the arm table and the rule override ---------------------------------------------------


def test_arm_table_pins_the_card_parameters_and_the_shipped_control() -> None:
    control, noabst = cfgm.ARMS["control"], cfgm.ARMS["control_noabst"]
    assert (control.b_cap, control.max_rungs, control.abstain) == (rule.B_CAP, rule.MAX_RUNGS, True)
    assert (noabst.b_cap, noabst.max_rungs, noabst.abstain) == (rule.B_CAP, rule.MAX_RUNGS, False)
    deep = cfgm.ARMS["nbp_deep"]
    assert (deep.b_cap, deep.max_rungs, deep.abstain, deep.spike) == (0.84, 3, False, False)
    spike = cfgm.ARMS["spike_bid"]
    assert (spike.max_rungs, spike.abstain, spike.spike) == (rule.MAX_RUNGS, False, True)
    assert set(cfgm.ARMS) == {
        "control",
        "control_noabst",
        "nbp_deep",
        "spike_bid",
        "sharp",
        "sharp_cap84",
        "sharp_dp600",
        "sharp_dm600",
        "sharp_k1",
        "sharp_l1",
        "sharp_l5",
    }


def _bound() -> tuple[float, int, int, int]:
    return (
        rule.B_CAP,
        rule.MAX_RUNGS,
        adapter.MAX_RUNGS_PASSED,
        vars(events_build)["MAX_RUNGS_PASSED"],
    )


def test_override_rebinds_every_module_that_captured_the_constants_and_restores_them() -> None:
    shipped = _bound()
    with nb.rule_override(0.84, 3):
        assert _bound() == (0.84, 3, 3, 3)
        assert rule.b_max(0.99, 0.0695) == 0.84  # B_CAP is read at call time
        ladder = rule.ladder_plan(
            {f"r{i}": 0.01 for i in range(8)}, {f"r{i}": float(i) for i in range(8)}
        )
        assert len(ladder.select({f"r{i}": 0.8 for i in range(8)})) == 3
    assert _bound() == shipped
    assert rule.b_max(0.99, 0.0695) == 0.80


def test_override_restores_the_shipped_constants_after_an_exception() -> None:
    shipped = _bound()
    with pytest.raises(RuntimeError, match="boom"), nb.rule_override(0.84, 3):
        raise RuntimeError("boom")
    assert _bound() == shipped


def test_override_with_the_shipped_values_is_a_no_op() -> None:
    shipped = _bound()
    with nb.rule_override(rule.B_CAP, rule.MAX_RUNGS):
        assert _bound() == shipped


# --- day selection -------------------------------------------------------------------------


def test_selection_keeps_covered_bidlive_station_days_in_range_minus_the_sealed_day() -> None:
    census = {
        (s, d): _census(s, d)
        for s in ("LAX", "SFO")
        for d in (dt.date(2026, 9, 29), dt.date(2026, 9, 30), dt.date(2026, 10, 1), DAY)
    }
    census[("LAX", DAY)] = _census("LAX", DAY, reason="LONG_HOLE")
    census[("SFO", dt.date(2026, 9, 30))] = _census("SFO", dt.date(2026, 9, 30), bidlive=False)
    cfg = cfgm.parse_config(
        _raw(**{"from": "2026-09-30", "to": "2026-10-03", "stations": ["LAX", "SFO"]})
    )
    assert nb.select_station_days(cfg, census) == [
        ("LAX", dt.date(2026, 9, 30)),
        ("SFO", DAY),
    ]


def test_selection_orders_day_major_then_station_and_ignores_rows_beyond_the_fence() -> None:
    cfg = cfgm.parse_config(_raw(**{"from": "2026-10-12", "to": "2026-10-13"}))
    census = {
        (s, d): _census(s, d)
        for s in ("SFO", "LAX")
        for d in (dt.date(2026, 10, 12), dt.date(2026, 10, 13), dt.date(2026, 10, 14))
    }
    keys = nb.select_station_days(cfg, census)
    assert keys == [
        ("LAX", dt.date(2026, 10, 12)),
        ("SFO", dt.date(2026, 10, 12)),
        ("LAX", dt.date(2026, 10, 13)),
        ("SFO", dt.date(2026, 10, 13)),
    ]
    assert all(d <= dt.date(2026, 10, 13) for _, d in keys)


def test_listing_abstention_is_the_stage0_rule_on_the_census_first_seen_instant() -> None:
    deadline_ns = int(dt.datetime(2026, 10, 1, 12, 0, tzinfo=dt.UTC).timestamp()) * 10**9
    on_time = _census("LAX", DAY, first_seen_ns=deadline_ns)
    late = _census("LAX", DAY, first_seen_ns=deadline_ns + 1)
    never = _census("LAX", DAY, first_seen_ns=None)
    assert [nb.abstains(c) for c in (on_time, late, never)] == [False, True, True]


# --- the Stage 0 positive control ------------------------------------------------------------


def _sd(station: str, day: str, **over: object) -> dict[str, object]:
    row: dict[str, object] = {
        "station": station, "climate_day": day, "bid_bearing": True, "n_attempts": 3,
        "n_episodes": 2, "n_refused": 1, "rung_trials_posted": 2,
        "rung_trials_filled_base": 1, "rung_trials_filled_stress": 1,
    }  # fmt: skip
    row.update(over)
    return row


def _write_reference(path: Path, rows: list[dict[str, object]]) -> Path:
    cols = list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[*cols, "extra"])
        writer.writeheader()
        for row in rows:
            cells = {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in row.items()}
            writer.writerow({**cells, "extra": "ignored"})
    return path


def _scope(rows: list[dict[str, object]]) -> list[tuple[str, str]]:
    return [(str(r["station"]), str(r["climate_day"])) for r in rows]


def test_reference_comparison_is_empty_on_an_exact_match(tmp_path: Path) -> None:
    rows = [_sd("LAX", "2026-10-02"), _sd("MDW", "2026-10-02", bid_bearing=False, n_attempts=0)]
    ref = _write_reference(tmp_path / "ref.csv", rows)
    assert nb.compare_with_reference(rows, ref, _scope(rows)) == []


def test_reference_comparison_names_every_difference_and_every_missing_key(
    tmp_path: Path,
) -> None:
    ref_rows = [_sd("LAX", "2026-10-02"), _sd("MDW", "2026-10-02"), _sd("SFO", "2026-10-02")]
    ref = _write_reference(tmp_path / "ref.csv", ref_rows)
    mine = [_sd("LAX", "2026-10-02", rung_trials_filled_stress=0), _sd("MDW", "2026-10-02")]
    diffs = nb.compare_with_reference(mine, ref, _scope(ref_rows))
    assert any("LAX 2026-10-02" in d and "rung_trials_filled_stress" in d for d in diffs)
    assert any("SFO 2026-10-02" in d and "missing" in d for d in diffs)
    assert not any("MDW" in d for d in diffs)


def test_reference_comparison_ignores_keys_outside_the_scope_and_beyond_the_reference(
    tmp_path: Path,
) -> None:
    ref_rows = [_sd("LAX", "2026-10-02"), _sd("MDW", "2026-10-02")]
    ref = _write_reference(tmp_path / "ref.csv", ref_rows)
    mine = [_sd("LAX", "2026-10-02"), _sd("LAX", "2026-10-13")]
    scope = [("LAX", "2026-10-02"), ("LAX", "2026-10-13")]  # MDW not run; 10-13 not in Stage 0
    assert nb.compare_with_reference(mine, ref, scope) == []


def test_reference_comparison_flags_a_day_stage0_left_unreplayed(tmp_path: Path) -> None:
    ref_rows = [_sd("LAX", "2026-10-02", bid_bearing="", n_attempts="", n_episodes="")]
    ref = _write_reference(tmp_path / "ref.csv", ref_rows)
    diffs = nb.compare_with_reference([_sd("LAX", "2026-10-02")], ref, [("LAX", "2026-10-02")])
    assert any("bid_bearing" in d for d in diffs)


# --- output writers ------------------------------------------------------------------------


def test_station_day_row_flattens_a_summary_without_asdict() -> None:
    from scripts.analysis.maker_stage0_fill_events import StationDaySummary

    summary = StationDaySummary(
        station="LAX", climate_day="2026-10-02", unit_hypothesis="CONTRACTS", bid_bearing=True,
        guard_refused_only=False, n_attempts=4, n_episodes=2, n_refused=2, n_process_cuts=0,
        n_gtd_cuts=1, rung_trials_attempted=2, rung_trials_posted=2, rung_trials_filled_base=1,
        rung_trials_filled_stress=1, rungs_ever_posted=2, filled_pairs_base=1,
        filled_pairs_stress=1, k1_rung_id="r", k1_filled_base=1, k1_filled_stress=1,
        bid_median_fills_stress=0.8, delta_ns=0, truncation_refused_share=None,
        first_refusal_to_first_placement_s=None, process_live_h=10.0, forecast_valid_h=9.0,
        gap_h=0.0, covered_live_h=10.0, gap_share=0.0,
    )  # fmt: skip
    row = nb.station_day_row(summary, arm="nbp_deep", late_listed=False)
    assert list(row)[:3] == ["arm", "station", "climate_day"]
    assert row["arm"] == "nbp_deep"
    assert row["late_listed"] is False
    assert row["bid_bearing"] is True
    assert row["rung_trials_filled_stress"] == 1


def test_forecast_free_arms_get_an_empty_vector_in_force_from_the_given_instant() -> None:
    vector = nb.flat_vector(123)
    assert vector.available_at_ns == 123
    assert dict(vector.p_yes_point) == {}
    assert dict(vector.p_yes_upper) == {}


# --- the plan cache --------------------------------------------------------------------------


def test_plan_cache_defaults_to_none_and_is_expanded_when_given(tmp_path: Path) -> None:
    cfg = cfgm.parse_config(_raw(plan_cache="~/.cache/breezy/maker_design_work/plans/p.json"))
    assert cfg.plan_cache == tmp_path / ".cache/breezy/maker_design_work/plans/p.json"


def test_plan_cache_round_trips_station_day_plans_and_the_skip_record(tmp_path: Path) -> None:
    plans = {
        ("LAX", DAY): StationDayPlan(("a.POLYMARKET_US", "b.POLYMARKET_US"), ("i1", "i2"), 123),
        ("SFO", DAY): StationDayPlan(("c.POLYMARKET_US",), ("i2",), 0),
    }
    path = cfgm.write_plan_cache(tmp_path / "plans.json", plans, {"i3": "verdict CORRUPT"})
    assert cfgm.read_plan_cache(path) == (plans, {"i3": "verdict CORRUPT"})


def test_plan_cache_refuses_a_file_it_did_not_write(tmp_path: Path) -> None:
    path = tmp_path / "plans.json"
    path.write_text(json.dumps({"version": 99, "plans": {}, "skipped": {}}), encoding="utf-8")
    with pytest.raises(cfgm.DesignRefused, match="plan cache"):
        cfgm.read_plan_cache(path)
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(cfgm.DesignRefused, match="plan cache"):
        cfgm.read_plan_cache(path)


def test_workers_is_a_small_positive_integer_when_given() -> None:
    assert cfgm.parse_config(_raw(workers=2)).workers == 2


def test_sharp_arms_pin_the_card_parameters_and_never_bid_to_no_090() -> None:
    sharp, capped = cfgm.ARMS["sharp"], cfgm.ARMS["sharp_cap84"]
    assert (sharp.p_min, sharp.e_min, sharp.b_floor) == (0.97, 0.04, 0.75)
    assert (sharp.b_cap, sharp.max_rungs, sharp.abstain, sharp.spike) == (0.89, 2, False, False)
    assert (capped.p_min, capped.e_min, capped.b_floor) == (0.97, 0.04, 0.75)
    assert (capped.b_cap, capped.max_rungs, capped.abstain) == (0.84, 2, False)
    assert all(arm.b_cap < 0.90 for arm in cfgm.ARMS.values())


def test_config_accepts_the_sharp_arms() -> None:
    cfg = cfgm.parse_config(_raw(arms=["sharp", "sharp_cap84"]))
    assert cfg.arms == ("sharp", "sharp_cap84")


def test_override_rebinds_p_min_e_min_and_b_floor_and_restores_them() -> None:
    shipped = (rule.P_MIN, rule.E_MIN, rule.B_FLOOR)
    with nb.rule_override(0.89, 2, p_min=0.97, e_min=0.04, b_floor=0.75):
        assert (rule.P_MIN, rule.E_MIN, rule.B_FLOOR) == (0.97, 0.04, 0.75)
        assert rule.decide_bid(0.96, None, None, 0.0695).bid is None  # below the new P_MIN
        assert rule.decide_bid(0.999, None, None, 0.0695).bid == 0.89
        assert rule.decide_bid(0.999, 0.70, None, 0.0695).bid is None  # 0.71 < the new floor
    assert (rule.P_MIN, rule.E_MIN, rule.B_FLOOR) == shipped
    assert rule.decide_bid(0.96, None, None, 0.0695).bid is not None


def test_config_refuses_an_arm_whose_cap_could_bid_no_090_or_more(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    monkeypatch.setitem(cfgm.ARMS, "sharp", replace(cfgm.ARMS["sharp"], b_cap=0.90))
    with pytest.raises(cfgm.DesignRefused, match="0.90"):
        cfgm.parse_config(_raw(arms=["sharp"]))


def test_robustness_arms_are_sharp_with_a_bounded_clock_offset_or_one_rung() -> None:
    base = cfgm.ARMS["sharp"]
    assert base.delta_ns == 0
    for name, delta in (("sharp_dp600", 600 * 10**9), ("sharp_dm600", -600 * 10**9)):
        arm = cfgm.ARMS[name]
        assert arm.delta_ns == delta
        assert (arm.p_min, arm.e_min, arm.b_floor, arm.b_cap, arm.max_rungs) == (
            base.p_min, base.e_min, base.b_floor, base.b_cap, base.max_rungs,
        )  # fmt: skip
    k1 = cfgm.ARMS["sharp_k1"]
    assert k1.max_rungs == 1
    assert (k1.p_min, k1.e_min, k1.b_floor, k1.b_cap) == (0.97, 0.04, 0.75, 0.89)
    assert all(abs(a.delta_ns) <= 600 * 10**9 for a in cfgm.ARMS.values())  # S-7 bound


# --- placement latency -----------------------------------------------------------------------


_NS = 10**9
_T0 = _NS
_QUEUE_AHEAD = 9
_RUNG = "gte80f"


def _no_decide(_ctx: object) -> None:
    raise AssertionError("synthetic pass does not decide")


def _latency_pass() -> fill_pass.Pass:
    """One live episode, r=5. The print's NO price equals the bid, so the whole size leaves r."""
    sim = fill_pass.Pass(_no_decide, False, 0, 0, 2)  # type: ignore[arg-type]
    sim.live[_RUNG] = fill_pass.Live(
        rung_id=_RUNG,
        t0_ns=_T0,
        bid_cents=20,
        a_gt=0,
        a_eq=4,
        r=5,
        g=_QUEUE_AHEAD,
        depth_ts_used_ns=_T0,
        placed_vector=ForecastVector(0, {}, {}, 0, "", "none"),
    )
    return sim


def _buyer(sim: fill_pass.Pass, ts: int, size: int, instance: str = "") -> None:
    sim._on_print(Print(_RUNG, 80, size, BUYER, instance), ts)


def test_a_print_inside_latency_leaves_the_queue_and_a_later_print_fills() -> None:
    sim = _latency_pass()
    episode = sim.live[_RUNG]
    with nb.latency_override(_NS):
        _buyer(sim, _T0 + _NS, 10, "inst-during-L")  # ts == t0 + L is still inside
        assert (episode.r, episode.g) == (5, _QUEUE_AHEAD)
        assert sim.instance == "inst-during-L"
        assert sim.rests == []
        _buyer(sim, _T0 + _NS + 1, 3)
        assert episode.r == 2
        assert _RUNG in sim.live
        assert sim.rests == []
        _buyer(sim, _T0 + _NS + 2, 2)
    assert _RUNG not in sim.live
    assert [(rest.end_reason, rest.filled_ns) for rest in sim.rests] == [("FILLED", _T0 + _NS + 2)]


def test_zero_latency_matches_the_unwrapped_simulator() -> None:
    def consume(sim: fill_pass.Pass) -> None:
        episode = sim.live[_RUNG]
        _buyer(sim, _T0, 10, "at-t0")  # the simulator already ignores ts <= t0
        assert (episode.r, episode.g) == (5, _QUEUE_AHEAD)
        assert sim.instance == "at-t0"
        assert sim.rests == []
        _buyer(sim, _T0 + 1, 10)

    bare, wrapped = _latency_pass(), _latency_pass()
    consume(bare)
    with nb.latency_override(0):
        consume(wrapped)
    filled = [("FILLED", _T0 + 1)]
    assert [(rest.end_reason, rest.filled_ns) for rest in bare.rests] == filled
    assert [(rest.end_reason, rest.filled_ns) for rest in wrapped.rests] == filled
    assert bare.live == {} and wrapped.live == {}


def test_latency_override_restores_on_print_after_an_exception() -> None:
    original = fill_pass.Pass._on_print
    with pytest.raises(RuntimeError, match="boom"), nb.latency_override(_NS):
        assert fill_pass.Pass._on_print is not original
        raise RuntimeError("boom")
    assert fill_pass.Pass._on_print is original
    sim = _latency_pass()
    _buyer(sim, _T0 + 1, 10)
    assert [(rest.end_reason, rest.filled_ns) for rest in sim.rests] == [("FILLED", _T0 + 1)]


def test_latency_arms_match_sharp_except_latency_and_stay_under_the_no_ceiling() -> None:
    from dataclasses import replace

    base = cfgm.ARMS["sharp"]
    assert base.latency_ns == 0
    one, five = cfgm.ARMS["sharp_l1"], cfgm.ARMS["sharp_l5"]
    assert (one.latency_ns, five.latency_ns) == (_NS, 5 * _NS)
    assert replace(one, name="sharp", latency_ns=0) == base
    assert replace(five, name="sharp", latency_ns=0) == base
    assert all(
        arm.latency_ns == 0
        for name, arm in cfgm.ARMS.items()
        if name not in {"sharp_l1", "sharp_l5"}
    )
    assert cfgm.NO_BID_CEILING == 0.90
    assert all(arm.b_cap < cfgm.NO_BID_CEILING for arm in cfgm.ARMS.values())
    cfg = cfgm.parse_config(_raw(arms=["sharp", "sharp_l1", "sharp_l5"]))
    assert cfg.arms == ("sharp", "sharp_l1", "sharp_l5")
