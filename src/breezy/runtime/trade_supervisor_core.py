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
from collections.abc import Mapping
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

#: [2026-09-15] Mid-day relaunch budget -- independent of the boot-time
#: MAX_RELAUNCH_ATTEMPTS/MIN_RELAUNCH_GAP above, and with no readiness gate
#: at all (plan §3 "Relaunch bookkeeping..."/§4 step 5).
MIDDAY_MAX_RELAUNCH_ATTEMPTS: Final[int] = 3
MIDDAY_MIN_RELAUNCH_GAP: Final[dt.timedelta] = dt.timedelta(minutes=5)
#: Bounded post-relaunch readiness re-check, anchored at
#: ``last_midday_relaunch_attempt_at`` -- observability only (§3), never a
#: forced extra relaunch attempt.
MIDDAY_READINESS_RECHECK_TIMEOUT: Final[dt.timedelta] = dt.timedelta(minutes=2)

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
#: WP-0a stopgap: the live family logs ``ContinuousRungHoldStrategy
#: subscribed``. Two accepted prefixes, not a registry. WP-11b parameterises
#: this by ``composition_kind`` — do not generalise here.
CONTINUOUS_STRATEGY_SUBSCRIBED_MARKER: Final[str] = "ContinuousRungHoldStrategy subscribed"
STRATEGY_SUBSCRIBED_MARKERS: Final[tuple[str, ...]] = (
    STRATEGY_SUBSCRIBED_MARKER,
    CONTINUOUS_STRATEGY_SUBSCRIBED_MARKER,
)


def strategy_subscribed_in(log_text: str) -> bool:
    """True iff ``log_text`` contains any accepted rung-hold subscribe prefix.

    WP-0a stopgap. WP-11b parameterises by ``composition_kind``.
    """
    return any(marker in log_text for marker in STRATEGY_SUBSCRIBED_MARKERS)


#: [2026-09-15 mid-day relaunch] A fatal-fault shutdown exits the process
#: cleanly (``EXIT_RUNTIME_ERROR`` via a normal ``return``, not an
#: uncaught exception) so it never reaches ``TRADING_NODE_FAILED_MARKER``'s
#: own emitter. Substrings of the two ``print()`` calls in
#: ``runtime/trade_cli.py`` -- pinned the same way, against the real source.
FATAL_MARKET_DATA_FAULT_MARKER: Final[str] = "FATAL market-data fault"
FATAL_EXEC_CLIENT_FAULT_MARKER: Final[str] = "FATAL execution-client fault"

#: [2026-09-12] Pinned the same way, against
#: ``strategy/current_rung_hold/continuous_strategy.py``'s own class name --
#: see ``tests/unit/test_trade_supervisor_cont_self_check.py``. A boot-time
#: raise of this error (Phase 0 mis-wiring) reaches the node's log via
#: ``app/trade.py``'s ``_report(..., exc_info=True)``, same path as
#: ``TRADING_NODE_FAILED_MARKER`` above.
PHASE0_PERMIT_FORBIDDEN_MARKER: Final[str] = "Phase0PermitForbiddenError"

