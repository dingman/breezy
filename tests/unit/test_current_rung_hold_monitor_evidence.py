"""RED-first tests for the intra-day position monitor's pure evidence
builder (INC-2, ``docs/plans/INTRADAY_POSITION_MONITOR_2026-09-15.md`` §2/§6).

Covers: one-sided book, insufficient depth, the NO-leg mark inversion
(Rev 2.1 addendum), cell-key parity with the frozen archive table
``evaluate_decision`` itself reads, the exit fee computed off ``mark_vwap``
(never ``fill_px``), and the ``p_hold_undefined`` hour-outside-coverage case.
"""

from __future__ import annotations

from decimal import Decimal

from nautilus_trader.model.data import BookOrder, OrderBookDepth10
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity

from breezy.strategy.current_rung_hold.archive_table import P_HOLD_LOWER, P_HOLD_UPPER
from breezy.strategy.current_rung_hold.monitor_evidence import (
    build_monitor_evidence,
    exit_fee,
    p_hold_at,
    walk_exit_vwap,
)

_INSTRUMENT_ID = InstrumentId.from_str("sfo-86-87.POLYMARKET_US")
_FEE_COEFFICIENT = Decimal("0.06")

#: A real, populated cell (`archive_table.py:229,476`) used for the parity
#: test -- never a fabricated golden value.
_STATION = "SFO"
_SEASON = "DJF"
_HOUR_LST = 14
_WIDTH_CODE = 0
_M_CODE = 0
_KEY = (_STATION, _SEASON, _HOUR_LST, _WIDTH_CODE, _M_CODE)


def _order(side: OrderSide, price: str, size: str) -> BookOrder:
    return BookOrder(side, Price(float(price), 2), Quantity(float(size), 2), 0)


def _depth(
    *,
    bids: tuple[tuple[str, str], ...],
    asks: tuple[tuple[str, str], ...],
    ts_ns: int = 1_000,
) -> OrderBookDepth10:
    """Build a real ``OrderBookDepth10`` -- Nautilus requires equal bid/ask
    lengths BEFORE its own null-padding, so a "one-sided" book here is
    represented by zero-size filler levels on the empty side, exactly the
    shape a real one-sided venue snapshot takes.
    """
    bid_orders = [_order(OrderSide.BUY, p, s) for p, s in bids]
    ask_orders = [_order(OrderSide.SELL, p, s) for p, s in asks]
    n = max(len(bid_orders), len(ask_orders))
    while len(bid_orders) < n:
        bid_orders.append(_order(OrderSide.BUY, "0", "0"))
    while len(ask_orders) < n:
        ask_orders.append(_order(OrderSide.SELL, "0", "0"))
    return OrderBookDepth10(
        instrument_id=_INSTRUMENT_ID,
        bids=bid_orders,
        asks=ask_orders,
        bid_counts=[1] * len(bid_orders),
        ask_counts=[1] * len(ask_orders),
        flags=0,
        sequence=0,
        ts_event=ts_ns,
        ts_init=ts_ns,
    )


