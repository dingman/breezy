"""CLI settlement-print lock: buy the one bucket the FINAL print already won.

WHAT THIS TRADES
-----------------
Once the FINAL ``NwsClimateDay`` record for a station/climate-day prints a
settlement extreme, this strategy buys YES, taker, on the ONE ladder bucket
containing that value -- usually an INTERIOR bucket, which is the point. See
``decision.py`` for the full edge hypothesis, why an interior bucket is sound
after the final and dead after a preliminary, and the record-shape gates. See
``docs/strategies/archive/breezy_strategy_cli_settlement_print_lock.md`` for the design
brief this implements.

WHY THIS STRATEGY REQUIRES AN EXPLICIT stale_observation_hours
----------------------------------------------------------------
Identical in kind to
``breezy.strategy.running_extreme_lock.strategy``'s guard, and for the same
reason: ``RiskLimits.stale_observation_hours`` defaults ``None``, which is
fail-closed but INVISIBLE -- it REFUSES every observation-kind order with the
counted reason ``observation_limit_unset``, while ``RefusalAlerter._conditions``
builds exactly one hardcoded ``SHORTS_DISABLED`` condition and so alerts on
nothing. A mis-wired strategy would silently refuse every order in live.
:class:`MissingObservationBoundError` makes that structural: construction
raises the moment the bound is ``None``.

The BOUND ITSELF IS NOT THE SIBLING'S. ``running_extreme_lock`` uses 12.665h,
derived from the preliminary->first-final ISSUANCE gap (max-over-sites P99
12.3167h + live receipt P99 0.3488h) -- the window during which a PRELIMINARY
must stay usable until the final lands. This strategy's signal IS the final,
and its window is print-to-settlement, a different and much shorter cadence.
The derivation is written out at the single construction site,
``scripts/analysis/run_weather_strategy_backtests.py``
(``STALE_OBSERVATION_HOURS_CLI_SETTLEMENT_PRINT_LOCK``).

WHERE p_stable COMES FROM (and why it is a constant here, not a runtime query)
--------------------------------------------------------------------------------
``decision.py``'s pure ``evaluate_instrument`` takes ``p_stable`` as an input
and never computes it; this module supplies a FIXED, explicitly-cited
constant. The reasons are the same two that rule out a runtime-built table in
``running_extreme_lock``:

1. The only corpus large enough is the held AFOS archive, and reading it from
   strategy code is FORBIDDEN by the import-linter contract "Settlement and
   strategy code never reaches archived backfill records" (``pyproject.toml``).
2. The live catalog holds only what Breezy has ingested going forward -- too
   sparse at cold start, and querying it inside a backtest risks reading days
   in the backtest's own future (a second look-ahead channel beyond the one
   ``decision.py``'s ``published_at`` guard closes).

So the constant is the RESULT of arithmetic that already ran, once, in the
cited study -- not a formula this module re-executes.

DATA SEAM
---------
Subscribes ``OrderBookDepth10`` (never ``QuoteTick`` -- book depth drives L2
execution, and a quote can arrive after a weather record) through
``breezy.strategy.depth10.market_quote_from_depth``, which is the one seam
that renders ``OrderBookDepth10``'s ten-level ``Price(0)``/``Quantity(0)``
padding as ``None`` instead of a fabricated 0.00 top-of-book. Weather records
arrive client-scoped via ``subscribe_data(..., client_id=NWS_BACKTEST_CLIENT_ID)``.
"Hours to settlement" is read LIVE from each instrument's own
``expiration_ns`` (the native settlement deadline) -- this strategy has no
forecast and therefore no ``ForecastSource`` to read a horizon from.

EXECUTION SEAM
--------------
Orders are MARKETABLE LIMITS at ``ask + slippage_prob``, IOC, never unpriced
market orders. ``slippage_prob`` is the load-bearing safety input -- the whole
"ask 0.99 is unwritable" contract rests on it -- and a market order carries no
price, so nothing downstream would hold a fill to the cost the edge model
charged. This strategy's trigger is a PUBLIC print: every participant receives
it at the same instant, so the quoted offer is exactly the offer everyone else
is lifting, and a taker with no price limit walks the book. The visible-depth
clip in ``decision.py`` does NOT close that -- ``market_quote_from_depth`` reads
LEVEL-0 size, which makes "price quoted is price paid" true only for a LIMIT.

For the same reason the admissible QUOTE AGE depends on which event is asking:
see :data:`PRINT_ARRIVAL_MAX_QUOTE_AGE_MINUTES`. And because the observation
is FINAL and never changes while the ask keeps moving, the dollar cost basis
is bounded at the POSITION, not per decision --
``_clip_to_cost_basis_anchor``.

NOT IMPLEMENTED, DELIBERATELY
-----------------------------
* Clock alerts for the expected CLI window. The brief lists them as
  OPTIONAL ("optionally set clock alerts"); every evaluation this strategy
  can make is already triggered by the two events that carry new information
  (a record, or a book update), so a timer would only re-run a decision on
  unchanged inputs.
* ``on_instrument_close`` handling. Settlement is harness-owned, per the
  brief.
"""

from __future__ import annotations

import datetime as dt
import math
from typing import TYPE_CHECKING, Final

from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.trading.strategy import Strategy

