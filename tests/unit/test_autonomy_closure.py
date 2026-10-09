"""ARCH-0 seam 3b: the code-identity closure hash (ARCH 4.3; AC 25 'Real machinery, empty pins').

``closure_sha256`` is runtime machinery (stdlib plus ``single_read``). ``closure_from_grimp`` is
gate-only and imports grimp lazily.
"""

from __future__ import annotations

import ast
import hashlib
import os
import time
import tracemalloc
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Final

import pytest

from breezy.persistence.autonomy import closure, closure_manifest
from breezy.persistence.autonomy.closure import (
    PINS_MODULE,
    ClosureUnavailable,
    closure_from_grimp,
    closure_sha256,
)
from tests.support.entry_points import SRC_DIR

RUNTIME_BUDGET_S: Final[float] = 5.0
MEMORY_BUDGET_BYTES: Final[int] = 128 * 1024 * 1024
PKG: Final[str] = "breezy.persistence.autonomy"


def _src(tmp_path: Path, files: Mapping[str, bytes]) -> Path:
    root = tmp_path / "src"
    for rel, data in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return root


_MODS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {"pkg.entry": ("pkg", "pkg.entry", "pkg.helper")}
)
_FILES: Final[Mapping[str, bytes]] = MappingProxyType(
    {"pkg/__init__.py": b"", "pkg/entry.py": b"import pkg.helper\n", "pkg/helper.py": b"X = 1\n"}
)


def _framed(pairs: list[tuple[str, bytes]]) -> str:
    h = hashlib.sha256()
    for name, data in sorted(pairs):
        raw = name.encode()
        h.update(len(raw).to_bytes(4, "big") + raw + len(data).to_bytes(8, "big") + data)
    return h.hexdigest()


def test_closure_hash_is_sha256_over_sorted_name_and_bytes(tmp_path: Path) -> None:
    root = _src(tmp_path, _FILES)
    expected = _framed(
        [("pkg", b""), ("pkg.entry", b"import pkg.helper\n"), ("pkg.helper", b"X = 1\n")]
    )
    assert closure_sha256("pkg.entry", src_root=root, modules=_MODS) == expected


def test_closure_hash_is_independent_of_manifest_order(tmp_path: Path) -> None:
    root = _src(tmp_path, _FILES)
    shuffled = {"pkg.entry": ("pkg.helper", "pkg.entry", "pkg")}
    assert closure_sha256("pkg.entry", src_root=root, modules=shuffled) == closure_sha256(
        "pkg.entry", src_root=root, modules=_MODS
    )


def test_closure_hash_changes_when_any_member_byte_changes(tmp_path: Path) -> None:
    root = _src(tmp_path, _FILES)
    before = closure_sha256("pkg.entry", src_root=root, modules=_MODS)
    (root / "pkg" / "helper.py").write_bytes(b"X = 2\n")
    assert closure_sha256("pkg.entry", src_root=root, modules=_MODS) != before


def test_unknown_component_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ClosureUnavailable):
        closure_sha256("nope", src_root=_src(tmp_path, _FILES), modules=_MODS)


def test_manifest_holds_only_the_reviewed_components_and_refuses_the_rest() -> None:
    """One reviewed row so far: the ``aut6.health`` producer entry (WP3 S6, P6-13)."""
    assert set(closure_manifest.CLOSURE_MODULES) == {"breezy.runtime.autonomy_health_cli"}
    with pytest.raises(ClosureUnavailable):
        closure_sha256(f"{PKG}.veto")


def test_missing_member_file_is_refused_not_skipped(tmp_path: Path) -> None:
    root = _src(tmp_path, {"pkg/__init__.py": b"", "pkg/entry.py": b""})
    with pytest.raises(ClosureUnavailable):
        closure_sha256("pkg.entry", src_root=root, modules=_MODS)


def test_symlinked_member_file_is_refused(tmp_path: Path) -> None:
    root = _src(tmp_path, _FILES)
    (root / "pkg" / "helper.py").unlink()
    (tmp_path / "elsewhere.py").write_bytes(b"X = 1\n")
    os.symlink(tmp_path / "elsewhere.py", root / "pkg" / "helper.py")
    with pytest.raises(ClosureUnavailable):
        closure_sha256("pkg.entry", src_root=root, modules=_MODS)


