"""AUT-1 streaming node-log parser (plan r12 section 3.11, r8 WP5; build ruling WP0-R7).

A READ-ONLY, memory-bounded reader of the trade node's ``breezy-trade-<stamp>.log`` files and the
supervisor's log. It holds only lines that matter (Take and TrySubmit decisions, ``OrderFilled``,
``instance_id``, disposal and writer-failure lines), never the whole file, so a 1 GB log scans in
memory proportional to the number of matches.

What it extracts:

* **Decision lines.** ``SHADOW_DECISION`` lines classified by ``kind``. Each evaluation emits
  exactly one decision-class line (``NotExecutable``, ``NotDPlus1``, ``Refuse`` or ``Take``); a
  Take adds one ``TrySubmit`` line when ``shadow_only=False``. So ``evaluation_count`` is total
  minus TrySubmit
  (R3), ``pair_take_trysubmit`` pairs each TrySubmit with its Take on
  ``(instrument_id, rung_id, side)`` (R1), and ``drop_try_submits`` removes TrySubmit before an
  on-change/``eval_seq`` replay (R2).
* **Spawn events and the boot census.** Exactly four supervisor events spawn a node:
  ``launched pid=`` and ``boot_retry_launched pid=`` (logged after the spawn) and ``relaunching
  attempt=`` and ``midday_relaunching phase= attempt=`` (logged BEFORE it). ``launch_spawn_failed``
  spawns nothing. ``match_spawns_to_logs`` pairs events 1:1, in time order, with node logs by the
  log's filename stamp; the pid is never a join key, and an event with no log is
  ``node_log_missing``.
* **Boot end and writer failures.** ``<component>: DISPOSED`` (the ``TradingNode`` line ends a boot)
  and the three writer-failure texts (Nautilus ``Failed to serialize``, ``Can't find writer for
  cls`` and capture's ``CAPTURE_PUBLISH_FAILED``).

Failure handling: a marker line that does not parse, an unterminated last line and an overlong
marker line are REPORTED (``UnparseableLine``), never skipped; counts are exact even when the
stored report list is capped. An unreadable file raises ``NodeLogUnreadable`` (the audit maps it
to ERROR).

Non-writer: stdlib only, no ``breezy.adapters`` import.
"""

import ast
import calendar
import datetime as dt
import re
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final

__all__ = [
    "CAUSE_LINE_TOO_LONG",
    "CAUSE_NODE_LOG_MISSING",
    "CAUSE_TORN_TAIL",
    "DISPOSED_TEXT",
    "MARKER_CAPTURE_PUBLISH_FAILED",
    "MARKER_FAILED_TO_SERIALIZE",
    "MARKER_MISSING_WRITER",
    "MAX_LINE_BYTES",
    "MAX_STORED_REPORTS",
    "NO_SPAWN_EVENTS",
    "SPAWN_EVENTS",
    "DecisionLine",
    "DisposedLine",
    "EntryPairing",
    "NodeLogEvent",
    "NodeLogScan",
    "NodeLogUnreadable",
    "OrderFilledLine",
    "SpawnCensus",
    "SpawnEvent",
    "SpawnMatch",
    "SupervisorScan",
    "TakeInputs",
    "UnparseableLine",
    "WriterFailureLine",
    "classify_line",
    "distinct_boot_ids",
    "drop_try_submits",
    "is_try_submit",
    "iter_node_log",
    "list_node_logs",
    "match_spawns_to_logs",
    "pair_take_trysubmit",
    "parse_supervisor_lines",
    "scan_node_log",
    "scan_supervisor_log",
]

# --- constants ------------------------------------------------------------------------------

#: A line longer than this is not read whole; its head is classified and the rest drained.
MAX_LINE_BYTES: Final[int] = 1 << 20
#: Stored reports per category; the ``*_total`` counters stay exact beyond it.
MAX_STORED_REPORTS: Final[int] = 1000
_EXCERPT_CHARS: Final[int] = 160

