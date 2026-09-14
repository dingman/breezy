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

import base64
import decimal
import logging
from decimal import Decimal, InvalidOperation
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
    PositionSide,
    TimeInForce,
)
from nautilus_trader.model.identifiers import TradeId, VenueOrderId
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Money, Price, Quantity

from breezy.adapters.polymarket_us.errors import ExecutionReportMappingError
from breezy.adapters.polymarket_us.exec import reports as reports_module
from breezy.adapters.polymarket_us.exec import submit_chain
from breezy.adapters.polymarket_us.exec.reports import (
    _EXECUTION_DRIFT_ALLOWED_KEYS,
    _EXECUTION_KEYS,
    _MARKET_METADATA_DRIFT_ALLOWED_KEYS,
    _MARKET_METADATA_KEYS,
    _ORDER_DRIFT_ALLOWED_KEYS,
    _ORDER_KEYS,
    _USER_BALANCE_DRIFT_ALLOWED_KEYS,
    _USER_BALANCE_KEYS,
    _USER_POSITION_DRIFT_ALLOWED_KEYS,
    _USER_POSITION_KEYS,
    ORDER_STATE_TO_ORDER_STATUS,
    _key_tree,
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


def test_the_2026_09_11_drift_fields_are_declared_but_unread(
    order: dict[str, Any], instrument: BinaryOption
) -> None:
    """L-36 resolver evidence, 2026-09-11T20:20:31Z (venue order
    ``CEBPX0EVTTMX``): the live GET body carries ``action``,
    ``lastTransactTime``, ``manualOrderIndicator`` and ``outcomeSide`` beyond
    the pinned snapshot. A terminal state with a full ``cumQuantity`` maps
    cleanly once those four are declared -- none of them is read by the
    mapper, so the report is identical to the one built from the plain
    fixture."""
    drifted = {
        **order,
        "state": "ORDER_STATE_FILLED",
        "cumQuantity": order["quantity"],
        "leavesQuantity": 0,
        "action": "NEW",
        "lastTransactTime": order["createTime"],
        "manualOrderIndicator": "MANUAL_ORDER_INDICATOR_AUTOMATIC",
        "outcomeSide": "YES",
    }

    report = parse_order_status_report(
        drifted,
        instrument=instrument,
        account_id=ACCOUNT_ID,
        report_id=REPORT_ID,
        ts_init=TS_INIT,
    )

    assert report.order_status == OrderStatus.FILLED
    assert report.filled_qty == Quantity.from_str("10.00")


def test_a_fifth_undeclared_field_alongside_the_drift_set_is_still_refused(
    order: dict[str, Any], instrument: BinaryOption
) -> None:
    """The drift allowance is exactly four fields, not "anything new"."""
    with pytest.raises(ExecutionReportMappingError, match="settlementInstruction"):
        parse_order_status_report(
            {
                **order,
                "action": "NEW",
                "lastTransactTime": order["createTime"],
                "manualOrderIndicator": "MANUAL_ORDER_INDICATOR_AUTOMATIC",
                "outcomeSide": "YES",
                "settlementInstruction": "AUTO",
            },
            instrument=instrument,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )


def test_the_2026_09_12_market_metadata_drift_fields_are_declared_but_unread(
    order: dict[str, Any], instrument: BinaryOption
) -> None:
    """L-36 resolver evidence, one layer deeper, 2026-09-12T02:04:06Z (venue
    order ``CEBPX0EVTTMX``): the live GET body's ``marketMetadata`` carries
    ``eventId`` and ``subject`` beyond the pinned snapshot. Declaring both
    maps a terminal order cleanly; neither is read by the mapper."""
    drifted = {
        **order,
        "state": "ORDER_STATE_FILLED",
        "cumQuantity": order["quantity"],
        "leavesQuantity": 0,
        "marketMetadata": {
            "slug": order["marketSlug"],
            "eventId": "evt-9182",
            "subject": "SFO temperature",
        },
    }

    report = parse_order_status_report(
        drifted,
        instrument=instrument,
        account_id=ACCOUNT_ID,
        report_id=REPORT_ID,
        ts_init=TS_INIT,
    )

    assert report.order_status == OrderStatus.FILLED
    assert report.filled_qty == Quantity.from_str("10.00")


def test_a_third_undeclared_market_metadata_field_is_still_refused(
    order: dict[str, Any], instrument: BinaryOption
) -> None:
    """The nested drift allowance is exactly two fields, not "anything new"."""
    with pytest.raises(ExecutionReportMappingError, match="unicornField"):
        parse_order_status_report(
            {
                **order,
                "marketMetadata": {
                    "slug": order["marketSlug"],
                    "eventId": "evt-9182",
                    "subject": "SFO temperature",
                    "unicornField": "nope",
                },
            },
            instrument=instrument,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )


def test_unmapped_body_error_names_every_nested_drift_layer_with_no_values(
    order: dict[str, Any], instrument: BinaryOption
) -> None:
    """Diagnostic: one resolver GET failure must reveal ALL remaining drift
    at once, not one nesting layer per relaunch round -- and never a value."""
    bad = {
        **order,
        "marketMetadata": {
            "slug": order["marketSlug"],
            "unicornField": "SECRET_VALUE_42",
        },
        "weirdTopLevelField": "ANOTHER_SECRET_99",
    }

    with pytest.raises(ExecutionReportMappingError) as excinfo:
        parse_order_status_report(
            bad,
            instrument=instrument,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )

    message = str(excinfo.value)
    assert "weirdTopLevelField" in message
    assert "unicornField" in message
    assert "SECRET_VALUE_42" not in message
    assert "ANOTHER_SECRET_99" not in message


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


def test_unknown_execution_key_error_carries_the_full_key_tree_no_values(
    execution: dict[str, Any], instrument: BinaryOption
) -> None:
    """The execution top-level check reveals its whole shape too -- names
    only, never a value -- so a fill refusal shows every field at once."""
    bad = {**execution, "settlementDate": "SECRET_DATE_2026"}

    with pytest.raises(ExecutionReportMappingError) as excinfo:
        parse_fill_report(
            bad,
            instrument=instrument,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )

    message = str(excinfo.value)
    assert "settlementDate" in message
    assert "lastShares" in message
    assert "order" in message
    assert "SECRET_DATE_2026" not in message


def _parse_fill_with_commission(
    execution: dict[str, Any],
    instrument: BinaryOption,
    value: str | float,
) -> Any:
    return parse_fill_report(
        {
            **execution,
            "commissionNotionalCollected": {"value": value, "currency": "USD"},
        },
        instrument=instrument,
        account_id=ACCOUNT_ID,
        report_id=REPORT_ID,
        ts_init=TS_INIT,
    )


def test_sub_cent_commission_is_bankers_rounded_not_silently_altered_by_money(
    execution: dict[str, Any], instrument: BinaryOption
) -> None:
    """``Money(0.005, USD)`` is ``0.01``; venue bankers is ``0.00``. We take the venue rule."""
    assert Money(Decimal("0.005"), USD) == Money(Decimal("0.01"), USD)
    report = _parse_fill_with_commission(execution, instrument, "0.005")
    assert report.commission == Money(0, USD)
    already_cent = _parse_fill_with_commission(execution, instrument, "0.3125")
    assert already_cent.commission == Money(Decimal("0.31"), USD)


@pytest.mark.parametrize(
    ("raw", "booked"),
    [
        ("0.004", "0.00"),
        ("0.005", "0.00"),
        ("0.0049", "0.00"),
        ("0", "0.00"),
        ("0.015", "0.02"),
        ("0.03", "0.03"),
        ("0.012096", "0.01"),
    ],
)
def test_parse_fill_report_sub_cent_commission_is_bankers_rounded(
    execution: dict[str, Any],
    instrument: BinaryOption,
    raw: str,
    booked: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="breezy.adapters.polymarket_us.exec.reports")
    report = _parse_fill_with_commission(execution, instrument, raw)
    assert report.commission == Money(Decimal(booked), USD)
    rounded = Decimal(raw) != Decimal(booked)
    raw_nonzero = Decimal(raw) != 0
    booked_zero = Decimal(booked) == 0
    if rounded:
        assert raw in caplog.text
        assert booked in caplog.text
    if booked_zero and raw_nonzero:
        assert any(record.levelno == logging.WARNING for record in caplog.records)
    elif not rounded:
        assert not any(
            record.levelno == logging.INFO and "commission" in record.getMessage().lower()
            for record in caplog.records
        )


def test_zero_raw_fee_books_zero_without_l25_warning(
    execution: dict[str, Any],
    instrument: BinaryOption,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="breezy.adapters.polymarket_us.exec.reports")
    report = _parse_fill_with_commission(execution, instrument, "0")
    assert report.commission == Money(0, USD)
    assert not any(record.levelno == logging.WARNING for record in caplog.records)


def test_nonzero_raw_rounding_to_zero_emits_l25_warning(
    execution: dict[str, Any],
    instrument: BinaryOption,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="breezy.adapters.polymarket_us.exec.reports")
    report = _parse_fill_with_commission(execution, instrument, "0.004")
    assert report.commission == Money(0, USD)
    assert any(record.levelno == logging.WARNING for record in caplog.records)
    assert "0.004" in caplog.text


def test_quantize_commission_matches_fee_model_bankers() -> None:
    from breezy.adapters.polymarket_us.exec.reports import _quantize_commission_field
    from breezy.adapters.polymarket_us.fees import _round_bankers

    for raw in ("0.004", "0.005", "0.025", "0.035"):
        value = Decimal(raw)
        assert _quantize_commission_field(value) == _round_bankers(value, USD)


def test_numeric_commission_value_is_booked_via_str_coercion(
    execution: dict[str, Any], instrument: BinaryOption
) -> None:
    report = _parse_fill_with_commission(execution, instrument, 0.004)
    assert report.commission == Money(0, USD)


@pytest.mark.parametrize(
    "raw",
    [
        "1" + "0" * (decimal.getcontext().prec + 40),
        "1E+999999",
    ],
)
def test_pathological_commission_raises_mapping_error_not_invalid_operation(
    execution: dict[str, Any], instrument: BinaryOption, raw: str
) -> None:
    with pytest.raises(ExecutionReportMappingError):
        try:
            _parse_fill_with_commission(execution, instrument, raw)
        except InvalidOperation:
            pytest.fail("InvalidOperation escaped parse_fill_report")


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


def test_the_2026_09_12_position_drift_fields_are_declared_but_unread(
    position: dict[str, Any], instrument: BinaryOption, slug: str
) -> None:
    """Startup-evidence, 2026-09-12T02:04:03Z: the live position surface
    carries eleven fields beyond the pinned snapshot for the account's real
    (net 1) position. Declaring all eleven maps cleanly; ``netPosition`` --
    not the new ``netPositionDecimal`` -- is still what decides quantity and
    side."""
    drifted = {
        **position,
        "netPosition": "1",
        "avgPx": {"value": "0.28", "currency": "USD"},
        "baseCost": {"value": "0.28", "currency": "USD"},
        "bodPositionDecimal": "0",
        "comboLegDetails": [],
        "costPerShare": {"value": "0.28", "currency": "USD"},
        "fees": {"value": "0.00", "currency": "USD"},
        "netPositionDecimal": "1.00",
        "positionId": "pos-441",
        "qtyAvailableDecimal": "1.00",
        "qtyBoughtDecimal": "1.00",
        "qtySoldDecimal": "0.00",
    }

    mapped = parse_position_status_report(
        drifted,
        market_slug=slug,
        instrument=instrument,
        account_id=ACCOUNT_ID,
        report_id=REPORT_ID,
        ts_init=TS_INIT,
    )

    assert mapped.report.position_side == PositionSide.LONG
    assert mapped.report.quantity == Quantity.from_str("1.00")


def test_a_twelfth_undeclared_position_field_is_still_refused(
    position: dict[str, Any], slug: str, instrument: BinaryOption
) -> None:
    """The position drift allowance is exactly eleven fields, not "anything
    new"."""
    with pytest.raises(ExecutionReportMappingError, match="mysteryField"):
        parse_position_status_report(
            {
                **position,
                "avgPx": {"value": "0.28", "currency": "USD"},
                "baseCost": {"value": "0.28", "currency": "USD"},
                "bodPositionDecimal": "0",
                "comboLegDetails": [],
                "costPerShare": {"value": "0.28", "currency": "USD"},
                "fees": {"value": "0.00", "currency": "USD"},
                "netPositionDecimal": "4.00",
                "positionId": "pos-441",
                "qtyAvailableDecimal": "4.00",
                "qtyBoughtDecimal": "4.00",
                "qtySoldDecimal": "0.00",
                "mysteryField": "nope",
            },
            market_slug=slug,
            instrument=instrument,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )


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


# ---------------------------------------------------------------------------
# SP-2 I0 -- `_key_tree` / `_safe_key_name` sanitiser (RV2.1-A11)
# ---------------------------------------------------------------------------


def test_a_key_tree_escapes_control_characters_in_a_venue_key_name() -> None:
    """S-H2: a venue key name can carry raw control characters, non-printable
    bidi marks, or an ANSI escape; none may reach a log line un-escaped."""
    bad_key = "line1\nline2\rcolor\x1b[31mtext\u202eevil"
    tree = _key_tree({bad_key: "value"})

    assert "\n" not in tree
    assert "\r" not in tree
    assert "\x1b" not in tree
    assert "\u202e" not in tree
    assert ascii(bad_key) in tree


def test_a_genuine_key_truncation_leaves_the_quoted_span_unterminated() -> None:
    """SEC-M1 + CX-N1: a 512-char key truncates with the marker OUTSIDE the
    quotes, reporting the RAW length (512), not the escaped rendering's
    length. A short control-character key whose escaped form expands past
    the cap reports the SMALLER raw length, by design."""
    from breezy.adapters.polymarket_us.exec.reports import _safe_key_name

    long_key = "k" * 512
    name = _safe_key_name(long_key)

    assert name.endswith("(truncated from 512 characters)")
    opening_quote = ascii(long_key)[0]
    assert name.startswith(opening_quote)
    # A genuine truncation never closes with the quote it opened -- the
    # marker text, not a quote character, is the last thing emitted.
    assert not name.endswith(opening_quote)

    # Escaping EXPANDS a short key past the cap: 20 raw control characters
    # each escape to 4 chars (``\xNN``) plus the two quote characters, so the
    # rendered name is 82 chars -- well past `_KEY_NAME_MAX_CHARS` (64) --
    # while the RAW key is only 20 characters long.
    short_key = "\x01" * 20
    name2 = _safe_key_name(short_key)
    assert name2.endswith(f"(truncated from {len(short_key)} characters)")


def test_a_key_whose_content_spells_the_truncation_marker_stays_inside_its_quotes() -> None:
    """SEC-M1: the exact string a forged marker would use renders as a
    CLOSED quoted name, distinguishable from a genuine (unterminated)
    truncation in the previous test."""
    from breezy.adapters.polymarket_us.exec.reports import _safe_key_name

    forged_key = "x (truncated from 999 characters)"
    name = _safe_key_name(forged_key)

    assert name == ascii(forged_key)
    quote = name[0]
    assert quote in ("'", '"')
    assert name.endswith(quote)


def test_a_key_tree_bounds_its_own_depth_instead_of_recursing() -> None:
    """S-H1: unbounded venue-controlled nesting must not become unbounded
    recursion; the bound renders `<depth-capped>` well before any interpreter
    recursion limit is threatened."""
    payload: dict[str, Any] = {"leaf": "value"}
    for _ in range(2000):
        payload = {"nest": payload}

    tree = _key_tree(payload)

    assert "<depth-capped>" in tree


def test_a_key_tree_renders_every_execution_row_not_only_the_first() -> None:
    """A-B5 / RV2.1-A9: every row up to the cap is rendered, not only leg 0;
    a list past the cap declares how many more elements it carried."""
    rows_three = [{"legA": 1}, {"legB": 2}, {"legC": 3}]
    tree_three = _key_tree({"executions": rows_three})
    for name in ("legA", "legB", "legC"):
        assert ascii(name) in tree_three
    assert "more" not in tree_three

    rows_twelve = [{"k": i} for i in range(12)]
    tree_twelve = _key_tree({"executions": rows_twelve})
    assert ", +4 more" in tree_twelve


def test_a_list_without_a_leading_mapping_still_renders_the_rows_it_has() -> None:
    """AR-N4: a list with no mapping element at all keeps the plain
    `key[n]` shape; a list whose FIRST element is not a mapping but which
    contains one within the first 8 rows now renders that row -- today's
    leg-0-only rule would have rendered nothing, hiding a later-row drift."""
    tree_no_mapping = _key_tree({"items": [1, 2, 3]})
    assert f"{'items'!a}[3]" in tree_no_mapping
    assert "{" not in tree_no_mapping

    mixed = [1, {"driftedKey": "value"}, 3]
    tree_mixed = _key_tree({"items": mixed})
    assert ascii("driftedKey") in tree_mixed


def test_a_free_form_venue_map_is_rendered_opaque_at_every_depth() -> None:
    """S-M1 + AR-N3: `MarketMetadata.team` is the one reachable free-form
    map in the declared shapes; matched globally, at any depth, because
    global matching can only make MORE content opaque, never less."""
    tree = _key_tree({"team": {"secretField": "SECRET_VALUE"}})
    assert "<opaque>" in tree
    assert "secretField" not in tree
    assert "SECRET_VALUE" not in tree

    nested_tree = _key_tree({"marketMetadata": {"team": {"anotherSecret": "X"}}})
    assert "<opaque>" in nested_tree
    assert "anotherSecret" not in nested_tree


def test_a_secret_looking_key_is_sanitised_and_bounded_not_redacted() -> None:
    """Accepted residual risk (narrowed names-only invariant): a venue key
    that LOOKS like a secret is sanitised and bounded, not redacted to
    absence -- redact-to-known-set would destroy the tree's only purpose,
    naming the undeclared key."""
    secret_like_key = base64.b64encode(b"x" * 32).decode()
    assert len(secret_like_key) == 44

    tree = _key_tree({secret_like_key: "value"})

    assert ascii(secret_like_key) in tree


def test_a_key_tree_of_ten_thousand_keys_stays_bounded() -> None:
    """DoS shape: 10,000 adversarially long venue keys must still return a
    boundedly-sized string -- without a per-key cap, this many long keys
    produce an output over 10x larger."""
    payload = {f"key{i}" + "x" * 1000: "v" for i in range(10_000)}

    tree = _key_tree(payload)

    assert isinstance(tree, str)
    assert len(tree) < 10_000 * 150


def test_every_declared_allowlist_name_survives_sanitisation_unchanged() -> None:
    """AC-7 non-lossiness: every declared allowlist name (short, plain
    ASCII, no special characters) renders identically to `repr()` -- the
    sanitiser changes nothing for a legitimate, undrifted key."""
    from breezy.adapters.polymarket_us.exec.reports import _safe_key_name

    all_names = (
        _EXECUTION_KEYS
        | _ORDER_KEYS
        | _MARKET_METADATA_KEYS
        | _USER_POSITION_KEYS
        | _USER_BALANCE_KEYS
        | _ORDER_DRIFT_ALLOWED_KEYS
        | _MARKET_METADATA_DRIFT_ALLOWED_KEYS
        | _USER_POSITION_DRIFT_ALLOWED_KEYS
        | _USER_BALANCE_DRIFT_ALLOWED_KEYS
    )

    for name in all_names:
        assert _safe_key_name(name) == repr(name)


# ---------------------------------------------------------------------------
# SP-2 I4 -- 2026-09-13 MIA execution-drift capture closes R-6
#
# Evidence: node log breezy-trade-20260913T165011Z.log line 533, captured
# 2026-09-13T17:03:46Z for a live MIA BUY 1 @0.70 IOC -- see
# docs/evidence/venue/polymarket_us/CREATE_ORDER_EXECUTION_DRIFT_2026-09-13_
# MIA.md for the full sanitised key tree.
# ---------------------------------------------------------------------------


def test_the_execution_drift_allowlist_is_exactly_the_2026_09_13_capture() -> None:
    """`_EXECUTION_DRIFT_ALLOWED_KEYS` is pinned to exactly the five
    execution-level fields the 09-13 MIA live capture carried beyond the
    pinned SDK snapshot (``types/orders.py:95-108``): `commissionSpreadPx`,
    `legPrices`, `traceId`, `transactTradeDate`, `unsolicitedCancelReason`.
    A regression that widens or narrows this set without new evidence fails
    here first."""
    assert _EXECUTION_DRIFT_ALLOWED_KEYS == frozenset(
        {
            "commissionSpreadPx",
            "legPrices",
            "traceId",
            "transactTradeDate",
            "unsolicitedCancelReason",
        }
    )


def test_an_execution_key_outside_the_allowlist_is_still_refused(
    execution: dict[str, Any], instrument: BinaryOption
) -> None:
    """A sixth, still-undeclared execution-level key is refused exactly as
    before -- the drift discipline stays: only the five 09-13-observed names
    are DECLARED-BUT-UNREAD, not an open door for any future venue field."""
    drifted = {**execution, "commissionSpreadPx": {"value": "0.00", "currency": "USD"}}
    drifted["notYetObservedField"] = "unexpected"

    with pytest.raises(ExecutionReportMappingError) as excinfo:
        parse_fill_report(
            drifted,
            instrument=instrument,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )

    assert "notYetObservedField" in str(excinfo.value)


# ---------------------------------------------------------------------------
# SP-2 I0b -- the execution-type refusal stops echoing the raw value (SEC-H1)
# ---------------------------------------------------------------------------


def test_a_non_fill_execution_type_is_named_without_echoing_the_whole_value(
    execution: dict[str, Any], instrument: BinaryOption
) -> None:
    """SEC-H1: a >64-char `type` truncates with the marker outside the
    quotes; a non-string `type` renders by TYPE NAME only (AM-8: a hashable
    non-string, since a dict `type` raises `TypeError: unhashable` in the
    pre-filter before `_name_value` is ever reached)."""
    long_type = "X" * 200
    with pytest.raises(ExecutionReportMappingError) as excinfo:
        parse_fill_report(
            {**execution, "type": long_type},
            instrument=instrument,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )
    message = str(excinfo.value)
    assert long_type not in message
    assert "(truncated from 200 characters)" in message

    with pytest.raises(ExecutionReportMappingError) as excinfo2:
        parse_fill_report(
            {**execution, "type": 12345},
            instrument=instrument,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )
    message2 = str(excinfo2.value)
    assert "12345" not in message2
    assert "int" in message2


def test_the_create_path_cannot_reach_the_execution_type_refusal(
    execution: dict[str, Any],
    instrument: BinaryOption,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CHARACTERISATION (SEC-H1 coupling, AM-2/AM-3). Keeps "structurally
    unreachable" honest: `submit_chain._FILL_EXECUTION_TYPES` and this
    module's own `_FILL_EXECUTION_TYPES` are two INDEPENDENTLY declared
    frozensets (verification 29); nothing else pins them equal. A RED on the
    `==` pin below is a finding to REPORT, never fixed by widening either
    set (AM-2). The in-process perturbation is reverted automatically by the
    `monkeypatch` fixture at teardown -- `git diff --stat src/` stays empty.
    """
    assert submit_chain._FILL_EXECUTION_TYPES <= reports_module._FILL_EXECUTION_TYPES
    assert submit_chain._FILL_EXECUTION_TYPES == reports_module._FILL_EXECUTION_TYPES

    drifted = {**execution, "type": "EXECUTION_TYPE_NEW"}
    body = {"id": "ord-7f3a", "executions": [drifted]}

    # Baseline: today's pre-filter excludes the drifted row outright -- it
    # never reaches `parse_fill_report`, so no refusal is even possible.
    assert submit_chain._durable_execution(body) is None

    # AM-3: `drifted` already satisfies `_durable_execution`'s OTHER filters
    # (order.id, lastPx, lastShares, tradeId all present via the shared
    # `execution` fixture), so once the pre-filter is perturbed to widen,
    # the row is genuinely SELECTED -- the RED artefact below shows the
    # assertion, not a vacuous early exit.
    monkeypatch.setattr(
        submit_chain,
        "_FILL_EXECUTION_TYPES",
        frozenset(submit_chain._FILL_EXECUTION_TYPES | {"EXECUTION_TYPE_NEW"}),
    )
    selected = submit_chain._durable_execution(body)
    assert selected is not None

    # RED (if this coupling ever breaks live): the widened pre-filter
    # selects a row this module's OWN frozenset still refuses.
    with pytest.raises(ExecutionReportMappingError, match="EXECUTION_TYPE_NEW"):
        parse_fill_report(
            selected,
            instrument=instrument,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )


def test_a_non_hashable_execution_type_is_refused_not_a_crash(
    execution: dict[str, Any], instrument: BinaryOption
) -> None:
    """I6 enumeration: `parse_fill_report`'s own execution-type refusal
    (`execution_type not in _FILL_EXECUTION_TYPES`) is the SAME hazard class
    as `_fill_type_executions`'s pre-filter -- a dict/list `type` raises
    `TypeError: unhashable type` on the frozenset membership test, uncaught,
    for any DIRECT caller of `parse_fill_report` (this module's own public
    surface, not only the create-path pre-filter that normally screens
    `type` first). Refused, never a crash."""
    with pytest.raises(ExecutionReportMappingError) as excinfo:
        parse_fill_report(
            {**execution, "type": {"nested": 1}},
            instrument=instrument,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )
    assert "dict" in str(excinfo.value)


# ---------------------------------------------------------------------------
# I8 (nits) -- opaque-key value guard + inner truncation marker assertion
# ---------------------------------------------------------------------------


def test_a_scalar_team_value_is_not_rendered_opaque() -> None:
    """I8(a): the opaque branch dropped the plan's value-type guard -- a
    SCALAR `team` (never a free-form map in life, but the sanitiser must not
    assume it) is not `<opaque>`; it falls to the plain scalar branch, same
    as any other key with a scalar value. Only a `team` whose value is
    actually a `Mapping` or `list` (the one declared free-form-map shape)
    is opaque."""
    tree = _key_tree({"team": "not-a-map"})
    assert "<opaque>" not in tree
    assert ascii("team") in tree
