"""RED-first tests for the `nbp_skill_study` CLI: the holdout guard (SL-8)
and the real-data validate-stage join (SL-8b task 5).

The join fixtures below are entirely SYNTHETIC -- hand-built
`DerivedNbpRow`/`SettlementTruthRow` rows written to `tmp_path` parquet
files, never the real backfill or the real v5.0 holdout.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import math
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final, cast

import pyarrow.parquet as pq
import pytest

_MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "analysis" / "nbp_skill_study.py"
_spec = importlib.util.spec_from_file_location("nbp_skill_study", _MODULE_PATH)
assert _spec is not None and _spec.loader is not None
nbp_skill_study = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = nbp_skill_study
_spec.loader.exec_module(nbp_skill_study)

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "analysis"))

from settlement_truth_dataset import STATUS_FINAL, SettlementTruthRow, rows_to_table  # type: ignore[import-not-found]  # noqa: E402

from breezy.analysis import nbp_calibration as calib  # noqa: E402
from scripts.analysis.nbp_skill_study import ComparatorMatchedEvent as NbpComparatorMatchedEvent  # noqa: E402
from breezy.analysis.nbp_calibration import DEFAULT_SPLITS  # noqa: E402
from breezy.analysis.nbp_comparator_models import target_climate_day  # noqa: E402
from breezy.persistence.archive_cache import ArchiveCache, ArchiveRequest, IEM_MOS_SOURCE  # noqa: E402
from breezy.persistence.nbp_derived_store import DerivedNbpRow, write_partition  # noqa: E402
from breezy.strategy.ladder_ev.quantile_density import (  # noqa: E402
    CdfMethod,
    EmosParams,
    Percentiles,
    build_cdf,
    rung_probabilities,
)
from breezy.strategy.weather_common.probability import ForecastErrorModel  # noqa: E402


def test_default_stage_is_validate_and_never_needs_authorization() -> None:
    assert nbp_skill_study.main([]) == 0


def test_stage_holdout_without_authorization_refuses() -> None:
    with pytest.raises(nbp_skill_study.HoldoutNotCoordinatorAuthorizedError):
        nbp_skill_study.main(["--stage", "holdout"])


def test_stage_holdout_with_authorization_runs() -> None:
    assert nbp_skill_study.main(["--stage", "holdout", "--coordinator-authorized"]) == 0


# ---------------------------------------------------------------------------
# Fixture builders.
# ---------------------------------------------------------------------------

_NS: int = 10**9


def _cycle_runtime_ns(day: dt.date, hour: int) -> int:
    instant = dt.datetime(day.year, day.month, day.day, hour, tzinfo=dt.UTC)
    return int(instant.timestamp()) * _NS

def _valid_00z_ns(day: dt.date) -> int:
    instant = dt.datetime(day.year, day.month, day.day, 0, tzinfo=dt.UTC)
    return int(instant.timestamp()) * _NS


#: A 13Z (or 19Z) cycle published on UTC day D maps to D+1 via the window
#: whose OWN valid UTC calendar day is D+2 -- never D+1 (that is the
#: temporally-nearest window, and it resolves to D0; see
#: `build_version_rows`'s docstring worked example). Both KMIA (-5) and
#: KLAX (-8) share this target -- hand-verified against the real
#: `climate_day_for_txn`/`local_standard_date` helpers, and pinned again in
#: `test_d1_worked_example_*` below.
def _d1_valid_ns_for_13z_or_19z(cycle_day: dt.date) -> int:
    return _valid_00z_ns(cycle_day + dt.timedelta(days=2))


#: A 01Z cycle published on UTC day X maps to D+1 (== X) via the window
#: whose OWN valid UTC calendar day is X+1 -- see `build_version_rows`'s
#: docstring worked example (01Z case).
def _d1_valid_ns_for_01z(cycle_day: dt.date) -> int:
    return _valid_00z_ns(cycle_day + dt.timedelta(days=1))


def _derived_row(
    *,
    station: str,
    variable: str,
    cycle_runtime_ns: int,
    valid_ns: int,
    value_f: float | None,
    nbm_version_era: str = "v5.0",
) -> DerivedNbpRow:
    return DerivedNbpRow(
        station=station,
        variable=variable,
        cycle_runtime_ns=cycle_runtime_ns,
        valid_start_ns=valid_ns,
        valid_end_ns=valid_ns,
        value_f=value_f,
        absence_reason=None,
        header_model_version=nbm_version_era.lstrip("v"),
        nbm_version_era=nbm_version_era,
        version_break_mismatch=False,
        available_at_ns=cycle_runtime_ns,
        last_modified=None,
        source_host="test",
        raw_sha256="0" * 64,
        fetched_at_ns=cycle_runtime_ns,
    )


def _complete_window_rows(
    *,
    station: str,
    cycle_runtime_ns: int,
    valid_ns: int,
    q50: float,
    sd: float = 3.0,
    nbm_version_era: str = "v5.0",
) -> list[DerivedNbpRow]:
    values = {
        "TXN_MEAN": q50,
        "TXN_SD": sd,
        "TXN_Q10": q50 - 4.0,
        "TXN_Q25": q50 - 2.0,
        "TXN_Q50": q50,
        "TXN_Q75": q50 + 2.0,
        "TXN_Q90": q50 + 4.0,
    }
    return [
        _derived_row(
            station=station,
            variable=variable,
            cycle_runtime_ns=cycle_runtime_ns,
            valid_ns=valid_ns,
            value_f=value,
            nbm_version_era=nbm_version_era,
        )
        for variable, value in values.items()
    ]


def _settlement_row(*, station: str, climate_day: dt.date, tmax_f: int) -> SettlementTruthRow:
    return SettlementTruthRow(
        station=station,
        city=station,
        climate_day=climate_day,
        status=STATUS_FINAL,
        is_final=True,
        tmax_f=tmax_f,
        tmin_f=None,
        tavg_f=None,
        tmax_flag=None,
        had_correction=False,
        preliminary_tmax_f=None,
        preliminary_differed=None,
        preliminary_delta_f=None,
        total_issuance_count=1,
        final_issuance_count=1,
        final_tmax_revised=False,
        final_is_correction_bbb=False,
        correction_text_evidence=False,
        revision_seq=1,
        wmo_transmission_sequence=None,
        wmo_bbb=None,
        product_id=None,
        raw_sha256=None,
        issued_at_utc=None,
        source_zip=None,
        source_member=None,
        within_expected_window=True,
        interior_bucket_lower_even_f=None,
        interior_bucket_upper_even_f=None,
        interior_bucket_slug_even=None,
        interior_bucket_lower_odd_f=None,
        interior_bucket_upper_odd_f=None,
        interior_bucket_slug_odd=None,
        settlement_grade_within_window=True,
        settlement_grade_including_spillover=True,
    )


def _write_settlement_truth(rows: list[SettlementTruthRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(rows_to_table(rows), path)


# ---------------------------------------------------------------------------
# complete_percentile_windows
# ---------------------------------------------------------------------------


#: Real observed NBM lead-hour grid (coordinator correction 2026-09-29,
#: verified against BOTH real archived sources: `tests/fixtures/nbm/
#: nbptx_t{13,19,01}z_excerpt.txt` -- a real 2026-09-28/29 capture whose FHR
#: row shows the first MAX (00Z) column at these exact leads -- and a
#: full-archive scan of the real on-disk IEM MOS NBS cache, whose txn-
#: populated ftimes land at the IDENTICAL leads. Neither source ever
#: publishes a shorter "nearest calendar 00Z" lead (e.g. 11h/5h after a
#: 13Z/19Z cycle): the grid jumps straight from the cycle to the first
#: MAX/MIN pair at these hours. So on REAL data, explicit
#: climate_day_for_txn selection agrees with "the first/nearest available
#: MAX column" -- both point to the SAME row. The second entry of each pair
#: is the NEXT real MAX column (24h later), which maps to D+2, not the
#: target D+1; the selector must discriminate between these two REAL
#: candidates, never approximate with whichever is merely nearest without
#: checking.
_REAL_FIRST_AND_SECOND_MAX_LEAD_HOURS: Final[dict[int, tuple[int, int]]] = {
    13: (35, 59),
    19: (29, 53),
    1: (23, 47),
}


def test_complete_percentile_windows_drops_incomplete_groups_and_counts_them() -> None:
    day = dt.date(2025, 6, 1)
    cycle = _cycle_runtime_ns(day, 13)
    near = _valid_00z_ns(day + dt.timedelta(days=1))
    far = _valid_00z_ns(day + dt.timedelta(days=2))
    rows = [
        *_complete_window_rows(station="KMIA", cycle_runtime_ns=cycle, valid_ns=near, q50=90.0),
        *_complete_window_rows(station="KMIA", cycle_runtime_ns=cycle, valid_ns=far, q50=91.0),
    ]
    # Drop one variable from the NEAR window only -- it is reported
    # (incomplete_windows), never imputed and never silently replaced by a
    # different window under the same identity.
    rows = [row for row in rows if not (row.valid_start_ns == near and row.variable == "TXN_SD")]

    counts = nbp_skill_study._WindowGroupCounts()
    windows = nbp_skill_study.complete_percentile_windows(rows, counts=counts)

    assert counts.incomplete_windows == 1
    assert len(windows) == 1
    assert windows[0].valid_start_ns == far
    assert windows[0].percentiles.q50 == pytest.approx(91.0)


def test_complete_percentile_windows_keeps_every_complete_window_for_the_same_cycle() -> None:
    """A (station, cycle) may publish more than one complete 00Z valid
    window -- `complete_percentile_windows` keeps ALL of them; WHICH one is
    the D+1 target is `build_version_rows`'s decision, never a "nearest"
    reduction made here (SL-8b review item 1)."""
    day = dt.date(2025, 6, 1)
    cycle = _cycle_runtime_ns(day, 13)
    near = _valid_00z_ns(day + dt.timedelta(days=1))
    far = _valid_00z_ns(day + dt.timedelta(days=2))
    rows = [
        *_complete_window_rows(station="KMIA", cycle_runtime_ns=cycle, valid_ns=near, q50=90.0),
        *_complete_window_rows(station="KMIA", cycle_runtime_ns=cycle, valid_ns=far, q50=91.0),
    ]
    windows = nbp_skill_study.complete_percentile_windows(rows)
    assert {window.valid_start_ns for window in windows} == {near, far}


# ---------------------------------------------------------------------------
# build_version_rows -- the join, gap counting, and the holdout invariant.
# ---------------------------------------------------------------------------


def _registry() -> object:
    # nbp_skill_study is loaded dynamically (importlib.util.module_from_spec
    # above), so mypy cannot resolve `nbp_skill_study.StationRegistry` as a
    # type expression -- `object` keeps this helper strictly typed without
    # that reference.
    return nbp_skill_study.station_registry()


def test_build_version_rows_matches_a_qualifying_window_to_its_settlement_row() -> None:
    # A 13Z cycle published on UTC day `day` has LST publish date == `day`
    # at KMIA (offset -5; 13-5=8, still day `day`), so its EXPLICIT D+1
    # target climate day is `day + 1`. That target is reached by the 00Z
    # window whose OWN valid UTC calendar day is `day + 2` --
    # `local_standard_date` of a 00Z instant is always the PRECEDING UTC
    # day for KMIA's negative offset (verified against the real
    # `climate_day_for_txn`/`local_standard_date` helpers; see
    # `build_version_rows`'s own docstring worked example and
    # NBP_TXN_WINDOW_AND_BBB_NOTE_2026-09-29.md). The temporally NEAREST
    # 00Z window (`day + 1`) would instead resolve to climate_day == `day`
    # (D0) -- exactly the SL-8b review item 1 bug this fix closes.
    day = dt.date(2025, 6, 1)
    climate_day = day + dt.timedelta(days=1)
    cycle = _cycle_runtime_ns(day, 13)
    from breezy.strategy.ladder_ev.quantile_density import Percentiles

    window = nbp_skill_study.NbpPercentileWindow(
        station="KMIA",
        cycle_runtime_ns=cycle,
        valid_start_ns=_valid_00z_ns(day + dt.timedelta(days=2)),
        nbm_version_era="v5.0",
        percentiles=Percentiles(q10=86, q25=88, q50=90, q75=92, q90=94, mean=90, sd=3.0),
    )
    settlement = {("MIA", climate_day): _settlement_row(station="MIA", climate_day=climate_day, tmax_f=91)}

    version_rows, gaps = nbp_skill_study.build_version_rows([window], settlement, registry=_registry())

    assert len(version_rows) == 1
    row = version_rows[0]
    assert row.station == "MIA"
    assert row.climate_day == climate_day
    assert row.cli_tmax_f == 91.0
    assert row.version == "v5.0"
    assert gaps == {}


def test_build_version_rows_counts_a_non_qualifying_cycle_hour() -> None:
    day = dt.date(2025, 6, 1)
    cycle = _cycle_runtime_ns(day, 6)  # 06Z is not a qualifying cycle
    climate_day = day + dt.timedelta(days=1)
    from breezy.strategy.ladder_ev.quantile_density import Percentiles

    window = nbp_skill_study.NbpPercentileWindow(
        station="KMIA",
        cycle_runtime_ns=cycle,
        valid_start_ns=_valid_00z_ns(climate_day),
        nbm_version_era="v5.0",
        percentiles=Percentiles(q10=86, q25=88, q50=90, q75=92, q90=94, mean=90, sd=3.0),
    )
    version_rows, gaps = nbp_skill_study.build_version_rows([window], {}, registry=_registry())
    assert version_rows == ()
    assert gaps == {"non_qualifying_cycle": 1}


def test_build_version_rows_counts_a_missing_settlement_row() -> None:
    day = dt.date(2025, 6, 1)
    cycle = _cycle_runtime_ns(day, 13)
    # See the explicit-D+1 note above: the target window's own valid UTC
    # day is `day + 2`, not `climate_day` itself.
    from breezy.strategy.ladder_ev.quantile_density import Percentiles

    window = nbp_skill_study.NbpPercentileWindow(
        station="KMIA",
        cycle_runtime_ns=cycle,
        valid_start_ns=_valid_00z_ns(day + dt.timedelta(days=2)),
        nbm_version_era="v5.0",
        percentiles=Percentiles(q10=86, q25=88, q50=90, q75=92, q90=94, mean=90, sd=3.0),
    )
    version_rows, gaps = nbp_skill_study.build_version_rows([window], {}, registry=_registry())
    assert version_rows == ()
    assert gaps == {"missing_settlement": 1}


def test_a_holdout_dated_row_is_never_present_in_validate_mode_output() -> None:
    """The HARD invariant: even when a matching settlement row exists for a
    holdout-dated climate day, build_version_rows must never emit it."""
    from breezy.strategy.ladder_ev.quantile_density import Percentiles

    holdout_day = DEFAULT_SPLITS.holdout_start  # 2026-07-01
    # A cycle published the DAY BEFORE holdout_day has target climate_day ==
    # holdout_day (explicit D+1: LST publish date `holdout_day - 1`, plus
    # one day) -- reached by the window whose own valid UTC day is
    # `holdout_day + 1` (see the explicit-D+1 note above).
    cycle_day = holdout_day - dt.timedelta(days=1)
    cycle = _cycle_runtime_ns(cycle_day, 13)
    window = nbp_skill_study.NbpPercentileWindow(
        station="KMIA",
        cycle_runtime_ns=cycle,
        valid_start_ns=_valid_00z_ns(holdout_day + dt.timedelta(days=1)),
        nbm_version_era="v5.0",
        percentiles=Percentiles(q10=86, q25=88, q50=90, q75=92, q90=94, mean=90, sd=3.0),
    )
    settlement = {
        ("MIA", holdout_day): _settlement_row(station="MIA", climate_day=holdout_day, tmax_f=91),
    }

    version_rows, gaps = nbp_skill_study.build_version_rows(
        [window], settlement, registry=_registry(), splits=DEFAULT_SPLITS
    )

    assert version_rows == ()
    assert all(row.climate_day < holdout_day for row in version_rows)
    assert gaps.get("holdout_excluded", 0) == 1


def test_settlement_lookup_never_carries_a_holdout_dated_row_even_before_the_join() -> None:
    """Defense in depth: `_settlement_lookup` itself drops any row at or
    after the holdout start, independent of what the NBP side does."""
    holdout_day = DEFAULT_SPLITS.holdout_start
    rows = [
        _settlement_row(station="MIA", climate_day=holdout_day, tmax_f=91),
        _settlement_row(station="MIA", climate_day=holdout_day - dt.timedelta(days=1), tmax_f=90),
    ]
    lookup = nbp_skill_study._settlement_lookup(rows, holdout_start=holdout_day)
    assert ("MIA", holdout_day) not in lookup
    assert ("MIA", holdout_day - dt.timedelta(days=1)) in lookup


# ---------------------------------------------------------------------------
# read_settlement_truth_rows -- round trip.
# ---------------------------------------------------------------------------


def test_read_settlement_truth_rows_round_trips_through_parquet(tmp_path: Path) -> None:
    rows = [
        _settlement_row(station="MIA", climate_day=dt.date(2025, 6, 1), tmax_f=91),
        _settlement_row(station="SFO", climate_day=dt.date(2025, 6, 2), tmax_f=68),
    ]
    path = tmp_path / "settlement_truth.parquet"
    _write_settlement_truth(rows, path)

    read_back = nbp_skill_study.read_settlement_truth_rows(path)

    assert len(read_back) == 2
    by_station = {row.station: row for row in read_back}
    assert by_station["MIA"].tmax_f == 91
    assert by_station["MIA"].climate_day == dt.date(2025, 6, 1)
    assert by_station["SFO"].tmax_f == 68


def test_read_settlement_truth_rows_returns_empty_for_a_missing_file(tmp_path: Path) -> None:
    assert nbp_skill_study.read_settlement_truth_rows(tmp_path / "nope.parquet") == ()


# ---------------------------------------------------------------------------
# run_validate -- end to end over tmp_path fixtures, bounded memory (one
# partition read at a time), tolerant of an unparseable partition.
# ---------------------------------------------------------------------------


def test_run_validate_end_to_end_over_synthetic_fixtures(tmp_path: Path) -> None:
    nbp_root = tmp_path / "nbp-derived"
    settlement_path = tmp_path / "settlement-truth" / "settlement_truth.parquet"
    archive_root = tmp_path / "archive"  # deliberately empty -- zero MOS/ASOS coverage, no crash

    day = dt.date(2025, 6, 1)
    climate_day = day + dt.timedelta(days=1)  # explicit D+1 -- see the note above
    cycle = _cycle_runtime_ns(day, 13)
    rows = _complete_window_rows(
        station="KMIA",
        cycle_runtime_ns=cycle,
        valid_ns=_valid_00z_ns(day + dt.timedelta(days=2)),
        q50=90.0,
    )
    write_partition(rows, nbp_root / "2025" / "06" / "nbp_20250601_13z.parquet")

    # A second, UNPARSEABLE "partition" -- the backfill may still be
    # writing; this must be counted, never fatal.
    bogus = nbp_root / "2025" / "06" / "nbp_20250602_13z.parquet"
    bogus.parent.mkdir(parents=True, exist_ok=True)
    bogus.write_bytes(b"not a parquet file")

    _write_settlement_truth(
        [_settlement_row(station="MIA", climate_day=climate_day, tmax_f=91)], settlement_path
    )

    version_rows, report = nbp_skill_study.run_validate(
        nbp_derived_root=nbp_root, settlement_truth_parquet=settlement_path, archive_root=archive_root
    )

    assert report.unparseable_partitions == 1
    assert report.matched_version_rows == 1
    assert version_rows[0].station == "MIA"
    assert version_rows[0].climate_day == climate_day
    assert version_rows[0].cli_tmax_f == 91.0
    assert report.n_by_split == {"validate": 1}
    assert report.n_by_version == {"v5.0": 1}
    assert report.mos_txn_populated_rows_by_station == {"KLAX": 0, "KMDW": 0, "KMIA": 0, "KSFO": 0}
    assert report.asos_1min_rows_by_station == {"KLAX": 0, "KMDW": 0, "KMIA": 0, "KSFO": 0}


def test_run_validate_over_an_empty_root_returns_zero_coverage(tmp_path: Path) -> None:
    version_rows, report = nbp_skill_study.run_validate(
        nbp_derived_root=tmp_path / "does-not-exist",
        settlement_truth_parquet=tmp_path / "also-missing.parquet",
        archive_root=tmp_path / "archive-missing",
    )
    assert version_rows == ()
    assert report.total_percentile_windows == 0
    assert report.matched_version_rows == 0


# ---------------------------------------------------------------------------
# Worked-example D+1 pins (SL-8b review item 1; coordinator-required
# extension to all 4 join stations, and CORRECTED against the real NBP
# bulletin grid -- coordinator correction 2026-09-29).
#
# **The real grid never publishes a same-UTC-day-after-cycle MAX column.**
# `tests/unit/test_nbm_quantile_parse.py` already parses and hand-verifies
# the REAL captured bulletins (`tests/fixtures/nbm/nbptx_t{13,19,01}z_
# excerpt.txt`): for a 13Z cycle the grid's first group (FHR 23) carries
# only the 12Z/MIN sub-value -- the FIRST MAX (00Z) column is FHR 35; for
# 19Z it is FHR 29; for 01Z the first group already carries both 00Z and
# 12Z, at FHR 23. All three converge on the SAME UTC instant for the
# 2026-09-28/29 fixture cycles (2026-09-30 00:00 UTC -- see that module's
# `test_hand_computed_dplus1_lst_day_per_station_per_cycle`), which is
# ALREADY the D+1 LST target at every station. Confirmed independently
# here against the real on-disk backfill (`~/.local/share/breezy/derived/
# nbp/2025/09/nbp_20250925_{13,19}z.parquet`): the smallest available
# valid_start_ns per (station, cycle) is day+2 (UTC), never day+1 -- a
# day+1 TXN row is never populated by this venue's real feed. So the OLD
# "nearest available complete window" reduction and the NEW explicit
# `climate_day_for_txn`-matched target select the IDENTICAL window on
# every real cycle this join has ever ingested (12/12 real (station,
# cycle) groups checked, zero mismatches) -- this is NOT an observed
# real-data D0 bug.
#
# The fix in `build_version_rows` is kept anyway, as an explicit-selection
# ROBUSTNESS improvement: the old reduction's correctness depended on an
# UNDECLARED assumption about the venue's publication grid (no day+1 MAX
# column ever exists), not on anything the algorithm itself enforced. A
# partial/malformed partition, a future NBM grid change, or an
# out-of-order backfill write could in principle populate an earlier,
# wrong-day row, and "nearest" would silently accept it; the explicit
# target check refuses instead. The tests below assert the REAL-grid
# equivalence (never a "picks the wrong day" claim), plus one adversarial
# case proving the explicit check actually refuses a hypothetical
# early/malformed row that "nearest" would have silently accepted.
# ---------------------------------------------------------------------------

from breezy.ingest.gaps import local_standard_date  # noqa: E402
from forecast_climate_day_map import climate_day_for_txn  # type: ignore[import-not-found]  # noqa: E402

_ALL_STATION_OFFSETS: dict[str, float] = {"KLAX": -8.0, "KMDW": -6.0, "KMIA": -5.0, "KSFO": -8.0}


def _target_climate_day(offset: float, cycle_day: dt.date, cycle_hour: int) -> tuple[dt.date, int]:
    """Independently reconstructs `build_version_rows`'s own D+1 target
    computation from the PUBLIC helpers, for one hand-picked cycle."""
    runtime_ns = _cycle_runtime_ns(cycle_day, cycle_hour)
    publish_lst_date = local_standard_date(runtime_ns, offset)
    target_climate_day = publish_lst_date + dt.timedelta(days=1)
    return target_climate_day, runtime_ns


@pytest.mark.parametrize("icao", sorted(_ALL_STATION_OFFSETS))
def test_d1_worked_example_13z_and_19z_target_equals_the_real_grids_only_available_window(icao: str) -> None:
    # HAND-WORKED (every join station, both cycle hours): a 13Z or 19Z
    # cycle published on UTC day D keeps 13/19 minus the (<=8h) offset
    # within day D itself (13-8=5, 13-6=7, 13-5=8; 19-8=11, 19-6=13,
    # 19-5=14; all >= 0) -- so the LST publish date is D, and the D+1
    # target climate_day is D+1. The window that reaches D+1 is the 00Z
    # valid time on UTC day D+2 -- which is ALSO the real bulletin's FIRST
    # available MAX column (FHR 35/29 respectively; a day+1 MAX is never
    # published -- see the module-level note above). "Nearest available"
    # and "explicit D+1 target" therefore select the SAME window here.
    offset = _ALL_STATION_OFFSETS[icao]
    day = dt.date(2025, 6, 1)
    for hour in (13, 19):
        target_climate_day, runtime_ns = _target_climate_day(offset, day, hour)
        assert target_climate_day == day + dt.timedelta(days=1)

        target_valid_ns = _valid_00z_ns(day + dt.timedelta(days=2))
        target_window_climate_day = climate_day_for_txn(
            icao=icao, runtime_ns=runtime_ns, ftime_ns=target_valid_ns, std_utc_offset_hours=offset,
            model="v5.0", kind="max",
        )
        assert target_window_climate_day == target_climate_day


@pytest.mark.parametrize("icao", sorted(_ALL_STATION_OFFSETS))
def test_d1_worked_example_01z_is_issued_on_the_previous_lst_evening(icao: str) -> None:
    # HAND-WORKED: a 01Z cycle published on UTC day X is 01:00 UTC; minus
    # the (5-8h) offset that falls on UTC day X-1 (01-8=17, 01-6=19,
    # 01-5=20, all negative before adding 24h -- i.e. the PREVIOUS day's
    # evening), so the LST publish date is X-1, and the D+1 target
    # climate_day is X. The window that reaches X is the 00Z valid time on
    # UTC day X+1 -- the real bulletin's first available MAX column here
    # too (FHR 23; the 01Z grid's very first group already carries both
    # 00Z and 12Z).
    offset = _ALL_STATION_OFFSETS[icao]
    x = dt.date(2025, 6, 2)
    target_climate_day, runtime_ns = _target_climate_day(offset, x, 1)
    assert target_climate_day == x

    target_valid_ns = _valid_00z_ns(x + dt.timedelta(days=1))
    target_window_climate_day = climate_day_for_txn(
        icao=icao, runtime_ns=runtime_ns, ftime_ns=target_valid_ns, std_utc_offset_hours=offset,
        model="v5.0", kind="max",
    )
    assert target_window_climate_day == target_climate_day


def test_real_archive_old_nearest_reduction_and_the_new_explicit_target_agree_on_every_group() -> None:
    """Direct regression against the real on-disk backfill: for every
    (station, cycle) group in a real 13Z/19Z/01Z partition trio, the OLD
    "smallest available valid_start_ns" choice and the NEW explicit
    `climate_day_for_txn`-matched-to-target choice select the SAME
    climate_day. Skips (never fails) if the real archive is absent in this
    environment -- it is a read-only cross-check of already-backfilled
    data, not a fixture this test owns."""
    from breezy.persistence.nbp_derived_store import read_partition

    root = Path.home() / ".local/share/breezy/derived/nbp/2025/09"
    paths = [
        root / "nbp_20250925_13z.parquet",
        root / "nbp_20250925_19z.parquet",
        root / "nbp_20250926_01z.parquet",
    ]
    if not all(p.exists() for p in paths):
        pytest.skip("real NBP archive not present in this environment")

    registry = nbp_skill_study.station_registry()
    rows = [row for path in paths for row in read_partition(path)]
    windows = nbp_skill_study.complete_percentile_windows(rows)

    # nbp_skill_study is loaded dynamically (see the module-level comment
    # above `_registry()`), so mypy cannot resolve `NbpPercentileWindow` as
    # a type expression here -- `Any` keeps attribute access typed-through.
    old_best: dict[tuple[str, int], Any] = {}
    for window in windows:
        key = (window.station, window.cycle_runtime_ns)
        if key not in old_best or window.valid_start_ns < old_best[key].valid_start_ns:
            old_best[key] = window

    assert len(old_best) == 12  # 4 stations x 3 cycles
    for (station, cycle_runtime_ns), window in old_best.items():
        offset = registry.std_utc_offset_hours_by_icao[station]
        target = local_standard_date(cycle_runtime_ns, offset) + dt.timedelta(days=1)
        old_climate_day = climate_day_for_txn(
            icao=station, runtime_ns=cycle_runtime_ns, ftime_ns=window.valid_start_ns,
            std_utc_offset_hours=offset, model=window.nbm_version_era, kind="max",
        )
        assert old_climate_day == target, (station, cycle_runtime_ns, old_climate_day, target)


def test_explicit_target_refuses_a_hypothetical_early_window_nearest_would_have_accepted() -> None:
    """The robustness case the real grid never exercises: IF a (station,
    cycle) group ever carried a spurious day+1 window (malformed partition,
    out-of-order backfill write -- something the real venue feed has never
    produced, per the module note above), `build_version_rows` must refuse
    it, counting `no_d1_window`, rather than silently accepting it the way
    the OLD "nearest available" reduction would have."""
    from breezy.strategy.ladder_ev.quantile_density import Percentiles

    day = dt.date(2025, 6, 1)
    cycle = _cycle_runtime_ns(day, 13)
    early_but_wrong = nbp_skill_study.NbpPercentileWindow(
        station="KMIA",
        cycle_runtime_ns=cycle,
        valid_start_ns=_valid_00z_ns(day + dt.timedelta(days=1)),  # never real; see module note
        nbm_version_era="v5.0",
        percentiles=Percentiles(q10=86, q25=88, q50=90, q75=92, q90=94, mean=90, sd=3.0),
    )
    version_rows, gaps = nbp_skill_study.build_version_rows([early_but_wrong], {}, registry=_registry())
    assert version_rows == ()
    assert gaps == {"no_d1_window": 1}


# ---------------------------------------------------------------------------
# SL-8c: build_comparator_matched_events -- M0/M1/M2 + G2.0a wiring,
# keyed on `target_climate_day` (coordinator directive, never "the nearest
# window").
# ---------------------------------------------------------------------------


def _frozen_error_model() -> ForecastErrorModel:
    # A plain, un-loaded ForecastErrorModel is a valid `ForecastErrorModel`
    # for these join-shape tests -- they exercise the WIRING, not M0's own
    # frozen-artefact byte-equality (covered in test_nbp_calibration.py).
    return ForecastErrorModel()


def _comparator_window(
    *, station: str, cycle_runtime_ns: int, valid_start_ns: int, q50: float, sd: float = 3.0
) -> object:
    # `build_comparator_matched_events` now selects explicitly via
    # `climate_day_for_txn(valid_start_ns) == target_climate_day` (shared
    # `_select_d1_window`, DRY with `build_version_rows`) -- callers must
    # pass a REAL D+1 00Z valid_start_ns, never an arbitrary instant.
    from breezy.strategy.ladder_ev.quantile_density import Percentiles

    return nbp_skill_study.NbpPercentileWindow(
        station=station,
        cycle_runtime_ns=cycle_runtime_ns,
        valid_start_ns=valid_start_ns,
        nbm_version_era="v5.0",
        percentiles=Percentiles(
            q10=q50 - 4, q25=q50 - 2, q50=q50, q75=q50 + 2, q90=q50 + 4, mean=q50, sd=sd
        ),
    )


def test_build_comparator_matched_events_aligns_m0_m1_m2_on_the_same_event() -> None:
    registry = nbp_skill_study.station_registry()
    offset = registry.std_utc_offset_hours_by_icao["KMIA"]
    settlement_station = registry.settlement_station_by_icao["KMIA"]
    cycle_day = dt.date(2025, 6, 2)
    cycle = _cycle_runtime_ns(cycle_day, 1)  # 01Z
    climate_day = target_climate_day(cycle, offset)

    window = _comparator_window(
        station="KMIA",
        cycle_runtime_ns=cycle,
        valid_start_ns=_d1_valid_ns_for_01z(cycle_day),
        q50=90.0,
    )
    settlement = {
        (settlement_station, climate_day): _settlement_row(
            station=settlement_station, climate_day=climate_day, tmax_f=90
        )
    }
    mos_by_cycle = {("KMIA", cycle): nbp_skill_study.RawMosTxnXnd(txn_f=90.0, xnd_f=2.0)}

    events, report = nbp_skill_study.build_comparator_matched_events(
        [window], settlement, mos_by_cycle, {}, _frozen_error_model(), registry=registry
    )

    assert report.matched_events == 1
    assert report.non_qualifying_cycle_windows == 0
    assert report.unmapped_station_windows == 0
    assert report.holdout_excluded_windows == 0
    assert report.missing_settlement_rows == 0
    assert report.missing_raw_mos_rows == 0
    assert len(events) == 1
    event = events[0]
    # The SAME event key carries all three model probabilities.
    assert event.station == settlement_station
    assert event.climate_day == climate_day
    for p in (event.p_m0, event.p_m1, event.p_m2):
        assert 0.0 <= p <= 1.0
    assert event.near_midnight is None
    assert event.near_midnight_stratum is None


def test_build_comparator_matched_events_never_admits_a_holdout_event() -> None:
    registry = nbp_skill_study.station_registry()
    offset = registry.std_utc_offset_hours_by_icao["KMIA"]
    settlement_station = registry.settlement_station_by_icao["KMIA"]
    # Choose a cycle whose D+1 target lands ON the holdout start: for a 01Z
    # cycle at KMIA (UTC-5), local_standard_date shifts back one UTC day
    # (01:00Z - 5h = 20:00 the PREVIOUS UTC day), so a 01Z cycle stamped on
    # `holdout_start` itself has local_standard_date == holdout_start - 1
    # day, and target_climate_day (+1) lands exactly on holdout_start.
    holdout_start = DEFAULT_SPLITS.holdout_start
    cycle = _cycle_runtime_ns(holdout_start, 1)
    assert target_climate_day(cycle, offset) == holdout_start

    window = _comparator_window(
        station="KMIA",
        cycle_runtime_ns=cycle,
        valid_start_ns=_d1_valid_ns_for_01z(holdout_start),
        q50=90.0,
    )
    settlement = {
        (settlement_station, holdout_start): _settlement_row(
            station=settlement_station, climate_day=holdout_start, tmax_f=90
        )
    }
    mos_by_cycle = {("KMIA", cycle): nbp_skill_study.RawMosTxnXnd(txn_f=90.0, xnd_f=2.0)}

    events, report = nbp_skill_study.build_comparator_matched_events(
        [window], settlement, mos_by_cycle, {}, _frozen_error_model(), registry=registry
    )

    assert events == ()
    assert report.holdout_excluded_windows == 1
    assert all(event.climate_day < holdout_start for event in events)


def test_build_comparator_matched_events_counts_a_missing_raw_mos_row() -> None:
    registry = nbp_skill_study.station_registry()
    offset = registry.std_utc_offset_hours_by_icao["KMIA"]
    settlement_station = registry.settlement_station_by_icao["KMIA"]
    cycle_day = dt.date(2025, 6, 2)
    cycle = _cycle_runtime_ns(cycle_day, 1)
    climate_day = target_climate_day(cycle, offset)

    window = _comparator_window(
        station="KMIA",
        cycle_runtime_ns=cycle,
        valid_start_ns=_d1_valid_ns_for_01z(cycle_day),
        q50=90.0,
    )
    settlement = {
        (settlement_station, climate_day): _settlement_row(
            station=settlement_station, climate_day=climate_day, tmax_f=90
        )
    }

    events, report = nbp_skill_study.build_comparator_matched_events(
        [window], settlement, {}, {}, _frozen_error_model(), registry=registry
    )

    assert events == ()
    assert report.missing_raw_mos_rows == 1


def test_build_comparator_matched_events_carries_the_near_midnight_stratum() -> None:
    from breezy.analysis.nbp_comparator_models import DailyMaxInstant

    registry = nbp_skill_study.station_registry()
    offset = registry.std_utc_offset_hours_by_icao["KMIA"]
    settlement_station = registry.settlement_station_by_icao["KMIA"]
    cycle_day = dt.date(2025, 6, 2)
    cycle = _cycle_runtime_ns(cycle_day, 1)
    climate_day = target_climate_day(cycle, offset)

    window = _comparator_window(
        station="KMIA",
        cycle_runtime_ns=cycle,
        valid_start_ns=_d1_valid_ns_for_01z(cycle_day),
        q50=90.0,
    )
    settlement = {
        (settlement_station, climate_day): _settlement_row(
            station=settlement_station, climate_day=climate_day, tmax_f=90
        )
    }
    mos_by_cycle = {("KMIA", cycle): nbp_skill_study.RawMosTxnXnd(txn_f=90.0, xnd_f=2.0)}
    daily_max = {
        (settlement_station, climate_day): DailyMaxInstant(
            station=settlement_station,
            climate_day=climate_day,
            lst_seconds_from_midnight=1800,
            value_f=90.0,
            near_midnight=True,
        )
    }

    events, _report = nbp_skill_study.build_comparator_matched_events(
        [window], settlement, mos_by_cycle, daily_max, _frozen_error_model(), registry=registry
    )

    assert len(events) == 1
    assert events[0].near_midnight is True
    assert events[0].near_midnight_stratum == "KMIA"


def test_build_comparator_matched_events_selects_the_d1_window_at_every_station_and_hour() -> None:
    """CRITICAL fix (coordinator review 2026-09-29), shared selector
    (`_select_d1_window`, SL-8c rebase DRY directive): given BOTH the real
    D+1 MAX column and the real D+2 one (24h later) for a (station, cycle),
    `build_comparator_matched_events` must pick the D+1 one -- never
    "whichever window is in the list first". Settlement is pinned to the
    D+1 window's own q50 (70), so a wrong (D+2, q50=80) selection would
    flip the rung outcome to False rather than silently matching."""
    registry = nbp_skill_study.station_registry()
    day = dt.date(2025, 6, 2)

    for station in ("KLAX", "KMDW", "KMIA", "KSFO"):
        offset = registry.std_utc_offset_hours_by_icao[station]
        settlement_station = registry.settlement_station_by_icao[station]
        for hour, (first_lead, second_lead) in _REAL_FIRST_AND_SECOND_MAX_LEAD_HOURS.items():
            cycle = _cycle_runtime_ns(day, hour)
            climate_day = target_climate_day(cycle, offset)
            cycle_dt = dt.datetime(day.year, day.month, day.day, hour, tzinfo=dt.UTC)
            first_ns = int((cycle_dt + dt.timedelta(hours=first_lead)).timestamp()) * _NS
            second_ns = int((cycle_dt + dt.timedelta(hours=second_lead)).timestamp()) * _NS

            d1_window = _comparator_window(
                station=station, cycle_runtime_ns=cycle, valid_start_ns=first_ns, q50=70.0
            )
            d2_window = _comparator_window(
                station=station, cycle_runtime_ns=cycle, valid_start_ns=second_ns, q50=80.0
            )
            settlement = {
                (settlement_station, climate_day): _settlement_row(
                    station=settlement_station, climate_day=climate_day, tmax_f=70
                )
            }
            mos_by_cycle = {
                (station, cycle): nbp_skill_study.RawMosTxnXnd(txn_f=70.0, xnd_f=2.0)
            }

            events, report = nbp_skill_study.build_comparator_matched_events(
                [d1_window, d2_window],
                settlement,
                mos_by_cycle,
                {},
                _frozen_error_model(),
                registry=registry,
            )

            assert report.no_d1_window_cycles == 0, f"{station} {hour}Z"
            assert len(events) == 1, f"{station} {hour}Z"
            assert events[0].outcome is True, (
                f"{station} {hour}Z: selected the D+2 (q50=80) window instead of D+1 (q50=70)"
            )


def test_build_comparator_matched_events_counts_a_cycle_with_no_d1_window() -> None:
    registry = nbp_skill_study.station_registry()
    day = dt.date(2025, 6, 2)
    cycle = _cycle_runtime_ns(day, 13)
    # Only a (wrong-day) window is present -- no candidate maps to the
    # explicit D+1 target, so the cycle must be dropped and counted, never
    # approximated by "nearest".
    wrong_day_ns = _valid_00z_ns(day + dt.timedelta(days=1))
    window = _comparator_window(
        station="KMIA", cycle_runtime_ns=cycle, valid_start_ns=wrong_day_ns, q50=70.0
    )

    events, report = nbp_skill_study.build_comparator_matched_events(
        [window], {}, {}, {}, _frozen_error_model(), registry=registry
    )

    assert events == ()
    assert report.no_d1_window_cycles == 1


# ---------------------------------------------------------------------------
# SL-8d: validate-stage calibrated M2 + gates.
# ---------------------------------------------------------------------------


def _fit_with_params(
    *,
    version: str = "v4.3",
    a: float = 0.0,
    gamma: float = 0.0,
    delta: float = 1.0,
    converged: bool = True,
) -> calib.CalibrationFit:
    point = EmosParams(a=a, gamma=gamma, delta=delta)
    estimate = calib.VersionEstimate(
        version=version,
        a=a,
        gamma=gamma,
        n=8,
        converged=converged,
        nfev=3,
    )
    selection = calib.KappaSelection(
        chosen_kappa=30.0,
        curve=(calib.KappaScore(kappa=30.0, mean_crps=1.0),),
    )
    return calib.CalibrationFit(
        delta=delta,
        delta_converged=converged,
        delta_nfev=5,
        hierarchical=calib.HierarchicalEmosResult(
            method=CdfMethod.NORMAL,
            delta=delta,
            kappa_selection=selection,
            tau_sensitivity=selection,
            shrunk_by_version={version: estimate},
            draws_by_version={
                version: calib.VersionEmosDraws(version=version, point=point, draws=(point,))
            },
        ),
    )


def _version_row(
    *,
    split: str,
    climate_day: dt.date,
    version: str = "v4.3",
    station: str = "MIA",
    q50: float = 90.0,
    cli_tmax_f: float = 90.0,
) -> calib.VersionRow:
    return calib.VersionRow(
        version=version,
        split=split,
        station=station,
        climate_day=climate_day,
        percentiles=Percentiles(
            q10=q50 - 4.0,
            q25=q50 - 2.0,
            q50=q50,
            q75=q50 + 2.0,
            q90=q50 + 4.0,
            mean=q50,
            sd=3.0,
        ),
        cli_tmax_f=cli_tmax_f,
    )


def _comparator_event(
    *,
    split: str,
    climate_day: dt.date,
    version: str = "v4.3",
    station: str = "MIA",
    q50: float = 90.0,
    outcome: bool = True,
    near_midnight: bool | None = None,
    near_midnight_stratum: str | None = None,
) -> NbpComparatorMatchedEvent:
    return cast(
        NbpComparatorMatchedEvent,
        nbp_skill_study.ComparatorMatchedEvent(
            station=station,
            climate_day=climate_day,
            split=split,
            version=version,
            percentiles=Percentiles(
                q10=q50 - 4.0,
                q25=q50 - 2.0,
                q50=q50,
                q75=q50 + 2.0,
                q90=q50 + 4.0,
                mean=q50,
                sd=3.0,
            ),
            rung_id="mid",
            p_m0=0.40,
            p_m1=0.45,
            p_m2=0.50,
            cli_tmax_f=q50,
            outcome=outcome,
            near_midnight=near_midnight,
            near_midnight_stratum=near_midnight_stratum,
        ),
    )


def test_calibrated_m2_uses_fitted_params_and_not_the_uncalibrated_placeholder() -> None:
    percentiles = Percentiles(q10=66, q25=68, q50=70, q75=72, q90=74, mean=70, sd=3)
    ladder = nbp_skill_study._forecast_centered_ladder(70)
    placeholder = rung_probabilities(build_cdf(CdfMethod.NORMAL, percentiles), ladder)["mid"]

    identity = nbp_skill_study.calibrated_m2_rung_probabilities(
        percentiles=percentiles,
        version="v4.3",
        calibration_fit=_fit_with_params(a=0.0),
        rungs=ladder,
        cdf_method=CdfMethod.NORMAL,
    )["mid"]
    shifted = nbp_skill_study.calibrated_m2_rung_probabilities(
        percentiles=percentiles,
        version="v4.3",
        calibration_fit=_fit_with_params(a=5.0),
        rungs=ladder,
        cdf_method=CdfMethod.NORMAL,
    )["mid"]

    assert identity == pytest.approx(placeholder)
    assert shifted != pytest.approx(identity)
    assert shifted != pytest.approx(placeholder)


def test_validate_gate_events_preserve_identical_event_keys_across_m0_m1_and_m2() -> None:
    event = _comparator_event(split="validate", climate_day=dt.date(2025, 6, 3))

    matched = nbp_skill_study.validate_gate_events_from_comparator_events(
        [event],
        calibration_fit=_fit_with_params(a=2.0),
        cdf_method=CdfMethod.NORMAL,
    )

    assert len(matched) == 1
    assert (matched[0].station, matched[0].climate_day) == (event.station, event.climate_day)
    assert matched[0].p_m0 == pytest.approx(event.p_m0)
    assert matched[0].p_m1 == pytest.approx(event.p_m1)
    assert matched[0].p_m2 != pytest.approx(event.p_m2)


def test_validate_gate_runner_filters_holdout_rows_before_any_gate() -> None:
    result = nbp_skill_study.run_validate_gates_from_rows(
        version_rows=[
            _version_row(split="train", climate_day=dt.date(2024, 1, 1)),
            _version_row(split="validate", climate_day=dt.date(2025, 6, 3)),
            _version_row(split="holdout", climate_day=DEFAULT_SPLITS.holdout_start),
        ],
        comparator_events=[
            _comparator_event(split="validate", climate_day=dt.date(2025, 6, 3)),
            _comparator_event(split="holdout", climate_day=DEFAULT_SPLITS.holdout_start),
        ],
        calibration_fit=_fit_with_params(),
        artefact_dir=Path("/tmp/nbp-synthetic-no-write"),
        bootstrap_iterations=3,
        write_candidate_artefact=False,
    )

    assert result["coverage_counts"]["validate_version_rows"] == 1
    assert result["coverage_counts"]["validate_comparator_events"] == 1
    assert result["coverage_counts"]["holdout_version_rows_filtered"] == 1
    assert result["coverage_counts"]["holdout_comparator_events_filtered"] == 1
    assert result["coverage_counts"]["gate_climate_day_max"] < DEFAULT_SPLITS.holdout_start.isoformat()


def test_validate_gate_runner_filters_mistagged_holdout_climate_day_before_fit_and_gates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_fit_rows: list[calib.VersionRow] = []

    def fake_fit_calibration(
        rows: Sequence[calib.VersionRow], *, method: CdfMethod
    ) -> calib.CalibrationFit:
        captured_fit_rows.extend(rows)
        return _fit_with_params()

    monkeypatch.setattr(nbp_skill_study, "fit_calibration", fake_fit_calibration)

    result = nbp_skill_study.run_validate_gates_from_rows(
        version_rows=[
            _version_row(split="train", climate_day=dt.date(2024, 1, 1)),
            _version_row(split="validate", climate_day=dt.date(2025, 6, 3)),
            _version_row(split="validate", climate_day=DEFAULT_SPLITS.holdout_start),
        ],
        comparator_events=[
            _comparator_event(split="validate", climate_day=dt.date(2025, 6, 3)),
            _comparator_event(split="validate", climate_day=DEFAULT_SPLITS.holdout_start),
        ],
        artefact_dir=Path("/tmp/nbp-synthetic-no-write"),
        bootstrap_iterations=3,
        write_candidate_artefact=False,
    )

    # Item 1 only (item 2 was corrected by the coordinator: validate rows are
    # NOT excluded from the fit -- v4.2/v4.3 are fitted on their own
    # validation rows by plan design, plan S2.2). Only the row dated on/after
    # the holdout start is ever dropped, regardless of its `split` tag.
    assert sorted(row.climate_day for row in captured_fit_rows) == [
        dt.date(2024, 1, 1),
        dt.date(2025, 6, 3),
    ]
    assert result["coverage_counts"]["validate_version_rows"] == 1
    assert result["coverage_counts"]["validate_comparator_events"] == 1
    assert result["coverage_counts"]["holdout_version_rows_filtered"] == 1
    assert result["coverage_counts"]["holdout_comparator_events_filtered"] == 1
    assert result["coverage_counts"]["gate_climate_day_max"] < DEFAULT_SPLITS.holdout_start.isoformat()


def test_fit_calibration_receives_every_pre_holdout_row_per_plan_s2_2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Coordinator correction (SL-8d item 2): plan S2.2, quoted verbatim in
    `run_validate_gates_from_rows`, fits v4.2 on its own validation rows
    (before 2025-05-27) and v4.3 on its own validation rows, train-era
    versions on train, and v5.0 on the v5.0 fit slice -- so the fit sees
    EVERY pre-holdout row, never a subset that excludes VALIDATE. Only
    holdout-dated rows (item 1) are ever dropped before the fit."""
    captured_fit_rows: list[calib.VersionRow] = []

    def fake_fit_calibration(
        rows: Sequence[calib.VersionRow], *, method: CdfMethod
    ) -> calib.CalibrationFit:
        captured_fit_rows.extend(rows)
        return _fit_with_versions("v4.1", "v4.2", "v4.3", "v5.0")

    monkeypatch.setattr(nbp_skill_study, "fit_calibration", fake_fit_calibration)

    nbp_skill_study.run_validate_gates_from_rows(
        version_rows=[
            _version_row(split="train", version="v4.1", climate_day=dt.date(2024, 1, 1)),
            _version_row(split="validate", version="v4.2", climate_day=dt.date(2025, 3, 1)),
            _version_row(split="validate", version="v4.3", climate_day=dt.date(2025, 6, 3)),
            _version_row(split="v5_fit_slice", version="v5.0", climate_day=dt.date(2026, 6, 1)),
        ],
        comparator_events=[],
        artefact_dir=Path("/tmp/nbp-synthetic-no-write"),
        bootstrap_iterations=3,
        write_candidate_artefact=False,
    )

    assert {row.version for row in captured_fit_rows} == {"v4.1", "v4.2", "v4.3", "v5.0"}
    assert {row.split for row in captured_fit_rows} == {"train", "validate", "v5_fit_slice"}