KIND_TAKE: Final[str] = "Take"
KIND_TRY_SUBMIT: Final[str] = "TrySubmit"
#: The four ``Decision`` variants, each emitted once per evaluation; ``TrySubmit`` is the extra.
EVALUATION_KINDS: Final[frozenset[str]] = frozenset(
    {"NotExecutable", "NotDPlus1", "Refuse", KIND_TAKE}
)

DISPOSED_TEXT: Final[str] = "DISPOSED"
_TRADING_NODE_SUFFIX: Final[str] = ".TradingNode"

MARKER_FAILED_TO_SERIALIZE: Final[str] = "failed_to_serialize"
MARKER_MISSING_WRITER: Final[str] = "missing_writer"
MARKER_CAPTURE_PUBLISH_FAILED: Final[str] = "capture_publish_failed"

CAUSE_TORN_TAIL: Final[str] = "torn_tail"
CAUSE_LINE_TOO_LONG: Final[str] = "line_too_long"
CAUSE_UNDECODABLE: Final[str] = "undecodable"
CAUSE_NO_MATCH: Final[str] = "no_match"
CAUSE_BAD_FIELDS: Final[str] = "bad_fields"
CAUSE_UNKNOWN_KIND: Final[str] = "unknown_kind"
CAUSE_NODE_LOG_MISSING: Final[str] = "node_log_missing"

#: ``launched`` and ``boot_retry_launched`` are logged AFTER the spawn (``trade_supervisor.py``
#: ``:1300``,
#: ``:1633``); ``relaunching`` and ``midday_relaunching`` BEFORE it (``:1377``, ``:1972``).
SPAWN_EVENTS: Final[tuple[str, ...]] = (
    "launched",
    "boot_retry_launched",
    "relaunching",
    "midday_relaunching",
)
#: ``trade_supervisor.py:1296``: the spawn raised, so no node and no log exist for it.
NO_SPAWN_EVENTS: Final[tuple[str, ...]] = ("launch_spawn_failed",)

#: A log stamp may be this much EARLIER than its event (the stamp's ``now`` precedes the event
#: is logged and both truncate to whole seconds), or this much LATER (a pre-spawn event).
LOG_STAMP_EARLY_SLACK_S: Final[int] = 30
LOG_STAMP_MAX_LAG_S: Final[int] = 300

# --- line grammar ---------------------------------------------------------------------------

_ANSI_RE: Final[re.Pattern[str]] = re.compile(r"\x1b\[[0-9;]*m")
_MARKER_RE: Final[re.Pattern[bytes]] = re.compile(
    rb"SHADOW_DECISION|instance_id: |DISPOSED|<--\[EVT\] OrderFilled\(|Failed to serialize"
    rb"|Can't find writer for cls|CAPTURE_PUBLISH_FAILED"
)
_LINE_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:\x1b\[1m)?(?P<ts>\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,9})?Z)(?:\x1b\[0m)?"
    r" \[(?P<level>[A-Z]+)\] (?P<comp>\S+): (?P<msg>.*?)(?:\x1b\[0m)?$"
)
_TS_RE: Final[re.Pattern[bytes]] = re.compile(
    rb"^(?:\x1b\[1m)?(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(?:\.(\d{1,9}))?Z"
)
_DATE_REPR_RE: Final[re.Pattern[str]] = re.compile(r"datetime\.date\((\d+), (\d+), (\d+)\)")
_DECISION_MSG_RE: Final[re.Pattern[str]] = re.compile(r"^SHADOW_DECISION (?P<body>\{.*\})$")
_INSTANCE_MSG_RE: Final[re.Pattern[str]] = re.compile(r"^instance_id: (?P<id>[0-9A-Za-z-]{8,64})$")
_FILLED_MSG_RE: Final[re.Pattern[str]] = re.compile(r"^<--\[EVT\] OrderFilled\((?P<body>.*)\)$")
_KV_RE: Final[re.Pattern[str]] = re.compile(r"(\w+)=(.*?)(?:, (?=\w+=)|$)")
_NODE_LOG_NAME_RE: Final[re.Pattern[str]] = re.compile(r"^breezy-trade-(\d{8}T\d{6}Z)\.log$")
_SUPERVISOR_LINE_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<ts>\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ) INFO breezy\.runtime\.trade_supervisor "
    r"(?P<event>[a-z_]+)(?P<fields>(?: \w+=\S+)*)$"
)
_SPAWN_TOKEN_RE: Final[re.Pattern[str]] = re.compile(
    r"trade_supervisor (?:launched|boot_retry_launched|relaunching|midday_relaunching"
    r"|launch_spawn_failed)(?: |$)"
)

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
_NS: Final[int] = 1_000_000_000


