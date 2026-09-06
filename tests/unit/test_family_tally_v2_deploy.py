"""RED-first suite for build-order commit 8 of
`docs/plans/FAMILY_TALLY_V2_BLUEPRINT_2026-09-04.md`: the family-tally-v2
systemd deploy surface. The CLI (`scripts/analysis/family_tally_v2.py`) is
built in a parallel commit and is deliberately NOT invoked here -- the
wrapper's own test stubs `python` so id validation and argv construction are
verified without it.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from breezy.runtime.trade_supervisor_core import LAUNCH_WINDOW_END_UTC

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SYSTEMD_DIR = _REPO_ROOT / "deploy" / "systemd"
_WRAPPER = _SYSTEMD_DIR / "family-tally-v2-run.sh"
_FAMILIES_DIR = _REPO_ROOT / "deploy" / "families"


def _valid_family_ids() -> set[str]:
    """B6: a family manifest is valid only when its own `family_id` field
    equals the file's basename -- excludes `gs_boundary_pm_us_crh_v2.json`
    (a boundary artefact, never a family manifest, carries no `family_id`
    field at all) from ever being mistaken for a family id."""
    ids: set[str] = set()
    for p in _FAMILIES_DIR.glob("*.json"):
        try:
            payload = json.loads(p.read_text())
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("family_id") == p.stem:
            ids.add(p.stem)
    return ids


def _run_wrapper(
    family_arg: list[str],
    tmp_path: Path,
    *,
    stub_python: Path | None = None,
    create_marker: bool = True,
    set_state_db: bool = True,
    write_counter_json: bool = True,
    state_db: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    # I3 (LIVE_FILL_SCORING_CHAIN_2026-09-05.md, BLOCK-2): the wrapper now
    # asserts the 14:15 score-live-trials-run.sh success marker before
    # tallying. Every pre-existing test in this module drives the wrapper
    # PAST that assertion by default (create_marker=True) so it exercises
    # exactly what it did before this increment; the two new marker tests
    # below flip it off.
    out_dir = tmp_path / "derived"
    env = dict(os.environ)
    env["BREEZY_SCORED_TRIALS_DIR"] = str(tmp_path / "scored_trials")
    env["BREEZY_LIVE_TALLY_OUTPUT_DIR"] = str(out_dir)
    if stub_python is not None:
        env["BREEZY_FAMILY_TALLY_V2_PYTHON"] = str(stub_python)
    if set_state_db:
        env["POLYMARKET_US_EXEC_STATE_DB"] = str(
            state_db
            if state_db is not None
            else tmp_path / "state" / "exec_polymarket_us.sqlite"
        )
    else:
        env.pop("POLYMARKET_US_EXEC_STATE_DB", None)
    if create_marker:
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%d")
        (out_dir / f"score_live_trials_ok_{stamp}").touch()
    if write_counter_json:
        _write_counter_json(tmp_path)
    return subprocess.run(
        ["bash", str(_WRAPPER), *family_arg],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_wrapper_exists_and_is_executable() -> None:
    assert _WRAPPER.exists()
    assert os.access(_WRAPPER, os.X_OK)


def test_wrapper_script_is_valid_bash() -> None:
    result = subprocess.run(
        ["bash", "-n", str(_WRAPPER)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_at_least_two_real_family_manifests_present() -> None:
    ids = _valid_family_ids()
    assert "pm_us_crh_v2" in ids
    assert "kalshi_crh_v1" in ids


def test_wrapper_rejects_unknown_family_id(tmp_path: Path) -> None:
    result = _run_wrapper(["definitely_not_a_real_family"], tmp_path)
    assert result.returncode == 2
    for valid_id in _valid_family_ids():
        assert valid_id in result.stderr, f"expected {valid_id!r} named in: {result.stderr!r}"
    assert "definitely_not_a_real_family" in result.stderr


def test_wrapper_rejects_missing_family_id(tmp_path: Path) -> None:
    result = _run_wrapper([], tmp_path)
    assert result.returncode == 2
    for valid_id in _valid_family_ids():
        assert valid_id in result.stderr


@pytest.mark.parametrize("family_id", sorted(_valid_family_ids()))
def test_wrapper_passes_family_id_through_unmodified(tmp_path: Path, family_id: str) -> None:
    capture = tmp_path / "argv_capture.txt"
    stub = tmp_path / "stub_python.sh"
    stub.write_text(
        f"""#!/usr/bin/env bash
