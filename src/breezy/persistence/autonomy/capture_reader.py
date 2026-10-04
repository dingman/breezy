"""AUT-1 capture reader and the C1 projection (plan r12 sections 3.3.1, 3.9; build rulings WP0-R4).

``read_capture_stream(boot_dir)`` reads one boot's stream directory
(``<capture_root>/<source>/<instance_id>/``) written by the native ``StreamingFeatherWriter``.
``project_c1(stream)`` yields the C1 logical records (``DecisionRecord``, ``OrderLink``,
``LifecycleEvent``, ``PositionMark``, ``DetectorEvent``) under C1's own names, so downstream readers
(AUT-2, AUT-3, AUT-4, AUT-6, the daily audit) never see the storage rename (ER-4).

Rules this module keeps:

* **Read-only, no symlinks.** The directory is opened with ``single_read.open_root``
  (``O_NOFOLLOW``, owner-checked); every entry is opened ``O_NOFOLLOW`` relative to that directory
  fd and the SAME fd is read, so no path is resolved twice. A symlink anywhere in the directory is a
  ``SYMLINK`` refusal, never a skipped file.
* **Torn tail.** A truncated final Arrow message is classified by the existing
  ``feather_preflight`` scanner (not a new one): the readable prefix is kept and the loss is named
  in ``CaptureStream.torn_tails``. Whether that is INFO (the boot is running) or counted (it has
  ended) is the audit's call, not the reader's.
* **Stored, never re-derived.** ``eval_ns`` and ``eval_seq`` are exposed exactly as stored (the r8
  L1 contract).
* **Streamed enum NAMES (WP0-R4).** A streamed ``OrderInitialized`` carries ``BUY`` / ``IOC``;
  ``intent_fingerprint`` hashes ``str(enum)`` (``'1'`` / ``'2'`` on Nautilus 1.231.0). The names are
  mapped back through ``order_side_from_str`` / ``time_in_force_from_str`` and ``str()``, and the
  price is read from the ``options`` JSON (the ``price`` column is null).
* **No raw venue order id, no path in any message.**
"""

import errno
import hashlib
import json
import os
import re
import stat
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

import pyarrow as pa
from nautilus_trader.model.enums import (
    OrderSide,
    TimeInForce,
    order_side_from_str,
    time_in_force_from_str,
)
from nautilus_trader.persistence.funcs import class_to_filename
from nautilus_trader.serialization.arrow.serializer import ArrowSerializer

from breezy.domain.forecast_point import ForecastPoint
from breezy.domain.instrument_leg import leg_of_symbol, symbol_of_instrument_id
from breezy.persistence.autonomy.capture_ids import (
    compute_exit_decision_id,
    compute_orphan_decision_id,
    forecast_ref_of,
    frame_ref_of,
    parse_frame_ref,
)
from breezy.persistence.autonomy.capture_records import (
    SOURCES,
    CaptureHeartbeat,
    DecisionRecord,
    DetectorEvent,
    FrameCopy,
    OrderEventRecord,
)
from breezy.persistence.autonomy.single_read import (
    SingleReadReason,
    SingleReadRefused,
    open_root,
)
from breezy.persistence.exit_tags import (
    DECISION_ID_TAG_PREFIX,
    EXIT_CLIENT_ORDER_ID_TAG_PREFIX,
    EXIT_FAMILY_TAG_PREFIX,
    EXIT_POSITION_TAG_PREFIX,
    EXIT_RULE_TAG_PREFIX,
)
from breezy.persistence.feather_preflight import FeatherStatus, salvage_feather_file

__all__ = [
    "C1View",
    "CaptureProjectionError",
    "CaptureStream",
    "DecisionView",
    "FillJoin",
    "FrameResolution",
    "FrameSource",
    "JoinStatus",
    "LifecycleEventView",
    "OrderLinkView",
    "PositionMarkView",
    "TapeLookup",
    "TornTail",
    "join_fills_to_decisions",
    "project_c1",
    "read_capture_stream",
    "recompute_intent_fingerprint",
    "resolve_frame_ref",
]

_FILE_RE: Final[re.Pattern[str]] = re.compile(r"\A(?P<table>.+)_(?P<ts>\d+)\.feather\Z")
_OPEN_FLAGS: Final[int] = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
#: The kernel path that names an already-verified fd, so the scanner reads the SAME inode.
_FD_PATH: Final[str] = "/proc/self/fd"

