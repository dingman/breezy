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
  13Z/19Z/01Z cycles and the EXPLICIT D+1 00Z daily-max window per
  (station, cycle) -- see :func:`build_version_rows`'s own docstring for
  the exact target computation. The window is picked by matching
  `climate_day_for_txn`'s own result to that target, never by "nearest
  available `valid_start_ns`": on the REAL NBP bulletin grid the two
  happen to select the identical window on every cycle observed so far
  (`tests/unit/test_nbm_quantile_parse.py` pins that the FIRST published
  MAX column already targets D+1 at every station, for 13Z, 19Z and 01Z
  alike -- a same-LST-day MAX is never published), but the explicit match
  is not merely cosmetic: it REFUSES (counted, never imputed) rather than
  silently accepts a window at any other day, should a malformed partition
  or a future grid change ever produce one (SL-8b review item 1).
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
import csv
import datetime as dt
import io
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
from mos_txn_occupancy import MosTxnRow, parse_mos_txn_rows  # type: ignore[import-not-found]  # noqa: E402
from settlement_alignment_study import IEM_ASOS_IDS, load_sites  # type: ignore[import-not-found]  # noqa: E402
from settlement_truth_dataset import SettlementTruthRow, final_rows_for_gate  # type: ignore[import-not-found]  # noqa: E402

from breezy.analysis.nbp_calibration import DEFAULT_SPLITS, NEAR_MIDNIGHT_STRATA, Splits, VersionRow  # noqa: E402
from breezy.analysis.nbp_comparator_models import (  # noqa: E402
    M0_PRIMARY_LEAD_HOURS,
    DailyMaxInstant,
    is_near_lst_midnight,
    load_frozen_0b_error_model,
    lst_clock_time,
    m0_rung_probabilities,
    m1_rung_probabilities,
    target_climate_day,
)
from breezy.ingest.gaps import local_standard_date  # noqa: E402
from breezy.persistence.archive_cache import (  # noqa: E402
    IEM_ASOS_1MIN_SOURCE,
    IEM_MOS_MODEL_PRODUCTS,
    IEM_MOS_SOURCE,
    ArchiveCache,
    ArchiveRequest,
)
from breezy.persistence.nbp_derived_store import DerivedNbpRow, read_partition  # noqa: E402
from breezy.strategy.ladder_ev.quantile_density import (  # noqa: E402
    CdfMethod,
    Percentiles,
    Rung,
    build_cdf,
    rung_probabilities,
)
from breezy.strategy.weather_common.probability import ForecastErrorModel  # noqa: E402

__all__ = [
    "DEFAULT_ARCHIVE_ROOT",
    "DEFAULT_NBP_DERIVED_ROOT",
    "DEFAULT_SETTLEMENT_TRUTH_PARQUET",
    "FROZEN_0B_ARTEFACT_RELPATH",
    "QUALIFYING_CYCLE_HOURS",
    "TXN_VARIABLES",
    "AsosRowOrderError",
    "ComparatorJoinReport",
    "ComparatorMatchedEvent",
    "HoldoutNotCoordinatorAuthorizedError",
    "JoinReport",
    "NbpPercentileWindow",
    "RawMosTxnXnd",
    "build_arg_parser",
    "build_comparator_matched_events",
    "build_version_rows",
    "complete_percentile_windows",
    "daily_max_instants",
    "iter_nbp_derived_rows",
    "main",
    "mos_txn_coverage",
    "mos_txn_xnd_by_cycle",
    "asos_1min_row_coverage",
    "read_settlement_truth_rows",
    "run_comparator_validate",
    "run_validate",
    "station_registry",
]

_HOLDOUT_GUARD_FLAG: str = "--coordinator-authorized"

DEFAULT_NBP_DERIVED_ROOT: Final[Path] = Path.home() / ".local/share/breezy/derived/nbp"
DEFAULT_SETTLEMENT_TRUTH_PARQUET: Final[Path] = (
    Path.home() / ".local/share/breezy/derived/settlement-truth/settlement_truth.parquet"
)
DEFAULT_ARCHIVE_ROOT: Final[Path] = Path.home() / ".local/share/breezy/archive"

