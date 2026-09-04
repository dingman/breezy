"""Portfolio risk gating, carried over from the bundle's ``risk.py`` section.

The limits, the order-screening sequence (settlement halt -> stale signal
(forecast or observation, see `breezy.strategy.weather_common.freshness`) ->
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
from typing import TYPE_CHECKING, Final

from breezy.strategy.weather_common.freshness import SignalKind
from breezy.strategy.weather_common.ladder import available_ask_depth
from breezy.strategy.weather_common.refusals import SHORTS_DISABLED, RefusalCounter

if TYPE_CHECKING:  # pragma: no cover - typing only
    from breezy.strategy.weather_common.bucket_contract import MispricingContract
    from breezy.strategy.weather_common.freshness import SignalFreshness
    from breezy.strategy.weather_common.models import MarketQuote

__all__ = [
    "COUNTED_REFUSAL_REASONS",
    "EQUITY_NONPOSITIVE",
    "EQUITY_UNOBSERVED",
    "PortfolioSnapshot",
    "RiskDecision",
    "RiskLimits",
    "RiskManager",
    "SharedExposureView",
    "edge_after_costs",
]

#: No account balance was ever OBSERVED, so there is no denominator to size
#: the equity-fraction cap against. Distinct from a measured zero below:
#: `equity` is `float | None` precisely because a float cannot say this.
EQUITY_UNOBSERVED: Final[str] = "equity_unobserved"

#: A balance WAS observed, and it is zero or negative.
#:
#: UNVERIFIED, recorded rather than asserted: whether the venue's
#: `currentBalance` (what `Account.balance_total` reports on this
#: `AccountType.CASH` account) includes the value of open positions. Its
#: sibling `assetNotional` is a separate field nothing in Breezy reads. So a
#: zero here is at least as plausibly "fully deployed and solvent" as
#: "drained", and this reason deliberately says only what was measured.
#: Refusing a NEW buy is correct under either reading, which is why the
#: uncertainty does not have to be resolved to act on it.
EQUITY_NONPOSITIVE: Final[str] = "equity_nonpositive"

#: Every distinct key `RiskManager.evaluate_order` can record on the
#: `RefusalCounter` it is passed. Fixed and finite by construction -- see
#: `RiskManager._counted_reason`, which canonicalizes `quote_tradable`'s one
#: dynamic-valued reason (`f"spread_{spread:.3f}"`) to `"wide_spread"`
#: before it ever reaches `.record`, so this set can never grow with market
#: noise the way an unmapped float-suffixed key would (see the
#: `weather_common.refusals` module docstring for why that matters: a
#: refusal reason nobody can bound is a memory leak, not a counter).
COUNTED_REFUSAL_REASONS: Final[frozenset[str]] = frozenset(
    {
        "settlement_halt",
        "too_close_to_settlement",
        "stale_forecast",
        "stale_observation",
        # Decision-layer reason (`weather_common/refusals.py`), NOT emitted
        # by `RiskManager.evaluate_order`, which has no observation value to
        # judge -- see `docs/plans/BL24_LIVE_RT_2026-09-04.md` amendment A4.
        # Counted here so the decision layer's counter shares the one fixed,
        # finite reason set.
        "observation_unavailable",
        "future_signal",
        "observation_limit_unset",
        "edge_below_minimum",
        SHORTS_DISABLED,
        "missing_bid_ask",
        "crossed_or_locked_ignored",
        "wide_spread",
        "insufficient_liquidity",
        "future_quote",
        "stale_quote",
        "exclusive_bucket_conflict",
        "max_position",
        "max_event_notional",
        "max_location_notional",
        "max_simultaneous_positions",
        EQUITY_UNOBSERVED,
        EQUITY_NONPOSITIVE,
        "equity_fraction",
        "insufficient_depth",
    },
)

#: The counted refusal reason for each `SignalKind`'s staleness check --
#: `RiskManager.evaluate_order`'s stale-signal step reports one of these two,
#: never the bare `"stale"`, so a block log names WHICH bound was breached.
_STALE_REASON: Final[dict[SignalKind, str]] = {
    SignalKind.FORECAST: "stale_forecast",
    SignalKind.OBSERVATION: "stale_observation",
}


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
    #: LIVENESS backstop only -- decay/revision risk is owned by each
    #: strategy's decision.py; do not tighten this to express confidence in a
    #: print. `None` (the default, and the only value any shipped strategy
    #: ships) means "unset", and unset REFUSES every observation-kind order
    #: (see `RiskManager.evaluate_order`'s `observation_limit_unset` branch)
    #: rather than falling back to `stale_forecast_hours` or admitting the
    #: order -- see `freshness.py` for why forecast and observation share one
    #: screening step but never one bound.
    stale_observation_hours: float | None = None
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

    def max_signal_age_hours(self, kind: SignalKind) -> float | None:
        """The staleness bound for one `SignalKind`.

        `FORECAST` always resolves to `stale_forecast_hours`, which is a
        plain `float` and therefore never `None`. `OBSERVATION` resolves to
        `stale_observation_hours`, which defaults `None` -- fail-closed, not
        a silent fallback to the forecast bound.
        """
        if kind is SignalKind.FORECAST:
            return self.stale_forecast_hours
        return self.stale_observation_hours


@dataclass(slots=True)
class PortfolioSnapshot:
    """A point-in-time view built fresh from the native cache/portfolio.

    Unlike the bundle's ``PortfolioSnapshot``, this is not a strategy-owned,
    incrementally-mutated ledger: the strategy re-derives it on every
    decision from ``Strategy.portfolio.net_position`` and ``Strategy.cache``
    (both native), so it can never drift from what Nautilus itself believes
    is true.

    The cache query is ``breezy.strategy.weather_common.inflight``'s
    ``working_orders`` -- ``cache.orders(...)`` filtered on
    ``not order.is_closed`` -- and NOT ``cache.orders_open(...)``, which
    excludes ``INITIALIZED`` and ``SUBMITTED`` and so read an empty book
    inside the submit -> ACCEPTED window (T-1).
    """

    position_qty: dict[str, float] = field(default_factory=dict)  # signed YES qty
    pending_qty: dict[str, float] = field(default_factory=dict)
    #: Account equity as OBSERVED, or `None` for never observed. NOT a float
    #: with a sentinel value: `float` cannot express "unobserved", and this
    #: field defaulted to a literal `10_000.0` that the equity-fraction cap
    #: then sized itself against as though somebody had counted the money.
    #: `None` is the default because the absence of an observation is the
    #: correct starting state, and every read of it is forced to say what it
    #: does about that (T-4). Populate it from
    #: `breezy.strategy.weather_common.equity.observed_equity`, which is the
    #: only reader; never from a config constant, and never with an
    #: `or`-default, which type-checks clean and silently reinstates the
    #: fabrication (pinned by `test_equity_observability_guard.py`).
    equity: float | None = None

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
        10-lot sell, so the sell component is not recoverable here.

        WHAT COVERS IT: exactly one thing, at submit time, in BOTH modes --
        :class:`breezy.runtime.backtest_order_guard.BacktestOrderGuard`, which
        sums working SELL quantity straight from the cache rather than from
        any signed net. `install_live_order_guard` wires that same class onto
        a live `MessageBus`, so it is not backtest-only; this docstring
        previously said it was, and that was stale.

        It is the ONLY cover, and this docstring previously claimed two.
        Neither of the other candidates is one. The strategies' in-flight
        gate read the SAME query this snapshot did, so the pair was one query
        with one hole, not two independent covers. And the gate never guarded
        the FLAT path at all: `_flatten` goes straight to
        `close_all_positions` without consulting it (T-1 removed the only
        query that path ever made, a cancel pre-filter, because Nautilus's own
        `cancel_all_orders` already asks the wider question).

        T-1 widened the query behind `pending_qty` to include INITIALIZED and
        SUBMITTED (`breezy.strategy.weather_common.inflight`). It deliberately
        did NOT change the REPRESENTATION: `pending_qty` is still a signed
        net and still cannot express the jointly-naked case, so this gap is
        exactly as open as it was. `settled_qty` itself is unchanged, and
        remains the only quantity a sell may net against. A change that splits
        `pending_qty` into buy and sell legs is what would close it.
        """
        return self.position_qty.get(instrument_id, 0.0)

    def open_position_count(self) -> int:
        """Instruments occupying a position SLOT -- settled OR pending.

        It read `position_qty.values()` alone (T-3), which is settled-only
        -- a native `Position` exists only after a FILL -- so the one
        consumer of this count, the `max_simultaneous_positions`
        refusal, was blind to every order still in flight while its sibling
        `pending_qty` (the field T-1 widened to include INITIALIZED and
        SUBMITTED) sat unread in this same snapshot.

        WHAT THAT COST: cap 12, all instruments flat, a depth/quote burst
        delivers ticks for 20 contracts on ONE handler thread, so all 20
        evaluate before any fill returns. The per-instrument in-flight gate
        is keyed on *that* instrument and cannot see the other 19; this count
        returned 0 on every pass, so the cap never bound and 20 BUYs went out
        against a cap of 12.

        Iterated over the UNION of both key sets, never one dict's
        `.values()`: the dicts carry different keys, so either alone
        under-counts (`position_qty` misses the purely in-flight
        instruments, `pending_qty` the purely settled ones). An instrument
        present in BOTH dicts is one key in that union and so counts exactly
        once, never twice.

        DELIBERATELY NOT `net_qty`, AND DELIBERATELY INCONSISTENT WITH IT.
        Do not harmonise this back. Every other cap asks "how much am I
        COMMITTED TO?", where signed netting is the right arithmetic. This
        one asks "how many contracts am I SIMULTANEOUSLY IN?", where it is
        not: a slot is occupied by ANY exposure, settled OR pending, and a
        settled long with a fully-offsetting working sell holds its slot.

        WHY THE NETTING READING IS WRONG HERE. Netting frees the slot on the
        strength of a fill that has not happened. The sell may be rejected,
        cancelled, or simply rest unfilled -- and on these weather markets
        resting unfilled is the NORMAL case, not the tail: the measured
        median top-of-book bid is ~0.3 contracts. Free the slot on that
        assumption and the strategy opens a 13th position against a cap of
        12, which is the same defect class as the T-3 bug above -- a limit
        relaxed on state that has not happened yet. A position you are
        TRYING to exit is still exposure until the fill lands.

        ASSUMPTION, recorded as one. `pending_qty` is a SIGNED net, so in
        principle a BUY and a SELL could cancel to zero and hide a slot from
        the `pending_qty` term. They cannot while T-1's class A gate holds,
        which permits at most one working order per instrument -- see
        `docs/plans/T1_STRATEGY_INFLIGHT_BLINDNESS_2026-09-02.md` D5, which
        defers the `pending_buy_qty`/`pending_sell_qty` split on exactly that
        ground. Whoever allows concurrent working orders per instrument must
        revisit D5 AND this line in the same change.
        """
        instrument_ids = self.position_qty.keys() | self.pending_qty.keys()
        return sum(
            1
            for iid in instrument_ids
            if abs(self.position_qty.get(iid, 0.0)) > 1e-9
            or abs(self.pending_qty.get(iid, 0.0)) > 1e-9
        )


