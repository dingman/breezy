"""Plain-Python value types shared by weather-mispricing strategies.

Carried over from the operator-supplied bundle's ``models.py`` section
unchanged in substance: ``SideIntent``, ``MarketQuote``, ``ForecastSnapshot``,
and ``SignalDecision`` are exactly the vocabulary
:func:`breezy.strategy.forecast_mispricing.decision.evaluate_instrument` was
written against, and the task is a behaviour-preserving refactor of that
decision logic -- not a redesign of the types it consumes.

Dropped from the original section: ``ProbabilityView`` (never referenced by
the mispricing strategy; ``WeatherProbabilityEngine`` returns plain floats)
and ``nws_forecast_data_type()`` / ``NWSForecastUpdate`` / ``NWSObservation``
(the wire-level custom-data types the bundle invented). Breezy has no forecast
ingestion, so there is no such wire event for a forecast -- see
``breezy.strategy.forecast_mispricing.forecast_source`` for how a forecast
reaches the strategy instead. And the settlement observation the bundle used
only to flatten positions is *already* a real Breezy record
(``breezy.domain.nws_climate_day.NwsClimateDay``); inventing a second
``NWSObservation`` type for the same fact would be exactly the parallel
record type ``breezy.runtime.backtest_feed`` warns against.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import Enum

__all__ = [
    "ForecastSnapshot",
    "MarketQuote",
    "SideIntent",
    "SignalDecision",
    "ensure_aware",
    "hours_until",
    "issuance_lead_hours",
]


class SideIntent(str, Enum):
    """Desired economic exposure in a binary 0/1 contract."""

    LONG_YES = "LONG_YES"  # buy the contract (profit if outcome = 1)
    SHORT_YES = "SHORT_YES"  # sell/short the contract (profit if outcome = 0)
    FLAT = "FLAT"


@dataclass(frozen=True, slots=True)
class MarketQuote:
    """Executable top-of-book snapshot used for edge calculation.

    Prices are stored in raw venue units. Convert to implied probability with
    ``implied_prob = raw_price * price_scale`` where ``price_scale`` is 1.0
    for 0-1 markets and 0.01 for cent markets.
    """

    instrument_id: str
    bid: float | None
    ask: float | None
    bid_size: float | None
    ask_size: float | None
    ts_event: datetime
    mid: float | None = None
    #: OPTIONAL per-level ask-side depth ladder, best price first, e.g.
    #: ``((ask, ask_size), (next_price, next_size), ...)`` in RAW venue price
    #: units (same units as ``ask``/``implied_ask``). ``None`` for callers
    #: that only ever look at top-of-book -- additive: every existing
    #: keyword-argument ``MarketQuote(...)`` call site is unaffected by this
    #: field's default. Only ``running_extreme_lock`` currently reads it (see
    #: that strategy's ``decision.py``): every fill there is a TAKER against
    #: the live ask, so sizing/pricing off level 0 alone can silently walk
    #: through price on a thin book (see that module's docstring).
    ask_ladder: tuple[tuple[float, float], ...] | None = None

    def __post_init__(self) -> None:
        if self.mid is None and self.bid is not None and self.ask is not None:
            object.__setattr__(self, "mid", 0.5 * (self.bid + self.ask))

    @property
    def spread(self) -> float | None:
        if self.bid is None or self.ask is None:
            return None
        return self.ask - self.bid

    def implied_bid(self, price_scale: float) -> float | None:
        return None if self.bid is None else self.bid * price_scale

    def implied_ask(self, price_scale: float) -> float | None:
        return None if self.ask is None else self.ask * price_scale

    def implied_mid(self, price_scale: float) -> float | None:
        if self.mid is None:
            return None
        return self.mid * price_scale


@dataclass(slots=True)
class ForecastSnapshot:
    """A forecast usable at one instant for one station/target-day.

    This is the ONLY vehicle through which a predicted high temperature
    reaches the strategy. See
    ``breezy.strategy.forecast_mispricing.forecast_source.ForecastSource``
    for the injection contract and why ``horizon_hours`` here is the live
    hours-remaining-to-settlement, not a value frozen at issuance.

    TWO TIME BASES LIVE ON THIS RECORD, AND THEY ARE NOT INTERCHANGEABLE.
    ``horizon_hours`` answers "how long until this settles?" -- it moves with
    the clock, and it is what the settlement halt, the minimum-horizon
    flatten, and the horizon-scaled sizing term want. The FORECAST ERROR
    model wants the other one: how far ahead this forecast was looking when
    it was ISSUED, which is ``hours_until(deadline, published_at)`` and does
    not move at all. Never feed ``horizon_hours`` to
    ``ForecastErrorModel.sigma`` -- see :func:`issuance_lead_hours` (T-11).
    """

    location_id: str
    target_date: date
    published_at: datetime
    expected_high_f: float
    horizon_hours: float
    source: str = "SYNTHETIC-INJECTED"
    nws_product: str | None = None
    raw_payload_id: str | None = None

    def is_stale(self, now: datetime, max_age_hours: float) -> bool:
        published = ensure_aware(self.published_at)
        aware_now = ensure_aware(now)
        age_hours = (aware_now - published).total_seconds() / 3600.0
        return age_hours > max_age_hours


@dataclass(slots=True)
class SignalDecision:
    """Strategy output consumed by the shared execution layer."""

    instrument_id: str
    intent: SideIntent
    model_probability: float
    market_probability: float
    edge: float
    conviction: float
    quantity: float
    reason: str
    metadata: Mapping[str, float | str | int | None] = field(default_factory=dict)


def ensure_aware(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)


def hours_until(later: datetime, now: datetime) -> float:
    return (ensure_aware(later) - ensure_aware(now)).total_seconds() / 3600.0


def issuance_lead_hours(deadline: datetime, forecast: ForecastSnapshot) -> float:
    """Hours from a forecast's ISSUANCE to settlement -- the ONLY horizon `sigma` may take.

    ``ForecastErrorModel.sigma(location_id, target_date, horizon_hours)`` models
    FORECAST ERROR, which is a property of the forecast: a 24-hour-out
    prediction carries roughly 2.8 degF of error, a 3-hour-out prediction
    roughly 1.4 degF. That distribution belongs to the forecast and is fixed
    the moment it is published. It does NOT shrink because the clock advanced
    toward the deadline -- the forecast did not get any better by being read
    later.

    Feeding ``ForecastSnapshot.horizon_hours`` (the LIVE hours-to-settlement)
    to ``sigma`` therefore reads a stale forecast as though it were a fresh
    one, understating sigma by roughly the ratio of the two horizons.
    Understated sigma pushes the model probability toward 0 or 1, which
    OVERSTATES edge -- worst on the near-certain buckets, where sizing is
    largest. That is a measurement corruption, not a cosmetic one: it inflates
    backtest ROI (T-11,
    ``docs/core/findings/BLIND_RISK_VIEWS_2026-09-02.md``).

    ``deadline`` is the instrument's OWN native ``expiration_ns``, held per
    instrument as ``_deadlines[instrument_id]`` at the strategy layer -- the
    same value the settlement halt reads, never a wall clock refabricated here.

    Deliberately a free function taking BOTH values rather than a method or a
    second stored field: it cannot be reached without naming a deadline, so
    ``sigma(..., issuance_lead_hours(deadline, forecast))`` and
    ``sigma(..., forecast.horizon_hours)`` can never be mistaken for each
    other at a call site. A stored field would have to be recomputed by every
    ``ForecastSource`` implementation (the seam T-7 has just shown is pinned
    by prose alone), and a method on the snapshot taking ``now`` would be
    wrong for a STORED publication -- ``forecast_revision`` keeps a history
    whose entries' ``horizon_hours`` were live at their own, now unrecoverable,
    observation instants.

    Negative once ``published_at`` is past the deadline, exactly as
    :func:`hours_until` is; ``sigma`` floors its own input at
    ``min_horizon_hours``, so no clamping is applied or needed here.
    """
    return hours_until(deadline, forecast.published_at)