#: [2026-09-12] The two ``SqliteStateStore`` keys the continuous family's
#: self-check reads directly -- literal duplicates of
#: ``strategy/current_rung_hold/trial_day_latch.py``'s own
#: ``STARTUP_EVIDENCE_KEY``/``FAMILY_HALT_KEY``, never imported from there:
#: the layers contract (``pyproject.toml``) forbids ``runtime`` reaching up
#: into ``strategy``. Pinned against the real source the same way as the
#: markers above.
CONTINUOUS_STARTUP_EVIDENCE_KEY: Final[str] = "exec/polymarket_us/startup_evidence"
CONTINUOUS_FAMILY_HALT_KEY: Final[str] = "continuous_rung_hold/halt"
#: [2026-09-12 cross-seam fix] The store has no delete, so
#: ``breezy-clear-family-halt`` (``trial_day_latch.TrialDayLatch.clear_family_halt``)
#: overwrites ``CONTINUOUS_FAMILY_HALT_KEY`` with this exact sentinel rather
#: than leaving an absent key. Literal duplicate of that module's own
#: private ``_HALT_CLEARED_MARKER`` -- pinned byte-for-byte against it in
#: ``tests/unit/test_trade_supervisor_cont_self_check.py`` (tests may import
#: both layers; production code here still never imports ``strategy``).
CONTINUOUS_FAMILY_HALT_CLEARED_MARKER: Final[bytes] = b'{"v":1,"state":"cleared"}'

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
    #: [2026-09-12] Continuous-family-only self-check extensions -- each
    #: names exactly one of the three checks in ``ContinuousFamilyCheck``.
    SELF_CHECK_FAIL_CONTINUOUS_PHASE0_FORBIDDEN = (
        "self_check_fail_continuous_phase0_forbidden"
    )
    SELF_CHECK_FAIL_CONTINUOUS_STARTUP_EVIDENCE_INVALID = (
        "self_check_fail_continuous_startup_evidence_invalid"
    )
    SELF_CHECK_FAIL_CONTINUOUS_FAMILY_HALTED = "self_check_fail_continuous_family_halted"
    PHASE_EXCEPTION_CONTAINED = "phase_exception_contained"
    #: [2026-09-15] Mid-day watch (§3/§4 step 5-6) -- fires exactly once
    #: (gated by ``DaySchedulerState.midday_alert_sent``) once the mid-day
    #: relaunch budget is exhausted, and once (observability only, never
    #: consuming an extra attempt) when a mid-day-relaunched child fails
    #: the bounded post-relaunch readiness re-check.
    MIDDAY_RELAUNCH_EXHAUSTED = "midday_relaunch_exhausted"
    MIDDAY_RELAUNCHED_CHILD_NOT_READY = "midday_relaunched_child_not_ready"


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
    #: [2026-09-12] Continuous-family-only -- see ``ContinuousFamilyCheck``.
    #: Never reached when ``continuous_check`` is ``None`` (flag absent),
    #: which keeps v2 callers byte-identical.
    FAIL_CONTINUOUS_PHASE0_FORBIDDEN = "FAIL_CONTINUOUS_PHASE0_FORBIDDEN"
    FAIL_CONTINUOUS_STARTUP_EVIDENCE_INVALID = "FAIL_CONTINUOUS_STARTUP_EVIDENCE_INVALID"
    FAIL_CONTINUOUS_FAMILY_HALTED = "FAIL_CONTINUOUS_FAMILY_HALTED"


#: Every FAIL member maps to a fixed alert detail; PASS emits no alert.
SELF_CHECK_ALERT_DETAIL: Final[dict[SelfCheckResult, AlertDetail]] = {
    SelfCheckResult.FAIL_NODE_NOT_READY: AlertDetail.SELF_CHECK_FAIL_NOT_READY,
    SelfCheckResult.FAIL_SHADOW_MODE_NO_PERMIT: (AlertDetail.SELF_CHECK_FAIL_SHADOW_MODE_NO_PERMIT),
    SelfCheckResult.FAIL_MULTIPLE_FLOCK_HOLDERS: (
        AlertDetail.SELF_CHECK_FAIL_MULTIPLE_FLOCK_HOLDERS
    ),
    SelfCheckResult.FAIL_CHILD_EXITED: AlertDetail.SELF_CHECK_FAIL_CHILD_EXITED,
    SelfCheckResult.FAIL_CONTINUOUS_PHASE0_FORBIDDEN: (
        AlertDetail.SELF_CHECK_FAIL_CONTINUOUS_PHASE0_FORBIDDEN
    ),
    SelfCheckResult.FAIL_CONTINUOUS_STARTUP_EVIDENCE_INVALID: (
        AlertDetail.SELF_CHECK_FAIL_CONTINUOUS_STARTUP_EVIDENCE_INVALID
    ),
    SelfCheckResult.FAIL_CONTINUOUS_FAMILY_HALTED: (
        AlertDetail.SELF_CHECK_FAIL_CONTINUOUS_FAMILY_HALTED
    ),
}


