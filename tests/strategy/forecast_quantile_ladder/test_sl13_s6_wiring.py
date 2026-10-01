"""FQ-S6: real-order path wiring (plan §3 S6, findings F6-F8, items 1-2).

Covers, at the strategy level:

* the fee-verified guard's ``(now_ns) -> bool`` shape (F6) -- the SAME shape
  ``ContinuousRungHoldStrategy`` already uses, called with
  ``self.clock.timestamp_ns()``, never a zero-arg callable;
* B4 (F7): the final ``... subscribed n=<k>`` marker is emitted ONLY on an
  actual, non-zero subscription;
* order-event alerts (``FQ_ORDER_FILLED|DENIED|REJECTED|EXPIRED``), routed
  through ``resolve_alert_sink()`` and never carrying an operator-reserved
  cap value;
* the D+1 readiness poll (item 2): a native ``TestClock``-driven
  ``Clock.set_timer`` re-resolution every 5 minutes for 60 minutes, then the
  terminal ``FQ_D1_NOT_READY_TERMINAL`` line plus one CRITICAL alert.

Reuses ``tests.unit.test_current_rung_hold_strategy``'s ``_instrument``
fixture builder exactly as ``test_sl13_wiring.py`` already does -- never a
second, drifting instrument fixture.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, MutableMapping, Sequence
from dataclasses import dataclass

import pytest
from nautilus_trader.common.component import TestClock
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import LiquiditySide, OrderSide, OrderType, TimeInForce
from nautilus_trader.model.events import OrderDenied, OrderExpired, OrderFilled, OrderRejected
from nautilus_trader.model.identifiers import (
    AccountId,
    InstrumentId,
    Symbol,
    TradeId,
    TraderId,
    Venue,
    VenueOrderId,
)
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.model.orders import LimitOrder
from nautilus_trader.portfolio import Portfolio
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.runtime.health import AlertPayload
from breezy.strategy.forecast_quantile_ladder import strategy as strategy_module
from breezy.strategy.forecast_quantile_ladder.bounds import RungBounds
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import LiveCalibration
from breezy.strategy.forecast_quantile_ladder.config import ForecastQuantileLadderConfig
from breezy.strategy.forecast_quantile_ladder.decision import Take
from breezy.strategy.forecast_quantile_ladder.strategy import ForecastQuantileLadderStrategy
from breezy.strategy.ladder_ev.config import LadderEvConfig
from breezy.strategy.ladder_ev.forecast_subscriber import ForecastQuantileStateActor
from breezy.strategy.ladder_ev.location_correction import CorrectionForm
from breezy.strategy.ladder_ev.quantile_density import (
    CdfMethod,
    EmosParams,
    Percentiles,
    Rung,
    build_cdf,
    rung_probabilities,
)
from tests.unit.test_current_rung_hold_strategy import _instrument

STATION = "LAX"
YES_ID = InstrumentId(Symbol("lax-80-81"), Venue("POLYMARKET_US"))


class _RecordingAlertSink:
    def __init__(self) -> None:
        self.payloads: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.payloads.append(payload)


def _config(station: str = STATION) -> ForecastQuantileLadderConfig:
    return ForecastQuantileLadderConfig(
        stations=(station,),
        calibration_artefact_path="/tmp/unused.json",
        calibration_artefact_sha256="a" * 64,
    )


def _artefact() -> LiveCalibration:
    identity = EmosParams(a=0.0, gamma=0.0, delta=1.0)
    return LiveCalibration(
        sha256="a" * 64,
        cdf_method=CdfMethod.NORMAL,
        correction_form=CorrectionForm.NONE,
        linear_coefficients=None,
        month_offsets={},
        point_by_version={"": identity},
        draws_by_version={"": (identity,)},
    )


def _bounds_provider(
    *, percentiles: Percentiles, draws: Sequence[EmosParams], ladder: Sequence[Rung], rung_id: str,
) -> RungBounds:
    del draws
    cdf = build_cdf(CdfMethod.NORMAL, percentiles)
    p_hat = rung_probabilities(cdf, ladder)[rung_id]
    return RungBounds(p_hat=p_hat, p_lower=max(0.0, p_hat - 0.03), p_upper=min(1.0, p_hat + 0.03))


def _build(
    *,
    station: str = STATION,
    instruments: tuple[BinaryOption, ...] = (),
    initial_ids: tuple[str, ...] | None = None,
    fee_verified: Callable[[int], bool] | None = None,
    d1_resolver: Callable[[], tuple[str, ...]] | None = None,
    d1_readiness_state: MutableMapping[str, bool | None] | None = None,
    now_ns: int = 1_700_000_000_000_000_000,
) -> tuple[ForecastQuantileLadderStrategy, TestClock]:
    """``instruments`` populate ``cache`` (what the catalog/venue KNOWS
    about); ``initial_ids`` (defaults to every id in ``instruments``) is
    what the strategy is CONSTRUCTED with as its own candidate list -- the
    two differ for the D+1 readiness-poll tests, which need an instrument
    already resolvable in the cache but NOT yet known to the strategy at
    `on_start`, exactly like a catalog row that only lands between boot and
    the readiness poll's own re-resolution.
    """
    quantile_actor = ForecastQuantileStateActor(
        stations=(station,), std_utc_offset_hours={station: -8.0},
    )
    clock = TestClock()
    clock.set_time(now_ns)
    msgbus = TestComponentStubs.msgbus()
    cache = TestComponentStubs.cache()
    for instrument in instruments:
        cache.add_instrument(instrument)
    quantile_actor.register_base(
        portfolio=TestComponentStubs.portfolio(), msgbus=msgbus, cache=cache, clock=clock,
    )
    quantile_actor.start()

    resolved_initial_ids = (
        initial_ids if initial_ids is not None else tuple(str(i.id) for i in instruments)
    )
    strategy = ForecastQuantileLadderStrategy(
        _config(station),
        quantile_actor=quantile_actor,
        calibration=_artefact(),
        ladder_cfg=LadderEvConfig(),
        bounds_provider=_bounds_provider,
        fee_verified=fee_verified,
        instrument_ids=resolved_initial_ids,
        d1_resolver=d1_resolver,
        d1_readiness_state=d1_readiness_state,
    )
    portfolio = Portfolio(msgbus=msgbus, cache=cache, clock=clock)
    strategy.register(
        trader_id=TraderId("BACKTEST-001"), portfolio=portfolio, msgbus=msgbus, cache=cache,
        clock=clock,
    )
    return strategy, clock


def _take() -> Take:
    return Take(
        instrument_id=str(YES_ID),
        station=STATION,
        climate_day=dt.date(2026, 9, 4),
        side="yes",
        rung_id="i1",
        qty=1,
        ev_net=0.1,
        p_hat=0.2,
        p_lower=0.17,
        p_upper=0.23,
    )


@dataclass(frozen=True, slots=True)
class _FakePermit:
    expires_at_ns: int


def _open_permit() -> _FakePermit:
    return _FakePermit(expires_at_ns=1_000_000_000_000 + 10 * 3_600_000_000_000)


def _limit_order(strategy: ForecastQuantileLadderStrategy) -> LimitOrder:
    return strategy.order_factory.limit(
        instrument_id=YES_ID,
        order_side=OrderSide.BUY,
        quantity=Quantity.from_int(1),
        price=Price.from_str("0.30"),
        time_in_force=TimeInForce.IOC,
    )


def _advance_by(clock: TestClock, delta_ns: int) -> None:
    """``TestClock.advance_time`` takes an ABSOLUTE target, never a delta."""
    to_time_ns = clock.timestamp_ns() + delta_ns
    for event in clock.advance_time(to_time_ns):
        event.handle()


# ---------------------------------------------------------------------------
# F6: the fee-verified guard is (now_ns) -> bool, called with the clock.
# ---------------------------------------------------------------------------


def test_fee_verified_is_called_with_now_ns_not_a_zero_arg_callable() -> None:
    captured: list[int] = []

    def _check(now_ns: int) -> bool:
        captured.append(now_ns)
        return True

    strategy, clock = _build(fee_verified=_check)
    strategy._order_submission_permit = _open_permit()  # white-box

    reason = strategy.try_submit(_take())

    assert reason is None
    assert captured == [clock.timestamp_ns()]


def test_an_unbound_fee_check_refuses_fee_unverified() -> None:
    strategy, _clock = _build(fee_verified=lambda _now_ns: False)
    strategy._order_submission_permit = _open_permit()  # white-box

    reason = strategy.try_submit(_take())

    assert reason == "fee_unverified"


# ---------------------------------------------------------------------------
# B4 (F7): the subscribed marker is emitted ONLY on an actual subscription.
# ---------------------------------------------------------------------------


#: Nautilus's `self.log` is its own Rust-backed logger, not interceptable
#: through `caplog`/`capsys`/`capfd` (the same limitation documented at
#: `tests/unit/test_polymarket_us_exec_client.py::test_the_budget_stop_log_
#: line_names_no_dollar_figure_and_no_control_name`). B4's marker is
#: therefore proven through its ONE real side effect instead:
#: `_on_subscribed` is the SOLE place `_d1_readiness_state[station]` is set
#: `True`, and it runs if-and-only-if the marker log line does.


def test_zero_cached_ids_never_marks_the_station_subscribed() -> None:
    state: MutableMapping[str, bool | None] = {}
    strategy, _clock = _build(instruments=(), d1_readiness_state=state)

    strategy.start()

    assert state.get(STATION) is None


def test_a_real_subscription_marks_the_station_subscribed() -> None:
    instrument = _instrument(YES_ID, lower_f=80, upper_f=81)
    state: MutableMapping[str, bool | None] = {}
    strategy, _clock = _build(instruments=(instrument,), d1_readiness_state=state)

    strategy.start()

    assert state[STATION] is True
    assert ("LAX", "2026-09-04", "80_81") in strategy.rung_instruments


# ---------------------------------------------------------------------------
# Order-event alerts -- never log an operator-reserved cap.
# ---------------------------------------------------------------------------


def test_on_order_filled_emits_an_fq_order_filled_alert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instrument = _instrument(YES_ID, lower_f=80, upper_f=81)
    strategy, clock = _build(instruments=(instrument,))
    strategy.start()
    sink = _RecordingAlertSink()
    monkeypatch.setattr(strategy_module, "resolve_alert_sink", lambda: sink)
    order = _limit_order(strategy)
    strategy.cache.add_order(order, position_id=None)

    event = OrderFilled(
        trader_id=order.trader_id,
        strategy_id=order.strategy_id,
        instrument_id=order.instrument_id,
        client_order_id=order.client_order_id,
        venue_order_id=VenueOrderId("V-1"),
        account_id=AccountId("POLYMARKET_US-001"),
        trade_id=TradeId("T-1"),
        position_id=None,
        order_side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        last_qty=Quantity.from_int(1),
        last_px=Price.from_str("0.30"),
        currency=USD,
        commission=Money(0, USD),
        liquidity_side=LiquiditySide.TAKER,
        event_id=UUID4(),
        ts_event=clock.timestamp_ns(),
        ts_init=clock.timestamp_ns(),
    )

    strategy.on_order_filled(event)

    assert len(sink.payloads) == 1
    payload = sink.payloads[0]
    assert payload.event == "FQ_ORDER_FILLED"
    assert payload.severity == "INFO"
    for cap_name in ("MAX_DAILY_BUDGET_USD", "MAX_POSITION_COST_USD"):
        assert cap_name not in payload.detail


def test_on_order_denied_emits_an_fq_order_denied_alert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instrument = _instrument(YES_ID, lower_f=80, upper_f=81)
    strategy, clock = _build(instruments=(instrument,))
    strategy.start()
    sink = _RecordingAlertSink()
    monkeypatch.setattr(strategy_module, "resolve_alert_sink", lambda: sink)
    order = _limit_order(strategy)
    strategy.cache.add_order(order, position_id=None)

    event = OrderDenied(
        trader_id=order.trader_id,
        strategy_id=order.strategy_id,
        instrument_id=order.instrument_id,
        client_order_id=order.client_order_id,
        reason="phase0_permit_absent",
        event_id=UUID4(),
        ts_init=clock.timestamp_ns(),
    )

    strategy.on_order_denied(event)

    assert len(sink.payloads) == 1
    payload = sink.payloads[0]
    assert payload.event == "FQ_ORDER_DENIED"
    assert payload.severity == "WARN"
    assert "reason=phase0_permit_absent" in payload.detail
    for cap_name in ("MAX_DAILY_BUDGET_USD", "MAX_POSITION_COST_USD"):
        assert cap_name not in payload.detail


def test_on_order_rejected_emits_an_fq_order_rejected_alert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instrument = _instrument(YES_ID, lower_f=80, upper_f=81)
    strategy, clock = _build(instruments=(instrument,))
    strategy.start()
    sink = _RecordingAlertSink()
    monkeypatch.setattr(strategy_module, "resolve_alert_sink", lambda: sink)
    order = _limit_order(strategy)
    strategy.cache.add_order(order, position_id=None)

    event = OrderRejected(
        trader_id=order.trader_id,
        strategy_id=order.strategy_id,
        instrument_id=order.instrument_id,
        client_order_id=order.client_order_id,
        account_id=AccountId("POLYMARKET_US-001"),
        reason="venue_rejected",
        event_id=UUID4(),
        ts_event=clock.timestamp_ns(),
        ts_init=clock.timestamp_ns(),
    )

    strategy.on_order_rejected(event)

    assert len(sink.payloads) == 1
    assert sink.payloads[0].event == "FQ_ORDER_REJECTED"
    assert "reason=venue_rejected" in sink.payloads[0].detail


def test_on_order_expired_emits_an_fq_order_expired_alert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instrument = _instrument(YES_ID, lower_f=80, upper_f=81)
    strategy, clock = _build(instruments=(instrument,))
    strategy.start()
    sink = _RecordingAlertSink()
    monkeypatch.setattr(strategy_module, "resolve_alert_sink", lambda: sink)
    order = _limit_order(strategy)
    strategy.cache.add_order(order, position_id=None)

    event = OrderExpired(
        trader_id=order.trader_id,
        strategy_id=order.strategy_id,
        instrument_id=order.instrument_id,
        client_order_id=order.client_order_id,
        venue_order_id=None,
        account_id=None,
        event_id=UUID4(),
        ts_event=clock.timestamp_ns(),
        ts_init=clock.timestamp_ns(),
    )

    strategy.on_order_expired(event)

    assert len(sink.payloads) == 1
    assert sink.payloads[0].event == "FQ_ORDER_EXPIRED"


# ---------------------------------------------------------------------------
# D+1 readiness poll (item 2): native TestClock-driven set_timer.
# ---------------------------------------------------------------------------


def test_zero_ids_then_ids_appear_at_the_second_fire_subscribes_and_marks() -> None:
    instrument = _instrument(YES_ID, lower_f=80, upper_f=81)
    attempts: list[int] = []

    def _resolver() -> tuple[str, ...]:
        attempts.append(1)
        if len(attempts) >= 2:
            return (str(YES_ID),)
        return ()

    state: MutableMapping[str, bool | None] = {}
    strategy, clock = _build(
        instruments=(instrument,),
        initial_ids=(),
        d1_resolver=_resolver,
        d1_readiness_state=state,
    )

    strategy.start()
    assert state.get(STATION) is None
    _advance_by(clock, 5 * 60 * 1_000_000_000)
    assert state.get(STATION) is None
    _advance_by(clock, 5 * 60 * 1_000_000_000)

    assert attempts == [1, 1]
    assert state[STATION] is True
    assert ("LAX", "2026-09-04", "80_81") in strategy.rung_instruments


def test_window_never_resolving_is_terminal_with_one_critical_alert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state: MutableMapping[str, bool | None] = {}
    strategy, clock = _build(instruments=(), d1_resolver=lambda: (), d1_readiness_state=state)
    sink = _RecordingAlertSink()
    monkeypatch.setattr(strategy_module, "resolve_alert_sink", lambda: sink)

    strategy.start()
    _advance_by(clock, 65 * 60 * 1_000_000_000)

    assert state[STATION] is False
    critical = [p for p in sink.payloads if p.event == "FQ_D1_NOT_READY"]
    assert len(critical) == 1
    assert critical[0].severity == "CRITICAL"
    assert STATION in critical[0].detail


def test_mixed_station_case_is_warn_only_never_critical_when_a_sibling_is_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A SECOND station in the SAME boot already subscribed -- this
    station's own window expiry is a per-station WARN, never the family-wide
    CRITICAL terminal (plan §3 S6, test 10's "mixed-station case").
    """
    shared_state: MutableMapping[str, bool | None] = {"LAX": True}
    strategy, _clock = _build(
        station="MIA", instruments=(), d1_resolver=lambda: (), d1_readiness_state=shared_state,
    )
    sink = _RecordingAlertSink()
    monkeypatch.setattr(strategy_module, "resolve_alert_sink", lambda: sink)

    strategy._on_d1_window_expired()  # direct unit test of the terminal path

    assert shared_state["MIA"] is False
    assert shared_state["LAX"] is True  # untouched
    assert sink.payloads == [], "a per-station WARN must never also alert CRITICAL"
