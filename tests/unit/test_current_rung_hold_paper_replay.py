"""RED tests 1-4, 7-11 plus the venue-skip and no-hand-computation guards
(`docs/plans/PAPER_REPLAY_6B_BRIEF_2026-09-04.md`).

Library-level tests (`breezy.runtime.paper_replay`) are pure/fast; driver-
level tests dynamically load `scripts/analysis/current_rung_hold_paper_replay.py`
the same way `test_live_family_tally.py` loads its module (`scripts/` is
unimportable as a package from `src/breezy`).
"""

from __future__ import annotations

import ast
import datetime as dt
import importlib.util
import sys
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import BookOrder, InstrumentClose, OrderBookDepth10, QuoteTick
from nautilus_trader.model.enums import AssetClass, InstrumentCloseType, OrderSide
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Money, Price, Quantity

from breezy.adapters.polymarket_us.parsing import (
    FEE_COEFFICIENT_KEY,
    FEE_SCHEDULE_STATUS_KEY,
    FEE_SCHEDULE_STATUS_KNOWN,
)
from breezy.domain.nws_climate_day import CLIMATE_DAY_SCHEMA_VERSION, NwsClimateDay
from breezy.domain.weather_bucket_facts import (
    CLIMATE_DAY_KEY,
    MEASURE_KEY,
    SETTLEMENT_STATION_KEY,
    STRIKE_LOWER_F_KEY,
    STRIKE_UPPER_F_KEY,
    WEATHER_FACTS_STATUS_KEY,
    WEATHER_FACTS_STATUS_KNOWN,
    read_weather_bucket_facts,
)
from breezy.runtime.backtest_feed import as_backtest_data
from breezy.runtime.backtest_harness import SettlementInvariantError, backtest
from breezy.runtime.paper_replay import (
    PRECISION_ARMS,
    ForeignReplayDataError,
    ImpossibleFillPriceError,
    PaperReplayInputs,
    QuoteOnlyReplayError,
    ReplayEntryContext,
    build_paper_replay_config,
    filled_trials_from_engine,
    format_roi_bound_for_paper_replay,
    load_replay_observations,
)
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import open_submit_intent_latch
from breezy.settlement.roi_bound import ROIBound, ROIBoundUnderpowered
from breezy.settlement.trial_scorer import FilledTrial, ScoredTrial, score_trial
from breezy.strategy.current_rung_hold.backtest_only import CurrentRungHoldBacktestStrategy
from breezy.strategy.current_rung_hold.config import (
    STALE_OBSERVATION_MINUTES,
    CurrentRungHoldConfig,
)
from breezy.strategy.current_rung_hold.trial_day_latch import (
    TrialDayLatch,
    open_trial_day_latch,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"

STATION = "LAX"
ICAO = "KLAX"
CLIMATE_DAY = dt.date(2026, 9, 4)
WINDOW_OPEN_NS = 1_788_552_000_000_000_000
NS_PER_MIN = 60_000_000_000
INSTRUMENT_ID = InstrumentId(Symbol("lax-86-87"), Venue("POLYMARKET_US"))
THETA = Decimal("0.06")


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------
def _facts_info(*, lower_f: int | None, upper_f: int | None) -> dict[str, object]:
    return {
        WEATHER_FACTS_STATUS_KEY: WEATHER_FACTS_STATUS_KNOWN,
        SETTLEMENT_STATION_KEY: STATION,
        CLIMATE_DAY_KEY: CLIMATE_DAY.isoformat(),
        MEASURE_KEY: "high",
        STRIKE_LOWER_F_KEY: lower_f,
        STRIKE_UPPER_F_KEY: upper_f,
        FEE_SCHEDULE_STATUS_KEY: FEE_SCHEDULE_STATUS_KNOWN,
        FEE_COEFFICIENT_KEY: str(THETA),
    }


def _instrument() -> BinaryOption:
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
        maker_fee=THETA,
        taker_fee=THETA,
        ts_event=0,
        ts_init=0,
        info=_facts_info(lower_f=86, upper_f=87),
    )


def _quote(*, ask: str, size: int, ts_event: int) -> QuoteTick:
    return QuoteTick(
        instrument_id=INSTRUMENT_ID,
        bid_price=Price.from_str("0.01"),
        ask_price=Price.from_str(ask),
        bid_size=Quantity.from_int(size),
        ask_size=Quantity.from_int(size),
        ts_event=ts_event,
        ts_init=ts_event,
    )


def _pad(
    side: OrderSide, levels: tuple[tuple[str, int], ...],
) -> tuple[list[BookOrder], list[int]]:
    filler = BookOrder(side, Price(0, 2), Quantity(0, 0), 0)
    orders = [BookOrder(side, Price.from_str(px), Quantity(size, 0), 0) for px, size in levels]
    counts = [1] * len(orders)
    while len(orders) < 10:
        orders.append(filler)
        counts.append(0)
    return orders, counts


def _depth(*, ask: str, size: int, ts_event: int) -> OrderBookDepth10:
    bid_orders, bid_counts = _pad(OrderSide.BUY, (("0.01", 10),))
    ask_orders, ask_counts = _pad(OrderSide.SELL, ((ask, size),) if size > 0 else ())
    return OrderBookDepth10(
        instrument_id=INSTRUMENT_ID,
        bids=bid_orders,
        asks=ask_orders,
        bid_counts=bid_counts,
        ask_counts=ask_counts,
        flags=0,
        sequence=0,
        ts_event=ts_event,
        ts_init=ts_event,
    )


@contextmanager
def _latch_context(store_path: Path) -> Iterator[TrialDayLatch]:
    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
        yield open_trial_day_latch(intent_latch)


def _latch_factory(store_path: Path) -> Callable[[], AbstractContextManager[TrialDayLatch]]:
    return lambda: _latch_context(store_path)


