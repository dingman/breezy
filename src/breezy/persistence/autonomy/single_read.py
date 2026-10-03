"""TOCTOU-free directory walk, single-fd read and link-published write (ARCH-0 AC 7).

Every operation is anchored on a directory fd and uses ``O_NOFOLLOW``; no path is
resolved twice. ``write_once`` publishes with ``os.link`` only (no rename fallback),
so an existing destination is never replaced. ``replace_atomic`` is the one
sanctioned overwrite. Refusals raise :class:`SingleReadRefused` with a closed
:class:`SingleReadReason`.

The writability refusal is a mode-bit check, never a probe, so it does not depend
on the uid the process runs as (V30).
"""

from __future__ import annotations

import errno
import os
import secrets
import stat
from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path
from typing import Final

_DIR_FLAGS: Final[int] = os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_READ_FLAGS: Final[int] = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_TEMP_FLAGS: Final[int] = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
_TEMP_PREFIX: Final[str] = ".tmp."
_TEMP_CREATE_MODE: Final[int] = 0o600
_TEMP_TOKEN_BYTES: Final[int] = 8
_GROUP_OTHER_WRITE: Final[int] = stat.S_IWGRP | stat.S_IWOTH
_LINK_UNSUPPORTED_ERRNOS: Final[frozenset[int]] = frozenset(
    {errno.EPERM, errno.EXDEV, errno.EOPNOTSUPP, errno.EMLINK}
)
_READ_CHUNK: Final[int] = 65536
_DEFAULT_DIR_MODE: Final[int] = 0o700


class ReadPolicy(StrEnum):
    """``STRICT`` refuses group-write and other-write bits; ``REPO`` drops the mode check (V5)."""

    STRICT = "strict"
    REPO = "repo"


class SingleReadReason(StrEnum):
    INVALID_NAME = "invalid_name"
    NOT_FOUND = "not_found"
    SYMLINK = "symlink"
    NOT_DIRECTORY = "not_directory"
    NOT_REGULAR = "not_regular"
    WRONG_OWNER = "wrong_owner"
    MODE_TOO_OPEN = "mode_too_open"
    OVERSIZE = "oversize"
    DIR_NOT_WRITABLE = "dir_not_writable"
    LINK_UNSUPPORTED = "link_unsupported"
    IO = "io"


class WriteOutcome(StrEnum):
    WRITTEN = "written"
    EXISTS_EQUAL = "exists_equal"
    EXISTS_DIFFERENT = "exists_different"


class SingleReadRefused(Exception):
    def __init__(self, reason: SingleReadReason, detail: str = "") -> None:
        super().__init__(f"{reason.value}: {detail}" if detail else reason.value)
        self.reason = reason
        self.detail = detail


def _refuse_name(name: str) -> None:
    if name in ("", ".", "..") or "\x00" in name or "/" in name:
        raise SingleReadRefused(SingleReadReason.INVALID_NAME, repr(name))


def _io(exc: OSError, what: str) -> SingleReadRefused:
    return SingleReadRefused(SingleReadReason.IO, f"{what}: {os.strerror(exc.errno or 0)}")


def _open_dir_at(dirfd: int | None, name: str) -> int:
    """Open one directory without following a final symlink; classify the refusal."""
    try:
        if dirfd is None:
            return os.open(name, _DIR_FLAGS)
        return os.open(name, _DIR_FLAGS, dir_fd=dirfd)
    except FileNotFoundError as exc:
        raise SingleReadRefused(SingleReadReason.NOT_FOUND, name) from exc
    except OSError as exc:
        if exc.errno not in (errno.ELOOP, errno.ENOTDIR):
            raise _io(exc, name) from exc
        raise SingleReadRefused(_why_not_directory(dirfd, name), name) from exc


