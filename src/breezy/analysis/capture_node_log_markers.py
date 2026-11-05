"""AUT-1 node-log marker events (plan r8 section 3.10 fail-loud list; design S2-R2, S2-R10).

The seven marker lines the audit's legs read beyond ``SHADOW_DECISION``, ``OrderFilled``, the
instance id and the writer failures. Each is parsed here into a frozen typed event; a marker line
that does not parse is returned as an ``UnparseableLine`` by the caller, never dropped (r5 H11).

* ``CAPTURE_REFUSED reason=<r> order_ref=<ref>``: ``guarded_strategy._refuse_one``. The sibling
  ``CAPTURE_REFUSED_ALERT_UNDELIVERED`` is a different line and is not a marker.
* ``<--[EVT] OrderSubmitted(...)`` and ``<--[EVT] OrderDenied(...)``: the Nautilus event ``str``.
* ``NBM_NBP_PUBLISHED``: ``NbmQuantileActor`` once per published cycle.
* ``FQ_VECTOR_COMPLETE``: ``ForecastQuantileStateActor`` once per complete (station, cycle).
* ``NBP_CYCLE_MISSED cycle_ns=<n> now_ns=<n> model=<m> [(no alert_offer wired)]``: pinned from WP4
  ``nbm_quantile_actor._offer_missed_cycle_alerts``. The suffix is logged only when no alert offer
  is wired; the wired path offers the alert and logs nothing, so ``offered`` is False exactly when
  the suffix is present.
* ``CAPTURE_EPOCH_START family=<id> epoch_ns=<n>``: ``CaptureActor.on_start`` (WP8 emits it; the
  format is pinned here, S2-R10).

Non-writer, stdlib only.
"""

import datetime as dt
import re
from dataclasses import dataclass
from typing import Final

from breezy.analysis.capture_node_log_io import (
    CAUSE_BAD_FIELDS,
    UnparseableLine,
    unparseable,
)

__all__ = [
    "MARKER_CAPTURE_EPOCH_START",
    "MARKER_CAPTURE_REFUSED",
    "MARKER_FQ_VECTOR_COMPLETE",
    "MARKER_NBP_CYCLE_MISSED",
    "MARKER_NBP_PUBLISHED",
    "MARKER_ORDER_DENIED",
    "MARKER_ORDER_SUBMITTED",
    "MARKER_TOKEN_PATTERN",
    "MAX_MARKER_TEXT_CHARS",
    "CaptureEpochStartLine",
    "CaptureRefusedLine",
    "FqVectorCompleteLine",
    "MarkerEvent",
    "NbpCycleMissedLine",
    "NbpPublishedLine",
    "OrderDeniedLine",
    "OrderSubmittedLine",
    "classify_marker_message",
    "marker_name_for_token",
]

#: A free-text field (an ``OrderDenied`` reason) is stored capped, so the state stays bounded.
MAX_MARKER_TEXT_CHARS: Final[int] = 512

MARKER_CAPTURE_REFUSED: Final[str] = "CAPTURE_REFUSED"
MARKER_ORDER_SUBMITTED: Final[str] = "OrderSubmitted"
MARKER_ORDER_DENIED: Final[str] = "OrderDenied"
MARKER_NBP_PUBLISHED: Final[str] = "NBM_NBP_PUBLISHED"
MARKER_FQ_VECTOR_COMPLETE: Final[str] = "FQ_VECTOR_COMPLETE"
MARKER_NBP_CYCLE_MISSED: Final[str] = "NBP_CYCLE_MISSED"
MARKER_CAPTURE_EPOCH_START: Final[str] = "CAPTURE_EPOCH_START"

#: The bytes pattern the line classifier searches for (alternatives of its ``_MARKER_RE``). A bare
#: name is not followed by an identifier character, so ``CAPTURE_REFUSED_ALERT_UNDELIVERED`` and
#: ``NBM_NBP_PUBLISHED_X`` are other lines.
MARKER_TOKEN_PATTERN: Final[bytes] = (
    rb"CAPTURE_REFUSED(?![A-Za-z0-9_])|<--\[EVT\] OrderSubmitted\(|<--\[EVT\] OrderDenied\("
    rb"|NBM_NBP_PUBLISHED(?![A-Za-z0-9_])|FQ_VECTOR_COMPLETE(?![A-Za-z0-9_])"
    rb"|NBP_CYCLE_MISSED(?![A-Za-z0-9_])|CAPTURE_EPOCH_START(?![A-Za-z0-9_])"
)