# ---------------------------------------------------------------------------
# RED test 1 -- no archive-derived / foreign market data ever enters the replay
# ---------------------------------------------------------------------------
def test_market_data_outside_the_capture_window_is_refused() -> None:
    instrument = _instrument()
    quote = _quote(ask="0.40", size=10, ts_event=WINDOW_OPEN_NS)
    depth = _depth(ask="0.40", size=10, ts_event=WINDOW_OPEN_NS)
    foreign_quote = _quote(ask="0.40", size=10, ts_event=WINDOW_OPEN_NS - 10 * NS_PER_MIN)
    with pytest.raises(ForeignReplayDataError):
        build_paper_replay_config(
            instruments=[instrument],
            market_data=[quote, depth, foreign_quote],
            starting_balances=(Money(10_000, USD),),
            capture_window_ns=(WINDOW_OPEN_NS, WINDOW_OPEN_NS + NS_PER_MIN),
        )


# ---------------------------------------------------------------------------
# RED test 2 -- a quote-only replay is refused, not silently fill-less
# ---------------------------------------------------------------------------
def test_a_quote_only_instrument_is_refused() -> None:
    instrument = _instrument()
    quote = _quote(ask="0.40", size=10, ts_event=WINDOW_OPEN_NS)
    with pytest.raises(QuoteOnlyReplayError, match="engine.pyx:4509,4551"):
        build_paper_replay_config(
            instruments=[instrument],
            market_data=[quote],
            starting_balances=(Money(10_000, USD),),
            capture_window_ns=(WINDOW_OPEN_NS, WINDOW_OPEN_NS + NS_PER_MIN),
        )


# ---------------------------------------------------------------------------
# RED tests 3-4 -- IOC fill mechanics, over a REAL BacktestEngine
# ---------------------------------------------------------------------------
def _run_engine(store_path: Path, *, ask: str, size: int) -> tuple[FilledTrial, ...]:
    instrument = _instrument()
    # Depth strictly precedes the quote's own ts_init: under L2_MBP,
    # `process_quote_tick` never mutates the book (engine.pyx:4509,4551), so
    # the book must already be populated by the time the strategy's
    # `on_quote_tick` submits the IOC.
    depth_ts = WINDOW_OPEN_NS - 1_000
    quote = _quote(ask=ask, size=size, ts_event=WINDOW_OPEN_NS)
    depth = _depth(ask=ask, size=size, ts_event=depth_ts)
    # Strictly BEFORE the quote's own ts_init -- ties at equal ts_init are not
    # guaranteed to resolve observation-before-quote through a real engine's
    # sorted merge (unlike the direct on_data/on_quote_tick call order the
    # non-engine strategy tests use).
    observation_ns = WINDOW_OPEN_NS - 5 * NS_PER_MIN
    from breezy.domain.station_observation import StationObservation

    observation = StationObservation(
        station=ICAO,
        observed_at_ns=observation_ns,
        received_at_ns=observation_ns + NS_PER_MIN,
        temp_c_tenths=300,  # 30.0C -> 86F exactly
        precision_c_tenths=5,
        is_metar=True,
        source_channel="iem_asos_metar",
        assumed_publication_lag_ns=1,
    )
    config = build_paper_replay_config(
        instruments=[instrument],
        market_data=[quote, depth],
        weather_data=as_backtest_data([observation]),
        starting_balances=(Money(10_000, USD),),
        capture_window_ns=(depth_ts, WINDOW_OPEN_NS),
        instruments_without_close=frozenset({instrument.id}),
    )
    cfg = CurrentRungHoldConfig(instrument_ids=(instrument.id,), stations=(STATION,))
    strategy = CurrentRungHoldBacktestStrategy(
        cfg, trial_day_latch_factory=_latch_factory(store_path),
    )
    with backtest(
        config, strategies=(strategy,), allow_idle_strategies=True, allow_open_positions=True,
    ) as engine:
        ctx = ReplayEntryContext(
            station=STATION,
            climate_day=CLIMATE_DAY.isoformat(),
            bucket=None,
            entry_ask=Decimal(ask),
            scheduled_release_at_ns=WINDOW_OPEN_NS + 7 * 24 * 3_600_000_000_000,
        )
        trials = filled_trials_from_engine(engine, {str(instrument.id): ctx})
    return trials


def test_an_ioc_below_minimum_displayed_size_records_no_fill(tmp_path: Path) -> None:
    trials = _run_engine(tmp_path / "state.db", ask="0.40", size=0)
    assert trials == ()


