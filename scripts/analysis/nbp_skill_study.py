#!/usr/bin/env python
"""CLI: NBP weather-only skill study (SL-8/SL-8b; plan
`FORECAST_NBP_PROBABILISTIC_FAMILY_Rev3_2026-09-29.md` S7 row SL-8, S2).

Wires `breezy.analysis.nbp_calibration`'s pure gate machinery to real data:
NBP rows from `breezy.persistence.nbp_derived_store`, final-only CLI labels
via `settlement_truth_dataset.final_rows_for_gate`, and (for M0/M1
coverage/G2.0a) the on-disk, read-only IEM MOS NBS and IEM ASOS 1-minute
archive caches. It runs the validation-stage real-data JOIN and reports
coverage; it does not run the S2 gates themselves (a later slice) and never
writes a sha-pinned calibration artefact.

**The holdout guard.** ``--stage validate`` (the default) never touches the
holdout. Every NBP window is mapped to its climate day via
`forecast_climate_day_map.climate_day_for_txn` and dropped BEFORE it is ever
looked up against settlement truth if that climate day falls in or after
`breezy.analysis.nbp_calibration.DEFAULT_SPLITS.holdout_start`
(2026-07-01) -- defense in depth on top of `Splits.split_for_date`'s own
classification, which is checked again once the row is built. ``--stage
holdout`` exists but this script is NOT the authority that decides when the
holdout may open -- it refuses outright unless ``--coordinator-authorized``
is passed explicitly, mirroring `nbp_calibration.open_holdout`'s own
single-look refusal.

**Real-data join (SL-8b task 5).** ``--stage validate`` joins three real,
on-disk, already-backfilled sources -- never fetches:

* NBP percentile rows from `breezy.persistence.nbp_derived_store`
  (`~/.local/share/breezy/derived/nbp` by default), restricted to the
  13Z/19Z/01Z cycles and the NEAREST (D+1) 00Z daily-max window per
  (station, cycle).
* Final CLI settlement labels via `settlement_truth_dataset
  .final_rows_for_gate`, read from the settlement-truth parquet
  (`~/.local/share/breezy/derived/settlement-truth/settlement_truth.parquet`
  by default). Stations are mapped KLAX/KSFO/KMDW/KMIA -> LAX/SFO/MDW/MIA
  (the settlement dataset's own station keys, `settlement_alignment_study
  .IEM_ASOS_IDS`) before the join.
* M0/M1 raw-input coverage (real `txn`/`xnd` row counts) from the on-disk
  IEM MOS NBS archive cache, and raw row coverage from the IEM ASOS 1-minute
  archive cache (G2.0a's eventual daily-max-instant source) -- both read
  read-only via `breezy.persistence.archive_cache.ArchiveCache`, reported
  per station, never imputed when absent.

Missing rows (an incomplete percentile window, an unmapped station, no
settlement-truth match, a holdout exclusion) are COUNTED and reported, never
silently dropped or imputed. Memory stays bounded: the NBP derived store is
read one partition file at a time (`nbp_derived_store.read_partition`); a
partition that fails to parse (the backfill may still be writing) is
skipped and counted, never fatal.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

_SCRIPTS_ANALYSIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPTS_ANALYSIS_DIR.parents[1]
for _entry in (str(_SCRIPTS_ANALYSIS_DIR), str(_REPO_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from forecast_climate_day_map import ForecastValidPeriodError, climate_day_for_txn  # type: ignore[import-not-found]  # noqa: E402
from mos_txn_occupancy import parse_mos_txn_rows  # type: ignore[import-not-found]  # noqa: E402
from settlement_alignment_study import IEM_ASOS_IDS, load_sites  # type: ignore[import-not-found]  # noqa: E402
from settlement_truth_dataset import SettlementTruthRow, final_rows_for_gate  # type: ignore[import-not-found]  # noqa: E402

from breezy.analysis.nbp_calibration import DEFAULT_SPLITS, Splits, VersionRow  # noqa: E402
from breezy.persistence.archive_cache import (  # noqa: E402
    IEM_ASOS_1MIN_SOURCE,
    IEM_MOS_MODEL_PRODUCTS,
    IEM_MOS_SOURCE,
    ArchiveCache,
    ArchiveRequest,
)
from breezy.persistence.nbp_derived_store import DerivedNbpRow, read_partition  # noqa: E402
from breezy.strategy.ladder_ev.quantile_density import Percentiles  # noqa: E402

__all__ = [
    "DEFAULT_ARCHIVE_ROOT",
    "DEFAULT_NBP_DERIVED_ROOT",
    "DEFAULT_SETTLEMENT_TRUTH_PARQUET",
    "QUALIFYING_CYCLE_HOURS",
    "TXN_VARIABLES",
    "HoldoutNotCoordinatorAuthorizedError",
    "JoinReport",
    "NbpPercentileWindow",
    "build_arg_parser",
    "build_version_rows",
    "iter_nbp_derived_rows",
    "main",
    "mos_txn_coverage",
    "asos_1min_row_coverage",
    "nearest_percentile_windows",
    "read_settlement_truth_rows",
    "run_validate",
    "station_registry",
]

_HOLDOUT_GUARD_FLAG: str = "--coordinator-authorized"

DEFAULT_NBP_DERIVED_ROOT: Final[Path] = Path.home() / ".local/share/breezy/derived/nbp"
DEFAULT_SETTLEMENT_TRUTH_PARQUET: Final[Path] = (
    Path.home() / ".local/share/breezy/derived/settlement-truth/settlement_truth.parquet"
)
DEFAULT_ARCHIVE_ROOT: Final[Path] = Path.home() / ".local/share/breezy/archive"

#: 13Z/19Z/01Z -- the pre-decision-window cycles feeding a D+1 trading
#: decision (SL-8b task 5's own instruction).
QUALIFYING_CYCLE_HOURS: Final[tuple[int, ...]] = (13, 19, 1)

#: The seven NBP quantile-bulletin fields one `Percentiles` needs
#: (`nbm_quantile_parse.TXN_VARIABLE_BY_ROW_LABEL`'s values).
TXN_VARIABLES: Final[tuple[str, ...]] = (
    "TXN_MEAN",
    "TXN_SD",
    "TXN_Q10",
    "TXN_Q25",
    "TXN_Q50",
    "TXN_Q75",
    "TXN_Q90",
)

_SECONDS_PER_HOUR: Final[int] = 3600
_NS_PER_SECOND: Final[int] = 10**9
_HOURS_PER_DAY: Final[int] = 24

#: The four stations this join covers (SL-8b task 5). KNYC is registered in
#: `settlement_alignment_study` too but is out of scope for this slice.
_JOIN_STATIONS: Final[tuple[str, ...]] = ("KLAX", "KMDW", "KMIA", "KSFO")


class HoldoutNotCoordinatorAuthorizedError(RuntimeError):
    """``--stage holdout`` was requested without the coordinator-only flag."""


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage",
        choices=("validate", "holdout"),
        default="validate",
        help="'validate' (default) never touches the holdout. 'holdout' needs "
        f"{_HOLDOUT_GUARD_FLAG}.",
    )
    parser.add_argument(
        "--coordinator-authorized",
        action="store_true",
        default=False,
        help="Required for --stage holdout. Never set this by default -- only "
        "an explicit coordinator call may open the holdout (plan S7 row SL-8).",
    )
    parser.add_argument("--nbp-derived-root", type=Path, default=DEFAULT_NBP_DERIVED_ROOT)
    parser.add_argument(
        "--settlement-truth-root",
        type=Path,
        default=DEFAULT_SETTLEMENT_TRUTH_PARQUET.parent,
        help="Directory containing settlement_truth.parquet.",
    )
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--out", type=Path, default=None)
    return parser


# ---------------------------------------------------------------------------
# Station registry (icao -> std UTC offset hours, icao -> settlement station key).
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StationRegistry:
    std_utc_offset_hours_by_icao: Mapping[str, float]
    settlement_station_by_icao: Mapping[str, str]


def station_registry(*, stations: Sequence[str] = _JOIN_STATIONS) -> StationRegistry:
    """The join's station identity, sourced from the SAME registry every
    other analysis script uses (`settlement_alignment_study.load_sites`) --
    never a second, hand-maintained copy of the offsets or the station-key
    mapping."""
    wanted = frozenset(stations)
    offsets: dict[str, float] = {}
    keys: dict[str, str] = {}
    for spec in load_sites():
        icao = spec.site.icao
        if icao not in wanted:
            continue
        offsets[icao] = spec.std_utc_offset_hours
        keys[icao] = IEM_ASOS_IDS[icao]
    return StationRegistry(std_utc_offset_hours_by_icao=offsets, settlement_station_by_icao=keys)


# ---------------------------------------------------------------------------
# NBP percentile windows (SL-8b task 5): read one partition at a time,
# reduce to one Percentiles per (station, cycle_runtime_ns).
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NbpPercentileWindow:
    """One (station, cycle) forecast's D+1 (nearest) daily-max percentile
    bulletin, reconstructed from the 7 `TXN_VARIABLES` derived-store rows
    that share the SAME (station, cycle_runtime_ns, valid_start_ns)."""

    station: str
    cycle_runtime_ns: int
    valid_start_ns: int
    nbm_version_era: str
    percentiles: Percentiles


def iter_nbp_derived_rows(root: Path) -> Iterable[tuple[Path, tuple[DerivedNbpRow, ...] | None]]:
    """Yield ``(path, rows_or_None)`` for every partition under ``root``, one
    file at a time -- bounded memory (SL-8b task 5). ``rows`` is ``None`` for
    a partition that failed to parse (the backfill may still be writing
    it) -- the caller counts this, never raises.
    """
    if not root.exists():
        return
    for path in sorted(root.rglob("*.parquet")):
        try:
            yield path, read_partition(path)
        except Exception:  # noqa: BLE001 - a partial/mid-write partition is expected, not fatal
            yield path, None


def _cycle_hour(cycle_runtime_ns: int) -> int:
    return (cycle_runtime_ns // (_SECONDS_PER_HOUR * _NS_PER_SECOND)) % _HOURS_PER_DAY


@dataclass(slots=True)
class _WindowGroupCounts:
    incomplete_windows: int = 0
    unparseable_partitions: int = 0


def nearest_percentile_windows(
    rows: Iterable[DerivedNbpRow], *, counts: _WindowGroupCounts | None = None
) -> list[NbpPercentileWindow]:
    """Reduce derived rows to one :class:`NbpPercentileWindow` per (station,
    cycle_runtime_ns) -- the NEAREST ``valid_start_ns`` window that carries
    ALL seven :data:`TXN_VARIABLES` with a non-null ``value_f``. A window
    missing any variable, or with a null value, is counted (never imputed,
    never silently promoted to the next-nearest window under a different
    identity).
    """
    by_group: dict[tuple[str, int, int], dict[str, DerivedNbpRow]] = {}
    for row in rows:
        if row.variable not in TXN_VARIABLES:
            continue
        key = (row.station, row.cycle_runtime_ns, row.valid_start_ns)
        by_group.setdefault(key, {})[row.variable] = row

    best: dict[tuple[str, int], tuple[int, dict[str, DerivedNbpRow]]] = {}
    incomplete = 0
    for (station, cycle_runtime_ns, valid_start_ns), variables in by_group.items():
        complete = set(variables) == set(TXN_VARIABLES) and all(
            entry.value_f is not None for entry in variables.values()
        )
        if not complete:
            incomplete += 1
            continue
        current = best.get((station, cycle_runtime_ns))
        if current is None or valid_start_ns < current[0]:
            best[(station, cycle_runtime_ns)] = (valid_start_ns, variables)

    if counts is not None:
        counts.incomplete_windows += incomplete

    windows: list[NbpPercentileWindow] = []
    for (station, cycle_runtime_ns), (valid_start_ns, variables) in best.items():
        any_row = next(iter(variables.values()))
        percentiles = Percentiles(
            q10=variables["TXN_Q10"].value_f,  # type: ignore[arg-type]
            q25=variables["TXN_Q25"].value_f,  # type: ignore[arg-type]
            q50=variables["TXN_Q50"].value_f,  # type: ignore[arg-type]
            q75=variables["TXN_Q75"].value_f,  # type: ignore[arg-type]
            q90=variables["TXN_Q90"].value_f,  # type: ignore[arg-type]
            mean=variables["TXN_MEAN"].value_f,  # type: ignore[arg-type]
            sd=variables["TXN_SD"].value_f,  # type: ignore[arg-type]
        )
        windows.append(
            NbpPercentileWindow(
                station=station,
                cycle_runtime_ns=cycle_runtime_ns,
                valid_start_ns=valid_start_ns,
                nbm_version_era=any_row.nbm_version_era,
                percentiles=percentiles,
            )
        )
    return windows


# ---------------------------------------------------------------------------
# Settlement truth (real parquet -> SettlementTruthRow).
# ---------------------------------------------------------------------------


def read_settlement_truth_rows(
    path: Path, *, climate_day_before: dt.date | None = None
) -> tuple[SettlementTruthRow, ...]:
    """Read the settlement-truth parquet back into `SettlementTruthRow`s.

    `settlement_truth_dataset.py` writes this file (`rows_to_table` /
    `write_dataset`) but exposes no reader of its own -- this is that
    reader's one caller-facing addition, kept in THIS module rather than
    duplicated: a plain column-for-field reconstruction, never
    `dataclasses.asdict` (banned in this repo outside its closed allowlist,
    `tests/unit/test_polymarket_us_credential_serialization.py`) and not
    needed here either, since this is a READ, not a serialise.

    ``climate_day_before`` (HARD RULE: never read a CLI label dated
    2026-07-01 or later) is applied as a pyarrow ROW-FILTER at read time --
    not a post-read discard -- so a holdout-dated row is never even
    materialised into a `SettlementTruthRow` in validate mode, on top of
    :func:`_settlement_lookup`'s own defense-in-depth filter.
    """
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    if not path.exists():
        return ()
    filters = None if climate_day_before is None else pc.field("climate_day") < climate_day_before
    table = pq.read_table(path, filters=filters)
    return tuple(SettlementTruthRow(**record) for record in table.to_pylist())


def _settlement_lookup(
    rows: Sequence[SettlementTruthRow], *, holdout_start: dt.date
) -> dict[tuple[str, dt.date], SettlementTruthRow]:
    """Final-only rows, pre-filtered to STRICTLY before ``holdout_start``
    (HARD RULE: never read a CLI label dated 2026-07-01 or later) -- defense
    in depth on top of BOTH :func:`read_settlement_truth_rows`'s own
    read-time filter and the NBP-side climate-day filter in
    :func:`build_version_rows`.
    """
    finals = final_rows_for_gate(rows)
    return {
        (row.station, row.climate_day): row for row in finals if row.climate_day < holdout_start
    }


# ---------------------------------------------------------------------------
# The join itself (SL-8b task 5).
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class JoinReport:
    """Real, honest join coverage (SL-8b tasks 5/6) -- every gap counted,
    never imputed."""

    total_percentile_windows: int
    incomplete_percentile_windows: int
    unparseable_partitions: int
    non_qualifying_cycle_windows: int
    unmapped_station_windows: int
    period_kind_mismatches: int
    holdout_excluded_windows: int
    missing_settlement_rows: int
    matched_version_rows: int
    n_by_split: Mapping[str, int]
    n_by_version: Mapping[str, int]
    mos_txn_populated_rows_by_station: Mapping[str, int]
    asos_1min_rows_by_station: Mapping[str, int]


def build_version_rows(
    windows: Sequence[NbpPercentileWindow],
    settlement_by_station_day: Mapping[tuple[str, dt.date], SettlementTruthRow],
    *,
    registry: StationRegistry,
    splits: Splits = DEFAULT_SPLITS,
) -> tuple[tuple[VersionRow, ...], dict[str, int]]:
    """The real join: percentile window x final CLI label -> `VersionRow`.

    Returns ``(version_rows, gap_counts)`` -- ``gap_counts`` keys are
    ``non_qualifying_cycle``, ``unmapped_station``, ``period_kind_mismatch``,
    ``holdout_excluded``, ``missing_settlement``. Every row this function
    KEEPS has already passed the D+1 LST climate-day mapping
    (`climate_day_for_txn`, kind="max") and is strictly before
    ``splits.holdout_start`` -- checked TWICE (before the settlement lookup,
    and again against `Splits.split_for_date`'s own classification) so a
    holdout-dated row can never reach the returned tuple by either path.
    """
    gaps: Counter[str] = Counter()
    version_rows: list[VersionRow] = []
    for window in windows:
        if _cycle_hour(window.cycle_runtime_ns) not in QUALIFYING_CYCLE_HOURS:
            gaps["non_qualifying_cycle"] += 1
            continue
        offset = registry.std_utc_offset_hours_by_icao.get(window.station)
        settlement_station = registry.settlement_station_by_icao.get(window.station)
        if offset is None or settlement_station is None:
            gaps["unmapped_station"] += 1
            continue
        try:
            climate_day = climate_day_for_txn(
                icao=window.station,
                runtime_ns=window.cycle_runtime_ns,
                ftime_ns=window.valid_start_ns,
                std_utc_offset_hours=offset,
                model=window.nbm_version_era,
                kind="max",
            )
        except ForecastValidPeriodError:
            gaps["period_kind_mismatch"] += 1
            continue

        if climate_day >= splits.holdout_start:
            gaps["holdout_excluded"] += 1
            continue

        settlement_row = settlement_by_station_day.get((settlement_station, climate_day))
        if settlement_row is None or settlement_row.tmax_f is None:
            gaps["missing_settlement"] += 1
            continue

        split = splits.split_for_date(climate_day)
        if split == "holdout":  # pragma: no cover - defense in depth, unreachable given the check above
            gaps["holdout_excluded"] += 1
            continue

        version_rows.append(
            VersionRow(
                version=window.nbm_version_era,
                split=split,
                station=settlement_station,
                climate_day=climate_day,
                percentiles=window.percentiles,
                cli_tmax_f=float(settlement_row.tmax_f),
            )
        )
    return tuple(version_rows), dict(gaps)


# ---------------------------------------------------------------------------
# M0/M1 real-input coverage (IEM MOS NBS archive) + G2.0a's raw-row
# coverage (IEM ASOS 1-minute archive) -- both read-only, never fetch.
# ---------------------------------------------------------------------------


def _read_only_archive_cache(source: str, *, archive_root: Path) -> ArchiveCache:
    def _refuse(_request: object) -> bytes:
        raise RuntimeError(
            "nbp_skill_study never fetches; the archive must already be on disk"
        )

    class _NoClock:
        def timestamp_ns(self) -> int:
            return 0

    return ArchiveCache(root=archive_root / source, fetch=_refuse, clock=_NoClock())


def mos_txn_coverage(
    *, archive_root: Path, stations: Sequence[str] = _JOIN_STATIONS, model: str = "NBS"
) -> dict[str, int]:
    """Real, `txn`-populated MOS row counts per station from the on-disk IEM
    MOS archive cache (SL-8b task 5's M0/M1 inputs) -- read-only, never
    fetches. A station absent from the cache reports ``0``, never omitted.
    """
    cache = _read_only_archive_cache(IEM_MOS_SOURCE, archive_root=archive_root)
    product = IEM_MOS_MODEL_PRODUCTS[model]
    counts: dict[str, int] = {station: 0 for station in stations}
    for entry in cache.entries(IEM_MOS_SOURCE):
        if entry.station not in counts or entry.product != product:
            continue
        request = ArchiveRequest(
            source=IEM_MOS_SOURCE,
            station=entry.station,
            product=entry.product,
            window_start=entry.window_start,
            window_end=entry.window_end,
            model=entry.model,
        )
        try:
            body = cache.read(request)
        except Exception:  # noqa: BLE001 - a partial backfill payload is a gap, not fatal
            continue
        rows = parse_mos_txn_rows(body.decode("utf-8", errors="replace"))
        counts[entry.station] += sum(1 for row in rows if row.txn_present)
    return counts


def asos_1min_row_coverage(
    *, archive_root: Path, stations: Sequence[str] = _JOIN_STATIONS
) -> dict[str, int]:
    """Raw cached-row counts per station from the on-disk IEM ASOS 1-minute
    archive cache (G2.0a's eventual daily-max-instant source, SL-8b task 5)
    -- read directly off the manifest's own `CoverageEntry.rows`, never
    parsed (no daily-max-instant computation in this slice; "where it
    exists" per the task, reported as coverage only). A station with no
    manifested entries reports ``0``.
    """
    cache = _read_only_archive_cache(IEM_ASOS_1MIN_SOURCE, archive_root=archive_root)
    counts: dict[str, int] = {station: 0 for station in stations}
    for entry in cache.entries(IEM_ASOS_1MIN_SOURCE):
        if entry.station in counts:
            counts[entry.station] += entry.rows
    return counts


# ---------------------------------------------------------------------------
# The validate-stage run.
# ---------------------------------------------------------------------------


def run_validate(
    *,
    nbp_derived_root: Path,
    settlement_truth_parquet: Path,
    archive_root: Path,
    splits: Splits = DEFAULT_SPLITS,
) -> tuple[tuple[VersionRow, ...], JoinReport]:
    registry = station_registry()
    settlement_rows = read_settlement_truth_rows(
        settlement_truth_parquet, climate_day_before=splits.holdout_start
    )
    settlement_by_station_day = _settlement_lookup(settlement_rows, holdout_start=splits.holdout_start)

    counts = _WindowGroupCounts()
    all_windows: list[NbpPercentileWindow] = []
    for _path, rows in iter_nbp_derived_rows(nbp_derived_root):
        if rows is None:
            counts.unparseable_partitions += 1
            continue
        all_windows.extend(nearest_percentile_windows(rows, counts=counts))

    version_rows, gaps = build_version_rows(all_windows, settlement_by_station_day, registry=registry, splits=splits)

    n_by_split: Counter[str] = Counter(row.split for row in version_rows)
    n_by_version: Counter[str] = Counter(row.version for row in version_rows)

    report = JoinReport(
        total_percentile_windows=len(all_windows),
        incomplete_percentile_windows=counts.incomplete_windows,
        unparseable_partitions=counts.unparseable_partitions,
        non_qualifying_cycle_windows=gaps.get("non_qualifying_cycle", 0),
        unmapped_station_windows=gaps.get("unmapped_station", 0),
        period_kind_mismatches=gaps.get("period_kind_mismatch", 0),
        holdout_excluded_windows=gaps.get("holdout_excluded", 0),
        missing_settlement_rows=gaps.get("missing_settlement", 0),
        matched_version_rows=len(version_rows),
        n_by_split=dict(n_by_split),
        n_by_version=dict(n_by_version),
        mos_txn_populated_rows_by_station=mos_txn_coverage(archive_root=archive_root),
        asos_1min_rows_by_station=asos_1min_row_coverage(archive_root=archive_root),
    )
    return version_rows, report


def _report_to_json_dict(report: JoinReport) -> dict[str, object]:
    return {
        "total_percentile_windows": report.total_percentile_windows,
        "incomplete_percentile_windows": report.incomplete_percentile_windows,
        "unparseable_partitions": report.unparseable_partitions,
        "non_qualifying_cycle_windows": report.non_qualifying_cycle_windows,
        "unmapped_station_windows": report.unmapped_station_windows,
        "period_kind_mismatches": report.period_kind_mismatches,
        "holdout_excluded_windows": report.holdout_excluded_windows,
        "missing_settlement_rows": report.missing_settlement_rows,
        "matched_version_rows": report.matched_version_rows,
        "n_by_split": dict(sorted(report.n_by_split.items())),
        "n_by_version": dict(sorted(report.n_by_version.items())),
        "mos_txn_populated_rows_by_station": dict(sorted(report.mos_txn_populated_rows_by_station.items())),
        "asos_1min_rows_by_station": dict(sorted(report.asos_1min_rows_by_station.items())),
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.stage == "holdout" and not args.coordinator_authorized:
        raise HoldoutNotCoordinatorAuthorizedError(
            f"--stage holdout needs {_HOLDOUT_GUARD_FLAG} -- only an explicit "
            "coordinator call may open it (plan S7 row SL-8)"
        )
    if args.stage == "holdout":
        print(f"nbp_skill_study: stage={args.stage} splits={DEFAULT_SPLITS!r}")
        return 0

    settlement_truth_parquet = args.settlement_truth_root / DEFAULT_SETTLEMENT_TRUTH_PARQUET.name
    _version_rows, report = run_validate(
        nbp_derived_root=args.nbp_derived_root,
        settlement_truth_parquet=settlement_truth_parquet,
        archive_root=args.archive_root,
    )
    import json

    payload = _report_to_json_dict(report)
    print(f"nbp_skill_study: stage=validate splits={DEFAULT_SPLITS!r}")
    print(json.dumps(payload, indent=2, sort_keys=True))
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
