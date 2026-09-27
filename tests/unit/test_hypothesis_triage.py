"""AUD-18 §7 steps 3–4: hypothesis triage over fake JSONL fixtures.

Every test passes an explicit `--derived-root` under `tmp_path`. None of
them reads or writes `~/.local/share/breezy/derived`.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import textwrap
import time
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, (REPO_ROOT / "scripts" / "analysis").as_posix())

import hypothesis_triage as triage_module
from hypothesis_register import (
    main as register_main,
)
from hypothesis_register import (
    register_forecast_taker_closed_disposition,
)
from hypothesis_triage import (
    AlreadyLookedRefusal,
    DuplicateHypothesisLookError,
    ZeroLookRefusal,
    _Args,
    _has_registered_draw_binding,
    append_hypothesis_evaluation,
    assert_look_permitted,
    cluster_bootstrap_ci,
)
from hypothesis_triage import (
    run as triage_run,
)

from breezy.analysis.hypothesis_ledger import (
    EVIDENCED_FEE_THETA,
    HYPOTHESIS_LEDGER_SCHEMA_VERSION_V2,
    MAX_HYPOTHESES,
    MAX_SINGLE_DAY_LEG_SHARE,
    PROGRAMME_ALPHA,
    STATION_DAY_STATISTIC,
    VARIANCE_BOUND,
    HypothesisLook,
    HypothesisRecord,
    read_hypothesis_ledger,
    recompute_mde,
    register_hypothesis,
    station_day_mean_x,
    write_hypothesis_ledger,
)
from breezy.analysis.replay_results import (
    REPLAY_RESULTS_SCHEMA_VERSION,
    REPLAY_VALIDITY,
    ReplayResult,
    append_replay_result,
)
from breezy.analysis.replay_sufficiency import (
    REPLAY_SUFFICIENCY_SCHEMA_VERSION,
    ReplaySufficiency,
    write_replay_sufficiency,
)
from breezy.persistence.scored_trial_store import write_scored_trials
from breezy.settlement.current_rung_hold_v2 import (
    StratumRow,
    combine_station_day,
)
from breezy.settlement.trial_scorer import ScoredTrial

SCRIPT = REPO_ROOT / "scripts" / "analysis" / "hypothesis_triage.py"
STRATEGY = "fixture"
LAG = 0


def _run(
    derived: Path,
    *extra: str,
    as_of: str = "2026-09-25",
) -> tuple[subprocess.CompletedProcess[str], list[dict[str, str]]]:
    alert_log = derived / "alert-log.jsonl"
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--derived-root",
            str(derived),
            "--as-of",
            as_of,
            "--alert-log",
            str(alert_log),
            *extra,
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    alerts: list[dict[str, str]] = []
    if alert_log.exists():
        for line in alert_log.read_text(encoding="utf-8").splitlines():
            if line.strip():
                alerts.append(json.loads(line))
    return proc, alerts


def _ledger(derived: Path) -> Path:
    return derived / "hypothesis" / "hypothesis_ledger.jsonl"


def _evaluations(derived: Path) -> Path:
    return derived / "hypothesis" / "hypothesis_evaluations.jsonl"


def _looks(derived: Path) -> list[dict[str, object]]:
    path = _evaluations(derived)
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _horizon_alert_state(derived: Path) -> Path:
    return derived / "hypothesis" / "horizon_alerts.json"


def _binding_alert_state(derived: Path) -> Path:
    return derived / "hypothesis" / "missing_stratum_binding_alerts.json"


def _assert_missing_stratum_binding(
    proc: subprocess.CompletedProcess[str],
    alerts: list[dict[str, str]],
    *,
    hypothesis_id: str,
) -> None:
    assert proc.returncode == 0, proc.stderr
    assert len(alerts) == 1
    assert alerts[0]["severity"] == "WARN"
    assert alerts[0]["event"] == "HYPOTHESIS_TRIAGE_MISSING_STRATUM_BINDING"
    assert "MISSING_STRATUM_BINDING" in alerts[0]["detail"]
    assert hypothesis_id in alerts[0]["detail"]
    assert "MISSING_STRATUM_BINDING" in proc.stdout


def _register(
    derived: Path,
    *,
    hypothesis_id: str,
    min_station_days: int,
    registered_at: str = "2026-09-20",
    status: str = "PARKED_INSUFFICIENT_DATA",
    k_variants: int = 1,
    variant_stratum_filters: tuple[str, ...] | None = None,
) -> None:
    per_variant_alpha = (PROGRAMME_ALPHA / MAX_HYPOTHESES) / k_variants
    mde = recompute_mde(
        per_variant_alpha=per_variant_alpha, n_station_days=min_station_days
    )
    record = register_hypothesis(
        hypothesis_id=hypothesis_id,
        hypothesis_class="ARCHIVE_RECAL",
        registered_at=registered_at,
        k_variants=k_variants,
        freeze_commit="abc1234",
        existing_records=(),
        min_station_days=min_station_days,
        max_single_day_leg_share_cap=MAX_SINGLE_DAY_LEG_SHARE,
        mde_at_allocated_alpha=mde,
        mde_plausibility_bound=mde + 1.0,
        power_is_primary_only=True,
        mde_reference_ask=0.30,
        mde_fee_theta=EVIDENCED_FEE_THETA,
        mde_slippage_allowance=0.01,
        mde_variance_bound=VARIANCE_BOUND,
        station_day_statistic=STATION_DAY_STATISTIC,
        order_quantity=1,
        look_policy="SINGLE_LOOK",
    )
    assert record.is_zero_look is False
    if variant_stratum_filters is not None:
        # V2-LOOK-GATE: register_hypothesis now refuses a v2 REGISTERED
        # outcome outright, so a filter-bound v2 record for these triage
        # look-path tests is built directly here from the REGISTERED v1
        # record register_hypothesis already computed -- every alpha/MDE
        # value stays register_hypothesis's own output (V2-LOOK-GATE r2 V-1).
        record = replace(
            record,
            schema_version=HYPOTHESIS_LEDGER_SCHEMA_VERSION_V2,
            variant_stratum_filters=variant_stratum_filters,
        )
    write_hypothesis_ledger(_ledger(derived), (replace(record, status=status),))


def _day(index: int) -> str:
    return (date(2026, 1, 1) + timedelta(days=index)).isoformat()


def _sufficiency(station: str, climate_day: str) -> ReplaySufficiency:
    return ReplaySufficiency(
        schema_version=REPLAY_SUFFICIENCY_SCHEMA_VERSION,
        station=station,
        climate_day=climate_day,
        verdict="SUFFICIENT",
        reason="",
        winner_instance_id="inst",
        depth_window_minutes=60.0,
        quote_window_minutes=60.0,
        distinct_instruments=1,
        computed_day=climate_day,
        window_start_ns=0,
        window_end_ns=1,
        winner_first_in_window_ns=0,
        winner_last_in_window_ns=1,
        window_complete=True,
        live_instance_count=1,
        coverage_kind="WHOLE",
        excluded_fragments=(),
    )


def _result(
    *,
    station: str,
    climate_day: str,
    fills: int,
    validity: str = "CITABLE",
    params_match: bool | None = True,
    outcome: str = "COMPLETED",
) -> ReplayResult:
    return ReplayResult(
        schema_version=REPLAY_RESULTS_SCHEMA_VERSION,
        run_ts="2026-09-25T00:00:00Z",
        station=station,
        climate_day=climate_day,
        strategy=STRATEGY,
        lag_minutes=LAG,
        outcome=outcome,  # type: ignore[arg-type]
        validity=validity,
        blocked_reason=None,
        exception_type=None,
        family_id="fam",
        manifest_sha256="abc",
        manifest_taker_fee_coefficient="0.0695",
        engine_required_fee_coefficient="0.0695",
        engine_params_source="pin",
        params_match=params_match,
        composition_kind="replay",
        tape_instance_id="inst",
        sufficiency_reason="",
        trials=fills,
        fills=fills,
        fill_price_vs_decision_ask=(),
        refusal_counts={},
        wall_s=1.0,
        peak_rss_bytes=1,
        parquet_sha256="def",
        window_complete=True,
        replayed_first_ns=0,
        replayed_last_ns=1,
        census_schema_version=REPLAY_SUFFICIENCY_SCHEMA_VERSION,
    )


def _write_replay(
    derived: Path,
    rows: list[tuple[str, str, int]],
    *,
    validity: str = "CITABLE",
    params_match: bool | None = True,
) -> None:
    sufficiency = [_sufficiency(station, day) for station, day, _fills in rows]
    write_replay_sufficiency(derived / "replay" / "replay_sufficiency.jsonl", sufficiency)
    results = derived / "replay" / "replay_results.jsonl"
    for station, day, fills in rows:
        append_replay_result(
            results,
            _result(
                station=station,
                climate_day=day,
                fills=fills,
                validity=validity,
                params_match=params_match,
            ),
        )


def _append_replay(path: Path, row: ReplayResult) -> None:
    append_replay_result(path, row)


def _trial(
    *,
    trial_id: str,
    station: str,
    climate_day: str,
    instrument_id: str,
    held: bool,
    entry_ask: str,
    fee: str,
) -> ScoredTrial:
    ask = Decimal(entry_ask)
    return ScoredTrial(
        trial_id=trial_id,
        station=station,
        climate_day=climate_day,
        instrument_id=instrument_id,
        settlement_tmax_f=70,
        held=held,
        pnl=Decimal(0),
        revision_seq=1,
        raw_sha256="abc",
        scored_at_ns=1,
        score_seq=0,
        settlement_basis="nws_final",
        excluded_reason=None,
        slippage=Decimal(0),
        entry_ask=ask,
        fill_px=ask,
        fee=Decimal(fee),
    )


def _write_store(derived: Path, trials: list[ScoredTrial]) -> None:
    by_day: dict[tuple[str, str], list[ScoredTrial]] = {}
    for trial in trials:
        by_day.setdefault((trial.station, trial.climate_day), []).append(trial)
    for (station, climate_day), group in by_day.items():
        directory = (
            derived
            / "paper_replay"
            / "scored_trials"
            / "v3"
            / station
            / climate_day
            / f"lag_{LAG}"
        )
        write_scored_trials(directory, group, now_ns=1)


def _winner(station: str, climate_day: str, *, trial_id: str) -> ScoredTrial:
    return _trial(
        trial_id=trial_id,
        station=station,
        climate_day=climate_day,
        instrument_id=f"yes-{climate_day}",
        held=True,
        entry_ask="0.02",
        fee="0",
    )


def _empty_replay_files(derived: Path) -> None:
    write_replay_sufficiency(derived / "replay" / "replay_sufficiency.jsonl", ())
    (derived / "replay").mkdir(parents=True, exist_ok=True)
    (derived / "replay" / "replay_results.jsonl").write_text("", encoding="utf-8")


def _triage_args(derived: Path, *, as_of: str = "2026-09-25") -> _Args:
    return _Args(
        derived_root=derived,
        as_of=as_of,
        horizon_days=21,
        alert_log=None,
        attempt_hypothesis_id=None,
    )


def test_bootstrap_iterations_resolve_tail_for_small_alpha() -> None:
    assert triage_module._bootstrap_iterations_for_alpha(0.00625) == 16000
    assert triage_module._bootstrap_iterations_for_alpha(0.25) == 400


def test_cluster_bootstrap_default_uses_alpha_resolved_iterations() -> None:
    means = tuple(index / 100.0 for index in range(12))

    assert cluster_bootstrap_ci(means, alpha=0.00625, seed=12345) == cluster_bootstrap_ci(
        means,
        alpha=0.00625,
        iterations=16000,
        seed=12345,
    )


def test_cluster_bootstrap_seed_remains_deterministic() -> None:
    means = tuple(index / 100.0 for index in range(12))

    first = cluster_bootstrap_ci(means, alpha=0.00625, seed=20260925)
    second = cluster_bootstrap_ci(means, alpha=0.00625, seed=20260925)

    assert first == second


def test_cluster_bootstrap_small_sample_runtime_sanity() -> None:
    means = tuple(index / 100.0 for index in range(12))

    started = time.perf_counter()
    cluster_bootstrap_ci(means, alpha=0.00625, seed=20260925)

    assert time.perf_counter() - started < 3.0


def _registered_binding() -> tuple[str, ...]:
    return ("station=SFO|hour_lst=10-11|side=YES|composition_kind=taker",)


def _materialized_output_bytes(derived: Path) -> dict[str, bytes]:
    return {
        path.relative_to(derived).as_posix(): path.read_bytes()
        for path in sorted((derived / "hypothesis").rglob("*"))
        if path.is_file()
    }


def test_missing_ledger_is_a_clean_non_alerting_outcome(tmp_path: Path) -> None:
    proc, alerts = _run(tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert alerts == []
    assert "CLEAN" in proc.stdout
    assert not _evaluations(tmp_path).exists()


def test_a_candidate_replay_row_reaches_triage_via_the_named_input_seam(
    tmp_path: Path,
) -> None:
    hypothesis_id = "H-CANDIDATE-SEAM"
    climate_day = _day(0)
    _register(
        tmp_path,
        hypothesis_id=hypothesis_id,
        min_station_days=1,
        variant_stratum_filters=_registered_binding(),
    )
    write_replay_sufficiency(
        tmp_path / "replay" / "replay_sufficiency.jsonl",
        [_sufficiency("SFO", climate_day)],
    )
    champion = tmp_path / "replay" / "replay_results.jsonl"
    champion.parent.mkdir(parents=True, exist_ok=True)
    champion.write_text("", encoding="utf-8")
    candidate = tmp_path / "candidate" / "replay_results.jsonl"
    _append_replay(candidate, _result(station="SFO", climate_day=climate_day, fills=1))
    _write_store(tmp_path, [_winner("SFO", climate_day, trial_id="candidate-winner")])

    assert (
        triage_run(
            _triage_args(tmp_path),
            replay_result_sources=(("candidate-family", candidate),),
        )
        == 0
    )

    looks = _looks(tmp_path)
    assert len(looks) == 1
    assert looks[0]["hypothesis_id"] == hypothesis_id
    assert looks[0]["n_station_days"] == 1
    assert read_hypothesis_ledger(_ledger(tmp_path))[0].status == "PRIMARY_PASSED_PNL_VETO"


def test_triage_with_no_seam_argument_reads_only_replay_results_jsonl_byte_identically(
    tmp_path: Path,
) -> None:
    def fixture(derived: Path) -> Path:
        _register(
            derived,
            hypothesis_id="H-DEFAULT-BYTES",
            min_station_days=2,
            variant_stratum_filters=_registered_binding(),
        )
        champion_day = _day(0)
        candidate_day = _day(1)
        write_replay_sufficiency(
            derived / "replay" / "replay_sufficiency.jsonl",
            [_sufficiency("SFO", champion_day), _sufficiency("SFO", candidate_day)],
        )
        _append_replay(
            derived / "replay" / "replay_results.jsonl",
            _result(station="SFO", climate_day=champion_day, fills=1),
        )
        candidate = derived / "candidate" / "replay_results.jsonl"
        _append_replay(
            candidate,
            _result(station="SFO", climate_day=candidate_day, fills=1),
        )
        _write_store(
            derived,
            [
                _winner("SFO", champion_day, trial_id="champion-winner"),
                _winner("SFO", candidate_day, trial_id="candidate-winner"),
            ],
        )
        return candidate

    default_root = tmp_path / "default"
    explicit_root = tmp_path / "explicit"
    fixture(default_root)
    fixture(explicit_root)

    assert triage_run(_triage_args(default_root)) == 0
    assert (
        triage_run(
            _triage_args(explicit_root),
            replay_result_sources=(
                ("champion", explicit_root / "replay" / "replay_results.jsonl"),
            ),
        )
        == 0
    )

    assert _materialized_output_bytes(default_root) == _materialized_output_bytes(
        explicit_root
    )
    assert read_hypothesis_ledger(_ledger(default_root))[0].status == (
        read_hypothesis_ledger(_ledger(explicit_root))[0].status
    )
    assert _looks(default_root) == _looks(explicit_root) == []


def test_exact_duplicate_replay_rows_across_named_sources_are_deduped(
    tmp_path: Path,
) -> None:
    climate_day = _day(0)
    _register(
        tmp_path,
        hypothesis_id="H-DUPE-EXACT",
        min_station_days=1,
        variant_stratum_filters=_registered_binding(),
    )
    write_replay_sufficiency(
        tmp_path / "replay" / "replay_sufficiency.jsonl",
        [_sufficiency("SFO", climate_day)],
    )
    row = _result(station="SFO", climate_day=climate_day, fills=1)
    first = tmp_path / "candidate-a" / "replay_results.jsonl"
    second = tmp_path / "candidate-b" / "replay_results.jsonl"
    _append_replay(first, row)
    _append_replay(second, row)
    _write_store(tmp_path, [_winner("SFO", climate_day, trial_id="dupe-winner")])

    assert (
        triage_run(
            _triage_args(tmp_path),
            replay_result_sources=(("candidate-a", first), ("candidate-b", second)),
        )
        == 0
    )

    (look,) = _looks(tmp_path)
    assert look["n_station_days"] == 1
    assert look["n_station_days_observed"] == 1


def test_conflicting_duplicate_replay_rows_across_named_sources_raise(
    tmp_path: Path,
) -> None:
    climate_day = _day(0)
    _register(
        tmp_path,
        hypothesis_id="H-DUPE-CONFLICT",
        min_station_days=1,
        variant_stratum_filters=_registered_binding(),
    )
    write_replay_sufficiency(
        tmp_path / "replay" / "replay_sufficiency.jsonl",
        [_sufficiency("SFO", climate_day)],
    )
    first = tmp_path / "candidate-a" / "replay_results.jsonl"
    second = tmp_path / "candidate-b" / "replay_results.jsonl"
    row = _result(station="SFO", climate_day=climate_day, fills=1)
    _append_replay(first, row)
    _append_replay(second, replace(row, fills=2))

    proc, alerts = _run(
        tmp_path,
        "--replay-results-source",
        f"candidate-a={first}",
        "--replay-results-source",
        f"candidate-b={second}",
    )

    assert proc.returncode == 1
    assert len(alerts) == 1
    assert alerts[0]["event"] == "HYPOTHESIS_TRIAGE_FAILED"
    assert "conflicting duplicate replay result" in alerts[0]["detail"]
    assert "candidate-a" in alerts[0]["detail"]
    assert "candidate-b" in alerts[0]["detail"]
    assert _looks(tmp_path) == []


def test_refused_only_ledger_is_a_clean_non_alerting_outcome(tmp_path: Path) -> None:
    register_forecast_taker_closed_disposition(
        path=_ledger(tmp_path), registered_at="2026-09-20", freeze_commit="deadbee"
    )
    per_variant_alpha = PROGRAMME_ALPHA / MAX_HYPOTHESES
    mde = recompute_mde(per_variant_alpha=per_variant_alpha, n_station_days=300)
    underpowered = register_hypothesis(
        hypothesis_id="H-NO-SIDE-UNDERPOWERED",
        hypothesis_class="NO_SIDE_HUNTING",
        registered_at="2026-09-25",
        k_variants=1,
        freeze_commit="abc1234",
        existing_records=read_hypothesis_ledger(_ledger(tmp_path)),
        min_station_days=300,
        max_single_day_leg_share_cap=MAX_SINGLE_DAY_LEG_SHARE,
        mde_at_allocated_alpha=mde,
        mde_plausibility_bound=0.0001,
        power_is_primary_only=True,
        mde_reference_ask=0.30,
        mde_fee_theta=EVIDENCED_FEE_THETA,
        mde_slippage_allowance=0.01,
        mde_variance_bound=VARIANCE_BOUND,
        station_day_statistic=STATION_DAY_STATISTIC,
        order_quantity=1,
        look_policy="SINGLE_LOOK",
    )
    assert underpowered.status == "UNDERPOWERED_NOT_REGISTERED"
    existing = read_hypothesis_ledger(_ledger(tmp_path))
    write_hypothesis_ledger(_ledger(tmp_path), (*existing, underpowered))

    proc, alerts = _run(tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert alerts == []
    assert "CLEAN" in proc.stdout
    assert _looks(tmp_path) == []


def test_under_min_station_days_stays_parked_and_scores_nothing(tmp_path: Path) -> None:
    """Absent stratum binding fails closed before global sufficiency can count."""
    hypothesis_id = "H-UNDER-MIN"
    _register(tmp_path, hypothesis_id=hypothesis_id, min_station_days=20)
    rows = [("SFO", _day(index), 0 if index < 28 else 1) for index in range(40)]
    _write_replay(tmp_path, rows)
    proc, alerts = _run(tmp_path)
    _assert_missing_stratum_binding(proc, alerts, hypothesis_id=hypothesis_id)
    assert _looks(tmp_path) == []
    records = read_hypothesis_ledger(_ledger(tmp_path))
    assert records[0].status == "PARKED_INSUFFICIENT_DATA"
    assert records[0].hypothesis_id == hypothesis_id


def test_mechanism_only_rows_are_never_evaluated(tmp_path: Path) -> None:
    hypothesis_id = "H-MECH"
    _register(tmp_path, hypothesis_id=hypothesis_id, min_station_days=1)
    rows = [("SFO", _day(index), 3) for index in range(6)]
    _write_replay(tmp_path, rows, validity=REPLAY_VALIDITY)
    proc, alerts = _run(tmp_path)
    _assert_missing_stratum_binding(proc, alerts, hypothesis_id=hypothesis_id)
    assert _looks(tmp_path) == []
    assert read_hypothesis_ledger(_ledger(tmp_path))[0].status == "PARKED_INSUFFICIENT_DATA"


def test_params_match_false_is_never_evaluated(tmp_path: Path) -> None:
    hypothesis_id = "H-PARAMS"
    _register(tmp_path, hypothesis_id=hypothesis_id, min_station_days=1)
    rows = [("SFO", _day(index), 3) for index in range(6)]
    _write_replay(tmp_path, rows, params_match=False)
    proc, alerts = _run(tmp_path)
    _assert_missing_stratum_binding(proc, alerts, hypothesis_id=hypothesis_id)
    assert _looks(tmp_path) == []


def test_missing_stratum_binding_skips_with_named_alert_and_no_global_evaluation(
    tmp_path: Path,
) -> None:
    hypothesis_id = "H-MEAN"
    _register(tmp_path, hypothesis_id=hypothesis_id, min_station_days=1)
    climate_day = _day(0)
    _write_replay(tmp_path, [("SFO", climate_day, 2)])
    _write_store(
        tmp_path,
        [
            _trial(
                trial_id="yes-leg",
                station="SFO",
                climate_day=climate_day,
                instrument_id="ya",
                held=True,
                entry_ask="0.20",
                fee="0.01",
            ),
            _trial(
                trial_id="no-leg",
                station="SFO",
                climate_day=climate_day,
                instrument_id="nb^no",
                held=False,
                entry_ask="0.20",
                fee="0.01",
            ),
        ],
    )
    oracle = combine_station_day(
        (
            StratumRow(
                entry_ask=Decimal("0.20"),
                fee=Decimal("0.01"),
                held=True,
                station="SFO",
                side="yes",
                rung="ya",
            ),
            StratumRow(
                entry_ask=Decimal("0.20"),
                fee=Decimal("0.01"),
                held=False,
                station="SFO",
                side="no",
                rung="nb",
            ),
        )
    )
    mean_excess = station_day_mean_x(oracle)
    assert mean_excess != pytest.approx(oracle.x)

    proc, alerts = _run(tmp_path)
    _assert_missing_stratum_binding(proc, alerts, hypothesis_id=hypothesis_id)
    assert _looks(tmp_path) == []
    status = read_hypothesis_ledger(_ledger(tmp_path))[0].status
    assert status == "PARKED_INSUFFICIENT_DATA"
    assert not (tmp_path / "hypothesis" / f"handoff_{hypothesis_id}.json").exists()


def test_zero_take_rows_are_counted_and_not_scored(tmp_path: Path) -> None:
    _register(tmp_path, hypothesis_id="H-ZERO", min_station_days=2)
    rows = [
        ("SFO", _day(0), 0),
        ("SFO", _day(1), 0),
        ("SFO", _day(2), 1),
        ("SFO", _day(3), 1),
    ]
    _write_replay(tmp_path, rows)
    _write_store(
        tmp_path,
        [
            _winner("SFO", _day(2), trial_id="w2"),
            _winner("SFO", _day(3), trial_id="w3"),
        ],
    )
    proc, _alerts = _run(tmp_path)
    _assert_missing_stratum_binding(proc, _alerts, hypothesis_id="H-ZERO")
    assert _looks(tmp_path) == []


def test_pooled_pnl_veto_counterexample_is_not_confirmed(tmp_path: Path) -> None:
    hypothesis_id = "H-VETO"
    _register(tmp_path, hypothesis_id=hypothesis_id, min_station_days=10)
    rows = [("SFO", _day(index), 1) for index in range(9)]
    rows.append(("SFO", _day(9), 100))
    _write_replay(tmp_path, rows)
    trials = [_winner("SFO", _day(index), trial_id=f"w{index}") for index in range(9)]
    trials.extend(
        _trial(
            trial_id=f"loser-{index}",
            station="SFO",
            climate_day=_day(9),
            instrument_id=f"r{index:03d}^no",
            held=False,
            entry_ask="0.98",
            fee="0.011",
        )
        for index in range(100)
    )
    _write_store(tmp_path, trials)
    proc, alerts = _run(tmp_path)
    _assert_missing_stratum_binding(proc, alerts, hypothesis_id=hypothesis_id)
    assert _looks(tmp_path) == []
    assert read_hypothesis_ledger(_ledger(tmp_path))[0].status == "PARKED_INSUFFICIENT_DATA"
    assert not (tmp_path / "hypothesis" / f"handoff_{hypothesis_id}.json").exists()


def test_exhausted_variants_alert_once_and_abandon(tmp_path: Path) -> None:
    hypothesis_id = "H-ABANDON"
    _register(tmp_path, hypothesis_id=hypothesis_id, min_station_days=1)
    climate_day = _day(0)
    _write_replay(tmp_path, [("SFO", climate_day, 1)])
    _write_store(
        tmp_path,
        [
            _trial(
                trial_id="lose",
                station="SFO",
                climate_day=climate_day,
                instrument_id="yes-lose",
                held=False,
                entry_ask="0.30",
                fee="0",
            )
        ],
    )
    proc, alerts = _run(tmp_path)
    _assert_missing_stratum_binding(proc, alerts, hypothesis_id=hypothesis_id)
    assert read_hypothesis_ledger(_ledger(tmp_path))[0].status == "PARKED_INSUFFICIENT_DATA"
    assert _looks(tmp_path) == []
    assert not (tmp_path / "hypothesis" / f"handoff_{hypothesis_id}.json").exists()


def test_parked_past_horizon_emits_one_advisory_without_changing_status(
    tmp_path: Path,
) -> None:
    hypothesis_id = "H-HORIZON"
    _register(
        tmp_path,
        hypothesis_id=hypothesis_id,
        min_station_days=20,
        registered_at="2026-08-01",
    )
    _empty_replay_files(tmp_path)
    proc, alerts = _run(tmp_path, as_of="2026-09-01")
    assert proc.returncode == 0, proc.stderr
    assert len(alerts) == 1
    assert alerts[0]["severity"] == "WARN"
    assert alerts[0]["event"] == "HYPOTHESIS_TRIAGE_HORIZON_STALL"
    assert hypothesis_id in alerts[0]["detail"]
    assert read_hypothesis_ledger(_ledger(tmp_path))[0].status == "PARKED_INSUFFICIENT_DATA"
    assert _looks(tmp_path) == []

    second, second_alerts = _run(tmp_path, as_of="2026-09-02")
    assert second.returncode == 0, second.stderr
    assert len(second_alerts) == 1
    assert [alert["event"] for alert in second_alerts] == [
        "HYPOTHESIS_TRIAGE_HORIZON_STALL"
    ]
    assert _horizon_alert_state(tmp_path).is_file()


def test_missing_horizon_state_reemits_instead_of_suppressing(tmp_path: Path) -> None:
    hypothesis_id = "H-HORIZON-MISSING-STATE"
    _register(
        tmp_path,
        hypothesis_id=hypothesis_id,
        min_station_days=20,
        registered_at="2026-08-01",
    )
    _empty_replay_files(tmp_path)
    first, first_alerts = _run(tmp_path, as_of="2026-09-01")
    assert first.returncode == 0, first.stderr
    assert len(first_alerts) == 1
    _horizon_alert_state(tmp_path).unlink()

    second, second_alerts = _run(tmp_path, as_of="2026-09-02")
    assert second.returncode == 0, second.stderr
    assert [alert["event"] for alert in second_alerts] == [
        "HYPOTHESIS_TRIAGE_HORIZON_STALL",
        "HYPOTHESIS_TRIAGE_HORIZON_STALL",
    ]


def test_corrupt_horizon_state_fails_loud_without_realerting(tmp_path: Path) -> None:
    hypothesis_id = "H-HORIZON-CORRUPT"
    _register(
        tmp_path,
        hypothesis_id=hypothesis_id,
        min_station_days=20,
        registered_at="2026-08-01",
    )
    _empty_replay_files(tmp_path)
    state = _horizon_alert_state(tmp_path)
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text("{not-json\n", encoding="utf-8")

    proc, alerts = _run(tmp_path, as_of="2026-09-01")
    assert proc.returncode != 0
    assert len(alerts) == 1
    assert alerts[0]["severity"] == "CRITICAL"
    assert alerts[0]["event"] == "HYPOTHESIS_TRIAGE_FAILED"
    assert "horizon alert state" in alerts[0]["detail"]
    assert "HYPOTHESIS_TRIAGE_HORIZON_STALL" not in {
        alert["event"] for alert in alerts
    }


def test_second_run_emits_missing_stratum_binding_alert_exactly_once(tmp_path: Path) -> None:
    """AUD-18 triage review HIGH fix: every registered look-taking hypothesis
    fails the fail-closed stratum-binding check (`_has_registered_draw_binding`
    is always `False` today), so without a one-shot state -- mirroring the
    sibling HORIZON_STALL dedupe -- this would page on every single run.
    Two consecutive runs must emit exactly one alert and write no look rows.
    """
    hypothesis_id = "H-ONCE"
    _register(tmp_path, hypothesis_id=hypothesis_id, min_station_days=5)
    rows = [("SFO", _day(index), 1) for index in range(5)]
    _write_replay(tmp_path, rows)
    _write_store(
        tmp_path,
        [_winner("SFO", _day(index), trial_id=f"w{index}") for index in range(5)],
    )
    first, first_alerts = _run(tmp_path)
    _assert_missing_stratum_binding(first, first_alerts, hypothesis_id=hypothesis_id)
    assert read_hypothesis_ledger(_ledger(tmp_path))[0].status == "PARKED_INSUFFICIENT_DATA"
    assert not (tmp_path / "hypothesis" / f"handoff_{hypothesis_id}.json").exists()
    written = [path for path in (tmp_path / "hypothesis").rglob("*") if path.is_file()]
    assert written
    assert all(path.is_relative_to(tmp_path / "hypothesis") for path in written)
    assert _binding_alert_state(tmp_path).is_file()

    second, second_alerts = _run(tmp_path)
    assert second.returncode == 0, second.stderr
    assert len(second_alerts) == 1
    assert [alert["event"] for alert in second_alerts] == [
        "HYPOTHESIS_TRIAGE_MISSING_STRATUM_BINDING"
    ]
    assert len(_looks(tmp_path)) == 0
    assert read_hypothesis_ledger(_ledger(tmp_path))[0].status == "PARKED_INSUFFICIENT_DATA"


def test_missing_binding_and_horizon_stall_alerts_do_not_suppress_each_other(
    tmp_path: Path,
) -> None:
    """The two alert kinds share the one-shot state MECHANISM but must never
    share its KEY SPACE: a hypothesis alerted for MISSING_STRATUM_BINDING
    must still page once for HORIZON_STALL once the horizon is crossed."""
    hypothesis_id = "H-BOTH"
    _register(
        tmp_path,
        hypothesis_id=hypothesis_id,
        min_station_days=1,
        registered_at="2026-09-01",
    )
    climate_day = _day(0)
    _write_replay(tmp_path, [("SFO", climate_day, 1)])
    _write_store(tmp_path, [_winner("SFO", climate_day, trial_id="w0")])

    # Before the horizon: eligible + data present, but no stratum binding.
    first, first_alerts = _run(tmp_path, as_of="2026-09-05")
    assert first.returncode == 0, first.stderr
    assert [alert["event"] for alert in first_alerts] == [
        "HYPOTHESIS_TRIAGE_MISSING_STRATUM_BINDING"
    ]

    # Still before the horizon: the binding alert must not re-fire.
    second, second_alerts = _run(tmp_path, as_of="2026-09-06")
    assert second.returncode == 0, second.stderr
    assert [alert["event"] for alert in second_alerts] == [
        "HYPOTHESIS_TRIAGE_MISSING_STRATUM_BINDING"
    ]

    # Past the horizon: HORIZON_STALL fires too -- the binding alert's own
    # one-shot state must not suppress it, and vice versa.
    third, third_alerts = _run(tmp_path, as_of="2026-10-10")
    assert third.returncode == 0, third.stderr
    assert [alert["event"] for alert in third_alerts] == [
        "HYPOTHESIS_TRIAGE_MISSING_STRATUM_BINDING",
        "HYPOTHESIS_TRIAGE_HORIZON_STALL",
    ]
    assert _binding_alert_state(tmp_path).is_file()
    assert _horizon_alert_state(tmp_path).is_file()


def test_corrupt_missing_stratum_binding_state_fails_loud_without_realerting(
    tmp_path: Path,
) -> None:
    hypothesis_id = "H-BINDING-CORRUPT"
    _register(tmp_path, hypothesis_id=hypothesis_id, min_station_days=1)
    climate_day = _day(0)
    _write_replay(tmp_path, [("SFO", climate_day, 1)])
    _write_store(tmp_path, [_winner("SFO", climate_day, trial_id="w0")])
    state = _binding_alert_state(tmp_path)
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text("{not-json\n", encoding="utf-8")

    proc, alerts = _run(tmp_path)
    assert proc.returncode != 0
    assert len(alerts) == 1
    assert alerts[0]["severity"] == "CRITICAL"
    assert alerts[0]["event"] == "HYPOTHESIS_TRIAGE_FAILED"
    assert "missing stratum binding alert state" in alerts[0]["detail"]
    assert "HYPOTHESIS_TRIAGE_MISSING_STRATUM_BINDING" not in {
        alert["event"] for alert in alerts
    }


def test_duplicate_look_key_is_a_hard_error(tmp_path: Path) -> None:
    look = HypothesisLook(
        hypothesis_id="H-DUP",
        variant_id="v1",
        looked_at="2026-09-25",
        n_station_days=1,
        n_station_days_observed=1,
        n_station_days_with_takes=1,
        take_rate=1.0,
        ci_lower=0.1,
        ci_upper=0.2,
        pooled_net_pnl_per_contract=0.1,
        max_single_day_leg_share=0.2,
        veto_reason="NONE",
        alpha_spent_cumulative=0.0125,
        is_terminal_look=True,
    )
    path = _evaluations(tmp_path)
    append_hypothesis_evaluation(path, look)
    with pytest.raises(DuplicateHypothesisLookError):
        append_hypothesis_evaluation(path, look)
    assert len(_looks(tmp_path)) == 1


def test_look_against_zero_look_record_is_a_hard_refusal(tmp_path: Path) -> None:
    register_forecast_taker_closed_disposition(
        path=_ledger(tmp_path), registered_at="2026-09-20", freeze_commit="deadbee"
    )
    record = read_hypothesis_ledger(_ledger(tmp_path))[0]
    with pytest.raises(ZeroLookRefusal):
        assert_look_permitted(record, (), "v1")
    proc, alerts = _run(
        tmp_path,
        "--attempt-hypothesis-id",
        record.hypothesis_id,
    )
    assert proc.returncode != 0
    assert len(alerts) == 1
    assert alerts[0]["severity"] == "CRITICAL"
    assert _looks(tmp_path) == []


def test_second_evaluation_of_a_variant_is_refused(tmp_path: Path) -> None:
    _register(tmp_path, hypothesis_id="H-REFUSE", min_station_days=1, status="REGISTERED")
    record = read_hypothesis_ledger(_ledger(tmp_path))[0]
    existing = HypothesisLook(
        hypothesis_id=record.hypothesis_id,
        variant_id="v1",
        looked_at="2026-09-20",
        n_station_days=1,
        n_station_days_observed=1,
        n_station_days_with_takes=1,
        take_rate=1.0,
        ci_lower=0.1,
        ci_upper=0.2,
        pooled_net_pnl_per_contract=0.1,
        max_single_day_leg_share=0.2,
        veto_reason="NONE",
        alpha_spent_cumulative=record.per_variant_alpha,
        is_terminal_look=True,
    )
    with pytest.raises(AlreadyLookedRefusal):
        assert_look_permitted(record, (existing,), "v1")


def test_triage_source_loads_no_boundary_artefact() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "load_boundary_artefact" not in text
    assert "gs_boundary_artefact" not in text
    assert "nautilus_trader" not in text


def test_missing_replay_artefact_emits_one_critical_and_exits_nonzero(tmp_path: Path) -> None:
    _register(tmp_path, hypothesis_id="H-MISSING", min_station_days=5)
    proc, alerts = _run(tmp_path)
    assert proc.returncode != 0
    assert len(alerts) == 1
    assert alerts[0]["severity"] == "CRITICAL"
    assert alerts[0]["event"] == "HYPOTHESIS_TRIAGE_FAILED"
    assert _looks(tmp_path) == []
    assert read_hypothesis_ledger(_ledger(tmp_path))[0].status == "PARKED_INSUFFICIENT_DATA"


def test_unknown_ledger_schema_emits_one_critical_and_exits_nonzero(tmp_path: Path) -> None:
    path = _ledger(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"schema_version": 99, "hypothesis_id": "H-BAD"}\n', encoding="utf-8")
    proc, alerts = _run(tmp_path)
    assert proc.returncode != 0
    assert len(alerts) == 1
    assert alerts[0]["severity"] == "CRITICAL"
    assert alerts[0]["event"] == "HYPOTHESIS_TRIAGE_FAILED"
    assert "99" in alerts[0]["detail"]
    assert _looks(tmp_path) == []


def test_triage_clean_on_cli_written_closed_plus_no_side_ledger(tmp_path: Path) -> None:
    """T10 -- characterisation. A ledger written entirely through the
    `hypothesis_register` CLI (CLOSED forecast-taker + NO-SIDE
    UNDERPOWERED_NOT_REGISTERED, both zero-look) triages CLEAN and never
    touches an AUD-09 replay artefact, because `run`'s `look_taking` filter
    (`hypothesis_triage.py`: `[record for record in records if not
    record.is_zero_look]`) excludes both. This fixture deliberately writes no
    replay_sufficiency.jsonl/replay_results.jsonl -- CLEAN never needs them.

    Mutation evidence: flipping the NO-SIDE record's `is_zero_look` to
    `False` on disk (simulating a bug that miscounts it as look-taking) makes
    triage treat it as an active look-taking hypothesis, which then requires
    AUD-09 artefacts this fixture never wrote -- `_load_aud09` raises
    `_TriageFailure("absent AUD-09 artefact")`, `main()` emits exactly one
    CRITICAL `HYPOTHESIS_TRIAGE_FAILED` alert, and the process exits 1. This
    proves CLEAN is not a no-op default the runner falls into unconditionally.
    """
    path = _ledger(tmp_path)
    assert (
        register_main(
            [
                "--derived-root",
                str(tmp_path),
                "--registered-at",
                "2026-09-20",
                "--freeze-commit",
                "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
                "--register-forecast-taker-closed",
            ]
        )
        == 0
    )
    assert (
        register_main(
            [
                "--derived-root",
                str(tmp_path),
                "--registered-at",
                "2026-09-25",
                "--register-underpowered",
                "H-NO-SIDE-2026-09",
            ]
        )
        == 0
    )
    before_bytes = path.read_bytes()

    proc, alerts = _run(tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "CLEAN" in proc.stdout
    assert alerts == []
    assert _looks(tmp_path) == []
    assert not _evaluations(tmp_path).exists()
    assert not (tmp_path / "alert-log.jsonl").exists()
    assert path.read_bytes() == before_bytes

    # Mutation: corrupt the NO-SIDE record's is_zero_look on disk.
    records = [
        json.loads(line) for line in before_bytes.decode("utf-8").splitlines() if line.strip()
    ]
    mutated = [
        {**record, "is_zero_look": False}
        if record["hypothesis_id"] == "H-NO-SIDE-2026-09"
        else record
        for record in records
    ]
    path.write_text(
        "\n".join(json.dumps(record, sort_keys=True) for record in mutated) + "\n",
        encoding="utf-8",
    )

    proc2, alerts2 = _run(tmp_path)
    assert proc2.returncode == 1
    assert len(alerts2) == 1
    assert alerts2[0]["severity"] == "CRITICAL"
    assert alerts2[0]["event"] == "HYPOTHESIS_TRIAGE_FAILED"


# --------------------------------------------------------------------------
# RA-2 (EDGE-5, 2026-09-27): _has_registered_draw_binding real predicate
# --------------------------------------------------------------------------


def test_has_registered_draw_binding_true_for_a_matching_filter() -> None:
    record = register_hypothesis(
        hypothesis_id="H-BINDING-TRUE",
        hypothesis_class="ALL_HOURS",
        registered_at="2026-09-27",
        k_variants=1,
        freeze_commit="abc1234",
        existing_records=(),
        min_station_days=300,
        max_single_day_leg_share_cap=MAX_SINGLE_DAY_LEG_SHARE,
        mde_at_allocated_alpha=recompute_mde(
            per_variant_alpha=PROGRAMME_ALPHA / MAX_HYPOTHESES, n_station_days=300
        ),
        mde_plausibility_bound=0.01,
        power_is_primary_only=True,
        mde_reference_ask=0.30,
        mde_fee_theta=EVIDENCED_FEE_THETA,
        mde_slippage_allowance=0.01,
        mde_variance_bound=VARIANCE_BOUND,
        station_day_statistic=STATION_DAY_STATISTIC,
        order_quantity=1,
        look_policy="SINGLE_LOOK",
        variant_stratum_filters=("station=SFO|hour_lst=10-11|side=YES|composition_kind=taker",),
    )
    # V2-LOOK-GATE: register_hypothesis now refuses a v2 REGISTERED outcome,
    # so this is a real UNDERPOWERED_NOT_REGISTERED v2 record instead --
    # `_has_registered_draw_binding` is status-independent (it only reads
    # `variant_stratum_filters`), so the predicate under test is unaffected.
    assert record.status == "UNDERPOWERED_NOT_REGISTERED"
    assert _has_registered_draw_binding(record, "v1") is True


def test_has_registered_draw_binding_false_and_names_the_missing_variant() -> None:
    # A v1 record: the schema field is entirely absent (empty tuple).
    v1_record = register_hypothesis(
        hypothesis_id="H-BINDING-FALSE-V1",
        hypothesis_class="ALL_HOURS",
        registered_at="2026-09-27",
        k_variants=1,
        freeze_commit="abc1234",
        existing_records=(),
        min_station_days=300,
        max_single_day_leg_share_cap=MAX_SINGLE_DAY_LEG_SHARE,
        mde_at_allocated_alpha=recompute_mde(
            per_variant_alpha=PROGRAMME_ALPHA / MAX_HYPOTHESES, n_station_days=300
        ),
        mde_plausibility_bound=1.0,
        power_is_primary_only=True,
        mde_reference_ask=0.30,
        mde_fee_theta=EVIDENCED_FEE_THETA,
        mde_slippage_allowance=0.01,
        mde_variance_bound=VARIANCE_BOUND,
        station_day_statistic=STATION_DAY_STATISTIC,
        order_quantity=1,
        look_policy="SINGLE_LOOK",
    )
    assert _has_registered_draw_binding(v1_record, "v1") is False

    # A v2 record with 2 variants, both legitimately registered (register_
    # hypothesis validates every entry eagerly -- it never accepts an empty
    # or malformed filter at intake).
    v2_record = register_hypothesis(
        hypothesis_id="H-BINDING-FALSE-V2",
        hypothesis_class="ALL_HOURS",
        registered_at="2026-09-27",
        k_variants=2,
        freeze_commit="abc1234",
        existing_records=(v1_record,),
        min_station_days=300,
        max_single_day_leg_share_cap=MAX_SINGLE_DAY_LEG_SHARE,
        mde_at_allocated_alpha=recompute_mde(
            per_variant_alpha=(PROGRAMME_ALPHA / MAX_HYPOTHESES) / 2, n_station_days=300
        ),
        mde_plausibility_bound=0.01,
        power_is_primary_only=True,
        mde_reference_ask=0.30,
        mde_fee_theta=EVIDENCED_FEE_THETA,
        mde_slippage_allowance=0.01,
        mde_variance_bound=VARIANCE_BOUND,
        station_day_statistic=STATION_DAY_STATISTIC,
        order_quantity=1,
        look_policy="SINGLE_LOOK",
        variant_stratum_filters=(
            "station=SFO|hour_lst=10-11|side=YES|composition_kind=taker",
            "station=MDW|hour_lst=10-11|side=YES|composition_kind=taker",
        ),
    )
    # V2-LOOK-GATE: real UNDERPOWERED_NOT_REGISTERED v2 record (see the v1
    # case above for why the predicate under test is unaffected).
    assert v2_record.status == "UNDERPOWERED_NOT_REGISTERED"
    assert _has_registered_draw_binding(v2_record, "v1") is True
    assert _has_registered_draw_binding(v2_record, "v2") is True

    # `from_dict` (the READ path) only checks variant_stratum_filters is a
    # list of str -- it does not re-parse each entry. A corrupted/incomplete
    # on-disk row (v2's own binding blank) must still fail closed for v2
    # without disturbing v1's real binding -- exercised via `replace`,
    # mirroring what a read of such a row would reconstruct.
    corrupted = replace(
        v2_record,
        variant_stratum_filters=(
            "station=SFO|hour_lst=10-11|side=YES|composition_kind=taker",
            "",
        ),
    )
    assert _has_registered_draw_binding(corrupted, "v1") is True
    assert _has_registered_draw_binding(corrupted, "v2") is False


# --------------------------------------------------------------------------
# LEDGER-V3 (RA-9d per-record horizon + RA-8c re_arm_gating), EDGE-5 2026-09-27
# --------------------------------------------------------------------------

_V3_TEST_FILTER = "station=ALL|hour_lst=ALL|side=ALL|composition_kind=test"


def _v3_horizon_record(
    *, hypothesis_id: str, registered_at: str, horizon_days: int | None
) -> HypothesisRecord:
    """A schema_version=3 record, built directly (not via `register_hypothesis`,
    which refuses any v3 call reaching REGISTERED/PARKED look-taking status
    while `HORIZON_TOLLING_LANDED` is False) -- mirrors the plan's own note
    that "the triage tests build HypothesisRecord directly"."""
    per_variant_alpha = (PROGRAMME_ALPHA / MAX_HYPOTHESES) / 1
    mde = recompute_mde(per_variant_alpha=per_variant_alpha, n_station_days=20)
    return HypothesisRecord(
        schema_version=3,
        hypothesis_id=hypothesis_id,
        hypothesis_class="ARCHIVE_RECAL",
        registered_at=registered_at,
        k_variants=1,
        allocated_alpha=PROGRAMME_ALPHA / MAX_HYPOTHESES,
        per_variant_alpha=per_variant_alpha,
        min_station_days=20,
        max_single_day_leg_share_cap=MAX_SINGLE_DAY_LEG_SHARE,
        mde_at_allocated_alpha=mde,
        mde_plausibility_bound=mde + 1.0,
        power_is_primary_only=True,
        mde_reference_ask=0.30,
        mde_fee_theta=EVIDENCED_FEE_THETA,
        mde_slippage_allowance=0.01,
        mde_variance_bound=VARIANCE_BOUND,
        mde_variance_bound_justification=None,
        station_day_statistic=STATION_DAY_STATISTIC,
        order_quantity=1,
        look_policy="SINGLE_LOOK",
        freeze_commit="abc1234",
        status="PARKED_INSUFFICIENT_DATA",
        is_zero_look=False,
        variant_stratum_filters=(_V3_TEST_FILTER,),
        horizon_days=horizon_days,
        re_arm_gating=False,
    )


def _v3_confirmed_shape_record(
    *, hypothesis_id: str, re_arm_gating: bool, allocated_alpha: float, per_variant_alpha: float
) -> HypothesisRecord:
    """A schema_version=3, non-zero-look record shaped for `_write_handoff`
    (`may_gate_re_arm`) tests -- status is irrelevant to that predicate."""
    return HypothesisRecord(
        schema_version=3,
        hypothesis_id=hypothesis_id,
        hypothesis_class="ARCHIVE_RECAL",
        registered_at="2026-09-01",
        k_variants=1,
        allocated_alpha=allocated_alpha,
        per_variant_alpha=per_variant_alpha,
        min_station_days=1,
        max_single_day_leg_share_cap=MAX_SINGLE_DAY_LEG_SHARE,
        mde_at_allocated_alpha=0.5,
        mde_plausibility_bound=0.5,
        power_is_primary_only=True,
        mde_reference_ask=0.30,
        mde_fee_theta=EVIDENCED_FEE_THETA,
        mde_slippage_allowance=0.01,
        mde_variance_bound=VARIANCE_BOUND,
        mde_variance_bound_justification=None,
        station_day_statistic=STATION_DAY_STATISTIC,
        order_quantity=1,
        look_policy="SINGLE_LOOK",
        freeze_commit="abc1234",
        status="CONFIRMED",
        is_zero_look=False,
        variant_stratum_filters=(_V3_TEST_FILTER,),
        horizon_days=None,
        re_arm_gating=re_arm_gating,
    )


def test_v3_180_day_horizon_does_not_stall_at_day_22(tmp_path: Path) -> None:
    """Regression twin of `test_parked_past_horizon_...` (v1, 21-day default)
    -- a v3 record's own 180-day horizon must not stall at day 31."""
    hypothesis_id = "H-V3-HORIZON-180-OK"
    record = _v3_horizon_record(
        hypothesis_id=hypothesis_id, registered_at="2026-08-01", horizon_days=180
    )
    write_hypothesis_ledger(_ledger(tmp_path), (record,))
    _empty_replay_files(tmp_path)
    proc, alerts = _run(tmp_path, as_of="2026-09-01")
    assert proc.returncode == 0, proc.stderr
    assert alerts == []
    assert read_hypothesis_ledger(_ledger(tmp_path))[0].status == "PARKED_INSUFFICIENT_DATA"


