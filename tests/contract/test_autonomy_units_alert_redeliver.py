"""AUT-6 WP1 unit-file contract: the redeliver pair and the AUT-6 unit rules (plan r15).

Sections 3.6.5 and 3.10.

Every test parses unit-file text, so each is named ``*_config_*``: this host does not enforce
user-unit mount sandboxing (E-7), and a unit file is configuration, not a control.
"""

from __future__ import annotations

import shlex
from collections.abc import Mapping
from pathlib import Path
from typing import Final

import pytest

from breezy.runtime.autonomy_sandbox.table import AUTONOMY_BWRAP_TABLE
from breezy.runtime.autonomy_sandbox.unit_lint import (
    WRAPPER_PATH,
    UnitFile,
    lint_units,
    parse_unit,
    start_phase_bound_s,
)
from tests.support.entry_points import DEPLOY_SYSTEMD_DIR

pytestmark = pytest.mark.contract

UNIT: Final = "breezy-autonomy-alert-redeliver"
SERVICE: Final = DEPLOY_SYSTEMD_DIR / f"{UNIT}.service"
TIMER: Final = DEPLOY_SYSTEMD_DIR / f"{UNIT}.timer"
ALERTS_ENV: Final = "EnvironmentFile=-%h/.config/breezy/alerts.env"
JOURNAL_PATH: Final = "%h/.local/share/breezy/evidence/alerts"
#: The wrapper-secret rule: a key naming a secret, or any value carrying a URL.
_SECRET_SUFFIXES: Final = ("_URL", "_TOKEN", "_KEY", "_SECRET", "_PASSWORD")
_WEBHOOK_VAR: Final = "BREEZY_ALERT_WEBHOOK_URL"


def _unit(path: Path) -> UnitFile:
    return parse_unit(path.read_text(encoding="utf-8"))


def _alerting_sandboxed(directory: Path) -> dict[str, UnitFile]:
    found: dict[str, UnitFile] = {}
    for path in sorted(directory.glob("*.service")):
        text = path.read_text(encoding="utf-8")
        lines = [line.strip() for line in text.splitlines()]
        sandboxed = any(
            line.startswith("ProtectHome=") or line == "ProtectSystem=strict" for line in lines
        )
        if ALERTS_ENV in lines and sandboxed:
            found[path.name] = parse_unit(text)
    return found


def _journal_gaps(directory: Path) -> set[str]:
    return {
        name
        for name, unit in _alerting_sandboxed(directory).items()
        if not any(
            JOURNAL_PATH in value.split() for value in unit.values("Service", "ReadWritePaths")
        )
        and not any(
            "/.local/share/breezy/evidence/alerts" in value
            for value in unit.values("Service", "ReadWritePaths")
        )
    }


def _secret_findings(unit: UnitFile) -> list[str]:
    """``Environment=`` lines and ``--setenv``/``-E``/``env VAR=`` args naming a secret or a URL."""
    findings: list[str] = []
    for _section, key, value in unit.entries:
        if key == "Environment":
            findings.append(f"Environment={value}")
        if key not in {"ExecStart", "ExecStartPre", "ExecStartPost", "ExecStopPost"}:
            continue
        tokens = shlex.split(value.lstrip("@-:+!|"))
        for index, token in enumerate(tokens):
            carries = token in {"--setenv", "-E"} and index + 1 < len(tokens)
            assignment = tokens[index + 1] if carries else token
            name, sep, rest = assignment.partition("=")
            is_assignment = bool(sep) and name.replace("_", "").isalnum() and name.isupper()
            if is_assignment and (
                name == _WEBHOOK_VAR or name.endswith(_SECRET_SUFFIXES) or "://" in rest
            ):
                findings.append(f"{key} {name}")
    return findings


# -- the redeliver pair ---------------------------------------------------------------------------


def test_redeliver_config_exec_goes_through_the_wrapper_with_its_own_row() -> None:
    unit = _unit(SERVICE)
    (line,) = unit.values("Service", "ExecStart")
    tokens = shlex.split(line)
    assert tokens[:2] == ["/usr/bin/timeout", "-k"]
    assert tokens[tokens.index(WRAPPER_PATH) + 1] == UNIT
    assert tokens[tokens.index(WRAPPER_PATH) + 2 :][-2:] == [
        "-m",
        "breezy.runtime.alert_redeliver_cli",
    ]
    assert AUTONOMY_BWRAP_TABLE[UNIT].entry_modules == ("breezy.runtime.alert_redeliver_cli",)
    assert f"{UNIT}.service" in AUTONOMY_BWRAP_TABLE[UNIT].units


