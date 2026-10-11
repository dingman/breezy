"""Pure codec for the EXEC-PAR D-PREREG durable records (BG-1a; inert).

No I/O and no latch dependency. Every record is canonical sorted-key JSON
``{"v": 1, <fields>}``; decoding is strict (exact key set, exact types, no
bool-as-int, no empty required strings) and every defect raises
:class:`ExecParRecordError`. Nothing ever returns a default for garbled bytes.

Store keys (all under ``exec/polymarket_us/exec_par/``; PROPOSED by spec
D-PREREG 1, 1b, 10, 10a, r4.1 K9, r4.3 M3, r4.4 N4):

* ``stage_reset``              latest floor record ``{ts, cause, halt_ts}``
* ``excluded_days``            one list record of ``{day, cause, ts}``
* ``epoch/<boot_ts_ns>``       ``{commit_sha, effective_k, force_reason,
  boot_ts, stop_ts}``; ``epoch/latest`` pointer
* ``amendment/<ts_ns>``        ``{ts_ns, commit_sha, note}``
* ``stage_eval_dry``           latest ``{verdict, input_complete, ts}``
* ``force_k1_cleared``         latest ``{ts, halt_ts, incident_report}``
* ``stop_verdict/<ts_ns>``     ``{reason, ts_ns}``; ``stop_verdict/latest``
* ``cleanup_demotion/<ts_ns>`` ``{from_k, to_k, ts_ns, reason}``;
  ``cleanup_demotion/latest`` pointer
* ``settled_pnl/<YYYY-MM-DD>`` BG-1c per-arm-day settled-P&L row (overwritten on
  each recompute; pnl is a canonical decimal STRING, never a float)
* ``settled_pnl_floor_stub/<label>`` BG-5c N-A: a floor label's POST-floor settled-P&L row
* ``settled_pnl_revision/<label>/<ts_ns>`` (``.../stub`` for a stub row) BG-5c WP-D audit row that
  must exist before a promoted CLI revision may replace a row non-monotonically
* ``settled_pnl_basis/<label>`` (``.../stub`` for a stub row) BG-5c WP-D: the CLI-product tokens a
  settled-P&L row was built from; a different token for the same station-day is a revision, even
  one promoted while the node was down
* ``force_k1``                 flag ``{reason, ts_ns, set_by}`` or, once
  cleared, the tombstone ``{cleared_ts_ns}``
* ``day_convention``           ``{"v": 2}`` (BG-5c R1): per-station standard-time ``entry_day``;
  written by the first K>1 boot, any other ``v`` refuses K>1

BG-1b counter rows (event-sourced; the id in each key must equal the row's own
field; ``day`` is the climate-day label of the ARM time, I2, and equals
``entry_day(station, arm_ns)`` of the row's own ``station``, BG-5c R1):

* ``order/<client_order_id>``  posted entry + the durable DECISION ASK
* ``denial/<day>/<client_order_id>`` and ``ambiguous/<day>/<intent_id>``
* ``fill/<day>/<trade_id>``    per-fill slippage, realized and unrounded fees
* ``openflag/<day>/<station_day>`` value-free "open cost over fraction" flag
* ``window/<day>/<start_ns>``  per 5 s window order count and notional
* ``gappy/<day>``              gappy-day mark
* ``lapse/<start_ns>/<end_ns>`` BG-5c R7.3 append-only lapse / unclean-shutdown span
  ``{start_ns, end_ns, kind, marked_ts}``; exclusive per (start, end), overlaps coexist (the
  heartbeat is ONE overwritten row, so it keeps no history); ``marked_ts`` is set once when its
  days are gappy-marked

BG-5b stage-evaluator rows (single writer = the node's loop thread, via the latch):

* ``look/<YYYY-MM-DD>``        promotion look ``{day, outcome, ts_ns}``; outcome is
  ``passed`` / ``failed`` / ``not_taken``; EXCLUSIVE per day (identical rewrite is a no-op)
* ``stage_eval/stamp``         ``{ts_ns, boot_ns}`` of the last healthy pass (r4 1a)
* ``stage_eval/liveness``      ``{stage_eval_last_start_ns, stage_eval_last_ok_ns}`` (N3)
* ``stage_eval/reconcile_phase`` ``{reconcile_start_ns, reconcile_ok_ns}`` (N3)
* ``stage_eval/report``        latest ``{ts_ns, verdict, reason, report_json}``; the report
  carries counts, ratios and flags only
* ``counts_delta/<day>``       BG-1d rebuild: SIGNED deltas (durable minus the BG-1b row scan at
  rebuild time) added to the scan, so later events and retried rows keep counting
* ``rebuild/<day>``            pending BG-1d rebuild note; retired to ``rebuild_log/<day>/<ts_ns>``

The store has only ``get``/``set``, so each ``<ts_ns>`` family keeps a
``latest`` pointer ``{"v":1,"ts_ns":N}`` written AFTER the row.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Final, TypeVar

from breezy.runtime.submit_intent_slots import SlotTableError, canonical_text

__all__ = [
    "AMENDMENT_KEY_PREFIX",
    "DAY_CONVENTION_KEY",
    "DAY_CONVENTION_VERSION",
    "EPOCH_KEY_PREFIX",
    "EXEC_PAR_PREFIX",
    "LAPSE_KEY_PREFIX",
    "AmbiguousRow",
    "Amendment",
    "CleanupDemotion",
    "DayCountsDelta",
    "DenialRow",
    "EpochRow",
    "ExcludedDay",
    "ExecParRecordError",
    "FillRow",
    "ForceK1Cleared",
    "ForceK1Flag",
    "ForceK1Kind",
    "ForceK1State",
    "GappyMark",
    "HeartbeatLapse",
    "LookRow",
    "OpenCostFlag",
    "OrderAnchor",
    "RebuildRow",
    "ReconcilePhase",
    "SettledPnlBasis",
    "SettledPnlDay",
    "SettledPnlRevision",
    "StageEvalDry",
    "StageEvalLiveness",
    "StageEvalStamp",
    "StageReportDoc",
    "StageReset",
    "StopVerdict",
    "WindowPeak",
    "canonical_decimal",
    "decode_day_convention",
    "decode_excluded_days",
    "decode_force_k1_flag",
    "decode_pointer",
    "decode_record",
    "encode_day_convention",
    "encode_excluded_days",
    "encode_force_k1_tombstone",
    "encode_pointer",
    "encode_record",
]

EXEC_PAR_PREFIX: Final[str] = "exec/polymarket_us/exec_par/"
#: Key layout of the append-style rows; the one owner, shared by the latch writers
#: and the read-only ledger reader.
EPOCH_KEY_PREFIX: Final[str] = EXEC_PAR_PREFIX + "epoch/"
AMENDMENT_KEY_PREFIX: Final[str] = EXEC_PAR_PREFIX + "amendment/"
#: BG-5c R7.3: append-only lapse / unclean-shutdown spans (``lapse/<start_ns>/<end_ns>``).
LAPSE_KEY_PREFIX: Final[str] = EXEC_PAR_PREFIX + "lapse/"
_VERSION: Final[int] = 1
#: ``exec_par/day_convention`` row version: 2 = per-station standard-time ``entry_day`` (BG-5c R1).
DAY_CONVENTION_VERSION: Final[int] = 2
DAY_CONVENTION_KEY: Final[str] = EXEC_PAR_PREFIX + "day_convention"


class ExecParRecordError(SlotTableError):
    """A durable EXEC-PAR record is structurally invalid (fail closed)."""


@dataclass(frozen=True, slots=True)
class StageReset:
    ts: int
    cause: str
    halt_ts: int | None


@dataclass(frozen=True, slots=True)
class ExcludedDay:
    day: str
    cause: str
    ts: int


@dataclass(frozen=True, slots=True)
class EpochRow:
    commit_sha: str
    effective_k: int
    force_reason: str | None
    boot_ts: int
    stop_ts: int | None = None


@dataclass(frozen=True, slots=True)
class Amendment:
    ts_ns: int
    commit_sha: str
    note: str


@dataclass(frozen=True, slots=True)
class StageEvalDry:
    verdict: str
    input_complete: bool
    ts: int


@dataclass(frozen=True, slots=True)
class ForceK1Cleared:
    ts: int
    halt_ts: int
    incident_report: str


@dataclass(frozen=True, slots=True)
class StopVerdict:
    reason: str
    ts_ns: int


@dataclass(frozen=True, slots=True)
class CleanupDemotion:
    from_k: int
    to_k: int
    ts_ns: int
    reason: str


@dataclass(frozen=True, slots=True)
class ForceK1Flag:
    reason: str
    ts_ns: int
    set_by: str


@dataclass(frozen=True, slots=True)
class SettledPnlRevision:
    """BG-5c WP-D audit: a promoted CLI revision replaced a settled-P&L row (scope day/stub)."""

    day: str
    ts_ns: int
    scope: str
    old_pnl: str
    new_pnl: str
    old_entries: int
    new_entries: int
    cause: str
    product_sha256: str

    def __post_init__(self) -> None:
        if self.scope not in ("day", "stub"):
            raise ExecParRecordError("revision scope")


@dataclass(frozen=True, slots=True)
class SettledPnlBasis:
    """BG-5c WP-D: the final CLI tokens (``station@day=token;...``) a row was built from."""

    day: str
    scope: str
    basis: str

    def __post_init__(self) -> None:
        if self.scope not in ("day", "stub"):
            raise ExecParRecordError("basis scope")


@dataclass(frozen=True, slots=True)
class SettledPnlDay:
    """BG-1c: one arm-time climate day's settled P&L (spec 10a, 15). Currency stays local."""

    day: str
    pnl: str
    settled_entries: int
    ambiguous_entries: int
    unsettled_entries: int
    overdue_entries: int = 0
    fee_unreconciled_entries: int = 0
    #: Sum of the fees CHARGED to the unreconciled entries (floor-or-recorded); bounds the
    #: pnl rise a later reconciliation to a lower recorded fee may cause.
    fee_floor_total: str = "0"

    @property
    def fee_floor_decimal(self) -> Decimal:
        return Decimal(self.fee_floor_total)

    @property
    def total_entries(self) -> int:
        return (
            self.settled_entries
            + self.ambiguous_entries
            + self.unsettled_entries
            + self.overdue_entries
        )

    @property
    def pnl_decimal(self) -> Decimal:
        return Decimal(self.pnl)


