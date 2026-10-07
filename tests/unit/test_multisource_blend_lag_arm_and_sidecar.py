"""RED-first tests: F13 runner lag-arm pairing, lost-key diagnostics and the sidecar cross-check.

Review-fix items 2, 3 and 5: both arms are summarised on the SAME key set and compared as a paired
difference; lost keys are diagnosed; a lag-only key is a builder inconsistency; the two sidecars are
cross-checked (variant, anchors, lags, routine minutes, digest, shifts, row counts). Synthetic rows
only.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from breezy.analysis import multisource_blend as msb
from scripts.analysis import multisource_blend_skill as skill
from tests.unit.test_multisource_blend_skill import (
    DROP,
    _design,
    _freeze,
    _Scenario,
    _write_features,
    write_sidecar,
)


def _caps(value: Any) -> dict[str, Any]:
    return {"overall": value, "per_horizon": value, "per_station": value}


def _digest(scenario: _Scenario) -> str:
    return skill.content_digest(json.loads(scenario.prereg.read_text(encoding="utf-8")))


def _sidecar_meta(path: Path) -> dict[str, Any]:
    meta: dict[str, Any] = json.loads(
        Path(str(path) + skill.SIDECAR_SUFFIX).read_text(encoding="utf-8")
    )
    return meta


def _rewrite(path: Path, role: str, digest: str, **overrides: Any) -> None:
    write_sidecar(path, role=role, digest=digest, **overrides)


# ------------------------------------------------------------------ item 2: paired lag arm


def _drop_lag_keys(scenario: _Scenario, count: int) -> None:
    _write_features(scenario.lag_features, scenario.rows[count:])


def test_primary_delta_is_recomputed_on_the_common_keys_and_paired_with_the_lag_arm(
    tmp_path: Path,
) -> None:
    scenario = _Scenario(tmp_path)
    _drop_lag_keys(scenario, 40)

    result = scenario.run()

    lost = {(r.station, r.climate_day, r.horizon) for r in scenario.rows[:40]}
    oof = [
        json.loads(line)
        for line in (scenario.out / "oof_rows.jsonl").read_text(encoding="utf-8").splitlines()[1:]
    ]
    kept = [
        msb.scored_row_from_json(d)
        for d in oof
        if (d["station"], d["climate_day"], d["horizon"])
        not in {(s, day.isoformat(), h) for s, day, h in lost}
    ]
    expected = msb.delta_by_day(kept, "M0prime", "M3")
    lag = result["lag_rerun"]
    assert lag["primary_on_common"]["n_days"] == len(expected)
    assert lag["primary_on_common"]["mean"] == pytest.approx(
        sum(v for _d, v in expected) / len(expected)
    )
    assert set(lag["paired_difference"]) == {"mean", "lb", "n_days"}
    assert lag["paired_difference"]["mean"] == pytest.approx(
        lag["primary_on_common"]["mean"] - lag["mean"]
    )


def test_identical_files_give_a_zero_paired_difference(tmp_path: Path) -> None:
    result = _Scenario(tmp_path).run()

    lag = result["lag_rerun"]
    assert lag["paired_difference"]["mean"] == pytest.approx(0.0, abs=1e-9)
    assert lag["primary_on_common"]["mean"] == pytest.approx(result["delta_m0p_m3"]["mean"])
    assert lag["lost_fraction"] == 0.0


def test_lost_vs_kept_diagnostics_are_reported(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path)
    _drop_lag_keys(scenario, 40)

    lag = scenario.run()["lag_rerun"]

    assert lag["lost_fraction"] == pytest.approx(40 / len(scenario.rows))
    assert lag["lost_by_horizon"] == {
        "D-1": {"n": len(scenario.rows), "lost": 40, "fraction": pytest.approx(40 / 336)}
    }
    assert set(lag["lost_by_station"]) == {"NYC", "LAX"}
    assert sum(cell["lost"] for cell in lag["lost_by_station"].values()) == 40
    assert lag["lost_by_fold"]
    diagnostics = lag["lost_vs_kept"]
    for name in ("mean_m0_crps", "mean_abs_truth_minus_q50"):
        assert set(diagnostics[name]) == {"lost", "kept"}
        assert diagnostics[name]["kept"] is not None
    expected = sum(abs(r.cli_tmax_f - r.percentiles.q50) for r in scenario.rows[:40]) / 40
    assert diagnostics["mean_abs_truth_minus_q50"]["lost"] == pytest.approx(expected)


def test_changed_nbp_cycle_among_kept_keys_is_counted(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path)
    primary = [dataclasses.replace(r, nbp_cycle_ns=100) for r in scenario.rows]
    lag = [
        dataclasses.replace(r, nbp_cycle_ns=99 if i < 3 else 100)
        for i, r in enumerate(scenario.rows)
    ]
    _write_features(scenario.features, primary)
    _write_features(scenario.lag_features, lag)

    assert scenario.run()["lag_rerun"]["nbp_cycle_changed"] == 3


def test_changed_cycle_count_is_none_when_the_rows_carry_no_cycle_id(tmp_path: Path) -> None:
    assert _Scenario(tmp_path).run()["lag_rerun"]["nbp_cycle_changed"] is None


def test_the_feature_row_cycle_id_round_trips_through_json() -> None:
    row = dataclasses.replace(_first_row(), nbp_cycle_ns=1234)

    assert msb.feature_row_from_json(msb.feature_row_to_json(row)).nbp_cycle_ns == 1234
    legacy = msb.feature_row_to_json(row)
    del legacy["nbp_cycle_ns"]
    assert msb.feature_row_from_json(legacy).nbp_cycle_ns is None


def _first_row() -> msb.FeatureRow:
    from tests.unit.test_multisource_blend import two_version_rows

    return two_version_rows(seed=5)[0]


def test_lost_fraction_above_the_pin_refuses_before_anything_is_scored(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path, lag_arm_max_lost_fraction=_caps(0.05))
    _drop_lag_keys(scenario, 40)  # 40 / 336 = 11.9 %

    with pytest.raises(skill.Refusal, match="lag_arm_max_lost_fraction"):
        scenario.run()
    assert not (scenario.out / "stage_a.json").exists()
    assert not (scenario.out / "result.json").exists()


def test_lost_fraction_at_or_below_the_pin_is_accepted(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path, lag_arm_max_lost_fraction=_caps(0.2))
    _drop_lag_keys(scenario, 40)

    assert scenario.run()["lag_rerun"]["lost_fraction"] < 0.2


def test_a_null_lag_arm_max_lost_fraction_pin_is_refused_like_the_others(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path, lag_arm_max_lost_fraction=None)

    with pytest.raises(skill.Refusal, match="lag_arm_max_lost_fraction"):
        scenario.run()


@pytest.mark.parametrize("bad", [-0.1, 1.5, "half", True])
def test_lag_arm_max_lost_fraction_must_be_a_fraction(tmp_path: Path, bad: Any) -> None:
    prereg = _freeze(tmp_path / "repo", _design(lag_arm_max_lost_fraction=_caps(bad)))

    with pytest.raises(skill.Refusal, match="lag_arm_max_lost_fraction"):
        skill.load_verified_prereg(prereg)


def test_the_prereg_skeleton_carries_the_lag_arm_caps_pinned_by_pin_r5() -> None:
    from tests.unit.test_multisource_blend_skill import _PREREG_SRC

    draft = json.loads(_PREREG_SRC.read_text(encoding="utf-8"))

    assert draft["pins"]["lag_arm_max_lost_fraction"] == {
        "overall": 0.05,
        "per_horizon": 0.05,
        "per_station": 0.10,
    }
    assert "lag_arm_max_lost_fraction" in draft["pin_units"]
    assert "lag_arm_max_lost_fraction" in skill.REQUIRED_PINS


# ------------------------------------------------------------------ item 5: lag-only keys


def test_a_key_present_only_in_the_lag_file_is_a_refusal(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path)
    _write_features(scenario.features, scenario.rows[3:])

    with pytest.raises(skill.Refusal, match="only in the lag"):
        scenario.run()


# ------------------------------------------------------------------ item 3: sidecar cross-check


def test_a_full_consistent_sidecar_pair_is_accepted(tmp_path: Path) -> None:
    assert _Scenario(tmp_path).run()["rows_input"] > 0


@pytest.mark.parametrize("which", ["primary", "lag"])
@pytest.mark.parametrize(
    "key",
    [
        "anchor_variant",
        "anchors",
        "source_lags_ns",
        "obs_routine_minute_by_station",
        "n_rows",
        "lag_shift_ns",
    ],
)
def test_a_sidecar_missing_a_cross_checked_field_is_refused(
    tmp_path: Path, which: str, key: str
) -> None:
    scenario = _Scenario(tmp_path)
    path = scenario.features if which == "primary" else scenario.lag_features
    _rewrite(path, which, _digest(scenario), **{key: DROP})

    with pytest.raises(skill.Refusal, match=key):
        scenario.run()


def test_a_primary_pair_built_as_the_12_lst_sensitivity_is_refused_by_default(
    tmp_path: Path,
) -> None:
    scenario = _Scenario(tmp_path)
    for path, role in ((scenario.features, "primary"), (scenario.lag_features, "lag")):
        _rewrite(path, role, _digest(scenario), anchor_variant="d0_12lst")

    with pytest.raises(skill.Refusal, match="anchor_variant"):
        scenario.run()


def test_the_12_lst_pair_is_accepted_when_the_sensitivity_variant_is_selected(
    tmp_path: Path,
) -> None:
    scenario = _Scenario(tmp_path)
    for path, role in ((scenario.features, "primary"), (scenario.lag_features, "lag")):
        _rewrite(path, role, _digest(scenario), anchor_variant="d0_12lst")

    assert scenario.run(anchor_variant="d0_12lst")["rows_input"] > 0


def test_a_primary_pair_is_refused_when_the_sensitivity_variant_is_selected(
    tmp_path: Path,
) -> None:
    with pytest.raises(skill.Refusal, match="anchor_variant"):
        _Scenario(tmp_path).run(anchor_variant="d0_12lst")


def test_an_unknown_variant_is_refused(tmp_path: Path) -> None:
    with pytest.raises(skill.Refusal, match="anchor_variant"):
        _Scenario(tmp_path).run(anchor_variant="d0_09lst")


@pytest.mark.parametrize(
    ("key", "other"),
    [
        ("anchor_variant", "d0_12lst"),
        ("anchors", {"D-1": {"kind": "utc", "hour": 12}}),
        ("source_lags_ns", {"lamp-mdl": 9, "lav-iem": 9, "pfm": 9, "mos-gfs": 9, "obs": 9}),
        ("obs_routine_minute_by_station", {"NYC": 51}),
    ],
)
def test_the_two_files_must_agree_on_variant_anchors_lags_and_routine_minutes(
    tmp_path: Path, key: str, other: Any
) -> None:
    scenario = _Scenario(tmp_path)
    _rewrite(scenario.lag_features, "lag", _digest(scenario), **{key: other})

    with pytest.raises(skill.Refusal, match=key):
        scenario.run()


def test_the_two_files_must_share_the_prereg_digest(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path)
    _rewrite(scenario.lag_features, "lag", "e" * 64)

    with pytest.raises(skill.Refusal, match="digest"):
        scenario.run()


@pytest.mark.parametrize(
    ("which", "shift"),
    [("primary", 3_600_000_000_000), ("lag", 0), ("lag", 1_800_000_000_000)],
)
def test_the_lag_shift_must_be_zero_for_primary_and_one_hour_for_the_twin(
    tmp_path: Path, which: str, shift: int
) -> None:
    scenario = _Scenario(tmp_path)
    path = scenario.features if which == "primary" else scenario.lag_features
    _rewrite(path, which, _digest(scenario), lag_shift_ns=shift)

    with pytest.raises(skill.Refusal, match="lag_shift_ns"):
        scenario.run()


@pytest.mark.parametrize("which", ["primary", "lag"])
def test_the_sidecar_row_count_must_equal_the_actual_row_count(tmp_path: Path, which: str) -> None:
    scenario = _Scenario(tmp_path)
    path = scenario.features if which == "primary" else scenario.lag_features
    actual = _sidecar_meta(path)["n_rows"]
    _rewrite(path, which, _digest(scenario), n_rows=actual + 1)

    with pytest.raises(skill.Refusal, match="n_rows"):
        scenario.run()
