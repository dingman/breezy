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
    (`docs/plans/archive/FORECAST_INGESTION_PLAN.md` is unbuilt).
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
from collections.abc import Iterable, Mapping, Sequence
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
    GATE_NO_QUOTE,
    PROVENANCE_REAL,
    STATUS_COMPLETED,
    STATUS_COMPLETED_ALL_REFUSED,
    PrintLockGateRecord,
    Scenario,
    build_settlement_scenarios,
    derive_completion_status,
    first_blocking_gate,
    hours_from_now_until,
    latest_publication_at_or_before,
    select_book_backed_instrument_ids,
    select_tradable_instrument_ids,
    settlement_prices_for_scenario,
)

from breezy.adapters.polymarket_us.errors import FeeScheduleUnknownError

# DELIBERATE private-name import -- see `PolymarketUSFeeCoefficients` below for
# why the public promotion could not be made in this change.
from breezy.adapters.polymarket_us.fees import _fee_coefficient
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
from breezy.strategy.cli_settlement_print_lock import (
    CliSettlementPrintLockConfig,
    CliSettlementPrintLockStrategy,
)
from breezy.strategy.cli_settlement_print_lock.decision import CliPrintObservation
from breezy.strategy.depth10 import market_quote_from_depth
from breezy.strategy.forecast_mispricing import ForecastMispricingConfig, ForecastMispricingStrategy
from breezy.strategy.forecast_revision import ForecastRevisionConfig, ForecastRevisionStrategy
from breezy.strategy.running_extreme_lock import (
    RunningExtremeLockConfig,
    RunningExtremeLockStrategy,
)
from breezy.strategy.weather_common.bucket_contract import MispricingContract
from breezy.strategy.weather_common.costs import (
    FeeCoefficientSource,
    UnknownFeeScheduleError,
)
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

#: `CliSettlementPrintLockConfig.slippage_prob` has no shipped default either,
#: and for the same reason: it is the ONLY writable cost input, so an implicit
#: value would be an unowned economic assumption. The venue fee is NOT here --
#: it is `theta * p * (1 - p)` read per instrument from the market's own
#: `feeCoefficient` through `PolymarketUSFeeCoefficients`, and it is not
#: configurable at all.
#:
#: The value is UNMEASURED. 0.01 is ONE TICK on this venue's 0.01 grid -- the
#: smallest representable adverse price move -- and is a placeholder, not a
#: measurement (`docs/evidence/bl19_edge_and_cost_decision_2026-09-01.md` s2,
#: s8.2, s8.6). Say plainly what it decides: at ask 0.99 the edge after FEE
#: ALONE is +0.006302 and clears the 0.005 floor; only this placeholder pushes
#: it to -0.003698. So the single number deciding whether print-lock may pay
#: 0.99 is a figure nobody has measured. s8.5's per-station-day record exists
#: to replace it -- `SignalDecision.metadata` carries `fee_coefficient`,
#: `fee_prob` and `slippage_prob` precisely so the threshold is re-derivable
#: OFFLINE from a recorded tape, without re-running the capture.
#:
#: It is floored at the instrument's own `price_increment` in `on_start`
#: (`UnpricedInstrumentError`). A floor of ZERO would restore the exact unsafe
#: configuration the structured cost term exists to forbid, so if realised
#: fills show slippage below one tick the floor is RE-DERIVED, never removed.
#: A BUILD-side decision, not an operator-reserved control.
SLIPPAGE_PROB_CLI_SETTLEMENT_PRINT_LOCK: Final[float] = 0.01

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


