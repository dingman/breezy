"""Outcome-blind seam C contracts; all study artifacts stay under tmp_path."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Sequence
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, cast

import pytest

import breezy.analysis.leak_null as ln
import breezy.analysis.leak_null_decide as dec
import breezy.analysis.multisource_blend as msb
from scripts.analysis import leak_null_guards as g
from scripts.analysis import leak_null_study as study
from scripts.analysis import multisource_blend_skill as skill
from scripts.analysis.multisource_blend_lag_arm import split_lag_keys
from tests.unit.test_leak_null import _null_fixture
from tests.unit.test_leak_null_guards import _draft
from tests.unit.test_multisource_blend_skill import _PINS

N1, N2, N3 = ln.NullId


@pytest.fixture
def case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, ...]:
    out = tmp_path / "leak_null_2026-11-03"
    prereg = tmp_path / "prereg.json"
    prereg.write_text("synthetic frozen design\n")
    design = g.LeakNullDesign(
        prereg,
        hashlib.sha256(prereg.read_bytes()).hexdigest(),
        "frozen",
        "a" * 40,
        g.PINNED_BLOBS,
        {},
        (31, 32, 33),
        999,
        asdict(replace(dec.THRESHOLDS, k=3, pc_k=3)),
        {"m0p_vs_m3_mean": 0.165, "m0p_vs_m3_lb": 0.15, "floor": 0.01},
        out,
    )
    rows, plan, settings = _null_fixture()
    ctx = skill.RunContext(
        {"pins": _PINS, "fixed_by_plan": {"mean_block_days": 7}},
        out,
        rows,
        rows,
        settings,
        plan,
        3,
        split_lag_keys(rows, rows),
    )

    def unchanged(out: Path, path: Path, design: g.LeakNullDesign, repo: Path) -> None:
        if hashlib.sha256(path.read_bytes()).hexdigest() != design.prereg_sha256:
            raise g.Refusal("prereg digest changed")

    monkeypatch.setattr(g, "assert_unchanged", unchanged)
    monkeypatch.setattr(study, "_prepare_context", lambda design: ctx)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    return ctx, design, out


def _fake_scores(
    rows: Sequence[msb.FeatureRow],
    plan: msb.FoldPlan,
    settings: msb.BlendSettings,
    **kwargs: Any,
) -> list[msb.ScoredRow]:
    """A deterministic score surrogate for I/O tests; e2e tests use real fits."""
    assert kwargs == {"levels": (0, 3), "champion": False, "embargo_days": 3}
    return [
        msb.ScoredRow(
            r.station,
            r.climate_day,
            r.horizon,
            r.version,
            fold.fold_id,
            r.cli_tmax_f,
            {"M0prime": 2.0, "M3": 1.0 if r.prefix_level else 2.0},
            {},
            None,
            {"M3": r.prefix_level},
        )
        for fold in plan.folds
        for r in rows
        if r.version == fold.version and r.climate_day in fold.held_days
    ]


def _fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(msb, "out_of_fold_scores", _fake_scores)


@pytest.mark.parametrize("kind", ["direct", "symlink", "dotdot"])
def test_refuses_out_dir_inside_gap1_j3_dir(tmp_path: Path, kind: str) -> None:
    sealed = tmp_path / "gap1_j3_2026-11-02"
    sealed.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(sealed, target_is_directory=True)
    parent = {"direct": sealed, "symlink": alias, "dotdot": sealed / ".."}[kind]
    with pytest.raises(g.Refusal, match="gap1_j3"):
        g.guard_out_dir(parent / "leak_null_2026-11-03", tmp_path)


@pytest.mark.parametrize("resolved", [False, True])
def test_refuses_live_data_root_raw_and_resolved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    resolved: bool,
) -> None:
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    live = tmp_path / ".local/share/breezy"
    live.mkdir(parents=True)
    alias = tmp_path / "alias"
    alias.symlink_to(live, target_is_directory=True)
    with pytest.raises(g.Refusal, match="live data"):
        g.guard_out_dir((alias if resolved else live) / "leak_null_2026-11-03", tmp_path)


def test_refuses_bad_basename(tmp_path: Path) -> None:
    with pytest.raises(g.Refusal, match="basename"):
        g.guard_out_dir(tmp_path / "result", tmp_path)


def test_never_scores_unpermuted_labels(
    case: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, design, out = case
    original = {(r.version, r.station, r.climate_day): r.cli_tmax_f for r in ctx.rows}
    calls = []

    def spy(rows: Sequence[msb.FeatureRow], *args: Any, **kwargs: Any) -> list[msb.ScoredRow]:
        labels = {(r.version, r.station, r.climate_day): r.cli_tmax_f for r in rows}
        assert sum(v != original[k] for k, v in labels.items()) >= len(original) * 0.5
        calls.append(1)
        return _fake_scores(rows, *args, **kwargs)

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("F13 stages must never run")

    monkeypatch.setattr(msb, "out_of_fold_scores", spy)
    for name in ("run_stage_a", "run_stage_b", "_score"):
        monkeypatch.setattr(skill, name, forbidden)
    study.run_study(ctx, design, out)
    assert len(calls) == 12  # three PC calls, then three nulls per study seed


def test_result_allowlist_has_no_primary_statistic(
    case: tuple[Any, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx, design, out = case
    _fast(monkeypatch)
    result = study.run_study(ctx, design, out)
    assert set(result) == {
        "prereg_sha256",
        "code_sha",
        "verdict",
        "reasons",
        "by_null",
        "positive_control",
        "invariant_defects",
        "f13_bias_adjusted",
        "limitations",
    }
    assert "m0p_vs_m3_mean" not in json.dumps(result)
    assert "wall_s" not in json.dumps(result)
    assert json.loads((out / "leak_null_result.json").read_text()) == result


def test_seed_determinism_byte_identical(
    case: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, design, out = case
    _fast(monkeypatch)
    study.run_study(ctx, design, out)
    other = out.parent / "other/leak_null_2026-11-03"
    study.run_study(ctx, design, other)
    for path in (out / "seeds").glob("*.json"):
        assert path.read_bytes() == (other / "seeds" / path.name).read_bytes()
        assert "wall_s" not in path.read_text()
    assert (out / "timing.jsonl").is_file()


def test_seed_files_write_once_and_resume_skips_done(
    case: tuple[Any, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx, design, out = case
    _fast(monkeypatch)
    original = study.run_seed

    def interrupt(ctx: skill.RunContext, design: g.LeakNullDesign, seed: int) -> dict[str, Any]:
        if seed == design.seeds[1]:
            raise RuntimeError("interrupted")
        return original(ctx, design, seed)

    monkeypatch.setattr(study, "run_seed", interrupt)
    with pytest.raises(RuntimeError, match="interrupted"):
        study.run_study(ctx, design, out)
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (out / "seeds").glob("*.json")}
    calls = []

    def remaining(ctx: skill.RunContext, design: g.LeakNullDesign, seed: int) -> dict[str, Any]:
        calls.append(seed)
        return original(ctx, design, seed)

    monkeypatch.setattr(study, "run_seed", remaining)
    study.run_study(ctx, design, out)
    assert calls == list(design.seeds[1:])
    assert len(list((out / "seeds").glob("*.json"))) == 6
    for path, evidence in before.items():
        assert (path.read_bytes(), path.stat().st_mtime_ns) == evidence


@pytest.mark.parametrize("payload", ["{", "{}", '{"seed":31}', "[]"])
def test_torn_seed_file_refused(case: tuple[Any, ...], payload: str) -> None:
    ctx, design, out = case
    (out / "seeds").mkdir(parents=True)
    (out / "seeds/pc_31.json").write_text(payload)
    with pytest.raises(g.Refusal):
        study.run_study(ctx, design, out)
    assert not (out / "leak_null_result.json").exists()


def test_unfrozen_refused_outside_probe(tmp_path: Path) -> None:
    path = tmp_path / "draft.json"
    path.write_text(json.dumps(_draft(tmp_path)))
    assert study.main(["--prereg", str(path), "--out-dir", str(tmp_path / "out")]) == 2


def test_timing_probe_writes_nothing_under_out_root(
    case: tuple[Any, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx, design, out = case
    parents = []

    def prepare(design: g.LeakNullDesign) -> skill.RunContext:
        parents.append(design.out_root)
        (design.out_root / "prereg_record.json").write_text("probe only")
        return cast(skill.RunContext, ctx)

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("probe must never summarize or decide")

    monkeypatch.setattr(study, "_prepare_context", prepare)
    monkeypatch.setattr(dec, "seed_summary", forbidden)
    monkeypatch.setattr(dec, "decide", forbidden)
    _fast(monkeypatch)
    study.run_probe(replace(design, frozen_sha=skill.UNFROZEN), out.parent)
    assert parents and all(not p.exists() for p in parents)
    assert not out.exists()


def test_probe_prints_only_timing_keys_and_sums_three_nulls(
    case: tuple[Any, ...],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ctx, design, out = case
    ticks = iter([0.0, 1.0, 10.0, 12.0, 20.0, 23.0])
    monkeypatch.setattr(time, "perf_counter", lambda: next(ticks))
    calls = []

    def spy(rows: Sequence[msb.FeatureRow], plan: msb.FoldPlan, *a: Any, **kw: Any) -> Any:
        assert len(plan.folds) == 1
        assert len(plan.folds[0].train_days) == max(len(f.train_days) for f in ctx.plan.folds)
        calls.append(1)
        return _fake_scores(rows, plan, *a, **kw)

    monkeypatch.setattr(msb, "out_of_fold_scores", spy)
    line = study.run_probe(design, out.parent)
    printed = capsys.readouterr().out
    assert printed == line + "\n"
    values = {k: float(v) for k, v in (part.split("=") for part in line.split())}
    assert list(values) == ["folds", "n1_s", "n2_s", "n3_s", "projected_seed_s", "projected_pc_s"]
    assert list(values.values()) == [
        len(ctx.plan.folds),
        1,
        2,
        3,
        6 * len(ctx.plan.folds),
        10 * len(ctx.plan.folds),
    ]
    assert len(calls) == 3


def test_probe_parent_missing_refused_without_traceback(
    case: tuple[Any, ...], tmp_path: Path
) -> None:
    _, design, _ = case
    with pytest.raises(g.Refusal, match="existing directory"):
        study.run_probe(design, tmp_path / "absent_parent")


def test_probe_parent_inside_out_root_refused(case: tuple[Any, ...]) -> None:
    _, design, out = case
    with pytest.raises(g.Refusal, match="outside out_root"):
        study.run_probe(design, out / "probe")
    assert not out.exists()


def test_fold_breach_short_circuits_invalid(
    case: tuple[Any, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx, design, out = case
    first, *rest = ctx.plan.folds
    first = replace(first, train_days=first.train_days + first.held_days[:1])
    ctx = replace(ctx, plan=replace(ctx.plan, folds=(first, *rest)))
    monkeypatch.setattr(msb, "out_of_fold_scores", lambda *a, **kw: pytest.fail("fold breach"))
    result = study.run_study(ctx, design, out)
    assert result["verdict"] == "INVALID"
    assert any("overlap" in d for d in result["invariant_defects"])
    assert not list((out / "seeds").glob("*.json"))


def test_pc_unflagged_short_circuits_invalid(
    case: tuple[Any, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx, design, out = case
    design = replace(design, thresholds={**design.thresholds, "plant_noise_sd_f": 1e3})
    monkeypatch.setattr(study, "run_seed", lambda *a: pytest.fail("PC must short circuit"))
    result = study.run_study(ctx, design, out)
    assert result["verdict"] == "INVALID"
    assert result["positive_control"]["flagged"] is False
    assert not list((out / "seeds").glob("seed_*.json"))


def test_planted_leak_in_n2_drives_leak_confirmed(
    case: tuple[Any, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx, design, out = case
    real_score = msb.out_of_fold_scores

    def planted(
        rows: Sequence[msb.FeatureRow],
        plan: msb.FoldPlan,
        settings: msb.BlendSettings,
        **kwargs: Any,
    ) -> list[msb.ScoredRow]:
        if settings.weight_sum_lambda == 0:
            rows = ln.plant_leak(ln.NullLabels(tuple(rows), 1.0), seed=51, noise_sd_f=1).rows
        return real_score(rows, plan, settings, **kwargs)

    monkeypatch.setattr(msb, "out_of_fold_scores", planted)
    assert study.run_study(ctx, design, out)["verdict"] == "LEAK_CONFIRMED"


def test_end_to_end_fixture_emits_verdict_equal_to_decide(
    case: tuple[Any, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, design, out = case
    real_decide = dec.decide
    decisions = []

    def spy(*args: Any, **kwargs: Any) -> Any:
        decision = real_decide(*args, **kwargs)
        decisions.append(decision)
        return decision

    monkeypatch.setattr(dec, "decide", spy)
    result = study.run_study(study._prepare_context(design), design, out)
    assert result["positive_control"]["flagged"] is True
    assert not result["invariant_defects"]
    assert len(decisions) == 1
    assert result["verdict"] == decisions[0][0]
    assert result["reasons"] == list(decisions[0][1])
    assert 0 <= result["positive_control"]["plant_mask_rate"] <= 1
    assert set(result["by_null"]) == set(ln.NullId)


def test_prereg_changed_mid_run_writes_no_result(
    case: tuple[Any, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx, design, out = case
    _fast(monkeypatch)
    original = study.run_seed

    def change(*args: Any) -> Any:
        result = original(*args)
        design.prereg_path.write_text("changed")
        return result

    monkeypatch.setattr(study, "run_seed", change)
    with pytest.raises(g.Refusal, match="prereg digest changed"):
        study.run_study(ctx, design, out)
    assert not (out / "leak_null_result.json").exists()


def test_main_exits_2_on_refusal(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert study.main(["--prereg", str(tmp_path / "absent.json")]) == 2
    assert "cannot read" in capsys.readouterr().err


def test_main_exits_2_on_pure_module_refusal(
    case: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _, design, out = case

    def refuse(*args: Any, **kwargs: Any) -> None:
        raise ln.Refusal("moved_fraction must be at least 0.5 over nonempty rows")

    monkeypatch.setattr(g, "load_leak_prereg", lambda *a, **k: design)
    monkeypatch.setattr(g, "guard_out_dir", lambda *a: out)
    monkeypatch.setattr(g, "verify_inputs", lambda *a: {})
    monkeypatch.setattr(g, "check_code_pin", lambda *a: [])
    monkeypatch.setattr(g, "record_provenance", lambda *a: None)
    monkeypatch.setattr(study, "apply_address_space_cap", lambda *a: None)
    monkeypatch.setattr(ln, "null_label_rows", refuse)
    assert study.main(["--prereg", str(design.prereg_path), "--out-dir", str(out)]) == 2
    assert "moved_fraction" in capsys.readouterr().err
    assert not (out / "leak_null_result.json").exists()


def test_main_reports_skipped_module_origin_notes(
    case: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _, design, out = case
    monkeypatch.setattr(g, "load_leak_prereg", lambda *a, **k: design)
    monkeypatch.setattr(g, "guard_out_dir", lambda *a: out)
    monkeypatch.setattr(g, "verify_inputs", lambda *a: {})
    monkeypatch.setattr(g, "check_code_pin", lambda *a: ["pinned module x not loaded"])
    monkeypatch.setattr(g, "record_provenance", lambda *a: None)
    monkeypatch.setattr(study, "apply_address_space_cap", lambda *a: None)
    monkeypatch.setattr(
        study, "_prepare_context", lambda d: (_ for _ in ()).throw(g.Refusal("stop"))
    )
    assert study.main(["--prereg", str(design.prereg_path), "--out-dir", str(out)]) == 2
    assert "note: pinned module x not loaded" in capsys.readouterr().err


def test_main_guard_order(case: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch) -> None:
    ctx, design, out = case
    calls: list[str] = []

    def recorded(name: str, value: Any) -> Any:
        def call(*args: Any, **kwargs: Any) -> Any:
            calls.append(name)
            return value

        return call

    monkeypatch.setattr(g, "load_leak_prereg", recorded("load", design))
    monkeypatch.setattr(g, "guard_out_dir", recorded("out", out))
    monkeypatch.setattr(g, "verify_inputs", recorded("inputs", {}))
    monkeypatch.setattr(g, "check_code_pin", lambda *a: calls.append("code"))
    monkeypatch.setattr(g, "record_provenance", lambda *a: calls.append("provenance"))
    monkeypatch.setattr(study, "apply_address_space_cap", lambda *a: calls.append("cap"))
    monkeypatch.setattr(study, "_prepare_context", recorded("prepare", ctx))
    monkeypatch.setattr(study, "run_study", recorded("study", {}))
    assert study.main(["--prereg", str(design.prereg_path), "--out-dir", str(out)]) == 0
    assert calls == ["load", "out", "inputs", "code", "provenance", "cap", "prepare", "study"]


def test_fit_failure_is_per_null(case: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch) -> None:
    ctx, design, _ = case

    def fail_n2(rows: Any, plan: Any, settings: Any, **kwargs: Any) -> Any:
        if settings.weight_sum_lambda == 0:
            raise msb.FitNotConvergedError("synthetic fit failure")
        return _fake_scores(rows, plan, settings, **kwargs)

    monkeypatch.setattr(msb, "out_of_fold_scores", fail_n2)
    record = study.run_seed(ctx, design, design.seeds[0])
    assert record["summaries"][N2]["failed"] == "synthetic fit failure"
    assert record["summaries"][N1]["failed"] is None
    assert record["summaries"][N3]["failed"] is None


def test_score_requires_null_labels(case: tuple[Any, ...]) -> None:
    ctx, _, _ = case
    with pytest.raises(g.Refusal, match="NullLabels"):
        study._score(ctx, ctx.rows, ctx.settings)


def test_score_refuses_labels_below_moved_fraction(case: tuple[Any, ...]) -> None:
    ctx, design, _ = case
    labels = ln.null_label_rows(ctx.rows, design.seeds[0])
    object.__setattr__(labels, "moved_fraction", 0.49)  # bypass __post_init__
    with pytest.raises(g.Refusal, match="moved_fraction"):
        study._score(ctx, labels, ctx.settings)


@pytest.mark.parametrize("pin", ["prereg_sha256", "code_sha"])
def test_resume_refuses_changed_checkpoint_pin(
    case: tuple[Any, ...],
    monkeypatch: pytest.MonkeyPatch,
    pin: str,
) -> None:
    ctx, design, out = case
    _fast(monkeypatch)
    (out / "seeds").mkdir(parents=True)
    study.run_pc(ctx, design)
    path = out / "seeds/pc_31.json"
    record = json.loads(path.read_text())
    record[pin] = "different"
    path.write_text(json.dumps(record))
    with pytest.raises(g.Refusal, match="checkpoint provenance differs"):
        study.run_study(ctx, design, out)
    assert not (out / "leak_null_result.json").exists()


def test_probe_cleanup_on_score_failure(
    case: tuple[Any, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx, design, out = case
    created = []

    def prepare(design: g.LeakNullDesign) -> skill.RunContext:
        created.append(design.out_root)
        return cast(skill.RunContext, ctx)

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("probe failed")

    monkeypatch.setattr(study, "_prepare_context", prepare)
    monkeypatch.setattr(msb, "out_of_fold_scores", fail)
    with pytest.raises(RuntimeError, match="probe failed"):
        study.run_probe(design, out.parent)
    assert created and all(not p.exists() for p in created)
    assert not out.exists()


def test_main_probe_does_not_record_provenance(
    case: tuple[Any, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, design, out = case
    monkeypatch.setattr(g, "load_leak_prereg", lambda *a, **kw: design)
    monkeypatch.setattr(g, "verify_inputs", lambda *a: {})
    monkeypatch.setattr(g, "check_code_pin", lambda *a: None)
    monkeypatch.setattr(study, "apply_address_space_cap", lambda *a: None)
    monkeypatch.setattr(g, "record_provenance", lambda *a: pytest.fail("probe provenance"))
    _fast(monkeypatch)
    assert (
        study.main(
            [
                "--prereg",
                str(design.prereg_path),
                "--timing-probe",
                "--probe-parent",
                str(out.parent),
            ]
        )
        == 0
    )
    assert not out.exists()


@pytest.mark.parametrize("broken", ["level0", "m0prime", "fold"])
def test_scored_invariant_breach_is_invalid(
    case: tuple[Any, ...],
    monkeypatch: pytest.MonkeyPatch,
    broken: str,
) -> None:
    ctx, design, out = case
    calls = 0

    def breach(*args: Any, **kwargs: Any) -> list[msb.ScoredRow]:
        nonlocal calls
        calls += 1
        scored = _fake_scores(*args, **kwargs)
        if calls <= 3:
            return scored
        if broken == "fold":
            scored[0] = replace(scored[0], fold_id=-1)
        elif broken == "level0":
            scored[0] = replace(scored[0], crps={"M0prime": 2.0, "M3": 1.0}, levels={"M3": 0})
        elif calls % 3 == 0:
            scored[0] = replace(scored[0], crps={"M0prime": 3.0, "M3": 3.0})
        return scored

    monkeypatch.setattr(msb, "out_of_fold_scores", breach)
    result = study.run_study(ctx, design, out)
    assert result["verdict"] == "INVALID"
    assert result["invariant_defects"]


@pytest.mark.parametrize("broken", ["invariants", "summary"])
def test_semantically_torn_seed_file_refused(
    case: tuple[Any, ...],
    monkeypatch: pytest.MonkeyPatch,
    broken: str,
) -> None:
    ctx, design, out = case
    _fast(monkeypatch)
    (out / "seeds").mkdir(parents=True)
    study.run_pc(ctx, design)
    record = study.run_seed(ctx, design, 31)
    if broken == "invariants":
        record["invariants"] = {}
    else:
        record["summaries"][N1]["day_values"] = []
    (out / "seeds/seed_31.json").write_text(json.dumps(record))
    with pytest.raises(g.Refusal):
        study.run_study(ctx, design, out)
    assert not (out / "leak_null_result.json").exists()
