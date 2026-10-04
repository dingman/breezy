"""ARCH-0 seam B (WP-B2b-3): the shared write-site allowlist and the code manifest.

Plan r5 AC-4 / B-R3 (erratum E-7e(a)). ``SHARED_WRITE_SITES`` is the exact set of
(module, function, call) write sites the shared sandbox modules own, so a
consumer's read-only-closure lint (AUT-6 ruling AC6: an *allowlist* of read
calls, everything else is a write) can admit those sites and no others.
``WRAPPER_CODE_FILES`` is the V11 manifest: the wrapper script plus every
package module.
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

from breezy.runtime.autonomy_sandbox import write_sites
from breezy.runtime.autonomy_sandbox.write_sites import (
    SHARED_WRITE_MODULES,
    SHARED_WRITE_SITES,
    WRAPPER_CODE_FILES,
    WriteSite,
)
from tests.support.autonomy_write_sites import (
    cache_dir_is_own_module_constant,
    scan_write_sites,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / "src" / "breezy" / "runtime" / "autonomy_sandbox"


def _sites(source: str) -> set[tuple[str, str]]:
    found = scan_write_sites("m", textwrap.dedent(source))
    return {(site.function, site.call) for site in found}


def _call(source: str) -> tuple[ast.Call, ast.Module]:
    tree = ast.parse(textwrap.dedent(source))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and _is_snapshot(n)]
    assert len(calls) == 1
    return calls[0], tree


def _is_snapshot(node: ast.Call) -> bool:
    return isinstance(node.func, ast.Name) and node.func.id == "snapshot"


# --- the exact allowlist -----------------------------------------------------------


def test_shared_write_sites_equal_package_scan() -> None:
    scanned: set[WriteSite] = set()
    for module in SHARED_WRITE_MODULES:
        source = (PACKAGE_DIR / f"{module}.py").read_text(encoding="utf-8")
        scanned |= scan_write_sites(module, source)
    assert scanned == set(SHARED_WRITE_SITES)
    assert SHARED_WRITE_SITES, "the self-probe owns write sites; an empty set means a blind scan"
    assert {site.module for site in SHARED_WRITE_SITES} <= set(SHARED_WRITE_MODULES)


def test_write_sites_are_a_frozenset_of_exact_triples() -> None:
    assert isinstance(SHARED_WRITE_SITES, frozenset)
    for site in SHARED_WRITE_SITES:
        assert isinstance(site, WriteSite)
        assert site.module and site.function and site.call


def test_every_shared_write_module_exists_in_the_package() -> None:
    for module in SHARED_WRITE_MODULES:
        assert (PACKAGE_DIR / f"{module}.py").is_file()


def test_the_wrapper_and_binder_modules_are_not_write_site_owners() -> None:
    assert {"bwrap", "binds", "run_mounts", "table", "unit_lint"}.isdisjoint(SHARED_WRITE_MODULES)


# --- the AC6 read allowlist, with positive controls --------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "os.open(p, os.O_RDONLY | os.O_CLOEXEC)",
        "os.open(p, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)",
        "os.open(p, os.O_PATH | os.O_NOFOLLOW)",
        "open(p)",
        "open(p, 'r')",
        "open(p, mode='rb')",
        "os.stat(p)",
        "os.lstat(p)",
        "os.fstat(fd)",
        "os.statvfs(p)",
        "os.scandir(p)",
        "os.listdir(p)",
        "os.readlink(p)",
        "os.access(p, os.R_OK)",
        "os.close(fd)",
        "os.getpid()",
        "os.geteuid()",
        "os.path.realpath(p)",
        "os.environ.get('X')",
        "sqlite3.connect('file:x?mode=ro', uri=True)",
        "len(x)",
        "sorted(x)",
        "str(x).replace('a', 'b')",
        "Path(p).read_text()",
        "Path(p).is_dir()",
        "Path(p).iterdir()",
    ],
)
def test_allowlisted_reads_are_not_write_sites(line: str) -> None:
    source = f"import os, sqlite3\nfrom pathlib import Path\ndef f(p, fd, x):\n    {line}\n"
    assert _sites(source) == set(), line


@pytest.mark.parametrize(
    ("line", "call"),
    [
        ("os.open(p, os.O_TMPFILE | os.O_WRONLY, 0o600)", "os.open"),
        ("os.open(p, os.O_RDONLY | os.O_CREAT)", "os.open"),
        ("os.open(p, flags)", "os.open"),
        ("open(p, 'w')", "open"),
        ("open(p, mode='ab')", "open"),
        ("os.truncate(p, 0)", "os.truncate"),
        ("os.chmod(p, 0)", "os.chmod"),
        ("os.utime(p)", "os.utime"),
        ("os.unlink(p)", "os.unlink"),
        ("os.mkdir(p)", "os.mkdir"),
        ("os.execv(p, [])", "os.execv"),
        ("shutil.rmtree(p)", "shutil.rmtree"),
        ("subprocess.run([p])", "subprocess.run"),
        ("sqlite3.connect(p)", "sqlite3.connect"),
        ("Path(p).write_text('x')", "write_text"),
        ("Path(p).write_bytes(b'x')", "write_bytes"),
        ("Path(p).mkdir()", "mkdir"),
        ("Path(p).touch()", "touch"),
        ("Path(p).unlink()", "unlink"),
        ("Path(p).open('w')", "open"),
        ("exec(x)", "exec"),
        ("eval(x)", "eval"),
    ],
)
def test_everything_else_is_a_write_site(line: str, call: str) -> None:
    source = (
        "import os, shutil, sqlite3, subprocess\n"
        "from pathlib import Path\n"
        f"def f(p, fd, x, flags):\n    {line}\n"
    )
    assert _sites(source) == {("f", call)}, line


def test_scan_follows_import_aliases() -> None:
    source = """
        from os import unlink as rm
        import os as o
        def f(p):
            rm(p)
            o.chmod(p, 0)
    """
    assert _sites(source) == {("f", "os.unlink"), ("f", "os.chmod")}


def test_scan_names_the_enclosing_function_and_method() -> None:
    source = """
        import os
        def outer(p):
            def inner():
                os.unlink(p)
            return inner
        class C:
            def m(self, p):
                os.unlink(p)
        os.unlink('x')
    """
    assert _sites(source) == {
        ("outer.inner", "os.unlink"),
        ("C.m", "os.unlink"),
        ("<module>", "os.unlink"),
    }


def test_scan_collapses_repeats_of_one_site() -> None:
    source = "import os\ndef f(p):\n    os.unlink(p)\n    os.unlink(p)\n"
    assert len(scan_write_sites("m", source)) == 1


# --- cache_dir_is_own_module_constant (B-R2(a)) ------------------------------------


def test_cache_dir_predicate_accepts_module_final_constant() -> None:
    call, tree = _call(
        """
        from typing import Final
        import typing
        _CACHE: Final = "x"
        OTHER: typing.Final[str] = "y"
        def run():
            snapshot(cache_dir=_CACHE)
        """
    )
    assert cache_dir_is_own_module_constant(call, tree) is True
    call, tree = _call(
        """
        import typing
        OTHER: typing.Final[str] = "y"
        def run():
            snapshot(take_flock=False, cache_dir=OTHER)
        """
    )
    assert cache_dir_is_own_module_constant(call, tree) is True


@pytest.mark.parametrize(
    "body",
    [
        "snapshot(cache_dir='/tmp/x')",
        "snapshot(cache_dir=f'/tmp/{x}')",
        "snapshot(cache_dir=Path('/tmp/x'))",
        "snapshot(cache_dir=other.CACHE)",
        "snapshot(cache_dir=self.cache)",
        "snapshot(cache_dir=_CACHE / 'x')",
        "snapshot(cache_dir=cache_dir_param)",
        "snapshot(_CACHE)",
        "snapshot(take_flock=False)",
        "snapshot(**kw)",
    ],
)
def test_cache_dir_predicate_rejects_literal_param_attribute_and_call(body: str) -> None:
    call, tree = _call(
        f"""
        from typing import Final
        _CACHE: Final = "x"
        def run(cache_dir_param, kw, self, other, x):
            {body}
        """
    )
    assert cache_dir_is_own_module_constant(call, tree) is False, body


def test_cache_dir_predicate_rejects_a_non_final_module_variable() -> None:
    call, tree = _call(
        """
        _CACHE = "x"
        def run():
            snapshot(cache_dir=_CACHE)
        """
    )
    assert cache_dir_is_own_module_constant(call, tree) is False


def test_cache_dir_predicate_rejects_a_local_shadowing_the_constant() -> None:
    call, tree = _call(
        """
        from typing import Final
        _CACHE: Final = "x"
        def run(arg):
            _CACHE = arg
            snapshot(cache_dir=_CACHE)
        """
    )
    assert cache_dir_is_own_module_constant(call, tree) is False
    call, tree = _call(
        """
        from typing import Final
        _CACHE: Final = "x"
        def run(_CACHE):
            snapshot(cache_dir=_CACHE)
        """
    )
    assert cache_dir_is_own_module_constant(call, tree) is False


def test_cache_dir_predicate_rejects_a_constant_imported_from_elsewhere() -> None:
    call, tree = _call(
        """
        from elsewhere import _CACHE
        def run():
            snapshot(cache_dir=_CACHE)
        """
    )
    assert cache_dir_is_own_module_constant(call, tree) is False


# --- WRAPPER_CODE_FILES (V11) ------------------------------------------------------


def test_wrapper_code_files_manifest_covers_package() -> None:
    expected = ["deploy/systemd/breezy-autonomy-bwrap"] + sorted(
        path.relative_to(REPO_ROOT).as_posix() for path in PACKAGE_DIR.glob("*.py")
    )
    assert list(WRAPPER_CODE_FILES) == expected
    for rel in WRAPPER_CODE_FILES:
        assert (REPO_ROOT / rel).is_file(), rel
        assert not rel.startswith("/")


def test_wrapper_code_files_names_the_modules_this_work_package_adds() -> None:
    names = {Path(rel).name for rel in WRAPPER_CODE_FILES}
    assert {"self_probe.py", "selftest_cli.py", "write_sites.py", "bwrap.py"} <= names
    assert "__pycache__" not in "".join(WRAPPER_CODE_FILES)


def test_module_exports_are_final_constants() -> None:
    tree = ast.parse(Path(write_sites.__file__).read_text(encoding="utf-8"))
    final = {
        node.target.id
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and "Final" in ast.unparse(node.annotation)
    }
    assert {"SHARED_WRITE_SITES", "SHARED_WRITE_MODULES", "WRAPPER_CODE_FILES"} <= final


# --- wal_snapshot's own sites (WP-B3) ----------------------------------------------


def test_wal_snapshot_is_a_shared_write_module_with_sites() -> None:
    assert "wal_snapshot" in SHARED_WRITE_MODULES
    own = {site for site in SHARED_WRITE_SITES if site.module == "wal_snapshot"}
    assert own, "the cache copy writes; an empty set means a blind scan"
    assert {s.function for s in own} >= {
        "_make_snap_dir",
        "_create_copy",
        "_recover",
        "_remove_tree",
    }


def test_wal_snapshot_never_writes_through_its_source_readers_or_the_ro_connection() -> None:
    """Fingerprinting, the source opens and the read-only connection are not write sites."""
    functions = {s.function for s in SHARED_WRITE_SITES if s.module == "wal_snapshot"}
    assert functions.isdisjoint(
        {
            "_fingerprint",
            "_open_source",
            "_open_source_dir",
            "_acquire_intent_lock",
            "_open_cache_dir",
            "connect_snapshot_readonly",
            "exec_store_paths",
        }
    )
    assert ("wal_snapshot", "_recover", "sqlite3.connect") in {
        (s.module, s.function, s.call) for s in SHARED_WRITE_SITES
    }
