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
import time as _time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, TextIO

from breezy.runtime.exec_state_db_path import ExecStateDbNotConfiguredError, resolve_store_path
from breezy.runtime.health import AlertPayload, AlertSink, emit_alert, resolve_alert_sink
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import (
    CURRENT_INTENT_KEY,
    SubmitIntent,
    SubmitIntentCorrupt,
    SubmitIntentState,
)
from breezy.runtime.trade_supervisor_core import (
    LAUNCH_UTC,
    MAX_RELAUNCH_ATTEMPTS,
    MIN_RELAUNCH_GAP,
    NODE_ARGV_ANCHOR,
    PERMIT_ISSUED_MARKER,
    RELAUNCH_CUTOFF_UTC,
    SELF_CHECK_ALERT_DETAIL,
    SELF_CHECK_UTC,
    STOP_PRIOR_UTC,
    STRATEGY_SUBSCRIBED_MARKER,
    SUPERVISOR_ARGV_TOKEN,
    AlertDetail,
    DaySchedulerState,
    LaunchAction,
    Phase,
    SelfCheckResult,
    StopPriorAction,
    assert_no_live_node_before_intent_probe,
    classify_exit1_cause,
    decide_launch_action,
    decide_relaunch,
    decide_stop_prior_action,
    initial_scheduler_state,
    mark_phase_fired,
    next_due,
    permit_expiry_valid,
    readiness_observed,
    record_readiness_observed,
    record_relaunch_attempt,
    self_check,
)

logger = logging.getLogger(__name__)

EXIT_OK: Final[int] = 0
EXIT_RUNTIME_ERROR: Final[int] = 1
EXIT_CONFIG_ERROR: Final[int] = 2

NODE_CONSOLE_SCRIPT: Final[str] = "breezy-trade"
SUPERVISOR_LOCK_FILENAME: Final[str] = "trade-supervisor.lock"

_SIGTERM_WAIT_S: Final[float] = 10.0
_SIGTERM_POLL_ATTEMPTS: Final[int] = 20
_SIGTERM_POLL_INTERVAL_S: Final[float] = 0.5

#: Bounded poll interval for the main schedule loop -- an early return or a
#: backwards clock step is always re-evaluated within this many seconds,
#: never a single unbounded sleep.
_SCHEDULE_POLL_INTERVAL_S: Final[float] = 60.0

#: [D1] Pacing interval after a RELAUNCH_CHECK dispatch specifically -- a
#: TIGHTER interval than the general schedule poll (the child may become
#: ready or fail within seconds of being spawned), but every dispatch, not
#: just a NONE result, must be followed by SOME bounded sleep: without
#: this a live RELAUNCH_CHECK window (launched but not yet ready) is a
#: zero-delay busy loop -- pegs a core, hammers /proc/locks and the log.
_RELAUNCH_POLL_INTERVAL_S: Final[float] = 15.0

#: The real ``/proc/locks`` path. A parameter (not a hardcoded literal)
#: everywhere it is read, so tests can point at a synthetic file with real
#: dev/inode-matching content instead of the kernel's own table.
DEFAULT_PROC_LOCKS_PATH: Final[Path] = Path("/proc/locks")

#: /proc/locks' lock-type field: this module's own lock and the node's
#: intent lock are both `fcntl.flock` (BSD) locks, which the kernel reports
#: as `FLOCK`. A `POSIX` (`fcntl.lockf`/byte-range) entry on the SAME
#: dev:inode is a DIFFERENT locking mechanism and must never be mistaken
#: for -- or counted alongside -- the flock holder [M2].
_FLOCK_LOCK_TYPE: Final[str] = "FLOCK"


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


def _iter_flock_holders(
    lock_path: Path, *, locks_path: Path = DEFAULT_PROC_LOCKS_PATH
) -> Iterator[int]:
    """Yield every PID holding an ``FLOCK``-type lock on ``lock_path``'s
    dev:inode, per ``locks_path`` (``/proc/locks`` in production, an
    injectable synthetic file in tests). A ``POSIX`` (``fcntl.lockf``)
    entry on the same inode is a different locking mechanism and is never
    yielded [M2] -- this module and the node it supervises use
    ``fcntl.flock`` exclusively."""
    try:
        stat = lock_path.stat()
    except OSError:
        return
    try:
        raw = locks_path.read_text()
    except OSError:
        return
    for line in raw.splitlines():
        fields = line.split()
        if len(fields) < 6:
            continue
        if fields[1] != _FLOCK_LOCK_TYPE:
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
        yield pid


