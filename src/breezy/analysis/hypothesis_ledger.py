"""AUD-18 Slice A: the programme-level hypothesis pre-registration ledger.

See `docs/plans/backlog/AUDIT_2026-09-21/AUD-18-strategy-design-backtest-iterate-programme.md`
SS6.1/SS6.2. This module is a PURE core (no disk I/O in its domain logic) plus
a thin, versioned JSONL reader/writer for `HypothesisRecord` rows, mirroring
the discipline `breezy.analysis.replay_sufficiency` already established for
AUD-09's H0 hand-off: an unknown `schema_version` is a hard refusal naming the
path/line/version, and a duplicate identity key is a hard error, never
last-wins.

**Scope, stated once (SS5 exclusions):** this module registers and allocates
alpha; it never scores a look, never reads AUD-09's replay artefacts, and
never places an order. `scripts/analysis/hypothesis_triage.py` (SS6.4, a
LATER slice) is the only consumer of `HypothesisLook`-shaped scoring, which
this module does not yet implement beyond the pure veto/statistic helpers
SS6.1 pins.

**Invariant, binding:** this module never imports `breezy.strategy`,
`breezy.adapters`, `breezy.runtime`, or anything execution-shaped -- enforced
mechanically by the two-way `import-linter` `forbidden` contract in
`pyproject.toml` (AUD-18 D6(i)). The one reused import from below `analysis`
in the layer stack is `breezy.settlement.current_rung_hold_v2`'s
`CombinedDraw`/`combine_station_day` family, exactly as SS6.1 mandates reuse
over re-invention.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import NormalDist
from typing import Final, Literal

from breezy.settlement.current_rung_hold_v2 import CombinedDraw

__all__ = [
    "EVIDENCED_FEE_THETA",
    "HYPOTHESIS_LEDGER_SCHEMA_VERSION",
    "HYPOTHESIS_LEDGER_SCHEMA_VERSION_V2",
    "MAX_HYPOTHESES",
    "MAX_SINGLE_DAY_LEG_SHARE",
    "MAX_VARIANTS_PER_HYPOTHESIS",
    "MDE_MISMATCH_TOLERANCE",
    "MIN_PER_VARIANT_ALPHA",
    "PINNED_ORDER_QUANTITY",
    "POOLED_PNL_VETO_REQUIRED",
    "POWER",
    "PROGRAMME_ALPHA",
    "STATION_DAY_STATISTIC",
    "ZERO_TAKE_STATION_DAYS_EXCLUDED",
    "DuplicateHypothesisIdError",
    "DuplicateHypothesisLedgerRecordError",
    "DuplicateStratumAxisError",
    "HypothesisLedgerRecordError",
    "HypothesisLook",
    "HypothesisRecord",
    "InvalidLookPolicyError",
    "MalformedStratumRangeError",
    "MdeMismatchError",
    "MissingRegistrationInputError",
    "MissingStratumAxisError",
    "NonMeanStationDayStatisticError",
    "NonPinnedLegShareCapError",
    "NonPositiveVariantCountError",
    "NonUnitOrderQuantityError",
    "PooledPnlVetoOutcome",
    "PowerPrimaryOnlyRequiredError",
    "ProgrammeBudgetExhaustedError",
    "StaleFeeThetaError",
    "StratumFilter",
    "StratumFilterCountMismatchError",
    "UnjustifiedVarianceBoundError",
    "UnknownHypothesisLedgerSchemaError",
    "UnknownStratumAxisError",
    "VariantCountCeilingExceededError",
    "ZeroTakeFilterResult",
    "alpha_remaining",
    "break_even",
    "evaluate_pooled_pnl_veto",
    "filter_zero_take_station_days",
    "is_variant_eligible",
    "max_single_day_leg_share",
    "parse_stratum_filter",
    "pooled_net_pnl_per_contract",
    "programme_budget_remaining",
    "read_hypothesis_ledger",
    "recompute_mde",
    "register_hypothesis",
    "station_day_mean_variance",
    "station_day_mean_x",
    "write_hypothesis_ledger",
]

#: Hand-off shape for this item's own artefact -- an unrecognised version is a
#: hard refusal, never a silent fallback (mirrors AUD-09's H0 discipline).
#: This is schema V1 -- kept exactly as-is, never bumped in place (RA-2,
#: EDGE-5 2026-09-27): the 3 existing on-disk rows are written at this
#: version and must keep reading and round-tripping byte-identically.
HYPOTHESIS_LEDGER_SCHEMA_VERSION: Final[int] = 1
#: Schema V2 (RA-2, EDGE-5 2026-09-27): adds `variant_stratum_filters` to
#: `HypothesisRecord`, the hypothesis/variant -> stratum/draw-population
#: binding AUD-18 SS7 step 8 names. `read_hypothesis_ledger` accepts both
#: {1, 2} and refuses anything else; a V1 record never round-trips forward
#: as V2 (its own `to_dict()` keeps emitting `schema_version: 1` and omits
#: the new key entirely).
HYPOTHESIS_LEDGER_SCHEMA_VERSION_V2: Final[int] = 2
_SUPPORTED_SCHEMA_VERSIONS: Final[frozenset[int]] = frozenset(
    {HYPOTHESIS_LEDGER_SCHEMA_VERSION, HYPOTHESIS_LEDGER_SCHEMA_VERSION_V2}
)

#: Programme-level, fixed BEFORE any intake (SS6.1); never re-derived from data.
PROGRAMME_ALPHA: Final[float] = 0.05
#: = SS6.3's three open classes (archive-table recalibration, NO-side hunting,
#: hours 10-11 repricing window) + one reserve slot for a future maker/resting
#: redesign.
MAX_HYPOTHESES: Final[int] = 4
#: Fewer, sharper hypotheses over broad variant sweeps (SS6.1).
MAX_VARIANTS_PER_HYPOTHESIS: Final[int] = 4
#: Floor on any real allocation: PROGRAMME_ALPHA / MAX_HYPOTHESES / MAX_VARIANTS_PER_HYPOTHESIS.
#: Asserted, never re-derived.
MIN_PER_VARIANT_ALPHA: Final[float] = 0.003125

#: SS6.1 POWER CHECK -- pinned design constants, identical for every hypothesis.
#: PRIMARY-test design power ONLY (SS6.1 POWER-PRIMARY-ONLY): because CONFIRMED
#: also requires the pooled-P&L veto, every MDE derived from this is an UPPER
#: bound on P(reach CONFIRMED). The gap is not bounded analytically here.
POWER: Final[float] = 0.80
#: Popoviciu bound on the SS6.1 MEAN statistic: each (W_i - BE_i) spans width 1,
#: so their mean does too, so Var <= 1/4 for ANY side mix, ANY leg count, ANY
#: dependence (gs_boundary_artefact.py:75-78; PREREG_v2:55-60).
VARIANCE_BOUND: Final[float] = 0.25
#: The ONE admitted station-day observation, for the power check AND the
#: confirmatory test (SS6.1). The station-day SUM is NOT admitted here.
STATION_DAY_STATISTIC: Final[str] = "MEAN_EXCESS_PER_TAKE"
#: SS6.1: registration constraint, not a dial (PREREG_WP7 SS2.2:110-113;
#: config.py:253-255).
PINNED_ORDER_QUANTITY: Final[int] = 1
#: FEE_SCHEDULE_PIN_2026-09-18.md:7,47 -- NOT config.py:226's stale 0.06.
EVIDENCED_FEE_THETA: Final[float] = 0.0695
#: SS6.1 ZERO-TAKE RULE. A station-day with no realized take carries no X_d (a
#: mean over no takes is undefined) and is dropped before any statistic.
ZERO_TAKE_STATION_DAYS_EXCLUDED: Final[bool] = True
#: SS6.1 POOLED-P&L VETO. Alpha-free and VETO-ONLY.
POOLED_PNL_VETO_REQUIRED: Final[bool] = True
#: SS6.1 concentration cap: the largest share of a variant's TOTAL legs any ONE
#: station-day may contribute. Pinned once, never a per-hypothesis dial.
MAX_SINGLE_DAY_LEG_SHARE: Final[float] = 0.20

#: A caller-stated MDE within this of the recomputed value is accepted; beyond
#: it, `register_hypothesis` refuses naming both numbers (SS6.1 enforcement).
MDE_MISMATCH_TOLERANCE: Final[float] = 1e-4

_STATUS_VALUES = frozenset(
    {
        "REGISTERED",
        "PARKED_INSUFFICIENT_DATA",
        "EVALUATING",
        "CONFIRMED",
        "REJECTED",
        "ABANDONED_CAP_EXHAUSTED",
        "UNDERPOWERED_NOT_REGISTERED",
        "PRIMARY_PASSED_PNL_VETO",
    }
)


class HypothesisLedgerRecordError(Exception):
    """`HypothesisRecord.from_dict` refuses a malformed payload (missing key,
    extra key, or wrong-typed key), named explicitly -- mirrors
    `ReplaySufficiencyRecordError`."""


class UnknownHypothesisLedgerSchemaError(Exception):
    """A `hypothesis_ledger.jsonl` line names an unrecognised `schema_version`.

    Names the offending path, line number, and version -- never a silent
    fallback (SS6.2).
    """


class DuplicateHypothesisLedgerRecordError(Exception):
    """Two lines in `hypothesis_ledger.jsonl` share one `hypothesis_id` -- a
    hard error, never last-wins."""


class DuplicateHypothesisIdError(ValueError):
    """`register_hypothesis` refuses a `hypothesis_id` already present among
    the caller-supplied `existing_records` (SS6.2)."""


class NonPositiveVariantCountError(ValueError):
    """`k_variants < 1` is refused at registration."""


class VariantCountCeilingExceededError(ValueError):
    """`k_variants > MAX_VARIANTS_PER_HYPOTHESIS` is refused for a look-taking
    registration (zero-look records are exempt, SS6.1)."""


class ProgrammeBudgetExhaustedError(ValueError):
    """`MAX_HYPOTHESES` look-taking registrations already exist; the programme
    REFUSES a further intake rather than shrinking anyone's prior allocation
    (SS6.1)."""


class InvalidLookPolicyError(ValueError):
    """Any `look_policy` other than `"SINGLE_LOOK"` is refused -- `LD_OBF` is
    WITHDRAWN under this programme's alpha budget (SS6.1)."""


