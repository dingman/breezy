"""ARCH-0 seam 4a: autonomy files have one writer (L-50; ARCH section 4.7, seam A AC 7).

An AST scan over every autonomy source (plus ``live_orders_gate``, home of the one named
exemption) fails on any filesystem write site outside the rows of
``autonomy_writer_table.WRITE_SITE_ALLOWLIST``: ``single_read.{write_once, replace_atomic,
ensure_dir}`` (and their private helpers), the whole ``registry_store`` module, and
``live_orders_gate._verify_ruling_file``. Allowlist rows for code that has not landed are accepted
while absent. Anything the scan cannot resolve (an ``open`` mode or ``os.open`` flags it cannot
evaluate statically) counts as a write: the gate fails closed.

A write site is: ``open`` in a write/append/exclusive/update mode (builtin, ``io``, ``Path.open``),
``os.open`` with a write flag, the ``os`` mutators (``link``, ``replace``, ``rename``, ``unlink``,
``mkdir``, ``write``, ``chmod`` ...), the ``shutil`` mutators, ``tempfile`` creators, the
``Path`` mutators (``write_text``, ``write_bytes``, ``mkdir``, ``touch``, ``unlink``, ``rename``,
one-argument ``replace`` ...), and the dataframe and array writers.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Final

import pytest

from tests.support.autonomy_scan import (
    Finding,
    autonomy_source_files,
    module_name,
    relative_path,
    scan_files,
    walk_with_scope,
)
from tests.support.entry_points import REPO_ROOT, SRC_DIR
from tests.unit.autonomy_writer_table import (
    AUTONOMY_FILE_WRITERS,
    WRITE_MECHANISMS,
    WRITE_SITE_ALLOWLIST,
    WriteSiteRule,
)

#: A scan that judges fewer files than this is vacuous (16 autonomy modules exist at seam 4a).
MIN_JUDGED_FILES: Final = 14
#: Seam 2b's ``single_read`` holds ten distinct write calls; the unfiltered scan must see them.
MIN_SINGLE_READ_SITES: Final = 6

_LIVE_ORDERS_GATE: Final[Path] = SRC_DIR / "breezy" / "persistence" / "live_orders_gate.py"

_OS_MUTATORS: Final = frozenset(
    {
        "link", "symlink", "replace", "rename", "renames", "mkdir", "makedirs", "unlink", "remove",
        "rmdir", "removedirs", "truncate", "ftruncate", "write", "writev", "chmod", "fchmod",
        "chown", "fchown", "utime", "mkfifo", "mknod",
    }
)  # fmt: skip
_SHUTIL_MUTATORS: Final = frozenset(
    {"copy", "copy2", "copyfile", "copyfileobj", "copytree", "move", "rmtree", "make_archive",
     "unpack_archive", "chown"}
)  # fmt: skip
_TEMPFILE_CREATORS: Final = frozenset(
    {"mkstemp", "mkdtemp", "NamedTemporaryFile", "TemporaryFile", "SpooledTemporaryFile",
     "TemporaryDirectory"}
)  # fmt: skip
#: Path methods that mutate regardless of arguments. ``replace`` is handled separately because
#: ``str.replace`` exists: ``Path.replace`` takes one argument, ``str.replace`` two or three.
_PATH_MUTATORS: Final = frozenset(
    {"write_text", "write_bytes", "touch", "mkdir", "unlink", "rmdir", "rename", "symlink_to",
     "hardlink_to", "chmod", "lchmod"}
)  # fmt: skip
_DATA_WRITERS: Final = frozenset(
    {"to_csv", "to_parquet", "to_json", "to_feather", "write_table", "write_feather",
     "write_dataset", "save", "savez", "savez_compressed", "savetxt"}
)  # fmt: skip
_WRITE_OS_FLAGS: Final = frozenset(
    {"O_WRONLY", "O_RDWR", "O_CREAT", "O_APPEND", "O_TRUNC", "O_EXCL", "O_TMPFILE"}
)
_MODE_STRING_RE: Final = re.compile(r"\A[rwxabt+U]{1,4}\Z")
_MAX_ALIAS_DEPTH: Final = 8


def _module_constants(tree: ast.Module) -> dict[str, ast.expr]:
    constants: dict[str, ast.expr] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    constants[target.id] = node.value
        elif (
            isinstance(node, ast.AnnAssign)
            and node.value is not None
            and isinstance(node.target, ast.Name)
        ):
            constants[node.target.id] = node.value
    return constants


def _os_flags(
    expr: ast.expr, constants: dict[str, ast.expr], depth: int = 0
) -> tuple[set[str], bool]:
    """``os.O_*`` names an ``os.open`` flag expression uses, and whether any part is opaque."""
    if depth > _MAX_ALIAS_DEPTH:
        return set(), True
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.BitOr):
        left, left_opaque = _os_flags(expr.left, constants, depth + 1)
        right, right_opaque = _os_flags(expr.right, constants, depth + 1)
        return left | right, left_opaque or right_opaque
    if isinstance(expr, ast.Attribute) and expr.attr.startswith("O_"):
        return {expr.attr}, False
    if isinstance(expr, ast.Name):
        if expr.id in constants:
            return _os_flags(constants[expr.id], constants, depth + 1)
        if expr.id.startswith("O_"):
            return {expr.id}, False
    if isinstance(expr, ast.Constant) and expr.value == 0:
        return set(), False  # O_RDONLY
    return set(), True


def _open_mode_writes(call: ast.Call) -> str | None:
    """A reason when an ``open``-named call may write, else None."""
    candidates: list[ast.expr] = [kw.value for kw in call.keywords if kw.arg == "mode"]
    positional = call.args[:2]
    for arg in positional:
        if (
            isinstance(arg, ast.Constant)
            and isinstance(arg.value, str)
            and _MODE_STRING_RE.match(arg.value)
            and any(ch in arg.value for ch in "wax+")
        ):
            return f"open mode {arg.value!r}"
    for value in candidates:
        if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
            return "open mode is not a literal"
        if any(ch in value.value for ch in "wax+"):
            return f"open mode {value.value!r}"
    func = call.func
    if (
        isinstance(func, ast.Name)
        and len(call.args) >= 2
        and not isinstance(call.args[1], ast.Constant)
    ):
        return "open mode is not a literal"
    return None


def _call_reason(
    call: ast.Call, constants: dict[str, ast.expr], os_names: dict[str, str]
) -> str | None:
    func = call.func
    receiver = (
        func.value.id
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
        else ""
    )
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    if isinstance(func, ast.Name) and name in os_names:
        receiver, name = "os", os_names[name]  # from os import X [as Y]
    if name == "open" and receiver != "os":
        return _open_mode_writes(call)
    if receiver == "os":
        if name == "open":
            flag_arg = call.args[1] if len(call.args) > 1 else None
            flag_kw = next((kw.value for kw in call.keywords if kw.arg == "flags"), None)
            flags_expr = flag_arg or flag_kw
            if flags_expr is None:
                return None
            names, opaque = _os_flags(flags_expr, constants)
            if names & _WRITE_OS_FLAGS:
                return f"os.open flags {sorted(names & _WRITE_OS_FLAGS)}"
            return "os.open flags are not statically resolvable" if opaque else None
        return f"os.{name}" if name in _OS_MUTATORS else None
    if receiver == "shutil" and name in _SHUTIL_MUTATORS:
        return f"shutil.{name}"
    if receiver == "tempfile" and name in _TEMPFILE_CREATORS:
        return f"tempfile.{name}"
    if isinstance(func, ast.Attribute):
        if name in _PATH_MUTATORS:
            return f".{name}()"
        if name == "replace" and len(call.args) == 1 and not call.keywords:
            return ".replace(target)"
        if name in _DATA_WRITERS:
            return f".{name}()"
    return None


def find_write_sites(path: str, source: str) -> list[Finding]:
    """Every filesystem write site in ``source`` (unfiltered by any allowlist)."""
    tree = ast.parse(source, filename=path)
    constants = _module_constants(tree)
    os_names = {
        alias.asname or alias.name: alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "os"
        for alias in node.names
    }
    findings: list[Finding] = []
    for node, scope in walk_with_scope(tree):
        if isinstance(node, ast.Call):
            reason = _call_reason(node, constants, os_names)
            if reason is not None:
                findings.append(Finding(path, node.lineno, "write_site", reason, scope))
    return findings


def _rule_allows(rule: WriteSiteRule, module: str, scope: str) -> bool:
    if rule.module != module:
        return False
    if rule.function is None:
        return True
    return scope == rule.function or scope.startswith(f"{rule.function}.")


def unallowed_write_sites(
    path: str, source: str, *, module: str, rules: Sequence[WriteSiteRule] = WRITE_SITE_ALLOWLIST
) -> list[Finding]:
    """Write sites in ``source`` (a file of ``module``) that no allowlist row covers."""
    return [
        site
        for site in find_write_sites(path, source)
        if not any(_rule_allows(rule, module, site.scope) for rule in rules)
    ]


def judged_files() -> list[Path]:
    return sorted({*autonomy_source_files(), _LIVE_ORDERS_GATE})


def scan_real_tree() -> list[Finding]:
    return scan_files(
        judged_files(),
        lambda path, source: unallowed_write_sites(
            path, source, module=module_name(REPO_ROOT / path)
        ),
    )


# ---------------------------------------------------------------------------
# The gate, over the real tree
# ---------------------------------------------------------------------------


def test_autonomy_files_have_one_writer() -> None:
    findings = scan_real_tree()
    assert findings == [], [(f.path, f.lineno, f.scope, f.detail) for f in findings]


def test_the_scan_judges_enough_files_and_sees_single_read_write_sites() -> None:
    files = judged_files()
    assert len(files) >= MIN_JUDGED_FILES
    single_read = REPO_ROOT / "src/breezy/persistence/autonomy/single_read.py"
    assert single_read in files
    sites = find_write_sites(relative_path(single_read), single_read.read_text(encoding="utf-8"))
    assert len(sites) >= MIN_SINGLE_READ_SITES
    assert {"os.link", "os.replace"} <= {site.detail for site in sites}


def test_removing_a_single_read_helper_row_makes_the_real_tree_fail() -> None:
    rows = tuple(rule for rule in WRITE_SITE_ALLOWLIST if rule.function != "_link_temp")
    single_read = REPO_ROOT / "src/breezy/persistence/autonomy/single_read.py"
    findings = unallowed_write_sites(
        relative_path(single_read),
        single_read.read_text(encoding="utf-8"),
        module=module_name(single_read),
        rules=rows,
    )
    assert [f.scope for f in findings] == ["_link_temp"]


# ---------------------------------------------------------------------------
# Positive controls: every write form the scan claims to catch
# ---------------------------------------------------------------------------

_PLANTED_WRITES: Final[dict[str, str]] = {
    "open_w": "def f(p):\n    open(p, 'w').close()\n",
    "open_append_binary": "def f(p):\n    open(p, 'ab')\n",
    "open_mode_keyword": "def f(p):\n    open(p, mode='x')\n",
    "open_update": "def f(p):\n    open(p, 'r+')\n",
    "open_non_literal_mode": "def f(p, m):\n    open(p, m)\n",
    "path_open_write": "def f(p):\n    p.open('w')\n",
    "io_open_write": "import io\ndef f(p):\n    io.open(p, 'w')\n",
    "os_link": "import os\ndef f(a, b):\n    os.link(a, b)\n",
    "os_replace": "import os\ndef f(a, b):\n    os.replace(a, b)\n",
    "os_rename": "import os\ndef f(a, b):\n    os.rename(a, b)\n",
    "os_unlink": "import os\ndef f(a):\n    os.unlink(a)\n",
    "os_mkdir": "import os\ndef f(a):\n    os.mkdir(a)\n",
    "os_write": "import os\ndef f(fd):\n    os.write(fd, b'x')\n",
    "os_open_creat": "import os\ndef f(a):\n    os.open(a, os.O_CREAT | os.O_WRONLY)\n",
    "os_open_via_constant": (
        "import os\nFLAGS = os.O_RDONLY | os.O_TRUNC\ndef f(a):\n    os.open(a, FLAGS)\n"
    ),
    "os_open_opaque_flags": "import os\ndef f(a, flags):\n    os.open(a, flags)\n",
    "from_os_import": "from os import replace as swap\ndef f(a, b):\n    swap(a, b)\n",
    "shutil_copy": "import shutil\ndef f(a, b):\n    shutil.copy(a, b)\n",
    "shutil_rmtree": "import shutil\ndef f(a):\n    shutil.rmtree(a)\n",
    "tempfile_mkstemp": "import tempfile\ndef f():\n    tempfile.mkstemp()\n",
    "path_write_text": "def f(p):\n    p.write_text('x')\n",
    "path_write_bytes": "def f(p):\n    p.write_bytes(b'x')\n",
    "path_mkdir": "def f(p):\n    p.mkdir()\n",
    "path_touch": "def f(p):\n    p.touch()\n",
    "path_unlink": "def f(p):\n    p.unlink()\n",
    "path_replace_one_arg": "def f(p, q):\n    p.replace(q)\n",
    "dataframe_to_parquet": "def f(df):\n    df.to_parquet('x')\n",
}


@pytest.mark.parametrize("case", sorted(_PLANTED_WRITES))
def test_the_scan_fires_on_every_planted_write_form(case: str) -> None:
    sites = unallowed_write_sites(
        "src/breezy/persistence/autonomy/planted.py",
        _PLANTED_WRITES[case],
        module="breezy.persistence.autonomy.planted",
    )
    assert sites, f"the scan did not fire on the planted {case!r}"


_PLANTED_READS: Final[dict[str, str]] = {
    "open_default_read": "def f(p):\n    open(p).close()\n",
    "open_rb": "def f(p):\n    open(p, 'rb')\n",
    "path_open_read": "def f(p):\n    p.open('rb')\n",
    "os_open_read_constant": (
        "import os\nFLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC\n"
        "def f(a, fd):\n    os.open(a, FLAGS, dir_fd=fd)\n"
    ),
    "os_fsync_and_stat": "import os\ndef f(fd):\n    os.fsync(fd)\n    os.fstat(fd)\n",
    "str_replace": "def f(s):\n    return s.replace('a', 'b')\n",
    "path_read_text": "def f(p):\n    return p.read_text()\n",
}


@pytest.mark.parametrize("case", sorted(_PLANTED_READS))
def test_the_scan_does_not_fire_on_read_only_forms(case: str) -> None:
    assert find_write_sites("src/planted.py", _PLANTED_READS[case]) == []


# ---------------------------------------------------------------------------
# Allowlist semantics
# ---------------------------------------------------------------------------

_SINGLE_READ_MODULE: Final = "breezy.persistence.autonomy.single_read"


def test_a_write_inside_an_allowlisted_function_is_accepted() -> None:
    source = "import os\ndef write_once(a, b):\n    os.link(a, b)\n"
    assert unallowed_write_sites("p.py", source, module=_SINGLE_READ_MODULE) == []


def test_a_closure_inside_an_allowlisted_function_is_accepted() -> None:
    source = (
        "import os\ndef write_once(a, b):\n    def inner():\n        os.link(a, b)\n    inner()\n"
    )
    assert unallowed_write_sites("p.py", source, module=_SINGLE_READ_MODULE) == []


def test_a_new_write_function_in_single_read_is_refused() -> None:
    source = "import os\ndef sneaky(a, b):\n    os.link(a, b)\n"
    sites = unallowed_write_sites("p.py", source, module=_SINGLE_READ_MODULE)
    assert [site.scope for site in sites] == ["sneaky"]


def test_a_function_name_prefix_is_not_a_match() -> None:
    source = "import os\ndef write_once_extra(a, b):\n    os.link(a, b)\n"
    assert unallowed_write_sites("p.py", source, module=_SINGLE_READ_MODULE)


def test_the_same_function_name_in_another_module_is_refused() -> None:
    source = "import os\ndef write_once(a, b):\n    os.link(a, b)\n"
    assert unallowed_write_sites("p.py", source, module="breezy.persistence.autonomy.other")


def test_registry_store_is_allowed_as_a_whole_module() -> None:
    source = "import os\ndef anything(a):\n    os.unlink(a)\n"
    module = "breezy.persistence.autonomy.registry_store"
    assert unallowed_write_sites("p.py", source, module=module) == []


def test_only_the_named_live_orders_gate_function_is_exempt() -> None:
    source = (
        "import os\ndef _verify_ruling_file(p):\n    os.replace(p, p)\n"
        "def other(p):\n    os.replace(p, p)\n"
    )
    sites = unallowed_write_sites("p.py", source, module="breezy.persistence.live_orders_gate")
    assert [site.scope for site in sites] == ["other"]


def test_allowlist_rows_for_code_that_has_not_landed_are_accepted_while_absent() -> None:
    landed = {module_name(path) for path in judged_files()}
    absent = [rule for rule in WRITE_SITE_ALLOWLIST if rule.module not in landed]
    assert absent, "expected registry_store (seam 6e) to be absent at seam 4a"
    assert scan_real_tree() == []


# ---------------------------------------------------------------------------
# The table itself
# ---------------------------------------------------------------------------


def test_the_writer_table_names_only_known_mechanisms_and_unique_paths() -> None:
    assert {row.mechanism for row in AUTONOMY_FILE_WRITERS} <= WRITE_MECHANISMS
    paths = [row.path for row in AUTONOMY_FILE_WRITERS]
    assert len(paths) == len(set(paths)) == 8


def test_exemptions_are_narrow_and_unique() -> None:
    keys = [(rule.module, rule.function) for rule in WRITE_SITE_ALLOWLIST]
    assert len(keys) == len(set(keys))
    whole_module = {rule.module for rule in WRITE_SITE_ALLOWLIST if rule.function is None}
    assert whole_module == {"breezy.persistence.autonomy.registry_store"}
    assert all(rule.reason for rule in WRITE_SITE_ALLOWLIST)
    named_exemption = [r for r in WRITE_SITE_ALLOWLIST if r.module.endswith("live_orders_gate")]
    assert [(r.function) for r in named_exemption] == ["_verify_ruling_file"]