_CUSTOM_CLASSES: Final[tuple[type, ...]] = (
    DecisionRecord,
    FrameCopy,
    OrderEventRecord,
    DetectorEvent,
    CaptureHeartbeat,
    ForecastPoint,
)
_CUSTOM_BY_TABLE: Final[dict[str, type]] = {class_to_filename(c): c for c in _CUSTOM_CLASSES}
_ORDER_INITIALIZED: Final[str] = "order_initialized"
_ORDER_FILLED: Final[str] = "order_filled"
_POSITION_TABLES: Final[frozenset[str]] = frozenset(
    {"position_opened", "position_changed", "position_closed"}
)
_NATIVE_TABLES: Final[frozenset[str]] = frozenset(
    {_ORDER_INITIALIZED, _ORDER_FILLED, *_POSITION_TABLES}
)
#: ``intent_fingerprint`` joins its six fields with a newline (``submit_chain.py:243``).
_FINGERPRINT_SEP: Final[str] = "\n"
_NODE_BELIEF: Final[str] = "node_belief"
_FILLED: Final[str] = "FILLED"
_ORDER_PREFIX: Final[str] = "Order"
_ACCEPTED: Final[str] = "OrderAccepted"
_NO: Final[str] = "no"

NativeRow = Mapping[str, Any]


class CaptureProjectionError(ValueError):
    """A stored row cannot be projected (an unknown enum name, a malformed tag list)."""


@dataclass(frozen=True, slots=True)
class TornTail:
    """A file whose final Arrow message is incomplete. The readable prefix was kept."""

    table: str
    file_name: str
    size_bytes: int
    readable_bytes: int
    rows_recovered: int

    @property
    def lost_bytes(self) -> int:
        return self.size_bytes - self.readable_bytes


@dataclass(frozen=True, slots=True)
class CaptureStream:
    """One boot's stream, every table in stream order (file timestamp, then row order)."""

    instance_id: str
    source: str
    decisions: tuple[Any, ...] = ()
    frame_copies: tuple[Any, ...] = ()
    order_events: tuple[Any, ...] = ()
    detector_events: tuple[Any, ...] = ()
    heartbeats: tuple[Any, ...] = ()
    forecast_points: tuple[ForecastPoint, ...] = ()
    order_initialized: tuple[NativeRow, ...] = ()
    order_filled: tuple[NativeRow, ...] = ()
    #: ``(table, row)`` for every native ``Position*`` event, in stream order per table.
    position_events: tuple[tuple[str, NativeRow], ...] = ()
    torn_tails: tuple[TornTail, ...] = ()
    #: Regular files in the directory that are not a known ``<table>_<ts>.feather``.
    unrecognised_files: tuple[str, ...] = ()

    @property
    def has_torn_tail(self) -> bool:
        return bool(self.torn_tails)


# -- reading -----------------------------------------------------------------------------------


def _refused(reason: SingleReadReason, name: str) -> SingleReadRefused:
    return SingleReadRefused(reason, name)


def _open_entry(dirfd: int, name: str) -> int:
    try:
        fd = os.open(name, _OPEN_FLAGS, dir_fd=dirfd)
    except FileNotFoundError as exc:
        raise _refused(SingleReadReason.NOT_FOUND, name) from exc
    except OSError as exc:
        if exc.errno == errno.ELOOP:  # O_NOFOLLOW met a symlink
            raise _refused(SingleReadReason.SYMLINK, name) from exc
        raise _refused(SingleReadReason.IO, name) from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise _refused(SingleReadReason.NOT_REGULAR, name)
        if info.st_uid != os.geteuid():
            raise _refused(SingleReadReason.WRONG_OWNER, name)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _list_entries(dirfd: int) -> list[str]:
    """Every entry name; any symlink, of any name, is refused (fail closed)."""
    names: list[str] = []
    with os.scandir(dirfd) as scan:
        for entry in scan:
            if entry.is_symlink():
                raise _refused(SingleReadReason.SYMLINK, entry.name)
            names.append(entry.name)
    return sorted(names)


def _scan_file(dirfd: int, name: str) -> tuple[Any, pa.Table | None]:
    """The preflight report and the readable-prefix table of one file, read through one fd."""
    fd = _open_entry(dirfd, name)
    try:
        result = salvage_feather_file(Path(f"{_FD_PATH}/{fd}"))
    finally:
        os.close(fd)
    if result.report.status is FeatherStatus.UNREADABLE:
        raise _refused(SingleReadReason.IO, name)
    return result.report, result.table


