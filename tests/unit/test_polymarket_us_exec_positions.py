"""R-3: the POSITION mapper -- ``UserPosition`` -> native ``PositionStatusReport``.

Authority: ``docs/plans/EXEC_SPINE_2026-09-01.md`` section R-3. This suite is
READ/MAP ONLY -- nothing here submits, cancels, or contacts a venue.

WHY THE POSITION MAPPER HAS ITS OWN SUITE
------------------------------------------

Its two hazards are unlike the order and fill mappers', and both are about what
the payload does NOT say.

* **A position carries no market identity of its own.** ``UserPosition``
  (``types/portfolio.py:21-34``) declares no ``marketSlug``; the authoritative
  slug is the DICT KEY of ``GetUserPositionsResponse.positions``
  (``:45-50``), which the mapper never sees. ``marketMetadata`` is OPTIONAL and
  the TypedDict is ``total=False``, so a payload with no metadata block used to
  reach the native constructor with NO market check at all -- market A's
  position binding to instrument B. With Nautilus's ``generate_missing_orders``
  defaulting True, reconciliation then synthesises a fill and invents exposure
  in a market Breezy never traded. So the caller passes the slug and the check
  is UNCONDITIONAL, and this suite pins the metadata-absent path specifically.

* **A settled position looks exactly like a live one.** ``expired`` is declared
  by the snapshot but has no slot on ``PositionStatusReport``. Dropped, a
  resolved weather binary reporting ``expired: True, netPosition: "4"`` maps to
  a LONG-4 report indistinguishable from tradeable risk. It is returned
  ALONGSIDE the native report instead -- see ``MappedPosition``.

A negative ``netPosition`` is REPORTED, not refused: Breezy is long-only and
never opens one, but a position it did not open is precisely the risk an
operator must be told about.

Siblings: the decode and balances mapper in
``test_polymarket_us_exec_endpoints.py``, the order and fill mappers in
``test_polymarket_us_exec_reports.py``, the allowlist drift check in
``test_polymarket_us_exec_snapshot_drift.py``. Shared payload shapes live in
``polymarket_us_exec_shapes.py``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from nautilus_trader.execution.reports import PositionStatusReport
from nautilus_trader.model.enums import PositionSide
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Quantity

from breezy.adapters.polymarket_us.errors import ExecutionReportMappingError
from breezy.adapters.polymarket_us.exec.reports import (
    derive_position_cost_basis,
    parse_position_status_report,
)
from tests.unit.polymarket_us_exec_shapes import (
    ACCOUNT_ID,
    REPORT_ID,
    TS_EVENT_NANOS,
    TS_INIT,
    build_instrument,
    build_position,
)


@pytest.fixture
def instrument() -> BinaryOption:
    return build_instrument()


@pytest.fixture
def slug(instrument: BinaryOption) -> str:
    return str(instrument.raw_symbol)


@pytest.fixture
def position(slug: str) -> dict[str, Any]:
    return build_position(slug)


# ---------------------------------------------------------------------------
# UserPosition -> native PositionStatusReport
# ---------------------------------------------------------------------------


def test_position_status_report_round_trip(
    position: dict[str, Any], instrument: BinaryOption, slug: str
) -> None:
    report = parse_position_status_report(
        position,
        market_slug=slug,
        instrument=instrument,
        account_id=ACCOUNT_ID,
        report_id=REPORT_ID,
        ts_init=TS_INIT,
    ).report

    assert isinstance(report, PositionStatusReport)
    assert report.account_id == ACCOUNT_ID
    assert report.instrument_id == instrument.id
    assert report.position_side == PositionSide.LONG
    assert report.quantity == Quantity.from_str("4.00")
    assert report.venue_position_id is None
    assert report.ts_last == TS_EVENT_NANOS
    assert report.ts_init == TS_INIT


def test_zero_net_position_is_flat(
    position: dict[str, Any], instrument: BinaryOption, slug: str
) -> None:
    report = parse_position_status_report(
        {**position, "netPosition": "0"},
        market_slug=slug,
        instrument=instrument,
        account_id=ACCOUNT_ID,
        report_id=REPORT_ID,
        ts_init=TS_INIT,
    ).report

    assert report.position_side == PositionSide.FLAT
    assert report.quantity == Quantity.from_str("0.00")


def test_a_negative_net_position_is_reported_not_refused(
    position: dict[str, Any], instrument: BinaryOption, slug: str
) -> None:
    """Breezy never opens one, but refusing to REPORT one hides real risk."""
    report = parse_position_status_report(
        {**position, "netPosition": "-4"},
        market_slug=slug,
        instrument=instrument,
        account_id=ACCOUNT_ID,
        report_id=REPORT_ID,
        ts_init=TS_INIT,
    ).report

    assert report.quantity == Quantity.from_str("4.00")
    assert report.signed_decimal_qty == Decimal("-4.00")


def test_position_average_open_price_is_not_invented(
    position: dict[str, Any], instrument: BinaryOption, slug: str
) -> None:
    """``UserPosition`` carries no average-entry field. R-3 does not derive one.

    ``cost``/``qtyBought`` LOOK like a derivation, but whether ``cost`` is net
    of sells is undefined by the snapshot and unobserved live. The plan assigns
    the entry price to R-4's durable fill record (OQ-1); guessing it here would
    put an unverified number into reconciliation.
    """
    report = parse_position_status_report(
        position,
        market_slug=slug,
        instrument=instrument,
        account_id=ACCOUNT_ID,
        report_id=REPORT_ID,
        ts_init=TS_INIT,
    ).report

    assert report.avg_px_open is None


def test_position_for_another_market_is_refused(
    position: dict[str, Any], instrument: BinaryOption
) -> None:
    with pytest.raises(ExecutionReportMappingError):
        parse_position_status_report(
            {**position, "marketMetadata": {"slug": "tc-temp-nychigh-2026-08-25-lt80f"}},
            market_slug="tc-temp-nychigh-2026-08-25-lt80f",
            instrument=instrument,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )


def test_unknown_position_key_is_refused(
    position: dict[str, Any], instrument: BinaryOption, slug: str
) -> None:
    with pytest.raises(ExecutionReportMappingError, match="lockedQty"):
        parse_position_status_report(
            {**position, "lockedQty": "1"},
            market_slug=slug,
            instrument=instrument,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )


def test_position_missing_the_net_quantity_is_refused(
    position: dict[str, Any], instrument: BinaryOption, slug: str
) -> None:
    incomplete = {k: v for k, v in position.items() if k != "netPosition"}

    with pytest.raises(ExecutionReportMappingError, match="netPosition"):
        parse_position_status_report(
            incomplete,
            market_slug=slug,
            instrument=instrument,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )


# ---------------------------------------------------------------------------
# Position -- the market binding and the settled-exposure flag
# ---------------------------------------------------------------------------


def test_a_position_without_market_metadata_is_still_bound_to_its_market(
    position: dict[str, Any], instrument: BinaryOption
) -> None:
    """HIGH: ``UserPosition`` is ``total=False``, so ``marketMetadata`` may be ABSENT.

    The market check used to sit inside ``if metadata is not None``, so an
    absent block meant NO market check at all -- market A's position booking
    onto instrument B. With ``generate_missing_orders`` defaulting True,
    Nautilus then synthesises a fill and invents exposure in a market never
    traded. The authoritative slug is the DICT KEY of
    ``GetUserPositionsResponse.positions`` (``types/portfolio.py:45-50``), so
    the caller must pass it and the check must be unconditional.
    """
    without_metadata = {k: v for k, v in position.items() if k != "marketMetadata"}

    with pytest.raises(ExecutionReportMappingError):
        parse_position_status_report(
            without_metadata,
            market_slug="tc-temp-nychigh-2026-08-25-lt80f",
            instrument=instrument,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )


def test_a_position_without_market_metadata_maps_on_its_authoritative_slug(
    position: dict[str, Any], instrument: BinaryOption, slug: str
) -> None:
    without_metadata = {k: v for k, v in position.items() if k != "marketMetadata"}

    mapped = parse_position_status_report(
        without_metadata,
        market_slug=slug,
        instrument=instrument,
        account_id=ACCOUNT_ID,
        report_id=REPORT_ID,
        ts_init=TS_INIT,
    )

    assert mapped.report.position_side == PositionSide.LONG


def test_position_metadata_that_disagrees_with_the_authoritative_slug_is_refused(
    position: dict[str, Any], instrument: BinaryOption, slug: str
) -> None:
    """Two slugs that disagree is a venue contradiction, not a preference."""
    with pytest.raises(ExecutionReportMappingError):
        parse_position_status_report(
            {**position, "marketMetadata": {"slug": "tc-temp-nychigh-2026-08-25-lt80f"}},
            market_slug=slug,
            instrument=instrument,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )


def test_an_expired_position_is_reported_as_expired_not_as_live_risk(
    position: dict[str, Any], instrument: BinaryOption, slug: str
) -> None:
    """A resolved weather binary is settled, not tradeable exposure.

    ``PositionStatusReport`` has no slot for it, so ``expired`` is returned
    ALONGSIDE the native report rather than dropped -- an exposure cap that
    counts settled contracts as tradeable is over-stating risk it cannot act on.
    """
    mapped = parse_position_status_report(
        {**position, "expired": True},
        market_slug=slug,
        instrument=instrument,
        account_id=ACCOUNT_ID,
        report_id=REPORT_ID,
        ts_init=TS_INIT,
    )

    assert mapped.expired is True
    assert mapped.report.position_side == PositionSide.LONG
    assert mapped.report.quantity == Quantity.from_str("4.00")


def test_a_live_position_reports_expired_false(
    position: dict[str, Any], instrument: BinaryOption, slug: str
) -> None:
    mapped = parse_position_status_report(
        position,
        market_slug=slug,
        instrument=instrument,
        account_id=ACCOUNT_ID,
        report_id=REPORT_ID,
        ts_init=TS_INIT,
    )

    assert mapped.expired is False


def test_a_position_without_the_expired_flag_is_refused_not_assumed_live(
    position: dict[str, Any], instrument: BinaryOption, slug: str
) -> None:
    """An absent settlement flag is not a "still live" flag."""
    without_expired = {k: v for k, v in position.items() if k != "expired"}

    with pytest.raises(ExecutionReportMappingError, match="expired"):
        parse_position_status_report(
            without_expired,
            market_slug=slug,
            instrument=instrument,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )


def test_a_malformed_position_timestamp_stays_inside_the_mapping_taxonomy(
    position: dict[str, Any], instrument: BinaryOption, slug: str
) -> None:
    """``updateTime`` is the third field whose refusal escaped the taxonomy."""
    with pytest.raises(ExecutionReportMappingError, match="updateTime"):
        parse_position_status_report(
            {**position, "updateTime": 1_787_617_188},
            market_slug=slug,
            instrument=instrument,
            account_id=ACCOUNT_ID,
            report_id=REPORT_ID,
            ts_init=TS_INIT,
        )



# ---------------------------------------------------------------------------
# `derive_position_cost_basis` -- the SECOND source of `avg_px_open`, sound
# only while `qtySold == 0`
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda p: p.pop("qtySold"), "missing qtySold"),
        (lambda p: p.pop("qtyBought"), "missing qtyBought"),
        (lambda p: p.pop("cost"), "missing cost"),
        (lambda p: p.__setitem__("qtySold", "1"), "qtySold != 0"),
        (lambda p: p.__setitem__("qtyBought", "0"), "qtyBought == 0"),
        (lambda p: p.__setitem__("qtyBought", "-1"), "qtyBought < 0"),
        (
            lambda p: p.__setitem__("cost", {"value": "0", "currency": "USD"}),
            "cost == 0",
        ),
        (
            lambda p: p.__setitem__("cost", {"value": "-2.08", "currency": "USD"}),
            "cost < 0",
        ),
    ],
    ids=[
        "missing-qtySold",
        "missing-qtyBought",
        "missing-cost",
        "qtySold-nonzero",
        "qtyBought-zero",
        "qtyBought-negative",
        "cost-zero",
        "cost-negative",
    ],
)
def test_derive_position_cost_basis_refuses_by_returning_none(
    position: dict[str, Any],
    mutation: Any,
    reason: str,
) -> None:
    """Every condition that makes `cost / qtyBought` unsound returns `None`,
    never an exception and never a best-effort number. `None` is the caller's
    signal to forward the position UNPRICED plus a refusal -- an exception
    here would instead escape to `generate_mass_status`'s outer handler and
    (before EXEC_SPINE R-4's review fix) drop every OTHER position too."""
    payload = dict(position)
    mutation(payload)

    assert derive_position_cost_basis(payload) is None, reason


def test_derive_position_cost_basis_happy_path_is_cost_over_qty_bought(
    position: dict[str, Any],
) -> None:
    """`qtySold == 0` removes the netting ambiguity: `cost / qtyBought` is the
    entry price under either reading of what `cost` nets."""
    payload = {
        **position,
        "qtySold": "0",
        "qtyBought": "4",
        "cost": {"value": "2.08", "currency": "USD"},
    }

    assert derive_position_cost_basis(payload) == Decimal("2.08") / Decimal(4)
