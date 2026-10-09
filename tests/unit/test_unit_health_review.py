"""AUT-6 WP3 S3 review round: run_bounded, cursor fallback, multi-day rollup, ownership,
per-line parsing, journal-blind, store robustness, at-least-once action, small guards."""

from __future__ import annotations

import errno
import hashlib
import json
import subprocess
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

from breezy.runtime import unit_health, unit_health_journal
from breezy.runtime.autonomy_sandbox.table import RUN_TRANSIENT_SHOW_ARGV
from breezy.runtime.unit_health_journal import (
    JournalError,
    RunResult,
    SubprocessJournal,
    run_bounded,
)
from breezy.runtime.unit_health_model import (
    Ownership,
    UnitClass,
    WorktreesUnavailable,
    classify,
    needs_worktrees,
    ownership,
    parse_failure_line,
)
from breezy.runtime.unit_health_store import HealthStore, day_start_s
from tests.support.unit_health_fixtures import (
    DAY,
    NOW_NS,
    NS,
    REPO,
    FakeClock,
    Trace,
    failure_line,
    inv,
    make_snapshot,
    show_block,
)
from tests.unit.test_unit_health import FakeJournal, SpyStore, harness, live, site

UNIT = "breezy-portfolio-roi.service"
DAY_S = 86_400


def _recording(sink: list[float]) -> Callable[[float], Sequence[str]]:
    def worktrees(timeout_s: float) -> Sequence[str]:
        sink.append(timeout_s)
        return ()

    return worktrees


def _gone(pid: int) -> bool:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        except OSError:
            return True
        if state == "Z":
            return True
        time.sleep(0.05)
    return False


# --------------------------------------------------------------------------- 1. run_bounded


def test_run_bounded_timeout_kills_the_process_group_and_reaps(tmp_path: Path) -> None:
    pids = tmp_path / "pids"
    script = f"echo $$ > {pids}; sleep 60 & echo $! >> {pids}; wait"
    result = run_bounded(["/bin/sh", "-c", script], 0.5)
    assert (result.timed_out, result.oversize) == (True, False)
    assert result.rc == -9
    found = [int(x) for x in pids.read_text().split()]
    assert len(found) == 2
    assert all(_gone(pid) for pid in found)


def test_run_bounded_flood_is_oversize_and_the_child_is_gone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(unit_health_journal, "MAX_OUTPUT_BYTES", 200_000)
    pid_file = tmp_path / "pid"
    result = run_bounded(["/bin/sh", "-c", f"echo $$ > {pid_file}; exec yes"], 10)
    assert (result.oversize, result.timed_out) == (True, False)
    assert result.stdout == ""
    assert _gone(int(pid_file.read_text()))


def test_run_bounded_normal_output() -> None:
    result = run_bounded(["/bin/echo", "hi"], 5)
    assert result == RunResult(0, "hi\n", False, False)
    assert run_bounded(["/bin/false"], 5).rc == 1


def test_run_bounded_missing_binary_is_rc_127() -> None:
    assert run_bounded(["/nonexistent/binary"], 1).rc == 127


def test_run_bounded_closed_stdout_but_running_is_killed_and_reaped(tmp_path: Path) -> None:
    pid_file = tmp_path / "pid"
    script = f"echo $$ > {pid_file}; exec >&-; exec sleep 60"
    result = run_bounded(["/bin/sh", "-c", script], 0.5)
    assert result.timed_out is True
    assert _gone(int(pid_file.read_text()))


def test_run_bounded_without_a_stdout_pipe_does_not_assert(monkeypatch: pytest.MonkeyPatch) -> None:
    class Proc:
        pid = 0
        stdout = None

        def wait(self, timeout: float | None = None) -> int:
            return 0

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: Proc())
    assert run_bounded(["x"], 1) == RunResult(127, "", False, False)


# --------------------------------------------------------------------------- 2. cursor fallback


