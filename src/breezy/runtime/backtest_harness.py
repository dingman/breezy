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

**Genuinely absent, and therefore authored here.** Exactly one thing: the
three settlement invariants of spec §5. Nautilus enforces none of them, and
each failure is silent:

* *Coverage.* ``check_instrument_expiration`` (``backtest/engine.pyx:5934``)
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

import enum
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.backtest.models import FillModel
from nautilus_trader.config import LoggingConfig
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import CustomData, InstrumentClose
from nautilus_trader.model.enums import AccountType, BookType, InstrumentCloseType, OmsType
from nautilus_trader.model.identifiers import TraderId

from breezy.adapters.polymarket_us.fees import PolymarketUSFeeModel
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE
from breezy.runtime.backtest_feed import NWS_BACKTEST_CLIENT_ID

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterable, Mapping, Sequence

    from nautilus_trader.core.data import Data
    from nautilus_trader.model.identifiers import InstrumentId
    from nautilus_trader.model.instruments import Instrument
    from nautilus_trader.model.objects import Money
    from nautilus_trader.trading.strategy import Strategy

__all__ = [
    "DEFAULT_BACKTEST_INSTANCE_ID",
    "DEFAULT_BACKTEST_TRADER_ID",
    "HARNESS_SOURCE_PATH",
    "BreezyBacktestConfig",
    "SettlementInvariant",
    "SettlementInvariantError",
    "UnwrappedWeatherRecordError",
    "assert_settlement_invariants",
    "assert_weather_is_wrapped",
    "build_backtest_engine",
    "run_backtest",
]

#: This module's own file, so a source-level test can read the `add_venue`
#: call without re-deriving the path and silently scanning nothing.
HARNESS_SOURCE_PATH: Final[str] = __file__

#: Fixed rather than generated. `TraderId` is stamped into every
#: `ClientOrderId`, so a per-run value would make two identical runs produce
#: different order ids -- determinism is a property of the whole harness, not
#: only of `use_random_ids=False`.
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


@enum.unique
class SettlementInvariant(enum.Enum):
    """Which of the three §5 rules a :class:`SettlementInvariantError` names."""

    #: Every instrument receiving a ``CONTRACT_EXPIRED`` close has a price.
    COVERAGE = "coverage"
    #: Every settlement price is exactly ``0.0`` or ``1.0``.
    ENDPOINT = "endpoint"
    #: Every close's ``ts_init`` strictly exceeds its instrument's last
    #: market-data ``ts_init``.
    ORDERING = "ordering"


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


class SettlementInvariantError(ValueError):
    """A backtest was configured in a way whose error would not be visible.

    Carries :attr:`invariant` so a caller (and a test) can distinguish the
    three rules without matching on message text.
    """

    def __init__(self, invariant: SettlementInvariant, message: str) -> None:
        super().__init__(message)
        self.invariant = invariant


@dataclass(frozen=True, kw_only=True, slots=True)
class BreezyBacktestConfig:
    """Everything the harness needs that is not fixed by the venue spec.

    Parameters
    ----------
    instruments : Sequence[Instrument]
        Every instrument the run touches. Each is added before any data, as
        ``BacktestEngine.add_data`` requires a matching instrument in the cache.
    market_data : Sequence[Data]
        Venue market data -- ``OrderBookDepth10``, ``QuoteTick``, and the
        terminal ``InstrumentClose`` records. Order does not matter: the engine
        sorts by ``ts_init``.
    weather_data : Sequence[Data]
        Weather records **already wrapped** by
        :func:`breezy.runtime.backtest_feed.as_backtest_data`. Passing bare
        ``NwsClimateDay`` objects here would see them logged and dropped by
        ``DataEngine._handle_data``; wrapping is the caller's step because the
        catalog readers deliberately return the unwrapped shape.
    settlement_prices : Mapping[InstrumentId, float]
        Spec §0. The ONLY source of the settlement price -- an instrument
        absent from this mapping closes at the prevailing book.
    starting_balances : Sequence[Money]
        An operator budget decision, not a venue fact (spec §1).
    trader_id, instance_id : optional
        Pinned by default for determinism; overridable so two runs can be told
        apart when that is what the caller wants.
    bypass_logging : bool
        Default ``True``. The engine's logger writes to stdout with wall-clock
        timestamps, which is noise in a test and a determinism hazard in a
        recorded transcript.

    """

    instruments: Sequence[Instrument]
    market_data: Sequence[Data]
    settlement_prices: Mapping[InstrumentId, float]
    starting_balances: Sequence[Money]
    weather_data: Sequence[Data] = field(default_factory=tuple)
    trader_id: TraderId = DEFAULT_BACKTEST_TRADER_ID
    instance_id: UUID4 = DEFAULT_BACKTEST_INSTANCE_ID
    bypass_logging: bool = True


