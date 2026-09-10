"""GL-14/BL-24: the new frequent ingest timer must be syntactically valid.

``breezy-quote-tape-ingest-frequent.timer`` fires the SAME
``breezy-quote-tape-ingest.service`` the pre-existing 6-hourly timer already
triggers, at a 15-minute cadence -- see that timer file's own comments and
the ingest module's "Per-file conversion (GL-14/BL-24)" docstring section
for why a shorter interval is now safe (idempotent per file, not per whole
instance).

This file is deliberately NOT installed or enabled by this change --
``systemctl --user enable`` is an operator step, not a test-time side
effect. This test only proves the unit-file SYNTAX is valid, via
``systemd-analyze verify``, the authoritative parser for it -- skipped
(never failed) when the binary is absent, since this suite must also run on
a host with no systemd.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TIMER_PATH = _REPO_ROOT / "deploy" / "systemd" / "breezy-quote-tape-ingest-frequent.timer"
_SERVICE_PATH = _REPO_ROOT / "deploy" / "systemd" / "breezy-quote-tape-ingest.service"

_SYSTEMD_ANALYZE = shutil.which("systemd-analyze")


def test_the_timer_and_service_files_exist() -> None:
    # A missing file would otherwise make the (possibly skipped) verify
    # test below silently prove nothing.
    assert _TIMER_PATH.is_file()
    assert _SERVICE_PATH.is_file()


def test_the_timer_targets_the_existing_ingest_service_not_a_new_one() -> None:
    # The existing service is reused verbatim (its ExecStart, safety
    # comments, and idempotency guarantees are unchanged) -- this pins that
    # no `breezy-quote-tape-ingest-frequent.service` was introduced.
    text = _TIMER_PATH.read_text()
    assert "Unit=breezy-quote-tape-ingest.service" in text
    frequent_service = (
        _REPO_ROOT / "deploy" / "systemd" / "breezy-quote-tape-ingest-frequent.service"
    )
    assert not frequent_service.exists()


@pytest.mark.skipif(_SYSTEMD_ANALYZE is None, reason="systemd-analyze not on PATH")
def test_systemd_analyze_verify_passes() -> None:
    result = subprocess.run(
        [_SYSTEMD_ANALYZE, "verify", str(_TIMER_PATH), str(_SERVICE_PATH)],  # type: ignore[list-item]
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
