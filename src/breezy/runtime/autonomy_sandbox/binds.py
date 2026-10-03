"""Nofollow bind walks and fd-opened bind sources (plan r5, AC-1.2).

Every path is walked one component at a time with ``O_PATH|O_NOFOLLOW`` from
``/``, so a symlink anywhere on the path is refused rather than followed, and
the fd handed to ``--bind-fd`` / ``--ro-bind-fd`` is the object that was
checked. Each bind must be a directory on the base's device, distinct from
``state/``, its ancestors and the data root, and must not nest in another bind.

**The wrapper never creates a bind source.** A missing path is a refusal
(exit 78), never a ``mkdir``. Error codes carry no path.
"""

from __future__ import annotations

import errno
import os
import stat
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Final, Literal

from breezy.runtime.autonomy_sandbox.table import (
    ALTERNATE_BIND_BASES,
    DEFAULT_BIND_BASE,
    BwrapRow,
    SandboxRoots,
)

Kind = Literal["dir", "file", "socket"]
Ident = tuple[int, int]

_WALK_FLAGS: Final = os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC
_STATE_DIR: Final = "state"
_UNSAFE_WRITE_BITS: Final = 0o022
_KIND_CHECKS: Final = {"dir": stat.S_ISDIR, "file": stat.S_ISREG, "socket": stat.S_ISSOCK}


class BindIntegrityError(Exception):
    """A bind source (or ``/run`` re-bind) failed an integrity check; the wrapper exits 78."""

    exit_status: ClassVar[int] = 78

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class Walked:
    """An open ``O_PATH`` fd plus the identity of every component on its path."""

    fd: int
    ident: Ident
    chain: tuple[Ident, ...]
    st: os.stat_result


@dataclass(frozen=True, slots=True)
class OpenedBind:
    rel: str
    path: str
    fd: int
    dev: int
    ino: int


@dataclass(frozen=True, slots=True)
class OpenedBinds:
    binds: tuple[OpenedBind, ...]
    config_files: tuple[OpenedBind, ...]
    config_dirs: tuple[OpenedBind, ...]


def _ident(st: os.stat_result) -> Ident:
    return (st.st_dev, st.st_ino)


def _components(path: str | Path) -> list[str]:
    text = os.fspath(path)
    if not text.startswith("/"):
        raise BindIntegrityError("bad_path")
    parts = [] if text == "/" else text[1:].split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise BindIntegrityError("bad_path")
    return parts


def _open_error(exc: OSError) -> BindIntegrityError:
    if exc.errno == errno.ENOENT:
        return BindIntegrityError("missing")
    if exc.errno in (errno.ENOTDIR, errno.ELOOP):
        return BindIntegrityError("not_dir")
    return BindIntegrityError("open_failed")


def walk_nofollow(path: str | Path, *, kind: Kind) -> Walked:
    """Walk ``path`` from ``/`` without following any symlink; return the final fd.

    The caller owns (and must close) ``Walked.fd``. Intermediate components are
    always directories; the final one must be ``kind``. Never creates anything.
    """
    parts = _components(path)
    current = os.open("/", _WALK_FLAGS | os.O_DIRECTORY)
    try:
        chain = [_ident(os.fstat(current))]
        for index, part in enumerate(parts):
            is_last = index == len(parts) - 1
            flags = _WALK_FLAGS if is_last and kind != "dir" else _WALK_FLAGS | os.O_DIRECTORY
            try:
                following = os.open(part, flags, dir_fd=current)
            except OSError as exc:
                raise _open_error(exc) from None
            os.close(current)
            current = following
            chain.append(_ident(os.fstat(current)))
        st = os.fstat(current)
        if not _KIND_CHECKS[kind](st.st_mode):
            raise BindIntegrityError(f"not_{kind}")
    except BaseException:
        os.close(current)
        raise
    return Walked(fd=current, ident=chain[-1], chain=tuple(chain), st=st)


def forbidden_dirs(roots: SandboxRoots) -> frozenset[Ident]:
    """Identities no bind may equal or sit under: the data root, its ancestors, ``state/``."""
    idents: set[Ident] = set()
    root = walk_nofollow(roots.data_root, kind="dir")
    os.close(root.fd)
    idents.update(root.chain)
    try:
        state = walk_nofollow(roots.data_root / _STATE_DIR, kind="dir")
    except BindIntegrityError as exc:
        if exc.code != "missing":
            raise
    else:
        os.close(state.fd)
        idents.add(state.ident)
    return frozenset(idents)