class MissingRegistrationInputError(ValueError):
    """A NORMAL-disposition registration omitted a required input."""


class PowerPrimaryOnlyRequiredError(ValueError):
    """A record asserting `power_is_primary_only=False` is refused -- SS6.1
    POWER-PRIMARY-ONLY is the single canonical statement of this rule."""


class MdeMismatchError(ValueError):
    """A caller-stated `mde_at_allocated_alpha` disagrees with the recomputed
    value beyond `MDE_MISMATCH_TOLERANCE`; both numbers are named."""


class StaleFeeThetaError(ValueError):
    """`mde_fee_theta` is not `EVIDENCED_FEE_THETA` -- refuses the stale
    `config.py:226` default of `0.06`."""


class UnjustifiedVarianceBoundError(ValueError):
    """`mde_variance_bound != VARIANCE_BOUND` with no recorded outcome-free
    justification."""


class NonUnitOrderQuantityError(ValueError):
    """`order_quantity != PINNED_ORDER_QUANTITY` is refused, naming
    `NON_UNIT_ORDER_QUANTITY`."""


class NonMeanStationDayStatisticError(ValueError):
    """`station_day_statistic != STATION_DAY_STATISTIC` is refused, naming
    `NON_MEAN_STATION_DAY_STATISTIC`."""


class NonPinnedLegShareCapError(ValueError):
    """`max_single_day_leg_share_cap != MAX_SINGLE_DAY_LEG_SHARE` is refused,
    naming `NON_PINNED_LEG_SHARE_CAP`."""


class UnknownStratumAxisError(ValueError):
    """A `variant_stratum_filters` entry names an axis outside the closed,
    validated vocabulary (`station`, `hour_lst`, `side`, `composition_kind`)
    -- a wrong or missing axis is a REFUSAL, never a silent gap (RA-2)."""


class MalformedStratumRangeError(ValueError):
    """A `variant_stratum_filters` entry's `hour_lst` value is not `ALL`, a
    single hour `0-23`, or an ascending `N-M` range within `0-23`."""


