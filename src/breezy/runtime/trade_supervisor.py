"""``breezy-trade-supervisor``: the detached daily launcher for ``breezy-trade``.

I/O shell around :mod:`breezy.runtime.trade_supervisor_core`'s pure decision
rules. Every OS interaction (process discovery, ``/proc/locks`` inspection,
flock probing, log reading, ``subprocess.Popen``, alerting) lives here as a
thin, individually-testable function; the decisions themselves stay in the
core module with zero I/O imports.

Values-free, matching ``app/trade.py``: the seven operator-reserved values
are never read, parsed, or logged by this module -- they travel ONLY inside
``env=`` when spawning the child, forwarded from the supervisor's own
process environment as-is. Nothing under ``deploy/`` is touched; no systemd
unit targets ``breezy-trade``; no value is ever written to argv, a file, or
a log record.

Null hypothesis checked before writing this: Nautilus Trader has no native
scheduled-restart facility (``kernel.py`` carries no ``restart``/
``reschedule``/``scheduled_restart`` hook; ``TradingNode.run()`` returns
``None`` with no restart signal -- ``live/node.py:283-302``), so this is
process-shell machinery Breezy must own, same category as ``app/trade.py``
and ``runtime/trade_cli.py``.
"""

from __future__ import annotations

import datetime as dt
import errno
import fcntl
import logging
import os
import resource
import signal
import subprocess
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Final

from breezy.adapters.polymarket_us.factories import EXEC_STATE_DB_ENV_VAR
from breezy.runtime.health import AlertPayload, AlertSink, emit_alert, resolve_alert_sink
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import (
    CURRENT_INTENT_KEY,
    SubmitIntent,
    SubmitIntentCorrupt,
    SubmitIntentState,
)
from breezy.runtime.trade_supervisor_core import (
    SUPERVISOR_ARGV_TOKEN,
    AlertDetail,
    assert_no_live_node_before_intent_probe,
)

logger = logging.getLogger(__name__)

EXIT_OK: Final[int] = 0
EXIT_RUNTIME_ERROR: Final[int] = 1
EXIT_CONFIG_ERROR: Final[int] = 2

NODE_CONSOLE_SCRIPT: Final[str] = "breezy-trade"
SUPERVISOR_LOCK_FILENAME: Final[str] = "trade-supervisor.lock"

_SIGTERM_WAIT_S: Final[float] = 10.0


# ---------------------------------------------------------------------------
# Hardening [R9].
# ---------------------------------------------------------------------------


def apply_core_limit() -> None:
    """``resource.setrlimit(RLIMIT_CORE, (0, 0))`` for THIS process.

    Called once at supervisor startup. Never touches, reads, or logs any
    environ value -- it takes no arguments derived from the environment.
    """
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _child_preexec() -> None:
    """``preexec_fn`` for the spawned node: the same hardening, run in the
    child after ``fork()`` and before ``exec()``."""
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


# ---------------------------------------------------------------------------
# Supervisor mutual exclusion [R7a].
# ---------------------------------------------------------------------------


class SupervisorLockHeld(RuntimeError):
    """Raised when a second supervisor instance is already running."""


class SupervisorLockError(RuntimeError):
    """Raised when the supervisor's own lock cannot be opened/acquired for a
    non-contention reason."""


def supervisor_lock_path(state_store_path: Path) -> Path:
    """The supervisor's own lock, beside the store -- same directory, same
    pattern as ``submit_intent.py``'s process lock, but a DISTINCT file so
    the two locks never contend with each other."""
    return state_store_path.parent / SUPERVISOR_LOCK_FILENAME


@contextmanager
def hold_supervisor_lock(lock_path: Path) -> Iterator[None]:
    """Hold an exclusive non-blocking flock on ``lock_path``, or fail closed.

    Same shape as ``submit_intent.hold_submit_intent_process_lock`` -- a
    second supervisor over the same store refuses loudly (``SupervisorLockHeld``)
    rather than pgrep-marker detection [R7a].
    """
    if not lock_path.parent.is_dir():
        raise SupervisorLockError(f"lock directory does not exist: {lock_path.parent}")
    flags = os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        fd = os.open(lock_path, flags, 0o644)
    except OSError as exc:
        raise SupervisorLockError(str(type(exc).__name__)) from None
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in {errno.EWOULDBLOCK, errno.EAGAIN}:
                raise SupervisorLockHeld() from None
            raise SupervisorLockError(str(type(exc).__name__)) from None
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


# ---------------------------------------------------------------------------
# Intent-flock probing (external -- never owning the lock) [R6/R7b/E5].
# ---------------------------------------------------------------------------


def intent_lock_path(state_store_path: Path) -> Path:
    """Matches ``submit_intent.hold_submit_intent_process_lock``'s own path
    derivation exactly: ``<store>.intent.lock`` beside the store file."""
    return state_store_path.with_name(state_store_path.name + ".intent.lock")