def test_redeliver_timeout_start_sec_is_55_and_stop_sec_5() -> None:
    """E-9: both values are declared; each pre line counts at T + K; ExecStart fits 55 s."""
    unit = _unit(SERVICE)
    assert unit.values("Service", "TimeoutStartSec") == ["55"]
    assert unit.values("Service", "TimeoutStopSec") == ["5"]
    assert unit.values("Service", "MemoryMax") == ["128M"]
    assert start_phase_bound_s(SERVICE) == 5
    (line,) = unit.values("Service", "ExecStart")
    tokens = shlex.split(line)
    assert (int(tokens[2]), int(tokens[3])) == (4, 46)
    exec_bound = int(tokens[2]) + int(tokens[3])
    assert exec_bound <= 55
    # worst end = AccuracySec + pre lines (T + K) + ExecStart (K + T) + TimeoutStopSec = 61 s
    accuracy = int(_unit(TIMER).values("Timer", "AccuracySec")[0].removesuffix("s"))
    assert accuracy + start_phase_bound_s(SERVICE) + exec_bound + 5 == 61


def test_redeliver_config_names_the_autonomy_failed_notifier_and_resolves_dns() -> None:
    """X-3 ships the OnFailure line before the notifier exists; E-15 declares egress and DNS."""
    unit = _unit(SERVICE)
    assert unit.values("Unit", "OnFailure") == ["breezy-autonomy-failed@%n.service"]
    row = AUTONOMY_BWRAP_TABLE[UNIT]
    assert (row.network, row.resolves_dns, row.binds) == ("egress", True, ("evidence/alerts",))


def test_redeliver_config_loads_alerts_env_and_lists_the_delivery_journal() -> None:
    unit = _unit(SERVICE)
    assert "EnvironmentFile=-%h/.config/breezy/alerts.env" in SERVICE.read_text()
    # Reviewed row change: ReadWritePaths= used to be pinned to [JOURNAL_PATH]. That line made
    # systemd build a private mount namespace in which bwrap cannot create its user namespace
    # (AppArmor userns restriction), so the unit never ran. The bwrap row is the control.
    assert unit.values("Service", "ReadWritePaths") == []


def test_redeliver_timer_config_is_slot_critical_and_never_persistent() -> None:
    unit = _unit(TIMER)
    assert unit.values("Timer", "OnCalendar") == ["*:03/5"]
    assert unit.values("Timer", "AccuracySec") == ["1s"]
    assert unit.values("Timer", "RandomizedDelaySec") == ["0"]
    assert unit.values("Timer", "Persistent") == ["false"]
    assert unit.values("Timer", "Unit") == [f"{UNIT}.service"]


def test_deploy_units_config_lint_reports_only_the_x3_gap() -> None:
    """X-3: the notifier row does not exist yet, so its scope error is the one recorded gap."""
    assert SERVICE.is_file() and TIMER.is_file()
    errors = lint_units(DEPLOY_SYSTEMD_DIR, AUTONOMY_BWRAP_TABLE)
    # AUT-6 WP2 widens the recorded gap by exactly one reviewed row: the canary unit.
    assert [(e.unit, e.rule) for e in errors] == [
        (f"{UNIT}.service", "onfailure_scope"),
        ("breezy-autonomy-canary.service", "onfailure_scope"),
        ("breezy-autonomy-health.service", "onfailure_scope"),  # AUT-6 WP3 S2: one reviewed row
    ]


# -- the rules AUT-6 holds over every unit it owns ------------------------------------------------


def test_every_alerting_sandboxed_unit_config_lists_the_delivery_journal() -> None:
    assert _alerting_sandboxed(DEPLOY_SYSTEMD_DIR), "the scan must judge at least one unit"
    assert _journal_gaps(DEPLOY_SYSTEMD_DIR) == set()


def test_alerting_sandboxed_unit_config_without_the_journal_path_fails(tmp_path: Path) -> None:
    (tmp_path / "x.service").write_text(
        f"[Service]\n{ALERTS_ENV}\nProtectHome=read-only\nReadWritePaths=/srv/elsewhere\n"
    )
    (tmp_path / "y.service").write_text(
        f"[Service]\n{ALERTS_ENV}\nProtectSystem=strict\nReadWritePaths={JOURNAL_PATH}\n"
    )
    assert _journal_gaps(tmp_path) == {"x.service"}


#: Directives that make systemd build a mount namespace; bwrap cannot create its user namespace
#: inside one on this host (AppArmor userns restriction): "No permissions to create a namespace".
_MOUNT_NAMESPACE_DIRECTIVES: Final = (
    "ReadWritePaths",
    "ReadOnlyPaths",
    "InaccessiblePaths",
    "ProtectSystem",
    "ProtectHome",
    "PrivateTmp",
    "PrivateDevices",
    "PrivateMounts",
    "BindPaths",
    "BindReadOnlyPaths",
    "TemporaryFileSystem",
    "ProtectKernelTunables",
    "ProtectKernelModules",
    "ProtectKernelLogs",
    "ProtectControlGroups",
    "ProtectProc",
    "ProcSubset",
    "MountAPIVFS",
    "RootDirectory",
    "RootImage",
    "ReadWriteDirectories",
    "ReadOnlyDirectories",
    "InaccessibleDirectories",
    "PrivateUsers",
    "PrivateNetwork",
    "PrivateIPC",
    "ProtectHostname",
)


