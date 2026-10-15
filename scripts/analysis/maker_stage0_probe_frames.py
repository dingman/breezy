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
from collections.abc import Iterable
from decimal import Decimal
from pathlib import Path
from typing import Final

from breezy.analysis.labeling.instrument_facts import bucket_facts_from_instrument_id
from breezy.analysis.maker_tape_census import PrintRecord
from scripts.analysis.maker_stage0_probe_core import DirectionFold, DirectionResult, Frame

__all__ = ["FrameSpill", "fold_directions"]

_RECORD: Final[struct.Struct] = struct.Struct("<qqi")
_NO_MID: Final[int] = 2**31 - 1  # exponent sentinel: the frame's mid is None
_READ_RECORDS: Final[int] = 1 << 16  # records per read chunk (1.5 MiB)


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
