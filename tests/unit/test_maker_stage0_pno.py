"""MAKER-S2 WP2 -- the p_NO loader, on a synthetic ``DerivedNbpRow`` store.

The store is built in ``tmp_path`` from the committed NBP fixture excerpts
(13Z/19Z on 2026-09-28, 01Z on 2026-09-29 => climate day D = 2026-09-29, LAX
std offset -8). The real derived store is never read.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from collections.abc import Sequence
from pathlib import Path

import pytest

from breezy.domain.location_correction import CorrectionForm
from breezy.ingest.nbm_quantile_actor import DEFAULT_NBM_QUANTILE_TIMER_INTERVAL_SECONDS
from breezy.persistence import nbp_derived_store
from breezy.persistence.nbp_derived_store import (
    PUBLICATION_LAG_FLOOR_NS,
    DerivedNbpRow,
    partition_path,
    write_partition,
)
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import LiveCalibration
from breezy.strategy.ladder_ev.quantile_density import (
    CdfMethod,
    EmosParams,
    Percentiles,
    Rung,
    apply_emos,
    build_cdf,
)
from scripts.analysis.maker_stage0_pno import (
    STALE_H,
    AlignmentLine,
    PNoStore,
    StationRefusedError,
    VintageAgeLine,
    load_p_no,
    verify_first_s6,
)
from scripts.analysis.nbp_backfill import derive_rows_for_bulletin

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "nbm"
RAW_SHA = {13: "sha13", 19: "sha19", 1: "sha01"}
LAST_MODIFIED = {
    13: "Mon, 28 Sep 2026 14:04:00 GMT",
    19: "Mon, 28 Sep 2026 20:17:00 GMT",
    1: "Tue, 29 Sep 2026 02:04:00 GMT",
}
NS_PER_DAY = 86_400 * 10**9
DAY = dt.date(2026, 9, 29)
LADDER: tuple[Rung, ...] = (
    Rung("lt80", None, 79),
    Rung("r80", 80, 81),
    Rung("r82", 82, 83),
    Rung("r84", 84, 85),
    Rung("ge86", 86, None),
)
DRAWS = (EmosParams(0.0, 0.0, 1.0), EmosParams(0.4, 0.05, 1.0))


def _ns(day: dt.date, hour: int, minute: int = 0) -> int:
    stamp = dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=dt.UTC)
    return int(stamp.timestamp()) * 10**9


def _derive(hour: int, last_modified: str | None) -> tuple[DerivedNbpRow, ...]:
    text = (FIXTURES / f"nbptx_t{hour:02d}z_excerpt.txt").read_text()
    rows, _ = derive_rows_for_bulletin(
        text=text,
        source_host="fixture",
        last_modified=last_modified,
        fetched_at_ns=1,
        raw_sha256=RAW_SHA[hour],
        stations=frozenset({"KLAX", "KMDW", "KMIA", "KSFO"}),
    )
    return rows


def _shift(rows: Sequence[DerivedNbpRow], days: int) -> tuple[DerivedNbpRow, ...]:
    delta = days * NS_PER_DAY
    return tuple(
        dataclasses.replace(
            row,
            cycle_runtime_ns=row.cycle_runtime_ns + delta,
            valid_start_ns=row.valid_start_ns + delta,
            valid_end_ns=row.valid_end_ns + delta,
            available_at_ns=row.available_at_ns + delta,
        )
        for row in rows
    )


def _write(root: Path, rows: Sequence[DerivedNbpRow]) -> None:
    cycle = dt.datetime.fromtimestamp(rows[0].cycle_runtime_ns / 10**9, tz=dt.UTC)
    write_partition(rows, partition_path(root, cycle.date(), cycle.hour))


def _build_root(
    tmp_path: Path,
    *,
    hours: Sequence[int] = (13, 19, 1),
    last_modified: dict[int, str | None] | None = None,
) -> Path:
    root = tmp_path / "nbp"
    lms: dict[int, str | None] = dict(LAST_MODIFIED) if last_modified is None else last_modified
    for hour in hours:
        _write(root, _derive(hour, lms[hour]))
    return root


def _calibration(versions: Sequence[str] = ("v5.0",)) -> LiveCalibration:
    return LiveCalibration(
        sha256="test",
        cdf_method=CdfMethod.NORMAL,
        correction_form=CorrectionForm.NONE,
        linear_coefficients=None,
        month_offsets={},
        point_by_version={v: DRAWS[0] for v in versions},
        draws_by_version={v: DRAWS for v in versions},
    )


def _store(
    root: Path,
    *,
    day: dt.date = DAY,
    calibration: LiveCalibration | None = None,
    stations: Sequence[str] = ("LAX",),
) -> PNoStore:
    return PNoStore.from_root(
        root,
        stations=stations,
        days=[day],
        calibration=calibration or _calibration(),
        ladders={(s, day): LADDER for s in stations},
    )


def test_inclusive_band_uses_hi_plus_half_and_lo_minus_half(tmp_path: Path) -> None:
    store = _store(_build_root(tmp_path))
    result = load_p_no(store, "LAX", DAY, _ns(dt.date(2026, 9, 28), 16, 50), stress="none")
    assert result is not None
    vector = result.vector
    pct = Percentiles(
        vector.q10, vector.q25, vector.q50, vector.q75, vector.q90, vector.mean, vector.sd
    )
    base = build_cdf(CdfMethod.NORMAL, pct)
    expected = sum(
        apply_emos(base, pct, d)(83.5) - apply_emos(base, pct, d)(81.5) for d in DRAWS
    ) / len(DRAWS)
    assert result.p_yes_point_live["r82"] == pytest.approx(expected, abs=1e-12)
    assert sum(result.p_yes_point_live.values()) == pytest.approx(1.0, abs=1e-12)
    assert result.p_no("r82") == pytest.approx(1.0 - expected, abs=1e-12)


def test_non_partition_ladder_falls_back_to_complement(tmp_path: Path) -> None:
    root = _build_root(tmp_path)
    partial = (Rung("r82", 82, 83),)
    store = PNoStore.from_root(
        root,
        stations=("LAX",),
        days=[DAY],
        calibration=_calibration(),
        ladders={("LAX", DAY): partial},
    )
    full = load_p_no(_store(root), "LAX", DAY, _ns(dt.date(2026, 9, 28), 16, 50), stress="none")
    result = load_p_no(store, "LAX", DAY, _ns(dt.date(2026, 9, 28), 16, 50), stress="none")
    assert full is not None and result is not None
    assert result.p_yes_point_live["r82"] == pytest.approx(full.p_yes_point_live["r82"], abs=1e-12)


def test_only_first_max_column_is_pushed(tmp_path: Path) -> None:
    store = _store(_build_root(tmp_path))
    result = load_p_no(store, "LAX", DAY, _ns(dt.date(2026, 9, 28), 16, 50), stress="none")
    assert result is not None
    first_column_q50 = min(
        (r for r in _derive(13, None) if r.station == "KLAX" and r.variable == "TXN_Q50"),
        key=lambda r: r.valid_start_ns,
    ).value_f
    assert result.vector.q50 == first_column_q50
    assert result.vector.climate_day == DAY
    assert result.cycle == _ns(dt.date(2026, 9, 28), 13)


def test_13z_day_d_cycle_never_feeds_day_d(tmp_path: Path) -> None:
    root = _build_root(tmp_path)
    _write(root, _shift(_derive(13, LAST_MODIFIED[13]), 1))  # 13Z on D: targets D+1
    store = _store(root)
    at = _ns(DAY, 15, 0)  # the 13Z D cycle is available (14:04Z); the 01Z D vector is 12.9 h old
    assert load_p_no(store, "LAX", DAY, at, stress="none") is None
    assert store.abstentions["forecast_stale"] == 1
    assert all(cycle != _ns(DAY, 13) for cycle, _ in store.consumed_cycles())


def test_vector_for_another_climate_day_abstains_day_mismatch(tmp_path: Path) -> None:
    root = _build_root(tmp_path, hours=(13, 19))
    next_day = tuple(
        dataclasses.replace(
            r,
            valid_start_ns=r.valid_start_ns + NS_PER_DAY,
            valid_end_ns=r.valid_end_ns + NS_PER_DAY,
        )
        for r in _derive(1, LAST_MODIFIED[1])
    )
    _write(root, next_day)
    store = _store(root)
    assert load_p_no(store, "LAX", DAY, _ns(DAY, 3, 0), stress="none") is None
    assert store.abstentions["forecast_day_mismatch"] == 1


def test_vector_not_yet_available_is_invisible(tmp_path: Path) -> None:
    store = _store(_build_root(tmp_path))
    assert load_p_no(store, "LAX", DAY, _ns(dt.date(2026, 9, 28), 14, 3), stress="none") is None
    assert store.abstentions["no_vector"] == 1


def test_available_at_must_precede_decision_instant(tmp_path: Path) -> None:
    store = _store(_build_root(tmp_path))
    avail = _ns(dt.date(2026, 9, 28), 14, 4)
    assert load_p_no(store, "LAX", DAY, avail, stress="none") is None
    later = load_p_no(store, "LAX", DAY, avail + 1, stress="none")
    assert later is not None
    assert later.available_at_ns == avail
    assert later.available_at_ns < avail + 1


def test_vector_older_than_8h_is_stale(tmp_path: Path) -> None:
    store = _store(_build_root(tmp_path, hours=(13,)))
    avail = _ns(dt.date(2026, 9, 28), 14, 4)
    limit = avail + STALE_H * 3600 * 10**9
    fresh = load_p_no(store, "LAX", DAY, limit, stress="none")
    assert fresh is not None
    assert fresh.vintage_age_s == STALE_H * 3600
    assert load_p_no(store, "LAX", DAY, limit + 1, stress="none") is None
    assert store.abstentions["forecast_stale"] == 1


def test_unknown_era_yields_none(tmp_path: Path) -> None:
    store = _store(_build_root(tmp_path), calibration=_calibration(("v4.2",)))
    assert load_p_no(store, "LAX", DAY, _ns(dt.date(2026, 9, 28), 16, 50), stress="none") is None
    assert store.abstentions["unknown_era"] == 1


def test_only_three_pinned_cycles_are_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _build_root(tmp_path)
    d_minus_1 = dt.date(2026, 9, 28)
    for stray in (_shift(_derive(13, None), 1), _shift(_derive(1, None), -1)):  # 13Z D, 01Z D-1
        _write(root, stray)
    seven = tuple(
        dataclasses.replace(
            r, cycle_runtime_ns=_ns(d_minus_1, 7), available_at_ns=_ns(d_minus_1, 8, 10)
        )
        for r in _derive(13, None)
    )
    _write(root, seven)
    read: list[str] = []
    real = nbp_derived_store.read_partition

    def spy(path: Path) -> tuple[DerivedNbpRow, ...]:
        read.append(path.name)
        return real(path)

    monkeypatch.setattr("scripts.analysis.maker_stage0_pno.read_partition", spy)
    store = _store(root)
    assert sorted(read) == [
        "nbp_20260928_13z.parquet",
        "nbp_20260928_19z.parquet",
        "nbp_20260929_01z.parquet",
    ]
    assert {c for c, _ in store.consumed_cycles()} == {
        _ns(d_minus_1, 13),
        _ns(d_minus_1, 19),
        _ns(DAY, 1),
    }


def test_poll_lag_stress_delays_available_at_by_actor_poll_interval(tmp_path: Path) -> None:
    store = _store(_build_root(tmp_path))
    avail = _ns(dt.date(2026, 9, 28), 14, 4)
    lag_ns = DEFAULT_NBM_QUANTILE_TIMER_INTERVAL_SECONDS * 10**9
    assert load_p_no(store, "LAX", DAY, avail + 1, stress="poll_lag") is None
    assert load_p_no(store, "LAX", DAY, avail + lag_ns, stress="poll_lag") is None
    delayed = load_p_no(store, "LAX", DAY, avail + lag_ns + 1, stress="poll_lag")
    assert delayed is not None
    assert delayed.available_at_ns == avail + lag_ns
    assert delayed.vintage_age_s == pytest.approx(1e-9)


def test_plus60_stress_delays_floor_governed_rows(tmp_path: Path) -> None:
    root = _build_root(tmp_path, last_modified={13: LAST_MODIFIED[13], 19: None, 1: None})
    store = _store(root)
    d_minus_1 = dt.date(2026, 9, 28)
    at = _ns(d_minus_1, 20, 30)
    base = load_p_no(store, "LAX", DAY, at, stress="none")
    assert base is not None
    assert base.available_at_ns == _ns(d_minus_1, 19) + PUBLICATION_LAG_FLOOR_NS  # floor governs
    stressed = load_p_no(store, "LAX", DAY, at, stress="plus60")
    assert stressed is not None  # 19Z delayed to 21:00Z, so 13Z (Last-Modified governed) serves
    assert stressed.cycle == _ns(d_minus_1, 13)
    assert stressed.available_at_ns == _ns(d_minus_1, 14, 4)  # not delayed
    released = load_p_no(store, "LAX", DAY, _ns(d_minus_1, 21, 0) + 1, stress="plus60")
    assert released is not None
    assert released.cycle == _ns(d_minus_1, 19)


def test_nyc_is_refused(tmp_path: Path) -> None:
    root = _build_root(tmp_path)
    with pytest.raises(StationRefusedError):
        _store(root, stations=("LAX", "NYC"))
    store = _store(root)
    with pytest.raises(StationRefusedError):
        load_p_no(store, "NYC", DAY, _ns(DAY, 1, 30), stress="none")


def test_consumed_cycles_are_reported_for_pins(tmp_path: Path) -> None:
    store = _store(_build_root(tmp_path))
    d_minus_1 = dt.date(2026, 9, 28)
    assert store.consumed_cycles() == frozenset(
        {(_ns(d_minus_1, 13), "sha13"), (_ns(d_minus_1, 19), "sha19"), (_ns(DAY, 1), "sha01")}
    )


def test_verify_first_runs_only_on_2026_06_30_and_emits_no_fill_output(tmp_path: Path) -> None:
    june = dt.date(2026, 6, 30)
    shift = (june - DAY).days
    root = tmp_path / "june"
    for hour in (13, 19, 1):
        _write(root, _shift(_derive(hour, LAST_MODIFIED[hour]), shift))
    with pytest.raises(ValueError, match="2026-06-30"):
        verify_first_s6(root, DAY)
    report = verify_first_s6(root, june)
    assert report.climate_day == june
    assert {line.station for line in report.alignment} == {"LAX", "MDW", "MIA", "SFO"}
    assert all(line.matches_climate_day_for_txn for line in report.alignment)
    assert {line.instant for line in report.vintage_age} == {"16:50Z D-1", "00:00Z D", "02:50Z D"}
    assert all(line.within_tolerance for line in report.vintage_age)
    names = {f.name for f in dataclasses.fields(report)}
    assert names == {"climate_day", "alignment", "vintage_age"}
    forbidden = ("fill", "bid", "episode", "p_no", "p_yes", "truth")
    lines: tuple[AlignmentLine | VintageAgeLine, ...] = (*report.alignment, *report.vintage_age)
    for line in lines:
        assert not any(w in f.name for f in dataclasses.fields(line) for w in forbidden)
