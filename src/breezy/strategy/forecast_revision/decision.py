"""The preserved trading decision: an unabsorbed forecast revision.

This is ``ForecastRevisionStrategy.evaluate_instrument`` (plus its
``_maybe_exit_caught_up`` and ``_market_move_since`` helpers, and the state
``on_forecast_updated`` maintained) from the operator's bundle, extracted
verbatim in its arithmetic and branching, as a pure function of its inputs
instead of a method on the Nautilus ``Strategy`` subclass. Every branch below
-- the three magnitude floors, the same-sign persistence filter, the
absorbed-fraction comparison, the reaction window, the per-publication
cooldown, the edge-after-costs screen and the catch-up exit -- is exactly the
operator's intent, and is now unit-testable with no Nautilus object in scope.

THE ONE STRUCTURAL ADAPTATION: PUSH BECAME PULL
------------------------------------------------
The bundle learned about revisions from a PUSH event. Its ``on_data`` received
a wire-level ``NWSForecastUpdate`` custom data type, called ``on_nws_forecast``
-> ``on_forecast_updated``, and there appended to a per-(station, day) history
deque while snapshotting the market midpoint of every affected contract at that
instant.

Breezy publishes no such event -- there is no forecast ingestion at all, and
the forecast seam is a PULL
(``breezy.strategy.weather_common.forecast_source.ForecastSource.snapshot``,
called fresh on every quote or depth update). So the history is accumulated by
:meth:`RevisionState.observe`, which the strategy calls with each PULLED
snapshot. ``observe`` appends only when ``published_at`` is strictly newer than
the newest publication already held.

WHAT THE PULL SEAM REPRODUCES, AND WHAT IT DOES NOT
----------------------------------------------------
It IS equivalent for the two idempotence guards. Repeated pulls of the SAME
publication do not grow the history -- the push path saw each publication once,
and the bundle additionally no-oped on an unchanged publication at
``evaluate_instrument``'s ``current.published_at <= previous.published_at``
check (NOT at its ``on_nws_forecast`` ingestion filter, which used a strict
``<`` and so let an equal timestamp through to the history). And an
out-of-order publication is ignored, as the bundle logged and dropped it.

It is NOT equivalent for publication COVERAGE, and this changes trading
behaviour. ``ForecastSource.snapshot`` returns only the forecast current as of
``now`` -- not a queue of everything published since the last poll. If two
genuine NWS revisions land between two poll ticks, only the later survives:
the intermediate publication is permanently invisible, and ``evaluate_instrument``
scores ONE MERGED delta across what were two separately-scored events. Three
consequences, all real:

* a merged ``d_t``/``d_p`` can clear ``min_temp_revision_f`` /
  ``min_unabsorbed_prob`` when neither constituent revision would alone --
  a false positive;
* two opposite-sign revisions can net to roughly zero and both be skipped --
  a false negative;
* ``window_end`` anchors to ``current.published_at``, the LATER revision, so a
  poll landing after ``reaction_window_minutes`` has already elapsed drops
  straight to :func:`_maybe_exit_caught_up` and never attempts an entry it
  could have traded.

Correctness therefore REQUIRES a polling cadence strictly finer than BOTH the
real forecast-issuance interval and ``reaction_window_minutes``. The durable
fix is a ``ForecastSource`` that can return every publication since the last
poll; that is plan increment I-6 (see
``docs/plans/FORECAST_INGESTION_PLAN.md``), not a change to the Protocol here,
and the strategy is degraded until it lands. The behaviour is pinned by
``test_a_publication_missed_between_polls_is_merged_not_scored``.

The market-probability baseline is captured at the same moment, from the
caller's latest quote, exactly as ``on_forecast_updated`` did -- and, as there,
independently of whether the SHARED per-(station, day) history advanced. See
:meth:`RevisionState.observe` for why that independence is load-bearing on a
bucket ladder.

Two smaller adaptations, neither touching the math: bucket probabilities come
from ``engine.revision(contract.facts, ...)`` rather than
``engine.revision(contract, ...)`` -- real venue facts instead of the bundle's
hand-rolled ``TemperatureContract`` -- and ``current_qty`` is passed in from the
native ``Portfolio.net_position`` rather than read from a strategy-owned ledger
the bundle mutated by hand.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from breezy.strategy.weather_common.models import (
    SideIntent,
    SignalDecision,
    ensure_aware,
)
from breezy.strategy.weather_common.refusals import SHORTS_DISABLED, RefusalCounter

if TYPE_CHECKING:  # pragma: no cover - typing only
    from breezy.strategy.forecast_revision.config import ForecastRevisionConfig
    from breezy.strategy.weather_common.bucket_contract import MispricingContract
    from breezy.strategy.weather_common.models import ForecastSnapshot, MarketQuote
    from breezy.strategy.weather_common.probability import WeatherProbabilityEngine

__all__ = ["RevisionState", "evaluate_instrument"]

_HistoryKey = tuple[str, date]


@dataclass(slots=True)
class RevisionState:
    """Per-strategy revision bookkeeping, with no Nautilus object in scope.

    Holds the four dicts the bundle kept as strategy attributes:
    ``_forecast_hist``, ``_market_p_at_forecast``, ``_traded_publication`` and
    ``_active_revision``. Extracted so the decision function stays pure with
    respect to everything except this one explicit, testable accumulator.
    """

    history_len: int = 12
    _history: dict[_HistoryKey, deque[ForecastSnapshot]] = field(default_factory=dict)
    _market_p_at_forecast: dict[str, list[tuple[datetime, float]]] = field(default_factory=dict)
    traded_publication: dict[str, datetime] = field(default_factory=dict)
    active_revision: dict[str, tuple[datetime, float]] = field(default_factory=dict)

    def history(self, contract: MispricingContract) -> list[ForecastSnapshot]:
        """Publications held for this contract's station and climate day."""
        return list(self._history.get(self._key(contract), ()))

    def observe(
        self,
        *,
        contract: MispricingContract,
        forecast: ForecastSnapshot,
        market_mid_p: float | None,
    ) -> bool:
        """Record ``forecast`` if it is a NEW publication. Returns whether it was.

        Replaces the bundle's ``on_forecast_updated`` push hook -- see the
        module docstring. Re-observing a publication already held, or one older
        than the newest held, does not grow the SHARED history.

        THE SHARED HISTORY AND THE PER-INSTRUMENT BASELINE ARE INDEPENDENT.
        ``_history`` is keyed by ``(settlement_station, climate_day)``, which
        every bucket in a ladder SHARES; ``_market_p_at_forecast`` is keyed by
        ``instrument_id``, which they do not. Each ladder sibling learns of a
        revision from its OWN quote tick, so only the first sibling to tick
        advances the shared history -- gating the baseline on that advance would
        leave every other sibling with no baseline at all, hence a ``None`` from
        :meth:`market_move_since`, hence ``market_dp`` defaulting to 0.0 and
        ``unabsorbed`` collapsing to the full model revision as though the book
        had absorbed nothing. The bundle had no such coupling: its
        ``on_forecast_updated`` advanced the per-(location, date) history once
        and then looped ``self.registry.all()`` recording EVERY matching
        contract's own midpoint regardless. The baseline is therefore appended
        below independent of the return value -- but only ONCE per publication
        per instrument, which is both the semantics the name promises (the
        market probability AT THE MOMENT the forecast arrived) and what the
        push path recorded, since it saw each publication exactly once. Later
        re-polls of a publication already baselined are ignored, so decoupling
        does not turn the series into a per-poll tick log.
        """
        key = self._key(contract)
        bucket = self._history.get(key)
        if bucket is None:
            bucket = deque(maxlen=self.history_len)
            self._history[key] = bucket
        published = ensure_aware(forecast.published_at)
        advanced = not (bucket and published <= ensure_aware(bucket[-1].published_at))
        if advanced:
            bucket.append(forecast)
        if market_mid_p is not None:
            series = self._market_p_at_forecast.setdefault(contract.instrument_id, [])
            if not any(ensure_aware(ts) == published for ts, _ in series):
                series.append((published, market_mid_p))
        return advanced

    def clear(self) -> None:
        self._history.clear()
        self._market_p_at_forecast.clear()
        self.traded_publication.clear()
        self.active_revision.clear()

    @staticmethod
    def _key(contract: MispricingContract) -> _HistoryKey:
        return (contract.facts.settlement_station, contract.facts.climate_day)

    # -- internals used by `evaluate_instrument` ------------------------
    def market_move_since(
        self,
        *,
        instrument_id: str,
        published_at: datetime,
        quote: MarketQuote,
        price_scale: float,
    ) -> float | None:
        """How far the market midpoint has moved since ``published_at``."""
        series = self._market_p_at_forecast.get(instrument_id, [])
        target = ensure_aware(published_at)
        baseline: float | None = None
        for ts, p in series:
            if ensure_aware(ts) == target:
                baseline = p
                break
        if baseline is None and series:
            # Nearest snapshot at or before publication.
            prior = [p for ts, p in series if ensure_aware(ts) <= target]
            baseline = prior[-1] if prior else None
        mid = quote.implied_mid(price_scale)
        if baseline is None or mid is None:
            return None
        return mid - baseline


