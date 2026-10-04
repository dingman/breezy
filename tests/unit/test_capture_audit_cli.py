"""AUT-1 WP5 stage 2b W3: the ``breezy-capture-audit`` entry point (S2-R8).

Split out of ``test_capture_audit.py`` (S2-R43); the helpers are in
``tests/support/capture_audit_run_support.py``.
"""

import datetime as dt
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from breezy.analysis import capture_audit as audit
from breezy.analysis import capture_audit_cli as cli
from breezy.analysis import capture_audit_host as host
from breezy.analysis import capture_audit_inputs as inputs
from breezy.analysis.capture_audit_model import (
    DayStatus,
)
from breezy.analysis.capture_node_log import scan_node_log
from breezy.persistence.autonomy.capture_epoch import write_epoch_once
from tests.support import capture_audit_fixtures as fx
from tests.support import capture_audit_w3_fixtures as w3
from tests.support.capture_audit_run_support import (
    Offers,
)
from tests.support.capture_audit_run_support import (
    fake_gather as _fake_gather,
)
from tests.support.capture_audit_run_support import (
    quiet_duties as _quiet_duties,
)
from tests.support.capture_audit_w3_fixtures import leg_result, stub_legs

DAY = fx.DAY
NS = w3.NS
TODAY = DAY + dt.timedelta(days=1)


# -- the entry point (S2-R8) -------------------------------------------------------------------


def _argv(root: Path, *extra: str) -> list[str]:
    return ["--data-root", str(root), *extra]


def _clock(hour: int, minute: int = 0) -> Any:
    return lambda: w3.day_ns(TODAY, hour, minute)


def test_bus_snapshot_read_before_any_scan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """MUTATION: bus snapshot read after the scan. The wrapper's snapshot goes stale, so ``main``
    reads it before anything else, including the first log scan."""
    root = w3.full_world(tmp_path, monkeypatch)
    events: list[str] = []
    real_consume = host._consume_snapshot
    real_scan = scan_node_log

    def consume(data_root: Path, now_ns: int) -> Any:
        events.append("bus")
        return real_consume(data_root, now_ns)

    def scan(path: Path, **kw: Any) -> Any:
        events.append("scan")
        return real_scan(path, **kw)

    monkeypatch.setattr(host, "_consume_snapshot", consume)
    monkeypatch.setattr(inputs, "scan_node_log", scan)
    stub_legs(monkeypatch)
    _quiet_duties(monkeypatch)
    w3.FakeMarkers.planted = {}
    code = cli._main(_argv(root, "--family-id", w3.FAMILY), offer=Offers(), clock=lambda: w3.NOW_NS)
    assert events[0] == "bus" and events.count("bus") == 1  # read once, cached for every day
    assert "scan" in events and events.index("bus") < events.index("scan")
    assert code in (0, 1)


def test_a_stale_bus_snapshot_is_each_days_error_and_masked_before_the_epoch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.make_root(tmp_path)
    w3.install(monkeypatch, root, snapshot=False)
    w3.plant_snapshot(root, ts_ns=w3.NOW_NS - 3600 * NS)  # an hour old: aged out
    stub_legs(monkeypatch)
    _quiet_duties(monkeypatch)
    w3.write_epoch(root, epoch_ns=w3.day_ns(DAY - dt.timedelta(days=3)))  # three days before D
    code = cli._main(_argv(root, "--family-id", w3.FAMILY), offer=Offers(), clock=lambda: w3.NOW_NS)
    statuses = audit._audited_statuses(root, w3.FAMILY)
    assert code == 1
    assert statuses[DAY] is DayStatus.ERROR
    assert {s for d, s in statuses.items() if d < DAY - dt.timedelta(days=3)} <= {
        DayStatus.PRE_CAPTURE
    }


def test_the_cli_defers_inside_the_launch_window_but_still_reads_the_snapshot_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.make_root(tmp_path)
    w3.install(monkeypatch, root)
    ran: list[int] = []
    monkeypatch.setattr(cli, "run_audit", w3.recording(ran))
    code = cli._main(_argv(root, "--family-id", w3.FAMILY), offer=Offers(), clock=_clock(16, 40))
    assert code == 0 and ran == []
    assert not (
        root / w3.SNAP_BIND / ".bus_snapshot" / f"{w3.INVOCATION}.json"
    ).exists()  # consumed


