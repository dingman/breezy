"""MAKER S2 WP0 -- the probe's on-disk frame store (S-5: the preamble must not grow with the tape).

The direction check needs, for every unique print, the last gap-free depth frame strictly before
it -- over the frames of EVERY recorder instance that saw the rung. Holding every ``Frame`` of all
96 station-days in the ledger until the last instance has been read costs gigabytes, so each
instance's gap-free frames are appended to a per-rung scratch file as soon as they are read and
the ledger keeps nothing. After the last instance a rung's file is read back (stable-sorted by
``ts_ns`` exactly as the in-memory merge was: append order is read order) and folded into the
direction tallies one rung at a time, so at most one rung's frames are alive.

A frame is a fixed record ``(ts_ns, mid coefficient, mid exponent)``: the mid ``Decimal`` is stored
as its exact (sign, digits, exponent) tuple, so the round trip is lossless and every comparison
against a print price is the one the in-memory path made. ``mid is None`` (one-sided or empty
book) is a reserved exponent. The scratch lives under the probe's ``work_root`` and is removed by
``close``; nothing is ever written under the capture root.
"""

from __future__ import annotations

import shutil
import struct
from collections import defaultdict
from collections.abc import Collection, Iterable, Iterator, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Final

from nautilus_trader.model.data import OrderBookDepth10
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

from breezy.adapters.polymarket_us.tape_records import DepthTruncation
from breezy.analysis.labeling.instrument_facts import bucket_facts_from_instrument_id
from breezy.analysis.maker_tape_census import PrintRecord
from scripts.analysis.maker_stage0_probe_core import (
    DirectionFold,
    DirectionResult,
    Frame,
    Gap,
    gap_free_frames,
    mid_of,
)

__all__ = ["FrameSpill", "count_truncations", "fold_directions", "read_depth_frames", "time_slices"]

_RECORD: Final[struct.Struct] = struct.Struct("<qqi")
_NO_MID: Final[int] = 2**31 - 1  # exponent sentinel: the frame's mid is None
_READ_RECORDS: Final[int] = 1 << 16  # records per read chunk (1.5 MiB)
_HOUR_NS: Final[int] = 3_600 * 1_000_000_000
FINE_SLICE_NS: Final[int] = 2 * _HOUR_NS  # inside the rung's own station-day window
COARSE_SLICE_NS: Final[int] = 48 * _HOUR_NS  # everywhere else in the query bounds


def _encode(frame: Frame) -> bytes:
    mid = frame.mid
    if mid is None:
        return _RECORD.pack(frame.ts_ns, 0, _NO_MID)
    sign, digits, exponent = mid.as_tuple()
    if not isinstance(exponent, int):  # NaN / Infinity can never be a book mid
        raise TypeError(f"frame mid {mid!r} is not a finite decimal")
    coefficient = int("".join(map(str, digits))) * (-1 if sign else 1)
    return _RECORD.pack(frame.ts_ns, coefficient, exponent)


class FrameSpill:
    """Append-only per-rung frame files with a stable, sorted read-back."""

    def __init__(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=False)
        self._dir = directory
        self._files: dict[str, Path] = {}

    def append(self, rung: str, frames: Iterable[Frame]) -> None:
        """Append ``frames`` to the rung's file in the given order."""
        blob = b"".join(map(_encode, frames))
        if not blob:
            return
        path = self._files.setdefault(rung, self._dir / f"{len(self._files):06d}.frames")
        with path.open("ab") as handle:
            handle.write(blob)

    def rungs(self) -> frozenset[str]:
        """The rungs that have at least one stored frame."""
        return frozenset(self._files)

    def load(self, rung: str) -> list[Frame]:
        """The rung's frames sorted by ``ts_ns`` (stable: equal stamps keep their append order)."""
        path = self._files.get(rung)
        if path is None:
            return []
        shared: dict[tuple[int, int], Decimal] = {}  # a rung repeats a few thousand mids at most
        frames: list[Frame] = []
        with path.open("rb") as handle:
            while chunk := handle.read(_RECORD.size * _READ_RECORDS):
                for ts_ns, coefficient, exponent in _RECORD.iter_unpack(chunk):
                    if exponent == _NO_MID:
                        frames.append(Frame(ts_ns, None))
                        continue
                    mid = shared.get((coefficient, exponent))
                    if mid is None:
                        mid = shared[(coefficient, exponent)] = Decimal(f"{coefficient}E{exponent}")
                    frames.append(Frame(ts_ns, mid))
        frames.sort(key=lambda f: f.ts_ns)
        return frames

    def close(self) -> None:
        shutil.rmtree(self._dir, ignore_errors=True)
        self._files.clear()


