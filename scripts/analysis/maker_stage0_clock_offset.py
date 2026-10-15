"""MAKER S2 WP0 -- the robust clock-offset (Delta) estimator behind the S-7 pre-pass (no I/O).

Plan: docs/plans/backlog/MAKER_2026-10-12/S2_stage0_replay_plan_r4_delta_s7_estimator.md.
This changes the ESTIMAND of Delta (r4 (i)3 said "max |offset_ns|"); the S-7 bound itself
(``assert_delta_within_bound``) is untouched. Verdict-blind: it reads recorder offsets only.

A recorder instance's ``VenueClockOffset`` samples are sorted by the total key
``(ts_init, offset_ns)``. Neighbours are the adjacent elements of that sequence, within ONE
instance, no further than ``MAX_NEIGHBOUR_GAP_NS`` apart (inclusive). With ``a = |offset|``::

    f = min(a, max(a_prev, a_next) + SPIKE_TOLERANCE_NS)   both neighbours confirm
    f = a                                                  otherwise (unconfirmable, counted)

The clamp runs over the full sequence BEFORE the window is applied, using RAW neighbours.
Delta of an instance-day = max ``f`` over its in-window samples; ``raw_delta_ns`` keeps the old
max ``a``. Always ``f <= a``; where the clamp fired ``f`` is the larger raw neighbour + 10 s.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import KW_ONLY, dataclass
from typing import Final

_NS: Final[int] = 1_000_000_000
SPIKE_TOLERANCE_NS: Final[int] = 10 * _NS
"""Headroom a sample may exceed its larger neighbour by before it is clamped: 10 s = 1e10 ns."""
MAX_NEIGHBOUR_GAP_NS: Final[int] = 300 * _NS
"""Largest spacing at which an adjacent sample still confirms: 5 min = 3e11 ns, inclusive."""

Samples = Sequence[tuple[int, int]]  # (ts_init, signed offset_ns)
Despiked = tuple[int, int, int, bool]  # (ts_init, signed offset_ns, filtered |offset|, confirmable)


def despike_abs_offsets(samples: Samples) -> tuple[Despiked, ...]:
    """Sorted ``(ts_init, offset_ns, filtered_abs_ns, confirmable)`` for every sample."""
    ordered = sorted(samples)
    last = len(ordered) - 1
    out: list[Despiked] = []
    for i, (ts, offset) in enumerate(ordered):
        raw = abs(offset)
        confirmed = (
            0 < i < last
            and ts - ordered[i - 1][0] <= MAX_NEIGHBOUR_GAP_NS
            and ordered[i + 1][0] - ts <= MAX_NEIGHBOUR_GAP_NS
        )
        ceiling = (
            max(abs(ordered[i - 1][1]), abs(ordered[i + 1][1])) + SPIKE_TOLERANCE_NS
            if confirmed
            else raw
        )
        out.append((ts, offset, min(raw, ceiling), confirmed))
    return tuple(out)


@dataclass(frozen=True, slots=True)
class InstanceDayDelta:
    """Delta of one recorder instance's samples in a station-day window.

    ``min_offset_ns``/``max_offset_ns`` are the RAW signed in-window extremes; ``n_despiked``
    (filtered < raw) and ``n_unconfirmable`` count in-window samples only.
    """

    delta_ns: int
    samples: int
    min_offset_ns: int
    max_offset_ns: int
    instance: str = ""
    station: str = ""
    climate_day: str = ""
    _: KW_ONLY
    raw_delta_ns: int  # the previous estimator: max |offset_ns| in the window (report only)
    n_despiked: int = 0
    n_unconfirmable: int = 0


def instance_day_deltas(
    samples_by_instance: Mapping[str, Samples], window: tuple[int, int]
) -> dict[str, InstanceDayDelta]:
    """Per instance: Delta over its samples with ``window[0] <= ts_init < window[1]``.

    An instance with no sample in the window has NO entry (unknown, never zero).
    """
    out: dict[str, InstanceDayDelta] = {}
    for instance, samples in samples_by_instance.items():
        rows = [r for r in despike_abs_offsets(samples) if window[0] <= r[0] < window[1]]
        if not rows:
            continue
        offsets = [r[1] for r in rows]
        out[instance] = InstanceDayDelta(
            max(r[2] for r in rows), len(rows), min(offsets), max(offsets),
            instance=instance,
            raw_delta_ns=max(abs(o) for o in offsets),
            n_despiked=sum(r[2] < abs(r[1]) for r in rows),
            n_unconfirmable=sum(not r[3] for r in rows),
        )  # fmt: skip
    return out


def station_day_delta(per_instance: Mapping[str, InstanceDayDelta]) -> int | None:
    """Max over instances; None (unknown, NOT zero) when no instance has a sample."""
    return max((d.delta_ns for d in per_instance.values()), default=None)


def delta_summary(deltas: Iterable[InstanceDayDelta]) -> dict[str, int | None]:
    """Report-only additions to ``delta_distribution``: the old estimator's max, and how many
    instance-day samples were clamped (a sample is counted once per station-day it serves)."""
    rows = list(deltas)
    return {
        "raw_max": max((d.raw_delta_ns for d in rows), default=None),
        "n_despiked": sum(d.n_despiked for d in rows),
    }
