"""ARCH-0 seam 4a: the owner-placeholder gate (seam A AC 27; ARCH section 4.7).

Carried stubs for tests whose GREEN belongs to another owner sit under
``xfail(strict=True, raises=OwnerPending)`` and have a row in
``autonomy_owner_placeholders.OWNER_PLACEHOLDERS``. These tests keep the mechanism honest:

* markers equal the ledger, in the decorator form and in the ``pytest.param(..., marks=...)`` form;
* a row whose declared owner symbol now resolves is stale;
* every row's owner names a plan (and work-package token) that exists in the plan docs;
* the section 4.7 envelope manifest equals the frozen ARCH, with the E-11 renames applied;
* every manifest node id is collected and carries no skip marker or skip call;
* no widening kind is enabled while a ledger row still blocks it;
* no row blocks fewer kinds than the frozen floor.

The ledger is empty at seam 4a (seam 4b carries the stubs), so each gate also runs against planted
rows and planted sources: that is what makes an empty ledger a proof and not a vacuum.
"""

from __future__ import annotations

import ast
import functools
import hashlib
import os
import re
import subprocess
import sys
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Final

import pytest

from breezy.persistence.autonomy import pins
from tests.support.autonomy_owner import OwnerPending, declared_module_names, require_owner_symbol
from tests.support.entry_points import REPO_ROOT
from tests.unit.autonomy_blocks_kinds_floor import BLOCKS_KINDS_FLOOR, FLOOR_KIND_VOCABULARY
from tests.unit.autonomy_envelope_manifest import (
    ARCH_FREEZE_SHA256,
    E11_RENAMES,
    ENVELOPE_NODE_IDS,
    ENVELOPE_PENDING_NAMES,
)
from tests.unit.autonomy_owner_placeholders import OWNER_PLACEHOLDERS, OwnerRow

PLANS_DIR: Final[Path] = REPO_ROOT / "docs/plans/backlog/AUTONOMY_2026-10-03"
ARCH_PATH: Final[Path] = PLANS_DIR / "AUTONOMY_ARCHITECTURE.md"
TESTS_DIR: Final[Path] = REPO_ROOT / "tests"

#: A marker scan over fewer files than this is vacuous (hundreds of test files exist).
MIN_SCANNED_TEST_FILES: Final = 100
#: ARCH section 4.7 names 167 distinct tests after the E-11 renames; fewer means a parse bug.
MIN_ENVELOPE_NAMES: Final = 150


# ---------------------------------------------------------------------------
# Scanning tests/ for owner markers
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OwnerMarker:
    node_id: str
    strict: bool
    form: str  # "decorator" | "param" | "pytestmark"


def _is_owner_xfail(expr: ast.AST) -> bool:
    if not isinstance(expr, ast.Call):
        return False
    if ast.unparse(expr.func).split(".")[-1] != "xfail":
        return False
    return any(
        kw.arg == "raises" and ast.unparse(kw.value).split(".")[-1] == "OwnerPending"
        for kw in expr.keywords
    )


def _is_strict(call: ast.Call) -> bool:
    return any(
        kw.arg == "strict" and isinstance(kw.value, ast.Constant) and kw.value.value is True
        for kw in call.keywords
    )


def _owner_xfails(expr: ast.AST) -> list[ast.Call]:
    return [n for n in ast.walk(expr) if isinstance(n, ast.Call) and _is_owner_xfail(n)]


def _param_calls(expr: ast.AST) -> list[ast.Call]:
    return [
        n
        for n in ast.walk(expr)
        if isinstance(n, ast.Call) and ast.unparse(n.func).split(".")[-1] == "param"
    ]


def _literal_id(call: ast.Call) -> str | None:
    for kw in call.keywords:
        if (
            kw.arg == "id"
            and isinstance(kw.value, ast.Constant)
            and isinstance(kw.value.value, str)
        ):
            return kw.value.value
    return None


def _functions(
    body: Sequence[ast.stmt], prefix: tuple[str, ...]
) -> Iterator[tuple[tuple[str, ...], ast.FunctionDef | ast.AsyncFunctionDef]]:
    for node in body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            yield (*prefix, node.name), node
        elif isinstance(node, ast.ClassDef):
            yield from _functions(node.body, (*prefix, node.name))


def _pytestmark_markers(
    path: str, body: Sequence[ast.stmt], prefix: tuple[str, ...]
) -> list[OwnerMarker]:
    found: list[OwnerMarker] = []
    for node in body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets
        ):
            found.extend(
                OwnerMarker("::".join([path, *prefix, "*"]), _is_strict(call), "pytestmark")
                for call in _owner_xfails(node.value)
            )
        elif isinstance(node, ast.ClassDef):
            found.extend(_pytestmark_markers(path, node.body, (*prefix, node.name)))
    return found


def scan_owner_markers(path: str, source: str) -> list[OwnerMarker]:
    """Every ``xfail(raises=OwnerPending)`` marker in ``source``, as a node id."""
    tree = ast.parse(source, filename=path)
    found = _pytestmark_markers(path, tree.body, ())
    for parts, func in _functions(tree.body, ()):
        base = "::".join([path, *parts])
        for decorator in func.decorator_list:
            found.extend(
                OwnerMarker(base, _is_strict(call), "decorator")
                for call in _owner_xfails(decorator)
                if call is decorator
            )
            for param in _param_calls(decorator):
                marks = [kw.value for kw in param.keywords if kw.arg == "marks"]
                for call in (c for m in marks for c in _owner_xfails(m)):
                    param_id = _literal_id(param)
                    suffix = f"[{param_id}]" if param_id is not None else "[<no literal id>]"
                    found.append(OwnerMarker(base + suffix, _is_strict(call), "param"))
    return found


@functools.cache
def _test_sources() -> tuple[tuple[str, str], ...]:
    return tuple(
        (path.relative_to(REPO_ROOT).as_posix(), path.read_text(encoding="utf-8"))
        for path in sorted(TESTS_DIR.rglob("*.py"))
    )


def real_tree_markers() -> list[OwnerMarker]:
    return [m for path, source in _test_sources() for m in scan_owner_markers(path, source)]


def ledger_marker_problems(rows: Iterable[OwnerRow], markers: Iterable[OwnerMarker]) -> list[str]:
    ledger = [row.node_id for row in rows]
    marked = [marker.node_id for marker in markers]
    problems = [
        f"duplicate ledger row {n}" for n in sorted({n for n in ledger if ledger.count(n) > 1})
    ]
    problems += [f"marker without ledger row: {n}" for n in sorted(set(marked) - set(ledger))]
    problems += [f"ledger row without marker: {n}" for n in sorted(set(ledger) - set(marked))]
    return problems


def non_strict_markers(markers: Iterable[OwnerMarker]) -> list[str]:
    return [m.node_id for m in markers if not m.strict]


_DECORATED: Final = (
    "import pytest\nfrom tests.support.autonomy_owner import OwnerPending\n"
    "@pytest.mark.xfail(strict=True, raises=OwnerPending)\n"
    "def test_carried() -> None:\n    ...\n"
)
_PARAMETRISED: Final = (
    "import pytest\nfrom tests.support.autonomy_owner import OwnerPending\n"
    "@pytest.mark.parametrize('x', [\n"
    "    pytest.param(1, id='real'),\n"
    "    pytest.param(2, id='owner', marks=pytest.mark.xfail(strict=True, raises=OwnerPending)),\n"
    "])\n"
    "def test_half_real(x: int) -> None:\n    ...\n"
)


def test_owner_placeholder_ledger_matches_markers() -> None:
    assert len(_test_sources()) >= MIN_SCANNED_TEST_FILES
    markers = real_tree_markers()
    assert ledger_marker_problems(OWNER_PLACEHOLDERS, markers) == []
    assert non_strict_markers(markers) == []
    for row in OWNER_PLACEHOLDERS:
        file_part, _, _ = row.node_id.partition("::")
        assert (REPO_ROOT / file_part).is_file(), f"ledger row names a missing file: {row.node_id}"
        assert row.owner and row.owner_symbol
        assert row.blocks_kinds <= FLOOR_KIND_VOCABULARY, row.node_id


def test_marker_scan_finds_the_decorator_form() -> None:
    markers = scan_owner_markers("tests/unit/planted.py", _DECORATED)
    assert [(m.node_id, m.strict, m.form) for m in markers] == [
        ("tests/unit/planted.py::test_carried", True, "decorator")
    ]


def test_marker_scan_finds_the_pytest_param_form_and_only_the_marked_param() -> None:
    markers = scan_owner_markers("tests/unit/planted.py", _PARAMETRISED)
    assert [(m.node_id, m.form) for m in markers] == [
        ("tests/unit/planted.py::test_half_real[owner]", "param")
    ]


def test_marker_scan_finds_markers_on_methods_and_in_class_pytestmark() -> None:
    source = (
        "import pytest\nfrom tests.support.autonomy_owner import OwnerPending\n"
        "class TestGroup:\n"
        "    pytestmark = pytest.mark.xfail(strict=True, raises=OwnerPending)\n"
        "    @pytest.mark.xfail(strict=True, raises=OwnerPending)\n"
        "    def test_method(self) -> None: ...\n"
    )
    ids = {m.node_id for m in scan_owner_markers("tests/unit/planted.py", source)}
    assert ids == {
        "tests/unit/planted.py::TestGroup::*",
        "tests/unit/planted.py::TestGroup::test_method",
    }


def test_marker_scan_ignores_other_xfails_and_other_exceptions() -> None:
    source = (
        "import pytest\n"
        "@pytest.mark.xfail(strict=True, raises=ValueError)\n"
        "def test_a() -> None: ...\n"
        "@pytest.mark.xfail(strict=True)\n"
        "def test_b() -> None: ...\n"
        "@pytest.mark.skip\n"
        "def test_c() -> None: ...\n"
    )
    assert scan_owner_markers("tests/unit/planted.py", source) == []


def test_marker_scan_reports_a_non_strict_marker() -> None:
    source = _DECORATED.replace("strict=True, ", "")
    markers = scan_owner_markers("tests/unit/planted.py", source)
    assert non_strict_markers(markers) == ["tests/unit/planted.py::test_carried"]


def test_marker_scan_reports_a_param_without_a_literal_id_so_it_cannot_match_a_row() -> None:
    source = _PARAMETRISED.replace(", id='owner'", "")
    markers = scan_owner_markers("tests/unit/planted.py", source)
    assert [m.node_id for m in markers] == [
        "tests/unit/planted.py::test_half_real[<no literal id>]"
    ]


_ROW: Final = OwnerRow(
    "tests/unit/planted.py::test_carried",
    "AUT-5:WP1",
    "breezy.persistence.autonomy.resolver:resolve_sending_family",
    frozenset({"PROMOTE"}),
)


def test_a_marker_without_a_ledger_row_is_a_mismatch() -> None:
    markers = scan_owner_markers("tests/unit/planted.py", _DECORATED)
    assert ledger_marker_problems([], markers) == [
        "marker without ledger row: tests/unit/planted.py::test_carried"
    ]


def test_a_ledger_row_without_a_marker_is_a_mismatch() -> None:
    assert ledger_marker_problems([_ROW], []) == [
        "ledger row without marker: tests/unit/planted.py::test_carried"
    ]


def test_matching_marker_and_row_agree_in_both_forms() -> None:
    decorated = scan_owner_markers("tests/unit/planted.py", _DECORATED)
    assert ledger_marker_problems([_ROW], decorated) == []
    param_row = _ROW._replace(node_id="tests/unit/planted.py::test_half_real[owner]")
    param = scan_owner_markers("tests/unit/planted.py", _PARAMETRISED)
    assert ledger_marker_problems([param_row], param) == []


def test_a_duplicate_ledger_row_is_a_mismatch() -> None:
    markers = scan_owner_markers("tests/unit/planted.py", _DECORATED)
    assert ledger_marker_problems([_ROW, _ROW], markers) == [
        "duplicate ledger row tests/unit/planted.py::test_carried"
    ]


# ---------------------------------------------------------------------------
# require_owner_symbol: narrow OwnerPending
# ---------------------------------------------------------------------------


def test_require_owner_symbol_returns_a_delivered_symbol() -> None:
    value = require_owner_symbol("breezy.persistence.autonomy.canonical", "canonical_json")
    assert callable(value)
    assert isinstance(require_owner_symbol("breezy.persistence.autonomy.canonical"), ModuleType)


def test_require_owner_symbol_is_pending_for_an_absent_module_and_its_absent_ancestors() -> None:
    with pytest.raises(OwnerPending):
        require_owner_symbol("breezy.persistence.autonomy.not_delivered_yet", "x")
    with pytest.raises(OwnerPending):
        require_owner_symbol("breezy.not_delivered_package.child", "x")


def test_require_owner_symbol_is_pending_for_an_absent_attribute_of_a_delivered_module() -> None:
    with pytest.raises(OwnerPending):
        require_owner_symbol("breezy.persistence.autonomy.canonical", "not_delivered_yet")
    with pytest.raises(OwnerPending):
        require_owner_symbol(
            "breezy.persistence.autonomy.canonical", "canonical_json.nested.missing"
        )


def test_declared_module_names_exclude_the_root_package() -> None:
    assert declared_module_names("breezy.a.b") == {"breezy.a", "breezy.a.b"}
    assert declared_module_names("breezy") == {"breezy"}
    assert declared_module_names("thirdparty.mod") == {"thirdparty.mod"}


def test_require_owner_symbol_propagates_broken_owner_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A module that exists but fails to import must fail the stub, never xfail it."""
    package = tmp_path / "ownerpkg_broken"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "imports_a_missing_dependency.py").write_text(
        "import a_dependency_that_is_not_installed_anywhere\n", encoding="utf-8"
    )
    (package / "raises_on_import.py").write_text("raise RuntimeError('boom')\n", encoding="utf-8")
    (package / "bad_name.py").write_text("from os import not_a_name\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    with pytest.raises(ModuleNotFoundError):
        require_owner_symbol("ownerpkg_broken.imports_a_missing_dependency", "x")
    with pytest.raises(RuntimeError):
        require_owner_symbol("ownerpkg_broken.raises_on_import", "x")
    with pytest.raises(ImportError):
        require_owner_symbol("ownerpkg_broken.bad_name", "x")
    with pytest.raises(OwnerPending):
        require_owner_symbol("ownerpkg_broken.truly_absent", "x")


# ---------------------------------------------------------------------------
# Symbol absent
# ---------------------------------------------------------------------------


def split_symbol(owner_symbol: str) -> tuple[str, str | None]:
    module, _, attribute = owner_symbol.partition(":")
    return module, attribute or None


def stale_rows(rows: Iterable[OwnerRow]) -> list[OwnerRow]:
    """Rows whose declared owner symbol now resolves: the owner landed it, so the row must go."""
    stale: list[OwnerRow] = []
    for row in rows:
        module, attribute = split_symbol(row.owner_symbol)
        try:
            require_owner_symbol(module, attribute)
        except OwnerPending:
            continue
        stale.append(row)
    return stale


def test_owner_placeholder_symbol_absent() -> None:
    assert stale_rows(OWNER_PLACEHOLDERS) == []


def test_a_row_whose_symbol_resolves_is_stale() -> None:
    resolved = _ROW._replace(owner_symbol="breezy.persistence.autonomy.canonical:canonical_json")
    module_only = _ROW._replace(owner_symbol="breezy.persistence.autonomy.canonical")
    assert stale_rows([resolved, module_only]) == [resolved, module_only]


def test_a_row_whose_symbol_is_still_absent_is_not_stale() -> None:
    assert stale_rows([_ROW]) == []
    attribute_absent = _ROW._replace(owner_symbol="breezy.persistence.autonomy.canonical:not_yet")
    assert stale_rows([attribute_absent]) == []


# ---------------------------------------------------------------------------
# Owner ids exist in the plan docs
# ---------------------------------------------------------------------------

_PLAN_FILE_RE: Final = re.compile(
    r"\A(?P<id>ARCH-0-seam[AB]|AUT-\d+)(?:-[a-z][a-z-]*)?_plan_r(?P<rev>\d+)\.md\Z"
)


def newest_plans(plans_dir: Path) -> dict[str, Path]:
    newest: dict[str, tuple[int, Path]] = {}
    for path in sorted(plans_dir.glob("*_plan_r*.md")):
        match = _PLAN_FILE_RE.match(path.name)
        if match is None:
            continue
        revision = int(match.group("rev"))
        if match.group("id") not in newest or revision > newest[match.group("id")][0]:
            newest[match.group("id")] = (revision, path)
    return {plan_id: path for plan_id, (_, path) in newest.items()}


def owner_problem(owner: str, plans: Mapping[str, Path]) -> str | None:
    """Why ``owner`` (``<plan id>`` or ``<plan id>:<token>``) is not a plan reference, or None."""
    plan_id, _, token = owner.partition(":")
    if plan_id not in plans:
        return f"{owner}: no plan {plan_id!r}"
    if token:
        pattern = rf"(?<![A-Za-z0-9]){re.escape(token)}(?![A-Za-z0-9])"
        if re.search(pattern, plans[plan_id].read_text(encoding="utf-8")) is None:
            return f"{owner}: token {token!r} not in {plans[plan_id].name}"
    return None


def owner_problems(rows: Iterable[OwnerRow], plans_dir: Path) -> list[str]:
    plans = newest_plans(plans_dir)
    return [p for row in rows if (p := owner_problem(row.owner, plans)) is not None]


def test_owner_ids_exist_in_plan_docs() -> None:
    plans = newest_plans(PLANS_DIR)
    assert {"ARCH-0-seamA", "ARCH-0-seamB", "AUT-1", "AUT-5", "AUT-6", "AUT-7"} <= set(plans)
    assert owner_problems(OWNER_PLACEHOLDERS, PLANS_DIR) == []
    assert owner_problem("AUT-5:WP1", plans) is None  # the owner form seam 4b will use


def test_an_owner_with_no_plan_doc_is_refused(tmp_path: Path) -> None:
    assert owner_problems([_ROW._replace(owner="AUT-99")], PLANS_DIR) == [
        "AUT-99: no plan 'AUT-99'"
    ]
    assert owner_problems([_ROW._replace(owner="AUT-5:WP1")], tmp_path) == [
        "AUT-5:WP1: no plan 'AUT-5'"
    ]


def test_an_owner_token_missing_from_the_newest_plan_is_refused() -> None:
    problems = owner_problems([_ROW._replace(owner="AUT-5:WP99z")], PLANS_DIR)
    assert len(problems) == 1 and "token 'WP99z'" in problems[0]


def test_the_newest_revision_of_each_plan_is_the_one_checked(tmp_path: Path) -> None:
    (tmp_path / "AUT-5-promotion-demotion_plan_r2.md").write_text("old WPold", encoding="utf-8")
    (tmp_path / "AUT-5-promotion-demotion_plan_r10.md").write_text("new WPnew", encoding="utf-8")
    plans = newest_plans(tmp_path)
    assert plans["AUT-5"].name.endswith("_r10.md")
    assert owner_problem("AUT-5:WPnew", plans) is None
    assert owner_problem("AUT-5:WPold", plans) is not None


# ---------------------------------------------------------------------------
# The envelope manifest equals the frozen ARCH
# ---------------------------------------------------------------------------


def extract_envelope_names(arch_text: str) -> list[str]:
    """Backticked ``test_*`` names in the section 4.7 "New test" column, in order.

    ARCH abbreviates a sibling as ``…_suffix``; it expands against the previous name by replacing
    that name's last ``_word``. The extraction fails closed when the table or its names are absent.
    """
    lines = arch_text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("| New test |")), None)
    if start is None:
        raise AssertionError("section 4.7 table not found")
    names: list[str] = []
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        previous: str | None = None
        for token in re.findall(r"`([^`]+)`", line.split("|")[1]):
            if token.startswith("test_"):
                names.append(token)
                previous = token
            elif token.startswith("…_") and previous is not None:
                previous = previous.rsplit("_", 1)[0] + token[1:]
                names.append(previous)
    if not names:
        raise AssertionError("section 4.7 table has no test names")
    return names


def adopted_names(names: Iterable[str], renames: Mapping[str, str]) -> set[str]:
    return {renames.get(name, name) for name in names}


def base_name(node_id: str) -> str:
    return node_id.split("::")[-1].split("[")[0]


def manifest_names() -> tuple[set[str], set[str]]:
    return {base_name(n) for n in ENVELOPE_NODE_IDS}, set(ENVELOPE_PENDING_NAMES)


def manifest_problems(arch_text: str) -> list[str]:
    frozen = adopted_names(extract_envelope_names(arch_text), E11_RENAMES)
    landed, pending = manifest_names()
    problems = [f"in ARCH, not in manifest: {n}" for n in sorted(frozen - landed - pending)]
    problems += [f"in manifest, not in ARCH: {n}" for n in sorted((landed | pending) - frozen)]
    problems += [f"both landed and pending: {n}" for n in sorted(landed & pending)]
    return problems


def test_envelope_manifest_equals_frozen_arch() -> None:
    data = ARCH_PATH.read_bytes()
    assert hashlib.sha256(data).hexdigest() == ARCH_FREEZE_SHA256
    text = data.decode("utf-8")
    assert len(extract_envelope_names(text)) >= MIN_ENVELOPE_NAMES
    assert manifest_problems(text) == []
    assert set(E11_RENAMES) <= set(extract_envelope_names(text))
    assert not set(E11_RENAMES.values()) & set(extract_envelope_names(text))


_PLANTED_ARCH: Final = (
    "| New test | Pins |\n|---|---|\n"
    "| `test_alpha`; `test_beta_one`; `…_two` | x |\n"
    "| `test_self_heal_cap_survives_process_restart` | y |\n"
)


def test_extraction_expands_an_ellipsis_sibling_and_keeps_order() -> None:
    assert extract_envelope_names(_PLANTED_ARCH) == [
        "test_alpha",
        "test_beta_one",
        "test_beta_two",
        "test_self_heal_cap_survives_process_restart",
    ]


def test_extraction_fails_closed_without_a_table_or_names() -> None:
    with pytest.raises(AssertionError):
        extract_envelope_names("no table here\n")
    with pytest.raises(AssertionError):
        extract_envelope_names("| New test | Pins |\n|---|---|\n| none | x |\n")


def test_the_manifest_comparison_fires_on_an_added_removed_or_renamed_arch_name() -> None:
    real = ARCH_PATH.read_text(encoding="utf-8")
    added = real.replace(
        "| New test | Pins |\n|---|---|\n",
        "| New test | Pins |\n|---|---|\n| `test_planted_new_row` | z |\n",
    )
    assert "in ARCH, not in manifest: test_planted_new_row" in manifest_problems(added)
    removed = real.replace("`test_family_artefact_binding_immutable`", "`no_longer_a_test`")
    assert "in manifest, not in ARCH: test_family_artefact_binding_immutable" in manifest_problems(
        removed
    )
    renamed = real.replace("`test_family_plugin_exact_set`", "`test_family_plugin_set_renamed`")
    problems = manifest_problems(renamed)
    assert "in ARCH, not in manifest: test_family_plugin_set_renamed" in problems
    assert "in manifest, not in ARCH: test_family_plugin_exact_set" in problems


def test_the_e11_renames_are_applied_before_comparison() -> None:
    names = adopted_names(["test_self_heal_cap_survives_process_restart", "test_x"], E11_RENAMES)
    assert names == {E11_RENAMES["test_self_heal_cap_survives_process_restart"], "test_x"}
    assert len(E11_RENAMES) == 3


# ---------------------------------------------------------------------------
# Every manifest node id is collected and unskipped; pending names are not collected
# ---------------------------------------------------------------------------

_SKIP_MARKS: Final = frozenset({"skip", "skipif", "importorskip", "xfail"})


def _mark_calls(expr: ast.AST) -> list[ast.Call | ast.Attribute]:
    """Skip-ish marks anywhere in a decorator, mark list or ``pytestmark`` expression."""
    found: list[ast.Call | ast.Attribute] = []
    for node in ast.walk(expr):
        if isinstance(node, ast.Call):
            names = _SKIP_MARKS
            name = ast.unparse(node.func).split(".")[-1]
        elif isinstance(node, ast.Attribute):
            names = frozenset({"skip", "skipif"})
            name = node.attr
        else:
            continue
        if name in names:
            found.append(node)
    return found


def _skip_problem(mark: ast.Call | ast.Attribute) -> str | None:
    if isinstance(mark, ast.Call) and ast.unparse(mark.func).split(".")[-1] == "xfail":
        if _is_owner_xfail(mark) and _is_strict(mark):
            return None  # an owner-carried stub is unskipped by definition
        return "xfail other than strict OwnerPending"
    return f"skip mark {ast.unparse(mark)}"


def skip_problems(path: str, source: str, base_names: frozenset[str]) -> list[str]:
    """Skip marks or calls on the named test functions, their classes, or the whole module."""
    tree = ast.parse(source, filename=path)
    problems: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets
        ):
            problems += [
                f"{path}: module pytestmark: {p}"
                for m in _mark_calls(node.value)
                if (p := _skip_problem(m))
            ]
        elif isinstance(node, ast.Expr) and any(
            isinstance(n, ast.Call) and ast.unparse(n.func).endswith("importorskip")
            for n in ast.walk(node)
        ):
            problems.append(f"{path}: module-level importorskip")
    for parts, func in _functions(tree.body, ()):
        if func.name not in base_names:
            continue
        where = f"{path}::{'::'.join(parts)}"
        for decorator in func.decorator_list:
            problems += [f"{where}: {p}" for m in _mark_calls(decorator) if (p := _skip_problem(m))]
        for inner in (n for stmt in func.body for n in ast.walk(stmt)):  # body, not decorators
            if (
                isinstance(inner, ast.Call)
                and ast.unparse(inner.func).split(".")[-1] in {"skip", "importorskip", "xfail"}
                and ast.unparse(inner.func).startswith(("pytest.", "unittest."))
            ):
                problems.append(f"{where}: imperative {ast.unparse(inner.func)}()")
    return problems


def _group_by_file(node_ids: Iterable[str]) -> dict[str, set[str]]:
    grouped: dict[str, set[str]] = {}
    for node_id in node_ids:
        file_part = node_id.split("::")[0]
        grouped.setdefault(file_part, set()).add(base_name(node_id))
    return grouped


def collect_node_ids(files: Sequence[str]) -> set[str]:
    """One ``--collect-only`` subprocess over ``files`` in the already-sandboxed interpreter."""
    env = {
        k: v
        for k, v in os.environ.items()
        if k
        not in {
            "PYTEST_ADDOPTS",
            "BREEZY_GATE_COLLECT_ONLY_CLAIM",
            "BREEZY_GATE_COLLECT_ONLY_CONFIRM_FILE",
        }
    }
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-p",
            "no:randomly",
            "-p",
            "no:cacheprovider",
            *files,
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    ids = {
        line.strip()
        for line in proc.stdout.splitlines()
        if re.match(r"\Atests/\S+::\S", line.strip())
    }
    if proc.returncode != 0:
        raise AssertionError(
            f"collect-only exited {proc.returncode}\n{(proc.stdout + proc.stderr)[-1500:]}"
        )
    return ids


def uncollected(manifest_ids: Iterable[str], collected: set[str]) -> list[str]:
    return sorted(set(manifest_ids) - collected)


def defined_test_names() -> set[str]:
    """Every function or method name defined anywhere under tests/ (AST, no import)."""
    names: set[str] = set()
    for path, source in _test_sources():
        for _, func in _functions(ast.parse(source, filename=path).body, ()):
            names.add(func.name)
    return names


def stale_pending(pending: Iterable[str], defined: set[str]) -> list[str]:
    """Pending envelope names that some test under tests/ now defines."""
    return sorted(set(pending) & defined)


def test_every_envelope_node_id_collected_and_unskipped() -> None:
    by_file = _group_by_file(ENVELOPE_NODE_IDS)
    assert len(ENVELOPE_NODE_IDS) >= 19
    sources = dict(_test_sources())
    problems: list[str] = []
    for file_part, names in sorted(by_file.items()):
        assert file_part in sources, f"manifest names a missing file: {file_part}"
        problems += skip_problems(file_part, sources[file_part], frozenset(names))
    assert problems == []
    assert uncollected(ENVELOPE_NODE_IDS, collect_node_ids(sorted(by_file))) == []
    stale = stale_pending(ENVELOPE_PENDING_NAMES, defined_test_names())
    assert stale == [], f"landed tests still listed as pending: {stale}"


def test_a_planted_skip_on_an_envelope_test_is_found_in_every_form() -> None:
    names = frozenset({"test_x"})
    forms = {
        "decorator_skip": "import pytest\n@pytest.mark.skip\ndef test_x(): ...\n",
        "decorator_skip_call": "import pytest\n@pytest.mark.skip(reason='r')\ndef test_x(): ...\n",
        "decorator_skipif": (
            "import pytest\n@pytest.mark.skipif(True, reason='r')\ndef test_x(): ...\n"
        ),
        "plain_xfail": "import pytest\n@pytest.mark.xfail(strict=True)\ndef test_x(): ...\n",
        "xfail_non_strict_owner": (
            "import pytest\n@pytest.mark.xfail(raises=OwnerPending)\ndef test_x(): ...\n"
        ),
        "param_marks_skip": (
            "import pytest\n"
            "@pytest.mark.parametrize('a', [pytest.param(1, marks=pytest.mark.skip)])\n"
            "def test_x(a): ...\n"
        ),
        "imperative_skip": "import pytest\ndef test_x():\n    pytest.skip('no')\n",
        "imperative_importorskip": (
            "import pytest\ndef test_x():\n    pytest.importorskip('numpy')\n"
        ),
        "module_pytestmark": "import pytest\npytestmark = pytest.mark.skip\ndef test_x(): ...\n",
        "module_importorskip": "import pytest\npytest.importorskip('numpy')\ndef test_x(): ...\n",
    }
    missed = [
        name
        for name, source in forms.items()
        if not skip_problems("tests/unit/planted.py", source, names)
    ]
    assert missed == []


def test_unskipped_and_owner_carried_envelope_tests_are_accepted() -> None:
    names = frozenset({"test_x"})
    clean = "def test_x() -> None: ...\n"
    carried = (
        "import pytest\nfrom tests.support.autonomy_owner import OwnerPending\n"
        "@pytest.mark.xfail(strict=True, raises=OwnerPending)\ndef test_x() -> None: ...\n"
    )
    other_test_skipped = (
        "import pytest\n@pytest.mark.skip\ndef test_other(): ...\ndef test_x(): ...\n"
    )
    for source in (clean, carried, other_test_skipped):
        assert skip_problems("tests/unit/planted.py", source, names) == []


def test_an_envelope_id_that_is_not_collected_is_reported() -> None:
    manifest = {"tests/unit/a.py::test_x", "tests/unit/a.py::test_y[p]"}
    assert uncollected(manifest, {"tests/unit/a.py::test_x"}) == ["tests/unit/a.py::test_y[p]"]
    assert uncollected(manifest, manifest) == []


def test_a_deselected_or_misnamed_envelope_id_is_not_collected_for_real() -> None:
    real = sorted(ENVELOPE_NODE_IDS)[:1]
    collected = collect_node_ids([real[0].split("::")[0]])
    assert uncollected(real, collected) == []
    assert uncollected([real[0] + "_typo"], collected) == [real[0] + "_typo"]


def test_a_pending_name_that_is_now_defined_is_detected() -> None:
    defined = defined_test_names()
    assert "test_autonomy_files_have_one_writer" in defined
    assert stale_pending({"test_autonomy_files_have_one_writer", "test_nowhere"}, defined) == [
        "test_autonomy_files_have_one_writer"
    ]
    assert stale_pending({"test_nowhere"}, defined) == []


# ---------------------------------------------------------------------------
# Widening kinds enabled only when their placeholders are cleared
# ---------------------------------------------------------------------------


def enabled_kinds_still_blocked(enabled: Iterable[str], rows: Iterable[OwnerRow]) -> list[str]:
    """``<kind> blocked by <node id>`` for each enabled kind a ledger row still blocks."""
    enabled_set = set(enabled)
    return sorted(
        f"{kind} blocked by {row.node_id}"
        for row in rows
        for kind in sorted(row.blocks_kinds & enabled_set)
    )


def test_widening_kind_enabled_only_when_its_placeholders_cleared() -> None:
    assert enabled_kinds_still_blocked(pins.ENABLED_WIDENING_KINDS, OWNER_PLACEHOLDERS) == []
    assert pins.ENABLED_WIDENING_KINDS <= FLOOR_KIND_VOCABULARY


def test_an_enabled_kind_that_a_row_still_blocks_is_reported() -> None:
    rows = [_ROW._replace(blocks_kinds=frozenset({"PROMOTE", "RESUME"}))]
    assert enabled_kinds_still_blocked({"RESUME"}, rows) == [f"RESUME blocked by {_ROW.node_id}"]
    assert enabled_kinds_still_blocked({"RESUME", "PROMOTE"}, rows) == [
        f"PROMOTE blocked by {_ROW.node_id}",
        f"RESUME blocked by {_ROW.node_id}",
    ]


def test_a_kind_blocked_only_while_it_is_disabled_is_accepted() -> None:
    rows = [_ROW._replace(blocks_kinds=frozenset({"PROMOTE"}))]
    assert enabled_kinds_still_blocked({"RESUME"}, rows) == []
    assert enabled_kinds_still_blocked(frozenset(), rows) == []


# ---------------------------------------------------------------------------
# blocks_kinds never below the frozen floor
# ---------------------------------------------------------------------------


def floor_violations(rows: Iterable[OwnerRow], floor: Mapping[str, frozenset[str]]) -> list[str]:
    violations: list[str] = []
    for row in rows:
        key = row.node_id.split("::", 1)[1] if "::" in row.node_id else row.node_id
        required = floor.get(key)
        if required is not None and not required <= row.blocks_kinds:
            missing = ", ".join(sorted(required - row.blocks_kinds))
            violations.append(f"{row.node_id} does not block {missing}")
    return violations


def test_blocks_kinds_never_below_floor() -> None:
    assert floor_violations(OWNER_PLACEHOLDERS, BLOCKS_KINDS_FLOOR) == []
    assert len(BLOCKS_KINDS_FLOOR) >= 50
    assert all(kinds and kinds <= FLOOR_KIND_VOCABULARY for kinds in BLOCKS_KINDS_FLOOR.values())
    assert BLOCKS_KINDS_FLOOR["test_resume_admission_reads_policy_block_bounds"] == {"RESUME"}
    assert BLOCKS_KINDS_FLOOR["test_repeat_supersede_same_family_is_not_replay[store]"] == {
        "SUPERSEDE",
        "PROMOTE",
    }


def test_a_row_blocking_fewer_kinds_than_the_floor_is_reported() -> None:
    row = _ROW._replace(
        node_id="tests/unit/test_autonomy_cross_area.py::test_repeat_supersede_same_family_is_not_replay[store]",
        blocks_kinds=frozenset({"SUPERSEDE"}),
    )
    assert floor_violations([row], BLOCKS_KINDS_FLOOR) == [f"{row.node_id} does not block PROMOTE"]
    emptied = row._replace(blocks_kinds=frozenset())
    assert floor_violations([emptied], BLOCKS_KINDS_FLOOR) == [
        f"{row.node_id} does not block PROMOTE, SUPERSEDE"
    ]


def test_a_row_at_or_above_the_floor_and_an_unfloored_row_are_accepted() -> None:
    at_floor = _ROW._replace(
        node_id="tests/unit/test_autonomy_cross_area.py::test_resume_admission_reads_policy_block_bounds",
        blocks_kinds=frozenset({"RESUME"}),
    )
    above = at_floor._replace(blocks_kinds=frozenset({"RESUME", "PROMOTE"}))
    unfloored = _ROW._replace(
        node_id="tests/unit/x.py::test_not_in_the_floor", blocks_kinds=frozenset()
    )
    assert floor_violations([at_floor, above, unfloored], BLOCKS_KINDS_FLOOR) == []


def test_the_floor_cites_only_known_kinds_and_is_immutable() -> None:
    with pytest.raises(TypeError):
        BLOCKS_KINDS_FLOOR["x"] = frozenset({"PROMOTE"})  # type: ignore[index]
    assert {
        "PROMOTE",
        "RESUME",
        "ROLLBACK",
        "ACTIVATE",
        "ROOT_ADMIT",
        "SUPERSEDE",
        "HWM_RESET",
    } <= (FLOOR_KIND_VOCABULARY)
