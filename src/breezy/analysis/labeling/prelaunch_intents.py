"""Z19: the open intent after STOP (AUT-2 r7 WP5, section 3.9).

``observe_open_intent_post_stop`` reads the submit-intent singleton once, read-only, with the node
down, and returns the value for the post-STOP verdict's ``open_intent_at_poststop`` metric. Anything
that cannot be observed soundly is ``unknown``, never ``none``: no STOP signal, a live node, an
unreadable singleton.

``reconstruct_open_intent_at`` replays ``intent/history`` for the backfill. It trusts a history
record only if its ``created_ns`` is provably the one the retire path preserved (L-1 ii:
``_retired_from`` keeps ``created_ns`` and stamps ``retired_ns``); a record whose ``created_ns``
is not strictly below its ``retired_ns``, or two records for one intent id that disagree, make
the answer ``unknown``.

Until AUT-5a journals the STOP, ``unknown`` is a metric only and never an alert.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from breezy.runtime.submit_intent import SubmitIntent, SubmitIntentCorrupt, SubmitIntentState
from breezy.runtime.trade_supervisor_core import (
    PreLaunchProbeInvariantError,
    assert_no_live_node_before_intent_probe,
)

__all__ = [
    "IntentObservation",
    "Z19Counts",
    "observe_open_intent_post_stop",
    "reconstruct_open_intent_at",
    "z19_alerts",
    "z19_counts",
    "z19_line",
    "z19_observation_for_day",
]


class IntentObservation(StrEnum):
    NONE = "none"
    OPEN = "OPEN"
    AMBIGUOUS = "AMBIGUOUS"
    UNKNOWN = "unknown"


_NodePid = Callable[[], int | None]
_ReadCurrent = Callable[[], SubmitIntent | None]


def observe_open_intent_post_stop(
    *,
    stop_signal_present: bool,
    node_pid: _NodePid,
    read_current: _ReadCurrent,
    is_ambiguous: Callable[[SubmitIntent], bool] = lambda _intent: False,
) -> IntentObservation:
    """The intent state with the node down. The live-node guard runs immediately before the read."""
    if not stop_signal_present:
        return IntentObservation.UNKNOWN
    try:
        assert_no_live_node_before_intent_probe(node_pid())
        current = read_current()
    except (PreLaunchProbeInvariantError, SubmitIntentCorrupt, OSError):
        return IntentObservation.UNKNOWN
    if current is None or current.state is not SubmitIntentState.OPEN:
        return IntentObservation.NONE
    return IntentObservation.AMBIGUOUS if is_ambiguous(current) else IntentObservation.OPEN


def reconstruct_open_intent_at(history: Sequence[SubmitIntent], at_ns: int) -> IntentObservation:
    """Whether an intent was open at ``at_ns`` per the retired-intent history, or ``unknown``."""
    created: dict[str, int] = {}
    for record in history:
        retired = record.retired_ns
        if retired is None or record.created_ns >= retired:
            return IntentObservation.UNKNOWN  # created_ns preservation is unproven
        if created.setdefault(record.intent_id, record.created_ns) != record.created_ns:
            return IntentObservation.UNKNOWN
    for record in history:
        if record.retired_ns is not None and record.created_ns <= at_ns < record.retired_ns:
            return IntentObservation.OPEN
    return IntentObservation.NONE


@dataclass(frozen=True)
class Z19Counts:
    days_open: int
    n: int
    ambiguous: int
    unknown: int


def z19_observation_for_day(
    day: str, observations: Mapping[str, IntentObservation]
) -> IntentObservation:
    """A day with no post-STOP run is ``unknown``, never ``none``."""
    return observations.get(day, IntentObservation.UNKNOWN)


def z19_counts(observations: Sequence[IntentObservation]) -> Z19Counts:
    return Z19Counts(
        days_open=sum(
            1 for o in observations if o in (IntentObservation.OPEN, IntentObservation.AMBIGUOUS)
        ),
        n=len(observations),
        ambiguous=sum(1 for o in observations if o is IntentObservation.AMBIGUOUS),
        unknown=sum(1 for o in observations if o is IntentObservation.UNKNOWN),
    )


_Z19_LINE: Final = "Z19 open_intent_at_poststop days={k}/{n} ambiguous={a} unknown={u}"


def z19_line(counts: Z19Counts) -> str:
    return _Z19_LINE.format(k=counts.days_open, n=counts.n, a=counts.ambiguous, u=counts.unknown)


def z19_alerts(counts: Z19Counts) -> tuple[str, ...]:
    """``unknown`` is a metric only until AUT-5a's STOP journaling exists: never an alert."""
    return ()
