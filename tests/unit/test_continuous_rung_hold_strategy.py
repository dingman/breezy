"""Phase 0 tests for ``ContinuousRungHoldStrategy``."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from decimal import Decimal
from pathlib import Path

import pytest
from nautilus_trader.common.component import TestClock
from nautilus_trader.model.identifiers import TraderId
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.portfolio import Portfolio
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

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
from tests.unit.test_current_rung_hold_strategy import (
    CLIMATE_DAY,
    ICAO,
    INTERIOR_ID,
    NS_PER_MIN,
    STATION,
    WINDOW_OPEN_NS,
    _instrument,
    _observation,
    _quote,
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


def _register_and_start(
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
    strategy.start()
    return strategy


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