case "$*" in
  *"-m breezy.runtime.exec_state_db_path --check"*)
    echo "MATCH"
    exit 0
    ;;
  *"-m breezy.runtime.structural_pin_guard"*)
    exit 0
    ;;
  *)
    printf "%s\\n" "$@" > "{capture}"
    exit 0
    ;;
esac
"""
    )
    stub.chmod(0o755)

    result = _run_wrapper([family_id], tmp_path, stub_python=stub)

    assert result.returncode == 0, result.stderr
    argv_lines = capture.read_text().splitlines()
    assert "--family" in argv_lines
    assert argv_lines[argv_lines.index("--family") + 1] == family_id
    assert "--store-dir" in argv_lines
    assert "--output" in argv_lines
    output_arg = argv_lines[argv_lines.index("--output") + 1]
    assert family_id in output_arg
    # B6: --as-of is passed a UTC date stamp (YYYY-MM-DD).
    assert "--as-of" in argv_lines
    as_of_arg = argv_lines[argv_lines.index("--as-of") + 1]
    assert len(as_of_arg) == len("2026-09-04")
    assert as_of_arg.count("-") == 2


def test_wrapper_never_lists_a_boundary_artefact_json_as_a_valid_family_id(
    tmp_path: Path,
) -> None:
    """B6: `gs_boundary_pm_us_crh_v2.json` sits in the same directory as the
    family manifests but is never itself a family manifest (no `family_id`
    field) -- the wrapper must never accept it as a `--family` value."""
    result = _run_wrapper(["gs_boundary_pm_us_crh_v2"], tmp_path)
    assert result.returncode == 2
    assert "gs_boundary_pm_us_crh_v2" not in _valid_family_ids()


def test_wrapper_exits_nonzero_and_never_invokes_the_tally_when_marker_absent(
    tmp_path: Path,
) -> None:
    stub = tmp_path / "stub_python.sh"
    capture = tmp_path / "argv_capture.txt"
    stub.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$@" >> "{capture}"\nexit 0\n')
    stub.chmod(0o755)

    family_id = min(_valid_family_ids())
    result = _run_wrapper([family_id], tmp_path, stub_python=stub, create_marker=False)

    assert result.returncode != 0
    assert not capture.exists()


def test_wrapper_invokes_the_tally_when_marker_present(tmp_path: Path) -> None:
    stub = tmp_path / "stub_python.sh"
    capture = tmp_path / "argv_capture.txt"
    stub.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "{capture}"\nexit 0\n')
    stub.chmod(0o755)

    family_id = min(_valid_family_ids())
    result = _run_wrapper([family_id], tmp_path, stub_python=stub, create_marker=True)

    assert result.returncode == 0, result.stderr
    assert capture.exists()


def test_wrapper_reports_failure_from_the_stub_analysis_script(tmp_path: Path) -> None:
    stub = tmp_path / "stub_python.sh"
    stub.write_text("#!/usr/bin/env bash\nexit 1\n")
    stub.chmod(0o755)

    family_id = min(_valid_family_ids())
    result = _run_wrapper([family_id], tmp_path, stub_python=stub)

    assert result.returncode == 1


@pytest.mark.parametrize(
    "service_name,timer_name,family_id",
    [
        ("breezy-pm-crh-v2-tally.service", "breezy-pm-crh-v2-tally.timer", "pm_us_crh_v2"),
    ],
)
def test_concrete_unit_pair_exists_and_wires_to_wrapper(
    service_name: str, timer_name: str, family_id: str
) -> None:
    service_path = _SYSTEMD_DIR / service_name
    timer_path = _SYSTEMD_DIR / timer_name
    assert service_path.exists()
    assert timer_path.exists()

    service_text = service_path.read_text()
    exec_start_lines = [line for line in service_text.splitlines() if line.startswith("ExecStart=")]
    assert len(exec_start_lines) == 1
    assert "family-tally-v2-run.sh" in exec_start_lines[0]
    assert exec_start_lines[0].strip().endswith(family_id)

    timer_text = timer_path.read_text()
    assert f"Unit={service_name}" in timer_text


def test_pm_crh_v2_timer_fires_at_1715_utc() -> None:
    timer_text = (_SYSTEMD_DIR / "breezy-pm-crh-v2-tally.timer").read_text()
    assert "OnCalendar=*-*-* 17:15:00 UTC" in timer_text


def test_pm_crh_v2_tally_tick_is_after_node_launch() -> None:
    """A1: parse OnCalendar= and require the tick at/after launch-window end.

    Compares the parsed ``dt.time`` to ``LAUNCH_WINDOW_END_UTC`` (not a
    restated 16:50 literal). RED while the timer still fires at 15:30.
    """
    timer_text = (_SYSTEMD_DIR / "breezy-pm-crh-v2-tally.timer").read_text()
    match = re.search(
        r"^OnCalendar=\S+\s+(\d{2}):(\d{2}):(\d{2})\s+UTC\s*$",
        timer_text,
        re.MULTILINE,
    )
    assert match is not None, "breezy-pm-crh-v2-tally.timer has no parseable OnCalendar="
    tick = _dt.time(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    assert tick >= LAUNCH_WINDOW_END_UTC


def _write_counter_json(
    tmp_path: Path, *, fetch_start: str = "2026-09-05", count: int = 20
) -> Path:
    out = tmp_path / "derived"
    out.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%d")
    payload = {
        "count": count,
        "depth_root_present": True,
        "fetch_end": fetch_start,
        "fetch_start": fetch_start,
        "manifest_sha256": "b" * 64,
        "stations": ["LAX", "MDW", "MIA", "SFO"],
    }
    path = out / f"covered_listed_station_days_{stamp}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return path


def test_wrapper_passes_covered_listed_and_fill_source(tmp_path: Path) -> None:
    """pm_us_crh_v2 only: same-day JSON + POLYMARKET_US_EXEC_STATE_DB + d0."""
    capture = tmp_path / "argv_capture.txt"
    stub = tmp_path / "stub_python.sh"
    stub.write_text(
        f"""#!/usr/bin/env bash
