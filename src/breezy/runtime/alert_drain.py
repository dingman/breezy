"""Outbox draining: claim, attempt once, record (AUT-6 plan r15 §3.6.3, E-1)."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from breezy.registry.health_model import AlertPayload
from breezy.runtime.alert_outbox import (
    NS,
    AlertOutbox,
    DeliveryRecordWriter,
    ts_ns_of,
    validate_ids,
)
from breezy.runtime.alert_proof import deliver_with_proof

REDELIVER_MIN_AGE_S: Final[int] = 60
ALERT_OUTBOX_STALE_S: Final[int] = 300
_ABANDON_AFTER_S: Final[int] = 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class DrainSummary:
    """What one ``drain_outbox`` pass did. ``abandoned`` names entries older than 24 h."""

    delivered: int
    attempted: int
    reclaims: int
    failures: int
    abandoned: tuple[str, ...]


def _is_older(path: Path, now_ns: int, age_s: int, *, strictly: bool) -> bool:
    ts_ns = ts_ns_of(path)
    if ts_ns is None:
        return False
    age_ns = now_ns - ts_ns
    return age_ns > age_s * NS if strictly else age_ns >= age_s * NS


def _load_entry(path: Path) -> tuple[AlertPayload, bool] | None:
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(body, dict):
        return None
    try:
        payload = AlertPayload(
            severity=str(body["severity"]),
            event=str(body["event"]),
            site=str(body["site"]),
            detail=str(body["detail"]),
        )
    except (KeyError, TypeError):
        return None
    return payload, bool(body.get("drill", False))


def _work_list(
    outbox: AlertOutbox, drainer: str, reclaimed: list[Path], clock: int, min_age_s: int
) -> list[tuple[Path, bool]]:
    """``(path, already_claimed)``. Reclaimed claims are always attempted; the rest by age."""
    work: list[tuple[Path, bool]] = [(path, True) for path in reclaimed]
    seen = set(reclaimed)
    own = outbox.root / "outbox" / "claimed" / drainer
    if own.is_dir():
        for path in sorted(own.glob("*.json")):
            if path not in seen and _is_older(path, clock, min_age_s, strictly=False):
                work.append((path, True))
    for path in sorted((outbox.root / "outbox").glob("*.json")):
        if _is_older(path, clock, min_age_s, strictly=False):
            work.append((path, False))
    return work


def drain_outbox(
    *,
    drainer: str,
    outbox: AlertOutbox,
    sink: object,
    records: DeliveryRecordWriter,
    min_age_s: int,
    budget_s: int = 40,
    monotonic: Callable[[], float] = time.monotonic,
    now_ns: Callable[[], int] = time.time_ns,
) -> DrainSummary:
    """Claim entries whose filename age is at least ``min_age_s`` and attempt each once.

    Stops taking new claims once ``budget_s`` has elapsed. An entry older than 24 h is still
    attempted and named in ``abandoned``. The record writer id is the drainer, not the originator.
    """
    validate_ids(drainer, "drain")
    started = monotonic()
    reclaimed = outbox.reclaim_stale(drainer)
    clock = now_ns()
    work = _work_list(outbox, drainer, reclaimed, clock, min_age_s)
    delivered = failures = 0
    abandoned: list[str] = []
    for path, already in work:
        if monotonic() - started >= budget_s:
            break
        claimed = path if already else outbox.claim(path, drainer)
        if claimed is None:
            continue
        if _is_older(claimed, clock, _ABANDON_AFTER_S, strictly=True):
            abandoned.append(claimed.name)
        loaded = _load_entry(claimed)
        if loaded is None:
            failures += 1
            continue
        payload, drill = loaded
        proof = deliver_with_proof(
            sink,
            payload,
            writer=drainer,
            records=records,
            attempt_kind="drain",
            drill=drill,
            now_ns=lambda: clock,
            outbox=outbox,
            claimed=claimed,
        )
        delivered += int(proof.delivered)
        failures += int(not proof.delivered)
    return DrainSummary(delivered, len(work), len(reclaimed), failures, tuple(abandoned))
