"""RED-first tests for `scripts/analysis/replay_daily_runner.py` (AUD-09
plan §6b.3, step 8; AUD-09b amendment §4/§6 "Runner").

Drives the module directly, never the wrapper (base plan step 8), with the
ASOS producer and the driver stubbed as fake subprocesses (`run_subprocess`
dependency injection) and a recording fake `AlertSink` (B19/R-e).
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, (REPO_ROOT / "scripts/analysis").as_posix())

import replay_daily_runner as runner

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
        window_start_ns=0,
        window_end_ns=18_000_000_000_000,
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


def test_stall_alert_fires_exactly_once_at_the_third_consecutive_blocked_row(
    tmp_path: Path,
) -> None:
    path = tmp_path / "replay_results.jsonl"
    sink = _RecordingSink()
    for _ in range(4):
        runner.record_blocked(
            results_path=path, station=STATION, climate_day=CLIMATE_DAY, strategy=STRATEGY,
            lag_minutes=LAG_MINUTES, blocked_reason="ASOS_CACHE_EMPTY", sink=sink,
        )
    assert len(sink.payloads) == 1
    payload = sink.payloads[0]
    assert payload.event == "BREEZY_REPLAY_STALLED"  # type: ignore[attr-defined]
    assert "/" not in payload.detail  # type: ignore[attr-defined]


def test_stall_run_resets_on_a_different_blocked_reason(tmp_path: Path) -> None:
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
    for _ in range(2):
        runner.record_blocked(
            results_path=path, station=STATION, climate_day=CLIMATE_DAY, strategy=STRATEGY,
            lag_minutes=LAG_MINUTES, blocked_reason="ASOS_CACHE_EMPTY", sink=sink,
        )
    assert not sink.payloads


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


# ---------------------------------------------------------------------------
# run_once integration (fake subprocesses)
# ---------------------------------------------------------------------------


def _completed_process(
    returncode: int, *, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _config(tmp_path: Path, *, family_manifest_path: Path | None = None) -> runner.RunConfig:
    return runner.RunConfig(
        replay_sufficiency_path=tmp_path / "replay_sufficiency.jsonl",
        replay_results_path=tmp_path / "replay_results.jsonl",
        replay_drift_path=tmp_path / "replay_drift.jsonl",
        quote_catalog=tmp_path / "quote_catalog",
        weather_catalog_root=tmp_path / "weather_catalog",
        family_manifest_path=family_manifest_path or (tmp_path / "family.json"),
        output_root=tmp_path / "out",
        python_executable=sys.executable,
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
            '{"family_id": "pm_us_crh_v4", "manifest_sha256": "'
            + ("a" * 64)
            + '", "manifest_taker_fee_coefficient": "0.0695", '
            '"engine_required_fee_coefficient": "0.0695", '
            '"engine_params_source": "FAMILY_MANIFEST", "params_match": true, '
            '"composition_kind": "continuous_rung_hold"}'
        )
        return _completed_process(
            0, stdout="strategy refusals: {'no_decision_window_coverage': 2}\n",
        )

    exit_code = runner.run_once(
        config, run_subprocess=fake_subprocess, sink=_RecordingSink(),
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
