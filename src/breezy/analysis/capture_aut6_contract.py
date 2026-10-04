"""AUT-1 WP5 stage 3a: the AUT-6 key shapes AUT-1 reads (design r3 D11; S3-R9, S3-R30, S3-R44).

One module owns the name shapes of the delivery evidence AUT-6 writes, so the audit's legs, the heal
duty and the live proof read the same patterns:

* the notifier marker ``<unit>__<32-hex invocation>.delivered.json``;
* the NBP missed-cycle marker ``NBP_CYCLE_MISSED__<cycle_ns>.delivered.json`` (the decimal cycle
  instant; the notifier shape cannot match it, which left leg N failing closed, F10);
* the per-attempt delivery record ``<ts_ns>_<writer>_d.json`` of schema ``alert_delivery/v1``.

``read_notifier_proofs`` (extracted from the inputs module, which imports it) reads both marker
shapes; ``delivered_events`` reads the delivery records. Both follow the F12 single-read pattern:
``list_names``, then one ``ReadPolicy.REPO`` read per name, and anything unreadable proves no
delivery, so a caller fails closed toward a re-send. This module imports only ``capture_audit_io``
and ``single_read``, NEVER ``capture_audit_inputs`` (S3-R30), and nothing that loads Nautilus.
"""

import datetime as dt
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from breezy.analysis.capture_audit_io import list_names, read_file
from breezy.persistence.autonomy.single_read import ReadPolicy, SingleReadRefused

__all__ = [
    "ALERTS_REL",
    "DELIVERY_RECORD_NAME_RE",
    "DELIVERY_SCHEMA",
    "NBP_MISSED_MARKER_RE",
    "NBP_MISSED_PROOF_UNIT",
    "NOTIFIER_MARKER_RE",
    "NOTIFY_REL",
    "NotifierProof",
    "delivered_events",
    "delivered_events_by_day",
    "read_notifier_proofs",
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
#: The ``unit`` a missed-cycle marker is filed under: the proof of ``NBP_CYCLE_MISSED__<cycle_ns>``
#: carries the cycle instant in the ``invocation_id`` field.
NBP_MISSED_PROOF_UNIT: Final[str] = "NBP_CYCLE_MISSED"
#: ``evidence/alerts/<date>/`` below the data root: AUT-6's per-attempt delivery records.
ALERTS_REL: Final[tuple[str, ...]] = ("evidence", "alerts")
#: ``evidence/alerts/notify/<date>/``: AUT-6's per-kill notifier markers.
NOTIFY_REL: Final[tuple[str, ...]] = ("evidence", "alerts", "notify")


@dataclass(frozen=True, slots=True)
class NotifierProof:
    """AUT-6's ``evidence/alerts/notify/<date>/<unit>__<InvocationID>.delivered.json`` marker.

    Defined here, and re-exported by ``capture_audit_input_types``, so the live-proof unit can read
    a marker without importing the input types (their closure loads Nautilus, about 260 MiB, past
    that unit's ``MemoryMax=256M``)."""

    unit: str
    invocation_id: str
    delivered: bool
    date: str


def _body(data_root: Path, rel: tuple[str, ...], name: str) -> object:
    """The parsed JSON of one record, or ``None`` when it is unreadable (proves nothing)."""
    try:
        return json.loads(read_file(data_root, rel, name, ReadPolicy.REPO) or b"")
    except (SingleReadRefused, OSError, ValueError):
        return None


def _delivered(body: object) -> bool:
    return isinstance(body, dict) and body.get("delivered") is True


def _names(data_root: Path, rel: tuple[str, ...]) -> list[str]:
    try:
        return list_names(data_root, rel)
    except (SingleReadRefused, OSError):
        return []  # an unreadable directory proves no delivery


def read_notifier_proofs(data_root: Path, day: dt.date) -> tuple[NotifierProof, ...]:
    """Every notifier marker of ``day`` and the day after, in either shape, sorted. A marker that
    is unreadable, or whose ``delivered`` is not ``true``, is a proof of no delivery."""
    found: list[NotifierProof] = []
    for offset in (0, 1):
        stamp = (day + dt.timedelta(days=offset)).isoformat()
        rel = (*NOTIFY_REL, stamp)
        for name in _names(data_root, rel):
            unit_match = NOTIFIER_MARKER_RE.fullmatch(name)
            if unit_match is not None:
                unit, key = unit_match["unit"], unit_match["inv"]
            elif (nbp_match := NBP_MISSED_MARKER_RE.fullmatch(name)) is not None:
                unit, key = NBP_MISSED_PROOF_UNIT, nbp_match["cycle_ns"]
            else:
                continue
            found.append(NotifierProof(unit, key, _delivered(_body(data_root, rel, name)), stamp))
    return tuple(sorted(found, key=lambda p: (p.date, p.unit, p.invocation_id)))


def delivered_events_by_day(
    data_root: Path, first: dt.date, last: dt.date
) -> dict[dt.date, frozenset[str]]:
    """The events with a ``delivered`` record under ``evidence/alerts/<date>/``, per date, for the
    dates ``first`` to ``last`` inclusive; a missing or unreadable record is not delivered. One
    read of the ledger serves any number of per-window questions."""
    by_day: dict[dt.date, frozenset[str]] = {}
    day = first
    while day <= last:
        rel = (*ALERTS_REL, day.isoformat())
        events: set[str] = set()
        for name in _names(data_root, rel):
            if DELIVERY_RECORD_NAME_RE.fullmatch(name) is None:
                continue
            body = _body(data_root, rel, name)
            if not (isinstance(body, dict) and body.get("schema") == DELIVERY_SCHEMA):
                continue
            event = body.get("event")
            if _delivered(body) and isinstance(event, str) and event:
                events.add(event)
        by_day[day] = frozenset(events)
        day += dt.timedelta(days=1)
    return by_day


def delivered_events(data_root: Path, first: dt.date, last: dt.date) -> frozenset[str]:
    """The events with a ``delivered`` record under ``evidence/alerts/<date>/`` for the dates
    ``first`` to ``last`` inclusive; a missing or unreadable record is not delivered."""
    return frozenset().union(*delivered_events_by_day(data_root, first, last).values())
