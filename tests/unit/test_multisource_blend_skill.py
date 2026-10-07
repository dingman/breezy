"""RED-first tests for the F13 Phase A runner and the descriptive veto analysis.

Runner: ``scripts/analysis/multisource_blend_skill.py``.
Veto: ``scripts/analysis/blend_veto_descriptive.py``.
Synthetic fixtures only; temporary git repositories for the prereg freeze checks. Nothing reads real
data, the network or a sealed (>= 2026-07-01) day.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, REPO_ROOT.as_posix())

from breezy.analysis import multisource_blend as msb
from breezy.strategy.ladder_ev.quantile_density import Percentiles, Rung
from scripts.analysis import blend_veto_descriptive as veto
from scripts.analysis import multisource_blend_skill as skill
from tests.unit.test_multisource_blend import make_rows, two_version_rows

_PREREG_SRC = (
    REPO_ROOT
    / "docs"
    / "plans"
    / "backlog"
    / "FQ_LOSS_RESPONSE_2026-10-04"
    / "F13_prereg_blend_v1.json"
)
_SIDECAR_ANCHORS: dict[str, Any] = {
    "D-1": {"kind": "utc", "hour": 18},
    "D0": {"kind": "lst", "hour": 10},
    "D0_sensitivity": {"kind": "lst", "hour": 12},
    "offset_rule": "fixed_standard_time_never_dst",
}
_PINS: dict[str, Any] = {
    "anchors": _SIDECAR_ANCHORS,
    "floor_multiple": 0.5,
    "m0_prime_tolerance_crps_f": 0.2,
    "station_tolerance_crps_f": 0.2,
    "leak_audit_spread_multiple": 50.0,
    "student_t_nu": 6.0,
    "sigma_floor_f": 0.5,
    "weight_sum_lambda": 1.0,
    "min_cell_rows": 20,
    "bootstrap_n": 200,
    "bootstrap_seed": 17,
    "champion_cdf_method": "NORMAL",
    "m0_bootstrap_draws": 3,
    "source_breaks": [],
    "rung_edges_f": [50, 55, 60, 65, 70, 75],
    "min_uncensored_lag_samples": 5,
    "embargo_days": 2,
    "lag_arm_max_lost_fraction": 0.5,
}


# ------------------------------------------------------------------ git + prereg helpers


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def _freeze(repo: Path, design: dict[str, Any], name: str = "prereg.json") -> Path:
    """Commit the draft, then stamp that commit's sha as frozen_sha in a second commit."""
    repo.mkdir(parents=True, exist_ok=True)
    if not (repo / ".git").exists():
        _git(repo, "init", "-q")
    path = repo / name
    path.write_text(
        json.dumps({**design, "frozen_sha": msb_unfrozen()}, indent=2), encoding="utf-8"
    )
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", "draft")
    sha = _git(repo, "rev-parse", "HEAD")
    path.write_text(json.dumps({**design, "frozen_sha": sha}, indent=2), encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", "stamp")
    return path


def msb_unfrozen() -> str:
    return skill.UNFROZEN


def _design(**pin_overrides: Any) -> dict[str, Any]:
    draft: dict[str, Any] = json.loads(_PREREG_SRC.read_text(encoding="utf-8"))
    draft["pins"] = {**_PINS, **pin_overrides}
    return draft


def _write_features(path: Path, rows: list[msb.FeatureRow]) -> Path:
    path.write_text(
        "\n".join(json.dumps(msb.feature_row_to_json(r)) for r in rows), encoding="utf-8"
    )
    sidecar = Path(str(path) + skill.SIDECAR_SUFFIX)
    if sidecar.exists():  # FB-R14 fixture: a rewritten file keeps a sidecar that matches it
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
        kept = {k: v for k, v in meta.items() if k not in _DERIVED_SIDECAR_KEYS}
        write_sidecar(path, role=meta["role"], digest=meta["prereg_content_sha256"], **kept)
    return path


_DERIVED_SIDECAR_KEYS = ("schema", "role", "prereg_content_sha256", "features_sha256", "n_rows")
_SIDECAR_LAGS: dict[str, int] = {"lamp-mdl": 1, "lav-iem": 2, "pfm": 3, "mos-gfs": 4, "obs": 5}
_LAG_SHIFT_NS = 3_600_000_000_000


def write_sidecar(
    features: Path, *, role: str, digest: str, sha: str | None = None, **overrides: Any
) -> Path:
    """FB-R14 fixture helper: the ``<features>.manifest.json`` the builder would have written.

    Every field the runner cross-checks is present with a consistent default; ``overrides``
    replace (or, set to the ``DROP`` sentinel, remove) a field to build a broken sidecar.
    """
    path = Path(str(features) + skill.SIDECAR_SUFFIX)
    body: dict[str, Any] = {
        "schema": skill.SIDECAR_SCHEMA,
        "role": role,
        "prereg_content_sha256": digest,
        "features_sha256": sha or hashlib.sha256(features.read_bytes()).hexdigest(),
        "n_rows": len([ln for ln in features.read_text(encoding="utf-8").splitlines() if ln]),
        "anchor_variant": "primary",
        "anchors": _SIDECAR_ANCHORS,
        "source_lags_ns": _SIDECAR_LAGS,
        "obs_routine_minute_by_station": {"NYC": 40},
        "lag_shift_ns": _LAG_SHIFT_NS if role == "lag" else 0,
    }
    body.update(overrides)
    path.write_text(json.dumps({k: v for k, v in body.items() if v is not DROP}), encoding="utf-8")
    return path


DROP: Any = object()


class _Scenario:
    def __init__(self, tmp_path: Path, *, sidecars: bool = True, **pin_overrides: Any) -> None:
        self.sidecars = sidecars
        self.repo = tmp_path / "repo"
        self.prereg = _freeze(self.repo, _design(**pin_overrides))
        rows = two_version_rows(seed=5)
        self.rows = rows
        self.features = _write_features(tmp_path / "features.jsonl", rows)
        self.lag_features = _write_features(tmp_path / "features_lag60.jsonl", rows)
        self.evidence = tmp_path / "c1_lags.json"
        self.evidence.write_text(
            json.dumps(
                {
                    "measured_days": {"lamp": 20, "pfm": 20, "mos": 20},
                    "uncensored": {"lamp": 30, "pfm": 30, "mos": 30},
                }
            ),
            encoding="utf-8",
        )
        self.out = tmp_path / "out"
        self.write_sidecars()

    def write_sidecars(self) -> None:
        """Bind both feature files to the CURRENT prereg (no-op if ``sidecars=False``)."""
        if not self.sidecars:
            return
        digest = skill.content_digest(json.loads(self.prereg.read_text(encoding="utf-8")))
        write_sidecar(self.features, role="primary", digest=digest)
        write_sidecar(self.lag_features, role="lag", digest=digest)

    def run(self, **kwargs: Any) -> dict[str, Any]:
        return skill.run(
            prereg=self.prereg,
            features=self.features,
            lag_features=self.lag_features,
            c1_evidence=self.evidence,
            out_dir=self.out,
            **kwargs,
        )


# ------------------------------------------------------------------ prereg skeleton


def test_prereg_skeleton_is_an_unfrozen_draft_with_null_pins() -> None:
    draft = json.loads(_PREREG_SRC.read_text(encoding="utf-8"))
    assert draft["frozen_sha"] == "UNFROZEN"
    pins = draft["pins"]
    for key in ("floor_multiple", "m0_prime_tolerance_crps_f", "station_tolerance_crps_f"):
        assert key in pins and pins[key] is None
    assert "coordinator pins before any M1" in draft["pin_note"]
    assert set(skill.REQUIRED_PINS) <= set(pins)
    assert draft["fixed_by_plan"]["holdout_start"] == "2026-07-01"
    assert "decision.py:349-355" in draft["veto"]["take_rule"]["citation"]


# ------------------------------------------------------------------ the freeze


def test_prereg_sha_is_recorded_before_scoring_and_run_refuses_if_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []
    real = msb.out_of_fold_scores

    def _spy(*args: Any, **kwargs: Any) -> Any:
        record = scenario.out / "prereg_record.json"
        calls.append({"record_exists": record.exists(), "levels": kwargs.get("levels")})
        return real(*args, **kwargs)

    monkeypatch.setattr(msb, "out_of_fold_scores", _spy)

    # 1. an UNFROZEN draft never scores and never records
    draft = tmp_path / "draft"
    draft.mkdir()
    scenario = _Scenario(draft)
    unfrozen = scenario.repo / "unfrozen.json"
    unfrozen.write_text(json.dumps({**_design(), "frozen_sha": "UNFROZEN"}), encoding="utf-8")
    with pytest.raises(skill.Refusal, match="UNFROZEN"):
        skill.run(
            prereg=unfrozen,
            features=scenario.features,
            lag_features=scenario.lag_features,
            c1_evidence=scenario.evidence,
            out_dir=scenario.out,
        )
    assert calls == [] and not (scenario.out / "prereg_record.json").exists()

    # 2. a frozen prereg records its sha BEFORE the first scoring call, then scores
    result = scenario.run()
    record = json.loads((scenario.out / "prereg_record.json").read_text(encoding="utf-8"))
    frozen_sha = json.loads(scenario.prereg.read_text(encoding="utf-8"))["frozen_sha"]
    assert record["frozen_sha"] == frozen_sha == result["prereg_frozen_sha"]
    assert calls and all(c["record_exists"] for c in calls)

    # 3. an edited (uncommitted) prereg is refused: the blob differs from the frozen commit
    edited = json.loads(scenario.prereg.read_text(encoding="utf-8"))
    edited["pins"]["floor_multiple"] = 0.01
    scenario.prereg.write_text(json.dumps(edited, indent=2), encoding="utf-8")
    calls.clear()
    with pytest.raises(skill.Refusal, match="differs"):
        scenario.run()
    assert calls == []

    # 4. a re-frozen prereg with a different sha cannot reuse the recorded run directory
    _git(scenario.repo, "checkout", "-q", "--", "prereg.json")
    edited_design = _design(floor_multiple=0.01)
    scenario.prereg = _freeze(scenario.repo, edited_design)
    with pytest.raises(skill.Refusal, match="changed since"):
        scenario.run()
    assert calls == []


def test_runner_refuses_null_pins_even_when_frozen(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path, floor_multiple=None)
    with pytest.raises(skill.Refusal, match="floor_multiple"):
        scenario.run()
    assert not (scenario.out / "stage_a.json").exists()


def test_runner_commits_floor_before_scoring_m1_m3(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scenario = _Scenario(tmp_path)
    seen: list[tuple[tuple[int, ...], bool]] = []
    real = msb.out_of_fold_scores

    def _spy(*args: Any, **kwargs: Any) -> Any:
        levels = tuple(kwargs["levels"])
        seen.append((levels, (scenario.out / "stage_a.json").exists()))
        return real(*args, **kwargs)

    monkeypatch.setattr(msb, "out_of_fold_scores", _spy)
    result = scenario.run()
    stage_a = json.loads((scenario.out / "stage_a.json").read_text(encoding="utf-8"))
    assert seen[0] == ((0,), False)  # stage A scores M0 / M0' only
    later = [entry for entry in seen[1:] if set(entry[0]) & {1, 2, 3}]
    assert later and all(committed for _levels, committed in later)
    assert stage_a["floor"] == pytest.approx(result["floor"])
    assert stage_a["floor_multiple"] == 0.5
    assert stage_a["m1_m3_scored"] is False


def test_runner_refuses_until_c1_has_14_days_of_measured_lags(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path)
    scenario.evidence.write_text(
        json.dumps({"measured_days": {"lamp": 13, "pfm": 20, "mos": 20}, "uncensored": {}}),
        encoding="utf-8",
    )
    with pytest.raises(skill.Refusal, match="14"):
        scenario.run()
    assert not (scenario.out / "stage_a.json").exists()


def test_runner_refuses_sealed_holdout_rows(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path)
    sealed = make_rows(days=2, start=dt.date(2026, 7, 1), stations=("NYC",), horizons=("D-1",))
    _write_features(scenario.features, [*scenario.rows, *sealed])
    with pytest.raises(skill.Refusal, match="2026-07-01"):
        scenario.run()


def test_runner_end_to_end_reports_every_acceptance_input(tmp_path: Path) -> None:
    scenario = _Scenario(tmp_path)
    result = scenario.run()
    assert result["verdict"] in {v.value for v in msb.Verdict}
    assert result["primary_comparison"] == "M3 vs M0prime"
    for key in (
        "delta_m0p_m3",
        "delta_m0_m3",
        "fold_means_m0p_m3",
        "station_deltas",
        "lag_rerun",
        "diagnostics",
        "lamp_missingness",
        "m0_prime_status",
        "floor",
    ):
        assert key in result
    assert (scenario.out / "result.json").exists()
    assert (scenario.out / "oof_rows.jsonl").exists()
    assert result["rows_scored"] == len(scenario.rows)
    assert "abs_delta" not in result["negative_control"]
    assert set(result["negative_control"]) >= {"mean", "lb", "n_days"}


def test_runner_applies_the_memory_cap_before_scoring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scenario = _Scenario(tmp_path)
    order: list[str] = []

    def _cap(gib: float) -> int:
        order.append(f"cap:{gib}")
        return 1

    real = msb.out_of_fold_scores

    def _score(*args: Any, **kwargs: Any) -> Any:
        order.append("score")
        return real(*args, **kwargs)

    monkeypatch.setattr(skill, "apply_address_space_cap", _cap)
    monkeypatch.setattr(msb, "out_of_fold_scores", _score)
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
            "--max-memory-gib",
            "6",
        ]
    )
    assert code == 0
    assert order[0] == "cap:6.0" and "score" in order


