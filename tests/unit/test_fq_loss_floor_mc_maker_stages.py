"""MAKER S3 WP3 review fixes: the CLI stage runners end to end, with the cell runners stubbed."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from scripts.analysis import fq_loss_floor_mc_maker as maker
from scripts.analysis import fq_loss_floor_mc_maker_bench as bench
from tests.unit.test_fq_loss_floor_mc_maker_verdict import (
    C_BY,
    CAP_PIN,
    S2_DOC,
    _cell,
    _ok,
    _s1_rows,
    _write,
)

SE = math.sqrt(0.25 * 0.75 / 10_000)
BLOCKED = {"reason": "s6_failed", "detail": "builder"}


class Harness:
    """Records every stubbed call; the stubs are installed on the CLI module's patch points."""

    def __init__(
        self, *, veto: bool = False, borderline: bool = False, blocked: Any = None
    ) -> None:
        self.veto, self.borderline, self.blocked = veto, borderline, blocked
        self.runs: list[dict[str, Any]] = []
        self.rechecks: list[tuple[Any, ...]] = []
        self.horizons: list[dict[str, Any]] = []
        self.caps: list[float] = []

    def run_cell(
        self,
        mix: Any,
        *,
        replicates: int,
        outer_resamples: int,
        outer_replicates: int,
        seed: int,
        n_dates: int = 1000,
    ) -> dict[str, Any]:
        self.runs.append(
            {
                "k": mix.rungs,
                "b": mix.bid,
                "f": mix.fill_rate,
                "theta": mix.theta,
                "replicates": replicates,
                "outer": (outer_resamples, outer_replicates),
                "seed": seed,
            }
        )
        block = self.blocked is not None and self.blocked(mix)
        c = None if self.veto or block else C_BY[(mix.rungs, mix.bid)]
        g3 = 0.25 + 0.5 * SE if self.borderline and replicates == 10_000 else 0.9
        extra: dict[str, Any] = {"floor_mode": None, "freeze_blocked": BLOCKED} if block else {}
        return _cell(
            mix.rungs,
            mix.bid,
            mix.fill_rate,
            c,
            theta=mix.theta,
            replicates=replicates,
            seed=seed,
            g3_by_delta={"-0.16": g3, "-0.08": 0.3, "-0.04": 0.1},
            **extra,
        )

    def recheck(self, cell: Any, frozen: Any) -> dict[str, Any]:
        self.rechecks.append((cell["k"], cell["b"], cell["f"], cell["theta"], frozen["c"]))
        return _ok()

    def horizon(self, cell: Any, frozen: Any, **kwargs: Any) -> dict[str, Any]:
        self.horizons.append({"cell": cell, "frozen": frozen, **kwargs})
        return {"report_only": True, "marker": "HORIZON"}

    def install(self, monkeypatch: pytest.MonkeyPatch) -> Harness:
        monkeypatch.setattr(maker, "run_cell", self.run_cell)
        monkeypatch.setattr(maker, "recheck_cell", self.recheck)
        monkeypatch.setattr(maker, "horizon_sensitivity", self.horizon)
        monkeypatch.setattr(maker, "apply_address_space_cap", self.caps.append)
        return self


