"""Coordinator-review follow-up on commit 0868fbb: `run_batch`'s DEFAULT
`run_subprocess` (`_default_run_subprocess`) has no `timeout` kwarg, so
every real (non-test-fake) batch run raised `TypeError` the moment
`_run_one` called it for the driver step -- the per-target RSS fix
(`_run_subprocess_with_rss`) was consequently never wired into production
at all. RED-first on 0868fbb.

Unlike `test_replay_daily_runner_batch.py` (which injects a fake
`run_subprocess`, a pure Python callable), every test in THIS file calls
`run_batch` with its OWN default `run_subprocess` -- a REAL child process,
spawned via a `python_executable` stub (mirrors `test_replay_daily_
wrapper.py`'s own `$PY`-stub idiom, one level down: a real, dispatching,
executable script standing in for `current_rung_hold_paper_replay.py`/
`asos_cache_csv.py`, never a Python-level fake).
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import subprocess
import sys
import textwrap
from collections.abc import Callable
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

STATION = "SFO"
CLIMATE_DAY = "2026-09-01"
_REAL_PYTHON = "/home/jon/breezy/.venv/bin/python"
_SAFE_NOW_UTC: Callable[[], dt.datetime] = lambda: dt.datetime(2026, 9, 29, 12, 0, tzinfo=dt.UTC)


def _row() -> ReplaySufficiency:
    return ReplaySufficiency(
        schema_version=REPLAY_SUFFICIENCY_SCHEMA_VERSION,
        station=STATION,
        climate_day=CLIMATE_DAY,
        verdict="SUFFICIENT",
        reason="",
        winner_instance_id="5a111bca-0000-0000-0000-000000000000",
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
                "stations": [STATION],
                "status": "REGISTERED",
                "composition_kind": "continuous_rung_hold",
                "density_artefact_path": "deploy/families/artefacts/not_applicable_density.json",
                "density_artefact_sha256": "c" * 64,
                "taker_fee_coefficient": "0.0695",
            }
        )
    )
    return path


def _config(tmp_path: Path) -> runner.RunConfig:
    return runner.RunConfig(
        replay_sufficiency_path=tmp_path / "replay_sufficiency.jsonl",
        replay_results_path=tmp_path / "replay_results.jsonl",
        replay_drift_path=tmp_path / "replay_drift.jsonl",
        quote_catalog=tmp_path / "quote_catalog",
        weather_catalog_root=tmp_path / "weather_catalog",
        family_manifest_path=_write_manifest(tmp_path / "family.json"),
        output_root=tmp_path / "out",
        python_executable=_driver_stub_executable(tmp_path),
        skip_state_path=tmp_path / "wrapper_skip_state",
    )


def _driver_stub_executable(tmp_path: Path) -> str:
    """A REAL, chmod +x, shebang-executable Python script standing in for
    `python_executable` -- exactly the seam production already uses
    (`RunConfig.python_executable`), never a new one. Dispatches on
    `sys.argv[1]` (the real script PATH string `build_asos_argv`/
    `build_driver_argv` still build, unchanged) the same way `test_
    replay_daily_wrapper.py`'s bash `$PY` stub dispatches on `"$*"`.

    The ASOS branch exits 0 immediately (only `returncode` is consulted).
    The driver branch optionally sleeps `STUB_DRIVER_SLEEP_S` seconds
    (env, default 0) BEFORE writing a real scored-trial parquet + a
    matching `family_params.json` sidecar -- a real, slow-if-asked child
    for the timeout test, a real, fast child for the COMPLETED test.
    """
    stub = tmp_path / "driver_stub.py"
    stub.write_text(
        textwrap.dedent(
            f"""\
            #!{_REAL_PYTHON}
            import json
            import os
            import sys
            import time
            from decimal import Decimal
            from pathlib import Path

            sys.path.insert(0, {str(REPO_ROOT / "scripts/analysis")!r})
            sys.path.insert(0, {str(REPO_ROOT / "src")!r})
            import argv_digest

            script = sys.argv[1]
            flags = sys.argv[2:]

            def _flag(name):
                return flags[flags.index(name) + 1]

            if "asos_cache_csv.py" in script:
                sys.exit(0)

            assert "current_rung_hold_paper_replay.py" in script, script

            sleep_s = float(os.environ.get("STUB_DRIVER_SLEEP_S", "0"))
            if sleep_s:
                time.sleep(sleep_s)

            from breezy.persistence.scored_trial_store import write_scored_trials
            from breezy.settlement.trial_scorer import ScoredTrial

            output_dir = Path(_flag("--output-dir"))
            output_dir.mkdir(parents=True, exist_ok=True)
            scored = ScoredTrial(
                trial_id="t1", station=_flag("--station"), climate_day=_flag("--climate-day"),
                instrument_id="i1", settlement_tmax_f=70, held=True, pnl=Decimal("0.5"),
                revision_seq=1, raw_sha256="x", scored_at_ns=1, score_seq=0,
                settlement_basis="nws_final", excluded_reason=None,
                slippage=Decimal("0.01"), entry_ask=Decimal("0.4"), fill_px=Decimal("0.41"),
                fee=Decimal("0.02"),
            )
            write_scored_trials(output_dir, [scored], now_ns=2)
            payload = {{
                "family_id": "pm_us_crh_v4",
                "manifest_sha256": "a" * 64,
                "manifest_taker_fee_coefficient": "0.0695",
                "engine_required_fee_coefficient": "0.0695",
                "engine_params_source": "FAMILY_MANIFEST",
                "params_match": True,
                "composition_kind": "continuous_rung_hold",
                "argv_sha256": argv_digest.argv_sha256(flags),
            }}
            (output_dir / "family_params.json").write_text(json.dumps(payload), encoding="utf-8")
            sys.exit(0)
            """
        ),
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return str(stub)


# ---------------------------------------------------------------------------
# The production bug: run_batch's default run_subprocess crashes on the
# driver call the instant a real batch tries to enforce a timeout.
# ---------------------------------------------------------------------------


def test_run_batch_with_its_own_default_run_subprocess_writes_a_completed_row(
    tmp_path: Path,
) -> None:
    """On 0868fbb this raises `TypeError: _default_run_subprocess() got an
    unexpected keyword argument 'timeout'` the moment `_run_one` calls the
    driver -- `run_batch`'s default `run_subprocess` must itself accept
    (and honour) `timeout=`, AND must be the RSS-aware adapter so the
    R3V-a item 4 fix is actually wired into production."""
    config = _config(tmp_path)
    write_replay_sufficiency(config.replay_sufficiency_path, [_row()])
    exit_code = runner.run_batch(
        config, max_targets=1, budget_s=10_000.0, now_utc=_SAFE_NOW_UTC,
    )
    assert exit_code == 0
    rows = read_replay_results(config.replay_results_path)
    assert len(rows) == 1
    assert rows[0].outcome == "COMPLETED"
    assert rows[0].peak_rss_bytes is not None
    assert rows[0].peak_rss_bytes > 0


def test_run_batch_with_its_own_default_run_subprocess_kills_a_hung_real_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real child that outlives the driver's own timeout budget is
    killed, reaped, and recorded FAILED/DRIVER_TIMEOUT -- the batch stops
    with a non-zero exit. `reserve_s`/`budget_s` are chosen so the
    computed driver timeout is about 1s; the stub sleeps 5s."""
    monkeypatch.setenv("STUB_DRIVER_SLEEP_S", "5")
    config = _config(tmp_path)
    write_replay_sufficiency(config.replay_sufficiency_path, [_row()])
    exit_code = runner.run_batch(
        config, max_targets=1, budget_s=3.0, reserve_s=2.0, now_utc=_SAFE_NOW_UTC,
    )
    assert exit_code == 1
    rows = read_replay_results(config.replay_results_path)
    assert len(rows) == 1
    assert rows[0].outcome == "FAILED"
    assert rows[0].exception_type == "DRIVER_TIMEOUT"


