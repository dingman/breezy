"""AUT-1 WP3 step 1 (r11, GH1): the bound constants have ONE source.

WP5 stage 3 adds the calendar, E-9 and budget cases over the six capture-unit FIXTURES in
``tests/fixtures/capture_units/`` (D1: the units are promoted into ``deploy/systemd/`` only in
stage 4, after AUT-6; nothing under ``deploy/systemd/`` is read or edited here).
"""

from __future__ import annotations

import ast
import datetime as dt
import math
import re
import shlex
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

import pytest

from breezy.adapters.polymarket_us import recorder_watchdog as rw
from breezy.analysis import capture_audit_host as host
from breezy.analysis.capture_audit_model import (
    AUDIT_EXEC_TIMEOUT_S,
    AUDIT_MARGIN_S,
    AUDIT_WORK_BUDGET_S,
)
from breezy.persistence.autonomy.capture_schedule import launch_window_guard
from breezy.runtime import node_config
from breezy.runtime.autonomy_sandbox.table import AUTONOMY_BWRAP_TABLE, BwrapRow
from breezy.runtime.autonomy_sandbox.unit_lint import (
    WRAPPER_PATH,
    lint_units,
    parse_unit,
    start_phase_bound_s,
)

BANNED_LITERALS = {4200, 4362, 4500, 4662, 4680}


def test_bound_constants_single_source() -> None:
    base = rw.UNIT_TIMEOUT_START_SEC
    expected_start = (
        base
        + node_config.QUOTE_TAPE_EMPTY_DISCOVERY_RETRY_SECS
        + rw.DISCOVERING_GRACE_S
        + rw.CONNECT_BUDGET_S
        + rw.START_EXTEND_S
    )
    assert node_config.QUOTE_TAPE_MAX_START_SECS == expected_start == 4500
    assert node_config.QUOTE_TAPE_MAX_START_SECS == node_config.recorder_max_start_s(base)
    total = rw.UNIT_TIMEOUT_STOP_SEC + rw.STOP_HOOK_BOUND_S + expected_start + rw.ROTATE_MARGIN_S
    assert total == 4662
    assert node_config.QUOTE_TAPE_ROTATE_TIMEOUT_START_SECS == math.ceil(total / 60) * 60 == 4680
    assert node_config.QUOTE_TAPE_ROTATE_TIMEOUT_START_SECS == node_config.rotate_timeout_start_s(
        node_config.QUOTE_TAPE_MAX_START_SECS
    )
    # The pinger's own extension window is the same parts: it can never grant past the budget.
    assert (
        rw.UNIT_TIMEOUT_START_SEC + rw.extension_window_s() + rw.START_EXTEND_S
        == node_config.QUOTE_TAPE_MAX_START_SECS
    )


def test_a_raised_base_moves_both_constants_together() -> None:
    assert node_config.recorder_max_start_s(240) == 4560
    assert node_config.rotate_timeout_start_s(4560) == 4740


def test_no_module_carries_a_bound_literal() -> None:
    """The derived numbers appear nowhere as literals: they are computed, in one place each."""
    for module in (node_config, rw):
        tree = ast.parse(Path(str(module.__file__)).read_text())
        literals = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, int)
        }
        assert not literals & BANNED_LITERALS, module.__name__


# -- WP5 stage 3: the six capture-unit fixtures (design r3 D12, E-9 table, S3-R45, S3-R48) ------

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "capture_units"
SETTLEMENT, AUDIT, LIVE_PROOF = (
    "breezy-capture-settlement",
    "breezy-capture-audit",
    "breezy-capture-live-proof",
)
SERVICES = (SETTLEMENT, AUDIT, LIVE_PROOF)
NS = 10**9
DAY = dt.date(2026, 10, 4)
WINDOW_START, WINDOW_END = dt.time(16, 30), dt.time(17, 10)
ACCURACY_S = 60  # systemd's default AccuracySec: a timer may fire up to a minute late
STOP_S = 5  # TimeoutStopSec
#: Per unit: (TimeoutStartSec, P = start_phase_bound_s, X = ExecStart's own K + T).
E9 = {SETTLEMENT: (300, 5, 295), AUDIT: (1500, 25, 1475), LIVE_PROOF: (300, 5, 295)}
STAND_IN = BwrapRow(
    name="breezy-autonomy-failed",
    owner_plan="AUT-6 (stand-in)",
    units=frozenset({"breezy-autonomy-failed@"}),
    binds=("cache/autonomy_failed",),
    entry_modules=("x",),
    resolves_dns=True,
    network="egress",
)


def _service(name: str) -> Path:
    return FIXTURES / f"{name}.service"


def _timer(name: str) -> Path:
    return FIXTURES / f"{name}.timer"


def _directive(path: Path, section: str, key: str) -> list[str]:
    return parse_unit(path.read_text()).values(section, key)


def _seconds(path: Path, key: str) -> int:
    (value,) = _directive(path, "Service", key)
    return int(value)