def _files(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


def _binding_argv(tmp: Path) -> tuple[list[str], Path]:
    inp = tmp / "in"
    inp.mkdir()
    s1 = inp / "s1.jsonl"
    s1.write_text("\n".join(json.dumps(r) for r in _s1_rows(30, 1, 0)) + "\n", encoding="utf-8")
    out = tmp / "out" / "binding.json"
    argv = [
        "--binding",
        "--s2-artifact",
        str(_write(inp, "s2.json", S2_DOC)),
        "--s1-artifact",
        str(s1),
        "--s5-cap-pin",
        str(_write(inp, "pin.json", CAP_PIN)),
        "--out",
        str(out),
    ]
    return argv, out


# ------------------------------------------------------------------------------------ sweep


def test_sweep_runs_without_outer_se_and_confirm_with_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    h = Harness(veto=True).install(monkeypatch)
    out = tmp_path / "out" / "sweep.json"
    assert maker.main(["--sweep", "--out", str(out)]) == 0
    sweep, confirm = h.runs[:30], h.runs[30:]
    assert len(sweep) == 30 and len(confirm) == 6
    assert all(r["replicates"] == maker.SWEEP_REPLICATES == 2000 for r in sweep)
    assert all(r["outer"] == (0, 0) and r["theta"] == 0.0695 for r in sweep)
    assert all(r["replicates"] == 10_000 and r["outer"] == (20, 2000) for r in confirm)
    assert {r["f"] for r in confirm} == {0.5} and {r["seed"] for r in h.runs} == {maker.SEED}
    assert h.caps == [8.0]
    assert _files(tmp_path) == ["out/sweep.json"]  # tmp + rename leaves only --out


def test_sweep_early_stop_writes_a_full_unreachable_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    Harness(veto=True).install(monkeypatch)
    out = tmp_path / "sweep.json"
    assert maker.main(["--sweep", "--out", str(out)]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["verdict"] == "UNREACHABLE" and doc["early_stop"] == "sweep_all_veto"
    assert doc["early_stop_basis"]["replicates"] == 10_000 and doc["mode"] == "sweep"
    assert len(doc["sweep_cells"]) == 30 and len(doc["cells"]) == 6 == len(doc["confirm_cells"])
    assert all(c["f"] == 0.5 for c in doc["cells"])
    prov = doc["provenance"]
    assert len(prov["git_head"]) == 40 and len(prov["script_git_sha"]) == 40
    assert isinstance(prov["git_tree_clean"], bool)
    assert doc["frozen_cell"] is None and doc["freeze_blocked_cells"] == []


def test_sweep_without_early_stop_has_no_verdict_and_no_confirm(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    h = Harness(veto=False).install(monkeypatch)
    out = tmp_path / "sweep.json"
    assert maker.main(["--sweep", "--out", str(out)]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert len(h.runs) == 30 and doc["verdict"] is None and "early_stop" not in doc
    assert doc["confirm_cells"] == [] and len(doc["sweep_cells"]) == 30


def test_freeze_blocked_cell_is_surfaced_and_blocks_early_stop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    blocked = lambda mix: (mix.rungs, mix.bid, mix.fill_rate) == (1, 0.70, 0.1)
    h = Harness(veto=True, blocked=blocked).install(monkeypatch)
    out = tmp_path / "sweep.json"
    assert maker.main(["--sweep", "--out", str(out)]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert len(h.runs) == 30  # the blocked cell never counts as a veto: no confirm, no stop
    assert doc["verdict"] is None and "early_stop" not in doc
    assert doc["freeze_blocked_cells"] == [
        {
            "group": "sweep_cells",
            "k": 1,
            "b": 0.70,
            "f": 0.1,
            "theta": 0.0695,
            "freeze_blocked": BLOCKED,
        }
    ]
    assert "BUILDER-DEFECT" in capsys.readouterr().out


# ---------------------------------------------------------------------------------- binding


def test_binding_runs_pinned_cells_report_cells_and_the_frozen_horizon(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    h = Harness().install(monkeypatch)
    argv, out = _binding_argv(tmp_path)
    assert maker.main(argv) == 0
    pinned = [r for r in h.runs if r["theta"] == 0.0695]
    report = [r for r in h.runs if r["theta"] == 0.08]
    assert len(pinned) == 12 and len(report) == 6 and len(h.runs) == 18
    for r in h.runs:  # binding, report and horizon-feeding cells all carry the outer 20 x 2000
        assert r["replicates"] == 10_000 and r["outer"] == (20, 2000) and r["seed"] == maker.SEED
    assert {(r["k"], r["f"]) for r in pinned} == {(2, 0.30), (2, 0.22), (1, 0.20), (1, 0.14)}
    assert {(r["k"], r["f"]) for r in report} == {(2, 0.22), (1, 0.14)}  # f_pass, never f_kill
    assert h.caps == [8.0]
    art = json.loads(out.read_text(encoding="utf-8"))
    assert art["verdict"] == "REACHABLE" and len(art["cells"]) == 12
    assert len(art["report_cells"]) == 6 and all(c["theta"] == 0.08 for c in art["report_cells"])
    assert all(c["theta"] == 0.0695 for c in art["cells"])
    # every one of the 12 binding cells is re-checked at the same frozen c; report cells never
    assert len(h.rechecks) == 12 and {r[4] for r in h.rechecks} == {C_BY[(2, 0.75)]}
    assert all(r[3] == 0.0695 for r in h.rechecks)
    # the horizon cell is fed the FROZEN cell (k=2, b=0.75, f_kill) with the S5 cap pin
    (call,) = h.horizons
    assert (call["cell"]["k"], call["cell"]["b"], call["cell"]["f"]) == (2, 0.75, 0.30)
    assert call["frozen"]["c"] == C_BY[(2, 0.75)] and call["l_cap"] == 220
    assert call["holdout_start"] == "2026-11-23" and call["cap_date"] == "2027-06-30"
    assert art["horizon_sensitivity"]["marker"] == "HORIZON"
    assert art["frozen_cell"] == {"k": 2, "b": 0.75, "f_kill": 0.30}


def test_binding_writes_only_the_out_file_with_full_provenance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    Harness().install(monkeypatch)
    argv, out = _binding_argv(tmp_path)
    before = _files(tmp_path)
    assert maker.main(argv) == 0
    assert sorted(set(_files(tmp_path)) - set(before)) == ["out/binding.json"]
    prov = json.loads(out.read_text(encoding="utf-8"))["provenance"]
    s2_lines = prov["s2_lines"]
    assert s2_lines["fill_rate_2x.point"] != s2_lines["fill_rate_base.point"]
    assert len(set(s2_lines.values())) == len(s2_lines) and min(s2_lines.values()) >= 1
    assert prov["s1_rows"] == 31 * 5 and len(prov["s1_sha256"]) == 64
    assert len(prov["s2_sha256"]) == 64 and len(prov["git_head"]) == 40
    assert isinstance(prov["git_tree_clean"], bool) and prov["L_cap"] == 220
    assert prov["fill_icc_s2_raw"] == 0.12
    assert prov["fill_icc_rung_trial"] == 0.12
    assert prov["fill_icc_station_day"] == pytest.approx(0.12 * 7 / 3)
    assert prov["design_effect_pinned"] == pytest.approx(1.84)
    assert prov["design_effect_realised"] == pytest.approx(prov["design_effect_pinned"])
    assert "four_station" in prov["unknown_share_basis"]
    assert prov["unknown_share_all_rows"] == 0.0


def test_borderline_rerun_applies_to_binding_cells_not_report_cells(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    h = Harness(borderline=True).install(monkeypatch)
    argv, out = _binding_argv(tmp_path)
    assert maker.main(argv) == 0
    reruns = [r for r in h.runs if r["replicates"] == 50_000]
    assert len(reruns) == 12 and all(r["theta"] == 0.0695 for r in reruns)
    assert all(r["seed"] == 20261013 for r in reruns)
    assert [r for r in h.runs if r["theta"] == 0.08 and r["replicates"] != 10_000] == []
    art = json.loads(out.read_text(encoding="utf-8"))
    assert all(c["borderline_rerun"] for c in art["cells"])
    assert not any("borderline_rerun" in c for c in art["report_cells"])


def test_binding_surfaces_a_freeze_blocked_cell(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    blocked = lambda mix: (mix.rungs, mix.bid, mix.theta) == (1, 0.80, 0.08)
    Harness(blocked=blocked).install(monkeypatch)
    argv, out = _binding_argv(tmp_path)
    assert maker.main(argv) == 0
    art = json.loads(out.read_text(encoding="utf-8"))
    (entry,) = art["freeze_blocked_cells"]
    assert (entry["group"], entry["k"], entry["b"], entry["theta"]) == (
        "report_cells",
        1,
        0.8,
        0.08,
    )
    assert art["verdict"] == "REACHABLE"  # report cells never enter the verdict


# ------------------------------------------------------------------------------- benchmark


def test_subset_benchmark_times_one_recheck_cell(capsys: pytest.CaptureFixture[str]) -> None:
    runs: list[tuple[int, int]] = []
    rechecked: list[tuple[Any, Any]] = []

    def run(mix: Any, *, replicates: int, outer_resamples: int, **_: Any) -> dict[str, Any]:
        runs.append((replicates, outer_resamples))
        return _cell(2, 0.80, 0.5, None, replicates=replicates)

    def recheck(cell: Any, frozen: Any) -> dict[str, Any]:
        rechecked.append((cell, frozen))
        return {}

    assert bench.benchmark(run, recheck=recheck) == 0
    out = capsys.readouterr().out
    assert runs == [(100, 0), (200, 0), (100, 2)]
    assert len(rechecked) == 1 and rechecked[0][0]["replicates"] == 100
    assert rechecked[0][1]["c"] > 0  # a veto cell gets a timing-only fallback stop
    for needle in (
        "benchmark_point recheck replicates=100",
        "projected_recheck_seconds_per_cell_binding=",
        "projected_recheck_seconds_12_cells=",
        "projected_recheck_sims=84",
        "official_evidence_written=0",
    ):
        assert needle in out