# ------------------------------------------------------------------ veto: the FQ rule


def _scored(
    *,
    fold_id: int | None,
    day: dt.date = dt.date(2026, 5, 10),
    station: str = "NYC",
    mu: float = 66.0,
    observed: float = 70.0,
    horizon: str = "D-1",
) -> msb.ScoredRow:
    pct = Percentiles(q10=66.8, q25=68.3, q50=70.0, q75=71.7, q90=73.2, mean=70.0, sd=2.5)
    return msb.ScoredRow(
        station=station,
        climate_day=day,
        horizon=horizon,
        version="v5.0",
        fold_id=fold_id,
        observed_f=observed,
        crps={"M0": 1.0, "M3": 0.8},
        arm_predictions={"M3": msb.ArmPrediction(mu=mu, sigma=2.0, nu=6.0)},
        champion=msb.ChampionSpec(method="NORMAL", percentiles=pct, a=0.0, gamma=0.0, delta=0.0),
    )


_LADDER = (
    Rung("lt64", None, 63),
    Rung("64-65", 64, 65),
    Rung("66-67", 66, 67),
    Rung("68-69", 68, 69),
    Rung("70-71", 70, 71),
    Rung("72-73", 72, 73),
    Rung("ge74", 74, None),
)


def _const_reference(price: float = 0.20, source: str = "prereg_reference") -> Any:
    return lambda _row, _rung, _side: veto.ReferenceAsk(price=price, source=source)


