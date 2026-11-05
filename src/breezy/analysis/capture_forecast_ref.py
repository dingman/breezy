"""AUT-1 forecast-reference resolution (plan r12 section 3.3.1, ruling R-B; build rulings WP0-R6).

``resolve_forecast_ref`` rebuilds the ``ForecastQuantileVector`` a decision cited from the SAME
boot's streamed ``ForecastPoint`` rows, through FQ's own accumulator
(``strategy.ladder_ev.forecast_state.ForecastQuantileState``), so a reissue overwrites exactly as it
did live. It lives in ``analysis`` because analysis may import ``strategy`` and ``persistence`` may
not. It is a non-writer: it reads a ``CaptureStream`` and returns a value.

Replay, exactly as ``ForecastQuantileStateActor.on_data`` consumes a point (the unit tests run the
real actor as the oracle, so a drift in either is a red test):

* only points of the cited station and the cited cycle, with ``available_at_ns`` at or before the
  cited vintage (a later reissue was not yet held at the decision);
* the model must be ``NBM_NBP`` and the variable one of the seven NBP variables;
* an absent point (``value_f is None``) is skipped, never pushed;
* the climate day is the point's ``valid_end_ns`` in the station's fixed standard time, and the
  model version is ``"v" + model_version``.

The result is ``RESOLVED`` only when the cycle's complete vector exists and its own vintage (the max
of its seven variables') equals the cited ``available_at_ns``; otherwise ``UNRESOLVED`` with a named
reason.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from breezy.normalize.climate_day import local_standard_date
from breezy.persistence.autonomy.capture_reader import CaptureStream
from breezy.strategy.ladder_ev.forecast_state import (
    NBP_QUANTILE_MODEL,
    NBP_QUANTILE_VARIABLES,
    ForecastQuantileState,
    ForecastQuantileVector,
)

__all__ = [
    "NBP_QUANTILE_MODEL",
    "REASON_INCOMPLETE_VECTOR",
    "REASON_NO_POINTS",
    "REASON_VINTAGE_MISMATCH",
    "ForecastRefResolution",
    "ForecastRefStatus",
    "resolve_forecast_ref",
]

REASON_NO_POINTS: Final[str] = "no_points"
REASON_INCOMPLETE_VECTOR: Final[str] = "incomplete_vector"
REASON_VINTAGE_MISMATCH: Final[str] = "vintage_mismatch"


class ForecastRefStatus(StrEnum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class ForecastRefResolution:
    status: ForecastRefStatus
    vector: ForecastQuantileVector | None = None
    reason: str = ""


def _unresolved(reason: str) -> ForecastRefResolution:
    return ForecastRefResolution(ForecastRefStatus.UNRESOLVED, None, reason)


def resolve_forecast_ref(
    stream: CaptureStream,
    station: str,
    cycle_ns: int,
    available_at_ns: int,
    *,
    std_utc_offset_hours: float,
) -> ForecastRefResolution:
    """Rebuild the vector ``(station, cycle_ns, available_at_ns)`` cited, from ``stream`` alone.

    ``std_utc_offset_hours`` is the station's fixed standard-time offset (the registry's
    ``climate_day_window``); it only derives ``ForecastQuantileVector.climate_day``.
    """
    state = ForecastQuantileState()
    pushed = 0
    for point in stream.forecast_points:
        if (
            point.station != station
            or point.cycle_runtime_ns != cycle_ns
            or point.available_at_ns > available_at_ns
            or point.model != NBP_QUANTILE_MODEL
            or point.variable not in NBP_QUANTILE_VARIABLES
            or point.value_f is None
        ):
            continue
        state.push(
            variable=point.variable,
            value_f=point.value_f,
            available_at_ns=point.available_at_ns,
            cycle_runtime_ns=point.cycle_runtime_ns,
            climate_day=local_standard_date(point.valid_end_ns, std_utc_offset_hours),
            model_version=f"v{point.model_version}",
        )
        pushed += 1
    if pushed == 0:
        return _unresolved(REASON_NO_POINTS)
    vector = state.value_at(available_at_ns)
    if vector is None or vector.cycle_runtime_ns != cycle_ns:
        return _unresolved(REASON_INCOMPLETE_VECTOR)
    if vector.available_at_ns != available_at_ns:
        return _unresolved(REASON_VINTAGE_MISMATCH)
    return ForecastRefResolution(ForecastRefStatus.RESOLVED, vector, "")
