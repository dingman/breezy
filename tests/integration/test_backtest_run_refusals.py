"""``run_backtest`` must refuse to hand back a run that silently did nothing.

Three shapes of empty, all verified against a live engine
---------------------------------------------------------

1. **Every order rejected.** A weather record stamped BEFORE the first depth
   snapshot makes the strategy submit a MARKET BUY into an empty book. The
   ``SimulatedExchange`` answers ``OrderRejected(reason='no market')``. Zero
   fills, zero positions, no exception. This is the NORMAL case for real NWS
   data: the climate day is issued in the morning and the market data arrives
   later, so the first weather record a strategy sees routinely precedes the
   book.
2. **A position left open.** Nothing settled it. ``avg_px_close`` is ``0.0`` on
   an unsettled position -- the SAME value a genuine settle-at-zero produces,
   and on a weather ladder most legs settle at zero -- so the author's obvious
   check cannot distinguish the two.
3. **A strategy that submitted nothing at all.** Its subscription may have
   matched no topic, its instrument may be missing from the cache, its
   condition may never have been true. Every downstream number is then a
   description of an empty portfolio, reported as a result.

Each refusal is INDIVIDUALLY overridable, because each has a legitimate case:
a strategy under test that deliberately never trades, a run studying an
unsettled leg, a rejection the run exists to observe. The overrides are
separate booleans rather than one ``strict=False`` so that waiving one cannot
waive the others -- one flag is how a guard becomes a decoration.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.events import OrderInitialized
from nautilus_trader.model.identifiers import OrderListId
from nautilus_trader.model.objects import Money
from nautilus_trader.model.orders.list import OrderList
from nautilus_trader.trading.config import StrategyConfig
from nautilus_trader.trading.strategy import Strategy

import breezy.runtime.backtest_harness as harness
from breezy.runtime.backtest_feed import as_backtest_data
from breezy.runtime.backtest_harness import (
    BreezyBacktestConfig,
    SilentRunCondition,
    SilentRunError,
    backtest,
    run_backtest,
)
from breezy.runtime.backtest_order_guard import ORDER_EVENT_TOPIC, install_order_guard
from breezy.strategy.harness_probe import BreezyHarnessProbe, BreezyHarnessProbeConfig
from tests.support.synthetic_binary_tape import SyntheticBinaryTape, synthetic_binary_tape
from tests.unit.test_persistence_catalog import make_climate_day

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nautilus_trader.model.data import OrderBookDepth10

CLIP = 10
STARTING_BALANCE_USD = 1_000


def _probe(tape: SyntheticBinaryTape) -> BreezyHarnessProbe:
    return BreezyHarnessProbe(
        BreezyHarnessProbeConfig(
            instrument_id=tape.instrument.id,
            trade_quantity=Decimal(CLIP),
        ),
    )


def _config(tape: SyntheticBinaryTape, **overrides: object) -> BreezyBacktestConfig:
    kwargs: dict[str, object] = {
        "instruments": (tape.instrument,),
        "market_data": tape.all_data(),
        "weather_data": as_backtest_data(
            [make_climate_day(retrieved_at_ns=tape.weather_ts_ns)],
        ),
        "settlement_prices": {tape.instrument.id: tape.settlement_price},
        "starting_balances": (Money(STARTING_BALANCE_USD, tape.instrument.quote_currency),),
    }
    kwargs.update(overrides)
    return BreezyBacktestConfig(**kwargs)  # type: ignore[arg-type]


@pytest.fixture
def tape() -> SyntheticBinaryTape:
    return synthetic_binary_tape(size_precision=0, settlement_price=1.0)


def _weather_before_the_book(tape: SyntheticBinaryTape) -> tuple[object, ...]:
    """A climate day stamped before the first depth snapshot.

    The realistic case, not a contrived one: NWS issues the climate day in the
    morning, the venue tape starts later.
    """
    first_depth: OrderBookDepth10 = tape.market_data[0]
    return tuple(
        as_backtest_data([make_climate_day(retrieved_at_ns=first_depth.ts_init - 1)]),
    )


# ---------------------------------------------------------------------------
# 1 -- a run in which every order was rejected
# ---------------------------------------------------------------------------


def test_a_run_whose_only_order_was_rejected_is_refused(tape: SyntheticBinaryTape) -> None:
    with pytest.raises(SilentRunError) as excinfo:
        run_backtest(
            _config(tape, weather_data=_weather_before_the_book(tape)),
            strategies=(_probe(tape),),
        )

    assert excinfo.value.condition is SilentRunCondition.REJECTED_ORDERS


def test_the_rejection_error_carries_the_venue_reason(tape: SyntheticBinaryTape) -> None:
    """`no market` is the whole diagnosis, and it is otherwise only in a log
    line the harness used to suppress.
    """
    with pytest.raises(SilentRunError) as excinfo:
        run_backtest(
            _config(tape, weather_data=_weather_before_the_book(tape)),
            strategies=(_probe(tape),),
        )

    assert "no market" in str(excinfo.value)


def test_the_rejection_refusal_is_individually_overridable(
    tape: SyntheticBinaryTape,
) -> None:
    """A run that EXISTS to observe a rejection must still be writable.

    Note that the other two refusals still apply -- with no fill there is no
    position to leave open, but the probe did submit, so `allow_idle_strategies`
    is not needed. One override, one waiver.
    """
    engine = run_backtest(
        _config(tape, weather_data=_weather_before_the_book(tape)),
        strategies=(_probe(tape),),
        allow_rejected_orders=True,
    )
    try:
        assert engine.cache.positions() == []
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# 2 -- a position left open
# ---------------------------------------------------------------------------


def test_a_run_leaving_a_position_open_is_refused(tape: SyntheticBinaryTape) -> None:
    with pytest.raises(SilentRunError) as excinfo:
        run_backtest(
            _config(
                tape,
                market_data=list(tape.market_data),
                instruments_without_close=frozenset({tape.instrument.id}),
            ),
            strategies=(_probe(tape),),
        )

    assert excinfo.value.condition is SilentRunCondition.OPEN_POSITIONS


def test_the_open_position_error_names_the_instrument(tape: SyntheticBinaryTape) -> None:
    with pytest.raises(SilentRunError) as excinfo:
        run_backtest(
            _config(
                tape,
                market_data=list(tape.market_data),
                instruments_without_close=frozenset({tape.instrument.id}),
            ),
            strategies=(_probe(tape),),
        )

    assert str(tape.instrument.id) in str(excinfo.value)


def test_the_open_position_error_explains_the_avg_px_close_trap(
    tape: SyntheticBinaryTape,
) -> None:
    """An author cannot detect this from the obvious field, so the guard says so.

    H-2: tightened from the bare field name "avg_px_close" (which also
    appears earlier in the same message purely as part of the `detail`
    listing, e.g. "(avg_px_close=0.0)") to the actual TRAP being explained --
    that the field reads the same 0.0 an unsettled position and a genuine
    settle-at-zero both produce.
    """
    with pytest.raises(SilentRunError) as excinfo:
        run_backtest(
            _config(
                tape,
                market_data=list(tape.market_data),
                instruments_without_close=frozenset({tape.instrument.id}),
            ),
            strategies=(_probe(tape),),
        )

    assert "`avg_px_close` is 0.0 on a position that never closed" in str(excinfo.value)


def test_the_open_position_refusal_is_individually_overridable(
    tape: SyntheticBinaryTape,
) -> None:
    engine = run_backtest(
        _config(
            tape,
            market_data=list(tape.market_data),
            instruments_without_close=frozenset({tape.instrument.id}),
        ),
        strategies=(_probe(tape),),
        allow_open_positions=True,
    )
    try:
        assert [p.is_closed for p in engine.cache.positions()] == [False]
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# 3 -- a strategy that submitted nothing
# ---------------------------------------------------------------------------


def test_a_strategy_that_submitted_no_orders_is_refused(tape: SyntheticBinaryTape) -> None:
    """No weather reaches the probe, so its only trigger never fires."""
    with pytest.raises(SilentRunError) as excinfo:
        run_backtest(_config(tape, weather_data=()), strategies=(_probe(tape),))

    assert excinfo.value.condition is SilentRunCondition.IDLE_STRATEGY


def test_the_idle_strategy_error_names_the_strategy(tape: SyntheticBinaryTape) -> None:
    probe = _probe(tape)

    with pytest.raises(SilentRunError) as excinfo:
        run_backtest(_config(tape, weather_data=()), strategies=(probe,))

    assert str(probe.id) in str(excinfo.value)


def test_the_idle_strategy_refusal_is_individually_overridable(
    tape: SyntheticBinaryTape,
) -> None:
    """A strategy under test that deliberately never trades is legitimate."""
    probe = _probe(tape)
    engine = run_backtest(
        _config(tape, weather_data=()),
        strategies=(probe,),
        allow_idle_strategies=True,
    )
    try:
        assert probe.orders_submitted == 0
    finally:
        engine.dispose()


def test_a_healthy_run_is_returned_untouched(tape: SyntheticBinaryTape) -> None:
    """The refusals must not fire on the run the stop gate already proves."""
    probe = _probe(tape)
    engine = run_backtest(_config(tape), strategies=(probe,))
    try:
        assert probe.own_fills == 1
        assert [p.is_closed for p in engine.cache.positions()] == [True]
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# The refused engine is disposed, not leaked
# ---------------------------------------------------------------------------


def test_a_refused_run_does_not_leak_its_engine(
    tape: SyntheticBinaryTape,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The caller never receives the engine, so the harness must dispose it.

    A `BacktestEngine` that is built and abandoned leaves its trader registered
    for the life of the process. The engine is captured by wrapping the
    harness's own builder, because the refusal path deliberately returns
    nothing -- an assertion on a later run's success would pass whether or not
    the first engine had been disposed.
    """
    captured: list[object] = []
    original = harness.build_backtest_engine

    def _capture(config: BreezyBacktestConfig) -> object:
        engine = original(config)
        captured.append(engine)
        return engine

    monkeypatch.setattr(harness, "build_backtest_engine", _capture)

    with pytest.raises(SilentRunError):
        run_backtest(_config(tape, weather_data=()), strategies=(_probe(tape),))

    assert len(captured) == 1
    assert captured[0].trader.is_disposed  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# The disposing context manager