def test_train_era_version_shrunk_estimate_is_its_own_unshrunk_train_fit() -> None:
    """A train-era version's point estimate is fitted UNSHRUNK on its OWN
    train rows alone (plan S2.2; `nbp_calibration` review item 4) -- adding
    MORE validation-era versions to the same calibration run must never move
    it, proving train-era versions never see validation rows."""
    from breezy.analysis.nbp_calibration import fit_calibration as real_fit_calibration

    train_only_rows = [
        _version_row(
            split="train", version="v4.1", climate_day=dt.date(2024, 1, d), cli_tmax_f=88.0 + d
        )
        for d in range(1, 7)
    ]
    validate_rows_v42 = [
        _version_row(
            split="validate", version="v4.2", climate_day=dt.date(2025, 2, d), cli_tmax_f=70.0 + d
        )
        for d in range(1, 7)
    ]
    validate_rows_v43 = [
        _version_row(
            split="validate", version="v4.3", climate_day=dt.date(2025, 6, d), cli_tmax_f=90.0 + d
        )
        for d in range(1, 7)
    ]
    v5_fit_slice_rows = [
        _version_row(
            split="v5_fit_slice", version="v5.0", climate_day=dt.date(2026, 6, d), cli_tmax_f=95.0 + d
        )
        for d in range(1, 7)
    ]

    # `bootstrap_draws=1, resample_delta=False`: this test only checks the
    # POINT estimate, never the bootstrap interval, so the (expensive, and
    # here irrelevant) per-draw delta refit is skipped.
    baseline = real_fit_calibration(
        [*train_only_rows, *validate_rows_v42, *validate_rows_v43],
        method=CdfMethod.NORMAL,
        bootstrap_draws=1,
        resample_delta=False,
    )
    with_more_versions = real_fit_calibration(
        [*train_only_rows, *validate_rows_v42, *validate_rows_v43, *v5_fit_slice_rows],
        method=CdfMethod.NORMAL,
        bootstrap_draws=1,
        resample_delta=False,
    )

    before = baseline.hierarchical.shrunk_by_version["v4.1"]
    after = with_more_versions.hierarchical.shrunk_by_version["v4.1"]
    assert before.a == pytest.approx(after.a)
    assert before.gamma == pytest.approx(after.gamma)


