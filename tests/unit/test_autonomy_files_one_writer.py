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

from collections.abc import Sequence
from pathlib import Path
from typing import Final

import pytest

from breezy.runtime.autonomy_sandbox.write_sites import SHARED_WRITE_SITES
from tests.support.autonomy_scan import (
    SANDBOX_EXCLUSION_REASON,
    Finding,
    autonomy_source_files,
    module_name,
    relative_path,
    scan_files,
)
from tests.support.autonomy_write_scan import find_write_sites
from tests.support.autonomy_write_sites import scan_write_sites
from tests.support.capture_closure_lint import aut1_files
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
    return sorted({*autonomy_source_files(), *aut1_files(), _LIVE_ORDERS_GATE})


def scan_real_tree(rules: Sequence[WriteSiteRule] = WRITE_SITE_ALLOWLIST) -> list[Finding]:
    return scan_files(
        judged_files(),
        lambda path, source: unallowed_write_sites(
            path, source, module=module_name(REPO_ROOT / path), rules=rules
        ),
    )


# ---------------------------------------------------------------------------
# The gate, over the real tree
# ---------------------------------------------------------------------------


def test_autonomy_files_have_one_writer() -> None:
    findings = scan_real_tree()
    assert findings == [], [(f.path, f.lineno, f.scope, f.detail) for f in findings]


def test_the_scan_also_judges_the_aut1_modules_outside_autonomy_packages() -> None:
    """AUT-1 WP1 part B (L-12): ``analysis/capture_*`` is not an ``autonomy`` path, so the AUT-1
    globs widen the judged set; a planted write there would fail the real-tree gate."""
    judged = {relative_path(p) for p in judged_files()}
    assert "src/breezy/analysis/capture_forecast_ref.py" in judged
    assert "src/breezy/persistence/autonomy/capture_reader.py" in judged
    planted = unallowed_write_sites(
        "src/breezy/analysis/capture_planted.py",
        "def f(p):\n    open(p, 'w').close()\n",
        module="breezy.analysis.capture_planted",
    )
    assert [site.detail for site in planted] == ["open mode 'w'"]


def test_the_aut1_file_writer_rows_name_one_writer_per_path() -> None:
    rows = {row.path: row for row in AUTONOMY_FILE_WRITERS}
    stream = rows["derived/capture_stream/<venue>/<source>/<instance_id>/<table>_<ts_ns>.feather"]
    assert stream.mechanism == "native_stream_writer"
    assert "CaptureStreamWriter" in stream.writers
    assert rows["evidence/capture/epoch/<family_id>.json"].mechanism == "write_once"


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
    # Ruling A4-R2: the reviewer's MISSED table, one planted control each.
    "import_os_as_o": "import os as o\ndef f(a, b):\n    o.replace(a, b)\n",
    "import_shutil_as_sh": "import shutil as sh\ndef f(a, b):\n    sh.copy(a, b)\n",
    "from_shutil_import_copy": "from shutil import copy\ndef f(a, b):\n    copy(a, b)\n",
    "from_tempfile_import_mkstemp": "from tempfile import mkstemp\ndef f():\n    mkstemp()\n",
    "from_pyarrow_parquet_write_table": (
        "from pyarrow.parquet import write_table\ndef f(t, p):\n    write_table(t, p)\n"
    ),
    "pyarrow_submodule_alias": (
        "import pyarrow.parquet as pq\ndef f(t, p):\n    pq.write_table(t, p)\n"
    ),
    "getattr_on_os": "import os\ndef f(a, b):\n    getattr(os, 'replace')(a, b)\n",
    "dunder_import": "def f(a, b):\n    __import__('os').replace(a, b)\n",
    "importlib_import_module": (
        "import importlib\ndef f(a, b):\n    importlib.import_module('os').replace(a, b)\n"
    ),
    "reference_not_call": "import os\nW = os.replace\n",
    "star_import": "from os import *\n",
    "os_fdopen_write": "import os\ndef f(fd):\n    os.fdopen(fd, 'w')\n",
    "os_fdopen_non_literal": "import os\ndef f(fd, m):\n    os.fdopen(fd, m)\n",
    "os_pwrite": "import os\ndef f(fd):\n    os.pwrite(fd, b'x', 0)\n",
    "os_copy_file_range": "import os\ndef f(a, b):\n    os.copy_file_range(a, b, 1)\n",
    "os_truncate": "import os\ndef f(p):\n    os.truncate(p, 0)\n",
    "sqlite3_connect": "import sqlite3\ndef f(p):\n    sqlite3.connect(p)\n",
    "logging_file_handler": "import logging\ndef f(p):\n    logging.FileHandler(p)\n",
    "logging_rotating_handler": (
        "from logging.handlers import RotatingFileHandler\ndef f(p):\n    RotatingFileHandler(p)\n"
    ),
    "subprocess_run": "import subprocess\ndef f():\n    subprocess.run(['cp', 'a', 'b'])\n",
    "open_with_kwargs": "def f(p, kw):\n    open(p, **kw)\n",
    "path_open_non_literal_mode": "from pathlib import Path\ndef f(p, m):\n    Path(p).open(m)\n",
    "builtins_open_write": "import builtins\ndef f(p):\n    builtins.open(p, 'w')\n",
    "numpy_save_alias": "import numpy as np\ndef f(a):\n    np.save('x', a)\n",
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
    """Uses a planted rules tuple, so it stays green when ``registry_store`` lands (seam 6e)."""
    rows = (
        *WRITE_SITE_ALLOWLIST,
        WriteSiteRule("breezy.persistence.autonomy.never_landed", None, "planted absent module"),
        WriteSiteRule("breezy.persistence.autonomy.single_read", "never_landed_fn", "planted"),
    )
    assert scan_real_tree(rules=rows) == []
    landed = {module_name(path) for path in judged_files()}
    assert "breezy.persistence.autonomy.never_landed" not in landed


