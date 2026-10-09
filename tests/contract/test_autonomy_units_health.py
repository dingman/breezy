"""AUT-6 WP3 S2 unit-file contract: the health pair and the programme runtime-bound rules.

Plan r15 sections 3.9, 3.10 and WP3; errata E-7e(f)/(h) (bus snapshot handoff) and E-9
(``TimeoutStopSec`` in every worst end). Every test parses unit-file text, so each is named
``*_config_*`` or judges the parser: this host does not enforce user-unit mount sandboxing (E-7),
and a unit file is configuration, not a control.

The three programme tests extend ``tests/unit/test_launch_window_table.py`` (its ``parse_service``
now sums per-command bounds) and ``tests/unit/test_capture_units.py`` (the same E-9 arithmetic on
the capture fixtures); they do not copy either.
"""

from __future__ import annotations

import datetime as dt
import shlex
import shutil
from pathlib import Path
from typing import Final

import pytest

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
    firings,
    fmt,
    hms,
    merged_directives,
    parse_duration_s,
    parse_on_calendar,
    parse_service,
)

pytestmark = pytest.mark.contract

UNIT: Final = "breezy-autonomy-health"
SERVICE: Final = DEPLOY_SYSTEMD_DIR / f"{UNIT}.service"
TIMER: Final = DEPLOY_SYSTEMD_DIR / f"{UNIT}.timer"
STOP_S: Final = 5
#: ARCH section 5.2 "Ends by", after erratum E-9 (health amended to 145 s plus 1 s accuracy).
ENDS_BY_S: Final[dict[str, int]] = {
    UNIT: 146,
    "breezy-autonomy-canary": 61,
    "breezy-autonomy-alert-redeliver": 61,
}
SNAPSHOT_PRE: Final = f"-/usr/bin/timeout -k 2 18 {WRAPPER_PATH} --bus-snapshot {UNIT}"


def _unit(path: Path) -> UnitFile:
    return parse_unit(path.read_text(encoding="utf-8"))


def _exec_bound(unit: UnitFile) -> int:
    (line,) = unit.values("Service", "ExecStart")
    tokens = shlex.split(line)
    assert tokens[:2] == ["/usr/bin/timeout", "-k"], line
    return int(tokens[2]) + int(tokens[3])


def _worst_end_after_slot_s(directory: Path, name: str) -> float:
    """AccuracySec + start phase + ExecStart ``K + T`` + ``TimeoutStopSec`` (default 90 s)."""
    service = directory / f"{name}.service"
    unit = _unit(service)
    timer = _unit(directory / f"{name}.timer")
    accuracy = parse_duration_s(timer.values("Timer", "AccuracySec")[0])
    stops = unit.values("Service", "TimeoutStopSec")
    stop = parse_duration_s(stops[0]) if stops else 90.0
    return accuracy + start_phase_bound_s(service) + _exec_bound(unit) + stop


def oneshot_services(directory: Path) -> list[str]:
    """Every ``*.service`` whose merged ``Type=`` is ``oneshot``: derived from the files."""
    found: list[str] = []
    for path in sorted(directory.glob("*.service")):
        directives = merged_directives(
            path.read_text(encoding="utf-8"), directory / f"{path.name}.d"
        )
        if directives.get("Type", ["simple"])[-1] == "oneshot":
            found.append(path.name)
    return found


def oneshot_rule_violations(directory: Path) -> list[str]:
    """The programme rule: a oneshot declares ``TimeoutStartSec`` and never ``RuntimeMaxSec``."""
    problems: list[str] = []
    for name in oneshot_services(directory):
        directives = merged_directives(
            (directory / name).read_text(encoding="utf-8"), directory / f"{name}.d"
        )
        if "RuntimeMaxSec" in directives:
            problems.append(f"{name}: RuntimeMaxSec")
        if "TimeoutStartSec" not in directives:
            problems.append(f"{name}: no TimeoutStartSec")
    return problems


