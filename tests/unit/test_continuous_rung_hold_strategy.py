"""Phase 0 tests for ``ContinuousRungHoldStrategy``."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.common.component import TestClock
from nautilus_trader.model.data import BookOrder, OrderBookDepth10
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import TraderId
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.portfolio import Portfolio
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.adapters.polymarket_us.parsing import DEPTH10_LEVELS
from breezy.domain.station_observation import StationObservation
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import open_submit_intent_latch
from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
from breezy.strategy.current_rung_hold.continuous_strategy import (
    ContinuousRungHoldStrategy,
    Phase0PermitForbiddenError,
)
from breezy.strategy.current_rung_hold.offer_tape import OfferTape
from breezy.strategy.current_rung_hold.trial_day_latch import (
    CONTINUOUS_TRIAL_KEY_PREFIX,
    TrialDayLatch,
    open_trial_day_latch,
)
from breezy.strategy.weather_common.refusals import RefusalAlerter
from tests.unit.test_current_rung_hold_strategy import (
    _WAIT_VOCABULARY,
    CLIMATE_DAY,
    ICAO,
    INTERIOR_ID,
    NS_PER_MIN,
    STATION,
    WINDOW_OPEN_NS,
    _instrument,
    _observation,
    _quote,
    _RecordingSink,
    _SpyClock,
)


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "state.db"


@pytest.fixture
def interior_instrument() -> BinaryOption:
    return _instrument(INTERIOR_ID, lower_f=86, upper_f=87)


@contextmanager
def _open_cont_latch(store_path: Path) -> Iterator[TrialDayLatch]:
    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
        yield open_trial_day_latch(intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)


def _cont_latch_factory(
    store_path: Path,
) -> Callable[[], AbstractContextManager[TrialDayLatch]]:
    return lambda: _open_cont_latch(store_path)


def _register(
    *,
    store_path: Path,
    instruments: tuple[BinaryOption, ...],
    clock: TestClock | None = None,
    offer_tape: OfferTape | None = None,
) -> ContinuousRungHoldStrategy:
    cfg = CurrentRungHoldConfig(
        instrument_ids=tuple(instrument.id for instrument in instruments),
    )
    strategy = ContinuousRungHoldStrategy(
        cfg,
        trial_day_latch_factory=_cont_latch_factory(store_path),
        offer_tape=offer_tape,
    )
    used_clock = TestClock() if clock is None else clock
    used_clock.set_time(WINDOW_OPEN_NS)
    msgbus = TestComponentStubs.msgbus()
    cache = TestComponentStubs.cache()
    for instrument in instruments:
        cache.add_instrument(instrument)
    portfolio = Portfolio(msgbus=msgbus, cache=cache, clock=used_clock)
    strategy.register(
        trader_id=TraderId("BACKTEST-001"),
        portfolio=portfolio,
        msgbus=msgbus,
        cache=cache,
        clock=used_clock,
    )
    return strategy


def _register_and_start(
    *,
    store_path: Path,
    instruments: tuple[BinaryOption, ...],
    clock: TestClock | None = None,
    offer_tape: OfferTape | None = None,
) -> ContinuousRungHoldStrategy:
    strategy = _register(
        store_path=store_path, instruments=instruments, clock=clock, offer_tape=offer_tape,
    )
    strategy.start()
    return strategy


def _pad(
    side: OrderSide, levels: tuple[tuple[str, int], ...],
) -> tuple[list[BookOrder], list[int]]:
    """Ten-level Depth10 side, padded with the size-0 Arrow filler (matches
    `parse_order_book_depth10`'s own padding at the instrument's precision)."""
    filler = BookOrder(side, Price(0, 2), Quantity(0, 0), 0)
    orders = [BookOrder(side, Price.from_str(px), Quantity(size, 0), 0) for px, size in levels]
    counts = [1] * len(orders)
    while len(orders) < DEPTH10_LEVELS:
        orders.append(filler)
        counts.append(0)
    return orders, counts


def _depth(
    instrument_id: object,
    *,
    bids: tuple[tuple[str, int], ...],
    asks: tuple[tuple[str, int], ...],
    ts_event: int,
) -> OrderBookDepth10:
    bid_orders, bid_counts = _pad(OrderSide.BUY, bids)
    ask_orders, ask_counts = _pad(OrderSide.SELL, asks)
    return OrderBookDepth10(
        instrument_id=instrument_id,
        bids=bid_orders,
        asks=ask_orders,
        bid_counts=bid_counts,
        ask_counts=ask_counts,
        flags=0,
        sequence=0,
        ts_event=ts_event,
        ts_init=ts_event,
    )


def test_refuse_does_not_write_trial(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    # ask=0.80: executable but p_hold_lower 0.6982 does not clear BE.
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.80", ts_event=WINDOW_OPEN_NS))
    assert strategy._latch is not None
    assert strategy._latch.is_consumed(STATION, CLIMATE_DAY.isoformat()) is False
    assert strategy.refusals.count("edge_below_break_even") == 1
    assert any(rec.reason == "edge_below_break_even" for rec in strategy.offer_tape.records())


def test_illegal_cell_counted_once_visible_on_stop(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    # 87F METAR → m_code = 1 on interior [86, 87] → illegal_cell.
    strategy.on_data(_observation(temp_c_tenths=306, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))
    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + NS_PER_MIN),
    )
    assert strategy.refusals.count("illegal_cell") == 1
    assert strategy._latch is not None
    assert strategy._latch.is_consumed(STATION, CLIMATE_DAY.isoformat()) is False
    message = strategy._illegal_cell_snapshot_message()
    assert message == "continuous_rung_hold illegal_cell once-count: 1"
    strategy.stop()
    assert "illegal_cell once-count: 1" in strategy._illegal_cell_snapshot_message()


def test_inflight_commits_before_arm(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    order: list[str] = []
    assert strategy._latch is not None
    orig_set = strategy._latch.set_inflight
    orig_maybe = strategy._maybe_submit

    def spy_set(*args: object, **kwargs: object) -> None:
        order.append("inflight")
        orig_set(*args, **kwargs)
        assert strategy._latch is not None
        assert strategy._latch.is_inflight(STATION, CLIMATE_DAY.isoformat()) is True

    def spy_maybe(*args: object, **kwargs: object) -> None:
        order.append("maybe_submit")
        assert strategy._latch is not None
        assert strategy._latch.is_inflight(STATION, CLIMATE_DAY.isoformat()) is True
        return orig_maybe(*args, **kwargs)

    strategy._latch.set_inflight = spy_set  # type: ignore[method-assign]
    strategy._maybe_submit = spy_maybe  # type: ignore[method-assign]
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))
    assert order == ["inflight", "maybe_submit"]
    assert strategy._latch.is_consumed(STATION, CLIMATE_DAY.isoformat()) is False


def test_on_data_skips_stale_or_future_last_tick(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    obs = _observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1)
    future = _quote(
        INTERIOR_ID, ask="0.40", ts_event=obs.received_at_ns + NS_PER_MIN,
    )
    strategy.cache.add_quote_tick(future)
    strategy.on_data(obs)
    assert len(strategy.offer_tape) == 0

    stale = _quote(
        INTERIOR_ID,
        ask="0.40",
        ts_event=obs.received_at_ns - 51 * NS_PER_MIN,
    )
    strategy.cache.add_quote_tick(stale)
    strategy.on_data(obs)
    assert len(strategy.offer_tape) == 0

    fresh = _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS)
    strategy.cache.add_quote_tick(fresh)
    later = StationObservation(
        station=ICAO,
        observed_at_ns=WINDOW_OPEN_NS - 1,
        received_at_ns=WINDOW_OPEN_NS,
        temp_c_tenths=300,
        precision_c_tenths=5,
        is_metar=True,
        source_channel="iem_asos_metar",
        assumed_publication_lag_ns=1,
    )
    strategy.on_data(later)
    assert len(strategy.offer_tape) == 1
    assert strategy.offer_tape.records()[0].trigger == "on_data"


def test_timer_calls_empty(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    clock = _SpyClock()
    strategy = _register_and_start(
        store_path=store_path, instruments=(interior_instrument,), clock=clock,
    )
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))
    assert clock.timer_calls == []
    assert clock.alert_calls == []


def test_constructing_with_a_non_none_permit_raises_phase0_error(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """Phase 0 seal: `ContinuousRungHoldStrategy.__init__` refuses a
    non-None `order_submission_permit`, naming Phase 0 in the error."""
    cfg = CurrentRungHoldConfig(instrument_ids=(interior_instrument.id,))
    with pytest.raises(Phase0PermitForbiddenError, match="Phase 0"):
        ContinuousRungHoldStrategy(
            cfg,
            trial_day_latch_factory=_cont_latch_factory(store_path),
            order_submission_permit=object(),  # type: ignore[arg-type]
        )


def test_a_take_decision_with_permit_none_never_calls_submit_order(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """With `order_submission_permit=None`, a Take-equivalent decision (ask
    clears break-even) must leave `submit_order` uncalled -- asserted
    directly on the spy, never via an `... or ...` fallback that would pass
    vacuously."""
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    assert strategy._order_submission_permit is None
    submitted: list[object] = []
    strategy.submit_order = submitted.append
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    # ask=0.40 clears break-even (same fixture as test_inflight_commits_before_arm).
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))
    assert submitted == []


def test_offer_tape_records_eligible_nonfills_and_is_bounded(
    store_path: Path, interior_instrument: BinaryOption, tmp_path: Path,
) -> None:
    tape = OfferTape(tmp_path / "offer.jsonl", maxlen=3)
    strategy = _register_and_start(
        store_path=store_path, instruments=(interior_instrument,), offer_tape=tape,
    )
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    for i in range(10):
        strategy.on_quote_tick(
            _quote(
                INTERIOR_ID,
                ask="0.80",
                ts_event=WINDOW_OPEN_NS + i * NS_PER_MIN,
            ),
        )
    assert len(tape) == 3
    assert tape.maxlen == 3
    assert all(rec.reason == "edge_below_break_even" for rec in tape.records())
    lines = (tmp_path / "offer.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 10
    assert strategy._latch is not None
    assert strategy._latch.is_consumed(STATION, CLIMATE_DAY.isoformat()) is False
    assert Decimal("0.80") == Decimal(tape.records()[-1].ask)


def test_an_unwritable_offer_tape_jsonl_path_never_raises_from_hunt_tick(
    store_path: Path, interior_instrument: BinaryOption, tmp_path: Path,
) -> None:
    """A disk error on `OfferTape.append`'s optional JSONL write must never
    propagate out of `on_quote_tick`/`on_data` -- the in-memory deque still
    records regardless."""
    unwritable_dir = tmp_path / "unwritable"
    unwritable_dir.mkdir(mode=0o500)
    try:
        tape = OfferTape(unwritable_dir / "offer.jsonl")
        strategy = _register_and_start(
            store_path=store_path, instruments=(interior_instrument,), offer_tape=tape,
        )
        strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
        strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.80", ts_event=WINDOW_OPEN_NS))
        assert len(tape) == 1
        assert not (unwritable_dir / "offer.jsonl").exists()
    finally:
        unwritable_dir.chmod(0o700)


# ---------------------------------------------------------------------------
# Phase 0b: hunt on Depth10 asks (shadow, permit None)
# ---------------------------------------------------------------------------


def test_on_start_subscribes_order_book_depth_for_each_resolved_instrument(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    strategy = _register(store_path=store_path, instruments=(interior_instrument,))
    subscribed: list[object] = []
    strategy.subscribe_order_book_depth = subscribed.append  # type: ignore[method-assign]

    strategy.on_start()

    assert subscribed == [interior_instrument.id]


def test_on_stop_unsubscribes_order_book_depth(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    unsubscribed: list[object] = []
    strategy.unsubscribe_order_book_depth = unsubscribed.append  # type: ignore[method-assign]

    strategy.stop()

    assert unsubscribed == [interior_instrument.id]


def test_a_one_sided_depth10_ask_drives_the_same_decision_as_the_equivalent_quote_tick(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """A recorded one-sided window (bids all size-0 pad, asks populated) still
    reaches the SAME hunt path a two-sided QuoteTick would, via
    `on_order_book_depth` -> `best_order(depth.asks)`."""
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    depth = _depth(INTERIOR_ID, bids=(), asks=(("0.40", 10),), ts_event=WINDOW_OPEN_NS)

    strategy.on_order_book_depth(depth)

    # Phase 0 (`order_submission_permit=None`) clears IN_FLIGHT synchronously
    # inside `_hunt_tick` itself (see `test_a_take_decision_with_permit_none_
    # never_calls_submit_order`), so the durable proof of "same decision
    # path as a QuoteTick" is the offer-tape record, not a post-hoc
    # `is_inflight` read.
    assert len(strategy.offer_tape) == 1
    record = strategy.offer_tape.records()[0]
    assert record.reason == "taken"
    assert record.source == "depth"


def test_a_two_sided_frame_delivered_as_both_quote_and_depth_evaluates_once(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """The SAME WS frame yields a QuoteTick and a Depth10 with identical
    (instrument_id, ts_event, ask, size) -- whichever arrives second must be
    a no-op, not a second offer-tape entry. `ask=0.80` is a REFUSE decision
    (`edge_below_break_even`), which does not set inflight, so only de-dupe
    -- not the inflight guard -- can be responsible for a single record."""
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    quote = _quote(INTERIOR_ID, ask="0.80", ts_event=WINDOW_OPEN_NS)
    depth = _depth(
        INTERIOR_ID, bids=(("0.01", 10),), asks=(("0.80", 10),), ts_event=WINDOW_OPEN_NS,
    )

    strategy.on_quote_tick(quote)
    strategy.on_order_book_depth(depth)

    assert len(strategy.offer_tape) == 1
    assert strategy.offer_tape.records()[0].reason == "edge_below_break_even"


def _order_denied(strategy: ContinuousRungHoldStrategy, *, reason: str) -> Any:
    from nautilus_trader.core.uuid import UUID4
    from nautilus_trader.model.events import OrderDenied
    from nautilus_trader.model.identifiers import ClientOrderId

    return OrderDenied(
        trader_id=strategy.trader_id,
        strategy_id=strategy.id,
        instrument_id=INTERIOR_ID,
        client_order_id=ClientOrderId("O-RACE-TEST-1"),
        reason=reason,
        event_id=UUID4(),
        ts_init=WINDOW_OPEN_NS,
    )


def test_on_order_denied_with_the_wait_reason_clears_inflight(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """SAFETY C1 (plan rev 6.1): a WAIT-class deny (the pre-arm re-check
    inside ``_submit_order``) frees the station-day to re-hunt on a later
    tick -- it is not a refusal and must not leave IN_FLIGHT stuck."""
    from breezy.adapters.polymarket_us.exec import submit_chain

    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    assert strategy._latch is not None
    strategy._latch.set_inflight(STATION, CLIMATE_DAY.isoformat())
    assert strategy._latch.is_inflight(STATION, CLIMATE_DAY.isoformat()) is True

    strategy.on_order_denied(
        _order_denied(strategy, reason=submit_chain.OPEN_INTENT_WAIT_REASON),
    )

    assert strategy._latch.is_inflight(STATION, CLIMATE_DAY.isoformat()) is False


def test_on_order_denied_with_any_other_reason_leaves_inflight_set(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """A standing refusal (not the WAIT sentinel) is NOT cleared here -- a
    narrower match would risk silently waving off a real refusal."""
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    assert strategy._latch is not None
    strategy._latch.set_inflight(STATION, CLIMATE_DAY.isoformat())

    strategy.on_order_denied(_order_denied(strategy, reason="some other denial reason"))

    assert strategy._latch.is_inflight(STATION, CLIMATE_DAY.isoformat()) is True


def _arm_and_release_stale_intent(store_path: Path) -> None:
    """Simulate a crash-left OPEN singleton: arm it, then release the flock
    without retiring -- exactly the durable shape a crash leaves, and
    exactly what `_register_and_start`'s own factory will re-open next."""
    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as latch:
        latch.arm("a" * 64, now_ns=1)


