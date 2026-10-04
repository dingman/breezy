"""ARCH-0 seam 6c: ``stage_policy.STAGE`` (AC 15; ARCH stage S/L1/L2; AUT-5 r7 stage masks).

``STAGE`` is the one ``StagePolicy`` instance. It is built once from two reviewed literals: the
``pins`` kind-name set and ``transitions._ADMISSION_IMPLEMENTED``. Both ship empty, so the stage
that ships admits no widening row. The construction ban lives in ``test_autonomy_policy_ban.py``.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
from pathlib import Path
from typing import Final

import pytest

from breezy.persistence.autonomy import pins, stage_policy, transitions
from breezy.persistence.autonomy.schemas import (
    AdmissibilityResult,
    Kind,
    RefusalReason,
    StagePolicy,
    StageView,
)
from breezy.persistence.autonomy.stage_policy import STAGE
from breezy.persistence.autonomy.transitions import WIDENING_KINDS, rows_admissible
from tests.support.entry_points import SRC_DIR
from tests.unit.test_registry_fold import _CH, _CP, _S, CHILD, DAY, INCUMBENT, Chain

STAGE_POLICY_PATH: Final[Path] = SRC_DIR / "breezy" / "persistence" / "autonomy" / "stage_policy.py"


def test_stage_is_the_frozen_stage_policy_the_shipped_literals_describe() -> None:
    assert type(STAGE) is StagePolicy
    assert STAGE.enabled_widening_kinds == frozenset(Kind(v) for v in pins.ENABLED_WIDENING_KINDS)
    assert STAGE.admission_implemented == transitions._ADMISSION_IMPLEMENTED
    view: StageView = STAGE  # structural: both read-only kind sets exist
    assert view.enabled_widening_kinds == STAGE.enabled_widening_kinds


def test_the_shipped_stage_enables_and_implements_nothing() -> None:
    assert STAGE.enabled_widening_kinds == frozenset()
    assert STAGE.admission_implemented == frozenset()


def test_stage_is_immutable_and_has_no_instance_dict() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        STAGE.enabled_widening_kinds = frozenset({Kind.RESUME})  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        del STAGE.admission_implemented
    assert not hasattr(STAGE, "__dict__")
    assert type(STAGE.enabled_widening_kinds) is frozenset  # the sets cannot grow in place


def test_stage_is_one_instance_whichever_import_path_reaches_it() -> None:
    assert importlib.import_module("breezy.persistence.autonomy.stage_policy").STAGE is STAGE
    assert stage_policy.STAGE is STAGE


def test_build_reads_the_two_reviewed_literals_each_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pins, "ENABLED_WIDENING_KINDS", frozenset({"RESUME"}))
    monkeypatch.setattr(transitions, "_ADMISSION_IMPLEMENTED", frozenset({Kind.RESUME}))
    built = stage_policy._build()
    assert built == StagePolicy(frozenset({Kind.RESUME}), frozenset({Kind.RESUME}))
    assert built is not STAGE
    assert STAGE.enabled_widening_kinds == frozenset()  # the built-once instance never moved


@pytest.mark.parametrize("planted", ["NOT_A_KIND", "resume", "", "Kind.RESUME"])
def test_build_refuses_an_enabled_name_that_is_not_a_kind_value(
    monkeypatch: pytest.MonkeyPatch, planted: str
) -> None:
    monkeypatch.setattr(pins, "ENABLED_WIDENING_KINDS", frozenset({planted}))
    with pytest.raises(ValueError):
        stage_policy._build()


def test_shipped_admission_implemented_is_a_subset_of_the_widening_kinds() -> None:
    assert transitions._ADMISSION_IMPLEMENTED <= WIDENING_KINDS


def test_the_shipped_stage_refuses_every_widening_row_as_not_enabled() -> None:
    for kind in sorted(WIDENING_KINDS - {Kind.PROMOTE}, key=lambda k: k.value):
        chain = Chain()
        chain.add(kind, _CP, family=INCUMBENT)
        assert rows_admissible(chain.rows, stage=STAGE) == AdmissibilityResult(
            0, RefusalReason.WIDENING_KIND_NOT_ENABLED
        ), kind


def test_the_shipped_stage_admits_a_nomination_but_refuses_the_promotion() -> None:
    chain = Chain()
    chain.add(Kind.PROMOTE, _CH, family=CHILD, frm=_S)
    chain.add(Kind.PROMOTE, _CP, family=CHILD, frm=_CH, effective_launch_date=DAY)
    assert rows_admissible(chain.rows, stage=STAGE) == AdmissibilityResult(
        1, RefusalReason.WIDENING_KIND_NOT_ENABLED
    )


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            found.add((node.module or "").removeprefix("breezy.persistence.autonomy."))
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
    return found


def test_stage_policy_imports_transitions_pins_and_schemas_only() -> None:
    imports = _imports(STAGE_POLICY_PATH)
    autonomy = {i for i in imports if i in {p.stem for p in STAGE_POLICY_PATH.parent.glob("*.py")}}
    assert autonomy == {"pins", "transitions", "schemas"}
    assert not any(i.startswith(("os", "sys", "pathlib", "time", "datetime")) for i in imports)


def test_stage_policy_module_is_pure_and_has_one_public_name() -> None:
    assert stage_policy.__all__ == ["STAGE"]
    tree = ast.parse(STAGE_POLICY_PATH.read_text(encoding="utf-8"))
    calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert calls == {"Kind", "frozenset", "StagePolicy", "_build"}
