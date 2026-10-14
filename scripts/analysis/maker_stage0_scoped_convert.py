"""MAKER-S2 S-5 reader fix: scope a recorder-instance conversion to the rungs a pass will read.

A live instance is ~15 GB and holds every rung the recorder ever listed; converting all of it for
one station-day OOMs at 4 GiB. The per-rung streams are stored as one feather subdirectory per
instrument, so ``default_convert(..., identifiers=...)`` converts only the named ones. Instrument
definitions and the venue-clock series are flat and always converted whole.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Collection, Sequence
from pathlib import Path
from typing import Any, Final

from nautilus_trader.model.data import OrderBookDepth10, TradeTick
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from nautilus_trader.persistence.funcs import class_to_filename

from breezy.adapters.polymarket_us.tape_records import DepthTruncation, QuoteTapeGap
from breezy.persistence.feather_preflight import (
    DEFAULT_SUBDIRECTORY,
    PreflightReport,
    iter_feather_files,
    scan_instance,
)
from scripts.analysis.maker_stage0_probe_core import station_day_key

__all__ = [
    "PER_RUNG_STREAMS",
    "convert_scoped",
    "licensed_rung_filter",
    "licensed_rungs",
    "scan_instance_memoized",
    "scope_kwargs",
]

#: stream types the recorder partitions into one feather subdirectory per instrument
PER_RUNG_STREAMS: Final[tuple[type, ...]] = (
    QuoteTapeGap,
    TradeTick,
    OrderBookDepth10,
    DepthTruncation,
)


def scope_kwargs(data_cls: type, rungs: Sequence[str] | None) -> dict[str, Any]:
    """``default_convert`` keywords scoping ``data_cls`` to ``rungs`` (none: whole instance)."""
    if rungs is None or data_cls not in PER_RUNG_STREAMS:
        return {}
    return {"identifiers": sorted(rungs)}


def licensed_rungs(
    instance_dir: Path, data_cls: type, keep: Callable[[str], bool]
) -> list[str] | None:
    """Subdirectory (= instrument id) names of ``data_cls`` under ``instance_dir`` passing ``keep``.

    ``None`` for a flat (non-partitioned) type: nothing to scope.
    """
    if data_cls not in PER_RUNG_STREAMS:
        return None
    stream_dir = instance_dir / class_to_filename(data_cls)
    if not stream_dir.is_dir():
        return []
    return sorted(p.name for p in stream_dir.iterdir() if p.is_dir() and keep(p.name))


def licensed_rung_filter(
    days: Collection[dt.date], stations: Collection[str]
) -> Callable[[str], bool]:
    """Instrument-id predicate: the rung is a YES leg of a declared ``stations`` x ``days`` day."""

    def keep(rung: str) -> bool:
        return station_day_key(InstrumentId.from_str(rung), days, stations) is not None

    return keep


def convert_scoped(
    convert: Callable[..., Any],
    source: ParquetDataCatalog,
    work: ParquetDataCatalog,
    instance_dir: Path,
    streams: Sequence[type],
    keep_rung: Callable[[str], bool] | None,
) -> None:
    """``convert`` (``default_convert``) ``streams`` of one instance into ``work``.

    Per-rung types only for ``keep_rung``. ``convert`` is injected so this module stays free of
    ``breezy.runtime`` (each importer of that package is a registered entry point).
    """
    for data_cls in streams:
        rungs = None if keep_rung is None else licensed_rungs(instance_dir, data_cls, keep_rung)
        convert(
            source,
            instance_dir.name,
            data_cls,
            DEFAULT_SUBDIRECTORY,
            target=work,
            **scope_kwargs(data_cls, rungs),
        )


_SCANS: dict[tuple[str, str, str], tuple[tuple[tuple[str, int, int], ...], PreflightReport]] = {}


def _signature(directory: Path) -> tuple[tuple[str, int, int], ...]:
    """(path, size, mtime_ns) of every feather file: any append or rewrite changes it."""
    return tuple(
        (str(p), (st := p.stat()).st_size, st.st_mtime_ns) for p in iter_feather_files(directory)
    )


def scan_instance_memoized(
    catalog_root: Path, instance_id: str, subdirectory: str = DEFAULT_SUBDIRECTORY
) -> PreflightReport:
    """``scan_instance``, remembered for the life of the process while the files are unchanged.

    The first-print, plan and probe passes each classify every instance, and the stream scan reads
    every byte (~70 s for a 15 GB instance). The memo lives in process memory only -- nothing is
    written under the capture -- and is keyed by every file's size and mtime, so a file a live
    writer has since touched is rescanned. ``classify_instance`` still runs per call with the
    caller's own ``now_ns``.
    """
    key = (str(catalog_root), subdirectory, instance_id)
    signature = _signature(catalog_root / subdirectory / instance_id)
    cached = _SCANS.get(key)
    if cached is not None and cached[0] == signature:
        return cached[1]
    report = scan_instance(catalog_root, instance_id, subdirectory)
    _SCANS[key] = (signature, report)
    return report
