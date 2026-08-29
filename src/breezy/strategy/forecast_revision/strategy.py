"""``ForecastRevisionStrategy`` -- trading unabsorbed NWS forecast revisions.

Trades the gap between how far a forecast revision SHOULD move a weather-bucket
binary option's probability and how far the book has actually moved since that
revision published. This is the Nautilus-facing half of the split: lifecycle,
subscriptions, event handlers and order construction live here; the preserved
decision math and the revision bookkeeping live in
:mod:`breezy.strategy.forecast_revision.decision`.

NO FORECAST INGESTION EXISTS IN BREEZY -- READ THIS BEFORE WIRING A RUN
------------------------------------------------------------------------
Breezy ingests only OBSERVED climate days
(``breezy.domain.nws_climate_day.NwsClimateDay``). There is no forecast source.
This strategy therefore takes a
:class:`~breezy.strategy.weather_common.forecast_source.ForecastSource` as a
REQUIRED constructor argument -- never a config field, never defaulted, never
constructed internally. Passing ``None`` (or omitting it) is refused at
construction; no code path here derives a forecast from ``NwsClimateDay.tmax_f``
or any other settlement-derived value, and none should ever be added.

This strategy is the one most sensitive to that seam: it trades REVISIONS, so
it needs successive publications with truthful, distinct ``published_at`` values
and a live ``horizon_hours``. A ``ForecastSource`` that returns a constant
snapshot produces no revisions and this strategy will correctly never trade.

WHAT CHANGED FROM THE OPERATOR'S BUNDLE, AND WHY
--------------------------------------------------
The bundle this replaces was a single 1882-line file concatenating eight
modules, seven of which were byte-identical to the sibling
``calibration_mean_reversion_strategy.py`` bundle and near-identical to the
already-split ``breezy.strategy.weather_common``. Those seven are not
duplicated here; only the unique decision section was ported.

* **The construction crash is fixed.** The bundle ended ``__init__`` with
  ``self.config: ForecastRevisionConfig = config`` after
  ``super().__init__(config)``. ``Actor.config`` is a read-only Cython
  ``getset_descriptor``, so that line raises ``AttributeError: attribute
  'config' of 'nautilus_trader.common.actor.Actor' objects is not writable``.
  The base class already stores it; the typed handle here is ``self._config``.
* **Revision detection moved from PUSH to PULL.** See the ``decision`` module
  docstring -- this is the one structural adaptation, and it is reported rather
  than hidden.
* **The data seam is fixed.** The bundle subscribed to its own
  ``NWSForecastUpdate*`` / ``NWSObservation*`` topics with ``nws_client_id``
  defaulting to ``"NWS"``; the harness publishes ``NwsClimateDay*`` on
  ``NWS_BACKTEST_CLIENT_ID`` (``ClientId("BREEZY-NWS")``). Neither half raises:
  the topics do not match under ``is_matching_py``, and a client-id mismatch
  drops the ``SubscribeData`` command with one ERROR log line while the run
  completes looking healthy.
* **The fabricated settlement clock is gone.** The bundle derived hours-to-
  settlement from a hardcoded 23:59 ``"America/Chicago"`` per contract, wrong
  for four of the venue's five cities. Settlement here is the native
  ``InstrumentClose`` (``breezy.runtime.backtest_harness``); the only horizon
  read is ``ForecastSnapshot.horizon_hours``.
* **Bucket bounds come from real venue facts**, the Nautilus shim and its
  ``_Dummy*`` stand-ins are gone, depth is subscribed alongside quotes, blind
  ``except Exception`` handlers are gone, and stop-time flattening is the
  native ``StrategyConfig.manage_stop`` rather than a hand-rolled duplicate.
  Same rationale as the two sibling packages.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.trading.strategy import Strategy

from breezy.domain.nws_climate_day import NwsClimateDay
from breezy.domain.weather_bucket_facts import Measure, read_weather_bucket_facts
from breezy.ingest.nws_actor import nws_climate_day_data_type
from breezy.runtime.backtest_feed import NWS_BACKTEST_CLIENT_ID
from breezy.strategy.forecast_revision.config import ForecastRevisionConfig
from breezy.strategy.forecast_revision.decision import RevisionState, evaluate_instrument
from breezy.strategy.weather_common.bucket_contract import MispricingContract
from breezy.strategy.weather_common.forecast_source import (
    ForecastSource,
    MissingForecastSourceError,
)
from breezy.strategy.weather_common.models import ForecastSnapshot, MarketQuote, SideIntent
from breezy.strategy.weather_common.probability import (
    ForecastErrorModel,
    HorizonSigmaParams,
    WeatherProbabilityEngine,
)
from breezy.strategy.weather_common.risk import PortfolioSnapshot, RiskLimits, RiskManager

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nautilus_trader.core.data import Data
    from nautilus_trader.model.data import OrderBookDepth10, QuoteTick
    from nautilus_trader.model.identifiers import InstrumentId
    from nautilus_trader.model.orders.base import Order

    from breezy.strategy.weather_common.models import SignalDecision

__all__ = ["ForecastRevisionStrategy"]


class ForecastRevisionStrategy(Strategy):
    """Buys/sells YES when the book has not yet absorbed a forecast revision."""

    def __init__(
        self,
        config: ForecastRevisionConfig,
        forecast_source: ForecastSource,
    ) -> None:
        super().__init__(config)
        if forecast_source is None:
            raise MissingForecastSourceError(
                "ForecastRevisionStrategy requires an explicit ForecastSource; "
                "Breezy ingests no forecast data, so there is no default to fall back to. "
                "See breezy.strategy.weather_common.forecast_source for the contract.",
            )
        self._forecast_source = forecast_source
        # NOT `self.config` -- that is a read-only native attribute the base
        # class already populated; assigning it raises AttributeError.
        self._config: ForecastRevisionConfig = config
        self._engine = WeatherProbabilityEngine(
            ForecastErrorModel(
                distribution=config.error_distribution,
                student_t_df=config.student_t_df,
                sigma_params=HorizonSigmaParams(
                    sigma_floor_f=config.sigma_floor_f,
                    sigma_per_sqrt_hour_f=config.sigma_per_sqrt_hour_f,
                ),
                p_floor=config.p_floor,
            ),
        )
        self._state = RevisionState(history_len=config.history_len)
        self._contracts: dict[str, MispricingContract] = {}
        self._nt_ids: dict[str, InstrumentId] = {}
        self._quotes: dict[str, MarketQuote] = {}
        self._risk: RiskManager | None = None

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
                    f"{instrument_id} measures {facts.measure.value!r}; this strategy's "
                    "probability model supports HIGH-measure buckets only",
                )
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
            self.subscribe_quote_ticks(instrument_id)
            self.subscribe_order_book_depth(instrument_id)
            self.log.info(f"ForecastRevisionStrategy subscribed {instrument_id}")

        self._risk = RiskManager(self._risk_limits(), self._contracts)
        self.subscribe_data(nws_climate_day_data_type(), client_id=NWS_BACKTEST_CLIENT_ID)

    def on_reset(self) -> None:
        self._quotes.clear()
        self._state.clear()

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
            stale_forecast_hours=cfg.stale_forecast_hours,
            stale_quote_minutes=cfg.stale_quote_minutes,
            transaction_cost_prob=cfg.transaction_cost_prob,
            allow_short=cfg.allow_short,
        )

    # ------------------------------------------------------------------
    # Data handlers
    # ------------------------------------------------------------------
    def on_quote_tick(self, tick: QuoteTick) -> None:
        iid = str(tick.instrument_id)
        if iid not in self._contracts:
            return
        self._quotes[iid] = MarketQuote(
            instrument_id=iid,
            bid=float(tick.bid_price),
            ask=float(tick.ask_price),
            bid_size=float(tick.bid_size),
            ask_size=float(tick.ask_size),
            ts_event=_ns_to_datetime(tick.ts_event),
        )
        self._evaluate_and_act(iid)

    def on_order_book_depth(self, depth: OrderBookDepth10) -> None:
        iid = str(depth.instrument_id)
        if iid not in self._contracts:
            return
        best_bid = depth.bids[0] if depth.bids else None
        best_ask = depth.asks[0] if depth.asks else None
        if best_bid is None or best_ask is None:
            return
        self._quotes[iid] = MarketQuote(
            instrument_id=iid,
            bid=float(best_bid.price),
            ask=float(best_ask.price),
            bid_size=float(best_bid.size),
            ask_size=float(best_ask.size),
            ts_event=_ns_to_datetime(depth.ts_event),
        )
        self._evaluate_and_act(iid)

    def on_data(self, data: Data) -> None:
        if type(data) is not NwsClimateDay:
            return
        if not data.is_final or not self._config.flatten_on_observation:
            return
        for iid, contract in self._contracts.items():
            if contract.facts.applies_to(data.station, data.climate_day):
                self._flatten(iid, "observation_received")

    # ------------------------------------------------------------------
    # Decision + execution
    # ------------------------------------------------------------------
    def _evaluate_and_act(self, instrument_id: str) -> None:
        contract = self._contracts[instrument_id]
        quote = self._quotes.get(instrument_id)
        if quote is None:
            return
        now = self.clock.utc_now()
        forecast = self._forecast_source.snapshot(
            station=contract.facts.settlement_station,
            climate_day=contract.facts.climate_day,
            now=now,
        )
        if forecast is None:
            return

        # The push -> pull adaptation: a pulled snapshot with a newer
        # `published_at` IS the revision event the bundle received on the wire.
        scale = (
            self._config.price_scale_override
            if self._config.price_scale_override is not None
            else contract.price_scale
        )
        self._state.observe(
            contract=contract,
            forecast=forecast,
            market_mid_p=quote.implied_mid(scale),
        )

        if forecast.horizon_hours <= self._config.halt_hours_before_settlement:
            self._flatten(instrument_id, "settlement_halt")
            return

        current_qty = float(self.portfolio.net_position(self._nt_ids[instrument_id]))
        decision = evaluate_instrument(
            contract=contract,
            quote=quote,
            now=now,
            current_qty=current_qty,
            state=self._state,
            engine=self._engine,
            cfg=self._config,
        )
        if decision is None:
            return
        if decision.intent is SideIntent.FLAT:
            if abs(current_qty) > 1e-9:
                self._flatten(instrument_id, decision.reason)
            return
        self._maybe_submit(contract, quote, decision, forecast, now, current_qty)

    def _maybe_submit(
        self,
        contract: MispricingContract,
        quote: MarketQuote,
        decision: SignalDecision,
        forecast: ForecastSnapshot,
        now: datetime,
        current_qty: float,
    ) -> None:
        nt_id = self._nt_ids[contract.instrument_id]
        if self.cache.orders_open(instrument_id=nt_id):
            self.log.debug(f"skip {contract.instrument_id}: working order exists")
            return
        target_qty = (
            decision.quantity if decision.intent is SideIntent.LONG_YES else -decision.quantity
        )
        delta = target_qty - current_qty
        if abs(delta) < 1.0:
            return

        forecast_age_hours = (now - forecast.published_at).total_seconds() / 3600.0
        assert self._risk is not None  # built in on_start, before any data can arrive
        risk_decision = self._risk.evaluate_order(
            contract=contract,
            signed_qty_delta=delta,
            hours_to_settlement=forecast.horizon_hours,
            forecast_age_hours=forecast_age_hours,
            edge=decision.edge,
            portfolio=self._portfolio_snapshot(),
            quote=quote,
        )
        if not risk_decision.allowed:
            self.log.info(
                f"RISK block {contract.instrument_id}: {risk_decision.reason} "
                f"edge={decision.edge:.3f}",
            )
            return
        self._submit_delta(contract, quote, risk_decision.clipped_quantity, decision)

    def _submit_delta(
        self,
        contract: MispricingContract,
        quote: MarketQuote,
        signed_delta: float,
        decision: SignalDecision,
    ) -> None:
        nt_id = self._nt_ids[contract.instrument_id]
        instrument = self.cache.instrument(nt_id)
        if instrument is None:
            self.log.error(f"instrument vanished from cache: {contract.instrument_id}")
            return
        side = OrderSide.BUY if signed_delta > 0 else OrderSide.SELL
        qty = instrument.make_qty(abs(signed_delta))
        if self._config.use_limit_orders:
            raw_px = quote.ask if signed_delta > 0 else quote.bid
            if raw_px is None:
                return
            adjust = self._config.limit_inside_ticks * contract.tick_size
            limit_px = raw_px - adjust if signed_delta > 0 else raw_px + adjust
            order = self.order_factory.limit(
                instrument_id=nt_id,
                order_side=side,
                quantity=qty,
                price=instrument.make_price(limit_px),
                time_in_force=TimeInForce.IOC,
            )
        else:
            order = self.order_factory.market(
                instrument_id=nt_id,
                order_side=side,
                quantity=qty,
            )
        self.submit_order(order)
        self.log.info(
            f"ORDER {contract.instrument_id} delta={signed_delta:+.1f} "
            f"intent={decision.intent.value} edge={decision.edge:.3f} reason={decision.reason}",
        )

    def _flatten(self, instrument_id: str, reason: str) -> None:
        nt_id = self._nt_ids[instrument_id]
        qty = float(self.portfolio.net_position(nt_id))
        if abs(qty) < 1e-9:
            return
        if self.cache.orders_open(instrument_id=nt_id):
            self.cancel_all_orders(nt_id)
        self.close_all_positions(nt_id)
        self.log.info(f"FLATTEN {instrument_id} qty={qty:.1f} reason={reason}")

    def _portfolio_snapshot(self) -> PortfolioSnapshot:
        position_qty = {
            iid: float(self.portfolio.net_position(nt_id)) for iid, nt_id in self._nt_ids.items()
        }
        pending_qty = {
            iid: _signed_open_order_qty(self.cache.orders_open(instrument_id=nt_id))
            for iid, nt_id in self._nt_ids.items()
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


def _ns_to_datetime(ts_event: int) -> datetime:
    return datetime.fromtimestamp(ts_event / 1_000_000_000, tz=UTC)


def _signed_open_order_qty(orders: list[Order]) -> float:
    total = 0.0
    for order in orders:
        total += float(order.signed_decimal_qty())
    return total
