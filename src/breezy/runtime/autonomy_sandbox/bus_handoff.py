"""The bus snapshot handoff (plan r5 AC-9; M34, M38, M40, M41, B6-R3).

A sandbox never reaches the user bus (``--tmpfs /run``). A row that needs ``systemctl --user``
reads gets them *handed over*: ``breezy-autonomy-bwrap --bus-snapshot ROW`` runs **unsandboxed**
in ``ExecStartPre`` (``write_bus_snapshot``), makes the row's fixed read-only calls, and writes
one ``<INVOCATION_ID>.json`` into ``<bind>/.bus_snapshot``. Inside the sandbox
``read_bus_snapshot`` reads that file once and unlinks it; a missing, forged or stale file
raises, it is never an empty snapshot.

Safety properties, each pinned by a test:

* **Read verbs only.** Every argv is re-validated against the AC-9.1 grammar immediately before
  it is spawned (``table.validate_bus_read``), after ``{instance}`` substitution, so no
  ``kill``/``start``/``stop``/``restart``/``try-restart``/``systemd-run`` can run, and an
  ``{instance}`` that is not a unit token is refused.
* **Nothing is written until every check passed.** The invocation id, the row, the argv set and
  the bind are validated before the directory is touched; the directory is then validated by
  ``fstat`` (a symlink, another owner, group/other bits, another device or a forbidden inode is
  refused with nothing written and nothing swept).
* **Bounded.** Each read runs in its own process group (``Popen(start_new_session=True)``); on
  timeout the whole group is killed, so the mode's wall time stays below the row's budget.
* **Reason codes only.** stderr carries a code, never a path.

stdlib only. No exec of its own and no bus call beyond the read verbs.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from breezy.runtime.autonomy_sandbox.binds import (
    BindIntegrityError,
    Ident,
    OpenedBind,
    bind_base_path,
    forbidden_dirs,
    open_validated_binds,
    walk_nofollow,
)
from breezy.runtime.autonomy_sandbox.table import (
    INSTANCE_TOKEN,
    UNIT_INSTANCE_RE,
    BusRead,
    BwrapRow,
    SandboxRoots,
    TableError,
    unit_matches_row,
    validate_bus_read,
)

SNAPSHOT_DIR: Final = ".bus_snapshot"
SCHEMA: Final = "bus_snapshot/v1"
BUS_ENV_PATH: Final = "/usr/bin:/bin"
BUS_READ_TIMEOUT_S: Final = 10
READ_MARGIN_S: Final = 1.0
MIN_READ_S: Final = 0.5
DRAIN_TIMEOUT_S: Final = 1.0
MAX_STDOUT_BYTES: Final = 4 * 1024 * 1024
MAX_DOCUMENT_BYTES: Final = 64 * 1024 * 1024
SWEEP_AGE_S: Final = 24 * 3600
EX_CONFIG: Final = 78
EX_WRITE: Final = 73
SKIPPED_RC: Final = -1
SPAWN_FAILED_RC: Final = 127
MISSING: Final = "bus_snapshot_missing"
STALE: Final = "bus_snapshot_stale"
_PROGRAM: Final = "breezy-autonomy-bwrap"
_INVOCATION_ID_RE: Final = re.compile(r"[0-9a-f]{32}")
_SNAPSHOT_NAME_RE: Final = re.compile(r"[0-9a-f]{32}\.json")
_SERVICE_SUFFIX: Final = ".service"
_PRIVATE_DIR_MODE: Final = 0o700
_PRIVATE_FILE_MODE: Final = 0o600
_GROUP_OTHER_BITS: Final = 0o077
_CREATE_FLAGS: Final = os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC
_READ_CHUNK: Final = 1 << 20
_READ_KEYS: Final = frozenset({"name", "argv", "rc", "timed_out", "skipped", "oversize", "stdout"})

Popen = Callable[..., Any]


class BusSnapshotError(Exception):
    """No usable snapshot: ``code`` is ``bus_snapshot_missing`` or ``bus_snapshot_stale``."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class BusHandoffError(Exception):
    """A refusal on the writing side; ``exit_status`` is 78 (config) or 73 (write failure)."""

    def __init__(self, code: str, exit_status: int = EX_CONFIG) -> None:
        super().__init__(code)
        self.code = code
        self.exit_status = exit_status


@dataclass(frozen=True, slots=True)
class BusReadResult:
    name: str
    argv: tuple[str, ...]
    rc: int
    timed_out: bool
    skipped: bool
    oversize: bool
    stdout: str