# ---------------------------------------------------------------------------
# RED test D3 -- a fill below its own decision-instant entry_ask is refused,
# never silently reported as negative slippage. A BUY IOC at limit=ask can
# only fill AT the displayed ask (this fixture's book) or be rejected --
# never below it -- so an `entry_ask` set artificially ABOVE the true fill
# reproduces the impossible-improvement shape without needing a second
# (lower) book snapshot.
# ---------------------------------------------------------------------------
def test_a_fill_below_its_decision_instant_entry_ask_is_refused(tmp_path: Path) -> None:
    instrument = _instrument()
    depth_ts = WINDOW_OPEN_NS - 1_000
    ask = "0.40"
    quote = _quote(ask=ask, size=10, ts_event=WINDOW_OPEN_NS)
    depth = _depth(ask=ask, size=10, ts_event=depth_ts)
    observation_ns = WINDOW_OPEN_NS - 5 * NS_PER_MIN
    from breezy.domain.station_observation import StationObservation

    observation = StationObservation(
        station=ICAO,
        observed_at_ns=observation_ns,
        received_at_ns=observation_ns + NS_PER_MIN,
        temp_c_tenths=300,
        precision_c_tenths=5,
        is_metar=True,
        source_channel="iem_asos_metar",
        assumed_publication_lag_ns=1,
    )
    config = build_paper_replay_config(
        instruments=[instrument],
        market_data=[quote, depth],
        weather_data=as_backtest_data([observation]),
        starting_balances=(Money(10_000, USD),),
        capture_window_ns=(depth_ts, WINDOW_OPEN_NS),
        instruments_without_close=frozenset({instrument.id}),
    )
    cfg = CurrentRungHoldConfig(instrument_ids=(instrument.id,), stations=(STATION,))
    strategy = CurrentRungHoldBacktestStrategy(
        cfg, trial_day_latch_factory=_latch_factory(tmp_path / "state.db"),
    )
    with backtest(
        config, strategies=(strategy,), allow_idle_strategies=True, allow_open_positions=True,
    ) as engine:
        # `entry_ask` deliberately ABOVE the true fill (0.40) -- the
        # impossible-improvement shape D3 refuses.
        ctx = ReplayEntryContext(
            station=STATION,
            climate_day=CLIMATE_DAY.isoformat(),
            bucket=None,
            entry_ask=Decimal("0.50"),
            scheduled_release_at_ns=WINDOW_OPEN_NS + 7 * 24 * 3_600_000_000_000,
        )
        with pytest.raises(ImpossibleFillPriceError, match="0.40.*0.50|entry_ask=0.50"):
            filled_trials_from_engine(engine, {str(instrument.id): ctx})


def test_an_ioc_at_displayed_size_one_fills_exactly_one_contract_at_the_displayed_ask(
    tmp_path: Path,
) -> None:
    trials = _run_engine(tmp_path / "state.db", ask="0.40", size=10)
    assert len(trials) == 1
    trial = trials[0]
    assert trial.fill_px == Decimal("0.40")
    assert trial.entry_ask == Decimal("0.40")
    assert trial.qty == Decimal(1)
    expected_id = f"paper_replay/current_rung_hold/trial/{STATION}/{CLIMATE_DAY.isoformat()}"
    assert trial.trial_id == expected_id


# ---------------------------------------------------------------------------
# RED tests (a)/(b) -- the capture's own recorded `InstrumentClose` is used,
# never `instruments_without_close`; a capture with no close still refuses.
# ---------------------------------------------------------------------------
def _close(*, price: str, ts_event: int) -> InstrumentClose:
    return InstrumentClose(
        instrument_id=INSTRUMENT_ID,
        close_price=Price.from_str(price),
        close_type=InstrumentCloseType.CONTRACT_EXPIRED,
        ts_event=ts_event,
        ts_init=ts_event,
    )


def test_a_capture_with_a_real_close_builds_and_runs_the_engine(tmp_path: Path) -> None:
    """(a) A fixture capture WITH a real recorded close builds the engine and
    fills -- no `instruments_without_close` bypass anywhere in this path."""
    instrument = _instrument()
    depth_ts = WINDOW_OPEN_NS - 1_000
    quote = _quote(ask="0.40", size=10, ts_event=WINDOW_OPEN_NS)
    depth = _depth(ask="0.40", size=10, ts_event=depth_ts)
    # Stamped strictly AFTER the quote window -- a real settlement close, not
    # a synthetic one, and outside [lo, hi] on purpose (RED "closes come at
    # settlement").
    close = _close(price="1.00", ts_event=WINDOW_OPEN_NS + NS_PER_MIN)
    observation_ns = WINDOW_OPEN_NS - 5 * NS_PER_MIN
    from breezy.domain.station_observation import StationObservation

    observation = StationObservation(
        station=ICAO,
        observed_at_ns=observation_ns,
        received_at_ns=observation_ns + NS_PER_MIN,
        temp_c_tenths=300,
        precision_c_tenths=5,
        is_metar=True,
        source_channel="iem_asos_metar",
        assumed_publication_lag_ns=1,
    )
    config = build_paper_replay_config(
        instruments=[instrument],
        market_data=[quote, depth, close],
        weather_data=as_backtest_data([observation]),
        settlement_prices={instrument.id: 1.0},
        starting_balances=(Money(10_000, USD),),
        capture_window_ns=(depth_ts, WINDOW_OPEN_NS),
        # Deliberately NOT passing `instruments_without_close` -- the real
        # close above is what satisfies the invariant.
    )
    cfg = CurrentRungHoldConfig(instrument_ids=(instrument.id,), stations=(STATION,))
    strategy = CurrentRungHoldBacktestStrategy(
        cfg, trial_day_latch_factory=_latch_factory(tmp_path / "state.db"),
    )
    with backtest(config, strategies=(strategy,), allow_idle_strategies=True) as engine:
        ctx = ReplayEntryContext(
            station=STATION,
            climate_day=CLIMATE_DAY.isoformat(),
            bucket=None,
            entry_ask=Decimal("0.40"),
            scheduled_release_at_ns=WINDOW_OPEN_NS + 7 * 24 * 3_600_000_000_000,
        )
        trials = filled_trials_from_engine(engine, {str(instrument.id): ctx})
    assert len(trials) == 1
    assert trials[0].fill_px == Decimal("0.40")


def test_a_capture_with_no_close_still_refuses_settlement_invariant(tmp_path: Path) -> None:
    """(b) No close record anywhere -- the invariant must NOT be bypassed."""
    instrument = _instrument()
    depth_ts = WINDOW_OPEN_NS - 1_000
    quote = _quote(ask="0.40", size=10, ts_event=WINDOW_OPEN_NS)
    depth = _depth(ask="0.40", size=10, ts_event=depth_ts)
    config = build_paper_replay_config(
        instruments=[instrument],
        market_data=[quote, depth],
        starting_balances=(Money(10_000, USD),),
        capture_window_ns=(depth_ts, WINDOW_OPEN_NS),
        # No close, no `instruments_without_close` -- must still refuse.
    )
    cfg = CurrentRungHoldConfig(instrument_ids=(instrument.id,), stations=(STATION,))
    strategy = CurrentRungHoldBacktestStrategy(
        cfg, trial_day_latch_factory=_latch_factory(tmp_path / "state.db"),
    )
    with pytest.raises(SettlementInvariantError), backtest(
        config, strategies=(strategy,), allow_idle_strategies=True,
    ):
        pass  # pragma: no cover - must raise before yielding


