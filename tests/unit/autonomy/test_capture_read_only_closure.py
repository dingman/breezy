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
    REASON_COPY_SITES,
    STDIO_CONSTANT_REFERENCES,
    WRITE_MODULE_FUNCTIONS,
    AuthorityRow,
    aut1_files,
    lint_files,
    lint_source,
    module_of,
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
    "eval_call": "def f(x):\n    return eval(x)\n",
    "exec_call": "def f(x):\n    exec(x)\n",
    "compile_call": "def f(x):\n    return compile(x, 'f', 'exec')\n",
    "sys_modules": "import sys\ndef f():\n    return sys.modules\n",
    "sys_modules_alias": "import sys as s\ndef f():\n    return s.modules\n",
    "open_alias": "opener = open\n",
    "open_alias_in_function": "def f():\n    g = open\n    return g\n",
    "open_passed_as_argument": "def f(p):\n    return list(map(open, p))\n",
    "builtins_open_reference": "import builtins\ndef f(p):\n    return builtins.open(p, 'rb')\n",
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


def test_the_new_forbidden_forms_do_not_flag_lookalikes() -> None:
    clean = (
        "import re\n"
        "PATTERN = re.compile('x')\n"
        "def f(p, mod):\n"
        "    mod.compile(p)\n"
        "    return open(p, 'rb')\n"
    )
    assert _lint(clean) == []


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


_ARGV_ROW: Final = AuthorityRow(_PLANTED_MODULE, argvs=(("journalctl", "--user"),), min_calls=0)


def test_only_the_two_stdio_constants_are_exempt_references() -> None:
    assert STDIO_CONSTANT_REFERENCES == {"subprocess.PIPE", "subprocess.DEVNULL"}


def test_stdio_constants_are_accepted_inside_a_row_matched_popen() -> None:
    source = (
        "import subprocess\n"
        "def f():\n"
        "    return subprocess.Popen(['journalctl', '--user'],"
        " stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)\n"
    )
    assert _lint(source, row=_ARGV_ROW) == []


@pytest.mark.parametrize(
    "call",
    [
        "subprocess.run(['rm', '-rf', 'x'], stdout=subprocess.PIPE)",
        "subprocess.Popen(['rm', 'x'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)",
        "subprocess.run(['journalctl', '--user'])",
        "os.write(1, b'x')",
        "os.replace('a', 'b')",
    ],
)
def test_stdio_constants_do_not_exempt_other_subprocess_or_os_writes(call: str) -> None:
    source = f"import os\nimport subprocess\ndef unlisted():\n    return {call}\n"
    row = AuthorityRow(_PLANTED_MODULE, argvs=(("journalctl", "--user"),), min_calls=0)
    findings = _lint(source, row=row)
    if "journalctl" in call:  # the row's own argv is judged as before: allowed
        assert findings == []
    else:
        assert _rules(findings) == {"aut1_write_authority"}


def test_a_stdio_constant_does_not_launder_an_unlisted_subprocess_run() -> None:
    source = "import subprocess\ndef f():\n    subprocess.run(['x'], stdout=subprocess.PIPE)\n"
    details = {f.detail for f in _lint(source, row=_ARGV_ROW)}
    assert "subprocess.run" in details and "subprocess.PIPE" not in details


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


# -- WP2-R2: ``reason=<name>.reason`` is admitted only at enumerated copy sites -----------------

_SITE_MODULE: Final = "breezy.strategy.autonomy_capture.guarded_strategy"
_SITE_PATH: Final = "src/breezy/strategy/autonomy_capture/guarded_strategy.py"
_SITE_SCOPE: Final = "decision_follow_up"
_SITE_ROW: Final = AuthorityRow(_SITE_MODULE, min_calls=0)


def _site_lint(body: str, *, function: str = _SITE_SCOPE) -> list[Finding]:
    source = f"def {function}(take, outcome):\n    return make_record(DecisionRecord, {body})\n"
    return lint_source(_SITE_PATH, source, module=_SITE_MODULE, authority=(_SITE_ROW,))


def test_a_reason_attribute_read_is_accepted_at_an_enumerated_site() -> None:
    assert _site_lint("reason=outcome.reason") == []


def test_the_same_attribute_read_is_flagged_anywhere_else() -> None:
    """MUTATION: dropping the (module, function) check admits ``x.reason`` everywhere."""
    assert _rules(_site_lint("reason=outcome.reason", function="other")) == {"aut1_reason_constant"}
    assert _rules(_lint("def f(e):\n    make_record(DecisionRecord, reason=e.reason)\n")) == {
        "aut1_reason_constant"
    }


@pytest.mark.parametrize(
    "expression",
    [
        "'inline'",
        "outcome",
        "compute(outcome)",
        "outcome.reason.upper()",
        "outcome.a.reason",
        "outcome.other",
        "outcome.REASON_X.lower",
        "outcome['reason']",
        "outcome.reason or 'x'",
        "f'{outcome.reason}'",
    ],
)
def test_an_arbitrary_expression_is_still_flagged_even_at_an_enumerated_site(
    expression: str,
) -> None:
    """MUTATION: accepting any attribute (or any expression) at a site fails these controls."""
    assert _rules(_site_lint(f"reason={expression}")) == {"aut1_reason_constant"}


def test_the_receiver_name_is_pinned_at_each_site() -> None:
    """WP2-R6 L4. MUTATION: dropping the receiver from the site key admits ``other.reason``."""
    assert _rules(_site_lint("reason=other.reason")) == {"aut1_reason_constant"}
    assert _site_lint("reason=outcome.reason") == []