def _fit_with_versions(*versions: str) -> calib.CalibrationFit:
    """Like `_fit_with_params` but with an arbitrary set of fitted versions
    -- needed to score comparator/version rows tagged with more than one
    version against a single hand-built fit."""
    point = EmosParams(a=0.0, gamma=0.0, delta=1.0)
    shrunk = {
        version: calib.VersionEstimate(version=version, a=0.0, gamma=0.0, n=8, converged=True, nfev=3)
        for version in versions
    }
    draws_by_version = {
        version: calib.VersionEmosDraws(version=version, point=point, draws=(point,))
        for version in versions
    }
    selection = calib.KappaSelection(
        chosen_kappa=30.0, curve=(calib.KappaScore(kappa=30.0, mean_crps=1.0),)
    )
    return calib.CalibrationFit(
        delta=1.0,
        delta_converged=True,
        delta_nfev=5,
        hierarchical=calib.HierarchicalEmosResult(
            method=CdfMethod.NORMAL,
            delta=1.0,
            kappa_selection=selection,
            tau_sensitivity=selection,
            shrunk_by_version=shrunk,
            draws_by_version=draws_by_version,
        ),
    )


def test_g21_g22_g23_report_all_and_out_of_sample_with_labels(tmp_path: Path) -> None:
    """Coordinator correction (SL-8d item 2b): G2.1/G2.2/G2.3 are reported
    TWICE -- once over ALL validate rows (labelled in-sample, since by plan
    design a version's own validation rows both fit and score it: "Scoring
    validation rows that a version was fitted on is by design at this
    stage"), and once over OUT-OF-SAMPLE validate rows only: comparator
    events whose version had NO validation-split row in the fit input."""
    fit = _fit_with_versions("v4.3", "v4.1")

    result = nbp_skill_study.run_validate_gates_from_rows(
        version_rows=[
            _version_row(split="train", version="v4.1", climate_day=dt.date(2024, 1, 1)),
            _version_row(split="validate", version="v4.3", climate_day=dt.date(2025, 6, 3)),
        ],
        comparator_events=[
            _comparator_event(split="validate", version="v4.3", climate_day=dt.date(2025, 6, 3)),
            _comparator_event(split="validate", version="v4.1", climate_day=dt.date(2025, 6, 4)),
        ],
        calibration_fit=fit,
        artefact_dir=Path("/tmp/nbp-synthetic-no-write"),
        bootstrap_iterations=3,
        write_candidate_artefact=False,
    )

    in_sample_label = "in-sample (by plan design) -- diagnostic only"
    assert result["gates"]["G2.2"]["n"] == 2
    assert result["gates"]["G2.2"]["statistics"]["sample_label"] == in_sample_label
    assert result["gates"]["G2.3"]["n"] == 2
    assert result["gates"]["G2.3"]["statistics"]["sample_label"] == in_sample_label
    assert result["gates"]["G2.1"]["statistics"]["sample_label"] == in_sample_label

    assert result["gates"]["G2.2_out_of_sample"]["n"] == 1
    assert result["gates"]["G2.2_out_of_sample"]["statistics"]["sample_label"] == "out-of-sample"
    assert result["gates"]["G2.3_out_of_sample"]["n"] == 1
    assert result["gates"]["G2.3_out_of_sample"]["statistics"]["sample_label"] == "out-of-sample"
    assert result["gates"]["G2.1_out_of_sample"]["statistics"]["sample_label"] == "out-of-sample"

    note = nbp_skill_study.write_validate_evidence_note(
        result, date=dt.date(2026, 9, 30), evidence_dir=tmp_path
    )
    note_text = note.read_text(encoding="utf-8")
    assert in_sample_label in note_text
    assert "out-of-sample" in note_text
    assert "G2.2_out_of_sample" in note_text
    assert note.parent == tmp_path
    note.unlink()


