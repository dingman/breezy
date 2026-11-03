"""Frozen LEAK-NULL decision rules, with synthetic seed summaries only."""

from __future__ import annotations

import datetime as dt
import math
import statistics
from collections.abc import Mapping
from dataclasses import FrozenInstanceError, asdict, replace
from typing import Any

import pytest
from scipy.special import stdtrit

import breezy.analysis.leak_null as ln
import breezy.analysis.leak_null_decide as dec
import breezy.analysis.multisource_blend as msb
from tests.unit.test_multisource_blend_skill import _PINS

N1, N2, N3 = ln.NullId
_RECORD: dict[str, Any] = {"m0p_vs_m3_mean": 0.165, "m0p_vs_m3_lb": 0.150, "floor": 0.01}


def _summaries(
    mean: float,
    *,
    null_id: str = N1,
    n: int = 20,
    lb: float | None = None,
) -> tuple[dec.SeedSummary, ...]:
    return tuple(
        dec.SeedSummary(
            seed=i,
            null_id=null_id,
            mean=mean,
            lb=mean if lb is None else lb,
            n_days=2,
            by_horizon={},
            by_m3_level={},
            day_values=(
                (dt.date(2025, 1, 1), mean),
                (dt.date(2025, 1, 2), mean),
            ),
            failed=None,
        )
        for i in range(n)
    )


def _nulls(a: float, b: float, c: float) -> dict[str, tuple[dec.SeedSummary, ...]]:
    return {key: _summaries(mean, null_id=key) for key, mean in zip((N1, N2, N3), (a, b, c))}


def _pc() -> tuple[dec.SeedSummary, ...]:
    return _summaries(0.5, null_id=N2, n=5)


def _decide(
    data: Mapping[str, tuple[dec.SeedSummary, ...]],
    pc: tuple[dec.SeedSummary, ...] | None = None,
    defects: tuple[str, ...] = (),
    record: Mapping[str, Any] = _RECORD,
) -> ln_decision:
    return dec.decide(data, _pc() if pc is None else pc, defects, record, dec.THRESHOLDS)


ln_decision = tuple[dec.LeakNullVerdict, tuple[str, ...]]


def test_bound_equals_2093_formula_at_k20() -> None:
    summaries = tuple(replace(s, mean=0.01 * s.seed) for s in _summaries(0))
    values = [0.01 * s.seed for s in summaries]
    bound = dec.across_seed_bound(summaries)
    assert bound.n == 20 and bound.t == 2.093
    assert bound.m == pytest.approx(statistics.mean(values))
    assert bound.sd == pytest.approx(statistics.stdev(values))
    assert bound.l == pytest.approx(bound.m - 2.093 * bound.sd / math.sqrt(20))
    assert dec.across_seed_bound(_summaries(0.1)).l == 0.1
    one = dec.across_seed_bound(_summaries(0.1, n=1))
    assert one.n == 1 and one.sd == 0 and one.l == one.m == 0.1
    assert one.note and "n=1" in one.note
    three = dec.across_seed_bound(_summaries(0.1, n=3))
    assert three.t == pytest.approx(stdtrit(2, 0.975))
    with pytest.raises(dec.Refusal, match="completed"):
        dec.across_seed_bound(())
    with pytest.raises(dec.Refusal):
        dec.across_seed_bound((replace(_summaries(0.1, n=1)[0], failed="fit"),))


def test_stdtrit_matches_pins() -> None:
    assert msb.ALPHA_ONE_SIDED == 0.025
    assert abs(stdtrit(19, 1 - msb.ALPHA_ONE_SIDED) - 2.093) < 5e-4
    assert abs(stdtrit(4, 1 - msb.ALPHA_ONE_SIDED) - 2.776) < 5e-4
    assert asdict(dec.THRESHOLDS) == {
        "lb_gt": 0.0,
        "leak_mean_min": 0.005,
        "fluke_count_max": 2,
        "benign_n2_ratio_max": 0.25,
        "benign_n3_ratio_min": 0.5,
        "invariant_tol": 1e-9,
        "max_failed_seeds": 2,
        "min_moved_fraction": 0.5,
        "k": 20,
        "pc_k": 5,
        "t_crit_k20": 2.093,
        "t_crit_pc5": 2.776,
        "plant_noise_sd_f": 1.0,
    }
    with pytest.raises(FrozenInstanceError):
        dec.THRESHOLDS.k = 19  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        _pc()[0].mean = 1  # type: ignore[misc]
    assert not hasattr(_pc()[0], "__dict__")


