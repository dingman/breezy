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

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from math import sqrt
from pathlib import Path
from typing import Final, Protocol

__all__ = [
    "CORPUS_SHA256",
    "FORECAST_OUTCOME_ALPHABET",
    "ON_DISK_BUILD_RAN",
    "RUNG_IDS",
    "DensityCell",
    "DensityKey",
    "DensityRecord",
    "DensityTable",
    "ForecastCorpusPinMismatchError",
    "ForecastDensityCell",
    "ForecastDensityKey",
    "ForecastDensityRecord",
    "ForecastDensityTable",
    "build_density_table",
    "build_forecast_density_table",
    "load_forecast_density_table",
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

#: Forecast-mode closed outcome alphabet (plan §7.5). Distinct from ``RUNG_IDS``.
FORECAST_OUTCOME_ALPHABET: Final[tuple[str, ...]] = (
    "below",
    "contains",
    "above1",
    "above2",
    "above3+",
)

ForecastDensityKey = tuple[str, str, int, str]


class ForecastCorpusPinMismatchError(ValueError):
    """Raised when the artefact sha256 does not match the manifest pin."""


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
class ForecastDensityRecord:
    """One settled station-day-hour labelled with a forecast-alphabet outcome."""

    station: str
    season: str
    hour_lst: int
    forecast_bucket: str
    outcome: str


@dataclass(frozen=True, slots=True)
class DensityCell:
    """6-rung DEGRADED cell. Wilson bounds are structurally non-null.

    ``_wilson_lower`` / ``_wilson_upper`` are total (0.0 / 1.0 at n=0), and
    ``build_density_table`` always calls both, so ``p_lower`` and ``p_upper``
    are plain ``float``. Forecast-mode nulling-below-``n_min_cell`` lives on
    :class:`ForecastDensityCell`, not here.
    """

    p_hat: float
    p_lower: float
    n_cell: int
    k_r: int
    p_upper: float


@dataclass(frozen=True, slots=True)
class ForecastDensityCell:
    """Forecast-mode cell. Bounds are ``None`` below ``n_min_cell``.

    YES uses ``p_lower``; NO uses ``1 - p_upper``. Never the degenerate
    Wilson-at-n=0 zero.
    """

    p_hat: float
    p_lower: float | None
    n_cell: int
    k_r: int
    p_upper: float | None


class _PartitionCell(Protocol):
    """Anything ``partition_check`` can sum — both cell types satisfy this."""

    p_hat: float


DensityTable = dict[DensityKey, dict[str, DensityCell]]
ForecastDensityTable = dict[ForecastDensityKey, dict[str, ForecastDensityCell]]


def _wilson_lower(successes: int, total: int, *, z: float = _Z_95) -> float:
    """Wilson 95% lower bound; restated from ``archive_correction_probe.py:352``."""
    if total == 0:
        return 0.0
    phat = successes / total
    denom = 1 + z * z / total
    center = (phat + z * z / (2 * total)) / denom
    half = z * sqrt((phat * (1 - phat) + z * z / (4 * total)) / total) / denom
    return max(0.0, center - half)


def _wilson_upper(successes: int, total: int, *, z: float = _Z_95) -> float:
    """Wilson 95% upper bound; mirror of :func:`_wilson_lower` (same interval)."""
    if total == 0:
        return 1.0
    phat = successes / total
    denom = 1 + z * z / total
    center = (phat + z * z / (2 * total)) / denom
    half = z * sqrt((phat * (1 - phat) + z * z / (4 * total)) / total) / denom
    return min(1.0, center + half)


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
                p_upper=_wilson_upper(per_rung[rung_id], n_cell),
            )
            for rung_id in RUNG_IDS
        }
    return table


def build_forecast_density_table(
    records: Iterable[ForecastDensityRecord],
    *,
    n_min_cell: int = 90,
) -> ForecastDensityTable:
    """Aggregate injected records into a forecast-alphabet density per 4-tuple key."""
    counts: dict[ForecastDensityKey, dict[str, int]] = defaultdict(
        lambda: dict.fromkeys(FORECAST_OUTCOME_ALPHABET, 0)
    )
    for record in records:
        if record.outcome not in FORECAST_OUTCOME_ALPHABET:
            raise ValueError(
                f"unknown outcome {record.outcome!r}; expected one of {FORECAST_OUTCOME_ALPHABET}"
            )
        key = (record.station, record.season, record.hour_lst, record.forecast_bucket)
        counts[key][record.outcome] += 1
    table: ForecastDensityTable = {}
    for key, per_outcome in counts.items():
        n_cell = sum(per_outcome.values())
        powered = n_cell >= n_min_cell
        table[key] = {
            outcome: ForecastDensityCell(
                p_hat=(per_outcome[outcome] / n_cell) if n_cell else 0.0,
                p_lower=_wilson_lower(per_outcome[outcome], n_cell) if powered else None,
                n_cell=n_cell,
                k_r=per_outcome[outcome],
                p_upper=_wilson_upper(per_outcome[outcome], n_cell) if powered else None,
            )
            for outcome in FORECAST_OUTCOME_ALPHABET
        }
    return table


def load_forecast_density_table(
    path: Path,
    *,
    density_artefact_sha256: str,
    n_min_cell: int = 90,
) -> ForecastDensityTable:
    """Load a forecast density artefact from disk; refuse a pin mismatch.

    The expected pin is the family-manifest ``density_artefact_sha256``, never
    a source constant.
    """
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != density_artefact_sha256:
        raise ForecastCorpusPinMismatchError(
            "forecast density artefact sha256 does not match the manifest pin "
            f"(expected {density_artefact_sha256!r}, got {digest!r})"
        )
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict) or "records" not in payload:
        raise ValueError(f"{path}: forecast density artefact must be an object with 'records'")
    rows = payload["records"]
    if not isinstance(rows, list):
        raise TypeError(f"{path}: 'records' must be a list")
    records: list[ForecastDensityRecord] = []
    required = ("station", "season", "hour_lst", "forecast_bucket", "outcome")
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise TypeError(f"{path}: records[{index}] must be an object")
        missing = [key for key in required if key not in row]
        if missing:
            raise ValueError(f"{path}: records[{index}] missing {missing}")
        records.append(
            ForecastDensityRecord(
                station=str(row["station"]),
                season=str(row["season"]),
                hour_lst=int(row["hour_lst"]),
                forecast_bucket=str(row["forecast_bucket"]),
                outcome=str(row["outcome"]),
            )
        )
    return build_forecast_density_table(records, n_min_cell=n_min_cell)


def partition_check[K](table: Mapping[K, Mapping[str, _PartitionCell]]) -> None:
    """Assert ``Σ_r p_hat = 1`` per key within ``1e-9``."""
    for key, cells in table.items():
        total = sum(cell.p_hat for cell in cells.values())
        assert abs(total - 1.0) <= 1e-9, (
            f"partition sum for {key!r} is {total!r}, not 1 within 1e-9"
        )