class DuplicateStratumAxisError(ValueError):
    """A `variant_stratum_filters` entry names the same axis twice."""


class MissingStratumAxisError(ValueError):
    """A `variant_stratum_filters` entry omits a required axis."""


class StratumFilterCountMismatchError(ValueError):
    """A NORMAL-disposition registration's `variant_stratum_filters` does not
    have exactly `k_variants` entries."""


#: RA-2's closed, validated vocabulary (never a free-form DSL) -- exactly the
#: axes `RULING_HUNT-1`'s own triggers name (EDGE-5 plan r1 SS5).
_STRATUM_AXES: Final[tuple[str, ...]] = ("station", "hour_lst", "side", "composition_kind")
_STRATUM_SIDE_VALUES: Final[frozenset[str]] = frozenset({"YES", "NO", "ALL"})
_HOUR_LST_RE: Final[re.Pattern[str]] = re.compile(r"^(ALL|[0-9]{1,2}(-[0-9]{1,2})?)$")


@dataclass(frozen=True, slots=True, kw_only=True)
class StratumFilter:
    """One parsed, validated `variant_stratum_filters` entry (RA-2).

    Fields are kept as their validated STRING form (never further parsed into
    e.g. a station tuple) -- `_has_registered_draw_binding` only needs to know
    a filter parses; matching it against a real replay row's shape is a later
    slice's scope (EDGE-5 RA-9b), not this one's.
    """

    station: str
    hour_lst: str
    side: str
    composition_kind: str


def _parse_hour_lst(value: str) -> None:
    if not _HOUR_LST_RE.match(value):
        raise MalformedStratumRangeError(
            f"malformed hour_lst {value!r}: expected ALL, a single hour 0-23, "
            "or an ascending N-M range within 0-23"
        )
    if value == "ALL":
        return
    bounds = tuple(int(part) for part in value.split("-"))
    if any(bound < 0 or bound > 23 for bound in bounds):
        raise MalformedStratumRangeError(f"malformed hour_lst {value!r}: hour(s) out of range 0-23")
    if len(bounds) == 2 and bounds[0] > bounds[1]:
        raise MalformedStratumRangeError(
            f"malformed hour_lst {value!r}: range must be ascending (N <= M)"
        )


