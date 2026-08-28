"""The forecast-injection seam -- read this before wiring any weather strategy.

THE GAP THIS MODULE EXISTS TO CLOSE
------------------------------------
Breezy ingests NO forecast data. The only weather records that exist are
OBSERVED climate days (``breezy.domain.nws_climate_day.NwsClimateDay``:
``tmax_f``, ``is_final``) and the raw products they were parsed from. There is
no forecast source anywhere in this codebase, and adding one is out of scope
for the strategies that consume this module.

A forecast-driven strategy
(:class:`~breezy.strategy.forecast_mispricing.strategy.ForecastMispricingStrategy`
and, in future, its siblings) therefore cannot get ``expected_high_f`` from
anywhere Breezy owns. The one and only wrong answer is to fabricate it from
the settled observation -- feeding ``NwsClimateDay.tmax_f`` in as
``expected_high_f`` (directly, as a "temporary" stand-in, or as any fallback)
gives the strategy perfect foresight of its own settlement outcome. That is
lookahead bias, full stop: every backtest run against it will look
spectacular and mean nothing, because the "forecast" it traded on could only
exist after the question it was forecasting had already been answered.

THE CONTRACT
------------
:class:`ForecastSource` is a plain, non-Nautilus ``Protocol`` supplied to the
strategy as a REQUIRED, POSITIONAL constructor argument -- never a config
field with a default, and never constructed by the strategy itself. Omitting
it is a ``TypeError`` at construction; the strategy also checks it is not
``None`` and raises :class:`MissingForecastSourceError` if it is, so a caller
that manages to pass ``None`` through (e.g. from an ``Optional``-typed call
site) still gets a loud, immediate refusal rather than a strategy that quietly
never trades or -- worse -- one that falls back to something derived from
settlement data.

``ForecastSource.snapshot`` may return ``None`` to mean "no forecast is
available yet for this station/day" -- that is a legitimate, non-fabricating
answer, and the strategy's response to it is to skip evaluation entirely
(never trade, never flatten-for-lack-of-forecast). It is a deliberately
NARROW seam: a pull, not a push. The strategy calls it fresh on every quote or
depth update, passing the CURRENT ``now`` -- it does not cache a stale
snapshot and does not subscribe to any wire-level forecast event, because no
such event exists in Breezy.

``horizon_hours`` ON THE RETURNED SNAPSHOT IS LOAD-BEARING
------------------------------------------------------------
The operator's bundle computed "hours to settlement" from a settlement
clock it fabricated per-contract (a hardcoded default timezone and
23:59-local settlement time -- see
``breezy.strategy.weather_common.bucket_contract`` for why that was removed).
Breezy has no equivalent wall-clock settlement source at the strategy layer:
in this harness, settlement is driven entirely by the native
``InstrumentClose`` event (``breezy.runtime.backtest_harness``), not by a
computable wall-clock deadline. Rather than re-fabricate one, this seam
requires ``ForecastSource.snapshot`` to return a ``horizon_hours`` that is
ALREADY the live hours-remaining-to-settlement as of the ``now`` it was
called with -- not a value frozen at the forecast's original issuance time.
The strategy uses this one number for both the probability model's horizon
AND the settlement-halt / horizon-scaled-sizing decisions the bundle used to
compute separately. This is reported as a deliberate collapsing of two
previously-separate time bases -- see the integration report for why, and
treat it as a real constraint on any ``ForecastSource`` implementation, not
an implementation detail to route around.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Protocol

from breezy.strategy.weather_common.models import ForecastSnapshot

__all__ = ["ForecastSource", "MissingForecastSourceError"]


class MissingForecastSourceError(ValueError):
    """Raised when a strategy is constructed with no forecast source.

    A forecast-driven strategy must refuse loudly rather than trade on a
    forecast it fabricated from the settlement outcome -- see the module
    docstring.
    """


class ForecastSource(Protocol):
    """Injected, external dependency: the only path a forecast reaches a strategy."""

    def snapshot(
        self,
        *,
        station: str,
        climate_day: date,
        now: datetime,
    ) -> ForecastSnapshot | None:
        """Return the forecast usable at ``now``, or ``None`` if unavailable.

        Must never derive ``expected_high_f`` from the realized observation
        for ``(station, climate_day)`` -- see the module docstring.
        """
        ...