from breezy.domain.nws_climate_day import NwsClimateDay
from breezy.domain.weather_bucket_facts import Measure, read_weather_bucket_facts
from breezy.ingest.nws_actor import nws_climate_day_data_type
from breezy.runtime.backtest_feed import NWS_BACKTEST_CLIENT_ID
from breezy.strategy.cli_settlement_print_lock.config import CliSettlementPrintLockConfig
from breezy.strategy.cli_settlement_print_lock.decision import (
    MEASURED_STATIONS,
    CliPrintObservation,
    evaluate_instrument,
)
from breezy.strategy.depth10 import market_quote_from_depth
from breezy.strategy.weather_common.bucket_contract import MispricingContract
from breezy.strategy.weather_common.costs import (
    INSTRUMENT_INFO_FEE_COEFFICIENT_KEY,
    FeeCoefficientSource,
    UnknownFeeScheduleError,
    fee_coefficient_from_info,
)
from breezy.strategy.weather_common.equity import (
    observed_equity,
    reduce_only_refusal_note,
)
from breezy.strategy.weather_common.freshness import SignalFreshness
from breezy.strategy.weather_common.inflight import signed_working_qty, working_orders
from breezy.strategy.weather_common.models import MarketQuote, hours_until
from breezy.strategy.weather_common.refusals import RefusalAlerter, RefusalCounter
from breezy.strategy.weather_common.risk import (
    PortfolioSnapshot,
    RiskLimits,
    RiskManager,
    SharedExposureView,
)
from breezy.strategy.weather_common.shared_exposure import SharedExposureMixin

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nautilus_trader.core.data import Data
    from nautilus_trader.model.data import OrderBookDepth10
    from nautilus_trader.model.identifiers import InstrumentId

    from breezy.strategy.weather_common.models import SignalDecision

__all__ = [
    "ABSOLUTE_SLIPPAGE_FLOOR_PROB",
    "COST_BASIS_EXHAUSTED_REFUSAL",
    "MEASURED_P_STABLE_WILSON_LOWER",
    "MEASURED_STATIONS",
    "PRINT_ARRIVAL_MAX_QUOTE_AGE_MINUTES",
    "CliSettlementPrintLockStrategy",
    "EdgeFloorInversionError",
    "FeeCoefficientMismatchError",
    "MissingFeeCoefficientSourceError",
    "MissingObservationBoundError",
    "NegativeEdgeFloorError",
    "NoTradableMeasureError",
    "UnmeasuredStationError",
    "UnpricedInstrumentError",
]

#: The slippage floor that does NOT depend on the venue's price granularity,
#: in probability units.
#:
#: WHY AN ABSOLUTE CONSTANT AND NOT THE TICK. The floor used to be
#: ``slippage_prob >= instrument.price_increment`` alone. A taker's slippage is
#: a function of BOOK DEPTH and LATENCY; the tick is a function of the venue's
#: price GRANULARITY, and halving the tick does not halve the adverse move.
#: Executed counter-example on the old rule: at ``tick_size = 0.001``,
#: ``slippage_prob = 0.001`` was legal and ``worst_admissible_ask(...)``
#: returned **0.99** with edge **+0.005302** -- the exact trade BL-19 s8.2
#: computes as **-0.003698** and the whole cost contract exists to refuse.
#:
#: The value is BL-19 s8.5's placeholder, unchanged: one 0.01 tick at the
#: observed tick size, explicitly UNMEASURED, covering quote-age drift and
#: queue risk only (the depth component is priced separately by the visible-
#: depth clip in ``decision.py``). It is a FLOOR, not a replacement -- the
#: effective bound is ``max(ABSOLUTE_SLIPPAGE_FLOOR_PROB, tick_size)``, so a
#: COARSER venue grid still raises it. When s8.5's instrumentation yields a
#: measured figure this constant is RE-DERIVED from it, never removed: a floor
#: of zero restores exactly the configuration the cost contract exists to
#: forbid. A BUILD-side decision, not an operator-reserved control.
ABSOLUTE_SLIPPAGE_FLOOR_PROB: Final[float] = 0.01

#: The MAXIMUM age, in minutes, of the cached book this strategy will act on
#: when the trigger is a CLI PRINT ARRIVAL rather than a book update.
#:
#: ``stale_quote_minutes`` (15.0) is the general bound and stays in force on
#: the book-driven path. It is far too loose on the print-driven one, and the
#: difference is not data quality -- it is ADVERSE SELECTION. The final print
#: is PUBLIC: every participant sees it at the same instant, so the offer
#: quoted before it is precisely the offer everyone else is lifting. At ask
#: 0.98 the entire modelled edge is +0.005720 -- 0.57 of ONE tick -- so a
#: single tick of post-print movement is already a loss.
#:
#: One minute, fail-closed, pending BL-19 s8.5's measurement of realised
#: fills: no bound on the rate at which these books move has ever been
#: measured, so the honest choice is the tightest bound that still permits a
#: trade at all. The cost of being tight is only a DELAY -- the observation is
#: stored and ``on_order_book_depth`` re-evaluates on the next book update,
#: which by construction carries a zero-age quote.
PRINT_ARRIVAL_MAX_QUOTE_AGE_MINUTES: Final[float] = 1.0

#: Counted refusal reason for a top-up refused by the POSITION-level cost
#: basis anchor. A FIXED string, never composed from a value -- see
#: ``weather_common.refusals``: an unbounded key space is a memory leak, not
#: a counter. Recorded by the strategy layer rather than by
#: ``RiskManager.evaluate_order`` (so it is deliberately NOT a member of
#: ``COUNTED_REFUSAL_REASONS``, which documents that method's own closed set),
#: exactly as the decision layer already records ``shorts_disabled`` --
#: ``weather_common.refusals`` is explicit that both layers count into the one
#: counter, because counting only the risk manager leaves the counter at zero
#: for refusals that never reach it (BL-10 / BL-19 s8.5 null class N1).
COST_BASIS_EXHAUSTED_REFUSAL: Final[str] = "cost_basis_exhausted"

#: ``RiskManager.quote_tradable``'s own spelling, reused so the strategy-side
#: print-arrival bound and the risk-side general bound land on ONE counter key.
_STALE_QUOTE_REFUSAL: Final[str] = "stale_quote"

#: Guards ``ceil``/``floor`` against a representation error in an exact tick
#: multiple (0.01 has no exact binary representation). Same role and magnitude
#: as ``decision._TICK_EPSILON``.
_TICK_EPSILON: Final[float] = 1e-9


class MissingObservationBoundError(ValueError):
    """Raised when this strategy is wired with no observation-liveness bound.

    See the module docstring's "WHY THIS STRATEGY REQUIRES AN EXPLICIT
    stale_observation_hours" section.

    Deliberately a SEPARATE class from
    ``breezy.strategy.running_extreme_lock.strategy.MissingObservationBoundError``
    rather than an import of it: one shipped strategy package importing
    another's private failure type would couple two independent plug-ins for
    the sake of one exception name. The right home for a shared version is
    ``weather_common``, which is a refactor of already-shipped code and a
    named follow-up, not part of this change.
    """


