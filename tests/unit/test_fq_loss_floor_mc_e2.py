"""E-2: calibration rate, p_keep tolerance note, veto fields, per-α t_min."""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pytest

from breezy.analysis.fq_loss_stop_core import ALPHA_FLOOR_GRID, T_MIN_GRID
from scripts.analysis.fq_loss_floor_mc_e2 import complete_veto
from scripts.analysis.fq_loss_floor_mc_engine import run_floor
from scripts.analysis.fq_loss_floor_mc_gate import (
    AlphaEval,
    FloorConfig,
    rate_cal,
    rate_cal_max,
    select_alpha,
)
from scripts.analysis.fq_loss_floor_mc_rates import split_p_keep_cap
from scripts.analysis.fq_loss_floor_mc_report import MIXES, evaluate_alpha
from scripts.analysis.fq_loss_floor_mc_rows import make_leg, make_station_day
from scripts.analysis.fq_loss_floor_mc_sim import Simulation

_FREEZE = date(2026, 10, 8)


def _config(**overrides: object) -> FloorConfig:
    base: dict[str, object] = {
        "take_rate_lower": 0.25,
        "theta": 0.0,
        "lambda_pool": 0.40,
        "r_sd": 1.0,
        "lambda_sd": 1.0,
        "half_spread": 0.03,
        "pool_exit_fraction": 0.0,
        "rho_hat": None,
        "freeze": _FREEZE,
        "horizon": date(2026, 10, 10),
    }
    base.update(overrides)
    return FloorConfig(**base)  # type: ignore[arg-type]


def _eval(alpha: float, *, g1: bool, g3: float, c: float = 2.05, t_min: int = 2) -> AlphaEval:
    return AlphaEval(
        alpha=alpha,
        g1_pass=g1,
        g1_margin=g1,
        g3_at_m016=g3,
        s6_rate=0.04,
        s6_se=0.01,
        c=c,
        c_se=0.03,
        t_min=t_min,
        measured_power={"-0.16": g3, "-0.08": g3 / 2, "-0.04": g3 / 4},
        epoch_ok={_FREEZE.isoformat(): False},
    )


def _gate(
    alpha: float, mix: str, g3: dict[str, float], *, g1: bool, epoch: str
) -> dict[str, object]:
    return {
        "alpha": alpha,
        "epoch": epoch,
        "mix": mix,
        "g1": g1,
        "g1_margin": g1,
        "g3": g3,
    }


def test_rate_cal_e2_both_branches() -> None:
    # λ above the floor: bind at the floor, not at λ (pre-E2 calibrated at λ).
    assert rate_cal(0.40, 0.25) == pytest.approx(0.25)
    assert rate_cal(5.794, 0.25) == pytest.approx(0.25)
    # λ below the floor: the max() rule still binds, so this is not λ.
    assert rate_cal(0.10, 0.25) == pytest.approx(0.25)
    assert rate_cal(0.25, 0.25) == pytest.approx(0.25)
    assert rate_cal_max(5.794, 0.25) == pytest.approx(5.794)
    assert rate_cal_max(0.10, 0.25) == pytest.approx(0.25)


def test_p_keep_within_bisection_tolerance_is_not_a_warning() -> None:
    warnings, notes = split_p_keep_cap(1.0, 1.008065)
    assert warnings == []
    assert notes == ["achieved rate within bisection tolerance (raw=1.008065)"]
    assert all("within bisection tolerance" not in line for line in warnings)


def test_p_keep_beyond_bisection_tolerance_warns() -> None:
    warnings, notes = split_p_keep_cap(1.0, 1.05)
    assert notes == []
    assert len(warnings) == 1
    assert "p_keep capped at 1" in warnings[0]
    assert "within bisection tolerance" not in warnings[0]


def test_g3_floor_veto_fills_power_and_names_the_failing_mix() -> None:
    epoch = _FREEZE.isoformat()
    gates = [
        _gate(0.10, "M-pool", {"-0.16": 0.579, "-0.08": 0.40, "-0.04": 0.20}, g1=True, epoch=epoch),
        _gate(0.10, "M-no", {"-0.16": 0.434, "-0.08": 0.30, "-0.04": 0.15}, g1=True, epoch=epoch),
        _gate(0.10, "M-yes", {"-0.16": 0.210, "-0.08": 0.12, "-0.04": 0.05}, g1=True, epoch=epoch),
        _gate(0.20, "M-yes", {"-0.16": 0.01, "-0.08": 0.01, "-0.04": 0.01}, g1=True, epoch=epoch),
        _gate(
            0.10,
            "M-yes",
            {"-0.16": 0.99, "-0.08": 0.99, "-0.04": 0.99},
            g1=True,
            epoch="2026-11-01",
        ),
    ]
    chosen = select_alpha((_eval(0.10, g1=True, g3=0.210, c=2.05, t_min=3),))
    assert chosen.veto_cause == "g3_floor"
    filled = complete_veto(
        chosen,
        gates=gates,
        evals=(_eval(0.10, g1=True, g3=0.210, c=2.05, t_min=3),),
        freeze=_FREEZE,
    )
    assert filled.measured_power is not None
    assert filled.measured_power["-0.16"] == pytest.approx(0.210)
    assert filled.measured_power["-0.08"] == pytest.approx(0.12)
    assert filled.measured_power["-0.04"] == pytest.approx(0.05)
    assert filled.failing_mix == "M-yes"
    assert filled.c is None
    assert filled.t_min is None
    diagnostics = filled.diagnostics
    assert diagnostics is not None
    assert float(diagnostics["alpha"]) == pytest.approx(ALPHA_FLOOR_GRID[0])
    assert float(diagnostics["c"]) == pytest.approx(2.05)
    assert diagnostics["t_min"] == 3
    assert float(diagnostics["c_mc_se_total"]) == pytest.approx(0.03)
    assert float(diagnostics["s6"]) == pytest.approx(0.04)


