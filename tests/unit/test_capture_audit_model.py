"""AUT-1 WP5 stage 2a: the shared audit model, input types and wire format (design S2-R3).

Pure value types only: no leg logic and no I/O live in these modules.
"""

import dataclasses
import datetime as dt
import json
from typing import Any

import pytest

from breezy.analysis import capture_audit_input_types as types
from breezy.analysis import capture_audit_model as model
from breezy.analysis import capture_audit_wire as wire
from breezy.persistence.autonomy.veto import VetoReason
from tests.support import capture_audit_fixtures as fx

DAY = dt.date(2026, 10, 3)


def _finding(**over: Any) -> model.Finding:
    kw: dict[str, Any] = {
        "leg": model.Leg.R2,
        "outcome": model.LegOutcome.FAIL,
        "cause": "stream_record_lost",
        "subject": "ab" * 32,
        "detail": "table=decisions",
    }
    kw.update(over)
    return model.Finding(**kw)


def _rich_result() -> model.AuditResult:
    finding = _finding()
    leg = model.LegResult(model.Leg.R2, model.LegOutcome.FAIL, (finding,), {"missing": 2})
    fill = model.FillAudit(
        client_order_id="O-20261003-165052-L001-LAX-1",
        trade_id="CVWEANWH8YHR",
        family_id="pm_us_crh_fq_v1",
        source="live",
        drill=False,
        attributed=True,
        legs=(model.LegResult(model.Leg.L, model.LegOutcome.PASS),),
        causes=("link_conflict",),
    )
    return model.AuditResult(
        day=DAY,
        family_id="pm_us_crh_fq_v1",
        status=model.DayStatus.FAIL,
        cause="stream_record_lost",
        legs=(leg,),
        fills=(fill,),
        metrics={"day_status": "FAIL", "fills_total": 1, "refusal_frame_ref_resolved_frac": 0.91},
        watchdog_evidence_gaps=(
            model.WatchdogGap("breezy-quote-tape.service", "inv-1", 5, "no_page"),
        ),
        duplicate_decision_lines=3,
        tape_marks=(model.TapeMark("tc-x.POLYMARKET_US", 12, 0.5, -1),),
    )


# -- constants and closed sets ---------------------------------------------------------------------


def test_constants_have_the_design_values() -> None:
    assert model.AUDIT_SCHEMA == "capture_audit/v2"
    assert model.STREAM_GAP_FAIL_S == 180
    assert model.FLUSH_WINDOW_S == 61
    assert model.R6_BASELINE == 0.923
    assert model.SETTLEMENT_PENDING_H == 36
    assert model.SETTLEMENT_ALERT_H == 48
    assert model.BACKFILL_DAYS == 8
    assert model.LIVE_PROOF_MAX_AGE_H == 26
    assert model.PC_MIN_OVERLAP_S == 1200
    assert model.AUDIT_WORK_BUDGET_S == 840 == 1500 - 600 - 60
    assert model.AUDIT_EXEC_TIMEOUT_S == 1470  # S3-R50: the audit ExecStart ``timeout -k 5 1470``
    assert model.AUDIT_MARGIN_S == 60 and model.DUTY_RESERVE_S == 60  # S3-R41
    assert model.AUDIT_DIR_REL == "evidence/capture/audit"
    assert model.AUDIT_CACHE_DIR == "cache/capture_audit"


def test_live_proof_name_pattern_matches_the_documented_file_name() -> None:
    match = model.LIVE_PROOF_NAME_RE.fullmatch("live_proof_pm_us_crh_fq_v1_2026-10-03.json")
    assert match is not None and match["family_id"] == "pm_us_crh_fq_v1"
    assert match["asof"] == "2026-10-03"
    assert model.LIVE_PROOF_NAME_RE.fullmatch("live_proof_x_notadate.json") is None


def test_error_causes_are_the_closed_design_set_plus_the_review_additions() -> None:
    assert model.ERROR_CAUSES == frozenset(
        {
            "exec_snapshot_failed",
            "exec_key_prefix_unknown",
            "exec_record_undecodable",
            "node_log_unreadable",
            "node_log_unparseable",
            "node_log_missing",
            "node_log_blind",
            "journal_failed",
            "epoch_missing",
            "epoch_rewritten",
            "epoch_unlogged",
            "epoch_unreadable",
            "stream_unreadable",
            "capture_projection_failed",
            "recorder_watchdog_unarmed",
            "bus_snapshot_missing",
            "bus_snapshot_stale",
            "funnel_missing",
            "node_log_sink_failed",
            "tape_unreadable",
            "settlement_unreadable",
            "entry_lines_capped",
        }
    )


def test_audit_input_error_carries_a_known_cause() -> None:
    err = model.AuditInputError("tape_unreadable", "catalog column missing")
    assert err.cause == "tape_unreadable" and "catalog column missing" in str(err)


def test_audit_input_error_refuses_an_unknown_cause() -> None:
    with pytest.raises(ValueError, match="unknown audit error cause"):
        model.AuditInputError("something_else")


