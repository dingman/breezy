"""A fabricated, multi-instrument market-data tape: one city, several strikes.

WHY THIS EXISTS
---------------

``tests/support/synthetic_binary_tape.py`` builds a tape for exactly ONE
instrument. A weather strategy that is worth anything holds positions across
several strikes on the same city (or several cities), so the harness has to be
exercised with more than one instrument in the same run -- different
settlement outcomes, different books, one ``InstrumentClose`` each.

This module is that fixture. It is a NEW file rather than an edit to
``synthetic_binary_tape``: that module's public shape
(``SyntheticBinaryTape.instrument``, ``.best_ask``, ``.settlement_price`` --
all scalars) is a single-instrument shape, and the contract test
``tests/contract/test_backtest_harness_stop_gate.py`` reads every one of those
attributes. Generalising it would have been an edit to a proved artifact for
the convenience of a new one.

EVERYTHING HERE IS FABRICATED except the instruments
----------------------------------------------------

The instruments are parsed from the captured
``GET /v1/market/slug/{slug}`` corpus under
``docs/evidence/venue/polymarket_us/raw`` via
:func:`breezy.adapters.polymarket_us.parsing.parse_binary_option`, exactly as
the single-instrument tape does, and for the same reason: ``BookOrder``
precisions must match the instrument's or
``OrderMatchingEngine.process_order_book_depth`` raises ``RuntimeError``
(``backtest/engine.pyx:4444-4471``). Every price and size below is a
fabrication and none may ever be cited as a venue observation.

TWO THINGS THIS TAPE DOES THAT THE SINGLE-INSTRUMENT ONE CANNOT
---------------------------------------------------------------

* **One time origin for all instruments.** The captured strikes on a single
  city/day do NOT share an ``activation_ns`` (observed: two distinct values
  one second apart across the six ``nychigh-2026-04-23`` strikes). Anchoring
  each instrument to its own activation would produce streams offset from one
  another for no modelled reason, so the tape anchors every instrument to
  ``max(activation_ns) + 1s`` and interleaves from there.
* **Per-instrument settlement.** ``settlement_prices`` is a mapping, and the
  point of this fixture is that some entries are ``1.0`` and some are ``0.0``
  in the SAME run.
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
    from collections.abc import Sequence

    from nautilus_trader.core.data import Data
    from nautilus_trader.model.identifiers import InstrumentId
    from nautilus_trader.model.instruments import BinaryOption

__all__ = [
    "SYNTHETIC_MULTI_TAPE_MARKER",
    "SyntheticStrikeLeg",
    "SyntheticStrikeTape",
    "synthetic_strike_tape",
]

#: Stamped onto the tape so no reader can mistake it for a capture.
SYNTHETIC_MULTI_TAPE_MARKER: Final[str] = "SYNTHETIC-NOT-A-VENUE-CAPTURE"

#: Nanoseconds between successive records on ONE instrument's stream.
_STEP_NS: Final[int] = 1_000_000_000

#: How far after an instrument's last market-data record its close sits.
_CLOSE_GAP_NS: Final[int] = 5 * _STEP_NS

#: Fabricated bid ladder shape, as (offset-from-best, size). Applied beneath
#: whatever best bid a leg is given.
_BID_SHAPE: Final[tuple[tuple[int, int], ...]] = ((0, 50), (1, 40), (2, 30))
_ASK_SHAPE: Final[tuple[tuple[int, int], ...]] = ((0, 50), (1, 40), (2, 30))


@dataclass(frozen=True, kw_only=True, slots=True)
class SyntheticStrikeLeg:
    """One instrument in the tape, with its book and its settlement."""

    instrument: BinaryOption
    #: Best ask on every depth update: what a MARKET BUY pays.
    best_ask: Price
    #: Best bid on every depth update. Used only to prove that a settled
    #: position did NOT close at the book.
    best_bid: Price
    #: Exactly 0.0 or 1.0 (``BACKTEST_VENUE_CONFIG.md`` §5).
    settlement_price: float
    #: The instrument's own terminal CONTRACT_EXPIRED trigger.
    instrument_close: InstrumentClose
    #: ``ts_init`` of this instrument's last non-close record.
    last_market_data_ts_ns: int

    @property
    def instrument_id(self) -> InstrumentId:
        return self.instrument.id


@dataclass(frozen=True, kw_only=True, slots=True)
class SyntheticStrikeTape:
    """Several strikes on one city, their books, and their closes."""

    marker: str
    legs: tuple[SyntheticStrikeLeg, ...]
    #: Depth and quote records for EVERY leg, interleaved, ascending ts_init.
    market_data: tuple[Data, ...]
    #: After the first depth update of every leg, before every close: a
    #: strategy reacting to weather here submits into a live book on all legs.
    weather_ts_ns: int

    def instruments(self) -> tuple[BinaryOption, ...]:
        return tuple(leg.instrument for leg in self.legs)

    def all_data(self) -> list[Data]:
        """Market data then every close, in the order ``add_data`` expects."""
        return [*self.market_data, *(leg.instrument_close for leg in self.legs)]

    def settlement_prices(self) -> dict[InstrumentId, float]:
        return {leg.instrument_id: leg.settlement_price for leg in self.legs}

    def leg(self, symbol_fragment: str) -> SyntheticStrikeLeg:
        """The one leg whose symbol contains ``symbol_fragment``, or raise."""
        matches = [leg for leg in self.legs if symbol_fragment in str(leg.instrument.symbol)]
        if len(matches) != 1:
            raise LookupError(
                f"{len(matches)} legs match {symbol_fragment!r}; "
                f"tape carries {[str(leg.instrument.symbol) for leg in self.legs]}",
            )
        return matches[0]


def captured_instruments(slugs: Sequence[str]) -> tuple[BinaryOption, ...]:
    """Parse exactly the captured markets named by ``slugs``, in that order.

    Raises rather than skipping a miss: a tape that quietly dropped a leg
    would still run, and would stop being a multi-instrument tape without
    saying so.
    """
    by_slug: dict[str, BinaryOption] = {}
    for payload in iter_captured_market_payloads():
        instrument = parse_binary_option(payload, ts_init=0)
        by_slug.setdefault(str(instrument.symbol), instrument)
    missing = [slug for slug in slugs if slug not in by_slug]
    if missing:
        raise LookupError(
            f"captured corpus has no market(s) {missing}; {len(by_slug)} slugs are available",
        )
    return tuple(by_slug[slug] for slug in slugs)


def _ladder(
    *,
    best: str,
    shape: tuple[tuple[int, int], ...],
    side: OrderSide,
    instrument: BinaryOption,
) -> list[BookOrder]:
    """A ladder at the INSTRUMENT's precisions, never at literal ones."""
    tick = float(instrument.price_increment)
    sign = -1 if side == OrderSide.BUY else 1
    return [
        BookOrder(
            side,
            Price(float(best) + sign * offset * tick, instrument.price_precision),
            Quantity(size, instrument.size_precision),
            0,
        )
        for offset, size in shape
    ]


