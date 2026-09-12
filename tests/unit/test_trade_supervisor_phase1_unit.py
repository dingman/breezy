"""G1/G2 (plan rev 6.1) + review item 2, POST-CUT (2026-09-12, d0): the
installed `deploy/systemd/breezy-trade-supervisor.service` (symlinked into
~/.config/systemd/user) now carries the Phase 1 `continuous_rung_hold`
launch profile. The former `.phase1` sibling was applied verbatim at the cut
(three `Environment=` line changes) and deleted; these pins hold the
post-cut state so nobody re-enables the frozen v2 family or the shadow
flag by accident. This module never runs `daemon-reload` or touches any
service.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_DEPLOY_DIR = Path(__file__).resolve().parents[2] / "deploy" / "systemd"
_INSTALLED_UNIT = _DEPLOY_DIR / "breezy-trade-supervisor.service"

_SYSTEMD_ANALYZE = shutil.which("systemd-analyze")

_EXPECTED_REMOVED = "Environment=BREEZY_CURRENT_RUNG_HOLD=1"
_EXPECTED_REPLACEMENT_ADDED = "Environment=BREEZY_CONTINUOUS_RUNG_HOLD=1"
_EXPECTED_SHADOW_PIN_ADDED = "Environment=BREEZY_CRH_CONT_PHASE0_SHADOW=0"
_OPERATOR_ENV_LINE = "EnvironmentFile=-%h/breezy/operator.env"


def test_installed_unit_exists() -> None:
    assert _INSTALLED_UNIT.is_file()


def test_installed_unit_runs_the_continuous_family_not_v2() -> None:
    lines = _INSTALLED_UNIT.read_text().splitlines()
    assert _EXPECTED_REPLACEMENT_ADDED in lines
    assert _EXPECTED_REMOVED not in lines
    assert lines.count(_EXPECTED_REPLACEMENT_ADDED) == 1


def test_installed_unit_pins_the_phase0_shadow_flag_off_after_operator_env() -> None:
    """Review item 2 (MEDIUM): the shadow flag is fenced from `operator.env`
    by `Environment=` line ORDER -- the build-side pin comes after the
    `EnvironmentFile=` line so the operator file can never re-enable it."""
    lines = _INSTALLED_UNIT.read_text().splitlines()
    assert lines.count(_EXPECTED_SHADOW_PIN_ADDED) == 1
    assert lines.index(_EXPECTED_SHADOW_PIN_ADDED) > lines.index(_OPERATOR_ENV_LINE)


@pytest.mark.skipif(_SYSTEMD_ANALYZE is None, reason="systemd-analyze not on PATH")
def test_installed_unit_verifies_with_systemd_analyze(tmp_path: Path) -> None:
    candidate = tmp_path / "breezy-trade-supervisor.service"
    candidate.write_text(_INSTALLED_UNIT.read_text())
    result = subprocess.run(
        [_SYSTEMD_ANALYZE, "verify", "--user", str(candidate)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
