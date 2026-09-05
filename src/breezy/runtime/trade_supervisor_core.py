"""Pure decision logic for the daily trade-node supervisor. No I/O.

Implements the decision rules of ``docs/plans/TRADE_NODE_DAILY_RELAUNCH_2026-09-04.md``
(Rev 3) as free functions over plain values, so every rule is unit-testable
with fakes -- no clock, process table, lock probe, log reader, spawner, or
alert sink is touched from this module. :mod:`breezy.runtime.trade_supervisor`
is the I/O shell that resolves real inputs (pgrep, ``/proc/locks``, log
files, ``subprocess.Popen``) and calls into these functions.

Readiness (:func:`readiness_observed`) is the B3 three-way conjunction and
consults ONLY the two Breezy-owned log markers below plus a caller-supplied
intent-lock-holder check. This module never references, greps for, or
otherwise consults Nautilus's own ``TradingNode: RUNNING`` or ``Execution
state reconciled`` log lines in any control-flow decision -- see the plan's
[E1]. (Grepped for by ``tests/unit/test_trade_supervisor.py`` against this
file's source, not merely asserted here.)
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, replace
from enum import Enum
from typing import Final

# ---------------------------------------------------------------------------
# Schedule -- UTC only.
# ---------------------------------------------------------------------------

STOP_PRIOR_UTC: Final[dt.time] = dt.time(16, 40)
LAUNCH_UTC: Final[dt.time] = dt.time(16, 50)
SELF_CHECK_UTC: Final[dt.time] = dt.time(17, 5)
RELAUNCH_CUTOFF_UTC: Final[dt.time] = dt.time(17, 0)

#: The LAUNCH/RELAUNCH_CHECK window closes at the same instant the relaunch
#: budget does -- one shared window, not two.
LAUNCH_WINDOW_END_UTC: Final[dt.time] = RELAUNCH_CUTOFF_UTC

#: SELF_CHECK's own catch-up window is narrow and deliberately does NOT
#: extend to the next STOP_PRIOR: a supervisor restarting at 17:10 UTC does
#: nothing until tomorrow's 16:40 rather than running a stale, late
#: self-check (restart-scenario table, coordinator round 2).
SELF_CHECK_WINDOW_END_UTC: Final[dt.time] = dt.time(17, 10)

MAX_RELAUNCH_ATTEMPTS: Final[int] = 2
MIN_RELAUNCH_GAP: Final[dt.timedelta] = dt.timedelta(minutes=3)

#: The console entry's required first positional argv token -- distinct from
#: the node's own argv so ``pgrep -f`` can anchor on either without
#: substring-matching the other [R8].
SUPERVISOR_ARGV_TOKEN: Final[str] = "breezy-trade-supervisor-daily"

#: Anchored ``pgrep -f`` patterns (trailing ``$``), matching the plan's own
#: verification checklist commands verbatim.
NODE_ARGV_ANCHOR: Final[str] = "breezy-trade$"
SUPERVISOR_ARGV_ANCHOR: Final[str] = f"{SUPERVISOR_ARGV_TOKEN}$"

# ---------------------------------------------------------------------------
# Breezy-owned control-flow log markers.
#
# These are pinned against the REAL emitters by
# tests/unit/test_trade_supervisor.py, which reads the source of
# app/trade.py / runtime/trade_cli.py / strategy/current_rung_hold/strategy.py
# directly and asserts each marker is a substring of the actual logging call
# -- so a reworded emitter fails that test, not just a hardcoded duplicate.
# ---------------------------------------------------------------------------

PERMIT_ISSUED_MARKER: Final[str] = "live-trading permit issued issued_at_ns="
PERMIT_NOT_ISSUED_MARKER: Final[str] = "order submission permit not issued"
TRADING_NODE_FAILED_MARKER: Final[str] = "trading node failed"
STRATEGY_SUBSCRIBED_MARKER: Final[str] = "CurrentRungHoldStrategy subscribed"

EXIT_OK: Final[int] = 0
EXIT_RUNTIME_ERROR: Final[int] = 1
EXIT_CONFIG_ERROR: Final[int] = 2


class AlertDetail(str, Enum):
    """Closed set of alert ``detail`` reasons this module ever emits.

    Never exception text, never a config/permit value -- matches
    ``AlertPayload``'s own ban on raw upstream content (``health.py``).
    """

    INTENT_OPEN_BLOCKS_ARM = "intent_open_blocks_arm"
    ADOPTION_REFUSED = "adoption_refused"
    STOP_PRIOR_RACE_REFUSED = "stop_prior_race_refused"
    LAUNCH_BLOCKED_LOCK_HELD = "launch_blocked_lock_held"
    LAUNCH_SPAWN_FAILED = "launch_spawn_failed"
    SECOND_SUPERVISOR_REFUSED = "second_supervisor_refused"
    SELF_CHECK_FAIL_NOT_READY = "self_check_fail_not_ready"
    SELF_CHECK_FAIL_SHADOW_MODE_NO_PERMIT = "self_check_fail_shadow_mode_no_permit"
    SELF_CHECK_FAIL_MULTIPLE_FLOCK_HOLDERS = "self_check_fail_multiple_flock_holders"
    SELF_CHECK_FAIL_CHILD_EXITED = "self_check_fail_child_exited"
    PHASE_EXCEPTION_CONTAINED = "phase_exception_contained"


class StopPriorAction(str, Enum):
    """[B2/E5] The 16:40 UTC stop-prior decision."""

    NOOP = "noop"
    SIGTERM_TRACKED = "sigterm_tracked"
    REFUSE_ALERT = "refuse_alert"


class LaunchAction(str, Enum):
    """[R6/B1] The 16:50 UTC launch decision."""

    LAUNCH = "launch"
    REFUSE_INTENT_OPEN = "refuse_intent_open"
    REFUSE_LOCK_HELD = "refuse_lock_held"


class RelaunchCause(str, Enum):
    """[E4] Which of the two exit-1 causes a child's log shows, or neither."""

    TRANSIENT = "transient"
    DETERMINISTIC = "deterministic"
    UNKNOWN = "unknown"


