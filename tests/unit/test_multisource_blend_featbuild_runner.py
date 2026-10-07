"""F13 Phase A feature-build rulings that land in the runner and the prereg skeleton.

FB-R2 (lag arm compares on the key intersection and reports rows lost per horizon), FB-R6
(``embargo_days`` >= 2), FB-R10 (the ``<features>.manifest.json`` sidecar is checked whenever it is
present; a sha or prereg-digest mismatch refuses the run) and the prereg skeleton pins. Synthetic
rows only; nothing reads real data.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from scripts.analysis import multisource_blend_skill as skill
from tests.unit.test_multisource_blend import make_rows
from tests.unit.test_multisource_blend_skill import (
    _PREREG_SRC,
    _Scenario,
    _write_features,
    write_sidecar,
)

_NEW_PINS = (
    "anchors",
    "source_lags_ns",
    "obs_source",
    "obs_cadence_seconds",
    "obs_routine_minute_by_station",
    "obs_min_coverage_per_station_year",
)


def _sidecar(features: Path, *, role: str, digest: str, sha: str | None = None) -> Path:
    return write_sidecar(features, role=role, digest=digest, sha=sha)


def _digest(scenario: _Scenario) -> str:
    return skill.content_digest(json.loads(scenario.prereg.read_text(encoding="utf-8")))


# ------------------------------------------------------------------ prereg skeleton


def test_prereg_skeleton_carries_the_builder_pins_null_and_unfrozen() -> None:
    draft = json.loads(_PREREG_SRC.read_text(encoding="utf-8"))
    assert draft["frozen_sha"] == "UNFROZEN"
    for key in _NEW_PINS:
        assert key in draft["pins"] and draft["pins"][key] is None, key
        assert key in draft["pin_units"], key
    assert all(value is None for value in draft["pins"].values())


# ------------------------------------------------------------------ FB-R2 key intersection


def _lag_without(scenario: _Scenario, drop: int) -> None:
    kept = scenario.rows[drop:]
    _write_features(scenario.lag_features, kept)


def test_lag_arm_compares_on_the_key_intersection_and_reports_rows_lost_per_horizon(
    tmp_path: Path,
) -> None:
    scenario = _Scenario(tmp_path)
    _lag_without(scenario, drop=6)

    result = scenario.run()

    lag = result["lag_rerun"]
    assert lag["keys_lost_by_horizon"] == {"D-1": 6}
    assert lag["n_keys_common"] == len(scenario.rows) - 6


def test_lag_rows_absent_from_the_base_file_are_refused_not_dropped(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path)
    _write_features(scenario.features, scenario.rows[3:])

    with pytest.raises(skill.Refusal, match="only in the lag"):
        scenario.run()


def test_identical_key_sets_report_zero_rows_lost(tmp_path: Path) -> None:
    result = _Scenario(tmp_path).run()

    assert result["lag_rerun"]["keys_lost_by_horizon"] == {}


def test_a_lag_file_sharing_no_key_with_the_base_is_refused(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path)
    _write_features(scenario.lag_features, [dataclasses.replace(scenario.rows[0], station="MIA")])

    with pytest.raises(skill.Refusal, match="no station-day in common"):
        scenario.run()


# ------------------------------------------------------------------ FB-R6 embargo floor


@pytest.mark.parametrize("bad", [0, 1])
def test_embargo_days_below_two_is_refused(tmp_path: Path, bad: int) -> None:
    scenario = _Scenario(tmp_path, embargo_days=bad)

    with pytest.raises(skill.Refusal, match="embargo_days"):
        scenario.run()


def test_embargo_days_of_two_is_accepted(tmp_path: Path) -> None:
    assert _Scenario(tmp_path, embargo_days=2).run()["embargo_days"] == 2


# ------------------------------------------------------------------ FB-R10 sidecar


def test_a_matching_sidecar_on_both_files_is_accepted(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path)
    digest = _digest(scenario)
    _sidecar(scenario.features, role="primary", digest=digest)
    _sidecar(scenario.lag_features, role="lag", digest=digest)

    assert scenario.run()["rows_input"] == len(scenario.rows)


def test_a_feature_file_that_no_longer_matches_its_sidecar_sha_is_refused(
    tmp_path: Path,
) -> None:
    scenario = _Scenario(tmp_path)
    digest = _digest(scenario)
    _sidecar(scenario.features, role="primary", digest=digest, sha="0" * 64)

    with pytest.raises(skill.Refusal, match="sha256"):
        scenario.run()


def test_a_sidecar_built_under_a_different_prereg_is_refused(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path)
    _sidecar(scenario.features, role="primary", digest=_digest(scenario))
    _sidecar(scenario.lag_features, role="lag", digest="f" * 64)

    with pytest.raises(skill.Refusal, match="prereg"):
        scenario.run()


def test_a_sidecar_with_the_wrong_role_or_schema_is_refused(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path)
    _sidecar(scenario.features, role="lag", digest=_digest(scenario))

    with pytest.raises(skill.Refusal, match="role"):
        scenario.run()


def test_an_unreadable_sidecar_is_refused_not_ignored(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path)
    Path(str(scenario.features) + skill.SIDECAR_SUFFIX).write_text("{not json", encoding="utf-8")

    with pytest.raises(skill.Refusal, match="sidecar"):
        scenario.run()


def test_runner_refuses_without_sidecar(tmp_path: Path) -> None:
    """FB-R14: a scoring run without the builder's sidecar is REFUSED (exit 2 through main)."""
    scenario = _Scenario(tmp_path, sidecars=False)

    assert not Path(str(scenario.features) + skill.SIDECAR_SUFFIX).exists()
    with pytest.raises(skill.Refusal, match="sidecar"):
        scenario.run()
    assert not (scenario.out / "stage_a.json").exists()