def _why_not_directory(dirfd: int | None, name: str) -> SingleReadReason:
    try:
        info = os.stat(name, dir_fd=dirfd, follow_symlinks=False)
    except OSError:
        return SingleReadReason.NOT_DIRECTORY
    return (
        SingleReadReason.SYMLINK if stat.S_ISLNK(info.st_mode) else SingleReadReason.NOT_DIRECTORY
    )


def _require_owned_dir(fd: int, name: str) -> None:
    info = os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode):
        raise SingleReadRefused(SingleReadReason.NOT_DIRECTORY, name)
    if info.st_uid != os.geteuid():
        raise SingleReadRefused(SingleReadReason.WRONG_OWNER, name)


def open_root(root: Path) -> int:
    """Open the data root as a directory fd (caller closes)."""
    fd = _open_dir_at(None, os.fspath(root))
    try:
        _require_owned_dir(fd, os.fspath(root))
    except BaseException:
        os.close(fd)
        raise
    return fd


def walk_dirs(
    rootfd: int, rel: Sequence[str], *, create: bool, mode: int = _DEFAULT_DIR_MODE
) -> int:
    """One ``openat`` per component; returns an fd the caller closes.

    An empty ``rel`` returns a duplicate of ``rootfd``. Every component must be a
    directory owned by the effective uid and never a symlink.
    """
    for component in rel:
        _refuse_name(component)
    current = os.dup(rootfd)
    try:
        for component in rel:
            if create:
                try:
                    os.mkdir(component, mode, dir_fd=current)
                except FileExistsError:
                    pass
                except OSError as exc:
                    raise _io(exc, component) from exc
            child = _open_dir_at(current, component)
            os.close(current)
            current = child
            _require_owned_dir(current, component)
    except BaseException:
        os.close(current)
        raise
    return current