case "$*" in
  *"-m breezy.runtime.exec_state_db_path --check"*)
    echo "MATCH"
    exit 0
    ;;
  *"-m breezy.runtime.structural_pin_guard"*)
    exit 0
    ;;
  *)
    printf "%s\\n" "$@" > "{capture}"
    exit 0
    ;;
esac
"""
    )
    stub.chmod(0o755)
    _write_counter_json(tmp_path, count=42, fetch_start="2026-09-05")
    result = _run_wrapper(
        ["pm_us_crh_v2"],
        tmp_path,
        stub_python=stub,
        set_state_db=True,
        write_counter_json=False,
    )
    assert result.returncode == 0, result.stderr
    argv_lines = capture.read_text().splitlines()
    assert "--covered-listed-station-days" in argv_lines
    assert argv_lines[argv_lines.index("--covered-listed-station-days") + 1] == "42"
    assert "--fill-source" in argv_lines
    assert argv_lines[argv_lines.index("--fill-source") + 1] == str(
        tmp_path / "state" / "exec_polymarket_us.sqlite"
    )
    assert "--fill-since-climate-day" in argv_lines
    assert argv_lines[argv_lines.index("--fill-since-climate-day") + 1] == "2026-09-05"

    kalshi_capture = tmp_path / "kalshi_argv.txt"
    kalshi_stub = tmp_path / "kalshi_stub.sh"
    kalshi_stub.write_text(
        f'#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "{kalshi_capture}"\nexit 0\n'
    )
    kalshi_stub.chmod(0o755)
    kalshi = _run_wrapper(["kalshi_crh_v1"], tmp_path, stub_python=kalshi_stub)
    assert kalshi.returncode == 0, kalshi.stderr
    kalshi_argv = kalshi_capture.read_text().splitlines()
    assert "--covered-listed-station-days" not in kalshi_argv
    assert "--fill-source" not in kalshi_argv
    assert "--fill-since-climate-day" not in kalshi_argv


def test_wrapper_skips_when_counter_json_absent(tmp_path: Path) -> None:
    capture = tmp_path / "argv_capture.txt"
    stub = tmp_path / "stub_python.sh"
    stub.write_text(
        f"""#!/usr/bin/env bash
