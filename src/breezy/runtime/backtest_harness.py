"""The Breezy backtest harness: one `BacktestEngine`, configured to the spec.

Authority: ``docs/specs/BACKTEST_VENUE_CONFIG.md``. Every ``add_venue``
argument below is fixed by that document, argument by argument, and is pinned
against it from SOURCE by ``tests/unit/test_runtime_backtest_harness.py`` --
because most of the choices are indistinguishable at runtime from the defaults
they replace.

Null hypothesis, checked against the installed ``nautilus-trader==1.231.0``
before this module was written
-----------------------------------------------------------------------------

**Native, and therefore used rather than rebuilt.** All of it:
``BacktestEngine``/``BacktestEngineConfig``, ``add_venue``,
``add_instrument``, ``add_data``, ``add_strategy``, ``run``. There is no
Breezy engine, no Breezy exchange, no Breezy execution model, and no wrapper
class around any of them -- this module is a **composition root**, and the
object it returns is the framework's own ``BacktestEngine``, handed back
unwrapped so a caller reaches the native ``cache``/``portfolio``/``trader``
surfaces directly.

**Genuinely absent, and therefore authored here.** The settlement invariants of
spec §5, the submit-time order screen in
``breezy.runtime.backtest_order_guard``, and the post-run refusals below.
Nautilus enforces none of them, and every failure they cover is silent:

* *Settlement.* ``check_instrument_expiration`` (``backtest/engine.pyx:5934``)
  applies ``settlement_prices[instrument_id]`` when present and otherwise
  falls through to ``fill_market_order`` -- closing the position at the
  **prevailing book**. ``settlement_prices`` defaults to ``None``, so this is
  what doing nothing gives you. For a weather binary, settlement IS the PnL,
  and the substituted error is *mean-reverting*: winners close near 0.97
  rather than 1.00 and losers near 0.03 rather than 0.00, which compresses the
  PnL distribution symmetrically and **improves Sharpe**. Nothing logs.
* *Endpoints.* A price strictly inside ``(0, 1)`` also fabricates a settlement
  fee the venue never charges: ``PolymarketUSFeeModel`` computes
  ``theta * C * p * (1 - p)``, which is zero **only** at 0 and 1.
* *Ordering.* ``_expiration_processed`` is a one-shot latch that also cancels
  every open order (``engine.pyx:5936-5947``). An ``InstrumentClose`` stamped
  before the instrument's last market-data record kills that instrument for
  the remainder of the run and produces a shorter, calmer, entirely plausible
  equity curve.

A fourth fact makes the third one sharper, and is worth stating because it is
easy to assume the opposite: ``BinaryOption.instrument_class`` is
``BINARY_OPTION``, which is **not** in ``ENGINE_EXPIRING_INSTRUMENT_CLASSES``
(``model/instruments/base.pyx:67`` -- only the futures and option classes).
``_instrument_has_expiration`` is therefore ``False`` for every Breezy
instrument, and the time-based expiration branch can never fire. The
``InstrumentClose`` is the **sole** settlement trigger.

Every guard here is stated in the direction that fails when nothing is
configured
-----------------------------------------------------------------------------

The first version of the settlement invariants was derived FROM
``market_data``: *every instrument that receives a ``CONTRACT_EXPIRED`` close
must carry an endpoint price stamped after its last record*. All three rules
are true, and all three are **vacuous on the empty set** -- a run with no close
at all satisfied every one of them, left its position open, reported
commission-only PnL, and raised nothing. The rules are now derived from
``instruments``: everything that could trade must RECEIVE exactly one close.
Read :func:`assert_settlement_invariants` and :func:`run_backtest` with that
direction in mind; each waiver is per-instrument or per-condition, never a
single ``strict=False``, because one flag is how a guard becomes a decoration.

Three things a strategy author will otherwise learn the expensive way
---------------------------------------------------------------------

**Weather is delivered to EVERY strategy in the run, from EVERY city.** The
weather stream is scoped by ``client_id`` and not by ``instrument_id``, which
is both necessary (``Actor.subscribe_data(instrument_id=...)`` builds a topic
``DataType(NwsClimateDay).topic`` never matches, so an instrument-scoped
subscription receives ZERO records with no error) and semantically right (one
climate day settles many markets). The cost is that a strategy trading New York
is handed Chicago's ``NwsClimateDay`` with nothing marking it foreign. **A
strategy MUST filter on ``record.station`` itself.** Nothing in the platform
does it, nothing correlates a station with an instrument's city, and a ladder
that acts on the first record it sees will size a New York position off
Chicago's temperature and log nothing.
``breezy.strategy.harness_probe.BreezyHarnessProbe`` demonstrates the filter.

**``ClientOrderId`` is NOT deterministic across runs, even though everything
else is.** The engine's own settlement leg is stamped
``ClientOrderId(f"EXPIRATION-LEG-{uuid.uuid4()}")`` (``engine.pyx:5956``),
freshly per run, and ``use_random_ids=False`` does not reach it. It is the
natural field to put in a decision log, and doing so makes a first determinism
test fail intermittently for a reason that has nothing to do with the strategy.
Log ``venue_order_id`` instead, which the harness's fixed ``TraderId`` and
``instance_id`` do make reproducible.

**``Cache.orders_open()`` guarantees no ordering** (``cache.pyx:4719``). A
sweep that iterates it and cancels is non-deterministic *by construction*, and
so is any decision log written from that loop. Sort by ``client_order_id``
first, or aggregate into something order-independent.

Why this module lives in ``breezy.runtime``
-------------------------------------------

``runtime`` is the top layer of the import-linter contract, and is the only
layer that may reach both the venue adapter (``PolymarketUSFeeModel``,
``POLYMARKET_US_VENUE``) and the weather feed seam
(``breezy.runtime.backtest_feed``). It is also where every other composition
root already lives -- ``node_config`` builds the ``TradingNodeConfig`` for each
live process, ``composition`` builds the ingest node -- and a
``BacktestEngine`` assembly is the same kind of object: configuration mapped
onto native constructors, no domain logic.

It is deliberately NOT in ``breezy.adapters.polymarket_us``: an adapter that
imported ``breezy.runtime.backtest_feed`` would invert the layer direction. It
is deliberately NOT in ``breezy.strategy``: that package holds trading logic
and sits ABOVE runtime, and a harness importable only from there could not be
reached by the runtime tooling that will eventually drive parameter sweeps.

Like ``backtest_feed``, this module is **not** re-exported from
``breezy.runtime``'s facade: that package is imported eagerly by the ingest
process, and re-exporting here would drag the venue adapter into every one of
those imports. Import it directly.
"""

