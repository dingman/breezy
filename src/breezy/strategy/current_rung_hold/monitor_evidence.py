"""Pure evidence-building for the intra-day shadow position monitor (INC-2).

L-1: GAP. Nautilus has no leg-aware, Depth10-walked mark for a held
position -- ``Portfolio.unrealized_pnl`` marks a LONG off
``Cache.price(BID)`` from a ``QuoteTick`` only (never Depth10, never leg
aware). This module is the authored gap-filler
(``docs/plans/INTRADAY_POSITION_MONITOR_2026-09-15.md`` Rev 2 + 2.1 addendum,
§2/§4). It is a PURE module: no ``nautilus_trader`` runtime state, no
Nautilus strategy/clock/cache access, no I/O. Every fact it needs (the
running-max interval, staleness, rung geometry, a snapshotted
``OrderBookDepth10`` or ``None``) is a plain value or Nautilus VALUE OBJECT
(``OrderBookDepth10``/``BookOrder``/``Price``/``Quantity`` -- themselves
pure, immutable data) passed in by the caller (``position_monitor.py``,
INC-5).

Fee reuse (D5): :func:`exit_fee` calls the SAME per-contract fee helper
``evaluate_decision``/``_finalize_take`` uses
(``breezy.strategy.current_rung_hold.decision._fee``, ``theta * p * (1 - p)``
banker's-rounded to the cent) rather than re-deriving the 0.06 coefficient
inline -- the two paths can never silently drift.

NO-leg mark rule (Rev 2.1 addendum, unambiguous): there is only ONE live
order book per market (the YES-denominated one). To value or hypothetically
exit a held NO position, walk the YES book's ASK side
(``depth.asks``) for the held quantity to get ``ask_walk_vwap``, then the NO
exit price is ``1 - ask_walk_vwap``. A YES position walks ``depth.bids``
directly. Never walk ``depth.bids`` for a NO leg.

NO-leg PnL sign convention (documented per the brief, not re-derived): a NO
take BUYS the NO-leg instrument (never a short of the YES one -- see
``decision.Take``'s docstring); the fill price Breezy books for a NO fill is
already ``instrument_price_for_leg("no", wire_price)`` --
i.e. already inverted into the NO instrument's OWN price domain
(``breezy.adapters.polymarket_us.leg_prices.instrument_price_for_leg``) --
and the execution client's ``_RECORD_SIGNS`` records every Breezy fill
(YES or NO) under the single ``BUY``/``LONG_ONLY_SIDE`` sign (+1): Breezy
never submits a SELL, so both legs are booked as a plain LONG in their own
price domain. Consequently ``mark_vwap`` (computed above, ALSO in the held
leg's own price domain: identity for YES, ``1 - ask_walk_vwap`` for NO) is
directly comparable to ``fill_px`` with NO extra sign flip:
``unrealized_pnl = (mark_vwap - fill_px) * held_qty`` for BOTH legs.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Final, Literal

from breezy.strategy.current_rung_hold.archive_table import P_HOLD_LOWER, P_HOLD_UPPER
from breezy.strategy.current_rung_hold.decision import _fee as _entry_fee

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nautilus_trader.model.data import OrderBookDepth10

__all__ = [
    "Leg",
    "MonitorEvidence",
    "build_monitor_evidence",
    "exit_fee",
    "p_hold_at",
    "walk_exit_vwap",
]

#: Deliberately UPPERCASE, distinct from ``decision.py``'s lowercase
#: ``Literal["yes", "no"]`` side convention (and from
#: ``adapters.polymarket_us.leg_prices.Leg``, also lowercase) -- this module's
#: brief specifies "YES"/"NO" so a monitor record is never mistaken for a
#: raw ``DecisionInputs.side``/wire-leg value at a glance.
Leg = Literal["YES", "NO"]

_ONE: Final[Decimal] = Decimal(1)
_ZERO: Final[Decimal] = Decimal(0)

_CellKey = tuple[str, str, int, int, int]


@dataclass(frozen=True, slots=True, kw_only=True)
class MonitorEvidence:
    """Every fact :func:`evaluate_monitor` (``monitor_decision.py``) needs
    for one evaluation of one held position, built fresh each time -- never
    mutated, never accumulated here (see the plan's M5: held qty and every
    other fact are read fresh on every evaluation by the caller).
    """

    ts_ns: int
    instrument_id: str
    station: str
    climate_day: str
    leg: Leg
    cell_key: _CellKey
    p_hold_at_entry: Decimal | None
    p_hold_at_t: Decimal | None
    fill_px: Decimal
    held_qty: int
    mark_vwap: Decimal | None
    mark_source: Literal["depth_walk", "missing"]
    spread: Decimal | None
    depth_sufficient: bool
    staleness_ns: int | None
    book_staleness_ns: int | None
    running_max_lower: int
    running_max_upper: int
    rung_low: int | None
    rung_high: int | None
    exit_fee_at_mark: Decimal | None
    unrealized_pnl: Decimal | None
    recoverable_value: Decimal | None
    hour_lst: int
    entry_context: str

    def to_dict(self) -> dict[str, object]:
        """Explicit field-by-field mapping (``dataclasses.asdict`` is banned
        repo-wide). ``Decimal`` fields serialise to ``str``; the tuple
        ``cell_key`` serialises to a ``list`` for JSON/parquet friendliness.
        """
        return {
            "ts_ns": self.ts_ns,
            "instrument_id": self.instrument_id,
            "station": self.station,
            "climate_day": self.climate_day,
            "leg": self.leg,
            "cell_key": list(self.cell_key),
            "p_hold_at_entry": _decimal_or_none(self.p_hold_at_entry),
            "p_hold_at_t": _decimal_or_none(self.p_hold_at_t),
            "fill_px": str(self.fill_px),
            "held_qty": self.held_qty,
            "mark_vwap": _decimal_or_none(self.mark_vwap),
            "mark_source": self.mark_source,
            "spread": _decimal_or_none(self.spread),
            "depth_sufficient": self.depth_sufficient,
            "staleness_ns": self.staleness_ns,
            "book_staleness_ns": self.book_staleness_ns,
            "running_max_lower": self.running_max_lower,
            "running_max_upper": self.running_max_upper,
            "rung_low": self.rung_low,
            "rung_high": self.rung_high,
            "exit_fee_at_mark": _decimal_or_none(self.exit_fee_at_mark),
            "unrealized_pnl": _decimal_or_none(self.unrealized_pnl),
            "recoverable_value": _decimal_or_none(self.recoverable_value),
            "hour_lst": self.hour_lst,
            "entry_context": self.entry_context,
        }


def _decimal_or_none(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def walk_exit_vwap(
    depth: OrderBookDepth10, leg: Leg, qty: int
) -> tuple[Decimal | None, bool]:
    """Walk the correct side of ``depth`` for ``qty`` contracts, best-first.

    YES walks ``depth.bids`` directly. NO walks ``depth.asks`` and returns
    ``1 - ask_walk_vwap`` (Rev 2.1 addendum's NO-leg rule -- see the module
    docstring). Levels with zero size are skipped. Returns ``(None, False)``
    when the relevant side is empty or the displayed size never reaches
    ``qty`` (one-sided or insufficient depth) -- never a partial-fill VWAP,
    never an interpolated price.
    """
    if leg == "YES":
        levels = depth.bids
    elif leg == "NO":
        levels = depth.asks
    else:  # pragma: no cover - Leg is a closed Literal; defence in depth.
        raise ValueError(f"unknown leg {leg!r}; expected 'YES' or 'NO'")

    remaining = Decimal(qty)
    filled = _ZERO
    cost = _ZERO
    for level in levels:
        size = level.size.as_decimal()
        if size <= _ZERO:
            continue
        take = min(size, remaining)
        cost += take * level.price.as_decimal()
        filled += take
        remaining -= take
        if remaining <= _ZERO:
            break

    if filled <= _ZERO or filled < Decimal(qty):
        return None, False

    vwap = cost / filled
    if leg == "NO":
        vwap = _ONE - vwap
    return vwap, True


def _book_spread(depth: OrderBookDepth10) -> Decimal | None:
    """Top-of-book ask minus bid, or ``None`` when either side is empty."""
    bids = [order for order in depth.bids if order.size.as_decimal() > _ZERO]
    asks = [order for order in depth.asks if order.size.as_decimal() > _ZERO]
    if not bids or not asks:
        return None
    best_ask: Decimal = asks[0].price.as_decimal()
    best_bid: Decimal = bids[0].price.as_decimal()
    return best_ask - best_bid


def exit_fee(price: Decimal, qty: int, fee_coefficient: Decimal) -> Decimal:
    """The total exit-side fee for ``qty`` contracts at the EXIT price.

    ``price`` here is ALWAYS the walked exit price (``mark_vwap``), never
    ``fill_px`` (D4/D5, plan §2): the fee owed on exit is a function of the
    price the exit would clear at, not the price the position was entered
    at. Reuses :func:`breezy.strategy.current_rung_hold.decision._fee`'s
    exact per-contract formula and rounding.
    """
    return _entry_fee(price, fee_coefficient) * qty


def p_hold_at(
    *,
    station: str,
    season: str,
    hour_lst: int,
    width_code: int,
    m_code: int,
    leg: Leg,
) -> Decimal | None:
    """The same estimand ``evaluate_decision`` looked up at entry, re-read
    for THIS ``(station, season, hour_lst, width_code, m_code)`` cell.

    YES: ``P_HOLD_LOWER[key]`` -- identical to ``evaluate_decision``'s YES
    dispatch. NO: ``1 - P_HOLD_UPPER[key]`` -- identical to
    ``_evaluate_no_side``'s ``p_miss_lower`` derivation. Returns ``None``
    when the key is absent from the frozen table (an under-powered cell, or
    an hour outside the table's 12-16 coverage) -- never ``0`` (SS1) --
    callers record reason ``p_hold_undefined``. Never extends the table.
    """
    key: _CellKey = (station, season, hour_lst, width_code, m_code)
    if leg == "YES":
        return P_HOLD_LOWER.get(key)
    if leg == "NO":
        upper = P_HOLD_UPPER.get(key)
        return None if upper is None else _ONE - upper
    raise ValueError(f"unknown leg {leg!r}; expected 'YES' or 'NO'")  # pragma: no cover


def build_monitor_evidence(
    *,
    ts_ns: int,
    instrument_id: str,
    station: str,
    climate_day: str,
    season: str,
    hour_lst: int,
    width_code: int,
    m_code: int,
    leg: Leg,
    entry_context: str,
    fill_px: Decimal,
    held_qty: int,
    running_max_lower: int,
    running_max_upper: int,
    staleness_ns: int | None,
    book_staleness_ns: int | None,
    rung_low: int | None,
    rung_high: int | None,
    depth: OrderBookDepth10 | None,
    fee_coefficient: Decimal,
    p_hold_at_entry: Decimal | None,
) -> MonitorEvidence:
    """Build one :class:`MonitorEvidence` snapshot from already-computed
    plain values -- ``running_max_lower``/``upper``, ``rung_low``/``high``,
    staleness, etc. are the CALLER's responsibility (``position_monitor.py``,
    INC-5), computed there via ``RunningExtremeAccumulator.value_at``/
    ``staleness_ns`` and ``tick_eval.width_and_m``/
    ``instrument_rung_is_current`` exactly as ``evaluate_decision``'s own
    caller does. This function stays pure: it never reads a clock, cache, or
    accumulator itself.
    """
    p_hold_t = p_hold_at(
        station=station,
        season=season,
        hour_lst=hour_lst,
        width_code=width_code,
        m_code=m_code,
        leg=leg,
    )

    mark_vwap: Decimal | None = None
    depth_sufficient = False
    spread: Decimal | None = None
    if depth is not None:
        mark_vwap, depth_sufficient = walk_exit_vwap(depth, leg, held_qty)
        spread = _book_spread(depth)

    mark_source: Literal["depth_walk", "missing"] = (
        "depth_walk" if mark_vwap is not None else "missing"
    )

    exit_fee_at_mark = (
        None if mark_vwap is None else exit_fee(mark_vwap, held_qty, fee_coefficient)
    )
    unrealized_pnl = None if mark_vwap is None else (mark_vwap - fill_px) * held_qty
    recoverable_value = (
        None
        if mark_vwap is None or exit_fee_at_mark is None
        else mark_vwap * held_qty - exit_fee_at_mark
    )

    return MonitorEvidence(
        ts_ns=ts_ns,
        instrument_id=instrument_id,
        station=station,
        climate_day=climate_day,
        leg=leg,
        cell_key=(station, season, hour_lst, width_code, m_code),
        p_hold_at_entry=p_hold_at_entry,
        p_hold_at_t=p_hold_t,
        fill_px=fill_px,
        held_qty=held_qty,
        mark_vwap=mark_vwap,
        mark_source=mark_source,
        spread=spread,
        depth_sufficient=depth_sufficient,
        staleness_ns=staleness_ns,
        book_staleness_ns=book_staleness_ns,
        running_max_lower=running_max_lower,
        running_max_upper=running_max_upper,
        rung_low=rung_low,
        rung_high=rung_high,
        exit_fee_at_mark=exit_fee_at_mark,
        unrealized_pnl=unrealized_pnl,
        recoverable_value=recoverable_value,
        hour_lst=hour_lst,
        entry_context=entry_context,
    )
