"""Tape-seam helper logic shared by the paper-replay and census scripts.

Everything here is deliberately free of Nautilus engine construction, catalog
I/O, and strategy wiring, so it can be unit tested without a `BacktestEngine`
or a live `ParquetDataCatalog`. Three areas only:

* **Instrument selection** -- which tape instruments carry enough data to back
  a run at all (:func:`select_tradable_instrument_ids`,
  :func:`select_book_backed_instrument_ids`).
* **Settlement-price mapping** -- bucket containment turned into the
  ``settlement_prices`` mapping ``BreezyBacktestConfig`` requires
  (:func:`settlement_prices_for_scenario`).
* **Scenario construction** -- the REAL-vs-ASSUMED settlement sweep
  (:func:`build_settlement_scenarios`).

The dead-strategy backtest runner that originally consumed this module, and the
print-lock gate classifier that lived here, were removed at BC-3; they resolve at
git tag ``bc3-pre-removal-2026-10-02``.

ANTI-LOOKAHEAD BY CONSTRUCTION
-------------------------------
:func:`build_settlement_scenarios` never reads a forecast value and
:func:`settlement_prices_for_scenario` never reads one either.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from breezy.domain.weather_bucket_facts import WeatherBucketFacts

__all__ = [
    "PROVENANCE_ASSUMED",
    "PROVENANCE_REAL",
    "Scenario",
    "build_settlement_scenarios",
    "select_book_backed_instrument_ids",
    "select_tradable_instrument_ids",
    "settlement_prices_for_scenario",
]

#: A station's reading in a `Scenario` was read from the live weather catalog.
PROVENANCE_REAL = "REAL"
#: A station's reading in a `Scenario` is a sensitivity value chosen by this
#: script -- never derived from any settlement truth or from the forecast.
PROVENANCE_ASSUMED = "ASSUMED"


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


def select_book_backed_instrument_ids(depth_counts: Mapping[str, int]) -> list[str]:
    """Instrument ids carrying at least one ORDER-BOOK DEPTH row.

    The sibling of :func:`select_tradable_instrument_ids`, NOT a relaxation of
    it -- that rule stays exactly as it is, and is still the right one for the
    forecast strategies, which quote from `QuoteTick`.

    Why a depth-only rule is sound for `cli_settlement_print_lock`: its own
    module docstring states "A long-only taker needs an ASK and nothing else.
    An asks-only book ... is TRADED". Its only market-data handler is
    `on_order_book_depth`; it never reads a `QuoteTick`. And under
    `BookType.L2_MBP` the harness's `InvalidConfiguration: No order book data
    found` guard fires for a QUOTE-ONLY leg, which is the opposite shape.

    Why the distinction is load-bearing on the live capture rather than
    hypothetical: `parse_book_top` requires a best level on BOTH sides, so a
    market whose bid side has emptied records depth and **zero** `QuoteTick`s.
    That is the state of every terminal weather ladder, and applying the
    quote-AND-depth rule to it discards exactly the instruments the print-lock
    strategy exists to trade.
    """
    return sorted(iid for iid, count in depth_counts.items() if count > 0)
