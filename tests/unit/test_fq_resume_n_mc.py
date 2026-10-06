"""FQ F5 FQ-PREREG: the N Monte-Carlo (`scripts/analysis/fq_resume_n_mc.py`).

Everything here is synthetic and seeded; no tape, no network, no holdout. Replicate
counts are small so the file runs in seconds.
"""

from __future__ import annotations

import ast
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, REPO_ROOT.as_posix())
from scripts.analysis import fq_mc_livedata as livedata
from scripts.analysis import fq_resume_n_mc as mc

MODULES = tuple(
    REPO_ROOT / "scripts/analysis" / f"{name}.py"
    for name in ("fq_resume_n_mc", "fq_mc_eprocess", "fq_mc_livedata", "fq_mc_type1")
)
STATIONS = ("KAAA", "KBBB")
RUNGS = ("B70.5", "B72.5", "B74.5", "B76.5", "T78", "T68")


def _synthetic_pool(
    days: int = 40, start: dt.date = dt.date(2025, 3, 1), *, with_bids: bool = True
) -> list[mc.PoolRung]:
    rows: list[mc.PoolRung] = []
    asks = (0.12, 0.24, 0.31, 0.22, 0.09, 0.55)
    for offset in range(days):
        day = start + dt.timedelta(days=offset)
        for station in STATIONS:
            for rung, ask in zip(RUNGS, asks, strict=True):
                rows.append(
                    mc.PoolRung(
                        station=station,
                        climate_day=day,
                        rung_id=rung,
                        yes_ask=ask,
                        yes_bid=(ask - 0.02) if with_bids else None,
                        result=bool((offset + len(rung)) % 3 == 0),
                    )
                )
    return rows


@pytest.fixture(scope="module")
def pool_days() -> list[mc.PoolDay]:
    return mc.group_days(_synthetic_pool())


