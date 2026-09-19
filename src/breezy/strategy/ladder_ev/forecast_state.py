"""In-memory forecast visibility for the ladder_ev forecast-mode hot path.

Nautilus Cache/catalog can store custom ``Data``, but the live decider must
not ``catalog.query`` (plan R1-11). This accumulator mirrors
``RunningExtremeAccumulator.value_at(now_ns)``: latest point with
``available_at_ns <= now_ns``, never interpolated, never a future vintage.
``ForecastPoint`` (WP-12) will push here via the actor; WP-10 is the store.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["ForecastState", "ForecastTxnSnapshot"]


@dataclass(frozen=True, slots=True)
class ForecastTxnSnapshot:
    """One visible TXN value at an ``available_at_ns`` vintage.

    Distinct from ``weather_common.models.ForecastSnapshot`` (mispricing
    predicted-high vehicle). Do not alias or re-export that name.
    """

    value_f: float
    available_at_ns: int
    cycle_runtime_ns: int


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