# ---------------------------------------------------------------------------


def test_the_context_manager_disposes_the_engine(tape: SyntheticBinaryTape) -> None:
    with backtest(_config(tape), strategies=(_probe(tape),)) as engine:
        assert not engine.trader.is_disposed

    assert engine.trader.is_disposed


def test_the_context_manager_disposes_even_when_the_body_raises(
    tape: SyntheticBinaryTape,
) -> None:
    captured = None
    with (
        pytest.raises(ZeroDivisionError),
        backtest(_config(tape), strategies=(_probe(tape),)) as engine,
    ):
        captured = engine
        raise ZeroDivisionError

    assert captured is not None
    assert captured.trader.is_disposed


# ---------------------------------------------------------------------------
# Logging is NOT bypassed by default
# ---------------------------------------------------------------------------


def test_engine_logging_is_on_by_default() -> None:
    """`bypass_logging=True` deletes every diagnostic above.

    `OrderRejected`, `OrderDenied` and the settlement fall-through are all
    reported by the engine's own logger and by nothing else. A harness whose
    default is to suppress them is a harness that hides its own failures.
    """
    tape = synthetic_binary_tape(size_precision=0, settlement_price=1.0)

    assert _config(tape).bypass_logging is False


# ---------------------------------------------------------------------------
# post_only is refused at SUBMIT time, not at fill time
# ---------------------------------------------------------------------------


