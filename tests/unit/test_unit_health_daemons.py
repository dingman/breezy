"""AUT-6 WP3 S4: daemon and invocation rules and the build-side marker (plan r15 section 3.9).

Every test drives the pass through its seams (bus snapshot, fake journal, alert recorder).
"""

from __future__ import annotations

import json
import stat
from collections.abc import Sequence
from pathlib import Path

import pytest

from breezy.runtime import unit_health, unit_health_model
from breezy.runtime.unit_health import unexplained_for_day
from breezy.runtime.unit_health_daemon_support import UnitEntry
from breezy.runtime.unit_health_daemons import (
    Ending,
    classify_ending,
    ended_invocation_ids,
    parse_systemd_timestamp,
    run_mark_buildside_restart,
    write_buildside_marker,
)
from breezy.runtime.unit_health_journal import JournalError
from breezy.runtime.unit_health_store import day_of_ns
from tests.support.unit_health_daemon_fixtures import (
    QUOTE_TAPE,
    crash_entries,
    exited,
    failed,
    line,
    rotate_stop_entries,
    scheduled,
    started,
    stopping,
)
from tests.support.unit_health_daemon_world import (
    NODE,
    World,
    baseline,
    qt_block,
    rotate_block,
)
from tests.support.unit_health_fixtures import (
    NOW_NS,
    NS,
    inv,
    show_block,
)


@pytest.fixture
def w(tmp_path: Path) -> World:
    return World(tmp_path)


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


NWS = "breezy-nws-ingest.service"


def never_started(unit: str = NWS) -> str:
    return show_block(
        unit, Restart="always", ActiveState="inactive", InvocationID="", NRestarts="0"
    )


def _seen_daemon(w: World, unit: str) -> dict[str, object]:
    seen = w.store.read_seen(unit)
    assert seen is not None
    return dict(seen["daemon"])


def test_never_started_daemon_is_no_baseline_and_does_not_block_a_crash(w: World) -> None:
    w.units = [qt_block(1), never_started()]
    w.run(0)
    assert w.store.read_seen(NWS) is None  # no baseline, no state written
    w.journal.add(crash_entries(QUOTE_TAPE, inv(1), 100))
    w.units = [qt_block(2, restarts=1, aet=101), never_started()]
    result = w.run()
    assert "daemon_crashed" in w.events
    assert result.pass_result == "FINDINGS"
    assert not any(r.startswith("daemon_property_unreadable") for r in result.unknown_reasons)
    assert _seen_daemon(w, QUOTE_TAPE)["invocation_id"] == inv(2)  # the commit step ran
    assert w.store.read_seen(NWS) is None


def test_unreadable_daemon_property_is_a_per_unit_reason_and_finding_not_a_block(
    w: World,
) -> None:
    w.units = [qt_block(1), qt_block(5, unit=NWS)]
    w.run(0)
    w.journal.add(crash_entries(QUOTE_TAPE, inv(1), 100))
    bad = qt_block(5, unit=NWS).replace("NRestarts=0", "NRestarts=")
    w.units = [qt_block(2, restarts=1, aet=101), bad]
    result = w.run()
    assert result.pass_result == "UNKNOWN"
    assert f"daemon_property_unreadable:{NWS}" in result.unknown_reasons
    assert "daemon_property_unreadable" in w.events and "daemon_crashed" in w.events
    assert _seen_daemon(w, QUOTE_TAPE)["invocation_id"] == inv(2)  # not blocked: committed
    assert _seen_daemon(w, NWS)["invocation_id"] == inv(5)  # the bad unit keeps its old state
    # one page per unit and day, however many passes see it
    w.run()
    assert w.events.count("daemon_property_unreadable") == 1


def test_corrupt_daemon_baseline_is_a_finding_before_the_rebaseline(w: World) -> None:
    baseline(w)
    path = w.store.root / "seen" / f"{QUOTE_TAPE}.json"
    path.write_text(json.dumps({"unit": QUOTE_TAPE, "daemon": {"invocation_id": "nonsense"}}))
    w.units = [qt_block(1)]
    result = w.run()
    assert f"daemon_baseline_corrupt:{QUOTE_TAPE}" in result.unknown_reasons
    assert "daemon_baseline_corrupt" in w.events
    assert _seen_daemon(w, QUOTE_TAPE)["invocation_id"] == inv(1)  # re-baselined afterwards


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


def _is_daemon_event(event: str) -> bool:
    return event.startswith("daemon_")


def test_marker_cli_and_production_env_share_one_default_health_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    argv = ["--mark-buildside-restart", QUOTE_TAPE, "--reason", "r", "--commit", "abc1234"]
    assert run_mark_buildside_restart(argv, now_ns=lambda: NOW_NS) == 0
    root = tmp_path / ".local" / "share" / "breezy" / "evidence" / "unit_health"
    assert list((root / "buildside_restart").glob("*/*.json"))
    assert unit_health.production_env(environ={}).store.root == root