@dataclass(frozen=True, slots=True)
class BusSnapshot:
    invocation_id: str
    unit: str
    ts_ns: int
    budget_s: int
    reads: tuple[BusReadResult, ...]


def bus_env(uid: int) -> dict[str, str]:
    """The fixed environment of every bus read: nothing is inherited from the unit."""
    return {
        "PATH": BUS_ENV_PATH,
        "XDG_RUNTIME_DIR": f"/run/user/{uid}",
        "LANG": "C.UTF-8",
        "SYSTEMD_PAGER": "",
        "SYSTEMD_COLORS": "0",
    }


# --------------------------------------------------------------------------- writing side


def _invocation_id(environ: Mapping[str, str]) -> str:
    value = environ.get("INVOCATION_ID")
    if value is None or not _INVOCATION_ID_RE.fullmatch(value):
        raise BusHandoffError("invocation_id")
    return value


def _instance(unit: str) -> str | None:
    if not unit.endswith(_SERVICE_SUFFIX):
        return None
    stem = unit[: -len(_SERVICE_SUFFIX)]
    at = stem.find("@")
    return stem[at + 1 :] if at >= 0 else None


def _substituted(row: BwrapRow, read: BusRead, unit: str) -> BusRead:
    """``read`` with ``{instance}`` replaced, then re-validated against the full grammar."""
    argv = read.argv
    if INSTANCE_TOKEN in argv:
        instance = _instance(unit)
        if instance is None or not UNIT_INSTANCE_RE.fullmatch(instance):
            raise BusHandoffError("instance")
        argv = tuple(instance if token == INSTANCE_TOKEN else token for token in argv)
    checked = BusRead(read.name, argv)
    try:
        validate_bus_read(row.name, checked)
    except TableError:
        raise BusHandoffError("bus_read_invalid") from None
    return checked


def _snapshot_plan(row: BwrapRow, unit: str) -> tuple[str, int, tuple[BusRead, ...]]:
    bind, budget = row.bus_snapshot_bind, row.bus_snapshot_budget_s
    if not row.bus_reads or bind is None or budget is None or bind not in row.binds:
        raise BusHandoffError("not_a_bus_row")
    return bind, budget, tuple(_substituted(row, read, unit) for read in row.bus_reads)


def _check_snapshot_dir(
    st: os.stat_result, *, euid: int, bind_dev: int, forbidden: frozenset[Ident]
) -> None:
    if not stat.S_ISDIR(st.st_mode):
        raise BusHandoffError("snapshot_dir")
    if st.st_uid != euid or st.st_mode & _GROUP_OTHER_BITS:
        raise BusHandoffError("snapshot_dir")
    if st.st_dev != bind_dev or (st.st_dev, st.st_ino) in forbidden:
        raise BusHandoffError("snapshot_dir")


def _open_snapshot_dir(bind: OpenedBind, roots: SandboxRoots) -> int:
    """``mkdirat`` (EEXIST accepted) then a nofollow open of ``.bus_snapshot``; fstat-validated."""
    try:
        os.mkdir(SNAPSHOT_DIR, _PRIVATE_DIR_MODE, dir_fd=bind.fd)
    except FileExistsError:
        pass
    except OSError:
        raise BusHandoffError("snapshot_dir") from None
    try:
        fd = os.open(
            SNAPSHOT_DIR,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=bind.fd,
        )
    except OSError:
        raise BusHandoffError("snapshot_dir") from None
    try:
        _check_snapshot_dir(
            os.fstat(fd),
            euid=os.geteuid(),
            bind_dev=bind.dev,
            forbidden=forbidden_dirs(roots),
        )
    except BaseException:
        os.close(fd)
        raise
    return fd


def _kill_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass  # the group is already gone: nothing left to kill


