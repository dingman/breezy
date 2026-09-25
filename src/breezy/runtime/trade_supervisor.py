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
unit targets ``breezy-trade``; no value is ever written to argv, a file this
process reads, or a log record.

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
import json
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

import breezy
from breezy.runtime.build_sha import (
    BUILD_REVISION_ENV_VAR,  # noqa: F401 - re-exported, see Rev 3.1 R8 note below
    _looks_like_git_sha,  # noqa: F401 - re-exported, see Rev 3.1 R8 note below
    _read_git_head_sha,
    _read_ref_sha,  # noqa: F401 - re-exported, see Rev 3.1 R8 note below
)
from breezy.runtime.build_sha import resolve_build_revision as _resolve_build_revision_impl
from breezy.runtime.exec_state_db_path import ExecStateDbNotConfiguredError, resolve_store_path
from breezy.runtime.health import (
    AlertPayload,
    AlertSink,
    emit_alert,
    log_alert_egress_status,
    resolve_alert_sink,
)
from breezy.runtime.settings import SENDING_FAMILY_ID_VAR
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.stop_intent_marker import discard_stop_intent_marker, write_stop_intent_marker
from breezy.runtime.submit_intent import (
    CURRENT_INTENT_KEY,
    SubmitIntent,
    SubmitIntentCorrupt,
    SubmitIntentState,
)
from breezy.runtime.trade_supervisor_core import (
    LAUNCH_UTC,
    MAX_RELAUNCH_ATTEMPTS,
    MIDDAY_READINESS_RECHECK_TIMEOUT,
    MIN_RELAUNCH_GAP,
    NODE_ARGV_ANCHOR,
    PERMIT_EXPIRY_CEILING_NS_ENV_VAR,
    PERMIT_ISSUED_MARKER,
    RELAUNCH_CUTOFF_UTC,
    SELF_CHECK_ALERT_DETAIL,
    SELF_CHECK_ESCALATION_STORE_KEY,
    SELF_CHECK_GAP_ALERT_THRESHOLD_HOURS,
    SELF_CHECK_UTC,
    STOP_PRIOR_UTC,
    SUPERVISOR_ARGV_TOKEN,
    AlertDetail,
    ContinuousFamilyCheck,
    DaySchedulerState,
    EscalationLoadOutcome,
    LaunchAction,
    Phase,
    RelaunchCause,
    SelfCheckEscalationState,
    SelfCheckResult,
    StopPriorAction,
    _trading_day,
    assert_no_live_node_before_intent_probe,
    classify_exit1_cause,
    continuous_family_check,
    continuous_family_halt_key,
    continuous_family_is_halted,
    continuous_family_startup_evidence_key,
    decide_launch_action,
    decide_midday_relaunch,
    decide_relaunch,
    decide_stop_prior_action,
    decode_self_check_escalation_state,
    encode_self_check_escalation_state,
    escalated_self_check_severity,
    initial_scheduler_state,
    launch_time_ns,
    mark_phase_fired,
    midday_watch_window_end,
    next_due,
    parse_permit_expiry_ns,
    permit_expiry_valid,
    readiness_observed,
    record_child_adopted,
    record_first_boot_permit_seen,
    record_midday_alert_sent,
    record_midday_cause_seen,
    record_midday_ceiling_unknown_alert_sent,
    record_midday_not_ready_alert_sent,
    record_midday_readiness_recheck_done,
    record_midday_relaunch_attempt,
    record_permit_issued_seen,
    record_readiness_observed,
    record_relaunch_attempt,
    record_self_check_result,
    record_strategy_subscribed_seen,
    self_check,
    self_check_gap_hours,
    strategy_subscribed_in,
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
# [2026-09-12] Continuous-family self-check reads -- WP-11b (2026-09-19)
# migrated the arming source off the retired continuous-rung-hold boolean
# flag to a family-agnostic predicate over :data:`SENDING_FAMILY_ID_VAR`
# (see `sending_family_active` below). Deliberately NOT routed through
# probe_open_intent/assert_no_live_node_before_intent_probe: that guard is
# a business
# invariant scoped to the pre-launch OPEN-intent probe specifically (its own
# docstring: "[E5 scope] The probe is pre-launch ONLY"), not a technical
# limitation of SqliteStateStore -- the self-check runs at 17:05 UTC, WHILE
# the node is live, by design. Reading here is still safe: SqliteStateStore
# opens WAL (`PRAGMA journal_mode=WAL`), which serves concurrent readers
# against the node's own writer connection with no coordination needed, and
# this helper only ever calls `.get()`, on a brand-new independent
# connection -- never `.set()`, never sharing a connection or flock with the
# node's own store handle.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ContinuousFamilyStoreState:
    startup_evidence: Mapping[str, object] | None
    family_halted: bool


def _decode_startup_evidence(raw: bytes | None) -> Mapping[str, object] | None:
    """Fail-closed JSON decode of the startup-evidence record, matching
    ``TrialDayLatch.read_startup_evidence``'s own stance: absent or
    malformed is indistinguishable here from "never written". Duplicated
    rather than imported -- ``runtime`` never imports ``strategy`` (layers
    contract, ``pyproject.toml``)."""
    if raw is None:
        return None
    try:
        decoded: object = json.loads(raw.decode("utf-8"))
    except ValueError:
        return None
    if not isinstance(decoded, dict):
        return None
    return decoded


def read_continuous_family_store_state(
    store_path: Path, sending_family_id: str
) -> ContinuousFamilyStoreState:
    """Read-only via a fresh, independent ``SqliteStateStore`` connection --
    see the module note above for why this is safe while the node is live.

    WP-11b: takes the sending family id -- see
    :func:`trade_supervisor_core.continuous_family_startup_evidence_key` /
    :func:`trade_supervisor_core.continuous_family_halt_key` for why the
    keys those functions return do not vary with it today (F6,
    global-equivalent under cardinality-1).

    [2026-09-12 cross-seam fix] ``family_halted`` is NOT mere key presence:
    the store has no delete, so a legitimate ``breezy-clear-family-halt``
    run leaves the cleared sentinel in place rather than an absent key --
    see :func:`continuous_family_is_halted`.
    """
    startup_evidence_key = continuous_family_startup_evidence_key(sending_family_id)
    family_halt_key = continuous_family_halt_key(sending_family_id)
    with SqliteStateStore(store_path) as store:
        evidence = _decode_startup_evidence(store.get(startup_evidence_key))
        family_halted = continuous_family_is_halted(store.get(family_halt_key))
    return ContinuousFamilyStoreState(startup_evidence=evidence, family_halted=family_halted)


def sending_family_active() -> bool:
    """``True`` iff :data:`SENDING_FAMILY_ID_VAR` is set to a non-blank
    value -- the ONLY environment value this module ever reads for the
    continuous-family self-check block's arming decision. Family-agnostic
    (WP-11b F1): replaces the retired ``continuous_rung_hold_env_active``,
    which read the now-retired continuous-rung-hold boolean flag and so
    left the self-check block permanently unarmed for any OTHER sending
    family (e.g. a promoted ``pm_us_crh_fc_v1``). Never the
    operator-reserved caps, and never logged by value."""
    raw = os.environ.get(SENDING_FAMILY_ID_VAR)
    return raw is not None and raw.strip() != ""


def resolve_sending_family_id() -> str | None:
    """The raw :data:`SENDING_FAMILY_ID_VAR` value, or ``None`` if unset/blank.

    Separate from :func:`sending_family_active` (a bool) because
    :func:`_do_self_check` needs the actual id to pass to
    :func:`read_continuous_family_store_state`, not merely whether one is
    set."""
    raw = os.environ.get(SENDING_FAMILY_ID_VAR)
    if raw is None or not raw.strip():
        return None
    return raw


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
    store_path: Path | None = None,
    mark_stop_intent: Callable[[Path, int], None] = write_stop_intent_marker,
) -> None:
    """[L3] TOCTOU-safe SIGTERM: the stop-prior DECISION
    (:func:`decide_stop_prior_action`) and the actual signal are two
    separate moments: re-verify, immediately before sending it, that
    ``pid`` (a) still exists and (b) still resolves as the FLOCK holder of
    ``intent_lock_path_``'s inode. Either check failing raises
    ``StopPriorRaceRefused`` -- the caller refuses and alerts rather than
    signalling a PID that may since have been reused by an unrelated
    process.

    [AUD-13d HIGH-1] When ``store_path`` is given, the ONE-SHOT stop-intent
    marker is written for ``pid`` immediately before ``terminate_fn`` sends
    the signal -- never before the recheck above passes, so a race-refused
    terminate (no signal sent) leaves no marker behind. ``store_path``
    defaults to ``None`` (no marker, unchanged behaviour) so every existing
    caller of this function is untouched.

    [2026-09-24 review, HIGH] If ``terminate_fn`` itself raises -- the
    target died in the tiny window between the recheck above and the signal
    (``ProcessLookupError``) -- the marker just written would otherwise be
    orphaned for a LATER, unrelated process to be assigned that pid and have
    a genuine boot halt wrongly suppressed. The marker is discarded here,
    then the original exception is re-raised unchanged: this function's
    exception behaviour for every OTHER caller (``store_path=None``) is
    untouched.
    """
    alive_check = is_alive if is_alive is not None else process_is_alive
    if not alive_check(pid):
        raise StopPriorRaceRefused("pid no longer exists")
    if resolve_holder(intent_lock_path_) != pid:
        raise StopPriorRaceRefused("pid no longer holds the intent flock")
    if store_path is not None:
        mark_stop_intent(store_path, pid)
    try:
        terminate_fn(pid)
    except Exception:
        if store_path is not None:
            discard_stop_intent_marker(store_path)
        raise


