"""EXEC-PAR BG-10(c): the pure simulation module behind the pre-registered section 5 outputs.

Pools of simulated days, stage trajectories sampled from them (vectorised), the Clopper-Pearson
plus burst halts, the level search, the viability decision, and the ICC report. A small end to
end run pins the JSON schema and that every pinned assumption is recorded.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
EXEC_PAR = REPO / "docs" / "evidence" / "exec_par"
NS = 10**9
HOUR = 3600 * NS
T0 = int(dt.datetime(2026, 9, 1, 12, tzinfo=dt.UTC).timestamp()) * NS


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def sim() -> ModuleType:
    sys.path.insert(0, str(EXEC_PAR))
    try:
        return _load("exec_par_bg10_sim_t", EXEC_PAR / "exec_par_bg10_sim.py")
    finally:
        sys.path.remove(str(EXEC_PAR))


@pytest.fixture(scope="module")
def st(sim: ModuleType) -> ModuleType:
    mod = sim.stats
    assert isinstance(mod, ModuleType)
    return mod


@pytest.fixture(scope="module")
def v2(sim: ModuleType) -> ModuleType:
    mod = sim.dhat
    assert isinstance(mod, ModuleType)
    return mod


def _pool(sim: ModuleType, m: list[int], mask: list[int], burst: list[int]) -> object:
    """A pool of one day type with len(m) draws."""
    arr = np.asarray
    return sim.PoolSet(
        m=arr([m], dtype=np.int64),
        a=arr([[(k).bit_count() for k in mask]], dtype=np.int64),
        mask=arr([mask], dtype=np.int64),
        burst=arr([burst], dtype=np.int64),
    )


# ------------------------------------------------------------------ ICC from the pre-window table
TSV_HEAD = "coid\tsubmit_ts\tside\tposted\toutcome\n"


def _write_orders(path: Path, rows: list[tuple[str, str, str]]) -> Path:
    body = "".join(
        f"c{i}\t{ts}\tYES\t{posted}\t{out}\n" for i, (ts, posted, out) in enumerate(rows)
    )
    path.write_text(TSV_HEAD + body)
    return path


def test_icc_groups_are_posted_orders_by_day_with_ambiguous_counts(
    sim: ModuleType, tmp_path: Path
) -> None:
    rows = [
        ("2026-09-05T20:19:49.0Z", "Y", "AMBIGUOUS"),
        ("2026-09-05T20:30:00.0Z", "Y", "FILL"),
        ("2026-09-05T21:30:00.0Z", "N", "DENIED_PRE_POST"),
        ("2026-09-06T17:03:46.0Z", "Y", "FILL"),
        ("2026-09-06T17:13:46.0Z", "Y", "AMBIGUOUS"),
        ("2026-09-06T17:23:46.0Z", "Y", "AMBIGUOUS"),
    ]
    groups = sim.icc_groups_from_orders(_write_orders(tmp_path / "o.tsv", rows))
    assert sorted(groups) == [(2, 1), (3, 2)]


def test_icc_groups_refuse_window_dated_orders(sim: ModuleType, tmp_path: Path) -> None:
    path = _write_orders(tmp_path / "o.tsv", [("2026-10-07T00:00:00.0Z", "Y", "FILL")])
    with pytest.raises(sim.dhat.WindowDataRefused):
        sim.icc_groups_from_orders(path)
    with pytest.raises(sim.dhat.WindowDataRefused):
        sim.icc_groups_from_orders(tmp_path / "orders-2026-10-09.tsv")


def test_icc_report_with_too_few_ambiguous_orders_uses_the_floor(sim: ModuleType) -> None:
    groups = [(3, 1), (2, 1), (4, 2), (5, 0), (4, 1), (2, 0), (6, 1)]  # 6 AMBIGUOUS
    out = sim.icc_report(groups, boot_runs=300, seed=5)
    assert out["n_ambiguous"] == 6
    assert out["too_few_ambiguous"] is True
    assert out["icc_used"] == 0.1
    assert out["min_ambiguous_for_meaningful_icc"] == sim.MIN_AMB_FOR_ICC
    assert set(out["instability"]) >= {"undefined_share", "used_p05", "used_p50", "used_p95"}
    assert out["estimate_raw"] == out["estimate_raw"]  # the estimate is still reported


def test_icc_report_with_enough_ambiguous_orders_uses_the_floored_estimate(
    sim: ModuleType,
) -> None:
    groups = [(5, 5), (5, 0), (5, 4), (5, 1), (5, 5), (5, 0), (5, 3), (5, 2)]  # 20 AMBIGUOUS
    out = sim.icc_report(groups, boot_runs=200, seed=5)
    assert out["n_ambiguous"] == 20 and out["too_few_ambiguous"] is False
    assert out["icc_used"] == pytest.approx(max(0.1, out["estimate_raw"]))
    assert out["icc_used"] > 0.1


def test_icc_report_is_seeded(sim: ModuleType) -> None:
    groups = [(3, 1), (2, 1), (4, 2), (5, 0), (4, 1), (2, 0), (6, 1)]
    assert sim.icc_report(groups, boot_runs=200, seed=1) == sim.icc_report(
        groups, boot_runs=200, seed=1
    )


# ------------------------------------------------------------------ pools
def _cands(v2: ModuleType, n: int) -> tuple[object, ...]:
    return tuple(
        v2.Candidate(T0 + i * 20 * NS, "SFO", f"wthr-high-sfo-2026-09-01-r{i}.POLYMARKET_US", 0.93)
        for i in range(n)
    )


def test_build_pool_records_entries_masks_and_bursts(sim: ModuleType, v2: ModuleType) -> None:
    arm = v2.Arm(k=2, p_amb=0.5, bucket=0.05, throttle=True, bound=True, free0=1.0)
    pool = sim.build_day_pool(_cands(v2, 12), arm, dt.date(2026, 9, 1), draws=60)
    assert pool.m.shape == pool.mask.shape == pool.a.shape == pool.burst.shape == (60,)
    assert (pool.m <= 12).all() and (pool.m >= 1).all()
    for m, a, mask, burst in zip(pool.m, pool.a, pool.mask, pool.burst, strict=True):
        assert int(mask).bit_count() == int(a)
        assert int(mask) >> int(m) == 0  # no bit beyond the admitted entries
        assert burst <= a


def test_build_pool_is_seeded_by_the_arm_seed(sim: ModuleType, v2: ModuleType) -> None:
    day = dt.date(2026, 9, 1)

    def pool(seed: int) -> Any:
        arm = v2.Arm(k=2, p_amb=0.4, bucket=0.05, free0=1.0, seed=seed)
        return sim.build_day_pool(_cands(v2, 12), arm, day, draws=80)

    a0, a0b, a1 = pool(0), pool(0), pool(1)
    assert (a0.mask == a0b.mask).all() and (a0.m == a0b.m).all()
    assert not (a0.mask == a1.mask).all()


def test_an_empty_day_pools_to_zero_entries(sim: ModuleType, v2: ModuleType) -> None:
    arm = v2.Arm(k=2, p_amb=0.4, bucket=0.05, free0=1.0)
    pool = sim.build_day_pool((), arm, dt.date(2026, 9, 1), draws=10)
    assert (pool.m == 0).all() and (pool.mask == 0).all() and (pool.burst == 0).all()


def test_burst_counts_ambiguous_within_sixty_minutes_of_arm_time(
    sim: ModuleType, v2: ModuleType
) -> None:
    arm = v2.Arm(k=8, p_amb=1.0, bucket=0.05, throttle=False, bound=False, free0=None)
    spread = tuple(
        v2.Candidate(
            T0 + i * 25 * 60 * NS, "SFO", f"wthr-high-sfo-2026-09-01-r{i}.POLYMARKET_US", 0.93
        )
        for i in range(6)
    )  # one candidate every 25 minutes: at most 3 inside a 60 minute span
    pool = sim.build_day_pool(spread, arm, dt.date(2026, 9, 1), draws=3)
    assert (pool.a == 6).all() and (pool.burst == 3).all()


# ------------------------------------------------------------------ stage trajectories
def _reference_halts(
    entries: list[int], masks: list[int], crit_alpha: float, p0: float, min_n: int, st: ModuleType
) -> int:
    """Scalar reference: the first day (1-based) the Clopper-Pearson rule fires, else 16."""
    n = x = 0
    for day, (m, mask) in enumerate(zip(entries, masks, strict=True), start=1):
        for j in range(m):
            n += 1
            x += (mask >> j) & 1
            if n >= min_n and st.clopper_pearson_lower(x, n, crit_alpha) > p0:
                return day
    return 16


def test_sample_stage_cp_day_matches_the_scalar_reference(sim: ModuleType, st: ModuleType) -> None:
    rng = np.random.default_rng(2)
    nd, draws = 5, 40
    m = rng.integers(0, 9, size=(nd, draws))
    mask = np.zeros((nd, draws), dtype=np.int64)
    for i in range(nd):
        for j in range(draws):
            mask[i, j] = sum(1 << b for b in range(int(m[i, j])) if rng.random() < 0.4)
    pools = sim.PoolSet(
        m=m,
        a=np.vectorize(lambda v: int(v).bit_count())(mask),
        mask=mask,
        burst=np.zeros_like(m),
    )
    crit = st.cp_critical_counts(15 * 9, 0.18, 0.01, min_n=20)
    sample = sim.sample_stage(pools, np.random.default_rng(9), runs=150, days=15, crit=crit)
    for r in range(150):
        want = _reference_halts(
            sample.entries[r].tolist(), sample.masks[r].tolist(), 0.01, 0.18, 20, st
        )
        assert sample.cp_day[r] == want


def test_sample_stage_amb_counts_equal_the_mask_popcount(sim: ModuleType, st: ModuleType) -> None:
    pools = _pool(sim, [6, 4, 5], [0b000111, 0b0101, 0b11111], [3, 2, 5])
    crit = st.cp_critical_counts(100, 0.18, 0.01, min_n=20)
    sample = sim.sample_stage(pools, np.random.default_rng(1), runs=50, days=15, crit=crit)
    pop = np.vectorize(lambda v: int(v).bit_count())(sample.masks)
    assert (sample.amb == pop).all()
    assert sample.entries.shape == (50, 15)


def test_burst_day_is_the_first_day_reaching_the_threshold(sim: ModuleType) -> None:
    bursts = np.array([[0, 2, 5, 1], [0, 0, 0, 0], [6, 0, 0, 0], [4, 4, 4, 4]])
    got5 = sim.burst_day(bursts, 5)
    got6 = sim.burst_day(bursts, 6)
    never = bursts.shape[1] + 1
    assert got5.tolist() == [3, never, 1, never]
    assert got6.tolist() == [never, never, 1, never]


def test_halt_day_is_the_earlier_of_cp_and_burst(sim: ModuleType) -> None:
    assert sim.halt_day(np.array([7, 3, 16]), np.array([5, 9, 16])).tolist() == [5, 3, 16]


def test_rate_within_counts_halts_inside_the_horizon(sim: ModuleType) -> None:
    days = np.array([1, 5, 6, 16, 16])
    assert sim.rate_within(days, 5, never=16) == pytest.approx(2 / 5)
    assert sim.rate_within(days, 15, never=16) == pytest.approx(3 / 5)


def test_promotion_with_no_halt_before_the_decision_day(sim: ModuleType) -> None:
    from types import SimpleNamespace

    batch = SimpleNamespace(
        first_look=np.array([8, 8, 8, 0]),
        first_pass=np.array([True, True, False, False]),
        promoted=np.array([True, True, True, False]),
    )
    halt = np.array([16, 8, 12, 1])
    # decision day: first look when it passed, else the cumulative re-look five days later
    got = sim.promoted_without_halt(batch, halt, never=16)
    assert got.tolist() == [True, False, False, False]
    late = np.array([16, 8, 14, 1])
    assert sim.promoted_without_halt(batch, late, never=16).tolist() == [True, False, True, False]


# ------------------------------------------------------------------ level search and viability
def test_find_level_brackets_and_bisects_a_monotone_function(sim: ModuleType) -> None:
    res = sim.find_level(
        lambda p: 0.1 + 0.5 * p, bar=0.30, grid=(0.3, 0.35, 0.4, 0.45, 0.5), tol=1e-4
    )
    assert res.root == pytest.approx(0.4, abs=2e-4)
    assert res.bracket[0] <= res.root <= res.bracket[1]
    assert [round(p, 2) for p, _ in res.table][:3] == [0.3, 0.35, 0.4]


def test_find_level_when_the_first_grid_point_already_fails(sim: ModuleType) -> None:
    res = sim.find_level(lambda p: 0.5, bar=0.30, grid=(0.3, 0.4), tol=1e-3)
    assert res.root is None and res.status == "below_grid"


def test_find_level_when_the_bar_is_never_reached(sim: ModuleType) -> None:
    res = sim.find_level(lambda p: 0.1, bar=0.30, grid=(0.3, 0.4), tol=1e-3)
    assert res.root is None and res.status == "above_grid"


def test_find_level_nan_is_a_failure_not_a_pass(sim: ModuleType) -> None:
    res = sim.find_level(lambda p: float("nan"), bar=0.30, grid=(0.3, 0.4), tol=1e-3)
    assert res.status == "below_grid"


def test_viability_passes_at_90_when_v3_holds(sim: ModuleType) -> None:
    out = sim.decide_viability(level=0.36, v2_90=0.86, v3_90=0.17, v2_95=None, v3_95=None)
    assert out["verdict"] == "VIABLE" and out["bound_in_force"] == 0.90


def test_viability_v2_failure_at_90_is_not_rescued_by_the_95_switch(sim: ModuleType) -> None:
    out = sim.decide_viability(level=0.36, v2_90=0.75, v3_90=0.10, v2_95=0.95, v3_95=0.02)
    assert out["verdict"] == "NOT-VIABLE" and out["bound_in_force"] == 0.90
    assert "V2" in " ".join(out["failed"])


def test_viability_switches_to_95_only_on_a_v3_failure(sim: ModuleType) -> None:
    ok = sim.decide_viability(level=0.36, v2_90=0.9, v3_90=0.25, v2_95=0.82, v3_95=0.12)
    assert ok["verdict"] == "VIABLE" and ok["bound_in_force"] == 0.95
    bad_v2 = sim.decide_viability(level=0.36, v2_90=0.9, v3_90=0.25, v2_95=0.79, v3_95=0.12)
    assert bad_v2["verdict"] == "NOT-VIABLE"
    bad_v3 = sim.decide_viability(level=0.36, v2_90=0.9, v3_90=0.25, v2_95=0.9, v3_95=0.21)
    assert bad_v3["verdict"] == "NOT-VIABLE"
    missing = sim.decide_viability(level=0.36, v2_90=0.9, v3_90=0.25, v2_95=None, v3_95=None)
    assert missing["verdict"] == "NOT-VIABLE"


def test_viability_v1_requires_a_level_of_at_least_0_33(sim: ModuleType) -> None:
    low = sim.decide_viability(level=0.329, v2_90=0.9, v3_90=0.1, v2_95=None, v3_95=None)
    assert low["verdict"] == "NOT-VIABLE" and low["v1_ok"] is False
    edge = sim.decide_viability(level=0.33, v2_90=0.9, v3_90=0.1, v2_95=None, v3_95=None)
    assert edge["v1_ok"] is True
    none = sim.decide_viability(level=None, v2_90=0.9, v3_90=0.1, v2_95=None, v3_95=None)
    assert none["verdict"] == "NOT-VIABLE"


def test_viability_thresholds_are_inclusive(sim: ModuleType) -> None:
    out = sim.decide_viability(level=0.33, v2_90=0.80, v3_90=0.20, v2_95=None, v3_95=None)
    assert out["verdict"] == "VIABLE"


# ------------------------------------------------------------------ end to end (tiny)
def _tiny_inputs(tmp_path: Path, v2: ModuleType) -> tuple[Path, Path]:
    days = {}
    for d in range(1, 13):
        day = dt.date(2026, 9, d)
        t0 = int(dt.datetime(day.year, day.month, day.day, 12, tzinfo=dt.UTC).timestamp()) * NS
        days[day.isoformat()] = [
            {
                "ts_ns": t0 + i * 30 * NS,
                "station": "SFO",
                "instrument_id": f"wthr-high-sfo-{day.isoformat()}-r{i}.POLYMARKET_US",
                "no_ask": "0.93",
            }
            for i in range(d % 4 + 3)
        ]
    cands = tmp_path / "cands.json"
    cands.write_text(json.dumps({"schema": 1, "days": days}))
    orders = _write_orders(
        tmp_path / "orders.tsv",
        [
            (f"2026-09-{d:02d}T17:00:00.0Z", "Y", "AMBIGUOUS" if d % 5 == 0 else "FILL")
            for d in range(1, 12)
            for _ in range(2)
        ],
    )
    return cands, orders


def test_end_to_end_tiny_run_records_every_pinned_assumption(
    sim: ModuleType, v2: ModuleType, tmp_path: Path
) -> None:
    cands, orders = _tiny_inputs(tmp_path, v2)
    out = tmp_path / "res.json"
    rc = sim.main(
        [
            "--cands", str(cands), "--orders", str(orders), "--out", str(out),
            "--draws", "30", "--runs", "400", "--workers", "1",
            "--level-draws", "20", "--level-resamples", "200", "--boot-runs", "100",
            "--level-grid", "0.33,0.6",
        ]
    )  # fmt: skip
    assert rc == 0
    res = json.loads(out.read_text())
    assert {"v1_level", "icc", "v2", "v3", "burst", "cp_burst", "pins", "viability"} <= set(res)
    pins = res["pins"]
    for key in (
        "entries_per_day",
        "intraday_entry_times",
        "icc_model",
        "seeds",
        "runs",
        "draws_per_day",
        "level_resamples",
        "k",
        "bucket",
        "bounds",
        "stage_rules",
    ):
        assert key in pins, key
    assert pins["seeds"] == list(v2.SEEDS)
    assert pins["k"] == 2
    assert res["burst"]["threshold_applied"] in (5, 6)
    assert set(res["burst"]["false_alarm_15d"]) == {"rho0.0", "rho0.1"}
    assert set(res["cp_burst"]["power_5d"]) >= {"p0.33", "p0.45"}
    assert res["viability"]["verdict"] in ("VIABLE", "NOT-VIABLE")
    assert "reference_at_level_0.33" in res["v2"] and "reference_at_level_0.33" in res["v3"]
    assert "sensitivity_icc_estimate" in res
    assert "passing_grid_points_above_root" in res["v1_level"]
    assert set(res["meta"]["scripts_sha256"]) == {
        "exec_parallel_dhat_v2.py",
        "exec_par_bg10_stats.py",
        "exec_par_bg10_sim.py",
    }


def test_main_refuses_window_inputs_before_any_work(
    sim: ModuleType, v2: ModuleType, tmp_path: Path
) -> None:
    cands, orders = _tiny_inputs(tmp_path, v2)
    bad = tmp_path / "cands-2026-10-09.json"
    bad.write_text(cands.read_text())
    out = tmp_path / "res.json"
    rc = sim.main(["--cands", str(bad), "--orders", str(orders), "--out", str(out)])
    assert rc == 2 and not out.exists()
    late = _write_orders(tmp_path / "late.tsv", [("2026-10-07T01:00:00.0Z", "Y", "FILL")])
    rc = sim.main(["--cands", str(cands), "--orders", str(late), "--out", str(out)])
    assert rc == 2 and not out.exists()
    rc = sim.main(
        [
            "--cands",
            str(cands),
            "--orders",
            str(orders),
            "--out",
            str(tmp_path / "r-2026-11-01.json"),
        ]
    )
    assert rc == 2