def _write_oneshot(directory: Path, name: str, body: str) -> None:
    (directory / f"{name}.service").write_text(f"[Service]\nType=oneshot\n{body}", encoding="utf-8")


# -- programme rules (E-9, AA1) -------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(ENDS_BY_S))
def test_aut6_oneshot_worst_end_includes_timeout_stop_sec(name: str) -> None:
    """E-9: every AUT-6 oneshot declares ``TimeoutStopSec=5`` and fits its ARCH 'Ends by' column."""
    unit = _unit(DEPLOY_SYSTEMD_DIR / f"{name}.service")
    assert unit.values("Service", "TimeoutStopSec") == [str(STOP_S)], name
    assert _worst_end_after_slot_s(DEPLOY_SYSTEMD_DIR, name) <= ENDS_BY_S[name], name


def test_aut6_health_worst_end_is_slot_plus_146_and_inside_every_launch_window_gap() -> None:
    """Pre lines 5 + 20, ExecStart 115, stop 5, accuracy 1: the 16:41 pass ends 16:43:26."""
    assert _worst_end_after_slot_s(DEPLOY_SYSTEMD_DIR, UNIT) == 146
    (row,) = [r for r in LAUNCH_PATH_TABLE if r.unit == "aut6_health"]
    assert row.ends_after_s == 146 and row.flock_wait_s + row.timeout_start_s == 146
    assert hms("16:41") + 146 == hms("16:43:26")
    slots = sorted(
        {s for e in _unit(TIMER).values("Timer", "OnCalendar") for s in parse_on_calendar(e)}
    )
    inside = [fmt(s) for s in slots if WINDOW_START_S <= s < WINDOW_END_S]
    assert inside == [fmt(hms(f)) for f in row.firings]
    assert len(slots) == 144


def test_aut6_worst_end_check_fails_a_unit_without_timeout_stop_sec(tmp_path: Path) -> None:
    """The 90 s systemd default for a missing ``TimeoutStopSec`` breaks the bound (control)."""
    for suffix in ("service", "timer"):
        shutil.copy(DEPLOY_SYSTEMD_DIR / f"{UNIT}.{suffix}", tmp_path / f"{UNIT}.{suffix}")
    text = (tmp_path / f"{UNIT}.service").read_text(encoding="utf-8")
    (tmp_path / f"{UNIT}.service").write_text(
        "".join(line for line in text.splitlines(keepends=True) if "TimeoutStopSec" not in line),
        encoding="utf-8",
    )
    assert _worst_end_after_slot_s(tmp_path, UNIT) == 1 + 25 + 115 + 90 > ENDS_BY_S[UNIT]


def test_discovery_pull_worst_end_includes_timeout_stop_sec() -> None:
    """E-9: 17:12 + 60 s accuracy + 900 s + 5 s stop = 17:28:05Z."""
    service = _unit(DEPLOY_SYSTEMD_DIR / "breezy-discovery-pull.service")
    assert service.values("Service", "TimeoutStopSec") == [str(STOP_S)]
    spec = parse_service(
        "breezy-discovery-pull.service",
        (DEPLOY_SYSTEMD_DIR / "breezy-discovery-pull.service").read_text(encoding="utf-8"),
        DEPLOY_SYSTEMD_DIR,
    )
    (fire,) = [f for f in firings(DEPLOY_SYSTEMD_DIR) if f.timer == "breezy-discovery-pull"]
    assert spec.timeout_stop_s == STOP_S
    assert fmt(fire.worst_end_s) == "17:28:05"