def _design(**overrides: object) -> mc.Design:
    base: dict[str, object] = {
        "delta_h": 0.06,
        "m_cap": 2,
        "x_max": 4.0,
        "earliest_look_n": 5,
    }
    base.update(overrides)
    return mc.Design(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- E-25 pieces


def test_gamma_schedule_is_normalised_heavy_tail() -> None:
    gamma = mc.gamma_schedule(4)
    assert sum(gamma) == pytest.approx(1.0)
    assert list(gamma) == sorted(gamma, reverse=True)
    assert mc.alpha_k(1) == pytest.approx(0.025 * gamma[0])
    assert mc.alpha_k(1, promotions=1) == pytest.approx(0.025 * gamma[0] * 2)


def test_take_x_clips_upside_only() -> None:
    assert mc.take_x(1.0, 0.1, 2.0) == pytest.approx(2.0)  # 1/0.1 - 1 = 9, clipped
    assert mc.take_x(0.0, 0.1, 2.0) == pytest.approx(-1.0)  # downside never clipped
    assert mc.take_x(1.0, 0.8, 2.0) == pytest.approx(0.25)  # below the clip, untouched


def test_daily_y_pins_denominator_voids_and_excess_takes() -> None:
    assert mc.daily_y([], m_cap=2) == 0.0
    assert mc.daily_y([1.0], m_cap=2) == pytest.approx(0.5)  # empty slot contributes 0
    assert mc.daily_y([1.0, 0.0, 0.0], m_cap=2) == pytest.approx(0.5)  # a void is a 0 slot
    assert mc.daily_y([1.0, 1.0, 5.0], m_cap=2) == pytest.approx(1.0)  # takes past the cap excluded
    with pytest.raises(ValueError):
        mc.daily_y([1.0], m_cap=4)


def test_ties_are_ordered_by_station_rung_never_outcome_or_arrival() -> None:
    takes = [("KBBB", "B70.5", "yes"), ("KAAA", "B72.5", "no"), ("KAAA", "B70.5", "yes")]
    ordered = mc.order_takes(takes)
    assert [t[:2] for t in ordered] == [("KAAA", "B70.5"), ("KAAA", "B72.5"), ("KBBB", "B70.5")]
    assert mc.order_takes(list(reversed(takes))) == ordered


def test_lambda_is_predictable_and_capped_at_half() -> None:
    assert mc.agrapa_lambda(0.0, 0.0, 0, cap=0.5) == 0.0
    assert mc.agrapa_lambda(-5.0, 5.0, 10, cap=0.5) == 0.0  # losing history never bets long
    big = mc.agrapa_lambda(np.array([50.0]), np.array([60.0]), 50, cap=0.5)
    assert float(big[0]) <= 0.5
    assert mc.MAX_LAMBDA == 0.5


# ---------------------------------------------------------------- the pool and the holdout


def test_n_uses_out_of_fold_pre_20260701_only() -> None:
    rows = _synthetic_pool(days=4, start=dt.date(2026, 6, 28))  # 06-28 .. 07-01
    kept = mc.filter_pre_holdout(rows)
    assert kept
    assert max(r.climate_day for r in kept) == dt.date(2026, 6, 30)
    assert all(r.climate_day < mc.HOLDOUT_START for r in kept)
    assert mc.HOLDOUT_START == dt.date(2026, 7, 1)
    assert len(rows) > len(kept)  # the 07-01 rows were dropped, not silently kept


def test_pool_loader_drops_holdout_dated_tickers(tmp_path: Path) -> None:
    def candle(ticker: str) -> str:
        body = {
            "candlesticks": [
                {
                    "end_period_ts": 1,
                    "yes_ask": {"open": "1.0000", "close": "0.2500"},
                    "yes_bid": {"open": "0.0100", "close": "0.2000"},
                }
            ]
        }
        return json.dumps({"ticker": ticker, "response": body})

    cpath = tmp_path / "candles.jsonl"
    cpath.write_text(
        "\n".join(
            candle(t)
            for t in ("KXHIGHNY-25MAR01-B70.5", "KXHIGHNY-26JUN30-B70.5", "KXHIGHNY-26JUL02-B70.5")
        )
        + "\n"
    )
    pool = mc.load_pool(cpath, markets_dir=tmp_path, start=dt.date(2023, 1, 1))
    assert {r.climate_day for r in pool} == {dt.date(2025, 3, 1), dt.date(2026, 6, 30)}
    assert all(r.yes_ask == pytest.approx(0.25) for r in pool)  # open 1.0 is no offer: close used


def test_mc_never_calls_open_holdout(
    monkeypatch: pytest.MonkeyPatch, pool_days: list[mc.PoolDay]
) -> None:
    from breezy.analysis import nbp_calibration

    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError("the MC must never open the sealed holdout")

    monkeypatch.setattr(nbp_calibration, "open_holdout", boom)
    templates = mc.build_templates(pool_days, pi_fav=0.3, seed=1)
    batch = mc.simulate_pooled(templates, _design(), reps=20, days=30, seed=1, null=True)
    assert batch.n_d.shape == (20, 30)
    for module in MODULES:
        tree = ast.parse(module.read_text(encoding="utf-8"))
        called = {
            n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
        }
        assert "open_holdout" not in called, module
        imported = {
            a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names
        }
        assert "open_holdout" not in imported, module


# --------------------------------------------------------------------------- the live loop


def test_mc_replays_live_daily_loop_verbatim(
    monkeypatch: pytest.MonkeyPatch, pool_days: list[mc.PoolDay]
) -> None:
    from breezy.strategy.forecast_quantile_ladder import decision as live

    assert mc.evaluate is live.evaluate  # imported, never re-implemented
    assert mc.venue_fee_prob.__module__ == "breezy.strategy.weather_common.costs"
    assert mc.forecast_margin.__module__ == "breezy.strategy.forecast_quantile_ladder.margin"

    calls: list[tuple[str, str, str]] = []
    real = live.evaluate

    def spy(**kwargs: object):  # type: ignore[no-untyped-def]
        calls.append((str(kwargs["station"]), str(kwargs["rung_id"]), str(kwargs["side"])))
        return real(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(livedata, "evaluate", spy)
    day = pool_days[0]
    view = mc.draw_model_view(day, pi_fav=1.0, seed=3)
    takes = mc.replay_live_day(day, view, mc.LoopConfig())
    assert calls, "the loop must call the live take rule"
    sides = {c[2] for c in calls}
    assert sides == {"yes", "no"}  # both native instruments are evaluated
    assert takes, "pi_fav=1 must produce takes"
    assert all(t.be > t.ask for t in takes)  # BE = haircut ask + fee, always above the ask
    keys = [(t.station, t.rung_id) for t in takes]
    assert keys == sorted(keys)  # decision order is the pinned G-measurable order
    # one latch: no (station, rung, side) twice, and never both sides of one rung
    assert len({(t.station, t.rung_id) for t in takes}) == len(takes)


def test_no_side_with_empty_yes_bid_is_ineligible() -> None:
    pool = mc.group_days(_synthetic_pool(days=3, with_bids=False))
    day = pool[0]
    view = mc.draw_model_view(day, pi_fav=1.0, seed=5)
    takes = mc.replay_live_day(day, view, mc.LoopConfig())
    assert all(t.side == "yes" for t in takes)


def test_mc_includes_mixed_side_days(pool_days: list[mc.PoolDay]) -> None:
    templates = mc.build_templates(pool_days, pi_fav=0.5, seed=2)
    assert any(t.is_mixed_side for t in templates), "the pool must contain mixed-side days"
    mixed = mc.simulate_pooled(
        templates, _design(), reps=10, days=40, seed=4, null=True, mixed_only=True
    )
    assert mixed.n_d.min() >= 2


# --------------------------------------------------------------------------- outcomes


def test_h0_mc_outcomes_bernoulli_exactly_at_be(pool_days: list[mc.PoolDay]) -> None:
    assert mc.outcome_probability(0.37, delta_h=0.0, null=True) == 0.37
    # null=True ignores any delta: H0 is exactly BE.
    assert mc.outcome_probability(0.37, delta_h=0.2, null=True) == 0.37
    templates = mc.build_templates(pool_days, pi_fav=0.6, seed=7)
    batch = mc.simulate_pooled(templates, _design(), reps=400, days=60, seed=7, null=True)
    # per-take outcome mean equals mean BE (z-test, many draws)
    v = batch.valid
    resid = (batch.h - batch.be)[v]
    se = np.sqrt((batch.be[v] * (1 - batch.be[v])).sum()) / v.sum()
    assert abs(resid.mean()) < 4.0 * se


def test_h1_outcomes_from_delta_h_at_sampled_asks_residuals_only_for_rho_var(
    pool_days: list[mc.PoolDay],
) -> None:
    assert mc.outcome_probability(0.30, delta_h=0.05, null=False) == pytest.approx(0.35)
    assert mc.outcome_probability(0.98, delta_h=0.05, null=False) == 1.0  # capped
    templates = mc.build_templates(pool_days, pi_fav=0.6, seed=7)
    a = mc.simulate_pooled(templates, _design(delta_h=0.10), reps=500, days=60, seed=9, null=False)
    v = a.valid
    excess = (a.h - a.be)[v].mean()
    assert 0.07 < excess < 0.13  # tracks delta_h, not the residual sample
    # residuals feed rho and variance and nothing else
    rho, var = mc.residual_rho_var([[0.1, 0.2, -0.3], [0.4, 0.5]])
    assert var > 0.0
    assert -1.0 <= rho <= 1.0
    params = mc.simulate_pooled.__code__.co_varnames[: mc.simulate_pooled.__code__.co_argcount]
    assert "residuals" not in params


# --------------------------------------------------------------------------- power and N


def test_n_e_power_is_joint_power_of_min_ea_eb() -> None:
    # Hand-built scan: e_a crosses early, e_b only late; the joint crossing is the later one.
    reps, days = 6, 40
    batch = mc.ItemBatch(
        be=np.full((reps, days, 3), 0.3),
        ask=np.full((reps, days, 3), 0.2),
        p=np.full((reps, days, 3), 0.9),
        h=np.ones((reps, days, 3)),
        valid=np.tile(np.array([True, False, False]), (reps, days, 1)),
        n_d=np.ones((reps, days), dtype=np.int64),
    )
    y, z = mc.items_to_yz(batch, m_cap=2, x_max=4.0)
    scan = mc.eprocess_scan(
        y,
        z,
        np.cumsum(batch.n_d, axis=1),
        alphas=(0.05,),
        earliest_look_n=1,
        lam_max=0.5,
        mu_max=0.5,
        alpha_kill=0.05,
        x_max=4.0,
    )
    joint = scan.cross_joint[0]
    cross_a, cross_b = scan.cross_a[0], scan.cross_b[0]
    assert (joint >= 0).all()
    assert (joint >= np.maximum(cross_a, cross_b)).all()
    n_joint = mc.n_for_power(joint, target=0.8)
    assert n_joint is not None
    assert n_joint >= mc.n_for_power(cross_a, target=0.8)  # type: ignore[operator]
    # a stream where e_b never moves can never PASS jointly, however strong e_a is
    never_b = mc.eprocess_scan(
        y,
        np.zeros_like(z),
        np.cumsum(batch.n_d, axis=1),
        alphas=(0.05,),
        earliest_look_n=1,
        lam_max=0.5,
        mu_max=0.5,
        alpha_kill=0.05,
        x_max=4.0,
    )
    assert (never_b.cross_joint[0] < 0).all()
    assert (never_b.cross_a[0] >= 0).all()
    assert mc.n_for_power(never_b.cross_joint[0], target=0.8) is None


def test_n_for_power_is_the_smallest_n_reaching_target() -> None:
    cross = np.array([5, 7, 9, 11, -1])
    assert mc.n_for_power(cross, target=0.6) == 9
    assert mc.n_for_power(cross, target=0.8) == 11
    assert mc.n_for_power(cross, target=0.81) is None  # censored: unreachable inside the horizon


def test_n_reported_over_delta_h_and_take_rate_interval(pool_days: list[mc.PoolDay]) -> None:
    grid = mc.run_grid(
        pool_days,
        deltas=(0.05, 0.10),
        rates=(0.5, 1.0),
        m_caps=(2, 3),
        x_maxes=(2.0, 4.0),
        reps=40,
        n_max=60,
        seed=11,
        earliest_look_n=5,
    )
    keys = {(c["m_cap"], c["x_max"], c["delta_h"], c["take_rate"]) for c in grid}
    assert len(keys) == 2 * 2 * 2 * 2
    assert all("n_e_power" in c and "n_e_power_by_k" in c for c in grid)
    assert all("realised_take_rate" in c for c in grid)


def test_take_rate_calibration_hits_the_requested_rate(pool_days: list[mc.PoolDay]) -> None:
    pi, templates = mc.calibrate_take_rate(pool_days, target_rate=0.8, seed=3)
    realised = float(np.mean([t.n for t in templates]))
    assert 0.0 < pi <= 1.0
    assert realised == pytest.approx(0.8, abs=0.35)


def test_n_starvation_compares_projection_to_n() -> None:
    out = mc.n_starvation(
        n_required={0.25: 400, 1.0: 150},
        d0=dt.date(2026, 10, 10),
        uptime_floor=0.9,
    )
    assert out["kill_date"] == "2027-01-25"
    assert out["days_to_kill"] == (dt.date(2027, 1, 25) - dt.date(2026, 10, 10)).days + 1
    lo = out["by_rate"]["0.25"]
    assert lo["n_available"] == int(0.25 * out["days_to_kill"] * 0.9)
    assert lo["starved"] is True
    assert out["m1_fallback_preregistered"] is True
    assert "M1 fallback is pre-registered" in out["statement"]


# --------------------------------------------------------------------------- type I


def test_mc_type1_mixed_side_le_alpha(pool_days: list[mc.PoolDay]) -> None:
    result = mc.type1_mixed_side(
        pool_days,
        designs=[(2, 4.0), (3, 4.0)],
        reps=300,
        days=50,
        seed=21,
        pi_fav=0.6,
        earliest_look_n=5,
    )
    assert result["mixed_side_fraction"] > 0.5
    assert result["positive_covariance"] is True
    for row in result["rows"]:
        for k, rate in row["type1_joint"].items():
            assert rate <= mc.alpha_k(int(k)) + 1e-12, (row, k)
        for k, rate in row["type1_a"].items():
            assert rate <= mc.alpha_k(int(k)) + 1e-12, (row, k)


def test_mc_type1_intraday_dependent_take_count_le_alpha() -> None:
    result = mc.type1_intraday(
        designs=[(2, 4.0), (3, 4.0)],
        reps=60,
        days=25,
        seed=33,
        earliest_look_n=5,
    )
    assert result["take_count_varies_with_signal"] is True
    assert result["signal_outcome_correlation"] > 0.0
    assert result["true_conditional_edge"] == 0.0
    for row in result["rows"]:
        for k, rate in row["type1_joint"].items():
            assert rate <= mc.alpha_k(int(k)) + 1e-12, (row, k)
        for k, rate in row["type1_a"].items():
            assert rate <= mc.alpha_k(int(k)) + 1e-12, (row, k)


def test_kill_cs_flags_a_clearly_negative_stream_and_spares_a_positive_one() -> None:
    reps, days = 4, 80
    neg = np.full((reps, days), -0.5)
    pos = np.full((reps, days), 0.5)
    k_neg = mc.kill_first_n(
        neg,
        np.cumsum(np.ones((reps, days), dtype=np.int64), axis=1),
        x_max=2.0,
        alpha_kill=0.05,
        earliest_look_n=1,
    )
    k_pos = mc.kill_first_n(
        pos,
        np.cumsum(np.ones((reps, days), dtype=np.int64), axis=1),
        x_max=2.0,
        alpha_kill=0.05,
        earliest_look_n=1,
    )
    assert (k_neg >= 0).all()
    assert (k_pos < 0).all()


def test_exact_null_eprocess_is_a_supermartingale_in_expectation() -> None:
    # E[prod(1+lam*Y)] <= 1 for predictable lam under a mean-zero Y.
    rng = np.random.default_rng(0)
    y = np.where(rng.random((4000, 30)) < 0.2, 4.0, -1.0) * 1.0
    y = y - y.mean()  # exactly mean-zero overall
    z = np.zeros_like(y)
    scan = mc.eprocess_scan(
        y,
        z,
        np.cumsum(np.ones_like(y, dtype=np.int64), axis=1),
        alphas=(0.02,),
        earliest_look_n=1,
        lam_max=0.5,
        mu_max=0.5,
        alpha_kill=0.05,
        x_max=4.0,
    )
    assert scan.mean_final_e_a <= 1.0 + 0.1


# --------------------------------------------------------------------------- the CLI


def _write_candles(path: Path) -> None:
    asks = {"B70.5": 0.12, "B72.5": 0.24, "B74.5": 0.31, "B76.5": 0.22, "T78": 0.09, "T68": 0.55}
    lines = []
    for series in ("KXHIGHAAA", "KXHIGHBBB"):
        for day in range(1, 29):
            for rung, ask in asks.items():
                body = {
                    "candlesticks": [
                        {
                            "end_period_ts": 1,
                            "yes_ask": {"open": "1.0000", "close": f"{ask:.4f}"},
                            "yes_bid": {"open": "0.0100", "close": f"{ask - 0.02:.4f}"},
                        }
                    ]
                }
                ticker = f"{series}-25MAR{day:02d}-{rung}"
                lines.append(json.dumps({"ticker": ticker, "response": body}))
    # a holdout-window market that must never reach the pool
    lines.append(json.dumps({"ticker": "KXHIGHAAA-26JUL02-T99", "response": body}))
    path.write_text("\n".join(lines) + "\n")


def test_cli_runs_end_to_end_and_states_the_starvation_outcome(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    candles = tmp_path / "candles.jsonl"
    _write_candles(candles)
    out = tmp_path / "out"
    rc = mc.main(
        [
            "--candles", str(candles), "--markets-dir", str(tmp_path), "--outdir", str(out),
            "--deltas", "0.10,0.20", "--rates", "0.5,1.0", "--m-caps", "2,3", "--x-maxes", "2,4",
            "--reps", "30", "--n-max", "60", "--pool-days", "20", "--earliest-look-n", "5",
            "--type1-reps", "20", "--type1-days", "20", "--type1-intraday-reps", "4",
            "--type1-intraday-days", "4", "--claim-excess", "0.04", "--sens-reps", "20",
        ]
    )  # fmt: skip
    assert rc == 0
    result = json.loads(next(out.glob("fq_resume_n_mc_seed*.json")).read_text())
    assert result["pool"]["max_climate_day"] < mc.HOLDOUT_START.isoformat()
    assert len(result["cells"]) == 2 * 2 * 2 * 2
    assert {"i", "ii"} == set(result["type1"])
    assert result["n_starvation"]["m1_fallback_preregistered"] is True
    assert "M1 fallback is pre-registered" in capsys.readouterr().out


def test_every_cli_script_has_a_main_guard() -> None:
    for name in ("fq_resume_n_mc", "prereg_precommit_check"):
        text = (REPO_ROOT / "scripts/analysis" / f"{name}.py").read_text(encoding="utf-8")
        assert 'if __name__ == "__main__":' in text, name
