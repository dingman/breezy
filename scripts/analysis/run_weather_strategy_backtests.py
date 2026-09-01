"""Backtest all three Breezy weather strategies against the REAL captured tape.

WHAT THIS RUNS
--------------
Every strategy runs through the REAL harness
(``breezy.runtime.backtest_harness.run_backtest`` -- no mocked engine, no
patched Nautilus internals) against the REAL Polymarket.us quote tape at
``/home/jon/.local/share/breezy/catalog/quote_tape/polymarket_us``: NYC/MIA
high-temperature markets for 2026-08-30, ~16:05-16:11 UTC. Only the 5
instruments that actually carry BOTH order-book depth and quote data are
tradable and are the only ones included (verified at runtime, not assumed --
see :func:`_select_tape_instruments`); the other 55 captured instruments have
no book/quote rows at all.

Each of the three strategies (`CalibrationMeanReversionStrategy`,
`ForecastMispricingStrategy`, `ForecastRevisionStrategy`) runs in its OWN
`run_backtest` call, once per settlement scenario (see below), so results are
attributable per strategy.

REAL vs ASSUMED vs CONSTRUCTED -- READ THIS BEFORE THE NUMBERS BELOW
----------------------------------------------------------------------
**REAL** (measured, never fabricated):
  * The order book depth, quote ticks, and `BinaryOption` instrument
    definitions -- read verbatim from the captured tape.
  * `WeatherBucketFacts` (bucket bounds, station, measure) -- read from each
    instrument's `info`.
  * The NYC and MIA PRELIMINARY `NwsClimateDay` observations for
    2026-08-30 (`tmax_f=78` NYC, `tmax_f=91` MIA; `is_final=False`,
    `revision_seq=1`), read live from the weather catalog via
    `breezy.persistence.catalog.read_climate_days`. PRELIMINARY, not FINAL --
    this repository's own measured preliminary/final revision rate is ~7.1%
    (`/home/jon/.local/share/breezy/derived/settlement-truth/coverage.json`),
    so this reading could still change.

**ASSUMED** (an explicit, labelled input this script supplies because no real
source exists):
  * The injected forecast (`expected_high_f` per station) fed to every
    strategy's `ForecastSource`. Fixed, and deliberately NOT derived from any
    settlement observation (real or swept) -- see `_SyntheticForecastSource`.
    Breezy has no forecast ingestion at all
    (`docs/plans/FORECAST_INGESTION_PLAN.md` is unbuilt).
  * The settlement-scenario SWEEP candidates (every scenario after
    `primary_real_preliminary`) -- sensitivity values around the real
    preliminary reading, never a measured outcome.

**CONSTRUCTED** (a required harness input synthesized because the real tape
does not carry it):
  * `InstrumentClose` records. The real tape has ZERO of them (0 rows in the
    flat stream file; every settlement snapshot in the capture is
    `is_terminal=False` / `MARKET_STATUS_OPEN` -- the markets had not settled
    when the tape was captured). `run_backtest` REQUIRES exactly one
    `CONTRACT_EXPIRED` close per instrument (see
    `assert_settlement_invariants`), so one is synthesized per instrument,
    timestamped strictly after that instrument's last real market-data record.
    Its `close_price` is cosmetic: the engine reads settlement price ONLY from
    `settlement_prices` (`docs/specs/BACKTEST_VENUE_CONFIG.md` Sec.0).
  * The weather record's timestamps. The real preliminary observations were
    retrieved at ~20:32-20:50 UTC on 2026-08-30 -- AFTER the tape window ends
    (~16:11:53 UTC) -- so feeding them at their real timestamp would place
    them after every instrument's synthesized close, deep in the record
    stream. They are RESTAMPED to just before the tape window starts so they
    are available context throughout the run; `tmax_f`, `is_final`,
    `revision_seq` and every other field are untouched. Because both
    strategies gate flatten-on-observation on `is_final` (`False` here) and
    that flag defaults off in every strategy config used here, this
    restamping has no effect on trading behaviour -- it exists only so the
    weather record's *arrival* is honestly inside the observed window rather
    than centered on a timestamp that never occurred in the tape.

NEVER PRESENT AS MEASURED PERFORMANCE
---------------------------------------
Every scenario after `primary_real_preliminary` sweeps a hypothetical
settlement outcome. PnL under those scenarios describes "what this strategy
would have earned if the day had settled this way", not a measured result.
Only `primary_real_preliminary` combines a real settlement input with real
market data, and even that scenario trades against an ASSUMED forecast (no
forecast ingestion exists) -- so no number this script prints is a claim about
live trading performance.

TWO CONDITIONS: `naive` (baseline) AND `realistic`
-----------------------------------------------------
A first version of this runner used one forecast shape for every strategy: a
single, constant snapshot published at the instant the tape begins. Every one
of the three strategies traded zero or aborted every scenario under it, and
independent review found all three blockers traced to that ONE unrealistic
input, not to the strategies or the harness. Both conditions below are run and
reported; the `naive` condition is kept, unmodified, as the baseline it always
was.

* **`naive`** (baseline, unchanged): `published_at` == the tape's own first
  timestamp (a forecast 0-6 minutes old for the whole run), one constant
  snapshot per station, every strategy at its config defaults.
* **`realistic`**: three independent, individually-justified input fixes --
  never a strategy, config default, harness, or guard change:

  1. **`published_at` moved `REALISTIC_PUBLISHED_AT_OFFSET_HOURS` (6.0 hours) before
     the tape window**, for `calibration_mean_reversion` and
     `forecast_mispricing`. Real NWS forecasts are issued hours before the
     trading window they cover; a 0-6-minute-old forecast is the unrealistic
     artifact, not `stable_forecast_minutes=25.0`
     (`CalibrationMeanReversionConfig`) that it was failing. The offset is
     also comfortably inside `stale_forecast_hours=8.0` (`RiskLimits`), so it
     unblocks the stability floor without tripping the staleness ceiling.
     `expected_high_f` is UNCHANGED from the `naive` condition -- only the
     timing moves, so any behaviour change is attributable to that alone.
  2. **`forecast_mispricing` is constructed with `allow_short=False` and
     `use_limit_orders=False`.** Both are config fields the strategy already
     exposes with defaults; setting them is using a knob, not weakening the
     `BacktestOrderGuard`, which stays untouched and still refuses any naked
     short that gets through. Breezy holds no inventory at run start, so
     `SHORT_YES` is unreachable on this CLOB for a first move -- the guard's
     own message says as much ("short YES is spelled buy NO, which is a
     different InstrumentId"). The `naive` condition's `NakedShortRefusedError`
     is kept and reported as a genuine pre-live default-config defect, not
     papered over.
  3. **`forecast_revision` is given a PUBLISHED SEQUENCE, not a constant
     snapshot** (`REVISION_SEQUENCE_...` constants below, printed at
     runtime): a baseline publication `REALISTIC_PUBLISHED_AT_OFFSET_HOURS`
     before the tape, then two more inside the tape window, each
     `REVISION_STEP_F` degrees higher than the last (same sign, satisfying
     `persistence_same_sign=True` with `persistence_updates=2`). The strategy
     is structurally unable to detect a revision in a forecast that never
     changes; this is the minimum realistic input that lets it observe one.
     `allow_short` is left at its config default (`False` --
     `ForecastRevisionConfig.allow_short`, and likewise `False` for the other
     two strategies' configs) for this strategy -- unlike `forecast_mispricing`,
     this was not one of the three diagnosed blockers, so no override is
     constructed for it here. Because the default is `False`, not `True`, any
     SHORT_YES signal this strategy forms is refused before it ever reaches a
     naked-short abort: the abort path (`NakedShortRefusedError`) is
     unreachable at these defaults, and a refusal is reported exactly as it
     occurs (see `RefusalCounter`) rather than pre-emptively silenced.

None of these three touches the settlement sweep, the settlement truth, or any
forecast VALUE relative to `naive` (only #3 introduces new values, and only to
create a detectable revision, never reverse-engineered from the settlement
sweep or chosen to manufacture a profitable trade). If a strategy still does
not trade under `realistic`, that is reported plainly, with the specific gate
that blocked it -- this script does not iterate on forecast values to
manufacture trades.

WHY BOTH CONDITIONS ARE KEPT, DELIBERATELY
--------------------------------------------
On `orders_submitted`/`fills`/`ending_balance_usd` alone, every
`naive`/`realistic` row pair is identical for `forecast_mispricing` (its
`realistic` override sets `allow_short=False`, already that strategy's config
default) and for `calibration_mean_reversion`/`forecast_revision` (both
submit zero orders in EITHER condition, because `SHORTS_DISABLED` -- every
`SHORT_YES` signal refused under each strategy's own `allow_short=False`
default, see `RefusalCounter`/`derive_completion_status` -- refuses the
signal before `published_at` timing can matter). That made the two
conditions LOOK like a no-op pair. They are not: `naive` and `realistic`
differ materially in REFUSAL signal, which only became visible once
`RunResult.refusal_counts`/`status` existed. From the real
`primary_real_preliminary` scenario:

    condition  strategy                    orders  status                 refusals
    naive      calibration_mean_reversion  0       COMPLETED              {}
    naive      forecast_revision           0       COMPLETED              {}
    realistic  calibration_mean_reversion  0       COMPLETED_ALL_REFUSED  {'shorts_disabled': 2}
    realistic  forecast_revision           0       COMPLETED_ALL_REFUSED  {'shorts_disabled': 860}

Under `naive`, `calibration_mean_reversion` and `forecast_revision` never
form a `SHORT_YES` signal at all -- the unrealistic 0-6-minute-old forecast
never clears their entry gate, so there is nothing to refuse. Under
`realistic`, the same two strategies DO signal -- 860 times for
`forecast_revision` alone -- and every one is refused as `shorts_disabled`.
"Never signalled" and "signalled 860 times, every signal gagged" are
different diagnostic states: only `realistic` shows these two strategies are
functional-but-gagged by `allow_short=False` rather than simply idle. Both
conditions are retained for exactly this reason, not by inertia.

USAGE
-----
    uv run python scripts/analysis/run_weather_strategy_backtests.py

Analysis only: reads the catalogs read-only, contacts no network, places no
real orders, and writes its own JSON report under
`/home/jon/.local/share/breezy/derived/strategy-backtests/`.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import InstrumentClose, OrderBookDepth10, QuoteTick
from nautilus_trader.model.enums import InstrumentCloseType
from nautilus_trader.model.events import OrderFilled
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import BinaryOption, Instrument
from nautilus_trader.model.objects import Money
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from nautilus_trader.trading.strategy import Strategy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from weather_strategy_backtest_lib import (
    STATUS_COMPLETED,
    STATUS_COMPLETED_ALL_REFUSED,
    Scenario,
    build_settlement_scenarios,
    derive_completion_status,
    hours_until,
    latest_publication_at_or_before,
    select_tradable_instrument_ids,
    settlement_prices_for_scenario,
)

from breezy.domain.nws_climate_day import NwsClimateDay
from breezy.domain.weather_bucket_facts import WeatherBucketFacts, read_weather_bucket_facts
from breezy.persistence.catalog import open_station_catalog, read_climate_days
from breezy.runtime.backtest_feed import as_backtest_data
from breezy.runtime.backtest_harness import (
    BreezyBacktestConfig,
    NotVenueMarketDataError,
    SettlementInvariantError,
    SilentRunError,
    UnwrappedWeatherRecordError,
    run_backtest,
)
from breezy.runtime.backtest_order_guard import NakedShortRefusedError, PostOnlyRefusedError
from breezy.strategy.calibration_mean_reversion import (
    CalibrationMeanReversionConfig,
    CalibrationMeanReversionStrategy,
)
from breezy.strategy.forecast_mispricing import ForecastMispricingConfig, ForecastMispricingStrategy
from breezy.strategy.forecast_revision import ForecastRevisionConfig, ForecastRevisionStrategy
from breezy.strategy.cli_settlement_print_lock import (
    CliSettlementPrintLockConfig,
    CliSettlementPrintLockStrategy,
)
from breezy.strategy.running_extreme_lock import RunningExtremeLockConfig, RunningExtremeLockStrategy
from breezy.strategy.weather_common.forecast_source import ForecastSource
from breezy.strategy.weather_common.models import ForecastSnapshot

#: `RiskLimits.stale_observation_hours` has no shipped default (see
#: `breezy.strategy.weather_common.risk` and
#: `breezy.strategy.running_extreme_lock.config`'s module docstring) --
#: every construction site must supply an explicit value. 12.665h is the
#: measured, cited bound: 12.3167h is the MAX-over-sites P99 issuance gap
#: (MIA's OWN P99, not the pooled P99 of 12.52h -- MIA's per-site P99
#: exceeds the pooled figure, so a pooled bound would spuriously refuse
#: MIA's slowest ~1% of legitimate days), plus 0.3488h live-receipt P99.
#: Accepted consequence: the observed MAX gap is 18.80h, so this bound
#: refuses on rare legitimate days -- a deliberate conservative trade for a
#: strategy whose premise is a fresh observation. A BUILD-side decision, not
#: an operator-reserved control (see `docs/evidence/observation_lock_falsification_2026-08-31.md`
#: section 4).
STALE_OBSERVATION_HOURS_RUNNING_EXTREME_LOCK: Final[float] = 12.665

#: `RiskLimits.stale_observation_hours` has no shipped default, so this
#: construction site must supply one. It is DERIVED FOR THIS STRATEGY'S OWN
#: CADENCE and is deliberately NOT the 12.665h above: that number bounds the
#: preliminary->first-final ISSUANCE gap (how long a PRELIMINARY must stay
#: usable until the final lands), which is not a quantity this strategy's
#: signal has at all. `cli_settlement_print_lock`'s signal IS the final
#: print, so its bound is the FINAL-PRINT-TO-LAST-LEGAL-DECISION window:
#:
#:   earliest FINAL print          05:00Z  (the 05:00-13:00Z capture window,
#:                                 docs/core/PROGRESS.md BL-13; the brief's
#:                                 "12:30-05:00 local on D+1")
#:   latest venue settlement       16:00Z  (11:00 ET under EST -- the METAR
#:                                 review path from the brief's section 1;
#:                                 the ordinary 08:00 ET path is 12:00Z EDT
#:                                 / 13:00Z EST, all earlier)
#:   risk halt                     -2.0h   (`min_hours_to_settlement`, which
#:                                 binds above `halt_hours_before_settlement`
#:                                 = 1.0 -- see the evidence document's
#:                                 halt-window row)
#:   latest legal decision         14:00Z
#:   MAX legitimate print age      14:00Z - 05:00Z = 9.0h
#:
#: No receipt-lag term is added, unlike the sibling's `+ 0.3488h`. That term
#: exists there because the sibling's bound must cover "until the next
#: product ARRIVES"; here the bound covers "until a wall-clock deadline",
#: and age is measured from ISSUANCE (`SignalFreshness` contract), so a
#: record received late is already old on arrival and consumes no extra
#: headroom.
#:
#: Accepted consequence: this is the widest corner (EST + METAR review), so
#: on an ordinary EDT 08:00 ET day the bound is looser than strictly needed.
#: That is the right direction for a LIVENESS backstop -- a too-tight bound
#: refuses legitimate trades invisibly (counted `stale_observation`, alerted
#: on by nothing -- BL-14), while a loose one is still bounded by the
#: settlement halt this strategy already enforces per instrument. A
#: BUILD-side decision, not an operator-reserved control.
STALE_OBSERVATION_HOURS_CLI_SETTLEMENT_PRINT_LOCK: Final[float] = 9.0

DEFAULT_QUOTE_CATALOG_PATH: Final[Path] = Path(
    "/home/jon/.local/share/breezy/catalog/quote_tape/polymarket_us",
)
DEFAULT_WEATHER_CATALOG_ROOT: Final[Path] = Path("/home/jon/.local/share/breezy/catalog")
DEFAULT_OUTPUT_DIR: Final[Path] = Path(
    "/home/jon/.local/share/breezy/derived/strategy-backtests",
)
WEATHER_VENUE: Final[str] = "polymarket_us"
CLIMATE_DAY: Final[dt.date] = dt.date(2026, 8, 30)
STARTING_BALANCE_USD: Final[int] = 10_000
_ONE_SECOND_NS: Final[int] = 1_000_000_000

#: ASSUMED. Breezy ingests no forecast data (see module docstring); this is a
#: fixed, explicit stand-in, deliberately different from both the real
#: preliminary reading and every swept settlement candidate below, and
#: identical across every scenario/strategy run so scenario differences are
#: attributable to the settlement sweep alone, never to a moving forecast.
ASSUMED_FORECAST_HIGH_F: Final[dict[str, float]] = {"NYC": 83.0, "MIA": 90.0}

#: ASSUMED sensitivity candidates, per station, for the settlement sweep.
#: Chosen to land in each of that station's tradable buckets (see
#: `_select_tape_instruments`) plus one reading outside every tradable bucket.
SETTLEMENT_SWEEP_CANDIDATES_F: Final[dict[str, tuple[int, ...]]] = {
    "NYC": (82, 84, 90),
    "MIA": (89, 100),
}

STRATEGY_KINDS: Final[tuple[str, ...]] = (
    "calibration_mean_reversion",
    "forecast_mispricing",
    "forecast_revision",
)

#: The unmodified baseline (a forecast published at/near tape start) and the
#: input-realism fix (see the module docstring's "TWO CONDITIONS" section).
CONDITION_NAIVE: Final[str] = "naive"
CONDITION_REALISTIC: Final[str] = "realistic"
CONDITIONS: Final[tuple[str, ...]] = (CONDITION_NAIVE, CONDITION_REALISTIC)

#: ASSUMED, fix #1. Real NWS forecasts are issued hours ahead of the trading
#: window they cover; this is comfortably inside `RiskLimits.stale_forecast_hours`
#: (8.0) and clears `CalibrationMeanReversionConfig.stable_forecast_minutes`
#: (25.0) many times over. `expected_high_f` is UNCHANGED from `naive`.
REALISTIC_PUBLISHED_AT_OFFSET_HOURS: Final[float] = 6.0

#: ASSUMED, fix #3. `forecast_revision`'s published SEQUENCE: a baseline
#: publication `REALISTIC_PUBLISHED_AT_OFFSET_HOURS` before the tape (shared
#: with fix #1), then two more inside the tape window, `REVISION_STEP_F`
#: degrees apart and same-sign (`persistence_same_sign=True`,
#: `persistence_updates=2`). Chosen to be large enough to clear
#: `min_temp_revision_f=1.5` on its own; never reverse-engineered from the
#: settlement sweep.
REVISION_PUB1_OFFSET_MINUTES: Final[float] = 1.0
REVISION_PUB2_OFFSET_MINUTES: Final[float] = 3.0
REVISION_STEP_F: Final[float] = 3.0


@dataclass(frozen=True, slots=True)
class _SequenceForecastSource:
    """ASSUMED forecast(s), injected explicitly -- see the module docstring.

    Generalizes over both conditions: a station with ONE `(published_at,
    expected_high_f)` entry behaves exactly like a constant single-snapshot
    source (`naive`, and `realistic`'s `calibration_mean_reversion` /
    `forecast_mispricing` sources); a station with several entries lets
    `forecast_revision` observe a sequence of publications as `now` advances
    past each one in turn. Never reads any settlement observation, real or
    swept -- `expected_high_f` values are supplied by the caller, always
    independently of `observed_by_station`.

    `horizon_hours` is always LIVE, computed from `now` against that station's
    real settlement deadline (`settlement_deadline_by_station`, sourced from
    the tradable instruments' own `expiration_ns`), regardless of which
    publication is currently active.
    """

    publications_by_station: dict[str, tuple[tuple[dt.datetime, float], ...]]
    settlement_deadline_by_station: dict[str, dt.datetime]

    def snapshot(
        self,
        *,
        station: str,
        climate_day: dt.date,
        now: dt.datetime,
    ) -> ForecastSnapshot | None:
        if climate_day != CLIMATE_DAY:
            return None
        publications = self.publications_by_station.get(station)
        deadline = self.settlement_deadline_by_station.get(station)
        if not publications or deadline is None:
            return None
        current = latest_publication_at_or_before(publications, now)
        if current is None:
            return None
        published_at, expected_high_f = current
        return ForecastSnapshot(
            location_id=station,
            target_date=climate_day,
            published_at=published_at,
            expected_high_f=expected_high_f,
            horizon_hours=hours_until(now, deadline),
        )


@dataclass(frozen=True, slots=True)
class TapeInstrument:
    """One tradable instrument plus the REAL data selected for it."""

    instrument: BinaryOption
    facts: WeatherBucketFacts
    depths: list[OrderBookDepth10]
    quotes: list[QuoteTick]

    @property
    def last_market_data_ts_init(self) -> int:
        return int(
            max(
                [d.ts_init for d in self.depths] + [q.ts_init for q in self.quotes],
            ),
        )


@dataclass(frozen=True, slots=True)
class FillSummary:
    side: str
    quantity: float
    avg_price: float


@dataclass(frozen=True, slots=True)
class PositionSummary:
    instrument_id: str
    is_closed: bool
    avg_px_open: float
    avg_px_close: float
    realized_pnl: float | None


@dataclass(frozen=True, slots=True)
class RunResult:
    condition: str  # CONDITION_NAIVE or CONDITION_REALISTIC
    strategy: str
    scenario: str
    provenance_by_station: dict[str, str]
    observed_by_station: dict[str, int]
    status: str  # STATUS_COMPLETED, STATUS_COMPLETED_ALL_REFUSED, or "REFUSED"
    refusal_type: str | None
    refusal_message: str | None
    orders_submitted: int
    # Per-reason counts from this run's strategy `RefusalCounter` (e.g.
    # `{"shorts_disabled": 12}`) -- see `derive_completion_status`. Empty for
    # the hard-abort "REFUSED" path, where `refusal_type`/`refusal_message`
    # already carry the reason.
    refusal_counts: dict[str, int] = field(default_factory=dict)
    fills: list[FillSummary] = field(default_factory=list)
    positions: list[PositionSummary] = field(default_factory=list)
    ending_balance_usd: float | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "condition": self.condition,
            "strategy": self.strategy,
            "scenario": self.scenario,
            "provenance_by_station": self.provenance_by_station,
            "observed_by_station": self.observed_by_station,
            "status": self.status,
            "refusal_type": self.refusal_type,
            "refusal_message": self.refusal_message,
            "orders_submitted": self.orders_submitted,
            "refusal_counts": dict(self.refusal_counts),
            "fills": [
                {"side": f.side, "quantity": f.quantity, "avg_price": f.avg_price}
                for f in self.fills
            ],
            "positions": [
                {
                    "instrument_id": p.instrument_id,
                    "is_closed": p.is_closed,
                    "avg_px_open": p.avg_px_open,
                    "avg_px_close": p.avg_px_close,
                    "realized_pnl": p.realized_pnl,
                }
                for p in self.positions
            ],
            "ending_balance_usd": self.ending_balance_usd,
        }


def _select_tape_instruments(catalog: ParquetDataCatalog) -> list[TapeInstrument]:
    """Every instrument on the tape with REAL depth AND quote coverage.

    Queries every captured instrument's depth/quote counts (I/O; not the pure
    selection rule itself -- that is
    `weather_strategy_backtest_lib.select_tradable_instrument_ids`, unit
    tested against fabricated counts) and returns only the ones that clear it.
    """
    instruments = catalog.instruments()
    depth_counts: dict[str, int] = {}
    quote_counts: dict[str, int] = {}
    depths_by_id: dict[str, list[OrderBookDepth10]] = {}
    quotes_by_id: dict[str, list[QuoteTick]] = {}
    for instrument in instruments:
        depths = catalog.order_book_depth10(instrument_ids=[instrument.id.value])
        quotes = catalog.quote_ticks(instrument_ids=[instrument.id.value])
        depth_counts[instrument.id.value] = len(depths)
        quote_counts[instrument.id.value] = len(quotes)
        depths_by_id[instrument.id.value] = depths
        quotes_by_id[instrument.id.value] = quotes

    tradable_ids = set(select_tradable_instrument_ids(depth_counts, quote_counts))
    by_id: dict[str, Instrument] = {i.id.value: i for i in instruments}

    result: list[TapeInstrument] = []
    for instrument_id in sorted(tradable_ids):
        instrument = by_id[instrument_id]
        if not isinstance(instrument, BinaryOption):
            raise TypeError(
                f"{instrument_id} is a {type(instrument).__name__}, not a "
                f"BinaryOption; every Breezy weather instrument on this venue "
                f"is a BinaryOption",
            )
        facts = read_weather_bucket_facts(instrument.info)
        result.append(
            TapeInstrument(
                instrument=instrument,
                facts=facts,
                depths=depths_by_id[instrument_id],
                quotes=quotes_by_id[instrument_id],
            ),
        )
    return result


def _synthesize_close(tape_instrument: TapeInstrument) -> InstrumentClose:
    """One CONSTRUCTED `CONTRACT_EXPIRED` close, strictly after the real tape.

    See the module docstring: the real tape carries ZERO `InstrumentClose`
    records, and `run_backtest` requires exactly one per instrument.
    `close_price` is cosmetic -- the engine settles from `settlement_prices`
    only.
    """
    ts = tape_instrument.last_market_data_ts_init + _ONE_SECOND_NS
    instrument = tape_instrument.instrument
    return InstrumentClose(
        instrument.id,
        instrument.make_price(0.5),
        InstrumentCloseType.CONTRACT_EXPIRED,
        ts,
        ts,
    )


def _load_real_observations(
    weather_catalog_root: Path,
) -> tuple[dict[str, int], dict[str, NwsClimateDay]]:
    """The REAL preliminary NYC/MIA observations for `CLIMATE_DAY`.

    Selects, per station, the non-superseded record with the highest
    `revision_seq` for `CLIMATE_DAY` -- there happens to be exactly one
    (`revision_seq=1`, `is_final=False`) for each station at the time this was
    written, but the selection rule does not assume that.

    Raises
    ------
    LookupError
        If a station has no non-superseded record for `CLIMATE_DAY` -- this
        script must not silently fall back to a fabricated reading.

    """
    observed: dict[str, int] = {}
    records: dict[str, NwsClimateDay] = {}
    for station in ("NYC", "MIA"):
        station_catalog = open_station_catalog(weather_catalog_root, WEATHER_VENUE, station)
        candidates = [
            record
            for record in read_climate_days(station_catalog)
            if record.climate_day == CLIMATE_DAY and not record.is_superseded
        ]
        if not candidates:
            raise LookupError(
                f"no non-superseded NwsClimateDay for station={station!r} "
                f"climate_day={CLIMATE_DAY.isoformat()} under {weather_catalog_root}",
            )
        best = max(candidates, key=lambda r: r.revision_seq)
        if best.tmax_f is None:
            raise LookupError(
                f"selected NwsClimateDay for {station} {CLIMATE_DAY.isoformat()} "
                f"carries no tmax_f (flagged missing/trace)",
            )
        observed[station] = best.tmax_f
        records[station] = best
    return observed, records


def _restamp_climate_day(record: NwsClimateDay, retrieved_at_ns: int) -> NwsClimateDay:
    """A copy of `record` with `retrieved_at_ns`/`ts_event` moved inside the tape window.

    See the module docstring: the real retrieval timestamp is AFTER the tape
    window ends. Every other field, including `tmax_f`, `is_final` and
    `revision_seq`, is copied verbatim.
    """
    return NwsClimateDay(
        station=record.station,
        climate_day=record.climate_day,
        tmax_f=record.tmax_f,
        tmin_f=record.tmin_f,
        tavg_f=record.tavg_f,
        tmax_flag=record.tmax_flag,
        tmin_flag=record.tmin_flag,
        tavg_flag=record.tavg_flag,
        is_final=record.is_final,
        correction_flag=record.correction_flag,
        revision_seq=record.revision_seq,
        is_superseded=record.is_superseded,
        issuing_office=record.issuing_office,
        issuance_time_ns=record.issuance_time_ns,
        retrieved_at_ns=retrieved_at_ns,
        parser_version=record.parser_version,
        registry_version=record.registry_version,
        raw_sha256=record.raw_sha256,
        source_channel=record.source_channel,
        schema_version=record.schema_version,
        ts_event=retrieved_at_ns,
    )


def _build_strategy(
    kind: str,
    instrument_ids: tuple[InstrumentId, ...],
    forecast_source: ForecastSource | None,
    **config_overrides: Any,
) -> Strategy:
    """Build one strategy of `kind`. Every field but `instrument_ids` is a
    config default UNLESS explicitly named in `config_overrides` -- see the
    module docstring's "TWO CONDITIONS" section for which run passes which
    overrides and why each one is justified on its own.

    `forecast_source` is `None` for the two OBSERVATION-kind strategies,
    `cli_settlement_print_lock` and `running_extreme_lock`, which
    structurally cannot accept a `ForecastSource`. It is mandatory for the
    three forecast-driven kinds; a `None` there is a caller bug, not a case
    to fabricate a forecast for.
    """
    if kind == "cli_settlement_print_lock":
        return CliSettlementPrintLockStrategy(
            CliSettlementPrintLockConfig(
                instrument_ids=instrument_ids,
                stale_observation_hours=STALE_OBSERVATION_HOURS_CLI_SETTLEMENT_PRINT_LOCK,
                **config_overrides,
            ),
        )
    if kind == "running_extreme_lock":
        return RunningExtremeLockStrategy(
            RunningExtremeLockConfig(
                instrument_ids=instrument_ids,
                stale_observation_hours=STALE_OBSERVATION_HOURS_RUNNING_EXTREME_LOCK,
                **config_overrides,
            ),
        )
    if forecast_source is None:
        raise ValueError(f"strategy kind {kind!r} requires a forecast_source, got None")
    if kind == "calibration_mean_reversion":
        return CalibrationMeanReversionStrategy(
            CalibrationMeanReversionConfig(instrument_ids=instrument_ids, **config_overrides),
            forecast_source,
        )
    if kind == "forecast_mispricing":
        return ForecastMispricingStrategy(
            ForecastMispricingConfig(instrument_ids=instrument_ids, **config_overrides),
            forecast_source,
        )
    if kind == "forecast_revision":
        return ForecastRevisionStrategy(
            ForecastRevisionConfig(instrument_ids=instrument_ids, **config_overrides),
            forecast_source,
        )
    raise ValueError(f"unknown strategy kind {kind!r}")


def _run_one(
    *,
    condition: str,
    strategy_kind: str,
    scenario: Scenario,
    tape_instruments: list[TapeInstrument],
    closes: list[InstrumentClose],
    weather_data: list[Any],
    forecast_source: ForecastSource | None,
    config_overrides: dict[str, Any],
) -> RunResult:
    instruments = [ti.instrument for ti in tape_instruments]
    instrument_ids = tuple(i.id for i in instruments)
    facts_by_id = {ti.instrument.id: ti.facts for ti in tape_instruments}
    settlement_prices = settlement_prices_for_scenario(
        facts_by_id,
        scenario.observed_by_station,
    )
    market_data: list[Any] = [*closes]
    for ti in tape_instruments:
        market_data.extend(ti.depths)
        market_data.extend(ti.quotes)

    config = BreezyBacktestConfig(
        instruments=instruments,
        market_data=market_data,
        weather_data=weather_data,
        settlement_prices=settlement_prices,
        starting_balances=(Money(STARTING_BALANCE_USD, USD),),
    )
    strategy = _build_strategy(
        strategy_kind, instrument_ids, forecast_source, **config_overrides,
    )

    try:
        engine = run_backtest(
            config,
            strategies=(strategy,),
            allow_idle_strategies=True,
        )
    except (
        SettlementInvariantError,
        NotVenueMarketDataError,
        UnwrappedWeatherRecordError,
        SilentRunError,
        PostOnlyRefusedError,
        NakedShortRefusedError,
    ) as exc:
        return RunResult(
            condition=condition,
            strategy=strategy_kind,
            scenario=scenario.name,
            provenance_by_station=dict(scenario.provenance_by_station),
            observed_by_station=dict(scenario.observed_by_station),
            status="REFUSED",
            refusal_type=type(exc).__name__,
            refusal_message=str(exc),
            orders_submitted=0,
        )

    try:
        orders = engine.cache.orders()
        fills = [
            FillSummary(
                side=event.order_side.name,
                quantity=float(event.last_qty),
                avg_price=float(event.last_px),
            )
            for order in orders
            for event in order.events
            if isinstance(event, OrderFilled)
        ]
        positions = [
            PositionSummary(
                instrument_id=str(position.instrument_id),
                is_closed=position.is_closed,
                avg_px_open=float(position.avg_px_open),
                avg_px_close=float(position.avg_px_close),
                realized_pnl=(
                    float(position.realized_pnl.as_decimal())
                    if position.realized_pnl is not None
                    else None
                ),
            )
            for position in engine.cache.positions()
        ]
        ending_balance: float | None = None
        account = engine.portfolio.account(instrument_ids[0].venue)
        if account is not None:
            balance = account.balance_total(USD)
            if balance is not None:
                ending_balance = float(balance.as_double())
        # Every weather strategy owns a `RefusalCounter` (`strategy.refusals`,
        # see `breezy.strategy.weather_common.refusals`) that both its
        # decision layer and `RiskManager` record into during the run just
        # completed. Read it here, before `engine.dispose()`, so a strategy
        # whose entire signal set was refused (e.g. every SHORT_YES gagged by
        # `allow_short=False`) is never indistinguishable from one that
        # simply saw no opportunity.
        refusal_counts = dict(strategy.refusals.counts)
        status = derive_completion_status(
            orders_submitted=len(orders),
            refusal_counts=refusal_counts,
        )
        return RunResult(
            condition=condition,
            strategy=strategy_kind,
            scenario=scenario.name,
            provenance_by_station=dict(scenario.provenance_by_station),
            observed_by_station=dict(scenario.observed_by_station),
            status=status,
            refusal_type=None,
            refusal_message=None,
            orders_submitted=len(orders),
            refusal_counts=refusal_counts,
            fills=fills,
            positions=positions,
            ending_balance_usd=ending_balance,
        )
    finally:
        engine.dispose()


def _fill_detail(result: RunResult) -> str:
    if not result.fills:
        return "-"
    parts = []
    for f in result.fills:
        parts.append(f"{f.side}{f.quantity:.0f}@{f.avg_price:.3f}")
    return ",".join(parts)


def _print_summary(results: list[RunResult]) -> None:
    header = (
        f"{'condition':<10} {'strategy':<28} {'scenario':<24} {'status':<10} {'orders':>6} "
        f"{'fills':>5} {'realized_pnl':>13} {'balance':>10}  fills_detail"
    )
    print(header)
    print("-" * len(header))
    for r in results:
        realized = sum(p.realized_pnl or 0.0 for p in r.positions)
        realized_str = f"{realized:+.2f}" if r.status == STATUS_COMPLETED else "n/a"
        balance_str = f"{r.ending_balance_usd:.2f}" if r.ending_balance_usd is not None else "n/a"
        if r.status == STATUS_COMPLETED:
            detail = r.status
        elif r.status == STATUS_COMPLETED_ALL_REFUSED:
            reasons = ",".join(f"{k}={v}" for k, v in sorted(r.refusal_counts.items()))
            detail = f"{r.status}:{reasons}"
        else:
            detail = f"{r.status}:{r.refusal_type}"
        print(
            f"{r.condition:<10} {r.strategy:<28} {r.scenario:<24} {detail:<10} "
            f"{r.orders_submitted:>6} {len(r.fills):>5} {realized_str:>13} "
            f"{balance_str:>10}  {_fill_detail(r)}",
        )


def _forecast_sources_and_overrides(
    *,
    tape_start_dt: dt.datetime,
    settlement_deadline_by_station: dict[str, dt.datetime],
) -> tuple[
    dict[str, ForecastSource],
    dict[str, dict[str, Any]],
]:
    """Per (condition, strategy_kind): the `ForecastSource` and config overrides.

    Keys are `f"{condition}:{strategy_kind}"`. See the module docstring's "TWO
    CONDITIONS" section for what each one is and why.
    """
    realistic_published_at = tape_start_dt - dt.timedelta(
        hours=REALISTIC_PUBLISHED_AT_OFFSET_HOURS,
    )
    stations = tuple(settlement_deadline_by_station)

    naive_source = _SequenceForecastSource(
        publications_by_station={
            station: ((tape_start_dt, ASSUMED_FORECAST_HIGH_F[station]),) for station in stations
        },
        settlement_deadline_by_station=settlement_deadline_by_station,
    )
    realistic_single_source = _SequenceForecastSource(
        publications_by_station={
            station: ((realistic_published_at, ASSUMED_FORECAST_HIGH_F[station]),)
            for station in stations
        },
        settlement_deadline_by_station=settlement_deadline_by_station,
    )
    pub1_at = tape_start_dt + dt.timedelta(minutes=REVISION_PUB1_OFFSET_MINUTES)
    pub2_at = tape_start_dt + dt.timedelta(minutes=REVISION_PUB2_OFFSET_MINUTES)
    realistic_revision_source = _SequenceForecastSource(
        publications_by_station={
            station: (
                (realistic_published_at, ASSUMED_FORECAST_HIGH_F[station]),
                (pub1_at, ASSUMED_FORECAST_HIGH_F[station] + REVISION_STEP_F),
                (pub2_at, ASSUMED_FORECAST_HIGH_F[station] + 2 * REVISION_STEP_F),
            )
            for station in stations
        },
        settlement_deadline_by_station=settlement_deadline_by_station,
    )

    sources: dict[str, ForecastSource] = {
        f"{CONDITION_NAIVE}:calibration_mean_reversion": naive_source,
        f"{CONDITION_NAIVE}:forecast_mispricing": naive_source,
        f"{CONDITION_NAIVE}:forecast_revision": naive_source,
        f"{CONDITION_REALISTIC}:calibration_mean_reversion": realistic_single_source,
        f"{CONDITION_REALISTIC}:forecast_mispricing": realistic_single_source,
        f"{CONDITION_REALISTIC}:forecast_revision": realistic_revision_source,
    }
    overrides: dict[str, dict[str, Any]] = {
        f"{CONDITION_NAIVE}:calibration_mean_reversion": {},
        f"{CONDITION_NAIVE}:forecast_mispricing": {},
        f"{CONDITION_NAIVE}:forecast_revision": {},
        f"{CONDITION_REALISTIC}:calibration_mean_reversion": {},
        f"{CONDITION_REALISTIC}:forecast_mispricing": {
            "allow_short": False,
            "use_limit_orders": False,
        },
        f"{CONDITION_REALISTIC}:forecast_revision": {},
    }
    print(
        f"ASSUMED forecast, {CONDITION_NAIVE} condition (fixed, published_at="
        f"{tape_start_dt.isoformat()}): {ASSUMED_FORECAST_HIGH_F}",
    )
    print(
        f"ASSUMED forecast, {CONDITION_REALISTIC} condition, single-snapshot "
        f"(calibration_mean_reversion, forecast_mispricing), published_at="
        f"{realistic_published_at.isoformat()} "
        f"({REALISTIC_PUBLISHED_AT_OFFSET_HOURS}h before tape start): "
        f"{ASSUMED_FORECAST_HIGH_F}",
    )
    print(
        f"ASSUMED forecast, {CONDITION_REALISTIC} condition, PUBLISHED SEQUENCE "
        f"(forecast_revision): "
        + "; ".join(
            f"{station}: "
            + " -> ".join(
                f"{p[1]:.1f}F@{p[0].isoformat()}"
                for p in realistic_revision_source.publications_by_station[station]
            )
            for station in stations
        ),
    )
    print(
        f"CONFIG OVERRIDE, {CONDITION_REALISTIC} condition, forecast_mispricing: "
        f"{overrides[f'{CONDITION_REALISTIC}:forecast_mispricing']} "
        f"(venue holds no inventory at run start, so SHORT_YES is unreachable "
        f"on this CLOB for a first move; BacktestOrderGuard is unchanged)",
    )
    return sources, overrides


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quote-catalog", type=Path, default=DEFAULT_QUOTE_CATALOG_PATH)
    parser.add_argument("--weather-catalog-root", type=Path, default=DEFAULT_WEATHER_CATALOG_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    catalog = ParquetDataCatalog(str(args.quote_catalog))
    tape_instruments = _select_tape_instruments(catalog)
    if not tape_instruments:
        print("REFUSAL: no instrument on the tape carries both depth and quote data.")
        return 1
    print(f"REAL: {len(tape_instruments)} tradable instruments selected from the tape:")
    for ti in tape_instruments:
        print(
            f"  {ti.instrument.id.value}: {len(ti.depths)} depth rows, "
            f"{len(ti.quotes)} quote rows, station={ti.facts.settlement_station}",
        )

    real_observed, real_records = _load_real_observations(args.weather_catalog_root)
    print(f"REAL preliminary observations for {CLIMATE_DAY.isoformat()}: {real_observed}")

    tape_start_ns = min(ti.last_market_data_ts_init for ti in tape_instruments)
    tape_start_ns = min(
        tape_start_ns,
        min(d.ts_init for ti in tape_instruments for d in ti.depths),
    )
    tape_start_dt = dt.datetime.fromtimestamp(tape_start_ns / 1_000_000_000, tz=dt.UTC)
    restamped_ns = tape_start_ns - _ONE_SECOND_NS
    for station, record in real_records.items():
        print(
            f"CONSTRUCTED: restamping {station} NwsClimateDay retrieved_at_ns "
            f"{record.retrieved_at_ns} -> {restamped_ns} (real value fell outside "
            f"the tape window; tmax_f/is_final/revision_seq unchanged)",
        )
    weather_data = as_backtest_data(
        [_restamp_climate_day(record, restamped_ns) for record in real_records.values()],
    )

    closes = [_synthesize_close(ti) for ti in tape_instruments]
    print(f"CONSTRUCTED: synthesized {len(closes)} CONTRACT_EXPIRED closes (one per instrument).")

    stations = {ti.facts.settlement_station for ti in tape_instruments}
    settlement_deadline_by_station = {
        station: dt.datetime.fromtimestamp(
            next(
                ti.instrument.expiration_ns
                for ti in tape_instruments
                if ti.facts.settlement_station == station
            )
            / 1_000_000_000,
            tz=dt.UTC,
        )
        for station in stations
    }
    forecast_sources, config_overrides = _forecast_sources_and_overrides(
        tape_start_dt=tape_start_dt,
        settlement_deadline_by_station=settlement_deadline_by_station,
    )

    scenarios = build_settlement_scenarios(
        real_observed_by_station=real_observed,
        sweep_by_station=SETTLEMENT_SWEEP_CANDIDATES_F,
    )
    print(f"Settlement scenarios ({len(scenarios)}): {[s.name for s in scenarios]}")

    results: list[RunResult] = []
    for condition in CONDITIONS:
        for strategy_kind in STRATEGY_KINDS:
            key = f"{condition}:{strategy_kind}"
            for scenario in scenarios:
                result = _run_one(
                    condition=condition,
                    strategy_kind=strategy_kind,
                    scenario=scenario,
                    tape_instruments=tape_instruments,
                    closes=closes,
                    weather_data=weather_data,
                    forecast_source=forecast_sources[key],
                    config_overrides=config_overrides[key],
                )
                results.append(result)
                print(
                    f"ran condition={condition} strategy={strategy_kind} "
                    f"scenario={scenario.name} status={result.status} "
                    f"orders={result.orders_submitted} fills={len(result.fills)}"
                    + (f" refusal={result.refusal_type}: {result.refusal_message}"
                       if result.status == "REFUSED" else ""),
                )

    print()
    for condition in CONDITIONS:
        print(f"=== {condition} condition ===")
        _print_summary([r for r in results if r.condition == condition])
        print()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.now(tz=dt.UTC).strftime("%Y%m%dT%H%M%S%z")
    output_path = args.output_dir / f"weather_strategy_backtests_{timestamp}.json"
    output_path.write_text(
        json.dumps(
            {
                "generated_at_utc": dt.datetime.now(tz=dt.UTC).isoformat(),
                "quote_catalog": str(args.quote_catalog),
                "weather_catalog_root": str(args.weather_catalog_root),
                "real_observed_by_station": real_observed,
                "assumed_forecast_high_f_by_station": ASSUMED_FORECAST_HIGH_F,
                "realistic_published_at_offset_hours": REALISTIC_PUBLISHED_AT_OFFSET_HOURS,
                "revision_sequence_step_f": REVISION_STEP_F,
                "tradable_instrument_ids": [ti.instrument.id.value for ti in tape_instruments],
                "scenarios": [
                    {
                        "name": s.name,
                        "observed_by_station": dict(s.observed_by_station),
                        "provenance_by_station": dict(s.provenance_by_station),
                    }
                    for s in scenarios
                ],
                "results": [r.to_json() for r in results],
            },
            indent=2,
            sort_keys=True,
        ),
    )
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
