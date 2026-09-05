"""RED-first suite for I3's v1-wrapper changes to `deploy/systemd/
live-tally-run.sh` (`docs/plans/LIVE_FILL_SCORING_CHAIN_2026-09-05.md`
section 3.0/I3): the wrapper now asserts the 14:15 scorer wrapper's dated
success marker, reads `count`/`fetch_start` from that same run's counter
JSON (never running the counter itself -- section 7's build-time
disposition), runs the node-env pre-flight, then invokes
`live_family_tally.py` with all three stop flags. `live_family_tally.py`
itself is v1-BINDING and untouched; `$PY` is stubbed exactly as
`test_family_tally_v2_deploy.py:40-47,95-99,127-133` stubs it, so none of
this depends on a real tally script or a real `exec_state_db_path` leaf.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import shlex
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SYSTEMD_DIR = _REPO_ROOT / "deploy" / "systemd"
_WRAPPER = _SYSTEMD_DIR / "live-tally-run.sh"


def _make_stub(
    tmp_path: Path,
    *,
    check_exit: int = 0,
    check_token: str = "MATCH",
    tally_exit: int = 0,
) -> tuple[Path, Path]:
    argv_log = tmp_path / "argv_log.txt"
    script = f"""#!/usr/bin/env bash
ARGV_LOG={shlex.quote(str(argv_log))}
case "$*" in
  *"-m breezy.runtime.exec_state_db_path --check"*)
    echo "CHECK $*" >> "$ARGV_LOG"
    echo "{check_token}"
    exit {check_exit}
    ;;
  *"live_family_tally.py"*)
    echo "TALLY $*" >> "$ARGV_LOG"
    exit {tally_exit}
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
        env["BREEZY_LIVE_TALLY_PYTHON"] = str(stub_python)
    return subprocess.run(
        ["bash", str(_WRAPPER)],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _stamp() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%d")


def _out_dir(tmp_path: Path) -> Path:
    return tmp_path / "derived"


def _write_marker(tmp_path: Path) -> None:
    out = _out_dir(tmp_path)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"score_live_trials_ok_{_stamp()}").touch()


def _write_counter_json(
    tmp_path: Path, *, fetch_start: str = "2026-09-05", count: int = 20
) -> None:
    out = _out_dir(tmp_path)
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "count": count,
        "depth_root_present": True,
        "fetch_end": "2026-09-05",
        "fetch_start": fetch_start,
        "manifest_sha256": "b" * 64,
        "stations": ["LAX", "MDW", "MIA", "SFO"],
    }
    (out / f"covered_listed_station_days_{_stamp()}.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True)
    )


def _tally_calls(argv_log: Path) -> list[str]:
    if not argv_log.exists():
        return []
    return [line for line in argv_log.read_text().splitlines() if line.startswith("TALLY")]


def test_wrapper_exists_and_is_executable() -> None:
    assert _WRAPPER.exists()
    assert os.access(_WRAPPER, os.X_OK)