#: Relative to the repo root. The frozen 0b error model artefact (SL-8c),
#: fitted once on the WP-6 TRAIN split and committed as the freeze point
#: (`breezy.analysis.nbp_comparator_models` module docstring "Provenance,
#: stated precisely") so M0 never re-runs the fit. Lives HERE, not in
#: `breezy.analysis.nbp_comparator_models`, because `docs/evidence/` is
#: EVIDENCE ONLY -- NEVER INGEST from `src/` (see
#: `tests/unit/test_probe_containment.py::test_no_module_under_src_reads_docs_evidence`);
#: this script is the caller allowed to name that path and hand the loader an
#: explicit :class:`~pathlib.Path`.
FROZEN_0B_ARTEFACT_RELPATH: Final[str] = "docs/evidence/FC_0b_FROZEN_ERROR_MODEL_2026-09-19.json"

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
    parser.add_argument(
        "--comparator-models",
        action="store_true",
        default=False,
        help="Also run the SL-8c M0/M1/M2 + G2.0a comparator join. Opt-in: "
        "unlike the coverage-only counts above, this fully parses the ASOS "
        "1-minute archive, which is not cheap.",
    )
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
    """One (station, cycle, valid_start) forecast's daily-max percentile
    bulletin, reconstructed from the 7 `TXN_VARIABLES` derived-store rows
    that share the SAME (station, cycle_runtime_ns, valid_start_ns). A
    (station, cycle) may have more than one complete window (the venue can
    publish several 00Z daily-max valid times per cycle) -- WHICH one is
    the D+1 target is decided explicitly by :func:`build_version_rows`,
    never here."""

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


def complete_percentile_windows(
    rows: Iterable[DerivedNbpRow], *, counts: _WindowGroupCounts | None = None
) -> list[NbpPercentileWindow]:
    """Reduce derived rows to one :class:`NbpPercentileWindow` per COMPLETE
    (station, cycle_runtime_ns, valid_start_ns) group -- EVERY complete
    window, never a single "nearest" one. A window missing any
    :data:`TXN_VARIABLES` entry, or with a null ``value_f``, is counted
    (never imputed, never silently substituted for a different identity).

    Deliberately does NOT reduce further to one window per (station,
    cycle): a cycle can publish more than one complete 00Z daily-max valid
    window, and which one is the D+1 trading target is an EXPLICIT
    decision made downstream, by :func:`build_version_rows` -- SL-8b
    review item 1 (the prior "nearest ``valid_start_ns``" reduction here
    relied on an undeclared assumption about the venue's publication grid
    rather than on an explicit check; see that function's docstring).
    """
    by_group: dict[tuple[str, int, int], dict[str, DerivedNbpRow]] = {}
    for row in rows:
        if row.variable not in TXN_VARIABLES:
            continue
        key = (row.station, row.cycle_runtime_ns, row.valid_start_ns)
        by_group.setdefault(key, {})[row.variable] = row

    incomplete = 0
    windows: list[NbpPercentileWindow] = []
    for (station, cycle_runtime_ns, valid_start_ns), variables in by_group.items():
        complete = set(variables) == set(TXN_VARIABLES) and all(
            entry.value_f is not None for entry in variables.values()
        )
        if not complete:
            incomplete += 1
            continue
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

    if counts is not None:
        counts.incomplete_windows += incomplete
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
    #: (station, cycle_runtime_ns) groups with no COMPLETE window mapping to
    #: the explicit D+1 target climate day (SL-8b review item 1) -- counted,
    #: never filled in from whatever window happens to be nearest.
    no_d1_window_cycles: int
    holdout_excluded_windows: int
    missing_settlement_rows: int
    matched_version_rows: int
    n_by_split: Mapping[str, int]
    n_by_version: Mapping[str, int]
    mos_txn_populated_rows_by_station: Mapping[str, int]
    asos_1min_rows_by_station: Mapping[str, int]


