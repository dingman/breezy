"""AUT-6 WP3b unit-file contract: the discovery pull's ceilings follow its measured working set.

Plan r15 section 3.8.1 and section 3.10. Every test parses unit-file text, so each is named
``*_config_*``: this host does not enforce user-unit mount sandboxing (E-7), and a unit file is
configuration, not a control. The unit stays unwrapped (not autonomy-owned, E-7a).
"""

from __future__ import annotations

import math
from typing import Final

import pytest

from breezy.runtime.autonomy_sandbox.table import AUTONOMY_BWRAP_TABLE
from breezy.runtime.autonomy_sandbox.unit_lint import UnitFile, parse_unit
from tests.support.entry_points import DEPLOY_SYSTEMD_DIR, REPO_ROOT

pytestmark = pytest.mark.contract

UNIT: Final = "breezy-discovery-pull"
SERVICE: Final = DEPLOY_SYSTEMD_DIR / f"{UNIT}.service"
TIMER: Final = DEPLOY_SYSTEMD_DIR / f"{UNIT}.timer"
EVIDENCE: Final = REPO_ROOT / "docs/evidence/aut6/WP3b_discovery_pull_memory_2026-10-08.md"
#: Peak process RSS of the redesigned pull (imports + today's poll + trigger replay), KiB, from
#: the fresh-child measurement recorded in EVIDENCE (``ru_maxrss``, three runs 312,864-314,596).
MEASURED_WORKING_SET_KIB: Final = 314_596
MIB_KIB: Final = 1024
HARD_CAP_MIB: Final = 512
#: The pre-redesign working set (RSS + swap) of the 10-02 run, plan section 3.8.1 step 1.
OLD_WORKING_SET_GB: Final = 4.47


def _unit() -> UnitFile:
    return parse_unit(SERVICE.read_text(encoding="utf-8"))


def _mib(value: str) -> int:
    assert value.endswith("M"), value
    return int(value.removesuffix("M"))


def test_discovery_pull_ceiling_matches_measured_working_set() -> None:
    unit = _unit()
    (high,) = unit.values("Service", "MemoryHigh")
    (maximum,) = unit.values("Service", "MemoryMax")
    measured_mib = MEASURED_WORKING_SET_KIB / MIB_KIB
    assert _mib(high) == math.floor(1.5 * measured_mib)
    assert _mib(maximum) == min(math.floor(2 * measured_mib), HARD_CAP_MIB)
    assert _mib(maximum) <= HARD_CAP_MIB
    assert _mib(high) <= _mib(maximum)
    # the redesign is accepted only if the working set is at most 1 GB
    assert measured_mib <= 1024
    assert OLD_WORKING_SET_GB * 1024 > 1024


def test_discovery_pull_config_evidence_records_the_measurement() -> None:
    text = EVIDENCE.read_text(encoding="utf-8")
    assert f"{MEASURED_WORKING_SET_KIB:,}" in text
    assert "MemorySwapPeak" in text
    assert "owed at activation" in text


def test_discovery_pull_config_timeouts_and_worst_end_fit_the_window() -> None:
    unit = _unit()
    assert unit.values("Service", "TimeoutStartSec") == ["900"]
    assert unit.values("Service", "TimeoutStopSec") == ["5"]
    (calendar,) = parse_unit(TIMER.read_text(encoding="utf-8")).values("Timer", "OnCalendar")
    assert calendar == "*-*-* 17:12:00 UTC"
    # 17:12 + 60 s AccuracySec + 900 s + 5 s = 17:28:05Z
    worst_end_s = (17 * 3600 + 12 * 60) + 60 + 900 + 5
    assert worst_end_s == 17 * 3600 + 28 * 60 + 5


def test_discovery_pull_config_stays_unwrapped_and_outside_the_autonomy_table() -> None:
    unit = _unit()
    (exec_start,) = unit.values("Service", "ExecStart")
    assert "breezy-autonomy-bwrap" not in exec_start
    assert UNIT not in AUTONOMY_BWRAP_TABLE
