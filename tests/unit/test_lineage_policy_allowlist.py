"""ARCH-0 seam A 8a: the lineage-policy gate in `persistence/live_orders_gate.py`.

`lineage_policy_authorized` decides whether a CHILD family (`<root>_rNNNN`) may be
routed under its root's lineage-policy ruling. It reuses the move-only
`_verify_ruling_file` extraction, uses existing `LiveOrdersReason` members only and
carries no permit semantics. The allowlist ships empty (AUT-5 WP9 adds the one row), so
tests inject a fixture allowlist through the private `_lineage_policy_authorized`.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import inspect
import typing
from pathlib import Path
from typing import Any

import pytest

from breezy.persistence import live_orders_gate as gate
from breezy.persistence.family_manifest import FamilyManifest, load_family_manifest
from breezy.persistence.live_orders_gate import (
    LiveOrdersGateRefusedError,
    LiveOrdersReason,
    live_orders_authorized,
)
from tests.unit.test_family_manifest import _VALID, _write

_ROOT = "pm_us_crh_v2"
_CHILD = "pm_us_crh_v2_r0001"
_POLICY_RULING = "RULING_lineage_policy_fixture"
_POLICY_BYTES = b"fixture lineage policy ruling\n"
_POLICY_SHA = hashlib.sha256(_POLICY_BYTES).hexdigest()
_OPERATOR_RULING = "RULING_operator_fq_live_real_orders_2026-10-01"
_GATE_SOURCE = Path(str(inspect.getsourcefile(gate)))


def _child(
    tmp_path: Path, *, family_id: str = _CHILD, ruling: str | None = _POLICY_RULING
) -> FamilyManifest:
    base = load_family_manifest(_write(tmp_path, _VALID))
    return dataclasses.replace(base, family_id=family_id, live_orders_ruling=ruling)


def _repo(tmp_path: Path, *, body: bytes | None = _POLICY_BYTES) -> Path:
    rulings = tmp_path / "repo" / "deploy" / "families" / "rulings"
    rulings.mkdir(parents=True)
    if body is not None:
        (rulings / f"{_POLICY_RULING}.md").write_bytes(body)
    return tmp_path / "repo"


_ROW = (_ROOT, _POLICY_RULING, _POLICY_SHA)


def _authorize(child: FamilyManifest, repo: Path, *, allowlist: Any = frozenset({_ROW})) -> Any:
    return gate._lineage_policy_authorized(child, _ROOT, repo, allowlist=allowlist)


def _refusal_reason(child: FamilyManifest, repo: Path, **kw: Any) -> str:
    with pytest.raises(LiveOrdersGateRefusedError) as err:
        _authorize(child, repo, **kw)
    return err.value.reason


def test_lineage_policy_allowlist_is_literal_only() -> None:
    tree = ast.parse(_GATE_SOURCE.read_text(encoding="utf-8"))
    values = [
        n.value
        for n in tree.body
        if isinstance(n, ast.AnnAssign)
        and isinstance(n.target, ast.Name)
        and n.target.id == "_LINEAGE_POLICY_ALLOWLIST"
        and n.value is not None
    ]
    assert len(values) == 1
    (value,) = values
    # A `frozenset(...)` call whose only argument is absent or a set display of literal
    # str 3-tuples; never computed, never read from disk or a manifest.
    assert isinstance(value, ast.Call)
    assert isinstance(value.func, ast.Name) and value.func.id == "frozenset"
    assert not value.keywords and len(value.args) <= 1
    for arg in value.args:
        assert isinstance(arg, ast.Set)
        for row in arg.elts:
            assert isinstance(row, ast.Tuple) and len(row.elts) == 3
            assert all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in row.elts)
    assert gate._LINEAGE_POLICY_ALLOWLIST == frozenset()


def test_child_requires_lineage_triple_and_policy_ruling(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    child = _child(tmp_path)
    decision = _authorize(child, repo)
    assert decision.authorized is True
    assert decision.reason == "ok"
    assert decision.ruling_sha256 == _POLICY_SHA
    # No allowlist row for the root: refused.
    assert _refusal_reason(child, repo, allowlist=frozenset()) == "not_allowlisted"
    other_root = frozenset({("other_root", _POLICY_RULING, _POLICY_SHA)})
    assert _refusal_reason(child, repo, allowlist=other_root) == "not_allowlisted"
    other_ruling = frozenset({(_ROOT, "RULING_other", _POLICY_SHA)})
    assert _refusal_reason(child, repo, allowlist=other_ruling) == "not_allowlisted"
    # The shipped allowlist is empty, so the public function refuses every child.
    with pytest.raises(LiveOrdersGateRefusedError) as err:
        gate.lineage_policy_authorized(child, _ROOT, repo)
    assert err.value.reason == "not_allowlisted"


def test_child_without_declared_ruling_is_not_authorized(tmp_path: Path) -> None:
    decision = _authorize(_child(tmp_path, ruling=None), _repo(tmp_path))
    assert (decision.authorized, decision.reason, decision.ruling_sha256) == (
        False,
        "no_ruling",
        None,
    )


def test_child_with_operator_ruling_refused(tmp_path: Path) -> None:
    # The child declares the ROOT's operator ruling, not the lineage-policy ruling.
    child = _child(tmp_path, ruling=_OPERATOR_RULING)
    assert _refusal_reason(child, _repo(tmp_path)) == "not_allowlisted"


def test_tampered_policy_ruling_refuses_child(tmp_path: Path) -> None:
    repo = _repo(tmp_path, body=_POLICY_BYTES + b" ")
    assert _refusal_reason(_child(tmp_path), repo) == "ruling_sha_mismatch"


def test_lineage_gate_refuses_missing_ruling_file(tmp_path: Path) -> None:
    repo = _repo(tmp_path, body=None)
    assert _refusal_reason(_child(tmp_path), repo) == "ruling_missing"


def test_lineage_gate_refuses_ruling_symlinked_outside_subtree(tmp_path: Path) -> None:
    repo = _repo(tmp_path, body=None)
    outside = tmp_path / "outside.md"
    outside.write_bytes(_POLICY_BYTES)
    (repo / "deploy" / "families" / "rulings" / f"{_POLICY_RULING}.md").symlink_to(outside)
    assert _refusal_reason(_child(tmp_path), repo) == "ruling_outside_evidence"


@pytest.mark.parametrize(
    "child_id",
    [
        _ROOT,  # the root itself is not a child
        "other_root_r0001",  # a different lineage
        "pm_us_crh_v2_r001",  # three digits
        "pm_us_crh_v2_r00001",  # five digits
        "pm_us_crh_v2_R0001",  # wrong case
        "pm_us_crh_v2_r0001\n",  # trailing newline must not slip past `$`
        "pm_us_crh_v2_r000١",  # non-ASCII digit
        "pm_us_crh_v2_r0001_r0002",  # grandchild: root group is not the root
        "",
    ],
)
def test_lineage_gate_refuses_child_id_outside_root_lineage(tmp_path: Path, child_id: str) -> None:
    child = _child(tmp_path, family_id=child_id)
    assert _refusal_reason(child, _repo(tmp_path)) == "not_allowlisted"


def test_child_family_id_regex_shape() -> None:
    match = gate.CHILD_FAMILY_ID_RE.match("pm_us_crh_fq_v1_r0007")
    assert match is not None and match.group("root") == "pm_us_crh_fq_v1"
    assert gate.CHILD_FAMILY_ID_RE.flags & 256  # re.ASCII
    assert gate.CHILD_FAMILY_ID_RE.pattern == (r"\A(?P<root>[a-z0-9_]{1,58})_r[0-9]{4}\Z")
    assert gate.CHILD_FAMILY_ID_RE.match("a" * 59 + "_r0001") is None


def test_lineage_decision_carries_no_permit_semantics() -> None:
    fields = {f.name for f in dataclasses.fields(gate.LineagePolicyDecision)}
    assert fields == {"authorized", "reason", "ruling_sha256"}
    for name in ("lineage_policy_authorized", "_lineage_policy_authorized"):
        assert "permit_present" not in inspect.signature(getattr(gate, name)).parameters
    assert list(inspect.signature(gate.lineage_policy_authorized).parameters) == [
        "child",
        "root_family_id",
        "repo_root",
    ]
    # No new LiveOrdersReason member (AC 20).
    assert set(typing.get_args(LiveOrdersReason)) == {
        "no_ruling",
        "not_allowlisted",
        "ruling_missing",
        "ruling_outside_evidence",
        "ruling_sha_mismatch",
        "permit_absent",
        "ok",
    }


def test_verify_ruling_file_extraction_keeps_reasons_and_messages(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    ok_path = repo / "deploy" / "families" / "rulings" / f"{_POLICY_RULING}.md"
    # Pass: returns None.
    gate._verify_ruling_file(_POLICY_RULING, _POLICY_SHA, repo)
    # Mismatch: verbatim message.
    wrong = "0" * 64
    with pytest.raises(LiveOrdersGateRefusedError) as err:
        gate._verify_ruling_file(_POLICY_RULING, wrong, repo)
    assert err.value.reason == "ruling_sha_mismatch"
    assert str(err.value) == (
        f"ruling {_POLICY_RULING!r} sha256 mismatch: expected {wrong}, got {_POLICY_SHA}"
    )
    # Missing: verbatim message.
    with pytest.raises(LiveOrdersGateRefusedError) as err:
        gate._verify_ruling_file("RULING_absent", _POLICY_SHA, repo)
    assert err.value.reason == "ruling_missing"
    absent = repo / "deploy" / "families" / "rulings" / "RULING_absent.md"
    assert str(err.value) == f"ruling file missing: {absent.resolve()}"
    # Escape: verbatim message.
    with pytest.raises(LiveOrdersGateRefusedError) as err:
        gate._verify_ruling_file("../../../escape", _POLICY_SHA, repo)
    assert err.value.reason == "ruling_outside_evidence"
    assert str(err.value) == ("ruling path for '../../../escape' escapes deploy/families/rulings")
    assert ok_path.is_file()


def test_live_orders_authorized_still_delegates_to_the_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, str, Path]] = []
    real = gate._verify_ruling_file

    def spy(ruling_id: str, expected: str, repo_root: Path) -> None:
        calls.append((ruling_id, expected, repo_root))
        real(ruling_id, expected, repo_root)

    repo_root = Path(__file__).resolve().parents[2]
    manifest = dataclasses.replace(
        load_family_manifest(_write(tmp_path, _VALID)),
        family_id="pm_us_crh_fq_v1",
        live_orders_ruling=_OPERATOR_RULING,
    )
    monkeypatch.setattr(gate, "_verify_ruling_file", spy)
    decision = live_orders_authorized(manifest, repo_root, permit_present=False)
    assert decision.reason == "permit_absent"
    assert [(c[0], c[2]) for c in calls] == [(_OPERATOR_RULING, repo_root)]