def _read_fd(fd: int, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    remaining = max_bytes + 1
    while remaining > 0:
        chunk = os.read(fd, min(_READ_CHUNK, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    data = b"".join(chunks)
    if len(data) > max_bytes:
        raise SingleReadRefused(SingleReadReason.OVERSIZE, f"> {max_bytes} bytes")
    return data


def read_once_at(dirfd: int, name: str, *, max_bytes: int, policy: ReadPolicy) -> bytes:
    """Open ``name`` under ``dirfd`` once, check that fd, read at most ``max_bytes``."""
    _refuse_name(name)
    try:
        fd = os.open(name, _READ_FLAGS, dir_fd=dirfd)
    except FileNotFoundError as exc:
        raise SingleReadRefused(SingleReadReason.NOT_FOUND, name) from exc
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise SingleReadRefused(SingleReadReason.SYMLINK, name) from exc
        raise _io(exc, name) from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise SingleReadRefused(SingleReadReason.NOT_REGULAR, name)
        if info.st_uid != os.geteuid():
            raise SingleReadRefused(SingleReadReason.WRONG_OWNER, name)
        if policy is ReadPolicy.STRICT and info.st_mode & _GROUP_OTHER_WRITE:
            raise SingleReadRefused(SingleReadReason.MODE_TOO_OPEN, name)
        try:
            return _read_fd(fd, max_bytes)
        except OSError as exc:
            raise _io(exc, name) from exc
    finally:
        os.close(fd)


def _split(path: Path, root: Path) -> tuple[tuple[str, ...], str]:
    try:
        parts = path.relative_to(root).parts
    except ValueError as exc:
        raise SingleReadRefused(SingleReadReason.INVALID_NAME, "path is outside the root") from exc
    if not parts:
        raise SingleReadRefused(SingleReadReason.INVALID_NAME, "path is the root")
    return parts[:-1], parts[-1]


def _require_writable_dir(dirfd: int) -> None:
    if os.fstat(dirfd).st_mode & stat.S_IWUSR == 0:
        raise SingleReadRefused(SingleReadReason.DIR_NOT_WRITABLE)


def _compare_existing(dirfd: int, name: str, data: bytes) -> WriteOutcome | None:
    """``None`` when the destination is absent; otherwise EQUAL or DIFFERENT (fail-closed)."""
    try:
        existing = read_once_at(dirfd, name, max_bytes=len(data), policy=ReadPolicy.REPO)
    except SingleReadRefused as exc:
        if exc.reason is SingleReadReason.NOT_FOUND:
            return None
        if exc.reason is SingleReadReason.IO:
            raise
        return WriteOutcome.EXISTS_DIFFERENT
    return WriteOutcome.EXISTS_EQUAL if existing == data else WriteOutcome.EXISTS_DIFFERENT


def _write_temp(dirfd: int, data: bytes, mode: int) -> str:
    """Create, fill and fsync a ``.tmp.<16 hex>`` file; always cleans up after itself on error."""
    temp = f"{_TEMP_PREFIX}{secrets.token_hex(_TEMP_TOKEN_BYTES)}"
    fd = os.open(temp, _TEMP_FLAGS, _TEMP_CREATE_MODE, dir_fd=dirfd)
    try:
        os.fchmod(fd, mode)
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view) :]
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        _unlink_quietly(dirfd, temp)
        raise
    os.close(fd)
    return temp


def _unlink_quietly(dirfd: int, name: str) -> None:
    try:
        os.unlink(name, dir_fd=dirfd)
    except FileNotFoundError:
        pass


def write_once(path: Path, data: bytes, *, root: Path, mode: int) -> WriteOutcome:
    """Publish ``data`` at ``path`` only if nothing is there (``os.link``, no rename)."""
    parent_rel, name = _split(path, root)
    rootfd = open_root(root)
    try:
        dirfd = walk_dirs(rootfd, parent_rel, create=False)
    finally:
        os.close(rootfd)
    try:
        existing = _compare_existing(dirfd, name, data)
        if existing is not None:
            return existing
        _require_writable_dir(dirfd)
        return _publish_by_link(dirfd, name, data, mode)
    finally:
        os.close(dirfd)


def _publish_by_link(dirfd: int, name: str, data: bytes, mode: int) -> WriteOutcome:
    try:
        temp = _write_temp(dirfd, data, mode)
    except OSError as exc:
        raise _io(exc, name) from exc
    try:
        os.link(temp, name, src_dir_fd=dirfd, dst_dir_fd=dirfd, follow_symlinks=False)
    except FileExistsError:
        return _compare_existing(dirfd, name, data) or WriteOutcome.EXISTS_DIFFERENT
    except OSError as exc:
        if exc.errno in _LINK_UNSUPPORTED_ERRNOS:
            raise SingleReadRefused(SingleReadReason.LINK_UNSUPPORTED, name) from exc
        raise _io(exc, name) from exc
    finally:
        _unlink_quietly(dirfd, temp)
        _fsync_dir(dirfd)
    return WriteOutcome.WRITTEN


def _fsync_dir(dirfd: int) -> None:
    try:
        os.fsync(dirfd)
    except OSError as exc:
        raise _io(exc, "directory fsync") from exc


def replace_atomic(path: Path, data: bytes, *, root: Path, mode: int) -> None:
    """Atomically replace (or create) ``path`` with ``data`` via a same-directory temp."""
    parent_rel, name = _split(path, root)
    _refuse_name(name)
    rootfd = open_root(root)
    try:
        dirfd = walk_dirs(rootfd, parent_rel, create=False)
    finally:
        os.close(rootfd)
    try:
        _require_writable_dir(dirfd)
        try:
            temp = _write_temp(dirfd, data, mode)
        except OSError as exc:
            raise _io(exc, name) from exc
        try:
            os.replace(temp, name, src_dir_fd=dirfd, dst_dir_fd=dirfd)
        except OSError as exc:
            raise _io(exc, name) from exc
        finally:
            _unlink_quietly(dirfd, temp)
            _fsync_dir(dirfd)
    finally:
        os.close(dirfd)
