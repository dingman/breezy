"""RED-first tests for the F13 Phase A review-fix batch (runner and veto side).

Items: embargo pin + S1/S2/S3 reporting in the runner, S5 (``raw_nbp_cdf`` veto reference),
P4 (veto refusals, null-pin check, OOF digest), P6 (prereg value type checks), P7 (stage split,
write-once ``stage_a.json``). Synthetic fixtures and temporary git repositories only.
"""

from __future__ import annotations

import ast
import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest

from breezy.analysis import multisource_blend as msb
from breezy.strategy.ladder_ev.quantile_density import (
    CdfMethod,
    Percentiles,
    build_cdf,
    rung_probabilities,
)
from scripts.analysis import blend_veto_descriptive as veto
from scripts.analysis import multisource_blend_skill as skill
from scripts.analysis.fq_evaluate_shim import Side
from tests.unit.test_multisource_blend import make_rows
from tests.unit.test_multisource_blend_skill import (
    _LADDER,
    REPO_ROOT,
    _design,
    _freeze,
    _Scenario,
    _scored,
    _write_features,
)

_CONST_REFERENCE = {"kind": "const", "price": 0.2}


class _VetoScenario(_Scenario):
    """A scenario whose frozen prereg also pins the veto reference ask."""

    def __init__(self, tmp_path: Path, reference: Any = _CONST_REFERENCE, **pins: Any) -> None:
        super().__init__(tmp_path, **pins)
        design = _design(**pins)
        design["veto"] = {**design["veto"], "reference": reference}
        self.prereg = _freeze(self.repo, design, name="prereg_veto.json")
        self.write_sidecars()

    def veto_args(self, *, oof: Path | None = None, out: Path | None = None) -> list[str]:
        return [
            "--prereg",
            str(self.prereg),
            "--oof-rows",
            str(oof or self.out / "oof_rows.jsonl"),
            "--out",
            str(out or self.out / "veto.json"),
        ]


# ------------------------------------------------------------------ embargo pin + reporting


def test_embargo_days_is_a_required_pin_filled_in_the_draft_prereg() -> None:
    assert "embargo_days" in skill.REQUIRED_PINS
    draft = json.loads(
        (
            REPO_ROOT / "docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/F13_prereg_blend_v1.json"
        ).read_text(encoding="utf-8")
    )
    assert draft["pins"]["embargo_days"] == 3  # PIN-R2: fixed literal in the skeleton
    assert "embargo_days" in draft["pin_units"]


def test_runner_refuses_a_null_embargo_pin(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path, embargo_days=None)
    with pytest.raises(skill.Refusal, match="embargo_days"):
        scenario.run()


def test_runner_applies_the_pinned_embargo_to_every_scoring_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scenario = _Scenario(tmp_path)
    seen: list[Any] = []
    real = msb.out_of_fold_scores

    def _spy(*args: Any, **kwargs: Any) -> Any:
        seen.append(kwargs.get("embargo_days"))
        return real(*args, **kwargs)

    monkeypatch.setattr(msb, "out_of_fold_scores", _spy)
    result = scenario.run()
    assert len(seen) >= 4 and set(seen) == {2}
    assert result["embargo_days"] == 2


def test_runner_reports_pooled_m0_complete_case_levels_and_fallbacks(tmp_path: Path) -> None:
    result = _Scenario(tmp_path).run()
    assert "M0pooled" in result["ladder_mean_crps"]
    pooled = result["pooled_m0_sensitivity"]
    assert pooled["mean_crps"] == pytest.approx(result["ladder_mean_crps"]["M0pooled"])
    assert pooled["difference_vs_m0"] == pytest.approx(
        result["ladder_mean_crps"]["M0pooled"] - result["ladder_mean_crps"]["M0"]
    )
    assert pooled["label"] == "sensitivity_only_never_gating"
    assert result["complete_case"]["label"] == "diagnostic_only_never_gating"
    assert sum(result["level_counts"]["M3"].values()) == result["rows_scored"]
    assert set(result["fit_fallbacks"]) == {"M0prime", "M1", "M2", "M3"}
    assert "m0p_vs_m0_two_sided" in result["report"]


