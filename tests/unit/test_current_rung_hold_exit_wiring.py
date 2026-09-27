"""RED-first suite for `continuous_strategy.py`'s exit-side wiring (INC-E3,
``docs/plans/POSITION_EXIT_EXECUTION_2026-09-16.md`` §3).

Two harnesses, matching `test_continuous_rung_hold_backtest_only.py`'s own
split:

* The FULL `BacktestEngine` harness (`backtest()`) -- for the one test that
  needs `submit_exit` to actually reach a `SimulatedExchange` (order shape,
  fill, and Nautilus net-position reduction).
* The LIGHTWEIGHT `_register_and_start` harness (no exec engine) -- for
  everything that only needs a registered `ContinuousRungHoldStrategy` to
  receive a directly-constructed event (`on_order_filled`/`on_order_denied`/
  `on_order_rejected`), never an actual submission.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import LiquiditySide, OrderSide, OrderStatus, TimeInForce
from nautilus_trader.model.events import OrderDenied, OrderFilled, OrderRejected
from nautilus_trader.model.identifiers import (
    AccountId,
    ClientOrderId,
    PositionId,
    TradeId,
    VenueOrderId,
)
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.model.orders import LimitOrder

from breezy.persistence.family_manifest import FamilyManifest
from breezy.runtime.backtest_feed import as_backtest_data
from breezy.runtime.backtest_harness import BreezyBacktestConfig, backtest
from breezy.runtime.paper_replay import (
    UNSCOPED_FAMILY_ID,
    ReplayEntryContext,
    build_paper_replay_config,
    filled_trials_from_engine,
)
from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
from breezy.strategy.current_rung_hold.continuous_backtest_only import (
    ContinuousRungHoldBacktestStrategy,
)
from breezy.strategy.current_rung_hold.continuous_strategy import ContinuousRungHoldStrategy
from breezy.strategy.current_rung_hold.exit_authorization import ExitAuthorization, ExitRule
from breezy.strategy.current_rung_hold.exit_decider import ExitProposal
from breezy.strategy.current_rung_hold.exit_wiring import (
    EXIT_POSITION_TAG_PREFIX as _EXIT_POSITION_TAG_PREFIX,
)
from breezy.strategy.current_rung_hold.exit_wiring import (
    EXIT_RULE_TAG_PREFIX as _EXIT_RULE_TAG_PREFIX,
)
from breezy.strategy.current_rung_hold.trial_day_latch import (
    CONTINUOUS_TRIAL_KEY_PREFIX,
    TrialDayLatchError,
)
from tests.unit.test_continuous_rung_hold_strategy import (
    _PERMISSIVE_EVIDENCE,
    _cont_latch_factory,
    _depth,
    _register_and_start,
)
from tests.unit.test_current_rung_hold_strategy import (
    CLIMATE_DAY,
    INTERIOR_ID,
    NS_PER_MIN,
    STATION,
    WINDOW_OPEN_NS,
    _instrument,
    _observation,
    _quote,
)

_FEE_COEFFICIENT = Decimal("0.06")


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "state.db"


@pytest.fixture
def interior_instrument() -> BinaryOption:
    return _instrument(INTERIOR_ID, lower_f=86, upper_f=87)


def _manifest(*, exit_rule: str | None) -> FamilyManifest:
    return FamilyManifest(
        family_id="pm_us_crh_exit_v4",
        venue="polymarket_us",
        taker_fee_coefficient=Decimal("0.06"),
        trial_id_prefix="current_rung_hold_exit_v4/trial/",
        d0_climate_day="2099-01-01",
        boundary_artefact_path=Path("deploy/families/gs_boundary_pm_us_crh_v2.json"),
        boundary_inputs_sha256="a" * 64,
        composition_kind="continuous_rung_hold",
        density_artefact_path=Path("deploy/families/artefacts/not_applicable_density.json"),
        density_artefact_sha256="247f636350685b38966251703c47d10531913367fbcca175b086a2c298421a65",
        stations=("SFO",),
        status="REGISTERED" if exit_rule is not None else "DRAFT_NOT_REGISTERED",
        manifest_sha256="b" * 64,
        exit_rule=exit_rule,
    )


def _authorization(*, position_id: str, limit_price: Decimal, rule: ExitRule) -> ExitAuthorization:
    return ExitAuthorization(
        family_id="pm_us_crh_exit_v4",
        position_id=position_id,
        client_order_id="exit-shape-1",
        leg="yes",
        attributed_net_long=1,
        working_sell_qty=0,
        quantity=1,
        limit_price=limit_price,
        rule=rule,
        expected_settlement_value=Decimal(0),
        fee_coefficient=_FEE_COEFFICIENT,
        decided_at_ns=WINDOW_OPEN_NS,
        book_staleness_ns=0,
    )


# ---------------------------------------------------------------------------
# Full BacktestEngine harness -- order shape + fill + net-position reduction
#
# `install_position_monitor` (the paper-replay driver, dynamically loaded
# exactly like `test_continuous_rung_hold_backtest_only.py` does) wires a
# REAL `PositionMonitor` BEFORE `strategy.register()` runs -- the exit
# fields are then set directly (mirrors that file's own
# `strategy._position_monitor = ...` convention), so `submit_exit` fires
# DURING the engine's run (while `self._latch` is still open), never after
# it (a `BacktestEngine` runs its FULL configured data and calls
# `on_stop()` before `backtest()` ever yields -- `self._latch` is `None`
# by then, so a post-run call to `submit_exit` would assert-fail).
# ---------------------------------------------------------------------------

_DEAD_TEMP_C_TENTHS = 320  # 32.0C -> 90F, strictly above rung_high=87
_DEAD_CONFIRM_SPAN_MIN = 6  # >= monitor_decision._DEAD_MIN_CONFIRM_SPAN_NS (5 min)


def _dead_scenario_config_and_strategy(
    store_path: Path, interior_instrument: BinaryOption,
) -> tuple[BreezyBacktestConfig, ContinuousRungHoldBacktestStrategy]:
    interior_instrument.info["fee_coefficient"] = "0.06"
    depth_pre_ts = WINDOW_OPEN_NS - 1_000
    quote_ts = WINDOW_OPEN_NS
    depth_post_ts = WINDOW_OPEN_NS + 1
    dead1_ts = WINDOW_OPEN_NS + 2 * NS_PER_MIN
    dead2_ts = WINDOW_OPEN_NS + (2 + _DEAD_CONFIRM_SPAN_MIN) * NS_PER_MIN
    depth_pre = _depth(
        INTERIOR_ID, bids=(("0.01", 10),), asks=(("0.40", 10),), ts_event=depth_pre_ts,
    )
    quote = _quote(INTERIOR_ID, ask="0.40", ts_event=quote_ts)
    # A real resting bid at 0.30, kept fresh through both DEAD readings --
    # what the exit LIMIT SELL prices against and should clear (IOC).
    depth_post = _depth(
        INTERIOR_ID, bids=(("0.30", 10),), asks=(("0.90", 10),), ts_event=depth_post_ts,
    )
    depth_dead1 = _depth(
        INTERIOR_ID, bids=(("0.30", 10),), asks=(("0.90", 10),), ts_event=dead1_ts,
    )
    depth_dead2 = _depth(
        INTERIOR_ID, bids=(("0.30", 10),), asks=(("0.90", 10),), ts_event=dead2_ts,
    )
    observation = _observation(
        temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 5 * NS_PER_MIN,
    )
    first_dead = _observation(temp_c_tenths=_DEAD_TEMP_C_TENTHS, observed_at_ns=dead1_ts)
    second_dead = _observation(temp_c_tenths=_DEAD_TEMP_C_TENTHS, observed_at_ns=dead2_ts)
    config = build_paper_replay_config(
        instruments=[interior_instrument],
        market_data=[depth_pre, quote, depth_post, depth_dead1, depth_dead2],
        weather_data=as_backtest_data([observation, first_dead, second_dead]),
        starting_balances=(Money(10_000, USD),),
        capture_window_ns=(depth_pre_ts, dead2_ts),
        instruments_without_close=frozenset({interior_instrument.id}),
    )
    strategy = ContinuousRungHoldBacktestStrategy(
        CurrentRungHoldConfig(instrument_ids=(interior_instrument.id,)),
        trial_day_latch_factory=_cont_latch_factory(store_path),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    return config, strategy


def test_submit_exit_builds_a_limit_ioc_sell_qty_one_reduce_only_false_order(
    store_path: Path, interior_instrument: BinaryOption, tmp_path: Path,
) -> None:
    """Plan §3 INC-E3 order shape + §4 step 3 acceptance: LIMIT, IOC, SELL,
    qty 1, `reduce_only=False`, and the exit fill REDUCES the Nautilus net
    position (never grows it) -- driven end to end through a real
    `PositionMonitor` + `decide_exit` + `submit_exit`, DURING a real
    `BacktestEngine` run on a confirmed DEAD/EXIT_RECOMMENDED scenario."""
    from tests.unit.test_continuous_rung_hold_backtest_only import _load_paper_replay_driver

    driver = _load_paper_replay_driver()
    from breezy.strategy.current_rung_hold.exit_decider import decide_exit

    config, strategy = _dead_scenario_config_and_strategy(store_path, interior_instrument)
    monitor = driver.install_position_monitor(
        strategy, out_dir=tmp_path / "monitor_out", clock_ns=lambda: strategy.clock.timestamp_ns(),
    )
    monitor._exit_decider = decide_exit
    monitor._exit_manifest = _manifest(exit_rule="crh_exit_v4:R_THREAT_PRIMARY+R_DEAD_BACKSTOP")
    monitor._exit_family_id = "pm_us_crh_exit_v4"
    monitor._exit_client_order_id_factory = lambda: "exit-shape-1"
    monitor._submit_exit = strategy.submit_exit
    monitor._record_exit_offer = strategy.offer_tape.append

    with backtest(
        config, strategies=(strategy,), allow_idle_strategies=True, allow_open_positions=True,
    ) as engine:
        # `filled_trials_from_engine` assumes every order in the cache is an
        # entry-shaped BUY (paper-replay's own invariant, plan-unrelated) --
        # this run also carries a SELL exit order, so this test inspects
        # `engine.cache` directly instead of reusing that helper. Queried
        # INSIDE the `with` block: `engine.dispose()` (on exit) detaches the
        # cache, so a post-exit query on `strategy.cache` sees nothing.
        orders = engine.cache.orders(instrument_id=interior_instrument.id)
        filled_buys = [
            order
            for order in orders
            if order.side is OrderSide.BUY and order.status is OrderStatus.FILLED
        ]
        assert len(filled_buys) == 1, "expected exactly one filled entry BUY order"
        exit_orders = [order for order in orders if order.side is OrderSide.SELL]
        assert len(exit_orders) == 1
        order = exit_orders[0]
        assert isinstance(order, LimitOrder)
        assert order.time_in_force is TimeInForce.IOC
        assert order.quantity == Quantity.from_int(1)
        assert order.is_reduce_only is False
        assert str(order.client_order_id) == "exit-shape-1"

        # The exit fills and REDUCES the position rather than growing it.
        remaining = engine.cache.positions_open(instrument_id=interior_instrument.id)
        assert len(remaining) == 0 or remaining[0].quantity < Quantity.from_int(1)


def test_a_gate_refused_family_manifest_submits_no_order_on_the_same_dead_scenario(
    store_path: Path, interior_instrument: BinaryOption, tmp_path: Path,
) -> None:
    """The live composition with the `pm_us_crh_cont` manifest (no
    `exit_rule`) must never construct an order on the SAME confirmed
    DEAD/EXIT_RECOMMENDED scenario the previous test fires an exit on."""
    from tests.unit.test_continuous_rung_hold_backtest_only import _load_paper_replay_driver

    driver = _load_paper_replay_driver()
    from breezy.strategy.current_rung_hold.exit_decider import decide_exit

    config, strategy = _dead_scenario_config_and_strategy(store_path, interior_instrument)
    monitor = driver.install_position_monitor(
        strategy, out_dir=tmp_path / "monitor_out", clock_ns=lambda: strategy.clock.timestamp_ns(),
    )
    monitor._exit_decider = decide_exit
    monitor._exit_manifest = _manifest(exit_rule=None)
    monitor._exit_family_id = "pm_us_crh_cont"
    monitor._exit_client_order_id_factory = lambda: "should-never-be-minted"
    monitor._submit_exit = strategy.submit_exit
    monitor._record_exit_offer = strategy.offer_tape.append

    with backtest(
        config, strategies=(strategy,), allow_idle_strategies=True, allow_open_positions=True,
    ) as engine:
        ctx = ReplayEntryContext(
            station=STATION,
            climate_day=CLIMATE_DAY.isoformat(),
            bucket=None,
            entry_ask=Decimal("0.40"),
            scheduled_release_at_ns=WINDOW_OPEN_NS + 7 * 24 * 3_600_000_000_000,
        )
        trials = filled_trials_from_engine(
            engine,
            {str(interior_instrument.id): ctx},
            family_id=UNSCOPED_FAMILY_ID,
            trial_id_prefix=CONTINUOUS_TRIAL_KEY_PREFIX,
        )
        assert len(trials) == 1

        # Queried INSIDE the `with` block -- `engine.dispose()` (on exit)
        # detaches the cache, so a post-exit query would see nothing and
        # make this assertion vacuously true.
        orders = engine.cache.orders(instrument_id=interior_instrument.id)
        assert orders, "expected at least the entry BUY order to exist"
        assert all(order.side is OrderSide.BUY for order in orders), (
            "the shadow family must never construct a SELL/exit order"
        )


# ---------------------------------------------------------------------------
# Lightweight harness -- halt veto, fill provenance, AMBIGUOUS/rejected kill
# ---------------------------------------------------------------------------


def test_submit_exit_refuses_when_the_family_is_already_halted(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    assert strategy._latch is not None
    strategy._latch.record_duplicate_fill(
        STATION,
        CLIMATE_DAY.isoformat(),
        venue_order_id="ord-halt-1",
        qty=Decimal(1),
        fill_px=Decimal("0.40"),
        fee=Decimal("0.01"),
        ts_ns=WINDOW_OPEN_NS,
    )
    assert strategy._latch.is_family_halted() is True

    proposal = ExitProposal(
        instrument_id=str(INTERIOR_ID),
        authorization=_authorization(
            position_id="P-halted", limit_price=Decimal("0.30"), rule=ExitRule.R_DEAD,
        ),
        decided_at_ns=WINDOW_OPEN_NS,
    )
    # Must return quietly -- never reach `self.cache.instrument`/
    # `order_factory`/`submit_order` (there is no exec engine wired in this
    # lightweight harness, so any such call would raise).
    strategy.submit_exit(proposal)


def test_an_exit_submitted_while_fee_unverified_is_not_blocked_by_this_check(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """EDGE-1 (architect #1, mandatory): the fee-unverified veto is
    entry-only -- `exit_wiring.submit_exit` must never even consult it."""
    calls: list[int] = []

    def _spy_check(now_ns: int) -> bool:
        calls.append(now_ns)
        return False

    strategy = _register_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        fee_verified_check=_spy_check,
    )
    assert strategy._latch is not None
    assert strategy._latch.is_family_halted() is False

    proposal = ExitProposal(
        instrument_id=str(INTERIOR_ID),
        authorization=_authorization(
            position_id="P-unverified", limit_price=Decimal("0.30"), rule=ExitRule.R_DEAD,
        ),
        decided_at_ns=WINDOW_OPEN_NS,
    )
    # No position exists in this lightweight harness's cache, so this
    # returns quietly after the instrument/position lookups -- the point is
    # that `_spy_check` is never invoked anywhere on this path.
    strategy.submit_exit(proposal)

    assert calls == [], "the fee-verified veto must never be consulted on the exit path"


def _exit_order_filled_event(
    strategy: ContinuousRungHoldStrategy,
    *,
    venue_order_id: str,
    rule: str,
    position_id: str,
) -> OrderFilled:
    order = strategy.order_factory.limit(
        instrument_id=INTERIOR_ID,
        order_side=OrderSide.SELL,
        quantity=Quantity.from_int(1),
        price=Price.from_str("0.30"),
        time_in_force=TimeInForce.IOC,
        reduce_only=False,
        tags=[
            f"{_EXIT_RULE_TAG_PREFIX}{rule}",
            f"{_EXIT_POSITION_TAG_PREFIX}{position_id}",
        ],
        client_order_id=ClientOrderId(f"C-{venue_order_id}"),
    )
    strategy.cache.add_order(order, position_id=PositionId(position_id))
    return OrderFilled(
        trader_id=strategy.trader_id,
        strategy_id=strategy.id,
        instrument_id=INTERIOR_ID,
        client_order_id=order.client_order_id,
        venue_order_id=VenueOrderId(venue_order_id),
        account_id=AccountId("POLYMARKET_US-001"),
        trade_id=TradeId(f"T-{venue_order_id}"),
        position_id=PositionId(position_id),
        order_side=OrderSide.SELL,
        order_type=order.order_type,
        last_qty=Quantity.from_int(1),
        last_px=Price.from_str("0.30"),
        currency=USD,
        commission=Money(0, USD),
        liquidity_side=LiquiditySide.TAKER,
        event_id=UUID4(),
        ts_event=WINDOW_OPEN_NS + 1,
        ts_init=WINDOW_OPEN_NS + 1,
    )


def test_an_exit_fill_records_provenance_onto_the_existing_trial(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    assert strategy._latch is not None
    strategy._latch.consume(
        STATION,
        CLIMATE_DAY.isoformat(),
        latched_at_ns=WINDOW_OPEN_NS,
        instrument_id=str(INTERIOR_ID),
        ask=Decimal("0.40"),
        reason="taken",
        key_instrument_id=str(INTERIOR_ID),
    )

    fill = _exit_order_filled_event(
        strategy, venue_order_id="ord-exit-1", rule="R_DEAD", position_id="P-exit-1",
    )
    strategy.on_order_filled(fill)

    record = strategy._latch.record(
        STATION, CLIMATE_DAY.isoformat(), key_instrument_id=str(INTERIOR_ID),
    )
    assert record is not None
    assert record.exit_reason == "R_DEAD"
    assert record.exit_px == Decimal("0.30")
    assert record.exit_at_ns == WINDOW_OPEN_NS + 1
    assert strategy.position_events.count("exit_filled") == 1
    # The entry-path duplicate-fill halt must NEVER fire for an exit fill.
    assert strategy._latch.is_family_halted() is False


def test_an_exit_order_rejected_by_the_venue_halts_the_family(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    assert strategy._latch is not None
    order = strategy.order_factory.limit(
        instrument_id=INTERIOR_ID,
        order_side=OrderSide.SELL,
        quantity=Quantity.from_int(1),
        price=Price.from_str("0.30"),
        time_in_force=TimeInForce.IOC,
        reduce_only=False,
        tags=[f"{_EXIT_RULE_TAG_PREFIX}R_THREAT", f"{_EXIT_POSITION_TAG_PREFIX}P-rej-1"],
    )
    strategy.cache.add_order(order, position_id=None)
    event = OrderRejected(
        trader_id=strategy.trader_id,
        strategy_id=strategy.id,
        instrument_id=INTERIOR_ID,
        client_order_id=order.client_order_id,
        account_id=AccountId("POLYMARKET_US-001"),
        reason="venue_rejected_test",
        event_id=UUID4(),
        ts_event=WINDOW_OPEN_NS,
        ts_init=WINDOW_OPEN_NS,
    )

    assert strategy._latch.is_family_halted() is False
    strategy.on_order_rejected(event)
    assert strategy._latch.is_family_halted() is True
    assert strategy.position_events.count("exit_order_rejected") == 1


def test_an_exit_order_denied_by_nautilus_halts_the_family_never_the_wait_path(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """A denied EXIT order must never fall through to the entry-only
    `OPEN_INTENT_WAIT_REASON` IN_FLIGHT-clear branch."""
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    assert strategy._latch is not None
    order = strategy.order_factory.limit(
        instrument_id=INTERIOR_ID,
        order_side=OrderSide.SELL,
        quantity=Quantity.from_int(1),
        price=Price.from_str("0.30"),
        time_in_force=TimeInForce.IOC,
        reduce_only=False,
        tags=[f"{_EXIT_RULE_TAG_PREFIX}R_DEAD", f"{_EXIT_POSITION_TAG_PREFIX}P-den-1"],
    )
    strategy.cache.add_order(order, position_id=None)
    event = OrderDenied(
        trader_id=strategy.trader_id,
        strategy_id=strategy.id,
        instrument_id=INTERIOR_ID,
        client_order_id=order.client_order_id,
        reason="risk_engine_denied_test",
        event_id=UUID4(),
        ts_init=WINDOW_OPEN_NS,
    )

    strategy.on_order_denied(event)
    assert strategy._latch.is_family_halted() is True


def test_record_exit_and_record_ambiguous_exit_are_reachable_from_the_public_latch_api(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """Cheap smoke test that the two new `TrialDayLatch` methods this
    wiring depends on stay reachable through the SAME
    `trial_day_latch_factory` the strategy itself uses (defence in depth
    over the focused `test_current_rung_hold_trial_day_latch.py` suite)."""
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    assert strategy._latch is not None
    with pytest.raises(TrialDayLatchError):
        strategy._latch.record_exit(
            STATION,
            CLIMATE_DAY.isoformat(),
            key_instrument_id=str(INTERIOR_ID),
            exit_reason="R_DEAD",
            exit_px=Decimal("0.05"),
            exit_fee=Decimal("0.00"),
            exit_at_ns=WINDOW_OPEN_NS,
        )
    strategy._latch.record_ambiguous_exit(
        position_id="P-smoke", reason="smoke", ts_ns=WINDOW_OPEN_NS,
    )
    assert strategy._latch.is_family_halted() is True


# ---------------------------------------------------------------------------
# Review finding B: the second layer of the AMBIGUOUS-exit cover.
# ---------------------------------------------------------------------------


def _cached_exit_order(
    strategy: ContinuousRungHoldStrategy, *, client_order_id: str, position_id: str,
) -> LimitOrder:
    order = strategy.order_factory.limit(
        instrument_id=INTERIOR_ID,
        order_side=OrderSide.SELL,
        quantity=Quantity.from_int(1),
        price=Price.from_str("0.30"),
        time_in_force=TimeInForce.IOC,
        reduce_only=False,
        tags=[
            f"{_EXIT_RULE_TAG_PREFIX}R_THREAT",
            f"{_EXIT_POSITION_TAG_PREFIX}{position_id}",
        ],
        client_order_id=ClientOrderId(client_order_id),
    )
    strategy.cache.add_order(order, position_id=None)
    return order


def test_a_fresh_process_with_no_open_intent_is_a_no_op(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    assert strategy._latch is not None
    _cached_exit_order(strategy, client_order_id="O-EXIT-noop", position_id="P-noop")

    strategy.check_ambiguous_exit_intent(
        client_order_id="O-EXIT-noop", position_id="P-noop", now_ns=WINDOW_OPEN_NS,
    )

    assert strategy._latch.is_family_halted() is False


def test_an_open_intent_younger_than_the_deadline_never_halts(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """RED (pre-fix): `check_ambiguous_exit_intent` did not exist at all.
    GREEN: an intent still well within a healthy round trip is left alone."""
    from breezy.adapters.polymarket_us.exec import submit_chain

    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    assert strategy._latch is not None
    order = _cached_exit_order(strategy, client_order_id="O-EXIT-young", position_id="P-young")
    strategy._latch._intent_latch.arm(  # type: ignore[union-attr]
        submit_chain.intent_fingerprint(order), now_ns=WINDOW_OPEN_NS,
    )

    strategy.check_ambiguous_exit_intent(
        client_order_id="O-EXIT-young",
        position_id="P-young",
        now_ns=WINDOW_OPEN_NS + 1_000_000_000,  # +1s -- well under the 30s deadline
    )

    assert strategy._latch.is_family_halted() is False


def test_an_open_intent_past_the_deadline_with_a_matching_fingerprint_halts_the_family(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """GREEN: the SAME exit order's own intent, still OPEN well past the
    AMBIGUOUS-send deadline, durably halts the family -- the second-layer
    cover the exec client's silent-refuse path cannot itself provide."""
    from breezy.adapters.polymarket_us.exec import submit_chain

    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    assert strategy._latch is not None
    order = _cached_exit_order(strategy, client_order_id="O-EXIT-stale", position_id="P-stale")
    strategy._latch._intent_latch.arm(  # type: ignore[union-attr]
        submit_chain.intent_fingerprint(order), now_ns=WINDOW_OPEN_NS,
    )

    strategy.check_ambiguous_exit_intent(
        client_order_id="O-EXIT-stale",
        position_id="P-stale",
        now_ns=WINDOW_OPEN_NS + 31_000_000_000,  # +31s -- past the 30s deadline
    )

    assert strategy._latch.is_family_halted() is True


def test_a_stale_open_intent_for_a_DIFFERENT_order_never_halts(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """A stale OPEN intent belonging to a DIFFERENT order (a concurrent
    entry, or a prior exit for a different position) must never be
    attributed to THIS position's exit -- the fingerprint match is the
    unforgeable link, never the client_order_id/position_id arguments
    alone."""
    from breezy.adapters.polymarket_us.exec import submit_chain

    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    assert strategy._latch is not None
    other_order = _cached_exit_order(
        strategy, client_order_id="O-EXIT-other", position_id="P-other",
    )
    strategy._latch._intent_latch.arm(  # type: ignore[union-attr]
        submit_chain.intent_fingerprint(other_order), now_ns=WINDOW_OPEN_NS,
    )
    _cached_exit_order(strategy, client_order_id="O-EXIT-mine", position_id="P-mine")

    strategy.check_ambiguous_exit_intent(
        client_order_id="O-EXIT-mine",
        position_id="P-mine",
        now_ns=WINDOW_OPEN_NS + 31_000_000_000,
    )

    assert strategy._latch.is_family_halted() is False