# --- errors and value types -----------------------------------------------------------------


class NodeLogUnreadable(Exception):
    """A log could not be opened or read. ``cause`` is the OS error class name: no path, no text."""

    def __init__(self, path: Path, cause: str) -> None:
        super().__init__(cause)
        self.path = path
        self.cause = cause


@dataclass(frozen=True, slots=True)
class TakeInputs:
    qty: int
    ev_net: float
    p_hat: float
    p_lower: float
    p_upper: float


@dataclass(frozen=True, slots=True)
class DecisionLine:
    """One ``SHADOW_DECISION`` line. ``reason`` is None for a Take; ``take`` is None otherwise."""

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


@dataclass(frozen=True, slots=True)
class UnparseableLine:
    """A line the parser had to report instead of classify. ``excerpt`` is ANSI-stripped, capped."""

    line_no: int
    marker: str
    cause: str
    excerpt: str


NodeLogEvent = (
    DecisionLine
    | OrderFilledLine
    | InstanceIdLine
    | DisposedLine
    | WriterFailureLine
    | UnparseableLine
)


# --- low-level reading ----------------------------------------------------------------------


def _read_lines(path: Path) -> Iterator[tuple[int, bytes, bool, bool]]:
    """Yield ``(line_no, line, terminated, truncated)``; a line over ``MAX_LINE_BYTES`` is truncated
    to its head and the remainder drained, so memory per line is bounded."""
    try:
        with path.open("rb") as fh:
            line_no = 0
            while True:
                chunk = fh.readline(MAX_LINE_BYTES + 1)
                if not chunk:
                    return
                line_no += 1
                if len(chunk) > MAX_LINE_BYTES and not chunk.endswith(b"\n"):
                    terminated = False
                    while True:
                        rest = fh.readline(MAX_LINE_BYTES)
                        if not rest:
                            break
                        if rest.endswith(b"\n"):
                            terminated = True
                            break
                    yield line_no, chunk, terminated, True
                    continue
                yield line_no, chunk.rstrip(b"\r\n"), chunk.endswith(b"\n"), False
    except OSError as exc:
        raise NodeLogUnreadable(path, type(exc).__name__) from exc


def _ts_ns(head: bytes) -> int | None:
    m = _TS_RE.match(head)
    if m is None:
        return None
    year, month, day, hour, minute, second = (int(g) for g in m.groups()[:6])
    try:
        seconds = calendar.timegm((year, month, day, hour, minute, second))
    except (ValueError, OverflowError):
        return None
    frac = (m.group(7) or b"0").ljust(9, b"0")
    return seconds * _NS + int(frac)


def _excerpt(raw: bytes) -> str:
    text = _ANSI_RE.sub("", raw[: _EXCERPT_CHARS * 4].decode("utf-8", "replace"))
    return text[:_EXCERPT_CHARS]


# --- per-line classification ----------------------------------------------------------------


def _unparseable(line_no: int, marker: str, cause: str, raw: bytes) -> UnparseableLine:
    return UnparseableLine(line_no, marker, cause, _excerpt(raw))


