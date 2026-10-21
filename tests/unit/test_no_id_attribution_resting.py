"""S4 WP3 (ARM maker-sharp B4, r2 D2): in-process ADOPT of a resting no-id order.

Pure, like ``test_no_id_attribution.py``. A RESTING echo (``NoIdEcho.resting``)
turns a single in-window, unknown, echo-matching GTD open order of quantity 1 on
the opening side into an ADOPT candidate; everything else keeps today's verdict.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Final

import pytest

from tests.unit.ambig_latch_rig import IOC, SEC_NS, ns_to_rfc3339
from tests.unit.test_no_id_attribution import (
    SLUG,
    T0,
    WINDOW_END,
    WINDOW_START,
    na,
    older_row,
    row,
    scan,
)

GTD: Final[str] = "TIME_IN_FORCE_GOOD_TILL_DATE"


def rest_echo(*, resting: bool = True, price: str = "0.60") -> Any:
    return na().NoIdEcho(
        slug=SLUG,
        outcome_side="OUTCOME_SIDE_NO",
        action="ORDER_ACTION_BUY",
        price=price,
        resting=resting,
    )


def rest_order(
    order_id: str = "REST-1",
    *,
    created: int = T0 + 5 * SEC_NS,
    tif: str = GTD,
    side: str = "ORDER_SIDE_SELL",
    quantity: str = "1",
    price: str = "0.60",
    slug: str = SLUG,
) -> Any:
    return SimpleNamespace(
        venue_order_id=order_id,
        market_slug=slug,
        price=Decimal(price),
        tif=tif,
        side=side,
        quantity=Decimal(quantity),
        create_time=ns_to_rfc3339(created),
    )


def verdict(open_orders: tuple[Any, ...], *, echo: Any = "default", rows: Any = None) -> Any:
    result = scan(rows if rows is not None else [older_row()])
    return na().classify_no_id_evidence(
        legs=result.legs,
        passive_manual=result.passive_manual,
        legs_complete=result.passed_window_start and not result.out_of_order,
        out_of_order=result.out_of_order,
        open_orders=open_orders,
        open_orders_ok=True,
        known_order_ids=frozenset(),
        echo=rest_echo() if echo == "default" else echo,
        window_start_ns=WINDOW_START,
        window_end_ns=WINDOW_END,
    )


def test_resting_single_echo_match_open_order_is_adopt() -> None:
    v = verdict((rest_order(),))
    assert v.kind == "ADOPT"
    assert v.order_id == "REST-1"


def test_ioc_echo_match_open_order_stays_contradiction() -> None:
    v = verdict((rest_order(tif=IOC),))
    assert v.kind == "CONTRADICTION"
    assert v.token == "in_window_open_order"


def test_resting_two_echo_matches_stay_contradiction() -> None:
    v = verdict((rest_order("REST-1"), rest_order("REST-2")))
    assert v.kind == "CONTRADICTION"
    assert v.order_id is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"quantity": "2"},
        {"side": "ORDER_SIDE_BUY"},
        {"tif": "TIME_IN_FORCE_GOOD_TILL_CANCEL"},
    ],
    ids=["quantity", "side", "tif"],
)
def test_resting_echo_match_that_is_not_a_clean_gtd_rest_stays_contradiction(
    overrides: dict[str, str],
) -> None:
    order: Any = rest_order(**overrides)  # type: ignore[arg-type]
    v = verdict((order,))
    assert v.kind == "CONTRADICTION"


def test_resting_order_outside_the_window_or_other_slug_is_not_a_candidate() -> None:
    late = rest_order(created=WINDOW_END + SEC_NS)
    other_slug = rest_order(slug="tc-temp-sfohigh-2026-09-05-gte70lt71f")
    assert verdict((late, other_slug)).kind == "NO_FILL"


def test_resting_order_with_a_different_price_is_not_a_candidate() -> None:
    assert verdict((rest_order(price="0.59"),)).kind == "NO_FILL"


def test_known_order_ids_are_never_candidates() -> None:
    result = scan([older_row()])
    v = na().classify_no_id_evidence(
        legs=result.legs,
        passive_manual=result.passive_manual,
        legs_complete=True,
        out_of_order=False,
        open_orders=(rest_order("REST-1"),),
        open_orders_ok=True,
        known_order_ids=frozenset({"REST-1"}),
        echo=rest_echo(),
        window_start_ns=WINDOW_START,
        window_end_ns=WINDOW_END,
    )
    assert v.kind == "NO_FILL"


def test_non_resting_echo_never_adopts_an_open_order() -> None:
    """[CHAR] ``echo.resting`` False is byte-equivalent to the pre-S4 verdict: an
    echo-matching GTD open order is a contradiction, never an ADOPT."""
    v = verdict((rest_order(),), echo=rest_echo(resting=False))
    assert v.kind == "CONTRADICTION"


def test_open_order_verdict_non_resting_is_unchanged() -> None:
    module = na()
    third = module._open_order_verdict(
        (rest_order(tif=IOC),),
        frozenset(),
        rest_echo(resting=False),
        WINDOW_START,
        WINDOW_END,
    )
    assert third == (True, False, None)
    assert module._open_order_verdict((), frozenset(), None, WINDOW_START, WINDOW_END) == (
        False,
        False,
        None,
    )


def test_resting_fill_leg_never_matches_echo() -> None:
    """A maker fill is the PASSIVE side of a trade row: the aggressor leg is some
    other order, never a candidate, so it is unattributed (a contradiction)."""
    maker_filled = row(T0 + 3 * SEC_NS, "AGGRESSOR-1", tif=GTD, price="0.60")
    v = verdict((), rows=[maker_filled, older_row()])
    assert v.kind == "CONTRADICTION"
    assert v.token == "unattributed_automated_trade_in_window"