from __future__ import annotations

import contextlib
import enum
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.backtest.models import FillModel
from nautilus_trader.config import LoggingConfig
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import (
    CustomData,
    InstrumentClose,
    InstrumentStatus,
    OrderBookDelta,
    OrderBookDeltas,
    OrderBookDepth10,
    QuoteTick,
    TradeTick,
)
from nautilus_trader.model.enums import (
    AccountType,
    BookType,
    InstrumentCloseType,
    OmsType,
    OrderStatus,
)
from nautilus_trader.model.identifiers import TraderId

from breezy.adapters.polymarket_us.fees import PolymarketUSFeeModel
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE
from breezy.runtime.backtest_feed import NWS_BACKTEST_CLIENT_ID
from breezy.runtime.backtest_order_guard import install_order_guard

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence

    from nautilus_trader.core.data import Data
    from nautilus_trader.model.identifiers import InstrumentId
    from nautilus_trader.model.instruments import Instrument
    from nautilus_trader.model.objects import Money
    from nautilus_trader.trading.strategy import Strategy

__all__ = [
    "DEFAULT_BACKTEST_INSTANCE_ID",
    "DEFAULT_BACKTEST_TRADER_ID",
    "HARNESS_SOURCE_PATH",
    "VENUE_MARKET_DATA_TYPES",
    "BreezyBacktestConfig",
    "NotVenueMarketDataError",
    "SettlementInvariant",
    "SettlementInvariantError",
    "SilentRunCondition",
    "SilentRunError",
    "UnwrappedWeatherRecordError",
    "assert_market_data_is_venue_data",
    "assert_settlement_invariants",
    "assert_weather_is_wrapped",
    "backtest",
    "build_backtest_engine",
    "run_backtest",
]

#: This module's own file, so a source-level test can read the `add_venue`
#: call without re-deriving the path and silently scanning nothing.
HARNESS_SOURCE_PATH: Final[str] = __file__

#: Fixed rather than generated. `TraderId` is stamped into every
#: `ClientOrderId`, so a per-run value would make two identical runs produce
#: different order ids -- determinism is a property of the whole harness, not
#: only of `use_random_ids=False`. It does NOT reach the engine's own
#: settlement leg; see the module docstring.
DEFAULT_BACKTEST_TRADER_ID: Final[TraderId] = TraderId("BREEZY-BACKTEST-001")

#: `BacktestEngineConfig.instance_id` defaults to a fresh `UUID4`. Pinned for
#: the same reason. `NautilusKernel.__init__` passes it straight to
#: `register_component_clock`, which type-checks it as a real `UUID4` -- a
#: string here raises at engine construction.
DEFAULT_BACKTEST_INSTANCE_ID: Final[UUID4] = UUID4.from_str(
    "00000000-0000-4000-8000-000000000001",
)

#: The only two settlement prices a weather binary may carry. Anything else is
#: a void or ambiguous resolution (spec §5 step 3).
_SETTLEMENT_ENDPOINTS: Final[frozenset[float]] = frozenset({0.0, 1.0})

#: What `BreezyBacktestConfig.market_data` may contain. An ALLOWLIST, because
#: the failure it guards is "something unforeseen was silently dropped" and a
#: blocklist cannot catch the unforeseen.
#:
#: `Bar` is deliberately absent even though `add_data` accepts it: the venue
#: publishes no bars, the spec sets `bar_execution=False`, and `Bar` is the one
#: market-data type that carries its instrument under `bar_type.instrument_id`
#: rather than `instrument_id` -- so admitting it would put a special case into
#: the grouping below for a record type this venue never produces.
VENUE_MARKET_DATA_TYPES: Final[frozenset[type]] = frozenset(
    {
        OrderBookDelta,
        OrderBookDeltas,
        OrderBookDepth10,
        QuoteTick,
        TradeTick,
        InstrumentClose,
        InstrumentStatus,
    },
)


@enum.unique
class SettlementInvariant(enum.Enum):
    """Which settlement rule a :class:`SettlementInvariantError` names."""

    #: Every instrument that could trade RECEIVES a ``CONTRACT_EXPIRED`` close.
    CLOSE = "close"
    #: No instrument receives more than one ``CONTRACT_EXPIRED`` close.
    DUPLICATE_CLOSE = "duplicate_close"
    #: Every instrument receiving a ``CONTRACT_EXPIRED`` close has a price.
    COVERAGE = "coverage"
    #: Every settlement price is exactly ``0.0`` or ``1.0``.
    ENDPOINT = "endpoint"
    #: Every close's ``ts_init`` strictly exceeds its instrument's last
    #: market-data ``ts_init``.
    ORDERING = "ordering"


@enum.unique
class SilentRunCondition(enum.Enum):
    """Which post-run refusal a :class:`SilentRunError` names."""

    #: At least one order ended ``DENIED`` or ``REJECTED``.
    REJECTED_ORDERS = "rejected_orders"
    #: At least one position was still open when the run ended.
    OPEN_POSITIONS = "open_positions"
    #: At least one strategy submitted no orders at all.
    IDLE_STRATEGY = "idle_strategy"


class UnwrappedWeatherRecordError(TypeError):
    """A weather record reached the harness without its `CustomData` envelope.

    ``DataEngine._handle_data`` dispatches on ``isinstance`` and its terminal
    ``else`` LOGS AND DROPS -- it does not raise. A bare ``NwsClimateDay``
    therefore vanishes, and
    :func:`breezy.persistence.catalog.read_climate_days` returns exactly that
    shape by design, so ``add_data(read_climate_days(catalog))`` is the obvious
    call and is silently empty. This is the last boundary that can make the
    drop loud.
    """


class NotVenueMarketDataError(TypeError):
    """Something that is not venue market data was passed as ``market_data``.

    ``market_data`` is the field every other record already lives in, so it is
    where a weather record naturally gets put. ``add_data`` validates only
    ``data[0]``, so a weather record sitting anywhere else in the list sails
    through, is sorted into the stream, and is then logged and dropped by
    ``DataEngine._handle_data``. The run completes, ``on_data`` is never
    called, and the bot has never seen weather.
    """


class SettlementInvariantError(ValueError):
    """A backtest was configured in a way whose error would not be visible.

    Carries :attr:`invariant` so a caller (and a test) can distinguish the
    rules without matching on message text.
    """

    def __init__(self, invariant: SettlementInvariant, message: str) -> None:
        super().__init__(message)
        self.invariant = invariant


class SilentRunError(RuntimeError):
    """A completed run whose result would describe nothing, returned as a result.

    Carries :attr:`condition` so a caller (and a test) can distinguish the
    three shapes without matching on message text.
    """

    def __init__(self, condition: SilentRunCondition, message: str) -> None:
        super().__init__(message)
        self.condition = condition


