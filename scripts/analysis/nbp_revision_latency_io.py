"""Real-data loader for the LAT-1 scorer. Never imported by the tests; never run on real data
until the prereg is frozen (every stage refuses while ``PREREG_SHA256`` is UNFROZEN).

One station-day is loaded at a time. Tape time is the tape's ``ts_event`` column (the only clock
``read_top_of_book`` exposes), used as the book clock; ``ts_init`` is not read (plan deviation).
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Final

from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

from breezy.adapters.polymarket_us.symbology import parse_weather_slug, slug_closed_interval
from breezy.analysis.revision_latency import ARTEFACT_SHA256, chain_for
from breezy.runtime.quote_tape_gaps import load_partitioned_quote_tape_gaps
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import load_live_calibration
from breezy.strategy.ladder_ev.quantile_density import Rung
from breezy.strategy.no_ladder_maker.pno_store import build_state, read_pinned, site
from breezy.strategy.weather_common.revision_gate import BookRow, BookSeries, GapSpan
from scripts.analysis.nbp_revision_latency_core import StationDayData
from scripts.analysis.p2_nbp_ask_murphy import _NbpSource
from scripts.analysis.release_timing_b0 import DEPTH_DIR, parse_instrument, read_top_of_book

DEFAULT_DERIVED: Final[Path] = Path.home() / ".local/share/breezy/derived/nbp"
DEFAULT_TAPE: Final[Path] = Path("/mnt/storage/breezy/catalog/quote_tape/polymarket_us")
_VENUE_SUFFIX: Final[str] = ".POLYMARKET_US"

Loader = Callable[[str, dt.date], StationDayData | None]


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
        pinned = read_pinned(source, placed.icao, day)
        chain = chain_for(build_state(pinned.rows, placed.offset_hours, "none"), day)
        source.clear()
        books: dict[str, BookSeries] = {}
        heartbeat: set[int] = set()
        if with_books:
            for rung_id, (name, _rung) in rungs.items():
                top = read_top_of_book(depth_dir / name)
                rows = [
                    BookRow(int(t), float(b), float(a))
                    for t, b, a in zip(top.ts, top.bid, top.ask, strict=True)
                ]
                books[rung_id] = BookSeries(rows)
                heartbeat.update(row.ts_init for row in rows)
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
        )

    return load
