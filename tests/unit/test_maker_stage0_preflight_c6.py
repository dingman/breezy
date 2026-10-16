"""MAKER-S2 second look (C6): v2 truth agreement before the claim; NB1 disclosed list on ``Pre``.

Fixture worlds only: no real catalog, truth, node log or network.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scripts.analysis import maker_stage0_driver as drv
from scripts.analysis import maker_stage0_modes as modes
from scripts.analysis import maker_stage0_preflight as pf
from scripts.analysis import maker_stage0_preflight_v2 as pf2
from scripts.analysis import maker_stage0_report as rep
from scripts.analysis.maker_stage0_frozen import load_amendment, truth_keys
from scripts.analysis.maker_stage0_inputs import InputRefused, TruthConflict
from scripts.analysis.maker_stage0_run_types import Pre, RunConfig, RunSummary
from tests.fixtures.maker_stage0 import replay_world as rw
from tests.fixtures.maker_stage0 import replay_world_v2 as rw2
from tests.fixtures.maker_stage0.frozen_v2 import BLOCK_FIRST
from tests.unit import test_maker_stage0_pins as pins_fx


def _cfg(repo: Path, base: Path, world: Any) -> RunConfig:
    return RunConfig(
        census_days=world.census,
        trade_unit=world.unit,
        catalog_root=base / "capture",
        nbp_root=world.nbp_root,
        truth=world.truth,
        truth_cross_check=world.cross_check,
        node_log_dir=world.node_log_dir,
        out_dir=base / "runs" / "run1",
        repo_root=repo,
        amendment=world.amendment,
        amendment_sha=world.amendment_sha,
        spec=repo / "docs/strategies/SPEC.md",
        ledger=base / "derived" / "verdict_ledger.jsonl",
        work_root=base / "work" / "run1",
    )


def _v2(tmp_path: Path, **kw: Any) -> tuple[RunConfig, rw2.WorldV2]:
    repo = pins_fx._repo(tmp_path)
    world = rw2.build_world_v2(tmp_path / "w", repo, **kw)
    pins_fx._git(repo, "add", "--", rw2.TRIGGER_REL)
    pins_fx._git(repo, "commit", "-q", "-m", "trigger rows")
    return _cfg(repo, tmp_path, world), world


def _assert_no_claim(cfg: RunConfig) -> None:
    assert not cfg.ledger.exists()
    assert not cfg.out_dir.exists()


def test_v2_cross_check_without_overlap_refused_before_claim(tmp_path: Path) -> None:
    cfg, _ = _v2(tmp_path, overlap=False)
    with pytest.raises(InputRefused, match="vacuous"):
        pf.preflight(cfg, "verdict")
    _assert_no_claim(cfg)


def test_v2_truth_conflict_refused_before_claim(tmp_path: Path) -> None:
    cfg, _ = _v2(tmp_path, cross_tmax_f=rw2.TRUTH_TMAX_F + 1)
    with pytest.raises(TruthConflict):
        pf.preflight(cfg, "verdict")
    _assert_no_claim(cfg)


def test_preflight_and_score_truth_keys_are_equal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deliberate reading: v2 score keys are the ``truth_keys`` grid, not the replayed rows.

    Per-row truth is unchanged; the grid is what preflight already proved, which removes the
    post-claim FrozenSetRefused/TruthConflict risk. Hence a sparse ``sd_rows`` still loads the grid.
    """
    cfg, world = _v2(tmp_path)
    fs = load_amendment(world.amendment, world.amendment_sha)
    seen: dict[str, set[tuple[str, dt.date]]] = {}

    def spy(name: str) -> Any:
        def record(*_a: Any, keys: Any, **_k: Any) -> None:
            seen[name] = set(keys)
            raise RuntimeError(name)

        return record

    monkeypatch.setattr(pf2, "load_truth", spy("preflight"))
    with pytest.raises(RuntimeError, match="preflight"):
        pf.preflight(cfg, "verdict")
    monkeypatch.setattr(rep, "load_truth", spy("score"))
    sparse = [SimpleNamespace(station="SFO", climate_day=BLOCK_FIRST.isoformat())]
    with pytest.raises(RuntimeError, match="score"):
        rep.score(
            sd_rows=sparse,  # type: ignore[arg-type]
            seeds=[],
            census=world.census_rows,
            frozen=fs,
            truth_csv=world.truth,
            cross_check=world.cross_check,
            run_dir=tmp_path / "scratch",
        )
    assert seen["preflight"] == seen["score"] == truth_keys(fs.stations, fs.dates)


