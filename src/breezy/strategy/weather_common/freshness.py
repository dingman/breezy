"""A tagged freshness value for `RiskManager.evaluate_order`'s staleness step.

WHY A NEW TYPE INSTEAD OF A SECOND SCALAR PARAMETER (F5)
----------------------------------------------------------
`RiskLimits` already carries one age-in-a-different-unit idiom,
`stale_quote_minutes`, and the obvious first move is to extend it a third
time with a bare `observation_age_hours: float` parameter alongside the
existing `forecast_age_hours: float`. That is wrong for this case, and the
reason is structural, not stylistic:

* `forecast_age_hours` and an observation's age are MUTUALLY EXCLUSIVE
  ALTERNATIVES for the SAME screening step in `evaluate_order`. A signal
  reaching risk is either forecast-derived or observation-derived, never
  both at once, so there is exactly one age to check and exactly one bound
  to check it against -- the only question is WHICH bound. Two bare float
  parameters would let a caller supply both, or neither, with no way for
  the type system to say "exactly one, and I need to know which."
* `stale_quote_minutes` (via `quote_age_minutes`) is not in this position.
  It is an INDEPENDENT, ADDITIONAL step later in `evaluate_order`'s
  sequence, checked for every order regardless of what kind of signal
  produced it. It stays its own scalar parameter because it is not an
  alternative to anything -- extending IT a third time would be the wrong
  move for the opposite reason.

A single tagged value -- one scalar, one `SignalKind` -- makes "exactly one
of two alternatives" the only representable state, and lets
`RiskLimits.max_signal_age_hours` dispatch on the tag instead of the caller
having to remember which bare parameter maps to which bound.

(`Enum` was chosen over `Literal["forecast", "observation"]` for
consistency with the existing closed-vocabulary type in this package,
`SignalKind` in `models.py`'s sibling `SideIntent(str, Enum)`; either would
have worked equally well here.)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

__all__ = ["SignalFreshness", "SignalKind"]


class SignalKind(Enum):
    """Which kind of evidence a `SignalFreshness.age_hours` measures the age of."""

    FORECAST = "forecast"
    OBSERVATION = "observation"


@dataclass(frozen=True, slots=True)
class SignalFreshness:
    """How old the evidence behind a trading signal is, and what kind it is.

    `age_hours` is hours since the evidence was PUBLISHED/PRINTED (issuance
    time), never a retrieval or ingest timestamp -- a backfilled record
    ingested days after issuance must not look fresh (R5 in the plan this
    type was introduced for).
    """

    kind: SignalKind
    age_hours: float

    @classmethod
    def forecast(cls, age_hours: float) -> SignalFreshness:
        return cls(SignalKind.FORECAST, age_hours)

    @classmethod
    def observation(cls, age_hours: float) -> SignalFreshness:
        return cls(SignalKind.OBSERVATION, age_hours)
