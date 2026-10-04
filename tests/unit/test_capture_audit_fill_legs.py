"""AUT-1 WP5 stage 2b W1: the per-fill legs and the census legs O, F and R6 (plan r12 3.11.2).

Every leg is a pure function over one ``AuditInputs``. Each test changes the one thing it varies
from ``entry_day()`` / ``exit_day()`` and reads the leg outcome and the finding cause.
"""

import ast
import dataclasses
import datetime as dt
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from breezy.analysis import capture_audit_fill_legs as legs_mod
from breezy.analysis.capture_audit_fill_legs import (
    audit_fills,
    leg_f,
    leg_o,
    leg_r6,
    tape_marks,
)
from breezy.analysis.capture_audit_input_types import AuditInputs, ExecFill, ExecOrder
from breezy.analysis.capture_audit_model import (
    FillAudit,
    Leg,
    LegOutcome,
    LegResult,
    TapeMark,
)
from breezy.analysis.capture_node_log import NodeLogScan
from breezy.analysis.capture_node_log_decisions import OrderFilledLine
from breezy.analysis.capture_settlement import SettlementRecord
from breezy.ingest.records import _climate_day_end_ns
from breezy.persistence.autonomy.capture_ids import (
    compute_orphan_decision_id,
    forecast_ref_of,
    frame_ref_of,
)
from breezy.persistence.autonomy.capture_records import FrameCopy, make_record
from tests.support import capture_audit_fixtures as base
from tests.support.capture_audit_w1_fixtures import (
    COID,
    DAY_START_NS,
    DEPTH_BODY,
    EVAL_NS,
    FILL_TS,
    FRAME_TS,
    INSTRUMENT,
    NO_INSTRUMENT,
    QUOTE_BODY,
    STATION,
    TRADE_ID,
    VSHA,
    DictTape,
    decision_view,
    entry_day,
    exit_day,
    link_view,
    markers_with,
    replace_boot,
    replace_c1,
    resolver,
    with_decisions,
)
from tests.unit.capture_reader_support import HOUR_NS

NS = base.NS
DAY = base.DAY
H = 3600 * NS
FILL_KINDS = ("depth10", "quote")


def _one(inp: AuditInputs) -> FillAudit:
    fills = audit_fills(inp)
    assert len(fills) == 1
    return fills[0]


def _leg(fill: FillAudit, leg: Leg) -> LegResult:
    (found,) = [r for r in fill.legs if r.leg is leg]
    return found


def _causes(result: LegResult) -> set[str]:
    return {f.cause for f in result.findings}


def _failing(result: LegResult) -> set[str]:
    return {f.cause for f in result.findings if f.outcome is LegOutcome.FAIL}


def _with_links(inp: AuditInputs, *links: Any) -> AuditInputs:
    return replace_c1(inp, order_links=tuple(links))


# -- the clean day ---------------------------------------------------------------------------


@pytest.mark.parametrize("frame_kind", FILL_KINDS)
def test_complete_day_passes_final(frame_kind: str) -> None:
    fill = _one(entry_day(frame_kind))

    assert [r.leg for r in fill.legs] == [Leg.L, Leg.D, Leg.B, Leg.I, Leg.E, Leg.P, Leg.S]
    assert [r.outcome for r in fill.legs] == [LegOutcome.PASS] * 7
    assert fill.attributed is True
    assert (fill.client_order_id, fill.trade_id) == (COID, TRADE_ID)
    assert (fill.family_id, fill.source, fill.drill) == (base.FAMILY_ID, "live", False)
    assert fill.causes == ()


def test_no_fills_gives_no_fill_audits() -> None:
    inp = entry_day()
    empty = dataclasses.replace(inp, exec=dataclasses.replace(inp.exec, fills=()))
    assert audit_fills(empty) == ()


def test_only_fills_of_the_audited_utc_day_are_audited() -> None:
    inp = entry_day()
    other = dataclasses.replace(inp.exec.fills[0], ts_event=FILL_TS + 86_400 * NS)
    inp = dataclasses.replace(
        inp, exec=dataclasses.replace(inp.exec, fills=(inp.exec.fills[0], other))
    )
    assert len(audit_fills(inp)) == 1


# -- epoch -----------------------------------------------------------------------------------


def test_fill_before_epoch_is_unattributed() -> None:
    inp = entry_day()
    assert inp.epoch is not None
    late_epoch = dataclasses.replace(inp.epoch, epoch_start_ns=FILL_TS + 1)
    fill = _one(dataclasses.replace(inp, epoch=late_epoch))

    assert fill.attributed is False
    assert fill.legs == ()
    assert fill.causes == ("unattributed",)


def test_fill_at_exactly_the_epoch_is_attributed() -> None:
    inp = entry_day()
    assert inp.epoch is not None
    at_epoch = dataclasses.replace(inp.epoch, epoch_start_ns=FILL_TS)
    assert _one(dataclasses.replace(inp, epoch=at_epoch)).attributed is True


def test_no_epoch_attributes_nothing() -> None:
    fill = _one(dataclasses.replace(entry_day(), epoch=None))
    assert (fill.attributed, fill.legs) == (False, ())


# -- leg L -----------------------------------------------------------------------------------


def test_orphan_fill_without_link_fails() -> None:
    fill = _one(_with_links(entry_day()))

    result = _leg(fill, Leg.L)
    assert result.outcome is LegOutcome.FAIL
    assert _failing(result) == {"no_order_link"}
    assert result.findings[0].subject == COID
    assert "no_order_link" in fill.causes
    for later in (Leg.D, Leg.B, Leg.I):
        assert _leg(fill, later).outcome is LegOutcome.SKIPPED


def test_untagged_order_orphan_id_fails_leg_l() -> None:
    orphan = compute_orphan_decision_id(base.FAMILY_ID, COID)
    fill = _one(_with_links(entry_day(), link_view(orphan, side="SELL")))

    assert _failing(_leg(fill, Leg.L)) == {"untagged_order"}
    assert "untagged_order" in fill.causes


def test_link_conflict_fails() -> None:
    inp = entry_day()
    first = inp.boots[0].c1.order_links[0]
    second = link_view("f" * 32)
    fill = _one(_with_links(inp, first, second))

    result = _leg(fill, Leg.L)
    assert result.outcome is LegOutcome.FAIL
    assert _failing(result) == {"link_conflict"}


def test_the_same_tag_twice_is_not_a_conflict() -> None:
    inp = entry_day()
    link = inp.boots[0].c1.order_links[0]
    assert _leg(_one(_with_links(inp, link, link)), Leg.L).outcome is LegOutcome.PASS