def _base_path(row: BwrapRow, roots: SandboxRoots) -> Path:
    if row.bind_base == DEFAULT_BIND_BASE:
        return roots.data_root
    if row.bind_base not in ALTERNATE_BIND_BASES:
        raise BindIntegrityError("bad_base")
    return roots.home / ALTERNATE_BIND_BASES[row.bind_base]


def _walk_registered(stack: ExitStack, path: str | Path, kind: Kind) -> Walked:
    walked = walk_nofollow(path, kind=kind)
    stack.callback(os.close, walked.fd)
    return walked


def _refuse_forbidden(walked: Walked, base_depth: int, forbidden: frozenset[Ident]) -> None:
    if any(ident in forbidden for ident in walked.chain[base_depth:]):
        raise BindIntegrityError("forbidden")


def _refuse_nested(walked: Walked, earlier: list[Walked]) -> None:
    for other in earlier:
        if (
            walked.ident == other.ident
            or other.ident in walked.chain[:-1]
            or walked.ident in other.chain[:-1]
        ):
            raise BindIntegrityError("nested")


def _refuse_unsafe_owner_or_mode(walked: Walked, roots: SandboxRoots) -> None:
    if walked.st.st_uid != roots.uid:
        raise BindIntegrityError("owner")
    if walked.st.st_mode & _UNSAFE_WRITE_BITS:
        raise BindIntegrityError("writable")


def _open_data_binds(
    stack: ExitStack,
    row: BwrapRow,
    roots: SandboxRoots,
    forbidden: frozenset[Ident],
    earlier: list[Walked],
) -> tuple[OpenedBind, ...]:
    if not row.binds:
        return ()
    base_path = _base_path(row, roots)
    base = _walk_registered(stack, base_path, "dir")
    opened: list[OpenedBind] = []
    for rel in row.binds:
        path = f"{base_path}/{rel}"
        walked = _walk_registered(stack, path, "dir")
        if walked.st.st_dev != base.st.st_dev:
            raise BindIntegrityError("wrong_device")
        _refuse_forbidden(walked, len(base.chain), forbidden)
        _refuse_unsafe_owner_or_mode(walked, roots)
        _refuse_nested(walked, earlier)
        earlier.append(walked)
        opened.append(OpenedBind(rel, path, walked.fd, walked.st.st_dev, walked.st.st_ino))
    return tuple(opened)


def _open_config(
    stack: ExitStack,
    rels: tuple[str, ...],
    kind: Kind,
    roots: SandboxRoots,
    home: Walked,
    forbidden: frozenset[Ident],
    earlier: list[Walked],
) -> tuple[OpenedBind, ...]:
    opened: list[OpenedBind] = []
    for rel in rels:
        path = f"{roots.home}/{rel}"
        walked = _walk_registered(stack, path, kind)
        _refuse_forbidden(walked, len(home.chain), forbidden)
        _refuse_unsafe_owner_or_mode(walked, roots)
        _refuse_nested(walked, earlier)
        earlier.append(walked)
        opened.append(OpenedBind(rel, path, walked.fd, walked.st.st_dev, walked.st.st_ino))
    return tuple(opened)


@contextmanager
def open_validated_binds(row: BwrapRow, roots: SandboxRoots) -> Iterator[OpenedBinds]:
    """Open every bind and config source of ``row`` by nofollow walk; close them on exit.

    Raises ``BindIntegrityError`` (exit 78) on any violation, closing whatever it
    had already opened. Creates nothing.
    """
    with ExitStack() as stack:
        forbidden = forbidden_dirs(roots)
        earlier: list[Walked] = []
        data = _open_data_binds(stack, row, roots, forbidden, earlier)
        files: tuple[OpenedBind, ...] = ()
        dirs: tuple[OpenedBind, ...] = ()
        if row.config_ro_binds or row.config_ro_dirs:
            home = _walk_registered(stack, roots.home, "dir")
            files = _open_config(
                stack, row.config_ro_binds, "file", roots, home, forbidden, earlier
            )
            dirs = _open_config(stack, row.config_ro_dirs, "dir", roots, home, forbidden, earlier)
        yield OpenedBinds(binds=data, config_files=files, config_dirs=dirs)