@pytest.mark.parametrize("reason", ["timed_out", "oversize", "parse"])
def test_failure_other_than_rejection_on_a_healthy_cursor_is_unknown_without_reset(
    tmp_path: Path, reason: str
) -> None:
    store = HealthStore(tmp_path / "unit_health")
    store.write_cursor("s=ok", NOW_NS - 60 * NS, None)

    class Failing(FakeJournal):
        def failures(self, **kw: Any) -> Any:
            self.trace.add("journal:failures")
            self.calls.append(kw)
            raise JournalError(reason)

    journal = Failing(Trace())
    h = harness(tmp_path, journal=journal, store=store)
    result = h.run()
    assert result.pass_result == "UNKNOWN"
    assert f"journal:{reason}" in result.unknown_reasons
    assert result.cursor_reset is False
    assert len(journal.calls) == 1
    assert store.cursor_reset_records(DAY) == []
    kept = store.read_cursor()
    assert kept is not None and kept.cursor == "s=ok"


def test_rejected_cursor_falls_back_from_the_stored_cursor_ts(tmp_path: Path) -> None:
    store = HealthStore(tmp_path / "unit_health")
    stored = NOW_NS - 7200 * NS
    store.write_cursor("s=old", stored, None)
    journal = FakeJournal(Trace(), fail_first_with_cursor=True)
    h = harness(tmp_path, journal=journal, store=store)
    result = h.run()
    assert result.cursor_reset is True
    assert journal.calls[1]["since_s"] == stored // NS
    assert len(store.cursor_reset_records(DAY)) == 1


def test_lost_cursor_falls_back_to_today_minus_two_days(tmp_path: Path) -> None:
    h = harness(tmp_path)
    h.run()
    assert h.journal.calls[0]["since_s"] == day_start_s(DAY) - 2 * DAY_S
    assert len(h.store.cursor_reset_records(DAY)) == 1


def test_lost_cursor_falls_back_to_the_oldest_unrolled_day(tmp_path: Path) -> None:
    store = HealthStore(tmp_path / "unit_health")
    (store.root / "2026-10-03").mkdir(parents=True)
    (store.root / "2026-10-03" / "x__class.json").write_text("{}")
    (store.root / "2026-10-04").mkdir(parents=True)
    store.write_rollup("2026-10-04", {"schema": "unit_health_day/v1"})
    h = harness(tmp_path, store=store)
    h.run()
    assert h.journal.calls[0]["since_s"] == day_start_s("2026-10-03")


def test_corrupt_cursor_uses_the_stored_ts_when_it_is_the_oldest(tmp_path: Path) -> None:
    store = HealthStore(tmp_path / "unit_health")
    store.root.mkdir(parents=True)
    hint = NOW_NS - 5 * DAY_S * NS
    (store.root / "cursor.json").write_text(json.dumps({"schema": "bad", "ts_ns": hint}))
    h = harness(tmp_path, store=store)
    h.run()
    assert h.journal.calls[0]["since_s"] == hint // NS


def test_subprocess_journal_marks_only_a_nonzero_cursor_seek_as_rejection() -> None:
    def run_with(result: RunResult) -> JournalError:
        journal = SubprocessJournal(run=lambda argv, timeout_s: result)
        with pytest.raises(JournalError) as info:
            journal.failures(after_cursor="s=x", since_s=None, timeout_s=5)
        return info.value

    assert run_with(RunResult(1, "", False, False)).cursor_rejected is True
    assert run_with(RunResult(-9, "", True, False)).cursor_rejected is False
    assert run_with(RunResult(0, "", False, True)).cursor_rejected is False
    journal = SubprocessJournal(run=lambda argv, timeout_s: RunResult(1, "", False, False))
    with pytest.raises(JournalError) as info:
        journal.failures(after_cursor=None, since_s=5, timeout_s=5)
    assert info.value.cursor_rejected is False


# --------------------------------------------------------------------------- 3. rollup across days


def _at(day: str, hh: int, mm: int) -> int:
    return (day_start_s(day) + hh * 3600 + mm * 60) * NS


def test_late_processed_failure_appears_in_the_rewritten_rollup_of_its_own_day(
    tmp_path: Path,
) -> None:
    clock = FakeClock(now_ns=_at("2026-10-09", 0, 2))
    ts_us = _at("2026-10-08", 23, 58) // 1000
    snap = live(clock, units=[show_block(UNIT, Result="exit-code", InvocationID=inv(1))])
    h = harness(
        tmp_path,
        clock=clock,
        snapshot=snap,
        entries=[failure_line(UNIT, inv(1), "exit-code", ts_us=ts_us)],
    )
    h.run()
    yesterday = h.store.read_rollup("2026-10-08")
    assert yesterday is not None
    assert yesterday["unexplained_failed_units"] == {"count": 1, "names": [f"{UNIT}__{inv(1)}"]}
    assert yesterday["produced_at_ns"] == clock.now_ns
    today = h.store.read_rollup("2026-10-09")
    assert today is not None and today["passes_completed"] == 1
    assert yesterday["passes_completed"] == 0  # pass counters belong to the pass's own day