def test_runtime_bound_sums_per_command_timeouts(tmp_path: Path) -> None:
    """AA1: the bound sums each command's own ``timeout -k K T``, not N x TimeoutStartSec."""
    _write_oneshot(
        tmp_path,
        "multi",
        "TimeoutStartSec=115\n"
        "ExecStartPre=/usr/bin/timeout -k 1 4 /bin/true\n"
        "ExecStartPre=-/usr/bin/timeout -k 2 18 /bin/true\n"
        "ExecStart=/usr/bin/timeout -k 5 110 /bin/true\n",
    )
    spec = parse_service("multi.service", (tmp_path / "multi.service").read_text(), tmp_path)
    assert spec.command_bound_s == 5 + 20 + 115 < 3 * 115
    # a command with no timeout head counts the whole TimeoutStartSec (nothing else bounds it)
    _write_oneshot(
        tmp_path,
        "bare",
        "TimeoutStartSec=115\nExecStartPre=/bin/true\n"
        "ExecStart=/usr/bin/timeout -k 5 110 /bin/true\n",
    )
    bare = parse_service("bare.service", (tmp_path / "bare.service").read_text(), tmp_path)
    assert bare.command_bound_s == 115 + 115
    # a per-command bound above TimeoutStartSec is capped by it (systemd re-arms, then kills)
    _write_oneshot(
        tmp_path, "capped", "TimeoutStartSec=30\nExecStart=/usr/bin/timeout -k 5 600 /bin/true\n"
    )
    capped = parse_service("capped.service", (tmp_path / "capped.service").read_text(), tmp_path)
    assert capped.command_bound_s == 30
    # no TimeoutStartSec on a oneshot stays unbounded whatever the heads say
    _write_oneshot(tmp_path, "loose", "ExecStart=/usr/bin/timeout -k 5 10 /bin/true\n")
    loose = parse_service("loose.service", (tmp_path / "loose.service").read_text(), tmp_path)
    assert loose.command_bound_s == float("inf")


def test_health_runtime_bound_is_the_sum_of_its_three_commands() -> None:
    spec = parse_service(f"{UNIT}.service", SERVICE.read_text(encoding="utf-8"), DEPLOY_SYSTEMD_DIR)
    assert spec.command_bound_s == 5 + 20 + 115
    assert (spec.timeout_start_s, spec.timeout_stop_s) == (115, STOP_S)


def test_every_unit_has_an_effective_runtime_bound() -> None:
    """Every timer-driven unit has a finite worst end, and so does every deployed oneshot."""
    fired = firings(DEPLOY_SYSTEMD_DIR)
    assert fired, "the scan must judge at least one firing"
    unbounded = sorted({f.unit for f in fired if f.worst_end_s == float("inf")})
    assert unbounded == []
    for name in oneshot_services(DEPLOY_SYSTEMD_DIR):
        spec = parse_service(
            name, (DEPLOY_SYSTEMD_DIR / name).read_text(encoding="utf-8"), DEPLOY_SYSTEMD_DIR
        )
        assert spec.command_bound_s != float("inf"), name


def test_an_unbounded_unit_is_caught_by_the_effective_bound_scan(tmp_path: Path) -> None:
    _write_oneshot(tmp_path, "loose", "ExecStart=/bin/true\n")
    (tmp_path / "loose.timer").write_text("[Timer]\nOnCalendar=*-*-* 09:00:00 UTC\n")
    assert [f.worst_end_s for f in firings(tmp_path)] == [float("inf")]


def test_oneshot_rule_derives_unit_set_from_type_lines(tmp_path: Path) -> None:
    """LOW-3: a fixture oneshot grows the checked set by one; no literal count appears anywhere."""
    copy = tmp_path / "systemd"
    shutil.copytree(DEPLOY_SYSTEMD_DIR, copy)
    before = oneshot_services(copy)
    assert before and oneshot_rule_violations(copy) == []
    _write_oneshot(copy, "zz-fixture", "TimeoutStartSec=30\nExecStart=/bin/true\n")
    assert len(oneshot_services(copy)) == len(before) + 1
    (copy / "zz-daemon.service").write_text("[Service]\nType=simple\nExecStart=/bin/true\n")
    assert len(oneshot_services(copy)) == len(before) + 1  # a daemon never joins the set
    assert oneshot_rule_violations(copy) == []
    _write_oneshot(copy, "zz-bad", "TimeoutStartSec=30\nRuntimeMaxSec=20\nExecStart=/bin/true\n")
    _write_oneshot(copy, "zz-none", "ExecStart=/bin/true\n")
    assert oneshot_rule_violations(copy) == [
        "zz-bad.service: RuntimeMaxSec",
        "zz-none.service: no TimeoutStartSec",
    ]


