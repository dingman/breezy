"""AUT-6 unit health pass core (plan r15 section 3.9; E-7e(f); F2, F4, F6, F10; WP3 S3).

One pass, in this order (the snapshot FIRST, so every failure it lists predates the journal read):

1. read the bus snapshot (the only systemd read) and validate it;
2. take the health lock; read the journal's unit-failed entries after the stored cursor;
3. for each in-scope entry, in journal order: classification record (``O_EXCL``, deduped on
   ``USER_INVOCATION_ID``), the alert (enqueued: the health row has no network), action record;
4. reconcile every in-scope failed unit of the snapshot against a classification record, with one
   targeted lookup by ``InvocationID`` when none exists; a unit the journal cannot show is
   ``journal_blind`` and makes the pass UNKNOWN;
5. only when every entry has both records: the ``seen`` files, then the cursor LAST.

Any systemd or journal error, the 90 s budget, an unreadable fold and an enqueue refusal make the
pass UNKNOWN: the streak grows, the heartbeat keeps its old ``ts_ns`` and nothing reads as zero
failures. The health unit changes nothing in systemd and reads none of the trading gates (X-6).
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final

from breezy.registry.health_model import AlertPayload
from breezy.runtime.alert_outbox import AlertOutbox, DeliveryRecordWriter, default_alerts_root
from breezy.runtime.alert_proof import enqueue_alert
from breezy.runtime.autonomy_sandbox.bus_handoff import (
    BusSnapshot,
    BusSnapshotError,
    read_bus_snapshot,
)
from breezy.runtime.unit_health_journal import (
    MIN_CALL_S,
    PER_CALL_CAP_S,
    JournalBatch,
    JournalError,
    JournalSource,
    SubprocessJournal,
    run_bounded,
)
from breezy.runtime.unit_health_model import (
    FOREIGN_UNIT_PREFIXES,
    HEALTH_PASS_BUDGET_S,
    FailureEntry,
    Ownership,
    UnitFacts,
    classify,
    facts_from_block,
    is_explained,
    is_transient,
    ownership,
)
from breezy.runtime.unit_health_obs import (
    HEALTH_ROW,
    SnapshotUnusable,
    UnitObservation,
    parse_observation,
)
from breezy.runtime.unit_health_store import (
    HealthStore,
    alerts_delivered,
    day_of_ns,
    day_start_s,
    previous_day,
)

__all__ = [
    "DRIFT_CRITICAL_FROM",
    "FOREIGN_UNIT_PREFIXES",
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
EVENT_JOURNAL_BLIND: Final = "unit_health_journal_blind"
EVENT_FOLD_UNREADABLE: Final = "fold_unreadable"
EVENT_CONFIG_DRIFT: Final = "unit_config_drift"
HEALTH_WRITER: Final = "health"
#: Row #24: WARN until this date, CRITICAL from it (``detector_catalog``).
DRIFT_CRITICAL_FROM: Final = "2026-10-16"
#: Units whose resident memory is added back to ``MemAvailable`` (section 3.10.1 item 6). S5 widens
#: this to the studies holders and own-lock units; the node lives in the supervisor's cgroup.
MEMORY_ADDBACK_UNITS: Final = frozenset(
    {
        "breezy-quote-tape-ingest.service",
        "breezy-quote-tape.service",
        "breezy-trade-supervisor.service",
    }
)
PRODUCER_STALE_DETECTOR: Final = "aut6.producer_stale"
_INVOCATION_RE: Final = re.compile(r"[0-9a-f]{32}")
_KEY_SAFE: Final = re.compile(r"[^A-Za-z0-9_.-]")
_HOST: Final = "_host"
_WORKTREE_TIMEOUT_S: Final = 3.0
_REPO_ROOT: Final = "/home/jon/breezy"
_US: Final = 1_000_000


class FoldUnreadable(Exception):
    """The fold could not be read (F4); ``reason`` is ``unreadable`` or ``empty``."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class HostVerdict:
    """A ``#26`` FAIL for the ``_host`` subject; S6 makes it a C4 verdict (the pin lands last)."""

    detector: str
    outcome: str
    metrics: Mapping[str, str]
    ts_ns: int


@dataclass(frozen=True, slots=True)
class DriftFinding:
    unit: str
    dropin: str
    severity: str
    detail: str


@dataclass(frozen=True, slots=True)
class NewFailure:
    unit: str
    invocation_id: str
    unit_class: str
    severity: str


@dataclass(frozen=True, slots=True)
class PassResult:
    pass_result: str  # OK | FINDINGS | UNKNOWN | LOCKED
    unknown_reasons: tuple[str, ...] = ()
    failed_units: int | None = None
    new_failures: tuple[NewFailure, ...] = ()
    foreign_failed: tuple[str, ...] = ()
    journal_blind: tuple[str, ...] = ()
    cursor_reset: bool = False
    drift: tuple[DriftFinding, ...] = ()