def test_replay_after_an_outage_rewrites_older_days_until_explained(tmp_path: Path) -> None:
    clock = FakeClock(now_ns=_at("2026-10-06", 12, 0))
    ts_us = clock.now_ns // 1000 - 60_000_000
    first = harness(
        tmp_path, clock=clock, entries=[failure_line(UNIT, inv(1), "exit-code", ts_us=ts_us)]
    )
    first.run()
    clock.now_ns = _at("2026-10-08", 12, 0)
    h = harness(tmp_path, clock=clock, store=first.store)
    h.run()
    old = h.store.read_rollup("2026-10-06")
    assert old is not None
    assert old["unexplained_failed_units"]["count"] == 1
    assert old["produced_at_ns"] == clock.now_ns
    h.delivered.add(("unit_health_unit_failed", site(UNIT, 1)))
    clock.advance(600)
    h.run()
    refreshed = h.store.read_rollup("2026-10-06")
    assert refreshed is not None
    assert refreshed["unexplained_failed_units"]["count"] == 0


# --------------------------------------------------------------------------- 4. ownership


def test_run_transient_show_set_names_working_directory() -> None:
    assert "WorkingDirectory" in RUN_TRANSIENT_SHOW_ARGV[4].split(",")


def test_ownership_checks_working_directory_and_never_calls_no_block_foreign() -> None:
    unit = "run-p1-i1.service"
    assert ownership(unit, {}, ()) is Ownership.UNRESOLVED
    assert ownership(unit, {"Id": unit, "Description": " "}, ()) is Ownership.UNRESOLVED
    in_repo = {"WorkingDirectory": REPO, "ExecStart": "{ path=/usr/bin/env }"}
    assert ownership(unit, in_repo, ()) is Ownership.OWNED
    assert ownership(unit, {"WorkingDirectory": REPO + "/scripts"}, ()) is Ownership.OWNED
    other = {"WorkingDirectory": "/home/jon/breezy-other", "ExecStart": "{ path=/bin/sleep }"}
    assert ownership(unit, other, ()) is Ownership.FOREIGN
    assert needs_worktrees(unit, other) is True
    assert needs_worktrees(unit, in_repo) is False
    assert needs_worktrees(unit, {}) is False
    assert ownership(unit, {"WorkingDirectory": "/opt/wt/a"}, ("/opt/wt/a",)) is Ownership.OWNED


def test_classify_unresolved_transient_is_a_warning() -> None:
    entry = parse_failure_line(failure_line("run-p1-i1.service", inv(1), "exit-code"))
    got = classify(entry, None, unresolved=True)
    assert (got.unit_class, got.severity) == (UnitClass.UNRESOLVED_TRANSIENT, "WARNING")


def test_gone_run_transient_is_classified_unresolved_not_foreign(tmp_path: Path) -> None:
    unit = "run-p5-i5.service"
    h = harness(tmp_path, entries=[failure_line(unit, inv(5), "exit-code")])
    result = h.run()
    body = h.store.read_class(unit, inv(5))
    assert body is not None
    assert (body["unit_class"], body["severity"]) == ("UNRESOLVED_TRANSIENT", "WARNING")
    assert result.foreign_failed == ()
    assert h.alerts.payloads[0].severity == "WARNING"
    day = h.store.read_rollup(DAY)
    assert day is not None and day["unexplained_failed_units"]["count"] == 1
    h.delivered.add(("unit_health_unit_failed", site(unit, 5)))
    h.clock.advance(600)
    h.run()
    again = h.store.read_rollup(DAY)
    assert again is not None and again["unexplained_failed_units"]["count"] == 0


def test_run_transient_with_a_non_repo_block_is_foreign(tmp_path: Path) -> None:
    unit = "run-p6-i6.service"
    block = show_block(
        unit, ExecStart="{ path=/usr/bin/sleep }", WorkingDirectory="/tmp", Transient="yes"
    )
    snap = make_snapshot(run_transient=[block], failed=[unit])
    h = harness(tmp_path, snapshot=snap, entries=[failure_line(unit, inv(6), "exit-code")])
    result = h.run()
    assert result.foreign_failed == (unit,)
    assert h.store.class_records_on(DAY) == []