@dataclass(frozen=True, slots=True)
class ContinuousFamilyCheck:
    """[2026-09-12] The three additional named checks the 17:05 UTC
    self-check runs ONLY when the continuous family
    (``BREEZY_CONTINUOUS_RUNG_HOLD=1``) is active for this process. Each is
    reported by name -- never folded into one opaque boolean -- both in the
    self-check log line and, on failure, as a distinct
    :class:`SelfCheckResult`/``AlertDetail`` pair.
    """

    #: (a) no :data:`PHASE0_PERMIT_FORBIDDEN_MARKER` in the node's log.
    phase0_clean: bool
    #: (b) see :func:`continuous_startup_evidence_valid`.
    startup_evidence_valid: bool
    #: (c) the family-halt key is absent.
    family_not_halted: bool

    @property
    def passed(self) -> bool:
        return self.phase0_clean and self.startup_evidence_valid and self.family_not_halted


def continuous_startup_evidence_valid(
    evidence: Mapping[str, object] | None, *, launch_ns: int
) -> bool:
    """(b): the durable startup-evidence record exists, was written at or
    after ``launch_ns`` (today's 16:50 UTC launch), and declares
    ``eof_complete=True`` and ``position_read_refused=False``.

    Fails closed on absence or any malformed/unexpected field -- a
    corrupt or stale record is indistinguishable here from "never written
    this launch", matching :func:`TrialDayLatch.read_startup_evidence`'s own
    fail-closed stance on the write side.
    """
    if evidence is None:
        return False
    ts_ns = evidence.get("ts_ns")
    if not isinstance(ts_ns, int) or isinstance(ts_ns, bool):
        return False
    if ts_ns < launch_ns:
        return False
    if evidence.get("eof_complete") is not True:
        return False
    return evidence.get("position_read_refused") is False


def continuous_family_is_halted(raw_halt_value: bytes | None) -> bool:
    """(c): mirrors ``TrialDayLatch.is_family_halted()`` exactly. The store
    has no delete, so a legitimate ``breezy-clear-family-halt`` run leaves
    :data:`CONTINUOUS_FAMILY_HALT_CLEARED_MARKER` in place rather than an
    absent key -- key-present therefore does NOT mean halted on its own.

    Absent key or exactly the cleared sentinel -> not halted. Any other
    stored value -- including corrupt or unrecognised bytes -- IS halted,
    fail-closed, matching the strategy layer's own stance rather than
    laundering an unknown value into a false PASS.
    """
    return raw_halt_value is not None and raw_halt_value != CONTINUOUS_FAMILY_HALT_CLEARED_MARKER


def continuous_family_check(
    *,
    log_text: str,
    startup_evidence: Mapping[str, object] | None,
    family_halted: bool,
    launch_ns: int,
) -> ContinuousFamilyCheck:
    """Pure projection of already-fetched I/O (a log-reader delta, the
    startup-evidence record, and the family-halt flag) onto the three named
    checks. No I/O of its own -- the shell resolves every input first."""
    return ContinuousFamilyCheck(
        phase0_clean=PHASE0_PERMIT_FORBIDDEN_MARKER not in log_text,
        startup_evidence_valid=continuous_startup_evidence_valid(
            startup_evidence, launch_ns=launch_ns
        ),
        family_not_halted=not family_halted,
    )