class PolymarketUSFeeCoefficients:
    """A `FeeCoefficientSource` backed by already-parsed Polymarket.us markets.

    WHY THIS LIVES IN THIS SCRIPT AND NOT IN `src/breezy/`
    ------------------------------------------------------
    It must reach BOTH `breezy.adapters.polymarket_us` (for the validated
    coefficient read) and `breezy.strategy.weather_common.costs` (for the
    error type the strategy layer catches). Under `pyproject.toml`'s layers
    contract -- `strategy` > `runtime` > `adapters`, `exhaustive = true` --
    the only module inside `breezy` that may import both is one in the
    `strategy` layer, and putting it there would weld a strategy package to
    one venue, against Breezy's portability priority. A `runtime` home fails
    `lint-imports` outright ("breezy.runtime is not allowed to import
    breezy.strategy").

    So it lives at the construction site, which is EXACTLY the precedent
    `_SequenceForecastSource` below already sets for the identical problem:
    the injected Protocol is venue-neutral and lives in `weather_common`, the
    concrete implementation lives with the wiring. See the
    "DEVIATION FROM THE PLAN" note in the module docstring of
    `breezy.strategy.weather_common.costs`'s consumer.

    NAUTILUS NULL HYPOTHESIS (L-1). Nautilus exposes no API that resolves a
    market's fee COEFFICIENT for a contemplated price. `Instrument.taker_fee`
    is a flat notional rate (`adapters.polymarket_us.fees` documents its
    unbounded relative error as `p -> 1`), and `FeeModel.get_commission`
    (`backtest/models/fee.pyx:38`) prices an ALREADY-FILLED order and returns
    `Money`. The gap is real.

    REFUSE, NEVER DEFAULT. The read is DELEGATED to the adapter's own
    already-validated `_fee_coefficient` rather than re-implemented, so the
    gate-time resolution and the settlement-time authority cannot diverge on
    what counts as usable: it checks the status marker (barrier F1) and then
    re-validates the value -- absence, `bool` round-trip, undecodable text,
    and the `[0, 1]` range -- because the marker lives in a loosely-typed
    `info` dict and must never on its own license a computation. Every failure
    becomes `UnknownFeeScheduleError`, so the strategy layer never catches an
    adapter-specific type.

    (`_fee_coefficient` is module-private. The design asks for it to be
    PROMOTED to a public `read_fee_coefficient`; that rename could not be made
    because `src/breezy/adapters/polymarket_us/` was under concurrent edit and
    read-only for this change. The design's stated fallback -- duplicating the
    ~25 lines of validation -- is worse: a DRY violation on a fail-closed
    path, with two places for the rule to rot. Re-point this one line when the
    adapter is writable again.)
    """

    def __init__(self, instruments: Mapping[str, Instrument]) -> None:
        # Copied, not aliased: a source that silently gained or lost markets
        # after construction would make the once-at-`on_start` resolution a
        # lie about what was actually read.
        self._instruments: dict[str, Instrument] = dict(instruments)

    def fee_coefficient_for(self, instrument_id: str) -> float:
        """Return this market's `theta`, or raise. Never returns a default."""
        instrument = self._instruments.get(instrument_id)
        if instrument is None:
            raise UnknownFeeScheduleError(
                f"No Polymarket.us instrument held for {instrument_id!r}, so its fee "
                "schedule is unknown. An unheld market is 'we do not know', never "
                "'free' -- refusing rather than pricing a trade at zero.",
            )
        try:
            return float(_fee_coefficient(instrument))
        except FeeScheduleUnknownError as exc:
            raise UnknownFeeScheduleError(
                f"Refusing to price {instrument_id!r}: {exc}",
            ) from exc


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
            horizon_hours=hours_from_now_until(now, deadline),
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
    #: The account the engine was FUNDED with for this run. Emitted per row so
    #: a reader can always reconstruct the denominator of
    #: `return_on_starting_balance_pct` without going back to the manifest --
    #: see the two-denominator note below.
    starting_balance_usd: float = float(STARTING_BALANCE_USD)

    @property
    def realized_pnl_usd(self) -> float:
        """Realised PnL summed across this run's positions, in dollars."""
        return sum(p.realized_pnl or 0.0 for p in self.positions)

    @property
    def capital_deployed_usd(self) -> float:
        """Cash actually PUT AT RISK: the buy-side cost basis of every fill.

        For a long-only taker in a 0/1 binary this is the entire downside --
        premium paid is the whole of what can be lost. A SELL returns cash and
        is therefore not additional capital deployed, so it is excluded rather
        than summed as `abs(notional)`.

        `0.0` for a run that never filled, which is honestly "no capital was
        deployed", not "a zero return".
        """
        return sum(f.quantity * f.avg_price for f in self.fills if f.side == "BUY")

    @property
    def return_on_starting_balance_pct(self) -> float | None:
        """PnL against the CONFIGURED account balance.

        Kept because it is the figure every prior run reported and removing it
        would break comparison with them -- but it is NOT a return on the
        capital this strategy risked: `STARTING_BALANCE_USD` is a harness
        setting, and the strategy's own cost-basis anchor deploys ~$24.53 of
        it. Read it beside `return_on_capital_deployed_pct`, never alone.
        """
        if self.starting_balance_usd <= 0.0:
            return None
        return 100.0 * self.realized_pnl_usd / self.starting_balance_usd

    @property
    def return_on_capital_deployed_pct(self) -> float | None:
        """PnL against the capital actually deployed -- the honest denominator.

        BL-25 D3. A -$5.41 result is -0.054% of a $10,000 configured balance
        and roughly -20% of the ~$24.53 the strategy actually put at risk.
        Return-on-configured-balance is not a return; it is a statement about
        how the harness was funded.

        `None` -- never 0.0, never a zero-division -- when nothing was
        deployed. A run with no fills has no return to report, and reporting
        one would be fabricating a number.
        """
        deployed = self.capital_deployed_usd
        if deployed <= 0.0:
            return None
        return 100.0 * self.realized_pnl_usd / deployed

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
            # BOTH denominators, unambiguously labelled, plus the input each
            # one is computed from -- so no reader ever has to guess which
            # base a percentage is against (BL-25 D3).
            "starting_balance_usd": self.starting_balance_usd,
            "realized_pnl_usd": self.realized_pnl_usd,
            "capital_deployed_usd": self.capital_deployed_usd,
            "return_on_starting_balance_pct": self.return_on_starting_balance_pct,
            "return_on_capital_deployed_pct": self.return_on_capital_deployed_pct,
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
    fee_coefficients: FeeCoefficientSource | None = None,
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

    `fee_coefficients` is mandatory for `cli_settlement_print_lock`, the one
    strategy that nets its edge against the venue's own per-market fee rather
    than a scalar. A `None` there is a caller bug too -- there is deliberately
    no default coefficient anywhere in the system, because a default is how a
    market whose schedule nobody read gets traded as though it were free.
    """
    if kind == "cli_settlement_print_lock":
        if fee_coefficients is None:
            raise ValueError(
                f"strategy kind {kind!r} requires a fee_coefficients source, got None",
            )
        return CliSettlementPrintLockStrategy(
            CliSettlementPrintLockConfig(
                instrument_ids=instrument_ids,
                stale_observation_hours=STALE_OBSERVATION_HOURS_CLI_SETTLEMENT_PRINT_LOCK,
                slippage_prob=SLIPPAGE_PROB_CLI_SETTLEMENT_PRINT_LOCK,
                **config_overrides,
            ),
            fee_coefficients,
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
    log_level: str = "WARNING",
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
        log_level=log_level,
    )
    strategy = _build_strategy(
        strategy_kind,
        instrument_ids,
        forecast_source,
        PolymarketUSFeeCoefficients({str(i.id): i for i in instruments}),
        **config_overrides,
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


def _summary_lines(results: list[RunResult]) -> list[str]:
    """The summary table, as lines, so its content is testable.

    TWO RETURN COLUMNS, BOTH LABELLED (BL-25 D3). `ret_bal%` is PnL over the
    CONFIGURED starting balance -- the figure prior runs reported, kept so
    they stay comparable. `ret_cap%` is PnL over the capital actually
    deployed, which is the only one of the two that is a return. `cap_usd`
    carries the denominator itself so neither percentage is a black box.
    """
    header = (
        f"{'condition':<10} {'strategy':<28} {'scenario':<24} {'status':<10} {'orders':>6} "
        f"{'fills':>5} {'realized_pnl':>13} {'balance':>10} {'cap_usd':>9} "
        f"{'ret_bal%':>9} {'ret_cap%':>9}  fills_detail"
    )
    lines = [header, "-" * len(header)]
    for r in results:
        completed = r.status == STATUS_COMPLETED
        realized_str = f"{r.realized_pnl_usd:+.2f}" if completed else "n/a"
        balance_str = f"{r.ending_balance_usd:.2f}" if r.ending_balance_usd is not None else "n/a"
        deployed = r.capital_deployed_usd
        cap_str = f"{deployed:.2f}" if completed and deployed > 0.0 else "n/a"
        ret_bal = r.return_on_starting_balance_pct
        ret_cap = r.return_on_capital_deployed_pct
        ret_bal_str = f"{ret_bal:+.4f}" if completed and ret_bal is not None else "n/a"
        ret_cap_str = f"{ret_cap:+.2f}" if completed and ret_cap is not None else "n/a"
        if completed:
            detail = r.status
        elif r.status == STATUS_COMPLETED_ALL_REFUSED:
            reasons = ",".join(f"{k}={v}" for k, v in sorted(r.refusal_counts.items()))
            detail = f"{r.status}:{reasons}"
        else:
            detail = f"{r.status}:{r.refusal_type}"
        lines.append(
            f"{r.condition:<10} {r.strategy:<28} {r.scenario:<24} {detail:<10} "
            f"{r.orders_submitted:>6} {len(r.fills):>5} {realized_str:>13} "
            f"{balance_str:>10} {cap_str:>9} {ret_bal_str:>9} {ret_cap_str:>9}  "
            f"{_fill_detail(r)}",
        )
    return lines


def _print_summary(results: list[RunResult]) -> None:
    for line in _summary_lines(results):
        print(line)


def _partition_supported_stations(
    stations: Iterable[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split ``stations`` into (supported, excluded) against `ASSUMED_FORECAST_HIGH_F`.

    "Supported" means this script has a constructed forecast input (and, for
    the legacy tape path, a REAL preliminary observation -- both are keyed to
    the same NYC/MIA constants) for that station. A station the tape grows to
    cover with neither must be excluded, never silently defaulted -- see
    LESSONS L-17/L-12.
    """
    ordered = tuple(dict.fromkeys(stations))
    supported = tuple(s for s in ordered if s in ASSUMED_FORECAST_HIGH_F)
    excluded = tuple(s for s in ordered if s not in ASSUMED_FORECAST_HIGH_F)
    return supported, excluded


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
    stations, excluded_stations = _partition_supported_stations(settlement_deadline_by_station)
    if excluded_stations:
        print(
            f"EXCLUDED from the constructed-forecast condition: {excluded_stations}; "
            f"no constructed forecast input for {excluded_stations} (see "
            f"ASSUMED_FORECAST_HIGH_F) -- not fabricated, so these stations get no "
            f"forecast signal in this run rather than a silently-defaulted one.",
        )

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


