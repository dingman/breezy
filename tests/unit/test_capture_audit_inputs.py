"""AUT-1 WP5 stage 2b W3: ``gather_inputs`` and its parts (plan r12 section 3.11.1; S2-R6, S2-R14).

A REAL data root under ``tmp_path`` (``tests/support/capture_audit_w3_fixtures.py``): real node
logs, real streams from the real writer, a real SQLite exec store written through the real
``DurableFillRecord``, real Parquet tape, a bus snapshot in seam B's document shape. Only the two
W2 sinks and ``journalctl`` are fakes. Each fail-loud cause is provoked by breaking exactly one
input of an otherwise good world.
"""

import datetime as dt
import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from breezy.analysis import capture_audit_cache as cache
from breezy.analysis import capture_audit_exec_view as exec_view
from breezy.analysis import capture_audit_host as host
from breezy.analysis import capture_audit_inputs as inputs
from breezy.analysis.capture_audit_input_types import LogMarkers, ReplayResult
from breezy.analysis.capture_audit_model import AuditInputError
from breezy.domain import exec_intent
from breezy.ingest import nbm_quantile_actor
from breezy.persistence.autonomy.capture_reader import read_capture_stream
from breezy.persistence.autonomy.capture_stream import capture_root
from breezy.runtime.autonomy_sandbox.wal_snapshot import exec_snapshot
from tests.support import capture_audit_w3_fixtures as w3
from tests.support.capture_node_log_fixtures import write_log

DAY = w3.DAY
NS = w3.NS


def _cause(root: Path, **kw: Any) -> str:
    with pytest.raises(AuditInputError) as info:
        w3.gather(root, **kw)
    return info.value.cause


# -- a complete world --------------------------------------------------------------------------


def test_a_complete_world_gathers_one_boot_with_every_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.full_world(tmp_path, monkeypatch)
    inp = w3.gather(root)
    (boot,) = inp.boots
    assert (boot.instance_id, boot.source) == (w3.INSTANCE, "live")
    assert boot.log_name == f"breezy-trade-{w3.LOG_STAMP}.log"
    assert boot.disposed and boot.ended and boot.scan is not None and boot.scan.node_disposed
    assert boot.summary.row_counts["custom_decision_record"] == 1
    assert boot.summary.heartbeats[0].ts_ns == w3.day_ns(DAY, 17, 0)
    assert boot.c1.decisions and boot.stream().instance_id == w3.INSTANCE
    assert boot.subscribed == {w3.INSTRUMENT}
    assert inp.recorder_props.watchdog_usec == 600_000_000
    assert inp.ingest_exited_after_rotation is True
    assert inp.epoch is not None and inp.epoch.family_id == w3.FAMILY
    assert [f.trade_id for f in inp.exec.fills] == ["CVWEANWH8YHR"] and inp.exec.advisory
    assert inp.tape.lookup("quote", w3.INSTRUMENT, w3.day_ns(DAY, 17, 0)) == {
        "ask": "0.15",
        "bid": "0.01",
        "ts_event": w3.day_ns(DAY, 17, 0),
    }
    assert inp.std_offsets["LAX"] == inp.std_offsets["KLAX"] == -8.0
    assert inp.nbp_stations == ("KLAX", "KMDW", "KMIA", "KNYC", "KSFO")