def _decode(table_name: str, table: pa.Table) -> list[Any]:
    cls = _CUSTOM_BY_TABLE.get(table_name)
    if cls is not None:
        return list(ArrowSerializer.deserialize(cls, table))
    return list(table.to_pylist())


@dataclass(slots=True)
class _Collected:
    rows: dict[str, list[Any]]
    torn: list[TornTail]
    unrecognised: list[str]


def _collect(dirfd: int) -> _Collected:
    by_table: dict[str, list[tuple[int, str]]] = {}
    unrecognised: list[str] = []
    for name in _list_entries(dirfd):
        match = _FILE_RE.match(name)
        table = match.group("table") if match else ""
        if match is None or (table not in _CUSTOM_BY_TABLE and table not in _NATIVE_TABLES):
            unrecognised.append(name)
            continue
        by_table.setdefault(table, []).append((int(match.group("ts")), name))
    collected = _Collected({}, [], unrecognised)
    for table, files in by_table.items():
        for _, name in sorted(files):
            report, data = _scan_file(dirfd, name)
            if report.status is FeatherStatus.TRUNCATED:
                collected.torn.append(
                    TornTail(table, name, report.size_bytes, report.readable_bytes, report.rows)
                )
            if data is not None:
                collected.rows.setdefault(table, []).extend(_decode(table, data))
    return collected


def read_capture_stream(boot_dir: Path) -> CaptureStream:
    """Read one boot's stream directory. Raises ``SingleReadRefused`` for a symlink (the directory
    itself or any entry), a missing or foreign-owned directory, or an unreadable file."""
    dirfd = open_root(boot_dir)
    try:
        collected = _collect(dirfd)
    finally:
        os.close(dirfd)
    rows = collected.rows
    source = boot_dir.parent.name
    return CaptureStream(
        instance_id=boot_dir.name,
        source=source if source in SOURCES else "",
        decisions=tuple(rows.get(class_to_filename(DecisionRecord), ())),
        frame_copies=tuple(rows.get(class_to_filename(FrameCopy), ())),
        order_events=tuple(rows.get(class_to_filename(OrderEventRecord), ())),
        detector_events=tuple(rows.get(class_to_filename(DetectorEvent), ())),
        heartbeats=tuple(rows.get(class_to_filename(CaptureHeartbeat), ())),
        forecast_points=tuple(rows.get(class_to_filename(ForecastPoint), ())),
        order_initialized=tuple(rows.get(_ORDER_INITIALIZED, ())),
        order_filled=tuple(rows.get(_ORDER_FILLED, ())),
        position_events=tuple(
            (table, row) for table in sorted(_POSITION_TABLES) for row in rows.get(table, ())
        ),
        torn_tails=tuple(collected.torn),
        unrecognised_files=tuple(collected.unrecognised),
    )


# -- the C1 views ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DecisionView:
    """C1 ``DecisionRecord``: ``instrument`` is ``instrument_id``, ``ts_init`` is ``ts_ns``, and the
    frame and forecast references are the C1 strings."""

    schema: str
    decision_id: str
    family_id: str
    node_boot_id: str
    build_sha: str
    registry_seq: int
    drill: bool
    source: str
    kind: str
    reason: str
    eval_ns: int
    eval_seq: int
    wall_ns: int
    ts_ns: int
    station: str
    climate_day: str
    rung_id: str
    side: str
    instrument_id: str
    ask_px: str
    depth_ref: str
    quote_ref: str
    p_hat: str
    p_hat_raw: str
    p_lower: str
    p_upper: str
    ev_net: str
    margin: str
    forecast_input_ref: str
    artefact_sha256: str
    manifest_sha256: str


_DECISION_PASSTHROUGH: Final[tuple[str, ...]] = (
    "schema",
    "decision_id",
    "family_id",
    "node_boot_id",
    "build_sha",
    "registry_seq",
    "drill",
    "source",
    "kind",
    "reason",
    "eval_ns",
    "eval_seq",
    "wall_ns",
    "station",
    "climate_day",
    "rung_id",
    "side",
    "ask_px",
    "p_hat",
    "p_hat_raw",
    "p_lower",
    "p_upper",
    "ev_net",
    "margin",
    "artefact_sha256",
    "manifest_sha256",
)