def test_veto_rule_is_the_shipped_fq_take_rule() -> None:
    assert veto.RULE_CITATION["evaluate"].endswith("decision.py:349-355")
    assert veto.RULE_CITATION["margin"].endswith("margin.py:30-37")
    kwargs: dict[str, Any] = {"climate_day": dt.date(2026, 5, 10), "station": "NYC"}
    # cheap ask, confident model: a YES take
    assert veto.would_take(side="yes", p_yes=0.60, ask=0.30, **kwargs)
    # ask at the model's lower bound: edge after fee + slippage is negative
    assert not veto.would_take(side="yes", p_yes=0.60, ask=0.55, **kwargs)
    # clears break-even but not the horizon margin (0.06 at h=30)
    assert not veto.would_take(side="yes", p_yes=0.60, ask=0.50, **kwargs)
    # the NO leg reads p_upper
    assert veto.would_take(side="no", p_yes=0.10, ask=0.40, **kwargs)
    assert not veto.would_take(side="no", p_yes=0.60, ask=0.40, **kwargs)


def test_veto_proxy_uses_out_of_fold_champion_output() -> None:
    kwargs: dict[str, Any] = {"rungs": _LADDER, "reference_ask": _const_reference()}
    report = veto.proxy_report([_scored(fold_id=2)], **kwargs)
    assert report["n_rows"] == 1 and report["fitted_in_sample_champion_used"] is False
    with pytest.raises(veto.NotOutOfFoldError):
        veto.proxy_report([_scored(fold_id=None)], **kwargs)
    no_champion = _scored(fold_id=1)
    with pytest.raises(veto.NotOutOfFoldError):
        veto.proxy_report([_replace_champion(no_champion, None)], **kwargs)


