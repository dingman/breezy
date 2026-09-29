"""RED-first tests for the `nbp_skill_study` CLI: the holdout guard (SL-8)
and the real-data validate-stage join (SL-8b task 5).

The join fixtures below are entirely SYNTHETIC -- hand-built
`DerivedNbpRow`/`SettlementTruthRow` rows written to `tmp_path` parquet
files, never the real backfill or the real v5.0 holdout.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path

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

from breezy.analysis.nbp_calibration import DEFAULT_SPLITS  # noqa: E402
from breezy.persistence.nbp_derived_store import DerivedNbpRow, write_partition  # noqa: E402


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
# nearest_percentile_windows
# ---------------------------------------------------------------------------


def test_nearest_percentile_windows_keeps_only_complete_groups() -> None:
    day = dt.date(2025, 6, 1)
    cycle = _cycle_runtime_ns(day, 13)
    near = _valid_00z_ns(day + dt.timedelta(days=1))
    far = _valid_00z_ns(day + dt.timedelta(days=2))
    rows = [
        *_complete_window_rows(station="KMIA", cycle_runtime_ns=cycle, valid_ns=near, q50=90.0),
        *_complete_window_rows(station="KMIA", cycle_runtime_ns=cycle, valid_ns=far, q50=91.0),
    ]
    # Drop one variable from the NEAR window only -- it is reported
    # (incomplete_windows), never imputed. The FAR window is a genuinely
    # complete, real forecast (not fabricated), so it is the nearest
    # COMPLETE window used -- falling back to it is real-data reuse, not
    # imputation of the dropped near-window value.
    rows = [row for row in rows if not (row.valid_start_ns == near and row.variable == "TXN_SD")]

    counts = nbp_skill_study._WindowGroupCounts()
    windows = nbp_skill_study.nearest_percentile_windows(rows, counts=counts)

    assert counts.incomplete_windows == 1
    assert len(windows) == 1
    assert windows[0].valid_start_ns == far
    assert windows[0].percentiles.q50 == pytest.approx(91.0)


def test_nearest_percentile_windows_picks_the_smallest_valid_start_ns() -> None:
    day = dt.date(2025, 6, 1)
    cycle = _cycle_runtime_ns(day, 13)
    near = _valid_00z_ns(day + dt.timedelta(days=1))
    far = _valid_00z_ns(day + dt.timedelta(days=2))
    rows = [
        *_complete_window_rows(station="KMIA", cycle_runtime_ns=cycle, valid_ns=near, q50=90.0),
        *_complete_window_rows(station="KMIA", cycle_runtime_ns=cycle, valid_ns=far, q50=91.0),
    ]
    windows = nbp_skill_study.nearest_percentile_windows(rows)
    assert len(windows) == 1
    assert windows[0].valid_start_ns == near
    assert windows[0].percentiles.q50 == pytest.approx(90.0)


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
    # climate_day_for_txn(kind="max") maps a 00Z ftime to the LOCAL date the
    # evening before it (negative UTC offsets) -- so a 00Z window dated
    # `day + 1` in UTC resolves to climate_day == `day` (verified against
    # the real function; see NBP_TXN_WINDOW_AND_BBB_NOTE_2026-09-29.md).
    day = dt.date(2025, 6, 1)
    climate_day = day
    cycle = _cycle_runtime_ns(day, 13)
    from breezy.strategy.ladder_ev.quantile_density import Percentiles

    window = nbp_skill_study.NbpPercentileWindow(
        station="KMIA",
        cycle_runtime_ns=cycle,
        valid_start_ns=_valid_00z_ns(day + dt.timedelta(days=1)),
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
    assert gaps == {"missing_settlement": 1}


def test_a_holdout_dated_row_is_never_present_in_validate_mode_output() -> None:
    """The HARD invariant: even when a matching settlement row exists for a
    holdout-dated climate day, build_version_rows must never emit it."""
    from breezy.strategy.ladder_ev.quantile_density import Percentiles

    holdout_day = DEFAULT_SPLITS.holdout_start  # 2026-07-01
    cycle = _cycle_runtime_ns(holdout_day, 13)
    # A 00Z window one UTC day later resolves (kind="max") to climate_day ==
    # holdout_day -- see the note in the previous test.
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
    climate_day = day  # see the climate_day_for_txn note above
    cycle = _cycle_runtime_ns(day, 13)
    rows = _complete_window_rows(
        station="KMIA",
        cycle_runtime_ns=cycle,
        valid_ns=_valid_00z_ns(day + dt.timedelta(days=1)),
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