# ---------------------------------------------------------------------------
# RED -- a capture with NO recorded close but a FINAL climate day synthesizes
# a close per the `_synthesize_close` precedent; PnL is provably driven by
# `settlement_prices` (from the FINAL record), never the cosmetic close price.
# ---------------------------------------------------------------------------
def _final_climate_day(*, tmax_f: int) -> NwsClimateDay:
    return NwsClimateDay(
        station=STATION,
        climate_day=CLIMATE_DAY,
        tmax_f=tmax_f,
        tmin_f=63,
        tavg_f=75,
        tavg_flag=None,
        tmax_flag=None,
        tmin_flag=None,
        is_final=True,
        correction_flag=False,
        revision_seq=1,
        is_superseded=False,
        issuing_office="KLAX",
        issuance_time_ns=WINDOW_OPEN_NS - 1_000,
        retrieved_at_ns=WINDOW_OPEN_NS,
        parser_version="test",
        registry_version="test",
        raw_sha256="c" * 64,
        source_channel="cli_daily",
        schema_version=CLIMATE_DAY_SCHEMA_VERSION,
        ts_event=WINDOW_OPEN_NS,
    )


def _tape_instrument_no_close(driver: ModuleType, *, ask: str, size: int) -> object:
    instrument = _instrument()
    facts = read_weather_bucket_facts(instrument.info)
    depth_ts = WINDOW_OPEN_NS - 1_000
    quote = _quote(ask=ask, size=size, ts_event=WINDOW_OPEN_NS)
    depth = _depth(ask=ask, size=size, ts_event=depth_ts)
    return driver.TapeInstrument(
        instrument=instrument, facts=facts, depths=[depth], quotes=[quote], closes=[],
    )


_OBSERVATION_ROWS = [{"station": ICAO, "valid": "2026-09-04 19:55", "metar": "KLAX T03000167"}]

#: WINDOW_OPEN_NS is exactly 12:00 LST (see the module comment above); shift
#: four hours earlier -> 08:00 LST, outside the [12:00,17:00) decision
#: window on the SAME climate day.
_OUTSIDE_WINDOW_NS = WINDOW_OPEN_NS - 4 * 3_600_000_000_000
LAX_STD_UTC_OFFSET_HOURS = -8.0


def _tape_instrument_outside_window(driver: ModuleType, *, ask: str, size: int) -> object:
    """A tape whose only `QuoteTick` is outside the [12:00,17:00) LST window
    -- the (b) no-coverage-precondition fixture: `on_quote_tick` would count
    it `outside_decision_window` and never fill."""
    instrument = _instrument()
    facts = read_weather_bucket_facts(instrument.info)
    depth_ts = _OUTSIDE_WINDOW_NS - 1_000
    quote = _quote(ask=ask, size=size, ts_event=_OUTSIDE_WINDOW_NS)
    depth = _depth(ask=ask, size=size, ts_event=depth_ts)
    return driver.TapeInstrument(
        instrument=instrument, facts=facts, depths=[depth], quotes=[quote], closes=[],
    )


def test_close_source_label_is_recorded_when_every_instrument_has_a_close(
    driver: ModuleType,
) -> None:
    instrument = _instrument()
    facts = read_weather_bucket_facts(instrument.info)
    with_close = driver.TapeInstrument(
        instrument=instrument,
        facts=facts,
        depths=[],
        quotes=[],
        closes=[_close(price="1.00", ts_event=WINDOW_OPEN_NS + NS_PER_MIN)],
    )
    assert driver.close_source_label([with_close]) == "closes=recorded"


def test_close_source_label_is_synthesized_when_a_close_is_missing(driver: ModuleType) -> None:
    without_close = _tape_instrument_no_close(driver, ask="0.40", size=10)
    assert driver.close_source_label([without_close]) == (
        "closes=synthesized_after_last_tick (price cosmetic; settlement_prices from FINAL)"
    )


def test_a_capture_with_no_close_but_a_final_climate_day_synthesizes_and_settles(
    driver: ModuleType, tmp_path: Path,
) -> None:
    """Bucket 86-87 CONTAINS tmax_f=87 -> held=True. The synthesized close's
    OWN `close_price` is the cosmetic 0.5 (`_synthesize_close`) -- if that
    ever leaked into settlement, `assert_settlement_invariants`'s ENDPOINT
    rule would refuse the run outright (0.5 is not 0.0/1.0). The run
    completing AND `pnl == 1 - fill_px - fee` prove settlement came from
    `settlement_prices` (built from the FINAL record), never the close price.
    """
    tape_instrument = _tape_instrument_no_close(driver, ask="0.40", size=10)
    final = _final_climate_day(tmax_f=87)
    settlement_by_key = {(STATION, CLIMATE_DAY.isoformat()): final}

    result = driver.run_one_precision_arm(
        tape_instruments=[tape_instrument],
        observation_rows=_OBSERVATION_ROWS,
        station=STATION,
        lag_minutes=1,
        precision_mode="nws_integer_c",
        latch_store_path=tmp_path / "state.db",
        settlement_by_key=settlement_by_key,
    )
    trials = result.trials
    assert len(trials) == 1
    trial = trials[0]
    assert trial.fill_px == Decimal("0.40")
    # (a) reporting gap: the strategy's own refusal counts must ride along
    # with the trials -- this arm fills, so no `outside_decision_window`
    # refusal is expected.
    assert result.strategy_refusals == {}
    # WAIT-state diagnostics -- a fill on the first executable snapshot
    # leaves no diagnostic recorded either.
    assert result.strategy_diagnostics == {}

    scored = score_trial(trial, final, now_ns=WINDOW_OPEN_NS + 10_000)
    assert isinstance(scored, ScoredTrial)
    assert scored.held is True
    assert scored.pnl == Decimal(1) - trial.fill_px - trial.fee