def test_wrapper_script_is_valid_bash() -> None:
    result = subprocess.run(
        ["bash", "-n", str(_WRAPPER)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_missing_marker_is_nonzero_and_tally_never_invoked(tmp_path: Path) -> None:
    _write_counter_json(tmp_path)
    stub, argv_log = _make_stub(tmp_path)
    result = _run_wrapper(tmp_path, stub_python=stub)
    assert result.returncode != 0
    assert not _tally_calls(argv_log)


def test_missing_counter_json_is_nonzero(tmp_path: Path) -> None:
    _write_marker(tmp_path)
    stub, argv_log = _make_stub(tmp_path)
    result = _run_wrapper(tmp_path, stub_python=stub)
    assert result.returncode != 0
    assert not _tally_calls(argv_log)


def test_d0_mismatch_is_nonzero(tmp_path: Path) -> None:
    _write_marker(tmp_path)
    _write_counter_json(tmp_path, fetch_start="2026-09-06")
    stub, argv_log = _make_stub(tmp_path)
    result = _run_wrapper(tmp_path, stub_python=stub)
    assert result.returncode != 0
    assert not _tally_calls(argv_log)


def test_tally_argv_pinned_to_the_literal_invocation_count_and_fetch_start_extracted(
    tmp_path: Path,
) -> None:
    _write_marker(tmp_path)
    _write_counter_json(tmp_path, count=42, fetch_start="2026-09-05")
    stub, argv_log = _make_stub(tmp_path)
    result = _run_wrapper(tmp_path, stub_python=stub)
    assert result.returncode == 0, result.stderr

    calls = _tally_calls(argv_log)
    assert len(calls) == 1
    parts = calls[0].split()
    # "TALLY" tag, then the script path, then the store-dir positional, then flags.
    assert "live_family_tally.py" in parts[1]
    assert parts[2] == str(tmp_path / "scored_trials")
    assert "--output" in parts
    assert "--as-of" in parts
    assert parts[parts.index("--as-of") + 1] == _stamp()
    assert "--fill-source" in parts
    assert parts[parts.index("--fill-source") + 1] == str(
        tmp_path / "state" / "exec_polymarket_us.sqlite"
    )
    assert "--fill-since-climate-day" in parts
    assert parts[parts.index("--fill-since-climate-day") + 1] == "2026-09-05"
    assert "--covered-listed-station-days" in parts
    assert parts[parts.index("--covered-listed-station-days") + 1] == "42"


@pytest.mark.parametrize("check_exit,token", [(3, "MISMATCH"), (3, "DISCOVERY_FAILED")])
def test_check_mismatch_or_discovery_failed_aborts_before_the_tally(
    tmp_path: Path, check_exit: int, token: str
) -> None:
    _write_marker(tmp_path)
    _write_counter_json(tmp_path)
    stub, argv_log = _make_stub(tmp_path, check_exit=check_exit, check_token=token)
    result = _run_wrapper(tmp_path, stub_python=stub)
    assert result.returncode != 0
    assert not _tally_calls(argv_log)


@pytest.mark.parametrize("token", ["MATCH", "NO_NODE"])
def test_check_match_or_no_node_invokes_the_tally(tmp_path: Path, token: str) -> None:
    _write_marker(tmp_path)
    _write_counter_json(tmp_path)
    stub, argv_log = _make_stub(tmp_path, check_exit=0, check_token=token)
    result = _run_wrapper(tmp_path, stub_python=stub)
    assert result.returncode == 0, result.stderr
    assert len(_tally_calls(argv_log)) == 1


def test_truncated_counter_json_missing_closing_brace_is_nonzero(tmp_path: Path) -> None:
    _write_marker(tmp_path)
    out = _out_dir(tmp_path)
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "count": 20,
        "depth_root_present": True,
        "fetch_end": "2026-09-05",
        "fetch_start": "2026-09-05",
        "manifest_sha256": "b" * 64,
        "stations": ["LAX", "MDW", "MIA", "SFO"],
    }
    lines = json.dumps(payload, indent=2, sort_keys=True).splitlines()
    truncated = "\n".join(lines[:-1])  # drop the closing "}"
    (out / f"covered_listed_station_days_{_stamp()}.json").write_text(truncated)
    stub, argv_log = _make_stub(tmp_path)

    result = _run_wrapper(tmp_path, stub_python=stub)

    assert result.returncode != 0
    assert not _tally_calls(argv_log)


def test_counter_json_with_duplicate_count_line_is_nonzero(tmp_path: Path) -> None:
    _write_marker(tmp_path)
    out = _out_dir(tmp_path)
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "count": 20,
        "depth_root_present": True,
        "fetch_end": "2026-09-05",
        "fetch_start": "2026-09-05",
        "manifest_sha256": "b" * 64,
        "stations": ["LAX", "MDW", "MIA", "SFO"],
    }
    lines = json.dumps(payload, indent=2, sort_keys=True).splitlines()
    count_idx = next(i for i, line in enumerate(lines) if line.strip().startswith('"count"'))
    duplicated = lines[: count_idx + 1] + [lines[count_idx]] + lines[count_idx + 1 :]
    (out / f"covered_listed_station_days_{_stamp()}.json").write_text("\n".join(duplicated))
    stub, argv_log = _make_stub(tmp_path)

    result = _run_wrapper(tmp_path, stub_python=stub)

    assert result.returncode != 0
    assert not _tally_calls(argv_log)


def test_unset_state_db_env_var_is_nonzero(tmp_path: Path) -> None:
    _write_marker(tmp_path)
    _write_counter_json(tmp_path)
    stub, argv_log = _make_stub(tmp_path)
    result = _run_wrapper(tmp_path, stub_python=stub, set_state_db=False)
    assert result.returncode != 0
    assert not _tally_calls(argv_log)
