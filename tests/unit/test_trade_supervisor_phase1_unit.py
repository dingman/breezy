"""G1/G2 (plan rev 6.1) + review item 2: the Phase 1 deploy artefact.

`deploy/systemd/breezy-trade-supervisor.service.phase1` is a NEW, UNINSTALLED
sibling of the installed `breezy-trade-supervisor.service` unit -- this
module never reads from or writes to any INSTALLED systemd unit path, never
runs `daemon-reload`, and never starts/stops/restarts any service.

It differs from the installed unit by EXACTLY three lines:
`Environment=BREEZY_CURRENT_RUNG_HOLD=1` removed,
`Environment=BREEZY_CONTINUOUS_RUNG_HOLD=1` added -- the shadow-mode
v3-only launch profile for Phase 1's `continuous_rung_hold` family -- and a
NEW `Environment=BREEZY_CRH_CONT_PHASE0_SHADOW=0` line, added review item 2
(MEDIUM): the shadow flag is documented build-side but nothing previously
fenced it from an `operator.env` line of the same name. Pinning it via an
`Environment=` line placed AFTER `EnvironmentFile=-%h/breezy/operator.env`
exploits systemd's own last-one-wins `Environment=`/`EnvironmentFile=`
ordering, so a stray `BREEZY_CRH_CONT_PHASE0_SHADOW=1` planted in
`operator.env` can never win over this build-side `=0`.

The THIRD line is a pure addition (no removal counterpart): the installed
unit does not yet carry it. The installed unit is expected to gain the SAME
line at cut time -- a coordinator step, out of this seam's scope and this
module's reach (this module never touches the installed unit).
"""

from __future__ import annotations

import difflib
import shutil
import subprocess
from pathlib import Path

import pytest

_DEPLOY_DIR = Path(__file__).resolve().parents[2] / "deploy" / "systemd"
_INSTALLED_UNIT = _DEPLOY_DIR / "breezy-trade-supervisor.service"
_PHASE1_UNIT = _DEPLOY_DIR / "breezy-trade-supervisor.service.phase1"

_SYSTEMD_ANALYZE = shutil.which("systemd-analyze")

_EXPECTED_REMOVED = "Environment=BREEZY_CURRENT_RUNG_HOLD=1"
_EXPECTED_REPLACEMENT_ADDED = "Environment=BREEZY_CONTINUOUS_RUNG_HOLD=1"
_EXPECTED_SHADOW_PIN_ADDED = "Environment=BREEZY_CRH_CONT_PHASE0_SHADOW=0"
_OPERATOR_ENV_LINE = "EnvironmentFile=-%h/breezy/operator.env"


def test_phase1_unit_files_both_exist() -> None:
    assert _INSTALLED_UNIT.is_file()
    assert _PHASE1_UNIT.is_file()


def test_phase1_unit_differs_from_the_installed_unit_by_exactly_three_lines() -> None:
    installed_lines = _INSTALLED_UNIT.read_text().splitlines()
    phase1_lines = _PHASE1_UNIT.read_text().splitlines()

    diff = list(difflib.unified_diff(installed_lines, phase1_lines, lineterm="", n=0))
    changed = [
        line
        for line in diff
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    ]

    assert changed == [
        f"-{_EXPECTED_REMOVED}",
        f"+{_EXPECTED_REPLACEMENT_ADDED}",
        f"+{_EXPECTED_SHADOW_PIN_ADDED}",
    ]


def test_phase1_unit_removes_current_rung_hold_and_adds_continuous_rung_hold() -> None:
    installed_text = _INSTALLED_UNIT.read_text()
    phase1_text = _PHASE1_UNIT.read_text()

    assert _EXPECTED_REMOVED in installed_text
    assert _EXPECTED_REMOVED not in phase1_text
    assert _EXPECTED_REPLACEMENT_ADDED not in installed_text
    assert _EXPECTED_REPLACEMENT_ADDED in phase1_text

    # Every other `Environment=` line is byte-identical between the two
    # units -- only the rung-hold flag swap and the new shadow-pin addition
    # differ.
    installed_env_lines = {
        line
        for line in installed_text.splitlines()
        if line.startswith("Environment=") and line != _EXPECTED_REMOVED
    }
    phase1_env_lines = {
        line
        for line in phase1_text.splitlines()
        if line.startswith("Environment=")
        and line not in (_EXPECTED_REPLACEMENT_ADDED, _EXPECTED_SHADOW_PIN_ADDED)
    }
    assert installed_env_lines == phase1_env_lines


def test_phase1_unit_pins_the_phase0_shadow_flag_off_after_operator_env() -> None:
    """Review item 2 (MEDIUM): the shadow flag must be fenced from
    `operator.env`, not merely documented as build-side.

    No dedicated `operator.env` key VALIDATOR exists in `src/` -- verified by
    grepping every reference to ``operator.env`` in `src/`: only
    `operator_controls.py`'s own docstring names it, and that module reads
    exactly the two operator-reserved caps by name (never parses the file's
    key set). Commit 4a94d8a's "unknown operator.env keys are still
    rejected" describes exactly this property -- an unrecognised key is
    simply never consulted by any reader, not validated by a dedicated
    parser or allowlist module -- so there is no separate validator to widen
    with the shadow key here. The fence for THIS key is therefore the
    `Environment=` line ordering asserted below, matching every other
    build-side constant in this block.
    """
    lines = _PHASE1_UNIT.read_text().splitlines()
    operator_env_index = lines.index(_OPERATOR_ENV_LINE)
    shadow_pin_index = lines.index(_EXPECTED_SHADOW_PIN_ADDED)
    assert shadow_pin_index > operator_env_index


@pytest.mark.skipif(_SYSTEMD_ANALYZE is None, reason="systemd-analyze not on PATH")
def test_phase1_unit_verifies_with_systemd_analyze(tmp_path: Path) -> None:
    """`systemd-analyze verify` requires a filename with a recognised unit
    suffix (`.service`) -- the `.phase1` artefact is copied, byte-for-byte,
    to a temp path with that suffix before verification. This NEVER installs
    or mutates the real unit file, and never touches the systemd user unit
    directory."""
    assert _SYSTEMD_ANALYZE is not None  # narrows for mypy; skipif already guards this
    candidate = tmp_path / "breezy-trade-supervisor.service"
    candidate.write_text(_PHASE1_UNIT.read_text())

    result = subprocess.run(
        [_SYSTEMD_ANALYZE, "verify", "--user", str(candidate)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