class ExitConfigErrorCause(str, Enum):
    """[R7b] Exit-2 is disambiguated by the intent flock, not the exit code."""

    DUPLICATE_NODE = "duplicate_node"
    CONFIG_ERROR = "config_error"


class SelfCheckResult(str, Enum):
    """[B4/E3] The 17:05 UTC self-check's single PASS/FAIL line."""

    PASS = "PASS"
    #: [D2] Adopted a verified live flock holder whose log location could
    #: not be determined -- permit/subscribed markers are unreadable
    #: without a log, so this PASSes on flock+liveness evidence alone
    #: rather than reporting a false FAIL for a healthy node.
    PASS_ADOPTED_LOG_UNKNOWN = "PASS_ADOPTED_LOG_UNKNOWN"
    FAIL_NODE_NOT_READY = "FAIL_NODE_NOT_READY"
    FAIL_SHADOW_MODE_NO_PERMIT = "FAIL_SHADOW_MODE_NO_PERMIT"
    FAIL_MULTIPLE_FLOCK_HOLDERS = "FAIL_MULTIPLE_FLOCK_HOLDERS"
    FAIL_CHILD_EXITED = "FAIL_CHILD_EXITED"


#: Every FAIL member maps to a fixed alert detail; PASS emits no alert.
SELF_CHECK_ALERT_DETAIL: Final[dict[SelfCheckResult, AlertDetail]] = {
    SelfCheckResult.FAIL_NODE_NOT_READY: AlertDetail.SELF_CHECK_FAIL_NOT_READY,
    SelfCheckResult.FAIL_SHADOW_MODE_NO_PERMIT: (AlertDetail.SELF_CHECK_FAIL_SHADOW_MODE_NO_PERMIT),
    SelfCheckResult.FAIL_MULTIPLE_FLOCK_HOLDERS: (
        AlertDetail.SELF_CHECK_FAIL_MULTIPLE_FLOCK_HOLDERS
    ),
    SelfCheckResult.FAIL_CHILD_EXITED: AlertDetail.SELF_CHECK_FAIL_CHILD_EXITED,
}


