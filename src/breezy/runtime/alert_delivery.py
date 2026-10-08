"""Public surface of the AUT-6 alert delivery layer (plan r15 §3.6).

The implementation is split into ``alert_outbox`` (durable storage, E-1 claim), ``alert_proof``
(delivery proof, enqueue-only API) and ``alert_drain`` (redeliver and dead-man draining). This
module re-exports them and holds the two production seams that wire them to the real sink:
``JournalingWebhookAlertSink`` and ``run_deadman_drain``.
"""

from __future__ import annotations

import httpx

from breezy.registry.health_model import AlertPayload
from breezy.runtime.alert_drain import (
    ALERT_OUTBOX_STALE_S,
    REDELIVER_MIN_AGE_S,
    DrainSummary,
    drain_outbox,
)
from breezy.runtime.alert_outbox import (
    ALERT_CLAIM_STALE_S,
    ALERT_OUTBOX_CRITICAL_RESERVED,
    ALERT_OUTBOX_MAX,
    AlertOutbox,
    DeliveryRecordWriter,
    default_alerts_root,
)
from breezy.runtime.alert_proof import (
    ALERT_DELIVERY_TIMEOUT_S,
    COUNTERS,
    PROOF_BEARING_EVENTS,
    AlertNotDeliveredError,
    AttemptKind,
    DeliveryCounters,
    DeliveryProof,
    StatusClass,
    deliver_with_proof,
    enqueue_alert,
    is_proof_bearing,
)
from breezy.runtime.health import WebhookAlertSink, resolve_alert_sink

__all__ = [
    "ALERT_CLAIM_STALE_S",
    "ALERT_DELIVERY_TIMEOUT_S",
    "ALERT_OUTBOX_CRITICAL_RESERVED",
    "ALERT_OUTBOX_MAX",
    "ALERT_OUTBOX_STALE_S",
    "COUNTERS",
    "PROOF_BEARING_EVENTS",
    "REDELIVER_MIN_AGE_S",
    "AlertNotDeliveredError",
    "AlertOutbox",
    "AttemptKind",
    "DeliveryCounters",
    "DeliveryProof",
    "DeliveryRecordWriter",
    "DrainSummary",
    "JournalingWebhookAlertSink",
    "StatusClass",
    "default_alerts_root",
    "deliver_with_proof",
    "drain_outbox",
    "enqueue_alert",
    "is_proof_bearing",
    "run_deadman_drain",
]


def run_deadman_drain() -> DrainSummary:
    """The one call AUT-5's dead-man makes: entries whose filename age is at least 300 s."""
    root = default_alerts_root()
    sink = resolve_alert_sink()
    try:
        return drain_outbox(
            drainer="deadman",
            outbox=AlertOutbox(root),
            sink=sink,
            records=DeliveryRecordWriter(root),
            min_age_s=ALERT_OUTBOX_STALE_S,
        )
    finally:
        closer = getattr(sink, "close", None)
        if callable(closer):
            closer()


def JournalingWebhookAlertSink(
    url: str,
    *,
    client: httpx.Client | None = None,
    writer: str = "legacy_runtime",
) -> WebhookAlertSink:
    """A real ``WebhookAlertSink`` whose ``emit`` records, queues and re-raises on non-2xx.

    It stays an exact ``WebhookAlertSink`` (the egress tests compare ``type(branch)``), so ``emit``
    is replaced on the instance. Construction does not touch disk. The writer id is
    ``legacy_<component>`` (X-2).
    """
    sink = WebhookAlertSink(url, client=client)

    def _emit(payload: AlertPayload) -> None:
        root = default_alerts_root()
        proof = deliver_with_proof(
            sink,
            payload,
            writer=writer,
            records=DeliveryRecordWriter(root),
            attempt_kind="alert",
            outbox=AlertOutbox(root),
        )
        if not proof.delivered:
            raise AlertNotDeliveredError(proof.status_class)

    setattr(sink, "emit", _emit)  # noqa: B010 - instance-level override of a method
    return sink
