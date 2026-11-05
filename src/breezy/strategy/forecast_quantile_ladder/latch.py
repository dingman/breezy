"""QuantileLadderLatch -- first-qualifying-snapshot latch per (station-day, rung, side).

Plan §3.3: "The trial is the first executable snapshot per (station-day,
rung, side, variant) that satisfies ``ev_net > margin``... One latch; qty 1
... A new cycle never re-opens a latched rung." (`variant` is fixed per
strategy instance -- V1 taker -- so it is not part of this key.)

Pure, in-memory, process-local. SL-12 is shadow-only: this is deliberately
NOT the persistent, flock-backed
``breezy.strategy.current_rung_hold.trial_day_latch.TrialDayLatch`` that
guards the live exec submission path -- wiring THIS strategy's latch to that
persistent one (and to ``family_halt_submit_veto``/the phase-0 permit guard)
is SL-13's job, not this slice's.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

__all__ = ["QuantileLadderLatch"]

_LatchKey = tuple[str, str, str, str]


class QuantileLadderLatch:
    """At-most-one-trial-per-(station, climate_day, rung, side)."""

    def __init__(self) -> None:
        self._latched: set[_LatchKey] = set()

    @staticmethod
    def _key(
        *,
        station: str,
        climate_day: date,
        rung_id: str,
        side: Literal["yes", "no"],
    ) -> _LatchKey:
        return (station, climate_day.isoformat(), rung_id, side)

    def is_latched(
        self,
        *,
        station: str,
        climate_day: date,
        rung_id: str,
        side: Literal["yes", "no"],
    ) -> bool:
        return (
            self._key(station=station, climate_day=climate_day, rung_id=rung_id, side=side)
            in self._latched
        )

    def latch(
        self,
        *,
        station: str,
        climate_day: date,
        rung_id: str,
        side: Literal["yes", "no"],
    ) -> None:
        """Idempotent: latching an already-latched key is a no-op, never an error."""
        self._latched.add(
            self._key(station=station, climate_day=climate_day, rung_id=rung_id, side=side),
        )