def test_runner_refuses_when_no_fold_has_an_admissible_m0_pool(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path)
    solo = make_rows(
        days=112,
        start=dt.date(2025, 1, 1),
        version="v4.2",
        stations=("NYC",),
        horizons=("D-1",),
        seed=3,
    )
    _write_features(scenario.features, solo)
    _write_features(scenario.lag_features, solo)
    with pytest.raises(skill.Refusal, match="M0 pool"):
        scenario.run()
    assert not (scenario.out / "stage_a.json").exists()


# ------------------------------------------------------------------ S2: negative-control gate


def test_positive_shuffled_lower_bound_holds_the_run_for_leak_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clean = _Scenario(tmp_path / "clean").run()
    assert clean["delta_m0p_m3"]["lb"] > 0.0  # the fixture has real skill
    assert clean["negative_control"]["lb"] <= 0.0
    assert clean["verdict"] != msb.Verdict.HELD_LEAK_AUDIT.value
    # an identity "shuffle" leaves the skill in: the control now shows a positive lower bound
    monkeypatch.setattr(msb, "shuffle_labels", lambda rows, seed: list(rows))
    leaky = _Scenario(tmp_path / "leaky").run()
    assert leaky["negative_control"]["lb"] > 0.0
    assert leaky["verdict"] == msb.Verdict.HELD_LEAK_AUDIT.value
    assert any("negative control" in reason for reason in leaky["reasons"])


# ------------------------------------------------------------------ P7: stages + write-once


def test_stage_a_json_is_write_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scenario = _Scenario(tmp_path)
    scenario.out.mkdir(parents=True)
    sentinel = scenario.out / "stage_a.json"
    sentinel.write_text('{"committed": true}', encoding="utf-8")
    calls: list[Any] = []
    real = msb.out_of_fold_scores

    def _spy(*args: Any, **kwargs: Any) -> Any:
        calls.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(msb, "out_of_fold_scores", _spy)
    with pytest.raises(skill.Refusal, match="stage_a.json"):
        scenario.run()
    assert calls == []
    assert sentinel.read_text(encoding="utf-8") == '{"committed": true}'


def test_a_finished_run_directory_cannot_be_rerun(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path)
    scenario.run()
    committed = (scenario.out / "stage_a.json").read_text(encoding="utf-8")
    with pytest.raises(skill.Refusal, match="stage_a.json"):
        scenario.run()
    assert (scenario.out / "stage_a.json").read_text(encoding="utf-8") == committed


def test_write_stage_a_refuses_to_overwrite(tmp_path: Path) -> None:
    skill.write_stage_a(tmp_path, {"floor": 1.0})
    with pytest.raises(skill.Refusal, match="stage_a.json"):
        skill.write_stage_a(tmp_path, {"floor": 2.0})
    assert json.loads((tmp_path / "stage_a.json").read_text(encoding="utf-8")) == {"floor": 1.0}


def test_run_is_split_into_prepare_stage_a_stage_b_and_assembly() -> None:
    tree = ast.parse((REPO_ROOT / "scripts/analysis/multisource_blend_skill.py").read_text("utf-8"))
    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    for name in ("prepare_run", "run_stage_a", "run_stage_b", "assemble_result", "run"):
        assert name in functions, name
    run = functions["run"]
    assert (run.end_lineno or 0) - run.lineno < 40
    for node in functions.values():
        assert (node.end_lineno or 0) - node.lineno < 80, node.name


# ------------------------------------------------------------------ P6: value type checks


