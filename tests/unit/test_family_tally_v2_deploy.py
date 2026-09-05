"""RED-first suite for build-order commit 8 of
`docs/plans/FAMILY_TALLY_V2_BLUEPRINT_2026-09-04.md`: the family-tally-v2
systemd deploy surface. The CLI (`scripts/analysis/family_tally_v2.py`) is
built in a parallel commit and is deliberately NOT invoked here -- the
wrapper's own test stubs `python` so id validation and argv construction are
verified without it.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

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
    family_arg: list[str], tmp_path: Path, *, stub_python: Path | None = None
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["BREEZY_SCORED_TRIALS_DIR"] = str(tmp_path / "scored_trials")
    env["BREEZY_LIVE_TALLY_OUTPUT_DIR"] = str(tmp_path / "derived")
    if stub_python is not None:
        env["BREEZY_FAMILY_TALLY_V2_PYTHON"] = str(stub_python)
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
    stub.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "{capture}"\nexit 0\n')
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


def test_pm_crh_v2_timer_fires_at_1530_utc() -> None:
    timer_text = (_SYSTEMD_DIR / "breezy-pm-crh-v2-tally.timer").read_text()
    assert "OnCalendar=*-*-* 15:30:00 UTC" in timer_text


def test_kalshi_crh_unit_pair_is_parked_off_main(tmp_path: Path) -> None:
    # breezy-kalshi-crh-tally.{service,timer} moved to wip/kalshi-s4-registry
    # per the 2026-09-04 operator priority (PM-only until PM is working).
    # The manifest itself still exists on disk, so the wrapper must keep
    # listing kalshi_crh_v1 as a valid family id even with no unit for it.
    assert not (_SYSTEMD_DIR / "breezy-kalshi-crh-tally.service").exists()
    assert not (_SYSTEMD_DIR / "breezy-kalshi-crh-tally.timer").exists()
    assert "kalshi_crh_v1" in _valid_family_ids()