case "$*" in
  *"-m breezy.runtime.exec_state_db_path --check"*)
    echo "MATCH"
    exit 0
    ;;
  *"-m breezy.runtime.structural_pin_guard"*)
    exit 0
    ;;
  *)
    printf "%s\\n" "$@" > "{capture}"
    exit 0
    ;;
esac
"""
    )
    stub.chmod(0o755)
    result = _run_wrapper(
        ["pm_us_crh_v2"],
        tmp_path,
        stub_python=stub,
        set_state_db=True,
        write_counter_json=False,
    )
    assert result.returncode != 0
    assert not capture.exists()


def _wrapper_output_blob(result: subprocess.CompletedProcess[str], tmp_path: Path) -> str:
    log_path = tmp_path / "derived" / "family_tally_v2.log"
    log_text = log_path.read_text() if log_path.exists() else ""
    return f"{result.stdout}{result.stderr}{log_text}"


def test_pm_wrapper_exits_nonzero_and_does_not_invoke_tally_when_check_returns_no_node(
    tmp_path: Path,
) -> None:
    capture = tmp_path / "argv_capture.txt"
    stub = tmp_path / "stub_python.sh"
    stub.write_text(
        f"""#!/usr/bin/env bash
case "$*" in
  *"-m breezy.runtime.exec_state_db_path --check"*)
    echo "NO_NODE"
    exit 0
    ;;
  *"-m breezy.runtime.structural_pin_guard"*)
    echo "UNAVAILABLE token='NO_NODE'" >&2
    exit 1
    ;;
  *)
    printf "%s\\n" "$@" > "{capture}"
    exit 0
    ;;
esac
"""
    )
    stub.chmod(0o755)
    result = _run_wrapper(
        ["pm_us_crh_v2"],
        tmp_path,
        stub_python=stub,
        set_state_db=True,
    )
    blob = _wrapper_output_blob(result, tmp_path)
    assert result.returncode != 0
    assert "UNAVAILABLE" in blob or "PRE_LAUNCH" in blob
    assert "NO_NODE" in blob
    assert not capture.exists()


def test_pm_wrapper_exits_nonzero_and_does_not_invoke_tally_when_check_refuses(
    tmp_path: Path,
) -> None:
    """Non-zero --check (token 'refused') must fail-loud: no sequential tally."""
    capture = tmp_path / "argv_capture.txt"
    stub = tmp_path / "stub_python.sh"
    stub.write_text(
        f"""#!/usr/bin/env bash
case "$*" in
  *"-m breezy.runtime.exec_state_db_path --check"*)
    exit 1
    ;;
  *"-m breezy.runtime.structural_pin_guard"*)
    echo "UNAVAILABLE token='refused'" >&2
    exit 1
    ;;
  *)
    printf "%s\\n" "$@" > "{capture}"
    exit 0
    ;;