@dataclass(frozen=True, slots=True)
class OrderAnchor:
    """A posted entry. ``arm_ns`` is the slot ``created_ns``; ``decision_ask`` a Decimal string."""

    client_order_id: str
    slug: str
    day: str
    arm_ns: int
    decision_ask: str
    qty: str
    notional: str
    window_start_ns: int
    #: How ``arm_ns`` was obtained: ``slot_join`` (the armed slot, joined by coid) or
    #: ``event_time`` (the ``OrderSubmitted`` ``ts_event``; today's only route).
    attribution: str
    #: The entry's station: ``day`` is ``entry_day(station, arm_ns)`` (BG-5c R1).
    station: str


@dataclass(frozen=True, slots=True)
class DenialRow:
    client_order_id: str
    reason: str
    day: str
    arm_ns: int
    station: str


@dataclass(frozen=True, slots=True)
class AmbiguousRow:
    """An entry that was ever AMBIGUOUS, keyed by intent id (counted once, kept on resolution).

    ``attribution`` is ``slot`` (open slot), ``history`` (retired slot) or
    ``unattributed`` (neither found; ``day`` is then ``unattributed``).
    """

    intent_id: str
    source: str
    day: str
    arm_ns: int
    attribution: str
    ts_ns: int
    #: The mark's station, or ``unattributed`` when neither slot nor history was found.
    station: str


