"""EXEC-PAR BG-7: the cross-check service and timer files (text-only; nothing is installed)."""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SYSTEMD = _REPO_ROOT / "deploy" / "systemd"
_SERVICE = _SYSTEMD / "breezy-exec-par-stage-gate.service"
_TIMER = _SYSTEMD / "breezy-exec-par-stage-gate.timer"


def _directives(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _value(path: Path, name: str) -> str:
    matches = [d[len(name) + 1 :] for d in _directives(path) if d.startswith(f"{name}=")]
    assert len(matches) == 1, (name, matches)
    return matches[0]


def test_the_service_runs_the_script_as_a_module_under_the_repo_working_directory() -> None:
    assert _value(_SERVICE, "WorkingDirectory") == "/home/jon/breezy"
    exec_start = _value(_SERVICE, "ExecStart")
    assert exec_start.startswith("/home/jon/breezy/.venv/bin/python -m ")
    assert "scripts.analysis.exec_par_stage_gate" in exec_start
    assert "--family-id pm_us_crh_fq_v1" in exec_start
    assert "--db %h/.local/share/breezy/state/exec_polymarket_us.sqlite" in exec_start


def test_the_service_has_a_memory_ceiling_a_timeout_and_failure_alerting() -> None:
    assert _value(_SERVICE, "Type") == "oneshot"
    assert _value(_SERVICE, "MemoryMax").endswith("G")
    assert _value(_SERVICE, "MemoryHigh").endswith("G")
    assert int(_value(_SERVICE, "TimeoutStartSec")) > 0
    assert _value(_SERVICE, "OnFailure") == "breezy-study-failed@%n.service"
    assert "EnvironmentFile=-%h/.config/breezy/alerts.env" in _directives(_SERVICE)


def test_the_service_never_loads_credentials_or_operator_controls_and_has_no_install() -> None:
    text = "\n".join(_directives(_SERVICE))
    for forbidden in ("polymarket.env", "breezy-trade.env", "operator.env", "breezy.env"):
        assert forbidden not in text
    assert "[Install]" not in text


def test_the_timer_fires_the_service_once_a_day_at_a_unique_minute() -> None:
    assert _value(_TIMER, "Unit") == "breezy-exec-par-stage-gate.service"
    calendar = _value(_TIMER, "OnCalendar")
    match = re.fullmatch(r"\*-\*-\* (\d{2}):(\d{2}):00 UTC", calendar)
    assert match is not None, calendar
    tick = (match.group(1), match.group(2))
    owners = [
        timer.name
        for timer in sorted(_SYSTEMD.glob("*.timer"))
        for line in _directives(timer)
        if line.startswith("OnCalendar=") and re.search(rf" {tick[0]}:{tick[1]}:00 UTC$", line)
    ]
    assert owners == ["breezy-exec-par-stage-gate.timer"]
    assert "[Install]" in _directives(_TIMER)