def _num(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _decision_fields(body: str) -> dict[str, object] | None:
    quoted = _DATE_REPR_RE.sub(lambda m: f"('__date__', {m[1]}, {m[2]}, {m[3]})", body)
    try:
        parsed = ast.literal_eval(quoted)
    except (ValueError, SyntaxError, MemoryError, RecursionError):
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
        return _unparseable(line_no, marker, CAUSE_NO_MATCH, raw)
    kind = fields.get("kind")
    if not isinstance(kind, str) or (kind not in EVALUATION_KINDS and kind != KIND_TRY_SUBMIT):
        return _unparseable(line_no, marker, CAUSE_UNKNOWN_KIND, raw)
    wanted = _TAKE_KEYS if kind == KIND_TAKE else _OTHER_KEYS
    day = _climate_day(fields.get("climate_day"))
    now_ns = fields.get("now_ns")
    strs = [fields.get(k) for k in ("station", "rung_id", "side", "instrument_id")]
    ok = (
        set(fields) == wanted
        and day is not None
        and isinstance(now_ns, int)
        and not isinstance(now_ns, bool)
        and all(isinstance(s, str) for s in strs)
        and strs[2] in _SIDES
    )
    take = _take_inputs(fields) if ok and kind == KIND_TAKE else None
    reason = fields.get("reason")
    if (
        not ok
        or (kind == KIND_TAKE and take is None)
        or (kind != KIND_TAKE and not isinstance(reason, str))
    ):
        return _unparseable(line_no, marker, CAUSE_BAD_FIELDS, raw)
    station, rung_id, side, instrument_id = (str(s) for s in strs)
    assert day is not None and isinstance(now_ns, int)  # narrowed by ``ok``
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
    )


def _parse_filled(line_no: int, raw: bytes, ts: int, msg: str) -> OrderFilledLine | UnparseableLine:
    m = _FILLED_MSG_RE.match(msg)
    pairs = dict(_KV_RE.findall(m["body"])) if m else {}
    if not all(k in pairs for k in _FILLED_KEYS) or not pairs["ts_event"].isdigit():
        return _unparseable(line_no, "OrderFilled", CAUSE_BAD_FIELDS, raw)
    return OrderFilledLine(
        line_no=line_no,
        log_ts_ns=ts,
        instrument_id=pairs["instrument_id"],
        client_order_id=pairs["client_order_id"],
        venue_order_id=pairs["venue_order_id"],
        trade_id=pairs["trade_id"],
        ts_event=int(pairs["ts_event"]),
    )


def _writer_marker(raw: bytes) -> str | None:
    if b"Failed to serialize" in raw:
        return MARKER_FAILED_TO_SERIALIZE
    if b"Can't find writer for cls" in raw:
        return MARKER_MISSING_WRITER
    if b"CAPTURE_PUBLISH_FAILED" in raw:  # includes ``..._SUPPRESSED``: a failure's own counter
        return MARKER_CAPTURE_PUBLISH_FAILED
    return None


def classify_line(raw: bytes, line_no: int) -> NodeLogEvent | None:
    """Classify one line (no terminator). None means: not a line this parser reads."""
    hit = _MARKER_RE.search(raw)
    if hit is None:
        return None
    token = hit.group(0)
    failure = _writer_marker(raw)
    if failure is not None and token not in {b"SHADOW_DECISION", b"instance_id: "}:
        return WriterFailureLine(line_no, _ts_ns(raw), failure)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return _unparseable(line_no, token.decode().strip(": "), CAUSE_UNDECODABLE, raw)
    m = _LINE_RE.match(text)
    ts = _ts_ns(raw)
    if token == b"SHADOW_DECISION":
        if m is None or ts is None:
            return _unparseable(line_no, "SHADOW_DECISION", CAUSE_NO_MATCH, raw)
        return _parse_decision(line_no, raw, ts, m["comp"], m["msg"])
    if m is None or ts is None:
        return _unparseable_or_none(token, line_no, raw)
    if token == b"instance_id: ":
        return _parse_instance(line_no, raw, ts, m["comp"], m["msg"])
    if token == DISPOSED_TEXT.encode():
        return _parse_disposed(line_no, ts, m["comp"], m["msg"])
    return _parse_filled(line_no, raw, ts, m["msg"])


def _unparseable_or_none(token: bytes, line_no: int, raw: bytes) -> UnparseableLine | None:
    if token == b"instance_id: ":
        return _unparseable(line_no, "instance_id", CAUSE_NO_MATCH, raw)
    if token.startswith(b"<--"):
        return _unparseable(line_no, "OrderFilled", CAUSE_NO_MATCH, raw)
    return None


