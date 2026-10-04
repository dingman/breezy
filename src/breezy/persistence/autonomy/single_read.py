"""TOCTOU-free directory walk, single-fd read and link-published write (ARCH-0 AC 7).

Every operation is anchored on a directory fd and uses ``O_NOFOLLOW``; no path is
resolved twice. ``write_once`` publishes with ``os.link`` only (no rename fallback),
so an existing destination is never replaced. ``replace_atomic`` is the one
sanctioned overwrite. Refusals raise :class:`SingleReadRefused` with a closed
:class:`SingleReadReason`; ``write_once`` returns only ``WRITTEN`` or
``EXISTS_EQUAL`` and raises ``EXISTS_DIFFERENT`` for every other occupied
destination.

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
_TMPFILE_FLAGS: Final[int] = os.O_TMPFILE | os.O_WRONLY | os.O_CLOEXEC
_TMPFILE_UNSUPPORTED_ERRNOS: Final[frozenset[int]] = frozenset(
    {errno.EOPNOTSUPP, errno.EISDIR, errno.EINVAL}
)
_PROC_SELF_FD: Final = "/proc/self/fd"
_READ_CHUNK: Final[int] = 65536
_DEFAULT_DIR_MODE: Final[int] = 0o700
_PERMISSION_BITS: Final[int] = 0o777
_ROOT_LABEL: Final[str] = "<root>"

__all__ = [
    "ReadPolicy",
    "SingleReadReason",
    "SingleReadRefused",
    "WriteOutcome",
    "ensure_dir",
    "open_root",
    "read_once_at",
    "replace_atomic",
    "walk_dirs",
    "write_once",
    "write_once_tmpfile",
]


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
    EXISTS_DIFFERENT = "exists_different"
    INVALID_MODE = "invalid_mode"
    TMPFILE_UNSUPPORTED = "tmpfile_unsupported"


class WriteOutcome(StrEnum):
    """Successful ``write_once`` results; every other occupied destination raises."""

    WRITTEN = "written"
    EXISTS_EQUAL = "exists_equal"


class SingleReadRefused(Exception):
    """A single-read or link-write refusal; ``reason`` is machine-readable."""

    def __init__(self, reason: SingleReadReason, detail: str = "") -> None:
        super().__init__(f"{reason.value}: {detail}" if detail else reason.value)
        self.reason = reason
        self.detail = detail


def _refuse_name(name: str) -> None:
    if name in ("", ".", "..") or "\x00" in name or "/" in name:
        raise SingleReadRefused(SingleReadReason.INVALID_NAME, repr(name))


def _io(exc: OSError, what: str) -> SingleReadRefused:
    return SingleReadRefused(SingleReadReason.IO, f"{what}: {os.strerror(exc.errno or 0)}")


def _refuse_mode(mode: int) -> None:
    if mode & ~_PERMISSION_BITS:
        raise SingleReadRefused(SingleReadReason.INVALID_MODE, oct(mode))


def _open_dir_at(dirfd: int | None, name: str, label: str | None = None) -> int:
    """Open one directory without following a final symlink; classify the refusal.

    ``label`` replaces ``name`` in refusal details (used to keep the root path out).
    """
    shown = name if label is None else label
    try:
        if dirfd is None:
            return os.open(name, _DIR_FLAGS)
        return os.open(name, _DIR_FLAGS, dir_fd=dirfd)
    except FileNotFoundError as exc:
        raise SingleReadRefused(SingleReadReason.NOT_FOUND, shown) from exc
    except OSError as exc:
        if exc.errno not in (errno.ELOOP, errno.ENOTDIR):
            raise _io(exc, shown) from exc
        raise SingleReadRefused(_why_not_directory(dirfd, name), shown) from exc


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
    """Open the data root as a directory fd (caller closes).

    The ancestors of ``root`` are trusted: only the final component is opened with
    ``O_NOFOLLOW`` and ownership-checked. Refusal details say ``<root>``, never the path.
    """
    fd = _open_dir_at(None, os.fspath(root), _ROOT_LABEL)
    try:
        _require_owned_dir(fd, _ROOT_LABEL)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _descend(parent: int, name: str) -> int:
    """Open the child directory ``name`` of ``parent`` and check its ownership.

    ``parent`` stays open (the caller closes it); on a refusal the child is closed.
    """
    child = _open_dir_at(parent, name)
    try:
        _require_owned_dir(child, name)
    except BaseException:
        os.close(child)
        raise
    return child


def walk_dirs(rootfd: int, rel: Sequence[str]) -> int:
    """One ``openat`` per component; returns an fd the caller closes. Never creates.

    An empty ``rel`` returns a duplicate of ``rootfd``. Every component must be a
    directory owned by the effective uid and never a symlink. Creation is
    :func:`ensure_dir`'s alone (ruling A4-R4).
    """
    for component in rel:
        _refuse_name(component)
    current = os.dup(rootfd)
    try:
        for component in rel:
            child = _descend(current, component)
            os.close(current)
            current = child
    except BaseException:
        os.close(current)
        raise
    return current


def _is_absent(parent: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return True
    except OSError:
        return False  # let the open classify it
    return False


def _fsync_dir(dirfd: int, what: str) -> None:
    try:
        os.fsync(dirfd)
    except OSError as exc:
        raise _io(exc, what) from exc


def ensure_dir(rootfd: int, rel: Sequence[str], *, mode: int = _DEFAULT_DIR_MODE) -> int:
    """``walk_dirs`` that creates each missing component: the one directory creator (A4-R4).

    Existing components are only walked, so their modes are left alone and a path of
    existing directories succeeds even through read-only ones. A missing component in a
    parent without the owner-write bit is refused ``DIR_NOT_WRITABLE`` (a mode-bit check,
    V30), never created. The parent is fsynced after each ``mkdir`` it performed (A6d-A2 L1).
    Returns an fd the caller closes.
    """
    _refuse_mode(mode)
    for component in rel:
        _refuse_name(component)
    current = os.dup(rootfd)
    try:
        for component in rel:
            if _is_absent(current, component):
                _require_writable_dir(current)
                try:
                    os.mkdir(component, mode, dir_fd=current)
                except FileExistsError:
                    pass  # a concurrent creator won; the walk below validates it
                except OSError as exc:
                    raise _io(exc, component) from exc
                else:
                    _fsync_dir(current, "directory fsync")
            child = _descend(current, component)
            os.close(current)
            current = child
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
    _refuse_name(parts[-1])
    return parts[:-1], parts[-1]


def _require_writable_dir(dirfd: int) -> None:
    if os.fstat(dirfd).st_mode & stat.S_IWUSR == 0:
        raise SingleReadRefused(SingleReadReason.DIR_NOT_WRITABLE)


def _compare_existing(dirfd: int, name: str, data: bytes) -> bool | None:
    """``None`` when absent, ``True`` when equal; raises ``EXISTS_DIFFERENT`` otherwise.

    Different bytes (including a larger file), a symlink or a non-regular destination
    become ``EXISTS_DIFFERENT``; ``WRONG_OWNER`` and ``IO`` propagate as themselves.
    """
    try:
        existing = read_once_at(dirfd, name, max_bytes=len(data), policy=ReadPolicy.REPO)
    except SingleReadRefused as exc:
        if exc.reason is SingleReadReason.NOT_FOUND:
            return None
        if exc.reason in (
            SingleReadReason.SYMLINK,
            SingleReadReason.NOT_REGULAR,
            SingleReadReason.OVERSIZE,  # larger than ``data`` is simply different content
        ):
            raise SingleReadRefused(SingleReadReason.EXISTS_DIFFERENT, name) from exc
        raise
    if existing != data:
        raise SingleReadRefused(SingleReadReason.EXISTS_DIFFERENT, name)
    return True


def _cleanup_temp(dirfd: int, temp: str, primary: BaseException) -> None:
    """Failure-path unlink: a cleanup error is attached to ``primary``, never raised."""
    try:
        os.unlink(temp, dir_fd=dirfd)
    except FileNotFoundError:
        pass
    except OSError as exc:
        primary.add_note(f"cleanup of {temp} failed: {os.strerror(exc.errno or 0)}")


def _write_temp(dirfd: int, data: bytes, mode: int) -> str:
    """Create, fill and fsync a ``.tmp.<16 hex>`` file; on any failure no temp or fd remains."""
    temp = f"{_TEMP_PREFIX}{secrets.token_hex(_TEMP_TOKEN_BYTES)}"
    fd = os.open(temp, _TEMP_FLAGS, _TEMP_CREATE_MODE, dir_fd=dirfd)
    try:
        os.fchmod(fd, mode)
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view) :]
        os.fsync(fd)
        closing, fd = fd, -1
        os.close(closing)
    except BaseException as primary:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError as exc:
                primary.add_note(f"close of {temp} failed: {os.strerror(exc.errno or 0)}")
        _cleanup_temp(dirfd, temp, primary)
        raise
    return temp


def _finish(dirfd: int, temp: str, *, sync_dir: bool) -> None:
    """Success-path tail: unlink the temp, then fsync the directory (both always attempted).

    The first failure is raised as ``IO``. After a successful link the destination
    already exists, so a retry returns ``EXISTS_EQUAL``.
    """
    errors: list[SingleReadRefused] = []
    try:
        os.unlink(temp, dir_fd=dirfd)
    except FileNotFoundError:
        pass
    except OSError as exc:
        errors.append(_io(exc, "temp unlink"))
    if sync_dir:
        try:
            os.fsync(dirfd)
        except OSError as exc:
            errors.append(_io(exc, "directory fsync"))
    if errors:
        for extra in errors[1:]:
            errors[0].add_note(str(extra))
        raise errors[0]


def _open_parent(path: Path, root: Path) -> tuple[int, str]:
    parent_rel, name = _split(path, root)
    rootfd = open_root(root)
    try:
        return walk_dirs(rootfd, parent_rel), name
    finally:
        os.close(rootfd)


def write_once(path: Path, data: bytes, *, root: Path, mode: int) -> WriteOutcome:
    """Publish ``data`` at ``path`` only if nothing is there (``os.link``, no rename).

    Returns ``WRITTEN`` or ``EXISTS_EQUAL``. Different bytes, a symlink, FIFO,
    directory or any other non-regular destination raise ``EXISTS_DIFFERENT``. If the
    final directory fsync fails after a successful link, ``IO`` is raised; a retry then
    returns ``EXISTS_EQUAL``.
    """
    _refuse_mode(mode)
    dirfd, name = _open_parent(path, root)
    try:
        if _compare_existing(dirfd, name, data):
            return WriteOutcome.EXISTS_EQUAL
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
        outcome = _link_temp(dirfd, temp, name, data)
    except BaseException as primary:
        _cleanup_temp(dirfd, temp, primary)
        raise
    _finish(dirfd, temp, sync_dir=outcome is WriteOutcome.WRITTEN)
    return outcome


def _link_temp(dirfd: int, temp: str, name: str, data: bytes) -> WriteOutcome:
    try:
        os.link(temp, name, src_dir_fd=dirfd, dst_dir_fd=dirfd, follow_symlinks=False)
    except FileExistsError as exc:
        if _compare_existing(dirfd, name, data):  # the winner's bytes equal ours
            return WriteOutcome.EXISTS_EQUAL
        raise SingleReadRefused(SingleReadReason.EXISTS_DIFFERENT, name) from exc
    except OSError as exc:
        if exc.errno in _LINK_UNSUPPORTED_ERRNOS:
            raise SingleReadRefused(SingleReadReason.LINK_UNSUPPORTED, name) from exc
        raise _io(exc, name) from exc
    return WriteOutcome.WRITTEN


def replace_atomic(path: Path, data: bytes, *, root: Path, mode: int) -> None:
    """Atomically replace (or create) ``path`` with ``data`` via a same-directory temp.

    There is no outcome to report: success returns ``None`` and every refusal raises.
    A failure after the replace (temp unlink or directory fsync) raises ``IO`` with the
    new bytes already in place.
    """
    _refuse_mode(mode)
    dirfd, name = _open_parent(path, root)
    try:
        _require_writable_dir(dirfd)
        try:
            temp = _write_temp(dirfd, data, mode)
        except OSError as exc:
            raise _io(exc, name) from exc
        try:
            os.replace(temp, name, src_dir_fd=dirfd, dst_dir_fd=dirfd)
        except OSError as exc:
            refusal = _io(exc, name)
            _cleanup_temp(dirfd, temp, refusal)
            raise refusal from exc
        _finish(dirfd, temp, sync_dir=True)
    finally:
        os.close(dirfd)


def write_once_tmpfile(path: Path, data: bytes, *, root: Path, mode: int) -> WriteOutcome:
    """``write_once`` with no visible temporary name (AUT-6 r15 AC1; ruling A5b-R4).

    The bytes are written to an unnamed ``O_TMPFILE`` inode, fsynced, and linked into place through
    ``/proc/self/fd``; the directory is then fsynced. ``EXISTS_EQUAL`` / ``EXISTS_DIFFERENT``
    follow ``write_once``. A filesystem without ``O_TMPFILE``, or a missing ``/proc/self/fd``,
    raises ``TMPFILE_UNSUPPORTED`` and writes nothing; there is deliberately no named-temp fallback.
    """
    _refuse_mode(mode)
    dirfd, name = _open_parent(path, root)
    try:
        if _compare_existing(dirfd, name, data):
            return WriteOutcome.EXISTS_EQUAL
        _require_writable_dir(dirfd)
        try:
            fd = os.open(".", _TMPFILE_FLAGS, _TEMP_CREATE_MODE, dir_fd=dirfd)
        except OSError as exc:
            if exc.errno in _TMPFILE_UNSUPPORTED_ERRNOS:
                raise SingleReadRefused(SingleReadReason.TMPFILE_UNSUPPORTED, name) from exc
            raise _io(exc, name) from exc
        try:
            os.fchmod(fd, mode)
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view) :]
            os.fsync(fd)
            try:
                os.link(
                    f"{_PROC_SELF_FD}/{fd}",
                    name,
                    dst_dir_fd=dirfd,
                    follow_symlinks=True,
                )
            except FileExistsError as exc:
                if _compare_existing(dirfd, name, data):  # the winner's bytes equal ours
                    return WriteOutcome.EXISTS_EQUAL
                raise SingleReadRefused(SingleReadReason.EXISTS_DIFFERENT, name) from exc
            except FileNotFoundError as exc:  # no /proc/self/fd entry to link from
                raise SingleReadRefused(SingleReadReason.TMPFILE_UNSUPPORTED, name) from exc
            except OSError as exc:
                if exc.errno in _LINK_UNSUPPORTED_ERRNOS:
                    raise SingleReadRefused(SingleReadReason.LINK_UNSUPPORTED, name) from exc
                raise _io(exc, name) from exc
        except OSError as exc:
            raise _io(exc, name) from exc
        finally:
            os.close(fd)
        try:
            os.fsync(dirfd)
        except OSError as exc:
            raise _io(exc, "directory fsync") from exc
        return WriteOutcome.WRITTEN
    finally:
        os.close(dirfd)
