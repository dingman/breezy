"""AUT-6 WP2 unit-file contract: the canary pair (plan r15 sections 3.7, 3.10; E-9, E-7a, X-3).

Every test parses unit-file text, so each is named ``*_config_*``: this host does not enforce
user-unit mount sandboxing (E-7), and a unit file is configuration, not a control. The firings are
checked against the launch-window table so a retime cannot enter the launch path unnoticed.
"""

from __future__ import annotations

import itertools
import shlex
from pathlib import Path
from typing import Final

import pytest

from breezy.persistence.autonomy import pins
from breezy.runtime.autonomy_sandbox.table import AUTONOMY_BWRAP_TABLE
from breezy.runtime.autonomy_sandbox.unit_lint import (
    WRAPPER_PATH,
    UnitFile,
    parse_unit,
    start_phase_bound_s,
)
from tests.contract.test_autonomy_units_alert_redeliver import (
    _bwrap_wrapped,
    _mount_namespace_findings,
    _secret_findings,
)
from tests.support.entry_points import DEPLOY_SYSTEMD_DIR
from tests.unit.test_launch_window_table import (
    LAUNCH_PATH_TABLE,
    WINDOW_END_S,
    WINDOW_START_S,
    fmt,
    hms,
    parse_on_calendar,
)

pytestmark = pytest.mark.contract

UNIT: Final = "breezy-autonomy-canary"
SERVICE: Final = DEPLOY_SYSTEMD_DIR / f"{UNIT}.service"
TIMER: Final = DEPLOY_SYSTEMD_DIR / f"{UNIT}.timer"


def _unit(path: Path) -> UnitFile:
    return parse_unit(path.read_text(encoding="utf-8"))


def test_canary_config_exec_goes_through_the_wrapper_with_its_own_row() -> None:
    unit = _unit(SERVICE)
    (line,) = unit.values("Service", "ExecStart")
    tokens = shlex.split(line)
    assert tokens[:2] == ["/usr/bin/timeout", "-k"]
    assert tokens[tokens.index(WRAPPER_PATH) + 1] == UNIT
    assert tokens[tokens.index(WRAPPER_PATH) + 2 :][-2:] == [
        "-m",
        "breezy.runtime.autonomy_canary_cli",
    ]
    assert AUTONOMY_BWRAP_TABLE[UNIT].entry_modules == ("breezy.runtime.autonomy_canary_cli",)
    assert f"{UNIT}.service" in AUTONOMY_BWRAP_TABLE[UNIT].units


def test_canary_config_row_binds_alerts_only_with_egress_and_dns() -> None:
    row = AUTONOMY_BWRAP_TABLE[UNIT]
    assert (row.network, row.resolves_dns, row.binds) == ("egress", True, ("evidence/alerts",))
    assert row.credential_names == () and row.credential_env == {}
    assert row.host_proc is False


def test_canary_timeouts_end_within_61_seconds_of_the_slot() -> None:
    """E-9: pre line T + K = 5, ExecStart K + T = 50, stop 5, accuracy 1 s: slot + 61 s."""
    unit = _unit(SERVICE)
    assert unit.values("Service", "TimeoutStartSec") == ["55"]
    assert unit.values("Service", "TimeoutStopSec") == ["5"]
    assert unit.values("Service", "MemoryMax") == ["128M"]
    assert unit.values("Service", "Type") == ["oneshot"]
    assert start_phase_bound_s(SERVICE) == 5
    (line,) = unit.values("Service", "ExecStart")
    tokens = shlex.split(line)
    exec_bound = int(tokens[2]) + int(tokens[3])
    assert (int(tokens[2]), int(tokens[3])) == (4, 46) and exec_bound <= 55
    accuracy = int(_unit(TIMER).values("Timer", "AccuracySec")[0].removesuffix("s"))
    assert accuracy + start_phase_bound_s(SERVICE) + exec_bound + 5 == 61


def test_canary_config_names_the_autonomy_failed_notifier() -> None:
    """X-3: the OnFailure line ships before the notifier row exists (WP4/WP7)."""
    assert _unit(SERVICE).values("Unit", "OnFailure") == ["breezy-autonomy-failed@%n.service"]


def test_canary_config_loads_alerts_env_and_names_no_secret() -> None:
    assert "EnvironmentFile=-%h/.config/breezy/alerts.env" in SERVICE.read_text()
    assert _secret_findings(_unit(SERVICE)) == []
    assert "://" not in SERVICE.read_text() and "://" not in TIMER.read_text()


def test_canary_unit_config_has_no_mount_namespace_directive() -> None:
    """Redeliver defect (a65ee68f/03789239): the bwrap row is the only control."""
    wrapped = _bwrap_wrapped(DEPLOY_SYSTEMD_DIR)
    assert f"{UNIT}.service" in wrapped, "the canary unit must be in the scanned set"
    assert _mount_namespace_findings({f"{UNIT}.service": wrapped[f"{UNIT}.service"]}) == []
    assert _unit(SERVICE).values("Service", "ReadWritePaths") == []


def test_canary_timer_config_is_slot_critical_and_never_persistent() -> None:
    unit = _unit(TIMER)
    assert unit.values("Timer", "OnCalendar") == [
        "*:45:00 UTC",
        "*-*-* 16:30:00 UTC",
        "*-*-* 17:10:00 UTC",
    ]
    assert unit.values("Timer", "AccuracySec") == ["1s"]
    assert unit.values("Timer", "RandomizedDelaySec") in ([], ["0"])
    assert unit.values("Timer", "Persistent") == ["false"]
    assert unit.values("Timer", "Unit") == [f"{UNIT}.service"]


def test_canary_timer_firings_match_launch_window_table() -> None:
    """Inside [16:30Z, 17:10Z) the timer fires exactly where the table's canary row says."""
    slots = sorted(
        {s for e in _unit(TIMER).values("Timer", "OnCalendar") for s in parse_on_calendar(e)}
    )
    inside = [fmt(s) for s in slots if WINDOW_START_S <= s < WINDOW_END_S]
    (row,) = [r for r in LAUNCH_PATH_TABLE if r.unit == "canary_scheduled"]
    assert inside == [fmt(hms(f)) for f in row.firings]
    # 24 hourly :45 firings, plus the 16:30 and 17:10 extras
    assert len(slots) == 26
    assert hms("15:45") in slots and hms("17:10") in slots
    # the 17:10 firing opens the retry gate the table does not need to bound
    assert hms("17:10") >= WINDOW_END_S


def test_canary_retry_cadence_equals_the_hourly_45_firings() -> None:
    hourly = [s for s in parse_on_calendar("*:45:00 UTC")]
    gaps = {b - a for a, b in itertools.pairwise(hourly)}
    assert gaps == {3600}
    assert gaps == {pins.CANARY_RETRY_PERIOD_MIN * 60}


def test_canary_suppression_drill_dates_are_unregistered_until_the_endpoint_exists() -> None:
    """Ruling r3 item 4: the drill code exists, no date is registered."""
    assert pins.CANARY_SUPPRESSION_DRILL_DATES == frozenset()
    assert type(pins.CANARY_SUPPRESSION_DRILL_DATES) is frozenset
