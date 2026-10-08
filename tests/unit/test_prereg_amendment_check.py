"""F5 amendment checker: sibling of the parent precommit check (r2 §2.5, §3.3).

Git-history cases use a temporary repository. The A0 content-digest pin and the
loader success path stay xfail until the coordinator's freeze stamps them.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
for _entry in (str(REPO_ROOT), str(REPO_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from breezy.analysis.autonomy import confidence_sequence as cs
from scripts.analysis import fq_mc_eprocess as mc
from scripts.analysis.multisource_blend_pin_guards import UNFROZEN
from scripts.analysis.multisource_blend_skill import content_digest
from scripts.analysis.prereg_precommit_check import MAX_LAMBDA as E25_MAX_LAMBDA

_PLAN = REPO_ROOT / "docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04"
_PARENT = _PLAN / "F5_prereg_v2_design.json"
_A0 = _PLAN / "F5_prereg_v2_amendment_A0.json"
_A0_ID = "F5_prereg_v2_A0_kill"
_ENVELOPE = frozenset({"frozen_sha", "amendment_id", "amends", "provenance"})
_KILL_KEYS = frozenset(
    {
        "kill_grid_points",
        "kill_grid_span",
        "kill_lambda_max",
        "kill_min_range",
        "kill_var_floor",
        "kill_prior_pseudo_days",
        "kill_prior_second_moment",
        "kill_lambda_cap_rule",
        "kill_betting_rule",
        "kill_bar_rule",
    }
)
# Replaced with the real digest in the stamp commit. Not a guess at the digest.
_A0_CONTENT_DIGEST = "STAMPED_AT_FREEZE"


def _chk() -> Any:
    from scripts.analysis import prereg_amendment_check as chk

    return chk


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def _commit_json(repo: Path, rel: str, payload: dict[str, Any]) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _git(repo, "add", rel)
    _git(repo, "commit", "-q", "-m", f"update {rel}")


def _init(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")


def _freeze(repo: Path, rel: str, body: dict[str, Any]) -> tuple[Path, str]:
    """Draft commit, then stamp that commit's sha as frozen_sha."""
    _commit_json(repo, rel, {**body, "frozen_sha": UNFROZEN})
    sha = _git(repo, "rev-parse", "HEAD")
    _commit_json(repo, rel, {**body, "frozen_sha": sha})
    return repo / rel, sha


def _parent_body() -> dict[str, Any]:
    design = json.loads(_PARENT.read_text(encoding="utf-8"))
    design.pop("frozen_sha")
    return design


def _kill(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kill_grid_points": cs.KILL_GRID_POINTS,
        "kill_grid_span": "grid",
        "kill_lambda_max": cs.KILL_MAX_LAMBDA,
        "kill_min_range": cs._MIN_RANGE,
        "kill_var_floor": cs._VAR_FLOOR,
        "kill_prior_pseudo_days": cs.PRIOR_PSEUDO_DAYS,
        "kill_prior_second_moment": cs.PRIOR_SECOND_MOMENT,
        "kill_lambda_cap_rule": "cap",
        "kill_betting_rule": "bet",
        "kill_bar_rule": "bar",
    }
    payload.update(overrides)
    return payload


def _a0_body(parent_rel: str, parent_sha: str, **kill_overrides: Any) -> dict[str, Any]:
    return {
        "amendment_id": _A0_ID,
        "amends": {"path": parent_rel, "frozen_sha": parent_sha},
        "kill": _kill(**kill_overrides),
        "provenance": {"note": "fixture"},
    }


def _frozen_pair(tmp: Path, *, amendment_rel: str = "amendment.json") -> tuple[Path, Path]:
    repo = tmp / "repo"
    _init(repo)
    _, parent_sha = _freeze(repo, "design.json", _parent_body())
    path, _ = _freeze(repo, amendment_rel, _a0_body("design.json", parent_sha))
    return repo, path


def _ready_draft(tmp: Path) -> tuple[Path, Path, dict[str, Any]]:
    repo = tmp / "repo"
    _init(repo)
    _, parent_sha = _freeze(repo, "design.json", _parent_body())
    payload = {**_a0_body("design.json", parent_sha), "frozen_sha": UNFROZEN}
    path = repo / "amendment.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return repo, path, payload


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_unfrozen_amendment_is_refused_by_loader(tmp_path: Path) -> None:
    from scripts.analysis.multisource_blend_refusal import Refusal

    path = tmp_path / "draft.json"
    _write(path, {"frozen_sha": UNFROZEN, "amendment_id": _A0_ID})

    with pytest.raises(Refusal, match="UNFROZEN"):
        _chk().load_verified_amendment(path, _A0_ID)