def test_link_in_a_second_boot_conflicts_with_the_first() -> None:
    inp = entry_day()
    other = base.make_boot(
        instance_id="second-boot",
        c1=dataclasses.replace(
            inp.boots[0].c1, order_links=(link_view("e" * 32),), decisions=(), lifecycle_events=()
        ),
    )
    fill = _one(dataclasses.replace(inp, boots=(*inp.boots, other)))
    assert _failing(_leg(fill, Leg.L)) == {"link_conflict"}


# -- leg D -----------------------------------------------------------------------------------


def test_take_missing_fails_leg_d() -> None:
    inp = entry_day()
    submit_only = tuple(d for d in inp.boots[0].c1.decisions if d.kind == "TrySubmit")
    fill = _one(replace_c1(inp, decisions=submit_only))
    assert _failing(_leg(fill, Leg.D)) == {"take_missing"}


def test_trysubmit_submitted_missing_fails_leg_d() -> None:
    inp = entry_day()
    takes = tuple(d for d in inp.boots[0].c1.decisions if d.kind == "Take")
    assert _failing(_leg(_one(replace_c1(inp, decisions=takes)), Leg.D)) == {"trysubmit_missing"}


def test_a_refused_trysubmit_is_not_a_submitted_one() -> None:
    inp = entry_day()
    take = inp.boots[0].c1.decisions[0]
    vetoed = decision_view("TrySubmit", "capture_gap", decision_id=take.decision_id)
    fill = _one(replace_c1(inp, decisions=(take, vetoed)))
    assert _failing(_leg(fill, Leg.D)) == {"trysubmit_missing"}


def test_leg_d_recomputes_the_id_from_the_take() -> None:
    """A Take whose stored id is not what its own fields hash to fails, even when linked."""
    inp = entry_day()
    forged = "9" * 32
    take = decision_view("Take", "take", decision_id=forged)
    submit = decision_view("TrySubmit", "submitted", decision_id=forged)
    fill = _one(replace_c1(inp, decisions=(take, submit), order_links=(link_view(forged),)))

    assert _failing(_leg(fill, Leg.D)) == {"decision_id_mismatch"}


def test_leg_d_recompute_uses_the_stored_eval_seq() -> None:
    """The id is recomputed from the record's own ``eval_seq``, never a derived one."""
    inp = entry_day()
    take = decision_view("Take", "take", eval_seq=1_000_001)
    submit = decision_view(
        "TrySubmit", "submitted", decision_id=take.decision_id, eval_seq=1_000_001
    )
    fill = _one(
        replace_c1(inp, decisions=(take, submit), order_links=(link_view(take.decision_id),))
    )
    assert _leg(fill, Leg.D).outcome is LegOutcome.PASS


def test_registry_seq_zero_after_resolver_live_fails() -> None:
    inp = entry_day()
    take = decision_view("Take", "take", registry_seq=0)
    submit = decision_view("TrySubmit", "submitted", decision_id=take.decision_id, registry_seq=0)
    zeroed = replace_c1(inp, decisions=(take, submit))

    live = _one(dataclasses.replace(zeroed, resolver_live=True))
    assert _failing(_leg(live, Leg.D)) == {"registry_seq_zero"}
    assert "registry_seq_zero" in live.causes

    not_live = _one(dataclasses.replace(zeroed, resolver_live=False))
    assert _leg(not_live, Leg.D).outcome is LegOutcome.PASS


def test_every_exit_fill_joins() -> None:
    fill = _one(exit_day())

    assert _leg(fill, Leg.L).outcome is LegOutcome.PASS
    assert _leg(fill, Leg.D).outcome is LegOutcome.PASS
    assert _leg(fill, Leg.B).outcome is LegOutcome.PASS
    assert [r.outcome for r in fill.legs] == [LegOutcome.PASS] * 7


def test_exit_record_missing_fails_leg_d() -> None:
    fill = _one(replace_c1(exit_day(), decisions=()))
    assert _failing(_leg(fill, Leg.D)) == {"exit_record_missing"}


def test_exit_id_that_does_not_recompute_from_the_tags_fails() -> None:
    inp = exit_day()
    link = inp.boots[0].c1.order_links[0]
    exit_record = inp.boots[0].c1.decisions[0]
    stream = inp.boots[0].stream()
    bad_row = {**stream.order_initialized[0], "tags": '["exit_rule=x","exit_position_id=p"]'}
    forged_stream = dataclasses.replace(stream, order_initialized=(bad_row,))
    forged = replace_boot(inp, stream=lambda: forged_stream)
    forged = replace_c1(forged, decisions=(exit_record,), order_links=(link,))

    assert _failing(_leg(_one(forged), Leg.D)) == {"exit_id_unrecomputable"}


def test_exit_decision_whose_id_differs_from_the_tag_hash_fails() -> None:
    inp = exit_day()
    link = inp.boots[0].c1.order_links[0]
    wrong = decision_view("Exit", "exit", decision_id="1" * 32, frame_kind="")
    fill = _one(
        replace_c1(
            inp, decisions=(wrong,), order_links=(dataclasses.replace(link, decision_id="1" * 32),)
        )
    )
    assert _failing(_leg(fill, Leg.D)) == {"exit_id_mismatch"}


# -- leg B -----------------------------------------------------------------------------------


def _tape_with(kind: str, body: Mapping[str, Any] | None) -> DictTape:
    rows = {} if body is None else {(kind, INSTRUMENT, FRAME_TS): body}
    return DictTape(rows=rows)


@pytest.mark.parametrize("frame_kind", FILL_KINDS)
def test_leg_b_frame_copy_equal_to_tape_passes_without_info(frame_kind: str) -> None:
    result = _leg(_one(entry_day(frame_kind)), Leg.B)
    assert result.outcome is LegOutcome.PASS
    assert result.findings == ()


@pytest.mark.parametrize("frame_kind", FILL_KINDS)
def test_tape_frame_absent_is_info_not_fail(frame_kind: str) -> None:
    inp = dataclasses.replace(entry_day(frame_kind), tape=_tape_with(frame_kind, None))
    fill = _one(inp)

    result = _leg(fill, Leg.B)
    assert result.outcome is LegOutcome.PASS
    assert [(f.outcome, f.cause) for f in result.findings] == [
        (LegOutcome.INFO, "tape_frame_absent")
    ]
    assert fill.causes == ()


