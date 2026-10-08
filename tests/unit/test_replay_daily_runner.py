"""RED-first tests for `scripts/analysis/replay_daily_runner.py` (AUD-09
plan §6b.3, step 8; AUD-09b amendment §4/§6 "Runner").

Drives the module directly, never the wrapper (base plan step 8), with the
ASOS producer and the driver stubbed as fake subprocesses (`run_subprocess`
dependency injection) and a recording fake `AlertSink` (B19/R-e).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, (REPO_ROOT / "scripts/analysis").as_posix())

import replay_daily_runner as runner

from breezy.adapters.polymarket_us.fees import taker_fee_coefficient_as_of
from breezy.analysis.replay_results import (
    REPLAY_RESULTS_SCHEMA_VERSION,
    REPLAY_VALIDITY,
    ReplayResult,
    append_replay_result,
    read_replay_results,
)
from breezy.analysis.replay_sufficiency import (
    REPLAY_SUFFICIENCY_SCHEMA_VERSION,
    ReplaySufficiency,
    write_replay_sufficiency,
)
from breezy.persistence.scored_trial_store import write_scored_trials
from breezy.settlement.trial_scorer import ScoredTrial

STATION = "SFO"
CLIMATE_DAY = "2026-09-01"
STRATEGY = runner.DEFAULT_STRATEGY
LAG_MINUTES = runner.DEFAULT_LAG_MINUTES


def _row(
    *,
    station: str = STATION,
    climate_day: str = CLIMATE_DAY,
    verdict: str = "SUFFICIENT",
    reason: str = "",
    winner_instance_id: str | None = "5a111bca-0000-0000-0000-000000000000",
    window_complete: bool = True,
    coverage_kind: str = "WHOLE",
    live_instance_count: int = 0,
    winner_first_in_window_ns: int | None = 1_000,
    winner_last_in_window_ns: int | None = 2_000,
    window_start_ns: int = 0,
    window_end_ns: int = 18_000_000_000_000,
) -> ReplaySufficiency:
    return ReplaySufficiency(
        schema_version=REPLAY_SUFFICIENCY_SCHEMA_VERSION,
        station=station,
        climate_day=climate_day,
        verdict=verdict,  # type: ignore[arg-type]
        reason=reason,
        winner_instance_id=winner_instance_id,
        depth_window_minutes=300.0,
        quote_window_minutes=300.0,
        distinct_instruments=4,
        computed_day="2026-09-25",
        window_start_ns=window_start_ns,
        window_end_ns=window_end_ns,
        winner_first_in_window_ns=winner_first_in_window_ns,
        winner_last_in_window_ns=winner_last_in_window_ns,
        window_complete=window_complete,
        live_instance_count=live_instance_count,
        coverage_kind=coverage_kind,
        excluded_fragments=(),
    )


def _terminal_row(
    *,
    station: str = STATION,
    climate_day: str = CLIMATE_DAY,
    strategy: str = STRATEGY,
    lag_minutes: int = LAG_MINUTES,
    outcome: str = "COMPLETED",
    tape_instance_id: str | None = "5a111bca-0000-0000-0000-000000000000",
) -> ReplayResult:
    return ReplayResult(
        schema_version=REPLAY_RESULTS_SCHEMA_VERSION,
        run_ts="2026-09-25T15:50:00+00:00",
        station=station,
        climate_day=climate_day,
        strategy=strategy,
        lag_minutes=lag_minutes,
        outcome=outcome,  # type: ignore[arg-type]
        validity=REPLAY_VALIDITY,
        blocked_reason=None,
        exception_type=None,
        family_id="pm_us_crh_v4",
        manifest_sha256="a" * 64,
        manifest_taker_fee_coefficient="0.0695",
        engine_required_fee_coefficient="0.0695",
        engine_params_source="FAMILY_MANIFEST",
        params_match=True,
        composition_kind="continuous_rung_hold",
        tape_instance_id=tape_instance_id,
        sufficiency_reason="",
        trials=1,
        fills=1,
        fill_price_vs_decision_ask=("0.01",),
        refusal_counts={},
        wall_s=10.0,
        peak_rss_bytes=1_000,
        parquet_sha256=None,
        window_complete=True,
        replayed_first_ns=1_000,
        replayed_last_ns=2_000,
        census_schema_version=REPLAY_SUFFICIENCY_SCHEMA_VERSION,
    )


def _write_manifest(
    path: Path, *, composition_kind: str = "continuous_rung_hold", family_id: str = "pm_us_crh_v4"
) -> Path:
    """A minimal REGISTERED, pinned manifest fixture -- shape mirrors
    `deploy/families/*.json`, real enough for `load_family_manifest` to
    accept it. Review fix 2: composition_kind is the axis under test."""
    path.write_text(
        json.dumps(
            {
                "family_id": family_id,
                "venue": "polymarket_us",
                "trial_id_prefix": "trial/",
                "d0_climate_day": "2026-09-01",
                "boundary_artefact_path": "deploy/families/artefacts/boundary.json",
                "boundary_inputs_sha256": "b" * 64,
                "stations": [STATION],
                "status": "REGISTERED",
                "composition_kind": composition_kind,
                "density_artefact_path": "deploy/families/artefacts/not_applicable_density.json",
                "density_artefact_sha256": "c" * 64,
                "taker_fee_coefficient": "0.0695",
            }
        )
    )
    return path


class _RecordingSink:
    def __init__(self) -> None:
        self.payloads: list[object] = []

    def emit(self, payload: object) -> None:
        self.payloads.append(payload)


class _RaisingSink:
    def emit(self, payload: object) -> None:
        raise RuntimeError("sink is down")


# ---------------------------------------------------------------------------
# R1 target selection
# ---------------------------------------------------------------------------


def test_select_target_is_oldest_first_regardless_of_input_order() -> None:
    rows = [
        _row(station="SFO", climate_day="2026-09-05"),
        _row(station="LAX", climate_day="2026-09-01"),
        _row(station="MIA", climate_day="2026-09-03"),
    ]
    target = runner.select_target(rows=rows, replayed=(), drift=())
    assert target is not None
    assert (target.station, target.climate_day) == ("LAX", "2026-09-01")

    import random

    shuffled = list(rows)
    random.Random(7).shuffle(shuffled)
    target2 = runner.select_target(rows=shuffled, replayed=(), drift=())
    assert target2 is not None
    assert (target2.station, target2.climate_day) == ("LAX", "2026-09-01")


def test_select_target_ties_break_by_supported_stations_order() -> None:
    rows = [
        _row(station="MIA", climate_day=CLIMATE_DAY),
        _row(station="LAX", climate_day=CLIMATE_DAY),
    ]
    target = runner.select_target(rows=rows, replayed=(), drift=())
    assert target is not None
    assert target.station == "LAX"


def test_select_target_never_picks_a_row_with_a_live_instance() -> None:
    rows = [_row(live_instance_count=1)]
    assert runner.select_target(rows=rows, replayed=(), drift=()) is None


def test_select_target_never_picks_a_partial_row() -> None:
    fragment = _row(coverage_kind="FRAGMENT")
    incomplete = _row(station="LAX", window_complete=False)
    assert runner.select_target(rows=[fragment, incomplete], replayed=(), drift=()) is None


def test_select_target_never_picks_an_unsupported_station() -> None:
    rows = [_row(station="NYC")]
    assert runner.select_target(rows=rows, replayed=(), drift=()) is None


def test_select_target_skips_a_key_with_a_terminal_result_row() -> None:
    rows = [_row()]
    replayed = [_terminal_row()]
    assert runner.select_target(rows=rows, replayed=replayed, drift=()) is None


def test_select_target_ignores_family_id_and_reselects_on_lag_change() -> None:
    """B11: the queue key has no family dimension."""
    rows = [_row()]
    # A terminal row exists for lag=30 (the default) -- day is done.
    replayed = [_terminal_row(lag_minutes=LAG_MINUTES)]
    assert runner.select_target(rows=rows, replayed=replayed, drift=()) is None
    # A terminal row for a DIFFERENT lag never blocks lag=30's own selection.
    replayed_other_lag = [_terminal_row(lag_minutes=45)]
    target = runner.select_target(rows=rows, replayed=replayed_other_lag, drift=())
    assert target is not None


def test_select_target_never_picks_a_drifted_key() -> None:
    rows = [_row()]
    drift = [
        runner.DriftRecord(
            schema_version=runner.REPLAY_DRIFT_SCHEMA_VERSION,
            station=STATION,
            climate_day=CLIMATE_DAY,
            strategy=STRATEGY,
            lag_minutes=LAG_MINUTES,
            replayed_tape_instance_id="old",
            new_verdict="INSUFFICIENT_NO_CLEAN_INSTANCE",
            new_winner_instance_id=None,
        )
    ]
    assert runner.select_target(rows=rows, replayed=(), drift=drift) is None


# ---------------------------------------------------------------------------
# Review fix 3 (HIGH): durable wrapper-skip record + escalation
# ---------------------------------------------------------------------------


def test_read_skip_state_of_a_missing_file_is_zero_and_no_reason(tmp_path: Path) -> None:
    assert runner.read_skip_state(tmp_path / "absent") == (0, None)


def test_record_skip_increments_the_same_reason_and_resets_on_a_new_one(tmp_path: Path) -> None:
    path = tmp_path / "wrapper_skip_state"
    sink = _RecordingSink()
    runner.record_skip(skip_state_path=path, reason="LOCK_CONTENTION", sink=sink)
    assert runner.read_skip_state(path) == (1, "LOCK_CONTENTION")
    runner.record_skip(skip_state_path=path, reason="LOCK_CONTENTION", sink=sink)
    assert runner.read_skip_state(path) == (2, "LOCK_CONTENTION")
    runner.record_skip(skip_state_path=path, reason="NO_ARMED_FAMILY", sink=sink)
    assert runner.read_skip_state(path) == (1, "NO_ARMED_FAMILY")
    assert not sink.payloads


def test_record_skip_escalates_on_every_run_once_the_run_reaches_three(tmp_path: Path) -> None:
    path = tmp_path / "wrapper_skip_state"
    sink = _RecordingSink()
    for _ in range(5):
        runner.record_skip(skip_state_path=path, reason="NO_ARMED_FAMILY", sink=sink)
    assert len(sink.payloads) == 3
    for payload in sink.payloads:
        assert payload.event == "BREEZY_REPLAY_SKIPPED_STALLED"  # type: ignore[attr-defined]
        assert payload.severity == "warning"  # type: ignore[attr-defined]


def test_record_skip_never_propagates_a_raising_sink(tmp_path: Path) -> None:
    path = tmp_path / "wrapper_skip_state"
    for _ in range(3):
        runner.record_skip(skip_state_path=path, reason="LOCK_CONTENTION", sink=_RaisingSink())
    assert runner.read_skip_state(path) == (3, "LOCK_CONTENTION")


def test_reset_skip_state_clears_the_counter(tmp_path: Path) -> None:
    path = tmp_path / "wrapper_skip_state"
    runner.record_skip(skip_state_path=path, reason="LOCK_CONTENTION", sink=_RecordingSink())
    runner.reset_skip_state(path)
    assert runner.read_skip_state(path) == (0, None)


def test_run_once_resets_skip_state_on_a_real_attempt(tmp_path: Path) -> None:
    """A run that gets far enough to call `run_once` at all is, by
    definition, no longer a wrapper-level skip -- the streak must not keep
    counting a day whose queue merely happened to be empty."""
    config = _config(tmp_path)
    runner.record_skip(
        skip_state_path=config.skip_state_path, reason="LOCK_CONTENTION", sink=_RecordingSink(),
    )
    assert runner.read_skip_state(config.skip_state_path) == (1, "LOCK_CONTENTION")
    write_replay_sufficiency(config.replay_sufficiency_path, [])
    runner.run_once(config, sink=_RecordingSink())
    assert runner.read_skip_state(config.skip_state_path) == (0, None)


# ---------------------------------------------------------------------------
# record_blocked + B19 stall escalation
# ---------------------------------------------------------------------------


def test_record_blocked_appends_a_row_and_leaves_the_day_queued(tmp_path: Path) -> None:
    path = tmp_path / "replay_results.jsonl"
    sink = _RecordingSink()
    runner.record_blocked(
        results_path=path, station=STATION, climate_day=CLIMATE_DAY, strategy=STRATEGY,
        lag_minutes=LAG_MINUTES, blocked_reason="ASOS_CACHE_EMPTY", sink=sink,
    )
    rows = read_replay_results(path)
    assert len(rows) == 1
    assert rows[0].outcome == "BLOCKED"
    assert rows[0].blocked_reason == "ASOS_CACHE_EMPTY"
    assert not sink.payloads


def test_stall_alert_fires_on_every_run_once_the_run_reaches_three(
    tmp_path: Path,
) -> None:
    """Review fix 5 (MEDIUM): firing only at `n == 3` loses the alert
    forever if that one send fails (fix for the sink-failure case is
    covered separately by `test_a_raising_sink_never_propagates`, but a
    TRANSIENT delivery failure at exactly n==3 must not silence every
    later run too). Firing on every run while the trailing BLOCKED run is
    `>= 3` is self-healing: the very next daily run tries again. The timer
    is daily, so this is at most one alert per day."""
    path = tmp_path / "replay_results.jsonl"
    sink = _RecordingSink()
    for _ in range(5):
        runner.record_blocked(
            results_path=path, station=STATION, climate_day=CLIMATE_DAY, strategy=STRATEGY,
            lag_minutes=LAG_MINUTES, blocked_reason="ASOS_CACHE_EMPTY", sink=sink,
        )
    # Runs 1-2: no alert. Runs 3, 4, 5 (run length 3, 4, 5): one alert each.
    assert len(sink.payloads) == 3
    for payload in sink.payloads:
        assert payload.event == "BREEZY_REPLAY_STALLED"  # type: ignore[attr-defined]
        assert "/" not in payload.detail  # type: ignore[attr-defined]


def test_stall_run_does_not_reset_on_a_different_blocked_reason(tmp_path: Path) -> None:
    """Review fix 4 (MEDIUM-HIGH): the stall is "the schedule has stopped
    replaying", not "the schedule keeps hitting the SAME reason" -- two
    BLOCKED rows for reason A followed by one for reason B is still three
    consecutive BLOCKED rows and must count toward the run."""
    path = tmp_path / "replay_results.jsonl"
    sink = _RecordingSink()
    for _ in range(2):
        runner.record_blocked(
            results_path=path, station=STATION, climate_day=CLIMATE_DAY, strategy=STRATEGY,
            lag_minutes=LAG_MINUTES, blocked_reason="ASOS_CACHE_EMPTY", sink=sink,
        )
    runner.record_blocked(
        results_path=path, station=STATION, climate_day=CLIMATE_DAY, strategy=STRATEGY,
        lag_minutes=LAG_MINUTES, blocked_reason="ASOS_PRODUCER_FAILED", sink=sink,
    )
    assert len(sink.payloads) == 1


def test_stall_run_length_counts_blocked_rows_regardless_of_reason() -> None:
    path_rows = [
        ReplayResult(
            schema_version=REPLAY_RESULTS_SCHEMA_VERSION, run_ts="t", station=STATION,
            climate_day=CLIMATE_DAY, strategy=STRATEGY, lag_minutes=LAG_MINUTES,
            outcome="BLOCKED", validity=REPLAY_VALIDITY, blocked_reason=reason,
            exception_type=None, family_id=None, manifest_sha256=None,
            manifest_taker_fee_coefficient=None, engine_required_fee_coefficient=None,
            engine_params_source=None, params_match=None, composition_kind=None,
            tape_instance_id=None, sufficiency_reason="", trials=0, fills=0,
            fill_price_vs_decision_ask=(), refusal_counts={}, wall_s=None, peak_rss_bytes=None,
            parquet_sha256=None, window_complete=None, replayed_first_ns=None,
            replayed_last_ns=None, census_schema_version=None,
        )
        for reason in ("ASOS_CACHE_EMPTY", "ASOS_PRODUCER_FAILED", "FAMILY_MANIFEST_REFUSED")
    ]
    assert runner.stall_run_length(path_rows) == 3


def test_stall_run_resets_on_a_completed_row(tmp_path: Path) -> None:
    path = tmp_path / "replay_results.jsonl"
    sink = _RecordingSink()
    append_replay_result(path, _terminal_row(outcome="COMPLETED"))
    for _ in range(3):
        runner.record_blocked(
            results_path=path, station=STATION, climate_day=CLIMATE_DAY, strategy=STRATEGY,
            lag_minutes=LAG_MINUTES, blocked_reason="ASOS_CACHE_EMPTY", sink=sink,
        )
    assert len(sink.payloads) == 1


def test_record_blocked_remediation_text_branches_on_the_reason(tmp_path: Path) -> None:
    """Review fix 7 (MEDIUM): the alert detail must not hardcode ASOS
    remediation for a non-ASOS reason (e.g. a family-manifest refusal)."""
    asos_path = tmp_path / "asos.jsonl"
    asos_sink = _RecordingSink()
    for _ in range(3):
        runner.record_blocked(
            results_path=asos_path, station=STATION, climate_day=CLIMATE_DAY, strategy=STRATEGY,
            lag_minutes=LAG_MINUTES, blocked_reason="ASOS_CACHE_EMPTY", sink=asos_sink,
        )
    manifest_path = tmp_path / "manifest.jsonl"
    manifest_sink = _RecordingSink()
    for _ in range(3):
        runner.record_blocked(
            results_path=manifest_path, station=STATION, climate_day=CLIMATE_DAY,
            strategy=STRATEGY, lag_minutes=LAG_MINUTES,
            blocked_reason="FAMILY_MANIFEST_REFUSED", sink=manifest_sink,
        )
    asos_detail = asos_sink.payloads[0].detail  # type: ignore[attr-defined]
    manifest_detail = manifest_sink.payloads[0].detail  # type: ignore[attr-defined]
    assert asos_detail != manifest_detail
    assert "asos" in asos_detail.lower()
    assert "asos" not in manifest_detail.lower()
    assert "manifest" in manifest_detail.lower()


def test_a_raising_sink_never_propagates(tmp_path: Path) -> None:
    path = tmp_path / "replay_results.jsonl"
    sink = _RaisingSink()
    for _ in range(3):
        runner.record_blocked(
            results_path=path, station=STATION, climate_day=CLIMATE_DAY, strategy=STRATEGY,
            lag_minutes=LAG_MINUTES, blocked_reason="ASOS_CACHE_EMPTY", sink=sink,
        )
    assert len(read_replay_results(path)) == 3


# ---------------------------------------------------------------------------
# R4 provenance drift
# ---------------------------------------------------------------------------


def test_compute_drift_flags_a_flipped_verdict() -> None:
    replayed = [_terminal_row(outcome="COMPLETED", tape_instance_id="w1")]
    current = {
        (STATION, CLIMATE_DAY): _row(
            verdict="INSUFFICIENT", reason="NO_CLEAN_INSTANCE", winner_instance_id=None,
        )
    }
    drift = runner.compute_drift(replayed=replayed, census_by_station_day=current)
    assert len(drift) == 1
    assert drift[0].new_verdict == "INSUFFICIENT"


def test_compute_drift_flags_a_changed_winner() -> None:
    replayed = [_terminal_row(outcome="COMPLETED", tape_instance_id="w1")]
    current = {(STATION, CLIMATE_DAY): _row(winner_instance_id="w2")}
    drift = runner.compute_drift(replayed=replayed, census_by_station_day=current)
    assert len(drift) == 1
    assert drift[0].new_winner_instance_id == "w2"


def test_compute_drift_flags_a_missing_row() -> None:
    replayed = [_terminal_row(outcome="COMPLETED", tape_instance_id="w1")]
    drift = runner.compute_drift(replayed=replayed, census_by_station_day={})
    assert len(drift) == 1
    assert drift[0].new_verdict == "MISSING"


def test_compute_drift_is_silent_when_unchanged() -> None:
    replayed = [_terminal_row(outcome="COMPLETED", tape_instance_id="w1")]
    current = {(STATION, CLIMATE_DAY): _row(winner_instance_id="w1")}
    assert runner.compute_drift(replayed=replayed, census_by_station_day=current) == ()


def test_compute_drift_ignores_a_blocked_row() -> None:
    replayed = [
        ReplayResult(
            schema_version=REPLAY_RESULTS_SCHEMA_VERSION, run_ts="t", station=STATION,
            climate_day=CLIMATE_DAY, strategy=STRATEGY, lag_minutes=LAG_MINUTES,
            outcome="BLOCKED", validity=REPLAY_VALIDITY, blocked_reason="ASOS_CACHE_EMPTY",
            exception_type=None, family_id=None, manifest_sha256=None,
            manifest_taker_fee_coefficient=None, engine_required_fee_coefficient=None,
            engine_params_source=None, params_match=None, composition_kind=None,
            tape_instance_id=None, sufficiency_reason="", trials=0, fills=0,
            fill_price_vs_decision_ask=(), refusal_counts={}, wall_s=None, peak_rss_bytes=None,
            parquet_sha256=None, window_complete=None, replayed_first_ns=None,
            replayed_last_ns=None, census_schema_version=None,
        )
    ]
    assert runner.compute_drift(replayed=replayed, census_by_station_day={}) == ()


def test_drift_alerts_once_per_new_key_then_stays_silent(tmp_path: Path) -> None:
    drift_path = tmp_path / "replay_drift.jsonl"
    sink = _RecordingSink()
    current = (
        runner.DriftRecord(
            schema_version=runner.REPLAY_DRIFT_SCHEMA_VERSION, station=STATION,
            climate_day=CLIMATE_DAY, strategy=STRATEGY, lag_minutes=LAG_MINUTES,
            replayed_tape_instance_id="w1", new_verdict="MISSING", new_winner_instance_id=None,
        ),
    )
    previous = runner.read_replay_drift(drift_path)
    runner.emit_new_drift_alerts(previous=previous, current=current, sink=sink)
    runner.write_replay_drift(drift_path, current)
    assert len(sink.payloads) == 1

    previous2 = runner.read_replay_drift(drift_path)
    runner.emit_new_drift_alerts(previous=previous2, current=current, sink=sink)
    assert len(sink.payloads) == 1


# ---------------------------------------------------------------------------
# B17: the argument vector is complete
# ---------------------------------------------------------------------------


def test_driver_argv_contains_every_required_flag_of_the_real_driver() -> None:
    driver_source = (REPO_ROOT / "scripts/analysis/current_rung_hold_paper_replay.py").read_text()
    required_flags = set(
        re.findall(
            r'add_argument\(\s*"(--[a-z0-9-]+)",\s*required=True', driver_source,
        )
    )
    assert required_flags, "the driver's own required=True set must be non-empty"
    argv = runner.build_driver_argv(
        python_executable="python3", station=STATION, climate_day=CLIMATE_DAY,
        tape_instance_id="w1", quote_catalog=Path("/q"), work_catalog=Path("/w"),
        asos_cache_csv=Path("/a.csv"), weather_catalog_root=Path("/wcr"),
        output_dir=Path("/out"), family_manifest_path=Path("/fm.json"),
    )
    present_flags = {token for token in argv if token.startswith("--")}
    missing = required_flags - present_flags
    assert not missing, f"argument vector is missing required flag(s): {missing}"


def test_asos_argv_invokes_the_producer_script() -> None:
    argv = runner.build_asos_argv(
        python_executable="python3", station=STATION, climate_day=CLIMATE_DAY,
        out_path=Path("/tmp/out.csv"),
    )
    assert argv[0] == "python3"
    assert argv[1].endswith("asos_cache_csv.py")
    assert "--station" in argv and STATION in argv


def test_driver_argv_never_passes_strategy_explicitly() -> None:
    """Review fix 2 (HIGH): the driver's own contract
    (`current_rung_hold_paper_replay.py` ~:1376-1383, `resolve_family_
    parameters` ~:461) derives the strategy from `--family-manifest`'s
    `composition_kind`; an explicit `--strategy` that disagrees is REFUSED
    (`FamilyManifestArgumentError` -> exit 2). Passing it hardcoded as
    `continuous_rung_hold` permanently refuses any `current_rung_hold`
    -composition family (e.g. `pm_us_crh_v2`). The runner must never pass
    it at all."""
    argv = runner.build_driver_argv(
        python_executable="python3", station=STATION, climate_day=CLIMATE_DAY,
        tape_instance_id="w1", quote_catalog=Path("/q"), work_catalog=Path("/w"),
        asos_cache_csv=Path("/a.csv"), weather_catalog_root=Path("/wcr"),
        output_dir=Path("/out"), family_manifest_path=Path("/fm.json"),
    )
    assert "--strategy" not in argv


# ---------------------------------------------------------------------------
# Review fix 2: strategy is derived from the manifest's composition_kind
# ---------------------------------------------------------------------------


def test_resolve_strategy_from_manifest_reads_composition_kind(tmp_path: Path) -> None:
    manifest = _write_manifest(tmp_path / "family.json", composition_kind="current_rung_hold")
    assert runner.resolve_strategy_from_manifest(manifest) == "current_rung_hold"


def test_resolve_strategy_from_manifest_refuses_forecast_ladder(tmp_path: Path) -> None:
    manifest = _write_manifest(tmp_path / "family.json", composition_kind="forecast_ladder")
    with pytest.raises(runner.UnsupportedCompositionKindError):
        runner.resolve_strategy_from_manifest(manifest)


# ---------------------------------------------------------------------------
# Review fix 2: classify_driver_failure for both FAMILY_MANIFEST_* codes
# ---------------------------------------------------------------------------


def test_classify_driver_failure_family_manifest_refused() -> None:
    assert runner.classify_driver_failure(returncode=2, stderr="") == (
        "BLOCKED", "FAMILY_MANIFEST_REFUSED",
    )


def test_classify_driver_failure_family_manifest_unusable() -> None:
    assert runner.classify_driver_failure(returncode=3, stderr="") == (
        "BLOCKED", "FAMILY_MANIFEST_UNUSABLE",
    )


def test_classify_driver_failure_falls_back_to_failed_for_other_codes() -> None:
    outcome, reason = runner.classify_driver_failure(
        returncode=1, stderr="ValueError: boom",
    )
    assert outcome == "FAILED"
    assert reason == "ValueError"


# ---------------------------------------------------------------------------
# run_once integration (fake subprocesses)
# ---------------------------------------------------------------------------


def _completed_process(
    returncode: int, *, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _config(tmp_path: Path, *, family_manifest_path: Path | None = None) -> runner.RunConfig:
    manifest_path = family_manifest_path
    if manifest_path is None:
        manifest_path = _write_manifest(tmp_path / "family.json")
    return runner.RunConfig(
        replay_sufficiency_path=tmp_path / "replay_sufficiency.jsonl",
        replay_results_path=tmp_path / "replay_results.jsonl",
        replay_drift_path=tmp_path / "replay_drift.jsonl",
        quote_catalog=tmp_path / "quote_catalog",
        weather_catalog_root=tmp_path / "weather_catalog",
        family_manifest_path=manifest_path,
        output_root=tmp_path / "out",
        python_executable=sys.executable,
        skip_state_path=tmp_path / "wrapper_skip_state",
    )


def test_run_once_reports_empty_queue_when_every_day_is_already_replayed(tmp_path: Path) -> None:
    config = _config(tmp_path)
    write_replay_sufficiency(config.replay_sufficiency_path, [_row()])
    append_replay_result(config.replay_results_path, _terminal_row())
    exit_code = runner.run_once(config, sink=_RecordingSink())
    assert exit_code == 0


def test_run_once_reports_every_day_insufficient(tmp_path: Path) -> None:
    config = _config(tmp_path)
    write_replay_sufficiency(
        config.replay_sufficiency_path,
        [_row(verdict="INSUFFICIENT", reason="NO_CLEAN_INSTANCE", winner_instance_id=None)],
    )
    exit_code = runner.run_once(config, sink=_RecordingSink())
    assert exit_code == 0
    if config.replay_results_path.exists():
        assert read_replay_results(config.replay_results_path) == ()


def test_run_once_refuses_an_unreadable_sufficiency_file_rather_than_reporting_empty(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    config.replay_sufficiency_path.parent.mkdir(parents=True, exist_ok=True)
    config.replay_sufficiency_path.write_text('{"schema_version": 999}\n')
    exit_code = runner.run_once(config, sink=_RecordingSink())
    assert exit_code != 0


def test_run_once_blocks_on_asos_cache_empty_and_leaves_the_day_queued(tmp_path: Path) -> None:
    config = _config(tmp_path)
    write_replay_sufficiency(config.replay_sufficiency_path, [_row()])

    def fake_subprocess(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        assert "asos_cache_csv.py" in argv[1]
        return _completed_process(2)

    exit_code = runner.run_once(
        config, run_subprocess=fake_subprocess, sink=_RecordingSink(),
        work_dir_factory=lambda: tmp_path / "work",
    )
    assert exit_code == 0
    rows = read_replay_results(config.replay_results_path)
    assert len(rows) == 1
    assert rows[0].outcome == "BLOCKED"
    assert rows[0].blocked_reason == "ASOS_CACHE_EMPTY"


def test_run_once_recovers_a_parquet_with_no_matching_row(tmp_path: Path) -> None:
    config = _config(tmp_path)
    write_replay_sufficiency(config.replay_sufficiency_path, [_row()])
    output_dir = (
        config.output_root / "paper_replay/scored_trials/v3" / STATION / CLIMATE_DAY
        / f"lag_{LAG_MINUTES}"
    )
    scored = ScoredTrial(
        trial_id="t1", station=STATION, climate_day=CLIMATE_DAY, instrument_id="i1",
        settlement_tmax_f=70, held=True, pnl=Decimal("0.5"), revision_seq=1, raw_sha256="x",
        scored_at_ns=1, score_seq=0, settlement_basis="nws_final", excluded_reason=None,
        slippage=Decimal("0.01"), entry_ask=Decimal("0.4"), fill_px=Decimal("0.41"),
        fee=Decimal("0.02"),
    )
    write_scored_trials(output_dir, [scored], now_ns=1)

    def fail_if_called(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        raise AssertionError("no subprocess should run during a recovery")

    exit_code = runner.run_once(
        config, run_subprocess=fail_if_called, sink=_RecordingSink(),
        work_dir_factory=lambda: tmp_path / "work",
    )
    assert exit_code == 0
    rows = read_replay_results(config.replay_results_path)
    assert len(rows) == 1
    assert rows[0].outcome == "RECOVERED"
    assert rows[0].parquet_sha256


def test_run_once_writes_a_completed_row_from_the_sidecar_and_parquet(tmp_path: Path) -> None:
    config = _config(tmp_path)
    write_replay_sufficiency(config.replay_sufficiency_path, [_row()])
    output_dir = (
        config.output_root / "paper_replay/scored_trials/v3" / STATION / CLIMATE_DAY
        / f"lag_{LAG_MINUTES}"
    )

    def fake_subprocess(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        script = argv[1]
        if "asos_cache_csv.py" in script:
            return _completed_process(0)
        assert "current_rung_hold_paper_replay.py" in script
        output_dir.mkdir(parents=True, exist_ok=True)
        scored = ScoredTrial(
            trial_id="t1", station=STATION, climate_day=CLIMATE_DAY, instrument_id="i1",
            settlement_tmax_f=70, held=True, pnl=Decimal("0.5"), revision_seq=1, raw_sha256="x",
            scored_at_ns=1, score_seq=0, settlement_basis="nws_final", excluded_reason=None,
            slippage=Decimal("0.01"), entry_ask=Decimal("0.4"), fill_px=Decimal("0.41"),
            fee=Decimal("0.02"),
        )
        write_scored_trials(output_dir, [scored], now_ns=2)
        (output_dir / "family_params.json").write_text(
            json.dumps(_matching_sidecar(argv)), encoding="utf-8",
        )
        return _completed_process(
            0, stdout="strategy refusals: {'no_decision_window_coverage': 2}\n",
        )

    sink = _RecordingSink()
    exit_code = runner.run_once(
        config, run_subprocess=fake_subprocess, sink=sink,
        work_dir_factory=lambda: tmp_path / "work",
    )
    assert exit_code == 0
    rows = read_replay_results(config.replay_results_path)
    assert len(rows) == 1
    row = rows[0]
    assert row.outcome == "COMPLETED"
    assert row.family_id == "pm_us_crh_v4"
    assert row.manifest_sha256 == "a" * 64
    assert row.params_match is True
    assert row.trials == 1
    assert row.fills == 1
    assert row.fill_price_vs_decision_ask == ("0.01",)
    assert row.refusal_counts == {"no_decision_window_coverage": 2}
    assert row.window_complete is True
    assert row.validity == "MECHANISM_ONLY"
    # Review fix 6: real activity (a trial, or a non-empty refusal
    # histogram) is never flagged suspect.
    assert not any(
        getattr(p, "event", None) == "BREEZY_REPLAY_SUSPECT_ZERO_ACTIVITY" for p in sink.payloads
    )


def test_run_once_withholds_trials_and_fills_on_a_post_freeze_completed_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """R3-VIABILITY r1 §3.4 / r2 delta "R3V-b" item 5: a post-freeze
    (`climate_day > runner.FREEZE_CLIMATE_DAY`) COMPLETED line prints
    `post-freeze: counts withheld` and carries neither `trials=` nor
    `fills=` -- only the stored row (read by `r3_viability.py`) still
    carries the real counts."""
    post_freeze_day = "2026-09-26"
    assert post_freeze_day > runner.FREEZE_CLIMATE_DAY
    config = _config(tmp_path)
    write_replay_sufficiency(config.replay_sufficiency_path, [_row(climate_day=post_freeze_day)])
    output_dir = _output_dir_for(config, post_freeze_day)

    def fake_subprocess(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        script = argv[1]
        if "asos_cache_csv.py" in script:
            return _completed_process(0)
        assert "current_rung_hold_paper_replay.py" in script
        output_dir.mkdir(parents=True, exist_ok=True)
        scored = ScoredTrial(
            trial_id="t1", station=STATION, climate_day=post_freeze_day, instrument_id="i1",
            settlement_tmax_f=70, held=True, pnl=Decimal("0.5"), revision_seq=1, raw_sha256="x",
            scored_at_ns=1, score_seq=0, settlement_basis="nws_final", excluded_reason=None,
            slippage=Decimal("0.01"), entry_ask=Decimal("0.4"), fill_px=Decimal("0.41"),
            fee=Decimal("0.02"),
        )
        write_scored_trials(output_dir, [scored], now_ns=2)
        (output_dir / "family_params.json").write_text(
            json.dumps(_matching_sidecar(argv)), encoding="utf-8",
        )
        return _completed_process(0)

    capsys.readouterr()
    exit_code = runner.run_once(
        config, run_subprocess=fake_subprocess, sink=_RecordingSink(),
        work_dir_factory=lambda: tmp_path / "work",
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "post-freeze: counts withheld" in out
    assert "trials=" not in out
    assert "fills=" not in out
    # The stored row is unaffected -- only the printed line withholds.
    rows = read_replay_results(config.replay_results_path)
    assert len(rows) == 1
    assert rows[0].trials == 1
    assert rows[0].fills == 1


def _append_terminal_row(
    tmp_path: Path,
    *,
    params_match: bool | None,
    aud11_and_aud12_landed: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> ReplayResult:
    config = _config(tmp_path)
    monkeypatch.setattr(runner, "AUD11_AND_AUD12_LANDED", aud11_and_aud12_landed)
    runner._append_terminal(
        config,
        _row(),
        strategy=STRATEGY,
        now_ts=lambda: "2026-09-25T15:50:00+00:00",
        outcome="COMPLETED",
        family_id="pm_us_crh_v4",
        manifest_sha256="a" * 64,
        manifest_taker_fee_coefficient="0.0695",
        engine_required_fee_coefficient="0.0695",
        engine_params_source="FAMILY_MANIFEST",
        params_match=params_match,
        composition_kind="continuous_rung_hold",
        trials=1,
        fills=1,
        fill_price_vs_decision_ask=("0.01",),
        wall_s=10.0,
        peak_rss_bytes=1_000,
    )
    (row,) = read_replay_results(config.replay_results_path)
    return row


def test_append_terminal_keeps_mechanism_only_when_landed_gate_false_even_if_params_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _append_terminal_row(
        tmp_path,
        params_match=True,
        aud11_and_aud12_landed=False,
        monkeypatch=monkeypatch,
    )
    assert row.validity == "MECHANISM_ONLY"


def test_append_terminal_writes_params_verified_when_landed_gate_true_and_params_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _append_terminal_row(
        tmp_path,
        params_match=True,
        aud11_and_aud12_landed=True,
        monkeypatch=monkeypatch,
    )
    assert row.validity == "PARAMS_VERIFIED"


def test_append_terminal_keeps_mechanism_only_when_landed_gate_true_but_params_do_not_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _append_terminal_row(
        tmp_path,
        params_match=False,
        aud11_and_aud12_landed=True,
        monkeypatch=monkeypatch,
    )
    assert row.validity == "MECHANISM_ONLY"


def test_append_terminal_default_gate_preserves_today_terminal_row_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _append_terminal_row(
        tmp_path,
        params_match=True,
        aud11_and_aud12_landed=False,
        monkeypatch=monkeypatch,
    )
    expected = _terminal_row()
    assert json.dumps(row.to_dict(), sort_keys=True) == json.dumps(
        expected.to_dict(), sort_keys=True
    )


def test_run_once_replays_a_current_rung_hold_composition_family_without_a_strategy_flag(
    tmp_path: Path,
) -> None:
    """Review fix 2 (HIGH): a `current_rung_hold`-composition family (e.g.
    `pm_us_crh_v2`) must be replayable -- the pre-fix hardcoded
    `--strategy continuous_rung_hold` would have this refused by the
    driver's own `resolve_family_parameters` conflict check."""
    manifest = _write_manifest(
        tmp_path / "family.json", composition_kind="current_rung_hold", family_id="pm_us_crh_v2",
    )
    config = _config(tmp_path, family_manifest_path=manifest)
    write_replay_sufficiency(config.replay_sufficiency_path, [_row()])
    output_dir = (
        config.output_root / "paper_replay/scored_trials/v3" / STATION / CLIMATE_DAY
        / f"lag_{LAG_MINUTES}"
    )
    captured_driver_argv: list[str] = []

    def fake_subprocess(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        script = argv[1]
        if "asos_cache_csv.py" in script:
            return _completed_process(0)
        captured_driver_argv.extend(argv)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "family_params.json").write_text(
            json.dumps(
                _matching_sidecar(
                    argv,
                    family_id="pm_us_crh_v2",
                    manifest_sha256="d" * 64,
                    manifest_taker_fee_coefficient="0.06",
                    engine_required_fee_coefficient="0.06",
                    composition_kind="current_rung_hold",
                )
            ),
            encoding="utf-8",
        )
        return _completed_process(0)

    sink = _RecordingSink()
    exit_code = runner.run_once(
        config, run_subprocess=fake_subprocess, sink=sink,
        work_dir_factory=lambda: tmp_path / "work",
    )
    assert exit_code == 0
    assert "--strategy" not in captured_driver_argv
    rows = read_replay_results(config.replay_results_path)
    assert len(rows) == 1
    assert rows[0].strategy == "current_rung_hold"
    assert rows[0].composition_kind == "current_rung_hold"
    # Review fix 6 (MEDIUM): trials=0 AND an empty refusal_counts is
    # indistinguishable from a broken engine -- still COMPLETED (a real
    # mechanism outcome), but flagged with a WARN alert.
    assert rows[0].trials == 0
    assert rows[0].refusal_counts == {}
    suspect_alerts = [
        p for p in sink.payloads
        if getattr(p, "event", None) == "BREEZY_REPLAY_SUSPECT_ZERO_ACTIVITY"
    ]
    assert len(suspect_alerts) == 1
    assert suspect_alerts[0].severity == "warning"  # type: ignore[attr-defined]