@dataclass(frozen=True, slots=True)
class FillRow:
    """One fill, Decimal strings: slippage = px - decision_ask; fee_exact is unrounded."""

    trade_id: str
    client_order_id: str
    day: str
    arm_ns: int
    qty: str
    px: str
    decision_ask: str
    slippage: str
    fee_realized: str
    fee_exact: str
    fee_theta: str
    station: str


@dataclass(frozen=True, slots=True)
class OpenCostFlag:
    station_day: str
    day: str
    exceeded: bool
    ts_ns: int


@dataclass(frozen=True, slots=True)
class WindowPeak:
    day: str
    window_start_ns: int
    orders: int
    notional: str
    #: Comma-joined client order ids counted in this window (idempotent replay).
    coids: str


@dataclass(frozen=True, slots=True)
class GappyMark:
    day: str
    cause: str
    ts_ns: int
    cleared_ts: int | None


@dataclass(frozen=True, slots=True)
class HeartbeatLapse:
    """BG-5c R7.3: one span the node was not provably healthy (``kind`` is a ``GapKind`` value).

    Append-only: ``(start_ns, end_ns)`` keys the row and the span never changes. ``marked_ts`` is
    stamped once when every governed open day the span overlaps carries its gappy mark, so a
    later rebuild that deletes a mark is never undone by re-marking a handled span.
    """

    start_ns: int
    end_ns: int
    kind: str
    marked_ts: int | None = None


