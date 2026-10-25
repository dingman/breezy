"""Selector input/output records (the live twin of the replay `fill_events` selector types)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final

CENTS: Final[int] = 100  # YES price + NO price

CANCEL_PMIN: Final[str] = "CANCEL_PMIN"
CANCEL_BFLOOR: Final[str] = "CANCEL_BFLOOR"
CANCEL_STALE: Final[str] = "CANCEL_STALE"
CANCEL_DAYMISMATCH: Final[str] = "CANCEL_DAYMISMATCH"
CANCEL_HARD: Final[str] = "CANCEL_HARD"
NOT_YET_AVAILABLE: Final[str] = "NOT_YET_AVAILABLE"
DROP_REASONS: Final[frozenset[str]] = frozenset(
    {CANCEL_PMIN, CANCEL_BFLOOR, CANCEL_STALE, CANCEL_DAYMISMATCH, CANCEL_HARD, NOT_YET_AVAILABLE}
)

Level = tuple[int, int]  # (price in cents, displayed size in whole contracts)


@dataclass(frozen=True, kw_only=True)
class DepthFrame:
    """One book frame; YES asks at ``a`` cents are NO bids at ``100 - a`` cents."""

    rung_id: str
    ts_ns: int
    yes_bids: tuple[Level, ...]
    yes_asks: tuple[Level, ...]


@dataclass(frozen=True)
class Desired:
    rung_id: str
    bid_cents: int
    # Evidence for the post log only. Excluded from equality and repr so parity and
    # existing constructors (rung, cents) stay unchanged.
    p_no: float | None = field(default=None, compare=False, repr=False)
    b_max: float | None = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class Decision:
    """Selector output; ``desired`` is in rank order (first = the K1 rung)."""

    desired: tuple[Desired, ...] = ()
    drop_reason: str | None = None
    forecast_valid: bool = False
    dropped: Mapping[str, str] = field(default_factory=dict)
    # Forecast cycle that served this decision (``PNoAtInstant.cycle``). Log-only.
    cycle_ns: int | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        reasons = [*self.dropped.values(), *([self.drop_reason] if self.drop_reason else [])]
        for reason in reasons:
            if reason not in DROP_REASONS:
                raise ValueError(f"unknown drop reason {reason!r}; expected one of DROP_REASONS")
        object.__setattr__(self, "dropped", MappingProxyType(dict(self.dropped)))

    def reason_for(self, rung_id: str) -> str:
        reason = self.dropped.get(rung_id, self.drop_reason)
        if reason is None:
            raise ValueError(f"selector dropped live rung {rung_id} without a drop reason")
        return reason


@dataclass(frozen=True)
class DecisionContext:
    """What the selector may see at a decision instant."""

    now_ns: int
    books: Mapping[str, DepthFrame]
    live_bids: Mapping[str, int]
    held: frozenset[str]
