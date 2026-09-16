"""Zero-call-sites guarantee, wiring half (plan §6 shadow stage): the SAME
take/refuse decision -- and therefore the SAME arguments ever reaching
``_maybe_submit`` (Phase 0's sole gateway toward order construction) --
results whether the shadow resting-bid decider computes its real values or
something else entirely. The decider is consulted strictly AFTER
``decision``/``yes_admission_refusal`` are already final (see
``continuous_strategy.py``'s own comment at the YES/NO wiring sites), so
this pins that guarantee directly rather than trusting the wiring by
inspection alone.

Complements ``test_resting_decider_shadow.py``'s own zero-call-sites AST
scan (the decider module never IMPORTS order-construction names) with the
runtime half: even a decider that returns wildly different values on every
tick cannot change what the live family submits.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from nautilus_trader.common.component import TestClock
from nautilus_trader.model.identifiers import TraderId
from nautilus_trader.portfolio import Portfolio
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
from breezy.strategy.current_rung_hold.continuous_strategy import ContinuousRungHoldStrategy
from breezy.strategy.current_rung_hold.decision import Take
from breezy.strategy.current_rung_hold.resting_decider import ShadowRestTickResult
from tests.unit.test_continuous_rung_hold_strategy import _cont_latch_factory
from tests.unit.test_current_rung_hold_strategy import (
    INTERIOR_ID,
    WINDOW_OPEN_NS,
    _instrument,
    _observation,
    _quote,
)

_BOGUS_RESULT = ShadowRestTickResult(
    state="RESTING",
    price=Decimal("0.13"),
    margin=Decimal("0.13"),
    price_secondary=Decimal("0.13"),
    reason="rest",
    fill_event=True,
)


def _build_strategy(store_path: Path) -> ContinuousRungHoldStrategy:
    instrument = _instrument(INTERIOR_ID, lower_f=86, upper_f=87)
    cfg = CurrentRungHoldConfig(instrument_ids=(instrument.id,))
    strategy = ContinuousRungHoldStrategy(
        cfg, trial_day_latch_factory=_cont_latch_factory(store_path),
    )
    clock = TestClock()
    clock.set_time(WINDOW_OPEN_NS)
    msgbus = TestComponentStubs.msgbus()
    cache = TestComponentStubs.cache()
    cache.add_instrument(instrument)
    portfolio = Portfolio(msgbus=msgbus, cache=cache, clock=clock)
    strategy.register(
        trader_id=TraderId("BACKTEST-001"),
        portfolio=portfolio,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
    )
    strategy.start()
    return strategy


def _run_and_capture_submit_args(strategy: ContinuousRungHoldStrategy) -> list[object]:
    captured: list[object] = []
    orig_maybe = strategy._maybe_submit

    def spy_maybe(iid: str, decision: object) -> None:
        captured.append((iid, decision))
        return orig_maybe(iid, decision)

    strategy._maybe_submit = spy_maybe  # type: ignore[method-assign]

    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))
    return captured


def test_a_bogus_shadow_decider_output_never_changes_what_reaches_maybe_submit(
    tmp_path: Path,
) -> None:
    real_strategy = _build_strategy(tmp_path / "real")
    real_calls = _run_and_capture_submit_args(real_strategy)

    bogus_strategy = _build_strategy(tmp_path / "bogus")
    # A deliberately wrong, fixed shadow result on EVERY tick -- if the
    # decider's output ever leaked into the take/refuse path, this would
    # change the captured `_maybe_submit` arguments.
    bogus_strategy._shadow_rest_decider.evaluate_tick = (  # type: ignore[method-assign]
        lambda **_kwargs: _BOGUS_RESULT
    )
    bogus_calls = _run_and_capture_submit_args(bogus_strategy)

    assert len(real_calls) == 1
    assert len(bogus_calls) == 1
    (real_iid, real_decision), = real_calls
    (bogus_iid, bogus_decision), = bogus_calls
    assert real_iid == bogus_iid
    assert isinstance(real_decision, Take)
    assert isinstance(bogus_decision, Take)
    assert real_decision == bogus_decision


def test_a_raising_shadow_decider_still_never_reaches_maybe_submit_differently(
    tmp_path: Path,
) -> None:
    """An even stronger form: if the decider call itself raised, Phase 0's
    own `_hunt_tick` has no try/except around the decider call today by
    design (a decider bug should be loud, never silently swallowed into a
    live strategy the way `_forward_to_monitor` swallows a monitor bug) --
    pinned here so a future change that wraps it in a blanket try/except
    is a deliberate decision, not an accident."""
    strategy = _build_strategy(tmp_path / "raising")

    def _raise(**_kwargs: object) -> ShadowRestTickResult:
        raise RuntimeError("shadow decider exploded")

    strategy._shadow_rest_decider.evaluate_tick = _raise  # type: ignore[method-assign]

    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    try:
        strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))
    except RuntimeError as exc:
        assert "shadow decider exploded" in str(exc)
    else:
        raise AssertionError("expected the decider's exception to propagate, not be swallowed")
