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
import hashlib
import json
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

#: [FU-17] Boot-retry's own budget/cadence -- independent of both the
#: boot-time (MAX_RELAUNCH_ATTEMPTS/MIN_RELAUNCH_GAP) and mid-day
#: (MIDDAY_MAX_RELAUNCH_ATTEMPTS/MIDDAY_MIN_RELAUNCH_GAP) budgets above.
BOOT_RETRY_MAX_ATTEMPTS: Final[int] = 8
BOOT_RETRY_MIN_GAP: Final[dt.timedelta] = dt.timedelta(minutes=15)
#: How long a boot-retry child may stay alive without ever producing a
#: permit-issued line before ``BOOT_RETRY_CHILD_NOT_READY`` WARNs once.
BOOT_RETRY_READINESS_TIMEOUT: Final[dt.timedelta] = dt.timedelta(minutes=15)

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

#: [FU-17] The zero-instrument-refusal marker: `_zero_instruments_message`
#: (`strategy/current_rung_hold/composition.py`) builds its whole message
#: from these two constants, byte-identical to the pre-FU-17 literal. Kept
#: in `runtime` (stdlib-only) so `composition.py` reaches DOWN to import
#: them (a `strategy -> runtime` import, the direction the layers contract
#: already permits) rather than `runtime` reaching up into `strategy`.
ZERO_INSTRUMENTS_REFUSAL_PREFIX: Final[str] = "current_rung_hold: resolved 0 instruments for"
ZERO_INSTRUMENTS_REFUSAL_SUFFIX: Final[str] = "; refusing to start"

#: [FU-17, architect item 4] Prefix and suffix must appear on the SAME log
#: line -- a whole-text substring check would false-match a prefix on one
#: line and an unrelated suffix fragment on another. `composition.py`'s own
#: skip/yesterday warnings carry a "resolved 0 instruments for" fragment but
#: never the full, contiguous prefix (a station name interrupts it) and
#: never the suffix; `settings.py`'s empty-site-set sentence carries the
#: suffix fragment but never the prefix.
_ZERO_INSTRUMENTS_REFUSAL_LINE_RE: Final[re.Pattern[str]] = re.compile(
    re.escape(ZERO_INSTRUMENTS_REFUSAL_PREFIX) + r".*" + re.escape(ZERO_INSTRUMENTS_REFUSAL_SUFFIX)
)


def zero_instruments_refusal_in(log_text: str) -> bool:
    """True iff any single line of ``log_text`` carries the exact
    zero-instrument refusal marker (prefix ... suffix, same line)."""
    return any(_ZERO_INSTRUMENTS_REFUSAL_LINE_RE.search(line) for line in log_text.splitlines())

#: [A-1, 2026-09-25] Injected by ``_do_midday_watch`` into a mid-day-relaunched
#: child's environment, read by ``app/trade.py::main`` and passed to
#: ``issue_live_trading_permit`` as ``max_expires_at_ns`` -- caps that
#: child's permit at the day's FIRST boot's expiry so cumulative daily
#: coverage stays <= ``PERMIT_TTL_NS`` + spawn grace instead of one fresh
#: 10 h window per relaunch. Never set for the 16:50Z daily boot spawn.
PERMIT_EXPIRY_CEILING_NS_ENV_VAR: Final[str] = "BREEZY_PERMIT_EXPIRY_CEILING_NS"

#: [B1, 2026-09-25] The supervisor-side permit-lapse watch's own window --
#: opens the instant SELF_CHECK's catch-up window closes (17:10 UTC), so the
#: two windows never overlap, and closes at the same 01:00 UTC instant
#: MIDDAY_WATCH's own window does (see :func:`midday_watch_window_end`).
#: Both endpoints are shared with existing constants deliberately -- B1 is
#: never the owner of a THIRD independent schedule boundary.
B1_WINDOW_OPEN_UTC: Final[dt.time] = SELF_CHECK_WINDOW_END_UTC

#: [B1] At most one CRITICAL page per bad capability per hour -- a change to
#: a DIFFERENT bad capability still emits immediately (D5).
PERMIT_ALERT_HEARTBEAT: Final[dt.timedelta] = dt.timedelta(minutes=60)

#: [B1] DEFERRED (no live child with the mid-day budget still live, or a
#: fresh mid-day child within its boot grace) that persists longer than this
#: is promoted to NO_NODE -- 3 mid-day relaunch attempts x 5 min gap + 2 min
#: recheck, rounded up (D3).
PERMIT_DEFERRED_MAX: Final[dt.timedelta] = dt.timedelta(minutes=20)

#: [B1/D9] Verified emitter: ``app/trade.py``'s ``settings is not None and
#: not orders_enabled_requested`` branch. Never collides with
#: ``PERMIT_NOT_ISSUED_MARKER`` ("...not issued") -- this one says "not
#: minted: orders not requested".
PERMIT_NOT_REQUESTED_MARKER: Final[str] = "order submission permit not minted: orders not requested"

#: WP-11b (active-family registry, cardinality-1): the WP-0a two-prefix
#: stopgap is replaced by a ``composition_kind`` -> subscribe-marker
#: mapping, pinned against each strategy class's own name the same way the
#: two retired markers were. ``forecast_ladder`` is wired here so the map
#: is complete even though WP-14 has not landed and that composition kind
#: refuses to boot -- the marker exists so the mapping (and this module's
#: own exact-set expectations) never need a second edit once it does.
COMPOSITION_KIND_SUBSCRIBED_MARKERS: Final[dict[str, str]] = {
    "current_rung_hold": "CurrentRungHoldStrategy subscribed",
    "continuous_rung_hold": "ContinuousRungHoldStrategy subscribed",
    "forecast_ladder": "ForecastLadderStrategy subscribed",
}
#: Back-compat names for the two markers that existed before WP-11b --
#: several call sites/tests reference these directly.
STRATEGY_SUBSCRIBED_MARKER: Final[str] = COMPOSITION_KIND_SUBSCRIBED_MARKERS[
    "current_rung_hold"
]
CONTINUOUS_STRATEGY_SUBSCRIBED_MARKER: Final[str] = COMPOSITION_KIND_SUBSCRIBED_MARKERS[
    "continuous_rung_hold"
]
STRATEGY_SUBSCRIBED_MARKERS: Final[tuple[str, ...]] = tuple(
    COMPOSITION_KIND_SUBSCRIBED_MARKERS.values()
)


