"""RED-first tests for R3V-a: batch mode for the daily replay runner
(`docs/plans/backlog/RESOLUTION_2026-09-28/R3-VIABILITY_plan_r1_2026-09-28.md`
Sections 3 items 1-3 / 5-6, AS AMENDED by
`R3-VIABILITY_plan_r2_delta_2026-09-28.md` "R3V-a" -- r2 wins).

Mirrors `test_replay_daily_runner.py`'s own idiom (fake `run_subprocess`,
recording fake `AlertSink`) but scoped to the NEW batch surface:
`runner.run_batch`, the `exclude` kwarg on `select_target`/
`_pre_fee_eligible_rows`, and `runner._run_subprocess_with_rss`. Does not
re-test anything `test_replay_daily_runner.py` already covers.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from collections.abc import Callable, Sequence
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, (REPO_ROOT / "scripts/analysis").as_posix())

import replay_daily_runner as runner

from breezy.analysis.replay_results import read_replay_results
from breezy.analysis.replay_sufficiency import (
    REPLAY_SUFFICIENCY_SCHEMA_VERSION,
    ReplaySufficiency,
    write_replay_sufficiency,
)
from breezy.persistence.scored_trial_store import write_scored_trials
from breezy.settlement.trial_scorer import ScoredTrial

STRATEGY = runner.DEFAULT_STRATEGY
LAG_MINUTES = runner.DEFAULT_LAG_MINUTES
STATIONS = ("LAX", "MDW", "MIA", "SFO")
#: Noon UTC -- well outside the protected no-start window `[16:35Z,
#: 01:15Z)` -- so `run_batch` tests never flake on the actual wall-clock
#: time of day (item 3).
_SAFE_NOW_UTC: Callable[[], dt.datetime] = lambda: dt.datetime(2026, 9, 29, 12, 0, tzinfo=dt.UTC)


def _row(
    *,
    station: str,
    climate_day: str,
    verdict: str = "SUFFICIENT",
    winner_instance_id: str | None = "5a111bca-0000-0000-0000-000000000000",
) -> ReplaySufficiency:
    return ReplaySufficiency(
        schema_version=REPLAY_SUFFICIENCY_SCHEMA_VERSION,
        station=station,
        climate_day=climate_day,
        verdict=verdict,  # type: ignore[arg-type]
        reason="",
        winner_instance_id=winner_instance_id,
        depth_window_minutes=300.0,
        quote_window_minutes=300.0,
        distinct_instruments=4,
        computed_day="2026-09-25",
        window_start_ns=0,
        window_end_ns=18_000_000_000_000,
        winner_first_in_window_ns=1_000,
        winner_last_in_window_ns=2_000,
        window_complete=True,
        live_instance_count=0,
        coverage_kind="WHOLE",
        excluded_fragments=(),
    )


def _write_manifest(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "family_id": "pm_us_crh_v4",
                "venue": "polymarket_us",
                "trial_id_prefix": "trial/",
                "d0_climate_day": "2026-09-01",
                "boundary_artefact_path": "deploy/families/artefacts/boundary.json",
                "boundary_inputs_sha256": "b" * 64,
                "stations": list(STATIONS),
                "status": "REGISTERED",
                "composition_kind": "continuous_rung_hold",
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


def _completed_process(
    returncode: int, *, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _config(tmp_path: Path) -> runner.RunConfig:
    return runner.RunConfig(
        replay_sufficiency_path=tmp_path / "replay_sufficiency.jsonl",
        replay_results_path=tmp_path / "replay_results.jsonl",
        replay_drift_path=tmp_path / "replay_drift.jsonl",
        quote_catalog=tmp_path / "quote_catalog",
        weather_catalog_root=tmp_path / "weather_catalog",
        family_manifest_path=_write_manifest(tmp_path / "family.json"),
        output_root=tmp_path / "out",
        python_executable=sys.executable,
        skip_state_path=tmp_path / "wrapper_skip_state",
    )


def _output_dir_for(config: runner.RunConfig, *, station: str, climate_day: str) -> Path:
    return (
        config.output_root / "paper_replay/scored_trials/v3" / station / climate_day
        / f"lag_{config.lag_minutes}"
    )


def _argv_field(argv: Sequence[str], flag: str) -> str:
    return argv[argv.index(flag) + 1]


def _matching_sidecar(argv: Sequence[str]) -> dict[str, object]:
    import argv_digest

    return {
        "family_id": "pm_us_crh_v4",
        "manifest_sha256": "a" * 64,
        "manifest_taker_fee_coefficient": "0.0695",
        "engine_required_fee_coefficient": "0.0695",
        "engine_params_source": "FAMILY_MANIFEST",
        "params_match": True,
        "composition_kind": "continuous_rung_hold",
        "argv_sha256": argv_digest.argv_sha256(list(argv[2:])),
    }


def _happy_driver(
    config: runner.RunConfig, argv: Sequence[str],
) -> subprocess.CompletedProcess[str]:
    """Writes one scored trial + a matching sidecar for whichever
    (station, climate_day) `argv` names, so any eligible target this batch
    picks completes successfully."""
    station = _argv_field(argv, "--station")
    climate_day = _argv_field(argv, "--climate-day")
    output_dir = _output_dir_for(config, station=station, climate_day=climate_day)
    output_dir.mkdir(parents=True, exist_ok=True)
    scored = ScoredTrial(
        trial_id="t1", station=station, climate_day=climate_day, instrument_id="i1",
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


def _happy_subprocess(
    config: runner.RunConfig,
) -> Callable[..., subprocess.CompletedProcess[str]]:
    def fake(
        argv: Sequence[str], *, timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if "asos_cache_csv.py" in argv[1]:
            return _completed_process(0)
        assert "current_rung_hold_paper_replay.py" in argv[1]
        return _happy_driver(config, argv)

    return fake


def _five_rows() -> list[ReplaySufficiency]:
    return [
        _row(station="LAX", climate_day="2026-09-01"),
        _row(station="MDW", climate_day="2026-09-01"),
        _row(station="MIA", climate_day="2026-09-01"),
        _row(station="SFO", climate_day="2026-09-01"),
        _row(station="LAX", climate_day="2026-09-02"),
    ]


# ---------------------------------------------------------------------------
# select_target / _pre_fee_eligible_rows: exclude kwarg
# ---------------------------------------------------------------------------


def test_select_target_exclude_kwarg_skips_a_listed_key() -> None:
    rows = [
        _row(station="LAX", climate_day="2026-09-01"),
        _row(station="MDW", climate_day="2026-09-01"),
    ]
    excluded_key = ("LAX", "2026-09-01", STRATEGY, LAG_MINUTES)
    target = runner.select_target(
        rows=rows, replayed=(), drift=(), exclude=frozenset({excluded_key}),
    )
    assert target is not None
    assert target.station == "MDW"


def test_select_target_exclude_kwarg_defaults_to_empty_and_never_changes_todays_pick() -> None:
    rows = [
        _row(station="LAX", climate_day="2026-09-01"),
        _row(station="MDW", climate_day="2026-09-01"),
    ]
    target = runner.select_target(rows=rows, replayed=(), drift=())
    assert target is not None
    assert target.station == "LAX"


# ---------------------------------------------------------------------------
# run_batch: max_targets, exclusion of a BLOCKED head-of-line, budget,
# failure propagation, per-batch state, work-dir cleanup, summary line
# ---------------------------------------------------------------------------


def test_run_batch_runs_at_most_max_targets(tmp_path: Path) -> None:
    config = _config(tmp_path)
    write_replay_sufficiency(config.replay_sufficiency_path, _five_rows())
    exit_code = runner.run_batch(
        config, max_targets=3, budget_s=10_000.0,
        run_subprocess=_happy_subprocess(config), sink=_RecordingSink(),
        work_dir_factory=lambda: tmp_path / "work",
        now_utc=_SAFE_NOW_UTC,
    )
    assert exit_code == 0
    rows = read_replay_results(config.replay_results_path)
    assert len(rows) == 3
    assert [r.outcome for r in rows] == ["COMPLETED", "COMPLETED", "COMPLETED"]
    # Oldest-first, SUPPORTED_STATIONS tie-break: LAX, MDW, MIA on 09-01.
    assert [(r.station, r.climate_day) for r in rows] == [
        ("LAX", "2026-09-01"), ("MDW", "2026-09-01"), ("MIA", "2026-09-01"),
    ]


def test_run_batch_completed_line_for_a_post_freeze_day_withholds_trials_and_fills(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """R3-VIABILITY r2 delta "R3V-b" item 5, ported through R3V-a's batch
    path: `_run_one` is the ONE place the COMPLETED line is printed for
    BOTH `run_once` (single target) and `run_batch` (R3V-a's loop calls it
    too), so a post-freeze row inside a BATCH run must withhold
    `trials=`/`fills=` exactly like the single-target path already does
    (`test_replay_daily_runner.py::test_run_once_withholds_trials_and_
    fills_on_a_post_freeze_completed_line`)."""
    post_freeze_day = "2026-09-26"
    assert post_freeze_day > runner.FREEZE_CLIMATE_DAY
    config = _config(tmp_path)
    write_replay_sufficiency(
        config.replay_sufficiency_path, [_row(station="LAX", climate_day=post_freeze_day)],
    )
    capsys.readouterr()
    exit_code = runner.run_batch(
        config, max_targets=1, budget_s=10_000.0,
        run_subprocess=_happy_subprocess(config), sink=_RecordingSink(),
        work_dir_factory=lambda: tmp_path / "work",
        now_utc=_SAFE_NOW_UTC,
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "post-freeze: counts withheld" in out
    assert "trials=" not in out
    assert "fills=" not in out
    # The stored row is unaffected -- only the printed line withholds.
    rows = read_replay_results(config.replay_results_path)
    assert len(rows) == 1
    assert rows[0].outcome == "COMPLETED"
    assert rows[0].trials == 1
    assert rows[0].fills == 1


def test_run_batch_never_reselects_an_always_blocked_target_within_the_batch(
    tmp_path: Path,
) -> None:
    """An ASOS-empty (always-BLOCKED) day must not stall the queue: with
    two eligible days and max_targets=5, the batch tries each ONCE, not
    the first one five times (R3V head-of-line fix)."""
    config = _config(tmp_path)
    write_replay_sufficiency(
        config.replay_sufficiency_path,
        [
            _row(station="LAX", climate_day="2026-09-01"),
            _row(station="MDW", climate_day="2026-09-01"),
        ],
    )

    def fake(
        argv: Sequence[str], *, timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        assert "asos_cache_csv.py" in argv[1]
        return _completed_process(2)  # ASOS_CACHE_EMPTY -- BLOCKED, never terminal

    exit_code = runner.run_batch(
        config, max_targets=5, budget_s=10_000.0,
        run_subprocess=fake, sink=_RecordingSink(),
        work_dir_factory=lambda: tmp_path / "work",
        now_utc=_SAFE_NOW_UTC,
    )
    assert exit_code == 0
    rows = read_replay_results(config.replay_results_path)
    assert len(rows) == 2
    assert {(r.station, r.climate_day) for r in rows} == {
        ("LAX", "2026-09-01"), ("MDW", "2026-09-01"),
    }
    assert all(r.outcome == "BLOCKED" for r in rows)


def test_run_batch_honours_the_budget_reserve_under_a_fake_clock(tmp_path: Path) -> None:
    config = _config(tmp_path)
    write_replay_sufficiency(config.replay_sufficiency_path, _five_rows())
    # Each call to the fake clock advances past the reserve after the first
    # target completes, so the second target must never start.
    clock = iter([0.0, 0.0, 0.0, 5_000.0, 5_000.0, 5_000.0, 5_000.0, 5_000.0, 5_000.0])

    def fake_monotonic() -> float:
        try:
            return next(clock)
        except StopIteration:
            return 5_000.0

    exit_code = runner.run_batch(
        config, max_targets=5, budget_s=5_000.0, reserve_s=240.0,
        run_subprocess=_happy_subprocess(config), sink=_RecordingSink(),
        work_dir_factory=lambda: tmp_path / "work", monotonic=fake_monotonic,
        now_utc=_SAFE_NOW_UTC,
    )
    assert exit_code == 0
    rows = read_replay_results(config.replay_results_path)
    assert len(rows) == 1


def test_run_batch_stops_on_the_first_failed_target_with_a_nonzero_exit(tmp_path: Path) -> None:
    config = _config(tmp_path)
    write_replay_sufficiency(config.replay_sufficiency_path, _five_rows())
    calls: list[str] = []

    def fake(
        argv: Sequence[str], *, timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if "asos_cache_csv.py" in argv[1]:
            return _completed_process(0)
        station = _argv_field(argv, "--station")
        calls.append(station)
        if station == "LAX" and _argv_field(argv, "--climate-day") == "2026-09-01":
            return _completed_process(1, stderr="ValueError: boom")
        return _happy_driver(config, argv)

    exit_code = runner.run_batch(
        config, max_targets=5, budget_s=10_000.0,
        run_subprocess=fake, sink=_RecordingSink(),
        work_dir_factory=lambda: tmp_path / "work",
        now_utc=_SAFE_NOW_UTC,
    )
    assert exit_code == 1
    rows = read_replay_results(config.replay_results_path)
    assert len(rows) == 1
    assert rows[0].outcome == "FAILED"
    assert calls == ["LAX"]  # the batch never even tried a second target


def test_run_batch_prints_no_summary_line_when_max_targets_is_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    config = _config(tmp_path)
    write_replay_sufficiency(config.replay_sufficiency_path, _five_rows())
    runner.run_batch(
        config, max_targets=1, budget_s=10_000.0,
        run_subprocess=_happy_subprocess(config), sink=_RecordingSink(),
        work_dir_factory=lambda: tmp_path / "work",
        now_utc=_SAFE_NOW_UTC,
    )
    assert "BATCH_SUMMARY" not in capsys.readouterr().out


def test_run_batch_prints_a_summary_line_with_per_target_wall_s(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    config = _config(tmp_path)
    write_replay_sufficiency(config.replay_sufficiency_path, _five_rows()[:2])
    runner.run_batch(
        config, max_targets=3, budget_s=10_000.0,
        run_subprocess=_happy_subprocess(config), sink=_RecordingSink(),
        work_dir_factory=lambda: tmp_path / "work",
        now_utc=_SAFE_NOW_UTC,
    )
    out = capsys.readouterr().out
    assert "BATCH_SUMMARY 2 target(s)" in out
    assert "wall_s=" in out


def test_run_batch_zero_or_negative_budget_starts_zero_targets_and_exits_zero(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    write_replay_sufficiency(config.replay_sufficiency_path, _five_rows())

    def fail_if_called(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        raise AssertionError("no subprocess should run under an exhausted budget")

    exit_code = runner.run_batch(
        config, max_targets=5, budget_s=-100.0, reserve_s=240.0,
        run_subprocess=fail_if_called, sink=_RecordingSink(),
        work_dir_factory=lambda: tmp_path / "work",
        now_utc=_SAFE_NOW_UTC,
    )
    assert exit_code == 0
    assert not config.replay_results_path.exists() or read_replay_results(
        config.replay_results_path,
    ) == ()


def test_run_batch_never_starts_a_target_inside_the_protected_window(tmp_path: Path) -> None:
    config = _config(tmp_path)
    write_replay_sufficiency(config.replay_sufficiency_path, _five_rows())

    def fail_if_called(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        raise AssertionError("no subprocess should run inside the protected window")

    exit_code = runner.run_batch(
        config, max_targets=5, budget_s=10_000.0,
        run_subprocess=fail_if_called, sink=_RecordingSink(),
        work_dir_factory=lambda: tmp_path / "work",
        now_utc=lambda: dt.datetime(2026, 9, 29, 16, 40, tzinfo=dt.UTC),
    )
    assert exit_code == 0
    assert not config.replay_results_path.exists() or read_replay_results(
        config.replay_results_path,
    ) == ()


def test_run_batch_resolves_drift_and_manifest_exactly_once(tmp_path: Path) -> None:
    config = _config(tmp_path)
    write_replay_sufficiency(config.replay_sufficiency_path, _five_rows()[:3])
    calls: list[Path] = []
    real_resolve = runner.resolve_strategy_from_manifest

    def counting_resolve(path: Path) -> str:
        calls.append(path)
        return real_resolve(path)

    runner.resolve_strategy_from_manifest = counting_resolve  # type: ignore[assignment]
    try:
        runner.run_batch(
            config, max_targets=3, budget_s=10_000.0,
            run_subprocess=_happy_subprocess(config), sink=_RecordingSink(),
            work_dir_factory=lambda: tmp_path / "work",
            now_utc=_SAFE_NOW_UTC,
        )
    finally:
        runner.resolve_strategy_from_manifest = real_resolve  # type: ignore[assignment]
    assert len(calls) == 1


def test_run_batch_prints_fee_regime_excluded_exactly_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    config = _config(tmp_path)
    write_replay_sufficiency(config.replay_sufficiency_path, _five_rows()[:3])
    runner.run_batch(
        config, max_targets=3, budget_s=10_000.0,
        run_subprocess=_happy_subprocess(config), sink=_RecordingSink(),
        work_dir_factory=lambda: tmp_path / "work",
        now_utc=_SAFE_NOW_UTC,
    )
    out = capsys.readouterr().out
    assert out.count("FEE_REGIME_EXCLUDED") == 1


def test_run_batch_cleans_up_each_targets_work_dir(tmp_path: Path) -> None:
    config = _config(tmp_path)
    write_replay_sufficiency(config.replay_sufficiency_path, _five_rows()[:2])
    made_dirs: list[Path] = []

    def work_dir_factory() -> Path:
        made = tmp_path / f"work-{len(made_dirs)}"
        made.mkdir(parents=True, exist_ok=True)
        (made / "marker.txt").write_text("x")
        made_dirs.append(made)
        return made

    runner.run_batch(
        config, max_targets=2, budget_s=10_000.0,
        run_subprocess=_happy_subprocess(config), sink=_RecordingSink(),
        work_dir_factory=work_dir_factory,
        now_utc=_SAFE_NOW_UTC,
    )
    assert len(made_dirs) == 2
    assert all(not d.exists() for d in made_dirs)


# ---------------------------------------------------------------------------
# Driver timeout (L-53)
# ---------------------------------------------------------------------------


def test_run_batch_driver_timeout_appends_a_failed_row_and_stops_the_batch(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    write_replay_sufficiency(config.replay_sufficiency_path, _five_rows())

    def fake(
        argv: Sequence[str], *, timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if "asos_cache_csv.py" in argv[1]:
            return _completed_process(0)
        raise subprocess.TimeoutExpired(cmd=list(argv), timeout=1.0)

    exit_code = runner.run_batch(
        config, max_targets=5, budget_s=10_000.0,
        run_subprocess=fake, sink=_RecordingSink(),
        work_dir_factory=lambda: tmp_path / "work",
        now_utc=_SAFE_NOW_UTC,
    )
    assert exit_code == 1
    rows = read_replay_results(config.replay_results_path)
    assert len(rows) == 1
    assert rows[0].outcome == "FAILED"
    assert rows[0].exception_type == "DRIVER_TIMEOUT"


# ---------------------------------------------------------------------------
# _run_subprocess_with_rss: per-child RSS (item 4)
# ---------------------------------------------------------------------------


def test_run_subprocess_with_rss_returns_stdout_and_a_positive_peak_rss() -> None:
    result, peak_rss_bytes = runner._run_subprocess_with_rss(
        [sys.executable, "-c", "print('hello')"], timeout=30.0,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "hello"
    assert peak_rss_bytes > 0


def test_run_subprocess_with_rss_reports_the_childs_own_return_code() -> None:
    result, _peak_rss_bytes = runner._run_subprocess_with_rss(
        [sys.executable, "-c", "import sys; sys.exit(3)"], timeout=30.0,
    )
    assert result.returncode == 3


def test_run_subprocess_with_rss_raises_timeout_expired_and_reaps_the_child() -> None:
    with pytest.raises(subprocess.TimeoutExpired):
        runner._run_subprocess_with_rss(
            [sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.2,
        )


def test_run_batch_measures_per_target_rss_correctly_when_the_second_target_is_smaller(
    tmp_path: Path,
) -> None:
    """R3V-a item 4: `RUSAGE_CHILDREN`'s cumulative watermark used to read
    0 for any target smaller than an earlier one -- a driver result that
    already carries its own `peak_rss_bytes` (as `_run_subprocess_with_rss`
    produces in production) must be trusted verbatim, never re-derived
    from the watermark delta."""
    config = _config(tmp_path)
    write_replay_sufficiency(config.replay_sufficiency_path, _five_rows()[:2])
    rss_by_station = {"LAX": 500_000_000, "MDW": 9_000}

    def fake(
        argv: Sequence[str], *, timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if "asos_cache_csv.py" in argv[1]:
            return _completed_process(0)
        station = _argv_field(argv, "--station")
        result = _happy_driver(config, argv)
        result.peak_rss_bytes = rss_by_station[station]  # type: ignore[attr-defined]
        return result

    runner.run_batch(
        config, max_targets=2, budget_s=10_000.0,
        run_subprocess=fake, sink=_RecordingSink(),
        work_dir_factory=lambda: tmp_path / "work",
        now_utc=_SAFE_NOW_UTC,
    )
    rows = {r.station: r for r in read_replay_results(config.replay_results_path)}
    assert rows["LAX"].peak_rss_bytes == 500_000_000
    assert rows["MDW"].peak_rss_bytes == 9_000


def test_run_batch_warns_when_a_target_exceeds_the_rss_warn_constant(tmp_path: Path) -> None:
    config = _config(tmp_path)
    write_replay_sufficiency(config.replay_sufficiency_path, _five_rows()[:1])
    sink = _RecordingSink()

    def fake(
        argv: Sequence[str], *, timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if "asos_cache_csv.py" in argv[1]:
            return _completed_process(0)
        result = _happy_driver(config, argv)
        result.peak_rss_bytes = runner.REPLAY_TARGET_RSS_WARN_BYTES + 1  # type: ignore[attr-defined]
        return result

    runner.run_batch(
        config, max_targets=1, budget_s=10_000.0,
        run_subprocess=fake, sink=sink, work_dir_factory=lambda: tmp_path / "work",
        now_utc=_SAFE_NOW_UTC,
    )
    assert any(
        getattr(p, "event", None) == "BREEZY_REPLAY_TARGET_RSS_HIGH" for p in sink.payloads
    )


# ---------------------------------------------------------------------------
# run_once is untouched: byte-identity with the max_targets=1 default path
# ---------------------------------------------------------------------------


def test_run_batch_at_max_targets_one_is_byte_identical_to_run_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """R3V-a item 7. `run_once` is not touched by this change at all; this
    proves `run_batch(max_targets=1, ...)` -- the path a bare invocation
    with no `--max-targets` flag exercises via `main` -- produces the same
    stdout and the same row as calling `run_once` directly."""
    (tmp_path / "a").mkdir(parents=True, exist_ok=True)
    config_a = _config(tmp_path / "a")
    write_replay_sufficiency(config_a.replay_sufficiency_path, _five_rows())
    capsys.readouterr()
    exit_code_a = runner.run_once(
        config_a, run_subprocess=_happy_subprocess(config_a), sink=_RecordingSink(),
        work_dir_factory=lambda: tmp_path / "a" / "work",
    )
    stdout_a = capsys.readouterr().out
    rows_a = read_replay_results(config_a.replay_results_path)

    (tmp_path / "b").mkdir(parents=True, exist_ok=True)
    config_b = _config(tmp_path / "b")
    write_replay_sufficiency(config_b.replay_sufficiency_path, _five_rows())
    exit_code_b = runner.run_batch(
        config_b, max_targets=1, budget_s=10_000.0,
        run_subprocess=_happy_subprocess(config_b), sink=_RecordingSink(),
        work_dir_factory=lambda: tmp_path / "b" / "work",
        now_utc=_SAFE_NOW_UTC,
    )
    stdout_b = capsys.readouterr().out
    rows_b = read_replay_results(config_b.replay_results_path)

    assert exit_code_a == exit_code_b
    assert stdout_a == stdout_b
    assert len(rows_a) == len(rows_b) == 1
    assert rows_a[0].outcome == rows_b[0].outcome == "COMPLETED"
    assert rows_a[0].peak_rss_bytes == rows_b[0].peak_rss_bytes
