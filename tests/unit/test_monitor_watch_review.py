"""AUT-6 WP3 S5 review round: isolation, evidence, resident memory, bounds (silent-failure and
architect reviews). Every case here failed on 8de8084d."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from breezy.runtime import monitor_watch, process_lookup, trade_supervisor_core
from breezy.runtime.monitor_watch import (
    NOT_DEPLOYED_ARTIFACTS,
    NOT_YET_DEPLOYED,
    TIMER_INSTANCE_INTERVAL_S,
    unwired_without_row,
)
from breezy.runtime.monitor_watch_memory import (
    NODE_UNIT,
    RECORDER_UNIT,
    free_addback_kib,
)
from breezy.runtime.monitor_watch_model import deploy_unit_names
from breezy.runtime.monitor_watch_producer import (
    FileProducerSource,
    evaluate_daily,
    evaluate_producer,
    scan_verdict_cadences,
)
from breezy.runtime.unit_health_journal import JournalError
from tests.support.monitor_watch_fixtures import (
    TIMER_A,
    TIMER_R,
    installed,
    kinds,
    run_watch,
    snapshot,
    subjects,
    synth_deploy,
    timer_block,
    wiring,
)
from tests.support.unit_health_fixtures import DAY, NOW_NS, NS, FakeClock, show_block
from tests.unit.test_monitor_watch import (
    ARTIFACTS,
    INSTANCE_ONE,
    INSTANCE_TWO,
    ROWS,
    TIMERS,
    UNITS,
    healthy,
    judge,
    x8,
    x8_files,
)
from tests.unit.test_unit_health import harness

DAILY_TIMER = "breezy-autonomy-producer-daily.timer"
INTRADAY_TIMER = "breezy-autonomy-producer-intraday.timer"
PRODUCER = "aut6.producer_stale"


# --------------------------------------------------------------------------- HIGH 1: isolation


class Boom(RuntimeError):
    pass


def test_one_detector_raising_is_isolated_and_named(tmp_path: Path) -> None:
    deploy = synth_deploy(tmp_path / "deploy")

    def broken(_since: int, _timeout: float) -> Any:
        raise Boom("x")

    files = installed(deploy, skip=[TIMER_R], instances=[INSTANCE_ONE])
    w = wiring(tmp_path, deploy, summary=broken)
    result = run_watch(w, snapshot(blocks=healthy(deploy), unit_files=files))
    delivery = result.by_detector("aut6.alert_delivery")
    assert delivery.unknown_reasons == ("detector_error:aut6.alert_delivery:Boom",)
    assert delivery.outcome == "INCONCLUSIVE"
    assert result.by_detector(TIMERS).outcome == "PASS"  # the others still ran
    assert result.by_detector("aut6.memory_budget").detector == "aut6.memory_budget"


def test_every_detector_is_isolated(tmp_path: Path) -> None:
    deploy = synth_deploy(tmp_path / "deploy")
    files = installed(deploy, skip=[TIMER_R], instances=[INSTANCE_ONE])

    class Exploding:
        def __getattr__(self, name: str) -> Any:
            raise Boom(name)

    w = wiring(tmp_path, deploy, producer=Exploding(), rows={}, node_log_tail=Exploding())
    result = run_watch(w, snapshot(blocks=healthy(deploy), unit_files=files))
    reasons = set(result.unknown_reasons)
    assert "detector_error:aut6.producer_stale:Boom" in reasons
    assert "detector_error:aut6.daily_verdict_absent:Boom" in reasons
    assert len(result.results) == 5


def test_an_unreadable_outbox_is_a_reason_not_an_exception(tmp_path: Path) -> None:
    from tests.unit.test_monitor_watch_delivery import judge as judge_delivery

    root = tmp_path / "alerts"
    (root / "outbox").mkdir(parents=True)
    (root / "outbox").chmod(0)
    try:
        result = judge_delivery(root, NOW_NS)
    finally:
        (root / "outbox").chmod(0o700)
    assert "outbox_unreadable" in result.unknown_reasons


def test_a_failing_verdict_sink_does_not_lose_committed_findings(tmp_path: Path) -> None:
    from tests.unit.test_monitor_watch_pass import world

    h = world(tmp_path, stale=True)

    def sink(_verdict: Any) -> None:
        raise Boom("sink")

    h.env.host_verdict = sink
    result = h.run()
    assert "timer_last_trigger_stale" in [p.event for p in h.alerts.payloads]
    assert "host_verdict_sink_failed" in result.unknown_reasons
    assert result.pass_result == "UNKNOWN"


# --------------------------------------------------------------------------- HIGH 2: summary cursor


def summary_world(tmp_path: Path, beat: dict[str, Any] | None) -> tuple[Any, list[int]]:
    from tests.unit.test_monitor_watch_pass import world

    seen: list[int] = []

    def reader(since_ns: int, _timeout: float) -> list[str]:
        seen.append(since_ns)
        return []

    h = world(tmp_path, summary=reader)
    if beat is not None:
        h.store.write_heartbeat(beat)
    return h, seen


def beat_of(ts_ns: int, attempt_ns: int) -> dict[str, Any]:
    return {
        "schema": "health_heartbeat/v1",
        "ts_ns": ts_ns,
        "last_attempt_ns": attempt_ns,
        "invocation_id": "x",
        "pass_result": "OK",
        "passes_unknown_streak": 0,
    }


def test_summary_reads_from_the_last_completed_pass_not_the_last_attempt(tmp_path: Path) -> None:
    """An UNKNOWN pass leaves ``ts_ns`` alone: its lines are re-read, never lost."""
    h, seen = summary_world(tmp_path, beat_of(NOW_NS - 3 * 3600 * NS, NOW_NS - 60 * NS))
    h.run()
    assert seen == [NOW_NS - 3 * 3600 * NS]  # a 3 h gap is read whole, not shrunk to 1 h


def test_first_ever_pass_reads_a_short_lookback(tmp_path: Path) -> None:
    h, seen = summary_world(tmp_path, None)
    h.run()
    assert seen == [NOW_NS - 15 * 60 * NS]


def test_a_gap_beyond_48h_is_clamped_and_said_so(tmp_path: Path) -> None:
    h, seen = summary_world(tmp_path, beat_of(NOW_NS - 10 * 86_400 * NS, NOW_NS - 60 * NS))
    h.run()
    assert seen == [NOW_NS - 48 * 3600 * NS]
    clamped = [p for p in h.alerts.payloads if p.event == "summary_lookback_clamped"]
    assert len(clamped) == 1 and clamped[0].severity == "WARNING"


# --------------------------------------------------------------------------- HIGH 3: evidence


def verdict_file(root: Path, family: str, detector: str, day: str = DAY) -> None:
    directory = root / "derived" / "verdicts" / family / day
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{abs(hash(detector)):x}.json").write_text(json.dumps({"detector": detector}))


def test_verdict_cadences_split_producers_by_detector_catalog_row(tmp_path: Path) -> None:
    assert scan_verdict_cadences(tmp_path) == frozenset()  # no verdict root: no evidence
    verdict_file(tmp_path, "_host", "aut6.timer_liveness")  # the health pass's own verdicts
    assert scan_verdict_cadences(tmp_path) == frozenset()
    verdict_file(tmp_path, "fam_a", "aut6.fill_better_than_ask")
    assert scan_verdict_cadences(tmp_path) == {"intraday"}
    verdict_file(tmp_path, "fam_b", "aut6.forecast_drift")
    assert "daily" in scan_verdict_cadences(tmp_path)
    verdict_file(tmp_path, "fam_c", "not.a.detector")  # unknown detector: ignored, not fatal
    (tmp_path / "derived" / "verdicts" / "fam_c" / DAY / "junk.json").write_text("{")


@pytest.mark.parametrize(
    ("detector", "vanished"),
    [("aut6.fill_better_than_ask", set(UNITS)), ("aut6.timer_liveness", set())],
)
def test_producer_verdict_files_are_artifacts_of_a_vanished_unit(
    tmp_path: Path, detector: str, vanished: set[str]
) -> None:
    verdict_file(tmp_path / "data", "fam_a", detector)
    deploy = synth_deploy(tmp_path / "deploy")
    result = x8(tmp_path, deploy, unit_files=x8_files(deploy))
    assert subjects(result.by_detector(TIMERS), "deployed_then_vanished") == vanished


def test_producer_journal_lines_are_artifacts_of_a_vanished_unit(tmp_path: Path) -> None:
    deploy = synth_deploy(tmp_path / "deploy")
    asked: list[str] = []

    def evidence(identifier: str, _timeout: float) -> bool:
        asked.append(identifier)
        return identifier == "breezy-autonomy-producer-daily"

    result = x8(tmp_path, deploy, unit_files=x8_files(deploy), journal_evidence=evidence)
    vanished = subjects(result.by_detector(TIMERS), "deployed_then_vanished")
    assert vanished == {"breezy-autonomy-producer-daily.service", DAILY_TIMER}
    assert set(asked) == {"breezy-autonomy-producer-daily", "breezy-autonomy-producer-intraday"}
    assert len(asked) == 2  # one read per identifier, not per unit


def test_an_unreadable_journal_is_a_reason_and_not_a_vanished_unit(tmp_path: Path) -> None:
    deploy = synth_deploy(tmp_path / "deploy")

    def broken(_identifier: str, _timeout: float) -> bool:
        raise JournalError("rc=1")

    result = x8(tmp_path, deploy, unit_files=x8_files(deploy), journal_evidence=broken)
    assert "journal_evidence_unreadable" in result.unknown_reasons
    assert not subjects(result.by_detector(TIMERS), "deployed_then_vanished")


# --------------------------------------------------------------------------- HIGH 4 and 5: RSS


def rss_world(
    tmp_path: Path, *, node_pid: Any, rss: dict[int, Any], recorder_pid: str = "0"
) -> Any:
    deploy = synth_deploy(tmp_path / "deploy")
    files = installed(deploy, skip=[TIMER_R], instances=[INSTANCE_ONE])
    blocks = [*healthy(deploy), show_block(RECORDER_UNIT, MainPID=recorder_pid)]

    def find() -> int | None:
        if isinstance(node_pid, Exception):
            raise node_pid
        return int(node_pid) if node_pid is not None else None

    w = wiring(tmp_path, deploy, find_node_pid=find, pid_rss_kib=lambda pid: rss.get(pid))
    return run_watch(w, snapshot(blocks=blocks, unit_files=files))


def memory_of(result: Any) -> Any:
    return result.by_detector("aut6.memory_budget")


def test_node_and_recorder_rss_come_from_proc_status_of_their_pids(tmp_path: Path) -> None:
    result = rss_world(tmp_path, node_pid=111, rss={111: 5000, 222: 700}, recorder_pid="222")
    assert result.resident_kib == (5000, 700)
    assert not memory_of(result).unknown_reasons


def test_no_node_process_is_a_real_zero_but_an_unreadable_one_is_unknown(tmp_path: Path) -> None:
    none = rss_world(tmp_path, node_pid=None, rss={})
    assert none.resident_kib == (0, 0) and not memory_of(none).unknown_reasons
    for rss in ({}, {111: 0}):
        bad = rss_world(tmp_path / str(len(rss)), node_pid=111, rss=rss)
        assert memory_of(bad).unknown_reasons == ("memory_rss_unreadable",), rss
        assert bad.resident_kib is None


def test_recorder_with_a_main_pid_but_no_rss_is_unknown_never_zero(tmp_path: Path) -> None:
    result = rss_world(tmp_path, node_pid=None, rss={}, recorder_pid="222")
    assert memory_of(result).unknown_reasons == ("memory_rss_unreadable",)


def test_a_failing_process_lookup_is_unknown(tmp_path: Path) -> None:
    result = rss_world(tmp_path, node_pid=OSError("pgrep"), rss={})
    assert memory_of(result).unknown_reasons == ("memory_rss_unreadable",)


def test_the_free_side_adds_back_the_same_rss_not_memory_current() -> None:
    blocks = {
        "a.service": {"MemoryCurrent": str(100 * 2**20)},
        NODE_UNIT: {"MemoryCurrent": str(9 * 2**30)},  # the cgroup figure must be ignored
        RECORDER_UNIT: {"MemoryCurrent": str(9 * 2**30)},
    }
    units = {"a.service", NODE_UNIT, RECORDER_UNIT}
    assert free_addback_kib(blocks, units, node_kib=5000, recorder_kib=700) == 100 * 1024 + 5700


def test_the_pass_samples_memavail_with_vmrss_for_node_and_recorder(tmp_path: Path) -> None:
    deploy = synth_deploy(tmp_path / "deploy")
    (tmp_path / "data" / "evidence" / "alerts").mkdir(parents=True)
    cur = str(100 * 2**20)
    blocks = "\n".join(
        [
            show_block("breezy-quote-tape-ingest.service", MemoryCurrent=cur),
            show_block(NODE_UNIT, MemoryCurrent=str(9 * 2**30)),
            show_block(RECORDER_UNIT, MemoryCurrent=str(9 * 2**30), MainPID="222"),
        ]
    )
    w = wiring(
        tmp_path,
        deploy,
        rows=NOT_YET_DEPLOYED,
        artifacts=NOT_DEPLOYED_ARTIFACTS,
        find_node_pid=lambda: 111,
        pid_rss_kib=lambda pid: {111: 5000, 222: 700}[pid],
    )
    clock = FakeClock()
    h = harness(
        tmp_path,
        snapshot=lambda: snapshot(blocks=[blocks], now_ns=clock.now_ns),
        clock=clock,
        watch=w,
        meminfo=lambda: (8_000_000, 16_000_000),
    )
    h.run()
    sample = json.loads(next(h.store.root.glob("memavail_*.jsonl")).read_text().splitlines()[0])
    assert sample["mem_available_free_kib"] == 8_000_000 + 100 * 1024 + 5700


def test_node_lookup_reuses_the_supervisors_anchor_and_a_shared_checked_lookup() -> None:
    assert vars(monitor_watch)["NODE_ARGV_ANCHOR"] is trade_supervisor_core.NODE_ARGV_ANCHOR
    from breezy.runtime import trade_supervisor

    assert vars(trade_supervisor)["find_pid_by_argv"] is process_lookup.find_pid_by_argv


def fake_run(rc: int, out: str = "", *, raises: Exception | None = None) -> Any:
    def run(argv: Any, **kw: Any) -> Any:
        if raises is not None:
            raise raises
        return subprocess.CompletedProcess(argv, rc, out, "")

    return run


def test_checked_lookup_separates_not_running_from_failed() -> None:
    check = process_lookup.find_pid_by_argv_checked
    assert check("a$", run=fake_run(0, "42\n")) == 42
    assert check("a$", run=fake_run(1)) is None
    for bad in (
        fake_run(2),
        fake_run(0, raises=OSError("x")),
        fake_run(0, raises=subprocess.TimeoutExpired("pgrep", 5)),
    ):
        with pytest.raises(OSError, match="pgrep"):
            check("a$", run=bad)
    assert process_lookup.find_pid_by_argv("a$", run=fake_run(2)) is None  # legacy: swallowed


# --------------------------------------------------------------------------- MEDIUM


def test_daily_without_subjects_fails_once_the_deployment_is_older_than_30h() -> None:
    src = type("S", (), {})()
    src.newest_daily_verdict_ns = dict
    src.daily_skips = list
    young = evaluate_daily(src, now_ns=NOW_NS, today=DAY, deployed_since_ns=NOW_NS - 10 * 3600 * NS)
    assert young.outcome == "INCONCLUSIVE" and not young.findings
    old = evaluate_daily(src, now_ns=NOW_NS, today=DAY, deployed_since_ns=NOW_NS - 31 * 3600 * NS)
    assert [f.kind for f in old.findings] == ["daily_verdict_absent"]
    blind = evaluate_daily(src, now_ns=NOW_NS, today=DAY, deployed_since_ns=None)
    assert blind.outcome == "INCONCLUSIVE" and blind.metrics["deployment_evidence_missing"] == "1"


def test_first_seen_survives_a_timer_restart(tmp_path: Path) -> None:
    """The stored first sighting, not a restarted timer's ActiveEnter, bounds the wait."""
    from tests.unit.test_monitor_watch_pass import world

    h = world(tmp_path, producer=FileProducerSource(tmp_path / "data"))
    h.store.write_seen(
        INTRADAY_TIMER, {"unit": INTRADAY_TIMER, "first_seen_ns": NOW_NS - 3 * 86_400 * NS}
    )
    h.env.read_snapshot = lambda: snapshot(
        blocks=[timer_block(INTRADAY_TIMER, entered_s=-60)],
        unit_files=installed(h.env.watch.deploy_dir, skip=[TIMER_R], instances=[INSTANCE_ONE])
        + "".join(f"{u:<44} enabled   enabled\n" for u in UNITS),
        now_ns=h.clock.now_ns,
    )
    h.run()
    assert "producer_heartbeat_missing" in [p.event for p in h.alerts.payloads]


