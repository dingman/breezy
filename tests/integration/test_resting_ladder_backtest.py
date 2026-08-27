"""`BreezyRestingLadder` driven end-to-end through the real backtest harness.

This is an ACCEPTANCE test for the harness written from a strategy author's
seat: it asserts that a LIMIT-order, resting-liquidity strategy which
modifies, cancels, and reads cache/portfolio state actually does those things
inside ``breezy.runtime.backtest_harness.run_backtest``.

Everything it runs against is fabricated
(``tests/support/synthetic_binary_tape.py`` plus the moving tape below); no
number here is a venue observation.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from nautilus_trader.model.data import BookOrder, OrderBookDepth10
from nautilus_trader.model.enums import OrderSide, OrderStatus
from nautilus_trader.model.events import OrderFilled
from nautilus_trader.model.objects import Money, Price, Quantity

from breezy.runtime.backtest_harness import BreezyBacktestConfig, run_backtest
from breezy.strategy.resting_ladder import BreezyRestingLadder, BreezyRestingLadderConfig
from tests.support.synthetic_binary_tape import SyntheticBinaryTape, synthetic_binary_tape

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nautilus_trader.backtest.engine import BacktestEngine

CLIP = 10
STARTING_BALANCE_USD = 1_000
_STEP_NS = 1_000_000_000


def _strategy(tape: SyntheticBinaryTape, **overrides: object) -> BreezyRestingLadder:
    return BreezyRestingLadder(
        BreezyRestingLadderConfig(
            instrument_id=tape.instrument.id,
            clip=Decimal(CLIP),
            **overrides,  # type: ignore[arg-type]
        ),
    )


def _config(tape: SyntheticBinaryTape, market_data: object = None) -> BreezyBacktestConfig:
    return BreezyBacktestConfig(
        instruments=(tape.instrument,),
        market_data=tape.all_data() if market_data is None else market_data,  # type: ignore[arg-type]
        settlement_prices={tape.instrument.id: tape.settlement_price},
        starting_balances=(Money(STARTING_BALANCE_USD, tape.instrument.quote_currency),),
    )


@pytest.fixture(scope="module")
def tape() -> SyntheticBinaryTape:
    # Enough snapshots that the engine clock reaches both time alerts before
    # the terminal close: last data ts is base + 9s, alerts at +2s and +4s.
    return synthetic_binary_tape(size_precision=0, settlement_price=1.0, depth_updates=5)


@pytest.fixture(scope="module")
def run(tape: SyntheticBinaryTape) -> tuple[BacktestEngine, BreezyRestingLadder]:
    strategy = _strategy(tape)
    engine = run_backtest(_config(tape), strategies=(strategy,))
    return engine, strategy


# ---------------------------------------------------------------------------
# The strategy actually did something
# ---------------------------------------------------------------------------


def test_the_depth_callback_drove_the_strategy(
    run: tuple[BacktestEngine, BreezyRestingLadder],
) -> None:
    _engine, strategy = run

    assert strategy.depths > 0


def test_three_limit_orders_were_submitted(
    run: tuple[BacktestEngine, BreezyRestingLadder],
) -> None:
    """Take, rest, and the cache-sized exit sell."""
    _engine, strategy = run

    assert strategy.orders_submitted == 3


def test_the_marketable_limit_buy_filled_as_taker(
    run: tuple[BacktestEngine, BreezyRestingLadder],
) -> None:
    _engine, strategy = run

    assert strategy.own_fills == 1
    assert strategy.own_fill_sides == (OrderSide.BUY,)
    assert strategy.maker_fills == 0


def test_the_resting_buy_was_modified(
    run: tuple[BacktestEngine, BreezyRestingLadder],
) -> None:
    _engine, strategy = run

    assert strategy.modifies_requested == 1
    assert strategy.updates == 1


def test_the_still_open_orders_were_cancelled(
    run: tuple[BacktestEngine, BreezyRestingLadder],
) -> None:
    _engine, strategy = run

    assert strategy.cancels_requested == 2  # the resting buy and the exit sell
    assert strategy.cancel_events == 2


def test_no_order_was_rejected(
    run: tuple[BacktestEngine, BreezyRestingLadder],
) -> None:
    _engine, strategy = run

    assert strategy.rejections == 0


def test_the_time_alerts_fired_on_the_engine_clock(
    run: tuple[BacktestEngine, BreezyRestingLadder],
) -> None:
    _engine, strategy = run

    assert strategy.timer_events == 2


def test_cache_and_portfolio_were_readable_from_inside_the_strategy(
    run: tuple[BacktestEngine, BreezyRestingLadder],
) -> None:
    _engine, strategy = run

    assert strategy.open_orders_at_sweep == 2
    assert strategy.net_position_at_sweep == Decimal(CLIP)


# ---------------------------------------------------------------------------
# The economics came out
# ---------------------------------------------------------------------------


def test_the_position_settled_and_produced_pnl(
    run: tuple[BacktestEngine, BreezyRestingLadder],
    tape: SyntheticBinaryTape,
) -> None:
    engine, _strategy = run
    position = engine.cache.positions()[0]
    fills = [
        event
        for order in engine.cache.orders()
        for event in order.events
        if isinstance(event, OrderFilled)
    ]
    commissions = sum((f.commission.as_decimal() for f in fills), Decimal(0))
    expected = (
        Decimal(CLIP) * (Decimal(str(tape.settlement_price)) - tape.best_ask.as_decimal())
        - commissions
    )

    assert position.is_closed
    assert position.avg_px_close == tape.settlement_price
    assert position.realized_pnl is not None
    assert position.realized_pnl.as_decimal() == expected
    assert position.realized_pnl.as_decimal() > 0


def test_the_run_is_deterministic(tape: SyntheticBinaryTape) -> None:
    first = _strategy(tape)
    second = _strategy(tape)
    engine_a = run_backtest(_config(tape), strategies=(first,))
    engine_b = run_backtest(_config(tape), strategies=(second,))
    try:
        assert first.decisions == second.decisions
        assert len(first.decisions) > 0
    finally:
        engine_a.dispose()
        engine_b.dispose()


# ---------------------------------------------------------------------------
# The maker path: what happens when a resting limit is crossed by the book
# ---------------------------------------------------------------------------


def _depth(
    tape: SyntheticBinaryTape,
    *,
    bids: tuple[tuple[str, int], ...],
    asks: tuple[tuple[str, int], ...],
    sequence: int,
    ts: int,
) -> OrderBookDepth10:
    instrument = tape.instrument

    def side(levels: tuple[tuple[str, int], ...], s: OrderSide) -> list[BookOrder]:
        return [
            BookOrder(
                s,
                Price(float(px), instrument.price_precision),
                Quantity(size, instrument.size_precision),
                0,
            )
            for px, size in levels
        ]

    return OrderBookDepth10(
        instrument_id=instrument.id,
        bids=side(bids, OrderSide.BUY),
        asks=side(asks, OrderSide.SELL),
        bid_counts=[1] * len(bids),
        ask_counts=[1] * len(asks),
        flags=0,
        sequence=sequence,
        ts_event=ts,
        ts_init=ts,
    )


def test_a_resting_limit_crossed_by_a_collapsing_book_fills_as_maker(
    tape: SyntheticBinaryTape,
) -> None:
    """A LIMIT that was never post-only can still fill as MAKER.

    The fee model then prices it at +theta where the venue documents a
    -0.0125 REBATE, and emits `UserWarning`. This test pins that the warning
    is what a strategy author gets -- not an exception, and not silence.
    """
    instrument = tape.instrument
    base = instrument.activation_ns + _STEP_NS
    flat_bids = (("0.40", 50), ("0.39", 40))
    flat_asks = (("0.42", 50), ("0.43", 40))
    # Snapshot 2 collapses the ask side THROUGH the resting bid at 0.39.
    collapsed_asks = (("0.30", 50), ("0.31", 40))
    market_data = [
        _depth(tape, bids=flat_bids, asks=flat_asks, sequence=0, ts=base),
        _depth(tape, bids=flat_bids, asks=flat_asks, sequence=1, ts=base + _STEP_NS),
        _depth(
            tape,
            bids=(("0.28", 50), ("0.27", 40)),
            asks=collapsed_asks,
            sequence=2,
            ts=base + 6 * _STEP_NS,
        ),
        _depth(
            tape,
            bids=(("0.28", 50), ("0.27", 40)),
            asks=collapsed_asks,
            sequence=3,
            ts=base + 7 * _STEP_NS,
        ),
        tape.instrument_close,
    ]
    strategy = _strategy(tape, sweep_after_ns=20 * _STEP_NS)
    with pytest.warns(UserWarning, match="wrong in SIGN"):
        engine = run_backtest(_config(tape, market_data), strategies=(strategy,))
    try:
        assert strategy.maker_fills >= 1
    finally:
        engine.dispose()


def test_the_engine_expiration_latch_cancels_orders_left_open(
    tape: SyntheticBinaryTape,
) -> None:
    """A never-swept resting order is killed by the settlement latch, silently.

    `sweep_after_ns` is pushed past the end of the tape, so the strategy
    itself never cancels. `engine.pyx:5936-5947` cancels every open order when
    the `InstrumentClose` lands.
    """
    strategy = _strategy(tape, sweep_after_ns=100 * _STEP_NS)
    engine = run_backtest(_config(tape), strategies=(strategy,))
    try:
        assert strategy.cancels_requested == 0
        leftovers = [
            order for order in engine.cache.orders() if order.status == OrderStatus.CANCELED
        ]

        assert len(leftovers) == 2
    finally:
        engine.dispose()
