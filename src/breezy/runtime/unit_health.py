"""AUT-6 unit health pass core (plan r15 section 3.9; E-7e(f); F2, F4, F6, F10; WP3 S3).

One pass, in this order (the snapshot FIRST, so every failure it lists predates the journal read):

1. read the bus snapshot (the only systemd read) and validate it;
2. take the health lock; read the journal's unit-failed entries after the stored cursor;
3. for each in-scope entry, in journal order: classification record (``O_EXCL``, deduped on
   ``USER_INVOCATION_ID``), the alert (enqueued: the health row has no network), action record;
4. reconcile every in-scope failed unit of the snapshot against a classification record, with one
   targeted lookup by ``InvocationID`` when none exists; a unit the journal cannot show gets a
   ``journal_blind`` CRITICAL (enqueued once) and makes the pass UNKNOWN, but once that alert is
   durably enqueued it no longer holds the cursor back from the other units;
5. when every entry has both records: the ``seen`` files, then the cursor LAST.

Delivery is at-least-once. The alert is enqueued BEFORE its action record is written, so a crash
between the two replays the entry on the next pass and may page twice; it never writes two action
records and never loses the page.

Any systemd or journal error, the 90 s budget, an unreadable fold, an unreadable class record, a
store error, unknown ownership and an enqueue refusal make the pass UNKNOWN: the streak grows, the
heartbeat keeps its old ``ts_ns`` and nothing reads as zero failures. The health unit changes
nothing in systemd and reads none of the trading gates (X-6).

Operator step for an unreadable class record: records are 0444 and write-once and the health
unit never repairs one. The pass pages CRITICAL ``class_record_unreadable`` naming the file
(``<unit>__<invocation>__class.json``) and stays UNKNOWN; move that file out of
``evidence/unit_health/<day>/``, and the next pass reclassifies the failure from the journal.

Known limitation: scope is judged by unit name and, for ``run-*`` transients, by the path
properties of the show block. A Breezy transient started with a custom ``--unit=`` name that is
neither ``breezy-*`` nor ``run-*`` is read as foreign (listed under ``foreign_failed``), because
nothing else about it is visible to the snapshot reads. A ``run-*`` transient that has left the
snapshot (``--collect``, reset, failed between the snapshot and the journal read) is
``UNRESOLVED_TRANSIENT``, never foreign.
"""

from __future__ import annotations

import logging
import os
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final

from breezy.registry.health_model import AlertPayload
from breezy.runtime.autonomy_sandbox.bus_handoff import (
    BusSnapshot,
    BusSnapshotError,
    read_bus_snapshot,
)
from breezy.runtime.monitor_watch import production_watch
from breezy.runtime.monitor_watch_apply import apply_watch
from breezy.runtime.monitor_watch_memory import addback_kib, addback_units, free_addback_kib
from breezy.runtime.unit_health_daemon_support import DaemonWiring, SubprocessDaemonJournal
from breezy.runtime.unit_health_daemons import run_daemon_rules
from breezy.runtime.unit_health_journal import (
    MIN_CALL_S,
    PER_CALL_CAP_S,
    JournalBatch,
    JournalError,
    SubprocessJournal,
)
from breezy.runtime.unit_health_model import (
    FOREIGN_UNIT_PREFIXES,
    HEALTH_PASS_BUDGET_S,
    FailureEntry,
    Ownership,
    UnitFacts,
    WorktreesUnavailable,
    classify,
    facts_from_block,
    is_transient,
    needs_worktrees,
    ownership,
)
from breezy.runtime.unit_health_obs import (
    HEALTH_ROW,
    SnapshotUnusable,
    UnitObservation,
    parse_observation,
)
from breezy.runtime.unit_health_rollup import heartbeat_body, rollup_body, rollup_days
from breezy.runtime.unit_health_store import (
    NS,
    RECENT_INVOCATIONS_KEPT,
    HealthStore,
    StoreRecordError,
    alerts_delivered,
    day_of_ns,
    day_start_s,
    default_data_root,
    finding_site,
    health_root,
    previous_day,
    safe_key,
)
from breezy.runtime.unit_health_support import (
    DRIFT_CRITICAL_FROM,
    EVENT_JOURNAL_BLIND,
    DriftFinding,
    enqueue_health_alert,
    unexplained_for_day,
    unit_config_drift,
)
from breezy.runtime.unit_health_types import (
    PRODUCER_STALE_DETECTOR,
    FoldUnreadable,
    HostVerdict,
    NewFailure,
    PassEnv,
    PassResult,
)