def resolve_lock_holder_pid(
    lock_path: Path, *, locks_path: Path = DEFAULT_PROC_LOCKS_PATH
) -> int | None:
    """[E5/M2] Read ``/proc/locks`` and return the PID holding an
    ``FLOCK``-type lock on ``lock_path``, cross-referenced by device+inode
    -- never assumed from ``pgrep`` alone, and never a ``POSIX``
    (``fcntl.lockf``) entry on the same inode. Returns ``None`` when the
    file does not exist, is unlocked, or ``/proc/locks`` is unreadable
    (fails closed to "no verified holder")."""
    for pid in _iter_flock_holders(lock_path, locks_path=locks_path):
        return pid
    return None


def count_lock_holders(lock_path: Path, *, locks_path: Path = DEFAULT_PROC_LOCKS_PATH) -> int:
    """[B4/M2] How many distinct PIDs currently hold an ``FLOCK``-type
    lock on ``lock_path`` per ``/proc/locks`` -- an exclusive flock
    structurally admits at most one, so >1 is a defensive falsifiable
    signal the self-check reports on. A ``POSIX`` entry on the same inode
    is never counted here."""
    return len(set(_iter_flock_holders(lock_path, locks_path=locks_path)))


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


class StopPriorRaceRefused(RuntimeError):
    """Raised by :func:`terminate_after_toctou_recheck` when ``pid`` no
    longer verifies as the intent-flock holder immediately before the
    signal would be sent."""


def terminate_after_toctou_recheck(
    pid: int,
    *,
    intent_lock_path_: Path,
    resolve_holder: Callable[[Path], int | None] = resolve_lock_holder_pid,
    terminate_fn: Callable[[int], None] = terminate,
    is_alive: Callable[[int], bool] | None = None,
) -> None:
    """[L3] TOCTOU-safe SIGTERM: the stop-prior DECISION
    (:func:`decide_stop_prior_action`) and the actual signal are two
    separate moments: re-verify, immediately before sending it, that
    ``pid`` (a) still exists and (b) still resolves as the FLOCK holder of
    ``intent_lock_path_``'s inode. Either check failing raises
    ``StopPriorRaceRefused`` -- the caller refuses and alerts rather than
    signalling a PID that may since have been reused by an unrelated
    process."""
    alive_check = is_alive if is_alive is not None else process_is_alive
    if not alive_check(pid):
        raise StopPriorRaceRefused("pid no longer exists")
    if resolve_holder(intent_lock_path_) != pid:
        raise StopPriorRaceRefused("pid no longer holds the intent flock")
    terminate_fn(pid)


def process_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


# ---------------------------------------------------------------------------
# Log markers -- reading, never writing, the child's log. [H1] Offset-
# tracking: the node log grows ~100 KB/min, so re-reading the whole file on
# every poll is unbounded I/O over a multi-hour session. This reader seeks
# to the last byte offset it returned for a given path and reads only the
# NEW bytes -- a multi-MB prefix is read at most once, ever.
# ---------------------------------------------------------------------------


