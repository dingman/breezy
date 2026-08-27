"""STOP GATE: "the bot is ready to accept a strategy for backtesting."

This module is the evidence for that gate. It runs a REAL
``BacktestEngine`` -- the venue configured exactly as
``docs/specs/BACKTEST_VENUE_CONFIG.md`` specifies -- over a fabricated tape
(``tests/support/synthetic_binary_tape.py``), with a deliberately trivial
reference strategy (``breezy.strategy.harness_probe.BreezyHarnessProbe``), and
asserts the six facts that make a backtest result *readable*. Each one closes a
failure mode whose symptom is a clean-looking run rather than an error.

The six, and what each kills
---------------------------

1. **Quotes reached the strategy.** The venue data path is alive at all.
2. **Weather reached the strategy.** The highest-value assertion here.
   ``DataEngine._handle_data`` LOGS AND DROPS an unrecognised record
   (``data/engine.pyx``), and ``Actor.subscribe_data(instrument_id=...)``
   builds a topic that ``DataType(NwsClimateDay).topic`` never matches. Both
   failures deliver ZERO weather records with no exception and no failing
   assertion anywhere else in this file -- the backtest simply becomes a
   weather bot that has never seen weather.
3. **Exactly one strategy fill, TAKER.** The order round-trip works, and the
   maker path -- which ``PolymarketUSFeeModel`` prices with an INVERTED SIGN
   and therefore refuses to be evaluated on -- was not taken.
4. **Exactly one non-zero commission, and it is the venue formula.** Proves
   ``PolymarketUSFeeModel`` ran rather than the ``MakerTakerFeeModel`` default
   that ``add_venue`` installs when ``fee_model`` is omitted
   (``backtest/engine.pyx:643-644``). The settlement fill's commission being
   exactly zero is what distinguishes the two: ``theta*C*p*(1-p)`` is zero at
   ``p=1``, while a flat ``taker_fee`` notional rate is not.
5. **The position settled at the SETTLEMENT price, not at the book.** §0 of the
   spec: ``InstrumentClose.close_price`` is never read; an instrument missing
   from ``settlement_prices`` falls through to ``fill_market_order`` and closes
   at the prevailing bid. The realised PnL is asserted against the settlement
   arithmetic to the cent, so that fall-through cannot pass.
6. **Two runs produce an identical ordered decision log.** No wall-clock, no
   random ids.

Nothing here opens a socket: the fills are produced internally by
``SimulatedExchange``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from nautilus_trader.model.enums import LiquiditySide, OrderSide
from nautilus_trader.model.events import OrderFilled
from nautilus_trader.model.objects import Money

from breezy.runtime.backtest_feed import as_backtest_data
from breezy.runtime.backtest_harness import BreezyBacktestConfig, run_backtest
from breezy.strategy.harness_probe import BreezyHarnessProbe, BreezyHarnessProbeConfig
from tests.support.synthetic_binary_tape import SyntheticBinaryTape, synthetic_binary_tape
from tests.unit.test_persistence_catalog import make_climate_day

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nautilus_trader.backtest.engine import BacktestEngine

pytestmark = pytest.mark.contract

#: The probe's clip, in contracts. Small enough to fill wholly at the best ask.
CLIP: int = 10

#: Starting cash. Not a venue fact -- an operator budget, per spec §1.
STARTING_BALANCE_USD: int = 1_000


def _probe(tape: SyntheticBinaryTape) -> BreezyHarnessProbe:
    return BreezyHarnessProbe(
        BreezyHarnessProbeConfig(
            instrument_id=tape.instrument.id,
            trade_quantity=Decimal(CLIP),
        ),
    )


def _two_cities(tape: SyntheticBinaryTape) -> list[object]:
    """Chicago's climate day, then New York's -- foreign record FIRST."""
    return as_backtest_data(
        [
            make_climate_day(
                station="MDW",
                tmax_f=95,
                is_final=True,
                retrieved_at_ns=tape.weather_ts_ns - 1,
            ),
            make_climate_day(
                station="NYC",
                tmax_f=72,
                is_final=True,
                retrieved_at_ns=tape.weather_ts_ns,
            ),
        ],
    )


def _config(
    tape: SyntheticBinaryTape,
    *,
    settle_at: float | None = None,
    weather: object = None,
) -> BreezyBacktestConfig:
    price = tape.settlement_price if settle_at is None else settle_at
    return BreezyBacktestConfig(
        instruments=(tape.instrument,),
        market_data=tape.all_data(),
        weather_data=(
            as_backtest_data([make_climate_day(retrieved_at_ns=tape.weather_ts_ns)])
            if weather is None
            else weather  # type: ignore[arg-type]
        ),
        settlement_prices={tape.instrument.id: price},
        starting_balances=(Money(STARTING_BALANCE_USD, tape.instrument.quote_currency),),
    )


def _run(tape: SyntheticBinaryTape) -> tuple[BacktestEngine, BreezyHarnessProbe]:
    probe = _probe(tape)
    engine = run_backtest(_config(tape), strategies=(probe,))
    return engine, probe


@pytest.fixture(scope="module")
def tape() -> SyntheticBinaryTape:
    return synthetic_binary_tape(size_precision=0, settlement_price=1.0)


@pytest.fixture(scope="module")
def run(tape: SyntheticBinaryTape) -> BreezyHarnessProbe:
    """One shared run; every assertion below reads the SAME probe."""
    engine, probe = _run(tape)
    try:
        return probe
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def fills(tape: SyntheticBinaryTape) -> list[OrderFilled]:
    engine, _probe = _run(tape)
    try:
        # `Cache` exposes no flat event log, so the fills are gathered from
        # the orders themselves -- including the engine's own settlement leg,
        # which `Cache.orders()` carries because it was added to the cache.
        return [
            event
            for order in engine.cache.orders()
            for event in order.events
            if isinstance(event, OrderFilled)
        ]
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# 1-2 -- the two data paths reached the strategy
# ---------------------------------------------------------------------------


def test_the_venue_quote_path_reached_the_strategy(run: BreezyHarnessProbe) -> None:
    assert run.quotes > 0


def test_the_venue_depth_path_reached_the_strategy(run: BreezyHarnessProbe) -> None:
    # Under L2_MBP the depth stream -- not the quote stream -- is what drives
    # execution (`engine.pyx:4551`), so its arrival is asserted separately.
    assert run.depths > 0


def test_the_weather_path_reached_the_strategy(run: BreezyHarnessProbe) -> None:
    """The single most important assertion in this file.

    A silent drop (unwrapped record), a mismatched `client_id`, or an
    instrument-scoped subscription each yield exactly zero here while every
    other test in this module still passes.
    """
    assert run.weather > 0


def test_the_terminal_close_reached_the_strategy(run: BreezyHarnessProbe) -> None:
    assert run.closes == 1


# ---------------------------------------------------------------------------
# 3 -- the order round-trip, taker-only
# ---------------------------------------------------------------------------


def test_the_probe_submitted_exactly_one_order(run: BreezyHarnessProbe) -> None:
    assert run.orders_submitted == 1


def test_exactly_one_fill_belongs_to_an_order_the_probe_submitted(
    run: BreezyHarnessProbe,
) -> None:
    """The probe's own clip filled once.

    Note the deliberate distinction from :attr:`BreezyHarnessProbe.fills`,
    which is 2: the engine's own settlement close is a MarketOrder tagged
    ``EXPIRATION_<venue>_CLOSE`` (`engine.pyx:5947-5958`) issued against the
    probe's position, so `on_order_filled` legitimately fires for it too.
    Asserting a bare `fills == 1` would fail against a CORRECT implementation.
    """
    assert run.own_fills == 1


def test_the_engine_settlement_leg_also_filled_against_the_probes_position(
    run: BreezyHarnessProbe,
) -> None:
    assert run.fills == 2


def test_the_probe_saw_the_order_lifecycle_events(run: BreezyHarnessProbe) -> None:
    # `on_event` is the catch-all; a zero here would mean the strategy was
    # never wired to the message bus at all, which every other assertion in
    # this file would still survive if the probe had been driven directly.
    assert run.events > 0


def test_no_fill_was_a_maker_fill(run: BreezyHarnessProbe) -> None:
    # `PolymarketUSFeeModel` prices maker fills at the taker coefficient, which
    # is wrong in SIGN. Any maker fill makes the whole result unevaluable.
    assert run.maker_fills == 0


def test_every_fill_in_the_run_was_taken_not_made(fills: list[OrderFilled]) -> None:
    """The event-level counterpart to the probe's own maker counter.

    Both legs -- the probe's MARKET BUY and the engine's settlement close --
    must be TAKER. `PolymarketUSFeeModel` prices a maker fill at +theta where
    the venue documents a rebate, so a maker fill anywhere makes the whole
    commission column wrong in sign.
    """
    assert {f.liquidity_side for f in fills} == {LiquiditySide.TAKER}


def test_the_probe_bought_rather_than_shorted(run: BreezyHarnessProbe) -> None:
    # Spec §2/§7(4): a naked short on a CASH account passes every RiskEngine
    # check and RAISES free cash. The probe must never depend on that path.
    assert run.own_fill_sides == (OrderSide.BUY,)


# ---------------------------------------------------------------------------
# 4 -- the fee model that ran is Breezy's, not the engine default
# ---------------------------------------------------------------------------


def test_exactly_one_fill_carried_a_non_zero_commission(fills: list[OrderFilled]) -> None:
    non_zero = [f for f in fills if f.commission.as_decimal() != 0]

    assert len(non_zero) == 1


def test_the_entry_commission_is_the_venue_formula_not_a_flat_notional_rate(
    fills: list[OrderFilled],
    tape: SyntheticBinaryTape,
) -> None:
    """``theta * C * p * (1 - p)``, banker's-rounded to the cent.

    The `MakerTakerFeeModel` default `add_venue` installs would instead charge
    `theta * notional` = 0.06 * 10 * 0.42 = $0.25 here. The two differ, so
    this assertion fails RED if `fee_model=` is dropped from `add_venue`.
    """
    entry = next(f for f in fills if f.order_side == OrderSide.BUY)
    theta = Decimal(str(tape.instrument.taker_fee))
    price = tape.best_ask.as_decimal()
    expected = (theta * Decimal(CLIP) * price * (Decimal(1) - price)).quantize(Decimal("0.01"))

    assert entry.commission.as_decimal() == expected


def test_the_settlement_fill_is_free_because_the_formula_vanishes_at_the_endpoint(
    fills: list[OrderFilled],
) -> None:
    """``theta * C * p * (1-p)`` is exactly zero at ``p = 1``.

    A flat notional model would charge 0.06 * 10 * 1.00 = $0.60 here, so this
    is the assertion that most cheaply distinguishes the two fee models.
    """
    settlement = [f for f in fills if f.last_px.as_decimal() == Decimal(1)]

    assert len(settlement) == 1
    assert settlement[0].commission.as_decimal() == 0


# ---------------------------------------------------------------------------
# 5 -- the position settled at 0 or 1, NOT at the prevailing book
# ---------------------------------------------------------------------------


def test_the_position_closed_at_the_settlement_price_not_at_the_book(
    tape: SyntheticBinaryTape,
) -> None:
    engine, _probe = _run(tape)
    try:
        position = engine.cache.positions()[0]

        assert position.is_closed
        assert position.avg_px_close == tape.settlement_price
        # The book's best bid at close time. Passing this WOULD be the
        # `fill_market_order` fall-through -- see spec §0.
        assert position.avg_px_close != float(tape.instrument_close.close_price) - 0.60
    finally:
        engine.dispose()


def test_the_realised_pnl_equals_the_settlement_arithmetic(
    tape: SyntheticBinaryTape,
    fills: list[OrderFilled],
) -> None:
    """PnL to the cent: ``C * (settlement - entry) - commissions``.

    This is the assertion that proves §0 was handled. Under the
    `fill_market_order` fall-through the close price is the best BID (0.40),
    not 1.00, and this number is wrong by ``C * 0.60``.
    """
    engine, _probe = _run(tape)
    try:
        position = engine.cache.positions()[0]
        settlement = Decimal(str(tape.settlement_price))
        entry = tape.best_ask.as_decimal()
        commissions = sum((f.commission.as_decimal() for f in fills), Decimal(0))
        expected = Decimal(CLIP) * (settlement - entry) - commissions

        assert position.realized_pnl is not None
        assert position.realized_pnl.as_decimal() == expected
    finally:
        engine.dispose()


def test_a_contract_that_settles_at_zero_loses_the_whole_stake(
    tape: SyntheticBinaryTape,
) -> None:
    """The other endpoint, so the arithmetic is not fitted to a single case."""
    losing = synthetic_binary_tape(size_precision=0, settlement_price=0.0)
    probe = _probe(losing)
    engine = run_backtest(_config(losing), strategies=(probe,))
    try:
        position = engine.cache.positions()[0]

        assert position.avg_px_close == 0.0
        assert position.realized_pnl is not None
        assert position.realized_pnl.as_decimal() < Decimal(-CLIP) * losing.best_ask.as_decimal()
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# The cost of client-scoped weather: EVERY city reaches EVERY strategy
# ---------------------------------------------------------------------------


def test_a_foreign_citys_weather_is_delivered_to_the_probe(
    tape: SyntheticBinaryTape,
) -> None:
    """Verified platform behaviour, pinned so it cannot be mistaken for a bug.

    Weather is scoped by `client_id` (it must be -- an instrument-scoped
    subscription matches no topic and receives zero records), so a run covering
    two cities hands BOTH cities' `NwsClimateDay` records to EVERY strategy.
    Nothing on the record marks it foreign and nothing correlates a station
    with an instrument's city.
    """
    probe = BreezyHarnessProbe(
        BreezyHarnessProbeConfig(
            instrument_id=tape.instrument.id,
            trade_quantity=Decimal(CLIP),
            station="NYC",
        ),
    )
    engine = run_backtest(
        _config(tape, weather=_two_cities(tape)),
        strategies=(probe,),
    )
    try:
        assert probe.weather == 2
        assert probe.weather_stations == ("MDW", "NYC")
    finally:
        engine.dispose()


def test_the_probe_trades_only_on_its_OWN_stations_record(
    tape: SyntheticBinaryTape,
) -> None:
    """The filter the probe exists to demonstrate.

    Chicago's record arrives FIRST and carries a wildly different high. A
    strategy that acted on the first record it received -- the obvious shape,
    and the one an author writes when nothing tells them otherwise -- would
    size this New York position off Chicago's weather and log nothing.
    """
    probe = BreezyHarnessProbe(
        BreezyHarnessProbeConfig(
            instrument_id=tape.instrument.id,
            trade_quantity=Decimal(CLIP),
            station="NYC",
        ),
    )
    engine = run_backtest(
        _config(tape, weather=_two_cities(tape)),
        strategies=(probe,),
    )
    try:
        assert probe.orders_submitted == 1
        assert probe.traded_station == "NYC"
        assert "foreign|MDW" in "".join(probe.decisions)
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# 6 -- determinism
# ---------------------------------------------------------------------------


def test_two_runs_produce_an_identical_ordered_decision_log(
    tape: SyntheticBinaryTape,
) -> None:
    first_engine, first = _run(tape)
    second_engine, second = _run(tape)
    try:
        assert first.decisions == second.decisions
        assert len(first.decisions) > 0
    finally:
        first_engine.dispose()
        second_engine.dispose()


# ---------------------------------------------------------------------------
# Precision: the tape works for BOTH captured size precisions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("size_precision", [0, 2])
def test_the_harness_runs_against_either_captured_size_precision(size_precision: int) -> None:
    """`engine.pyx:4444-4471` raises `RuntimeError` on a precision mismatch."""
    variant = synthetic_binary_tape(size_precision=size_precision, settlement_price=1.0)
    probe = _probe(variant)
    engine = run_backtest(_config(variant), strategies=(probe,))
    try:
        assert probe.own_fills == 1
        assert probe.weather > 0
    finally:
        engine.dispose()