def test_member_name_with_traversal_is_refused(tmp_path: Path) -> None:
    root = _src(tmp_path, _FILES)
    with pytest.raises(ClosureUnavailable):
        closure_sha256("x", src_root=root, modules={"x": ("pkg", "..", "pkg.entry")})


def test_breezy_root_init_has_no_module_level_imports() -> None:
    # closure_from_grimp adds the root package without following its (function-local) imports.
    tree = ast.parse((SRC_DIR / "breezy" / "__init__.py").read_text(encoding="utf-8"))
    assert [n for n in tree.body if isinstance(n, ast.Import | ast.ImportFrom)] == []


def test_closure_module_never_imports_grimp_at_module_level() -> None:
    tree = ast.parse(Path(closure.__file__).read_text(encoding="utf-8"))
    top = [n for n in tree.body if isinstance(n, ast.Import | ast.ImportFrom)]
    names = {a.name for n in top if isinstance(n, ast.Import) for a in n.names}
    names |= {n.module or "" for n in top if isinstance(n, ast.ImportFrom)}
    assert not any(n.split(".")[0] == "grimp" for n in names)
    lazy = [
        n
        for fn in ast.walk(tree)
        if isinstance(fn, ast.FunctionDef) and fn.name == "closure_from_grimp"
        for n in ast.walk(fn)
        if isinstance(n, ast.Import | ast.ImportFrom)
    ]
    assert lazy, "grimp must be imported lazily inside closure_from_grimp"


# --- closure_from_grimp (gate-only) -------------------------------------------------------


@pytest.fixture(scope="module")
def real_closure_veto() -> tuple[str, ...]:
    return closure_from_grimp(f"{PKG}.veto")


def test_grimp_closure_of_a_leaf_is_itself_plus_ancestor_inits(
    real_closure_veto: tuple[str, ...],
) -> None:
    assert real_closure_veto == ("breezy", "breezy.persistence", PKG, f"{PKG}.veto")


def test_grimp_closure_follows_imports_and_excludes_unrelated() -> None:
    got = closure_from_grimp(f"{PKG}.plugin")
    assert f"{PKG}.veto" in got
    assert f"{PKG}.plugin" in got
    assert f"{PKG}.single_read" not in got
    assert list(got) == sorted(got)


def test_grimp_closure_excludes_pins_even_when_imported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pkg = tmp_path / "zzclosurepkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "entry.py").write_text("from zzclosurepkg import helper, pins\n")
    (pkg / "helper.py").write_text("X = 1\n")
    (pkg / "pins.py").write_text("P = 1\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    got = closure_from_grimp(
        "zzclosurepkg.entry", package="zzclosurepkg", excluded=frozenset({"zzclosurepkg.pins"})
    )
    assert got == ("zzclosurepkg", "zzclosurepkg.entry", "zzclosurepkg.helper")
    assert PINS_MODULE == f"{PKG}.pins"


def test_grimp_closure_of_an_unknown_entry_is_refused() -> None:
    with pytest.raises(ClosureUnavailable):
        closure_from_grimp("breezy.no_such_module_here")


# --- Budget (plan: <= 5 s and <= 128 MB) ---------------------------------------------------


def _every_breezy_module() -> dict[str, tuple[str, ...]]:
    names: list[str] = []
    for path in sorted((SRC_DIR / "breezy").rglob("*.py")):
        rel = path.relative_to(SRC_DIR).with_suffix("")
        parts = rel.parts[:-1] if rel.name == "__init__" else rel.parts
        names.append(".".join(parts))
    return {"breezy": tuple(names)}


def test_closure_hash_runtime_under_budget() -> None:
    # The whole package is a worst case: far larger than any real component closure.
    modules = _every_breezy_module()
    assert len(modules["breezy"]) > 200
    started = time.perf_counter()
    digest = closure_sha256("breezy", src_root=SRC_DIR, modules=modules)
    elapsed = time.perf_counter() - started
    assert len(digest) == 64
    assert elapsed <= RUNTIME_BUDGET_S
    tracemalloc.start()
    try:
        closure_sha256("breezy", src_root=SRC_DIR, modules=modules)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak <= MEMORY_BUDGET_BYTES
