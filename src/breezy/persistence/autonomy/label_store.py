"""C2 label store: write-once ``label/v1`` parquet files and the one consumer gate (AUT-2 r7 WP2).

One parquet file per labelling run is published at
``derived/labels/<family_id>/labels_<now_ns>.parquet`` (ARCH C2; plan r7 section 3.2.2). The schema
is the ARCH-0 pin, :data:`label_schema.LABEL_V1_ARROW_SCHEMA`; this module adds no column. The file
bytes are built in memory and published through ``single_read.write_once`` (a temp file linked into
place), so a reader never sees a partial file and a second write to the same name is refused.

Reads dedupe on ``(label_id, max label_seq)``: a correction is a new row at ``label_seq + 1``.

``labels_consumable`` is the one predicate every consumer uses to decide whether the newest run
marker lets it read labels (plan r7 section 3.12). It lives here, once, so portfolio-roi, AUT-3 and
AUT-4 cannot drift apart.

Money values are canonical decimal strings (``canonical.decimal_str``), never floats; the two
probabilities are the only ``float64`` columns, as ARCH names them. This module reaches ``pyarrow``
and is therefore outside import contract (c), like ``label_schema``.
"""

from __future__ import annotations

import io
import math
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, fields
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

import pyarrow as pa
import pyarrow.parquet as pq

from breezy.persistence.autonomy.canonical import decimal_str
from breezy.persistence.autonomy.label_schema import (
    LABEL_SCHEMA_ID,
    LABEL_V1_ARROW_SCHEMA,
    ExcludedReason,
    LabelRole,
    PSource,
)
from breezy.persistence.autonomy.paths import family_component
from breezy.persistence.autonomy.single_read import (
    ReadPolicy,
    SingleReadReason,
    SingleReadRefused,
    ensure_dir,
    open_root,
    read_once_at,
    walk_dirs,
    write_once,
)
from breezy.persistence.autonomy.wire import WireRefused

__all__ = [
    "LABELS_DIR",
    "LABEL_FILE_MODE",
    "MARKER_STALE_H",
    "ConflictingLabelRows",
    "InvalidLabelRow",
    "LabelMarker",
    "LabelRow",
    "LabelStoreError",
    "RunOutcome",
    "UnknownLabelSchema",
    "UnmappedScorerReason",
    "admissible_rows",
    "label_relative_path",
    "labels_consumable",
    "read_labels",
    "write_labels",
]

LABELS_DIR: Final[tuple[str, ...]] = ("derived", "labels")
LABEL_FILE_MODE: Final[int] = 0o600
#: The newest run marker is stale past this age (plan r7 section 3.12; ``LABEL_MARKER_STALE_H``).
MARKER_STALE_H: Final[int] = 26
_SCHEMA_META_KEY: Final[bytes] = b"breezy_label_schema"
_MAX_LABEL_FILE_BYTES: Final[int] = 256 * 1024 * 1024
_NS_PER_H: Final[int] = 3_600_000_000_000
_FILE_PREFIX: Final[str] = "labels_"
_FILE_SUFFIX: Final[str] = ".parquet"

#: The money columns, in schema order: canonical decimal strings, ``Decimal`` in memory.
_MONEY_FIELDS: Final[tuple[str, ...]] = (
    "qty",
    "fill_px",
    "entry_ask",
    "fee_reconciled",
    "slippage",
    "settlement_tmax_f",
    "realized_pnl",
    "counterfactual_hold_pnl",
    "reconciliation_delta",
)
_PROBABILITY_FIELDS: Final[tuple[str, ...]] = ("p_at_decision", "p_raw_at_decision")


class LabelStoreError(Exception):
    """Base of every label-store refusal."""


class UnknownLabelSchema(LabelStoreError):
    """A label file whose schema or schema-version stamp is not exactly ``label/v1``."""


class UnmappedScorerReason(LabelStoreError):
    """An ``excluded_reason`` outside the closed C2 vocabulary: the scorer mapping is total."""