def test_seed_summary_matches_msb_delta_summary() -> None:
    scored = [
        msb.ScoredRow(
            station=station,
            climate_day=dt.date(2025, 1, 1) + dt.timedelta(days=i),
            horizon=h,
            version="v4.2",
            fold_id=0,
            observed_f=70,
            crps={"M0prime": 1.0 + i / 10, "M3": 0.9},
            arm_predictions={},
            champion=None,
            levels={"M3": level},
        )
        for i in range(8)
        for station in ("NYC", "LAX")
        for h, level in (("D-1", 0), ("D0", 3))
    ]
    boot = ln.subseed(31, f"boot:{N1}")
    kwargs: dict[str, Any] = {"n_boot": int(_PINS["bootstrap_n"]), "seed": boot, "mean_block": 7.0}
    expected = msb.delta_summary(msb.delta_by_day(scored, "M0prime", "M3"), **kwargs)
    summary = dec.seed_summary(
        scored,
        seed=31,
        null_id=N1,
        n_boot=int(_PINS["bootstrap_n"]),
        boot_seed=boot,
        mean_block=7.0,
    )
    assert (summary.mean, summary.lb, summary.n_days) == (
        expected.mean,
        expected.lb,
        expected.n_days,
    )
    assert summary.day_values == tuple(msb.delta_by_day(scored, "M0prime", "M3"))
    assert set(summary.by_horizon) == {"D-1", "D0"}
    assert set(summary.by_m3_level) == {0, 3}
    for h, result in summary.by_horizon.items():
        assert result == msb.delta_summary(
            msb.delta_by_day([r for r in scored if r.horizon == h], "M0prime", "M3"),
            **kwargs,
        )
    for level, result in summary.by_m3_level.items():
        assert result == msb.delta_summary(
            msb.delta_by_day([r for r in scored if r.levels["M3"] == level], "M0prime", "M3"),
            **kwargs,
        )


def test_lb_exactly_zero_is_not_positive() -> None:
    data = _nulls(0, 0, 0)
    data[N1] = _summaries(0, lb=0)
    assert _decide(data)[0] == dec.LeakNullVerdict.DISCHARGED_FLUKE
    assert not dec.pc_flagged(_summaries(0, n=5), dec.THRESHOLDS)[0]


@pytest.mark.parametrize(
    "trigger",
    [
        "level0",
        "fold_disjointness",
        "m0prime",
        "prefix_level",
        "pc",
        "completed",
        "pins",
    ],
)
def test_decide_r0_each_trigger(trigger: str) -> None:
    data = _nulls(0.02, 0.02, 0.02)  # R1 would fire without R0's precedence.
    defects: tuple[str, ...] = ()
    pc = _pc()
    if trigger == "pc":
        pc = _summaries(0, n=5)
    elif trigger == "completed":
        data[N3] = data[N3][:17]
    else:
        defects = (f"{trigger} invariant breach",)
    verdict, reasons = _decide(data, pc, defects)
    assert verdict == dec.LeakNullVerdict.INVALID
    assert reasons


def test_decide_r1_leak() -> None:
    assert _decide(_nulls(0.02, 0.005, 0.01))[0] == dec.LeakNullVerdict.LEAK_CONFIRMED


def test_decide_r1_small_mean_held_inconclusive() -> None:
    assert _decide(_nulls(0.02, 0.0049, 0.01))[0] == dec.LeakNullVerdict.HELD_INCONCLUSIVE


def test_decide_r2_fluke() -> None:
    data = _nulls(-0.01, 0, 0)
    data[N1] = tuple(replace(s, lb=0.1 if i < 2 else 0) for i, s in enumerate(data[N1]))
    assert _decide(data)[0] == dec.LeakNullVerdict.DISCHARGED_FLUKE


def test_decide_r2_blocked_by_three_positives() -> None:
    data = _nulls(-0.01, 0, 0)
    data[N1] = tuple(replace(s, lb=0.1 if i < 3 else 0) for i, s in enumerate(data[N1]))
    assert _decide(data)[0] == dec.LeakNullVerdict.HELD


