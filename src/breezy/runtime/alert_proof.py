"""Delivery proof and the enqueue-only API (AUT-6 plan r15 §3.6.1-3.6.3, X-4).

The webhook POST goes through ``WebhookAlertSink._client`` directly. ``emit_alert`` and the tee
swallow branch failures (G25), so they are used only for the non-webhook branches. Proof is an
HTTP 2xx; a 3xx is not delivery. Only the exception type is ever logged, never its text.
"""

from __future__ import annotations

import logging
import ssl
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, cast

import httpx

from breezy.registry.health_model import AlertPayload, AlertSink
from breezy.runtime.alert_outbox import (
    AlertOutbox,
    DeliveryRecordWriter,
    validate_ids,
)
from breezy.runtime.health import (
    TeeAlertSink,
    WebhookAlertSink,
    emit_alert,
)

_LOG = logging.getLogger(__name__)

ALERT_DELIVERY_TIMEOUT_S: Final[int] = 5

StatusClass = Literal["2xx", "3xx", "4xx", "5xx", "transport", "not_configured", "outbox_overflow"]
AttemptKind = Literal["alert", "retry", "canary", "drain"]

#: Detector CRITICAL events plus the named failure modes. The WARNING ``CAPTURE_VENUE_SILENT`` is
#: absent.
PROOF_BEARING_EVENTS: Final[frozenset[str]] = frozenset(
    {
        "CAPTURE_PUBLISH_FAILED",
        "CAPTURE_REFUSED",
        "NBP_CYCLE_MISSED",
        "CAPTURE_EPOCH_UNREADABLE",
        "CAPTURE_STREAM_TYPE_FLAT",
        "CAPTURE_WATCHDOG_EVIDENCE_GAP",
        "CAPTURE_JOIN_GAP",
        "CAPTURE_TAPE_INGEST",
        "CAPTURE_NBP_CENSUS",
        "CAPTURE_AUDIT_ERROR",
        "CAPTURE_REFUSAL_REFS_UNRESOLVED",
        "CAPTURE_SETTLEMENT_MISSING",
        "CAPTURE_AUDIT_STUCK_INCONCLUSIVE",
        "CAPTURE_LIVE_PROOF_STALE",
        "CAPTURE_AUDIT_DEADMAN",
        "CAPTURE_AUDIT_FILE_MISSING",
        "CAPTURE_SETTLEMENT_ERROR",
        "CAPTURE_DRILL_NOT_HEALED",
        "CAPTURE_DRILL_SKIPPED",
        "autonomy_canary_undelivered",
        "bwrap_self_probe_failed",
    }
)


@dataclass
class DeliveryCounters:
    """Process-lifetime counts printed by a unit summary line."""

    journal_write_failures: int = 0
    outbox_write_failures: int = 0


#: Not thread-safe: plain ``+=`` on a module global. Every AUT-6 oneshot is single-threaded; the
#: node worker (WP1b) must hold its own lock or count per thread before it touches these.
COUNTERS = DeliveryCounters()


@dataclass(frozen=True, slots=True)
class DeliveryProof:
    """One attempt. ``delivered`` is true only for an HTTP 2xx."""

    delivered: bool
    status_class: StatusClass
    event: str
    ts_ns: int
    recorded: bool


class AlertNotDeliveredError(Exception):
    """The journaling webhook branch did not get an HTTP 2xx."""


@dataclass(frozen=True, slots=True)
class _Attempt:
    """The record fields that do not change between the paths of one attempt."""

    payload: AlertPayload
    writer: str
    attempt_kind: str
    drill: bool

    def record(
        self,
        records: DeliveryRecordWriter,
        *,
        ts_ns: int,
        status: StatusClass,
        entry: str = "",
        outbox_write_failed: bool = False,
    ) -> DeliveryProof:
        """Write the record; a failure is counted and logged, and never blocks delivery."""
        used, recorded = ts_ns, True
        try:
            path = records.write(
                event=self.payload.event,
                ts_ns=ts_ns,
                writer=self.writer,
                delivered=status == "2xx",
                status_class=status,
                severity=self.payload.severity,
                attempt_kind=self.attempt_kind,
                drill=self.drill,
                site=self.payload.site,
                outbox_entry=entry,
                outbox_write_failed=outbox_write_failed,
            )
        except OSError:
            COUNTERS.journal_write_failures += 1
            _LOG.error("alert_delivery_journal_unwritable exception_type=OSError")
            recorded = False
        else:
            head = path.name.split("_", 1)[0]
            used = int(head) if head.isdigit() else ts_ns
        return DeliveryProof(status == "2xx", status, self.payload.event, used, recorded)


def is_proof_bearing(payload: AlertPayload) -> bool:
    """Every CRITICAL, plus any severity whose event is a detector or named failure mode."""
    return payload.severity == "CRITICAL" or payload.event in PROOF_BEARING_EVENTS


def _branches(sink: object) -> tuple[object, ...]:
    if isinstance(sink, TeeAlertSink):
        return sink.sinks
    return (sink,)


