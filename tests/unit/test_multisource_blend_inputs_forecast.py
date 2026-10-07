"""NBP, PFM and GFS-MOS readers for the F13 Phase A feature build (FB-R5, FB-R7, FB-R8).

Every store is written by its production writer (``write_partition``, ``UsSourceRevisionStore``,
``ArchiveCache``); fixtures are the real IEM GFS-MOS CSV and the real 2021 PFM products.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from pathlib import Path

import pytest

from breezy.ingest.pfm_parse import parse_pfm_product
from breezy.persistence.archive_cache import (
    ArchiveCache,
    iem_mos_request,
    iem_mos_window_request,
)
from breezy.persistence.nbp_derived_store import partition_path
from scripts.analysis import multisource_blend_inputs_forecast as fc
from scripts.analysis import nbp_skill_study as nss
from scripts.analysis.multisource_blend_features_build import read_only_cache
from scripts.archive.iem_mos_backfill import ModelMixError
from tests.unit.featbuild_fixtures import (
    HOUR_NS,
    ns,
    truth_row,
    utc,
    write_cache_entry,
    write_nbp_cycle,
    write_pfm_product,
)
from tests.unit.test_us_source_pfm_history import _FIXTURES, _fixture

_HOLDOUT = dt.date(2026, 7, 1)
_REGISTRY_STATIONS = ("KMIA", "KLAX")


def _registry() -> nss.StationRegistry:
    return nss.station_registry(stations=_REGISTRY_STATIONS)


def _collect(
    root: Path, *, end: dt.date = _HOLDOUT, counts: Counter[str] | None = None
) -> dict[tuple[str, dt.date], list[fc.NbpCandidate]]:
    return fc.collect_nbp_candidates(
        root,
        _registry(),
        end_exclusive=end,
        counts=counts if counts is not None else Counter(),
    )


# ------------------------------------------------------------------ NBP (FB-R5)


def test_nbp_window_availability_carried_and_latest_cycle_before_anchor(tmp_path: Path) -> None:
    day = dt.date(2025, 6, 1)  # cycle day D-1; the explicit D+1 target is 2025-06-02
    c13 = write_nbp_cycle(
        tmp_path,
        station="KMIA",
        cycle_day=day,
        cycle_hour=13,
        q50=90.0,
        available_after_ns=4 * HOUR_NS,
    )
    c19 = write_nbp_cycle(
        tmp_path,
        station="KMIA",
        cycle_day=day,
        cycle_hour=19,
        q50=92.0,
        available_after_ns=2 * HOUR_NS,
    )
    candidates = _collect(tmp_path)[("MIA", dt.date(2025, 6, 2))]

    assert sorted(c.cycle_runtime_ns for c in candidates) == [c13, c19]
    anchor = ns(utc(2025, 6, 1, 18))
    picked = fc.select_nbp(candidates, anchor_ns=anchor)
    later = fc.select_nbp(candidates, anchor_ns=ns(utc(2025, 6, 1, 22)))

    assert picked is not None and picked.cycle_runtime_ns == c13
    assert picked.available_at_ns == c13 + 4 * HOUR_NS == ns(utc(2025, 6, 1, 17))
    assert picked.percentiles.q50 == 90.0 and picked.version == "v4.2"
    assert later is not None and later.cycle_runtime_ns == c19


def test_the_lag_twin_shifts_nbp_and_can_drop_the_window(tmp_path: Path) -> None:
    day = dt.date(2025, 6, 1)
    write_nbp_cycle(
        tmp_path,
        station="KMIA",
        cycle_day=day,
        cycle_hour=13,
        q50=90.0,
        available_after_ns=4 * HOUR_NS,
    )
    candidates = _collect(tmp_path)[("MIA", dt.date(2025, 6, 2))]
    anchor = ns(utc(2025, 6, 1, 18))  # 13Z + 4 h = 17Z: before 18Z, but not once shifted +60 min

    assert fc.select_nbp(candidates, anchor_ns=anchor) is not None
    assert fc.select_nbp(candidates, anchor_ns=anchor, extra_lag_ns=HOUR_NS) is None


def test_selected_nbp_cycle_is_one_the_champion_m0_trains_on(tmp_path: Path) -> None:
    # 13Z and 19Z of 2025-06-01 and the 01Z of 2025-06-02 all target 2025-06-02
    for hour, cycle_day, q50 in (
        (13, dt.date(2025, 6, 1), 90.0),
        (19, dt.date(2025, 6, 1), 91.0),
        (1, dt.date(2025, 6, 2), 92.0),
    ):
        write_nbp_cycle(tmp_path, station="KMIA", cycle_day=cycle_day, cycle_hour=hour, q50=q50)
    candidates = _collect(tmp_path)[("MIA", dt.date(2025, 6, 2))]
    rows = [r for _p, rs in nss.iter_nbp_derived_rows(tmp_path) if rs for r in rs]
    windows = nss.complete_percentile_windows(rows)
    truth = {
        ("MIA", dt.date(2025, 6, 2)): truth_row(
            station="MIA", climate_day=dt.date(2025, 6, 2), tmax_f=91
        )
    }
    champion, _gaps = nss.build_version_rows(windows, truth, registry=_registry())

    champion_q50 = {v.percentiles.q50 for v in champion if v.climate_day == dt.date(2025, 6, 2)}
    assert champion_q50 == {90.0, 91.0, 92.0}
    assert {c.percentiles.q50 for c in candidates} == champion_q50  # same selector, same cycles
    d_minus_1 = fc.select_nbp(candidates, anchor_ns=ns(utc(2025, 6, 1, 18)))
    d0 = fc.select_nbp(candidates, anchor_ns=ns(utc(2025, 6, 2, 15)))
    assert d_minus_1 is not None and d_minus_1.percentiles.q50 == 90.0  # the 13Z cycle
    assert d0 is not None and d0.percentiles.q50 == 92.0  # the 01Z cycle, the latest one for D0


def test_non_qualifying_cycles_unreadable_partitions_and_holdout_targets_are_dropped(
    tmp_path: Path,
) -> None:
    write_nbp_cycle(tmp_path, station="KMIA", cycle_day=dt.date(2025, 6, 1), cycle_hour=7, q50=1.0)
    write_nbp_cycle(
        tmp_path, station="KMIA", cycle_day=dt.date(2026, 6, 30), cycle_hour=13, q50=2.0
    )
    write_nbp_cycle(
        tmp_path, station="KMIA", cycle_day=dt.date(2026, 6, 20), cycle_hour=13, q50=3.0
    )
    bad = partition_path(tmp_path, dt.date(2025, 6, 3), 13)
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_bytes(b"not a parquet file")
    counts: Counter[str] = Counter()

    found = _collect(tmp_path, counts=counts)

    assert set(found) == {("MIA", dt.date(2026, 6, 21))}  # 06-30 cycle targets 07-02 (sealed)
    assert counts["nbp_partition_unreadable"] == 1
    assert counts["nbp_holdout_excluded"] == 1
    assert counts["nbp_non_qualifying_cycle"] >= 1


def test_a_window_without_a_published_availability_is_refused(tmp_path: Path) -> None:
    candidates = [
        fc.NbpCandidate(
            station="MIA",
            climate_day=dt.date(2025, 6, 2),
            cycle_runtime_ns=1,
            available_at_ns=None,
            version="v4.2",
            percentiles=None,  # type: ignore[arg-type]
        )
    ]

    with pytest.raises(fc.FeatureInputError, match="available_at"):
        fc.select_nbp(candidates, anchor_ns=10**18)


# ------------------------------------------------------------------ PFM (FB-R8)

_OKX_2021 = "pfm_okx_real_20210312.txt"
_ISSUED_2021 = utc(2021, 3, 12, 23, 5)
_HOUR_LAG = HOUR_NS


def _okx_store(root: Path, **kwargs: object) -> None:
    write_pfm_product(
        root,
        station="KNYC",
        wfo="OKX",
        issued=_ISSUED_2021,
        text=_fixture(_OKX_2021),
        **kwargs,  # type: ignore[arg-type]
    )


def _pfm(root: Path, counts: Counter[str], end: dt.date = _HOLDOUT) -> dict[dt.date, list[object]]:
    return fc.collect_pfm_vintages(  # type: ignore[return-value]
        read_only_cache(root), icao="KNYC", lag_ns=_HOUR_LAG, end_exclusive=end, counts=counts
    )


def test_pfm_vintage_is_wmo_issuance_plus_the_pinned_lag_per_forecast_day(tmp_path: Path) -> None:
    _okx_store(tmp_path)
    expected = dict(
        parse_pfm_product(
            _fixture(_OKX_2021).encode(), station="KNYC", reference_time=_ISSUED_2021
        ).max_by_day
    )

    found = _pfm(tmp_path, Counter())

    assert set(found) == set(expected)
    for day, (vintage,) in found.items():
        assert vintage.available_at_ns == ns(_ISSUED_2021) + _HOUR_LAG  # type: ignore[attr-defined]
        assert vintage.mu_f == float(expected[day])  # type: ignore[attr-defined]


def test_pfm_first_revision_only(tmp_path: Path) -> None:
    changed = _fixture(_OKX_2021).replace("          47", "          49", 1)
    assert changed != _fixture(_OKX_2021)
    _okx_store(tmp_path, revision_texts=[changed])
    first = dict(
        parse_pfm_product(
            _fixture(_OKX_2021).encode(), station="KNYC", reference_time=_ISSUED_2021
        ).max_by_day
    )

    found = _pfm(tmp_path, Counter())

    assert {d: v[0].mu_f for d, v in found.items()} == {d: float(m) for d, m in first.items()}  # type: ignore[attr-defined]


def test_a_first_row_that_is_not_the_earliest_fetched_is_refused_and_counted(
    tmp_path: Path,
) -> None:
    changed = _fixture(_OKX_2021).replace("          47", "          49", 1)
    _okx_store(tmp_path, revision_texts=[changed], clock_steps_ns=[0, -(10**12)])
    counts: Counter[str] = Counter()

    found = _pfm(tmp_path, counts)

    assert found == {}
    assert counts["pfm_first_revision_not_earliest"] == 1


def test_an_unparseable_pfm_is_counted_and_skipped(tmp_path: Path) -> None:
    write_pfm_product(
        tmp_path, station="KNYC", wfo="OKX", issued=_ISSUED_2021, text="not a product\n"
    )
    counts: Counter[str] = Counter()

    assert _pfm(tmp_path, counts) == {}
    assert counts["pfm_unparseable"] == 1


def test_a_pfm_issued_on_or_after_the_holdout_start_is_never_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_pfm_product(
        tmp_path,
        station="KNYC",
        wfo="OKX",
        issued=utc(2026, 7, 2, 19, 1),
        text=_fixture("pfm_okx_real_20261006.txt"),
    )
    reads: list[object] = []
    real = ArchiveCache.read

    def spy(self: ArchiveCache, request: object) -> bytes:
        reads.append(request)
        return real(self, request)  # type: ignore[arg-type]

    monkeypatch.setattr(ArchiveCache, "read", spy)

    assert _pfm(tmp_path, Counter()) == {}
    assert reads == []


def test_pfm_forecast_days_on_or_after_the_end_are_not_kept(tmp_path: Path) -> None:
    _okx_store(tmp_path)

    found = _pfm(tmp_path, Counter(), end=dt.date(2021, 3, 14))

    assert found and max(found) < dt.date(2021, 3, 14)


# ------------------------------------------------------------------ GFS MOS (FB-R7)

_MOS_LAG = 5 * HOUR_NS
_GFS_FIXTURE = _FIXTURES.parent / "iem" / "mos_GFS_KMIA_2021-06-15_1day.csv"


def _gfs_cache(root: Path, payload: bytes | None = None) -> ArchiveCache:
    request = iem_mos_window_request("KMIA", dt.date(2021, 6, 15), dt.date(2021, 6, 16), "GFS")
    write_cache_entry(root, request, payload if payload is not None else _GFS_FIXTURE.read_bytes())
    return read_only_cache(root)


def _mos(cache: ArchiveCache, counts: Counter[str]) -> fc.MosResult:
    return fc.collect_mos_vintages(
        cache,
        icao="KMIA",
        std_utc_offset_hours=-5.0,
        first_day=dt.date(2021, 6, 15),
        last_day=dt.date(2021, 6, 15),
        lag_ns=_MOS_LAG,
        model="GFS",
        counts=counts,
    )


def test_mos_runtime_plus_5h_conservative(tmp_path: Path) -> None:
    result = _mos(_gfs_cache(tmp_path), Counter())

    vintages = result.vintages_by_day[dt.date(2021, 6, 15)]
    # hand-read from the real file: n_x at ftime 2021-06-16 00Z, from the 00Z and 06Z runtimes only
    assert [(v.available_at_ns, v.mu_f) for v in vintages] == [
        (ns(utc(2021, 6, 15, 0)) + _MOS_LAG, 91.0),
        (ns(utc(2021, 6, 15, 6)) + _MOS_LAG, 90.0),
    ]


def test_the_12z_min_rows_are_never_taken_as_a_daily_max(tmp_path: Path) -> None:
    result = _mos(_gfs_cache(tmp_path), Counter())

    # the 12Z-ftime n_x values of that file (74, 75, 76, 73, 78) are daily MINIMA
    assert {v.mu_f for v in result.vintages_by_day[dt.date(2021, 6, 15)]} == {91.0, 90.0}


def test_a_coverage_gap_is_reported_not_fatal(tmp_path: Path) -> None:
    counts: Counter[str] = Counter()

    result = _mos(_gfs_cache(tmp_path), counts)

    assert result.vintages_by_day  # the covered day is still served
    assert dt.date(2021, 6, 14) in result.coverage_gap_days  # the D-1 runtimes are not on disk
    assert counts["mos_coverage_gap_days"] == len(result.coverage_gap_days) > 0


def test_a_gfs_payload_that_carries_nbs_rows_is_a_model_mix_and_refused(tmp_path: Path) -> None:
    text = _GFS_FIXTURE.read_text()
    lines = text.splitlines()
    mixed = "\n".join(lines[:3] + [ln.replace(",GFS,", ",NBS,") for ln in lines[3:6]] + lines[6:])
    cache = _gfs_cache(tmp_path, (mixed + "\n").encode())

    with pytest.raises(ModelMixError):
        _mos(cache, Counter())


def test_a_whole_payload_of_the_wrong_model_is_refused(tmp_path: Path) -> None:
    nbs_as_gfs = _GFS_FIXTURE.read_text().replace(",GFS,", ",NBS,").encode()

    with pytest.raises(ModelMixError):
        _mos(_gfs_cache(tmp_path, nbs_as_gfs), Counter())


def test_year_entries_are_served_through_the_same_resolver(tmp_path: Path) -> None:
    write_cache_entry(tmp_path, iem_mos_request("KMIA", 2021, "GFS"), _GFS_FIXTURE.read_bytes())
    result = fc.collect_mos_vintages(
        read_only_cache(tmp_path),
        icao="KMIA",
        std_utc_offset_hours=-5.0,
        first_day=dt.date(2021, 6, 15),
        last_day=dt.date(2021, 6, 16),
        lag_ns=_MOS_LAG,
        model="GFS",
        counts=Counter(),
    )

    assert result.coverage_gap_days == ()
    assert [v.mu_f for v in result.vintages_by_day[dt.date(2021, 6, 16)]] == [
        85.0,
        89.0,
        88.0,
        85.0,
    ]