@pytest.mark.parametrize(
    ("frame_kind", "tampered"),
    [
        ("depth10", {**DEPTH_BODY, "asks": [["0.15", "6"]]}),
        ("depth10", {**DEPTH_BODY, "bids": []}),
        ("quote", {**QUOTE_BODY, "ask": "0.16"}),
        ("quote", {**QUOTE_BODY, "bid": "0.13"}),
    ],
)
def test_frame_copy_mismatch_with_tape_fails(frame_kind: str, tampered: Mapping[str, Any]) -> None:
    inp = dataclasses.replace(entry_day(frame_kind), tape=_tape_with(frame_kind, tampered))
    fill = _one(inp)

    result = _leg(fill, Leg.B)
    assert result.outcome is LegOutcome.FAIL
    assert _failing(result) == {"frame_copy_mismatch"}
    assert "frame_copy_mismatch" in fill.causes


def test_a_tape_row_with_zero_size_pad_levels_still_equals_the_copy() -> None:
    padded = {
        **DEPTH_BODY,
        "bids": [["0.14", "10"], ["0.13", "0"]],
        "asks": [*DEPTH_BODY["asks"], ["0.99", "0"]],
    }
    inp = dataclasses.replace(entry_day("depth10"), tape=_tape_with("depth10", padded))
    assert _leg(_one(inp), Leg.B).outcome is LegOutcome.PASS


def test_the_tape_is_looked_up_at_the_decision_frame_reference() -> None:
    inp = entry_day("quote")
    tape = inp.tape
    assert isinstance(tape, DictTape)
    _one(inp)
    assert ("quote", INSTRUMENT, FRAME_TS) in tape.lookups


def test_take_path_frame_copy_missing_fails() -> None:
    inp = entry_day()
    boot = inp.boots[0]
    empty = dataclasses.replace(boot.stream(), frame_copies=())
    fill = _one(replace_boot(inp, stream=lambda: empty))

    assert _failing(_leg(fill, Leg.B)) == {"frame_copy_missing"}


def test_frame_copy_of_another_decision_is_not_the_takes_copy() -> None:
    inp = entry_day()
    stream = inp.boots[0].stream()
    other = make_record(
        FrameCopy,
        ts_event=FRAME_TS,
        ts_init=EVAL_NS,
        schema="capture_frame_copy/v1",
        decision_id="0" * 32,
        frame_kind="depth10",
        instrument=INSTRUMENT,
        frame_ts_event=FRAME_TS,
        frame_body=dict(DEPTH_BODY),
    )
    swapped = dataclasses.replace(stream, frame_copies=(other,))
    assert _failing(_leg(_one(replace_boot(inp, stream=lambda: swapped)), Leg.B)) == {
        "frame_copy_missing"
    }


def test_forecast_ref_resolves_inside_the_boot_stream() -> None:
    assert _leg(_one(entry_day()), Leg.B).outcome is LegOutcome.PASS


def test_forecast_ref_missing_from_the_boot_stream_fails() -> None:
    """The cycle's points are in ANOTHER boot's stream: the cited boot cannot resolve it."""
    inp = entry_day()
    stream = dataclasses.replace(inp.boots[0].stream(), forecast_points=())
    fill = _one(replace_boot(inp, stream=lambda: stream))

    assert _failing(_leg(fill, Leg.B)) == {"forecast_ref_unresolved"}
    assert fill.causes == ("forecast_ref_unresolved",)


def test_forecast_ref_with_a_wrong_vintage_fails() -> None:
    inp = entry_day()
    take = inp.boots[0].c1.decisions[0]
    skewed = dataclasses.replace(
        take, forecast_input_ref=forecast_ref_of("KLAX", 100 * HOUR_NS, 102 * HOUR_NS + 7)
    )
    submit = inp.boots[0].c1.decisions[1]
    fill = _one(replace_c1(inp, decisions=(skewed, submit)))
    assert _failing(_leg(fill, Leg.B)) == {"forecast_ref_unresolved"}


def test_take_without_any_forecast_reference_fails() -> None:
    inp = entry_day()
    take = dataclasses.replace(inp.boots[0].c1.decisions[0], forecast_input_ref="")
    fill = _one(replace_c1(inp, decisions=(take, inp.boots[0].c1.decisions[1])))
    assert _failing(_leg(fill, Leg.B)) == {"forecast_ref_missing"}


def test_unknown_standard_time_offset_fails_leg_b_by_name() -> None:
    fill = _one(dataclasses.replace(entry_day(), std_offsets={}))
    assert "std_offset_unknown" in _failing(_leg(fill, Leg.B))


def test_the_forecast_stations_offset_may_be_keyed_by_icao() -> None:
    inp = dataclasses.replace(entry_day(), std_offsets={"KLAX": -8.0})
    assert _leg(_one(inp), Leg.B).outcome is LegOutcome.PASS


@pytest.mark.parametrize("artefact", ["", "not-a-sha", "AB" * 32, "ab" * 31])
def test_artefact_sha256_must_be_a_lowercase_sha256(artefact: str) -> None:
    inp = entry_day()
    take, submit = (
        dataclasses.replace(d, artefact_sha256=artefact) for d in inp.boots[0].c1.decisions
    )
    assert _failing(_leg(_one(replace_c1(inp, decisions=(take, submit))), Leg.B)) == {
        "artefact_unresolved"
    }


def test_a_non_exit_record_without_a_frame_kind_fails() -> None:
    inp = entry_day()
    take, submit = inp.boots[0].c1.decisions
    bare = dataclasses.replace(submit, depth_ref="", quote_ref="")
    assert _failing(_leg(_one(replace_c1(inp, decisions=(take, bare))), Leg.B)) == {
        "frame_kind_missing"
    }


def test_an_exit_record_needs_no_frame_kind() -> None:
    assert _leg(_one(exit_day()), Leg.B).outcome is LegOutcome.PASS


def test_exit_without_its_frame_copy_fails_leg_b() -> None:
    inp = exit_day()
    stream = dataclasses.replace(inp.boots[0].stream(), frame_copies=())
    assert _failing(_leg(_one(replace_boot(inp, stream=lambda: stream)), Leg.B)) == {
        "frame_copy_missing"
    }


# -- leg I -----------------------------------------------------------------------------------


def test_leg_i_recomputed_fingerprint_matches_fill_by_fingerprint() -> None:
    assert _leg(_one(entry_day()), Leg.I).outcome is LegOutcome.PASS


def test_leg_i_mismatch_fails_intent_link_mismatch() -> None:
    inp = entry_day()
    wrong = dataclasses.replace(
        inp.exec, fill_by_fingerprint={f"{DAY.isoformat()}:{'0' * 64}": VSHA}
    )
    fill = _one(dataclasses.replace(inp, exec=wrong))

    assert _failing(_leg(fill, Leg.I)) == {"intent_link_mismatch"}
    assert "intent_link_mismatch" in fill.causes