# ---------------------------------------------------------------------------
# LIVE-CAPTURE MODE (`--tape-instance-id`)
# ---------------------------------------------------------------------------
#
# The default (`legacy`) path above reads the quote catalog's already-converted
# `data/` partition, which holds the 2026-08-30 tape. A live recorder run is
# staged somewhere else entirely: `<catalog_root>/live/<instance_id>/`, in
# FEATHER, and the only sanctioned way to read it back is the native
# `ParquetDataCatalog.convert_stream_to_data(instance_id, T,
# subdirectory="live")` (`persistence/catalog/parquet.py:2604`;
# `runtime/quote_tape_cli` documents exactly this call). This section is that
# wiring and nothing more -- no strategy change, no shipped constant change.
#
# NULL HYPOTHESIS (checked before any of it was written):
#   * The feather -> parquet conversion is NATIVE. `convert_stream_to_data` is
#     used verbatim; nothing here parses a feather file.
#   * Reading instruments/depth/quotes back is NATIVE: `catalog.instruments()`,
#     `catalog.order_book_depth10()`, `catalog.quote_ticks()`.
#   * Backtest replay of the weather custom type is NATIVE: `add_data(...,
#     client_id=...)` through `breezy.runtime.backtest_harness`.
# What is genuinely absent, and therefore authored here: the CHOICE of target
# catalog (the capture root is read-only evidence, so every converted row goes
# to a SEPARATE work root), the climate-day filter, and the s8.5 record.


