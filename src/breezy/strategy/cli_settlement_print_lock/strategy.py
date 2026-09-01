"""CLI settlement-print lock: buy the one bucket the FINAL print already won.

WHAT THIS TRADES
-----------------
Once the FINAL ``NwsClimateDay`` record for a station/climate-day prints a
settlement extreme, this strategy buys YES, taker, on the ONE ladder bucket
containing that value -- usually an INTERIOR bucket, which is the point. See
``decision.py`` for the full edge hypothesis, why an interior bucket is sound
after the final and dead after a preliminary, and the record-shape gates. See
``docs/strategies/breezy_strategy_cli_settlement_print_lock.md`` for the design
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
from typing import TYPE_CHECKING, Final

from nautilus_trader.model.enums import OrderSide
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
    FeeCoefficientSource,
    UnknownFeeScheduleError,
)
from breezy.strategy.weather_common.freshness import SignalFreshness
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
    from nautilus_trader.model.orders.base import Order

    from breezy.strategy.weather_common.models import SignalDecision

__all__ = [
    "MEASURED_P_STABLE_WILSON_LOWER",
    "MEASURED_STATIONS",
    "CliSettlementPrintLockStrategy",
    "EdgeFloorInversionError",
    "MissingFeeCoefficientSourceError",
    "MissingObservationBoundError",
    "NoTradableMeasureError",
    "UnmeasuredStationError",
    "UnpricedInstrumentError",
]


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
    the configured ``slippage_prob`` is below the instrument's own tick.

    Same reasoning, and for the same reason, as
    :class:`MissingObservationBoundError` above: both are STATIC properties of
    a market, so deferring the refusal to decision time converts a loud
    startup failure into a permanent, SILENT no-op that the refusal counter
    cannot see (BL-19 s8.5 null class N1 -- a pre-signal ``None`` never reaches
    ``evaluate_order`` and is never counted, the same class as BL-10).
    ``adapters.polymarket_us.fees`` is explicit that an unparseable
    coefficient raises rather than trading free; this is that rule, moved to
    the gate.

    The tick floor lives here rather than in ``config.py`` because
    ``tick_size`` is PER INSTRUMENT and unknown at config construction --
    ``bucket_contract.py`` records that the captured universe carries more
    than one tick size.
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
            if self._config.slippage_prob < tick_size:
                raise UnpricedInstrumentError(
                    f"CliSettlementPrintLockConfig.slippage_prob "
                    f"{self._config.slippage_prob} is below {instrument_id}'s own tick "
                    f"{tick_size}. Slippage cannot be smaller than the smallest "
                    "representable adverse price move, and it is the ONLY writable "
                    "cost input -- a value below one tick is how ask 0.99 gets "
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
        quote = market_quote_from_depth(depth)
        if quote is None:
            return
        self._quotes[iid] = quote
        self._evaluate_and_act(iid)

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
            self._evaluate_and_act(iid)

    # ------------------------------------------------------------------
    # Decision + execution
    # ------------------------------------------------------------------
    def _evaluate_and_act(self, instrument_id: str) -> None:
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
        self._maybe_submit(contract, quote, decision, observation, now, current_qty)

    def _maybe_submit(
        self,
        contract: MispricingContract,
        quote: MarketQuote,
        decision: SignalDecision,
        observation: CliPrintObservation,
        now: dt.datetime,
        current_qty: float,
    ) -> None:
        nt_id = self._nt_ids[contract.instrument_id]
        if self.cache.orders_open(instrument_id=nt_id):
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
                f"edge={decision.edge:.3f}",
            )
            self._report_refusals()
            return
        self._submit_delta(contract, risk_decision.clipped_quantity, decision)

    def _submit_delta(
        self,
        contract: MispricingContract,
        signed_delta: float,
        decision: SignalDecision,
    ) -> None:
        nt_id = self._nt_ids[contract.instrument_id]
        instrument = self.cache.instrument(nt_id)
        if instrument is None:
            self.log.error(f"instrument vanished from cache: {contract.instrument_id}")
            return
        # Taker against the live ask only -- a market order IS a taker fill.
        # No post-only, no maker rebate, and no emitted limit price, so the
        # venue's 0.01 tick cannot be violated here.
        order = self.order_factory.market(
            instrument_id=nt_id,
            order_side=OrderSide.BUY,
            quantity=instrument.make_qty(abs(signed_delta)),
        )
        self.submit_order(order)
        self.log.info(
            f"ORDER {contract.instrument_id} qty={signed_delta:+.1f} "
            f"intent=LONG_YES edge={decision.edge:.3f} reason={decision.reason}",
        )

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
            iid: _signed_open_order_qty(self.cache.orders_open(instrument_id=nt_id))
            for iid, nt_id in nt_ids.items()
        }
        return PortfolioSnapshot(
            position_qty=position_qty,
            pending_qty=pending_qty,
            equity=self._equity(),
        )

    def _equity(self) -> float:
        for nt_id in self._nt_ids.values():
            instrument = self.cache.instrument(nt_id)
            if instrument is None:
                continue
            account = self.portfolio.account(nt_id.venue)
            if account is None:
                continue
            balance = account.balance_total(instrument.quote_currency)
            if balance is not None:
                return float(balance.as_double())
        return self._config.starting_equity


def _ns_to_datetime(ts_event: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(ts_event / 1_000_000_000, tz=dt.UTC)


def _signed_open_order_qty(orders: list[Order]) -> float:
    total = 0.0
    for order in orders:
        total += float(order.signed_decimal_qty())
    return total