def test_leg_i_index_pointing_at_another_venue_order_fails() -> None:
    inp = entry_day()
    key = next(iter(inp.exec.fill_by_fingerprint))
    wrong = dataclasses.replace(inp.exec, fill_by_fingerprint={key: "11" * 32})
    assert _failing(_leg(_one(dataclasses.replace(inp, exec=wrong)), Leg.I)) == {
        "intent_link_mismatch"
    }


def test_leg_i_fingerprint_is_recomputed_not_trusted_from_the_link() -> None:
    """A link whose stored fingerprint lies still joins on what its own fields hash to."""
    inp = entry_day()
    link = dataclasses.replace(inp.boots[0].c1.order_links[0], intent_fingerprint="0" * 64)
    assert _leg(_one(_with_links(inp, link)), Leg.I).outcome is LegOutcome.PASS

    skewed = dataclasses.replace(inp.boots[0].c1.order_links[0], px="0.99")
    assert _failing(_leg(_one(_with_links(inp, skewed)), Leg.I)) == {"intent_link_mismatch"}


def test_leg_i_day_is_the_intent_day_not_the_fill_day() -> None:
    """The key's day is the UTC day of the intent (the link), as ``record_fill`` derives it from
    ``intent_created_ns``. An intent armed just before midnight and filled just after it is keyed
    under the PREVIOUS day, while the fill itself belongs to the audited day."""
    prev = (DAY - dt.timedelta(days=1)).isoformat()
    inp = entry_day()
    fill = dataclasses.replace(inp.exec.fills[0], ts_event=DAY_START_NS + NS)
    link = dataclasses.replace(inp.boots[0].c1.order_links[0], ts_ns=DAY_START_NS - 2 * NS)
    keyed_on_intent = dataclasses.replace(
        inp.exec,
        fills=(fill,),
        fill_by_fingerprint={f"{prev}:{link.intent_fingerprint}": VSHA},
    )
    ok = _with_links(dataclasses.replace(inp, exec=keyed_on_intent), link)
    assert _leg(_one(ok), Leg.I).outcome is LegOutcome.PASS

    keyed_on_fill = dataclasses.replace(
        keyed_on_intent, fill_by_fingerprint={f"{DAY.isoformat()}:{link.intent_fingerprint}": VSHA}
    )
    bad = _with_links(dataclasses.replace(inp, exec=keyed_on_fill), link)
    assert _failing(_leg(_one(bad), Leg.I)) == {"intent_link_mismatch"}


# -- legs E and P ----------------------------------------------------------------------------


def test_leg_e_needs_a_filled_event_or_a_resolver_context() -> None:
    inp = replace_c1(entry_day(), lifecycle_events=())
    fill = _one(inp)
    assert _failing(_leg(fill, Leg.E)) == {"no_filled_event"}


def test_leg_e_filled_event_must_carry_the_same_trade_id() -> None:
    inp = entry_day()
    other = dataclasses.replace(inp.boots[0].c1.lifecycle_events[0], trade_id="OTHER")
    assert _failing(_leg(_one(replace_c1(inp, lifecycle_events=(other,))), Leg.E)) == {
        "no_filled_event"
    }


def test_resolver_fill_without_node_filled_event_passes_e_and_p() -> None:
    inp = replace_c1(entry_day(), lifecycle_events=(), position_marks=())
    inp = dataclasses.replace(inp, exec=dataclasses.replace(inp.exec, resolvers=(resolver(),)))
    fill = _one(inp)

    assert _leg(fill, Leg.E).outcome is LegOutcome.PASS
    assert _leg(fill, Leg.P).outcome is LegOutcome.PASS
    assert _leg(fill, Leg.E).findings == ()
    assert "fill_via_resolver" in fill.causes
    assert fill.causes == ("fill_via_resolver",)


def test_resolver_for_another_order_does_not_satisfy_leg_e() -> None:
    inp = replace_c1(entry_day(), lifecycle_events=())
    inp = dataclasses.replace(
        inp, exec=dataclasses.replace(inp.exec, resolvers=(resolver("O-OTHER"),))
    )
    assert _leg(_one(inp), Leg.E).outcome is LegOutcome.FAIL


def test_leg_p_node_mark_must_not_precede_the_fill() -> None:
    inp = entry_day()
    early = dataclasses.replace(inp.boots[0].c1.position_marks[0], ts_ns=FILL_TS - 1)
    fill = _one(replace_c1(inp, position_marks=(early,)))
    assert _failing(_leg(fill, Leg.P)) == {"no_position_mark"}


def test_leg_p_node_mark_must_name_the_fills_instrument() -> None:
    inp = entry_day()
    other = dataclasses.replace(
        inp.boots[0].c1.position_marks[0], instrument_id="other.POLYMARKET_US"
    )
    assert _leg(_one(replace_c1(inp, position_marks=(other,))), Leg.P).outcome is LegOutcome.FAIL


def test_tape_mark_satisfies_leg_p_without_node() -> None:
    inp = replace_c1(entry_day(), position_marks=())
    asks = {(INSTRUMENT, DAY_START_NS + 18 * 3600 * NS): 0.16}
    tape = DictTape(asks=asks)
    fill = _one(dataclasses.replace(inp, tape=tape))

    assert _leg(fill, Leg.P).outcome is LegOutcome.PASS
    assert fill.causes == ()


def test_tape_mark_before_the_fill_does_not_satisfy_leg_p() -> None:
    inp = replace_c1(entry_day(), position_marks=())
    tape = DictTape(asks={(INSTRUMENT, DAY_START_NS + 16 * 3600 * NS): 0.16})
    assert _leg(_one(dataclasses.replace(inp, tape=tape)), Leg.P).outcome is LegOutcome.FAIL


def test_a_tape_mark_before_a_later_fill_does_not_satisfy_that_fills_leg_p() -> None:
    """The position is held from the first fill, so 18:00 is marked; a second fill at 20:30 needs
    a mark at or after itself."""
    inp = replace_c1(entry_day(), position_marks=())
    later = ExecFill(
        "O-20261003-203000-L001-LAX-2",
        "88" * 32,
        "T7",
        INSTRUMENT,
        "BUY",
        "1",
        "0.2",
        DAY_START_NS + 20 * H + 1800 * NS,
        True,
    )
    inp = dataclasses.replace(
        inp,
        exec=dataclasses.replace(inp.exec, fills=(*inp.exec.fills, later)),
        tape=DictTape(asks={(INSTRUMENT, DAY_START_NS + 18 * H): 0.16}),
    )
    first, second = audit_fills(inp)

    assert _leg(first, Leg.P).outcome is LegOutcome.PASS
    assert _leg(second, Leg.P).outcome is LegOutcome.FAIL


# -- leg S -----------------------------------------------------------------------------------


