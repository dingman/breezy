"""``PersistentQuantileLadderLatch`` -- SL-13: a durable, flock-backed
adapter satisfying :mod:`breezy.strategy.forecast_quantile_ladder.latch`'s
``QuantileLadderLatch`` call shape (``is_latched``/``latch``, keyed
``(station, climate_day, rung_id, side)``), so a composed
``ForecastQuantileLadderStrategy`` survives a process restart without
retaking an already-latched rung.

``latch.py``'s own ``QuantileLadderLatch`` is deliberately pure/in-memory
(SL-12's own docstring: "wiring THIS strategy's latch to that persistent
one... is SL-13's job, not this slice's"). This module is that wiring: it
never replaces ``QuantileLadderLatch``, it wraps a
:class:`~breezy.strategy.current_rung_hold.trial_day_latch.TrialDayLatch`
(the SAME persistent, flock-backed, ``SqliteStateStore``-durable latch
``ContinuousRungHoldStrategy`` already uses) behind the identical
``is_latched(*, station, climate_day, rung_id, side)`` /
``latch(*, station, climate_day, rung_id, side)`` surface --
``decision.py::evaluate`` (SL-12, unmodified) calls only these two methods,
so it works unmodified against either implementation.

``FORECAST_QUANTILE_TRIAL_KEY_PREFIX`` gives this family its OWN durable
namespace inside the shared ``SqliteStateStore`` -- never
``current_rung_hold``'s or ``continuous_rung_hold``'s own prefix, so a
forecast-mode trial can never collide with (or be mistaken for) a
current/continuous one sharing the same station-day.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Final, Literal, Protocol, runtime_checkable

from breezy.strategy.current_rung_hold.trial_day_latch import TrialDayLatch, TrialDayRecord

__all__ = [
    "FORECAST_QUANTILE_TRIAL_KEY_PREFIX",
    "InvalidLatchKeyError",
    "PersistentQuantileLadderLatch",
    "SupportsQuantileLatch",
]


@runtime_checkable
class SupportsQuantileLatch(Protocol):
    """The narrow structural surface ``decision.py::evaluate`` actually
    calls (``is_latched``/``latch``, both keyed ``(station, climate_day,
    rung_id, side)``) -- both ``latch.QuantileLadderLatch`` (SL-12, pure/
    in-memory) and :class:`PersistentQuantileLadderLatch` (SL-13, durable)
    satisfy this Protocol structurally, so a composition root can type a
    ``latch`` parameter against ONE surface accepting either, rather than
    the SL-12 concrete class specifically.
    """

    def is_latched(
        self, *, station: str, climate_day: date, rung_id: str, side: Literal["yes", "no"],
    ) -> bool: ...

    def latch(
        self, *, station: str, climate_day: date, rung_id: str, side: Literal["yes", "no"],
    ) -> None: ...

#: Must end with ``trial/`` -- ``TrialDayLatch``'s own ``_inflight_prefix``
#: asserts this (see ``trial_day_latch.py``), even though this adapter never
#: uses the IN_FLIGHT surface (a forecast-mode take is qty-1 and fully
#: latched in the SAME call, plan §3.3 -- see :meth:`PersistentQuantileLadderLatch.latch`).
FORECAST_QUANTILE_TRIAL_KEY_PREFIX: Final[str] = "forecast_quantile_ladder/trial/"

#: The one ``TrialDayRecord.reason`` this adapter ever writes -- a member of
#: ``TrialDayLatch``'s own closed ``_REASONS`` set (``REFUSAL_REASONS |
#: {"taken", TAKEN_FROM_FILL_WALK_REASON}``), which every family's trial
#: record reason must belong to.
_TAKEN_REASON: Final[str] = "taken"


class InvalidLatchKeyError(ValueError):
    """``rung_id`` or ``side`` contains ``':'`` or ``'/'``.

    Either character would corrupt the composite ``key_instrument_id`` this
    adapter builds (``':'`` is this module's own field separator; ``'/'``
    is refused by ``trial_day_latch._key`` itself, at the station/climate_day/
    instrument-id key boundary).
    """


def _composite_key(rung_id: str, side: str) -> str:
    for label, value in (("rung_id", rung_id), ("side", side)):
        if ":" in value or "/" in value:
            raise InvalidLatchKeyError(
                f"{label} must not contain ':' or '/': {value!r} -- either "
                "character would corrupt this adapter's composite latch key",
            )
    return f"{rung_id}:{side}"


class PersistentQuantileLadderLatch:
    """``QuantileLadderLatch``-shaped adapter over a persistent ``TrialDayLatch``.

    Construct one per composed station (mirrors
    ``make_trial_day_latch_factory``'s per-station ``TrialDayLatch`` binding)
    from a ``TrialDayLatch`` already opened against the shared submit-intent
    store/flock -- never a second store, never a second flock.
    """

    def __init__(
        self,
        trial_day_latch: TrialDayLatch,
        *,
        now_ns_fn: Callable[[], int] = time.time_ns,
    ) -> None:
        self._latch = trial_day_latch
        #: ``QuantileLadderLatch.latch``'s own call shape carries no
        #: timestamp (``decision.py::evaluate`` calls it with exactly
        #: ``station``/``climate_day``/``rung_id``/``side``), so this
        #: adapter stamps ``TrialDayRecord.latched_at_ns`` from an injected
        #: clock read at write time rather than leaving it a meaningless
        #: constant. Defaults to wall-clock ``time.time_ns`` -- this is a
        #: live-node adapter (never a backtest driver, which has its own
        #: `QuantileLadderLatch`), so wall-clock and ``self.clock.
        #: timestamp_ns()`` agree to within scheduling jitter.
        self._now_ns_fn = now_ns_fn

    def is_latched(
        self,
        *,
        station: str,
        climate_day: date,
        rung_id: str,
        side: Literal["yes", "no"],
    ) -> bool:
        return self._latch.is_consumed(
            station,
            climate_day.isoformat(),
            key_instrument_id=_composite_key(rung_id, side),
        )

    def latch(
        self,
        *,
        station: str,
        climate_day: date,
        rung_id: str,
        side: Literal["yes", "no"],
    ) -> None:
        """Durably latch this rung. Idempotent -- mirrors
        ``QuantileLadderLatch.latch`` exactly: latching an already-latched
        key is a no-op, never an error, and survives a process restart
        (a fresh ``TrialDayLatch`` bound to the same store observes the
        SAME durable record via :meth:`is_latched`).

        Delegates to ``TrialDayLatch.consume_if_absent`` (never ``consume``,
        which RAISES on an already-consumed key) -- this method's own
        idempotent contract is exactly ``consume_if_absent``'s.
        """
        record = TrialDayRecord(
            latched_at_ns=self._now_ns_fn(),
            instrument_id=f"{station}:{rung_id}:{side}",
            ask=Decimal(0),
            reason=_TAKEN_REASON,
        )
        self._latch.consume_if_absent(
            station,
            climate_day.isoformat(),
            record,
            key_instrument_id=_composite_key(rung_id, side),
        )
