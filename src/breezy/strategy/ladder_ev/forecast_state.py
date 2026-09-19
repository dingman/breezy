"""In-memory forecast visibility for the ladder_ev forecast-mode hot path.

Nautilus Cache/catalog can store custom ``Data``, but the live decider must
not ``catalog.query`` (plan R1-11). This accumulator mirrors
``RunningExtremeAccumulator.value_at(now_ns)``: latest point with
``available_at_ns <= now_ns``, never interpolated, never a future vintage.
``ForecastPoint`` is pushed here by
:class:`breezy.strategy.ladder_ev.forecast_subscriber.ForecastStateActor`
(WP-12 Seam D); WP-10 is the store.

ABSENCE IS EXPLICIT (WP-12 Seam D). ``value_at`` answering ``None`` is the
same answer whether the producing Actor is absent, has published nothing yet,
or published only absences -- and an absent forecast must never read as a
zero or as yesterday's number. :meth:`ForecastState.visibility_at` therefore
returns a NAMED verdict -- `FORECAST_UNAVAILABLE`, `FORECAST_STALE` or
`FORECAST_OK` -- and :func:`forecast_take_permitted` is the single place that
turns a verdict into "may this leg trade". A stale value is still REPORTED,
so an operator can see what was known and how old it was; it simply does not
license a take.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

__all__ = [
    "FORECAST_OK",
    "FORECAST_STALE",
    "FORECAST_UNAVAILABLE",
    "ForecastState",
    "ForecastTxnSnapshot",
    "ForecastVisibility",
    "forecast_take_permitted",
]

#: The closed verdict alphabet. Named strings, never a bare ``None``.
FORECAST_OK: Final[str] = "ok"
FORECAST_UNAVAILABLE: Final[str] = "forecast_unavailable"
FORECAST_STALE: Final[str] = "forecast_stale"


@dataclass(frozen=True, slots=True)
class ForecastTxnSnapshot:
    """One visible TXN value at an ``available_at_ns`` vintage.

    Distinct from ``weather_common.models.ForecastSnapshot`` (mispricing
    predicted-high vehicle). Do not alias or re-export that name.
    """

    value_f: float
    available_at_ns: int
    cycle_runtime_ns: int


@dataclass(frozen=True, slots=True)
class ForecastVisibility:
    """What the decider is allowed to know about the forecast at one instant.

    ``snapshot`` is ``None`` exactly when ``reason`` is
    `FORECAST_UNAVAILABLE`; a stale verdict still carries its value so the
    refusal is auditable rather than merely negative.
    """

    snapshot: ForecastTxnSnapshot | None
    reason: str
    staleness_ns: int | None


class ForecastState:
    """Per-station in-memory TXN store. Actor-push; never a catalog read.

    Eviction / climate-day reset is WP-12's actor-push concern; this store
    only answers PIT visibility.
    """

    def __init__(self) -> None:
        self._points: list[ForecastTxnSnapshot] = []

    def push(
        self,
        *,
        value_f: float | None,
        available_at_ns: int,
        cycle_runtime_ns: int,
    ) -> None:
        if value_f is None:
            return
        self._points.append(
            ForecastTxnSnapshot(
                value_f=value_f,
                available_at_ns=available_at_ns,
                cycle_runtime_ns=cycle_runtime_ns,
            )
        )

    def value_at(self, now_ns: int) -> ForecastTxnSnapshot | None:
        """Latest TXN visible at ``now_ns``, or ``None`` (forecast_unavailable)."""
        eligible = [point for point in self._points if point.available_at_ns <= now_ns]
        if not eligible:
            return None
        return max(eligible, key=lambda point: (point.available_at_ns, point.cycle_runtime_ns))

    def staleness_ns(self, now_ns: int) -> int | None:
        """``now_ns`` minus the newest VISIBLE vintage, or ``None`` if none is.

        Applies the same visibility gate as :meth:`value_at`
        (``available_at_ns <= now_ns``), so a not-yet-published point can
        never make staleness negative nor hide a genuinely stale store behind
        a vintage nobody could have known yet.
        """
        latest = self.value_at(now_ns)
        if latest is None:
            return None
        return now_ns - latest.available_at_ns

    def visibility_at(self, now_ns: int, *, max_staleness_ns: int) -> ForecastVisibility:
        """The NAMED forecast verdict at ``now_ns``.

        `max_staleness_ns` has no default on purpose: a silently-defaulted
        staleness bound is a policy decision made in the wrong file.
        """
        if max_staleness_ns <= 0:
            raise ValueError(
                f"`max_staleness_ns` must be positive, was {max_staleness_ns}",
            )
        snapshot = self.value_at(now_ns)
        if snapshot is None:
            return ForecastVisibility(
                snapshot=None, reason=FORECAST_UNAVAILABLE, staleness_ns=None,
            )
        staleness_ns = now_ns - snapshot.available_at_ns
        reason = FORECAST_STALE if staleness_ns > max_staleness_ns else FORECAST_OK
        return ForecastVisibility(
            snapshot=snapshot, reason=reason, staleness_ns=staleness_ns,
        )


def forecast_take_permitted(visibility: ForecastVisibility) -> bool:
    """Whether `visibility` licenses a forecast-mode take. Fails CLOSED.

    Only `FORECAST_OK` with a value permits one. An unknown verdict -- a
    future member of the alphabet that nobody taught this function about --
    permits nothing, so widening the alphabet can never silently widen what
    is tradable.
    """
    return visibility.reason == FORECAST_OK and visibility.snapshot is not None
