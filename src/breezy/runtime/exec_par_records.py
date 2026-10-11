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
* ``force_k1``                 flag ``{reason, ts_ns, set_by}`` or, once
  cleared, the tombstone ``{cleared_ts_ns}``

BG-1b counter rows (event-sourced; the id in each key must equal the row's own
field; ``day`` is the climate-day label of the ARM time, I2):

* ``order/<client_order_id>``  posted entry + the durable DECISION ASK
* ``denial/<client_order_id>`` and ``ambiguous/<intent_id>``
* ``fill/<trade_id>``          per-fill slippage, realized and unrounded fees
* ``openflag/<station_day>``   value-free "open cost over fraction" flag
* ``window/<day>/<start_ns>``  per 5 s window order count and notional
* ``gappy/<day>``              gappy-day mark

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
    "EXEC_PAR_PREFIX",
    "AmbiguousRow",
    "Amendment",
    "CleanupDemotion",
    "DenialRow",
    "EpochRow",
    "ExcludedDay",
    "ExecParRecordError",
    "FillRow",
    "ForceK1Cleared",
    "ForceK1Flag",
    "ForceK1Kind",
    "ForceK1State",
    "SettledPnlDay",
    "GappyMark",
    "OpenCostFlag",
    "OrderAnchor",
    "StageEvalDry",
    "StageReset",
    "StopVerdict",
    "WindowPeak",
    "decode_excluded_days",
    "decode_force_k1_flag",
    "decode_pointer",
    "decode_record",
    "encode_excluded_days",
    "encode_force_k1_tombstone",
    "encode_pointer",
    "encode_record",
]

EXEC_PAR_PREFIX: Final[str] = "exec/polymarket_us/exec_par/"
_VERSION: Final[int] = 1


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


@dataclass(frozen=True, slots=True)
class DenialRow:
    client_order_id: str
    reason: str
    day: str
    arm_ns: int


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


@dataclass(frozen=True, slots=True)
class GappyMark:
    day: str
    cause: str
    ts_ns: int
    cleared_ts: int | None


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
    OrderAnchor: {
        "client_order_id": "str",
        "slug": "str",
        "day": "str",
        "arm_ns": "int",
        "decision_ask": "str",
        "qty": "str",
        "notional": "str",
        "window_start_ns": "int",
    },
    DenialRow: {"client_order_id": "str", "reason": "str", "day": "str", "arm_ns": "int"},
    AmbiguousRow: {
        "intent_id": "str",
        "source": "str",
        "day": "str",
        "arm_ns": "int",
        "attribution": "str",
        "ts_ns": "int",
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
    },
    OpenCostFlag: {"station_day": "str", "day": "str", "exceeded": "bool", "ts_ns": "int"},
    WindowPeak: {"day": "str", "window_start_ns": "int", "orders": "int", "notional": "str"},
    GappyMark: {"day": "str", "cause": "str", "ts_ns": "int", "cleared_ts": "int?"},
}

_DAY_RE: Final = re.compile(r"\d{4}-\d{2}-\d{2}")
_DEC_RE: Final = re.compile(r"-?(0|[1-9]\d*)(\.\d*[1-9])?")

T = TypeVar("T")


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