def test_g20_holm_family_combines_months_daylength_terciles_and_near_midnight_strata() -> None:
    version_rows: list[calib.VersionRow] = [
        _version_row(split="train", station="MDW", climate_day=dt.date(2024, 1, 1)),
        _version_row(split="train", station="MDW", climate_day=dt.date(2024, 6, 1)),
        _version_row(split="train", station="MIA", climate_day=dt.date(2024, 9, 1)),
    ]
    for month in range(1, 13):
        for i in range(60):
            day = dt.date(2025, month, (i % 20) + 1)
            station = ("MIA", "MDW", "SFO", "LAX")[i % 4]
            version_rows.append(
                _version_row(
                    split="validate",
                    station=station,
                    climate_day=day,
                    q50=70.0,
                    cli_tmax_f=70.0 + float((i % 5) - 2),
                )
            )

    comparator_events: list[NbpComparatorMatchedEvent] = []
    for station, stratum in (("MIA", "KMIA"), ("MDW", "KMDW"), ("SFO", "KLAX_KSFO_POOLED")):
        for i in range(60):
            comparator_events.append(
                _comparator_event(
                    split="validate",
                    station=station,
                    climate_day=dt.date(2025, 6, (i % 20) + 1),
                    near_midnight=True,
                    near_midnight_stratum=stratum,
                )
            )

    result = nbp_skill_study.run_validate_gates_from_rows(
        version_rows=version_rows,
        comparator_events=comparator_events,
        calibration_fit=_fit_with_params(),
        artefact_dir=Path("/tmp/nbp-synthetic-no-write"),
        bootstrap_iterations=3,
        write_candidate_artefact=False,
    )

    assert result["gates"]["G2.0"]["statistics"]["holm_family_size"] == 18
    assert result["gates"]["G2.0a"]["statistics"]["holm_family_size"] == 18
    assert len(result["gates"]["G2.0"]["groups"]) == 15
    assert len(result["gates"]["G2.0a"]["groups"]) == 3