@dataclass(frozen=True, kw_only=True, slots=True)
class BreezyBacktestConfig:
    """Everything the harness needs that is not fixed by the venue spec.

    Parameters
    ----------
    instruments : Sequence[Instrument]
        Every instrument the run touches. Each is added before any data, as
        ``BacktestEngine.add_data`` requires a matching instrument in the
        cache. This is also the set the settlement rules are derived FROM:
        everything listed here must receive a ``CONTRACT_EXPIRED`` close.
    market_data : Sequence[Data]
        Venue market data only -- ``OrderBookDepth10``, ``QuoteTick``, and the
        terminal ``InstrumentClose`` records; see
        :data:`VENUE_MARKET_DATA_TYPES` for the full allowlist. Weather does
        NOT go here (see ``weather_data``).

        Order does not matter, and the reason is worth stating precisely
        because the obvious reason is wrong. ``add_data`` does not merely sort:
        it reads ``data[0]`` and registers **that one** instrument into
        ``_has_data``/``_has_book_data`` (``engine.pyx:863-897``), which is
        what arms the ``InvalidConfiguration: No order book data found ...``
        guard. Handed one flat heterogeneous list, that guard would cover the
        first instrument only. :func:`build_backtest_engine` therefore groups
        this sequence by ``(instrument_id, type)`` and calls ``add_data`` once
        per group -- one call per instrument per record type, which is exactly
        the shape ``add_data`` documents itself as assuming -- and the engine
        sorts the combined stream by ``ts_init``. THAT is why order does not
        matter here.
    weather_data : Sequence[Data]
        Weather records **already wrapped** by
        :func:`breezy.runtime.backtest_feed.as_backtest_data`. Passing bare
        ``NwsClimateDay`` objects here would see them logged and dropped by
        ``DataEngine._handle_data``; wrapping is the caller's step because the
        catalog readers deliberately return the unwrapped shape. Delivered to
        every strategy in the run regardless of city -- see the module
        docstring; a strategy must filter on ``station`` itself.
    settlement_prices : Mapping[InstrumentId, float]
        Spec §0. The ONLY source of the settlement price -- an instrument
        absent from this mapping closes at the prevailing book.
    starting_balances : Sequence[Money]
        An operator budget decision, not a venue fact (spec §1).
    instruments_without_close : frozenset[InstrumentId]
        Instruments deliberately left unsettled, NAMED one by one. The waiver
        for the ``CLOSE`` rule. Per-instrument rather than a boolean so that
        studying one unsettled leg cannot silently waive the others -- which
        is precisely how the market-data-derived version behaved.
    trader_id, instance_id : optional
        Pinned by default for determinism; overridable so two runs can be told
        apart when that is what the caller wants.
    bypass_logging : bool
        Default ``False``. ``True`` was the original default and it deletes
        every diagnostic this module exists to surface: ``OrderRejected``'s
        reason, ``OrderDenied``, and the RiskEngine's own "no prices for ..."
        warning are reported by the engine's logger and by nothing else. The
        post-run refusals in :func:`run_backtest` raise on those conditions,
        but the log is what EXPLAINS them.
    log_level : str
        Default ``"WARNING"``, and that is what makes ``bypass_logging=False``
        affordable. The engine's ``INFO`` stream is per-component lifecycle
        chatter -- roughly a hundred lines per run, written by the Rust logger
        straight to stdout where pytest's capture does not reach it. Suppressing
        the whole log to be rid of it is exactly the trade that hid the
        diagnostics; suppressing only ``INFO`` keeps every rejection, denial and
        risk warning and drops the noise. Raise it to ``"INFO"``/``"DEBUG"`` when
        a run needs the full transcript.

    """

    instruments: Sequence[Instrument]
    market_data: Sequence[Data]
    settlement_prices: Mapping[InstrumentId, float]
    starting_balances: Sequence[Money]
    weather_data: Sequence[Data] = field(default_factory=tuple)
    instruments_without_close: frozenset[InstrumentId] = frozenset()
    trader_id: TraderId = DEFAULT_BACKTEST_TRADER_ID
    instance_id: UUID4 = DEFAULT_BACKTEST_INSTANCE_ID
    bypass_logging: bool = False
    log_level: str = "WARNING"


def _expired_closes(market_data: Iterable[Data]) -> list[InstrumentClose]:
    """Every ``CONTRACT_EXPIRED`` close in ``market_data``, in arrival order.

    Type-EXACT on ``InstrumentClose`` and identity-exact on the close type: a
    ``END_OF_SESSION`` close is discarded by
    ``SimulatedExchange.process_instrument_close`` (``engine.pyx:4844``) and so
    never reaches the settlement branch. Counting it as a settlement would move
    the vacuity one level down.
    """
    return [
        record
        for record in market_data
        if type(record) is InstrumentClose
        and record.close_type == InstrumentCloseType.CONTRACT_EXPIRED
    ]


def _expired_instrument_ids(market_data: Iterable[Data]) -> set[InstrumentId]:
    """Instruments that receive a ``CONTRACT_EXPIRED`` close."""
    return {close.instrument_id for close in _expired_closes(market_data)}


def _last_market_data_ts(market_data: Iterable[Data]) -> dict[InstrumentId, int]:
    """Per instrument, the greatest non-close ``ts_init`` in ``market_data``.

    Per instrument, never global: instrument A's close may legitimately
    precede instrument B's data in a multi-market run, and a global maximum
    would reject that.
    """
    latest: dict[InstrumentId, int] = {}
    for record in market_data:
        if type(record) is InstrumentClose:
            continue
        instrument_id = getattr(record, "instrument_id", None)
        if instrument_id is None:
            continue
        previous = latest.get(instrument_id)
        if previous is None or record.ts_init > previous:
            latest[instrument_id] = record.ts_init
    return latest


def _assert_every_instrument_is_closed(
    *,
    instruments: Sequence[Instrument],
    closes: Sequence[InstrumentClose],
    instruments_without_close: Collection[InstrumentId],
) -> None:
    """The INVERTED rule: derived from ``instruments``, not from ``market_data``.

    Stated this way round because the other way round is vacuous on the empty
    set: a run with no closes at all satisfied coverage, endpoint AND ordering
    simultaneously, and the only symptom was a position that never closed.
    """
    waived = set(instruments_without_close)
    received = [close.instrument_id for close in closes]

    missing = sorted(
        str(instrument.id)
        for instrument in instruments
        if instrument.id not in waived and instrument.id not in set(received)
    )
    if missing:
        raise SettlementInvariantError(
            SettlementInvariant.CLOSE,
            f"{len(missing)} instrument(s) can trade in this run but receive no "
            f"CONTRACT_EXPIRED close: {', '.join(missing)}. `BinaryOption` is not in "
            f"`ENGINE_EXPIRING_INSTRUMENT_CLASSES`, so an `InstrumentClose` is the SOLE "
            f"settlement trigger -- without one the position simply never closes, and "
            f"the run still finishes green with commission-only PnL. You cannot detect "
            f"this from the obvious field: `avg_px_close` reads 0.0 on an unsettled "
            f"position, which is the SAME value a genuine settle-at-zero produces, and "
            f"on a weather ladder most legs DO settle at zero. Add one "
            f"CONTRACT_EXPIRED `InstrumentClose` per instrument, stamped after that "
            f"instrument's last market-data record -- or name the instrument in "
            f"`instruments_without_close` if it is deliberately left unsettled.",
        )

    duplicated = sorted({str(i) for i in received if received.count(i) > 1})
    if duplicated:
        raise SettlementInvariantError(
            SettlementInvariant.DUPLICATE_CLOSE,
            f"{len(duplicated)} instrument(s) receive more than one CONTRACT_EXPIRED "
            f"close: {', '.join(duplicated)}. `_expiration_processed` is a one-shot "
            f"latch (`engine.pyx:5936`), so every close after the first is a silent "
            f"no-op -- a tape carrying two of them describes a settlement sequence "
            f"that does not happen.",
        )