def _convert_live_capture(
    *,
    quote_catalog: Path,
    instance_id: str,
    subdirectory: str,
    work_catalog: Path,
) -> ParquetDataCatalog:
    """Convert one live-recorder run into a SEPARATE work catalog, natively.

    `other_catalog` is mandatory here, not incidental: the capture root is
    evidence and is never written to. `convert_stream_to_data` writes parquet
    into whichever catalog it is handed, and it SKIPS (with a bare `print`, no
    exception -- `parquet.py:2680`) any file whose computed name already
    exists, so a re-run against a populated work root is a silent partial
    no-op. The work root is therefore required to be empty or absent.
    """
    if work_catalog.resolve() == quote_catalog.resolve() or quote_catalog.resolve() in (
        work_catalog.resolve().parents
    ):
        raise ValueError(
            f"--work-catalog {work_catalog} is inside the capture root {quote_catalog}. "
            "The capture is read-only evidence; converted rows must go somewhere else.",
        )
    if work_catalog.exists() and any(work_catalog.iterdir()):
        raise ValueError(
            f"--work-catalog {work_catalog} is not empty. `convert_stream_to_data` "
            "silently SKIPS a write whose filename already exists (parquet.py:2680, a "
            "bare print), so converting into a populated root can produce a partial "
            "tape with no error. Point it at a fresh directory.",
        )
    work_catalog.mkdir(parents=True, exist_ok=True)
    source = ParquetDataCatalog(str(quote_catalog))
    work = ParquetDataCatalog(str(work_catalog))
    for data_cls in (BinaryOption, InstrumentClose, QuoteTick, OrderBookDepth10):
        source.convert_stream_to_data(
            instance_id,
            data_cls,
            other_catalog=work,
            subdirectory=subdirectory,
        )
    return work


