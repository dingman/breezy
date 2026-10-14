"""MAKER-S2 WP6: the capture reader (Nautilus-native; read-only on the capture).

Plan r3 WP6 + r4 delta (g) (catalog slice manifest) and (i)9 (bench by catalog bytes). Each CLEAN
recorder instance is converted by ``default_convert`` into a scratch ``ParquetDataCatalog`` under
``work_root`` (never under the capture), queried with ``ParquetDataCatalog.query`` scoped by
instrument and absolute ns, and deleted. ``plan`` converts only the instrument definitions to find
which instances hold each station-day; ``read`` keeps at most ``keep`` converted instances alive
(day-major iteration touches each instance on consecutive station-days) so no instance is
converted more than once in a normal run. ``_catalog`` converts only the planned rungs' partitions
(S-5 reader fix), so no byte outside the station-day's ladder reaches scratch. The CAPTURE's
source files (by path relative to the capture root, size and sha256; never the scratch
conversion, which differs in path and mtime on every run and every LRU re-conversion) behind each
query are hashed into the caller's
``CatalogSliceManifest``. The reader returns plain records (``maker_stage0_events_build``);
it never imports the simulator, the truth loader or the report.
"""

from __future__ import annotations

import datetime as dt
import shutil
from collections import OrderedDict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from nautilus_trader.model.data import OrderBookDepth10, TradeTick
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

from breezy.adapters.polymarket_us.tape_records import DepthTruncation, QuoteTapeGap
from breezy.analysis.maker_tape_census import (
    bidlive_window_ns,
    maker_window_ns,
)
from breezy.persistence.feather_preflight import DEFAULT_SUBDIRECTORY
from breezy.runtime.quote_tape_gaps import load_partitioned_quote_tape_gaps
from breezy.runtime.quote_tape_ingest_core import default_convert
from scripts.analysis.maker_stage0_events_build import (
    InstanceSlice,
    RawFrame,
    RawGap,
    RawPrint,
    RawTruncation,
)
from scripts.analysis.maker_stage0_pno_store import site
from scripts.analysis.maker_stage0_probe import _for_each_clean_instance
from scripts.analysis.maker_stage0_probe_core import StationDay, station_day_key
from scripts.analysis.maker_stage0_scoped_convert import scope_kwargs

if TYPE_CHECKING:  # annotation only: the pins module imports the frozen-set module
    from scripts.analysis.maker_stage0_pins import CatalogSliceManifest

__all__ = ["CatalogSession", "StationDayPlan", "query_window_ns"]

#: Streams converted for a replay (instrument defs, gaps, prints, Depth10, truncation rows).
REPLAY_STREAMS: Final[tuple[type, ...]] = (
    BinaryOption,
    QuoteTapeGap,
    TradeTick,
    OrderBookDepth10,
    DepthTruncation,
)
_BYTE_STREAMS: Final[tuple[str, ...]] = ("order_book_depths", "trade_tick")
#: capture stream directories (one subdirectory per instrument) a read consumes
_HASHED_STREAMS: Final[tuple[str, ...]] = (
    *_BYTE_STREAMS,
    "custom_quote_tape_gap",
    "custom_depth_truncation",
)
_NS: Final[int] = 10**9


@dataclass(frozen=True, slots=True)
class StationDayPlan:
    instruments: tuple[str, ...]  # YES-leg instrument ids, sorted
    instances: tuple[str, ...]  # CLEAN recorder instances that define any of them, sorted
    catalog_bytes: int  # depth + print bytes in the capture (outcome-blind bench weight)


def query_window_ns(station: str, day: dt.date) -> tuple[int, int]:
    """[D-1 12:00Z, bid-live end): the opening book through the end of the process window."""
    offset = site(station).offset_hours
    window = maker_window_ns(climate_day=day, std_utc_offset_hours=offset)
    return window.start_ns, bidlive_window_ns(climate_day=day, window=window)[1]


def _unwrap(item: Any) -> Any:
    return getattr(item, "data", item)


