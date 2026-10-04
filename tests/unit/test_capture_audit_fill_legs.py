"""AUT-1 WP5 stage 2b W1: legs L, D and B of the per-fill audit (plan r12 3.11.2).

Every leg is a pure function over one ``AuditInputs``. Each test changes the one thing it varies
from ``entry_day()`` / ``exit_day()`` and reads the leg outcome and the finding cause.
"""

import dataclasses
from collections.abc import Mapping
from typing import Any

import pytest

from breezy.analysis.capture_audit_fill_legs import (
    audit_fills,
)
from breezy.analysis.capture_audit_input_types import AuditInputs
from breezy.analysis.capture_audit_model import (
    Leg,
    LegOutcome,
)
from breezy.persistence.autonomy.capture_ids import (
    compute_orphan_decision_id,
    forecast_ref_of,
)
from breezy.persistence.autonomy.capture_records import FrameCopy, make_record
from tests.support import capture_audit_fixtures as base
from tests.support.capture_audit_w1_fixtures import (
    COID,
    DEPTH_BODY,
    EVAL_NS,
    FILL_TS,
    FRAME_TS,
    INSTRUMENT,
    QUOTE_BODY,
    TRADE_ID,
    DictTape,
    decision_view,
    entry_day,
    exit_day,
    link_view,
    replace_boot,
    replace_c1,
)
from tests.support.capture_audit_w1_fixtures import (
    causes_of as _causes,
)
from tests.support.capture_audit_w1_fixtures import (
    failing_of as _failing,
)
from tests.support.capture_audit_w1_fixtures import (
    leg_of as _leg,
)
from tests.support.capture_audit_w1_fixtures import (
    one_fill as _one,
)
from tests.support.capture_audit_w1_fixtures import (
    with_links as _with_links,
)
from tests.unit.capture_reader_support import HOUR_NS

NS = base.NS
DAY = base.DAY
H = 3600 * NS
FILL_KINDS = ("depth10", "quote")


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


# -- leg B no-lookahead (S2-R34) and the minimal frame shape (S2-R39) --------------------------


def _retime_take(inp: AuditInputs, **over: Any) -> AuditInputs:
    take, submit = inp.boots[0].c1.decisions
    return replace_c1(inp, decisions=(dataclasses.replace(take, **over), submit))


def test_a_forecast_available_after_the_evaluation_is_a_lookahead() -> None:
    ref = forecast_ref_of("KLAX", 100 * HOUR_NS, EVAL_NS + 1)
    fill = _one(_retime_take(entry_day(), forecast_input_ref=ref))
    assert "forecast_ref_lookahead" in _failing(_leg(fill, Leg.B))
    assert "forecast_ref_lookahead" in fill.causes


def test_a_forecast_available_at_the_evaluation_instant_is_not_a_lookahead() -> None:
    ref = forecast_ref_of("KLAX", 100 * HOUR_NS, EVAL_NS)
    fill = _one(_retime_take(entry_day(), forecast_input_ref=ref))
    assert "forecast_ref_lookahead" not in _causes(_leg(fill, Leg.B))


def test_a_frame_stamped_after_the_evaluation_is_a_lookahead() -> None:
    inp = _retime_take(entry_day(), eval_ns=FRAME_TS - 1)
    assert "frame_ref_lookahead" in _failing(_leg(_one(inp), Leg.B))


def test_a_frame_stamped_at_the_evaluation_instant_is_not_a_lookahead() -> None:
    inp = _retime_take(entry_day(), eval_ns=FRAME_TS)
    assert _leg(_one(inp), Leg.B).outcome is LegOutcome.PASS


@pytest.mark.parametrize(
    ("frame_kind", "partial"),
    [
        ("depth10", {"ts_event": FRAME_TS}),
        ("depth10", {"ts_event": FRAME_TS, "bids": DEPTH_BODY["bids"]}),
        ("quote", {"ts_event": FRAME_TS, "ask": "0.15"}),
        ("quote", {"bid": "0.14", "ask": "0.15"}),
    ],
)
def test_a_copy_body_missing_a_frame_key_never_equals_the_tape(
    frame_kind: str, partial: Mapping[str, Any]
) -> None:
    """A subset body would equal any tape row on its keys alone."""
    inp = entry_day(frame_kind)
    stream = inp.boots[0].stream()
    (copy,) = stream.frame_copies
    thin = make_record(
        FrameCopy,
        ts_event=FRAME_TS,
        ts_init=EVAL_NS,
        schema="capture_frame_copy/v1",
        decision_id=copy.decision_id,
        frame_kind=frame_kind,
        instrument=INSTRUMENT,
        frame_ts_event=FRAME_TS,
        frame_body=dict(partial),
    )
    thinned = dataclasses.replace(stream, frame_copies=(thin,))
    inp = dataclasses.replace(
        replace_boot(inp, stream=lambda: thinned), tape=_tape_with(frame_kind, partial)
    )
    assert _failing(_leg(_one(inp), Leg.B)) == {"frame_copy_mismatch"}