def assert_settlement_invariants(
    *,
    instruments: Sequence[Instrument],
    market_data: Sequence[Data],
    settlement_prices: Mapping[InstrumentId, float],
    instruments_without_close: Collection[InstrumentId] = (),
) -> None:
    """Enforce the settlement rules of spec §5, or raise.

    Parameters
    ----------
    instruments : Sequence[Instrument]
        Everything that could trade. The ``CLOSE`` rule is derived from this.
    market_data : Sequence[Data]
        The venue tape, including its ``InstrumentClose`` records.
    settlement_prices : Mapping[InstrumentId, float]
        The mapping handed to ``add_venue``.
    instruments_without_close : Collection[InstrumentId], optional
        Instruments deliberately left unsettled, named one by one.

    Raises
    ------
    SettlementInvariantError
        Carrying the :class:`SettlementInvariant` that failed.

    """
    closes = _expired_closes(market_data)
    _assert_every_instrument_is_closed(
        instruments=instruments,
        closes=closes,
        instruments_without_close=instruments_without_close,
    )

    expired = _expired_instrument_ids(market_data)

    missing = sorted(str(i) for i in expired - set(settlement_prices))
    if missing:
        raise SettlementInvariantError(
            SettlementInvariant.COVERAGE,
            f"{len(missing)} instrument(s) receive a CONTRACT_EXPIRED close but carry no "
            f"settlement price: {', '.join(missing)}. `SimulatedExchange` would close each "
            f"position at the PREVAILING BOOK instead (backtest/engine.pyx:5965-5978); the "
            f"resulting error is mean-reverting and improves Sharpe, and nothing logs it.",
        )

    off_endpoint = sorted(
        f"{instrument_id}={price!r}"
        for instrument_id, price in settlement_prices.items()
        if float(price) not in _SETTLEMENT_ENDPOINTS
    )
    if off_endpoint:
        raise SettlementInvariantError(
            SettlementInvariant.ENDPOINT,
            f"settlement prices must be exactly 0.0 or 1.0; got {', '.join(off_endpoint)}. A "
            f"weather binary resolving anywhere else is a void or ambiguous resolution, and any "
            f"interior price fabricates a settlement fee (theta*C*p*(1-p) is zero only at the "
            f"endpoints).",
        )

    latest = _last_market_data_ts(market_data)
    out_of_order = sorted(
        f"{close.instrument_id} close ts_init={close.ts_init} <= "
        f"last market data ts_init={latest[close.instrument_id]}"
        for close in closes
        if close.instrument_id in latest and close.ts_init <= latest[close.instrument_id]
    )
    if out_of_order:
        raise SettlementInvariantError(
            SettlementInvariant.ORDERING,
            f"every CONTRACT_EXPIRED close must strictly FOLLOW its instrument's last "
            f"market-data record: {'; '.join(out_of_order)}. `_expiration_processed` is a "
            f"one-shot latch that also cancels all open orders, so an early close kills the "
            f"instrument for the rest of the run.",
        )


def assert_weather_is_wrapped(weather_data: Sequence[Data]) -> None:
    """Refuse a weather record that would be logged and dropped.

    Type-EXACT on ``CustomData``: ``DataEngine._handle_data`` dispatches on the
    exact envelope, so a subclass is not what it recognises either.

    Raises
    ------
    UnwrappedWeatherRecordError

    """
    unwrapped = [
        type(record).__name__ for record in weather_data if type(record) is not CustomData
    ]
    if unwrapped:
        raise UnwrappedWeatherRecordError(
            f"{len(unwrapped)} weather record(s) reached the harness unwrapped "
            f"({', '.join(sorted(set(unwrapped)))}); `DataEngine._handle_data` logs and "
            f"DROPS them. Wrap with `breezy.runtime.backtest_feed.as_backtest_data` first.",
        )


