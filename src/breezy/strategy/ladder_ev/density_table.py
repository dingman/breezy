"""6-rung conditional density ``P(r | station, season, hour_lst, width, m)``.

Builder consumes an injected records iterable. The on-disk freeze of CRH's
archive corpus is **not** a 6-rung partition (``P_HOLD_LOWER`` is a
current-rung selector), so this module does not fabricate a frozen table.

Archive loaders reused from
``scripts/analysis/generate_current_rung_hold_archive_table.py``:

* ``:38-50``  ``load_archive_days_and_finals``, ``build_archive_table``,
  ``WIDTH_*``, ``ArchiveCell`` / ``ArchiveCellKey``
* ``:84-112`` ``_corpus_files``
* ``:115-125`` ``corpus_sha256`` (RAW archive corpus bytes CRH's selector
  was built from)
* ``:148-171`` ``build_frozen_table``

``CORPUS_SHA256`` pins those RAW archive corpus bytes
(``generate_current_rung_hold_archive_table.py:115-125``), the same pin as
``current_rung_hold.archive_table.CORPUS_SHA256``. It is NOT a hash of the
6-rung table. ``ON_DISK_BUILD_RAN`` is False: the on-disk 6-rung freeze is
NOT RUN; the 6-rung table is built from injected records.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from math import sqrt
from typing import Final

__all__ = [
    "CORPUS_SHA256",
    "ON_DISK_BUILD_RAN",
    "RUNG_IDS",
    "DensityCell",
    "DensityKey",
    "DensityRecord",
    "DensityTable",
    "build_density_table",
    "partition_check",
]

#: Pin of the RAW archive corpus bytes CRH's selector was built from
#: (``generate_current_rung_hold_archive_table.py:115-125``). Same value as
#: ``current_rung_hold.archive_table.CORPUS_SHA256``. NOT a hash of the
#: 6-rung table.
CORPUS_SHA256: Final[str] = "3b410fb9c0c9208c5afb5cd8de05789077aca93c71fd540ddae0607ad6f04d48"

#: The on-disk 6-rung freeze is NOT RUN.
ON_DISK_BUILD_RAN: Final[bool] = False

#: Venue 6-rung identity: open-lower, four 2 °F interiors, open-upper.
RUNG_IDS: Final[tuple[str, ...]] = ("lt", "i0", "i1", "i2", "i3", "gte")

_Z_95: Final[float] = 1.959963984540054

DensityKey = tuple[str, str, int, int, int]


@dataclass(frozen=True, slots=True)
class DensityRecord:
    """One labelled station-day-hour that settled in ``rung_id``."""

    station: str
    season: str
    hour_lst: int
    width_code: int
    m_code: int
    rung_id: str


@dataclass(frozen=True, slots=True)
class DensityCell:
    """``p_hat``, Wilson-95% lower, and cell count for one rung of a key."""

    p_hat: float
    p_lower: float
    n_cell: int
    k_r: int


DensityTable = dict[DensityKey, dict[str, DensityCell]]


def _wilson_lower(successes: int, total: int, *, z: float = _Z_95) -> float:
    """Wilson 95% lower bound; restated from ``archive_correction_probe.py:352``."""
    if total == 0:
        return 0.0
    phat = successes / total
    denom = 1 + z * z / total
    center = (phat + z * z / (2 * total)) / denom
    half = z * sqrt((phat * (1 - phat) + z * z / (4 * total)) / total) / denom
    return max(0.0, center - half)


def build_density_table(records: Iterable[DensityRecord]) -> DensityTable:
    """Aggregate injected records into a 6-rung density per CRH-shaped key."""
    counts: dict[DensityKey, dict[str, int]] = defaultdict(lambda: dict.fromkeys(RUNG_IDS, 0))
    for record in records:
        if record.rung_id not in RUNG_IDS:
            raise ValueError(f"unknown rung_id {record.rung_id!r}; expected one of {RUNG_IDS}")
        key = (
            record.station,
            record.season,
            record.hour_lst,
            record.width_code,
            record.m_code,
        )
        counts[key][record.rung_id] += 1
    table: DensityTable = {}
    for key, per_rung in counts.items():
        n_cell = sum(per_rung.values())
        table[key] = {
            rung_id: DensityCell(
                p_hat=(per_rung[rung_id] / n_cell) if n_cell else 0.0,
                p_lower=_wilson_lower(per_rung[rung_id], n_cell),
                n_cell=n_cell,
                k_r=per_rung[rung_id],
            )
            for rung_id in RUNG_IDS
        }
    return table


def partition_check(table: Mapping[DensityKey, Mapping[str, DensityCell]]) -> None:
    """Assert ``Σ_r p_hat = 1`` per key within ``1e-9``."""
    for key, cells in table.items():
        total = sum(cell.p_hat for cell in cells.values())
        assert abs(total - 1.0) <= 1e-9, (
            f"partition sum for {key!r} is {total!r}, not 1 within 1e-9"
        )
