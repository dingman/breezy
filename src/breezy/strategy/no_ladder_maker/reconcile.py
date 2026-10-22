"""Turn one selector ``Decision`` into cancels and posts (live twin of the sim's ``_decide``).

Pure: no clock, no Nautilus, no I/O. The rules are those of ``maker_stage0_fill_pass.Pass._decide``:

* a live rung the decision no longer wants is cancelled (its drop reason is the decision's);
* a live rung whose wanted price differs is cancelled and re-posted only after the venue
  confirms the cancel (the caller re-runs the decision on ``OrderCanceled``);
* a wanted rung that is neither live nor held, with a book, is posted, in rank order, while
  ``held + live < max_rungs`` (a cancel in flight keeps its slot until it is confirmed).

``held`` rungs (filled) never get a second order.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from breezy.strategy.no_ladder_maker.records import Decision, Desired

__all__ = ["REPLACED", "Cancel", "Plan", "plan_actions"]

REPLACED = "REPLACED"


@dataclass(frozen=True, slots=True)
class Cancel:
    rung_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class Plan:
    cancels: tuple[Cancel, ...]
    posts: tuple[Desired, ...]


def plan_actions(
    decision: Decision,
    *,
    live: Mapping[str, int],
    cancelling: frozenset[str],
    held: frozenset[str],
    booked: frozenset[str],
    max_rungs: int,
) -> Plan:
    """The cancels and posts that move the resting set to ``decision``.

    ``live`` maps each rung with a resting (or in-flight) order to its price in cents;
    ``cancelling`` is the subset whose cancel is already in flight; ``booked`` are the rungs
    that have a book frame (a rung with no book is never an attempt).
    """
    want: dict[str, Desired] = {}
    for desired in decision.desired:
        if desired.rung_id in want:
            raise ValueError(f"duplicate rung {desired.rung_id} in Decision.desired")
        if desired.rung_id not in held:
            want[desired.rung_id] = desired
    cancels: list[Cancel] = []
    for rung, cents in live.items():
        if rung in cancelling:
            continue
        if rung not in want:
            cancels.append(Cancel(rung, decision.reason_for(rung)))
        elif want[rung].bid_cents != cents:
            cancels.append(Cancel(rung, REPLACED))
    slots = max_rungs - len(held) - len(live)
    posts: list[Desired] = []
    for rung, desired in want.items():
        if rung in live or rung not in booked:
            continue
        if slots <= 0:
            break
        posts.append(desired)
        slots -= 1
    return Plan(tuple(cancels), tuple(posts))
