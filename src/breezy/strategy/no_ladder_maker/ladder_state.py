"""Per-station-day state of the live maker and the pure helpers the strategy shares.

No Nautilus order calls live here: the strategy owns every command. This module holds the
bookkeeping dataclasses, the Depth10 -> ``DepthFrame`` conversion (size-0 pad skipped), and the
marketability / truncation refusals the simulator applies before it admits a rest
(``maker_stage0_fill_pass._refusal``, minus the recorder-only stale-frame and gap tests).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
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