__all__ = [
    "DRIFT_CRITICAL_FROM",
    "FOREIGN_UNIT_PREFIXES",
    "RECENT_INVOCATIONS_KEPT",
    "DriftFinding",
    "FoldUnreadable",
    "HostVerdict",
    "PassEnv",
    "PassResult",
    "alerts_delivered",
    "enqueue_health_alert",
    "observe_units",
    "production_env",
    "run_health_pass",
    "unexplained_for_day",
    "unit_config_drift",
]

EVENT_UNIT_FAILED: Final = "unit_health_unit_failed"
EVENT_FOLD_UNREADABLE: Final = "fold_unreadable"
EVENT_CONFIG_DRIFT: Final = "unit_config_drift"
EVENT_UNPARSEABLE: Final = "journal_entry_unparseable"
EVENT_CLASS_UNREADABLE: Final = "class_record_unreadable"
#: Units whose resident memory is added back to ``MemAvailable`` (section 3.10.1 item 6). S5 widens
#: this to the studies holders and own-lock units; the node lives in the supervisor's cgroup.
MEMORY_ADDBACK_UNITS: Final = frozenset(
    {
        "breezy-quote-tape-ingest.service",
        "breezy-quote-tape.service",
        "breezy-trade-supervisor.service",
    }
)
#: ``systemctl show`` prints an unset ``MemoryCurrent`` as 2**64 - 1.
_MEMORY_UNSET_FROM: Final = 2**63
_LOG: Final = logging.getLogger(__name__)
_INVOCATION_RE: Final = re.compile(r"[0-9a-f]{32}")
_HOST: Final = "_host"
_LOST_CURSOR_DAYS: Final = 2
_DAY_S: Final = 86_400


def production_env(
    *, environ: Mapping[str, str] | None = None, data_root: Path | None = None
) -> PassEnv:
    """The real wiring: bus snapshot, ``journalctl``, outbox enqueue. Touches nothing until run."""
    env_map: Mapping[str, str] = os.environ if environ is None else environ
    root = data_root if data_root is not None else default_data_root()
    alerts = root / "evidence" / "alerts"
    return PassEnv(
        store=HealthStore(health_root(root)),
        read_snapshot=lambda: read_bus_snapshot(HEALTH_ROW, environ=env_map),
        journal=SubprocessJournal(),
        alert=enqueue_health_alert(alerts),
        delivered=alerts_delivered(alerts),
        invocation_id=env_map.get("INVOCATION_ID", ""),
        daemons=DaemonWiring(SubprocessDaemonJournal(), alerts_root=alerts),
        watch=production_watch(root),
    )


def observe_units(
    *,
    environ: Mapping[str, str] | None = None,
    now_ns: Callable[[], int] = time.time_ns,
    snapshot: BusSnapshot | None = None,
) -> UnitObservation:
    """One validated observation. Without ``snapshot`` it runs the production reader once."""
    if snapshot is None:
        env_map: Mapping[str, str] = os.environ if environ is None else environ
        snapshot = read_bus_snapshot(HEALTH_ROW, environ=env_map)
    return parse_observation(snapshot, now_ns())


# --------------------------------------------------------------------------- the pass


class _Budget(Exception):
    pass


class _EnqueueFailed(Exception):
    pass