def decide_stop_prior_action(
    *, discovered_node_pid: int | None, lock_holder_pid: int | None
) -> StopPriorAction:
    """[B2/E5] SIGTERM only on a verified PID match.

    Equal-and-present -> SIGTERM the adopted/owned node. Any disagreement, a
    lock held with no matching discovered process, or a discovered process
    not holding the lock, is a REFUSE -- never a SIGTERM, and this module
    sends no other signal anywhere (never SIGKILL).
    """
    if discovered_node_pid is None and lock_holder_pid is None:
        return StopPriorAction.NOOP
    if discovered_node_pid is not None and discovered_node_pid == lock_holder_pid:
        return StopPriorAction.SIGTERM_TRACKED
    return StopPriorAction.REFUSE_ALERT


def decide_launch_action(*, lock_free: bool, open_intent_detected: bool) -> LaunchAction:
    """[R6/B1] Launch only when the intent flock is free and no OPEN intent
    blocks ``arm`` -- lock state is checked first: an OPEN-intent probe must
    never run while a node may still hold the store open (see
    :func:`assert_no_live_node_before_intent_probe`), and a free flock is the
    caller's evidence that no node is running."""
    if not lock_free:
        return LaunchAction.REFUSE_LOCK_HELD
    if open_intent_detected:
        return LaunchAction.REFUSE_INTENT_OPEN
    return LaunchAction.LAUNCH


class PreLaunchProbeInvariantError(RuntimeError):
    """Raised when the OPEN-intent probe is invoked while a node PID is live.

    [E5 scope] The probe is pre-launch ONLY. This is a caller-misuse guard,
    not a race handler: the I/O shell must resolve ``node_pid`` (a pgrep
    discovery) before calling the probe, never after.
    """


def assert_no_live_node_before_intent_probe(node_pid: int | None) -> None:
    """[B1/E5 scope] Refuse to let the OPEN-intent probe run while a node
    PID is live. Call this immediately before probing the store."""
    if node_pid is not None:
        raise PreLaunchProbeInvariantError(
            "the OPEN-intent probe must not run while a node PID is live"
        )


def readiness_observed(
    *, holds_intent_lock: bool, permit_issued: bool, strategy_subscribed: bool
) -> bool:
    """[B3] The three-way conjunction. Consults none of Nautilus's own
    ``TradingNode: RUNNING`` / ``Execution state reconciled`` lines -- those
    strings never appear as parameters here and this module never reads
    them in any control-flow decision [E1]."""
    return holds_intent_lock and permit_issued and strategy_subscribed


def classify_exit1_cause(log_text: str) -> RelaunchCause:
    """[E4] The two exit-1 causes are distinguished by log TEXT, not exit
    code. The deterministic marker is checked first: a build that logs both
    (should never happen) must never be treated as transient."""
    if PERMIT_NOT_ISSUED_MARKER in log_text:
        return RelaunchCause.DETERMINISTIC
    if TRADING_NODE_FAILED_MARKER in log_text:
        return RelaunchCause.TRANSIENT
    return RelaunchCause.UNKNOWN


def disambiguate_exit_config_error(*, lock_held: bool) -> ExitConfigErrorCause:
    """[R7b] Exit code 2 is read off the intent flock, not the exit code
    alone: held -> duplicate-node path (never retried); free -> config
    error (retryable once before 17:00 UTC)."""
    if lock_held:
        return ExitConfigErrorCause.DUPLICATE_NODE
    return ExitConfigErrorCause.CONFIG_ERROR


@dataclass(frozen=True, slots=True)
class RelaunchDecision:
    should_relaunch: bool
    reason: str


def decide_relaunch(
    *,
    now: dt.datetime,
    attempts_so_far: int,
    last_attempt_at: dt.datetime | None,
    readiness_was_observed: bool,
    cause: RelaunchCause,
) -> RelaunchDecision:
    """[E4] Bounded relaunch: <=2 attempts, >=3 min apart, never at/after
    17:00 UTC, and zero attempts once readiness was ever observed -- checked
    FIRST and unconditionally, ahead of every other gate."""
    if readiness_was_observed:
        return RelaunchDecision(False, "readiness already observed")
    if now.time() >= RELAUNCH_CUTOFF_UTC:
        return RelaunchDecision(False, "at or past the 17:00 UTC relaunch cutoff")
    if cause is not RelaunchCause.TRANSIENT:
        return RelaunchDecision(False, "exit cause is not transient")
    if attempts_so_far >= MAX_RELAUNCH_ATTEMPTS:
        return RelaunchDecision(False, "attempt budget exhausted")
    if last_attempt_at is not None and (now - last_attempt_at) < MIN_RELAUNCH_GAP:
        return RelaunchDecision(False, "minimum inter-attempt gap not elapsed")
    return RelaunchDecision(True, "transient failure, within budget and window")


