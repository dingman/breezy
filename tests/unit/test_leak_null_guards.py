"""Outcome-blind LEAK-NULL guards; all filesystem fixtures live under tmp_path."""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from scripts.analysis import leak_null_guards as g
from scripts.analysis import multisource_blend_skill as skill
from tests.unit.test_multisource_blend_skill import _freeze, _git

THRESHOLDS = {
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
PINNED = (
    "src/breezy/analysis/leak_null.py",
    "src/breezy/analysis/leak_null_decide.py",
    "src/breezy/analysis/multisource_blend_fit.py",
    "src/breezy/analysis/multisource_blend_folds.py",
    "src/breezy/analysis/multisource_blend_stats.py",
    "src/breezy/analysis/multisource_blend_features.py",
    "src/breezy/analysis/multisource_blend.py",
    "scripts/analysis/leak_null_guards.py",
    "scripts/analysis/leak_null_study.py",
    "scripts/analysis/multisource_blend_skill.py",
)


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _draft(tmp_path: Path) -> dict[str, Any]:
    inputs = {}
    for role, name in (
        ("f13_prereg", "f13.json"),
        ("features", "f.jsonl"),
        ("lag_features", "fl.jsonl"),
        ("c1_evidence", "c1.json"),
    ):
        path = tmp_path / name
        path.write_text("{}", encoding="utf-8")
        inputs[role] = {"path": str(path), "sha256": _sha(path)}
    return {
        "frozen_sha": skill.UNFROZEN,
        "code_sha": "a" * 40,
        "pinned_blobs": list(PINNED),
        "inputs": inputs,
        "seeds": list(range(100, 120)),
        "probe_seed": 999,
        "thresholds": {**THRESHOLDS, "source": "multisource_blend_stats.py:230"},
        "f13_record": {
            "m0p_vs_m3_mean": 0.165,
            "m0p_vs_m3_lb": 0.150,
            "floor": 0.01,
            "source": "synthetic/result.json:acceptance.floor; sha256=" + "b" * 64,
        },
        "out_root": str(tmp_path / "derived"),
    }


def _load(tmp_path: Path, draft: dict[str, Any]) -> g.LeakNullDesign:
    path = tmp_path / "leak_prereg.json"
    path.write_text(json.dumps(draft), encoding="utf-8")
    return g.load_leak_prereg(path, allow_unfrozen=True)


def _repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    for name in PINNED:
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# pinned fixture\n", encoding="utf-8")
        _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", "synthetic code")
    return repo, _git(repo, "rev-parse", "HEAD")


def _frozen(tmp_path: Path, *, floor: float | None = 0.01) -> tuple[Path, Path, g.LeakNullDesign]:
    repo, sha = _repo(tmp_path)
    draft = _draft(tmp_path)
    draft["code_sha"] = sha
    draft["f13_record"]["floor"] = floor
    path = _freeze(repo, draft)
    return repo, path, g.load_leak_prereg(path, allow_unfrozen=False)


def _loaded_origins(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for path in PINNED:
        name = path.removeprefix("src/").removesuffix(".py").replace("/", ".")
        module = ModuleType(name)
        module.__file__ = str(repo / path)
        monkeypatch.setitem(sys.modules, name, module)


@pytest.mark.parametrize("kind", ["direct", "symlink", "dotdot"])
def test_refuses_out_dir_inside_gap1_j3_dir(tmp_path: Path, kind: str) -> None:
    root = tmp_path / "derived"
    sealed = root / "gap1_j3_2026-11-02"
    sealed.mkdir(parents=True)
    if kind == "symlink":
        (root / "alias").symlink_to(sealed, target_is_directory=True)
        path = root / "alias/leak_null_2026-11-03"
    elif kind == "dotdot":
        path = sealed / "../leak_null_2026-11-03"
    else:
        path = sealed / "leak_null_2026-11-03"
    with pytest.raises(g.Refusal, match="gap1_j3"):
        g.guard_out_dir(path, root)


@pytest.mark.parametrize("kind", ["raw", "resolved", "raw_dotdot"])
def test_refuses_live_data_root_raw_and_resolved(tmp_path: Path, kind: str) -> None:
    live = tmp_path / ".local/share/breezy"
    live.mkdir(parents=True)
    (tmp_path / "alias").symlink_to(live, target_is_directory=True)
    path = {
        "raw": live / "leak_null_2026-11-03",
        "resolved": tmp_path / "alias/leak_null_2026-11-03",
        "raw_dotdot": live / "../../../leak_null_2026-11-03",
    }[kind]
    with pytest.raises(g.Refusal, match="live"):
        g.guard_out_dir(path, tmp_path)


@pytest.mark.parametrize("basename", ["result", "leak_null_2026-1-03", "leak_null_2026-11-03x"])
def test_refuses_bad_basename(tmp_path: Path, basename: str) -> None:
    with pytest.raises(g.Refusal, match="basename"):
        g.guard_out_dir(tmp_path / basename, tmp_path)


def test_guard_out_dir_accepts_inside_root_only(tmp_path: Path) -> None:
    root = tmp_path / "derived"
    path = root / "leak_null_2026-11-03"
    assert g.guard_out_dir(path, root) == path.resolve()
    assert not root.exists()
    with pytest.raises(g.Refusal, match="out_root"):
        g.guard_out_dir(tmp_path / "leak_null_2026-11-03", root)


@pytest.mark.parametrize("k", [0, 19, 21])
def test_k_not_20_refused(tmp_path: Path, k: int) -> None:
    draft = _draft(tmp_path)
    draft["seeds"] = list(range(k))
    with pytest.raises(g.Refusal, match="K must equal 20"):
        _load(tmp_path, draft)


@pytest.mark.parametrize("bad", [101, 20261006, 999, True, 100.0, "100"])
def test_duplicate_or_f13_or_probe_seed_refused(tmp_path: Path, bad: Any) -> None:
    draft = _draft(tmp_path)
    draft["seeds"][0] = bad
    with pytest.raises(g.Refusal, match="seed"):
        _load(tmp_path, draft)


@pytest.mark.parametrize("key", list(THRESHOLDS))
def test_thresholds_other_than_frozen_refused(tmp_path: Path, key: str) -> None:
    draft = _draft(tmp_path)
    draft["thresholds"][key] += 0.001
    with pytest.raises(g.Refusal, match="threshold"):
        _load(tmp_path, draft)


def test_null_f13_floor_allowed_marks_unavailable(tmp_path: Path) -> None:
    draft = _draft(tmp_path)
    draft["f13_record"]["floor"] = None
    design = _load(tmp_path, draft)
    assert design.f13_record["floor"] is None
    assert design.f13_record["floor_check"] == "unavailable"
    assert design.pc_seeds == tuple(draft["seeds"][:5])
    assert g.Refusal is skill.Refusal
    with pytest.raises(FrozenInstanceError):
        design.probe_seed = 1  # type: ignore[misc]


def test_null_f13_floor_can_freeze(tmp_path: Path) -> None:
    _, _, design = _frozen(tmp_path, floor=None)
    assert design.f13_record["floor_check"] == "unavailable"


@pytest.mark.parametrize(
    "field,bad",
    [
        ("floor", -1),
        ("floor", float("nan")),
        ("m0p_vs_m3_mean", None),
        ("m0p_vs_m3_lb", True),
        ("source", ""),
    ],
)
def test_invalid_f13_record_refused(tmp_path: Path, field: str, bad: Any) -> None:
    draft = _draft(tmp_path)
    draft["f13_record"][field] = bad
    with pytest.raises(g.Refusal, match="f13_record"):
        _load(tmp_path, draft)


def test_t_pin_drift_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("scipy.special.stdtrit", lambda *_: 3.0)
    with pytest.raises(g.Refusal, match="t.pin"):
        _load(tmp_path, _draft(tmp_path))


def test_input_sha_mismatch_refuses(tmp_path: Path) -> None:
    design = _load(tmp_path, _draft(tmp_path))
    Path(design.inputs["features"]["path"]).write_text("changed", encoding="utf-8")
    with pytest.raises(g.Refusal, match="sha256"):
        g.verify_inputs(design)


def test_verify_inputs_exact_pins_and_f13_content_digest(tmp_path: Path) -> None:
    draft = _draft(tmp_path)
    spec = draft["inputs"]["f13_prereg"]
    spec["content_sha256"] = skill.content_digest({})
    design = _load(tmp_path, draft)
    assert g.verify_inputs(design) == {
        role: spec["sha256"] for role, spec in draft["inputs"].items()
    }
    spec["content_sha256"] = "0" * 64
    with pytest.raises(g.Refusal, match="content_sha256"):
        g.verify_inputs(_load(tmp_path, draft))


def test_f13_content_digest_only_pin_accepted(tmp_path: Path) -> None:
    draft = _draft(tmp_path)
    spec = draft["inputs"]["f13_prereg"]
    expected = spec.pop("sha256")
    spec["content_sha256"] = skill.content_digest({})
    assert g.verify_inputs(_load(tmp_path, draft))["f13_prereg"] == expected


@pytest.mark.parametrize("change", ["missing", "extra", "no_digest", "bad_digest"])
def test_invalid_input_pins_refused(tmp_path: Path, change: str) -> None:
    draft = _draft(tmp_path)
    if change == "missing":
        draft["inputs"].pop("features")
    elif change == "extra":
        draft["inputs"]["extra"] = dict(draft["inputs"]["features"])
    elif change == "no_digest":
        draft["inputs"]["features"].pop("sha256")
    else:
        draft["inputs"]["features"]["sha256"] = "not-a-sha"
    with pytest.raises(g.Refusal, match="inputs"):
        _load(tmp_path, draft)


@pytest.mark.parametrize("change", ["missing", "duplicate", "absolute"])
def test_incomplete_or_non_relative_pinned_blobs_refused(tmp_path: Path, change: str) -> None:
    draft = _draft(tmp_path)
    if change == "missing":
        draft["pinned_blobs"].pop()
    elif change == "duplicate":
        draft["pinned_blobs"][0] = draft["pinned_blobs"][1]
    else:
        draft["pinned_blobs"][0] = str(tmp_path / "module.py")
    with pytest.raises(g.Refusal, match="pinned_blobs"):
        _load(tmp_path, draft)


@pytest.mark.parametrize("name", ["result.json", "murphy.json", "stage_a.json", "oof_rows.jsonl"])
@pytest.mark.parametrize("symlink", [False, True])
def test_forbidden_basenames_refused(tmp_path: Path, name: str, symlink: bool) -> None:
    draft = _draft(tmp_path)
    forbidden = tmp_path / name
    forbidden.write_text("{}", encoding="utf-8")
    path = forbidden
    if symlink:
        path = tmp_path / "innocent.json"
        path.symlink_to(forbidden)
    draft["inputs"]["features"]["path"] = str(path)
    with pytest.raises(g.Refusal, match="forbidden"):
        g.verify_inputs(_load(tmp_path, draft))


def test_real_freeze_path_accepts_and_refreeze_refused(tmp_path: Path) -> None:
    repo, path, design = _frozen(tmp_path)
    assert design.seeds == tuple(range(100, 120))
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["probe_seed"] += 1
    _freeze(repo, raw)
    with pytest.raises(g.Refusal, match="re-frozen"):
        g.load_leak_prereg(path, allow_unfrozen=False)


def test_prereg_digest_mismatch_refuses(tmp_path: Path) -> None:
    _, path, _ = _frozen(tmp_path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["probe_seed"] += 1
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(g.Refusal, match="FROZEN_BLOB_DIFFERS"):
        g.load_leak_prereg(path, allow_unfrozen=False)


def test_unfrozen_refused_outside_probe(tmp_path: Path) -> None:
    design = _load(tmp_path, _draft(tmp_path))
    with pytest.raises(g.Refusal, match="UNFROZEN"):
        g.load_leak_prereg(design.prereg_path, allow_unfrozen=False)


def test_code_pin_refuses_non_ancestor(tmp_path: Path) -> None:
    repo, sha = _repo(tmp_path)
    tree = _git(repo, "rev-parse", "HEAD^{tree}")
    orphan = _git(repo, "commit-tree", tree, "-m", "unrelated history")
    assert g.code_ok(repo, sha, sha)
    assert not g.code_ok(repo, orphan, sha)
    assert not g.code_ok(repo, sha.upper(), sha)
    with pytest.raises(g.Refusal, match="ancestor"):
        g.check_code_pin(repo, orphan, PINNED)


@pytest.mark.parametrize("committed", [False, True])
def test_code_pin_refuses_head_blob_drift(tmp_path: Path, committed: bool) -> None:
    repo, sha = _repo(tmp_path)
    path = PINNED[0]
    (repo / path).write_text("# drift\n", encoding="utf-8")
    if committed:
        _git(repo, "add", path)
        _git(repo, "commit", "-q", "-m", "drift")
    with pytest.raises(g.Refusal, match="blob"):
        g.check_code_pin(repo, sha, (path,))


def test_code_pin_refuses_head_drift_even_if_worktree_restored(tmp_path: Path) -> None:
    repo, sha = _repo(tmp_path)
    name = PINNED[0]
    (repo / name).write_text("# drift\n", encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", "drift")
    (repo / name).write_text("# pinned fixture\n", encoding="utf-8")
    with pytest.raises(g.Refusal, match="blob"):
        g.check_code_pin(repo, sha, (name,))


@pytest.mark.parametrize("name", PINNED)
def test_code_pin_checks_every_loaded_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    repo, sha = _repo(tmp_path)
    _loaded_origins(repo, monkeypatch)
    g.check_code_pin(repo, sha, PINNED)
    module_name = name.removeprefix("src/").removesuffix(".py").replace("/", ".")
    monkeypatch.setattr(sys.modules[module_name], "__file__", str(tmp_path / "other.py"))
    with pytest.raises(g.Refusal, match="loaded.*outside"):
        g.check_code_pin(repo, sha, PINNED)


def test_code_pin_refuses_module_loaded_outside_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, sha = _repo(tmp_path)
    module = ModuleType("breezy.analysis.leak_null")
    module.__file__ = str(tmp_path / "other/leak_null.py")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    with pytest.raises(g.Refusal, match="loaded.*outside"):
        g.check_code_pin(repo, sha, (PINNED[0],))
    module.__file__ = str(repo / PINNED[0])
    g.check_code_pin(repo, sha, (PINNED[0],))
    del module.__file__
    with pytest.raises(g.Refusal, match="loaded"):
        g.check_code_pin(repo, sha, (PINNED[0],))


def test_code_pin_notes_pinned_modules_that_are_not_loaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, sha = _repo(tmp_path)
    monkeypatch.delitem(sys.modules, "breezy.analysis.leak_null", raising=False)
    notes = g.check_code_pin(repo, sha, (PINNED[0],))
    assert len(notes) == 1
    assert "breezy.analysis.leak_null not loaded" in notes[0]


@pytest.mark.parametrize("path", ["../outside.py", "/absolute.py", "src/../escape.py"])
def test_code_pin_refuses_non_repo_relative_paths(tmp_path: Path, path: str) -> None:
    repo, sha = _repo(tmp_path)
    with pytest.raises(g.Refusal, match="repo.relative"):
        g.check_code_pin(repo, sha, (path,))


@pytest.mark.parametrize("kind", ["same", "child", "symlink"])
def test_probe_parent_inside_out_root_refused(tmp_path: Path, kind: str) -> None:
    root = tmp_path / "derived"
    root.mkdir()
    (tmp_path / "alias").symlink_to(root, target_is_directory=True)
    path = {"same": root, "child": root / "scratch", "symlink": tmp_path / "alias"}[kind]
    with pytest.raises(g.Refusal, match="probe_parent"):
        g.guard_probe_parent(path, root)
    (tmp_path / "scratch").mkdir()
    assert g.guard_probe_parent(tmp_path / "scratch", root) == (tmp_path / "scratch").resolve()


@pytest.mark.parametrize("kind", ["missing", "file"])
def test_probe_parent_must_be_an_existing_directory(tmp_path: Path, kind: str) -> None:
    root = tmp_path / "derived"
    path = tmp_path / "scratch"
    if kind == "file":
        path.write_text("not a directory\n")
    with pytest.raises(g.Refusal, match="existing directory"):
        g.guard_probe_parent(path, root)


def test_record_provenance_is_write_once(tmp_path: Path) -> None:
    design = _load(tmp_path, _draft(tmp_path))
    shas = g.verify_inputs(design)
    out = tmp_path / "out"
    g.record_provenance(out, design, shas)
    path = out / "provenance.json"
    before = path.read_bytes()
    stat = path.stat()
    g.record_provenance(out, design, shas)
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == stat.st_mtime_ns
    with pytest.raises(g.Refusal, match="provenance"):
        g.record_provenance(out, design, {**shas, "features": "0" * 64})
    assert path.read_bytes() == before


def test_assert_unchanged_refuses_on_digest_change(tmp_path: Path) -> None:
    repo, path, design = _frozen(tmp_path)
    out = tmp_path / "out"
    g.record_provenance(out, design, g.verify_inputs(design))
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["probe_seed"] += 1
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(g.Refusal, match="changed|FROZEN_BLOB_DIFFERS"):
        g.assert_unchanged(out, path, design, repo)
    assert not (out / "leak_null_result.json").exists()


@pytest.mark.parametrize(
    "change", ["none", "input", "code", "prereg_bytes", "missing", "torn", "record"]
)
def test_assert_unchanged_rechecks_inputs_code_and_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    repo, prereg, design = _frozen(tmp_path)
    _loaded_origins(repo, monkeypatch)
    out = tmp_path / "out"
    g.record_provenance(out, design, g.verify_inputs(design))
    path = out / "provenance.json"
    if change == "input":
        Path(design.inputs["features"]["path"]).write_text("changed", encoding="utf-8")
    elif change == "code":
        (repo / PINNED[0]).write_text("# changed\n", encoding="utf-8")
    elif change == "prereg_bytes":
        prereg.write_bytes(prereg.read_bytes() + b"\n")
    elif change == "missing":
        path.unlink()
    elif change == "torn":
        path.write_text("{", encoding="utf-8")
    elif change == "record":
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["prereg_sha256"] = "0" * 64
        path.write_text(json.dumps(raw), encoding="utf-8")
    if change == "none":
        g.assert_unchanged(out, prereg, design, repo)
    else:
        with pytest.raises(g.Refusal):
            g.assert_unchanged(out, prereg, design, repo)
    assert not (out / "leak_null_result.json").exists()
