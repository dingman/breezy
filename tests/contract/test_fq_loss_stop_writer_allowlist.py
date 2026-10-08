"""FQ loss-stop writer allowlist (FQ-R8-2-UNDER-VETO plan r2 Phase 1a+1b).

T2 and T3 are closed sets. A writer row or a new caller is one reviewed
addition, and only while ``reachable_floor`` is true. The probe module is the
reader. ``app/trade.py`` is the grandfathered FQ composition.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import tomllib
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
for _entry in (str(REPO_ROOT), str(REPO_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from breezy.runtime.health import LoggingAlertSink
from breezy.strategy.forecast_quantile_ladder.loss_stop_probe import (
    REASON_UNKNOWN,
    LossStopProbe,
)
from scripts.analysis.prereg_amendment_check import (
    load_verified_amendment,
    reachable_floor,
)

_PLAN_REL: Final[str] = "docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04"
_A1_ID: Final[str] = "F5_prereg_v2_A1_floor"
_A1_REL: Final[str] = f"{_PLAN_REL}/F5_prereg_v2_amendment_A1.json"
# Hard-coded amendment paths (C-3). A1b is not listed; that row lands with A1b.
_AMENDMENT_FILES: Final[dict[str, str]] = {_A1_ID: _A1_REL}
# (path, amendment_id, frozen_sha). Empty until a frozen reachable floor exists.
_WRITERS: frozenset[tuple[str, str, str]] = frozenset()
# Widening for NEW callers is one reviewed row and requires reachable_floor.
_NEW_CALLERS: frozenset[str] = frozenset()
_GRANDFATHERED_CALLERS: Final[frozenset[str]] = frozenset(
    {
        "src/breezy/strategy/forecast_quantile_ladder/loss_stop_probe.py",
        "src/breezy/app/trade.py",
    }
)
_SCAN_DIRS: Final[tuple[str, ...]] = ("src", "scripts", "deploy")
_PROBE_REL: Final[str] = "src/breezy/strategy/forecast_quantile_ladder/loss_stop_probe.py"
_ARTEFACT_TOKEN: Final[str] = "fq-loss-stop"
_UNIT_PREFIX: Final[str] = "breezy-fq-loss-stop."
_CALL_NAME: Final[str] = "loss_stop_artefact_path"
_SHALLOW_SKIP: Final[str] = (
    "git rev-parse --is-shallow-repository returned true; "
    "a shallow clone cannot prove the amendment was frozen only once"
)


def _is_shallow_repository() -> bool:
    done = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return done.stdout.strip() == "true"


def _names_artefact(path: Path) -> bool:
    """True when ``path`` carries the artefact token. Unreadable counts as a hit."""
    try:
        payload = path.read_bytes()
    except OSError:
        return True
    return _ARTEFACT_TOKEN.encode("ascii") in payload


def _pyproject_script_names_artefact(path: Path) -> bool:
    """True when ``[project.scripts]`` names the artefact. Unparseable fails closed."""
    if not path.is_file():
        return False
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        return True
    project: object = document.get("project")
    if not isinstance(project, dict):
        return False
    scripts: object = project.get("scripts")
    if scripts is None:
        return False
    if not isinstance(scripts, dict):
        return True
    for name, target in scripts.items():
        if _ARTEFACT_TOKEN in str(name) or _ARTEFACT_TOKEN in str(target):
            return True
    return False


def scan_fq_loss_stop_writers(root: Path) -> frozenset[str]:
    """Repo-relative writers of the fq-loss-stop artefact under ``root``.

    Hits are the artefact path literal outside the probe module, a
    ``breezy-fq-loss-stop.*`` unit file, or a pyproject console script that
    names it. ``tests/`` and ``docs/`` are not scanned. The probe module is
    the reader.
    """
    found: set[str] = set()
    for dirname in _SCAN_DIRS:
        base = root / dirname
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.is_symlink() or "__pycache__" in path.parts:
                continue
            rel = path.relative_to(root).as_posix()
            if path.name.startswith(_UNIT_PREFIX):
                found.add(rel)
                continue
            if rel == _PROBE_REL:
                continue
            if _names_artefact(path):
                found.add(rel)
    if _pyproject_script_names_artefact(root / "pyproject.toml"):
        found.add("pyproject.toml")
    return frozenset(found)


def _assert_writer_rows_are_frozen(root: Path, writers: frozenset[tuple[str, str, str]]) -> None:
    """A non-empty row is legal only when the floor is reachable and the sha matches."""
    if not writers:
        return
    plan_dir = root / _PLAN_REL
    assert reachable_floor(plan_dir) is True, (
        "a non-empty _WRITERS requires reachable_floor(plan_dir)"
    )
    for path, amendment_id, frozen_sha in sorted(writers):
        loaded = load_verified_amendment(root / _AMENDMENT_FILES[amendment_id], amendment_id)
        assert loaded["frozen_sha"] == frozen_sha, (
            f"{path} cites {amendment_id} frozen_sha {frozen_sha}, loaded {loaded['frozen_sha']!r}"
        )


def _calls_loss_stop_artefact_path(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == _CALL_NAME:
            return True
        if isinstance(func, ast.Attribute) and func.attr == _CALL_NAME:
            return True
    return False


def loss_stop_artefact_path_callers(root: Path) -> frozenset[str]:
    """Relative paths under ``src/`` and ``scripts/`` that call the path helper."""
    found: set[str] = set()
    for dirname in ("src", "scripts"):
        base = root / dirname
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            if _calls_loss_stop_artefact_path(path):
                found.add(path.relative_to(root).as_posix())
    return frozenset(found)


@pytest.mark.skipif(_is_shallow_repository(), reason=_SHALLOW_SKIP)
def test_a1_floor_mode_is_unreachable_veto() -> None:
    loaded = load_verified_amendment(REPO_ROOT / _A1_REL, _A1_ID)
    floor = loaded["loss_stop_floor"]
    assert isinstance(floor, Mapping)
    assert floor["floor_mode"] == "unreachable_veto"
    assert floor["c"] is None


def test_artefact_writer_allowlist_is_empty_without_a_frozen_reachable_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    planted = tmp_path / "src" / "breezy" / "analysis" / "fq_loss_stop.py"
    planted.parent.mkdir(parents=True)
    planted.write_text('OUT = "derived/fq-loss-stop/latest.json"\n', encoding="utf-8")
    detected = scan_fq_loss_stop_writers(tmp_path)
    assert detected == frozenset({"src/breezy/analysis/fq_loss_stop.py"})

    found = scan_fq_loss_stop_writers(REPO_ROOT)
    assert found <= {row[0] for row in _WRITERS}
    _assert_writer_rows_are_frozen(REPO_ROOT, _WRITERS)

    row = ("src/breezy/analysis/fq_loss_stop.py", _A1_ID, "0" * 40)
    monkeypatch.setattr(f"{__name__}.reachable_floor", lambda _plan_dir: False)
    with pytest.raises(AssertionError, match="reachable_floor"):
        _assert_writer_rows_are_frozen(REPO_ROOT, frozenset({row}))

    def _load_other_sha(_path: Path, _amendment_id: str) -> Mapping[str, Any]:
        return {"frozen_sha": "f" * 40}

    monkeypatch.setattr(f"{__name__}.reachable_floor", lambda _plan_dir: True)
    monkeypatch.setattr(f"{__name__}.load_verified_amendment", _load_other_sha)
    with pytest.raises(AssertionError, match="frozen_sha"):
        _assert_writer_rows_are_frozen(REPO_ROOT, frozenset({row}))

    def _load_row_sha(_path: Path, _amendment_id: str) -> Mapping[str, Any]:
        return {"frozen_sha": row[2]}

    monkeypatch.setattr(f"{__name__}.load_verified_amendment", _load_row_sha)
    _assert_writer_rows_are_frozen(REPO_ROOT, frozenset({row}))


def test_loss_stop_artefact_path_callers_in_closed_allowlist() -> None:
    # Widening for NEW callers is one reviewed row and requires reachable_floor.
    # The existing app/trade.py FQ composition is grandfathered by name.
    callers = loss_stop_artefact_path_callers(REPO_ROOT)
    assert callers <= (_GRANDFATHERED_CALLERS | _NEW_CALLERS)
    assert "src/breezy/app/trade.py" in callers
    if _NEW_CALLERS:
        assert reachable_floor(REPO_ROOT / _PLAN_REL) is True


def test_missing_artefact_vetoes_with_reason_unknown(tmp_path: Path) -> None:
    path = tmp_path / "derived" / "fq-loss-stop" / "latest.json"
    assert not path.exists()

    def _now() -> datetime:
        return datetime(2026, 10, 8, 12, tzinfo=UTC)

    def _halt(_reason: str, _evidence_sha256: str) -> None:
        return None

    probe = LossStopProbe(
        path=path,
        clock=_now,
        set_family_halted=_halt,
        alert_sink=LoggingAlertSink(),
        alert_every_probe=lambda: False,
        expected_uid=os.getuid(),
    )
    probe.probe_once()
    assert probe.veto_reason() == REASON_UNKNOWN
