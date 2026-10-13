"""MAKER S3 WP3: inputs, frozen cell, verdict, horizon sensitivity, early stop, artifact, CLI."""

from __future__ import annotations

import copy
import json
import math
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from scripts.analysis import fq_loss_floor_mc_maker as maker
from scripts.analysis import fq_loss_floor_mc_maker_verdict as vmod
from scripts.analysis.fq_loss_floor_mc_engine import _run as engine_run
from scripts.analysis.fq_loss_floor_mc_gate import HORIZON, inclusive_days, t_low_count

ICC = 0.5 / 7
GRID = (0.70, 0.75, 0.80)

S2_DOC: dict[str, Any] = {
    "verdict": "NOT-KILLED",
    "fill_rate_2x": {"point": 0.30, "lower95": 0.22},
    "fill_rate_2x_lowest_rung": {"point": 0.20, "lower95": 0.14},
    "fill_rate_base": {"point": 0.35},
    "two_fill_share": 0.4,
    "bid_bearing_share": 0.8,
    "fill_icc": 0.12,
    "n0": 40,
    "realised_bid_iqr": [0.72, 0.78],
    "realised_bid_median": 0.75,
}
CAP_PIN: dict[str, Any] = {"holdout_start_date": "2026-11-23", "calendar_cap_date": "2027-06-30"}


def _write(tmp: Path, name: str, doc: Any) -> Path:
    path = tmp / name
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return path


def _s1_rows(
    listed: int, unlisted: int, outage_days: int, *, start: int = 1
) -> list[dict[str, Any]]:
    """Per climate day: LAX/MDW/MIA/SFO plus one sibling station (NYC-free)."""
    rows: list[dict[str, Any]] = []
    day = start

    def add(reasons: dict[str, str], seen: dict[str, bool]) -> None:
        nonlocal day
        for station, reason in reasons.items():
            rows.append(
                {
                    "station": station,
                    "climate_day": f"2026-09-{day:02d}",
                    "reason": reason,
                    "first_seen_ns": 1 if seen[station] else None,
                }
            )
        day += 1

    four = ("LAX", "MDW", "MIA", "SFO")
    for _ in range(listed):  # 4 listed station-days
        add({s: "COVERED" for s in (*four, "DEN")}, {s: True for s in (*four, "DEN")})
    for _ in range(unlisted):  # LAX unlisted while a sibling was seen
        reasons = {s: "COVERED" for s in (*four, "DEN")}
        seen = {s: True for s in (*four, "DEN")}
        reasons["LAX"], seen["LAX"] = "NEVER_LISTED", False
        add(reasons, seen)
    for _ in range(outage_days):  # recorder outage: nobody seen
        add({s: "NEVER_LISTED" for s in (*four, "DEN")}, {s: False for s in (*four, "DEN")})
    return rows


def _cell(k: int, b: float, f: float, c: float | None, **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "k": k,
        "b": b,
        "f": f,
        "theta": 0.0695,
        "replicates": 100,
        "seed": 1,
        "n_dates": 20,
        "floor_mode": "sqrt_boundary" if c is not None else "unreachable_veto",
        "power_class": "gross_loss_tripwire",
        "alpha_star": 0.10,
        "c": c,
        "c_deff": None if c is None else c / math.sqrt(1.5),
        "t_min": 5,
        "freeze_blocked": None,
        "certified_ticks": 100 + int(100 * f),
    }
    base.update(kw)
    return base


def _ok(**kw: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "frozen_c_g1_holds": True,
        "frozen_c_g3_by_delta": {"-0.16": 0.9, "-0.08": 0.5, "-0.04": 0.2},
        "frozen_c_g3_holds": True,
        "frozen_c_h0_rate_by_row": {"H0": 0.09, "S4": 0.09, "S5-bind": 0.09, "S8-persist3": 0.09},
        "frozen_c_h0_ok": True,
    }
    out.update(kw)
    return out


