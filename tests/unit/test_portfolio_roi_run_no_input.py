"""AUT-6 WP3 S1: ``portfolio-roi-run.sh`` reads the score-live-trials skip marker.

``score-live-trials-run.sh`` SKIPs a forecast_quantile_ladder sending family by
design and writes ``score_live_trials_ok_<date>.skipped`` (one closed
``reason=`` line) instead of the success marker. The ROI wrapper must treat that
as NO_INPUT (exit 0, journal line), while a truly absent marker, or a marker
carrying a reason outside the closed set, stays a failure (exit 1).
"""

from __future__ import annotations

import datetime as _dt
import os
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WRAPPER = _REPO_ROOT / "deploy" / "systemd" / "portfolio-roi-run.sh"
_CLOSED_REASON = "composition_kind_has_no_scorer"


def _stamp() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%d")


def _stub(tmp_path: Path) -> tuple[Path, Path]:
    capture = tmp_path / "argv_capture.txt"
    stub = tmp_path / "stub_python.sh"
    stub.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "{capture}"\nexit 0\n')
    stub.chmod(0o755)
    return stub, capture


def _run(
    tmp_path: Path,
    stub: Path,
    *,
    skip_marker_text: str | None = None,
    ok_marker: bool = False,
) -> subprocess.CompletedProcess[str]:
    out_dir = tmp_path / "derived"
    out_dir.mkdir(parents=True, exist_ok=True)
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    if ok_marker:
        (out_dir / f"score_live_trials_ok_{_stamp()}").touch()
    if skip_marker_text is not None:
        (out_dir / f"score_live_trials_ok_{_stamp()}.skipped").write_text(skip_marker_text)
    env = dict(os.environ)
    env["BREEZY_LIVE_TALLY_OUTPUT_DIR"] = str(out_dir)
    env["BREEZY_PORTFOLIO_ROI_PYTHON"] = str(stub)
    env["XDG_RUNTIME_DIR"] = str(run_dir)
    return subprocess.run(
        ["bash", str(_WRAPPER)],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_skip_marker_gives_no_input_exit_0(tmp_path: Path) -> None:
    stub, capture = _stub(tmp_path)

    result = _run(tmp_path, stub, skip_marker_text=f"reason={_CLOSED_REASON}\n")

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"PORTFOLIO ROI NO_INPUT -- upstream skipped: {_CLOSED_REASON}" in result.stdout
    assert not capture.exists()


def test_absent_markers_still_exit_1(tmp_path: Path) -> None:
    stub, capture = _stub(tmp_path)

    result = _run(tmp_path, stub)

    assert result.returncode == 1
    assert "no score-live-trials success marker" in result.stdout
    assert "NO_INPUT" not in result.stdout
    assert not capture.exists()


def test_skip_marker_with_unknown_reason_is_not_trusted(tmp_path: Path) -> None:
    stub, capture = _stub(tmp_path)

    result = _run(tmp_path, stub, skip_marker_text="reason=because_i_said_so\n")

    assert result.returncode == 1
    assert "NO_INPUT" not in result.stdout
    assert not capture.exists()


def test_skip_marker_with_trailing_junk_is_not_trusted(tmp_path: Path) -> None:
    stub, _ = _stub(tmp_path)

    result = _run(
        tmp_path, stub, skip_marker_text=f"reason={_CLOSED_REASON}\nreason={_CLOSED_REASON}\n"
    )

    assert result.returncode == 1


def test_success_marker_wins_over_a_skip_marker(tmp_path: Path) -> None:
    stub, capture = _stub(tmp_path)

    result = _run(tmp_path, stub, skip_marker_text=f"reason={_CLOSED_REASON}\n", ok_marker=True)

    assert result.returncode == 0, result.stdout + result.stderr
    assert capture.exists()
    assert "NO_INPUT" not in result.stdout
