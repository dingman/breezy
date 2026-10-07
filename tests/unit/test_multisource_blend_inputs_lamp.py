"""LAMP (MDL archive) and LAV (IEM gap-fill) readers for the F13 Phase A feature build.

FB-R8: availability is the NOMINAL run time plus the pinned lag, never a manifest ``available_at``
(a download time); sealed (>= 2026-07-01) runs are never read; the MDL -> LAV basis break is
observed and reported. FB-R9: ``lav_csv_to_lamp_run`` is new here. Every store is written by the
production writers (L-42); the real 2026-01 archive bulletin is one fixture.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from pathlib import Path

import pytest

from breezy.analysis.multisource_blend_features import LampRun
from breezy.persistence.archive_cache import ArchiveCache
from scripts.analysis import multisource_blend_inputs_lamp as lamp
from scripts.analysis.multisource_blend_features_build import read_only_cache
from scripts.archive.lamp_archive_runs import LavPayloadError, iter_lamp_runs
from tests.unit.featbuild_fixtures import (
    HOUR_NS,
    LAV_HEADER,
    NS,
    lav_csv,
    ns,
    utc,
    write_lav_run,
    write_mdl_run,
)
from tests.unit.test_us_source_pfm_history import _FIXTURES

_MIN = 60 * NS
_LAGS = {"lamp-mdl": 60 * _MIN, "lav-iem": 90 * _MIN}
_HOLDOUT = dt.date(2026, 7, 1)
_TEMPS = [50 + i for i in range(25)]


def _archive(root: Path, counts: Counter[str] | None = None) -> lamp.LampArchive:
    return lamp.LampArchive(
        read_only_cache(root),
        root,
        lag_ns_by_source=_LAGS,
        holdout_start=_HOLDOUT,
        counts=counts if counts is not None else Counter(),
    )


# ------------------------------------------------------------------ MDL availability (FB-R8)


def test_mdl_run_available_at_is_nominal_plus_pinned_lag_never_the_manifest_value(
    tmp_path: Path,
) -> None:
    run_at = utc(2025, 3, 10, 12, 30)
    # a manifest row stamped with a (weeks-later) download time must be ignored
    write_mdl_run(
        tmp_path,
        run_at=run_at,
        temps_by_station={"KNYC": _TEMPS},
        manifest_available_at_ns=ns(utc(2025, 4, 20)),
    )

    choice = _archive(tmp_path).runs_for("KNYC", anchor_ns=ns(utc(2025, 3, 10, 18)))

    assert choice.basis == "mdl"
    assert [r.available_at_ns for r in choice.runs] == [ns(run_at) + 60 * _MIN]
    assert choice.runs[0].issued_ns == ns(run_at)


def test_runs_whose_pinned_availability_is_not_before_the_anchor_are_not_eligible(
    tmp_path: Path,
) -> None:
    write_mdl_run(tmp_path, run_at=utc(2025, 3, 10, 12, 30), temps_by_station={"KNYC": _TEMPS})
    write_mdl_run(tmp_path, run_at=utc(2025, 3, 10, 13, 30), temps_by_station={"KNYC": _TEMPS})
    archive = _archive(tmp_path)

    # 13:30 + 60 min = 14:30 is not before a 14:30 anchor (strictly before, as the leak check)
    at = archive.runs_for("KNYC", anchor_ns=ns(utc(2025, 3, 10, 14, 30)))
    after = archive.runs_for("KNYC", anchor_ns=ns(utc(2025, 3, 10, 14, 31)))

    assert [r.issued_ns for r in at.runs] == [ns(utc(2025, 3, 10, 12, 30))]
    assert [r.issued_ns for r in after.runs] == [
        ns(utc(2025, 3, 10, 12, 30)),
        ns(utc(2025, 3, 10, 13, 30)),
    ]


def test_runs_parse_the_requested_station_block_hours(tmp_path: Path) -> None:
    run_at = utc(2025, 3, 10, 12, 30)
    write_mdl_run(
        tmp_path,
        run_at=run_at,
        temps_by_station={"KNYC": _TEMPS, "KLAX": [70] * 25},
    )

    nyc = _archive(tmp_path).runs_for("KNYC", anchor_ns=ns(utc(2025, 3, 10, 18))).runs[0]
    lax = _archive(tmp_path).runs_for("KLAX", anchor_ns=ns(utc(2025, 3, 10, 18))).runs[0]

    assert len(nyc.hours) == 25
    assert nyc.hours[0].valid_ts_ns == ns(utc(2025, 3, 10, 13))
    assert [h.tmp_f for h in nyc.hours[:3]] == [50.0, 51.0, 52.0]
    assert {h.tmp_f for h in lax.hours} == {70.0}


def test_a_missing_marker_hour_is_none_never_imputed(tmp_path: Path) -> None:
    write_mdl_run(
        tmp_path,
        run_at=utc(2025, 3, 10, 12, 30),
        temps_by_station={"KNYC": [50, None, 52] + [53] * 22},
    )

    run = _archive(tmp_path).runs_for("KNYC", anchor_ns=ns(utc(2025, 3, 10, 18))).runs[0]

    assert [h.tmp_f for h in run.hours[:3]] == [50.0, None, 52.0]


def test_a_station_block_absent_from_the_run_is_counted_and_the_run_excluded(
    tmp_path: Path,
) -> None:
    write_mdl_run(tmp_path, run_at=utc(2025, 3, 10, 12, 30), temps_by_station={"KNYC": _TEMPS})
    counts: Counter[str] = Counter()

    choice = _archive(tmp_path, counts).runs_for("KLAX", anchor_ns=ns(utc(2025, 3, 10, 18)))

    assert choice.runs == ()
    assert choice.basis is None
    assert counts["lamp_station_block_missing"] == 1


def test_an_unreadable_run_is_counted_and_skipped(tmp_path: Path) -> None:
    from breezy.persistence.us_source_request import US_LAMP_MDL_SOURCE
    from breezy.persistence.us_source_revision_store import UsSourceRevisionStore
    from tests.unit.featbuild_fixtures import FixedClock

    bad_at = utc(2025, 3, 10, 13, 30)
    UsSourceRevisionStore(tmp_path, FixedClock()).append_if_new(
        source=US_LAMP_MDL_SOURCE,
        station="ALL",
        run_ts_ns=ns(bad_at),
        model=None,
        payload=b" KNYC   GFS LAMP GUIDANCE   3/10/2025  1330 UTC\n UTC  14 15\n TMP  5X 51\n\n",
    )
    write_mdl_run(tmp_path, run_at=utc(2025, 3, 10, 12, 30), temps_by_station={"KNYC": _TEMPS})
    counts: Counter[str] = Counter()

    choice = _archive(tmp_path, counts).runs_for("KNYC", anchor_ns=ns(utc(2025, 3, 10, 18)))

    assert [r.issued_ns for r in choice.runs] == [ns(utc(2025, 3, 10, 12, 30))]
    assert counts["lamp_run_unreadable"] == 1


def test_the_real_2026_archive_bulletin_parses_through_the_production_grouping(
    tmp_path: Path,
) -> None:
    raw = (_FIXTURES / "lamp_archive_real_202601_1230z.txt").read_text()
    lines = [ln for ln in raw.splitlines(keepends=True) if not ln.startswith("#")]
    (run,) = list(iter_lamp_runs(lines, expect_year_month=(2026, 1), expect_hhmm="1230", tally={}))
    from breezy.persistence.us_source_request import US_LAMP_MDL_SOURCE
    from breezy.persistence.us_source_revision_store import UsSourceRevisionStore
    from tests.unit.featbuild_fixtures import FixedClock

    UsSourceRevisionStore(tmp_path, FixedClock()).append_if_new(
        source=US_LAMP_MDL_SOURCE,
        station="ALL",
        run_ts_ns=ns(run.run_at),
        model=None,
        payload=run.payload(),
    )

    choice = _archive(tmp_path).runs_for("KNYC", anchor_ns=ns(utc(2026, 1, 1, 18)))

    (parsed,) = choice.runs
    assert len(parsed.hours) == 25
    assert parsed.hours[0].valid_ts_ns == ns(utc(2026, 1, 1, 13))
    assert [h.tmp_f for h in parsed.hours[:4]] == [27.0, 25.0, 25.0, 26.0]  # the real TMP row


# ------------------------------------------------------------------ holdout


def test_holdout_sealed_manifest_rows_never_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a pre-holdout date whose manifest row says sealed: the payload must never be read
    write_mdl_run(
        tmp_path,
        run_at=utc(2025, 3, 10, 12, 30),
        temps_by_station={"KNYC": _TEMPS},
        sealed_in_manifest=True,
    )
    reads: list[str] = []
    real = ArchiveCache.read

    def spy(self: ArchiveCache, request: object) -> bytes:
        reads.append(str(request))
        return real(self, request)  # type: ignore[arg-type]

    monkeypatch.setattr(ArchiveCache, "read", spy)
    counts: Counter[str] = Counter()

    choice = _archive(tmp_path, counts).runs_for("KNYC", anchor_ns=ns(utc(2025, 3, 10, 18)))

    assert choice.runs == ()
    assert reads == []
    assert counts["lamp_holdout_sealed_skipped"] == 1


def test_a_run_dated_on_or_after_the_holdout_start_is_never_read_even_without_a_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_mdl_run(
        tmp_path,
        run_at=utc(2026, 7, 1, 12, 30),
        temps_by_station={"KNYC": _TEMPS},
        sealed_in_manifest=False,
    )
    reads: list[str] = []
    real = ArchiveCache.read

    def spy(self: ArchiveCache, request: object) -> bytes:
        reads.append(str(request))
        return real(self, request)  # type: ignore[arg-type]

    monkeypatch.setattr(ArchiveCache, "read", spy)

    choice = _archive(tmp_path).runs_for("KNYC", anchor_ns=ns(utc(2026, 7, 1, 18)))

    assert choice.runs == () and reads == []


# ------------------------------------------------------------------ LAV (new reader, FB-R9)


def test_lav_csv_to_lamp_run_reads_the_real_iem_column_layout() -> None:
    run_at = utc(2026, 3, 1, 12)
    payload = lav_csv("KNYC", run_at, [41, None, 43])
    assert payload.decode().splitlines()[0] == LAV_HEADER  # the header the IEM mos.py CSV prints

    run = lamp.lav_csv_to_lamp_run(payload, station="KNYC", available_at_ns=ns(run_at) + 90 * _MIN)

    assert isinstance(run, LampRun)
    assert run.issued_ns == ns(run_at)
    assert run.available_at_ns == ns(run_at) + 90 * _MIN
    assert [h.valid_ts_ns for h in run.hours] == [ns(run_at) + i * HOUR_NS for i in (1, 2, 3)]
    assert [h.tmp_f for h in run.hours] == [41.0, None, 43.0]


def test_lav_csv_for_another_model_or_station_or_two_runs_is_refused() -> None:
    gfs_mos = (_FIXTURES.parent / "iem" / "mos_GFS_KMIA_2021-06-15_1day.csv").read_bytes()
    with pytest.raises(LavPayloadError, match="model"):
        lamp.lav_csv_to_lamp_run(gfs_mos, station="KMIA", available_at_ns=0)

    run_at = utc(2026, 3, 1, 12)
    with pytest.raises(LavPayloadError, match="station"):
        lamp.lav_csv_to_lamp_run(lav_csv("KNYC", run_at, [41]), station="KLAX", available_at_ns=0)

    two = (
        lav_csv("KNYC", run_at, [41])
        + lav_csv("KNYC", utc(2026, 3, 1, 18), [42]).split(b"\n", 1)[1]
    )
    with pytest.raises(LavPayloadError, match="one run"):
        lamp.lav_csv_to_lamp_run(two, station="KNYC", available_at_ns=0)


def test_lav_availability_uses_the_lav_lag_pin(tmp_path: Path) -> None:
    run_at = utc(2026, 3, 1, 12)
    write_lav_run(
        tmp_path, station="KNYC", run_at=run_at, payload=lav_csv("KNYC", run_at, [41] * 5)
    )

    choice = _archive(tmp_path).runs_for("KNYC", anchor_ns=ns(utc(2026, 3, 1, 20)))

    assert choice.basis == "lav"
    assert [r.available_at_ns for r in choice.runs] == [ns(run_at) + 90 * _MIN]


def test_mdl_is_preferred_and_lav_fills_only_where_mdl_has_no_eligible_run(tmp_path: Path) -> None:
    write_mdl_run(tmp_path, run_at=utc(2026, 2, 27, 12, 30), temps_by_station={"KNYC": _TEMPS})
    lav_at = utc(2026, 3, 5, 12)
    write_lav_run(
        tmp_path, station="KNYC", run_at=lav_at, payload=lav_csv("KNYC", lav_at, [41] * 5)
    )
    archive = _archive(tmp_path)

    early = archive.runs_for("KNYC", anchor_ns=ns(utc(2026, 2, 27, 18)))
    late = archive.runs_for("KNYC", anchor_ns=ns(utc(2026, 3, 5, 20)))

    assert (early.basis, late.basis) == ("mdl", "lav")


def test_basis_breaks_are_the_first_day_each_basis_changes() -> None:
    d = dt.date
    bases = {
        d(2026, 2, 26): "mdl",
        d(2026, 2, 27): "mdl",
        d(2026, 3, 1): "lav",
        d(2026, 3, 2): "lav",
        d(2026, 3, 3): "mdl",
        d(2026, 3, 4): None,
    }

    assert lamp.basis_breaks(bases) == [d(2026, 3, 1), d(2026, 3, 3)]