def test_a_capture_with_no_close_and_no_final_climate_day_is_refused(
    driver: ModuleType, tmp_path: Path,
) -> None:
    """PENDING station-day: no recorded close, no FINAL to synthesize a
    settlement price from -- refused via the same `SettlementInvariantError`
    a genuinely close-less capture already takes, never a fabricated price."""
    tape_instrument = _tape_instrument_no_close(driver, ask="0.40", size=10)

    with pytest.raises(SettlementInvariantError):
        driver.run_one_precision_arm(
            tape_instruments=[tape_instrument],
            observation_rows=_OBSERVATION_ROWS,
            station=STATION,
            lag_minutes=1,
            precision_mode="nws_integer_c",
            latch_store_path=tmp_path / "state.db",
            settlement_by_key={},
        )


# ---------------------------------------------------------------------------
# RED test D1 -- entry_ask comes from the trial-day latch, never the tape's
# first quote. A decoy quote sits hours BEFORE the window at a materially
# different ask; the real, in-window quote is what the strategy actually
# decides and fills on.
# ---------------------------------------------------------------------------
def _tape_instrument_with_decoy_first_quote(
    driver: ModuleType, *, decoy_ask: str, real_ask: str, size: int,
) -> object:
    instrument = _instrument()
    facts = read_weather_bucket_facts(instrument.info)
    decoy_quote = _quote(ask=decoy_ask, size=size, ts_event=_OUTSIDE_WINDOW_NS)
    decoy_depth = _depth(ask=decoy_ask, size=size, ts_event=_OUTSIDE_WINDOW_NS - 1_000)
    real_depth_ts = WINDOW_OPEN_NS - 1_000
    real_quote = _quote(ask=real_ask, size=size, ts_event=WINDOW_OPEN_NS)
    real_depth = _depth(ask=real_ask, size=size, ts_event=real_depth_ts)
    return driver.TapeInstrument(
        instrument=instrument,
        facts=facts,
        # Decoy first -- `ti.quotes[0]` is the OLD defect's source.
        depths=[decoy_depth, real_depth],
        quotes=[decoy_quote, real_quote],
        closes=[],
    )


def test_entry_ask_comes_from_the_trial_day_latch_not_the_tapes_first_quote(
    driver: ModuleType, tmp_path: Path,
) -> None:
    tape_instrument = _tape_instrument_with_decoy_first_quote(
        driver, decoy_ask="0.15", real_ask="0.06", size=10,
    )
    final = _final_climate_day(tmax_f=87)
    settlement_by_key = {(STATION, CLIMATE_DAY.isoformat()): final}

    result = driver.run_one_precision_arm(
        tape_instruments=[tape_instrument],
        observation_rows=_OBSERVATION_ROWS,
        station=STATION,
        lag_minutes=1,
        precision_mode="nws_integer_c",
        latch_store_path=tmp_path / "state.db",
        settlement_by_key=settlement_by_key,
    )
    assert len(result.trials) == 1
    trial = result.trials[0]
    # The OLD defect: entry_ask == Decimal("0.15") (the decoy, tape's first
    # quote). The fix: entry_ask is the REAL decision-instant ask, which is
    # also what the IOC fills at here (no slippage in this fixture's book).
    assert trial.entry_ask == Decimal("0.06")
    assert trial.entry_ask != Decimal("0.15")
    assert trial.fill_px == Decimal("0.06")


def test_a_fill_with_no_corroborating_latch_record_is_refused(
    driver: ModuleType, tmp_path: Path,
) -> None:
    """The refusal half of D1: `_entry_contexts_from_latch` refuses a filled
    instrument the latch does not corroborate, rather than silently dropping
    it (`filled_trials_from_engine`'s own `ctx is None -> skip`)."""

    class _FakeOrder:
        def __init__(self, instrument_id: str) -> None:
            self.status = driver.OrderStatus.FILLED
            self.client_order_id = "O-1"
            self.instrument_id = instrument_id

    class _FakeCache:
        def orders(self) -> list[_FakeOrder]:
            return [_FakeOrder(str(INSTRUMENT_ID))]

    class _FakeEngine:
        def __init__(self) -> None:
            self.cache = _FakeCache()

    with pytest.raises(driver.EntryAskFromLatchMissingError):
        driver._entry_contexts_from_latch(
            [],
            _FakeEngine(),
            station=STATION,
            climate_day=CLIMATE_DAY.isoformat(),
            latch_store_path=tmp_path / "state.db",
            scheduled_release_at_ns=WINDOW_OPEN_NS + 7 * 24 * 3_600_000_000_000,
        )


# ---------------------------------------------------------------------------
# RED test D2 -- a quote and its own-instant depth snapshot (identical
# ts_init, one WS message) must resolve depth-before-quote: the fill must
# reflect the NEW snapshot's ask, never the stale, pre-existing one.
# ---------------------------------------------------------------------------
def _tape_instrument_with_tied_depth_update(
    driver: ModuleType, *, stale_ask: str, new_ask: str, size: int,
) -> object:
    instrument = _instrument()
    facts = read_weather_bucket_facts(instrument.info)
    stale_depth = _depth(ask=stale_ask, size=size, ts_event=WINDOW_OPEN_NS - 1_000)
    # SAME ts_init as the quote below -- one WS message (D2).
    new_depth = _depth(ask=new_ask, size=size, ts_event=WINDOW_OPEN_NS)
    quote = _quote(ask=new_ask, size=size, ts_event=WINDOW_OPEN_NS)
    return driver.TapeInstrument(
        instrument=instrument, facts=facts, depths=[stale_depth, new_depth], quotes=[quote],
        closes=[],
    )


