"""Unit tests for `breezy.runtime.backtest_harness` -- the venue configuration
and the three settlement invariants it refuses to run without.

Scope split, deliberately. The end-to-end proof that a strategy can be dropped
in and produces a readable result lives in
``tests/contract/test_backtest_harness_stop_gate.py``, because it pins
NautilusTrader 1.231.0 behaviour. THIS module pins the two things that are
Breezy's own:

* the ``add_venue`` argument values fixed by ``docs/specs/BACKTEST_VENUE_CONFIG.md``,
  read from SOURCE where a runtime assertion cannot distinguish "chosen" from
  "defaulted"; and
* the three §5 invariants, as RAISED ERRORS. Every one of them guards a
  failure that is otherwise invisible -- a missing settlement price closes the
  position at the prevailing book and *improves* Sharpe (§0, §7 rank 1).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import CustomData, InstrumentClose
from nautilus_trader.model.enums import InstrumentCloseType
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.objects import Money, Price

from breezy.runtime.backtest_feed import as_backtest_data
from breezy.runtime.backtest_harness import (
    HARNESS_SOURCE_PATH,
    BreezyBacktestConfig,
    SettlementInvariant,
    SettlementInvariantError,
    UnwrappedWeatherRecordError,
    assert_settlement_invariants,
    build_backtest_engine,
)
from tests.support.synthetic_binary_tape import synthetic_binary_tape
from tests.unit.test_persistence_catalog import make_climate_day

ABSENT = InstrumentId(Symbol("synthetic-absent-market"), Venue("POLYMARKET_US"))


def make_config(**overrides: object) -> BreezyBacktestConfig:
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
# Invariant 1 -- coverage. "Highest-value guard in the entire configuration."
# ---------------------------------------------------------------------------


def test_an_instrument_closed_without_a_settlement_price_is_refused() -> None:
    tape = synthetic_binary_tape(size_precision=0)

    with pytest.raises(SettlementInvariantError) as excinfo:
        assert_settlement_invariants(market_data=tape.all_data(), settlement_prices={})

    assert excinfo.value.invariant is SettlementInvariant.COVERAGE
    assert str(tape.instrument.id) in str(excinfo.value)


def test_a_settlement_price_for_a_DIFFERENT_instrument_does_not_satisfy_coverage() -> None:
    """A dict that is merely non-empty is the near-miss this guard exists for."""
    tape = synthetic_binary_tape(size_precision=0)

    with pytest.raises(SettlementInvariantError) as excinfo:
        assert_settlement_invariants(
            market_data=tape.all_data(),
            settlement_prices={ABSENT: 1.0},
        )

    assert excinfo.value.invariant is SettlementInvariant.COVERAGE


def test_an_end_of_session_close_needs_no_settlement_price() -> None:
    """`process_instrument_close` silently discards non-CONTRACT_EXPIRED closes
    (`engine.pyx:4844`), so such an instrument never reaches the settlement
    branch and demanding a price for it would be a false positive.
    """
    tape = synthetic_binary_tape(size_precision=0)
    benign = InstrumentClose(
        tape.instrument.id,
        Price(1.0, tape.instrument.price_precision),
        InstrumentCloseType.END_OF_SESSION,
        tape.instrument_close.ts_event,
        tape.instrument_close.ts_init,
    )

    assert_settlement_invariants(
        market_data=[*tape.market_data, benign],
        settlement_prices={},
    )


def test_a_run_with_no_close_at_all_needs_no_settlement_prices() -> None:
    tape = synthetic_binary_tape(size_precision=0)

    assert_settlement_invariants(market_data=list(tape.market_data), settlement_prices={})


# ---------------------------------------------------------------------------
# Invariant 2 -- every value is exactly 0.0 or 1.0
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("price", [0.97, 0.5, -0.0001, 1.0000001, 2.0, -1.0])
def test_a_settlement_price_that_is_not_an_endpoint_is_refused(price: float) -> None:
    """§5 step 3: a weather binary settling off the endpoints is a void or an
    ambiguous resolution. It must raise, never be quantized to two decimals --
    and `theta*C*p*(1-p)` fabricates a settlement fee anywhere but 0 and 1.
    """
    tape = synthetic_binary_tape(size_precision=0)

    with pytest.raises(SettlementInvariantError) as excinfo:
        assert_settlement_invariants(
            market_data=tape.all_data(),
            settlement_prices={tape.instrument.id: price},
        )

    assert excinfo.value.invariant is SettlementInvariant.ENDPOINT


@pytest.mark.parametrize("price", [0.0, 1.0])
def test_both_endpoints_are_accepted(price: float) -> None:
    tape = synthetic_binary_tape(size_precision=0)

    assert_settlement_invariants(
        market_data=tape.all_data(),
        settlement_prices={tape.instrument.id: price},
    )


def test_an_extra_settlement_price_for_an_uncosed_instrument_is_still_endpoint_checked() -> None:
    """Coverage is a superset rule (`⊇`), so extras are allowed -- but an extra
    carrying 0.97 would still be applied by the engine if that instrument were
    later closed, so the endpoint rule covers the whole dict.
    """
    tape = synthetic_binary_tape(size_precision=0)

    with pytest.raises(SettlementInvariantError) as excinfo:
        assert_settlement_invariants(
            market_data=tape.all_data(),
            settlement_prices={tape.instrument.id: 1.0, ABSENT: 0.97},
        )

    assert excinfo.value.invariant is SettlementInvariant.ENDPOINT


# ---------------------------------------------------------------------------
# Invariant 3 -- the close strictly follows the instrument's last market data
# ---------------------------------------------------------------------------


def test_a_close_that_precedes_the_last_market_data_is_refused() -> None:
    """`_expiration_processed` is a one-shot latch that ALSO cancels every open
    order (`engine.pyx:5936-5947`). An early close kills the instrument for the
    rest of the run and yields a shorter, calmer, entirely plausible curve.
    """
    tape = synthetic_binary_tape(size_precision=0)
    early = InstrumentClose(
        tape.instrument.id,
        Price(1.0, tape.instrument.price_precision),
        InstrumentCloseType.CONTRACT_EXPIRED,
        tape.market_data[0].ts_event,
        tape.market_data[0].ts_init,
    )

    with pytest.raises(SettlementInvariantError) as excinfo:
        assert_settlement_invariants(
            market_data=[*tape.market_data, early],
            settlement_prices={tape.instrument.id: 1.0},
        )

    assert excinfo.value.invariant is SettlementInvariant.ORDERING


def test_a_close_exactly_equal_to_the_last_market_data_ts_is_refused() -> None:
    """"Strictly exceeds" -- the boundary case, stated by the spec in those words."""
    tape = synthetic_binary_tape(size_precision=0)
    tied = InstrumentClose(
        tape.instrument.id,
        Price(1.0, tape.instrument.price_precision),
        InstrumentCloseType.CONTRACT_EXPIRED,
        tape.last_market_data_ts_ns,
        tape.last_market_data_ts_ns,
    )

    with pytest.raises(SettlementInvariantError) as excinfo:
        assert_settlement_invariants(
            market_data=[*tape.market_data, tied],
            settlement_prices={tape.instrument.id: 1.0},
        )

    assert excinfo.value.invariant is SettlementInvariant.ORDERING


def test_the_ordering_rule_is_per_instrument_not_global() -> None:
    """Instrument A's close may precede instrument B's data. A global maximum
    would reject a perfectly valid multi-market run.
    """
    early = synthetic_binary_tape(size_precision=0, settlement_price=1.0)
    late = synthetic_binary_tape(size_precision=2, settlement_price=0.0)
    shifted_close = InstrumentClose(
        late.instrument.id,
        Price(0.0, late.instrument.price_precision),
        InstrumentCloseType.CONTRACT_EXPIRED,
        late.instrument_close.ts_event,
        late.instrument_close.ts_init,
    )

    assert_settlement_invariants(
        market_data=[*early.all_data(), *late.market_data, shifted_close],
        settlement_prices={early.instrument.id: 1.0, late.instrument.id: 0.0},
    )


def test_the_valid_synthetic_tape_satisfies_all_three_invariants() -> None:
    tape = synthetic_binary_tape(size_precision=0, settlement_price=1.0)

    assert_settlement_invariants(
        market_data=tape.all_data(),
        settlement_prices={tape.instrument.id: tape.settlement_price},
    )


# ---------------------------------------------------------------------------
# The invariants are enforced by the BUILDER, not merely available to callers
# ---------------------------------------------------------------------------


def test_building_an_engine_runs_the_invariants() -> None:
    """A helper nobody calls is a comment. The builder must call it itself."""
    with pytest.raises(SettlementInvariantError) as excinfo:
        build_backtest_engine(make_config(settlement_prices={}))

    assert excinfo.value.invariant is SettlementInvariant.COVERAGE


def test_the_invariants_run_before_any_engine_is_constructed() -> None:
    """Ordering matters: a `BacktestEngine` built and then abandoned leaks a
    Rust-side trader registration for the whole process.
    """
    with pytest.raises(SettlementInvariantError):
        build_backtest_engine(make_config(settlement_prices={ABSENT: 0.5}))


# ---------------------------------------------------------------------------
# Weather records must arrive WRAPPED
# ---------------------------------------------------------------------------


def test_an_unwrapped_weather_record_is_refused_rather_than_dropped() -> None:
    """`DataEngine._handle_data` LOGS AND DROPS a record it cannot dispatch on.

    The catalog readers return the unwrapped shape by design, so
    `add_data(read_climate_days(catalog), client_id=...)` is the obvious call
    and loses every record to an ERROR line. The harness is the last place
    that can turn that into a failure.
    """
    with pytest.raises(UnwrappedWeatherRecordError) as excinfo:
        build_backtest_engine(make_config(weather_data=(make_climate_day(),)))

    assert "as_backtest_data" in str(excinfo.value)


def test_wrapped_weather_records_are_accepted() -> None:
    engine = build_backtest_engine(
        make_config(weather_data=tuple(as_backtest_data([make_climate_day()]))),
    )
    try:
        assert engine is not None
    finally:
        engine.dispose()


def test_the_wrapping_check_is_type_exact_on_custom_data() -> None:
    """A subclass of `CustomData` is not what `DataEngine` dispatches on."""

    class _CustomDataSubclass(CustomData):
        pass

    wrapped = as_backtest_data([make_climate_day()])[0]
    impostor = _CustomDataSubclass(data_type=wrapped.data_type, data=wrapped.data)

    with pytest.raises(UnwrappedWeatherRecordError):
        build_backtest_engine(make_config(weather_data=(impostor,)))


# ---------------------------------------------------------------------------
# The venue configuration matches the spec, argument by argument
# ---------------------------------------------------------------------------


def add_venue_keywords() -> dict[str, str]:
    """The `add_venue(...)` call in the harness, as SOURCE text per keyword.

    Read from source rather than from a built `SimulatedExchange` because most
    of these arguments are indistinguishable at runtime from their defaults --
    `use_random_ids=False`, `queue_position=False` and `bar_execution=False`
    all leave no observable trace on an exchange that saw no bars and no
    trades. Only the source can say the value was CHOSEN.
    """
    tree = ast.parse(Path(HARNESS_SOURCE_PATH).read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_venue"
    ]
    assert len(calls) == 1, f"expected exactly one add_venue call, found {len(calls)}"
    call = calls[0]
    assert not call.args, "every add_venue argument must be passed BY KEYWORD"
    return {kw.arg: ast.unparse(kw.value) for kw in call.keywords if kw.arg is not None}


#: `docs/specs/BACKTEST_VENUE_CONFIG.md` §1, transcribed. Values that are
#: expressions rather than literals (`venue`, `starting_balances`,
#: `settlement_prices`, `fee_model`) are matched on their source text.
SPEC_ARGUMENTS: dict[str, str] = {
    "oms_type": "OmsType.NETTING",
    "account_type": "AccountType.CASH",
    "base_currency": "USD",
    "book_type": "BookType.L2_MBP",
    "fill_model": "FillModel()",
    "fee_model": "PolymarketUSFeeModel()",
    "latency_model": "None",
    "liquidity_consumption": "True",
    "trade_execution": "False",
    "bar_execution": "False",
    "bar_adaptive_high_low_ordering": "False",
    "queue_position": "False",
    "reject_stop_orders": "True",
    "support_gtd_orders": "True",
    "support_contingent_orders": "False",
    "use_reduce_only": "True",
    "use_position_ids": "True",
    "use_random_ids": "False",
    "use_market_order_acks": "False",
    "allow_cash_borrowing": "False",
    "frozen_account": "False",
    "price_protection_points": "None",
    "routing": "False",
}


@pytest.mark.parametrize(("argument", "value"), sorted(SPEC_ARGUMENTS.items()))
def test_the_venue_is_configured_exactly_as_the_spec_fixes_it(argument: str, value: str) -> None:
    assert add_venue_keywords().get(argument) == value


def test_the_venue_omits_the_margin_arguments_the_spec_says_to_omit() -> None:
    # "Ignored on CASH" (§1). Passing them would imply leverage exists here.
    keywords = add_venue_keywords()

    assert "default_leverage" not in keywords
    assert "leverages" not in keywords
    assert "margin_model" not in keywords


def test_the_venue_names_the_polymarket_us_venue_and_the_operator_balances() -> None:
    keywords = add_venue_keywords()

    assert keywords["venue"] == "POLYMARKET_US_VENUE"
    assert keywords["starting_balances"] == "list(config.starting_balances)"
    assert keywords["settlement_prices"] == "dict(config.settlement_prices)"


def test_every_spec_argument_is_covered_by_this_table() -> None:
    """Guards the table itself: an argument added to the call without being
    added here would go unreviewed.
    """
    unreviewed = set(add_venue_keywords()) - set(SPEC_ARGUMENTS) - {
        "venue",
        "starting_balances",
        "settlement_prices",
    }

    assert unreviewed == set()