def launch_time_ns(day: dt.date) -> int:
    """Today's 16:50 UTC launch instant, in epoch nanoseconds -- the floor
    a continuous-family startup-evidence record's ``ts_ns`` must meet or
    exceed to count as "written after today's launch". Mirrors ``_at``'s own
    ``datetime.combine(day, time_, tzinfo=dt.UTC)`` construction."""
    return int(_at(day, LAUNCH_UTC).timestamp() * 1e9)


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
    (should never happen) must never be treated as transient. [2026-09-15]
    Purely additive: either fatal-fault marker (a clean shutdown, not an
    uncaught exception) also classifies TRANSIENT, checked last so neither
    existing branch's precedence changes."""
    if PERMIT_NOT_ISSUED_MARKER in log_text:
        return RelaunchCause.DETERMINISTIC
    if TRADING_NODE_FAILED_MARKER in log_text:
        return RelaunchCause.TRANSIENT
    if FATAL_MARKET_DATA_FAULT_MARKER in log_text or FATAL_EXEC_CLIENT_FAULT_MARKER in log_text:
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
    continuous_check: ContinuousFamilyCheck | None = None,
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

    [2026-09-12] ``continuous_check`` is ``None`` by default -- every
    existing caller (v2, or any caller that never set
    ``BREEZY_CONTINUOUS_RUNG_HOLD=1``) sees byte-identical behaviour, because
    the block below is skipped entirely. When the continuous family is
    active the caller resolves a :class:`ContinuousFamilyCheck` first (log
    scan + a read-only store read) and passes it here; each of its three
    named checks that fails maps to its OWN ``SelfCheckResult``, evaluated
    only once every earlier (structural) check has already passed -- a
    continuous-family failure is reported on top of a healthy node, never
    instead of a genuine ``FAIL_CHILD_EXITED``/``FAIL_NODE_NOT_READY``/
    ``FAIL_SHADOW_MODE_NO_PERMIT``.
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
    if continuous_check is not None:
        if not continuous_check.phase0_clean:
            return SelfCheckResult.FAIL_CONTINUOUS_PHASE0_FORBIDDEN
        if not continuous_check.startup_evidence_valid:
            return SelfCheckResult.FAIL_CONTINUOUS_STARTUP_EVIDENCE_INVALID
        if not continuous_check.family_not_halted:
            return SelfCheckResult.FAIL_CONTINUOUS_FAMILY_HALTED
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
    #: [2026-09-15] Mid-day watch: catches a dead-feed/exec-client shutdown
    #: any time after SELF_CHECK's own window closes, so the node is never
    #: left unsupervised for the rest of the trading day.
    MIDDAY_WATCH = "midday_watch"


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
    #: [fix 2026-09-05] Sticky latch: once ANY log read (RELAUNCH_CHECK's
    #: polling reads or SELF_CHECK's own) has observed
    #: ``STRATEGY_SUBSCRIBED_MARKER``, that fact is recorded here for the
    #: current child. The strategy subscribes once, at boot; a later read
    #: of the SAME shared, offset-draining ``IncrementalLogReader`` seeing
    #: a delta that no longer contains the marker text (because
    #: RELAUNCH_CHECK's polling already consumed past it while waiting on a
    #: permit that never came) must not be treated as "never subscribed".
    #: Reset by :func:`_for_day` on a new calendar day, by
    #: :func:`record_relaunch_attempt` when a new child is launched, and
    #: by :func:`record_child_adopted` when a live node is adopted --
    #: evidence is per-child.
    strategy_subscribed_seen: bool = False
    #: [fix 2026-09-06] Sticky latch for the permit-issued line's
    #: ``expires_at_ns``. Same shared-reader drain as
    #: ``strategy_subscribed_seen``: the permit is issued once, at boot, and
    #: a later delta that no longer contains the line must not be treated as
    #: "never issued". ``None`` means not yet seen for this child; reset by
    #: :func:`_for_day` on a new calendar day, by
    #: :func:`record_relaunch_attempt` when a new child is launched, and
    #: by :func:`record_child_adopted` when a live node is adopted. The
    #: stored expiry is still enforced at self-check. First-seen-wins
    #: applies per child.
    permit_issued_seen_expires_at_ns: int | None = None
    #: [2026-09-15] Mid-day relaunch budget bookkeeping -- independent of
    #: ``relaunch_attempts``/``last_relaunch_attempt_at`` above (see
    #: :data:`MIDDAY_MAX_RELAUNCH_ATTEMPTS`/:data:`MIDDAY_MIN_RELAUNCH_GAP`).
    midday_relaunch_attempts: int = 0
    last_midday_relaunch_attempt_at: dt.datetime | None = None
    #: Sticky latch for the first non-``UNKNOWN`` mid-day
    #: :func:`classify_exit1_cause` result -- same drain-race guard as
    #: ``strategy_subscribed_seen``/``permit_issued_seen_expires_at_ns``
    #: (plan §3). Reset by :func:`record_child_adopted` for a new child.
    midday_cause_seen: RelaunchCause | None = None
    #: Gates ``AlertDetail.MIDDAY_RELAUNCH_EXHAUSTED`` to exactly once per
    #: trading day.
    midday_alert_sent: bool = False
    #: [2026-09-15] Gates ``AlertDetail.MIDDAY_RELAUNCHED_CHILD_NOT_READY``
    #: to exactly once per mid-day-relaunched child -- observability only,
    #: never a forced extra relaunch attempt (plan §3 "Relaunch
    #: bookkeeping..."). Reset by :func:`record_child_adopted` for a new
    #: child, same as ``midday_cause_seen``.
    midday_not_ready_alert_sent: bool = False
    #: [2026-09-15 F1] Gates the post-relaunch readiness recheck (and its
    #: ``resolve_intent_lock_holder`` flock probe) to running only until a
    #: verdict is reached for the current mid-day-relaunched child --
    #: either readiness was observed (success) or
    #: ``midday_not_ready_alert_sent`` fired (timeout). Without this,
    #: nothing latches the SUCCESS path and the probe runs on every poll
    #: for the rest of the day. Reset by :func:`record_child_adopted` for
    #: a new child, same as ``midday_not_ready_alert_sent``.
    midday_readiness_recheck_done: bool = False


