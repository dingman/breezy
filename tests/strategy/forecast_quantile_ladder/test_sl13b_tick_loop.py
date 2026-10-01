"""SL-13 fix-first review item 2 -- ``ForecastQuantileLadderStrategy``'s live
tick loop (``on_order_book_depth``/``on_quote_tick``), mirroring
``ContinuousRungHoldStrategy``'s own hunt tick (``continuous_strategy.py``
~L1507-1542).

Harness reuses ``tests.unit.test_current_rung_hold_strategy``'s
``_instrument``/``_pad_depth_side``-shaped fixture builders (STATION="LAX",
CLIMATE_DAY=2026-09-04, LAX_STD_OFFSET_HOURS=-8.0) so ``on_start``'s
weather-bucket-facts resolution runs unmodified. ``_NOW_NS`` is 24h before
that file's own ``WINDOW_OPEN_NS`` -- same 12:00 LST instant, one day
EARLIER -- so ``local_standard_date(_NOW_NS, -8.0) + 1 day == CLIMATE_DAY``:
the D+1 gate is satisfied for CLIMATE_DAY instruments and refuses both a D0
(CLIMATE_DAY - 1) and a D+2 (CLIMATE_DAY + 1) one.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

from nautilus_trader.common.component import TestClock
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import BookOrder, OrderBookDepth10, QuoteTick
from nautilus_trader.model.enums import AssetClass, OrderSide
from nautilus_trader.model.identifiers import InstrumentId, TraderId
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.portfolio import Portfolio
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.adapters.polymarket_us.symbology import sibling_instrument_id
from breezy.domain.weather_bucket_facts import (
    CLIMATE_DAY_KEY,
    MEASURE_KEY,
    SETTLEMENT_STATION_KEY,
    STRIKE_LOWER_F_KEY,
    STRIKE_UPPER_F_KEY,
    WEATHER_FACTS_STATUS_KEY,
    WEATHER_FACTS_STATUS_KNOWN,
)
from breezy.strategy.forecast_quantile_ladder.bounds import RungBounds
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import CalibrationArtefact
from breezy.strategy.forecast_quantile_ladder.config import ForecastQuantileLadderConfig
from breezy.strategy.forecast_quantile_ladder.strategy import (
    ForecastQuantileLadderStrategy,
    ShadowDecisionLogLine,
    SupportsExpiresAtNs,
)
from breezy.strategy.ladder_ev.config import LadderEvConfig
from breezy.strategy.ladder_ev.forecast_state import NBP_QUANTILE_VARIABLES
from breezy.strategy.ladder_ev.forecast_subscriber import ForecastQuantileStateActor
from breezy.strategy.ladder_ev.quantile_density import CdfMethod, EmosParams
from tests.unit.test_current_rung_hold_strategy import (
    CLIMATE_DAY,
    INTERIOR_ID,
    STATION,
    WINDOW_OPEN_NS,
    _instrument,
)

_NOW_NS = WINDOW_OPEN_NS - 24 * 3_600 * 10**9
_NO_INTERIOR_ID = sibling_instrument_id(INTERIOR_ID)
_DEPTH10_LEVELS = 10
#: LAX_STD_OFFSET_HOURS per the module docstring -- the actor's own
#: constructor validation (SL-13e) needs an offset per served station.
_STD_UTC_OFFSET_HOURS = {STATION: -8.0}


def _config() -> ForecastQuantileLadderConfig:
    return ForecastQuantileLadderConfig(
        stations=(STATION,),
        calibration_artefact_path="/tmp/unused.json",
        calibration_artefact_sha256="a" * 64,
    )


def _config_with_shadow_only(shadow_only: bool) -> ForecastQuantileLadderConfig:
    return ForecastQuantileLadderConfig(
        stations=(STATION,),
        calibration_artefact_path="/tmp/unused.json",
        calibration_artefact_sha256="a" * 64,
        shadow_only=shadow_only,
    )


def _artefact() -> CalibrationArtefact:
    return CalibrationArtefact(
        sha256="a" * 64, cdf_method=CdfMethod.NORMAL, emos=EmosParams(a=0.0, gamma=0.0, delta=1.0),
    )


def _bounds_provider_factory(
    *, p_hat: float, p_lower: float, p_upper: float,
) -> Callable[..., RungBounds]:
    def _provider(*, cdf: Any, ladder: Any, rung_id: str) -> RungBounds:
        del cdf, ladder, rung_id
        return RungBounds(p_hat=p_hat, p_lower=p_lower, p_upper=p_upper)

    return _provider


def _push_vector(actor: ForecastQuantileStateActor, *, station: str, now_ns: int) -> None:
    """A complete, already-visible 7-variable NBP vector -- see
    ``ForecastQuantileState.push``/``value_at``.

    ``climate_day=CLIMATE_DAY`` matches every ``Take``-producing fixture
    instrument's own settlement day in this file (``_instrument``'s default);
    the D0/D+2 tests never reach the vector-day check at all (they refuse
    earlier, at ``decision.evaluate``'s D+1 gate)."""
    state = actor.state_for(station)
    for variable in NBP_QUANTILE_VARIABLES:
        state.push(
            variable=variable,
            value_f=80.0,
            available_at_ns=now_ns - 1,
            cycle_runtime_ns=now_ns - 1,
            climate_day=CLIMATE_DAY,
        )


def _facts_info(
    *, station: str, climate_day: dt.date, lower_f: int | None, upper_f: int | None,
) -> dict[str, object]:
    return {
        WEATHER_FACTS_STATUS_KEY: WEATHER_FACTS_STATUS_KNOWN,
        SETTLEMENT_STATION_KEY: station,
        CLIMATE_DAY_KEY: climate_day.isoformat(),
        MEASURE_KEY: "high",
        STRIKE_LOWER_F_KEY: lower_f,
        STRIKE_UPPER_F_KEY: upper_f,
    }


def _instrument_on(
    instrument_id: InstrumentId, *, climate_day: dt.date, lower_f: int = 80, upper_f: int = 81,
) -> BinaryOption:
    increment = Price.from_str("0.01")
    size_increment = Quantity.from_str("1")
    return BinaryOption(
        instrument_id=instrument_id,
        raw_symbol=instrument_id.symbol,
        outcome="Yes",
        description=f"{STATION} daily high",
        asset_class=AssetClass.ALTERNATIVE,
        currency=USD,
        price_precision=increment.precision,
        price_increment=increment,
        size_precision=size_increment.precision,
        size_increment=size_increment,
        activation_ns=0,
        expiration_ns=200 * 3_600_000_000_000,
        max_quantity=None,
        min_quantity=Quantity.from_int(1),
        maker_fee=Decimal("0.06"),
        taker_fee=Decimal("0.06"),
        ts_event=0,
        ts_init=0,
        info=_facts_info(station=STATION, climate_day=climate_day, lower_f=lower_f, upper_f=upper_f),
    )


def _pad_depth_side(side: OrderSide, levels: tuple[tuple[str, int], ...]) -> list[BookOrder]:
    filler = BookOrder(side, Price(0, 2), Quantity(0, 0), 0)
    orders = [BookOrder(side, Price.from_str(px), Quantity(size, 0), 0) for px, size in levels]
    while len(orders) < _DEPTH10_LEVELS:
        orders.append(filler)
    return orders


def _depth(
    instrument_id: InstrumentId,
    *,
    bids: tuple[tuple[str, int], ...] = (),
    asks: tuple[tuple[str, int], ...] = (),
    ts_event: int,
) -> OrderBookDepth10:
    bid_orders = _pad_depth_side(OrderSide.BUY, bids)
    ask_orders = _pad_depth_side(OrderSide.SELL, asks)
    return OrderBookDepth10(
        instrument_id=instrument_id,
        bids=bid_orders,
        asks=ask_orders,
        bid_counts=[1 if o.size.as_double() > 0 else 0 for o in bid_orders],
        ask_counts=[1 if o.size.as_double() > 0 else 0 for o in ask_orders],
        flags=0,
        sequence=0,
        ts_event=ts_event,
        ts_init=ts_event,
    )


@dataclass(frozen=True, slots=True)
class _FakePermit:
    expires_at_ns: int


@dataclass(slots=True)
class _MutablePermit:
    expires_at_ns: int


def _open_permit() -> _FakePermit:
    return _FakePermit(expires_at_ns=_NOW_NS + 10 * 3_600_000_000_000)


def _build_registered(
    *,
    instruments: tuple[BinaryOption, ...],
    bounds_provider: Callable[..., RungBounds],
    order_submission_permit: SupportsExpiresAtNs | None = None,
    submit_veto: Callable[[], str | None] | None = None,
    shadow_only: bool = False,
    shadow_decision_sink: Callable[[ShadowDecisionLogLine], None] | None = None,
) -> ForecastQuantileLadderStrategy:
    quantile_actor = ForecastQuantileStateActor(
        stations=(STATION,), std_utc_offset_hours=_STD_UTC_OFFSET_HOURS,
    )
    clock = TestClock()
    clock.set_time(_NOW_NS)
    msgbus = TestComponentStubs.msgbus()
    cache = TestComponentStubs.cache()
    for instrument in instruments:
        cache.add_instrument(instrument)
    quantile_actor.register_base(
        portfolio=TestComponentStubs.portfolio(), msgbus=msgbus, cache=cache, clock=clock,
    )
    quantile_actor.start()
    _push_vector(quantile_actor, station=STATION, now_ns=_NOW_NS)

    strategy = ForecastQuantileLadderStrategy(
        _config_with_shadow_only(shadow_only),
        quantile_actor=quantile_actor,
        artefact=_artefact(),
        ladder_cfg=LadderEvConfig(),
        bounds_provider=bounds_provider,
        order_submission_permit=order_submission_permit,
        submit_veto=submit_veto,
        instrument_ids=tuple(str(i.id) for i in instruments),
        shadow_decision_sink=shadow_decision_sink,
    )
    portfolio = Portfolio(msgbus=msgbus, cache=cache, clock=clock)
    strategy.register(
        trader_id=TraderId("BACKTEST-001"), portfolio=portfolio, msgbus=msgbus, cache=cache, clock=clock,
    )
    strategy.start()
    return strategy


_CLEAR_TAKE_YES = _bounds_provider_factory(p_hat=0.9, p_lower=0.9, p_upper=0.95)
_CLEAR_TAKE_NO = _bounds_provider_factory(p_hat=0.05, p_lower=0.02, p_upper=0.05)


def test_a_depth_update_produces_exactly_one_take_per_rung_and_side() -> None:
    records: list[ShadowDecisionLogLine] = []
    strategy = _build_registered(
        instruments=(_instrument(INTERIOR_ID, lower_f=80, upper_f=81),),
        bounds_provider=_CLEAR_TAKE_YES,
        order_submission_permit=_open_permit(),
        shadow_decision_sink=records.append,
    )
    strategy.submit_order = MagicMock()

    strategy.on_order_book_depth(_depth(INTERIOR_ID, asks=(("0.10", 5),), ts_event=_NOW_NS))
    # A second depth update on the SAME rung/side must NOT produce a second Take.
    strategy.on_order_book_depth(_depth(INTERIOR_ID, asks=(("0.10", 5),), ts_event=_NOW_NS + 1))

    takes = [d for d in records if d["kind"] == "Take"]
    assert len(takes) == 1
    strategy.submit_order.assert_called_once()


def test_a_no_side_decision_uses_the_no_instruments_own_book() -> None:
    records: list[ShadowDecisionLogLine] = []
    strategy = _build_registered(
        # The NO instrument itself must ALSO be resolvable from `self.cache`
        # for `_maybe_submit` to build a native order off it -- `on_start`
        # only iterates `instrument_ids` looking for YES ids (the NO id is
        # DERIVED, never separately configured), but every id passed to
        # `_build_registered`'s `instruments` is added to the cache, which
        # is the surface `_maybe_submit` actually reads.
        instruments=(
            _instrument(INTERIOR_ID, lower_f=80, upper_f=81),
            _instrument(_NO_INTERIOR_ID, lower_f=80, upper_f=81),
        ),
        bounds_provider=_CLEAR_TAKE_NO,
        order_submission_permit=_open_permit(),
        shadow_decision_sink=records.append,
    )
    strategy.submit_order = MagicMock()

    # The YES book never fires (no ask on YES) -- only the NO instrument's
    # own depth update must drive a NO decision.
    strategy.on_order_book_depth(_depth(_NO_INTERIOR_ID, asks=(("0.05", 5),), ts_event=_NOW_NS))

    takes = [d for d in records if d["kind"] == "Take"]
    assert len(takes) == 1
    assert takes[0]["side"] == "no"
    assert takes[0]["instrument_id"] == str(_NO_INTERIOR_ID)
    strategy.submit_order.assert_called_once()
    order = strategy.submit_order.call_args.args[0]
    assert str(order.instrument_id) == str(_NO_INTERIOR_ID)


def test_a_book_with_no_populated_levels_is_a_logged_skip_never_an_exception() -> None:
    strategy = _build_registered(
        instruments=(_instrument(INTERIOR_ID, lower_f=80, upper_f=81),),
        bounds_provider=_CLEAR_TAKE_YES,
        order_submission_permit=_open_permit(),
    )
    strategy.submit_order = MagicMock()

    # Every level padded (size 0) on both sides -- best_order returns None
    # for both; the handler must not raise.
    strategy.on_order_book_depth(_depth(INTERIOR_ID, asks=(), bids=(), ts_event=_NOW_NS))

    strategy.submit_order.assert_not_called()
    assert not hasattr(strategy, "shadow_decisions")


def test_without_a_permit_submit_order_is_never_called() -> None:
    records: list[ShadowDecisionLogLine] = []
    strategy = _build_registered(
        instruments=(_instrument(INTERIOR_ID, lower_f=80, upper_f=81),),
        bounds_provider=_CLEAR_TAKE_YES,
        order_submission_permit=None,
        shadow_decision_sink=records.append,
    )
    strategy.submit_order = MagicMock()

    strategy.on_order_book_depth(_depth(INTERIOR_ID, asks=(("0.10", 5),), ts_event=_NOW_NS))

    strategy.submit_order.assert_not_called()
    takes = [d for d in records if d["kind"] == "NotExecutable"]
    assert takes  # phase-0 absent permit -> NotExecutable, never latched


def test_shadow_only_true_never_reaches_submit_order_even_when_guards_clear() -> None:
    records: list[ShadowDecisionLogLine] = []
    strategy = _build_registered(
        instruments=(_instrument(INTERIOR_ID, lower_f=80, upper_f=81),),
        bounds_provider=_CLEAR_TAKE_YES,
        order_submission_permit=_open_permit(),
        shadow_only=True,
        shadow_decision_sink=records.append,
    )
    strategy.submit_order = MagicMock()

    strategy.on_order_book_depth(_depth(INTERIOR_ID, asks=(("0.10", 5),), ts_event=_NOW_NS))

    assert [d["kind"] for d in records] == ["Take"]
    strategy.submit_order.assert_not_called()


def test_ticks_before_and_inside_the_permit_window_get_different_outcomes() -> None:
    records: list[ShadowDecisionLogLine] = []
    permit = _MutablePermit(expires_at_ns=_NOW_NS)
    strategy = _build_registered(
        instruments=(_instrument(INTERIOR_ID, lower_f=80, upper_f=81),),
        bounds_provider=_CLEAR_TAKE_YES,
        order_submission_permit=permit,
        shadow_decision_sink=records.append,
    )
    strategy.submit_order = MagicMock()

    before = _NOW_NS
    inside = _NOW_NS + 1
    strategy.on_order_book_depth(_depth(INTERIOR_ID, asks=(("0.10", 5),), ts_event=before))
    permit.expires_at_ns = inside + 1
    strategy.on_order_book_depth(_depth(INTERIOR_ID, asks=(("0.10", 5),), ts_event=inside))

    # FQ-S11: a Take that reaches `_maybe_submit` with a clear guard chain
    # now also records its `try_submit` outcome through the same sink.
    assert [d["kind"] for d in records] == ["NotExecutable", "Take", "TrySubmit"]


def test_a_d0_instrument_is_refused_never_taken() -> None:
    records: list[ShadowDecisionLogLine] = []
    d0_id = InstrumentId.from_str("d0-lax-80-81.POLYMARKET_US")
    strategy = _build_registered(
        instruments=(_instrument_on(d0_id, climate_day=CLIMATE_DAY - dt.timedelta(days=1)),),
        bounds_provider=_CLEAR_TAKE_YES,
        order_submission_permit=_open_permit(),
        shadow_decision_sink=records.append,
    )
    strategy.submit_order = MagicMock()

    strategy.on_order_book_depth(_depth(d0_id, asks=(("0.10", 5),), ts_event=_NOW_NS))

    strategy.submit_order.assert_not_called()
    assert [d["kind"] for d in records] == ["NotDPlus1"]


def test_a_d_plus_2_instrument_is_refused_never_taken() -> None:
    records: list[ShadowDecisionLogLine] = []
    d2_id = InstrumentId.from_str("dplus2-lax-80-81.POLYMARKET_US")
    strategy = _build_registered(
        instruments=(_instrument_on(d2_id, climate_day=CLIMATE_DAY + dt.timedelta(days=1)),),
        bounds_provider=_CLEAR_TAKE_YES,
        order_submission_permit=_open_permit(),
        shadow_decision_sink=records.append,
    )
    strategy.submit_order = MagicMock()

    strategy.on_order_book_depth(_depth(d2_id, asks=(("0.10", 5),), ts_event=_NOW_NS))

    strategy.submit_order.assert_not_called()
    assert [d["kind"] for d in records] == ["NotDPlus1"]


def test_on_quote_tick_also_drives_a_take() -> None:
    strategy = _build_registered(
        instruments=(_instrument(INTERIOR_ID, lower_f=80, upper_f=81),),
        bounds_provider=_CLEAR_TAKE_YES,
        order_submission_permit=_open_permit(),
    )
    strategy.submit_order = MagicMock()
    tick = QuoteTick(
        instrument_id=INTERIOR_ID,
        bid_price=Price.from_str("0.05"),
        ask_price=Price.from_str("0.10"),
        bid_size=Quantity.from_int(5),
        ask_size=Quantity.from_int(5),
        ts_event=_NOW_NS,
        ts_init=_NOW_NS,
    )

    strategy.on_quote_tick(tick)

    strategy.submit_order.assert_called_once()
