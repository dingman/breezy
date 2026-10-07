"""F13 Phase A feature assembly: ``scripts/analysis/multisource_blend_features_build.py``.

One synthetic world (KNYC, climate days 2021-03-13 and 2021-03-14, EST, the week DST starts) is
written with the PRODUCTION writers into tmp stores (L-42) and the builder runs through ``main()``
with its default readers (L-55); nothing reads the live data root or the network. The world is
hand-derived (see ``_World``): every expected value below was computed from the inputs, not from
the code under test.

Expected rows (anchor D-1 = 18Z of the day before, D0 = 10:00 LST = 15Z, fixed EST):

* (3/13, D-1): LAMP MISSING (the 16:30Z run does not reach LST hours 13..18), PFM absent (its
  availability 3/13 14:50Z is after the anchor), MOS 88 (12Z run, available 17Z), no obs;
* (3/13, D0): LAMP 74, PFM 47, MOS 85, obs 44; the +60 min twin loses LAMP and PFM, has obs 43;
* (3/14, D-1): LAMP MISSING, PFM 55, MOS 88, no obs; (3/14, D0): LAMP 74, PFM 55, MOS 88, obs 44.
"""

from __future__ import annotations

import ast
import datetime as dt
import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from breezy.analysis import multisource_blend as msb
from breezy.analysis.multisource_blend_features import LeakageError
from breezy.persistence.archive_cache import iem_mos_window_request
from scripts.analysis import multisource_blend_features_build as fb
from scripts.analysis import multisource_blend_skill as skill
from tests.unit.featbuild_fixtures import (
    HOUR_NS,
    NS,
    asos_1min_payload,
    ns,
    truth_row,
    utc,
    write_asos_year,
    write_cache_entry,
    write_mdl_run,
    write_nbp_cycle,
    write_pfm_product,
    write_truth,
)
from tests.unit.test_multisource_blend_skill import _PREREG_SRC
from tests.unit.test_us_source_pfm_history import _FIXTURES, _fixture

_MIN = 60 * NS
_HOLDOUT = dt.date(2026, 7, 1)
_D13, _D14 = dt.date(2021, 3, 13), dt.date(2021, 3, 14)
_LAMP_TEMPS = [60 + i for i in range(25)]
_LAGS_NS = {
    "lamp-mdl": 60 * _MIN,
    "lav-iem": 90 * _MIN,
    "pfm": 15 * 60 * _MIN + 45 * _MIN,  # 23:05Z + 15h45 = 14:50Z next day: before 15Z, not +60
    "mos-gfs": 5 * 60 * _MIN,
    "obs": 15 * _MIN,
}
_ANCHORS: dict[str, Any] = {
    "D-1": {"kind": "utc", "hour": 18},
    "D0": {"kind": "lst", "hour": 10},
    "D0_sensitivity": {"kind": "lst", "hour": 12},
    "offset_rule": "fixed_standard_time_never_dst",
}


def _pins(**overrides: Any) -> dict[str, Any]:
    pins: dict[str, Any] = {
        "anchors": _ANCHORS,
        "source_lags_ns": dict(_LAGS_NS),
        "obs_source": "iem_asos_1min_whole_f_via_metar_tgroup_quantisation",
        "obs_cadence_seconds": 300,
    }
    pins.update(overrides)
    return pins


@dataclass
class _World:
    root: Path
    prereg: Path
    nbp: Path
    us: Path
    mos: Path
    asos: Path
    truth: Path

    def argv(
        self,
        tag: str = "a",
        *extra: str,
        end: str = "2021-03-14",
        start: str = "2021-03-13",
    ) -> list[str]:
        out = self.root / f"out_{tag}"
        return [
            "--prereg", str(self.prereg),
            "--nbp-root", str(self.nbp),
            "--us-source-root", str(self.us),
            "--mos-root", str(self.mos),
            "--asos-root", str(self.asos),
            "--truth", str(self.truth),
            "--start", start,
            "--end", end,
            "--stations", "KNYC",
            "--out-features", str(out / "features.jsonl"),
            "--out-lag-features", str(out / "features_lag60.jsonl"),
            "--report-json", str(out / "report.json"),
            *extra,
        ]  # fmt: skip

    def out(self, tag: str = "a") -> Path:
        return self.root / f"out_{tag}"

    def rows(self, tag: str = "a", name: str = "features.jsonl") -> list[msb.FeatureRow]:
        lines = (self.out(tag) / name).read_text(encoding="utf-8").splitlines()
        return [msb.feature_row_from_json(json.loads(ln)) for ln in lines]

    def report(self, tag: str = "a") -> dict[str, Any]:
        report: dict[str, Any] = json.loads(
            (self.out(tag) / "report.json").read_text(encoding="utf-8")
        )
        return report