def _select_d1_window(
    group_windows: Sequence[NbpPercentileWindow],
    *,
    station: str,
    cycle_runtime_ns: int,
    offset: float,
    target_day: dt.date,
    gaps: Counter[str],
) -> NbpPercentileWindow | None:
    """The ONE shared explicit-D+1 selector (SL-8b review item 1). Reused by
    BOTH `build_version_rows` and `build_comparator_matched_events` (SL-8c
    rebase DRY directive, 2026-09-29) -- there is exactly one selector in
    this module, never two independently-maintained copies. Returns the
    window in ``group_windows`` whose own `climate_day_for_txn` (kind="max")
    equals ``target_day``, or ``None`` if none does -- counting
    ``period_kind_mismatch`` per non-matching window that raises
    `ForecastValidPeriodError`, and ``no_d1_window`` once if nothing in the
    group matches. Never falls back to "nearest"."""
    for window in group_windows:
        try:
            window_climate_day = climate_day_for_txn(
                icao=station,
                runtime_ns=cycle_runtime_ns,
                ftime_ns=window.valid_start_ns,
                std_utc_offset_hours=offset,
                model=window.nbm_version_era,
                kind="max",
            )
        except ForecastValidPeriodError:
            gaps["period_kind_mismatch"] += 1
            continue
        if window_climate_day == target_day:
            return window
    gaps["no_d1_window"] += 1
    return None


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
    ``no_d1_window``, ``holdout_excluded``, ``missing_settlement``. Every
    row this function KEEPS maps to the EXPLICIT D+1 climate day and is
    strictly before ``splits.holdout_start`` -- checked TWICE (before the
    settlement lookup, and again against `Splits.split_for_date`'s own
    classification) so a holdout-dated row can never reach the returned
    tuple by either path.

    **Explicit D+1 window selection (SL-8b review item 1; corrected against
    the real NBP grid, coordinator note 2026-09-29).** A (station,
    cycle_runtime_ns) group may carry more than one complete window (the
    venue can publish several 00Z daily-max valid times per cycle). The ONE
    this join uses is the window whose own climate day (via
    `climate_day_for_txn`, kind="max") equals the cycle's explicit D+1
    target, ``local_standard_date(cycle_runtime_ns, std_utc_offset_hours) +
    1 day`` (`breezy.ingest.gaps.local_standard_date` -- the SAME helper
    the strategy's own D+1 gate uses), rather than whichever window happens
    to be temporally nearest. A group with no window at that exact target
    is counted (``no_d1_window``), never substituted.

    **On the real NBP bulletin grid this selects the SAME window "nearest
    available" already did.** The venue never publishes a same-LST-day MAX
    column: for a 13Z cycle the first MAX (00Z) column is FHR 35 (the
    grid's first group, FHR 23, carries only the 12Z/MIN sub-value); for
    19Z it is FHR 29; for 01Z the first group already carries both 00Z and
    12Z. All three land on the D+1 target directly --
    `tests/unit/test_nbm_quantile_parse.py` hand-verifies this against the
    real captured bulletins (`test_hand_computed_dplus1_lst_day_per_
    station_per_cycle`), and `tests/unit/test_nbp_skill_study.py`
    independently re-confirms it against the real on-disk backfill (zero
    mismatches across every real (station, cycle) group checked). The
    explicit check is a robustness improvement, not a fix to an observed
    real-data defect: it refuses (rather than silently accepting) a window
    at the wrong day should a malformed partition or a future grid change
    ever produce one.

    Worked example (KLAX/KMDW/KMIA/KSFO, std_utc_offset_hours -8/-6/-5/-8
    respectively; all four offsets keep 13Z/19Z/01Z within a single
    day-shift regime, so the target is IDENTICAL across every station for a
    given cycle):

    * 13Z or 19Z cycle published on UTC day D: LST publish date is ALSO D
      (13 or 19 minus each offset, at most 8h, stays >= 0 on day D) -- so
      the D+1 target climate day is D+1, reached by the 00Z window whose
      OWN UTC calendar day is D+2 (``local_standard_date`` of a 00Z instant
      is always the PRECEDING UTC day for these negative offsets). This IS
      the real grid's first available MAX column (FHR 35/29 respectively).
    * 01Z cycle published on UTC day X (01:00 UTC): LST publish date is X-1
      (01 minus each offset falls on the PRECEDING UTC day) -- so the D+1
      target climate day is X, reached by the 00Z window whose own UTC
      calendar day is X+1 -- also the real grid's first available MAX
      column (FHR 23) here.
    """
    windows_by_cycle: dict[tuple[str, int], list[NbpPercentileWindow]] = {}
    for window in windows:
        windows_by_cycle.setdefault((window.station, window.cycle_runtime_ns), []).append(window)

    gaps: Counter[str] = Counter()
    version_rows: list[VersionRow] = []
    for (station, cycle_runtime_ns), group_windows in windows_by_cycle.items():
        if _cycle_hour(cycle_runtime_ns) not in QUALIFYING_CYCLE_HOURS:
            gaps["non_qualifying_cycle"] += 1
            continue
        offset = registry.std_utc_offset_hours_by_icao.get(station)
        settlement_station = registry.settlement_station_by_icao.get(station)
        if offset is None or settlement_station is None:
            gaps["unmapped_station"] += 1
            continue

        target_climate_day = local_standard_date(cycle_runtime_ns, offset) + dt.timedelta(days=1)

        chosen = _select_d1_window(
            group_windows,
            station=station,
            cycle_runtime_ns=cycle_runtime_ns,
            offset=offset,
            target_day=target_climate_day,
            gaps=gaps,
        )
        if chosen is None:
            continue

        climate_day = target_climate_day
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
                version=chosen.nbm_version_era,
                split=split,
                station=settlement_station,
                climate_day=climate_day,
                percentiles=chosen.percentiles,
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
# SL-8c: M0/M1 comparator models + G2.0a real-data wiring.
#
# Originally built as new functions only, alongside the (then still
# "nearest window") `build_version_rows`. Rebased 2026-09-29 onto the SL-8b
# review fix that made `build_version_rows` select explicitly via
# `climate_day_for_txn`: `build_comparator_matched_events` below now shares
# that SAME `_select_d1_window` selector (DRY -- one selector, not two).
# Every event this section builds is still keyed on
# `nbp_comparator_models.target_climate_day(cycle_runtime_ns, offset)` --
# the D+1 day derived from the cycle's OWN publish instant -- never from a
# percentile window's `valid_start_ns` alone.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RawMosTxnXnd:
    """One (station, cycle) forecast's raw NBS TXN + XND, read straight off
    the MOS CSV (SL-8c tasks 1/2). ``xnd_f`` is ``None`` when the column was
    empty or non-numeric for every candidate row -- never imputed."""

    txn_f: float
    xnd_f: float | None


_MOS_INSTANT_FORMATS: Final[tuple[str, ...]] = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%MZ",
    "%Y-%m-%d",
)


def _parse_mos_instant(value: str) -> dt.datetime | None:
    stripped = value.strip()
    if not stripped:
        return None
    for fmt in _MOS_INSTANT_FORMATS:
        try:
            return dt.datetime.strptime(stripped, fmt).replace(tzinfo=dt.UTC)
        except ValueError:
            continue
    return None


def _mos_row_txn_xnd(row: MosTxnRow) -> tuple[float, float | None] | None:
    if not row.txn_present:
        return None
    try:
        txn_f = float(row.txn)
    except ValueError:
        return None
    try:
        xnd_f: float | None = float(row.xnd)
    except ValueError:
        xnd_f = None
    return txn_f, xnd_f


def mos_txn_xnd_by_cycle(
    *,
    archive_root: Path,
    registry: StationRegistry,
    stations: Sequence[str] = _JOIN_STATIONS,
    model: str = "NBS",
) -> dict[tuple[str, int], RawMosTxnXnd]:
    """Real NBS TXN + XND per ``(station, cycle_runtime_ns)`` (SL-8c tasks
    1/2), read-only from the on-disk IEM MOS archive cache -- never fetches.

    **Row selection (coordinator review 2026-09-29, CRITICAL fix).** For a
    cycle with multiple candidate ftime rows carrying a populated ``txn``,
    the SELECTED row is the one whose
    `forecast_climate_day_map.climate_day_for_txn(..., kind="max")` equals
    that cycle's own :func:`~breezy.analysis.nbp_comparator_models
    .target_climate_day` -- verified explicitly, never assumed correct by
    proximity alone. **Measured against the real on-disk archive (full
    scan, all 4 stations):** the real MOS grid never publishes a
    same-cycle-day 00Z ``txn`` row for a 13Z/19Z cycle -- the shortest
    available MAX lead is 35h (13Z) / 29h (19Z) / 23h (01Z), and that FIRST
    available MAX column already IS the correct D+1 target at every station
    and cycle hour checked. The NEXT real MAX column (24h later) maps to
    D+2 and must be rejected -- this function's explicit check is what
    guarantees that rejection; it does not depend on "nearest" happening to
    be right. A cycle with no candidate row mapping to its own target day is
    simply ABSENT from the returned dict -- never approximated.
    """
    cache = _read_only_archive_cache(IEM_MOS_SOURCE, archive_root=archive_root)
    product = IEM_MOS_MODEL_PRODUCTS[model]
    wanted = frozenset(stations)
    candidates: dict[tuple[str, int], list[tuple[int, RawMosTxnXnd]]] = {}
    for entry in cache.entries(IEM_MOS_SOURCE):
        if entry.station not in wanted or entry.product != product:
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
        for row in parse_mos_txn_rows(body.decode("utf-8", errors="replace")):
            parsed = _mos_row_txn_xnd(row)
            if parsed is None:
                continue
            runtime = _parse_mos_instant(row.runtime)
            ftime = _parse_mos_instant(row.ftime)
            if runtime is None or ftime is None or ftime < runtime:
                continue
            runtime_ns = int(runtime.timestamp()) * _NS_PER_SECOND
            ftime_ns = int(ftime.timestamp()) * _NS_PER_SECOND
            candidates.setdefault((entry.station, runtime_ns), []).append(
                (ftime_ns, RawMosTxnXnd(txn_f=parsed[0], xnd_f=parsed[1]))
            )

    result: dict[tuple[str, int], RawMosTxnXnd] = {}
    for (station, runtime_ns), rows in candidates.items():
        offset = registry.std_utc_offset_hours_by_icao.get(station)
        if offset is None:
            continue
        target = target_climate_day(runtime_ns, offset)
        for ftime_ns, raw in sorted(rows, key=lambda pair: pair[0]):
            try:
                mapped_day = climate_day_for_txn(
                    icao=station,
                    runtime_ns=runtime_ns,
                    ftime_ns=ftime_ns,
                    std_utc_offset_hours=offset,
                    model=model,
                    kind="max",
                )
            except ForecastValidPeriodError:
                continue
            if mapped_day == target:
                result[(station, runtime_ns)] = raw
                break
    return result


class AsosRowOrderError(RuntimeError):
    """A raw IEM ASOS 1-minute payload's rows are not chronologically
    ordered -- `daily_max_instants`'s tie-break-to-first-occurrence
    convention depends on file order, so an out-of-order row fails loudly
    rather than silently trusting or re-sorting it (coordinator review
    2026-09-29)."""


def daily_max_instants(
    *, archive_root: Path, registry: StationRegistry, stations: Sequence[str] = _JOIN_STATIONS
) -> dict[tuple[str, dt.date], DailyMaxInstant]:
    """Real G2.0a daily-max LST instant per ``(settlement_station,
    climate_day)`` (SL-8c task 3), read-only from the on-disk IEM ASOS
    1-minute archive cache. ONE station-year entry is read and reduced to
    its per-day maxima at a time -- bounded memory, mirroring
    ``forecast_conditional_corpus.observations_from_asos_payload``'s own
    streamed-reduce-then-drop shape. A station-day with no samples is simply
    ABSENT from the returned mapping -- never imputed. Ties are resolved to
    the FIRST occurrence: a strict ``>`` comparison never lets a later,
    equal reading win, PROVIDED the stream is chronological -- which is
    checked, not assumed (coordinator review 2026-09-29, MEDIUM fix): each
    row's ``valid(UTC)`` is asserted non-decreasing against the previous row
    of the SAME entry as it streams, and :class:`AsosRowOrderError` is
    raised immediately (never silently reordered or skipped) the first time
    that fails, rather than sorting the whole entry into memory up front.
    """
    cache = _read_only_archive_cache(IEM_ASOS_1MIN_SOURCE, archive_root=archive_root)
    wanted = frozenset(stations)
    result: dict[tuple[str, dt.date], DailyMaxInstant] = {}
    for entry in cache.entries(IEM_ASOS_1MIN_SOURCE):
        if entry.station not in wanted:
            continue
        settlement_station = registry.settlement_station_by_icao.get(entry.station)
        offset = registry.std_utc_offset_hours_by_icao.get(entry.station)
        if settlement_station is None or offset is None:
            continue
        request = ArchiveRequest(
            source=IEM_ASOS_1MIN_SOURCE,
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
        running: dict[dt.date, tuple[int, float]] = {}
        last_when: dt.datetime | None = None
        stream = io.TextIOWrapper(io.BytesIO(body), encoding="utf-8", newline="")
        reader = csv.reader(stream)
        try:
            header = next(reader)
            i_valid = header.index("valid(UTC)")
            i_temp = header.index("tmpf")
        except (StopIteration, ValueError):
            continue
        for raw_row in reader:
            if len(raw_row) <= max(i_valid, i_temp):
                continue
            raw_temp = raw_row[i_temp].strip()
            if not raw_temp or raw_temp == "M":
                continue
            try:
                when = dt.datetime.strptime(
                    raw_row[i_valid], "%Y-%m-%d %H:%M"
                ).replace(tzinfo=dt.UTC)
                value = float(raw_temp)
            except ValueError:
                continue
            if last_when is not None and when < last_when:
                raise AsosRowOrderError(
                    f"{entry.station} {entry.window_start}: ASOS 1-minute row out of "
                    f"chronological order ({when.isoformat()} after "
                    f"{last_when.isoformat()}) -- the tie-break-to-first-occurrence "
                    "convention requires a chronological stream; refusing rather than "
                    "silently accepting an unordered file"
                )
            last_when = when
            climate_day, seconds = lst_clock_time(when, std_utc_offset_hours=offset)
            if value > running.get(climate_day, (0, -999.0))[1]:
                running[climate_day] = (seconds, value)
        for climate_day, (seconds, value) in running.items():
            result[(settlement_station, climate_day)] = DailyMaxInstant(
                station=settlement_station,
                climate_day=climate_day,
                lst_seconds_from_midnight=seconds,
                value_f=value,
                near_midnight=is_near_lst_midnight(seconds),
            )
    return result


def _forecast_centered_ladder(center_f: int) -> tuple[Rung, ...]:
    """A minimal 3-rung complete partition (plan S3.2 item 7): one 2 degF
    interior rung ``[center, center+1]`` flanked by open tails, centered on
    a FORECAST value -- never the settled outcome, which would leak the
    outcome into rung selection. Every model in one matched event scores the
    SAME ladder."""
    return (
        Rung("lt", None, center_f - 1),
        Rung("mid", center_f, center_f + 1),
        Rung("gte", center_f + 2, None),
    )


@dataclass(frozen=True, slots=True)
class ComparatorMatchedEvent:
    """One D+1 rung event, scored under M0, M1 and M2 on the SAME rung
    (SL-8c task 4). ``p_m2`` this slice is the NBP percentile bulletin's own
    NORMAL(q50, sd) CDF, uncalibrated -- the hierarchical EMOS fit
    (`breezy.analysis.nbp_calibration.fit_calibration`) is a later slice's
    wiring; this keeps the three models comparable on one event now without
    pre-empting that fit's own method choice (plan S9 Q1, still open)."""

    station: str
    climate_day: dt.date
    split: str
    p_m0: float
    p_m1: float
    p_m2: float
    outcome: bool
    near_midnight: bool | None
    near_midnight_stratum: str | None


@dataclass(frozen=True, slots=True)
class ComparatorJoinReport:
    windows_considered: int
    non_qualifying_cycle_windows: int
    unmapped_station_windows: int
    period_kind_mismatch_windows: int
    no_d1_window_cycles: int
    holdout_excluded_windows: int
    missing_settlement_rows: int
    missing_raw_mos_rows: int
    matched_events: int
    n_by_split: Mapping[str, int]


_NEAR_MIDNIGHT_STRATUM_OF_ICAO: Final[dict[str, str]] = {
    icao: stratum for stratum, members in NEAR_MIDNIGHT_STRATA.items() for icao in members
}


def build_comparator_matched_events(
    windows: Sequence[NbpPercentileWindow],
    settlement_by_station_day: Mapping[tuple[str, dt.date], SettlementTruthRow],
    mos_by_cycle: Mapping[tuple[str, int], RawMosTxnXnd],
    daily_max_by_station_day: Mapping[tuple[str, dt.date], DailyMaxInstant],
    frozen_0b_model: ForecastErrorModel,
    *,
    registry: StationRegistry,
    splits: Splits = DEFAULT_SPLITS,
) -> tuple[tuple[ComparatorMatchedEvent, ...], ComparatorJoinReport]:
    """SL-8c task 4: per-event M0/M1/M2 probabilities + the G2.0a stratum
    label, on the SAME matched events. Never opens the holdout -- every
    event's ``climate_day`` is checked against ``splits.holdout_start``
    exactly like `build_version_rows`.

    **Explicit D+1 window selection, shared with `build_version_rows`
    (SL-8c rebase DRY directive, 2026-09-29).** ``windows`` is grouped by
    (station, cycle_runtime_ns) exactly like `build_version_rows`, and the
    SAME `_select_d1_window` helper picks the one window per group whose own
    `climate_day_for_txn` (kind="max") equals the cycle's explicit D+1
    target -- never "whichever window happens to be in the list". There is
    one selector in this module, not two.
    """
    windows_by_cycle: dict[tuple[str, int], list[NbpPercentileWindow]] = {}
    for window in windows:
        windows_by_cycle.setdefault((window.station, window.cycle_runtime_ns), []).append(window)

    gaps: Counter[str] = Counter()
    events: list[ComparatorMatchedEvent] = []
    for (station, cycle_runtime_ns), group_windows in windows_by_cycle.items():
        if _cycle_hour(cycle_runtime_ns) not in QUALIFYING_CYCLE_HOURS:
            gaps["non_qualifying_cycle"] += 1
            continue
        offset = registry.std_utc_offset_hours_by_icao.get(station)
        settlement_station = registry.settlement_station_by_icao.get(station)
        if offset is None or settlement_station is None:
            gaps["unmapped_station"] += 1
            continue

        climate_day = target_climate_day(cycle_runtime_ns, offset)

        chosen = _select_d1_window(
            group_windows,
            station=station,
            cycle_runtime_ns=cycle_runtime_ns,
            offset=offset,
            target_day=climate_day,
            gaps=gaps,
        )
        if chosen is None:
            continue

        if climate_day >= splits.holdout_start:
            gaps["holdout_excluded"] += 1
            continue

        settlement_row = settlement_by_station_day.get((settlement_station, climate_day))
        if settlement_row is None or settlement_row.tmax_f is None:
            gaps["missing_settlement"] += 1
            continue

        split = splits.split_for_date(climate_day)
        if split == "holdout":  # pragma: no cover - defense in depth, unreachable above
            gaps["holdout_excluded"] += 1
            continue

        raw_mos = mos_by_cycle.get((station, cycle_runtime_ns))
        if raw_mos is None or raw_mos.xnd_f is None or raw_mos.xnd_f <= 0.0:
            gaps["missing_raw_mos"] += 1
            continue

        center_f = round(chosen.percentiles.q50)
        ladder = _forecast_centered_ladder(center_f)

        p_m0 = m0_rung_probabilities(
            txn_f=raw_mos.txn_f,
            station=settlement_station,
            climate_day=climate_day,
            horizon_hours=M0_PRIMARY_LEAD_HOURS,
            error_model=frozen_0b_model,
            rungs=ladder,
        )["mid"]
        p_m1 = m1_rung_probabilities(
            txn_mean_f=raw_mos.txn_f, xnd_sd_f=raw_mos.xnd_f, rungs=ladder
        )["mid"]
        # M2, this slice: the NBP percentile bulletin's own CDF, uncalibrated
        # (see ComparatorMatchedEvent's docstring).
        p_m2 = rung_probabilities(build_cdf(CdfMethod.NORMAL, chosen.percentiles), ladder)["mid"]

        outcome = int(settlement_row.tmax_f) in (center_f, center_f + 1)
        instant = daily_max_by_station_day.get((settlement_station, climate_day))
        stratum = _NEAR_MIDNIGHT_STRATUM_OF_ICAO.get(station)

        events.append(
            ComparatorMatchedEvent(
                station=settlement_station,
                climate_day=climate_day,
                split=split,
                p_m0=p_m0,
                p_m1=p_m1,
                p_m2=p_m2,
                outcome=outcome,
                near_midnight=None if instant is None else instant.near_midnight,
                near_midnight_stratum=(
                    stratum if (instant is not None and instant.near_midnight) else None
                ),
            )
        )

    n_by_split: Counter[str] = Counter(event.split for event in events)
    report = ComparatorJoinReport(
        windows_considered=len(windows),
        non_qualifying_cycle_windows=gaps.get("non_qualifying_cycle", 0),
        unmapped_station_windows=gaps.get("unmapped_station", 0),
        period_kind_mismatch_windows=gaps.get("period_kind_mismatch", 0),
        no_d1_window_cycles=gaps.get("no_d1_window", 0),
        holdout_excluded_windows=gaps.get("holdout_excluded", 0),
        missing_settlement_rows=gaps.get("missing_settlement", 0),
        missing_raw_mos_rows=gaps.get("missing_raw_mos", 0),
        matched_events=len(events),
        n_by_split=dict(n_by_split),
    )
    return tuple(events), report


def run_comparator_validate(
    *,
    nbp_derived_root: Path,
    settlement_truth_parquet: Path,
    archive_root: Path,
    frozen_0b_artefact_path: Path | None = None,
    splits: Splits = DEFAULT_SPLITS,
) -> tuple[tuple[ComparatorMatchedEvent, ...], ComparatorJoinReport]:
    """SL-8c task 4 entry point: wires M0, M1, M2 and the G2.0a stratum
    label into ONE real-data pass over the SAME sources `run_validate` reads
    (never the holdout). Kept SEPARATE from `run_validate` itself
    (coordinator directive) -- `main()` calls both."""
    registry = station_registry()
    resolved_frozen_path = (
        frozen_0b_artefact_path
        if frozen_0b_artefact_path is not None
        else _REPO_ROOT / FROZEN_0B_ARTEFACT_RELPATH
    )
    frozen_0b_model = load_frozen_0b_error_model(resolved_frozen_path)

    settlement_rows = read_settlement_truth_rows(
        settlement_truth_parquet, climate_day_before=splits.holdout_start
    )
    settlement_by_station_day = _settlement_lookup(settlement_rows, holdout_start=splits.holdout_start)

    all_windows: list[NbpPercentileWindow] = []
    for _path, rows in iter_nbp_derived_rows(nbp_derived_root):
        if rows is None:
            continue
        all_windows.extend(complete_percentile_windows(rows))

    mos_by_cycle = mos_txn_xnd_by_cycle(archive_root=archive_root, registry=registry)
    daily_max_by_station_day = daily_max_instants(archive_root=archive_root, registry=registry)

    return build_comparator_matched_events(
        all_windows,
        settlement_by_station_day,
        mos_by_cycle,
        daily_max_by_station_day,
        frozen_0b_model,
        registry=registry,
        splits=splits,
    )


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
        all_windows.extend(complete_percentile_windows(rows, counts=counts))

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
        no_d1_window_cycles=gaps.get("no_d1_window", 0),
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
        "no_d1_window_cycles": report.no_d1_window_cycles,
        "holdout_excluded_windows": report.holdout_excluded_windows,
        "missing_settlement_rows": report.missing_settlement_rows,
        "matched_version_rows": report.matched_version_rows,
        "n_by_split": dict(sorted(report.n_by_split.items())),
        "n_by_version": dict(sorted(report.n_by_version.items())),
        "mos_txn_populated_rows_by_station": dict(sorted(report.mos_txn_populated_rows_by_station.items())),
        "asos_1min_rows_by_station": dict(sorted(report.asos_1min_rows_by_station.items())),
    }


def _comparator_report_to_json_dict(report: ComparatorJoinReport) -> dict[str, object]:
    return {
        "windows_considered": report.windows_considered,
        "non_qualifying_cycle_windows": report.non_qualifying_cycle_windows,
        "unmapped_station_windows": report.unmapped_station_windows,
        "period_kind_mismatch_windows": report.period_kind_mismatch_windows,
        "no_d1_window_cycles": report.no_d1_window_cycles,
        "holdout_excluded_windows": report.holdout_excluded_windows,
        "missing_settlement_rows": report.missing_settlement_rows,
        "missing_raw_mos_rows": report.missing_raw_mos_rows,
        "matched_events": report.matched_events,
        "n_by_split": dict(sorted(report.n_by_split.items())),
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
    if args.comparator_models:
        # Opt-in: `daily_max_instants` fully parses the ASOS 1-minute
        # archive (~367MB / 9.0M rows) rather than reading manifest row
        # counts only, unlike every OTHER function `main()` calls by
        # default -- so this stays off the default fast path (SL-8c).
        _comparator_events, comparator_report = run_comparator_validate(
            nbp_derived_root=args.nbp_derived_root,
            settlement_truth_parquet=settlement_truth_parquet,
            archive_root=args.archive_root,
        )
        payload["comparator_models"] = _comparator_report_to_json_dict(comparator_report)
    print(f"nbp_skill_study: stage=validate splits={DEFAULT_SPLITS!r}")
    print(json.dumps(payload, indent=2, sort_keys=True))
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