@pytest.mark.parametrize(
    ("key", "bad"),
    [
        ("block_days", None),
        ("block_days", "28"),
        ("block_days", 0),
        ("block_days", True),
        ("min_train_days", None),
        ("min_blocks", 1.5),
        ("mean_block_days", None),
        ("mean_block_days", "seven"),
        ("mean_block_days", 0),
        ("c1_min_measured_days", None),
        ("c1_min_measured_days", -1),
    ],
)
def test_fixed_by_plan_values_are_type_checked_into_a_refusal(
    tmp_path: Path, key: str, bad: Any
) -> None:
    design = _design()
    design["fixed_by_plan"][key] = bad
    prereg = _freeze(tmp_path / "repo", design)
    with pytest.raises(skill.Refusal, match=key):
        skill.load_verified_prereg(prereg)


def test_a_missing_fixed_by_plan_key_is_a_refusal(tmp_path: Path) -> None:
    design = _design()
    del design["fixed_by_plan"]["block_days"]
    prereg = _freeze(tmp_path / "repo", design)
    with pytest.raises(skill.Refusal, match="block_days"):
        skill.load_verified_prereg(prereg)


@pytest.mark.parametrize(
    ("key", "bad"),
    [
        ("student_t_nu", "six"),
        ("bootstrap_n", 1.5),
        ("min_cell_rows", True),
        ("source_breaks", "2025-01-01"),
        ("source_breaks", ["not-a-date"]),
        ("rung_edges_f", []),
        ("champion_cdf_method", "BOGUS"),
        ("embargo_days", -1),
    ],
)
def test_pin_values_are_type_checked_into_a_refusal(tmp_path: Path, key: str, bad: Any) -> None:
    prereg = _freeze(tmp_path / "repo", _design(**{key: bad}))
    with pytest.raises(skill.Refusal, match=key):
        skill.load_verified_prereg(prereg)


def test_a_bad_fixed_value_exits_2_through_main_not_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(skill, "apply_address_space_cap", lambda _gib: 0)  # never cap pytest
    scenario = _Scenario(tmp_path)
    design = _design()
    design["fixed_by_plan"]["block_days"] = None
    scenario.prereg = _freeze(scenario.repo, design, name="bad.json")
    code = skill.main(
        [
            "--prereg",
            str(scenario.prereg),
            "--features",
            str(scenario.features),
            "--lag-features",
            str(scenario.lag_features),
            "--c1-evidence",
            str(scenario.evidence),
            "--out-dir",
            str(scenario.out),
        ]
    )
    assert code == 2 and "REFUSED:" in capsys.readouterr().err


# ------------------------------------------------------------------ S5: raw_nbp_cdf reference


def _raw_design(**spec: Any) -> dict[str, Any]:
    return {"veto": {"reference": {"kind": "raw_nbp_cdf", **spec}}}


def test_raw_nbp_cdf_reference_is_the_uncalibrated_normal_rung_probability_plus_spread() -> None:
    reference = veto.reference_from_prereg(_raw_design(spread_prob=0.03), _LADDER)
    row = _scored(fold_id=1)
    assert row.champion is not None
    probs = rung_probabilities(build_cdf(CdfMethod.NORMAL, row.champion.percentiles), _LADDER)
    priced = 0
    for rung in _LADDER:
        quotes: tuple[tuple[Side, float], ...] = (
            ("yes", probs[rung.rung_id] + 0.03),
            ("no", 1.0 - probs[rung.rung_id] + 0.03),
        )
        for side, expected in quotes:
            ask = reference(row, rung, side)
            if 0.0 < expected < 1.0:
                assert ask is not None and ask.price == pytest.approx(expected)
                assert ask.source == veto.SOURCE_PREREG_REFERENCE
                priced += 1
            else:
                assert ask is None  # p + spread outside (0, 1) is no tradable ask
    assert priced >= len(_LADDER)  # the fixture prices most rungs on both sides


