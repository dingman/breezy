"""AUT-1 alert-event catalogue (plan r12 section 3.16; event-string rules from r8 section 3.13).

The ``event`` handed to ``deliver_with_proof`` or ``AlertOutbox.offer`` is a bare token from the
closed tuple below (qualifiers go in the payload ``detail``), or ``CAPTURE_HEALED_<sha>`` /
``CAPTURE_HEAL_ALERT_ABANDONED_<sha>`` with ``<sha>`` 64 lowercase hex. Every event matches
``CAPTURE_EVENT_RE`` after the hex is upper-cased (for the check only), so it is safe inside the
outbox file name ``<ts_ns>_<event>.json``.

Events AUT-1 no longer raises (r12 section 3.16 "Removed"): the recorder watch and watchdog family,
``CAPTURE_WRITE_FAILED``, ``CAPTURE_BYTE_CAP`` and ``CAPTURE_PAYLOAD_COLLISION``.
"""

import re
from typing import Final

__all__ = [
    "ABANDONED_EVENT_PREFIX",
    "CAPTURE_ALERT_EVENTS",
    "CAPTURE_ALERT_SEVERITIES",
    "CAPTURE_EVENT_RE",
    "HEALED_EVENT_PREFIX",
    "abandoned_alert_event",
    "heal_alert_event",
    "is_capture_alert_event",
]

CAPTURE_EVENT_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Z0-9_]{1,96}$")
HEALED_EVENT_PREFIX: Final[str] = "CAPTURE_HEALED_"
ABANDONED_EVENT_PREFIX: Final[str] = "CAPTURE_HEAL_ALERT_ABANDONED_"
_SHA_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")

_CRITICAL: Final[str] = "CRITICAL"
_WARNING: Final[str] = "WARNING"

#: event -> severity, per section 3.16. The tuple below is derived from it, so they cannot drift.
CAPTURE_ALERT_SEVERITIES: Final[dict[str, str]] = {
    "CAPTURE_PUBLISH_FAILED": _CRITICAL,
    "CAPTURE_REFUSED": _CRITICAL,
    "CAPTURE_VENUE_SILENT": _WARNING,
    "NBP_CYCLE_MISSED": _CRITICAL,
    "CAPTURE_EPOCH_UNREADABLE": _CRITICAL,
    "CAPTURE_STREAM_TYPE_FLAT": _CRITICAL,
    "CAPTURE_WATCHDOG_EVIDENCE_GAP": _CRITICAL,
    "CAPTURE_JOIN_GAP": _CRITICAL,
    "CAPTURE_TAPE_INGEST": _CRITICAL,
    "CAPTURE_NBP_CENSUS": _CRITICAL,
    "CAPTURE_AUDIT_ERROR": _CRITICAL,
    "CAPTURE_REFUSAL_REFS_UNRESOLVED": _CRITICAL,
    "CAPTURE_SETTLEMENT_MISSING": _CRITICAL,
    "CAPTURE_AUDIT_STUCK_INCONCLUSIVE": _CRITICAL,
    "CAPTURE_LIVE_PROOF_STALE": _CRITICAL,
    "CAPTURE_AUDIT_DEADMAN": _CRITICAL,
    "CAPTURE_AUDIT_FILE_MISSING": _CRITICAL,
    "CAPTURE_SETTLEMENT_ERROR": _CRITICAL,
    "CAPTURE_DRILL_NOT_HEALED": _CRITICAL,
    "CAPTURE_DRILL_SKIPPED": _CRITICAL,
}
CAPTURE_ALERT_EVENTS: Final[tuple[str, ...]] = tuple(CAPTURE_ALERT_SEVERITIES)


def _checked_sha(observation_sha256: object) -> str:
    if not isinstance(observation_sha256, str) or _SHA_RE.match(observation_sha256) is None:
        raise ValueError("observation_sha256 must be 64 lowercase hex characters")
    return observation_sha256


def heal_alert_event(observation_sha256: str) -> str:
    """``CAPTURE_HEALED_<sha>`` (79 characters); the heal's sha rides in ``event`` (R-11)."""
    return HEALED_EVENT_PREFIX + _checked_sha(observation_sha256)


def abandoned_alert_event(observation_sha256: str) -> str:
    """``CAPTURE_HEAL_ALERT_ABANDONED_<sha>`` (93 characters), per heal (r8 X1)."""
    return ABANDONED_EVENT_PREFIX + _checked_sha(observation_sha256)


def is_capture_alert_event(event: str) -> bool:
    if event in CAPTURE_ALERT_SEVERITIES:
        return True
    for prefix in (HEALED_EVENT_PREFIX, ABANDONED_EVENT_PREFIX):
        if event.startswith(prefix):
            return _SHA_RE.match(event[len(prefix) :]) is not None
    return False