class _PostOnlyProbeConfig(StrategyConfig, frozen=True):
    instrument_id: object


class _PostOnlyProbe(Strategy):  # type: ignore[misc]  # Strategy is a compiled Cython class erasing to Any
    """Submits one post-only LIMIT far from the touch, so it can never fill."""

    def __init__(self, config: _PostOnlyProbeConfig) -> None:
        super().__init__(config)
        self.submitted = 0

    def on_start(self) -> None:
        self.subscribe_order_book_depth(self.config.instrument_id)

    def on_order_book_depth(self, depth: object) -> None:
        if self.submitted:
            return
        instrument = self.cache.instrument(self.config.instrument_id)
        self.submitted += 1
        self.submit_order(
            self.order_factory.limit(
                instrument_id=instrument.id,
                order_side=OrderSide.BUY,
                quantity=instrument.make_qty(Decimal(1)),
                price=instrument.make_price(Decimal("0.01")),
                time_in_force=TimeInForce.GTC,
                post_only=True,
            ),
        )


def test_a_post_only_order_is_refused_when_it_is_SUBMITTED(
    tape: SyntheticBinaryTape,
) -> None:
    """The policy is right; the PHASE was wrong.

    `PolymarketUSFeeModel` raises `MakerRebateUnmodelledError` when it PRICES a
    post-only fill -- so a post-only order that never fills gives the author no
    signal at all, and one that does fill aborts the run halfway through with
    an error about fees. Refusing the intent at submit time makes the same
    policy legible.
    """
    strategy = _PostOnlyProbe(_PostOnlyProbeConfig(instrument_id=tape.instrument.id))

    # H-2: `match="post_only"` would also match a message that only ever
    # mentioned the PARAMETER NAME in passing; the value is the actual claim
    # (that THIS order carried it), matching the guard's own message and the
    # unit-level pin in `test_runtime_backtest_order_guard.py`.
    with pytest.raises(ValueError, match="post_only=True") as excinfo:
        run_backtest(_config(tape), strategies=(strategy,))

    # H-2: tightened from a case-insensitive check for the word "rebate"
    # (which could survive a rewrite that dropped the actual coefficient) to
    # the specific numeric fact the message exists to convey -- the sign and
    # magnitude of the maker rebate the fee model cannot price.
    assert "-0.0125" in str(excinfo.value)