@pytest.mark.parametrize(("module", "scope", "receiver"), sorted(REASON_COPY_SITES))
def test_each_enumerated_copy_site_really_holds_the_attribute_read(
    module: str, scope: str, receiver: str
) -> None:
    """Non-vacuous: the site exists in the real file and carries a ``reason=<name>.reason``
    keyword in that function, so a stale row (renamed function) fails here."""
    import ast

    from tests.support.autonomy_scan import walk_with_scope
    from tests.support.entry_points import SRC_DIR

    path = SRC_DIR.joinpath(*module.split(".")).with_suffix(".py")
    assert module_of(path) == module
    tree = ast.parse(path.read_text(encoding="utf-8"))
    reads = [
        keyword
        for node, where in walk_with_scope(tree)
        if where == scope and isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg == "reason"
        and isinstance(keyword.value, ast.Attribute)
        and keyword.value.attr == "reason"
        and isinstance(keyword.value.value, ast.Name)
        and keyword.value.value.id == receiver
    ]
    assert reads, f"{module}:{scope} holds no reason=<name>.reason read"
    assert lint_files([path]) == []


# -- D10: an argv-matched subprocess call is admitted only in its plain form (S3-R15, S3-R36) ----

_PLAIN_CALL: Final = "subprocess.run(['journalctl', '--user']{extra})"


def _argv_lint(call: str, *, prefix: str = "import subprocess\n") -> list[Finding]:
    return _lint(f"{prefix}def f(rest, opts):\n    return {call}\n", row=_ARGV_ROW)


def test_the_plain_argv_call_is_admitted() -> None:
    """Control for every refusal below: the same call without the extra is admitted."""
    assert _argv_lint(_PLAIN_CALL.format(extra="")) == []
    both = ", stdout=subprocess.PIPE, stderr=subprocess.DEVNULL"
    assert _argv_lint(_PLAIN_CALL.format(extra=both)) == []
    assert _argv_lint("subprocess.Popen(['journalctl', '--user'], stdout=subprocess.PIPE)") == []


def test_the_allowed_keyword_set_is_the_two_stdio_slots() -> None:
    from tests.support.capture_closure_lint import ALLOWED_SUBPROCESS_KWARGS

    assert ALLOWED_SUBPROCESS_KWARGS == {"stdout", "stderr"}


@pytest.mark.parametrize(
    "keyword",
    [
        "shell=True",
        "env={}",
        "executable='/bin/sh'",
        "cwd='/'",
        "stdin=subprocess.PIPE",
        "input=b''",
        "close_fds=False",
        "preexec_fn=None",
        "start_new_session=True",
    ],
)
def test_argv_call_refuses_kwarg(keyword: str) -> None:
    findings = _argv_lint(_PLAIN_CALL.format(extra=f", {keyword}"))
    assert _rules(findings) == {"aut1_write_authority"}, keyword


@pytest.mark.parametrize(
    "stdio", ["open('journal.bin', 'rb')", "rest", "None", "subprocess.STDOUT"]
)
def test_argv_call_refuses_a_stdio_keyword_that_is_not_a_stdio_constant(stdio: str) -> None:
    assert _argv_lint(_PLAIN_CALL.format(extra=f", stdout={stdio}"))


def test_argv_call_refuses_second_positional() -> None:
    assert _argv_lint(_PLAIN_CALL.format(extra=", 4096"))


def test_argv_call_refuses_starred_element() -> None:
    assert _argv_lint("subprocess.run(['journalctl', '--user', *rest])")
    assert _argv_lint("subprocess.run([*rest])")


def test_argv_call_refuses_splat() -> None:
    assert _argv_lint(_PLAIN_CALL.format(extra=", *rest"))
    assert _argv_lint(_PLAIN_CALL.format(extra=", **opts"))
    assert _argv_lint("subprocess.run(*rest)")


def test_from_subprocess_import_popen_refused() -> None:
    source = "from subprocess import Popen\ndef f():\n    return Popen(['journalctl', '--user'])\n"
    assert _rules(_lint(source, row=_ARGV_ROW)) == {"aut1_write_authority"}


def test_an_aliased_subprocess_module_is_refused() -> None:
    call = "sp.run(['journalctl', '--user'])"
    assert _argv_lint(call, prefix="import subprocess as sp\n")


def test_two_subprocess_calls_on_one_line_matched_by_position() -> None:
    """The admitted call must not launder an unlisted one that shares its line (S3-R36)."""
    both = "(subprocess.run(['journalctl', '--user']), subprocess.run(['rm', '-rf', 'x']))"
    findings = _argv_lint(both)
    assert len(findings) == 1 and findings[0].rule == "aut1_write_authority"
    two_good = (
        "(subprocess.run(['journalctl', '--user']), subprocess.run(['journalctl', '--user']))"
    )
    assert _argv_lint(two_good) == []
    reference = "(subprocess.run(['journalctl', '--user']), subprocess.run)"
    assert len(_argv_lint(reference)) == 1


def test_existing_journal_templates_still_admitted() -> None:
    """Guard: the three real journal ``Popen`` sites keep passing (the rows are the real ones)."""
    from tests.support.capture_closure_lint import AUT1_WRITE_AUTHORITY, aut1_files

    host = next(p for p in aut1_files() if p.name == "capture_audit_host.py")
    rows = [r for r in AUT1_WRITE_AUTHORITY if r.module.endswith("capture_audit_host")]
    assert rows and len(rows[0].argvs) == 3
    assert lint_files([host]) == []