# -- the health pair ------------------------------------------------------------------------------


def test_health_config_exec_goes_through_the_wrapper_with_its_own_row() -> None:
    unit = _unit(SERVICE)
    (line,) = unit.values("Service", "ExecStart")
    tokens = shlex.split(line)
    assert tokens[:4] == ["/usr/bin/timeout", "-k", "5", "110"]
    assert tokens[tokens.index(WRAPPER_PATH) + 1] == UNIT
    assert tokens[tokens.index(WRAPPER_PATH) + 2 :] == [
        "/home/jon/breezy/.venv/bin/python3",
        "-I",
        "-m",
        "breezy.runtime.autonomy_health_cli",
    ]
    row = AUTONOMY_BWRAP_TABLE[UNIT]
    assert row.entry_modules == ("breezy.runtime.autonomy_health_cli",)
    assert f"{UNIT}.service" in row.units


def test_health_config_start_phase_is_install_then_the_bus_snapshot_last() -> None:
    """E-7e(h): the snapshot is the last pre line, ``-`` prefixed, ``timeout -k 2 B+3``."""
    unit = _unit(SERVICE)
    pre = unit.values("Service", "ExecStartPre")
    row = AUTONOMY_BWRAP_TABLE[UNIT]
    assert row.bus_snapshot_budget_s == 15
    assert len(pre) == 2 and pre[-1] == SNAPSHOT_PRE
    install = shlex.split(pre[0])
    assert install[:7] == ["/usr/bin/timeout", "-k", "1", "4", "/usr/bin/install", "-d", "-m"]
    assert install[7] == "0700"
    dirs = {Path(p).relative_to("%h/.local/share/breezy").as_posix() for p in install[8:]}
    assert dirs == set(row.binds)
    assert start_phase_bound_s(SERVICE) == 5 + 20
    assert 15 + 5 < int(unit.values("Service", "TimeoutStartSec")[0])  # B + 5 < TimeoutStartSec


def test_health_config_limits_and_names_the_autonomy_failed_notifier() -> None:
    unit = _unit(SERVICE)
    assert unit.values("Service", "Type") == ["oneshot"]
    assert unit.values("Service", "TimeoutStartSec") == ["115"]
    assert unit.values("Service", "TimeoutStopSec") == ["5"]
    assert unit.values("Service", "MemoryMax") == ["256M"]
    assert unit.values("Service", "MemorySwapMax") == ["0"]
    assert unit.values("Service", "RuntimeMaxSec") == []
    assert unit.values("Unit", "OnFailure") == ["breezy-autonomy-failed@%n.service"]  # X-3


def test_health_config_row_is_networkless_with_host_proc_and_four_binds() -> None:
    row = AUTONOMY_BWRAP_TABLE[UNIT]
    assert (row.network, row.resolves_dns, row.host_proc) == ("none", False, True)
    assert row.exceptions == frozenset({"E7A_R2_PROC", "E7_CONFIG_DIR"})  # X-13: config bind
    assert row.config_ro_dirs == (".config/systemd/user",) and row.config_ro_binds == ()
    assert row.binds == (
        "evidence/unit_health",
        "derived/verdicts",
        "evidence/alerts",
        "cache/aut6_health_bus",
    )
    assert row.bus_snapshot_bind == "cache/aut6_health_bus"
    assert row.credential_names == () and row.credential_env == {}
    assert row.studies_lock is False


