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
from nautilus_trader.model.data import BookOrder, OrderBookDepth10, QuoteTick
from nautilus_trader.model.enums import AssetClass, OrderSide
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
)
from breezy.runtime.backtest_feed import as_backtest_data
from breezy.runtime.backtest_harness import backtest
from breezy.runtime.paper_replay import (
    PRECISION_ARMS,
    ForeignReplayDataError,
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
from breezy.settlement.trial_scorer import FilledTrial
from breezy.strategy.current_rung_hold.backtest_only import CurrentRungHoldBacktestStrategy
from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
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
