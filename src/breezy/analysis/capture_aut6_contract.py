"""AUT-1 WP5 stage 3a: the AUT-6 key shapes AUT-1 reads (design r3 D11; S3-R9, S3-R30, S3-R44).

One module owns the name shapes of the delivery evidence AUT-6 writes, so the audit's legs, the heal
duty and the live proof read the same patterns:

* the notifier marker ``<unit>__<32-hex invocation>.delivered.json``;
* the NBP missed-cycle marker ``NBP_CYCLE_MISSED__<cycle_ns>.delivered.json`` (the decimal cycle
  instant; the notifier shape cannot match it, which left leg N failing closed, F10);
* the per-attempt delivery record ``<ts_ns>_<writer>_d.json`` of schema ``alert_delivery/v1``.

3a holds only the constants. Stage 3 stream S2 adds ``read_notifier_proofs`` (extracted from the
inputs module) and fills ``delivered_events``. This module imports only ``capture_audit_io``,
``single_read`` and the input types, NEVER ``capture_audit_inputs`` (S3-R30).
"""

import datetime as dt
import re
from pathlib import Path
from typing import Final

__all__ = [
    "DELIVERY_RECORD_NAME_RE",
    "DELIVERY_SCHEMA",
    "NBP_MISSED_MARKER_RE",
    "NOTIFIER_MARKER_RE",
    "delivered_events",
]

DELIVERY_SCHEMA: Final[str] = "alert_delivery/v1"
NOTIFIER_MARKER_PATTERN: Final[str] = r"\A(?P<unit>.+)__(?P<inv>[0-9a-f]{32})\.delivered\.json\Z"
NBP_MISSED_MARKER_PATTERN: Final[str] = (
    r"\ANBP_CYCLE_MISSED__(?P<cycle_ns>\d{1,20})\.delivered\.json\Z"
)
DELIVERY_RECORD_NAME_PATTERN: Final[str] = (
    r"\A(?P<ts_ns>\d{1,20})_(?P<writer>[a-z0-9_]{1,64})_d\.json\Z"
)
NOTIFIER_MARKER_RE: Final[re.Pattern[str]] = re.compile(NOTIFIER_MARKER_PATTERN)
NBP_MISSED_MARKER_RE: Final[re.Pattern[str]] = re.compile(NBP_MISSED_MARKER_PATTERN)
DELIVERY_RECORD_NAME_RE: Final[re.Pattern[str]] = re.compile(DELIVERY_RECORD_NAME_PATTERN)


def delivered_events(data_root: Path, first: dt.date, last: dt.date) -> frozenset[str]:
    """The events with a ``delivered`` record under ``evidence/alerts/<date>/`` for the dates
    ``first`` to ``last`` inclusive; a missing or unreadable record is not delivered (stage 3
    S2)."""
    raise NotImplementedError("stage 3 S2: the delivery-record reader")