def test_first_seen_is_recorded_once_and_never_moved(tmp_path: Path) -> None:
    from tests.unit.test_monitor_watch_pass import world

    h = world(tmp_path, producer=FileProducerSource(tmp_path / "data"))
    h.env.read_snapshot = lambda: snapshot(
        blocks=[timer_block(INTRADAY_TIMER, entered_s=-60)],
        unit_files=installed(h.env.watch.deploy_dir, skip=[TIMER_R], instances=[INSTANCE_ONE])
        + "".join(f"{u:<44} enabled   enabled\n" for u in UNITS),
        now_ns=h.clock.now_ns,
    )
    h.run()
    first = h.store.read_seen(INTRADAY_TIMER)["first_seen_ns"]
    h.clock.advance(600)
    h.run()
    assert h.store.read_seen(INTRADAY_TIMER)["first_seen_ns"] == first


def test_every_listed_template_instance_must_be_present_and_enabled(tmp_path: Path) -> None:
    deploy = synth_deploy(tmp_path / "deploy")
    expected = {INSTANCE_ONE: (86_400, 60), INSTANCE_TWO: (86_400, 60)}
    files = installed(deploy, skip=[TIMER_R], instances=[INSTANCE_ONE])
    result = judge(
        tmp_path, deploy, healthy(deploy), unit_files=files, wiring={"instance_intervals": expected}
    )
    assert subjects(result, "timer_instance_missing") == {INSTANCE_TWO}
    files += f"{INSTANCE_TWO:<44} disabled  enabled\n"
    result = judge(
        tmp_path, deploy, healthy(deploy), unit_files=files, wiring={"instance_intervals": expected}
    )
    assert subjects(result, "timer_instance_missing") == {INSTANCE_TWO}
    ok = judge(
        tmp_path,
        deploy,
        [*healthy(deploy), timer_block(INSTANCE_TWO)],
        unit_files=installed(deploy, skip=[TIMER_R], instances=[INSTANCE_ONE, INSTANCE_TWO]),
        wiring={"instance_intervals": expected},
    )
    assert "timer_instance_missing" not in kinds(ok)