def test_nbp_cycles_are_those_whose_3h_deadline_falls_on_the_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inp = w3.gather(w3.full_world(tmp_path, monkeypatch))
    hours = [(c // NS - w3.day_ns(DAY) // NS) // 3600 for c in inp.nbp_cycles_ns]
    assert hours == [1, 13, 19]
    assert all(
        w3.day_ns(DAY) <= c + 3 * 3600 * NS < w3.day_ns(DAY + dt.timedelta(days=1))
        for c in inp.nbp_cycles_ns
    )


def test_the_restated_cycle_hours_equal_the_actors_constant() -> None:
    assert inputs.NBP_CYCLE_HOURS_UTC == nbm_quantile_actor.DEFAULT_NBM_QUANTILE_CYCLE_HOURS


def test_the_boot_overlap_is_measured_inside_the_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.full_world(tmp_path, monkeypatch)
    (boot,) = w3.gather(root).boots
    assert boot.started_ns == w3.day_ns(DAY, 16, 50) + 45 * NS  # the log's own name stamp
    assert boot.overlap_s == (w3.day_ns(DAY, 23, 0) - boot.started_ns) // NS


def test_the_journals_are_asked_for_the_right_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = w3.JournalFake(supervisor=w3.supervisor_launched())
    root = w3.full_world(tmp_path, monkeypatch, journal=fake)
    w3.gather(root)
    windows = {key: (since, until) for key, since, until in fake.calls}
    assert windows[host.SUPERVISOR_JOURNAL_ARGV] == (
        "2026-10-02 00:00:00 UTC",
        "2026-10-04 00:00:00 UTC",
    )
    assert windows[host.RECORDER_JOURNAL_ARGV] == (
        "2026-10-03 00:00:00 UTC",
        "2026-10-04 00:00:00 UTC",
    )
    assert windows[host.INGEST_JOURNAL_ARGV] == (
        "2026-10-04 00:00:00 UTC",
        "2026-10-05 00:00:00 UTC",
    )


def test_stall_records_and_notifier_proofs_are_read_single_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.full_world(tmp_path, monkeypatch)
    inv = "ab" * 16
    stall = root / "evidence" / "capture" / "stall" / DAY.isoformat()
    stall.mkdir(parents=True)
    ts = w3.day_ns(DAY, 5)
    record = stall / f"{ts}_{inv}_recorder_watchdog.json"
    record.write_text(json.dumps({"invocation_id": inv, "detected_ns": ts}))
    record.chmod(0o600)  # the stop hook's own mode
    proofs = root / "evidence" / "alerts" / "notify" / DAY.isoformat()
    proofs.mkdir(parents=True)
    (proofs / f"breezy-quote-tape.service__{inv}.delivered.json").write_text('{"delivered": true}')
    (proofs / f"breezy-quote-tape.service__{'cd' * 16}.delivered.json").write_text(
        '{"delivered": false}'
    )
    (proofs / f"breezy-quote-tape.service__{'ef' * 16}.delivered.json").write_text("{torn")
    inp = w3.gather(root)
    assert [(s.invocation_id, s.ts_ns, s.day) for s in inp.stall_records] == [
        (inv, ts, DAY.isoformat())
    ]
    delivered = {p.invocation_id: p.delivered for p in inp.notifier_proofs}
    assert delivered == {
        inv: True,
        "cd" * 16: False,
        "ef" * 16: False,
    }  # a torn marker proves nothing


def test_the_funnel_rows_of_the_boot_day_are_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.full_world(tmp_path, monkeypatch)
    row = {
        "ts_ns": w3.day_ns(DAY, 17, 15),
        "boot_day": DAY.isoformat(),
        "final": False,
        "counts": [{"station": "LAX", "side": "yes", "kind": "Take", "reason": "", "count": 2}],
    }
    path = root / "catalog" / "quote_tape" / "decisions" / f"fq_funnel_{DAY.isoformat()}.jsonl"
    path.write_text(json.dumps(row) + "\n")
    path.chmod(0o600)
    (funnel,) = w3.gather(root).funnel
    assert (
        funnel.boot_day == DAY.isoformat()
        and funnel.counts[0].count == 2
        and funnel.counts[0].kind == "Take"
    )


def test_settlements_of_the_surrounding_climate_days_are_loaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from breezy.analysis.capture_settlement import SettlementRecord

    root = w3.full_world(tmp_path, monkeypatch)
    for offset in (-1, 1, 3):
        day = DAY + dt.timedelta(days=offset)
        path = root / "catalog" / "quote_tape" / "decisions" / f"settlement_{day}.jsonl"
        path.write_text(SettlementRecord("LAX", str(day), 84, "NWS_CLI", "ab" * 32, 1).to_line())
        path.chmod(0o600)
    inp = w3.gather(root)
    assert sorted(r.climate_day for r in inp.settlements) == [
        "2026-10-02",
        "2026-10-04",
    ]  # D+3 is out


def test_a_resolver_context_created_on_the_day_marks_resolver_live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.full_world(tmp_path, monkeypatch)
    context = {
        "intentId": "i1",
        "clientOrderId": "O-1",
        "instrumentId": w3.INSTRUMENT,
        "createdNs": w3.day_ns(DAY, 18),
    }
    rows = w3.standard_exec_rows()
    rows[f"{exec_intent.RESOLVER_CONTEXT_KEY_PREFIX}i1"] = json.dumps(context).encode()
    w3.write_exec_store(root, rows)
    inp = w3.gather(root)
    assert inp.resolver_live and [r.intent_id for r in inp.exec.resolvers] == ["i1"]


# -- the boot census (H5, WP0-R5/R9, S2-R14) ---------------------------------------------------


def test_census_counts_a_boot_seen_three_ways_once_by_instance_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.full_world(tmp_path, monkeypatch)  # a log, a live stream dir and a supervisor spawn
    ids = inputs.boot_census(root, DAY, supervisor_journal=w3.supervisor_launched())
    assert ids == (w3.INSTANCE,)


def test_census_is_the_union_of_log_stream_and_spawn_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.full_world(tmp_path, monkeypatch)
    w3.write_node_log(
        root,
        stamp="20261003T120000Z",
        instance_id=w3.OTHER_INSTANCE,
        start_ns=w3.day_ns(DAY, 12),
        disposed_ns=w3.day_ns(DAY, 14),
    )
    spawns = f"{w3.supervisor_launched('2026-10-03T12:00:00Z')}\n{w3.supervisor_launched()}\n"
    assert inputs.boot_census(root, DAY, supervisor_journal=spawns) == tuple(
        sorted((w3.INSTANCE, w3.OTHER_INSTANCE))
    )


def test_a_boot_that_ended_before_the_day_is_not_a_member(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.full_world(tmp_path, monkeypatch)
    w3.write_node_log(
        root,
        stamp="20261001T120000Z",
        instance_id=w3.OTHER_INSTANCE,
        start_ns=w3.day_ns(DAY - dt.timedelta(days=2), 12),
        disposed_ns=w3.day_ns(DAY - dt.timedelta(days=2), 14),
    )
    assert inputs.boot_census(root, DAY, supervisor_journal=w3.supervisor_launched()) == (
        w3.INSTANCE,
    )


def test_supervisor_spawn_without_log_is_error_node_log_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.full_world(tmp_path, monkeypatch)
    spawns = f"{w3.supervisor_launched()}\n{w3.supervisor_launched('2026-10-03T21:30:00Z')}\n"
    with pytest.raises(AuditInputError) as info:
        inputs.boot_census(root, DAY, supervisor_journal=spawns)
    assert (info.value.cause, info.value.detail) == ("node_log_missing", "spawn_without_log")


def test_capture_records_without_node_log_is_error_not_no_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.full_world(tmp_path, monkeypatch)
    w3.write_stream(root, instance_id=w3.OTHER_INSTANCE)  # a stream whose boot has no log
    assert _cause(root) == "node_log_missing"


def test_a_stream_record_naming_an_unknown_boot_is_node_log_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.make_root(tmp_path)
    w3.install(monkeypatch, root)
    w3.write_node_log(root)
    w3.write_stream(root, node_boot_id=w3.OTHER_INSTANCE)
    w3.write_exec_store(root, {})
    assert _cause(root) == "node_log_missing"


def test_supervisor_journal_failure_is_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Failing(w3.JournalFake):
        def __call__(self, template: Any, since: str, until: str, **_: Any) -> str:
            if tuple(template) == host.SUPERVISOR_JOURNAL_ARGV:
                raise AuditInputError("journal_failed", "exit_1")
            return super().__call__(template, since, until)

    root = w3.full_world(tmp_path, monkeypatch, journal=Failing(supervisor="x"))
    assert _cause(root) == "journal_failed"


def test_an_empty_supervisor_journal_on_a_day_with_node_logs_is_journal_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.full_world(tmp_path, monkeypatch, journal=w3.JournalFake(supervisor=""))
    assert _cause(root) == "journal_failed"


def test_an_empty_supervisor_journal_on_a_day_with_no_logs_is_tolerated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.make_root(tmp_path)
    w3.install(monkeypatch, root, journal=w3.JournalFake(supervisor=""))
    w3.write_exec_store(root, {})
    inp = w3.gather(root)
    assert inp.boots == () and inp.epoch is None


def test_the_ingest_journal_may_be_empty_unless_the_unit_exited_after_the_rotation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    quiet = w3.JournalFake(supervisor=w3.supervisor_launched(), ingest="")
    root = w3.full_world(
        tmp_path, monkeypatch, journal=quiet
    )  # the planted exit is after D's rotation
    assert _cause(root) == "journal_failed"
    w3.plant_snapshot(root, ingest="ExecMainExitTimestamp=Fri 2026-10-02 09:07:22 UTC\n")
    host._BUS_OUTCOMES.clear()
    inp = w3.gather(root)
    assert inp.ingest_lines == () and inp.ingest_exited_after_rotation is False


def test_journalctl_failures_are_errors_never_empty_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Broken(w3.JournalFake):
        def __call__(self, template: Any, since: str, until: str, **_: Any) -> str:
            if tuple(template) == host.RECORDER_JOURNAL_ARGV:
                raise AuditInputError("journal_failed", "timeout")
            return super().__call__(template, since, until)

    root = w3.full_world(tmp_path, monkeypatch, journal=Broken(supervisor=w3.supervisor_launched()))
    assert _cause(root) == "journal_failed"


def test_an_empty_recorder_journal_is_a_quiet_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.full_world(
        tmp_path,
        monkeypatch,
        journal=w3.JournalFake(supervisor=w3.supervisor_launched(), recorder=""),
    )
    assert w3.gather(root).recorder_journal == ()


# -- fail-loud (C2, D15): one broken input each ------------------------------------------------


def _break_exec_open(root: Path) -> None:
    (root / "state" / "exec_polymarket_us.sqlite").unlink()


def _break_exec_decode(root: Path) -> None:
    rows = w3.standard_exec_rows()
    rows[f"{exec_intent.FILL_KEY_PREFIX}CVWBAD"] = b"{not json"
    w3.write_exec_store(root, rows)


def _break_exec_prefix(root: Path) -> None:
    w3.write_exec_store(
        root, {**w3.standard_exec_rows(), f"{exec_intent.STATE_KEY_NAMESPACE}fills_v2/x": b"1"}
    )


def _break_log_dir(root: Path) -> None:
    (root / "logs").rmdir() if not any((root / "logs").iterdir()) else None
    for log in (root / "logs").iterdir():
        log.unlink()
    (root / "logs").rmdir()
    (root / "logs").write_text("not a directory")


def _break_marker(root: Path) -> None:
    (log,) = (root / "logs").iterdir()
    log.write_bytes(
        log.read_bytes().replace(
            b"\n", b"\n[INFO] BREEZY-L001.breezy: NBM_NBP_PUBLISHED garbage\n", 1
        )
    )


def _break_epoch_missing(root: Path) -> None:
    (root / "evidence" / "capture" / "epoch" / f"{w3.FAMILY}.json").unlink()


def _break_epoch_rewritten(root: Path) -> None:
    (root / "evidence" / "capture" / "epoch" / f"{w3.FAMILY}.json").unlink()
    w3.write_epoch(root, epoch_ns=w3.day_ns(DAY, 19))  # later than the first stream record (17:00)


def _break_epoch_unreadable(root: Path) -> None:
    path = root / "evidence" / "capture" / "epoch" / f"{w3.FAMILY}.json"
    path.chmod(0o644)
    path.write_text("{}")


def _break_stream_file(root: Path) -> None:
    feather = next(capture_root(root, w3.VENUE).rglob("*.feather"))
    other = feather.with_name("elsewhere")
    other.write_bytes(feather.read_bytes())
    feather.unlink()
    feather.symlink_to(other)  # a symlink in a stream directory is refused, never followed


def _break_funnel(root: Path) -> None:
    path = root / "catalog" / "quote_tape" / "decisions" / f"fq_funnel_{DAY.isoformat()}.jsonl"
    path.write_text("{torn\n")
    path.chmod(0o600)


def _break_tape(root: Path) -> None:
    parquet = next((root / "catalog").rglob("*.parquet"))
    parquet.write_bytes(b"PAR1 broken")


def _break_settlement(root: Path) -> None:
    path = root / "catalog" / "quote_tape" / "decisions" / f"settlement_{DAY}.jsonl"
    path.write_text("not json\n")
    path.chmod(0o600)


@pytest.mark.parametrize(
    ("breaker", "cause"),
    [
        (_break_exec_open, "exec_snapshot_failed"),
        (_break_exec_decode, "exec_record_undecodable"),
        (_break_exec_prefix, "exec_key_prefix_unknown"),
        (_break_log_dir, "node_log_unreadable"),
        (_break_marker, "node_log_unparseable"),
        (_break_epoch_missing, "epoch_missing"),
        (_break_epoch_rewritten, "epoch_rewritten"),
        (_break_epoch_unreadable, "epoch_unreadable"),
        (_break_stream_file, "stream_unreadable"),
        (_break_funnel, "funnel_missing"),
        (_break_tape, "tape_unreadable"),
        (_break_settlement, "settlement_unreadable"),
    ],
    ids=lambda v: getattr(v, "__name__", v),
)
def test_each_broken_input_is_a_named_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, breaker: Any, cause: str
) -> None:
    root = w3.full_world(tmp_path, monkeypatch)
    breaker(root)
    assert _cause(root) == cause


def test_exec_store_open_error_is_error_never_no_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.full_world(tmp_path, monkeypatch)
    (root / "state" / "exec_polymarket_us.sqlite").unlink()
    with pytest.raises(AuditInputError) as info:
        inputs.read_exec_view(root)
    assert info.value.cause == "exec_snapshot_failed"


def test_undecodable_fill_record_is_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = w3.full_world(tmp_path, monkeypatch)
    _break_exec_decode(root)
    with pytest.raises(AuditInputError) as info:
        inputs.read_exec_view(root)
    assert (info.value.cause, info.value.detail) == ("exec_record_undecodable", "fill")


def test_unknown_exec_key_prefix_is_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = w3.full_world(tmp_path, monkeypatch)
    _break_exec_prefix(root)
    with pytest.raises(AuditInputError) as info:
        inputs.read_exec_view(root)
    assert info.value.cause == "exec_key_prefix_unknown"


def test_unreadable_node_log_is_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = w3.full_world(tmp_path, monkeypatch)
    (log,) = (root / "logs").iterdir()
    log.chmod(0)
    if os.access(log, os.R_OK):
        pytest.skip("running as a user that ignores file modes")
    assert _cause(root) == "node_log_unreadable"
    log.chmod(0o600)


def test_unparseable_marker_line_is_error_node_log_unparseable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.full_world(tmp_path, monkeypatch)
    _break_marker(root)
    with pytest.raises(AuditInputError) as info:
        w3.gather(root)
    assert info.value.cause == "node_log_unparseable"


def test_a_torn_last_line_of_a_running_log_is_not_unparseable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.full_world(tmp_path, monkeypatch)
    (log,) = (root / "logs").iterdir()
    log.write_bytes(log.read_bytes() + b"2026-10-03T23:30:00.0Z [INFO] torn")
    assert w3.gather(root).boots


def test_a_sink_that_raises_is_node_log_sink_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.full_world(tmp_path, monkeypatch)

    class Boom(w3.FakeReplay):
        def feed(self, event: object) -> None:
            raise RuntimeError("sink bug")

    monkeypatch.setattr(inputs, "BootReplay", Boom)
    assert _cause(root) == "node_log_sink_failed"


def test_a_record_naming_a_boot_with_a_log_but_no_instance_line_is_node_log_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.full_world(tmp_path, monkeypatch)
    write_log(root / "logs" / "breezy-trade-20261003T170000Z.log", "plain line only")
    spawns = f"{w3.supervisor_launched()}\n{w3.supervisor_launched('2026-10-03T17:00:00Z')}\n"
    host_fake = w3.JournalFake(supervisor=spawns)
    monkeypatch.setattr(inputs, "run_journal", host_fake)
    assert _cause(root) == "node_log_missing"


def test_the_bus_snapshot_errors_surface_through_gather(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.full_world(tmp_path, monkeypatch, snapshot=False)
    assert _cause(root) == "bus_snapshot_missing"
    host._BUS_OUTCOMES.clear()
    w3.plant_snapshot(root, ts_ns=w3.NOW_NS - 3600 * NS)
    assert _cause(root) == "bus_snapshot_stale"


# -- the exec store (E-8a, L-42) ---------------------------------------------------------------


def test_exec_store_read_uses_snapshot_helper_without_flock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.full_world(tmp_path, monkeypatch)
    seen: list[dict[str, Any]] = []
    real = exec_snapshot

    def spy(**kw: Any) -> Any:
        seen.append(kw)
        return real(**kw)

    monkeypatch.setattr(exec_view, "exec_snapshot", spy)
    inputs.read_exec_view(root)
    assert len(seen) == 1 and seen[0]["take_flock"] is False and seen[0]["data_root"] == root
    assert seen[0]["cache_dir"] == root / "cache" / "capture_audit"


def test_the_exec_store_itself_is_never_opened_by_the_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.full_world(tmp_path, monkeypatch)
    db = root / "state" / "exec_polymarket_us.sqlite"
    before = (db.stat().st_mtime_ns, db.stat().st_size)
    real_connect = sqlite3.connect
    opened: list[str] = []

    def spy(target: Any, *a: Any, **k: Any) -> Any:
        opened.append(str(target))
        return real_connect(target, *a, **k)

    monkeypatch.setattr(sqlite3, "connect", spy)
    inputs.read_exec_view(root)
    assert all(str(db) not in o.split("?")[0] for o in opened) and opened  # only the cached copy
    assert (db.stat().st_mtime_ns, db.stat().st_size) == before


def test_exec_store_fixture_written_through_real_record_fill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L-42: every record the fixture stores is the REAL client's own encoding, read back through
    the audit's decoder (the client class cannot be imported by the audit itself, E-7a)."""
    record = w3.fill_record()
    assert w3.real_client_round_trip(record)
    root = w3.full_world(tmp_path, monkeypatch)
    (fill,) = inputs.read_exec_view(root).fills
    assert (fill.client_order_id, fill.instrument_id, fill.trade_id, fill.ts_event) == (
        record.client_order_id,
        record.instrument_id,
        record.trade_id,
        record.ts_event,
    )
    assert (fill.cumulative_qty, fill.cumulative_cost) == ("1", "0.15") and fill.fee_reconciled


def test_venue_order_ids_leave_the_exec_view_only_as_sha256(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.full_world(tmp_path, monkeypatch)
    view = inputs.read_exec_view(root)
    sha = hashlib.sha256(b"CVW455HKJYGE").hexdigest()
    assert view.fills[0].venue_order_id_sha256 == sha and view.fill_by_day[DAY.isoformat()] == (
        sha,
    )
    assert view.orders[0].venue_order_id_sha256 == sha
    assert "CVW455HKJYGE" not in repr(view)


def test_the_fingerprint_and_resolver_keys_are_decoded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.full_world(tmp_path, monkeypatch)
    rows = w3.standard_exec_rows()
    rows[f"{exec_intent.FILL_BY_FINGERPRINT_KEY_PREFIX}{DAY}:{'cd' * 32}"] = b"CVW455HKJYGE"
    w3.write_exec_store(root, rows)
    view = inputs.read_exec_view(root)
    assert view.fill_by_fingerprint == {
        f"{DAY}:{'cd' * 32}": hashlib.sha256(b"CVW455HKJYGE").hexdigest()
    }


def test_keys_outside_the_exec_namespace_are_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.full_world(tmp_path, monkeypatch)
    w3.write_exec_store(root, {**w3.standard_exec_rows(), "latch/family_halt": b"1"})
    assert len(inputs.read_exec_view(root).fills) == 1


def test_the_known_exec_prefixes_cover_every_client_constant() -> None:
    constants = w3.client_key_constants()
    assert all(c.startswith(exec_view.KNOWN_EXEC_SUBPREFIXES) for c in constants), constants


# -- canary and drill --------------------------------------------------------------------------


def test_canary_fills_reported_separately_never_in_live_legs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.full_world(tmp_path, monkeypatch)
    w3.write_stream(root, source="canary", with_decision=False)
    inp = w3.gather(root)
    assert sorted((b.source, b.instance_id) for b in inp.boots) == [
        ("canary", w3.INSTANCE),
        ("live", w3.INSTANCE),
    ]
    canary = next(b for b in inp.boots if b.source == "canary")
    assert (
        canary.scan is None and canary.markers == LogMarkers() and canary.replay == ReplayResult()
    )
    live = next(b for b in inp.boots if b.source == "live")
    assert live.c1.decisions and not canary.c1.decisions


def test_a_live_boot_never_opens_the_canary_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.full_world(tmp_path, monkeypatch)
    opened: list[str] = []
    real = read_capture_stream

    def spy(directory: Path) -> Any:
        opened.append(directory.parent.name)
        return real(directory)

    monkeypatch.setattr(inputs, "read_capture_stream", spy)
    w3.gather(root)
    assert opened == ["live"]  # no canary directory exists, so none is opened


def test_the_stream_handle_reads_the_boot_again_on_demand(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.full_world(tmp_path, monkeypatch)
    (boot,) = w3.gather(root).boots
    reads: list[int] = []
    real = read_capture_stream
    monkeypatch.setattr(inputs, "read_capture_stream", w3.wrapping(reads, real))
    assert reads == [] and boot.stream().decisions and reads == [1]


# -- provenance --------------------------------------------------------------------------------


def test_the_audit_inputs_hold_no_data_root_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.full_world(tmp_path, monkeypatch)
    inp = w3.gather(root)
    shown = repr(
        (inp.exec, inp.settlements, inp.stall_records, inp.notifier_proofs, inp.funnel, inp.epoch)
    )
    assert str(root) not in shown
    assert all("/" not in (b.log_name or "") for b in inp.boots)


def test_the_gather_modules_import_no_venue_adapter(tmp_path: Path) -> None:
    import ast

    for name in ("inputs", "host", "tape", "cache", "exec_view"):
        tree = ast.parse(Path(inputs.__file__).with_name(f"capture_audit_{name}.py").read_text())
        mods = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        assert not [m for m in mods if m.startswith("breezy.adapters")], name


def test_no_pickle_anywhere_in_the_cache() -> None:
    assert "import pickle" not in Path(cache.__file__).read_text()


# -- stream errors in legs (coordinator contract 3) --------------------------------------------


def test_a_stream_that_cannot_be_re_read_is_stream_unreadable_not_a_raw_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.full_world(tmp_path, monkeypatch)
    (boot,) = w3.gather(root).boots
    feather = next(capture_root(root, w3.VENUE).rglob("*.feather"))
    other = feather.with_name("elsewhere")
    other.write_bytes(feather.read_bytes())
    feather.unlink()
    feather.symlink_to(other)
    with pytest.raises(AuditInputError) as info:
        boot.stream()  # what leg B calls
    assert info.value.cause == "stream_unreadable"


def test_a_leg_that_re_reads_a_broken_stream_makes_the_day_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from breezy.analysis import capture_audit as audit
    from tests.support.capture_audit_w3_fixtures import stub_legs

    root = w3.full_world(tmp_path, monkeypatch)
    inp = w3.gather(root)
    shutil_target = next(capture_root(root, w3.VENUE).rglob("*.feather"))
    shutil_target.unlink()
    shutil_target.symlink_to("/nonexistent")
    stub_legs(monkeypatch)
    monkeypatch.setattr(audit, "audit_fills", lambda i: [b.stream() for b in i.boots] and ())
    result = audit.audit_day(inp)
    assert (result.status.value, result.cause) == ("ERROR", "stream_unreadable")


def test_row_count_table_names_are_the_catalog_table_names() -> None:
    from nautilus_trader.persistence.funcs import class_to_filename

    from breezy.domain.forecast_point import ForecastPoint
    from breezy.persistence.autonomy import capture_records as rec
    from breezy.persistence.autonomy.capture_reader import CaptureStream

    stream_counts = inputs._row_counts(CaptureStream(instance_id="i", source="live"))
    expected = {
        class_to_filename(c)
        for c in (
            rec.DecisionRecord,
            rec.FrameCopy,
            rec.OrderEventRecord,
            rec.DetectorEvent,
            rec.CaptureHeartbeat,
            ForecastPoint,
        )
    }
    assert expected <= set(stream_counts)