def test_v3_180_day_horizon_stalls_at_day_181(tmp_path: Path) -> None:
    hypothesis_id = "H-V3-HORIZON-180-STALL"
    record = _v3_horizon_record(
        hypothesis_id=hypothesis_id, registered_at="2026-01-01", horizon_days=180
    )
    write_hypothesis_ledger(_ledger(tmp_path), (record,))
    _empty_replay_files(tmp_path)
    as_of = (date(2026, 1, 1) + timedelta(days=181)).isoformat()
    proc, alerts = _run(tmp_path, as_of=as_of)
    assert proc.returncode == 0, proc.stderr
    assert len(alerts) == 1
    assert alerts[0]["event"] == "HYPOTHESIS_TRIAGE_HORIZON_STALL"
    assert "180" in alerts[0]["detail"]


def test_v3_null_horizon_falls_back_to_cli(tmp_path: Path) -> None:
    """A v3 record with `horizon_days=None` behaves exactly like a v1/v2
    record: the CLI default (21 days, `_run` passes no `--horizon-days`)
    applies, and the alert names THAT horizon."""
    hypothesis_id = "H-V3-HORIZON-NULL"
    record = _v3_horizon_record(
        hypothesis_id=hypothesis_id, registered_at="2026-08-01", horizon_days=None
    )
    write_hypothesis_ledger(_ledger(tmp_path), (record,))
    _empty_replay_files(tmp_path)
    proc, alerts = _run(tmp_path, as_of="2026-09-01")
    assert proc.returncode == 0, proc.stderr
    assert len(alerts) == 1
    assert alerts[0]["event"] == "HYPOTHESIS_TRIAGE_HORIZON_STALL"
    assert "21" in alerts[0]["detail"]