def test_runner_refuses_when_only_the_lag_sidecar_is_missing(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path, sidecars=False)
    _sidecar(scenario.features, role="primary", digest=_digest(scenario))

    with pytest.raises(skill.Refusal, match="sidecar"):
        scenario.run()


def test_runner_has_no_production_sidecar_bypass_flag() -> None:
    assert "allow-no-sidecar" not in Path(skill.__file__).read_text(encoding="utf-8")


# ------------------------------------------------------------------ lag file: shifted leak check


def test_the_lag_file_is_leak_checked_under_the_plus_60_min_shift(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path)
    # a lag row whose PFM availability is only 30 min before the anchor: leak-free as a primary
    # row, but the twin shifts it by 60 min, past the anchor
    leaky = [
        dataclasses.replace(r, pfm_available_at_ns=r.anchor_ns - 30 * 60 * 10**9)
        if r.pfm_mu_f is not None
        else r
        for r in scenario.rows
    ]
    _write_features(scenario.lag_features, leaky)

    with pytest.raises(skill.Refusal, match="pfm available_at"):
        scenario.run()


def test_the_primary_file_is_not_shifted_by_the_lag_check(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path)
    same = [
        dataclasses.replace(r, pfm_available_at_ns=r.anchor_ns - 30 * 60 * 10**9)
        if r.pfm_mu_f is not None
        else r
        for r in scenario.rows
    ]

    assert skill._load_rows(_write_features(scenario.features, same))  # no raise
    with pytest.raises(skill.Refusal, match="pfm available_at"):
        skill._load_rows(scenario.features, extra_lag_ns=skill.LAG_SHIFT_NS)


# ------------------------------------------------------------------ anchors vs the sidecar


def _both_horizons() -> list[Any]:
    return make_rows(days=3, stations=("NYC", "LAX"), horizons=("D-1", "D0"))


