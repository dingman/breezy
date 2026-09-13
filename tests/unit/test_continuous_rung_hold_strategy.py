"""Phase 0 tests for ``ContinuousRungHoldStrategy``."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.common.component import TestClock
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import BookOrder, OrderBookDepth10
from nautilus_trader.model.enums import LiquiditySide, OmsType, OrderSide
from nautilus_trader.model.events import OrderFilled
from nautilus_trader.model.identifiers import (
    AccountId,
    ClientOrderId,
    PositionId,
    TradeId,
    TraderId,
    VenueOrderId,
)
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.model.position import Position
from nautilus_trader.portfolio import Portfolio
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.adapters.polymarket_us.parsing import DEPTH10_LEVELS
from breezy.domain.station_observation import StationObservation
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import CURRENT_INTENT_KEY, open_submit_intent_latch
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
    position_evidence_reader: Any | None = None,
) -> ContinuousRungHoldStrategy:
    cfg = CurrentRungHoldConfig(
        instrument_ids=tuple(instrument.id for instrument in instruments),
    )
    strategy = ContinuousRungHoldStrategy(
        cfg,
        trial_day_latch_factory=_cont_latch_factory(store_path),
        offer_tape=offer_tape,
        position_evidence_reader=position_evidence_reader,
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
    position_evidence_reader: Any | None = None,
) -> ContinuousRungHoldStrategy:
    strategy = _register(
        store_path=store_path,
        instruments=instruments,
        clock=clock,
        offer_tape=offer_tape,
        position_evidence_reader=position_evidence_reader,
    )
    strategy.start()
    return strategy


#: A `position_evidence_reader` that always permits arming, flat on the
#: shared `INTERIOR_ID` fixture slug -- the "green" default most fill-
#: wiring/re-arm tests want, so `on_start`'s never-arm walk does not itself
#: halt the strategy. R-8 (2026-09-12, docs/core/PROGRESS.md, supersedes
#: three-seam Slice 4 review item 5): an eof-complete page ABSENT the slug
#: now arms too, for a candidate instrument, PROVIDED the record is fresh
#: (`ts_ns` within the ceiling) and Nautilus's reconciled portfolio agrees
#: (Option B). This fixture carries no `ts_ns`, so it EXPLICITLY lists
#: `INTERIOR_ID`'s own slug at "0" (present branch, freshness-independent)
#: rather than relying on the absent branch -- an empty `positions` list
#: here would halt on a missing/stale `ts_ns`, not arm.
_PERMISSIVE_EVIDENCE: dict[str, object] = {
    "v": 1,
    "eof_complete": True,
    "position_read_refused": False,
    "fill_walk_complete": True,
    "positions": [{"slug": str(INTERIOR_ID.symbol.value), "net_position": "0"}],
}


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


# ---------------------------------------------------------------------------
# HF-4 (post-take re-arm reachability): C1 -- release a stale IN_FLIGHT
# marker once the account-wide submit intent has closed, so attempts 2/3
# become reachable (PREREG v3 SS5). `submit_order` is stubbed to a no-op in
# every test below -- the real submit-intent flock is therefore never armed
# by these tests, so `is_intent_open()` stays False throughout unless a
# test explicitly arms it via `_arm_and_release_stale_intent` (already
# defined above) or writes a corrupt singleton directly.
# ---------------------------------------------------------------------------

_S: int = 1_000_000_000  # one second, in nanoseconds


def _register_phase1_and_start(
    *,
    store_path: Path,
    instruments: tuple[BinaryOption, ...],
    clock: TestClock | None = None,
    position_evidence_reader: Any | None = None,
) -> ContinuousRungHoldStrategy:
    """Phase 1 (real, non-None permit) registration -- mirrors `_register`/
    `_register_and_start` above, plus the `phase0_permit_guard=False` +
    `order_submission_permit=object()` idiom already used by
    `test_continuous_rung_hold_fill_wiring.py`'s
    `test_phase0_permit_guard_false_accepts_a_real_permit_and_submits_once`.
    `submit_order` is replaced with a no-op: these tests exercise the
    release/re-arm GATE, never the real order-submission chain.
    """
    cfg = CurrentRungHoldConfig(
        instrument_ids=tuple(instrument.id for instrument in instruments),
    )
    strategy = ContinuousRungHoldStrategy(
        cfg,
        trial_day_latch_factory=_cont_latch_factory(store_path),
        order_submission_permit=object(),  # type: ignore[arg-type]
        phase0_permit_guard=False,
        position_evidence_reader=position_evidence_reader,
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
    strategy.start()
    strategy.submit_order = lambda order: None  # type: ignore[method-assign]
    return strategy


def _arm_one_attempt(strategy: ContinuousRungHoldStrategy, *, ts_ns: int) -> None:
    assert strategy._latch is not None
    strategy._latch.set_inflight(STATION, CLIMATE_DAY.isoformat())
    strategy._latch.record_attempt(STATION, CLIMATE_DAY.isoformat(), ts_ns=ts_ns)


def _order_filled_for_position(
    strategy: ContinuousRungHoldStrategy, *, venue_order_id: str,
) -> OrderFilled:
    """A minimal `OrderFilled` for seeding a REAL reconciled Nautilus
    position via `cache.add_position` + `portfolio.initialize_positions()`
    -- the same idiom `test_continuous_rung_hold_fill_wiring.py`'s own
    `_fill` helper uses, inlined here to avoid a cross-test-module import
    cycle (that module imports FROM this one)."""
    return OrderFilled(
        trader_id=strategy.trader_id,
        strategy_id=strategy.id,
        instrument_id=INTERIOR_ID,
        client_order_id=ClientOrderId(f"C-{venue_order_id}"),
        venue_order_id=VenueOrderId(venue_order_id),
        account_id=AccountId("POLYMARKET_US-001"),
        trade_id=TradeId(f"T-{venue_order_id}"),
        position_id=PositionId(f"P-{venue_order_id}"),
        order_side=OrderSide.BUY,
        order_type=strategy.order_factory.limit(
            instrument_id=INTERIOR_ID,
            order_side=OrderSide.BUY,
            quantity=Quantity.from_int(1),
            price=Price.from_str("0.40"),
        ).order_type,
        last_qty=Quantity.from_int(1),
        last_px=Price.from_str("0.40"),
        currency=USD,
        commission=Money(0, USD),
        liquidity_side=LiquiditySide.TAKER,
        event_id=UUID4(),
        ts_event=WINDOW_OPEN_NS,
        ts_init=WINDOW_OPEN_NS,
    )


def test_a_closed_intent_and_an_elapsed_delay_floor_release_a_stale_inflight_marker(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """AC-1: a closed intent + an elapsed 120s delay floor releases the
    stale IN_FLIGHT marker, and the SAME tick reaches `evaluate_eligible_
    snapshot` and arms attempt 2."""
    strategy = _register_phase1_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    _arm_one_attempt(strategy, ts_ns=WINDOW_OPEN_NS)
    assert strategy._latch is not None
    assert strategy._latch.is_intent_open() is False

    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + 120 * _S),
    )

    assert strategy.diagnostics.count("inflight_released") == 1
    assert strategy._latch.is_inflight(STATION, CLIMATE_DAY.isoformat()) is True
    assert strategy._latch.attempt_state(STATION, CLIMATE_DAY.isoformat()) == (
        2, WINDOW_OPEN_NS + 120 * _S,
    )


def test_a_second_attempt_arms_after_a_resolver_terminal_zero_refreshes_evidence(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """AC-1, integration-shaped: a first re-arm-eligible tick against STALE
    evidence releases IN_FLIGHT but is denied (no attempt 2 yet); a resolver
    terminal-zero resolution's own evidence rewrite (simulated here by
    updating the reader's return value, exactly as `_write_startup_position_
    evidence` would) makes the VERY NEXT tick's read fresh, and attempt 2
    then arms -- the re-arm gate reads the CURRENT evidence, never a value
    cached from an earlier tick."""
    evidence_state: dict[str, object] = {"value": _PERMISSIVE_EVIDENCE}
    strategy = _register_phase1_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: evidence_state["value"],
    )
    # Now stale, absent-slug -- the boot walk above already ran (and
    # passed) against the fresh permissive evidence.
    evidence_state["value"] = {
        **_PERMISSIVE_EVIDENCE, "positions": [], "ts_ns": WINDOW_OPEN_NS - 10_000 * _S,
    }
    _arm_one_attempt(strategy, ts_ns=WINDOW_OPEN_NS)
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + 120 * _S),
    )
    assert strategy._latch is not None
    # Released, but denied -- stale evidence -- so attempt 2 did NOT arm.
    assert strategy._latch.is_inflight(STATION, CLIMATE_DAY.isoformat()) is False
    assert strategy._latch.attempt_state(STATION, CLIMATE_DAY.isoformat()) == (1, WINDOW_OPEN_NS)

    # The resolver's own rewrite: fresh, absent-slug evidence.
    evidence_state["value"] = {
        **_PERMISSIVE_EVIDENCE, "positions": [], "ts_ns": WINDOW_OPEN_NS,
    }
    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + 121 * _S),
    )

    assert strategy._latch.is_inflight(STATION, CLIMATE_DAY.isoformat()) is True
    assert strategy._latch.attempt_state(STATION, CLIMATE_DAY.isoformat()) == (
        2, WINDOW_OPEN_NS + 121 * _S,
    )


def test_a_third_attempt_arms_and_a_fourth_never_does(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """AC-2, AC-3: with two attempts already burned, a closed intent past
    the floor releases and arms attempt 3; the NEXT such release finds
    `attempts == 3` and the re-arm gate denies forever."""
    strategy = _register_phase1_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    assert strategy._latch is not None
    strategy._latch.record_attempt(STATION, CLIMATE_DAY.isoformat(), ts_ns=WINDOW_OPEN_NS)
    strategy._latch.record_attempt(STATION, CLIMATE_DAY.isoformat(), ts_ns=WINDOW_OPEN_NS)
    strategy._latch.set_inflight(STATION, CLIMATE_DAY.isoformat())
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + 120 * _S),
    )
    assert strategy._latch.attempt_state(STATION, CLIMATE_DAY.isoformat()) == (
        3, WINDOW_OPEN_NS + 120 * _S,
    )
    assert strategy._latch.is_inflight(STATION, CLIMATE_DAY.isoformat()) is True

    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + 240 * _S),
    )
    # Attempt 4 never arms: released, then denied by the attempt cap.
    assert strategy._latch.is_inflight(STATION, CLIMATE_DAY.isoformat()) is False
    assert strategy._latch.attempt_state(STATION, CLIMATE_DAY.isoformat()) == (
        3, WINDOW_OPEN_NS + 120 * _S,
    )


def test_a_stale_inflight_marker_is_never_released_while_the_intent_is_open(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """AC-4: a crash-left OPEN singleton (`_arm_and_release_stale_intent`,
    defined above) blocks the release regardless of how far past the delay
    floor the tick lands."""
    _arm_and_release_stale_intent(store_path)
    strategy = _register_phase1_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    assert strategy._latch is not None
    assert strategy._latch.is_intent_open() is True
    _arm_one_attempt(strategy, ts_ns=WINDOW_OPEN_NS)
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + 1_000 * _S),
    )

    assert strategy.diagnostics.count("inflight_released") == 0
    assert strategy._latch.is_inflight(STATION, CLIMATE_DAY.isoformat()) is True
    assert strategy._latch.attempt_state(STATION, CLIMATE_DAY.isoformat()) == (1, WINDOW_OPEN_NS)


def test_a_corrupt_intent_singleton_leaves_the_inflight_marker_set(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """AC-5: `is_latched()` treats a corrupt singleton as `True` (fail
    closed) -- the release must never fire against one."""
    store = SqliteStateStore(store_path)
    with open_submit_intent_latch(store, store_path):
        pass
    store.set(CURRENT_INTENT_KEY, b"not json")
    store.close()

    strategy = _register_phase1_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    assert strategy._latch is not None
    assert strategy._latch.is_intent_open() is True
    _arm_one_attempt(strategy, ts_ns=WINDOW_OPEN_NS)
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + 1_000 * _S),
    )

    assert strategy._latch.is_inflight(STATION, CLIMATE_DAY.isoformat()) is True
    assert strategy._latch.attempt_state(STATION, CLIMATE_DAY.isoformat()) == (1, WINDOW_OPEN_NS)


def test_a_release_inside_the_delay_floor_never_happens(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """AC-6: the same-burst race guard -- a tick inside the 120s floor
    never releases, even with the intent closed."""
    strategy = _register_phase1_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    _arm_one_attempt(strategy, ts_ns=WINDOW_OPEN_NS)
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

    strategy.on_quote_tick(_quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + 1))

    assert strategy.diagnostics.count("inflight_released") == 0
    assert strategy._latch is not None
    assert strategy._latch.is_inflight(STATION, CLIMATE_DAY.isoformat()) is True
    assert strategy._latch.attempt_state(STATION, CLIMATE_DAY.isoformat()) == (1, WINDOW_OPEN_NS)


def test_a_released_marker_still_cannot_arm_on_stale_absent_slug_evidence(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """AC-8: the release never bypasses `_rearm_permitted` -- evidence far
    outside EITHER the pre-HF-4 600s ceiling or HF-4's own 180s re-arm
    ceiling still denies. Re-run after C3 (still denied, a fortiori)."""
    evidence_state: dict[str, object] = {"value": _PERMISSIVE_EVIDENCE}
    strategy = _register_phase1_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: evidence_state["value"],
    )
    # Now stale, absent-slug -- the boot walk above already ran (and
    # passed) against the fresh permissive evidence.
    evidence_state["value"] = {
        **_PERMISSIVE_EVIDENCE, "positions": [], "ts_ns": WINDOW_OPEN_NS - 10_000 * _S,
    }
    _arm_one_attempt(strategy, ts_ns=WINDOW_OPEN_NS)
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + 120 * _S),
    )

    assert strategy._latch is not None
    assert strategy._latch.is_inflight(STATION, CLIMATE_DAY.isoformat()) is False
    assert strategy._latch.attempt_state(STATION, CLIMATE_DAY.isoformat()) == (1, WINDOW_OPEN_NS)
    assert len(strategy.offer_tape) == 0


def test_a_released_marker_still_cannot_arm_when_nautilus_reports_a_long(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """AC-8, R9: the release never bypasses the Nautilus cross-check --
    fresh absent-slug evidence still denies when the reconciled portfolio
    shows a LONG."""
    evidence = {**_PERMISSIVE_EVIDENCE, "positions": [], "ts_ns": WINDOW_OPEN_NS}
    strategy = _register_phase1_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: evidence,
    )
    fill = _order_filled_for_position(strategy, venue_order_id="ord-hf4-long")
    position = Position(interior_instrument, fill)
    strategy.cache.add_position(position, OmsType.NETTING)
    strategy.portfolio.initialize_positions()
    _arm_one_attempt(strategy, ts_ns=WINDOW_OPEN_NS)
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + 120 * _S),
    )

    assert strategy._latch is not None
    assert strategy._latch.is_inflight(STATION, CLIMATE_DAY.isoformat()) is False
    assert strategy._latch.attempt_state(STATION, CLIMATE_DAY.isoformat()) == (1, WINDOW_OPEN_NS)
    assert len(strategy.offer_tape) == 0


def test_the_release_and_the_rearm_decision_each_record_exactly_one_decision_line(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """AC-17 (B3): the release and a successful re-arm each emit exactly
    ONE `rearm:`-prefixed decision line, recorded on `last_rearm_decision`
    -- asserted on the recorded value, never via log capture (L-27)."""
    strategy = _register_phase1_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    emitted: list[str] = []
    strategy._emit_rearm_decision = emitted.append  # type: ignore[method-assign,assignment]
    _arm_one_attempt(strategy, ts_ns=WINDOW_OPEN_NS)
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + 120 * _S),
    )

    assert len(emitted) == 2
    assert "rearm:" in emitted[0] and "released" in emitted[0]
    assert "rearm:" in emitted[1] and "re-armed" in emitted[1]
    assert strategy.last_rearm_decision == emitted[-1]


def test_a_consumed_station_day_never_reaches_the_inflight_release(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """AC-7 (N3, mutation-regression authored with C1): `is_consumed` short-
    circuits `_hunt_tick` BEFORE the release path is ever consulted -- a
    genuine fill freezes the station-day regardless of any IN_FLIGHT
    residue. Mutation evidence (commit message): moving the release above
    `is_consumed` makes this RED; reverted before commit."""
    strategy = _register_phase1_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    assert strategy._latch is not None
    strategy._latch.consume(
        STATION, CLIMATE_DAY.isoformat(),
        latched_at_ns=WINDOW_OPEN_NS, instrument_id=str(INTERIOR_ID),
        ask=Decimal("0.40"), reason="taken",
    )
    # A residual IN_FLIGHT marker that should never be consulted.
    _arm_one_attempt(strategy, ts_ns=WINDOW_OPEN_NS)
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + 120 * _S),
    )

    assert strategy.diagnostics.count("inflight_released") == 0
    assert strategy._latch.is_inflight(STATION, CLIMATE_DAY.isoformat()) is True
    assert strategy._latch.attempt_state(STATION, CLIMATE_DAY.isoformat()) == (1, WINDOW_OPEN_NS)
    assert len(strategy.offer_tape) == 0


def test_a_standing_pre_arm_refusal_burns_three_attempts_and_then_stops_forever(
    store_path: Path, interior_instrument: BinaryOption,
) -> None:
    """N2, AC-3: a standing pre-`arm()` refusal (the real submit-intent
    flock is never armed by these tests -- `submit_order` is stubbed) burns
    exactly three attempts, 120s apart, and then stops FOREVER -- a later
    tick keeps denying, never re-arming a fourth time."""
    strategy = _register_phase1_and_start(
        store_path=store_path,
        instruments=(interior_instrument,),
        position_evidence_reader=lambda: _PERMISSIVE_EVIDENCE,
    )
    assert strategy._latch is not None
    strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

    for i in range(3):
        strategy.on_quote_tick(
            _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + i * 120 * _S),
        )
        assert strategy._latch.attempt_state(STATION, CLIMATE_DAY.isoformat()) == (
            i + 1, WINDOW_OPEN_NS + i * 120 * _S,
        )
        assert strategy._latch.is_inflight(STATION, CLIMATE_DAY.isoformat()) is True

    # A fourth re-arm-eligible tick: released, then denied forever by the
    # attempt cap.
    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + 3 * 120 * _S),
    )
    assert strategy._latch.is_inflight(STATION, CLIMATE_DAY.isoformat()) is False
    assert strategy._latch.attempt_state(STATION, CLIMATE_DAY.isoformat()) == (
        3, WINDOW_OPEN_NS + 2 * 120 * _S,
    )
    assert len(strategy.offer_tape) == 3

    # And a fifth, far later: still denied, still no fourth arm.
    strategy.on_quote_tick(
        _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + 10 * 120 * _S),
    )
    assert strategy._latch.is_inflight(STATION, CLIMATE_DAY.isoformat()) is False
    assert strategy._latch.attempt_state(STATION, CLIMATE_DAY.isoformat()) == (
        3, WINDOW_OPEN_NS + 2 * 120 * _S,
    )
    assert len(strategy.offer_tape) == 3
