"""AUT-1 WP5 stage 2b W3: the audit's orchestration (plan r12 sections 3.11.4-3.11.6; S2-R6/R9/R12).

The legs belong to W1 and W2 (other worktrees), so every test here stubs them through
``stub_legs`` and drives the REAL status table, scheduling, file writer, verdict writer, delivery
seam, moved duties and entry point. Files are real, under ``tmp_path``.
"""

import dataclasses
import datetime as dt
import json
import logging
import os
import stat
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from breezy.analysis import capture_audit as audit
from breezy.analysis import capture_audit_cli as cli
from breezy.analysis import capture_audit_host as host
from breezy.analysis import capture_audit_inputs as inputs
from breezy.analysis.capture_audit_input_types import (
    ExecFill,
    ExecView,
    RecorderProps,
    ReplayResult,
)
from breezy.analysis.capture_audit_model import (
    AUDIT_WORK_BUDGET_S,
    METRIC_NAMES,
    AuditInputError,
    AuditResult,
    DayStatus,
    FillAudit,
    Leg,
    LegResult,
    WatchdogGap,
)
from breezy.analysis.capture_audit_wire import audit_from_wire
from breezy.analysis.capture_node_log import scan_node_log
from breezy.analysis.capture_settlement import SettlementRecord
from breezy.persistence.autonomy import pins
from breezy.persistence.autonomy.capture_epoch import EpochRecord, write_epoch_once
from breezy.persistence.autonomy.verdict import VerdictRefusalReason, VerdictRefused
from tests.support import capture_audit_fixtures as fx
from tests.support import capture_audit_w3_fixtures as w3
from tests.support.capture_audit_w3_fixtures import leg_result, stub_legs

DAY = fx.DAY
NS = w3.NS
TODAY = DAY + dt.timedelta(days=1)


def _fill_audit(*, legs: Sequence[LegResult] = (), drill: bool = False) -> FillAudit:
    return FillAudit(
        client_order_id="O-20261003-165052-L001-LAX-1",
        trade_id="CVWEANWH8YHR",
        family_id=fx.FAMILY_ID,
        source="live",
        drill=drill,
        attributed=True,
        legs=tuple(legs),
    )


def _status(monkeypatch: pytest.MonkeyPatch, inp: Any = None, **kw: Any) -> AuditResult:
    stub_legs(monkeypatch, **kw)
    return audit.audit_day(inp if inp is not None else fx.make_inputs())


# -- the status table (S2-R9) ------------------------------------------------------------------


