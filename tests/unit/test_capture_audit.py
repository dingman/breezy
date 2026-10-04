"""AUT-1 WP5 stage 2b W3: the audit's orchestration (plan r12 sections 3.11.4-3.11.6; S2-R6/R9/R12).

The legs belong to W1 and W2 (other worktrees), so every test here stubs them through
``stub_legs`` and drives the REAL status table, scheduling, file writer, verdict writer, delivery
seam, moved duties and entry point. Files are real, under ``tmp_path``.
"""

import dataclasses
import datetime as dt
import json
import logging
import stat
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from breezy.analysis import capture_audit as audit
from breezy.analysis import capture_audit_inputs as inputs
from breezy.analysis.capture_audit_input_types import (
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
from breezy.persistence.autonomy import pins
from breezy.persistence.autonomy.capture_epoch import EpochRecord
from breezy.persistence.autonomy.verdict import VerdictRefusalReason, VerdictRefused
from tests.support import capture_audit_fixtures as fx
from tests.support import capture_audit_w3_fixtures as w3
from tests.support.capture_audit_run_support import (
    Offers,
)
from tests.support.capture_audit_run_support import (
    fake_gather as _fake_gather,
)
from tests.support.capture_audit_run_support import (
    quiet_duties as _quiet_duties,
)
from tests.support.capture_audit_run_support import (
    run as _run,
)
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
        pytest.param(
            {
                "boots": (
                    fx.make_boot(
                        replay=fx.make_replay(
                            admitted_total=1,
                            admitted_by_kind={"Take": 1},
                            evaluations=1,
                            eval_seq_final=0,
                        )
                    ),
                )
            },
            id="take_line",
        ),
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


def test_delivery_send_accepts_prefixed_events() -> None:
    """S3-R2, S3-R40: ``HEALED_``/``ABANDONED_`` events are not dict keys; they must still reach
    ``offer`` (INFO and CRITICAL) and must not count as a failed delivery."""
    offers = Offers()
    delivery = audit._Delivery(offers)
    delivery.send(f"CAPTURE_HEALED_{'ab' * 32}", "d=1")
    delivery.send(f"CAPTURE_HEAL_ALERT_ABANDONED_{'cd' * 32}", "d=2")
    assert delivery.failed == 0
    assert [(c[0][-4:], c[1]) for c in offers.calls] == [("abab", "INFO"), ("cdcd", "CRITICAL")]


def test_delivery_send_unknown_event_is_a_failed_delivery_not_a_crash() -> None:
    offers = Offers()
    delivery = audit._Delivery(offers)
    delivery.send("NOT_AN_EVENT", "x")
    assert delivery.failed == 1 and offers.calls == []


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