def _station_of(record: PrintRecord) -> str | None:
    facts = bucket_facts_from_instrument_id(record.rung)
    return None if facts is None else facts.settlement_station


def fold_directions(
    unique: Iterable[PrintRecord], spill: FrameSpill, control_station: str
) -> tuple[DirectionResult, DirectionResult]:
    """The pooled and the ``control_station`` direction result, one rung's frames alive at a time.

    A print reads only the frames of its own rung, so grouping the unique prints by rung and
    folding rung by rung gives the same tallies and ages as one pass over every frame at once.
    """
    by_rung: dict[str, list[PrintRecord]] = defaultdict(list)
    for record in unique:
        by_rung[record.rung].append(record)
    pooled, control = DirectionFold(), DirectionFold()
    for rung, group in by_rung.items():
        frames = {rung: spill.load(rung)}
        pooled.add(group, frames)
        control.add([r for r in group if _station_of(r) == control_station], frames)
    return pooled.result(), control.result()


def _steps(lo: int, hi: int, width: int) -> Iterator[tuple[int, int]]:
    for start in range(lo, hi + 1, width):
        yield start, min(start + width - 1, hi)


def time_slices(
    bounds: tuple[int, int],
    focus: tuple[int, int],
    fine: int = FINE_SLICE_NS,
    coarse: int = COARSE_SLICE_NS,
) -> Iterator[tuple[int, int]]:
    """Disjoint inclusive ``(start, end)`` ns slices whose union is exactly ``bounds``.

    ``focus`` (the rung's own window) is cut ``fine``, the rest ``coarse``; ``query`` bounds are
    inclusive at both ends, so adjacent slices touch at ``end + 1`` and a frame is in one slice.
    """
    lo, hi = bounds
    f_lo, f_hi = max(focus[0], lo), min(focus[1], hi)
    if f_lo > f_hi:
        yield from _steps(lo, hi, coarse)
        return
    if lo < f_lo:
        yield from _steps(lo, f_lo - 1, coarse)
    yield from _steps(f_lo, f_hi, fine)
    if f_hi < hi:
        yield from _steps(f_hi + 1, hi, coarse)


def read_depth_frames(
    work: ParquetDataCatalog,
    rung: str,
    gaps: Sequence[Gap],
    bounds: tuple[int, int],
    focus: tuple[int, int],
    spill: FrameSpill,
    fine: int = FINE_SLICE_NS,
    coarse: int = COARSE_SLICE_NS,
) -> int:
    """Spill the rung's gap-free (ts, mid) frames slice by slice; returns the depth frame count.

    Only one slice of ``OrderBookDepth10`` objects is materialised at a time (S-5). The slices
    partition ``bounds`` and the query is ordered by its bound column, so the appended sequence is
    the unsliced one.
    """
    total = 0
    for start, end in time_slices(bounds, focus, fine, coarse):
        depths = work.query(data_cls=OrderBookDepth10, identifiers=[rung], start=start, end=end)
        total += len(depths)
        frames = [Frame(d.ts_event, mid_of(d)) for d in depths]  # only (ts, mid) is kept
        spill.append(rung, gap_free_frames(frames, gaps))
    return total


TRUNCATION_SLICE_NS: Final[int] = _HOUR_NS


def count_truncations(work: ParquetDataCatalog, rungs: Collection[str]) -> int:
    """How many ``DepthTruncation`` rows belong to ``rungs``, read one time slice at a time.

    An instance holds millions of truncation rows (1.9M = 1.8 GB resident when queried whole, the
    S-5 OOM), so the file intervals the catalog already knows are cut into hour slices; the slices
    are disjoint and inclusive-bounded, so every row is counted once, as in the whole query.
    """
    wanted, total = frozenset(rungs), 0
    for lo, hi in work.get_intervals(DepthTruncation):
        for start, end in _steps(lo, hi, TRUNCATION_SLICE_NS):
            rows = work.query(data_cls=DepthTruncation, start=start, end=end)
            total += sum(str(getattr(t, "data", t).instrument_id) in wanted for t in rows)
    return total