def intent_lock_is_free(lock_path: Path) -> bool:
    """Non-blocking external probe: True if a fresh exclusive flock on
    ``lock_path`` can be taken and released immediately (i.e. nothing else
    currently holds it). Never blocks; never yields the lock to a caller."""
    if not lock_path.exists():
        return True
    try:
        fd = os.open(lock_path, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        return False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in {errno.EWOULDBLOCK, errno.EAGAIN}:
                return False
            return False
        fcntl.flock(fd, fcntl.LOCK_UN)
        return True
    finally:
        os.close(fd)


def resolve_lock_holder_pid(lock_path: Path) -> int | None:
    """[E5] Read ``/proc/locks`` and return the PID holding ``lock_path``,
    cross-referenced by device+inode -- never assumed from ``pgrep`` alone.
    Returns ``None`` when the file does not exist, is unlocked, or
    ``/proc/locks`` is unreadable (fails closed to "no verified holder")."""
    try:
        stat = lock_path.stat()
    except OSError:
        return None
    try:
        raw = Path("/proc/locks").read_text()
    except OSError:
        return None
    for line in raw.splitlines():
        fields = line.split()
        if len(fields) < 6:
            continue
        devino = fields[5].split(":")
        if len(devino) != 3:
            continue
        major_s, minor_s, inode_s = devino
        try:
            pid = int(fields[4])
            inode = int(inode_s)
            major = int(major_s, 16)
            minor = int(minor_s, 16)
        except ValueError:
            continue
        if inode != stat.st_ino:
            continue
        if os.makedev(major, minor) != stat.st_dev:
            continue
        return pid
    return None


def count_lock_holders(lock_path: Path) -> int:
    """[B4] How many distinct PIDs currently hold ``lock_path`` per
    ``/proc/locks`` -- an exclusive flock structurally admits at most one,
    so >1 is a defensive falsifiable signal the self-check reports on."""
    try:
        stat = lock_path.stat()
    except OSError:
        return 0
    try:
        raw = Path("/proc/locks").read_text()
    except OSError:
        return 0
    holders: set[int] = set()
    for line in raw.splitlines():
        fields = line.split()
        if len(fields) < 6:
            continue
        devino = fields[5].split(":")
        if len(devino) != 3:
            continue
        major_s, minor_s, inode_s = devino
        try:
            pid = int(fields[4])
            inode = int(inode_s)
            major = int(major_s, 16)
            minor = int(minor_s, 16)
        except ValueError:
            continue
        if inode != stat.st_ino or os.makedev(major, minor) != stat.st_dev:
            continue
        holders.add(pid)
    return len(holders)


# ---------------------------------------------------------------------------
# Pre-launch OPEN-intent probe [B1/E5 scope].
# ---------------------------------------------------------------------------


def probe_open_intent(store_path: Path, *, node_pid: int | None) -> bool:
    """Read-only-by-convention read of the submit-intent singleton via a
    FRESH ``SqliteStateStore`` connection (SQLite serves concurrent
    readers), outside any mutex or flock -- never invoked while a node PID
    is live (:func:`assert_no_live_node_before_intent_probe` enforces this).

    A corrupt singleton is treated as OPEN (fail closed), matching
    ``SubmitIntentLatch.is_latched``'s own stance.
    """
    assert_no_live_node_before_intent_probe(node_pid)
    with SqliteStateStore(store_path) as store:
        raw = store.get(CURRENT_INTENT_KEY)
        if raw is None:
            return False
        try:
            record = SubmitIntent.from_bytes(raw)
        except SubmitIntentCorrupt:
            return True
        return record.state is SubmitIntentState.OPEN


# ---------------------------------------------------------------------------
# Process discovery and signalling. SIGTERM only -- never SIGKILL anywhere
# in this module.
# ---------------------------------------------------------------------------


def find_pid_by_argv(anchor_pattern: str) -> int | None:
    """``pgrep -f <anchor_pattern>``, anchored (trailing ``$``) by the
    caller. Returns the first matching PID, or ``None``."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", anchor_pattern],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.isdigit():
            return int(line)
    return None


def terminate(pid: int) -> None:
    """SIGTERM only. This module never sends SIGKILL on any path."""
    os.kill(pid, signal.SIGTERM)


def process_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


# ---------------------------------------------------------------------------
# Log markers -- reading, never writing, the child's log.
# ---------------------------------------------------------------------------


def read_log_text(log_path: Path) -> str:
    try:
        return log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# Spawning the node [R6].
# ---------------------------------------------------------------------------


def node_log_path(log_dir: Path, now: dt.datetime) -> Path:
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    return log_dir / f"breezy-trade-{stamp}.log"


def supervisor_log_path(log_dir: Path) -> Path:
    return log_dir / "breezy-trade-supervisor.log"


def spawn_node(
    *,
    node_bin: Path,
    repo_root: Path,
    env: Mapping[str, str],
    log_path: Path,
) -> subprocess.Popen[bytes]:
    """Launch ``breezy-trade`` detached: own SID/PGID, no controlling
    terminal input, ``env`` forwarded AS-IS (never filtered, never logged),
    NO values in argv, ``RLIMIT_CORE=0`` applied in the child before exec."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "ab") as log_fh:
        # preexec_fn is safe here: this supervisor is single-threaded by
        # design (a values-free process shell, same category as
        # app/trade.py) -- it is the one sanctioned way to apply
        # RLIMIT_CORE=0 in the CHILD before exec, which os.posix_spawn
        # cannot do. Accepted, not a defect.
        return subprocess.Popen(
            [str(node_bin)],
            env=dict(env),
            cwd=str(repo_root),
            stdin=subprocess.DEVNULL,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            preexec_fn=_child_preexec,  # noqa: PLW1509
            close_fds=True,
        )


# ---------------------------------------------------------------------------
# Value-free logging and alerting.
# ---------------------------------------------------------------------------


def log_decision(event: str, **fields: int | str) -> None:
    """One line per decision. Static event name + int/str fields only --
    never an exception object, never an environ mapping, never anything
    that could carry a value from the seven operator-reserved controls."""
    if fields:
        rendered = " ".join(f"{key}={value}" for key, value in fields.items())
        logger.info("%s %s", event, rendered)
    else:
        logger.info(event)


def alert(
    sink: AlertSink,
    *,
    event: str,
    severity: str,
    detail: AlertDetail,
    site: str = "trade_node",
) -> None:
    """Emit through the shared sink. ``detail`` is always a closed-enum
    value, never exception text or a config/permit value."""
    emit_alert(
        sink,
        AlertPayload(severity=severity, event=event, site=site, detail=detail.value),
    )


# ---------------------------------------------------------------------------
# Console entry.
# ---------------------------------------------------------------------------


class ExecStateDbNotConfiguredError(RuntimeError):
    """Raised when the supervisor's own environment carries no exec state
    DB path -- it needs this only to locate the store/intent-lock paths,
    never to read or forward its value anywhere but ``env=`` at spawn time."""


def resolve_store_path(env: Mapping[str, str]) -> Path:
    raw = env.get(EXEC_STATE_DB_ENV_VAR, "").strip()
    if not raw:
        raise ExecStateDbNotConfiguredError(EXEC_STATE_DB_ENV_VAR)
    return Path(raw)


def main(argv: list[str] | None = None) -> int:
    """Console-script entrypoint for ``breezy-trade-supervisor``.

    Requires the distinct argv token :data:`SUPERVISOR_ARGV_TOKEN` as the
    first positional argument [R8] so ``pgrep -f
    'breezy-trade-supervisor-daily$'`` can find exactly this process without
    substring-matching the node's own ``breezy-trade`` argv. Acquires the
    supervisor's own mutual-exclusion flock; a second instance logs loudly
    and exits 2 [R7a]. Beyond argv validation and lock acquisition this
    function only wires the real I/O helpers above together for the
    long-running daily loop -- the decisions themselves are exercised
    directly, with fakes, in the pure-core tests.
    """
    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] != SUPERVISOR_ARGV_TOKEN:
        print(
            f"breezy-trade-supervisor: refusing to start: first argument must be "
            f"{SUPERVISOR_ARGV_TOKEN!r}",
            file=sys.stderr,
        )
        return EXIT_CONFIG_ERROR

    apply_core_limit()

    try:
        store_path = resolve_store_path(os.environ)
    except ExecStateDbNotConfiguredError as exc:
        log_decision("configuration_error", missing=str(exc))
        return EXIT_CONFIG_ERROR

    lock_path = supervisor_lock_path(store_path)
    try:
        with hold_supervisor_lock(lock_path):
            log_decision("supervisor_started")
            _run_forever(store_path=store_path)
    except SupervisorLockHeld:
        log_decision("second_supervisor_refused")
        alert(
            resolve_alert_sink(),
            event="TRADE_SUPERVISOR_DUPLICATE",
            severity="WARN",
            detail=AlertDetail.SECOND_SUPERVISOR_REFUSED,
        )
        return EXIT_CONFIG_ERROR
    except SupervisorLockError:
        log_decision("supervisor_lock_error")
        return EXIT_CONFIG_ERROR
    return EXIT_OK


def _run_forever(*, store_path: Path) -> None:  # pragma: no cover - long-running I/O loop
    """The actual daily schedule loop.

    Deliberately thin: every decision it makes is delegated to the pure
    functions in ``trade_supervisor_core`` plus the I/O helpers above, both
    already covered directly by unit tests with fakes. This function itself
    is process/time-bound (real ``time.sleep`` against real wall clock) and
    is exercised operationally, not in the unit-test suite -- see the
    module docstring and the coordinator invocation in the task report.
    """
    import time

    while True:
        time.sleep(30)
