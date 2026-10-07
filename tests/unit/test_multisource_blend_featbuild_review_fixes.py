"""RED-first tests: the F13 feature-builder review-fix batch (items 1, 6-11).

Item 1 unexpected exceptions still write the report (status ``error``, exit 2); item 6 atomic output
set and stale ``.tmp`` cleanup; item 7 the F2 truth is a protected input and sealed concordance rows
are never value-parsed; item 8 LAMP basis per (day, horizon); item 9 the twin re-check uses shifted
availability; item 10 PFM day labels across both DST transitions; item 11 chunked hashing and the
module size bound. Synthetic worlds written with the production writers; nothing touches the live
data root or the network.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from breezy.analysis import multisource_blend as msb
from breezy.analysis.multisource_blend_features import (
    LAG_SHIFT_NS,
    FeatureRow,
    LampFeature,
    LeakageError,
    assemble_feature_row,
)
from breezy.domain.climate_day import climate_day_for_instant
from breezy.strategy.ladder_ev.quantile_density import Percentiles
from scripts.analysis import multisource_blend_features_build as fb
from scripts.analysis import multisource_blend_inputs_forecast as forecast
from scripts.analysis import multisource_blend_inputs_lamp as lampmod
from scripts.analysis import multisource_blend_inputs_report as report_mod
from scripts.analysis import multisource_blend_sidecar as sidecar
from tests.unit.featbuild_fixtures import ns, utc, write_pfm_product
from tests.unit.test_multisource_blend_features_build import (
    _D13,
    _D14,
    _build_world,
    _no_process_cap,  # noqa: F401  (autouse fixture re-used here)
    _run,
)
from tests.unit.test_us_source_pfm_history import _fixture

_REPO = Path(__file__).resolve().parents[2]
_BUILDER = _REPO / "scripts" / "analysis" / "multisource_blend_features_build.py"


# ------------------------------------------------------------------ item 1: any exception reports


@pytest.mark.parametrize(
    "exc",
    [
        KeyError("missing_column"),
        OSError("disk gone"),
        ValueError("bad value"),
        json.JSONDecodeError("bad json", "{", 1),
        ZeroDivisionError("odd"),
    ],
)
def test_an_unexpected_exception_still_writes_the_report_and_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exc: Exception
) -> None:
    world = _build_world(tmp_path)

    def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise exc

    monkeypatch.setattr(fb, "collect_nbp_candidates", boom)

    assert _run(world) == fb.EXIT_REFUSED

    report = world.report()
    assert report["status"] == "error" and report["exit_code"] == 2
    assert type(exc).__name__ in report["reason"] and str(exc.args[0]) in report["reason"]
    assert not (world.out() / "features.jsonl").exists()


def test_a_bad_f2_csv_is_reported_as_an_error_not_a_traceback(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    f2 = tmp_path / "f2.csv"
    f2.write_text("station,city\nNYC,NYC\n", encoding="utf-8")  # no climate_day column

    assert _run(world, "a", "--f2-truth", str(f2)) == fb.EXIT_REFUSED

    report = world.report()
    assert report["status"] == "error" and "KeyError" in report["reason"]


def test_a_malformed_cached_payload_error_is_reported_with_its_type_and_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = _build_world(tmp_path)

    def boom(_cfg: Any) -> Any:
        raise FileNotFoundError("truth.parquet vanished")

    monkeypatch.setattr(fb, "_truth_lookup", boom)

    assert _run(world) == fb.EXIT_REFUSED
    assert "FileNotFoundError: truth.parquet vanished" in world.report()["reason"]


# ------------------------------------------------------------------ item 6: atomic output set


def _four(world: Any, tag: str = "a") -> list[Path]:
    out = world.out(tag)
    names = ("features.jsonl", "features_lag60.jsonl")
    return [out / n for n in names] + [Path(str(out / n) + ".manifest.json") for n in names]


def test_all_four_outputs_are_written_when_everything_succeeds(tmp_path: Path) -> None:
    world = _build_world(tmp_path)

    assert _run(world) == fb.EXIT_OK

    assert all(p.is_file() for p in _four(world))
    assert not list(world.out().glob("*.tmp"))


def test_a_failure_part_way_through_leaves_none_of_the_four_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = _build_world(tmp_path)
    real = os.replace

    def flaky(src: Any, dst: Any) -> None:
        if str(dst).endswith("features_lag60.jsonl"):
            raise OSError("rename failed")
        real(src, dst)

    monkeypatch.setattr(os, "replace", flaky)

    assert _run(world) == fb.EXIT_REFUSED

    assert not any(p.exists() for p in _four(world))
    assert not list(world.out().glob("*.tmp"))
    assert world.report()["status"] == "error" and "rename failed" in world.report()["reason"]


def test_a_failure_while_writing_a_temp_file_leaves_nothing_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = _build_world(tmp_path)
    real = os.fsync
    calls = {"n": 0}

    def flaky(fd: int) -> None:
        calls["n"] += 1
        if calls["n"] == 3:
            raise OSError("fsync failed")
        real(fd)

    monkeypatch.setattr(os, "fsync", flaky)

    assert _run(world) == fb.EXIT_REFUSED
    assert not any(p.exists() for p in _four(world))
    assert not list(world.out().glob("*.tmp"))


def test_stale_tmp_files_from_an_interrupted_run_are_cleaned_not_fatal(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    out = world.out()
    out.mkdir(parents=True)
    stale = [
        out / "features.jsonl.tmp",
        out / "features_lag60.jsonl.tmp",
        out / "features.jsonl.manifest.json.tmp",
        out / "features_lag60.jsonl.manifest.json.tmp",
    ]
    for path in stale:
        path.write_text("half written", encoding="utf-8")

    assert _run(world) == fb.EXIT_OK

    assert not any(p.exists() for p in stale)
    assert all(p.is_file() for p in _four(world))


# ------------------------------------------------------------------ item 7: guards and the F2 file


def test_the_f2_truth_file_is_a_protected_input(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    f2 = tmp_path / "f2.csv"
    f2.write_text("climate_day,city,tmax_f\n", encoding="utf-8")
    argv = world.argv("a", "--f2-truth", str(f2))
    argv[argv.index("--out-features") + 1] = str(f2)

    assert fb.main(argv) == fb.EXIT_REFUSED

    assert "input root" in world.report()["reason"]
    assert f2.read_text(encoding="utf-8") == "climate_day,city,tmax_f\n"


def test_sealed_f2_rows_are_never_value_parsed(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    f2 = tmp_path / "f2.csv"
    f2.write_text(
        "station,city,climate_day,tmax_f,tmax_flag\n"
        "NYC,NYC,2021-03-13,50,\n"
        "NYC,NYC,2026-07-02,not-a-number,\n"
        "NYC,NYC,2026-12-31,,\n",
        encoding="utf-8",
    )

    assert _run(world, "a", "--f2-truth", str(f2)) == fb.EXIT_OK

    concord = world.report()["truth_concordance"]
    assert concord["n_overlap"] == 1 and concord["n_disagree"] == 0


def test_the_concordance_reads_the_date_before_any_other_column(tmp_path: Path) -> None:
    f2 = tmp_path / "f2.csv"
    f2.write_text("climate_day,city\n2026-07-05,\n", encoding="utf-8")  # sealed, no tmax_f column

    assert report_mod.truth_concordance(f2, {})["n_overlap"] == 0


# ------------------------------------------------------------------ item 8: basis per horizon


class _StubLamp:
    """A LAMP archive whose basis is a function of (anchor day, hour): D-1 anchors are 18Z."""

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    def runs_for(self, _station: str, *, anchor_ns: int) -> lampmod.LampRunChoice:
        when = dt.datetime.fromtimestamp(anchor_ns // 10**9, tz=dt.UTC)
        lav_from_d_minus_1 = when.hour == 18 and when.date() >= dt.date(2021, 3, 13)
        return lampmod.LampRunChoice((), "lav" if lav_from_d_minus_1 else "mdl")


def test_a_d_minus_1_only_lamp_basis_break_is_visible_per_horizon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = _build_world(tmp_path)
    monkeypatch.setattr(fb, "LampArchive", _StubLamp)

    assert _run(world) == fb.EXIT_OK

    breaks = world.report()["source_breaks_observed"]
    # D-1 anchors for 3/13 (3/12 18Z) are mdl, for 3/14 (3/13 18Z) lav; D0 stays mdl throughout
    assert breaks["lamp_by_horizon"] == {"D-1": ["2021-03-14"], "D0": []}
    assert breaks["lamp"] == ["2021-03-14"]


# ------------------------------------------------------------------ item 9: shifted re-check


def _row(**overrides: Any) -> FeatureRow:
    base: dict[str, Any] = {
        "station": "NYC",
        "climate_day": dt.date(2021, 3, 13),
        "version": "v4.2",
        "horizon": "D0",
        "anchor_ns": 10_000 * 10**9,
        "percentiles": Percentiles(q10=40, q25=45, q50=50, q75=55, q90=60, mean=50, sd=5),
        "cli_tmax_f": 50.0,
    }
    base.update(overrides)
    return FeatureRow(**base)


def test_the_leakage_assertion_takes_the_extra_lag_for_pfm_mos_and_lamp() -> None:
    anchor = 10_000 * 10**9
    half_hour_before = anchor - 1_800 * 10**9
    for field in ("pfm", "mos"):
        row = _row(
            anchor_ns=anchor,
            **{f"{field}_mu_f": 50.0, f"{field}_available_at_ns": half_hour_before},
        )
        msb.assert_row_leakage_free(row)  # fine unshifted
        with pytest.raises(LeakageError):
            msb.assert_row_leakage_free(row, extra_lag_ns=LAG_SHIFT_NS)
    lamp = LampFeature(55.0, 3, True, False, half_hour_before, anchor + 1, None)
    row = _row(anchor_ns=anchor, lamp=lamp)
    msb.assert_row_leakage_free(row)
    with pytest.raises(LeakageError):
        msb.assert_row_leakage_free(row, extra_lag_ns=LAG_SHIFT_NS)


def test_the_builder_rechecks_the_twin_with_the_shifted_availability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = _build_world(tmp_path)
    extras: list[int] = []
    real = msb.assert_row_leakage_free

    def spy(row: FeatureRow, **kwargs: Any) -> None:
        extras.append(kwargs.get("extra_lag_ns", 0))
        real(row, **kwargs)

    monkeypatch.setattr(msb, "assert_row_leakage_free", spy)

    assert _run(world) == fb.EXIT_OK

    assert extras.count(LAG_SHIFT_NS) == 4 and extras.count(0) == 4


def test_a_twin_row_that_ignored_the_shift_is_refused_at_the_post_build_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = _build_world(tmp_path)
    real = assemble_feature_row

    def forgetful(**kwargs: Any) -> FeatureRow:
        return real(**{**kwargs, "extra_lag_ns": 0})  # builds the twin as if it were unshifted

    monkeypatch.setattr(fb, "assemble_feature_row", forgetful)

    assert _run(world) == fb.EXIT_REFUSED

    assert "Leakage" in world.report()["reason"]
    assert not (world.out() / "features_lag60.jsonl").exists()


# ------------------------------------------------------------------ item 2 support: the cycle id


def test_builder_rows_carry_the_nbp_cycle_id_as_metadata(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    _run(world)

    rows = {(r.climate_day, r.horizon): r for r in world.rows()}

    assert rows[(_D13, "D0")].nbp_cycle_ns == ns(utc(2021, 3, 13, 1))
    assert rows[(_D13, "D-1")].nbp_cycle_ns == ns(utc(2021, 3, 12, 13))
    assert rows[(_D14, "D-1")].nbp_cycle_ns == ns(utc(2021, 3, 13, 13))


def test_the_twin_rows_record_the_cycle_they_actually_used(tmp_path: Path) -> None:
    world = _build_world(tmp_path, slow_nbp_cycle=True)
    _run(world)

    lag = {(r.climate_day, r.horizon): r for r in world.rows(name="features_lag60.jsonl")}

    assert (_D13, "D-1") not in lag
    assert lag[(_D13, "D0")].nbp_cycle_ns == ns(utc(2021, 3, 13, 1))


# ------------------------------------------------------------------ item 10: PFM day labels at DST


def _utc_midnight_after(day: dt.date) -> dt.datetime:
    return dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC) + dt.timedelta(days=1)


def _assert_labels_are_lst_climate_days(vintages: dict[dt.date, list[Any]], offset: float) -> None:
    days = sorted(vintages)
    assert days == [days[0] + dt.timedelta(days=i) for i in range(len(days))]  # no skip, no dup
    for day in days:
        # the MAX column ends at 00Z after the local afternoon: 7 pm LST of ``day``
        instant = _utc_midnight_after(day) - dt.timedelta(seconds=1)
        assert climate_day_for_instant(instant, offset) == day


def test_pfm_day_labels_across_the_march_transition_are_the_lst_climate_days(
    tmp_path: Path,
) -> None:
    issued = utc(2021, 3, 12, 23, 5)  # the table runs 3/12 .. 3/19: DST starts 3/14
    write_pfm_product(
        tmp_path,
        station="KNYC",
        wfo="OKX",
        issued=issued,
        text=_fixture("pfm_okx_real_20210312.txt"),
    )

    found = forecast.collect_pfm_vintages(
        fb.read_only_cache(tmp_path),
        icao="KNYC",
        lag_ns=3_600 * 10**9,
        end_exclusive=dt.date(2026, 7, 1),
        counts=Counter(),
    )

    assert {dt.date(2021, 3, 13), dt.date(2021, 3, 14), dt.date(2021, 3, 15)} <= set(found)
    _assert_labels_are_lst_climate_days(found, -5.0)


def _november_okx_product() -> str:
    """The real 2026-10-06 OKX product moved 26 days: issued 10/31, DST ends 11/1."""
    text = _fixture("pfm_okx_real_20261006.txt")
    for old, new in (
        ("10/05/26", "10/31/26"),
        ("10/06/26", "11/01/26"),
        ("10/07/26", "11/02/26"),
        ("10/08", "11/03"),
        ("10/09/26", "11/04/26"),
        ("10/10/26", "11/05/26"),
        ("10/11/26", "11/06/26"),
        ("10/12/26", "11/07/26"),
        ("Mon Oct 5 2026", "Sat Oct 31 2026"),
        ("051901", "311901"),
        ("060800", "010800"),
    ):
        text = text.replace(old, new)
    return text


def test_pfm_day_labels_across_the_november_transition_are_the_lst_climate_days(
    tmp_path: Path,
) -> None:
    issued = utc(2026, 10, 31, 19, 1)
    write_pfm_product(
        tmp_path, station="KNYC", wfo="OKX", issued=issued, text=_november_okx_product()
    )

    found = forecast.collect_pfm_vintages(
        fb.read_only_cache(tmp_path),
        icao="KNYC",
        lag_ns=3_600 * 10**9,
        end_exclusive=dt.date(2027, 1, 1),
        counts=Counter(),
    )

    assert {dt.date(2026, 11, 1), dt.date(2026, 11, 2), dt.date(2026, 11, 3)} <= set(found)
    _assert_labels_are_lst_climate_days(found, -5.0)


# ------------------------------------------------------------------ item 11: hashing and size


def test_files_are_hashed_in_chunks_and_match_hashlib(tmp_path: Path) -> None:
    path = tmp_path / "big.bin"
    payload = os.urandom(5 * 1024 + 7)
    path.write_bytes(payload)

    assert sidecar.sha256_file(path, chunk_size=1024) == hashlib.sha256(payload).hexdigest()
    assert sidecar.sha256_file(path) == hashlib.sha256(payload).hexdigest()


def test_the_builders_input_hash_is_absent_for_a_missing_file_and_never_reads_it_whole(
    tmp_path: Path,
) -> None:
    assert fb._sha256(tmp_path / "nope") == "absent"
    for module in (_BUILDER, _REPO / "scripts" / "analysis" / "multisource_blend_skill.py"):
        assert ".read_bytes()" not in module.read_text(encoding="utf-8"), module.name


def test_no_type_ignore_remains_on_the_forecast_reader_cache_entries() -> None:
    text = (_REPO / "scripts" / "analysis" / "multisource_blend_inputs_forecast.py").read_text(
        encoding="utf-8"
    )
    assert "type: ignore[attr-defined]" not in text


def test_the_builder_module_stays_under_800_lines() -> None:
    assert len(_BUILDER.read_text(encoding="utf-8").splitlines()) < 800


def test_no_builder_function_is_longer_than_50_lines() -> None:
    import ast

    tree = ast.parse(_BUILDER.read_text(encoding="utf-8"))
    long = [
        (node.name, node.end_lineno - node.lineno + 1)  # type: ignore[operator]
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.end_lineno - node.lineno + 1 > 50  # type: ignore[operator]
    ]
    assert long == []