def _s_inputs(
    now_after_end_s: int, *, offset: float = -8.0, settlements: tuple[SettlementRecord, ...] = ()
) -> AuditInputs:
    end_ns = _climate_day_end_ns(DAY, offset)
    return dataclasses.replace(
        entry_day(),
        settlements=settlements,
        now_ns=end_ns + now_after_end_s * NS,
        std_offsets={"KLAX": offset, "LAX": offset},
    )


def test_settlement_pending_is_inconclusive_overdue_fails() -> None:
    pending = _leg(_one(_s_inputs(10 * 3600)), Leg.S)
    assert pending.outcome is LegOutcome.PENDING
    assert _causes(pending) == {"settlement_pending"}

    overdue = _leg(_one(_s_inputs(40 * 3600)), Leg.S)
    assert overdue.outcome is LegOutcome.FAIL
    assert _failing(overdue) == {"settlement_missing"}


def test_leg_s_is_pending_until_36_hours_after_the_climate_day_ended() -> None:
    assert _leg(_one(_s_inputs(36 * 3600 - 1)), Leg.S).outcome is LegOutcome.PENDING
    assert _leg(_one(_s_inputs(36 * 3600)), Leg.S).outcome is LegOutcome.FAIL


def test_leg_s_overdue_48_hours_adds_the_alert_cause() -> None:
    between = _one(_s_inputs(47 * 3600 + 3599))
    assert "settlement_missing_alert_due" not in between.causes
    assert "settlement_missing" in between.causes

    alerted = _one(_s_inputs(48 * 3600))
    assert {"settlement_missing", "settlement_missing_alert_due"} <= set(alerted.causes)
    assert _leg(alerted, Leg.S).outcome is LegOutcome.FAIL


def test_leg_s_ended_is_end_of_climate_day_in_local_standard_time() -> None:
    """The end is local STANDARD midnight at the next date: -8 h, never DST (a July day under PDT
    would end an hour earlier). Pinned against ``ingest.records``' own derivation."""
    summer = dt.date(2026, 7, 15)
    end_ns = _climate_day_end_ns(summer, -8.0)
    assert end_ns == int(dt.datetime(2026, 7, 16, 8, tzinfo=dt.UTC).timestamp()) * NS

    take = decision_view("Take", "take", climate_day=summer.isoformat())
    inp = entry_day()
    submit = decision_view(
        "TrySubmit", "submitted", decision_id=take.decision_id, climate_day=summer.isoformat()
    )
    inp = replace_c1(inp, decisions=(take, submit), order_links=(link_view(take.decision_id),))
    just_before = dataclasses.replace(inp, settlements=(), now_ns=end_ns + 36 * 3600 * NS - 1)
    just_after = dataclasses.replace(inp, settlements=(), now_ns=end_ns + 36 * 3600 * NS)
    assert _leg(_one(just_before), Leg.S).outcome is LegOutcome.PENDING
    assert _leg(_one(just_after), Leg.S).outcome is LegOutcome.FAIL


def test_leg_s_passes_with_a_settlement_record_for_the_station_day() -> None:
    record = SettlementRecord(STATION, DAY.isoformat(), 84, "NWS_CLI", VSHA, 1)
    assert (
        _leg(_one(_s_inputs(100 * 3600, settlements=(record,))), Leg.S).outcome is LegOutcome.PASS
    )


def test_a_settlement_for_another_station_or_day_does_not_count() -> None:
    wrong = (
        SettlementRecord("SFO", DAY.isoformat(), 84, "NWS_CLI", VSHA, 1),
        SettlementRecord(STATION, (DAY + dt.timedelta(days=1)).isoformat(), 84, "NWS_CLI", VSHA, 1),
    )
    assert _leg(_one(_s_inputs(100 * 3600, settlements=wrong)), Leg.S).outcome is LegOutcome.FAIL


def test_leg_s_unknown_offset_fails_by_name() -> None:
    inp = dataclasses.replace(_s_inputs(100 * 3600), std_offsets={})
    assert "std_offset_unknown" in _failing(_leg(_one(inp), Leg.S))


def test_leg_s_offset_may_be_keyed_by_the_icao_station() -> None:
    inp = dataclasses.replace(_s_inputs(100 * 3600), std_offsets={"KLAX": -8.0})
    assert _leg(_one(inp), Leg.S).outcome is LegOutcome.FAIL  # offset known: it is just overdue


# -- drill and canary ------------------------------------------------------------------------


def test_drill_fills_joined_and_marked() -> None:
    inp = entry_day()
    take, submit = (dataclasses.replace(d, drill=True) for d in inp.boots[0].c1.decisions)
    fill = _one(replace_c1(inp, decisions=(take, submit)))

    assert fill.drill is True
    assert _leg(fill, Leg.D).outcome is LegOutcome.PASS


def test_canary_fills_report_their_source() -> None:
    inp = entry_day()
    link = dataclasses.replace(inp.boots[0].c1.order_links[0], source="canary")
    fill = _one(_with_links(inp, link))
    assert fill.source == "canary"


# -- leg O -----------------------------------------------------------------------------------


def _trysubmit_only(
    *, ended: bool = True, linked: bool = True, evidence: bool = True
) -> AuditInputs:
    inp = entry_day()
    take, submit = inp.boots[0].c1.decisions
    links = inp.boots[0].c1.order_links if linked else ()
    out = replace_c1(inp, decisions=(take, submit), order_links=links, lifecycle_events=())
    out = replace_boot(out, ended=ended)
    if not evidence:
        out = dataclasses.replace(
            out, exec=dataclasses.replace(out.exec, orders=(), resolvers=(), fills=())
        )
    return out


def test_trysubmit_linked() -> None:
    result = leg_o(_trysubmit_only())

    assert result.leg is Leg.O
    assert result.outcome is LegOutcome.PASS
    assert _causes(result) == set()


def test_trysubmit_refused_after_trysubmit_by_guard_entryveto() -> None:
    inp = _trysubmit_only(linked=False, evidence=False)
    take = inp.boots[0].c1.decisions[0]
    veto = decision_view("EntryVeto", "capture_gap", decision_id=take.decision_id)
    result = leg_o(with_decisions(inp, veto))

    assert result.outcome is LegOutcome.PASS
    assert _causes(result) == set()


def test_a_non_guard_entryveto_does_not_explain_an_unlinked_trysubmit() -> None:
    """Leg O guard exclusion: FQ's own VetoReason EntryVetos are not the capture guard's own."""
    inp = _trysubmit_only(linked=False, evidence=False)
    take = inp.boots[0].c1.decisions[0]
    veto = decision_view("EntryVeto", "registry_halted", decision_id=take.decision_id)
    result = leg_o(with_decisions(inp, veto))

    assert result.outcome is LegOutcome.FAIL
    assert _failing(result) == {"trysubmit_unlinked"}


