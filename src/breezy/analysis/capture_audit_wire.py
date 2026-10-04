"""AUT-1 WP5 stage 2a: the ``capture_audit/v2`` wire format (plan r12 section 3.11.4; design S2-R3).

``audit_to_wire`` turns an ``AuditResult`` into a JSON-safe document (string enums, ISO day);
``audit_from_wire`` is its strict inverse, the only reader the live-proof unit and the stage-3 heal
use. Strict: a wrong schema, a missing or unexpected key, an unknown enum value, a bad day, a
``bool`` where an ``int`` is required or an unregistered metric raises ``AuditWireError``. Pure; no
I/O. A round trip is lossless (``tests/unit/test_capture_audit_model.py``).
"""

import datetime as dt
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Final

from breezy.analysis.capture_audit_model import (
    AUDIT_SCHEMA,
    AuditResult,
    DayStatus,
    FillAudit,
    Finding,
    Leg,
    LegOutcome,
    LegResult,
    MetricValue,
    TapeMark,
    WatchdogGap,
)

__all__ = ["AuditWireError", "audit_from_wire", "audit_to_wire"]


_TOP_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema",
        "day",
        "family_id",
        "status",
        "cause",
        "legs",
        "fills",
        "metrics",
        "watchdog_evidence_gaps",
        "duplicate_decision_lines",
        "tape_marks",
    }
)
_FINDING_KEYS: Final[frozenset[str]] = frozenset({"leg", "outcome", "cause", "subject", "detail"})
_LEG_KEYS: Final[frozenset[str]] = frozenset({"leg", "outcome", "findings", "metrics"})
_FILL_KEYS: Final[frozenset[str]] = frozenset(
    {"client_order_id", "trade_id", "family_id", "source", "drill", "attributed", "legs", "causes"}
)
_GAP_KEYS: Final[frozenset[str]] = frozenset({"unit", "invocation_id", "ts_ns", "cause"})
_MARK_KEYS: Final[frozenset[str]] = frozenset({"instrument_id", "hour", "best_ask", "net_qty"})


class AuditWireError(ValueError):
    """The document is not a valid ``capture_audit/v2`` audit."""


# -- to wire -----------------------------------------------------------------------------------


def _finding_to_wire(f: Finding) -> dict[str, Any]:
    return {
        "leg": f.leg.value,
        "outcome": f.outcome.value,
        "cause": f.cause,
        "subject": f.subject,
        "detail": f.detail,
    }


def _leg_to_wire(r: LegResult) -> dict[str, Any]:
    return {
        "leg": r.leg.value,
        "outcome": r.outcome.value,
        "findings": [_finding_to_wire(f) for f in r.findings],
        "metrics": dict(r.metrics),
    }


def _fill_to_wire(f: FillAudit) -> dict[str, Any]:
    return {
        "client_order_id": f.client_order_id,
        "trade_id": f.trade_id,
        "family_id": f.family_id,
        "source": f.source,
        "drill": f.drill,
        "attributed": f.attributed,
        "legs": [_leg_to_wire(r) for r in f.legs],
        "causes": list(f.causes),
    }


def audit_to_wire(result: AuditResult) -> dict[str, Any]:
    """The JSON-safe document of ``result`` (schema ``capture_audit/v2``)."""
    return {
        "schema": AUDIT_SCHEMA,
        "day": result.day.isoformat(),
        "family_id": result.family_id,
        "status": result.status.value,
        "cause": result.cause,
        "legs": [_leg_to_wire(r) for r in result.legs],
        "fills": [_fill_to_wire(f) for f in result.fills],
        "metrics": dict(result.metrics),
        "watchdog_evidence_gaps": [
            {"unit": g.unit, "invocation_id": g.invocation_id, "ts_ns": g.ts_ns, "cause": g.cause}
            for g in result.watchdog_evidence_gaps
        ],
        "duplicate_decision_lines": result.duplicate_decision_lines,
        "tape_marks": [
            {
                "instrument_id": m.instrument_id,
                "hour": m.hour,
                "best_ask": m.best_ask,
                "net_qty": m.net_qty,
            }
            for m in result.tape_marks
        ],
    }


# -- from wire ---------------------------------------------------------------------------------