def _drain(proc: Any) -> None:
    """Reap the killed group's leader and empty its pipe, for at most ``DRAIN_TIMEOUT_S``."""
    try:
        proc.communicate(timeout=DRAIN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        pass  # the group is SIGKILLed; the pipe is closed by the caller either way


def _result(
    read: BusRead, rc: int, stdout: bytes, *, timed_out: bool = False, skipped: bool = False
) -> BusReadResult:
    oversize = len(stdout) > MAX_STDOUT_BYTES
    text = "" if oversize else stdout.decode("utf-8", errors="replace")
    return BusReadResult(read.name, read.argv, rc, timed_out, skipped, oversize, text)


def _one_read(read: BusRead, allowance: float, popen: Popen, env: dict[str, str]) -> BusReadResult:
    try:
        proc = popen(
            list(read.argv),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
            close_fds=True,
        )
    except OSError:
        return _result(read, SPAWN_FAILED_RC, b"")
    try:
        try:
            out, _ = proc.communicate(timeout=allowance)
        except subprocess.TimeoutExpired:
            _kill_group(proc.pid)
            _drain(proc)
            rc = proc.returncode if isinstance(proc.returncode, int) else -signal.SIGKILL
            return _result(read, rc, b"", timed_out=True)
        return _result(read, proc.returncode, bytes(out or b""))
    finally:
        if getattr(proc, "stdout", None) is not None:
            proc.stdout.close()


def _run_reads(
    reads: tuple[BusRead, ...], budget: int, popen: Popen, clock: Callable[[], float], uid: int
) -> list[BusReadResult]:
    deadline = clock() + budget
    env = bus_env(uid)
    results: list[BusReadResult] = []
    for read in reads:
        allowance = min(BUS_READ_TIMEOUT_S, deadline - clock() - READ_MARGIN_S)
        if allowance < MIN_READ_S:
            results.append(_result(read, SKIPPED_RC, b"", skipped=True))
        else:
            results.append(_one_read(read, allowance, popen, env))
    return results


def _document(invocation: str, unit: str, budget: int, results: list[BusReadResult]) -> bytes:
    doc = {
        "schema": SCHEMA,
        "invocation_id": invocation,
        "unit": unit,
        "ts_ns": time.time_ns(),
        "budget_s": budget,
        "reads": [
            {
                "name": r.name,
                "argv": list(r.argv),
                "rc": r.rc,
                "timed_out": r.timed_out,
                "skipped": r.skipped,
                "oversize": r.oversize,
                "stdout": r.stdout,
            }
            for r in results
        ],
    }
    return json.dumps(doc, sort_keys=True).encode("utf-8")


def _create_snapshot(dir_fd: int, invocation: str, data: bytes) -> None:
    name = f"{invocation}.json"
    try:
        fd = os.open(name, _CREATE_FLAGS, _PRIVATE_FILE_MODE, dir_fd=dir_fd)
    except OSError:
        raise BusHandoffError("snapshot_write", EX_WRITE) from None
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view) :]
        os.fsync(fd)
    except OSError:
        try:
            os.unlink(name, dir_fd=dir_fd)
        except OSError:
            pass  # a partial file with an unmatched id is swept after SWEEP_AGE_S
        raise BusHandoffError("snapshot_write", EX_WRITE) from None
    finally:
        os.close(fd)