# ---------------------------------------------------------------------------
# A naked short is refused BY THE HARNESS
# ---------------------------------------------------------------------------


class _NakedShortProbeConfig(StrategyConfig, frozen=True):
    instrument_id: object
    quantity: Decimal


class _NakedShortProbe(Strategy):  # type: ignore[misc]  # Strategy is a compiled Cython class erasing to Any
    """Sells with no position at all -- which the RiskEngine cannot catch.

    `CashAccount.balance_impact` returns +notional for a SELL, so
    `(free + impact) < 0` can never fire; 1.231.0 exempts position-reducing
    sells, so the only sells reaching that gate are the naked ones.
    """

    def __init__(self, config: _NakedShortProbeConfig) -> None:
        super().__init__(config)
        self.submitted = 0

    def on_start(self) -> None:
        self.subscribe_order_book_depth(self.config.instrument_id)

    def on_order_book_depth(self, depth: object) -> None:
        if self.submitted:
            return
        instrument = self.cache.instrument(self.config.instrument_id)
        self.submitted += 1
        self.submit_order(
            self.order_factory.limit(
                instrument_id=instrument.id,
                order_side=OrderSide.SELL,
                quantity=instrument.make_qty(self.config.quantity),
                price=instrument.make_price(Decimal("0.10")),
                time_in_force=TimeInForce.GTC,
                post_only=False,
            ),
        )


def test_a_sell_with_no_position_is_refused_by_the_harness(
    tape: SyntheticBinaryTape,
) -> None:
    """Verified live: 500 contracts against $1000 cash and a ZERO position was
    accepted and filled 50, with no rejection and no warning.
    """
    strategy = _NakedShortProbe(
        _NakedShortProbeConfig(instrument_id=tape.instrument.id, quantity=Decimal(500)),
    )

    # H-2: `match="naked"` would also match if the word appeared only in an
    # unrelated aside; `"naked short of"` is the phrase that introduces the
    # actual computed overage and cannot appear without the claim it makes.
    with pytest.raises(ValueError, match="naked short of") as excinfo:
        run_backtest(_config(tape), strategies=(strategy,))

    assert str(tape.instrument.id) in str(excinfo.value)


def test_the_naked_short_guard_lives_in_the_harness_not_in_the_strategy(
    tape: SyntheticBinaryTape,
) -> None:
    """The point of moving it.

    `_NakedShortProbe` contains no guard of any kind, and is not required to:
    the spec used to prescribe "a strategy-side invariant", which asks every
    author to re-derive it from prose they may never read.
    """
    source = _NakedShortProbe.__module__

    assert source is not None
    strategy = _NakedShortProbe(
        _NakedShortProbeConfig(instrument_id=tape.instrument.id, quantity=Decimal(1)),
    )

    with pytest.raises(ValueError, match="naked short of"):
        run_backtest(_config(tape), strategies=(strategy,))


# ---------------------------------------------------------------------------
# RED-9: the settlement leg publishes no `OrderInitialized` -- behind §1/§2
# ---------------------------------------------------------------------------


def test_the_expiration_settlement_leg_publishes_no_order_initialized_to_the_guard(
    tape: SyntheticBinaryTape,
) -> None:
    """RED-9, load-bearing. Widening `_refuse_naked_short` to run for every
    SELL (dropping the `reduce_only` exemption) can only be safe if the
    engine's own settlement leg -- a `reduce_only` SELL sized to the whole
    position -- never reaches the guard at all (F7). Proved behaviourally,
    independent of the guard's own screening: a second handler subscribed to
    the SAME topic (`ORDER_EVENT_TOPIC`) captures every `OrderInitialized`
    published during a full run that holds a position to expiry, and none of
    them is the `EXPIRATION-LEG-<uuid4>` the engine builds directly via
    `cache.add_order` + `_generate_order_accepted`
    (`backtest/engine.pyx:5945-5978`).
    """
    engine = harness.build_backtest_engine(_config(tape))
    captured: list[OrderInitialized] = []

    def _capture(event: object) -> None:
        if type(event) is OrderInitialized:
            captured.append(event)

    engine.kernel.msgbus.subscribe(topic=ORDER_EVENT_TOPIC, handler=_capture)
    install_order_guard(engine)
    probe = _probe(tape)
    engine.add_strategy(probe)
    try:
        engine.run()
    finally:
        engine.dispose()

    # Positive control: the probe's own entry order DID publish one, so an
    # empty `captured` would mean the subscription never worked at all.
    assert captured
    assert not any(
        str(event.client_order_id).startswith("EXPIRATION-LEG-") for event in captured
    )