def _gfs_for_knyc() -> bytes:
    """The real IEM GFS-MOS fixture, its calendar moved to 2021-03-12 and its station to KNYC."""
    text = (_FIXTURES.parent / "iem" / "mos_GFS_KMIA_2021-06-15_1day.csv").read_text()
    for old, new in (
        ("06-18", "03-15"),
        ("06-17", "03-14"),
        ("06-16", "03-13"),
        ("06-15", "03-12"),
    ):
        text = text.replace(f"2021-{old}", f"2021-{new}")
    return text.replace(",KMIA,", ",KNYC,").encode("utf-8")


def _asos_rows() -> list[tuple[dt.datetime, int | str]]:
    rows: list[tuple[dt.datetime, int | str]] = []
    when = utc(2021, 3, 12)
    while when < utc(2021, 3, 15, 6):
        rows.append((when, 30 + when.hour))  # whole degF, hour of day
        when += dt.timedelta(minutes=5)
    return rows


def _build_world(
    tmp_path: Path, *, slow_nbp_cycle: bool = False, pins: dict[str, Any] | None = None
) -> _World:
    root = tmp_path
    nbp, us, mos, asos = root / "nbp", root / "us", root / "mos", root / "asos"
    # NBP: the 13Z / 19Z of the day before and the 01Z of the day itself target each climate day
    for cycle_day, hour, q50 in (
        (dt.date(2021, 3, 12), 13, 80.0),
        (dt.date(2021, 3, 12), 19, 81.0),
        (dt.date(2021, 3, 13), 1, 82.0),
        (dt.date(2021, 3, 13), 13, 83.0),
        (dt.date(2021, 3, 13), 19, 84.0),
        (dt.date(2021, 3, 14), 1, 85.0),
    ):
        slow = slow_nbp_cycle and (cycle_day, hour) == (dt.date(2021, 3, 12), 13)
        write_nbp_cycle(
            nbp,
            station="KNYC",
            cycle_day=cycle_day,
            cycle_hour=hour,
            q50=q50,
            available_after_ns=(4 * HOUR_NS + 30 * _MIN) if slow else 2 * HOUR_NS,
        )
    # LAMP MDL runs (KNYC and a KLAX block that must never leak into KNYC)
    for run_at in (
        utc(2021, 3, 12, 16, 30),
        utc(2021, 3, 13, 13, 30),
        utc(2021, 3, 13, 16, 30),
        utc(2021, 3, 14, 13, 30),
    ):
        write_mdl_run(us, run_at=run_at, temps_by_station={"KNYC": _LAMP_TEMPS, "KLAX": [90] * 25})
    # PFM: the real OKX product of 2021-03-12 23:05Z, then a later REVISION that changes a cell
    original = _fixture("pfm_okx_real_20210312.txt")
    write_pfm_product(
        us,
        station="KNYC",
        wfo="OKX",
        issued=utc(2021, 3, 12, 23, 5),
        text=original,
        revision_texts=[original.replace("          47", "          49", 1)],
    )
    write_cache_entry(
        mos,
        iem_mos_window_request("KNYC", dt.date(2021, 3, 12), dt.date(2021, 3, 13), "GFS"),
        _gfs_for_knyc(),
    )
    write_asos_year(asos, "KNYC", 2021, asos_1min_payload(_asos_rows(), station="NYC"))
    truth = write_truth(
        root / "truth" / "settlement_truth.parquet",
        [
            truth_row(station="NYC", climate_day=_D13, tmax_f=50),
            truth_row(station="NYC", climate_day=_D14, tmax_f=56),
            truth_row(station="NYC", climate_day=dt.date(2026, 7, 2), tmax_f=99),  # sealed
        ],
    )
    design = json.loads(_PREREG_SRC.read_text(encoding="utf-8"))
    design["pins"] = {**design["pins"], **(pins if pins is not None else _pins())}
    prereg = root / "prereg.json"
    prereg.write_text(json.dumps(design, indent=2), encoding="utf-8")
    return _World(root, prereg, nbp, us, mos, asos, truth)