def _proc_state_char(pid: int) -> str | None:
    """The state field of ``/proc/<pid>/stat``, or ``None`` if unreadable.

    ``comm`` (the second field) is parenthesized and may itself contain
    spaces or parentheses, so the state field is found by splitting after
    the LAST ``)`` on the line, never by positional field-splitting."""
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    after_comm = raw.rsplit(")", 1)[-1]
    fields = after_comm.split()
    return fields[0] if fields else None


# WP-0a: spawn sites used to keep only ``proc.pid`` and drop the Popen, so
# ``waitpid`` never ran and a dead child sat ``<defunct>``. Retain the
# Popen here (supervisor is single-threaded) and poll it from
# :func:`process_is_alive`. Adopted pids have no Popen and are not retained.
_SPAWNED_CHILDREN: dict[int, subprocess.Popen[bytes]] = {}


def _retain_spawned_child(proc: subprocess.Popen[bytes]) -> None:
    """Keep the Popen so ``poll``/``waitpid`` can reap it."""
    _SPAWNED_CHILDREN[proc.pid] = proc


def _reap_spawned_children() -> None:
    """``Popen.poll()`` every retained child.

    A dead pid we are not currently asking about must still be waitpid'd,
    otherwise it sits ``<defunct>`` until the supervisor exits (e.g. after
    SIGTERM at STOP_PRIOR, when ``tracked_pid`` is dropped).
    """
    for pid, proc in list(_SPAWNED_CHILDREN.items()):
        if proc.poll() is not None:
            _SPAWNED_CHILDREN.pop(pid, None)