class InvalidLabelRow(LabelStoreError):
    """A row that breaks a C2 invariant (type, probability range, source or family)."""


class ConflictingLabelRows(LabelStoreError):
    """Two stored rows share ``(label_id, label_seq)`` but differ in content."""


class RunOutcome(StrEnum):
    LABELLED = "LABELLED"
    PENDING = "PENDING"
    NO_INPUT = "NO_INPUT"
    FAILED_IDENTITY = "FAILED_IDENTITY"


@dataclass(frozen=True)
class LabelRow:
    """One C2 ``label/v1`` row. Field order is the ARCH column order (test-pinned)."""

    # identity
    label_id: str
    decision_id: str | None
    family_id: str
    trial_id: str
    client_order_id: str
    trade_id: str | None
    # market
    station: str
    climate_day: str
    instrument_id: str
    rung_id: str
    leg: str
    role: LabelRole
    # fill
    qty: Decimal
    fill_px: Decimal
    entry_ask: Decimal | None
    fee_reconciled: Decimal | None
    slippage: Decimal | None
    # the bought leg's win probability
    p_at_decision: float | None
    p_raw_at_decision: float | None
    p_source: PSource
    # settlement
    settled_outcome: bool | None
    settlement_tmax_f: Decimal | None
    settlement_basis: str | None
    # P&L
    realized_pnl: Decimal | None
    counterfactual_hold_pnl: Decimal | None
    # reconciliation
    reconciled: bool
    reconciliation_delta: Decimal | None
    reconciliation_source: str
    net_position_key: str
    # admissibility
    admissible: bool
    excluded_reason: ExcludedReason | None
    # run metadata
    labelled_at_ns: int
    label_seq: int
    scorer_id: str


@dataclass(frozen=True)
class LabelMarker:
    """The newest run marker's gate-relevant fields (plan r7 section 3.12).

    ``written_at_ns`` is the ``now_ns`` in the marker's file name. The marker file itself is
    written by the label run; this type is what a consumer hands :func:`labels_consumable`.
    """

    run_outcome: RunOutcome
    pending: int
    unresolved: int
    missing_label: int
    written_at_ns: int


def labels_consumable(marker: LabelMarker | None, *, now_ns: int) -> bool:
    """False (GATED) iff the marker is absent or stale, the run FAILED_IDENTITY, or anything is
    pending, unresolved or missing a label. Every consumer reads labels through this one rule."""
    if marker is None:
        return False
    if now_ns - marker.written_at_ns > MARKER_STALE_H * _NS_PER_H:
        return False
    if marker.run_outcome is RunOutcome.FAILED_IDENTITY:
        return False
    return marker.pending + marker.unresolved + marker.missing_label == 0


def label_relative_path(family_id: str, now_ns: int) -> tuple[str, ...]:
    """Path parts of one run's file below the data root; ``family_id`` is validated."""
    if isinstance(now_ns, bool) or not isinstance(now_ns, int) or now_ns < 0:
        raise InvalidLabelRow("now_ns must be a non-negative int")
    return (*LABELS_DIR, family_component(family_id), f"{_FILE_PREFIX}{now_ns}{_FILE_SUFFIX}")


def _as_decimal(name: str, value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Decimal) or not value.is_finite():
        raise InvalidLabelRow(f"{name} must be a finite Decimal or None, never a float")
    return value


def _as_probability(name: str, value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, float) or not math.isfinite(value):
        raise InvalidLabelRow(f"{name} must be a finite float or None")
    if not 0.0 <= value <= 1.0:
        raise InvalidLabelRow(f"{name} must lie in [0, 1]")
    return value


def _as_excluded_reason(value: object) -> ExcludedReason | None:
    if value is None:
        return None
    if isinstance(value, ExcludedReason):
        return value
    try:
        return ExcludedReason(str(value))
    except ValueError as exc:
        raise UnmappedScorerReason("excluded_reason is outside the closed C2 vocabulary") from exc


