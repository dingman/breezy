"""TestClock-driven tests for `CurrentRungHoldStrategy`
(src/breezy/strategy/current_rung_hold/strategy.py, build order step 6).

Pattern: `tests/unit/test_cli_settlement_print_lock_strategy_construction.py`
`_register` helper (`TestClock`, `TestComponentStubs.msgbus()/cache()`,
`Portfolio`, `strategy.register`), extended with a REAL trial-day latch
opened over a temp-path `SqliteStateStore` (`open_submit_intent_latch` +
`open_trial_day_latch`, the shared-store fold the peer review converged on).

Two instruments make up ONE ladder for LAX 2026-09-04: an interior 2F rung
`[86, 87]` and its open-upper neighbour `[88, None]`. `RunningMax` rows are
pushed through `StationObservation` (`is_metar=True` -- an exact point, so
`lower_f == upper_f` and the interval never spans on its own) via
`strategy.on_data`, and quotes are delivered directly to `on_quote_tick`
(never through the message bus -- this harness drives the strategy's real
handlers, not its subscriptions).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from decimal import Decimal
from pathlib import Path

import pytest
from nautilus_trader.common.component import TestClock
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import QuoteTick
from nautilus_trader.model.enums import AssetClass
from nautilus_trader.model.identifiers import InstrumentId, Symbol, TraderId, Venue
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.portfolio import Portfolio
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.domain.station_observation import StationObservation
from breezy.domain.weather_bucket_facts import (
    CLIMATE_DAY_KEY,
    MEASURE_KEY,
    SETTLEMENT_STATION_KEY,
    STRIKE_LOWER_F_KEY,
    STRIKE_UPPER_F_KEY,
    WEATHER_FACTS_STATUS_KEY,
    WEATHER_FACTS_STATUS_KNOWN,
)
from breezy.registry.sites import default_registry
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import (
    SubmitIntentLockHeld,
    SubmitIntentLockNotHeld,
    open_submit_intent_latch,
)
from breezy.strategy.current_rung_hold.config import SUPPORTED_STATIONS, CurrentRungHoldConfig
from breezy.strategy.current_rung_hold.strategy import (
    CurrentRungHoldStrategy,
    MissingTrialDayLatchError,
)
from breezy.strategy.current_rung_hold.trial_day_latch import TrialDayLatch, open_trial_day_latch

STATION = "LAX"
ICAO = "KLAX"
CLIMATE_DAY = dt.date(2026, 9, 4)
LAX_STD_OFFSET_HOURS = -8.0
# 2026-09-04T20:00:00Z == 12:00:00 LST (PST, -8h) -- the window's opening instant.
WINDOW_OPEN_NS = 1_788_552_000_000_000_000
NS_PER_MIN = 60_000_000_000
INTERIOR_ID = InstrumentId(Symbol("lax-86-87"), Venue("POLYMARKET_US"))
OPEN_UPPER_ID = InstrumentId(Symbol("lax-88-plus"), Venue("POLYMARKET_US"))
THETA = Decimal("0.06")


def _facts_info(*, lower_f: int | None, upper_f: int | None) -> dict[str, object]:
    return {
        WEATHER_FACTS_STATUS_KEY: WEATHER_FACTS_STATUS_KNOWN,
        SETTLEMENT_STATION_KEY: STATION,
        CLIMATE_DAY_KEY: CLIMATE_DAY.isoformat(),
        MEASURE_KEY: "high",
        STRIKE_LOWER_F_KEY: lower_f,
        STRIKE_UPPER_F_KEY: upper_f,
    }


def _instrument(
    instrument_id: InstrumentId, *, lower_f: int | None, upper_f: int | None,
    fee_coefficient: Decimal = THETA,
) -> BinaryOption:
    increment = Price.from_str("0.01")
    size_increment = Quantity.from_str("1")
    return BinaryOption(
        instrument_id=instrument_id,
        raw_symbol=instrument_id.symbol,
        outcome="Yes",
        description="LAX daily high",
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
        maker_fee=fee_coefficient,
        taker_fee=fee_coefficient,
        ts_event=0,
        ts_init=0,
        info=_facts_info(lower_f=lower_f, upper_f=upper_f),
    )


def _quote(
    instrument_id: InstrumentId, *, ask: str, size: int = 10, ts_event: int,
) -> QuoteTick:
    return QuoteTick(
        instrument_id=instrument_id,
        bid_price=Price.from_str("0.01"),
        ask_price=Price.from_str(ask),
        bid_size=Quantity.from_int(size),
        ask_size=Quantity.from_int(size),
        ts_event=ts_event,
        ts_init=ts_event,
    )


def _observation(*, temp_c_tenths: int, observed_at_ns: int) -> StationObservation:
    return StationObservation(
        station=ICAO,
        observed_at_ns=observed_at_ns,
        received_at_ns=observed_at_ns + 1,
        temp_c_tenths=temp_c_tenths,
        precision_c_tenths=5,
        is_metar=True,
        source_channel="iem_asos_metar",
        assumed_publication_lag_ns=1,
    )


class _Rig:
    def __init__(self, strategy: CurrentRungHoldStrategy) -> None:
        self.strategy = strategy


@contextmanager
def _open_latch_context(store_path: Path) -> Iterator[TrialDayLatch]:
    """Opens a real `SubmitIntentLatch`+`TrialDayLatch` pair for the test.

    `CurrentRungHoldStrategy.__init__`'s `trial_day_latch_factory` is a
    zero-arg callable returning a context manager yielding a `TrialDayLatch`
    -- `on_start` enters it through its own `ExitStack` and `on_stop` closes
    that stack, so the flock's lifetime is owned by the strategy's own
    lifecycle, never by a GC-pinning trick on the factory closure.
    """
    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
        yield open_trial_day_latch(intent_latch)


def _open_latch_factory(
    store_path: Path,
) -> Callable[[], AbstractContextManager[TrialDayLatch]]:
    return lambda: _open_latch_context(store_path)


def _register_and_start(
    *,
    store_path: Path,
    instruments: tuple[BinaryOption, ...],
    config: CurrentRungHoldConfig | None = None,
) -> _Rig:
    cfg = config or CurrentRungHoldConfig(
        instrument_ids=tuple(instrument.id for instrument in instruments),
    )
    strategy = CurrentRungHoldStrategy(
        cfg, trial_day_latch_factory=_open_latch_factory(store_path),
    )
    clock = TestClock()
    clock.set_time(WINDOW_OPEN_NS)
    msgbus = TestComponentStubs.msgbus()
    cache = TestComponentStubs.cache()
    for instrument in instruments:
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
    return _Rig(strategy)


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "state.db"


@pytest.fixture
def interior_instrument() -> BinaryOption:
    return _instrument(INTERIOR_ID, lower_f=86, upper_f=87)


@pytest.fixture
def open_upper_instrument() -> BinaryOption:
    return _instrument(OPEN_UPPER_ID, lower_f=88, upper_f=None)


class TestConstruction:
    def test_missing_latch_factory_raises_at_on_start(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        cfg = CurrentRungHoldConfig(instrument_ids=(interior_instrument.id,))
        strategy = CurrentRungHoldStrategy(cfg)
        clock = TestClock()
        msgbus = TestComponentStubs.msgbus()
        cache = TestComponentStubs.cache()
        cache.add_instrument(interior_instrument)
        portfolio = Portfolio(msgbus=msgbus, cache=cache, clock=clock)
        strategy.register(
            trader_id=TraderId("BACKTEST-001"),
            portfolio=portfolio,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
        )
        with pytest.raises(MissingTrialDayLatchError):
            strategy.on_start()


class TestFirstExecutableSnapshot:
    def test_first_executable_snapshot_is_the_only_candidate(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        rig = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
        strategy = rig.strategy
        # R(t) = 86 exactly (METAR, exact point) -- inside [86, 87], not ambiguous.
        strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
        # 30.0C -> 86F exactly.
        first = _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS)
        strategy.on_quote_tick(first)
        assert strategy._latch is not None
        record = strategy._latch.record(STATION, CLIMATE_DAY.isoformat())
        assert record is not None
        assert record.ask == Decimal("0.40")

        # A CHEAPER later ask the same day must be ignored -- the latch is consumed.
        second = _quote(
            INTERIOR_ID, ask="0.10", ts_event=WINDOW_OPEN_NS + 10 * NS_PER_MIN,
        )
        strategy.on_quote_tick(second)
        record_after = strategy._latch.record(STATION, CLIMATE_DAY.isoformat())
        assert record_after == record  # unchanged: never re-evaluated

    def test_a_non_executable_quote_does_not_consume_the_day(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        rig = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
        strategy = rig.strategy
        strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
        too_expensive = _quote(INTERIOR_ID, ask="0.99", ts_event=WINDOW_OPEN_NS)
        strategy.on_quote_tick(too_expensive)
        assert strategy._latch is not None
        assert strategy._latch.is_consumed(STATION, CLIMATE_DAY.isoformat()) is False


class TestWindow:
    def test_a_quote_outside_the_window_is_refused_and_never_latched(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        rig = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
        strategy = rig.strategy
        strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
        before_window = _quote(
            INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS - 30 * NS_PER_MIN,
        )
        strategy.on_quote_tick(before_window)
        assert strategy.refusals.count("outside_decision_window") == 1
        assert strategy._latch is not None
        assert strategy._latch.is_consumed(STATION, CLIMATE_DAY.isoformat()) is False


class TestObservationRefusals:
    def test_stale_observation_refuses_observation_unavailable(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        rig = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
        strategy = rig.strategy
        # Pushed 2 hours before the quote -- well past the 0.75h staleness bound.
        stale_ns = WINDOW_OPEN_NS - 2 * 3_600_000_000_000
        strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=stale_ns))
        quote = _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS)
        strategy.on_quote_tick(quote)
        assert strategy.refusals.count("observation_unavailable") == 1
        record = strategy._latch.record(STATION, CLIMATE_DAY.isoformat())  # type: ignore[union-attr]
        assert record is not None
        assert record.reason == "observation_unavailable"

    def test_an_ambiguous_observation_refuses_observation_ambiguous(
        self, store_path: Path,
        interior_instrument: BinaryOption,
        open_upper_instrument: BinaryOption,
    ) -> None:
        rig = _register_and_start(
            store_path=store_path,
            instruments=(interior_instrument, open_upper_instrument),
        )
        strategy = rig.strategy
        # 31.0C, non-METAR, 1-degree-C interval -> [87.8, 89.6)F, straddling
        # the interior [86, 87] rung and the open-upper [88, None) rung.
        obs = StationObservation(
            station=ICAO,
            observed_at_ns=WINDOW_OPEN_NS - 1,
            received_at_ns=WINDOW_OPEN_NS,
            temp_c_tenths=310,
            precision_c_tenths=10,
            is_metar=False,
            source_channel="nws_api_observations",
            assumed_publication_lag_ns=1,
        )
        strategy.on_data(obs)
        # `running_max.lower_f == 87` falls inside the INTERIOR instrument's
        # own facts ([86, 87]) -- that is the instrument the strategy reads
        # as a candidate for the current rung; `upper_f == 89` falls in the
        # OPEN-UPPER rung instead, which is exactly the straddle `spans`
        # (and therefore `observation_ambiguous`) exists to catch.
        quote = _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS)
        strategy.on_quote_tick(quote)
        assert strategy.refusals.count("observation_ambiguous") == 1
        record = strategy._latch.record(STATION, CLIMATE_DAY.isoformat())  # type: ignore[union-attr]
        assert record is not None
        assert record.reason == "observation_ambiguous"


class TestTakeNeverSubmits:
    def test_a_take_records_taken_and_never_calls_submit_order(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        rig = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
        strategy = rig.strategy
        submitted: list[object] = []
        strategy.submit_order = submitted.append  # type: ignore[method-assign]
        strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
        # LAX/SON/12/0/0 p_hold_lower=0.6982; ask=0.40 clears break-even easily.
        quote = _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS)
        strategy.on_quote_tick(quote)

        record = strategy._latch.record(STATION, CLIMATE_DAY.isoformat())  # type: ignore[union-attr]
        assert record is not None
        assert record.reason == "taken"
        assert submitted == []
        assert len(strategy.cache.orders()) == 0


class TestAskBandEquivalence:
    def test_config_pins_the_archive_studys_qualifying_ask_band_and_size(self) -> None:
        """Mirrors `ma_prelock_winner_ask_study.ASK_QUALIFYING_LOW/HIGH` and
        `MIN_EXECUTABLE_SIZE`, imported into
        `mb_current_rung_edge_study.py:88-95` and applied at
        `CurrentRungTrial.executable` (`:472-478`) -- `scripts/` is
        unimportable from `src/breezy` (layers contract), so this pins the
        MEASURED numbers directly rather than importing the module.
        """
        cfg = CurrentRungHoldConfig()
        assert cfg.executable_ask_lower == Decimal("0.05")
        assert cfg.executable_ask_upper == Decimal("0.95")
        assert cfg.minimum_displayed_size == 1


class TestRegistryOffset:
    @pytest.mark.parametrize("station", SUPPORTED_STATIONS)
    def test_strategys_offset_equals_the_registrys(
        self, store_path: Path, station: str,
    ) -> None:
        instrument = _instrument(
            InstrumentId(Symbol(f"{station.lower()}-fixture"), Venue("POLYMARKET_US")),
            lower_f=80, upper_f=81,
        )
        rig = _register_and_start(
            store_path=store_path,
            instruments=(instrument,),
            config=CurrentRungHoldConfig(instrument_ids=(instrument.id,), stations=(station,)),
        )
        strategy = rig.strategy
        expected = default_registry().climate_day_window("polymarket_us", station)
        assert (
            strategy._std_utc_offset_hours_by_station[station]
            == expected.std_utc_offset_hours
        )


class TestLatchLifecycle:
    def test_start_stop_start_rearms_without_a_stale_flock(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        rig = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
        strategy = rig.strategy
        latch_after_first_start = strategy._latch
        assert latch_after_first_start is not None
        assert latch_after_first_start.is_consumed(STATION, CLIMATE_DAY.isoformat()) is False

        strategy.stop()
        assert strategy._latch is None
        with pytest.raises(SubmitIntentLockNotHeld):
            latch_after_first_start.is_consumed(STATION, CLIMATE_DAY.isoformat())

        # A second `open_submit_intent_latch` over the SAME store path would
        # raise `SubmitIntentLockHeld` were the first flock still held --
        # proving `on_stop` genuinely released it, not merely nulled the
        # strategy's own reference.
        with open_submit_intent_latch(SqliteStateStore(store_path), store_path):
            pass

        # Nautilus's own FSM (`ComponentFSMFactory`) has no `STOPPED ->
        # STARTING` edge -- only `RESUME`/`RESET`/`DISPOSE`/`FAULT` are legal
        # from `STOPPED` (`nautilus_trader/common/component.pyx`, the state
        # table). A genuine restart is `reset()` (`STOPPED -> READY`, via
        # `on_reset`) then `start()` (`READY -> STARTING -> RUNNING`, via
        # `on_start`) -- the same sequence a live redeploy or engine restart
        # drives the strategy through.
        strategy.reset()
        strategy.start()
        assert strategy._latch is not None
        assert strategy._latch is not latch_after_first_start
        assert strategy._latch.is_consumed(STATION, CLIMATE_DAY.isoformat()) is False

    def test_a_second_concurrent_open_over_the_same_store_is_refused(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        rig = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
        with (
            pytest.raises(SubmitIntentLockHeld),
            open_submit_intent_latch(SqliteStateStore(store_path), store_path),
        ):
            pass
        rig.strategy.stop()


class TestSpanningIntervalRouting:
    def test_an_interval_only_touching_this_instruments_upper_bound_is_counted_ambiguous(
        self, store_path: Path,
        interior_instrument: BinaryOption,
        open_upper_instrument: BinaryOption,
    ) -> None:
        """`running_max` = `[85, 86]` -- `lower_f` (85) is OUTSIDE the interior
        instrument's own facts (`[86, 87]`), but `upper_f` (86) is INSIDE
        them. The old pre-filter (`facts.contains(running_max.lower_f)`
        only) would silently skip the interior instrument's tick here --
        never routing to `evaluate_decision`, never counting a refusal, even
        though this interval genuinely touches the interior rung and is
        ambiguous against the two-instrument ladder.
        """
        rig = _register_and_start(
            store_path=store_path,
            instruments=(interior_instrument, open_upper_instrument),
        )
        strategy = rig.strategy
        # 29.7C rounds to 85F (`round_half_up_f`); 1C precision, non-METAR,
        # closed-upper interval -> lower_f=85, upper_f=86 (verified via the
        # accumulator's own published contract in `running_extreme.py`).
        obs = StationObservation(
            station=ICAO,
            observed_at_ns=WINDOW_OPEN_NS - 1,
            received_at_ns=WINDOW_OPEN_NS,
            temp_c_tenths=297,
            precision_c_tenths=10,
            is_metar=False,
            source_channel="nws_api_observations",
            assumed_publication_lag_ns=1,
        )
        strategy.on_data(obs)
        accumulator = strategy._accumulators[STATION]
        running_max = accumulator.value_at(WINDOW_OPEN_NS)
        assert running_max is not None and running_max.lower_f == 85 and running_max.upper_f == 86

        quote = _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS)
        strategy.on_quote_tick(quote)
        assert strategy.refusals.count("observation_ambiguous") == 1
        record = strategy._latch.record(STATION, CLIMATE_DAY.isoformat())  # type: ignore[union-attr]
        assert record is not None
        assert record.reason == "observation_ambiguous"