@dataclass(frozen=True, slots=True)
class OrderLinkView:
    """C1 ``OrderLink``, one per streamed ``OrderInitialized``. ``side``, ``qty``, ``px`` and
    ``time_in_force`` are the exact ``str()`` forms ``intent_fingerprint`` consumes."""

    decision_id: str
    client_order_id: str
    venue_order_id_sha256: str
    instrument_id: str
    side: str
    qty: str
    px: str
    time_in_force: str
    intent_fingerprint: str
    ts_ns: int
    source: str


@dataclass(frozen=True, slots=True)
class LifecycleEventView:
    """C1 ``LifecycleEvent`` from an ``OrderFilled`` or an ``OrderEventRecord``."""

    event: str
    client_order_id: str
    trade_id: str
    qty: str
    px: str
    fee: str
    decision_id: str
    venue_order_id_sha256: str
    reason: str
    ts_ns: int
    source: str


@dataclass(frozen=True, slots=True)
class PositionMarkView:
    """C1 ``PositionMark``: ``net_qty`` is signed in the venue's convention (a NO holding counts
    as short YES), ``reconciliation_source`` is always ``node_belief``."""

    instrument_id: str
    leg: str
    net_qty: str
    mark_px: str
    reconciliation_source: str
    source: str
    ts_ns: int
    event_type: str


@dataclass(frozen=True, slots=True)
class C1View:
    family_id: str
    decisions: tuple[DecisionView, ...]
    order_links: tuple[OrderLinkView, ...]
    lifecycle_events: tuple[LifecycleEventView, ...]
    position_marks: tuple[PositionMarkView, ...]
    detector_events: tuple[Any, ...]


def _fingerprint(
    instrument_id: str, side: str, qty: str, px: str, time_in_force: str, client_order_id: str
) -> str:
    payload = _FINGERPRINT_SEP.join((instrument_id, side, qty, px, time_in_force, client_order_id))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def recompute_intent_fingerprint(link: OrderLinkView) -> str:
    """``intent_fingerprint`` (``submit_chain.py:242-253``) over the link's six stored forms."""
    return _fingerprint(
        link.instrument_id, link.side, link.qty, link.px, link.time_in_force, link.client_order_id
    )


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _decision_view(record: Any) -> DecisionView:
    passthrough = {name: getattr(record, name) for name in _DECISION_PASSTHROUGH}
    ref = frame_ref_of(record.frame_kind, record.instrument, record.frame_ts_event)
    return DecisionView(
        **passthrough,
        ts_ns=record.ts_init,
        instrument_id=record.instrument,
        depth_ref=ref if record.frame_kind == "depth10" else "",
        quote_ref=ref if record.frame_kind == "quote" else "",
        forecast_input_ref=forecast_ref_of(
            record.forecast_station,
            record.forecast_cycle_ns,
            record.forecast_available_at_ns,
        ),
    )


def _tags_of(row: NativeRow) -> list[str]:
    raw = row.get("tags")
    try:
        parsed = json.loads(raw) if raw else None
    except (TypeError, ValueError) as exc:
        raise CaptureProjectionError("order tags are not JSON") from exc
    if parsed is None:
        return []
    if not isinstance(parsed, list) or not all(isinstance(t, str) for t in parsed):
        raise CaptureProjectionError("order tags are not a list of strings")
    return parsed


def _tag_value(tags: Iterable[str], prefix: str) -> str | None:
    for tag in tags:
        if tag.startswith(prefix):
            return tag.removeprefix(prefix)
    return None


def _link_decision_id(tags: list[str], family_id: str, client_order_id: str) -> str:
    decision_id = _tag_value(tags, DECISION_ID_TAG_PREFIX)
    if decision_id is not None:
        return decision_id
    exit_values = [
        _tag_value(tags, prefix)
        for prefix in (
            EXIT_RULE_TAG_PREFIX,
            EXIT_POSITION_TAG_PREFIX,
            EXIT_FAMILY_TAG_PREFIX,
            EXIT_CLIENT_ORDER_ID_TAG_PREFIX,
        )
    ]
    if all(value is not None for value in exit_values):
        rule, position, family, coid = (str(v) for v in exit_values)
        return compute_exit_decision_id(rule, position, family, coid)
    return compute_orphan_decision_id(family_id, client_order_id)