def parse_stratum_filter(spec: str) -> StratumFilter:
    """Parse one pipe-joined `variant_stratum_filters` entry (RA-2):

        station=<ALL|comma-set>|hour_lst=<ALL|N|N-M>|side=<YES|NO|ALL>|composition_kind=<name>

    Refuses an unknown axis, a duplicate axis, a missing axis, an invalid
    `side`, or a malformed `hour_lst` -- never silently drops or defaults.
    """
    values: dict[str, str] = {}
    for part in spec.split("|"):
        axis, separator, value = part.partition("=")
        if not separator:
            raise UnknownStratumAxisError(
                f"malformed stratum filter segment {part!r} in {spec!r}: expected axis=value"
            )
        if axis not in _STRATUM_AXES:
            raise UnknownStratumAxisError(
                f"unknown stratum filter axis {axis!r} in {spec!r}; expected one of {_STRATUM_AXES}"
            )
        if axis in values:
            raise DuplicateStratumAxisError(f"duplicate stratum filter axis {axis!r} in {spec!r}")
        if not value:
            raise MissingStratumAxisError(
                f"stratum filter axis {axis!r} in {spec!r} has an empty value"
            )
        values[axis] = value
    missing = [axis for axis in _STRATUM_AXES if axis not in values]
    if missing:
        raise MissingStratumAxisError(f"stratum filter {spec!r} is missing axis(es): {missing}")
    if values["side"] not in _STRATUM_SIDE_VALUES:
        raise ValueError(
            f"stratum filter side must be one of {sorted(_STRATUM_SIDE_VALUES)}, "
            f"got {values['side']!r} in {spec!r}"
        )
    _parse_hour_lst(values["hour_lst"])
    return StratumFilter(
        station=values["station"],
        hour_lst=values["hour_lst"],
        side=values["side"],
        composition_kind=values["composition_kind"],
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class HypothesisRecord:
    """One programme-level hypothesis pre-registration (SS6.2).

    `is_zero_look` marks the two bookkeeping dispositions SS6.1 carves out --
    the CLOSED forecast-taker record and `UNDERPOWERED_NOT_REGISTERED` -- as
    permanently exempt from `MAX_HYPOTHESES`/`MAX_VARIANTS_PER_HYPOTHESIS` and
    from ever carrying a `HypothesisLook` row. It is this module's explicit
    marker for that exemption rather than an implicit numeric coincidence
    (e.g. `k_variants == 12`), so the exemption is checkable directly.
    """

    schema_version: int
    hypothesis_id: str
    hypothesis_class: str
    registered_at: str
    k_variants: int
    allocated_alpha: float
    per_variant_alpha: float
    min_station_days: int
    max_single_day_leg_share_cap: float
    mde_at_allocated_alpha: float
    mde_plausibility_bound: float
    power_is_primary_only: bool
    mde_reference_ask: float
    mde_fee_theta: float
    mde_slippage_allowance: float
    mde_variance_bound: float
    mde_variance_bound_justification: str | None
    station_day_statistic: str
    order_quantity: int
    look_policy: str
    freeze_commit: str
    status: str
    is_zero_look: bool
    #: V2-only (RA-2). Always `()` on a V1 record -- `from_dict` never
    #: populates this from a V1 payload, and `to_dict` never emits the key
    #: for a V1 record (see `test_v1_record_to_dict_never_emits_variant_stratum_filters`).
    #: On a V2 look-taking record, length must equal `k_variants`, one
    #: canonical pipe-joined `parse_stratum_filter`-shaped string per variant,
    #: in `v1, v2, ...` order.
    variant_stratum_filters: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in _STATUS_VALUES:
            raise ValueError(
                f"HypothesisRecord.status must be one of {sorted(_STATUS_VALUES)}, "
                f"got {self.status!r}"
            )
        if self.schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(
                f"HypothesisRecord.schema_version must be one of "
                f"{sorted(_SUPPORTED_SCHEMA_VERSIONS)}, got {self.schema_version!r}"
            )
        if self.schema_version == HYPOTHESIS_LEDGER_SCHEMA_VERSION and self.variant_stratum_filters:
            raise ValueError(
                f"schema_version={HYPOTHESIS_LEDGER_SCHEMA_VERSION} (V1) records must not "
                "carry variant_stratum_filters"
            )
        if (
            self.schema_version == HYPOTHESIS_LEDGER_SCHEMA_VERSION_V2
            and not self.is_zero_look
            and len(self.variant_stratum_filters) != self.k_variants
        ):
            raise StratumFilterCountMismatchError(
                f"schema_version=2 look-taking record {self.hypothesis_id!r} must carry "
                f"variant_stratum_filters of length k_variants={self.k_variants}, "
                f"got {len(self.variant_stratum_filters)}"
            )

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "hypothesis_id": self.hypothesis_id,
            "hypothesis_class": self.hypothesis_class,
            "registered_at": self.registered_at,
            "k_variants": self.k_variants,
            "allocated_alpha": self.allocated_alpha,
            "per_variant_alpha": self.per_variant_alpha,
            "min_station_days": self.min_station_days,
            "max_single_day_leg_share_cap": self.max_single_day_leg_share_cap,
            "mde_at_allocated_alpha": self.mde_at_allocated_alpha,
            "mde_plausibility_bound": self.mde_plausibility_bound,
            "power_is_primary_only": self.power_is_primary_only,
            "mde_reference_ask": self.mde_reference_ask,
            "mde_fee_theta": self.mde_fee_theta,
            "mde_slippage_allowance": self.mde_slippage_allowance,
            "mde_variance_bound": self.mde_variance_bound,
            "mde_variance_bound_justification": self.mde_variance_bound_justification,
            "station_day_statistic": self.station_day_statistic,
            "order_quantity": self.order_quantity,
            "look_policy": self.look_policy,
            "freeze_commit": self.freeze_commit,
            "status": self.status,
            "is_zero_look": self.is_zero_look,
        }
        if self.schema_version == HYPOTHESIS_LEDGER_SCHEMA_VERSION_V2:
            payload["variant_stratum_filters"] = list(self.variant_stratum_filters)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> HypothesisRecord:
        version = payload.get("schema_version")
        if version == HYPOTHESIS_LEDGER_SCHEMA_VERSION:
            field_types = _HYPOTHESIS_RECORD_FIELD_TYPES_V1
        elif version == HYPOTHESIS_LEDGER_SCHEMA_VERSION_V2:
            field_types = _HYPOTHESIS_RECORD_FIELD_TYPES_V2
        else:
            raise HypothesisLedgerRecordError(
                f"hypothesis_ledger record has unrecognised schema_version {version!r} "
                f"(expected one of {sorted(_SUPPORTED_SCHEMA_VERSIONS)})"
            )
        known_keys = set(field_types)
        keys = set(payload)
        missing = known_keys - keys
        if missing:
            raise HypothesisLedgerRecordError(
                f"hypothesis_ledger record missing key(s): {sorted(missing)}"
            )
        extra = keys - known_keys
        if extra:
            raise HypothesisLedgerRecordError(
                f"hypothesis_ledger record has unexpected key(s): {sorted(extra)}"
            )
        for name, expected_type in field_types.items():
            if name == "variant_stratum_filters":
                value = payload[name]
                if not isinstance(value, (list, tuple)) or not all(
                    isinstance(item, str) for item in value
                ):
                    raise HypothesisLedgerRecordError(
                        f"{name!r} must be a list of str, got {type(value).__name__}"
                    )
                continue
            value = payload[name]
            if value is None:
                if name == "mde_variance_bound_justification":
                    continue
                raise HypothesisLedgerRecordError(f"{name!r} must not be null")
            is_bool_value = isinstance(value, bool)
            if expected_type is bool and not is_bool_value:
                raise HypothesisLedgerRecordError(
                    f"{name!r} must be a bool, got {type(value).__name__}"
                )
            if expected_type is int and (not isinstance(value, int) or is_bool_value):
                raise HypothesisLedgerRecordError(
                    f"{name!r} must be an int, got {type(value).__name__}"
                )
            if expected_type is float and not isinstance(value, (int, float)) or (
                expected_type is float and is_bool_value
            ):
                raise HypothesisLedgerRecordError(
                    f"{name!r} must be a float, got {type(value).__name__}"
                )
            if expected_type is str and not isinstance(value, str):
                raise HypothesisLedgerRecordError(
                    f"{name!r} must be a str, got {type(value).__name__}"
                )
        variant_stratum_filters = (
            tuple(payload["variant_stratum_filters"])  # type: ignore[arg-type]
            if version == HYPOTHESIS_LEDGER_SCHEMA_VERSION_V2
            else ()
        )
        return cls(
            schema_version=payload["schema_version"],  # type: ignore[arg-type]
            hypothesis_id=payload["hypothesis_id"],  # type: ignore[arg-type]
            hypothesis_class=payload["hypothesis_class"],  # type: ignore[arg-type]
            registered_at=payload["registered_at"],  # type: ignore[arg-type]
            k_variants=payload["k_variants"],  # type: ignore[arg-type]
            allocated_alpha=float(payload["allocated_alpha"]),  # type: ignore[arg-type]
            per_variant_alpha=float(payload["per_variant_alpha"]),  # type: ignore[arg-type]
            min_station_days=payload["min_station_days"],  # type: ignore[arg-type]
            max_single_day_leg_share_cap=float(payload["max_single_day_leg_share_cap"]),  # type: ignore[arg-type]
            mde_at_allocated_alpha=float(payload["mde_at_allocated_alpha"]),  # type: ignore[arg-type]
            mde_plausibility_bound=float(payload["mde_plausibility_bound"]),  # type: ignore[arg-type]
            power_is_primary_only=payload["power_is_primary_only"],  # type: ignore[arg-type]
            mde_reference_ask=float(payload["mde_reference_ask"]),  # type: ignore[arg-type]
            mde_fee_theta=float(payload["mde_fee_theta"]),  # type: ignore[arg-type]
            mde_slippage_allowance=float(payload["mde_slippage_allowance"]),  # type: ignore[arg-type]
            mde_variance_bound=float(payload["mde_variance_bound"]),  # type: ignore[arg-type]
            mde_variance_bound_justification=payload["mde_variance_bound_justification"],  # type: ignore[arg-type]
            station_day_statistic=payload["station_day_statistic"],  # type: ignore[arg-type]
            order_quantity=payload["order_quantity"],  # type: ignore[arg-type]
            look_policy=payload["look_policy"],  # type: ignore[arg-type]
            freeze_commit=payload["freeze_commit"],  # type: ignore[arg-type]
            status=payload["status"],  # type: ignore[arg-type]
            is_zero_look=payload["is_zero_look"],  # type: ignore[arg-type]
            variant_stratum_filters=variant_stratum_filters,
        )


