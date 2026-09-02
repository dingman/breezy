"""R-3: the ORDER and FILL mappers, venue payload -> native report.

Authority: ``docs/plans/EXEC_SPINE_2026-09-01.md`` section R-3. This suite is
READ/MAP ONLY -- nothing here submits, cancels, or contacts a venue.

WHAT IS PINNED, AND WHY EACH PIN EXISTS
---------------------------------------

* **The mappers are total, and refuse what they do not recognise.** No live
  venue shape capture exists -- all four authenticated smoke runs returned
  ``Connectivity verdict: FAIL`` -- so the mappers are keyed off the SDK
  snapshot TypedDicts and nothing else. Every key an SDK ``TypedDict``
  declares is accepted; anything else is REFUSED. A venue that grows a field
  has changed a shape we reconcile money against, and silently ignoring it is
  how a semantic change lands unnoticed. That the allowlists still MATCH the
  snapshot is checked in ``test_polymarket_us_exec_snapshot_drift.py``.

* **Refusal, never coercion, never a default.** A missing required field, an
  unknown enum member, or a money value that will not survive ``Money``'s
  currency precision all raise. ``Money(Decimal("0.3125"), USD)`` silently
  returns ``Money(0.31, USD)`` -- measured -- so the refusal is in Breezy,
  ahead of the native constructor.

* **Every price runs the price guard, whatever the native field's type.**
  ``OrderStatusReport.avg_px`` is typed ``Decimal | None`` and looks like a
  plain amount. It is not: Nautilus reconciliation feeds it to
  ``instrument.make_price()`` and books the result as a fill price
  (``live/reconciliation.py:487``). It is therefore range- and
  precision-checked exactly as ``price`` is, and this suite pins both.

* **Every refusal lands in ONE taxonomy.** ``reports.py`` documents that all
  of them raise ``ExecutionReportMappingError``. A shared primitive that
  hardcoded a sibling class broke that promise for sub-tick and out-of-range
  prices, so the taxonomy is asserted on those paths and not only on the ones
  that always held.

The report TYPES are native and are used unwrapped: ``OrderStatusReport``,
``FillReport``, ``ExecutionMassStatus``
(``nautilus_trader/execution/reports.py:95,619,1038``). Breezy defines no
parallel report class -- asserted in ``test_polymarket_us_exec_endpoints.py``.

Siblings: the decode and the balances mapper are in
``test_polymarket_us_exec_endpoints.py``, the position mapper in
``test_polymarket_us_exec_positions.py``, and the allowlists' drift check in
``test_polymarket_us_exec_snapshot_drift.py``. Shared payload shapes live in
``polymarket_us_exec_shapes.py``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from nautilus_trader.execution.reports import (
    ExecutionMassStatus,
    FillReport,
    OrderStatusReport,
)
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import (
    LiquiditySide,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from nautilus_trader.model.identifiers import TradeId, VenueOrderId
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Money, Price, Quantity

from breezy.adapters.polymarket_us.errors import ExecutionReportMappingError
from breezy.adapters.polymarket_us.exec.reports import (
    ORDER_STATE_TO_ORDER_STATUS,
    build_execution_mass_status,
    parse_fill_report,
    parse_order_status_report,
    parse_position_status_report,
)
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE
from tests.unit.polymarket_us_exec_shapes import (
    ACCOUNT_ID,
    CLIENT_ID,
    REPORT_ID,
    TS_EVENT_NANOS,
    TS_INIT,
    build_execution,
    build_instrument,
    build_order,
    build_position,
)

# ---------------------------------------------------------------------------
# Fixtures -- thin views onto the shared SDK-snapshot shapes
# ---------------------------------------------------------------------------


@pytest.fixture
def instrument() -> BinaryOption:
    return build_instrument()


@pytest.fixture
def slug(instrument: BinaryOption) -> str:
    return str(instrument.raw_symbol)


@pytest.fixture
def order(slug: str) -> dict[str, Any]:
    return build_order(slug)


@pytest.fixture
def execution(order: dict[str, Any]) -> dict[str, Any]:
    return build_execution(order)


@pytest.fixture
def position(slug: str) -> dict[str, Any]:
    return build_position(slug)


# ---------------------------------------------------------------------------
# Order -> native OrderStatusReport
# ---------------------------------------------------------------------------


def test_order_status_report_round_trip(
    order: dict[str, Any], instrument: BinaryOption
) -> None:
    report = parse_order_status_report(
        order,
        instrument=instrument,
        account_id=ACCOUNT_ID,
        report_id=REPORT_ID,
        ts_init=TS_INIT,
    )

    assert isinstance(report, OrderStatusReport)
    assert report.account_id == ACCOUNT_ID
    assert report.instrument_id == instrument.id
    assert report.venue_order_id == VenueOrderId("ord-7f3a")
    assert report.client_order_id is None
    assert report.order_side == OrderSide.BUY
    assert report.order_type == OrderType.LIMIT
    assert report.time_in_force == TimeInForce.IOC
    assert report.order_status == OrderStatus.PARTIALLY_FILLED
    assert report.quantity == Quantity.from_str("10.00")
    assert report.filled_qty == Quantity.from_str("4.00")
    assert report.price == Price.from_str("0.53")
    assert report.avg_px == Decimal("0.52")
    assert report.ts_accepted == TS_EVENT_NANOS
    assert report.ts_last == TS_EVENT_NANOS
    assert report.ts_init == TS_INIT


def test_order_status_report_maps_every_snapshot_state(
    order: dict[str, Any], instrument: BinaryOption
) -> None:
    """Totality: every ``OrderState`` the snapshot declares maps to a status."""
    snapshot_states = {
        "ORDER_STATE_NEW",
        "ORDER_STATE_PENDING_NEW",
        "ORDER_STATE_PENDING_REPLACE",
        "ORDER_STATE_PENDING_CANCEL",
        "ORDER_STATE_PENDING_RISK",
        "ORDER_STATE_PARTIALLY_FILLED",
        "ORDER_STATE_FILLED",
        "ORDER_STATE_CANCELED",
        "ORDER_STATE_REPLACED",
        "ORDER_STATE_REJECTED",
        "ORDER_STATE_EXPIRED",
    }
    assert set(ORDER_STATE_TO_ORDER_STATUS) == snapshot_states

    for state in sorted(snapshot_states):
        report = parse_order_status_report(
            {**order, "state": state},
            instrument=instrument,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )
        assert report.order_status == ORDER_STATE_TO_ORDER_STATUS[state]


def test_market_order_without_a_price_is_mapped(
    order: dict[str, Any], instrument: BinaryOption
) -> None:
    market_order = {k: v for k, v in order.items() if k != "price"}
    market_order["type"] = "ORDER_TYPE_MARKET"

    report = parse_order_status_report(
        market_order,
        instrument=instrument,
        account_id=ACCOUNT_ID,
        report_id=REPORT_ID,
        ts_init=TS_INIT,
    )

    assert report.order_type == OrderType.MARKET
    assert report.price is None


def test_unknown_order_state_is_refused(
    order: dict[str, Any], instrument: BinaryOption
) -> None:
    with pytest.raises(ExecutionReportMappingError, match="ORDER_STATE_SUSPENDED"):
        parse_order_status_report(
            {**order, "state": "ORDER_STATE_SUSPENDED"},
            instrument=instrument,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )


def test_unknown_order_key_is_refused(
    order: dict[str, Any], instrument: BinaryOption
) -> None:
    with pytest.raises(ExecutionReportMappingError, match="settlementInstruction"):
        parse_order_status_report(
            {**order, "settlementInstruction": "AUTO"},
            instrument=instrument,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )


def test_order_for_another_market_is_refused(
    order: dict[str, Any], instrument: BinaryOption
) -> None:
    """Mapping a report onto the wrong instrument is a money-moving mistake."""
    with pytest.raises(ExecutionReportMappingError):
        parse_order_status_report(
            {**order, "marketSlug": "tc-temp-nychigh-2026-08-25-lt80f"},
            instrument=instrument,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )


def test_order_missing_a_required_field_is_refused(
    order: dict[str, Any], instrument: BinaryOption
) -> None:
    incomplete = {k: v for k, v in order.items() if k != "cumQuantity"}

    with pytest.raises(ExecutionReportMappingError, match="cumQuantity"):
        parse_order_status_report(
            incomplete,
            instrument=instrument,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )


# ---------------------------------------------------------------------------
# Execution -> native FillReport
# ---------------------------------------------------------------------------


def test_fill_report_round_trip(
    execution: dict[str, Any], instrument: BinaryOption
) -> None:
    report = parse_fill_report(
        execution,
        instrument=instrument,
        account_id=ACCOUNT_ID,
        report_id=REPORT_ID,
        ts_init=TS_INIT,
    )

    assert isinstance(report, FillReport)
    assert report.account_id == ACCOUNT_ID
    assert report.instrument_id == instrument.id
    assert report.venue_order_id == VenueOrderId("ord-7f3a")
    assert report.trade_id == TradeId("trd-902")
    assert report.order_side == OrderSide.BUY
    assert report.last_qty == Quantity.from_str("4.00")
    assert report.last_px == Price.from_str("0.52")
    assert report.commission == Money(Decimal("0.03"), USD)
    assert report.liquidity_side == LiquiditySide.TAKER
    assert report.client_order_id is None
    assert report.ts_event == TS_EVENT_NANOS
    assert report.ts_init == TS_INIT


def test_a_non_fill_execution_type_is_refused(
    execution: dict[str, Any], instrument: BinaryOption
) -> None:
    """A cancel acknowledgement is not a fill; it must not become one."""
    with pytest.raises(ExecutionReportMappingError, match="EXECUTION_TYPE_CANCELED"):
        parse_fill_report(
            {**execution, "type": "EXECUTION_TYPE_CANCELED"},
            instrument=instrument,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )


def test_unknown_execution_type_is_refused(
    execution: dict[str, Any], instrument: BinaryOption
) -> None:
    with pytest.raises(ExecutionReportMappingError, match="EXECUTION_TYPE_TRADE_BUST"):
        parse_fill_report(
            {**execution, "type": "EXECUTION_TYPE_TRADE_BUST"},
            instrument=instrument,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )


def test_unknown_execution_key_is_refused(
    execution: dict[str, Any], instrument: BinaryOption
) -> None:
    with pytest.raises(ExecutionReportMappingError, match="settlementDate"):
        parse_fill_report(
            {**execution, "settlementDate": "2026-08-26"},
            instrument=instrument,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )


def test_sub_cent_commission_is_refused_rather_than_rounded(
    execution: dict[str, Any], instrument: BinaryOption
) -> None:
    """``Money`` rounds to the currency precision without a word. We refuse."""
    with pytest.raises(ExecutionReportMappingError):
        parse_fill_report(
            {**execution, "commissionNotionalCollected": {"value": "0.3125", "currency": "USD"}},
            instrument=instrument,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )


def test_fill_missing_the_commission_is_refused_not_zeroed(
    execution: dict[str, Any], instrument: BinaryOption
) -> None:
    incomplete = {
        k: v for k, v in execution.items() if k != "commissionNotionalCollected"
    }

    with pytest.raises(ExecutionReportMappingError, match="commissionNotionalCollected"):
        parse_fill_report(
            incomplete,
            instrument=instrument,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )


def test_zero_quantity_fill_is_refused(
    execution: dict[str, Any], instrument: BinaryOption
) -> None:
    with pytest.raises(ExecutionReportMappingError):
        parse_fill_report(
            {**execution, "lastShares": "0"},
            instrument=instrument,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )


# ---------------------------------------------------------------------------
# ExecutionMassStatus -- native assembly
# ---------------------------------------------------------------------------


def test_execution_mass_status_carries_every_report(
    order: dict[str, Any],
    execution: dict[str, Any],
    position: dict[str, Any],
    instrument: BinaryOption,
    slug: str,
) -> None:
    order_report = parse_order_status_report(
        order,
        instrument=instrument,
        account_id=ACCOUNT_ID,
        report_id=REPORT_ID,
        ts_init=TS_INIT,
    )
    fill_report = parse_fill_report(
        execution,
        instrument=instrument,
        account_id=ACCOUNT_ID,
        report_id=REPORT_ID,
        ts_init=TS_INIT,
    )
    position_report = parse_position_status_report(
        position,
        market_slug=slug,
        instrument=instrument,
        account_id=ACCOUNT_ID,
        report_id=REPORT_ID,
        ts_init=TS_INIT,
    ).report

    mass_status = build_execution_mass_status(
        client_id=CLIENT_ID,
        account_id=ACCOUNT_ID,
        report_id=REPORT_ID,
        ts_init=TS_INIT,
        order_reports=[order_report],
        fill_reports=[fill_report],
        position_reports=[position_report],
    )

    assert isinstance(mass_status, ExecutionMassStatus)
    assert mass_status.venue == POLYMARKET_US_VENUE
    assert mass_status.client_id == CLIENT_ID
    assert mass_status.account_id == ACCOUNT_ID
    assert mass_status.order_reports == {order_report.venue_order_id: order_report}
    assert mass_status.fill_reports == {fill_report.venue_order_id: [fill_report]}
    assert mass_status.position_reports == {instrument.id: [position_report]}


def test_execution_mass_status_is_empty_when_nothing_is_open() -> None:
    """A flat, orderless account is a valid state -- not an error."""
    mass_status = build_execution_mass_status(
        client_id=CLIENT_ID,
        account_id=ACCOUNT_ID,
        report_id=REPORT_ID,
        ts_init=TS_INIT,
        order_reports=[],
        fill_reports=[],
        position_reports=[],
    )

    assert mass_status.order_reports == {}
    assert mass_status.fill_reports == {}
    assert mass_status.position_reports == {}


# ---------------------------------------------------------------------------
# R-3 REVIEW FINDINGS -- RED block
# ---------------------------------------------------------------------------


def test_sub_tick_avg_px_is_refused_rather_than_silently_rounded(
    order: dict[str, Any], instrument: BinaryOption
) -> None:
    """CRITICAL: ``avgPx`` is a FILL PRICE to Nautilus, so it needs the price guard.

    ``reconciliation.py:487`` calls ``instrument.make_price(report.avg_px)``.
    Measured at precision 2: ``make_price(Decimal("0.5249"))`` is ``0.52`` --
    the silent round this module exists to prevent. The ``price`` field is
    already refused here; ``avg_px`` must be refused identically.
    """
    with pytest.raises(ExecutionReportMappingError, match="avgPx"):
        parse_order_status_report(
            {**order, "avgPx": {"value": "0.5249", "currency": "USD"}},
            instrument=instrument,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )


def test_avg_px_outside_the_binary_range_is_refused(
    order: dict[str, Any], instrument: BinaryOption
) -> None:
    """A binary contract pays at most 1.00; 1.35 is an impossible cost basis."""
    with pytest.raises(ExecutionReportMappingError, match="avgPx"):
        parse_order_status_report(
            {**order, "avgPx": {"value": "1.35", "currency": "USD"}},
            instrument=instrument,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )


def test_avg_px_stays_a_decimal_on_the_native_report(
    order: dict[str, Any], instrument: BinaryOption
) -> None:
    """``OrderStatusReport.avg_px`` is typed ``Decimal | None`` (``reports.py:209``)."""
    report = parse_order_status_report(
        order,
        instrument=instrument,
        account_id=ACCOUNT_ID,
        report_id=REPORT_ID,
        ts_init=TS_INIT,
    )

    assert isinstance(report.avg_px, Decimal)
    assert report.avg_px == Decimal("0.52")


def test_sub_tick_price_refusal_stays_inside_the_mapping_taxonomy(
    order: dict[str, Any], instrument: BinaryOption
) -> None:
    """The module docstring promises every refusal is an ``ExecutionReportMappingError``.

    ``_build_price`` hardcoded ``VenuePayloadError``, so an R-4 caller writing
    ``except ExecutionReportMappingError`` would have missed a sub-tick price.
    """
    with pytest.raises(ExecutionReportMappingError, match="price"):
        parse_order_status_report(
            {**order, "price": {"value": "0.5271", "currency": "USD"}},
            instrument=instrument,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )


def test_out_of_range_price_refusal_stays_inside_the_mapping_taxonomy(
    order: dict[str, Any], instrument: BinaryOption
) -> None:
    with pytest.raises(ExecutionReportMappingError, match="price"):
        parse_order_status_report(
            {**order, "price": {"value": "1.35", "currency": "USD"}},
            instrument=instrument,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )


def test_out_of_range_fill_price_refusal_stays_inside_the_mapping_taxonomy(
    execution: dict[str, Any], instrument: BinaryOption
) -> None:
    with pytest.raises(ExecutionReportMappingError, match="lastPx"):
        parse_fill_report(
            {**execution, "lastPx": {"value": "1.35", "currency": "USD"}},
            instrument=instrument,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )


def test_cum_quantity_above_quantity_is_refused(
    order: dict[str, Any], instrument: BinaryOption
) -> None:
    """``OrderStatusReport`` only CLAMPS (``saturating_sub``); it does not refuse."""
    with pytest.raises(ExecutionReportMappingError, match="cumQuantity"):
        parse_order_status_report(
            {**order, "quantity": 10, "cumQuantity": 14, "leavesQuantity": 0},
            instrument=instrument,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )


def test_leaves_quantity_inconsistent_with_the_fill_is_refused(
    order: dict[str, Any], instrument: BinaryOption
) -> None:
    """Allowlisted then discarded is a wasted cross-check on a money surface."""
    with pytest.raises(ExecutionReportMappingError, match="leavesQuantity"):
        parse_order_status_report(
            {**order, "quantity": 10, "cumQuantity": 4, "leavesQuantity": 9},
            instrument=instrument,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )


def test_a_consistent_leaves_quantity_is_accepted(
    order: dict[str, Any], instrument: BinaryOption
) -> None:
    report = parse_order_status_report(
        {**order, "quantity": 10, "cumQuantity": 4, "leavesQuantity": 6},
        instrument=instrument,
        account_id=ACCOUNT_ID,
        report_id=REPORT_ID,
        ts_init=TS_INIT,
    )

    assert report.quantity == Quantity.from_str("10.00")
    assert report.filled_qty == Quantity.from_str("4.00")


def test_a_maker_fill_is_refused_because_its_commission_sign_is_unmodelled(
    execution: dict[str, Any], instrument: BinaryOption
) -> None:
    """The venue's documented maker coefficient is a REBATE (-0.0125), i.e. income.

    ``commissionNotionalCollected`` was mapped whatever its sign, so a
    magnitude-only ``0.03`` on a maker fill books a COST against INCOME --
    wrong in sign. Breezy is taker-only (``MakerRebateUnmodelledError``), so
    refusing costs nothing today and mis-signing money costs twice the fee.
    """
    with pytest.raises(ExecutionReportMappingError, match="aggressor"):
        parse_fill_report(
            {**execution, "aggressor": False},
            instrument=instrument,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )


def test_quantity_refusal_names_the_field_not_the_value(
    order: dict[str, Any], instrument: BinaryOption
) -> None:
    with pytest.raises(ExecutionReportMappingError) as excinfo:
        parse_order_status_report(
            {**order, "quantity": -7654321, "cumQuantity": 0, "leavesQuantity": 0},
            instrument=instrument,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )

    assert "quantity" in str(excinfo.value)
    assert "7654321" not in str(excinfo.value)


def test_an_unknown_enum_value_is_named_but_bounded(
    order: dict[str, Any], instrument: BinaryOption
) -> None:
    """A venue-supplied string is echoed for diagnosis, but never unbounded."""
    with pytest.raises(ExecutionReportMappingError) as excinfo:
        parse_order_status_report(
            {**order, "state": "ORDER_STATE_" + "X" * 4000},
            instrument=instrument,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )

    assert "X" * 4000 not in str(excinfo.value)
    assert "ORDER_STATE_" in str(excinfo.value)




def test_a_malformed_order_timestamp_stays_inside_the_mapping_taxonomy(
    order: dict[str, Any], instrument: BinaryOption
) -> None:
    """Same taxonomy leak as the price guard had, on the timestamp guard.

    ``parse_rfc3339_nanos`` also hardcoded ``VenuePayloadError``. An R-4 caller
    writing ``except ExecutionReportMappingError`` would have missed a
    malformed ``createTime`` for exactly the reason it would have missed a
    sub-tick price.
    """
    with pytest.raises(ExecutionReportMappingError, match="createTime"):
        parse_order_status_report(
            {**order, "createTime": "2026-08-25 00:19:48"},
            instrument=instrument,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )


def test_a_malformed_fill_timestamp_stays_inside_the_mapping_taxonomy(
    execution: dict[str, Any], instrument: BinaryOption
) -> None:
    with pytest.raises(ExecutionReportMappingError, match="transactTime"):
        parse_fill_report(
            {**execution, "transactTime": "not-a-timestamp"},
            instrument=instrument,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )
