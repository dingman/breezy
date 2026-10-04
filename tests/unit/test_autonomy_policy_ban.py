"""ARCH-0 seam 6c: the stage-policy construction ban, one-home rule and acyclic graph (AC 15).

Three contract tests judge the real tree; each has planted controls so a scan that walks nothing, or
that misses a form, fails. The scans are ``tests/support/autonomy_policy_scan.py``.

The ban is blanket (ruling A5-R9): an AST cannot see argument types. A consumer that needs
``dataclasses.replace`` or ``copy.*`` on its own records adds one reviewed literal row to
``POLICY_BAN_EXEMPTIONS`` in its own commit; no row may cover a ``StagePolicy`` construction.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from graphlib import CycleError, TopologicalSorter
from pathlib import Path
from typing import Final, NamedTuple

import pytest

from tests.support.autonomy_policy_scan import (
    POLICY_MODULES,
    PRIVATE_SEAMS,
    find_policy_violations,
    find_predicate_reads,
    in_construction_scope,
)
from tests.support.autonomy_scan import (
    Finding,
    autonomy_source_files,
    imported_modules,
    package_of,
    relative_path,
    scan_files,
)
from tests.support.entry_points import REPO_ROOT, SRC_DIR

AUTONOMY: Final = "src/breezy/persistence/autonomy"
AUTONOMY_PACKAGE: Final = "breezy.persistence.autonomy"
CONSUMER: Final = f"{AUTONOMY}/registry_store.py"
OUTSIDE: Final = "src/breezy/strategy/some_module.py"
MIN_SRC_FILES: Final = 250  # all of src/breezy (273 at seam 6c)
MIN_AUTONOMY_FILES: Final = 20


class ExemptionRow(NamedTuple):
    """A reviewed ``(module, lineno-free call description, reason)`` row (ruling A5-R9)."""

    module: str
    call: str
    reason: str


#: A consumer adds its row in its own commit (ERRATA (b) items 42-44). The one row at 6c is a
#: core module that predates the ban; it is flagged to the coordinator as a deviation.
POLICY_BAN_EXEMPTIONS: Final[tuple[ExemptionRow, ...]] = (
    ExemptionRow(
        f"{AUTONOMY}/drill_marker.py",
        "dataclasses.replace",
        "read_marker_at stamps raw_sha256 on the DrillMarker it just parsed (seam 5b); the "
        "object is a DrillMarker, never a StagePolicy",
    ),
)


class AllowRow(NamedTuple):
    """A reviewed ``(module, finding detail, reason)`` row for a rule (i) false positive."""

    module: str
    detail: str
    reason: str


SEAM_ALLOWLIST: Final[tuple[AllowRow, ...]] = (
    AllowRow(
        "src/breezy/strategy/forecast_quantile_ladder/composition.py",
        "_resolve",
        "a closure local to composition's own lazy tuple, unrelated to resolver._resolve",
    ),
    AllowRow(
        "src/breezy/analysis/promotion_criteria.py",
        "subscript-write:sys.modules",
        "registers the script it loads by file path under a private name; the key is a local "
        "constant naming scripts/analysis/structural_dead_stop.py, never a policy module",
    ),
)


def _pairs(rows: tuple[ExemptionRow, ...] | tuple[AllowRow, ...]) -> frozenset[tuple[str, str]]:
    return frozenset((row[0], row[1]) for row in rows)


def _scan(
    path: str,
    source: str,
    *,
    exemptions: tuple[ExemptionRow, ...] = POLICY_BAN_EXEMPTIONS,
    seams: tuple[AllowRow, ...] = SEAM_ALLOWLIST,
) -> list[Finding]:
    return find_policy_violations(
        path, source, exemptions=_pairs(exemptions), allowlist=_pairs(seams)
    )


def _src_files() -> list[Path]:
    return sorted({*(SRC_DIR / "breezy").rglob("*.py"), *autonomy_source_files()})


# ---------------------------------------------------------------------------
# Planted forms
# ---------------------------------------------------------------------------

_CONSTRUCTION: Final[dict[str, str]] = {
    "stage_policy_call": (
        "from breezy.persistence.autonomy.schemas import StagePolicy\n"
        "def f():\n    return StagePolicy(frozenset(), frozenset())\n"
    ),
    "aliased_import": (
        "from breezy.persistence.autonomy.schemas import StagePolicy as SP\n"
        "def f():\n    return SP(frozenset(), frozenset())\n"
    ),
    "assignment_alias": (
        "from breezy.persistence.autonomy.schemas import StagePolicy\n"
        "SP = StagePolicy\nQ = SP\ndef f():\n    return Q(frozenset(), frozenset())\n"
    ),
    "module_alias": (
        "import breezy.persistence.autonomy.schemas as s\n"
        "def f():\n    return s.StagePolicy(frozenset(), frozenset())\n"
    ),
    "relative_import": (
        "from .schemas import StagePolicy\n"
        "def f():\n    return StagePolicy(frozenset(), frozenset())\n"
    ),
    "relative_module": (
        "from . import schemas\n"
        "def f():\n    return schemas.StagePolicy(frozenset(), frozenset())\n"
    ),
    "new": "from .schemas import StagePolicy\nx = StagePolicy.__new__(StagePolicy)\n",
    "dataclasses_replace": (
        "import dataclasses\ndef f(x):\n    return dataclasses.replace(x, a=1)\n"
    ),
    "replace_aliased": "from dataclasses import replace as r\ndef f(x):\n    return r(x, a=1)\n",
    "dataclasses_module_alias": "import dataclasses as dc\nf = dc.replace\n",
    "copy_copy": "import copy\ndef f(x):\n    return copy.copy(x)\n",
    "copy_deepcopy": "import copy\ndef f(x):\n    return copy.deepcopy(x)\n",
    "copy_replace": "import copy\ndef f(x):\n    return copy.replace(x, a=1)\n",
    "copy_from_import": "from copy import deepcopy as dup\ndef f(x):\n    return dup(x)\n",
    "dunder_class_call": "def f(x):\n    return x.__class__(1, 2)\n",
    "type_call": "def f(x):\n    return type(x)(1, 2)\n",
    "object_new": "def f(x):\n    return object.__new__(type(x))\n",
    "copy_dunder": "def f(x):\n    return x.__copy__()\n",
    "replace_dunder": "def f(x):\n    return x.__replace__(a=1)\n",
    "pickle_round_trip": "import pickle\ndef f(x):\n    return pickle.loads(pickle.dumps(x))\n",
    "importlib_import_module": (
        "import importlib\n"
        "m = importlib.import_module('breezy.persistence.autonomy.schemas')\n"
        "x = m.StagePolicy(frozenset(), frozenset())\n"
    ),
    "importlib_from_import": "from importlib import import_module as im\nm = im('os')\n",
    "dunder_import": "m = __import__('breezy.persistence.autonomy.schemas')\n",
    "getattr_literal": "import dataclasses\nf = getattr(dataclasses, 'replace')\n",
    "getattr_stage_policy": (
        "def f(m):\n    return getattr(m, 'StagePolicy')(frozenset(), frozenset())\n"
    ),
}

_WRITES: Final[dict[str, str]] = {
    "assign_module_attr": (
        "from breezy.persistence.autonomy import pins\npins.ENABLED_WIDENING_KINDS = frozenset()\n"
    ),
    "assign_nested_attr": (
        "import breezy.persistence.autonomy.stage_policy as sp\n"
        "sp.STAGE.enabled_widening_kinds = 1\n"
    ),
    "augassign": "from breezy.persistence.autonomy import pins\npins.X += 1\n",
    "annassign": "from breezy.persistence.autonomy import transitions\ntransitions.X: int = 1\n",
    "delete": "from breezy.persistence.autonomy import pins\ndel pins.X\n",
    "subscript_write": (
        "from breezy.persistence.autonomy import transitions\ntransitions.ALLOWED['k'] = 1\n"
    ),
    "assign_via_alias": "from breezy.persistence.autonomy import pins\np = pins\np.X = 1\n",
    "assign_family_manifest": "from breezy.persistence import family_manifest as fm\nfm.X = 1\n",
    "assign_live_orders_gate": (
        "from breezy.persistence import live_orders_gate\nlive_orders_gate.X = 1\n"
    ),
    "setattr": "from breezy.persistence.autonomy import pins\nsetattr(pins, 'X', 1)\n",
    "delattr": "from breezy.persistence.autonomy import pins\ndelattr(pins, 'X')\n",
    "object_setattr": (
        "from breezy.persistence.autonomy.stage_policy import STAGE\n"
        "object.__setattr__(STAGE, 'enabled_widening_kinds', frozenset())\n"
    ),
    "dict_write": "from breezy.persistence.autonomy import pins\npins.__dict__['X'] = 1\n",
    "dict_update": "from breezy.persistence.autonomy import pins\npins.__dict__.update(X=1)\n",
    "vars_call": "from breezy.persistence.autonomy import pins\nvars(pins)['X'] = 1\n",
    "globals_write": "globals()['ENABLED_WIDENING_KINDS'] = frozenset()\n",
    "sys_modules_write": "import sys\nsys.modules['breezy.persistence.autonomy.pins'] = object()\n",
    "reload": (
        "import importlib\nfrom breezy.persistence.autonomy import pins\nimportlib.reload(pins)\n"
    ),
    "reload_bare": "from importlib import reload\nreload(object())\n",
    "mock_patch": (
        "from unittest import mock\n"
        "mock.patch('breezy.persistence.autonomy.pins.ENABLED_WIDENING_KINDS', frozenset())\n"
    ),
    "mock_patch_imported": "from unittest.mock import patch\n",
    "monkeypatch": "def f(monkeypatch):\n    monkeypatch.setattr('a.pins.X', 1)\n",
    "rebind_imported_name": (
        "from breezy.persistence.autonomy.pins import ENABLED_WIDENING_KINDS\n"
        "ENABLED_WIDENING_KINDS = frozenset()\n"
    ),
    "rebind_imported_module": ("from breezy.persistence.autonomy import pins\npins = object()\n"),
    "rebind_in_function": (
        "from breezy.persistence.autonomy.pins import ENABLED_WIDENING_KINDS as E\n"
        "def f():\n    global E\n    E = frozenset()\n"
    ),
    "import_module_policy": (
        "import importlib\nm = importlib.import_module('breezy.persistence.autonomy.pins')\n"
    ),
}

_SEAMS: Final[dict[str, str]] = {
    "append": "def f(store):\n    return store._append([])\n",
    "append_import": "from breezy.persistence.autonomy.registry_store import _append\n",
    "resolve": "def f(r):\n    return r._resolve()\n",
    "replay_full": (
        "from breezy.persistence.autonomy.replay import _replay_full\nx = _replay_full\n"
    ),
    "lineage": "def f(g):\n    return g._lineage_policy_authorized()\n",
    "ruling": "def f(g):\n    return g._verify_ruling_file()\n",
    "build_import": "from breezy.persistence.autonomy.stage_policy import _build\n",
    "build_attr": "import breezy.persistence.autonomy.stage_policy as sp\nx = sp._build\n",
    "string_lookup": "def f(m):\n    return getattr(m, '_append')\n",
}

_CLEAN: Final[dict[str, str]] = {
    "reads_stage": (
        "from breezy.persistence.autonomy.stage_policy import STAGE\n"
        "def f(rows):\n    return STAGE\n"
    ),
    "reads_pins": "from breezy.persistence.autonomy import pins\nx = pins.ENABLED_WIDENING_KINDS\n",
    "annotation_only": (
        "from breezy.persistence.autonomy.schemas import StagePolicy\n"
        "def f(stage: StagePolicy) -> StagePolicy:\n    return stage\n"
    ),
    "class_name_read": "def f(x):\n    return x.__class__.__name__\n",
    "type_one_arg": "def f(x):\n    return type(x)\n",
    "type_three_arg": "def f():\n    return type('T', (), {})\n",
    "unrelated_replace": "def f(s):\n    return s.replace('a', 'b')\n",
    "local_names": "def f():\n    copy = 1\n    return copy\n",
}


def _flagged(cases: Mapping[str, str], path: str, rule: str) -> list[str]:
    return [n for n, s in cases.items() if not [f for f in _scan(path, s) if f.rule == rule]]


def test_construction_scan_fires_on_every_planted_form() -> None:
    assert _flagged(_CONSTRUCTION, CONSUMER, "policy-construction") == []


def test_write_scan_fires_on_every_planted_form_in_any_src_module() -> None:
    assert _flagged(_WRITES, OUTSIDE, "policy-write") == []
    assert _flagged(_WRITES, CONSUMER, "policy-write") == []


def test_private_seam_scan_fires_on_every_planted_form_outside_the_defining_module() -> None:
    assert _flagged(_SEAMS, OUTSIDE, "policy-private-seam") == []


def test_clean_sources_are_not_flagged() -> None:
    for name, source in _CLEAN.items():
        assert _scan(CONSUMER, source) == [], name


@pytest.mark.parametrize("name", sorted(PRIVATE_SEAMS))
def test_a_seam_is_free_inside_its_defining_module_only(name: str) -> None:
    stem = PRIVATE_SEAMS[name]
    source = f"def {name}():\n    return 1\n\nx = {name}()\n"
    assert _scan(f"src/breezy/persistence/autonomy/{stem}.py", source) == []
    assert [f.detail for f in _scan(OUTSIDE, source)] == [name]


def test_the_stage_policy_builder_is_free_only_inside_stage_policy() -> None:
    source = "def _build():\n    return 1\nSTAGE = _build()\nx = stage_policy._build\n"
    assert _scan(f"{AUTONOMY}/stage_policy.py", source) == []
    assert _scan(OUTSIDE, source)


# ---------------------------------------------------------------------------
# Scope (rule ii) and exemption rows
# ---------------------------------------------------------------------------


def test_construction_ban_scope_is_every_autonomy_package_except_stage_policy() -> None:
    assert in_construction_scope(CONSUMER)
    assert in_construction_scope("src/breezy/analysis/autonomy_refit/x.py")
    assert in_construction_scope("src/breezy/strategy/autonomy_capture/deep/x.py")
    assert in_construction_scope("src/breezy/runtime/autonomy_watch.py")
    assert in_construction_scope("scripts/run_autonomy_tick.py")
    assert not in_construction_scope(f"{AUTONOMY}/stage_policy.py")
    assert not in_construction_scope(OUTSIDE)
    assert not in_construction_scope("src/breezy/persistence/live_orders_gate.py")


def test_scope_follows_the_judged_autonomy_file_predicate(tmp_path: Path) -> None:
    src = tmp_path / "src" / "breezy"
    for rel in (
        "strategy/autonomy_capture/w.py",
        "analysis/autonomy_refit/w.py",
        "x/autonomy_y.py",
    ):
        path = src / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("import copy\nx = copy.copy\n", "utf-8")
    judged = autonomy_source_files(src, tmp_path / "scripts")
    assert len(judged) == 3
    for path in judged:
        relative = "src/breezy/" + path.relative_to(src).as_posix()
        assert in_construction_scope(relative)


def test_the_ban_does_not_apply_to_construction_outside_autonomy_packages() -> None:
    source = "import copy\nimport dataclasses\nx = copy.copy\ny = dataclasses.replace\n"
    assert [f for f in _scan(OUTSIDE, source) if f.rule == "policy-construction"] == []


_PLANTED_EXEMPT_PATH: Final = "src/breezy/analysis/autonomy_refit/rows.py"
_PLANTED_EXEMPT_SOURCE: Final = (
    "import dataclasses\ndef f(row):\n    return dataclasses.replace(row, split='v5_fit_slice')\n"
)
_PLANTED_ROW: Final = ExemptionRow(
    _PLANTED_EXEMPT_PATH, "dataclasses.replace", "planted control for the exemption mechanism"
)


def test_an_exemption_row_exempts_exactly_its_module_and_call() -> None:
    assert _scan(_PLANTED_EXEMPT_PATH, _PLANTED_EXEMPT_SOURCE)  # blanket without the row
    assert _scan(_PLANTED_EXEMPT_PATH, _PLANTED_EXEMPT_SOURCE, exemptions=(_PLANTED_ROW,)) == []
    # another module, another call, and a second call kind in the same module stay refused
    other = "src/breezy/analysis/autonomy_refit/other.py"
    assert _scan(other, _PLANTED_EXEMPT_SOURCE, exemptions=(_PLANTED_ROW,))
    copied = _PLANTED_EXEMPT_SOURCE + "import copy\ng = copy.deepcopy\n"
    left = _scan(_PLANTED_EXEMPT_PATH, copied, exemptions=(_PLANTED_ROW,))
    assert [f.detail for f in left] == ["copy.deepcopy"]


def test_an_exemption_row_never_exempts_a_stage_policy_construction() -> None:
    source = (
        "from breezy.persistence.autonomy.schemas import StagePolicy\n"
        "x = StagePolicy(frozenset(), frozenset())\n"
    )
    row = ExemptionRow(_PLANTED_EXEMPT_PATH, "StagePolicy(...)", "must not be honoured")
    assert _scan(_PLANTED_EXEMPT_PATH, source, exemptions=(row,))


def test_an_exemption_row_never_exempts_a_write_or_a_seam_reference() -> None:
    write = "from breezy.persistence.autonomy import pins\npins.X = 1\n"
    for call in ("assign:breezy.persistence.autonomy.pins.X", "policy-write"):
        row = ExemptionRow(_PLANTED_EXEMPT_PATH, call, "must not be honoured")
        assert _scan(_PLANTED_EXEMPT_PATH, write, exemptions=(row,))
    seam = "def f(s):\n    return s._append()\n"
    assert _scan(
        _PLANTED_EXEMPT_PATH, seam, exemptions=(ExemptionRow(_PLANTED_EXEMPT_PATH, "_append", "x"),)
    )


def test_a_allowlist_row_covers_only_its_module_and_name() -> None:
    path = "src/breezy/strategy/composition.py"
    source = "def f():\n    def _resolve():\n        return 1\n    return _resolve\n"
    row = AllowRow(path, "_resolve", "planted control")
    assert _scan(path, source)
    assert _scan(path, source, seams=(row,)) == []
    assert _scan("src/breezy/strategy/other.py", source, seams=(row,))
    assert _scan(path, "x = g._append\n", seams=(row,))


def test_every_exemption_and_allowlist_row_is_reasoned_literal_and_live() -> None:
    for exemption in POLICY_BAN_EXEMPTIONS:
        assert exemption.reason.strip()
        assert "StagePolicy" not in exemption.call
        source = (REPO_ROOT / exemption.module).read_text(encoding="utf-8")
        details = {f.detail for f in _scan(exemption.module, source, exemptions=())}
        assert exemption.call in details, f"stale exemption row {exemption}"
    for seam in SEAM_ALLOWLIST:
        assert seam.reason.strip()
        source = (REPO_ROOT / seam.module).read_text(encoding="utf-8")
        assert seam.detail in {f.detail for f in _scan(seam.module, source, seams=())}


# ---------------------------------------------------------------------------
# The real tree
# ---------------------------------------------------------------------------


def test_autonomy_policy_not_mutable_from_src() -> None:
    files = _src_files()
    assert len(files) >= MIN_SRC_FILES
    assert len([p for p in files if in_construction_scope(relative_path(p))]) >= MIN_AUTONOMY_FILES

    def scan(path: str, source: str) -> list[Finding]:
        return _scan(path, source)

    findings = scan_files(files, scan)
    assert findings == [], "\n".join(f"{f.path}:{f.lineno} {f.rule} {f.detail}" for f in findings)


# ---------------------------------------------------------------------------
# One home for the admissibility predicate
# ---------------------------------------------------------------------------

_SCHEMAS: Final = f"{AUTONOMY}/schemas.py"
_PINS: Final = f"{AUTONOMY}/pins.py"
_TRANSITIONS: Final = f"{AUTONOMY}/transitions.py"
_STAGE_POLICY: Final = f"{AUTONOMY}/stage_policy.py"
#: path -> enclosing scope ("*" = any) -> names that scope may reference. Nothing else in ``src``
#: may name either stage kind set; ``rows_admissible`` alone compares them against rows.
PREDICATE_HOMES: Final[dict[str, dict[str, frozenset[str]]]] = {
    _SCHEMAS: {"*": frozenset({"enabled_widening_kinds", "admission_implemented"})},
    _PINS: {"*": frozenset({"ENABLED_WIDENING_KINDS"})},
    _TRANSITIONS: {
        "": frozenset({"_ADMISSION_IMPLEMENTED"}),
        "rows_admissible": frozenset({"enabled_widening_kinds", "admission_implemented"}),
    },
    _STAGE_POLICY: {
        "_build": frozenset(
            {
                "enabled_widening_kinds",
                "admission_implemented",
                "ENABLED_WIDENING_KINDS",
                "_ADMISSION_IMPLEMENTED",
            }
        ),
    },
}

_PLANTED_READS: Final[dict[str, tuple[str, str]]] = {
    "store_reads_enabled": (
        CONSUMER,
        "def f(stage, row):\n    return row.kind in stage.enabled_widening_kinds\n",
    ),
    "store_reads_implemented": (
        CONSUMER,
        "def f(stage, row):\n    return row.kind in stage.admission_implemented\n",
    ),
    "resolver_reads_pins": (
        f"{AUTONOMY}/resolver.py",
        "from breezy.persistence.autonomy import pins\nx = pins.ENABLED_WIDENING_KINDS\n",
    ),
    "private_set_read": (
        CONSUMER,
        (
            "from breezy.persistence.autonomy import transitions\n"
            "x = transitions._ADMISSION_IMPLEMENTED\n"
        ),
    ),
    "import_name": (
        CONSUMER,
        "from breezy.persistence.autonomy.pins import ENABLED_WIDENING_KINDS\n",
    ),
    "string_lookup": (CONSUMER, "def f(s):\n    return getattr(s, 'enabled_widening_kinds')\n"),
    "keyword_argument": (
        CONSUMER,
        "def f(c):\n    return c(enabled_widening_kinds=frozenset())\n",
    ),
    "transitions_second_function": (
        _TRANSITIONS,
        "def other(stage):\n    return stage.admission_implemented\n",
    ),
    "transitions_module_level_read": (_TRANSITIONS, "x = stage.enabled_widening_kinds\n"),
    "stage_policy_outside_build": (_STAGE_POLICY, "x = _ADMISSION_IMPLEMENTED\n"),
}


def _reads(path: str, source: str) -> list[Finding]:
    return find_predicate_reads(path, source, PREDICATE_HOMES)


def test_admissibility_predicate_has_one_home() -> None:
    files = _src_files()
    assert len(files) >= MIN_SRC_FILES
    findings = scan_files(files, _reads)
    assert findings == [], "\n".join(
        f"{f.path}:{f.lineno} {f.detail} in {f.scope}" for f in findings
    )
    # the homes must really be where the table says (a table that names nothing proves nothing)
    for home in PREDICATE_HOMES:
        assert (REPO_ROOT / home).is_file(), home
        assert find_predicate_reads(home, (REPO_ROOT / home).read_text("utf-8"), {}), home


def test_predicate_scan_fires_on_every_planted_read() -> None:
    missed = [name for name, (path, source) in _PLANTED_READS.items() if not _reads(path, source)]
    assert missed == []


def test_predicate_scan_accepts_the_reviewed_shape_of_each_home() -> None:
    assert (
        _reads(
            _TRANSITIONS,
            "_ADMISSION_IMPLEMENTED = frozenset()\n"
            "def rows_admissible(rows, *, stage):\n"
            "    return (frozenset(stage.enabled_widening_kinds),\n"
            "            frozenset(stage.admission_implemented))\n",
        )
        == []
    )
    assert _reads(_PINS, "ENABLED_WIDENING_KINDS = frozenset()\n") == []
    assert (
        _reads(
            _STAGE_POLICY,
            "def _build():\n    return c(enabled_widening_kinds=pins.ENABLED_WIDENING_KINDS)\n",
        )
        == []
    )


def test_predicate_scan_ignores_unrelated_code() -> None:
    assert _reads(CONSUMER, "def f(stage):\n    return stage.enabled\n") == []


def test_the_store_and_resolver_call_the_shared_predicate_not_a_copy() -> None:
    """Both consumers land later; until then no ``src`` module may carry a second comparison."""
    comparing = [
        relative_path(p)
        for p in _src_files()
        if "rows_admissible" not in p.read_text("utf-8")
        and any(
            n in p.read_text("utf-8") for n in ("admission_pending", "widening_kind_not_enabled")
        )
        and relative_path(p) != _SCHEMAS
    ]
    assert comparing == []


# ---------------------------------------------------------------------------
# Acyclic package import graph
# ---------------------------------------------------------------------------


def _autonomy_graph(modules: Mapping[str, str]) -> dict[str, set[str]]:
    """Module -> the autonomy modules it imports (any import, at any depth)."""
    graph: dict[str, set[str]] = {name: set() for name in modules}
    for name, source in modules.items():
        package = package_of(f"src/{name.replace('.', '/')}.py")
        for target, _ in imported_modules(ast.parse(source), package=package):
            if target in graph and target != name:
                graph[name].add(target)
    return graph


def _cycle(graph: Mapping[str, set[str]]) -> list[str] | None:
    try:
        tuple(TopologicalSorter(graph).static_order())
    except CycleError as error:
        return list(error.args[1])
    return None


def _real_modules() -> dict[str, str]:
    root = SRC_DIR / "breezy" / "persistence" / "autonomy"
    return {
        f"{AUTONOMY_PACKAGE}.{p.stem}": p.read_text(encoding="utf-8")
        for p in sorted(root.glob("*.py"))
        if p.stem != "__init__"
    }


def test_autonomy_package_import_graph_is_acyclic() -> None:
    graph = _autonomy_graph(_real_modules())
    assert len(graph) >= 20
    assert _cycle(graph) is None, _cycle(graph)


def test_import_order_is_schemas_then_transitions_then_stage_policy() -> None:
    graph = _autonomy_graph(_real_modules())
    pre = f"{AUTONOMY_PACKAGE}."
    stage, trans, schemas, pins = (
        pre + n for n in ("stage_policy", "transitions", "schemas", "pins")
    )
    assert {trans, pins, schemas} <= graph[stage]
    assert stage not in graph[trans]
    assert stage not in graph[schemas]
    assert trans not in graph[schemas]
    assert not any(
        stage in deps for name, deps in graph.items() if name != stage
    )  # only 6e+ import it later


def test_cycle_detector_sees_a_planted_cycle_and_a_planted_back_edge() -> None:
    pre = f"{AUTONOMY_PACKAGE}."
    cyc = _autonomy_graph(
        {
            pre + "a": f"from {AUTONOMY_PACKAGE} import b\n",
            pre + "b": f"import {AUTONOMY_PACKAGE}.a\n",
        }
    )
    assert _cycle(cyc) is not None
    real = _real_modules()
    real[pre + "transitions"] += f"\nfrom {AUTONOMY_PACKAGE}.stage_policy import STAGE\n"
    assert _cycle(_autonomy_graph(real)) is not None
    relative = dict(_real_modules())
    relative[pre + "schemas"] += "\nfrom . import stage_policy\n"
    assert _cycle(_autonomy_graph(relative)) is not None
    assert _cycle(_autonomy_graph({pre + "a": "x = 1\n", pre + "b": f"import {pre}a\n"})) is None


def test_policy_modules_set_is_the_five_named_by_the_plan() -> None:
    assert POLICY_MODULES == {
        "pins",
        "stage_policy",
        "transitions",
        "live_orders_gate",
        "family_manifest",
    }


def test_dynamic_import_is_banned_only_inside_autonomy_scope() -> None:
    source = "import importlib.metadata\nx = importlib.metadata.version('breezy')\n"
    assert _scan(OUTSIDE, source) == []
    assert [f.rule for f in _scan(CONSUMER, source)] == ["policy-construction"]
