"""H-1: which refusal wins when TWO are true at once.

The harness refuses a run for several distinct reasons, and every existing
test (``test_runtime_backtest_harness.py``, ``test_runtime_backtest_data_screen.py``,
``test_backtest_harness_prose_guard.py``, ``test_runtime_backtest_order_guard.py``,
``tests/integration/test_backtest_run_refusals.py``) triggers EXACTLY ONE
condition at a time. So which refusal is reported when two conditions are
simultaneously true was never observed, only implied by reading the source
top-to-bottom.

This module constructs configurations where two conditions are true at once
and pins WHICH ONE is actually raised, reading the answer off a live call --
not off the source.

Status: none of these is a defect. Every assertion below was ALREADY true of
the current implementation; these tests are new observations of existing,
correct-by-construction behaviour (single sequential functions, each check
run unconditionally in source order and returning/raising on the first
match). Where the ordering could plausibly have gone the other way with no
change in what the harness is FOR -- i.e. it is a fact about which line of
code runs first, not a deliberate business priority -- the test comment says
so explicitly: DESCRIPTIVE of current behaviour, not NORMATIVE. The one
exception is the CLOSE-before-everything-else placement, which the module's
own docstring already argues for directly (the vacuity fix); that one test
says so too.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import InstrumentClose
from nautilus_trader.model.enums import InstrumentCloseType, OrderSide, OrderType, TimeInForce
from nautilus_trader.model.events import OrderInitialized
from nautilus_trader.model.identifiers import (
    ClientOrderId,
    InstrumentId,
    StrategyId,
    Symbol,
    TraderId,
    Venue,
)
from nautilus_trader.model.objects import Money, Price, Quantity

from breezy.runtime.backtest_harness import (
    BreezyBacktestConfig,
    NotVenueMarketDataError,
    SettlementInvariant,
    SettlementInvariantError,
    assert_settlement_invariants,
    build_backtest_engine,
)
from breezy.runtime.backtest_order_guard import BacktestOrderGuard, PostOnlyRefusedError
from tests.support.synthetic_binary_tape import synthetic_binary_tape
from tests.unit.test_persistence_catalog import make_climate_day

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

#: An instrument id that is never added to `instruments` in any test below --
#: used only as a second KEY in `settlement_prices` so its ENDPOINT validity
#: can be exercised independently of whether it was ever closed.
_OTHER_INSTRUMENT = InstrumentId(Symbol("synthetic-precedence-other"), Venue("POLYMARKET_US"))


def _config(**overrides: object) -> BreezyBacktestConfig:
    tape = synthetic_binary_tape(size_precision=0, settlement_price=1.0)
    kwargs: dict[str, object] = {
        "instruments": (tape.instrument,),
        "market_data": tape.all_data(),
        "weather_data": (),
        "settlement_prices": {tape.instrument.id: tape.settlement_price},
        "starting_balances": (Money(1_000, USD),),
    }
    kwargs.update(overrides)
    return BreezyBacktestConfig(**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Total order WITHIN `assert_settlement_invariants`:
#   CLOSE > DUPLICATE_CLOSE > COVERAGE > ENDPOINT > ORDERING
#
# Read directly off `_assert_every_instrument_is_closed` (missing computed and
# raised before duplicated) and `assert_settlement_invariants` (coverage, then
# endpoint, then ordering, each an early-return `if ...: raise`).
# ---------------------------------------------------------------------------


def test_close_beats_duplicate_close() -> None:
    """An instrument missing its close entirely, and ANOTHER carrying two.

    `_assert_every_instrument_is_closed` computes and raises on `missing`
    strictly before it computes `duplicated` -- so even though the second
    instrument's double close is also a real violation, it is never reached.

    DESCRIPTIVE, not normative: the module docstring argues CLOSE must be
    checked first because the invariants used to be derived from
    `market_data` and were vacuously satisfied by a tape with no close at
    all -- that is a deliberate design fact, not an accident. Nothing in the
    code or the docs argues CLOSE must ALSO outrank DUPLICATE_CLOSE
    specifically (as opposed to some other order); this test pins the
    observed behaviour of the two checks living in the same function, in
    this order, and no more.
    """
    missing_tape = synthetic_binary_tape(size_precision=0, settlement_price=1.0)
    duplicated_tape = synthetic_binary_tape(size_precision=2, settlement_price=1.0)

    with pytest.raises(SettlementInvariantError) as excinfo:
        assert_settlement_invariants(
            instruments=(missing_tape.instrument, duplicated_tape.instrument),
            market_data=[
                *missing_tape.market_data,  # NO close at all for this instrument
                *duplicated_tape.market_data,
                duplicated_tape.instrument_close,
                duplicated_tape.instrument_close,  # the SAME close, twice
            ],
            settlement_prices={duplicated_tape.instrument.id: duplicated_tape.settlement_price},
        )

    assert excinfo.value.invariant is SettlementInvariant.CLOSE


def test_duplicate_close_beats_coverage() -> None:
    """One instrument closed twice; a DIFFERENT instrument closed once with no price.

    Both violations are live simultaneously. `_assert_every_instrument_is_closed`
    (which raises DUPLICATE_CLOSE) returns control to `assert_settlement_invariants`
    only if it does NOT raise -- so DUPLICATE_CLOSE, if triggered, is reported
    before the COVERAGE check ever runs, regardless of what else is wrong.

    DESCRIPTIVE, not normative: nothing states that a duplicated close is a
    "worse" problem than a missing settlement price -- only that the code
    checks the former first because it lives in the same helper as the CLOSE
    check, which must run first (see the module docstring).
    """
    duplicated_tape = synthetic_binary_tape(size_precision=0, settlement_price=1.0)
    uncovered_tape = synthetic_binary_tape(size_precision=2, settlement_price=1.0)

    with pytest.raises(SettlementInvariantError) as excinfo:
        assert_settlement_invariants(
            instruments=(duplicated_tape.instrument, uncovered_tape.instrument),
            market_data=[
                *duplicated_tape.market_data,
                duplicated_tape.instrument_close,
                duplicated_tape.instrument_close,
                *uncovered_tape.market_data,
                uncovered_tape.instrument_close,
            ],
            # `uncovered_tape.instrument.id` is closed but carries NO price at
            # all -- a COVERAGE violation that is never reached.
            settlement_prices={duplicated_tape.instrument.id: duplicated_tape.settlement_price},
        )

    assert excinfo.value.invariant is SettlementInvariant.DUPLICATE_CLOSE


def test_coverage_beats_endpoint() -> None:
    """An instrument closed with no price at all, plus an off-endpoint price
    for a DIFFERENT (never-closed, never-traded) id in the same dict.

    The COVERAGE check runs (and raises, if triggered) before the ENDPOINT
    check even starts iterating `settlement_prices.items()`.

    DESCRIPTIVE, not normative: coverage and endpoint are unrelated dict
    scans over the same mapping; nothing argues one must precede the other.
    """
    tape = synthetic_binary_tape(size_precision=0, settlement_price=1.0)

    with pytest.raises(SettlementInvariantError) as excinfo:
        assert_settlement_invariants(
            instruments=(tape.instrument,),
            market_data=tape.all_data(),
            # `tape.instrument.id` is entirely ABSENT (COVERAGE); `_OTHER_INSTRUMENT`
            # carries an off-endpoint price (ENDPOINT), reached only if coverage
            # did not already raise.
            settlement_prices={_OTHER_INSTRUMENT: 0.5},
        )

    assert excinfo.value.invariant is SettlementInvariant.COVERAGE


def test_endpoint_beats_ordering() -> None:
    """One instrument, one close: off-endpoint price AND stamped too early.

    The ENDPOINT loop over `settlement_prices.items()` runs, and can raise,
    strictly before the ORDERING comparison against `_last_market_data_ts`.

    DESCRIPTIVE, not normative: nothing ranks a void settlement price as more
    urgent than an early close -- both corrupt the same run. The code simply
    writes the endpoint check first.
    """
    tape = synthetic_binary_tape(size_precision=0)
    early_close = InstrumentClose(
        tape.instrument.id,
        Price(0.5, tape.instrument.price_precision),
        InstrumentCloseType.CONTRACT_EXPIRED,
        tape.market_data[0].ts_event,
        tape.market_data[0].ts_init,  # precedes the last market-data record: ORDERING
    )

    with pytest.raises(SettlementInvariantError) as excinfo:
        assert_settlement_invariants(
            instruments=(tape.instrument,),
            market_data=[*tape.market_data, early_close],
            settlement_prices={tape.instrument.id: 0.5},  # off-endpoint: ENDPOINT
        )

    assert excinfo.value.invariant is SettlementInvariant.ENDPOINT


# ---------------------------------------------------------------------------
# Build-time cross-guard order:
#   NotVenueMarketDataError > SettlementInvariantError > UnwrappedWeatherRecordError
#
# Read directly off `build_backtest_engine`'s three guard calls, in the
# order they are written.
# ---------------------------------------------------------------------------


def test_the_market_data_screen_beats_settlement_invariants() -> None:
    """A foreign record in `market_data`, AND no settlement price at all.

    `build_backtest_engine` calls `assert_market_data_is_venue_data` before
    `assert_settlement_invariants`. Both conditions are true; only the first
    is ever reported.

    DESCRIPTIVE, not normative: no documented reason ranks "wrong field" above
    "invisible settlement corruption" -- the module docstring's own priority
    order (settlement first, in its narrative) is not what the CODE does at
    the top of `build_backtest_engine`. This is exactly the kind of gap H-1
    exists to surface.
    """
    tape = synthetic_binary_tape(size_precision=0, settlement_price=1.0)

    with pytest.raises(NotVenueMarketDataError):
        build_backtest_engine(
            _config(
                market_data=[*tape.all_data(), make_climate_day()],
                settlement_prices={},  # ALSO a COVERAGE violation
            ),
        )


def test_settlement_invariants_beat_the_weather_wrap_check() -> None:
    """No settlement price at all, AND an unwrapped weather record.

    `build_backtest_engine` calls `assert_settlement_invariants` before
    `assert_weather_is_wrapped`. Both conditions are true; only the first is
    ever reported.

    DESCRIPTIVE, not normative: same reasoning as above -- this is the order
    the three guard calls happen to be written in.
    """
    with pytest.raises(SettlementInvariantError):
        build_backtest_engine(
            _config(
                settlement_prices={},
                weather_data=(make_climate_day(),),  # ALSO unwrapped
            ),
        )


# ---------------------------------------------------------------------------
# The submit-time order guard: post_only is refused before the naked-short
# check ever runs (`BacktestOrderGuard.on_order_event`).
# ---------------------------------------------------------------------------


class _FakePortfolio:
    def __init__(self, net: Decimal) -> None:
        self._net = net

    def net_position(self, instrument_id: InstrumentId) -> Decimal:
        del instrument_id
        return self._net


class _FakeCache:
    def orders_open(self, *, instrument_id: InstrumentId | None = None) -> Sequence[object]:
        del instrument_id
        return ()


_GUARD_INSTRUMENT = InstrumentId(Symbol("synthetic-guard-precedence"), Venue("POLYMARKET_US"))


def test_post_only_beats_naked_short() -> None:
    """One `OrderInitialized`: `post_only=True` AND a SELL against zero position.

    `on_order_event` calls `_refuse_post_only` before `_refuse_naked_short`.
    The order is simultaneously refusable both ways; only `PostOnlyRefusedError`
    is ever raised.

    DESCRIPTIVE, not normative: nothing in the module docstring ranks the two
    refusals against each other -- they are two independent, unrelated
    concerns (unmodelled maker economics vs. an unfunded short) that happen to
    share one dispatch method, written in this order.
    """
    guard = BacktestOrderGuard(_FakePortfolio(Decimal(0)), _FakeCache())  # type: ignore[arg-type]
    event = OrderInitialized(
        trader_id=TraderId("BREEZY-BACKTEST-001"),
        strategy_id=StrategyId("S-1"),
        instrument_id=_GUARD_INSTRUMENT,
        client_order_id=ClientOrderId("O-1"),
        order_side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        quantity=Quantity(5, 0),  # net long is 0: also a naked short
        time_in_force=TimeInForce.GTC,
        post_only=True,
        reduce_only=False,
        quote_quantity=False,
        options={},
        emulation_trigger=0,
        trigger_instrument_id=None,
        contingency_type=0,
        order_list_id=None,
        linked_order_ids=None,
        parent_order_id=None,
        exec_algorithm_id=None,
        exec_algorithm_params=None,
        exec_spawn_id=None,
        tags=None,
        event_id=UUID4(),
        ts_init=0,
    )

    with pytest.raises(PostOnlyRefusedError):
        guard.on_order_event(event)