def test_trysubmit_instrument_vanished_is_refused_after_trysubmit() -> None:
    inp = _trysubmit_only(linked=False, evidence=False)
    take = inp.boots[0].c1.decisions[0]
    refuse = decision_view(
        "Refuse", "instrument_vanished_after_trysubmit", decision_id=take.decision_id
    )
    assert leg_o(with_decisions(inp, refuse)).outcome is LegOutcome.PASS


def test_a_refuse_with_another_reason_does_not_explain_an_unlinked_trysubmit() -> None:
    inp = _trysubmit_only(linked=False, evidence=False)
    take = inp.boots[0].c1.decisions[0]
    refuse = decision_view("Refuse", "ev_below_floor", decision_id=take.decision_id)
    assert _failing(leg_o(with_decisions(inp, refuse))) == {"trysubmit_unlinked"}


def test_trysubmit_unlinked_pending_while_boot_running() -> None:
    result = leg_o(_trysubmit_only(ended=False, linked=False, evidence=False))

    assert result.outcome is LegOutcome.PENDING
    assert _causes(result) == {"order_pending"}


def test_trysubmit_unlinked_fails_after_boot_ended() -> None:
    result = leg_o(_trysubmit_only(ended=True, linked=False, evidence=False))

    assert result.outcome is LegOutcome.FAIL
    assert _failing(result) == {"trysubmit_unlinked"}


def test_crash_between_link_and_submit_classified_never_submitted() -> None:
    result = leg_o(_trysubmit_only(ended=True, linked=True, evidence=False))

    assert result.outcome is LegOutcome.PASS
    assert [(f.outcome, f.cause) for f in result.findings] == [(LegOutcome.INFO, "never_submitted")]


def test_a_linked_trysubmit_with_no_evidence_in_a_running_boot_is_still_linked() -> None:
    result = leg_o(_trysubmit_only(ended=False, linked=True, evidence=False))
    assert result.outcome is LegOutcome.PASS
    assert result.findings == ()


def test_a_log_line_is_evidence_of_submission() -> None:
    inp = _trysubmit_only(ended=True, linked=True, evidence=False)
    inp = replace_boot(inp, markers=markers_with(submitted=[COID]))
    assert leg_o(inp).findings == ()


def test_lifecycle_event_is_evidence_of_submission() -> None:
    inp = _trysubmit_only(ended=True, linked=True, evidence=False)
    filled = entry_day().boots[0].c1.lifecycle_events
    assert leg_o(replace_c1(inp, lifecycle_events=filled)).findings == ()


def test_every_exec_store_order_record_has_order_link() -> None:
    inp = entry_day()
    stray = ExecOrder("O-20261003-170001-L001-LAX-9", "34" * 32)
    inp = dataclasses.replace(
        inp, exec=dataclasses.replace(inp.exec, orders=(*inp.exec.orders, stray))
    )
    result = leg_o(inp)

    assert result.outcome is LegOutcome.FAIL
    assert _failing(result) == {"order_without_order_link"}
    assert result.findings[0].subject == "O-20261003-170001-L001-LAX-9"


def test_exec_order_of_another_day_is_not_census_material() -> None:
    inp = entry_day()
    old = ExecOrder("O-20261001-170001-L001-LAX-9", "34" * 32)
    inp = dataclasses.replace(
        inp, exec=dataclasses.replace(inp.exec, orders=(*inp.exec.orders, old))
    )
    assert leg_o(inp).outcome is LegOutcome.PASS


def test_exec_order_with_an_undated_id_is_still_checked() -> None:
    inp = entry_day()
    odd = ExecOrder("manual-order", "34" * 32)
    inp = dataclasses.replace(
        inp, exec=dataclasses.replace(inp.exec, orders=(*inp.exec.orders, odd))
    )
    assert _failing(leg_o(inp)) == {"order_without_order_link"}


def test_resolver_context_created_on_the_day_needs_an_order_link() -> None:
    inp = entry_day()
    ctx = resolver("O-NOLINK", created_ns=FILL_TS)
    inp = dataclasses.replace(inp, exec=dataclasses.replace(inp.exec, resolvers=(ctx,)))
    assert _failing(leg_o(inp)) == {"resolver_without_order_link"}


def test_resolver_context_created_on_another_day_is_ignored() -> None:
    inp = entry_day()
    ctx = resolver("O-NOLINK", created_ns=FILL_TS - 2 * 86_400 * NS)
    inp = dataclasses.replace(inp, exec=dataclasses.replace(inp.exec, resolvers=(ctx,)))
    assert leg_o(inp).outcome is LegOutcome.PASS


@pytest.mark.parametrize("which", ["submitted", "denied"])
def test_order_log_lines_need_an_order_link(which: str) -> None:
    inp = replace_boot(entry_day(), markers=markers_with(**{which: ["O-NOLINK"]}))
    assert _failing(leg_o(inp)) == {"log_order_without_order_link"}


def test_order_log_line_naming_a_streamed_order_passes() -> None:
    inp = replace_boot(entry_day(), markers=markers_with(submitted=[COID], denied=[COID]))
    assert leg_o(inp).outcome is LegOutcome.PASS


def test_a_leg_o_with_no_orders_at_all_passes() -> None:
    inp = entry_day()
    inp = dataclasses.replace(
        inp, exec=dataclasses.replace(inp.exec, orders=(), resolvers=(), fills=())
    )
    inp = replace_c1(inp, decisions=(), order_links=())
    assert leg_o(inp).outcome is LegOutcome.PASS


# -- leg F -----------------------------------------------------------------------------------


def _scan_with(*fills: OrderFilledLine, total: int | None = None) -> NodeLogScan:
    kwargs: dict[str, Any] = {
        name: 0
        for name in (
            "line_count",
            "decision_line_count",
            "entry_total",
            "instance_id_total",
            "disposed_count",
            "fill_total",
            "writer_failure_total",
            "unparseable_total",
            "duplicate_decision_count",
            "duplicate_evaluation_count",
        )
    }
    return NodeLogScan(
        **{**kwargs, "fill_total": len(fills) if total is None else total},
        kind_counts={},
        entry_lines=(),
        instance_ids=(),
        node_disposed=True,
        fills=tuple(fills),
        writer_failures=(),
        unparseable=(),
        marker_counts={},
        last_line_ts_ns=None,
    )


def _node_fill(coid: str = COID, ts: int = FILL_TS) -> OrderFilledLine:
    return OrderFilledLine(1, ts, INSTRUMENT, coid, "venue-raw", TRADE_ID, ts)