def test_the_real_instance_table_is_all_present_in_a_complete_inventory() -> None:
    assert set(TIMER_INSTANCE_INTERVAL_S) and all("@" in n for n in TIMER_INSTANCE_INTERVAL_S)


def test_an_unreadable_or_empty_deploy_dir_is_a_reason_never_a_silent_skip(tmp_path: Path) -> None:
    missing = tmp_path / "no-such-deploy"
    with pytest.raises(OSError):
        deploy_unit_names(missing)
    empty = tmp_path / "empty"
    empty.mkdir()
    for directory in (missing, empty):
        w = wiring(tmp_path, directory)
        result = run_watch(w, snapshot(blocks=[], unit_files=""))
        assert "deploy_dir_unreadable" in result.by_detector(TIMERS).unknown_reasons
        assert "deploy_dir_unreadable" in memory_of(result).unknown_reasons


# --------------------------------------------------------------------------- LOW


def test_retired_timer_enabled_only_in_the_file_inventory_still_fails(
    tmp_path: Path,
) -> None:
    deploy = synth_deploy(tmp_path / "deploy")
    files = installed(deploy, instances=[INSTANCE_ONE])  # includes r.timer as enabled, unloaded
    result = judge(tmp_path, deploy, healthy(deploy), unit_files=files)
    assert subjects(result, "retired_timer_enabled") == {TIMER_R}