class IncrementalLogReader:
    """Per-path byte-offset log tail reader with a small carry-over buffer.

    ``read_new(path)`` returns ``carry + newly-appended-bytes`` for marker
    matching, where ``carry`` is the tail of the PREVIOUS return (bounded by
    ``carry_bytes``) -- long enough that a control-flow marker split across
    two poll boundaries (e.g. one read ends mid-``issued_at_ns=``) is still
    found whole in the next call's return value, without re-reading
    anything already returned. A shrunk file (rotation/truncation) resets
    the tracked offset to 0 for that path.
    """

    def __init__(self, *, carry_bytes: int = 256) -> None:
        self._carry_bytes = carry_bytes
        self._offsets: dict[Path, int] = {}
        self._carry: dict[Path, str] = {}

    def read_new(self, path: Path) -> str:
        try:
            size = path.stat().st_size
        except OSError:
            return self._carry.get(path, "")
        offset = self._offsets.get(path, 0)
        if size < offset:
            offset = 0
        try:
            with open(path, "rb") as fh:
                fh.seek(offset)
                new_bytes = fh.read()
        except OSError:
            return self._carry.get(path, "")
        self._offsets[path] = offset + len(new_bytes)
        combined = self._carry.get(path, "") + new_bytes.decode("utf-8", errors="replace")
        self._carry[path] = combined[-self._carry_bytes :] if combined else ""
        return combined

    def bytes_read(self, path: Path) -> int:
        """Test/introspection helper: total bytes consumed from ``path``
        across every ``read_new`` call so far."""
        return self._offsets.get(path, 0)


# ---------------------------------------------------------------------------
# Spawning the node [R6].
# ---------------------------------------------------------------------------


def node_log_path(log_dir: Path, now: dt.datetime) -> Path:
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    return log_dir / f"breezy-trade-{stamp}.log"


def supervisor_log_path(log_dir: Path) -> Path:
    return log_dir / "breezy-trade-supervisor.log"


def _process_start_time(pid: int) -> float | None:
    """Best-effort process-start approximation: ``/proc/<pid>``'s own
    ctime, which Linux sets at process creation. ``None`` if unreadable."""
    try:
        return Path(f"/proc/{pid}").stat().st_ctime
    except OSError:
        return None