def _grid_cells(f: float, c_by: Mapping[tuple[int, float], float | None]) -> list[dict[str, Any]]:
    return [_cell(k, b, f, c_by[(k, b)]) for k in (2, 1) for b in GRID]


C_BY = {
    (2, 0.70): 2.0,
    (2, 0.75): 2.4,
    (2, 0.80): 2.2,
    (1, 0.70): 1.9,
    (1, 0.75): 2.1,
    (1, 0.80): 2.0,
}


# ------------------------------------------------------------------------------------- inputs


def test_binding_mode_refuses_missing_s2_field(tmp_path: Path) -> None:
    for field in S2_DOC:
        doc = {k: v for k, v in S2_DOC.items() if k != field}
        if field == "realised_bid_iqr":
            continue  # IQR may be absent: all three bids bind
        with pytest.raises(maker.MakerRefusal, match=field):
            maker.load_s2(_write(tmp_path, f"s2_{field}.json", doc))
    nested = copy.deepcopy(S2_DOC)
    del nested["fill_rate_2x"]["lower95"]
    with pytest.raises(maker.MakerRefusal, match="lower95"):
        maker.load_s2(_write(tmp_path, "s2_nested.json", nested))
    ok = maker.load_s2(_write(tmp_path, "s2_ok.json", S2_DOC))
    assert (ok.f_kill, ok.f_pass) == (0.30, 0.22)
    assert (ok.f_kill_k1, ok.f_pass_k1) == (0.20, 0.14)
    assert ok.fill_icc == 0.12 and len(ok.sha256) == 64 and ok.lines["fill_icc"] > 1
    low_icc = maker.load_s2(_write(tmp_path, "s2_low.json", {**S2_DOC, "fill_icc": 0.01}))
    assert low_icc.fill_icc == ICC  # max(S2 ICC, 0.5/7)


def test_binding_mode_refuses_s2_no_go(tmp_path: Path) -> None:
    with pytest.raises(maker.MakerRefusal, match="NO-GO"):
        maker.load_s2(_write(tmp_path, "s2.json", {**S2_DOC, "verdict": "NO-GO"}))
    with pytest.raises(maker.MakerRefusal, match="verdict"):
        maker.load_s2(_write(tmp_path, "s2b.json", {**S2_DOC, "verdict": "MAYBE"}))
    unscreened = maker.load_s2(
        _write(tmp_path, "s2c.json", {**S2_DOC, "verdict": "NOT-KILLED-UNSCREENED"})
    )
    assert unscreened.verdict == "NOT-KILLED-UNSCREENED"
    out = tmp_path / "out.json"
    s1 = tmp_path / "s1.jsonl"
    s1.write_text("\n".join(json.dumps(r) for r in _s1_rows(30, 0, 0)) + "\n")
    argv = [
        "--binding",
        "--s2-artifact",
        str(_write(tmp_path, "nogo.json", {**S2_DOC, "verdict": "NO-GO"})),
        "--s1-artifact",
        str(s1),
        "--s5-cap-pin",
        str(_write(tmp_path, "pin.json", CAP_PIN)),
        "--out",
        str(out),
    ]
    assert maker.main(argv) == 2
    assert not out.exists()


def test_binding_mode_refuses_realised_bid_outside_floor_cap(tmp_path: Path) -> None:
    for bad in (0.82, 0.65):
        with pytest.raises(maker.MakerRefusal, match="B_FLOOR|B_CAP"):
            maker.load_s2(
                _write(tmp_path, f"s2_{bad}.json", {**S2_DOC, "realised_bid_median": bad})
            )
        with pytest.raises(maker.MakerRefusal, match="B_FLOOR|B_CAP"):
            maker.select_frozen_cell(_grid_cells(0.3, C_BY), b_median=bad, k_admitted=2)


