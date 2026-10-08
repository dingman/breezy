"""Seams and pure helpers of the AUT-6 unit health pass: host reads, alert enqueue, drift."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from breezy.registry.health_model import AlertPayload
from breezy.runtime.alert_outbox import AlertOutbox, DeliveryRecordWriter, default_alerts_root
from breezy.runtime.alert_proof import enqueue_alert
from breezy.runtime.unit_health_journal import run_bounded
from breezy.runtime.unit_health_model import WorktreesUnavailable, is_explained
from breezy.runtime.unit_health_store import HealthStore

HEALTH_WRITER: Final = "health"
#: Row #24: WARN until this date, CRITICAL from it (``detector_catalog``).
DRIFT_CRITICAL_FROM: Final = "2026-10-16"
EVENT_JOURNAL_BLIND: Final = "unit_health_journal_blind"
_REPO_ROOT: Final = "/home/jon/breezy"


@dataclass(frozen=True, slots=True)
class DriftFinding:
    unit: str
    dropin: str
    severity: str
    detail: str


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


def default_worktrees(timeout_s: float) -> tuple[str, ...]:
    """Paths of ``git worktree list --porcelain`` (read-only), bounded by ``timeout_s``.

    Raises ``WorktreesUnavailable`` when git cannot answer: ownership is then unknown, which the
    pass reports as UNKNOWN rather than reading a transient as foreign.
    """
    result = run_bounded(
        ["/usr/bin/git", "-C", _REPO_ROOT, "worktree", "list", "--porcelain"], timeout_s
    )
    if result.rc != 0 or result.timed_out or result.oversize:
        raise WorktreesUnavailable
    return tuple(
        line[len("worktree ") :].strip()
        for line in result.stdout.splitlines()
        if line.startswith("worktree ")
    )


def enqueue_health_alert(alerts_root: Path | None = None) -> Callable[[AlertPayload], bool]:
    """The health row's alert seam: queue to the outbox as writer ``health`` (X-4, no network)."""
    root = alerts_root if alerts_root is not None else default_alerts_root()
    outbox, records = AlertOutbox(root), DeliveryRecordWriter(root)

    def enqueue(payload: AlertPayload) -> bool:
        return enqueue_alert(payload, writer=HEALTH_WRITER, outbox=outbox, records=records)

    return enqueue


def unexplained_for_day(
    store: HealthStore, day: str, delivered: Callable[[str, str], bool]
) -> tuple[str, ...]:
    """``<unit>__<key>`` of every failure of ``day`` lacking a class and a proven action, plus
    every ``journal_blind`` finding (the journal cannot show that failure: never explained)."""
    names: list[str] = []
    for body in store.class_records_on(day):
        unit, invocation = str(body.get("unit")), str(body.get("invocation_id"))
        if not is_explained(body, store.read_action(unit, invocation), delivered):
            names.append(f"{unit}__{invocation}")
    for body in store.finding_records_on(day, EVENT_JOURNAL_BLIND):
        names.append(f"{body.get('unit')}__{body.get('key')}")
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
