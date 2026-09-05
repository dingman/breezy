"""RED-first suite for I3-deploy of
`docs/plans/LIVE_FILL_SCORING_CHAIN_2026-09-05.md` -- the new 14:15 UTC
`breezy-score-live-trials` unit pair + `deploy/systemd/
score-live-trials-run.sh`. The counter (`structural_dead_stop.py`), the
scorer (`score_live_trials.py`) and the node-env pre-flight leaf
(`breezy.runtime.exec_state_db_path`) are built in parallel commits and are
deliberately NOT invoked here -- the wrapper's own `$PY` is stubbed with a
shell script that dispatches on the invocation shape, so argv, the marker
and failure propagation are pinned against a stub, never a real scorer
(plan section 3.0, `test_family_tally_v2_deploy.py:40-47,95-99,127-133`
idiom).
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import shlex
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SYSTEMD_DIR = _REPO_ROOT / "deploy" / "systemd"
_WRAPPER = _SYSTEMD_DIR / "score-live-trials-run.sh"
_V1_WRAPPER = _SYSTEMD_DIR / "live-tally-run.sh"
_FAMILY_MANIFEST_LITERAL = str(_REPO_ROOT / "deploy" / "families" / "pm_us_crh_v2.json")

_PINNED_STATE_DB_LITERAL = (
    "Environment=POLYMARKET_US_EXEC_STATE_DB="
    "/home/jon/.local/share/breezy/state/exec_polymarket_us.sqlite"
)

_MARKER_WRITE_PATTERN = re.compile(
    r'^\s*:\s*>\s*"\$OUT/score_live_trials_ok_\$STAMP"\s*$', re.MULTILINE
)


def _default_counter_json(*, count: int = 20, fetch_start: str = "2026-09-05") -> str:
    payload = {
        "count": count,
        "depth_root_present": True,
        "fetch_end": "2026-09-05",
        "fetch_start": fetch_start,
        "manifest_sha256": "a" * 64,
        "stations": ["LAX", "MDW", "MIA", "SFO"],
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def _make_stub(
    tmp_path: Path,
    *,
    check_exit: int = 0,
    check_token: str = "MATCH",
    counter_exit: int = 0,
    counter_json: str | None = None,
    scorer_fail_city: str = "",
    scorer_exit: int = 0,
) -> tuple[Path, Path]:
    """A dispatching stub `$PY`: recognises the three invocation shapes the
    wrapper makes (the `--check` module call, the counter, one scorer call
    per city), logs each to `argv_log` tagged by shape, and behaves per the
    keyword arguments. Returns (stub_path, argv_log_path)."""
    argv_log = tmp_path / "argv_log.txt"
    json_text = counter_json if counter_json is not None else _default_counter_json()
    script = f"""#!/usr/bin/env bash
ARGV_LOG={shlex.quote(str(argv_log))}
case "$*" in
  *"-m breezy.runtime.exec_state_db_path --check"*)
    echo "CHECK $*" >> "$ARGV_LOG"
    echo "{check_token}"
    exit {check_exit}
    ;;
  *"structural_dead_stop.py"*)
    echo "COUNTER $*" >> "$ARGV_LOG"
    if [ {counter_exit} -eq 0 ]; then
      prev=""
      for arg in "$@"; do
        if [ "$prev" = "--output" ]; then
          cat > "$arg" <<'BREEZY_STUB_JSON'
{json_text}
BREEZY_STUB_JSON
        fi
        prev="$arg"
      done
    fi
    exit {counter_exit}
    ;;
  *"score_live_trials.py"*)
    echo "SCORER $*" >> "$ARGV_LOG"
    city=""
    prev=""
    for arg in "$@"; do
      if [ "$prev" = "--city" ]; then
        city="$arg"
      fi
      prev="$arg"
    done
    if [ -n "{scorer_fail_city}" ] && [ "$city" = "{scorer_fail_city}" ]; then
      exit 1
    fi
    exit {scorer_exit}
    ;;
  *)
    echo "UNKNOWN $*" >> "$ARGV_LOG"
    exit 0
    ;;