# ---------------------------------------------------------------------------
# The table itself
# ---------------------------------------------------------------------------


def test_the_writer_table_names_only_known_mechanisms_and_unique_paths() -> None:
    assert {row.mechanism for row in AUTONOMY_FILE_WRITERS} <= WRITE_MECHANISMS
    paths = [row.path for row in AUTONOMY_FILE_WRITERS]
    assert len(paths) == len(set(paths)) == 11


def test_exemptions_are_narrow_and_unique() -> None:
    keys = [(rule.module, rule.function) for rule in WRITE_SITE_ALLOWLIST]
    assert len(keys) == len(set(keys))
    whole_module = {rule.module for rule in WRITE_SITE_ALLOWLIST if rule.function is None}
    assert whole_module == {"breezy.persistence.autonomy.registry_store"}
    assert all(rule.reason for rule in WRITE_SITE_ALLOWLIST)
    named_exemption = [r for r in WRITE_SITE_ALLOWLIST if r.module.endswith("live_orders_gate")]
    assert [(r.function) for r in named_exemption] == ["_verify_ruling_file"]


# ---------------------------------------------------------------------------
# Judged-file predicate (ruling A4-R1) and transitional rows (ruling A4-R4)
# ---------------------------------------------------------------------------


def test_the_judged_predicate_reaches_autonomy_prefixed_packages(tmp_path: Path) -> None:
    src = tmp_path / "src" / "breezy"
    planted = [
        src / "strategy" / "autonomy_capture" / "w.py",
        src / "analysis" / "autonomy_refit" / "w.py",
        src / "persistence" / "autonomy" / "w.py",
    ]
    unjudged = src / "strategy" / "other_pkg" / "w.py"
    for path in [*planted, unjudged]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("import os\ndef f(a, b):\n    os.replace(a, b)\n", encoding="utf-8")
    judged = autonomy_source_files(src, tmp_path / "scripts")
    assert judged == sorted(planted)
    for path in judged:
        sites = unallowed_write_sites(
            str(path), path.read_text(encoding="utf-8"), module="breezy.planted"
        )
        assert [site.detail for site in sites] == ["os.replace"]


def test_the_judged_predicate_excludes_only_the_seam_b_sandbox_package(tmp_path: Path) -> None:
    """Ruling B8-R1: one reasoned exclusion row; siblings stay judged."""
    assert SANDBOX_EXCLUSION_REASON
    src = tmp_path / "src" / "breezy"
    sandbox = src / "runtime" / "autonomy_sandbox" / "w.py"
    siblings = [
        src / "strategy" / "autonomy_capture" / "w.py",
        src / "runtime" / "autonomy_other" / "w.py",
        src / "analysis" / "autonomy_sandbox" / "w.py",
    ]
    for path in [sandbox, *siblings]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("import os\n", encoding="utf-8")
    assert autonomy_source_files(src, tmp_path / "scripts") == sorted(siblings)


def test_a_planted_write_site_in_the_sandbox_is_caught_by_seam_b_own_gate() -> None:
    """Ruling B8-R1: the excluded package is still policed, by ``test_autonomy_write_sites``."""
    module = "self_probe"
    source = (SRC_DIR / "breezy" / "runtime" / "autonomy_sandbox" / f"{module}.py").read_text(
        encoding="utf-8"
    )
    planted = source + "\n\ndef _planted(a, b):\n    os.replace(a, b)\n"
    assert scan_write_sites(module, source) <= set(SHARED_WRITE_SITES)
    assert scan_write_sites(module, planted) != scan_write_sites(module, source)
    assert not scan_write_sites(module, planted) <= set(SHARED_WRITE_SITES)


def test_transitional_rows_name_an_owner_and_a_closing_condition() -> None:
    transitional = [rule for rule in WRITE_SITE_ALLOWLIST if rule.owner or rule.closing]
    assert transitional == []  # the walk_dirs row retired with ensure_dir (ruling A4-R4, seam 6d)
    assert all(rule.owner and rule.closing for rule in transitional)


def test_the_publish_by_link_helper_needs_no_allowlist_row() -> None:
    assert all(rule.function != "_publish_by_link" for rule in WRITE_SITE_ALLOWLIST)


def test_walk_dirs_mkdir_row_retired() -> None:
    from breezy.persistence.autonomy import single_read

    assert callable(single_read.ensure_dir)
    assert all(rule.function != "walk_dirs" for rule in WRITE_SITE_ALLOWLIST)
    path = SRC_DIR / "breezy" / "persistence" / "autonomy" / "single_read.py"
    sites = unallowed_write_sites(
        str(path),
        path.read_text(encoding="utf-8"),
        module="breezy.persistence.autonomy.single_read",
    )
    assert sites == []
    assert _called_names(path, "walk_dirs").isdisjoint({"mkdir", "makedirs"})


def test_a_mkdir_in_walk_dirs_would_be_flagged_without_its_row() -> None:
    planted = "import os\ndef walk_dirs(fd, rel):\n    os.mkdir(rel, 0o700, dir_fd=fd)\n"
    sites = unallowed_write_sites(
        "planted.py", planted, module="breezy.persistence.autonomy.single_read"
    )
    assert [site.detail for site in sites] == ["os.mkdir"]


def _called_names(path: Path, function: str) -> set[str]:
    import ast

    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.FunctionDef) and node.name == function:
            return {
                call.func.attr
                if isinstance(call.func, ast.Attribute)
                else getattr(call.func, "id", "")
                for call in ast.walk(node)
                if isinstance(call, ast.Call)
            }
    raise AssertionError(function)