def _evidence(**overrides: object) -> object:
    base: dict[str, object] = {
        "ts_ns": 1_000,
        "instrument_id": str(_INSTRUMENT_ID),
        "station": _STATION,
        "climate_day": "2026-09-01",
        "season": _SEASON,
        "hour_lst": _HOUR_LST,
        "width_code": _WIDTH_CODE,
        "m_code": _M_CODE,
        "leg": "YES",
        "entry_context": "live",
        "fill_px": Decimal("0.40"),
        "held_qty": 1,
        "running_max_lower": 86,
        "running_max_upper": 86,
        "staleness_ns": 0,
        "book_staleness_ns": 0,
        "rung_low": 86,
        "rung_high": 87,
        "depth": None,
        "fee_coefficient": _FEE_COEFFICIENT,
        "p_hold_at_entry": Decimal("0.6293"),
    }
    base.update(overrides)
    return build_monitor_evidence(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# walk_exit_vwap
# --------------------------------------------------------------------------


def test_one_sided_book_yields_no_mark_and_insufficient_depth() -> None:
    # Arrange: no real bid levels at all (YES walks bids).
    depth = _depth(bids=(), asks=(("0.55", "5"),))

    # Act
    vwap, sufficient = walk_exit_vwap(depth, "YES", 1)

    # Assert
    assert vwap is None
    assert sufficient is False


def test_insufficient_displayed_size_for_the_held_quantity_yields_no_mark() -> None:
    # Arrange: only 2 contracts displayed on the bid, but 5 are held.
    depth = _depth(bids=(("0.60", "2"),), asks=(("0.65", "5"),))

    # Act
    vwap, sufficient = walk_exit_vwap(depth, "YES", 5)

    # Assert
    assert vwap is None
    assert sufficient is False


def test_yes_leg_walks_bids_best_first_across_two_levels_with_exact_vwap() -> None:
    # Arrange: 2 @ 0.60 then 3 @ 0.50 -- walking 4 contracts crosses levels.
    depth = _depth(bids=(("0.60", "2"), ("0.50", "3")), asks=(("0.99", "1"),))

    # Act
    vwap, sufficient = walk_exit_vwap(depth, "YES", 4)

    # Assert: (2*0.60 + 2*0.50) / 4 == 0.55, exact in Decimal.
    assert sufficient is True
    assert vwap == Decimal("0.55")


def test_no_leg_walks_asks_and_inverts_never_the_bid_side() -> None:
    # Arrange: bids and asks deliberately differ so walking the wrong side
    # (bids) would produce a different, wrong answer.
    depth = _depth(bids=(("0.10", "10"),), asks=(("0.30", "2"), ("0.40", "2")))

    # Act
    vwap, sufficient = walk_exit_vwap(depth, "NO", 4)

    # Assert: ask VWAP is (2*0.30 + 2*0.40)/4 == 0.35; NO exit == 1 - 0.35.
    assert sufficient is True
    assert vwap == Decimal("0.65")


def test_zero_size_levels_are_skipped_when_walking() -> None:
    # Arrange: a zero-size level sits ahead of the real one.
    depth = _depth(bids=(("0.70", "0"), ("0.60", "5")), asks=(("0.90", "1"),))

    # Act
    vwap, sufficient = walk_exit_vwap(depth, "YES", 3)

    # Assert: only the 0.60 level should ever be consulted.
    assert sufficient is True
    assert vwap == Decimal("0.60")


# --------------------------------------------------------------------------
# p_hold_at -- cell-key parity with evaluate_decision's own lookup path
# --------------------------------------------------------------------------


def test_p_hold_at_yes_matches_the_frozen_tables_lower_bound_exactly() -> None:
    assert p_hold_at(
        station=_STATION, season=_SEASON, hour_lst=_HOUR_LST,
        width_code=_WIDTH_CODE, m_code=_M_CODE, leg="YES",
    ) == P_HOLD_LOWER[_KEY]


def test_p_hold_at_no_inverts_the_frozen_tables_upper_bound_exactly() -> None:
    expected = Decimal(1) - P_HOLD_UPPER[_KEY]
    assert p_hold_at(
        station=_STATION, season=_SEASON, hour_lst=_HOUR_LST,
        width_code=_WIDTH_CODE, m_code=_M_CODE, leg="NO",
    ) == expected


def test_p_hold_at_is_none_for_an_hour_outside_the_tables_coverage() -> None:
    # Arrange/Act: hour 3 LST is nowhere in the frozen table (12-16 only).
    result = p_hold_at(
        station=_STATION, season=_SEASON, hour_lst=3,
        width_code=_WIDTH_CODE, m_code=_M_CODE, leg="YES",
    )

    # Assert
    assert result is None


# --------------------------------------------------------------------------
# exit_fee -- off mark_vwap, never fill_px
# --------------------------------------------------------------------------


def test_exit_fee_is_computed_off_the_exit_price_not_the_fill_price() -> None:
    # Arrange: fill_px != mark_vwap; fee must use mark_vwap (0.40) only --
    # theta*p*(1-p) == 0.06*0.40*0.60 == 0.0144 -> banker's-rounded $0.01.
    mark_vwap = Decimal("0.40")
    fill_px = Decimal("0.50")

    # Act
    fee_at_mark = exit_fee(mark_vwap, 1, _FEE_COEFFICIENT)
    fee_at_fill = exit_fee(fill_px, 1, _FEE_COEFFICIENT)

    # Assert
    assert fee_at_mark == Decimal("0.01")
    assert fee_at_mark != fee_at_fill


def test_exit_fee_scales_linearly_with_quantity() -> None:
    assert exit_fee(Decimal("0.40"), 3, _FEE_COEFFICIENT) == Decimal("0.03")


# --------------------------------------------------------------------------
# build_monitor_evidence -- integration of the pieces above
# --------------------------------------------------------------------------


def test_build_monitor_evidence_with_no_depth_reports_missing_mark() -> None:
    evidence = _evidence(depth=None)

    assert evidence.mark_vwap is None
    assert evidence.mark_source == "missing"
    assert evidence.depth_sufficient is False
    assert evidence.exit_fee_at_mark is None
    assert evidence.unrealized_pnl is None
    assert evidence.recoverable_value is None


def test_build_monitor_evidence_yes_leg_computes_pnl_and_recoverable_value() -> None:
    depth = _depth(bids=(("0.50", "1"),), asks=(("0.99", "1"),))
    evidence = _evidence(depth=depth, fill_px=Decimal("0.40"), held_qty=1)

    assert evidence.mark_source == "depth_walk"
    assert evidence.mark_vwap == Decimal("0.50")
    # fee = 0.06*0.50*0.50 = 0.015 -> banker's rounds to 0.02.
    assert evidence.exit_fee_at_mark == exit_fee(Decimal("0.50"), 1, _FEE_COEFFICIENT)
    assert evidence.unrealized_pnl == (Decimal("0.50") - Decimal("0.40")) * 1
    assert evidence.recoverable_value == Decimal("0.50") * 1 - evidence.exit_fee_at_mark


def test_build_monitor_evidence_p_hold_undefined_outside_hours() -> None:
    evidence = _evidence(hour_lst=3)

    assert evidence.p_hold_at_t is None
    assert evidence.hour_lst == 3


def test_build_monitor_evidence_cell_key_matches_the_lookup_key() -> None:
    evidence = _evidence()

    assert evidence.cell_key == _KEY


def test_monitor_evidence_to_dict_serialises_decimals_as_strings() -> None:
    depth = _depth(bids=(("0.50", "1"),), asks=(("0.99", "1"),))
    evidence = _evidence(depth=depth)

    payload = evidence.to_dict()

    assert payload["mark_vwap"] == "0.5"
    assert payload["fill_px"] == "0.40"
    assert isinstance(payload["cell_key"], list)


def test_no_price_field_in_output_is_ever_a_float() -> None:
    depth = _depth(bids=(("0.50", "1"),), asks=(("0.99", "1"),))
    evidence = _evidence(depth=depth)

    for field in (
        evidence.p_hold_at_entry,
        evidence.p_hold_at_t,
        evidence.fill_px,
        evidence.mark_vwap,
        evidence.exit_fee_at_mark,
        evidence.unrealized_pnl,
        evidence.recoverable_value,
    ):
        if field is not None:
            assert isinstance(field, Decimal)
