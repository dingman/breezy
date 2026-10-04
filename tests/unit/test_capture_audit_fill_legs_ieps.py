"""AUT-1 WP5 stage 2b W1: legs I, E, P and S, drill and canary (S2-R38 split)."""

import dataclasses
import datetime as dt
from typing import Any

from breezy.analysis.capture_audit_fill_legs import (
    audit_fills,
)
from breezy.analysis.capture_audit_input_types import AuditInputs, ExecFill
from breezy.analysis.capture_audit_model import (
    Leg,
    LegOutcome,
)
from breezy.analysis.capture_settlement import SettlementRecord
from breezy.ingest.records import _climate_day_end_ns
from tests.support import capture_audit_fixtures as base
from tests.support.capture_audit_w1_fixtures import (
    DAY_START_NS,
    FILL_TS,
    INSTRUMENT,
    STATION,
    VSHA,
    DictTape,
    decision_view,
    entry_day,
    link_view,
    replace_c1,
    resolver,
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

NS = base.NS
DAY = base.DAY
H = 3600 * NS
FILL_KINDS = ("depth10", "quote")


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


# -- leg P after 23:00Z (S2-R35) -----------------------------------------------------------------

LATE_FILL_TS = DAY_START_NS + 23 * H + 1800 * NS  # 23:30Z: no whole-hour mark of D follows it
NEXT_MIDNIGHT = DAY_START_NS + 24 * H


def _late_fill(tape: DictTape) -> AuditInputs:
    inp = replace_c1(entry_day(), position_marks=())
    late = dataclasses.replace(inp.exec.fills[0], ts_event=LATE_FILL_TS)
    return dataclasses.replace(inp, exec=dataclasses.replace(inp.exec, fills=(late,)), tape=tape)


def test_a_fill_after_23z_is_marked_by_the_next_days_midnight_tape_mark() -> None:
    inp = _late_fill(DictTape(asks={(INSTRUMENT, NEXT_MIDNIGHT): 0.16}))
    assert _leg(_one(inp), Leg.P).outcome is LegOutcome.PASS


def test_a_fill_after_23z_without_the_next_midnight_mark_is_pending_never_fail() -> None:
    result = _leg(_one(_late_fill(DictTape())), Leg.P)

    assert result.outcome is LegOutcome.PENDING
    assert _causes(result) == {"tape_mark_next_day_pending"}
    assert _failing(result) == set()


def test_a_pending_late_fill_does_not_add_a_fill_cause() -> None:
    assert _one(_late_fill(DictTape())).causes == ()


def test_a_fill_before_23z_without_any_mark_still_fails() -> None:
    inp = replace_c1(entry_day(), position_marks=())
    tape = DictTape(asks={(INSTRUMENT, NEXT_MIDNIGHT): 0.16})
    assert _failing(_leg(_one(dataclasses.replace(inp, tape=tape)), Leg.P)) == {"no_position_mark"}


def test_a_late_fill_with_a_node_mark_needs_no_tape() -> None:
    inp = entry_day()
    late = dataclasses.replace(inp.exec.fills[0], ts_event=LATE_FILL_TS)
    mark = dataclasses.replace(inp.boots[0].c1.position_marks[0], ts_ns=LATE_FILL_TS + NS)
    inp = replace_c1(
        dataclasses.replace(inp, exec=dataclasses.replace(inp.exec, fills=(late,))),
        position_marks=(mark,),
    )
    assert _leg(_one(inp), Leg.P).outcome is LegOutcome.PASS


# -- leg P fill defects (S2-R39) -----------------------------------------------------------------


def _with_fill(**over: Any) -> AuditInputs:
    inp = replace_c1(entry_day(), position_marks=())
    odd = dataclasses.replace(inp.exec.fills[0], **over)
    return dataclasses.replace(inp, exec=dataclasses.replace(inp.exec, fills=(odd,)))


def test_an_unknown_fill_side_fails_that_fill_not_the_day() -> None:
    fill = _one(_with_fill(order_side="BUY_SHORT"))
    assert _failing(_leg(fill, Leg.P)) == {"fill_side_unknown"}
    assert "fill_side_unknown" in fill.causes


def test_a_fractional_fill_quantity_fails_that_fill() -> None:
    fill = _one(_with_fill(cumulative_qty="1.5"))
    assert _failing(_leg(fill, Leg.P)) == {"fill_qty_fractional"}


def test_leg_s_matches_an_icao_decision_station_to_a_city_settlement() -> None:
    inp = entry_day()
    take, submit = inp.boots[0].c1.decisions
    icao = dataclasses.replace(take, station="KLAX")
    assert _leg(_one(replace_c1(inp, decisions=(icao, submit))), Leg.S).outcome is LegOutcome.PASS


def test_leg_s_matches_a_city_decision_station_to_an_icao_settlement() -> None:
    inp = entry_day()
    icao = dataclasses.replace(inp.settlements[0], station="KLAX")
    assert (
        _leg(_one(dataclasses.replace(inp, settlements=(icao,))), Leg.S).outcome is LegOutcome.PASS
    )


def test_leg_s_does_not_match_a_different_station() -> None:
    inp = entry_day()
    other = dataclasses.replace(inp.settlements[0], station="KJFK")
    result = _leg(_one(dataclasses.replace(inp, settlements=(other,))), Leg.S)
    assert result.outcome is not LegOutcome.PASS


def test_offset_of_and_leg_s_share_one_station_normaliser() -> None:
    from breezy.analysis.capture_audit_fill_support import offset_of, same_station

    inp = entry_day()
    assert same_station("KLAX", "LAX") and same_station("LAX", "KLAX")
    assert not same_station("KLAX", "KJFK") and not same_station("LAX", "JFK")
    for form in ("LAX", "KLAX"):
        assert offset_of(dataclasses.replace(inp, std_offsets={"KLAX": -8.0}), form) == -8.0
        assert offset_of(dataclasses.replace(inp, std_offsets={"LAX": -8.0}), form) == -8.0
