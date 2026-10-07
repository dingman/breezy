"""F13 Phase A feature-build rulings that land in the runner and the prereg skeleton.

FB-R2 (lag arm compares on the key intersection and reports rows lost per horizon), FB-R6
(``embargo_days`` >= 2), FB-R10 (the ``<features>.manifest.json`` sidecar is checked whenever it is
present; a sha or prereg-digest mismatch refuses the run) and the prereg skeleton pins. Synthetic
rows only; nothing reads real data.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

import pytest

from scripts.analysis import multisource_blend_skill as skill
from tests.unit.test_multisource_blend_skill import _PREREG_SRC, _Scenario, _write_features

_NEW_PINS = ("anchors", "source_lags_ns", "obs_source", "obs_cadence_seconds")


def _sidecar(features: Path, *, role: str, digest: str, sha: str | None = None) -> Path:
    path = Path(str(features) + skill.SIDECAR_SUFFIX)
    path.write_text(
        json.dumps(
            {
                "schema": skill.SIDECAR_SCHEMA,
                "role": role,
                "prereg_content_sha256": digest,
                "features_sha256": sha or hashlib.sha256(features.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    return path


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
    assert lag["keys_extra_in_lag_dropped"] == 0
    assert lag["n_keys_common"] == len(scenario.rows) - 6


def test_lag_rows_absent_from_the_base_file_are_dropped_and_counted(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path)
    _write_features(scenario.features, scenario.rows[3:])

    result = scenario.run()

    assert result["lag_rerun"]["keys_extra_in_lag_dropped"] == 3
    assert result["lag_rerun"]["keys_lost_by_horizon"] == {}


def test_identical_key_sets_report_zero_rows_lost(tmp_path: Path) -> None:
    result = _Scenario(tmp_path).run()

    assert result["lag_rerun"]["keys_lost_by_horizon"] == {}
    assert result["lag_rerun"]["keys_extra_in_lag_dropped"] == 0


def test_a_lag_file_sharing_no_key_with_the_base_is_refused(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path)
    _write_features(scenario.lag_features, [dataclasses.replace(scenario.rows[0], station="ZZZ")])

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


def test_no_sidecar_means_no_sidecar_check(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path)

    assert not Path(str(scenario.features) + skill.SIDECAR_SUFFIX).exists()
    assert scenario.run()["rows_input"] == len(scenario.rows)