def _option_price(row: NativeRow) -> str:
    try:
        options = json.loads(row["options"]) if row.get("options") else {}
    except (TypeError, ValueError) as exc:
        raise CaptureProjectionError("order options are not JSON") from exc
    price = options.get("price") if isinstance(options, dict) else None
    return "" if price is None else str(price)


def _enum_forms(row: NativeRow) -> tuple[str, str]:
    """``str(OrderSide)`` and ``str(TimeInForce)`` of the streamed names (WP0-R4).

    The native ``*_from_str`` parsers PANIC the interpreter (a Rust abort, not an exception) on an
    unknown name, so a name outside the closed member set is refused here first.
    """
    side, tif = row.get("order_side"), row.get("time_in_force")
    if side not in OrderSide.__members__ or tif not in TimeInForce.__members__:
        raise CaptureProjectionError("unknown order side or time in force name")
    return str(order_side_from_str(side)), str(time_in_force_from_str(tif))


def _venue_hashes(stream: CaptureStream) -> dict[str, str]:
    """client_order_id -> sha256 of the venue order id, from an Accepted record, else a fill."""
    hashes: dict[str, str] = {}
    for event in stream.order_events:
        if event.event_type == _ACCEPTED and event.venue_order_id_sha256:
            hashes.setdefault(event.client_order_id, event.venue_order_id_sha256)
    for row in stream.order_filled:
        hashes.setdefault(row["client_order_id"], _sha256(row["venue_order_id"]))
    return hashes


def _order_links(stream: CaptureStream, family_id: str) -> tuple[OrderLinkView, ...]:
    hashes = _venue_hashes(stream)
    links: list[OrderLinkView] = []
    for row in stream.order_initialized:
        client_order_id = row["client_order_id"]
        side, tif = _enum_forms(row)
        instrument_id, qty, px = row["instrument_id"], row["quantity"], _option_price(row)
        links.append(
            OrderLinkView(
                decision_id=_link_decision_id(_tags_of(row), family_id, client_order_id),
                client_order_id=client_order_id,
                venue_order_id_sha256=hashes.get(client_order_id, ""),
                instrument_id=instrument_id,
                side=side,
                qty=qty,
                px=px,
                time_in_force=tif,
                intent_fingerprint=_fingerprint(instrument_id, side, qty, px, tif, client_order_id),
                ts_ns=row["ts_init"],
                source=stream.source,
            )
        )
    return tuple(links)


def _event_name(event_type: str) -> str:
    return event_type.removeprefix(_ORDER_PREFIX).upper()


def _lifecycle_events(stream: CaptureStream) -> tuple[LifecycleEventView, ...]:
    events = [
        LifecycleEventView(
            event=_event_name(e.event_type),
            client_order_id=e.client_order_id,
            trade_id="",
            qty="",
            px="",
            fee="",
            decision_id=e.decision_id,
            venue_order_id_sha256=e.venue_order_id_sha256,
            reason=e.reason,
            ts_ns=e.ts_event,
            source=e.source,
        )
        for e in stream.order_events
    ]
    events.extend(
        LifecycleEventView(
            event=_FILLED,
            client_order_id=row["client_order_id"],
            trade_id=row["trade_id"],
            qty=row["last_qty"],
            px=row["last_px"],
            fee=str(row["commission"]).split()[0],
            decision_id="",
            venue_order_id_sha256=_sha256(row["venue_order_id"]),
            reason="",
            ts_ns=row["ts_event"],
            source=stream.source,
        )
        for row in stream.order_filled
    )
    return tuple(events)


def _signed(value: float, leg: str) -> str:
    quantity = Decimal(repr(value))
    if leg == _NO and quantity != 0:
        quantity = -quantity
    return str(quantity)


def _position_marks(stream: CaptureStream) -> tuple[PositionMarkView, ...]:
    marks: list[PositionMarkView] = []
    for table, row in stream.position_events:
        instrument_id = row["instrument_id"]
        leg = leg_of_symbol(symbol_of_instrument_id(instrument_id))
        marks.append(
            PositionMarkView(
                instrument_id=instrument_id,
                leg=leg,
                net_qty=_signed(row["signed_qty"], leg),
                mark_px=str(row["last_px"]),
                reconciliation_source=_NODE_BELIEF,
                source=stream.source,
                ts_ns=row["ts_closed"] if table == "position_closed" else row["ts_event"],
                event_type=table,
            )
        )
    return tuple(marks)