def test_a_table_key_absent_everywhere_is_a_finding(tmp_path: Path) -> None:
    deploy = synth_deploy(tmp_path / "deploy")
    table = {TIMER_A: (86_400, 60), "breezy-ghost.timer": (86_400, 60)}
    files = installed(deploy, skip=[TIMER_R])
    result = judge(tmp_path, deploy, healthy(deploy)[:1], unit_files=files, wiring={"table": table})
    assert subjects(result, "timer_table_key_orphan") == {"breezy-ghost.timer"}


def test_an_overdue_producer_is_one_page_from_the_timer_detector_not_a_second_critical(
    tmp_path: Path,
) -> None:
    import datetime as dt

    deploy = synth_deploy(tmp_path / "deploy")
    past = NOW_NS + ((dt.date(2026, 11, 20) - dt.date(2026, 10, 8)).days) * 86_400 * NS
    result = x8(tmp_path, deploy, unit_files=x8_files(deploy), now_ns=past)
    producer = result.by_detector(PRODUCER)
    assert producer.outcome == "INCONCLUSIVE" and not producer.findings
    assert producer.metrics["unknown_reason"] == "not_deployed_overdue"
    sev = {f.severity for f in result.by_detector(TIMERS).findings if f.subject in ROWS}
    assert sev == {"WARNING"}  # before 2026-11-30


