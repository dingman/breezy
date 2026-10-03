"""Code-identity closure hash (ARCH 4.3; ARCH-0 AC 25).

``closure_sha256`` is runtime machinery: it hashes the sorted ``(module name, bytes)`` of a
component's manifest closure, reading each file through ``single_read`` (one fd, no symlink).
``closure_from_grimp`` is gate-only: it derives that closure from the import graph (grimp, the
engine behind ``lint-imports``), imported lazily so runtime never loads it. Importing a module
runs its ancestors' ``__init__.py`` first, which grimp does not model, so ancestors are added.
The root package is added but not followed: its only import is function-local (grimp counts
those as edges, which would drag the whole CLI into every closure).
``pins.py`` is excluded from every closure (a pin cannot hash itself).
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from breezy.persistence.autonomy.closure_manifest import CLOSURE_MODULES
from breezy.persistence.autonomy.single_read import (
    ReadPolicy,
    SingleReadReason,
    SingleReadRefused,
    open_root,
    read_once_at,
    walk_dirs,
)

__all__ = ["PINS_MODULE", "ClosureUnavailable", "closure_from_grimp", "closure_sha256"]

PINS_MODULE: Final[str] = "breezy.persistence.autonomy.pins"
_PACKAGE: Final[str] = "breezy"
_MODULE_MAX_BYTES: Final[int] = 4 * 1024 * 1024
_SRC_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
_NAME_LEN_BYTES: Final[int] = 4
_DATA_LEN_BYTES: Final[int] = 8


class ClosureUnavailable(Exception):
    """The closure cannot be established; callers treat the component as unpinned."""


def _read_in(rootfd: int, directory: list[str], filename: str) -> bytes:
    dirfd = walk_dirs(rootfd, directory, create=False)
    try:
        return read_once_at(dirfd, filename, max_bytes=_MODULE_MAX_BYTES, policy=ReadPolicy.REPO)
    finally:
        os.close(dirfd)


def _read_module(rootfd: int, module: str) -> bytes:
    """``a/b.py`` else ``a/b/__init__.py``; anything but absence is a refusal."""
    parts = module.split(".")
    try:
        try:
            return _read_in(rootfd, parts[:-1], f"{parts[-1]}.py")
        except SingleReadRefused as exc:
            if exc.reason is not SingleReadReason.NOT_FOUND:
                raise
        return _read_in(rootfd, parts, "__init__.py")
    except SingleReadRefused as exc:
        raise ClosureUnavailable(f"{module}: {exc.reason.value}") from exc


def closure_sha256(
    component: str,
    *,
    src_root: Path | None = None,
    modules: Mapping[str, tuple[str, ...]] = CLOSURE_MODULES,
) -> str:
    """sha256 over the sorted, length-framed ``(module name, bytes)`` of ``component``'s closure."""
    members = modules.get(component)
    if members is None:
        raise ClosureUnavailable(f"{component}: not in the closure manifest")
    try:
        rootfd = open_root(src_root if src_root is not None else _SRC_ROOT)
    except SingleReadRefused as exc:
        raise ClosureUnavailable(f"<src root>: {exc.reason.value}") from exc
    digest = hashlib.sha256()
    try:
        for name in sorted(members):
            raw = name.encode()
            data = _read_module(rootfd, name)
            digest.update(len(raw).to_bytes(_NAME_LEN_BYTES, "big") + raw)
            digest.update(len(data).to_bytes(_DATA_LEN_BYTES, "big") + data)
    finally:
        os.close(rootfd)
    return digest.hexdigest()


def _ancestors(module: str) -> list[str]:
    parts = module.split(".")
    return [".".join(parts[:i]) for i in range(1, len(parts))]


def closure_from_grimp(
    entry: str,
    *,
    package: str = _PACKAGE,
    excluded: frozenset[str] = frozenset({PINS_MODULE}),
) -> tuple[str, ...]:
    """Sorted transitive ``package.*`` import closure of ``entry`` (gate-only; lazy grimp)."""
    import grimp

    graph = grimp.build_graph(package)
    if entry not in graph.modules:
        raise ClosureUnavailable(f"{entry}: not in the import graph")
    seen: set[str] = set()
    pending = [entry]
    while pending:
        module = pending.pop()
        if module in seen or module in excluded:
            continue
        seen.add(module)
        if module == package:
            continue  # lazy-only root __init__; a test pins that it has no top-level import
        pending.extend(_ancestors(module))
        pending.extend(sorted(graph.find_modules_directly_imported_by(module)))
    return tuple(sorted(m for m in seen if m in graph.modules))