def test_amendment_exits_0_when_frozen_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo, path = _frozen_pair(tmp_path, amendment_rel="nested/amendment.json")
    chk = _chk()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    assert chk.main([str(path)]) == 0
    assert chk.main(["--draft", str(path)]) == 1


def test_parent_body_edited_is_refused(tmp_path: Path) -> None:
    repo, path = _frozen_pair(tmp_path)
    parent = repo / "design.json"
    body = json.loads(parent.read_text(encoding="utf-8"))
    body["delta_h"] = 0.15
    _write(parent, body)

    defects = _chk().validate_amendment(path)
    assert any(d.code == "FROZEN_BLOB_DIFFERS" for d in defects)
    assert _chk().main([str(path)]) == 1


def test_parent_sha_not_an_ancestor_of_head_is_refused(tmp_path: Path) -> None:
    repo, path = _frozen_pair(tmp_path)
    _git(repo, "checkout", "-q", "--orphan", "side")
    _git(repo, "commit", "-q", "-m", "unrelated root")

    defects = _chk().validate_amendment(path)
    assert any(d.code == "FROZEN_SHA_NOT_ANCESTOR" for d in defects)


def test_parent_refrozen_is_refused(tmp_path: Path) -> None:
    repo, path = _frozen_pair(tmp_path)
    parent = json.loads((repo / "design.json").read_text(encoding="utf-8"))
    parent["delta_h"] = 0.15
    parent["frozen_sha"] = _git(repo, "rev-parse", "HEAD")
    _commit_json(repo, "design.json", parent)

    defects = _chk().validate_amendment(path)
    assert any(d.code == "REFROZEN" and "design.json" in d.message for d in defects)


def test_amendment_refrozen_is_refused(tmp_path: Path) -> None:
    repo, path = _frozen_pair(tmp_path)
    body = json.loads(path.read_text(encoding="utf-8"))
    body["provenance"] = {"note": "second freeze"}
    body["frozen_sha"] = _git(repo, "rev-parse", "HEAD")
    _commit_json(repo, "amendment.json", body)

    defects = _chk().validate_amendment(path)
    assert any(d.code == "REFROZEN" and "amendment.json" in d.message for d in defects)


def test_edit_after_the_stamp_is_refused(tmp_path: Path) -> None:
    repo, path = _frozen_pair(tmp_path)
    body = json.loads(path.read_text(encoding="utf-8"))
    body["provenance"] = {"note": "edited after the stamp"}
    _commit_json(repo, path.relative_to(repo).as_posix(), body)

    defects = _chk().validate_amendment(path)
    assert any(d.code == "REFROZEN" and "amendment.json" in d.message for d in defects)


def test_shallow_clone_is_refused(tmp_path: Path) -> None:
    repo, path = _frozen_pair(tmp_path)
    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", repo.as_uri(), str(clone)],
        check=True,
        capture_output=True,
    )

    defects = _chk().validate_amendment(clone / path.name)
    assert any(d.code == "REFROZEN" and "shallow" in d.message for d in defects)


def test_unknown_top_level_key_is_refused(tmp_path: Path) -> None:
    _repo, path, payload = _ready_draft(tmp_path)
    payload["extra"] = 1
    _write(path, payload)

    defects = _chk().validate_amendment(path, draft=True)
    assert any(d.code == "BAD_KEYS" for d in defects)
    assert _chk().main(["--draft", str(path)]) == 1


def test_payload_key_equal_to_a_parent_key_is_refused(tmp_path: Path) -> None:
    _repo, path, payload = _ready_draft(tmp_path)
    payload["kill"] = _kill(theta=0)
    _write(path, payload)

    defects = _chk().validate_amendment(path, draft=True)
    assert any(d.code == "KEY_OVERLAP" and "theta" in d.message for d in defects)


def test_payload_key_equal_to_an_a0_key_inside_a1_is_refused(tmp_path: Path) -> None:
    repo, _path, _payload = _ready_draft(tmp_path)
    parent_sha = json.loads((repo / "design.json").read_text(encoding="utf-8"))["frozen_sha"]
    earlier = {
        "frozen_sha": UNFROZEN,
        "amendment_id": _A0_ID,
        "amends": {"path": "design.json", "frozen_sha": parent_sha},
        "kill": {"kill_grid_points": cs.KILL_GRID_POINTS},
        "provenance": {},
    }
    _write(repo / "F5_prereg_v2_amendment_A0.json", earlier)
    a1 = {
        "frozen_sha": UNFROZEN,
        "amendment_id": "F5_prereg_v2_A1_floor",
        "amends": {"path": "design.json", "frozen_sha": parent_sha},
        "loss_stop_floor": {"kill_grid_points": cs.KILL_GRID_POINTS},
        "provenance": {},
    }
    path = repo / "a1.json"
    _write(path, a1)

    defects = _chk().validate_amendment(path, draft=True)
    assert any(d.code == "KEY_OVERLAP" and "kill_grid_points" in d.message for d in defects)
    assert any(d.code == "PAYLOAD_NOT_YET_DEFINED" for d in defects)