def assert_market_data_is_venue_data(market_data: Sequence[Data]) -> None:
    """Refuse anything in ``market_data`` that is not venue market data.

    Type-EXACT against :data:`VENUE_MARKET_DATA_TYPES`, for the same reason
    :func:`assert_weather_is_wrapped` is type-exact: ``DataEngine._handle_data``
    dispatches on the exact type, so a subclass of a market-data record is not
    what it recognises either.

    Raises
    ------
    NotVenueMarketDataError

    """
    foreign = sorted(
        {
            type(record).__name__
            for record in market_data
            if type(record) not in VENUE_MARKET_DATA_TYPES
        },
    )
    if foreign:
        raise NotVenueMarketDataError(
            f"{', '.join(foreign)} is not venue market data, and `market_data` accepts only "
            f"{', '.join(sorted(t.__name__ for t in VENUE_MARKET_DATA_TYPES))}. If this is "
            f"weather, it belongs in `weather_data`, wrapped by "
            f"`breezy.runtime.backtest_feed.as_backtest_data` -- that field is added with "
            f"`client_id=NWS_BACKTEST_CLIENT_ID`, which is the routing a strategy's "
            f"`subscribe_data` call is waiting on. In `market_data` it would be sorted into "
            f"the venue stream and then logged and DROPPED by `DataEngine._handle_data`: the "
            f"run completes, `on_data` is never called, and the bot has never seen weather.",
        )


def _group_market_data(market_data: Sequence[Data]) -> list[list[Data]]:
    """Group by ``(instrument_id, type)``, preserving first-appearance order.

    One ``add_data`` call per group, because ``add_data`` inspects ``data[0]``
    only -- see ``BreezyBacktestConfig.market_data``. Grouping by type as well
    as by instrument is what makes the ``_has_book_data`` registration correct:
    a group whose first record is a ``QuoteTick`` registers ``_has_data`` but
    not ``_has_book_data``, which is exactly the state that must trip
    ``InvalidConfiguration`` when an instrument has quotes and no book.

    Deterministic: dict insertion order, not set iteration.
    """
    groups: dict[tuple[InstrumentId, type], list[Data]] = {}
    for record in market_data:
        groups.setdefault((record.instrument_id, type(record)), []).append(record)
    return list(groups.values())


def build_backtest_engine(config: BreezyBacktestConfig) -> BacktestEngine:
    """Assemble a `BacktestEngine` with the POLYMARKET_US venue, per the spec.

    Every guard runs FIRST, before any engine exists: a ``BacktestEngine``
    that is constructed and then abandoned leaves its trader registered for the
    lifetime of the process, so raising after construction would leak.

    Returns
    -------
    BacktestEngine
        The native engine, unwrapped. The caller owns it, and must call
        ``dispose()`` -- or use :func:`backtest`, which does it for you.

    Raises
    ------
    SettlementInvariantError
        If any §5 invariant fails.
    NotVenueMarketDataError
        If ``market_data`` carries anything that is not venue market data.
    UnwrappedWeatherRecordError
        If any weather record is missing its ``CustomData`` envelope.

    """
    assert_market_data_is_venue_data(config.market_data)
    assert_settlement_invariants(
        instruments=config.instruments,
        market_data=config.market_data,
        settlement_prices=config.settlement_prices,
        instruments_without_close=config.instruments_without_close,
    )
    assert_weather_is_wrapped(config.weather_data)

    # `msgspec.Struct` config classes are untyped to mypy (compiled Nautilus
    # surface), so the constructor call is typed as Any at this one boundary.
    engine_config: Any = BacktestEngineConfig(
        trader_id=config.trader_id,
        instance_id=config.instance_id,
        logging=LoggingConfig(
            bypass_logging=config.bypass_logging,
            log_level=config.log_level,
        ),
        # Both halves of the execution cage that DO apply here are stated
        # rather than defaulted, exactly as `runtime.node_config` states them:
        # strategies arrive through `add_strategy` (a live object), and no
        # execution algorithm is registered at all.
        strategies=[],
        exec_algorithms=[],
    )
    engine = BacktestEngine(engine_config)

    engine.add_venue(
        venue=POLYMARKET_US_VENUE,
        # Token-balance CLOB: you hold N YES tokens, not lots. HEDGING would
        # permit simultaneous long and short in one InstrumentId.
        oms_type=OmsType.NETTING,
        # NOT `BETTING`: `BettingAccount.balance_impact` assumes decimal odds
        # >= 1.01, so for p in [0,1] a BUY would appear to ADD cash. NOT
        # `MARGIN`: margin_init = margin_maint = 0 on a BinaryOption.
        account_type=AccountType.CASH,
        # NOT `None`. `BinaryOption.get_base_currency()` returns None, so a
        # multi-currency account makes BOTH sell checks evaluate False and
        # every sell check disappears (risk/engine.pyx:996,1007).
        base_currency=USD,
        starting_balances=list(config.starting_balances),
        # The `L1_MBP` default discards levels 2-10 and fills any residual
        # quantity at one price_increment through top-of-book -- $0.01 on a
        # $1.00 payout. Under L2, `process_quote_tick` does NOT mutate the book
        # (engine.pyx:4551): depth coverage is the binding constraint.
        book_type=BookType.L2_MBP,
        # `prob_slippage` is inert under L2 and `prob_fill_on_limit=1.0` is
        # moot for a taker-only bot. `BestPriceFillModel` must never be used:
        # it returns 1_000_000 units at best bid/ask.
        fill_model=FillModel(),
        # Mandatory; barrier F2 fails the build otherwise. `add_venue` would
        # otherwise install `MakerTakerFeeModel`, which reads `taker_fee` as a
        # flat notional rate and charges a fee at settlement.
        fee_model=PolymarketUSFeeModel(),
        # A KNOWN OVERSTATEMENT of reaction speed. Uncalibratable without live
        # round-trip observation (spec §6); must be labelled in any result.
        latency_model=None,
        # The `False` default lets each iteration fill against the full book
        # independently -- one stale Depth10 snapshot refills infinitely.
        liquidity_consumption=True,
        # The adapter publishes no TradeTick. `True` arms the bid/ask override
        # path if one ever leaks in.
        trade_execution=False,
        bar_execution=False,
        bar_adaptive_high_low_ordering=False,
        # Requires `trade_execution=True`, which requires a trade tape Breezy
        # does not have.
        queue_position=False,
        reject_stop_orders=True,
        # UNVERIFIED venue fact (spec §6): whether the CLOB honours GTD.
        support_gtd_orders=True,
        # The `True` default would grant OCO/OTO semantics never observed on
        # this venue.
        support_contingent_orders=False,
        # The engine's own settlement close order is reduce_only (engine.pyx:5957).
        use_reduce_only=True,
        use_position_ids=True,
        # Determinism.
        use_random_ids=False,
        use_market_order_acks=False,
        # `True` disables every `free`-balance check in the RiskEngine.
        allow_cash_borrowing=False,
        frozen_account=False,
        # Unit undefined by the docstring against `price_increment`. Guessing a
        # boundary risks rejecting every marketable order (spec §9).
        price_protection_points=None,
        routing=False,
        # Spec §0: the ONLY source of the settlement price.
        settlement_prices=dict(config.settlement_prices),
    )

    for instrument in config.instruments:
        engine.add_instrument(instrument)

    # One call per (instrument, record type). NOT one flat list: `add_data`
    # registers only `data[0]`'s instrument, so a flat heterogeneous list arms
    # the "no order book data" guard for the first instrument and leaves every
    # other one unguarded, with its orders silently REJECTED.
    for group in _group_market_data(config.market_data):
        engine.add_data(group)

    if config.weather_data:
        # Scoped by CLIENT, never by instrument: one climate day settles many
        # markets, and an instrument-scoped weather subscription matches no
        # topic and receives ZERO records with no error. The cost is that every
        # strategy receives every city's records -- see the module docstring.
        engine.add_data(list(config.weather_data), client_id=NWS_BACKTEST_CLIENT_ID)

    return engine