def strategy_subscribed_in(log_text: str) -> bool:
    """True iff ``log_text`` contains any accepted composition-kind subscribe
    marker (:data:`COMPOSITION_KIND_SUBSCRIBED_MARKERS`)."""
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
#: ``STARTUP_EVIDENCE_KEY``/``LEGACY_FAMILY_HALT_KEY``, never imported from there:
#: the layers contract (``pyproject.toml``) forbids ``runtime`` reaching up
#: into ``strategy``. Pinned against the real source the same way as the
#: markers above.
CONTINUOUS_STARTUP_EVIDENCE_KEY: Final[str] = "exec/polymarket_us/startup_evidence"
CONTINUOUS_LEGACY_FAMILY_HALT_KEY: Final[str] = "continuous_rung_hold/halt"
CONTINUOUS_FAMILY_HALT_KEY_PREFIX: Final[str] = "continuous_rung_hold/family_halt/"
CONTINUOUS_LEGACY_HALT_ATTRIBUTED_FAMILY_ID: Final[str] = "pm_us_crh_v4"
CONTINUOUS_LEGACY_HALT_PINNED_SHA256: Final[str] = (
    "5a82b40140618de8d35338c0c9463afb256de37b73729ebbe32ffd8d75b19f28"
)
CONTINUOUS_FAMILY_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_-]{1,64}\Z")


def continuous_family_startup_evidence_key(sending_family_id: str) -> str:
    """WP-11b: the startup-evidence key expressed as a function of
    ``sending_family_id``, for API symmetry with
    :func:`continuous_family_halt_key`.

    Returns :data:`CONTINUOUS_STARTUP_EVIDENCE_KEY` regardless of the
    argument: the underlying key is exec-client-wide (there is exactly one
    execution-client connection regardless of which family is sending), not
    literally scoped by family id, so no rename of the on-disk key is
    needed or safe -- see F6 (per-family state is global-equivalent under
    cardinality-1).
    """
    del sending_family_id  # exec-client-wide; family-agnostic by design
    return CONTINUOUS_STARTUP_EVIDENCE_KEY


def continuous_family_halt_key(sending_family_id: str) -> str:
    """Return the validated per-family continuous-rung-hold halt key."""
    if CONTINUOUS_FAMILY_ID_PATTERN.fullmatch(sending_family_id) is None:
        raise ValueError(f"invalid sending_family_id: {sending_family_id!r}")
    return f"{CONTINUOUS_FAMILY_HALT_KEY_PREFIX}{sending_family_id}"


#: [2026-09-12 cross-seam fix] The store has no delete, so
#: ``breezy-clear-family-halt`` (``trial_day_latch.TrialDayLatch.clear_family_halt``)
#: overwrites the legacy or per-family halt key with this exact sentinel
#: rather than leaving an absent key. Literal duplicate of that module's own
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
    #: [A-1, 2026-09-25] The day's first-boot permit expiry was never
    #: observed (e.g. the first child died between writing its permit line
    #: and the next poll) -- fires once per day and DECLINES every mid-day
    #: relaunch for the rest of the day rather than mint a relaunched
    #: child's permit with no ceiling.
    MIDDAY_RELAUNCH_CEILING_UNKNOWN = "midday_relaunch_ceiling_unknown"
    #: [A-1 follow-up, 2026-09-25] A relaunched child's permit line shows an
    #: expiry equal to the day's first-boot ceiling anchor -- A-1's clamp
    #: working as designed, never a genuine "no permit was issued" refusal.
    #: Distinct from ``SELF_CHECK_FAIL_SHADOW_MODE_NO_PERMIT`` so an
    #: operator is not misled into treating expected daily-coverage-limit
    #: shadow time as a broken permit path. Still alerts -- never silenced.
    SELF_CHECK_FAIL_SHADOW_MODE_PERMIT_EXPIRED_AT_DAILY_CEILING = (
        "self_check_fail_shadow_mode_permit_expired_at_daily_ceiling"
    )
    #: [AUD-14b] The self-check repeat-failure escalation machinery's own
    #: fault paths -- see ``SelfCheckEscalationState``/``EscalationLoadOutcome``
    #: below. Each fails TOWARD alerting, never toward silence.
    SELF_CHECK_ESCALATION_STATE_CORRUPT = "self_check_escalation_state_corrupt"
    SELF_CHECK_ESCALATION_STORE_UNAVAILABLE = "self_check_escalation_store_unavailable"
    SELF_CHECK_ESCALATION_STATE_WRITE_FAILED = "self_check_escalation_state_write_failed"
    #: [B1, 2026-09-25] The supervisor-side permit-lapse watch's own alert
    #: details -- each names exactly one :class:`PermitCapability` (or, for
    #: ``PERMIT_WATCH_EXCEPTION_CONTAINED``, B1's own contained fault).
    PERMIT_LAPSED_IN_DECISION_WINDOW = "permit_lapsed_in_decision_window"
    PERMIT_EXPIRED_AT_DAILY_CEILING_IN_DECISION_WINDOW = (
        "permit_expired_at_daily_ceiling_in_decision_window"
    )
    PERMIT_ABSENT_IN_DECISION_WINDOW = "permit_absent_in_decision_window"
    PERMIT_NO_NODE_IN_DECISION_WINDOW = "permit_no_node_in_decision_window"
    PERMIT_UNVERIFIABLE = "permit_unverifiable"
    PERMIT_WATCH_EXCEPTION_CONTAINED = "permit_watch_exception_contained"
    PERMIT_NOT_REQUIRED_SHADOW = "permit_not_required_shadow"
    #: [FU-17] Boot-retry path -- see ``decide_boot_retry``/``_do_boot_retry``
    #: (``trade_supervisor.py``) and ``boot_retry_window_closed`` below.
    BOOT_RETRY_ATTEMPTS_EXHAUSTED = "boot_retry_attempts_exhausted"
    BOOT_RETRY_CHILD_NONTRANSIENT_EXIT = "boot_retry_child_nontransient_exit"
    BOOT_RETRY_PRECHECK_REFUSED_LOCK_HELD = "boot_retry_precheck_refused_lock_held"
    BOOT_RETRY_PRECHECK_REFUSED_INTENT_OPEN = "boot_retry_precheck_refused_intent_open"
    BOOT_RETRY_FIRST_ATTEMPT = "boot_retry_first_attempt"
    BOOT_RETRY_CHILD_NOT_READY = "boot_retry_child_not_ready"
    BOOT_RETRY_WINDOW_CLOSED_NEVER_READY = "boot_retry_window_closed_never_ready"


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
    #: [A-1 follow-up, 2026-09-25] See ``AlertDetail.SELF_CHECK_FAIL_
    #: SHADOW_MODE_PERMIT_EXPIRED_AT_DAILY_CEILING``'s own docstring.
    FAIL_SHADOW_MODE_PERMIT_EXPIRED_AT_DAILY_CEILING = (
        "FAIL_SHADOW_MODE_PERMIT_EXPIRED_AT_DAILY_CEILING"
    )
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
    SelfCheckResult.FAIL_SHADOW_MODE_PERMIT_EXPIRED_AT_DAILY_CEILING: (
        AlertDetail.SELF_CHECK_FAIL_SHADOW_MODE_PERMIT_EXPIRED_AT_DAILY_CEILING
    ),
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