def test_g1_unreachable_veto_still_fills_measured_power() -> None:
    epoch = _FREEZE.isoformat()
    gates = [
        _gate(0.10, "M-pool", {"-0.16": 0.50, "-0.08": 0.20, "-0.04": 0.10}, g1=True, epoch=epoch),
        _gate(0.10, "M-yes", {"-0.16": 0.40, "-0.08": 0.18, "-0.04": 0.08}, g1=True, epoch=epoch),
        _gate(0.10, "M-no", {"-0.16": 0.30, "-0.08": 0.11, "-0.04": 0.04}, g1=False, epoch=epoch),
    ]
    chosen = select_alpha(
        (
            _eval(0.10, g1=False, g3=0.0),
            _eval(0.20, g1=False, g3=0.0),
            _eval(0.30, g1=False, g3=0.0),
        )
    )
    assert chosen.veto_cause == "g1_unreachable"
    assert chosen.measured_power is None
    filled = complete_veto(
        chosen,
        gates=gates,
        evals=(
            _eval(0.10, g1=False, g3=0.0, c=1.2, t_min=1),
            _eval(0.20, g1=False, g3=0.0),
        ),
        freeze=_FREEZE,
    )
    assert filled.measured_power is not None
    assert filled.measured_power["-0.16"] == pytest.approx(0.30)
    assert filled.measured_power["-0.08"] == pytest.approx(0.11)
    assert filled.measured_power["-0.04"] == pytest.approx(0.04)
    assert filled.failing_mix == "M-no"
    assert filled.c is None
    assert filled.diagnostics is not None
    assert filled.diagnostics["t_min"] == 1


def _obj(value: object) -> dict[Any, Any]:
    assert isinstance(value, dict)
    return value


def test_run_floor_veto_emits_filled_power_and_the_sensitivity_row() -> None:
    day = make_station_day("K", (make_leg("T70", "yes", 0.45),))
    document = _obj(
        run_floor(
            ((day,),),
            replicates=4,
            seed=1,
            config=_config(lambda_sd=0.01),
            alphas=(0.10,),
            outer_resamples=0,
        )
    )
    assert document["rate_cal_rule"] == "E2"
    assert document["rate_cal"] == pytest.approx(0.25)
    outcome = _obj(document["outcome"])
    assert outcome["floor_mode"] == "unreachable_veto"
    assert outcome["veto_cause"] == "g1_unreachable"
    power = _obj(outcome["measured_power"])
    assert set(power) == {"-0.16", "-0.08", "-0.04"}
    assert all(value is not None for value in power.values())
    diagnostics = _obj(outcome["diagnostics"])
    assert set(diagnostics) == {"alpha", "c", "t_min", "c_mc_se_total", "s6"}
    assert diagnostics["t_min"] in T_MIN_GRID
    assert outcome["c"] is None
    assert outcome["t_min"] is None
    rows = document["rows"]
    assert isinstance(rows, list)
    sens = [_obj(row) for row in rows if _obj(row)["row"] == "cal_at_max_rate"]
    assert len(sens) == 1
    assert sens[0]["role"] == "sensitivity"
    assert set(sens[0]) == {"row", "role", "alpha", "c"}
    assert isinstance(sens[0]["c"], float)


def test_t_min_is_chosen_from_the_grid_for_each_alpha() -> None:
    sim = Simulation(
        paths=((0.0, 0.0, 0.0, 0.0, 0.0),) * 4,
        cuts=((1, 2, 3, 4, 5),) * 4,
        max_abs_carry_over_sigma=0.0,
        mean_carry=0.0,
        multi_tick_share=0.0,
    )
    keys = [
        (row, mode, mix)
        for row, mode in (
            ("H0", "none"),
            ("S1", "none"),
            ("S2", "none"),
            ("S4", "none"),
            ("S5", "bind"),
            ("S5", "half"),
            ("S6", "none"),
            ("S7", "none"),
        )
        for mix in MIXES
    ]
    cal_sims = {key: sim for key in keys}
    critical = np.array([0.01, 0.01, 0.01, 0.01])

    def crit(simulation: Simulation, n_days: int, t_min: int) -> np.ndarray:
        del simulation, n_days, t_min
        return critical

    day = make_station_day("K", (make_leg("T70", "yes", 0.5),))
    config = _config()
    seen: dict[float, set[int]] = {}

    def _run(alpha: float, prefer: int) -> int:
        asked: set[int] = set()

        def power(delta: float, mix: str, n_days: int, t_min: int, solved: float) -> float:
            del delta, mix, n_days, solved
            asked.add(t_min)
            return 0.9 if t_min == prefer else 0.1

        rows: list[dict[str, object]] = []
        gates: list[dict[str, object]] = []
        evaluation, _cell = evaluate_alpha(
            alpha=alpha,
            cal_sims=cal_sims,
            crit=crit,
            power=power,
            n_cal=5,
            replicates=4,
            config=config,
            lengths={_FREEZE.isoformat(): 5},
            p_gate=1.0,
            cleaned=((day,),),
            feasible={mix: () for mix in MIXES},
            seed=1,
            rows=rows,
            gates=gates,
        )
        seen[alpha] = asked
        assert all(row["t_min"] == prefer for row in gates)
        assert all(row["t_min"] == prefer for row in rows)
        return evaluation.t_min

    assert _run(0.10, 5) == 5
    assert _run(0.20, 1) == 1
    assert seen[0.10] == set(T_MIN_GRID)
    assert seen[0.20] == set(T_MIN_GRID)