def _as_p_source(value: object) -> PSource:
    try:
        return PSource(str(value))
    except ValueError as exc:
        raise InvalidLabelRow("p_source is outside the closed C2 set") from exc


def _validated(row: LabelRow, family_id: str) -> LabelRow:
    if row.family_id != family_id:
        raise InvalidLabelRow("a row's family_id must equal the file's family")
    for name in ("admissible", "reconciled"):
        if not isinstance(getattr(row, name), bool):
            raise InvalidLabelRow(f"{name} must be a bool")
    stamp = row.labelled_at_ns
    if isinstance(stamp, bool) or not isinstance(stamp, int) or stamp < 0:
        raise InvalidLabelRow("labelled_at_ns must be a non-negative int")
    p_source = _as_p_source(row.p_source)
    p_at = _as_probability("p_at_decision", row.p_at_decision)
    p_raw = _as_probability("p_raw_at_decision", row.p_raw_at_decision)
    if p_source is PSource.C1_DECISION and p_at is None:
        raise InvalidLabelRow("a c1_decision row must carry p_at_decision")
    try:
        role = LabelRole(row.role)
    except ValueError as exc:
        raise InvalidLabelRow("role is outside {entry, exit}") from exc
    if isinstance(row.label_seq, bool) or not isinstance(row.label_seq, int) or row.label_seq < 0:
        raise InvalidLabelRow("label_seq must be a non-negative int")
    values: dict[str, Any] = {name: _as_decimal(name, getattr(row, name)) for name in _MONEY_FIELDS}
    return LabelRow(
        **{
            **{f.name: getattr(row, f.name) for f in fields(LabelRow)},
            **values,
            "p_at_decision": p_at,
            "p_raw_at_decision": p_raw,
            "p_source": p_source,
            "role": role,
            "excluded_reason": _as_excluded_reason(row.excluded_reason),
        }
    )


def _wire(row: LabelRow) -> dict[str, Any]:
    """One row as arrow-ready python values: decimals as canonical strings, enums as their value."""
    wire: dict[str, Any] = {}
    for f in fields(LabelRow):
        value = getattr(row, f.name)
        if f.name in _MONEY_FIELDS:
            wire[f.name] = None if value is None else decimal_str(value)
        elif isinstance(value, ExcludedReason | PSource | LabelRole):
            wire[f.name] = value.value
        else:
            wire[f.name] = value
    return wire


def _serialise(rows: Sequence[dict[str, Any]]) -> bytes:
    schema = LABEL_V1_ARROW_SCHEMA.with_metadata({_SCHEMA_META_KEY: LABEL_SCHEMA_ID.encode()})
    table = pa.Table.from_pylist(list(rows), schema=schema)
    sink = io.BytesIO()
    pq.write_table(table, sink)
    return sink.getvalue()


def write_labels(data_root: Path, family_id: str, rows: Sequence[LabelRow], *, now_ns: int) -> Path:
    """Publish one run's rows for ``family_id`` and return the file path.

    Every row is validated first (nothing is written for a bad row). The file is write-once: a
    second call for the same ``(family_id, now_ns)`` with different rows raises
    ``SingleReadRefused(EXISTS_DIFFERENT)``; identical bytes are an idempotent no-op.
    """
    parts = label_relative_path(family_id, now_ns)
    checked = [_validated(row, family_id) for row in rows]
    data = _serialise([_wire(row) for row in checked])
    rootfd = open_root(data_root)
    try:
        os.close(ensure_dir(rootfd, parts[:-1]))
    finally:
        os.close(rootfd)
    path = data_root.joinpath(*parts)
    write_once(path, data, root=data_root, mode=LABEL_FILE_MODE)
    return path


def _row_of(wire: Mapping[str, Any]) -> LabelRow:
    """One stored row; any decode failure is an ``InvalidLabelRow`` chained from its cause."""
    try:
        values: dict[str, Any] = dict(wire)
        for name in _MONEY_FIELDS:
            raw = values[name]
            values[name] = None if raw is None else Decimal(raw)
        values["p_source"] = PSource(values["p_source"])
        values["role"] = LabelRole(values["role"])
        reason = values["excluded_reason"]
        values["excluded_reason"] = None if reason is None else ExcludedReason(reason)
        return LabelRow(**values)
    except (InvalidOperation, ValueError, TypeError, KeyError) as exc:
        raise InvalidLabelRow("a stored label row does not decode") from exc


