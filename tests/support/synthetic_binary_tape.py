"""A hand-built, obviously-synthetic market-data tape for ONE binary option.

WHY THIS EXISTS, AND WHY IT IS NOT REAL DATA
--------------------------------------------

The Breezy catalog currently holds **zero** venue market data -- counted on
2026-08-27: ``QuoteTick`` 0, ``TradeTick`` 0, ``OrderBookDepth10`` 0,
``InstrumentClose`` 0, ``BinaryOption`` 0. The backtest harness therefore
cannot be exercised against captured ticks, and a harness that has never run
is a harness whose settlement path has never been observed.

Everything in this module is fabricated, and is named so that it cannot be
mistaken for a capture: the module lives under ``tests/support/``, every
public name carries the word ``synthetic``, and :data:`SYNTHETIC_TAPE_MARKER`
is written into the tape object itself. **No number here is a venue
observation and none may ever be cited as one.**

THE ONE THING THAT IS NOT FABRICATED
------------------------------------

The **instrument** is parsed from a captured
``GET /v1/market/slug/{slug}`` payload via
:func:`breezy.adapters.polymarket_us.parsing.parse_binary_option` (no network
call: the corpus under ``docs/evidence/venue/polymarket_us/raw`` is read from
disk). That is deliberate and load-bearing:

``OrderMatchingEngine.process_order_book_depth`` raises ``RuntimeError`` when a
``BookOrder``'s price or size precision differs from the instrument's
(``backtest/engine.pyx:4444-4471``), and the captured universe carries **two**
size precisions -- 405 markets at ``size_precision=2, min_quantity=0.01`` and
324 at ``size_precision=0, min_quantity=1``. A venue-wide constant would build
a tape that works for one half of the universe and raises for the other. Every
``Price``/``Quantity`` below is therefore constructed from
``instrument.price_precision`` / ``instrument.size_precision``, never from a
literal precision, and :func:`synthetic_binary_tape` can be asked for either.

SHAPE OF THE TAPE
-----------------

``L2_MBP`` is the book type the backtest venue configuration specifies
(``docs/specs/BACKTEST_VENUE_CONFIG.md`` §3), and under it
``process_quote_tick`` does **not** mutate the book (``engine.pyx:4551`` gates
the mutation on ``L1_MBP``). Execution is therefore driven entirely by the
``OrderBookDepth10`` records; the ``QuoteTick`` records exist only so a
subscriber can prove the quote path is alive. Both are emitted, interleaved,
ascending in ``ts_init``, followed by exactly one ``InstrumentClose`` carrying
``InstrumentCloseType.CONTRACT_EXPIRED``.

``BinaryOption.instrument_class`` is ``BINARY_OPTION``, which is **absent**
from ``ENGINE_EXPIRING_INSTRUMENT_CLASSES`` (``model/instruments/base.pyx:67``
-- only ``FUTURE``, ``FUTURES_SPREAD``, ``OPTION``, ``OPTION_SPREAD``). So
``_instrument_has_expiration`` is False and the wall-clock branch of
``check_instrument_expiration`` can never fire: the ``InstrumentClose`` is the
**sole** trigger for settlement on these instruments. That makes the ordering
invariant in ``BACKTEST_VENUE_CONFIG.md`` §5 the only thing standing between a
correct run and a run whose position is closed before its data arrives.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from nautilus_trader.model.data import BookOrder, InstrumentClose, OrderBookDepth10, QuoteTick
from nautilus_trader.model.enums import InstrumentCloseType, OrderSide
from nautilus_trader.model.objects import Price, Quantity

from breezy.adapters.polymarket_us.parsing import parse_binary_option
from tests.unit.conftest import iter_captured_market_payloads

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nautilus_trader.core.data import Data
    from nautilus_trader.model.instruments import BinaryOption

__all__ = [
    "SYNTHETIC_ASK_LEVELS",
    "SYNTHETIC_BID_LEVELS",
    "SYNTHETIC_TAPE_MARKER",
    "SyntheticBinaryTape",
    "synthetic_binary_tape",
]

#: Stamped onto every tape so a downstream reader cannot mistake it for a
#: capture. Asserted by the tape's own tests.
SYNTHETIC_TAPE_MARKER: Final[str] = "SYNTHETIC-NOT-A-VENUE-CAPTURE"

#: Fabricated bid ladder, best first: ``(price, size)``. Three real levels,
#: padded to ten at construction time with precision-matched zero-size orders.
#: Nautilus' own null padding uses precision zero and cannot be serialized.
SYNTHETIC_BID_LEVELS: Final[tuple[tuple[str, int], ...]] = (
    ("0.40", 50),
    ("0.39", 40),
    ("0.38", 30),
)

#: Fabricated ask ladder, best first. The best level holds far more than the
#: probe's clip, so a MARKET BUY fills wholly at ``0.42`` and the expected
#: entry price is arithmetic rather than a walk down the ladder.
SYNTHETIC_ASK_LEVELS: Final[tuple[tuple[str, int], ...]] = (
    ("0.42", 50),
    ("0.43", 40),
    ("0.44", 30),
)

#: Nanoseconds between successive synthetic records.
_STEP_NS: Final[int] = 1_000_000_000

#: How far after the last market-data record the ``InstrumentClose`` sits.
_CLOSE_GAP_NS: Final[int] = 5 * _STEP_NS


@dataclass(frozen=True, kw_only=True, slots=True)
class SyntheticBinaryTape:
    """One instrument, its fabricated book updates, and its terminal close."""

    #: Always :data:`SYNTHETIC_TAPE_MARKER`.
    marker: str
    #: Parsed from a captured payload -- the only non-fabricated part.
    instrument: BinaryOption
    #: Depth and quote records, interleaved, ascending in ``ts_init``.
    market_data: tuple[Data, ...]
    #: The single ``CONTRACT_EXPIRED`` trigger. Its ``ts_init`` strictly
    #: exceeds every entry in :attr:`market_data`.
    instrument_close: InstrumentClose
    #: The value the venue configuration must carry in ``settlement_prices``.
    #: Exactly ``0.0`` or ``1.0`` -- see ``BACKTEST_VENUE_CONFIG.md`` §5.
    settlement_price: float
    #: Best ask on every depth update, i.e. the price a MARKET BUY pays.
    best_ask: Price
    #: A timestamp that sits AFTER the first depth update (so the book is
    #: populated) and before the close. Weather records are stamped here so a
    #: strategy reacting to weather submits into a live book.
    weather_ts_ns: int
    #: ``ts_init`` of the last entry in :attr:`market_data`.
    last_market_data_ts_ns: int

    def all_data(self) -> list[Data]:
        """Market data then the close, in the order ``add_data`` expects."""
        return [*self.market_data, self.instrument_close]


def _captured_instrument(*, size_precision: int, ts_init: int) -> BinaryOption:
    """The first captured market whose ``size_precision`` matches.

    Raises rather than falling back: a tape that silently used the other
    precision would still pass, and would stop testing what it names.
    """
    for payload in iter_captured_market_payloads():
        instrument = parse_binary_option(payload, ts_init=ts_init)
        if instrument.size_precision == size_precision:
            return instrument
    available = sorted(
        {
            parse_binary_option(payload, ts_init=ts_init).size_precision
            for payload in iter_captured_market_payloads()
        },
    )
    raise LookupError(
        f"no captured Polymarket.us market has size_precision={size_precision}; "
        f"the corpus under docs/evidence/venue/polymarket_us/raw carries only "
        f"{available}",
    )


def _book_side(
    levels: tuple[tuple[str, int], ...],
    side: OrderSide,
    instrument: BinaryOption,
) -> tuple[list[BookOrder], list[int]]:
    """Build one ladder at the INSTRUMENT's precisions, never at literals."""
    orders = [
        BookOrder(
            side,
            Price(float(price), instrument.price_precision),
            Quantity(size, instrument.size_precision),
            0,
        )
        for price, size in levels
    ]
    counts = [1] * len(orders)
    filler = BookOrder(
        side,
        Price(0, instrument.price_precision),
        Quantity(0, instrument.size_precision),
        0,
    )
    while len(orders) < 10:
        orders.append(filler)
        counts.append(0)
    return orders, counts


