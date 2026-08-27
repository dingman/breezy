"""The settlement gate, INVERTED: every tradeable instrument must be settled.

Why this is a separate module from ``test_runtime_backtest_harness.py``
-----------------------------------------------------------------------

That module pins the three §5 invariants as they were first written. All three
were derived FROM ``market_data``: "every instrument that receives a
``CONTRACT_EXPIRED`` close must carry a settlement price, at an endpoint, after
its last record". Each is true and each is worth keeping -- but all three are
**vacuous on the empty set**. A run whose ``market_data`` carries no close at
all satisfies every one of them, and produces:

* a position that is never closed,
* ``realized_pnl`` equal to the entry commission alone,
* ``avg_px_close == 0.0`` -- which is the SAME value a genuine settle-at-zero
  produces, and on a weather ladder most legs DO settle at zero,
* and no exception, no log line, and no failing assertion anywhere.

The rules in this module invert the direction: they are derived from
``instruments`` -- everything that could trade -- and demand that each one
RECEIVES exactly one ``CONTRACT_EXPIRED`` close. That is the direction in which
"nothing was configured" fails instead of passing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import InstrumentClose
from nautilus_trader.model.enums import InstrumentCloseType
from nautilus_trader.model.objects import Money, Price

from breezy.runtime.backtest_harness import (
    BreezyBacktestConfig,
    SettlementInvariant,
    SettlementInvariantError,
    assert_settlement_invariants,
    build_backtest_engine,
)
from tests.support.synthetic_binary_tape import synthetic_binary_tape

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nautilus_trader.core.data import Data


def _config(**overrides: object) -> BreezyBacktestConfig:
    tape = synthetic_binary_tape(size_precision=0, settlement_price=1.0)
    kwargs: dict[str, object] = {
        "instruments": (tape.instrument,),
        "market_data": tape.all_data(),
        "settlement_prices": {tape.instrument.id: tape.settlement_price},
        "starting_balances": (Money(1_000, USD),),
    }
    kwargs.update(overrides)
    return BreezyBacktestConfig(**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The inverted rule: derived from `instruments`, not from `market_data`
# ---------------------------------------------------------------------------


def test_an_instrument_that_receives_no_close_at_all_is_refused() -> None:
    """The whole point. Every older invariant passes VACUOUSLY on this input."""
    tape = synthetic_binary_tape(size_precision=0, settlement_price=1.0)

    with pytest.raises(SettlementInvariantError) as excinfo:
        assert_settlement_invariants(
            instruments=(tape.instrument,),
            market_data=list(tape.market_data),  # every record EXCEPT the close
            settlement_prices={tape.instrument.id: 1.0},
        )

    assert excinfo.value.invariant is SettlementInvariant.CLOSE
    assert str(tape.instrument.id) in str(excinfo.value)


def test_the_missing_close_error_explains_why_the_author_cannot_see_it_themselves(
) -> None:
    """`avg_px_close` is 0.0 on an unsettled position AND on a real loser.

    A strategy author who checks the obvious field cannot tell the two apart,
    so the error has to say so; otherwise the guard reads as pedantry and gets
    silenced.
    """
    tape = synthetic_binary_tape(size_precision=0, settlement_price=1.0)

    with pytest.raises(SettlementInvariantError) as excinfo:
        assert_settlement_invariants(
            instruments=(tape.instrument,),
            market_data=list(tape.market_data),
            settlement_prices={tape.instrument.id: 1.0},
        )

    assert "avg_px_close" in str(excinfo.value)


def test_a_multi_leg_run_missing_ONE_close_names_exactly_that_leg() -> None:
    """The realistic shape: N-1 legs settle and look right, one is silent."""
    settled = synthetic_binary_tape(size_precision=0, settlement_price=1.0)
    unsettled = synthetic_binary_tape(size_precision=2, settlement_price=0.0)
    market_data: list[Data] = [*settled.all_data(), *unsettled.market_data]

    with pytest.raises(SettlementInvariantError) as excinfo:
        assert_settlement_invariants(
            instruments=(settled.instrument, unsettled.instrument),
            market_data=market_data,
            settlement_prices={
                settled.instrument.id: 1.0,
                unsettled.instrument.id: 0.0,
            },
        )

    assert excinfo.value.invariant is SettlementInvariant.CLOSE
    assert str(unsettled.instrument.id) in str(excinfo.value)
    assert str(settled.instrument.id) not in str(excinfo.value)


def test_a_second_close_for_the_same_instrument_is_refused() -> None:
    """`_expiration_processed` is a ONE-SHOT latch: the second close is a no-op.

    A tape carrying two closes is therefore a tape whose author believes
    something is happening that is not.
    """
    tape = synthetic_binary_tape(size_precision=0, settlement_price=1.0)
    later = tape.instrument_close.ts_init + 1
    duplicate = InstrumentClose(
        tape.instrument.id,
        Price(1.0, tape.instrument.price_precision),
        InstrumentCloseType.CONTRACT_EXPIRED,
        later,
        later,
    )

    with pytest.raises(SettlementInvariantError) as excinfo:
        assert_settlement_invariants(
            instruments=(tape.instrument,),
            market_data=[*tape.all_data(), duplicate],
            settlement_prices={tape.instrument.id: 1.0},
        )

    assert excinfo.value.invariant is SettlementInvariant.DUPLICATE_CLOSE
    assert str(tape.instrument.id) in str(excinfo.value)


def test_an_end_of_session_close_does_not_satisfy_the_rule() -> None:
    """`process_instrument_close` DISCARDS a non-CONTRACT_EXPIRED close
    (`engine.pyx:4844`), so it never reaches the settlement branch. Accepting
    it here would be the same vacuity one level down.
    """
    tape = synthetic_binary_tape(size_precision=0, settlement_price=1.0)
    benign = InstrumentClose(
        tape.instrument.id,
        Price(1.0, tape.instrument.price_precision),
        InstrumentCloseType.END_OF_SESSION,
        tape.instrument_close.ts_event,
        tape.instrument_close.ts_init,
    )

    with pytest.raises(SettlementInvariantError) as excinfo:
        assert_settlement_invariants(
            instruments=(tape.instrument,),
            market_data=[*tape.market_data, benign],
            settlement_prices={tape.instrument.id: 1.0},
        )

    assert excinfo.value.invariant is SettlementInvariant.CLOSE


def test_a_fully_settled_tape_passes() -> None:
    tape = synthetic_binary_tape(size_precision=0, settlement_price=1.0)

    assert_settlement_invariants(
        instruments=(tape.instrument,),
        market_data=tape.all_data(),
        settlement_prices={tape.instrument.id: 1.0},
    )


# ---------------------------------------------------------------------------
# The opt-out NAMES the instrument -- it is not a boolean
# ---------------------------------------------------------------------------


def test_an_instrument_named_in_the_opt_out_may_go_unsettled() -> None:
    """A test that deliberately studies an unsettled leg must still be writable.

    The waiver is per-INSTRUMENT rather than a flag, so waiving one leg cannot
    silently waive the others -- which is exactly how the vacuous version
    behaved.
    """
    tape = synthetic_binary_tape(size_precision=0, settlement_price=1.0)

    assert_settlement_invariants(
        instruments=(tape.instrument,),
        market_data=list(tape.market_data),
        settlement_prices={tape.instrument.id: 1.0},
        instruments_without_close=(tape.instrument.id,),
    )


def test_the_opt_out_covers_only_the_instrument_it_names() -> None:
    settled = synthetic_binary_tape(size_precision=0, settlement_price=1.0)
    unsettled = synthetic_binary_tape(size_precision=2, settlement_price=0.0)

    with pytest.raises(SettlementInvariantError) as excinfo:
        assert_settlement_invariants(
            instruments=(settled.instrument, unsettled.instrument),
            market_data=[*settled.market_data, *unsettled.market_data],
            settlement_prices={
                settled.instrument.id: 1.0,
                unsettled.instrument.id: 0.0,
            },
            instruments_without_close=(unsettled.instrument.id,),
        )

    assert excinfo.value.invariant is SettlementInvariant.CLOSE
    assert str(settled.instrument.id) in str(excinfo.value)


# ---------------------------------------------------------------------------
# The BUILDER enforces it, and does so before an engine exists
# ---------------------------------------------------------------------------


def test_building_an_engine_refuses_a_tape_with_no_close() -> None:
    tape = synthetic_binary_tape(size_precision=0, settlement_price=1.0)

    with pytest.raises(SettlementInvariantError) as excinfo:
        build_backtest_engine(_config(market_data=list(tape.market_data)))

    assert excinfo.value.invariant is SettlementInvariant.CLOSE


def test_the_config_carries_the_per_instrument_waiver() -> None:
    tape = synthetic_binary_tape(size_precision=0, settlement_price=1.0)
    engine = build_backtest_engine(
        _config(
            market_data=list(tape.market_data),
            instruments_without_close=frozenset({tape.instrument.id}),
        ),
    )
    try:
        assert engine is not None
    finally:
        engine.dispose()
