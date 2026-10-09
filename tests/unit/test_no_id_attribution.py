"""AMBIG-LATCH-RESUME Phase B: the pure no-id attribution module (T41).

Authority: ``docs/plans/backlog/BACKLOG_PLANS_2026-10-03/
AMBIG-LATCH-RESUME_plan_r6.md`` section 2.8.5.

``breezy.adapters.polymarket_us.no_id_attribution`` does no I/O. Its inputs
here are synthetic rows and the git-tracked 2026-09-05 SFO capture, whose
operator attestation (positions ``{}``, open orders ``[]``, no activity for the
market) is the real-data positive control for the no-fill verdict.

The module is imported lazily so a missing module fails each test on its own
(RED), not the whole collection.
"""

from __future__ import annotations

import copy
import importlib
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final

from tests.unit.ambig_latch_rig import IOC, SEC_NS, ns_to_rfc3339, trade_row

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
CAPTURE_DIR: Final[Path] = (
    REPO_ROOT / "docs" / "evidence" / "venue" / "polymarket_us" / "AMBIGUOUS_ORDER_2026-09-05_SFO"
)
SLUG: Final[str] = "tc-temp-sfohigh-2026-09-05-gte73lt74f"
T0: Final[int] = 1_788_000_000 * SEC_NS
BACK: Final[int] = 120 * SEC_NS
FWD: Final[int] = 120 * SEC_NS
WINDOW_START: Final[int] = T0 - BACK
WINDOW_END: Final[int] = T0 + FWD


def na() -> Any:
    return importlib.import_module("breezy.adapters.polymarket_us.no_id_attribution")


def aa() -> Any:
    return importlib.import_module("breezy.adapters.polymarket_us.account_activity")


def echo(price: str = "0.28") -> Any:
    return na().NoIdEcho(
        slug=SLUG,
        outcome_side="OUTCOME_SIDE_YES",
        action="ORDER_ACTION_BUY",
        price=price,
    )


def row(ts: int, order_id: str = "X", **kw: Any) -> dict[str, Any]:
    kw.setdefault("price", "0.28")
    return trade_row(ts_ns=ts, order_id=order_id, slug=SLUG, **kw)


def page(rows: list[Any], eof: bool = True) -> dict[str, Any]:
    return {"activities": rows, "eof": eof}


def scan(rows: list[Any], start: int = WINDOW_START, prev: int | None = None) -> Any:
    return na().no_id_aggressor_legs(page(rows), start, prev)


def verdict(
    rows: list[Any],
    *,
    ec: Any = "default",
    known: frozenset[str] = frozenset(),
    open_orders: tuple[Any, ...] = (),
    open_ok: bool = True,
    complete: bool | None = None,
    start: int = WINDOW_START,
    end: int = WINDOW_END,
) -> Any:
    result = scan(rows, start)
    is_complete = (
        (result.passed_window_start and not result.out_of_order) if complete is None else complete
    )
    return na().classify_no_id_evidence(
        legs=result.legs,
        passive_manual=result.passive_manual,
        legs_complete=is_complete,
        out_of_order=result.out_of_order,
        open_orders=open_orders,
        open_orders_ok=open_ok,
        known_order_ids=known,
        echo=echo() if ec == "default" else ec,
        window_start_ns=start,
        window_end_ns=end,
    )


def older_row(order_id: str = "old") -> dict[str, Any]:
    """An AUTOMATIC row before the window: it lets an early-terminated scan
    complete without being a leg."""
    return row(WINDOW_START - 10 * SEC_NS, order_id, price="0.99")


def load_capture() -> dict[str, Any]:
    return json.loads((CAPTURE_DIR / "activities_p0.json").read_text())["payload"]


def trade_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [a for a in payload["activities"] if a["type"] == "ACTIVITY_TYPE_TRADE"]


def open_orders_row(created: int, *, tif: str = IOC, slug: str = SLUG, price: str = "0.28") -> Any:
    return SimpleNamespace(
        venue_order_id="open-1",
        market_slug=slug,
        price=Decimal(price),
        tif=tif,
        create_time=ns_to_rfc3339(created),
    )


# ---------------------------------------------------------------------------
# (i)-(vi): the classifier and the scan
# ---------------------------------------------------------------------------


def test_decimal_price_equality_0_28_equals_0_2800() -> None:
    v = verdict([row(T0 + SEC_NS, price="0.2800"), older_row()])
    assert v.kind == "ADOPT" and v.order_id == "X"