def _parse_instance(
    line_no: int, raw: bytes, ts: int, comp: str, msg: str
) -> InstanceIdLine | UnparseableLine | None:
    if not comp.endswith(_TRADING_NODE_SUFFIX):
        return None
    m = _INSTANCE_MSG_RE.match(msg)
    if m is None:
        return _unparseable(line_no, "instance_id", CAUSE_BAD_FIELDS, raw)
    return InstanceIdLine(line_no, ts, m["id"])


def _parse_disposed(line_no: int, ts: int, comp: str, msg: str) -> DisposedLine | None:
    return DisposedLine(line_no, ts, comp) if msg == DISPOSED_TEXT else None


def is_try_submit(line: DecisionLine) -> bool:
    return line.kind == KIND_TRY_SUBMIT


def drop_try_submits(lines: Iterable[DecisionLine]) -> Iterator[DecisionLine]:
    """R2: TrySubmit lines are extra to the evaluation, so drop them before any replay."""
    return (line for line in lines if not is_try_submit(line))


# --- streaming a node log -------------------------------------------------------------------


def iter_node_log(path: Path) -> Iterator[NodeLogEvent]:
    """Stream the classified events of one node log, in file order, holding one line at a time.

    Raises ``NodeLogUnreadable`` if the file cannot be opened or read. A truncated overlong marker
    line and an unterminated non-blank last line are yielded as ``UnparseableLine``."""
    for line_no, raw, terminated, truncated in _read_lines(path):
        event = _event_for(line_no, raw, terminated, truncated)
        if event is not None:
            yield event


@dataclass(frozen=True, slots=True)
class EntryPairing:
    """R1: each TrySubmit paired with the preceding Take on the same key."""

    pairs: tuple[tuple[DecisionLine, DecisionLine], ...]
    unpaired_takes: tuple[DecisionLine, ...]
    unpaired_try_submits: tuple[DecisionLine, ...]


def pair_take_trysubmit(lines: Iterable[DecisionLine]) -> EntryPairing:
    """Pair on ``(instrument_id, rung_id, side)`` in log order. A Take with no TrySubmit is normal
    when ``shadow_only=True``; a TrySubmit with no earlier Take (or one whose ``now_ns`` precedes
    its Take's) is unanchored. Feed only Take and TrySubmit lines."""
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


@dataclass(frozen=True, slots=True)
class NodeLogScan:
    """The summary of one node log. Only O(matches) lines are stored."""

    line_count: int
    decision_line_count: int
    kind_counts: Mapping[str, int]
    #: Take and TrySubmit lines, in log order (the input to ``pair_take_trysubmit``).
    entry_lines: tuple[DecisionLine, ...]
    instance_ids: tuple[str, ...]
    disposed_count: int
    node_disposed: bool
    fills: tuple[OrderFilledLine, ...]
    writer_failures: tuple[WriterFailureLine, ...]
    writer_failure_total: int
    unparseable: tuple[UnparseableLine, ...]
    unparseable_total: int
    last_line_ts_ns: int | None

    @property
    def evaluation_count(self) -> int:
        """R3: total decision-class lines minus TrySubmit lines."""
        return self.decision_line_count - self.kind_counts.get(KIND_TRY_SUBMIT, 0)

    @property
    def has_writer_failure(self) -> bool:
        return self.writer_failure_total > 0

    @property
    def takes(self) -> tuple[DecisionLine, ...]:
        return tuple(ln for ln in self.entry_lines if ln.kind == KIND_TAKE)

    @property
    def try_submits(self) -> tuple[DecisionLine, ...]:
        return tuple(ln for ln in self.entry_lines if ln.kind == KIND_TRY_SUBMIT)