def continuous_classify_legacy_family_halt(raw_halt_value: bytes | None) -> str:
    if raw_halt_value is None:
        return "absent"
    if raw_halt_value == CONTINUOUS_FAMILY_HALT_CLEARED_MARKER:
        return "cleared"
    if hashlib.sha256(raw_halt_value).hexdigest() == CONTINUOUS_LEGACY_HALT_PINNED_SHA256:
        return "attributable_to_v4"
    return "halts_all"


@dataclass(frozen=True, slots=True)
class ContinuousFamilyHaltState:
    halted: bool
    source: str
    legacy: str


def continuous_family_halt_state(
    sending_family_id: str, legacy_raw: bytes | None, family_raw: bytes | None
) -> ContinuousFamilyHaltState:
    continuous_family_halt_key(sending_family_id)
    legacy = continuous_classify_legacy_family_halt(legacy_raw)
    if legacy == "halts_all":
        source = "legacy_halts_all"
    elif family_raw is not None and family_raw != CONTINUOUS_FAMILY_HALT_CLEARED_MARKER:
        source = "per_family"
    elif (
        legacy == "attributable_to_v4"
        and sending_family_id == CONTINUOUS_LEGACY_HALT_ATTRIBUTED_FAMILY_ID
    ):
        source = "legacy_attributed"
    else:
        source = "none"
    return ContinuousFamilyHaltState(halted=source != "none", source=source, legacy=legacy)


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
    # [FU-17] Purely additive, checked last: a zero-instrument boot refusal
    # is a config/data-timing issue, not a code fault, but is retried the
    # same way -- see `boot_zero_instruments_seen` for the DEDICATED latch
    # that keys boot-retry eligibility, never this broader TRANSIENT bucket.
    if zero_instruments_refusal_in(log_text):
        return RelaunchCause.TRANSIENT
    return RelaunchCause.UNKNOWN


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
    permit_expiry_at_daily_ceiling: bool = False,
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

    [A-1 follow-up, 2026-09-25] ``permit_expiry_at_daily_ceiling`` defaults
    ``False`` -- every existing caller that never sets it sees byte-
    identical behaviour. When the caller has determined the observed
    permit's expiry equals the day's first-boot ceiling anchor (A-1), the
    would-be ``FAIL_SHADOW_MODE_NO_PERMIT`` is reported as the distinct
    ``FAIL_SHADOW_MODE_PERMIT_EXPIRED_AT_DAILY_CEILING`` instead -- a
    permit WAS issued and A-1's clamp is working as designed, not a
    genuine refusal. Still alerts (see ``SELF_CHECK_ALERT_DETAIL``), never
    silenced.
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
        if permit_issued and permit_expiry_at_daily_ceiling:
            return SelfCheckResult.FAIL_SHADOW_MODE_PERMIT_EXPIRED_AT_DAILY_CEILING
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
# [AUD-14b] Self-check repeat-failure escalation.
#
# A SEPARATE, store-backed record -- deliberately NOT a ``DaySchedulerState``
# field. See the plan's §6 for the full rationale: `_for_day` resets every
# ``DaySchedulerState`` field on a trading-day rollover, and the 17:05Z
# self-check straddles that rollover boundary on every consecutive pair, so
# a day-keyed counter cannot survive it. This record carries no ``day``
# field at all -- that absence IS the mechanism -- and its reducer never
# calls ``_for_day``. Still fully pure/no-I/O, matching this module's
# contract; the I/O shell (``trade_supervisor.py``) owns reading and
# writing the persisted value fresh at every self-check.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SelfCheckEscalationState:
    """The self-check repeat-failure counter. No ``day`` field -- not being
    day-keyed is the mechanism that lets it survive a trading-day rollover
    (see the module note above)."""

    consecutive_failures: int = 0
    #: "" means never observed.
    last_self_check_utc: str = ""


#: The literal, store-backed record key -- colon-separated, matching
#: ``bootstrap_witness.py``'s ``runtime:bootstrap_witness`` convention
#: (never tilde-separated: composite ids use ``^``/``:``, a tilde breaks
#: catalog queries).
SELF_CHECK_ESCALATION_STORE_KEY: Final[str] = "runtime:supervisor:self_check_escalation"

#: Every FAIL-family ``SelfCheckResult`` value that is actually a PASS of
#: some kind, by value -- mirrors ``trade_supervisor._SELF_CHECK_PASS_RESULTS``
#: without importing it (this module owns zero I/O and never imports the
#: shell it is imported BY).
_PASS_RESULT_VALUES: Final[frozenset[str]] = frozenset(
    {SelfCheckResult.PASS.value, SelfCheckResult.PASS_ADOPTED_LOG_UNKNOWN.value}
)


def record_self_check_result(
    state: SelfCheckEscalationState, result: str, *, now_utc: str
) -> SelfCheckEscalationState:
    """Pure reducer: increments ``consecutive_failures`` on a FAIL result,
    resets it to ``0`` on a PASS (or ``PASS_ADOPTED_LOG_UNKNOWN``), and sets
    ``last_self_check_utc=now_utc`` on EVERY result. Deliberately does not
    match the ``record_*``/``_for_day`` family: no ``now`` (a ``dt.datetime``)
    and no ``day`` parameter, because this field must not have a
    day-rollover reset (see the module note above)."""
    if result in _PASS_RESULT_VALUES:
        return SelfCheckEscalationState(consecutive_failures=0, last_self_check_utc=now_utc)
    return replace(
        state, consecutive_failures=state.consecutive_failures + 1, last_self_check_utc=now_utc
    )


def escalated_self_check_severity(
    *, result_is_fail: bool, consecutive_failures: int, count_known: bool
) -> str | None:
    """The fail-toward-alerting rule, as a pure function: ``None`` for a
    PASS result; ``"CRITICAL"`` when the result is a FAIL and EITHER the
    count is unknown (a corrupt or unavailable escalation record) OR the
    count has reached 2; ``"WARN"`` otherwise (a known first failure)."""
    if not result_is_fail:
        return None
    if not count_known or consecutive_failures >= 2:
        return "CRITICAL"
    return "WARN"


#: The escalation record's declared JSON keys -- exactly these two, by
#: name, one-to-one with ``SelfCheckEscalationState``'s fields. A decode
#: succeeds only when the value is a JSON object with EXACTLY this key set
#: and each value's own declared scalar type -- never a subset, never a
#: superset, never coerced.
_ESCALATION_STATE_KEYS: Final[frozenset[str]] = frozenset(
    {"consecutive_failures", "last_self_check_utc"}
)


def encode_self_check_escalation_state(state: SelfCheckEscalationState) -> bytes:
    """Total encode: the two fields, by name, one-to-one."""
    return json.dumps(
        {
            "consecutive_failures": state.consecutive_failures,
            "last_self_check_utc": state.last_self_check_utc,
        }
    ).encode("utf-8")


