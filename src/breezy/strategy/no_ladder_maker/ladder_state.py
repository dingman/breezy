"""Per-station-day state of the live maker and the pure helpers the strategy shares.

No Nautilus order calls live here: the strategy owns every command. This module holds the
bookkeeping dataclasses, the Depth10 -> ``DepthFrame`` conversion (size-0 pad skipped), and the
marketability / truncation refusals the simulator applies before it admits a rest
(``maker_stage0_fill_pass._refusal``, minus the recorder-only stale-frame and gap tests).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Final, Protocol, SupportsFloat

from nautilus_trader.model.identifiers import ClientOrderId, InstrumentId

from breezy.strategy.no_ladder_maker.records import CENTS, DepthFrame, Level
from breezy.strategy.no_ladder_maker.selector import RungSelector, no_ask

__all__ = [
    "DEPTH10_LEVELS",
    "MARKETABLE",
    "TRUNCATED_FRAME",
    "Ladder",
    "Rest",
    "RestState",
    "Rung",
    "book_refusal",
    "frame_from_levels",
    "own_excluded",
]

DEPTH10_LEVELS: Final[int] = 10
MARKETABLE: Final[str] = "MARKETABLE"
TRUNCATED_FRAME: Final[str] = "TRUNCATED_FRAME"


class _Level(Protocol):
    @property
    def price(self) -> SupportsFloat: ...
    @property
    def size(self) -> SupportsFloat: ...


class RestState(Enum):
    """Lifecycle of one maker order (``SHADOW`` = a would-be order, never sent)."""

    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    CANCELING = "CANCELING"
    SHADOW = "SHADOW"


@dataclass(slots=True)
class Rest:
    rung_id: str
    bid_cents: int
    expire_ns: int
    state: RestState
    client_order_id: ClientOrderId | None = None
    #: CANCELING only: the instant after which the cancel is re-queried and re-issued (0 = now)
    cancel_deadline_ns: int = 0
    #: clock instant of the submit (0 = adopted, unknown). A frame stamped at or before it cannot
    #: contain this order, so SEL-1 must not subtract it from that frame.
    posted_ns: int = 0


@dataclass(frozen=True, slots=True)
class Rung:
    """One tradable rung: the YES instrument the book is read from, the NO leg we bid on."""

    rung_id: str  # str(yes instrument id): the key the selector and the sim use
    yes_id: InstrumentId
    no_id: InstrumentId
    lower_edge_f: float
    lower_f: int | None
    upper_f: int | None


@dataclass(slots=True)
class Ladder:
    """Everything the maker tracks for one (station, climate day)."""

    station: str
    day: dt.date
    hard_cancel_ns: int
    #: D-1 16:50Z: nothing is posted before the sim's window opens (plan r2 D4)
    window_open_ns: int = 0
    rungs: dict[str, Rung] = field(default_factory=dict)
    books: dict[str, DepthFrame] = field(default_factory=dict)
    rests: dict[str, Rest] = field(default_factory=dict)
    held: set[str] = field(default_factory=set)
    #: rung -> earliest ns a re-post may be attempted (after a denial / rejection)
    backoff_until_ns: dict[str, int] = field(default_factory=dict)
    #: rung -> (price, stored frame) of a rest the venue just cancelled/expired. That frame (taken
    #: before the cancel) still displays it, so SEL-1 excludes it only while that very frame object
    #: is the rung's stored book; the next frame replaces the object and ends the exclusion.
    departed: dict[str, tuple[int, DepthFrame]] = field(default_factory=dict)
    hard_cancelled: bool = False
    selector: RungSelector | None = None
    selector_stamp: object = None

    def cancelling(self) -> frozenset[str]:
        return frozenset(r for r, rest in self.rests.items() if rest.state is RestState.CANCELING)


def _cents(price: SupportsFloat) -> int:
    return round(float(price) * CENTS)


def frame_from_levels(
    rung_id: str, ts_ns: int, bids: Sequence[_Level], asks: Sequence[_Level]
) -> DepthFrame:
    """A ``DepthFrame`` from Depth10 sides; a size-0 level is the Arrow pad, never a quote."""

    def levels(side: Sequence[_Level]) -> tuple[Level, ...]:
        return tuple(
            (_cents(level.price), int(float(level.size))) for level in side if float(level.size) > 0
        )

    return DepthFrame(rung_id=rung_id, ts_ns=ts_ns, yes_bids=levels(bids), yes_asks=levels(asks))


def own_excluded(frame: DepthFrame, bid_cents: int, qty: int) -> DepthFrame:
    """``frame`` without our own resting BUY NO of ``qty`` at ``bid_cents`` (SEL-1).

    A NO buy is a SELL on the YES book, so our bid shows as YES-ask size at ``100 - bid_cents``.
    Only that size is subtracted, never below zero; a level that reaches 0 is dropped and every
    other level (and the bid side) is untouched. ``frame`` itself is returned when nothing at our
    level can be ours, so identity-keyed memos stay warm.
    """
    level = CENTS - bid_cents
    remaining = qty
    asks: list[Level] = []
    for price, size in frame.yes_asks:
        if price == level and remaining > 0:
            taken = min(size, remaining)
            remaining -= taken
            size -= taken
        if size > 0:
            asks.append((price, size))
    if remaining == qty:
        return frame
    return replace(frame, yes_asks=tuple(asks))


def book_refusal(
    frame: DepthFrame, bid_cents: int, *, ask_levels_displayed: int = DEPTH10_LEVELS
) -> str | None:
    """Why a rest at ``bid_cents`` may not be placed against ``frame`` (None = admissible).

    * ``MARKETABLE``: the bid reaches the NO ask (a resting order that would take);
    * ``TRUNCATED_FRAME``: all ten YES-ask levels are displayed and our NO level lies beyond the
      deepest one, so the queue ahead of us is unknown (the live twin of the recorder's
      ``asks_truncated`` flag).
    """
    ask = no_ask(frame)
    if ask is not None and bid_cents >= round(ask * CENTS):
        return MARKETABLE
    level = CENTS - bid_cents
    asks = frame.yes_asks
    if len(asks) >= ask_levels_displayed and level > max(price for price, _ in asks):
        return TRUNCATED_FRAME
    return None


#: A callable that tells the strategy whether entries are vetoed (None = clear).
VetoFn = Callable[[], str | None]