def test_raw_nbp_cdf_reference_ignores_the_calibrated_champion_params() -> None:
    reference = veto.reference_from_prereg(_raw_design(spread_prob=0.03), _LADDER)
    row = _scored(fold_id=1)
    assert row.champion is not None
    shifted = msb.ScoredRow(
        **{
            **{f: getattr(row, f) for f in row.__dataclass_fields__},
            "champion": msb.ChampionSpec(
                "NORMAL", row.champion.percentiles, a=5.0, gamma=1.0, delta=0.5
            ),
        }
    )
    for rung in _LADDER:
        assert reference(shifted, rung, "yes") == reference(row, rung, "yes")


def test_raw_nbp_cdf_reference_returns_no_ask_when_the_price_leaves_the_unit_interval() -> None:
    sharp = Percentiles(q10=69.9, q25=69.95, q50=70.0, q75=70.05, q90=70.1, mean=70.0, sd=0.2)
    base = _scored(fold_id=1)
    row = msb.ScoredRow(
        **{
            **{f: getattr(base, f) for f in base.__dataclass_fields__},
            "champion": msb.ChampionSpec("NORMAL", sharp, 0.0, 0.0, 0.0),
        }
    )
    reference = veto.reference_from_prereg(_raw_design(spread_prob=0.05), _LADDER)
    rung = next(r for r in _LADDER if r.rung_id == "70-71")
    p_yes = rung_probabilities(build_cdf(CdfMethod.NORMAL, sharp), _LADDER)["70-71"]
    assert p_yes > 0.95
    assert reference(row, rung, "yes") is None  # p + spread >= 1 is not a tradable ask
    assert reference(row, rung, "no") is not None


@pytest.mark.parametrize("bad", [None, "x", float("nan"), float("inf"), -0.01, 1.0, True])
def test_raw_nbp_cdf_reference_refuses_a_bad_spread(bad: Any) -> None:
    with pytest.raises(veto.Refusal, match="spread_prob"):
        veto.reference_from_prereg(_raw_design(spread_prob=bad), _LADDER)
    with pytest.raises(veto.Refusal, match="spread_prob"):
        veto.reference_from_prereg(_raw_design(), _LADDER)


def test_unknown_reference_kind_is_refused_and_const_is_documented_unsuitable() -> None:
    with pytest.raises(veto.Refusal, match="kind"):
        veto.reference_from_prereg({"veto": {"reference": {"kind": "magic"}}}, _LADDER)
    doc = (veto.reference_from_prereg.__doc__ or "").lower()
    assert "const" in doc and "unsuitable" in doc
    constant = veto.reference_from_prereg({"veto": {"reference": _CONST_REFERENCE}}, _LADDER)
    ask = constant(_scored(fold_id=1), _LADDER[0], "yes")
    assert ask is not None and ask.price == pytest.approx(0.2)


def test_proxy_report_runs_with_the_raw_nbp_reference() -> None:
    reference = veto.reference_from_prereg(_raw_design(spread_prob=0.02), _LADDER)
    report = veto.proxy_report(
        [_scored(fold_id=1, mu=60.0, station="LAX", observed=61.0)],
        rungs=_LADDER,
        reference_ask=reference,
    )
    assert report["label"] == "descriptive_only_no_verdict"


# ------------------------------------------------------------------ P4: veto main


def test_veto_main_accepts_a_run_directory_recorded_under_the_same_prereg(tmp_path: Path) -> None:
    scenario = _VetoScenario(tmp_path)
    scenario.run()
    assert veto.main(scenario.veto_args()) == 0
    report = json.loads((scenario.out / "veto.json").read_text(encoding="utf-8"))
    assert report["label"] == "descriptive_only_no_verdict"


def test_runner_oof_file_carries_the_prereg_digest(tmp_path: Path) -> None:
    scenario = _VetoScenario(tmp_path)
    scenario.run()
    record = json.loads((scenario.out / "prereg_record.json").read_text(encoding="utf-8"))
    first = (scenario.out / "oof_rows.jsonl").read_text(encoding="utf-8").splitlines()[0]
    header = json.loads(first)["header"]
    assert header["content_sha256"] == record["content_sha256"]
    assert header["frozen_sha"] == record["frozen_sha"]