def self_check(
    *,
    child_alive: bool,
    flock_holder_count: int,
    flock_held_by_tracked_pid: bool,
    permit_issued: bool,
    permit_expiry_valid: bool,
    strategy_subscribed: bool,
    log_available: bool = True,
) -> SelfCheckResult:
    """[B4/E3/D2] The 17:05 UTC self-check. Exactly one PASS/FAIL result.

    Shadow mode (flock held by the tracked PID and the strategy subscribed,
    but no valid permit-issued line) is its own distinct FAIL state, not a
    silent PASS and not folded into the generic not-ready case.

    ``log_available=False`` (an adopted node whose log location could not
    be determined) skips the log-derived checks (permit/subscribed, which
    are unreadable without a log) and PASSes on flock+liveness evidence
    alone, as ``PASS_ADOPTED_LOG_UNKNOWN`` -- never silently folded into a
    plain ``PASS`` it did not actually verify.
    """
    if not child_alive:
        return SelfCheckResult.FAIL_CHILD_EXITED
    if flock_holder_count > 1:
        return SelfCheckResult.FAIL_MULTIPLE_FLOCK_HOLDERS
    if not flock_held_by_tracked_pid:
        return SelfCheckResult.FAIL_NODE_NOT_READY
    if not log_available:
        return SelfCheckResult.PASS_ADOPTED_LOG_UNKNOWN
    if not strategy_subscribed:
        return SelfCheckResult.FAIL_NODE_NOT_READY
    if not (permit_issued and permit_expiry_valid):
        return SelfCheckResult.FAIL_SHADOW_MODE_NO_PERMIT
    return SelfCheckResult.PASS


_PERMIT_ISSUED_RE: Final[re.Pattern[str]] = re.compile(
    r"live-trading permit issued issued_at_ns=(\d+) expires_at_ns=(\d+) ttl_s=(\d+)"
)


def parse_permit_expiry_ns(log_text: str) -> int | None:
    """Extract ``expires_at_ns`` from the permit-issued marker line, or
    ``None`` if the line is absent. Pure string parsing -- no I/O."""
    match = _PERMIT_ISSUED_RE.search(log_text)
    if match is None:
        return None
    return int(match.group(2))


def permit_expiry_valid(log_text: str, *, now_ns: int) -> bool:
    """[B4] "permit-issued line present with expiry beyond now"."""
    expiry = parse_permit_expiry_ns(log_text)
    return expiry is not None and expiry > now_ns


# ---------------------------------------------------------------------------
# Pure daily scheduler.
#
# `trade_supervisor._run_forever` is the I/O shell that calls `next_due` in
# a loop and dispatches to real phase handlers; this section owns none of
# that I/O and is fully unit-testable over plain datetimes.
# ---------------------------------------------------------------------------


class Phase(str, Enum):
    """Which of the daily schedule's actions is due right now."""

    NONE = "none"
    STOP_PRIOR = "stop_prior"
    LAUNCH = "launch"
    RELAUNCH_CHECK = "relaunch_check"
    SELF_CHECK = "self_check"


@dataclass(frozen=True, slots=True)
class DaySchedulerState:
    """Per-trading-day "phase already fired" bookkeeping.

    A fresh instance is produced whenever the UTC calendar date changes --
    :func:`next_due` and the ``record_*``/``mark_*`` functions all detect
    the rollover themselves, so the caller never has to remember to reset
    it. Every phase fires at most once per day.
    """

    day: dt.date
    stop_prior_done: bool = False
    launch_done: bool = False
    self_check_done: bool = False
    readiness_observed: bool = False
    relaunch_attempts: int = 0
    last_relaunch_attempt_at: dt.datetime | None = None


