"""G1/G2 (plan rev 6.1) + review item 2, POST-CUT (2026-09-12, d0), migrated
by WP-11b (active-family registry, cardinality-1, 2026-09-19): the installed
`deploy/systemd/breezy-trade-supervisor.service` (symlinked into
~/.config/systemd/user) now carries ONE `BREEZY_SENDING_FAMILY_ID` value
naming the live family, replacing the retired
`BREEZY_CURRENT_RUNG_HOLD`/`BREEZY_CONTINUOUS_RUNG_HOLD` boolean pair. These
pins hold the post-WP-11b state so nobody reintroduces either retired
boolean by accident, and so a promotion (changing ONLY this value) is
visible in a diff. This module never runs `daemon-reload` or touches any
service.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from breezy.runtime.settings import SENDING_FAMILY_ID_VAR

_DEPLOY_DIR = Path(__file__).resolve().parents[2] / "deploy" / "systemd"
_INSTALLED_UNIT = _DEPLOY_DIR / "breezy-trade-supervisor.service"

_SYSTEMD_ANALYZE = shutil.which("systemd-analyze")

_EXPECTED_REMOVED_CURRENT = "Environment=BREEZY_CURRENT_RUNG_HOLD=1"
_EXPECTED_REMOVED_CONTINUOUS = "Environment=BREEZY_CONTINUOUS_RUNG_HOLD=1"
_EXPECTED_REPLACEMENT_ADDED = "Environment=BREEZY_SENDING_FAMILY_ID=pm_us_crh_cont"
_EXPECTED_SHADOW_PIN_ADDED = "Environment=BREEZY_CRH_CONT_PHASE0_SHADOW=0"
_OPERATOR_ENV_LINE = "EnvironmentFile=-%h/breezy/operator.env"


def test_installed_unit_exists() -> None:
    assert _INSTALLED_UNIT.is_file()


def test_installed_unit_runs_the_registered_sending_family_by_id() -> None:
    lines = _INSTALLED_UNIT.read_text().splitlines()
    assert _EXPECTED_REPLACEMENT_ADDED in lines
    assert _EXPECTED_REMOVED_CURRENT not in lines
    assert _EXPECTED_REMOVED_CONTINUOUS not in lines
    assert lines.count(_EXPECTED_REPLACEMENT_ADDED) == 1

    # Gap closed (independent review, MEDIUM, 2026-09-19): the assertions
    # above pin the env-var NAME as a bare literal, so a future rename of
    # `breezy.runtime.settings.SENDING_FAMILY_ID_VAR` with no matching edit
    # to this systemd unit would drift silently -- this test would keep
    # passing against the OLD name. Derive the prefix from the constant
    # itself so a rename on either side (settings.py or the unit file)
    # without the other shows up here.
    derived_prefix = f"Environment={SENDING_FAMILY_ID_VAR}="
    matched = [line for line in lines if line.startswith(derived_prefix)]
    assert matched == [_EXPECTED_REPLACEMENT_ADDED]


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
