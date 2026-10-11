"""EXEC-PAR BG-10(d)/(e): the v2 dhat script (resampling controls, 3 seeds, rho = 0.1 arm).

The WP0 script is hash-pinned and stays byte-identical; v2 is a copy that is extended.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import math
import random
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "docs" / "evidence" / "exec_par" / "exec_parallel_dhat_v2.py"
NS = 10**9
DAY = dt.date(2026, 9, 1)
T0 = int(dt.datetime(2026, 9, 1, 12, tzinfo=dt.UTC).timestamp()) * NS


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("exec_parallel_dhat_v2_t", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["exec_parallel_dhat_v2_t"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def v2() -> ModuleType:
    return _load()


def _cands(v2: ModuleType, n: int, step_s: float = 0.2) -> tuple[Any, ...]:
    return tuple(
        v2.Candidate(
            ts_ns=T0 + int(i * step_s * NS),
            station="SFO",
            instrument_id=f"wthr-high-sfo-2026-09-01-r{i}.POLYMARKET_US",
            no_ask=0.93,
        )
        for i in range(n)
    )


def _arm(v2: ModuleType, **kw: object) -> object:
    base: dict[str, object] = {"k": 3, "p_amb": 0.33, "bucket": 0.05, "stuck": 1}
    base.update(kw)
    return v2.Arm(**base)


# --------------------------------------------------------------------------- (d) resampling
def test_resamples_default_to_at_least_20000_and_are_configurable(v2: ModuleType) -> None:
    assert v2.RESAMPLES >= 20_000
    assert v2.parse_args([]).resamples == v2.RESAMPLES
    assert v2.parse_args(["--resamples", "500"]).resamples == 500
    with pytest.raises(SystemExit):
        v2.parse_args(["--resamples", "0"])


def test_three_distinct_seeds_vary_both_the_bootstrap_seed_and_the_draw_string(
    v2: ModuleType,
) -> None:
    assert len(v2.SEEDS) == 3 and len(set(v2.SEEDS)) == 3
    boots = [v2.boot_seed(s) for s in v2.SEEDS]
    assert len(set(boots)) == 3  # BOOT_SEED varies with the seed
    arms = [_arm(v2, seed=s) for s in v2.SEEDS]
    strings = [v2.draw_seed_string(a, DAY) for a in arms]
    assert len(set(strings)) == 3  # the draw-seed string varies with the seed
    assert all(str(DAY) in s and s.startswith("wp0|") for s in strings)


def test_seed_independence_different_seeds_give_different_draws(v2: ModuleType) -> None:
    cands = _cands(v2, 12)
    stats = [v2.day_stats(cands, _arm(v2, seed=s), DAY, draws=400) for s in v2.SEEDS]
    assert len({st.dhat for st in stats}) == 3
    again = v2.day_stats(cands, _arm(v2, seed=v2.SEEDS[1]), DAY, draws=400)
    assert again == stats[1]  # the same seed reproduces exactly


def test_the_draw_seed_ignores_k_bucket_and_free_arm_for_common_random_numbers(
    v2: ModuleType,
) -> None:
    a = v2.draw_seed_string(_arm(v2, k=3, bucket=0.05, free_arm="A", seed=1), DAY)
    b = v2.draw_seed_string(_arm(v2, k=6, bucket=0.10, free_arm="B", seed=1), DAY)
    assert a == b


def test_bootstrap_seed_changes_the_interval_and_same_seed_repeats(v2: ModuleType) -> None:
    values = [(i * 37 % 101) / 101 for i in range(30)]
    s0, s1 = (v2.boot_seed(s) for s in v2.SEEDS[:2])
    first = v2.cluster_bootstrap_ci(values, 0.9, resamples=300, seed=s0)
    assert first == v2.cluster_bootstrap_ci(values, 0.9, resamples=300, seed=s0)
    assert first != v2.cluster_bootstrap_ci(values, 0.9, resamples=300, seed=s1)


def test_stop_rule_passes_only_if_every_seed_upper_bound_is_within_the_bar(v2: ModuleType) -> None:
    assert v2.passes_all_seeds([0.29, 0.30, 0.2999])
    assert not v2.passes_all_seeds([0.29, 0.2901, 0.3001])
    assert not v2.passes_all_seeds([0.10, math.nan, 0.10])  # absence is not evidence
    assert not v2.passes_all_seeds([])


def test_cells_are_keyed_by_seed_and_the_worst_seed_decides(v2: ModuleType) -> None:
    def stat(upper: float) -> object:
        return v2.CellStat(upper, upper, upper, upper, upper)

    cells = {}
    for seed, upper in zip(v2.SEEDS, (0.25, 0.26, 0.31), strict=True):
        for free_arm in ("A", "B"):
            key = v2.CellKey(0.05, 6, 0.33, free_arm, 1, False, seed=seed)
            cells[key] = stat(upper if free_arm == "A" else upper - 0.01)
    uppers = v2.seed_uppers(cells, 0.05, 6, 0.33, 1, False)
    assert uppers == (pytest.approx(0.25), pytest.approx(0.26), pytest.approx(0.31))
    assert not v2.passes_all_seeds(uppers)
    assert all(math.isnan(u) for u in v2.seed_uppers(cells, 0.05, 7, 0.33, 1, False))


# --------------------------------------------------------------------------- (e) rho arm
def test_beta_parameters_have_the_requested_mean_and_icc(v2: ModuleType) -> None:
    a, b = v2.beta_params(0.33, 0.1)
    assert a / (a + b) == pytest.approx(0.33)
    assert 1.0 / (a + b + 1.0) == pytest.approx(0.1)  # beta-binomial ICC = 1 / (a + b + 1)


def test_day_p_amb_is_overdispersed_with_the_right_moments(v2: ModuleType) -> None:
    arm = _arm(v2, p_amb=0.33, rho=0.1)
    rng = random.Random(5)
    draws = [v2.day_p_amb(arm, rng) for _ in range(20_000)]
    mean = sum(draws) / len(draws)
    var = sum((d - mean) ** 2 for d in draws) / len(draws)
    assert mean == pytest.approx(0.33, abs=0.01)
    assert var == pytest.approx(0.1 * 0.33 * 0.67, rel=0.08)  # Var(p_day) = rho p (1 - p)
    assert all(0.0 <= d <= 1.0 for d in draws)


def test_rho_zero_consumes_no_extra_randomness(v2: ModuleType) -> None:
    arm = _arm(v2, p_amb=0.33)
    rng = random.Random(1)
    before = rng.getstate()
    assert v2.day_p_amb(arm, rng) == 0.33
    assert rng.getstate() == before


def test_rho_arm_is_report_only_and_does_not_change_the_rho_zero_cells(v2: ModuleType) -> None:
    cands = _cands(v2, 12)
    base = v2.day_stats(cands, _arm(v2, k=3), DAY, draws=300)
    over = v2.day_stats(cands, _arm(v2, k=3, rho=0.1), DAY, draws=300)
    assert base != over
    assert v2.RHO_ARM == 0.1
    assert v2.RHO_ARM_GATES is False


def test_rho_edges(v2: ModuleType) -> None:
    for p in (0.0, 1.0):
        assert v2.day_p_amb(_arm(v2, p_amb=p, rho=0.1), random.Random(1)) == p
    with pytest.raises(ValueError):
        v2.beta_params(0.3, 0.0)
    with pytest.raises(ValueError):
        v2.beta_params(0.3, 1.0)


# --------------------------------------------------------------------------- data rule
@pytest.mark.parametrize(
    "bad", [dt.date(2026, 10, 7), dt.date(2026, 10, 8), dt.date(2026, 11, 28), dt.date(2027, 1, 1)]
)
def test_v2_still_refuses_any_input_on_or_after_2026_10_07(v2: ModuleType, bad: dt.date) -> None:
    with pytest.raises(v2.WindowDataRefused):
        v2.refuse_window_day(bad)
    v2.refuse_window_day(dt.date(2026, 10, 6))
    cutoff_ns = int(dt.datetime(2026, 10, 7, tzinfo=dt.UTC).timestamp()) * NS
    with pytest.raises(v2.WindowDataRefused):
        v2.refuse_window_ns(cutoff_ns)
    v2.refuse_window_ns(cutoff_ns - 1)


def test_v2_refuses_window_paths_candidates_and_orders(v2: ModuleType, tmp_path: Path) -> None:
    with pytest.raises(v2.WindowDataRefused):
        v2.refuse_window_path(tmp_path / "cands-2026-10-09.json")
    bad = tmp_path / "c.json"
    bad.write_text(json.dumps({"schema": 1, "days": {"2026-10-07": []}}))
    with pytest.raises(v2.WindowDataRefused):
        v2.load_candidates(bad)
    assert v2.main(["--cands", str(bad), "--out", str(tmp_path / "o.json")]) == 2
    assert not (tmp_path / "o.json").exists()
    orders = tmp_path / "orders.tsv"
    orders.write_text(
        "coid\tsubmit_ts\tposted\toutcome\tside\thpost_s\n"
        "x\t2026-10-07T00:00:00.0Z\tY\tFILL\tYES\t0.1\n"
    )
    with pytest.raises(v2.WindowDataRefused):
        v2.read_hold_inputs(orders)


# --------------------------------------------------------------------------- arm-time record
def test_simulate_day_records_arm_times_and_ambiguity_of_admitted_entries(v2: ModuleType) -> None:
    cands = _cands(v2, 8, step_s=1.0)
    arm = v2.Arm(k=2, p_amb=0.5, bucket=0.05, throttle=True, bound=True)
    out = v2.simulate_day(cands, arm, random.Random(11))
    assert len(out.arm_ns) == len(out.ambiguous) == out.admitted
    assert list(out.arm_ns) == sorted(out.arm_ns)
    assert set(out.arm_ns) <= {c.ts_ns for c in cands}
    clean = v2.simulate_day(cands, v2.Arm(k=8, p_amb=0.0, bucket=0.05), random.Random(1))
    assert clean.ambiguous == (False,) * clean.admitted
    every = v2.simulate_day(cands, v2.Arm(k=8, p_amb=1.0, bucket=0.05), random.Random(1))
    assert every.ambiguous == (True,) * every.admitted