def test_custom_named_transient_is_foreign_a_documented_limitation(tmp_path: Path) -> None:
    unit = "claude-aut6-scratch.service"
    snap = make_snapshot(failed=[unit])
    h = harness(tmp_path, snapshot=snap, entries=[failure_line(unit, inv(8), "exit-code")])
    result = h.run()
    assert result.foreign_failed == (unit,)
    assert h.store.class_records_on(DAY) == []
    assert "custom" in unit_health.__doc__.lower()


def test_unavailable_worktrees_is_ownership_unknown_never_foreign(tmp_path: Path) -> None:
    unit = "run-p7-i7.service"
    block = show_block(unit, ExecStart="{ path=/opt/elsewhere/run.sh }", Transient="yes")
    snap = make_snapshot(run_transient=[block])

    def broken(timeout_s: float) -> Sequence[str]:
        raise WorktreesUnavailable

    h = harness(
        tmp_path,
        snapshot=snap,
        entries=[failure_line(unit, inv(7), "exit-code")],
        worktrees=broken,
    )
    result = h.run()
    assert result.pass_result == "UNKNOWN"
    assert "ownership_unknown" in result.unknown_reasons
    assert result.foreign_failed == ()
    assert h.store.class_records_on(DAY) == []
    assert h.store.read_cursor() is None


def test_repo_owned_run_transient_needs_no_worktree_call(tmp_path: Path) -> None:
    unit = "run-p7-i7.service"
    block = show_block(unit, ExecStart=f"{{ path={REPO}/x }}", Transient="yes")
    calls: list[float] = []
    h = harness(
        tmp_path,
        snapshot=make_snapshot(run_transient=[block]),
        entries=[failure_line(unit, inv(7), "exit-code")],
        worktrees=_recording(calls),
    )
    h.run()
    assert calls == []


def test_worktree_call_is_bounded_by_the_pass_budget(tmp_path: Path) -> None:
    unit = "run-p7-i7.service"
    block = show_block(unit, ExecStart="{ path=/opt/elsewhere/run.sh }", Transient="yes")
    clock = FakeClock()
    seen: list[float] = []
    journal = FakeJournal(
        Trace(), entries=[failure_line(unit, inv(7), "exit-code")], clock=clock, advance_s=80
    )
    h = harness(
        tmp_path,
        clock=clock,
        journal=journal,
        snapshot=live(clock, run_transient=[block]),
        worktrees=_recording(seen),
    )
    h.run()
    assert seen == [pytest.approx(10.0)]
    clock2 = FakeClock()
    journal2 = FakeJournal(
        Trace(), entries=[failure_line(unit, inv(7), "exit-code")], clock=clock2, advance_s=89.5
    )
    seen2: list[float] = []
    h2 = harness(
        tmp_path / "b",
        clock=clock2,
        journal=journal2,
        snapshot=live(clock2, run_transient=[block]),
        worktrees=_recording(seen2),
    )
    result = h2.run()
    assert seen2 == []
    assert "pass_budget" in result.unknown_reasons


# --------------------------------------------------------------------------- 5. per-line parsing


def test_entry_without_invocation_id_gets_a_synthetic_key_and_does_not_poison_the_batch(
    tmp_path: Path,
) -> None:
    raw = json.loads(failure_line("breezy-a.service", inv(1), "exit-code", seq=1))
    del raw["USER_INVOCATION_ID"]
    cursor = raw["__CURSOR"]
    key = "noinv-" + hashlib.sha256(cursor.encode()).hexdigest()[:16]
    h = harness(
        tmp_path,
        entries=[json.dumps(raw), failure_line("breezy-b.service", inv(2), "exit-code", seq=2)],
    )
    result = h.run()
    assert result.pass_result == "FINDINGS"
    assert h.store.read_class("breezy-a.service", key) is not None
    assert h.store.read_class("breezy-b.service", inv(2)) is not None
    assert h.alerts.events == ["unit_health_unit_failed"] * 2
    assert h.store.read_cursor() is not None