@dataclass(slots=True)
class RiskDecision:
    allowed: bool
    reason: str
    clipped_quantity: float = 0.0


class SharedExposureView:
    """Shared max-payout exposure registry for strategies in one composition root."""

    def __init__(self) -> None:
        self._contracts: dict[str, MispricingContract] = {}
        self._native_instrument_ids: dict[str, object] = {}

    def register(
        self,
        contracts: Mapping[str, MispricingContract],
        native_instrument_ids: Mapping[str, object] | None = None,
    ) -> None:
        self._contracts.update(contracts)
        if native_instrument_ids is not None:
            self._native_instrument_ids.update(native_instrument_ids)

    def instrument_ids(
        self,
        local_instrument_ids: Mapping[str, object],
    ) -> dict[str, object]:
        instrument_ids = dict(local_instrument_ids)
        instrument_ids.update(self._native_instrument_ids)
        return instrument_ids

    def event_notional(self, portfolio: PortfolioSnapshot, event_key: str) -> float:
        total = 0.0
        for contract in self._contracts.values():
            if contract.event_key != event_key:
                continue
            total += abs(portfolio.net_qty(contract.instrument_id)) * contract.contract_size
        return total

    def location_notional(self, portfolio: PortfolioSnapshot, location_id: str) -> float:
        total = 0.0
        for contract in self._contracts.values():
            if contract.location_id != location_id:
                continue
            total += abs(portfolio.net_qty(contract.instrument_id)) * contract.contract_size
        return total

    def mutually_exclusive_group(
        self, contract: MispricingContract,
    ) -> list[MispricingContract]:
        return [
            other
            for other in self._contracts.values()
            if other.instrument_id != contract.instrument_id
            and other.event_key == contract.event_key
        ]