def evaluate_instrument(
    *,
    contract: MispricingContract,
    quote: MarketQuote,
    now: datetime,
    current_qty: float,
    state: RevisionState,
    engine: WeatherProbabilityEngine,
    cfg: ForecastRevisionConfig,
    refusals: RefusalCounter | None = None,
) -> SignalDecision | None:
    """Return the desired position change, or ``None`` for "do nothing"."""
    hist = state.history(contract)
    if len(hist) < 2:
        return None
    current = hist[-1]
    previous = hist[-2]
    if ensure_aware(current.published_at) <= ensure_aware(previous.published_at):
        return None

    scale = (
        cfg.price_scale_override if cfg.price_scale_override is not None else contract.price_scale
    )

    rev = engine.revision(
        contract.facts,
        previous.expected_high_f,
        previous.horizon_hours,
        current.expected_high_f,
        current.horizon_hours,
    )
    d_t = rev.forecast_revision_f
    d_p = rev.prob_revision
    _, sigma_prev = engine.mu_sigma(
        previous.expected_high_f,
        previous.horizon_hours,
        contract.facts.settlement_station,
        contract.facts.climate_day,
    )

    window_end = ensure_aware(current.published_at) + timedelta(
        minutes=cfg.reaction_window_minutes,
    )
    if ensure_aware(now) > window_end:
        return _maybe_exit_caught_up(
            contract=contract, quote=quote, current_qty=current_qty,
            state=state, cfg=cfg, price_scale=scale,
        )

    last_traded = state.traded_publication.get(contract.instrument_id)
    if last_traded is not None and ensure_aware(last_traded) == ensure_aware(
        current.published_at,
    ):
        return _maybe_exit_caught_up(
            contract=contract, quote=quote, current_qty=current_qty,
            state=state, cfg=cfg, price_scale=scale,
        )
    if last_traded is not None:
        cooldown_until = ensure_aware(last_traded) + timedelta(minutes=cfg.cooldown_minutes)
        if ensure_aware(now) < cooldown_until:
            return None

    if abs(d_t) < cfg.min_temp_revision_f and abs(d_p) < cfg.min_prob_revision:
        return None
    if abs(d_t) / max(sigma_prev, 0.4) < cfg.min_revision_over_sigma and (
        abs(d_p) < cfg.min_prob_revision
    ):
        return None

    if cfg.persistence_same_sign and len(hist) >= cfg.persistence_updates + 1:
        signs = []
        for i in range(-cfg.persistence_updates, 0):
            a, b = hist[i - 1], hist[i]
            signs.append(1 if b.expected_high_f - a.expected_high_f >= 0 else -1)
        if abs(sum(signs)) != cfg.persistence_updates and cfg.persistence_updates > 1:
            # Require the last N revisions to share a sign.
            return None

    market_dp = state.market_move_since(
        instrument_id=contract.instrument_id,
        published_at=current.published_at,
        quote=quote,
        price_scale=scale,
    )
    if market_dp is None:
        market_dp = 0.0
    # How much of the model revision the book has already priced.
    absorbed = market_dp / d_p if abs(d_p) > 1e-9 else 1.0
    unabsorbed = d_p - market_dp
    if abs(unabsorbed) < cfg.min_unabsorbed_prob:
        return None
    if absorbed >= cfg.min_caught_up_fraction and d_p * market_dp > 0:
        return None

    intent = SideIntent.LONG_YES if unabsorbed > 0 else SideIntent.SHORT_YES
    if intent is SideIntent.SHORT_YES and not cfg.allow_short:
        # Counted, not merely suppressed -- see `weather_common.refusals`.
        if refusals is not None:
            refusals.record(SHORTS_DISABLED)
        return None

    bid_p, ask_p, mid_p = (
        quote.implied_bid(scale),
        quote.implied_ask(scale),
        quote.implied_mid(scale),
    )
    if bid_p is None or ask_p is None or mid_p is None:
        # Defensive only, and NOT the preserved defect below. A one-sided or
        # empty book cannot produce a market probability at all, so there is
        # nothing to report and nothing to trade against. `calibration_mean_reversion`
        # carries this same explicit check; the bundle omitted it here, and the
        # omission is unreachable today (quotes are built from non-None floats
        # and depth is guarded upstream) -- this aligns the defensive style
        # without changing any reachable outcome.
        return None
    # PRESERVED DEFECT -- AWAITING AN OPERATOR RULING. DO NOT "FIX" SILENTLY.
    # `or` tests FALSINESS, not None. A touch price of exactly 0.0 -- a real,
    # reachable price on a 0-1 binary market -- is falsy, so this silently
    # falls through to `mid_p` and then to the literal 0.0, reporting a market
    # probability that is not the side actually being hit. The intended reading
    # is an explicit `is not None` chain (compare the same pattern, preserved
    # identically, in `forecast_mispricing.decision`). Carried over verbatim
    # from the operator's bundle. `mkt` is reported, not traded on: it reaches
    # `SignalDecision.market_probability` and the order log, never the sizing
    # or the side, both of which are already fixed above.
    mkt = (ask_p if intent is SideIntent.LONG_YES else bid_p) or mid_p or 0.0
    edge = abs(unabsorbed) - cfg.transaction_cost_prob
    if edge < cfg.min_model_edge:
        return None

    qty = min(cfg.max_quantity, cfg.base_quantity + cfg.revision_qty_scale * abs(unabsorbed))
    decision = SignalDecision(
        instrument_id=contract.instrument_id,
        intent=intent,
        model_probability=rev.new_prob,
        market_probability=mkt,
        edge=edge,
        conviction=min(1.0, abs(unabsorbed) / max(cfg.min_prob_revision, 1e-6)),
        quantity=qty,
        reason="forecast_revision_unabsorbed",
        metadata={
            "dT": d_t,
            "dP_model": d_p,
            "dP_market": market_dp,
            "unabsorbed": unabsorbed,
            "absorbed_frac": absorbed,
            "sigma_prev": sigma_prev,
            "publication": current.published_at.isoformat(),
        },
    )
    state.traded_publication[contract.instrument_id] = current.published_at
    state.active_revision[contract.instrument_id] = (current.published_at, d_p)
    return decision


def _maybe_exit_caught_up(
    *,
    contract: MispricingContract,
    quote: MarketQuote,
    current_qty: float,
    state: RevisionState,
    cfg: ForecastRevisionConfig,
    price_scale: float,
) -> SignalDecision | None:
    if not cfg.exit_when_market_catches_up:
        return None
    if abs(current_qty) < 1e-9:
        return None
    active = state.active_revision.get(contract.instrument_id)
    if active is None:
        return None
    published_at, model_dp = active
    if abs(model_dp) < 1e-9:
        return None
    market_dp = (
        state.market_move_since(
            instrument_id=contract.instrument_id,
            published_at=published_at,
            quote=quote,
            price_scale=price_scale,
        )
        or 0.0
    )
    absorbed = market_dp / model_dp
    if absorbed >= cfg.min_caught_up_fraction and model_dp * market_dp > 0:
        mid = quote.implied_mid(price_scale) or 0.0
        return SignalDecision(
            contract.instrument_id,
            SideIntent.FLAT,
            mid + model_dp,
            mid,
            0.0,
            0.0,
            0.0,
            "revision_market_caught_up",
            {"absorbed_frac": absorbed},
        )
    return None