def _select_capture_instruments(
    catalog: ParquetDataCatalog,
    *,
    climate_day: dt.date,
) -> list[TapeInstrument]:
    """Every captured instrument for `climate_day` that carries ORDER-BOOK depth.

    Depth-only, via `select_book_backed_instrument_ids` -- see that function
    for why the quote-AND-depth rule is the wrong one for an asks-only book,
    and why relaxing it here is not a relaxation of anything the forecast
    strategies rely on.

    `catalog.instruments()` returns one row per RECORDED definition, and the
    recorder re-publishes definitions on every discovery cycle, so the same
    `InstrumentId` appears many times. De-duplicated on `id`, keeping the
    first, so an instrument is counted once.
    """
    by_id: dict[str, Instrument] = {}
    for instrument in catalog.instruments():
        by_id.setdefault(instrument.id.value, instrument)

    facts_by_id: dict[str, WeatherBucketFacts] = {}
    for instrument_id, instrument in by_id.items():
        facts = read_weather_bucket_facts(instrument.info)
        if facts.climate_day == climate_day:
            facts_by_id[instrument_id] = facts

    depth_counts: dict[str, int] = {}
    depths_by_id: dict[str, list[OrderBookDepth10]] = {}
    quotes_by_id: dict[str, list[QuoteTick]] = {}
    for instrument_id in facts_by_id:
        depths = catalog.order_book_depth10(instrument_ids=[instrument_id])
        depths_by_id[instrument_id] = depths
        depth_counts[instrument_id] = len(depths)
        quotes_by_id[instrument_id] = catalog.quote_ticks(instrument_ids=[instrument_id])

    result: list[TapeInstrument] = []
    for instrument_id in select_book_backed_instrument_ids(depth_counts):
        instrument = by_id[instrument_id]
        if not isinstance(instrument, BinaryOption):
            raise TypeError(
                f"{instrument_id} is a {type(instrument).__name__}, not a BinaryOption",
            )
        result.append(
            TapeInstrument(
                instrument=instrument,
                facts=facts_by_id[instrument_id],
                depths=depths_by_id[instrument_id],
                quotes=quotes_by_id[instrument_id],
            ),
        )
    return result


def _load_climate_day_records(
    weather_catalog_root: Path,
    *,
    stations: Sequence[str],
    climate_day: dt.date,
) -> list[NwsClimateDay]:
    """Every non-superseded `NwsClimateDay` for `climate_day`, at its REAL ts_init.

    NOT restamped. The legacy path restamps because its real retrieval
    timestamps fall OUTSIDE the tape window; on a live capture that spans the
    morning final prints they fall INSIDE it, so the honest wiring is to feed
    them exactly where they landed. Sorted by `ts_init` for readability only
    -- `BacktestEngine.add_data` sorts by `ts_init` itself
    (`backtest/engine.pyx:903`), and `ts_event` is never read on the replay
    path.
    """
    records: list[NwsClimateDay] = []
    for station in stations:
        station_catalog = open_station_catalog(weather_catalog_root, WEATHER_VENUE, station)
        records.extend(
            record
            for record in read_climate_days(station_catalog)
            if record.climate_day == climate_day and not record.is_superseded
        )
    return sorted(records, key=lambda r: r.ts_init)


def _settled_readings(records: Sequence[NwsClimateDay]) -> dict[str, int]:
    """Per station, the highest-`revision_seq` FINAL print's `tmax_f`.

    This is the SETTLEMENT truth for the run: the venue settles weather
    contracts on the NWS Daily Climate Report, and only the final issuance is
    settlement-grade (`nws-cli-settlement`). Raises rather than guessing.
    """
    best: dict[str, NwsClimateDay] = {}
    for record in records:
        if not record.is_final:
            continue
        current = best.get(record.station)
        if current is None or record.revision_seq > current.revision_seq:
            best[record.station] = record
    readings: dict[str, int] = {}
    for station, record in best.items():
        if record.tmax_f is None:
            raise LookupError(
                f"{station} {record.climate_day.isoformat()} final print carries no "
                f"tmax_f (flagged missing/trace); refusing to fabricate a settlement",
            )
        readings[station] = record.tmax_f
    return readings