def test_the_window_start_boundary_is_inclusive() -> None:
    at = scan([row(WINDOW_START), older_row()])
    assert [leg.order_id for leg in at.legs] == ["X"]
    below = scan([row(WINDOW_START - 1)])
    assert below.legs == ()
    assert below.passed_window_start is True


def test_a_leg_quantity_of_7_63_does_not_match_a_quantity_of_1() -> None:
    v = verdict([row(T0 + SEC_NS, quantity=7.63), older_row()])
    assert v.kind == "CONTRADICTION"
    assert v.token == "unattributed_automated_trade_in_window"


def test_a_missing_manual_indicator_on_an_in_window_row_is_uninterpretable() -> None:
    bad = row(T0 + SEC_NS)
    del bad["trade"]["aggressor"]["manualOrderIndicator"]
    result = scan([bad])
    assert result.uninterpretable_rows == 1
    assert result.legs == ()


def test_the_aggressor_execution_order_fallback_is_read() -> None:
    r = row(T0 + SEC_NS)
    r["trade"]["aggressorExecution"] = {"order": r["trade"].pop("aggressor")}
    r["trade"]["passiveExecution"] = {"order": r["trade"].pop("passive")}
    result = scan([r, older_row()])
    assert [leg.order_id for leg in result.legs] == ["X"]
    assert result.uninterpretable_rows == 0


def test_a_non_trade_row_with_a_trade_key_is_uninterpretable() -> None:
    odd = {"type": "ACTIVITY_TYPE_ACCOUNT_DEPOSIT", "trade": {"createTime": "x"}}
    assert scan([odd]).uninterpretable_rows == 1
    plain = {"type": "ACTIVITY_TYPE_ACCOUNT_DEPOSIT", "accountBalanceChange": {}}
    assert scan([plain]).uninterpretable_rows == 0


def test_a_known_venue_id_is_ignored_even_when_it_matches_the_echo() -> None:
    v = verdict([row(T0 + SEC_NS, "known-1"), older_row()], known=frozenset({"known-1"}))
    assert v.kind == "NO_FILL"


def test_manual_and_manual_passive_rows_are_ignored_and_other_automatic_rows_contradict() -> None:
    assert verdict([row(T0 + SEC_NS, manual=True), older_row()]).kind == "NO_FILL"
    assert (
        verdict([row(T0 + SEC_NS, price="0.55", passive_manual=True), older_row()]).kind
        == "NO_FILL"
    )
    contradiction = verdict([row(T0 + SEC_NS, price="0.55"), older_row()])
    assert (contradiction.kind, contradiction.token) == (
        "CONTRADICTION",
        "unattributed_automated_trade_in_window",
    )


def test_our_own_order_that_hit_a_manual_resting_order_is_still_a_candidate() -> None:
    """The passive leg being MANUAL must not hide OUR fill (rule 2 precedes 4)."""
    v = verdict([row(T0 + SEC_NS, passive_manual=True), older_row()])
    assert v.kind == "ADOPT"


def test_two_distinct_candidates_are_a_contradiction() -> None:
    v = verdict([row(T0 + 2 * SEC_NS, "b"), row(T0 + SEC_NS, "a"), older_row()])
    assert (v.kind, v.token) == ("CONTRADICTION", "multiple_candidates")


def test_window_only_mode_has_no_candidates_and_contradicts_any_automatic_leg() -> None:
    v = verdict([row(T0 + SEC_NS), older_row()], ec=None)
    assert (v.kind, v.token) == ("CONTRADICTION", "unattributed_automated_trade_in_window")


def test_open_orders_in_window_ioc_or_echo_match_contradict_and_others_are_ignored() -> None:
    base = [older_row()]
    ioc = verdict(base, open_orders=(open_orders_row(T0 + SEC_NS),))
    assert (ioc.kind, ioc.token) == ("CONTRADICTION", "in_window_open_order")
    echo_match = verdict(
        base,
        open_orders=(open_orders_row(T0, tif="TIME_IN_FORCE_DAY"),),
    )
    assert echo_match.token == "in_window_open_order"
    other_day = verdict(
        base,
        open_orders=(open_orders_row(T0, tif="TIME_IN_FORCE_DAY", slug="other", price="0.77"),),
    )
    assert other_day.kind == "NO_FILL"
    outside = verdict(base, open_orders=(open_orders_row(T0 - 600 * SEC_NS),))
    assert outside.kind == "NO_FILL"