# ---------------------------------------------------------------------------
# RED-10: the accept window (§5, corrected) does not endanger settlement
# ---------------------------------------------------------------------------


class _AcceptWatchingProbe(BreezyHarnessProbe):
    """RED-10. Overrides `on_order_accepted` -- the window §5 names as the
    only currently-reachable residual behind `_working_sell_quantity`'s
    counting (no Breezy strategy did this before this test) -- and submits
    nothing from it. If reached, the leg is still open at full size with the
    position still open at full size, so any further SELL screened during
    this window is genuinely naked; §5 concludes this can only produce a
    CORRECT refusal, never a false one, and this probe never submits from the
    hook at all, so nothing should fire here either way.
    """

    def __init__(self, config: BreezyHarnessProbeConfig) -> None:
        super().__init__(config)
        self.accepted = 0

    def on_order_accepted(self, event: object) -> None:
        del event
        self.accepted += 1


def test_a_harness_run_holding_a_long_to_expiration_still_settles_under_the_guard(
    tape: SyntheticBinaryTape,
) -> None:
    probe = _AcceptWatchingProbe(
        BreezyHarnessProbeConfig(instrument_id=tape.instrument.id, trade_quantity=Decimal(CLIP)),
    )

    engine = run_backtest(_config(tape), strategies=(probe,))
    try:
        # Positive control: the accept hook actually fired (for the probe's
        # own entry, and again for the engine's settlement leg, which shares
        # the probe's `strategy_id`) -- an untouched `accepted == 0` would
        # mean this test exercised nothing.
        assert probe.accepted >= 1
        assert [p.is_closed for p in engine.cache.positions()] == [True]
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# RED-12: `submit_order_list` defeats the guard outright -- TRACKED, not fixed
# ---------------------------------------------------------------------------


class _OrderListNakedShortProbeConfig(StrategyConfig, frozen=True):
    instrument_id: object
    quantity: Decimal


class _OrderListNakedShortProbe(Strategy):  # type: ignore[misc]  # Strategy is a compiled Cython class erasing to Any
    """Enters a long, then exits it via `submit_order_list` with TWO plain
    SELLs each sized to the whole position -- no `reduce_only`, nothing
    attacker-settable.

    `Strategy.submit_order_list` publishes every member's `OrderInitialized`
    in one loop BEFORE any of them reaches `cache.add_order`
    (`trading/strategy.pyx:944-981`), so `_working_sell_quantity` reads
    `pending=0` for EVERY member -- both sells pass and net a naked short.
    """

    def __init__(self, config: _OrderListNakedShortProbeConfig) -> None:
        super().__init__(config)
        self.entered = False
        self.listed = False

    def on_start(self) -> None:
        self.subscribe_order_book_depth(self.config.instrument_id)

    def on_order_book_depth(self, depth: object) -> None:
        del depth
        if self.entered:
            return
        self.entered = True
        instrument = self.cache.instrument(self.config.instrument_id)
        self.submit_order(
            self.order_factory.market(
                instrument_id=instrument.id,
                order_side=OrderSide.BUY,
                quantity=instrument.make_qty(self.config.quantity),
            ),
        )

    def on_order_filled(self, event: object) -> None:
        if self.listed or event.order_side != OrderSide.BUY:  # type: ignore[attr-defined]
            return
        self.listed = True
        instrument = self.cache.instrument(self.config.instrument_id)
        legs = [
            self.order_factory.limit(
                instrument_id=instrument.id,
                order_side=OrderSide.SELL,
                quantity=instrument.make_qty(self.config.quantity),
                price=instrument.make_price(Decimal("0.10")),
                time_in_force=TimeInForce.GTC,
            )
            for _ in range(2)
        ]
        self.submit_order_list(OrderList(OrderListId("OL-1"), legs))