def _anchor_meta(variant: str = "primary", anchors: dict[str, Any] | None = None) -> dict[str, Any]:
    from tests.unit.test_multisource_blend_skill import _SIDECAR_ANCHORS

    return {"anchor_variant": variant, "anchors": {**_SIDECAR_ANCHORS, **(anchors or {})}}


def test_row_anchors_matching_the_sidecar_are_accepted(tmp_path: Path) -> None:
    skill.check_row_anchors(_both_horizons(), _anchor_meta(), tmp_path / "f.jsonl")  # no raise


def test_row_anchors_that_differ_from_the_declared_variant_are_refused(tmp_path: Path) -> None:
    with pytest.raises(skill.Refusal, match="anchor"):
        skill.check_row_anchors(_both_horizons(), _anchor_meta("d0_12lst"), tmp_path / "f.jsonl")


def test_row_anchors_that_differ_from_the_declared_pin_hour_are_refused(tmp_path: Path) -> None:
    with pytest.raises(skill.Refusal, match="anchor"):
        skill.check_row_anchors(
            _both_horizons(),
            _anchor_meta(anchors={"D-1": {"kind": "utc", "hour": 17}}),
            tmp_path / "f",
        )


def test_a_row_for_a_station_outside_the_registry_is_refused(tmp_path: Path) -> None:
    rows = make_rows(days=1, stations=("ZZZ",), horizons=("D0",))

    with pytest.raises(skill.Refusal, match="ZZZ"):
        skill.check_row_anchors(rows, _anchor_meta(), tmp_path / "f.jsonl")


def test_the_run_refuses_a_feature_file_whose_anchors_contradict_its_sidecar(
    tmp_path: Path,
) -> None:
    scenario = _Scenario(tmp_path)
    shifted = [dataclasses.replace(r, anchor_ns=r.anchor_ns + 3600 * 10**9) for r in scenario.rows]
    _write_features(scenario.features, shifted)
    _write_features(scenario.lag_features, shifted)

    with pytest.raises(skill.Refusal, match="anchor"):
        scenario.run()


# ------------------------------------------------------------------ sidecar anchors vs the prereg


def test_the_run_refuses_sidecar_anchors_that_differ_from_the_prereg_pin(tmp_path: Path) -> None:
    from tests.unit.test_multisource_blend_skill import _SIDECAR_ANCHORS

    scenario = _Scenario(tmp_path)
    other = {**_SIDECAR_ANCHORS, "D0_sensitivity": {"kind": "lst", "hour": 13}}
    for path, role in ((scenario.features, "primary"), (scenario.lag_features, "lag")):
        write_sidecar(path, role=role, digest=_digest(scenario), anchors=other)

    with pytest.raises(skill.Refusal, match="pinned"):
        scenario.run()


def test_the_run_refuses_a_prereg_without_usable_anchors(tmp_path: Path) -> None:
    with pytest.raises(skill.Refusal, match="anchors"):
        _Scenario(tmp_path, anchors=None).run()


def test_an_unknown_anchor_variant_in_a_sidecar_is_a_refusal_not_a_raw_error(
    tmp_path: Path,
) -> None:
    meta = _anchor_meta("d0_09lst")

    with pytest.raises(skill.Refusal, match="anchor_variant"):
        skill.check_row_anchors(_both_horizons(), meta, tmp_path / "f.jsonl")


def test_a_row_with_an_unknown_horizon_is_a_refusal_not_a_raw_error(tmp_path: Path) -> None:
    from types import SimpleNamespace

    # FeatureRow itself rejects a bad horizon, so a stand-in carries one to the anchor check
    rows = [
        SimpleNamespace(
            station=r.station, climate_day=r.climate_day, horizon="D+5", anchor_ns=r.anchor_ns
        )
        for r in _both_horizons()
    ]

    with pytest.raises(skill.Refusal, match="horizon"):
        skill.check_row_anchors(rows, _anchor_meta(), tmp_path / "f.jsonl")
