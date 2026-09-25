"""AUD-09b review fix 1 (CRITICAL) -- mirror of `test_portfolio_roi_alert_env.py`,
scoped to `breezy-replay-daily.service`.

Without a declared `EnvironmentFile=`, `breezy.runtime.health.
resolve_alert_sink` always resolves a LOG-ONLY sink on this host (the
`BREEZY_ALERT_WEBHOOK_URL` process environment is never populated) --
detection without delivery, the exact defect `f97c26f` was raised to
close. This module pins the fix at the unit-text level.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_DEPLOY_DIR: Final[Path] = _REPO_ROOT / "deploy" / "systemd"
_REPLAY_DAILY_UNIT: Final[Path] = _DEPLOY_DIR / "breezy-replay-daily.service"

_PERMITTED_ENV_FILES: Final[frozenset[str]] = frozenset({"%h/.config/breezy/alerts.env"})
_FORBIDDEN_ENV_SUBSTRINGS: Final[tuple[str, ...]] = (
    "breezy-trade.env",
    "polymarket.env",
    "operator.env",
)


def _directive_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if not line.strip().startswith("#")]


def test_the_replay_daily_unit_declares_only_the_allowlisted_alert_env_file() -> None:
    lines = _directive_lines(_REPLAY_DAILY_UNIT.read_text())
    env_files = [
        line.removeprefix("EnvironmentFile=").lstrip("-")
        for line in lines
        if line.startswith("EnvironmentFile=")
    ]
    assert set(env_files) == _PERMITTED_ENV_FILES
    assert not any(
        forbidden in env_file for env_file in env_files for forbidden in _FORBIDDEN_ENV_SUBSTRINGS
    )


def test_the_replay_daily_unit_env_file_prefix_keeps_it_startable_when_absent() -> None:
    """The `-` prefix on `EnvironmentFile=-%h/...` is load-bearing: without
    it, a host that has not yet run `migrate-alerts-env.sh` would refuse to
    start this unit at all rather than degrading to a logged warning."""
    lines = _directive_lines(_REPLAY_DAILY_UNIT.read_text())
    env_file_lines = [line for line in lines if line.startswith("EnvironmentFile=")]
    assert len(env_file_lines) == 1
    assert env_file_lines[0].startswith("EnvironmentFile=-")