class NoTradableMeasureError(ValueError):
    """Raised when both measure enables are off.

    ``use_tmax=False`` with ``use_tmin=False`` is a strategy that can never
    trade anything, which is the same silent-no-op failure mode
    :class:`MissingObservationBoundError` exists to prevent -- and equally
    invisible, since "evaluated nothing" and "refused everything" look
    identical from outside. Fail at construction instead.
    """


class MissingFeeCoefficientSourceError(ValueError):
    """Raised when this strategy is wired with no fee-coefficient source.

    Mirrors
    ``breezy.strategy.weather_common.forecast_source.MissingForecastSourceError``
    exactly, including the explicit ``is None`` check, so a caller that pushes
    ``None`` through an ``Optional``-typed call site gets a loud, immediate
    refusal rather than a strategy that quietly never trades -- or, worse, one
    that falls back to a hardcoded fee and trades a market whose real schedule
    nobody read.
    """


class UnpricedInstrumentError(ValueError):
    """Raised at ``on_start`` for an instrument this strategy cannot cost.

    Two causes, one posture: the market carries no usable fee coefficient, or
    the configured ``slippage_prob`` is below the effective slippage floor
    (:data:`ABSOLUTE_SLIPPAGE_FLOOR_PROB`, raised to the instrument's own tick
    when that tick is coarser), including a non-finite value.

    Same reasoning, and for the same reason, as
    :class:`MissingObservationBoundError` above: both are STATIC properties of
    a market, so deferring the refusal to decision time converts a loud
    startup failure into a permanent, SILENT no-op that the refusal counter
    cannot see (BL-19 s8.5 null class N1 -- a pre-signal ``None`` never reaches
    ``evaluate_order`` and is never counted, the same class as BL-10).
    ``adapters.polymarket_us.fees`` is explicit that an unparseable
    coefficient raises rather than trading free; this is that rule, moved to
    the gate.

    WHERE EACH HALF OF THE SLIPPAGE FLOOR IS CHECKED. The ABSOLUTE half
    (:data:`ABSOLUTE_SLIPPAGE_FLOOR_PROB`, and the finiteness check) needs no
    instrument and is therefore raised from ``__init__``, the earliest point
    at which it is knowable. Only the per-instrument half -- a venue whose
    tick is COARSER than the absolute floor -- has to wait for ``on_start``.

    The tick half used to be the WHOLE floor, justified by a claim in
    ``bucket_contract.py`` that "the captured universe carries more than one
    tick size". That claim is RETRACTED: a re-run of the sweep over
    ``docs/evidence/venue/polymarket_us/raw/*.json`` finds
    ``orderPriceMinTickSize == 0.01`` in 729/729 observations; the field that
    varies is ``minimumTradeQty``. The floor no longer rests on it either way
    -- see :data:`ABSOLUTE_SLIPPAGE_FLOOR_PROB` for why a price-granularity
    bound was never the right shape for an execution cost.
    """


class NegativeEdgeFloorError(ValueError):
    """Raised when either edge floor is negative or non-finite.

    :class:`EdgeFloorInversionError` above checks only the RELATIVE order of
    the two floors, so ``min_model_edge = min_edge_after_costs = -0.02``
    satisfies it. That pair is a two-line config edit with no error and
    negative expectation:

    * ``decision.py``'s ``edge < cfg.min_edge_after_costs`` admits ask 0.99 at
      edge **-0.003698** (BL-19 s8.2);
    * ``risk.py:421``'s ``abs(edge) < limits.min_model_edge`` can NEVER fire
      against a negative threshold, because ``abs`` is non-negative -- the
      re-application that exists to catch exactly this is disarmed;
    * ``worst_admissible_ask`` clamps ``a_max`` to 1.0, so the derived cost
      basis anchor becomes the full **$25.00** rather than $24.53.

    A floor of ZERO is accepted: "no positive expectation required" is a
    defensible (if useless) setting. A NEGATIVE floor is a requirement to
    lose money, which is not a setting. Non-finite is refused in the same
    place because ``nan`` compares ``False`` against everything, so a ``nan``
    floor passes both the inversion check and the decision-layer gate.
    """


class FeeCoefficientMismatchError(ValueError):
    """Raised at ``on_start`` when the injected ``theta`` is not this market's.

    :class:`~breezy.strategy.weather_common.costs.FeeCoefficientSource`
    is a PULL seam whose one method takes an OPAQUE ``instrument_id`` string.
    Nothing in the Protocol obliges an implementation to return a value ABOUT
    the instrument it was asked for, and the shipped
    ``PolymarketUSFeeCoefficients`` holds its own COPIED mapping built at the
    wiring site -- so a mis-keyed, partially-built or drifted map answers with
    another market's coefficient and every cost this strategy computes is
    priced off the wrong number, silently and forever.

    ``on_start`` already holds the ``Instrument``, whose own
    ``info[fee_coefficient]`` is the venue's authority on its own fee
    schedule. Comparing the two is free and turns a silent mispricing into a
    startup failure.

    STALENESS IS NOT HANDLED, AND THAT IS THE DECISION. ``theta`` is resolved
    once and frozen, with no ``on_instrument`` refresh, because:

    1. A fee schedule is a STATIC property of a market. The captured corpus
       carries ``feeCoefficient == 0.06`` in 729/729 observations across 680
       distinct slugs, spanning both OPEN and RESOLVED markets, and **no slug
       ever disagrees with itself across duplicate observations**
       (``docs/core/archive/PROGRESS-pre-2026-08-31-backlog-replacement.md``
       lines 941-944). There is no observed instance of the thing a refresh
       would track.
    2. A refresh would MUTATE a cost input mid-session that the decision layer
       treats as a constant, so two evaluations of the same book could size
       and price differently for a reason no recorded decision explains. That
       is a larger hazard than the one it closes, and it would also require
       subscribing to instrument updates that nothing else in this strategy
       needs.

    If a venue is ever observed re-pricing a live market, the correct response
    is a loud REFUSAL on change, not a silent re-read.
    """