def read_meminfo() -> tuple[int, int] | None:
    """``(MemAvailable, MemTotal)`` in KiB from ``/proc/meminfo``, or ``None`` when unreadable."""
    try:
        text = Path("/proc/meminfo").read_text(encoding="ascii")
    except OSError:
        return None
    values = {k: v.split()[0] for k, _, v in (ln.partition(":") for ln in text.splitlines()) if v}
    try:
        return int(values["MemAvailable"]), int(values["MemTotal"])
    except (KeyError, ValueError):
        return None


def default_worktrees() -> tuple[str, ...]:
    """Paths of ``git worktree list --porcelain`` (read-only); ``()`` when git cannot answer."""
    result = run_bounded(
        ["/usr/bin/git", "-C", _REPO_ROOT, "worktree", "list", "--porcelain"], _WORKTREE_TIMEOUT_S
    )
    if result.rc != 0 or result.timed_out or result.oversize:
        return ()
    return tuple(
        line[len("worktree ") :].strip()
        for line in result.stdout.splitlines()
        if line.startswith("worktree ")
    )


@dataclass
class PassEnv:
    store: HealthStore
    read_snapshot: Callable[[], BusSnapshot]
    journal: JournalSource
    alert: Callable[[AlertPayload], bool]
    delivered: Callable[[str, str], bool]
    now_ns: Callable[[], int] = time.time_ns
    monotonic: Callable[[], float] = time.monotonic
    worktrees: Callable[[], Sequence[str]] = default_worktrees
    meminfo: Callable[[], tuple[int, int] | None] = read_meminfo
    fold_probe: Callable[[], None] | None = None
    host_verdict: Callable[[HostVerdict], None] | None = None
    #: ``None`` skips the drift check (no committed baseline was readable): inconclusive.
    committed_dropins: Mapping[str, frozenset[str]] | None = None
    invocation_id: str = ""


# --------------------------------------------------------------------------- production wiring


def enqueue_health_alert(alerts_root: Path | None = None) -> Callable[[AlertPayload], bool]:
    """The health row's alert seam: queue to the outbox as writer ``health`` (X-4, no network)."""
    root = alerts_root if alerts_root is not None else default_alerts_root()
    outbox, records = AlertOutbox(root), DeliveryRecordWriter(root)

    def enqueue(payload: AlertPayload) -> bool:
        return enqueue_alert(payload, writer=HEALTH_WRITER, outbox=outbox, records=records)

    return enqueue