esac
"""
    stub = tmp_path / "stub_python.sh"
    stub.write_text(script)
    stub.chmod(0o755)
    return stub, argv_log


def _run_wrapper(
    tmp_path: Path, *, stub_python: Path | None, set_state_db: bool = True
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(home)
    env["BREEZY_SCORED_TRIALS_DIR"] = str(tmp_path / "scored_trials")
    env["BREEZY_LIVE_TALLY_OUTPUT_DIR"] = str(tmp_path / "derived")
    if set_state_db:
        env["POLYMARKET_US_EXEC_STATE_DB"] = str(tmp_path / "state" / "exec_polymarket_us.sqlite")
    else:
        env.pop("POLYMARKET_US_EXEC_STATE_DB", None)
    if stub_python is not None:
        env["BREEZY_SCORE_LIVE_TRIALS_PYTHON"] = str(stub_python)
    return subprocess.run(
        ["bash", str(_WRAPPER)],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _marker_path(tmp_path: Path) -> Path:
    stamp = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%d")
    return tmp_path / "derived" / f"score_live_trials_ok_{stamp}"


def _scorer_calls(argv_log: Path) -> list[str]:
    if not argv_log.exists():
        return []
    return [line for line in argv_log.read_text().splitlines() if line.startswith("SCORER")]


def _cities_of(calls: list[str]) -> set[str]:
    cities: set[str] = set()
    for call in calls:
        parts = call.split()
        cities.add(parts[parts.index("--city") + 1])
    return cities


def test_wrapper_exists_and_is_executable() -> None:
    assert _WRAPPER.exists()
    assert os.access(_WRAPPER, os.X_OK)


def test_wrapper_script_is_valid_bash() -> None:
    result = subprocess.run(
        ["bash", "-n", str(_WRAPPER)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_marker_written_only_when_counter_and_all_cities_succeed(tmp_path: Path) -> None:
    stub, argv_log = _make_stub(tmp_path)
    result = _run_wrapper(tmp_path, stub_python=stub)
    assert result.returncode == 0, result.stderr
    assert _marker_path(tmp_path).exists()
    assert len(_scorer_calls(argv_log)) == 4


def test_one_city_failure_leaves_all_cities_attempted_no_marker_nonzero(
    tmp_path: Path,
) -> None:
    stub, argv_log = _make_stub(tmp_path, scorer_fail_city="MDW")
    result = _run_wrapper(tmp_path, stub_python=stub)
    assert result.returncode != 0
    assert not _marker_path(tmp_path).exists()
    calls = _scorer_calls(argv_log)
    assert len(calls) == 4
    assert _cities_of(calls) == {"LAX", "MDW", "MIA", "SFO"}


def test_counter_failure_leaves_no_marker_and_never_invokes_a_scorer(
    tmp_path: Path,
) -> None:
    stub, argv_log = _make_stub(tmp_path, counter_exit=1)
    result = _run_wrapper(tmp_path, stub_python=stub)
    assert result.returncode != 0
    assert not _marker_path(tmp_path).exists()
    assert not _scorer_calls(argv_log)


def test_check_exit_3_leaves_no_marker_and_never_runs_the_counter(tmp_path: Path) -> None:
    stub, argv_log = _make_stub(tmp_path, check_exit=3, check_token="MISMATCH")
    result = _run_wrapper(tmp_path, stub_python=stub)
    assert result.returncode != 0
    assert not _marker_path(tmp_path).exists()
    calls = argv_log.read_text().splitlines() if argv_log.exists() else []
    assert not any(line.startswith("COUNTER") for line in calls)


def test_no_node_token_warns_but_marker_still_written(tmp_path: Path) -> None:
    stub, _ = _make_stub(tmp_path, check_token="NO_NODE", check_exit=0)
    result = _run_wrapper(tmp_path, stub_python=stub)
    assert result.returncode == 0, result.stderr
    assert _marker_path(tmp_path).exists()
    log_text = (tmp_path / "derived" / "score_live_trials.log").read_text()
    assert "NO_NODE" in log_text or "WARN" in log_text


def test_fetch_start_mismatch_leaves_no_marker(tmp_path: Path) -> None:
    bad_json = _default_counter_json(fetch_start="2026-09-06")
    stub, argv_log = _make_stub(tmp_path, counter_json=bad_json)
    result = _run_wrapper(tmp_path, stub_python=stub)
    assert result.returncode != 0
    assert not _marker_path(tmp_path).exists()
    assert not _scorer_calls(argv_log)


def test_stations_parsed_from_seeded_counter_json_exact_layout(tmp_path: Path) -> None:
    stub, argv_log = _make_stub(tmp_path)
    result = _run_wrapper(tmp_path, stub_python=stub)
    assert result.returncode == 0, result.stderr
    assert _cities_of(_scorer_calls(argv_log)) == {"LAX", "MDW", "MIA", "SFO"}


def test_scorer_argv_pinned_no_fill_source_family_manifest_present_one_city(
    tmp_path: Path,
) -> None:
    stub, argv_log = _make_stub(tmp_path)
    result = _run_wrapper(tmp_path, stub_python=stub)
    assert result.returncode == 0, result.stderr
    calls = _scorer_calls(argv_log)
    assert len(calls) == 4
    for call in calls:
        assert "--fill-source" not in call
        assert _FAMILY_MANIFEST_LITERAL in call
        assert call.count("--city") == 1


def test_unset_state_db_env_var_is_nonzero_and_never_invokes_python(tmp_path: Path) -> None:
    stub, argv_log = _make_stub(tmp_path)
    result = _run_wrapper(tmp_path, stub_python=stub, set_state_db=False)
    assert result.returncode != 0
    assert not argv_log.exists()


def test_environment_lines_byte_identical_and_equal_pinned_literal() -> None:
    scorer_svc = (_SYSTEMD_DIR / "breezy-score-live-trials.service").read_text()
    tally_svc = (_SYSTEMD_DIR / "breezy-live-tally.service").read_text()
    scorer_lines = [
        line
        for line in scorer_svc.splitlines()
        if line.startswith("Environment=POLYMARKET_US_EXEC_STATE_DB=")
    ]
    tally_lines = [
        line
        for line in tally_svc.splitlines()
        if line.startswith("Environment=POLYMARKET_US_EXEC_STATE_DB=")
    ]
    assert len(scorer_lines) == 1
    assert len(tally_lines) == 1
    assert scorer_lines[0] == tally_lines[0] == _PINNED_STATE_DB_LITERAL


def test_neither_i3_unit_carries_an_environment_file_directive() -> None:
    # Repo-wide: breezy-quote-tape.service legitimately carries an
    # EnvironmentFile= for venue credentials -- out of scope here. This
    # increment's invariant is narrower: neither of the two units this
    # plan touches (the new scorer unit, the existing tally unit it adds
    # one Environment= line to) may carry one.
    for name in ("breezy-score-live-trials.service", "breezy-live-tally.service"):
        assert "EnvironmentFile=" not in (_SYSTEMD_DIR / name).read_text(), name


def test_family_manifest_assignment_byte_identical_across_wrappers() -> None:
    scorer_lines = [
        line for line in _WRAPPER.read_text().splitlines() if line.startswith("FAMILY_MANIFEST=")
    ]
    v1_lines = [
        line for line in _V1_WRAPPER.read_text().splitlines() if line.startswith("FAMILY_MANIFEST=")
    ]
    assert len(scorer_lines) == 1
    assert len(v1_lines) == 1
    assert scorer_lines[0] == v1_lines[0]


def test_v1_d0_literal_assignment_byte_identical_across_wrappers() -> None:
    scorer_lines = [
        line for line in _WRAPPER.read_text().splitlines() if line.startswith("V1_D0_LITERAL=")
    ]
    v1_lines = [
        line for line in _V1_WRAPPER.read_text().splitlines() if line.startswith("V1_D0_LITERAL=")
    ]
    assert len(scorer_lines) == 1
    assert len(v1_lines) == 1
    assert scorer_lines[0] == v1_lines[0]


def test_only_the_scorer_wrapper_writes_the_success_marker() -> None:
    writers = [
        sh.name
        for sh in sorted(_SYSTEMD_DIR.glob("*.sh"))
        if _MARKER_WRITE_PATTERN.search(sh.read_text())
    ]
    assert writers == ["score-live-trials-run.sh"]


def test_score_live_trials_unit_pair_exists_and_wires_to_wrapper() -> None:
    service_path = _SYSTEMD_DIR / "breezy-score-live-trials.service"
    timer_path = _SYSTEMD_DIR / "breezy-score-live-trials.timer"
    assert service_path.exists()
    assert timer_path.exists()

    service_text = service_path.read_text()
    exec_lines = [line for line in service_text.splitlines() if line.startswith("ExecStart=")]
    assert len(exec_lines) == 1
    assert exec_lines[0].strip().endswith("score-live-trials-run.sh")
    assert "TimeoutStartSec=" in service_text
    assert "EnvironmentFile=" not in service_text

    timer_text = timer_path.read_text()
    assert "Unit=breezy-score-live-trials.service" in timer_text
    assert "OnCalendar=*-*-* 14:15:00 UTC" in timer_text
    assert "Persistent=true" in timer_text