def process_is_alive(pid: int) -> bool:
    _reap_spawned_children()
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return _proc_state_char(pid) != "Z"


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


#: Rev 3.1 R8: `BUILD_REVISION_ENV_VAR`, `_looks_like_git_sha`, `_read_ref_
#: sha` and `_read_git_head_sha` now live in `breezy.runtime.build_sha`
#: (imported above) and are re-exported here under the SAME private names
#: so this module's own tests (which import `_read_git_head_sha` directly
#: from it) stay green and unedited.


def _read_source_tree_head_sha() -> str | None:
    """The git commit of the SOURCE TREE ACTUALLY IMPORTED -- located from
    ``breezy.__file__`` (an editable install's ``src/breezy/__init__.py``;
    repo root is two levels up), never from ``sys.argv[0]``,
    ``os.getcwd()``, or any other proxy that could diverge from what this
    process actually loaded. Reflects the checked-out tree at supervisor
    START; the node is spawned later from that same tree, so this is also
    the node's revision. Returns ``None`` if no ``.git`` is resolvable
    (e.g. a non-editable install with no VCS metadata at all)."""
    repo_root = Path(breezy.__file__).resolve().parents[2]
    return _read_git_head_sha(repo_root / ".git")


def _resolve_build_revision(env: Mapping[str, str]) -> str:
    """Thin alias over :func:`breezy.runtime.build_sha.resolve_build_revision`
    (Rev 3.1 R8), for the ``supervisor_started`` ``revision`` field
    (AUD-14a).

    Passes THIS module's own ``_read_source_tree_head_sha`` as the override
    -- looked up by name at call time (a bare global reference, not a bound
    default), so this module's existing tests, which monkeypatch ``_read_
    source_tree_head_sha`` on `breezy.runtime.trade_supervisor` directly,
    keep working unedited. The node's own F-2 rows call ``resolve_build_
    revision`` directly with no override, so both resolve the identical
    build identity for the same process tree (D2 attribution join).
    """
    return _resolve_build_revision_impl(env, source_tree_head_sha=_read_source_tree_head_sha)


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
    #: [2026-09-12] Defaults preserve v2 behaviour for every test/caller that
    #: never sets these: a constant ``False`` means the continuous-family
    #: self-check block is never entered (see ``_do_self_check``).
    continuous_family_active: Callable[[], bool] = field(default=lambda: False)
    #: WP-11b: the actual sending-family id, resolved separately from the
    #: bool above so ``_do_self_check`` can pass it to
    #: ``read_continuous_family_store_state`` below.
    resolve_sending_family_id: Callable[[], str | None] = field(default=lambda: None)
    read_continuous_family_store_state: Callable[
        [Path, str], ContinuousFamilyStoreState
    ] = field(
        default=lambda _p, _f: ContinuousFamilyStoreState(
            startup_evidence=None, family_halted=False
        )
    )


