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
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from breezy.settlement.trial_scorer import ScoredTrial, SettlementBasis

__all__ = ["SCORED_TRIAL_SCHEMA", "read_scored_trials", "write_scored_trials"]

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
    }


def _scored_trial_from_row(row: dict[str, Any]) -> ScoredTrial:
    settlement_basis: SettlementBasis = row["settlement_basis"]
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
    )