def test_enums_have_the_design_members() -> None:
    assert {s.value for s in model.DayStatus} == {
        "PASS",
        "INCONCLUSIVE",
        "NO_INPUT",
        "PRE_CAPTURE",
        "PARTIAL_EPOCH",
        "ERROR",
        "FAIL",
    }
    assert {leg.value for leg in model.Leg} == {
        *"LDBIEPS",
        "R1",
        "R2",
        "R3",
        "R4",
        "R5",
        "R6",
        "R7",
        "W",
        "O",
        "F",
        "T",
        "N",
        "PC",
    }
    assert {o.value for o in model.LegOutcome} == {
        "PASS",
        "FAIL",
        "PENDING",
        "INFO",
        "ERROR",
        "SKIPPED",
    }


def test_metric_names_are_closed_and_cover_every_leg() -> None:
    assert {f"leg_{leg.value}_pass" for leg in model.Leg} <= model.METRIC_NAMES
    assert {
        "day_status",
        "fills_total",
        "fills_joined",
        "records_lost_in_flush_window",
        "refusal_frame_ref_resolved_frac",
        "watchdog_kills_unproven",
    } <= model.METRIC_NAMES
    assert len(model.METRIC_NAMES) == len(model.Leg) + 6


def test_an_audit_result_refuses_an_unregistered_metric_name() -> None:
    with pytest.raises(ValueError, match="unregistered metric"):
        model.AuditResult(
            day=DAY,
            family_id="f",
            status=model.DayStatus.PASS,
            cause="",
            legs=(),
            fills=(),
            metrics={"leg_Z_pass": 1},
        )


@pytest.mark.parametrize(
    ("kind", "reason", "expected"),
    [
        ("EntryVeto", VetoReason.CAPTURE_GAP.value, True),
        ("EntryVeto", VetoReason.CAPTURE_UNTAGGED.value, True),
        # FQ own VetoReason EntryVetos go through the adapter OnChangeFilter: not guard vetoes.
        ("EntryVeto", VetoReason.PERMIT_LAPSED.value, False),
        ("EntryVeto", VetoReason.FEED_STALE.value, False),
        ("EntryVeto", "family_halt", False),
        ("EntryVeto", "phase0_permit_absent", False),
        ("EntryVeto", "below_margin", False),
        ("Refuse", VetoReason.CAPTURE_GAP.value, False),
        ("Take", "", False),
        ("TrySubmit", "submitted", False),
    ],
)
def test_is_guard_entry_veto(kind: str, reason: str, expected: bool) -> None:
    assert model.is_guard_entry_veto(kind, reason) is expected


# -- every type is frozen --------------------------------------------------------------------


def _instances() -> list[object]:
    result = _rich_result()
    inputs = fx.make_inputs()
    return [
        _finding(),
        result.legs[0],
        result.fills[0],
        result,
        result.watchdog_evidence_gaps[0],
        result.tape_marks[0],
        inputs,
        inputs.boots[0],
        inputs.boots[0].summary,
        inputs.boots[0].markers,
        inputs.boots[0].replay,
        inputs.exec,
        inputs.exec.fills[0],
        inputs.exec.orders[0],
        inputs.exec.resolvers[0],
        inputs.funnel[0],
        inputs.recorder_props,
        inputs.recorder_journal[0],
        inputs.ingest_lines[0],
        inputs.stall_records[0],
        inputs.notifier_proofs[0],
    ]


@pytest.mark.parametrize("obj", _instances(), ids=lambda o: type(o).__name__)
def test_every_audit_type_is_frozen(obj: object) -> None:
    assert dataclasses.is_dataclass(obj)
    first = dataclasses.fields(obj)[0].name
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(obj, first, None)


def test_boot_evidence_holds_reduced_summaries_and_a_lazy_stream_handle() -> None:
    names = {f.name for f in dataclasses.fields(types.BootEvidence)}
    assert names == {
        "instance_id",
        "source",
        "stream",
        "summary",
        "c1",
        "log_name",
        "scan",
        "markers",
        "replay",
        "started_ns",
        "last_line_ts_ns",
        "ended",
        "disposed",
        "overlap_s",
        "subscribed",
    }
    boot = fx.make_boot()
    assert callable(boot.stream)  # a handle: nothing is materialised until it is called
    assert not hasattr(boot.summary, "decisions")


def test_audit_inputs_has_the_design_fields() -> None:
    names = [f.name for f in dataclasses.fields(types.AuditInputs)]
    assert names[:15] == [
        "day",
        "family_id",
        "epoch",
        "boots",
        "exec",
        "settlements",
        "std_offsets",
        "tape",
        "ingest_lines",
        "ingest_exited_after_rotation",
        "recorder_journal",
        "recorder_props",
        "stall_records",
        "notifier_proofs",
        "now_ns",
    ]
    assert names[15:] == ["funnel", "resolver_live", "nbp_stations", "nbp_cycles_ns"]


def test_the_fixture_tape_satisfies_the_tape_protocol() -> None:
    tape = fx.make_inputs().tape
    assert isinstance(tape, types.TapeIndex)
    assert tape.lookup("depth10", "tc-x.POLYMARKET_US", 1) is None
    assert tape.best_ask_at("tc-x.POLYMARKET_US", 1) is None
    assert list(tape.quote_rows("tc-x.POLYMARKET_US", 0, 10)) == []
    assert list(tape.depth_rows("tc-x.POLYMARKET_US", 0, 10)) == []