_HYPOTHESIS_RECORD_FIELD_TYPES_V1: Final[dict[str, type]] = {
    "schema_version": int,
    "hypothesis_id": str,
    "hypothesis_class": str,
    "registered_at": str,
    "k_variants": int,
    "allocated_alpha": float,
    "per_variant_alpha": float,
    "min_station_days": int,
    "max_single_day_leg_share_cap": float,
    "mde_at_allocated_alpha": float,
    "mde_plausibility_bound": float,
    "power_is_primary_only": bool,
    "mde_reference_ask": float,
    "mde_fee_theta": float,
    "mde_slippage_allowance": float,
    "mde_variance_bound": float,
    "mde_variance_bound_justification": str,
    "station_day_statistic": str,
    "order_quantity": int,
    "look_policy": str,
    "freeze_commit": str,
    "status": str,
    "is_zero_look": bool,
}

#: V2 = V1 plus RA-2's own field. A V1 payload on disk must NOT carry this
#: key (`from_dict` refuses an unexpected key); a V2 payload MUST.
_HYPOTHESIS_RECORD_FIELD_TYPES_V2: Final[dict[str, type]] = {
    **_HYPOTHESIS_RECORD_FIELD_TYPES_V1,
    "variant_stratum_filters": tuple,
}


@dataclass(frozen=True, slots=True, kw_only=True)
class HypothesisLook:
    """One SINGLE_LOOK confirmatory evaluation of one variant (SS6.2).

    Built and appended only by `scripts/analysis/hypothesis_triage.py` (a
    later slice); this dataclass ships now so `is_variant_eligible`/
    `alpha_remaining` have a concrete shape to test against.
    """

    hypothesis_id: str
    variant_id: str
    looked_at: str
    n_station_days: int
    n_station_days_observed: int
    n_station_days_with_takes: int
    take_rate: float
    ci_lower: float
    ci_upper: float
    pooled_net_pnl_per_contract: float
    max_single_day_leg_share: float
    veto_reason: Literal["NONE", "POOLED_PNL_NON_POSITIVE", "LEG_SHARE_ABOVE_CAP"]
    alpha_spent_cumulative: float
    is_terminal_look: bool


def programme_budget_remaining(records: Sequence[HypothesisRecord]) -> int:
    """`MAX_HYPOTHESES` minus the LOOK-TAKING records.

    Zero-look records (`is_zero_look=True` -- the REJECTED disposition row and
    `UNDERPOWERED_NOT_REGISTERED`) are excluded, so their share is never
    counted and never recycled: a look-taking record that later becomes
    `REJECTED` (a failed look) is NOT zero-look and keeps occupying its slot.
    """
    spent = sum(1 for record in records if not record.is_zero_look)
    return max(0, MAX_HYPOTHESES - spent)


def alpha_remaining(
    record: HypothesisRecord, looks: Sequence[HypothesisLook], variant_id: str
) -> float:
    """`per_variant_alpha` minus THIS variant's own spend -- no cross-variant
    pooling: a sibling variant's look under the same hypothesis never counts
    against this one's remaining alpha."""
    spent = sum(
        look.alpha_spent_cumulative
        for look in looks
        if look.hypothesis_id == record.hypothesis_id and look.variant_id == variant_id
    )
    return record.per_variant_alpha - spent


def is_variant_eligible(
    record: HypothesisRecord, looks: Sequence[HypothesisLook], variant_id: str
) -> bool:
    """False once an "already-looked" row exists for `(hypothesis_id,
    variant_id)`, and always False for a zero-look record (SS6.4 step 3's
    SINGLE_LOOK invariant: a variant is evaluated exactly once, ever)."""
    if record.is_zero_look:
        return False
    return not any(
        look.hypothesis_id == record.hypothesis_id and look.variant_id == variant_id
        for look in looks
    )


def break_even(*, reference_ask: float, fee_theta: float, slippage: float) -> float:
    """`BE = a + theta * a * (1 - a) + slippage` (SS6.1) -- the venue fee
    arithmetic `polymarket_us_fee` (`adapters/polymarket_us/fees.py:277`)
    reproduces, restated here rather than imported so this module never
    reaches into `breezy.adapters` (the invariant D6(i) enforces)."""
    return reference_ask + fee_theta * reference_ask * (1.0 - reference_ask) + slippage


def recompute_mde(*, per_variant_alpha: float, n_station_days: int) -> float:
    """SS6.1's pinned formula, the ONLY admitted derivation:

        (z(1 - per_variant_alpha) + z(POWER)) * sqrt(VARIANCE_BOUND) / sqrt(n)

    Outcome-free by construction: reads no `StratumRow` and no realized draw.
    """
    if n_station_days <= 0:
        raise ValueError("recompute_mde is undefined for n_station_days <= 0")
    normal = NormalDist()
    z_alpha = normal.inv_cdf(1.0 - per_variant_alpha)
    z_power = normal.inv_cdf(POWER)
    numerator = float(z_alpha + z_power) * float(VARIANCE_BOUND**0.5)
    return float(numerator / (float(n_station_days) ** 0.5))