class UnmeasuredStationError(ValueError):
    """Raised at ``on_start`` for a station ``p_stable`` was never measured on.

    :data:`MEASURED_STATIONS` is the support of
    :data:`MEASURED_P_STABLE_WILSON_LOWER`. The decision layer refuses an
    unmeasured station too (that gate is the independently-reusable one), but
    refusing here as well turns a silent per-record ``None`` into a loud
    startup failure -- a new city listing is a routine VENUE event that would
    otherwise present as "the market had no opportunities".
    """


class EdgeFloorInversionError(ValueError):
    """Raised when ``min_model_edge`` exceeds ``min_edge_after_costs``.

    The two are one concept spelled twice: the decision layer applies
    ``min_edge_after_costs`` to the cost-netted edge, and
    ``RiskManager.evaluate_order`` re-applies ``abs(edge) < min_model_edge``
    (``risk.py:421``) to that SAME already-netted number. An inverted pair
    means every signal the decision layer forms is refused 100% of the time as
    ``edge_below_minimum`` -- and ``RefusalAlerter._conditions`` builds only a
    ``SHORTS_DISABLED`` condition, so nothing alerts and the strategy is
    indistinguishable from a market with no opportunities. Exactly the failure
    class :class:`MissingObservationBoundError` exists to prevent.
    """


#: The measured stability of the FINAL CLI print, as the PER-STATION
#: Wilson-95%-LOWER bound (never the point estimate, and never the pooled
#: bound): ONE observed failure at n = 1821 station-days, which yields
#: 0.9968958673916. Source counts:
#: ``docs/evidence/observation_lock_falsification_2026-08-31.md`` section 1
#: (archive-powered, 2020-12..2026-08, KNYC/KMIA/KMDW/KLAX/KSFO; metric is
#: first FINAL -> last pre-settlement value). Derivation and consequences:
#: ``docs/evidence/bl19_edge_and_cost_decision_2026-09-01.md`` section 8.
#: Computed with the same formula as
#: ``scripts/analysis/settlement_alignment_study.py:wilson_lower_bound``
#: (z = 1.959963984540054); the derivation -- not merely the digits -- is
#: pinned by
#: ``test_measured_p_stable_is_the_per_station_wilson_lower_bound``.
#:
#: WHY NOT THE POOLED BOUND. The raw statistic is 9105/9106 pooled across the
#: five stations, whose Wilson-95% lower bound is 0.9993781607038432. Pooling
#: is only licensed if the five sites are EXCHANGEABLE, and this repo's own
#: powered G-01 study refutes that: measured preliminary->final revision rates
#: are MDW 13.96%, NYC 11.79% and SFO 4.50% -- all failing a Wilson-upper
#: <= 0.05 test -- while LAX and MIA pass
#: (``observation_lock_falsification_2026-08-31.md`` section 3; "Standing
#: verdicts" in ``docs/core/PROGRESS.md``). The CLI products are issued by
#: five different WFOs (CLINYC / CLIMIA / CLIMDW / CLILAX / CLISFO) with
#: independent QC practice, so the stations differ materially and the pooled
#: bound OVERSTATES confidence. The binding constraint is the per-site
#: denominator, not meteorology: at n ~ 1821 station-days no amount of
#: observed stability can certify past ~0.9979 at 95%.
#:
#: WHY ONE FAILURE AND NOT ZERO. The single observed failure is charged in
#: full to one station's denominator. A ZERO-failure bound at the same n
#: would be 0.9978949081838723 -- strictly HIGHER -- so this is deliberately
#: the conservative construction, not the optimistic one. Fail closed.
#:
#: The companion gate from the same table -- 98.66% (9041/9164) of
#: station-days leave a legal window above ``min_hours_to_settlement`` -- is
#: not a decision input: the window is enforced live, per instrument, by
#: ``RiskManager.evaluate_order``'s settlement-halt step against the
#: instrument's own ``expiration_ns``.
MEASURED_P_STABLE_WILSON_LOWER: Final[float] = 0.996896