def initial_scheduler_state(day: dt.date) -> DaySchedulerState:
    return DaySchedulerState(day=day)


def _for_day(state: DaySchedulerState, day: dt.date) -> DaySchedulerState:
    """Return ``state`` unchanged if it already belongs to ``day``,
    otherwise a fresh state for ``day`` -- the day-rollover reset, applied
    consistently by every function in this section."""
    return state if state.day == day else initial_scheduler_state(day)


def _trading_day(now_utc: dt.datetime) -> dt.date:
    """[2026-09-15] The trading day a UTC instant belongs to -- the daily
    cycle opens at :data:`STOP_PRIOR_UTC` (16:40Z), so the 00:00-16:40Z
    dead zone still belongs to the trading day that opened YESTERDAY's
    16:40Z, not the new UTC calendar date. Every ``_for_day`` rollover
    anchor in this module (and :func:`initial_scheduler_state`'s own seed
    at the I/O shell's boot) uses this, never a bare ``now_utc.date()``."""
    if now_utc.time() >= STOP_PRIOR_UTC:
        return now_utc.date()
    return now_utc.date() - dt.timedelta(days=1)


def _at(day: dt.date, time_: dt.time) -> dt.datetime:
    return dt.datetime.combine(day, time_, tzinfo=dt.UTC)


def midday_watch_window_end(trading_day: dt.date) -> dt.datetime:
    """[2026-09-15] MIDDAY_WATCH's window closes at 01:00Z on the calendar
    day AFTER ``trading_day`` -- crosses UTC midnight, so callers must
    compare a full ``datetime``, never a bare ``.time()``."""
    return _at(trading_day + dt.timedelta(days=1), dt.time(1, 0))


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
    effective = _for_day(state, _trading_day(now_utc))
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

    watch_open_at = _at(effective.day, SELF_CHECK_WINDOW_END_UTC)
    watch_close_at = midday_watch_window_end(effective.day)
    if (
        effective.launch_done
        and effective.readiness_observed
        and watch_open_at <= now_utc < watch_close_at
    ):
        return Phase.MIDDAY_WATCH, watch_open_at

    return Phase.NONE, _next_scheduled_event(today, effective, t)


def _next_scheduled_event(today: dt.date, effective: DaySchedulerState, t: dt.time) -> dt.datetime:
    """Informational only (never consulted for a DUE-NOW decision, which is
    entirely governed by the branches above): the next phase time a caller
    might want to log or sleep towards. [2026-09-15] ``effective`` may
    belong to a still-open trading day even after the UTC calendar date
    has rolled -- checked first so this never overshoots to ``today + 2``
    days when every phase for the still-open trading day is done."""
    if effective.day != today:
        return _at(today, STOP_PRIOR_UTC)
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
    effective = _for_day(state, _trading_day(now_utc))
    if phase is Phase.STOP_PRIOR:
        return replace(effective, stop_prior_done=True)
    if phase is Phase.LAUNCH:
        return replace(effective, launch_done=True)
    if phase is Phase.SELF_CHECK:
        return replace(effective, self_check_done=True)
    return effective