def _refuse_rejected_orders(engine: BacktestEngine) -> None:
    """Refuse a run in which the venue turned an order away.

    The realistic trigger is not a bug in the strategy: a weather record
    stamped before the first depth snapshot makes a MARKET BUY arrive at an
    empty book and be answered ``OrderRejected(reason='no market')``. That is
    the NORMAL shape of real NWS data -- the climate day is issued in the
    morning, the venue tape starts later -- and it produces zero fills, zero
    positions, and no exception.
    """
    refused = [
        order
        for order in engine.cache.orders()
        if order.status in (OrderStatus.DENIED, OrderStatus.REJECTED)
    ]
    if not refused:
        return
    detail = "; ".join(
        sorted(
            f"{order.client_order_id} on {order.instrument_id} "
            f"{order.status_string()}: {getattr(order.last_event, 'reason', 'no reason given')}"
            for order in refused
        ),
    )
    raise SilentRunError(
        SilentRunCondition.REJECTED_ORDERS,
        f"{len(refused)} order(s) were denied or rejected, so this run's fills, positions "
        f"and PnL describe less trading than the strategy asked for: {detail}. Nothing "
        f"raises on a rejection -- the strategy's `on_order_rejected` is called and the "
        f"run continues. If the reason is `no market`, the order arrived before that "
        f"instrument's first depth snapshot. Pass `allow_rejected_orders=True` if the "
        f"rejection is what this run exists to observe.",
    )


def _refuse_open_positions(engine: BacktestEngine) -> None:
    """Refuse a run that ended holding something.

    Cheap, per-instrument, and the only reliable detector of an unsettled leg:
    ``avg_px_close`` is ``0.0`` on a position that never closed, which is the
    same value a genuine settle-at-zero produces.
    """
    open_positions = engine.cache.positions_open()
    if not open_positions:
        return
    detail = "; ".join(
        sorted(
            f"{position.instrument_id} qty={position.quantity} "
            f"(avg_px_close={position.avg_px_close})"
            for position in open_positions
        ),
    )
    raise SilentRunError(
        SilentRunCondition.OPEN_POSITIONS,
        f"{len(open_positions)} position(s) were still open when the run ended, so their "
        f"PnL is unrealised and the run's economics are incomplete: {detail}. You cannot "
        f"see this from the obvious field: `avg_px_close` is 0.0 on a position that never "
        f"closed, which is EXACTLY the value a genuine settle-at-zero produces -- and on a "
        f"weather ladder most legs do settle at zero. `is_closed` and `realized_pnl` are "
        f"the fields that distinguish them. The usual cause is a missing or mis-ordered "
        f"`InstrumentClose`. Pass `allow_open_positions=True` if the open position is what "
        f"this run exists to study.",
    )


