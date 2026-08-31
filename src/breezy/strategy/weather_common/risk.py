"""Portfolio risk gating, carried over from the bundle's ``risk.py`` section.

The limits, the order-screening sequence (settlement halt -> stale forecast ->
minimum edge -> short permission -> quote tradability -> exclusivity ->
position/notional/count caps -> equity fraction) and every threshold are
unchanged from the operator's bundle. Only the "which contracts exist and how
are they grouped" plumbing changed: the bundle's ``WeatherContractRegistry``
is replaced by a plain ``Mapping[str, MispricingContract]`` the strategy
builds once, from real cached instruments, at ``on_start``.

One risk-grouping simplification, called out because it is a genuine
behaviour change from the bundle rather than a plumbing swap:
``mutually_exclusive_group`` here returns every OTHER contract sharing the
same ``event_key`` (station + climate day), full stop. The bundle
distinguished RANGE-kind siblings (strict partition) from ABOVE/BELOW
siblings (same-location, weaker check) via its own ``ContractKind``. Since
bucket bounds now come from real venue facts instead of a hand-authored kind
enum, and every bucket for one climate day is, in practice, a claim about the
same underlying temperature, this collapses to one rule: no two long-YES
positions on the same climate day at once. That is a *more* conservative
exclusivity check than the bundle's (it can only block more, never fewer,
redundant same-direction positions), so it changes no economic decision this
task exists to preserve -- but it is a deliberate simplification of
plumbing, not a hidden equivalence, and is reported as such.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from breezy.strategy.weather_common.refusals import SHORTS_DISABLED, RefusalCounter

if TYPE_CHECKING:  # pragma: no cover - typing only
    from breezy.strategy.weather_common.bucket_contract import MispricingContract
    from breezy.strategy.weather_common.models import MarketQuote

__all__ = [
    "PortfolioSnapshot",
    "RiskDecision",
    "RiskLimits",
    "RiskManager",
    "edge_after_costs",
]


@dataclass(slots=True)
class RiskLimits:
    max_position_contracts: float = 250.0
    max_event_notional: float = 1_000.0
    max_location_notional: float = 2_000.0
    max_simultaneous_positions: int = 12
    max_equity_fraction: float = 0.08
    min_model_edge: float = 0.04
    max_bid_ask_spread: float = 0.06
    min_liquidity_contracts: float = 25.0
    min_hours_to_settlement: float = 2.0
    halt_hours_before_settlement: float = 1.0
    stale_forecast_hours: float = 8.0
    stale_quote_minutes: float = 15.0
    transaction_cost_prob: float = 0.015  # fees + expected slippage in prob units
    #: FALSE, and it must stay false in every default construction path.
    #:
    #: This is not a conservative preference, it is the ONLY naked-short
    #: control in the system. `nautilus_trader==1.231.0` denies no naked short
    #: of its own: `risk/engine.pyx:974-985` exempts a position-REDUCING sell
    #: outright, and a position-OPENING sell is denied only by
    #: `CUM_NOTIONAL_EXCEEDS_FREE_BALANCE`, itself gated on
    #: `not allow_borrowing` -- and on a CASH account
    #: `CashAccount.balance_impact` returns +notional for a SELL, so the
    #: `(free + impact) < 0` gate cannot fire either. Nothing is behind this
    #: flag.
    #:
    #: The venue makes the same point economically: on a Polymarket CLOB you
    #: cannot sell tokens you do not hold -- "short YES" is spelled "buy NO",
    #: a different instrument with its own book (see
    #: `breezy.runtime.backtest_order_guard`).
    #:
    #: `True` is reachable only by writing it at a call site, which is an
    #: explicit operator act on the record. A test asserts the default on a
    #: bare `RiskLimits()` and on all three strategy configs.
    allow_short: bool = False
    allow_overlapping_exclusive_yes: bool = False


@dataclass(slots=True)
class PortfolioSnapshot:
    """A point-in-time view built fresh from the native cache/portfolio.

    Unlike the bundle's ``PortfolioSnapshot``, this is not a strategy-owned,
    incrementally-mutated ledger: the strategy re-derives it on every
    decision from ``Strategy.portfolio.net_position`` and
    ``Strategy.cache.orders_open`` (both native), so it can never drift from
    what Nautilus itself believes is true.
    """

    position_qty: dict[str, float] = field(default_factory=dict)  # signed YES qty
    pending_qty: dict[str, float] = field(default_factory=dict)
    equity: float = 10_000.0

    def net_qty(self, instrument_id: str) -> float:
        """Settled position PLUS signed working orders.

        The right quantity for every EXPOSURE question (notional caps,
        exclusivity, position caps): a working buy is exposure we have already
        committed to and must not double up on.

        The WRONG quantity for the close-only guard -- see
        :meth:`settled_qty`.
        """
        return self.position_qty.get(instrument_id, 0.0) + self.pending_qty.get(instrument_id, 0.0)

    def settled_qty(self, instrument_id: str) -> float:
        """Position actually HELD -- no working orders of any sign.

        The only quantity a sell can be netted against. `pending_qty` is
        signed and includes pending BUYS, so a working buy inflates
        :meth:`net_qty` and made a sell that opens a short look like a
        reduction (10 held + 50 working buy = 60, against which a 40-lot sell
        "reduces"; it opens a 30-lot naked short the moment it fills, and the
        buy may never fill at all).

        Symmetrically it excludes pending SELLS. That is a KNOWN second-order
        gap, recorded rather than papered over: two sells that are each within
        the settled long are jointly naked, and this method cannot see the
        first one. It is not fixable from `pending_qty`, which is a single
        SIGNED net per instrument -- a +50 net can be a 60-lot buy against a
        10-lot sell, so the sell component is not recoverable here. What
        covers it today: every strategy skips evaluation entirely while any
        order is working (`cache.orders_open`), and in backtests
        :class:`breezy.runtime.backtest_order_guard.BacktestOrderGuard` sums
        working sell quantity straight from the cache at submit time. The
        first of those is incidental and the second is backtest-only, so a
        change that widens the portfolio snapshot must re-examine this -- see
        the plan's P4.
        """
        return self.position_qty.get(instrument_id, 0.0)

    def open_position_count(self) -> int:
        return sum(1 for q in self.position_qty.values() if abs(q) > 1e-9)


@dataclass(slots=True)
class RiskDecision:
    allowed: bool
    reason: str
    clipped_quantity: float = 0.0


class RiskManager:
    def __init__(
        self,
        limits: RiskLimits,
        contracts: Mapping[str, MispricingContract],
        *,
        refusals: RefusalCounter | None = None,
    ) -> None:
        self.limits = limits
        self.contracts = contracts
        #: Shared with the strategy's DECISION layer, which refuses a
        #: `SHORT_YES` intent before it can reach here at all -- see
        #: `breezy.strategy.weather_common.refusals`. Optional so the pure
        #: screening tests need not construct one; a strategy always passes it.
        self.refusals = RefusalCounter() if refusals is None else refusals

    def quote_tradable(
        self, quote: MarketQuote, price_scale: float, now_ts_age_minutes: float,
    ) -> tuple[bool, str]:
        if quote.bid is None or quote.ask is None:
            return False, "missing_bid_ask"
        if quote.ask <= quote.bid:
            return False, "crossed_or_locked_ignored"
        spread = (quote.ask - quote.bid) * price_scale
        if spread > self.limits.max_bid_ask_spread:
            return False, f"spread_{spread:.3f}"
        liq = min(quote.bid_size or 0.0, quote.ask_size or 0.0)
        if liq < self.limits.min_liquidity_contracts:
            return False, "insufficient_liquidity"
        if now_ts_age_minutes > self.limits.stale_quote_minutes:
            return False, "stale_quote"
        return True, "ok"

    def event_notional(self, portfolio: PortfolioSnapshot, event_key: str) -> float:
        total = 0.0
        for contract in self.contracts.values():
            if contract.event_key != event_key:
                continue
            qty = abs(portfolio.net_qty(contract.instrument_id))
            total += qty * contract.contract_size
        return total

    def location_notional(self, portfolio: PortfolioSnapshot, location_id: str) -> float:
        total = 0.0
        for contract in self.contracts.values():
            if contract.location_id != location_id:
                continue
            total += abs(portfolio.net_qty(contract.instrument_id)) * contract.contract_size
        return total

    def mutually_exclusive_group(self, contract: MispricingContract) -> list[MispricingContract]:
        return [
            other
            for other in self.contracts.values()
            if other.instrument_id != contract.instrument_id
            and other.event_key == contract.event_key
        ]

    def exclusive_conflict(
        self,
        contract: MispricingContract,
        signed_qty_delta: float,
        portfolio: PortfolioSnapshot,
    ) -> bool:
        if self.limits.allow_overlapping_exclusive_yes:
            return False
        if signed_qty_delta <= 0:
            return False  # reducing or shorting YES is not a second long-YES
        for other in self.mutually_exclusive_group(contract):
            if portfolio.net_qty(other.instrument_id) > 1e-9:
                return True
        return False

    def evaluate_order(
        self,
        *,
        contract: MispricingContract,
        signed_qty_delta: float,
        hours_to_settlement: float,
        forecast_age_hours: float,
        edge: float,
        portfolio: PortfolioSnapshot,
        quote: MarketQuote,
    ) -> RiskDecision:
        limits = self.limits
        if hours_to_settlement < limits.halt_hours_before_settlement:
            return RiskDecision(False, "settlement_halt")
        if hours_to_settlement < limits.min_hours_to_settlement:
            return RiskDecision(False, "too_close_to_settlement")
        if forecast_age_hours > limits.stale_forecast_hours:
            return RiskDecision(False, "stale_forecast")
        if abs(edge) < limits.min_model_edge:
            return RiskDecision(False, "edge_below_minimum")
        # CLOSE-ONLY, and the only naked-short control there is (see
        # `RiskLimits.allow_short`). Netted against SETTLED position --
        # `settled_qty`, never `net_qty`: `net_qty` includes signed pending
        # quantity, so a working BUY inflated it and let a sell that opens a
        # short pass as a "reduction". A pending buy is not inventory.
        if (
            signed_qty_delta < 0
            and not limits.allow_short
            and portfolio.settled_qty(contract.instrument_id) + signed_qty_delta < -1e-9
        ):
            # Counted, because this refusal can silence a whole strategy: one
            # producing no trades because it is structurally disabled looks
            # exactly like one producing no trades because the market is
            # efficient. See `weather_common.refusals`.
            self.refusals.record(SHORTS_DISABLED)
            return RiskDecision(False, SHORTS_DISABLED)

        # PRESERVED DEFECT -- AWAITING AN OPERATOR RULING. DO NOT "FIX" SILENTLY.
        # The third argument is the quote's age in minutes, and it is hardcoded
        # to 0.0 here, so `quote_tradable`'s `stale_quote_minutes` check is
        # PERMANENTLY VACUOUS on this path: an arbitrarily stale quote passes.
        # WHAT THAT COSTS DIFFERS PER STRATEGY -- it is a dropped argument for
        # one caller and a total absence of quote-staleness protection for the
        # other two:
        #   * `forecast_mispricing` -- COVERED. It computes the real quote age
        #     (`age_min = (now - quote.ts_event) / 60`) and calls
        #     `quote_tradable` itself as an independent upstream gate before
        #     ever reaching here (`forecast_mispricing/decision.py:68-70`), so
        #     for this caller the 0.0 below is genuinely a dropped argument,
        #     not missing information.
        #   * `calibration_mean_reversion` -- NOT COVERED. It never calls
        #     `quote_tradable` anywhere, so the vacuous check below is its ONLY
        #     quote-staleness gate, i.e. it has none. (Do not be misled by
        #     `calibration_mean_reversion/decision.py:102`: that `age_min` is
        #     FORECAST age measured from `published_at`, gating
        #     `stable_forecast_minutes` -- a different quantity entirely.)
        #   * `forecast_revision` -- NOT COVERED, same as calibration: zero
        #     `quote_tradable` references in the package.
        # Carried over verbatim from the operator's bundle (the same hardcoded
        # 0.0, alongside an unused `quote_age_minutes` helper). Wiring the real
        # age in would start blocking orders that currently pass, which is an
        # economic change to live behaviour and is the operator's call, not this
        # integration's.
        ok, why = self.quote_tradable(quote, contract.price_scale, 0.0)
        if not ok:
            return RiskDecision(False, why)

        if self.exclusive_conflict(contract, signed_qty_delta, portfolio):
            return RiskDecision(False, "exclusive_bucket_conflict")

        projected = portfolio.net_qty(contract.instrument_id) + signed_qty_delta
        if abs(projected) > limits.max_position_contracts + 1e-9:
            room = limits.max_position_contracts - abs(portfolio.net_qty(contract.instrument_id))
            if room <= 0:
                return RiskDecision(False, "max_position")
            signed_qty_delta = room if signed_qty_delta > 0 else -room

        event_after = self.event_notional(portfolio, contract.event_key) + abs(
            signed_qty_delta,
        ) * contract.contract_size
        if event_after > limits.max_event_notional:
            return RiskDecision(False, "max_event_notional")

        loc_after = self.location_notional(portfolio, contract.location_id) + abs(
            signed_qty_delta,
        ) * contract.contract_size
        if loc_after > limits.max_location_notional:
            return RiskDecision(False, "max_location_notional")

        if (
            portfolio.open_position_count() >= limits.max_simultaneous_positions
            and abs(portfolio.net_qty(contract.instrument_id)) < 1e-9
        ):
            return RiskDecision(False, "max_simultaneous_positions")

        order_notional = abs(signed_qty_delta) * contract.contract_size
        if portfolio.equity > 0 and order_notional > limits.max_equity_fraction * portfolio.equity:
            clipped = (limits.max_equity_fraction * portfolio.equity) / max(
                contract.contract_size, 1e-9,
            )
            if clipped < 1.0:
                return RiskDecision(False, "equity_fraction")
            signed_qty_delta = clipped if signed_qty_delta > 0 else -clipped

        return RiskDecision(True, "ok", clipped_quantity=signed_qty_delta)


def edge_after_costs(
    *,
    model_p: float,
    bid_p: float | None,
    ask_p: float | None,
    intent_long_yes: bool,
    cost: float,
) -> float | None:
    """Executable edge versus bid/ask, not midpoint.

    Long YES edge = model_p - ask_p - cost
    Short YES edge = bid_p - model_p - cost
    """
    if intent_long_yes:
        if ask_p is None:
            return None
        return model_p - ask_p - cost
    if bid_p is None:
        return None
    return bid_p - model_p - cost
