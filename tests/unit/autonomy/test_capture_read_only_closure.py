"""AUT-1 WP1 part B: the read-only closure lint (plan r12 section 3.15; E-7, E-7a rule 4).

The lint lives in ``tests/support/capture_closure_lint.py``: an allowlist (``AUT1_WRITE_AUTHORITY``)
over only the AUT-1 module globs. These tests run it over the real tree and, with the same pure
function, over planted scratch sources, so a lint that stopped looking fails here.
"""

from pathlib import Path
from typing import Final

import pytest

from tests.support.autonomy_scan import Finding
from tests.support.capture_closure_lint import (
    AUT1_GLOBS,
    AUT1_WRITE_AUTHORITY,
    WRITE_MODULE_FUNCTIONS,
    AuthorityRow,
    aut1_files,
    lint_files,
    lint_source,
)

_PLANTED_MODULE: Final = "breezy.persistence.autonomy.capture_planted"
_PLANTED_PATH: Final = "src/breezy/persistence/autonomy/capture_planted.py"
#: A row that grants nothing: every planted violation below is judged against it.
_EMPTY_ROW: Final = AuthorityRow(_PLANTED_MODULE, min_calls=0)
_PERSISTENCE: Final = "breezy.persistence.autonomy"


def _lint(source: str, *, row: AuthorityRow = _EMPTY_ROW) -> list[Finding]:
    return lint_source(_PLANTED_PATH, source, module=_PLANTED_MODULE, authority=(row,))


def _rules(findings: list[Finding]) -> set[str]:
    return {f.rule for f in findings}


# -- the real tree -----------------------------------------------------------------------------


def test_aut1_closures_follow_write_authority_allowlist() -> None:
    files = aut1_files()
    findings = lint_files(files)
    assert findings == [], [(f.path, f.lineno, f.rule, f.detail) for f in findings]


def test_the_lint_judges_every_aut1_module_that_exists_and_is_not_vacuous() -> None:
    names = {f.name for f in aut1_files()}
    assert {
        "capture_records.py",
        "capture_stream.py",
        "capture_publish.py",
        "capture_reader.py",
        "capture_forecast_ref.py",
    } <= names
    assert len(AUT1_GLOBS) == 7
    rows = {row.module for row in AUT1_WRITE_AUTHORITY}
    assert len(rows) >= len(names)


def test_every_judged_module_needs_an_authority_row(tmp_path: Path) -> None:
    """A new AUT-1 module cannot land without a reviewed row: no row is itself a finding."""
    found = lint_source(
        _PLANTED_PATH, "X = 1\n", module="breezy.persistence.autonomy.capture_unlisted"
    )
    assert _rules(found) == {"aut1_no_authority_row"}


def test_the_real_tree_fails_with_no_allowlist() -> None:
    """Remove the allowlist and every real module is unjudged: the lint has teeth."""
    assert lint_files(aut1_files(), authority=()) != []


def test_writers_hold_only_the_write_imports_their_row_names() -> None:
    by_module = {row.module: row for row in AUT1_WRITE_AUTHORITY}
    assert by_module[f"{_PERSISTENCE}.capture_stream"].write_imports == {"ensure_dir"}
    assert by_module[f"{_PERSISTENCE}.capture_epoch"].write_imports == {"write_once", "ensure_dir"}
    for module, row in by_module.items():
        if module.endswith(("capture_reader", "capture_forecast_ref", "capture_records")):
            assert row.write_imports == frozenset(), module
            assert row.writes == () and row.argvs == () and row.sqlite == (), module


# -- positive controls: a planted violation must fail ------------------------------------------


_PLANTED_VIOLATIONS: Final[dict[str, str]] = {
    "open_write": "def f(p):\n    open(p, 'w').close()\n",
    "open_append": "def f(p):\n    open(p, 'ab')\n",
    "path_write_text": "def f(p):\n    p.write_text('x')\n",
    "os_replace": "import os\ndef f(a, b):\n    os.replace(a, b)\n",
    "os_open_creat": "import os\ndef f(a):\n    os.open(a, os.O_CREAT | os.O_WRONLY)\n",
    "os_open_opaque_flags": "import os\ndef f(a, flags):\n    os.open(a, flags)\n",
    "sqlite_connect": "import sqlite3\ndef f(p):\n    sqlite3.connect(p)\n",
    "subprocess_run": "import subprocess\ndef f():\n    subprocess.run(['cp', 'a', 'b'])\n",
    "os_system": "import os\ndef f():\n    os.system('true')\n",
    "os_popen": "import os\ndef f():\n    os.popen('true')\n",
    "os_execv": "import os\ndef f():\n    os.execv('/bin/true', ['true'])\n",
    "os_alias_system": "import os as o\ndef f():\n    o.system('true')\n",
    "from_os_system": "from os import system\ndef f():\n    system('true')\n",
    "ctypes_import": "import ctypes\n",
    "ctypes_from": "from ctypes import CDLL\n",
    "importlib_call": "import importlib\ndef f():\n    importlib.import_module('os')\n",
    "dunder_import": "def f():\n    __import__('os')\n",
}


@pytest.mark.parametrize("case", sorted(_PLANTED_VIOLATIONS))
def test_lint_has_positive_control(case: str) -> None:
    """MUTATION (red): a lint with no allowlist enforcement lets every planted form through."""
    assert _lint(_PLANTED_VIOLATIONS[case]), f"the lint did not fire on {case!r}"