@dataclass(frozen=True, slots=True)
class LookRow:
    """BG-5b: one recorded promotion look; ``outcome`` is passed / failed / not_taken."""

    day: str
    outcome: str
    ts_ns: int


@dataclass(frozen=True, slots=True)
class StageEvalStamp:
    """r4 1a stamp: the last healthy pass time and the latch ``boot_ns`` it ran under."""

    ts_ns: int
    boot_ns: int


@dataclass(frozen=True, slots=True)
class StageEvalLiveness:
    """N3 evaluate-phase liveness; ``None`` until the first pass starts / completes."""

    stage_eval_last_start_ns: int | None
    stage_eval_last_ok_ns: int | None


@dataclass(frozen=True, slots=True)
class ReconcilePhase:
    """N3 reconcile-phase liveness (``reconcile_ok_ns`` is ``None`` while it runs)."""

    reconcile_start_ns: int
    reconcile_ok_ns: int | None


@dataclass(frozen=True, slots=True)
class StageReportDoc:
    """The latest stage report (counts, ratios and flags only; ``report_json`` is canonical)."""

    ts_ns: int
    verdict: str
    reason: str | None
    report_json: str | None


@dataclass(frozen=True, slots=True)
class DayCountsDelta:
    """BG-1d rebuild adjustment for a day: signed counts and a signed canonical decimal spend."""

    day: str
    posted_entries: int
    ambiguous: int
    fills: int
    spend: str


@dataclass(frozen=True, slots=True)
class RebuildRow:
    """A pending BG-1d rebuild note: why (comma-joined kinds, never empty) and what was set."""

    day: str
    ts_ns: int
    mismatch_kinds: str
    posted_entries: int
    ambiguous: int
    fills: int
    spend: str


class ForceK1Kind(Enum):
    """Reading of the durable force-K1 flag. UNREADABLE must be treated as SET."""

    SET = "set"
    CLEARED = "cleared"
    UNREADABLE = "unreadable"


@dataclass(frozen=True, slots=True)
class ForceK1State:
    """Tri-state flag reading; ``record`` is present only for SET.

    CLEARED means no active flag: never set, or overwritten by a tombstone.
    """

    kind: ForceK1Kind
    record: ForceK1Flag | None = None