@pytest.mark.parametrize(
    ("hour", "minute", "runs"), [(13, 50, 1), (16, 29, 0), (17, 10, 1), (16, 30, 0)]
)
def test_cli_defers_inside_launch_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hour: int, minute: int, runs: int
) -> None:
    """The worst case is ``flock -w 600`` plus ``TimeoutStartSec=1500`` from the start instant."""
    root = w3.make_root(tmp_path)
    w3.install(monkeypatch, root)
    calls: list[int] = []
    monkeypatch.setattr(cli, "run_audit", w3.recording(calls))
    cli._main(_argv(root, "--family-id", w3.FAMILY), offer=Offers(), clock=_clock(hour, minute))
    assert len(calls) == runs


def test_the_cli_window_constants_are_the_plan_unit_numbers() -> None:
    assert (cli.FLOCK_WAIT_S, cli.TIMEOUT_START_S) == (600, 1500)


def test_the_default_offer_returns_false_so_an_alert_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = w3.make_root(tmp_path)
    w3.install(monkeypatch, root)
    stub_legs(monkeypatch, R1=leg_result("R1", "FAIL", "capture_missing"))
    _quiet_duties(monkeypatch)
    _fake_gather(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["x"])
    monkeypatch.setattr(time, "time_ns", lambda: w3.NOW_NS)
    assert cli._undeliverable_offer("CAPTURE_JOIN_GAP", "CRITICAL", "day=x") is False
    code = cli.main(_argv(root, "--family-id", w3.FAMILY))
    assert code == 1
    assert "CAPTURE_JOIN_GAP" in capsys.readouterr().err


def test_families_are_enumerated_by_construction_from_epoch_files_and_explicit_ids(
    tmp_path: Path,
) -> None:
    root = w3.make_root(tmp_path)
    for family in ("pm_us_a", "pm_us_b"):
        write_epoch_once(root, family_id=family, node_boot_id="b", build_sha="0" * 40, now_ns=1)
    assert cli.families_by_construction(root, ["pm_us_c", "pm_us_a"]) == (
        "pm_us_a",
        "pm_us_b",
        "pm_us_c",
    )
    assert cli.families_by_construction(w3.make_root(tmp_path / "empty"), []) == ()


def test_unknown_family_fill_is_enumerated_by_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A family that only has an epoch file is audited without being named."""
    root = w3.make_root(tmp_path)
    w3.install(monkeypatch, root)
    write_epoch_once(root, family_id="orphan_fam", node_boot_id="b", build_sha="0" * 40, now_ns=1)
    seen: list[str] = []

    def run_for(root_: Path, family: str, *a: Any, **k: Any) -> int:
        seen.append(family)
        return 0

    monkeypatch.setattr(cli, "run_audit", run_for)
    cli._main(_argv(root), offer=Offers(), clock=lambda: w3.NOW_NS)
    assert seen == ["orphan_fam"]


def test_a_malformed_family_id_is_refused_by_the_parser(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        cli._main(_argv(tmp_path, "--family-id", "../x"), offer=Offers(), clock=lambda: w3.NOW_NS)


def test_no_family_means_nothing_to_audit_and_exit_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.make_root(tmp_path)
    w3.install(monkeypatch, root)
    assert cli._main(_argv(root), offer=Offers(), clock=lambda: w3.NOW_NS) == 0


def test_the_cli_imports_no_venue_adapter_and_makes_no_network_call() -> None:
    code = (
        "import sys\n"
        "import breezy.analysis.capture_audit_cli\n"
        "bad = sorted(m for m in sys.modules if m.startswith('breezy.adapters')"
        " or m in ('httpx', 'requests', 'aiohttp', 'urllib3'))\n"
        "print(bad)\n"
        "raise SystemExit(1 if bad else 0)\n"
    )
    env = {**os.environ, "PYTHONPATH": str(Path(audit.__file__).parents[2])}
    done = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stdout + done.stderr


def test_the_audit_modules_are_judged_non_vacuous_by_the_closure_lint() -> None:
    from tests.support.capture_closure_lint import AUT1_WRITE_AUTHORITY

    rows = {row.module: row for row in AUT1_WRITE_AUTHORITY}
    for name in (
        "capture_audit",
        "capture_audit_inputs",
        "capture_audit_cache",
        "capture_audit_host",
    ):
        assert rows[f"breezy.analysis.{name}"].min_calls >= 70
    assert len(rows["breezy.analysis.capture_audit_host"].argvs) == 3
