"""AUT-1 WP5 stage 2b W1: census legs O, F and R6, tape marks and purity pins (S2-R38 split)."""

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
    AuditInputError,
    Leg,
    LegOutcome,
    TapeMark,
)
from breezy.ingest.records import _climate_day_end_ns
from breezy.persistence.autonomy.capture_ids import (
    frame_ref_of,
)
from tests.support import capture_audit_fixtures as base
from tests.support.capture_audit_w1_fixtures import (
    COID,
    DAY_START_NS,
    FILL_TS,
    INSTRUMENT,
    NO_INSTRUMENT,
    VSHA,
    DictTape,
    decision_view,
    entry_day,
    markers_with,
    node_fill,
    replace_boot,
    replace_c1,
    resolver,
    scan_with,
    with_decisions,
)
from tests.support.capture_audit_w1_fixtures import (
    causes_of as _causes,
)
from tests.support.capture_audit_w1_fixtures import (
    failing_of as _failing,
)

NS = base.NS
DAY = base.DAY
H = 3600 * NS
FILL_KINDS = ("depth10", "quote")


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
    result = leg_f(dataclasses.replace(inp, exec=exec_view))

    assert result.outcome is LegOutcome.PASS
    assert [(f.outcome, f.cause, f.subject) for f in result.findings] == [
        (LegOutcome.INFO, "fill_by_day_entry_cross_day", "77" * 32)
    ]


def test_node_log_fill_without_an_exec_fill_fails() -> None:
    inp = replace_boot(entry_day(), scan=scan_with(node_fill(), node_fill("O-GHOST")))
    result = leg_f(inp)

    assert _failing(result) == {"node_fill_without_exec_fill"}
    assert result.findings[0].subject == "O-GHOST"


def test_node_log_fills_that_are_exec_fills_pass() -> None:
    assert leg_f(replace_boot(entry_day(), scan=scan_with(node_fill()))).outcome is LegOutcome.PASS


def test_node_log_fill_of_another_day_is_not_checked() -> None:
    old = node_fill("O-GHOST", ts=FILL_TS - 2 * 86_400 * NS)
    assert (
        leg_f(replace_boot(entry_day(), scan=scan_with(node_fill(), old))).outcome
        is LegOutcome.PASS
    )


def test_extra_exec_fill_needs_a_resolver_context() -> None:
    inp = replace_boot(entry_day(), scan=scan_with())
    result = leg_f(inp)
    assert _failing(result) == {"exec_fill_unexplained"}

    explained = dataclasses.replace(
        inp, exec=dataclasses.replace(inp.exec, resolvers=(resolver(),))
    )
    assert leg_f(explained).outcome is LegOutcome.PASS


def test_a_day_with_no_boot_scan_is_inconclusive_not_a_pass() -> None:
    """S2-R36: without a scan the node-log fills cannot be cross-checked, so leg F cannot pass."""
    result = leg_f(replace_boot(entry_day(), scan=None))

    assert result.outcome is LegOutcome.PENDING
    assert _causes(result) == {"node_scan_missing"}


def test_a_truncated_node_fill_list_is_inconclusive_not_info() -> None:
    """S2-R36: a truncated scan cannot prove the census, so the leg is pending, never a pass."""
    inp = replace_boot(entry_day(), scan=scan_with(node_fill(), total=500))
    result = leg_f(inp)

    assert result.outcome is LegOutcome.PENDING
    assert [(f.outcome, f.cause) for f in result.findings] == [
        (LegOutcome.PENDING, "exec_fill_census_truncated")
    ]


def test_a_truncated_scan_still_reports_a_node_fill_without_an_exec_fill() -> None:
    inp = replace_boot(entry_day(), scan=scan_with(node_fill(), node_fill("O-GHOST"), total=500))
    result = leg_f(inp)

    assert result.outcome is LegOutcome.FAIL
    assert _causes(result) == {"node_fill_without_exec_fill", "exec_fill_census_truncated"}


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


def test_tape_marks_ignore_a_fill_stamped_after_the_mark_hour() -> None:
    inp = entry_day()
    later = ExecFill(
        "O-L", "44" * 32, "T5", INSTRUMENT, "BUY", "2", "0.2", DAY_START_NS + 20 * H + NS, True
    )
    inp = dataclasses.replace(
        inp,
        exec=dataclasses.replace(inp.exec, fills=(*inp.exec.fills, later)),
        tape=DictTape(asks=_hour_asks(INSTRUMENT, range(24))),
    )
    nets = {m.hour: m.net_qty for m in tape_marks(inp)}
    assert nets[19] == 1 and nets[20] == 1 and nets[21] == 3


@pytest.mark.parametrize(
    ("over", "cause"),
    [
        ({"order_side": "BUY_SHORT"}, "fill_side_unknown"),
        ({"cumulative_qty": "1.5"}, "fill_qty_fractional"),
    ],
)
def test_tape_marks_skip_a_defective_fill_instead_of_raising_or_truncating(
    over: dict[str, Any], cause: str
) -> None:
    inp = entry_day()
    odd = dataclasses.replace(inp.exec.fills[0], **over)
    inp = dataclasses.replace(
        inp,
        exec=dataclasses.replace(inp.exec, fills=(odd,)),
        tape=DictTape(asks=_hour_asks(INSTRUMENT, range(24))),
    )
    assert tape_marks(inp) == ()


def test_an_undecodable_fill_quantity_is_still_an_input_error() -> None:
    inp = entry_day()
    odd = dataclasses.replace(inp.exec.fills[0], cumulative_qty="abc")
    inp = dataclasses.replace(inp, exec=dataclasses.replace(inp.exec, fills=(odd,)))
    with pytest.raises(AuditInputError) as err:
        tape_marks(inp)
    assert err.value.cause == "exec_record_undecodable"


def test_leg_r6_with_no_refusals_carries_no_metric_and_the_audit_tolerates_it() -> None:
    result = leg_r6(entry_day())
    assert result.outcome is LegOutcome.PASS and dict(result.metrics) == {}
    from breezy.analysis.capture_audit_model import METRIC_NAMES

    assert set(result.metrics) <= METRIC_NAMES


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
