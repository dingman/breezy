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
* ``force_k1``                 flag ``{reason, ts_ns, set_by}`` or, once
  cleared, the tombstone ``{cleared_ts_ns}``

The store has only ``get``/``set``, so each ``<ts_ns>`` family keeps a
``latest`` pointer ``{"v":1,"ts_ns":N}`` written AFTER the row.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Final, TypeVar

from breezy.runtime.submit_intent_slots import SlotTableError, canonical_text

__all__ = [
    "EXEC_PAR_PREFIX",
    "Amendment",
    "CleanupDemotion",
    "EpochRow",
    "ExcludedDay",
    "ExecParRecordError",
    "ForceK1Cleared",
    "ForceK1Flag",
    "ForceK1Kind",
    "ForceK1State",
    "StageEvalDry",
    "StageReset",
    "StopVerdict",
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
}

T = TypeVar("T")


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