def test_health_config_names_no_secret_and_no_mount_namespace_directive() -> None:
    """X-10: the bwrap row is the only control; ``Environment=`` and alerts.env stay out."""
    text = SERVICE.read_text(encoding="utf-8")
    assert _secret_findings(_unit(SERVICE)) == []
    assert "Environment" not in "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )
    wrapped = _bwrap_wrapped(DEPLOY_SYSTEMD_DIR)
    assert f"{UNIT}.service" in wrapped, "the health unit must be in the scanned set"
    assert _mount_namespace_findings({f"{UNIT}.service": wrapped[f"{UNIT}.service"]}) == []
    assert _unit(SERVICE).values("Service", "ReadWritePaths") == []


def test_health_timer_config_is_slot_critical_every_ten_minutes_at_01() -> None:
    unit = _unit(TIMER)
    assert unit.values("Timer", "OnCalendar") == ["*:01/10 UTC"]
    assert parse_on_calendar("*:01/10")[:3] == [hms("00:01"), hms("00:11"), hms("00:21")]
    assert unit.values("Timer", "AccuracySec") == ["1s"]
    assert unit.values("Timer", "RandomizedDelaySec") in ([], ["0"])
    assert unit.values("Timer", "Persistent") in ([], ["false"])
    assert unit.values("Timer", "Unit") in ([], [f"{UNIT}.service"])
    start = dt.timedelta(seconds=hms("00:01"))
    assert start == dt.timedelta(minutes=1)


def test_health_row_show_read_names_the_review_properties_and_both_unit_patterns() -> None:
    """Review S2: MainPID/UnitFileState/LoadState, and the second timer template's instances."""
    (show,) = [r for r in AUTONOMY_BWRAP_TABLE[UNIT].bus_reads if r.name == "units_show"]
    argv = show.argv
    properties = set(argv[argv.index("-p") + 1].split(","))
    assert {"MainPID", "UnitFileState", "LoadState"} <= properties
    assert argv[argv.index("--") + 1 :] == ("breezy-*", "us-source-collector@*")
    assert not any("Environment" in p or "Credential" in p for p in properties)


def test_health_entry_defines_main_and_has_no_skeleton_left() -> None:
    """S6: the pass replaced the S2 skeleton, so an early enable can no longer exit 78 silently."""
    from breezy.runtime import autonomy_health_cli

    assert callable(autonomy_health_cli.main)
    assert not hasattr(autonomy_health_cli, "run_skeleton")
    assert not hasattr(autonomy_health_cli, "EX_CONFIG")
    assert autonomy_health_cli.main(["--no-such-flag"]) == autonomy_health_cli.EXIT_USAGE


def test_health_entry_must_join_the_closure_lint_before_main_exists() -> None:
    """Tripwire: defining ``main`` without the closure-lint rows fails here (done in S6)."""
    from breezy.persistence.autonomy.detector_catalog import AUT6_LINT_MIN_JUDGED_SITES
    from breezy.runtime import autonomy_health_cli
    from tests.unit.test_autonomy_readonly_closure import AUT6_ENTRY_MODULES

    if hasattr(autonomy_health_cli, "main"):
        assert UNIT in AUT6_ENTRY_MODULES, "add the health entry to AUT6_ENTRY_MODULES"
        assert UNIT in AUT6_LINT_MIN_JUDGED_SITES, "add the health floor to the min-sites literal"


def test_health_row_has_the_two_inventory_reads_inside_the_15_second_budget() -> None:
    """R-S2-1: the loaded and the on-disk inventory are fixed reads next to the detail read."""
    row = AUTONOMY_BWRAP_TABLE[UNIT]
    reads = {r.name: r.argv for r in row.bus_reads}
    patterns = ("--", "breezy-*", "us-source-collector@*")
    assert reads["units_inventory"][2:] == (
        "list-units", "--all", "--plain", "--no-legend", "--full", *patterns,
    )  # fmt: skip
    assert reads["unit_files_inventory"][2:] == (
        "list-unit-files", "--plain", "--no-legend", "--full", *patterns,
    )  # fmt: skip
    assert len(row.bus_reads) == 6 and row.bus_snapshot_budget_s == 15
    assert 2 + 1.5 * len(row.bus_reads) <= 15
