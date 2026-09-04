"""Study-replay equivalence: the SAME (station-day, ts_event, ask, hour_lst,
width_code, m_code) must be selected by `mb_current_rung_edge_study.py`'s own
offline selection functions (`build_current_rung_trials`/`classify_width`)
and by `CurrentRungHoldStrategy.on_quote_tick` replaying the identical
`StationObservation` + `QuoteTick` series.

Lag semantics (see `strategy.py`'s module docstring, "Lag semantics vs.
mb_current_rung_edge_study.py"): the study reads its entry ask at
`t + lag_minutes` (`find_lagged_entry`, `:479-490`); the live strategy applies
NO synthetic lag -- it prices whatever tick arrives, at that tick's own
`ts_event`. This fixture is built with `lag_minutes=0` and a single window
instant equal to the tick's own `ts_event`, which is the one configuration
under which the two selection paths are provably equivalent; a nonzero
`lag_minutes` measures a different execution model this strategy does not
implement, and is out of scope here (stated, not papered over).
"""

from __future__ import annotations

import datetime as dt
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from unittest.mock import ANY

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
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import open_submit_intent_latch
from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
from breezy.strategy.current_rung_hold.strategy import CurrentRungHoldStrategy
from breezy.strategy.current_rung_hold.trial_day_latch import TrialDayLatch, open_trial_day_latch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, (REPO_ROOT / "scripts/analysis").as_posix())

from h4_preliminary_economic_read import DepthObservation, Rung
from mb_current_rung_edge_study import (
    WIDTH_INTERIOR,
    build_current_rung_trials,
    classify_width,
    first_executable_trial,
)

STATION = "LAX"
ICAO = "KLAX"
STD_OFFSET_HOURS = -8.0
CLIMATE_DAY = dt.date(2026, 9, 4)
# 2026-09-04T20:00:00Z == 12:00:00 LST (PST, -8h) -- the window's opening instant.
WINDOW_OPEN_NS = 1_788_552_000_000_000_000
INSTRUMENT_ID = InstrumentId(Symbol("lax-86-87"), Venue("POLYMARKET_US"))
STUDY_INSTRUMENT_ID = "lax-86-87"


def _ns_to_utc(ns: int) -> dt.datetime:
    seconds, nanoseconds = divmod(ns, 1_000_000_000)
    return dt.datetime.fromtimestamp(seconds, tz=dt.UTC) + dt.timedelta(
        microseconds=nanoseconds // 1_000,
    )


@contextmanager
def _latch_context(store_path: Path) -> Iterator[TrialDayLatch]:
    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
        yield open_trial_day_latch(intent_latch)


def _interior_instrument() -> BinaryOption:
    increment = Price.from_str("0.01")
    size_increment = Quantity.from_str("1")
    return BinaryOption(
        instrument_id=INSTRUMENT_ID,
        raw_symbol=INSTRUMENT_ID.symbol,
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
        maker_fee=Decimal("0.06"),
        taker_fee=Decimal("0.06"),
        ts_event=0,
        ts_init=0,
        info={
            WEATHER_FACTS_STATUS_KEY: WEATHER_FACTS_STATUS_KNOWN,
            SETTLEMENT_STATION_KEY: STATION,
            CLIMATE_DAY_KEY: CLIMATE_DAY.isoformat(),
            MEASURE_KEY: "high",
            STRIKE_LOWER_F_KEY: 86,
            STRIKE_UPPER_F_KEY: 87,
        },
    )


