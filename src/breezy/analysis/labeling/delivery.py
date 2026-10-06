"""CRITICAL delivery, episode dedup and the delivery budget (AUT-2 r7 WP5, 3.2.1 and 3.7.3).

``deliver_or_fail`` wraps one injected delivery callable (the production binding is AUT-6's
``deliver_with_proof``, which writes the outbox entry first, ARCH 4.6): it runs in a worker thread
joined with ``AUT2_DELIVERY_DEADLINE_S`` and raises :class:`AlertDeliveryFailed` unless the callable
returns a delivered proof. A hung sink therefore never holds the run past its deadline; a late send
from the abandoned thread is at-least-once (U3).

``deliver_critical`` adds the P11/V7 dedup. The key is ``sha256(event | venue | subject |
episode_id)`` scoped to the UTC day by its directory; the journal file is created only after a
delivered proof, with ``EEXIST`` treated as success, so across two locks a key is delivered at least
once and never lost (L3). A repeat in the same day is suppressed and counted, and keeps its verdict
effect because no verdict is built here. Under ``measure_dry_run`` nothing is sent and nothing real
is written (V3).
"""

from __future__ import annotations

import hashlib
import os
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from breezy.analysis.labeling.constants import (
    AUT2_DELIVERY_DEADLINE_S,
    POST_READ_WRITE_RESERVE_S,
)
from breezy.analysis.labeling.skip_journal import utc_day, write_json_once
from breezy.persistence.autonomy.single_read import (
    SingleReadReason,
    SingleReadRefused,
    open_root,
    walk_dirs,
)

__all__ = [
    "DEDUP_DIR",
    "AlertDeliveryFailed",
    "DeliveryOutcome",
    "DeliveryProof",
    "DeliveryStatus",
    "critical_dedup_key",
    "deliver_critical",
    "deliver_or_fail",
    "episode_id",
    "is_duplicate",
    "max_deliveries_in_budget",
]

DEDUP_DIR: Final[tuple[str, ...]] = ("evidence", "aut2", "critical_dedup")
_DRY_RUN_DIR: Final = "measure_dry_run"
_HEX12: Final = 12


class AlertDeliveryFailed(Exception):
    """No delivered proof: a failure, a deadline expiry, or an undelivered result."""


@dataclass(frozen=True)
class DeliveryProof:
    delivered: bool
    status_class: str = "2xx"


class DeliveryStatus(StrEnum):
    DELIVERED = "DELIVERED"
    SUPPRESSED = "SUPPRESSED"
    FAILED = "FAILED"
    DEFERRED = "DEFERRED"
    DRY_RUN = "DRY_RUN"


@dataclass(frozen=True)
class DeliveryOutcome:
    status: DeliveryStatus
    key: str
    line: str | None = None


Deliver = Callable[[Mapping[str, Any]], DeliveryProof | None]


def deliver_or_fail(
    payload: Mapping[str, Any],
    *,
    deliver: Deliver,
    deadline_s: float = AUT2_DELIVERY_DEADLINE_S,
) -> DeliveryProof:
    """Deliver ``payload`` within ``deadline_s`` or raise ``AlertDeliveryFailed``."""
    box: dict[str, Any] = {}

    def _worker() -> None:
        try:
            box["proof"] = deliver(payload)
        except Exception as exc:  # noqa: BLE001 - every delivery failure is one refusal
            box["error"] = exc

    thread = threading.Thread(target=_worker, name="aut2-delivery", daemon=True)
    thread.start()
    thread.join(deadline_s)
    if thread.is_alive():
        raise AlertDeliveryFailed("the delivery deadline expired")
    if "error" in box:
        raise AlertDeliveryFailed("the delivery raised") from box["error"]
    proof = box.get("proof")
    if not isinstance(proof, DeliveryProof) or not proof.delivered:
        raise AlertDeliveryFailed("no delivered proof")
    return proof


def critical_dedup_key(event: str, venue: str, subject: str, episode: int) -> str:
    """``sha256(event | venue | subject | episode_id)``; ``subject`` is a slug, fill-key sha or
    family id, never an amount."""
    return hashlib.sha256("|".join((event, venue, subject, str(episode))).encode()).hexdigest()