def decode_self_check_escalation_state(raw: bytes) -> SelfCheckEscalationState | None:
    """Total decode: ``None`` for anything that is not exactly the two
    declared keys with the two declared scalar types -- not JSON, not an
    object, a missing or extra key, or a wrong scalar type. Never coerced,
    never partially accepted: the caller treats ``None`` as CORRUPT, never
    as a default with a warning attached."""
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(decoded, dict):
        return None
    if set(decoded.keys()) != _ESCALATION_STATE_KEYS:
        return None
    consecutive_failures = decoded["consecutive_failures"]
    last_self_check_utc = decoded["last_self_check_utc"]
    if not isinstance(consecutive_failures, int) or isinstance(consecutive_failures, bool):
        return None
    if not isinstance(last_self_check_utc, str):
        return None
    return SelfCheckEscalationState(
        consecutive_failures=consecutive_failures, last_self_check_utc=last_self_check_utc
    )


class EscalationLoadOutcome(str, Enum):
    """The escalation record's load outcome -- distinguished so an ``ABSENT``
    key (the only legitimate silent-zero case) is never conflated with a
    ``CORRUPT`` or ``UNAVAILABLE`` fault, both of which must alert and both
    of which leave the count UNKNOWN rather than zero."""

    #: ``store.get`` returned ``None`` -- the legitimate first-boot /
    #: first-deploy case. The ONLY outcome permitted to start at zero
    #: silently; the count is KNOWN.
    ABSENT = "absent"
    #: A value was present and decoded cleanly. The count is KNOWN.
    PRESENT = "present"
    #: A value was present but did not decode into exactly the two declared
    #: keys. A persistence FAULT, not an absence -- the count is UNKNOWN.
    CORRUPT = "corrupt"
    #: Opening the store or calling ``get``/``set`` raised. The count is
    #: UNKNOWN.
    UNAVAILABLE = "unavailable"


#: [2026-09-15 originally B4/D-man's-switch, tightened AUD-14b] A gap of more
#: than this many hours since the last recorded self-check is reported as a
#: field on the self-check log line -- it does not alert by itself (the run
#: reporting it is a run that happened), but it makes a missed day
#: recoverable from the journal instead of invisible. ~26h (not 24h) gives a
#: one-day trading cycle margin before a normal daily cadence would trip it.
SELF_CHECK_GAP_ALERT_THRESHOLD_HOURS: Final[float] = 26.0