@dataclass
class CatalogSession:
    capture_root: Path
    work_root: Path
    manifest: CatalogSliceManifest | None = None
    keep: int = 3
    skipped: dict[str, str] = field(default_factory=dict)
    _open: OrderedDict[str, tuple[ParquetDataCatalog, Path, frozenset[str]]] = field(
        default_factory=OrderedDict
    )

    # --- planning ---------------------------------------------------------------------------
    def plan(
        self, days: Collection[dt.date], stations: Collection[str]
    ) -> dict[StationDay, StationDayPlan]:
        found: dict[StationDay, dict[str, set[str]]] = {}

        def visit(work: ParquetDataCatalog, instance: str) -> None:
            for instrument in work.query(data_cls=BinaryOption):
                key = station_day_key(instrument.id, days, stations)
                if key is not None:
                    found.setdefault(key, {}).setdefault(str(instrument.id), set()).add(instance)

        _for_each_clean_instance(
            self.capture_root, self.work_root / "plan", (BinaryOption,), visit, self.skipped
        )
        return {key: self._station_day_plan(by_rung) for key, by_rung in sorted(found.items())}

    def _station_day_plan(self, by_rung: Mapping[str, set[str]]) -> StationDayPlan:
        instances = sorted({i for held in by_rung.values() for i in held})
        weight = sum(self._bytes(inst, rung) for rung, held in by_rung.items() for inst in held)
        return StationDayPlan(tuple(sorted(by_rung)), tuple(instances), weight)

    def _bytes(self, instance: str, rung: str) -> int:
        base = self.capture_root / DEFAULT_SUBDIRECTORY / instance
        return sum(
            f.stat().st_size
            for stream in _BYTE_STREAMS
            for f in (base / stream / rung).glob("*")
            if f.is_file()
        )

    # --- reading ----------------------------------------------------------------------------
    def read(self, plan: StationDayPlan, window: tuple[int, int]) -> list[InstanceSlice]:
        return [self._read_instance(i, plan.instruments, window) for i in plan.instances]

    def _catalog(self, instance: str, rungs: frozenset[str]) -> ParquetDataCatalog:
        """The scratch conversion of ``instance`` holding at least ``rungs`` (reused when it does).

        Only the planned rungs' depth/print/gap/truncation partitions are converted (S-5 reader
        fix: a whole live instance is ~15 GB and OOMs at 4 GiB); instrument definitions are few
        and converted whole. A cached conversion of a narrower rung set is rebuilt.
        """
        if instance in self._open:
            work, _dir, held = self._open[instance]
            if rungs <= held:
                self._open.move_to_end(instance)
                return work
            self._evict(instance)
        source = ParquetDataCatalog(str(self.capture_root))
        work_dir = self.work_root / "replay" / instance
        work_dir.mkdir(parents=True, exist_ok=False)
        work = ParquetDataCatalog(str(work_dir))
        for data_cls in REPLAY_STREAMS:
            default_convert(
                source,
                instance,
                data_cls,
                DEFAULT_SUBDIRECTORY,
                target=work,
                **scope_kwargs(data_cls, sorted(rungs)),
            )
        self._open[instance] = (work, work_dir, rungs)
        while len(self._open) > self.keep:
            self._evict(next(iter(self._open)))
        return work

    def _evict(self, instance: str) -> None:
        _work, work_dir, _rungs = self._open.pop(instance)
        shutil.rmtree(work_dir, ignore_errors=True)

    def close(self) -> None:
        for instance in list(self._open):
            self._evict(instance)

    def _read_instance(
        self, instance: str, rungs: Sequence[str], window: tuple[int, int]
    ) -> InstanceSlice:
        wanted = frozenset(rungs)
        work = self._catalog(instance, wanted)
        frames: list[RawFrame] = []
        prints: list[RawPrint] = []
        for rung in rungs:
            frames += [
                _frame(d)
                for d in work.query(
                    data_cls=OrderBookDepth10, identifiers=[rung], start=window[0], end=window[1]
                )
            ]
            prints += [
                _print(t)
                for t in work.query(
                    data_cls=TradeTick, identifiers=[rung], start=window[0], end=window[1]
                )
            ]
        truncations = [
            _truncation(t)
            for t in map(
                _unwrap, work.query(data_cls=DepthTruncation, start=window[0], end=window[1])
            )
            if str(t.instrument_id) in wanted
        ]
        gaps = [
            RawGap(str(key.instrument_id), g.started_ns, g.ended_ns if g.resolved else None)
            for key, records in load_partitioned_quote_tape_gaps(work).items()
            if str(key.instrument_id) in wanted
            for g in records
        ]
        self._hash_consumed(instance, wanted)
        return InstanceSlice(instance, frames, prints, gaps, truncations)

    def _hash_consumed(self, instance: str, rungs: frozenset[str]) -> None:
        if self.manifest is None:
            return
        base = self.capture_root / DEFAULT_SUBDIRECTORY / instance
        for stream in _HASHED_STREAMS:
            for rung in sorted(rungs):
                for path in sorted((base / stream / rung).glob("*")):
                    if path.is_file():
                        self.manifest.add_capture_file(self.capture_root, path)


@lru_cache(maxsize=1 << 16)
def _level(price: str, size: str) -> tuple[Decimal, Decimal]:
    """One shared (price, size) pair: a book repeats few distinct levels, many times over."""
    return Decimal(price), Decimal(size)


def _levels(orders: Sequence[Any]) -> tuple[tuple[Decimal, Decimal], ...]:
    return tuple(_level(str(o.price), str(o.size)) for o in orders)


def _frame(depth: OrderBookDepth10) -> RawFrame:
    return RawFrame(
        str(depth.instrument_id), depth.ts_event, _levels(depth.bids), _levels(depth.asks)
    )


def _print(tick: TradeTick) -> RawPrint:
    return RawPrint(
        tick.trade_id.value,
        str(tick.instrument_id),
        tick.ts_event,
        Decimal(str(tick.price)),
        Decimal(str(tick.size)),
        tick.aggressor_side.name,
    )


def _truncation(row: Any) -> RawTruncation:
    return RawTruncation(
        str(row.instrument_id), row.ts_event, row.bid_levels_seen, row.ask_levels_seen
    )