def register_hypothesis(
    *,
    hypothesis_id: str,
    hypothesis_class: str,
    registered_at: str,
    k_variants: int,
    freeze_commit: str,
    existing_records: Sequence[HypothesisRecord],
    disposition: Literal["NORMAL", "CLOSED"] = "NORMAL",
    min_station_days: int | None = None,
    max_single_day_leg_share_cap: float | None = None,
    mde_at_allocated_alpha: float | None = None,
    mde_plausibility_bound: float | None = None,
    power_is_primary_only: bool | None = None,
    mde_reference_ask: float | None = None,
    mde_fee_theta: float | None = None,
    mde_slippage_allowance: float | None = None,
    mde_variance_bound: float | None = None,
    mde_variance_bound_justification: str | None = None,
    station_day_statistic: str | None = None,
    order_quantity: int | None = None,
    look_policy: str | None = None,
    programme_alpha_override: float | None = None,
    variant_stratum_filters: tuple[str, ...] | None = None,
) -> HypothesisRecord:
    """Register one hypothesis (SS6.2).

    `allocated_alpha`/`per_variant_alpha` are ASSIGNED here, by the fixed
    Bonferroni split. `programme_alpha_override` may only narrow the
    programme-level budget for a registered ruling; callers still never
    supply an already-split allocation.

    `disposition="CLOSED"` is the SS7 step 7 zero-look path: it records a
    pre-decided disposition (the forecast-taker's CLOSED, TERMINAL ruling) as
    data, consuming no alpha and no slot, and skips every MDE/statistic/
    quantity/leg-share input (none of that machinery scored this class --
    `PREREG_WP7_MULTIPLICITY_RULE` already did, elsewhere). `disposition=
    "NORMAL"` (default) is the full look-taking intake path, gated by the
    SS6.1 power check.

    `variant_stratum_filters` (RA-2, EDGE-5 2026-09-27) is the schema-V2
    hypothesis/variant -> stratum/draw-population binding: omitted (`None`,
    the default), a NORMAL-disposition registration is written at
    schema_version=1 exactly as before -- byte-identical to pre-RA-2
    behaviour. Supplied, it must have exactly `k_variants` entries, each a
    `parse_stratum_filter`-shaped string; the resulting record (REGISTERED or
    UNDERPOWERED_NOT_REGISTERED) is written at schema_version=2. Never
    accepted for `disposition="CLOSED"` -- a zero-look, no-variant-shape
    record has nothing to bind.
    """
    if k_variants < 1:
        raise NonPositiveVariantCountError(f"k_variants must be >= 1, got {k_variants}")
    if any(record.hypothesis_id == hypothesis_id for record in existing_records):
        raise DuplicateHypothesisIdError(
            f"hypothesis_id {hypothesis_id!r} is already registered -- refusing a duplicate intake"
        )

    if programme_alpha_override is not None and (
        isinstance(programme_alpha_override, bool)
        or not isinstance(programme_alpha_override, (int, float))
    ):
        raise ValueError(
            "programme_alpha_override must be an int or float, or None; "
            f"got {programme_alpha_override!r}"
        )

    programme_alpha = (
        PROGRAMME_ALPHA if programme_alpha_override is None else programme_alpha_override
    )
    if not (0.0 < programme_alpha <= PROGRAMME_ALPHA):
        raise ValueError(
            f"programme_alpha_override must be > 0 and <= PROGRAMME_ALPHA={PROGRAMME_ALPHA}; "
            f"got {programme_alpha_override}"
        )

    if disposition == "CLOSED":
        if variant_stratum_filters is not None:
            raise ValueError("variant_stratum_filters is not applicable to disposition=CLOSED")
        return HypothesisRecord(
            schema_version=HYPOTHESIS_LEDGER_SCHEMA_VERSION,
            hypothesis_id=hypothesis_id,
            hypothesis_class=hypothesis_class,
            registered_at=registered_at,
            k_variants=k_variants,
            allocated_alpha=0.0,
            per_variant_alpha=0.0,
            min_station_days=0,
            max_single_day_leg_share_cap=MAX_SINGLE_DAY_LEG_SHARE,
            mde_at_allocated_alpha=0.0,
            mde_plausibility_bound=0.0,
            power_is_primary_only=True,
            mde_reference_ask=0.0,
            mde_fee_theta=EVIDENCED_FEE_THETA,
            mde_slippage_allowance=0.0,
            mde_variance_bound=VARIANCE_BOUND,
            mde_variance_bound_justification=None,
            station_day_statistic=STATION_DAY_STATISTIC,
            order_quantity=PINNED_ORDER_QUANTITY,
            look_policy="SINGLE_LOOK",
            freeze_commit=freeze_commit,
            status="REJECTED",
            is_zero_look=True,
        )

    required = {
        "min_station_days": min_station_days,
        "max_single_day_leg_share_cap": max_single_day_leg_share_cap,
        "mde_at_allocated_alpha": mde_at_allocated_alpha,
        "mde_plausibility_bound": mde_plausibility_bound,
        "power_is_primary_only": power_is_primary_only,
        "mde_reference_ask": mde_reference_ask,
        "mde_fee_theta": mde_fee_theta,
        "mde_slippage_allowance": mde_slippage_allowance,
        "mde_variance_bound": mde_variance_bound,
        "station_day_statistic": station_day_statistic,
        "order_quantity": order_quantity,
        "look_policy": look_policy,
    }
    missing_inputs = sorted(name for name, value in required.items() if value is None)
    if missing_inputs:
        raise MissingRegistrationInputError(
            f"a NORMAL-disposition registration requires: {missing_inputs}"
        )
    assert min_station_days is not None
    assert max_single_day_leg_share_cap is not None
    assert mde_at_allocated_alpha is not None
    assert mde_plausibility_bound is not None
    assert power_is_primary_only is not None
    assert mde_reference_ask is not None
    assert mde_fee_theta is not None
    assert mde_slippage_allowance is not None
    assert mde_variance_bound is not None
    assert station_day_statistic is not None
    assert order_quantity is not None
    assert look_policy is not None

    if variant_stratum_filters is None:
        record_schema_version = HYPOTHESIS_LEDGER_SCHEMA_VERSION
        stored_stratum_filters: tuple[str, ...] = ()
    else:
        if len(variant_stratum_filters) != k_variants:
            raise StratumFilterCountMismatchError(
                f"variant_stratum_filters has {len(variant_stratum_filters)} entries, "
                f"expected k_variants={k_variants}"
            )
        for spec in variant_stratum_filters:
            parse_stratum_filter(spec)
        record_schema_version = HYPOTHESIS_LEDGER_SCHEMA_VERSION_V2
        stored_stratum_filters = tuple(variant_stratum_filters)

    if k_variants > MAX_VARIANTS_PER_HYPOTHESIS:
        raise VariantCountCeilingExceededError(
            f"k_variants={k_variants} exceeds MAX_VARIANTS_PER_HYPOTHESIS="
            f"{MAX_VARIANTS_PER_HYPOTHESIS} for a look-taking registration"
        )
    if look_policy != "SINGLE_LOOK":
        raise InvalidLookPolicyError(
            f"look_policy={look_policy!r} is refused -- SINGLE_LOOK is the only "
            "admitted design; LD_OBF is WITHDRAWN under this programme's alpha budget (SS6.1)"
        )
    if order_quantity != PINNED_ORDER_QUANTITY:
        raise NonUnitOrderQuantityError(
            f"NON_UNIT_ORDER_QUANTITY: order_quantity={order_quantity} != "
            f"PINNED_ORDER_QUANTITY={PINNED_ORDER_QUANTITY}"
        )
    if station_day_statistic != STATION_DAY_STATISTIC:
        raise NonMeanStationDayStatisticError(
            f"NON_MEAN_STATION_DAY_STATISTIC: station_day_statistic={station_day_statistic!r} "
            f"!= {STATION_DAY_STATISTIC!r}"
        )
    if max_single_day_leg_share_cap != MAX_SINGLE_DAY_LEG_SHARE:
        raise NonPinnedLegShareCapError(
            f"NON_PINNED_LEG_SHARE_CAP: max_single_day_leg_share_cap="
            f"{max_single_day_leg_share_cap} != MAX_SINGLE_DAY_LEG_SHARE={MAX_SINGLE_DAY_LEG_SHARE}"
        )
    if power_is_primary_only is not True:
        raise PowerPrimaryOnlyRequiredError(
            "power_is_primary_only must be True -- SS6.1 POWER-PRIMARY-ONLY is "
            "the single canonical statement of this rule"
        )
    if mde_fee_theta != EVIDENCED_FEE_THETA:
        raise StaleFeeThetaError(
            f"mde_fee_theta={mde_fee_theta} is not the evidenced coefficient "
            f"EVIDENCED_FEE_THETA={EVIDENCED_FEE_THETA} "
            "(FEE_SCHEDULE_PIN_2026-09-18.md:7,47) -- config.py:226's 0.06 default is stale"
        )
    if mde_variance_bound != VARIANCE_BOUND and not mde_variance_bound_justification:
        raise UnjustifiedVarianceBoundError(
            f"mde_variance_bound={mde_variance_bound} != VARIANCE_BOUND={VARIANCE_BOUND} "
            "with no recorded outcome-free justification"
        )

    if programme_budget_remaining(existing_records) <= 0:
        raise ProgrammeBudgetExhaustedError(
            f"MAX_HYPOTHESES={MAX_HYPOTHESES} look-taking registrations already exist -- "
            "refusing a further intake rather than shrinking an existing allocation"
        )

    allocated_alpha = programme_alpha / MAX_HYPOTHESES
    per_variant_alpha = allocated_alpha / k_variants
    recomputed_mde = recompute_mde(
        per_variant_alpha=per_variant_alpha, n_station_days=min_station_days
    )
    if abs(recomputed_mde - mde_at_allocated_alpha) > MDE_MISMATCH_TOLERANCE:
        raise MdeMismatchError(
            f"caller-stated mde_at_allocated_alpha={mde_at_allocated_alpha} disagrees with "
            f"recomputed MDE={recomputed_mde} beyond tolerance {MDE_MISMATCH_TOLERANCE}"
        )

    if recomputed_mde > mde_plausibility_bound:
        return HypothesisRecord(
            schema_version=record_schema_version,
            hypothesis_id=hypothesis_id,
            hypothesis_class=hypothesis_class,
            registered_at=registered_at,
            k_variants=k_variants,
            allocated_alpha=0.0,
            per_variant_alpha=0.0,
            min_station_days=min_station_days,
            max_single_day_leg_share_cap=max_single_day_leg_share_cap,
            mde_at_allocated_alpha=recomputed_mde,
            mde_plausibility_bound=mde_plausibility_bound,
            power_is_primary_only=True,
            mde_reference_ask=mde_reference_ask,
            mde_fee_theta=mde_fee_theta,
            mde_slippage_allowance=mde_slippage_allowance,
            mde_variance_bound=mde_variance_bound,
            mde_variance_bound_justification=mde_variance_bound_justification,
            station_day_statistic=station_day_statistic,
            order_quantity=order_quantity,
            look_policy=look_policy,
            freeze_commit=freeze_commit,
            status="UNDERPOWERED_NOT_REGISTERED",
            is_zero_look=True,
            variant_stratum_filters=stored_stratum_filters,
        )

    return HypothesisRecord(
        schema_version=record_schema_version,
        hypothesis_id=hypothesis_id,
        hypothesis_class=hypothesis_class,
        registered_at=registered_at,
        k_variants=k_variants,
        allocated_alpha=allocated_alpha,
        per_variant_alpha=per_variant_alpha,
        min_station_days=min_station_days,
        max_single_day_leg_share_cap=max_single_day_leg_share_cap,
        mde_at_allocated_alpha=recomputed_mde,
        mde_plausibility_bound=mde_plausibility_bound,
        power_is_primary_only=True,
        mde_reference_ask=mde_reference_ask,
        mde_fee_theta=mde_fee_theta,
        mde_slippage_allowance=mde_slippage_allowance,
        mde_variance_bound=mde_variance_bound,
        mde_variance_bound_justification=mde_variance_bound_justification,
        station_day_statistic=station_day_statistic,
        order_quantity=order_quantity,
        look_policy=look_policy,
        freeze_commit=freeze_commit,
        status="REGISTERED",
        is_zero_look=False,
        variant_stratum_filters=stored_stratum_filters,
    )


