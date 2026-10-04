"""AUT-1 node-log line classification (plan r12 section 3.11; build rulings WP0-R7, WP5-R4).

Turns one node-log line into an event: a ``SHADOW_DECISION`` line (classified by ``kind``), an
``OrderFilled`` line, the ``TradingNode: instance_id:`` line, a ``<component>: DISPOSED`` line, or a
writer-failure line. A line that carries a marker but does not parse is returned as an
``UnparseableLine``, never dropped.

Failure vs decision (WP5-R4, py M2): a line is a decision line iff its LOG MESSAGE starts with
``SHADOW_DECISION ``. Otherwise a writer-failure marker anywhere in the line always counts, so a
failure text that quotes a decision can never be read as one, and a decision whose field text
mentions a marker is still a decision.

Each evaluation emits exactly one decision-class line (``NotExecutable``, ``NotDPlus1``, ``Refuse``
or ``Take``); a Take adds one ``TrySubmit`` line when ``shadow_only=False``. Older builds also
logged
byte-identical repeats of the same evaluation: ``DecisionLine.digest`` (blake2b-8 of the message)
lets ``DuplicateTracker`` and ``dedupe_decisions`` find them; whether a repeat fails a day is the
audit's ruling, not the parser's.
"""

import ast
import datetime as dt
import hashlib
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Final

from breezy.analysis.capture_node_log_io import (
    CAUSE_BAD_FIELDS,
    CAUSE_NO_MATCH,
    CAUSE_UNDECODABLE,
    CAUSE_UNKNOWN_KIND,
    FAILURE_RE,
    UnparseableLine,
    ts_ns,
    unparseable,
)

__all__ = [
    "DISPOSED_TEXT",
    "EVALUATION_KINDS",
    "KIND_TAKE",
    "KIND_TRY_SUBMIT",
    "MARKER_CAPTURE_PUBLISH_FAILED",
    "MARKER_FAILED_TO_SERIALIZE",
    "MARKER_MISSING_WRITER",
    "DecisionLine",
    "DisposedLine",
    "DuplicateTracker",
    "EntryPairing",
    "InstanceIdLine",
    "NodeLogEvent",
    "OrderFilledLine",
    "TakeInputs",
    "WriterFailureLine",
    "classify_line",
    "dedupe_decisions",
    "drop_try_submits",
    "is_try_submit",
    "marker_name",
    "pair_take_trysubmit",
]

KIND_TAKE: Final[str] = "Take"
KIND_TRY_SUBMIT: Final[str] = "TrySubmit"
#: The four ``Decision`` variants, each emitted once per evaluation; ``TrySubmit`` is the extra.
EVALUATION_KINDS: Final[frozenset[str]] = frozenset(
    {"NotExecutable", "NotDPlus1", "Refuse", KIND_TAKE}
)
DISPOSED_TEXT: Final[str] = "DISPOSED"
_TRADING_NODE_SUFFIX: Final[str] = ".TradingNode"
_DECISION_PREFIX: Final[str] = "SHADOW_DECISION "

MARKER_FAILED_TO_SERIALIZE: Final[str] = "failed_to_serialize"
MARKER_MISSING_WRITER: Final[str] = "missing_writer"
MARKER_CAPTURE_PUBLISH_FAILED: Final[str] = "capture_publish_failed"

_MARKER_RE: Final[re.Pattern[bytes]] = re.compile(
    rb"SHADOW_DECISION|instance_id: |DISPOSED|<--\[EVT\] OrderFilled\(|Failed to serialize"
    rb"|Can't find writer for cls|CAPTURE_PUBLISH_FAILED"
)
_LINE_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:\x1b\[1m)?(?P<ts>\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,9})?Z)(?:\x1b\[0m)?"
    r" \[(?P<level>[A-Z]+)\] (?P<comp>\S+): (?P<msg>.*?)(?:\x1b\[0m)?$"
)
_ANSI_END_RE: Final[re.Pattern[str]] = re.compile(r"(?:\x1b\[[0-9;]*m)+$")
_DATE_REPR_RE: Final[re.Pattern[str]] = re.compile(r"datetime\.date\((\d+), (\d+), (\d+)\)")
_DECISION_MSG_RE: Final[re.Pattern[str]] = re.compile(r"^SHADOW_DECISION (?P<body>\{.*\})$")
_INSTANCE_MSG_RE: Final[re.Pattern[str]] = re.compile(r"^instance_id: (?P<id>[0-9A-Za-z-]{8,64})$")
_FILLED_MSG_RE: Final[re.Pattern[str]] = re.compile(r"^<--\[EVT\] OrderFilled\((?P<body>.*)\)$")
_KV_RE: Final[re.Pattern[str]] = re.compile(r"(\w+)=(.*?)(?:, (?=\w+=)|$)")