def test_validation_power_metadata_and_shrinkage_weights_are_emitted(tmp_path: Path) -> None:
    events = [
        calib.MatchedEvent(
            station="MIA",
            climate_day=dt.date(2025, 6, 1),
            p_m2=1.0,
            p_m1=0.0,
            p_m0=0.0,
            outcome=True,
        ),
        calib.MatchedEvent(
            station="MIA",
            climate_day=dt.date(2025, 6, 2),
            p_m2=1.0,
            p_m1=0.0,
            p_m0=0.0,
            outcome=False,
        ),
    ]

    power = nbp_skill_study._validation_power_metadata(events)
    assert power["sigma_d"] > 0.0
    assert power["sigma_d_ci"][0] >= 0.0
    assert power["sigma_d_ci"][1] >= power["sigma_d_ci"][0]
    assert power["n_min"] > 520
    assert power["n_min_range"][1] >= power["n_min_range"][0]
    assert power["status"] == "PMUS_INFEASIBLE_ROUTE_NODE4"
    assert power["n_min_range_status"] in {
        "FEASIBILITY_UNDETERMINED",
        "PMUS_INFEASIBLE_ROUTE_NODE4",
    }

    result = nbp_skill_study.run_validate_gates_from_rows(
        version_rows=[
            _version_row(split="train", climate_day=dt.date(2024, 1, 1)),
            _version_row(split="validate", climate_day=dt.date(2025, 6, 3)),
        ],
        comparator_events=[
            _comparator_event(split="validate", climate_day=dt.date(2025, 6, 3)),
        ],
        calibration_fit=_fit_with_params(),
        artefact_dir=tmp_path,
        bootstrap_iterations=3,
        write_candidate_artefact=False,
    )

    assert result["power"]["sigma_d"] == pytest.approx(0.0)
    assert result["power"]["sigma_d_ci"] == [0.0, 0.0]
    assert result["power"]["n_min"] == 0
    assert result["power"]["n_min_range"] == [0, 0]
    assert result["power"]["status"] == "OK"
    assert result["power"]["n_min_range_status"] == "OK"
    assert result["shrinkage_weights"] == {"v4.3": pytest.approx(8.0 / 38.0)}

    note = nbp_skill_study.write_validate_evidence_note(
        result, date=dt.date(2026, 9, 30), evidence_dir=tmp_path
    )
    note_text = note.read_text(encoding="utf-8")
    assert "sigma_d" in note_text
    assert "sigma_d_ci" in note_text
    assert "n_min" in note_text
    assert "n_min_range" in note_text
    assert "n_min_range_status" in note_text
    assert "shrinkage_weights" in note_text
    assert note.parent == tmp_path
    note.unlink()