#: field name -> kind, per record type. A ``?`` suffix marks a nullable field.
_SPECS: Final[dict[type, dict[str, str]]] = {
    StageReset: {"ts": "int", "cause": "str", "halt_ts": "int?"},
    ExcludedDay: {"day": "str", "cause": "str", "ts": "int"},
    EpochRow: {
        "commit_sha": "str",
        "effective_k": "int",
        "force_reason": "str?",
        "boot_ts": "int",
        "stop_ts": "int?",
    },
    Amendment: {"ts_ns": "int", "commit_sha": "str", "note": "str"},
    StageEvalDry: {"verdict": "str", "input_complete": "bool", "ts": "int"},
    ForceK1Cleared: {"ts": "int", "halt_ts": "int", "incident_report": "str"},
    StopVerdict: {"reason": "str", "ts_ns": "int"},
    CleanupDemotion: {"from_k": "int", "to_k": "int", "ts_ns": "int", "reason": "str"},
    ForceK1Flag: {"reason": "str", "ts_ns": "int", "set_by": "str"},
    SettledPnlDay: {
        "day": "day",
        "pnl": "dec",
        "settled_entries": "count",
        "ambiguous_entries": "count",
        "unsettled_entries": "count",
        "overdue_entries": "count",
        "fee_unreconciled_entries": "count",
        "fee_floor_total": "dec",
    },
    SettledPnlBasis: {"day": "day", "scope": "str", "basis": "str"},
    SettledPnlRevision: {
        "day": "day",
        "ts_ns": "int",
        "scope": "str",
        "old_pnl": "dec",
        "new_pnl": "dec",
        "old_entries": "count",
        "new_entries": "count",
        "cause": "str",
        "product_sha256": "str",
    },
    OrderAnchor: {
        "client_order_id": "str",
        "slug": "str",
        "day": "str",
        "arm_ns": "int",
        "decision_ask": "str",
        "qty": "str",
        "notional": "str",
        "window_start_ns": "int",
        "attribution": "str",
        "station": "str",
    },
    DenialRow: {
        "client_order_id": "str",
        "reason": "str",
        "day": "str",
        "arm_ns": "int",
        "station": "str",
    },
    AmbiguousRow: {
        "intent_id": "str",
        "source": "str",
        "day": "str",
        "arm_ns": "int",
        "attribution": "str",
        "ts_ns": "int",
        "station": "str",
    },
    FillRow: {
        "trade_id": "str",
        "client_order_id": "str",
        "day": "str",
        "arm_ns": "int",
        "qty": "str",
        "px": "str",
        "decision_ask": "str",
        "slippage": "str",
        "fee_realized": "str",
        "fee_exact": "str",
        "fee_theta": "str",
        "station": "str",
    },
    OpenCostFlag: {"station_day": "str", "day": "str", "exceeded": "bool", "ts_ns": "int"},
    WindowPeak: {
        "day": "str",
        "window_start_ns": "int",
        "orders": "int",
        "notional": "str",
        "coids": "str",
    },
    GappyMark: {"day": "str", "cause": "str", "ts_ns": "int", "cleared_ts": "int?"},
    HeartbeatLapse: {"start_ns": "int", "end_ns": "int", "kind": "str", "marked_ts": "int?"},
    LookRow: {"day": "day", "outcome": "str", "ts_ns": "int"},
    StageEvalStamp: {"ts_ns": "int", "boot_ns": "int"},
    StageEvalLiveness: {"stage_eval_last_start_ns": "int?", "stage_eval_last_ok_ns": "int?"},
    ReconcilePhase: {"reconcile_start_ns": "int", "reconcile_ok_ns": "int?"},
    StageReportDoc: {
        "ts_ns": "int",
        "verdict": "str",
        "reason": "str?",
        "report_json": "str?",
    },
    DayCountsDelta: {
        "day": "day",
        "posted_entries": "int",
        "ambiguous": "int",
        "fills": "int",
        "spend": "dec",
    },
    RebuildRow: {
        "day": "day",
        "ts_ns": "int",
        "mismatch_kinds": "str",
        "posted_entries": "count",
        "ambiguous": "count",
        "fills": "count",
        "spend": "dec",
    },
}

_DAY_RE: Final = re.compile(r"\d{4}-\d{2}-\d{2}")
_DEC_RE: Final = re.compile(r"-?(0|[1-9]\d*)(\.\d*[1-9])?")

T = TypeVar("T")


def canonical_decimal(value: Decimal) -> str:
    """Plain, exponent-free decimal text with no trailing zeros (the ``dec`` field form)."""
    if not value.is_finite():
        raise ValueError("non-finite decimal")
    return "0" if value == 0 else format(value.normalize(), "f")


def _is_canonical_decimal(value: str) -> bool:
    """Plain decimal text that is its own canonical form (no exponent, no ``-0``)."""
    return _DEC_RE.fullmatch(value) is not None and value != "-0"


def _check(value: object, kind: str) -> object:
    base = kind.rstrip("?")
    if value is None:
        if kind.endswith("?"):
            return None
        raise ExecParRecordError("null in a required field")
    if base == "int" and isinstance(value, int) and not isinstance(value, bool):
        return value
    if base == "str" and isinstance(value, str) and value:
        return value
    if base == "count" and isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    if base == "day" and isinstance(value, str) and _DAY_RE.fullmatch(value):
        return value
    if base == "dec" and isinstance(value, str) and _is_canonical_decimal(value):
        return value
    if base == "bool" and isinstance(value, bool):
        return value
    raise ExecParRecordError(f"field is not a valid {base}")