def _refuse_idle_strategies(engine: BacktestEngine, strategies: Sequence[Strategy]) -> None:
    """Refuse a run in which some strategy never submitted anything.

    Every downstream number is then a description of an empty portfolio,
    reported as a result. The usual causes are a subscription that matched no
    topic, an instrument missing from the cache, or a condition that was never
    true -- none of which raises.
    """
    submitted = {order.strategy_id for order in engine.cache.orders()}
    idle = sorted(str(strategy.id) for strategy in strategies if strategy.id not in submitted)
    if not idle:
        return
    raise SilentRunError(
        SilentRunCondition.IDLE_STRATEGY,
        f"{len(idle)} strateg(ies) submitted no orders at all: {', '.join(idle)}. Every "
        f"number this run produces is therefore a description of an empty portfolio. The "
        f"usual causes are silent: a `subscribe_data` topic that matched nothing, an "
        f"instrument missing from the cache, or a decision condition that was never true. "
        f"Pass `allow_idle_strategies=True` for a strategy that deliberately never trades.",
    )


def _install_shared_exposure_view(strategies: Sequence[Strategy]) -> None:
    exposure_view = None
    for strategy in strategies:
        new_view = getattr(strategy, "new_shared_exposure_view", None)
        if new_view is not None:
            exposure_view = new_view()
            break
    if exposure_view is None:
        return
    for strategy in strategies:
        install = getattr(strategy, "use_shared_exposure_view", None)
        if install is not None:
            install(exposure_view)


def run_backtest(
    config: BreezyBacktestConfig,
    *,
    strategies: Sequence[Strategy],
    allow_rejected_orders: bool = False,
    allow_open_positions: bool = False,
    allow_idle_strategies: bool = False,
) -> BacktestEngine:
    """Build, register `strategies`, run, refuse a silent result, and hand the engine back.

    Strategies are passed as already-constructed objects rather than as
    ``ImportableStrategyConfig`` entries, for the same reason
    ``breezy.runtime.composition`` constructs its Actors: the config route ends
    in ``strategy_cls(config)`` round-tripped through JSON, which cannot carry
    a live object.

    Parameters
    ----------
    config : BreezyBacktestConfig
    strategies : Sequence[Strategy]
    allow_rejected_orders : bool, default False
        Return a run in which some order was ``DENIED`` or ``REJECTED``.
    allow_open_positions : bool, default False
        Return a run that ended holding an open position.
    allow_idle_strategies : bool, default False
        Return a run in which a strategy submitted no orders.

    Three separate flags, not one ``strict``: each covers a different
    legitimate case, and a single switch would let waiving one waive all three.

    Returns
    -------
    BacktestEngine
        After ``run()``. The caller owns it and must call ``dispose()``; the
        native ``cache`` and ``portfolio`` are the result surfaces. Prefer
        :func:`backtest`, which disposes for you.

    Raises
    ------
    SilentRunError
        If the completed run is empty in any of the three ways above.
    PostOnlyRefusedError, NakedShortRefusedError
        From the submit-time screen; see
        ``breezy.runtime.backtest_order_guard``.

    """
    engine = build_backtest_engine(config)
    try:
        install_order_guard(engine)
        _install_shared_exposure_view(strategies)
        for strategy in strategies:
            engine.add_strategy(strategy)
        engine.run()
        if not allow_rejected_orders:
            _refuse_rejected_orders(engine)
        if not allow_open_positions:
            _refuse_open_positions(engine)
        if not allow_idle_strategies:
            _refuse_idle_strategies(engine, strategies)
    except BaseException:
        # The caller never receives this engine, so nothing else can dispose
        # it, and an abandoned `BacktestEngine` leaves its trader registered
        # for the life of the process. Every diagnostic is already in the
        # exception's own message.
        engine.dispose()
        raise
    return engine


@contextlib.contextmanager
def backtest(
    config: BreezyBacktestConfig,
    *,
    strategies: Sequence[Strategy],
    allow_rejected_orders: bool = False,
    allow_open_positions: bool = False,
    allow_idle_strategies: bool = False,
) -> Iterator[BacktestEngine]:
    """:func:`run_backtest`, with ``dispose()`` guaranteed.

    ``run_backtest`` hands back an engine the caller must dispose, and nothing
    enforces it; a leaked engine leaves its trader registered for the life of
    the process, which in a test session means every later run shares it.

    Examples
    --------
    ::

        with backtest(config, strategies=(strategy,)) as engine:
            position = engine.cache.positions()[0]

    """
    engine = run_backtest(
        config,
        strategies=strategies,
        allow_rejected_orders=allow_rejected_orders,
        allow_open_positions=allow_open_positions,
        allow_idle_strategies=allow_idle_strategies,
    )
    try:
        yield engine
    finally:
        engine.dispose()