def test_an_order_list_of_two_sells_within_the_net_long_is_jointly_naked(
    tape: SyntheticBinaryTape,
) -> None:
    """CLOSED by `docs/plans/ORDER_LIST_BYPASS_2026-09-02.md` Increment 2 (§3):
    a cache-subordinate shim records every SELL the guard itself approves,
    live only while `cache.order(client_order_id) is None`. That covers
    exactly this shape -- `Strategy.submit_order_list` publishes every
    member's `OrderInitialized` in one loop BEFORE any of them reaches
    `cache.add_order` (`trading/strategy.pyx:944-981`), so the cache-sourced
    sum alone reads `pending=0` for every member -- without any eviction
    event to miss, since an entry that DOES reach the cache (by any path)
    is inert from that point on by the same predicate.
    """
    strategy = _OrderListNakedShortProbe(
        _OrderListNakedShortProbeConfig(instrument_id=tape.instrument.id, quantity=Decimal(CLIP)),
    )
    engine = None
    try:
        with pytest.raises(ValueError, match="naked short of"):
            engine = run_backtest(_config(tape), strategies=(strategy,))
    finally:
        if engine is not None:
            engine.dispose()


# ---------------------------------------------------------------------------
# RED-13: two PLAIN `submit_order` SELLs defeat the guard too -- no order
# list, no `reduce_only`, nothing exotic. docs/plans/ORDER_LIST_BYPASS_2026-
# 09-02.md §0 G6, closed by Increment 1 (widening `_working_sell_quantity`
# from `cache.orders_open(...)` to `cache.orders(...)` filtered to
# `not is_closed`).
# ---------------------------------------------------------------------------


class _TwoPlainSellsNakedShortProbeConfig(StrategyConfig, frozen=True):
    instrument_id: object
    quantity: Decimal


class _TwoPlainSellsNakedShortProbe(Strategy):  # type: ignore[misc]  # Strategy is a compiled Cython class erasing to Any
    """Enters a long, then exits it with TWO sequential plain `submit_order`
    SELLs, each sized to the whole position -- no `OrderList`, no
    `reduce_only`.

    Each `submit_order` publishes its `OrderInitialized` BEFORE calling
    `cache.add_order` (`trading/strategy.pyx:855-859`), but the FIRST sell's
    `cache.add_order` has already run (it happened when the first sell's own
    `OrderSubmitted`/`OrderAccepted` events processed, upstream of this
    handler) by the time the second is screened -- it sits in the cache as
    `SUBMITTED`, invisible to `cache.orders_open(...)` (G5), so the
    pre-Increment-1 guard read `pending=0` for the second sell and approved
    both.
    """

    def __init__(self, config: _TwoPlainSellsNakedShortProbeConfig) -> None:
        super().__init__(config)
        self.entered = False
        self.sells_submitted = 0

    def on_start(self) -> None:
        self.subscribe_order_book_depth(self.config.instrument_id)

    def on_order_book_depth(self, depth: object) -> None:
        del depth
        if self.entered:
            return
        self.entered = True
        instrument = self.cache.instrument(self.config.instrument_id)
        self.submit_order(
            self.order_factory.market(
                instrument_id=instrument.id,
                order_side=OrderSide.BUY,
                quantity=instrument.make_qty(self.config.quantity),
            ),
        )

    def on_order_filled(self, event: object) -> None:
        if self.sells_submitted >= 2 or event.order_side != OrderSide.BUY:  # type: ignore[attr-defined]
            return
        instrument = self.cache.instrument(self.config.instrument_id)
        for _ in range(2):
            self.sells_submitted += 1
            self.submit_order(
                self.order_factory.limit(
                    instrument_id=instrument.id,
                    order_side=OrderSide.SELL,
                    quantity=instrument.make_qty(self.config.quantity),
                    price=instrument.make_price(Decimal("0.10")),
                    time_in_force=TimeInForce.GTC,
                ),
            )


def test_two_plain_submit_order_sells_within_the_net_long_are_jointly_naked(
    tape: SyntheticBinaryTape,
) -> None:
    strategy = _TwoPlainSellsNakedShortProbe(
        _TwoPlainSellsNakedShortProbeConfig(
            instrument_id=tape.instrument.id,
            quantity=Decimal(CLIP),
        ),
    )
    engine = None
    try:
        with pytest.raises(ValueError, match="naked short of"):
            engine = run_backtest(_config(tape), strategies=(strategy,))
    finally:
        if engine is not None:
            engine.dispose()
