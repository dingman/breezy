"""AUT-1 WP5 stage 2b, W2: the marker collector sink (design S2-R2, S2-R10).

The marker GRAMMAR is not here: ``classify_line`` already yields the typed marker events
(``capture_node_log_markers``). ``MarkerParser`` is a ``LogSink`` that collects them per
``(instance_id, UTC day of the line)`` into ``LogMarkers``, switching boot on each
``InstanceIdLine`` (the same rule as ``BootReplay``). State is bounded: each marker kind keeps at
most ``MAX_MARKERS_PER_KIND`` lines per boot-day, and a line past the cap raises ``MarkerOverflow``,
which the scan reports as ``node_log_sink_failed`` (fail loud; a silently truncated list would let
a leg pass on partial evidence).

``CAPTURE_EPOCH_START`` format (S2-R10): ``CAPTURE_EPOCH_START family=<id> epoch_ns=<n>``. WP8's
``CaptureActor.on_start`` emits it; ``tests/unit/test_capture_audit_recon_legs.py`` round-trips the
line through the real classifier into ``LogMarkers.capture_epoch_start``.

Signatures are pinned by ``tests/unit/test_capture_audit_stubs.py``.
"""

import datetime as dt
from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from breezy.analysis.capture_audit_input_types import LogMarkers, LogSink, MarkerLine
from breezy.analysis.capture_node_log import (
    CaptureEpochStartLine,
    CaptureRefusedLine,
    FqVectorCompleteLine,
    InstanceIdLine,
    MarkerEvent,
    NbpCycleMissedLine,
    NbpPublishedLine,
    NodeLogEvent,
    OrderDeniedLine,
    OrderSubmittedLine,
)

__all__ = ["MAX_MARKERS_PER_KIND", "MarkerOverflow", "MarkerParser"]

#: Far above a healthy day (a handful of submits, three NBP cycles, one vector line per station and
#: cycle) and above a refusal storm worth auditing line by line.
MAX_MARKERS_PER_KIND: Final[int] = 50_000
_NS: Final[int] = 1_000_000_000
_BOOT_NONE: Final[str] = ""

#: The ``LogMarkers`` field each marker event type fills.
_FIELD_OF: Final[Mapping[type, str]] = {
    CaptureRefusedLine: "capture_refused",
    OrderSubmittedLine: "order_submitted",
    OrderDeniedLine: "order_denied",
    NbpPublishedLine: "nbp_published",
    FqVectorCompleteLine: "fq_vector_complete",
    NbpCycleMissedLine: "nbp_cycle_missed",
    CaptureEpochStartLine: "capture_epoch_start",
}


class MarkerOverflow(RuntimeError):
    """A boot-day held more than ``MAX_MARKERS_PER_KIND`` lines of one marker kind."""


def _day_of(ns: int) -> dt.date:
    return dt.datetime.fromtimestamp(ns // _NS, dt.UTC).date()


class MarkerParser(LogSink):
    """Collects marker events by boot and UTC day."""

    def __init__(self) -> None:
        self._found: dict[tuple[str, dt.date], dict[str, list[MarkerLine]]] = {}
        self._instance_id = _BOOT_NONE

    def feed(self, event: NodeLogEvent) -> None:
        if isinstance(event, InstanceIdLine):
            self._instance_id = event.instance_id
            return
        if not isinstance(event, MarkerEvent):
            return
        name = _FIELD_OF[type(event)]
        lines = self._found.setdefault((self._instance_id, _day_of(event.log_ts_ns)), {})
        bucket = lines.setdefault(name, [])
        if len(bucket) >= MAX_MARKERS_PER_KIND:
            raise MarkerOverflow(f"more than {MAX_MARKERS_PER_KIND} {name} lines in one boot-day")
        bucket.append(event)

    def markers(self) -> Mapping[tuple[str, dt.date], LogMarkers]:
        """The collected markers of each ``(instance_id, UTC day)`` seen."""
        return MappingProxyType(
            {
                key: LogMarkers(**{name: tuple(lines) for name, lines in fields.items()})
                for key, fields in self._found.items()
            }
        )