def test_amends_with_an_extra_key_is_refused(tmp_path: Path) -> None:
    _repo, path, payload = _ready_draft(tmp_path)
    payload["amends"] = {**payload["amends"], "content_sha256": "not-a-field"}
    _write(path, payload)

    defects = _chk().validate_amendment(path, draft=True)
    assert any(d.code == "BAD_AMENDS" for d in defects)


def test_envelope_keys_exempt_from_overlap(tmp_path: Path) -> None:
    _repo, path, payload = _ready_draft(tmp_path)
    payload["provenance"] = {"theta": "envelope nested keys are exempt"}
    _write(path, payload)

    assert _chk().validate_amendment(path, draft=True) == []
    assert _chk().main(["--draft", str(path)]) == 0


def test_kill_constants_equal_a0_production_and_mc() -> None:
    amendment = json.loads(_A0.read_text(encoding="utf-8"))
    kill = amendment["kill"]
    assert set(kill) == _KILL_KEYS
    assert kill["kill_grid_points"] == cs.KILL_GRID_POINTS == mc.KILL_GRID_POINTS
    assert kill["kill_lambda_max"] == cs.KILL_MAX_LAMBDA == mc.MAX_LAMBDA
    assert kill["kill_lambda_max"] <= E25_MAX_LAMBDA
    assert kill["kill_prior_pseudo_days"] == cs.PRIOR_PSEUDO_DAYS == mc.PRIOR_PSEUDO_DAYS
    assert kill["kill_prior_second_moment"] == cs.PRIOR_SECOND_MOMENT == mc.PRIOR_SECOND_MOMENT
    assert kill["kill_min_range"] == cs._MIN_RANGE
    assert kill["kill_var_floor"] == cs._VAR_FLOOR
    assert "including zero-take days with y = 0" in kill["kill_betting_rule"]
    assert "settled days" not in kill["kill_betting_rule"]
    report = amendment["provenance"]["kill_power_report"]
    assert report["seed"] == 20261008
    assert report["role"] == "reporting_only_changes_no_constant"


def test_mc_kill_increment_literals_equal_production_constants() -> None:
    """The min-range literal is the np.maximum floor, not the cap numerator (A0-C5)."""
    source = Path(mc.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    fn = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_kill_increment"
    )
    floors: list[float] = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call) or len(node.args) < 2:
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "maximum":
            continue
        floor = node.args[1]
        if isinstance(floor, ast.Constant) and type(floor.value) is float:
            floors.append(floor.value)
    assert floors == [cs._VAR_FLOOR, cs._MIN_RANGE]
    halves = [
        node.value
        for node in ast.walk(fn)
        if isinstance(node, ast.Constant) and node.value == cs._MIN_RANGE
    ]
    assert len(halves) == 2
    assert floors.count(cs._MIN_RANGE) == 1


def test_a0_payload_keys_disjoint_from_parent() -> None:
    parent = json.loads(_PARENT.read_text(encoding="utf-8"))
    amendment = json.loads(_A0.read_text(encoding="utf-8"))
    assert set(amendment) == _ENVELOPE | {"kill"}
    assert set(amendment["amends"]) == {"path", "frozen_sha"}
    assert amendment["amendment_id"] == _A0_ID
    assert amendment["frozen_sha"] == UNFROZEN
    assert amendment["amends"]["path"] == _PARENT.relative_to(REPO_ROOT).as_posix()
    assert amendment["amends"]["frozen_sha"] == parent["frozen_sha"]
    occupied = {key for key in amendment if key not in _ENVELOPE}
    occupied.update(amendment["kill"])
    assert "theta" in parent
    assert occupied.isdisjoint(parent)


@pytest.mark.xfail(strict=True, reason="stamped at freeze")
def test_F5_prereg_v2_A0_kill_content_digest_pinned() -> None:
    amendment = json.loads(_A0.read_text(encoding="utf-8"))
    assert content_digest(amendment) == _A0_CONTENT_DIGEST


@pytest.mark.xfail(strict=True, reason="stamped at freeze")
def test_a0_loads_through_load_verified_amendment() -> None:
    loaded = _chk().load_verified_amendment(_A0, _A0_ID)
    assert loaded["amendment_id"] == _A0_ID
    assert loaded["frozen_sha"] != UNFROZEN