def scan_node_log(path: Path) -> NodeLogScan:
    """One streaming pass over a node log. Raises ``NodeLogUnreadable``."""
    kinds: Counter[str] = Counter()
    entries: list[DecisionLine] = []
    instance_ids: dict[str, None] = {}
    fills: list[OrderFilledLine] = []
    failures: list[WriterFailureLine] = []
    bad: list[UnparseableLine] = []
    counts = {"lines": 0, "disposed": 0, "failures": 0, "bad": 0}
    node_disposed = False
    last_head = b""
    for line_no, raw, terminated, truncated in _read_lines(path):
        counts["lines"] = line_no
        if raw.strip():
            last_head = raw[:96]
        event = _event_for(line_no, raw, terminated, truncated)
        if event is None:
            continue
        if isinstance(event, DecisionLine):
            kinds[event.kind] += 1
            if event.kind in (KIND_TAKE, KIND_TRY_SUBMIT):
                entries.append(event)
        elif isinstance(event, InstanceIdLine):
            instance_ids.setdefault(event.instance_id)
        elif isinstance(event, DisposedLine):
            counts["disposed"] += 1
            node_disposed = node_disposed or event.is_trading_node
        elif isinstance(event, OrderFilledLine):
            fills.append(event)
        elif isinstance(event, WriterFailureLine):
            counts["failures"] += 1
            if len(failures) < MAX_STORED_REPORTS:
                failures.append(event)
        else:
            counts["bad"] += 1
            if len(bad) < MAX_STORED_REPORTS:
                bad.append(event)
    return NodeLogScan(
        line_count=counts["lines"],
        decision_line_count=sum(kinds.values()),
        kind_counts=MappingProxyType(dict(kinds)),
        entry_lines=tuple(entries),
        instance_ids=tuple(instance_ids),
        disposed_count=counts["disposed"],
        node_disposed=node_disposed,
        fills=tuple(fills),
        writer_failures=tuple(failures),
        writer_failure_total=counts["failures"],
        unparseable=tuple(bad),
        unparseable_total=counts["bad"],
        last_line_ts_ns=_ts_ns(last_head) if last_head else None,
    )


def _event_for(line_no: int, raw: bytes, terminated: bool, truncated: bool) -> NodeLogEvent | None:
    if truncated:
        return (
            _unparseable(line_no, "marker", CAUSE_LINE_TOO_LONG, raw)
            if _MARKER_RE.search(raw)
            else None
        )
    if not terminated and raw.strip():
        return _unparseable(line_no, "line", CAUSE_TORN_TAIL, raw)
    return classify_line(raw, line_no)


def distinct_boot_ids(scans: Iterable[NodeLogScan]) -> tuple[str, ...]:
    """Boots are counted by ``TradingNode: instance_id:``, never by a time window (WP0-R5)."""
    seen: dict[str, None] = {}
    for scan in scans:
        for instance_id in scan.instance_ids:
            seen.setdefault(instance_id)
    return tuple(seen)


# --- supervisor spawn events and the boot census --------------------------------------------


@dataclass(frozen=True, slots=True)
class SpawnEvent:
    line_no: int
    ts: dt.datetime
    event: str
    pid: int | None = None
    attempt: int | None = None
    phase: str | None = None


@dataclass(frozen=True, slots=True)
class SupervisorScan:
    spawns: tuple[SpawnEvent, ...]
    no_spawn_count: int
    unparseable: tuple[UnparseableLine, ...]
    unparseable_total: int


def _int_field(fields: Mapping[str, str], name: str) -> int | None:
    value = fields.get(name, "")
    return int(value) if value.isdigit() else None


def _spawn_event(
    line_no: int, when: dt.datetime, event: str, fields: Mapping[str, str]
) -> SpawnEvent | None:
    pid, attempt = _int_field(fields, "pid"), _int_field(fields, "attempt")
    phase = fields.get("phase")
    valid = {
        "launched": pid is not None,
        "boot_retry_launched": pid is not None,
        "relaunching": attempt is not None,
        "midday_relaunching": attempt is not None and phase is not None,
    }[event]
    if not valid:
        return None
    return SpawnEvent(line_no, when, event, pid=pid, attempt=attempt, phase=phase)


