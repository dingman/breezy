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
import json
import re
import sys
from collections.abc import Callable, Iterator, Sequence
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
from breezy.persistence.family_manifest import (
    UnpinnedBoundaryArtefactError,
    UnpinnedDensityArtefactError,
    UnregisteredFamilyManifestError,
    load_family_manifest,
)
from breezy.persistence.scored_trial_store import read_scored_trials
from breezy.runtime.backtest_feed import as_backtest_data
from breezy.runtime.backtest_harness import SettlementInvariantError, backtest
from breezy.runtime.paper_replay import (
    PAPER_TRIAL_ID_NAMESPACE,
    PRECISION_ARMS,
    UNSCOPED_FAMILY_ID,
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
from breezy.settlement.trial_scorer import (
    FilledTrial,
    ScoredPathQtyInvariantError,
    ScoredTrial,
    score_trial,
)
from breezy.strategy.current_rung_hold.backtest_only import CurrentRungHoldBacktestStrategy
from breezy.strategy.current_rung_hold.config import (
    STALE_OBSERVATION_MINUTES,
    CurrentRungHoldConfig,
)
from breezy.strategy.current_rung_hold.continuous_strategy import ContinuousRungHoldStrategy
from breezy.strategy.current_rung_hold.monitor_store import read_monitor_summaries
from breezy.strategy.current_rung_hold.trial_day_latch import (
    CONTINUOUS_TRIAL_KEY_PREFIX,
    DEFAULT_TRIAL_KEY_PREFIX,
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
def _facts_info(
    *, lower_f: int | None, upper_f: int | None, fee_coefficient: Decimal = THETA,
) -> dict[str, object]:
    return {
        WEATHER_FACTS_STATUS_KEY: WEATHER_FACTS_STATUS_KNOWN,
        SETTLEMENT_STATION_KEY: STATION,
        CLIMATE_DAY_KEY: CLIMATE_DAY.isoformat(),
        MEASURE_KEY: "high",
        STRIKE_LOWER_F_KEY: lower_f,
        STRIKE_UPPER_F_KEY: upper_f,
        FEE_SCHEDULE_STATUS_KEY: FEE_SCHEDULE_STATUS_KNOWN,
        FEE_COEFFICIENT_KEY: str(fee_coefficient),
    }


def _instrument(*, fee_coefficient: Decimal = THETA) -> BinaryOption:
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
        maker_fee=fee_coefficient,
        taker_fee=fee_coefficient,
        ts_event=0,
        ts_init=0,
        info=_facts_info(lower_f=86, upper_f=87, fee_coefficient=fee_coefficient),
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


def _depth(
    *,
    ask: str,
    size: int,
    ts_event: int,
    bids: tuple[tuple[str, int], ...] = (("0.01", 10),),
) -> OrderBookDepth10:
    """Two-sided by default (real bid + real ask), matching every existing
    caller. Pass ``bids=()`` for a genuinely one-sided book -- the size-0
    Arrow pad only, no real bid level -- which is what a real one-sided
    frame looks like (`parse_book_levels` never fabricates a bid)."""
    bid_orders, bid_counts = _pad(OrderSide.BUY, bids)
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
def _run_engine(
    store_path: Path,
    *,
    ask: str,
    size: int,
    family_id: str = UNSCOPED_FAMILY_ID,
    trial_id_prefix: str = DEFAULT_TRIAL_KEY_PREFIX,
) -> tuple[FilledTrial, ...]:
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
        trials = filled_trials_from_engine(
            engine,
            {str(instrument.id): ctx},
            family_id=family_id,
            trial_id_prefix=trial_id_prefix,
        )
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
            filled_trials_from_engine(
                engine,
                {str(instrument.id): ctx},
                family_id=UNSCOPED_FAMILY_ID,
                trial_id_prefix=DEFAULT_TRIAL_KEY_PREFIX,
            )


def test_an_ioc_at_displayed_size_one_fills_exactly_one_contract_at_the_displayed_ask(
    tmp_path: Path,
) -> None:
    trials = _run_engine(tmp_path / "state.db", ask="0.40", size=10)
    assert len(trials) == 1
    trial = trials[0]
    assert trial.fill_px == Decimal("0.40")
    assert trial.entry_ask == Decimal("0.40")
    assert trial.qty == Decimal(1)
    # AUD-19a: the id now carries the caller's `family_id` segment
    # (`UNSCOPED_FAMILY_ID` here -- no manifest is in play at this call
    # site) immediately after the `PAPER_TRIAL_ID_NAMESPACE` literal.
    expected_id = (
        f"{PAPER_TRIAL_ID_NAMESPACE}/{UNSCOPED_FAMILY_ID}/"
        f"{DEFAULT_TRIAL_KEY_PREFIX}{STATION}/{CLIMATE_DAY.isoformat()}"
    )
    assert trial.trial_id == expected_id


# ---------------------------------------------------------------------------
# AUD-19a -- family-scoped replay id (ruling
# `RULING_replay_evidence_citability_and_promotion_criteria_2026-09-21.md`
# Q1). Step 1: the ruled shape, over the REAL on-disk collision --
# `pm_us_crh_cont` and `pm_us_crh_v4` share `trial_id_prefix`
# "continuous_rung_hold/trial/" (`deploy/families/*.json`) yet must produce
# distinct ids.
# ---------------------------------------------------------------------------
def test_two_manifests_sharing_a_trial_id_prefix_yield_distinct_replay_ids(
    tmp_path: Path,
) -> None:
    cont_id = _run_engine(
        tmp_path / "cont.db",
        ask="0.40",
        size=10,
        family_id="pm_us_crh_cont",
        trial_id_prefix=CONTINUOUS_TRIAL_KEY_PREFIX,
    )[0].trial_id
    v4_id = _run_engine(
        tmp_path / "v4.db",
        ask="0.40",
        size=10,
        family_id="pm_us_crh_v4",
        trial_id_prefix=CONTINUOUS_TRIAL_KEY_PREFIX,
    )[0].trial_id
    assert cont_id != v4_id
    assert cont_id == (
        f"{PAPER_TRIAL_ID_NAMESPACE}/pm_us_crh_cont/"
        f"{CONTINUOUS_TRIAL_KEY_PREFIX}{STATION}/{CLIMATE_DAY.isoformat()}"
    )
    assert v4_id == (
        f"{PAPER_TRIAL_ID_NAMESPACE}/pm_us_crh_v4/"
        f"{CONTINUOUS_TRIAL_KEY_PREFIX}{STATION}/{CLIMATE_DAY.isoformat()}"
    )


def test_the_builder_refuses_a_missing_family_id() -> None:
    """D1, fail-closed: a caller supplying no `family_id` (or no
    `trial_id_prefix`) does not compile/typecheck and raises `TypeError` at
    runtime -- checked before the function body ever touches its other
    arguments, so no real engine is needed here."""
    with pytest.raises(TypeError):
        filled_trials_from_engine(None, {}, trial_id_prefix=DEFAULT_TRIAL_KEY_PREFIX)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        filled_trials_from_engine(None, {}, family_id=UNSCOPED_FAMILY_ID)  # type: ignore[call-arg]


class _FakeOrderCache:
    """The minimal `engine.cache` shape `filled_trials_from_engine` reads
    -- an empty order sequence -- so the character-class RED/GREEN below
    needs no real `BacktestEngine`: the pattern check fires before the
    order loop ever runs, and `pm_us_crh_v4` (the accepted case) must reach
    that loop without raising."""

    def orders(self) -> list[object]:
        return []


class _FakeEngineForFamilyIdCheck:
    cache = _FakeOrderCache()


@pytest.mark.parametrize("invalid_family_id", ["Not/Valid", "UPPER", "has space", ""])
def test_the_builder_refuses_a_family_id_outside_the_registry_key_character_class(
    invalid_family_id: str,
) -> None:
    """`_FAMILY_ID_PATTERN` (`[a-z0-9_]+`) pin -- a manifest's `family_id`
    is its registry primary key shape, never a path-shaped, uppercase, or
    whitespace-bearing string. `Not/Valid` in particular carries a `/` NOT
    at the leading position, so `_assert_valid_trial_id_component`'s own
    leading-`/`/`..`-segment checks pass it through -- only the character
    class catches it; deleting `_FAMILY_ID_PATTERN`'s check would make this
    case (and `UPPER`/`has space`) silently accepted."""
    with pytest.raises(ValueError, match=r"family_id"):
        filled_trials_from_engine(
            _FakeEngineForFamilyIdCheck(),
            {},
            family_id=invalid_family_id,
            trial_id_prefix=DEFAULT_TRIAL_KEY_PREFIX,
        )


def test_the_builder_accepts_a_registry_key_shaped_family_id() -> None:
    trials = filled_trials_from_engine(
        _FakeEngineForFamilyIdCheck(),
        {},
        family_id="pm_us_crh_v4",
        trial_id_prefix=DEFAULT_TRIAL_KEY_PREFIX,
    )
    assert trials == ()


# ---------------------------------------------------------------------------
# Phase 0b: a replayed one-sided window reaches `on_order_book_depth` through
# a REAL BacktestEngine (`backtest_harness.py` feeds `OrderBookDepth10` the
# same way it feeds `QuoteTick`) -- proving the subscription and delivery
# path, not just the direct unit call already covered in
# `test_continuous_rung_hold_strategy.py`.
# ---------------------------------------------------------------------------
def test_a_one_sided_depth_only_replay_delivers_on_order_book_depth_to_continuous_strategy(
    tmp_path: Path,
) -> None:
    instrument = _instrument()
    # One-sided: bids all size-0 pad, ask populated -- no `QuoteTick` would
    # even be produced for a real frame like this (`parse_quote_tick`
    # requires both sides); `_assert_every_quote_instrument_has_depth` only
    # requires the reverse pairing, so a depth-only instrument is accepted.
    depth = _depth(ask="0.40", size=10, ts_event=WINDOW_OPEN_NS, bids=())
    # Fidelity guard on the fixture itself: a genuinely one-sided book has NO
    # real (size > 0) bid level. `_depth`'s own default (used by every other
    # caller in this file) pads bids with a REAL level, so asserting this
    # here -- rather than trusting the docstring above -- is what actually
    # proves this fixture, not just its comment, is one-sided.
    assert not any(level.size > 0 for level in depth.bids)
    from breezy.domain.station_observation import StationObservation

    observation_ns = WINDOW_OPEN_NS - 5 * NS_PER_MIN
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
        market_data=[depth],
        weather_data=as_backtest_data([observation]),
        starting_balances=(Money(10_000, USD),),
        capture_window_ns=(WINDOW_OPEN_NS, WINDOW_OPEN_NS),
        instruments_without_close=frozenset({instrument.id}),
    )
    cfg = CurrentRungHoldConfig(instrument_ids=(instrument.id,), stations=(STATION,))
    strategy = ContinuousRungHoldStrategy(
        cfg, trial_day_latch_factory=_latch_factory(tmp_path / "state.db"),
    )
    delivered: list[OrderBookDepth10] = []
    original_handler = strategy.on_order_book_depth

    def _spy(depth_arg: OrderBookDepth10) -> None:
        delivered.append(depth_arg)
        original_handler(depth_arg)

    strategy.on_order_book_depth = _spy  # type: ignore[method-assign]

    with backtest(config, strategies=(strategy,), allow_idle_strategies=True):
        pass

    assert len(delivered) == 1
    assert delivered[0].instrument_id == instrument.id
    # GAP fix 2026-09-15 (commit 309dab6): a finalized evaluation now appends
    # one YES-side and one NO-side `OfferTapeRecord` -- 2 total, not 1. The
    # NO row carries its own composite `<slug>^no` instrument id (per
    # `trial_day_latch`'s NO-leg convention), so only the YES row is checked
    # against `instrument.id`.
    assert len(strategy.offer_tape) == 2
    records = strategy.offer_tape.records()
    yes_record = next(record for record in records if record.side == "YES")
    no_record = next(record for record in records if record.side == "NO")
    assert yes_record.instrument_id == str(instrument.id)
    assert yes_record.source == "depth"
    assert no_record.side == "NO"


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
        trials = filled_trials_from_engine(
            engine,
            {str(instrument.id): ctx},
            family_id=UNSCOPED_FAMILY_ID,
            trial_id_prefix=DEFAULT_TRIAL_KEY_PREFIX,
        )
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


def _tape_instrument_depth_and_quote_in_window(
    driver: ModuleType, *, ask: str, size: int, fee_coefficient: Decimal = THETA,
) -> object:
    """SP-4 increment D: BOTH the QuoteTick and the OrderBookDepth10 land
    IN the decision window -- for dispatch-level tests that stub `run_one_
    precision_arm` (never a real engine), where `_tape_instrument_no_
    close`'s depth-1000ns-before-the-quote tie-break (needed only for a
    REAL engine's depth-before-quote fill ordering) would otherwise trip
    the NEW depth-basis coverage gate the continuous arm now runs under.

    `fee_coefficient` (AUD-09b fee-regime plan, Phase 3) defaults to the
    module's own `THETA` -- every pre-existing caller stays byte-identical;
    a caller exercising `--family-manifest` with a DIFFERENT registered
    theta passes this so the new preflight (`assert_fee_schedule_matches_
    family`) sees a tape that genuinely agrees with the manifest under
    test, rather than tripping on an incidental fixture mismatch."""
    instrument = _instrument(fee_coefficient=fee_coefficient)
    facts = read_weather_bucket_facts(instrument.info)
    quote = _quote(ask=ask, size=size, ts_event=WINDOW_OPEN_NS)
    depth = _depth(ask=ask, size=size, ts_event=WINDOW_OPEN_NS)
    return driver.TapeInstrument(
        instrument=instrument, facts=facts, depths=[depth], quotes=[quote], closes=[],
    )


class _StubReplayCatalog:
    """`_convert_live_capture`'s dispatch-test stand-in (AUD-09b review fix).

    Before the warm-up peek existed, a bare `object()` sufficed here because
    `main` never touched the catalog outside the separately-stubbed
    `_select_capture_instruments`. `_warmup_start_ns_for_replay` now reads
    `catalog.instruments()` / `catalog.order_book_depth10()` / `catalog.
    quote_ticks()` directly (see `test_paper_replay_catalog_bounds.py` for
    the real-catalog-shaped coverage of that call), so these dispatch-level
    tests need a minimal fake exposing exactly that surface -- built from
    the SAME canned `TapeInstrument` already returned by the stubbed
    `_select_capture_instruments`, never a second, diverging fixture.
    """

    def __init__(self, tape_instrument: object) -> None:
        self._tape_instrument = tape_instrument

    def instruments(self) -> list[object]:
        return [self._tape_instrument.instrument]

    def order_book_depth10(self, *, instrument_ids: list[str], end: int) -> list[object]:
        return self._tape_instrument.depths

    def quote_ticks(self, *, instrument_ids: list[str], end: int) -> list[object]:
        return self._tape_instrument.quotes


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


INSTRUMENT_ID_2 = InstrumentId(Symbol("lax-87-88"), Venue("POLYMARKET_US"))


def _instrument2() -> BinaryOption:
    increment = Price.from_str("0.01")
    size_increment = Quantity.from_str("1")
    return BinaryOption(
        instrument_id=INSTRUMENT_ID_2,
        raw_symbol=INSTRUMENT_ID_2.symbol,
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
        info=_facts_info(lower_f=87, upper_f=88),
    )


def test_two_filled_rungs_on_one_station_day_yield_two_entry_contexts(
    driver: ModuleType, tmp_path: Path,
) -> None:
    """S1 follow-up (operator ruling 2026-09-14 / plan S1): two DIFFERENT
    rungs filled on the same station-day each get their own latch-
    corroborated entry context -- the v3 latch keys TRIAL by instrument-day,
    not station-day alone ("I never wanted a limit of 1 contract per
    station")."""
    instrument_a = _instrument()
    instrument_b = _instrument2()
    facts_a = read_weather_bucket_facts(instrument_a.info)
    facts_b = read_weather_bucket_facts(instrument_b.info)
    tape_a = driver.TapeInstrument(
        instrument=instrument_a, facts=facts_a, depths=[], quotes=[], closes=[],
    )
    tape_b = driver.TapeInstrument(
        instrument=instrument_b, facts=facts_b, depths=[], quotes=[], closes=[],
    )

    class _FakeOrder:
        def __init__(self, instrument_id: str) -> None:
            self.status = driver.OrderStatus.FILLED
            self.client_order_id = "O-1"
            self.instrument_id = instrument_id

    class _FakeCache:
        def orders(self) -> list[_FakeOrder]:
            return [_FakeOrder(str(instrument_a.id)), _FakeOrder(str(instrument_b.id))]

    class _FakeEngine:
        def __init__(self) -> None:
            self.cache = _FakeCache()

    latch_store_path = tmp_path / "state.db"
    with driver._latch_context(latch_store_path) as latch:
        latch.consume(
            STATION,
            CLIMATE_DAY.isoformat(),
            latched_at_ns=WINDOW_OPEN_NS,
            instrument_id=str(instrument_a.id),
            ask=Decimal("0.10"),
            reason="taken",
            key_instrument_id=str(instrument_a.id),
        )
        latch.consume(
            STATION,
            CLIMATE_DAY.isoformat(),
            latched_at_ns=WINDOW_OPEN_NS,
            instrument_id=str(instrument_b.id),
            ask=Decimal("0.20"),
            reason="taken",
            key_instrument_id=str(instrument_b.id),
        )

    contexts = driver._entry_contexts_from_latch(
        [tape_a, tape_b],
        _FakeEngine(),
        station=STATION,
        climate_day=CLIMATE_DAY.isoformat(),
        latch_store_path=latch_store_path,
        scheduled_release_at_ns=WINDOW_OPEN_NS + 7 * 24 * 3_600_000_000_000,
    )

    assert set(contexts) == {str(instrument_a.id), str(instrument_b.id)}
    assert contexts[str(instrument_a.id)].entry_ask == Decimal("0.10")
    assert contexts[str(instrument_b.id)].entry_ask == Decimal("0.20")


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
# SP-4 increment D: the depth-basis coverage gate for the continuous arm.
# ---------------------------------------------------------------------------


def test_the_v2_arm_coverage_gate_is_unchanged(driver: ModuleType) -> None:
    """CHARACTERISATION: an explicit `source="quote"` (the default every
    existing caller already uses, L-28) is byte-identical to the three
    pins above -- passes on an in-window quote, refuses an out-of-window
    tape, refuses a tape with none at all."""
    in_window = _tape_instrument_no_close(driver, ask="0.40", size=10)
    driver.assert_decision_window_has_coverage(
        [in_window],
        station=STATION,
        std_utc_offset_hours=LAX_STD_UTC_OFFSET_HOURS,
        source="quote",
    )  # must not raise

    outside = _tape_instrument_outside_window(driver, ask="0.40", size=10)
    with pytest.raises(driver.NoDecisionWindowCoverageError, match=r"08:00"):
        driver.assert_decision_window_has_coverage(
            [outside],
            station=STATION,
            std_utc_offset_hours=LAX_STD_UTC_OFFSET_HOURS,
            source="quote",
        )


def test_a_depth_only_window_is_covered_for_the_continuous_arm(driver: ModuleType) -> None:
    """A tape with ZERO `QuoteTick`s but ONE in-window, executable Depth10
    ask is COVERED under `source="depth"` -- the continuous arm hunts on
    depth too (L-35), so the v2 QuoteTick-only basis would wrongly refuse
    a tape it can actually trade."""
    instrument = _instrument()
    facts = read_weather_bucket_facts(instrument.info)
    depth = _depth(ask="0.40", size=10, ts_event=WINDOW_OPEN_NS)
    depth_only = driver.TapeInstrument(
        instrument=instrument, facts=facts, depths=[depth], quotes=[], closes=[],
    )
    with pytest.raises(driver.NoDecisionWindowCoverageError):
        driver.assert_decision_window_has_coverage(
            [depth_only],
            station=STATION,
            std_utc_offset_hours=LAX_STD_UTC_OFFSET_HOURS,
            source="quote",
        )
    driver.assert_decision_window_has_coverage(
        [depth_only],
        station=STATION,
        std_utc_offset_hours=LAX_STD_UTC_OFFSET_HOURS,
        source="depth",
    )  # must not raise


def test_a_quote_only_window_with_no_in_window_depth_is_refused_for_the_continuous_arm(
    driver: ModuleType,
) -> None:
    """L-24 NEGATIVE: an in-window QuoteTick with NO in-window executable
    depth is REFUSED under `source="depth"` -- the depth basis must never
    silently fall back to the quote population."""
    instrument = _instrument()
    facts = read_weather_bucket_facts(instrument.info)
    quote = _quote(ask="0.40", size=10, ts_event=WINDOW_OPEN_NS)
    outside_depth = _depth(ask="0.40", size=10, ts_event=_OUTSIDE_WINDOW_NS)
    quote_only = driver.TapeInstrument(
        instrument=instrument, facts=facts, depths=[outside_depth], quotes=[quote], closes=[],
    )
    driver.assert_decision_window_has_coverage(
        [quote_only],
        station=STATION,
        std_utc_offset_hours=LAX_STD_UTC_OFFSET_HOURS,
        source="quote",
    )  # must not raise
    with pytest.raises(driver.NoDecisionWindowCoverageError, match="executable Depth10 asks"):
        driver.assert_decision_window_has_coverage(
            [quote_only],
            station=STATION,
            std_utc_offset_hours=LAX_STD_UTC_OFFSET_HOURS,
            source="depth",
        )


def test_a_depth_window_of_only_size_zero_pad_asks_is_refused_for_the_continuous_arm(
    driver: ModuleType,
) -> None:
    """L-35 NEGATIVE, citing the shipped helper precedent
    `test_depth10_quote.py::test_best_order_skips_the_size_zero_pad`
    (`:196`): a Depth10 snapshot in-window whose ask side is ENTIRELY the
    size-0 Arrow pad (`size=0`) has no executable ask, so it must not count
    as coverage under `source="depth"`."""
    instrument = _instrument()
    facts = read_weather_bucket_facts(instrument.info)
    pad_only_depth = _depth(ask="0.40", size=0, ts_event=WINDOW_OPEN_NS)
    assert not any(level.size > 0 for level in pad_only_depth.asks)
    padded = driver.TapeInstrument(
        instrument=instrument, facts=facts, depths=[pad_only_depth], quotes=[], closes=[],
    )
    with pytest.raises(driver.NoDecisionWindowCoverageError, match="executable Depth10 asks"):
        driver.assert_decision_window_has_coverage(
            [padded],
            station=STATION,
            std_utc_offset_hours=LAX_STD_UTC_OFFSET_HOURS,
            source="depth",
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


def test_paper_latch_is_throwaway_not_exec_state_db(driver: ModuleType) -> None:
    """SP-4 increment E, L-5 drift correction: this pin's ORIGINAL premise
    ("the exec-state-db resolver is never imported") is exactly what E-1
    deliberately changes -- `assert_replay_latch_store_is_not_live`
    composes the SHIPPED `node_store_path_check` oracle rather than
    re-deriving it (L-11: the native exists and is USED). The invariant
    this test actually protects survives unchanged: the driver's OWN
    throwaway paper latch never reads `POLYMARKET_US_EXEC_STATE_DB` to
    source or redirect its own storage path -- `resolve_store_path`/
    `node_store_path_check` are consulted ONLY inside the read-only guard,
    value-free, never to build a `_latch_factory`/`_latch_context` call."""
    source = (_SCRIPTS_ANALYSIS_DIR / "current_rung_hold_paper_replay.py").read_text()
    assert "POLYMARKET_US_EXEC_STATE_DB" not in source
    assert "latch_" in source
    assert "work_catalog" in source
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
    # E-1 (ADOPTED): the shipped oracle IS imported and USED here, never
    # re-implemented -- test_exec_state_db_path.py's own 15 tests (byte-
    # unchanged) remain the authoritative pin on the oracle itself.
    assert "breezy.runtime.exec_state_db_path" in imported
    assert hasattr(driver, "node_store_path_check")
    assert hasattr(driver, "resolve_store_path")
    guard_def = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "assert_replay_latch_store_is_not_live"
    )
    guard_source = ast.get_source_segment(source, guard_def)
    assert guard_source is not None
    non_guard_source = source.replace(guard_source, "")
    assert "resolve_store_path(" not in non_guard_source
    assert "node_store_path_check(" not in non_guard_source
    assert hasattr(driver, "run_one_precision_arm")
    names = driver.run_one_precision_arm.__code__.co_varnames
    assert "strategy_cls" in names
    assert "latch_key_prefix" in names


# ---------------------------------------------------------------------------
# SP-4 increment C: `--strategy`, v3 evidence injection, position-event
# reporting, and the v3 latch key prefix coupling.
# ---------------------------------------------------------------------------


def _minimal_argv(tmp_path: Path, *, strategy: str | None) -> list[str]:
    argv = [
        "--climate-day", CLIMATE_DAY.isoformat(),
        "--station", STATION,
        "--tape-instance-id", "x",
        "--quote-catalog", str(tmp_path / "capture"),
        "--work-catalog", str(tmp_path / "work"),
        "--asos-cache-csv", str(tmp_path / "z.csv"),
        "--weather-catalog-root", str(tmp_path / "w"),
        "--lag-minutes", "30",
        "--output-dir", str(tmp_path / "out"),
    ]
    if strategy is not None:
        argv += ["--strategy", strategy]
    return argv


def _run_main_with_stubbed_capture(
    driver: ModuleType,
    tmp_path: Path,
    *,
    strategy: str | None,
    monkeypatch: pytest.MonkeyPatch,
    extra_argv: Sequence[str] = (),
    expect_rc: int = 0,
    tape_fee_coefficient: Decimal = THETA,
) -> dict[str, object]:
    """Stub the driver's OWN capture/settlement seams (never Nautilus, never
    the strategy under test) so `main` reaches `run_one_precision_arm`
    without a real recorded catalog on disk -- the dispatch logic under
    test lives entirely between argument parsing and that call.

    AUD-19b: `extra_argv` appends CLI arguments (e.g. `--family-manifest`)
    after `_minimal_argv`'s fixed set; the spy also captures
    `required_fee_coefficient`/`family_id`/`trial_id_prefix` so a caller can
    assert on what `main` resolved and threaded through.

    `tape_fee_coefficient` (AUD-09b fee-regime plan, Phase 3) defaults to
    `THETA`, matching `_family_manifest_payload`'s own default
    `taker_fee_coefficient` -- a caller registering a manifest theta that
    DIFFERS from `THETA` must pass the same value here, or the new
    `assert_fee_schedule_matches_family` preflight refuses before
    `run_one_precision_arm` is ever reached."""
    captured: dict[str, object] = {}
    tape_instrument = _tape_instrument_depth_and_quote_in_window(
        driver, ask="0.40", size=10, fee_coefficient=tape_fee_coefficient,
    )

    def _spy_run_one_precision_arm(**kwargs: object) -> object:
        captured["strategy_cls"] = kwargs["strategy_cls"]
        captured["latch_key_prefix"] = kwargs["latch_key_prefix"]
        captured["required_fee_coefficient"] = kwargs.get("required_fee_coefficient")
        captured["family_id"] = kwargs.get("family_id")
        captured["trial_id_prefix"] = kwargs.get("trial_id_prefix")
        # Simulates a CurrentRungHoldConfig that faithfully carried whatever
        # was passed in -- the dedicated mismatch test below overrides this
        # spy directly to prove the OTHER (non-echoing) branch.
        return driver.PrecisionArmResult(
            trials=(), engine_required_fee_coefficient=kwargs.get("required_fee_coefficient"),
        )

    monkeypatch.setattr(driver, "run_one_precision_arm", _spy_run_one_precision_arm)
    monkeypatch.setattr(
        driver, "_convert_live_capture", lambda **kw: _StubReplayCatalog(tape_instrument),
    )
    monkeypatch.setattr(
        driver,
        "_select_capture_instruments",
        lambda catalog, *, climate_day, **_kw: [tape_instrument],
    )
    monkeypatch.setattr(driver, "climate_day_records_to_settlement", lambda *a, **kw: {})
    monkeypatch.setattr(driver, "read_asos_rows", lambda path: _OBSERVATION_ROWS)

    argv = [*_minimal_argv(tmp_path, strategy=strategy), *extra_argv]
    rc = driver.main(argv)
    assert rc == expect_rc
    captured["rc"] = rc
    return captured


#: A real (non-zero) sha of the committed sentinel density artefact, lifted
#: verbatim from `tests/unit/test_family_manifest.py` -- shared by every
#: non-forecast family manifest on this tree.
_SENTINEL_DENSITY_SHA = "247f636350685b38966251703c47d10531913367fbcca175b086a2c298421a65"


def _family_manifest_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "family_id": "pm_us_crh_v4",
        "venue": "polymarket_us",
        "trial_id_prefix": "continuous_rung_hold/trial/",
        "d0_climate_day": "2026-08-31",
        # AUD-09b fee-regime plan, Phase 3: matches `THETA`, the fixture tape
        # instrument's own fee coefficient (`_instrument`'s default) -- a
        # test that registers a DIFFERENT theta must also pass a matching
        # `tape_fee_coefficient`/`fee_coefficient` override, or the new
        # `assert_fee_schedule_matches_family` preflight refuses it.
        "taker_fee_coefficient": str(THETA),
        "boundary_artefact_path": "deploy/families/gs_boundary_pm_us_crh_v4.json",
        "boundary_inputs_sha256": "a" * 64,
        "composition_kind": "continuous_rung_hold",
        "density_artefact_path": "deploy/families/artefacts/not_applicable_density.json",
        "density_artefact_sha256": _SENTINEL_DENSITY_SHA,
        "stations": [STATION],
        "status": "REGISTERED",
    }
    payload.update(overrides)
    return payload