def test_handoff_carries_may_gate_re_arm(tmp_path: Path) -> None:
    look = HypothesisLook(
        hypothesis_id="H-HANDOFF-RESEARCH",
        variant_id="v1",
        looked_at="2026-09-25",
        n_station_days=300,
        n_station_days_observed=300,
        n_station_days_with_takes=300,
        take_rate=1.0,
        ci_lower=0.01,
        ci_upper=0.05,
        pooled_net_pnl_per_contract=10.0,
        max_single_day_leg_share=0.1,
        veto_reason="NONE",
        alpha_spent_cumulative=0.0125,
        is_terminal_look=True,
    )
    research_record = _v3_confirmed_shape_record(
        hypothesis_id="H-HANDOFF-RESEARCH",
        re_arm_gating=False,
        allocated_alpha=PROGRAMME_ALPHA / MAX_HYPOTHESES,
        per_variant_alpha=PROGRAMME_ALPHA / MAX_HYPOTHESES,
    )
    triage_module._write_handoff(tmp_path, look, research_record)
    research_payload = json.loads(
        (tmp_path / "hypothesis" / f"handoff_{look.hypothesis_id}.json").read_text()
    )
    assert research_payload["may_gate_re_arm"] is False

    gating_look = replace(look, hypothesis_id="H-HANDOFF-GATING")
    gating_record = _v3_confirmed_shape_record(
        hypothesis_id="H-HANDOFF-GATING",
        re_arm_gating=True,
        allocated_alpha=0.025 / MAX_HYPOTHESES,
        per_variant_alpha=0.025 / MAX_HYPOTHESES,
    )
    triage_module._write_handoff(tmp_path, gating_look, gating_record)
    gating_payload = json.loads(
        (tmp_path / "hypothesis" / f"handoff_{gating_look.hypothesis_id}.json").read_text()
    )
    assert gating_payload["may_gate_re_arm"] is True