def test_a_future_dated_heartbeat_is_a_finding() -> None:
    src = type("S", (), {})()
    src.heartbeat = lambda: {"ts_ns": NOW_NS + 3600 * NS, "fold_ok": True}
    result = evaluate_producer(src, now_ns=NOW_NS, today=DAY)
    assert [f.kind for f in result.findings] == ["producer_heartbeat_future"]
    src.heartbeat = lambda: {"ts_ns": NOW_NS + 30 * NS, "fold_ok": True}  # skew tolerated
    assert evaluate_producer(src, now_ns=NOW_NS, today=DAY).outcome == "PASS"


def test_the_artifact_table_still_names_only_listed_units() -> None:
    assert (
        set(NOT_DEPLOYED_ARTIFACTS) <= set(NOT_YET_DEPLOYED) and ARTIFACTS == NOT_DEPLOYED_ARTIFACTS
    )


def test_deleting_a_wp6_wp7_row_while_no_reader_is_wired_is_refused(tmp_path: Path) -> None:
    unwired = FileProducerSource(tmp_path)
    assert unwired_without_row({}, unwired) == ["intraday", "daily"]
    assert unwired_without_row(dict(NOT_YET_DEPLOYED), unwired) == []
    only_intraday = {k: v for k, v in NOT_YET_DEPLOYED.items() if "intraday" in k}
    assert unwired_without_row(only_intraday, unwired) == ["daily"]
    wired = FileProducerSource(tmp_path, missing=lambda _n: [], daily=dict)
    assert unwired_without_row({}, wired) == []
    assert unwired_without_row({}, None) == ["intraday", "daily"]


def test_production_watch_has_every_row_while_its_readers_are_unwired() -> None:
    watch = monitor_watch.production_watch(Path("/nonexistent"))
    assert unwired_without_row(watch.rows, watch.producer) == []