def record_child_adopted(state: DaySchedulerState, now_utc: dt.datetime) -> DaySchedulerState:
    """Clear both per-child evidence latches without touching relaunch
    bookkeeping. Called when the I/O shell ADOPTS an already-live node
    (``tracked_pid`` swapped to a different process) so that node's own
    log is the only remaining evidence. :func:`record_relaunch_attempt`
    and :func:`record_midday_relaunch_attempt` both reuse this primitive
    when a new child is launched. [2026-09-15] Also clears
    ``midday_cause_seen`` -- a mid-day-relaunched child's own exit-1 cause
    is evidence about THAT child, never inherited from its predecessor --
    and ``midday_not_ready_alert_sent``, so a LATER mid-day relaunch (a
    fresh child) gets its own bounded readiness re-check rather than
    inheriting a prior child's already-fired alert latch. [2026-09-15 F1]
    Also clears ``midday_readiness_recheck_done`` -- the new child gets
    its own recheck window rather than inheriting a prior child's
    already-latched verdict."""
    effective = _for_day(state, _trading_day(now_utc))
    return replace(
        effective,
        strategy_subscribed_seen=False,
        permit_issued_seen_expires_at_ns=None,
        midday_cause_seen=None,
        midday_not_ready_alert_sent=False,
        midday_readiness_recheck_done=False,
    )


def record_relaunch_attempt(state: DaySchedulerState, now_utc: dt.datetime) -> DaySchedulerState:
    """Record a new-child launch. Clears both per-child evidence latches
    via :func:`record_child_adopted` so a relaunched child must prove its
    own subscription and permit; :func:`_for_day` still owns the
    calendar-day reset."""
    effective = record_child_adopted(state, now_utc)
    return replace(
        effective,
        relaunch_attempts=effective.relaunch_attempts + 1,
        last_relaunch_attempt_at=now_utc,
    )


def record_readiness_observed(state: DaySchedulerState, now_utc: dt.datetime) -> DaySchedulerState:
    effective = _for_day(state, _trading_day(now_utc))
    return replace(effective, readiness_observed=True)


def record_strategy_subscribed_seen(
    state: DaySchedulerState, now_utc: dt.datetime
) -> DaySchedulerState:
    """[fix 2026-09-05] Latch ``strategy_subscribed_seen`` -- called by the
    I/O shell the moment ANY log read observes an accepted rung-hold
    subscribe prefix (see :func:`strategy_subscribed_in`), so the fact
    survives a LATER read of the same shared, offset-draining reader whose
    delta no longer contains that text. Idempotent: a caller that has
    already latched today's marker gets the same state back unchanged."""
    effective = _for_day(state, _trading_day(now_utc))
    if effective.strategy_subscribed_seen:
        return effective
    return replace(effective, strategy_subscribed_seen=True)


def record_permit_issued_seen(
    state: DaySchedulerState, now_utc: dt.datetime, expires_at_ns: int
) -> DaySchedulerState:
    """[fix 2026-09-06] Latch ``permit_issued_seen_expires_at_ns`` -- called
    by the I/O shell the moment ANY log read observes a parseable
    ``PERMIT_ISSUED_MARKER`` line, so the expiry survives a LATER read of
    the same shared, offset-draining reader whose delta no longer contains
    that text. Idempotent: a caller that has already latched today's expiry
    gets the same state back unchanged (the first-seen expiry wins)."""
    effective = _for_day(state, _trading_day(now_utc))
    if effective.permit_issued_seen_expires_at_ns is not None:
        return effective
    return replace(effective, permit_issued_seen_expires_at_ns=expires_at_ns)


def record_midday_cause_seen(
    state: DaySchedulerState, now_utc: dt.datetime, cause: RelaunchCause
) -> DaySchedulerState:
    """[2026-09-15] Latch the first :func:`classify_exit1_cause` result a
    MIDDAY_WATCH poll observes for the current child -- same drain-race
    guard, and same first-seen-wins idempotency, as
    :func:`record_permit_issued_seen` (plan §3): the fatal-fault marker's
    line may print well before the process is actually observed dead, and
    a later poll's log delta may no longer contain it."""
    effective = _for_day(state, _trading_day(now_utc))
    if effective.midday_cause_seen is not None:
        return effective
    return replace(effective, midday_cause_seen=cause)


