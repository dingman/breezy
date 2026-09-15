"""Bounded buffer + batched catalog flush for the intra-day position monitor.

L-1: the bounded ``deque(maxlen=...)`` plus best-effort JSONL sidecar mirrors
the native pattern ``OfferTape`` already established
(``strategy/current_rung_hold/offer_tape.py:78-124``); batched persistence
reuses ``breezy.persistence.catalog.write_records``
(``persistence/catalog.py:422``) rather than a raw ``write_data`` call, and
per-position-day summary rows mirror ``scored_trial_store.py:79-121``
byte-for-byte in shape (atomic tempfile + ``os.replace``, dedup by the
latest revision). See
``docs/plans/INTRADAY_POSITION_MONITOR_2026-09-15.md`` Sec 2/4, Rev 2.1
addendum A2.

The monitor catalog is NEVER the quote-tape root (the trader writes no tape
of its own, ``runtime/node_config.py:748-750``) and is partitioned one
directory per climate day (:func:`open_monitor_catalog`), so a
``write_records`` read-back verify -- which re-reads the whole ``ts_init``
window it just wrote -- never scans more than one day's rows (A2).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import tempfile
from collections import deque
from collections.abc import Sequence
from pathlib import Path
from typing import Final

import pyarrow as pa
import pyarrow.parquet as pq
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

from breezy.persistence.catalog import (
    CatalogWriteError,
    WriterLockError,
    open_station_catalog,
    write_records,
)
from breezy.strategy.current_rung_hold.monitor_records import (
    PositionMarkRecord,
    PositionMonitorSummary,
)

__all__ = [
    "DEFAULT_MARK_BUFFER_MAXLEN",
    "MARK_BUFFER_FLUSH_THRESHOLD",
    "MONITOR_SUMMARY_SCHEMA",
    "MarkBuffer",
    "open_monitor_catalog",
    "read_monitor_summaries",
    "write_monitor_summaries",
]

logger = logging.getLogger(__name__)

DEFAULT_MARK_BUFFER_MAXLEN: Final[int] = 2048
MARK_BUFFER_FLUSH_THRESHOLD: Final[int] = 256

#: Never the quote-tape venue -- see the module docstring.
_MONITOR_CATALOG_VENUE: Final[str] = "monitor"

_SUMMARY_FILE_PREFIX: Final[str] = "position_monitor_summaries_"
_SUMMARY_FILE_SUFFIX: Final[str] = ".parquet"

#: Pinned column-for-column, mirroring `scored_trial_store.SCORED_TRIAL_SCHEMA`'s
#: placement and Decimal-as-string convention.
MONITOR_SUMMARY_SCHEMA: pa.Schema = pa.schema(
    [
        pa.field("trial_id", pa.string(), nullable=False),
        pa.field("instrument_id", pa.string(), nullable=False),
        pa.field("station", pa.string(), nullable=False),
        pa.field("climate_day", pa.string(), nullable=False),
        pa.field("leg", pa.string(), nullable=False),
        pa.field("entry_context", pa.string(), nullable=False),
        pa.field("monitor_seq", pa.int32(), nullable=False),
        pa.field("fill_px", pa.string(), nullable=False),
        pa.field("held_qty", pa.string(), nullable=False),
        pa.field("mae", pa.string(), nullable=False),
        pa.field("mfe", pa.string(), nullable=False),
        pa.field("first_signal_ts_ns", pa.int64(), nullable=True),
        pa.field("first_signal_hour_lst", pa.int32(), nullable=True),
        pa.field("first_signal_state", pa.string(), nullable=True),
        pa.field("verdict_at_signal", pa.string(), nullable=True),
        pa.field("recoverable_value_at_signal", pa.string(), nullable=True),
        pa.field("held_duration_ns", pa.int64(), nullable=False),
        pa.field("total_frames", pa.int32(), nullable=False),
        pa.field("mark_missing_frames", pa.int32(), nullable=False),
        pa.field("monitor_intervened", pa.bool_(), nullable=False),
        pa.field("settled_pnl", pa.string(), nullable=True),
        pa.field("settled_held", pa.bool_(), nullable=True),
    ]
)


def open_monitor_catalog(root: Path, climate_day: str) -> ParquetDataCatalog:
    """Open the per-climate-day monitor catalog root (A2).

    Thin wrapper over `open_station_catalog`, reusing its full path-safety
    surface (symlink guards, escape checks) rather than reimplementing any
    of it. `venue="monitor"` keeps this root disjoint from the quote-tape
    catalog; `city=climate_day` gives one directory per day so a
    `write_records` read-back verify is bounded to that day's rows.
    """
    return open_station_catalog(root, _MONITOR_CATALOG_VENUE, climate_day)


class MarkBuffer:
    """Bounded in-memory buffer of pending `PositionMarkRecord` rows.

    Same shape as `OfferTape` (`offer_tape.py:78-124`): a `deque(maxlen=...)`
    absorbs unbounded runtime without growing memory, and an optional JSONL
    sidecar is best-effort -- a disk error is caught and counted, never
    propagated into the strategy's hot path.
    """

    def __init__(
        self,
        *,
        sidecar_path: Path | None = None,
        maxlen: int = DEFAULT_MARK_BUFFER_MAXLEN,
    ) -> None:
        if maxlen < 1:
            raise ValueError("MarkBuffer maxlen must be >= 1")
        self._buf: deque[PositionMarkRecord] = deque(maxlen=maxlen)
        self._maxlen = maxlen
        self._sidecar_path = sidecar_path
        self._dropped = 0
        self._sidecar_errors = 0
        self._flush_errors = 0
        if sidecar_path is not None:
            sidecar_path.parent.mkdir(parents=True, exist_ok=True)

    def __len__(self) -> int:
        return len(self._buf)

    @property
    def dropped(self) -> int:
        """Records evicted by the bounded deque before ever being flushed."""
        return self._dropped

    @property
    def sidecar_errors(self) -> int:
        return self._sidecar_errors

    @property
    def flush_errors(self) -> int:
        return self._flush_errors

    def records(self) -> tuple[PositionMarkRecord, ...]:
        return tuple(self._buf)

    def should_flush(self) -> bool:
        return len(self._buf) >= MARK_BUFFER_FLUSH_THRESHOLD

    def append(self, record: PositionMarkRecord) -> None:
        """Buffer `record`, counting a drop if the deque is already full.

        The in-memory append always happens first and unconditionally,
        mirroring `OfferTape.append`: a disk error on the optional JSONL
        sidecar must never propagate out of a live strategy's `on_data`/
        `on_order_book_depth` handler.
        """
        if len(self._buf) >= self._maxlen:
            self._dropped += 1
        self._buf.append(record)

        if self._sidecar_path is None:
            return
        line = json.dumps(record.to_dict(), sort_keys=True)
        try:
            with self._sidecar_path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.write("\n")
        except OSError:
            self._sidecar_errors += 1
            logger.exception("MarkBuffer: failed to append to %s", self._sidecar_path)

    def flush(self, catalog_root: Path, climate_day: str) -> int:
        """Write every pending record in ONE batched `write_records` call.

        Records stay buffered (bounded by the deque, never unboundedly) on
        any writer failure, so a transient catalog fault never loses data
        beyond what the deque itself would already have dropped.
        """
        if not self._buf:
            return 0

        pending = list(self._buf)
        try:
            catalog = open_monitor_catalog(catalog_root, climate_day)
            outcome = write_records(catalog, pending)
        except (WriterLockError, CatalogWriteError, ValueError):
            self._flush_errors += 1
            logger.exception(
                "MarkBuffer: flush failed for climate_day=%s; %d record(s) remain buffered",
                climate_day,
                len(pending),
            )
            return 0

        self._buf.clear()
        return len(outcome.written)


def write_monitor_summaries(
    directory: Path,
    summaries: Sequence[PositionMonitorSummary],
    *,
    now_ns: int,
) -> Path:
    """Write one run's `summaries` as a new parquet file under `directory`.

    Byte-for-byte the same shape as `write_scored_trials`
    (`scored_trial_store.py:79-101`): never rewrites an existing file, atomic
    tempfile + `os.replace`, filename stamped from the caller's own clock
    reading (`now_ns`, never read from the wall clock here).
    """
    directory.mkdir(parents=True, exist_ok=True)
    rows = [summary.to_dict() for summary in summaries]
    table = pa.Table.from_pylist(rows, schema=MONITOR_SUMMARY_SCHEMA)
    target = directory / f"{_SUMMARY_FILE_PREFIX}{_stamp(now_ns)}{_SUMMARY_FILE_SUFFIX}"

    fd, tmp_name = tempfile.mkstemp(
        dir=directory, prefix=f".{_SUMMARY_FILE_PREFIX}", suffix=".tmp"
    )
    tmp_path = Path(tmp_name)
    try:
        os.close(fd)
        pq.write_table(table, tmp_path)
        os.replace(tmp_path, target)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    return target


def read_monitor_summaries(directory: Path) -> tuple[PositionMonitorSummary, ...]:
    """Read every summary run under `directory`, deduped by `(trial_id, max monitor_seq)`.

    An empty or absent directory returns no rows, never an error -- a fresh
    deployment with no summary runs yet is a normal state, not a defect.
    """
    if not directory.exists():
        return ()
    latest: dict[str, PositionMonitorSummary] = {}
    for path in sorted(directory.glob(f"{_SUMMARY_FILE_PREFIX}*{_SUMMARY_FILE_SUFFIX}")):
        table = pq.read_table(path, schema=MONITOR_SUMMARY_SCHEMA)
        for row in table.to_pylist():
            summary = PositionMonitorSummary.from_dict(row)
            current = latest.get(summary.trial_id)
            if current is None or summary.monitor_seq > current.monitor_seq:
                latest[summary.trial_id] = summary
    return tuple(latest.values())


def _stamp(now_ns: int) -> str:
    seconds, nanos = divmod(now_ns, 1_000_000_000)
    stamp = dt.datetime.fromtimestamp(seconds, tz=dt.UTC).strftime("%Y%m%dT%H%M%S")
    return f"{stamp}{nanos:09d}Z"
