"""The in-sandbox self-probe (plan r5 AC-2; erratum E-7 rule 2 as amended by E-7e(d)).

``run_self_probe(row)`` is the proof, made from *inside* the process, that a wrapped
unit really runs in its row: the table-derived write negatives, the positive binds,
the hidden credentials, the private ``/run`` and ``/tmp``, and the pid namespace.
A unit that finds itself unwrapped must stop, so the caller contract is
``require_sandbox(row)`` raising ``SandboxIntegrityError`` and printing
``<UNIT> INTEGRITY bwrap_probe_failed direction=<code>``.

Rules the probe keeps (each has a failing test):

* the ``BREEZY_AUTONOMY_BWRAP_ROW`` check runs **before any open**;
* every negative is a write attempt that creates **no directory entry**: an
  ``O_TMPFILE`` open must fail with exactly ``EROFS`` (``EOPNOTSUPP`` falls back to
  ``statvfs`` plus the mountinfo ``ro`` flag, never a named create);
* the negative targets come from the table only (no live listing), after a
  directory-owned-by-euid precondition;
* a reason code never carries a path.

The probe is an integrity check against misconfiguration, not a security boundary
(E-7e(c)): a same-uid hostile process is out of scope. It re-derives the home and
``/run`` allowlists on its own rather than calling the wrapper's builders, so a
drift in the wrapper shows up as a probe failure.
"""

from __future__ import annotations

import errno
import os
import re
import socket
import stat
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, NamedTuple

from breezy.runtime.autonomy_sandbox.binds import bind_base_path
from breezy.runtime.autonomy_sandbox.bwrap import DEGRADED_VAR, ROW_VAR, default_roots
from breezy.runtime.autonomy_sandbox.run_mounts import (
    NOTIFY_SOCKET_VAR,
    RESOLV_CONF,
    STUDIES_LOCK_NAME,
)
from breezy.runtime.autonomy_sandbox.table import (
    AUTONOMY_BWRAP_TABLE,
    NOTIFIER_FALLBACK_ROWS,
    BwrapRow,
    SandboxRoots,
)

#: Every reason code except the per-bind ``positive_<bind>`` family. Exact (L-12).
FIXED_REASON_CODES: Final[frozenset[str]] = frozenset(
    {
        "negative",
        "negative_registry",
        "negative_unverifiable",
        "probe_residue",
        "env_row",
        "degraded_forged",
        "credentials_visible",
        "user_bus_visible",
        "host_socket_visible",
        "run_not_private",
        "run_not_readonly",
        "tmp_not_private",
        "pid_ns",
        "net_reachable",
        "net_iface_visible",
    }
)
CREDENTIAL_PATHS: Final[tuple[str, ...]] = (
    ".config/breezy",
    ".ssh",
    ".aws",
    ".gnupg",
    ".netrc",
)
#: Root-equivalent sockets that ``--tmpfs /run`` must hide (M15, M17).
HOST_SOCKETS: Final[tuple[str, ...]] = (
    "/var/run/docker.sock",
    "/run/docker.sock",
    "/run/snapd.socket",
    "/run/snapd-snap.socket",
    "/var/snap/lxd/common/lxd/unix.socket",
    "/run/lxd-installer.socket",
    "/run/dbus/system_bus_socket",
)
USER_BUS_NAMES: Final[tuple[str, ...]] = ("bus", "systemd/private")
PROBE_DIR_NAME: Final = ".bwrap_probe"
BWRAP_INIT_COMM: Final = "bwrap"
_TMPFS: Final = "tmpfs"
_PROBE_FILE_ENTROPY_BYTES: Final = 6
_KIB: Final = 1024
_BIND_LABEL_UNSAFE: Final = re.compile(r"[^a-z0-9_]")
_MOUNT_ESCAPE: Final = re.compile(r"\\([0-7]{3})")
_PROBE_CREATE_FLAGS: Final = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
_PROBE_FILE_MODE: Final = 0o600
#: E-15 network check on ``none`` rows (S3-R34). A ``SOCK_DGRAM`` connect to a TEST-NET-2 address
#: sends no packet even when isolation is broken; inside a fresh netns it fails ``ENETUNREACH``.
PROBE_CONNECT_HOST: Final = "198.51.100.7"
PROBE_CONNECT_PORT: Final = 80
PROBE_CONNECT_TIMEOUT_S: Final = 2.0
_LOOPBACK: Final = "lo"
_NET_DEV_HEADER_LINES: Final = 2


