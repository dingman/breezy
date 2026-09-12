"""RED/GREEN coverage for `breezy-liveness-watchdog.{service,timer}`
(SP-6 A12, row 17). Text assertions only -- never invokes `systemctl`."""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SYSTEMD_DIR = _REPO_ROOT / "deploy" / "systemd"
_SERVICE = _SYSTEMD_DIR / "breezy-liveness-watchdog.service"
_TIMER = _SYSTEMD_DIR / "breezy-liveness-watchdog.timer"


def _exec_start_line(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("ExecStart="):
            return line
    raise AssertionError("no ExecStart= line found")


def test_timer_period_is_five_minutes() -> None:
    text = _TIMER.read_text()
    assert re.search(r"^OnCalendar=\*:0/5\s*$", text, re.MULTILINE)


def test_unit_contains_no_literal_url() -> None:
    assert not re.search(r"https?://", _SERVICE.read_text())
    assert not re.search(r"https?://", _TIMER.read_text())


def test_execstart_is_a_single_plain_command_with_no_shell() -> None:
    exec_line = _exec_start_line(_SERVICE.read_text())
    for forbidden in ("bash -c", "sh -c", "$(", "`", ";", "|", "&&"):
        assert forbidden not in exec_line, (forbidden, exec_line)
    assert "BREEZY_ALERT_WEBHOOK_URL" not in exec_line


def test_unit_declares_the_alerts_env_with_a_dash_prefix() -> None:
    text = _SERVICE.read_text()
    assert re.search(r"^EnvironmentFile=-.*alerts\.env\s*$", text, re.MULTILINE)


def test_timer_is_not_enabled_by_the_build() -> None:
    """The [Install] section exists (so an OPERATOR can enable it), but
    nothing in this repo runs `systemctl --user enable` -- that is an
    operator-only step (deploy/systemd/README.md)."""
    timer_text = _TIMER.read_text()
    assert "[Install]" in timer_text
    assert "WantedBy=timers.target" in timer_text
    # The service itself carries NO [Install] SECTION HEADER (a prose
    # mention in a comment is fine) -- it is started by the timer only,
    # never enabled directly.
    section_headers = [
        line
        for line in _SERVICE.read_text().splitlines()
        if line.strip().startswith("[") and line.strip().endswith("]")
    ]
    assert "[Install]" not in section_headers