def test_truly_unparseable_line_is_a_finding_and_the_cursor_advances() -> None:
    good = failure_line(UNIT, inv(1), "exit-code")
    text = "this is not json\n" + good + "\n[1,2]\n-- cursor: s=end\n"
    batch = SubprocessJournal(run=lambda a, t: RunResult(0, text, False, False)).failures(
        after_cursor=None, since_s=1, timeout_s=5
    )
    assert [e.unit for e in batch.entries] == [UNIT]
    assert len(batch.unparseable) == 2
    assert batch.end_cursor == "s=end"
    assert batch.unparseable[0] == hashlib.sha256(b"this is not json").hexdigest()[:16]


def test_unparseable_entry_pages_once_and_does_not_block(tmp_path: Path) -> None:
    from breezy.runtime.unit_health_journal import JournalBatch

    class Journal(FakeJournal):
        def failures(self, **kw: Any) -> JournalBatch:
            self.trace.add("journal:failures")
            self.calls.append(kw)
            return JournalBatch((), "s=end", ("abc123",))

    h = harness(tmp_path, journal=Journal(Trace()))
    assert h.run().pass_result == "FINDINGS"
    h.clock.advance(600)
    assert h.run().pass_result == "OK"
    assert h.alerts.events == ["journal_entry_unparseable"]
    assert h.alerts.payloads[0].severity == "CRITICAL"
    cursor = h.store.read_cursor()
    assert cursor is not None and cursor.cursor == "s=end"


# --------------------------------------------------------------------------- 6. journal blind


def test_one_persistent_blind_unit_does_not_stall_a_second_units_failure(tmp_path: Path) -> None:
    blind, other = "breezy-blind.service", "breezy-other.service"
    clock = FakeClock()
    first = live(
        clock,
        units=[
            show_block(blind, Result="exit-code", InvocationID=inv(7)),
            show_block(other, Result="exit-code", InvocationID=inv(2)),
        ],
        failed=[blind, other],
    )
    h = harness(
        tmp_path,
        clock=clock,
        snapshot=first,
        entries=[failure_line(other, inv(2), "exit-code", seq=2)],
    )
    one = h.run()
    assert one.pass_result == "UNKNOWN"
    assert one.journal_blind == (blind,)
    assert h.store.read_cursor() is not None  # the blind entry no longer blocks the cursor
    assert h.store.read_class(other, inv(2)) is not None
    third = "breezy-third.service"
    object.__setattr__(
        h.env,
        "journal",
        FakeJournal(h.trace, entries=[failure_line(third, inv(3), "exit-code", seq=3)]),
    )
    clock.advance(600)
    two = h.run()
    assert [f.unit for f in two.new_failures] == [third]
    assert h.alerts.events.count("unit_health_journal_blind") == 1
    day = h.store.read_rollup(DAY)
    assert day is not None
    assert f"{blind}__blind-{inv(7)}" in day["unexplained_failed_units"]["names"]


def test_blind_enqueue_refused_still_blocks_the_cursor(tmp_path: Path) -> None:
    unit = "breezy-blind.service"
    snap = make_snapshot(
        units=[show_block(unit, Result="exit-code", InvocationID=inv(7))], failed=[unit]
    )
    h = harness(tmp_path, snapshot=snap, alert_ok=False)
    result = h.run()
    assert "alert_enqueue_failed" in result.unknown_reasons
    assert h.store.read_cursor() is None


# --------------------------------------------------------------------------- 7. robustness


def _class_path(store: HealthStore, unit: str, n: int) -> Path:
    return store.root / DAY / f"{unit}__{inv(n)}__class.json"


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        "[]",
        json.dumps({"schema": "other/v9"}),
        json.dumps({"schema": "unit_health_class/v1", "kind": "x"}),
    ],
)
def test_corrupt_class_record_is_class_record_unreadable_not_an_enqueue_failure(
    tmp_path: Path, content: str
) -> None:
    store = HealthStore(tmp_path / "unit_health")
    path = _class_path(store, UNIT, 1)
    path.parent.mkdir(parents=True)
    path.write_text(content)
    h = harness(tmp_path, store=store, entries=[failure_line(UNIT, inv(1), "exit-code")])
    result = h.run()
    assert result.pass_result == "UNKNOWN"
    assert "class_record_unreadable" in result.unknown_reasons
    assert "alert_enqueue_failed" not in result.unknown_reasons
    assert h.alerts.events == ["class_record_unreadable"]
    assert f"{UNIT}__{inv(1)}__class.json" in h.alerts.payloads[0].detail
    beat = store.read_heartbeat()
    assert beat is not None and beat["passes_unknown_streak"] == 1
    day = store.read_rollup(DAY)
    assert day is not None and day["unexplained_failed_units"]["count"] == 1