def test_run_once_marks_a_driver_crash_as_failed_with_the_exception_type(tmp_path: Path) -> None:
    config = _config(tmp_path)
    write_replay_sufficiency(config.replay_sufficiency_path, [_row()])

    def fake_subprocess(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        if "asos_cache_csv.py" in argv[1]:
            return _completed_process(0)
        return _completed_process(
            1,
            stderr=(
                "Traceback (most recent call last):\n"
                "  ...\n"
                "breezy.runtime.paper_replay.NoDecisionWindowCoverageError: no coverage\n"
            ),
        )

    exit_code = runner.run_once(
        config, run_subprocess=fake_subprocess, sink=_RecordingSink(),
        work_dir_factory=lambda: tmp_path / "work",
    )
    assert exit_code == 1
    rows = read_replay_results(config.replay_results_path)
    assert rows[0].outcome == "FAILED"
    assert rows[0].exception_type == "NoDecisionWindowCoverageError"


# ---------------------------------------------------------------------------
# Review fix 3: `main` dispatches `--report-skip` without run_once's own
# required flags
# ---------------------------------------------------------------------------


def test_main_report_skip_dispatches_without_the_run_once_flags(tmp_path: Path) -> None:
    state_path = tmp_path / "wrapper_skip_state"
    exit_code = runner.main(
        ["--report-skip", "LOCK_CONTENTION", "--skip-state-path", str(state_path)]
    )
    assert exit_code == 0
    assert runner.read_skip_state(state_path) == (1, "LOCK_CONTENTION")


def test_main_reset_skip_state_clears_a_lock_contention_streak(tmp_path: Path) -> None:
    """After an FQ composition skip the persisted counter must be 0, or a
    stale LOCK_CONTENTION streak re-pages STALLED on any later collision."""
    state_path = tmp_path / "wrapper_skip_state"
    for _ in range(5):
        runner.main(["--report-skip", "LOCK_CONTENTION", "--skip-state-path", str(state_path)])
    assert runner.read_skip_state(state_path)[0] == 5

    exit_code = runner.main(["--reset-skip-state", "--skip-state-path", str(state_path)])

    assert exit_code == 0
    assert runner.read_skip_state(state_path)[0] == 0


def test_main_requires_the_usual_flags_when_report_skip_is_absent() -> None:
    with pytest.raises(SystemExit):
        runner.main([])


# ---------------------------------------------------------------------------
# AUD-09b amendment fee-regime plan, Phase 1: record_blocked provenance kwargs
# ---------------------------------------------------------------------------


def test_record_blocked_default_kwargs_row_unchanged(tmp_path: Path) -> None:
    """Regression pin: every pre-existing call site (none of which passes
    the new kwargs) still writes a byte-identical row."""
    path = tmp_path / "replay_results.jsonl"
    runner.record_blocked(
        results_path=path, station=STATION, climate_day=CLIMATE_DAY, strategy=STRATEGY,
        lag_minutes=LAG_MINUTES, blocked_reason="ASOS_CACHE_EMPTY", sink=_RecordingSink(),
    )
    row = read_replay_results(path)[0]
    assert row.family_id is None
    assert row.manifest_taker_fee_coefficient is None
    assert row.engine_required_fee_coefficient is None
    assert row.tape_instance_id is None
    assert row.refusal_counts == {}


def test_fee_schedule_mismatch_gets_a_blocked_remediation_entry(tmp_path: Path) -> None:
    path = tmp_path / "replay_results.jsonl"
    sink = _RecordingSink()
    for _ in range(3):
        runner.record_blocked(
            results_path=path, station=STATION, climate_day=CLIMATE_DAY, strategy=STRATEGY,
            lag_minutes=LAG_MINUTES, blocked_reason="FEE_SCHEDULE_MISMATCH", sink=sink,
        )
    assert len(sink.payloads) == 1
    detail = sink.payloads[0].detail  # type: ignore[attr-defined]
    assert "theta" in detail.lower()


# ---------------------------------------------------------------------------
# AUD-09b amendment fee-regime plan, Phase 1: `fee_void_keys` / AC2
# ---------------------------------------------------------------------------


def _fee_mismatch_blocked_row(
    *, manifest_taker_fee_coefficient: str, station: str = STATION, climate_day: str = CLIMATE_DAY,
) -> ReplayResult:
    return ReplayResult(
        schema_version=REPLAY_RESULTS_SCHEMA_VERSION, run_ts="2026-09-25T15:50:00+00:00",
        station=station, climate_day=climate_day, strategy=STRATEGY, lag_minutes=LAG_MINUTES,
        outcome="BLOCKED", validity=REPLAY_VALIDITY, blocked_reason="FEE_SCHEDULE_MISMATCH",
        exception_type=None, family_id="pm_us_crh_v2", manifest_sha256=None,
        manifest_taker_fee_coefficient=manifest_taker_fee_coefficient,
        engine_required_fee_coefficient=manifest_taker_fee_coefficient,
        engine_params_source=None, params_match=None, composition_kind=None,
        tape_instance_id="5a111bca-0000-0000-0000-000000000000", sufficiency_reason="", trials=0,
        fills=0, fill_price_vs_decision_ask=(),
        refusal_counts={"fee_schedule_mismatch": 1, "outside_decision_window": 26_215},
        wall_s=None, peak_rss_bytes=None, parquet_sha256=None, window_complete=None,
        replayed_first_ns=None, replayed_last_ns=None, census_schema_version=None,
    )


def test_select_target_skips_key_with_fee_mismatch_blocked_row_for_same_theta() -> None:
    """Review requirement 1: theta is compared as `Decimal`, never as raw
    strings -- `"0.0700"` and `Decimal("0.07")` are the SAME theta."""
    rows = [_row()]
    blocked = [_fee_mismatch_blocked_row(manifest_taker_fee_coefficient="0.0700")]
    target = runner.select_target(
        rows=rows, replayed=blocked, drift=(), required_fee_coefficient=Decimal("0.07"),
    )
    assert target is None


def test_select_target_reselects_fee_mismatch_key_for_a_different_theta() -> None:
    """A day voided under one family's theta is NOT excluded for another."""
    rows = [_row()]
    blocked = [_fee_mismatch_blocked_row(manifest_taker_fee_coefficient="0.07")]
    target = runner.select_target(
        rows=rows, replayed=blocked, drift=(), required_fee_coefficient=Decimal("0.06"),
    )
    assert target is not None


# ---------------------------------------------------------------------------
# AUD-09b amendment fee-regime plan, Phase 1: `run_once` net (1) + AC5
# ---------------------------------------------------------------------------


def _fake_subprocess_fee_mismatch(
    output_dir: Path, *, trials: int = 0,
) -> Sequence[str]:
    def fake_subprocess(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        script = argv[1]
        if "asos_cache_csv.py" in script:
            return _completed_process(0)
        assert "current_rung_hold_paper_replay.py" in script
        output_dir.mkdir(parents=True, exist_ok=True)
        if trials:
            scored = [
                ScoredTrial(
                    trial_id="t1", station=STATION, climate_day=CLIMATE_DAY, instrument_id="i1",
                    settlement_tmax_f=70, held=True, pnl=Decimal("0.5"), revision_seq=1,
                    raw_sha256="x", scored_at_ns=1, score_seq=0, settlement_basis="nws_final",
                    excluded_reason=None, slippage=Decimal("0.01"), entry_ask=Decimal("0.4"),
                    fill_px=Decimal("0.41"), fee=Decimal("0.02"),
                )
            ]
            write_scored_trials(output_dir, scored, now_ns=2)
        (output_dir / "family_params.json").write_text(
            json.dumps(
                _matching_sidecar(
                    argv,
                    engine_required_fee_coefficient="0.06",
                    params_match=False,
                )
            ),
            encoding="utf-8",
        )
        return _completed_process(
            0,
            stdout=(
                "strategy refusals: {'fee_schedule_mismatch': 1, "
                "'outside_decision_window': 26215}\n"
            ),
        )

    return fake_subprocess  # type: ignore[return-value]


def test_run_once_records_blocked_fee_schedule_mismatch_not_completed(tmp_path: Path) -> None:
    config = _config(tmp_path)
    write_replay_sufficiency(config.replay_sufficiency_path, [_row()])
    output_dir = (
        config.output_root / "paper_replay/scored_trials/v3" / STATION / CLIMATE_DAY
        / f"lag_{LAG_MINUTES}"
    )
    exit_code = runner.run_once(
        config, run_subprocess=_fake_subprocess_fee_mismatch(output_dir), sink=_RecordingSink(),
        work_dir_factory=lambda: tmp_path / "work",
    )
    assert exit_code == 0
    rows = read_replay_results(config.replay_results_path)
    assert len(rows) == 1
    assert rows[0].outcome == "BLOCKED"
    assert rows[0].blocked_reason == "FEE_SCHEDULE_MISMATCH"


def test_fee_mismatch_blocked_row_carries_family_and_theta_provenance(tmp_path: Path) -> None:
    config = _config(tmp_path)
    write_replay_sufficiency(config.replay_sufficiency_path, [_row()])
    output_dir = (
        config.output_root / "paper_replay/scored_trials/v3" / STATION / CLIMATE_DAY
        / f"lag_{LAG_MINUTES}"
    )
    runner.run_once(
        config, run_subprocess=_fake_subprocess_fee_mismatch(output_dir), sink=_RecordingSink(),
        work_dir_factory=lambda: tmp_path / "work",
    )
    row = read_replay_results(config.replay_results_path)[0]
    assert row.family_id == "pm_us_crh_v4"
    assert row.manifest_taker_fee_coefficient == "0.0695"
    assert row.engine_required_fee_coefficient == "0.06"
    assert row.tape_instance_id == "5a111bca-0000-0000-0000-000000000000"
    assert row.refusal_counts == {"fee_schedule_mismatch": 1, "outside_decision_window": 26_215}


def test_fee_mismatch_with_nonzero_trials_still_blocked_and_zeroed(tmp_path: Path) -> None:
    """AC1: a partial day under a latched halt is contaminated -- fails
    closed even when the engine produced trials."""
    config = _config(tmp_path)
    write_replay_sufficiency(config.replay_sufficiency_path, [_row()])
    output_dir = (
        config.output_root / "paper_replay/scored_trials/v3" / STATION / CLIMATE_DAY
        / f"lag_{LAG_MINUTES}"
    )
    runner.run_once(
        config, run_subprocess=_fake_subprocess_fee_mismatch(output_dir, trials=1),
        sink=_RecordingSink(), work_dir_factory=lambda: tmp_path / "work",
    )
    row = read_replay_results(config.replay_results_path)[0]
    assert row.outcome == "BLOCKED"
    assert row.trials == 0
    assert row.fills == 0


def test_fee_mismatch_quarantines_output_dir_and_recovered_never_adopts_it(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    write_replay_sufficiency(config.replay_sufficiency_path, [_row()])
    output_dir = (
        config.output_root / "paper_replay/scored_trials/v3" / STATION / CLIMATE_DAY
        / f"lag_{LAG_MINUTES}"
    )
    runner.run_once(
        config, run_subprocess=_fake_subprocess_fee_mismatch(output_dir, trials=1),
        sink=_RecordingSink(), work_dir_factory=lambda: tmp_path / "work",
    )
    assert not output_dir.exists()
    quarantined = sorted(output_dir.parent.glob(f"{output_dir.name}.fee_void.*"))
    assert len(quarantined) == 1
    assert sorted(quarantined[0].glob("scored_trials_*.parquet"))

    # A second run never sees a RECOVERED parquet under the original path --
    # the day is durably excluded for this SAME family theta instead.
    def _fail_if_called(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        raise AssertionError("no subprocess should run: the day is fee-void-excluded")

    exit_code = runner.run_once(
        config, run_subprocess=_fail_if_called, sink=_RecordingSink(),
        work_dir_factory=lambda: tmp_path / "work",
    )
    assert exit_code == 0
    assert len(read_replay_results(config.replay_results_path)) == 1


def test_fee_mismatch_does_not_reselect_same_day_next_run(tmp_path: Path) -> None:
    config = _config(tmp_path)
    write_replay_sufficiency(config.replay_sufficiency_path, [_row()])
    output_dir = (
        config.output_root / "paper_replay/scored_trials/v3" / STATION / CLIMATE_DAY
        / f"lag_{LAG_MINUTES}"
    )
    runner.run_once(
        config, run_subprocess=_fake_subprocess_fee_mismatch(output_dir), sink=_RecordingSink(),
        work_dir_factory=lambda: tmp_path / "work",
    )
    first_rows = read_replay_results(config.replay_results_path)
    assert len(first_rows) == 1

    def _fail_if_called(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        raise AssertionError("no subprocess should run on the second call")

    exit_code = runner.run_once(
        config, run_subprocess=_fail_if_called, sink=_RecordingSink(),
        work_dir_factory=lambda: tmp_path / "work",
    )
    assert exit_code == 0
    assert read_replay_results(config.replay_results_path) == first_rows


def test_three_consecutive_fee_mismatch_blocked_rows_fire_stall_alert(tmp_path: Path) -> None:
    path = tmp_path / "replay_results.jsonl"
    sink = _RecordingSink()
    for _ in range(3):
        runner.record_blocked(
            results_path=path, station=STATION, climate_day=CLIMATE_DAY, strategy=STRATEGY,
            lag_minutes=LAG_MINUTES, blocked_reason="FEE_SCHEDULE_MISMATCH", sink=sink,
        )
    assert len(sink.payloads) == 1
    assert sink.payloads[0].event == "BREEZY_REPLAY_STALLED"  # type: ignore[attr-defined]



# ---------------------------------------------------------------------------
# AUD-09b amendment fee-regime plan, Phase 1 review requirement 2: legacy
# quarantine migration
# ---------------------------------------------------------------------------


def _write_legacy_fee_void_row(path: Path) -> None:
    base = _terminal_row(outcome="COMPLETED")
    row = ReplayResult(
        schema_version=base.schema_version, run_ts=base.run_ts, station=base.station,
        climate_day=base.climate_day, strategy=base.strategy, lag_minutes=base.lag_minutes,
        outcome=base.outcome, validity=base.validity, blocked_reason=base.blocked_reason,
        exception_type=base.exception_type, family_id=base.family_id,
        manifest_sha256=base.manifest_sha256,
        manifest_taker_fee_coefficient=base.manifest_taker_fee_coefficient,
        engine_required_fee_coefficient=base.engine_required_fee_coefficient,
        engine_params_source=base.engine_params_source, params_match=base.params_match,
        composition_kind=base.composition_kind, tape_instance_id=base.tape_instance_id,
        sufficiency_reason=base.sufficiency_reason, trials=0, fills=0,
        fill_price_vs_decision_ask=(),
        refusal_counts={"fee_schedule_mismatch": 1, "outside_decision_window": 26_215},
        wall_s=base.wall_s, peak_rss_bytes=base.peak_rss_bytes, parquet_sha256=base.parquet_sha256,
        window_complete=base.window_complete, replayed_first_ns=base.replayed_first_ns,
        replayed_last_ns=base.replayed_last_ns, census_schema_version=base.census_schema_version,
    )
    append_replay_result(path, row)


def test_quarantine_legacy_fee_void_dry_run_lists_without_renaming(tmp_path: Path) -> None:
    results_path = tmp_path / "replay_results.jsonl"
    _write_legacy_fee_void_row(results_path)
    output_dir = (
        tmp_path / "out" / "paper_replay/scored_trials/v3" / STATION / CLIMATE_DAY
        / f"lag_{LAG_MINUTES}"
    )
    output_dir.mkdir(parents=True)
    (output_dir / "scored_trials_1.parquet").write_bytes(b"x")

    reports = runner.quarantine_legacy_fee_void(
        replay_results_path=results_path, output_root=tmp_path / "out", dry_run=True,
    )
    assert len(reports) == 1
    assert reports[0].action == "DRY_RUN"
    assert output_dir.exists()


def test_quarantine_legacy_fee_void_renames_the_output_dir(tmp_path: Path) -> None:
    results_path = tmp_path / "replay_results.jsonl"
    _write_legacy_fee_void_row(results_path)
    output_dir = (
        tmp_path / "out" / "paper_replay/scored_trials/v3" / STATION / CLIMATE_DAY
        / f"lag_{LAG_MINUTES}"
    )
    output_dir.mkdir(parents=True)
    (output_dir / "scored_trials_1.parquet").write_bytes(b"x")

    reports = runner.quarantine_legacy_fee_void(
        replay_results_path=results_path, output_root=tmp_path / "out",
    )
    assert len(reports) == 1
    assert reports[0].action == "QUARANTINED"
    assert not output_dir.exists()
    quarantined = sorted(output_dir.parent.glob(f"{output_dir.name}.fee_void.*"))
    assert len(quarantined) == 1


def test_quarantine_legacy_fee_void_is_idempotent_on_a_second_run(tmp_path: Path) -> None:
    results_path = tmp_path / "replay_results.jsonl"
    _write_legacy_fee_void_row(results_path)
    output_dir = (
        tmp_path / "out" / "paper_replay/scored_trials/v3" / STATION / CLIMATE_DAY
        / f"lag_{LAG_MINUTES}"
    )
    output_dir.mkdir(parents=True)
    (output_dir / "scored_trials_1.parquet").write_bytes(b"x")

    runner.quarantine_legacy_fee_void(
        replay_results_path=results_path, output_root=tmp_path / "out",
    )
    reports = runner.quarantine_legacy_fee_void(
        replay_results_path=results_path, output_root=tmp_path / "out",
    )
    assert len(reports) == 1
    assert reports[0].action == "ALREADY_QUARANTINED_OR_ABSENT"


def test_quarantine_legacy_fee_void_reports_a_missing_directory(tmp_path: Path) -> None:
    results_path = tmp_path / "replay_results.jsonl"
    _write_legacy_fee_void_row(results_path)
    reports = runner.quarantine_legacy_fee_void(
        replay_results_path=results_path, output_root=tmp_path / "out",
    )
    assert len(reports) == 1
    assert reports[0].action == "ALREADY_QUARANTINED_OR_ABSENT"


def test_quarantine_legacy_fee_void_never_rewrites_the_results_file(tmp_path: Path) -> None:
    results_path = tmp_path / "replay_results.jsonl"
    _write_legacy_fee_void_row(results_path)
    before = results_path.read_text()
    runner.quarantine_legacy_fee_void(
        replay_results_path=results_path, output_root=tmp_path / "out",
    )
    assert results_path.read_text() == before

# ---------------------------------------------------------------------------
# AUD-09b amendment fee-regime plan, Phase 2: dated-schedule pre-selection
# ---------------------------------------------------------------------------

_EARLIEST_NS = 1_787_616_000_000_000_000  # 2026-08-25T00:00:00Z
_AMBIGUOUS_START_NS = 1_789_603_200_000_000_000  # 2026-09-17T00:00:00Z
_AMBIGUOUS_END_NS = 1_789_664_400_000_000_000  # 2026-09-17T17:00:00Z
_POST_DRIFT_THETA = Decimal("0.0695")
_PRE_DRIFT_THETA = Decimal("0.06")


def test_select_target_excludes_pre_drift_day_under_post_drift_theta() -> None:
    row = _row(window_start_ns=_EARLIEST_NS, window_end_ns=_EARLIEST_NS + 1_000)
    target = runner.select_target(
        rows=[row], replayed=(), drift=(), required_fee_coefficient=_POST_DRIFT_THETA,
        fee_coefficient_as_of=taker_fee_coefficient_as_of,
    )
    assert target is None


def test_select_target_excludes_day_whose_window_touches_ambiguous_interval() -> None:
    row = _row(window_start_ns=_AMBIGUOUS_START_NS, window_end_ns=_AMBIGUOUS_END_NS)
    target = runner.select_target(
        rows=[row], replayed=(), drift=(), required_fee_coefficient=_POST_DRIFT_THETA,
        fee_coefficient_as_of=taker_fee_coefficient_as_of,
    )
    assert target is None


def test_select_target_excludes_unpinned_day_fail_closed() -> None:
    row = _row(window_start_ns=0, window_end_ns=_EARLIEST_NS - 1)
    target = runner.select_target(
        rows=[row], replayed=(), drift=(), required_fee_coefficient=_PRE_DRIFT_THETA,
        fee_coefficient_as_of=taker_fee_coefficient_as_of,
    )
    assert target is None


def test_select_target_admits_post_drift_day_under_post_drift_theta() -> None:
    row = _row(window_start_ns=_AMBIGUOUS_END_NS, window_end_ns=_AMBIGUOUS_END_NS + 1_000)
    target = runner.select_target(
        rows=[row], replayed=(), drift=(), required_fee_coefficient=_POST_DRIFT_THETA,
        fee_coefficient_as_of=taker_fee_coefficient_as_of,
    )
    assert target is not None


def test_run_once_prints_fee_regime_excluded_count(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    config = _config(tmp_path)
    write_replay_sufficiency(
        config.replay_sufficiency_path,
        [_row(window_start_ns=_EARLIEST_NS, window_end_ns=_EARLIEST_NS + 1_000)],
    )
    capsys.readouterr()
    exit_code = runner.run_once(
        config, sink=_RecordingSink(), fee_coefficient_as_of=taker_fee_coefficient_as_of,
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "FEE_REGIME_EXCLUDED 1" in out


def test_queue_empty_message_distinguishes_fee_regime_exclusion(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    config = _config(tmp_path)
    write_replay_sufficiency(
        config.replay_sufficiency_path,
        [_row(window_start_ns=_EARLIEST_NS, window_end_ns=_EARLIEST_NS + 1_000)],
    )
    capsys.readouterr()
    runner.run_once(
        config, sink=_RecordingSink(), fee_coefficient_as_of=taker_fee_coefficient_as_of,
    )
    out = capsys.readouterr().out
    assert "QUEUE EMPTY (FEE REGIME)" in out
    assert "all replayed under key" not in out


# ---------------------------------------------------------------------------
# AUD-09b amendment fee-regime plan, Phase 3: exit-code parity with the driver
# ---------------------------------------------------------------------------


def test_fee_schedule_mismatch_exit_code_matches_the_drivers_own_constant() -> None:
    import current_rung_hold_paper_replay as driver

    assert runner._EXIT_FEE_SCHEDULE_MISMATCH == driver.EXIT_FEE_SCHEDULE_MISMATCH == 4


def test_classify_driver_failure_fee_schedule_mismatch() -> None:
    assert runner.classify_driver_failure(returncode=4, stderr="") == (
        "BLOCKED", "FEE_SCHEDULE_MISMATCH",
    )


# ---------------------------------------------------------------------------
# AUD-19c: sidecar argv integrity, unclassified driver exits, AUD-09 anchors
# ---------------------------------------------------------------------------

#: Exit-0 provenance refusals (AUD-19 §6 E3). Missing file and a digest that
#: does not match the vector the runner passed are different operator acts,
#: so they are different closed-set reasons — both BLOCKED, both re-queued.
SIDECAR_MISSING_REASON = "FAMILY_PARAMS_SIDECAR_MISSING"
SIDECAR_MISMATCH_REASON = "FAMILY_PARAMS_ARGV_MISMATCH"
SIDECAR_MALFORMED_REASON = "FAMILY_PARAMS_SIDECAR_MALFORMED"

_COMPLETED_ROW_SIDECAR_KEYS = (
    "family_id",
    "manifest_sha256",
    "manifest_taker_fee_coefficient",
    "engine_required_fee_coefficient",
    "engine_params_source",
    "params_match",
    "composition_kind",
)

_FAILED_CLASS_EXCEPTIONS = (
    "NoDecisionWindowCoverageError",
    "EntryAskFromLatchMissingError",
    "ImpossibleFillPriceError",
)

#: AUD-19 A17's sweep, minus `4`. Exit 4 is the later AUD-09b fee-regime
#: preflight (`EXIT_FEE_SCHEDULE_MISMATCH`), already mapped to BLOCKED —
#: reclassifying it as unclassified would retire a fee-void day.
_UNCLASSIFIED_DRIVER_EXITS = (-9, -15, 75, 137, 255)


def _output_dir_for(config: runner.RunConfig, climate_day: str = CLIMATE_DAY) -> Path:
    return (
        config.output_root / "paper_replay/scored_trials/v3" / STATION / climate_day
        / f"lag_{config.lag_minutes}"
    )


def _matching_sidecar(argv: Sequence[str], **overrides: object) -> dict[str, object]:
    """Sidecar whose `argv_sha256` is the driver's own digest of the vector
    after the script path — the slice `main` hashes (`resolved_argv`)."""
    import argv_digest

    payload: dict[str, object] = {
        "family_id": "pm_us_crh_v4",
        "manifest_sha256": "a" * 64,
        "manifest_taker_fee_coefficient": "0.0695",
        "engine_required_fee_coefficient": "0.0695",
        "engine_params_source": "FAMILY_MANIFEST",
        "params_match": True,
        "composition_kind": "continuous_rung_hold",
        "argv_sha256": argv_digest.argv_sha256(list(argv[2:])),
    }
    payload.update(overrides)
    return payload


def _driver_then(
    on_driver: Callable[[Sequence[str]], subprocess.CompletedProcess[str]],
) -> Callable[[Sequence[str]], subprocess.CompletedProcess[str]]:
    def fake(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        if "asos_cache_csv.py" in argv[1]:
            return _completed_process(0)
        assert "current_rung_hold_paper_replay.py" in argv[1]
        return on_driver(argv)

    return fake


def test_the_cited_aud09_anchors_still_exist() -> None:
    """AUD-19c step 22-pre / A16: the anchors 19c cites are still in the
    current AUD-09 plan, and the built runner exposes the symbols 19c calls."""
    plan = REPO_ROOT / "docs/plans/backlog/AUDIT_2026-09-21/AUD-09-scheduled-per-station-replay.md"
    text = plan.read_text(encoding="utf-8")
    anchors = (
        "## 6",
        "## 7",
        "## 8",
        "## 9",
        "§6b.2",
        "§6b.3",
        "engine_params_source",
        "engine_required_fee_coefficient",
        "params_match",
        "COMPLETED",
        "RECOVERED",
        "BLOCKED",
        "FAILED",
        "ASOS_CACHE_EMPTY",
        "B16",
        "B17",
        "B18",
        *_FAILED_CLASS_EXCEPTIONS,
    )
    for anchor in anchors:
        assert anchor in text, f"missing anchor {anchor!r} in {plan}"

    runner_path = REPO_ROOT / "scripts/analysis/replay_daily_runner.py"
    source = runner_path.read_text(encoding="utf-8")
    for symbol in (
        "def record_blocked",
        "def build_driver_argv",
        "from argv_digest import argv_sha256",
    ):
        assert symbol in source, f"missing symbol {symbol!r} in {runner_path}"

    import argv_digest

    assert runner.argv_sha256 is argv_digest.argv_sha256, (
        f"replay_daily_runner.argv_sha256 is not argv_digest.argv_sha256 ({runner_path})"
    )


@pytest.mark.parametrize("case", ["missing", "mismatched"])
def test_a_missing_or_mismatched_sidecar_yields_a_BLOCKED_row(
    tmp_path: Path, case: str,
) -> None:
    """AUD-19 §6 E3 / A14: exit 0 with no sidecar, or a sidecar whose
    `argv_sha256` is not the digest of the vector the runner passed, is
    `BLOCKED` (day stays queued, exit 0) — never a COMPLETED row and never
    `engine_params_source="DRIVER_DEFAULTS"`."""
    config = _config(tmp_path)
    write_replay_sufficiency(config.replay_sufficiency_path, [_row()])
    output_dir = _output_dir_for(config)

    def on_driver(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        if case == "mismatched":
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "family_params.json").write_text(
                json.dumps(_matching_sidecar(argv, argv_sha256="0" * 64)),
                encoding="utf-8",
            )
        return _completed_process(0)

    exit_code = runner.run_once(
        config, run_subprocess=_driver_then(on_driver), sink=_RecordingSink(),
        work_dir_factory=lambda: tmp_path / "work",
    )
    assert exit_code == 0
    before = config.replay_results_path.read_text(encoding="utf-8")
    rows = read_replay_results(config.replay_results_path)
    assert len(rows) == 1
    assert before.count("\n") == 1
    row = rows[0]
    assert row.outcome == "BLOCKED"
    expected_reason = SIDECAR_MISSING_REASON if case == "missing" else SIDECAR_MISMATCH_REASON
    assert row.blocked_reason == expected_reason
    assert row.engine_params_source != "DRIVER_DEFAULTS"
    assert row.params_match is not True

    still_queued = runner.select_target(
        rows=[_row()],
        replayed=rows,
        drift=runner.read_replay_drift(config.replay_drift_path),
        strategy=STRATEGY,
        lag_minutes=LAG_MINUTES,
    )
    assert still_queued is not None
    assert still_queued.climate_day == CLIMATE_DAY

    def on_driver_again(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        if case == "mismatched":
            (output_dir / "family_params.json").write_text(
                json.dumps(_matching_sidecar(argv, argv_sha256="f" * 64)),
                encoding="utf-8",
            )
        return _completed_process(0)

    second = runner.run_once(
        config, run_subprocess=_driver_then(on_driver_again), sink=_RecordingSink(),
        work_dir_factory=lambda: tmp_path / "work",
    )
    assert second == 0
    again = read_replay_results(config.replay_results_path)
    assert len(again) == 2
    assert all(item.outcome == "BLOCKED" for item in again)
    assert all(item.engine_params_source != "DRIVER_DEFAULTS" for item in again)


def _assert_still_queued(config: runner.RunConfig, rows: Sequence[ReplayResult]) -> None:
    still_queued = runner.select_target(
        rows=[_row()],
        replayed=rows,
        drift=runner.read_replay_drift(config.replay_drift_path),
        strategy=STRATEGY,
        lag_minutes=LAG_MINUTES,
    )
    assert still_queued is not None
    assert still_queued.climate_day == CLIMATE_DAY


@pytest.mark.parametrize("missing_key", _COMPLETED_ROW_SIDECAR_KEYS)
def test_a_matching_sidecar_missing_any_completed_row_key_is_BLOCKED_and_still_queued(
    tmp_path: Path, missing_key: str,
) -> None:
    config = _config(tmp_path)
    write_replay_sufficiency(config.replay_sufficiency_path, [_row()])
    output_dir = _output_dir_for(config)

    def on_driver(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        output_dir.mkdir(parents=True, exist_ok=True)
        payload = _matching_sidecar(argv)
        payload.pop(missing_key)
        (output_dir / "family_params.json").write_text(json.dumps(payload), encoding="utf-8")
        return _completed_process(0)

    exit_code = runner.run_once(
        config, run_subprocess=_driver_then(on_driver), sink=_RecordingSink(),
        work_dir_factory=lambda: tmp_path / "work",
    )
    assert exit_code == 0
    rows = read_replay_results(config.replay_results_path)
    assert len(rows) == 1
    row = rows[0]
    assert row.outcome == "BLOCKED"
    assert row.blocked_reason == SIDECAR_MALFORMED_REASON
    assert row.engine_params_source != "DRIVER_DEFAULTS"
    assert row.params_match is not True
    _assert_still_queued(config, rows)


def test_a_matching_sidecar_with_the_wrong_completed_row_key_type_is_BLOCKED(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    write_replay_sufficiency(config.replay_sufficiency_path, [_row()])
    output_dir = _output_dir_for(config)

    def on_driver(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "family_params.json").write_text(
            json.dumps(_matching_sidecar(argv, params_match="true")),
            encoding="utf-8",
        )
        return _completed_process(0)

    exit_code = runner.run_once(
        config, run_subprocess=_driver_then(on_driver), sink=_RecordingSink(),
        work_dir_factory=lambda: tmp_path / "work",
    )
    assert exit_code == 0
    rows = read_replay_results(config.replay_results_path)
    assert len(rows) == 1
    row = rows[0]
    assert row.outcome == "BLOCKED"
    assert row.blocked_reason == SIDECAR_MALFORMED_REASON
    assert row.params_match is not True
    _assert_still_queued(config, rows)


def test_an_unparseable_sidecar_is_BLOCKED_and_still_queued(tmp_path: Path) -> None:
    config = _config(tmp_path)
    write_replay_sufficiency(config.replay_sufficiency_path, [_row()])
    output_dir = _output_dir_for(config)

    def on_driver(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        del argv
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "family_params.json").write_text("{not json", encoding="utf-8")
        return _completed_process(0)

    exit_code = runner.run_once(
        config, run_subprocess=_driver_then(on_driver), sink=_RecordingSink(),
        work_dir_factory=lambda: tmp_path / "work",
    )
    assert exit_code == 0
    rows = read_replay_results(config.replay_results_path)
    assert len(rows) == 1
    row = rows[0]
    assert row.outcome == "BLOCKED"
    assert row.blocked_reason == SIDECAR_MALFORMED_REASON
    assert row.engine_params_source != "DRIVER_DEFAULTS"
    assert row.params_match is not True
    _assert_still_queued(config, rows)


def test_the_runner_and_driver_agree_on_argv_sha256(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A15: the runner verifies the sidecar with `argv_digest.argv_sha256`
    over the arguments after the script path (the driver's `resolved_argv`),
    not a second digest. A reordered vector does not match."""
    import argv_digest

    seen: list[tuple[str, ...]] = []
    real = argv_digest.argv_sha256

    def spy(argv: Sequence[str]) -> str:
        seen.append(tuple(argv))
        return real(argv)

    monkeypatch.setattr(runner, "argv_sha256", spy)

    config = _config(tmp_path)
    write_replay_sufficiency(config.replay_sufficiency_path, [_row()])
    output_dir = _output_dir_for(config)
    captured: list[str] = []

    def on_driver(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        captured.extend(argv)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "family_params.json").write_text(
            json.dumps(_matching_sidecar(argv)), encoding="utf-8",
        )
        return _completed_process(0, stdout="strategy refusals: {'outside_decision_window': 1}\n")

    exit_code = runner.run_once(
        config, run_subprocess=_driver_then(on_driver), sink=_RecordingSink(),
        work_dir_factory=lambda: tmp_path / "work",
    )
    assert exit_code == 0
    assert seen, "runner never called argv_sha256"
    assert seen[0] == tuple(captured[2:])
    assert real(captured[2:]) == real(list(seen[0]))
    reordered = list(captured[2:])
    reordered[0], reordered[1] = reordered[1], reordered[0]
    assert real(reordered) != real(captured[2:])
    row = read_replay_results(config.replay_results_path)[0]
    assert row.outcome == "COMPLETED"
    assert row.engine_params_source == "FAMILY_MANIFEST"
    assert row.params_match is True


@pytest.mark.parametrize("returncode", _UNCLASSIFIED_DRIVER_EXITS)
def test_an_unclassified_driver_exit_appends_one_FAILED_row_and_leaves_the_queue(
    tmp_path: Path, returncode: int,
) -> None:
    """AUD-19 §6 E3 D6 / A14 / A17: a driver exit outside the mapped set
    appends exactly one FAILED row whose exception field is
    `UNCLASSIFIED_DRIVER_EXIT_<returncode>`, exits non-zero, and the day
    leaves the queue. Stderr that looks like a refusal or a FAILED-class
    exception does not change that. Three such crashes do not advance B19."""
    config = _config(tmp_path)
    days = ("2026-09-01", "2026-09-02", "2026-09-03")
    write_replay_sufficiency(
        config.replay_sufficiency_path, [_row(climate_day=day) for day in days],
    )
    sink = _RecordingSink()
    literal = f"UNCLASSIFIED_DRIVER_EXIT_{returncode}"
    refusal_looking_stderr = (
        "FAMILY_MANIFEST_REFUSED\n"
        "Traceback (most recent call last):\n"
        "NoDecisionWindowCoverageError: no coverage\n"
    )

    for index, day in enumerate(days):
        before = (
            config.replay_results_path.read_text(encoding="utf-8")
            if config.replay_results_path.exists()
            else ""
        )

        def on_driver(
            argv: Sequence[str], *, _day: str = day,
        ) -> subprocess.CompletedProcess[str]:
            assert "--climate-day" in argv and _day in argv
            return _completed_process(returncode, stderr=refusal_looking_stderr)

        exit_code = runner.run_once(
            config, run_subprocess=_driver_then(on_driver), sink=sink,
            work_dir_factory=lambda i=index: tmp_path / f"work-{i}",
        )
        assert exit_code != 0
        after = config.replay_results_path.read_text(encoding="utf-8")
        assert after.count("\n") == before.count("\n") + 1

    rows = read_replay_results(config.replay_results_path)
    assert len(rows) == 3
    assert [row.outcome for row in rows] == ["FAILED", "FAILED", "FAILED"]
    assert [row.exception_type for row in rows] == [literal, literal, literal]
    assert all(row.blocked_reason is None for row in rows)
    assert not any(
        getattr(payload, "event", None) == "BREEZY_REPLAY_STALLED" for payload in sink.payloads
    )

    def fail_if_called(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        raise AssertionError(f"day still queued; subprocess invoked: {argv}")

    drained = runner.run_once(
        config, run_subprocess=fail_if_called, sink=sink,
        work_dir_factory=lambda: tmp_path / "work-drained",
    )
    assert drained == 0
    assert len(read_replay_results(config.replay_results_path)) == 3
    assert runner.select_target(
        rows=[_row(climate_day=day) for day in days],
        replayed=read_replay_results(config.replay_results_path),
        drift=runner.read_replay_drift(config.replay_drift_path),
        strategy=STRATEGY,
        lag_minutes=LAG_MINUTES,
    ) is None


@pytest.mark.parametrize("exception_name", _FAILED_CLASS_EXCEPTIONS)
def test_a_failed_class_driver_crash_is_never_classified_as_BLOCKED(
    tmp_path: Path, exception_name: str,
) -> None:
    """AUD-19 §6 E3 / A14: exit 1 carrying one of AUD-09 §9's three
    FAILED-class exceptions is FAILED with that type, and the day leaves
    the queue. Never BLOCKED, never re-queued."""
    config = _config(tmp_path)
    write_replay_sufficiency(config.replay_sufficiency_path, [_row()])

    def on_driver(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return _completed_process(
            1,
            stderr=(
                "Traceback (most recent call last):\n"
                f"breezy.runtime.paper_replay.{exception_name}: defect\n"
            ),
        )

    exit_code = runner.run_once(
        config, run_subprocess=_driver_then(on_driver), sink=_RecordingSink(),
        work_dir_factory=lambda: tmp_path / "work",
    )
    assert exit_code != 0
    rows = read_replay_results(config.replay_results_path)
    assert len(rows) == 1
    assert rows[0].outcome == "FAILED"
    assert rows[0].exception_type == exception_name
    assert rows[0].blocked_reason is None

    def fail_if_called(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        raise AssertionError("FAILED-class day was re-queued")

    drained = runner.run_once(
        config, run_subprocess=fail_if_called, sink=_RecordingSink(),
        work_dir_factory=lambda: tmp_path / "work-2",
    )
    assert drained == 0
    assert len(read_replay_results(config.replay_results_path)) == 1


def test_the_runner_dispatches_on_exit_code_and_never_on_message(tmp_path: Path) -> None:
    """C7/E3: blank stderr, or stderr that names the other class, does not
    move a code. Exit 1 stays FAILED; exit 2/3 stay BLOCKED and queued;
    an unmapped code stays the unclassified literal."""
    cases = (
        (1, "", "FAILED", "UnknownDriverFailure", False),
        (1, "BLOCKED FAMILY_MANIFEST_REFUSED\n", "FAILED", "UnknownDriverFailure", False),
        (
            2,
            "NoDecisionWindowCoverageError: no coverage\n",
            "BLOCKED",
            "FAMILY_MANIFEST_REFUSED",
            True,
        ),
        (3, "", "BLOCKED", "FAMILY_MANIFEST_UNUSABLE", True),
        (
            -9,
            "ImpossibleFillPriceError: too good\n",
            "FAILED",
            "UNCLASSIFIED_DRIVER_EXIT_-9",
            False,
        ),
    )
    for index, (returncode, stderr, outcome, detail, stays_queued) in enumerate(cases):
        day_root = tmp_path / f"case-{index}"
        day_root.mkdir()
        config = _config(day_root)
        write_replay_sufficiency(config.replay_sufficiency_path, [_row()])

        def on_driver(
            argv: Sequence[str], *, _stderr: str = stderr, _rc: int = returncode,
        ) -> subprocess.CompletedProcess[str]:
            return _completed_process(_rc, stderr=_stderr)

        exit_code = runner.run_once(
            config, run_subprocess=_driver_then(on_driver), sink=_RecordingSink(),
            work_dir_factory=lambda root=day_root: root / "work",
        )
        rows = read_replay_results(config.replay_results_path)
        assert len(rows) == 1
        assert rows[0].outcome == outcome
        if outcome == "BLOCKED":
            assert exit_code == 0
            assert rows[0].blocked_reason == detail
        else:
            assert exit_code != 0
            assert rows[0].exception_type == detail
            assert rows[0].blocked_reason is None
        queued = runner.select_target(
            rows=[_row()],
            replayed=rows,
            drift=runner.read_replay_drift(config.replay_drift_path),
            strategy=STRATEGY,
            lag_minutes=LAG_MINUTES,
        )
        assert (queued is not None) is stays_queued