def test_non_literal_open_mode_fails_closed() -> None:
    assert _lint("def f(p, mode):\n    open(p, mode)\n")
    assert _lint("def f(p, mode):\n    open(p, mode=mode)\n")
    assert _lint("def f(p, kw):\n    open(p, **kw)\n")
    assert _lint("def f(p, m):\n    from pathlib import Path\n    Path(p).open(m)\n")
    # A literal read mode is not a write site.
    assert _lint("def f(p):\n    return open(p, 'rb')\n") == []


def test_a_write_is_allowed_only_inside_the_rows_named_scope() -> None:
    source = (
        "import os\n"
        "def publish(a, b):\n    os.replace(a, b)\n"
        "def sneaky(a, b):\n    os.replace(a, b)\n"
    )
    row = AuthorityRow(_PLANTED_MODULE, writes=("publish",), min_calls=0)
    findings = _lint(source, row=row)
    assert [f.scope for f in findings] == ["sneaky"]


def test_subprocess_and_sqlite_need_a_literal_argument_on_the_row() -> None:
    run = "import subprocess\ndef f():\n    subprocess.run(['journalctl', '--user'])\n"
    other = "import subprocess\ndef f():\n    subprocess.run(['rm', '-rf', 'x'])\n"
    dynamic = "import subprocess\ndef f(argv):\n    subprocess.run(argv)\n"
    row = AuthorityRow(_PLANTED_MODULE, argvs=(("journalctl", "--user"),), min_calls=0)
    assert _lint(run, row=row) == []
    assert _lint(other, row=row)
    assert _lint(dynamic, row=row)
    conn = "import sqlite3\ndef f():\n    sqlite3.connect('file:x?mode=ro')\n"
    sql_row = AuthorityRow(_PLANTED_MODULE, sqlite=("file:x?mode=ro",), min_calls=0)
    assert _lint(conn, row=sql_row) == []
    assert _lint(conn)


def test_a_non_writer_cannot_import_a_cross_unit_write_function() -> None:
    assert WRITE_MODULE_FUNCTIONS[f"{_PERSISTENCE}.single_read"] >= {"write_once", "ensure_dir"}
    forms = [
        f"from {_PERSISTENCE}.single_read import write_once\n",
        f"from {_PERSISTENCE}.single_read import ensure_dir as mk\n",
        f"import {_PERSISTENCE}.single_read\n",
        f"from {_PERSISTENCE} import single_read\n",
        f"from {_PERSISTENCE}.registry_store import RegistryStore\n",
        f"from {_PERSISTENCE}.hwm import write_monotone\n",
    ]
    for source in forms:
        assert "aut1_write_import" in _rules(_lint(source)), source
    # Named read-only functions stay importable.
    ok = f"from {_PERSISTENCE}.single_read import open_root, walk_dirs, read_once_at\n"
    assert _lint(ok) == []
    # A writer row that lists the name is allowed exactly that name.
    row = AuthorityRow(_PLANTED_MODULE, write_imports=frozenset({"ensure_dir"}), min_calls=0)
    assert _lint(f"from {_PERSISTENCE}.single_read import ensure_dir\n", row=row) == []
    assert _lint(f"from {_PERSISTENCE}.single_read import write_once\n", row=row)


def test_reason_values_are_constants() -> None:
    good = (
        "from somewhere import REFUSED\n"
        "LOCAL_REASON = 'x'\n"
        "def f(rec):\n"
        "    make_record(DecisionRecord, reason=LOCAL_REASON)\n"
        "    Refuse(reason=REFUSED)\n"
        "    OrderEventRecord(reason=mod.CAUSE)\n"
    )
    assert _lint(good) == []
    bad_literal = "def f():\n    make_record(DecisionRecord, reason='inline')\n"
    bad_computed = "def f(why):\n    Refuse(reason=f'x:{why}')\n"
    bad_variable = "def f(why):\n    OrderEventRecord(reason=why)\n"
    bad_lowercase_module_name = (
        "reason_name = 'x'\ndef f():\n    make_record(DecisionRecord, reason=reason_name)\n"
    )
    bad_suffix_sink = "def f(why):\n    SomethingRecord(reason=why)\n    X.Veto(reason=why)\n"
    for source in (
        bad_literal,
        bad_computed,
        bad_variable,
        bad_lowercase_module_name,
        bad_suffix_sink,
    ):
        assert _rules(_lint(source)) == {"aut1_reason_constant"}, source


def test_a_read_side_view_that_copies_a_stored_reason_is_not_a_sink() -> None:
    copied = "def f(e):\n    return LifecycleEventView(reason=e.reason)\n"
    assert _lint(copied) == []


def test_the_lint_refuses_a_vacuous_row() -> None:
    row = AuthorityRow(_PLANTED_MODULE, min_calls=5)
    assert _rules(_lint("X = 1\nprint('a')\n", row=row)) == {"aut1_vacuous"}


def test_a_planted_scratch_module_on_disk_fails_the_file_walk(tmp_path: Path) -> None:
    src = tmp_path / "persistence" / "autonomy"
    src.mkdir(parents=True)
    planted = src / "capture_planted.py"
    planted.write_text("def f(p):\n    open(p, 'w').close()\n", encoding="utf-8")
    assert aut1_files(tmp_path) == [planted]
    findings = lint_source(
        "planted.py", planted.read_text(encoding="utf-8"), module=_PLANTED_MODULE
    )
    assert _rules(findings) == {"aut1_no_authority_row"}
    granted = lint_source(
        "planted.py",
        planted.read_text(encoding="utf-8"),
        module=_PLANTED_MODULE,
        authority=(_EMPTY_ROW,),
    )
    assert _rules(granted) == {"aut1_write_authority"}
