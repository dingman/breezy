"""Does the backtest harness work with MORE THAN ONE instrument?

``tests/contract/test_backtest_harness_stop_gate.py`` proves the harness for a
single instrument. Everything a real weather strategy does is
multi-instrument: a ladder of mutually exclusive temperature buckets on one
city, of which exactly one settles at 1. This module runs
``breezy.strategy.strike_ladder.BreezyStrikeLadder`` over a three-strike
fabricated tape (``tests/support/synthetic_multi_strike_tape.py``) and asserts
the facts that a single-instrument proof cannot reach.

The seams under test, each of which fails QUIETLY
-------------------------------------------------

1. **Every instrument's data reached the strategy.** A run where one leg's
   depth stream never arrives still fills the other legs, still settles, and
   still produces a plausible equity curve. The per-instrument counters exist
   so that leg cannot hide.
2. **Every instrument the ladder chose actually traded.** An order that is
   never submitted, or is submitted and silently rejected by the RiskEngine
   for want of free cash, leaves no exception behind.
3. **Weather reached a strategy holding N instruments.** Weather is scoped by
   ``client_id``; the natural mistake at N instruments is N instrument-scoped
   subscriptions, which match no topic and deliver zero records with no error.
4. **Both settlement outcomes are correct in the SAME run.** One leg settles
   at 1 and two at 0. The engine's settlement price comes from a MAPPING
   (``settlement_prices``); a harness that took a scalar, or applied the first
   entry to every instrument, would pass every single-instrument test.
5. **Every position closed.** ``BinaryOption`` is not in
   ``ENGINE_EXPIRING_INSTRUMENT_CLASSES``, so each instrument's own
   ``InstrumentClose`` is its SOLE settlement trigger. A leg whose close is
   missing or mis-ordered stays open and is reported as unrealised.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from nautilus_trader.model.data import InstrumentClose
from nautilus_trader.model.enums import (
    InstrumentCloseType,
    LiquiditySide,
    OrderSide,
)
from nautilus_trader.model.events import OrderFilled
from nautilus_trader.model.objects import Money, Price

from breezy.domain.weather_bucket_facts import read_weather_bucket_facts
from breezy.runtime.backtest_feed import as_backtest_data
from breezy.runtime.backtest_harness import (
    BreezyBacktestConfig,
    SettlementInvariant,
    SettlementInvariantError,
    run_backtest,
)
from breezy.strategy.strike_ladder import BreezyStrikeLadder, BreezyStrikeLadderConfig
from tests.support.synthetic_multi_strike_tape import SyntheticStrikeTape, synthetic_strike_tape
from tests.unit.test_persistence_catalog import make_climate_day

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

    from nautilus_trader.backtest.engine import BacktestEngine

    from breezy.domain.nws_climate_day import NwsClimateDay

pytestmark = pytest.mark.contract

#: Three captured strikes on the SAME city and day. Real slugs; every price
#: below is fabricated.
WINNER = "tc-temp-nychigh-2026-04-23-gte72lt73f"
NEAR_MISS = "tc-temp-nychigh-2026-04-23-gte70lt71f"
FAR_SIDE = "tc-temp-nychigh-2026-04-23-gte74f"

#: The observation the ladder trades on. Sits inside WINNER's bucket and two
#: degrees from both hedges, so with ``tolerance_f=2`` all three legs trade.
OBSERVED_TMAX_F = 72

FULL_CLIP = 10
HEDGE_CLIP = 4
STARTING_BALANCE_USD = 1_000


_STANDARD_UTC_OFFSET_HOURS = {
    "NYC": 5,
    "MIA": 5,
    "MDW": 6,
    "LAX": 8,
    "SFO": 8,
}


def _final_ts_event_ns(*, station: str, climate_day: dt.date) -> int:
    day_end_utc = dt.datetime.combine(
        climate_day + dt.timedelta(days=1),
        dt.time(hour=_STANDARD_UTC_OFFSET_HOURS[station], tzinfo=dt.UTC),
    )
    return int(day_end_utc.timestamp() * 1_000_000_000)


def _climate_day_for_tape(tape: SyntheticStrikeTape) -> dt.date:
    climate_days = {
        read_weather_bucket_facts(leg.instrument.info).climate_day for leg in tape.legs
    }
    if len(climate_days) != 1:
        raise AssertionError(f"synthetic tape spans multiple climate days: {climate_days}")
    return next(iter(climate_days))


def _final_ts_event_for_tape(tape: SyntheticStrikeTape) -> int:
    expirations = {leg.instrument.expiration_ns for leg in tape.legs}
    if len(expirations) != 1:
        raise AssertionError(f"synthetic tape spans multiple expirations: {expirations}")
    return int(next(iter(expirations)))


def _make_weather_record(
    tape: SyntheticStrikeTape,
    *,
    station: str = "NYC",
    climate_day: dt.date | None = None,
    tmax_f: int = OBSERVED_TMAX_F,
    ts_event: int | None = None,
    retrieved_at_ns: int | None = None,
) -> NwsClimateDay:
    day = climate_day if climate_day is not None else _climate_day_for_tape(tape)
    final_ts_event = ts_event if ts_event is not None else _final_ts_event_ns(
        station=station,
        climate_day=day,
    )
    return make_climate_day(
        station=station,
        climate_day=day,
        tmax_f=tmax_f,
        is_final=True,
        ts_event=final_ts_event,
        retrieved_at_ns=retrieved_at_ns if retrieved_at_ns is not None else tape.weather_ts_ns,
    )


def build_tape() -> SyntheticStrikeTape:
    return synthetic_strike_tape(
        slugs=(WINNER, NEAR_MISS, FAR_SIDE),
        best_asks=("0.42", "0.25", "0.18"),
        best_bids=("0.40", "0.23", "0.16"),
        settlement_prices=(1.0, 0.0, 0.0),
    )


def _ladder(tape: SyntheticStrikeTape, *, tolerance_f: int = 2) -> BreezyStrikeLadder:
    # Built fresh rather than derived: `StrategyConfig` is a msgspec `Struct`,
    # not a dataclass, so `dataclasses.replace` raises on it.
    return BreezyStrikeLadder(
        BreezyStrikeLadderConfig(
            instrument_ids=tuple(leg.instrument_id for leg in tape.legs),
            trade_quantity=Decimal(FULL_CLIP),
            hedge_quantity=Decimal(HEDGE_CLIP),
            tolerance_f=tolerance_f,
        ),
    )


def _config(
    tape: SyntheticStrikeTape,
    *,
    weather_records: Sequence[NwsClimateDay] | None = None,
) -> BreezyBacktestConfig:
    return BreezyBacktestConfig(
        instruments=tape.instruments(),
        market_data=tape.all_data(),
        weather_data=as_backtest_data(
            list(weather_records) if weather_records is not None else [_make_weather_record(tape)]
        ),
        settlement_prices=tape.settlement_prices(),
        starting_balances=(Money(STARTING_BALANCE_USD, tape.legs[0].instrument.quote_currency),),
    )


def test_fixture_weather_record_matches_the_market_climate_day(tape: SyntheticStrikeTape) -> None:
    """The synthetic final must be a possible final for the traded market day."""
    config = _config(tape)
    weather = config.weather_data[0].data
    climate_days = {
        read_weather_bucket_facts(leg.instrument.info).climate_day for leg in tape.legs
    }

    assert climate_days == {weather.climate_day}
    assert weather.ts_event == min(leg.instrument.expiration_ns for leg in tape.legs)
    assert weather.retrieved_at_ns >= weather.ts_event


def test_contract_does_not_hand_type_bucket_bounds() -> None:
    source = Path(__file__).read_text(encoding="utf-8")

    assert "_" + "BUCKETS" not in source
    assert "OPEN" + "_BOUND_F" not in source
    assert "(" + "72, 73)" not in source


def test_strategy_does_not_hand_type_bucket_bounds() -> None:
    source = Path("src/breezy/strategy/strike_ladder.py").read_text(encoding="utf-8")

    assert "_" + "BUCKETS" not in source
    assert "OPEN" + "_BOUND_F" not in source
    assert "(" + "72, 73)" not in source
    assert "buckets" + ":" not in source


def _run(tape: SyntheticStrikeTape) -> tuple[BacktestEngine, BreezyStrikeLadder]:
    ladder = _ladder(tape)
    engine = run_backtest(_config(tape), strategies=(ladder,))
    return engine, ladder


@pytest.fixture(scope="module")
def tape() -> SyntheticStrikeTape:
    return build_tape()


@pytest.fixture(scope="module")
def run(tape: SyntheticStrikeTape) -> BreezyStrikeLadder:
    engine, ladder = _run(tape)
    try:
        return ladder
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def engine(tape: SyntheticStrikeTape) -> BacktestEngine:
    engine, _ladder = _run(tape)
    yield engine
    engine.dispose()


# ---------------------------------------------------------------------------
# 1 -- every instrument's data reached the strategy
# ---------------------------------------------------------------------------


def test_the_tape_carries_three_distinct_instruments(tape: SyntheticStrikeTape) -> None:
    assert len({leg.instrument_id for leg in tape.legs}) == 3


def test_depth_arrived_for_every_instrument(
    run: BreezyStrikeLadder, tape: SyntheticStrikeTape
) -> None:
    """A leg with zero depth still lets the run finish and settle."""
    assert {leg.instrument_id: run.depths[leg.instrument_id] for leg in tape.legs} == {
        leg.instrument_id: 3 for leg in tape.legs
    }


def test_quotes_arrived_for_every_instrument(
    run: BreezyStrikeLadder, tape: SyntheticStrikeTape
) -> None:
    assert all(run.quotes[leg.instrument_id] == 3 for leg in tape.legs)


def test_each_instrument_received_exactly_its_own_close(
    run: BreezyStrikeLadder, tape: SyntheticStrikeTape
) -> None:
    assert {leg.instrument_id: run.closes[leg.instrument_id] for leg in tape.legs} == {
        leg.instrument_id: 1 for leg in tape.legs
    }


# ---------------------------------------------------------------------------
# 2-3 -- weather drove the decision, and every chosen leg traded
# ---------------------------------------------------------------------------


def test_weather_reached_a_strategy_holding_three_instruments(run: BreezyStrikeLadder) -> None:
    """The highest-value assertion here -- see the module docstring, item 3."""
    assert run.weather == 1
    assert run.weather_stations == ("NYC",)


def test_the_decision_was_made_from_the_observed_temperature(run: BreezyStrikeLadder) -> None:
    assert run.traded_tmax_f == OBSERVED_TMAX_F


def test_all_three_legs_submitted_an_order(
    run: BreezyStrikeLadder, tape: SyntheticStrikeTape
) -> None:
    assert sorted(str(i) for i in run.submitted) == sorted(
        str(leg.instrument_id) for leg in tape.legs
    )


def test_the_containing_bucket_took_the_full_clip_and_the_hedges_took_less(
    run: BreezyStrikeLadder, tape: SyntheticStrikeTape
) -> None:
    sizes = {str(k): int(v.as_double()) for k, v in run.submitted.items()}

    assert sizes[str(tape.leg(WINNER).instrument_id)] == FULL_CLIP
    assert sizes[str(tape.leg(NEAR_MISS).instrument_id)] == HEDGE_CLIP
    assert sizes[str(tape.leg(FAR_SIDE).instrument_id)] == HEDGE_CLIP


def test_every_leg_actually_filled(run: BreezyStrikeLadder, tape: SyntheticStrikeTape) -> None:
    """Submitted is not filled: a denied order leaves no exception behind."""
    assert {leg.instrument_id: run.own_fills[leg.instrument_id] for leg in tape.legs} == {
        leg.instrument_id: 1 for leg in tape.legs
    }


def test_no_fill_anywhere_in_the_run_was_a_maker_fill(run: BreezyStrikeLadder) -> None:
    assert run.maker_fills == 0


# ---------------------------------------------------------------------------
# 4-5 -- settlement, both outcomes, in the same run
# ---------------------------------------------------------------------------


def test_the_run_produced_one_position_per_instrument(engine: BacktestEngine) -> None:
    positions = engine.cache.positions()

    assert len(positions) == 3
    assert len({p.instrument_id for p in positions}) == 3


def test_every_position_closed(engine: BacktestEngine) -> None:
    """An instrument whose close never fired stays OPEN and unrealised."""
    assert [p.is_closed for p in engine.cache.positions()] == [True, True, True]


def test_each_position_closed_at_ITS_OWN_settlement_price_not_a_shared_one(
    engine: BacktestEngine, tape: SyntheticStrikeTape
) -> None:
    """The assertion a single-instrument harness cannot make.

    One leg settles at 1.0 and two at 0.0 in the SAME run. A harness applying
    a single scalar settlement price, or the first mapping entry, to every
    instrument would pass every test in the single-instrument stop gate.
    """
    closed = {p.instrument_id: p.avg_px_close for p in engine.cache.positions()}

    assert closed == {leg.instrument_id: leg.settlement_price for leg in tape.legs}


def test_no_position_closed_at_the_prevailing_book(
    engine: BacktestEngine, tape: SyntheticStrikeTape
) -> None:
    """Spec §0: a missing `settlement_prices` entry closes at the best BID."""
    closed = {p.instrument_id: p.avg_px_close for p in engine.cache.positions()}

    for leg in tape.legs:
        assert closed[leg.instrument_id] != float(leg.best_bid)


def test_the_winner_and_the_losers_have_opposite_signed_realised_pnl(
    engine: BacktestEngine, tape: SyntheticStrikeTape
) -> None:
    realised = {
        p.instrument_id: p.realized_pnl.as_decimal()
        for p in engine.cache.positions()
        if p.realized_pnl is not None
    }

    assert len(realised) == 3
    assert realised[tape.leg(WINNER).instrument_id] > 0
    assert realised[tape.leg(NEAR_MISS).instrument_id] < 0
    assert realised[tape.leg(FAR_SIDE).instrument_id] < 0


def test_realised_pnl_is_the_settlement_arithmetic_on_every_leg(
    engine: BacktestEngine, tape: SyntheticStrikeTape
) -> None:
    """``C * (settlement - entry) - commissions``, per instrument, to the cent."""
    commissions: dict[object, Decimal] = {}
    for order in engine.cache.orders():
        for event in order.events:
            if isinstance(event, OrderFilled):
                commissions[event.instrument_id] = (
                    commissions.get(event.instrument_id, Decimal(0)) + event.commission.as_decimal()
                )

    realised = {p.instrument_id: p for p in engine.cache.positions()}
    for leg in tape.legs:
        position = realised[leg.instrument_id]
        clip = Decimal(FULL_CLIP if str(leg.instrument.symbol) == WINNER else HEDGE_CLIP)
        expected = (
            clip * (Decimal(str(leg.settlement_price)) - leg.best_ask.as_decimal())
            - commissions[leg.instrument_id]
        )

        assert position.realized_pnl is not None
        assert position.realized_pnl.as_decimal() == expected, leg.instrument_id


def test_only_the_winning_leg_pays_no_settlement_commission(engine: BacktestEngine) -> None:
    """``theta*C*p*(1-p)`` is zero at BOTH endpoints, so every settlement leg
    is free -- on the losers too. This pins that the venue fee model ran for
    all three instruments rather than only the first."""
    settlement_fills = [
        event
        for order in engine.cache.orders()
        for event in order.events
        if isinstance(event, OrderFilled) and event.order_side == OrderSide.SELL
    ]

    assert len(settlement_fills) == 3
    assert {f.commission.as_decimal() for f in settlement_fills} == {Decimal(0)}
    assert {f.liquidity_side for f in settlement_fills} == {LiquiditySide.TAKER}


# ---------------------------------------------------------------------------
# determinism
# ---------------------------------------------------------------------------


def test_two_multi_instrument_runs_produce_an_identical_decision_log(
    tape: SyntheticStrikeTape,
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
# staggered settlement -- legs do NOT all resolve at the same instant
# ---------------------------------------------------------------------------


def test_one_leg_may_settle_while_the_others_are_still_trading(
    tape: SyntheticStrikeTape,
) -> None:
    """Two cities on one run do not share a resolution time.

    ``_expiration_processed`` is a one-shot latch that also CANCELS ALL OPEN
    ORDERS (``backtest/engine.pyx:5936-5947``), and the harness's ordering
    invariant is deliberately per-instrument rather than global. This pins
    that a leg closing mid-run neither kills the other legs' data nor
    disturbs their settlement.
    """
    winner = tape.leg(WINNER)
    early_ts = winner.last_market_data_ts_ns + 1
    market_data = [
        record
        for record in tape.all_data()
        if not (type(record) is InstrumentClose and record.instrument_id == winner.instrument_id)
    ]
    market_data.append(
        InstrumentClose(
            winner.instrument_id,
            Price(1.0, winner.instrument.price_precision),
            InstrumentCloseType.CONTRACT_EXPIRED,
            early_ts,
            early_ts,
        ),
    )
    still_to_come = [
        record
        for record in market_data
        if record.ts_init > early_ts and record.instrument_id != winner.instrument_id
    ]
    assert still_to_come, "the early close must actually precede other legs' data"

    ladder = _ladder(tape)
    engine = run_backtest(
        replace(_config(tape), market_data=market_data),
        strategies=(ladder,),
    )
    try:
        closed = {p.instrument_id: p.avg_px_close for p in engine.cache.positions()}

        assert all(p.is_closed for p in engine.cache.positions())
        assert closed == {leg.instrument_id: leg.settlement_price for leg in tape.legs}
    finally:
        engine.dispose()


def test_a_never_settled_leg_is_NOT_distinguishable_by_its_close_price_alone(
    tape: SyntheticStrikeTape,
) -> None:
    """A documented trap, pinned so it cannot regress into a false comfort.

    Drop one losing leg's ``InstrumentClose`` and its position never settles
    -- but ``avg_px_close`` is ``0.0`` on an unsettled position too, which is
    the SAME value a genuine settle-at-zero produces. On a weather ladder most
    legs settle at zero, so ``avg_px_close`` is not a settlement check.
    ``is_closed`` and ``realized_pnl`` are.
    """
    missing = tape.leg(NEAR_MISS)
    market_data = [
        record
        for record in tape.all_data()
        if not (type(record) is InstrumentClose and record.instrument_id == missing.instrument_id)
    ]
    ladder = _ladder(tape)
    # BOTH waivers are needed, and both NAME what they waive: the harness now
    # refuses this run twice over -- once before the engine exists (no
    # CONTRACT_EXPIRED close for an instrument that can trade) and once after
    # it finishes (a position left open). This test studies the resulting
    # state deliberately, which is the case the waivers exist for.
    engine = run_backtest(
        replace(
            _config(tape),
            market_data=market_data,
            instruments_without_close=frozenset({missing.instrument_id}),
        ),
        strategies=(ladder,),
        allow_open_positions=True,
    )
    try:
        position = next(
            p for p in engine.cache.positions() if p.instrument_id == missing.instrument_id
        )

        # The trap: identical to a real settle-at-zero.
        assert position.avg_px_close == missing.settlement_price
        # The two things that actually detect it.
        assert not position.is_closed
        assert position.realized_pnl is not None
        assert position.realized_pnl.as_decimal() > Decimal(-1)
    finally:
        engine.dispose()


def test_the_harness_REFUSES_that_run_by_default(tape: SyntheticStrikeTape) -> None:
    """The companion to the test above, and the reason it needs two waivers.

    The trap it documents is real and undetectable from `avg_px_close`. What
    changed is that an author no longer has to know about it: the same input
    now raises before the engine is even constructed.
    """
    missing = tape.leg(NEAR_MISS)
    market_data = [
        record
        for record in tape.all_data()
        if not (type(record) is InstrumentClose and record.instrument_id == missing.instrument_id)
    ]

    with pytest.raises(SettlementInvariantError) as excinfo:
        run_backtest(
            replace(_config(tape), market_data=market_data),
            strategies=(_ladder(tape),),
        )

    assert excinfo.value.invariant is SettlementInvariant.CLOSE
    assert str(missing.instrument_id) in str(excinfo.value)


# ---------------------------------------------------------------------------
# bucket semantics -- the venue's intervals are CLOSED at both ends
# ---------------------------------------------------------------------------


def test_the_upper_edge_of_a_bucket_is_INSIDE_it(tape: SyntheticStrikeTape) -> None:
    """``...-gte72lt73f`` is titled "72 to 73": 73 belongs to it.

    Read half-open, 73 falls in NO bucket of the captured NYC ladder --
    ``[72,73)`` excludes it and ``[74,inf)`` starts above it. The ladder then
    buys only hedges, loses, and reports nothing. This test is the guard.
    """
    ladder = _ladder(tape, tolerance_f=0)
    engine = run_backtest(
        replace(
            _config(tape),
            weather_data=as_backtest_data([_make_weather_record(tape, tmax_f=73)]),
        ),
        strategies=(ladder,),
        allow_idle_strategies=True,
    )
    try:
        assert list(ladder.submitted) == [tape.leg(WINNER).instrument_id]
    finally:
        engine.dispose()


def test_right_station_wrong_climate_day_does_not_drive_the_ladder(
    tape: SyntheticStrikeTape,
) -> None:
    wrong_day = _climate_day_for_tape(tape) - dt.timedelta(days=1)
    ladder = _ladder(tape)
    engine = run_backtest(
        replace(
            _config(
                tape,
                weather_records=[
                    _make_weather_record(
                        tape,
                        climate_day=wrong_day,
                        retrieved_at_ns=tape.weather_ts_ns,
                    )
                ],
            ),
        ),
        strategies=(ladder,),
        allow_idle_strategies=True,
    )
    try:
        assert ladder.weather == 1
        assert ladder.traded_tmax_f is None
        assert ladder.submitted == {}
    finally:
        engine.dispose()


def test_wrong_station_right_climate_day_does_not_drive_the_ladder(
    tape: SyntheticStrikeTape,
) -> None:
    ladder = _ladder(tape)
    engine = run_backtest(
        replace(
            _config(
                tape,
                weather_records=[
                    _make_weather_record(tape, station="MIA", retrieved_at_ns=tape.weather_ts_ns)
                ],
            ),
        ),
        strategies=(ladder,),
        allow_idle_strategies=True,
    )
    try:
        assert ladder.weather == 1
        assert ladder.weather_stations == ("MIA",)
        assert ladder.traded_tmax_f is None
        assert ladder.submitted == {}
    finally:
        engine.dispose()


def test_a_client_scoped_subscription_delivers_OTHER_cities_weather_too(
    tape: SyntheticStrikeTape,
) -> None:
    """The cost of the correct weather scoping, made explicit.

    Weather is scoped by ``client_id``, so a run covering two cities hands
    BOTH cities' ``NwsClimateDay`` records to BOTH ladders. Nothing in the
    platform filters them, and nothing correlates a record's station with an
    instrument's city -- the strategy must do it. Here a Chicago high of 95
    arrives FIRST; a ladder that traded the first record it saw would buy the
    top NYC strike on Chicago's weather and never say so.
    """
    ladder = _ladder(tape)
    engine = run_backtest(
        replace(
            _config(tape),
            weather_data=as_backtest_data(
                [
                    _make_weather_record(
                        tape,
                        station="MIA",
                        tmax_f=95,
                        retrieved_at_ns=tape.weather_ts_ns - 1,
                    ),
                    _make_weather_record(tape),
                ],
            ),
        ),
        strategies=(ladder,),
    )
    try:
        # Both records were delivered -- the subscription is not city-scoped.
        assert ladder.weather == 2
        assert ladder.weather_stations == ("MIA", "NYC")
        # But only NYC's drove the ladder.
        assert ladder.traded_tmax_f == OBSERVED_TMAX_F
        assert len(ladder.submitted) == 3
    finally:
        engine.dispose()