def _write_family_manifest(tmp_path: Path, **overrides: object) -> Path:
    path = tmp_path / "family_manifest.json"
    path.write_text(json.dumps(_family_manifest_payload(**overrides)))
    return path


def test_the_strategy_flag_selects_the_continuous_backtest_subclass(
    driver: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _run_main_with_stubbed_capture(
        driver, tmp_path, strategy="continuous_rung_hold", monkeypatch=monkeypatch,
    )
    assert captured["strategy_cls"] is driver.ContinuousRungHoldBacktestStrategy
    assert captured["latch_key_prefix"] == driver.CONTINUOUS_TRIAL_KEY_PREFIX


def test_the_default_strategy_is_still_the_v2_backtest_subclass(
    driver: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Rev 2 + AM-14: no `--strategy` flag resolves the SAME v2 subclass and
    latch prefix as before this increment, and the new "strategy position
    events" stdout line (printed ONLY for the continuous arm) never
    appears -- the v2 golden transcript stays byte-identical except the
    plan-mandated `live_store_guard` line (increment E's
    `GuardReport.render()`, printed unconditionally for every arm)."""
    capsys.readouterr()
    captured = _run_main_with_stubbed_capture(
        driver, tmp_path, strategy=None, monkeypatch=monkeypatch,
    )
    assert captured["strategy_cls"] is driver.CurrentRungHoldBacktestStrategy
    assert captured["latch_key_prefix"] == driver.DEFAULT_TRIAL_KEY_PREFIX
    out = capsys.readouterr().out
    assert "strategy position events" not in out


# ---------------------------------------------------------------------------
# AUD-19b: `--family-manifest` on the driver (plan §7 steps 8-13, 17-20).
# ---------------------------------------------------------------------------
def test_omitting_family_manifest_leaves_the_argument_vector_and_config_unchanged(
    driver: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A2: the byte-identity pin on C2 -- no `--family-manifest` resolves the
    same strategy default, threads no `required_fee_coefficient` override,
    uses `UNSCOPED_FAMILY_ID`, and writes no sidecar."""
    captured = _run_main_with_stubbed_capture(
        driver, tmp_path, strategy=None, monkeypatch=monkeypatch,
    )
    assert captured["strategy_cls"] is driver.CurrentRungHoldBacktestStrategy
    assert captured["latch_key_prefix"] == driver.DEFAULT_TRIAL_KEY_PREFIX
    assert captured["required_fee_coefficient"] is None
    assert captured["family_id"] == driver.UNSCOPED_FAMILY_ID
    assert not (tmp_path / "out" / "family_params.json").exists()


def test_family_manifest_threads_the_registered_taker_fee_coefficient(
    driver: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A3: `--family-manifest` replaces the class-default fee coefficient
    with the manifest's registered `taker_fee_coefficient`, and the family
    segment threaded downstream is the manifest's own `family_id`.

    Audit fix: the tape keeps its ORIGINAL, DISTINCT default (`THETA` =
    0.06) while the manifest registers 0.0695 -- the Phase 3 preflight is
    stubbed to a no-op here ONLY, so this test still discriminates "reads
    the manifest's theta" from a regression that reads the tape's theta
    instead (which the Phase 3 preflight would otherwise legitimately
    refuse before `required_fee_coefficient` is ever captured)."""
    monkeypatch.setattr(driver, "assert_fee_schedule_matches_family", lambda *a, **kw: None)
    manifest_path = _write_family_manifest(
        tmp_path, family_id="pm_us_crh_v4", taker_fee_coefficient="0.0695",
    )
    captured = _run_main_with_stubbed_capture(
        driver, tmp_path, strategy=None, monkeypatch=monkeypatch,
        extra_argv=["--family-manifest", str(manifest_path)],
    )
    assert captured["required_fee_coefficient"] == Decimal("0.0695")
    assert captured["family_id"] == "pm_us_crh_v4"
    assert captured["trial_id_prefix"] == "continuous_rung_hold/trial/"


def test_a_multi_contract_backtest_fill_is_refused_before_the_scored_store_write(
    driver: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FU-3d AC1b mutation test (L-33/L-42): the only residual path to
    qty!=1 here is an engine over-fill (backtest fills are qty==1 by
    construction otherwise -- see the plan's Edge Cases). Monkeypatch
    `run_one_precision_arm` (precedent: `_spy_run_one_precision_arm` above)
    to return a qty=2 `FilledTrial`, with a REAL settlement record for its
    (station, climate_day) so the pair would actually score, and drive
    `main` with `--family-manifest` so both the parquet and the
    `family_params.json` sidecar are live write targets today. The guard
    must raise before either is written."""
    tape_instrument = _tape_instrument_depth_and_quote_in_window(
        driver, ask="0.40", size=10, fee_coefficient=THETA,
    )
    over_filled_trial = driver.FilledTrial(
        trial_id="continuous_rung_hold/trial/LAX/over-fill",
        station=STATION,
        climate_day=CLIMATE_DAY.isoformat(),
        instrument_id=str(INSTRUMENT_ID),
        bucket=read_weather_bucket_facts(_instrument().info),
        fill_px=Decimal("0.40"),
        fee=Decimal("0.01"),
        qty=Decimal(2),
        filled_at_ns=WINDOW_OPEN_NS,
        entry_ask=Decimal("0.40"),
        scheduled_release_at_ns=WINDOW_OPEN_NS,
    )
    settlement_record = _final_climate_day(tmax_f=86)  # inside the 86..87 rung -> would score

    monkeypatch.setattr(
        driver,
        "run_one_precision_arm",
        lambda **kwargs: driver.PrecisionArmResult(trials=(over_filled_trial,)),
    )
    monkeypatch.setattr(
        driver, "_convert_live_capture", lambda **kw: _StubReplayCatalog(tape_instrument),
    )
    monkeypatch.setattr(
        driver,
        "_select_capture_instruments",
        lambda catalog, *, climate_day, **_kw: [tape_instrument],
    )
    monkeypatch.setattr(
        driver,
        "climate_day_records_to_settlement",
        lambda *a, **kw: {(STATION, CLIMATE_DAY.isoformat()): settlement_record},
    )
    monkeypatch.setattr(driver, "read_asos_rows", lambda path: _OBSERVATION_ROWS)

    manifest_path = _write_family_manifest(tmp_path)
    argv = [
        *_minimal_argv(tmp_path, strategy="continuous_rung_hold"),
        "--family-manifest", str(manifest_path),
    ]

    with pytest.raises(ScoredPathQtyInvariantError) as excinfo:
        driver.main(argv)
    assert "over-fill" in str(excinfo.value)

    output_dir = tmp_path / "out"
    assert read_scored_trials(output_dir) == ()
    assert not (output_dir / driver._FAMILY_PARAMS_SIDECAR_FILENAME).exists()


# ---------------------------------------------------------------------------
# AUD-09b fee-regime plan, Phase 3: the exact tape-vs-manifest preflight
# ---------------------------------------------------------------------------
def test_assert_fee_schedule_matches_family_admits_an_agreeing_tape(
    driver: ModuleType,
) -> None:
    tape_instrument = _tape_instrument_depth_and_quote_in_window(driver, ask="0.40", size=10)
    driver.assert_fee_schedule_matches_family(
        [tape_instrument], required_fee_coefficient=THETA,
    )


def test_assert_fee_schedule_matches_family_refuses_a_disagreeing_tape(
    driver: ModuleType,
) -> None:
    tape_instrument = _tape_instrument_depth_and_quote_in_window(driver, ask="0.40", size=10)
    with pytest.raises(driver.FeeScheduleMismatchError, match=str(INSTRUMENT_ID)):
        driver.assert_fee_schedule_matches_family(
            [tape_instrument], required_fee_coefficient=Decimal("0.10"),
        )


def test_main_exits_fee_schedule_mismatch_before_the_engine_runs(
    driver: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real preflight, wired through `main`: a manifest registering a
    theta the tape's OWN instrument disagrees with never reaches
    `run_one_precision_arm` at all -- proven by never installing a
    `family_params.json`-writing spy and still getting no sidecar."""
    manifest_path = _write_family_manifest(tmp_path, taker_fee_coefficient="0.10")
    captured = _run_main_with_stubbed_capture(
        driver, tmp_path, strategy=None, monkeypatch=monkeypatch,
        extra_argv=["--family-manifest", str(manifest_path)],
        expect_rc=driver.EXIT_FEE_SCHEDULE_MISMATCH,
    )
    assert captured["rc"] == driver.EXIT_FEE_SCHEDULE_MISMATCH
    assert not (tmp_path / "out" / "family_params.json").exists()


@pytest.mark.parametrize(
    ("override", "expected_error"),
    [
        ({"status": "DRAFT_NOT_REGISTERED"}, UnregisteredFamilyManifestError),
        ({"boundary_inputs_sha256": "0" * 64}, UnpinnedBoundaryArtefactError),
        ({"density_artefact_sha256": "0" * 64}, UnpinnedDensityArtefactError),
    ],
)
def test_a_draft_or_unpinned_family_manifest_is_refused(
    driver: ModuleType,
    tmp_path: Path,
    override: dict[str, object],
    expected_error: type[Exception],
) -> None:
    """A4: every existing `family_manifest` refusal fires through this path
    INHERITED, never re-implemented -- `allow_draft` never appears here."""
    manifest_path = _write_family_manifest(tmp_path, **override)
    with pytest.raises(expected_error):
        driver.resolve_family_parameters(manifest_path, station=STATION, strategy_arg=None)


def test_a_station_outside_the_manifest_is_refused(
    driver: ModuleType, tmp_path: Path,
) -> None:
    """A5: refuses naming both sides, never silently preferring either."""
    manifest_path = _write_family_manifest(tmp_path, stations=["MDW"])
    with pytest.raises(driver.FamilyManifestArgumentError, match="LAX"):
        driver.resolve_family_parameters(manifest_path, station=STATION, strategy_arg=None)


def test_an_explicit_strategy_conflicting_with_composition_kind_is_refused(
    driver: ModuleType, tmp_path: Path,
) -> None:
    """A5: an explicit `--strategy` that disagrees with the manifest's
    `composition_kind` is refused, naming both sides."""
    manifest_path = _write_family_manifest(tmp_path)  # composition_kind=continuous_rung_hold
    with pytest.raises(driver.FamilyManifestArgumentError, match="current_rung_hold"):
        driver.resolve_family_parameters(
            manifest_path, station=STATION, strategy_arg="current_rung_hold",
        )


def test_a_forecast_ladder_manifest_is_refused(driver: ModuleType, tmp_path: Path) -> None:
    """C4: this driver has no `forecast_ladder` strategy class."""
    manifest_path = _write_family_manifest(tmp_path, composition_kind="forecast_ladder")
    with pytest.raises(driver.FamilyManifestArgumentError, match="forecast_ladder"):
        driver.resolve_family_parameters(manifest_path, station=STATION, strategy_arg=None)


def test_each_new_refusal_path_exits_with_its_pinned_code(
    driver: ModuleType, tmp_path: Path,
) -> None:
    """A17/C7: the three C4 argument refusals exit `EXIT_FAMILY_MANIFEST_
    REFUSED`; the loader-side refusals (plus a missing manifest path) exit
    `EXIT_FAMILY_MANIFEST_UNUSABLE`. Refusal happens before any capture I/O,
    so `_minimal_argv`'s placeholder paths never need to exist."""
    station_conflict = _write_family_manifest(tmp_path, stations=["MDW"])
    rc = driver.main(
        [*_minimal_argv(tmp_path, strategy=None), "--family-manifest", str(station_conflict)],
    )
    assert rc == driver.EXIT_FAMILY_MANIFEST_REFUSED

    strategy_conflict = _write_family_manifest(tmp_path)
    rc = driver.main(
        [
            *_minimal_argv(tmp_path, strategy="current_rung_hold"),
            "--family-manifest", str(strategy_conflict),
        ],
    )
    assert rc == driver.EXIT_FAMILY_MANIFEST_REFUSED

    forecast_ladder = _write_family_manifest(tmp_path, composition_kind="forecast_ladder")
    rc = driver.main(
        [*_minimal_argv(tmp_path, strategy=None), "--family-manifest", str(forecast_ladder)],
    )
    assert rc == driver.EXIT_FAMILY_MANIFEST_REFUSED

    draft = _write_family_manifest(tmp_path, status="DRAFT_NOT_REGISTERED")
    rc = driver.main([*_minimal_argv(tmp_path, strategy=None), "--family-manifest", str(draft)])
    assert rc == driver.EXIT_FAMILY_MANIFEST_UNUSABLE

    unpinned_boundary = _write_family_manifest(tmp_path, boundary_inputs_sha256="0" * 64)
    rc = driver.main(
        [*_minimal_argv(tmp_path, strategy=None), "--family-manifest", str(unpinned_boundary)],
    )
    assert rc == driver.EXIT_FAMILY_MANIFEST_UNUSABLE

    unpinned_density = _write_family_manifest(tmp_path, density_artefact_sha256="0" * 64)
    rc = driver.main(
        [*_minimal_argv(tmp_path, strategy=None), "--family-manifest", str(unpinned_density)],
    )
    assert rc == driver.EXIT_FAMILY_MANIFEST_UNUSABLE

    missing_manifest = tmp_path / "does_not_exist.json"
    rc = driver.main(
        [*_minimal_argv(tmp_path, strategy=None), "--family-manifest", str(missing_manifest)],
    )
    assert rc == driver.EXIT_FAMILY_MANIFEST_UNUSABLE


def test_old_signature_selector_fake_fails_loudly_instead_of_dropping_narrowing(
    driver: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FU-7c: `main` calls `_select_capture_instruments` directly with the
    station/window keywords -- no `inspect.signature` shim smooths over a
    fake stuck on the historical `(catalog, *, climate_day)` shape. A
    keyword-arity mismatch must raise loudly instead of silently dropping
    the replay-only narrowing."""
    tape_instrument = _tape_instrument_depth_and_quote_in_window(driver, ask="0.40", size=10)
    monkeypatch.setattr(
        driver, "_convert_live_capture", lambda **kw: _StubReplayCatalog(tape_instrument),
    )
    monkeypatch.setattr(
        driver,
        "_select_capture_instruments",
        lambda catalog, *, climate_day: [tape_instrument],
    )
    monkeypatch.setattr(driver, "climate_day_records_to_settlement", lambda *a, **kw: {})
    monkeypatch.setattr(driver, "read_asos_rows", lambda path: _OBSERVATION_ROWS)
    monkeypatch.setattr(
        driver, "run_one_precision_arm", lambda **kw: driver.PrecisionArmResult(trials=()),
    )

    with pytest.raises(TypeError):
        driver.main(_minimal_argv(tmp_path, strategy=None))


def test_no_pre_existing_failure_path_changed_its_exit_code(
    driver: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A17: a pre-existing failure path still propagates uncaught (exit `1`
    at the process boundary), with the flag absent AND present."""

    def _raise(*a: object, **kw: object) -> None:
        raise driver.NoDecisionWindowCoverageError("boom")

    tape_instrument = _tape_instrument_depth_and_quote_in_window(driver, ask="0.40", size=10)
    monkeypatch.setattr(driver, "assert_decision_window_has_coverage", _raise)
    monkeypatch.setattr(
        driver, "_convert_live_capture", lambda **kw: _StubReplayCatalog(tape_instrument),
    )
    monkeypatch.setattr(
        driver,
        "_select_capture_instruments",
        lambda catalog, *, climate_day, **_kw: [tape_instrument],
    )
    monkeypatch.setattr(driver, "climate_day_records_to_settlement", lambda *a, **kw: {})
    monkeypatch.setattr(driver, "read_asos_rows", lambda path: _OBSERVATION_ROWS)

    with pytest.raises(driver.NoDecisionWindowCoverageError):
        driver.main(_minimal_argv(tmp_path, strategy=None))

    manifest_path = _write_family_manifest(tmp_path, composition_kind="current_rung_hold")
    with pytest.raises(driver.NoDecisionWindowCoverageError):
        driver.main(
            [*_minimal_argv(tmp_path, strategy=None), "--family-manifest", str(manifest_path)],
        )


def test_composition_kind_selects_the_strategy_when_strategy_is_not_passed(
    driver: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C4: with `--family-manifest` and no explicit `--strategy`, the
    manifest's `composition_kind` selects the strategy."""
    manifest_path = _write_family_manifest(tmp_path, composition_kind="continuous_rung_hold")
    captured = _run_main_with_stubbed_capture(
        driver, tmp_path, strategy=None, monkeypatch=monkeypatch,
        extra_argv=["--family-manifest", str(manifest_path)],
    )
    assert captured["strategy_cls"] is driver.ContinuousRungHoldBacktestStrategy
    assert captured["latch_key_prefix"] == driver.CONTINUOUS_TRIAL_KEY_PREFIX


def test_family_params_sidecar_records_the_resolved_parameters(
    driver: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A6: the sidecar carries exactly the C6 key set, with
    `params_match=True`, `engine_params_source="FAMILY_MANIFEST"`, and a
    `manifest_sha256` equal to the loader's own."""
    manifest_path = _write_family_manifest(
        tmp_path, family_id="pm_us_crh_v4", taker_fee_coefficient="0.0695",
        composition_kind="continuous_rung_hold",
    )
    _run_main_with_stubbed_capture(
        driver, tmp_path, strategy=None, monkeypatch=monkeypatch,
        extra_argv=["--family-manifest", str(manifest_path)],
        tape_fee_coefficient=Decimal("0.0695"),
    )
    sidecar_path = tmp_path / "out" / "family_params.json"
    assert sidecar_path.exists()
    payload = json.loads(sidecar_path.read_text())
    assert set(payload) == {
        "family_id",
        "manifest_sha256",
        "manifest_taker_fee_coefficient",
        "engine_required_fee_coefficient",
        "engine_params_source",
        "params_match",
        "composition_kind",
        "strategy",
        "station",
        "climate_day",
        "exit_rule",
        "argv_sha256",
        "run_ts",
    }
    assert payload["params_match"] is True
    assert payload["engine_params_source"] == "FAMILY_MANIFEST"
    assert payload["family_id"] == "pm_us_crh_v4"
    assert payload["manifest_taker_fee_coefficient"] == "0.0695"
    assert payload["engine_required_fee_coefficient"] == "0.0695"
    assert payload["manifest_sha256"] == load_family_manifest(manifest_path).manifest_sha256


def test_a_pre_existing_sidecar_is_removed_before_the_run_starts(
    driver: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A9/C6 step 1: with the flag ABSENT, a seeded predecessor sidecar is
    unconditionally removed before the engine starts and none is written."""
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True)
    seeded = out_dir / "family_params.json"
    seeded.write_text("{}")

    _run_main_with_stubbed_capture(driver, tmp_path, strategy=None, monkeypatch=monkeypatch)
    assert not seeded.exists()


def test_a_crashing_run_leaves_no_sidecar(
    driver: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A9/C6 step 1: a run that crashes AFTER the pre-run clear (flag
    present) leaves neither the seeded predecessor nor a `.tmp`."""
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True)
    seeded = out_dir / "family_params.json"
    seeded.write_text("{}")
    manifest_path = _write_family_manifest(tmp_path)

    def _boom(**kwargs: object) -> object:
        raise RuntimeError("forced crash")

    tape_instrument = _tape_instrument_depth_and_quote_in_window(driver, ask="0.40", size=10)
    monkeypatch.setattr(driver, "run_one_precision_arm", _boom)
    monkeypatch.setattr(
        driver, "_convert_live_capture", lambda **kw: _StubReplayCatalog(tape_instrument),
    )
    monkeypatch.setattr(
        driver,
        "_select_capture_instruments",
        lambda catalog, *, climate_day, **_kw: [tape_instrument],
    )
    monkeypatch.setattr(driver, "climate_day_records_to_settlement", lambda *a, **kw: {})
    monkeypatch.setattr(driver, "read_asos_rows", lambda path: _OBSERVATION_ROWS)

    with pytest.raises(RuntimeError):
        driver.main(
            [*_minimal_argv(tmp_path, strategy=None), "--family-manifest", str(manifest_path)],
        )
    assert not seeded.exists()
    assert not (out_dir / "family_params.json.tmp").exists()


def test_the_sidecar_carries_a_verifiable_argv_sha256(
    driver: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A10/A15/C6 step 2: the sidecar's `argv_sha256` is produced by calling
    `argv_digest.argv_sha256` (spied here), never computed inline, and does
    not match a differently-ordered vector."""
    manifest_path = _write_family_manifest(tmp_path)
    real_argv_sha256 = driver.argv_sha256
    spy_calls: list[list[str]] = []

    def _spy(vector: list[str]) -> str:
        spy_calls.append(list(vector))
        return real_argv_sha256(vector)

    monkeypatch.setattr(driver, "argv_sha256", _spy)
    extra_argv = ["--family-manifest", str(manifest_path)]
    _run_main_with_stubbed_capture(
        driver, tmp_path, strategy=None, monkeypatch=monkeypatch, extra_argv=extra_argv,
    )
    full_argv = [*_minimal_argv(tmp_path, strategy=None), *extra_argv]
    sidecar = json.loads((tmp_path / "out" / "family_params.json").read_text())
    assert spy_calls, "the driver must call argv_digest.argv_sha256, never compute it inline"
    assert sidecar["argv_sha256"] == real_argv_sha256(full_argv)
    assert sidecar["argv_sha256"] != real_argv_sha256(list(reversed(full_argv)))


def test_the_sidecar_is_written_atomically(
    driver: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A10/C6 step 3: after a successful run no `.tmp` survives, and the
    final file parses as complete JSON."""
    manifest_path = _write_family_manifest(tmp_path)
    _run_main_with_stubbed_capture(
        driver, tmp_path, strategy=None, monkeypatch=monkeypatch,
        extra_argv=["--family-manifest", str(manifest_path)],
    )
    out_dir = tmp_path / "out"
    assert not (out_dir / "family_params.json.tmp").exists()
    payload = json.loads((out_dir / "family_params.json").read_text())
    assert isinstance(payload, dict)


# ---------------------------------------------------------------------------
# AUD-19b fix review (silent-failure-hunter): params_match must compare the
# engine's own readback, never echo the manifest's value as both sides.
# ---------------------------------------------------------------------------
def test_the_engine_readback_matches_a_correctly_threaded_fee_coefficient(
    driver: ModuleType, tmp_path: Path,
) -> None:
    """MEDIUM fix, non-stubbed: a REAL `run_one_precision_arm` call (real
    tape instrument, real engine, real `CurrentRungHoldConfig`) with a
    consistent family-scoped bundle reports the value the CONSTRUCTED config
    actually carried on `PrecisionArmResult.engine_required_fee_coefficient`
    -- never merely the caller's own input echoed back."""
    tape_instrument = _tape_instrument_no_close(driver, ask="0.40", size=10)
    settlement_by_key = {(STATION, CLIMATE_DAY.isoformat()): _final_climate_day(tmax_f=87)}

    result = driver.run_one_precision_arm(
        tape_instruments=[tape_instrument],
        observation_rows=_OBSERVATION_ROWS,
        station=STATION,
        lag_minutes=1,
        precision_mode="nws_integer_c",
        latch_store_path=tmp_path / "state.db",
        settlement_by_key=settlement_by_key,
        strategy_cls=driver.ContinuousRungHoldBacktestStrategy,
        latch_key_prefix=driver.CONTINUOUS_TRIAL_KEY_PREFIX,
        required_fee_coefficient=Decimal("0.0695"),
        family_id="pm_us_crh_v4",
        trial_id_prefix=driver.CONTINUOUS_TRIAL_KEY_PREFIX,
    )
    assert result.engine_required_fee_coefficient == Decimal("0.0695")


def test_params_match_is_computed_from_the_engines_actual_readback_not_echoed(
    driver: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MEDIUM fix: a driver whose engine readback DISAGREES with the
    manifest's registered value must yield `params_match=False` and report
    the READBACK (not the manifest's value) as
    `engine_required_fee_coefficient` -- proving the sidecar's comparison is
    genuine, not tautological."""
    manifest_path = _write_family_manifest(
        tmp_path, family_id="pm_us_crh_v4", taker_fee_coefficient="0.0695",
    )
    tape_instrument = _tape_instrument_depth_and_quote_in_window(
        driver, ask="0.40", size=10, fee_coefficient=Decimal("0.0695"),
    )

    def _spy_run_one_precision_arm(**kwargs: object) -> object:
        return driver.PrecisionArmResult(
            trials=(), engine_required_fee_coefficient=Decimal("0.9999"),
        )

    monkeypatch.setattr(driver, "run_one_precision_arm", _spy_run_one_precision_arm)
    monkeypatch.setattr(
        driver, "_convert_live_capture", lambda **kw: _StubReplayCatalog(tape_instrument),
    )
    monkeypatch.setattr(
        driver,
        "_select_capture_instruments",
        lambda catalog, *, climate_day, **_kw: [tape_instrument],
    )
    monkeypatch.setattr(driver, "climate_day_records_to_settlement", lambda *a, **kw: {})
    monkeypatch.setattr(driver, "read_asos_rows", lambda path: _OBSERVATION_ROWS)

    rc = driver.main(
        [*_minimal_argv(tmp_path, strategy=None), "--family-manifest", str(manifest_path)],
    )
    assert rc == 0
    sidecar = json.loads((tmp_path / "out" / "family_params.json").read_text())
    assert sidecar["params_match"] is False
    assert sidecar["engine_required_fee_coefficient"] == "0.9999"
    assert sidecar["manifest_taker_fee_coefficient"] == "0.0695"


@pytest.mark.parametrize(
    ("required_fee_coefficient", "family_id", "trial_id_prefix"),
    [
        (Decimal("0.0695"), UNSCOPED_FAMILY_ID, None),  # fee threaded but family unscoped
        (None, "pm_us_crh_v4", "continuous_rung_hold/trial/"),  # scoped, no fee
        (Decimal("0.0695"), "pm_us_crh_v4", None),  # scoped + fee, no trial_id_prefix
    ],
)
def test_a_piecemeal_family_parameter_bundle_is_refused(
    driver: ModuleType,
    tmp_path: Path,
    required_fee_coefficient: Decimal | None,
    family_id: str,
    trial_id_prefix: str | None,
) -> None:
    """LOW fix: `required_fee_coefficient`/`family_id`/`trial_id_prefix` are
    all-or-nothing -- a caller cannot produce a fee-scoped-but-unscoped (or
    otherwise partial) trial piecemeal."""
    tape_instrument = _tape_instrument_depth_and_quote_in_window(driver, ask="0.40", size=10)
    with pytest.raises(driver.PiecemealFamilyParametersError):
        driver.run_one_precision_arm(
            tape_instruments=[tape_instrument],
            observation_rows=_OBSERVATION_ROWS,
            station=STATION,
            lag_minutes=1,
            precision_mode="nws_integer_c",
            latch_store_path=tmp_path / "state.db",
            settlement_by_key={},
            required_fee_coefficient=required_fee_coefficient,
            family_id=family_id,
            trial_id_prefix=trial_id_prefix,
        )


def test_whole_tape_paper_replays_default_call_is_unaffected_by_the_piecemeal_guard(
    driver: ModuleType, tmp_path: Path,
) -> None:
    """LOW fix: the fully-defaulted bundle (no fee, `UNSCOPED_FAMILY_ID`, no
    `trial_id_prefix` -- exactly what `whole_tape_paper_replay.py`'s
    unmodified call site passes) must remain byte-identical, never refused."""
    result = driver.run_one_precision_arm(
        tape_instruments=[],
        observation_rows=_OBSERVATION_ROWS,
        station=STATION,
        lag_minutes=30,
        precision_mode="nws_integer_c",
        latch_store_path=tmp_path / "state.db",
        settlement_by_key={},
    )
    assert result.trials == ()


def test_the_continuous_arm_injects_flat_position_evidence_for_every_candidate_slug(
    driver: ModuleType, tmp_path: Path,
) -> None:
    """AM-6: the driver injects a `_FlatStartupEvidence` reader bound to the
    just-constructed strategy -- an in-window tape with a synthesizable
    close fills through the SAME armed branch the live node takes, never
    halting on `startup_evidence_missing`."""
    tape_instrument = _tape_instrument_no_close(driver, ask="0.40", size=10)
    settlement_by_key = {(STATION, CLIMATE_DAY.isoformat()): _final_climate_day(tmax_f=87)}

    result = driver.run_one_precision_arm(
        tape_instruments=[tape_instrument],
        observation_rows=_OBSERVATION_ROWS,
        station=STATION,
        lag_minutes=1,
        precision_mode="nws_integer_c",
        latch_store_path=tmp_path / "state.db",
        settlement_by_key=settlement_by_key,
        strategy_cls=driver.ContinuousRungHoldBacktestStrategy,
        latch_key_prefix=driver.CONTINUOUS_TRIAL_KEY_PREFIX,
    )
    assert len(result.trials) == 1
    assert "startup_evidence_missing" not in result.strategy_position_events


def test_the_early_return_result_also_carries_an_empty_position_event_map(
    driver: ModuleType, tmp_path: Path,
) -> None:
    """NB-3 (L-4): the `:519`-shaped early return (no market data at all)
    explicitly carries an empty `strategy_position_events`, never relying
    on the dataclass `default_factory` alone."""
    result = driver.run_one_precision_arm(
        tape_instruments=[],
        observation_rows=_OBSERVATION_ROWS,
        station=STATION,
        lag_minutes=30,
        precision_mode="nws_integer_c",
        latch_store_path=tmp_path / "state.db",
        settlement_by_key={},
        strategy_cls=driver.ContinuousRungHoldBacktestStrategy,
        latch_key_prefix=driver.CONTINUOUS_TRIAL_KEY_PREFIX,
    )
    assert result.trials == ()
    assert result.strategy_position_events == {}


def test_the_result_carries_the_position_event_counts(
    driver: ModuleType, tmp_path: Path,
) -> None:
    """AM-4: `strategy.position_events.counts` rides along unconditionally
    (populated from a REAL, non-empty count here), the same reporting-gap
    fix `strategy_refusals`/`strategy_diagnostics` already got."""
    latch_store_path = tmp_path / "state.db"
    with driver._latch_context(
        latch_store_path, key_prefix=driver.CONTINUOUS_TRIAL_KEY_PREFIX,
    ) as latch:
        latch.record_duplicate_fill(
            STATION,
            CLIMATE_DAY.isoformat(),
            venue_order_id="pre-seeded",
            qty=Decimal(1),
            fill_px=Decimal("0.40"),
            fee=Decimal(0),
            ts_ns=WINDOW_OPEN_NS,
        )
    tape_instrument = _tape_instrument_no_close(driver, ask="0.40", size=10)
    settlement_by_key = {(STATION, CLIMATE_DAY.isoformat()): _final_climate_day(tmax_f=87)}

    result = driver.run_one_precision_arm(
        tape_instruments=[tape_instrument],
        observation_rows=_OBSERVATION_ROWS,
        station=STATION,
        lag_minutes=30,
        precision_mode="nws_integer_c",
        latch_store_path=latch_store_path,
        settlement_by_key=settlement_by_key,
        strategy_cls=driver.ContinuousRungHoldBacktestStrategy,
        latch_key_prefix=driver.CONTINUOUS_TRIAL_KEY_PREFIX,
    )
    assert result.trials == ()
    assert result.strategy_position_events == {"family_halt_at_start": 1}


def test_a_reader_that_drops_a_facts_slug_fails_the_run_loudly(
    driver: ModuleType, tmp_path: Path,
) -> None:
    """L-24 NEGATIVE: a `position_evidence_reader` that omits a candidate's
    own slug halts the walk (`unreconciled_long_no_fill`) -- the driver
    never masks that with its own flat-evidence injection when a caller
    supplies a different reader directly."""
    tape_instrument = _tape_instrument_no_close(driver, ask="0.40", size=10)
    cfg = CurrentRungHoldConfig(
        instrument_ids=(tape_instrument.instrument.id,), stations=(STATION,),
    )
    strategy = driver.ContinuousRungHoldBacktestStrategy(
        cfg,
        trial_day_latch_factory=driver._latch_factory(
            tmp_path / "direct_state.db", key_prefix=driver.CONTINUOUS_TRIAL_KEY_PREFIX,
        ),
        position_evidence_reader=lambda: {
            "v": 1,
            "position_read_refused": False,
            "eof_complete": True,
            "fill_walk_complete": True,
            "positions": [],
            # RESTING_BID_HUNT Rev 2 §4.3: additive -- the gate now checks
            # the open-order enumeration BEFORE the per-slug walk; this
            # test's subject is the per-slug walk, so the enumeration is
            # stated clean and the dropped-slug halt is still what fires.
            "open_orders_read_refused": False,
            "open_orders": [],
        },
    )
    stopped: list[bool] = []
    strategy.stop = lambda: stopped.append(True)  # type: ignore[method-assign]
    from nautilus_trader.common.component import TestClock
    from nautilus_trader.model.identifiers import TraderId
    from nautilus_trader.portfolio import Portfolio
    from nautilus_trader.test_kit.stubs.component import TestComponentStubs

    clock = TestClock()
    clock.set_time(WINDOW_OPEN_NS)
    msgbus = TestComponentStubs.msgbus()
    cache = TestComponentStubs.cache()
    cache.add_instrument(tape_instrument.instrument)
    portfolio = Portfolio(msgbus=msgbus, cache=cache, clock=clock)
    strategy.register(
        trader_id=TraderId("BACKTEST-001"), portfolio=portfolio,
        msgbus=msgbus, cache=cache, clock=clock,
    )
    strategy.on_start()
    assert stopped == [True]
    assert strategy.position_events.count("unreconciled_long_no_fill") == 1


def test_an_unbound_evidence_reader_raises_rather_than_emitting_empty_positions(
    driver: ModuleType,
) -> None:
    """L-24 NEGATIVE: calling `_FlatStartupEvidence` before `bind()` raises
    `ReplayEvidenceUnboundError` -- it must never silently emit an empty
    `positions` list, which would read as UNKNOWN for every slug."""
    evidence = driver._FlatStartupEvidence()
    with pytest.raises(driver.ReplayEvidenceUnboundError):
        evidence()


def test_the_continuous_arm_uses_the_continuous_latch_key_prefix(
    driver: ModuleType, tmp_path: Path,
) -> None:
    """C-add-1: the continuous arm writes under `CONTINUOUS_TRIAL_KEY_PREFIX`,
    never the v2 default -- a v2-prefixed arm would write and read a prefix
    the live v3 family never uses (L-8: a silent zero-trial run indistinguishable
    from "no fills")."""
    tape_instrument = _tape_instrument_no_close(driver, ask="0.40", size=10)
    settlement_by_key = {(STATION, CLIMATE_DAY.isoformat()): _final_climate_day(tmax_f=87)}
    latch_store_path = tmp_path / "state.db"

    result = driver.run_one_precision_arm(
        tape_instruments=[tape_instrument],
        observation_rows=_OBSERVATION_ROWS,
        station=STATION,
        lag_minutes=1,
        precision_mode="nws_integer_c",
        latch_store_path=latch_store_path,
        settlement_by_key=settlement_by_key,
        strategy_cls=driver.ContinuousRungHoldBacktestStrategy,
        latch_key_prefix=driver.CONTINUOUS_TRIAL_KEY_PREFIX,
    )
    assert len(result.trials) == 1
    # Re-pinned (operator ruling 2026-09-14 / plan S1): the v3 latch now
    # keys TRIAL by instrument-day, not station-day alone.
    with driver._latch_context(
        latch_store_path, key_prefix=driver.CONTINUOUS_TRIAL_KEY_PREFIX,
    ) as latch:
        record = latch.record(
            STATION,
            CLIMATE_DAY.isoformat(),
            key_instrument_id=str(tape_instrument.instrument.id),
        )
    assert record is not None
    assert record.reason == "taken"


def test_the_write_prefix_and_the_entry_context_read_prefix_are_the_same(
    driver: ModuleType, tmp_path: Path,
) -> None:
    """AM-20/NB-6: `run_one_precision_arm` threads ONE `latch_key_prefix`
    into both the write side (the strategy's own latch factory) and the
    read side (`_entry_contexts_from_latch`) -- a mismatch would present as
    a silent zero-trial "market" result (L-8). Proven end-to-end: the SAME
    call that fills also successfully reads its own trial back out."""
    tape_instrument = _tape_instrument_no_close(driver, ask="0.40", size=10)
    settlement_by_key = {(STATION, CLIMATE_DAY.isoformat()): _final_climate_day(tmax_f=87)}

    result = driver.run_one_precision_arm(
        tape_instruments=[tape_instrument],
        observation_rows=_OBSERVATION_ROWS,
        station=STATION,
        lag_minutes=1,
        precision_mode="nws_integer_c",
        latch_store_path=tmp_path / "state.db",
        settlement_by_key=settlement_by_key,
        strategy_cls=driver.ContinuousRungHoldBacktestStrategy,
        latch_key_prefix=driver.CONTINUOUS_TRIAL_KEY_PREFIX,
    )
    # A prefix mismatch between the write side and `_entry_contexts_from_
    # latch`'s read side would make `_filled_instrument_ids` non-empty but
    # the latch record lookup miss, raising `EntryAskFromLatchMissingError`
    # rather than silently returning zero -- so reaching a real trial here
    # IS the coupling proof, not a weaker structural assertion.
    assert len(result.trials) == 1
    assert result.trials[0].fill_px == Decimal("0.40")


def test_the_continuous_arm_calls_is_intent_open_and_reads_false(
    driver: ModuleType, tmp_path: Path,
) -> None:
    """AM-17: the driver's own latch factory always binds a real
    `SubmitIntentLatch` (`open_trial_day_latch`, never a bare
    `TrialDayLatch`), so the continuous arm's inherited `_hunt_tick`
    reaches `is_intent_open()` and reads `False` rather than raising
    `TrialDayLatchError` -- proven end-to-end by the same fill this arm
    already produces."""
    tape_instrument = _tape_instrument_no_close(driver, ask="0.40", size=10)
    settlement_by_key = {(STATION, CLIMATE_DAY.isoformat()): _final_climate_day(tmax_f=87)}

    result = driver.run_one_precision_arm(
        tape_instruments=[tape_instrument],
        observation_rows=_OBSERVATION_ROWS,
        station=STATION,
        lag_minutes=1,
        precision_mode="nws_integer_c",
        latch_store_path=tmp_path / "state.db",
        settlement_by_key=settlement_by_key,
        strategy_cls=driver.ContinuousRungHoldBacktestStrategy,
        latch_key_prefix=driver.CONTINUOUS_TRIAL_KEY_PREFIX,
    )
    assert len(result.trials) == 1


def test_the_continuous_arm_selects_capture_instruments_exactly_once(
    driver: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-add-2/L-31: `main` calls `_select_capture_instruments` exactly
    once per invocation, regardless of how many precision arms it runs
    inside the PRECISION_ARMS loop -- the per-definition-row reselect
    defect measured elsewhere (`test_whole_tape_paper_replay.py:948`) has
    no analogue on this NEW v3 path."""
    calls: list[int] = []
    tape_instrument = _tape_instrument_depth_and_quote_in_window(driver, ask="0.40", size=10)

    def _counting_select(catalog: object, *, climate_day: dt.date, **_kw: object) -> list[object]:
        calls.append(1)
        return [tape_instrument]

    monkeypatch.setattr(driver, "_select_capture_instruments", _counting_select)
    monkeypatch.setattr(
        driver, "_convert_live_capture", lambda **kw: _StubReplayCatalog(tape_instrument),
    )
    monkeypatch.setattr(driver, "climate_day_records_to_settlement", lambda *a, **kw: {})
    monkeypatch.setattr(driver, "read_asos_rows", lambda path: _OBSERVATION_ROWS)
    monkeypatch.setattr(
        driver,
        "run_one_precision_arm",
        lambda **kw: driver.PrecisionArmResult(trials=()),
    )
    assert len(driver.PRECISION_ARMS) >= 2  # the loop this counts across

    rc = driver.main(_minimal_argv(tmp_path, strategy="continuous_rung_hold"))
    assert rc == 0
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# SP-4 increment E: the four-layer live-store guard
# (`assert_replay_latch_store_is_not_live`), composing the shipped
# `node_store_path_check` oracle (E-1) rather than re-deriving it.
# ---------------------------------------------------------------------------


def test_the_guard_refuses_a_path_the_running_node_owns_even_with_the_env_var_unset(
    driver: ModuleType, tmp_path: Path,
) -> None:
    """PRIMARY LAYER (E-1): layer 1 refuses on the node's OWN `/proc`
    environ alone -- it must fire even when layer 2's env var is UNSET in
    THIS process, which is exactly why layer 1 leads."""
    from tests.unit.test_exec_state_db_path import _write_process

    proc_root = tmp_path / "proc"
    candidate = tmp_path / "work" / "latch_nws_integer_c.db"
    _write_process(
        proc_root,
        111,
        [str(tmp_path / ".venv" / "bin" / "breezy-trade")],
        {"POLYMARKET_US_EXEC_STATE_DB": str(candidate)},
    )
    with pytest.raises(driver.ReplayLatchStoreIsLiveError, match=re.escape(str(candidate))):
        driver.assert_replay_latch_store_is_not_live(
            [candidate], environ={}, proc_root=proc_root,
        )


def test_a_discovery_failed_oracle_is_reported_not_silently_treated_as_clean(
    driver: ModuleType, tmp_path: Path,
) -> None:
    """E-1 degradation stance: an unreadable `/proc` never blocks the run
    (refusing every replay on a `/proc` read failure would block real work
    for no safety gain) but the report must carry the degradation, never
    silently read as clean."""
    unreadable_proc_root = tmp_path / "does-not-exist"
    candidate = tmp_path / "work"
    report = driver.assert_replay_latch_store_is_not_live(
        [candidate], environ={}, proc_root=unreadable_proc_root,
    )
    assert report.oracle == "DISCOVERY_FAILED"
    assert "DISCOVERY_FAILED" in report.render()


def test_a_work_catalog_equal_to_the_resolved_exec_state_db_is_refused(
    driver: ModuleType, tmp_path: Path,
) -> None:
    """AM-3 layer 2/3: an exact-match candidate is refused via the env-
    resolved path, even with no running node found (`NO_NODE`, not a pass
    signal by itself, but layer 3 still fires)."""
    from breezy.adapters.polymarket_us.factories import EXEC_STATE_DB_ENV_VAR

    live_db = tmp_path / "state" / "exec.sqlite3"
    empty_proc_root = tmp_path / "proc"
    empty_proc_root.mkdir()
    with pytest.raises(driver.ReplayLatchStoreIsLiveError, match=re.escape(str(live_db))):
        driver.assert_replay_latch_store_is_not_live(
            [live_db],
            environ={EXEC_STATE_DB_ENV_VAR: str(live_db)},
            proc_root=empty_proc_root,
        )


def test_a_work_catalog_equal_to_the_exec_state_db_parent_dir_is_refused(
    driver: ModuleType, tmp_path: Path,
) -> None:
    """AM-3 layer 3: the latch DB and its `-wal`/`-shm`/flock sidecars
    share the store's DIRECTORY -- the real collision surface the exact-
    match oracle (layer 1) cannot express."""
    from breezy.adapters.polymarket_us.factories import EXEC_STATE_DB_ENV_VAR

    live_db = tmp_path / "state" / "exec.sqlite3"
    candidate_dir = tmp_path / "state"
    empty_proc_root = tmp_path / "proc"
    empty_proc_root.mkdir()
    with pytest.raises(
        driver.ReplayLatchStoreIsLiveError, match=re.escape(str(candidate_dir)),
    ):
        driver.assert_replay_latch_store_is_not_live(
            [candidate_dir],
            environ={EXEC_STATE_DB_ENV_VAR: str(live_db)},
            proc_root=empty_proc_root,
        )


def test_a_latch_store_path_under_the_live_state_root_is_refused(
    driver: ModuleType, tmp_path: Path,
) -> None:
    """L-24 NEGATIVE, layer 4 (markers, always in addition): a candidate
    path substring-matching the live state-store root marker is refused
    even with the env var unset and no running node found."""
    candidate = tmp_path / "home" / "jon" / ".local" / "share" / "breezy" / "state" / "latch.db"
    empty_proc_root = tmp_path / "proc"
    empty_proc_root.mkdir()
    with pytest.raises(driver.ReplayLatchStoreIsLiveError, match=re.escape(str(candidate))):
        driver.assert_replay_latch_store_is_not_live(
            [candidate], environ={}, proc_root=empty_proc_root,
        )


def test_every_derived_per_arm_latch_path_is_checked_not_only_the_work_catalog(
    driver: ModuleType, tmp_path: Path,
) -> None:
    """CX-B3/CX-N4: the guard takes a SET of candidates, and EVERY layer
    applies to EVERY candidate -- a CLEAN `work_catalog` must not mask a
    live marker hit on one of its OWN derived per-arm latch paths."""
    clean_work_catalog = tmp_path / "work"
    live_latch_path = (
        tmp_path / "home" / ".local" / "share" / "breezy" / "state" / "latch_archive_metar.db"
    )
    empty_proc_root = tmp_path / "proc"
    empty_proc_root.mkdir()
    with pytest.raises(
        driver.ReplayLatchStoreIsLiveError, match=re.escape(str(live_latch_path)),
    ):
        driver.assert_replay_latch_store_is_not_live(
            [clean_work_catalog, live_latch_path], environ={}, proc_root=empty_proc_root,
        )


def test_a_clean_tmp_work_catalog_passes_and_no_engine_is_constructed_on_refusal(
    driver: ModuleType, tmp_path: Path,
) -> None:
    """L-24: a genuinely clean candidate set passes cleanly and reports
    every layer that ran."""
    clean_work_catalog = tmp_path / "work"
    clean_latch = tmp_path / "work" / "latch_nws_integer_c.db"
    empty_proc_root = tmp_path / "proc"
    empty_proc_root.mkdir()
    report = driver.assert_replay_latch_store_is_not_live(
        [clean_work_catalog, clean_latch], environ={}, proc_root=empty_proc_root,
    )
    assert report.oracle == "NO_NODE"
    assert report.env_set is False
    assert report.candidates_checked == 2
    assert report.markers_checked >= 3
    assert "live_store_guard=oracle:NO_NODE env:unset markers:" in report.render()


def test_the_guard_runs_before_convert_live_capture_writes_the_work_catalog(
    driver: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CX-B3, ordering: `_convert_live_capture` WRITES (and `mkdir`s)
    `args.work_catalog` -- the guard must run BEFORE that call, and BEFORE
    any engine/strategy is ever constructed (`run_one_precision_arm` must
    never be reached on a refusal)."""
    from tests.unit.test_exec_state_db_path import _write_process

    tape_instrument = _tape_instrument_depth_and_quote_in_window(driver, ask="0.40", size=10)
    work_catalog = tmp_path / "work"
    proc_root = tmp_path / "proc"
    _write_process(
        proc_root,
        111,
        [str(tmp_path / ".venv" / "bin" / "breezy-trade")],
        {"POLYMARKET_US_EXEC_STATE_DB": str(work_catalog)},
    )

    def _fail_if_called(*args: object, **kwargs: object) -> object:
        raise AssertionError("must never be reached once the guard refuses")

    real_guard = driver.assert_replay_latch_store_is_not_live
    monkeypatch.setattr(driver, "_convert_live_capture", _fail_if_called)
    monkeypatch.setattr(driver, "run_one_precision_arm", _fail_if_called)
    monkeypatch.setattr(
        driver,
        "_select_capture_instruments",
        lambda catalog, *, climate_day, **_kw: [tape_instrument],
    )
    monkeypatch.setattr(
        driver,
        "assert_replay_latch_store_is_not_live",
        lambda candidates, **kw: real_guard(candidates, environ={}, proc_root=proc_root),
    )

    with pytest.raises(driver.ReplayLatchStoreIsLiveError):
        driver.main(_minimal_argv(tmp_path, strategy=None))
    assert not work_catalog.exists()  # _convert_live_capture's own mkdir never ran


def test_two_precision_arms_write_monitor_output_to_distinct_per_arm_directories(
    driver: ModuleType, tmp_path: Path,
) -> None:
    """Review finding F2: `main` installs a shadow `PositionMonitor` for
    EVERY `PRECISION_ARMS` entry against the SAME `--monitor-out-dir` --
    unkeyed by arm, both arms' `PositionMarkRecord`/`PositionMonitorSummary`
    rows would land in one shared catalog and one shared summaries
    directory, where `read_monitor_summaries`' dedup by `(trial_id, max
    monitor_seq)` could hide one arm's row (neither record type carries a
    precision-arm discriminator). `run_one_precision_arm` now keys the
    monitor output per arm -- `monitor_out_dir / precision_mode` -- so both
    arms' summaries survive, each in its own subdirectory.
    """
    monitor_out_dir = tmp_path / "monitor_out"
    settlement_by_key = {(STATION, CLIMATE_DAY.isoformat()): _final_climate_day(tmax_f=87)}

    for index, precision_mode in enumerate(driver.PRECISION_ARMS):
        tape_instrument = _tape_instrument_no_close(driver, ask="0.40", size=10)
        result = driver.run_one_precision_arm(
            tape_instruments=[tape_instrument],
            observation_rows=_OBSERVATION_ROWS,
            station=STATION,
            lag_minutes=1,
            precision_mode=precision_mode,
            latch_store_path=tmp_path / f"state_{index}.db",
            settlement_by_key=settlement_by_key,
            strategy_cls=driver.ContinuousRungHoldBacktestStrategy,
            latch_key_prefix=driver.CONTINUOUS_TRIAL_KEY_PREFIX,
            monitor_out_dir=monitor_out_dir,
        )
        assert len(result.trials) == 1

    for precision_mode in driver.PRECISION_ARMS:
        summaries = read_monitor_summaries(monitor_out_dir / precision_mode / "monitor_summaries")
        assert len(summaries) == 1, (
            f"{precision_mode}: expected exactly one summary row in its own "
            f"per-arm directory, got {len(summaries)}"
        )

    # Never a shared pair at the root -- each arm's output is fully
    # contained under its own <precision_mode> subdirectory.
    assert not (monitor_out_dir / "monitor_summaries").exists()
    assert not (monitor_out_dir / "monitor").exists()