def test_precedence_contradiction_then_incomplete_then_the_rest() -> None:
    assert verdict([older_row()], open_ok=False).token == "open_orders_read"
    assert verdict([older_row()], complete=False).token == "activities_incomplete"
    both = verdict([row(T0 + SEC_NS, price="0.55")], complete=False, open_ok=False)
    assert both.kind == "CONTRADICTION"
    assert verdict([older_row()]).kind == "NO_FILL"


# ---------------------------------------------------------------------------
# (vii)-(viii): the real capture
# ---------------------------------------------------------------------------

CREATED_NS: Final[int] = 1_788_000_000 * SEC_NS  # placeholder, overwritten below


def _capture_window() -> tuple[int, int]:
    created = aa().parse_rfc3339_ns("2026-09-05T20:19:49.006Z")
    return created - BACK, created + FWD


def test_real_data_positive_control_the_operator_attested_no_fill() -> None:
    payload = load_capture()
    open_orders = json.loads((CAPTURE_DIR / "orders_open_all.json").read_text())["payload"]
    assert open_orders == {"orders": []}
    start, end = _capture_window()
    result = na().no_id_aggressor_legs(payload, start, None)
    v = na().classify_no_id_evidence(
        legs=result.legs,
        passive_manual=result.passive_manual,
        legs_complete=payload["eof"] is True or result.passed_window_start,
        out_of_order=result.out_of_order,
        open_orders=(),
        open_orders_ok=True,
        known_order_ids=frozenset(),
        echo=na().NoIdEcho(
            slug=SLUG,
            outcome_side="OUTCOME_SIDE_YES",
            action="ORDER_ACTION_BUY",
            price="0.28",
        ),
        window_start_ns=start,
        window_end_ns=end,
    )
    assert v.kind == "NO_FILL"


def test_the_same_capture_with_one_rewritten_aggressor_adopts_it() -> None:
    payload = copy.deepcopy(load_capture())
    start, end = _capture_window()
    target = trade_rows(payload)[0]["trade"]
    target["createTime"] = ns_to_rfc3339(start + 10 * SEC_NS)
    aggressor = target["aggressor"]
    aggressor["marketSlug"] = SLUG
    aggressor["price"] = {"value": "0.28", "currency": "USD"}
    aggressor["quantity"] = 1
    result = na().no_id_aggressor_legs(payload, start, None)
    v = na().classify_no_id_evidence(
        legs=result.legs,
        passive_manual=result.passive_manual,
        legs_complete=result.passed_window_start,
        out_of_order=result.out_of_order,
        open_orders=(),
        open_orders_ok=True,
        known_order_ids=frozenset(),
        echo=na().NoIdEcho(
            slug=SLUG,
            outcome_side="OUTCOME_SIDE_YES",
            action="ORDER_ACTION_BUY",
            price="0.28",
        ),
        window_start_ns=start,
        window_end_ns=end,
    )
    assert v.kind == "ADOPT"
    assert v.order_id == target["aggressor"]["id"]


# ---------------------------------------------------------------------------
# (ix)-(xi): ordering, early termination, across pages
# ---------------------------------------------------------------------------


def test_the_ordering_pin_against_the_captured_response() -> None:
    payload = load_capture()
    times = [aa().parse_rfc3339_ns(t["trade"]["createTime"]) for t in trade_rows(payload)]
    assert times == sorted(times, reverse=True), "non-increasing on real data"
    assert len(set(times)) < len(times), "an exact tie exists: a strict check is wrong"
    window_start = aa().parse_rfc3339_ns("2026-08-09T00:00:00Z")
    result = na().no_id_aggressor_legs(payload, window_start, None)
    assert result.out_of_order is False
    assert result.passed_window_start is True
    assert len(result.legs) == 1, "only the first TRADE row is at or after the window start"


def test_swapping_two_adjacent_trade_rows_is_out_of_order_and_incomplete() -> None:
    payload = copy.deepcopy(load_capture())
    activities = payload["activities"]
    indexes = [i for i, a in enumerate(activities) if a["type"] == "ACTIVITY_TYPE_TRADE"]
    first, second = indexes[0], indexes[1]
    activities[first], activities[second] = activities[second], activities[first]
    window_start = aa().parse_rfc3339_ns("2026-08-09T00:00:00Z")
    result = na().no_id_aggressor_legs(payload, window_start, None)
    assert result.out_of_order is True
    v = na().classify_no_id_evidence(
        legs=result.legs,
        passive_manual=result.passive_manual,
        legs_complete=False,
        out_of_order=True,
        open_orders=(),
        open_orders_ok=True,
        known_order_ids=frozenset(),
        echo=None,
        window_start_ns=window_start,
        window_end_ns=window_start + FWD,
    )
    assert (v.kind, v.token) == ("INCOMPLETE", "activities_out_of_order")


