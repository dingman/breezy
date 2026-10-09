"""AUT-6 WP3 S4: daemon and invocation rules, intraday-stage classification, build-side marker.

Plan r15 section 3.9 (auto-restarted daemons, unexplained InvocationID change, how each replaced
invocation ended, build-side restarts) and section 3.4.2 (the demand table, the independent
evaluate rule, only ended invocations judged, episode dedupe). Every test drives the pass through
its seams: a bus snapshot, a fake journal, an alert recorder and a delivered-record set. Nothing
here touches a ``breezy-*`` unit; the one real-journal test uses a ``claude-aut6-*`` scratch unit.
"""

from __future__ import annotations

import json
import shutil
import stat
import subprocess
import time
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from breezy.runtime import unit_health, unit_health_model
from breezy.runtime.unit_health import PassResult, unexplained_for_day
from breezy.runtime.unit_health_daemons import (
    MSG_EXIT,
    MSG_FAILED,
    MSG_STARTED,
    MSG_STOPPING,
    DaemonWiring,
    Ending,
    SubprocessDaemonJournal,
    UnitEntry,
    classify_ending,
    ended_invocation_ids,
    parse_systemd_timestamp,
    run_mark_buildside_restart,
    write_buildside_marker,
)
from breezy.runtime.unit_health_intraday import (
    EVALUATE_STAGE_BUDGET_S,
    INTRADAY_INVOCATION_MAX_S,
    InvocationJudgment,
    demand_summary_counters,
    judge_invocation,
)
from breezy.runtime.unit_health_journal import JournalError, Run, RunResult
from breezy.runtime.unit_health_store import HealthStore, day_of_ns
from tests.support.unit_health_daemon_fixtures import (
    INTRADAY,
    QUOTE_TAPE,
    ROTATE,
    FakeDaemonJournal,
    at_us,
    crash_entries,
    exited,
    failed,
    intraday_run,
    line,
    rotate_stop_entries,
    scheduled,
    started,
    stopping,
    systemd_ts,
)
from tests.support.unit_health_fixtures import (
    NOW_NS,
    NS,
    inv,
    make_snapshot,
    show_block,
)
from tests.unit.test_unit_health import Harness, harness

DAY_S = 86_400
NODE = "breezy-trade-supervisor.service"


# --------------------------------------------------------------------------- the world