_TOKEN_NAMES: Final[tuple[tuple[bytes, str], ...]] = (
    (b"CAPTURE_REFUSED", MARKER_CAPTURE_REFUSED),
    (b"<--[EVT] OrderSubmitted(", MARKER_ORDER_SUBMITTED),
    (b"<--[EVT] OrderDenied(", MARKER_ORDER_DENIED),
    (b"NBM_NBP_PUBLISHED", MARKER_NBP_PUBLISHED),
    (b"FQ_VECTOR_COMPLETE", MARKER_FQ_VECTOR_COMPLETE),
    (b"NBP_CYCLE_MISSED", MARKER_NBP_CYCLE_MISSED),
    (b"CAPTURE_EPOCH_START", MARKER_CAPTURE_EPOCH_START),
)

_ID = r"[0-9A-Za-z._:^-]+"
_INT = r"\d{1,30}"
_REFUSED_RE: Final[re.Pattern[str]] = re.compile(
    rf"^CAPTURE_REFUSED reason=(?P<reason>[a-z_]+) order_ref=(?P<ref>{_ID})$"
)
_SUBMITTED_RE: Final[re.Pattern[str]] = re.compile(
    rf"^<--\[EVT\] OrderSubmitted\(instrument_id=(?P<iid>{_ID}), "
    rf"client_order_id=(?P<coid>{_ID}), account_id=(?P<acct>{_ID}), ts_event=(?P<ts>{_INT})\)$"
)
_DENIED_RE: Final[re.Pattern[str]] = re.compile(
    rf"^<--\[EVT\] OrderDenied\(instrument_id=(?P<iid>{_ID}), "
    rf"client_order_id=(?P<coid>{_ID}), reason=(?P<reason>.*)\)$"
)
_PUBLISHED_RE: Final[re.Pattern[str]] = re.compile(
    rf"^NBM_NBP_PUBLISHED cycle_ns=(?P<cycle>{_INT}) stations=(?P<stations>\d{{1,9}}) "
    rf"points=(?P<points>\d{{1,9}}) model_version=(?P<mv>[0-9A-Za-z._-]+)$"
)
_VECTOR_RE: Final[re.Pattern[str]] = re.compile(
    rf"^FQ_VECTOR_COMPLETE station=(?P<station>{_ID}) cycle_ns=(?P<cycle>{_INT}) "
    rf"climate_day=(?P<day>\d{{4}}-\d\d-\d\d) era=(?P<era>[0-9A-Za-z._-]+)$"
)
_MISSED_RE: Final[re.Pattern[str]] = re.compile(
    rf"^NBP_CYCLE_MISSED cycle_ns=(?P<cycle>{_INT}) now_ns=(?P<now>{_INT}) "
    rf"model=(?P<model>[A-Za-z0-9_]+)(?P<unwired> \(no alert_offer wired\))?$"
)
_EPOCH_RE: Final[re.Pattern[str]] = re.compile(
    rf"^CAPTURE_EPOCH_START family=(?P<family>{_ID}) epoch_ns=(?P<epoch>{_INT})$"
)


@dataclass(frozen=True, slots=True)
class CaptureRefusedLine:
    line_no: int
    log_ts_ns: int
    reason: str
    order_ref: str


@dataclass(frozen=True, slots=True)
class OrderSubmittedLine:
    line_no: int
    log_ts_ns: int
    instrument_id: str
    client_order_id: str
    account_id: str
    ts_event: int


@dataclass(frozen=True, slots=True)
class OrderDeniedLine:
    line_no: int
    log_ts_ns: int
    instrument_id: str
    client_order_id: str
    #: The venue/client's quoted reason, capped at ``MAX_MARKER_TEXT_CHARS``.
    reason: str


@dataclass(frozen=True, slots=True)
class NbpPublishedLine:
    line_no: int
    log_ts_ns: int
    cycle_ns: int
    stations: int
    points: int
    model_version: str


@dataclass(frozen=True, slots=True)
class FqVectorCompleteLine:
    line_no: int
    log_ts_ns: int
    station: str
    cycle_ns: int
    climate_day: dt.date
    era: str