def test_decide_r3_benign_dof() -> None:
    data = _nulls(0.02, 0, 0.01)
    assert _decide(data)[0] == dec.LeakNullVerdict.DISCHARGED_BENIGN_DOF
    data[N3] = _summaries(0.0099, null_id=N3)
    assert _decide(data, record={**_RECORD, "floor": 1.0})[0] == dec.LeakNullVerdict.HELD


def test_decide_r4_requires_bias_check() -> None:
    data = _nulls(0.02, -0.001, 0)
    assert _decide(data)[0] == dec.LeakNullVerdict.DISCHARGED_PENALTY_MEDIATED
    assert _decide(data, record={**_RECORD, "floor": 0.14})[0] == dec.LeakNullVerdict.HELD
    assert _decide(data, record={**_RECORD, "floor": None})[0] == dec.LeakNullVerdict.HELD


def test_decide_else_held() -> None:
    data = _nulls(0.02, 0, 0)
    assert _decide(data, record={**_RECORD, "floor": 1.0})[0] == dec.LeakNullVerdict.HELD


def test_failed_seeds_non_positive_denominator_k() -> None:
    data = _nulls(-0.01, 0, 0)
    failed = replace(data[N1][-1], failed="FitNotConvergedError", mean=None, lb=999)
    data[N1] = (*data[N1][:-1], failed)
    assert dec.across_seed_bound(data[N1]).n == 19
    assert dec.across_seed_bound(data[N1]).m == -0.01
    assert _decide(data)[0] == dec.LeakNullVerdict.HELD  # D2: 19 cannot discharge R2.
    data[N1] = _summaries(-0.01)
    data[N2] = (*data[N2][:-2], *(replace(s, failed="fit", lb=999) for s in data[N2][-2:]))
    assert _decide(data)[0] == dec.LeakNullVerdict.DISCHARGED_FLUKE


def test_seventeen_completed_is_invalid() -> None:
    data = _nulls(0, 0, 0)
    data[N2] = tuple(replace(s, failed="fit") if i < 3 else s for i, s in enumerate(data[N2]))
    assert _decide(data)[0] == dec.LeakNullVerdict.INVALID


def test_pc_flag_requires_both_bound_and_floor() -> None:
    flagged, record = dec.pc_flagged(_pc(), dec.THRESHOLDS, plant_mask_rate=0.625)
    assert flagged
    assert record["M_PC"] == 0.5 and record["L_PC"] == 0.5
    assert record["per_seed_means"] == [0.5] * 5
    assert record["plant_mask_rate"] == 0.625
    assert dec.pc_flagged(_summaries(0.005, n=5), dec.THRESHOLDS)[0]
    assert not dec.pc_flagged(_summaries(0.0049, n=5), dec.THRESHOLDS)[0]
    varied = tuple(replace(s, mean=0.1 if i < 4 else 10) for i, s in enumerate(_pc()))
    assert not dec.pc_flagged(varied, dec.THRESHOLDS)[0]
    failed = (*_pc()[:-1], replace(_pc()[-1], failed="fit"))
    assert not dec.pc_flagged(failed, dec.THRESHOLDS)[0]
    assert not dec.pc_flagged((), dec.THRESHOLDS)[0]


def test_f13_bias_adjusted_mirrors_lb_failures() -> None:
    assert dec.f13_bias_adjusted(_RECORD, 0.02) == {
        "adj_lb": 0.13,
        "floor": 0.01,
        "floor_check": "pass",
        "pass": True,
    }
    assert not dec.f13_bias_adjusted({**_RECORD, "floor": 0.14}, 0.02)["pass"]
    assert dec.f13_bias_adjusted({**_RECORD, "floor": 0.13}, 0.02)["pass"]
    assert not dec.f13_bias_adjusted({**_RECORD, "floor": 0}, 0.150)["pass"]
    unavailable = dec.f13_bias_adjusted({**_RECORD, "floor": None}, 0.02)
    assert unavailable["floor_check"] == "unavailable" and unavailable["pass"]
    assert not dec.f13_bias_adjusted({**_RECORD, "floor": None}, 0.150)["pass"]
