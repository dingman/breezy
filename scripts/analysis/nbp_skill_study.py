#!/usr/bin/env python
"""CLI: NBP weather-only skill study (SL-8/SL-8b; plan
`FORECAST_NBP_PROBABILISTIC_FAMILY_Rev3_2026-09-29.md` S7 row SL-8, S2).

Wires `breezy.analysis.nbp_calibration`'s pure gate machinery to real data:
NBP rows from `breezy.persistence.nbp_derived_store`, final-only CLI labels
via `settlement_truth_dataset.final_rows_for_gate`, and (for M0/M1
coverage/G2.0a) the on-disk, read-only IEM MOS NBS and IEM ASOS 1-minute
archive caches. It runs the validation-stage real-data JOIN and reports
coverage by default. With explicit ``--run-gates`` on ``--stage validate``
it fits the existing hierarchical EMOS calibration, scores calibrated M2 on
validate events only, evaluates G2.0/G2.0a/G2.1/G2.2/G2.3, writes a JSON
result, writes a generated evidence note, and writes a sha-pinned candidate
artefact outside the repo only when the fit converges.

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
import json
import math
import statistics
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final, TypedDict

_SCRIPTS_ANALYSIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPTS_ANALYSIS_DIR.parents[1]
for _entry in (str(_SCRIPTS_ANALYSIS_DIR), str(_REPO_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from forecast_climate_day_map import ForecastValidPeriodError, climate_day_for_txn  # type: ignore[import-not-found]  # noqa: E402
from mos_txn_occupancy import MosTxnRow, parse_mos_txn_rows  # type: ignore[import-not-found]  # noqa: E402
from settlement_alignment_study import IEM_ASOS_IDS, VENUE, load_sites  # type: ignore[import-not-found]  # noqa: E402
from settlement_truth_dataset import SettlementTruthRow, final_rows_for_gate  # type: ignore[import-not-found]  # noqa: E402

from breezy.analysis.nbp_calibration import (  # noqa: E402
    BOOTSTRAP_SEED,
    DEFAULT_SPLITS,
    DEFAULT_BOOTSTRAP_DRAWS,
    FIT_STATUS_NOT_CONVERGED,
    FIT_STATUS_OK,
    NEAR_MIDNIGHT_STRATA,
    N_MIN_CEILING,
    CalibrationFit,
    CorrectionFitRow,
    CorrectionForm,
    CorrectionSelection,
    FitNotConvergedError,
    G20Result,
    G20aResult,
    G21Result,
    G23Result,
    MatchedEvent,
    ProbabilityRecalibrationForm,
    ProbabilityRecalibrationSelection,
    RecalibrationFitEvent,
    RungEvent,
    SkillGateResult,
    Splits,
    StationDayResidual,
    VersionRow,
    apply_probability_recalibration,
    apply_selected_correction,
    artefact_from_calibration_fit,
    cluster_bootstrap_draws,
    compute_n_min,
    evaluate_g20_and_g20a_combined,
    evaluate_g21,
    evaluate_g22,
    evaluate_g23,
    fit_calibration,
    percentile_interval,
    select_correction_form,
    select_probability_recalibration,
    shrinkage_weight,
    write_artefact,
)
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
from breezy.registry.sites import default_registry  # noqa: E402
from breezy.strategy.ladder_ev.location_correction import daylight_hours
from breezy.strategy.ladder_ev.quantile_density import (  # noqa: E402
    CdfMethod,
    EmosParams,
    Percentiles,
    Rung,
    apply_emos,
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
    "calibrated_m2_rung_probabilities",
    "complete_percentile_windows",
    "daily_max_instants",
    "iter_nbp_derived_rows",
    "main",
    "mos_txn_coverage",
    "mos_txn_xnd_by_cycle",
    "asos_1min_row_coverage",
    "read_settlement_truth_rows",
    "run_comparator_validate",
    "run_validate_gates_from_rows",
    "run_validate",
    "station_registry",
    "validate_gate_events_from_comparator_events",
    "write_validate_evidence_note",
]

_HOLDOUT_GUARD_FLAG: str = "--coordinator-authorized"

DEFAULT_NBP_DERIVED_ROOT: Final[Path] = Path.home() / ".local/share/breezy/derived/nbp"
DEFAULT_SETTLEMENT_TRUTH_PARQUET: Final[Path] = (
    Path.home() / ".local/share/breezy/derived/settlement-truth/settlement_truth.parquet"
)
DEFAULT_ARCHIVE_ROOT: Final[Path] = Path.home() / ".local/share/breezy/archive"
DEFAULT_CALIBRATION_ARTEFACT_DIR: Final[Path] = (
    Path.home() / ".local/share/breezy/derived/nbp_calibration"
)
DEFAULT_VALIDATE_EVIDENCE_DIR: Final[Path] = _REPO_ROOT / "docs/evidence"


class _GroupJson(TypedDict):
    key: str
    status: str
    n: int
    n_dates: int
    mean_residual_f: float | None
    p_value: float | None
    holm_rejected: bool | None
    bootstrap_degenerate: bool | None


class _BucketJson(TypedDict):
    lower: float
    upper: float
    n: int
    predicted: float
    observed: float
    z: float
    p_value: float
    holm_rejected: bool
    bootstrap_degenerate: bool


class _GateJson(TypedDict):
    status: str
    n: int
    statistics: dict[str, object]
    cis: dict[str, object]


class _G20GateJson(_GateJson):
    groups: list[_GroupJson]


class _G21GateJson(_GateJson):
    buckets: list[_BucketJson]


class _KappaCurveJson(TypedDict):
    kappa: float
    mean_crps: float


class _CoverageCountsJson(TypedDict):
    fit_rows: int
    train_fit_rows: int
    validate_version_rows: int
    validate_comparator_events: int
    holdout_version_rows_filtered: int
    holdout_comparator_events_filtered: int
    gate_climate_day_min: str | None
    gate_climate_day_max: str | None


class _ConvergenceJson(TypedDict, total=False):
    delta_converged: bool
    delta_nfev: int
    converged_by_version: dict[str, bool]
    nfev_by_version: dict[str, int]


class _ArtefactJson(TypedDict):
    path: str | None
    sha256: str | None


class _PowerJson(TypedDict):
    """S2 power metadata (plan S4.1; SL-8d review item 4): the
    validation-split estimate of sigma_d, the n_min it implies, and whether
    that n_min is reachable (:data:`breezy.analysis.nbp_calibration
    .N_MIN_CEILING`)."""

    sigma_d: float
    sigma_d_ci: list[float]
    n_min: int
    n_min_range: list[int]
    status: str
    n_min_range_status: str


class _CorrectionJson(TypedDict):
    form: str
    validation_crps: dict[str, float]
    month_offsets: dict[str, float]
    linear_coefficients: list[float] | None


class _RecalibrationJson(TypedDict):
    form: str
    validation_brier: dict[str, float]
    affine: list[float] | None
    isotonic_points: list[list[float]]


class ValidateGatePayload(TypedDict):
    label: str
    stage: str
    fit_status: str
    kappa_chosen: float
    kappa_curve: list[_KappaCurveJson]
    convergence: _ConvergenceJson
    coverage_counts: _CoverageCountsJson
    gates: dict[str, _GateJson]
    artefact: _ArtefactJson
    power: _PowerJson
    shrinkage_weights: dict[str, float]
    pooling: str
    effective_params_source: dict[str, str]
    in_sample_versions: list[str]
    fit_provenance: dict[str, dict[str, dict[str, object]]]
    correction: _CorrectionJson
    recalibration: _RecalibrationJson

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
    parser.add_argument(
        "--run-gates",
        action="store_true",
        default=False,
        help="Validate stage only: fit the hierarchical EMOS calibration, score "
        "calibrated M2, evaluate G2.0/G2.0a/G2.1/G2.2/G2.3 on validate rows, "
        "write the candidate artefact outside the repo if converged, and write "
        "the generated validate evidence note.",
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
    #: F13 FB-R5: the MAX of the group's `DerivedNbpRow.available_at_ns` (the window is public
    #: only when its last variable is). Set by :func:`complete_percentile_windows`; ``None`` for
    #: a window built by hand, which a point-in-time consumer must refuse.
    available_at_ns: int | None = None


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
                available_at_ns=max(entry.available_at_ns for entry in variables.values()),
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
    (SL-8c task 4). ``version``/``percentiles``/``rung_id`` are carried so
    SL-8d can replace the old uncalibrated M2 placeholder with calibrated
    hierarchical-EMOS probabilities on the exact same event key."""

    station: str
    climate_day: dt.date
    split: str
    version: str
    percentiles: Percentiles
    rung_id: str
    p_m0: float
    p_m1: float
    p_m2: float
    cli_tmax_f: float
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
        # M2 placeholder retained only for coverage/comparator shape when no
        # calibration fit is available; SL-8d gate scoring overwrites this via
        # `validate_gate_events_from_comparator_events`.
        p_m2 = rung_probabilities(build_cdf(CdfMethod.NORMAL, chosen.percentiles), ladder)["mid"]

        outcome = int(settlement_row.tmax_f) in (center_f, center_f + 1)
        instant = daily_max_by_station_day.get((settlement_station, climate_day))
        stratum = _NEAR_MIDNIGHT_STRATUM_OF_ICAO.get(station)

        events.append(
            ComparatorMatchedEvent(
                station=settlement_station,
                climate_day=climate_day,
                split=split,
                version=chosen.nbm_version_era,
                percentiles=chosen.percentiles,
                rung_id="mid",
                p_m0=p_m0,
                p_m1=p_m1,
                p_m2=p_m2,
                cli_tmax_f=float(settlement_row.tmax_f),
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
# SL-8d: validate-stage calibrated M2 + gates.
# ---------------------------------------------------------------------------


class UnknownStationError(ValueError):
    """`_daylight_hours` was asked for a station the registry does not know
    (SL-8d review item 5) -- never silently defaulted to a placeholder
    latitude."""


@lru_cache(maxsize=1)
def _station_latitudes() -> Mapping[str, float]:
    """Every polymarket_us station's latitude, keyed by BOTH its ICAO and
    its short settlement code (e.g. ``KMIA`` and ``MIA``), read from the
    SAME registry every other lookup in this module uses
    (`breezy.registry.sites`/``sites.toml``) -- never a second,
    hand-maintained copy (SL-8d review item 5). Cached: the registry is
    immutable for the process lifetime.
    """
    registry = default_registry()
    latitudes: dict[str, float] = {}
    for spec in load_sites():
        coordinates = registry.enrichment_coordinates(VENUE, spec.city)
        latitudes[spec.site.icao] = coordinates.lat
        latitudes[spec.iem_asos_id] = coordinates.lat
    return latitudes


def _daylight_hours(station: str, day: dt.date) -> float:
    """Approximate astronomical daylight hours for G2.0 tercile grouping.

    The latitude comes from `src/breezy/registry/sites.toml` via
    :func:`_station_latitudes` -- an unknown station raises
    :class:`UnknownStationError` rather than silently falling back to a
    placeholder latitude (SL-8d review item 5); the gate only needs a
    stable day-length ordering for train-derived tercile edges, never an
    unverified guess for a station it does not recognise.
    """
    try:
        latitude_deg = _station_latitudes()[station]
    except KeyError as exc:
        raise UnknownStationError(
            f"unknown station {station!r}: no latitude registered in sites.toml"
        ) from exc
    return daylight_hours(latitude_deg, day)


def _tercile_edges(values: Sequence[float]) -> tuple[float, float]:
    if len(values) < 3:
        return (10.0, 14.0)
    ordered = sorted(values)
    return (ordered[len(ordered) // 3], ordered[(2 * len(ordered)) // 3])


def _fit_status_from_calibration(fit: CalibrationFit) -> str:
    if not fit.delta_converged:
        return FIT_STATUS_NOT_CONVERGED
    if any(not estimate.converged for estimate in fit.hierarchical.shrunk_by_version.values()):
        return FIT_STATUS_NOT_CONVERGED
    return FIT_STATUS_OK


def _emos_params_for_version(*, version: str, calibration_fit: CalibrationFit) -> EmosParams:
    estimate = calibration_fit.hierarchical.shrunk_by_version[version]
    return EmosParams(a=estimate.a, gamma=estimate.gamma, delta=calibration_fit.delta)


def calibrated_m2_rung_probabilities(
    *,
    percentiles: Percentiles,
    version: str,
    calibration_fit: CalibrationFit,
    rungs: Sequence[Rung],
    cdf_method: CdfMethod,
    correction_f: float = 0.0,
    recalibration: ProbabilityRecalibrationSelection | None = None,
) -> dict[str, float]:
    """M2: NBP percentiles -> selected CDF -> fitted EMOS -> rung probs."""
    params = _emos_params_for_version(version=version, calibration_fit=calibration_fit)
    adjusted_params = EmosParams(a=params.a + correction_f, gamma=params.gamma, delta=params.delta)
    probabilities = rung_probabilities(
        apply_emos(build_cdf(cdf_method, percentiles), percentiles, adjusted_params),
        rungs,
    )
    if recalibration is None:
        return probabilities
    return apply_probability_recalibration(recalibration, probabilities)


def _calibrated_median_f(row: VersionRow, *, calibration_fit: CalibrationFit) -> float:
    params = _emos_params_for_version(version=row.version, calibration_fit=calibration_fit)
    return row.percentiles.q50 + params.a


def _correction_fit_row(row: VersionRow, *, calibration_fit: CalibrationFit) -> CorrectionFitRow:
    params = _emos_params_for_version(version=row.version, calibration_fit=calibration_fit)
    scale = math.exp(params.gamma + params.delta * math.log(row.percentiles.sd))
    return CorrectionFitRow(
        split=row.split,
        climate_day=row.climate_day,
        residual_f=row.cli_tmax_f - (row.percentiles.q50 + params.a),
        day_length_hours=_daylight_hours(row.station, row.climate_day),
        scale_f=scale,
    )


def _correction_amount(selection: CorrectionSelection, row: VersionRow, *, calibration_fit: CalibrationFit) -> float:
    correction_row = _correction_fit_row(row, calibration_fit=calibration_fit)
    return correction_row.residual_f - apply_selected_correction(
        selection, residual_f=correction_row.residual_f, row=correction_row
    )


def validate_gate_events_from_comparator_events(
    events: Sequence[ComparatorMatchedEvent],
    *,
    calibration_fit: CalibrationFit,
    cdf_method: CdfMethod,
    correction_selection: CorrectionSelection | None = None,
    recalibration_selection: ProbabilityRecalibrationSelection | None = None,
) -> tuple[MatchedEvent, ...]:
    matched: list[MatchedEvent] = []
    correction = (
        correction_selection
        if correction_selection is not None
        else CorrectionSelection(form=CorrectionForm.NONE)
    )
    recalibration = (
        recalibration_selection
        if recalibration_selection is not None
        else ProbabilityRecalibrationSelection(form=ProbabilityRecalibrationForm.NONE)
    )
    for event in events:
        if event.split != "validate":
            continue
        center_f = round(event.percentiles.q50)
        ladder = _forecast_centered_ladder(center_f)
        row = VersionRow(
            version=event.version,
            split=event.split,
            station=event.station,
            climate_day=event.climate_day,
            percentiles=event.percentiles,
            cli_tmax_f=event.cli_tmax_f,
        )
        p_m2 = calibrated_m2_rung_probabilities(
            percentiles=event.percentiles,
            version=event.version,
            calibration_fit=calibration_fit,
            rungs=ladder,
            cdf_method=cdf_method,
            correction_f=_correction_amount(
                correction, row, calibration_fit=calibration_fit
            ),
            recalibration=recalibration,
        )[event.rung_id]
        matched.append(
            MatchedEvent(
                station=event.station,
                climate_day=event.climate_day,
                p_m2=p_m2,
                p_m1=event.p_m1,
                p_m0=event.p_m0,
                outcome=event.outcome,
            )
        )
    return tuple(matched)


def _g20_rows(
    rows: Sequence[VersionRow],
    *,
    calibration_fit: CalibrationFit,
    correction_selection: CorrectionSelection,
) -> tuple[StationDayResidual, ...]:
    residual_rows: list[StationDayResidual] = []
    for row in rows:
        if row.split != "validate":
            continue
        correction_row = _correction_fit_row(row, calibration_fit=calibration_fit)
        residual_rows.append(
            StationDayResidual(
                station=row.station,
                climate_day=row.climate_day,
                residual_f=apply_selected_correction(
                    correction_selection,
                    residual_f=correction_row.residual_f,
                    row=correction_row,
                ),
                day_length_hours=correction_row.day_length_hours,
            )
        )
    return tuple(residual_rows)


def _g20a_rows(
    events: Sequence[ComparatorMatchedEvent],
    *,
    calibration_fit: CalibrationFit,
    correction_selection: CorrectionSelection,
) -> tuple[StationDayResidual, ...]:
    rows: list[StationDayResidual] = []
    for event in events:
        if event.split != "validate" or event.near_midnight is not True:
            continue
        row = VersionRow(
            version=event.version,
            split=event.split,
            station=event.station,
            climate_day=event.climate_day,
            percentiles=event.percentiles,
            cli_tmax_f=event.cli_tmax_f,
        )
        correction_row = _correction_fit_row(row, calibration_fit=calibration_fit)
        rows.append(
            StationDayResidual(
                station=event.station,
                climate_day=event.climate_day,
                residual_f=apply_selected_correction(
                    correction_selection,
                    residual_f=correction_row.residual_f,
                    row=correction_row,
                ),
                day_length_hours=correction_row.day_length_hours,
            )
        )
    return tuple(rows)


def _rung_events(events: Sequence[MatchedEvent]) -> tuple[RungEvent, ...]:
    return tuple(
        RungEvent(
            station=event.station,
            climate_day=event.climate_day,
            rung_id="mid",
            p_model=event.p_m2,
            outcome=event.outcome,
        )
        for event in events
    )


def _status_from_bool(passed: bool) -> str:
    return "PASS" if passed else "FAIL"


def _g20_to_json(result: G20Result | G20aResult, *, holm_family_size: int) -> _G20GateJson:
    groups: list[_GroupJson] = [
        {
            "key": group.key,
            "status": group.status,
            "n": group.n,
            "n_dates": group.n_dates,
            "mean_residual_f": group.mean_residual_f,
            "p_value": group.p_value,
            "holm_rejected": group.holm_rejected,
            "bootstrap_degenerate": group.bootstrap_degenerate,
        }
        for group in result.groups
    ]
    tested = [group for group in result.groups if group.status == "TESTED"]
    status = "UNTESTED" if not tested else _status_from_bool(result.flat)
    return {
        "status": status,
        "n": sum(group.n for group in result.groups),
        # `holm_family_size` (SL-8d review item 3): the SAME combined
        # G2.0/G2.0a Holm family size reported on BOTH gates -- never two
        # independently-sized families.
        "statistics": {"groups": groups, "holm_family_size": holm_family_size},
        "cis": {},
        "groups": groups,
    }


#: SL-8d coordinator correction (item 2b): every validate-stage row
#: currently scored by G2.1/G2.2/G2.3 is, by plan design, drawn from a
#: version that was ALSO used to fit that version's own (a_v, gamma_v) --
#: the decisive verdict comes from the sealed holdout, never this rehearsal.
#: Both labels are carried into the JSON `statistics` and the evidence note.
IN_SAMPLE_LABEL: Final[str] = "in-sample (by plan design) -- diagnostic only"
OUT_OF_SAMPLE_LABEL: Final[str] = "out-of-sample"


def _g21_to_json(result: G21Result, *, sample_label: str) -> _G21GateJson:
    buckets: list[_BucketJson] = [
        {
            "lower": bucket.lower,
            "upper": bucket.upper,
            "n": bucket.n,
            "predicted": bucket.predicted,
            "observed": bucket.observed,
            "z": bucket.z,
            "p_value": bucket.p_value,
            "holm_rejected": bucket.holm_rejected,
            "bootstrap_degenerate": bucket.bootstrap_degenerate,
        }
        for bucket in result.buckets
    ]
    status = "UNTESTED" if not result.buckets else _status_from_bool(result.passed)
    return {
        "status": status,
        "n": sum(bucket.n for bucket in result.buckets),
        "statistics": {"buckets": buckets, "sample_label": sample_label},
        "cis": {},
        "buckets": buckets,
    }


def _g22_to_json(result: SkillGateResult, *, n: int, sample_label: str) -> _GateJson:
    return {
        "status": _status_from_bool(result.passed),
        "n": n,
        "statistics": {
            "brier_diff_point": result.brier_diff_point,
            "d_res_point": result.d_res_point,
            "sample_label": sample_label,
        },
        "cis": {
            "brier_diff_ci": list(result.brier_diff_ci),
            "d_res_ci": list(result.d_res_ci),
        },
    }


def _g23_to_json(result: G23Result, *, n: int, sample_label: str) -> _GateJson:
    return {
        "status": _status_from_bool(result.passed),
        "n": n,
        "statistics": {"d_res_point": result.d_res_point, "sample_label": sample_label},
        "cis": {"d_res_ci": list(result.d_res_ci)},
    }


def _untested_gate(*, sample_label: str) -> _GateJson:
    return {"status": "UNTESTED", "n": 0, "statistics": {"sample_label": sample_label}, "cis": {}}


def _zero_power_metadata() -> _PowerJson:
    return {
        "sigma_d": 0.0,
        "sigma_d_ci": [0.0, 0.0],
        "n_min": 0,
        "n_min_range": [0, 0],
        "status": "OK",
        "n_min_range_status": "OK",
    }


def _fit_not_converged_gates() -> dict[str, _GateJson]:
    return {
        gate: {"status": FIT_STATUS_NOT_CONVERGED, "n": 0, "statistics": {}, "cis": {}}
        for gate in (
            "G2.0",
            "G2.0a",
            "G2.1",
            "G2.1_out_of_sample",
            "G2.2",
            "G2.2_out_of_sample",
            "G2.3",
            "G2.3_out_of_sample",
        )
    }


def _n_min_for_sigma(sigma_d: float) -> int:
    if sigma_d <= 0.0:
        return 0
    return compute_n_min(sigma_d).n_min


def _n_min_range_status(n_min_range: Sequence[int]) -> str:
    low, high = n_min_range
    if low <= N_MIN_CEILING < high:
        return "FEASIBILITY_UNDETERMINED"
    if high > N_MIN_CEILING:
        return "PMUS_INFEASIBLE_ROUTE_NODE4"
    return "OK"


def _validation_power_metadata(events: Sequence[MatchedEvent]) -> _PowerJson:
    """The validation-split estimate of sigma_d and the n_min it implies
    (plan S4.1; SL-8d review item 4), never the hard-coded ``n_min=0,
    sigma_d=0.0`` placeholder. sigma_d is the SD of each station-day's mean
    paired Brier difference (M2-M1). Its uncertainty is a seeded station-day
    cluster bootstrap with B=200. n_min and its feasibility come straight from
    :func:`breezy.analysis.nbp_calibration.compute_n_min` -- never a second,
    hand-rolled copy of that formula.
    """
    diffs_by_station_day: dict[tuple[str, dt.date], list[float]] = {}
    for event in events:
        outcome = float(event.outcome)
        diff = (event.p_m2 - outcome) ** 2 - (event.p_m1 - outcome) ** 2
        diffs_by_station_day.setdefault((event.station, event.climate_day), []).append(diff)
    per_day_items = [
        (key, statistics.fmean(diffs)) for key, diffs in sorted(diffs_by_station_day.items())
    ]
    per_day_means = [mean for _, mean in per_day_items]
    sigma_d = statistics.pstdev(per_day_means) if len(per_day_means) > 1 else 0.0
    if sigma_d <= 0.0:
        return _zero_power_metadata()
    n_min_result = compute_n_min(sigma_d)
    sigma_draws = cluster_bootstrap_draws(
        per_day_items,
        statistic=lambda drawn: statistics.pstdev([mean for _, mean in drawn])
        if len(drawn) > 1
        else 0.0,
        cluster_key=lambda item: item[0],
        seed=BOOTSTRAP_SEED,
        iterations=DEFAULT_BOOTSTRAP_DRAWS,
    )
    sigma_ci = percentile_interval(sigma_draws)
    n_min_range = [_n_min_for_sigma(sigma_ci[0]), _n_min_for_sigma(sigma_ci[1])]
    return {
        "sigma_d": n_min_result.sigma_d,
        "sigma_d_ci": [sigma_ci[0], sigma_ci[1]],
        "n_min": n_min_result.n_min,
        "n_min_range": n_min_range,
        "status": n_min_result.status,
        "n_min_range_status": _n_min_range_status(n_min_range),
    }


def _shrinkage_weights(fit: CalibrationFit, *, fit_rows: Sequence[VersionRow]) -> dict[str, float]:
    """Per-version shrinkage weight w_v = n_v / (n_v + kappa) (ruling S12
    A-4; SL-8d review item 4), via the SAME native
    :func:`breezy.analysis.nbp_calibration.shrinkage_weight` the fit itself
    used to shrink ``(a_v, gamma_v)`` -- never a second, hand-rolled copy.
    """
    kappa = fit.hierarchical.kappa_selection.chosen_kappa
    provenance = _fit_provenance(fit_rows)
    weights: dict[str, float] = {}
    for version, estimate in fit.hierarchical.shrunk_by_version.items():
        by_split = provenance.get(version, {})
        if by_split and set(by_split) <= {"train"}:
            weights[version] = 1.0
        else:
            weights[version] = shrinkage_weight(estimate.n, kappa=kappa)
    return weights


def _fit_provenance(rows: Sequence[VersionRow]) -> dict[str, dict[str, dict[str, object]]]:
    provenance: dict[str, dict[str, dict[str, object]]] = {}
    for row in rows:
        by_split = provenance.setdefault(row.version, {})
        split_record = by_split.setdefault(
            row.split,
            {"rows": 0, "first_climate_day": row.climate_day.isoformat(), "last_climate_day": row.climate_day.isoformat()},
        )
        row_count = split_record["rows"]
        if not isinstance(row_count, int):
            raise TypeError(f"fit provenance row count for {row.version}/{row.split} is not int")
        split_record["rows"] = row_count + 1
        first = str(split_record["first_climate_day"])
        last = str(split_record["last_climate_day"])
        split_record["first_climate_day"] = min(first, row.climate_day.isoformat())
        split_record["last_climate_day"] = max(last, row.climate_day.isoformat())
    return provenance


def _effective_params_source(rows: Sequence[VersionRow], fit: CalibrationFit) -> dict[str, str]:
    provenance = _fit_provenance(rows)
    result: dict[str, str] = {}
    for version in fit.hierarchical.shrunk_by_version:
        by_split = provenance.get(version, {})
        if by_split and set(by_split) <= {"train"}:
            result[version] = "train_unshrunk"
        else:
            result[version] = "validation_or_v5_fit_shrunk"
    return result


def _pooling_label(fit: CalibrationFit) -> str:
    return "full" if fit.hierarchical.kappa_selection.chosen_kappa == math.inf else "partial"


def _correction_to_json(selection: CorrectionSelection) -> _CorrectionJson:
    return {
        "form": selection.form.value,
        "validation_crps": dict(sorted(selection.validation_scores.items())),
        "month_offsets": {str(month): value for month, value in sorted(selection.month_offsets.items())},
        "linear_coefficients": (
            None
            if selection.linear_coefficients is None
            else [selection.linear_coefficients[0], selection.linear_coefficients[1]]
        ),
    }


def _recalibration_to_json(selection: ProbabilityRecalibrationSelection) -> _RecalibrationJson:
    return {
        "form": selection.form.value,
        "validation_brier": dict(sorted(selection.validation_brier.items())),
        "affine": None if selection.affine is None else [selection.affine[0], selection.affine[1]],
        "isotonic_points": [[x, y] for x, y in selection.isotonic_points],
    }


def _recalibration_events(
    events: Sequence[ComparatorMatchedEvent],
    *,
    calibration_fit: CalibrationFit,
    cdf_method: CdfMethod,
    correction_selection: CorrectionSelection,
) -> tuple[RecalibrationFitEvent, ...]:
    result: list[RecalibrationFitEvent] = []
    for event in events:
        if event.split not in ("train", "validate"):
            continue
        center_f = round(event.percentiles.q50)
        ladder = _forecast_centered_ladder(center_f)
        row = VersionRow(
            version=event.version,
            split=event.split,
            station=event.station,
            climate_day=event.climate_day,
            percentiles=event.percentiles,
            cli_tmax_f=event.cli_tmax_f,
        )
        probabilities = calibrated_m2_rung_probabilities(
            percentiles=event.percentiles,
            version=event.version,
            calibration_fit=calibration_fit,
            rungs=ladder,
            cdf_method=cdf_method,
            correction_f=_correction_amount(correction_selection, row, calibration_fit=calibration_fit),
            recalibration=None,
        )
        result.append(
            RecalibrationFitEvent(
                split=event.split,
                climate_day=event.climate_day,
                rung_id=event.rung_id,
                p_model=probabilities[event.rung_id],
                outcome=event.outcome,
            )
        )
    return tuple(result)


def _write_candidate_artefact(
    *,
    calibration_fit: CalibrationFit,
    cdf_method: CdfMethod,
    artefact_dir: Path,
    n_min: int,
    sigma_d: float,
    correction_selection: CorrectionSelection,
    recalibration_selection: ProbabilityRecalibrationSelection,
    pooling: str,
    effective_params_source: Mapping[str, str],
) -> _ArtefactJson:
    artefact_dir.mkdir(parents=True, exist_ok=True)
    artefact = artefact_from_calibration_fit(
        calibration_fit,
        cdf_method=cdf_method,
        recalibration=recalibration_selection.form.value,
        correction_form=correction_selection.form,
        correction_selection=correction_selection,
        recalibration_selection=recalibration_selection,
        pooling=pooling,
        effective_params_source=effective_params_source,
        n_min=n_min,
        sigma_d=sigma_d,
        rung_probability_bounds={},
    )
    path = artefact_dir / f"nbp_validate_candidate_{dt.date.today().isoformat()}.json"
    digest = write_artefact(path, artefact)
    return {"path": str(path), "sha256": digest}


def run_validate_gates_from_rows(
    *,
    version_rows: Sequence[VersionRow],
    comparator_events: Sequence[ComparatorMatchedEvent],
    artefact_dir: Path = DEFAULT_CALIBRATION_ARTEFACT_DIR,
    cdf_method: CdfMethod = CdfMethod.NORMAL,
    calibration_fit: CalibrationFit | None = None,
    bootstrap_iterations: int = 2_000,
    write_candidate_artefact: bool = True,
) -> ValidateGatePayload:
    # Item 1 (review): a row is holdout by ITS OWN climate_day, never by its
    # `split` tag alone -- a row mistagged e.g. "validate" but dated on or
    # after the holdout start is dropped and counted here, before it can
    # reach the fit or any gate input.
    holdout_start = DEFAULT_SPLITS.holdout_start
    pre_holdout_rows = [row for row in version_rows if row.climate_day < holdout_start]
    holdout_version_rows = [row for row in version_rows if row.climate_day >= holdout_start]
    pre_holdout_events = [event for event in comparator_events if event.climate_day < holdout_start]
    holdout_events = [event for event in comparator_events if event.climate_day >= holdout_start]

    validate_rows = [row for row in pre_holdout_rows if row.split == "validate"]
    validate_events_source = [event for event in pre_holdout_events if event.split == "validate"]

    # Item 2 (coordinator correction, superseding the SL-8d review's original
    # finding): the calibration fit sees EVERY pre-holdout row, VALIDATE
    # included. Plan S2.2, quoted verbatim: "Each version's parameters are
    # fitted on its own pre-holdout rows: train for the 2020-2024 versions,
    # validation for v4.2 (rows before 2025-05-27) and v4.3, and the v5.0 fit
    # slice (2026-05-04..06-30) for v5.0." Excluding VALIDATE would leave
    # v4.2/v4.3 with no rows to fit at all, which deviates from the plan.
    # Scoring validation rows that a version was fitted on is by design at
    # this stage -- the decisive S2 verdict comes from the sealed holdout,
    # never this rehearsal -- so every gate below that scores a
    # per-version-fitted row is labelled `IN_SAMPLE_LABEL`, and G2.1/G2.2/
    # G2.3 are ALSO reported over the out-of-sample subset only (item 2b).
    fit = (
        calibration_fit
        if calibration_fit is not None
        else fit_calibration(pre_holdout_rows, method=cdf_method)
    )
    fit_status = _fit_status_from_calibration(fit)
    kappa_curve: list[_KappaCurveJson] = [
        {"kappa": score.kappa, "mean_crps": score.mean_crps}
        for score in fit.hierarchical.kappa_selection.curve
    ]
    pooling = _pooling_label(fit)
    effective_params_source = _effective_params_source(pre_holdout_rows, fit)
    fit_provenance = _fit_provenance(pre_holdout_rows)

    # A version is "in-sample" for these gates iff its OWN pre-holdout rows
    # include at least one VALIDATE row (i.e. its fit actually touched
    # validation data) -- the only versions the plan fits on validation rows
    # (v4.2, v4.3). A comparator event whose version never appears here (a
    # train-era version, fitted purely on train) is genuinely out-of-sample:
    # its validate-split row was scored against a fit that never saw any
    # validation data for that version.
    in_sample_versions = frozenset(
        row.version for row in pre_holdout_rows if row.split == "validate"
    )
    out_of_sample_events_source = [
        event for event in validate_events_source if event.version not in in_sample_versions
    ]

    gate_days = [row.climate_day for row in validate_rows]
    gate_days.extend(event.climate_day for event in validate_events_source)
    coverage_counts: _CoverageCountsJson = {
        "fit_rows": len(pre_holdout_rows),
        "train_fit_rows": sum(1 for row in pre_holdout_rows if row.split == "train"),
        "validate_version_rows": len(validate_rows),
        "validate_comparator_events": len(validate_events_source),
        "holdout_version_rows_filtered": len(holdout_version_rows),
        "holdout_comparator_events_filtered": len(holdout_events),
        "gate_climate_day_min": min(gate_days).isoformat() if gate_days else None,
        "gate_climate_day_max": max(gate_days).isoformat() if gate_days else None,
    }

    if fit_status != FIT_STATUS_OK:
        identity_correction = CorrectionSelection(form=CorrectionForm.NONE)
        identity_recalibration = ProbabilityRecalibrationSelection(
            form=ProbabilityRecalibrationForm.NONE
        )
        return {
            "label": "validate-stage, pre-holdout -- NOT the S2 verdict",
            "stage": "validate",
            "fit_status": fit_status,
            "kappa_chosen": fit.hierarchical.kappa_selection.chosen_kappa,
            "kappa_curve": kappa_curve,
            "convergence": {
                "delta_converged": fit.delta_converged,
                "converged_by_version": {
                    version: estimate.converged
                    for version, estimate in fit.hierarchical.shrunk_by_version.items()
                },
            },
            "coverage_counts": coverage_counts,
            "gates": _fit_not_converged_gates(),
            "artefact": {"path": None, "sha256": None},
            "power": _zero_power_metadata(),
            "shrinkage_weights": {},
            "pooling": pooling,
            "effective_params_source": effective_params_source,
            "in_sample_versions": sorted(in_sample_versions),
            "fit_provenance": fit_provenance,
            "correction": _correction_to_json(identity_correction),
            "recalibration": _recalibration_to_json(identity_recalibration),
        }

    correction_input = [_correction_fit_row(row, calibration_fit=fit) for row in pre_holdout_rows]
    correction_selection = (
        select_correction_form(correction_input)
        if any(row.split == "validate" for row in correction_input)
        else CorrectionSelection(form=CorrectionForm.NONE)
    )
    recalibration_input = _recalibration_events(
        pre_holdout_events,
        calibration_fit=fit,
        cdf_method=cdf_method,
        correction_selection=correction_selection,
    )
    recalibration_selection = (
        select_probability_recalibration(recalibration_input)
        if any(event.split == "validate" for event in recalibration_input)
        else ProbabilityRecalibrationSelection(form=ProbabilityRecalibrationForm.NONE)
    )

    residual_rows = _g20_rows(validate_rows, calibration_fit=fit, correction_selection=correction_selection)
    train_day_lengths = [
        _daylight_hours(row.station, row.climate_day)
        for row in pre_holdout_rows
        if row.split == "train"
    ]
    tercile_edges = _tercile_edges(train_day_lengths)
    matched_events = validate_gate_events_from_comparator_events(
        validate_events_source,
        calibration_fit=fit,
        cdf_method=cdf_method,
        correction_selection=correction_selection,
        recalibration_selection=recalibration_selection,
    )
    g20a_residual_rows = _g20a_rows(
        validate_events_source,
        calibration_fit=fit,
        correction_selection=correction_selection,
    )
    stratum_of_station = {
        event.station: event.near_midnight_stratum
        for event in validate_events_source
        if event.near_midnight_stratum is not None
    }

    # Item 3 (review): G2.0 and G2.0a share ONE combined Holm family
    # (months + day-length terciles + near-midnight strata), per amendment
    # A-6 -- never two independently Holm-corrected families.
    g20_result, g20a_result, holm_family_size = evaluate_g20_and_g20a_combined(
        residual_rows,
        g20a_residual_rows,
        tercile_edges=tercile_edges,
        stratum_of_station=stratum_of_station,
        iterations=bootstrap_iterations,
    )
    # Item 2b (coordinator correction): the OUT-OF-SAMPLE subset of matched
    # events, scored through the SAME fit -- never re-fit -- so G2.1/G2.2/
    # G2.3 can also be read on rows whose version's fit never touched
    # validation data.
    matched_events_oos = validate_gate_events_from_comparator_events(
        out_of_sample_events_source,
        calibration_fit=fit,
        cdf_method=cdf_method,
        correction_selection=correction_selection,
        recalibration_selection=recalibration_selection,
    )

    gates: dict[str, _GateJson] = {}
    gates["G2.0"] = _g20_to_json(g20_result, holm_family_size=holm_family_size)
    gates["G2.0a"] = _g20_to_json(g20a_result, holm_family_size=holm_family_size)

    rung_events = _rung_events(matched_events)
    rung_events_oos = _rung_events(matched_events_oos)
    gates["G2.1"] = _g21_to_json(
        evaluate_g21(rung_events, iterations=bootstrap_iterations), sample_label=IN_SAMPLE_LABEL
    )
    gates["G2.1_out_of_sample"] = _g21_to_json(
        evaluate_g21(rung_events_oos, iterations=bootstrap_iterations),
        sample_label=OUT_OF_SAMPLE_LABEL,
    )

    if matched_events:
        gates["G2.2"] = _g22_to_json(
            evaluate_g22(matched_events, iterations=bootstrap_iterations),
            n=len(matched_events),
            sample_label=IN_SAMPLE_LABEL,
        )
        gates["G2.3"] = _g23_to_json(
            evaluate_g23(matched_events, iterations=bootstrap_iterations),
            n=len(matched_events),
            sample_label=IN_SAMPLE_LABEL,
        )
    else:
        gates["G2.2"] = _untested_gate(sample_label=IN_SAMPLE_LABEL)
        gates["G2.3"] = _untested_gate(sample_label=IN_SAMPLE_LABEL)

    if matched_events_oos:
        gates["G2.2_out_of_sample"] = _g22_to_json(
            evaluate_g22(matched_events_oos, iterations=bootstrap_iterations),
            n=len(matched_events_oos),
            sample_label=OUT_OF_SAMPLE_LABEL,
        )
        gates["G2.3_out_of_sample"] = _g23_to_json(
            evaluate_g23(matched_events_oos, iterations=bootstrap_iterations),
            n=len(matched_events_oos),
            sample_label=OUT_OF_SAMPLE_LABEL,
        )
    else:
        gates["G2.2_out_of_sample"] = _untested_gate(sample_label=OUT_OF_SAMPLE_LABEL)
        gates["G2.3_out_of_sample"] = _untested_gate(sample_label=OUT_OF_SAMPLE_LABEL)

    # Item 4 (review): sigma_d/n_min/status/w_v measured from real
    # validation data -- never the hard-coded n_min=0, sigma_d=0.0.
    power = _validation_power_metadata(matched_events)
    shrinkage_weights = _shrinkage_weights(fit, fit_rows=pre_holdout_rows)

    artefact_info: _ArtefactJson = {"path": None, "sha256": None}
    if write_candidate_artefact:
        try:
            artefact_info = _write_candidate_artefact(
                calibration_fit=fit,
                cdf_method=cdf_method,
                artefact_dir=artefact_dir,
                n_min=power["n_min"],
                sigma_d=power["sigma_d"],
                correction_selection=correction_selection,
                recalibration_selection=recalibration_selection,
                pooling=pooling,
                effective_params_source=effective_params_source,
            )
        except FitNotConvergedError:
            artefact_info = {"path": None, "sha256": None}

    return {
        "label": "validate-stage, pre-holdout -- NOT the S2 verdict",
        "stage": "validate",
        "fit_status": fit_status,
        "kappa_chosen": fit.hierarchical.kappa_selection.chosen_kappa,
        "kappa_curve": kappa_curve,
        "convergence": {
            "delta_converged": fit.delta_converged,
            "delta_nfev": fit.delta_nfev,
            "converged_by_version": {
                version: estimate.converged
                for version, estimate in fit.hierarchical.shrunk_by_version.items()
            },
            "nfev_by_version": {
                version: estimate.nfev
                for version, estimate in fit.hierarchical.shrunk_by_version.items()
            },
        },
        "coverage_counts": coverage_counts,
        "gates": gates,
        "artefact": artefact_info,
        "power": power,
        "shrinkage_weights": shrinkage_weights,
        "pooling": pooling,
        "effective_params_source": effective_params_source,
        "in_sample_versions": sorted(in_sample_versions),
        "fit_provenance": fit_provenance,
        "correction": _correction_to_json(correction_selection),
        "recalibration": _recalibration_to_json(recalibration_selection),
    }


def write_validate_evidence_note(
    payload: Mapping[str, object],
    *,
    date: dt.date,
    evidence_dir: Path,
) -> Path:
    # Required. A repo-path default let tests overwrite docs/evidence and unlink
    # the committed note. The CLI passes DEFAULT_VALIDATE_EVIDENCE_DIR itself.
    path = evidence_dir / f"NBP_S2_VALIDATE_RESULT_{date.isoformat()}.md"
    gates = payload.get("gates", {})
    artefact = payload.get("artefact")
    artefact_sha256 = artefact.get("sha256") if isinstance(artefact, Mapping) else None
    power = payload.get("power")
    power_sigma_d = power.get("sigma_d") if isinstance(power, Mapping) else None
    power_sigma_d_ci = power.get("sigma_d_ci") if isinstance(power, Mapping) else None
    power_n_min = power.get("n_min") if isinstance(power, Mapping) else None
    power_n_min_range = power.get("n_min_range") if isinstance(power, Mapping) else None
    power_status = power.get("status") if isinstance(power, Mapping) else None
    power_n_min_range_status = (
        power.get("n_min_range_status") if isinstance(power, Mapping) else None
    )
    shrinkage_weights = payload.get("shrinkage_weights")
    pooling = payload.get("pooling")
    effective_params_source = payload.get("effective_params_source")
    correction = payload.get("correction")
    recalibration = payload.get("recalibration")
    lines = [
        "# NBP S2 Validate Result",
        "",
        "**validate-stage, pre-holdout -- NOT the S2 verdict**",
        "",
        f"- fit_status: `{payload.get('fit_status')}`",
        f"- kappa_chosen: `{payload.get('kappa_chosen')}`",
        f"- artefact_sha256: `{artefact_sha256}`",
        f"- sigma_d: `{power_sigma_d}`",
        f"- sigma_d_ci: `{power_sigma_d_ci}`",
        f"- n_min: `{power_n_min}`",
        f"- n_min_range: `{power_n_min_range}`",
        f"- power_status: `{power_status}`",
        f"- n_min_range_status: `{power_n_min_range_status}`",
        f"- shrinkage_weights: `{shrinkage_weights}`",
        f"- pooling: `{pooling}`",
        f"- effective_params_source: `{effective_params_source}`",
        f"- correction: `{correction}`",
        f"- recalibration: `{recalibration}`",
        "",
        "## Gates",
        "",
    ]
    if isinstance(gates, Mapping):
        for gate_name in (
            "G2.0",
            "G2.0a",
            "G2.1",
            "G2.1_out_of_sample",
            "G2.2",
            "G2.2_out_of_sample",
            "G2.3",
            "G2.3_out_of_sample",
        ):
            gate = gates.get(gate_name, {})
            status = gate.get("status") if isinstance(gate, Mapping) else None
            n_value = gate.get("n") if isinstance(gate, Mapping) else None
            gate_statistics = gate.get("statistics") if isinstance(gate, Mapping) else None
            sample_label = (
                gate_statistics.get("sample_label") if isinstance(gate_statistics, Mapping) else None
            )
            label_suffix = f" [{sample_label}]" if sample_label else ""
            lines.append(f"- {gate_name}: `{status}` (n={n_value}){label_suffix}")
    lines.extend(
        [
            "",
            "## Source JSON",
            "",
            "This note is generated by `scripts/analysis/nbp_skill_study.py` from the JSON result; numbers are not hand-written.",
            "",
            "```json",
            json.dumps(payload, indent=2, sort_keys=True),
            "```",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


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
    if args.stage == "holdout" and args.run_gates:
        parser.error("--run-gates is validate-stage only; this script must not score holdout gates")
    if args.stage == "holdout":
        print(f"nbp_skill_study: stage={args.stage} splits={DEFAULT_SPLITS!r}")
        return 0

    settlement_truth_parquet = args.settlement_truth_root / DEFAULT_SETTLEMENT_TRUTH_PARQUET.name
    version_rows, report = run_validate(
        nbp_derived_root=args.nbp_derived_root,
        settlement_truth_parquet=settlement_truth_parquet,
        archive_root=args.archive_root,
    )

    payload = _report_to_json_dict(report)
    if args.comparator_models or args.run_gates:
        # Opt-in: `daily_max_instants` fully parses the ASOS 1-minute
        # archive (~367MB / 9.0M rows) rather than reading manifest row
        # counts only, unlike every OTHER function `main()` calls by
        # default -- so this stays off the default fast path (SL-8c).
        comparator_events, comparator_report = run_comparator_validate(
            nbp_derived_root=args.nbp_derived_root,
            settlement_truth_parquet=settlement_truth_parquet,
            archive_root=args.archive_root,
        )
        payload["comparator_models"] = _comparator_report_to_json_dict(comparator_report)
        if args.run_gates:
            gate_payload = run_validate_gates_from_rows(
                version_rows=version_rows,
                comparator_events=comparator_events,
            )
            payload["validate_gates"] = gate_payload
            evidence_note = write_validate_evidence_note(
                gate_payload,
                date=dt.date.today(),
                evidence_dir=DEFAULT_VALIDATE_EVIDENCE_DIR,
            )
            payload["validate_evidence_note"] = str(evidence_note)
    print(f"nbp_skill_study: stage=validate splits={DEFAULT_SPLITS!r}")
    print(json.dumps(payload, indent=2, sort_keys=True))
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