def find_adopted_node_log(log_dir: Path, pid: int) -> Path | None:
    """[D2] Best-effort: the newest ``breezy-trade-*.log`` under
    ``log_dir`` whose mtime is at or after ``pid``'s own process-start
    time -- ``None`` if that can't be determined (unreadable
    ``/proc/<pid>``, or no candidate log qualifies), in which case the
    caller degrades gracefully rather than guessing."""
    start = _process_start_time(pid)
    if start is None:
        return None
    try:
        candidates = sorted(
            log_dir.glob("breezy-trade-*.log"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return None
    for candidate in candidates:
        try:
            if candidate.stat().st_mtime >= start:
                return candidate
        except OSError:
            continue
    return None


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
# Logging configuration -- attaching real handlers so `log_decision`'s and
# `alert`'s log lines actually reach a file and stderr at INFO, instead of
# being silently dropped by Python's WARNING-only "lastResort" handler
# (the failure mode observed in production: `main` never configured
# logging, so B4/S6's one-line-per-decision observability -- including the
# 17:05 PASS/FAIL line -- was unobservable).
# ---------------------------------------------------------------------------


class _SupervisorFileHandler(logging.FileHandler):
    """Marker subclass -- distinguishes this module's own file handler from
    any other ``FileHandler`` a caller (or a test) might attach to the same
    logger, purely for the idempotency check below."""


class _SupervisorStreamHandler(logging.StreamHandler[TextIO]):
    """Marker subclass, matching :class:`_SupervisorFileHandler`."""


def configure_supervisor_logging(log_dir: Path) -> None:
    """Attach a line-flushed file handler on ``supervisor_log_path(log_dir)``
    (append mode) plus a stderr handler, both at INFO, in UTC. Idempotent:
    a repeated call with the SAME ``log_dir`` (e.g. a defensive re-entry in
    ``main``) is a no-op; a call with a DIFFERENT ``log_dir`` (only
    possible in-process, e.g. across tests) replaces the prior handlers
    rather than accumulating duplicates or leaking file descriptors.

    Every formatted line uses ``asctime`` in UTC (``Formatter.converter =
    time.gmtime``, never local time) -- never an environ value: the
    formatter interpolates only the record's own level/name/message, and
    every ``log_decision``/``alert`` caller already restricts itself to
    static strings and int/str fields (see their own docstrings).
    """
    target = supervisor_log_path(log_dir)
    for handler in logger.handlers:
        if isinstance(handler, _SupervisorFileHandler) and Path(handler.baseFilename) == target:
            return  # already configured for this exact target

    for handler in list(logger.handlers):
        if isinstance(handler, _SupervisorFileHandler | _SupervisorStreamHandler):
            handler.close()
            logger.removeHandler(handler)

    log_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        fmt="%(asctime)sZ %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    formatter.converter = _time.gmtime

    file_handler = _SupervisorFileHandler(target, mode="a")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    stream_handler = _SupervisorStreamHandler(sys.stderr)
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


# ---------------------------------------------------------------------------
# Injectable I/O surface for the schedule loop's phase handlers -- every
# field defaults to the real OS-backed function; tests override individual
# fields with fakes (process table, lock probe, spawner, log reader, alert
# sink).
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SupervisorPorts:
    find_node_pid: Callable[[], int | None]
    resolve_intent_lock_holder: Callable[[Path], int | None]
    intent_lock_free: Callable[[Path], bool]
    count_intent_lock_holders: Callable[[Path], int]
    terminate_after_recheck: Callable[..., None]
    process_alive: Callable[[int], bool]
    probe_open_intent_state: Callable[..., bool]
    spawn: Callable[..., subprocess.Popen[bytes]]
    read_log_new: Callable[[Path], str]
    alert_sink: AlertSink
    sigterm_poll_sleep: Callable[[float], None] = field(default=_time.sleep)
    find_adopted_log: Callable[[Path, int], Path | None] = field(default=find_adopted_node_log)


def default_ports(*, alert_sink: AlertSink | None = None) -> SupervisorPorts:
    log_reader = IncrementalLogReader()
    return SupervisorPorts(
        find_node_pid=lambda: find_pid_by_argv(NODE_ARGV_ANCHOR),
        resolve_intent_lock_holder=resolve_lock_holder_pid,
        intent_lock_free=intent_lock_is_free,
        count_intent_lock_holders=count_lock_holders,
        terminate_after_recheck=terminate_after_toctou_recheck,
        process_alive=process_is_alive,
        probe_open_intent_state=probe_open_intent,
        spawn=spawn_node,
        read_log_new=log_reader.read_new,
        alert_sink=alert_sink if alert_sink is not None else resolve_alert_sink(),
        find_adopted_log=find_adopted_node_log,
    )


# ---------------------------------------------------------------------------
# Phase handlers -- one function per Phase, each a thin composition of the
# pure decision in ``trade_supervisor_core`` and the ports above.
# ---------------------------------------------------------------------------


def _do_stop_prior(
    *, ports: SupervisorPorts, store_path: Path, tracked_pid: int | None
) -> int | None:
    """[B2/E5/L3] Returns the PID still outstanding (None if none)."""
    lock_path = intent_lock_path(store_path)
    discovered = tracked_pid if tracked_pid is not None else ports.find_node_pid()
    holder = ports.resolve_intent_lock_holder(lock_path)
    action = decide_stop_prior_action(discovered_node_pid=discovered, lock_holder_pid=holder)

    if action is StopPriorAction.NOOP:
        log_decision("stop_prior_noop")
        return None

    if action is StopPriorAction.REFUSE_ALERT:
        log_decision("stop_prior_refused")
        alert(
            ports.alert_sink,
            event="TRADE_SUPERVISOR_STOP_PRIOR_REFUSED",
            severity="CRITICAL",
            detail=AlertDetail.ADOPTION_REFUSED,
        )
        return discovered

    # SIGTERM_TRACKED.
    assert discovered is not None
    try:
        ports.terminate_after_recheck(discovered, intent_lock_path_=lock_path)
    except StopPriorRaceRefused:
        log_decision("stop_prior_race_refused", pid=discovered)
        alert(
            ports.alert_sink,
            event="TRADE_SUPERVISOR_STOP_PRIOR_REFUSED",
            severity="WARN",
            detail=AlertDetail.STOP_PRIOR_RACE_REFUSED,
        )
        return None
    log_decision("stop_prior_sigterm", pid=discovered)
    for _ in range(_SIGTERM_POLL_ATTEMPTS):
        if ports.intent_lock_free(lock_path):
            break
        ports.sigterm_poll_sleep(_SIGTERM_POLL_INTERVAL_S)
    return None


def _attempt_adoption(
    *, ports: SupervisorPorts, lock_path: Path, log_dir: Path
) -> tuple[int, Path | None] | None:
    """[D2] Verify a live discovered process IS the FLOCK holder -- never
    assumed from ``pgrep`` alone -- and, on match, return
    ``(pid, log_path)`` to adopt. ``log_path`` is ``None`` when it cannot
    be determined (the caller degrades gracefully, see
    :data:`SelfCheckResult.PASS_ADOPTED_LOG_UNKNOWN`). ``None`` overall
    when no live process verifies as the holder."""
    node_pid = ports.find_node_pid()
    holder = ports.resolve_intent_lock_holder(lock_path)
    if node_pid is None or holder is None or node_pid != holder:
        return None
    return node_pid, ports.find_adopted_log(log_dir, node_pid)


def _do_launch(
    *,
    ports: SupervisorPorts,
    state: DaySchedulerState,
    now: dt.datetime,
    store_path: Path,
    repo_root: Path,
    node_bin: Path,
    log_dir: Path,
) -> tuple[int | None, Path | None, DaySchedulerState, bool]:
    """[R6/B1/D2/D3] Returns ``(pid, log_path, updated_state, done)`` --
    ``done`` tells the caller whether LAUNCH should be marked fired this
    pass (False only while a spawn-failure retry is still pending within
    its bounded budget/gap [D3])."""
    node_pid = ports.find_node_pid()
    lock_path = intent_lock_path(store_path)
    lock_free = ports.intent_lock_free(lock_path)

    if lock_free and node_pid is not None:
        # [E5 scope] A node PID was discovered despite a free flock -- never
        # probe the store while ANY node PID is live; refuse conservatively.
        log_decision("launch_refused_pid_present", pid=node_pid)
        return None, None, state, True

    open_intent = ports.probe_open_intent_state(store_path, node_pid=None) if lock_free else False
    action = decide_launch_action(lock_free=lock_free, open_intent_detected=open_intent)

    if action is LaunchAction.REFUSE_LOCK_HELD:
        # [D2] A supervisor restarted mid-window with a healthy node
        # already holding the flock must ADOPT it, not report it dead.
        adoption = _attempt_adoption(ports=ports, lock_path=lock_path, log_dir=log_dir)
        if adoption is not None:
            pid, log_path = adoption
            log_decision("launch_adopted_live_node", pid=pid)
            return pid, log_path, state, True
        log_decision("launch_refused_lock_held")
        alert(
            ports.alert_sink,
            event="TRADE_SUPERVISOR_LAUNCH_REFUSED",
            severity="WARN",
            detail=AlertDetail.LAUNCH_BLOCKED_LOCK_HELD,
        )
        return None, None, state, True

    if action is LaunchAction.REFUSE_INTENT_OPEN:
        log_decision("launch_refused_intent_open")
        alert(
            ports.alert_sink,
            event="TRADE_SUPERVISOR_LAUNCH_REFUSED",
            severity="CRITICAL",
            detail=AlertDetail.INTENT_OPEN_BLOCKS_ARM,
        )
        return None, None, state, True

    # action is LAUNCH. [D3] A prior spawn attempt this window may have
    # raised -- gate a retry on the SAME bounded budget RELAUNCH_CHECK
    # uses (<=2 attempts, >=3 min apart, never at/after 17:00 UTC), never a
    # free-running immediate retry loop.
    if state.relaunch_attempts > 0:
        exhausted = (
            state.relaunch_attempts >= MAX_RELAUNCH_ATTEMPTS or now.time() >= RELAUNCH_CUTOFF_UTC
        )
        if exhausted:
            log_decision("launch_spawn_retry_exhausted")
            alert(
                ports.alert_sink,
                event="TRADE_SUPERVISOR_LAUNCH_REFUSED",
                severity="CRITICAL",
                detail=AlertDetail.LAUNCH_SPAWN_FAILED,
            )
            return None, None, state, True
        gap_elapsed = (
            state.last_relaunch_attempt_at is None
            or (now - state.last_relaunch_attempt_at) >= MIN_RELAUNCH_GAP
        )
        if not gap_elapsed:
            return None, None, state, False

    log_path = node_log_path(log_dir, now)
    try:
        proc = ports.spawn(
            node_bin=node_bin, repo_root=repo_root, env=os.environ, log_path=log_path
        )
    except Exception as exc:  # noqa: BLE001 -- deliberate: a spawn failure
        # is transient by definition [D3]; contained here and retried
        # against the bounded relaunch budget above, never propagated to
        # forfeit the day by marking LAUNCH fired with no tracked child.
        log_decision("launch_spawn_failed", error_type=type(exc).__name__)
        return None, None, record_relaunch_attempt(state, now), False

    log_decision("launched", pid=proc.pid)
    return proc.pid, log_path, state, True


def _do_relaunch_check(
    *,
    ports: SupervisorPorts,
    state: DaySchedulerState,
    now: dt.datetime,
    tracked_pid: int | None,
    node_log: Path | None,
    store_path: Path,
    repo_root: Path,
    node_bin: Path,
    log_dir: Path,
) -> tuple[int | None, Path | None, DaySchedulerState]:
    """[E4] Poll the tracked child: mark readiness, do nothing while it is
    still starting, or apply the bounded-relaunch decision once it exits."""
    if tracked_pid is None or node_log is None:
        return tracked_pid, node_log, state

    log_text = ports.read_log_new(node_log)
    holder = ports.resolve_intent_lock_holder(intent_lock_path(store_path))
    if readiness_observed(
        holds_intent_lock=(holder == tracked_pid),
        permit_issued=PERMIT_ISSUED_MARKER in log_text,
        strategy_subscribed=STRATEGY_SUBSCRIBED_MARKER in log_text,
    ):
        log_decision("node_ready", pid=tracked_pid)
        return tracked_pid, node_log, record_readiness_observed(state, now)

    if ports.process_alive(tracked_pid):
        return tracked_pid, node_log, state

    cause = classify_exit1_cause(log_text)
    decision = decide_relaunch(
        now=now,
        attempts_so_far=state.relaunch_attempts,
        last_attempt_at=state.last_relaunch_attempt_at,
        readiness_was_observed=state.readiness_observed,
        cause=cause,
    )
    if not decision.should_relaunch:
        log_decision("relaunch_declined", reason=decision.reason)
        return None, node_log, state

    log_decision("relaunching", attempt=state.relaunch_attempts + 1)
    new_log = node_log_path(log_dir, now)
    proc = ports.spawn(node_bin=node_bin, repo_root=repo_root, env=os.environ, log_path=new_log)
    return proc.pid, new_log, record_relaunch_attempt(state, now)


#: Self-check results that are a PASS of some kind -- never alerted on.
_SELF_CHECK_PASS_RESULTS: Final[frozenset[SelfCheckResult]] = frozenset(
    {SelfCheckResult.PASS, SelfCheckResult.PASS_ADOPTED_LOG_UNKNOWN}
)


def _do_self_check(
    *,
    ports: SupervisorPorts,
    now: dt.datetime,
    store_path: Path,
    log_dir: Path,
    tracked_pid: int | None,
    node_log: Path | None,
) -> tuple[int | None, Path | None]:
    """[B4/E3/D2] One PASS/FAIL line, and an alert through the shared sink
    on FAIL with a fixed enum ``detail``. Adopts a live verified flock
    holder FIRST when nothing was tracked -- a supervisor that restarted
    after 17:00 with a healthy node already running must not report
    ``FAIL_CHILD_EXITED`` for it. Returns the (possibly adopted)
    ``(tracked_pid, node_log)`` for the caller to keep carrying forward."""
    lock_path = intent_lock_path(store_path)
    if tracked_pid is None:
        adoption = _attempt_adoption(ports=ports, lock_path=lock_path, log_dir=log_dir)
        if adoption is not None:
            tracked_pid, node_log = adoption
            log_decision("self_check_adopted_live_node", pid=tracked_pid)

    holder = ports.resolve_intent_lock_holder(lock_path)
    holder_count = ports.count_intent_lock_holders(lock_path)
    log_text = ports.read_log_new(node_log) if node_log is not None else ""
    child_alive = tracked_pid is not None and ports.process_alive(tracked_pid)

    result = self_check(
        child_alive=child_alive,
        flock_holder_count=holder_count,
        flock_held_by_tracked_pid=(tracked_pid is not None and holder == tracked_pid),
        permit_issued=PERMIT_ISSUED_MARKER in log_text,
        permit_expiry_valid=permit_expiry_valid(log_text, now_ns=int(now.timestamp() * 1e9)),
        strategy_subscribed=STRATEGY_SUBSCRIBED_MARKER in log_text,
        log_available=node_log is not None,
    )
    log_decision("self_check", result=result.value)
    if result not in _SELF_CHECK_PASS_RESULTS:
        alert(
            ports.alert_sink,
            event="TRADE_SUPERVISOR_SELF_CHECK_FAIL",
            severity="WARN",
            detail=SELF_CHECK_ALERT_DETAIL[result],
        )
    return tracked_pid, node_log


# ---------------------------------------------------------------------------
# Console entry.
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None, *, log_dir: Path | None = None) -> int:
    """Console-script entrypoint for ``breezy-trade-supervisor``.

    Requires the distinct argv token :data:`SUPERVISOR_ARGV_TOKEN` as the
    first positional argument [R8] so ``pgrep -f
    'breezy-trade-supervisor-daily$'`` can find exactly this process without
    substring-matching the node's own ``breezy-trade`` argv. Configures
    logging (:func:`configure_supervisor_logging`) immediately after argv
    validation and before the lock, so every subsequent line -- including
    a configuration-error refusal -- actually reaches
    ``supervisor_log_path(log_dir)`` and stderr. Acquires the supervisor's
    own mutual-exclusion flock; a second instance logs loudly and exits 2
    [R7a]. Beyond argv validation, logging, and lock acquisition this
    function only wires the real I/O helpers above together for the
    long-running daily loop -- the decisions themselves are exercised
    directly, with fakes, in the pure-core tests.

    ``log_dir`` is an optional explicit override of the log directory,
    resolved to ``Path.home() / ".local" / "share" / "breezy" / "logs"``
    at CALL time (never import time) only when omitted. Production callers
    (the real console script) never pass it, so behaviour there is
    unchanged; tests can inject an explicit directory instead of relying on
    every caller remembering to isolate ``Path.home()`` first -- the gap
    that once let a test write straight into the real supervisor log.
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

    repo_root = Path(__file__).resolve().parents[3]
    node_bin = repo_root / ".venv" / "bin" / NODE_CONSOLE_SCRIPT
    if log_dir is None:
        log_dir = Path.home() / ".local" / "share" / "breezy" / "logs"
    configure_supervisor_logging(log_dir)

    try:
        store_path = resolve_store_path(os.environ)
    except ExecStateDbNotConfiguredError as exc:
        log_decision("configuration_error", missing=str(exc))
        return EXIT_CONFIG_ERROR

    lock_path = supervisor_lock_path(store_path)
    try:
        with hold_supervisor_lock(lock_path):
            log_decision(
                "supervisor_started",
                stop_prior_utc=str(STOP_PRIOR_UTC),
                launch_utc=str(LAUNCH_UTC),
                self_check_utc=str(SELF_CHECK_UTC),
                lock_path=str(lock_path),
                log_dir=str(log_dir),
            )
            _run_forever(
                store_path=store_path,
                repo_root=repo_root,
                node_bin=node_bin,
                log_dir=log_dir,
            )
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


def _default_clock() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _run_forever(
    *,
    store_path: Path,
    repo_root: Path,
    node_bin: Path,
    log_dir: Path,
    clock: Callable[[], dt.datetime] = _default_clock,
    sleep: Callable[[float], None] = _time.sleep,
    ports: SupervisorPorts | None = None,
    max_iterations: int | None = None,
) -> None:
    """The daily schedule loop.

    Every decision is delegated to :func:`next_due`
    (``trade_supervisor_core``) and the ``_do_*`` phase handlers above --
    this function only sequences them: compute what is due, run it,
    CONTAIN any exception per phase (one failing phase must never end the
    supervisor), and sleep in bounded (<=60 s) chunks otherwise so an early
    wakeup or a backwards clock step is re-evaluated on the next pass
    rather than slept through. A ``KeyboardInterrupt`` (Ctrl-C / SIGINT)
    ends the loop cleanly; it never touches the node, which runs in its
    own session (``start_new_session=True`` in :func:`spawn_node``) and is
    never signalled by anything other than :func:`terminate_after_toctou_recheck`.

    ``clock``/``sleep``/``ports``/``max_iterations`` are injection points
    for tests (a fake clock, a fake sleep that advances it, fakes for every
    port). Production callers (``main``) use the real defaults and never
    set ``max_iterations``.
    """
    active_ports = ports if ports is not None else default_ports()
    state = initial_scheduler_state(clock().date())
    tracked_pid: int | None = None
    node_log: Path | None = None
    iterations = 0

    try:
        while max_iterations is None or iterations < max_iterations:
            iterations += 1
            now = clock()
            phase, _fire_at = next_due(now, state)

            if phase is Phase.NONE:
                sleep(_SCHEDULE_POLL_INTERVAL_S)
                continue

            try:
                if phase is Phase.STOP_PRIOR:
                    tracked_pid = _do_stop_prior(
                        ports=active_ports, store_path=store_path, tracked_pid=tracked_pid
                    )
                    state = mark_phase_fired(state, phase, now)
                elif phase is Phase.LAUNCH:
                    tracked_pid, node_log, state, done = _do_launch(
                        ports=active_ports,
                        state=state,
                        now=now,
                        store_path=store_path,
                        repo_root=repo_root,
                        node_bin=node_bin,
                        log_dir=log_dir,
                    )
                    if done:
                        state = mark_phase_fired(state, phase, now)
                elif phase is Phase.RELAUNCH_CHECK:
                    tracked_pid, node_log, state = _do_relaunch_check(
                        ports=active_ports,
                        state=state,
                        now=now,
                        tracked_pid=tracked_pid,
                        node_log=node_log,
                        store_path=store_path,
                        repo_root=repo_root,
                        node_bin=node_bin,
                        log_dir=log_dir,
                    )
                else:
                    tracked_pid, node_log = _do_self_check(
                        ports=active_ports,
                        now=now,
                        store_path=store_path,
                        log_dir=log_dir,
                        tracked_pid=tracked_pid,
                        node_log=node_log,
                    )
                    state = mark_phase_fired(state, phase, now)
            except Exception as exc:  # noqa: BLE001 -- deliberate: one failing
                # phase must never end the supervisor (see the coordinator's
                # loop-wiring requirement). Named by TYPE only below, never
                # the exception message -- see the module's value-free stance.
                log_decision(
                    "phase_exception_contained",
                    phase=phase.value,
                    error_type=type(exc).__name__,
                )
                alert(
                    active_ports.alert_sink,
                    event="TRADE_SUPERVISOR_PHASE_EXCEPTION",
                    severity="CRITICAL",
                    detail=AlertDetail.PHASE_EXCEPTION_CONTAINED,
                )
                if phase is not Phase.RELAUNCH_CHECK:
                    state = mark_phase_fired(state, phase, now)

            # [D1] EVERY dispatch is followed by a bounded sleep -- without
            # this, a LAUNCH that leaves RELAUNCH_CHECK due every pass (not
            # yet ready, not yet exited) is a zero-delay busy loop until
            # readiness or the 17:00 UTC cutoff. Tighter for RELAUNCH_CHECK
            # (the child may become ready or fail within seconds) than the
            # general schedule poll.
            sleep(
                _RELAUNCH_POLL_INTERVAL_S
                if phase is Phase.RELAUNCH_CHECK
                else _SCHEDULE_POLL_INTERVAL_S
            )
    except KeyboardInterrupt:
        log_decision("supervisor_interrupted")
        return