@pytest.fixture(autouse=True)
def _no_process_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """``main()`` lowers RLIMIT_AS; that must never hit the pytest process."""
    monkeypatch.setattr(fb, "apply_address_space_cap", lambda _gib: 0)


def _run(world: _World, tag: str = "a", *extra: str, **kwargs: str) -> int:
    return fb.main(world.argv(tag, *extra, **kwargs))


def _by_key(rows: Sequence[msb.FeatureRow]) -> dict[tuple[dt.date, str], msb.FeatureRow]:
    return {(r.climate_day, r.horizon): r for r in rows}


# ------------------------------------------------------------------ output shape


def test_output_line_roundtrips_feature_row_from_json_and_has_no_header(tmp_path: Path) -> None:
    world = _build_world(tmp_path)

    assert _run(world) == fb.EXIT_OK

    text = (world.out() / "features.jsonl").read_text(encoding="utf-8")
    lines = text.splitlines()
    assert len(lines) == 4 and text.endswith("\n")
    for line in lines:
        data = json.loads(line)
        assert "header" not in data and data["horizon"] in {"D0", "D-1"}
        assert msb.feature_row_to_json(msb.feature_row_from_json(data)) == data
        assert line == json.dumps(data, sort_keys=True)
    assert lines == sorted(
        lines, key=lambda ln: (json.loads(ln)["climate_day"], json.loads(ln)["horizon"])
    )


