"""AUD-04 / AUD-15 amendment discipline (2026-09-22) -- mirror of
`test_asos_refresh_alert_env.py`'s env-file allowlist test, scoped to
`breezy-portfolio-roi.service`.

The D8 frozen-input ladder and the D9 unsettled-position check (section 6
of `docs/plans/backlog/AUDIT_2026-09-21/AUD-04-portfolio-roi-measurement.md`)
both deliver through the existing shipped alert sink
(`breezy.runtime.health.resolve_alert_sink`), which resolves a real webhook
branch only when `BREEZY_ALERT_WEBHOOK_URL` is present in the process
environment. Without a declared `EnvironmentFile=`, this unit's alerts
would always resolve a LOG-ONLY sink on this host -- detection without
delivery, the exact defect `f97c26f` was raised to close. This module pins
the fix at the unit-text level: exactly one, allowlisted
`EnvironmentFile=`, never the venue/operator files.

The runtime-visibility leg (`log_alert_egress_status` called before
`resolve_alert_sink` on every invocation) is `portfolio_roi_report.py`'s
own responsibility -- a disjoint file built in a parallel commit -- and is
therefore NOT re-asserted here; this module scopes strictly to the unit
TEXT, mirroring `test_asos_refresh_alert_env.py`'s own division of labour
between its unit-text test and its `asos_cache_freshness_check.main` test.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_DEPLOY_DIR: Final[Path] = _REPO_ROOT / "deploy" / "systemd"
_PORTFOLIO_ROI_UNIT: Final[Path] = _DEPLOY_DIR / "breezy-portfolio-roi.service"

_PERMITTED_ENV_FILES: Final[frozenset[str]] = frozenset({"%h/.config/breezy/alerts.env"})
_FORBIDDEN_ENV_SUBSTRINGS: Final[tuple[str, ...]] = (
    "breezy-trade.env",
    "polymarket.env",
    "operator.env",
)


def _directive_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if not line.strip().startswith("#")]


def test_the_portfolio_roi_unit_declares_only_the_allowlisted_alert_env_file() -> None:
    lines = _directive_lines(_PORTFOLIO_ROI_UNIT.read_text())
    env_files = [
        line.removeprefix("EnvironmentFile=").lstrip("-")
        for line in lines
        if line.startswith("EnvironmentFile=")
    ]
    assert set(env_files) == _PERMITTED_ENV_FILES
    assert not any(
        forbidden in env_file for env_file in env_files for forbidden in _FORBIDDEN_ENV_SUBSTRINGS
    )


def test_the_portfolio_roi_unit_env_file_prefix_keeps_it_startable_when_absent() -> None:
    """The `-` prefix on `EnvironmentFile=-%h/...` is load-bearing: without
    it, a host that has not yet run `migrate-alerts-env.sh` would refuse to
    start this unit at all rather than degrading to a logged warning."""
    lines = _directive_lines(_PORTFOLIO_ROI_UNIT.read_text())
    env_file_lines = [line for line in lines if line.startswith("EnvironmentFile=")]
    assert len(env_file_lines) == 1
    assert env_file_lines[0].startswith("EnvironmentFile=-")