def _print_lock_gate_records(
    *,
    tape_instruments: Sequence[TapeInstrument],
    records: Sequence[NwsClimateDay],
    fee_coefficients: FeeCoefficientSource,
    cfg: CliSettlementPrintLockConfig,
) -> list[PrintLockGateRecord]:
    """One BL-19 s8.5 decision-input record per (instrument, CLI print).

    Written REGARDLESS of whether an order forms, because two of the four
    nulls s8.5 enumerates are invisible at the `RefusalCounter`. Computes NO
    trading result -- see `first_blocking_gate`.

    The decision instant is the print's own `ts_init` (when the record reached
    the strategy), and the book is the last depth snapshot at or before that
    instant -- exactly the state `CliSettlementPrintLockStrategy.on_data`
    evaluates against (`self._quotes[iid]` is whatever was last cached).
    """
    out: list[PrintLockGateRecord] = []
    for tape_instrument in tape_instruments:
        instrument = tape_instrument.instrument
        instrument_id = instrument.id.value
        theta: float | None
        try:
            theta = fee_coefficients.fee_coefficient_for(instrument_id)
        except UnknownFeeScheduleError:
            theta = None
        contract = MispricingContract(
            instrument_id=instrument_id,
            facts=tape_instrument.facts,
            tick_size=float(instrument.price_increment),
            price_scale=1.0,
            fee_coefficient=theta,
        )
        deadline = dt.datetime.fromtimestamp(
            instrument.expiration_ns / 1_000_000_000, tz=dt.UTC,
        )
        depths = sorted(tape_instrument.depths, key=lambda d: d.ts_init)
        for record in records:
            if not tape_instrument.facts.applies_to(record.station, record.climate_day):
                continue
            now = dt.datetime.fromtimestamp(record.ts_init / 1_000_000_000, tz=dt.UTC)
            latest = None
            for depth in depths:
                if depth.ts_init <= record.ts_init:
                    latest = depth
                else:
                    break
            quote = market_quote_from_depth(latest, include_ask_ladder=True) if latest else None
            observation = CliPrintObservation(
                station=record.station,
                climate_day=record.climate_day,
                tmax_f=record.tmax_f,
                tmin_f=record.tmin_f,
                is_final=record.is_final,
                correction_flag=record.correction_flag,
                is_superseded=record.is_superseded,
                published_at=dt.datetime.fromtimestamp(
                    record.issuance_time_ns / 1_000_000_000, tz=dt.UTC,
                ),
            )
            if quote is None:
                out.append(
                    _no_quote_record(
                        contract=contract,
                        observation=observation,
                        now=now,
                        deadline=deadline,
                        cfg=cfg,
                    ),
                )
                continue
            out.append(
                first_blocking_gate(
                    contract=contract,
                    quote=quote,
                    observation=observation,
                    now=now,
                    deadline=deadline,
                    cfg=cfg,
                ),
            )
    return out


def _no_quote_record(
    *,
    contract: MispricingContract,
    observation: CliPrintObservation,
    now: dt.datetime,
    deadline: dt.datetime,
    cfg: CliSettlementPrintLockConfig,
) -> PrintLockGateRecord:
    """The s8.5 record for "the strategy had no cached book at print time" (N0)."""
    return PrintLockGateRecord(
        instrument_id=contract.instrument_id,
        station=contract.facts.settlement_station,
        climate_day=contract.facts.climate_day,
        deadline=deadline,
        decided_at=now,
        cli_issued_at=observation.published_at,
        hours_to_settlement=(deadline - now).total_seconds() / 3600.0,
        printed_f=observation.tmax_f,
        is_final=observation.is_final,
        correction_flag=observation.correction_flag,
        is_superseded=observation.is_superseded,
        bucket_lower_f=contract.facts.lower_f,
        bucket_upper_f=contract.facts.upper_f,
        bucket_contains_print=None,
        level0_ask=None,
        level0_ask_size=None,
        vwap_ask=None,
        vwap_ask_filled_qty=None,
        fee_coefficient=contract.fee_coefficient,
        fee_prob=None,
        slippage_prob=cfg.slippage_prob,
        model_probability=None,
        edge=None,
        edge_at_zero_slippage=None,
        quote_age_minutes=None,
        gate=GATE_NO_QUOTE,
        decision_formed=False,
        counted_by_refusal_counter=False,
    )


