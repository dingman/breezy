"""AUT-6: the 2026-10-09 09:00Z recorder rotation, replayed from the REAL journal entries.

The fixture is ``journalctl --user -o json`` of ``breezy-quote-tape.service`` and
``breezy-quote-tape-rotate.service`` over 08:59:50..09:00:20 UTC (recorder stdout text stripped).
The live 09:01Z pass paged ``daemon_invocation_changed_unexplained`` for this clean rotation.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from breezy.runtime.unit_health_daemon_support import parse_entry_line
from tests.support.unit_health_daemon_fixtures import QUOTE_TAPE, ROTATE
from tests.support.unit_health_daemon_world import World
from tests.support.unit_health_fixtures import NS, show_block

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "unit_health"
    / "quote_tape_rotate_2026-10-09.jsonl"
)
OLD_INVOCATION = "3ea3b54d06d94f75b315fba16942ee5a"
NEW_INVOCATION = "c74d9e163e494cb896a93e24f0bf76a3"
PASS_BEFORE = dt.datetime(2026, 10, 9, 8, 51, 0, 536_000, tzinfo=dt.UTC)
PASS_AFTER = dt.datetime(2026, 10, 9, 9, 1, 0, 412_160, tzinfo=dt.UTC)


def _ns(moment: dt.datetime) -> int:
    return int(moment.timestamp()) * NS + moment.microsecond * 1000


def _recorder(invocation: str, enter: str) -> str:
    return show_block(
        QUOTE_TAPE,
        Restart="always",
        Type="notify",
        ActiveState="active",
        SubState="running",
        InvocationID=invocation,
        NRestarts="0",
        ActiveEnterTimestamp=enter,
    )


def _rotate_block() -> str:
    # The values `systemctl --user show` printed after the run (a oneshot: no ActiveEnterTimestamp).
    return show_block(
        ROTATE,
        Result="success",
        ExecMainStartTimestamp="Fri 2026-10-09 09:00:00 UTC",
        InvocationID="a39822a2b2634f64b2c4d53c0f71c6a0",
    )


def _world(tmp_path: Path) -> World:
    w = World(tmp_path)
    w.journal.add([parse_entry_line(ln) for ln in FIXTURE.read_text().splitlines() if ln.strip()])
    w.h.clock.now_ns = _ns(PASS_BEFORE)
    w.units = [_recorder(OLD_INVOCATION, "Thu 2026-10-08 09:00:10 UTC")]
    assert w.run(0).pass_result in {"OK", "FINDINGS"}
    w.h.clock.now_ns = _ns(PASS_AFTER)
    w.units = [_recorder(NEW_INVOCATION, "Fri 2026-10-09 09:00:10 UTC"), _rotate_block()]
    return w


def test_the_real_09_00z_rotation_is_explained_by_the_rotate_run(tmp_path: Path) -> None:
    w = _world(tmp_path)
    w.run(0)
    assert "daemon_invocation_changed_unexplained" not in w.events
    assert w.events == []


def test_the_rotate_run_is_invisible_without_its_explicit_name_in_the_show_read(
    tmp_path: Path,
) -> None:
    """Root cause 2026-10-09: ``systemctl show -- 'breezy-*'`` does not list an inactive oneshot,
    so the pass had no rotate block and could not explain. The recorder change then pages."""
    w = _world(tmp_path)
    w.units = [_recorder(NEW_INVOCATION, "Fri 2026-10-09 09:00:10 UTC")]  # the glob-only snapshot
    w.run(0)
    assert w.events == ["daemon_invocation_changed_unexplained"]


def test_the_health_show_read_names_the_rotate_unit_explicitly() -> None:
    from breezy.runtime.autonomy_sandbox.table import AUTONOMY_BWRAP_TABLE
    from breezy.runtime.unit_health_daemons import ROTATE_UNIT

    row = AUTONOMY_BWRAP_TABLE["breezy-autonomy-health"]
    (show,) = [r for r in row.bus_reads if r.name == "units_show"]
    assert ROTATE_UNIT in show.argv[show.argv.index("--") + 1 :]


def test_the_08_31z_lamp_trigger_mid_run_is_graced_with_its_real_properties() -> None:
    """The 08:31Z pass saw ``us-source-collector@lamp.timer`` with no next elapse while its service
    (Type=exec, so ``active`` from 08:31:00) was running; the X-15 grace now forgives that."""
    from breezy.runtime.monitor_watch_timers import _check_block

    moment = dt.datetime(2026, 10, 9, 8, 31, 0, 600_000, tzinfo=dt.UTC)
    timer = {
        "UnitFileState": "enabled",
        "ActiveState": "active",
        "LastTriggerUSec": "Fri 2026-10-09 08:31:00 UTC",
        "ActiveEnterTimestamp": "Thu 2026-10-08 12:00:00 UTC",
        "NextElapseUSecRealtime": "n/a",
    }
    service = {"ActiveState": "active", "ActiveEnterTimestamp": "Fri 2026-10-09 08:31:00 UTC"}
    findings, unreadable = _check_block(
        "us-source-collector@lamp.timer",
        timer,
        interval_s=3600,
        monotonic=False,
        now_ns=_ns(moment),
        today="2026-10-09",
        service=service,
    )
    assert [f.kind for f in findings] == [] and unreadable == []