def _module_source_files() -> list[Path]:
    """Every non-test `.py` file under `src/` or `scripts/` (R3-4/R3-5 scope)."""
    files: list[Path] = []
    for root_name in ("src", "scripts"):
        files.extend((REPO_ROOT / root_name).rglob("*.py"))
    return [path for path in files if "tests" not in path.parts]


def _imports_hypothesis_record(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and node.module.endswith("hypothesis_ledger")
            and any(alias.name == "HypothesisRecord" for alias in node.names)
        ):
            return True
    return False


def _dataclasses_replace_bypass_offenses(tree: ast.Module) -> list[str]:
    """R3-4 AST barrier, alias-resolving: flags every call form that reaches
    `dataclasses.replace`, regardless of import aliasing --
    `import dataclasses as dc` + `dc.replace(...)`, and
    `from dataclasses import replace as r` + `r(...)` -- not just the literal
    `dataclasses.replace(...)` spelling. Free of false positives on
    `os.replace` or a local helper such as `_replace_status` (neither binds
    an alias to the `dataclasses` module or its `replace` function)."""
    module_aliases: set[str] = set()
    replace_aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "dataclasses":
                    module_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "dataclasses":
            for alias in node.names:
                if alias.name == "replace":
                    replace_aliases.add(alias.asname or alias.name)

    offenses: list[str] = []
    if replace_aliases:
        offenses.append(f"imports `replace` from dataclasses (as {sorted(replace_aliases)!r})")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "replace"
            and isinstance(func.value, ast.Name)
            and func.value.id in module_aliases
        ):
            offenses.append(f"calls {func.value.id}.replace (dataclasses alias)")
        elif isinstance(func, ast.Name) and func.id in replace_aliases:
            offenses.append(f"calls {func.id}(...) (dataclasses.replace alias)")
    return offenses


