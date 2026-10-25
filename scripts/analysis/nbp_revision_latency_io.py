"""Real-data loader for the LAT-1 scorer. Never imported by the tests; never run on real data
until the prereg is frozen (every stage refuses while ``PREREG_SHA256`` is UNFROZEN).

One station-day is loaded at a time. The book clock is the tape's ``ts_init`` (receipt time): the
Depth10 parquet is read directly with pyarrow, scoped to one instrument directory, because
``release_timing_b0.read_top_of_book`` exposes only ``ts_event``. Rows received at or after the
cutoff C are never loaded.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from pathlib import Path
from typing import Final

import numpy as np
import pyarrow.parquet as pq
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

from breezy.adapters.polymarket_us.symbology import parse_weather_slug, slug_closed_interval
from breezy.analysis.revision_latency import (
    ARTEFACT_SHA256,
    before_cutoff,
    chain_for,
    pinned_cycles,
)
from breezy.runtime.quote_tape_gaps import load_partitioned_quote_tape_gaps
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import load_live_calibration
from breezy.strategy.ladder_ev.quantile_density import Rung
from breezy.strategy.no_ladder_maker.pno_store import build_state, site
from breezy.strategy.weather_common.revision_gate import BookRow, BookSeries, GapSpan
from scripts.analysis.nbp_revision_latency_core import Loader, StationDayData
from scripts.analysis.p2_nbp_ask_murphy import _NbpSource
from scripts.analysis.release_timing_b0 import DEPTH_DIR, parse_instrument

DEFAULT_DERIVED: Final[Path] = Path.home() / ".local/share/breezy/derived/nbp"
DEFAULT_TAPE: Final[Path] = Path("/mnt/storage/breezy/catalog/quote_tape/polymarket_us")
_VENUE_SUFFIX: Final[str] = ".POLYMARKET_US"

_FIXED_SCALE: Final[float] = 1e16
_BATCH_ROWS: Final[int] = 65_536
_COLUMNS: Final[list[str]] = [
    "ts_init",
    "bid_price_0",
    "bid_size_0",
    "ask_price_0",
    "ask_size_0",
]


def _price_or_nan(price_col: object, size_col: object) -> np.ndarray:
    """A fixed_size_binary(16) price column as floats; NaN where the size is zero (empty side)."""

    def _words(array: object) -> np.ndarray:
        start = array.offset * 2  # type: ignore[attr-defined]
        flat = np.frombuffer(array.buffers()[1], dtype="<u8")  # type: ignore[attr-defined]
        return flat[start : start + len(array) * 2].reshape(-1, 2)  # type: ignore[arg-type]

    prices, sizes = _words(price_col), _words(size_col)
    present = (sizes[:, 0] != 0) | (sizes[:, 1] != 0)
    return np.where(present, prices[:, 0].astype(np.float64) / _FIXED_SCALE, np.nan)


class BookSchemaError(ValueError):
    """A Depth10 parquet file lacks a column the loader needs."""


def _require_columns(handle: pq.ParquetFile, path: Path, needed: list[str]) -> None:
    absent = [name for name in needed if name not in handle.schema_arrow.names]
    if absent:
        raise BookSchemaError(f"{path}: missing Depth10 column(s) {absent}")


def read_first_ts_init(instrument_dir: Path) -> int | None:
    """The earliest ``ts_init`` before the cutoff (the rung's listing instant); no prices read."""
    first: int | None = None
    for path in sorted(instrument_dir.glob("*.parquet")):
        with pq.ParquetFile(path) as handle:
            _require_columns(handle, path, ["ts_init"])
            for batch in handle.iter_batches(batch_size=_BATCH_ROWS, columns=["ts_init"]):
                for t in batch.column("ts_init").to_numpy(zero_copy_only=False):
                    if before_cutoff(int(t)) and (first is None or int(t) < first):
                        first = int(t)
    return first


def read_l0_book(instrument_dir: Path) -> list[BookRow]:
    """Level-0 rows of ONE instrument directory on the ``ts_init`` clock, ascending.

    Rows received at or after the cutoff C are dropped. An empty side is NaN."""
    rows: list[BookRow] = []
    for path in sorted(instrument_dir.glob("*.parquet")):
        with pq.ParquetFile(path) as handle:
            _require_columns(handle, path, _COLUMNS)
            for batch in handle.iter_batches(batch_size=_BATCH_ROWS, columns=_COLUMNS):
                ts = batch.column("ts_init").to_numpy(zero_copy_only=False)
                bid = _price_or_nan(batch.column("bid_price_0"), batch.column("bid_size_0"))
                ask = _price_or_nan(batch.column("ask_price_0"), batch.column("ask_size_0"))
                rows.extend(
                    BookRow(int(t), float(b), float(a))
                    for t, b, a in zip(ts, bid, ask, strict=True)
                    if before_cutoff(int(t))
                )
    rows.sort(key=lambda row: row.ts_init)
    return rows


def _rung_of(name: str) -> Rung | None:
    key = parse_instrument(name)
    weather = parse_weather_slug(name.removesuffix(_VENUE_SUFFIX))
    if key is None or weather is None:
        return None
    interval = slug_closed_interval(weather.bounds)
    return None if interval is None else Rung(key.rung_id, interval[0], interval[1])


def _gap_spans(tape: Path) -> dict[str, tuple[GapSpan, ...]]:
    catalog = ParquetDataCatalog(str(tape))
    spans: dict[str, list[GapSpan]] = defaultdict(list)
    for key, gaps in load_partitioned_quote_tape_gaps(catalog).items():
        spans[key.instrument_id.value].extend(
            GapSpan(g.started_ns, g.ended_ns, g.resolved) for g in gaps
        )
    return {name: tuple(rows) for name, rows in spans.items()}


def make_loader(
    artefact: Path,
    derived_root: Path | None,
    tape_root: Path | None,
    *,
    with_books: bool,
) -> Loader:
    calibration = load_live_calibration(str(artefact), expected_sha256=ARTEFACT_SHA256)
    source = _NbpSource(derived_root or DEFAULT_DERIVED)
    tape = tape_root or DEFAULT_TAPE
    depth_dir = tape / "data" / DEPTH_DIR
    members: dict[tuple[str, dt.date], list[str]] = defaultdict(list)
    for entry in sorted(depth_dir.iterdir()):  # names only: structure, never prices
        key = parse_instrument(entry.name) if entry.is_dir() else None
        if key is not None:
            members[(key.station, key.climate_day)].append(entry.name)
    gaps = _gap_spans(tape) if with_books else {}

    def load(station: str, day: dt.date) -> StationDayData | None:
        placed = site(station)
        names = members.get((placed.icao, day), [])
        rungs = {r.rung_id: (name, r) for name in names if (r := _rung_of(name)) is not None}
        if not rungs:
            return None
        pinned = pinned_cycles(source, placed.icao, day)
        chain = chain_for(build_state(pinned.rows, placed.offset_hours, "none"), day)
        source.clear()
        books: dict[str, BookSeries] = {}
        heartbeat: set[int] = set()
        listed_at: dict[str, int] = {}
        if with_books:
            for rung_id, (name, _rung) in rungs.items():
                rows = read_l0_book(depth_dir / name)
                books[rung_id] = BookSeries(rows)
                heartbeat.update(row.ts_init for row in rows)
                if rows:
                    listed_at[rung_id] = rows[0].ts_init
        else:  # stage tau: the listing instant only (one column), so tau and scoring share a ladder
            for rung_id, (name, _rung) in rungs.items():
                first = read_first_ts_init(depth_dir / name)
                if first is not None:
                    listed_at[rung_id] = first
        return StationDayData(
            station=station,
            climate_day=day,
            chain=chain,
            ladder=tuple(sorted((r for _n, r in rungs.values()), key=lambda r: r.rung_id)),
            calibration=calibration,
            latitude_deg=placed.latitude_deg,
            offset_hours=placed.offset_hours,
            books=books,
            gaps={rid: gaps.get(name, ()) for rid, (name, _r) in rungs.items()},
            heartbeat=tuple(sorted(heartbeat)),
            listed_at=listed_at,
        )

    return load