def test_the_studys_offline_selection_and_the_live_replay_agree(
    tmp_path: Path,
) -> None:
    obs_ns = WINDOW_OPEN_NS - 1
    tick_ns = WINDOW_OPEN_NS

    # ---- 1. The study's OWN selection, over a hand-built fixture. --------
    ladder = (
        Rung(
            instrument_id=STUDY_INSTRUMENT_ID,
            city=STATION,
            climate_day=CLIMATE_DAY,
            lower_f=86,
            upper_f=87,
        ),
    )
    tick_utc = _ns_to_utc(tick_ns)
    depth = {
        STUDY_INSTRUMENT_ID: (
            DepthObservation(
                instrument_id=STUDY_INSTRUMENT_ID,
                ts_event=tick_utc,
                best_ask=0.40,
                ask_ladder=((0.40, 10.0),),
                best_bid=0.01,
            ),
        ),
    }
    series = ((_ns_to_utc(obs_ns), 86),)
    trials = build_current_rung_trials(
        city=STATION,
        climate_day=CLIMATE_DAY,
        ladder=ladder,
        depth=depth,
        series=series,
        window_instants=[tick_utc],
        settled_f=None,
        lag_minutes=0,
        std_utc_offset_hours=STD_OFFSET_HOURS,
        archive={},
    )
    expected = first_executable_trial(trials)
    assert expected is not None
    assert expected.rung_instrument_id == STUDY_INSTRUMENT_ID
    assert expected.width == WIDTH_INTERIOR
    assert expected.entry_ask == pytest.approx(0.40)
    assert expected.entry_ts == tick_utc
    study_width, study_m = classify_width(ladder[0], expected.running_f)
    assert (study_width, study_m) == (WIDTH_INTERIOR, 0)
    # `strategy.py` uses an int width code (0=interior/1=open_upper/
    # 2=open_lower); map the study's string width the same way.
    expected_width_code = 0
    expected_m_code = study_m

    # ---- 2. The SAME series, replayed live through the strategy. ---------
    store_path = tmp_path / "state.db"
    instrument = _interior_instrument()
    cfg = CurrentRungHoldConfig(instrument_ids=(instrument.id,))
    strategy = CurrentRungHoldStrategy(
        cfg, trial_day_latch_factory=lambda: _latch_context(store_path),
    )
    clock = TestClock()
    clock.set_time(tick_ns)
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

    captured_inputs: list[object] = []
    real_evaluate_decision = sys.modules[
        "breezy.strategy.current_rung_hold.strategy"
    ].evaluate_decision

    def _spy(inputs: object) -> object:
        captured_inputs.append(inputs)
        return real_evaluate_decision(inputs)

    strategy_module = sys.modules["breezy.strategy.current_rung_hold.strategy"]
    strategy_module.evaluate_decision = _spy  # type: ignore[attr-defined]
    try:
        strategy.on_data(
            StationObservation(
                station=ICAO,
                observed_at_ns=obs_ns,
                received_at_ns=obs_ns + 1,
                temp_c_tenths=300,  # 30.0C -> 86F exactly (METAR, exact point)
                precision_c_tenths=5,
                is_metar=True,
                source_channel="iem_asos_metar",
                assumed_publication_lag_ns=1,
            )
        )
        quote = QuoteTick(
            instrument_id=INSTRUMENT_ID,
            bid_price=Price.from_str("0.01"),
            ask_price=Price.from_str("0.40"),
            bid_size=Quantity.from_int(10),
            ask_size=Quantity.from_int(10),
            ts_event=tick_ns,
            ts_init=tick_ns,
        )
        strategy.on_quote_tick(quote)
    finally:
        strategy_module.evaluate_decision = real_evaluate_decision  # type: ignore[attr-defined]

    assert len(captured_inputs) == 1
    live_inputs = captured_inputs[0]

    record = strategy._latch.record(STATION, CLIMATE_DAY.isoformat())  # type: ignore[union-attr]
    assert record is not None
    assert record.instrument_id == str(INSTRUMENT_ID)
    assert record.ask == Decimal(str(expected.entry_ask))
    assert record.latched_at_ns == ANY

    # ---- 3. Equivalence: SAME station-day, ts_event, ask, hour_lst, ------
    #         width_code, m_code.
    assert live_inputs.station == STATION  # type: ignore[attr-defined]
    assert live_inputs.climate_day == CLIMATE_DAY  # type: ignore[attr-defined]
    assert live_inputs.now_ns == tick_ns  # type: ignore[attr-defined]
    assert live_inputs.ask == Decimal(str(expected.entry_ask))  # type: ignore[attr-defined]
    assert live_inputs.hour_lst == expected.hour_lst  # type: ignore[attr-defined]
    assert live_inputs.width_code == expected_width_code  # type: ignore[attr-defined]
    assert live_inputs.m_code == expected_m_code  # type: ignore[attr-defined]
