"""Append-only parquet store for `ScoredTrial` rows (6c, review item 8).

Lives under `persistence/`, not `settlement/`: `src/breezy/settlement/` is an
AST-enforced PURE package
(`tests/unit/test_settlement_purity_guard.py`, rule D1 -- no `datetime`,
`os`, `pathlib`, `time`, or similar side-effecting/non-deterministic imports
anywhere under it), and this module does real, atomic file I/O. The layer
contract (`pyproject.toml` `[tool.importlinter]`) places `persistence` ABOVE
`settlement`, so importing `breezy.settlement.trial_scorer.ScoredTrial` from
here is the correct direction; the reverse would not be.

`SqliteStateStore` (`runtime/sqlite_store.py`) is key->BLOB with `get`/`set`
only -- no iteration, no aggregation -- so it cannot serve the queried table
6d must scan (a GENUINE gap, not a native decline). `pyarrow` is a transitive
dependency of `nautilus-trader` and is imported directly here, never pinned.

Decimal fields are stored as text (`Decimal(str(v))`, the repo idiom at
`adapters/polymarket_us/parsing.py:382`): `pa.decimal128` was rejected
because its fixed scale at schema-definition time risks silent truncation of
a value the schema did not anticipate. `climate_day` is likewise stored as
plain text (an ISO-8601 date string) rather than `pa.date32`, matching
`ScoredTrial.climate_day`'s own `str` type (itself forced by the D1 purity
rule -- see `trial_scorer.py`'s `FilledTrial` docstring).

One file per score run, named for the run's own `now_ns` so filenames sort
chronologically; writes never rewrite an existing file -- a re-score is
always a NEW file with a new row. The write is atomic
(`tempfile.mkstemp(dir=target)` + `os.replace`, the pattern at
`runtime/health.py:322,330`). Readers dedupe by `(trial_id, max score_seq)`,
so a superseded score row is never double-counted by a caller who reads the
whole directory.
"""

from __future__ import annotations

import datetime as dt
import os
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from breezy.settlement.trial_scorer import BucketSource, ScoredTrial, SettlementBasis

__all__ = [
    "SCORED_TRIAL_SCHEMA",
    "PooledScoredTrials",
    "read_scored_trials",
    "read_scored_trials_pooled",
    "write_scored_trials",
]

#: Pinned column-for-column (review item 8 plus the `settlement_basis` /
#: `excluded_reason` / `slippage` columns items 1, 2 and 6 require).
SCORED_TRIAL_SCHEMA: pa.Schema = pa.schema(
    [
        pa.field("trial_id", pa.string(), nullable=False),
        pa.field("station", pa.string(), nullable=False),
        pa.field("climate_day", pa.string(), nullable=False),
        pa.field("instrument_id", pa.string(), nullable=False),
        pa.field("settlement_tmax_f", pa.int32(), nullable=False),
        pa.field("held", pa.bool_(), nullable=False),
        pa.field("pnl", pa.string(), nullable=False),
        pa.field("revision_seq", pa.int32(), nullable=False),
        pa.field("raw_sha256", pa.string(), nullable=False),
        pa.field("scored_at_ns", pa.int64(), nullable=False),
        pa.field("score_seq", pa.int32(), nullable=False),
        pa.field("settlement_basis", pa.string(), nullable=False),
        pa.field("excluded_reason", pa.string(), nullable=True),
        pa.field("slippage", pa.string(), nullable=False),
        pa.field("entry_ask", pa.string(), nullable=False),
        pa.field("fill_px", pa.string(), nullable=False),
        pa.field("fee", pa.string(), nullable=False),
        #: Additive (2026-09-16, defect fix): absent on any file written
        #: before this column existed -- `read_table(path, schema=...)`
        #: fills a genuinely missing column with `None` for every row of an
        #: older file (measured), and `_scored_trial_from_row` maps that
        #: `None` back to `ScoredTrial.bucket_source`'s own "catalog"
        #: default, so an old row's meaning is unchanged.
        pa.field("bucket_source", pa.string(), nullable=True),
    ]
)

_FILE_PREFIX: str = "scored_trials_"
_FILE_SUFFIX: str = ".parquet"


def write_scored_trials(directory: Path, trials: Sequence[ScoredTrial], *, now_ns: int) -> Path:
    """Write one score run's `trials` as a new parquet file under `directory`.

    Never rewrites an existing file. `now_ns` (the caller's own clock reading
    for this run, never read from the wall clock here) names the file so
    concurrent runs cannot collide and readers can order runs without
    parsing row contents.
    """
    directory.mkdir(parents=True, exist_ok=True)
    rows = [_row_from_scored_trial(trial) for trial in trials]
    table = pa.Table.from_pylist(rows, schema=SCORED_TRIAL_SCHEMA)
    target = directory / f"{_FILE_PREFIX}{_stamp(now_ns)}{_FILE_SUFFIX}"

    fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=f".{_FILE_PREFIX}", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        os.close(fd)
        pq.write_table(table, tmp_path)
        os.replace(tmp_path, target)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    return target


def read_scored_trials(directory: Path) -> tuple[ScoredTrial, ...]:
    """Read every score run under `directory`, deduped by `(trial_id, max score_seq)`.

    An empty or absent directory returns no rows, never an error -- a fresh
    deployment with no score runs yet is a normal state, not a defect.
    """
    if not directory.exists():
        return ()
    latest: dict[str, ScoredTrial] = {}
    for path in sorted(directory.glob(f"{_FILE_PREFIX}*{_FILE_SUFFIX}")):
        table = pq.read_table(path, schema=SCORED_TRIAL_SCHEMA)
        for row in table.to_pylist():
            trial = _scored_trial_from_row(row)
            current = latest.get(trial.trial_id)
            if current is None or trial.score_seq > current.score_seq:
                latest[trial.trial_id] = trial
    return tuple(latest.values())


