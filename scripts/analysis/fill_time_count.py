"""FILL-TIME count of filled Takes for the v1 structural-dead stop.

`build_live_family_tally`'s `filled_takes` parameter
(`live_family_tally.py:242-267`) MUST be a fill-time count -- fills,
including any not yet settled/scored -- never a count derived from the 6c
SCORED-trial store (`len(rows)`), because a Take that filled today but has
not yet resolved an NWS-final settlement is invisible to that store
(`trial_scorer.score_trial` requires a settlement basis). This module is
that reader.

Source chosen, and the null hypothesis
---------------------------------------
**Null hypothesis: does Nautilus's own `Cache`/`CacheDatabase` already
persist fills queryable offline?** No. Verified by reading the installed
`nautilus_trader==1.231.0` in `.venv/` (`runtime/sqlite_store.py`'s own
docstring, `sqlite_store.py:3-46`, pins the same finding with cited
`path:line`s): `Cache.add` forwards to a database only
`if self._database is not None` (`cache/cache.pyx:1704-1708`), and Breezy
configures `CacheConfig(database=None, flush_on_start=False)` for every
node role (`node_config.py:217,500,759`) -- there is no Redis in this
deployment, the only backing store Nautilus's kernel accepts
(`system/kernel.py:310-329`). So `Cache` is memory-only here and answers
nothing after process exit. Native cache is ruled out.

**Source chosen: the exec-state `SqliteStateStore`
(`runtime/sqlite_store.py`), the SAME physical file the live trading
process already opens for two durable records written at fill time or
decision time by the live path itself:**

* `current_rung_hold/trial/{station}/{climate_day}` -- a `TrialDayRecord`
  (`strategy/current_rung_hold/trial_day_latch.py:112-171`), written by
  `TrialDayLatch.consume` (`trial_day_latch.py:199` via
  `strategy.py:456-462`) at DECISION time, carrying `reason` ("taken" for a
  Take) and the `instrument_id` traded.
* `exec/polymarket_us/fill/{venue_order_id}` -- a `DurableFillRecord`
  (`adapters/polymarket_us/exec/client.py:410-482`), written at fill
  application by R-7 (`client.py:1315-1337`, "Written at fill application
  (R-7)" per the module's own `FILL_KEY_PREFIX` comment, `client.py:335-337`),
  carrying the `instrument_id` that filled -- durable the instant
  `SqliteStateStore.set` COMMITs (`sqlite_store.py` docstring), independent
  of whether that fill has since been scored or settled.

Both records live in the ONE shared `state` table
(`sqlite_store.py:78`, `key TEXT PRIMARY KEY, value BLOB`): the trial-day
latch is bound to the SAME store and the SAME flock an already-opened
`SubmitIntentLatch` holds (`trial_day_latch.py` module docstring, "over the
SAME store"), and the exec client's `state_store_opener` is built from the
SAME `state_store_path` the composition root already used to open that
latch (`node_config.py:713,747`). There is no second file to reconcile.

**The join.** Neither record carries the other's key directly (a fill
record is keyed by `venue_order_id`, not by station/day), but each trial
that resulted in a Take records the exact `instrument_id` it traded
(`TrialDayRecord.instrument_id`), and each fill record independently records
the `instrument_id` that filled (`DurableFillRecord.instrument_id`). A
"taken" trial whose `instrument_id` appears in ANY fill record -- settled or
not -- is a filled Take. This reuses both records' real, already-durable
fields; it introduces no new store, no new schema, and no new write path.

Fails closed (returns `None`) when the file is absent or cannot be read as
this schema -- never inferred as zero, per `StructuralDeadVerdict`'s own
contract (`structural_dead_stop.py:80-93`).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from breezy.adapters.polymarket_us.errors import ExecutionReportMappingError
from breezy.adapters.polymarket_us.exec.client import FILL_KEY_PREFIX, DurableFillRecord
from breezy.strategy.current_rung_hold.trial_day_latch import (
    TrialDayRecord,
    TrialDayRecordCorrupt,
)

__all__ = ["count_filled_takes"]

#: The one non-refusal `TrialDayRecord.reason` value -- see `trial_day_latch`'s
#: own `_REASONS` closed set (`decision.py:REFUSAL_REASONS | {"taken"}`).
_TAKEN_REASON = "taken"


def _open_readonly(path: Path) -> sqlite3.Connection | None:
    """Open `path` read-only, or return `None` if that is not possible.

    A read-only URI connection never creates the file and never takes a
    write lock, so this reader cannot contend with the live process's own
    writer -- it is a pure observer of whatever has already been committed.
    """
    if not path.is_file():
        return None
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        conn.execute("SELECT 1 FROM state LIMIT 1")
        return conn
    except sqlite3.Error:
        return None


def count_filled_takes(
    source_path: Path,
    *,
    family_prefix: str,
    since_climate_day: str | None = None,
) -> int | None:
    """Count distinct "taken" trials under `family_prefix` with a matching
    fill record, read from the shared exec-state `SqliteStateStore` at
    `source_path`.

    Returns `None` -- fail closed, never zero -- when `source_path` is
    absent or cannot be read as this schema. `family_prefix` scopes to one
    provenance (e.g. `"current_rung_hold/trial/"` for the live family;
    `"paper_replay/current_rung_hold/trial/"` never matches that prefix and
    is correctly excluded by a plain `str.startswith` test).
    `since_climate_day`, when given, drops any trial whose `climate_day`
    string-compares less than it (ISO-8601 dates sort lexicographically).
    """
    conn = _open_readonly(source_path)
    if conn is None:
        return None
    try:
        rows = conn.execute("SELECT key, value FROM state").fetchall()
    except sqlite3.Error:
        return None
    finally:
        conn.close()

    filled_instrument_ids: set[str] = set()
    for key, value in rows:
        if not isinstance(key, str) or not key.startswith(FILL_KEY_PREFIX):
            continue
        try:
            record = DurableFillRecord.from_bytes(value)
        except ExecutionReportMappingError:
            continue
        filled_instrument_ids.add(record.instrument_id)

    counted_trial_keys: set[str] = set()
    for key, value in rows:
        if not isinstance(key, str) or not key.startswith(family_prefix):
            continue
        remainder = key[len(family_prefix) :]
        parts = remainder.split("/")
        if len(parts) != 2:
            continue
        _station, climate_day = parts
        if since_climate_day is not None and climate_day < since_climate_day:
            continue
        try:
            trial = TrialDayRecord.from_bytes(value)
        except TrialDayRecordCorrupt:
            continue
        if trial.reason != _TAKEN_REASON:
            continue
        if trial.instrument_id in filled_instrument_ids:
            counted_trial_keys.add(key)

    return len(counted_trial_keys)