@dataclass
class _Scan:
    new_failures: list[NewFailure] = field(default_factory=list)
    new_findings: int = 0
    foreign: set[str] = field(default_factory=set)
    blind: list[str] = field(default_factory=list)
    touched: dict[str, list[str]] = field(default_factory=dict)
    days: set[str] = field(default_factory=set)
    failed_owned: int = 0
    batch: JournalBatch | None = None
    cursor_reset: bool = False
    drift: tuple[DriftFinding, ...] = ()
    reasons: list[str] = field(default_factory=list)
    blocking: bool = False
    #: Replaced-state fields of ``seen/<unit>.json`` the S4 rules stage for the commit step.
    daemon_seen: dict[str, dict[str, object]] = field(default_factory=dict)
    #: Units read INCONCLUSIVE(not_deployed) by the S5 hook: listed in the day rollup (X-8).
    not_deployed: list[str] = field(default_factory=list)
    #: Measured ``(node, recorder)`` VmRSS KiB: the same numbers the #31 sum uses (item 6).
    resident_kib: tuple[int, int] | None = None


def _site(unit: str, invocation: str) -> str:
    return f"unit_health:{unit}:{invocation}"


class _Pass:
    def __init__(self, env: PassEnv, started: float) -> None:
        self.env = env
        self.store = env.store
        self.deadline = started + HEALTH_PASS_BUDGET_S
        self.now = env.now_ns()
        self.today = day_of_ns(self.now)
        self._worktrees: tuple[str, ...] | None = None
        self._worktrees_failed = False
        self.scan = _Scan()
        self.observation = UnitObservation(0, {}, (), {})

    # ---- budget

    def allowance(self) -> float:
        remaining = self.deadline - self.env.monotonic()
        if remaining < MIN_CALL_S:
            raise _Budget
        return min(PER_CALL_CAP_S, remaining)

    def check_budget(self) -> None:
        if self.env.monotonic() >= self.deadline:
            raise _Budget

    def block(self) -> None:
        self.scan.blocking = True

    # ---- scope

    def ownership_of(self, unit: str, block: Mapping[str, str]) -> Ownership | None:
        """``None`` when ownership cannot be decided (git cannot list the worktrees)."""
        paths: tuple[str, ...] = ()
        if needs_worktrees(unit, block):
            if self._worktrees is None:
                if self._worktrees_failed:
                    return None
                try:
                    self._worktrees = tuple(self.env.worktrees(self.allowance()))
                except WorktreesUnavailable:
                    self._worktrees_failed = True
                    self.scan.reasons.append("ownership_unknown")
                    self.block()
                    return None
            paths = self._worktrees
        return ownership(unit, block, paths)

    # ---- journal

    def fallback_since_s(self, state_ts_ns: int | None) -> int:
        """Where a re-read starts. A rejected cursor: its own commit time. A lost cursor: the
        oldest of its surviving timestamp, the oldest unrolled day and today minus two days."""
        if state_ts_ns is not None:
            return state_ts_ns // NS
        floor = day_start_s(self.today) - _LOST_CURSOR_DAYS * _DAY_S
        candidates = [floor]
        hint = self.store.cursor_ts_hint()
        if hint is not None:
            candidates.append(hint // NS)
        oldest = self.store.oldest_unrolled_day()
        if oldest is not None:
            candidates.append(day_start_s(oldest))
        return min(candidates)

    def read_failures(self) -> JournalBatch:
        state = self.store.read_cursor()
        journal = self.env.journal
        if state is not None:
            try:
                return journal.failures(
                    after_cursor=state.cursor,
                    since_s=None if state.cursor else (state.since_us or 0) // 1_000_000,
                    timeout_s=self.allowance(),
                )
            except JournalError as exc:
                # A non-zero rc with a cursor falls back (a spurious reset is harmless: the
                # re-read is deduped on invocation id); timeout, oversize and parse stay UNKNOWN.
                if state.cursor is None or not exc.cursor_rejected:
                    raise
        batch = journal.failures(
            after_cursor=None,
            since_s=self.fallback_since_s(state.ts_ns if state is not None else None),
            timeout_s=self.allowance(),
        )
        self.store.write_cursor_reset(
            self.today, self.now, "cursor_missing" if state is None else "cursor_rejected"
        )
        self.scan.cursor_reset = True
        return batch

    # ---- records

    def is_repeat(self, entry: FailureEntry, facts: UnitFacts, day: str) -> bool:
        if facts.exit_status is None:
            return False
        for rec in self.store.class_records_for(entry.unit, previous_day(day)):
            if (
                rec.get("unit_result") == entry.unit_result
                and rec.get("exit_status") == facts.exit_status
                and rec.get("invocation_id") != entry.invocation_id
                and rec.get("unit_class") in {"EXIT_CODE", "EXPECTED_FAILURE_SUSPECT"}
            ):
                return True
        return False

    def class_body(
        self, entry: FailureEntry, block: Mapping[str, str], day: str, unresolved: bool
    ) -> dict[str, Any]:
        facts = facts_from_block(block, entry)
        if entry.unit_result == "timeout":
            seen = self.env.journal.resources_for_invocation(
                entry.invocation_id, timeout_s=self.allowance()
            )
            if seen is not None:
                facts = replace(
                    facts,
                    cpu_usage_ns=seen.cpu_usage_ns,
                    memory_peak=seen.memory_peak
                    if seen.memory_peak is not None
                    else facts.memory_peak,
                    memory_swap_peak=seen.memory_swap_peak
                    if seen.memory_swap_peak is not None
                    else facts.memory_swap_peak,
                )
        verdict = classify(
            entry,
            facts,
            transient=is_transient(entry.unit, block),
            suspect=self.is_repeat(entry, facts, day),
            unresolved=unresolved,
        )
        return {
            "schema": "unit_health_class/v1",
            "kind": "unit_failure",
            "unit": entry.unit,
            "invocation_id": entry.invocation_id,
            "unit_result": entry.unit_result,
            "unit_class": verdict.unit_class.value,
            "detector": verdict.detector,
            "action": verdict.action,
            "severity": verdict.severity,
            "warn": verdict.warn,
            "exit_status": facts.exit_status,
            "ts_us": entry.ts_us,
            "day": day,
        }

    def read_class_or_page(self, unit: str, invocation: str) -> dict[str, Any] | None:
        """The class record, or None. An unreadable one is paged (naming the file) and re-raised."""
        try:
            return self.store.read_class(unit, invocation)
        except StoreRecordError:
            name = f"{unit}__{invocation}__class.json"
            self.commit_finding(
                EVENT_CLASS_UNREADABLE,
                unit,
                f"classrec-{invocation}",
                "CRITICAL",
                f"class record {name} unreadable; move it out of evidence/unit_health/<day>/",
            )
            raise

    def enqueue(self, payload: AlertPayload) -> None:
        if not self.env.alert(payload):
            raise _EnqueueFailed

    def process_entry(self, entry: FailureEntry) -> None:
        block = self.observation.blocks.get(entry.unit, {})
        owner = self.ownership_of(entry.unit, block)
        if owner is None:
            return
        if owner is Ownership.FOREIGN:
            self.scan.foreign.add(entry.unit)
            return
        unit, invocation = entry.unit, entry.invocation_id
        day = day_of_ns(entry.ts_us * 1000)
        body = self.read_class_or_page(unit, invocation)
        if body is None:
            record = self.class_body(entry, block, day, owner is Ownership.UNRESOLVED)
            self.store.write_class(day, unit, invocation, record)
            body = self.read_class_or_page(unit, invocation)
        if body is None:
            raise StoreRecordError("class_record_unreadable")
        day = str(body.get("day", day))
        self.scan.days.add(day)
        if not self.store.has_action(unit, invocation):
            unit_class = str(body.get("unit_class", "UNHEALABLE"))
            severity = str(body.get("severity", "CRITICAL"))
            detail = f"unit={unit} class={unit_class} result={entry.unit_result}"
            if body.get("warn"):
                detail += f" {body['warn']}"
            event, site = EVENT_UNIT_FAILED, _site(unit, invocation)
            self.enqueue(AlertPayload(severity, event, site, detail))
            action = {
                "schema": "unit_health_action/v1",
                "kind": "unit_failure",
                "unit": unit,
                "invocation_id": invocation,
                "event": event,
                "site": site,
                "severity": severity,
                "action": "ALERT",
                "enqueued_ns": self.env.now_ns(),
            }
            self.store.write_action(day, unit, invocation, action)
            self.scan.new_failures.append(NewFailure(unit, invocation, unit_class, severity))
        recent = self.scan.touched.setdefault(unit, [])
        if invocation not in recent:
            recent.append(invocation)

    def commit_finding(
        self,
        kind: str,
        unit: str,
        key: str,
        severity: str,
        detail: str,
        extra: Mapping[str, object] | None = None,
        *,
        page: bool = True,
    ) -> None:
        """One class record and one enqueued alert per ``(unit, key)``, ever.

        ``extra`` adds fields to the class record (``metrics``, ids). ``page=False`` records the
        finding without an alert or action: for a cause the failing stage already paged itself.
        """
        safe = safe_key(key)
        self.scan.days.add(self.today)
        self.store.write_class(
            self.today, unit, safe, self.finding_body(kind, unit, key, severity, extra)
        )
        if not page or self.store.has_action(unit, safe):
            return
        site = finding_site(kind, unit, key)
        self.enqueue(AlertPayload(severity, kind, site, detail))
        self.write_finding_action(unit, safe, kind, site, severity)
        self.scan.new_findings += 1

    def commit_cited_finding(
        self,
        kind: str,
        unit: str,
        key: str,
        severity: str,
        cite_event: str,
        cite_site: str,
        extra: Mapping[str, object] | None = None,
    ) -> None:
        """A class record whose action record cites an alert already delivered for the episode."""
        safe = safe_key(key)
        self.scan.days.add(self.today)
        self.store.write_class(
            self.today, unit, safe, self.finding_body(kind, unit, key, severity, extra)
        )
        if not self.store.has_action(unit, safe):
            self.write_finding_action(unit, safe, cite_event, cite_site, severity)

    def finding_body(
        self, kind: str, unit: str, key: str, severity: str, extra: Mapping[str, object] | None
    ) -> dict[str, Any]:
        return {
            **(extra or {}),
            "schema": "unit_health_class/v1",
            "kind": "finding",
            "finding": kind,
            "unit": unit,
            "key": key,
            "severity": severity,
            "day": self.today,
        }

    def write_finding_action(
        self, unit: str, safe: str, event: str, site: str, severity: str
    ) -> None:
        self.store.write_action(
            self.today,
            unit,
            safe,
            {
                "schema": "unit_health_action/v1",
                "kind": "finding",
                "unit": unit,
                "invocation_id": safe,
                "event": event,
                "site": site,
                "severity": severity,
                "action": "ALERT",
                "enqueued_ns": self.env.now_ns(),
            },
        )

    # ---- reconciliation (F2)

    def reconcile(self) -> None:
        for name in self.observation.failed_names:
            block = self.observation.blocks.get(name, {})
            owner = self.ownership_of(name, block)
            if owner is None:
                continue
            if owner is Ownership.FOREIGN:
                self.scan.foreign.add(name)
                continue
            self.scan.failed_owned += 1
            invocation = block.get("InvocationID", "")
            if not _INVOCATION_RE.fullmatch(invocation):
                self.blind(name, f"noinv-{self.today}")
                continue
            if self.read_class_or_page(name, invocation) is not None:
                continue
            found = self.env.journal.failures_for_invocation(invocation, timeout_s=self.allowance())
            matching = [e for e in found if e.unit == name and e.invocation_id == invocation]
            if not matching:
                self.blind(name, invocation)
                continue
            for entry in matching:
                self.check_budget()
                self.process_entry(entry)

    def blind(self, unit: str, key: str) -> None:
        """Page the blind unit once. The pass is UNKNOWN, but once the page is durably enqueued
        this unit no longer holds the cursor back from the others."""
        self.scan.blind.append(unit)
        # Its own key namespace: the real failure's class record, when the journal later shows
        # it, must not be shadowed by this finding.
        self.commit_finding(
            EVENT_JOURNAL_BLIND, unit, f"blind-{key}", "CRITICAL", f"unit={unit} journal_blind"
        )

    # ---- the pass body

    def run_scan(self, observation: UnitObservation) -> None:
        self.observation = observation
        batch = self.read_failures()
        self.scan.batch = batch
        self.check_budget()
        for key in batch.unparseable:
            self.commit_finding(
                EVENT_UNPARSEABLE, _HOST, key, "CRITICAL", f"journal entry {key} unparseable"
            )
        for entry in batch.entries:
            self.check_budget()
            self.process_entry(entry)
        self.reconcile()

    def emit_host_verdict(self, verdict: HostVerdict) -> None:
        """Hand ``verdict`` to the sink; a refusal is a reason, never a lost finding or a crash."""
        sink = self.env.host_verdict
        if sink is None:
            return
        try:
            sink(verdict)
        except Exception as exc:  # noqa: BLE001 - the finding and its page are committed after
            _LOG.error("host_verdict_sink_failed exception_type=%s", type(exc).__name__)
            if "host_verdict_sink_failed" not in self.scan.reasons:
                self.scan.reasons.append("host_verdict_sink_failed")

    def run_extras(self, observation: UnitObservation | None) -> None:
        env = self.env
        if env.fold_probe is not None:
            try:
                env.fold_probe()
            except FoldUnreadable as exc:
                self.scan.reasons.append("fold_unreadable")
                self.emit_host_verdict(
                    HostVerdict(
                        PRODUCER_STALE_DETECTOR, "FAIL", {"fold_reason": exc.reason}, self.now
                    )
                )
                self.commit_finding(
                    EVENT_FOLD_UNREADABLE,
                    _HOST,
                    f"fold_unreadable-{self.today}",
                    "CRITICAL",
                    f"fold_reason={exc.reason}",
                )
        if observation is not None and env.committed_dropins is not None:
            self.scan.drift = unit_config_drift(
                observation.blocks, env.committed_dropins, today=self.today
            )
            for finding in self.scan.drift:
                key = f"{finding.dropin}-{self.today}"
                self.commit_finding(
                    EVENT_CONFIG_DRIFT, finding.unit, key, finding.severity, finding.detail
                )
        if observation is not None:
            run_daemon_rules(self, observation)
            apply_watch(self, observation)

    def commit_state(self) -> None:
        batch = self.scan.batch
        if batch is None:
            return
        for unit in sorted(set(self.scan.touched) | set(self.scan.daemon_seen)):
            previous = self.store.read_seen(unit) or {}
            recent = [*previous.get("invocations", []), *self.scan.touched.get(unit, [])]
            deduped = list(dict.fromkeys(recent))[-RECENT_INVOCATIONS_KEPT:]
            self.store.write_seen(
                unit,
                {
                    **previous,
                    **self.scan.daemon_seen.get(unit, {}),
                    "schema": "unit_health_seen/v1",
                    "unit": unit,
                    "invocations": deduped,
                },
            )
        end = batch.end_cursor or (batch.entries[-1].cursor if batch.entries else None)
        if end is not None:
            self.store.write_cursor(end, self.now, None)
        elif self.store.read_cursor() is None:
            self.store.write_cursor(None, self.now, self.now // 1000)

    def sample_memory(self, observation: UnitObservation) -> None:
        meminfo = self.env.meminfo()
        if meminfo is None:
            return
        available, _total = meminfo
        watch = self.env.watch
        if watch is None:
            addback = addback_kib(observation.blocks, MEMORY_ADDBACK_UNITS)
        else:
            node, recorder = self.scan.resident_kib or (0, 0)
            addback = free_addback_kib(
                observation.blocks,
                addback_units(watch.deploy_dir),
                node_kib=node,
                recorder_kib=recorder,
            )
        self.store.append_memavail(self.env.now_ns(), available, available + addback)


def _snapshot(env: PassEnv, now_ns: int) -> tuple[UnitObservation | None, list[str]]:
    try:
        return parse_observation(env.read_snapshot(), now_ns), []
    except BusSnapshotError as exc:
        return None, [exc.code]
    except SnapshotUnusable as exc:
        return None, list(exc.reasons)
    except OSError:
        return None, ["bus_snapshot_error"]


def _scan_guarded(run: _Pass, observation: UnitObservation | None) -> None:
    scan = run.scan
    try:
        if observation is not None:
            run.run_scan(observation)
        run.run_extras(observation)
    except _Budget:
        scan.reasons.append("pass_budget")
        run.block()
    except JournalError as exc:
        scan.reasons.append(f"journal:{exc.reason}")
        run.block()
    except _EnqueueFailed:
        scan.reasons.append("alert_enqueue_failed")
        run.block()
    except StoreRecordError as exc:
        scan.reasons.append(exc.reason)
        run.block()
    except (OSError, KeyError):
        scan.reasons.append("store_error")
        run.block()


def _finish(env: PassEnv, run: _Pass, unknown: bool, label: str) -> None:
    """Heartbeat first, then the rollups. A failing write is a reason, never an exception."""
    scan = run.scan
    beat = heartbeat_body(env, not unknown, label)
    try:
        env.store.write_heartbeat(beat)
    except OSError:
        scan.reasons.append("heartbeat_write_failed")
    for day in rollup_days(env, run.today, scan.days):
        try:
            env.store.write_rollup(
                day,
                rollup_body(
                    env,
                    day,
                    own_day=day == run.today,
                    completed=not unknown,
                    streak=beat["passes_unknown_streak"],
                    foreign=scan.foreign,
                    not_deployed=scan.not_deployed,
                    cursor_reset=scan.cursor_reset,
                ),
            )
        except StoreRecordError as exc:
            scan.reasons.append(exc.reason)  # the unreadable file is left untouched
        except OSError:
            scan.reasons.append("rollup_write_failed")


def run_health_pass(env: PassEnv) -> PassResult:
    """One health pass. Reads systemd only through the bus snapshot, and reads it first."""
    started = env.monotonic()
    observation, reasons = _snapshot(env, env.now_ns())
    with env.store.lock() as held:
        if not held:
            return PassResult("LOCKED")
        run = _Pass(env, started)
        scan = run.scan
        scan.reasons.extend(reasons)
        scan.blocking = bool(reasons)
        _scan_guarded(run, observation)
        if scan.blind:
            scan.reasons.append("journal_blind")
        if not scan.blocking and observation is not None:
            try:
                run.commit_state()
            except OSError:
                scan.reasons.append("store_error")
        unknown = bool(scan.reasons)
        if not unknown and observation is not None:
            try:
                run.sample_memory(observation)
            except OSError:
                scan.reasons.append("store_error")
                unknown = True
        if unknown:
            label = "UNKNOWN"
        elif scan.new_failures or scan.new_findings or scan.failed_owned:
            label = "FINDINGS"
        else:
            label = "OK"
        _finish(env, run, unknown, label)
        if scan.reasons and label != "UNKNOWN":
            label = "UNKNOWN"
        return PassResult(
            label,
            tuple(scan.reasons),
            scan.failed_owned if observation is not None else None,
            tuple(scan.new_failures),
            tuple(sorted(scan.foreign)),
            tuple(scan.blind),
            scan.cursor_reset,
            scan.drift,
        )