def test_v1_preflight_unchanged_by_c6(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = pins_fx._repo(tmp_path)
    world = rw.build_world(tmp_path / "w")
    calls: list[str] = []
    monkeypatch.setattr(pf2, "load_truth", lambda *a, **k: calls.append("truth"))
    monkeypatch.setattr(pf, "check_v2_before_claim", lambda *a, **k: calls.append("v2"))
    pre = pf.preflight(_cfg(repo, tmp_path, world), "verdict")
    assert calls == []
    assert pre.v2_disclosed == ()


def test_pre_carries_v2_disclosed_list(tmp_path: Path) -> None:
    cfg, _ = _v2(tmp_path, late=frozenset({("SFO", BLOCK_FIRST)}))
    pre = pf.preflight(cfg, "verdict")
    assert isinstance(pre, Pre)
    assert pre.v2_disclosed == (f"SFO:{BLOCK_FIRST.isoformat()}",)


def test_v2_world_preflight_smoke(tmp_path: Path) -> None:
    cfg, world = _v2(tmp_path)
    pre = pf.preflight(cfg, "verdict")
    assert pre.frozen.block == 2
    assert pre.v2_disclosed == ()
    assert min(pre.frozen.dates) >= BLOCK_FIRST
    assert set(pre.frozen.stations) == {"LAX", "MDW", "MIA", "SFO"}
    _assert_no_claim(cfg)
    assert world.trigger_rows.is_file()


def _ledger_lines(cfg: RunConfig) -> list[str]:
    return cfg.ledger.read_text().splitlines() if cfg.ledger.exists() else []


def test_v2_preflight_refusal_precedes_claim_at_driver_level(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reached: list[str] = []
    monkeypatch.setattr(drv, "_execute", lambda cfg, pre: reached.append("execute"))
    bad, _ = _v2(tmp_path / "bad", overlap=False)
    with pytest.raises(InputRefused, match="vacuous"):
        drv.run(bad)
    assert _ledger_lines(bad) == []
    assert not bad.out_dir.exists()
    assert reached == []
    good, _ = _v2(tmp_path / "good")
    drv.run(good)
    assert reached == ["execute"]
    assert len(_ledger_lines(good)) == 1


def test_run_summary_carries_v2_disclosed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg, _ = _v2(tmp_path, late=frozenset({("SFO", BLOCK_FIRST)}))
    pre = pf.preflight(cfg, "verdict")

    class _Session:
        def __init__(self, *_a: Any) -> None: ...

        def close(self) -> None: ...

    monkeypatch.setattr(drv, "CatalogSession", _Session)
    monkeypatch.setattr(drv, "_wp0", lambda c, p: drv.Wp0({}, frozenset(), 0))
    monkeypatch.setattr(drv, "_simulate_all", lambda *a: None)
    monkeypatch.setattr(
        drv, "finish", lambda c, p, *a: RunSummary(c.out_dir, None, p.code_sha, "verdict")
    )
    summary = drv._execute(cfg, pre)
    assert summary.v2_disclosed == (f"SFO:{BLOCK_FIRST.isoformat()}",)
    cfg.out_dir.mkdir(parents=True)
    modes.write_manifest(cfg, pre, "verdict", ["preflight"], {})
    written = json.loads((cfg.out_dir / "run_manifest.json").read_text())
    assert written["v2_disclosed"] == [f"SFO:{BLOCK_FIRST.isoformat()}"]
    clean = dataclasses.replace(pre, v2_disclosed=())
    modes.write_manifest(cfg, clean, "verdict", ["preflight"], {})
    assert "v2_disclosed" not in json.loads((cfg.out_dir / "run_manifest.json").read_text())