def synthetic_binary_tape(
    *,
    size_precision: int = 0,
    settlement_price: float = 1.0,
    depth_updates: int = 3,
) -> SyntheticBinaryTape:
    """Fabricate a runnable tape for one captured binary option.

    Parameters
    ----------
    size_precision : int, default 0
        Which half of the captured universe to draw the instrument from. Both
        values present in the corpus (0 and 2) are supported, and the ladder
        is rebuilt at that precision -- the point of the parameter.
    settlement_price : float, default 1.0
        What the contract settles at. Must be ``0.0`` or ``1.0`` for the
        harness to accept it; the parameter is deliberately NOT validated
        here, so a test can build an invalid tape and watch the harness raise.
    depth_updates : int, default 3
        How many identical depth snapshots to emit. Identical by design: with
        ``liquidity_consumption=True`` a re-sent snapshot restores the ladder,
        so the entry price is independent of when the order is submitted.

    Returns
    -------
    SyntheticBinaryTape

    """
    instrument = _captured_instrument(size_precision=size_precision, ts_init=0)
    # Anchored to the instrument's own activation so engine time sits inside
    # the market's life. Nothing about the anchor is a venue observation --
    # only its ORDERING relative to the close is load-bearing.
    base_ns = instrument.activation_ns + _STEP_NS

    top_bid, top_bid_size = SYNTHETIC_BID_LEVELS[0]
    top_ask, top_ask_size = SYNTHETIC_ASK_LEVELS[0]

    market_data: list[Data] = []
    for update in range(depth_updates):
        depth_ts = base_ns + (2 * update) * _STEP_NS
        bids, bid_counts = _book_side(SYNTHETIC_BID_LEVELS, OrderSide.BUY, instrument)
        asks, ask_counts = _book_side(SYNTHETIC_ASK_LEVELS, OrderSide.SELL, instrument)
        market_data.append(
            OrderBookDepth10(
                instrument_id=instrument.id,
                # Fresh `BookOrder` lists per record: `OrderBookDepth10`
                # EXTENDS the lists it is given with null padding
                # (`model/data.pyx:3499`), so a shared list would grow past
                # ten on the second record and raise.
                bids=bids,
                asks=asks,
                bid_counts=bid_counts,
                ask_counts=ask_counts,
                flags=0,
                sequence=update,
                ts_event=depth_ts,
                ts_init=depth_ts,
            ),
        )
        quote_ts = depth_ts + _STEP_NS
        market_data.append(
            QuoteTick(
                instrument.id,
                Price(float(top_bid), instrument.price_precision),
                Price(float(top_ask), instrument.price_precision),
                Quantity(top_bid_size, instrument.size_precision),
                Quantity(top_ask_size, instrument.size_precision),
                quote_ts,
                quote_ts,
            ),
        )

    last_ts = base_ns + (2 * depth_updates - 1) * _STEP_NS
    close_ts = last_ts + _CLOSE_GAP_NS
    instrument_close = InstrumentClose(
        instrument.id,
        # Recorded for audit only. `SimulatedExchange.process_instrument_close`
        # stores the object as a TRIGGER and never reads this field
        # (`engine.pyx:4832-4848`); the price comes from `settlement_prices`.
        Price(settlement_price, instrument.price_precision),
        InstrumentCloseType.CONTRACT_EXPIRED,
        close_ts,
        close_ts,
    )

    return SyntheticBinaryTape(
        marker=SYNTHETIC_TAPE_MARKER,
        instrument=instrument,
        market_data=tuple(market_data),
        instrument_close=instrument_close,
        settlement_price=settlement_price,
        best_ask=Price(float(top_ask), instrument.price_precision),
        weather_ts_ns=base_ns + _STEP_NS // 2,
        last_market_data_ts_ns=last_ts,
    )