def test_validate_runner_does_not_modify_repo_docs_evidence(tmp_path: Path) -> None:
    """The validate runner and evidence-note writer must not touch the repo tree.

    Snapshot is names plus mtime_ns and size, so an overwrite of the committed
    note or a new NBP_S2_VALIDATE_RESULT_*.md fails even if the name survives.
    """
    evidence_root = _REPO_ROOT / "docs" / "evidence"

    def snapshot() -> tuple[tuple[str, int, int], ...]:
        recorded: list[tuple[str, int, int]] = []
        for path in sorted(evidence_root.iterdir(), key=lambda item: item.name):
            st = path.stat()
            recorded.append((path.name, st.st_mtime_ns, st.st_size))
        return tuple(recorded)

    before = snapshot()
    nbp_skill_study.run_validate(
        nbp_derived_root=tmp_path / "nbp",
        settlement_truth_parquet=tmp_path / "missing.parquet",
        archive_root=tmp_path / "archive",
    )
    note = nbp_skill_study.write_validate_evidence_note(
        {"fit_status": "OK", "gates": {}},
        date=dt.date(2026, 9, 30),
        evidence_dir=tmp_path,
    )

    assert note == tmp_path / "NBP_S2_VALIDATE_RESULT_2026-09-30.md"
    assert note.is_file()
    assert snapshot() == before