def test_fill_by_day_positive_control_matches_fill_keys() -> None:
    assert leg_f(entry_day()).outcome is LegOutcome.PASS


def test_fill_missing_from_the_day_index_fails() -> None:
    inp = entry_day()
    gone = dataclasses.replace(inp.exec, fill_by_day={DAY.isoformat(): ()})
    result = leg_f(dataclasses.replace(inp, exec=gone))

    assert _failing(result) == {"fill_by_day_mismatch"}


def test_index_entry_without_a_fill_record_fails() -> None:
    inp = entry_day()
    extra = dataclasses.replace(inp.exec, fill_by_day={DAY.isoformat(): (VSHA, "99" * 32)})
    assert _failing(leg_f(dataclasses.replace(inp, exec=extra))) == {"fill_by_day_mismatch"}


def test_index_entry_whose_fill_is_stamped_on_another_day_is_filtered() -> None:
    inp = entry_day()
    other = ExecFill(
        "O-20261002-170000-L001-LAX-1",
        "77" * 32,
        "T2",
        INSTRUMENT,
        "BUY",
        "1",
        "0.1",
        FILL_TS - 86_400 * NS,
        True,
    )
    exec_view = dataclasses.replace(
        inp.exec, fills=(*inp.exec.fills, other), fill_by_day={DAY.isoformat(): (VSHA, "77" * 32)}
    )
    assert leg_f(dataclasses.replace(inp, exec=exec_view)).outcome is LegOutcome.PASS


def test_node_log_fill_without_an_exec_fill_fails() -> None:
    inp = replace_boot(entry_day(), scan=_scan_with(_node_fill(), _node_fill("O-GHOST")))
    result = leg_f(inp)

    assert _failing(result) == {"node_fill_without_exec_fill"}
    assert result.findings[0].subject == "O-GHOST"


def test_node_log_fills_that_are_exec_fills_pass() -> None:
    assert (
        leg_f(replace_boot(entry_day(), scan=_scan_with(_node_fill()))).outcome is LegOutcome.PASS
    )


def test_node_log_fill_of_another_day_is_not_checked() -> None:
    old = _node_fill("O-GHOST", ts=FILL_TS - 2 * 86_400 * NS)
    assert (
        leg_f(replace_boot(entry_day(), scan=_scan_with(_node_fill(), old))).outcome
        is LegOutcome.PASS
    )


def test_extra_exec_fill_needs_a_resolver_context() -> None:
    inp = replace_boot(entry_day(), scan=_scan_with())
    result = leg_f(inp)
    assert _failing(result) == {"exec_fill_unexplained"}

    explained = dataclasses.replace(
        inp, exec=dataclasses.replace(inp.exec, resolvers=(resolver(),))
    )
    assert leg_f(explained).outcome is LegOutcome.PASS


def test_a_boot_without_a_scan_cannot_explain_but_does_not_invent_an_extra() -> None:
    """Leg F reads the node-log fills only of boots that HAVE a scan; a missing log is ERROR
    elsewhere (node_log_missing), so here the exec fill is simply not cross-checked."""
    assert leg_f(replace_boot(entry_day(), scan=None)).outcome is LegOutcome.PASS


def test_a_truncated_node_fill_list_is_reported_as_info() -> None:
    inp = replace_boot(entry_day(), scan=_scan_with(_node_fill(), total=500))
    result = leg_f(inp)
    assert result.outcome is LegOutcome.PASS
    assert [(f.outcome, f.cause) for f in result.findings] == [
        (LegOutcome.INFO, "node_fills_truncated")
    ]


# -- leg R6 ----------------------------------------------------------------------------------


def _refusals(n: int, *, resolved: int) -> tuple[tuple[Any, ...], DictTape]:
    decisions = []
    rows: dict[tuple[str, str, int], Mapping[str, Any]] = {}
    for i in range(n):
        ts = 1_000 + i
        decisions.append(
            decision_view(
                "Refuse",
                "ev_below_floor",
                eval_seq=i,
                depth_ref=frame_ref_of("depth10", INSTRUMENT, ts),
                quote_ref="",
            )
        )
        if i < resolved:
            rows[("depth10", INSTRUMENT, ts)] = {"ts_event": ts}
    return tuple(decisions), DictTape(rows=rows)


def test_refusal_ref_resolution_fraction_reported_and_alerted_below_baseline() -> None:
    decisions, tape = _refusals(100, resolved=90)
    inp = dataclasses.replace(replace_c1(entry_day(), decisions=decisions), tape=tape)
    result = leg_r6(inp)

    assert result.leg is Leg.R6
    assert result.metrics["refusal_frame_ref_resolved_frac"] == pytest.approx(0.9)
    assert result.outcome is LegOutcome.INFO  # never FAIL: refusals do not enter a fill's join
    assert _causes(result) == {"refusal_refs_unresolved"}


def test_refusal_refs_at_the_baseline_are_not_alerted() -> None:
    decisions, tape = _refusals(1000, resolved=924)
    result = leg_r6(dataclasses.replace(replace_c1(entry_day(), decisions=decisions), tape=tape))

    assert result.outcome is LegOutcome.PASS
    assert result.findings == ()
    assert result.metrics["refusal_frame_ref_resolved_frac"] == pytest.approx(0.924)


def test_refusal_refs_exactly_at_the_baseline_are_not_alerted() -> None:
    decisions, tape = _refusals(1000, resolved=923)
    result = leg_r6(dataclasses.replace(replace_c1(entry_day(), decisions=decisions), tape=tape))
    assert result.outcome is LegOutcome.PASS


def test_refusal_refs_just_under_the_baseline_are_alerted() -> None:
    decisions, tape = _refusals(1000, resolved=922)
    result = leg_r6(dataclasses.replace(replace_c1(entry_day(), decisions=decisions), tape=tape))
    assert result.outcome is LegOutcome.INFO


def test_refusal_refs_only_count_refusal_kinds() -> None:
    """Takes, TrySubmits and EntryVetos continue a Take (they share its frame copy): not counted."""
    inp = replace_c1(entry_day(), decisions=entry_day().boots[0].c1.decisions)
    result = leg_r6(inp)
    assert result.outcome is LegOutcome.PASS
    assert "refusal_frame_ref_resolved_frac" not in result.metrics


def test_refusal_without_a_frame_reference_counts_as_unresolved() -> None:
    bare = decision_view("NotExecutable", "no_ask", depth_ref="", quote_ref="")
    result = leg_r6(replace_c1(entry_day(), decisions=(bare,)))
    assert result.metrics["refusal_frame_ref_resolved_frac"] == 0.0
    assert result.outcome is LegOutcome.INFO