def test_a_newer_non_trade_row_never_trips_the_ordering_check() -> None:
    payload = copy.deepcopy(load_capture())
    newest = ns_to_rfc3339(aa().parse_rfc3339_ns("2027-01-01T00:00:00Z"))
    resolution = next(
        a for a in payload["activities"] if a["type"] == "ACTIVITY_TYPE_POSITION_RESOLUTION"
    )
    resolution["positionResolution"]["afterPosition"]["updateTime"] = newest
    deposit = next(a for a in payload["activities"] if a["type"] == "ACTIVITY_TYPE_ACCOUNT_DEPOSIT")
    deposit["accountBalanceChange"]["createTime"] = newest
    window_start = aa().parse_rfc3339_ns("2026-08-09T00:00:00Z")
    baseline = na().no_id_aggressor_legs(load_capture(), window_start, None)
    changed = na().no_id_aggressor_legs(payload, window_start, None)
    assert changed.out_of_order is False
    assert changed.legs == baseline.legs
    assert changed.passed_window_start == baseline.passed_window_start


def test_the_previous_page_row_time_makes_the_ordering_check_span_pages() -> None:
    rows = [row(T0 + 100 * SEC_NS, manual=True)]
    older_prev = T0 + 50 * SEC_NS
    assert na().no_id_aggressor_legs(page(rows, eof=False), WINDOW_START, older_prev).out_of_order
    ok_prev = T0 + 200 * SEC_NS
    result = na().no_id_aggressor_legs(page(rows, eof=False), WINDOW_START, ok_prev)
    assert result.out_of_order is False
    assert result.last_row_ts_ns == T0 + 100 * SEC_NS
    empty = na().no_id_aggressor_legs(page([], eof=False), WINDOW_START, ok_prev)
    assert empty.last_row_ts_ns == ok_prev, "a page with no TRADE row carries the previous time"


# ---------------------------------------------------------------------------
# (xii): the window end
# ---------------------------------------------------------------------------


def test_the_window_end_boundary_and_a_manual_leg_after_it() -> None:
    on_edge = verdict([row(WINDOW_END), older_row()])
    assert on_edge.kind == "ADOPT"
    late = verdict([row(WINDOW_END + 1), older_row()])
    assert (late.kind, late.token) == ("CONTRADICTION", "leg_after_attribution_window")
    manual_late = verdict([row(WINDOW_END + 1, manual=True), older_row()])
    assert manual_late.kind == "NO_FILL"


# ---------------------------------------------------------------------------
# (xiii): the holding delta
# ---------------------------------------------------------------------------


def delta(**kw: Any) -> Any:
    args: dict[str, Any] = {
        "base_venue_net": "3",
        "now_venue_net": "3",
        "base_durable_net": "0",
        "now_durable_net": Decimal(0),
        "leg_sign": 1,
    }
    args.update(kw)
    return na().holding_delta_consistent(**args)


def test_holding_delta_consistent() -> None:
    assert delta() is True, "a pre-existing manual LONG of 3 at both ends"
    assert delta(now_venue_net="4") is False, "+1 on the YES leg with d unchanged"
    assert delta(base_venue_net="-1", now_venue_net="-2", leg_sign=-1) is False
    assert delta(now_venue_net="not-a-number") is None
    assert delta(manual_net=Decimal(2), now_venue_net="5") is True
    assert delta(manual_net=Decimal(2), now_venue_net="6") is False
    # our own tracked fill moves venue and durable together: not foreign
    assert delta(now_venue_net="4", now_durable_net=Decimal(1)) is True


# ---------------------------------------------------------------------------
# (xiv): manual_leg_net_effect (route (d))
# ---------------------------------------------------------------------------

AFTER: Final[int] = T0
NOW: Final[int] = T0 + 1000 * SEC_NS
SETTLE: Final[int] = 120 * SEC_NS
STRADDLE: Final[int] = 30 * SEC_NS


def manual_row(ts: int, **kw: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "manual": True,
        "qty_decimal": "2.0000",
        "price": "0.55",
        "quantity": 9,
        "tif": "TIME_IN_FORCE_DAY",
    }
    defaults.update(kw)
    return row(ts, "manual-1", **defaults)


def net(rows: list[Any], slug: str = SLUG, after: int = AFTER, now: int = NOW) -> Any:
    result = scan(rows, start=0)
    return na().manual_leg_net_effect(
        legs=result.legs,
        passive_manual=result.passive_manual,
        slug=slug,
        after_ns=after,
        now_ns=now,
        settle_ns=SETTLE,
        straddle_ns=STRADDLE,
    )


