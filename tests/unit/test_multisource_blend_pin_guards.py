"""RED-first tests: F13 Phase A pin guards, runner side (PIN-R5..R9 of the r3 pin proposals).

PIN-R5 lag-arm loss caps (overall / per horizon / per station), PIN-R6 pinned lags against the C1
observed p99, PIN-R7 observed source breaks must be pinned, PIN-R8 freeze guards (non-scoring
sidecar, re-freeze, frozen content digest) and PIN-R9 required pins. Synthetic fixtures and
temporary git repositories only.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts.analysis import blend_veto_descriptive as veto
from scripts.analysis import multisource_blend_lag_arm as lag_arm
from scripts.analysis import multisource_blend_pin_guards as guards
from scripts.analysis import multisource_blend_skill as skill
from scripts.analysis.multisource_blend_sidecar import draft_scratch_digest
from tests.unit.test_multisource_blend_skill import (
    _LAG_CAPS,
    _NO_BREAKS,
    _PINNED_LAGS,
    _PREREG_SRC,
    DROP,
    _design,
    _freeze,
    _git,
    _Scenario,
    c1_lag_samples,
    write_sidecar,
)

# ------------------------------------------------------------------ PIN-R5: loss caps


def _keys(lost: set[lag_arm.Key], base: set[lag_arm.Key]) -> lag_arm.LagKeys:
    return lag_arm.LagKeys(base=frozenset(base), common=frozenset(base - lost))


def _grid() -> set[lag_arm.Key]:
    days = [dt.date(2020, 1, 1) + dt.timedelta(days=i) for i in range(10)]
    return {(s, d, h) for s in ("NYC", "LAX") for d in days for h in ("D0", "D-1")}  # 40 keys


def _caps(overall: float = 1.0, horizon: float = 1.0, station: float = 1.0) -> lag_arm.LagCaps:
    return lag_arm.parse_lag_caps(
        {"overall": overall, "per_horizon": horizon, "per_station": station}
    )


def test_a_loss_inside_every_cap_is_accepted() -> None:
    base = _grid()
    lost = {k for k in base if k[0] == "NYC" and k[2] == "D0" and k[1].day <= 2}  # 2 of 40
    lag_arm.check_lag_caps(_keys(lost, base), _caps(0.05, 0.2, 0.2))


def test_the_overall_cap_refuses() -> None:
    base = _grid()
    lost = {k for k in base if k[1].day <= 2 and k[0] == "NYC"}  # 4 of 40 = 10 %
    with pytest.raises(skill.Refusal, match=r"lag_arm_max_lost_fraction.*overall"):
        lag_arm.check_lag_caps(_keys(lost, base), _caps(0.05, 1.0, 1.0))


def test_the_per_horizon_cap_refuses_even_when_the_overall_loss_is_small() -> None:
    base = _grid()
    lost = {k for k in base if k[2] == "D0" and k[1].day <= 2}  # 4 of 40 overall, 4 of 20 in D0
    lag_arm.check_lag_caps(_keys(lost, base), _caps(0.5, 1.0, 1.0))
    with pytest.raises(skill.Refusal, match=r"lag_arm_max_lost_fraction.*horizon 'D0'"):
        lag_arm.check_lag_caps(_keys(lost, base), _caps(0.5, 0.15, 1.0))


def test_the_per_station_cap_refuses_even_when_the_overall_loss_is_small() -> None:
    base = _grid()
    lost = {k for k in base if k[0] == "LAX" and k[1].day <= 2}  # 4 of 40 overall, 4 of 20 LAX
    with pytest.raises(skill.Refusal, match=r"lag_arm_max_lost_fraction.*station 'LAX'"):
        lag_arm.check_lag_caps(_keys(lost, base), _caps(0.5, 1.0, 0.15))


def test_a_loss_exactly_at_a_cap_is_accepted() -> None:
    base = _grid()
    lost = {k for k in base if k[0] == "LAX" and k[2] == "D0" and k[1].day <= 2}  # 2 of 40
    lag_arm.check_lag_caps(_keys(lost, base), _caps(0.05, 0.1, 0.1))


@pytest.mark.parametrize(
    "bad",
    [
        0.05,  # the old scalar shape
        None,
        {"overall": 0.05, "per_horizon": 0.05},  # a missing key
        {"overall": 0.05, "per_horizon": 0.05, "per_station": 0.1, "extra": 1},
        {"overall": -0.1, "per_horizon": 0.05, "per_station": 0.1},
        {"overall": 0.05, "per_horizon": 1.5, "per_station": 0.1},
        {"overall": 0.05, "per_horizon": 0.05, "per_station": "0.1"},
        {"overall": True, "per_horizon": 0.05, "per_station": 0.1},
    ],
)
def test_the_caps_pin_must_be_an_object_of_three_fractions(tmp_path: Path, bad: Any) -> None:
    prereg = _freeze(tmp_path / "repo", _design(lag_arm_max_lost_fraction=bad))

    with pytest.raises(skill.Refusal, match="lag_arm_max_lost_fraction"):
        skill.load_verified_prereg(prereg)


def test_the_runner_refuses_a_per_horizon_loss_end_to_end(tmp_path: Path) -> None:
    caps = {**_LAG_CAPS, "per_horizon": 0.05}
    scenario = _Scenario(tmp_path, lag_arm_max_lost_fraction=caps)
    from tests.unit.test_multisource_blend_skill import _write_features

    _write_features(scenario.lag_features, scenario.rows[40:])  # 40 of 336 lost, all D-1

    with pytest.raises(skill.Refusal, match=r"lag_arm_max_lost_fraction.*horizon"):
        scenario.run()
    assert not (scenario.out / "stage_a.json").exists()


# ------------------------------------------------------------------ PIN-R6: lags vs C1 p99


def test_the_p99_is_the_nearest_rank_of_the_uncensored_samples() -> None:
    samples = list(range(1, 101))  # 1..100: nearest-rank p99 is the 99th value
    assert guards.observed_p99_ns(samples) == 99
    assert guards.observed_p99_ns([7]) == 7


def test_a_pinned_lag_below_the_c1_p99_refuses_naming_the_source(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path)
    too_slow = [_PINNED_LAGS["mos-gfs"] + 1] * 100
    scenario.evidence.write_text(_evidence(mos_gfs=too_slow), encoding="utf-8")

    with pytest.raises(skill.Refusal, match=r"mos-gfs.*C1.*p99"):
        scenario.run()
    assert not (scenario.out / "stage_a.json").exists()


def test_a_pinned_lag_equal_to_the_c1_p99_is_accepted(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path)
    scenario.evidence.write_text(_evidence(pfm=[_PINNED_LAGS["pfm"]] * 100), encoding="utf-8")

    assert scenario.run()["verdict"]


def test_one_outlier_in_a_hundred_samples_is_inside_the_p99(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path)
    samples = [1] * 99 + [_PINNED_LAGS["obs"] * 10]
    scenario.evidence.write_text(_evidence(obs=samples), encoding="utf-8")

    assert scenario.run()["verdict"]


def test_two_outliers_in_a_hundred_samples_move_the_p99_and_refuse(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path)
    samples = [1] * 98 + [_PINNED_LAGS["obs"] * 10] * 2
    scenario.evidence.write_text(_evidence(obs=samples), encoding="utf-8")

    with pytest.raises(skill.Refusal, match=r"obs.*p99"):
        scenario.run()


@pytest.mark.parametrize("missing", ["lamp-mdl", "lav-iem", "pfm", "mos-gfs", "obs"])
def test_a_source_without_c1_lag_samples_refuses(tmp_path: Path, missing: str) -> None:
    scenario = _Scenario(tmp_path)
    samples = c1_lag_samples()
    del samples[missing]
    scenario.evidence.write_text(_evidence_raw(samples), encoding="utf-8")

    with pytest.raises(skill.Refusal, match=rf"{missing}.*lag_samples_ns"):
        scenario.run()


def test_evidence_without_the_sample_object_refuses(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path)
    scenario.evidence.write_text(
        json.dumps(
            {
                "measured_days": {key: 20 for key in _PINNED_LAGS},
                "uncensored": {key: 30 for key in _PINNED_LAGS},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(skill.Refusal, match="lag_samples_ns"):
        scenario.run()


@pytest.mark.parametrize("bad", [[], [-1], [1.5], ["x"], [True], "abc"])
def test_malformed_lag_samples_refuse(tmp_path: Path, bad: Any) -> None:
    scenario = _Scenario(tmp_path)
    scenario.evidence.write_text(_evidence(pfm=bad), encoding="utf-8")

    with pytest.raises(skill.Refusal, match=r"pfm.*lag_samples_ns"):
        scenario.run()


def _evidence_raw(samples: dict[str, Any]) -> str:
    return json.dumps(
        {
            "measured_days": {key: 20 for key in _PINNED_LAGS},
            "uncensored": {key: 30 for key in _PINNED_LAGS},
            "lag_samples_ns": samples,
        }
    )


def _evidence(**overrides: Any) -> str:
    renamed = {k.replace("_", "-"): v for k, v in overrides.items()}
    return _evidence_raw({**c1_lag_samples(), **renamed})


# ------------------------------------------------------------------ PIN-R7: source breaks


def _breaks(**parts: Any) -> dict[str, Any]:
    return {**_NO_BREAKS, **parts}


def _rewrite_sidecars(scenario: _Scenario, **overrides: Any) -> None:
    digest = skill.content_digest(json.loads(scenario.prereg.read_text(encoding="utf-8")))
    write_sidecar(scenario.features, role="primary", digest=digest, **overrides)
    write_sidecar(scenario.lag_features, role="lag", digest=digest, **overrides)


def test_an_observed_break_that_is_not_pinned_refuses_naming_the_date(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path)  # pinned source_breaks = []
    _rewrite_sidecars(
        scenario, source_breaks_observed=_breaks(lamp=["2015-03-01"], nbp_versions=[])
    )

    with pytest.raises(skill.Refusal, match=r"2015-03-01.*source_breaks"):
        scenario.run()
    assert not (scenario.out / "stage_a.json").exists()


@pytest.mark.parametrize(
    "observed",
    [
        _breaks(nbp_versions=["2015-03-01"]),
        _breaks(lamp=["2015-03-01"], lamp_by_horizon={"D0": ["2015-03-01"], "D-1": []}),
        _breaks(lamp_by_horizon={"D0": [], "D-1": ["2015-03-01"]}),
    ],
)
def test_nbp_version_and_per_horizon_lamp_breaks_are_flattened_and_checked(
    tmp_path: Path, observed: dict[str, Any]
) -> None:
    scenario = _Scenario(tmp_path)
    _rewrite_sidecars(scenario, source_breaks_observed=observed)

    with pytest.raises(skill.Refusal, match="2015-03-01"):
        scenario.run()


def test_observed_breaks_inside_the_pinned_list_are_accepted(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path, source_breaks=["2015-03-01", "2015-04-01"])
    _rewrite_sidecars(
        scenario,
        source_breaks_observed=_breaks(
            lamp=["2015-03-01"],
            lamp_by_horizon={"D0": ["2015-03-01"], "D-1": []},
            nbp_versions=["2015-04-01"],
        ),
    )

    assert scenario.run()["verdict"]


def test_a_pinned_break_that_was_not_observed_is_not_a_refusal(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path, source_breaks=["2015-03-01"])

    assert scenario.run()["verdict"]  # a subset, not an equality: extra pinned breaks are fine


def test_a_sidecar_without_the_observed_breaks_refuses(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path)
    _rewrite_sidecars(scenario, source_breaks_observed=DROP)

    with pytest.raises(skill.Refusal, match="source_breaks_observed"):
        scenario.run()


@pytest.mark.parametrize("bad", ["2015-03-01", {"lamp": ["not-a-date"]}, {"lamp": [20150301]}])
def test_malformed_observed_breaks_refuse(tmp_path: Path, bad: Any) -> None:
    scenario = _Scenario(tmp_path)
    _rewrite_sidecars(scenario, source_breaks_observed=bad)

    with pytest.raises(skill.Refusal, match="source_breaks_observed"):
        scenario.run()


def test_the_two_sidecars_must_agree_on_the_observed_breaks(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path, source_breaks=["2015-03-01"])
    digest = skill.content_digest(json.loads(scenario.prereg.read_text(encoding="utf-8")))
    write_sidecar(
        scenario.lag_features,
        role="lag",
        digest=digest,
        source_breaks_observed=_breaks(lamp=["2015-03-01"]),
    )

    with pytest.raises(skill.Refusal, match="source_breaks_observed"):
        scenario.run()


# ------------------------------------------------------------------ PIN-R8a: non-scoring sidecar


def test_a_non_scoring_sidecar_is_refused(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path)
    _rewrite_sidecars(scenario, scoring=False)

    with pytest.raises(skill.Refusal, match=r"scoring.*draft"):
        scenario.run()
    assert not (scenario.out / "stage_a.json").exists()


def test_a_sidecar_without_the_scoring_stamp_is_refused(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path)
    _rewrite_sidecars(scenario, scoring=DROP)

    with pytest.raises(skill.Refusal, match="scoring"):
        scenario.run()


def test_flipping_a_draft_sidecar_to_scoring_true_breaks_the_digest_binding(
    tmp_path: Path,
) -> None:
    scenario = _Scenario(tmp_path)
    real = skill.content_digest(json.loads(scenario.prereg.read_text(encoding="utf-8")))
    for path, role in ((scenario.features, "primary"), (scenario.lag_features, "lag")):
        write_sidecar(path, role=role, digest=draft_scratch_digest(real), scoring=True)

    with pytest.raises(skill.Refusal, match="digest"):
        scenario.run()


def test_the_draft_digest_differs_from_the_real_one_and_is_deterministic() -> None:
    assert draft_scratch_digest("a" * 64) != "a" * 64
    assert draft_scratch_digest("a" * 64) == draft_scratch_digest("a" * 64)
    assert draft_scratch_digest("a" * 64) != draft_scratch_digest("b" * 64)


# ------------------------------------------------------------------ PIN-R4 sidecar side


def test_the_excluded_list_is_bound_to_its_digest(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path)
    _rewrite_sidecars(scenario, obs_excluded_station_years=["KNYC/2019"])  # digest is of []

    with pytest.raises(skill.Refusal, match="obs_excluded_station_years"):
        scenario.run()


def test_a_declared_excluded_list_with_its_matching_digest_is_accepted(tmp_path: Path) -> None:
    from scripts.analysis.multisource_blend_sidecar import excluded_digest

    scenario = _Scenario(tmp_path)
    listed = ["KNYC/2019"]
    _rewrite_sidecars(
        scenario,
        obs_excluded_station_years=listed,
        obs_excluded_station_years_sha256=excluded_digest(listed),
    )

    assert scenario.run()["verdict"]


def test_the_two_sidecars_must_agree_on_the_excluded_list(tmp_path: Path) -> None:
    from scripts.analysis.multisource_blend_sidecar import excluded_digest

    scenario = _Scenario(tmp_path)
    digest = skill.content_digest(json.loads(scenario.prereg.read_text(encoding="utf-8")))
    write_sidecar(
        scenario.lag_features,
        role="lag",
        digest=digest,
        obs_excluded_station_years=["KNYC/2019"],
        obs_excluded_station_years_sha256=excluded_digest(["KNYC/2019"]),
    )

    with pytest.raises(skill.Refusal, match="obs_excluded_station_years"):
        scenario.run()


def test_the_excluded_digest_is_order_independent_and_content_bound() -> None:
    from scripts.analysis.multisource_blend_sidecar import excluded_digest

    assert excluded_digest(["B/1", "A/2"]) == excluded_digest(["A/2", "B/1"])
    assert excluded_digest(["A/2"]) != excluded_digest([])


def test_a_row_in_an_excluded_station_year_refuses_in_both_files(tmp_path: Path) -> None:
    from scripts.analysis.multisource_blend_sidecar import excluded_digest

    scenario = _Scenario(tmp_path)  # rows: NYC and LAX, climate year 2025
    listed = ["KNYC/2025"]
    _rewrite_sidecars(
        scenario,
        obs_excluded_station_years=listed,
        obs_excluded_station_years_sha256=excluded_digest(listed),
    )

    with pytest.raises(skill.Refusal, match=r"KNYC/2025.*PIN-R4"):
        scenario.run()
    assert not (scenario.out / "stage_a.json").exists()


def test_a_row_in_an_excluded_station_year_refuses_when_only_the_lag_file_holds_it(
    tmp_path: Path,
) -> None:
    from scripts.analysis.multisource_blend_sidecar import excluded_digest
    from tests.unit.test_multisource_blend_skill import _write_features

    scenario = _Scenario(tmp_path)
    listed = ["KLAX/2025"]
    _rewrite_sidecars(
        scenario,
        obs_excluded_station_years=listed,
        obs_excluded_station_years_sha256=excluded_digest(listed),
    )
    _write_features(scenario.features, [r for r in scenario.rows if r.station != "LAX"])

    with pytest.raises(skill.Refusal, match=r"KLAX/2025"):
        scenario.run()


def test_an_excluded_station_year_with_no_rows_is_accepted(tmp_path: Path) -> None:
    from scripts.analysis.multisource_blend_sidecar import excluded_digest

    scenario = _Scenario(tmp_path)
    listed = ["KNYC/2019", "KMIA/2025"]  # NYC has no 2019 rows; no MIA rows at all
    _rewrite_sidecars(
        scenario,
        obs_excluded_station_years=listed,
        obs_excluded_station_years_sha256=excluded_digest(listed),
    )

    assert scenario.run()["verdict"]


@pytest.mark.parametrize("bad", ["KNYC", "KNYC/abc", "/2025"])
def test_a_malformed_excluded_station_year_refuses(tmp_path: Path, bad: str) -> None:
    from scripts.analysis.multisource_blend_sidecar import excluded_digest

    scenario = _Scenario(tmp_path)
    _rewrite_sidecars(
        scenario,
        obs_excluded_station_years=[bad],
        obs_excluded_station_years_sha256=excluded_digest([bad]),
    )

    with pytest.raises(skill.Refusal, match="obs_excluded_station_years"):
        scenario.run()


def test_a_sidecar_whose_lags_differ_from_the_pinned_lags_refuses(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path)
    _rewrite_sidecars(scenario, source_lags_ns={**_PINNED_LAGS, "pfm": _PINNED_LAGS["pfm"] + 1})

    with pytest.raises(skill.Refusal, match=r"source_lags_ns.*pfm"):
        scenario.run()
    assert not (scenario.out / "stage_a.json").exists()


# ------------------------------------------------------------------ PIN-R8b: re-freeze


def _commit_edit(repo: Path, name: str, design: dict[str, Any]) -> None:
    (repo / name).write_text(json.dumps(design, indent=2), encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", "edit")


def test_a_single_freeze_is_accepted(tmp_path: Path) -> None:
    prereg = _freeze(tmp_path / "repo", _design())

    guards.check_not_refrozen(prereg)


def test_a_second_freeze_commit_is_refused_as_a_refreeze(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    prereg = _freeze(repo, _design())
    again = json.loads(prereg.read_text(encoding="utf-8"))
    again["frozen_sha"] = _git(repo, "rev-parse", "HEAD")
    again["pins"]["floor_multiple"] = 0.5
    _commit_edit(repo, "prereg.json", again)

    with pytest.raises(skill.Refusal, match=r"re-frozen.*2"):
        guards.check_not_refrozen(prereg)


def test_an_edit_after_the_freeze_that_keeps_the_stamp_is_also_a_refreeze(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    prereg = _freeze(repo, _design())
    edited = json.loads(prereg.read_text(encoding="utf-8"))
    edited["pin_note"] = "reworded after the freeze"
    _commit_edit(repo, "prereg.json", edited)

    with pytest.raises(skill.Refusal, match="re-frozen"):
        guards.check_not_refrozen(prereg)


def test_the_history_follows_a_rename(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    prereg = _freeze(repo, _design(), name="old.json")
    _git(repo, "mv", "old.json", "new.json")
    _git(repo, "commit", "-q", "-m", "rename")
    renamed = json.loads((repo / "new.json").read_text(encoding="utf-8"))
    renamed["frozen_sha"] = _git(repo, "rev-parse", "HEAD")
    _commit_edit(repo, "new.json", renamed)

    assert prereg.exists() is False
    with pytest.raises(skill.Refusal, match="re-frozen"):
        guards.check_not_refrozen(repo / "new.json")


def test_an_amendment_copy_is_judged_on_its_own_history_not_the_frozen_original(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    original = _freeze(repo, _design(), name="prereg_v1.json")
    amended = _freeze(repo, _design(floor_multiple=0.5), name="prereg_v2.json")

    guards.check_not_refrozen(amended)
    guards.check_not_refrozen(original)  # the original stays a single freeze too


def test_a_pure_rename_of_the_frozen_file_is_not_a_refreeze(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _freeze(repo, _design(), name="old.json")
    _git(repo, "mv", "old.json", "new.json")
    _git(repo, "commit", "-q", "-m", "rename")

    guards.check_not_refrozen(repo / "new.json")


def test_a_v2_copy_is_not_charged_with_the_stamp_of_a_v1_that_is_later_deleted(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _freeze(repo, _design(), name="prereg_v1.json")
    amended = _freeze(repo, _design(), name="prereg_v2.json")
    _git(repo, "rm", "-q", "prereg_v1.json")
    _git(repo, "commit", "-q", "-m", "drop v1")

    guards.check_not_refrozen(amended)


def test_a_genuine_second_freeze_with_a_new_frozen_sha_is_refused_after_a_rename(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _freeze(repo, _design(), name="old.json")
    _git(repo, "mv", "old.json", "new.json")
    _git(repo, "commit", "-q", "-m", "rename")
    again = json.loads((repo / "new.json").read_text(encoding="utf-8"))
    again["frozen_sha"] = _git(repo, "rev-parse", "HEAD")
    _commit_edit(repo, "new.json", again)

    with pytest.raises(skill.Refusal, match="re-frozen"):
        guards.check_not_refrozen(repo / "new.json")


def test_a_shallow_clone_is_refused_because_its_history_is_truncated(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    prereg = _freeze(repo, _design())
    _commit_edit(repo, "other.json", {"x": 1})
    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", repo.as_uri(), str(clone)],
        check=True,
        capture_output=True,
    )

    with pytest.raises(skill.Refusal, match="shallow"):
        guards.check_not_refrozen(clone / prereg.name)


@pytest.mark.parametrize(
    "error",
    [OSError("no git"), subprocess.TimeoutExpired("git", 20), subprocess.SubprocessError("x")],
)
def test_a_git_failure_is_a_refusal_not_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    prereg = _freeze(tmp_path / "repo", _design())

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise error

    monkeypatch.setattr(subprocess, "run", _boom)

    with pytest.raises(skill.Refusal, match="git"):
        guards.check_not_refrozen(prereg)


def test_unfrozen_history_alone_is_not_a_refreeze(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    path = repo / "prereg.json"
    for note in ("one", "two", "three"):
        _commit_edit(repo, "prereg.json", {**_design(), "frozen_sha": skill.UNFROZEN, "n": note})

    guards.check_not_refrozen(path)


def test_the_runner_refuses_a_refrozen_prereg_before_scoring(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    prereg = _freeze(repo, _design())
    again = json.loads(prereg.read_text(encoding="utf-8"))
    again["frozen_sha"] = _git(repo, "rev-parse", "HEAD")
    again["pins"]["floor_multiple"] = 0.5
    _commit_edit(repo, "prereg.json", again)

    with pytest.raises(skill.Refusal, match="re-frozen"):
        skill.load_verified_prereg(prereg)


def test_a_prereg_outside_git_is_refused_by_the_guard(tmp_path: Path) -> None:
    path = tmp_path / "loose.json"
    path.write_text(json.dumps({**_design(), "frozen_sha": "a" * 40}), encoding="utf-8")

    with pytest.raises(skill.Refusal, match="git"):
        guards.check_not_refrozen(path)


# ------------------------------------------------------------------ PIN-R8c: frozen digest pin

#: Set to the skeleton's ``skill.content_digest`` in the SAME commit that stamps the freeze. While
#: the skeleton is UNFROZEN the test below skips; from the freeze on it is binding.
FROZEN_CONTENT_SHA256: str | None = None


def test_the_frozen_skeleton_content_digest_is_pinned_to_a_constant() -> None:
    design = json.loads(_PREREG_SRC.read_text(encoding="utf-8"))
    if design["frozen_sha"] == skill.UNFROZEN:
        pytest.skip("the prereg skeleton is UNFROZEN; this pin becomes binding at the freeze")
    assert FROZEN_CONTENT_SHA256 is not None, (
        "the prereg is frozen: set FROZEN_CONTENT_SHA256 to skill.content_digest(prereg)"
    )
    assert skill.content_digest(design) == FROZEN_CONTENT_SHA256


# ------------------------------------------------------------------ PIN-R9: required pins

_R9_PINS = (
    "anchors",
    "source_lags_ns",
    "obs_source",
    "obs_cadence_seconds",
    "obs_routine_minute_by_station",
    "obs_min_coverage_per_station_year",
    "obs_max_pin_minute_excluded_share",
)


def test_every_builder_pin_is_a_required_runner_pin() -> None:
    assert set(_R9_PINS) <= set(skill.REQUIRED_PINS)


@pytest.mark.parametrize("name", _R9_PINS)
def test_a_null_builder_pin_refuses_by_name(tmp_path: Path, name: str) -> None:
    prereg = _freeze(tmp_path / "repo", _design(**{name: None}))

    with pytest.raises(skill.Refusal, match=name):
        skill.load_verified_prereg(prereg)


@pytest.mark.parametrize(
    ("name", "bad"),
    [
        ("obs_source", "some_other_label"),
        ("obs_cadence_seconds", 1800),
        ("obs_routine_minute_by_station", {"NYC": 75}),
        ("obs_min_coverage_per_station_year", 1.5),
        ("obs_max_pin_minute_excluded_share", -0.1),
        ("obs_max_pin_minute_excluded_share", True),
        ("source_lags_ns", {"obs": 1}),
        ("anchors", {"D-1": 1}),
    ],
)
def test_a_malformed_builder_pin_refuses_by_name(tmp_path: Path, name: str, bad: Any) -> None:
    prereg = _freeze(tmp_path / "repo", _design(**{name: bad}))

    with pytest.raises(skill.Refusal, match=name):
        skill.load_verified_prereg(prereg)


# ------------------------------------------------------------------ the veto runs the same check


def _veto_args(prereg: Path, tmp_path: Path) -> list[str]:
    return ["--prereg", str(prereg), "--oof-rows", str(tmp_path / "x.jsonl"), "--out", "o.json"]


def test_the_veto_refuses_an_unfrozen_prereg(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "p.json"
    path.write_text(json.dumps({**_design(), "frozen_sha": "UNFROZEN"}), encoding="utf-8")

    assert veto.main(_veto_args(path, tmp_path)) == 2
    assert "UNFROZEN" in capsys.readouterr().err


def test_the_veto_refuses_an_edited_frozen_blob(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    prereg = _freeze(tmp_path / "repo", _design())
    edited = json.loads(prereg.read_text(encoding="utf-8"))
    edited["pins"]["floor_multiple"] = 0.01
    prereg.write_text(json.dumps(edited), encoding="utf-8")

    assert veto.main(_veto_args(prereg, tmp_path)) == 2
    assert "differs" in capsys.readouterr().err


def test_the_veto_refuses_a_refrozen_prereg(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    prereg = _freeze(repo, _design())
    again = json.loads(prereg.read_text(encoding="utf-8"))
    again["frozen_sha"] = _git(repo, "rev-parse", "HEAD")
    again["pins"]["floor_multiple"] = 0.5
    _commit_edit(repo, "prereg.json", again)

    assert veto.main(_veto_args(prereg, tmp_path)) == 2
    assert "re-frozen" in capsys.readouterr().err
