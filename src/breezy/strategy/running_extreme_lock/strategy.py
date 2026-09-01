"""Running-extreme open-tail lock strategy: buy the already-cleared upper tail.

WHAT THIS TRADES
-----------------
Once a same-day, non-final (or final -- neither is required or excluded)
``NwsClimateDay`` record prints a running high already inside an open-ended
upper-tail bucket (``upper_f is None``), this strategy buys YES on that ONE
surviving bucket, taker, against the live ask. See ``decision.py`` for the
full edge hypothesis, the v1 scope (open tail only -- no interior bucket, no
low-measure tail), the margin-conditioned probability table, and the
acknowledged fat tail. See
``docs/strategies/archive/breezy_strategy_running_extreme_lock.md`` for the design
brief this implements, and the observation-freshness plan
(``PLAN_observation_freshness.md``, peer-reviewed) for the risk-layer
contract (``SignalFreshness`` / ``RiskLimits.stale_observation_hours``) this
strategy is the first to wire up.

WHY THIS STRATEGY REQUIRES AN EXPLICIT stale_observation_hours (C1a)
------------------------------------------------------------------------
``RiskLimits.stale_observation_hours`` defaults to ``None`` -- fail-closed:
unset REFUSES every observation-kind order with the counted reason
``observation_limit_unset`` (see ``breezy.strategy.weather_common.risk``).
That refusal is real, but it is INVISIBLE in live: ``RefusalAlerter._conditions``
(``breezy.strategy.weather_common.refusals``) builds exactly one hardcoded
``SHORTS_DISABLED`` condition, so a strategy silently refusing every order as
``observation_limit_unset`` counts the refusal and alerts on nothing. That is
verbatim the pathology ``refusals.py`` exists to prevent. The mitigation
(peer review C1a) is structural, not a refusal: ``__init__`` raises
:class:`MissingObservationBoundError` the moment ``stale_observation_hours``
is ``None``, so a mis-wired strategy fails LOUDLY at construction, before it
can ever run -- the same posture ``MissingForecastSourceError``
(``forecast_mispricing/strategy.py``) already takes for the forecast-driven
strategies' required ``ForecastSource``.

WHERE THE MARGIN-CONDITIONED PROBABILITY TABLE COMES FROM (and why it is a
constant here, not a runtime query)
----------------------------------------------------------------------------
``decision.py``'s pure ``evaluate_instrument`` takes ``model_p_table`` as an
input, never computes it -- and this module supplies a FIXED, immutable,
explicitly-cited constant (``_MEASURED_MARGIN_MODEL_P``), not a table built by
querying historical finals at ``on_start``. That is a deliberate v1 fallback,
not an oversight -- two independent facts rule out a runtime-built table:

1. The only corpus large enough to measure a per-margin Wilson bound is the
   held AFOS archive (N=9736 preliminary records, 2020-12..2026-08, 5 sites --
   ``docs/evidence/observation_lock_falsification_2026-08-31.md`` section 2).
   Reading it from strategy code is not merely impractical, it is FORBIDDEN by
   the import-linter contract "Settlement and strategy code never reaches
   archived backfill records" (``pyproject.toml``): ``source_modules`` names
   ``breezy.strategy`` directly, ``forbidden_modules`` names
   ``breezy.domain.archived_climate_day`` / ``breezy.persistence.archive_catalog``
   directly, and ``allow_indirect_imports = false``. A strategy that opened the
   archive at ``on_start`` would violate the same architectural boundary that
   keeps analysis-only data out of the trading path.
2. The live catalog (``breezy.persistence.catalog.read_climate_days``) holds
   only what Breezy itself has ingested going forward -- far too sparse at
   cold start for a robust per-margin bound, and querying it inside a backtest
   risks reading days that are in the backtest's own future relative to
   ``now`` (a second, independent look-ahead channel beyond the one
   ``decision.py``'s ``published_at`` guard already closes).

``scripts/analysis/settlement_alignment_study.py:wilson_lower_bound`` computed
the published numbers, but that module lives in ``scripts/`` -- it has no
``__init__.py`` (not an importable package), sits entirely outside the
``breezy`` root the import-linter contract governs, and analysis scripts add
their own directory to ``sys.path`` rather than being a stable import target.
Importing it from ``src/breezy/strategy`` would be a real architecture
violation even where the linter's ``root_packages = ["breezy"]`` scope
happens not to catch it mechanically. This module does not need the general
Wilson-lower-bound FORMULA at runtime at all -- the arithmetic already ran,
once, in the cited study; what this module needs (and carries) is only its
RESULT: six measured, cited numbers.

So: the table is measured (cited, with N), immutable, and passed into the
pure decision function exactly as the accepted v1 fallback in the
observation-freshness plan calls for -- "table construction is on_start work,
never decision work". Construction here is trivial (a module constant); the
honest alternative -- silently deriving a runtime table from a source this
module cannot legally or safely read -- is the one this module refuses.

DATA SEAM
---------
Subscribes ``OrderBookDepth10`` (never ``QuoteTick`` -- see
``docs/specs/STRATEGY_QUICKSTART.md`` Sec.3.1: book depth drives L2
execution, and a quote can arrive after a weather record) and client-scoped
NWS data. "Hours to settlement" is read LIVE from each instrument's own
``expiration_ns`` (the native settlement deadline) rather than from an
injected ``ForecastSource`` -- this strategy has no forecast, and unlike
``breezy.strategy.weather_common.bucket_contract``'s docstring for the
forecast-driven strategies, ``expiration_ns`` is already used as the ground
truth for this exact purpose in
``scripts/analysis/run_weather_strategy_backtests.py``
(``settlement_deadline_by_station``).

WIRING INTO run_weather_strategy_backtests.py -- NOT DONE, DELIBERATELY
----------------------------------------------------------------------------
That script's entire structure is forecast-plumbing: every strategy kind runs
under an injected ``ForecastSource`` (``_SyntheticForecastSource`` /
``_SequenceForecastSource``), and its settlement/forecast scenario sweep is
built around ``published_at`` offsets. An observation-only strategy has no
forecast to inject and nothing in that sweep shape to vary. Wiring this
strategy in would mean fabricating a forecast this strategy structurally
never reads, which the design brief and CLAUDE.md both forbid outright. See
the task report for this call: STOP AND REPORT rather than fake it.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from nautilus_trader.model.enums import OrderSide
from nautilus_trader.trading.strategy import Strategy

from breezy.domain.nws_climate_day import NwsClimateDay
from breezy.domain.weather_bucket_facts import Measure, read_weather_bucket_facts
from breezy.ingest.nws_actor import nws_climate_day_data_type
from breezy.runtime.backtest_feed import NWS_BACKTEST_CLIENT_ID
from breezy.strategy.depth10 import market_quote_from_depth
from breezy.strategy.running_extreme_lock.config import RunningExtremeLockConfig
from breezy.strategy.running_extreme_lock.decision import (
    RunningExtremeObservation,
    evaluate_instrument,
)
from breezy.strategy.weather_common.bucket_contract import MispricingContract
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

__all__ = ["MissingObservationBoundError", "RunningExtremeLockStrategy"]


class MissingObservationBoundError(ValueError):
    """Raised when this strategy is wired with no observation-liveness bound.

    See the module docstring's "WHY THIS STRATEGY REQUIRES AN EXPLICIT
    stale_observation_hours" section.
    """


#: Measured, margin-conditioned Wilson-95%-LOWER bounds -- see decision.py's
#: module docstring and ``docs/evidence/observation_lock_falsification_2026-08-31.md``
#: section 2 (N=9736 preliminary records, archive-powered, 2020-12..2026-08,
#: KNYC/KMIA/KMDW/KLAX/KSFO). Key 5 is the "5+" row: every margin from 5
#: upward collapses to this one measured value (identical p_hold at 4 and 5+
#: in the source table). Immutable by construction (`MappingProxyType`) so no
#: caller can mutate the module-level constant in place.
MEASURED_MARGIN_MODEL_P: Final[Mapping[int, float]] = MappingProxyType(
    {
        0: 0.996829,
        1: 0.998244,
        2: 0.998798,
        3: 0.999094,
        4: 0.999418,
        5: 0.999418,
    },
)


class RunningExtremeLockStrategy(SharedExposureMixin, Strategy):
    """Buys YES, taker, on the open-ended upper tail once the running high clears it."""

    def __init__(self, config: RunningExtremeLockConfig) -> None:
        super().__init__(config)
        if config.stale_observation_hours is None:
            raise MissingObservationBoundError(
                "RunningExtremeLockConfig.stale_observation_hours is None. This is an "
                "observation-kind strategy: RiskLimits.stale_observation_hours defaults "
                "None and None REFUSES every order (counted as 'observation_limit_unset'), "
                "but that refusal is invisible in live -- RefusalAlerter._conditions only "
                "ever alerts on SHORTS_DISABLED. Set an explicit float bound at the call "
                "site rather than shipping a strategy that silently refuses everything. "
                "See the module docstring for the measured candidate (12.665h) and its "
                "derivation.",
            )
        if not config.open_tail_only:
            raise NotImplementedError(
                "RunningExtremeLockConfig.open_tail_only=False requests the interior-bucket "
                "path, which v1 does not implement. The pre-registered symmetric-revision "
                "study FAILS the interior path on 3/5 sites (MDW 13.96%, NYC 11.79%, "
                "SFO 4.50%); only the open tail is shipped. See the module docstring "
                "for the cited evidence.",
            )
        self._config: RunningExtremeLockConfig = config
        self._contracts: dict[str, MispricingContract] = {}
        self._nt_ids: dict[str, InstrumentId] = {}
        self._deadlines: dict[str, dt.datetime] = {}
        self._quotes: dict[str, MarketQuote] = {}
        self._observations: dict[str, RunningExtremeObservation] = {}
        self._risk: RiskManager | None = None
        self._shared_exposure_view: SharedExposureView | None = None
        #: PUBLIC -- see the identical field in `ForecastMispricingStrategy`
        #: for why: readable by an operator or a test asking "did this
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
            if facts.measure is not Measure.HIGH:
                raise NotImplementedError(
                    f"{instrument_id} measures {facts.measure.value!r}; v1 trades the "
                    "open upper (HIGH) tail only -- no p_hold table exists yet for a "
                    "running-minimum open tail (see the decision.py module docstring).",
                )
            if facts.lower_f is None or facts.upper_f is not None:
                # Not an open-ended upper tail (either an interior bucket, or
                # a bottom-open bucket) -- this strategy never trades it in
                # v1. Skipped, not a configuration error: a station's full
                # bucket ladder legitimately includes buckets this strategy
                # will never touch, and `decision.py` would return None for
                # it regardless. Not registered, so it never appears in the
                # exclusive-bucket exposure accounting either.
                self.log.warning(
                    f"{instrument_id} is not an open-ended upper tail "
                    f"(lower_f={facts.lower_f}, upper_f={facts.upper_f}); v1 never "
                    "trades it, skipping subscription for this instrument.",
                )
                continue
            contract = MispricingContract(
                instrument_id=str(instrument_id),
                facts=facts,
                tick_size=float(instrument.price_increment),
                price_scale=(
                    self._config.price_scale_override
                    if self._config.price_scale_override is not None
                    else 1.0
                ),
            )
            self._contracts[str(instrument_id)] = contract
            self._nt_ids[str(instrument_id)] = instrument_id
            self._deadlines[str(instrument_id)] = _ns_to_datetime(instrument.expiration_ns)
            self.subscribe_order_book_depth(instrument_id)
            self.log.info(f"RunningExtremeLockStrategy subscribed {instrument_id}")

        self._risk = RiskManager(
            self._risk_limits(),
            self._contracts,
            refusals=self.refusals,
            exposure_view=self._shared_exposure_view,
            native_instrument_ids=self._nt_ids,
        )
        self._refusal_alerter = RefusalAlerter(self.refusals, site=str(self.id))
        self.subscribe_data(nws_climate_day_data_type(), client_id=NWS_BACKTEST_CLIENT_ID)

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
            transaction_cost_prob=cfg.transaction_cost_prob,
            allow_short=cfg.allow_short,
        )

    # ------------------------------------------------------------------
    # Data handlers
    # ------------------------------------------------------------------
    def on_order_book_depth(self, depth: OrderBookDepth10) -> None:
        iid = str(depth.instrument_id)
        if iid not in self._contracts:
            return
        quote = market_quote_from_depth(depth, include_ask_ladder=True)
        if quote is None:
            return
        self._quotes[iid] = quote
        self._evaluate_and_act(iid)

    def on_data(self, data: Data) -> None:
        if type(data) is not NwsClimateDay:
            return
        for iid, contract in self._contracts.items():
            if not contract.facts.applies_to(data.station, data.climate_day):
                continue
            self._observations[iid] = RunningExtremeObservation(
                station=data.station,
                climate_day=data.climate_day,
                tmax_f=data.tmax_f,
                tmin_f=data.tmin_f,
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
            # No exit/flatten signal exists for this strategy beyond
            # settlement halt -- see the module docstring: it holds through
            # settlement once entered, per the design brief's holding-period
            # section. Nothing to flatten if never entered.
            return

        assert self._risk is not None  # built in on_start, before any data can arrive
        decision = evaluate_instrument(
            contract=contract,
            quote=quote,
            observation=observation,
            now=now,
            model_p_table=MEASURED_MARGIN_MODEL_P,
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
        observation: RunningExtremeObservation,
        now: dt.datetime,
        current_qty: float,
    ) -> None:
        nt_id = self._nt_ids[contract.instrument_id]
        if self.cache.orders_open(instrument_id=nt_id):
            self.log.debug(f"skip {contract.instrument_id}: working order exists")
            return
        # LONG_YES only -- decision.py never returns any other intent. A
        # delta below 1 lot means we are already at or past target size, and
        # this strategy never reduces (no exit signal exists in v1).
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
        # No post-only, no maker rebate, per the design brief.
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

        See `ForecastMispricingStrategy._report_refusals` for why this is
        cheap by design (`AlertState` dedupes).
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
