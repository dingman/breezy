"""AUT-6 WP3 S5: the meta-detectors inside the unit health pass, and their production seams."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from breezy.runtime.monitor_watch import (
    NODE_LOG_TAIL_BYTES,
    NOT_DEPLOYED_ARTIFACTS,
    NOT_YET_DEPLOYED,
    SUMMARY_UNITS,
    journal_summary_reader,
    production_watch,
    read_node_log_tail,
    read_unit_rss_kib,
)
from breezy.runtime.monitor_watch_producer import FileProducerSource
from breezy.runtime.unit_health import production_env
from breezy.runtime.unit_health_journal import JournalError, RunResult
from breezy.runtime.unit_health_types import HostVerdict
from tests.support.monitor_watch_fixtures import (
    TIMER_A,
    installed,
    snapshot,
    synth_deploy,
    timer_block,
    wiring,
)
from tests.support.unit_health_fixtures import DAY, NOW_NS, NS, FakeClock
from tests.unit.test_unit_health import harness

INSTANCE = "breezy-t@one.timer"


def world(tmp_path: Path, *, stale: bool = False, **extra: Any) -> Any:
    deploy = synth_deploy(
        tmp_path / "deploy",
        {"breezy-quote-tape-ingest.service": "[Service]\nExecStart=/bin/true\nMemoryMax=2G\n"},
    )
    (tmp_path / "data" / "evidence" / "alerts").mkdir(parents=True)
    clock = FakeClock()
    files = installed(deploy, skip=["breezy-r.timer"], instances=[INSTANCE])
    blocks = [
        timer_block(TIMER_A, last_s=-3 * 86_400 if stale else -60, next_s=7200),
        timer_block("breezy-m.timer", monotonic_next="45min", next_s=None, last_s=-60),
        timer_block(INSTANCE, last_s=-60, next_s=7200),
    ]
    watch = wiring(
        tmp_path,
        deploy,
        rows=NOT_YET_DEPLOYED,
        artifacts=NOT_DEPLOYED_ARTIFACTS,
        **extra,
    )
    return harness(
        tmp_path,
        snapshot=lambda: snapshot(blocks=blocks, unit_files=files, now_ns=clock.now_ns),
        clock=clock,
        watch=watch,
        meminfo=lambda: (8_000_000, 16_000_000),
    )


def events(h: Any) -> list[str]:
    return [p.event for p in h.alerts.payloads]


def test_a_timer_finding_pages_once_a_day_across_passes(tmp_path: Path) -> None:
    h = world(tmp_path, stale=True)
    first = h.run()
    h.clock.advance(600)
    second = h.run()
    assert events(h).count("timer_last_trigger_stale") == 1
    assert first.pass_result == "FINDINGS"
    assert second.pass_result == "OK"  # a standing finding is not a new one: no second page
    payload = next(p for p in h.alerts.payloads if p.event == "timer_last_trigger_stale")
    assert payload.severity == "CRITICAL" and TIMER_A in payload.detail
    h.clock.advance(86_400)
    h.run()
    stale_a = [
        p
        for p in h.alerts.payloads
        if p.event == "timer_last_trigger_stale" and TIMER_A in p.detail
    ]
    assert len(stale_a) == 2  # a new UTC day pages again


def test_a_healthy_world_pages_nothing_and_lists_the_not_deployed_units(tmp_path: Path) -> None:
    h = world(tmp_path)
    result = h.run()
    assert result.pass_result == "OK", (result.unknown_reasons, events(h))
    assert events(h) == []
    day = h.store.read_rollup(DAY)
    assert day["not_deployed"] == sorted(NOT_YET_DEPLOYED)
    beat = h.store.read_heartbeat()
    assert beat["passes_unknown_streak"] == 0 and beat["pass_result"] == "OK"


def test_not_deployed_never_counts_toward_the_unknown_streak(tmp_path: Path) -> None:
    h = world(tmp_path)
    for _ in range(4):
        h.clock.advance(600)
        result = h.run()
        assert result.pass_result == "OK", (events(h), result.unknown_reasons)
    assert h.store.read_heartbeat()["passes_unknown_streak"] == 0
    assert h.store.read_rollup(DAY)["max_passes_unknown_streak"] == 0


def test_unreadable_meta_inputs_make_the_pass_unknown(tmp_path: Path) -> None:
    h = world(tmp_path, node_log_tail=lambda: None)
    result = h.run()
    assert result.pass_result == "UNKNOWN" and "node_log_tail_unreadable" in result.unknown_reasons
    assert h.store.read_heartbeat()["passes_unknown_streak"] == 1


def test_every_detector_hands_a_verdict_to_the_host_sink(tmp_path: Path) -> None:
    seen: list[HostVerdict] = []
    h = world(tmp_path)
    h.env.host_verdict = seen.append
    h.run()
    by = {v.detector: v for v in seen}
    assert {
        "aut6.timer_liveness",
        "aut6.producer_stale",
        "aut6.daily_verdict_absent",
        "aut6.alert_delivery",
        "aut6.memory_budget",
    } <= set(by)
    assert by["aut6.producer_stale"].outcome == "INCONCLUSIVE"
    assert by["aut6.producer_stale"].metrics["unknown_reason"] == "not_deployed"
    assert all(v.ts_ns == NOW_NS for v in seen)


def test_finding_class_records_carry_the_detector_and_metrics(tmp_path: Path) -> None:
    h = world(tmp_path, stale=True)
    h.run()
    records = h.store.finding_records_on(DAY, "timer_last_trigger_stale")
    assert records and records[0]["detector"] == "aut6.timer_liveness"
    assert records[0]["metrics"] == {"unit": TIMER_A}


def test_a_pass_without_watch_wiring_is_unchanged(tmp_path: Path) -> None:
    h = harness(tmp_path, snapshot=lambda: snapshot(blocks=[]))
    assert h.run().pass_result == "OK"
    day = h.store.read_rollup(DAY)
    assert day is not None and day["not_deployed"] == []


# --------------------------------------------------------------------------- production seams


def test_production_env_wires_the_meta_detectors(tmp_path: Path) -> None:
    env = production_env(environ={}, data_root=tmp_path)
    assert env.watch is not None and env.watch.data_root == tmp_path
    assert isinstance(env.watch.producer, FileProducerSource)
    assert env.watch.deploy_dir.name == "systemd" and env.watch.deploy_dir.is_dir()
    assert env.watch.summary is not None and env.watch.node_log_tail is not None
    assert production_watch(tmp_path).rows is NOT_YET_DEPLOYED


def test_journal_summary_reader_builds_one_bounded_argv_and_filters_lines() -> None:
    calls: list[tuple[list[str], float]] = []

    def run(argv: Any, timeout_s: float) -> RunResult:
        calls.append((list(argv), timeout_s))
        text = (
            "noise\nAUTONOMY_CANARY journal_write_failures=2\n"
            "PRODUCER_INTRADAY_DEMAND INTEGRITY x\n"
        )
        return RunResult(0, text, False, False)

    reader = journal_summary_reader(run)
    lines = reader(1_700_000_000 * NS, 7.5)
    assert lines == [
        "AUTONOMY_CANARY journal_write_failures=2",
        "PRODUCER_INTRADAY_DEMAND INTEGRITY x",
    ]
    argv, timeout = calls[0]
    assert timeout == 7.5 and argv[1:3] == ["--user", "-o"] and "--since=@1700000000" in argv
    assert [a for a in argv if a.startswith("_SYSTEMD_USER_UNIT=")] == [
        f"_SYSTEMD_USER_UNIT={u}" for u in SUMMARY_UNITS
    ]


@pytest.mark.parametrize(
    "result",
    [RunResult(1, "", False, False), RunResult(-9, "", True, False), RunResult(0, "", False, True)],
)
def test_journal_summary_reader_errors_are_unknown_never_empty(result: RunResult) -> None:
    reader = journal_summary_reader(lambda _a, _t: result)
    with pytest.raises(JournalError):
        reader(0, 1.0)


def test_a_failing_summary_read_makes_the_pass_unknown(tmp_path: Path) -> None:
    def broken(_since: int, _timeout: float) -> Any:
        raise JournalError("rc=1")

    h = world(tmp_path, summary=broken)
    assert "summary_lines_unreadable" in h.run().unknown_reasons


def test_node_log_tail_reads_the_newest_log_bounded(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    assert read_node_log_tail(logs) == ""  # no directory: no node, nothing to read
    logs.mkdir()
    assert read_node_log_tail(logs) == ""
    (logs / "breezy-trade-20261007T000000Z.log").write_text("old\n")
    (logs / "breezy-trade-supervisor.log").write_text("not a node log\n")
    big = logs / "breezy-trade-20261008T000000Z.log"
    big.write_bytes(b"A" * (NODE_LOG_TAIL_BYTES + 10) + b"TAIL")
    tail = read_node_log_tail(logs)
    assert tail is not None and tail.endswith("TAIL") and len(tail) == NODE_LOG_TAIL_BYTES
    big.chmod(0)
    try:
        assert read_node_log_tail(logs) is None
    finally:
        big.chmod(0o600)


def test_unit_rss_sums_the_processes_of_one_cgroup(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    for pid, cgroup, rss in (
        ("100", "0::/user.slice/user-1000.slice/app.slice/breezy-trade-supervisor.service", 4096),
        ("101", "0::/user.slice/app.slice/breezy-trade-supervisor.service", 1024),
        ("200", "0::/user.slice/app.slice/breezy-quote-tape.service", 777),
    ):
        (proc / pid).mkdir(parents=True)
        (proc / pid / "cgroup").write_text(cgroup + "\n")
        (proc / pid / "status").write_text(f"Name:\tx\nVmRSS:\t   {rss} kB\n")
    (proc / "self").mkdir()
    (proc / "300").mkdir()  # exited while scanning: no files
    assert read_unit_rss_kib("breezy-trade-supervisor.service", proc) == 5120
    assert read_unit_rss_kib("breezy-quote-tape.service", proc) == 777
    assert read_unit_rss_kib("breezy-absent.service", proc) == 0
    assert read_unit_rss_kib("x.service", tmp_path / "nope") is None


def test_the_meta_detector_class_record_is_plain_json(tmp_path: Path) -> None:
    h = world(tmp_path, stale=True)
    h.run()
    for path in (h.store.root / DAY).glob("*__class.json"):
        json.loads(path.read_text())
