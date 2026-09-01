"""The traded contract's identity, sourced from Breezy's own venue facts.

Replaces the bundle's ``contract_metadata.py`` section wholesale.
``TemperatureContract``/``ContractKind``/``WeatherContractRegistry`` there
were the bundle re-parsing bucket bounds from a venue slug, hand-rolled, with
no relationship to Breezy's own parsed facts and no test against a captured
market. :class:`MispricingContract` instead WRAPS
:class:`breezy.domain.weather_bucket_facts.WeatherBucketFacts`, which is read
from ``Instrument.info`` by
``breezy.domain.weather_bucket_facts.read_weather_bucket_facts`` -- the
already-corroborated source (114/114 captured buckets, per that module's
docstring) -- so the bounds a decision trades against are the same bounds the
venue actually settles on, closed at both finite ends.

Also dropped: the bundle's ``settlement_local_time`` / ``timezone`` fields
(defaults of ``time(23, 59)`` / ``"America/Chicago"`` baked into every
contract regardless of station -- wrong for every station outside Chicago,
and not sourced from anything). Breezy has no wall-clock settlement-time
source at the strategy layer (settlement here is driven entirely by the
native ``InstrumentClose`` -- see ``breezy.runtime.backtest_harness``), so
"hours to settlement" is not recomputed from a fabricated clock. It comes
from the injected :class:`~breezy.strategy.forecast_mispricing.forecast_source.ForecastSource`
instead -- see that module's docstring for the contract this implies.
"""

from __future__ import annotations

from dataclasses import dataclass

from breezy.domain.weather_bucket_facts import WeatherBucketFacts

__all__ = ["MispricingContract"]


@dataclass(frozen=True, slots=True, kw_only=True)
class MispricingContract:
    """One tradable instrument's weather-settlement identity and pricing facts."""

    instrument_id: str
    facts: WeatherBucketFacts
    #: The instrument's own minimum price increment
    #: (``float(instrument.price_increment)``), never a literal default.
    #:
    #: CORRECTED 2026-09-01. This field previously claimed "the captured
    #: universe carries more than one tick size". It does not, and never did:
    #: a re-run of the recursive sweep over
    #: ``docs/evidence/venue/polymarket_us/raw/*.json`` (26 files, 729 market
    #: observations across 680 distinct slugs) finds
    #: ``orderPriceMinTickSize == 0.01`` in **729/729**, with no exceptions
    #: -- matching ``docs/core/archive/PROGRESS-pre-2026-08-31-backlog-replacement.md``
    #: line 945. The field that actually VARIES in that corpus is
    #: ``minimumTradeQty`` (405 observations at 0.01, 324 at 1), i.e. the SIZE
    #: increment, not the price tick; the original comment conflated the two.
    #:
    #: The field stays per-instrument anyway -- reading a venue fact per market
    #: is right regardless of how uniform today's capture happens to be -- but
    #: NOTHING SAFETY-CRITICAL MAY REST ON TICK VARIATION. It used to: the
    #: print-lock slippage floor was ``slippage_prob >= tick``, which on a
    #: hypothetical 0.001-tick market admitted ``slippage_prob = 0.001`` and
    #: with it ask 0.99 at edge +0.005302 -- the exact trade BL-19 s8.2
    #: computes as -0.003698. That floor is now
    #: ``max(ABSOLUTE_SLIPPAGE_FLOOR_PROB, tick)``. See
    #: ``breezy.strategy.cli_settlement_print_lock.strategy``.
    #:
    #: (``docs/evidence/bl19_edge_and_cost_decision_2026-09-01.md`` s1 and
    #: falsifier 5 both cite the retracted claim, sourcing it to this comment.
    #: Falsifier 5 -- "tick size is not 0.01 on the traded instruments" --
    #: remains a legitimate thing to watch for; what is retracted is the claim
    #: that it has ALREADY been observed.)
    tick_size: float
    #: 1.0 for markets already priced in [0, 1]; overridable per-strategy via
    #: config for a cent-priced venue.
    price_scale: float = 1.0
    #: The venue's per-market fee coefficient (``theta``), resolved ONCE at
    #: ``on_start`` from a
    #: :class:`breezy.strategy.weather_common.costs.FeeCoefficientSource`.
    #: ``None`` means UNRESOLVED, and an unresolved schedule is a NO-TRADE,
    #: never a free trade -- ``breezy.adapters.polymarket_us.fees`` raises
    #: rather than trading free, and a strategy-side default would reintroduce
    #: exactly the fallback the adapter refuses. Defaults ``None`` so the three
    #: forecast strategies, which still use their own scalar
    #: ``transaction_cost_prob``, are unaffected by this field.
    fee_coefficient: float | None = None
    #: Payout dollars per contract at YES. Binary options here always pay 1.0.
    contract_size: float = 1.0

    @property
    def location_id(self) -> str:
        """The settlement station, doubling as the risk-grouping "location"."""
        return self.facts.settlement_station

    @property
    def event_key(self) -> str:
        """Groups every bucket settling off the same station/climate-day."""
        return f"{self.facts.settlement_station}:{self.facts.climate_day.isoformat()}"