def _run_live_capture(args: argparse.Namespace) -> int:
    """The live-capture run: one climate day, real prints, real settlement."""
    climate_day = dt.date.fromisoformat(args.climate_day)
    stations = tuple(s.strip().upper() for s in args.stations.split(",") if s.strip())
    strategy_kinds = tuple(k.strip() for k in args.strategies.split(",") if k.strip())

    print(f"LIVE CAPTURE instance={args.tape_instance_id} subdirectory={args.tape_subdirectory}")
    catalog = _convert_live_capture(
        quote_catalog=args.quote_catalog,
        instance_id=args.tape_instance_id,
        subdirectory=args.tape_subdirectory,
        work_catalog=args.work_catalog,
    )
    tape_instruments = _select_capture_instruments(catalog, climate_day=climate_day)
    if not tape_instruments:
        print(
            f"REFUSAL: no captured instrument for climate_day={climate_day.isoformat()} "
            f"carries order-book depth.",
        )
        return 1
    print(
        f"REAL: {len(tape_instruments)} book-backed instruments for "
        f"climate_day={climate_day.isoformat()}:",
    )
    for ti in tape_instruments:
        print(
            f"  {ti.instrument.id.value}: {len(ti.depths)} depth rows, "
            f"{len(ti.quotes)} quote rows, station={ti.facts.settlement_station}, "
            f"bucket=[{ti.facts.lower_f}, {ti.facts.upper_f}], "
            f"endDate={dt.datetime.fromtimestamp(ti.instrument.expiration_ns / 1e9, tz=dt.UTC)}",
        )

    records = _load_climate_day_records(
        args.weather_catalog_root, stations=stations, climate_day=climate_day,
    )
    print(f"REAL: {len(records)} non-superseded NwsClimateDay records, at their REAL ts_init:")
    for record in records:
        print(
            f"  {record.station} {record.climate_day.isoformat()} tmax_f={record.tmax_f} "
            f"is_final={record.is_final} rev={record.revision_seq} "
            f"corr={record.correction_flag} "
            f"issued={dt.datetime.fromtimestamp(record.issuance_time_ns / 1e9, tz=dt.UTC)} "
            f"ts_init={dt.datetime.fromtimestamp(record.ts_init / 1e9, tz=dt.UTC)}",
        )

    observed = _settled_readings(records)
    print(f"REAL settlement readings (highest-revision FINAL print per station): {observed}")
    missing = sorted({ti.facts.settlement_station for ti in tape_instruments} - set(observed))
    if missing:
        print(
            f"REFUSAL: no FINAL print for station(s) {missing}; settlement price would have "
            f"to be fabricated. Refusing rather than assuming an outcome.",
        )
        return 1

    weather_data = as_backtest_data(list(records))
    closes = [_synthesize_close(ti) for ti in tape_instruments]
    print(
        f"CONSTRUCTED: {len(closes)} CONTRACT_EXPIRED closes (the tape carries ZERO; "
        f"verified via catalog.instrument_closes()).",
    )

    scenario = Scenario(
        name="real_final_print",
        observed_by_station=observed,
        provenance_by_station={station: PROVENANCE_REAL for station in observed},
    )

    instruments = [ti.instrument for ti in tape_instruments]
    fee_source = PolymarketUSFeeCoefficients({str(i.id): i for i in instruments})
    gate_cfg = CliSettlementPrintLockConfig(
        instrument_ids=tuple(i.id for i in instruments),
        stale_observation_hours=STALE_OBSERVATION_HOURS_CLI_SETTLEMENT_PRINT_LOCK,
        slippage_prob=SLIPPAGE_PROB_CLI_SETTLEMENT_PRINT_LOCK,
    )
    gate_records = _print_lock_gate_records(
        tape_instruments=tape_instruments,
        records=records,
        fee_coefficients=fee_source,
        cfg=gate_cfg,
    )

    results: list[RunResult] = []
    for strategy_kind in strategy_kinds:
        result = _run_one(
            condition="live_capture",
            strategy_kind=strategy_kind,
            scenario=scenario,
            tape_instruments=tape_instruments,
            closes=closes,
            weather_data=weather_data,
            forecast_source=None,
            config_overrides={},
            log_level=args.log_level,
        )
        results.append(result)
        print(
            f"ran strategy={strategy_kind} scenario={scenario.name} status={result.status} "
            f"orders={result.orders_submitted} fills={len(result.fills)}"
            + (
                f" refusal={result.refusal_type}: {result.refusal_message}"
                if result.status == "REFUSED"
                else ""
            ),
        )

    print()
    _print_summary(results)
    print()
    print("=== BL-19 s8.5 per-station-day decision record (first blocking gate) ===")
    by_gate: dict[str, int] = {}
    for gate_record in gate_records:
        by_gate[gate_record.gate] = by_gate.get(gate_record.gate, 0) + 1
    for gate, count in sorted(by_gate.items()):
        print(f"  first_gate={gate:<24} {count} (instrument, print) pairs")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.now(tz=dt.UTC).strftime("%Y%m%dT%H%M%S%z")
    output_path = args.output_dir / f"print_lock_live_capture_{timestamp}.json"
    output_path.write_text(
        json.dumps(
            {
                "generated_at_utc": dt.datetime.now(tz=dt.UTC).isoformat(),
                "mode": "live_capture",
                "quote_catalog": str(args.quote_catalog),
                "tape_instance_id": args.tape_instance_id,
                "tape_subdirectory": args.tape_subdirectory,
                "work_catalog": str(args.work_catalog),
                "weather_catalog_root": str(args.weather_catalog_root),
                "climate_day": climate_day.isoformat(),
                "starting_balance_usd": STARTING_BALANCE_USD,
                "account_base_currency": USD.code,
                "real_observed_by_station": observed,
                "tradable_instrument_ids": [ti.instrument.id.value for ti in tape_instruments],
                "climate_day_records": [
                    {
                        "station": r.station,
                        "climate_day": r.climate_day.isoformat(),
                        "tmax_f": r.tmax_f,
                        "is_final": r.is_final,
                        "revision_seq": r.revision_seq,
                        "correction_flag": r.correction_flag,
                        "issuance_time_ns": r.issuance_time_ns,
                        "ts_init": r.ts_init,
                    }
                    for r in records
                ],
                "results": [r.to_json() for r in results],
                "decision_records": [g.to_json() for g in gate_records],
            },
            indent=2,
            sort_keys=True,
        ),
    )
    print(f"Wrote {output_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quote-catalog", type=Path, default=DEFAULT_QUOTE_CATALOG_PATH)
    parser.add_argument("--weather-catalog-root", type=Path, default=DEFAULT_WEATHER_CATALOG_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--tape-instance-id",
        default=None,
        help=(
            "Read the tape from `<quote-catalog>/<subdir>/<instance-id>/` (a live "
            "recorder run) instead of the already-converted `data/` partition. "
            "Selects LIVE-CAPTURE mode."
        ),
    )
    parser.add_argument("--tape-subdirectory", default="live")
    parser.add_argument(
        "--work-catalog",
        type=Path,
        default=None,
        help=(
            "Where the converted parquet lands. MUST be outside the capture root: the "
            "capture is read-only evidence."
        ),
    )
    parser.add_argument("--climate-day", default=None)
    parser.add_argument("--stations", default="NYC,MIA,MDW,LAX,SFO")
    parser.add_argument("--strategies", default="cli_settlement_print_lock")
    parser.add_argument(
        "--log-level",
        default="WARNING",
        help=(
            "Engine log level for LIVE-CAPTURE mode. `INFO` surfaces the strategy's own "
            "per-instrument subscription lines, which is the positive control that the "
            "run was WIRED and not merely quiet."
        ),
    )
    args = parser.parse_args(argv)

    if args.tape_instance_id is not None:
        if args.work_catalog is None or args.climate_day is None:
            parser.error("--tape-instance-id requires --work-catalog and --climate-day")
        return _run_live_capture(args)

    catalog = ParquetDataCatalog(str(args.quote_catalog))
    tape_instruments = _select_tape_instruments(catalog)
    if not tape_instruments:
        print("REFUSAL: no instrument on the tape carries both depth and quote data.")
        return 1

    _supported_stations, _excluded_stations = _partition_supported_stations(
        ti.facts.settlement_station for ti in tape_instruments
    )
    if _excluded_stations:
        _excluded_instrument_ids = [
            ti.instrument.id.value
            for ti in tape_instruments
            if ti.facts.settlement_station in _excluded_stations
        ]
        print(
            f"EXCLUDED {len(_excluded_instrument_ids)} instrument(s) for station(s) "
            f"{_excluded_stations}: no constructed forecast input and no REAL preliminary "
            f"observation for {_excluded_stations} (see ASSUMED_FORECAST_HIGH_F, "
            f"_load_real_observations) -- not fabricated, so excluded rather than defaulted.",
        )
        tape_instruments = [
            ti for ti in tape_instruments if ti.facts.settlement_station in _supported_stations
        ]
        if not tape_instruments:
            print("REFUSAL: no tradable instrument remains for a supported station.")
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