def station_day_mean_x(draw: CombinedDraw) -> float:
    """The SS6.1 MEAN statistic's value: `X_d / m_d`. `Var(X/m) = Var(X)/m^2`
    exactly for a fixed constant `m`, so this is a scaling of
    `combine_station_day`'s own SUM -- no new estimator (SS6.1 (b))."""
    return draw.x / draw.n_constituents


def station_day_mean_variance(draw: CombinedDraw) -> float:
    """The SS6.1 MEAN statistic's variance: `Var(X_d)/m_d^2`."""
    return draw.variance / (draw.n_constituents**2)


@dataclass(frozen=True, slots=True, kw_only=True)
class ZeroTakeFilterResult:
    """SS6.1's zero-take rule, reported on every look row."""

    n_station_days_observed: int
    n_station_days_with_takes: int
    take_rate: float
    with_takes_fills: tuple[int, ...]


def filter_zero_take_station_days(fills: Sequence[int]) -> ZeroTakeFilterResult:
    """Drop `fills == 0` station-days BEFORE any statistic is computed
    (SS6.1/SS6.4 step 4's named draw-set-construction filter), reporting both
    counts and the take rate rather than silently shrinking `n`."""
    observed = tuple(fills)
    with_takes = tuple(count for count in observed if count > 0)
    n_observed = len(observed)
    n_with_takes = len(with_takes)
    take_rate = (n_with_takes / n_observed) if n_observed > 0 else 0.0
    return ZeroTakeFilterResult(
        n_station_days_observed=n_observed,
        n_station_days_with_takes=n_with_takes,
        take_rate=take_rate,
        with_takes_fills=with_takes,
    )