def _read_file(dirfd: int, name: str) -> list[LabelRow]:
    raw = read_once_at(dirfd, name, max_bytes=_MAX_LABEL_FILE_BYTES, policy=ReadPolicy.STRICT)
    try:
        table = pq.read_table(pa.BufferReader(raw))
    except (pa.ArrowException, OSError) as exc:
        raise UnknownLabelSchema(f"{name} is not a readable parquet file") from exc
    meta = table.schema.metadata or {}
    if meta.get(_SCHEMA_META_KEY) != LABEL_SCHEMA_ID.encode():
        raise UnknownLabelSchema(f"{name} is not stamped {LABEL_SCHEMA_ID}")
    if not table.schema.remove_metadata().equals(LABEL_V1_ARROW_SCHEMA):
        raise UnknownLabelSchema(f"{name} does not match the pinned {LABEL_SCHEMA_ID} columns")
    return [_row_of(wire) for wire in table.to_pylist()]


def _list_dir(dirfd: int) -> list[str]:
    return sorted(os.listdir(dirfd))


def _family_dirs(rootfd: int, family_id: str | None) -> list[str]:
    if family_id is not None:
        return [family_component(family_id)]
    try:
        labels_fd = walk_dirs(rootfd, LABELS_DIR)
    except SingleReadRefused as exc:
        if exc.reason is SingleReadReason.NOT_FOUND:
            return []
        raise
    try:
        return _list_dir(labels_fd)
    finally:
        os.close(labels_fd)


def _check_family(row: LabelRow, directory: str) -> None:
    try:
        expected = family_component(row.family_id)
    except WireRefused as exc:
        raise InvalidLabelRow("a stored row's family_id is not a valid family") from exc
    if expected != directory:
        raise InvalidLabelRow("a stored row's family_id does not match its directory")


def _keep_latest(latest: dict[str, LabelRow], row: LabelRow) -> None:
    kept = latest.get(row.label_id)
    if kept is None or row.label_seq > kept.label_seq:
        latest[row.label_id] = row
    elif row.label_seq == kept.label_seq and row != kept:
        raise ConflictingLabelRows(
            "two stored rows share (label_id, label_seq) with differing content"
        )


def admissible_rows(rows: Iterable[LabelRow]) -> tuple[LabelRow, ...]:
    """The one selection rule for any P&L or ROI aggregate: ``admissible`` rows and nothing else.

    A null ``excluded_reason`` does not make a row eligible (an exit row or a venue-fallback row has
    none and is still inadmissible).
    """
    return tuple(row for row in rows if row.admissible)


def read_labels(data_root: Path, family_id: str | None = None) -> tuple[LabelRow, ...]:
    """Every stored row (one family, or all), deduped to the highest ``label_seq`` per
    ``label_id``. An unreadable file or a foreign schema raises; an absent directory is empty."""
    latest: dict[str, LabelRow] = {}
    rootfd = open_root(data_root)
    try:
        for family in _family_dirs(rootfd, family_id):
            try:
                dirfd = walk_dirs(rootfd, (*LABELS_DIR, family))
            except SingleReadRefused as exc:
                if exc.reason is SingleReadReason.NOT_FOUND:
                    continue
                raise
            try:
                names = [
                    n
                    for n in _list_dir(dirfd)
                    if n.startswith(_FILE_PREFIX) and n.endswith(_FILE_SUFFIX)
                ]
                for name in names:
                    for row in _read_file(dirfd, name):
                        _check_family(row, family)
                        _keep_latest(latest, row)
            finally:
                os.close(dirfd)
    finally:
        os.close(rootfd)
    return tuple(latest.values())