def synthetic_strike_tape(
    *,
    slugs: Sequence[str],
    best_asks: Sequence[str],
    best_bids: Sequence[str],
    settlement_prices: Sequence[float],
    depth_updates: int = 3,
) -> SyntheticStrikeTape:
    """Fabricate a runnable multi-instrument tape.

    Parameters
    ----------
    slugs : Sequence[str]
        Captured market slugs, one per leg. Order is preserved.
    best_asks, best_bids : Sequence[str]
        Best price per leg, as decimal strings. Same length as ``slugs``.
    settlement_prices : Sequence[float]
        Per leg. Must be 0.0 or 1.0 for the harness to accept the run --
        deliberately NOT validated here, so a test can build an invalid tape
        and watch the harness raise.
    depth_updates : int, default 3
        Identical snapshots per leg. Identical by design: with
        ``liquidity_consumption=True`` a re-sent snapshot restores the ladder,
        so a leg's entry price does not depend on when its order arrives.

    """
    if not (len(slugs) == len(best_asks) == len(best_bids) == len(settlement_prices)):
        raise ValueError("slugs, best_asks, best_bids and settlement_prices must align")

    instruments = captured_instruments(slugs)
    # ONE origin for every leg. The captured strikes on a single city/day do
    # not share an activation instant, and a per-leg anchor would offset the
    # streams for no modelled reason.
    base_ns = max(i.activation_ns for i in instruments) + _STEP_NS

    market_data: list[Data] = []
    legs: list[SyntheticStrikeLeg] = []

    for index, instrument in enumerate(instruments):
        ask = best_asks[index]
        bid = best_bids[index]
        # Legs are staggered by one step so that no two records in the whole
        # tape share a ts_init -- the engine sorts on ts_init and a tie would
        # make the delivery order an implementation detail.
        leg_base = base_ns + index * _STEP_NS
        stride = len(instruments) * 2 * _STEP_NS
        last_ts = leg_base
        for update in range(depth_updates):
            depth_ts = leg_base + update * stride
            market_data.append(
                OrderBookDepth10(
                    instrument_id=instrument.id,
                    # Fresh lists per record: OrderBookDepth10 EXTENDS the
                    # lists it is given with null padding (model/data.pyx:3499).
                    bids=_ladder(
                        best=bid, shape=_BID_SHAPE, side=OrderSide.BUY, instrument=instrument
                    ),
                    asks=_ladder(
                        best=ask, shape=_ASK_SHAPE, side=OrderSide.SELL, instrument=instrument
                    ),
                    bid_counts=[1] * len(_BID_SHAPE),
                    ask_counts=[1] * len(_ASK_SHAPE),
                    flags=0,
                    sequence=update,
                    ts_event=depth_ts,
                    ts_init=depth_ts,
                ),
            )
            quote_ts = depth_ts + len(instruments) * _STEP_NS
            market_data.append(
                QuoteTick(
                    instrument.id,
                    Price(float(bid), instrument.price_precision),
                    Price(float(ask), instrument.price_precision),
                    Quantity(50, instrument.size_precision),
                    Quantity(50, instrument.size_precision),
                    quote_ts,
                    quote_ts,
                ),
            )
            last_ts = quote_ts

        close_ts = last_ts + _CLOSE_GAP_NS + index
        legs.append(
            SyntheticStrikeLeg(
                instrument=instrument,
                best_ask=Price(float(ask), instrument.price_precision),
                best_bid=Price(float(bid), instrument.price_precision),
                settlement_price=settlement_prices[index],
                instrument_close=InstrumentClose(
                    instrument.id,
                    # Recorded for audit only; the engine never reads it.
                    Price(settlement_prices[index], instrument.price_precision),
                    InstrumentCloseType.CONTRACT_EXPIRED,
                    close_ts,
                    close_ts,
                ),
                last_market_data_ts_ns=last_ts,
            ),
        )

    market_data.sort(key=lambda record: record.ts_init)
    # Half a step after the LAST leg's first depth update, so every book in
    # the run is populated when a weather-driven order is submitted.
    first_depth_of_last_leg = base_ns + (len(instruments) - 1) * _STEP_NS
    weather_ts_ns = first_depth_of_last_leg + _STEP_NS // 2

    return SyntheticStrikeTape(
        marker=SYNTHETIC_MULTI_TAPE_MARKER,
        legs=tuple(legs),
        market_data=tuple(market_data),
        weather_ts_ns=weather_ts_ns,
    )