def test_the_manual_sign_table_is_exactly_the_three_observed_shapes() -> None:
    assert dict(na().MANUAL_SIGN_TABLE) == {
        ("OUTCOME_SIDE_YES", "ORDER_ACTION_BUY", "ORDER_INTENT_BUY_LONG"): 1,
        ("OUTCOME_SIDE_YES", "ORDER_ACTION_SELL", "ORDER_INTENT_SELL_LONG"): -1,
        ("OUTCOME_SIDE_NO", "ORDER_ACTION_BUY", "ORDER_INTENT_BUY_SHORT"): -1,
    }
    payload = load_capture()
    sell = next(
        t
        for t in trade_rows(payload)
        if t["trade"]["aggressor"]["manualOrderIndicator"] == "MANUAL_ORDER_INDICATOR_MANUAL"
    )
    stamp = aa().parse_rfc3339_ns(sell["trade"]["createTime"])
    result = na().no_id_aggressor_legs(payload, 0, None)
    effect = na().manual_leg_net_effect(
        legs=result.legs,
        passive_manual=result.passive_manual,
        slug=sell["trade"]["aggressor"]["marketSlug"],
        after_ns=stamp - 3600 * SEC_NS,
        now_ns=stamp + 10_000 * SEC_NS,
        settle_ns=SETTLE,
        straddle_ns=STRADDLE,
    )
    assert effect.status == "ok"
    assert effect.value == -Decimal(sell["trade"]["qtyDecimal"])


def test_unknown_shapes_and_missing_fields_are_unreconcilable() -> None:
    sell_short = manual_row(
        AFTER + 100 * SEC_NS,
        outcome_side="OUTCOME_SIDE_NO",
        action="ORDER_ACTION_SELL",
        intent="ORDER_INTENT_SELL_SHORT",
    )
    effect = net([sell_short])
    assert (effect.status, effect.value, effect.reason) == (
        "unreconcilable",
        None,
        "unknown_shape",
    )
    no_intent = manual_row(AFTER + 100 * SEC_NS)
    del no_intent["trade"]["aggressor"]["intent"]
    assert net([no_intent]).status == "unreconcilable"
    no_qty = manual_row(AFTER + 100 * SEC_NS, qty_decimal=None)
    effect = net([no_qty])
    assert (effect.status, effect.reason) == ("unreconcilable", "missing_field")


def test_a_leg_within_the_straddle_of_the_snapshot_is_unreconcilable() -> None:
    for offset in (-30, 0, 30):
        effect = net([manual_row(AFTER + offset * SEC_NS)])
        assert (effect.status, effect.reason) == ("unreconcilable", "straddles_snapshot"), offset


def test_a_manual_passive_leg_on_the_slug_after_the_snapshot_closes_the_route() -> None:
    effect = net([row(AFTER + 100 * SEC_NS, "hit", passive_manual=True, price="0.55")])
    assert (effect.status, effect.reason) == ("unreconcilable", "manual_passive_leg")


def test_a_leg_newer_than_now_minus_settle_is_unsettled() -> None:
    effect = net([manual_row(NOW - 60 * SEC_NS)])
    assert (effect.status, effect.value) == ("unsettled", None)


def test_legs_that_are_not_counted() -> None:
    other_slug = manual_row(AFTER + 100 * SEC_NS)
    other_slug["trade"]["aggressor"]["marketSlug"] = "other-slug"
    automatic = row(AFTER + 100 * SEC_NS, "auto", price="0.55")
    long_before = manual_row(AFTER - 31 * SEC_NS)
    effect = net([other_slug, automatic, long_before])
    assert (effect.status, effect.value, effect.count) == ("ok", Decimal(0), 0)


def test_no_legs_is_ok_zero_and_the_fill_size_is_qty_decimal_not_the_order_quantity() -> None:
    assert net([]).value == Decimal(0)
    leg = manual_row(AFTER + 100 * SEC_NS, quantity=7.63, qty_decimal="2.0000")
    effect = net([leg])
    assert (effect.status, effect.value, effect.count) == ("ok", Decimal(2), 1)
    sell = manual_row(
        AFTER + 100 * SEC_NS,
        action="ORDER_ACTION_SELL",
        intent="ORDER_INTENT_SELL_LONG",
        qty_decimal="1.5000",
    )
    assert net([sell, leg]).value == Decimal("0.5")
