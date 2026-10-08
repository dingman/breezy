"""AUT-6 WP3 S3: the unit health core (plan r15 section 3.9; E-7e(f); F2, F4, F6, F10).

Every test drives the pass through its seams: a bus snapshot (the only systemd read), a journal
source, an alert enqueue, a delivered-record lookup, a clock. Nothing here runs systemctl or
journalctl, reads the permit or the orders switch, or touches the real data root.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from breezy.persistence.autonomy.detector_catalog import CATALOG
from breezy.registry.health_model import AlertPayload
from breezy.runtime import unit_health
from breezy.runtime.alert_outbox import AlertOutbox, DeliveryRecordWriter
from breezy.runtime.autonomy_sandbox.bus_handoff import BusSnapshot, BusSnapshotError
from breezy.runtime.unit_health import (
    PassEnv,
    PassResult,
    enqueue_health_alert,
    observe_units,
    run_health_pass,
    unexplained_for_day,
    unit_config_drift,
)
from breezy.runtime.unit_health_journal import (
    PER_CALL_CAP_S,
    JournalBatch,
    JournalError,
    Resources,
    RunResult,
    SubprocessJournal,
)
from breezy.runtime.unit_health_model import (
    HEALTH_PASS_BUDGET_S,
    SNAPSHOT_MAX_AGE_S,
    FailureEntry,
    Ownership,
    UnitClass,
    UnitFacts,
    classify,
    is_explained,
    ownership,
    parse_failure_line,
)
from breezy.runtime.unit_health_store import (
    HEARTBEAT_STALE_S,
    HealthStore,
    alerts_delivered,
    heartbeat_is_stale,
    heartbeat_unknown_streak,
)
from tests.support.unit_health_fixtures import (
    DAY,
    DAY_START_S,
    NOW_NS,
    NS,
    REPO,
    AlertRecorder,
    FakeClock,
    Trace,
    failure_line,
    heartbeat_fixtures,
    inv,
    make_snapshot,
    show_block,
)

UNIT = "breezy-portfolio-roi.service"
DISCOVERY = "breezy-discovery-pull.service"
SRC = Path(unit_health.__file__).resolve().parent


# --------------------------------------------------------------------------- fakes


class FakeJournal:
    def __init__(
        self,
        trace: Trace,
        *,
        entries: Sequence[str] = (),
        end_cursor: str | None = "s=aa;i=ff;b=bb;m=1;t=2;x=3",
        by_invocation: dict[str, Sequence[str]] | None = None,
        resources: Resources | None = None,
        fail_first_with_cursor: bool = False,
        clock: FakeClock | None = None,
        advance_s: float = 0.0,
    ) -> None:
        self.trace = trace
        self.entries = tuple(parse_failure_line(line) for line in entries)
        self.end_cursor = end_cursor
        self.by_invocation = {
            k: tuple(parse_failure_line(x) for x in v) for k, v in (by_invocation or {}).items()
        }
        self.resources = resources
        self.fail_first_with_cursor = fail_first_with_cursor
        self.clock = clock
        self.advance_s = advance_s
        self.calls: list[dict[str, Any]] = []

    def failures(
        self, *, after_cursor: str | None, since_s: int | None, timeout_s: float
    ) -> JournalBatch:
        self.trace.add("journal:failures")
        self.calls.append(
            {"after_cursor": after_cursor, "since_s": since_s, "timeout_s": timeout_s}
        )
        if self.clock is not None:
            self.clock.advance(self.advance_s)
        if self.fail_first_with_cursor and after_cursor is not None:
            raise JournalError("rc=1")
        return JournalBatch(self.entries, self.end_cursor if self.entries else None)

    def failures_for_invocation(
        self, invocation_id: str, *, timeout_s: float
    ) -> tuple[FailureEntry, ...]:
        self.trace.add("journal:invocation")
        return self.by_invocation.get(invocation_id, ())

    def resources_for_invocation(self, invocation_id: str, *, timeout_s: float) -> Resources | None:
        self.trace.add("journal:resources")
        return self.resources


class SpyStore(HealthStore):
    def __init__(self, root: Path, trace: Trace, *, crash_cursor_once: bool = False) -> None:
        super().__init__(root)
        self.trace = trace
        self.crash_cursor_once = crash_cursor_once

    def write_class(self, *a: Any, **k: Any) -> bool:
        self.trace.add("class")
        return super().write_class(*a, **k)

    def write_action(self, *a: Any, **k: Any) -> bool:
        self.trace.add("action")
        return super().write_action(*a, **k)

    def write_seen(self, *a: Any, **k: Any) -> None:
        self.trace.add("seen")
        super().write_seen(*a, **k)

    def write_cursor(self, *a: Any, **k: Any) -> None:
        self.trace.add("cursor")
        if self.crash_cursor_once:
            self.crash_cursor_once = False
            raise RuntimeError("crash before the cursor commit")
        super().write_cursor(*a, **k)


@dataclass
class Harness:
    env: PassEnv
    store: HealthStore
    trace: Trace
    alerts: AlertRecorder
    journal: Any
    clock: FakeClock
    delivered: set[tuple[str, str]]

    def run(self) -> PassResult:
        return run_health_pass(self.env)


def harness(
    tmp_path: Path,
    *,
    snapshot: BusSnapshot | Callable[[], BusSnapshot] | None = None,
    journal: Any = None,
    entries: Sequence[str] = (),
    clock: FakeClock | None = None,
    store: HealthStore | None = None,
    alert_ok: bool = True,
    **extra: Any,
) -> Harness:
    trace = Trace()
    clock = clock or FakeClock()
    store = store or HealthStore(tmp_path / "unit_health")
    alerts = AlertRecorder(trace, ok=alert_ok)
    delivered: set[tuple[str, str]] = set()
    snap = snapshot if snapshot is not None else live(clock)

    def read_snapshot() -> BusSnapshot:
        trace.add("snapshot")
        if isinstance(snap, BusSnapshot):
            return snap
        return snap()

    jr = journal if journal is not None else FakeJournal(trace, entries=entries, clock=clock)
    env = PassEnv(
        store=store,
        read_snapshot=read_snapshot,
        journal=jr,
        alert=alerts,
        delivered=lambda event, site: (event, site) in delivered,
        now_ns=clock.wall,
        monotonic=clock.monotonic,
        worktrees=lambda: (),
        meminfo=lambda: (8_000_000, 16_000_000),
        invocation_id=inv(0xFEED),
        **extra,
    )
    return Harness(env, store, trace, alerts, jr, clock, delivered)


def live(clock: FakeClock, **kw: Any) -> Callable[[], BusSnapshot]:
    """A snapshot taken at the clock's present, so a multi-pass test never reads a stale one."""
    return lambda: make_snapshot(now_ns=clock.now_ns, **kw)


