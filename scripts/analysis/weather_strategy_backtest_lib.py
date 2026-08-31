"""Pure helper logic for ``run_weather_strategy_backtests.py``.

Everything here is deliberately free of Nautilus engine construction, catalog
I/O, and strategy wiring, so it can be unit tested without a `BacktestEngine`
or a live `ParquetDataCatalog`. Three areas only, matching what the runner
actually needs to get right before it ever touches the harness:

* **Instrument selection** -- which tape instruments carry enough data to back
  a run at all (:func:`select_tradable_instrument_ids`).
* **Settlement-price mapping** -- bucket containment turned into the
  ``settlement_prices`` mapping ``BreezyBacktestConfig`` requires
  (:func:`settlement_prices_for_scenario`).
* **Scenario construction** -- the REAL-vs-ASSUMED settlement sweep
  (:func:`build_settlement_scenarios`).

:func:`hours_until` is the one small piece of arithmetic the runner's
synthetic ``ForecastSource`` needs to make ``horizon_hours`` a LIVE quantity
(computed from the current backtest clock, not frozen at forecast-issuance
time) -- see ``breezy.strategy.weather_common.forecast_source`` for why that
field is load-bearing.

ANTI-LOOKAHEAD BY CONSTRUCTION
-------------------------------
:func:`build_settlement_scenarios` never reads a forecast value and
:func:`settlement_prices_for_scenario` never reads one either -- the forecast
this runner injects is a constant, independent of every station's real or
swept reading, is never a parameter of either function below, and is wired in
only by the runner script itself.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from breezy.domain.weather_bucket_facts import WeatherBucketFacts

__all__ = [
    "PROVENANCE_ASSUMED",
    "PROVENANCE_REAL",
    "STATUS_COMPLETED",
    "STATUS_COMPLETED_ALL_REFUSED",
    "Scenario",
    "build_settlement_scenarios",
    "derive_completion_status",
    "hours_until",
    "latest_publication_at_or_before",
    "select_tradable_instrument_ids",
    "settlement_prices_for_scenario",
]

#: A station's reading in a `Scenario` was read from the live weather catalog.
PROVENANCE_REAL = "REAL"
#: A station's reading in a `Scenario` is a sensitivity value chosen by this
#: script -- never derived from any settlement truth or from the forecast.
PROVENANCE_ASSUMED = "ASSUMED"

#: A run submitted zero orders and recorded zero risk/decision refusals: it
#: saw no tradable opportunity. Indistinguishable, without more, from a run
#: whose entire signal set was gagged -- see :func:`derive_completion_status`.
STATUS_COMPLETED = "COMPLETED"
#: A run submitted zero orders BUT its strategy recorded at least one
#: refusal (e.g. `SHORTS_DISABLED`, see
#: `breezy.strategy.weather_common.refusals`): its entire signal set was
#: refused, not merely absent. Distinct from :data:`STATUS_COMPLETED` so a
#: gagged strategy never reports as an unqualified clean completion.
STATUS_COMPLETED_ALL_REFUSED = "COMPLETED_ALL_REFUSED"


@dataclass(frozen=True, slots=True)
class Scenario:
    """One settlement-outcome hypothesis to run every strategy against.

    Parameters
    ----------
    name : str
        Unique, stable across a run -- used as the JSON/report key.
    observed_by_station : Mapping[str, int]
        Station code (e.g. ``"NYC"``) -> whole-degree Fahrenheit high used to
        derive this scenario's ``settlement_prices``.
    provenance_by_station : Mapping[str, str]
        Same keys as ``observed_by_station``; each value is
        :data:`PROVENANCE_REAL` or :data:`PROVENANCE_ASSUMED`, so a report can
        never present a swept number as measured fact.

    """

    name: str
    observed_by_station: Mapping[str, int]
    provenance_by_station: Mapping[str, str]


def select_tradable_instrument_ids(
    depth_counts: Mapping[str, int],
    quote_counts: Mapping[str, int],
) -> list[str]:
    """Instrument ids carrying at least one depth row AND one quote row.

    An instrument with only one of the two record types cannot back a run
    under ``book_type=BookType.L2_MBP`` (``breezy.runtime.backtest_harness``):
    Nautilus's own ``InvalidConfiguration: No order book data found`` guard
    fires per instrument for a quote-only leg. Sorted so the result is
    deterministic regardless of the input mappings' iteration order.
    """
    ids = {
        instrument_id
        for instrument_id, count in depth_counts.items()
        if count > 0 and quote_counts.get(instrument_id, 0) > 0
    }
    return sorted(ids)


def settlement_prices_for_scenario[InstrumentIdT](
    facts_by_instrument_id: Mapping[InstrumentIdT, WeatherBucketFacts],
    observed_by_station: Mapping[str, int],
) -> dict[InstrumentIdT, float]:
    """Map every instrument to the settlement endpoint its bucket resolves to.

    ``1.0`` if ``facts.contains(observed_by_station[facts.settlement_station])``,
    else ``0.0`` -- the only two values
    ``breezy.runtime.backtest_harness.assert_settlement_invariants`` accepts.

    Raises
    ------
    KeyError
        If any instrument's ``settlement_station`` has no reading in
        ``observed_by_station``. Fail-closed rather than skipping that
        instrument: a partial mapping would silently trip the harness's
        COVERAGE invariant instead of failing here, with a much less specific
        message.

    """
    prices: dict[InstrumentIdT, float] = {}
    for instrument_id, facts in facts_by_instrument_id.items():
        if facts.settlement_station not in observed_by_station:
            raise KeyError(
                f"no observed reading for station {facts.settlement_station!r} "
                f"(instrument {instrument_id!r}); every instrument's station must "
                f"appear in `observed_by_station`",
            )
        reading = observed_by_station[facts.settlement_station]
        prices[instrument_id] = 1.0 if facts.contains(reading) else 0.0
    return prices


def build_settlement_scenarios(
    *,
    real_observed_by_station: Mapping[str, int],
    sweep_by_station: Mapping[str, Sequence[int]],
) -> list[Scenario]:
    """The full settlement-outcome sweep: one REAL scenario, then per-station sweeps.

    The first scenario, ``"primary_real_preliminary"``, uses
    ``real_observed_by_station`` for every station -- the one scenario that is
    not fabricated. Every other scenario varies exactly ONE station's reading
    to an :data:`PROVENANCE_ASSUMED` candidate from ``sweep_by_station`` while
    holding every other station at its REAL reading, so a PnL difference
    between two scenarios is attributable to the one station that changed.

    Parameters
    ----------
    real_observed_by_station : Mapping[str, int]
        Every station this run touches, at its REAL (measured) reading.
    sweep_by_station : Mapping[str, Sequence[int]]
        Station -> candidate readings to sweep. A station with an empty
        sequence contributes no extra scenarios.

    Raises
    ------
    ValueError
        If ``sweep_by_station`` names a station absent from
        ``real_observed_by_station`` -- there is nothing to hold fixed for the
        other scenarios in that case.

    """
    unknown = sorted(set(sweep_by_station) - set(real_observed_by_station))
    if unknown:
        raise ValueError(
            f"sweep_by_station names station(s) with no real reading to hold "
            f"fixed: {unknown}",
        )

    scenarios = [
        Scenario(
            name="primary_real_preliminary",
            observed_by_station=dict(real_observed_by_station),
            provenance_by_station=dict.fromkeys(real_observed_by_station, PROVENANCE_REAL),
        ),
    ]
    for station in sorted(sweep_by_station):
        for candidate in sweep_by_station[station]:
            observed = dict(real_observed_by_station)
            observed[station] = candidate
            provenance = dict.fromkeys(real_observed_by_station, PROVENANCE_REAL)
            provenance[station] = PROVENANCE_ASSUMED
            scenarios.append(
                Scenario(
                    name=f"sweep_{station.lower()}_{candidate}f",
                    observed_by_station=observed,
                    provenance_by_station=provenance,
                ),
            )
    return scenarios


def derive_completion_status(
    *,
    orders_submitted: int,
    refusal_counts: Mapping[str, int],
) -> str:
    """:data:`STATUS_COMPLETED_ALL_REFUSED` iff the run traded nothing AND was refused.

    A run that submits zero orders is ambiguous on its own: it may simply
    have seen no opportunity (an efficient market), or every signal it formed
    may have been refused by a risk/decision gate (e.g. `SHORTS_DISABLED`
    under `allow_short=False`) -- see
    `breezy.strategy.weather_common.refusals.RefusalCounter`. Those are
    different facts and must not report identically.

    ``refusal_counts`` is summed across every reason rather than checked for
    a specific key, so any reason the counter records (not only
    `SHORTS_DISABLED`) counts as evidence the run was gagged, not merely
    unopportune. A run with `orders_submitted > 0` is always
    :data:`STATUS_COMPLETED`, even if some of its signals were separately
    refused -- only a wholly-gagged run (zero orders) gets the distinct
    status.
    """
    if orders_submitted == 0 and sum(refusal_counts.values()) > 0:
        return STATUS_COMPLETED_ALL_REFUSED
    return STATUS_COMPLETED


def hours_until(now: dt.datetime, deadline: dt.datetime) -> float:
    """Hours from ``now`` to ``deadline``; negative once ``now`` is past it.

    Both arguments must be timezone-aware. This is the one place the synthetic
    ``ForecastSource`` computes ``ForecastSnapshot.horizon_hours`` LIVE (as of
    the backtest clock's current instant), rather than freezing it at forecast
    issuance -- see ``breezy.strategy.weather_common.forecast_source`` for why
    a frozen value would be wrong.

    Raises
    ------
    ValueError
        If either argument is a naive `datetime`.

    """
    if now.tzinfo is None or deadline.tzinfo is None:
        raise ValueError("both `now` and `deadline` must be timezone-aware")
    return (deadline - now).total_seconds() / 3600.0


def latest_publication_at_or_before(
    publications: Sequence[tuple[dt.datetime, float]],
    now: dt.datetime,
) -> tuple[dt.datetime, float] | None:
    """The `(published_at, expected_high_f)` with the greatest `published_at` <= `now`.

    Models a forecast source that can only ever report the latest publication
    that has actually happened as of `now` -- never a future one, and never
    interpolated between two. `publications` need not be pre-sorted.

    Returns
    -------
    tuple[dt.datetime, float] | None
        `None` if `now` precedes every publication (nothing has been issued
        yet) or `publications` is empty.

    """
    applicable = [p for p in publications if p[0] <= now]
    if not applicable:
        return None
    return max(applicable, key=lambda p: p[0])
