"""The exact per-row ``/run`` re-bind set (plan r5, AC-1.3(7)).

The wrapper mounts a ``--tmpfs /run`` and re-binds only what a row declares it
needs, so the docker, snapd and system-bus sockets stay hidden. In this order:

(a) ``resolves_dns``: the ``/etc/resolv.conf`` target, if it lies under ``/run/``
    (fd bind);
(b) ``E7A_R2_NOTIFY``: ``$NOTIFY_SOCKET`` under ``/run/user/<uid>/systemd/`` (path bind);
(c) ``E7_STUDIES_LOCK``: ``/run/user/<uid>/breezy-studies.lock``, a regular file owned
    by the uid with ``st_nlink == 1`` (fd bind);
(d) ``E7A_R2_RECONCILE``: ``$CREDENTIALS_DIRECTORY`` (fd bind).

**The wrapper never creates a bind source.** A missing studies lock is exit 78;
the unit's own ``touch`` pre line creates it. Error codes carry no path.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from breezy.runtime.autonomy_sandbox.binds import (
    BindIntegrityError,
    Kind,
    Walked,
    walk_nofollow,
)
from breezy.runtime.autonomy_sandbox.table import BwrapRow, SandboxRoots, unit_matches_row

RESOLV_CONF: Final = Path("/etc/resolv.conf")
HOST_RUN: Final = Path("/run")
STUDIES_LOCK_NAME: Final = "breezy-studies.lock"
CREDENTIALS_DIR_MODE: Final = 0o500
CREDENTIAL_FILE_MODE: Final = 0o400
NOTIFY_SOCKET_VAR: Final = "NOTIFY_SOCKET"
CREDENTIALS_DIRECTORY_VAR: Final = "CREDENTIALS_DIRECTORY"

RebindKind = Literal["dns", "notify", "studies_lock", "credentials"]


class RunMountError(BindIntegrityError):
    """A ``/run`` re-bind source failed its check; the wrapper exits 78."""


@dataclass(frozen=True, slots=True)
class RunRebind:
    """One re-bind: ``--ro-bind-fd fd dest`` when ``fd`` is set, else ``--ro-bind src dest``."""

    kind: RebindKind
    dest: str
    fd: int | None = None
    src: str | None = None


def close_run_rebinds(rebinds: tuple[RunRebind, ...]) -> None:
    """Close the fd of every fd-bound re-bind (path binds own no fd)."""
    for rebind in rebinds:
        if rebind.fd is not None:
            os.close(rebind.fd)


def _walk(path: str | Path, kind: Kind, codes: Mapping[str, str]) -> Walked:
    """Walk ``path`` nofollow, mapping the walk's codes to this mount's codes (``*`` = rest)."""
    try:
        return walk_nofollow(path, kind=kind)
    except BindIntegrityError as exc:
        raise RunMountError(codes.get(exc.code, codes["*"])) from None


def _walk_kept(stack: ExitStack, path: str | Path, kind: Kind, codes: Mapping[str, str]) -> Walked:
    walked = _walk(path, kind, codes)
    stack.callback(os.close, walked.fd)
    return walked


def _dns(stack: ExitStack, resolv_conf: Path, host_run: Path) -> RunRebind | None:
    target = os.path.realpath(resolv_conf)
    if not target.startswith(f"{host_run}/"):
        return None
    walked = _walk_kept(stack, target, "file", {"*": "dns_target"})
    return RunRebind("dns", dest=target, fd=walked.fd)


def _notify(roots: SandboxRoots, environ: Mapping[str, str]) -> RunRebind:
    value = environ.get(NOTIFY_SOCKET_VAR, "")
    if not value:
        raise RunMountError("notify_missing")
    allowed = f"{roots.run_user}/systemd/"
    if not value.startswith(allowed) or os.path.normpath(value) != value:
        raise RunMountError("notify_path")
    codes = {"*": "notify_socket"}
    walked = _walk(value, "socket", codes)
    try:
        if walked.st.st_uid != roots.uid:
            raise RunMountError("notify_owner")
    finally:
        os.close(walked.fd)
    return RunRebind("notify", dest=value, src=value)


def _studies_lock(stack: ExitStack, roots: SandboxRoots) -> RunRebind:
    path = str(roots.run_user / STUDIES_LOCK_NAME)
    codes = {"missing": "studies_lock_missing", "*": "studies_lock_not_regular"}
    walked = _walk_kept(stack, path, "file", codes)
    if walked.st.st_uid != roots.uid:
        raise RunMountError("studies_lock_owner")
    if walked.st.st_nlink != 1:
        raise RunMountError("studies_lock_nlink")
    return RunRebind("studies_lock", dest=path, fd=walked.fd)


def _credential_names(directory_fd: int) -> dict[str, os.stat_result]:
    scan_fd = os.open(".", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC, dir_fd=directory_fd)
    try:
        with os.scandir(scan_fd) as entries:
            return {entry.name: entry.stat(follow_symlinks=False) for entry in entries}
    finally:
        os.close(scan_fd)


def _credentials(
    stack: ExitStack,
    row: BwrapRow,
    roots: SandboxRoots,
    environ: Mapping[str, str],
    unit: str | None,
) -> RunRebind:
    if unit is None or not unit_matches_row(row, unit):
        raise RunMountError("credentials_unit")
    expected = str(roots.run_user / "credentials" / unit)
    if environ.get(CREDENTIALS_DIRECTORY_VAR) != expected:
        raise RunMountError("credentials_path")
    walked = _walk_kept(
        stack, expected, "dir", {"missing": "credentials_missing", "*": "credentials_path"}
    )
    if stat.S_IMODE(walked.st.st_mode) != CREDENTIALS_DIR_MODE:
        raise RunMountError("credentials_dir_mode")
    if walked.st.st_uid != roots.uid:
        raise RunMountError("credentials_dir_owner")
    entries = _credential_names(walked.fd)
    if set(entries) != set(row.credential_names):
        raise RunMountError("credentials_contents")
    for st in entries.values():
        if not stat.S_ISREG(st.st_mode) or stat.S_IMODE(st.st_mode) != CREDENTIAL_FILE_MODE:
            raise RunMountError("credentials_file")
        if st.st_uid != roots.uid:
            raise RunMountError("credentials_file")
    return RunRebind("credentials", dest=expected, fd=walked.fd)


def run_rebinds(
    row: BwrapRow,
    roots: SandboxRoots,
    environ: Mapping[str, str],
    *,
    unit: str | None = None,
    resolv_conf: Path = RESOLV_CONF,
    host_run: Path = HOST_RUN,
) -> tuple[RunRebind, ...]:
    """The ``/run`` re-binds ``row`` needs, in a fixed order, each checked before it is returned.

    ``unit`` is the validated cgroup leaf (``E7A_R2_RECONCILE`` rows need it to name the
    credentials directory). On success the caller owns the fds and must call
    ``close_run_rebinds``; on failure every fd opened so far is already closed.
    """
    with ExitStack() as stack:
        rebinds: list[RunRebind] = []
        if row.resolves_dns:
            dns = _dns(stack, resolv_conf, host_run)
            if dns is not None:
                rebinds.append(dns)
        if "E7A_R2_NOTIFY" in row.exceptions:
            rebinds.append(_notify(roots, environ))
        if row.studies_lock:
            rebinds.append(_studies_lock(stack, roots))
        if row.credential_names:
            rebinds.append(_credentials(stack, row, roots, environ, unit))
        stack.pop_all()
        return tuple(rebinds)
