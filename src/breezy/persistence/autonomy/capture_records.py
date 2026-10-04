"""AUT-1 capture record types (plan r12 section 3.4.1; ER-4).

Five ``@customdataclass`` types persisted by Nautilus's own ``StreamingFeatherWriter``. Encoding:
``str`` for decimals and nullable strings (``NULL_STR`` is null), ``int`` for nanoseconds and
counters (0 is null only where the plan says so), ``bool`` for ``drill`` / ``final`` /
``health_ok``, ``dict`` (an Arrow string of canonical JSON) for ``frame_body`` and
``written_by_type``. ``@customdataclass`` admits no ``Optional`` or ``Decimal`` field.

Rules this module must keep:

* No field is named ``instrument_id`` (ER-4): the native writer would route the type to a
  per-instrument file and silently drop it whenever ``cache.instrument(...)`` is None. The field
  is ``instrument``; the reader projects it back to C1's ``instrument_id``.
* No ``from __future__ import annotations``: the decorator reads real annotation objects, and
  stringified ones raise (WP0 finding).
* Class names are globally unique (the serializer registry is keyed by name).
* No custom record carries an absolute path, an env value, an account id or a raw venue order id.

Importing this module registers every schema, before any writer exists (V-1).
"""

from dataclasses import field
from typing import Any, Final, cast

from nautilus_trader.model.custom import customdataclass

__all__ = [
    "CAPTURE_RECORD_TYPES",
    "DECISION_KINDS",
    "DECISION_SCHEMA",
    "DETECTOR_SCHEMA",
    "DETECTOR_STATES",
    "FRAME_COPY_SCHEMA",
    "FRAME_KINDS",
    "HEARTBEAT_SCHEMA",
    "NULL_STR",
    "ORDER_EVENT_SCHEMA",
    "SOURCES",
    "CaptureHeartbeat",
    "DecisionRecord",
    "DetectorEvent",
    "FrameCopy",
    "OrderEventRecord",
    "make_record",
]

NULL_STR: Final[str] = ""


def make_record[R](cls: type[R], **fields: Any) -> R:
    """Construct a capture record. ``@customdataclass`` classes are untyped to mypy (their
    ``__init__`` is added at runtime, with ``ts_event`` / ``ts_init`` first), so every caller
    builds through this one typed boundary and keyword arguments only."""
    return cast(Any, cls)(**fields)  # type: ignore[no-any-return]


DECISION_SCHEMA: Final[str] = "capture_decision/v2"
FRAME_COPY_SCHEMA: Final[str] = "capture_frame_copy/v1"
ORDER_EVENT_SCHEMA: Final[str] = "capture_order_event/v1"
DETECTOR_SCHEMA: Final[str] = "capture_detector_event/v2"
HEARTBEAT_SCHEMA: Final[str] = "capture_heartbeat/v1"

DECISION_KINDS: Final[tuple[str, ...]] = (
    "Take",
    "Refuse",
    "NotExecutable",
    "NotDPlus1",
    "TrySubmit",
    "EntryVeto",
    "Exit",
)
SOURCES: Final[tuple[str, ...]] = ("live", "canary")
DETECTOR_STATES: Final[tuple[str, ...]] = ("AGREE", "DISAGREE", "UNKNOWN")
#: ``""`` is the Exit reference (no frame).
FRAME_KINDS: Final[tuple[str, ...]] = ("depth10", "quote", "")


def _empty_dict() -> dict[str, Any]:
    return {}


@customdataclass
class DecisionRecord:
    """One FQ decision. ``ts_event`` is ``eval_ns``; ``ts_init`` is the publish wall clock."""

    schema: str = NULL_STR
    decision_id: str = NULL_STR
    family_id: str = NULL_STR
    node_boot_id: str = NULL_STR
    build_sha: str = NULL_STR
    registry_seq: int = 0
    drill: bool = False
    source: str = NULL_STR
    kind: str = NULL_STR
    reason: str = NULL_STR
    eval_ns: int = 0
    eval_seq: int = 0
    wall_ns: int = 0
    station: str = NULL_STR
    climate_day: str = NULL_STR
    rung_id: str = NULL_STR
    side: str = NULL_STR
    instrument: str = NULL_STR
    ask_px: str = NULL_STR
    frame_kind: str = NULL_STR
    frame_ts_event: int = 0
    p_hat: str = NULL_STR
    p_hat_raw: str = NULL_STR
    p_lower: str = NULL_STR
    p_upper: str = NULL_STR
    ev_net: str = NULL_STR
    margin: str = NULL_STR
    forecast_station: str = NULL_STR
    forecast_cycle_ns: int = 0
    forecast_available_at_ns: int = 0
    artefact_sha256: str = NULL_STR
    manifest_sha256: str = NULL_STR


@customdataclass
class FrameCopy:
    """The Take-path copy of the triggering frame. ``ts_event`` is ``frame_ts_event``."""

    schema: str = NULL_STR
    decision_id: str = NULL_STR
    frame_kind: str = NULL_STR
    instrument: str = NULL_STR
    frame_ts_event: int = 0
    frame_body: dict = field(default_factory=_empty_dict)  # type: ignore[type-arg]


@customdataclass
class OrderEventRecord:
    """An order event class with no registered Arrow schema. ``ts_event`` is the event's own."""

    schema: str = NULL_STR
    decision_id: str = NULL_STR
    event_type: str = NULL_STR
    client_order_id: str = NULL_STR
    venue_order_id_sha256: str = NULL_STR
    reason: str = NULL_STR
    node_boot_id: str = NULL_STR
    drill: bool = False
    source: str = NULL_STR


@customdataclass
class DetectorEvent:
    """A detector transition. ``ts_event`` is the publish time."""

    schema: str = NULL_STR
    detector: str = NULL_STR
    observation_sha256: str = NULL_STR
    state: str = NULL_STR
    node_boot_id: str = NULL_STR
    drill: bool = False
    source: str = NULL_STR


@customdataclass
class CaptureHeartbeat:
    """The 60 s positive-control record. ``ts_event`` is the write time.

    ``written_by_type`` is a snapshot taken immediately BEFORE this heartbeat's own write (r11,
    GL1), so it excludes the heartbeat that carries it.
    """

    schema: str = NULL_STR
    node_boot_id: str = NULL_STR
    seq: int = 0
    final: bool = False
    records_written: int = 0
    written_by_type: dict = field(default_factory=_empty_dict)  # type: ignore[type-arg]
    write_failures: int = 0
    write_drops: int = 0
    health_ok: bool = False
    health_cause: str = NULL_STR


CAPTURE_RECORD_TYPES: Final[tuple[type, ...]] = (
    DecisionRecord,
    FrameCopy,
    OrderEventRecord,
    DetectorEvent,
    CaptureHeartbeat,
)