def _json_object(raw: bytes) -> dict[str, object]:
    try:
        decoded: object = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise ExecParRecordError("not UTF-8 JSON") from None
    if not isinstance(decoded, dict):
        raise ExecParRecordError("not a JSON object")
    version = decoded.get("v")
    if isinstance(version, bool) or version != _VERSION:
        raise ExecParRecordError("record version")
    return decoded


def _fields_from(payload: dict[str, object], spec: dict[str, str]) -> dict[str, object]:
    if set(payload) != {"v", *spec}:
        raise ExecParRecordError("record key set")
    return {name: _check(payload[name], kind) for name, kind in spec.items()}


def encode_record(record: object) -> bytes:
    """Canonical bytes of one record; a bad field raises, never coerces."""
    spec = _SPECS.get(type(record))
    if spec is None:
        raise ExecParRecordError("unknown record type")
    body = {name: _check(getattr(record, name), kind) for name, kind in spec.items()}
    return canonical_text({"v": _VERSION, **body})


def decode_record(factory: Callable[..., T], raw: bytes) -> T:
    """Strict decode of ``raw`` into ``factory`` (one of the record classes)."""
    spec = _SPECS.get(factory) if isinstance(factory, type) else None
    if spec is None:
        raise ExecParRecordError("unknown record type")
    return factory(**_fields_from(_json_object(raw), spec))


def encode_pointer(ts_ns: int) -> bytes:
    return canonical_text({"v": _VERSION, "ts_ns": _check(ts_ns, "int")})


def decode_pointer(raw: bytes) -> int:
    value = _fields_from(_json_object(raw), {"ts_ns": "int"})["ts_ns"]
    if not isinstance(value, int):
        raise ExecParRecordError("pointer")
    return value


def encode_excluded_days(days: tuple[ExcludedDay, ...]) -> bytes:
    """One list record; rows sorted by ``day`` so the bytes are deterministic."""
    rows = [
        {name: _check(getattr(d, name), kind) for name, kind in _SPECS[ExcludedDay].items()}
        for d in sorted(days, key=lambda d: d.day)
    ]
    return canonical_text({"v": _VERSION, "days": rows})


def decode_excluded_days(raw: bytes) -> tuple[ExcludedDay, ...]:
    payload = _json_object(raw)
    rows = payload.get("days")
    if set(payload) != {"v", "days"} or not isinstance(rows, list):
        raise ExecParRecordError("excluded_days shape")
    out: list[ExcludedDay] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ExecParRecordError("excluded_days row")
        if "v" in row:
            raise ExecParRecordError("excluded_days row carries its own version")
        keyed: dict[str, object] = {"v": _VERSION, **row}
        out.append(decode_record(ExcludedDay, canonical_text(keyed)))
    if len({d.day for d in out}) != len(out):
        raise ExecParRecordError("excluded_days duplicate day")
    return tuple(out)


def encode_day_convention() -> bytes:
    """The ``exec_par/day_convention`` row: ``{"v": 2}`` (v1 was the station-less UTC-label era)."""
    return canonical_text({"v": DAY_CONVENTION_VERSION})


def decode_day_convention(raw: bytes) -> int:
    """The stored convention version. Strict shape; a foreign version is RETURNED, not hidden.

    The caller (the boot check) refuses K>1 on any version other than
    :data:`DAY_CONVENTION_VERSION`.
    """
    try:
        decoded: object = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise ExecParRecordError("not UTF-8 JSON") from None
    if not isinstance(decoded, dict) or set(decoded) != {"v"}:
        raise ExecParRecordError("day_convention shape")
    version = decoded["v"]
    if isinstance(version, bool) or not isinstance(version, int):
        raise ExecParRecordError("day_convention version")
    return version


def encode_force_k1_tombstone(cleared_ts_ns: int) -> bytes:
    return canonical_text({"v": _VERSION, "cleared_ts_ns": _check(cleared_ts_ns, "int")})


def decode_force_k1_flag(raw: bytes) -> ForceK1Flag | None:
    """The flag, or ``None`` for a cleared tombstone; anything else raises."""
    payload = _json_object(raw)
    if set(payload) == {"v", "cleared_ts_ns"}:
        cleared = _check(payload["cleared_ts_ns"], "int")
        if not isinstance(cleared, int) or cleared <= 0:
            raise ExecParRecordError("tombstone ts must be positive")
        return None
    return decode_record(ForceK1Flag, raw)
