"""The registry database's schema constants and row decoder (ARCH-0 seam A 6f; ruling A6f-R4).

Pyarrow-free: ``registry_store`` (the one writer) and ``registry_export`` (the reader) both build on
these names, so neither imports the other's private state and the reader does not reach pyarrow.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from breezy.persistence.autonomy.schemas import TransitionRow
from breezy.persistence.autonomy.wire import WireRefused, parse_json_exact

__all__ = [
    "APPLICATION_ID",
    "COLUMNS",
    "DDL_OBJECTS",
    "SCHEMA_ID",
    "SELECT_MASTER",
    "SELECT_ROWS",
    "USER_VERSION",
    "RowDecodeError",
    "row_from_record",
]

SCHEMA_ID: Final = "registry/v1"
USER_VERSION: Final = 1
APPLICATION_ID: Final = 0x42524759

#: The ``transitions`` columns, in table order (AUT-5 r7 3.2).
COLUMNS: Final[tuple[str, ...]] = (
    "seq", "venue", "venue_seq", "transition_id", "family_id", "family_prior_seq",
    "paired_transition_id", "from_state", "to_state", "kind", "cause_verdict_ids", "cause_code",
    "halt_cause_class", "trigger_cause_class", "voids_transition_ids", "manifest_sha256",
    "artefact_sha256", "lineage_root_family_id", "attest_valid_until_ns", "k_life", "alpha_k",
    "n_min_eff", "n_cap", "nomination_feasible", "hwm_from", "hwm_to", "carried_counters", "drill",
    "drill_clause_sha256", "policy_ruling_id", "policy_ruling_sha256", "decided_by",
    "invocation_id", "engine_code_sha", "expected_prior_seq", "effective_launch_date", "ts_ns",
    "prev_transition_hash", "transition_hash",
)  # fmt: skip

_TABLE_DDL: Final = """CREATE TABLE transitions (
    seq INTEGER PRIMARY KEY,
    venue TEXT NOT NULL,
    venue_seq INTEGER NOT NULL,
    transition_id TEXT NOT NULL,
    family_id TEXT NOT NULL,
    family_prior_seq INTEGER NOT NULL,
    paired_transition_id TEXT,
    from_state TEXT,
    to_state TEXT NOT NULL,
    kind TEXT NOT NULL,
    cause_verdict_ids TEXT NOT NULL,
    cause_code TEXT,
    halt_cause_class TEXT,
    trigger_cause_class TEXT,
    voids_transition_ids TEXT,
    manifest_sha256 TEXT,
    artefact_sha256 TEXT,
    lineage_root_family_id TEXT,
    attest_valid_until_ns INTEGER,
    k_life INTEGER,
    alpha_k TEXT,
    n_min_eff INTEGER,
    n_cap INTEGER,
    nomination_feasible INTEGER CHECK (nomination_feasible IN (0, 1)),
    hwm_from INTEGER,
    hwm_to INTEGER,
    carried_counters TEXT,
    drill INTEGER NOT NULL CHECK (drill IN (0, 1)),
    drill_clause_sha256 TEXT,
    policy_ruling_id TEXT NOT NULL,
    policy_ruling_sha256 TEXT NOT NULL,
    decided_by TEXT NOT NULL,
    invocation_id TEXT NOT NULL,
    engine_code_sha TEXT NOT NULL,
    expected_prior_seq INTEGER NOT NULL,
    effective_launch_date TEXT,
    ts_ns INTEGER NOT NULL,
    prev_transition_hash TEXT NOT NULL,
    transition_hash TEXT NOT NULL,
    UNIQUE (venue, venue_seq),
    UNIQUE (transition_id)
)"""
_NO_UPDATE_DDL: Final = """CREATE TRIGGER transitions_no_update BEFORE UPDATE ON transitions
BEGIN
    SELECT RAISE(ABORT, 'append-only');
END"""
_NO_DELETE_DDL: Final = """CREATE TRIGGER transitions_no_delete BEFORE DELETE ON transitions
BEGIN
    SELECT RAISE(ABORT, 'append-only');
END"""
#: V11: ``COALESCE`` makes the first row of a venue demand ``venue_seq = 1``; without it the
#: comparison is NULL and a genesis at any number would pass.
_INSERT_GUARD_DDL: Final = """CREATE TRIGGER transitions_insert_guard BEFORE INSERT ON transitions
BEGIN
    SELECT RAISE(ABORT, 'seq exists')
    WHERE NEW.seq IS NOT NULL AND EXISTS (SELECT 1 FROM transitions WHERE seq = NEW.seq);
    SELECT RAISE(ABORT, 'transition_id exists')
    WHERE EXISTS (SELECT 1 FROM transitions WHERE transition_id = NEW.transition_id);
    SELECT RAISE(ABORT, 'venue_seq duplicate')
    WHERE EXISTS (
        SELECT 1 FROM transitions WHERE venue = NEW.venue AND venue_seq = NEW.venue_seq
    );
    SELECT RAISE(ABORT, 'venue_seq gap')
    WHERE NEW.venue_seq <> COALESCE(
        (SELECT MAX(venue_seq) FROM transitions WHERE venue = NEW.venue), 0
    ) + 1;
END"""
_META_DDL: Final = "CREATE TABLE meta (schema TEXT NOT NULL)"

#: ``(sqlite_master type, name, sql)`` for every object the store owns, in creation order.
DDL_OBJECTS: Final[tuple[tuple[str, str, str], ...]] = (
    ("table", "transitions", _TABLE_DDL),
    ("trigger", "transitions_no_update", _NO_UPDATE_DDL),
    ("trigger", "transitions_no_delete", _NO_DELETE_DDL),
    ("trigger", "transitions_insert_guard", _INSERT_GUARD_DDL),
    ("table", "meta", _META_DDL),
)

#: Every row of the ``transitions`` table, in column order.
SELECT_ROWS: Final = f"SELECT {', '.join(COLUMNS)} FROM transitions"
SELECT_MASTER: Final = (
    "SELECT type, name, sql FROM sqlite_master "
    "WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite\\_stat%' ESCAPE '\\'"
)

_ID_LIST_COLUMNS: Final = ("cause_verdict_ids", "voids_transition_ids")
_BOOL_COLUMNS: Final = ("drill", "nomination_feasible")


class RowDecodeError(ValueError):
    """A stored record does not decode to a C5 row (the data no longer fits the schema)."""


def _decode_ids(text: object) -> list[str] | None:
    if text is None:
        return None
    if not isinstance(text, str):
        raise RowDecodeError("id list column is not text")
    return text.split(",") if text else []


def row_from_record(record: Sequence[object]) -> TransitionRow:
    """The sealed row of one ``SELECT_ROWS`` record; ``RowDecodeError`` if it does not decode."""
    obj: dict[str, object] = dict(zip(COLUMNS, record, strict=True))
    for name in _ID_LIST_COLUMNS:
        obj[name] = _decode_ids(obj[name])
    for name in _BOOL_COLUMNS:
        if obj[name] is not None:
            obj[name] = obj[name] == 1
    counters = obj["carried_counters"]
    try:
        if counters is not None:
            obj["carried_counters"] = parse_json_exact(str(counters))
        return TransitionRow.from_wire(obj)
    except WireRefused as exc:
        raise RowDecodeError(f"stored row does not decode: {exc.reason.value}") from exc