def test_a_quote_and_its_own_instant_depth_update_fills_the_new_snapshot(
    driver: ModuleType, tmp_path: Path,
) -> None:
    tape_instrument = _tape_instrument_with_tied_depth_update(
        driver, stale_ask="0.04", new_ask="0.06", size=10,
    )
    final = _final_climate_day(tmax_f=87)
    settlement_by_key = {(STATION, CLIMATE_DAY.isoformat()): final}

    result = driver.run_one_precision_arm(
        tape_instruments=[tape_instrument],
        observation_rows=_OBSERVATION_ROWS,
        station=STATION,
        lag_minutes=1,
        precision_mode="nws_integer_c",
        latch_store_path=tmp_path / "state.db",
        settlement_by_key=settlement_by_key,
    )
    assert len(result.trials) == 1
    trial = result.trials[0]
    # The OLD defect: the quote sorts before its own-instant depth update, so
    # the IOC fills against the STALE 0.04 level. The fix: 0.06, the level
    # actually displayed at the decision instant.
    assert trial.fill_px == Decimal("0.06")
    assert trial.fill_px != Decimal("0.04")


# ---------------------------------------------------------------------------
# `load_replay_observations` -- receipt synthesis, precision arms
# ---------------------------------------------------------------------------
def test_lag_minutes_has_no_default_and_is_required() -> None:
    with pytest.raises(TypeError):
        PaperReplayInputs()  # type: ignore[call-arg]


def test_received_at_ns_is_synthesized_as_observed_plus_lag() -> None:
    rows = [{"station": ICAO, "valid": "2026-09-03 12:00", "metar": "KLAX T03000167"}]
    inputs = PaperReplayInputs(lag_minutes=30)
    observations = load_replay_observations(station=ICAO, rows=rows, inputs=inputs)
    assert len(observations) == 1
    obs = observations[0]
    assert obs.received_at_ns == obs.observed_at_ns + 30 * NS_PER_MIN


def test_a_lag_45_receipt_leaves_a_positive_window_under_the_stale_bound() -> None:
    """Mirrors ``test_current_rung_hold_decision.py``'s characterizing widen
    on the paper-replay path: a lag-45 receipt (`received = observed + 45
    min`) plus one 5-minute ASOS cadence tick, minus one nanosecond, must
    stay strictly under the decision-layer stale bound
    (``STALE_OBSERVATION_MINUTES`` = 50 min) so the lag-45 arm is not
    structurally empty (rev 3 delta, 2026-09-04)."""
    rows = [{"station": ICAO, "valid": "2026-09-03 12:00", "metar": "KLAX T03000167"}]
    inputs = PaperReplayInputs(lag_minutes=45)
    obs = load_replay_observations(station=ICAO, rows=rows, inputs=inputs)[0]
    assert obs.received_at_ns == obs.observed_at_ns + 45 * NS_PER_MIN
    bound_ns = STALE_OBSERVATION_MINUTES * NS_PER_MIN
    quote_ts_ns = obs.received_at_ns + 5 * NS_PER_MIN - 1
    staleness_ns = quote_ts_ns - obs.observed_at_ns
    assert staleness_ns < bound_ns


def test_precision_arms_are_both_present_and_default_is_pessimistic() -> None:
    assert set(PRECISION_ARMS) == {"nws_integer_c", "archive_metar"}
    rows = [{"station": ICAO, "valid": "2026-09-03 12:00", "metar": "KLAX T03000167"}]
    default_obs = load_replay_observations(
        station=ICAO, rows=rows, inputs=PaperReplayInputs(lag_minutes=30),
    )[0]
    archive_obs = load_replay_observations(
        station=ICAO,
        rows=rows,
        inputs=PaperReplayInputs(lag_minutes=30, precision_mode="archive_metar"),
    )[0]
    assert default_obs.precision_c_tenths == 10
    assert archive_obs.precision_c_tenths == 5


def test_format_roi_bound_for_paper_replay_never_prints_underpowered(
) -> None:
    """Every real paper-replay run is n<=10 (module docstring), so
    `ROIBoundUnderpowered` must never surface the banned `UNDERPOWERED`
    family-tally verdict token here."""
    rendered = format_roi_bound_for_paper_replay(ROIBoundUnderpowered(n=3))
    assert rendered == "BCa: n<30 — bound not computed"
    for banned in ("UNDERPOWERED", "KILL", "SURVIVE"):
        assert banned not in rendered


def test_format_roi_bound_for_paper_replay_delegates_other_variants() -> None:
    result = ROIBound(lower_bound=Decimal("0.10"), n=42, theta_hat=Decimal("0.20"))
    assert (
        format_roi_bound_for_paper_replay(result)
        == "BCa 95% lower bound on ROI: 0.10 (n=42, B=10000, seed=20260904)"
    )


