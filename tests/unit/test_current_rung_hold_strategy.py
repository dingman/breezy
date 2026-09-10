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

import ast
import datetime as dt
import inspect
import itertools
import textwrap
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from decimal import Decimal
from pathlib import Path

import pytest
from nautilus_trader.common.component import TestClock
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import QuoteTick
from nautilus_trader.model.enums import AssetClass, OmsType, OrderSide
from nautilus_trader.model.events import OrderFilled
from nautilus_trader.model.identifiers import InstrumentId, PositionId, Symbol, TraderId, Venue
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.model.position import Position
from nautilus_trader.portfolio import Portfolio
from nautilus_trader.test_kit.stubs.component import TestComponentStubs
from nautilus_trader.test_kit.stubs.events import TestEventStubs

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
from breezy.runtime.health import AlertState
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import (
    SubmitIntentLockHeld,
    SubmitIntentLockNotHeld,
    open_submit_intent_latch,
)
from breezy.strategy.current_rung_hold.composition import _DIAGNOSTICS_RENOTIFY_AFTER_NS
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
    instrument_id: InstrumentId,
    *,
    ask: str,
    size: int = 10,
    ts_event: int,
    bid: str = "0.01",
    bid_size: int | None = None,
) -> QuoteTick:
    displayed_bid = size if bid_size is None else bid_size
    return QuoteTick(
        instrument_id=instrument_id,
        bid_price=Price.from_str(bid),
        ask_price=Price.from_str(ask),
        bid_size=Quantity.from_int(displayed_bid),
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


class _SpyClock(TestClock):
    """Records Clock timer entry points (Cython methods are otherwise
    unpatchable from a Python test). Covers both the timedelta and ``_ns``
    variants -- installed ``resting_ladder`` uses ``set_time_alert_ns``.
    """

    def __init__(self) -> None:
        super().__init__()
        self.timer_calls: list[object] = []
        self.alert_calls: list[object] = []

    def set_timer(self, *args: object, **kwargs: object) -> object:
        self.timer_calls.append(("set_timer", args, kwargs))
        return super().set_timer(*args, **kwargs)

    def set_timer_ns(self, *args: object, **kwargs: object) -> object:
        self.timer_calls.append(("set_timer_ns", args, kwargs))
        return super().set_timer_ns(*args, **kwargs)

    def set_time_alert(self, *args: object, **kwargs: object) -> object:
        self.alert_calls.append(("set_time_alert", args, kwargs))
        return super().set_time_alert(*args, **kwargs)

    def set_time_alert_ns(self, *args: object, **kwargs: object) -> object:
        self.alert_calls.append(("set_time_alert_ns", args, kwargs))
        return super().set_time_alert_ns(*args, **kwargs)


def _register_and_start(
    *,
    store_path: Path,
    instruments: tuple[BinaryOption, ...],
    config: CurrentRungHoldConfig | None = None,
    clock: TestClock | None = None,
) -> _Rig:
    cfg = config or CurrentRungHoldConfig(
        instrument_ids=tuple(instrument.id for instrument in instruments),
    )
    strategy = CurrentRungHoldStrategy(
        cfg, trial_day_latch_factory=_open_latch_factory(store_path),
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
        sink = _RecordingSink()
        strategy.refusal_alerter = RefusalAlerter(
            strategy.refusals, site=str(strategy.id), sink=sink,
        )
        quote = _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS)
        strategy.on_quote_tick(quote)
        assert strategy.refusals.count("observation_ambiguous") == 1
        assert strategy._latch is not None
        assert strategy._latch.is_consumed(STATION, CLIMATE_DAY.isoformat()) is False
        record = strategy._latch.record(STATION, CLIMATE_DAY.isoformat())
        assert record is None
        # Skip-without-consume still surfaces through the existing alert path.
        assert len(sink.payloads) == 1
        assert sink.payloads[0].event == "OBSERVATION_AMBIGUOUS_REFUSALS"  # type: ignore[attr-defined]

        # A second ambiguous tick keeps counting and still does not latch;
        # AlertState dedupes the still-active condition.
        second_ambiguous = _quote(
            INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + NS_PER_MIN,
        )
        strategy.on_quote_tick(second_ambiguous)
        assert strategy.refusals.count("observation_ambiguous") == 2
        assert strategy._latch.is_consumed(STATION, CLIMATE_DAY.isoformat()) is False
        assert len(sink.payloads) == 1

        # L-24 later-eligibility: a hotter METAR lifts lower_f/upper_f into
        # the open-upper rung (running_extreme.py:286-301); that unambiguous
        # executable quote can still consume.
        strategy.on_data(
            _observation(
                temp_c_tenths=350,
                observed_at_ns=WINDOW_OPEN_NS + 5 * NS_PER_MIN,
            ),
        )
        later = _quote(
            OPEN_UPPER_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + 10 * NS_PER_MIN,
        )
        strategy.on_quote_tick(later)
        assert strategy._latch.is_consumed(STATION, CLIMATE_DAY.isoformat()) is True
        later_record = strategy._latch.record(STATION, CLIMATE_DAY.isoformat())
        assert later_record is not None
        # LAX/SON/12/open_upper p_hold_lower=0.7918; ask=0.40 clears break-even.
        assert later_record.reason == "taken"

    def test_observation_ambiguous_returns_before_consume_and_gate_order(
        self,
    ) -> None:
        """ARCH (a): pin the consume-site ORDERING at strategy.py.

        ``observation_ambiguous`` must return BEFORE ``consume``. The WAIT
        gates (latch-first, window, executable, running-max, current-rung)
        must run in that order before evaluate/ambiguous. If this handling
        cannot be hoisted into ``tick_eval`` without changing this order,
        it stays in the v2 strategy.
        """
        source = inspect.getsource(CurrentRungHoldStrategy.on_quote_tick)
        mark_at = source.find("_report_open_position_mark")
        consumed_at = source.find("is_consumed")
        window_at = source.find("_OUTSIDE_DECISION_WINDOW")
        exec_at = source.find("_DIAG_NOT_EXECUTABLE")
        max_at = source.find("_DIAG_NO_RUNNING_MAX_YET")
        rung_at = source.find("_DIAG_RUNG_NOT_CURRENT")
        ambiguous_at = source.find("OBSERVATION_AMBIGUOUS")
        consume_at = source.find("self._latch.consume")
        positions = {
            "mark": mark_at,
            "is_consumed": consumed_at,
            "window": window_at,
            "not_executable": exec_at,
            "no_running_max": max_at,
            "rung_not_current": rung_at,
            "observation_ambiguous": ambiguous_at,
            "consume": consume_at,
        }
        missing = [name for name, pos in positions.items() if pos == -1]
        assert missing == [], f"gate markers missing from on_quote_tick: {missing}"
        ordered = [
            "mark",
            "is_consumed",
            "window",
            "not_executable",
            "no_running_max",
            "rung_not_current",
            "observation_ambiguous",
            "consume",
        ]
        for earlier, later in itertools.pairwise(ordered):
            assert positions[earlier] < positions[later], (
                f"{earlier} must precede {later} in on_quote_tick "
                f"({positions[earlier]} >= {positions[later]})"
            )
        between = source[ambiguous_at:consume_at]
        assert "return" in between, (
            "observation_ambiguous must return before consume "
            "(return-before-consume at the strategy consume site)"
        )


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

    def test_shadow_default_never_submits_with_permit_none(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        """T6: with no ``order_submission_permit`` (the shadow default,
        ``None``), ``submit_order``/``post_order`` are never reached.
        """
        rig = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
        strategy = rig.strategy
        assert strategy._order_submission_permit is None
        submitted: list[object] = []
        strategy.submit_order = submitted.append  # type: ignore[method-assign]
        strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
        quote = _quote(INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS)
        strategy.on_quote_tick(quote)
        assert submitted == []

    def test_shadow_log_line_names_the_permit_gate(self) -> None:
        """T6 (static half): the runbook's grep target
        (``R8_OPERATOR_RUNBOOK.md`` Shadow mode section) is the literal text
        ``strategy.py``'s ``_maybe_submit`` emits -- ``Actor.log`` is
        Nautilus's own Cython logger (not stdlib ``logging``), so ``caplog``
        cannot observe it dynamically; the source text is the reliable
        check.
        """
        import inspect

        from breezy.strategy.current_rung_hold import strategy as strategy_module

        source = inspect.getsource(strategy_module.CurrentRungHoldStrategy._maybe_submit)
        assert "TAKE recorded, no submit" in source
        assert "order_submission_permit=" in source
        assert "'granted' if self._order_submission_permit is not None else 'none'" in source


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
        assert strategy._latch is not None
        assert strategy._latch.is_consumed(STATION, CLIMATE_DAY.isoformat()) is False
        record = strategy._latch.record(STATION, CLIMATE_DAY.isoformat())
        assert record is None


class TestAdmissionRefusalLatch:
    """Skip-without-consume is exact: other post-decision Refuse reasons still latch."""

    def test_edge_below_break_even_still_consumes(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        rig = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
        strategy = rig.strategy
        # R(t) = 86F exactly -- inside [86, 87], unambiguous, executable.
        strategy.on_data(_observation(temp_c_tenths=300, observed_at_ns=WINDOW_OPEN_NS - 1))
        # LAX/SON/12/interior p_hold_lower=0.6982; ask=0.90 is inside the
        # executable band but below break-even after the fee.
        quote = _quote(INTERIOR_ID, ask="0.90", ts_event=WINDOW_OPEN_NS)
        strategy.on_quote_tick(quote)
        record = strategy._latch.record(STATION, CLIMATE_DAY.isoformat())  # type: ignore[union-attr]
        assert record is not None
        assert record.reason == "edge_below_break_even"


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
        strategy._report_alerter(
            strategy.refusal_alerter,
            "current_rung_hold refusal report failed",
        )

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


#: The vocabulary `composition.install_current_rung_hold_refusal_watch`
#: actually wires the diagnostics alerter with (mirrored here, not
#: imported, so a test drifting from production would fail loudly rather
#: than the two silently diverging).
_WAIT_VOCABULARY: dict[str, str] = {
    "event_suffix": "WAIT",
    "noun": "tick(s)",
    "verb": "observed",
    "detail_note": " (pre-decision WAIT, not a refusal)",
}


def _diagnostics_alerter(
    strategy: CurrentRungHoldStrategy, sink: _RecordingSink,
) -> RefusalAlerter:
    return RefusalAlerter(
        strategy.diagnostics, site=str(strategy.id), sink=sink, **_WAIT_VOCABULARY,
    )


#: Finding 2's LOW follow-up: exercise all three `_DIAG_*` reasons, not just
#: `in_window_not_executable`. `observation_temp_c_tenths` is `None` when no
#: `StationObservation` should be pushed before the tick (leaves
#: `running_max` unset, or leaves size/ask the only gate); `0` (32F, exact
#: METAR point) pushes an observation nowhere near the interior `[86, 87]`
#: rung, so `facts.contains` is False at both ends.
_DIAGNOSTIC_CASES = (
    pytest.param("in_window_not_executable", None, "0.97", id="not_executable"),
    pytest.param("in_window_no_running_max_yet", None, "0.40", id="no_running_max_yet"),
    pytest.param("in_window_rung_not_current", 0, "0.40", id="rung_not_current"),
)


@pytest.mark.parametrize(("reason", "observation_temp_c_tenths", "ask"), _DIAGNOSTIC_CASES)
class TestDiagnosticsVisibility:
    """The three WAIT-state diagnostics (`TestDiagnosticsCounter`) stay OUT
    of `self.refusals` / the refusal alert path, but a write-only counter an
    operator can never see is exactly the blind spot this closes: each
    diagnostic must reach the alert sink through the SAME
    `RefusalAlerter`/`AlertState` mechanism `self.refusal_alerter` already
    uses, over a SEPARATE `self.diagnostics_alerter` instance bound to
    `self.diagnostics` -- never the refusal counter, and never a second,
    invented reporting path.

    Review finding 1: a WAIT state is not a refusal, so it must never be
    reported in genuine-refusal vocabulary (`..._REFUSALS` event, "order(s)
    refused as ..." detail) -- every test below pins the WAIT vocabulary
    (`_WAIT_VOCABULARY`) `composition.py` actually wires, not the refusal
    default.
    """

    @staticmethod
    def _prime(strategy: CurrentRungHoldStrategy, observation_temp_c_tenths: int | None) -> None:
        if observation_temp_c_tenths is not None:
            strategy.on_data(
                _observation(
                    temp_c_tenths=observation_temp_c_tenths, observed_at_ns=WINDOW_OPEN_NS - 1,
                ),
            )

    def test_a_diagnostic_reaches_the_sink_in_wait_not_refusal_vocabulary(
        self,
        store_path: Path,
        interior_instrument: BinaryOption,
        reason: str,
        observation_temp_c_tenths: int | None,
        ask: str,
    ) -> None:
        rig = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
        strategy = rig.strategy
        self._prime(strategy, observation_temp_c_tenths)
        sink = _RecordingSink()
        strategy.diagnostics_alerter = _diagnostics_alerter(strategy, sink)

        quote = _quote(INTERIOR_ID, ask=ask, ts_event=WINDOW_OPEN_NS)
        strategy.on_quote_tick(quote)

        assert strategy.diagnostics.count(reason) == 1
        assert len(sink.payloads) == 1
        payload = sink.payloads[0]
        assert payload.event == f"{reason.upper()}_WAIT"  # type: ignore[attr-defined]
        assert "refused" not in payload.detail  # type: ignore[attr-defined]
        assert "not a refusal" in payload.detail  # type: ignore[attr-defined]

    def test_a_diagnostic_never_reaches_the_refusal_alerter(
        self,
        store_path: Path,
        interior_instrument: BinaryOption,
        reason: str,
        observation_temp_c_tenths: int | None,
        ask: str,
    ) -> None:
        rig = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
        strategy = rig.strategy
        self._prime(strategy, observation_temp_c_tenths)
        refusal_sink = _RecordingSink()
        diagnostics_sink = _RecordingSink()
        strategy.refusal_alerter = RefusalAlerter(
            strategy.refusals, site=str(strategy.id), sink=refusal_sink,
        )
        strategy.diagnostics_alerter = _diagnostics_alerter(strategy, diagnostics_sink)

        quote = _quote(INTERIOR_ID, ask=ask, ts_event=WINDOW_OPEN_NS)
        strategy.on_quote_tick(quote)

        assert len(diagnostics_sink.payloads) == 1
        assert refusal_sink.payloads == []

    def test_no_diagnostics_alerter_wired_is_a_no_op_not_a_raise(
        self,
        store_path: Path,
        interior_instrument: BinaryOption,
        reason: str,
        observation_temp_c_tenths: int | None,
        ask: str,
    ) -> None:
        rig = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
        strategy = rig.strategy
        self._prime(strategy, observation_temp_c_tenths)
        assert strategy.diagnostics_alerter is None

        quote = _quote(INTERIOR_ID, ask=ask, ts_event=WINDOW_OPEN_NS)
        strategy.on_quote_tick(quote)  # must not raise

        assert strategy.diagnostics.count(reason) == 1

    def test_a_second_diagnostic_for_the_same_reason_does_not_re_notify(
        self,
        store_path: Path,
        interior_instrument: BinaryOption,
        reason: str,
        observation_temp_c_tenths: int | None,
        ask: str,
    ) -> None:
        rig = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
        strategy = rig.strategy
        self._prime(strategy, observation_temp_c_tenths)
        sink = _RecordingSink()
        strategy.diagnostics_alerter = _diagnostics_alerter(strategy, sink)

        first = _quote(INTERIOR_ID, ask=ask, ts_event=WINDOW_OPEN_NS)
        strategy.on_quote_tick(first)
        second = _quote(INTERIOR_ID, ask=ask, ts_event=WINDOW_OPEN_NS + NS_PER_MIN)
        strategy.on_quote_tick(second)

        assert strategy.diagnostics.count(reason) == 2
        assert len(sink.payloads) == 1


class TestDiagnosticsSnapshotOnStop:
    """Review finding 2: `AlertState`'s false->true-then-renotify semantics
    (`_report_alerter`) tell an operator a gate fired at least
    once, and diagnostics re-notify on a 15-minute cadence, but the alert
    stream still cannot recover exact per-gate magnitudes after a covered
    afternoon. `on_stop`
    closes that gap: it logs `self.log.info(self._diagnostics_snapshot_message())`
    (a single line naming the full, exact per-gate tally) on every
    shutdown, not only a crash.

    `Actor.log` is Nautilus's own Cython logger (see
    `test_shadow_log_line_names_the_permit_gate`'s docstring) -- `caplog`
    cannot observe it dynamically, so this pins the MESSAGE the extracted,
    directly-callable `_diagnostics_snapshot_message` builds (dynamically,
    with real recorded counts), and separately pins -- statically, same
    convention as the permit-gate test -- that `on_stop`'s source actually
    passes that message to `self.log.info`.
    """

    def test_the_snapshot_message_recovers_per_gate_magnitudes_after_a_simulated_afternoon(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        rig = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
        strategy = rig.strategy

        # `in_window_not_executable` fires N=5 times (ask outside the
        # executable band); `in_window_rung_not_current` fires M=3 times
        # (an observation far from this instrument's rung) -- two DIFFERENT
        # gates with two DIFFERENT magnitudes over one simulated afternoon,
        # exactly what a write-once alert cannot distinguish.
        for i in range(5):
            quote = _quote(INTERIOR_ID, ask="0.97", ts_event=WINDOW_OPEN_NS + i * NS_PER_MIN)
            strategy.on_quote_tick(quote)

        strategy.on_data(
            _observation(temp_c_tenths=0, observed_at_ns=WINDOW_OPEN_NS + 10 * NS_PER_MIN),
        )
        for i in range(3):
            quote = _quote(
                INTERIOR_ID, ask="0.40", ts_event=WINDOW_OPEN_NS + (20 + i) * NS_PER_MIN,
            )
            strategy.on_quote_tick(quote)

        assert strategy.diagnostics.count("in_window_not_executable") == 5
        assert strategy.diagnostics.count("in_window_rung_not_current") == 3

        message = strategy._diagnostics_snapshot_message()

        assert "in_window_not_executable" in message
        assert "5" in message
        assert "in_window_rung_not_current" in message
        assert "3" in message

    def test_the_snapshot_message_names_a_zero_tally_not_just_silence(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        """An empty snapshot must still be a LINE an analyst can find --
        never indistinguishable from "on_stop never ran".
        """
        rig = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
        strategy = rig.strategy

        message = strategy._diagnostics_snapshot_message()

        assert "current_rung_hold diagnostics snapshot" in message
        assert strategy.diagnostics.total() == 0

    def test_on_stop_logs_the_snapshot_message(self) -> None:
        """Static half, same convention as
        `test_shadow_log_line_names_the_permit_gate`: pins that `on_stop`
        actually reaches the log with the computed message, since
        `caplog` cannot observe `Actor.log` dynamically.
        """
        import inspect

        source = inspect.getsource(CurrentRungHoldStrategy.on_stop)
        assert "self.log.info(self._diagnostics_snapshot_message())" in source


def _seed_open_long(
    strategy: CurrentRungHoldStrategy,
    instrument: BinaryOption,
    *,
    px: str = "0.40",
    qty: int = 1,
) -> tuple[OrderFilled, Position]:
    """Put one LONG into the strategy cache the same way sibling weather
    tests do (`Position(instrument, fill)` + `cache.add_position`).

    The engine would have done this before `on_order_filled` /
    `on_position_opened` fire (`trading/strategy.pyx` `handle_event` is
    a post-bookkeeping callback). Tests that drive those handlers
    directly still need the cache row, because the later quote-tick
    mark reads `Cache.positions_open` / `Cache.calculate_unrealized_pnl`.
    """
    position_id = PositionId("P-O1-OBS")
    order = strategy.order_factory.limit(
        instrument_id=instrument.id,
        order_side=OrderSide.BUY,
        quantity=instrument.make_qty(qty),
        price=instrument.make_price(px),
    )
    strategy.cache.add_order(order, position_id=position_id)
    order.apply(TestEventStubs.order_submitted(order))
    order.apply(TestEventStubs.order_accepted(order))
    fill = TestEventStubs.order_filled(
        order,
        instrument,
        position_id=position_id,
        last_px=instrument.make_price(px),
    )
    order.apply(fill)
    strategy.cache.update_order(order)
    position = Position(instrument, fill)
    strategy.cache.add_position(position, OmsType.NETTING)
    return fill, position


_FORBIDDEN_ACTIONS: tuple[str, ...] = (
    "submit_order",
    "close_position",
    "close_all_positions",
    "cancel_order",
    "modify_order",
    "set_timer",
    "set_timer_ns",
    "set_time_alert",
    "set_time_alert_ns",
)

_OBSERVABILITY_METHOD_NAMES: tuple[str, ...] = (
    "on_order_filled",
    "on_position_opened",
    "_report_order_filled",
    "_report_position_opened",
    "_report_open_position_mark",
    "_report_alerter",
    "_run_observability",
    "_order_filled_message",
    "_position_opened_message",
    "_open_position_mark_message",
)

_TALLY_CALL_NAMES: frozenset[str] = frozenset(
    {
        "ScoredTrial",
        "score_live_trials",
        "scored_trial_store",
        "family_tally",
        "write_scored_trials",
    },
)


def _install_action_spies(
    strategy: CurrentRungHoldStrategy,
) -> dict[str, list[object]]:
    """Shadow every forbidden Strategy entry point on the Python instance.

    Cython ``Strategy.submit_order`` (etc.) is read-only on the C class, but a
    Python subclass stores the shadow in ``__dict__``, so a Python handler
    that called ``self.submit_order(...)`` is observed. ``set_timer`` /
    ``set_time_alert`` do not exist on Strategy -- they live on Clock -- so
    tests that need the clock path pass a ``_SpyClock``.
    """
    captured: dict[str, list[object]] = {name: [] for name in _FORBIDDEN_ACTIONS}
    for name, bucket in captured.items():
        setattr(strategy, name, bucket.append)
    return captured


def _assert_no_forbidden_actions(
    captured: dict[str, list[object]],
    clock: TestClock,
) -> None:
    for name, calls in captured.items():
        assert calls == [], f"{name} was invoked: {calls!r}"
    if isinstance(clock, _SpyClock):
        assert clock.timer_calls == []
        assert clock.alert_calls == []


def _wire_position_alerter(
    strategy: CurrentRungHoldStrategy,
    sink: _RecordingSink,
    *,
    renotify_after_ns: int = _DIAGNOSTICS_RENOTIFY_AFTER_NS,
) -> None:
    strategy.position_alerter = RefusalAlerter(
        strategy.position_events,
        site=str(strategy.id),
        sink=sink,
        state=AlertState(renotify_after_ns=renotify_after_ns),
        event_suffix="POSITION",
        noun="event(s)",
        verb="observed",
        detail_note=" (log-only, never an order)",
    )


def _spy_mark_messages(strategy: CurrentRungHoldStrategy) -> list[str]:
    """Record every ``_open_position_mark_message`` call (the Decimal/Money
    + f-string path). ``Actor.log`` is Cython, so this is the observable
    proxy for the raw mark log line.
    """
    lines: list[str] = []
    original = strategy._open_position_mark_message

    def _wrapped(position: Position, tick: QuoteTick) -> str:
        line = original(position, tick)
        lines.append(line)
        return line

    strategy._open_position_mark_message = _wrapped  # type: ignore[method-assign]
    return lines


def _consume_taken(
    strategy: CurrentRungHoldStrategy,
    instrument: BinaryOption,
) -> None:
    assert strategy._latch is not None
    strategy._latch.consume(
        STATION,
        CLIMATE_DAY.isoformat(),
        latched_at_ns=WINDOW_OPEN_NS,
        instrument_id=str(instrument.id),
        ask=Decimal("0.40"),
        reason="taken",
    )


class TestOpenPositionObservability:
    """O-1: log-only fill / position-open / ask-marked unrealised PnL.

    `Actor.log` is Nautilus's Cython logger (`caplog` cannot observe it),
    so these tests pin (a) the public `position_events` counter the
    handlers increment, (b) extracted message builders, (c) the alert
    sink, and (d) `inspect.getsource` that the handlers actually log
    those messages -- the same convention as
    `test_on_stop_logs_the_snapshot_message`.
    """

    def test_a_synthetic_fill_produces_the_position_opened_log(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        rig = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
        strategy = rig.strategy
        submitted: list[object] = []
        strategy.submit_order = submitted.append
        fill, position = _seed_open_long(strategy, interior_instrument)
        sink = _RecordingSink()
        strategy.position_alerter = RefusalAlerter(
            strategy.position_events,
            site=str(strategy.id),
            sink=sink,
            event_suffix="POSITION",
            noun="event(s)",
            verb="observed",
            detail_note=" (log-only, never an order)",
        )

        strategy.on_order_filled(fill)
        opened = TestEventStubs.position_opened(position)
        strategy.on_position_opened(opened)

        assert strategy.position_events.count("order_filled") == 1
        assert strategy.position_events.count("position_opened") == 1
        filled_line = strategy._order_filled_message(fill)
        opened_line = strategy._position_opened_message(opened)
        assert str(interior_instrument.id) in filled_line
        assert str(fill.last_qty) in filled_line
        assert str(interior_instrument.id) in opened_line
        assert str(opened.quantity) in opened_line
        assert "avg_px_open=" in opened_line
        assert str(opened.avg_px_open) in opened_line
        assert len(sink.payloads) >= 1
        events = {payload.event for payload in sink.payloads}  # type: ignore[attr-defined]
        assert "POSITION_OPENED_POSITION" in events
        assert submitted == []

    def test_a_later_quote_logs_ask_marked_unrealized_pnl_and_bid_size(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        """`Cache.calculate_unrealized_pnl` marks a LONG at the ask
        (`cache.pyx:1523-1528`). The log line must say so, must carry
        that ask-marked value (not the bid-marked one), and must also
        carry the current top-of-book bid size so a vanishing bid is
        visible independently of the mark.
        """
        rig = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
        strategy = rig.strategy
        submitted: list[object] = []
        strategy.submit_order = submitted.append
        _fill, position = _seed_open_long(strategy, interior_instrument, px="0.40")
        assert strategy._latch is not None
        strategy._latch.consume(
            STATION,
            CLIMATE_DAY.isoformat(),
            latched_at_ns=WINDOW_OPEN_NS,
            instrument_id=str(interior_instrument.id),
            ask=Decimal("0.40"),
            reason="taken",
        )
        record_before = strategy._latch.record(STATION, CLIMATE_DAY.isoformat())

        quote = _quote(
            INTERIOR_ID,
            ask="0.30",
            bid="0.01",
            size=10,
            bid_size=0,
            ts_event=WINDOW_OPEN_NS + 10 * NS_PER_MIN,
        )
        strategy.cache.add_quote_tick(quote)
        ask_pnl = strategy.cache.calculate_unrealized_pnl(position)
        bid_pnl = position.unrealized_pnl(quote.bid_price)
        assert ask_pnl is not None
        assert str(ask_pnl) != str(bid_pnl)

        strategy.on_quote_tick(quote)

        assert strategy.position_events.count("open_position_ask_mark") == 1
        line = strategy._open_position_mark_message(position, quote)
        assert str(ask_pnl) in line
        assert str(bid_pnl) not in line
        assert "mark=ask" in line
        assert "bid-marked" not in line.lower()
        assert "mark=bid" not in line
        assert "bid_size=0" in line
        record_after = strategy._latch.record(STATION, CLIMATE_DAY.isoformat())
        assert record_after == record_before
        assert strategy.refusals.total() == 0
        assert submitted == []

    def test_open_position_logging_does_not_disturb_the_latch_first_return(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        """The mark must run BEFORE `latch.is_consumed` returns, otherwise
        a filled station-day is silent until next-day NWS score.
        """
        import inspect

        source = inspect.getsource(CurrentRungHoldStrategy.on_quote_tick)
        mark_at = source.find("_report_open_position_mark")
        latch_at = source.find("is_consumed")
        assert mark_at != -1
        assert latch_at != -1
        assert mark_at < latch_at

    def test_handlers_call_through_to_the_empty_nautilus_stubs(
        self,
    ) -> None:
        """Installed `trading/strategy.pyx:723-767`: `on_order_filled` /
        `on_position_opened` are empty "optionally override" stubs;
        `handle_event` (`:1970-1974`) dispatches to them then to
        `on_order_event` / `on_position_event`. Raising inside the
        override would skip those follow-on handlers (`:1983-1986`
        re-raises). Call `super()` and wrap reporting so bookkeeping
        dispatch is preserved.
        """
        import inspect

        filled_src = inspect.getsource(CurrentRungHoldStrategy.on_order_filled)
        opened_src = inspect.getsource(CurrentRungHoldStrategy.on_position_opened)
        assert "super().on_order_filled" in filled_src
        assert "super().on_position_opened" in opened_src

    def test_observability_failure_does_not_raise(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        class _Boom:
            def report(self, *, now_ns: int) -> int:
                raise RuntimeError("boom")

        rig = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
        strategy = rig.strategy
        fill, position = _seed_open_long(strategy, interior_instrument)
        strategy.position_alerter = _Boom()  # type: ignore[assignment]
        strategy.on_order_filled(fill)
        strategy.on_position_opened(TestEventStubs.position_opened(position))
        quote = _quote(
            INTERIOR_ID, ask="0.30", bid_size=0, ts_event=WINDOW_OPEN_NS,
        )
        strategy.cache.add_quote_tick(quote)
        strategy.on_quote_tick(quote)
        assert strategy.position_events.count("order_filled") == 1
        assert strategy.position_events.count("position_opened") == 1
        assert strategy.position_events.count("open_position_ask_mark") == 1

    def test_no_open_position_does_not_record_a_mark(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        rig = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
        strategy = rig.strategy
        quote = _quote(INTERIOR_ID, ask="0.99", ts_event=WINDOW_OPEN_NS)
        strategy.cache.add_quote_tick(quote)
        strategy.on_quote_tick(quote)
        assert strategy.position_events.count("open_position_ask_mark") == 0

    def test_observability_source_text_does_not_name_order_or_timer_tokens(
        self,
    ) -> None:
        """Smoke layer only: a literal-token search of handler source.

        This does not prove the handlers cannot submit or flatten -- an
        alias, ``getattr``, or ``self.clock.set_timer`` would stay green.
        The behavioural spies in
        ``test_observability_handlers_do_not_submit_flatten_or_arm_timers``
        are the live-trading invariant.
        """
        forbidden = _FORBIDDEN_ACTIONS
        for name in (
            "on_order_filled",
            "on_position_opened",
            "_report_open_position_mark",
            "_report_order_filled",
            "_report_position_opened",
            "_run_observability",
        ):
            source = inspect.getsource(getattr(CurrentRungHoldStrategy, name))
            for token in forbidden:
                assert token not in source, f"{name} contains {token}"
        reporter_src = inspect.getsource(CurrentRungHoldStrategy._report_alerter)
        for token in forbidden:
            assert token not in reporter_src, f"reporter contains {token}"

    def test_observability_source_text_does_not_name_tally_tokens(self) -> None:
        """Smoke layer only: module source does not contain tally names.

        The real guarantee is that the new methods make no persistence /
        tally call -- see
        ``test_observability_methods_do_not_call_tally_or_order_entry_points``.
        """
        import breezy.strategy.current_rung_hold.strategy as strategy_module

        source = inspect.getsource(strategy_module)
        for token in _TALLY_CALL_NAMES:
            assert token not in source

    def test_handlers_log_the_extracted_messages(self) -> None:
        filled_src = inspect.getsource(CurrentRungHoldStrategy._report_order_filled)
        opened_src = inspect.getsource(CurrentRungHoldStrategy._report_position_opened)
        mark_src = inspect.getsource(CurrentRungHoldStrategy._report_open_position_mark)
        message_src = inspect.getsource(
            CurrentRungHoldStrategy._open_position_mark_message,
        )
        assert "self.log.info(self._order_filled_message" in filled_src
        assert "self.log.info(self._position_opened_message" in opened_src
        assert "self.log.info(self._open_position_mark_message" in mark_src
        assert "calculate_unrealized_pnl" in message_src
        assert "mark=ask" in message_src

    def test_an_open_position_mark_log_is_throttled_to_the_alerter_cadence(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        """Reuse AlertState dedupe/renotify -- do not invent a second throttle.

        A standing open position must not emit the Decimal/Money/f-string
        mark line on every tick. The first tick (false->true) logs; a later
        tick inside the production 15-minute diagnostics cadence does not;
        a tick past that cadence logs again. The counter still increments
        every tick so the re-notify detail can grow.
        """
        rig = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
        strategy = rig.strategy
        _seed_open_long(strategy, interior_instrument, px="0.40")
        _consume_taken(strategy, interior_instrument)
        sink = _RecordingSink()
        _wire_position_alerter(strategy, sink)
        lines = _spy_mark_messages(strategy)

        first = _quote(
            INTERIOR_ID,
            ask="0.30",
            bid_size=0,
            ts_event=WINDOW_OPEN_NS,
        )
        strategy.cache.add_quote_tick(first)
        strategy.on_quote_tick(first)

        assert strategy.position_events.count("open_position_ask_mark") == 1
        assert len(lines) == 1
        assert "mark=ask" in lines[0]
        mark_events = [
            payload for payload in sink.payloads
            if getattr(payload, "event", None) == "OPEN_POSITION_ASK_MARK_POSITION"
        ]
        assert len(mark_events) == 1

        second = _quote(
            INTERIOR_ID,
            ask="0.31",
            bid_size=0,
            ts_event=WINDOW_OPEN_NS + NS_PER_MIN,
        )
        strategy.cache.add_quote_tick(second)
        strategy.on_quote_tick(second)

        assert strategy.position_events.count("open_position_ask_mark") == 2
        assert len(lines) == 1
        mark_events = [
            payload for payload in sink.payloads
            if getattr(payload, "event", None) == "OPEN_POSITION_ASK_MARK_POSITION"
        ]
        assert len(mark_events) == 1

        later_ns = WINDOW_OPEN_NS + _DIAGNOSTICS_RENOTIFY_AFTER_NS
        strategy.clock.set_time(later_ns)
        third = _quote(
            INTERIOR_ID,
            ask="0.32",
            bid_size=0,
            ts_event=later_ns,
        )
        strategy.cache.add_quote_tick(third)
        strategy.on_quote_tick(third)

        assert strategy.position_events.count("open_position_ask_mark") == 3
        assert len(lines) == 2
        mark_events = [
            payload for payload in sink.payloads
            if getattr(payload, "event", None) == "OPEN_POSITION_ASK_MARK_POSITION"
        ]
        assert len(mark_events) == 2

    def test_a_sibling_position_event_renotify_does_not_unthrottle_the_mark_log(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        """Fill/open share the position alerter with the mark. A sibling
        key's 15-minute re-notify must not force a mark log while the mark
        key is still inside its own window.
        """
        rig = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
        strategy = rig.strategy
        fill, _position = _seed_open_long(strategy, interior_instrument, px="0.40")
        _consume_taken(strategy, interior_instrument)
        sink = _RecordingSink()
        _wire_position_alerter(strategy, sink)
        lines = _spy_mark_messages(strategy)

        strategy.on_order_filled(fill)

        ten_min = WINDOW_OPEN_NS + 10 * NS_PER_MIN
        strategy.clock.set_time(ten_min)
        first = _quote(
            INTERIOR_ID, ask="0.30", bid_size=0, ts_event=ten_min,
        )
        strategy.cache.add_quote_tick(first)
        strategy.on_quote_tick(first)
        assert len(lines) == 1

        sibling_renotify_ns = WINDOW_OPEN_NS + _DIAGNOSTICS_RENOTIFY_AFTER_NS
        strategy.clock.set_time(sibling_renotify_ns)
        second = _quote(
            INTERIOR_ID, ask="0.31", bid_size=0, ts_event=sibling_renotify_ns,
        )
        strategy.cache.add_quote_tick(second)
        strategy.on_quote_tick(second)

        assert strategy.position_events.count("open_position_ask_mark") == 2
        assert len(lines) == 1
        sibling_events = [
            payload.event for payload in sink.payloads  # type: ignore[attr-defined]
        ]
        assert "ORDER_FILLED_POSITION" in sibling_events
        assert sibling_events.count("OPEN_POSITION_ASK_MARK_POSITION") == 1

    def test_no_open_position_mark_path_does_not_build_a_mark_line(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        """Empty-cache ticks must stay a positions_open lookup + return."""
        rig = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
        strategy = rig.strategy
        lines = _spy_mark_messages(strategy)
        quote = _quote(INTERIOR_ID, ask="0.99", ts_event=WINDOW_OPEN_NS)
        strategy.cache.add_quote_tick(quote)
        strategy.on_quote_tick(quote)
        assert strategy.position_events.count("open_position_ask_mark") == 0
        assert lines == []

    def test_mark_label_is_honest_when_unrealized_pnl_is_none(
        self, store_path: Path, interior_instrument: BinaryOption,
    ) -> None:
        """``calculate_unrealized_pnl`` returns None when the cache has no
        quote (`cache.pyx:1518`). Printing ``mark=ask`` next to
        ``unrealized_pnl=None`` would claim a mark that was never computed.
        """
        rig = _register_and_start(store_path=store_path, instruments=(interior_instrument,))
        strategy = rig.strategy
        _fill, position = _seed_open_long(strategy, interior_instrument, px="0.40")
        quote = _quote(
            INTERIOR_ID, ask="0.30", bid_size=0, ts_event=WINDOW_OPEN_NS,
        )
        assert strategy.cache.quote_tick(interior_instrument.id) is None
        assert strategy.cache.calculate_unrealized_pnl(position) is None

        line = strategy._open_position_mark_message(position, quote)

        assert "unrealized_pnl=None" in line
        assert "mark=ask" not in line
        assert "mark=unavailable" in line

    @pytest.mark.parametrize(
        "path",
        ("fill", "opened", "later_quote_mark", "position_change"),
    )
    def test_observability_handlers_do_not_submit_flatten_or_arm_timers(
        self,
        store_path: Path,
        interior_instrument: BinaryOption,
        path: str,
    ) -> None:
        """Live-trading invariant: the new handlers never reach an order or
        timer entry point. Runtime spies, not a source substring search.
        """
        clock = _SpyClock()
        rig = _register_and_start(
            store_path=store_path,
            instruments=(interior_instrument,),
            clock=clock,
        )
        strategy = rig.strategy
        fill, position = _seed_open_long(strategy, interior_instrument)
        sink = _RecordingSink()
        _wire_position_alerter(strategy, sink)
        captured = _install_action_spies(strategy)

        if path == "fill":
            strategy.on_order_filled(fill)
        elif path == "opened":
            strategy.on_position_opened(TestEventStubs.position_opened(position))
        elif path == "later_quote_mark":
            _consume_taken(strategy, interior_instrument)
            quote = _quote(
                INTERIOR_ID, ask="0.30", bid_size=0, ts_event=WINDOW_OPEN_NS,
            )
            strategy.cache.add_quote_tick(quote)
            strategy.on_quote_tick(quote)
        elif path == "position_change":
            strategy.position_events.record("position_opened")
            strategy._report_alerter(
                strategy.position_alerter,
                "current_rung_hold position report failed",
            )
        else:  # pragma: no cover
            raise AssertionError(path)

        _assert_no_forbidden_actions(captured, clock)

    def test_observability_methods_do_not_call_tally_or_order_entry_points(
        self,
    ) -> None:
        """AST of the new methods' call targets: no tally persistence and no
        order/timer entry point. Complements the runtime spies; an alias or
        ``getattr`` still needs those spies. The guarantee this test states
        is "no persistence call in these methods".
        """
        forbidden = frozenset(_FORBIDDEN_ACTIONS) | _TALLY_CALL_NAMES
        seen: set[str] = set()
        for name in _OBSERVABILITY_METHOD_NAMES:
            method = getattr(CurrentRungHoldStrategy, name, None)
            if method is None:
                continue
            tree = ast.parse(textwrap.dedent(inspect.getsource(method)))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if isinstance(func, ast.Name):
                    seen.add(func.id)
                elif isinstance(func, ast.Attribute):
                    seen.add(func.attr)
        assert not (seen & forbidden), f"forbidden call targets: {seen & forbidden}"
