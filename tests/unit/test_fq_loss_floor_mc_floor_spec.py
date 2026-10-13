"""S3 WP1: ``FloorSpec``, station persistence and the feasible G1 path.

Sibling of ``test_fq_loss_floor_mc_spec_pins.py`` (kept unedited: it pins the FQ
documents). Every new parameter defaults to the FQ value, so the WP0 hashes are the
oracle for "FQ byte-identical". New API is read as ``gate.FloorSpec`` at call time so
each test fails on its own behaviour rather than on one collection-time ImportError.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

import pytest

from breezy.analysis.fq_loss_stop_core import step_clock
from scripts.analysis import fq_loss_floor_mc_engine as engine
from scripts.analysis import fq_loss_floor_mc_gate as gate
from scripts.analysis import fq_loss_floor_mc_outer as outer
from scripts.analysis import fq_loss_floor_mc_report as report
from scripts.analysis import fq_loss_floor_mc_rows as rows
from scripts.analysis.fq_loss_floor_mc_draw import PreparedDay, clock_block, prepare_day
from scripts.analysis.fq_loss_floor_mc_gate import repeated_crossing
from scripts.analysis.fq_loss_floor_mc_rows import StationDay, make_leg, make_station_day
from scripts.analysis.fq_loss_floor_mc_sim import simulate_family
from tests.unit.test_fq_loss_floor_mc_spec_pins import (
    PASS_DOC_SHA256,
    _config,
    _mixed_world,
    _sha,
)

_FQ_MIXES = ("M-pool", "M-yes", "M-no")
# simulate_family(H0 / S5, persist omitted) digest taken on HEAD 63e1cdbb before any edit.
_SIM_GOLDEN = {
    ("H0", None): "9d11a1999a082e10413e74288d635ea92812055a5b7eae1e128319d7521ac59a",
    ("S5", 0.5): "c4817562bccec4b14fa55765f531b9e7b40adf91ee08f6e6678a8a6a87b5c7dc",
}


def _fq_cal() -> tuple[tuple[str, str], ...]:
    return tuple(gate.FQ_CAL)


def _maker_spec() -> Any:
    return gate.FloorSpec(
        mixes=("M-pool",),
        cal=(*_fq_cal(), ("S8", "persist3"), ("S9", "persist5")),
        binding=(("H0", "none"), ("S4", "none"), ("S5", "bind"), ("S8", "persist3")),
        persist=(("persist3", 3, 0.5), ("persist5", 5, 0.9)),
        g1_path="worst_feasible",
    )


def _all_no_days(count: int = 8) -> tuple[StationDay, ...]:
    return tuple(
        make_station_day(f"S{i % 4}", (make_leg("T70", "no", 0.78), make_leg("T72", "no", 0.78)))
        for i in range(count)
    )


def _run(days: Sequence[StationDay], **kwargs: Any) -> dict[str, Any]:
    document = engine.run_floor(
        (days[0::2], days[1::2]),
        gate_groups=(days[0::3], days[1::3], days[2::3]),
        **kwargs,
    )
    assert isinstance(document, dict)
    return document


def _one_leg_station(station: str, be: float = 0.5) -> StationDay:
    return make_station_day(station, (make_leg("T70", "no", be),))


def _prepared(*stations: str) -> list[list[PreparedDay]]:
    return [[prepare_day(_one_leg_station(station)) for station in stations]]


def _outcome_series(sim: Any, rep: int, offset: int, stride: int) -> list[int | None]:
    return [draw.index for draw in sim.draws[rep]][offset::stride]


# --------------------------------------------------------------------------- FloorSpec


def test_floor_spec_rejects_noncanonical_mixes_and_missing_m_pool() -> None:
    bad_mixes = (
        (),
        ("M-yes",),
        ("M-yes", "M-no"),
        ("M-yes", "M-pool"),
        ("M-no", "M-yes", "M-pool"),
        ("M-pool", "M-pool"),
        ("M-pool", "M-other"),
    )
    for mixes in bad_mixes:
        with pytest.raises(ValueError, match="mixes"):
            gate.FloorSpec(mixes=mixes)
    assert gate.FloorSpec(mixes=("M-pool", "M-no")).mixes == ("M-pool", "M-no")
    assert gate.FloorSpec(mixes=("M-pool",)).mixes == ("M-pool",)


def test_floor_spec_rejects_duplicate_binding_row_labels_and_binding_outside_cal() -> None:
    with pytest.raises(ValueError, match="binding"):
        gate.FloorSpec(binding=(("S5", "bind"), ("S5", "half")))
    with pytest.raises(ValueError, match="binding"):
        gate.FloorSpec(binding=(("H0", "none"), ("S9", "persist5")))
    with pytest.raises(ValueError, match="persist"):
        gate.FloorSpec(persist=(("persist3", 3, 0.5),))
    # A binding row that is in cal, with a unique label, is accepted.
    spec = gate.FloorSpec(
        cal=(*_fq_cal(), ("S8", "persist3")),
        binding=(("H0", "none"), ("S8", "persist3")),
        persist=(("persist3", 3, 0.5),),
    )
    assert spec.persist_for("persist3") == (3, 0.5)
    assert spec.persist_for("none") is None


def test_floor_spec_rejects_duplicate_persist_modes() -> None:
    cells = (*_fq_cal(), ("S8", "persist3"))
    with pytest.raises(ValueError, match="persist"):
        gate.FloorSpec(
            mixes=("M-pool",),
            cal=cells,
            persist=(("persist3", 3, 0.5), ("persist3", 5, 0.9)),
        )
    one = gate.FloorSpec(mixes=("M-pool",), cal=cells, persist=(("persist3", 3, 0.5),))
    assert one.persist_for("persist3") == (3, 0.5)


def test_report_day_z_skips_exactly_the_days_the_sim_drops() -> None:
    days = {
        "ok": StationDay("LAX", (make_leg("T70", "no", 0.75),)),
        "two_leg_ok": StationDay("LAX", (make_leg("T70", "no", 0.75), make_leg("T72", "no", 0.75))),
        "refusal": StationDay("LAX", (make_leg("T70", "no", 0.2), make_leg("T72", "no", 0.2))),
        "zero_sigma": StationDay("LAX", (make_leg("T70", "no", 1 - 1e-13),)),
        "zero_variance_nonzero_outcome": StationDay("LAX", (make_leg("T70", "no", 1e-13),)),
        "legless": StationDay("LAX", ()),
    }
    no_z = {name for name, day in days.items() if report._day_z(day, "worst_feasible") is None}
    dropped = {
        name
        for name, day in days.items()
        if not engine.prepare_mix_groups([[day]], "M-pool", s6=False)[0]
    }
    assert no_z == dropped == {"refusal", "zero_sigma", "zero_variance_nonzero_outcome", "legless"}
    # the sim names the clock reason for each non-legless drop
    assert clock_block(days["refusal"]) == "sigma_no_exceeds_one"
    assert clock_block(days["zero_sigma"]) == "zero_variance_realised"
    assert clock_block(days["zero_variance_nonzero_outcome"]) == "zero_variance_realised"


def test_floor_spec_defaults_are_fq_and_path_families_counts_cells() -> None:
    assert gate.FloorSpec() == gate.FQ_SPEC
    assert gate.FQ_SPEC.mixes == _FQ_MIXES
    assert gate.FQ_SPEC.persist == ()
    assert gate.FQ_SPEC.g1_path == "all_lose"
    assert gate.path_families(gate.FQ_SPEC) == 60 == engine.PATH_FAMILIES
    # 10 calibration rows x 1 mix + 3 deltas x 1 mix x 4 epoch lengths.
    assert gate.path_families(_maker_spec()) == 22
    assert engine.MIXES == gate.FQ_SPEC.mixes


# ------------------------------------------------------------ FQ default stays byte-identical


def test_run_floor_default_and_explicit_fq_spec_hash_equal() -> None:
    days = _mixed_world()

    def hashed(**extra: Any) -> str:
        return _sha(
            _run(
                days,
                replicates=64,
                seed=11,
                config=_config(),
                alphas=None,
                outer_resamples=2,
                outer_replicates=32,
                **extra,
            )
        )

    assert hashed() == PASS_DOC_SHA256
    assert hashed(spec=gate.FQ_SPEC) == PASS_DOC_SHA256


def test_fq_spec_document_has_no_floor_spec_key() -> None:
    document = _run(
        _mixed_world(),
        replicates=32,
        seed=11,
        config=_config(),
        spec=gate.FQ_SPEC,
        alphas=(0.10,),
        outer_resamples=0,
    )
    assert "floor_spec" not in document
    assert "g1_all_lose_z" not in document
    assert all("z_all_lose" not in row and "z_g1" not in row for row in document["gates"])


def _sim_digest(sim: Any) -> str:
    payload = [
        sim.paths,
        sim.cuts,
        sim.max_abs_carry_over_sigma,
        sim.mean_carry,
        sim.multi_tick_share,
    ]
    return hashlib.sha256(json.dumps(payload).encode()).hexdigest()


def test_persist_none_leaves_rng_stream_unchanged() -> None:
    days = [
        make_station_day(s, (make_leg("T70", "no", 0.6), make_leg("T72", "yes", 0.4)))
        for s in ("LAX", "MIA")
    ]
    groups = [[prepare_day(d) for d in days], [prepare_day(days[0])]]
    for (row, rho), golden in _SIM_GOLDEN.items():
        kwargs: dict[str, Any] = {
            "replicates": 40,
            "n_days": 9,
            "p_keep": 0.7,
            "seed": 5,
            "row": row,
            "rho": rho,
        }
        omitted = simulate_family(groups, **kwargs)
        explicit = simulate_family(groups, persist=None, **kwargs)
        assert _sim_digest(omitted) == golden
        assert _sim_digest(explicit) == golden


def test_m_pool_equals_m_no_on_all_no_templates() -> None:
    days = _all_no_days()
    for day in days:
        pooled = rows.apply_mix(day, "M-pool")
        no_only = rows.apply_mix(day, "M-no")
        assert pooled.legs == no_only.legs
        assert pooled.netting == no_only.netting == 0.0
    groups = (days[0::2], days[1::2])
    pool_prepared = engine.prepare_mix_groups(groups, "M-pool", s6=False)
    no_prepared = engine.prepare_mix_groups(groups, "M-no", s6=False)
    assert [[p.xs for p in g] for g in pool_prepared] == [[p.xs for p in g] for g in no_prepared]
    assert [[p.masses for p in g] for g in pool_prepared] == [
        [p.masses for p in g] for g in no_prepared
    ]
    kwargs: dict[str, Any] = {"replicates": 20, "n_days": 6, "p_keep": 1.0, "seed": 9, "row": "H0"}
    pool_sim = simulate_family(pool_prepared, **kwargs)
    no_sim = simulate_family(no_prepared, **kwargs)
    assert pool_sim.paths == no_sim.paths
    assert pool_sim.cuts == no_sim.cuts


# ---------------------------------------------------------------------------- persistence


def test_persist_and_rho_together_are_refused() -> None:
    groups = _prepared("LAX")
    kwargs: dict[str, Any] = {"replicates": 2, "n_days": 3, "p_keep": 1.0, "seed": 1, "row": "H0"}
    with pytest.raises(ValueError, match="persist"):
        simulate_family(groups, rho=0.5, persist=(3, 0.5), **kwargs)
    with pytest.raises(ValueError, match="persist"):
        simulate_family(groups, persist=(0, 0.5), **kwargs)
    with pytest.raises(ValueError, match="persist"):
        simulate_family(groups, persist=(3, 1.5), **kwargs)
    assert simulate_family(groups, persist=(3, 0.5), **kwargs).paths


def test_persist_full_correlation_shares_station_factor_within_block() -> None:
    sim = simulate_family(
        _prepared("LAX", "MIA"),
        replicates=80,
        n_days=6,
        p_keep=1.0,
        seed=17,
        row="H0",
        persist=(3, 1.0),
        record_draws=True,
    )
    lax_vs_mia = 0
    for rep in range(80):
        lax = _outcome_series(sim, rep, 0, 2)
        mia = _outcome_series(sim, rep, 1, 2)
        assert len(lax) == len(mia) == 6
        for series in (lax, mia):
            assert len(set(series[0:3])) == 1
            assert len(set(series[3:6])) == 1
        lax_vs_mia += int(lax[0] != mia[0])
    # Stations carry independent factors: they disagree in some replicates.
    assert lax_vs_mia > 0


def _critical_mean_se(sim: Any, n_days: int) -> tuple[float, float]:
    values = engine._criticals(sim, n_days, 1)
    return float(values.mean()), float(values.std(ddof=1) / math.sqrt(len(values)))


def test_persist_factor_redrawn_every_L_days() -> None:
    reps = 300
    sim = simulate_family(
        _prepared("LAX"),
        replicates=reps,
        n_days=6,
        p_keep=1.0,
        seed=23,
        row="H0",
        persist=(2, 1.0),
        record_draws=True,
    )
    differ = 0
    pairs = 0
    for rep in range(reps):
        series = _outcome_series(sim, rep, 0, 1)
        assert series[0] == series[1]
        assert series[2] == series[3]
        assert series[4] == series[5]
        for left, right in ((1, 2), (3, 4)):
            pairs += 1
            differ += int(series[left] != series[right])
    # A fresh N(0,1) factor flips a fair categorical about half the time between blocks.
    assert 0.35 < differ / pairs < 0.65

    # rho_p = 0 reproduces the independent stream in distribution (own factor child stream).
    n_days = 20
    kwargs: dict[str, Any] = {"replicates": 800, "n_days": n_days, "p_keep": 1.0, "row": "H0"}
    groups = _prepared("LAX", "MIA")
    base_mean, base_se = _critical_mean_se(simulate_family(groups, seed=31, **kwargs), n_days)
    zero_mean, zero_se = _critical_mean_se(
        simulate_family(groups, seed=37, persist=(3, 0.0), **kwargs), n_days
    )
    assert abs(base_mean - zero_mean) < 3.0 * math.hypot(base_se, zero_se)
    # Power check on the comparison: strong persistence visibly raises the critical value.
    strong_mean, strong_se = _critical_mean_se(
        simulate_family(groups, seed=41, persist=(5, 0.9), **kwargs), n_days
    )
    assert strong_mean - base_mean > 3.0 * math.hypot(base_se, strong_se)


# -------------------------------------------------------------------------- G1 worst path


def _expected_z(day: StationDay, x_rand: float) -> float | None:
    step = step_clock(
        rows._normalised(day.station, x_rand, day.netting, rows.production_variance(day)), 0.0
    )
    return step.z


def test_g1_all_lose_path_is_infeasible_for_exclusive_no_legs() -> None:
    day = make_station_day("LAX", (make_leg("T70", "no", 0.70), make_leg("T72", "no", 0.78)))
    prep = prepare_day(day)
    # Two exclusive NO legs: at most one loses, so the all-lose sum is not an outcome.
    all_lose_x = -(Decimal("0.70") + Decimal("0.78"))
    assert float(all_lose_x) not in [round(x, 12) for x in prep.xs]
    one_lost_x = -0.70 + (1.0 - 0.78)
    assert any(math.isclose(x, one_lost_x) for x in prep.xs)

    worst = rows.worst_feasible_z(day, prep.xs)
    all_lose = rows.all_lose_z(day)
    assert worst is not None
    assert all_lose is not None
    assert worst > all_lose
    assert worst == pytest.approx(_expected_z(day, min(prep.xs)))
    assert worst == pytest.approx(_expected_z(day, one_lost_x))
    assert rows.worst_feasible_z(make_station_day("LAX", ()), (0.0,)) is None


def test_maker_spec_g1_uses_worst_feasible_and_reports_all_lose() -> None:
    days = _all_no_days()
    config = _config(lambda_pool=0.5, take_rate_lower=0.5, r_sd=2.0, lambda_sd=1.0)
    document = _run(
        days,
        replicates=120,
        seed=3,
        config=config,
        spec=_maker_spec(),
        alphas=(0.10,),
        outer_resamples=0,
    )
    assert document["floor_spec"]["g1_path"] == "worst_feasible"
    assert document["floor_spec"]["mixes"] == ["M-pool"]
    context = document["g1_all_lose_z"]
    assert set(context) == {"M-pool"}
    day = days[0]
    all_lose = rows.all_lose_z(day)
    worst = rows.worst_feasible_z(day, prepare_day(day).xs)
    assert context["M-pool"] == pytest.approx(all_lose)
    assert worst is not None
    assert all_lose is not None
    assert worst > all_lose
    assert document["gates"]
    for row in document["gates"]:
        assert row["mix"] == "M-pool"
        assert row["z_all_lose"] == pytest.approx(all_lose)
        assert row["z_g1"] == pytest.approx(worst)
        expected = repeated_crossing(worst, c=row["c"], t_min=row["t_min"], t_low=row["t_low"])
        assert row["t_cross"] == expected
        early = repeated_crossing(all_lose, c=row["c"], t_min=row["t_min"], t_low=row["t_low"])
        assert expected is None or early is None or expected >= early


def test_run_floor_maker_spec_all_no_world_is_not_vetoed_by_empty_cells() -> None:
    days = _all_no_days()
    config = _config(lambda_pool=0.5, take_rate_lower=0.5, r_sd=2.0, lambda_sd=1.0)
    document = _run(
        days,
        replicates=120,
        seed=3,
        config=config,
        spec=_maker_spec(),
        alphas=(0.10, 0.20, 0.30),
        outer_resamples=0,
    )
    outcome = document["outcome"]
    # Under FQ_SPEC this world vetoes g1_unreachable on the empty M-yes cell (WP0 pin).
    assert outcome["failing_mix"] != "M-yes"
    assert {row["mix"] for row in document["gates"]} == {"M-pool"}
    assert {row["mix"] for row in document["rows"] if "mix" in row} == {"M-pool"}
    assert outcome["floor_mode"] == "sqrt_boundary"
    assert outcome["veto_cause"] is None
    assert outcome["c"] is not None


# ---------------------------------------------------------- binding set read from the spec


def test_maker_binding_c_takes_max_over_s8(monkeypatch: pytest.MonkeyPatch) -> None:
    groups = tuple((_one_leg_station("LAX"),) for _ in range(4))
    config = _config()
    cells = (*_fq_cal(), ("S8", "persist3"))
    s8 = gate.FloorSpec(
        mixes=("M-pool",),
        cal=cells,
        binding=(("H0", "none"), ("S8", "persist3")),
        persist=(("persist3", 5, 0.9),),
    )
    h0 = gate.FloorSpec(mixes=("M-pool",), cal=cells, binding=(("H0", "none"),))

    # Site 1: outer.binding_c reads spec.binding, so S8 enters the max.
    kwargs: dict[str, Any] = {
        "alpha": 0.10,
        "t_min": 1,
        "replicates": 300,
        "n_days": 30,
        "p_keep": 1.0,
        "seed": 7,
        "config": config,
    }
    c_h0 = outer.binding_c(groups, spec=h0, **kwargs)
    c_s8 = outer.binding_c(groups, spec=s8, **kwargs)
    assert c_s8 > c_h0
    assert outer._BINDING == (("H0", "none"), ("S4", "none"), ("S5", "bind"))

    # Sites 2 (report) and 3 (e2 sensitivity): run the whole floor and read both.
    labels: list[str] = []
    real_seed = engine._seed

    def spy(master: int, label: str) -> int:
        labels.append(label)
        return real_seed(master, label)

    monkeypatch.setattr(engine, "_seed", spy)
    document: dict[str, Any] = engine.run_floor(
        groups,
        gate_groups=groups,
        replicates=200,
        seed=5,
        config=config,
        spec=s8,
        alphas=(0.10,),
        outer_resamples=0,
    )
    binding_rows = [r for r in document["rows"] if r.get("role") == "binding"]
    by_row = {r["row"]: r["c_cell"] for r in binding_rows}
    assert set(by_row) == {"H0", "S8"}
    assert by_row["S8"] > by_row["H0"]
    outcome = document["outcome"]
    chosen = outcome["c"] if outcome["c"] is not None else outcome["diagnostics"]["c"]
    assert chosen == pytest.approx(max(by_row.values()))
    sensitivity = [r for r in document["rows"] if r.get("row") == "cal_at_max_rate"]
    assert len(sensitivity) == 1
    # lambda_pool 0.40 > take_rate_lower 0.25, so the sensitivity c is re-solved per binding row.
    assert any(label.startswith("sens|S8|persist3|M-pool|") for label in labels)
    assert any(label.startswith("sens|H0|none|M-pool|") for label in labels)
    assert not any(label.startswith("sens|S4|") for label in labels)
    # The sensitivity keeps every station-day (p_keep 1.0 vs the calibration's 0.625), so its c
    # sits above the calibration c: +0.32 at this seed. The band [-0.1, +0.5] is about 1 MC SE
    # of c below (200 replicates) and 1.5x the observed gap above.
    cal_c = max(by_row.values())
    assert cal_c - 0.1 <= sensitivity[0]["c"] <= cal_c + 0.5
    # S8 enters the sensitivity max: with S8 dropped from the binding set the c is smaller.
    h0_doc: dict[str, Any] = engine.run_floor(
        groups,
        gate_groups=groups,
        replicates=200,
        seed=5,
        config=config,
        spec=h0,
        alphas=(0.10,),
        outer_resamples=0,
    )
    h0_sens = [r for r in h0_doc["rows"] if r.get("row") == "cal_at_max_rate"]
    assert sensitivity[0]["c"] > h0_sens[0]["c"] + 0.2
