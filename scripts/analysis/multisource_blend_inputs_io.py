"""F13 Phase A feature build: write-once, all-or-nothing output of a set of files.

Split out of ``multisource_blend_features_build.py`` (behaviour-neutral): every file of the set is
written to a temp name, then hard-linked into place so an existing target is never replaced; a
failure removes whatever this call created.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from scripts.analysis.multisource_blend_inputs_anchors import BuildRefusal

__all__ = ["write_set"]


def _tmp_name(path: Path) -> Path:
    return path.with_name(path.name + ".tmp")


def _stage(path: Path, data: bytes) -> Path:
    """Write ``data`` to ``<path>.tmp`` (a stale one from an interrupted run is replaced)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_name(path)
    tmp.unlink(missing_ok=True)
    with tmp.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    return tmp


def _publish(staged: Sequence[tuple[Path, Path]]) -> None:
    """Hard-link each temp file to its target: an existing target is never replaced (O_EXCL-like).

    ``os.link`` fails with ``FileExistsError`` when the target appeared after ``_guard_outputs``;
    that is a refusal, and every target this call already published is removed again.
    """
    published: list[Path] = []
    try:
        for tmp, path in staged:
            try:
                os.link(tmp, path)
            except FileExistsError as exc:
                raise BuildRefusal(f"{path} already exists; outputs are write-once") from exc
            published.append(path)
    except BaseException:
        for path in published:  # only the links this call created
            path.unlink(missing_ok=True)
        raise
    for tmp, _path in staged:
        tmp.unlink(missing_ok=True)


def write_set(items: Sequence[tuple[Path, bytes]]) -> None:
    """Write every file to a temp name, then rename the set; a failure leaves none of them."""
    staged: list[tuple[Path, Path]] = []
    try:
        for path, data in items:
            tmp = _tmp_name(path)
            staged.append((tmp, path))  # registered first so a partial write is cleaned too
            _stage(path, data)
        _publish(staged)
    except BaseException:
        for tmp, _path in staged:
            tmp.unlink(missing_ok=True)
        raise