def initial_scheduler_state(day: dt.date) -> DaySchedulerState:
    return DaySchedulerState(day=day)


def _for_day(state: DaySchedulerState, day: dt.date) -> DaySchedulerState:
    """Return ``state`` unchanged if it already belongs to ``day``,
    otherwise a fresh state for ``day`` -- the day-rollover reset, applied
    consistently by every function in this section."""
    return state if state.day == day else initial_scheduler_state(day)


def _at(day: dt.date, time_: dt.time) -> dt.datetime:
    return dt.datetime.combine(day, time_, tzinfo=dt.UTC)


def next_due(now_utc: dt.datetime, state: DaySchedulerState) -> tuple[Phase, dt.datetime]:
    """The pure scheduler query: which single phase is due right now, and
    when it was (or will be) canonically scheduled for today.

    Read-only: never mutates ``state``, and tolerates ``state`` belonging
    to a stale (prior) day by treating it as if every phase were undone
    for today -- the caller supplies whatever state it has; a day rollover
    is handled here, not by the caller. When nothing is due,
    ``fire_at_utc`` names the NEXT scheduled event (today's remaining
    phase, or tomorrow's STOP_PRIOR once every phase for today is done).
    """
    today = now_utc.date()
    effective = _for_day(state, today)
    t = now_utc.time()

    if not effective.stop_prior_done and STOP_PRIOR_UTC <= t < LAUNCH_UTC:
        return Phase.STOP_PRIOR, _at(today, STOP_PRIOR_UTC)

    if not effective.launch_done and LAUNCH_UTC <= t < LAUNCH_WINDOW_END_UTC:
        return Phase.LAUNCH, _at(today, LAUNCH_UTC)

    if (
        effective.launch_done
        and not effective.readiness_observed
        and LAUNCH_UTC <= t < LAUNCH_WINDOW_END_UTC
    ):
        return Phase.RELAUNCH_CHECK, _at(today, LAUNCH_UTC)

    if not effective.self_check_done and SELF_CHECK_UTC <= t < SELF_CHECK_WINDOW_END_UTC:
        return Phase.SELF_CHECK, _at(today, SELF_CHECK_UTC)

    return Phase.NONE, _next_scheduled_event(today, effective, t)


def _next_scheduled_event(today: dt.date, effective: DaySchedulerState, t: dt.time) -> dt.datetime:
    """Informational only (never consulted for a DUE-NOW decision, which is
    entirely governed by the branches above): the next phase time a caller
    might want to log or sleep towards."""
    if not effective.stop_prior_done and t < STOP_PRIOR_UTC:
        return _at(today, STOP_PRIOR_UTC)
    if not effective.launch_done and t < LAUNCH_UTC:
        return _at(today, LAUNCH_UTC)
    if not effective.self_check_done and t < SELF_CHECK_UTC:
        return _at(today, SELF_CHECK_UTC)
    return _at(today + dt.timedelta(days=1), STOP_PRIOR_UTC)


def mark_phase_fired(
    state: DaySchedulerState, phase: Phase, now_utc: dt.datetime
) -> DaySchedulerState:
    """Record that ``phase`` fired for today. ``RELAUNCH_CHECK`` and
    ``NONE`` never set a "done" flag -- the relaunch window stays open
    until readiness is observed or the window itself closes."""
    effective = _for_day(state, now_utc.date())
    if phase is Phase.STOP_PRIOR:
        return replace(effective, stop_prior_done=True)
    if phase is Phase.LAUNCH:
        return replace(effective, launch_done=True)
    if phase is Phase.SELF_CHECK:
        return replace(effective, self_check_done=True)
    return effective


def record_relaunch_attempt(state: DaySchedulerState, now_utc: dt.datetime) -> DaySchedulerState:
    effective = _for_day(state, now_utc.date())
    return replace(
        effective,
        relaunch_attempts=effective.relaunch_attempts + 1,
        last_relaunch_attempt_at=now_utc,
    )


def record_readiness_observed(state: DaySchedulerState, now_utc: dt.datetime) -> DaySchedulerState:
    effective = _for_day(state, now_utc.date())
    return replace(effective, readiness_observed=True)