def _emit_local(sink: object, payload: AlertPayload) -> None:
    for branch in _branches(sink):
        if not isinstance(branch, WebhookAlertSink):
            emit_alert(cast(AlertSink, branch), payload)


def _status_of(code: int) -> StatusClass:
    bucket = code // 100
    if bucket == 2:
        return "2xx"
    if bucket == 3:
        return "3xx"
    if bucket == 4:
        return "4xx"
    if bucket == 5:
        return "5xx"
    return "transport"


def _post(sink: object, payload: AlertPayload) -> StatusClass:
    """POST the webhook branch directly. 3xx is not delivery. Never log the exception text."""
    for branch in _branches(sink):
        if not isinstance(branch, WebhookAlertSink):
            continue
        try:
            response = branch._client.post(branch._url, json=payload.to_dict())
        except (httpx.HTTPError, ssl.SSLError, OSError) as exc:
            _LOG.error("alert delivery transport failure exception_type=%s", type(exc).__name__)
            return "transport"
        return _status_of(response.status_code)
    return "not_configured"


@dataclass(frozen=True, slots=True)
class _Queued:
    """Where a proof-bearing alert stands before its POST."""

    claimed: Path | None
    entry: str
    write_failed: bool


def _queue_and_claim(
    outbox: AlertOutbox, attempt: _Attempt, ts_ns: int
) -> _Queued | Literal["lost"]:
    """Write the entry (fsynced) and claim it. An OS error degrades to a direct attempt."""
    try:
        entry = outbox.write_entry(
            attempt.payload, writer=attempt.writer, drill=attempt.drill, ts_ns=ts_ns
        )
    except OSError:
        COUNTERS.outbox_write_failures += 1
        _LOG.error("alert_outbox_unwritable exception_type=OSError")
        return _Queued(None, "", True)
    try:
        claimed = outbox.claim(entry, attempt.writer)
    except OSError:
        # The entry is durable: leave it for a drainer. No direct send, and not a write failure.
        _LOG.error("alert_outbox_claim_failed exception_type=OSError")
        return "lost"
    if claimed is None:
        return "lost"
    return _Queued(claimed, entry.name, False)


def deliver_with_proof(
    sink: object,
    payload: AlertPayload,
    *,
    writer: str,
    records: DeliveryRecordWriter,
    attempt_kind: AttemptKind,
    drill: bool = False,
    now_ns: Callable[[], int] = time.time_ns,
    outbox: AlertOutbox | None = None,
    claimed: Path | None = None,
) -> DeliveryProof:
    """Record one attempt.

    With ``outbox`` set, a proof-bearing alert is written and claimed before the POST (E-1).
    ``claimed`` is a drainer's already-claimed entry: it is re-stamped, attempted, and removed only
    after a delivered record was written. The local log line is skipped for it: the originator
    already wrote one.
    """
    validate_ids(writer, attempt_kind)
    ts_ns = now_ns()
    attempt = _Attempt(payload, writer, attempt_kind, drill)
    if claimed is None:
        _emit_local(sink, payload)
    store = outbox if outbox is not None else AlertOutbox(records.root)
    queued = _Queued(claimed, claimed.name if claimed is not None else "", False)
    if claimed is None and outbox is not None and is_proof_bearing(payload):
        if outbox.refuses(payload.severity):
            return attempt.record(records, ts_ns=ts_ns, status="outbox_overflow")
        made = _queue_and_claim(outbox, attempt, ts_ns)
        if made == "lost":
            return DeliveryProof(False, "transport", payload.event, ts_ns, False)
        queued = made
    if queued.claimed is not None and not store.restamp(queued.claimed):
        return DeliveryProof(False, "transport", payload.event, ts_ns, False)
    status = _post(sink, payload)
    proof = attempt.record(
        records,
        ts_ns=ts_ns,
        status=status,
        entry=queued.entry,
        outbox_write_failed=queued.write_failed,
    )
    if proof.delivered and proof.recorded and queued.claimed is not None:
        store.complete(queued.claimed)
    return proof


def enqueue_alert(
    payload: AlertPayload,
    *,
    writer: str,
    outbox: AlertOutbox,
    records: DeliveryRecordWriter,
    drill: bool = False,
    now_ns: Callable[[], int] = time.time_ns,
) -> bool:
    """X-4: queue one alert and return. No HTTP, no sink, and no record on a successful enqueue.

    For ``network="none"`` rows. A drainer (redeliver, 60 s filename age) delivers it. Overflow and
    an unwritable outbox write one failed record and return ``False``.
    """
    validate_ids(writer, "alert")
    attempt = _Attempt(payload, writer, "alert", drill)
    if outbox.refuses(payload.severity):
        attempt.record(records, ts_ns=now_ns(), status="outbox_overflow")
        return False
    try:
        outbox.write_entry(payload, writer=writer, drill=drill, ts_ns=now_ns())
    except OSError:
        COUNTERS.outbox_write_failures += 1
        _LOG.error("alert_outbox_unwritable exception_type=OSError")
        attempt.record(records, ts_ns=now_ns(), status="transport", outbox_write_failed=True)
        return False
    return True