def _exec_bound(name: str) -> int:
    """ExecStart's own ``K + T`` from its ``timeout -k K T`` head."""
    (line,) = _directive(_service(name), "Service", "ExecStart")
    tokens = shlex.split(line)
    assert tokens[:2] == ["/usr/bin/timeout", "-k"], line
    return int(tokens[2]) + int(tokens[3])


def _exec_timeout(name: str) -> int:
    (line,) = _directive(_service(name), "Service", "ExecStart")
    return int(shlex.split(line)[3])


def _calendar_start(name: str) -> dt.datetime:
    (value,) = _directive(_timer(name), "Timer", "OnCalendar")
    match = re.fullmatch(r"\*-\*-\* (\d{2}):(\d{2}):00 UTC", value)
    assert match is not None, value
    return dt.datetime.combine(DAY, dt.time(int(match[1]), int(match[2])), tzinfo=dt.UTC)


def _ns(moment: dt.datetime) -> int:
    return int(moment.timestamp()) * NS


def _latest_end(start: dt.datetime, name: str, *, kill_path: bool = False) -> dt.datetime:
    bound = min(start_phase_bound_s(_service(name)) + _exec_bound(name), E9[name][0])
    return start + dt.timedelta(seconds=bound + (STOP_S if kill_path else 0))


def _table(*extra: BwrapRow) -> Mapping[str, BwrapRow]:
    return MappingProxyType({**AUTONOMY_BWRAP_TABLE, **{row.name: row for row in extra}})


def test_fixture_set_is_exactly_the_six_unit_files() -> None:
    assert sorted(p.name for p in FIXTURES.iterdir()) == sorted(
        f"{name}.{kind}" for name in SERVICES for kind in ("service", "timer")
    )


def test_no_unit_overlaps_launch_window() -> None:
    """[start (+ accuracy), + min(P + X, S) + stop] never meets [16:30Z, 17:10Z)."""
    audit_start = _calendar_start(AUDIT) + dt.timedelta(seconds=ACCURACY_S)
    audit_end = _latest_end(audit_start, AUDIT, kill_path=True)
    runs = [  # (unit, latest start)
        (name, _calendar_start(name) + dt.timedelta(seconds=ACCURACY_S))
        for name in (SETTLEMENT, AUDIT, LIVE_PROOF)
    ]
    runs.append((LIVE_PROOF, audit_end))  # the OnSuccess= run: no calendar accuracy term
    for name, latest_start in runs:
        span = min(start_phase_bound_s(_service(name)) + _exec_bound(name), E9[name][0]) + STOP_S
        assert launch_window_guard(_ns(latest_start), 0, span), name
        end = latest_start + dt.timedelta(seconds=span)
        assert end.time() < WINDOW_START, name
    assert (WINDOW_START, WINDOW_END) == (dt.time(16, 30), dt.time(17, 10))


def test_oneshot_units_use_timeout_start_sec_not_runtime_max_sec() -> None:
    for name in SERVICES:
        path = _service(name)
        assert _directive(path, "Service", "Type") == ["oneshot"], name
        assert _directive(path, "Service", "RuntimeMaxSec") == [], name
        assert _directive(path, "Service", "TimeoutSec") == [], name
        assert _seconds(path, "TimeoutStartSec") == E9[name][0], name
        assert _seconds(path, "TimeoutStopSec") == STOP_S, name  # M-STOP
        assert _directive(path, "Service", "UMask") == ["0077"], name
        assert _directive(path, "Unit", "OnFailure") == ["breezy-autonomy-failed@%n.service"]


def test_no_capture_timer_is_persistent() -> None:
    for name in SERVICES:
        timer = _timer(name)
        assert _directive(timer, "Timer", "Persistent") == [], name
        assert _directive(timer, "Timer", "AccuracySec") == [], name  # the default 60 s
        assert _directive(timer, "Timer", "Unit") == [f"{name}.service"], name


def test_every_capture_unit_and_onfailure_target_runs_through_bwrap_wrapper() -> None:
    assert lint_units(FIXTURES, _table(STAND_IN)) == ()
    for name in SERVICES:
        (line,) = _directive(_service(name), "Service", "ExecStart")
        tokens = shlex.split(line)
        assert tokens[:2] == ["/usr/bin/timeout", "-k"]
        assert WRAPPER_PATH in tokens
        assert tokens[tokens.index(WRAPPER_PATH) + 1] == name
        assert tokens[tokens.index(WRAPPER_PATH) + 2 :][:3] == [
            "/home/jon/breezy/.venv/bin/python3",
            "-I",
            "-m",
        ]
        assert name in AUTONOMY_BWRAP_TABLE
    (target,) = {
        t.split("%")[0] for n in SERVICES for t in _directive(_service(n), "Unit", "OnFailure")
    }
    assert target == "breezy-autonomy-failed@" and target in STAND_IN.units