def _sweep(dir_fd: int, wall: Callable[[], float]) -> None:
    """Delete matching regular files older than 24 h; skip entirely under flock contention."""
    try:
        fcntl.flock(dir_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return  # another writer holds the sweep; the snapshot is already written
    cutoff = wall() - SWEEP_AGE_S
    with os.scandir(dir_fd) as entries:
        names = [entry.name for entry in entries]
    for name in names:
        if not _SNAPSHOT_NAME_RE.fullmatch(name):
            continue
        try:
            st = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
            if stat.S_ISREG(st.st_mode) and st.st_mtime < cutoff:
                os.unlink(name, dir_fd=dir_fd)
        except OSError:
            continue  # raced with another remover, or not ours to delete: leave it


def _write(
    row: BwrapRow,
    *,
    roots: SandboxRoots,
    environ: Mapping[str, str],
    unit: str,
    popen: Popen,
    clock: Callable[[], float],
    wall: Callable[[], float],
) -> None:
    invocation = _invocation_id(environ)
    bind_rel, budget, reads = _snapshot_plan(row, unit)
    with open_validated_binds(row, roots, only=bind_rel) as opened:
        (bind,) = opened.binds
        dir_fd = _open_snapshot_dir(bind, roots)
        try:
            results = _run_reads(reads, budget, popen, clock, roots.uid)
            _create_snapshot(dir_fd, invocation, _document(invocation, unit, budget, results))
            _sweep(dir_fd, wall)
        finally:
            os.close(dir_fd)


def _refuse(code: str, status: int) -> int:
    sys.stderr.write(f"{_PROGRAM}: refused: {code}\n")
    return status


def write_bus_snapshot(
    row: BwrapRow,
    *,
    roots: SandboxRoots,
    environ: Mapping[str, str],
    unit: str,
    popen: Popen = subprocess.Popen,
    clock: Callable[[], float] = time.monotonic,
    wall: Callable[[], float] = time.time,
) -> int:
    """Write ``<INVOCATION_ID>.json`` for ``row``; return the mode's exit status.

    0 once written (a failed, timed-out or skipped read is *recorded*, never an exit status);
    78 for a config error (nothing written, nothing run); 73 for a write failure. The caller
    (``bwrap.main``) has already passed the syntax, table, row and cgroup checks.
    """
    try:
        _write(
            row,
            roots=roots,
            environ=environ,
            unit=unit,
            popen=popen,
            clock=clock,
            wall=wall,
        )
    except BindIntegrityError as exc:
        return _refuse(exc.code, exc.exit_status)
    except BusHandoffError as exc:
        return _refuse(exc.code, exc.exit_status)
    return 0


# --------------------------------------------------------------------------- reading side


def _consume(bind_fd: int, invocation: str) -> bytes:
    """Read ``<invocation>.json`` once through nofollow opens, then unlink it."""
    name = f"{invocation}.json"
    try:
        dir_fd = os.open(
            SNAPSHOT_DIR,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=bind_fd,
        )
    except OSError:
        raise BusSnapshotError(MISSING) from None
    try:
        try:
            # O_NONBLOCK so a planted FIFO cannot hang the reader; fstat refuses non-regular files.
            fd = os.open(
                name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                dir_fd=dir_fd,
            )
        except OSError:
            raise BusSnapshotError(MISSING) from None
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise BusSnapshotError(MISSING)
            chunks: list[bytes] = []
            total = 0
            while chunk := os.read(fd, _READ_CHUNK):
                total += len(chunk)
                if total > MAX_DOCUMENT_BYTES:
                    raise BusSnapshotError(STALE)
                chunks.append(chunk)
        finally:
            os.close(fd)
        try:
            os.unlink(name, dir_fd=dir_fd)
        except OSError:
            pass  # already read; an unmatched leftover is swept after SWEEP_AGE_S
        return b"".join(chunks)
    finally:
        os.close(dir_fd)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _parse_read(raw: object) -> BusReadResult:
    if not isinstance(raw, dict) or set(raw) != _READ_KEYS:
        raise BusSnapshotError(STALE)
    argv, stdout = raw["argv"], raw["stdout"]
    flags = (raw["timed_out"], raw["skipped"], raw["oversize"])
    if (
        not isinstance(raw["name"], str)
        or not isinstance(argv, list)
        or not all(isinstance(token, str) for token in argv)
        or not _is_int(raw["rc"])
        or not all(isinstance(flag, bool) for flag in flags)
        or not isinstance(stdout, str)
    ):
        raise BusSnapshotError(STALE)
    return BusReadResult(raw["name"], tuple(argv), raw["rc"], *flags, stdout)


def _parse(data: bytes, row: BwrapRow, invocation: str) -> BusSnapshot:
    try:
        doc = json.loads(data)
    except ValueError:
        raise BusSnapshotError(STALE) from None
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise BusSnapshotError(STALE)
    unit, reads = doc.get("unit"), doc.get("reads")
    if (
        doc.get("invocation_id") != invocation
        or not isinstance(unit, str)
        or not unit_matches_row(row, unit)
        or not _is_int(doc.get("ts_ns"))
        or not _is_int(doc.get("budget_s"))
        or not isinstance(reads, list)
    ):
        raise BusSnapshotError(STALE)
    parsed = tuple(_parse_read(raw) for raw in reads)
    if [r.name for r in parsed] != [read.name for read in row.bus_reads]:
        raise BusSnapshotError(STALE)
    return BusSnapshot(invocation, unit, doc["ts_ns"], doc["budget_s"], parsed)


def read_bus_snapshot(
    row: BwrapRow,
    *,
    environ: Mapping[str, str],
    roots: SandboxRoots | None = None,
) -> BusSnapshot:
    """The handed-over snapshot of this invocation, consumed; never an empty snapshot.

    Raises ``BusSnapshotError`` with ``bus_snapshot_missing`` (nothing usable to read) or
    ``bus_snapshot_stale`` (read, but not this row's, this invocation's or well-formed). The
    unit is matched against the *row*: inside the sandbox's cgroup namespace the calling unit's
    own name is not visible.
    """
    invocation = environ.get("INVOCATION_ID")
    rel = row.bus_snapshot_bind
    if invocation is None or not _INVOCATION_ID_RE.fullmatch(invocation) or rel is None:
        raise BusSnapshotError(MISSING)
    if roots is None:
        from breezy.runtime.autonomy_sandbox.bwrap import default_roots

        roots = default_roots()
    try:
        bind = walk_nofollow(f"{bind_base_path(row, roots)}/{rel}", kind="dir")
    except BindIntegrityError:
        raise BusSnapshotError(MISSING) from None
    try:
        data = _consume(bind.fd, invocation)
    finally:
        os.close(bind.fd)
    return _parse(data, row, invocation)