def test_class_record_missing_optional_fields_falls_back_to_critical(tmp_path: Path) -> None:
    store = HealthStore(tmp_path / "unit_health")
    store.write_class(
        DAY,
        UNIT,
        inv(1),
        {
            "schema": "unit_health_class/v1",
            "kind": "unit_failure",
            "unit": UNIT,
            "invocation_id": inv(1),
        },
    )
    h = harness(tmp_path, store=store, entries=[failure_line(UNIT, inv(1), "exit-code")])
    h.run()
    assert h.alerts.payloads[0].severity == "CRITICAL"
    assert "UNHEALABLE" in h.alerts.payloads[0].detail


def test_enospc_from_a_store_write_is_store_error_and_the_heartbeat_still_updates(
    tmp_path: Path,
) -> None:
    class Full(SpyStore):
        def write_class(self, *a: Any, **k: Any) -> bool:
            raise OSError(errno.ENOSPC, "no space")

    store = Full(tmp_path / "unit_health", Trace())
    h = harness(tmp_path, store=store, entries=[failure_line(UNIT, inv(1), "exit-code")])
    result = h.run()
    assert result.pass_result == "UNKNOWN"
    assert "store_error" in result.unknown_reasons
    beat = store.read_heartbeat()
    assert beat is not None
    assert (beat["pass_result"], beat["passes_unknown_streak"]) == ("UNKNOWN", 1)


def test_keyerror_from_a_store_is_store_error(tmp_path: Path) -> None:
    class Odd(SpyStore):
        def read_cursor(self) -> Any:
            raise KeyError("cursor")

    h = harness(tmp_path, store=Odd(tmp_path / "unit_health", Trace()))
    assert "store_error" in h.run().unknown_reasons


def test_a_failing_heartbeat_write_is_reported_not_raised(tmp_path: Path) -> None:
    class NoBeat(SpyStore):
        def write_heartbeat(self, body: Any) -> None:
            raise OSError(errno.ENOSPC, "no space")

    h = harness(tmp_path, store=NoBeat(tmp_path / "unit_health", Trace()))
    result = h.run()
    assert result.pass_result == "UNKNOWN"
    assert "heartbeat_write_failed" in result.unknown_reasons


# --------------------------------------------------------------------------- 8. at-least-once


def test_crash_between_enqueue_and_action_record_replays_with_one_action(tmp_path: Path) -> None:
    class Crashy(SpyStore):
        armed = True

        def write_action(self, *a: Any, **k: Any) -> bool:
            if self.armed:
                self.armed = False
                raise RuntimeError("crash after the enqueue")
            return super().write_action(*a, **k)

    store = Crashy(tmp_path / "unit_health", Trace())
    h = harness(tmp_path, store=store, entries=[failure_line(UNIT, inv(1), "exit-code")])
    with pytest.raises(RuntimeError, match="after the enqueue"):
        h.run()
    assert len(h.alerts.payloads) == 1
    h.run()
    assert len(h.alerts.payloads) == 2  # at-least-once: a duplicate page is allowed
    actions = list((store.root / DAY).glob("*__action.json"))
    assert len(actions) == 1
    h.run()
    assert len(h.alerts.payloads) == 2  # and no more once the action record exists


def test_at_least_once_is_documented() -> None:
    assert "at-least-once" in unit_health.__doc__


# --------------------------------------------------------------------------- 9. small guards


def test_unset_memory_current_is_not_added_back(tmp_path: Path) -> None:
    gib = 1024**3
    snap = make_snapshot(
        units=[
            show_block("breezy-quote-tape-ingest.service", MemoryCurrent=str(gib)),
            show_block("breezy-quote-tape.service", MemoryCurrent=str(2**64 - 1)),
            show_block("breezy-trade-supervisor.service", MemoryCurrent=str(2**63)),
        ]
    )
    h = harness(tmp_path, snapshot=snap)
    h.run()
    line = (h.store.root / f"memavail_{DAY}.jsonl").read_text().splitlines()[0]
    assert json.loads(line)["mem_available_free_kib"] == 8_000_000 + gib // 1024