def _refused(code: int, capsys: pytest.CaptureFixture[str], needle: str) -> None:
    err = capsys.readouterr().err
    assert code == 2 and err.startswith("REFUSED:") and needle in err, err


def test_veto_refuses_an_oof_file_without_a_digest_header(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scenario = _VetoScenario(tmp_path)
    scenario.run()
    lines = (scenario.out / "oof_rows.jsonl").read_text(encoding="utf-8").splitlines()
    bare = tmp_path / "bare"
    bare.mkdir()
    (bare / "oof_rows.jsonl").write_text("\n".join(lines[1:]), encoding="utf-8")
    (bare / "prereg_record.json").write_text(
        (scenario.out / "prereg_record.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    code = veto.main(scenario.veto_args(oof=bare / "oof_rows.jsonl", out=bare / "v.json"))
    _refused(code, capsys, "digest")


def test_veto_refuses_an_oof_digest_that_differs_from_the_recorded_prereg(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scenario = _VetoScenario(tmp_path)
    scenario.run()
    forged = tmp_path / "forged"
    forged.mkdir()
    lines = (scenario.out / "oof_rows.jsonl").read_text(encoding="utf-8").splitlines()
    header = json.loads(lines[0])
    header["header"]["content_sha256"] = "0" * 64
    (forged / "oof_rows.jsonl").write_text("\n".join([json.dumps(header), *lines[1:]]), "utf-8")
    (forged / "prereg_record.json").write_text(
        (scenario.out / "prereg_record.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    code = veto.main(scenario.veto_args(oof=forged / "oof_rows.jsonl", out=forged / "v.json"))
    _refused(code, capsys, "digest")


def test_veto_refuses_when_the_run_directory_has_no_prereg_record(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scenario = _VetoScenario(tmp_path)
    scenario.run()
    lonely = tmp_path / "lonely"
    lonely.mkdir()
    (lonely / "oof_rows.jsonl").write_text(
        (scenario.out / "oof_rows.jsonl").read_text(encoding="utf-8"), encoding="utf-8"
    )
    code = veto.main(scenario.veto_args(oof=lonely / "oof_rows.jsonl", out=lonely / "v.json"))
    _refused(code, capsys, "prereg_record.json")


def test_veto_refuses_a_different_frozen_prereg_than_the_one_that_scored(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scenario = _VetoScenario(tmp_path)
    scenario.run()
    other_design = _design(floor_multiple=0.01)
    other_design["veto"] = {**other_design["veto"], "reference": _CONST_REFERENCE}
    other = _freeze(scenario.repo, other_design, name="other.json")
    args = scenario.veto_args()
    args[1] = str(other)
    _refused(veto.main(args), capsys, "digest")


def test_veto_enforces_the_full_null_pin_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scenario = _VetoScenario(tmp_path)
    scenario.run()
    design = _design(floor_multiple=None)
    design["veto"] = {**design["veto"], "reference": _CONST_REFERENCE}
    nulled = _freeze(scenario.repo, design, name="nulled.json")
    args = scenario.veto_args()
    args[1] = str(nulled)
    _refused(veto.main(args), capsys, "floor_multiple")


def test_veto_refuses_an_unsupported_reference_kind_with_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scenario = _VetoScenario(tmp_path, reference={"kind": "magic"})
    scenario.run()
    _refused(veto.main(scenario.veto_args()), capsys, "kind")


def test_veto_refuses_sealed_rows_with_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scenario = _VetoScenario(tmp_path)
    scenario.run()
    path = scenario.out / "oof_rows.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    sealed = msb.scored_row_to_json(_scored(fold_id=1, day=dt.date(2026, 7, 2)))
    path.write_text("\n".join([*lines, json.dumps(sealed)]), encoding="utf-8")
    code = veto.main(scenario.veto_args())
    assert code == 2 and "REFUSED:" in capsys.readouterr().err