def episode_id(observations: Sequence[tuple[int, bool]]) -> int | None:
    """The ``ts_ns`` of the first non-clear observation in the current unbroken run.

    ``observations`` are chronological ``(ts_ns, is_clear)`` pairs for one ``(event, venue,
    subject)``. A clearing observation (a MATCH, a PASS leg) ends the episode, so MISMATCH, MATCH,
    MISMATCH is two episodes. ``None`` when the newest observation is clear.
    """
    start: int | None = None
    for ts_ns, is_clear in sorted(observations):
        if is_clear:
            start = None
        elif start is None:
            start = ts_ns
    return start


def _dedup_parts(day: str, key: str) -> tuple[str, ...]:
    return (*DEDUP_DIR, day, f"{key}.json")


def is_duplicate(data_root: Path, day: str, key: str) -> bool:
    """Whether the dedup journal already holds ``key`` for ``day``."""
    rootfd = open_root(data_root)
    try:
        try:
            dirfd = walk_dirs(rootfd, (*DEDUP_DIR, day))
        except SingleReadRefused as exc:
            if exc.reason is SingleReadReason.NOT_FOUND:
                return False
            raise
        try:
            return f"{key}.json" in os.listdir(dirfd)
        finally:
            os.close(dirfd)
    finally:
        os.close(rootfd)


def _record_delivered(data_root: Path, day: str, key: str, event: str) -> None:
    try:
        write_json_once(
            data_root,
            _dedup_parts(day, key),
            {"schema": "aut2_critical_dedup/v1", "event": event, "key_sha12": key[:_HEX12]},
        )
    except SingleReadRefused as exc:
        # EEXIST: another writer, possibly under the other lock, already holds the proof
        if exc.reason is not SingleReadReason.EXISTS_DIFFERENT:
            raise


def max_deliveries_in_budget(post_read_budget_s: float) -> int:
    """How many deliveries fit after the write reserve: post-STOP ``(29 - 5) // 8 = 3``."""
    return max(0, int((post_read_budget_s - POST_READ_WRITE_RESERVE_S) // AUT2_DELIVERY_DEADLINE_S))


def deliver_critical(
    data_root: Path,
    *,
    event: str,
    venue: str,
    subject: str,
    episode: int,
    payload: Mapping[str, Any],
    deliver: Deliver,
    now_ns: int,
    deadline_s: float = AUT2_DELIVERY_DEADLINE_S,
    budget_remaining_s: float | None = None,
    dry_run_root: Path | None = None,
) -> DeliveryOutcome:
    """Deliver one CRITICAL once per episode per UTC day; never lose it, never repeat it.

    ``budget_remaining_s`` below the delivery deadline defers (the outbox keeps the entry).
    ``dry_run_root`` makes the call a measurement: nothing is sent, the real journal untouched.
    """
    key = critical_dedup_key(event, venue, subject, episode)
    day = utc_day(now_ns)
    if dry_run_root is not None:
        write_json_once(
            dry_run_root,
            (_DRY_RUN_DIR, f"{now_ns}_{key[:_HEX12]}.json"),
            {"delivered": False, "status_class": "measure_dry_run", "event": event},
        )
        return DeliveryOutcome(DeliveryStatus.DRY_RUN, key)
    if is_duplicate(data_root, day, key):
        line = f"AUT2 CRITICAL_SUPPRESSED event={event} key={key[:_HEX12]}"
        return DeliveryOutcome(DeliveryStatus.SUPPRESSED, key, line)
    if budget_remaining_s is not None and budget_remaining_s < deadline_s:
        return DeliveryOutcome(
            DeliveryStatus.DEFERRED, key, f"AUT2 DELIVERY_DEFERRED event={event}"
        )
    try:
        deliver_or_fail(payload, deliver=deliver, deadline_s=deadline_s)
    except AlertDeliveryFailed:
        return DeliveryOutcome(DeliveryStatus.FAILED, key, f"AUT2 DELIVERY_FAILED event={event}")
    _record_delivered(data_root, day, key, event)
    return DeliveryOutcome(DeliveryStatus.DELIVERED, key)