esac
"""
    )
    stub.chmod(0o755)
    result = _run_wrapper(
        ["pm_us_crh_v2"],
        tmp_path,
        stub_python=stub,
        set_state_db=True,
    )
    blob = _wrapper_output_blob(result, tmp_path)
    assert result.returncode != 0
    assert "UNAVAILABLE" in blob or "PRE_LAUNCH" in blob
    assert "refused" in blob
    assert not capture.exists()


def test_pm_wrapper_mismatch_exits_1_and_does_not_pass_fill_source(
    tmp_path: Path,
) -> None:
    """A7/A12: --check exit 3 (MISMATCH) → wrapper exit 1, no --fill-source."""
    capture = tmp_path / "argv_capture.txt"
    stub = tmp_path / "stub_python.sh"
    stub.write_text(
        f"""#!/usr/bin/env bash
case "$*" in
  *"-m breezy.runtime.exec_state_db_path --check"*)
    echo "MISMATCH"
    exit 3
    ;;
  *"-m breezy.runtime.structural_pin_guard"*)
    echo "UNAVAILABLE token='refused'" >&2
    exit 1
    ;;
  *)
    printf "%s\\n" "$@" > "{capture}"
    exit 0
    ;;
esac
"""
    )
    stub.chmod(0o755)
    other_db = tmp_path / "other" / "exec_polymarket_us.sqlite"
    result = _run_wrapper(
        ["pm_us_crh_v2"],
        tmp_path,
        stub_python=stub,
        set_state_db=True,
        state_db=other_db,
    )
    assert result.returncode == 1
    assert not capture.exists()


def test_pm_wrapper_invokes_structural_pin_guard_then_tally_on_match(
    tmp_path: Path,
) -> None:
    tally_capture = tmp_path / "tally_argv.txt"
    guard_capture = tmp_path / "guard_argv.txt"
    stub = tmp_path / "stub_python.sh"
    stub.write_text(
        f"""#!/usr/bin/env bash
case "$*" in
  *"-m breezy.runtime.exec_state_db_path --check"*)
    echo "MATCH"
    exit 0
    ;;
  *"-m breezy.runtime.structural_pin_guard"*)
    printf "%s\\n" "$@" > "{guard_capture}"
    exit 0
    ;;
  *)
    printf "%s\\n" "$@" > "{tally_capture}"
    exit 0
    ;;
esac
"""
    )
    stub.chmod(0o755)
    result = _run_wrapper(
        ["pm_us_crh_v2"],
        tmp_path,
        stub_python=stub,
        set_state_db=True,
    )
    assert result.returncode == 0, result.stderr
    assert guard_capture.exists()
    guard_argv = guard_capture.read_text().splitlines()
    assert "--family" in guard_argv
    assert guard_argv[guard_argv.index("--family") + 1] == "pm_us_crh_v2"
    assert "--token" in guard_argv
    assert guard_argv[guard_argv.index("--token") + 1] == "MATCH"
    tally_argv = tally_capture.read_text().splitlines()
    assert "--covered-listed-station-days" in tally_argv
    assert "--fill-source" in tally_argv
    assert "--fill-since-climate-day" in tally_argv
    assert tally_argv[tally_argv.index("--fill-since-climate-day") + 1] == "2026-09-05"


def test_kalshi_crh_unit_pair_is_parked_off_main(tmp_path: Path) -> None:
    # breezy-kalshi-crh-tally.{service,timer} moved to wip/kalshi-s4-registry
    # per the 2026-09-04 operator priority (PM-only until PM is working).
    # The manifest itself still exists on disk, so the wrapper must keep
    # listing kalshi_crh_v1 as a valid family id even with no unit for it.
    assert not (_SYSTEMD_DIR / "breezy-kalshi-crh-tally.service").exists()
    assert not (_SYSTEMD_DIR / "breezy-kalshi-crh-tally.timer").exists()
    assert "kalshi_crh_v1" in _valid_family_ids()
