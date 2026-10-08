"""AUT-6 WP3 S1: the FQ skip of ``score-live-trials-run.sh`` leaves a skip marker.

The composition skip (forecast_quantile_ladder has no score_live_trials) exits 0
and must say WHY in a durable, closed-vocabulary marker that
``portfolio-roi-run.sh`` reads, so the downstream ROI wrapper reports NO_INPUT
instead of failing on a missing success marker. An absent sending-family id is
NOT a legitimate skip: it stays exit 1 and writes no skip marker.
"""

from __future__ import annotations

import datetime as _dt
import os
import shlex
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WRAPPER = _REPO_ROOT / "deploy" / "systemd" / "score-live-trials-run.sh"
_FAMILIES_DIR = _REPO_ROOT / "deploy" / "families"
_FQ_FAMILY = "pm_us_crh_fq_v1"


def _stamp() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%d")


def _run(tmp_path: Path, environment_line: str) -> subprocess.CompletedProcess[str]:
    py = tmp_path / "py.sh"
    py.write_text("#!/usr/bin/env bash\necho NO_NODE\nexit 0\n")
    py.chmod(0o755)
    systemctl = tmp_path / "systemctl.sh"
    systemctl.write_text(f"#!/usr/bin/env bash\nprintf '%s\\n' {shlex.quote(environment_line)}\n")
    systemctl.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update(
        HOME=str(home),
        BREEZY_SCORED_TRIALS_DIR=str(tmp_path / "scored"),
        BREEZY_LIVE_TALLY_OUTPUT_DIR=str(tmp_path / "derived"),
        BREEZY_SCORE_LIVE_TRIALS_FAMILIES_DIR=str(_FAMILIES_DIR),
        BREEZY_SCORE_LIVE_TRIALS_PYTHON=str(py),
        BREEZY_SYSTEMCTL=str(systemctl),
        POLYMARKET_US_EXEC_STATE_DB=str(tmp_path / "state.sqlite3"),
    )
    return subprocess.run(
        ["bash", str(_WRAPPER)],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _skip_marker(tmp_path: Path) -> Path:
    return tmp_path / "derived" / f"score_live_trials_ok_{_stamp()}.skipped"


def test_fq_skip_writes_skip_marker_with_closed_reason(tmp_path: Path) -> None:
    result = _run(tmp_path, f"Environment=BREEZY_SENDING_FAMILY_ID={_FQ_FAMILY}")

    assert result.returncode == 0, result.stderr
    assert _skip_marker(tmp_path).read_text() == "reason=composition_kind_has_no_scorer\n"
    assert not (tmp_path / "derived" / f"score_live_trials_ok_{_stamp()}").exists()


def test_stale_skip_marker_is_removed_by_a_later_non_skip_run(tmp_path: Path) -> None:
    first = _run(tmp_path, f"Environment=BREEZY_SENDING_FAMILY_ID={_FQ_FAMILY}")
    assert first.returncode == 0
    assert _skip_marker(tmp_path).exists()

    second = _run(tmp_path, "Environment=OTHER=1")

    assert second.returncode != 0
    assert not _skip_marker(tmp_path).exists()


def test_absent_sending_family_id_is_a_failure_with_no_skip_marker(tmp_path: Path) -> None:
    result = _run(tmp_path, "Environment=OTHER=1")

    assert result.returncode != 0
    assert not _skip_marker(tmp_path).exists()


def test_unwritable_skip_marker_exits_one_with_a_clear_line_and_no_marker(
    tmp_path: Path,
) -> None:
    """The marker is written tmp-then-mv and the write is checked: if it cannot
    land, the wrapper must fail loudly (exit 1) rather than exit 0 with no
    marker (which would make portfolio-roi report a misleading missing-success
    failure far downstream). The marker path is pre-occupied by a non-empty
    directory so ``rm -f`` leaves it and ``mv -T`` cannot replace it."""
    blocker = _skip_marker(tmp_path)
    (blocker / "keep").mkdir(parents=True)

    result = _run(tmp_path, f"Environment=BREEZY_SENDING_FAMILY_ID={_FQ_FAMILY}")

    assert result.returncode == 1, result.stderr
    assert not blocker.is_file()
    log_text = (tmp_path / "derived" / "score_live_trials.log").read_text()
    assert "SCORE LIVE TRIALS FAILED -- cannot write the skip marker" in log_text
    assert not list((tmp_path / "derived").glob("*.skipped.tmp.*"))