_BASE_KEYS: Final[frozenset[str]] = frozenset(
    {"now_ns", "station", "climate_day", "rung_id", "side", "instrument_id", "kind"}
)
_TAKE_KEYS: Final[frozenset[str]] = _BASE_KEYS | {"qty", "ev_net", "p_hat", "p_lower", "p_upper"}
_OTHER_KEYS: Final[frozenset[str]] = _BASE_KEYS | {"reason"}
_SIDES: Final[frozenset[str]] = frozenset({"yes", "no"})
_FILLED_KEYS: Final[tuple[str, ...]] = (
    "instrument_id",
    "client_order_id",
    "venue_order_id",
    "trade_id",
    "ts_event",
)
_DIGEST_BYTES: Final[int] = 8


@dataclass(frozen=True, slots=True)
class TakeInputs:
    qty: int
    ev_net: float
    p_hat: float
    p_lower: float
    p_upper: float


@dataclass(frozen=True, slots=True)
class DecisionLine:
    """One ``SHADOW_DECISION`` line. ``reason`` is None for a Take; ``take`` is None otherwise.

    ``digest`` is blake2b-8 of the log message (not of the timestamped line, so a repeat logged a
    moment later has the same digest); it is empty for a hand-built line."""

    line_no: int
    log_ts_ns: int
    component: str
    now_ns: int
    station: str
    climate_day: dt.date
    rung_id: str
    side: str
    instrument_id: str
    kind: str
    reason: str | None
    take: TakeInputs | None
    digest: bytes = b""

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.instrument_id, self.rung_id, self.side)


@dataclass(frozen=True, slots=True)
class OrderFilledLine:
    line_no: int
    log_ts_ns: int
    instrument_id: str
    client_order_id: str
    venue_order_id: str
    trade_id: str
    ts_event: int


@dataclass(frozen=True, slots=True)
class InstanceIdLine:
    line_no: int
    log_ts_ns: int
    instance_id: str


@dataclass(frozen=True, slots=True)
class DisposedLine:
    line_no: int
    log_ts_ns: int
    component: str

    @property
    def is_trading_node(self) -> bool:
        """The ``TradingNode`` disposal is the last one logged, and the one that ends a boot."""
        return self.component.endswith(_TRADING_NODE_SUFFIX)


@dataclass(frozen=True, slots=True)
class WriterFailureLine:
    line_no: int
    log_ts_ns: int | None
    marker: str


NodeLogEvent = (
    DecisionLine
    | OrderFilledLine
    | InstanceIdLine
    | DisposedLine
    | WriterFailureLine
    | UnparseableLine
)