#: L-38 (`cbd5fec`): `score-live-trials-run.sh` now writes each REGISTERED
#: family's rows to its OWN `<store>/<family_id>/` subdirectory rather than
#: a shared top-level directory, because `family_tally_v2.py`'s
#: contamination barrier (`FamilyStoreContaminationError`) forbids a shared
#: store. `read_scored_trials` itself stays non-recursive and single-
#: directory (its existing per-family and legacy callers are unchanged); a
#: caller that wants the union across every family -- the live/pooled
#: diagnostic tally and the two nightly studies that join on `trial_id`
#: (`live_family_tally.py`, `position_monitor_nightly_report.py`,
#: `current_rung_hold_exit_window_study.py`) -- calls this instead.
_LEGACY_SOURCE_LABEL: str = "(top-level)"


@dataclass(frozen=True, slots=True, kw_only=True)
class PooledScoredTrials:
    """The union of every per-family scored-trial store under a base
    directory, plus any legacy top-level parquet files written directly
    under it (the pre-L-38 layout, kept working for a store that has not
    been migrated). `family_counts` is `(source_label, row_count)` in
    discovery order -- `"(top-level)"` for the legacy rows (only present
    when at least one legacy row exists), then one entry per non-empty
    subdirectory named for its `family_id` (L-38's own convention: the
    subdirectory name IS the family id). Rows are never deduped across
    sources: `family_tally_v2.py`'s own contamination barrier already keeps
    each per-family store disjoint from every other by `trial_id` manifest
    prefix, and legacy top-level rows predate any per-family store existing
    at all.
    """

    rows: tuple[ScoredTrial, ...]
    family_counts: tuple[tuple[str, int], ...]


def read_scored_trials_pooled(base_dir: Path) -> PooledScoredTrials:
    """Read `base_dir`'s own legacy top-level parquet files (if any) UNION
    every immediate subdirectory's parquet files (if any), each read via
    `read_scored_trials` unmodified.

    An absent or fully empty `base_dir` returns no rows and no breakdown
    entries -- the same "never an error" contract `read_scored_trials`
    itself carries: a fresh deployment with no score runs yet, or one that
    has not scored today's family yet, is a normal state, not a defect.
    """
    legacy_rows = read_scored_trials(base_dir)
    rows: list[ScoredTrial] = list(legacy_rows)
    counts: list[tuple[str, int]] = []
    if legacy_rows:
        counts.append((_LEGACY_SOURCE_LABEL, len(legacy_rows)))
    if base_dir.exists():
        for child in sorted(p for p in base_dir.iterdir() if p.is_dir()):
            family_rows = read_scored_trials(child)
            if not family_rows:
                continue
            rows.extend(family_rows)
            counts.append((child.name, len(family_rows)))
    return PooledScoredTrials(rows=tuple(rows), family_counts=tuple(counts))


def _stamp(now_ns: int) -> str:
    seconds, nanos = divmod(now_ns, 1_000_000_000)
    stamp = dt.datetime.fromtimestamp(seconds, tz=dt.UTC).strftime("%Y%m%dT%H%M%S")
    return f"{stamp}{nanos:09d}Z"


def _row_from_scored_trial(trial: ScoredTrial) -> dict[str, Any]:
    return {
        "trial_id": trial.trial_id,
        "station": trial.station,
        "climate_day": trial.climate_day,
        "instrument_id": trial.instrument_id,
        "settlement_tmax_f": trial.settlement_tmax_f,
        "held": trial.held,
        "pnl": str(trial.pnl),
        "revision_seq": trial.revision_seq,
        "raw_sha256": trial.raw_sha256,
        "scored_at_ns": trial.scored_at_ns,
        "score_seq": trial.score_seq,
        "settlement_basis": trial.settlement_basis,
        "excluded_reason": trial.excluded_reason,
        "slippage": str(trial.slippage),
        "entry_ask": str(trial.entry_ask),
        "fill_px": str(trial.fill_px),
        "fee": str(trial.fee),
        "bucket_source": trial.bucket_source,
    }


def _scored_trial_from_row(row: dict[str, Any]) -> ScoredTrial:
    settlement_basis: SettlementBasis = row["settlement_basis"]
    #: `.get` (not `row["bucket_source"]`): a pre-existing file written
    #: before this column existed decodes with the column present but
    #: `None` for every row (module docstring); a stored `None` maps to
    #: `ScoredTrial.bucket_source`'s own "catalog" default either way.
    bucket_source: BucketSource = row.get("bucket_source") or "catalog"
    return ScoredTrial(
        trial_id=row["trial_id"],
        station=row["station"],
        climate_day=row["climate_day"],
        instrument_id=row["instrument_id"],
        settlement_tmax_f=row["settlement_tmax_f"],
        held=row["held"],
        pnl=Decimal(row["pnl"]),
        revision_seq=row["revision_seq"],
        raw_sha256=row["raw_sha256"],
        scored_at_ns=row["scored_at_ns"],
        score_seq=row["score_seq"],
        settlement_basis=settlement_basis,
        excluded_reason=row["excluded_reason"],
        slippage=Decimal(row["slippage"]),
        entry_ask=Decimal(row["entry_ask"]),
        fill_px=Decimal(row["fill_px"]),
        fee=Decimal(row["fee"]),
        bucket_source=bucket_source,
    )