def _expired_instrument_ids(market_data: Iterable[Data]) -> set[InstrumentId]:
    """Instruments that receive a ``CONTRACT_EXPIRED`` close.

    Type-EXACT on ``InstrumentClose`` and identity-exact on the close type: a
    ``END_OF_SESSION`` close is discarded by
    ``SimulatedExchange.process_instrument_close`` (``engine.pyx:4844``) and so
    never reaches the settlement branch. Demanding a price for it would be a
    false positive, and a barrier that must be silenced will be silenced.
    """
    return {
        record.instrument_id
        for record in market_data
        if type(record) is InstrumentClose
        and record.close_type == InstrumentCloseType.CONTRACT_EXPIRED
    }


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


def assert_settlement_invariants(
    *,
    market_data: Sequence[Data],
    settlement_prices: Mapping[InstrumentId, float],
) -> None:
    """Enforce the three §5 invariants, or raise.

    Raises
    ------
    SettlementInvariantError
        Carrying the :class:`SettlementInvariant` that failed.

    """
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
        f"{record.instrument_id} close ts_init={record.ts_init} <= "
        f"last market data ts_init={latest[record.instrument_id]}"
        for record in market_data
        if type(record) is InstrumentClose
        and record.close_type == InstrumentCloseType.CONTRACT_EXPIRED
        and record.instrument_id in latest
        and record.ts_init <= latest[record.instrument_id]
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


def build_backtest_engine(config: BreezyBacktestConfig) -> BacktestEngine:
    """Assemble a `BacktestEngine` with the POLYMARKET_US venue, per the spec.

    Every guard runs FIRST, before any engine exists: a ``BacktestEngine``
    that is constructed and then abandoned leaves its trader registered for the
    lifetime of the process, so raising after construction would leak.

    Returns
    -------
    BacktestEngine
        The native engine, unwrapped. The caller owns it, and must call
        ``dispose()``.

    Raises
    ------
    SettlementInvariantError
        If any §5 invariant fails.
    UnwrappedWeatherRecordError
        If any weather record is missing its ``CustomData`` envelope.

    """
    assert_settlement_invariants(
        market_data=config.market_data,
        settlement_prices=config.settlement_prices,
    )
    assert_weather_is_wrapped(config.weather_data)

    # `msgspec.Struct` config classes are untyped to mypy (compiled Nautilus
    # surface), so the constructor call is typed as Any at this one boundary.
    engine_config: Any = BacktestEngineConfig(
        trader_id=config.trader_id,
        instance_id=config.instance_id,
        logging=LoggingConfig(bypass_logging=config.bypass_logging),
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

    engine.add_data(list(config.market_data))
    if config.weather_data:
        # Scoped by CLIENT, never by instrument: one climate day settles many
        # markets, and an instrument-scoped weather subscription matches no
        # topic and receives ZERO records with no error.
        engine.add_data(list(config.weather_data), client_id=NWS_BACKTEST_CLIENT_ID)

    return engine


def run_backtest(
    config: BreezyBacktestConfig,
    *,
    strategies: Sequence[Strategy],
) -> BacktestEngine:
    """Build, register `strategies`, run, and hand the engine back.

    Strategies are passed as already-constructed objects rather than as
    ``ImportableStrategyConfig`` entries, for the same reason
    ``breezy.runtime.composition`` constructs its Actors: the config route ends
    in ``strategy_cls(config)`` round-tripped through JSON, which cannot carry
    a live object.

    Returns
    -------
    BacktestEngine
        After ``run()``. The caller owns it and must call ``dispose()``; the
        native ``cache`` and ``portfolio`` are the result surfaces.

    """
    engine = build_backtest_engine(config)
    for strategy in strategies:
        engine.add_strategy(strategy)
    engine.run()
    return engine