def self_check_gap_hours(*, last_self_check_utc: str, now_utc: dt.datetime) -> float | None:
    """Hours between ``last_self_check_utc`` (an ISO-8601 ``...Z`` string, or
    ``""`` meaning never observed) and ``now_utc``. ``None`` when there is no
    prior recorded self-check or the stored timestamp fails to parse --
    pure, no I/O, no alerting; the caller (the I/O shell) decides whether
    and how to log it."""
    if not last_self_check_utc:
        return None
    try:
        previous = dt.datetime.fromisoformat(last_self_check_utc.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (now_utc - previous).total_seconds() / 3600.0


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
    #: [A-1, 2026-09-25] The day's FIRST-observed permit-issued expiry --
    #: DISTINCT from ``permit_issued_seen_expires_at_ns`` above, which is
    #: per-child and cleared by :func:`record_child_adopted` on every
    #: relaunch. This field is first-seen-wins for the whole TRADING DAY
    #: (set once, via :func:`record_first_boot_permit_seen`) and is
    #: deliberately absent from every ``replace(...)`` in
    #: :func:`record_child_adopted` and the relaunch recorders that reuse
    #: it, so it survives every mid-day relaunch unchanged. Reset only by
    #: :func:`_for_day` at the trading-day boundary, same as every other
    #: field here. ``None`` means no permit-issued line has been observed
    #: yet today -- the fail-closed anchor :func:`_do_midday_watch` requires
    #: before it will ever relaunch a sending node (A-1).
    first_boot_permit_expires_at_ns: int | None = None
    #: [A-1, 2026-09-25] Gates ``AlertDetail.MIDDAY_RELAUNCH_CEILING_UNKNOWN``
    #: to exactly once per trading day -- same idempotent-latch shape as
    #: ``midday_alert_sent``. A day-level gate, not per-child: NOT cleared
    #: by :func:`record_child_adopted`.
    midday_ceiling_unknown_alert_sent: bool = False
    #: [B1, 2026-09-25] Day-level heartbeat latches for the permit-lapse
    #: watch's own alerting (D5) -- reset only by :func:`_for_day`, never by
    #: :func:`record_child_adopted`, never gated by ``midday_alert_sent``.
    permit_alert_last_sent_at: dt.datetime | None = None
    #: The :class:`PermitCapability` value (a string) B1 last alerted on --
    #: ``None`` means B1 has never alerted today.
    permit_alert_last_capability: str | None = None
    #: [B1] Set on first entering DEFERRED, cleared only by a VALID or
    #: NOT_REQUIRED observation (or the day rollover) -- an interstitial
    #: UNKNOWN/other bad capability does NOT reset it (silent-failure-review
    #: amendment A1).
    permit_deferred_since: dt.datetime | None = None
    #: [B1] Gates the one ``permit_accepted_gap`` INFO line to once per
    #: trading day.
    permit_gap_info_logged: bool = False
    #: [B1] Gates the ``PERMIT_NOT_REQUIRED_SHADOW`` WARN to once per day.
    permit_not_required_warned: bool = False
    #: [B1] Per-child latch for :data:`PERMIT_NOT_REQUESTED_MARKER` -- reset
    #: by :func:`record_child_adopted` for a new child, same as every other
    #: per-child evidence latch above.
    orders_not_requested_seen: bool = False
    #: [FU-17] Day-level, monotonic latch set ONLY by a direct
    #: ``zero_instruments_refusal_in`` check on a log read -- NEVER inferred
    #: from ``classify_exit1_cause(...) is RelaunchCause.TRANSIENT``, which
    #: also covers ``TRADING_NODE_FAILED_MARKER``/``FATAL_*`` and can fire on
    #: a child that already minted a permit and traded. Never cleared by
    #: :func:`record_child_adopted` -- once a day is a zero-instrument boot
    #: day, it stays one for the rest of the day, regardless of which child
    #: is currently tracked.
    boot_zero_instruments_seen: bool = False
    #: [FU-17] Boot-retry's own attempt/gap bookkeeping -- day-level,
    #: independent of ``relaunch_attempts``/``midday_relaunch_attempts``.
    boot_retry_attempts: int = 0
    last_boot_retry_attempt_at: dt.datetime | None = None
    #: [FU-17] Terminal, once-per-day CRITICAL latches for the boot-retry
    #: path -- day-level, never cleared by :func:`record_child_adopted`.
    boot_retry_exhausted_alert_sent: bool = False
    boot_retry_nontransient_alert_sent: bool = False
    #: [FU-17] Gates ``AlertDetail.BOOT_RETRY_FIRST_ATTEMPT`` WARN to once
    #: per day -- day-level, checked before ``boot_retry_attempts`` is
    #: bumped for the very first eligible attempt.
    boot_retry_first_attempt_alert_sent: bool = False
    #: [FU-17] Per-child latch: a boot-retry child that stays alive without
    #: ever producing a permit-issued line for longer than
    #: ``BOOT_RETRY_READINESS_TIMEOUT`` gets exactly one WARN. Cleared by
    #: :func:`record_child_adopted` for the NEXT retry child, same shape as
    #: ``midday_not_ready_alert_sent``.
    boot_retry_not_ready_alert_sent: bool = False
    #: [FU-17] Gates ``AlertDetail.BOOT_RETRY_WINDOW_CLOSED_NEVER_READY`` to
    #: once per day -- day-level, never cleared by :func:`record_child_adopted`.
    boot_retry_window_closed_alert_sent: bool = False
    #: [FU-17b] Gates the interim WARNING for the unowned/unknown-log
    #: boot-retry fallback to once per trading day. This is log-only
    #: observability, not an alert.
    boot_retry_unknown_log_fallback_warned: bool = False
    #: [SUP-ADOPT-PERMIT, 2026-09-27] Consecutive-poll counter for an
    #: adoption-time boot-log replay (`ports.read_log_from_start`) that
    #: raised ``OSError`` -- distinct from "log read cleanly, no permit
    #: marker yet", which must never page as
    #: ``PermitCapability.ABSENT``. Reset to 0 by
    #: :func:`record_child_adopted` for a NEW child (a fresh child gets its
    #: own retry budget); NOT reset between polls for the SAME still-failing
    #: adopted child, so it keeps counting toward
    #: ``_ADOPTION_LOG_UNREADABLE_MAX_POLLS`` until either a read succeeds or
    #: the day rolls over.
    adoption_log_unreadable_polls: int = 0


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
    # [FU-17] The OR is nested INSIDE the existing three-way AND, never a
    # top-level OR of two whole clauses -- a bare top-level OR would dispatch
    # MIDDAY_WATCH before SELF_CHECK, and even before `launch_done`.
    if (
        effective.launch_done
        and (effective.readiness_observed or effective.boot_zero_instruments_seen)
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
    already-latched verdict. [SUP-ADOPT-PERMIT] Also clears
    ``adoption_log_unreadable_polls`` -- a NEW child's boot-log replay gets
    its own fresh retry budget, never inheriting a prior child's failure
    count."""
    effective = _for_day(state, _trading_day(now_utc))
    return replace(
        effective,
        strategy_subscribed_seen=False,
        permit_issued_seen_expires_at_ns=None,
        midday_cause_seen=None,
        midday_not_ready_alert_sent=False,
        midday_readiness_recheck_done=False,
        orders_not_requested_seen=False,
        boot_retry_not_ready_alert_sent=False,
        adoption_log_unreadable_polls=0,
    )


def record_adoption_log_unreadable_poll(
    state: DaySchedulerState, now_utc: dt.datetime
) -> DaySchedulerState:
    """[SUP-ADOPT-PERMIT] Increment the consecutive-failure counter for an
    adoption-time boot-log replay that raised ``OSError``. Day-scoped like
    every other latch here; cleared only by :func:`record_child_adopted`
    (a new child) or the trading-day rollover -- a persistently unreadable
    log for the SAME adopted child keeps counting toward
    ``_ADOPTION_LOG_UNREADABLE_MAX_POLLS``."""
    effective = _for_day(state, _trading_day(now_utc))
    return replace(
        effective, adoption_log_unreadable_polls=effective.adoption_log_unreadable_polls + 1
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


def record_first_boot_permit_seen(
    state: DaySchedulerState, now_utc: dt.datetime, expires_at_ns: int
) -> DaySchedulerState:
    """[A-1, 2026-09-25] Latch ``first_boot_permit_expires_at_ns`` -- the
    day's FIRST-observed permit-issued expiry, DISTINCT from the per-child
    :func:`record_permit_issued_seen` latch. First-seen-wins for the whole
    trading day, same ``_for_day`` shape as :func:`record_permit_issued_seen`
    (idempotent: a caller that has already latched today's anchor gets the
    same state back unchanged). Callers latch this ALONGSIDE
    :func:`record_permit_issued_seen`, every time a permit-issued log line
    is observed, at every phase (boot, relaunch, mid-day)."""
    effective = _for_day(state, _trading_day(now_utc))
    if effective.first_boot_permit_expires_at_ns is not None:
        return effective
    return replace(effective, first_boot_permit_expires_at_ns=expires_at_ns)


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


def record_midday_ceiling_unknown_alert_sent(
    state: DaySchedulerState, now_utc: dt.datetime
) -> DaySchedulerState:
    """[A-1, 2026-09-25] Latch that
    ``AlertDetail.MIDDAY_RELAUNCH_CEILING_UNKNOWN`` has already fired today --
    gates it to exactly once, same idempotent shape as
    :func:`record_midday_alert_sent`. A day-level gate: unlike
    ``midday_not_ready_alert_sent``, this is NOT cleared by
    :func:`record_child_adopted` -- an unknown first-boot anchor is a
    property of the DAY, not of any one child."""
    effective = _for_day(state, _trading_day(now_utc))
    if effective.midday_ceiling_unknown_alert_sent:
        return effective
    return replace(effective, midday_ceiling_unknown_alert_sent=True)


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


def record_boot_zero_instruments_seen(
    state: DaySchedulerState, now_utc: dt.datetime
) -> DaySchedulerState:
    """[FU-17] Idempotent day-level latch -- see
    :attr:`DaySchedulerState.boot_zero_instruments_seen`'s own docstring."""
    effective = _for_day(state, _trading_day(now_utc))
    if effective.boot_zero_instruments_seen:
        return effective
    return replace(effective, boot_zero_instruments_seen=True)


def record_boot_retry_attempt(state: DaySchedulerState, now_utc: dt.datetime) -> DaySchedulerState:
    """[FU-17] Clears per-child evidence latches (via
    :func:`record_child_adopted`) for the incoming retry child, then bumps
    the INDEPENDENT boot-retry attempt/last-attempt bookkeeping. Never
    touches ``boot_zero_instruments_seen``, ``first_boot_permit_expires_at_ns``,
    ``relaunch_attempts``, or ``midday_relaunch_attempts``."""
    effective = record_child_adopted(state, now_utc)
    return replace(
        effective,
        boot_retry_attempts=effective.boot_retry_attempts + 1,
        last_boot_retry_attempt_at=now_utc,
    )


def record_boot_retry_exhausted_alert_sent(
    state: DaySchedulerState, now_utc: dt.datetime
) -> DaySchedulerState:
    """[FU-17] Idempotent day-level latch for ``BOOT_RETRY_ATTEMPTS_EXHAUSTED``."""
    effective = _for_day(state, _trading_day(now_utc))
    if effective.boot_retry_exhausted_alert_sent:
        return effective
    return replace(effective, boot_retry_exhausted_alert_sent=True)


def record_boot_retry_nontransient_alert_sent(
    state: DaySchedulerState, now_utc: dt.datetime
) -> DaySchedulerState:
    """[FU-17] Idempotent day-level latch for ``BOOT_RETRY_CHILD_NONTRANSIENT_EXIT``."""
    effective = _for_day(state, _trading_day(now_utc))
    if effective.boot_retry_nontransient_alert_sent:
        return effective
    return replace(effective, boot_retry_nontransient_alert_sent=True)


def record_boot_retry_first_attempt_alert_sent(
    state: DaySchedulerState, now_utc: dt.datetime
) -> DaySchedulerState:
    """[FU-17] Idempotent day-level latch for ``BOOT_RETRY_FIRST_ATTEMPT``."""
    effective = _for_day(state, _trading_day(now_utc))
    if effective.boot_retry_first_attempt_alert_sent:
        return effective
    return replace(effective, boot_retry_first_attempt_alert_sent=True)


def record_boot_retry_not_ready_alert_sent(
    state: DaySchedulerState, now_utc: dt.datetime
) -> DaySchedulerState:
    """[FU-17] Idempotent PER-CHILD latch for ``BOOT_RETRY_CHILD_NOT_READY`` --
    cleared by :func:`record_child_adopted` for the next retry child."""
    effective = _for_day(state, _trading_day(now_utc))
    if effective.boot_retry_not_ready_alert_sent:
        return effective
    return replace(effective, boot_retry_not_ready_alert_sent=True)


def record_boot_retry_window_closed_alert_sent(
    state: DaySchedulerState, now_utc: dt.datetime
) -> DaySchedulerState:
    """[FU-17] Idempotent day-level latch for
    ``BOOT_RETRY_WINDOW_CLOSED_NEVER_READY``."""
    effective = _for_day(state, _trading_day(now_utc))
    if effective.boot_retry_window_closed_alert_sent:
        return effective
    return replace(effective, boot_retry_window_closed_alert_sent=True)


def record_boot_retry_unknown_log_fallback_warned(
    state: DaySchedulerState, now_utc: dt.datetime
) -> DaySchedulerState:
    """[FU-17b] Idempotent day-level latch for the log-only interim WARNING
    when the unowned/unknown-log boot-retry fallback is taken."""
    effective = _for_day(state, _trading_day(now_utc))
    if effective.boot_retry_unknown_log_fallback_warned:
        return effective
    return replace(effective, boot_retry_unknown_log_fallback_warned=True)


def decide_boot_retry(
    *,
    now: dt.datetime,
    attempts_so_far: int,
    last_attempt_at: dt.datetime | None,
) -> RelaunchDecision:
    """[FU-17] Boot-retry's own pure attempt/gap check -- deliberately no
    ``window_end``/``cause``/``catalog_ready`` parameter: the window-close
    case is handled entirely OUTSIDE this function, by the separate,
    unconditional per-tick predicate :func:`boot_retry_window_closed`."""
    if attempts_so_far >= BOOT_RETRY_MAX_ATTEMPTS:
        return RelaunchDecision(False, "attempt budget exhausted")
    if last_attempt_at is not None and (now - last_attempt_at) < BOOT_RETRY_MIN_GAP:
        return RelaunchDecision(False, "minimum inter-attempt gap not elapsed")
    return RelaunchDecision(True, "eligible")


def boot_retry_window_closed(state: DaySchedulerState, now_utc: dt.datetime) -> bool:
    """[FU-17, r4->r5 ruling 3 + disclosed fix] True once a boot-zero-
    instruments day reaches ``midday_watch_window_end`` (01:00Z the next
    day) with boot-retry still structurally eligible -- i.e. no readiness
    or permit was ever observed, and neither terminal alert (exhausted,
    non-transient-exit, or this alert itself) has already fired -- WITHOUT
    the attempt budget ever having exhausted (one or more retry children
    stayed alive long enough between deaths that fewer than
    ``BOOT_RETRY_MAX_ATTEMPTS`` were consumed by day close). Also excludes a
    day where the not-owned/known-log fall-through already alerted
    ``MIDDAY_RELAUNCH_CEILING_UNKNOWN`` -- that branch's own alert is this
    day's terminal signal; this predicate must not ALSO page for it."""
    effective = _for_day(state, _trading_day(now_utc))
    return (
        effective.boot_zero_instruments_seen
        and not effective.readiness_observed
        and effective.first_boot_permit_expires_at_ns is None
        and not effective.boot_retry_nontransient_alert_sent
        and not effective.boot_retry_exhausted_alert_sent
        and not effective.boot_retry_window_closed_alert_sent
        and not effective.midday_ceiling_unknown_alert_sent
        and now_utc >= midday_watch_window_end(effective.day)
    )


# ---------------------------------------------------------------------------
# [B1, 2026-09-25] Supervisor-side permit-lapse detector -- pure decision
# rules. See ``docs/plans`` B1 Rev 2 plan for the full design (D1-D9). The
# I/O shell (``_do_permit_watch`` in ``trade_supervisor.py``) resolves real
# inputs (process liveness, log deltas, adoption) and calls into these.
# ---------------------------------------------------------------------------


class PermitCapability(str, Enum):
    """[B1/D2] The permit-lapse watch's own closed-set classification of
    "can this trading day still submit orders right now", evaluated once per
    poll inside :data:`B1_WINDOW_OPEN_UTC`--``midday_watch_window_end``."""

    UNKNOWN = "unknown"
    VALID = "valid"
    LAPSED = "lapsed"
    EXPIRED_AT_CEILING = "expired_at_ceiling"
    NOT_REQUIRED = "not_required"
    DEFERRED = "deferred"
    ABSENT = "absent"
    NO_NODE = "no_node"
    #: [D8] Fed into :func:`decide_permit_alert` when B1's own evaluation
    #: raised -- never returned by :func:`permit_capability_valid` itself.
    WATCH_FAILED = "watch_failed"


def permit_watch_window(trading_day: dt.date) -> tuple[dt.datetime, dt.datetime]:
    """[B1/D2] The watch's own window: ``[B1_WINDOW_OPEN_UTC`` on
    ``trading_day``, ``midday_watch_window_end(trading_day))`` -- identical
    bounds to MIDDAY_WATCH's own window, by design (D1: never a third
    independent schedule boundary)."""
    return _at(trading_day, B1_WINDOW_OPEN_UTC), midday_watch_window_end(trading_day)


def midday_budget_live(
    *,
    launch_done: bool,
    readiness_observed: bool,
    midday_watch_window_open: bool,
    midday_alert_sent: bool,
    midday_ceiling_unknown_alert_sent: bool,
    midday_relaunch_attempts: int,
) -> bool:
    """[B1/D3] True only when a mid-day relaunch remains a live possibility
    for the CURRENT dead child -- every one of MIDDAY_WATCH's own
    preconditions plus neither of its two day-level exhaustion latches plus
    budget remaining. Used ONLY to decide DEFERRED-vs-NO_NODE (D2 row 5a);
    never consulted for B1's own alerting, which reacts to a genuine
    permit-expiry latch regardless of this value (AC3)."""
    return (
        launch_done
        and readiness_observed
        and midday_watch_window_open
        and not midday_alert_sent
        and not midday_ceiling_unknown_alert_sent
        and midday_relaunch_attempts < MIDDAY_MAX_RELAUNCH_ATTEMPTS
    )


def permit_capability_valid(
    state: DaySchedulerState,
    now_ns: int,
    *,
    child_alive: bool,
    log_available: bool,
    midday_budget_live: bool,
) -> PermitCapability:
    """[B1/D2/D2a/D3] The capability table, evaluated in the documented
    order. Never returns :attr:`PermitCapability.WATCH_FAILED` -- that value
    is fed directly into :func:`decide_permit_alert` by the I/O shell's own
    exception containment (D8), never derived here."""
    if child_alive and not log_available:
        return PermitCapability.UNKNOWN

    latched_expiry_ns = state.permit_issued_seen_expires_at_ns
    if latched_expiry_ns is not None:
        if latched_expiry_ns > now_ns:
            return PermitCapability.VALID
        if (
            latched_expiry_ns == state.first_boot_permit_expires_at_ns
            and (state.relaunch_attempts + state.midday_relaunch_attempts) > 0
        ):
            return PermitCapability.EXPIRED_AT_CEILING
        return PermitCapability.LAPSED

    if state.orders_not_requested_seen:
        return PermitCapability.NOT_REQUIRED

    if not child_alive:
        deferred_candidate = midday_budget_live
    else:
        # [silent-failure-review A1] The boot grace applies ONLY to a
        # midday-relaunched child -- a never-relaunched (16:50Z) first boot
        # with no permit line has no ``last_midday_relaunch_attempt_at`` at
        # all and must resolve to ABSENT, never a silent, unbounded DEFERRED.
        last_midday_attempt = state.last_midday_relaunch_attempt_at
        if last_midday_attempt is None:
            deferred_candidate = False
        else:
            grace_ns = int(MIDDAY_READINESS_RECHECK_TIMEOUT.total_seconds() * 1e9)
            attempt_ns = int(last_midday_attempt.timestamp() * 1e9)
            deferred_candidate = (now_ns - attempt_ns) < grace_ns

    if deferred_candidate:
        if state.permit_deferred_since is not None:
            since_ns = int(state.permit_deferred_since.timestamp() * 1e9)
            deferred_max_ns = int(PERMIT_DEFERRED_MAX.total_seconds() * 1e9)
            if now_ns - since_ns > deferred_max_ns:
                return PermitCapability.NO_NODE
        return PermitCapability.DEFERRED

    if not child_alive:
        return PermitCapability.NO_NODE
    # [D2a] Alive, log readable (checked at the top), no permit latch, no
    # not-required marker, past the boot grace -- ABSENT, never UNKNOWN.
    return PermitCapability.ABSENT


class PermitAlertAction(str, Enum):
    """[B1] What :func:`decide_permit_alert` wants the I/O shell to do."""

    NONE = "none"
    ALERT = "alert"
    #: Bad -> VALID transition -- one INFO log line, never an ``alert()``
    #: call (there is no operator-facing severity for "it recovered").
    RESTORED = "restored"


@dataclass(frozen=True, slots=True)
class PermitAlertDecision:
    action: PermitAlertAction
    severity: str | None = None
    event: str | None = None
    detail: AlertDetail | None = None


#: Every :class:`PermitCapability` that is a genuine fault, mapped to its
#: fixed :class:`AlertDetail`. ``VALID``, ``NOT_REQUIRED`` and ``DEFERRED``
#: are deliberately absent -- each has its own bespoke handling below.
_PERMIT_ALERT_DETAIL: Final[dict[PermitCapability, AlertDetail]] = {
    PermitCapability.LAPSED: AlertDetail.PERMIT_LAPSED_IN_DECISION_WINDOW,
    PermitCapability.EXPIRED_AT_CEILING: (
        AlertDetail.PERMIT_EXPIRED_AT_DAILY_CEILING_IN_DECISION_WINDOW
    ),
    PermitCapability.ABSENT: AlertDetail.PERMIT_ABSENT_IN_DECISION_WINDOW,
    PermitCapability.NO_NODE: AlertDetail.PERMIT_NO_NODE_IN_DECISION_WINDOW,
    PermitCapability.UNKNOWN: AlertDetail.PERMIT_UNVERIFIABLE,
    PermitCapability.WATCH_FAILED: AlertDetail.PERMIT_WATCH_EXCEPTION_CONTAINED,
}
_BAD_CAPABILITY_VALUES: Final[frozenset[str]] = frozenset(
    capability.value for capability in _PERMIT_ALERT_DETAIL
)


def decide_permit_alert(
    *,
    capability: PermitCapability,
    now: dt.datetime,
    last_sent_at: dt.datetime | None,
    last_capability: str | None,
    not_required_warned: bool,
) -> PermitAlertDecision:
    """[B1/D5] The heartbeat/change/once-per-day decision, pure. ``changed``
    is deliberately ``False`` on a true first observation (``last_capability
    is None``) -- that case alerts because ``heartbeat_elapsed`` is True
    when nothing has ever been sent, not because it "changed". This is what
    lets :func:`seed_permit_alert` (which sets only ``last_sent_at``, never
    ``last_capability``) suppress B1's own first page for the SAME
    underlying fault another handler already alerted on, while a genuine
    capability CHANGE still bypasses the heartbeat (AC5 vs "a change to a
    different bad capability emits immediately")."""
    if capability is PermitCapability.NOT_REQUIRED:
        if not_required_warned:
            return PermitAlertDecision(action=PermitAlertAction.NONE)
        return PermitAlertDecision(
            action=PermitAlertAction.ALERT,
            severity="WARN",
            event="TRADE_SUPERVISOR_PERMIT_NOT_REQUIRED",
            detail=AlertDetail.PERMIT_NOT_REQUIRED_SHADOW,
        )
    if capability is PermitCapability.DEFERRED:
        return PermitAlertDecision(action=PermitAlertAction.NONE)
    if capability is PermitCapability.VALID:
        if last_capability is not None and last_capability in _BAD_CAPABILITY_VALUES:
            return PermitAlertDecision(action=PermitAlertAction.RESTORED)
        return PermitAlertDecision(action=PermitAlertAction.NONE)
    if capability.value in _BAD_CAPABILITY_VALUES:
        changed = last_capability is not None and last_capability != capability.value
        heartbeat_elapsed = last_sent_at is None or (now - last_sent_at) >= PERMIT_ALERT_HEARTBEAT
        if changed or heartbeat_elapsed:
            return PermitAlertDecision(
                action=PermitAlertAction.ALERT,
                severity="CRITICAL",
                event="TRADE_SUPERVISOR_PERMIT_WATCH",
                detail=_PERMIT_ALERT_DETAIL[capability],
            )
        return PermitAlertDecision(action=PermitAlertAction.NONE)
    # [silent-failure-hunter/python-reviewer review] An unmapped capability
    # must fail loudly, never silently resolve to NONE -- a future
    # PermitCapability member added without a matching `_PERMIT_ALERT_DETAIL`
    # entry (or `VALID`/`DEFERRED`/`NOT_REQUIRED` handling above) would
    # otherwise be swallowed here forever. D8's own containment
    # (`_do_permit_watch`) turns this into a CRITICAL `WATCH_FAILED` page,
    # never silence.
    raise AssertionError(f"unmapped PermitCapability {capability!r}")


def latch_log_facts(
    state: DaySchedulerState, now_utc: dt.datetime, log_text: str
) -> DaySchedulerState:
    """[B1/D6] Pure projection of an already-read log-reader delta onto
    every latch the three existing handlers' own inline logic would set
    from the same text: strategy-subscribed, permit-issued (+ the
    first-boot anchor), the first non-``UNKNOWN`` exit-1 cause, and the
    orders-not-requested marker. Used ONLY by B1, and ONLY on a drain the
    dispatched handler itself did not perform (D6).

    [FU-1, 2026-09-25] Investigated migrating ``_do_relaunch_check``,
    ``_do_midday_watch``, and ``_do_self_check`` onto this helper; declined
    for all three, byte-identical-behaviour constraint (each handler's own
    inline sequence is gated on live-vs-latched values, or an early return,
    this helper does not expose, so calling it directly would change
    alerting/relaunch behaviour, not just tidy the code).

    That investigation found the three handlers' own inline sequences were
    NOT actually at parity with what this helper latches from the same
    drained text: ``_do_relaunch_check`` never recorded ``midday_cause_seen``,
    and both ``_do_midday_watch`` and ``_do_self_check`` never recorded
    ``orders_not_requested_seen`` -- each a real gap (fixed inline, same
    2026-09-25 change, not by migrating onto this helper), since B1's own
    call to this helper is skipped whenever the dispatched handler is the
    one that read the log (``handler_read_log``), and by the time B1 next
    runs, the shared, offset-draining ``IncrementalLogReader``'s next delta
    no longer holds the line. All four handlers (this helper plus the three
    inline callers) now latch the same superset of facts from a delta they
    each drain -- parity restored without merging their control flow."""
    if strategy_subscribed_in(log_text):
        state = record_strategy_subscribed_seen(state, now_utc)
    permit_expiry_ns = parse_permit_expiry_ns(log_text)
    if permit_expiry_ns is not None:
        state = record_permit_issued_seen(state, now_utc, permit_expiry_ns)
        state = record_first_boot_permit_seen(state, now_utc, permit_expiry_ns)
    cause = classify_exit1_cause(log_text)
    if cause is not RelaunchCause.UNKNOWN:
        state = record_midday_cause_seen(state, now_utc, cause)
    if PERMIT_NOT_REQUESTED_MARKER in log_text:
        state = record_orders_not_requested_seen(state, now_utc)
    # [FU-17, r4->r5 ruling 6] The identical per-site gap the 2026-09-25
    # FU-1 fix already had to close once for `midday_cause_seen`/
    # `orders_not_requested_seen` above: this latch must be wired at EVERY
    # log-read site, not just `_do_relaunch_check`'s.
    if zero_instruments_refusal_in(log_text) and not state.boot_zero_instruments_seen:
        state = record_boot_zero_instruments_seen(state, now_utc)
    return state


def record_orders_not_requested_seen(
    state: DaySchedulerState, now_utc: dt.datetime
) -> DaySchedulerState:
    """[B1/D9] First-seen-wins per-child latch for
    :data:`PERMIT_NOT_REQUESTED_MARKER`. Cleared by
    :func:`record_child_adopted` for the next child."""
    effective = _for_day(state, _trading_day(now_utc))
    if effective.orders_not_requested_seen:
        return effective
    return replace(effective, orders_not_requested_seen=True)


def record_permit_deferred_since(
    state: DaySchedulerState, now_utc: dt.datetime, *, capability: PermitCapability
) -> DaySchedulerState:
    """[B1/D3, silent-failure-review A1] Set on first entering DEFERRED;
    cleared ONLY by a VALID or NOT_REQUIRED observation, never by an
    interstitial UNKNOWN/LAPSED/ABSENT/NO_NODE -- so a DEFERRED -> UNKNOWN
    -> DEFERRED flicker still promotes to NO_NODE 20 minutes from the FIRST
    observation, never resets."""
    effective = _for_day(state, _trading_day(now_utc))
    if capability is PermitCapability.DEFERRED:
        if effective.permit_deferred_since is not None:
            return effective
        return replace(effective, permit_deferred_since=now_utc)
    if capability in (PermitCapability.VALID, PermitCapability.NOT_REQUIRED):
        if effective.permit_deferred_since is None:
            return effective
        return replace(effective, permit_deferred_since=None)
    return effective


def record_permit_not_required_warned(
    state: DaySchedulerState, now_utc: dt.datetime
) -> DaySchedulerState:
    """[B1/D9] Gates the once-per-day WARN. Idempotent."""
    effective = _for_day(state, _trading_day(now_utc))
    if effective.permit_not_required_warned:
        return effective
    return replace(effective, permit_not_required_warned=True)


def record_permit_gap_info_logged(
    state: DaySchedulerState, now_utc: dt.datetime
) -> DaySchedulerState:
    """[B1/D2] Gates the one ``permit_accepted_gap`` INFO line to once per
    trading day. Idempotent."""
    effective = _for_day(state, _trading_day(now_utc))
    if effective.permit_gap_info_logged:
        return effective
    return replace(effective, permit_gap_info_logged=True)


def record_permit_alert_sent(
    state: DaySchedulerState, now_utc: dt.datetime, *, capability: PermitCapability
) -> DaySchedulerState:
    """[B1/D5] Latch the heartbeat timer and the last-alerted capability --
    called by the shell only AFTER ``alert()`` returns successfully
    (silent-failure-review A2), so a failed send is retried on the next
    poll rather than silenced for a heartbeat. Also used, with
    ``capability=PermitCapability.VALID``, to clear ``last_capability`` on a
    RESTORED transition."""
    effective = _for_day(state, _trading_day(now_utc))
    return replace(
        effective,
        permit_alert_last_sent_at=now_utc,
        permit_alert_last_capability=capability.value,
    )


def seed_permit_alert(state: DaySchedulerState, now_utc: dt.datetime) -> DaySchedulerState:
    """[B1/D5] Seed ONLY the heartbeat timer (never ``last_capability``) from
    a FAIL/CRITICAL another handler (self-check, mid-day watch) already
    alerted on this poll -- so B1's own first page for the SAME underlying
    fault is suppressed until the heartbeat elapses (AC5), while a later
    capability CHANGE observed by B1 itself still bypasses the heartbeat
    (see :func:`decide_permit_alert`'s docstring)."""
    effective = _for_day(state, _trading_day(now_utc))
    return replace(effective, permit_alert_last_sent_at=now_utc)