def _replace_champion(row: msb.ScoredRow, champion: msb.ChampionSpec | None) -> msb.ScoredRow:
    import dataclasses

    return dataclasses.replace(row, champion=champion)


def test_veto_proxy_counts_refused_versus_kept_with_cli_outcomes() -> None:
    rows = [_scored(fold_id=1, mu=70.0), _scored(fold_id=1, mu=60.0, station="LAX", observed=61.0)]
    report = veto.proxy_report(rows, rungs=_LADDER, reference_ask=_const_reference(0.15))
    assert report["takes"] > 0
    assert report["refused"] + report["kept"] == report["takes"]
    assert 0.0 <= report["refusal_rate"] <= 1.0
    assert report["refused"] > 0  # the LAX blend is far from the champion: it vetoes
    assert set(report["by_station"]) == {"NYC", "LAX"}
    for bucket in (report["outcome_refused"], report["outcome_kept"]):
        assert set(bucket) == {"n", "mean_net_per_contract"}
    assert report["label"] == "descriptive_only_no_verdict"
    assert "verdict" not in report


def test_veto_report_uses_no_market_price_before_2026_08_30() -> None:
    row = _scored(fold_id=1, day=dt.date(2026, 5, 10))
    with pytest.raises(veto.PreTapeMarketPriceError):
        veto.proxy_report([row], rungs=_LADDER, reference_ask=_const_reference(source="market"))
    veto.proxy_report([row], rungs=_LADDER, reference_ask=_const_reference())
    assert veto.TAPE_START == dt.date(2026, 8, 30)
    source = (REPO_ROOT / "scripts" / "analysis" / "blend_veto_descriptive.py").read_text("utf-8")
    for banned in ("pyarrow", "ParquetDataCatalog", "order_book_depths", "quote_tick"):
        assert banned not in source
    with pytest.raises(msb.HoldoutLeakError):
        veto.proxy_report(
            [_scored(fold_id=1, day=dt.date(2026, 9, 2))],
            rungs=_LADDER,
            reference_ask=_const_reference(),
        )


