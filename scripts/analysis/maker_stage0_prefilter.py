"""C7 instance pre-filter: stat gate plus a fail-closed licensed-listing check."""

from __future__ import annotations

import datetime as dt
from collections.abc import Collection, Sequence
from pathlib import Path

import pyarrow as pa
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.persistence.funcs import class_to_filename

from scripts.analysis import maker_stage0_scoped_convert as sc
from scripts.analysis.maker_stage0_probe_core import station_day_key

_ONE_DAY_NS: int = 86_400 * 1_000_000_000
_DEF_DIR = class_to_filename(BinaryOption)


def prefilter_cutoff_ns(
    days: Collection[dt.date],
    stations: Collection[str],
    *,
    earliest_licensed_ns: int | None = None,
) -> int | None:
    """One day before the block (or the listing, if earlier); None when the block is empty."""
    if not days or not stations:
        return None
    from scripts.analysis.maker_stage0_probe import _query_bounds

    base = _query_bounds(days, stations)[0] - _ONE_DAY_NS
    if earliest_licensed_ns is not None:
        return min(base, earliest_licensed_ns)
    return base


def _read_definition_instrument_ids(path: Path) -> tuple[InstrumentId, ...]:
    with pa.OSFile(str(path), "rb") as source:
        table = pa.ipc.open_stream(source).read_all()
    return tuple(
        InstrumentId.from_str(str(raw)) for raw in table.column("id").to_pylist() if raw is not None
    )


def _prefilter_reason(
    instance_dir: Path,
    cutoff_ns: int,
    days: Collection[dt.date] = (),
    stations: Collection[str] = (),
) -> str | None:
    """Skip when the newest feather is strictly older. Empty or ``OSError`` fails open.

    When the stat gate would skip, only BinaryOption definition feathers are read (paths
    from ``sc._signature`` whose first relative part is the class directory or a
    flat ``binary_option_*.feather``). Any row whose
    ``station_day_key(instrument_id, days, stations)`` is not None keeps the instance.
    OSError, pyarrow errors, or schema surprises while reading definitions keep it.

    The gate trusts file mtimes; a backdated restore (touch -d / tar with old mtimes)
    can make data look older than it is; the definitions check guarantees no licensed
    listing is ever lost regardless.
    """
    try:
        rows = sc._signature(instance_dir)
        newest = max((row[2] for row in rows), default=None)
    except OSError:
        return None
    if newest is None or newest >= cutoff_ns:
        return None
    if not days or not stations:
        return None
    try:
        if _holds_licensed_listing(instance_dir, rows, days, stations):
            return None
    except Exception:  # noqa: BLE001 - fail-open on any definitions-read surprise
        return None
    return f"prefilter: last_written_ns {newest} < cutoff_ns {cutoff_ns}"


def _holds_licensed_listing(
    instance_dir: Path,
    rows: Sequence[tuple[str, int, int]],
    days: Collection[dt.date],
    stations: Collection[str],
) -> bool:
    for path_s, _size, _mtime in rows:
        path = Path(path_s)
        rel = path.relative_to(instance_dir)
        first, last = rel.parts[0], rel.parts[-1]
        if first != _DEF_DIR and not last.startswith(_DEF_DIR + "_"):
            continue
        for instrument_id in _read_definition_instrument_ids(path):
            if station_day_key(instrument_id, days, stations) is not None:
                return True
    return False