def site(unit: str, n: int) -> str:
    return f"unit_health:{unit}:{inv(n)}"


# --------------------------------------------------------------------------- classification


def _entry(result: str, unit: str = DISCOVERY, n: int = 1) -> FailureEntry:
    return parse_failure_line(failure_line(unit, inv(n), result))


_HIGH = 128 * 1024 * 1024


def test_classifies_low_cpu_wall_with_swap_peak_as_memory_ceiling_suspect() -> None:
    facts = UnitFacts(
        wall_ns=1800 * NS,
        cpu_usage_ns=int(13.86 * NS),
        memory_peak=170_000_000,
        memory_swap_peak=4_300_000_000,
        memory_high=_HIGH,
    )
    got = classify(_entry("timeout"), facts)
    assert got.unit_class is UnitClass.MEMORY_CEILING_SUSPECT
    assert got.severity == "CRITICAL"
    assert got.detector == "aut6.unit_health_unhealable"


def test_low_cpu_wall_without_memory_signal_is_timeout_not_memory() -> None:
    facts = UnitFacts(
        wall_ns=1800 * NS,
        cpu_usage_ns=int(13.86 * NS),
        memory_peak=10_000_000,
        memory_swap_peak=0,
        memory_high=_HIGH,
    )
    assert classify(_entry("timeout"), facts).unit_class is UnitClass.TIMEOUT