def _parse_supervisor(items: Iterable[tuple[int, str, bool]]) -> SupervisorScan:
    spawns: list[SpawnEvent] = []
    bad: list[UnparseableLine] = []
    bad_total = no_spawn = 0
    for line_no, text, terminated in items:
        if _SPAWN_TOKEN_RE.search(text) is None:
            continue
        m = _SUPERVISOR_LINE_RE.match(text) if terminated else None
        parsed: SpawnEvent | None = None
        if m is not None:
            if m["event"] in NO_SPAWN_EVENTS:
                no_spawn += 1
                continue
            fields = dict(kv.split("=", 1) for kv in m["fields"].split())
            when = dt.datetime.strptime(m["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.UTC)
            parsed = _spawn_event(line_no, when, m["event"], fields)
        if parsed is not None:
            spawns.append(parsed)
            continue
        bad_total += 1
        if len(bad) < MAX_STORED_REPORTS:
            cause = CAUSE_BAD_FIELDS if terminated else CAUSE_TORN_TAIL
            bad.append(UnparseableLine(line_no, "spawn_event", cause, text[:_EXCERPT_CHARS]))
    return SupervisorScan(tuple(spawns), no_spawn, tuple(bad), bad_total)


def parse_supervisor_lines(lines: Iterable[str]) -> SupervisorScan:
    """Extract spawn events from supervisor log text (one complete line per item)."""
    return _parse_supervisor((n, text, True) for n, text in enumerate(lines, start=1))


def scan_supervisor_log(path: Path) -> SupervisorScan:
    """Read a supervisor log file. Raises ``NodeLogUnreadable``. An unterminated last spawn line is
    reported as ``torn_tail``."""
    return _parse_supervisor(
        (n, raw.decode("utf-8", "replace"), terminated)
        for n, raw, terminated, _truncated in _read_lines(path)
    )


@dataclass(frozen=True, slots=True)
class SpawnMatch:
    event: SpawnEvent
    log_path: Path | None

    @property
    def cause(self) -> str | None:
        return CAUSE_NODE_LOG_MISSING if self.log_path is None else None


@dataclass(frozen=True, slots=True)
class SpawnCensus:
    matches: tuple[SpawnMatch, ...]
    unmatched_logs: tuple[Path, ...]

    @property
    def missing(self) -> tuple[SpawnMatch, ...]:
        """Events with no log: each is ``ERROR node_log_missing``."""
        return tuple(m for m in self.matches if m.log_path is None)


def _stamp(path: Path) -> dt.datetime | None:
    m = _NODE_LOG_NAME_RE.match(path.name)
    if m is None:
        return None
    return dt.datetime.strptime(m[1], "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.UTC)


def list_node_logs(log_dir: Path) -> list[Path]:
    """``breezy-trade-<stamp>.log`` files, oldest first. The supervisor's own logs share the prefix
    and never match. Raises ``NodeLogUnreadable`` if the directory cannot be listed."""
    try:
        found = [p for p in log_dir.iterdir() if _NODE_LOG_NAME_RE.match(p.name)]
    except OSError as exc:
        raise NodeLogUnreadable(log_dir, type(exc).__name__) from exc
    return sorted(found, key=lambda p: p.name)


def match_spawns_to_logs(events: Sequence[SpawnEvent], logs: Sequence[Path]) -> SpawnCensus:
    """Match each spawn event, in time order, to the next unmatched node log, 1:1.

    The log's stamp must lie within ``LOG_STAMP_EARLY_SLACK_S`` before to ``LOG_STAMP_MAX_LAG_S``
    after the event: a later log belongs to a later spawn, so an event does not borrow it. The pid
    is never consulted.
    Logs left over (a hand-launched node has no event) are reported, not errors."""
    stamped = sorted(((s, p) for p in logs if (s := _stamp(p)) is not None), key=lambda sp: sp[0])
    if len(stamped) != len(logs):
        raise ValueError("every path must be a breezy-trade-<stamp>.log node log")
    used = [False] * len(stamped)
    early, late = (
        dt.timedelta(seconds=LOG_STAMP_EARLY_SLACK_S),
        dt.timedelta(seconds=LOG_STAMP_MAX_LAG_S),
    )
    matches: list[SpawnMatch] = []
    for event in sorted(events, key=lambda e: e.ts):
        chosen: Path | None = None
        for i, (stamp, path) in enumerate(stamped):
            if not used[i] and event.ts - early <= stamp <= event.ts + late:
                used[i], chosen = True, path
                break
        matches.append(SpawnMatch(event, chosen))
    leftover = tuple(path for i, (_s, path) in enumerate(stamped) if not used[i])
    return SpawnCensus(tuple(matches), leftover)
