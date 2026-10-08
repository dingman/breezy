"""AUT-6 read-only closure lint, WP1 slice (plan r15 §3.1; E-7 rules 3 and 4; E-7a rule 4).

This reuses ``tests/support/capture_closure_lint.py`` (AUT-1's allowlist lint) with AUT-6's rows.
The single write scope of every WP1 entry point (redeliver, check, node sinks) is
``evidence/alerts/**``, and only ``alert_outbox`` holds the write sites that reach it. Every later
AUT-6 work package adds its entry point and its module rows here. The lint is a defence in depth:
each wrapped unit's bwrap row is the control.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

import pytest

from breezy.persistence.autonomy import detector_catalog
from breezy.persistence.autonomy.detector_catalog import (
    AUT6_LINT_MIN_JUDGED_SITES,
    AUT6_PURE_BUILTINS,
    AUT6_READ_ALLOWLIST,
    AUT6_ROLLBACK_JOURNAL_STORES,
    AUT6_SELF_PROBE_PATHS,
    AUT6_WRITE_AUTHORITY,
)
from tests.support.aut6_closure_lint import (
    read_allowlist_findings,
    sqlite_findings,
    wal_in_place_findings,
)
from tests.support.autonomy_scan import Finding
from tests.support.capture_closure_lint import AuthorityRow, lint_files, lint_source, module_of
from tests.support.entry_points import DEPLOY_SYSTEMD_DIR, SRC_DIR

_RUNTIME: Final = SRC_DIR / "breezy" / "runtime"
_ALERTS_WRITES: Final = "evidence/alerts/**"
_OUTBOX: Final = "breezy.runtime.alert_outbox"

#: Function scopes of ``alert_outbox`` that hold a filesystem write site. A new write function
#: needs a reviewed entry here. Every entry point below has ``evidence/alerts/**`` authority.
_OUTBOX_WRITE_SCOPES: Final[tuple[str, ...]] = (
    "_mkdir",
    "_publish",
    "AlertOutbox.claim",
    "AlertOutbox.restamp",
    "AlertOutbox.complete",
    "AlertOutbox.quarantine",
)

#: The WP1 modules the closure lint judges, with the minimum call sites each must hold.
AUT6_WP1_ROWS: Final[tuple[AuthorityRow, ...]] = (
    AuthorityRow(_OUTBOX, writes=_OUTBOX_WRITE_SCOPES, min_calls=50),
    AuthorityRow("breezy.runtime.alert_proof", min_calls=45),
    AuthorityRow("breezy.runtime.alert_drain", min_calls=32),
    AuthorityRow("breezy.runtime.alert_delivery", min_calls=12),
    AuthorityRow("breezy.runtime.alert_redeliver_cli", min_calls=22),
    AuthorityRow("breezy.runtime.check_alerts_cli", min_calls=24),
    AuthorityRow("breezy.persistence.autonomy.detector_catalog", min_calls=8),
)

#: Entry point (a key of ``AUT6_WRITE_AUTHORITY``) -> the WP1 modules in its closure.
AUT6_ENTRY_MODULES: Final[dict[str, tuple[str, ...]]] = {
    "breezy-autonomy-alert-redeliver": (
        "breezy.runtime.alert_redeliver_cli",
        "breezy.runtime.alert_delivery",
        "breezy.runtime.alert_drain",
        "breezy.runtime.alert_proof",
        _OUTBOX,
    ),
    "breezy-check-alerts": (
        "breezy.runtime.check_alerts_cli",
        "breezy.runtime.alert_delivery",
        "breezy.runtime.alert_proof",
        _OUTBOX,
    ),
    "node-sinks": (
        "breezy.runtime.alert_delivery",
        "breezy.runtime.alert_proof",
        _OUTBOX,
    ),
}


def _path_of(module: str) -> Path:
    return SRC_DIR.joinpath(*module.split(".")).with_suffix(".py")


def _findings(files: list[Path]) -> list[Finding]:
    return lint_files(files, AUT6_WP1_ROWS)


def _judged_files() -> list[Path]:
    return [_path_of(row.module) for row in AUT6_WP1_ROWS]


def test_aut6_closures_read_only_outside_one_writer_rows() -> None:
    files = _judged_files()
    assert all(path.is_file() for path in files)
    found = _findings(files)
    assert found == [], [(f.path, f.lineno, f.rule, f.detail) for f in found]


def test_aut6_only_the_outbox_module_holds_write_authority() -> None:
    with_writes = [row.module for row in AUT6_WP1_ROWS if row.writes]
    assert with_writes == [_OUTBOX]
    for row in AUT6_WP1_ROWS:
        assert row.argvs == () and row.sqlite == () and row.write_imports == frozenset(), row.module


def test_aut6_closure_entry_points_with_the_outbox_have_alerts_write_authority() -> None:
    for entry, modules in AUT6_ENTRY_MODULES.items():
        row = AUT6_WRITE_AUTHORITY[entry]
        assert row.writes == (_ALERTS_WRITES,), entry
        assert row.process_calls == (), entry
        assert {row.module for row in AUT6_WP1_ROWS} >= set(modules), entry


def test_aut6_write_authority_table_lists_every_aut6_unit() -> None:
    units = {
        path.name.removesuffix(".service").removesuffix(".timer")
        for path in DEPLOY_SYSTEMD_DIR.glob("breezy-autonomy-*")
        if path.suffix in {".service", ".timer"}
    }
    assert "breezy-autonomy-alert-redeliver" in units
    # the shared wrapper is a script, not a unit; AUT-5's engine rows are judged under AUT-5's table
    own = {unit for unit in units if not unit.startswith(("breezy-autonomy-bwrap",))}
    rows = {key.split("#")[0] for key in AUT6_WRITE_AUTHORITY}
    assert own <= rows
    for key, row in AUT6_WRITE_AUTHORITY.items():
        assert row.writes == tuple(sorted(set(row.writes), key=row.writes.index)), key
        assert all(not path.startswith(("/", "~")) for path in row.writes), key


def _call_count(module: str) -> int:
    return sum(isinstance(n, ast.Call) for n in ast.walk(ast.parse(_path_of(module).read_text())))


def test_aut6_lint_is_non_vacuous_per_entry_point() -> None:
    """The M2 floor: an entry point judging fewer sites than its literal floor, or zero, fails."""
    assert set(AUT6_LINT_MIN_JUDGED_SITES) == set(AUT6_ENTRY_MODULES)
    for entry, modules in AUT6_ENTRY_MODULES.items():
        floor = AUT6_LINT_MIN_JUDGED_SITES[entry]
        judged = sum(_call_count(m) for m in modules)
        assert floor > 0, entry
        assert judged >= floor, (entry, judged, floor)
    emptied = "X = 1\n"
    found = lint_source(
        "src/breezy/runtime/alert_proof.py",
        emptied,
        module="breezy.runtime.alert_proof",
        authority=AUT6_WP1_ROWS,
    )
    assert {f.rule for f in found} == {"aut1_vacuous"}


_PLANTED: Final[dict[str, str]] = {
    "write_mode_open": "def f(p):\n    open(p, 'w').close()\n",
    "sqlite_connect": "import sqlite3\ndef f(p):\n    sqlite3.connect(p)\n",
    "subprocess_call": "import subprocess\ndef f():\n    subprocess.run(['true'])\n",
    "os_system": "import os\ndef f():\n    os.system('true')\n",
    "unlink_outside_row": "import os\ndef f(p):\n    os.unlink(p)\n",
    "ctypes": "import ctypes\n",
}


@pytest.mark.parametrize("case", sorted(_PLANTED))
def test_aut6_closure_positive_control_planted_write_outside_a_row_fails(case: str) -> None:
    row = AuthorityRow("breezy.runtime.alert_planted", min_calls=0)
    found = lint_source(
        "src/breezy/runtime/alert_planted.py",
        _PLANTED[case],
        module="breezy.runtime.alert_planted",
        authority=(row,),
    )
    assert found, f"the lint did not fire on {case!r}"


def test_aut6_write_row_scope_is_a_function_not_the_whole_module() -> None:
    row = AuthorityRow("breezy.runtime.alert_planted", writes=("_publish",), min_calls=0)
    src = "import os\ndef _publish(p):\n    os.unlink(p)\ndef other(p):\n    os.unlink(p)\n"
    found = lint_source(
        "src/breezy/runtime/alert_planted.py",
        src,
        module="breezy.runtime.alert_planted",
        authority=(row,),
    )
    assert [f.scope for f in found] == ["other"]


def test_aut6_real_files_resolve_to_their_module_names() -> None:
    for row in AUT6_WP1_ROWS:
        assert module_of(_path_of(row.module)) == row.module
    assert _RUNTIME.is_dir()


# -- the self-probe constants, derived from the bwrap table (AE3) ----------------------------


def _derived_probe(row_name: str) -> detector_catalog.SelfProbe:
    from breezy.runtime.autonomy_sandbox.table import AUTONOMY_BWRAP_TABLE

    binds = AUTONOMY_BWRAP_TABLE[row_name].binds
    bound = set(binds)
    parents = []
    for bind in binds:
        parent = bind.rsplit("/", 1)[0]
        if parent not in bound and parent not in parents:
            parents.append(parent)
    positives = tuple(f"{bind}/.bwrap_probe" for bind in binds)
    return detector_catalog.SelfProbe(("state", "registry", *parents), positives)


def test_aut6_self_probe_paths_are_constants_derived_from_bwrap_table() -> None:
    for row, probe in AUT6_SELF_PROBE_PATHS.items():
        assert probe == _derived_probe(row), row
    assert "breezy-autonomy-alert-redeliver" in AUT6_SELF_PROBE_PATHS
    writes = AUT6_WRITE_AUTHORITY["bwrap-self-probe"].writes
    assert writes and all(path.endswith("/.aut6_bwrap_probe_*") for path in writes)
    assert {w.removesuffix("/.aut6_bwrap_probe_*") for w in writes} == {
        d for p in AUT6_SELF_PROBE_PATHS.values() for d in (*p.negative, *p.positive)
    }


def test_aut6_widened_bind_fails_the_self_probe_derivation() -> None:
    import dataclasses

    from breezy.runtime.autonomy_sandbox.table import AUTONOMY_BWRAP_TABLE

    row = AUTONOMY_BWRAP_TABLE["breezy-autonomy-alert-redeliver"]
    widened = dataclasses.replace(row, binds=("evidence/alerts", "cache/extra"))
    assert len(widened.binds) == 2 and _derived_probe(row.name) == AUT6_SELF_PROBE_PATHS[row.name]


def test_aut6_authority_rows_carry_no_in_sandbox_systemctl_call() -> None:
    """E-7e(h): bus reads arrive through the snapshot pre-line, never in the sandbox."""
    for key, row in AUT6_WRITE_AUTHORITY.items():
        assert not any("systemctl" in call for call in row.process_calls), key


# -- read allowlist, sqlite, WAL (r9, r10, r11) -----------------------------------------------

_NON_WRITER_FILES: Final[tuple[str, ...]] = (
    "breezy.runtime.alert_proof",
    "breezy.runtime.alert_drain",
    "breezy.runtime.alert_delivery",
    "breezy.runtime.alert_redeliver_cli",
    "breezy.runtime.check_alerts_cli",
    "breezy.persistence.autonomy.detector_catalog",
)


def _allow(source: str) -> list[Finding]:
    return read_allowlist_findings("planted.py", source)


def test_aut6_non_writer_io_calls_are_on_read_allowlist() -> None:
    for module in _NON_WRITER_FILES:
        path = _path_of(module)
        found = read_allowlist_findings(str(path), path.read_text(encoding="utf-8"))
        assert found == [], [(f.lineno, f.detail) for f in found]


def test_aut6_read_allowlist_accepts_rdonly_cloexec_and_bare_open() -> None:
    ok = (
        "import os\nos.open(p, os.O_RDONLY | os.O_CLOEXEC)\n",
        "import os\nos.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY)\n",
        "import os\nos.open(p, os.O_RDONLY)\n",
        "open(p)\n",
        "open(p, 'r')\n",
        "open(p, 'rb', encoding=None)\n",
        "import fcntl\nfcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n",
    )
    for source in ok:
        assert _allow(source) == [], source
    for bad in (
        "open(p, mode)\n",
        "open(p, 'w')\n",
        "open(p, mode='ab')\n",
        "import os\nos.open(p, os.O_RDWR)\n",
        "import os\nos.open(p, os.O_RDONLY | os.O_CREAT)\n",
        "import os\nos.open(p, flags)\n",
    ):
        assert _allow(bad), bad


_R9_PLANTED: Final[dict[str, str]] = {
    "path_write_text": "def f(p):\n    p.write_text('x')\n",
    "path_unlink": "def f(p):\n    p.unlink()\n",
    "os_replace": "import os\ndef f(a, b):\n    os.replace(a, b)\n",
    "os_link": "import os\ndef f(a, b):\n    os.link(a, b)\n",
    "shutil_copy": "import shutil\ndef f(a, b):\n    shutil.copy(a, b)\n",
    "tempfile": "import tempfile\ndef f():\n    tempfile.mkstemp()\n",
    "from_os_system": "from os import system\ndef f():\n    system('x')\n",
    "aliased_os": "import os as o\ndef f(a):\n    o.unlink(a)\n",
    "subprocess": "import subprocess\ndef f():\n    subprocess.run(['x'])\n",
    "ctypes": "import ctypes\ndef f():\n    ctypes.CDLL('x')\n",
    "importlib": "import importlib\ndef f():\n    importlib.import_module('x')\n",
    "dunder_import": "def f():\n    __import__('os')\n",
    "eval": "def f(x):\n    eval(x)\n",
    "exec": "def f(x):\n    exec(x)\n",
    "compile": "def f(x):\n    compile(x, 'f', 'exec')\n",
    "setattr": "def f(o):\n    setattr(o, 'a', 1)\n",
    "path_open_write": "def f(p):\n    p.open('w')\n",
    "socket": "import socket\ndef f():\n    socket.socket()\n",
}


@pytest.mark.parametrize("case", sorted(_R9_PLANTED))
def test_aut6_closure_forbids_extended_write_and_dynamic_code_constructs(case: str) -> None:
    """Each case fails because it is off the allowlist (r10), not because it is in a denylist."""
    found = _allow(_R9_PLANTED[case])
    assert found and {f.rule for f in found} == {"aut6_off_allowlist"}, case


def test_aut6_write_rows_are_path_literal_or_constant() -> None:
    """The authority literals are plain strings (or one named constant), never computed paths."""
    tree = ast.parse(Path(detector_catalog.__file__).read_text(encoding="utf-8"))
    constants = {
        t.id
        for n in tree.body
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)
        for t in n.targets
        if isinstance(t, ast.Name)
    }
    constants |= {
        n.target.id
        for n in tree.body
        if isinstance(n, ast.AnnAssign)
        and isinstance(n.target, ast.Name)
        and isinstance(n.value, ast.Constant)
    }
    rows = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "AuthorityRow"
    ]
    assert len(rows) >= len(AUT6_WRITE_AUTHORITY) - 1
    for row in rows:
        writes = row.args[0] if row.args else None
        if not isinstance(writes, ast.Tuple):
            continue  # the self-probe row is computed from AUT6_SELF_PROBE_PATHS (tested above)
        for element in writes.elts:
            assert isinstance(element, ast.Constant) or (
                isinstance(element, ast.Name) and element.id in constants
            ), ast.dump(element)
    # a planted computed path is not literal-or-constant
    planted = ast.parse("AuthorityRow((base + '/x',))").body[0]
    assert isinstance(planted, ast.Expr)


def test_aut6_closure_scope_is_aut6_globs_and_every_module_classified() -> None:
    aut6_runtime = {
        "alert_outbox.py",
        "alert_proof.py",
        "alert_drain.py",
        "alert_delivery.py",
        "alert_redeliver_cli.py",
    }
    not_aut6 = {"alert_ladder.py"}  # the study-failure alert ladder, judged under its own plan
    found = {p.name for p in _RUNTIME.glob("alert_*.py")}
    assert found == aut6_runtime | not_aut6, found ^ (aut6_runtime | not_aut6)
    judged = {Path(p).name for p in map(str, _judged_files())}
    assert aut6_runtime <= judged


def test_aut6_read_allowlist_and_pure_builtins_are_literal() -> None:
    tree = ast.parse(Path(detector_catalog.__file__).read_text(encoding="utf-8"))
    for name in ("AUT6_READ_ALLOWLIST", "AUT6_PURE_BUILTINS", "AUT6_ROLLBACK_JOURNAL_STORES"):
        node = next(
            n.value
            for n in tree.body
            if isinstance(n, ast.AnnAssign)
            and isinstance(n.target, ast.Name)
            and n.target.id == name
            and n.value is not None
        )
        assert isinstance(node, ast.Call) and node.func.id == "frozenset", name  # type: ignore[attr-defined]
        for arg in node.args:
            assert isinstance(arg, ast.Set), name
            assert all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in arg.elts)
    assert "open" in AUT6_READ_ALLOWLIST and "print" in AUT6_PURE_BUILTINS
    assert not {"eval", "exec", "setattr", "open"} & AUT6_PURE_BUILTINS
    assert AUT6_ROLLBACK_JOURNAL_STORES == frozenset()


def test_sqlite_readers_use_mode_ro_and_query_only() -> None:
    good = (
        "import sqlite3\ndef f():\n    c = sqlite3.connect('file:x?mode=ro', uri=True)\n"
        "    c.execute('PRAGMA query_only=ON')\n"
    )
    assert sqlite_findings("p.py", good) == []
    for bad in (
        "import sqlite3\nsqlite3.connect('x.db')\n",
        "import sqlite3\nsqlite3.connect('file:x?mode=ro', uri=True)\n",  # no query_only
        "import sqlite3\nsqlite3.connect(path, uri=True)\n",
    ):
        assert sqlite_findings("p.py", bad), bad
    for module in _NON_WRITER_FILES:
        path = _path_of(module)
        assert sqlite_findings(str(path), path.read_text(encoding="utf-8")) == []


def test_aut6_wrapped_units_open_no_live_wal_db_in_place() -> None:
    for row in AUT6_WP1_ROWS:
        path = _path_of(row.module)
        assert wal_in_place_findings(str(path), path.read_text(encoding="utf-8")) == []
    planted = "import sqlite3\nsqlite3.connect('state/exec.sqlite')\n"
    assert wal_in_place_findings("p.py", planted), "positive control"