def test_refusal_quote_reference_resolves_through_the_quote_table() -> None:
    ref = frame_ref_of("quote", INSTRUMENT, 5)
    refusal = decision_view("NotDPlus1", "d0", depth_ref="", quote_ref=ref)
    tape = DictTape(rows={("quote", INSTRUMENT, 5): {"ts_event": 5}})
    inp = dataclasses.replace(replace_c1(entry_day(), decisions=(refusal,)), tape=tape)
    assert leg_r6(inp).metrics["refusal_frame_ref_resolved_frac"] == 1.0


# -- tape marks ------------------------------------------------------------------------------


def _hour_asks(
    instrument: str, hours: range, value: float = 0.2
) -> dict[tuple[str, int], float | None]:
    return {(instrument, DAY_START_NS + h * H): value for h in hours}


def test_tape_marks_for_a_nonzero_net_position_at_every_whole_hour() -> None:
    inp = dataclasses.replace(entry_day(), tape=DictTape(asks=_hour_asks(INSTRUMENT, range(24))))
    marks = tape_marks(inp)

    assert all(isinstance(m, TapeMark) for m in marks)
    held = {m.hour for m in marks}
    assert held == set(range(18, 24))  # the fill is at 17:00:05Z; marks from the next whole hour
    assert {m.instrument_id for m in marks} == {INSTRUMENT}
    assert {m.net_qty for m in marks} == {1}
    assert {m.best_ask for m in marks} == {0.2}


def test_tape_marks_are_ordered_by_instrument_then_hour() -> None:
    inp = dataclasses.replace(entry_day(), tape=DictTape(asks=_hour_asks(INSTRUMENT, range(24))))
    marks = tape_marks(inp)
    assert [m.hour for m in marks] == sorted(m.hour for m in marks)


def test_tape_mark_keeps_a_none_best_ask() -> None:
    inp = dataclasses.replace(entry_day(), tape=DictTape())
    marks = tape_marks(inp)
    assert marks and all(m.best_ask is None for m in marks)


def test_tape_marks_net_a_no_leg_fill_against_the_yes_leg() -> None:
    """A NO holding is a short YES (ARCH-0 AC 22): YES BUY +1 and NO BUY -1 net to zero."""
    inp = entry_day()
    no_fill = ExecFill(
        "O-NO", "55" * 32, "T9", NO_INSTRUMENT, "BUY", "1", "0.1", FILL_TS + NS, True
    )
    inp = dataclasses.replace(
        inp,
        exec=dataclasses.replace(inp.exec, fills=(*inp.exec.fills, no_fill)),
        tape=DictTape(asks=_hour_asks(INSTRUMENT, range(24))),
    )
    assert tape_marks(inp) == ()


def test_tape_marks_a_lone_no_leg_holding_marks_the_yes_leg_book_with_a_negative_net() -> None:
    inp = entry_day()
    no_fill = ExecFill("O-NO", "55" * 32, "T9", NO_INSTRUMENT, "BUY", "2", "0.1", FILL_TS, True)
    inp = dataclasses.replace(
        inp,
        exec=dataclasses.replace(inp.exec, fills=(no_fill,)),
        tape=DictTape(asks=_hour_asks(INSTRUMENT, range(24))),
    )
    marks = tape_marks(inp)
    assert {m.instrument_id for m in marks} == {INSTRUMENT}
    assert {m.net_qty for m in marks} == {-2}


def test_a_closed_position_has_no_marks_after_the_close() -> None:
    inp = entry_day()
    sell = ExecFill(
        "O-S", "66" * 32, "T8", INSTRUMENT, "SELL", "1", "0.2", DAY_START_NS + 20 * H + NS, True
    )
    inp = dataclasses.replace(
        inp,
        exec=dataclasses.replace(inp.exec, fills=(*inp.exec.fills, sell)),
        tape=DictTape(asks=_hour_asks(INSTRUMENT, range(24))),
    )
    assert {m.hour for m in tape_marks(inp)} == {18, 19, 20}


def test_no_fills_gives_no_tape_marks() -> None:
    inp = entry_day()
    assert tape_marks(dataclasses.replace(inp, exec=dataclasses.replace(inp.exec, fills=()))) == ()


# -- purity and layering ---------------------------------------------------------------------


def test_the_module_imports_no_adapter_and_does_no_io() -> None:
    tree = ast.parse(Path(legs_mod.__file__ or "").read_text(encoding="utf-8"))
    imported = {(n.module or "") for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    assert not [m for m in imported if m.startswith("breezy.adapters")]
    assert not {"os", "subprocess", "socket", "pathlib", "time", "datetime.now"} & imported
    calls = {
        n.func.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert not {"open", "print", "exec", "eval"} & calls


def test_audit_fills_does_not_mutate_its_input() -> None:
    inp = entry_day()
    before = repr(inp.boots[0].c1) + repr(inp.exec)
    audit_fills(inp)
    assert repr(inp.boots[0].c1) + repr(inp.exec) == before


def test_tape_marks_and_legs_are_deterministic() -> None:
    inp = dataclasses.replace(entry_day(), tape=DictTape(asks=_hour_asks(INSTRUMENT, range(24))))
    assert audit_fills(inp) == audit_fills(inp)
    assert tape_marks(inp) == tape_marks(inp)
    assert leg_o(inp) == leg_o(inp)


# -- pins to the code the legs mirror ------------------------------------------------------------


def test_trysubmit_reason_constants_equal_the_guarded_strategys() -> None:
    from breezy.strategy.autonomy_capture import guarded_strategy

    assert legs_mod.REASON_SUBMITTED == guarded_strategy.REASON_SUBMITTED
    assert legs_mod.REASON_INSTRUMENT_VANISHED == guarded_strategy.REASON_INSTRUMENT_VANISHED


@pytest.mark.parametrize("offset", [-8.0, -6.0, -5.0, 0.0, 5.5])
@pytest.mark.parametrize(
    "day", [dt.date(2026, 3, 8), dt.date(2026, 3, 9), dt.date(2026, 7, 15), dt.date(2026, 11, 1)]
)
def test_climate_day_end_equals_the_ingest_derivation(day: dt.date, offset: float) -> None:
    from breezy.analysis.capture_audit_fill_support import climate_day_end_ns

    assert climate_day_end_ns(day, offset) == _climate_day_end_ns(day, offset)


def test_the_support_module_imports_no_adapter() -> None:
    from breezy.analysis import capture_audit_fill_support as support

    tree = ast.parse(Path(support.__file__ or "").read_text(encoding="utf-8"))
    imported = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not [m for m in imported if m.startswith("breezy.adapters")]
