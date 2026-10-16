"""MAKER-S2 second look (C4, D3): the parked trigger unit pins its caps and calendar."""

from __future__ import annotations

import re
from pathlib import Path

_DIR = Path(__file__).resolve().parents[2] / "deploy" / "systemd"
_SERVICE = "breezy-maker-s2-trigger.service"


def _directives(name: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for line in (_DIR / name).read_text().splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            out.setdefault(key.strip(), []).append(value.strip())
    return out


def test_trigger_unit_files_pin_caps_and_calendar() -> None:
    svc = _directives(_SERVICE)
    timer = _directives("breezy-maker-s2-trigger.timer")
    assert svc["Type"] == ["oneshot"]
    assert svc["MemoryMax"] == ["8G"] and svc["TimeoutStartSec"] == ["10800"]
    assert svc["Slice"] == ["breezy-studies.slice"]
    assert svc["LimitNOFILE"] == ["524288"]
    assert re.search(r"-m scripts\.analysis\.maker_stage0_trigger check$", svc["ExecStart"][0])
    assert timer["OnCalendar"] == ["*-*-* 10:05:00 UTC"]
    assert timer["Persistent"] == ["false"]
    assert timer["Unit"] == [_SERVICE]
    assert timer["WantedBy"] == ["timers.target"]
    assert "\n[Install]" not in (_DIR / _SERVICE).read_text()