def record_midday_relaunch_attempt(
    state: DaySchedulerState, now_utc: dt.datetime
) -> DaySchedulerState:
    """[2026-09-15] Mid-day sibling of :func:`record_relaunch_attempt`:
    clears the per-child evidence latches (via :func:`record_child_adopted`,
    which now also clears ``midday_cause_seen``) for the new child, then
    bumps the INDEPENDENT mid-day attempt/last-attempt bookkeeping --
    ``relaunch_attempts`` (the boot-time budget) is left untouched."""
    effective = record_child_adopted(state, now_utc)
    return replace(
        effective,
        midday_relaunch_attempts=effective.midday_relaunch_attempts + 1,
        last_midday_relaunch_attempt_at=now_utc,
    )


def record_midday_alert_sent(state: DaySchedulerState, now_utc: dt.datetime) -> DaySchedulerState:
    """[2026-09-15] Latch that ``AlertDetail.MIDDAY_RELAUNCH_EXHAUSTED`` has
    already fired today -- gates it to exactly once. Idempotent."""
    effective = _for_day(state, _trading_day(now_utc))
    if effective.midday_alert_sent:
        return effective
    return replace(effective, midday_alert_sent=True)


def record_midday_not_ready_alert_sent(
    state: DaySchedulerState, now_utc: dt.datetime
) -> DaySchedulerState:
    """[2026-09-15] Latch that ``AlertDetail.MIDDAY_RELAUNCHED_CHILD_NOT_READY``
    has already fired for the current mid-day-relaunched child -- gates it
    to exactly once per relaunch (cleared by :func:`record_child_adopted`
    for the NEXT relaunched child). Idempotent."""
    effective = _for_day(state, _trading_day(now_utc))
    if effective.midday_not_ready_alert_sent:
        return effective
    return replace(effective, midday_not_ready_alert_sent=True)


def record_midday_readiness_recheck_done(
    state: DaySchedulerState, now_utc: dt.datetime
) -> DaySchedulerState:
    """[2026-09-15 F1] Latch that the post-relaunch readiness recheck (and
    its flock probe) has reached a verdict -- either readiness was
    observed, or the not-ready alert fired -- for the current mid-day-
    relaunched child. Gates the recheck to running only until a verdict
    exists; cleared by :func:`record_child_adopted` for the NEXT
    relaunched child. Idempotent."""
    effective = _for_day(state, _trading_day(now_utc))
    if effective.midday_readiness_recheck_done:
        return effective
    return replace(effective, midday_readiness_recheck_done=True)


def decide_midday_relaunch(
    *,
    now: dt.datetime,
    window_end: dt.datetime,
    attempts_so_far: int,
    last_attempt_at: dt.datetime | None,
    cause: RelaunchCause,
) -> RelaunchDecision:
    """[2026-09-15] Mid-day sibling of :func:`decide_relaunch` [E4] -- <=3
    attempts, >=5 min apart, never at/after ``window_end`` (a full
    ``datetime``, since the mid-day watch window crosses UTC midnight).

    Deliberately has NO readiness gate: unlike the boot-time budget, a
    node that achieved readiness and then died mid-day is exactly the
    scenario this budget exists for (plan §2 item 2, §3)."""
    if now >= window_end:
        return RelaunchDecision(False, "at or past the mid-day watch window close")
    if cause is not RelaunchCause.TRANSIENT:
        return RelaunchDecision(False, "exit cause is not transient")
    if attempts_so_far >= MIDDAY_MAX_RELAUNCH_ATTEMPTS:
        return RelaunchDecision(False, "attempt budget exhausted")
    if last_attempt_at is not None and (now - last_attempt_at) < MIDDAY_MIN_RELAUNCH_GAP:
        return RelaunchDecision(False, "minimum inter-attempt gap not elapsed")
    return RelaunchDecision(True, "transient failure, within budget and window")