def test_builder_output_loads_through_the_runners_loader_end_to_end(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    _run(world)

    primary = skill._load_rows(world.out() / "features.jsonl")
    lag = skill._load_rows(world.out() / "features_lag60.jsonl")

    assert len(primary) == len(lag) == 4
    assert {r.station for r in primary} == {"NYC"}


# ------------------------------------------------------------------ the hand-derived rows


def test_every_feature_matches_the_hand_derived_world(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    _run(world)
    rows = _by_key(world.rows())

    d13m1, d13, d14m1, d14 = (
        rows[(_D13, "D-1")],
        rows[(_D13, "D0")],
        rows[(_D14, "D-1")],
        rows[(_D14, "D0")],
    )
    assert d13m1.anchor_ns == ns(utc(2021, 3, 12, 18)) and d14m1.anchor_ns == ns(
        utc(2021, 3, 13, 18)
    )
    assert d13.anchor_ns == ns(utc(2021, 3, 13, 15)) and d14.anchor_ns == ns(utc(2021, 3, 14, 15))
    # NBP: the latest cycle available before the anchor; its era and percentiles ride along
    assert (d13m1.percentiles.q50, d13.percentiles.q50) == (80.0, 82.0)
    assert (d14m1.percentiles.q50, d14.percentiles.q50) == (83.0, 85.0)
    assert d13m1.version == "v4.2" and d13m1.cli_tmax_f == 50.0 and d14.cli_tmax_f == 56.0
    # LAMP: D-1 MISSING (R37), D0 present; hours strictly after the anchor inside the LST day
    assert d13m1.lamp.missing and d14m1.lamp.missing
    assert d13m1.lamp.run_available_at_ns == ns(utc(2021, 3, 12, 17, 30))
    assert not d13.lamp.missing and d13.lamp.rem_max_f == 74.0 and d13.lamp.hours_covered == 13
    assert d13.lamp.run_available_at_ns == ns(utc(2021, 3, 13, 14, 30))
    assert d13.lamp.min_valid_ts_ns == ns(utc(2021, 3, 13, 16)) > d13.anchor_ns
    # PFM: the FIRST revision (47, not the revised 49), available at issuance + the pinned lag
    assert d13m1.pfm_mu_f is None and d13.pfm_mu_f == 47.0 and d14m1.pfm_mu_f == 55.0
    assert d13.pfm_available_at_ns == ns(utc(2021, 3, 12, 23, 5)) + _LAGS_NS["pfm"]
    # MOS: runtime + 5 h, the latest runtime strictly before the anchor
    assert (d13m1.mos_mu_f, d13.mos_mu_f, d14m1.mos_mu_f, d14.mos_mu_f) == (88.0, 85.0, 88.0, 88.0)
    assert d13m1.mos_available_at_ns == ns(utc(2021, 3, 12, 12)) + 5 * HOUR_NS
    # obs: whole degF at the cadence, available 15 min after the report, never after the anchor
    assert d13m1.obs_so_far_f is None and d14m1.obs_so_far_f is None
    assert (d13.obs_so_far_f, d14.obs_so_far_f) == (44.0, 44.0)
    assert d13.obs_available_at_ns == ns(utc(2021, 3, 13, 14, 40)) + 15 * _MIN < d13.anchor_ns


def test_dm1_archive_row_lamp_missing_r37_is_counted_per_horizon(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    _run(world)

    report = world.report()

    assert report["by_horizon"]["D-1"]["lamp_missing"] == 2
    assert report["by_horizon"]["D0"]["lamp_missing"] == 0
    assert report["by_horizon"]["D-1"]["rows"] == report["by_horizon"]["D0"]["rows"] == 2


def test_d0_row_lamp_rem_hours_after_anchor_only(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    _run(world)
    row = _by_key(world.rows())[(_D13, "D0")]

    # idx 0 is valid at 14Z, i.e. BEFORE the 15Z anchor; the hours that count start at 16Z and
    # stop before the next LST midnight (3/14 05Z): idx 2..14, max 60 + 14
    assert row.lamp.rem_max_f == 74.0 and row.lamp.min_valid_ts_ns is not None
    assert row.lamp.min_valid_ts_ns > row.anchor_ns


def test_obs_reading_after_anchor_excluded_and_never_lamp(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    _run(world)
    row = _by_key(world.rows())[(_D13, "D0")]

    # the 15:00 and later archive rows (45, 46, ...) exist but are not available before 15Z
    assert row.obs_so_far_f == 44.0
    assert row.obs_available_at_ns is not None and row.obs_available_at_ns < row.anchor_ns
    assert world.report()["obs"]["source"] == "iem_asos_1min_whole_f_via_metar_tgroup_quantisation"


# ------------------------------------------------------------------ the +60 min twin (FB-R2)


def test_lag_shift_moves_every_source_including_nbp_and_obs_availability(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    _run(world)
    base, lag = _by_key(world.rows()), _by_key(world.rows(name="features_lag60.jsonl"))

    # LAMP and PFM move out of reach, obs steps back one reading and its availability is shifted
    assert not base[(_D13, "D0")].lamp.missing and lag[(_D13, "D0")].lamp.missing
    assert base[(_D13, "D0")].pfm_mu_f == 47.0 and lag[(_D13, "D0")].pfm_mu_f is None
    assert lag[(_D13, "D0")].obs_so_far_f == 43.0
    shifted = lag[(_D13, "D0")].obs_available_at_ns
    assert shifted == ns(utc(2021, 3, 13, 13, 40)) + 15 * _MIN + HOUR_NS
    # MOS: the 12Z run (available 17Z) is not before the shifted 18Z anchor, so the 06Z run (89)
    assert base[(_D13, "D-1")].mos_mu_f == 88.0 and lag[(_D13, "D-1")].mos_mu_f == 89.0
    assert all(r.cli_tmax_f == base[k].cli_tmax_f for k, r in lag.items())  # the label never moves
    assert world.report()["lag_file"]["obs_available_at_ns_shifted"] is True


def test_lag_file_has_identical_keys_and_one_row_per_key(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    _run(world)

    for name in ("features.jsonl", "features_lag60.jsonl"):
        keys = [(r.station, r.climate_day, r.horizon) for r in world.rows(name=name)]
        assert len(keys) == len(set(keys)) == 4
    base = {(r.climate_day, r.horizon) for r in world.rows()}
    lag = {(r.climate_day, r.horizon) for r in world.rows(name="features_lag60.jsonl")}
    assert base == lag


def test_a_row_whose_nbp_cycle_is_shifted_out_is_lost_and_reported_per_horizon(
    tmp_path: Path,
) -> None:
    world = _build_world(tmp_path, slow_nbp_cycle=True)  # 13Z cycle available 17:30Z

    assert _run(world) == fb.EXIT_OK

    base = {(r.climate_day, r.horizon) for r in world.rows()}
    lag = {(r.climate_day, r.horizon) for r in world.rows(name="features_lag60.jsonl")}
    assert base - lag == {(_D13, "D-1")} and lag <= base
    assert world.report()["lag_file"]["rows_lost_by_horizon"] == {"D-1": 1}


def test_lamp_pfm_and_mos_losses_are_reported_by_source(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    _run(world)

    assert world.report()["lag_file"]["source_rows_lost"] == {"lamp": 2, "pfm": 1, "mos": 0}


# ------------------------------------------------------------------ anchors (FB-R1)


@pytest.mark.parametrize(
    ("offset", "utc_hour"), [(-5.0, 15), (-6.0, 16), (-8.0, 18)], ids=["EST", "CST", "PST"]
)
def test_d0_anchor_is_10_lst_on_fixed_standard_time_never_dst(offset: float, utc_hour: int) -> None:
    anchors = fb.parse_anchors(_ANCHORS)
    july = dt.date(2021, 7, 15)  # EDT/CDT/PDT in force: the anchor must not move

    assert fb.anchor_ns_for("D0", july, offset, anchors) == ns(utc(2021, 7, 15, utc_hour))
    assert fb.anchor_ns_for("D-1", july, offset, anchors) == ns(utc(2021, 7, 14, 18))


def test_the_d0_12_lst_sensitivity_builds_a_separate_pair_with_its_own_anchor(
    tmp_path: Path,
) -> None:
    world = _build_world(tmp_path)

    assert _run(world, "primary") == fb.EXIT_OK
    assert _run(world, "sens", "--anchor-variant", "d0_12lst") == fb.EXIT_OK

    primary, sens = _by_key(world.rows("primary")), _by_key(world.rows("sens"))
    assert sens[(_D13, "D0")].anchor_ns == ns(utc(2021, 3, 13, 17))
    assert primary[(_D13, "D0")].anchor_ns == ns(utc(2021, 3, 13, 15))
    assert sens[(_D13, "D-1")].anchor_ns == primary[(_D13, "D-1")].anchor_ns
    assert world.report("sens")["anchor_variant"] == "d0_12lst"


def test_anchor_pin_shapes_are_validated() -> None:
    bad = {**_ANCHORS, "D0": {"kind": "lst", "hour": 24}}
    with pytest.raises(fb.BuildRefusal, match="anchors"):
        fb.parse_anchors(bad)
    with pytest.raises(fb.BuildRefusal, match="offset_rule"):
        fb.parse_anchors({**_ANCHORS, "offset_rule": "dst_aware"})


# ------------------------------------------------------------------ pins and lags (FB-R4)


def test_lag_below_conservative_refused(tmp_path: Path) -> None:
    lags = {**_LAGS_NS, "lamp-mdl": 30 * _MIN}
    world = _build_world(tmp_path, pins=_pins(source_lags_ns=lags))

    assert _run(world) == fb.EXIT_REFUSED

    assert not (world.out() / "features.jsonl").exists()
    assert "lamp-mdl" in world.report()["reason"]


@pytest.mark.parametrize(
    "pins",
    [
        {"obs_cadence_seconds": 60},
        {"obs_source": "iem_asos_1min_raw"},
        {"anchors": None},
        {"source_lags_ns": None},
        {"source_lags_ns": {k: v for k, v in _LAGS_NS.items() if k != "obs"}},
    ],
)
def test_null_or_unaccepted_builder_pins_are_refused(tmp_path: Path, pins: dict[str, Any]) -> None:
    world = _build_world(tmp_path, pins=_pins(**pins))

    assert _run(world) == fb.EXIT_REFUSED
    assert not (world.out() / "features.jsonl").exists()


def test_every_lag_basis_is_flagged_provisional_in_the_report(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    _run(world)

    lags = world.report()["source_lags"]

    assert set(lags) == {"lamp-mdl", "lav-iem", "pfm", "mos-gfs", "obs", "nbp"}
    assert all(item["basis"] for item in lags.values())
    assert lags["pfm"]["ns"] == _LAGS_NS["pfm"] and lags["pfm"]["provisional"] is True
    assert lags["nbp"]["basis"].startswith("nominal")


# ------------------------------------------------------------------ holdout


def test_end_on_or_after_2026_07_01_refused_exit_2(tmp_path: Path) -> None:
    world = _build_world(tmp_path)

    assert _run(world, end="2026-07-01") == fb.EXIT_REFUSED

    assert not (world.out() / "features.jsonl").exists()
    assert "2026-07-01" in world.report()["reason"]


def test_truth_read_filtered_before_holdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts.analysis import nbp_skill_study as nss

    world = _build_world(tmp_path)
    seen: list[dt.date | None] = []
    real = nss.read_settlement_truth_rows

    def spy(path: Path, *, climate_day_before: dt.date | None = None) -> Any:
        seen.append(climate_day_before)
        return real(path, climate_day_before=climate_day_before)

    monkeypatch.setattr(nss, "read_settlement_truth_rows", spy)

    assert _run(world) == fb.EXIT_OK

    assert seen == [_HOLDOUT]
    assert all(r.climate_day < _HOLDOUT for r in world.rows())


def test_open_holdout_never_imported_ast() -> None:
    root = Path(fb.__file__).resolve().parent
    for name in (
        "multisource_blend_features_build",
        "multisource_blend_inputs_lamp",
        "multisource_blend_inputs_forecast",
        "multisource_blend_inputs_obs",
    ):
        tree = ast.parse((root / f"{name}.py").read_text(encoding="utf-8"))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names |= {
            a.name
            for n in ast.walk(tree)
            if isinstance(n, ast.ImportFrom | ast.Import)
            for a in n.names
        }
        assert "open_holdout" not in names, name


def test_holdout_sealed_manifest_rows_never_read(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    # a sealed-in-manifest run of an in-range date: the builder must behave as if it were absent
    write_mdl_run(
        world.us,
        run_at=utc(2021, 3, 13, 14, 30),
        temps_by_station={"KNYC": [10] * 25},
        sealed_in_manifest=True,
    )

    assert _run(world) == fb.EXIT_OK

    row = _by_key(world.rows())[(_D13, "D0")]
    assert row.lamp.rem_max_f == 74.0  # the sealed run's 10 F never appeared
    assert world.report()["counts"]["lamp_holdout_sealed_skipped"] == 1


# ------------------------------------------------------------------ paths, report, atomicity


def test_refuses_live_root_and_existing_output(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    live = Path.home() / ".local" / "share" / "breezy" / "featbuild_must_not_exist" / "f.jsonl"
    argv = world.argv()
    argv[argv.index("--out-features") + 1] = str(live)

    assert fb.main(argv) == fb.EXIT_REFUSED
    assert not live.parent.exists()

    (world.out("b")).mkdir(parents=True)
    existing = world.out("b") / "features.jsonl"
    existing.write_text("precious\n", encoding="utf-8")
    assert fb.main(world.argv("b")) == fb.EXIT_REFUSED
    assert existing.read_text(encoding="utf-8") == "precious\n"


def test_an_output_inside_an_input_root_is_refused(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    argv = world.argv()
    argv[argv.index("--out-features") + 1] = str(world.nbp / "features.jsonl")

    assert fb.main(argv) == fb.EXIT_REFUSED
    assert not (world.nbp / "features.jsonl").exists()


def test_report_written_on_refusal(tmp_path: Path) -> None:
    world = _build_world(tmp_path, pins=_pins(obs_cadence_seconds=60))

    assert _run(world) == fb.EXIT_REFUSED

    report = world.report()
    assert report["status"] == "refused" and report["exit_code"] == 2
    assert "obs_cadence_seconds" in report["reason"]


def test_leakage_error_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    world = _build_world(tmp_path)

    def boom(**_kwargs: Any) -> Any:
        raise LeakageError("synthetic leak")

    monkeypatch.setattr(fb, "assemble_feature_row", boom)

    assert _run(world) == fb.EXIT_REFUSED

    out = world.out()
    assert not (out / "features.jsonl").exists()
    assert not (out / "features_lag60.jsonl").exists()
    assert not list(out.glob("*.manifest.json"))
    assert world.report()["status"] == "refused" and "synthetic leak" in world.report()["reason"]


def test_a_degraded_run_exits_1_with_its_outputs_written(tmp_path: Path) -> None:
    from breezy.persistence.nbp_derived_store import partition_path

    world = _build_world(tmp_path)
    broken = partition_path(world.nbp, dt.date(2021, 3, 1), 13)
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_bytes(b"not a parquet file")

    assert _run(world) == fb.EXIT_DEGRADED

    assert len(world.rows()) == 4
    report = world.report()
    assert report["status"] == "degraded" and report["counts"]["nbp_partition_unreadable"] == 1


def test_gfs_payload_that_is_not_gfs_is_refused_exit_2(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    nbs = _gfs_for_knyc().replace(b",GFS,", b",NBS,")
    other = tmp_path / "mos_bad"
    write_cache_entry(
        other,
        iem_mos_window_request("KNYC", dt.date(2021, 3, 12), dt.date(2021, 3, 13), "GFS"),
        nbs,
    )
    argv = world.argv()
    argv[argv.index("--mos-root") + 1] = str(other)

    assert fb.main(argv) == fb.EXIT_REFUSED
    assert not (world.out() / "features.jsonl").exists()
    assert "model" in world.report()["reason"].lower()


def test_a_mos_coverage_gap_is_reported_and_the_run_still_completes(tmp_path: Path) -> None:
    world = _build_world(tmp_path)

    assert _run(world) == fb.EXIT_OK

    assert world.report()["counts"]["mos_coverage_gap_days"] > 0


def test_the_report_cites_the_live_obs_path_and_flags_what_is_not_emulated(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    _run(world)

    obs = world.report()["obs"]

    assert "running_extreme" in obs["live_path"] and "iem_observations" in obs["live_path"]
    assert obs["cadence_seconds"] == 300 and obs["interval_rows_not_emulated"] is True
    assert obs["raw_1min_running_max_is_descriptive_only"] is True
    assert obs["d0_rows_where_raw_1min_max_differs"] == 2  # 45 at 15:00 vs the cadence feature 44
    assert "qc_revision_risk" in obs


def test_truth_concordance_counts_the_f2_disagreements(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    f2 = tmp_path / "f2.csv"
    f2.write_text(
        "station,city,climate_day,tmax_f,tmax_flag,correction_flag,issued_at_utc,"
        "product_sha256,revision_fetch_date,revision_sha256\n"
        "NYC,NYC,2021-03-13,50,,False,,x,2026-10-06,y\n"
        "NYC,NYC,2021-03-14,57,,False,,x,2026-10-06,y\n"
        "NYC,NYC,2026-07-02,12,,False,,x,2026-10-06,y\n",
        encoding="utf-8",
    )

    assert _run(world, "a", "--f2-truth", str(f2)) == fb.EXIT_OK

    concord = world.report()["truth_concordance"]
    assert concord["n_overlap"] == 2 and concord["n_disagree"] == 1
    assert concord["disagreements"] == [
        {"station": "NYC", "climate_day": "2021-03-14", "champion": 56, "f2": 57}
    ]


# ------------------------------------------------------------------ sidecar (FB-R10)


def test_sidecars_record_the_prereg_digest_the_file_shas_and_the_pins(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    _run(world)
    digest = skill.content_digest(json.loads(world.prereg.read_text(encoding="utf-8")))

    for role, name in (("primary", "features.jsonl"), ("lag", "features_lag60.jsonl")):
        path = world.out() / name
        side = json.loads(Path(str(path) + skill.SIDECAR_SUFFIX).read_text(encoding="utf-8"))
        assert side["schema"] == skill.SIDECAR_SCHEMA and side["role"] == role
        assert side["prereg_content_sha256"] == digest
        assert side["features_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert side["anchors"] == _ANCHORS and side["source_lags_ns"] == _LAGS_NS
        assert side["obs_cadence_seconds"] == 300
        assert "lamp" in side["source_breaks_observed"]


def test_the_runners_check_accepts_the_builders_sidecars_and_refuses_a_tampered_file(
    tmp_path: Path,
) -> None:
    world = _build_world(tmp_path)
    _run(world)
    design = json.loads(world.prereg.read_text(encoding="utf-8"))
    features = world.out() / "features.jsonl"

    skill._check_sidecar(features, design, role="primary")  # no raise
    features.write_text(features.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(skill.Refusal, match="sha256"):
        skill._check_sidecar(features, design, role="primary")


def test_the_same_inputs_build_byte_identical_files(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    _run(world, "one")
    _run(world, "two")

    for name in ("features.jsonl", "features_lag60.jsonl"):
        assert (world.out("one") / name).read_bytes() == (world.out("two") / name).read_bytes()


def test_the_report_carries_the_input_and_prereg_hashes(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    _run(world)

    report = world.report()

    assert report["prereg_content_sha256"] == skill.content_digest(
        json.loads(world.prereg.read_text(encoding="utf-8"))
    )
    assert report["inputs_sha256"]["truth"] == hashlib.sha256(world.truth.read_bytes()).hexdigest()
    assert report["nbp_availability_basis"].startswith("nominal")
    assert report["pfm_iem_entered_time"] == "unavailable_in_archive"