def test_validation_power_metadata_bootstrap_is_deterministic_and_flags_straddle() -> None:
    events = [
        calib.MatchedEvent(
            station="K",
            climate_day=dt.date(2025, 1, 1) + dt.timedelta(days=i),
            p_m2=math.sqrt(0.26 if i % 2 else 0.0),
            p_m1=0.0,
            p_m0=0.0,
            outcome=False,
        )
        for i in range(40)
    ]

    first = nbp_skill_study._validation_power_metadata(events)
    second = nbp_skill_study._validation_power_metadata(events)

    assert first == second
    assert first["status"] == "PMUS_INFEASIBLE_ROUTE_NODE4"
    assert first["n_min_range"][0] <= 520 < first["n_min_range"][1]
    assert first["n_min_range_status"] == "FEASIBILITY_UNDETERMINED"


def test_validate_payload_emits_pooling_in_sample_versions_and_fit_provenance(
    tmp_path: Path,
) -> None:
    fit = _fit_with_versions("v4.1", "v4.3")
    result = nbp_skill_study.run_validate_gates_from_rows(
        version_rows=[
            _version_row(split="train", version="v4.1", climate_day=dt.date(2024, 1, 1)),
            _version_row(split="train", version="v4.1", climate_day=dt.date(2024, 1, 2)),
            _version_row(split="validate", version="v4.3", climate_day=dt.date(2025, 6, 3)),
        ],
        comparator_events=[
            _comparator_event(split="validate", version="v4.3", climate_day=dt.date(2025, 6, 3)),
            _comparator_event(split="validate", version="v4.1", climate_day=dt.date(2025, 6, 4)),
        ],
        calibration_fit=fit,
        artefact_dir=tmp_path,
        bootstrap_iterations=3,
        write_candidate_artefact=False,
    )

    assert result["pooling"] == "partial"
    assert result["in_sample_versions"] == ["v4.3"]
    assert result["fit_provenance"]["v4.1"]["train"]["rows"] == 2
    assert result["fit_provenance"]["v4.3"]["validate"]["rows"] == 1
    assert result["effective_params_source"]["v4.1"] == "train_unshrunk"
    assert result["effective_params_source"]["v4.3"] == "validation_or_v5_fit_shrunk"


def test_candidate_artefact_round_trips_selected_correction_and_recalibration(
    tmp_path: Path,
) -> None:
    result = nbp_skill_study.run_validate_gates_from_rows(
        version_rows=[
            _version_row(split="train", climate_day=dt.date(2024, 1, 1)),
        ],
        comparator_events=[
            _comparator_event(split="train", climate_day=dt.date(2024, 1, 1), outcome=False),
            _comparator_event(split="train", climate_day=dt.date(2024, 1, 2), outcome=True),
            _comparator_event(split="validate", climate_day=dt.date(2025, 6, 1), outcome=False),
            _comparator_event(split="validate", climate_day=dt.date(2025, 6, 2), outcome=True),
        ],
        calibration_fit=_fit_with_params(),
        artefact_dir=tmp_path,
        bootstrap_iterations=3,
        write_candidate_artefact=True,
    )

    written = json.loads(Path(result["artefact"]["path"]).read_text(encoding="utf-8"))
    assert written["correction_form"] == result["correction"]["form"]
    assert written["recalibration"] == result["recalibration"]["form"]
    assert "correction_month_offsets" in written
    assert "recalibration_affine" in written


def test_write_candidate_artefact_threads_measured_power_metadata_not_hardcoded_zero(
    tmp_path: Path,
) -> None:
    """SL-8d review item 4: the persisted candidate artefact's `n_min`/
    `sigma_d` come from the SAME measured `power` metadata the payload
    reports -- never the hard-coded `n_min=0, sigma_d=0.0` placeholder."""
    result = nbp_skill_study.run_validate_gates_from_rows(
        version_rows=[
            _version_row(split="train", climate_day=dt.date(2024, 1, 1)),
        ],
        comparator_events=[
            _comparator_event(split="validate", climate_day=dt.date(2025, 6, 1), outcome=True),
            _comparator_event(split="validate", climate_day=dt.date(2025, 6, 2), outcome=False),
        ],
        calibration_fit=_fit_with_params(),
        artefact_dir=tmp_path,
        bootstrap_iterations=3,
        write_candidate_artefact=True,
    )

    assert result["power"]["sigma_d"] > 0.0
    assert result["power"]["n_min"] > 0
    assert result["artefact"]["path"] is not None
    written = json.loads(Path(result["artefact"]["path"]).read_text(encoding="utf-8"))
    assert written["n_min"] == result["power"]["n_min"]
    assert written["sigma_d"] == pytest.approx(result["power"]["sigma_d"])
    assert written["n_min"] != 0


def test_daylight_hours_refuses_unknown_station_instead_of_using_latitude_fallback() -> None:
    with pytest.raises(ValueError, match="unknown station"):
        nbp_skill_study._daylight_hours("KDEN", dt.date(2025, 6, 1))


def test_validate_gate_runner_reports_untested_gate_below_threshold_never_pass() -> None:
    result = nbp_skill_study.run_validate_gates_from_rows(
        version_rows=[
            _version_row(split="train", climate_day=dt.date(2024, 1, 1)),
            _version_row(split="validate", climate_day=dt.date(2025, 6, 3)),
        ],
        comparator_events=[
            _comparator_event(split="validate", climate_day=dt.date(2025, 6, 3)),
        ],
        calibration_fit=_fit_with_params(),
        artefact_dir=Path("/tmp/nbp-synthetic-no-write"),
        bootstrap_iterations=3,
        write_candidate_artefact=False,
    )

    assert result["gates"]["G2.0"]["status"] == "UNTESTED"
    assert result["gates"]["G2.0"]["status"] != "PASS"
    assert result["gates"]["G2.1"]["status"] == "UNTESTED"
    assert result["gates"]["G2.1"]["status"] != "PASS"