@dataclass(frozen=True, slots=True)
class NbpCycleMissedLine:
    line_no: int
    log_ts_ns: int
    cycle_ns: int
    now_ns: int
    model: str
    #: False when the "(no alert_offer wired)" suffix is present: no offer was made.
    offered: bool


@dataclass(frozen=True, slots=True)
class CaptureEpochStartLine:
    line_no: int
    log_ts_ns: int
    family_id: str
    epoch_ns: int


MarkerEvent = (
    CaptureRefusedLine
    | OrderSubmittedLine
    | OrderDeniedLine
    | NbpPublishedLine
    | FqVectorCompleteLine
    | NbpCycleMissedLine
    | CaptureEpochStartLine
)


def marker_name_for_token(token: bytes) -> str | None:
    """The marker name of a matched token, or None when it is not one of the seven."""
    for prefix, name in _TOKEN_NAMES:
        if token.startswith(prefix):
            return name
    return None


def _build(name: str, line_no: int, ts: int, m: re.Match[str]) -> MarkerEvent | None:
    """The event of a regex match, or None when a field is semantically invalid."""
    if name == MARKER_CAPTURE_REFUSED:
        return CaptureRefusedLine(line_no, ts, m["reason"], m["ref"])
    if name == MARKER_ORDER_SUBMITTED:
        return OrderSubmittedLine(line_no, ts, m["iid"], m["coid"], m["acct"], int(m["ts"]))
    if name == MARKER_ORDER_DENIED:
        return OrderDeniedLine(
            line_no, ts, m["iid"], m["coid"], m["reason"][:MAX_MARKER_TEXT_CHARS]
        )
    if name == MARKER_NBP_PUBLISHED:
        return NbpPublishedLine(
            line_no, ts, int(m["cycle"]), int(m["stations"]), int(m["points"]), m["mv"]
        )
    if name == MARKER_FQ_VECTOR_COMPLETE:
        try:
            day = dt.date.fromisoformat(m["day"])
        except ValueError:
            return None
        return FqVectorCompleteLine(line_no, ts, m["station"], int(m["cycle"]), day, m["era"])
    if name == MARKER_NBP_CYCLE_MISSED:
        return NbpCycleMissedLine(
            line_no, ts, int(m["cycle"]), int(m["now"]), m["model"], m["unwired"] is None
        )
    return CaptureEpochStartLine(line_no, ts, m["family"], int(m["epoch"]))


#: ``(marker name, message head, strict grammar)``. A bare-name head must be followed by a space (or
#: end the message), so ``CAPTURE_REFUSED_ALERT_UNDELIVERED`` is another line, not a malformed one.
_GRAMMARS: Final[tuple[tuple[str, str, re.Pattern[str]], ...]] = (
    (MARKER_CAPTURE_REFUSED, "CAPTURE_REFUSED", _REFUSED_RE),
    (MARKER_ORDER_SUBMITTED, "<--[EVT] OrderSubmitted(", _SUBMITTED_RE),
    (MARKER_ORDER_DENIED, "<--[EVT] OrderDenied(", _DENIED_RE),
    (MARKER_NBP_PUBLISHED, "NBM_NBP_PUBLISHED", _PUBLISHED_RE),
    (MARKER_FQ_VECTOR_COMPLETE, "FQ_VECTOR_COMPLETE", _VECTOR_RE),
    (MARKER_NBP_CYCLE_MISSED, "NBP_CYCLE_MISSED", _MISSED_RE),
    (MARKER_CAPTURE_EPOCH_START, "CAPTURE_EPOCH_START", _EPOCH_RE),
)


def classify_marker_message(
    line_no: int, raw: bytes, ts: int, msg: str
) -> MarkerEvent | UnparseableLine | None:
    """Classify the LOG MESSAGE of a line that matched the line grammar.

    None: the message does not start with a marker (a marker quoted inside another message is not a
    marker line). A message that starts with a marker but does not match its strict grammar is an
    ``UnparseableLine`` (``bad_fields``)."""
    for name, head, pattern in _GRAMMARS:
        if not msg.startswith(head):
            continue
        if not head.endswith("(") and msg[len(head) : len(head) + 1] not in ("", " "):
            continue
        match = pattern.match(msg)
        event = None if match is None else _build(name, line_no, ts, match)
        return event if event is not None else unparseable(line_no, name, CAUSE_BAD_FIELDS, raw)
    return None