def test_hunt_tick_waits_while_the_account_wide_intent_is_open(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """Resolution B (plan rev 6.1): a stale/crash-left OPEN singleton is seen
    by `_hunt_tick` BEFORE `set_inflight`/`_maybe_submit` -- no task hop, no
    offer-tape entry, no IN_FLIGHT ever set, counted as a WAIT diagnostic."""
    _arm_and_release_stale_intent(store_path)
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    calls: list[str] = []
    orig_maybe = strategy._maybe_submit

    def spy_maybe(*args: object, **kwargs: object) -> None:
        calls.append("maybe_submit")
        return orig_maybe(*args, **kwargs)  # type: ignore[return-value]

    strategy._maybe_submit = spy_maybe  # type: ignore[method-assign]

    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))

    assert calls == []
    assert strategy._latch is not None
    assert strategy._latch.is_inflight(STATION, CLIMATE_DAY.isoformat()) is False
    assert strategy._latch.is_consumed(STATION, CLIMATE_DAY.isoformat()) is False
    assert strategy.diagnostics.count("open_intent_wait") == 1
    assert len(strategy.offer_tape) == 0


def test_repeated_ticks_while_open_never_loop_and_the_alert_is_throttled(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """No hunt -> WAIT-deny -> clear -> hunt loop: with the Resolution B
    pre-filter in place, repeated ticks while the singleton stays OPEN never
    reach `_maybe_submit`/IN_FLIGHT at all, and the diagnostics alert
    renotifies on the existing `AlertState` cadence, not on every tick."""
    _arm_and_release_stale_intent(store_path)
    strategy = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
    calls: list[str] = []
    orig_maybe = strategy._maybe_submit

    def spy_maybe(*args: object, **kwargs: object) -> None:
        calls.append("maybe_submit")
        return orig_maybe(*args, **kwargs)  # type: ignore[return-value]

    strategy._maybe_submit = spy_maybe  # type: ignore[method-assign]
    sink = _RecordingSink()
    strategy.diagnostics_alerter = RefusalAlerter(
        strategy.diagnostics, site=str(strategy.id), sink=sink, **_WAIT_VOCABULARY,
    )
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS))
    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + NS_PER_MIN),
    )

    assert calls == []
    assert strategy.diagnostics.count("open_intent_wait") == 2
    assert len(sink.payloads) == 1
    assert strategy._latch is not None
    assert strategy._latch.is_inflight(STATION, CLIMATE_DAY.isoformat()) is False