def pooled_net_pnl_per_contract(draws: Sequence[CombinedDraw]) -> float:
    """SS6.1's VETO gate: the SUM of `combine_station_day`'s own `x` term over
    the SAME with-takes station-day draws the primary test consumed -- the
    existing SUM machinery reused, never a new estimator."""
    if not draws:
        raise ValueError("pooled_net_pnl_per_contract is undefined for an empty draw set")
    return sum(draw.x for draw in draws)


def max_single_day_leg_share(draws: Sequence[CombinedDraw]) -> float:
    """The largest share of the variant's TOTAL legs contributed by any ONE
    station-day (SS6.1 concentration screen)."""
    if not draws:
        raise ValueError("max_single_day_leg_share is undefined for an empty draw set")
    total_legs = sum(draw.n_constituents for draw in draws)
    if total_legs == 0:
        raise ValueError("max_single_day_leg_share is undefined when every draw has zero legs")
    return max(draw.n_constituents for draw in draws) / total_legs


@dataclass(frozen=True, slots=True, kw_only=True)
class PooledPnlVetoOutcome:
    """The SS6.1 veto's terminal decision over an already-passed/failed
    primary test. `status="REJECTED"` covers a failed primary regardless of
    the pooled number -- the veto can only shrink the CONFIRMED set, never
    rescue a failed primary or promote a passing one on its own."""

    status: Literal["REJECTED", "CONFIRMED", "PRIMARY_PASSED_PNL_VETO"]
    veto_reason: Literal["NONE", "POOLED_PNL_NON_POSITIVE", "LEG_SHARE_ABOVE_CAP"]


def evaluate_pooled_pnl_veto(
    *,
    primary_excludes_zero: bool,
    pooled_net_pnl_per_contract: float,
    max_single_day_leg_share: float,
    max_single_day_leg_share_cap: float,
) -> PooledPnlVetoOutcome:
    """SS6.1's mandatory, alpha-free, veto-only pooled-P&L gate.

    Checked in this order, deliberately: a failed primary is `REJECTED`
    outright; a passing primary with non-positive pooled P&L is
    `PRIMARY_PASSED_PNL_VETO`/`POOLED_PNL_NON_POSITIVE` -- checked BEFORE the
    concentration screen, because SS6.1 states the money-losing-CONFIRM gap is
    closed by the strict pooled-P&L condition, and the leg-share cap is only
    an ADDITIONAL robustness screen on top of it (SS6.1 "What it does NOT
    do"). Only a passing primary with POSITIVE pooled P&L reaches the leg-
    share check.
    """
    if max_single_day_leg_share_cap != MAX_SINGLE_DAY_LEG_SHARE:
        raise NonPinnedLegShareCapError(
            f"NON_PINNED_LEG_SHARE_CAP: max_single_day_leg_share_cap="
            f"{max_single_day_leg_share_cap} != MAX_SINGLE_DAY_LEG_SHARE={MAX_SINGLE_DAY_LEG_SHARE}"
        )
    if not primary_excludes_zero:
        return PooledPnlVetoOutcome(status="REJECTED", veto_reason="NONE")
    if pooled_net_pnl_per_contract <= 0:
        return PooledPnlVetoOutcome(
            status="PRIMARY_PASSED_PNL_VETO", veto_reason="POOLED_PNL_NON_POSITIVE"
        )
    if max_single_day_leg_share > max_single_day_leg_share_cap:
        return PooledPnlVetoOutcome(
            status="PRIMARY_PASSED_PNL_VETO", veto_reason="LEG_SHARE_ABOVE_CAP"
        )
    return PooledPnlVetoOutcome(status="CONFIRMED", veto_reason="NONE")


def write_hypothesis_ledger(path: Path, records: Sequence[HypothesisRecord]) -> None:
    """Atomic whole-file rewrite: one line per `hypothesis_id`, temp file plus
    `os.replace` (mirrors `write_replay_sufficiency`). A crash leaves the
    prior file intact."""
    ordered = sorted(records, key=lambda record: record.hypothesis_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for record in ordered:
                handle.write(json.dumps(record.to_dict(), sort_keys=True))
                handle.write("\n")
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def read_hypothesis_ledger(path: Path) -> tuple[HypothesisRecord, ...]:
    """Parse `hypothesis_ledger.jsonl`. Refuses (never silently drops or
    last-wins) on an unrecognised `schema_version` or a duplicate
    `hypothesis_id`."""
    records: list[HypothesisRecord] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            payload = json.loads(line)
            version = payload.get("schema_version")
            if version not in _SUPPORTED_SCHEMA_VERSIONS:
                raise UnknownHypothesisLedgerSchemaError(
                    f"{path}:{line_number}: unknown hypothesis_ledger schema_version "
                    f"{version!r} (expected one of {sorted(_SUPPORTED_SCHEMA_VERSIONS)})"
                )
            record = HypothesisRecord.from_dict(payload)
            if record.hypothesis_id in seen:
                raise DuplicateHypothesisLedgerRecordError(
                    f"{path}:{line_number}: duplicate hypothesis_id={record.hypothesis_id!r}"
                )
            seen.add(record.hypothesis_id)
            records.append(record)
    return tuple(records)