def test_no_module_importing_hypothesisrecord_uses_dataclasses_replace() -> None:
    """R3-4: only `hypothesis_ledger.py` (the definer) may call
    `dataclasses.replace`/`replace(...)` on a `HypothesisRecord`. Every other
    module that imports `HypothesisRecord` must go through
    `replace_record_status` instead. Must NOT trip on `os.replace` or a local
    name such as `_replace_status`. Alias-resolving (`import dataclasses as
    dc`, `from dataclasses import replace as r`) -- see
    `_dataclasses_replace_bypass_offenses`."""
    offenders: list[str] = []
    for path in _module_source_files():
        if path.name == "hypothesis_ledger.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if not _imports_hypothesis_record(tree):
            continue
        offenders.extend(
            f"{path}: {offense}" for offense in _dataclasses_replace_bypass_offenses(tree)
        )
    assert offenders == []


def test_dataclasses_replace_bypass_scanner_catches_aliased_module_import() -> None:
    """Negative control 1: `import dataclasses as dc` + `dc.replace(...)`."""
    source = textwrap.dedent(
        """
        import dataclasses as dc

        def bad(rec):
            return dc.replace(rec, status="REGISTERED")
        """
    )
    offenses = _dataclasses_replace_bypass_offenses(ast.parse(source))
    assert any("dc.replace" in offense for offense in offenses), offenses