def test_binding_cells_round_iqr_outward_and_follow_admitted_k(tmp_path: Path) -> None:
    def cells(iqr: Any, k: int | None = None) -> list[tuple[int, float]]:
        median = 0.75 if iqr is None else min(max(0.75, iqr[0]), iqr[1])  # the IQR holds the median
        doc = {**S2_DOC, "realised_bid_iqr": iqr, "realised_bid_median": median}
        s2 = maker.load_s2(_write(tmp_path, "s2.json", doc))
        return sorted((c.k, c.b) for c in maker.binding_cells(s2, admitted_k=k))

    assert cells([0.72, 0.78]) == sorted((k, b) for k in (1, 2) for b in GRID)
    assert cells([0.76, 0.78]) == sorted((k, b) for k in (1, 2) for b in (0.75, 0.80))
    assert cells([0.75, 0.75], 2) == [(2, 0.75)]
    assert cells(None) == sorted((k, b) for k in (1, 2) for b in GRID)
    one = {
        (c.k): (c.f_kill, c.f_pass)
        for c in maker.binding_cells(maker.load_s2(_write(tmp_path, "s2k.json", S2_DOC)))
    }
    assert one[2] == (0.30, 0.22) and one[1] == (0.20, 0.14)


def test_binding_mode_refuses_missing_s5_cap_pin(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    s2 = _write(tmp_path, "s2.json", S2_DOC)
    s1 = tmp_path / "s1.jsonl"
    s1.write_text("\n".join(json.dumps(r) for r in _s1_rows(30, 0, 0)) + "\n")
    base = [
        "--binding",
        "--s2-artifact",
        str(s2),
        "--s1-artifact",
        str(s1),
        "--out",
        str(tmp_path / "o.json"),
    ]
    assert maker.main(base) == 2
    assert "--s5-cap-pin" in capsys.readouterr().err
    assert maker.main([*base, "--s5-cap-pin", str(tmp_path / "missing.json")]) == 2
    with pytest.raises(maker.MakerRefusal, match="calendar_cap_date"):
        maker.load_s5_cap_pin(_write(tmp_path, "bad.json", {"holdout_start_date": "2026-11-23"}))
    with pytest.raises(maker.MakerRefusal, match="L_cap"):
        maker.load_s5_cap_pin(
            _write(tmp_path, "neg.json", {**CAP_PIN, "calendar_cap_date": "2026-01-01"})
        )
    pin = maker.load_s5_cap_pin(_write(tmp_path, "ok.json", CAP_PIN))
    assert pin.l_cap == inclusive_days(pin.holdout_start, pin.cap_date) == 220
    assert (
        maker.main(
            [*base, "--s5-cap-pin", str(_write(tmp_path, "pin.json", CAP_PIN)), "--inputs-only"]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert (
        "listing_rate_4stn=1.0" in out and "L_cap=220" in out and "realised_bid_median=0.75" in out
    )


def test_binding_mode_refuses_listing_rate_below_pin(tmp_path: Path) -> None:
    rows = _s1_rows(listed=8, unlisted=10, outage_days=0)  # 62 listed / 72 -> 0.861
    s1 = tmp_path / "s1.jsonl"
    s1.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    with pytest.raises(maker.MakerRefusal, match="listing_rate_4stn"):
        maker.load_s1(s1)
    rate = maker.listing_rate_4stn(rows)
    assert (rate.listed, rate.unlisted) == (62, 10)
    assert rate.listing_rate == pytest.approx(62 / 72)
    assert rate.listing_rate < 0.91
    good = maker.listing_rate_4stn(_s1_rows(listed=30, unlisted=1, outage_days=0))
    assert good.listing_rate == pytest.approx(123 / 124) and good.listing_rate >= 0.91


def test_listing_rate_counts_recorder_outage_as_unknown(tmp_path: Path) -> None:
    rows = _s1_rows(listed=10, unlisted=0, outage_days=2)
    rows.append(
        {
            "station": "LAX",
            "climate_day": "2026-08-01",
            "reason": "PRE_TRADE_CAPTURE",
            "first_seen_ns": None,
        }
    )
    rows.append(  # AMBIGUOUS counts as listed
        {
            "station": "MIA",
            "climate_day": "2026-08-02",
            "reason": "AMBIGUOUS_NO_CLEAN_INSTANCE",
            "first_seen_ns": 5,
        }
    )
    rate = maker.listing_rate_4stn(rows)
    assert rate.unknown == 8  # 2 outage days x 4 stations
    assert rate.unlisted == 0
    assert rate.listed == 41  # 10 days x 4 + the ambiguous row; PRE_TRADE excluded entirely
    assert rate.listing_rate == 1.0
    assert rate.unknown_share == pytest.approx(8 / 49)
    # a station NEVER_LISTED while a sibling was seen is UNLISTED, not unknown
    mixed = maker.listing_rate_4stn(_s1_rows(listed=10, unlisted=1, outage_days=0))
    assert (mixed.unlisted, mixed.unknown) == (1, 0)
    heavy = _s1_rows(listed=10, unlisted=0, outage_days=5)  # 20/60 = 0.33 unknown
    s1 = tmp_path / "s1.jsonl"
    s1.write_text("\n".join(json.dumps(r) for r in heavy) + "\n")
    with pytest.raises(maker.MakerRefusal, match="unknown_share"):
        maker.load_s1(s1)
    assert maker.listing_rate_4stn(heavy).listing_rate == 1.0


# -------------------------------------------------------------------- frozen cell and verdict


def test_verdict_reachable_underdetermined_unreachable() -> None:
    assert maker.verdict([True, True], [True, True]) == "REACHABLE"
    assert maker.verdict([True, False], [True, True]) == "UNDERDETERMINED"
    assert maker.verdict([False, False], [True, True]) == "UNDERDETERMINED"
    assert maker.verdict([True, True], [True, False]) == "UNREACHABLE"
    assert maker.verdict([False, True], [False, True]) == "UNREACHABLE"
    with pytest.raises(ValueError):
        maker.verdict([], [])
    with pytest.raises(ValueError):
        maker.verdict([True], [True, True])


def _evaluate(
    kill: list[dict[str, Any]],
    pas: list[dict[str, Any]],
    recheck: Callable[[Mapping[str, Any], Mapping[str, Any]], dict[str, Any]],
    *,
    b_median: float = 0.75,
    k: int | None = 2,
) -> dict[str, Any]:
    return maker.evaluate_binding(kill, pas, b_median=b_median, k_admitted=k, recheck=recheck)


def test_verdict_kill_reads_stressed_point_and_pass_reads_stressed_lower_bound() -> None:
    kill, pas = _grid_cells(0.30, C_BY), _grid_cells(0.22, C_BY)

    def fails_at(f: float) -> Callable[[Mapping[str, Any], Mapping[str, Any]], dict[str, Any]]:
        def recheck(cell: Mapping[str, Any], frozen: Mapping[str, Any]) -> dict[str, Any]:
            if (cell["k"], cell["b"], cell["f"]) == (1, 0.80, f):
                return _ok(frozen_c_g3_holds=False)
            return _ok()

        return recheck

    assert _evaluate(kill, pas, lambda c, f: _ok())["verdict"] == "REACHABLE"
    assert _evaluate(kill, pas, fails_at(0.22))["verdict"] == "UNDERDETERMINED"
    assert _evaluate(kill, pas, fails_at(0.30))["verdict"] == "UNREACHABLE"
    # a veto at f_pass only is UNDERDETERMINED; at f_kill it is UNREACHABLE
    pas_veto = _grid_cells(0.22, {**C_BY, (1, 0.80): None})
    assert _evaluate(kill, pas_veto, lambda c, f: _ok())["verdict"] == "UNDERDETERMINED"
    kill_veto = _grid_cells(0.30, {**C_BY, (1, 0.80): None})
    assert _evaluate(kill_veto, pas, lambda c, f: _ok())["verdict"] == "UNREACHABLE"


def test_frozen_c_reevaluates_g1_g3_on_every_binding_cell() -> None:
    kill = _grid_cells(0.30, C_BY)
    pas = _grid_cells(0.22, C_BY)
    seen: list[tuple[int, float, float, float, int, float]] = []

    def recheck(cell: Mapping[str, Any], frozen: Mapping[str, Any]) -> dict[str, Any]:
        seen.append(
            (cell["k"], cell["b"], cell["f"], frozen["c"], frozen["t_min"], frozen["alpha_star"])
        )
        return _ok()

    # b midpoint 0.725 with k admitted 2: larger c of (2,0.70)=2.0 and (2,0.75)=2.4
    out = _evaluate(kill, pas, recheck, b_median=0.725, k=2)
    assert out["frozen_cell"] == {"k": 2, "b": 0.75, "f_kill": 0.30}
    assert out["frozen_c"] == 2.4 and out["frozen_c_deff"] == pytest.approx(2.4 / math.sqrt(1.5))
    assert out["frozen_t_min"] == 5 and out["frozen_alpha_star"] == 0.10
    assert len(seen) == 12 and {s[3] for s in seen} == {2.4}  # every cell, both f, same frozen c
    assert {(s[0], s[1]) for s in seen} == {(k, b) for k in (1, 2) for b in GRID}
    for cell in out["cells"]:
        for key in (
            "frozen_c_g1_holds",
            "frozen_c_g3_by_delta",
            "frozen_c_h0_rate_by_row",
            "frozen_c_pass",
        ):
            assert key in cell
        assert "certified_ticks" in cell and "c_deff" in cell
    # exact grid point, k undetermined: larger c of the two k cells at b=0.75 (2.4 vs 2.1)
    assert _evaluate(kill, pas, lambda c, f: _ok(), b_median=0.75, k=None)["frozen_c"] == 2.4
    # k = 1 admitted, exact b: that cell's c
    assert _evaluate(kill, pas, lambda c, f: _ok(), b_median=0.80, k=1)["frozen_c"] == 2.0
    # a cell with different tick count fails the frozen-c H0 re-check: the verdict flips
    kill2 = [
        dict(c, certified_ticks=(400 if (c["k"], c["b"]) == (1, 0.70) else c["certified_ticks"]))
        for c in kill
    ]

    def h0_fail(cell: Mapping[str, Any], frozen: Mapping[str, Any]) -> dict[str, Any]:
        if (cell["k"], cell["b"]) == (1, 0.70):
            return _ok(frozen_c_h0_ok=False, frozen_c_h0_rate_by_row={"H0": 0.2, "S4": 0.1})
        return _ok()

    flipped = _evaluate(kill2, pas, h0_fail, b_median=0.75, k=2)
    assert flipped["verdict"] == "UNREACHABLE"
    bad = next(c for c in flipped["cells"] if (c["k"], c["b"], c["f"]) == (1, 0.70, 0.30))
    assert bad["frozen_c_pass"] is False and bad["frozen_c_h0_rate_by_row"]["H0"] == 0.2


def test_recheck_cell_reports_g1_g3_and_h0_rates_at_frozen_c() -> None:
    cell = maker.run_cell(
        maker.MakerMix(0.5, 0.75, 2, 1.0, 0.5, ICC),
        replicates=200,
        outer_resamples=0,
        outer_replicates=0,
        seed=maker.SEED,
        n_dates=100,
    )
    assert cell["floor_mode"] == "sqrt_boundary", cell
    frozen = {"c": 50.0, "t_min": cell["t_min"], "alpha_star": cell["alpha_star"]}
    loose = vmod.recheck_cell(cell, frozen)
    assert set(loose["frozen_c_h0_rate_by_row"]) == {"H0", "S4", "S5-bind", "S8-persist3"}
    assert loose["frozen_c_h0_ok"] is True and loose["frozen_c_g1_holds"] is False
    assert loose["frozen_c_g3_holds"] is False and set(loose["frozen_c_g3_by_delta"]) == {
        "-0.16",
        "-0.08",
        "-0.04",
    }
    tight = vmod.recheck_cell(cell, {**frozen, "c": 0.05})
    assert tight["frozen_c_h0_ok"] is False and tight["frozen_c_g3_holds"] is True
    own = vmod.recheck_cell(cell, {**frozen, "c": cell["c"]})
    assert own["frozen_c_h0_ok"] is True and own["frozen_c_g1_holds"] is True


def test_freeze_blocked_cell_is_unreachable() -> None:
    blocked = _cell(
        1,
        0.80,
        0.30,
        None,
        floor_mode=None,
        power_class="none",
        freeze_blocked={"reason": "s6_failed", "detail": "x"},
    )
    kill = [blocked if (c["k"], c["b"]) == (1, 0.80) else c for c in _grid_cells(0.30, C_BY)]
    out = _evaluate(kill, _grid_cells(0.22, C_BY), lambda c, f: _ok())
    assert out["verdict"] == "UNREACHABLE"
    assert next(c for c in out["cells"] if c["freeze_blocked"])["frozen_c_pass"] is False
    # the frozen candidate itself blocked: no frozen c, still UNREACHABLE
    only = [blocked]
    out2 = maker.evaluate_binding(
        only, only, b_median=0.80, k_admitted=1, recheck=lambda c, f: _ok()
    )
    assert out2["verdict"] == "UNREACHABLE" and out2["frozen_c"] is None


def test_theta_008_cell_is_report_only(tmp_path: Path) -> None:
    kill, pas = _grid_cells(0.30, C_BY), _grid_cells(0.22, C_BY)
    evaluation = _evaluate(kill, pas, lambda c, f: _ok())
    theta_ok = [_cell(2, 0.75, 0.22, 2.5, theta=0.08)]
    theta_bad = [_cell(2, 0.75, 0.22, None, theta=0.08)]
    a = maker.assemble_artifact(evaluation, report_cells=theta_ok)
    b = maker.assemble_artifact(evaluation, report_cells=theta_bad)
    assert a["verdict"] == b["verdict"] == "REACHABLE"
    assert (
        a["report_cells"][0]["theta"] == 0.08
        and b["report_cells"][0]["floor_mode"] == "unreachable_veto"
    )
    assert all(c["theta"] == 0.0695 for c in a["cells"])
    assert maker.STRESS_THETA == 0.08


def test_borderline_g3_triggers_one_pinned_rerun(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[int, int]] = []
    se = math.sqrt(0.25 * 0.75 / 10_000)

    def fake(
        mix: Any,
        *,
        replicates: int,
        outer_resamples: int,
        outer_replicates: int,
        seed: int,
        n_dates: int = 1000,
    ) -> dict[str, Any]:
        calls.append((replicates, seed))
        g3 = 0.25 + 0.5 * se if replicates == 10_000 else 0.9
        return _cell(
            2,
            0.75,
            0.3,
            2.0,
            replicates=replicates,
            seed=seed,
            g3_by_delta={"-0.16": g3, "-0.08": 0.3, "-0.04": 0.1},
            alpha_star=0.10,
        )

    monkeypatch.setattr(maker, "run_cell", fake)
    mix = maker.MakerMix(0.3, 0.75, 2, 1.0, 0.5, ICC)
    out = maker.run_cell_final(
        mix, replicates=10_000, outer_resamples=20, outer_replicates=2000, seed=maker.SEED
    )
    assert calls == [(10_000, maker.SEED), (50_000, 20261013)]
    assert (
        out["borderline_rerun"] is True and out["replicates"] == 50_000 and out["seed"] == 20261013
    )
    assert out["g3_by_delta"]["-0.16"] == 0.9  # the re-run is final, never re-checked
    calls.clear()

    def clear_cut(mix: Any, **kw: Any) -> dict[str, Any]:
        calls.append((kw["replicates"], kw["seed"]))
        return _cell(
            2,
            0.75,
            0.3,
            2.0,
            g3_by_delta={"-0.16": 0.9},
            alpha_star=0.10,
            replicates=kw["replicates"],
        )

    monkeypatch.setattr(maker, "run_cell", clear_cut)
    out2 = maker.run_cell_final(
        mix, replicates=10_000, outer_resamples=20, outer_replicates=2000, seed=maker.SEED
    )
    assert len(calls) == 1 and out2["borderline_rerun"] is False
    assert not maker.needs_borderline_rerun(_cell(2, 0.75, 0.3, None, alpha_star=None))


# ----------------------------------------------------------------------------- early stop


def _veto(k: int, b: float, f: float, **kw: Any) -> dict[str, Any]:
    return _cell(k, b, f, None, **kw)


def _sweep(override: dict[Any, Any] | None = None) -> list[dict[str, Any]]:
    override = override or {}
    return [
        override.get((m.rungs, m.bid, m.fill_rate), _veto(m.rungs, m.bid, m.fill_rate))
        for m in maker.sweep_mixes()
    ]


def test_sweep_all_veto_triggers_early_stop_after_confirm_rerun() -> None:
    confirmed: list[Any] = []

    def confirm_veto(mix: Any) -> dict[str, Any]:
        confirmed.append(mix)
        return _veto(mix.rungs, mix.bid, mix.fill_rate)

    out = maker.sweep_early_stop(_sweep(), confirm_veto)
    assert out == {
        "early_stop": "sweep_all_veto",
        "early_stop_basis": {"f_max": 0.5, "beta": 1.0, "replicates": 10_000},
    }
    assert len(confirmed) == 6 and {m.fill_rate for m in confirmed} == {0.5}
    assert {(m.rungs, m.bid) for m in confirmed} == {(k, b) for k in (1, 2) for b in GRID}
    # one sweep cell reachable: no confirm, no early stop
    confirmed.clear()
    reach = {(2, 0.75, 0.5): _cell(2, 0.75, 0.5, 2.0)}
    assert maker.sweep_early_stop(_sweep(reach), confirm_veto) is None and not confirmed

    # confirm re-run reaches on one cell: no early stop
    def confirm_one(mix: Any) -> dict[str, Any]:
        if (mix.rungs, mix.bid) == (2, 0.80):
            return _cell(2, 0.80, 0.5, 2.0)
        return _veto(mix.rungs, mix.bid, mix.fill_rate)

    assert maker.sweep_early_stop(_sweep(), confirm_one) is None
    # freeze_blocked anywhere never counts, sweep side
    confirmed.clear()
    blocked = {"reason": "s6_failed", "detail": "d"}
    fb = {(1, 0.70, 0.1): _cell(1, 0.70, 0.1, None, floor_mode=None, freeze_blocked=blocked)}
    assert maker.sweep_early_stop(_sweep(fb), confirm_veto) is None and not confirmed

    # ... and confirm side
    def confirm_blocked(mix: Any) -> dict[str, Any]:
        if (mix.rungs, mix.bid) == (1, 0.75):
            return _cell(1, 0.75, 0.5, None, floor_mode=None, freeze_blocked=blocked)
        return _veto(mix.rungs, mix.bid, mix.fill_rate)

    assert maker.sweep_early_stop(_sweep(), confirm_blocked) is None
    with pytest.raises(ValueError, match="30"):
        maker.sweep_early_stop(_sweep()[:5], confirm_veto)


# ------------------------------------------------------------------------ horizon and window


def _real_cell() -> dict[str, Any]:
    return maker.run_cell(
        maker.MakerMix(0.5, 0.75, 2, 1.0, 0.5, ICC),
        replicates=200,
        outer_resamples=0,
        outer_replicates=0,
        seed=maker.SEED,
        n_dates=100,
    )


def test_horizon_sensitivity_resimulates_to_l_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    cell = _real_cell()
    frozen = {"c": 1.2, "t_min": cell["t_min"], "alpha_star": cell["alpha_star"]}
    base = engine_run
    days_seen: list[int] = []

    def spy(*args: Any, **kwargs: Any) -> Any:
        days_seen.append(kwargs["n_days"])
        return base(*args, **kwargs)

    monkeypatch.setattr(vmod, "_run", spy)
    short = vmod.horizon_sensitivity(cell, frozen, l_cap=110)
    long = vmod.horizon_sensitivity(cell, frozen, l_cap=330)
    assert set(days_seen) == {110, 330}
    assert short["min_simulated_days"] >= 110 and long["min_simulated_days"] >= 330
    assert long["worst_binding_row_rate"] > short["worst_binding_row_rate"] + 0.02
    assert long["certified_ticks_at_cap"] > short["certified_ticks_at_cap"]
    assert long["L_cap"] == 330 and set(long["false_stop_rate_by_row"]) == {
        "H0",
        "S4",
        "S5-bind",
        "S8-persist3",
    }


def test_horizon_sensitivity_cell_is_report_only_and_pinned() -> None:
    cell = _real_cell()
    frozen = {"c": 1.2, "t_min": cell["t_min"], "alpha_star": cell["alpha_star"]}
    out = vmod.horizon_sensitivity(
        cell, frozen, l_cap=150, holdout_start="2026-11-23", cap_date="2027-04-21"
    )
    assert out["report_only"] is True and out["freeze"] == "2026-10-08"
    assert out["seed"] == cell["seed"] == maker.SEED and out["frozen_c"] == 1.2
    assert out["note"] == (
        "capital-conservative; costs power; a tail STOP is terminal STOP, not FAIL, not refutation"
    )
    assert (out["holdout_start_date"], out["calendar_cap_date"]) == ("2026-11-23", "2027-04-21")
    assert out["worst_binding_row_rate"] == max(out["false_stop_rate_by_row"].values())
    # deterministic, same seeds
    assert (
        vmod.horizon_sensitivity(cell, frozen, l_cap=150)["false_stop_rate_by_row"]
        == out["false_stop_rate_by_row"]
    )
    evaluation = _evaluate(_grid_cells(0.3, C_BY), _grid_cells(0.22, C_BY), lambda c, f: _ok())
    a = maker.assemble_artifact(evaluation, horizon=out)
    b = maker.assemble_artifact(evaluation, horizon={**out, "worst_binding_row_rate": 0.99})
    assert a["verdict"] == b["verdict"] and a["horizon_sensitivity"]["report_only"] is True


def test_artifact_records_window_label_and_certified_horizon() -> None:
    evaluation = _evaluate(
        _grid_cells(0.30, C_BY), _grid_cells(0.22, C_BY), lambda c, f: _ok(), b_median=0.75, k=2
    )
    art = maker.assemble_artifact(evaluation)
    frozen = evaluation["frozen_cell"]
    ticks = next(
        c["certified_ticks"]
        for c in evaluation["cells"]
        if (c["k"], c["b"], c["f"]) == (2, 0.75, 0.30)
    )
    expected = (
        "window = FQ v2 window 2026-10-08..2027-01-25 used as a 110-climate-date label; "
        "certified_horizon_climate_days = 110; "
        f"certified_ticks = {ticks}; "
        f"frozen cell = {frozen['k']}, {frozen['b']}, {frozen['f_kill']}; "
        f"frozen_c_deff = {evaluation['frozen_c_deff']}; "
        "see RULING_MAKER-S3_loss_stop_window_2026-10-13"
    )
    assert art["window_label"] == expected
    assert (
        art["certified_horizon_climate_days"]
        == inclusive_days(maker.DEFAULT_FREEZE, HORIZON)
        == 110
    )
    assert art["frozen_c_deff"] == evaluation["frozen_c_deff"] and art["certified_ticks"] == ticks
    assert all(c["certified_ticks"] > 0 for c in art["cells"])
    assert art["frozen_cell"] == frozen
    # real run: certified_ticks is T_low at epoch 0
    cell = _real_cell()
    assert cell["certified_ticks"] == t_low_count(
        110, cell["lambda_sd"], cell["p_keep_gate"], tick_share=cell["tick_share"]
    )
    early = maker.assemble_artifact(
        evaluation, early_stop={"early_stop": "sweep_all_veto", "early_stop_basis": {"f_max": 0.5}}
    )
    assert early["early_stop"] == "sweep_all_veto" and early["verdict"] == "UNREACHABLE"