def test_validate_gate_runner_non_converged_fit_blocks_gates_and_artefact(tmp_path: Path) -> None:
    artefact_dir = tmp_path / "derived"
    result = nbp_skill_study.run_validate_gates_from_rows(
        version_rows=[
            _version_row(split="train", climate_day=dt.date(2024, 1, 1)),
            _version_row(split="validate", climate_day=dt.date(2025, 6, 3)),
        ],
        comparator_events=[
            _comparator_event(split="validate", climate_day=dt.date(2025, 6, 3)),
        ],
        calibration_fit=_fit_with_params(converged=False),
        artefact_dir=artefact_dir,
        bootstrap_iterations=3,
        write_candidate_artefact=True,
    )

    assert result["fit_status"] == "FIT_NOT_CONVERGED"
    assert result["artefact"]["path"] is None
    assert result["artefact"]["sha256"] is None
    assert not list(artefact_dir.glob("*.json"))


# ---------------------------------------------------------------------------
# mos_txn_xnd_by_cycle -- real archive-cache read (seeded via get_or_fetch).
# ---------------------------------------------------------------------------


class _FixedClock:
    def timestamp_ns(self) -> int:
        return 0


def _seed_mos_archive(tmp_path: Path, *, station: str, body: bytes) -> Path:
    archive_root = tmp_path / "archive"
    request = ArchiveRequest(
        source=IEM_MOS_SOURCE,
        station=station,
        product="mos-nbs",
        window_start=0,
        window_end=10**18,
        model="NBS",
    )
    cache = ArchiveCache(
        root=archive_root / IEM_MOS_SOURCE, fetch=lambda _req: body, clock=_FixedClock()
    )
    cache.get_or_fetch(request)
    return archive_root


def test_mos_txn_xnd_by_cycle_reads_a_real_seeded_archive_entry(tmp_path: Path) -> None:
    # KMIA (UTC-5), 01Z cycle on 2025-06-02: local_standard_date shifts back
    # one UTC day (01:00Z - 5h = 20:00 the PREVIOUS UTC day, 2025-06-01), so
    # target_climate_day = 2025-06-01 + 1 = 2025-06-02. The ONLY valid
    # daily-max ftime hour is 00Z (`TXN_MAX_PERIOD_END_UTC_HOUR`), and 00Z on
    # 2025-06-03 maps back to climate_day 2025-06-02 (00:00Z - 5h = 19:00 on
    # 2025-06-02) -- the matching row, at 23h lead (the "nearest" 00Z after a
    # 01Z cycle IS correct; only 13Z/19Z need the one AFTER nearest).
    body = (
        b"station,runtime,ftime,txn,xnd\n"
        b"KMIA,2025-06-02 01:00:00,2025-06-03 00:00:00,90,2.0\n"
    )
    archive_root = _seed_mos_archive(tmp_path, station="KMIA", body=body)
    registry = nbp_skill_study.station_registry()

    result = nbp_skill_study.mos_txn_xnd_by_cycle(
        archive_root=archive_root, registry=registry, stations=("KMIA",)
    )

    cycle_ns = _cycle_runtime_ns(dt.date(2025, 6, 2), 1)
    key = ("KMIA", cycle_ns)
    assert key in result
    assert result[key].txn_f == pytest.approx(90.0)
    assert result[key].xnd_f == pytest.approx(2.0)


def test_mos_txn_xnd_by_cycle_selects_the_target_day_row_at_every_station_and_hour(
    tmp_path: Path,
) -> None:
    """CRITICAL fix (coordinator review 2026-09-29), all 4 stations,
    13Z/19Z/01Z, using the REAL observed MOS/NBS lead-hour grid (a
    full-archive scan of the real on-disk cache; see
    `_REAL_FIRST_AND_SECOND_MAX_LEAD_HOURS`). Real MOS never publishes a
    same-cycle-day 00Z ``txn`` row for 13Z/19Z -- the shortest available MAX
    lead is 35h/29h -- so the correction is not "pick the non-nearest row"
    but "verify explicitly rather than trust proximity": the explicit
    `climate_day_for_txn` selection must pick the FIRST real MAX column
    (which also happens to be nearest) and reject the SECOND real one (24h
    later, D+2), for every station and cycle hour.
    """
    from forecast_climate_day_map import climate_day_for_txn

    registry = nbp_skill_study.station_registry()
    day = dt.date(2025, 6, 2)

    for station in ("KLAX", "KMDW", "KMIA", "KSFO"):
        offset = registry.std_utc_offset_hours_by_icao[station]
        for hour, (first_lead, second_lead) in _REAL_FIRST_AND_SECOND_MAX_LEAD_HOURS.items():
            cycle_ns = _cycle_runtime_ns(day, hour)
            target = target_climate_day(cycle_ns, offset)
            cycle_dt = dt.datetime(day.year, day.month, day.day, hour, tzinfo=dt.UTC)
            first_00z = cycle_dt + dt.timedelta(hours=first_lead)
            second_00z = cycle_dt + dt.timedelta(hours=second_lead)

            body = (
                b"station,runtime,ftime,txn,xnd\n"
                + f"{station},{cycle_dt:%Y-%m-%d %H:%M:%S},"
                f"{first_00z:%Y-%m-%d %H:%M:%S},77,3.0\n".encode()
                + f"{station},{cycle_dt:%Y-%m-%d %H:%M:%S},"
                f"{second_00z:%Y-%m-%d %H:%M:%S},88,4.0\n".encode()
            )
            archive_root = _seed_mos_archive(
                tmp_path / f"{station}-h{hour}", station=station, body=body
            )

            result = nbp_skill_study.mos_txn_xnd_by_cycle(
                archive_root=archive_root, registry=registry, stations=(station,)
            )

            key = (station, cycle_ns)
            assert key in result, f"{station} {hour}Z: no D+1-matching row found"
            mapped_day = climate_day_for_txn(
                icao=station,
                runtime_ns=cycle_ns,
                ftime_ns=int(first_00z.timestamp()) * _NS,
                std_utc_offset_hours=offset,
                model="NBS",
                kind="max",
            )
            assert mapped_day == target, f"{station} {hour}Z: first real MAX column is not D+1"
            # The FIRST real MAX column is correct here; the SECOND (24h
            # later, a real D+2 column) must be rejected.
            assert result[key].txn_f == pytest.approx(77.0), (
                f"{station} {hour}Z: selected the D+2 column instead of the D+1 one"
            )
            assert result[key].xnd_f == pytest.approx(3.0)


def test_mos_txn_xnd_by_cycle_over_a_missing_archive_root_is_empty(tmp_path: Path) -> None:
    registry = nbp_skill_study.station_registry()
    result = nbp_skill_study.mos_txn_xnd_by_cycle(
        archive_root=tmp_path / "does-not-exist", registry=registry
    )
    assert result == {}


def test_daily_max_instants_over_a_missing_archive_root_is_empty(tmp_path: Path) -> None:
    registry = nbp_skill_study.station_registry()
    result = nbp_skill_study.daily_max_instants(
        archive_root=tmp_path / "does-not-exist", registry=registry
    )
    assert result == {}


def _seed_asos_archive(tmp_path: Path, *, station: str, body: bytes) -> Path:
    from breezy.persistence.archive_cache import IEM_ASOS_1MIN_SOURCE

    archive_root = tmp_path / "archive"
    request = ArchiveRequest(
        source=IEM_ASOS_1MIN_SOURCE,
        station=station,
        product="asos-1min",
        window_start=0,
        window_end=10**18,
        model=None,
    )
    cache = ArchiveCache(
        root=archive_root / IEM_ASOS_1MIN_SOURCE, fetch=lambda _req: body, clock=_FixedClock()
    )
    cache.get_or_fetch(request)
    return archive_root


def test_daily_max_instants_reads_a_real_seeded_archive_entry(tmp_path: Path) -> None:
    registry = nbp_skill_study.station_registry()
    body = (
        b"valid(UTC),tmpf\n"
        b"2025-06-01 20:00,88\n"
        b"2025-06-01 21:00,90\n"
        b"2025-06-01 22:00,89\n"
    )
    archive_root = _seed_asos_archive(tmp_path, station="KMIA", body=body)

    result = nbp_skill_study.daily_max_instants(archive_root=archive_root, registry=registry)

    settlement_station = registry.settlement_station_by_icao["KMIA"]
    # KMIA UTC-5: 21:00Z -> 16:00 LST on 2025-06-01, the max of the three readings.
    key = (settlement_station, dt.date(2025, 6, 1))
    assert key in result
    assert result[key].value_f == pytest.approx(90.0)
    assert result[key].lst_seconds_from_midnight == 16 * 3600


def test_daily_max_instants_raises_loudly_on_an_out_of_order_row(tmp_path: Path) -> None:
    """MEDIUM fix (coordinator review 2026-09-29): the tie-break-to-first-
    occurrence convention depends on a chronological stream -- an
    out-of-order row must raise, never be silently accepted or re-sorted."""
    registry = nbp_skill_study.station_registry()
    body = (
        b"valid(UTC),tmpf\n"
        b"2025-06-01 21:00,90\n"
        b"2025-06-01 20:00,88\n"  # earlier timestamp AFTER a later one: out of order
    )
    archive_root = _seed_asos_archive(tmp_path, station="KMIA", body=body)

    with pytest.raises(nbp_skill_study.AsosRowOrderError):
        nbp_skill_study.daily_max_instants(archive_root=archive_root, registry=registry)
