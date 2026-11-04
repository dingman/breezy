"""AUD-04 admissible statistics for decisions; this module owns no capital.

E-TE1-a permits report-native admissible and residual statistics, never
accounting sums. Accounting counts in the report only withhold or disclose.
Vocabulary is copied and pinned to its producers to keep this reader stdlib-only.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum, auto
from pathlib import Path
from typing import Final

__all__ = [
    "DECISION_SCHEMA_VERSIONS",
    "INPUT_FRESHNESS_OK",
    "INPUT_FRESHNESS_STALE",
    "LABEL_GATE_REFUSES",
    "LABEL_GATE_SERVES",
    "MAX_DECISION_REPORT_AGE",
    "FamilyDecisionRefusal",
    "FamilyDecisionStats",
    "FamilyRefusalReason",
    "FamilyRestrictiveBlock",
    "RoiDecisionRefusal",
    "RoiDecisionRefusalReason",
    "RoiDecisionView",
    "read_roi_for_decision",
]

INPUT_FRESHNESS_OK: Final = "OK"
INPUT_FRESHNESS_STALE: Final = "STALE"
DECISION_SCHEMA_VERSIONS: Final = frozenset({6})
MAX_DECISION_REPORT_AGE: Final = timedelta(hours=26)
LABEL_GATE_SERVES: Final = frozenset({None, "GATED_UNSETTLED_CAPITAL"})
LABEL_GATE_REFUSES: Final = frozenset({"GATED_IDENTITY", "GATED_UNLABELLED_FQ"})
_UNKNOWN_FAMILY: Final = "UNKNOWN"


class _Malformed(ValueError):
    """A decision field does not have its declared representation."""


def _integer(raw: Mapping[str, object], key: str, *, signed: bool = False) -> int:
    value = raw.get(key)
    if type(value) is not int or (not signed and value < 0):
        raise _Malformed(key)
    return value


def _text(raw: Mapping[str, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise _Malformed(key)
    return value


def _decimal(raw: Mapping[str, object], key: str) -> Decimal:
    try:
        value = Decimal(_text(raw, key))
    except InvalidOperation as exc:
        raise _Malformed(key) from exc
    if not value.is_finite() or (value.is_zero() and value.is_signed()):
        raise _Malformed(key)
    return value


def _decimal_text(value: Decimal) -> str:
    return "0" if value.is_zero() else str(value)


@dataclass(frozen=True, slots=True, kw_only=True)
class FamilyDecisionStats:
    family_id: str
    n_admissible: int
    net_pnl: Decimal
    n_incomplete: int
    n_fee_unverified: int
    n_settlement_disagree: int
    n_residual: int
    n_residual_pending: int
    residual_pnl: Decimal
    n_residual_fee_unverified: int
    n_residual_settlement_disagree: int
    n_fills_attributed: int
    n_other_excluded: int

    def to_json(self) -> dict[str, object]:
        return {
            "family_id": self.family_id,
            "n_admissible": self.n_admissible,
            "net_pnl": _decimal_text(self.net_pnl),
            "n_incomplete": self.n_incomplete,
            "n_fee_unverified": self.n_fee_unverified,
            "n_settlement_disagree": self.n_settlement_disagree,
            "n_residual": self.n_residual,
            "n_residual_pending": self.n_residual_pending,
            "residual_pnl": _decimal_text(self.residual_pnl),
            "n_residual_fee_unverified": self.n_residual_fee_unverified,
            "n_residual_settlement_disagree": self.n_residual_settlement_disagree,
            "n_fills_attributed": self.n_fills_attributed,
            "n_other_excluded": self.n_other_excluded,
        }

    @classmethod
    def from_json(cls, raw: Mapping[str, object]) -> FamilyDecisionStats:
        return cls(
            family_id=_text(raw, "family_id"),
            n_admissible=_integer(raw, "n_admissible"),
            net_pnl=_decimal(raw, "net_pnl"),
            n_incomplete=_integer(raw, "n_incomplete"),
            n_fee_unverified=_integer(raw, "n_fee_unverified"),
            n_settlement_disagree=_integer(raw, "n_settlement_disagree"),
            n_residual=_integer(raw, "n_residual"),
            n_residual_pending=_integer(raw, "n_residual_pending"),
            residual_pnl=_decimal(raw, "residual_pnl"),
            n_residual_fee_unverified=_integer(raw, "n_residual_fee_unverified"),
            n_residual_settlement_disagree=_integer(raw, "n_residual_settlement_disagree"),
            n_fills_attributed=_integer(raw, "n_fills_attributed"),
            n_other_excluded=_integer(raw, "n_other_excluded", signed=True),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class FamilyRestrictiveBlock:
    """For restrictive LOSS_STOP use only, never eligibility or sizing."""

    net_pnl: Decimal
    n_residual: int
    n_residual_pending: int
    residual_pnl: Decimal
    n_residual_fee_unverified: int
    n_residual_settlement_disagree: int


class FamilyRefusalReason(StrEnum):
    FAMILY_FEE_UNVERIFIED = auto()
    FAMILY_SETTLEMENT_DISAGREE = auto()
    FAMILY_INCOMPLETE = auto()
    FAMILY_UNKNOWN = auto()
    FAMILY_PARTITION = auto()
    NOT_IN_REPORT = auto()


@dataclass(frozen=True, slots=True, kw_only=True)
class FamilyDecisionRefusal:
    family_id: str
    reason: FamilyRefusalReason
    restrictive: FamilyRestrictiveBlock | None


@dataclass(frozen=True, slots=True, kw_only=True)
class RoiDecisionView:
    schema_version: int
    generated_at: datetime
    settled_through: str
    roi_status: str
    label_gate_status: str | None
    days_since_newest_input: int | None
    input_freshness_status: str
    n_open_anchors_without_fill: int | None
    family_stats: tuple[FamilyDecisionStats, ...]
    family_refusals: tuple[FamilyDecisionRefusal, ...]

    def for_family(self, family_id: str) -> FamilyDecisionStats | FamilyDecisionRefusal:
        for row in self.family_stats:
            if row.family_id == family_id:
                return row
        for refusal in self.family_refusals:
            if refusal.family_id == family_id:
                return refusal
        return FamilyDecisionRefusal(
            family_id=family_id, reason=FamilyRefusalReason.NOT_IN_REPORT, restrictive=None
        )


class RoiDecisionRefusalReason(StrEnum):
    UNREADABLE = auto()
    MALFORMED = auto()
    SCHEMA_VERSION = auto()
    GENERATED_AT_INVALID = auto()
    REPORT_FROM_FUTURE = auto()
    REPORT_STALE = auto()
    LABELS_GATED = auto()


@dataclass(frozen=True, slots=True, kw_only=True)
class RoiDecisionRefusal:
    reason: RoiDecisionRefusalReason


def _label_gate(raw: object) -> str | None:
    if raw is not None and not isinstance(raw, str):
        raise _Malformed("label_gate_status")
    if raw not in LABEL_GATE_SERVES and raw not in LABEL_GATE_REFUSES:
        raise _Malformed("label_gate_status")
    return raw


def _nullable_integer(raw: Mapping[str, object], key: str) -> int | None:
    if key not in raw:
        raise _Malformed(key)
    return None if raw[key] is None else _integer(raw, key)


def _family_refusal(row: FamilyDecisionStats) -> FamilyDecisionRefusal | None:
    if row.family_id == _UNKNOWN_FAMILY:
        return FamilyDecisionRefusal(
            family_id=row.family_id, reason=FamilyRefusalReason.FAMILY_UNKNOWN, restrictive=None
        )
    reason: FamilyRefusalReason | None = None
    if row.n_incomplete:
        reason = FamilyRefusalReason.FAMILY_INCOMPLETE
    elif row.n_fee_unverified:
        reason = FamilyRefusalReason.FAMILY_FEE_UNVERIFIED
    elif row.n_settlement_disagree:
        reason = FamilyRefusalReason.FAMILY_SETTLEMENT_DISAGREE
    elif row.n_other_excluded < 0:
        reason = FamilyRefusalReason.FAMILY_PARTITION
    if reason is None:
        return None
    return FamilyDecisionRefusal(
        family_id=row.family_id,
        reason=reason,
        restrictive=FamilyRestrictiveBlock(
            net_pnl=row.net_pnl,
            n_residual=row.n_residual,
            n_residual_pending=row.n_residual_pending,
            residual_pnl=row.residual_pnl,
            n_residual_fee_unverified=row.n_residual_fee_unverified,
            n_residual_settlement_disagree=row.n_residual_settlement_disagree,
        ),
    )


def _families(
    raw: object,
) -> tuple[tuple[FamilyDecisionStats, ...], tuple[FamilyDecisionRefusal, ...]]:
    if not isinstance(raw, list):
        raise _Malformed("family_decision_stats")
    stats: list[FamilyDecisionStats] = []
    refusals: list[FamilyDecisionRefusal] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise _Malformed("family_decision_stats row")
        row = FamilyDecisionStats.from_json(item)
        if row.family_id in seen:
            raise _Malformed("duplicate family_id")
        seen.add(row.family_id)
        refusal = _family_refusal(row)
        if refusal is None:
            stats.append(row)
        else:
            refusals.append(refusal)
    return (
        tuple(sorted(stats, key=lambda row: row.family_id)),
        tuple(sorted(refusals, key=lambda refusal: refusal.family_id)),
    )


def _view(
    raw: Mapping[str, object], generated_at: datetime
) -> RoiDecisionView | RoiDecisionRefusal:
    disclosures = raw.get("disclosures")
    if not isinstance(disclosures, dict):
        raise _Malformed("disclosures")
    labels_gated = _integer(disclosures, "n_labels_gated")
    roi_status = _text(raw, "roi_status")
    freshness = _text(raw, "input_freshness_status")
    if freshness not in {INPUT_FRESHNESS_OK, INPUT_FRESHNESS_STALE}:
        raise _Malformed("input_freshness_status")
    days = _nullable_integer(raw, "days_since_newest_input")
    anchors = _nullable_integer(raw, "n_open_anchors_without_fill")
    if "label_gate_status" not in raw:
        raise _Malformed("label_gate_status")
    gate = _label_gate(raw["label_gate_status"])
    if labels_gated or gate in LABEL_GATE_REFUSES:
        return RoiDecisionRefusal(reason=RoiDecisionRefusalReason.LABELS_GATED)
    stats, refusals = _families(raw.get("family_decision_stats"))
    return RoiDecisionView(
        schema_version=_integer(raw, "schema_version"),
        generated_at=generated_at,
        settled_through=_text(raw, "settled_through"),
        roi_status=roi_status,
        label_gate_status=gate,
        days_since_newest_input=days,
        input_freshness_status=freshness,
        n_open_anchors_without_fill=anchors,
        family_stats=stats,
        family_refusals=refusals,
    )


def read_roi_for_decision(path: Path, now: datetime) -> RoiDecisionView | RoiDecisionRefusal:
    """Read once and fail closed; freshness of inputs is disclosure only."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return RoiDecisionRefusal(reason=RoiDecisionRefusalReason.UNREADABLE)
    if not isinstance(raw, dict):
        return RoiDecisionRefusal(reason=RoiDecisionRefusalReason.UNREADABLE)
    version = raw.get("schema_version")
    if type(version) is not int or version not in DECISION_SCHEMA_VERSIONS:
        return RoiDecisionRefusal(reason=RoiDecisionRefusalReason.SCHEMA_VERSION)
    try:
        generated_at = datetime.fromisoformat(_text(raw, "generated_at"))
        if generated_at.tzinfo is None or generated_at.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
    except ValueError:
        return RoiDecisionRefusal(reason=RoiDecisionRefusalReason.GENERATED_AT_INVALID)
    if generated_at > now:
        return RoiDecisionRefusal(reason=RoiDecisionRefusalReason.REPORT_FROM_FUTURE)
    if now - generated_at > MAX_DECISION_REPORT_AGE:
        return RoiDecisionRefusal(reason=RoiDecisionRefusalReason.REPORT_STALE)
    try:
        return _view(raw, generated_at)
    except _Malformed:
        return RoiDecisionRefusal(reason=RoiDecisionRefusalReason.MALFORMED)