def production_env(
    *, environ: Mapping[str, str] | None = None, data_root: Path | None = None
) -> PassEnv:
    """The real wiring: bus snapshot, ``journalctl``, outbox enqueue. Touches nothing until run."""
    env_map: Mapping[str, str] = os.environ if environ is None else environ
    root = data_root if data_root is not None else Path.home() / ".local" / "share" / "breezy"
    alerts = root / "evidence" / "alerts"
    return PassEnv(
        store=HealthStore(root / "evidence" / "unit_health"),
        read_snapshot=lambda: read_bus_snapshot(HEALTH_ROW, environ=env_map),
        journal=SubprocessJournal(),
        alert=enqueue_health_alert(alerts),
        delivered=alerts_delivered(alerts),
        invocation_id=env_map.get("INVOCATION_ID", ""),
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


# --------------------------------------------------------------------------- explained, drift


def unexplained_for_day(
    store: HealthStore, day: str, delivered: Callable[[str, str], bool]
) -> tuple[str, ...]:
    """``<unit>__<invocation>`` of every failure of ``day`` lacking a class and a proven action."""
    names: list[str] = []
    for body in store.class_records_on(day):
        unit, invocation = str(body.get("unit")), str(body.get("invocation_id"))
        if not is_explained(body, store.read_action(unit, invocation), delivered):
            names.append(f"{unit}__{invocation}")
    return tuple(sorted(names))


def unit_config_drift(
    blocks: Mapping[str, Mapping[str, str]],
    committed: Mapping[str, frozenset[str]],
    *,
    today: str,
    critical_from: str = DRIFT_CRITICAL_FROM,
) -> tuple[DriftFinding, ...]:
    """Drop-ins in a unit's ``DropInPaths`` that have no committed copy (row #24)."""
    severity = "CRITICAL" if today >= critical_from else "WARNING"
    found: list[DriftFinding] = []
    for unit in sorted(blocks):
        known = committed.get(unit, frozenset())
        for path in blocks[unit].get("DropInPaths", "").split():
            name = path.rsplit("/", 1)[-1]
            if name not in known:
                found.append(
                    DriftFinding(unit, name, severity, f"unit={unit} dropin={name} uncommitted")
                )
    return tuple(found)


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
    failed_owned: int = 0
    batch: JournalBatch | None = None
    cursor_reset: bool = False
    drift: tuple[DriftFinding, ...] = ()
    reasons: list[str] = field(default_factory=list)
    blocking: bool = False


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

    # ---- scope

    def ownership_of(self, unit: str, block: Mapping[str, str]) -> Ownership:
        paths: tuple[str, ...] = ()
        if unit.startswith("run-"):
            if self._worktrees is None:
                self._worktrees = tuple(self.env.worktrees())
            paths = self._worktrees
        return ownership(unit, block, paths)

    # ---- journal

    def read_failures(self) -> JournalBatch:
        state = self.store.read_cursor()
        journal = self.env.journal
        if state is not None:
            try:
                return journal.failures(
                    after_cursor=state.cursor,
                    since_s=None if state.cursor else (state.since_us or 0) // _US,
                    timeout_s=self.allowance(),
                )
            except JournalError:
                if state.cursor is None:
                    raise
        latest = self.store.latest_rollup_day() or self.today
        batch = journal.failures(
            after_cursor=None, since_s=day_start_s(latest), timeout_s=self.allowance()
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

    def class_body(self, entry: FailureEntry, block: Mapping[str, str], day: str) -> dict[str, Any]:
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

    def enqueue(self, payload: AlertPayload) -> None:
        if not self.env.alert(payload):
            raise _EnqueueFailed

    def process_entry(self, entry: FailureEntry) -> None:
        block = self.observation.blocks.get(entry.unit, {})
        if self.ownership_of(entry.unit, block) is Ownership.FOREIGN:
            self.scan.foreign.add(entry.unit)
            return
        unit, invocation = entry.unit, entry.invocation_id
        day = day_of_ns(entry.ts_us * 1000)
        body = self.store.read_class(unit, invocation)
        if body is None:
            self.store.write_class(day, unit, invocation, self.class_body(entry, block, day))
            body = self.store.read_class(unit, invocation)
        if body is None:
            raise _EnqueueFailed
        if not self.store.has_action(unit, invocation):
            unit_class, severity = str(body["unit_class"]), str(body["severity"])
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
            self.store.write_action(str(body.get("day", day)), unit, invocation, action)
            self.scan.new_failures.append(NewFailure(unit, invocation, unit_class, severity))
        recent = self.scan.touched.setdefault(unit, [])
        if invocation not in recent:
            recent.append(invocation)

    def commit_finding(self, kind: str, unit: str, key: str, severity: str, detail: str) -> None:
        """One class record and one enqueued alert per ``(unit, key)``, ever."""
        safe = _KEY_SAFE.sub("_", key)
        self.store.write_class(
            self.today,
            unit,
            safe,
            {
                "schema": "unit_health_class/v1",
                "kind": "finding",
                "finding": kind,
                "unit": unit,
                "key": key,
                "severity": severity,
                "day": self.today,
            },
        )
        if self.store.has_action(unit, safe):
            return
        site = f"{kind}:{unit}:{safe}"
        self.enqueue(AlertPayload(severity, kind, site, detail))
        self.store.write_action(
            self.today,
            unit,
            safe,
            {
                "schema": "unit_health_action/v1",
                "kind": "finding",
                "unit": unit,
                "invocation_id": safe,
                "event": kind,
                "site": site,
                "severity": severity,
                "action": "ALERT",
                "enqueued_ns": self.env.now_ns(),
            },
        )
        self.scan.new_findings += 1

    # ---- reconciliation (F2)

    def reconcile(self) -> None:
        for name in self.observation.failed_names:
            block = self.observation.blocks.get(name, {})
            if self.ownership_of(name, block) is Ownership.FOREIGN:
                self.scan.foreign.add(name)
                continue
            self.scan.failed_owned += 1
            invocation = block.get("InvocationID", "")
            if not _INVOCATION_RE.fullmatch(invocation):
                self.blind(name, f"noinv-{self.today}")
                continue
            if self.store.read_class(name, invocation) is not None:
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
        self.scan.blind.append(unit)
        self.scan.blocking = True
        self.commit_finding(
            EVENT_JOURNAL_BLIND, unit, key, "CRITICAL", f"unit={unit} journal_blind"
        )

    # ---- the pass body

    def run_scan(self, observation: UnitObservation) -> None:
        self.observation = observation
        batch = self.read_failures()
        self.scan.batch = batch
        self.check_budget()
        for entry in batch.entries:
            self.check_budget()
            self.process_entry(entry)
        self.reconcile()

    def run_extras(self, observation: UnitObservation | None) -> None:
        env = self.env
        if env.fold_probe is not None:
            try:
                env.fold_probe()
            except FoldUnreadable as exc:
                self.scan.reasons.append("fold_unreadable")
                if env.host_verdict is not None:
                    env.host_verdict(
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

    def commit_state(self, since_us: int) -> None:
        batch = self.scan.batch
        if batch is None:
            return
        for unit, invocations in sorted(self.scan.touched.items()):
            previous = self.store.read_seen(unit) or {}
            recent = [*previous.get("invocations", []), *invocations]
            deduped = list(dict.fromkeys(recent))[-32:]
            self.store.write_seen(
                unit, {"schema": "unit_health_seen/v1", "unit": unit, "invocations": deduped}
            )
        end = batch.end_cursor or (batch.entries[-1].cursor if batch.entries else None)
        if end is not None:
            self.store.write_cursor(end, self.now, None)
        elif self.store.read_cursor() is None:
            self.store.write_cursor(None, self.now, since_us)

    def sample_memory(self, observation: UnitObservation) -> None:
        meminfo = self.env.meminfo()
        if meminfo is None:
            return
        available, _total = meminfo
        addback = 0
        for unit in MEMORY_ADDBACK_UNITS:
            current = observation.blocks.get(unit, {}).get("MemoryCurrent", "")
            if current.isdigit():
                addback += int(current) // 1024
        self.store.append_memavail(self.env.now_ns(), available, available + addback)


def _heartbeat(env: PassEnv, store: HealthStore, completed: bool, result: str) -> dict[str, Any]:
    previous = store.read_heartbeat() or {}
    end = env.now_ns()
    old_ts = previous.get("ts_ns")
    old_streak = previous.get("passes_unknown_streak")
    streak = 0 if completed else (old_streak if isinstance(old_streak, int) else 0) + 1
    ts_ns = end if completed else (old_ts if isinstance(old_ts, int) else 0)
    return {
        "schema": "health_heartbeat/v1",
        "ts_ns": ts_ns,
        "last_attempt_ns": end,
        "invocation_id": env.invocation_id,
        "pass_result": result,
        "passes_unknown_streak": streak,
    }


def _rollup(env: PassEnv, day: str, completed: bool, streak: int, scan: _Scan) -> dict[str, Any]:
    previous = env.store.read_rollup(day) or {}
    names = unexplained_for_day(env.store, day, env.delivered)
    foreign = sorted({*previous.get("foreign_failed", []), *scan.foreign})
    return {
        "schema": "unit_health_day/v1",
        "day": day,
        "unexplained_failed_units": {"count": len(names), "names": list(names)},
        "foreign_failed": foreign,
        "passes_completed": int(previous.get("passes_completed", 0)) + int(completed),
        "passes_unknown": int(previous.get("passes_unknown", 0)) + int(not completed),
        "max_passes_unknown_streak": max(int(previous.get("max_passes_unknown_streak", 0)), streak),
        "cursor_reset": bool(previous.get("cursor_reset")) or scan.cursor_reset,
        "produced_at_ns": env.now_ns(),
    }


def _snapshot(env: PassEnv, now_ns: int) -> tuple[UnitObservation | None, list[str]]:
    try:
        return parse_observation(env.read_snapshot(), now_ns), []
    except BusSnapshotError as exc:
        return None, [exc.code]
    except SnapshotUnusable as exc:
        return None, list(exc.reasons)
    except OSError:
        return None, ["bus_snapshot_error"]


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
        try:
            if observation is not None:
                run.run_scan(observation)
            run.run_extras(observation)
        except _Budget:
            scan.reasons.append("pass_budget")
            scan.blocking = True
        except JournalError as exc:
            scan.reasons.append(f"journal:{exc.reason}")
            scan.blocking = True
        except _EnqueueFailed:
            scan.reasons.append("alert_enqueue_failed")
            scan.blocking = True
        if scan.blind:
            scan.reasons.append("journal_blind")
        if not scan.blocking and observation is not None:
            run.commit_state(run.now // 1000)
        unknown = bool(scan.reasons)
        completed = not unknown
        if completed and observation is not None:
            run.sample_memory(observation)
        if unknown:
            label = "UNKNOWN"
        elif scan.new_failures or scan.new_findings or scan.failed_owned:
            label = "FINDINGS"
        else:
            label = "OK"
        beat = _heartbeat(env, env.store, completed, label)
        env.store.write_heartbeat(beat)
        env.store.write_rollup(
            run.today, _rollup(env, run.today, completed, beat["passes_unknown_streak"], scan)
        )
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