def _mapping(value: object, keys: frozenset[str], what: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AuditWireError(f"{what} is not an object")
    missing = sorted(keys - set(value))
    if missing:
        raise AuditWireError(f"{what} is missing keys {missing}")
    extra = sorted(set(value) - keys)
    if extra:
        raise AuditWireError(f"{what} has unexpected keys {extra}")
    return value


def _str(value: object, what: str) -> str:
    if not isinstance(value, str):
        raise AuditWireError(f"{what} is not a string")
    return value


def _int(value: object, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AuditWireError(f"{what} is not an integer")
    return value


def _bool(value: object, what: str) -> bool:
    if not isinstance(value, bool):
        raise AuditWireError(f"{what} is not a boolean")
    return value


def _list(value: object, what: str) -> list[Any]:
    if not isinstance(value, list):
        raise AuditWireError(f"{what} is not an array")
    return value


def _enum[E: (Leg, LegOutcome, DayStatus)](cls: type[E], value: object, what: str) -> E:
    try:
        return cls(_str(value, what))
    except ValueError as exc:
        raise AuditWireError(f"{what} is not a known {cls.__name__}") from exc


def _metrics(value: object, what: str) -> Mapping[str, MetricValue]:
    if not isinstance(value, Mapping):
        raise AuditWireError(f"{what} is not an object")
    out: dict[str, MetricValue] = {}
    for key, item in value.items():
        valid = isinstance(item, int | float | str) and not isinstance(item, bool)
        if not isinstance(key, str) or not valid:
            raise AuditWireError(f"{what} has a bad entry")
        out[key] = item
    return MappingProxyType(out)


def _finding_from_wire(doc: object) -> Finding:
    m = _mapping(doc, _FINDING_KEYS, "finding")
    return Finding(
        _enum(Leg, m["leg"], "finding leg"),
        _enum(LegOutcome, m["outcome"], "finding outcome"),
        _str(m["cause"], "finding cause"),
        _str(m["subject"], "finding subject"),
        _str(m["detail"], "finding detail"),
    )


def _leg_from_wire(doc: object) -> LegResult:
    m = _mapping(doc, _LEG_KEYS, "leg")
    return LegResult(
        _enum(Leg, m["leg"], "leg"),
        _enum(LegOutcome, m["outcome"], "leg outcome"),
        tuple(_finding_from_wire(f) for f in _list(m["findings"], "leg findings")),
        _metrics(m["metrics"], "leg metrics"),
    )


def _fill_from_wire(doc: object) -> FillAudit:
    m = _mapping(doc, _FILL_KEYS, "fill")
    return FillAudit(
        client_order_id=_str(m["client_order_id"], "fill client_order_id"),
        trade_id=_str(m["trade_id"], "fill trade_id"),
        family_id=_str(m["family_id"], "fill family_id"),
        source=_str(m["source"], "fill source"),
        drill=_bool(m["drill"], "fill drill"),
        attributed=_bool(m["attributed"], "fill attributed"),
        legs=tuple(_leg_from_wire(r) for r in _list(m["legs"], "fill legs")),
        causes=tuple(_str(c, "fill cause") for c in _list(m["causes"], "fill causes")),
    )


def _gap_from_wire(doc: object) -> WatchdogGap:
    m = _mapping(doc, _GAP_KEYS, "watchdog gap")
    return WatchdogGap(
        _str(m["unit"], "gap unit"),
        _str(m["invocation_id"], "gap invocation_id"),
        _int(m["ts_ns"], "gap ts_ns"),
        _str(m["cause"], "gap cause"),
    )


def _mark_from_wire(doc: object) -> TapeMark:
    m = _mapping(doc, _MARK_KEYS, "tape mark")
    ask = m["best_ask"]
    if ask is not None and (isinstance(ask, bool) or not isinstance(ask, int | float)):
        raise AuditWireError("tape mark best_ask is not a number")
    return TapeMark(
        _str(m["instrument_id"], "mark instrument_id"),
        _int(m["hour"], "mark hour"),
        None if ask is None else float(ask),
        _int(m["net_qty"], "mark net_qty"),
    )


def audit_from_wire(doc: Mapping[str, Any]) -> AuditResult:
    """The ``AuditResult`` of a ``capture_audit/v2`` document. Raises ``AuditWireError``."""
    m = _mapping(doc, _TOP_KEYS, "audit")
    if m["schema"] != AUDIT_SCHEMA:
        raise AuditWireError(f"schema is not {AUDIT_SCHEMA}")
    try:
        day = dt.date.fromisoformat(_str(m["day"], "day"))
    except ValueError as exc:
        raise AuditWireError("day is not an ISO date") from exc
    try:
        return AuditResult(
            day=day,
            family_id=_str(m["family_id"], "family_id"),
            status=_enum(DayStatus, m["status"], "status"),
            cause=_str(m["cause"], "cause"),
            legs=tuple(_leg_from_wire(r) for r in _list(m["legs"], "legs")),
            fills=tuple(_fill_from_wire(f) for f in _list(m["fills"], "fills")),
            metrics=_metrics(m["metrics"], "metrics"),
            watchdog_evidence_gaps=tuple(
                _gap_from_wire(g) for g in _list(m["watchdog_evidence_gaps"], "watchdog gaps")
            ),
            duplicate_decision_lines=_int(
                m["duplicate_decision_lines"], "duplicate_decision_lines"
            ),
            tape_marks=tuple(_mark_from_wire(t) for t in _list(m["tape_marks"], "tape_marks")),
        )
    except ValueError as exc:  # an unregistered metric name (AuditResult.__post_init__)
        if isinstance(exc, AuditWireError):
            raise
        raise AuditWireError(str(exc)) from exc