# ---------------------------------------------------------------------------
# Item 7: the real golden comparison against the pre-R3V-a blob.
# ---------------------------------------------------------------------------


def _load_baseline_module(tmp_path: Path) -> object:
    """Loads `scripts/analysis/replay_daily_runner.py` exactly as it stood
    at commit `5c30e1f` (verified byte-identical to `ca22035`, R3V-a's
    real parent -- `git diff 5c30e1f ca22035 -- scripts/analysis/
    replay_daily_runner.py` is empty) via `git show`, never `git stash`
    (LESSONS.md). Written under pytest's own `tmp_path`, never a
    hand-rolled scratch directory."""
    blob = subprocess.run(
        ["git", "show", "5c30e1f:scripts/analysis/replay_daily_runner.py"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout
    baseline_path = tmp_path / "_baseline" / "replay_daily_runner_baseline.py"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(blob, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(
        "replay_daily_runner_baseline", baseline_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses' postponed-annotation resolution (`from __future__ import
    # annotations`, which this file uses) looks the module up via
    # `sys.modules[cls.__module__]` -- it must be registered BEFORE exec.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[spec.name]
        raise
    return module


def _config_for(module: object, root: Path) -> object:
    root.mkdir(parents=True, exist_ok=True)
    return module.RunConfig(  # type: ignore[attr-defined]
        replay_sufficiency_path=root / "replay_sufficiency.jsonl",
        replay_results_path=root / "replay_results.jsonl",
        replay_drift_path=root / "replay_drift.jsonl",
        quote_catalog=root / "quote_catalog",
        weather_catalog_root=root / "weather_catalog",
        family_manifest_path=_write_manifest(root / "family.json"),
        output_root=root / "out",
        python_executable=sys.executable,
        skip_state_path=root / "wrapper_skip_state",
    )


def _asos_empty_fake(
    argv: object, *, timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    assert "asos_cache_csv.py" in argv[1]  # type: ignore[index]
    return subprocess.CompletedProcess(args=[], returncode=2, stdout="", stderr="")


class _NullSink:
    def emit(self, payload: object) -> None:
        pass


def test_run_once_is_behaviourally_identical_to_the_pre_r3va_baseline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """R3V-a item 7, the real golden comparison: `run_once` in the CURRENT
    file (which R3V-a mechanically extracted `_run_one` out of) produces
    the same stdout and the same row, for an identical ASOS-refusal
    scenario, as `run_once` in the file exactly as it stood before this
    plan (commit 5c30e1f, verified identical to the actual parent
    ca22035). ASOS_CACHE_EMPTY is the shortest path through `run_once`
    that still writes a row and prints a non-trivial stdout line, so it
    exercises real code on both sides without needing a real driver."""
    baseline = _load_baseline_module(tmp_path)

    config_old = _config_for(baseline, tmp_path / "old")
    write_replay_sufficiency(config_old.replay_sufficiency_path, [_row()])
    capsys.readouterr()
    exit_code_old = baseline.run_once(  # type: ignore[attr-defined]
        config_old, run_subprocess=_asos_empty_fake, sink=_NullSink(),
        work_dir_factory=lambda: tmp_path / "old" / "work",
    )
    stdout_old = capsys.readouterr().out
    rows_old = read_replay_results(config_old.replay_results_path)

    config_new = _config_for(runner, tmp_path / "new")
    write_replay_sufficiency(config_new.replay_sufficiency_path, [_row()])
    exit_code_new = runner.run_once(
        config_new, run_subprocess=_asos_empty_fake, sink=_NullSink(),
        work_dir_factory=lambda: tmp_path / "new" / "work",
    )
    stdout_new = capsys.readouterr().out
    rows_new = read_replay_results(config_new.replay_results_path)

    assert exit_code_old == exit_code_new == 0
    assert stdout_old == stdout_new
    assert len(rows_old) == len(rows_new) == 1
    assert rows_old[0].outcome == rows_new[0].outcome == "BLOCKED"
    assert rows_old[0].blocked_reason == rows_new[0].blocked_reason == "ASOS_CACHE_EMPTY"