class CliSettlementPrintLockStrategy(SharedExposureMixin, Strategy):
    """Buys YES, taker, on the bucket containing the FINAL CLI printed value."""

    def __init__(
        self,
        config: CliSettlementPrintLockConfig,
        fee_coefficients: FeeCoefficientSource,
    ) -> None:
        super().__init__(config)
        if fee_coefficients is None:
            raise MissingFeeCoefficientSourceError(
                "CliSettlementPrintLockStrategy requires a FeeCoefficientSource: the "
                "venue fee is theta * p * (1 - p) with theta a PER-MARKET venue fact, "
                "and there is deliberately no config field and no default for it -- a "
                "strategy-side default would reintroduce the fallback "
                "breezy.adapters.polymarket_us.fees refuses. Inject one at the "
                "construction site.",
            )
        if config.stale_observation_hours is None:
            raise MissingObservationBoundError(
                "CliSettlementPrintLockConfig.stale_observation_hours is None. This is an "
                "observation-kind strategy: RiskLimits.stale_observation_hours defaults "
                "None and None REFUSES every order (counted as 'observation_limit_unset'), "
                "but that refusal is invisible in live -- RefusalAlerter._conditions only "
                "ever alerts on SHORTS_DISABLED. Set an explicit float bound at the call "
                "site rather than shipping a strategy that silently refuses everything. "
                "The derived value for this strategy is NOT running_extreme_lock's "
                "12.665h -- see the module docstring and "
                "STALE_OBSERVATION_HOURS_CLI_SETTLEMENT_PRINT_LOCK.",
            )
        if not config.use_tmax and not config.use_tmin:
            raise NoTradableMeasureError(
                "CliSettlementPrintLockConfig has use_tmax=False and use_tmin=False: this "
                "strategy would evaluate no instrument at all and be indistinguishable "
                "from one that merely found no opportunity. Enable at least one measure.",
            )
        if not math.isfinite(config.slippage_prob):
            raise UnpricedInstrumentError(
                f"CliSettlementPrintLockConfig.slippage_prob {config.slippage_prob!r} is "
                "not a finite number. `nan < floor` is False, so a non-finite value "
                "passes every bare comparison and only raises later, inside "
                "`trade_cost_prob`, from a DATA HANDLER mid-session -- the exact "
                "loud-at-the-gate / silent-in-flight inversion every other guard here "
                "exists to prevent.",
            )
        if config.slippage_prob < ABSOLUTE_SLIPPAGE_FLOOR_PROB:
            raise UnpricedInstrumentError(
                f"CliSettlementPrintLockConfig.slippage_prob {config.slippage_prob} is "
                f"below the absolute floor {ABSOLUTE_SLIPPAGE_FLOOR_PROB}. Slippage is "
                "determined by BOOK DEPTH and LATENCY, not by the venue's price "
                "granularity, and it is the ONLY writable cost input -- a value below "
                "the floor is how ask 0.99 gets admitted (BL-19 s8.2: edge -0.003698 "
                "there). See ABSOLUTE_SLIPPAGE_FLOOR_PROB.",
            )
        for name, floor in (
            ("min_model_edge", config.min_model_edge),
            ("min_edge_after_costs", config.min_edge_after_costs),
        ):
            if not math.isfinite(floor) or floor < 0.0:
                raise NegativeEdgeFloorError(
                    f"CliSettlementPrintLockConfig.{name} is {floor!r}. An edge floor "
                    "must be a finite, non-negative number: `risk.py:421` compares "
                    "`abs(edge)` against it, so a NEGATIVE floor can never fire and a "
                    "`nan` floor compares False against everything -- either one "
                    "disarms the re-application silently and admits ask 0.99 at edge "
                    "-0.003698. Zero is accepted; below zero is a requirement to lose "
                    "money, which is not a setting.",
                )
        if config.min_model_edge > config.min_edge_after_costs:
            raise EdgeFloorInversionError(
                f"CliSettlementPrintLockConfig has min_model_edge "
                f"{config.min_model_edge} > min_edge_after_costs "
                f"{config.min_edge_after_costs}. RiskManager.evaluate_order re-applies "
                "min_model_edge to the number this strategy's decision layer has "
                "ALREADY cost-netted, so every formed signal would be refused as "
                "'edge_below_minimum' -- and RefusalAlerter only ever alerts on "
                "SHORTS_DISABLED, so that refusal is invisible in live. These are two "
                "spellings of ONE floor; both default to MIN_EDGE_AFTER_COSTS_BL19.",
            )
        self._config: CliSettlementPrintLockConfig = config
        self._fee_coefficients: FeeCoefficientSource = fee_coefficients
        self._contracts: dict[str, MispricingContract] = {}
        self._nt_ids: dict[str, InstrumentId] = {}
        self._deadlines: dict[str, dt.datetime] = {}
        self._quotes: dict[str, MarketQuote] = {}
        self._observations: dict[str, CliPrintObservation] = {}
        self._risk: RiskManager | None = None
        self._shared_exposure_view: SharedExposureView | None = None
        #: PUBLIC -- readable by an operator or a test asking "did this
        #: strategy do nothing, or was it stopped from doing something?".
        self.refusals = RefusalCounter()
        self._refusal_alerter: RefusalAlerter | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def on_start(self) -> None:
        for instrument_id in self._config.instrument_ids:
            instrument = self.cache.instrument(instrument_id)
            if instrument is None:
                self.log.error(f"no instrument {instrument_id} in the cache; stopping")
                self.stop()
                return
            facts = read_weather_bucket_facts(instrument.info)
            if not self._measure_enabled(facts.measure):
                # A station's ladder legitimately spans both measures while
                # this instance trades one of them. Skipped, not a config
                # error -- and not registered, so it never enters the
                # exclusive-bucket exposure accounting either.
                self.log.warning(
                    f"{instrument_id} measures {facts.measure.value!r}, which this instance "
                    f"does not trade (use_tmax={self._config.use_tmax}, "
                    f"use_tmin={self._config.use_tmin}); skipping subscription.",
                )
                continue
            if facts.settlement_station not in MEASURED_STATIONS:
                raise UnmeasuredStationError(
                    f"{instrument_id} settles on station "
                    f"{facts.settlement_station!r}, which is not one of the "
                    f"{sorted(MEASURED_STATIONS)} p_stable was measured on. The "
                    "shipped bound is the PER-STATION one precisely because the five "
                    "measured WFOs are not exchangeable (revision rates 4.50%-13.96%), "
                    "so an unmeasured sixth office has no bound at all. A new city "
                    "listing is a venue event, not a licence to extrapolate.",
                )
            tick_size = float(instrument.price_increment)
            # A FLOOR, raised by a coarser grid and never lowered by a finer
            # one. The absolute half is already refused in `__init__`; only a
            # tick COARSER than it can still bind here.
            slippage_floor = max(ABSOLUTE_SLIPPAGE_FLOOR_PROB, tick_size)
            if self._config.slippage_prob < slippage_floor:
                raise UnpricedInstrumentError(
                    f"CliSettlementPrintLockConfig.slippage_prob "
                    f"{self._config.slippage_prob} is below {instrument_id}'s effective "
                    f"slippage floor {slippage_floor} (the greater of "
                    f"{ABSOLUTE_SLIPPAGE_FLOOR_PROB} and this market's own tick "
                    f"{tick_size}). Slippage cannot be smaller than the smallest "
                    "representable adverse price move, and it is the ONLY writable "
                    "cost input -- a value below the floor is how ask 0.99 gets "
                    "admitted (BL-19 s8.2: edge -0.003698 there).",
                )
            try:
                theta = self._fee_coefficients.fee_coefficient_for(str(instrument_id))
            except UnknownFeeScheduleError as exc:
                raise UnpricedInstrumentError(
                    f"No usable fee coefficient for {instrument_id}. An unresolved fee "
                    "schedule is a NO-TRADE, never a free trade: refusing at on_start "
                    "rather than at decision time, because a pre-signal None is never "
                    "counted by the refusal counter and would present as a market with "
                    "no opportunities.",
                ) from exc
            self._assert_theta_is_this_markets(instrument_id, instrument.info, theta)
            contract = MispricingContract(
                instrument_id=str(instrument_id),
                facts=facts,
                tick_size=tick_size,
                price_scale=(
                    self._config.price_scale_override
                    if self._config.price_scale_override is not None
                    else 1.0
                ),
                fee_coefficient=theta,
            )
            self._contracts[str(instrument_id)] = contract
            self._nt_ids[str(instrument_id)] = instrument_id
            self._deadlines[str(instrument_id)] = _ns_to_datetime(instrument.expiration_ns)
            self.subscribe_order_book_depth(instrument_id)
            self.log.info(f"CliSettlementPrintLockStrategy subscribed {instrument_id}")

        self._risk = RiskManager(
            self._risk_limits(),
            self._contracts,
            refusals=self.refusals,
            exposure_view=self._shared_exposure_view,
            native_instrument_ids=self._nt_ids,
        )
        self._refusal_alerter = RefusalAlerter(self.refusals, site=str(self.id))
        self.subscribe_data(nws_climate_day_data_type(), client_id=NWS_BACKTEST_CLIENT_ID)

    def _assert_theta_is_this_markets(
        self, instrument_id: InstrumentId, info: object, theta: float,
    ) -> None:
        """Cross-check the INJECTED coefficient against the instrument in hand.

        See :class:`FeeCoefficientMismatchError` for why an injected value is
        not self-certifying, and for the explicit decision not to handle
        staleness.
        """
        try:
            own = fee_coefficient_from_info(info)
        except UnknownFeeScheduleError as exc:
            raise UnpricedInstrumentError(
                f"{instrument_id} carries {INSTRUMENT_INFO_FEE_COEFFICIENT_KEY!r} but no "
                f"usable value in it, while the injected FeeCoefficientSource answered "
                f"{theta}. A present-but-unusable coefficient is the venue saying its fee "
                "schedule is UNKNOWN, which is a no-trade -- so the injected number did "
                "not come from this market.",
            ) from exc
        if own is None:
            # FAIL-OPEN, narrowly: the instrument publishes no coefficient at
            # all, so there is no authority to check against. A real venue
            # instrument always carries the key.
            return
        if abs(own - theta) > 1e-12:
            raise FeeCoefficientMismatchError(
                f"The injected FeeCoefficientSource returned theta {theta} for "
                f"{instrument_id}, but that market's own "
                f"{INSTRUMENT_INFO_FEE_COEFFICIENT_KEY!r} is {own}. The instrument is the "
                "venue's authority on its own fee schedule; an injected value that "
                "disagrees with it is a value about some OTHER market, and every cost "
                "this strategy computes would be priced off it.",
            )

    def _measure_enabled(self, measure: Measure) -> bool:
        return self._config.use_tmax if measure is Measure.HIGH else self._config.use_tmin

    def _risk_limits(self) -> RiskLimits:
        cfg = self._config
        return RiskLimits(
            max_position_contracts=cfg.max_position_contracts,
            max_event_notional=cfg.max_event_notional,
            max_location_notional=cfg.max_location_notional,
            max_simultaneous_positions=cfg.max_simultaneous_positions,
            max_equity_fraction=cfg.max_equity_fraction,
            min_model_edge=cfg.min_model_edge,
            max_bid_ask_spread=cfg.max_bid_ask_spread,
            min_liquidity_contracts=cfg.min_liquidity_contracts,
            min_hours_to_settlement=cfg.min_hours_to_settlement,
            halt_hours_before_settlement=cfg.halt_hours_before_settlement,
            stale_observation_hours=cfg.stale_observation_hours,
            stale_quote_minutes=cfg.stale_quote_minutes,
            # `transaction_cost_prob` is NOT forwarded: the field is dead in
            # `risk.py` (the identifier appears there exactly once, at its own
            # definition on line 116 -- `evaluate_order` never reads it and
            # `edge_after_costs` takes `cost` by injection), and this strategy
            # no longer has a total-cost scalar to forward anyway.
            allow_short=cfg.allow_short,
        )

    # ------------------------------------------------------------------
    # Data handlers
    # ------------------------------------------------------------------
    def on_order_book_depth(self, depth: OrderBookDepth10) -> None:
        iid = str(depth.instrument_id)
        if iid not in self._contracts:
            return
        # WITH the ask ladder (BL-25 D1). The decision layer prices and sizes
        # over the rungs its own marketable IOC limit can lift, not the
        # level-0 tick alone -- see `decision.evaluate_instrument`. Level-0
        # `ask`/`ask_size` are unchanged by this flag, so every other reader
        # of the quote (the risk manager's liquidity and spread screens, the
        # marketable limit price) sees exactly what it saw before.
        quote = market_quote_from_depth(depth, include_ask_ladder=True)
        if quote is None:
            return
        self._quotes[iid] = quote
        # Book-driven: the quote being evaluated IS this update, so its age is
        # zero and the general bound is the right one.
        self._evaluate_and_act(iid, max_quote_age_minutes=self._config.stale_quote_minutes)

    def on_data(self, data: Data) -> None:
        if type(data) is not NwsClimateDay:
            return
        for iid, contract in self._contracts.items():
            # Every other city's and every other day's record is ignored --
            # `applies_to` is station AND climate-day, unconditionally.
            if not contract.facts.applies_to(data.station, data.climate_day):
                continue
            self._observations[iid] = CliPrintObservation(
                station=data.station,
                climate_day=data.climate_day,
                tmax_f=data.tmax_f,
                tmin_f=data.tmin_f,
                is_final=data.is_final,
                correction_flag=data.correction_flag,
                is_superseded=data.is_superseded,
                published_at=_ns_to_datetime(data.issuance_time_ns),
            )
            # Print-driven: the book is whatever was LAST CACHED, and the
            # trigger is public information every participant receives at the
            # same instant. See PRINT_ARRIVAL_MAX_QUOTE_AGE_MINUTES.
            self._evaluate_and_act(
                iid,
                max_quote_age_minutes=min(
                    self._config.stale_quote_minutes,
                    PRINT_ARRIVAL_MAX_QUOTE_AGE_MINUTES,
                ),
            )

    # ------------------------------------------------------------------
    # Decision + execution
    # ------------------------------------------------------------------
    def _evaluate_and_act(self, instrument_id: str, *, max_quote_age_minutes: float) -> None:
        contract = self._contracts[instrument_id]
        quote = self._quotes.get(instrument_id)
        observation = self._observations.get(instrument_id)
        if quote is None or observation is None:
            return
        now = self.clock.utc_now()
        deadline = self._deadlines[instrument_id]
        hours_to_settlement = hours_until(deadline, now)
        if hours_to_settlement <= self._config.halt_hours_before_settlement:
            # This strategy holds through settlement once entered (the
            # brief's holding-period section: the edge dies AT settlement),
            # so there is no exit signal to emit here and nothing to flatten
            # if it never entered.
            return

        assert self._risk is not None  # built in on_start, before any data can arrive
        decision = evaluate_instrument(
            contract=contract,
            quote=quote,
            observation=observation,
            now=now,
            p_stable=MEASURED_P_STABLE_WILSON_LOWER,
            cfg=self._config,
        )
        if decision is None:
            self._report_refusals()
            return
        current_qty = float(self.portfolio.net_position(self._nt_ids[instrument_id]))
        self._maybe_submit(
            contract,
            quote,
            decision,
            observation,
            now,
            current_qty,
            max_quote_age_minutes,
        )

    def _maybe_submit(
        self,
        contract: MispricingContract,
        quote: MarketQuote,
        decision: SignalDecision,
        observation: CliPrintObservation,
        now: dt.datetime,
        current_qty: float,
        max_quote_age_minutes: float,
    ) -> None:
        nt_id = self._nt_ids[contract.instrument_id]
        # INITIALIZED and SUBMITTED count: `cache.orders_open(...)` excludes
        # both, so this gate used to read an empty book inside the
        # submit -> ACCEPTED window and let a duplicate order through
        # (`weather_common.inflight`).
        if working_orders(self.cache, nt_id):
            self.log.debug(f"skip {contract.instrument_id}: working order exists")
            return
        # LONG_YES only -- `decision.py` never returns any other intent. A
        # delta below 1 lot means we are already at or past target size, and
        # this strategy never reduces (it has no exit signal).
        delta = decision.quantity - current_qty
        if delta < 1.0:
            return

        observation_age_hours = (now - observation.published_at).total_seconds() / 3600.0
        # Unit proof: this delta is minutes, the unit `stale_quote_minutes` expects.
        quote_age_minutes = (now - quote.ts_event).total_seconds() / 60.0
        # The TRIGGER-DEPENDENT bound, applied ahead of (and never instead of)
        # `RiskManager.quote_tradable`'s general one: risk is constructed once
        # and holds a single `stale_quote_minutes`, while the admissible age
        # here depends on WHICH event is asking. Only the tighter of the two
        # can fire here; risk still applies its own bound, its `future_quote`
        # guard for a negative age, and everything else. Counted under the
        # SAME key `quote_tradable` uses, so an operator reads one number.
        if quote_age_minutes > max_quote_age_minutes:
            self.refusals.record(_STALE_QUOTE_REFUSAL)
            self.log.info(
                f"RISK block {contract.instrument_id}: stale_quote "
                f"age={quote_age_minutes:.2f}m > {max_quote_age_minutes:.2f}m",
            )
            self._report_refusals()
            return

        delta = self._clip_to_cost_basis_anchor(contract, decision, delta)
        if delta < 1.0:
            self.refusals.record(COST_BASIS_EXHAUSTED_REFUSAL)
            self.log.info(
                f"RISK block {contract.instrument_id}: {COST_BASIS_EXHAUSTED_REFUSAL} "
                f"edge={decision.edge:.3f}",
            )
            self._report_refusals()
            return

        deadline = self._deadlines[contract.instrument_id]
        assert self._risk is not None
        risk_decision = self._risk.evaluate_order(
            contract=contract,
            signed_qty_delta=delta,
            hours_to_settlement=hours_until(deadline, now),
            signal_age=SignalFreshness.observation(observation_age_hours),
            edge=decision.edge,
            portfolio=self._portfolio_snapshot(),
            quote=quote,
            quote_age_minutes=quote_age_minutes,
        )
        if not risk_decision.allowed:
            self.log.info(
                f"RISK block {contract.instrument_id}: {risk_decision.reason} "
                f"edge={decision.edge:.3f}"
                + reduce_only_refusal_note(
                    risk_decision.reason, tick_ts_ns=self.clock.timestamp_ns(),
                ),
            )
            self._report_refusals()
            return
        self._submit_delta(contract, risk_decision.clipped_quantity, decision, quote)

    def _clip_to_cost_basis_anchor(
        self,
        contract: MispricingContract,
        decision: SignalDecision,
        delta: float,
    ) -> float:
        """Bound the POSITION's cost basis by ``A``, not merely this decision's.

        ``decision.quantity`` is a TARGET LEVEL, and this strategy tops up to
        it on every depth tick. The observation is FINAL and NEVER CHANGES --
        only the ask moves -- so as the ask falls ``A / premium`` rises and the
        old rule bought MORE, averaging down through the entire decline. Each
        decision genuinely committed the design's $24.53; the POSITION did not.
        Measured over a monotone decline from 0.98 to 0.16 the old rule
        deployed **$62.60**, 2.55x the anchor, and it deployed it SPECIFICALLY
        BECAUSE the market disagreed more -- which is the shape of a wrong
        bucket mapping or a pending correction, not of a bigger edge.

        The basis already committed is read from the NATIVE position
        (``Position.avg_px_open`` plus its own ``commissions()``), never
        re-derived from the current ask: at a falling ask a current-price
        estimate understates the historical basis and re-opens the ratchet.
        Working orders cannot double-count, because ``_maybe_submit`` has
        already returned if any order is WORKING on this instrument -- which
        now includes one merely ``INITIALIZED`` or ``SUBMITTED``, the two
        statuses ``orders_open`` missed (``weather_common.inflight``, T-1).
        """
        anchor = decision.metadata.get("cost_basis_anchor")
        fee_prob = decision.metadata.get("fee_prob")
        if not isinstance(anchor, float) or not isinstance(fee_prob, float):
            # The decision layer always supplies both. A decision that does not
            # is not one this execution path can bound, so it does not trade.
            self.log.error(
                f"decision for {contract.instrument_id} carries no cost basis anchor; "
                "refusing to size against an unbounded budget",
            )
            return 0.0
        premium = decision.market_probability + fee_prob
        if premium <= 0.0:
            return 0.0
        remaining = anchor - self._committed_basis(contract)
        affordable = math.floor(max(0.0, remaining) / premium + _TICK_EPSILON)
        return min(delta, float(affordable))

    def _committed_basis(self, contract: MispricingContract) -> float:
        """Dollars this instrument's OPEN position has already committed.

        NAUTILUS NULL HYPOTHESIS (L-1), checked first: ``Position`` already
        maintains ``avg_px_open`` (``model/position.pyx:95``, updated on every
        fill by ``_calculate_avg_px_open_px`` at ``:963``) and ``commissions()``
        (``:864``), and ``Cache.positions_open(instrument_id=...)`` already
        indexes them per instrument. Nothing is re-implemented here: this is
        the sum the framework already computes, converted from raw venue price
        units to payout dollars by the contract's own ``price_scale``.
        """
        total = 0.0
        nt_id = self._nt_ids[contract.instrument_id]
        for position in self.cache.positions_open(instrument_id=nt_id):
            total += float(position.quantity) * position.avg_px_open * contract.price_scale
            total += sum(float(money.as_double()) for money in position.commissions())
        return total

    def _submit_delta(
        self,
        contract: MispricingContract,
        signed_delta: float,
        decision: SignalDecision,
        quote: MarketQuote,
    ) -> None:
        nt_id = self._nt_ids[contract.instrument_id]
        instrument = self.cache.instrument(nt_id)
        if instrument is None:
            self.log.error(f"instrument vanished from cache: {contract.instrument_id}")
            return
        limit_price = self._marketable_limit_price(contract, quote)
        if limit_price is None:
            self.log.error(f"no ask to price against: {contract.instrument_id}")
            return
        # MARKETABLE LIMIT, IOC -- a taker fill that CANNOT pay more than the
        # price the edge was computed at plus the slippage that edge already
        # charged. An unpriced MARKET order carried no such bound: this
        # strategy is triggered by a PUBLIC print, so the quoted level is
        # exactly the level every other participant lifts at the same instant,
        # and the taker walks the book at whatever is left. Depth clipping does
        # not save that -- `market_quote_from_depth` takes level-0 size, which
        # guarantees "price quoted is price paid" only for a LIMIT.
        #
        # `post_only` stays False (the default): this is a taker, and
        # `backtest_order_guard` refuses a post-only order outright because
        # `PolymarketUSFeeModel` would price a maker fill wrong in SIGN.
        order = self.order_factory.limit(
            instrument_id=nt_id,
            order_side=OrderSide.BUY,
            quantity=instrument.make_qty(abs(signed_delta)),
            price=instrument.make_price(limit_price),
            time_in_force=TimeInForce.IOC,
        )
        self.submit_order(order)
        self.log.info(
            f"ORDER {contract.instrument_id} qty={signed_delta:+.1f} "
            f"limit={limit_price} intent=LONG_YES edge={decision.edge:.3f} "
            f"reason={decision.reason}",
        )

    def _marketable_limit_price(
        self, contract: MispricingContract, quote: MarketQuote,
    ) -> float | None:
        """``ask + slippage_prob``, in RAW venue units, ON the tick grid.

        ``slippage_prob`` is in PROBABILITY units and the order price is in the
        venue's own units, so it is divided by ``price_scale`` before being
        added (identity at the shipped scale of 1.0). It is then rounded UP to
        a whole number of ticks -- never down, which would emit a limit tighter
        than the cost the edge model charged -- and snapped to the grid, so the
        emitted price is representable by construction rather than by
        arithmetic luck. Capped at the maximum price of a binary (probability
        1.0), which no admissible ask can reach anyway: the edge floor already
        refuses ask 0.99.
        """
        if quote.ask is None:
            return None
        tick = contract.tick_size
        if tick <= 0.0:
            return None
        slippage_raw = self._config.slippage_prob / contract.price_scale
        ticks = math.ceil(slippage_raw / tick - _TICK_EPSILON)
        raw = quote.ask + ticks * tick
        snapped = math.floor(raw / tick + 0.5) * tick
        return min(snapped, 1.0 / contract.price_scale)

    def _report_refusals(self) -> None:
        """Push this evaluation's refusal counts through the alert path.

        Cheap by design -- `AlertState` dedupes.
        """
        if self._refusal_alerter is None:
            return
        self._refusal_alerter.report(now_ns=self.clock.timestamp_ns())

    def _portfolio_snapshot(self) -> PortfolioSnapshot:
        nt_ids = self._risk.instrument_ids(self._nt_ids) if self._risk is not None else self._nt_ids
        position_qty = {
            iid: float(self.portfolio.net_position(nt_id)) for iid, nt_id in nt_ids.items()
        }
        pending_qty = {
            iid: signed_working_qty(working_orders(self.cache, nt_id))
            for iid, nt_id in nt_ids.items()
        }
        return PortfolioSnapshot(
            position_qty=position_qty,
            pending_qty=pending_qty,
            equity=observed_equity(self.cache, self.portfolio, self._nt_ids),
        )


def _ns_to_datetime(ts_event: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(ts_event / 1_000_000_000, tz=dt.UTC)