def udp_connect_errno(host: str, port: int) -> int:
    """``0`` if a ``SOCK_DGRAM`` connect to ``host:port`` succeeds, else the ``errno`` it raised."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(PROBE_CONNECT_TIMEOUT_S)
        sock.connect((host, port))
    except OSError as exc:
        return exc.errno or errno.EIO
    finally:
        sock.close()
    return 0


@dataclass(frozen=True, slots=True)
class ProbeFs:
    """The fixed system paths the probe inspects, injectable so phase 1 can use a scratch tree."""

    host_root: Path = Path("/")
    run: Path = Path("/run")
    tmp: Path = Path("/tmp")
    proc: Path = Path("/proc")
    mountinfo: Path = Path("/proc/self/mountinfo")
    getpid: Callable[[], int] = os.getpid
    connect_errno: Callable[[str, int], int] = udp_connect_errno


DEFAULT_FS: Final = ProbeFs()


@dataclass(frozen=True, slots=True)
class SelfProbeResult:
    """``ok`` only if every step held. ``degraded`` marks a notifier row run unwrapped."""

    ok: bool
    degraded: bool
    failures: tuple[str, ...]
    facts: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True, slots=True)
class NegativeTarget:
    label: str
    path: Path
    code: str


@dataclass(frozen=True, slots=True)
class PositiveTarget:
    label: str
    path: Path
    kind: str


@dataclass(frozen=True, slots=True)
class SelfProbePlan:
    """Everything the probe checks that is a pure function of the row and the roots."""

    negatives: tuple[NegativeTarget, ...]
    positives: tuple[PositiveTarget, ...]
    home_listing_allowed: frozenset[str]


class SandboxIntegrityError(RuntimeError):
    """The unit is not running inside its row. ``code`` is the first reason, never a path."""

    def __init__(self, codes: tuple[str, ...]) -> None:
        super().__init__(",".join(codes))
        self.codes = codes
        self.code = codes[0]


class DegradedWriteTargetError(ValueError):
    """A degraded-mode write target is refused; the message is the code, never a path."""


def _bind_label(rel: str) -> str:
    return _BIND_LABEL_UNSAFE.sub("_", rel.lower())


def self_probe_plan(row: BwrapRow, roots: SandboxRoots) -> SelfProbePlan:
    """The negatives, positives and home allowlist for ``row``, derived from the table only."""
    base = bind_base_path(row, roots)
    data = roots.data_root
    negatives: dict[Path, NegativeTarget] = {}

    def add(label: str, path: Path, code: str = "negative") -> None:
        negatives.setdefault(path, NegativeTarget(label, path, code))

    add("state", data / "state")
    if "registry" not in row.binds:
        add("registry", data / "registry", "negative_registry")
    add("data_root", data)
    add("repo_root", roots.repo_root)
    if base != data:
        add("base", base)
    for rel in row.binds:
        parts = rel.split("/")
        for depth in range(1, len(parts)):
            add("ancestor_" + _bind_label("/".join(parts[:depth])), base.joinpath(*parts[:depth]))
    positives = tuple(
        PositiveTarget(
            _bind_label(rel),
            base / rel,
            row.positive_probe[rel].kind if rel in row.positive_probe else "tmpfile",
        )
        for rel in row.binds
    )
    return SelfProbePlan(tuple(negatives.values()), positives, _home_listing_allowed(row, roots))


def _home_listing_allowed(row: BwrapRow, roots: SandboxRoots) -> frozenset[str]:
    """First home component of each wrapper home re-bind, plus ``.config`` iff config binds."""
    paths = [roots.repo_root, roots.python_prefix, roots.data_root, bind_base_path(row, roots)]
    allowed = {
        path.relative_to(roots.home).parts[0]
        for path in paths
        if path.is_relative_to(roots.home) and path != roots.home
    }
    for rel in (*row.config_ro_binds, *row.config_ro_dirs):
        allowed.add(rel.split("/", 1)[0])
    return frozenset(allowed)


# --- O_TMPFILE: the no-write primitive ---------------------------------------------


def _tmpfile_outcome(path: str | Path) -> str:
    """``erofs``, ``unsupported``, ``created`` (an unnamed inode, closed at once) or ``error``."""
    try:
        fd = os.open(path, os.O_TMPFILE | os.O_WRONLY | os.O_CLOEXEC, _PROBE_FILE_MODE)
    except OSError as exc:
        if exc.errno == errno.EROFS:
            return "erofs"
        return "unsupported" if exc.errno == errno.EOPNOTSUPP else "error"
    os.close(fd)
    return "created"


class Mount(NamedTuple):
    mountpoint: str
    options: frozenset[str]
    fstype: str


def _parse_mountinfo(text: str) -> list[Mount]:
    entries: list[Mount] = []
    for line in text.splitlines():
        left, separator, right = line.partition(" - ")
        fields = left.split()
        if not separator or len(fields) < 6:
            continue
        mountpoint = _MOUNT_ESCAPE.sub(lambda m: chr(int(m.group(1), 8)), fields[4])
        entries.append(Mount(mountpoint, frozenset(fields[5].split(",")), right.split(" ", 1)[0]))
    return entries


def _read_mountinfo(fs: ProbeFs) -> list[Mount]:
    try:
        return _parse_mountinfo(fs.mountinfo.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return []


def _mount_for(path: str, entries: list[Mount]) -> Mount | None:
    """The mount holding ``path``: the longest matching mount point, the later entry on a tie."""
    best: Mount | None = None
    for entry in entries:
        covers = path == entry.mountpoint or path.startswith(entry.mountpoint.rstrip("/") + "/")
        if covers and (best is None or len(entry.mountpoint) >= len(best.mountpoint)):
            best = entry
    return best


def _read_only_by_statvfs_and_mountinfo(path: Path, fs: ProbeFs) -> bool:
    try:
        flagged = bool(os.statvfs(path).f_flag & os.ST_RDONLY)
    except OSError:
        return False
    mount = _mount_for(str(path), _read_mountinfo(fs))
    return flagged and mount is not None and "ro" in mount.options


# --- the steps ---------------------------------------------------------------------


def _negative_failure(target: NegativeTarget, fs: ProbeFs) -> str | None:
    try:
        st = os.lstat(target.path)
    except OSError:
        return "negative_unverifiable"
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid():
        return "negative_unverifiable"
    outcome = _tmpfile_outcome(target.path)
    if outcome == "erofs":
        return None
    if outcome == "unsupported":
        readonly = _read_only_by_statvfs_and_mountinfo(target.path, fs)
        return None if readonly else "negative_unverifiable"
    return target.code


def _positive_failure(target: PositiveTarget) -> str | None:
    failure = f"positive_{target.label}"
    if target.kind == "tmpfile":
        return None if _tmpfile_outcome(target.path) == "created" else failure
    return _subdir_positive(target.path, failure)


def _subdir_positive(bind: Path, failure: str) -> str | None:
    """Create and unlink one probe file inside the existing ``.bwrap_probe/`` (never mkdir)."""
    try:
        dir_fd = os.open(
            bind / PROBE_DIR_NAME,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
    except OSError:
        return failure
    name = f".probe_{os.getpid()}_{os.urandom(_PROBE_FILE_ENTROPY_BYTES).hex()}"
    try:
        st = os.fstat(dir_fd)
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid():
            return failure
        try:
            os.close(os.open(name, _PROBE_CREATE_FLAGS, _PROBE_FILE_MODE, dir_fd=dir_fd))
        except OSError:
            return failure
        try:
            os.unlink(name, dir_fd=dir_fd)
        except OSError:
            return "probe_residue"
        return None
    finally:
        os.close(dir_fd)


def _is_absent(path: Path) -> bool:
    """True only for ENOENT: any other outcome (even a permission error) fails closed."""
    try:
        os.lstat(path)
    except OSError as exc:
        return exc.errno == errno.ENOENT
    return False


def _credential_failures(
    plan: SelfProbePlan, roots: SandboxRoots, facts: dict[str, Any]
) -> list[str]:
    for rel in CREDENTIAL_PATHS:
        if not _is_absent(roots.home / rel):
            return ["credentials_visible"]
    try:
        listing = sorted(os.listdir(roots.home))
    except OSError:
        return ["credentials_visible"]
    facts["home_listing"] = listing
    return [] if set(listing) <= plan.home_listing_allowed else ["credentials_visible"]


def _connect_gives_enoent(host_root: Path, absolute: str) -> bool:
    """True iff connecting to ``absolute`` (under ``host_root``) fails with ENOENT.

    The parent is opened by fd and the leaf reached through ``/proc/self/fd`` so a long
    scratch path cannot trip ``sun_path``'s 107-byte limit.
    """
    path = host_root / absolute.lstrip("/")
    try:
        parent_fd = os.open(path.parent, os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC)
    except OSError as exc:
        return exc.errno in (errno.ENOENT, errno.ENOTDIR)
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(f"/proc/self/fd/{parent_fd}/{path.name}")
        except OSError as exc:
            return exc.errno == errno.ENOENT
        finally:
            sock.close()
        return False
    finally:
        os.close(parent_fd)


def _run_allowed(
    row: BwrapRow, roots: SandboxRoots, environ: Mapping[str, str], fs: ProbeFs
) -> frozenset[str]:
    """The ``/run`` paths the wrapper re-binds for ``row`` (E-7e(c)), derived independently."""
    allowed: set[str] = set()
    if row.resolves_dns:
        target = os.path.realpath(RESOLV_CONF)
        if target.startswith(f"{fs.run}/"):
            allowed.add(target)
    if "E7A_R2_NOTIFY" in row.exceptions and environ.get(NOTIFY_SOCKET_VAR):
        allowed.add(environ[NOTIFY_SOCKET_VAR])
    if row.studies_lock:
        allowed.add(str(roots.run_user / STUDIES_LOCK_NAME))
    if row.credential_env:
        first = environ.get(min(row.credential_env), "")
        directory = os.path.dirname(first)
        if directory.startswith(f"{roots.run_user}/credentials/"):
            allowed.add(directory)
    return frozenset(allowed)


def _walk_run(
    directory: str, allowed: frozenset[str], ancestors: frozenset[str], failures: list[str]
) -> None:
    """Nofollow walk: only allowed paths and their ancestors may exist under ``/run``."""
    try:
        entries = list(os.scandir(directory))
    except OSError:
        failures.append("run_not_private")
        return
    for entry in entries:
        if entry.path in allowed:
            continue
        try:
            mode = entry.stat(follow_symlinks=False).st_mode
        except OSError:
            failures.append("run_not_private")
            continue
        if entry.path in ancestors and stat.S_ISDIR(mode):
            _walk_run(entry.path, allowed, ancestors, failures)
        elif stat.S_ISSOCK(mode):
            failures.append("host_socket_visible")
        else:
            failures.append("run_not_private")


def _run_failures(
    row: BwrapRow, roots: SandboxRoots, environ: Mapping[str, str], fs: ProbeFs
) -> list[str]:
    failures: list[str] = []
    if not all(_connect_gives_enoent(fs.host_root, path) for path in HOST_SOCKETS):
        failures.append("host_socket_visible")
    user_run = f"/run/user/{roots.uid}"
    if not all(_connect_gives_enoent(fs.host_root, f"{user_run}/{n}") for n in USER_BUS_NAMES):
        failures.append("user_bus_visible")
    allowed = _run_allowed(row, roots, environ, fs)
    ancestors = frozenset(str(parent) for path in allowed for parent in Path(path).parents)
    _walk_run(str(fs.run), allowed, ancestors, failures)
    if _tmpfile_outcome(fs.run) != "erofs":
        failures.append("run_not_readonly")
    return failures


def _tmp_failures(fs: ProbeFs, facts: dict[str, Any]) -> list[str]:
    mounts = [m for m in _read_mountinfo(fs) if m.mountpoint == str(fs.tmp)]
    if not mounts or mounts[-1].fstype != _TMPFS or _tmpfile_outcome(fs.tmp) != "created":
        return ["tmp_not_private"]
    try:
        st = os.statvfs(fs.tmp)
    except OSError:
        return ["tmp_not_private"]
    facts["tmp_size_kib"] = st.f_blocks * st.f_frsize // _KIB
    return []


def _pid_ns_failures(row: BwrapRow, fs: ProbeFs) -> list[str]:
    if row.host_proc:
        try:
            return [] if int(os.readlink(fs.proc / "self")) != fs.getpid() else ["pid_ns"]
        except (OSError, ValueError):
            return ["pid_ns"]
    try:
        comm = (fs.proc / "1" / "comm").read_text(encoding="utf-8").strip()
    except OSError:
        return ["pid_ns"]
    return [] if comm == BWRAP_INIT_COMM else ["pid_ns"]


def _interfaces(fs: ProbeFs) -> list[str]:
    """The interface names in ``/proc/net/dev`` (the reader's own netns); ``[]`` if unreadable."""
    try:
        text = (fs.proc / "net" / "dev").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = text.splitlines()[_NET_DEV_HEADER_LINES:]
    return sorted(line.partition(":")[0].strip() for line in lines if ":" in line)


def _net_failures(row: BwrapRow, fs: ProbeFs, facts: dict[str, Any]) -> list[str]:
    """E-15: a ``none`` row must see no route out and only ``lo``. Every row records its ifaces."""
    interfaces = _interfaces(fs)
    facts["net_ifaces"] = interfaces
    if row.network != "none":
        return []
    failures: list[str] = []
    result = fs.connect_errno(PROBE_CONNECT_HOST, PROBE_CONNECT_PORT)
    facts["net_connect_errno"] = errno.errorcode.get(result, str(result)) if result else "connected"
    if result != errno.ENETUNREACH:
        failures.append("net_reachable")
    if interfaces != [_LOOPBACK]:
        failures.append("net_iface_visible")
    return failures


def _unique(codes: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(codes))


def run_self_probe(
    row_name: str,
    *,
    roots: SandboxRoots | None = None,
    environ: Mapping[str, str] | None = None,
    fs: ProbeFs = DEFAULT_FS,
    table: Mapping[str, BwrapRow] = AUTONOMY_BWRAP_TABLE,
    fallback_rows: Collection[str] = NOTIFIER_FALLBACK_ROWS,
) -> SelfProbeResult:
    """Run AC-2 steps 1-8 for ``row_name`` and report every failure code.

    An unknown row raises ``KeyError`` (fail closed; there is no default row).
    """
    env = os.environ if environ is None else environ
    if env.get(ROW_VAR) != row_name:
        return SelfProbeResult(False, False, ("env_row",))
    row = table[row_name]
    if DEGRADED_VAR in env:
        if row_name in fallback_rows:
            return SelfProbeResult(False, True, ())
        return SelfProbeResult(False, False, ("degraded_forged",))
    use_roots = roots if roots is not None else default_roots()
    plan = self_probe_plan(row, use_roots)
    facts: dict[str, Any] = {}
    failures = [code for t in plan.negatives if (code := _negative_failure(t, fs))]
    failures += [code for p in plan.positives if (code := _positive_failure(p))]
    failures += _credential_failures(plan, use_roots, facts)
    failures += _run_failures(row, use_roots, env, fs)
    failures += _tmp_failures(fs, facts)
    failures += _pid_ns_failures(row, fs)
    failures += _net_failures(row, fs, facts)
    codes = _unique(failures)
    return SelfProbeResult(not codes, False, codes, MappingProxyType(facts))


def require_sandbox(row_name: str, **kwargs: Any) -> SelfProbeResult:
    """Return the probe result, or raise ``SandboxIntegrityError`` unless it is ok or degraded.

    The caller prints ``<UNIT> INTEGRITY bwrap_probe_failed direction=<error.code>``,
    delivers a CRITICAL and exits 3.
    """
    result = run_self_probe(row_name, **kwargs)
    if result.ok or result.degraded:
        return result
    raise SandboxIntegrityError(result.failures)


def degraded_write_target(
    row_name: str,
    path: str | Path,
    *,
    roots: SandboxRoots | None = None,
    table: Mapping[str, BwrapRow] = AUTONOMY_BWRAP_TABLE,
) -> Path:
    """Resolve ``path`` for a degraded write, refusing ``state/`` and anything off the binds."""
    row = table[row_name]
    use_roots = roots if roots is not None else default_roots()
    resolved = Path(os.path.realpath(path))
    state = Path(os.path.realpath(use_roots.data_root / "state"))
    if resolved == state or resolved.is_relative_to(state):
        raise DegradedWriteTargetError("state")
    base = bind_base_path(row, use_roots)
    for rel in row.binds:
        bind = Path(os.path.realpath(base / rel))
        if resolved == bind or resolved.is_relative_to(bind):
            return resolved
    raise DegradedWriteTargetError("outside_binds")