class RiskManager:
    def __init__(
        self,
        limits: RiskLimits,
        contracts: Mapping[str, MispricingContract],
        *,
        refusals: RefusalCounter | None = None,
        exposure_view: SharedExposureView | None = None,
        native_instrument_ids: Mapping[str, object] | None = None,
    ) -> None:
        self.limits = limits
        self.contracts = contracts
        self._exposure_view = SharedExposureView() if exposure_view is None else exposure_view
        self._exposure_view.register(contracts, native_instrument_ids)
        #: Shared with the strategy's DECISION layer, which refuses a
        #: `SHORT_YES` intent before it can reach here at all -- see
        #: `breezy.strategy.weather_common.refusals`. Optional so the pure
        #: screening tests need not construct one; a strategy always passes it.
        self.refusals = RefusalCounter() if refusals is None else refusals

    def instrument_ids(self, local_instrument_ids: Mapping[str, object]) -> dict[str, object]:
        return self._exposure_view.instrument_ids(local_instrument_ids)

    def quote_tradable(
        self, quote: MarketQuote, price_scale: float, now_ts_age_minutes: float,
    ) -> tuple[bool, str]:
        if quote.bid is None and quote.ask is None:
            return False, "missing_bid_ask"
        if quote.bid is not None and quote.ask is not None:
            if quote.ask <= quote.bid:
                return False, "crossed_or_locked_ignored"
            spread = (quote.ask - quote.bid) * price_scale
            if spread > self.limits.max_bid_ask_spread:
                return False, f"spread_{spread:.3f}"
            liq = min(quote.bid_size or 0.0, quote.ask_size or 0.0)
        else:
            # One-sided book: spread is undefined, not ask-minus-zero. A
            # long-only taker buys at the ask; an absent bid is not a 0.00
            # price and is not a wide-spread refusal. Liquidity is the
            # populated side.
            if quote.ask is not None:
                liq = quote.ask_size or 0.0
            else:
                liq = quote.bid_size or 0.0
        if liq < self.limits.min_liquidity_contracts:
            return False, "insufficient_liquidity"
        # `now_ts_age_minutes` is MINUTES, matching `stale_quote_minutes` --
        # unit proof at the call site in `evaluate_order`. NEGATIVE here means
        # `quote.ts_event` is AHEAD of `now`: clock skew or a bad feed
        # timestamp, not freshness. Checked as its own bounded reason and
        # BEFORE the staleness check below, which only ever fires on the
        # positive side of zero -- without this, the more wrong (more
        # negative) the timestamp, the "fresher" the quote looks, and the
        # staleness gate fails open forever on that input (BL-9).
        if now_ts_age_minutes < 0:
            return False, "future_quote"
        if now_ts_age_minutes > self.limits.stale_quote_minutes:
            return False, "stale_quote"
        return True, "ok"

    def event_notional(self, portfolio: PortfolioSnapshot, event_key: str) -> float:
        return self._exposure_view.event_notional(portfolio, event_key)

    def location_notional(self, portfolio: PortfolioSnapshot, location_id: str) -> float:
        return self._exposure_view.location_notional(portfolio, location_id)

    def mutually_exclusive_group(self, contract: MispricingContract) -> list[MispricingContract]:
        return self._exposure_view.mutually_exclusive_group(contract)

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

    @staticmethod
    def _counted_reason(reason: str) -> str:
        """Bounded `RefusalCounter` key for a raw `evaluate_order` reason.

        `quote_tradable` returns `f"spread_{spread:.3f}"` as the
        outward-facing reason (kept verbatim on the returned `RiskDecision`
        -- an operator reading a block log wants the measured spread), but
        that string carries the spread VALUE and must never become a
        counter key: an unbounded, float-suffixed key space is a memory leak
        grown by market noise, not a `RefusalCounter` (see the
        `weather_common.refusals` module docstring). Every other reason this
        class produces is already one of the fixed strings in
        `COUNTED_REFUSAL_REASONS` and passes through unchanged.
        """
        if reason.startswith("spread_"):
            return "wide_spread"
        return reason

    def _refuse(self, reason: str) -> RiskDecision:
        """Record `reason` on the counter, then return the refusal.

        Every call site inside `evaluate_order` refuses an order the
        strategy already FORMED and tried to submit: `evaluate_order` is
        invoked once per signal, only after `<strategy>.decision.
        evaluate_instrument` has already returned a non-`None`, non-`FLAT`
        `SignalDecision` (see e.g.
        `calibration_mean_reversion.strategy._evaluate_and_act`, which
        returns early on `None`/`FLAT` and calls `_maybe_submit` ->
        `evaluate_order` only otherwise). That is the line this module
        draws: a decision-layer gate that fires BEFORE any signal exists can
        be ordinary market conditions (no opportunity), not a gag -- but
        every refusal returned from THIS method blocks an order the
        strategy actually tried to place, so every one of them counts. See
        `breezy.strategy.weather_common.refusals` for why that distinction
        matters and `COUNTED_REFUSAL_REASONS` for the fixed set this can
        record.
        """
        self.refusals.record(self._counted_reason(reason))
        return RiskDecision(False, reason)

    def evaluate_order(
        self,
        *,
        contract: MispricingContract,
        signed_qty_delta: float,
        hours_to_settlement: float,
        signal_age: SignalFreshness,
        edge: float,
        portfolio: PortfolioSnapshot,
        quote: MarketQuote,
        quote_age_minutes: float,
    ) -> RiskDecision:
        limits = self.limits
        if hours_to_settlement < limits.halt_hours_before_settlement:
            return self._refuse("settlement_halt")
        if hours_to_settlement < limits.min_hours_to_settlement:
            return self._refuse("too_close_to_settlement")
        # For FORECAST this reduces algebraically to the pre-change check
        # (`forecast_age_hours > limits.stale_forecast_hours`), at the same
        # sequence position: `max_signal_age_hours(FORECAST)` always returns
        # `stale_forecast_hours`, a plain `float`, so the `is None` branch
        # below is unreachable for a forecast signal. See
        # `test_forecast_age_exactly_at_the_stale_forecast_boundary_is_accepted`
        # for the equivalence pin.
        max_age_hours = limits.max_signal_age_hours(signal_age.kind)
        if max_age_hours is None:
            return self._refuse("observation_limit_unset")
        # `signal_age.age_hours` NEGATIVE means the evidence is timestamped
        # AHEAD of the decision clock: clock skew or a leaked-future signal,
        # not freshness. Checked as its own bounded reason and BEFORE the
        # staleness check below, which only ever fires on the positive side
        # of zero -- without this, the more wrong (more negative) the
        # timestamp, the "fresher" the signal looks, and the staleness gate
        # fails open forever on that input. Same shape as `quote_tradable`'s
        # `now_ts_age_minutes < 0` guard (BL-9); this is its forecast-signal
        # counterpart (BL-15).
        if signal_age.age_hours < 0:
            return self._refuse("future_signal")
        if signal_age.age_hours > max_age_hours:
            return self._refuse(_STALE_REASON[signal_age.kind])
        if abs(edge) < limits.min_model_edge:
            return self._refuse("edge_below_minimum")
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
            return self._refuse(SHORTS_DISABLED)

        # One-sided books are allowed through quote_tradable (spread is
        # undefined, not ask-minus-zero). The executable side still has to
        # exist: a BUY takes the ask, a sell hits the bid.
        if signed_qty_delta > 0 and quote.ask is None:
            return self._refuse("missing_bid_ask")
        if signed_qty_delta < 0 and quote.bid is None:
            return self._refuse("missing_bid_ask")

        # Unit proof: callers pass minutes, matching `stale_quote_minutes`.
        ok, why = self.quote_tradable(quote, contract.price_scale, quote_age_minutes)
        if not ok:
            return self._refuse(why)

        if self.exclusive_conflict(contract, signed_qty_delta, portfolio):
            return self._refuse("exclusive_bucket_conflict")

        projected = portfolio.net_qty(contract.instrument_id) + signed_qty_delta
        if abs(projected) > limits.max_position_contracts + 1e-9:
            room = limits.max_position_contracts - abs(portfolio.net_qty(contract.instrument_id))
            if room <= 0:
                return self._refuse("max_position")
            signed_qty_delta = room if signed_qty_delta > 0 else -room

        event_after = self.event_notional(portfolio, contract.event_key) + abs(
            signed_qty_delta,
        ) * contract.contract_size
        if event_after > limits.max_event_notional:
            return self._refuse("max_event_notional")

        loc_after = self.location_notional(portfolio, contract.location_id) + abs(
            signed_qty_delta,
        ) * contract.contract_size
        if loc_after > limits.max_location_notional:
            return self._refuse("max_location_notional")

        if (
            portfolio.open_position_count() >= limits.max_simultaneous_positions
            and abs(portfolio.net_qty(contract.instrument_id)) < 1e-9
        ):
            return self._refuse("max_simultaneous_positions")

        # EQUITY, BUY SIDE ONLY -- the WHOLE block, not merely the two
        # refusals below (T-4).
        #
        # Gating the whole block is a correctness requirement of the `None`
        # type, not a stylistic extension: this block's own predicate used to
        # be `portfolio.equity > 0`, which raises `TypeError` on `None`, so a
        # reducing sell would die at the gate rather than pass it. And that
        # predicate was itself fail-open -- false at `equity == 0.0`, so the
        # one balance that should stop a buy was the one that skipped the cap
        # entirely and let the order through at FULL size.
        #
        # It also closes a PRE-EXISTING exit trap, and that is a real
        # behaviour change: `signed_qty_delta = clipped if ... else -clipped`
        # clipped SELLS too, so a reducing sell of 200 against an observed
        # equity of $10 clipped to 0.8, fell below one contract, and was
        # refused `equity_fraction`. That is the same failure the depth clip
        # below explicitly declines to create ("clipping an exit to that would
        # trap positions the close-only guard exists to let out"), and it bit
        # hardest on a small account, which is exactly when getting out
        # matters. With `allow_short=False` every sell reaching here has
        # already been netted against `settled_qty` and is therefore
        # REDUCING, so letting it past this cap cannot open exposure.
        #
        # The resulting state -- new buys refused, exits allowed -- is
        # reduce-only, and it is monotonically de-risking. Its one genuine
        # defect is silence, which is why both refusals below carry a
        # timestamped, state-naming note into the strategy's log (see
        # `weather_common.equity.reduce_only_refusal_note`).
        if signed_qty_delta > 0:
            equity = portfolio.equity
            if equity is None:
                return self._refuse(EQUITY_UNOBSERVED)
            if equity <= 0.0:
                return self._refuse(EQUITY_NONPOSITIVE)
            order_notional = signed_qty_delta * contract.contract_size
            if order_notional > limits.max_equity_fraction * equity:
                clipped = (limits.max_equity_fraction * equity) / max(
                    contract.contract_size, 1e-9,
                )
                if clipped < 1.0:
                    return self._refuse("equity_fraction")
                signed_qty_delta = clipped

        # DEPTH, last and tightest (BL-25 D2). Every clip above is a POLICY
        # cap -- how much we are willing to hold. This one is a FACT about the
        # book: how much is actually offered. It runs last so a tighter policy
        # cap always still binds, and it can only ever reduce the order.
        #
        # BUY SIDE ONLY, deliberately. A buy takes the ask, and `MarketQuote`
        # carries an ask ladder (`ask_ladder`, else top-of-book) that
        # `weather_common.ladder.available_ask_depth` reads. A sell takes the
        # BID, for which there is no ladder field at all, and the measured
        # top-of-book bid on this venue is ~0.3 contracts -- clipping an exit
        # to that would trap positions the close-only guard exists to let out,
        # which is a worse failure than the one being fixed. Revisit only with
        # a recorded bid ladder in hand.
        if signed_qty_delta > 0:
            depth = available_ask_depth(quote)
            if depth < 1.0:
                # Mirrors the `equity_fraction` branch above: a sub-one-contract
                # allowance is not a smaller order, it is no order. Refused
                # rather than rounded up -- rounding up is exactly the
                # "buy 24.8 where 0.58 exist" behaviour this closes.
                return self._refuse("insufficient_depth")
            signed_qty_delta = min(signed_qty_delta, depth)

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
