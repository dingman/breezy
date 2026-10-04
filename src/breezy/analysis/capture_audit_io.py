"""AUT-1 WP5 stage 3a: the audit's two single-read helpers (design S3-R30, S3-R44).

``read_file`` and ``list_names`` moved out of ``capture_audit_inputs`` unchanged, so a module that
only needs to read below the data root (the AUT-6 contract reader) does not import the whole input
gatherer. Both walk the data root through the ``O_NOFOLLOW`` single-read helpers.
``capture_audit_inputs`` re-exports ``list_names``.
"""

import os
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from breezy.persistence.autonomy.single_read import (
    ReadPolicy,
    SingleReadReason,
    SingleReadRefused,
    open_root,
    read_once_at,
    walk_dirs,
)

__all__ = ["list_names", "read_file"]

_MAX_FILE_BYTES: Final[int] = 64 * 1024 * 1024


def read_file(
    root: Path, rel: Sequence[str], name: str, policy: ReadPolicy = ReadPolicy.STRICT
) -> bytes | None:
    """``name`` below ``root/rel`` through the ``O_NOFOLLOW`` walk, or ``None`` when absent. Any
    other refusal (a symlink, a foreign owner, an oversize file) is raised."""
    rootfd = open_root(root)
    try:
        try:
            dirfd = walk_dirs(rootfd, rel)
        except SingleReadRefused as exc:
            if exc.reason is SingleReadReason.NOT_FOUND:
                return None
            raise
    finally:
        os.close(rootfd)
    try:
        return read_once_at(dirfd, name, max_bytes=_MAX_FILE_BYTES, policy=policy)
    except SingleReadRefused as exc:
        if exc.reason is SingleReadReason.NOT_FOUND:
            return None
        raise
    finally:
        os.close(dirfd)


def list_names(root: Path, rel: Sequence[str]) -> list[str]:
    """The entry names of ``root/rel`` (empty when it is absent), through the nofollow walk."""
    rootfd = open_root(root)
    try:
        try:
            dirfd = walk_dirs(rootfd, rel)
        except SingleReadRefused as exc:
            if exc.reason is SingleReadReason.NOT_FOUND:
                return []
            raise
    finally:
        os.close(rootfd)
    try:
        return sorted(os.listdir(dirfd))
    finally:
        os.close(dirfd)