def test_capture_units_fail_lint_only_on_aut6_scope() -> None:
    """Against the real table the only error is the missing AUT-6 notifier row
    (``onfailure_scope``), one per service: promotion waits for AUT-6 (design F3)."""
    errors = lint_units(FIXTURES, AUTONOMY_BWRAP_TABLE)
    assert sorted((e.unit, e.rule) for e in errors) == sorted(
        (f"{name}.service", "onfailure_scope") for name in SERVICES
    )


def test_the_audit_unit_takes_the_studies_lock_in_process_not_through_flock() -> None:
    (line,) = _directive(_service(AUDIT), "Service", "ExecStart")
    assert "flock" not in line
    pre = _directive(_service(AUDIT), "Service", "ExecStartPre")
    assert sum("breezy-studies.lock" in p for p in pre) == 1  # the touch line only
    assert _directive(_service(AUDIT), "Service", "Slice") == ["breezy-studies.slice"]
    for name in (SETTLEMENT, LIVE_PROOF):
        (own,) = _directive(_service(name), "Service", "ExecStart")
        assert f"/usr/bin/flock -w 30 %t/{name}.lock" in own


def test_e9_latest_end_matches_table() -> None:
    """Recompute every E-9 value from the fixtures (S3-R45, S3-R48): P + X <= S, exactly."""
    for name, (start_s, pre_s, exec_s) in E9.items():
        path = _service(name)
        assert _seconds(path, "TimeoutStartSec") == start_s
        assert start_phase_bound_s(path) == pre_s, name
        assert _exec_bound(name) == exec_s, name
        assert pre_s + exec_s <= start_s, name
    assert E9[AUDIT][1] + E9[AUDIT][2] == E9[AUDIT][0] == 1500  # exactly on the bound (S3-R48)
    assert _exec_timeout(AUDIT) == 1470 and _exec_timeout(SETTLEMENT) == 290


@pytest.mark.parametrize(
    ("name", "kill_path", "expected"),
    [
        (SETTLEMENT, False, "13:41:00"),
        (SETTLEMENT, True, "13:41:05"),
        (AUDIT, False, "14:16:00"),
        (AUDIT, True, "14:16:05"),
        (LIVE_PROOF, False, "14:41:00"),
        (LIVE_PROOF, True, "14:41:05"),
    ],
)
def test_e9_latest_end_clock_values(name: str, kill_path: bool, expected: str) -> None:
    start = _calendar_start(name) + dt.timedelta(seconds=ACCURACY_S)
    assert _latest_end(start, name, kill_path=kill_path).strftime("%H:%M:%S") == expected


def test_e9_live_proof_on_success_run_follows_the_audit_end() -> None:
    audit_end = _latest_end(_calendar_start(AUDIT) + dt.timedelta(seconds=ACCURACY_S), AUDIT)
    for end, expected in (
        (audit_end, "14:21:00"),
        (audit_end + dt.timedelta(seconds=STOP_S), "14:21:05"),
    ):
        assert _latest_end(end, LIVE_PROOF).strftime("%H:%M:%S") == expected
    assert _directive(_service(AUDIT), "Unit", "OnSuccess") == [f"{LIVE_PROOF}.service"]


def test_audit_work_budget_derives_from_unit_timeout() -> None:
    """MUTATION M-840: the unit's literal is the source of ``AUDIT_EXEC_TIMEOUT_S`` (S3-R45)."""
    assert _exec_timeout(AUDIT) == AUDIT_EXEC_TIMEOUT_S == 1470
    assert AUDIT_WORK_BUDGET_S == 1500 - 600 - 60 == 840  # the existing pin stays
    assert E9[AUDIT][0] == _seconds(_service(AUDIT), "TimeoutStartSec")
    pre = start_phase_bound_s(_service(AUDIT))
    assert pre + 5 + AUDIT_EXEC_TIMEOUT_S == _seconds(_service(AUDIT), "TimeoutStartSec")
    # DEADLINE = min(lock + 840, exec_start + 1470 - 60) <= exec_start + 1410, after a 600 s wait.
    worst = min(600 + AUDIT_WORK_BUDGET_S, AUDIT_EXEC_TIMEOUT_S - AUDIT_MARGIN_S)
    assert worst == 1410 == AUDIT_EXEC_TIMEOUT_S - AUDIT_MARGIN_S


def test_no_capture_unit_binds_or_creates_the_alerts_spool() -> None:
    """D4: no ``evidence/alerts`` before stage 4. MUTATION M-BIND adds it to a pre line."""
    for name in SERVICES:
        assert "alerts" not in _service(name).read_text().replace("breezy-autonomy-failed", "")


def test_audit_bus_snapshot_line_names_the_audit_row_and_its_budget() -> None:
    row = AUTONOMY_BWRAP_TABLE[host.AUDIT_ROW_NAME]
    pre = _directive(_service(AUDIT), "Service", "ExecStartPre")
    budget = row.bus_snapshot_budget_s
    assert budget is not None
    snapshot = f"-/usr/bin/timeout -k 2 {budget + 3} {WRAPPER_PATH} --bus-snapshot {row.name}"
    assert pre[-1] == snapshot