def _num(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _decision_fields(body: str) -> dict[str, object] | None:
    quoted = _DATE_REPR_RE.sub(lambda m: f"('__date__', {m[1]}, {m[2]}, {m[3]})", body)
    try:
        parsed = ast.literal_eval(quoted)
    except (ValueError, TypeError, OverflowError, SyntaxError, MemoryError, RecursionError):
        return None
    if not isinstance(parsed, dict) or not all(isinstance(k, str) for k in parsed):
        return None
    return parsed


def _climate_day(value: object) -> dt.date | None:
    if not (isinstance(value, tuple) and len(value) == 4 and value[0] == "__date__"):
        return None
    try:
        return dt.date(int(value[1]), int(value[2]), int(value[3]))
    except (ValueError, TypeError):
        return None


def _take_inputs(fields: Mapping[str, object]) -> TakeInputs | None:
    qty = fields["qty"]
    nums = [_num(fields[k]) for k in ("ev_net", "p_hat", "p_lower", "p_upper")]
    if isinstance(qty, bool) or not isinstance(qty, int) or None in nums:
        return None
    ev_net, p_hat, p_lower, p_upper = (n for n in nums if n is not None)
    return TakeInputs(qty=qty, ev_net=ev_net, p_hat=p_hat, p_lower=p_lower, p_upper=p_upper)


def _parse_decision(
    line_no: int, raw: bytes, ts: int, comp: str, msg: str
) -> DecisionLine | UnparseableLine:
    marker = "SHADOW_DECISION"
    m = _DECISION_MSG_RE.match(msg)
    fields = _decision_fields(m["body"]) if m else None
    if fields is None:
        return unparseable(line_no, marker, CAUSE_NO_MATCH, raw)
    kind = fields.get("kind")
    if not isinstance(kind, str) or (kind not in EVALUATION_KINDS and kind != KIND_TRY_SUBMIT):
        return unparseable(line_no, marker, CAUSE_UNKNOWN_KIND, raw)
    day = _climate_day(fields.get("climate_day"))
    now_ns = fields.get("now_ns")
    strs = [fields.get(k) for k in ("station", "rung_id", "side", "instrument_id")]
    station, rung_id, side, instrument_id = strs
    reason = fields.get("reason")
    is_take = kind == KIND_TAKE
    take = _take_inputs(fields) if is_take and set(fields) == _TAKE_KEYS else None
    shape_ok = set(fields) == (_TAKE_KEYS if is_take else _OTHER_KEYS) and (
        take is not None if is_take else isinstance(reason, str)
    )
    if (
        not shape_ok
        or day is None
        or isinstance(now_ns, bool)
        or not isinstance(now_ns, int)
        or not isinstance(station, str)
        or not isinstance(rung_id, str)
        or not isinstance(side, str)
        or not isinstance(instrument_id, str)
        or side not in _SIDES
    ):
        return unparseable(line_no, marker, CAUSE_BAD_FIELDS, raw)
    return DecisionLine(
        line_no=line_no,
        log_ts_ns=ts,
        component=comp,
        now_ns=now_ns,
        station=station,
        climate_day=day,
        rung_id=rung_id,
        side=side,
        instrument_id=instrument_id,
        kind=kind,
        reason=reason if isinstance(reason, str) else None,
        take=take,
        digest=hashlib.blake2b(msg.encode("utf-8"), digest_size=_DIGEST_BYTES).digest(),
    )


def _parse_filled(line_no: int, raw: bytes, ts: int, msg: str) -> OrderFilledLine | UnparseableLine:
    m = _FILLED_MSG_RE.match(msg)
    pairs = dict(_KV_RE.findall(m["body"])) if m else {}
    if not all(k in pairs for k in _FILLED_KEYS) or not pairs["ts_event"].isdigit():
        return unparseable(line_no, "OrderFilled", CAUSE_BAD_FIELDS, raw)
    return OrderFilledLine(
        line_no=line_no,
        log_ts_ns=ts,
        instrument_id=pairs["instrument_id"],
        client_order_id=pairs["client_order_id"],
        venue_order_id=pairs["venue_order_id"],
        trade_id=pairs["trade_id"],
        ts_event=int(pairs["ts_event"]),
    )


def marker_name(text: bytes) -> str:
    """The marker name of a matched writer-failure text."""
    if text == b"Failed to serialize":
        return MARKER_FAILED_TO_SERIALIZE
    if text == b"CAPTURE_PUBLISH_FAILED":
        return MARKER_CAPTURE_PUBLISH_FAILED  # includes ``..._SUPPRESSED``: a failure's counter
    return MARKER_MISSING_WRITER


def _writer_marker(raw: bytes) -> str | None:
    hit = FAILURE_RE.search(raw)
    return None if hit is None else marker_name(hit.group(0))


def _parse_instance(
    line_no: int, raw: bytes, ts: int, comp: str, msg: str
) -> InstanceIdLine | UnparseableLine | None:
    if not comp.endswith(_TRADING_NODE_SUFFIX):
        return None
    m = _INSTANCE_MSG_RE.match(msg)
    if m is None:
        return unparseable(line_no, "instance_id", CAUSE_BAD_FIELDS, raw)
    return InstanceIdLine(line_no, ts, m["id"])


def _classify_grammatical(
    line_no: int, raw: bytes, ts: int, comp: str, msg: str
) -> NodeLogEvent | None:
    """A line that matched the Nautilus line grammar."""
    if msg.startswith(_DECISION_PREFIX):
        return _parse_decision(line_no, raw, ts, comp, msg)
    failure = _writer_marker(raw)
    if failure is not None:
        return WriterFailureLine(line_no, ts, failure)
    if "SHADOW_DECISION {" in msg:  # a decision body inside another message: a torn/merged write
        return unparseable(line_no, "SHADOW_DECISION", CAUSE_NO_MATCH, raw)
    if msg.startswith("instance_id: "):
        return _parse_instance(line_no, raw, ts, comp, msg)
    if msg.startswith("<--[EVT] OrderFilled("):
        return _parse_filled(line_no, raw, ts, msg)
    if msg == DISPOSED_TEXT:
        return DisposedLine(line_no, ts, comp)
    return None


def _classify_ungrammatical(line_no: int, raw: bytes, token: bytes) -> NodeLogEvent | None:
    """A marker line that failed the grammar: a failure still counts; the rest are reported."""
    failure = _writer_marker(raw)
    if failure is not None:
        return WriterFailureLine(line_no, ts_ns(raw), failure)
    if token == b"SHADOW_DECISION":
        return unparseable(line_no, "SHADOW_DECISION", CAUSE_NO_MATCH, raw)
    if token == b"instance_id: ":
        return unparseable(line_no, "instance_id", CAUSE_NO_MATCH, raw)
    if token.startswith(b"<--"):
        return unparseable(line_no, "OrderFilled", CAUSE_NO_MATCH, raw)
    text = _ANSI_END_RE.sub("", raw.decode("utf-8", "replace"))
    if token == DISPOSED_TEXT.encode() and ts_ns(raw) is not None and text.endswith(DISPOSED_TEXT):
        return unparseable(line_no, DISPOSED_TEXT, CAUSE_NO_MATCH, raw)  # timestamped, malformed
    return None


def classify_line(raw: bytes, line_no: int) -> NodeLogEvent | None:
    """Classify one line (no terminator). None means: not a line this parser reads."""
    hit = _MARKER_RE.search(raw)
    if hit is None:
        return None
    token = hit.group(0)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        failure = _writer_marker(raw)
        if failure is not None:
            return WriterFailureLine(line_no, ts_ns(raw), failure)
        return unparseable(line_no, token.decode().strip(": "), CAUSE_UNDECODABLE, raw)
    m = _LINE_RE.match(text)
    ts = ts_ns(raw)
    if m is None or ts is None:
        return _classify_ungrammatical(line_no, raw, token)
    return _classify_grammatical(line_no, raw, ts, m["comp"], m["msg"])


def is_try_submit(line: DecisionLine) -> bool:
    return line.kind == KIND_TRY_SUBMIT


def drop_try_submits(lines: Iterable[DecisionLine]) -> Iterator[DecisionLine]:
    """R2: TrySubmit lines are extra to the evaluation, so drop them before any replay."""
    return (line for line in lines if not is_try_submit(line))


class DuplicateTracker:
    """Finds byte-identical repeats of one evaluation: the same ``now_ns`` and message digest.

    Repeats are adjacent in practice (an older build logged each decision twice, ~100 us apart), so
    the tracker holds only the digests of the CURRENT ``now_ns``: memory is bounded by the number of
    distinct decisions of one tick. A line with no digest is never a duplicate."""

    def __init__(self) -> None:
        self._now_ns: int | None = None
        self._seen: set[bytes] = set()

    def is_duplicate(self, line: DecisionLine) -> bool:
        if not line.digest:
            return False
        if line.now_ns != self._now_ns:
            self._now_ns = line.now_ns
            self._seen = set()
        if line.digest in self._seen:
            return True
        self._seen.add(line.digest)
        return False


def dedupe_decisions(lines: Iterable[DecisionLine]) -> Iterator[DecisionLine]:
    """Yield each decision once, dropping byte-identical repeats within a tick."""
    tracker = DuplicateTracker()
    return (line for line in lines if not tracker.is_duplicate(line))


@dataclass(frozen=True, slots=True)
class EntryPairing:
    """R1: each TrySubmit paired with the preceding Take on the same key."""

    pairs: tuple[tuple[DecisionLine, DecisionLine], ...]
    unpaired_takes: tuple[DecisionLine, ...]
    unpaired_try_submits: tuple[DecisionLine, ...]


def pair_take_trysubmit(lines: Iterable[DecisionLine]) -> EntryPairing:
    """Pair on ``(instrument_id, rung_id, side)`` in log order. A Take with no TrySubmit is normal
    when ``shadow_only=True``; a TrySubmit with no earlier Take (or one whose ``now_ns`` precedes
    its Take's) is unanchored. Other kinds in ``lines`` are ignored."""
    pending: dict[tuple[str, str, str], DecisionLine] = {}
    pairs: list[tuple[DecisionLine, DecisionLine]] = []
    orphan_takes: list[DecisionLine] = []
    orphan_subs: list[DecisionLine] = []
    for line in lines:
        if line.kind == KIND_TAKE:
            replaced = pending.get(line.key)
            if replaced is not None:
                orphan_takes.append(replaced)
            pending[line.key] = line
        elif line.kind == KIND_TRY_SUBMIT:
            take = pending.get(line.key)
            if take is None or line.now_ns < take.now_ns:
                orphan_subs.append(line)
            else:
                del pending[line.key]
                pairs.append((take, line))
    leftover = sorted([*orphan_takes, *pending.values()], key=lambda ln: ln.line_no)
    return EntryPairing(tuple(pairs), tuple(leftover), tuple(orphan_subs))