@pytest.mark.parametrize(
    ("peak", "expected"),
    [
        (int(0.95 * _HIGH), UnitClass.MEMORY_CEILING_SUSPECT),
        (-(-9 * _HIGH // 10), UnitClass.MEMORY_CEILING_SUSPECT),  # exactly 90 percent, rounded up
        (-(-9 * _HIGH // 10) - 1, UnitClass.TIMEOUT),
    ],
)
def test_memory_peak_near_memory_high_counts_as_memory_signal(
    peak: int, expected: UnitClass
) -> None:
    facts = UnitFacts(
        wall_ns=900 * NS, cpu_usage_ns=NS, memory_peak=peak, memory_swap_peak=0, memory_high=_HIGH
    )
    assert classify(_entry("timeout"), facts).unit_class is expected


def test_high_cpu_timeout_with_memory_signal_stays_timeout() -> None:
    facts = UnitFacts(
        wall_ns=900 * NS,
        cpu_usage_ns=800 * NS,
        memory_peak=_HIGH,
        memory_swap_peak=1,
        memory_high=_HIGH,
    )
    assert classify(_entry("timeout"), facts).unit_class is UnitClass.TIMEOUT


def test_unit_result_map_exit_code_fixture() -> None:
    got = classify(_entry("exit-code", "breezy-portfolio-roi.service"), None)
    assert (got.unit_class, got.detector, got.action) == (
        UnitClass.EXIT_CODE,
        "aut6.unit_health_unhealable",
        "ALERT",
    )


@pytest.mark.parametrize("result", ["signal", "core-dump"])
def test_unit_result_map_signal_fixture(result: str) -> None:
    got = classify(_entry(result, "breezy-exit-window-study.service"), None)
    assert got.unit_class is UnitClass.SIGNAL


def test_unit_result_map_oom_kill_fixture() -> None:
    got = classify(_entry("oom-kill", "breezy-parity-fq.service"), None)
    assert got.unit_class is UnitClass.OOM
    assert got.severity == "CRITICAL"


@pytest.mark.parametrize("result", ["start-limit-hit", "resources"])
def test_unhealable_results_map_to_unhealable(result: str) -> None:
    assert classify(_entry(result), None).unit_class is UnitClass.UNHEALABLE


def test_unknown_unit_result_is_unhealable_and_warns(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING"):
        got = classify(_entry("frobnicated"), None)
    assert got.unit_class is UnitClass.UNHEALABLE
    assert "frobnicated" in got.warn
    assert any("frobnicated" in rec.getMessage() for rec in caplog.records)


def test_watchdog_on_a_non_member_is_handled_as_signal() -> None:
    assert classify(_entry("watchdog"), None).unit_class is UnitClass.SIGNAL


def test_timed_out_oneshot_routes_to_22_never_selfheal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    got = classify(_entry("timeout"), None)
    assert (got.unit_class, got.detector, got.action) == (
        UnitClass.TIMEOUT,
        "aut6.unit_health_unhealable",
        "ALERT",
    )
    # even a watchdog-daemon-set member that times out is #22, never SELF_HEAL (r6 S1)
    monkeypatch.setattr(
        "breezy.runtime.unit_health_model.WATCHDOG_DAEMON_UNITS", frozenset({DISCOVERY})
    )
    again = classify(_entry("timeout"), None)
    assert (again.detector, again.action) == ("aut6.unit_health_unhealable", "ALERT")
    h = harness(
        tmp_path,
        entries=[failure_line(DISCOVERY, inv(1), "timeout")],
        snapshot=make_snapshot(units=[show_block(DISCOVERY, Result="timeout")]),
    )
    h.run()
    body = h.store.read_class(DISCOVERY, inv(1))
    assert body is not None
    assert body["action"] == "ALERT"
    assert "self_heal" not in json.dumps(body).lower()


def test_parse_failure_line_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        parse_failure_line("not json")
    with pytest.raises(ValueError):
        parse_failure_line(json.dumps({"USER_UNIT": "x.service"}))


# --------------------------------------------------------------------------- journal cursor


def test_fail_then_succeed_between_passes_is_counted_via_journal_cursor(tmp_path: Path) -> None:
    # the unit failed and succeeded again between passes: the snapshot shows it healthy
    snap = make_snapshot(units=[show_block(UNIT, InvocationID=inv(2))])
    h = harness(tmp_path, snapshot=snap, entries=[failure_line(UNIT, inv(1), "exit-code", seq=7)])
    first = h.run()
    assert first.pass_result == "FINDINGS"
    assert [f.unit for f in first.new_failures] == [UNIT]
    assert h.alerts.events == ["unit_health_unit_failed"]
    second_journal = FakeJournal(h.trace)
    h2 = harness(tmp_path, snapshot=snap, journal=second_journal, store=h.store)
    again = h2.run()
    assert again.pass_result == "OK"
    assert second_journal.calls[0]["after_cursor"] == "s=aa;i=ff;b=bb;m=1;t=2;x=3"
    assert second_journal.calls[0]["since_s"] is None


def test_cursor_reset_falls_back_to_day_start_and_is_journaled(tmp_path: Path) -> None:
    h = harness(tmp_path)
    result = h.run()
    call = h.journal.calls[0]
    assert (call["after_cursor"], call["since_s"]) == (None, DAY_START_S)
    assert result.cursor_reset is True
    assert len(h.store.cursor_reset_records(DAY)) == 1
    day = h.store.read_rollup(DAY)
    assert day is not None
    assert day["cursor_reset"] is True


def test_corrupt_cursor_file_is_a_reset(tmp_path: Path) -> None:
    h = harness(tmp_path)
    h.store.root.mkdir(parents=True)
    (h.store.root / "cursor.json").write_text("{not json", encoding="utf-8")
    assert h.run().cursor_reset is True


def test_cursor_rejected_by_journal_retries_from_day_start_and_resets(tmp_path: Path) -> None:
    trace = Trace()
    store = HealthStore(tmp_path / "unit_health")
    store.write_cursor("s=old", NOW_NS - 3600 * NS, None)
    journal = FakeJournal(trace, fail_first_with_cursor=True)
    h = harness(tmp_path, journal=journal, store=store)
    result = h.run()
    assert result.cursor_reset is True
    assert [c["after_cursor"] for c in journal.calls] == ["s=old", None]
    assert result.pass_result == "OK"


def test_cursor_and_seen_committed_only_after_class_and_action_records(tmp_path: Path) -> None:
    trace = Trace()
    store = SpyStore(tmp_path / "unit_health", trace)
    entries = [
        failure_line(UNIT, inv(1), "exit-code", seq=1),
        failure_line("breezy-asos-refresh.service", inv(2), "exit-code", seq=2),
    ]
    h = harness(tmp_path, store=store, entries=entries)
    h.trace = trace  # shared trace
    object.__setattr__(h.env, "alert", AlertRecorder(trace))
    run_health_pass(h.env)
    seq = [e for e in trace.events if e in {"class", "action", "seen", "cursor"}]
    last_record = max(i for i, e in enumerate(seq) if e in {"class", "action"})
    first_commit = min(i for i, e in enumerate(seq) if e in {"seen", "cursor"})
    assert last_record < first_commit
    assert seq[-1] == "cursor"
    assert seq.count("class") == seq.count("action") == 2


def test_crash_between_records_and_cursor_commit_replays_without_double_action(
    tmp_path: Path,
) -> None:
    trace = Trace()
    store = SpyStore(tmp_path / "unit_health", trace, crash_cursor_once=True)
    entries = [failure_line(UNIT, inv(1), "exit-code")]
    h = harness(tmp_path, store=store, entries=entries)
    with pytest.raises(RuntimeError, match="crash before"):
        h.run()
    assert h.store.read_cursor() is None
    replay = h.run()
    assert replay.pass_result in {"FINDINGS", "OK"}
    assert h.alerts.events == ["unit_health_unit_failed"]  # one alert across both passes
    assert len(h.store.class_records_on(DAY)) == 1
    assert h.store.read_cursor() is not None


def test_dedupe_on_user_invocation_id_not_time(tmp_path: Path) -> None:
    day_us = 86_400 * 1_000_000
    base_us = NOW_NS // 1000
    same_inv = [
        failure_line(UNIT, inv(1), "exit-code", ts_us=base_us - 5, seq=1),
        failure_line(UNIT, inv(1), "exit-code", ts_us=base_us - day_us, seq=2),
    ]
    h = harness(tmp_path, entries=same_inv)
    h.run()
    assert h.alerts.events == ["unit_health_unit_failed"]
    other = [
        failure_line(UNIT, inv(1), "exit-code", ts_us=base_us - 9, seq=1),
        failure_line(UNIT, inv(2), "exit-code", ts_us=base_us - 9, seq=2),
    ]
    h2 = harness(tmp_path / "second", entries=other)
    h2.run()
    assert h2.alerts.events == ["unit_health_unit_failed"] * 2


# --------------------------------------------------------------------------- UNKNOWN handling


def test_systemctl_error_is_unknown_never_zero_failures(tmp_path: Path) -> None:
    snap = make_snapshot(bad={"failed_list": {"rc": 1}})
    h = harness(tmp_path, snapshot=snap)
    result = h.run()
    assert result.pass_result == "UNKNOWN"
    assert result.failed_units is None
    assert "failed_list:rc=1" in result.unknown_reasons
    assert h.store.read_cursor() is None


def test_bus_error_increments_passes_unknown_and_streak(tmp_path: Path) -> None:
    def broken() -> BusSnapshot:
        raise BusSnapshotError("bus_snapshot_missing")

    h = harness(tmp_path, snapshot=broken)
    h.run()
    h.clock.advance(600)
    h.run()
    day = h.store.read_rollup(DAY)
    assert day is not None
    assert day["passes_unknown"] == 2
    assert day["max_passes_unknown_streak"] == 2
    beat = h.store.read_heartbeat()
    assert beat is not None
    assert beat["passes_unknown_streak"] == 2


def test_health_bus_snapshot_missing_is_unknown(tmp_path: Path) -> None:
    def missing() -> BusSnapshot:
        raise BusSnapshotError("bus_snapshot_missing")

    h = harness(tmp_path, snapshot=missing)
    result = h.run()
    assert result.pass_result == "UNKNOWN"
    assert result.unknown_reasons == ("bus_snapshot_missing",)
    assert h.journal.calls == []
    assert h.alerts.payloads == []


@pytest.mark.parametrize(
    "name",
    [
        "units_show",
        "failed_list",
        "units_inventory",
        "unit_files_inventory",
        "timers_list",
        "run_transient",
    ],
)
@pytest.mark.parametrize(
    ("flag", "tag"),
    [
        ({"rc": 1}, "rc=1"),
        ({"timed_out": True}, "timed_out"),
        ({"oversize": True}, "oversize"),
        ({"skipped": True}, "skipped"),
    ],
)
def test_per_read_failure_is_unknown_for_that_read(
    tmp_path: Path, name: str, flag: dict[str, Any], tag: str
) -> None:
    h = harness(tmp_path, snapshot=make_snapshot(bad={name: flag}))
    result = h.run()
    assert result.pass_result == "UNKNOWN"
    assert f"{name}:{tag}" in result.unknown_reasons
    assert result.failed_units is None
    assert h.store.read_cursor() is None


def test_snapshot_older_than_75s_is_rejected(tmp_path: Path) -> None:
    assert SNAPSHOT_MAX_AGE_S == 75
    old = harness(tmp_path / "old", snapshot=make_snapshot(age_s=76))
    result = old.run()
    assert result.pass_result == "UNKNOWN"
    assert result.unknown_reasons == ("bus_snapshot_stale",)
    assert old.journal.calls == []
    fresh = harness(tmp_path / "fresh", snapshot=make_snapshot(age_s=74))
    assert fresh.run().pass_result == "OK"


def test_snapshot_is_the_first_read_of_the_pass(tmp_path: Path) -> None:
    unit = "run-p1-i1.service"
    block = show_block(unit, Transient="yes", ExecStart=f"{{ path={REPO}/x }}", InvocationID=inv(3))
    h = harness(
        tmp_path,
        snapshot=make_snapshot(run_transient=[block], failed=[unit]),
        entries=[failure_line(unit, inv(3), "exit-code")],
    )
    trace = h.trace

    def probe() -> None:
        trace.add("fold")

    def meminfo() -> tuple[int, int]:
        trace.add("meminfo")
        return (1, 2)

    def worktrees() -> tuple[str, ...]:
        trace.add("worktrees")
        return ()

    object.__setattr__(h.env, "fold_probe", probe)
    object.__setattr__(h.env, "meminfo", meminfo)
    object.__setattr__(h.env, "worktrees", worktrees)
    h.run()
    assert trace.events[0] == "snapshot"
    assert {"fold", "meminfo", "worktrees", "journal:failures"} <= set(trace.events)


def test_list_units_failed_read_before_journal_read(tmp_path: Path) -> None:
    snap = make_snapshot(
        units=[show_block(UNIT, Result="exit-code", InvocationID=inv(1))], failed=[UNIT]
    )
    h = harness(tmp_path, snapshot=snap, entries=[failure_line(UNIT, inv(1), "exit-code")])
    h.run()
    events = h.trace.events
    assert events.index("snapshot") < events.index("journal:failures")


def test_failed_unit_missing_from_journal_is_unknown_and_journal_blind(tmp_path: Path) -> None:
    unit = "breezy-foo.service"
    snap = make_snapshot(
        units=[show_block(unit, Result="exit-code", InvocationID=inv(7))], failed=[unit]
    )
    h = harness(tmp_path, snapshot=snap)
    result = h.run()
    assert result.pass_result == "UNKNOWN"
    assert result.journal_blind == (unit,)
    assert h.alerts.events == ["unit_health_journal_blind"]
    assert h.alerts.payloads[0].severity == "CRITICAL"
    assert h.trace.events.count("journal:invocation") == 1
    assert h.store.read_cursor() is None
    beat = h.store.read_heartbeat()
    assert beat is not None
    assert beat["passes_unknown_streak"] == 1


def test_failed_unit_with_empty_invocation_id_is_journal_blind(tmp_path: Path) -> None:
    unit = "breezy-foo.service"
    snap = make_snapshot(
        units=[show_block(unit, Result="exit-code", InvocationID="")], failed=[unit]
    )
    h = harness(tmp_path, snapshot=snap)
    result = h.run()
    assert result.journal_blind == (unit,)
    assert "journal:invocation" not in h.trace.events


def test_failed_unit_older_than_cursor_found_by_invocation_lookup_is_processed(
    tmp_path: Path,
) -> None:
    unit = "breezy-foo.service"
    store = HealthStore(tmp_path / "unit_health")
    store.write_cursor("s=aaa", NOW_NS - 60 * NS, None)
    snap = make_snapshot(
        units=[show_block(unit, Result="exit-code", InvocationID=inv(7))], failed=[unit]
    )
    trace = Trace()
    journal = FakeJournal(
        trace, by_invocation={inv(7): [failure_line(unit, inv(7), "exit-code", seq=3)]}
    )
    h = harness(tmp_path, snapshot=snap, journal=journal, store=store)
    result = h.run()
    assert result.pass_result == "FINDINGS"
    assert result.journal_blind == ()
    assert h.alerts.events == ["unit_health_unit_failed"]
    assert store.read_class(unit, inv(7)) is not None


def test_failed_unit_with_a_class_record_needs_no_lookup(tmp_path: Path) -> None:
    unit = "breezy-foo.service"
    snap = make_snapshot(
        units=[show_block(unit, Result="exit-code", InvocationID=inv(7))], failed=[unit]
    )
    h = harness(tmp_path, snapshot=snap, entries=[failure_line(unit, inv(7), "exit-code")])
    h.run()
    assert "journal:invocation" not in h.trace.events


# --------------------------------------------------------------------------- fold (F4)


class _Unreadable(Exception):
    pass


@pytest.mark.parametrize("reason", ["unreadable", "empty"])
def test_health_pass_fold_unreadable_writes_26_fail_under_host_and_alerts_directly(
    tmp_path: Path, reason: str
) -> None:
    def probe() -> None:
        raise unit_health.FoldUnreadable(reason)

    verdicts: list[Any] = []
    h = harness(tmp_path, fold_probe=probe, host_verdict=verdicts.append)
    result = h.run()
    assert result.pass_result == "UNKNOWN"
    assert "fold_unreadable" in result.unknown_reasons
    assert len(verdicts) == 1
    assert verdicts[0].detector == "aut6.producer_stale"
    assert verdicts[0].outcome == "FAIL"
    assert verdicts[0].metrics["fold_reason"] == reason
    assert h.alerts.events == ["fold_unreadable"]
    assert h.alerts.payloads[0].severity == "CRITICAL"


def test_fold_unreadable_health_pass_increments_passes_unknown_streak(tmp_path: Path) -> None:
    def probe() -> None:
        raise unit_health.FoldUnreadable("unreadable")

    h = harness(tmp_path, fold_probe=probe, host_verdict=lambda v: None)
    h.run()
    beat1 = h.store.read_heartbeat()
    h.clock.advance(600)
    h.run()
    beat2 = h.store.read_heartbeat()
    assert beat1 is not None and beat2 is not None
    assert (beat1["passes_unknown_streak"], beat2["passes_unknown_streak"]) == (1, 2)
    assert h.alerts.events == ["fold_unreadable"]  # one direct page per day


# --------------------------------------------------------------------------- budget (F6)


def test_health_pass_stops_unknown_at_90s_budget(tmp_path: Path) -> None:
    assert HEALTH_PASS_BUDGET_S == 90
    clock = FakeClock()
    trace = Trace()
    journal = FakeJournal(
        trace,
        entries=[failure_line(UNIT, inv(1), "exit-code", seq=1)],
        clock=clock,
        advance_s=91,
    )
    h = harness(tmp_path, journal=journal, clock=clock)
    result = h.run()
    assert result.pass_result == "UNKNOWN"
    assert "pass_budget" in result.unknown_reasons
    assert h.store.class_records_on(DAY) == []
    assert h.store.read_cursor() is None


def test_health_pass_commits_nothing_past_its_last_completed_entry(tmp_path: Path) -> None:
    clock = FakeClock()
    trace = Trace()
    journal = FakeJournal(
        trace,
        entries=[
            failure_line(UNIT, inv(1), "exit-code", seq=1),
            failure_line("breezy-asos-refresh.service", inv(2), "exit-code", seq=2),
        ],
        clock=clock,
    )
    h = harness(tmp_path, journal=journal, clock=clock)

    def slow_alert(payload: AlertPayload) -> bool:
        h.alerts(payload)
        clock.advance(95)
        return True

    object.__setattr__(h.env, "alert", slow_alert)
    result = h.run()
    assert result.pass_result == "UNKNOWN"
    assert "pass_budget" in result.unknown_reasons
    assert len(h.store.class_records_on(DAY)) == 1
    assert h.store.read_cursor() is None


def test_health_pass_subprocess_timeouts_fit_budget(tmp_path: Path) -> None:
    clock = FakeClock()
    calls: list[tuple[float, float]] = []  # (timeout, elapsed at call)
    start = clock.mono

    def run(argv: Sequence[str], timeout_s: float) -> RunResult:
        calls.append((timeout_s, clock.mono - start))
        clock.advance(40)
        if "USER_INVOCATION_ID" in " ".join(argv):
            return RunResult(0, "", False, False)
        lines = "\n".join(failure_line(DISCOVERY, inv(n), "timeout", seq=n) for n in (1, 2, 3))
        return RunResult(0, lines + "\n-- cursor: s=aa;i=9\n", False, False)

    journal = SubprocessJournal(run=run)
    snap = make_snapshot(units=[show_block(DISCOVERY, Result="timeout")])
    h = harness(tmp_path, journal=journal, clock=clock, snapshot=snap)
    result = h.run()
    assert calls, "the journal was never read"
    for timeout_s, elapsed in calls:
        assert timeout_s <= PER_CALL_CAP_S
        assert timeout_s <= HEALTH_PASS_BUDGET_S - elapsed + 1e-9
    assert result.pass_result == "UNKNOWN"
    assert "pass_budget" in result.unknown_reasons


def test_subprocess_journal_argv_is_a_list_with_message_id_and_no_shell() -> None:
    seen: list[Sequence[str]] = []

    def run(argv: Sequence[str], timeout_s: float) -> RunResult:
        seen.append(argv)
        return RunResult(
            0, failure_line(UNIT, inv(1), "exit-code") + "\n-- cursor: s=zz\n", False, False
        )

    batch = SubprocessJournal(run=run).failures(after_cursor="s=abc", since_s=None, timeout_s=5)
    argv = seen[0]
    assert argv[0].endswith("journalctl")
    assert {"--user", "-o", "json"} <= set(argv)
    assert "--after-cursor=s=abc" in argv
    assert "MESSAGE_ID=d9b373ed55a64feb8242e02dbe79a49c" in argv
    assert batch.end_cursor == "s=zz"
    assert [e.unit for e in batch.entries] == [UNIT]
    since = SubprocessJournal(run=run).failures(after_cursor=None, since_s=DAY_START_S, timeout_s=5)
    assert f"--since=@{DAY_START_S}" in seen[1]
    assert since.entries


@pytest.mark.parametrize(
    "result",
    [
        RunResult(1, "", False, False),
        RunResult(-9, "", True, False),
        RunResult(0, "", False, True),
        RunResult(0, "garbage\n", False, False),
    ],
)
def test_subprocess_journal_error_modes_raise(result: RunResult) -> None:
    journal = SubprocessJournal(run=lambda argv, timeout_s: result)
    with pytest.raises(JournalError):
        journal.failures(after_cursor=None, since_s=1, timeout_s=5)


# --------------------------------------------------------------------------- memory samples (F10)


def test_health_pass_appends_memavail_sample(tmp_path: Path) -> None:
    gib = 1024**3
    snap = make_snapshot(
        units=[show_block("breezy-quote-tape-ingest.service", MemoryCurrent=str(2 * gib))]
    )
    h = harness(tmp_path, snapshot=snap)
    assert h.run().pass_result == "OK"
    lines = (h.store.root / f"memavail_{DAY}.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    sample = json.loads(lines[0])
    assert sample == {
        "ts_ns": NOW_NS,
        "mem_available_kib": 8_000_000,
        "mem_available_free_kib": 8_000_000 + 2 * gib // 1024,
    }


def test_unknown_pass_appends_no_memavail_sample(tmp_path: Path) -> None:
    h = harness(tmp_path, snapshot=make_snapshot(bad={"failed_list": {"rc": 1}}))
    h.run()
    assert not list(h.store.root.glob("memavail_*.jsonl"))


def _seed(
    store: HealthStore, n: int, *, start_ns: int, step_s: int, free: Callable[[int], int]
) -> None:
    for i in range(n):
        store.append_memavail(start_ns + i * step_s * NS, 1000 + i, free(i))


def test_memory_sum_uses_24h_minimum_memavailable(tmp_path: Path) -> None:
    store = HealthStore(tmp_path / "unit_health")
    store.append_memavail(NOW_NS - 25 * 3600 * NS, 10, 5)  # outside the window: ignored
    _seed(store, 100, start_ns=NOW_NS - 23 * 3600 * NS, step_s=600, free=lambda i: 9000 - i)
    window = store.memavail_window(NOW_NS)
    assert window.unknown_reason is None
    assert window.minimum_free_kib == 9000 - 99
    assert window.minimum_available_kib == 1000
    assert window.count == 100


def test_memavail_samples_insufficient_is_inconclusive(tmp_path: Path) -> None:
    store = HealthStore(tmp_path / "unit_health")
    _seed(store, 71, start_ns=NOW_NS - 20 * 3600 * NS, step_s=600, free=lambda i: 5000)
    short = store.memavail_window(NOW_NS)
    assert short.unknown_reason == "memavail_samples_insufficient"
    assert short.minimum_free_kib is None
    store.append_memavail(NOW_NS - 60 * NS, 1, 4000)
    enough = store.memavail_window(NOW_NS)
    assert (enough.unknown_reason, enough.minimum_free_kib) == (None, 4000)


# --------------------------------------------------------------------------- scope / ownership


def test_run_sweep_owns_transient_by_repo_path_or_worktree_path() -> None:
    repo = show_block(
        "run-p1-i1.service",
        Description="[systemd-run] x",
        ExecStart=f"{{ path={REPO}/.venv/bin/python ; argv[]=x }}",
        Transient="yes",
    )
    assert ownership("run-p1-i1.service", _block(repo), ()) is Ownership.OWNED
    wt = show_block(
        "run-p2-i2.service", ExecStart="{ path=/opt/wt/a/run.sh ; argv[]=run.sh }", Transient="yes"
    )
    assert ownership("run-p2-i2.service", _block(wt), ("/opt/wt/a",)) is Ownership.OWNED
    assert ownership("run-p2-i2.service", _block(wt), ()) is Ownership.FOREIGN
    desc = show_block("run-p3-i3.service", Description=f"job in {REPO}/scripts", Transient="yes")
    assert ownership("run-p3-i3.service", _block(desc), ()) is Ownership.OWNED
    assert ownership("breezy-x.service", {}, ()) is Ownership.OWNED
    assert ownership("breezy-x@a.service", {}, ()) is Ownership.OWNED


def test_run_sweep_classifies_owned_transient_as_transient_adhoc(tmp_path: Path) -> None:
    unit = "run-p1-i1.service"
    block = show_block(
        unit,
        ExecStart=f"{{ path={REPO}/.venv/bin/python }}",
        Transient="yes",
        Result="exit-code",
        InvocationID=inv(5),
    )
    snap = make_snapshot(run_transient=[block], failed=[unit])
    h = harness(tmp_path, snapshot=snap, entries=[failure_line(unit, inv(5), "exit-code")])
    h.run()
    body = h.store.read_class(unit, inv(5))
    assert body is not None
    assert body["unit_class"] == "TRANSIENT_ADHOC"
    assert body["severity"] == "WARNING"


def _block(text: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


def test_foreign_transient_excluded_from_unexplained(tmp_path: Path) -> None:
    foreign_run = "run-p9-i9.service"
    block = show_block(
        foreign_run, ExecStart="{ path=/usr/bin/sleep }", Transient="yes", InvocationID=inv(9)
    )
    names = ["jetbrains-remote-dev.service", "pressure-memory.service", foreign_run]
    snap = make_snapshot(run_transient=[block], failed=names)
    entries = [failure_line(n, inv(9 + i), "exit-code", seq=i) for i, n in enumerate(names)]
    h = harness(tmp_path, snapshot=snap, entries=entries)
    result = h.run()
    assert result.pass_result == "OK"
    assert sorted(result.foreign_failed) == sorted(names)
    assert h.store.class_records_on(DAY) == []
    assert h.alerts.payloads == []
    day = h.store.read_rollup(DAY)
    assert day is not None
    assert day["unexplained_failed_units"] == {"count": 0, "names": []}
    assert sorted(day["foreign_failed"]) == sorted(names)


def test_snapshot_max_age_tracks_the_health_row() -> None:
    from breezy.runtime.unit_health_obs import HEALTH_ROW

    assert HEALTH_ROW.bus_snapshot_budget_s is not None
    assert SNAPSHOT_MAX_AGE_S == HEALTH_ROW.bus_snapshot_budget_s + 60


def test_production_env_builds_without_touching_the_host(tmp_path: Path) -> None:
    env = unit_health.production_env(environ={"INVOCATION_ID": inv(4)}, data_root=tmp_path)
    assert env.invocation_id == inv(4)
    assert env.store.root == tmp_path / "evidence" / "unit_health"
    assert list(tmp_path.iterdir()) == []


def test_foreign_prefixes_are_literal() -> None:
    assert unit_health.FOREIGN_UNIT_PREFIXES == ("jetbrains-remote-dev", "pressure-")


# --------------------------------------------------------------------------- explained


def test_failed_member_invocation_explained_by_class_and_delivered_alert(tmp_path: Path) -> None:
    snap = make_snapshot(
        units=[show_block(UNIT, Result="exit-code", InvocationID=inv(1))], failed=[UNIT]
    )
    h = harness(tmp_path, snapshot=snap, entries=[failure_line(UNIT, inv(1), "exit-code")])
    h.run()
    unexplained = unexplained_for_day(h.store, DAY, lambda e, s: (e, s) in h.delivered)
    assert unexplained == (f"{UNIT}__{inv(1)}",)
    h.delivered.add(("unit_health_unit_failed", site(UNIT, 1)))
    assert unexplained_for_day(h.store, DAY, lambda e, s: (e, s) in h.delivered) == ()


def test_explained_requires_classification_and_proven_action() -> None:
    klass = {"unit_class": "EXIT_CODE", "kind": "unit_failure"}
    action = {"event": "unit_health_unit_failed", "site": "s"}
    yes = lambda e, s: True
    no = lambda e, s: False
    assert is_explained(klass, action, yes) is True
    assert is_explained(klass, action, no) is False
    assert is_explained(klass, None, yes) is False
    assert is_explained(None, action, yes) is False


def test_classifies_portfolio_roi_repeat_exit1_on_distinct_invocations_as_expected_failure_suspect(
    tmp_path: Path,
) -> None:
    day_s = 86_400
    clock = FakeClock(now_ns=NOW_NS - day_s * NS)
    yesterday_us = clock.now_ns // 1000 - 60_000_000

    def snapshot(n: int, now_ns: int) -> BusSnapshot:
        return make_snapshot(
            now_ns=now_ns,
            units=[show_block(UNIT, Result="exit-code", ExecMainStatus="1", InvocationID=inv(n))],
            failed=[UNIT],
        )

    first = harness(
        tmp_path,
        clock=clock,
        snapshot=snapshot(1, clock.now_ns),
        entries=[failure_line(UNIT, inv(1), "exit-code", ts_us=yesterday_us)],
    )
    first.run()
    prior = first.store.read_class(UNIT, inv(1))
    assert prior is not None and prior["unit_class"] == "EXIT_CODE"
    today = FakeClock(now_ns=NOW_NS)
    second = harness(
        tmp_path,
        clock=today,
        snapshot=snapshot(2, NOW_NS),
        store=first.store,
        entries=[failure_line(UNIT, inv(2), "exit-code")],
    )
    second.run()
    body = second.store.read_class(UNIT, inv(2))
    assert body is not None
    assert body["unit_class"] == "EXPECTED_FAILURE_SUSPECT"
    assert body["exit_status"] == 1


def test_expected_failure_suspect_is_never_explained(tmp_path: Path) -> None:
    klass = {"unit_class": "EXPECTED_FAILURE_SUSPECT", "kind": "unit_failure"}
    action = {"event": "unit_health_unit_failed", "site": "s"}
    assert is_explained(klass, action, lambda e, s: True) is False


def test_same_status_on_the_same_day_is_not_a_suspect(tmp_path: Path) -> None:
    snap = make_snapshot(
        units=[show_block(UNIT, Result="exit-code", ExecMainStatus="1", InvocationID=inv(2))],
        failed=[UNIT],
    )
    h = harness(
        tmp_path,
        snapshot=snap,
        entries=[
            failure_line(UNIT, inv(1), "exit-code", seq=1),
            failure_line(UNIT, inv(2), "exit-code", seq=2),
        ],
    )
    h.run()
    second = h.store.read_class(UNIT, inv(2))
    assert second is not None and second["unit_class"] == "EXIT_CODE"


def test_rollup_counts_unexplained_passes_and_max_unknown_streak(tmp_path: Path) -> None:
    clock = FakeClock()
    bad = live(clock, bad={"failed_list": {"rc": 1}})
    good = live(
        clock, units=[show_block(UNIT, Result="exit-code", InvocationID=inv(1))], failed=[UNIT]
    )
    h = harness(tmp_path, snapshot=bad, clock=clock)
    h.run()
    h.clock.advance(600)
    h.run()  # streak 2
    object.__setattr__(h.env, "read_snapshot", good)
    object.__setattr__(
        h.env, "journal", FakeJournal(h.trace, entries=[failure_line(UNIT, inv(1), "exit-code")])
    )
    h.clock.advance(600)
    h.run()  # completed with a finding
    object.__setattr__(h.env, "read_snapshot", bad)
    h.clock.advance(600)
    h.run()  # streak 1 again
    day = h.store.read_rollup(DAY)
    assert day is not None
    assert day["passes_completed"] == 1
    assert day["passes_unknown"] == 3
    assert day["max_passes_unknown_streak"] == 2
    assert day["unexplained_failed_units"] == {"count": 1, "names": [f"{UNIT}__{inv(1)}"]}
    assert day["schema"] == "unit_health_day/v1"
    assert day["produced_at_ns"] == h.clock.now_ns


# --------------------------------------------------------------------------- observe_units


def test_observe_units_runs_the_production_reader_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Any] = []
    snap = make_snapshot(units=[show_block(UNIT)], failed=[UNIT])

    def reader(row: Any, *, environ: Any, **kwargs: Any) -> BusSnapshot:
        calls.append((row.name, dict(environ)))
        return snap

    monkeypatch.setattr(unit_health, "read_bus_snapshot", reader)
    observed = observe_units(environ={"INVOCATION_ID": inv(0xFEED)}, now_ns=lambda: NOW_NS)
    assert [c[0] for c in calls] == ["breezy-autonomy-health"]
    assert observed.failed_names == (UNIT,)
    assert UNIT in observed.blocks


# --------------------------------------------------------------------------- config drift (#24)


def test_unit_config_drift_detects_uncommitted_dropin_and_escalates_after_deadline() -> None:
    sup = "breezy-trade-supervisor.service"
    drop = "/home/jon/.config/systemd/user/breezy-trade-supervisor.service.d/zz-extra.conf"
    committed_one = "/home/jon/.config/systemd/user/breezy-trade-supervisor.service.d/ok.conf"
    blocks = {sup: {"Id": sup, "DropInPaths": f"{committed_one} {drop}"}}
    committed = {sup: frozenset({"ok.conf"})}
    before = unit_config_drift(blocks, committed, today="2026-10-15")
    assert [(f.unit, f.dropin, f.severity) for f in before] == [(sup, "zz-extra.conf", "WARNING")]
    after = unit_config_drift(blocks, committed, today="2026-10-16")
    assert [f.severity for f in after] == ["CRITICAL"]
    clean = unit_config_drift(blocks, {sup: frozenset({"ok.conf", "zz-extra.conf"})}, today=DAY)
    assert clean == ()
    assert unit_config_drift({sup: {"Id": sup, "DropInPaths": ""}}, committed, today=DAY) == ()


def test_drift_deadline_matches_the_catalogue_row() -> None:
    row = next(r for r in CATALOG if r.id == "aut6.unit_config_drift")
    assert unit_health.DRIFT_CRITICAL_FROM == row.critical_from


def test_drift_pass_alerts_once_per_day(tmp_path: Path) -> None:
    sup = "breezy-trade-supervisor.service"
    drop = "/home/jon/.config/systemd/user/breezy-trade-supervisor.service.d/zz-extra.conf"
    clock = FakeClock()
    snap = live(clock, units=[show_block(sup, DropInPaths=drop)])
    h = harness(tmp_path, snapshot=snap, clock=clock, committed_dropins={sup: frozenset()})
    h.run()
    h.clock.advance(600)
    h.run()
    assert h.alerts.events == ["unit_config_drift"]


# --------------------------------------------------------------------------- heartbeat


def test_health_heartbeat_ts_ns_advances_only_on_completed_pass(tmp_path: Path) -> None:
    h = harness(tmp_path)
    h.run()
    first = h.store.read_heartbeat()
    assert first is not None
    assert first["schema"] == "health_heartbeat/v1"
    assert first["ts_ns"] == NOW_NS
    assert first["pass_result"] == "OK"
    assert first["invocation_id"] == inv(0xFEED)
    h.clock.advance(600)
    h.run()
    second = h.store.read_heartbeat()
    assert second is not None and second["ts_ns"] == NOW_NS + 600 * NS


def test_unknown_pass_rewrites_heartbeat_with_streak_and_old_ts_ns(tmp_path: Path) -> None:
    h = harness(tmp_path)
    h.run()
    object.__setattr__(h.env, "read_snapshot", live(h.clock, bad={"failed_list": {"rc": 1}}))
    h.clock.advance(600)
    h.run()
    beat = h.store.read_heartbeat()
    assert beat is not None
    assert beat["ts_ns"] == NOW_NS  # unchanged
    assert beat["last_attempt_ns"] == NOW_NS + 600 * NS
    assert beat["pass_result"] == "UNKNOWN"
    assert beat["passes_unknown_streak"] == 1
    object.__setattr__(h.env, "read_snapshot", live(h.clock))
    h.clock.advance(600)
    h.run()
    healed = h.store.read_heartbeat()
    assert healed is not None
    assert healed["passes_unknown_streak"] == 0
    assert healed["ts_ns"] == NOW_NS + 1200 * NS


def test_first_ever_unknown_pass_writes_ts_ns_zero(tmp_path: Path) -> None:
    h = harness(tmp_path, snapshot=make_snapshot(bad={"failed_list": {"rc": 1}}))
    h.run()
    beat = h.store.read_heartbeat()
    assert beat is not None and beat["ts_ns"] == 0


def test_deadman_fixture_set_fresh_aged_and_unknown_streak(tmp_path: Path) -> None:
    assert HEARTBEAT_STALE_S == 1800
    fixtures = heartbeat_fixtures(NOW_NS)
    assert heartbeat_is_stale(fixtures["fresh"], NOW_NS) is False
    assert heartbeat_is_stale(fixtures["aged"], NOW_NS) is True
    streak = fixtures["unknown_streak"]
    assert heartbeat_is_stale(streak, NOW_NS) is True  # the age rule fires on ts_ns
    assert streak["last_attempt_ns"] > NOW_NS - 120 * NS
    assert heartbeat_unknown_streak(streak) == 3
    assert heartbeat_unknown_streak(fixtures["fresh"]) == 0
    # a real run of three UNKNOWN passes writes exactly that shape
    clock = FakeClock()
    h = harness(tmp_path, snapshot=live(clock, bad={"failed_list": {"rc": 1}}), clock=clock)
    h.run()
    for _ in range(2):
        h.clock.advance(600)
        h.run()
    real = h.store.read_heartbeat()
    assert real is not None
    assert set(real) == set(streak)
    assert heartbeat_unknown_streak(real) == 3


# ----------------------------------------------------------------- locks, adapters, guards


def test_a_held_health_lock_skips_the_pass_without_touching_state(tmp_path: Path) -> None:
    h = harness(tmp_path)
    with h.store.lock() as held:
        assert held
        result = h.run()
    assert result.pass_result == "LOCKED"
    assert h.store.read_heartbeat() is None
    assert h.store.read_rollup(DAY) is None


def test_alert_enqueue_failure_leaves_no_action_record_and_no_cursor(tmp_path: Path) -> None:
    h = harness(tmp_path, entries=[failure_line(UNIT, inv(1), "exit-code")], alert_ok=False)
    result = h.run()
    assert result.pass_result == "UNKNOWN"
    assert "alert_enqueue_failed" in result.unknown_reasons
    assert h.store.has_action(UNIT, inv(1)) is False
    assert h.store.read_cursor() is None


def test_production_alert_adapter_enqueues_with_the_health_writer_id(tmp_path: Path) -> None:
    root = tmp_path / "alerts"
    enqueue = enqueue_health_alert(root)
    payload = AlertPayload("CRITICAL", "unit_health_unit_failed", site(UNIT, 1), "d")
    assert enqueue(payload) is True
    entries = list((root / "outbox").glob("*.json"))
    assert len(entries) == 1
    body = json.loads(entries[0].read_text(encoding="utf-8"))
    assert body["writer"] == "health"
    assert re.fullmatch(r"[a-z0-9_]{1,64}", body["writer"])
    assert AlertOutbox(root).occupancy() == 1


def test_delivered_lookup_reads_delivered_records_by_event_and_site(tmp_path: Path) -> None:
    root = tmp_path / "alerts"
    look = alerts_delivered(root, now_ns=lambda: NOW_NS)
    assert look("unit_health_unit_failed", site(UNIT, 1)) is False
    writer = DeliveryRecordWriter(root)
    kwargs: dict[str, Any] = {
        "event": "unit_health_unit_failed",
        "ts_ns": NOW_NS,
        "writer": "redeliver",
        "status_class": "2xx",
        "severity": "CRITICAL",
        "attempt_kind": "drain",
        "drill": False,
        "outbox_entry": "x.json",
    }
    writer.write(delivered=False, site=site(UNIT, 1), **kwargs)
    assert look("unit_health_unit_failed", site(UNIT, 1)) is False
    writer.write(delivered=True, site=site(UNIT, 2), **kwargs)
    assert look("unit_health_unit_failed", site(UNIT, 1)) is False
    assert look("unit_health_unit_failed", site(UNIT, 2)) is True
    assert look("other_event", site(UNIT, 2)) is False


def test_unit_health_modules_read_no_permit_or_orders_state() -> None:
    forbidden = (
        "permit",
        "orders_enabled",
        "ORDERS_ENABLED",
        "order_enablement",
        "live_orders_gate",
        "BREEZY_ORDERS",
    )
    files = sorted(SRC.glob("unit_health*.py"))
    assert len(files) >= 4
    for path in files:
        text = path.read_text(encoding="utf-8")
        for word in forbidden:
            assert word not in text, f"{path.name} mentions {word}"
        assert len(text.splitlines()) < 800


def test_unit_health_never_calls_a_state_changing_verb() -> None:
    for path in sorted(SRC.glob("unit_health*.py")):
        text = path.read_text(encoding="utf-8")
        for verb in (
            '"restart"',
            '"start"',
            '"stop"',
            '"reset-failed"',
            '"kill"',
            '"daemon-reload"',
            "systemd-run",
        ):
            assert verb not in text, f"{path.name} names {verb}"


def test_store_files_are_private(tmp_path: Path) -> None:
    h = harness(tmp_path, entries=[failure_line(UNIT, inv(1), "exit-code")])
    h.run()
    record = next((h.store.root / DAY).glob("*__class.json"))
    assert oct(record.stat().st_mode & 0o777) == "0o444"
    assert oct((h.store.root / "heartbeat.json").stat().st_mode & 0o777) == "0o600"
    assert os.path.isdir(h.store.root / "seen")
