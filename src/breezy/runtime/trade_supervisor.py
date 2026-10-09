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
import re
import resource
import signal
import subprocess
import sys
import time as _time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Final, Literal, TextIO

import breezy
from breezy.domain.exec_intent import RESOLVER_CONTEXT_KEY_PREFIX
from breezy.runtime.alert_outbox import AlertOutbox, DeliveryRecordWriter, default_alerts_root
from breezy.runtime.alert_proof import COUNTERS as _ALERT_COUNTERS
from breezy.runtime.alert_proof import deliver_with_proof
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
    alert_egress_configured,
    emit_alert,
    log_alert_egress_status,
    resolve_alert_sink,
)
from breezy.runtime.process_lookup import find_pid_by_argv
from breezy.runtime.settings import SENDING_FAMILY_ID_VAR
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.stop_intent_marker import discard_stop_intent_marker, write_stop_intent_marker
from breezy.runtime.submit_intent import (
    CURRENT_INTENT_KEY,
    SubmitIntent,
    SubmitIntentCorrupt,
    SubmitIntentState,
)
from breezy.runtime.supervisor_decode_marker import (
    discard_supervisor_decode_marker,
    write_supervisor_decode_marker,
)
from breezy.runtime.trade_supervisor_core import (
    _PERMIT_FAIL_SELF_CHECK_RESULTS,
    _SCHEDULE_POLL_INTERVAL_S,
    BOOT_RETRY_READINESS_TIMEOUT,
    CONTINUOUS_LEGACY_FAMILY_HALT_KEY,
    LAUNCH_UTC,
    LAUNCH_WINDOW_END_UTC,
    MAX_RELAUNCH_ATTEMPTS,
    MIDDAY_READINESS_RECHECK_TIMEOUT,  # noqa: F401 - re-exported: moved/used via this module's namespace
    MIN_RELAUNCH_GAP,
    NODE_ARGV_ANCHOR,
    NODE_LOG_NAME_RE,
    PERMIT_EXPIRY_CEILING_NS_ENV_VAR,
    PERMIT_ISSUED_MARKER,  # noqa: F401 - re-exported: moved/used via this module's namespace
    PERMIT_NOT_REQUESTED_MARKER,
    READY_ADOPTION_EVIDENCE_TERMINALS,
    RELAUNCH_CUTOFF_UTC,
    SELF_CHECK_ALERT_DETAIL,  # noqa: F401 - re-exported: moved/used via this module's namespace
    SELF_CHECK_ESCALATION_STORE_KEY,
    SELF_CHECK_GAP_ALERT_THRESHOLD_HOURS,  # noqa: F401 - re-exported: moved/used via this module's namespace
    SELF_CHECK_UTC,
    SELF_CHECK_WINDOW_END_UTC,
    STOP_PRIOR_UTC,
    SUPERVISOR_ARGV_TOKEN,
    AlertDetail,
    AlertSpec,
    ContinuousFamilyCheck,
    DaySchedulerState,
    EscalationLoadOutcome,
    LaunchAction,
    MiddayDeadAction,
    MiddayRecheckAction,
    OpenIntentShape,
    PermitAlertAction,
    PermitAlertDecision,
    PermitCapability,
    Phase,
    ReadyAdoptionVerdict,
    RelaunchCause,
    SelfCheckEscalationState,
    StopPriorAction,
    _trading_day,
    assert_no_live_node_before_intent_probe,
    boot_retry_window_closed,
    classify_exit1_cause,
    continuous_family_check,
    continuous_family_halt_key,
    continuous_family_halt_state,
    continuous_family_startup_evidence_key,
    decide_boot_retry,
    decide_launch_action,
    decide_midday_dead_child,
    decide_midday_recheck,
    decide_midday_relaunch,  # noqa: F401 - re-exported: moved/used via this module's namespace
    decide_permit_alert,
    decide_ready_adoption,
    decide_ready_adoption_alert,
    decide_relaunch,
    decide_stop_prior_action,
    decode_self_check_escalation_state,
    derive_self_check_facts,
    encode_self_check_escalation_state,
    escalated_self_check_severity,  # noqa: F401 - re-exported: moved/used via this module's namespace
    initial_scheduler_state,
    is_deferral,
    latch_log_facts,
    latch_midday_log_facts,
    latest_liveness_line_ns,
    launch_time_ns,
    mark_phase_fired,
    midday_boot_retry_dispatch_due,
    midday_budget_live,
    midday_handler_reads_log,
    midday_recheck_pending,
    midday_watch_idle,
    midday_watch_window_end,
    next_due,
    node_log_spawned_at,
    parse_permit_expiry_ns,
    permit_capability_valid,
    permit_expiry_valid,  # noqa: F401 - re-exported: moved/used via this module's namespace
    permit_watch_window,
    phase_exception_marks_fired,
    phase_poll_interval_s,
    readiness_observed,
    record_adoption_log_unreadable_poll,
    record_boot_retry_attempt,
    record_boot_retry_exhausted_alert_sent,
    record_boot_retry_first_attempt_alert_sent,
    record_boot_retry_nontransient_alert_sent,
    record_boot_retry_not_ready_alert_sent,
    record_boot_retry_unknown_log_fallback_warned,
    record_boot_retry_window_closed_alert_sent,
    record_boot_zero_instruments_seen,
    record_child_adopted,
    record_first_boot_permit_seen,
    record_launch_to_resolve_page_defers,
    record_liveness_line_seen,
    record_midday_alert_sent,
    record_midday_cause_seen,
    record_midday_ceiling_unknown_alert_sent,
    record_midday_not_ready_alert_sent,
    record_midday_readiness_recheck_done,
    record_midday_relaunch_attempt,
    record_orders_not_requested_seen,
    record_permit_alert_sent,
    record_permit_deferred_since,
    record_permit_gap_info_logged,
    record_permit_issued_seen,
    record_permit_not_required_warned,
    record_readiness_observed,
    record_ready_adoption,
    record_ready_adoption_alert_sent,
    record_ready_adoption_deferral,
    record_ready_adoption_terminal_logged,
    record_relaunch_attempt,
    record_self_check_result,
    record_strategy_subscribed_seen,
    reset_ready_adoption_deferral,
    seed_permit_alert,
    self_check,
    self_check_gap_hours,
    self_check_load_alert,
    self_check_log_fields,
    self_check_result_alert,
    strategy_subscribed_in,
    zero_instruments_refusal_in,
)
from breezy.runtime.trade_supervisor_core import (
    _RELAUNCH_POLL_INTERVAL_S as _RELAUNCH_POLL_INTERVAL_S,  # noqa: PLC0414 - explicit re-export for mypy
)
from breezy.runtime.trade_supervisor_core import (
    _SELF_CHECK_PASS_RESULTS as _SELF_CHECK_PASS_RESULTS,  # noqa: PLC0414 - explicit re-export for mypy
)

logger = logging.getLogger(__name__)
_BOOT_RETRY_UNKNOWN_LOG_FALLBACK_REASON: Final[str] = "unowned_unknown_log"

EXIT_OK: Final[int] = 0
EXIT_RUNTIME_ERROR: Final[int] = 1
EXIT_CONFIG_ERROR: Final[int] = 2

NODE_CONSOLE_SCRIPT: Final[str] = "breezy-trade"
SUPERVISOR_LOCK_FILENAME: Final[str] = "trade-supervisor.lock"

_SIGTERM_WAIT_S: Final[float] = 10.0
_SIGTERM_POLL_ATTEMPTS: Final[int] = 20
_SIGTERM_POLL_INTERVAL_S: Final[float] = 0.5

#: The real ``/proc/locks`` path. A parameter (not a hardcoded literal)
#: everywhere it is read, so tests can point at a synthetic file with real
#: dev/inode-matching content instead of the kernel's own table.
DEFAULT_PROC_LOCKS_PATH: Final[Path] = Path("/proc/locks")

#: Adoption-only boot evidence replay cap. The permit/subscription lines are
#: boot-time facts near the front of the child log; the cap prevents a restarted
#: supervisor from reading an unbounded multi-hour log prefix on adoption.
_ADOPTION_LOG_REPLAY_MAX_BYTES: Final[int] = 2 * 1024 * 1024

#: [SUP-ADOPT-PERMIT] How many consecutive polls an adoption-time boot-log
#: replay may fail with ``OSError`` before B1 stops silently retrying and
#: fails loud via the existing D8 ``WATCH_FAILED`` containment. No existing
#: attempt-budget constant fits: `MAX_RELAUNCH_ATTEMPTS`/
#: `MIDDAY_MAX_RELAUNCH_ATTEMPTS`/`BOOT_RETRY_MAX_ATTEMPTS` all budget
#: process-relaunch attempts, not read retries of an already-alive child's
#: log.
_ADOPTION_LOG_UNREADABLE_MAX_POLLS: Final[int] = 3

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


def probe_open_intent_resolvable(store_path: Path, *, node_pid: int | None) -> bool:
    """[AMBIG-LATCH-RESUME Phase A, CM1] ``True`` iff the singleton DECODES
    and is OPEN -- i.e. the node's resolver can retire it, so the supervisor
    launches the node instead of stranding the intent (L-48).

    A corrupt singleton is ``False`` (today's refusal stays): the node's
    resolver treats corrupt as OPEN-unknown and never retires it. Same
    no-live-node guard and fresh read-only connection as
    :func:`probe_open_intent`; needs no adapter import and no context read.
    """
    assert_no_live_node_before_intent_probe(node_pid)
    with SqliteStateStore(store_path) as store:
        raw = store.get(CURRENT_INTENT_KEY)
        if raw is None:
            return False
        try:
            record = SubmitIntent.from_bytes(raw)
        except SubmitIntentCorrupt:
            return False
        return record.state is SubmitIntentState.OPEN