def _bwrap_wrapped(directory: Path) -> dict[str, UnitFile]:
    found: dict[str, UnitFile] = {}
    for path in sorted(directory.glob("*.service")):
        unit = _unit(path)
        if any(Path(WRAPPER_PATH).name in v for v in unit.values("Service", "ExecStart")):
            found[path.name] = unit
    return found


def _mount_namespace_findings(units: Mapping[str, UnitFile]) -> list[str]:
    return [
        f"{name}: {key}"
        for name, unit in units.items()
        for key in _MOUNT_NAMESPACE_DIRECTIVES
        if unit.values("Service", key)
    ]


def test_bwrap_wrapped_unit_config_has_no_mount_namespace_directive() -> None:
    wrapped = _bwrap_wrapped(DEPLOY_SYSTEMD_DIR)
    assert wrapped, "the scan must judge at least one bwrap-wrapped unit"
    assert _mount_namespace_findings(wrapped) == []


def test_mount_namespace_directive_scan_config_flags_a_wrapped_unit(tmp_path: Path) -> None:
    (tmp_path / "x.service").write_text(
        f"[Service]\nExecStart={WRAPPER_PATH} row /bin/true\nPrivateTmp=yes\n"
    )
    wrapped = _bwrap_wrapped(tmp_path)
    assert _mount_namespace_findings(wrapped) == ["x.service: PrivateTmp"]


def _timers(directory: Path) -> dict[str, UnitFile]:
    return {p.name: _unit(p) for p in sorted(directory.glob("breezy-autonomy-*.timer"))}


def _timer_pin_failures(timers: Mapping[str, UnitFile]) -> list[str]:
    bad: list[str] = []
    for name, unit in timers.items():
        if unit.values("Timer", "AccuracySec") != ["1s"]:
            bad.append(f"{name}: AccuracySec")
        if unit.values("Timer", "RandomizedDelaySec") not in ([], ["0"]):
            bad.append(f"{name}: RandomizedDelaySec")
    return bad


def test_slot_critical_autonomy_timers_config_pin_accuracy_sec_1s() -> None:
    timers = _timers(DEPLOY_SYSTEMD_DIR)
    assert f"{UNIT}.timer" in timers
    assert _timer_pin_failures(timers) == []


def test_slot_critical_timer_config_pin_fires_on_a_default_accuracy_fixture(tmp_path: Path) -> None:
    (tmp_path / "breezy-autonomy-fixture.timer").write_text(
        "[Timer]\nOnCalendar=*:00/5\nRandomizedDelaySec=30\n"
    )
    assert _timer_pin_failures(_timers(tmp_path)) == [
        "breezy-autonomy-fixture.timer: AccuracySec",
        "breezy-autonomy-fixture.timer: RandomizedDelaySec",
    ]


def _aut6_unit_files(directory: Path) -> list[Path]:
    """Each ``breezy-autonomy-*`` unit and drop-in that AUT-6 owns (every one at WP1)."""
    files = [p for p in sorted(directory.glob("breezy-autonomy-*.service"))]
    files.append(directory / "breezy-discovery-pull.service")  # changed by AUT-6 WP1 (E-7)
    for dropin in sorted(directory.glob("breezy-autonomy-*.service.d")):
        files += sorted(dropin.glob("*.conf"))
    return files


def test_aut6_unit_config_has_no_environment_secrets() -> None:
    files = _aut6_unit_files(DEPLOY_SYSTEMD_DIR)
    assert SERVICE in files and DEPLOY_SYSTEMD_DIR / "breezy-discovery-pull.service" in files
    findings = {p.name: _secret_findings(_unit(p)) for p in files}
    assert {name: found for name, found in findings.items() if found} == {}


@pytest.mark.parametrize(
    "line",
    [
        "Environment=BREEZY_ALERT_WEBHOOK_URL=https://example.invalid/x",
        "Environment=FOO=bar",
        "ExecStart=/usr/bin/env BREEZY_ALERT_WEBHOOK_URL=x /usr/bin/true",
        "ExecStart=/usr/bin/true --setenv API_TOKEN=abc",
        "ExecStart=/usr/bin/true -E SERVICE_KEY=abc",
        "ExecStartPre=/usr/bin/env FEED=https://host/path /usr/bin/true",
    ],
)
def test_aut6_unit_config_secret_rule_fires_on_each_planted_form(line: str) -> None:
    unit = parse_unit(f"[Service]\n{line}\n")
    assert _secret_findings(unit), line


def test_aut6_unit_config_secret_rule_ignores_a_clean_unit() -> None:
    assert _secret_findings(_unit(SERVICE)) == []
