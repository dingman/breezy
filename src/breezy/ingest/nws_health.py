"""NWS site health emission: alert-condition evaluation and snapshot dispatch.

Moved out of :mod:`breezy.ingest.nws_actor` (refactor R3.6) as free functions
over the actor; the actor keeps thin delegators (`_emit_health`,
`_alert_conditions`) so the call site and every test hook are unchanged.

This module imports :class:`NwsIngestActor` ONLY under ``TYPE_CHECKING`` (no
runtime cycle) and never imports ``breezy.runtime``: health I/O reaches it via
the actor's injected ``health_io`` seam.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Final

from breezy.ingest import gaps
from breezy.ingest.gate import GateReason, GateState, GateStatus
from breezy.registry.health_model import (
    FINAL_OVERDUE,
    GAP_RETENTION_WARNING,
    POLL_STALE,
    POST_SETTLEMENT_REVISION,
    SCHEMA_VERSION,
    SITE_BLOCKED,
    UA_TRAP_LATCHED,
    AlertCondition,
    AlertConditionKey,
    AlertPayload,
    AlertSink,
    GapSummary,
    HealthIO,
    HealthSnapshot,
    SiteHealth,
)

if TYPE_CHECKING:
    from breezy.ingest.nws_actor import NwsIngestActor

__all__ = [
    "CHRONIC_UNREADABLE_PRODUCT",
    "CHRONIC_UNREADABLE_PRODUCT_STREAK",
    "LEDGER_UNAVAILABLE",
    "SITE_BLOCKED_ALERT_INTERVALS",
    "STALENESS_DEGRADE_INTERVALS",
    "alert_conditions",
    "emit_health",
]

_NS_PER_SECOND: Final[int] = 1_000_000_000

#: `AlertCondition.key.kind`/`event` for "this site's gap ledger could not be
#: read or reconciled this cycle".
#:
#: Declared HERE and not in `runtime/health.py` alongside that module's other
#: kind constants, and the asymmetry is deliberate: `health.py` documents
#: itself as importing nothing from `breezy.ingest` and knowing nothing of the
#: ledger's vocabulary, while the condition is raised only from this module's
#: `reconcile_and_report` failure handler. `AlertConditionKey.kind` is a plain
#: `str` by that module's own design ("kept as plain strings (not an `Enum`) so
#: the ... wiring code can construct `AlertConditionKey`s without importing an
#: enum"), so the wiring owning the condition also owns its name.
LEDGER_UNAVAILABLE: Final[str] = "ledger_unavailable"

#: `AlertCondition.key.kind`/`event` for "this site's CLI parses have left a
#: non-settlement-bearing field (tmin/tavg) unreadable for
#: :data:`CHRONIC_UNREADABLE_PRODUCT_STREAK` CONSECUTIVE parses" -- CF-5b.
#:
#: CF-5's own per-occurrence signal (the `logger.warning` loop in
#: `_prepare_product`) is correct as the immediate, always-fires-per-poll
#: log line: a field warning must never hard-block the site, so it cannot
#: route through the gate the way a genuine parse failure does. But nothing
#: previously tracked the condition CHRONICALLY, so a field left unreadable
#: for days produced an unbroken stream of identical WARNING lines and never
#: reached the operator-facing `AlertState` every other standing condition
#: here goes through. Declared here, alongside `LEDGER_UNAVAILABLE`, for the
#: same reason that constant is: the condition is raised only from this
#: module's own parse path, and `health.py` knows nothing of it.
CHRONIC_UNREADABLE_PRODUCT: Final[str] = "chronic_unreadable_product"

#: A site with an unreadable field on this many CONSECUTIVE CLI parses raises
#: the deduped `CHRONIC_UNREADABLE_PRODUCT` alert. Same reasoning as
#: `SITE_BLOCKED_ALERT_INTERVALS`: patience before paging, without a second
#: knob to keep in sync with the poll cadence -- though this one counts
#: consecutive PARSES (one per fetched product), not poll intervals, since a
#: parse only happens when a product was actually fetched.
CHRONIC_UNREADABLE_PRODUCT_STREAK: Final[int] = 4

#: Staleness thresholds, derived from the configured poll interval rather than
#: from new config fields. Four missed intervals is a degrade; twelve is a
#: block. Both are multipliers on the ONE cadence the site actually has, so a
#: site polling every five minutes and one polling every hour get proportionate
#: watchdogs without a second knob to keep in sync.
STALENESS_DEGRADE_INTERVALS: Final[int] = 4

#: A site continuously BLOCKED for this many poll intervals raises the
#: `SiteBlocked` alert. Same reasoning as the two multipliers above -- derived
#: from the ONE cadence the site actually has, so there is no second knob to
#: keep in sync, and a five-minute site and an hourly site get proportionate
#: patience without either being configured separately.
SITE_BLOCKED_ALERT_INTERVALS: Final[int] = 4


async def emit_health(
    actor: NwsIngestActor,
    now_ns: int,
    *,
    entries: Sequence[gaps.GapEntry],
    revisions: Sequence[gaps.RevisionEvent],
) -> None:
    """Build this cycle's alert conditions and `HealthSnapshot`, dispatch,
    and write the snapshot atomically if a path is configured.

    The ``GapEntry -> GapSummary`` mapping lives HERE, at the call site,
    and that is deliberate: ``health.py`` does not import
    ``breezy.ingest`` and ``gaps.py`` does not import ``health`` -- neither
    module may learn the other's vocabulary, so the adapter belongs to the
    wiring that already knows both.
    """
    health_io = actor._health_io()

    status = actor.gate.status(actor._venue, actor._city)
    causes = actor.gate.blocking_causes(actor._venue, actor._city)
    ua_latched = GateReason.UA_TRAP_403 in causes
    site_label = f"{actor._venue}/{actor._city}"
    today = gaps.local_standard_date(now_ns, actor._window.std_utc_offset_hours)

    # `open_gaps` deliberately includes ACKNOWLEDGED_LOST: an acknowledged
    # day is muted for re-notify, never hidden. Removing it from the
    # snapshot would make an operator's acknowledgement look like a repair.
    summaries = tuple(
        GapSummary(
            climate_day=entry.climate_day.isoformat(),
            state=entry.state.value,
            severity=gaps.severity_for(entry.climate_day, today).value,
            days_until_retention_loss=gaps.days_remaining_until_retention_loss(
                entry.climate_day, today
            ),
        )
        for entry in entries
        if entry.state is not gaps.GapState.RESOLVED
    )
    acknowledged_lost = sum(
        1 for entry in entries if entry.state is gaps.GapState.ACKNOWLEDGED_LOST
    )

    conditions = actor._alert_conditions(
        now_ns,
        site_label=site_label,
        status=status,
        causes=causes,
        ua_latched=ua_latched,
        entries=entries,
        summaries=summaries,
        revisions=revisions,
    )
    # SPLIT ACROSS THE THREAD BOUNDARY, deliberately, and the split line
    # is the whole point.
    #
    # `evaluate` -- ON THE LOOP THREAD. It is a read-modify-write over
    # `AlertState`'s two dicts, and that class documents itself as
    # "deliberately not thread-safe ... exactly one poll loop is expected
    # to own an instance". Running it on an executor worker made that
    # ownership claim false: it was safe only because no other code path
    # dispatches alerts today -- thread-safety by exclusion, which the
    # next caller added anywhere silently converts into a data race over
    # the exact transitions that must never be lost (`UA_TRAP_LATCHED`,
    # `SITE_BLOCKED` are latched-persistent, so a lost false->true edge is
    # not re-tried until the 24h re-notify). It is pure bookkeeping over
    # a handful of dict entries, so it costs the loop nothing.
    #
    # `emit_alert` -- OFF THE LOOP, under the same ceiling as before. This
    # is the half with a real reason to leave: `WebhookAlertSink.emit` is
    # a SYNCHRONOUS `httpx.Client.post` with a 5s default timeout, and the
    # incident case is exactly the case it fires in -- several sites
    # transitioning to blocked at once serialises those POSTs and delays
    # every other site's poll and final-overdue check near a settlement
    # deadline.
    #
    # The `dispatch` contract is preserved exactly: `emitted` is what this
    # cycle DECIDED to emit, never what the sink managed to deliver, and
    # `emit_alert` still swallows every sink failure inside the worker.
    # The whole fan-out is one `_bounded_io` call, as `dispatch` was, so a
    # black-holed webhook still trips the ceiling and routes to
    # `_record_task_death` rather than parking a worker forever.
    tracker = actor._alert_tracker(health_io)
    sink = actor._resolved_alert_sink(health_io)
    payloads = tracker.evaluate(conditions, now_ns=now_ns)
    emitted = len(payloads)
    if payloads:
        await actor._bounded_io(lambda: _emit_all(health_io, sink, payloads))

    snapshot = HealthSnapshot(
        schema_version=SCHEMA_VERSION,
        process_started_at_ns=actor._process_started_at_ns,
        snapshot_at_ns=now_ns,
        trader_id=str(getattr(actor, "trader_id", "") or ""),
        sites=(
            SiteHealth(
                venue=actor._venue,
                city=actor._city,
                gate_state=status.state.value,
                gate_reason=status.reason.value,
                blocking_causes=tuple(cause.value for cause in causes),
                last_successful_poll_ns=status.last_successful_poll_ns,
                cursor=actor._cursor_text(),
                open_gaps=summaries,
                acknowledged_lost_count=acknowledged_lost,
                # The FILE-based half of the `LEDGER_UNAVAILABLE` signal.
                # The alert alone is not enough: `BREEZY_ALERT_WEBHOOK_URL`
                # is unset by default, so `resolve_alert_sink` yields a
                # LOGGING sink and the CRITICAL reaches nothing an operator
                # polls -- while the runbook points them at
                # `health-<venue>.<city>.json`. Without this field that
                # file shows `open_gaps: []`, byte-identical to a healthy
                # site, for a ledger that has been unreadable for days.
                ledger_unavailable=actor._ledger_failure_detail,
            ),
        ),
        ua_trap_latched=ua_latched,
        alerts_emitted_this_cycle=emitted,
    )
    actor.last_health_snapshot = snapshot
    snapshot_path = actor.health_snapshot_path
    if snapshot_path is not None:
        # Off the loop for the same reason as the dispatch above:
        # `write_snapshot_atomic` does an `fsync` plus a rename, and a
        # stalled disk must not be able to hold the poll cycle's thread.
        # BOUNDED for the second reason: off-loop-and-unbounded is a
        # fail-open, not a fix -- see `_bounded_io`.
        await actor._bounded_io(lambda: health_io.write_snapshot_atomic(snapshot_path, snapshot))


def _emit_all(health_io: HealthIO, sink: AlertSink, payloads: Sequence[AlertPayload]) -> None:
    """The blocking half of the old `AlertState.dispatch`, run on a worker.

    Kept as a named method rather than a comprehension inside the lambda so
    the executor call site reads as "fan out these already-decided
    payloads" -- the decision itself happened on the loop thread.
    """
    for payload in payloads:
        health_io.emit_alert(sink, payload)


def alert_conditions(
    actor: NwsIngestActor,
    now_ns: int,
    *,
    site_label: str,
    status: GateStatus,
    causes: Sequence[GateReason],
    ua_latched: bool,
    entries: Sequence[gaps.GapEntry],
    summaries: Sequence[GapSummary],
    revisions: Sequence[gaps.RevisionEvent],
) -> list[AlertCondition]:
    """Every condition this site tracks, evaluated fresh for this cycle.

    ``AlertState.evaluate`` leaves a key it is not handed untouched, so
    every standing condition is passed on every cycle -- including the ones
    that are ``active=False``, which is what lets a cleared condition fire
    again next time it sets.

    ``detail`` strings are short and structural by construction: no
    absolute path, no upstream body or header, no settings field. The
    snapshot has no slot for those either, so neither artifact can leak
    ``user_agent_contact``.
    """
    blocked_after_ns = (
        int(actor._config.poll_interval_seconds) * SITE_BLOCKED_ALERT_INTERVALS * _NS_PER_SECOND
    )
    # Duration is measured from when THIS process first OBSERVED the block,
    # never from `GateStatus.at_ns`. Two independent reasons, both found by
    # test rather than by inspection:
    #
    # 1. `at_ns` is the last TRANSITION instant, and a blocked site keeps
    #    transitioning -- `check_staleness` alone re-records every cycle.
    #    Elapsed-since-`at_ns` therefore resets continuously and a
    #    permanently blocked site would never reach the threshold at all.
    # 2. A never-polled site reports `BLOCKED` with `at_ns == 0`, so the
    #    same arithmetic reads the entire Unix epoch as downtime and pages
    #    CRITICAL on every fresh deployment.
    #
    # In-memory and never persisted, matching `AlertState`'s own cold-start
    # stance: at boot the site is unobserved, so the clock starts now and a
    # genuinely dead-on-arrival deployment alerts after the threshold --
    # which is the ONLY signal for that case, since `PollStale` cannot fire
    # while `last_successful_poll_ns` is still `None`. Sampled once per
    # cycle, because once per cycle is the only observation cadence there
    # is.
    if status.state is GateState.BLOCKED:
        if actor._blocked_since_ns is None:
            actor._blocked_since_ns = now_ns
    else:
        actor._blocked_since_ns = None
    blocked_long = (
        actor._blocked_since_ns is not None and now_ns - actor._blocked_since_ns >= blocked_after_ns
    )
    last_poll_ns = status.last_successful_poll_ns
    poll_stale = (
        last_poll_ns is not None and now_ns - last_poll_ns >= actor.staleness_degraded_after_ns
    )

    conditions: list[AlertCondition] = [
        AlertCondition(
            key=AlertConditionKey(kind=UA_TRAP_LATCHED, site="global"),
            active=ua_latched,
            severity="CRITICAL",
            event=UA_TRAP_LATCHED,
            detail="global UA-trap latch is set; every site has stopped polling",
        ),
        AlertCondition(
            key=AlertConditionKey(kind=SITE_BLOCKED, site=site_label),
            active=blocked_long,
            severity="CRITICAL",
            event=SITE_BLOCKED,
            detail=(
                f"blocked for at least {SITE_BLOCKED_ALERT_INTERVALS} poll intervals; "
                f"causes={','.join(cause.value for cause in causes)}"
            ),
        ),
        AlertCondition(
            key=AlertConditionKey(kind=FINAL_OVERDUE, site=site_label),
            active=GateReason.FINAL_CLI_OVERDUE in causes,
            severity="CRITICAL",
            event=FINAL_OVERDUE,
            detail="the final CLI is overdue past the venue settlement deadline",
        ),
        AlertCondition(
            key=AlertConditionKey(kind=POLL_STALE, site=site_label),
            active=poll_stale,
            severity="WARN",
            event=POLL_STALE,
            detail=(
                f"no successful poll for at least {STALENESS_DEGRADE_INTERVALS} poll intervals"
            ),
        ),
        # CRITICAL, and passed on EVERY cycle -- inactive ones included,
        # so `AlertState` sees the true->false edge and the next failure
        # is a fresh false->true rather than a 24h-muted repeat.
        #
        # This is the only signal that `reconcile_and_report`'s swallowed
        # branch fired. Without it the ledger can be unreadable
        # indefinitely while the snapshot reports `open_gaps: []` -- zero
        # gaps and zero alerts are exactly what a HEALTHY site looks like,
        # so the failure is indistinguishable from success. CRITICAL and
        # not WARN because a dead ledger means revision detection is off:
        # a superseded final can be settled on with nothing to notice it.
        AlertCondition(
            key=AlertConditionKey(kind=LEDGER_UNAVAILABLE, site=site_label),
            active=actor._ledger_failure_detail is not None,
            severity="CRITICAL",
            event=LEDGER_UNAVAILABLE,
            detail=(
                "gap ledger reconciliation failed; open_gaps in this snapshot is "
                f"NOT authoritative ({actor._ledger_failure_detail})"
            ),
        ),
        # CF-5b: WARN, not CRITICAL -- this never hard-blocks the site
        # (CF-5's own ruling), it only means a non-settlement-bearing
        # field has been unreadable for a while. Passed on EVERY cycle,
        # inactive included, for the same false->true re-arming reason as
        # `LEDGER_UNAVAILABLE` above.
        AlertCondition(
            key=AlertConditionKey(kind=CHRONIC_UNREADABLE_PRODUCT, site=site_label),
            active=actor._unreadable_field_streak >= CHRONIC_UNREADABLE_PRODUCT_STREAK,
            severity="WARN",
            event=CHRONIC_UNREADABLE_PRODUCT,
            detail=(
                f"{actor._unreadable_field_streak} consecutive CLI parse(s) left a "
                "non-settlement-bearing field unreadable; settlement-bearing "
                "fields are unaffected"
            ),
        ),
    ]

    # One condition per gap inside the retention warning band, keyed by
    # climate day so several simultaneous gaps each alert once rather than
    # collapsing into a single flapping condition. ACKNOWLEDGED_LOST is
    # muted for re-notify but still fires on transition and still appears
    # in the snapshot -- acknowledgement silences repetition, not the fact.
    acknowledged_days = {
        entry.climate_day.isoformat()
        for entry in entries
        if entry.state is gaps.GapState.ACKNOWLEDGED_LOST
    }
    for summary in summaries:
        conditions.append(
            AlertCondition(
                key=AlertConditionKey(
                    kind=GAP_RETENTION_WARNING,
                    site=site_label,
                    extra=summary.climate_day,
                ),
                active=summary.severity != gaps.GapSeverity.INFO.value,
                severity=summary.severity.upper(),
                event=GAP_RETENTION_WARNING,
                detail=(
                    f"climate day {summary.climate_day} is {summary.state} with "
                    f"{summary.days_until_retention_loss} day(s) until assumed "
                    f"retention loss"
                ),
                renotify_muted=summary.climate_day in acknowledged_days,
            )
        )

    # A revision is an EVENT, not a standing condition: `extra` carries the
    # new sequence number so each distinct revision is a distinct key and
    # therefore always a false->true transition. Passed only on the cycle
    # it is observed; a key not passed is left untouched, never cleared.
    for revision in revisions:
        conditions.append(
            AlertCondition(
                key=AlertConditionKey(
                    kind=POST_SETTLEMENT_REVISION,
                    site=site_label,
                    extra=f"{revision.climate_day.isoformat()}:{revision.new_revision_seq}",
                ),
                active=True,
                severity="CRITICAL",
                event=POST_SETTLEMENT_REVISION,
                detail=(
                    f"climate day {revision.climate_day.isoformat()} revised "
                    f"{revision.previous_revision_seq}->{revision.new_revision_seq} "
                    f"correction={revision.correction_flag} "
                    f"superseded={revision.is_superseded}"
                ),
            )
        )
    return conditions