class World:
    """One health pass loop over a mutable set of unit blocks and a fake journal."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.units: list[str] = []
        self.journal = FakeDaemonJournal()
        self.alerts_root = tmp_path / "alerts"
        self.h: Harness = harness(
            tmp_path,
            snapshot=self._snapshot,
            daemons=DaemonWiring(self.journal, alerts_root=self.alerts_root),
        )

    def _snapshot(self) -> Any:
        return make_snapshot(now_ns=self.h.clock.now_ns, units=self.units)

    @property
    def store(self) -> HealthStore:
        return self.h.store

    @property
    def events(self) -> list[str]:
        return self.h.alerts.events

    def run(self, advance_s: float = 600) -> PassResult:
        self.h.clock.advance(advance_s)
        return self.h.run()

    def deliver_all(self) -> None:
        for payload in self.h.alerts.payloads:
            self.h.delivered.add((payload.event, payload.site))

    def payloads(self, event: str) -> list[Any]:
        return [p for p in self.h.alerts.payloads if p.event == event]

    def records(self, event: str) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        for path in sorted(self.store.root.glob("*/*__class.json")):
            body = json.loads(path.read_text())
            if body.get("kind") == "finding" and body.get("finding") == event:
                found.append(body)
        return found


def qt_block(
    n: int, *, restarts: int = 0, aet: float = -3600, unit: str = QUOTE_TAPE, **props: str
) -> str:
    return show_block(
        unit,
        Restart="always",
        Type="notify",
        ActiveState="active",
        SubState="running",
        InvocationID=inv(n),
        NRestarts=str(restarts),
        ActiveEnterTimestamp=systemd_ts(aet),
        **props,
    )


def rotate_block(start: float, result: str = "success") -> str:
    return show_block(ROTATE, ExecMainStartTimestamp=systemd_ts(start), Result=result)


def baseline(w: World, n: int = 1, *, restarts: int = 0, unit: str = QUOTE_TAPE) -> None:
    w.units = [qt_block(n, restarts=restarts, unit=unit)]
    result = w.run(0)
    assert result.pass_result in {"OK", "FINDINGS"}, result
    assert w.events == []


@pytest.fixture
def w(tmp_path: Path) -> World:
    return World(tmp_path)


def _is_daemon_event(event: str) -> bool:
    return event.startswith("daemon_")


# --------------------------------------------------------------------------- F7: NRestarts


def test_nrestarts_growth_on_restart_always_daemon_is_22_finding(w: World) -> None:
    baseline(w)
    w.journal.add(started(QUOTE_TAPE, inv(1), 90), stopping(QUOTE_TAPE, inv(1), 100))
    w.units = [qt_block(2, restarts=1, aet=101)]
    result = w.run()
    grown = w.payloads("daemon_auto_restarted")
    assert len(grown) == 1
    assert grown[0].severity == "CRITICAL"  # a data-path unit
    assert result.pass_result == "FINDINGS"
    body = w.records("daemon_auto_restarted")[0]
    assert body["unit"] == QUOTE_TAPE
    assert body["metrics"]["nrestarts_delta"] == "1"
    # keyed (unit, InvocationID): a repeat pass with the same state pages nothing more
    w.run()
    assert len(w.payloads("daemon_auto_restarted")) == 1


def test_nrestarts_drop_rebaselines_without_finding(w: World) -> None:
    baseline(w, restarts=5)
    w.units = [qt_block(1, restarts=0)]
    w.run()
    assert w.events == []
    # and the new baseline stands: growth from 0 is then a finding
    w.journal.add(stopping(QUOTE_TAPE, inv(1), 700))
    w.units = [qt_block(2, restarts=1, aet=701)]
    w.run()
    assert "daemon_auto_restarted" in w.events


def test_restart_always_scope_is_read_from_the_unit_not_a_name_list(w: World) -> None:
    w.units = [show_block("breezy-portfolio-roi.service", Restart="no", NRestarts="0")]
    w.run(0)
    w.units = [show_block("breezy-portfolio-roi.service", Restart="no", NRestarts="4")]
    w.run()
    assert w.events == []


def test_unreadable_nrestarts_or_invocation_makes_the_pass_unknown(w: World) -> None:
    w.units = [qt_block(1)]
    w.run(0)
    w.units = [qt_block(1).replace("NRestarts=0", "NRestarts=")]
    result = w.run()
    assert result.pass_result == "UNKNOWN"
    assert "daemon_property_unreadable" in result.unknown_reasons
    assert w.events == []


def test_journal_error_in_the_daemon_rules_makes_the_pass_unknown(w: World) -> None:
    baseline(w)
    w.journal.fail_with = JournalError("timed_out")
    w.units = [qt_block(2, restarts=1, aet=101)]
    result = w.run()
    assert result.pass_result == "UNKNOWN"
    assert "journal:timed_out" in result.unknown_reasons


# --------------------------------------------------------------------------- S4 pair


def test_invocation_change_without_selfheal_or_rotate_is_22_finding(w: World) -> None:
    baseline(w)
    w.journal.add(rotate_stop_entries(QUOTE_TAPE, inv(1), 100))
    w.units = [qt_block(2, aet=101)]  # same NRestarts, a new invocation, no rotate run
    w.run()
    changed = w.payloads("daemon_invocation_changed_unexplained")
    assert len(changed) == 1 and changed[0].severity == "CRITICAL"
    body = w.records("daemon_invocation_changed_unexplained")[0]
    assert inv(1) in body["ended_invocations"] and body["new_invocation_id"] == inv(2)
    assert body["key"] == f"daemon_invocation_changed_unexplained-{inv(2)}"


def test_invocation_change_explained_by_rotate_run_or_member_watchdog_ending(
    w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    # (ii) the 09:00Z rotate run explains a recorder id change
    baseline(w)
    w.journal.add(rotate_stop_entries(QUOTE_TAPE, inv(1), 100))
    w.units = [qt_block(2, aet=101), rotate_block(95)]
    w.run()
    assert w.events == []


def test_member_watchdog_ending_is_21_not_22(w: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(unit_health_model, "WATCHDOG_DAEMON_UNITS", frozenset({QUOTE_TAPE}))
    baseline(w)
    # systemd's shape under WatchdogSignal=SIGTERM: unit-failed + scheduled restart, no exit entry
    w.journal.add(
        started(QUOTE_TAPE, inv(1), 50),
        failed(QUOTE_TAPE, inv(1), 100, "watchdog"),
        scheduled(QUOTE_TAPE, inv(1), 100.1),
    )
    w.units = [qt_block(2, restarts=1, aet=101)]
    w.run()
    # #21 reports the ending (WP4); neither daemon_crashed nor daemon_auto_restarted nor unexplained
    assert [e for e in w.events if _is_daemon_event(e)] == []


def test_crash_plus_nrestarts_reset_with_neither_rotate_nor_watchdog_fails(w: World) -> None:
    baseline(w, restarts=3)
    w.journal.add(crash_entries(QUOTE_TAPE, inv(1), 100))
    w.units = [qt_block(2, restarts=0, aet=105)]  # an explicit start reset the counter
    w.run()
    assert "daemon_crashed" in w.events


def test_watchdog_result_on_a_non_member_stays_daemon_crashed(w: World) -> None:
    baseline(w)
    w.journal.add(
        started(QUOTE_TAPE, inv(1), 50),
        failed(QUOTE_TAPE, inv(1), 100, "watchdog"),
        scheduled(QUOTE_TAPE, inv(1), 100.1),
    )
    w.units = [qt_block(2, restarts=1, aet=101)]
    w.run()
    assert "daemon_crashed" in w.events


def test_rotate_started_before_stored_invocation_does_not_explain_change(w: World) -> None:
    w.units = [qt_block(1, aet=-30)]  # the stored invocation began 30 s before the pass
    w.run(0)
    w.journal.add(rotate_stop_entries(QUOTE_TAPE, inv(1), 100))
    # the rotate run started before the stored invocation's ActiveEnterTimestamp
    w.units = [qt_block(2, aet=101), rotate_block(-100)]
    w.run()
    assert "daemon_invocation_changed_unexplained" in w.events


def test_failed_rotate_run_does_not_explain(w: World) -> None:
    baseline(w)
    w.journal.add(rotate_stop_entries(QUOTE_TAPE, inv(1), 100))
    w.units = [qt_block(2, aet=101), rotate_block(95, result="exit-code")]
    w.run()
    assert "daemon_invocation_changed_unexplained" in w.events


def test_rotate_explains_only_the_quote_tape_recorder(w: World) -> None:
    baseline(w, unit=NODE)
    w.journal.add(rotate_stop_entries(NODE, inv(1), 100))
    w.units = [qt_block(2, aet=101, unit=NODE), rotate_block(95)]
    w.run()
    assert "daemon_invocation_changed_unexplained" in w.events


# --------------------------------------------------------------------------- LOW-2: markers


def _marker_root(w: World) -> Path:
    return w.store.root


def _marker(w: World, t: float, unit: str = QUOTE_TAPE) -> Path | None:
    return write_buildside_marker(
        _marker_root(w), unit, reason="deploy", commit="abc1234", ts_ns=NOW_NS + int(t * NS)
    )


def test_invocation_change_with_buildside_marker_pages_warn_not_critical(w: World) -> None:
    baseline(w)
    assert _marker(w, 98) is not None
    w.journal.add(rotate_stop_entries(QUOTE_TAPE, inv(1), 100))
    w.units = [qt_block(2, aet=101)]
    w.run()
    assert w.events == ["daemon_restarted_buildside"]
    assert w.h.alerts.payloads[0].severity == "WARNING"
    # explained by its delivered alert, not before
    day = day_of_ns(w.h.clock.now_ns)
    assert unexplained_for_day(w.store, day, w.h.env.delivered) != ()
    w.deliver_all()
    assert unexplained_for_day(w.store, day, w.h.env.delivered) == ()


@pytest.mark.parametrize("case", ["outside_window", "unreadable_dir", "wrong_unit", "no_marker"])
def test_buildside_marker_outside_window_or_unreadable_keeps_critical(w: World, case: str) -> None:
    baseline(w)
    if case == "outside_window":
        _marker(w, -2000)
    elif case == "unreadable_dir":
        _marker_root(w).joinpath("buildside_restart").write_text("not a directory")
    elif case == "wrong_unit":
        _marker(w, 98, unit=NODE)
    w.journal.add(rotate_stop_entries(QUOTE_TAPE, inv(1), 100))
    w.units = [qt_block(2, aet=101)]
    w.run()
    assert w.events == ["daemon_invocation_changed_unexplained"]
    assert w.h.alerts.payloads[0].severity == "CRITICAL"


def test_a_marker_never_downgrades_a_crash(w: World) -> None:
    baseline(w)
    _marker(w, 98)
    w.journal.add(crash_entries(QUOTE_TAPE, inv(1), 100))
    w.units = [qt_block(2, restarts=1, aet=101)]
    w.run()
    assert "daemon_crashed" in w.events
    assert "daemon_restarted_buildside" not in w.events


def test_a_marker_that_matches_no_change_is_ignored(w: World) -> None:
    baseline(w)
    _marker(w, 98)
    w.units = [qt_block(1)]
    w.run()
    assert w.events == []


def test_mark_buildside_restart_cli_writes_write_once_marker(tmp_path: Path) -> None:
    root = tmp_path / "unit_health"
    argv = [
        "--mark-buildside-restart",
        QUOTE_TAPE,
        "--reason",
        "merge 79c21fde",
        "--commit",
        "79c21fde",
    ]
    code = run_mark_buildside_restart(argv, root=root, now_ns=lambda: NOW_NS)
    assert code == 0
    files = sorted((root / "buildside_restart").glob("*/*.json"))
    assert [f.name for f in files] == [f"{NOW_NS}_{QUOTE_TAPE}.json"]
    assert files[0].parent.name == day_of_ns(NOW_NS)
    assert stat.S_IMODE(files[0].stat().st_mode) == 0o444
    body = json.loads(files[0].read_text())
    assert body == {
        "schema": "buildside_restart/v1",
        "ts_ns": NOW_NS,
        "unit": QUOTE_TAPE,
        "reason": "merge 79c21fde",
        "commit": "79c21fde",
    }
    # never rewritten: a second call in the same nanosecond makes a new file, the first is intact
    first = files[0].read_text()
    assert run_mark_buildside_restart(argv, root=root, now_ns=lambda: NOW_NS) == 0
    files = sorted((root / "buildside_restart").glob("*/*.json"))
    assert len(files) == 2 and files[0].read_text() == first


@pytest.mark.parametrize(
    "argv",
    [
        ["--mark-buildside-restart", "not-a-unit", "--reason", "r", "--commit", "abc1234"],
        ["--mark-buildside-restart", QUOTE_TAPE, "--reason", "", "--commit", "abc1234"],
        ["--mark-buildside-restart", QUOTE_TAPE, "--reason", "r\nx", "--commit", "abc1234"],
        ["--mark-buildside-restart", QUOTE_TAPE, "--reason", "r", "--commit", "not hex!"],
        ["--mark-buildside-restart", QUOTE_TAPE, "--reason", "r"],
    ],
)
def test_mark_buildside_restart_cli_refuses_bad_input_and_writes_nothing(
    tmp_path: Path, argv: list[str]
) -> None:
    root = tmp_path / "unit_health"
    assert run_mark_buildside_restart(argv, root=root, now_ns=lambda: NOW_NS) == 2
    assert not (root / "buildside_restart").exists()


def test_health_cli_routes_the_mark_subcommand_to_the_marker_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from breezy.runtime import autonomy_health_cli, unit_health_daemons

    seen: list[list[str]] = []

    def fake(argv: Sequence[str]) -> int:
        seen.append(list(argv))
        return 0

    monkeypatch.setattr(unit_health_daemons, "run_mark_buildside_restart", fake)
    assert autonomy_health_cli.run_mark_buildside(["--mark-buildside-restart", QUOTE_TAPE]) == 0
    assert seen == [["--mark-buildside-restart", QUOTE_TAPE]]


def test_buildside_marker_has_its_one_writer_row() -> None:
    from tests.unit.autonomy_writer_table import AUTONOMY_FILE_WRITERS

    rows = [r for r in AUTONOMY_FILE_WRITERS if "buildside_restart" in r.path]
    assert len(rows) == 1
    assert rows[0].mechanism == "write_once"
    assert "--mark-buildside-restart" in rows[0].writers


# --------------------------------------------------------------------------- Y1


@pytest.mark.parametrize(
    "pattern", ["crash_autorestart_then_rotate", "rotate_then_crash", "self_exit_status_0"]
)
def test_crash_autorestart_then_rotate_in_one_interval_is_daemon_crashed(
    w: World, pattern: str
) -> None:
    baseline(w)
    if pattern == "crash_autorestart_then_rotate":
        w.journal.add(crash_entries(QUOTE_TAPE, inv(1), 100))
        w.journal.add(rotate_stop_entries(QUOTE_TAPE, inv(2), 300))
        crashed = inv(1)
        w.units = [qt_block(3, restarts=0, aet=301), rotate_block(295)]
    elif pattern == "rotate_then_crash":
        w.journal.add(rotate_stop_entries(QUOTE_TAPE, inv(1), 100))
        w.journal.add(crash_entries(QUOTE_TAPE, inv(2), 113))
        crashed = inv(2)
        w.units = [qt_block(3, restarts=0, aet=120), rotate_block(95)]
    else:
        w.journal.add(started(QUOTE_TAPE, inv(1), 50), exited(QUOTE_TAPE, inv(1), 100, "0"))
        crashed = inv(1)
        w.units = [qt_block(2, restarts=0, aet=101), rotate_block(95)]
    w.run()
    assert "daemon_crashed" in w.events  # regardless of any rotate run
    body = w.records("daemon_crashed")[0]
    assert body["key"] == f"daemon_crashed-{crashed}"
    assert w.payloads("daemon_crashed")[0].severity == "CRITICAL"
    if pattern == "self_exit_status_0":
        assert body["metrics"] == {"exit_code": "exited", "exit_status": "0"}


@pytest.mark.parametrize(
    ("entries", "expected"),
    [
        ([stopping("u", inv(1), 10)], Ending.STOPPED),
        ([stopping("u", inv(1), 10), exited("u", inv(1), 11, "15", "killed")], Ending.STOPPED),
        ([stopping("u", inv(1), 10), exited("u", inv(1), 11, "0")], Ending.STOPPED),
        ([stopping("u", inv(1), 10), exited("u", inv(1), 11, "143")], Ending.STOPPED),
        ([stopping("u", inv(1), 10), exited("u", inv(1), 11, "1")], Ending.CRASHED),
        ([stopping("u", inv(1), 10), exited("u", inv(1), 11, "9", "killed")], Ending.CRASHED),
        ([exited("u", inv(1), 5, "0"), stopping("u", inv(1), 10)], Ending.CRASHED),
        ([stopping("u", inv(1), 10), scheduled("u", inv(1), 11)], Ending.CRASHED),
        ([stopping("u", inv(1), 10), failed("u", inv(1), 11)], Ending.CRASHED),
        ([stopping("u", inv(1), 10, "restart")], Ending.CRASHED),
        ([exited("u", inv(1), 10, "1"), failed("u", inv(1), 10.1)], Ending.CRASHED),
        ([started("u", inv(1), 1)], Ending.UNPROVEN),
        ([], Ending.UNPROVEN),
    ],
)
def test_systemd_stop_ending_required_before_rotate_or_marker_explains(
    entries: list[UnitEntry], expected: Ending
) -> None:
    assert classify_ending("u", entries, watchdog_units=frozenset()).ending is expected


def test_watchdog_unit_failed_entry_classifies_only_for_a_member() -> None:
    entries = [failed("u", inv(1), 10, "watchdog"), scheduled("u", inv(1), 10.1)]
    assert classify_ending("u", entries, watchdog_units=frozenset({"u"})).ending is Ending.WATCHDOG
    assert classify_ending("u", entries, watchdog_units=frozenset()).ending is Ending.CRASHED
    # a member's other result stays a crash
    other = [failed("u", inv(1), 10, "exit-code")]
    assert classify_ending("u", other, watchdog_units=frozenset({"u"})).ending is Ending.CRASHED
    # DL2: a process-exit entry beside a watchdog ending changes nothing
    with_exit = [*entries, exited("u", inv(1), 9.9, "6", "dumped")]
    assert (
        classify_ending("u", with_exit, watchdog_units=frozenset({"u"})).ending is Ending.WATCHDOG
    )


def test_ended_invocation_without_journal_entries_stays_unexplained(w: World) -> None:
    baseline(w)
    w.units = [qt_block(2, aet=101), rotate_block(95)]  # the journal holds nothing at all
    w.run()
    assert w.events == ["daemon_invocation_changed_unexplained"]


def test_ended_invocations_enumerated_from_started_exit_and_stopping_entries() -> None:
    unit = QUOTE_TAPE
    entries = [
        started(unit, inv(2), 10),  # only a Started entry
        exited(unit, inv(3), 20, "1"),  # only an exit entry
        stopping(unit, inv(4), 30),  # only a Stopping entry
        started(unit, inv(5), 40),  # the current invocation
        line(unit, inv(6), 50, "plain stdout is not a lifecycle entry"),
    ]
    got = ended_invocation_ids(entries, current=inv(5), stored=inv(1))
    assert got == (inv(1), inv(2), inv(3), inv(4))
    assert ended_invocation_ids([], current=inv(5), stored=inv(5)) == ()


def test_one_explanation_per_ended_invocation(w: World) -> None:
    baseline(w)
    w.journal.add(rotate_stop_entries(QUOTE_TAPE, inv(1), 100))
    w.journal.add(rotate_stop_entries(QUOTE_TAPE, inv(2), 300))
    w.units = [qt_block(3, aet=301), rotate_block(90)]  # ONE rotate run, two stopped invocations
    w.run()
    changed = w.payloads("daemon_invocation_changed_unexplained")
    assert len(changed) == 1
    body = w.records("daemon_invocation_changed_unexplained")[0]
    assert body["ended_invocations"] == [inv(2)]  # the first stop was the rotate's


def test_crash_makes_the_stopped_ones_unexplained_too(w: World) -> None:
    baseline(w)
    w.journal.add(crash_entries(QUOTE_TAPE, inv(1), 100))
    w.journal.add(rotate_stop_entries(QUOTE_TAPE, inv(2), 300))
    w.units = [qt_block(3, aet=301), rotate_block(295)]
    w.run()
    assert sorted(e for e in w.events if _is_daemon_event(e)) == [
        "daemon_crashed",
        "daemon_invocation_changed_unexplained",
    ]


def test_daemon_findings_stay_unexplained_until_their_alert_is_delivered(w: World) -> None:
    baseline(w)
    w.journal.add(crash_entries(QUOTE_TAPE, inv(1), 100))
    w.units = [qt_block(2, restarts=1, aet=101)]
    w.run()
    day = day_of_ns(w.h.clock.now_ns)
    names = unexplained_for_day(w.store, day, w.h.env.delivered)
    assert any(n.startswith(f"{QUOTE_TAPE}__daemon_crashed-") for n in names)
    w.deliver_all()
    assert unexplained_for_day(w.store, day, w.h.env.delivered) == ()


def test_daemon_interval_replays_without_double_page(w: World) -> None:
    baseline(w)
    w.journal.add(crash_entries(QUOTE_TAPE, inv(1), 100))
    w.units = [qt_block(2, restarts=1, aet=101)]
    w.h.alerts.ok = False
    first = w.run()
    assert first.pass_result == "UNKNOWN"  # the enqueue was refused: nothing committed
    w.h.alerts.ok = True
    w.run(0)
    pages = w.events.count("daemon_crashed")
    assert pages == 2  # the refused attempt and the accepted one
    w.run(0)
    assert w.events.count("daemon_crashed") == pages


def test_parse_systemd_timestamp() -> None:
    assert parse_systemd_timestamp("Thu 2026-10-08 12:00:00 UTC") == NOW_NS
    assert parse_systemd_timestamp("") is None
    assert parse_systemd_timestamp("n/a") is None
    assert parse_systemd_timestamp("Thu 2026-10-08 12:00:00 CEST") is None


# --------------------------------------------------------------------------- journal reader


class RecordingRun:
    def __init__(self, stdout: str = "", rc: int = 0) -> None:
        self.calls: list[list[str]] = []
        self.result = RunResult(rc, stdout, False, False)

    def __call__(self, argv: Sequence[str], timeout_s: float) -> RunResult:
        self.calls.append(list(argv))
        return self.result


def _json_line(entry: UnitEntry) -> str:
    return json.dumps(
        {
            "MESSAGE_ID": entry.message_id,
            "USER_UNIT": entry.unit,
            "USER_INVOCATION_ID": entry.invocation_id,
            "__REALTIME_TIMESTAMP": str(entry.ts_us),
            "MESSAGE": entry.message,
            **entry.fields,
        }
    )


def test_daemon_journal_lifecycle_query_is_an_argv_list_with_the_three_message_ids() -> None:
    run = RecordingRun()
    SubprocessDaemonJournal(run).unit_entries(
        QUOTE_TAPE, since_us=1_000_000, until_us=9_000_000, lifecycle_only=True, timeout_s=5
    )
    argv = run.calls[0]
    assert argv[:2] == ["/usr/bin/journalctl", "--user"]
    assert f"USER_UNIT={QUOTE_TAPE}" in argv
    assert {f"MESSAGE_ID={m}" for m in (MSG_STARTED, MSG_EXIT, MSG_STOPPING)} <= set(argv)
    assert "--since=@1" in argv and "--until=@9" in argv
    assert "+" not in argv  # systemd's own entries only: no stdout lines of a chatty daemon


def test_daemon_journal_stage_query_joins_systemd_and_stdout_entries_with_or() -> None:
    run = RecordingRun()
    SubprocessDaemonJournal(run).invocation_entries(
        INTRADAY, inv(7), lifecycle_only=False, timeout_s=5
    )
    argv = run.calls[0]
    plus = argv.index("+")
    assert f"USER_INVOCATION_ID={inv(7)}" in argv[:plus]
    assert f"_SYSTEMD_INVOCATION_ID={inv(7)}" in argv[plus:]
    assert f"_SYSTEMD_USER_UNIT={INTRADAY}" in argv[plus:]


def test_daemon_journal_parses_entries_and_normalises_stdout_ids() -> None:
    systemd = _json_line(exited(QUOTE_TAPE, inv(1), 5, "3"))
    stdout = json.dumps(
        {
            "MESSAGE": "PRODUCER_INTRADAY START ts_ns=1",
            "_SYSTEMD_USER_UNIT": INTRADAY,
            "_SYSTEMD_INVOCATION_ID": inv(2),
            "__REALTIME_TIMESTAMP": str(at_us(1)),
        }
    )
    run = RecordingRun(systemd + "\n" + stdout + "\n")
    got = SubprocessDaemonJournal(run).invocation_entries(
        INTRADAY, inv(2), lifecycle_only=False, timeout_s=5
    )
    assert [(e.unit, e.invocation_id, e.message_id) for e in got] == [
        (QUOTE_TAPE, inv(1), MSG_EXIT),
        (INTRADAY, inv(2), ""),
    ]
    assert got[0].fields["EXIT_STATUS"] == "3" and got[1].message.startswith("PRODUCER_INTRADAY")


@pytest.mark.parametrize("bad", ["not json", "[1]", json.dumps({"MESSAGE": "x"})])
def test_daemon_journal_unparseable_line_is_a_journal_error(bad: str) -> None:
    run = RecordingRun(bad + "\n")
    with pytest.raises(JournalError):
        SubprocessDaemonJournal(run).unit_entries(
            QUOTE_TAPE, since_us=0, until_us=10**9, lifecycle_only=True, timeout_s=5
        )


def _fixed_run(result: RunResult) -> Run:
    def run(argv: Sequence[str], timeout_s: float) -> RunResult:
        return result

    return run


def test_daemon_journal_errors_are_never_empty_results() -> None:
    for result in (RunResult(1, "", False, False), RunResult(-9, "", True, False)):
        j = SubprocessDaemonJournal(_fixed_run(result))
        with pytest.raises(JournalError):
            j.unit_entries(QUOTE_TAPE, since_us=0, until_us=10**9, lifecycle_only=True, timeout_s=5)
    with pytest.raises(JournalError):
        SubprocessDaemonJournal(RecordingRun()).invocation_entries(
            QUOTE_TAPE, "not-an-id", lifecycle_only=True, timeout_s=5
        )


# --------------------------------------------------------------------------- intraday: pure


def _findings(
    entries: Sequence[UnitEntry], *, now_s: float = 400, activating: bool = False
) -> dict[str, dict[str, str]]:
    verdict = judge_invocation(entries, now_us=at_us(now_s), current_activating=activating)
    assert verdict is not None, "the invocation was not judged"
    return {f.finding: dict(f.metrics) for f in verdict.findings}


_OK_DEMAND = (
    "PRODUCER_INTRADAY_DEMAND wrote=0 skipped_existing=0 invalid=0 "
    "integrity_demand_write_failures=0 journal_write_failures=0 outbox_write_failures=0 "
    "deadline_hit={dh} unprocessed={un} "
    "evaluate_exit={ev} exit={ex}"
)


def _demand(dh: int = 0, un: int = 0, ev: str = "0", ex: int = 0) -> str:
    return _OK_DEMAND.format(dh=dh, un=un, ev=ev, ex=ex)


@pytest.mark.parametrize(
    ("run_kwargs", "expected"),
    [
        # exit 3, summary present: the stage's own INTEGRITY cause, already paged by the stage
        ({"exit_status": 3, "demand_summary": _demand(ex=3)}, {"demand_stage_integrity": {}}),
        # exit 5, deadline_hit=1: demand_stage_deadline_hit with metrics.unprocessed
        (
            {"exit_status": 5, "demand_summary": _demand(dh=1, un=4, ex=5)},
            {"demand_stage_deadline_hit": {"unprocessed": "4"}},
        ),
        # exit 4: no demand-row finding; the evaluate rule reports the cause
        (
            {
                "exit_status": 4,
                "eval_summary": "PRODUCER_INTRADAY wrote=0 exit=1",
                "demand_summary": _demand(ev="1", ex=4),
            },
            {"evaluate_stage_failed": {"evaluate_exit": "1"}},
        ),
        # 124 (timeout SIGTERM), summary absent
        (
            {"exit_status": 124, "demand_summary": None},
            {"demand_stage_timeout": {"exit_status": "124"}},
        ),
        # any other non-zero, START and summary both absent: bwrap_unavailable
        (
            {"exit_status": 1, "demand_start": False, "demand_summary": None},
            {"bwrap_unavailable": {"cause_hint": "unknown"}},
        ),
        # START present, summary absent
        (
            {"exit_status": 1, "demand_summary": None},
            {"demand_stage_failed": {"cause_hint": "interpreter_or_import"}},
        ),
        # any other non-zero, summary present
        (
            {"exit_status": 2, "demand_summary": _demand(ex=2)},
            {"demand_stage_failed": {"exit_status": "2"}},
        ),
    ],
)
def test_intraday_stage_outcomes_classified_from_exit_status_and_demand_line(
    run_kwargs: dict[str, Any], expected: dict[str, dict[str, str]]
) -> None:
    got = _findings(intraday_run(inv(1), 0, **run_kwargs))
    assert set(got) == set(expected)
    for name, metrics in expected.items():
        for key, value in metrics.items():
            assert got[name][key] == value, (name, key, got[name])


def test_clean_intraday_invocation_has_no_finding() -> None:
    verdict = judge_invocation(intraday_run(inv(1), 0), now_us=at_us(400), current_activating=False)
    assert isinstance(verdict, InvocationJudgment) and verdict.findings == ()


def test_bwrap_launch_failure_is_critical_bwrap_unavailable(w: World) -> None:
    w.units = [show_block(INTRADAY, ActiveState="inactive", InvocationID=inv(9))]
    w.journal.add(
        intraday_run(inv(1), -300, demand_start=False, demand_summary=None, exit_status=1)
    )
    w.journal.add(
        intraday_run(
            inv(2), -100, demand_start=False, demand_summary=None, exit_status=1, bwrap_line=True
        )
    )
    w.run(0)
    pages = w.payloads("bwrap_unavailable")
    assert len(pages) == 1 and pages[0].severity == "CRITICAL"
    hints = {r["key"]: r["metrics"]["cause_hint"] for r in w.records("bwrap_unavailable")}
    assert hints == {
        f"bwrap_unavailable-{inv(1)}": "unknown",
        f"bwrap_unavailable-{inv(2)}": "bwrap_launch",
    }


@pytest.mark.parametrize("evaluate", ["exit1", "killed100", "nolines"])
@pytest.mark.parametrize("demand", ["exit0", "exit3", "exit5", "exit124", "bwrap"])
def test_evaluate_stage_failure_reported_independently_of_demand_row(
    evaluate: str, demand: str
) -> None:
    kwargs: dict[str, Any] = {}
    if evaluate == "exit1":
        kwargs["eval_summary"] = "PRODUCER_INTRADAY wrote=0 exit=1"
        ev_label = "1"
    elif evaluate == "killed100":
        kwargs.update(eval_summary=None, eval_end_s=100.5)
        ev_label = "unrecorded"
    else:
        kwargs.update(eval_summary=None, eval_start=False)
        ev_label = "unrecorded"
    if demand == "exit0":
        kwargs["demand_summary"] = _demand(ev=ev_label)
    elif demand == "exit3":
        kwargs.update(exit_status=3, demand_summary=_demand(ev=ev_label, ex=3))
    elif demand == "exit5":
        kwargs.update(exit_status=5, demand_summary=_demand(dh=1, un=1, ev=ev_label, ex=5))
    elif demand == "exit124":
        kwargs.update(exit_status=124, demand_summary=None)
    else:
        kwargs.update(exit_status=1, demand_start=False, demand_summary=None)
    got = _findings(intraday_run(inv(1), 0, **kwargs))
    want = {
        "exit1": "evaluate_stage_failed",
        "killed100": "evaluate_stage_timeout",
        "nolines": "evaluate_stage_unrecorded",
    }[evaluate]
    assert want in got, got
    if evaluate == "exit1":
        assert got[want]["evaluate_exit"] == "1"
    # in addition to the demand-row finding, never instead of it
    demand_row = {
        "exit0": None,
        "exit3": "demand_stage_integrity",
        "exit5": "demand_stage_deadline_hit",
        "exit124": "demand_stage_timeout",
        "bwrap": "bwrap_unavailable",
    }[demand]
    if demand_row is not None:
        assert demand_row in got, got
    assert set(got) <= {want, demand_row}


def test_evaluate_positive_control_exit0_with_demand_exit0_raises_none() -> None:
    assert _findings(intraday_run(inv(1), 0)) == {}


def test_demand_line_disagreeing_with_a_clean_evaluate_summary_is_unrecorded() -> None:
    got = _findings(intraday_run(inv(1), 0, demand_summary=_demand(ev="unrecorded")))
    assert "evaluate_stage_unrecorded" in got
    got = _findings(intraday_run(inv(1), 0, eval_summary=None, demand_summary=_demand(ev="1")))
    assert "evaluate_stage_unrecorded" in got


def test_skipped_lock_held_counts_as_an_evaluate_summary_with_exit_zero() -> None:
    entries = intraday_run(inv(1), 0, eval_summary="PRODUCER_INTRADAY SKIPPED lock_held")
    assert _findings(entries) == {}


def test_evaluate_timeout_needs_the_full_budget_between_start_and_demand_start() -> None:
    short = intraday_run(inv(1), 0, eval_summary=None, eval_end_s=EVALUATE_STAGE_BUDGET_S - 1)
    assert "evaluate_stage_unrecorded" in _findings(short)
    long = intraday_run(inv(1), 0, eval_summary=None, eval_end_s=EVALUATE_STAGE_BUDGET_S)
    assert "evaluate_stage_timeout" in _findings(long)


def test_demand_stage_cause_hint_separates_bwrap_launch_from_import_crash() -> None:
    plain: dict[str, Any] = {"demand_start": False, "demand_summary": None, "exit_status": 1}
    assert (
        _findings(intraday_run(inv(1), 0, **plain))["bwrap_unavailable"]["cause_hint"] == "unknown"
    )
    with_line = _findings(intraday_run(inv(1), 0, bwrap_line=True, **plain))
    assert with_line["bwrap_unavailable"]["cause_hint"] == "bwrap_launch"
    crash = _findings(intraday_run(inv(1), 0, demand_summary=None, exit_status=1))
    assert crash["demand_stage_failed"]["cause_hint"] == "interpreter_or_import"
    # the evaluate-stage case: no evaluate START and a journaled bwrap: line
    ev = _findings(intraday_run(inv(1), 0, eval_start=False, eval_summary=None, bwrap_line=True))
    assert ev["evaluate_stage_unrecorded"]["cause_hint"] == "bwrap_launch"
    ev_plain = _findings(intraday_run(inv(1), 0, eval_start=False, eval_summary=None))
    assert "cause_hint" not in ev_plain["evaluate_stage_unrecorded"]


def test_intraday_exit_status_read_from_latest_exit_entry_by_timestamp() -> None:
    entries = intraday_run(inv(1), 0, exit_status=None, demand_summary=_demand(ex=3))
    entries += [
        exited(INTRADAY, inv(1), 30, "3"),
        exited(INTRADAY, inv(1), 25, "1"),
    ]  # out of order
    entries.append(failed(INTRADAY, inv(1), 30.1))
    got = _findings(entries)
    assert "demand_stage_integrity" in got and "demand_stage_failed" not in got
    assert got["demand_stage_integrity"]["exit_entries"] == "2"


def test_intraday_exit_entry_selected_by_command_execstart() -> None:
    entries = intraday_run(inv(1), 0, exit_status=None, demand_summary=_demand(ex=3))
    entries += [
        exited(INTRADAY, inv(1), 40, "7", command="ExecStartPre"),
        exited(INTRADAY, inv(1), 30, "3", command="ExecStart"),
        exited(INTRADAY, inv(1), 41, "9", command="ExecStartPost"),
        failed(INTRADAY, inv(1), 41.1),
    ]
    got = _findings(entries)
    assert set(got) == {"demand_stage_integrity"}
    assert "exit_entries" not in got["demand_stage_integrity"]  # one ExecStart entry: no note


@pytest.mark.parametrize(
    "ender", ["exit_entry", "unit_failed", "job_completion", "age", "not_activating"]
)
def test_intraday_invocation_ended_by_exit_entry_age_or_not_activating(ender: str) -> None:
    # an invocation with START lines only: judged (evaluate unrecorded) iff one of (a)-(c) holds
    base = intraday_run(
        inv(1), 0, eval_summary=None, demand_start=False, demand_summary=None, finish=False
    )
    now_s, activating = 30.0, True
    if ender == "exit_entry":
        base.append(exited(INTRADAY, inv(1), 29, "0"))
    elif ender == "unit_failed":
        base.append(failed(INTRADAY, inv(1), 29))
    elif ender == "job_completion":
        base.append(started(INTRADAY, inv(1), 29))
    elif ender == "age":
        now_s = 0.5 + INTRADAY_INVOCATION_MAX_S + 1
    else:
        activating = False
    verdict = judge_invocation(base, now_us=at_us(now_s), current_activating=activating)
    assert verdict is not None and verdict.findings


def test_intraday_in_flight_invocation_is_not_judged() -> None:
    base = intraday_run(
        inv(1), 0, eval_summary=None, demand_start=False, demand_summary=None, finish=False
    )
    assert judge_invocation(base, now_us=at_us(30), current_activating=True) is None
    assert judge_invocation([], now_us=at_us(30), current_activating=False) is None


def test_alert_delivery_keys_on_producer_intraday_demand_line_and_record() -> None:
    entries = intraday_run(
        inv(1),
        0,
        demand_summary=(
            "PRODUCER_INTRADAY_DEMAND wrote=2 skipped_existing=1 invalid=0 "
            "integrity_demand_write_failures=2 journal_write_failures=3 outbox_write_failures=4 "
            "deadline_hit=0 unprocessed=0 evaluate_exit=0 exit=0"
        ),
    )
    assert demand_summary_counters(entries) == {
        "integrity_demand_write_failures": 2,
        "journal_write_failures": 3,
        "outbox_write_failures": 4,
    }
    assert demand_summary_counters(intraday_run(inv(1), 0, demand_summary=None)) is None
    # the evaluate summary line is not the demand line
    assert (
        demand_summary_counters([line(INTRADAY, inv(1), 1, "PRODUCER_INTRADAY wrote=0 exit=0")])
        is None
    )


# --------------------------------------------------------------------------- intraday: the pass


def _intraday_world(w: World, current: int = 9, state: str = "inactive") -> None:
    w.units = [show_block(INTRADAY, ActiveState=state, InvocationID=inv(current))]


def test_production_yields_no_finding_without_an_intraday_unit(w: World) -> None:
    w.units = [show_block("breezy-portfolio-roi.service")]
    w.journal.add(
        intraday_run(inv(1), -300, demand_start=False, demand_summary=None, exit_status=1)
    )
    result = w.run(0)
    assert result.pass_result in {"OK", "FINDINGS"}
    assert w.events == []
    assert ("unit_entries", INTRADAY) not in w.journal.calls
    assert unit_health_model.WATCHDOG_DAEMON_UNITS == frozenset()  # filled by WP4


def test_production_env_wires_the_real_daemon_journal() -> None:
    env = unit_health.production_env(environ={}, data_root=Path("/nonexistent-aut6-s4"))
    assert isinstance(env.daemons, DaemonWiring)
    assert isinstance(env.daemons.journal, SubprocessDaemonJournal)


def test_overlapping_health_pass_does_not_page_in_flight_intraday_invocation(w: World) -> None:
    _intraday_world(w)
    w.run(0)
    # the :00:01 run is still activating at the :01 pass: START line, no summary
    partial = intraday_run(
        inv(1), 1, eval_summary=None, demand_start=False, demand_summary=None, finish=False
    )
    w.journal.add(partial)
    _intraday_world(w, current=1, state="activating")
    w.run(60)
    assert w.events == []
    assert list(w.store.root.glob("*/*__class.json")) == []
    # the run ends failing; the :11 pass judges it once
    w.journal.entries = [e for e in w.journal.entries if e.invocation_id != inv(1)]
    w.journal.add(intraday_run(inv(1), 1, exit_status=3, demand_summary=_demand(ex=3)))
    _intraday_world(w, current=2, state="inactive")
    w.run(540)
    assert len(w.records("demand_stage_integrity")) == 1
    w.run(600)
    assert len(w.records("demand_stage_integrity")) == 1


def test_demand_stage_deadline_hit_is_critical_22_finding(w: World) -> None:
    _intraday_world(w)
    w.journal.add(
        intraday_run(inv(1), -200, exit_status=5, demand_summary=_demand(dh=1, un=3, ex=5))
    )
    w.run(0)
    pages = w.payloads("demand_stage_deadline_hit")
    assert len(pages) == 1 and pages[0].severity == "CRITICAL"
    assert w.records("demand_stage_deadline_hit")[0]["metrics"]["unprocessed"] == "3"


def test_integrity_exit_3_is_recorded_but_not_paged_again_by_the_health_pass(w: World) -> None:
    _intraday_world(w)
    w.journal.add(intraday_run(inv(1), -200, exit_status=3, demand_summary=_demand(ex=3)))
    w.run(0)
    assert w.payloads("demand_stage_integrity") == []  # the stage already paged its own cause
    assert len(w.records("demand_stage_integrity")) == 1
    day = day_of_ns(w.h.clock.now_ns)
    assert unexplained_for_day(w.store, day, w.h.env.delivered) == ()


EPISODE_RUNS: dict[str, dict[str, Any]] = {
    "bwrap_unavailable": {"demand_start": False, "demand_summary": None, "exit_status": 1},
    "demand_stage_timeout": {"demand_summary": None, "exit_status": 124},
    "demand_stage_deadline_hit": {"exit_status": 5, "demand_summary": _demand(dh=1, un=2, ex=5)},
}


@pytest.mark.parametrize("finding", sorted(EPISODE_RUNS))
def test_bwrap_unavailable_and_demand_stage_timeout_paged_once_per_episode_repaged_24h(
    w: World, finding: str
) -> None:
    run = EPISODE_RUNS[finding]
    _intraday_world(w)
    w.journal.add(intraday_run(inv(1), -500, **run), intraday_run(inv(2), -200, **run))
    w.run(0)
    assert len(w.payloads(finding)) == 1  # one page for the first invocation of the episode
    first = w.payloads(finding)[0]
    # the later invocation has a classification record and an action citing the delivered page
    assert len(w.records(finding)) == 2
    action = w.store.read_action(INTRADAY, f"{finding}-{inv(2)}")
    assert action is not None and (action["event"], action["site"]) == (first.event, first.site)
    w.deliver_all()
    # a third failure the same day: still the same episode, no page
    w.journal.add(intraday_run(inv(3), 300, **run))
    w.run(600)
    assert len(w.payloads(finding)) == 1
    # 24 h after the page the episode re-pages
    w.journal.add(intraday_run(inv(4), 600 + DAY_S + 100, **run))
    w.run(DAY_S + 300)
    assert len(w.payloads(finding)) == 2


def test_episode_last_paged_ns_set_only_on_delivered(w: World) -> None:
    run = EPISODE_RUNS["bwrap_unavailable"]
    _intraday_world(w)
    w.journal.add(intraday_run(inv(1), -200, **run))
    w.run(0)
    path = w.store.root / "seen" / "_intraday_episode_bwrap_unavailable.json"
    episode = json.loads(path.read_text())
    assert episode["last_paged_ns"] is None and episode["first_ns"] == at_us(-200) * 1000
    # undelivered: the next invocation in the episode pages again (the outbox retries the first)
    w.journal.add(intraday_run(inv(2), 100, **run))
    w.run(600)
    assert len(w.payloads("bwrap_unavailable")) == 2
    w.deliver_all()
    w.journal.add(intraday_run(inv(3), 700, **run))
    w.run(600)
    assert len(w.payloads("bwrap_unavailable")) == 2
    assert json.loads(path.read_text())["last_paged_ns"] is not None


def test_episode_ends_only_on_a_judged_ended_invocation(w: World) -> None:
    bad = EPISODE_RUNS["bwrap_unavailable"]
    path = w.store.root / "seen" / "_intraday_episode_bwrap_unavailable.json"
    _intraday_world(w)
    w.journal.add(intraday_run(inv(1), -200, **bad))
    w.run(0)
    w.deliver_all()
    assert json.loads(path.read_text())["state"] == "active"
    # a clean invocation still activating at the pass does not end the episode
    w.journal.add(
        intraday_run(
            inv(2), 380, eval_summary=None, demand_start=False, demand_summary=None, finish=False
        )
    )
    _intraday_world(w, current=2, state="activating")
    w.run(400)
    assert json.loads(path.read_text())["state"] == "active"
    # judged ended at the next pass (it finished clean) it does
    w.journal.entries = [e for e in w.journal.entries if e.invocation_id != inv(2)]
    w.journal.add(intraday_run(inv(2), 380))
    _intraday_world(w, current=3, state="inactive")
    w.run(600)
    assert json.loads(path.read_text())["state"] == "ended"
    w.journal.add(intraday_run(inv(4), 1500, **bad))
    w.run(600)
    assert len(w.payloads("bwrap_unavailable")) == 2  # a new episode pages at once


def test_a_failing_invocation_between_keeps_one_episode_and_one_page(w: World) -> None:
    bad = EPISODE_RUNS["bwrap_unavailable"]
    _intraday_world(w)
    w.journal.add(intraday_run(inv(1), -300, **bad), intraday_run(inv(2), -100, **bad))
    w.run(0)
    w.deliver_all()
    w.journal.add(intraday_run(inv(3), 200, **bad))
    w.run(600)
    assert len(w.payloads("bwrap_unavailable")) == 1


def test_unreadable_episode_file_pages(w: World) -> None:
    run = EPISODE_RUNS["bwrap_unavailable"]
    _intraday_world(w)
    path = w.store.root / "seen" / "_intraday_episode_bwrap_unavailable.json"
    path.parent.mkdir(parents=True)
    path.write_text("{ not json")
    w.journal.add(intraday_run(inv(1), -200, **run))
    w.run(0)
    assert len(w.payloads("bwrap_unavailable")) == 1


# --------------------------------------------------------------------------- stage episode record


def _action_site(w: World, finding: str, n: int) -> str:
    action = w.store.read_action(INTRADAY, f"{finding}-{inv(n)}")
    assert action is not None
    return str(action["site"])


def _stage_record(w: World, body: dict[str, Any] | str) -> Path:
    path = w.alerts_root / "episodes" / "demand_stage_deadline_hit.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if isinstance(body, str) else json.dumps(body))
    return path


def _delivery_record(w: World, *, ts_ns: int, entry: str, delivered: bool = True) -> dict[str, Any]:
    body = {
        "event": "demand_stage_deadline_hit",
        "ts_ns": ts_ns,
        "delivered": delivered,
        "status_class": "2xx",
        "severity": "CRITICAL",
        "attempt_kind": "alert",
        "drill": False,
        "schema": "alert_delivery/v1",
        "site": "demand_stage:deadline",
        "outbox_entry": entry,
    }
    directory = w.alerts_root / day_of_ns(ts_ns)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{ts_ns}_redeliver_{'d' if delivered else 'f'}.json").write_text(json.dumps(body))
    if delivered:
        w.h.delivered.add((str(body["event"]), str(body["site"])))
    return body


HIT_RUN = EPISODE_RUNS["demand_stage_deadline_hit"]
ENTRY = "1791460700000000000_demand_stage_deadline_hit.json"


def _stage_queued(w: World, queued_ns: int) -> None:
    _stage_record(
        w,
        {
            "schema": "demand_stage_episode/v1",
            "first_ns": queued_ns,
            "last_queued_ns": queued_ns,
            "outbox_entry": ENTRY,
            "invocation_id": inv(1),
        },
    )


def test_stage_page_recorded_and_bound_to_episode_without_double_page(w: World) -> None:
    _intraday_world(w)
    hit_ns = (at_us(-200) + 5_000_000) * 1000
    w.journal.add(intraday_run(inv(1), -200, **HIT_RUN))
    _stage_queued(w, hit_ns)
    # while the entry is undelivered the episode is alert_pending: the health pass does not page
    w.run(0)
    assert w.payloads("demand_stage_deadline_hit") == []
    assert w.records("demand_stage_deadline_hit") == []
    # redeliver drains the entry and writes one delivered record
    _delivery_record(w, ts_ns=hit_ns + 120 * NS, entry=ENTRY)
    w.run(600)
    assert w.payloads("demand_stage_deadline_hit") == []  # exactly one page across both writers
    assert len(w.records("demand_stage_deadline_hit")) == 1
    action = w.store.read_action(INTRADAY, f"demand_stage_deadline_hit-{inv(1)}")
    assert action is not None and action["site"] == "demand_stage:deadline"
    episode = json.loads(
        (w.store.root / "seen" / "_intraday_episode_demand_stage_deadline_hit.json").read_text()
    )
    assert episode["last_paged_ns"] == hit_ns + 120 * NS
    day = day_of_ns(w.h.clock.now_ns)
    assert not [n for n in unexplained_for_day(w.store, day, w.h.env.delivered) if "deadline" in n]


def test_unreadable_stage_record_pages_again(w: World) -> None:
    _intraday_world(w)
    w.journal.add(intraday_run(inv(1), -200, **HIT_RUN))
    _stage_record(w, "{ garbage")
    w.run(0)
    assert len(w.payloads("demand_stage_deadline_hit")) == 1


def test_stage_delivery_record_binds_only_at_or_after_episode_first_ns_and_resets_on_clean_pass(
    w: World,
) -> None:
    first_ns = at_us(-200) * 1000  # the episode's first_ns: the invocation's first journal entry

    # (a) a delivered record older than first_ns is not bound: the episode pages
    _intraday_world(w)
    w.journal.add(intraday_run(inv(1), -200, **HIT_RUN))
    _stage_queued(w, first_ns - 3600 * NS)  # the stage's record still names an earlier episode
    _delivery_record(w, ts_ns=first_ns - 1, entry=ENTRY)
    w.run(0)
    assert len(w.payloads("demand_stage_deadline_hit")) == 1
    assert _action_site(w, "demand_stage_deadline_hit", 1) != "demand_stage:deadline"


def test_stage_delivery_record_at_first_ns_is_bound(w: World) -> None:
    first_ns = at_us(-200) * 1000
    _intraday_world(w)
    w.journal.add(intraday_run(inv(1), -200, **HIT_RUN))
    _stage_queued(w, first_ns + 5 * NS)
    _delivery_record(w, ts_ns=first_ns, entry=ENTRY)
    w.run(0)
    assert w.payloads("demand_stage_deadline_hit") == []
    assert _action_site(w, "demand_stage_deadline_hit", 1) == "demand_stage:deadline"


def test_stage_reset_record_does_not_bind_and_the_next_hit_pages(w: World) -> None:
    first_ns = at_us(-200) * 1000
    _intraday_world(w)
    w.journal.add(intraday_run(inv(1), -200, **HIT_RUN))
    _stage_record(
        w, {"schema": "demand_stage_episode/v1", "state": "reset", "reset_ns": first_ns - NS}
    )
    _delivery_record(w, ts_ns=first_ns + NS, entry=ENTRY)
    w.run(0)
    assert len(w.payloads("demand_stage_deadline_hit")) == 1


# --------------------------------------------------------------------------- real journal


def _user_manager_usable() -> bool:
    systemd_run = shutil.which("systemd-run")
    if systemd_run is None:
        return False
    probe = subprocess.run(
        ["/usr/bin/systemctl", "--user", "show", "-p", "Version", "--value"],
        capture_output=True,
        timeout=10,
        check=False,
    )
    return probe.returncode == 0


def test_intraday_exit_entries_on_real_journal_scratch_unit() -> None:
    """The production two-line shape on the real journal (LOW-r11-7).

    A scratch user unit ``claude-aut6-*`` (never a ``breezy-*`` unit) runs an ignored
    ``ExecStart=-`` line that exits 1 and a second line that exits 3. The journal must hold
    exactly one ``98e32220...`` entry for the invocation, ``COMMAND=ExecStart``, ``EXIT_STATUS=3``.
    """
    if not _user_manager_usable():
        pytest.skip("no usable systemd --user manager in this environment")
    name = f"claude-aut6-{uuid.uuid4().hex[:8]}"
    unit = f"{name}.service"
    began = int(time.time()) - 2
    first = (
        "echo 'PRODUCER_INTRADAY START ts_ns=1'; echo 'PRODUCER_INTRADAY wrote=0 exit=0'; exit 1"
    )
    second = "echo 'PRODUCER_INTRADAY_DEMAND START'; echo '" + _demand(ex=3) + "'; exit 3"
    try:
        run = subprocess.run(
            [
                "/usr/bin/systemd-run",
                "--user",
                f"--unit={name}",
                "--wait",
                "--collect",
                "-p",
                "Type=oneshot",
                "-p",
                f'ExecStart=-/bin/sh -c "{first}"',
                "/bin/sh",
                "-c",
                second,
            ],
            capture_output=True,
            timeout=60,
            check=False,
        )
        if b"Failed to connect" in run.stderr:
            pytest.skip("systemd-run could not reach the user bus")
        journal = SubprocessDaemonJournal()
        deadline = time.monotonic() + 10
        entries: tuple[UnitEntry, ...] = ()
        while time.monotonic() < deadline:
            seen = journal.unit_entries(
                unit,
                since_us=began * 1_000_000,
                until_us=(int(time.time()) + 5) * 1_000_000,
                lifecycle_only=True,
                timeout_s=10,
            )
            ids = {e.invocation_id for e in seen if e.message_id == MSG_EXIT}
            if ids:
                (invocation,) = ids
                entries = journal.invocation_entries(
                    unit, invocation, lifecycle_only=False, timeout_s=10
                )
                if any(e.message_id == MSG_FAILED for e in entries) and any(
                    "PRODUCER_INTRADAY_DEMAND wrote" in e.message for e in entries
                ):
                    break
            time.sleep(0.5)
        exits = [e for e in entries if e.message_id == MSG_EXIT]
        assert len(exits) == 1
        assert exits[0].fields["COMMAND"] == "ExecStart" and exits[0].fields["EXIT_STATUS"] == "3"
        verdict = judge_invocation(
            entries, now_us=int(time.time() * 1_000_000), current_activating=False
        )
        assert verdict is not None
        assert {f.finding for f in verdict.findings} == {"demand_stage_integrity"}
    finally:
        subprocess.run(
            ["/usr/bin/systemctl", "--user", "reset-failed", unit],
            capture_output=True,
            timeout=10,
            check=False,
        )


# --------------------------------------------------------------------------- misc guards


def test_daemons_module_does_not_read_the_permit_or_orders_switch() -> None:
    src = Path(unit_health.__file__).resolve().parent
    for name in ("unit_health_daemons.py", "unit_health_intraday.py"):
        text = (src / name).read_text(encoding="utf-8")
        for needle in ("BREEZY_ORDERS_ENABLED", "permit", "live_orders_gate"):
            assert needle not in text, (name, needle)