def test_read_cursor_rejects_a_boolean_ts_ns(tmp_path: Path) -> None:
    store = HealthStore(tmp_path)
    (tmp_path / "cursor.json").write_text(
        json.dumps({"schema": "health_cursor/v1", "cursor": "s=a", "since_us": None, "ts_ns": True})
    )
    assert store.read_cursor() is None
    (tmp_path / "cursor.json").write_text(
        json.dumps({"schema": "health_cursor/v1", "cursor": None, "since_us": True, "ts_ns": 5})
    )
    assert store.read_cursor() is None


def test_seen_history_is_bounded_by_the_named_constant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(unit_health, "RECENT_INVOCATIONS_KEPT", 2)
    entries = [failure_line(UNIT, inv(n), "exit-code", seq=n) for n in (1, 2, 3)]
    h = harness(tmp_path, entries=entries)
    h.run()
    seen = h.store.read_seen(UNIT)
    assert seen is not None and seen["invocations"] == [inv(2), inv(3)]


def test_blind_first_then_the_journal_shows_the_failure_gets_the_real_classification(
    tmp_path: Path,
) -> None:
    unit = "breezy-late.service"
    clock = FakeClock()
    snap = live(
        clock, units=[show_block(unit, Result="exit-code", InvocationID=inv(7))], failed=[unit]
    )
    h = harness(tmp_path, clock=clock, snapshot=snap)
    assert h.run().journal_blind == (unit,)
    assert h.alerts.events == ["unit_health_journal_blind"]
    object.__setattr__(
        h.env,
        "journal",
        FakeJournal(
            Trace(), by_invocation={inv(7): [failure_line(unit, inv(7), "exit-code", seq=9)]}
        ),
    )
    clock.advance(600)
    result = h.run()
    assert result.journal_blind == ()
    assert h.alerts.events == ["unit_health_journal_blind", "unit_health_unit_failed"]
    real = h.store.read_class(unit, inv(7))
    assert real is not None and real["kind"] == "unit_failure"
    assert len(h.store.finding_records_on(DAY, "unit_health_journal_blind")) == 1


def test_unreadable_past_day_rollup_is_left_untouched_and_named(tmp_path: Path) -> None:
    clock = FakeClock(now_ns=_at("2026-10-09", 0, 2))
    ts_us = _at("2026-10-08", 23, 58) // 1000
    snap = live(clock, units=[show_block(UNIT, Result="exit-code", InvocationID=inv(1))])
    store = HealthStore(tmp_path / "unit_health")
    store.root.mkdir(parents=True)
    bad = store.root / "day_2026-10-08.json"
    bad.write_text("{corrupt")
    h = harness(
        tmp_path,
        clock=clock,
        snapshot=snap,
        store=store,
        entries=[failure_line(UNIT, inv(1), "exit-code", ts_us=ts_us)],
    )
    result = h.run()
    assert "rollup_unreadable" in result.unknown_reasons
    assert bad.read_text() == "{corrupt"
    today = store.read_rollup("2026-10-09")
    assert today is not None and today["passes_completed"] + today["passes_unknown"] == 1


def test_one_failing_day_write_does_not_skip_the_other_days(tmp_path: Path) -> None:
    class Flaky(SpyStore):
        def write_rollup(self, day: str, body: Any) -> None:
            if day == "2026-10-08":
                raise OSError(errno.ENOSPC, "no space")
            super().write_rollup(day, body)

    clock = FakeClock(now_ns=_at("2026-10-09", 0, 2))
    ts_us = _at("2026-10-08", 23, 58) // 1000
    snap = live(clock, units=[show_block(UNIT, Result="exit-code", InvocationID=inv(1))])
    store = Flaky(tmp_path / "unit_health", Trace())
    h = harness(
        tmp_path,
        clock=clock,
        snapshot=snap,
        store=store,
        entries=[failure_line(UNIT, inv(1), "exit-code", ts_us=ts_us)],
    )
    result = h.run()
    assert "rollup_write_failed" in result.unknown_reasons
    assert store.read_rollup("2026-10-09") is not None