def project_c1(stream: CaptureStream, *, family_id: str = "") -> C1View:
    """The C1 logical records of one boot. ``family_id`` seeds the orphan id of an untagged order;
    when empty it is the first non-empty ``family_id`` among the stream's own decisions."""
    family = family_id or next((d.family_id for d in stream.decisions if d.family_id), "")
    return C1View(
        family_id=family,
        decisions=tuple(_decision_view(d) for d in stream.decisions),
        order_links=_order_links(stream, family),
        lifecycle_events=_lifecycle_events(stream),
        position_marks=_position_marks(stream),
        detector_events=tuple(stream.detector_events),
    )


# -- joins and resolvers -----------------------------------------------------------------------


class JoinStatus(StrEnum):
    JOINED = "joined"
    NO_LINK = "no_link"
    LINK_CONFLICT = "link_conflict"
    UNTAGGED_ORDER = "untagged_order"
    NO_DECISION = "no_decision"


@dataclass(frozen=True, slots=True)
class FillJoin:
    fill: LifecycleEventView
    link: OrderLinkView | None
    decision: DecisionView | None
    status: JoinStatus


def join_fills_to_decisions(
    view: C1View, fills: Iterable[LifecycleEventView]
) -> tuple[FillJoin, ...]:
    """Pure. Each fill joins, through its ``client_order_id``, to the OrderLink and then to the
    DecisionRecord named by the link's ``decision_id``. The decision is the STORED view, so its
    ``eval_ns`` and ``eval_seq`` are never recomputed."""
    links: dict[str, list[OrderLinkView]] = {}
    for link in view.order_links:
        links.setdefault(link.client_order_id, []).append(link)
    decisions = {d.decision_id: d for d in view.decisions}
    return tuple(_join_one(fill, links, decisions, view.family_id) for fill in fills)


def _join_one(
    fill: LifecycleEventView,
    links: Mapping[str, list[OrderLinkView]],
    decisions: Mapping[str, DecisionView],
    family_id: str,
) -> FillJoin:
    candidates = links.get(fill.client_order_id, [])
    if not candidates:
        return FillJoin(fill, None, None, JoinStatus.NO_LINK)
    link = candidates[0]
    if len({c.decision_id for c in candidates}) > 1:
        return FillJoin(fill, link, None, JoinStatus.LINK_CONFLICT)
    if link.decision_id == compute_orphan_decision_id(family_id, link.client_order_id):
        return FillJoin(fill, link, None, JoinStatus.UNTAGGED_ORDER)
    decision = decisions.get(link.decision_id)
    if decision is None:
        return FillJoin(fill, link, None, JoinStatus.NO_DECISION)
    return FillJoin(fill, link, decision, JoinStatus.JOINED)


class FrameSource(StrEnum):
    COPY = "copy"
    TAPE = "tape"
    UNRESOLVED = "unresolved"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class FrameResolution:
    source: FrameSource
    body: Mapping[str, Any] | None = None


#: ``(frame_kind, instrument, frame_ts_event) -> the recorder catalog's row, or None``. The caller
#: owns catalog access (``order_book_depths`` for ``depth10``, ``quote_tick`` for ``quote``).
TapeLookup = Callable[[str, str, int], Mapping[str, Any] | None]


def resolve_frame_ref(
    stream: CaptureStream,
    decision_id: str,
    frame_ref: str,
    *,
    tape: TapeLookup | None = None,
) -> FrameResolution:
    """Resolve a decision's frame reference, in this order only (plan r12 section 3.3.1):

    1. a ``FrameCopy`` in the same boot's stream with the same ``decision_id``;
    2. the recorder catalog, through ``tape``;
    3. otherwise ``UNRESOLVED``.

    An empty reference (an Exit cites no frame) is ``NONE``; a malformed one is ``UNRESOLVED``.
    """
    if not frame_ref:
        return FrameResolution(FrameSource.NONE)
    parsed = parse_frame_ref(frame_ref)
    if parsed is None:
        return FrameResolution(FrameSource.UNRESOLVED)
    for copy in stream.frame_copies:
        if copy.decision_id == decision_id:
            return FrameResolution(FrameSource.COPY, copy.frame_body)
    if tape is not None:
        row = tape(*parsed)
        if row is not None:
            return FrameResolution(FrameSource.TAPE, row)
    return FrameResolution(FrameSource.UNRESOLVED)