def test_veto_forward_shadow_never_feeds_a_verdict() -> None:
    first_forward = dt.date(2026, 10, 11)
    takes = [
        veto.ForwardTake(
            station="NYC",
            climate_day=dt.date(2026, 10, 12),
            side="yes",
            rung_id="68-69",
            blend_p_yes=0.10,
            champion_p_yes=0.60,
            ask=0.30,
        ),
        veto.ForwardTake(
            station="NYC",
            climate_day=dt.date(2026, 10, 12),
            side="yes",
            rung_id="70-71",
            blend_p_yes=0.62,
            champion_p_yes=0.60,
            ask=0.30,
        ),
    ]
    out = veto.forward_shadow_count(takes, first_forward_day=first_forward)
    assert out["n_takes"] == 2 and out["n_blend_would_refuse"] == 1
    assert out["feeds_verdict"] is False and out["label"] == "scan_day_shadow_count_never_evidence"
    assert not {"verdict", "p_value", "lower_bound", "ci"} & set(out)
    stale = veto.ForwardTake(
        station="NYC",
        climate_day=dt.date(2026, 10, 1),
        side="yes",
        rung_id="68-69",
        blend_p_yes=0.1,
        champion_p_yes=0.6,
        ask=0.3,
    )
    with pytest.raises(veto.PreFreezeDayError):
        veto.forward_shadow_count([stale], first_forward_day=first_forward)


def test_veto_main_refuses_unfrozen_prereg_and_unpinned_reference(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rows = tmp_path / "oof_rows.jsonl"
    rows.write_text("", encoding="utf-8")
    scenario_repo = tmp_path / "repo"
    frozen = _freeze(scenario_repo, _design())
    draft = scenario_repo / "draft.json"
    draft.write_text(json.dumps({**_design(), "frozen_sha": "UNFROZEN"}), encoding="utf-8")
    base = ["--oof-rows", str(rows), "--out", str(tmp_path / "veto.json")]
    assert veto.main(["--prereg", str(draft), *base]) == 2
    err = capsys.readouterr().err
    assert "REFUSED:" in err and "UNFROZEN" in err
    # the reference ask is an unpinned prereg value
    assert veto.main(["--prereg", str(frozen), *base]) == 2
    assert "reference" in capsys.readouterr().err


def test_oof_row_json_round_trips() -> None:
    row = _scored(fold_id=3)
    assert msb.scored_row_from_json(msb.scored_row_to_json(row)) == row
