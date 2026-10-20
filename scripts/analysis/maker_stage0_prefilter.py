"""C7 instance pre-filter: verdict-blind (file stat plus definition, rung-directory and file names).

Reads no price, size or outcome. The cutoff helper ``prefilter_cutoff_ns`` lives in
``maker_stage0_probe`` beside ``_query_bounds``; this module takes everything it needs as arguments
and imports nothing from the probe.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path

import pyarrow as pa
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.persistence.funcs import class_to_filename

from scripts.analysis import maker_stage0_scoped_convert as sc
from scripts.analysis.maker_stage0_probe_core import station_day_key

_DEF_DIR = class_to_filename(BinaryOption)
_PER_RUNG_DIRS = frozenset(class_to_filename(stream) for stream in sc.PER_RUNG_STREAMS)
_FLAT_PER_RUNG_PREFIXES = tuple(f"{name}_" for name in sorted(_PER_RUNG_DIRS))
_SKIP_PREFIX = "prefilter:"
_LOG = logging.getLogger(__name__)


def _read_definition_instrument_ids(path: Path) -> tuple[InstrumentId, ...]:
    with pa.OSFile(str(path), "rb") as source:
        table = pa.ipc.open_stream(source).read_all()
    return tuple(
        InstrumentId.from_str(str(raw)) for raw in table.column("id").to_pylist() if raw is not None
    )


def _fail_open(instance_dir: Path, fail_open: list[str] | None) -> None:
    """Record a read error from inside an ``except`` block: warn with the traceback, count it."""
    _LOG.warning("prefilter: %s kept after a read error", instance_dir.name, exc_info=True)
    if fail_open is not None:
        fail_open.append(instance_dir.name)


def _prefilter_reason(
    instance_dir: Path,
    cutoff_ns: int,
    *,
    days: Collection[dt.date],
    stations: Collection[str],
    fail_open: list[str] | None = None,
    kept_by_content: list[str] | None = None,
) -> str | None:
    """Why ``instance_dir`` can be skipped before classify, or None to keep it.

    Verdict-blind: the file stat, the definitions file names and the per-rung directory and file
    names. The instance is KEPT when any of these holds:

    1. its newest feather mtime is at or after ``cutoff_ns`` (a tie keeps);
    2. a per-rung stream directory under it names a licensed rung (a directory listing, via
       ``sc.licensed_rungs``);
    3. a readable ``BinaryOption`` definition feather holds a licensed YES-leg row
       (``station_day_key``);
    4. a FLAT per-rung stream file (``<table>_<ts>.feather`` at the instance level, not under a
       per-rung directory) exists. The writer names it with no instrument id, so any such file
       keeps the instance on its name alone, licensed or not.

    Any read error also keeps it (fail open: WARNING with traceback, appended to ``fail_open``), as
    do an instance with no feathers and an empty ``days`` or ``stations``. The gate trusts file
    mtimes (a backdated restore looks older than it is); conditions 2 to 4 rescue an old instance by
    content, and each such rescue is appended to ``kept_by_content`` (zero on the real catalog under
    premise P, so a non-zero count is the empirical premise-P violation signal).
    """
    try:
        rows = sc._signature(instance_dir)
    except OSError:
        _fail_open(instance_dir, fail_open)
        return None
    newest = max((row[2] for row in rows), default=None)
    if newest is None or newest >= cutoff_ns or not days or not stations:
        return None
    try:
        if _holds_licensed_data(instance_dir, rows, days, stations):
            if kept_by_content is not None:
                kept_by_content.append(instance_dir.name)
            return None
    except Exception:  # noqa: BLE001 - fail open on any definitions or listing surprise
        _fail_open(instance_dir, fail_open)
        return None
    return f"{_SKIP_PREFIX} last_written_ns {newest} < cutoff_ns {cutoff_ns}"


def _holds_licensed_data(
    instance_dir: Path,
    rows: Sequence[tuple[str, int, int]],
    days: Collection[dt.date],
    stations: Collection[str],
) -> bool:
    keep = sc.licensed_rung_filter(days, stations)
    if any(sc.licensed_rungs(instance_dir, stream, keep) for stream in sc.PER_RUNG_STREAMS):
        return True
    if _holds_flat_per_rung_file(instance_dir, rows):
        return True
    return _holds_licensed_listing(instance_dir, rows, days, stations)


def _holds_flat_per_rung_file(instance_dir: Path, rows: Sequence[tuple[str, int, int]]) -> bool:
    """Names only: a ``<table>_<ts>.feather`` of a per-rung stream outside its rung directory."""
    for path_s, _size, _mtime in rows:
        parts = Path(path_s).relative_to(instance_dir).parts
        if parts[0] not in _PER_RUNG_DIRS and parts[-1].startswith(_FLAT_PER_RUNG_PREFIXES):
            return True
    return False


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


def log_prefilter(
    skipped: Mapping[str, str], total: int, fail_open: int, kept_by_content: int
) -> None:
    """The one per-pass summary line: skips, instances listed, kept by error, kept by content.

    WARNING when either kept count is non-zero, else INFO: no maker_stage0 script configures
    logging, so only a WARNING reaches stderr (the last-resort handler drops INFO).
    """
    level = logging.WARNING if fail_open or kept_by_content else logging.INFO
    _LOG.log(
        level,
        "prefilter: skipped %s of %s instances (kept_by_fail_open %s, kept_by_content %s)",
        sum(1 for reason in skipped.values() if reason.startswith(_SKIP_PREFIX)),
        total,
        fail_open,
        kept_by_content,
    )
