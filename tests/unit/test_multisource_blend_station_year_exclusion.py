"""RED-first tests: F13 Phase A builder guards and the filled prereg skeleton (PIN-R2, R4, R8a).

PIN-R4: a station-year whose routine-METAR coverage is below ``obs_min_coverage_per_station_year``
or whose pin-minute-excluded share is above ``obs_max_pin_minute_excluded_share`` is excluded from
EVERY row (both feature files) and listed in the report and the sidecars; the build refuses only
when every station-year fails. PIN-R8a: an UNFROZEN prereg builds only with ``--draft-scratch``,
which stamps non-scoring sidecars bound into the prereg digest. PIN-R2: the skeleton carries the
fixed literals. Synthetic stores only.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from breezy.analysis import multisource_blend as msb
from breezy.strategy.ladder_ev.quantile_density import CdfMethod
from scripts.analysis import multisource_blend_features_build as fb
from scripts.analysis import multisource_blend_inputs_obs_coverage as cov
from scripts.analysis import multisource_blend_skill as skill
from scripts.analysis.multisource_blend_sidecar import draft_scratch_digest, excluded_digest
from tests.unit.featbuild_fixtures import (
    RoutineRow,
    truth_row,
    utc,
    write_nbp_cycle,
    write_routine_store,
    write_truth,
)
from tests.unit.test_multisource_blend_features_build import (
    _D13,
    _build_world,
    _no_process_cap,  # noqa: F401  (autouse fixture of the builder tests, needed here too)
    _pins,
    _routine_rows,
    _run,
    _World,
)
from tests.unit.test_multisource_blend_skill import _PREREG_SRC

_STRICT = {"obs_min_coverage_per_station_year": 0.95, "obs_max_pin_minute_excluded_share": 0.02}
_LONG = {"start": "2021-03-13", "end": "2022-03-14"}
_REPO = Path(__file__).resolve().parents[2]


def _add_2022(world: _World, *, bad: str | None) -> None:
    """A second KNYC station-year with NBP data; ``bad`` breaks its obs coverage or minute share."""
    for cycle_day, hour, q50 in (
        (dt.date(2022, 3, 12), 13, 80.0),
        (dt.date(2022, 3, 12), 19, 81.0),
        (dt.date(2022, 3, 13), 1, 82.0),
        (dt.date(2022, 3, 13), 13, 83.0),
        (dt.date(2022, 3, 13), 19, 84.0),
        (dt.date(2022, 3, 14), 1, 85.0),
    ):
        write_nbp_cycle(world.nbp, station="KNYC", cycle_day=cycle_day, cycle_hour=hour, q50=q50)
    rows: list[RoutineRow] = []
    when = utc(2022, 3, 12, 0, 40)
    while when < utc(2022, 3, 15, 6):
        if not (bad == "coverage" and when.date() == dt.date(2022, 3, 13)):
            rows.append((when, 30 + when.hour, "tgroup"))
        if bad == "share":
            rows.append((when.replace(minute=20), 30 + when.hour, "tgroup"))
        when += dt.timedelta(hours=1)
    write_routine_store(world.metar, "KNYC", 2022, rows)
    write_truth(
        world.truth,
        [
            truth_row(station="NYC", climate_day=_D13, tmax_f=50),
            truth_row(station="NYC", climate_day=dt.date(2021, 3, 14), tmax_f=56),
            truth_row(station="NYC", climate_day=dt.date(2022, 3, 13), tmax_f=52),
            truth_row(station="NYC", climate_day=dt.date(2022, 3, 14), tmax_f=58),
        ],
    )


def _feature_years(world: _World, name: str = "features.jsonl") -> set[int]:
    return {r.climate_day.year for r in world.rows(name=name)}


def _sidecar(world: _World, name: str = "features.jsonl") -> dict[str, Any]:
    path = world.out() / (name + skill.SIDECAR_SUFFIX)
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


# ------------------------------------------------------------------ PIN-R4: the pure rule


def _year(*, expected: int, used: int, rows: int, off_minute: int) -> cov.YearCoverage:
    year = cov.YearCoverage(expected=expected, used=used)
    year.rows_in_window = rows
    year.pin_minute_excluded = off_minute
    return year


def test_failing_reasons_cover_coverage_and_share_with_strict_inequalities() -> None:
    assert (
        cov.failure_reasons(_year(expected=100, used=95, rows=100, off_minute=2), 0.95, 0.02) == []
    )
    low = cov.failure_reasons(_year(expected=100, used=94, rows=100, off_minute=0), 0.95, 0.02)
    assert len(low) == 1 and "coverage" in low[0]
    high = cov.failure_reasons(_year(expected=100, used=100, rows=100, off_minute=3), 0.95, 0.02)
    assert len(high) == 1 and "pin-minute" in high[0]
    both = cov.failure_reasons(_year(expected=100, used=50, rows=100, off_minute=50), 0.95, 0.02)
    assert len(both) == 2


def test_a_year_with_no_expected_reports_and_no_rows_does_not_fail() -> None:
    assert cov.failure_reasons(_year(expected=0, used=0, rows=0, off_minute=0), 0.95, 0.02) == []


@pytest.mark.parametrize("bad", [None, True, -0.1, 1.5, "0.02"])
def test_the_share_pin_is_validated_and_null_refuses_by_name(bad: Any) -> None:
    with pytest.raises(fb.BuildRefusal, match="obs_max_pin_minute_excluded_share"):
        fb.load_pins({"pins": _pins(obs_max_pin_minute_excluded_share=bad)})


def test_a_valid_share_pin_loads() -> None:
    pins = fb.load_pins({"pins": _pins(obs_max_pin_minute_excluded_share=0.02)})

    assert pins.obs_max_pin_minute_excluded_share == 0.02


# ------------------------------------------------------------------ PIN-R4: the build


@pytest.mark.parametrize("bad", ["share", "coverage"])
def test_a_failing_station_year_is_excluded_from_every_row_and_listed(
    tmp_path: Path, bad: str
) -> None:
    world = _build_world(tmp_path, pins=_pins(**_STRICT))
    _add_2022(world, bad=bad)

    assert _run(world, **_LONG) in (fb.EXIT_OK, fb.EXIT_DEGRADED)

    assert _feature_years(world) == {2021}  # M0 included: nothing from 2022 in either file
    assert _feature_years(world, "features_lag60.jsonl") == {2021}
    report = world.report()["obs_coverage"]
    assert [e["station_year"] for e in report["excluded_station_years"]] == ["KNYC/2022"]
    assert report["excluded_station_years"][0]["reasons"]
    assert report["max_pin_minute_excluded_share_pin"] == 0.02
    for name in ("features.jsonl", "features_lag60.jsonl"):
        side = _sidecar(world, name)
        assert side["obs_excluded_station_years"] == ["KNYC/2022"]
        assert side["obs_excluded_station_years_sha256"] == excluded_digest(["KNYC/2022"])


def test_without_the_strict_pins_the_same_station_year_builds(tmp_path: Path) -> None:
    world = _build_world(tmp_path, pins=_pins())
    _add_2022(world, bad="share")

    assert _run(world, **_LONG) in (fb.EXIT_OK, fb.EXIT_DEGRADED)

    assert _feature_years(world) == {2021, 2022}
    assert _sidecar(world)["obs_excluded_station_years"] == []


def test_a_passing_build_records_an_empty_excluded_list(tmp_path: Path) -> None:
    world = _build_world(tmp_path, pins=_pins(**_STRICT))

    assert _run(world) == fb.EXIT_OK

    side = _sidecar(world)
    assert side["obs_excluded_station_years"] == []
    assert side["obs_excluded_station_years_sha256"] == excluded_digest([])
    assert world.report()["obs_coverage"]["excluded_station_years"] == []


def test_the_build_refuses_when_every_station_year_fails_on_the_minute_share(
    tmp_path: Path,
) -> None:
    extra: list[RoutineRow] = [(r[0].replace(minute=20), 99, "tgroup") for r in _routine_rows()]
    world = _build_world(tmp_path, pins=_pins(**_STRICT), routine_extra=extra)

    assert _run(world) == fb.EXIT_REFUSED

    report = world.report()
    assert "KNYC/2021" in report["reason"] and "every station-year" in report["reason"]
    assert [e["station_year"] for e in report["obs_coverage"]["excluded_station_years"]] == [
        "KNYC/2021"
    ]
    assert not (world.out() / "features.jsonl").exists()


def test_the_excluded_station_year_leaves_no_row_in_the_surviving_arms_either(
    tmp_path: Path,
) -> None:
    world = _build_world(tmp_path, pins=_pins(**_STRICT))
    _add_2022(world, bad="coverage")
    _run(world, **_LONG)

    primary = {(r.station, r.climate_day, r.horizon) for r in world.rows()}
    lag = {(r.station, r.climate_day, r.horizon) for r in world.rows(name="features_lag60.jsonl")}

    assert lag <= primary and all(day.year == 2021 for _s, day, _h in primary)
    assert {r.horizon for r in world.rows()} == {"D0", "D-1"}
    assert isinstance(world.rows()[0], msb.FeatureRow)


# ------------------------------------------------------------------ PIN-R8a: draft scratch


def test_an_unfrozen_prereg_is_refused_without_draft_scratch(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    world.draft = False

    assert _run(world) == fb.EXIT_REFUSED

    assert "--draft-scratch" in world.report()["reason"]
    assert not (world.out() / "features.jsonl").exists()
    assert not (world.out() / ("features.jsonl" + skill.SIDECAR_SUFFIX)).exists()


def test_draft_scratch_stamps_non_scoring_sidecars_bound_into_the_digest(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    real = skill.content_digest(json.loads(world.prereg.read_text(encoding="utf-8")))

    assert _run(world) == fb.EXIT_OK

    for name in ("features.jsonl", "features_lag60.jsonl"):
        side = _sidecar(world, name)
        assert side["scoring"] is False
        assert side["prereg_content_sha256"] == draft_scratch_digest(real) != real
    report = world.report()
    assert report["scoring"] is False and report["prereg_content_sha256"] == real


def test_the_runner_refuses_the_builders_draft_output(tmp_path: Path) -> None:
    world = _build_world(tmp_path)
    _run(world)
    design = json.loads(world.prereg.read_text(encoding="utf-8"))

    with pytest.raises(skill.Refusal, match=r"scoring"):
        skill._check_sidecar(world.out() / "features.jsonl", design, role="primary")


def test_a_frozen_prereg_builds_scoring_sidecars_without_the_flag(tmp_path: Path) -> None:
    world = _build_world(tmp_path, frozen=True)
    real = skill.content_digest(json.loads(world.prereg.read_text(encoding="utf-8")))

    assert _run(world) == fb.EXIT_OK

    side = _sidecar(world)
    assert side["scoring"] is True and side["prereg_content_sha256"] == real
    assert world.report()["scoring"] is True


def test_draft_scratch_on_a_frozen_prereg_is_still_non_scoring(tmp_path: Path) -> None:
    world = _build_world(tmp_path, frozen=True)
    world.draft = True

    assert _run(world) == fb.EXIT_OK

    assert _sidecar(world)["scoring"] is False


# ------------------------------------------------------------------ PIN-R2: the filled skeleton


def _skeleton() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(_PREREG_SRC.read_text(encoding="utf-8"))
    return loaded


def test_the_skeleton_carries_the_fixed_statistics_pins_as_exact_literals() -> None:
    pins = _skeleton()["pins"]

    assert pins["floor_multiple"] == 0.25
    assert pins["leak_audit_spread_multiple"] == 3.0
    assert pins["m0_prime_tolerance_crps_f"] == 0.03
    assert pins["station_tolerance_crps_f"] == 0.05
    assert pins["student_t_nu"] == 5
    assert pins["sigma_floor_f"] == 0.75
    assert pins["weight_sum_lambda"] == 1.0
    assert pins["min_cell_rows"] == 60
    assert pins["bootstrap_n"] == 10000
    assert pins["bootstrap_seed"] == 20261006
    assert pins["m0_bootstrap_draws"] == 200
    assert pins["min_uncensored_lag_samples"] == 30
    assert pins["embargo_days"] == 3


def test_the_rung_edges_are_the_71_even_integers_written_out() -> None:
    edges = _skeleton()["pins"]["rung_edges_f"]

    assert edges == list(range(-20, 121, 2)) and len(edges) == 71
    assert all(type(e) is int for e in edges)


def test_the_build_pins_are_filled_and_only_the_two_blocked_pins_stay_null() -> None:
    design = _skeleton()
    pins = design["pins"]

    assert pins["anchors"] == {
        "D-1": {"kind": "utc", "hour": 18},
        "D0": {"kind": "lst", "hour": 10},
        "D0_sensitivity": {"kind": "lst", "hour": 12},
        "offset_rule": "fixed_standard_time_never_dst",
    }
    assert pins["obs_source"] == "iem_routine_metar_tgroup_round_half_up_f"
    assert pins["obs_cadence_seconds"] == 3600
    assert pins["obs_routine_minute_by_station"] == {
        "KLAX": 53,
        "KMDW": 53,
        "KMIA": 53,
        "KNYC": 51,
        "KSFO": 56,
    }
    assert pins["obs_min_coverage_per_station_year"] == 0.95
    assert pins["obs_max_pin_minute_excluded_share"] == 0.02
    assert pins["lag_arm_max_lost_fraction"] == {
        "overall": 0.05,
        "per_horizon": 0.05,
        "per_station": 0.10,
    }
    assert design["veto"]["reference"] == {
        "kind": "raw_nbp_cdf",
        "method": "NORMAL",
        "spread_prob": 0.02,
    }
    assert {k for k, v in pins.items() if v is None} == {"source_lags_ns", "source_breaks"}
    assert design["frozen_sha"] == "UNFROZEN"


def test_the_skeleton_pins_pass_the_runner_and_builder_validators_once_the_blocked_two_are_set(
    tmp_path: Path,
) -> None:
    design = _skeleton()
    design["pins"]["source_lags_ns"] = {
        "lamp-mdl": 60 * 60 * 10**9,
        "lav-iem": 90 * 60 * 10**9,
        "pfm": 60 * 60 * 10**9,
        "mos-gfs": 300 * 60 * 10**9,
        "obs": 15 * 60 * 10**9,
    }
    design["pins"]["source_breaks"] = []

    skill._check_values(design)  # no Refusal: the exact JSON shapes the code validates
    fb.load_pins(design)
    assert all(design["pins"][k] is not None for k in skill.REQUIRED_PINS)


def test_the_champion_cdf_method_is_read_from_the_committed_champion_config() -> None:
    design = _skeleton()
    method = design["pins"]["champion_cdf_method"]
    source = design["pins"]["champion_cdf_method_source"]

    assert method in {m.name for m in CdfMethod}
    assert set(source) == {"path", "commit"}
    committed = subprocess.run(
        ["git", "show", f"{source['commit']}:{source['path']}"],
        cwd=_REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert CdfMethod(json.loads(committed)["cdf_method"]).name == method
    assert (_REPO / source["path"]).is_file()


def test_the_extra_source_key_is_not_a_required_pin() -> None:
    assert "champion_cdf_method_source" not in skill.REQUIRED_PINS


def test_every_new_pin_has_a_unit_note() -> None:
    units = _skeleton()["pin_units"]

    for key in ("obs_max_pin_minute_excluded_share", "lag_arm_max_lost_fraction"):
        assert key in units
    assert "per_horizon" in units["lag_arm_max_lost_fraction"]
