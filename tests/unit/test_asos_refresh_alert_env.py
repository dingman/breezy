"""AUD-15 amendment (2026-09-22) -- mirror of `test_study_failure_alert.py`'s
env-file discipline, scoped to `breezy-asos-refresh.service` and
`asos_cache_freshness_check.main`.

Contradiction closed: the plan's original "No EnvironmentFile=, no
credential" left `resolve_alert_sink()` resolving a LOG-ONLY sink on this
host, since `BREEZY_ALERT_WEBHOOK_URL` lives only in
`~/.config/breezy/breezy-trade.env`, loaded only by the supervisor. This
module pins the fix: a dedicated, single-key `alerts.env` file, an
allowlist (never the venue/operator files), and the runtime-visibility call
that makes a missing file loud every run rather than silently downgrading.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Final

import pytest

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_DEPLOY_DIR: Final[Path] = _REPO_ROOT / "deploy" / "systemd"
_REFRESH_UNIT: Final[Path] = _DEPLOY_DIR / "breezy-asos-refresh.service"

_PERMITTED_ENV_FILES: Final[frozenset[str]] = frozenset(
    {
        "%h/.config/breezy/alerts.env",
        # AUD-18 (2026-09-25): the MOS closed-day refresh step needs
        # BREEZY_USER_AGENT, which lives in the non-credential breezy.env.
        "%h/.config/breezy/breezy.env",
    }
)
_FORBIDDEN_ENV_SUBSTRINGS: Final[tuple[str, ...]] = (
    "breezy-trade.env",
    "polymarket.env",
    "operator.env",
)


def _directive_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if not line.strip().startswith("#")]


def test_the_asos_refresh_unit_declares_only_the_allowlisted_alert_env_file() -> None:
    lines = _directive_lines(_REFRESH_UNIT.read_text())
    env_files = [
        line.removeprefix("EnvironmentFile=").lstrip("-")
        for line in lines
        if line.startswith("EnvironmentFile=")
    ]
    assert set(env_files) == _PERMITTED_ENV_FILES
    assert not any(
        forbidden in env_file for env_file in env_files for forbidden in _FORBIDDEN_ENV_SUBSTRINGS
    )


def test_breezy_env_is_dash_prefixed_for_step_independence() -> None:
    """AUD-18: a missing `breezy.env` must not stop the independent ASOS
    steps from starting -- only the MOS step, which needs
    `BREEZY_USER_AGENT`, fails loudly (exit 2) when it is absent."""
    lines = _directive_lines(_REFRESH_UNIT.read_text())
    for line in lines:
        if line.startswith("EnvironmentFile=") and line.endswith("breezy.env"):
            assert line.startswith("EnvironmentFile=-"), (
                f"breezy.env must be dash-prefixed for step independence: {line!r}"
            )
            return
    raise AssertionError("no EnvironmentFile= line for breezy.env found")


_WRAPPER: Final[Path] = _DEPLOY_DIR / "asos-refresh-run.sh"

#: Named assumption (N1): the pre-AUD-18 TimeoutStartSec=600 budget for the
#: ASOS refresh (one HTTP GET per site) plus its freshness check. Not
#: re-derived from a live transport timeout -- asos_recent_refresh.py has no
#: single named constant to pin to -- so it is stated here explicitly rather
#: than left as a bare literal.
_ASOS_ASSUMED_BUDGET_S: Final[int] = 600
_MOS_KILL_AFTER_S: Final[int] = 30
_FRESHNESS_CHECKS_MARGIN_S: Final[int] = 60


def _parse_unit_int(text: str, directive: str) -> int:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{directive}="):
            return int(stripped.split("=", 1)[1].strip())
    raise AssertionError(f"no {directive}= line found")


def _parse_wrapper_int(text: str, var: str) -> int:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{var}="):
            return int(stripped.split("=", 1)[1].strip())
    raise AssertionError(f"no {var}= assignment found in the wrapper")


def test_unit_timeout_exceeds_step_bounds() -> None:
    """Mirrors `test_fee_drift_evidence_pull.py`'s own worst-case-bound
    pattern: `TimeoutStartSec` must clear the sum of every step's own bound,
    and the retry wall must sit well under the MOS step's own timeout."""
    scripts_archive_dir = _REPO_ROOT / "scripts" / "archive"
    if str(scripts_archive_dir) not in sys.path:
        sys.path.insert(0, str(scripts_archive_dir))
    from iem_mos_backfill import _MAX_RETRY_WALL_S

    timeout_start_sec = _parse_unit_int(_REFRESH_UNIT.read_text(), "TimeoutStartSec")
    mos_step_timeout_s = _parse_wrapper_int(_WRAPPER.read_text(), "MOS_STEP_TIMEOUT_S")

    assert _MAX_RETRY_WALL_S < mos_step_timeout_s
    assert (
        _ASOS_ASSUMED_BUDGET_S
        + mos_step_timeout_s
        + _MOS_KILL_AFTER_S
        + _FRESHNESS_CHECKS_MARGIN_S
        <= timeout_start_sec
    )


def test_main_logs_alert_egress_status_before_resolving_the_sink_env_variant(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Duplicate assertion, kept beside `test_asos_cache_freshness_check.py`'s
    own copy deliberately -- this file's job is the ENV-FILE story end to
    end for the refresh unit specifically, mirroring the notifier's own
    test file 1:1 so the two units' alert-delivery contracts are reviewable
    side by side."""
    import sys

    scripts_analysis_dir = _REPO_ROOT / "scripts" / "analysis"
    if str(scripts_analysis_dir) not in sys.path:
        sys.path.insert(0, str(scripts_analysis_dir))
    from asos_cache_freshness_check import main

    with caplog.at_level(logging.WARNING, logger="breezy.runtime.health"):
        exit_code = main(["--cache-dir", "/nonexistent-for-this-test"], env={})

    assert exit_code == 0
    assert any(
        "NO alert egress is configured" in record.getMessage() for record in caplog.records
    )