def _boot_alert_sink() -> AlertSink:
    """[WP-B0] Resolve the real sink, announcing whether it can reach anyone.

    The supervisor is the FIRST thing that starts each trading day, so this
    is the earliest point at which "no operator is reachable" can be made
    visible. Loud, never fatal: an unconfigured webhook still yields a
    working ``LoggingAlertSink`` and the supervisor still starts.
    """
    log_alert_egress_status(component="trade_supervisor")
    return resolve_alert_sink()


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
        alert_sink=alert_sink if alert_sink is not None else _boot_alert_sink(),
        find_adopted_log=find_adopted_node_log,
        continuous_family_active=sending_family_active,
        resolve_sending_family_id=resolve_sending_family_id,
        read_continuous_family_store_state=read_continuous_family_store_state,
    )


# ---------------------------------------------------------------------------
# Phase handlers -- one function per Phase, each a thin composition of the
# pure decision in ``trade_supervisor_core`` and the ports above.
# ---------------------------------------------------------------------------


def _do_stop_prior(
    *, ports: SupervisorPorts, store_path: Path, tracked_pid: int | None
) -> int | None:
    """[B2/E5/L3] Returns the PID still outstanding (None if none).

    [2026-09-15 F2] ``tracked_pid`` is trusted only when it is actually
    alive. Mid-day exhaustion (``_do_midday_watch``) intentionally keeps a
    dead pid as ``tracked_pid`` for operator diagnosis (kept, not changed
    here); passing that dead pid straight into
    :func:`decide_stop_prior_action` next boot -- with no lock holder --
    manufactures a REFUSE_ALERT for a non-event. A dead/absent
    ``tracked_pid`` falls back to :func:`SupervisorPorts.find_node_pid`,
    same as when nothing was tracked at all.
    """
    lock_path = intent_lock_path(store_path)
    tracked_pid_alive = tracked_pid is not None and ports.process_alive(tracked_pid)
    discovered = tracked_pid if tracked_pid_alive else ports.find_node_pid()
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
        ports.terminate_after_recheck(
            discovered, intent_lock_path_=lock_path, store_path=store_path
        )
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
    _reap_spawned_children()
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
            return pid, log_path, record_child_adopted(state, now), True
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

    _retain_spawned_child(proc)
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
    # [fix 2026-09-05] Latch the subscribed marker into state THE MOMENT this
    # read sees it -- this poll may be the last one whose delta still holds
    # it before later polls (waiting on a permit that never comes) drain the
    # shared reader's offset past it.
    if strategy_subscribed_in(log_text):
        state = record_strategy_subscribed_seen(state, now)
    permit_expiry_ns = parse_permit_expiry_ns(log_text)
    if permit_expiry_ns is not None:
        state = record_permit_issued_seen(state, now, permit_expiry_ns)
        # [A-1] Distinct, day-level anchor -- see DaySchedulerState's own
        # docstring for why this is never merged with the per-child latch
        # just above.
        state = record_first_boot_permit_seen(state, now, permit_expiry_ns)
    holder = ports.resolve_intent_lock_holder(intent_lock_path(store_path))
    if readiness_observed(
        holds_intent_lock=(holder == tracked_pid),
        permit_issued=state.permit_issued_seen_expires_at_ns is not None,
        strategy_subscribed=state.strategy_subscribed_seen,
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
    _retain_spawned_child(proc)
    return proc.pid, new_log, record_relaunch_attempt(state, now)


def _do_midday_watch(
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
    """[2026-09-15] Mid-day sibling of :func:`_do_relaunch_check`, run for
    the rest of the trading day once SELF_CHECK's own window has closed
    (plan §3/§4 step 6).

    Short-circuits before ANY log read once ``state.midday_alert_sent`` is
    latched -- the mid-day budget is exhausted and the operator has
    already been alerted exactly once; redoing full decision work every
    poll for the rest of the day would serve no purpose.

    Keeps latching any accepted rung-hold subscribe prefix (see
    :func:`strategy_subscribed_in`)/the permit-issued
    line and the first non-``UNKNOWN`` :func:`classify_exit1_cause` result
    on EVERY poll, alive or dead -- the same drain-safe pattern
    ``_do_relaunch_check`` already uses, guarding against a fatal-fault
    marker the shared, offset-draining ``IncrementalLogReader`` has
    already consumed past by the poll that first observes the process
    dead.

    The per-poll flock probe (:attr:`SupervisorPorts.resolve_intent_lock_holder`)
    is called ONLY inside the bounded post-relaunch readiness re-check
    below -- never on the steady-state "still alive" poll (plan §3
    "Dropped per-poll flock probe"): that gate alone removes ~470
    pointless ``/proc/locks`` reads/day in the common, no-incident case.

    **Contract, explicit and opposite of boot's**: on any mid-day decline
    -- mid-budget or exhausted -- this returns the SAME ``tracked_pid`` it
    was given, never ``None`` (contrast :func:`_do_relaunch_check`'s own
    ``return None, node_log, state`` on decline, correct for boot since
    that window is genuinely over). Keeping the dead PID visible names it
    in every subsequent :func:`log_decision` line for operator diagnosis.
    """
    if state.midday_alert_sent:
        return tracked_pid, node_log, state
    if tracked_pid is None or node_log is None:
        return tracked_pid, node_log, state

    log_text = ports.read_log_new(node_log)
    if strategy_subscribed_in(log_text):
        state = record_strategy_subscribed_seen(state, now)
    permit_expiry_ns = parse_permit_expiry_ns(log_text)
    if permit_expiry_ns is not None:
        state = record_permit_issued_seen(state, now, permit_expiry_ns)
        # [A-1] Distinct, day-level anchor -- see DaySchedulerState's own
        # docstring for why this is never merged with the per-child latch
        # just above.
        state = record_first_boot_permit_seen(state, now, permit_expiry_ns)
    live_cause = classify_exit1_cause(log_text)
    if live_cause is not RelaunchCause.UNKNOWN:
        state = record_midday_cause_seen(state, now, live_cause)

    if ports.process_alive(tracked_pid):
        relaunched_at = state.last_midday_relaunch_attempt_at
        if relaunched_at is not None and not state.midday_readiness_recheck_done:
            holder = ports.resolve_intent_lock_holder(intent_lock_path(store_path))
            ready = readiness_observed(
                holds_intent_lock=(holder == tracked_pid),
                permit_issued=state.permit_issued_seen_expires_at_ns is not None,
                strategy_subscribed=state.strategy_subscribed_seen,
            )
            if ready:
                return tracked_pid, node_log, record_midday_readiness_recheck_done(state, now)
            if (now - relaunched_at) > MIDDAY_READINESS_RECHECK_TIMEOUT:
                log_decision(
                    "midday_relaunched_child_not_ready", phase="midday_watch", pid=tracked_pid
                )
                alert(
                    ports.alert_sink,
                    event="TRADE_SUPERVISOR_MIDDAY_WATCH",
                    severity="WARN",
                    detail=AlertDetail.MIDDAY_RELAUNCHED_CHILD_NOT_READY,
                )
                state = record_midday_not_ready_alert_sent(state, now)
                return tracked_pid, node_log, record_midday_readiness_recheck_done(state, now)
        return tracked_pid, node_log, state

    cause = state.midday_cause_seen if state.midday_cause_seen is not None else live_cause

    # [A-1, 2026-09-25] Fail-closed gate, checked FIRST and unconditionally --
    # independent of the budget/window decision below. A mid-day relaunch
    # without a known first-boot anchor would mint a fresh, unbounded
    # +PERMIT_TTL_NS permit (the exact defect A-1 closes), so this never
    # reaches `decide_midday_relaunch`/`ports.spawn` at all. Accepted failure
    # surface (ruling doc): if the FIRST child dies between writing its
    # permit line and the next poll, this anchor stays `None` and every
    # mid-day relaunch for the rest of the day is declined here.
    if state.first_boot_permit_expires_at_ns is None:
        log_decision(
            "midday_relaunch_declined",
            phase="midday_watch",
            reason="first-boot permit expiry unknown",
        )
        if not state.midday_ceiling_unknown_alert_sent:
            log_decision(
                "midday_relaunch_ceiling_unknown", phase="midday_watch", pid=tracked_pid
            )
            alert(
                ports.alert_sink,
                event="TRADE_SUPERVISOR_MIDDAY_WATCH",
                severity="CRITICAL",
                detail=AlertDetail.MIDDAY_RELAUNCH_CEILING_UNKNOWN,
            )
            state = record_midday_ceiling_unknown_alert_sent(state, now)
        return tracked_pid, node_log, state

    decision = decide_midday_relaunch(
        now=now,
        window_end=midday_watch_window_end(state.day),
        attempts_so_far=state.midday_relaunch_attempts,
        last_attempt_at=state.last_midday_relaunch_attempt_at,
        cause=cause,
    )
    if not decision.should_relaunch:
        log_decision("midday_relaunch_declined", phase="midday_watch", reason=decision.reason)
        if decision.reason == "attempt budget exhausted":
            log_decision("midday_relaunch_exhausted", phase="midday_watch", pid=tracked_pid)
            alert(
                ports.alert_sink,
                event="TRADE_SUPERVISOR_MIDDAY_WATCH",
                severity="CRITICAL",
                detail=AlertDetail.MIDDAY_RELAUNCH_EXHAUSTED,
            )
            state = record_midday_alert_sent(state, now)
        return tracked_pid, node_log, state

    log_decision(
        "midday_relaunching", phase="midday_watch", attempt=state.midday_relaunch_attempts + 1
    )
    new_log = node_log_path(log_dir, now)
    # [A-1] Cap the relaunched child's permit at the day's first-boot expiry
    # -- a copy of the environment, never a mutation of `os.environ` itself
    # (which `_do_launch`'s own 16:50Z daily-boot spawn still forwards
    # as-is, with no ceiling).
    child_env = dict(os.environ)
    child_env[PERMIT_EXPIRY_CEILING_NS_ENV_VAR] = str(state.first_boot_permit_expires_at_ns)
    proc = ports.spawn(node_bin=node_bin, repo_root=repo_root, env=child_env, log_path=new_log)
    _retain_spawned_child(proc)
    return proc.pid, new_log, record_midday_relaunch_attempt(state, now)


#: Self-check results that are a PASS of some kind -- never alerted on.
_SELF_CHECK_PASS_RESULTS: Final[frozenset[SelfCheckResult]] = frozenset(
    {SelfCheckResult.PASS, SelfCheckResult.PASS_ADOPTED_LOG_UNKNOWN}
)


def _load_self_check_escalation(
    store_path: Path,
) -> tuple[SelfCheckEscalationState, EscalationLoadOutcome]:
    """[AUD-14b] The LOAD step of the escalation record's read-decide-write
    bracket. Read-only via a fresh, independent ``SqliteStateStore``
    connection -- matches :func:`read_continuous_family_store_state`'s own
    pattern -- so boot, a trading-day rollover, and a supervisor restart
    collapse into the same case: the value is re-read fresh every time.

    Never alerts itself: outcome classification only. The caller
    (:func:`_do_self_check`) decides severity and emits, per this module's
    DECIDE -> EMIT -> PERSIST ordering. The exception (on ``UNAVAILABLE``)
    is contained here alone and logged by TYPE only, matching this
    module's value-free stance -- never the exception message.
    """
    try:
        with SqliteStateStore(store_path) as store:
            raw = store.get(SELF_CHECK_ESCALATION_STORE_KEY)
    except Exception as exc:  # noqa: BLE001 -- deliberate, see docstring.
        log_decision("self_check_escalation_load_failed", error_type=type(exc).__name__)
        return SelfCheckEscalationState(), EscalationLoadOutcome.UNAVAILABLE
    if raw is None:
        return SelfCheckEscalationState(), EscalationLoadOutcome.ABSENT
    decoded = decode_self_check_escalation_state(raw)
    if decoded is None:
        return SelfCheckEscalationState(), EscalationLoadOutcome.CORRUPT
    return decoded, EscalationLoadOutcome.PRESENT


def _do_self_check(
    *,
    ports: SupervisorPorts,
    now: dt.datetime,
    store_path: Path,
    log_dir: Path,
    tracked_pid: int | None,
    node_log: Path | None,
    state: DaySchedulerState | None = None,
) -> tuple[int | None, Path | None, DaySchedulerState | None]:
    """[B4/E3/D2] One PASS/FAIL line, and an alert through the shared sink
    on FAIL with a fixed enum ``detail``. Adopts a live verified flock
    holder FIRST when nothing was tracked -- a supervisor that restarted
    after 17:00 with a healthy node already running must not report
    ``FAIL_CHILD_EXITED`` for it. Returns the (possibly adopted)
    ``(tracked_pid, node_log, state)`` for the caller to keep carrying
    forward.

    ``state`` is optional (defaults to ``None``) so a caller with no
    scheduler state to thread through (e.g. a direct unit test of this
    handler alone) still gets the old log-only ``strategy_subscribed``
    behaviour. When supplied, [fix 2026-09-05] ``strategy_subscribed`` is
    the sticky ``state.strategy_subscribed_seen`` latch OR'd with this
    call's own live read -- RELAUNCH_CHECK's polling shares ONE
    offset-draining ``IncrementalLogReader`` with this handler, so by the
    time SELF_CHECK runs, the marker text the strategy emitted once at boot
    may already be outside every reader delta; the latch is what makes that
    survive [see ``DaySchedulerState.strategy_subscribed_seen``].
    [fix 2026-09-06] The same latch applies to the permit-issued line:
    ``permit_issued`` is latched-or-live, and ``permit_expiry_valid`` is
    evaluated against the latched ``expires_at_ns`` (or this call's live
    delta if that is the first sighting)."""
    lock_path = intent_lock_path(store_path)
    if tracked_pid is None:
        adoption = _attempt_adoption(ports=ports, lock_path=lock_path, log_dir=log_dir)
        if adoption is not None:
            tracked_pid, node_log = adoption
            log_decision("self_check_adopted_live_node", pid=tracked_pid)
            if state is not None:
                state = record_child_adopted(state, now)

    holder = ports.resolve_intent_lock_holder(lock_path)
    holder_count = ports.count_intent_lock_holders(lock_path)
    log_text = ports.read_log_new(node_log) if node_log is not None else ""
    child_alive = tracked_pid is not None and ports.process_alive(tracked_pid)

    strategy_subscribed_live = strategy_subscribed_in(log_text)
    permit_issued_live = PERMIT_ISSUED_MARKER in log_text
    live_permit_expiry_ns = parse_permit_expiry_ns(log_text)
    now_ns = int(now.timestamp() * 1e9)
    if state is not None:
        if strategy_subscribed_live and not state.strategy_subscribed_seen:
            state = record_strategy_subscribed_seen(state, now)
        strategy_subscribed = state.strategy_subscribed_seen
        if live_permit_expiry_ns is not None and state.permit_issued_seen_expires_at_ns is None:
            state = record_permit_issued_seen(state, now, live_permit_expiry_ns)
        if live_permit_expiry_ns is not None:
            # [A-1] Distinct, day-level anchor -- idempotent, so calling it
            # unconditionally (whenever a permit-issued line is observed)
            # is safe even when the per-child latch above was skipped.
            state = record_first_boot_permit_seen(state, now, live_permit_expiry_ns)
        latched_permit_expiry_ns = state.permit_issued_seen_expires_at_ns
        permit_issued = latched_permit_expiry_ns is not None or permit_issued_live
        if latched_permit_expiry_ns is not None:
            expiry_valid = latched_permit_expiry_ns > now_ns
        else:
            expiry_valid = permit_expiry_valid(log_text, now_ns=now_ns)
        # [A-1 follow-up, 2026-09-25] Distinguish a permit whose expiry
        # equals the day's first-boot ceiling anchor -- A-1's clamp working
        # as designed, never a genuine refusal. ``relaunch_attempts > 0`` is
        # the only observable signal separating "this child's own permit IS
        # the anchor's source" (the never-relaunched original boot, where
        # the values trivially match) from "this child's permit was CLAMPED
        # to a pre-existing anchor" -- a clamped permit's log line is
        # byte-identical in shape to a fresh one (ruling doc §2/§4).
        observed_expiry_ns = (
            latched_permit_expiry_ns
            if latched_permit_expiry_ns is not None
            else live_permit_expiry_ns
        )
        permit_expiry_at_daily_ceiling = (
            observed_expiry_ns is not None
            and state.first_boot_permit_expires_at_ns is not None
            and observed_expiry_ns == state.first_boot_permit_expires_at_ns
            and state.relaunch_attempts > 0
        )
    else:
        strategy_subscribed = strategy_subscribed_live
        permit_issued = permit_issued_live
        expiry_valid = permit_expiry_valid(log_text, now_ns=now_ns)
        permit_expiry_at_daily_ceiling = False

    continuous_check: ContinuousFamilyCheck | None = None
    if ports.continuous_family_active():
        sending_family_id = ports.resolve_sending_family_id() or ""
        store_state = ports.read_continuous_family_store_state(store_path, sending_family_id)
        launch_day = state.day if state is not None else now.date()
        continuous_check = continuous_family_check(
            log_text=log_text,
            startup_evidence=store_state.startup_evidence,
            family_halted=store_state.family_halted,
            launch_ns=launch_time_ns(launch_day),
        )

    result = self_check(
        child_alive=child_alive,
        flock_holder_count=holder_count,
        flock_held_by_tracked_pid=(tracked_pid is not None and holder == tracked_pid),
        permit_issued=permit_issued,
        permit_expiry_valid=expiry_valid,
        strategy_subscribed=strategy_subscribed,
        log_available=node_log is not None,
        continuous_check=continuous_check,
        permit_expiry_at_daily_ceiling=permit_expiry_at_daily_ceiling,
    )
    # [AUD-14b] Repeat-failure escalation -- a separate, store-backed
    # record, re-read fresh at every self-check (see
    # `_load_self_check_escalation`'s docstring). Bracket ordering is
    # DECIDE -> EMIT -> PERSIST throughout: a write that never happens
    # (crash/restart between decide and persist) can only ever produce a
    # DUPLICATE escalation on the next FAIL, never a LOST one.
    escalation_state, load_outcome = _load_self_check_escalation(store_path)
    now_utc_iso = now.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")
    gap_hours = self_check_gap_hours(
        last_self_check_utc=escalation_state.last_self_check_utc, now_utc=now
    )

    log_fields: dict[str, int | str] = {"result": result.value}
    if continuous_check is not None:
        log_fields.update(
            continuous_phase0_clean=continuous_check.phase0_clean,
            continuous_startup_evidence_valid=continuous_check.startup_evidence_valid,
            continuous_family_not_halted=continuous_check.family_not_halted,
        )
    if load_outcome is EscalationLoadOutcome.ABSENT:
        # The only outcome permitted to be silent -- the count is known
        # (zero), just never previously observed.
        log_fields["escalation_state"] = "absent"
    if gap_hours is not None and gap_hours > SELF_CHECK_GAP_ALERT_THRESHOLD_HOURS:
        log_fields["self_check_gap_hours"] = int(gap_hours)
    log_decision("self_check", **log_fields)

    if load_outcome is EscalationLoadOutcome.CORRUPT:
        alert(
            ports.alert_sink,
            event="TRADE_SUPERVISOR_SELF_CHECK_ESCALATION_STATE_CORRUPT",
            severity="WARN",
            detail=AlertDetail.SELF_CHECK_ESCALATION_STATE_CORRUPT,
        )
    elif load_outcome is EscalationLoadOutcome.UNAVAILABLE:
        alert(
            ports.alert_sink,
            event="TRADE_SUPERVISOR_SELF_CHECK_ESCALATION_STORE_UNAVAILABLE",
            severity="WARN",
            detail=AlertDetail.SELF_CHECK_ESCALATION_STORE_UNAVAILABLE,
        )

    new_escalation_state = record_self_check_result(
        escalation_state, result.value, now_utc=now_utc_iso
    )
    count_known = load_outcome in (EscalationLoadOutcome.ABSENT, EscalationLoadOutcome.PRESENT)
    severity = escalated_self_check_severity(
        result_is_fail=result not in _SELF_CHECK_PASS_RESULTS,
        consecutive_failures=new_escalation_state.consecutive_failures,
        count_known=count_known,
    )
    if severity == "CRITICAL":
        if count_known:
            detail = SELF_CHECK_ALERT_DETAIL[result]
        elif load_outcome is EscalationLoadOutcome.CORRUPT:
            detail = AlertDetail.SELF_CHECK_ESCALATION_STATE_CORRUPT
        else:
            detail = AlertDetail.SELF_CHECK_ESCALATION_STORE_UNAVAILABLE
        alert(
            ports.alert_sink,
            event="TRADE_SUPERVISOR_SELF_CHECK_FAIL_REPEATED",
            severity="CRITICAL",
            detail=detail,
        )
    elif severity == "WARN":
        alert(
            ports.alert_sink,
            event="TRADE_SUPERVISOR_SELF_CHECK_FAIL",
            severity="WARN",
            detail=SELF_CHECK_ALERT_DETAIL[result],
        )

    try:
        with SqliteStateStore(store_path) as store:
            store.set(
                SELF_CHECK_ESCALATION_STORE_KEY,
                encode_self_check_escalation_state(new_escalation_state),
            )
    except Exception as exc:  # noqa: BLE001 -- contained; named by TYPE only.
        log_decision("self_check_escalation_state_write_failed", error_type=type(exc).__name__)
        alert(
            ports.alert_sink,
            event="TRADE_SUPERVISOR_SELF_CHECK_ESCALATION_STATE_WRITE_FAILED",
            severity="WARN",
            detail=AlertDetail.SELF_CHECK_ESCALATION_STATE_WRITE_FAILED,
        )

    return tracked_pid, node_log, state


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
                revision=_resolve_build_revision(os.environ),
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
    state = initial_scheduler_state(_trading_day(clock()))
    tracked_pid: int | None = None
    node_log: Path | None = None
    iterations = 0

    try:
        while max_iterations is None or iterations < max_iterations:
            iterations += 1
            now = clock()
            phase, _fire_at = next_due(now, state)

            if phase is Phase.NONE:
                # WP-0a review residual: a child SIGTERM'd at STOP_PRIOR is
                # reaped there via a bounded poll loop, but if it happens to
                # outlive that ~10 s window (e.g. slow shutdown), NOTHING
                # else called `_reap_spawned_children()` until the phase
                # machinery next made a port call -- which, since Phase.NONE
                # is exactly the "nothing due" idle state, could be hours
                # away (the next day's RELAUNCH_CHECK at worst). A
                # `<defunct>` process sitting that long in a long-lived
                # systemd unit's process table has caused a production
                # incident in this repo before (WP-0a's own motivation).
                # Reaping here bounds the window to one poll interval
                # (`_SCHEDULE_POLL_INTERVAL_S`, currently 60 s) instead.
                _reap_spawned_children()
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
                elif phase is Phase.SELF_CHECK:
                    tracked_pid, node_log, new_state = _do_self_check(
                        ports=active_ports,
                        now=now,
                        store_path=store_path,
                        log_dir=log_dir,
                        tracked_pid=tracked_pid,
                        node_log=node_log,
                        state=state,
                    )
                    if new_state is not None:
                        state = new_state
                    state = mark_phase_fired(state, phase, now)
                elif phase is Phase.MIDDAY_WATCH:
                    tracked_pid, node_log, state = _do_midday_watch(
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
                    # Defensive: a future third new `Phase` must never
                    # silently fall through into `_do_self_check` (the
                    # original bug this dispatch fixed) -- named and
                    # dropped instead.
                    log_decision("phase_unhandled", phase=phase.value)
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