def test_fixture_builders_override_fields() -> None:
    inputs = fx.make_inputs(family_id="other", now_ns=7)
    assert (inputs.family_id, inputs.now_ns) == ("other", 7)
    assert fx.make_inputs().family_id == "pm_us_crh_fq_v1"


# -- wire format -----------------------------------------------------------------------------


def test_wire_round_trip_is_lossless() -> None:
    result = _rich_result()
    doc = wire.audit_to_wire(result)
    assert doc["schema"] == model.AUDIT_SCHEMA
    again = wire.audit_from_wire(json.loads(json.dumps(doc)))
    assert again == result


def test_wire_round_trip_of_an_empty_result() -> None:
    empty = model.AuditResult(
        day=DAY, family_id="f", status=model.DayStatus.NO_INPUT, cause="", legs=(), fills=()
    )
    assert wire.audit_from_wire(json.loads(json.dumps(wire.audit_to_wire(empty)))) == empty


def test_wire_document_is_json_serialisable_with_string_enums() -> None:
    doc = wire.audit_to_wire(_rich_result())
    text = json.dumps(doc, sort_keys=True)
    assert '"status": "FAIL"' in text and '"day": "2026-10-03"' in text


def _doc() -> dict[str, Any]:
    doc: dict[str, Any] = json.loads(json.dumps(wire.audit_to_wire(_rich_result())))
    return doc


def test_from_wire_refuses_a_wrong_schema() -> None:
    doc = _doc()
    doc["schema"] = "capture_audit/v1"
    with pytest.raises(wire.AuditWireError, match="schema"):
        wire.audit_from_wire(doc)


@pytest.mark.parametrize("key", ["day", "family_id", "status", "legs", "fills", "metrics"])
def test_from_wire_refuses_a_missing_key(key: str) -> None:
    doc = _doc()
    del doc[key]
    with pytest.raises(wire.AuditWireError):
        wire.audit_from_wire(doc)


def test_from_wire_refuses_an_unknown_key() -> None:
    doc = _doc()
    doc["surprise"] = 1
    with pytest.raises(wire.AuditWireError, match="unexpected"):
        wire.audit_from_wire(doc)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("status",), "GREAT"),
        (("legs", 0, "leg"), "R9"),
        (("legs", 0, "outcome"), "MAYBE"),
        (("day",), "yesterday"),
    ],
)
def test_from_wire_refuses_an_unknown_status_leg_outcome_or_day(
    path: tuple[str | int, ...], value: str
) -> None:
    doc = _doc()
    node: Any = doc
    for step in path[:-1]:
        node = node[step]
    node[path[-1]] = value
    with pytest.raises(wire.AuditWireError):
        wire.audit_from_wire(doc)


def test_from_wire_refuses_a_bool_where_an_int_is_required() -> None:
    doc = _doc()
    doc["duplicate_decision_lines"] = True
    with pytest.raises(wire.AuditWireError):
        wire.audit_from_wire(doc)


def test_from_wire_refuses_an_unregistered_metric() -> None:
    doc = _doc()
    doc["metrics"]["made_up"] = 1
    with pytest.raises(wire.AuditWireError):
        wire.audit_from_wire(doc)


def test_from_wire_refuses_a_non_mapping_document() -> None:
    with pytest.raises(wire.AuditWireError):
        wire.audit_from_wire([])  # type: ignore[arg-type]


def test_guard_veto_reasons_are_the_capture_guards_own_refusal_reasons() -> None:
    """Derived from ``guarded_strategy`` (the reasons its ``_refuse_one`` writes directly, which
    never pass through the adapter's filter), and disjoint from FQ's own submit-guard reasons."""
    from breezy.strategy.autonomy_capture import guarded_strategy as guard

    enum_values = {r.value for r in VetoReason}
    guard_reasons = {
        value
        for name, value in vars(guard).items()
        if name.startswith("REASON_") and isinstance(value, str) and value in enum_values
    }
    assert guard_reasons == model.GUARD_VETO_REASONS == {"capture_gap", "capture_untagged"}
    fq_own = {
        guard.REASON_PHASE0_PERMIT_ABSENT,
        guard.REASON_FEE_UNVERIFIED,
        guard.REASON_FAMILY_HALT,
        guard.REASON_INSTRUMENT_VANISHED,
    }
    assert not guard_reasons & fq_own


def test_exec_timeout_fits_the_unit_budget_with_the_lint_pre_line_bound() -> None:
    """S3-R48/R50: pre lines 5 + 5 + 15, the ExecStart ``timeout -k 5 1470`` -> 25 + 5 + 1470 =
    1500, exactly ``TimeoutStartSec``."""
    pre_line_bound_s, kill_after_s, start_timeout_s = 25, 5, 1500
    assert pre_line_bound_s + kill_after_s + model.AUDIT_EXEC_TIMEOUT_S == start_timeout_s