def probe_open_intent_shape(store_path: Path, *, node_pid: int | None) -> OpenIntentShape:
    """[AMBIG-LATCH-RESUME Phase A, DH1] Classify the OPEN intent by its
    durable resolver context (one read-only ``get`` of
    ``RESOLVER_CONTEXT_KEY_PREFIX + intent_id``), to pick the alert severity.

    ``WITH_ID``: ``venueOrderId`` is a non-empty string. ``NO_ID``:
    ``venueOrderId == ""``. ``NO_CONTEXT``: the key is absent. ``UNKNOWN``:
    anything undecodable, an unreadable singleton or store, or any exception
    -- the fail-loud direction. Same no-live-node guard as
    :func:`probe_open_intent`.
    """
    assert_no_live_node_before_intent_probe(node_pid)
    try:
        with SqliteStateStore(store_path) as store:
            raw_intent = store.get(CURRENT_INTENT_KEY)
            if raw_intent is None:
                return OpenIntentShape.UNKNOWN
            intent = SubmitIntent.from_bytes(raw_intent)
            raw_context = store.get(f"{RESOLVER_CONTEXT_KEY_PREFIX}{intent.intent_id}")
        if raw_context is None:
            return OpenIntentShape.NO_CONTEXT
        payload = json.loads(raw_context)
        venue_order_id = payload.get("venueOrderId") if isinstance(payload, dict) else None
        if not isinstance(venue_order_id, str):
            return OpenIntentShape.UNKNOWN
        return OpenIntentShape.WITH_ID if venue_order_id else OpenIntentShape.NO_ID
    except Exception:  # noqa: BLE001 -- deliberate: every failure is UNKNOWN (loud).
        return OpenIntentShape.UNKNOWN


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
    family_halt_source: str = "none"
    family_halt_legacy: str = "absent"


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
    see :func:`continuous_family_halt_state`.
    """
    startup_evidence_key = continuous_family_startup_evidence_key(sending_family_id)
    halt_key = continuous_family_halt_key(sending_family_id)
    with SqliteStateStore(store_path) as store:
        evidence = _decode_startup_evidence(store.get(startup_evidence_key))
        halt_state = continuous_family_halt_state(
            sending_family_id,
            store.get(CONTINUOUS_LEGACY_FAMILY_HALT_KEY),
            store.get(halt_key),
        )
    return ContinuousFamilyStoreState(
        startup_evidence=evidence,
        family_halted=halt_state.halted,
        family_halt_source=halt_state.source,
        family_halt_legacy=halt_state.legacy,
    )


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

#: [FU-17] Distinct from ``_SPAWNED_CHILDREN`` above: NEVER popped by
#: ``owned()`` -- a genuinely dead pid this supervisor spawned must still
#: resolve as "owned" (see ``owned``'s own docstring). Pruned only at
#: trading-day rollover by ``_prune_supervisor_spawned`` (bounded growth).
_SUPERVISOR_SPAWNED: dict[int, subprocess.Popen[bytes]] = {}


def _retain_spawned_child(proc: subprocess.Popen[bytes]) -> None:
    """Keep the Popen so ``poll``/``waitpid`` can reap it."""
    _SPAWNED_CHILDREN[proc.pid] = proc
    _SUPERVISOR_SPAWNED[proc.pid] = proc


def owned(pid: int, *, process_alive: Callable[[int], bool]) -> bool:
    """[FU-17, AC16] True iff ``pid`` is a process THIS supervisor itself
    spawned (recorded in ``_SUPERVISOR_SPAWNED`` by every spawn call site,
    via :func:`_retain_spawned_child`), UNLESS our own ``Popen`` shows it
    has already exited while the OS-level pid is somehow still alive (pid
    reuse: whatever is now running at that pid is no longer ours, so this
    returns ``False`` rather than falsely trusting a stale record). A
    genuinely dead pid we spawned (``Popen.poll()`` non-``None`` AND the OS
    agrees it is gone) is still ``owned`` -- boot-retry's entry guard relies
    on recognizing its own, now-dead retry children."""
    proc = _SUPERVISOR_SPAWNED.get(pid)
    if proc is None:
        return False
    reused = proc.poll() is not None and process_alive(pid)
    return not reused


def _prune_supervisor_spawned() -> None:
    """[FU-17, AM-4] Bounded growth: ``_SUPERVISOR_SPAWNED`` is never popped
    by ``owned()`` itself (a genuinely dead pid must still resolve as
    owned), so without this it would grow by one entry per boot-retry/
    relaunch spawn forever. Called once per trading-day rollover
    (``_do_stop_prior``, 16:40Z): drops every entry whose ``Popen`` has
    already exited -- a live entry (still possibly polled by ``owned()``
    today) is left alone."""
    for pid, proc in list(_SUPERVISOR_SPAWNED.items()):
        if proc.poll() is not None:
            _SUPERVISOR_SPAWNED.pop(pid, None)


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

    def read_from_start_and_mark_consumed(
        self, path: Path, *, max_bytes: int = _ADOPTION_LOG_REPLAY_MAX_BYTES
    ) -> str:
        """Adoption-only replay from byte 0, then resume tailing at EOF.

        [SUP-ADOPT-PERMIT] Unlike ``read_new``, an ``OSError`` here is NOT
        swallowed into an empty-string return: this is a one-shot boot-
        evidence replay, and silently returning "" would be indistinguishable
        from "log read cleanly, no permit marker yet" -- exactly the
        false-positive ``PermitCapability.ABSENT`` CRITICAL this method
        exists to prevent. The caller
        (``_permit_watch_replay_boot_log_on_adoption``) catches this to
        retry rather than misclassify.
        """
        size = path.stat().st_size
        with open(path, "rb") as fh:
            new_bytes = fh.read(min(size, max_bytes))
        self._offsets[path] = size
        combined = new_bytes.decode("utf-8", errors="replace")
        self._carry[path] = combined[-self._carry_bytes :] if combined else ""
        return combined

    def bytes_read(self, path: Path) -> int:
        """Test/introspection helper: total bytes consumed from ``path``
        across every ``read_new`` call so far."""
        return self._offsets.get(path, 0)


def _read_log_from_start(path: Path) -> str:
    """[SUP-ADOPT-PERMIT] Default ``read_log_from_start`` port. Deliberately
    does not catch ``OSError`` -- see
    ``IncrementalLogReader.read_from_start_and_mark_consumed``."""
    with open(path, "rb") as fh:
        return fh.read(_ADOPTION_LOG_REPLAY_MAX_BYTES).decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Spawning the node [R6].
# ---------------------------------------------------------------------------


def node_log_path(log_dir: Path, now: dt.datetime) -> Path:
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    return log_dir / f"breezy-trade-{stamp}.log"


#: [SUP-ADOPT-LOG-GLOB] The exact shape ``node_log_path`` produces --
#: kept immediately adjacent to it so the two cannot drift apart.
#: ``find_adopted_node_log`` must match ONLY this: the supervisor's own logs
#: (``breezy-trade-supervisor.log`` and its ``-stdout-``/``.launch-``
#: variants) all share the ``breezy-trade-`` prefix but must never qualify
#: as an adopted node's log.
#: [SUP-RESTART-ANYTIME] The pattern now lives in (stdlib-only) core as the
#: public ``NODE_LOG_NAME_RE`` (one capture group around the stamp); this
#: module keeps the historical private name as an alias of the same object.
_NODE_LOG_NAME_RE: Final[re.Pattern[str]] = NODE_LOG_NAME_RE


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
    """[D2/SUP-ADOPT-LOG-GLOB] Best-effort: the newest NODE-stamped log
    (matching ``_NODE_LOG_NAME_RE``, i.e. exactly what ``node_log_path``
    produces) under ``log_dir`` whose mtime is at or after ``pid``'s own
    process-start time -- ``None`` if that can't be determined (unreadable
    ``/proc/<pid>``, or no candidate log qualifies), in which case the
    caller degrades gracefully rather than guessing.

    Deliberately narrower than a ``breezy-trade-*.log`` glob: the
    supervisor's own logs (``breezy-trade-supervisor.log`` and its
    ``-stdout-``/``.launch-`` variants) share that prefix, and a freshly
    restarted supervisor writes one just after adoption -- newer than any
    node log -- which a looser glob would wrongly return, producing a false
    ``PermitCapability.ABSENT`` CRITICAL when that supervisor log lacks a
    permit line."""
    start = _process_start_time(pid)
    if start is None:
        return None
    try:
        candidates = sorted(
            (p for p in log_dir.glob("breezy-trade-*.log") if _NODE_LOG_NAME_RE.match(p.name)),
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


def log_warning(event: str, **fields: int | str) -> None:
    """[SUP-ADOPT-PERMIT] Same static-event-name/int-str-fields-only
    discipline as :func:`log_decision`, at WARNING level -- for a condition
    that is retried and self-heals, never itself an operator page."""
    if fields:
        rendered = " ".join(f"{key}={value}" for key, value in fields.items())
        logger.warning("%s %s", event, rendered)
    else:
        logger.warning(event)


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


def _send_permit_alert(
    sink: AlertSink, *, event: str, severity: str, detail: AlertDetail, site: str = "trade_node"
) -> bool:
    """[B1, silent-failure-review A2] Like :func:`alert`, but the send's
    success/failure is OBSERVABLE to the caller -- ``emit_alert`` deliberately
    never reports that back (see its own docstring), which is right for
    every other fire-and-forget call site in this module but wrong for B1:
    a failed send here must be retried on the very next poll, never latched
    as sent. Same containment discipline as ``emit_alert`` (``BaseException``,
    exception TYPE only, never the message)."""
    payload = AlertPayload(severity=severity, event=event, site=site, detail=detail.value)
    try:
        sink.emit(payload)
    except BaseException as exc:  # noqa: BLE001 -- deliberate; see docstring.
        log_decision("permit_watch_alert_send_failed", error_type=type(exc).__name__)
        return False
    return True


def _require_permit_alert_fields(decision: PermitAlertDecision) -> tuple[str, str, AlertDetail]:
    """[CF-12 Wave 1] ``decide_permit_alert`` fills ``event``, ``severity``
    and ``detail`` on every branch that returns ``action=ALERT`` (see its own
    docstring) -- both call sites below already guard on
    ``decision.action is PermitAlertAction.ALERT`` before calling this, so
    these fields are proven non-``None`` here, never actually missing."""
    assert decision.event is not None
    assert decision.severity is not None
    assert decision.detail is not None
    return decision.event, decision.severity, decision.detail


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
    # httpx logs request URLs at INFO and webhook URLs are secrets: keep the
    # library silent even if a root handler is ever added.
    logging.getLogger("httpx").setLevel(logging.WARNING)


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
    read_log_from_start: Callable[[Path], str] = field(default=_read_log_from_start)
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
    read_continuous_family_store_state: Callable[[Path, str], ContinuousFamilyStoreState] = field(
        default=lambda _p, _f: ContinuousFamilyStoreState(
            startup_evidence=None, family_halted=False
        )
    )
    #: [AMBIG-LATCH-RESUME Phase A] Defaults keep every existing fake port
    #: set refusing on an OPEN intent exactly as before (resolvable False)
    #: and fail toward the louder alert (shape UNKNOWN).
    probe_open_intent_resolvable: Callable[..., bool] = field(default=lambda *a, **kw: False)
    #: ``True`` iff the OPEN intent is a with-id shape (the only shape whose
    #: alert is a WARN). Default ``False`` fails toward the louder CRITICAL.
    probe_open_intent_with_id: Callable[..., bool] = field(default=lambda *a, **kw: False)
    #: ``(sink, payload) -> bool``: True iff the alert is durable (delivered or
    #: queued). Default emits through ``alert_sink`` and assumes durable (fakes).
    send_alert_durable: Callable[..., bool] = field(
        default=lambda sink, payload: _emit_durable_assumed(sink, payload)
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
        read_log_from_start=log_reader.read_from_start_and_mark_consumed,
        find_adopted_log=find_adopted_node_log,
        continuous_family_active=sending_family_active,
        resolve_sending_family_id=resolve_sending_family_id,
        read_continuous_family_store_state=read_continuous_family_store_state,
        probe_open_intent_resolvable=probe_open_intent_resolvable,
        probe_open_intent_with_id=probe_open_intent_is_with_id,
        send_alert_durable=durable_alert_send,
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
    # [FU-17, AM-4] STOP_PRIOR fires at most once per trading-day rollover
    # (16:40Z) -- the natural, once-daily hook for bounding
    # `_SUPERVISOR_SPAWNED`'s growth.
    _prune_supervisor_spawned()
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


def probe_open_intent_is_with_id(store_path: Path, *, node_pid: int | None) -> bool:
    """[AMBIG-LATCH-RESUME Phase A, DH1] ``True`` iff
    :func:`probe_open_intent_shape` classifies the OPEN intent ``WITH_ID``."""
    return probe_open_intent_shape(store_path, node_pid=node_pid) is OpenIntentShape.WITH_ID


def _open_intent_resolvable(*, ports: SupervisorPorts, store_path: Path, open_intent: bool) -> bool:
    """``False`` unless an OPEN intent is resolvable. A raising probe is
    ``False`` too (today's refusal stays), logged by exception TYPE only."""
    if not open_intent:
        return False
    try:
        return bool(ports.probe_open_intent_resolvable(store_path, node_pid=None))
    except Exception as exc:  # noqa: BLE001 -- contained; named by TYPE only.
        log_decision("launch_resolvable_probe_failed", error_type=type(exc).__name__)
        return False


def _emit_durable_assumed(sink: AlertSink, payload: AlertPayload) -> bool:
    """Default ``send_alert_durable``: emit and assume durable (test doubles)."""
    emit_alert(sink, payload)
    return True


_DURABLE_WRITER: Final[str] = "legacy_runtime"


def durable_alert_send(
    sink: AlertSink,
    payload: AlertPayload,
    *,
    alerts_root: Path | None = None,
    egress_configured: bool | None = None,
) -> bool:
    """[AMBIG-LATCH-RESUME Phase A review] Send ``payload`` and report whether it
    is DURABLE: delivered (HTTP 2xx) or written to the alert outbox for a drainer.

    ``emit_alert`` swallows every failure, so it cannot say. This uses the
    result-returning ``deliver_with_proof`` (outbox entry written before the
    POST). Not durable = the outbox refused (overflow) or was unwritable AND the
    POST did not land. With no webhook configured the log line is the only
    channel that exists, so that case is reported durable: refusing to launch
    for want of a channel nothing can supply would recreate the L-48 strand.
    """
    configured = alert_egress_configured() if egress_configured is None else egress_configured
    if not configured:
        emit_alert(sink, payload)
        return True
    root = default_alerts_root() if alerts_root is None else alerts_root
    write_failures_before = _ALERT_COUNTERS.outbox_write_failures
    try:
        proof = deliver_with_proof(
            sink,
            payload,
            writer=_DURABLE_WRITER,
            records=DeliveryRecordWriter(root),
            attempt_kind="alert",
            outbox=AlertOutbox(root),
        )
    except Exception as exc:  # noqa: BLE001 -- contained; named by TYPE only.
        log_decision("launch_alert_send_failed", error_type=type(exc).__name__)
        return False
    if proof.delivered:
        return True
    if proof.status_class == "outbox_overflow":
        return False
    return _ALERT_COUNTERS.outbox_write_failures == write_failures_before


def _announce_launch_to_resolve(*, ports: SupervisorPorts, store_path: Path) -> bool:
    """[AMBIG-LATCH-RESUME Phase A, CM1/DH1] Log the decision and alert by the
    OPEN intent's shape immediately before the launch spawns over it. Returns
    ``False`` iff the spawn must be deferred.

    A with-id intent has the existing GET resolver (WARN, unchanged). A no-id,
    no-context or unknown shape needs the node's no-id resolver, so it pages
    CRITICAL and the page must be DURABLE (delivered or queued) before the
    spawn: otherwise log ``launch_to_resolve_alert_undelivered`` at ERROR and
    return ``False`` (the caller defers to the next permitted poll without
    consuming budget). A shape probe that raises is not-with-id.
    """
    try:
        with_id = bool(ports.probe_open_intent_with_id(store_path, node_pid=None))
    except Exception:  # noqa: BLE001 -- deliberate: fail toward the louder alert.
        with_id = False
    log_decision("launch_to_resolve_open_intent", shape="with_id" if with_id else "not_with_id")
    if with_id:
        alert(
            ports.alert_sink,
            event="TRADE_SUPERVISOR_LAUNCH_TO_RESOLVE",
            severity="WARN",
            detail=AlertDetail.INTENT_OPEN_LAUNCH_TO_RESOLVE,
        )
        return True
    payload = AlertPayload(
        severity="CRITICAL",
        event="TRADE_SUPERVISOR_LAUNCH_TO_RESOLVE_NO_ID",
        site="trade_node",
        detail=AlertDetail.INTENT_OPEN_LAUNCH_TO_RESOLVE_NO_ID.value,
    )
    try:
        durable = bool(ports.send_alert_durable(ports.alert_sink, payload))
    except Exception as exc:  # noqa: BLE001 -- contained; named by TYPE only.
        log_decision("launch_alert_send_failed", error_type=type(exc).__name__)
        durable = False
    if not durable:
        logger.error("launch_to_resolve_alert_undelivered")
    return durable


#: [AMBIG-LATCH-RESUME Phase A] A non-durable no-id launch-to-resolve page defers the
#: spawn for at most this many consecutive polls, then the gate FAILS OPEN.
LAUNCH_TO_RESOLVE_MAX_PAGE_DEFERS: Final[int] = 3
#: ... and never inside this many scheduler polls of the window close.
_PAGE_DEFER_MIN_POLLS_BEFORE_CLOSE: Final[int] = 2


def _launch_to_resolve_gate(
    *,
    ports: SupervisorPorts,
    store_path: Path,
    state: DaySchedulerState,
    now: dt.datetime,
    window_end: dt.datetime,
) -> tuple[bool, DaySchedulerState]:
    """Announce, then decide whether the spawn may proceed. A non-durable page
    defers only while fewer than :data:`LAUNCH_TO_RESOLVE_MAX_PAGE_DEFERS`
    consecutive defers AND at least two polls remain before ``window_end``;
    otherwise log ERROR and fail open (spawn). The counter resets on a durable
    page or a spawn; a defer consumes no launch budget."""
    if _announce_launch_to_resolve(ports=ports, store_path=store_path):
        return True, record_launch_to_resolve_page_defers(state, now, 0)
    polls_left_ok = (
        now + dt.timedelta(seconds=_PAGE_DEFER_MIN_POLLS_BEFORE_CLOSE * _SCHEDULE_POLL_INTERVAL_S)
        < window_end
    )
    if state.launch_to_resolve_page_defers < LAUNCH_TO_RESOLVE_MAX_PAGE_DEFERS and polls_left_ok:
        return False, record_launch_to_resolve_page_defers(
            state, now, state.launch_to_resolve_page_defers + 1
        )
    logger.error("launch_to_resolve_spawning_without_durable_page")
    return True, record_launch_to_resolve_page_defers(state, now, 0)


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
    resolvable = _open_intent_resolvable(
        ports=ports, store_path=store_path, open_intent=open_intent
    )
    action = decide_launch_action(
        lock_free=lock_free,
        open_intent_detected=open_intent,
        open_intent_resolvable=resolvable,
    )

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

    # action is LAUNCH or LAUNCH_TO_RESOLVE. [D3] A prior spawn attempt this window may have
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
    if action is LaunchAction.LAUNCH_TO_RESOLVE:
        # Once per ACTUAL spawn attempt (after the D3 gap/budget gates above). A
        # non-durable page defers a BOUNDED number of polls (no relaunch attempt
        # is recorded, so no budget is consumed), then fails open.
        proceed, state = _launch_to_resolve_gate(
            ports=ports,
            store_path=store_path,
            state=state,
            now=now,
            window_end=dt.datetime.combine(state.day, LAUNCH_WINDOW_END_UTC, tzinfo=dt.UTC),
        )
        if not proceed:
            return None, None, state, False
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
    # [SUP-RESTART-ANYTIME ops review, 2026-10-08] An orders-off node prints
    # this on log line 2, so this first drain is the only one that sees it;
    # unlatched, every later B1 poll reported a false ABSENT CRITICAL.
    if PERMIT_NOT_REQUESTED_MARKER in log_text:
        state = record_orders_not_requested_seen(state, now)
    permit_expiry_ns = parse_permit_expiry_ns(log_text)
    if permit_expiry_ns is not None:
        state = record_permit_issued_seen(state, now, permit_expiry_ns)
        # [A-1] Distinct, day-level anchor -- see DaySchedulerState's own
        # docstring for why this is never merged with the per-child latch
        # just above.
        state = record_first_boot_permit_seen(state, now, permit_expiry_ns)
    # [FU-1, 2026-09-25] Classified -- and latched into `midday_cause_seen`
    # -- from THIS read, unconditionally (alive or dead), same drain-safe
    # placement as the two latches just above. Without this, a transient
    # marker line drained here while the child is still starting (or on an
    # earlier dead-poll before B1 next runs) is gone by the time
    # `_do_midday_watch` later needs it for `decide_midday_relaunch`: B1's
    # own `_do_permit_watch` skips its `latch_log_facts` call whenever this
    # handler is the one dispatched (`handler_read_log`), and by the time it
    # does run, the shared `IncrementalLogReader`'s next delta no longer
    # holds this line. `cause` is reused, unchanged, by the boot-relaunch
    # decision below.
    cause = classify_exit1_cause(log_text)
    if cause is not RelaunchCause.UNKNOWN:
        state = record_midday_cause_seen(state, now, cause)
    # [FU-17] The ONLY call site that can ever set this latch for the
    # ORIGINAL boot -- that child dies within the RELAUNCH_CHECK window,
    # well before 17:00Z, so no later handler's read can be first to see it.
    if zero_instruments_refusal_in(log_text):
        state = record_boot_zero_instruments_seen(state, now)
    # [SUP-RESTART-ANYTIME] Same drain-safe parity as every latch above.
    liveness_ns = latest_liveness_line_ns(log_text, now_ns=int(now.timestamp() * 1e9))
    if liveness_ns is not None:
        state = record_liveness_line_seen(state, now, liveness_ns)
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


def _latch_boot_retry_read_facts(
    state: DaySchedulerState, now: dt.datetime, log_text: str
) -> tuple[DaySchedulerState, int | None]:
    if strategy_subscribed_in(log_text):
        state = record_strategy_subscribed_seen(state, now)
    if zero_instruments_refusal_in(log_text):
        state = record_boot_zero_instruments_seen(state, now)
    return state, parse_permit_expiry_ns(log_text)


def _latch_boot_retry_no_permit_facts(
    state: DaySchedulerState, now: dt.datetime, log_text: str
) -> tuple[DaySchedulerState, RelaunchCause]:
    cause_from_read = classify_exit1_cause(log_text)
    if cause_from_read is not RelaunchCause.UNKNOWN:
        state = record_midday_cause_seen(state, now, cause_from_read)
    if PERMIT_NOT_REQUESTED_MARKER in log_text:
        state = record_orders_not_requested_seen(state, now)
    return state, cause_from_read


def _boot_retry_hand_off_to_midday(
    *,
    ports: SupervisorPorts,
    state: DaySchedulerState,
    now: dt.datetime,
    tracked_pid: int,
    node_log: Path,
    store_path: Path,
    permit_expiry_ns: int,
) -> tuple[int, Path, DaySchedulerState]:
    """[item H] Resolve readiness for the hand-off instant itself -- nothing
    in the ordinary mid-day path this hand-off transfers control to ever
    gets a first chance to latch it for a child with no
    ``last_midday_relaunch_attempt_at``. [ruling 5] Both latches -- the
    per-child evidence latch AND the day-level first-boot anchor -- exactly
    like every other permit-observing call site. Called instead of
    (b) permanently: once a permit line is seen, boot-retry never spawns
    again for this child."""
    holder = ports.resolve_intent_lock_holder(intent_lock_path(store_path))
    if readiness_observed(
        holds_intent_lock=(holder == tracked_pid),
        permit_issued=True,
        strategy_subscribed=state.strategy_subscribed_seen,
    ):
        state = record_readiness_observed(state, now)
    state = record_permit_issued_seen(state, now, permit_expiry_ns)
    state = record_first_boot_permit_seen(state, now, permit_expiry_ns)
    log_decision("boot_retry_hand_off_to_midday_relaunch", pid=tracked_pid)
    return tracked_pid, node_log, state


def _handle_live_boot_retry_child(
    *,
    ports: SupervisorPorts,
    state: DaySchedulerState,
    now: dt.datetime,
    tracked_pid: int,
    node_log: Path,
    watch_open_at: dt.datetime,
) -> tuple[int, Path, DaySchedulerState]:
    anchor = state.last_boot_retry_attempt_at or watch_open_at
    if not state.boot_retry_not_ready_alert_sent and (now - anchor) > BOOT_RETRY_READINESS_TIMEOUT:
        alert(
            ports.alert_sink,
            event="TRADE_SUPERVISOR_MIDDAY_WATCH",
            severity="WARN",
            detail=AlertDetail.BOOT_RETRY_CHILD_NOT_READY,
        )
        state = record_boot_retry_not_ready_alert_sent(state, now)
    return tracked_pid, node_log, state


def _handle_dead_boot_retry_child(
    *,
    ports: SupervisorPorts,
    state: DaySchedulerState,
    now: dt.datetime,
    node_log: Path,
    cause_from_read: RelaunchCause,
) -> tuple[int | None, Path, DaySchedulerState, bool]:
    """Confirmed-dead child: a non-``TRANSIENT`` latched cause stops the
    retry path permanently (AC13, one CRITICAL, no spawn). ``TRANSIENT``
    reports ``should_retry=True`` -- the caller falls through to (b)'s
    bounded attempt/gap budget, but must keep surfacing THIS child's
    original ``tracked_pid`` there, never the ``None`` returned here (see
    :func:`_do_boot_retry`'s own docstring)."""
    cause = state.midday_cause_seen if state.midday_cause_seen is not None else cause_from_read
    if cause is RelaunchCause.TRANSIENT:
        return None, node_log, state, True
    log_decision("boot_retry_child_nontransient_exit")
    alert(
        ports.alert_sink,
        event="TRADE_SUPERVISOR_MIDDAY_WATCH",
        severity="CRITICAL",
        detail=AlertDetail.BOOT_RETRY_CHILD_NONTRANSIENT_EXIT,
    )
    return None, node_log, record_boot_retry_nontransient_alert_sent(state, now), False


def _poll_boot_retry_child(
    *,
    ports: SupervisorPorts,
    state: DaySchedulerState,
    now: dt.datetime,
    tracked_pid: int,
    node_log: Path,
    store_path: Path,
    watch_open_at: dt.datetime,
) -> tuple[int | None, Path | None, DaySchedulerState, bool]:
    log_text = ports.read_log_new(node_log)
    state, permit_expiry_ns = _latch_boot_retry_read_facts(state, now, log_text)
    if permit_expiry_ns is not None:
        pid, log, state = _boot_retry_hand_off_to_midday(
            ports=ports,
            state=state,
            now=now,
            tracked_pid=tracked_pid,
            node_log=node_log,
            store_path=store_path,
            permit_expiry_ns=permit_expiry_ns,
        )
        return pid, log, state, False
    state, cause_from_read = _latch_boot_retry_no_permit_facts(state, now, log_text)
    if ports.process_alive(tracked_pid):
        pid, log, state = _handle_live_boot_retry_child(
            ports=ports,
            state=state,
            now=now,
            tracked_pid=tracked_pid,
            node_log=node_log,
            watch_open_at=watch_open_at,
        )
        return pid, log, state, False
    return _handle_dead_boot_retry_child(
        ports=ports,
        state=state,
        now=now,
        node_log=node_log,
        cause_from_read=cause_from_read,
    )


def _handle_declined_boot_retry(
    *,
    ports: SupervisorPorts,
    state: DaySchedulerState,
    now: dt.datetime,
    tracked_pid: int | None,
    node_log: Path | None,
    reason: str,
) -> tuple[int | None, Path | None, DaySchedulerState]:
    log_decision("boot_retry_declined", reason=reason)
    if reason == "attempt budget exhausted" and not state.boot_retry_exhausted_alert_sent:
        alert(
            ports.alert_sink,
            event="TRADE_SUPERVISOR_MIDDAY_WATCH",
            severity="CRITICAL",
            detail=AlertDetail.BOOT_RETRY_ATTEMPTS_EXHAUSTED,
        )
        state = record_boot_retry_exhausted_alert_sent(state, now)
    return tracked_pid, node_log, state


def _boot_retry_final_drain_caught_permit(
    *, ports: SupervisorPorts, state: DaySchedulerState, now: dt.datetime, node_log: Path | None
) -> tuple[DaySchedulerState, bool]:
    """[AM-1] Final drain immediately before spawn, only after death is
    confirmed by the caller -- catches a permit line written by the dying
    child AFTER step (a)'s own read but BEFORE its liveness check (a TOCTOU
    window ``_do_relaunch_check`` shares and does not itself close)."""
    if node_log is None:
        return state, False
    final_log_text = ports.read_log_new(node_log)
    state = latch_log_facts(state, now, final_log_text)
    if state.first_boot_permit_expires_at_ns is None:
        return state, False
    log_decision("boot_retry_final_drain_caught_permit")
    return state, True


def _record_boot_retry_attempt_start(
    *, ports: SupervisorPorts, state: DaySchedulerState, now: dt.datetime
) -> DaySchedulerState:
    """[decision F] The attempt is consumed regardless of the precheck
    outcome that follows -- clears per-child latches for the incoming
    child."""
    if state.boot_retry_attempts == 0 and not state.boot_retry_first_attempt_alert_sent:
        alert(
            ports.alert_sink,
            event="TRADE_SUPERVISOR_MIDDAY_WATCH",
            severity="WARN",
            detail=AlertDetail.BOOT_RETRY_FIRST_ATTEMPT,
        )
        state = record_boot_retry_first_attempt_alert_sent(state, now)
    return record_boot_retry_attempt(state, now)


def _handle_boot_retry_precheck_refusal(
    *,
    ports: SupervisorPorts,
    state: DaySchedulerState,
    now: dt.datetime,
    tracked_pid: int | None,
    node_log: Path | None,
    store_path: Path,
    log_dir: Path,
) -> tuple[int | None, Path | None, DaySchedulerState] | Literal["launch_to_resolve"] | None:
    lock_path = intent_lock_path(store_path)
    lock_free = ports.intent_lock_free(lock_path)
    open_intent = ports.probe_open_intent_state(store_path, node_pid=None) if lock_free else False
    resolvable = _open_intent_resolvable(
        ports=ports, store_path=store_path, open_intent=open_intent
    )
    action = decide_launch_action(
        lock_free=lock_free,
        open_intent_detected=open_intent,
        open_intent_resolvable=resolvable,
    )
    if action is LaunchAction.LAUNCH:
        return None
    if action is LaunchAction.LAUNCH_TO_RESOLVE:
        # The caller announces immediately before the actual child spawn.
        return "launch_to_resolve"
    if action is LaunchAction.REFUSE_LOCK_HELD:
        adoption = _attempt_adoption(ports=ports, lock_path=lock_path, log_dir=log_dir)
        if adoption is not None:
            pid, adopted_log = adoption
            log_decision("boot_retry_adopted_live_node", pid=pid)
            return pid, adopted_log, record_child_adopted(state, now)
        log_decision("boot_retry_precheck_refused_lock_held")
        alert(
            ports.alert_sink,
            event="TRADE_SUPERVISOR_MIDDAY_WATCH",
            severity="WARN",
            detail=AlertDetail.BOOT_RETRY_PRECHECK_REFUSED_LOCK_HELD,
        )
        return tracked_pid, node_log, state
    log_decision("boot_retry_precheck_refused_intent_open")
    alert(
        ports.alert_sink,
        event="TRADE_SUPERVISOR_MIDDAY_WATCH",
        severity="CRITICAL",
        detail=AlertDetail.BOOT_RETRY_PRECHECK_REFUSED_INTENT_OPEN,
    )
    return tracked_pid, node_log, state


def _launch_boot_retry_child(
    *,
    ports: SupervisorPorts,
    now: dt.datetime,
    repo_root: Path,
    node_bin: Path,
    log_dir: Path,
) -> tuple[int, Path] | None:
    new_log = node_log_path(log_dir, now)
    try:
        proc = ports.spawn(node_bin=node_bin, repo_root=repo_root, env=os.environ, log_path=new_log)
    except Exception as exc:  # noqa: BLE001 -- deliberate: ONLY the spawn is contained.
        log_decision("boot_retry_spawn_failed", error_type=type(exc).__name__)
        alert(
            ports.alert_sink,
            event="TRADE_SUPERVISOR_MIDDAY_WATCH",
            severity="CRITICAL",
            detail=AlertDetail.LAUNCH_SPAWN_FAILED,
        )
        return None
    _retain_spawned_child(proc)
    log_decision("boot_retry_launched", pid=proc.pid)
    return proc.pid, new_log


def _attempt_boot_retry_relaunch(
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
    decision = decide_boot_retry(
        now=now,
        attempts_so_far=state.boot_retry_attempts,
        last_attempt_at=state.last_boot_retry_attempt_at,
    )
    if not decision.should_relaunch:
        return _handle_declined_boot_retry(
            ports=ports,
            state=state,
            now=now,
            tracked_pid=tracked_pid,
            node_log=node_log,
            reason=decision.reason,
        )
    state, caught_permit = _boot_retry_final_drain_caught_permit(
        ports=ports, state=state, now=now, node_log=node_log
    )
    if caught_permit:
        return tracked_pid, node_log, state
    state_before_attempt = state
    state = _record_boot_retry_attempt_start(ports=ports, state=state, now=now)
    precheck_result = _handle_boot_retry_precheck_refusal(
        ports=ports,
        state=state,
        now=now,
        tracked_pid=tracked_pid,
        node_log=node_log,
        store_path=store_path,
        log_dir=log_dir,
    )
    if precheck_result is not None and precheck_result != "launch_to_resolve":
        return precheck_result
    if precheck_result == "launch_to_resolve":
        proceed, gated = _launch_to_resolve_gate(
            ports=ports,
            store_path=store_path,
            state=state,
            now=now,
            window_end=midday_watch_window_end(state.day),
        )
        if not proceed:
            # No spawn this poll; the consumed attempt is handed back (a defer
            # consumes no budget) but the first-attempt WARN latch and the defer
            # counter are carried so neither resets.
            return (
                tracked_pid,
                node_log,
                replace(
                    state_before_attempt,
                    boot_retry_first_attempt_alert_sent=gated.boot_retry_first_attempt_alert_sent,
                    launch_to_resolve_page_defers=gated.launch_to_resolve_page_defers,
                ),
            )
        state = gated
    launched = _launch_boot_retry_child(
        ports=ports, now=now, repo_root=repo_root, node_bin=node_bin, log_dir=log_dir
    )
    if launched is None:  # spawn failed: logged and paged inside; the attempt stays consumed
        return tracked_pid, node_log, state
    pid, new_log = launched
    return pid, new_log, state


def _do_boot_retry(
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
    """[FU-17] Bounded fixed-cadence retry of a zero-instrument boot refusal.

    ``tracked_pid`` is deliberately NOT overwritten with the poll's own
    return value before falling through to step (b) below: on a confirmed
    ``TRANSIENT`` death, :func:`_poll_boot_retry_child` reports ``None`` as
    the "current" pid for its own tuple contract, but step (b)'s decline/
    precheck-refusal/final-drain-caught-permit returns must still surface
    the ORIGINAL (now-dead) pid, exactly like the pre-refactor monolith --
    :func:`_do_midday_watch`'s own decline path relies on the same "keep the
    dead PID visible for operator diagnosis" contract."""
    watch_open_at = dt.datetime.combine(state.day, SELF_CHECK_WINDOW_END_UTC, tzinfo=dt.UTC)

    if tracked_pid is not None and node_log is not None:
        polled_pid, node_log, state, should_retry = _poll_boot_retry_child(
            ports=ports,
            state=state,
            now=now,
            tracked_pid=tracked_pid,
            node_log=node_log,
            store_path=store_path,
            watch_open_at=watch_open_at,
        )
        if not should_retry:
            return polled_pid, node_log, state
    elif tracked_pid is not None and ports.process_alive(tracked_pid):
        # [item E, defense-in-depth] A live child whose log is unknown must
        # never be misread as "no live child" -- unreachable via AC16's own
        # outer guard today, kept so a future guard change cannot silently
        # reopen this misread. Consumes no attempt, spawns nothing.
        return tracked_pid, node_log, state

    return _attempt_boot_retry_relaunch(
        ports=ports,
        state=state,
        now=now,
        tracked_pid=tracked_pid,
        node_log=node_log,
        store_path=store_path,
        repo_root=repo_root,
        node_bin=node_bin,
        log_dir=log_dir,
    )


def _do_boot_retry_window_closed_check(
    *, ports: SupervisorPorts, state: DaySchedulerState, now: dt.datetime
) -> DaySchedulerState:
    """[FU-17, r4->r5 ruling 2/3] A SEPARATE, unconditional per-tick check --
    never a branch inside :func:`decide_boot_retry`/:func:`_do_boot_retry`,
    which only run when a boot-retry poll is actually dispatched (never on
    an ordinary "still alive" tick once a child is up). Closes the gap a
    retry child that dies only after long, live intervals would otherwise
    leave open: the 8-attempt budget never exhausting by day close, with no
    terminal alert."""
    if not boot_retry_window_closed(state, now):
        return state
    alert(
        ports.alert_sink,
        event="TRADE_SUPERVISOR_MIDDAY_WATCH",
        severity="CRITICAL",
        detail=AlertDetail.BOOT_RETRY_WINDOW_CLOSED_NEVER_READY,
    )
    return record_boot_retry_window_closed_alert_sent(state, now)


def _dispatch_boot_retry_window_closed_check(
    *, ports: SupervisorPorts, state: DaySchedulerState, now: dt.datetime
) -> DaySchedulerState:
    """[silent-failure-review A2 pattern] A containment layer around
    :func:`_do_boot_retry_window_closed_check`, matching
    :func:`_dispatch_permit_watch`'s own shape -- a fault here must never
    stop the loop or skip the next phase dispatch."""
    try:
        return _do_boot_retry_window_closed_check(ports=ports, state=state, now=now)
    except Exception as exc:
        logger.info(
            "phase_exception_contained phase=boot_retry_window_closed error_type=%s",
            type(exc).__name__,
            exc_info=True,
        )
        return state


def _boot_retry_unknown_log_fallback_due(
    *,
    state: DaySchedulerState,
    tracked_pid: int | None,
    node_log: Path | None,
    process_alive: Callable[[int], bool],
) -> bool:
    return (
        state.boot_zero_instruments_seen
        and not state.readiness_observed
        and state.first_boot_permit_expires_at_ns is None
        and not state.boot_retry_nontransient_alert_sent
        and not state.boot_retry_exhausted_alert_sent
        and tracked_pid is not None
        and node_log is None
        and not owned(tracked_pid, process_alive=process_alive)
    )


def _warn_boot_retry_unknown_log_fallback_once(
    state: DaySchedulerState, now: dt.datetime
) -> DaySchedulerState:
    if state.boot_retry_unknown_log_fallback_warned:
        return state
    logger.warning(
        "boot_retry_unknown_log_fallback reason=%s",
        _BOOT_RETRY_UNKNOWN_LOG_FALLBACK_REASON,
    )
    return record_boot_retry_unknown_log_fallback_warned(state, now)


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

    [FU-17, AC16] As the very FIRST statement: a zero-instrument boot day
    with neither readiness nor any permit ever observed, and neither
    terminal boot-retry alert already sent, dispatches to
    :func:`_do_boot_retry` instead -- but ONLY when there is no tracked
    child at all, or the tracked child is one THIS supervisor spawned
    (:func:`owned`) with a KNOWN log. Any OTHER tracked pid (not owned by
    this supervisor) falls through to this function's own unmodified body
    below -- but that body's own top-of-function guard
    (``tracked_pid is None or node_log is None``) means the fallthrough is
    NOT symmetric across a known vs. an unresolved log path: a not-owned
    pid with a KNOWN log reaches the body and independently fails closed
    via its own ``first_boot_permit_expires_at_ns is None`` ->
    ``CEILING_UNKNOWN`` branch once that child is later observed dead; a
    not-owned pid with an UNRESOLVED log path (``node_log is None``) never
    reaches that branch at all -- the body's own top-of-function guard
    returns first, with no read and no alert. That second sub-case stays
    silent, never a second unclamped spawn, until
    :func:`boot_retry_window_closed`'s own terminal, once-per-day
    ``BOOT_RETRY_WINDOW_CLOSED_NEVER_READY`` CRITICAL closes it at 01:00Z
    (r5 ruling 3) -- never ``CEILING_UNKNOWN``.
    """
    if midday_boot_retry_dispatch_due(
        state=state,
        tracked_pid=tracked_pid,
        node_log=node_log,
        is_owned=lambda pid: owned(pid, process_alive=ports.process_alive),
    ):
        return _do_boot_retry(
            ports=ports,
            state=state,
            now=now,
            tracked_pid=tracked_pid,
            node_log=node_log,
            store_path=store_path,
            repo_root=repo_root,
            node_bin=node_bin,
            log_dir=log_dir,
        )
    if _boot_retry_unknown_log_fallback_due(
        state=state,
        tracked_pid=tracked_pid,
        node_log=node_log,
        process_alive=ports.process_alive,
    ):
        state = _warn_boot_retry_unknown_log_fallback_once(state, now)
    # [AM-5] Boot-retry permanently terminated, mid-day budget already
    # alerted, or nothing tracked / no log: return unchanged, no read.
    if midday_watch_idle(state=state, tracked_pid=tracked_pid, node_log=node_log):
        return tracked_pid, node_log, state
    if tracked_pid is None or node_log is None:  # type narrowing only; idle above is exhaustive
        return tracked_pid, node_log, state

    log_text = ports.read_log_new(node_log)
    state, live_cause = latch_midday_log_facts(state=state, now=now, log_text=log_text)

    if ports.process_alive(tracked_pid):
        if midday_recheck_pending(state):
            holder = ports.resolve_intent_lock_holder(intent_lock_path(store_path))
            verdict = decide_midday_recheck(
                state=state, now=now, holds_intent_lock=(holder == tracked_pid)
            )
            if verdict is MiddayRecheckAction.READY:
                return tracked_pid, node_log, record_midday_readiness_recheck_done(state, now)
            if verdict is MiddayRecheckAction.NOT_READY_TIMEOUT:
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

    # [A-1, 2026-09-25] The fail-closed ceiling gate is decided FIRST and
    # unconditionally by `decide_midday_dead_child`: a mid-day relaunch
    # without a known first-boot anchor would mint a fresh, unbounded permit,
    # so that case never reaches `ports.spawn`.
    dead = decide_midday_dead_child(state=state, now=now, live_cause=live_cause)
    if dead.action in (
        MiddayDeadAction.CEILING_UNKNOWN_FIRST,
        MiddayDeadAction.CEILING_UNKNOWN_REPEAT,
    ):
        log_decision(
            "midday_relaunch_declined",
            phase="midday_watch",
            reason="first-boot permit expiry unknown",
        )
        if dead.action is MiddayDeadAction.CEILING_UNKNOWN_FIRST:
            log_decision("midday_relaunch_ceiling_unknown", phase="midday_watch", pid=tracked_pid)
            alert(
                ports.alert_sink,
                event="TRADE_SUPERVISOR_MIDDAY_WATCH",
                severity="CRITICAL",
                detail=AlertDetail.MIDDAY_RELAUNCH_CEILING_UNKNOWN,
            )
            state = record_midday_ceiling_unknown_alert_sent(state, now)
            state = seed_permit_alert(state, now)  # [B1/D5]
        return tracked_pid, node_log, state

    if dead.action is not MiddayDeadAction.RELAUNCH:
        log_decision("midday_relaunch_declined", phase="midday_watch", reason=dead.reason or "")
        if dead.action is MiddayDeadAction.EXHAUSTED:
            log_decision("midday_relaunch_exhausted", phase="midday_watch", pid=tracked_pid)
            alert(
                ports.alert_sink,
                event="TRADE_SUPERVISOR_MIDDAY_WATCH",
                severity="CRITICAL",
                detail=AlertDetail.MIDDAY_RELAUNCH_EXHAUSTED,
            )
            state = record_midday_alert_sent(state, now)
            state = seed_permit_alert(state, now)  # [B1/D5]
        return tracked_pid, node_log, state

    log_decision(
        "midday_relaunching", phase="midday_watch", attempt=state.midday_relaunch_attempts + 1
    )
    new_log = node_log_path(log_dir, now)
    # [A-1] Cap the relaunched child's permit at the day's first-boot expiry
    # -- a copy of the environment, never a mutation of `os.environ` itself
    # (which `_do_launch`'s own 16:50Z daily-boot spawn still forwards
    # as-is, with no ceiling). `RELAUNCH` implies the anchor is known.
    child_env = dict(os.environ)
    child_env[PERMIT_EXPIRY_CEILING_NS_ENV_VAR] = str(state.first_boot_permit_expires_at_ns)
    proc = ports.spawn(node_bin=node_bin, repo_root=repo_root, env=child_env, log_path=new_log)
    _retain_spawned_child(proc)
    return proc.pid, new_log, record_midday_relaunch_attempt(state, now)


# ---------------------------------------------------------------------------
# [B1, 2026-09-25] Supervisor-side permit-lapse detector -- the I/O shell.
# Read-only with respect to the node and the store: never spawns, never
# terminates, never writes ``SqliteStateStore`` (AC8). Runs on EVERY
# ``_run_forever`` iteration (both the ``Phase.NONE`` branch and after the
# dispatched phase, per the plan's Architecture section) and is a cheap
# no-op outside its own window (:func:`permit_watch_window`).
# ---------------------------------------------------------------------------


class _AdoptionLogPermanentlyUnreadableError(OSError):
    """[SUP-ADOPT-PERMIT] Raised by
    :func:`_permit_watch_replay_boot_log_on_adoption` once its own
    from-byte-0 read has failed with ``OSError`` for
    ``_ADOPTION_LOG_UNREADABLE_MAX_POLLS`` consecutive polls. Carries the
    already-updated ``state`` (with the failure counter latched) so
    :func:`_do_permit_watch`'s [D8] containment does not silently drop that
    update -- a bare ``raise`` would discard the local reassignment the
    caller's ``state = ...`` never got to see."""

    def __init__(self, state: DaySchedulerState, cause: OSError) -> None:
        super().__init__(str(cause))
        self.state = state


def _permit_watch_replay_boot_log_on_adoption(
    *, ports: SupervisorPorts, state: DaySchedulerState, now: dt.datetime, node_log: Path
) -> tuple[DaySchedulerState, bool]:
    """[SUP-ADOPT-PERMIT] Replay an adopted child's log from byte 0 once, so
    the boot-time permit/subscription lines the shared, offset-draining
    ``IncrementalLogReader`` will never see again in its own delta are
    latched before B1 classifies capability. Returns ``(state, succeeded)``;
    the caller must short-circuit (skip capability evaluation/alerting
    entirely for this poll) whenever ``succeeded`` is ``False``, so a read
    failure is never misclassified as ``PermitCapability.ABSENT``.

    An ``OSError`` here (a stale offset, a not-yet-flushed inode, a
    permission race) is retried SILENTLY for up to
    ``_ADOPTION_LOG_UNREADABLE_MAX_POLLS`` consecutive polls -- never
    paged, never latched as today's ``permit_accepted_gap`` -- then raises
    :class:`_AdoptionLogPermanentlyUnreadableError` so [D8]'s existing
    ``WATCH_FAILED`` exception containment in :func:`_do_permit_watch` fails
    loud rather than staying silent forever."""
    try:
        log_text = ports.read_log_from_start(node_log)
    except OSError as exc:
        state = record_adoption_log_unreadable_poll(state, now)
        log_warning(
            "permit_watch_adoption_log_unreadable",
            phase="permit_watch",
            consecutive_failures=state.adoption_log_unreadable_polls,
            max_polls=_ADOPTION_LOG_UNREADABLE_MAX_POLLS,
        )
        if state.adoption_log_unreadable_polls >= _ADOPTION_LOG_UNREADABLE_MAX_POLLS:
            raise _AdoptionLogPermanentlyUnreadableError(state, exc) from exc
        return state, False
    return latch_log_facts(state, now, log_text), True


def _permit_watch_adopt_and_evaluate(
    *,
    ports: SupervisorPorts,
    state: DaySchedulerState,
    now: dt.datetime,
    now_ns: int,
    tracked_pid: int | None,
    node_log: Path | None,
    store_path: Path,
    log_dir: Path,
    handler_read_log: bool,
) -> tuple[int | None, Path | None, DaySchedulerState]:
    """[D7] Adopt a live, unverified child if needed, then [D6] drain the
    log only when the dispatched phase did not, then [D2] classify and
    [D5] alert. Never adopts over an already-alive ``tracked_pid`` -- that
    includes a pid the mid-day watch just spawned earlier in this same
    iteration (the caller passes the POST-dispatch values)."""
    if tracked_pid is None or not ports.process_alive(tracked_pid):
        lock_path = intent_lock_path(store_path)
        adoption = _attempt_adoption(ports=ports, lock_path=lock_path, log_dir=log_dir)
        if adoption is not None:
            tracked_pid, node_log = adoption
            log_decision("permit_watch_adopted_live_node", pid=tracked_pid)
            state = record_child_adopted(state, now)
            if node_log is not None:
                state, replayed = _permit_watch_replay_boot_log_on_adoption(
                    ports=ports, state=state, now=now, node_log=node_log
                )
                if not replayed:
                    return tracked_pid, node_log, state
    elif node_log is not None and state.adoption_log_unreadable_polls > 0:
        # [SUP-ADOPT-PERMIT] The child was adopted on an earlier poll but its
        # boot-log replay has not yet succeeded (still under threshold) --
        # retry the SAME from-byte-0 replay rather than falling through to
        # the ordinary incremental drain below, which would never see the
        # boot-time lines again.
        state, replayed = _permit_watch_replay_boot_log_on_adoption(
            ports=ports, state=state, now=now, node_log=node_log
        )
        if not replayed:
            return tracked_pid, node_log, state

    child_alive = tracked_pid is not None and ports.process_alive(tracked_pid)
    log_available = node_log is not None
    if child_alive and node_log is not None and not handler_read_log:
        log_text = ports.read_log_new(node_log)
        state = latch_log_facts(state, now, log_text)

    budget_live = midday_budget_live(
        launch_done=state.launch_done,
        readiness_observed=state.readiness_observed,
        midday_watch_window_open=True,
        midday_alert_sent=state.midday_alert_sent,
        midday_ceiling_unknown_alert_sent=state.midday_ceiling_unknown_alert_sent,
        midday_relaunch_attempts=state.midday_relaunch_attempts,
    )
    capability = permit_capability_valid(
        state,
        now_ns,
        child_alive=child_alive,
        log_available=log_available,
        midday_budget_live=budget_live,
    )
    state = record_permit_deferred_since(state, now, capability=capability)

    decision = decide_permit_alert(
        capability=capability,
        now=now,
        last_sent_at=state.permit_alert_last_sent_at,
        last_capability=state.permit_alert_last_capability,
        not_required_warned=state.permit_not_required_warned,
    )
    if decision.action is PermitAlertAction.ALERT:
        event, severity, detail = _require_permit_alert_fields(decision)
        sent = _send_permit_alert(
            ports.alert_sink,
            event=event,
            severity=severity,
            detail=detail,
        )
        if not sent:  # [A2] retried on the next poll, never latched as sent.
            return tracked_pid, node_log, state
        log_decision("permit_watch", phase="permit_watch", capability=capability.value)
        if capability is PermitCapability.NOT_REQUIRED:
            state = record_permit_not_required_warned(state, now)
        else:
            state = record_permit_alert_sent(state, now, capability=capability)
    elif decision.action is PermitAlertAction.RESTORED:
        log_decision("permit_restored", phase="permit_watch")
        state = record_permit_alert_sent(state, now, capability=PermitCapability.VALID)
    return tracked_pid, node_log, state


def _ready_adoption_step(
    *,
    ports: SupervisorPorts,
    state: DaySchedulerState,
    now: dt.datetime,
    now_ns: int,
    tracked_pid: int | None,
    node_log: Path | None,
    store_path: Path,
) -> DaySchedulerState:
    """[SUP-RESTART-ANYTIME] After B1's adoption/replay/drain on this poll,
    re-derive ``launch_done`` + ``readiness_observed`` for a node proven
    ready (so MIDDAY_WATCH becomes due again after a supervisor restart).

    Returns at once, with no port call, when readiness is already observed,
    ``now`` is outside B1's window, or nothing is tracked (B1 pages NO_NODE
    for that; the counter is neither counted nor reset). The step has NO
    spawn, signal or store-write capability: its only port calls are
    ``process_alive``, ``resolve_intent_lock_holder`` and ``alert_sink``.
    An ``OSError`` is logged and counted; any other exception propagates to
    B1's ``[D8]`` containment (WATCH_FAILED, never a mark)."""
    if state.readiness_observed or tracked_pid is None:
        return state
    window_open, window_close = permit_watch_window(state.day)
    if not window_open <= now < window_close:
        return state

    child_alive = False
    holder_is_tracked = False
    try:
        child_alive = ports.process_alive(tracked_pid)
        if child_alive:
            holder = ports.resolve_intent_lock_holder(intent_lock_path(store_path))
            holder_is_tracked = holder is not None and holder == tracked_pid
    except OSError as exc:
        log_decision("ready_adoption_io_error", error_type=type(exc).__name__)
        verdict = ReadyAdoptionVerdict.IO_ERROR
    else:
        verdict = decide_ready_adoption(
            state=state,
            now=now,
            now_ns=now_ns,
            child_alive=child_alive,
            holder_is_tracked=holder_is_tracked,
            log_spawned_at=node_log_spawned_at(node_log.name) if node_log is not None else None,
        )

    if verdict is ReadyAdoptionVerdict.MARK:
        liveness_ns = state.liveness_line_last_ns or now_ns
        state = record_ready_adoption(state, now)
        log_decision(
            "restart_adopted_ready_node",
            pid=tracked_pid,
            liveness_age_s=max(0, (now_ns - liveness_ns) // 1_000_000_000),
        )
        return state
    if not is_deferral(verdict):
        state = reset_ready_adoption_deferral(state, now)
        if (
            verdict in READY_ADOPTION_EVIDENCE_TERMINALS
            and not state.ready_adoption_terminal_logged
        ):
            log_decision("ready_adoption_terminal", verdict=verdict.value, pid=tracked_pid)
            state = record_ready_adoption_terminal_logged(state, now)
        return state

    return _ready_adoption_defer(ports=ports, state=state, now=now, verdict=verdict)


def _ready_adoption_defer(
    *,
    ports: SupervisorPorts,
    state: DaySchedulerState,
    now: dt.datetime,
    verdict: ReadyAdoptionVerdict,
) -> DaySchedulerState:
    """Count one deferral, log it (first poll and every alert), and send the
    WARN/CRITICAL when due; an unsent alert is retried next poll (A2)."""
    state = record_ready_adoption_deferral(state, now)
    spec = decide_ready_adoption_alert(state)
    polls = state.ready_adoption_deferral_polls
    if polls == 1 or spec is not None:
        log_decision("ready_adoption_deferred", reason=verdict.value, polls=polls)
    if spec is not None:
        sent = _send_permit_alert(
            ports.alert_sink, event=spec.event, severity=spec.severity, detail=spec.detail
        )
        if sent:  # [A2] an unsent alert is retried on the next poll, never latched.
            state = record_ready_adoption_alert_sent(
                state, now, critical=spec.severity == "CRITICAL"
            )
    return state


def _do_permit_watch(
    *,
    ports: SupervisorPorts,
    state: DaySchedulerState,
    now: dt.datetime,
    tracked_pid: int | None,
    node_log: Path | None,
    store_path: Path,
    log_dir: Path,
    handler_read_log: bool,
) -> tuple[int | None, Path | None, DaySchedulerState]:
    """[B1] The permit-lapse watch, called on every ``_run_forever``
    iteration. [D8] Has its own ``try``, separate from the dispatched
    phase's own -- a fault here must never end the supervisor or skip the
    next phase dispatch.

    [D2] A no-op outside :func:`permit_watch_window`. [Rev 2 #4] On the
    first poll at or after the window's close, evaluates capability once
    AS OF the close instant (catching a lapse that fell between polls),
    then writes exactly one INFO ``permit_accepted_gap`` line and never
    evaluates again until the next window (a fresh trading day)."""
    try:
        window_open, window_close = permit_watch_window(state.day)

        if now >= window_close:
            if state.permit_gap_info_logged:
                return tracked_pid, node_log, state
            close_ns = int(window_close.timestamp() * 1e9)
            tracked_pid, node_log, state = _permit_watch_adopt_and_evaluate(
                ports=ports,
                state=state,
                now=now,
                now_ns=close_ns,
                tracked_pid=tracked_pid,
                node_log=node_log,
                store_path=store_path,
                log_dir=log_dir,
                handler_read_log=handler_read_log,
            )
            log_decision(
                "permit_accepted_gap",
                expires_at_ns=state.permit_issued_seen_expires_at_ns or 0,
                ruling="B3",
            )
            state = record_permit_gap_info_logged(state, now)
            return tracked_pid, node_log, state

        if now < window_open:
            return tracked_pid, node_log, state

        now_ns = int(now.timestamp() * 1e9)
        tracked_pid, node_log, state = _permit_watch_adopt_and_evaluate(
            ports=ports,
            state=state,
            now=now,
            now_ns=now_ns,
            tracked_pid=tracked_pid,
            node_log=node_log,
            store_path=store_path,
            log_dir=log_dir,
            handler_read_log=handler_read_log,
        )
        # [SUP-RESTART-ANYTIME] ``state`` is rebound to B1's result first, so
        # a fault in the step below is contained with B1's updates intact.
        state = _ready_adoption_step(
            ports=ports,
            state=state,
            now=now,
            now_ns=now_ns,
            tracked_pid=tracked_pid,
            node_log=node_log,
            store_path=store_path,
        )
        return tracked_pid, node_log, state
    except _AdoptionLogPermanentlyUnreadableError as exc:
        # [SUP-ADOPT-PERMIT] The exception carries the state update (failure
        # counter latched) that a bare re-raise inside the helper would
        # otherwise have discarded before it ever reached this scope's
        # ``state`` variable.
        return _contain_permit_watch_failure(
            ports=ports,
            state=exc.state,
            now=now,
            tracked_pid=tracked_pid,
            node_log=node_log,
            error_type=type(exc).__name__,
        )
    except Exception as exc:  # noqa: BLE001 -- [D8] B1's own containment.
        return _contain_permit_watch_failure(
            ports=ports,
            state=state,
            now=now,
            tracked_pid=tracked_pid,
            node_log=node_log,
            error_type=type(exc).__name__,
        )


def _contain_permit_watch_failure(
    *,
    ports: SupervisorPorts,
    state: DaySchedulerState,
    now: dt.datetime,
    tracked_pid: int | None,
    node_log: Path | None,
    error_type: str,
) -> tuple[int | None, Path | None, DaySchedulerState]:
    """[D8] B1's own exception containment, shared by every fault path that
    reaches :func:`_do_permit_watch`'s ``try`` -- a plain unexpected
    exception, and (SUP-ADOPT-PERMIT) an adoption-time boot-log replay that
    stayed unreadable through every retry. Never lets a fault end the
    supervisor or skip the next phase dispatch; always fails loud via
    ``PermitCapability.WATCH_FAILED`` rather than silence."""
    log_decision(
        "permit_watch_exception_contained",
        phase="permit_watch",
        error_type=error_type,
    )
    decision = decide_permit_alert(
        capability=PermitCapability.WATCH_FAILED,
        now=now,
        last_sent_at=state.permit_alert_last_sent_at,
        last_capability=state.permit_alert_last_capability,
        not_required_warned=state.permit_not_required_warned,
    )
    if decision.action is PermitAlertAction.ALERT:
        event, severity, detail = _require_permit_alert_fields(decision)
        sent = _send_permit_alert(
            ports.alert_sink,
            event=event,
            severity=severity,
            detail=detail,
        )
        if not sent:  # [A2] retried on the next poll, never latched.
            return tracked_pid, node_log, state
        state = record_permit_alert_sent(state, now, capability=PermitCapability.WATCH_FAILED)
    return tracked_pid, node_log, state


def _emit_alert_spec(sink: AlertSink, spec: AlertSpec) -> None:
    """Emit a decided :class:`AlertSpec` through the shared sink."""
    alert(sink, event=spec.event, severity=spec.severity, detail=spec.detail)


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

    facts = derive_self_check_facts(state=state, log_text=log_text, now=now)
    state = facts.state

    continuous_check: ContinuousFamilyCheck | None = None
    continuous_family_halt_source: str | None = None
    if ports.continuous_family_active():
        sending_family_id = ports.resolve_sending_family_id() or ""
        store_state = ports.read_continuous_family_store_state(store_path, sending_family_id)
        continuous_family_halt_source = store_state.family_halt_source
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
        permit_issued=facts.permit_issued,
        permit_expiry_valid=facts.permit_expiry_valid,
        strategy_subscribed=facts.strategy_subscribed,
        log_available=node_log is not None,
        continuous_check=continuous_check,
        permit_expiry_at_daily_ceiling=facts.permit_expiry_at_daily_ceiling,
    )
    # [B1/D5] A permit-specific FAIL seeds B1's own heartbeat timer so its
    # first CRITICAL for the SAME underlying fault waits for the heartbeat
    # rather than double-paging within the same minute (AC5).
    if state is not None and result in _PERMIT_FAIL_SELF_CHECK_RESULTS:
        state = seed_permit_alert(state, now)
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

    log_decision(
        "self_check",
        **self_check_log_fields(
            result=result,
            continuous_check=continuous_check,
            continuous_family_halt_source=continuous_family_halt_source,
            load_outcome=load_outcome,
            gap_hours=gap_hours,
        ),
    )

    load_alert = self_check_load_alert(load_outcome)
    if load_alert is not None:
        _emit_alert_spec(ports.alert_sink, load_alert)

    new_escalation_state = record_self_check_result(
        escalation_state, result.value, now_utc=now_utc_iso
    )
    result_alert = self_check_result_alert(
        result=result,
        load_outcome=load_outcome,
        consecutive_failures=new_escalation_state.consecutive_failures,
    )
    if result_alert is not None:
        _emit_alert_spec(ports.alert_sink, result_alert)

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
            revision = _resolve_build_revision(os.environ)
            log_decision(
                "supervisor_started",
                stop_prior_utc=str(STOP_PRIOR_UTC),
                launch_utc=str(LAUNCH_UTC),
                self_check_utc=str(SELF_CHECK_UTC),
                lock_path=str(lock_path),
                log_dir=str(log_dir),
                revision=revision,
            )
            # [AMBIG-LATCH-RESUME Phase A, DH1] Advertise the retirement
            # reasons THIS process can decode. A failure never stops the
            # supervisor: without the marker a node fails closed on the new
            # reason (the intent stays AMBIGUOUS and pages), which is safe.
            try:
                write_supervisor_decode_marker(store_path, revision=revision)
            except Exception as exc:  # noqa: BLE001 -- contained; named by TYPE only.
                log_decision("supervisor_decode_marker_write_failed", error_type=type(exc).__name__)
                # No stale marker may survive a failed write, and the loss is paged.
                discard_supervisor_decode_marker(store_path)
                alert(
                    resolve_alert_sink(),
                    event="TRADE_SUPERVISOR_DECODE_MARKER_WRITE_FAILED",
                    severity="WARN",
                    detail=AlertDetail.DECODE_MARKER_WRITE_FAILED,
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


def _dispatch_permit_watch(
    *,
    ports: SupervisorPorts,
    state: DaySchedulerState,
    now: dt.datetime,
    tracked_pid: int | None,
    node_log: Path | None,
    store_path: Path,
    log_dir: Path,
    handler_read_log: bool,
) -> tuple[int | None, Path | None, DaySchedulerState]:
    """[silent-failure-review A2] A SECOND, outer containment layer around
    :func:`_do_permit_watch`'s own ``try`` (D8) -- a fault escaping B1
    ENTIRELY (including one raised from within its own exception handling)
    must never stop the loop or skip the next phase dispatch. Returns the
    PRIOR triple unchanged on that (expected-to-be-rare) path; ``_do_permit_
    watch`` itself is the layer that actually classifies and alerts."""
    try:
        return _do_permit_watch(
            ports=ports,
            state=state,
            now=now,
            tracked_pid=tracked_pid,
            node_log=node_log,
            store_path=store_path,
            log_dir=log_dir,
            handler_read_log=handler_read_log,
        )
    except Exception as exc:  # noqa: BLE001 -- deliberate: see docstring.
        log_decision(
            "permit_watch_exception_contained",
            phase="permit_watch_outer",
            error_type=type(exc).__name__,
        )
        return tracked_pid, node_log, state


def _run_phase(
    *,
    phase: Phase,
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
    """Dispatch one due (non-``NONE``) phase to its handler and thread the
    ``(tracked_pid, node_log, state)`` triple through. May raise: the loop
    contains it per phase."""
    if phase is Phase.STOP_PRIOR:
        tracked_pid = _do_stop_prior(ports=ports, store_path=store_path, tracked_pid=tracked_pid)
        return tracked_pid, node_log, mark_phase_fired(state, phase, now)
    if phase is Phase.LAUNCH:
        tracked_pid, node_log, state, done = _do_launch(
            ports=ports,
            state=state,
            now=now,
            store_path=store_path,
            repo_root=repo_root,
            node_bin=node_bin,
            log_dir=log_dir,
        )
        if done:
            state = mark_phase_fired(state, phase, now)
        return tracked_pid, node_log, state
    if phase is Phase.RELAUNCH_CHECK:
        return _do_relaunch_check(
            ports=ports,
            state=state,
            now=now,
            tracked_pid=tracked_pid,
            node_log=node_log,
            store_path=store_path,
            repo_root=repo_root,
            node_bin=node_bin,
            log_dir=log_dir,
        )
    if phase is Phase.SELF_CHECK:
        tracked_pid, node_log, new_state = _do_self_check(
            ports=ports,
            now=now,
            store_path=store_path,
            log_dir=log_dir,
            tracked_pid=tracked_pid,
            node_log=node_log,
            state=state,
        )
        if new_state is not None:
            state = new_state
        return tracked_pid, node_log, mark_phase_fired(state, phase, now)
    if phase is Phase.MIDDAY_WATCH:
        return _do_midday_watch(
            ports=ports,
            state=state,
            now=now,
            tracked_pid=tracked_pid,
            node_log=node_log,
            store_path=store_path,
            repo_root=repo_root,
            node_bin=node_bin,
            log_dir=log_dir,
        )
    # Defensive: a future new `Phase` must never silently fall through into
    # `_do_self_check` (the original bug this dispatch fixed) -- named and
    # dropped instead.
    log_decision("phase_unhandled", phase=phase.value)
    return tracked_pid, node_log, state


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
            # [FU-17, r4->r5 ruling 2] Phase-independent -- runs exactly once
            # per loop iteration regardless of which phase `next_due` just
            # returned (including `Phase.NONE`), so this still fires after
            # `next_due` starts returning `Phase.NONE` for the rest of the
            # day past 01:00Z. The OLD idea of a post-dispatch-only site is
            # unreachable once the `Phase.NONE` branch's own `continue`
            # below is taken every remaining iteration.
            state = _dispatch_boot_retry_window_closed_check(
                ports=active_ports, state=state, now=now
            )

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
                tracked_pid, node_log, state = _dispatch_permit_watch(
                    ports=active_ports,
                    state=state,
                    now=now,
                    tracked_pid=tracked_pid,
                    node_log=node_log,
                    store_path=store_path,
                    log_dir=log_dir,
                    handler_read_log=False,
                )
                sleep(_SCHEDULE_POLL_INTERVAL_S)
                continue

            # [B1/D6] Captured BEFORE the dispatch: mirrors `_do_midday_watch`'s
            # own early-return guard exactly, so B1 drains the log itself only
            # when this dispatch did not (an early return means no read).
            permit_watch_handler_read_log = (
                phase is Phase.MIDDAY_WATCH
                and midday_handler_reads_log(
                    state=state, tracked_pid=tracked_pid, node_log=node_log
                )
            )
            try:
                tracked_pid, node_log, state = _run_phase(
                    phase=phase,
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
                if phase_exception_marks_fired(phase):
                    state = mark_phase_fired(state, phase, now)

            # [B1] Runs after EVERY dispatched phase (Architecture step 3) --
            # a cheap no-op outside its own window. Threaded back into the
            # SAME locals every other handler uses, so a child B1 adopts is
            # SIGTERM'd by the next STOP_PRIOR (AC11).
            tracked_pid, node_log, state = _dispatch_permit_watch(
                ports=active_ports,
                state=state,
                now=now,
                tracked_pid=tracked_pid,
                node_log=node_log,
                store_path=store_path,
                log_dir=log_dir,
                handler_read_log=permit_watch_handler_read_log,
            )

            # [D1] EVERY dispatch is followed by a bounded sleep -- without
            # this, a LAUNCH that leaves RELAUNCH_CHECK due every pass (not
            # yet ready, not yet exited) is a zero-delay busy loop until
            # readiness or the 17:00 UTC cutoff. Tighter for RELAUNCH_CHECK
            # (the child may become ready or fail within seconds) than the
            # general schedule poll.
            sleep(phase_poll_interval_s(phase))
    except KeyboardInterrupt:
        log_decision("supervisor_interrupted")
        return