def test_dataclasses_replace_bypass_scanner_catches_aliased_replace_import() -> None:
    """Negative control 2: `from dataclasses import replace as r` + `r(...)`."""
    source = textwrap.dedent(
        """
        from dataclasses import replace as r

        def bad(rec):
            return r(rec, status="REGISTERED")
        """
    )
    offenses = _dataclasses_replace_bypass_offenses(ast.parse(source))
    assert offenses != []
    assert any("r(...)" in offense for offense in offenses), offenses


def test_dataclasses_replace_bypass_scanner_ignores_os_replace_and_local_helper() -> None:
    """Must NOT false-positive on `os.replace` or a `_replace_status`-shaped
    local helper -- neither binds an alias to `dataclasses` or its
    `replace`."""
    source = textwrap.dedent(
        """
        import os

        def _replace_status(rec, status):
            os.replace("a", "b")
            return rec
        """
    )
    assert _dataclasses_replace_bypass_offenses(ast.parse(source)) == []


def test_no_module_other_than_hypothesis_ledger_reads_re_arm_gating_attribute() -> None:
    """R3-5: scope is `src/` and `scripts/` only -- tests may read
    `.re_arm_gating` directly; every non-test consumer must call
    `may_gate_re_arm` instead."""
    offenders: list[str] = []
    for path in _module_source_files():
        if path.name == "hypothesis_ledger.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "re_arm_gating":
                offenders.append(f"{path}:{node.lineno}")
    assert offenders == []