# ---------------------------------------------------------------------------
# Driver-level tests (dynamic module load)
# ---------------------------------------------------------------------------
def _load_driver() -> ModuleType:
    if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))
    path = _SCRIPTS_ANALYSIS_DIR / "current_rung_hold_paper_replay.py"
    spec = importlib.util.spec_from_file_location("current_rung_hold_paper_replay", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def driver() -> ModuleType:
    return _load_driver()


def test_lag_minutes_is_required_at_the_cli(driver: ModuleType) -> None:
    with pytest.raises(SystemExit):
        driver.main(
            [
                "--climate-day", CLIMATE_DAY.isoformat(),
                "--station", STATION,
                "--tape-instance-id", "x",
                "--quote-catalog", "/tmp/x",
                "--work-catalog", "/tmp/y",
                "--asos-cache-csv", "/tmp/z.csv",
                "--weather-catalog-root", "/tmp/w",
            ],
        )


def test_the_provenance_header_states_lag_precision_n_ceiling_and_no_verdict(
    driver: ModuleType, capsys: pytest.CaptureFixture[str],
) -> None:
    header = driver.build_provenance_header(
        lag_minutes=30, precision_mode="nws_integer_c", n_requested=1, n_data=1, n_live=1,
    )
    assert "MECHANISM TEST -- NO VERDICT" in header
    assert "lag_minutes=30" in header
    assert "precision_mode=nws_integer_c" in header
    assert "n<=10" in header
    for banned in ("**KILL**", "**SURVIVE**", "**UNDERPOWERED**"):
        assert banned not in header

    # Full paper stdout, not just the header: every real paper-replay run
    # is n<=10, so `_print_roi_and_wilson`'s BCa line must never surface
    # the banned UNDERPOWERED family-tally verdict token either. Scan the
    # ROI-bound line's OWN output, isolated from the header's descriptive
    # prose (which legitimately names the banned words while explaining
    # this module never prints them as a verdict).
    capsys.readouterr()  # discard anything printed above
    driver._print_roi_and_wilson((), {}, 0)
    captured = capsys.readouterr().out
    assert "BCa: n<30 — bound not computed" in captured
    for banned in ("UNDERPOWERED", "KILL", "SURVIVE"):
        assert banned not in captured


def test_settlement_comes_from_the_final_climate_day_only(driver: ModuleType) -> None:
    prelim = NwsClimateDay(
        station=STATION,
        climate_day=CLIMATE_DAY,
        tmax_f=88,
        tmin_f=63,
        tavg_f=75,
        tavg_flag=None,
        tmax_flag=None,
        tmin_flag=None,
        is_final=False,
        correction_flag=False,
        revision_seq=1,
        is_superseded=False,
        issuing_office="KLAX",
        issuance_time_ns=WINDOW_OPEN_NS - 1_000,
        retrieved_at_ns=WINDOW_OPEN_NS,
        parser_version="test",
        registry_version="test",
        raw_sha256="a" * 64,
        source_channel="iem_afos_forecast",
        schema_version=CLIMATE_DAY_SCHEMA_VERSION,
        ts_event=WINDOW_OPEN_NS,
    )
    final = NwsClimateDay(
        station=STATION,
        climate_day=CLIMATE_DAY,
        tmax_f=87,
        tmin_f=63,
        tavg_f=75,
        tavg_flag=None,
        tmax_flag=None,
        tmin_flag=None,
        is_final=True,
        correction_flag=False,
        revision_seq=2,
        is_superseded=False,
        issuing_office="KLAX",
        issuance_time_ns=WINDOW_OPEN_NS + 1_000,
        retrieved_at_ns=WINDOW_OPEN_NS + 2_000,
        parser_version="test",
        registry_version="test",
        raw_sha256="b" * 64,
        source_channel="cli_daily",
        schema_version=CLIMATE_DAY_SCHEMA_VERSION,
        ts_event=WINDOW_OPEN_NS + 1_000,
    )
    # `_load_climate_day_records` reads from disk; exercise the pure
    # reduction directly against both records, mirroring `_settled_readings`.
    best: dict[str, NwsClimateDay] = {}
    for record in (prelim, final):
        if not record.is_final:
            continue
        current = best.get(record.station)
        if current is None or record.revision_seq > current.revision_seq:
            best[record.station] = record
    assert best[STATION].tmax_f == 87
    assert best[STATION].revision_seq == 2


def test_a_populated_work_catalog_is_refused(driver: ModuleType, tmp_path: Path) -> None:
    quote_catalog = tmp_path / "capture"
    quote_catalog.mkdir()
    work_catalog = tmp_path / "work"
    work_catalog.mkdir()
    (work_catalog / "already_here.txt").write_text("x")
    with pytest.raises(ValueError, match="not empty"):
        driver._convert_live_capture(
            quote_catalog=quote_catalog,
            instance_id="does-not-matter",
            subdirectory="live",
            work_catalog=work_catalog,
        )


def test_venue_skipped_days_are_refused_not_silently_zero(driver: ModuleType) -> None:
    listed = [dt.date(2026, 8, 30), dt.date(2026, 8, 31)]
    with pytest.raises(driver.UnlistedStationDayError):
        driver.assert_requested_days_are_listed([dt.date(2026, 9, 2)], listed)
    driver.assert_requested_days_are_listed([dt.date(2026, 8, 30)], listed)  # must not raise


# ---------------------------------------------------------------------------
# (a) reporting gap -- `run_one_precision_arm` must surface the strategy's
# own `RefusalCounter`, not discard the strategy object silently.
# ---------------------------------------------------------------------------
def test_run_one_precision_arm_returns_the_strategys_own_refusal_counts(
    driver: ModuleType, tmp_path: Path,
) -> None:
    tape_instrument = _tape_instrument_outside_window(driver, ask="0.40", size=10)
    final = _final_climate_day(tmax_f=87)
    settlement_by_key = {(STATION, CLIMATE_DAY.isoformat()): final}

    result = driver.run_one_precision_arm(
        tape_instruments=[tape_instrument],
        observation_rows=_OBSERVATION_ROWS,
        station=STATION,
        lag_minutes=1,
        precision_mode="nws_integer_c",
        latch_store_path=tmp_path / "state.db",
        settlement_by_key=settlement_by_key,
    )
    assert result.trials == ()
    assert result.strategy_refusals == {"outside_decision_window": 1}
    # The quote never enters the decision window, so it never reaches
    # the WAIT-state diagnostics checks either.
    assert result.strategy_diagnostics == {}


def test_print_roi_and_wilson_uses_the_scoring_vocabulary_label(
    driver: ModuleType, capsys: pytest.CaptureFixture[str],
) -> None:
    """The 6c scorer's refusal vocabulary (over `FilledTrial`s) must never be
    printed under the SAME label as the strategy's own `RefusalCounter`
    (a different vocabulary, counted at `on_quote_tick` time) -- relabelled
    `scoring_refused` so a reader cannot conflate the two."""
    capsys.readouterr()
    driver._print_roi_and_wilson((), {}, 0)
    captured = capsys.readouterr().out
    assert "scored=0 scoring_refused=0" in captured
    assert "scored=0 refused=0" not in captured


# ---------------------------------------------------------------------------
# (b) no coverage precondition -- an uncovered station-day tape is refused
# loudly, never a silent zero-fill run (L-23 shape).
# ---------------------------------------------------------------------------
def test_assert_decision_window_has_coverage_passes_when_a_quote_is_in_window(
    driver: ModuleType,
) -> None:
    tape_instrument = _tape_instrument_no_close(driver, ask="0.40", size=10)
    driver.assert_decision_window_has_coverage(
        [tape_instrument], station=STATION, std_utc_offset_hours=LAX_STD_UTC_OFFSET_HOURS,
    )  # must not raise


def test_assert_decision_window_has_coverage_refuses_an_uncovered_tape(
    driver: ModuleType,
) -> None:
    tape_instrument = _tape_instrument_outside_window(driver, ask="0.40", size=10)
    with pytest.raises(driver.NoDecisionWindowCoverageError, match=r"08:00"):
        driver.assert_decision_window_has_coverage(
            [tape_instrument], station=STATION, std_utc_offset_hours=LAX_STD_UTC_OFFSET_HOURS,
        )


def test_assert_decision_window_has_coverage_refuses_a_tape_with_no_quotes_at_all(
    driver: ModuleType,
) -> None:
    instrument = _instrument()
    facts = read_weather_bucket_facts(instrument.info)
    empty = driver.TapeInstrument(
        instrument=instrument, facts=facts, depths=[], quotes=[], closes=[],
    )
    with pytest.raises(driver.NoDecisionWindowCoverageError):
        driver.assert_decision_window_has_coverage(
            [empty], station=STATION, std_utc_offset_hours=LAX_STD_UTC_OFFSET_HOURS,
        )


# ---------------------------------------------------------------------------
# (3) run-header visibility -- per-instrument quote/depth counts and LST span
# ---------------------------------------------------------------------------
def test_print_tape_instrument_header_reports_counts_and_lst_span(
    driver: ModuleType, capsys: pytest.CaptureFixture[str],
) -> None:
    tape_instrument = _tape_instrument_no_close(driver, ask="0.40", size=10)
    capsys.readouterr()
    driver.print_tape_instrument_header(
        [tape_instrument], std_utc_offset_hours=LAX_STD_UTC_OFFSET_HOURS,
    )
    out = capsys.readouterr().out
    assert str(INSTRUMENT_ID) in out
    assert "quotes=1" in out
    assert "depth_updates=1" in out
    assert "12:00" in out  # WINDOW_OPEN_NS's own LST instant, in the span


def test_paper_writer_refuses_a_live_scored_trials_output_path(driver: ModuleType) -> None:
    live_path = Path(
        "~/.local/share/breezy/derived/live/scored_trials",
    ).expanduser()
    with pytest.raises(driver.VenueOutsideLiveDirError):
        driver.assert_paper_write_path_is_not_live(live_path)
    driver.assert_paper_write_path_is_not_live(driver.DEFAULT_PAPER_STORE)  # must not raise


def test_the_strategy_object_is_the_shipped_one(driver: ModuleType) -> None:
    source = (_SCRIPTS_ANALYSIS_DIR / "current_rung_hold_paper_replay.py").read_text()
    tree = ast.parse(source)
    imports_backtest_strategy = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "breezy.strategy.current_rung_hold.backtest_only"
        and any(alias.name == "CurrentRungHoldBacktestStrategy" for alias in node.names)
        for node in ast.walk(tree)
    )
    assert imports_backtest_strategy
    forbidden_names = {"evaluate_decision", "DecisionInputs"}
    defined_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert not (forbidden_names & defined_names)


def test_the_driver_never_passes_instruments_without_close() -> None:
    """(c) The driver never bypasses the settlement invariant: a capture
    instrument that never closes must refuse, not be waived by name. Checked
    at the AST call-site level (never a caller-supplied keyword argument),
    not a bare text search -- the module legitimately DISCUSSES the
    invariant in comments/docstrings without ever invoking the bypass."""
    source = (_SCRIPTS_ANALYSIS_DIR / "current_rung_hold_paper_replay.py").read_text()
    tree = ast.parse(source)
    used = {
        keyword.arg
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
    }
    assert "instruments_without_close" not in used


def test_no_inline_wilson_or_bootstrap_arithmetic(driver: ModuleType) -> None:
    source = (_SCRIPTS_ANALYSIS_DIR / "current_rung_hold_paper_replay.py").read_text()
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported |= {alias.name for alias in node.names}
    assert {
        "score_trials", "compute_roi_bound", "format_roi_bound_for_paper_replay",
        "wilson_interval",
    } <= imported
    # No hand-rolled normal-approximation constant (the exact anticonservative
    # shape EXEC_SPINE R-9 refuses by name).
    assert "1.96" not in source
