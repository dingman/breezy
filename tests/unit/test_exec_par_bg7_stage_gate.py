"""EXEC-PAR BG-7: the read-only cross-check and stage report (``exec_par_stage_gate``)."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import pytest

from breezy.runtime.exec_par_records import (
    AmbiguousRow,
    EpochRow,
    ExcludedDay,
    OrderAnchor,
    RebuildRow,
    SettledPnlDay,
    StageEvalStamp,
    StageReportDoc,
    StageReset,
)
from breezy.runtime.health import AlertPayload
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import BREAKER_KEY, SubmitIntentLatch, open_submit_intent_latch
from scripts.analysis import exec_par_stage_gate as gate
from tests.unit.exec_par_days import UtcDays

NS = 1_000_000_000
BASE = dt.date(2026, 12, 1)


def d(i: int) -> str:
    return (BASE + dt.timedelta(days=i)).isoformat()


def ns_of(day: str) -> int:
    return int(dt.datetime.fromisoformat(day).replace(tzinfo=dt.UTC).timestamp()) * NS


FLOOR_TS = ns_of(d(0)) + 5
NOW = ns_of(d(3)) + 3_600 * NS


@dataclass
class _Sink:
    sent: list[AlertPayload] = field(default_factory=list)

    def emit(self, payload: AlertPayload) -> None:
        self.sent.append(payload)


def seed(tmp_path: Path, writer: Callable[[SubmitIntentLatch], None] | None = None) -> Path:
    db = tmp_path / "state.sqlite"
    with (
        SqliteStateStore(db) as store,
        open_submit_intent_latch(store, db, clock_ns=lambda: 777) as latch,
    ):
        if writer is not None:
            writer(latch)
    return db


def k2_stage(latch: SubmitIntentLatch) -> None:
    latch.write_epoch_row(EpochRow("sha-a", 2, None, FLOOR_TS))
    latch.write_stage_reset(StageReset(FLOOR_TS, "k_change", None))


def anchor(coid: str, day: str, arm_ns: int) -> OrderAnchor:
    return OrderAnchor(
        client_order_id=coid,
        slug="slug",
        day=day,
        arm_ns=arm_ns,
        decision_ask="0.40",
        qty="1",
        notional="0.40",
        window_start_ns=arm_ns - arm_ns % (60 * NS),
        attribution="event_time",
        station="LAX",
    )


def run(
    db: Path,
    out_dir: Path,
    *,
    sink: _Sink | None = None,
    now_ns: int = NOW,
    configured_k: int | None = None,
) -> gate.CrossCheckResult:
    return gate.run_cross_check(
        db_path=db,
        out_dir=out_dir,
        governed=UtcDays(),
        now_ns=now_ns,
        configured_k=configured_k,
        sink=sink if sink is not None else _Sink(),
    )


def doc_of(result: gate.CrossCheckResult, *, ts_ns: int = NOW - 3_600 * NS) -> StageReportDoc:
    return StageReportDoc(
        ts_ns=ts_ns,
        verdict=result.mine_verdict.lower(),
        reason=result.mine_reason,
        report_json=result.stage_report_json,
    )


# -- empty data and K=1 (K8) -----------------------------------------------


def test_empty_store_is_pass_pass_agreement_and_does_not_crash(tmp_path: Path) -> None:
    db = seed(tmp_path)
    sink = _Sink()
    result = run(db, tmp_path / "out", sink=sink)
    assert (result.mine_verdict, result.in_node_verdict) == ("PASS", "PASS")
    assert result.agreement == "AGREE"
    assert result.reasons == ()
    assert result.exit_code == 0
    assert sink.sent == []


def test_a_database_without_the_state_table_is_an_empty_store(tmp_path: Path) -> None:
    db = tmp_path / "bare.sqlite"
    sqlite3.connect(db).close()
    result = run(db, tmp_path / "out")
    assert result.agreement == "AGREE"
    assert result.exit_code == 0


def test_k1_epochs_without_an_in_node_report_agree_pass_pass(tmp_path: Path) -> None:
    db = seed(tmp_path, lambda latch: latch.write_epoch_row(EpochRow("sha", 1, None, 10)))
    result = run(db, tmp_path / "out")
    assert (result.mine_verdict, result.in_node_verdict, result.agreement) == (
        "PASS",
        "PASS",
        "AGREE",
    )


# -- agree and disagree ----------------------------------------------------


def test_agrees_when_the_in_node_report_matches_the_rebuilt_verdict(tmp_path: Path) -> None:
    first = run(seed(tmp_path, k2_stage), tmp_path / "o1")
    assert first.agreement == "DISAGREE"  # K=2 with no in-node report at all
    assert "in_node_report_missing" in first.reasons

    def with_report(latch: SubmitIntentLatch) -> None:
        k2_stage(latch)
        latch.write_stage_report(doc_of(first))
        latch.write_stage_eval_stamp(StageEvalStamp(NOW - 3_600 * NS, 777))

    other = tmp_path / "b"
    other.mkdir()
    sink = _Sink()
    result = run(seed(other, with_report), other / "out", sink=sink)
    assert result.agreement == "AGREE"
    assert result.reasons == ()
    assert result.exit_code == 0
    assert sink.sent == []


def test_disagrees_with_reasons_alerts_and_exits_non_zero_on_a_verdict_mismatch(
    tmp_path: Path,
) -> None:
    probe = run(seed(tmp_path, k2_stage), tmp_path / "o1")
    other = tmp_path / "b"
    other.mkdir()
    wrong = "stop" if probe.mine_verdict != "STOP" else "pass"

    def with_wrong_report(latch: SubmitIntentLatch) -> None:
        k2_stage(latch)
        latch.write_stage_report(
            StageReportDoc(NOW - 60 * NS, wrong, "s6_share", probe.stage_report_json)
        )

    sink = _Sink()
    result = run(seed(other, with_wrong_report), other / "out", sink=sink)
    assert result.agreement == "DISAGREE"
    assert result.exit_code == 1
    assert any(reason.startswith("verdict:") for reason in result.reasons)
    assert [p.event for p in sink.sent] == [gate.EVENT_DISAGREE]
    assert sink.sent[0].severity == "CRITICAL"


def test_disagrees_when_a_closed_day_stat_differs_from_the_in_node_report(
    tmp_path: Path,
) -> None:
    probe = run(seed(tmp_path, k2_stage), tmp_path / "o1")
    other = tmp_path / "b"
    other.mkdir()
    closed = d(1)

    def with_extra_anchor(latch: SubmitIntentLatch) -> None:
        k2_stage(latch)
        latch.write_order_anchor(anchor("coid-1", closed, ns_of(closed) + 99 * NS))
        latch.write_stage_report(doc_of(probe))
        latch.write_stage_eval_stamp(StageEvalStamp(NOW - 3_600 * NS, 777))

    result = run(seed(other, with_extra_anchor), other / "out")
    assert result.agreement == "DISAGREE"
    assert f"day_stats:{closed}" in result.reasons


def test_a_stale_in_node_report_disagrees(tmp_path: Path) -> None:
    probe = run(seed(tmp_path, k2_stage), tmp_path / "o1")
    other = tmp_path / "b"
    other.mkdir()

    def with_old_report(latch: SubmitIntentLatch) -> None:
        k2_stage(latch)
        latch.write_stage_report(doc_of(probe, ts_ns=NOW - 48 * 3_600 * NS))
        latch.write_stage_eval_stamp(StageEvalStamp(NOW - 48 * 3_600 * NS, 777))

    result = run(seed(other, with_old_report), other / "out")
    assert result.agreement == "DISAGREE"
    assert "in_node_report_stale" in result.reasons


def test_a_corrupt_row_becomes_a_fail_verdict_not_a_crash(tmp_path: Path) -> None:
    db = seed(tmp_path, k2_stage)
    with SqliteStateStore(db) as store:
        store.set("exec/polymarket_us/exec_par/stage_reset", b"not json")
    result = run(db, tmp_path / "out")
    assert result.mine_verdict == "FAIL"
    assert result.agreement == "DISAGREE"


# -- read-only proof ---------------------------------------------------------------------------


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_run_never_writes_the_store_including_the_breaker_key(tmp_path: Path) -> None:
    def seeded(latch: SubmitIntentLatch) -> None:
        k2_stage(latch)
        latch.write_stage_report(StageReportDoc(NOW - 60 * NS, "pass", None, None))

    db = seed(tmp_path, seeded)
    with SqliteStateStore(db) as store:
        store.set(BREAKER_KEY, b'{"sentinel":1}')
    before = _digest(db)
    run(db, tmp_path / "out")
    assert _digest(db) == before
    with SqliteStateStore(db) as store:
        assert store.get(BREAKER_KEY) == b'{"sentinel":1}'
    assert not Path(str(db) + "-wal").exists() or Path(str(db) + "-wal").stat().st_size == 0


def test_reads_a_live_wal_store_while_the_node_still_holds_it_open(tmp_path: Path) -> None:
    db = tmp_path / "state.sqlite"
    with (
        SqliteStateStore(db) as store,
        open_submit_intent_latch(store, db, clock_ns=lambda: 777) as latch,
    ):
        k2_stage(latch)  # committed to the WAL; the writer connection stays open
        assert Path(str(db) + "-wal").exists()
        result = run(db, tmp_path / "out")
        latch.write_epoch_row(EpochRow("sha-b", 2, None, FLOOR_TS + 1))  # node still writes
    assert result.epochs_path is not None
    assert [json.loads(x)["commit_sha"] for x in result.epochs_path.read_text().splitlines()] == [
        "sha-a"
    ]


def test_every_connection_is_mode_ro_and_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = seed(tmp_path, k2_stage)
    real = sqlite3.connect
    opened: list[tuple[str, bool, sqlite3.Connection]] = []

    def spy(database: str, *args: object, **kwargs: object) -> sqlite3.Connection:
        conn: sqlite3.Connection = real(database, *args, **kwargs)  # type: ignore[call-overload]
        opened.append((str(database), bool(kwargs.get("uri")), conn))
        return conn

    monkeypatch.setattr(sqlite3, "connect", spy)
    run(db, tmp_path / "out")
    assert opened, "the run opened no connection at all"
    for target, uri, conn in opened:
        assert uri is True and "mode=ro" in target and target.startswith("file:")
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")  # closed


def test_the_reader_exposes_no_write_surface_and_the_connection_rejects_writes(
    tmp_path: Path,
) -> None:
    db = seed(tmp_path, k2_stage)
    with gate.ReadOnlyState(db) as store:
        assert not hasattr(store, "set")
        assert not hasattr(store, "delete")
        with pytest.raises(sqlite3.OperationalError):
            store.connection.execute("INSERT INTO state (key, value) VALUES ('k', x'00')")


# -- the report ------------------------------------------------------------


def test_the_report_has_every_section(tmp_path: Path) -> None:
    pre_day, floor_day = d(-2), d(0)

    def rich(latch: SubmitIntentLatch) -> None:
        k2_stage(latch)
        latch.add_excluded_day(ExcludedDay(d(1), "spend_unaudited", NOW - 5))
        latch.write_rebuild_row(RebuildRow(d(2), 50, "fills,posted", 3, 1, 2, "9.99"))
        latch.write_rebuild_row(RebuildRow(d(1), 40, "ambiguous", 1, 1, 0, "1"))
        latch.retire_rebuild_row(d(1))
        latch.write_ambiguous(
            AmbiguousRow("intent-1", "slot", d(1), ns_of(d(1)) + 9 * NS, "slot", NOW - 9, "LAX")
        )
        latch.write_settled_pnl_day(SettledPnlDay(pre_day, "-3.5", 4, 1, 0))
        latch.write_settled_pnl_day(SettledPnlDay(floor_day, "-1", 3, 0, 0))
        latch.write_floor_stub_pnl_day(SettledPnlDay(floor_day, "-0.25", 1, 0, 0))

    out = tmp_path / "out"
    result = run(seed(tmp_path, rich), out)
    report = json.loads((out / gate.REPORT_NAME).read_text())
    for section in (
        "verdict_compare",
        "rebuilt_days",
        "excluded_days",
        "pre_reset_armed_settlements",
        "per_day_ambiguous",
        "looks",
        "holds",
        "spend_deferrals",
        "stage",
    ):
        assert section in report, section
    assert report["verdict_compare"]["agreement"] == result.agreement
    rebuilt = {(r["day"], r["status"]) for r in report["rebuilt_days"]}
    assert rebuilt == {(d(2), "pending"), (d(1), "retired")}
    assert report["excluded_days"] == [{"day": d(1), "cause": "spend_unaudited", "ts": NOW - 5}]
    pre = {r["day"]: r for r in report["pre_reset_armed_settlements"]}
    assert pre[pre_day]["settled_entries"] == 4 and pre[pre_day]["ambiguous_entries"] == 1
    assert pre[floor_day]["pre_floor_entries"] == 2
    ambiguous = {r["day"]: r["ambiguous"] for r in report["per_day_ambiguous"]}
    assert ambiguous[d(1)] == 1
    deferral = report["spend_deferrals"]
    assert deferral["cache_audit_available"] is False
    assert deferral["excluded_with_audit_cause"] == [d(1)]
    text = json.dumps(report)
    assert "9.99" not in text and "-3.5" not in text  # no currency amounts in the report


def test_the_report_is_written_atomically_beside_the_epochs_export(tmp_path: Path) -> None:
    out = tmp_path / "out"
    run(seed(tmp_path, k2_stage), out)
    assert sorted(p.name for p in out.iterdir()) == [gate.EPOCHS_NAME, gate.REPORT_NAME]


# -- k_epochs.jsonl --------------------------------------------------------


def test_k_epochs_export_has_one_sorted_line_per_epoch_row(tmp_path: Path) -> None:
    def epochs(latch: SubmitIntentLatch) -> None:
        latch.write_epoch_row(EpochRow("sha-b", 2, "supervisor_marker", 2_000))
        latch.write_epoch_row(EpochRow("sha-a", 1, None, 1_000, 1_500))

    out = tmp_path / "out"
    run(seed(tmp_path, epochs), out)
    lines = (out / gate.EPOCHS_NAME).read_text().splitlines()
    rows = [json.loads(line) for line in lines]
    assert [r["boot_ts"] for r in rows] == [1_000, 2_000]
    assert rows[0] == {
        "boot_ts": 1_000,
        "commit_sha": "sha-a",
        "effective_k": 1,
        "force_reason": None,
        "stop_ts": 1_500,
    }
    assert lines[0] == json.dumps(rows[0], sort_keys=True)


def test_empty_epochs_export_is_an_empty_file(tmp_path: Path) -> None:
    out = tmp_path / "out"
    run(seed(tmp_path), out)
    assert (out / gate.EPOCHS_NAME).read_text() == ""


def test_atomic_write_replaces_whole_or_not_at_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "k_epochs.jsonl"
    target.write_text("old\n")
    replaced: list[tuple[str, str]] = []
    real_replace = os.replace

    def spy(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        replaced.append((str(src), str(dst)))
        assert Path(src).read_text() == "new\n"  # complete before it becomes visible
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    gate.atomic_write_text(target, "new\n")
    assert replaced and replaced[0][1] == str(target)
    assert Path(replaced[0][0]).parent == target.parent
    assert target.read_text() == "new\n"
    assert [p.name for p in tmp_path.iterdir()] == ["k_epochs.jsonl"]


def test_a_failed_replace_keeps_the_old_file_and_leaves_no_tmp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "k_epochs.jsonl"
    target.write_text("old\n")

    def boom(src: object, dst: object) -> None:
        raise OSError("disk")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        gate.atomic_write_text(target, "new\n")
    assert target.read_text() == "old\n"
    assert [p.name for p in tmp_path.iterdir()] == ["k_epochs.jsonl"]


# -- CLI -------------------------------------------------------------------


def test_main_returns_two_and_alerts_when_the_store_cannot_be_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = _Sink()
    monkeypatch.setattr(gate, "resolve_alert_sink", lambda *a, **k: sink)
    code = gate.main(
        [
            "--db",
            str(tmp_path / "missing.sqlite"),
            "--out-dir",
            str(tmp_path / "out"),
            "--stations",
            "LAX",
        ]
    )
    assert code == 2
    assert [p.event for p in sink.sent] == [gate.EVENT_ERROR]


def test_main_on_an_empty_store_exits_zero(tmp_path: Path) -> None:
    db = seed(tmp_path)
    code = gate.main(["--db", str(db), "--out-dir", str(tmp_path / "out"), "--stations", "LAX"])
    assert code == 0
    assert (tmp_path / "out" / gate.REPORT_NAME).is_file()


def test_help_exits_zero() -> None:
    with pytest.raises(SystemExit) as raised:
        gate.main(["--help"])
    assert raised.value.code == 0


# -- import boundaries -----------------------------------------------------


def test_script_source_stays_off_the_network_and_asdict() -> None:
    source = Path(gate.__file__).read_text()
    for banned in ("urllib", "socket", "httpx", "asdict"):
        assert banned not in source, banned


def test_nothing_under_src_reads_the_export_or_imports_the_script() -> None:
    src = Path(__file__).resolve().parents[2] / "src"
    for path in src.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "k_epochs.jsonl" not in text, path
        assert "exec_par_stage_gate" not in text, path


# -- rulings: s15 not evaluated, cheap import, stations from the node's source, limitations ----


def _with_in_node(
    tmp_path: Path, name: str, probe: gate.CrossCheckResult, verdict: str, reason: str | None
) -> Path:
    sub = tmp_path / name
    sub.mkdir()

    def writer(latch: SubmitIntentLatch) -> None:
        k2_stage(latch)
        latch.write_stage_report(
            StageReportDoc(NOW - 60 * NS, verdict, reason, probe.stage_report_json)
        )
        latch.write_stage_eval_stamp(StageEvalStamp(NOW - 60 * NS, 777))

    return seed(sub, writer)


def test_the_script_never_touches_the_spend_ledger_or_operator_caps() -> None:
    source = Path(gate.__file__).read_text()
    for banned in ("operator_controls", "DailySpendLedger", "MAX_DAILY_BUDGET"):
        assert banned not in source, banned


def test_the_predicate_port_reports_not_evaluated_and_never_trips() -> None:
    port = gate.NotEvaluatedPredicates()
    assert port.evaluated is False
    assert (
        port.pnl_breaches_budget_fraction(aggregate_pnl=Decimal(-1000000), fraction=Decimal("0.15"))
        is False
    )
    assert port.evaluated is True


def test_an_in_node_s15_stop_is_agree_except_s15_not_evaluated(tmp_path: Path) -> None:
    db = _with_in_node(tmp_path, "s", gate_probe(tmp_path), "stop", "s15_day")
    sink = _Sink()
    result = run(db, tmp_path / "out", sink=sink)
    assert result.agreement == "AGREE_EXCEPT_S15_NOT_EVALUATED"
    assert result.exit_code == 0
    assert sink.sent == []
    report = json.loads((tmp_path / "out" / gate.REPORT_NAME).read_text())
    assert report["s15"] == {
        "status": "not_evaluated",
        "in_node_only": {"verdict": "stop", "reason": "s15_day", "is_s15_stop": True},
    }


def gate_probe(tmp_path: Path) -> gate.CrossCheckResult:
    sub = tmp_path / "probe"
    sub.mkdir(exist_ok=True)
    return run(seed(sub, k2_stage), sub / "o")


def test_an_in_node_s15_stop_with_a_closed_day_mismatch_still_disagrees(tmp_path: Path) -> None:
    probe = gate_probe(tmp_path)
    sub = tmp_path / "m"
    sub.mkdir()
    closed = d(1)

    def writer(latch: SubmitIntentLatch) -> None:
        k2_stage(latch)
        latch.write_order_anchor(anchor("coid-9", closed, ns_of(closed) + 99 * NS))
        latch.write_stage_report(
            StageReportDoc(NOW - 60 * NS, "stop", "s15_stage", probe.stage_report_json)
        )
        latch.write_stage_eval_stamp(StageEvalStamp(NOW - 60 * NS, 777))

    result = run(seed(sub, writer), sub / "out")
    assert result.agreement == "DISAGREE"
    assert f"day_stats:{closed}" in result.reasons


def test_an_in_node_non_s15_stop_is_a_disagreement(tmp_path: Path) -> None:
    probe = gate_probe(tmp_path)
    db = _with_in_node(tmp_path, "n", probe, "stop", "s6_dropped_share")
    result = run(db, tmp_path / "out")
    assert result.agreement == "DISAGREE"
    assert any(r.startswith("verdict:") for r in result.reasons)


def test_an_in_node_pass_agrees_and_the_s15_section_echoes_it(tmp_path: Path) -> None:
    probe = gate_probe(tmp_path)
    db = _with_in_node(tmp_path, "a", probe, "pass", None)
    result = run(db, tmp_path / "out")
    assert result.agreement == "AGREE"
    report = json.loads((tmp_path / "out" / gate.REPORT_NAME).read_text())
    assert report["s15"]["status"] == "not_evaluated"
    assert report["s15"]["in_node_only"] == {
        "verdict": "pass",
        "reason": None,
        "is_s15_stop": False,
    }


def test_importing_the_script_loads_no_breezy_or_network_module() -> None:
    root = Path(__file__).resolve().parents[2]
    code = (
        "import sys; import scripts.analysis.exec_par_stage_gate; "
        "bad = sorted(m for m in sys.modules if m.split('.')[0] in "
        "('breezy', 'httpx', 'nautilus_trader', 'pyarrow')); print(bad)"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        cwd=root,
        env={**os.environ, "PYTHONPATH": f"{root / 'src'}{os.pathsep}{root}"},
    )
    assert out.stdout.strip() == "[]", out.stdout


def test_stations_come_from_the_family_manifest_in_supported_order() -> None:
    from breezy.persistence.family_manifest import load_family_manifest
    from breezy.strategy.current_rung_hold.config import SUPPORTED_STATIONS

    root = Path(__file__).resolve().parents[2]
    manifest = load_family_manifest(root / "deploy/families/pm_us_crh_fq_v1.json")
    expected = tuple(x for x in SUPPORTED_STATIONS if x in set(manifest.stations))
    assert gate.resolve_stations("pm_us_crh_fq_v1", root / "deploy/families") == expected


def test_an_unknown_family_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        gate.resolve_stations("no_such_family", tmp_path)


def test_no_station_literal_is_hardcoded_in_the_script() -> None:
    source = Path(gate.__file__).read_text()
    for station in ("LAX", "MDW", "MIA", "SFO"):
        assert station not in source, station


def test_main_resolves_stations_from_a_family_id(tmp_path: Path) -> None:
    db = seed(tmp_path)
    code = gate.main(
        ["--db", str(db), "--out-dir", str(tmp_path / "out"), "--family-id", "pm_us_crh_fq_v1"]
    )
    assert code == 0


def test_main_without_stations_or_family_exits_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BREEZY_SENDING_FAMILY_ID", raising=False)
    monkeypatch.setattr(gate, "resolve_alert_sink", lambda *a, **k: _Sink())
    db = seed(tmp_path)
    assert gate.main(["--db", str(db), "--out-dir", str(tmp_path / "out")]) == 2


def test_the_report_states_its_limitations(tmp_path: Path) -> None:
    out = tmp_path / "out"
    run(seed(tmp_path), out)
    limitations = json.loads((out / gate.REPORT_NAME).read_text())["limitations"]
    joined = " ".join(limitations)
    assert "spend" in joined and "audit" in joined
    assert "settlement" in joined and "pre-reset" in joined
    assert "s15" in joined
