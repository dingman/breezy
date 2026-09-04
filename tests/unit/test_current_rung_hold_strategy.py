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

from breezy.adapters.polymarket_us.parsing import (
    FEE_SCHEDULE_STATUS_KEY,
    FEE_SCHEDULE_STATUS_KNOWN,
)
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
from breezy.runtime.backtest_feed import NWS_BACKTEST_CLIENT_ID
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
from breezy.strategy.weather_common.refusals import RefusalAlerter

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


def _facts_info(
    *, lower_f: int | None, upper_f: int | None, fee_schedule_known: bool = True,
) -> dict[str, object]:
    info: dict[str, object] = {
        WEATHER_FACTS_STATUS_KEY: WEATHER_FACTS_STATUS_KNOWN,
        SETTLEMENT_STATION_KEY: STATION,
        CLIMATE_DAY_KEY: CLIMATE_DAY.isoformat(),
        MEASURE_KEY: "high",
        STRIKE_LOWER_F_KEY: lower_f,
        STRIKE_UPPER_F_KEY: upper_f,
    }
    if fee_schedule_known:
        info[FEE_SCHEDULE_STATUS_KEY] = FEE_SCHEDULE_STATUS_KNOWN
    return info


def _instrument(
    instrument_id: InstrumentId, *, lower_f: int | None, upper_f: int | None,
    fee_coefficient: Decimal = THETA,
    fee_schedule_known: bool = True,
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
        info=_facts_info(
            lower_f=lower_f, upper_f=upper_f, fee_schedule_known=fee_schedule_known,
        ),
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


class TestPartialInstrumentResolution:
    """A configured id absent from the cache (L-23: ~9% of station-days
    never listed, and the provider may lag the catalog) must not kill
    every OTHER station's subscription -- only an unresolved id itself is
    refused, counted, and skipped."""

    def test_a_missing_instrument_is_skipped_counted_and_does_not_stop(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        missing_id = InstrumentId(Symbol("lax-missing"), Venue("POLYMARKET_US"))
        cfg = CurrentRungHoldConfig(instrument_ids=(interior_instrument.id, missing_id))
        rig = _register_and_start(
            store_path=store_path, instruments=(interior_instrument,), config=cfg,
        )
        strategy = rig.strategy
        assert strategy.is_running
        assert str(interior_instrument.id) in strategy._facts
        assert strategy.refusals.count("instrument_unresolved") == 1

    def test_a_missing_instrument_does_not_consume_the_trial_day_latch(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        missing_id = InstrumentId(Symbol("lax-missing"), Venue("POLYMARKET_US"))
        cfg = CurrentRungHoldConfig(instrument_ids=(interior_instrument.id, missing_id))
        rig = _register_and_start(
            store_path=store_path, instruments=(interior_instrument,), config=cfg,
        )
        strategy = rig.strategy
        assert strategy._latch is not None
        assert strategy._latch.is_consumed(STATION, CLIMATE_DAY.isoformat()) is False

    def test_all_instruments_missing_stops_the_strategy(self, store_path: Path) -> None:
        missing_id = InstrumentId(Symbol("lax-missing"), Venue("POLYMARKET_US"))
        cfg = CurrentRungHoldConfig(instrument_ids=(missing_id,))
        rig = _register_and_start(store_path=store_path, instruments=(), config=cfg)
        strategy = rig.strategy
        assert strategy.is_stopped
        assert strategy.refusals.count("instrument_unresolved") == 1


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
        # Pushed 2 hours before the quote -- well past the 50 min staleness bound.
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


class TestFeeScheduleGuard:
    """Barrier F1: the fee coefficient must come from a GUARDED read.

    ``instrument.maker_fee`` is real, typed ``Decimal`` machinery even when
    the venue's fee schedule is UNKNOWN (``BinaryOption`` defaults it, per
    ``breezy.adapters.polymarket_us.parsing``'s module docstring) -- so the
    strategy must call ``assert_fee_schedule_known`` before ever reading it,
    and route an unresolved schedule to the SAME counted, latched
    ``fee_schedule_mismatch`` refusal ``decision.py`` already emits for a
    mismatched (but KNOWN) coefficient, never raise and never silently
    default.
    """

    def test_an_unknown_fee_schedule_refuses_fee_schedule_mismatch(
        self, store_path: Path,
    ) -> None:
        instrument = _instrument(
            INTERIOR_ID, lower_f=86, upper_f=87, fee_schedule_known=False,
        )
        rig = _register_and_start(store_path=store_path, instruments=(instrument,))
        strategy = rig.strategy
        strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
        quote = _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS)
        strategy.on_quote_tick(quote)

        assert strategy.refusals.count("fee_schedule_mismatch") == 1
        record = strategy._latch.record(STATION, CLIMATE_DAY.isoformat())  # type: ignore[union-attr]
        assert record is not None
        assert record.reason == "fee_schedule_mismatch"

    def test_a_known_fee_schedule_at_the_required_coefficient_proceeds(
        self, store_path: Path,
    ) -> None:
        instrument = _instrument(
            INTERIOR_ID, lower_f=86, upper_f=87,
            fee_coefficient=Decimal("0.06"), fee_schedule_known=True,
        )
        rig = _register_and_start(store_path=store_path, instruments=(instrument,))
        strategy = rig.strategy
        strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
        quote = _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS)
        strategy.on_quote_tick(quote)

        assert strategy.refusals.count("fee_schedule_mismatch") == 0
        record = strategy._latch.record(STATION, CLIMATE_DAY.isoformat())  # type: ignore[union-attr]
        assert record is not None
        assert record.reason == "taken"


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


class _RecordingSink:
    """An `AlertSink` that keeps what it was handed (see
    `test_weather_common_refusals.py`'s identical helper).
    """

    def __init__(self) -> None:
        self.payloads: list[object] = []

    def emit(self, payload: object) -> None:
        self.payloads.append(payload)


class TestRefusalVisibility:
    """Review fix: a refusal must surface WITHOUT any component-degrade
    event -- `on_quote_tick` reports through `strategy.refusal_alerter` on
    the very tick that produced the refusal, never a
    `COMPONENT_STATE_TOPIC` subscription. This harness never publishes to
    `msgbus` at all (module docstring), so a passing test here is
    per-tick-only proof, not an artifact of some other trigger firing.
    """

    def test_a_refusal_reaches_the_sink_on_its_own_tick_with_no_degrade_event(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        rig = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
        strategy = rig.strategy
        sink = _RecordingSink()
        strategy.refusal_alerter = RefusalAlerter(
            strategy.refusals, site=str(strategy.id), sink=sink
        )
        strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

        before_window = _quote(
            INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS - 30 * NS_PER_MIN,
        )
        strategy.on_quote_tick(before_window)

        assert strategy.refusals.count("outside_decision_window") == 1
        assert len(sink.payloads) == 1
        assert sink.payloads[0].event == "OUTSIDE_DECISION_WINDOW_REFUSALS"  # type: ignore[attr-defined]

    def test_a_second_refusal_for_the_same_reason_does_not_re_notify(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        """`AlertState` dedupes the still-active condition: proves the
        per-tick call is throttled by count-CHANGE (the false->true edge),
        not by unconditionally re-emitting on every tick.
        """
        rig = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
        strategy = rig.strategy
        sink = _RecordingSink()
        strategy.refusal_alerter = RefusalAlerter(
            strategy.refusals, site=str(strategy.id), sink=sink
        )
        strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

        first = _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS - 30 * NS_PER_MIN)
        strategy.on_quote_tick(first)
        strategy.refusals.record("outside_decision_window")
        strategy._report_refusal_change()

        assert strategy.refusals.count("outside_decision_window") == 2
        assert len(sink.payloads) == 1

    def test_no_alerter_wired_is_a_no_op_not_a_raise(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        rig = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
        strategy = rig.strategy
        assert strategy.refusal_alerter is None
        strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))

        before_window = _quote(
            INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS - 30 * NS_PER_MIN,
        )
        strategy.on_quote_tick(before_window)  # must not raise

        assert strategy.refusals.count("outside_decision_window") == 1


class TestObservationSubscription:
    """Finding 1: `on_start` must subscribe the `StationObservation` stream
    with the SAME `client_id` the backtest weather stream is registered
    under (`NWS_BACKTEST_CLIENT_ID`, `runtime/backtest_feed.py`) -- matching
    every sibling strategy's `nws_climate_day_data_type()` subscription
    (`running_extreme_lock/strategy.py:274`, `forecast_revision/
    strategy.py:210`, `cli_settlement_print_lock/strategy.py:607`).

    `Actor.subscribe_data` (installed `nautilus_trader.common.actor.pyx`,
    lines 1258-1296) makes the msgbus topic subscription UNCONDITIONALLY,
    before it ever inspects `client_id` -- but the `SubscribeData` command
    to `DataEngine.execute` is only constructed and sent past that same
    check (line 1292: `if client_id is None and instrument_id is None:
    self.log.error(...); return`). So a command reaching the captured
    endpoint below is direct proof the error-and-return branch was NOT
    taken: the log line these commands are gated by cannot have fired.
    """

    def test_on_start_sends_a_subscribe_data_command_with_the_shared_client_id(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        cfg = CurrentRungHoldConfig(instrument_ids=(interior_instrument.id,))
        strategy = CurrentRungHoldStrategy(
            cfg, trial_day_latch_factory=_open_latch_factory(store_path),
        )
        clock = TestClock()
        clock.set_time(WINDOW_OPEN_NS)
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
        sent_commands: list[object] = []
        msgbus.register(endpoint="DataEngine.execute", handler=sent_commands.append)

        strategy.start()

        observation_commands = [
            command
            for command in sent_commands
            if type(command).__name__ == "SubscribeData"
            and command.data_type.type.__name__ == "StationObservation"
        ]
        assert len(observation_commands) == 1
        assert observation_commands[0].client_id == NWS_BACKTEST_CLIENT_ID


class TestDiagnosticsCounter:
    """Finding 2: the three WAIT-state `return`s inside `on_quote_tick`
    (raw-executable false, no observation yet, rung not current) are not
    orders being refused -- they are moments this station-day's ONE trial
    has not arrived yet. They stay OUT of `self.refusals`,
    `decision.REFUSAL_REASONS`, the latch's `_REASONS`, and
    `risk.COUNTED_REFUSAL_REASONS` (unchanged), and are instead surfaced
    through the separate, public `self.diagnostics` counter so an operator
    can tell "no take yet" apart from "nothing will ever happen".
    """

    def test_raw_executable_false_increments_the_not_executable_diagnostic(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        rig = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
        strategy = rig.strategy

        quote = _quote(INTERIOR_ID, ask="0.97", ts_event=WINDOW_OPEN_NS)
        strategy.on_quote_tick(quote)

        assert strategy.diagnostics.count("in_window_not_executable") == 1
        assert strategy.refusals.total() == 0

    def test_no_observation_yet_increments_the_no_running_max_diagnostic(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        rig = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
        strategy = rig.strategy

        quote = _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS)
        strategy.on_quote_tick(quote)

        assert strategy.diagnostics.count("in_window_no_running_max_yet") == 1
        assert strategy.refusals.total() == 0

    def test_rung_not_current_increments_the_rung_not_current_diagnostic(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        rig = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
        strategy = rig.strategy
        # 32F (0.0C, exact METAR point) is nowhere near this instrument's
        # [86, 87] rung -- `facts.contains` is False at both ends, so this
        # instrument cannot be the currently-active rung.
        strategy.on_data(_observation(temp_c_tenths=0, observed_at_ns=WINDOW_OPEN_NS - 1))

        quote = _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS)
        strategy.on_quote_tick(quote)

        assert strategy.diagnostics.count("in_window_rung_not_current") == 1
        assert strategy.refusals.total() == 0

    def test_diagnostics_never_reach_the_trial_day_latch(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        rig = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
        strategy = rig.strategy

        quote = _quote(INTERIOR_ID, ask="0.97", ts_event=WINDOW_OPEN_NS)
        strategy.on_quote_tick(quote)

        assert strategy.diagnostics.count("in_window_not_executable") == 1
        record = strategy._latch.record(STATION, CLIMATE_DAY.isoformat())  # type: ignore[union-attr]
        assert record is None