def test_complete_day_passes_final(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _status(monkeypatch, fills=(_fill_audit(legs=(leg_result("L"), leg_result("D"))),))
    assert (result.status, result.cause) == (DayStatus.PASS, "")
    assert result.metrics["day_status"] == "PASS"
    assert result.metrics["fills_total"] == 1 and result.metrics["fills_joined"] == 1


def test_every_metric_the_audit_writes_is_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _status(monkeypatch, fills=(_fill_audit(legs=(leg_result("L"),)),))
    assert set(result.metrics) <= METRIC_NAMES
    assert {f"leg_{leg.value}_pass" for leg in Leg} <= set(result.metrics)
    assert all(result.metrics[f"leg_{leg}_pass"] == 1 for leg in ("R1", "R2", "L", "S"))


def test_a_failing_day_leg_fails_the_day_with_its_cause(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _status(monkeypatch, R1=leg_result("R1", "FAIL", "capture_missing"))
    assert (result.status, result.cause) == (DayStatus.FAIL, "R1:capture_missing")
    assert result.metrics["leg_R1_pass"] == 0


def test_a_failing_fill_leg_fails_the_day(monkeypatch: pytest.MonkeyPatch) -> None:
    fill = _fill_audit(legs=(leg_result("L", "FAIL", "link_conflict"),))
    result = _status(monkeypatch, fills=(fill,))
    assert result.status is DayStatus.FAIL and result.cause == "L:link_conflict"
    assert result.metrics["fills_joined"] == 0 and result.metrics["leg_L_pass"] == 0


def test_r6_reports_but_never_fails_the_day(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _status(monkeypatch, R6=leg_result("R6", "FAIL", "refs_unresolved"))
    assert result.status is DayStatus.PASS and result.metrics["leg_R6_pass"] == 0


def test_a_pending_leg_is_inconclusive(monkeypatch: pytest.MonkeyPatch) -> None:
    fill = _fill_audit(legs=(leg_result("S", "PENDING", "settlement_pending"),))
    result = _status(monkeypatch, fills=(fill,))
    assert (result.status, result.cause) == (DayStatus.INCONCLUSIVE, "settlement_pending")


def test_a_fail_beats_a_pending_leg(monkeypatch: pytest.MonkeyPatch) -> None:
    fill = _fill_audit(legs=(leg_result("S", "PENDING"),))
    result = _status(monkeypatch, fills=(fill,), O=leg_result("O", "FAIL", "trysubmit_unlinked"))
    assert result.status is DayStatus.FAIL


def test_no_input_day_has_no_fills_resolvers_or_takes(monkeypatch: pytest.MonkeyPatch) -> None:
    inp = fx.make_inputs(exec=ExecView(), boots=(fx.make_boot(replay=ReplayResult()),))
    assert _status(monkeypatch, inp).status is DayStatus.NO_INPUT


@pytest.mark.parametrize(
    "inp_over",
    [
        pytest.param({"boots": (fx.make_boot(),)}, id="take_line"),
        pytest.param({"exec": fx.make_exec_view()}, id="resolver_context"),
    ],
)
def test_a_take_line_or_resolver_context_is_input(
    monkeypatch: pytest.MonkeyPatch, inp_over: dict[str, Any]
) -> None:
    base: dict[str, Any] = {"exec": ExecView(), "boots": (fx.make_boot(replay=ReplayResult()),)}
    base.update(inp_over)
    assert _status(monkeypatch, fx.make_inputs(**base)).status is DayStatus.PASS


def test_days_before_epoch_are_pre_capture_and_epoch_day_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = w3.day_ns(DAY, 16, 50)
    epoch = EpochRecord(fx.FAMILY_ID, start, fx.INSTANCE_ID, "0" * 40)
    before = _status(
        monkeypatch,
        fx.make_inputs(epoch=dataclasses.replace(epoch, epoch_start_ns=start + 86_400 * NS)),
    )
    same = _status(monkeypatch, fx.make_inputs(epoch=epoch))
    assert before.status is DayStatus.PRE_CAPTURE and same.status is DayStatus.PARTIAL_EPOCH


def test_no_epoch_at_all_is_pre_capture(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _status(monkeypatch, fx.make_inputs(epoch=None)).status is DayStatus.PRE_CAPTURE


def test_pre_capture_masks_a_failing_leg(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _status(monkeypatch, fx.make_inputs(epoch=None), R1=leg_result("R1", "FAIL", "x"))
    assert result.status is DayStatus.PRE_CAPTURE and result.cause == ""


def test_an_integrity_error_beats_pre_capture(monkeypatch: pytest.MonkeyPatch) -> None:
    """MUTATION: precedence order. PRE_CAPTURE must not hide a node-log, exec or journal error."""
    for cause in ("node_log_missing", "journal_failed", "exec_snapshot_failed", "epoch_rewritten"):
        result = _status(
            monkeypatch, fx.make_inputs(epoch=None), PC=leg_result("PC", "ERROR", cause)
        )
        assert (result.status, result.cause) == (DayStatus.ERROR, cause)


def test_pre_capture_beats_a_host_state_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """MUTATION: precedence order. A day before the epoch is not made ERROR by the host's state."""
    unarmed = RecorderProps(watchdog_usec=0, notify_access="all", type="notify")
    result = _status(monkeypatch, fx.make_inputs(epoch=None, recorder_props=unarmed))
    assert result.status is DayStatus.PRE_CAPTURE


def test_a_host_state_error_beats_fail_and_partial_epoch(monkeypatch: pytest.MonkeyPatch) -> None:
    unarmed = RecorderProps(watchdog_usec=0, notify_access="all", type="notify")
    result = _status(
        monkeypatch, fx.make_inputs(recorder_props=unarmed), R1=leg_result("R1", "FAIL")
    )
    assert (result.status, result.cause) == (DayStatus.ERROR, "recorder_watchdog_unarmed")


@pytest.mark.parametrize(
    "props",
    [
        RecorderProps(0, "all", "notify"),
        RecorderProps(600_000_000, "main", "notify"),
        RecorderProps(600_000_000, "all", "simple"),
    ],
    ids=["watchdog_usec_0", "notify_access_main", "type_simple"],
)
def test_recorder_watchdog_unarmed_is_error(
    monkeypatch: pytest.MonkeyPatch, props: RecorderProps
) -> None:
    result = _status(monkeypatch, fx.make_inputs(recorder_props=props))
    assert (result.status, result.cause) == (DayStatus.ERROR, "recorder_watchdog_unarmed")


def test_a_leg_that_cannot_read_its_input_makes_the_day_error_not_a_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_legs(monkeypatch)

    def broken(inp: Any) -> LegResult:
        raise AuditInputError("tape_unreadable", "OSError")

    monkeypatch.setattr(audit, "leg_t", broken)
    result = audit.audit_day(fx.make_inputs())
    assert (result.status, result.cause) == (DayStatus.ERROR, "tape_unreadable")


def test_fail_beats_partial_epoch_and_partial_epoch_beats_inconclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = w3.day_ns(DAY, 16, 50)
    inp = fx.make_inputs(epoch=EpochRecord(fx.FAMILY_ID, start, fx.INSTANCE_ID, "0" * 40))
    fill = _fill_audit(legs=(leg_result("S", "PENDING"),))
    assert _status(monkeypatch, inp, fills=(fill,)).status is DayStatus.PARTIAL_EPOCH
    assert _status(monkeypatch, inp, R1=leg_result("R1", "FAIL")).status is DayStatus.FAIL


def test_watchdog_gaps_and_duplicates_and_marks_are_carried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gap = WatchdogGap("breezy-quote-tape.service", "ab" * 16, 5, "watchdog_evidence_gap")
    boot = fx.make_boot(replay=ReplayResult(admitted_by_kind={"Take": 1}, duplicate_lines=3))
    result = _status(
        monkeypatch, fx.make_inputs(boots=(boot,)), gaps=(gap,), W=leg_result("W", "FAIL", "gap")
    )
    assert result.watchdog_evidence_gaps == (gap,) and result.duplicate_decision_lines == 3
    assert result.metrics["watchdog_kills_unproven"] == 1 and result.status is DayStatus.FAIL


def test_leg_metrics_are_lifted_only_when_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _status(
        monkeypatch,
        R5=leg_result("R5", records_lost_in_flush_window=4, private_counter=9),
        R6=leg_result("R6", refusal_frame_ref_resolved_frac=0.95),
    )
    assert result.metrics["records_lost_in_flush_window"] == 4
    assert result.metrics["refusal_frame_ref_resolved_frac"] == 0.95
    assert "private_counter" not in result.metrics


def test_drill_fills_are_marked_in_the_audit_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _status(monkeypatch, fills=(_fill_audit(drill=True),))
    audit.write_audit_file(w3.make_root(tmp_path), result, ts_ns=1)
    (written,) = (tmp_path / "data" / "evidence" / "capture" / "audit" / fx.FAMILY_ID).glob(
        "*.json"
    )
    assert json.loads(written.read_text())["fills"][0]["drill"] is True


# -- scheduling --------------------------------------------------------------------------------


def _days(*offsets: int) -> tuple[dt.date, ...]:
    return tuple(TODAY - dt.timedelta(days=o) for o in offsets)


def test_a_run_audits_yesterday_then_inconclusive_then_the_backfill_oldest_first() -> None:
    audited = {
        TODAY - dt.timedelta(days=3): DayStatus.INCONCLUSIVE,
        TODAY - dt.timedelta(days=2): DayStatus.PASS,
        TODAY - dt.timedelta(days=5): DayStatus.INCONCLUSIVE,
    }
    assert audit.days_to_audit(TODAY, audited) == _days(1, 5, 3, 8, 7, 6, 4)


def test_audit_backfills_days_without_audit_file_within_8() -> None:
    order = audit.days_to_audit(TODAY, {})
    assert order[0] == TODAY - dt.timedelta(days=1)
    assert order[1:] == _days(8, 7, 6, 5, 4, 3, 2) and len(set(order)) == 8
    assert TODAY - dt.timedelta(days=9) not in order and TODAY not in order


def test_yesterday_is_audited_once_even_when_it_is_inconclusive() -> None:
    order = audit.days_to_audit(TODAY, {TODAY - dt.timedelta(days=1): DayStatus.INCONCLUSIVE})
    assert order.count(TODAY - dt.timedelta(days=1)) == 1


def test_a_settled_or_failed_day_is_not_re_audited() -> None:
    audited = {d: DayStatus.PASS for d in _days(2, 3, 4, 5, 6, 7, 8)}
    assert audit.days_to_audit(TODAY, audited) == _days(1)
    audited = {d: DayStatus.FAIL for d in _days(2, 3, 4, 5, 6, 7, 8)}
    assert audit.days_to_audit(TODAY, audited) == _days(1)


# -- the audit file ----------------------------------------------------------------------------


def _audit_dir(root: Path) -> Path:
    return root / "evidence" / "capture" / "audit" / fx.FAMILY_ID


def test_the_audit_file_is_write_once_0444_and_round_trips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.make_root(tmp_path)
    result = _status(monkeypatch, fills=(_fill_audit(legs=(leg_result("L"),)),))
    audit.write_audit_file(root, result, ts_ns=111)
    path = _audit_dir(root) / f"{DAY.isoformat()}.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o444
    assert audit_from_wire(json.loads(path.read_text())) == result
    audit.write_audit_file(root, result, ts_ns=222)  # the same bytes: nothing new
    assert [p.name for p in _audit_dir(root).iterdir()] == [path.name]


def test_a_re_audit_writes_a_ts_named_file_and_never_replaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.make_root(tmp_path)
    first = _status(monkeypatch, fills=(_fill_audit(legs=(leg_result("S", "PENDING"),)),))
    second = _status(monkeypatch)
    audit.write_audit_file(root, first, ts_ns=111)
    audit.write_audit_file(root, second, ts_ns=222)
    names = sorted(p.name for p in _audit_dir(root).iterdir())
    assert names == [f"{DAY.isoformat()}.json", f"{DAY.isoformat()}_222.json"]
    original = json.loads((_audit_dir(root) / names[0]).read_text())
    assert original["status"] == "INCONCLUSIVE"  # the first file is untouched
    assert audit._audited_statuses(root, fx.FAMILY_ID) == {DAY: DayStatus.PASS}  # newest wins


def test_audit_evidence_has_no_absolute_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.make_root(tmp_path)
    audit.write_audit_file(root, _status(monkeypatch), ts_ns=1)
    text = (_audit_dir(root) / f"{DAY.isoformat()}.json").read_text()
    assert str(tmp_path) not in text and "/home/" not in text


def test_an_unreadable_audit_file_counts_as_no_audit(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    root = w3.make_root(tmp_path)
    _audit_dir(root).mkdir(parents=True)
    (_audit_dir(root) / f"{DAY.isoformat()}.json").write_text("{not json")
    with caplog.at_level(logging.WARNING):
        assert audit._audited_statuses(root, fx.FAMILY_ID) == {}
    assert "unreadable audit file" in caplog.text


def test_the_audit_dir_is_the_pinned_relative_path() -> None:
    from breezy.analysis.capture_audit_model import AUDIT_DIR_REL

    assert AUDIT_DIR_REL == "evidence/capture/audit"


# -- the run: ordering, errors, deadline, exit code --------------------------------------------


class Offers:
    def __init__(self, *, accept: bool = True, raises: bool = False) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.accept, self.raises = accept, raises

    def __call__(self, event: str, severity: str, detail: str) -> bool:
        self.calls.append((event, severity, detail))
        if self.raises:
            raise RuntimeError("outbox down")
        return self.accept

    @property
    def events(self) -> list[str]:
        return [c[0] for c in self.calls]


def _fake_gather(monkeypatch: pytest.MonkeyPatch, **per_day: Any) -> list[dt.date]:
    """``gather_inputs`` is replaced by one that returns fixture inputs (or raises the given
    exception for a day). Returns the list of days it was asked for."""
    asked: list[dt.date] = []

    def gather(root: Path, family: str, day: dt.date, *, now_ns: int) -> Any:
        asked.append(day)
        planted = per_day.get(day.isoformat())
        if isinstance(planted, Exception):
            raise planted
        return fx.make_inputs(day=day, **(planted or {}))

    monkeypatch.setattr(audit, "gather_inputs", gather)
    monkeypatch.setattr(audit, "_pre_capture", lambda root, family, day: False)
    return asked


def _run(root: Path, offer: Offers, *, today: dt.date = TODAY) -> int:
    return audit.run_audit(root, fx.FAMILY_ID, today, now_ns=w3.NOW_NS, offer=offer)


def _quiet_duties(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("_check_settlements", "_check_stuck", "_check_live_proof"):
        monkeypatch.setattr(audit, name, lambda *a, **k: None)


def test_a_pass_day_run_audits_the_window_writes_files_and_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.make_root(tmp_path)
    stub_legs(monkeypatch)
    _quiet_duties(monkeypatch)
    asked = _fake_gather(monkeypatch)
    offers = Offers()
    assert _run(root, offers) == 0
    assert asked == list(audit.days_to_audit(TODAY, {}))
    assert len(list(_audit_dir(root).iterdir())) == 8 and offers.calls == []


def test_a_second_run_audits_only_yesterday(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.make_root(tmp_path)
    stub_legs(monkeypatch)
    _quiet_duties(monkeypatch)
    asked = _fake_gather(monkeypatch)
    _run(root, Offers())
    asked.clear()
    _run(root, Offers())
    assert asked == [DAY]


def test_error_writes_audit_file_and_verdict_before_exit_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.make_root(tmp_path)
    stub_legs(monkeypatch)
    _quiet_duties(monkeypatch)
    _fake_gather(monkeypatch, **{DAY.isoformat(): AuditInputError("node_log_missing", "x")})
    verdicts: list[AuditResult] = []
    offers = Offers()
    audit_files_at_verdict: list[int] = []

    def note_verdict(r: Path, res: AuditResult, n: int) -> None:
        audit_files_at_verdict.append(len(list(_audit_dir(r).iterdir())))
        verdicts.append(res)

    monkeypatch.setattr(
        audit,
        "_write_health_verdict",
        note_verdict,
    )
    assert _run(root, offers) == 1
    (errored,) = [r for r in verdicts if r.status is DayStatus.ERROR]
    assert (errored.day, errored.cause) == (DAY, "node_log_missing")
    assert audit_files_at_verdict[0] >= 1  # the audit file precedes its verdict
    assert (_audit_dir(root) / f"{DAY.isoformat()}.json").exists()


def test_error_sends_capture_audit_error_through_deliver_with_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.make_root(tmp_path)
    stub_legs(monkeypatch)
    _quiet_duties(monkeypatch)
    _fake_gather(monkeypatch, **{DAY.isoformat(): AuditInputError("journal_failed", "exit_1")})
    offers = Offers()
    _run(root, offers)
    assert offers.calls == [
        ("CAPTURE_AUDIT_ERROR", "CRITICAL", f"day={DAY} family={fx.FAMILY_ID} cause=journal_failed")
    ]


def test_fail_sends_critical_through_deliver_with_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.make_root(tmp_path)
    stub_legs(monkeypatch, R1=leg_result("R1", "FAIL", "capture_missing"))
    _quiet_duties(monkeypatch)
    _fake_gather(monkeypatch)
    offers = Offers()
    code = _run(root, offers, today=TODAY)
    assert "CAPTURE_JOIN_GAP" in offers.events and all(c[1] == "CRITICAL" for c in offers.calls)
    detail = next(c[2] for c in offers.calls if c[0] == "CAPTURE_JOIN_GAP")
    assert "legs=R1" in detail and code == 0  # a FAIL day alone is not an exit-1 condition


def test_tape_nbp_and_refusal_ref_failures_have_their_own_alerts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.make_root(tmp_path)
    stub_legs(
        monkeypatch,
        T=leg_result("T", "FAIL", "tape_flat_root"),
        N=leg_result("N", "FAIL", "nbp_cycle_missing"),
        R6=leg_result("R6", "FAIL", "refs_unresolved"),
    )
    _quiet_duties(monkeypatch)
    _fake_gather(monkeypatch)
    offers = Offers()
    _run(root, offers)
    assert set(offers.events) == {
        "CAPTURE_TAPE_INGEST",
        "CAPTURE_NBP_CENSUS",
        "CAPTURE_REFUSAL_REFS_UNRESOLVED",
    }


def test_a_failed_delivery_exits_one_only_after_every_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.make_root(tmp_path)
    stub_legs(monkeypatch, R1=leg_result("R1", "FAIL", "capture_missing"))
    _quiet_duties(monkeypatch)
    _fake_gather(monkeypatch)
    for offer in (Offers(accept=False), Offers(raises=True)):
        assert _run(root, offer) == 1
    assert len(list(_audit_dir(root).iterdir())) >= 8  # every day was written before the exit


def test_pre_capture_and_inconclusive_days_send_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.make_root(tmp_path)
    fill = _fill_audit(legs=(leg_result("S", "PENDING"),))
    stub_legs(monkeypatch, fills=(fill,), R1=leg_result("R1", "FAIL", "x"))
    _quiet_duties(monkeypatch)
    _fake_gather(
        monkeypatch, **{d.isoformat(): {"epoch": None} for d in audit.days_to_audit(TODAY, {})}
    )
    offers = Offers()
    assert _run(root, offers) == 0 and offers.calls == []


def test_a_bus_error_on_a_pre_capture_day_is_masked_and_otherwise_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.make_root(tmp_path)
    stub_legs(monkeypatch)
    _quiet_duties(monkeypatch)
    stale = AuditInputError("bus_snapshot_stale", "aged")
    _fake_gather(monkeypatch, **{d.isoformat(): stale for d in audit.days_to_audit(TODAY, {})})
    monkeypatch.setattr(audit, "_pre_capture", lambda r, f, day: day == DAY)
    offers = Offers()
    assert _run(root, offers) == 1
    statuses = audit._audited_statuses(root, fx.FAMILY_ID)
    assert statuses[DAY] is DayStatus.PRE_CAPTURE
    assert {s for d, s in statuses.items() if d != DAY} == {DayStatus.ERROR}


def test_one_broken_day_does_not_stop_the_others_and_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.make_root(tmp_path)
    stub_legs(monkeypatch)
    _quiet_duties(monkeypatch)
    _fake_gather(monkeypatch, **{DAY.isoformat(): RuntimeError("leg bug")})
    assert _run(root, Offers()) == 1
    names = {p.name for p in _audit_dir(root).iterdir()}
    assert f"{DAY.isoformat()}.json" not in names and len(names) == 7  # never a partial day


def test_a_day_the_deadline_stops_is_deferred_without_a_file_and_does_not_fail_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """MUTATION: deadline ignored (the ScanDeadline branch gone) and partial day written."""
    root = w3.make_root(tmp_path)
    stub_legs(monkeypatch)
    _quiet_duties(monkeypatch)
    ordered = audit.days_to_audit(TODAY, {})
    reached, stopped = ordered[:2], ordered[2]
    _fake_gather(monkeypatch, **{stopped.isoformat(): inputs.ScanDeadline()})
    assert _run(root, Offers()) == 0
    names = {p.name for p in _audit_dir(root).iterdir()}
    assert names == {
        f"{d.isoformat()}.json" for d in reached
    }  # nothing for the stopped day or after
    err = capsys.readouterr().err
    assert all(d.isoformat() in err.split("audit_deferred_days=")[1] for d in ordered[2:])
    assert "errors=0" in err


def test_the_run_sets_the_work_deadline_from_the_monotonic_clock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[float | None] = []
    root = w3.make_root(tmp_path)
    stub_legs(monkeypatch)
    _quiet_duties(monkeypatch)
    monkeypatch.setattr(inputs, "MONOTONIC", lambda: 1000.0)
    asked = _fake_gather(monkeypatch)
    real: Any = vars(audit)["gather_inputs"]

    def spying(*a: Any, **k: Any) -> Any:
        seen.append(inputs.DEADLINE.get())
        return real(*a, **k)

    monkeypatch.setattr(audit, "gather_inputs", spying)
    _run(root, Offers())
    assert set(seen) == {1000.0 + AUDIT_WORK_BUDGET_S} and asked
    assert inputs.DEADLINE.get() is None  # reset after the run


def test_the_budget_is_the_unit_timeout_less_the_lock_wait_and_a_margin() -> None:
    assert AUDIT_WORK_BUDGET_S == 1500 - 600 - 60 == 840


# -- the HEALTH verdict (S2-R12) ---------------------------------------------------------------


def _pin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audit, "PRODUCER_SOURCE_SHA256", {audit.PRODUCER_ID: "ab" * 32})


def _verdicts(root: Path) -> list[dict[str, Any]]:
    base = root / "derived" / "verdicts" / fx.FAMILY_ID
    return (
        [json.loads(p.read_text()) for p in sorted(base.rglob("*.json"))] if base.exists() else []
    )


def test_verdict_schema_valid_bound_artefact_sha_and_pinned_producer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.make_root(tmp_path)
    _pin(monkeypatch)
    result = _status(monkeypatch, fills=(_fill_audit(legs=(leg_result("L"),)),))
    audit._write_health_verdict(root, result, w3.NOW_NS)
    (verdict,) = _verdicts(root)
    assert (
        verdict["kind"] == "HEALTH"
        and verdict["detector"] == audit.DETECTOR == "health.capture_join"
    )
    assert verdict["outcome"] == "PASS" and verdict["producer_code_sha"] == "ab" * 32
    assert verdict["n"] == 1 and verdict["metrics"]["day_status"] == "PASS"
    assert verdict["valid_until_ns"] - verdict["produced_at_ns"] == 26 * 3600 * NS
    assert verdict["policy_ruling_sha256"] is None and verdict["assumptions"] == [
        "no_policy_ruling"
    ]


def test_no_input_day_writes_file_and_inconclusive_verdict_with_day_status_no_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.make_root(tmp_path)
    _pin(monkeypatch)
    inp = fx.make_inputs(exec=ExecView(), boots=(fx.make_boot(replay=ReplayResult()),))
    result = _status(monkeypatch, inp)
    audit.write_audit_file(root, result, ts_ns=1)
    audit._write_health_verdict(root, result, w3.NOW_NS)
    (verdict,) = _verdicts(root)
    assert verdict["outcome"] == "INCONCLUSIVE" and verdict["n"] == 0
    assert verdict["metrics"]["day_status"] == "NO_INPUT"
    assert (_audit_dir(root) / f"{DAY.isoformat()}.json").exists()


@pytest.mark.parametrize(
    ("status", "outcome"),
    [
        (DayStatus.FAIL, "FAIL"),
        (DayStatus.ERROR, "ERROR"),
        (DayStatus.INCONCLUSIVE, "INCONCLUSIVE"),
        (DayStatus.PRE_CAPTURE, "INCONCLUSIVE"),
    ],
)
def test_the_verdict_outcome_follows_the_day_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: DayStatus, outcome: str
) -> None:
    root = w3.make_root(tmp_path)
    _pin(monkeypatch)
    result = dataclasses.replace(
        _status(monkeypatch), status=status, metrics={"day_status": status.value}
    )
    audit._write_health_verdict(root, result, w3.NOW_NS)
    assert _verdicts(root)[0]["outcome"] == outcome


def test_an_unpinned_producer_writes_no_verdict_and_says_so_at_info(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    assert pins.PRODUCER_SOURCE_SHA256.get(audit.PRODUCER_ID) is None  # the real pin is ARCH-0's
    root = w3.make_root(tmp_path)
    with caplog.at_level(logging.INFO):
        audit._write_health_verdict(root, _status(monkeypatch), w3.NOW_NS)
    assert _verdicts(root) == [] and "producer unpinned" in caplog.text


def test_a_refused_verdict_write_is_info_and_the_audit_file_stands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    root = w3.make_root(tmp_path)
    _pin(monkeypatch)
    stub_legs(monkeypatch)
    _quiet_duties(monkeypatch)
    _fake_gather(monkeypatch)

    def refuse(*a: Any, **k: Any) -> Any:
        raise VerdictRefused(VerdictRefusalReason.VALIDITY_ABOVE_CEILING)

    monkeypatch.setattr(audit, "write_verdict", refuse)
    with caplog.at_level(logging.INFO):
        assert _run(root, Offers()) == 0
    assert "verdict refused" in caplog.text and len(list(_audit_dir(root).iterdir())) == 8


def test_only_the_health_capture_join_verdict_is_ever_written() -> None:
    import ast

    tree = ast.parse(Path(audit.__file__).read_text())
    kinds = {
        n.attr
        for n in ast.walk(tree)
        if isinstance(n, ast.Attribute)
        and isinstance(n.value, ast.Name)
        and n.value.id == "VerdictKind"
    }
    assert kinds == {"HEALTH"}


# -- the moved duties (section 3.11.5) ---------------------------------------------------------


def _decisions(root: Path) -> Path:
    path = root / "catalog" / "quote_tape" / "decisions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _settle(root: Path, station: str, day: dt.date) -> None:
    record = SettlementRecord(station, day.isoformat(), 84, "NWS_CLI", "ab" * 32, 1)
    path = _decisions(root) / f"settlement_{day.isoformat()}.jsonl"
    path.write_text(record.to_line())
    path.chmod(0o600)  # the writer's own mode; a group- or world-writable file is refused


def _fill_for(station_day: dt.date, instrument_station: str = "lax") -> ExecFill:
    slug = f"tc-temp-{instrument_station}high-{station_day.isoformat()}-gte93lt94f.POLYMARKET_US"
    return dataclasses.replace(fx.make_exec_view().fills[0], instrument_id=slug)


def _delivery() -> audit._Delivery:
    return audit._Delivery(Offers())


def _duty_offers(offer: Offers) -> audit._Delivery:
    return audit._Delivery(offer)


def test_audit_alerts_settlement_missing_after_48h(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.make_root(tmp_path)
    old = TODAY - dt.timedelta(days=4)
    fresh = TODAY - dt.timedelta(days=1)
    monkeypatch.setattr(
        audit, "read_exec_view", lambda r: ExecView(fills=(_fill_for(old), _fill_for(fresh)))
    )
    offers = Offers()
    audit._check_settlements(root, TODAY, w3.NOW_NS, _duty_offers(offers))
    assert offers.calls == [
        ("CAPTURE_SETTLEMENT_MISSING", "CRITICAL", f"station=LAX climate_day={old}")
    ]


def test_a_settled_station_day_raises_no_settlement_alert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.make_root(tmp_path)
    old = TODAY - dt.timedelta(days=4)
    _settle(root, "LAX", old)
    monkeypatch.setattr(audit, "read_exec_view", lambda r: ExecView(fills=(_fill_for(old),)))
    offers = Offers()
    audit._check_settlements(root, TODAY, w3.NOW_NS, _duty_offers(offers))
    assert offers.calls == []


def test_settlement_alert_waits_exactly_48h_after_the_climate_day_ends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.make_root(tmp_path)
    day = TODAY - dt.timedelta(days=3)  # ends at TODAY-2 00:00; 48h later is TODAY 00:00
    monkeypatch.setattr(audit, "read_exec_view", lambda r: ExecView(fills=(_fill_for(day),)))
    boundary = w3.day_ns(TODAY)
    early, late = Offers(), Offers()
    audit._check_settlements(root, TODAY, boundary, _duty_offers(early))
    audit._check_settlements(root, TODAY, boundary + 1, _duty_offers(late))
    assert early.calls == [] and late.events == ["CAPTURE_SETTLEMENT_MISSING"]


def test_audit_alerts_stuck_inconclusive_after_8_days(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.make_root(tmp_path)
    stub_legs(monkeypatch)
    for age, status in (
        (9, DayStatus.INCONCLUSIVE),
        (8, DayStatus.INCONCLUSIVE),
        (10, DayStatus.PASS),
    ):
        day = TODAY - dt.timedelta(days=age)
        result = dataclasses.replace(audit.audit_day(fx.make_inputs(day=day)), status=status)
        audit.write_audit_file(root, result, ts_ns=1)
    offers = Offers()
    audit._check_stuck(root, fx.FAMILY_ID, TODAY, _duty_offers(offers))
    assert offers.calls == [
        ("CAPTURE_AUDIT_STUCK_INCONCLUSIVE", "CRITICAL", f"day={TODAY - dt.timedelta(days=9)}")
    ]


def _proof(root: Path, family: str, asof: dt.date, *, age_h: float) -> None:
    directory = root / "evidence" / "capture" / "live_proof"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"live_proof_{family}_{asof.isoformat()}.json"
    path.write_text("{}")
    stamp = w3.NOW_NS - int(age_h * 3600 * NS)
    os.utime(path, ns=(stamp, stamp))


@pytest.mark.parametrize(("age_h", "alerts"), [(25.9, 0), (26.0, 0), (26.1, 1), (72.0, 1)])
def test_audit_alerts_live_proof_stale(tmp_path: Path, age_h: float, alerts: int) -> None:
    root = w3.make_root(tmp_path)
    _proof(root, fx.FAMILY_ID, DAY, age_h=age_h)
    _proof(root, "other_family", DAY, age_h=1.0)  # another family's roll-up never rescues this one
    offers = Offers()
    audit._check_live_proof(root, fx.FAMILY_ID, w3.NOW_NS, _duty_offers(offers))
    assert len(offers.calls) == alerts


def test_a_missing_live_proof_is_stale(tmp_path: Path) -> None:
    offers = Offers()
    audit._check_live_proof(w3.make_root(tmp_path), fx.FAMILY_ID, w3.NOW_NS, _duty_offers(offers))
    assert offers.events == ["CAPTURE_LIVE_PROOF_STALE"]


def test_each_moved_check_isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """MUTATION: a moved check that is not isolated. A raising check must not stop the others."""
    root = w3.make_root(tmp_path)
    stub_legs(monkeypatch)
    _fake_gather(monkeypatch)
    ran: list[str] = []

    def broken(*a: Any, **k: Any) -> None:
        ran.append("settlement")
        raise OSError("snapshot")

    monkeypatch.setattr(audit, "_check_settlements", broken)
    monkeypatch.setattr(audit, "_check_stuck", lambda *a, **k: ran.append("stuck"))
    monkeypatch.setattr(audit, "_check_live_proof", lambda *a, **k: ran.append("live_proof"))
    assert _run(root, Offers()) == 1  # a failed duty fails the run, loudly, after all of them ran
    assert ran == ["settlement", "stuck", "live_proof"]


@pytest.mark.parametrize("breaker", ["_check_settlements", "_check_stuck", "_check_live_proof"])
def test_each_duty_failure_leaves_the_other_two_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, breaker: str
) -> None:
    root = w3.make_root(tmp_path)
    stub_legs(monkeypatch)
    _fake_gather(monkeypatch)
    ran: set[str] = set()
    for name in ("_check_settlements", "_check_stuck", "_check_live_proof"):

        def duty(*a: Any, _n: str = name, **k: Any) -> None:
            ran.add(_n)
            if _n == breaker:
                raise RuntimeError("boom")

        monkeypatch.setattr(audit, name, duty)
    _run(root, Offers())
    assert ran == {"_check_settlements", "_check_stuck", "_check_live_proof"}


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
