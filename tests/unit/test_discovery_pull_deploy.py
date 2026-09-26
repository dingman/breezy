"""AUD-02 WP-D1 (r2.1 Blocker A/B, r3.1 F4): the discovery-pull unit contract.

Text-parsing only, same shape as ``test_fee_drift_evidence_pull_deploy.py``
and ``test_deploy_timer_hours.py`` -- this module never runs
``systemctl``/``daemon-reload``.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SYSTEMD_DIR = _REPO_ROOT / "deploy" / "systemd"
_SERVICE = _SYSTEMD_DIR / "breezy-discovery-pull.service"
_TIMER = _SYSTEMD_DIR / "breezy-discovery-pull.timer"


def _directive_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if not line.strip().startswith("#")]


def _directive(text: str, name: str) -> list[str]:
    prefix = f"{name}="
    return [line for line in _directive_lines(text) if line.startswith(prefix)]


def test_unit_and_timer_exist() -> None:
    assert _SERVICE.is_file()
    assert _TIMER.is_file()


def test_unit_is_oneshot() -> None:
    lines = _directive_lines(_SERVICE.read_text())
    assert "Type=oneshot" in lines


def test_memory_max_is_at_most_256m() -> None:
    lines = _directive(_SERVICE.read_text(), "MemoryMax")
    assert lines == ["MemoryMax=256M"]


def test_never_takes_the_studies_flock_or_slice() -> None:
    text = _SERVICE.read_text()
    lines = _directive_lines(text)
    assert not any(line.startswith("Slice=") for line in lines)
    exec_start = _directive(text, "ExecStart")
    assert len(exec_start) == 1
    assert "flock" not in exec_start[0]
    assert "studies" not in exec_start[0]


def test_timeout_start_sec_is_1800() -> None:
    lines = _directive(_SERVICE.read_text(), "TimeoutStartSec")
    assert lines == ["TimeoutStartSec=1800"]


def test_protect_home_read_only_with_matching_read_write_path() -> None:
    text = _SERVICE.read_text()
    lines = _directive_lines(text)
    protect_home = [line for line in lines if line.startswith("ProtectHome=")]
    read_write = [line for line in lines if line.startswith("ReadWritePaths=")]
    assert protect_home == ["ProtectHome=read-only"]
    assert read_write == ["ReadWritePaths=/home/jon/breezy/data/evidence/discovery_set_equality"]


def test_service_declares_breezy_env_required_and_alerts_env_optional() -> None:
    lines = _directive_lines(_SERVICE.read_text())
    env_files = [line for line in lines if line.startswith("EnvironmentFile=")]
    assert "EnvironmentFile=%h/.config/breezy/breezy.env" in env_files
    assert "EnvironmentFile=-%h/.config/breezy/alerts.env" in env_files
    assert not any(
        line.startswith("EnvironmentFile=-") and "breezy.env" in line for line in env_files
    )


def test_no_credential_env_file_is_referenced() -> None:
    lines = _directive_lines(_SERVICE.read_text())
    env_files = [line for line in lines if line.startswith("EnvironmentFile=")]
    for forbidden in ("polymarket.env", "breezy-trade.env", "operator.env"):
        assert not any(forbidden in env_file for env_file in env_files)


def test_exec_start_reads_log_dir_and_writes_only_the_evidence_dir() -> None:
    exec_start = _directive(_SERVICE.read_text(), "ExecStart")[0]
    assert "--node-log-dir %h/.local/share/breezy/logs" in exec_start
    assert "--out-dir /home/jon/breezy/data/evidence/discovery_set_equality" in exec_start
    assert '--user-agent "${BREEZY_USER_AGENT}"' in exec_start


_EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9-]+)+"
)


def test_unit_file_contains_no_email_address_on_any_line() -> None:
    offending = [line for line in _SERVICE.read_text().splitlines() if _EMAIL_RE.search(line)]
    assert offending == [], f"unit file hardcodes an email address: {offending!r}"


def test_timer_fires_at_1652_utc_and_is_persistent() -> None:
    lines = _directive_lines(_TIMER.read_text())
    assert "OnCalendar=*-*-* 16:52:00 UTC" in lines
    assert "Persistent=true" in lines
