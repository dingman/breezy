"""Replay-sufficiency census core (AUD-09a; AUD-09b amendment Rev 2.1 Stage A).

Classifies each ``(station, climate_day)`` seen in the quote-tape capture as
``SUFFICIENT``/``INSUFFICIENT`` for a single-day paper replay, from
disk-derived facts only. This module never touches disk itself -- the
companion script, ``scripts/analysis/replay_sufficiency_census.py``, performs
every read (feather preflight, catalog conversion) and hands this module pure
:class:`InstanceSpan` values, exactly the split ``cli_basis_offer_gate_scan.py``
already uses between its I/O and its ``classify_instance``/``classify_blocked_reason``
cores.

**Winner rule** (``docs/plans/WHOLE_TAPE_PAPER_REPLAY_2026-09-05.md``,
"De-dup BEFORE replay"; memory ``paper-replay-instance-selection`` records the
zero-fill trap a first-listed instance caused): key ``(station, climate_day)``
only; the winner is the ``CLEAN`` instance with the longest in-window Depth10
span.

**Overlap winner rule (AUD-09b amendment Stage B, §3)**: two or more
eligible (``span_ns >= `` :data:`MIN_DEPTH_WINDOW_NS`) ``CLEAN`` instances no
longer always refuse the pair. A genuine overlap -- pairwise
``min(last_i, last_j) - max(first_i, first_j)`` exceeding
:data:`OVERLAP_TOLERANCE_NS` -- still refuses
(``AMBIGUOUS_WINNER_OVERLAPPING_CLEAN_GE_30MIN``: two writers plausibly
touched the same instant). Otherwise every eligible pair is DISJOINT (a
sequential recorder restart split one afternoon into fragments), and the
longest fragment wins by ``(-span_ns, first_ns, instance_id)`` -- still no
first-list, no stitch, no union: the losing fragment's hours are never
replayed. That loss is recorded, never hidden: ``coverage_kind`` is
``"FRAGMENT"`` whenever any other ``CLEAN`` instance has a date-scoped event
outside the winner's own ``[first, last]``, and ``excluded_fragments`` names
each such instance's own extent.

**Coverage basis is DEPTH, not quotes**: v3 hunts Depth10 (L-35), and at
``L2_MBP`` the QuoteTick tape is inert for execution
(``BACKTEST_VENUE_CONFIG.md:144-150``). Both spans are reported on every row,
but the verdict decides on depth -- SHARING the window definition with
``assert_decision_window_has_coverage(..., source="depth")``
(``scripts/analysis/current_rung_hold_paper_replay.py:257``) and with the KILL
clock's own ``structural_dead_stop.py`` (B21). The remaining differences are
real and are NOT claimed away here: the KILL clock counts every depth instant
across rungs of the MERGED tape catalog and subtracts resolved
``QuoteTapeGap`` intervals, while this census counts PER INSTANCE, executable
asks only (``best_order``), with no gap handling. "Cannot disagree about
covered" was an overclaim; the shared piece is the window, nothing more.

**Date scoping (AUD-09b amendment Rev 2.1, F3)**: the daily 09:00Z recorder
rotation (``breezy-quote-tape-rotate.service``) opens a fresh instance every
day, so a market listed the day before gives the earlier instance ``D-1``'s
afternoon depth for a ``D`` market. :func:`decision_window_ns` and
:func:`window_extent` scope the decision window by BOTH date and hour (ns
precision, integer arithmetic only), replacing the hour-only filter this
module used to leave to the script.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from breezy.domain.climate_day import standard_time_zone

__all__ = [
    "AMBIGUOUS_WINNER_OVERLAPPING_CLEAN_GE_30MIN",
    "CANDIDATE_UNSUPPORTED_STATION",
    "CORRUPT_ONLY",
    "DECISION_WINDOW_END_LST",
    "DECISION_WINDOW_START_LST",
    "DEPTH_WINDOW_UNDER_30MIN",
    "INGEST_INSTANCE_REFUSED",
    "MIN_DEPTH_WINDOW_MINUTES",
    "MIN_DEPTH_WINDOW_NS",
    "NO_CLEAN_INSTANCE",
    "NO_IN_WINDOW_DEPTH",
    "OVERLAP_TOLERANCE_NS",
    "REPLAY_SUFFICIENCY_REASONS",
    "REPLAY_SUFFICIENCY_SCHEMA_VERSION",
    "VENUE_NEVER_LISTED_UNCONFIRMED",
    "WINDOW_EDGE_TOLERANCE_NS",
    "DuplicateReplaySufficiencyRecordError",
    "FragmentSpan",
    "InstanceSpan",
    "InstanceVerdict",
    "ReplaySufficiency",
    "ReplaySufficiencyRecordError",
    "ReplaySufficiencyVerdict",
    "UnknownReplaySufficiencySchemaError",
    "WindowExtent",
    "classify_station_day",
    "count_live_instances_in_window",
    "decision_window_ns",
    "read_replay_sufficiency",
    "window_extent",
    "write_replay_sufficiency",
]

#: Hand-off H0 (AUD-09 plan §6a): every writer/reader agrees on this version.
#: Bumped to 3 by the AUD-09b amendment Stage B (§3): the MEANING of the
#: rows changed again (the overlap winner rule replaces the old
#: two-CLEAN-instances-always-refuse rule, and every row now carries
#: ``coverage_kind``/``excluded_fragments``), so a v1 or v2 line is refused
#: rather than silently misread.
REPLAY_SUFFICIENCY_SCHEMA_VERSION: Final[int] = 3

#: Matches ``structural_dead_stop.py``'s own >=30 min afternoon-coverage rule
#: (``scripts/analysis/ma_prelock_winner_ask_study.MIN_AFTERNOON_COVERAGE_MINUTES``,
#: rule applied at ``structural_dead_stop.py:214``), so the census and the
#: KILL clock share the WINDOW definition (B21 -- not "cannot disagree about
#: covered"; see the module docstring). Declared locally rather than
#: imported: that module lives in ``scripts/``, unimportable from
#: ``src/breezy/**`` -- the same reasoning :data:`InstanceVerdict` documents.
MIN_DEPTH_WINDOW_MINUTES: Final[float] = 30.0

#: AUD-09b amendment Stage B (§3): the SAME 30-minute eligibility floor as
#: :data:`MIN_DEPTH_WINDOW_MINUTES`, expressed in integer nanoseconds and
#: computed directly from an instance's ``first_in_window_ns``/
#: ``last_in_window_ns`` (C1's date-scoped extents), never from the derived
#: float ``depth_window_minutes``. Used only by the Stage B overlap rule.
MIN_DEPTH_WINDOW_NS: Final[int] = 30 * 60 * 1_000_000_000

#: AUD-09b amendment Stage B (§3): two eligible CLEAN instances whose
#: in-window depth overlaps by MORE than this many nanoseconds are a genuine
#: duplicate and stay ``AMBIGUOUS_WINNER_OVERLAPPING_CLEAN_GE_30MIN``.
#: Touching intervals and an overlap of EXACTLY this value count as disjoint.
#: 60 s is far below the 30-minute floor (so a real duplicate can hide at
#: most 60 s) and above zero (to absorb a boot-snapshot ``ts_event`` at a
#: recorder handoff).
OVERLAP_TOLERANCE_NS: Final[int] = 60 * 1_000_000_000

#: The decision window is local-STANDARD-time ``[12:00, 17:00)`` -- the same
#: bounds ``ma_prelock_winner_ask_study.AFTERNOON_WINDOW_START/END`` and
#: ``current_rung_hold_paper_replay``'s own hour constants use.
DECISION_WINDOW_START_LST: Final[dt.time] = dt.time(12, 0)
DECISION_WINDOW_END_LST: Final[dt.time] = dt.time(17, 0)

#: C2a: a winner within this many nanoseconds of BOTH window edges is
#: `window_complete`. 5 minutes, re-reviewed after Stage 0 measures the real
#: edge-distance distribution.
WINDOW_EDGE_TOLERANCE_NS: Final[int] = 5 * 60 * 1_000_000_000

_EPOCH: Final[dt.datetime] = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)
_US_PER_UNIT: Final[dt.timedelta] = dt.timedelta(microseconds=1)
_NS_PER_US: Final[int] = 1_000

#: The closed refusal-reason alphabet (AUD-09 plan §6a), each traceable to a
#: measured cause. Exactly one never-listed token exists --
#: ``VENUE_NEVER_LISTED_UNCONFIRMED`` -- because the census never probes the
#: venue; a bare ``VENUE_NEVER_LISTED`` would claim a fact only a by-slug
#: probe can establish (memory ``venue-skips-station-days``).
NO_CLEAN_INSTANCE: Final[str] = "NO_CLEAN_INSTANCE"
#: AUD-09b amendment Stage B (§3): replaces the pre-Stage-B "two eligible
#: CLEAN instances always refuse the pair" token, which is now false text --
#: only a genuine overlap (> :data:`OVERLAP_TOLERANCE_NS`) refuses the pair.
#: The old token is never emitted and no longer exists in this module (B-f).
AMBIGUOUS_WINNER_OVERLAPPING_CLEAN_GE_30MIN: Final[str] = (
    "AMBIGUOUS_WINNER_OVERLAPPING_CLEAN_GE_30MIN"
)
DEPTH_WINDOW_UNDER_30MIN: Final[str] = "DEPTH_WINDOW_UNDER_30MIN"
NO_IN_WINDOW_DEPTH: Final[str] = "NO_IN_WINDOW_DEPTH"
VENUE_NEVER_LISTED_UNCONFIRMED: Final[str] = "VENUE_NEVER_LISTED_UNCONFIRMED"
INGEST_INSTANCE_REFUSED: Final[str] = "INGEST_INSTANCE_REFUSED"
CORRUPT_ONLY: Final[str] = "CORRUPT_ONLY"
CANDIDATE_UNSUPPORTED_STATION: Final[str] = "CANDIDATE_UNSUPPORTED_STATION"

REPLAY_SUFFICIENCY_REASONS: Final[frozenset[str]] = frozenset(
    {
        NO_CLEAN_INSTANCE,
        AMBIGUOUS_WINNER_OVERLAPPING_CLEAN_GE_30MIN,
        DEPTH_WINDOW_UNDER_30MIN,
        NO_IN_WINDOW_DEPTH,
        VENUE_NEVER_LISTED_UNCONFIRMED,
        INGEST_INSTANCE_REFUSED,
        CORRUPT_ONLY,
        CANDIDATE_UNSUPPORTED_STATION,
    }
)

#: Deliberately the SAME four-value alphabet as
#: ``scripts/analysis/cli_basis_offer_gate_scan.InstanceVerdict`` (``:247``),
#: produced there by ``classify_instance`` from a ``PreflightReport``. It is
#: declared locally, not imported, because that module lives in
#: ``scripts/analysis/`` and is unimportable from ``src/breezy/**``.
#: ``tests/unit/test_replay_sufficiency.py`` pins the two literal sets equal
#: (B15) so they cannot silently drift apart.
InstanceVerdict = Literal["CLEAN", "EMPTY", "LIVE", "CORRUPT"]

ReplaySufficiencyVerdict = Literal["SUFFICIENT", "INSUFFICIENT"]


def decision_window_ns(*, climate_day: dt.date, std_utc_offset_hours: float) -> tuple[int, int]:
    """Half-open ``[12:00, 17:00)`` local-standard-time window, in epoch ns.

    Integer arithmetic only (AUD-09b amendment Rev 2.1 C1): the timedelta
    between two timezone-aware ``datetime``s has microsecond resolution
    exactly, so floor-dividing it by one microsecond and scaling to
    nanoseconds never rounds -- unlike ``structural_dead_stop._afternoon_window_ns``'s
    ``timestamp() * 1_000_000_000`` float path, which this function
    deliberately avoids.
    """
    tz = standard_time_zone(std_utc_offset_hours)
    start = dt.datetime.combine(climate_day, DECISION_WINDOW_START_LST, tzinfo=tz)
    end = dt.datetime.combine(climate_day, DECISION_WINDOW_END_LST, tzinfo=tz)
    start_ns = ((start - _EPOCH) // _US_PER_UNIT) * _NS_PER_US
    end_ns = ((end - _EPOCH) // _US_PER_UNIT) * _NS_PER_US
    return start_ns, end_ns


@dataclass(frozen=True, slots=True, kw_only=True)
class WindowExtent:
    """The first/last in-window instant and the span between them.

    Half-open window: an instant is in-window iff ``start_ns <= ts < end_ns``.
    ``first_ns``/``last_ns`` are ``None`` with zero in-window instants;
    ``span_ns`` is ``0`` with fewer than two (a single snapshot covers no
    span -- the same rule ``ma_prelock_winner_ask_study.afternoon_coverage_minutes``
    applies).
    """

    first_ns: int | None
    last_ns: int | None
    span_ns: int


def window_extent(ts_event_ns: Iterable[int], *, start_ns: int, end_ns: int) -> WindowExtent:
    """Pure: first/last/span of the instants inside ``[start_ns, end_ns)``.

    Date-scoped by construction: `start_ns`/`end_ns` (from
    :func:`decision_window_ns`) already carry the climate day, so an instant
    on a DIFFERENT day never matches even if its LOCAL HOUR is inside
    ``[12, 17)`` -- the AUD-09b amendment's F3 fix.
    """
    in_window = sorted(ts for ts in ts_event_ns if start_ns <= ts < end_ns)
    if not in_window:
        return WindowExtent(first_ns=None, last_ns=None, span_ns=0)
    first_ns, last_ns = in_window[0], in_window[-1]
    span_ns = (last_ns - first_ns) if len(in_window) >= 2 else 0
    return WindowExtent(first_ns=first_ns, last_ns=last_ns, span_ns=span_ns)


def count_live_instances_in_window(
    capture_start_ns_values: Sequence[int], *, window_end_ns: int,
) -> int:
    """C3/B7: count LIVE instances whose CAPTURE START precedes the window's end.

    ``capture_start_ns_values`` holds one entry per LIVE instance whose own
    ``binary_option`` registrations named this ``(station, climate_day)``.
    Registration rows span ``D-1..D+1`` (a listing can appear well before or
    after the market trades), so registration alone must never count -- only
    an instance whose capture actually started before the window closes can
    plausibly have captured any of it.
    """
    return sum(
        1 for capture_start_ns in capture_start_ns_values if capture_start_ns < window_end_ns
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class FragmentSpan:
    """One losing CLEAN instance's own extent, excluded from a FRAGMENT winner
    (AUD-09b amendment Stage B, C4's pinned shape).

    Exactly these three fields -- the closed JSON shape ``{"instance_id":
    str, "first_in_window_ns": int, "last_in_window_ns": int}`` -- so a
    :class:`ReplaySufficiency` row records WHICH hours were never replayed,
    never a stitch or union of them.
    """

    instance_id: str
    first_in_window_ns: int
    last_in_window_ns: int


@dataclass(frozen=True, slots=True, kw_only=True)
class InstanceSpan:
    """One instance's contribution to one ``(station, climate_day)``.

    A pure value the SCRIPT builds from real feather/catalog reads; this
    module never constructs one from disk.

    ``first_in_window_ns``/``last_in_window_ns`` (AUD-09b amendment C2a) are
    the same bounds a :class:`WindowExtent` over this instance's executable
    depth instants would report; ``depth_window_minutes`` is DERIVED from
    that span for reporting only -- eligibility comparisons in
    :func:`classify_station_day` stay on ``depth_window_minutes`` (the
    existing rule, unchanged -- AUD-09b amendment A3), which is itself now
    computed from the ns-precision span rather than an independent float
    timestamp reduction.
    """

    instance_id: str
    verdict: InstanceVerdict
    depth_window_minutes: float
    quote_window_minutes: float
    distinct_instruments: int
    first_in_window_ns: int | None = None
    last_in_window_ns: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplaySufficiency:
    """One census row: whether ``(station, climate_day)`` can be replayed.

    ``reason`` is the empty string for a ``SUFFICIENT`` verdict; for
    ``INSUFFICIENT`` it is one member of :data:`REPLAY_SUFFICIENCY_REASONS`.

    AUD-09b amendment Stage A (C2a/C3) fields: ``window_start_ns``/
    ``window_end_ns`` are the row's own decision window (schema v2, always
    populated for a station known to the registry; ``0`` for a
    ``CANDIDATE_UNSUPPORTED_STATION`` row, which has no registry offset).
    ``winner_first_in_window_ns``/``winner_last_in_window_ns`` are ``None``
    for an ``INSUFFICIENT`` row (no winner). ``window_complete`` is true iff
    the winner's edges are each within :data:`WINDOW_EDGE_TOLERANCE_NS` of
    the window's own edges. ``live_instance_count`` is the count from
    :func:`count_live_instances_in_window` for this ``(station,
    climate_day)``.

    AUD-09b amendment Stage B (§3) fields: ``coverage_kind`` is ``"WHOLE"``
    unless some OTHER ``CLEAN`` instance has a date-scoped event outside the
    winner's own ``[winner_first_in_window_ns, winner_last_in_window_ns]``,
    in which case it is ``"FRAGMENT"`` -- the winner's hours are real but
    incomplete for the day. ``excluded_fragments`` names each such losing
    instance's own extent (C4's pinned shape), sorted by
    ``(first_in_window_ns, instance_id)``. Both default to the degenerate
    ``"WHOLE"``/``()`` for every ``INSUFFICIENT`` row (no winner, nothing
    excluded).
    """

    schema_version: int
    station: str
    climate_day: str
    verdict: ReplaySufficiencyVerdict
    reason: str
    winner_instance_id: str | None
    depth_window_minutes: float
    quote_window_minutes: float
    distinct_instruments: int
    computed_day: str
    window_start_ns: int
    window_end_ns: int
    winner_first_in_window_ns: int | None
    winner_last_in_window_ns: int | None
    window_complete: bool
    live_instance_count: int
    coverage_kind: str
    excluded_fragments: tuple[FragmentSpan, ...]

    def to_dict(self) -> dict[str, object]:
        """Explicit field-by-field row -- never ``dataclasses.asdict`` (AUD-09b
        amendment C4; the credential-serialisation guard bans every
        ``asdict(...)`` call site outside a closed allowlist that does not
        include this module)."""
        return {
            "schema_version": self.schema_version,
            "station": self.station,
            "climate_day": self.climate_day,
            "verdict": self.verdict,
            "reason": self.reason,
            "winner_instance_id": self.winner_instance_id,
            "depth_window_minutes": self.depth_window_minutes,
            "quote_window_minutes": self.quote_window_minutes,
            "distinct_instruments": self.distinct_instruments,
            "computed_day": self.computed_day,
            "window_start_ns": self.window_start_ns,
            "window_end_ns": self.window_end_ns,
            "winner_first_in_window_ns": self.winner_first_in_window_ns,
            "winner_last_in_window_ns": self.winner_last_in_window_ns,
            "window_complete": self.window_complete,
            "live_instance_count": self.live_instance_count,
            "coverage_kind": self.coverage_kind,
            "excluded_fragments": [
                {
                    "instance_id": fragment.instance_id,
                    "first_in_window_ns": fragment.first_in_window_ns,
                    "last_in_window_ns": fragment.last_in_window_ns,
                }
                for fragment in self.excluded_fragments
            ],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> ReplaySufficiency:
        """Reconstruct from a :meth:`to_dict` payload; never ``cls(**payload)``.

        Raises :class:`ReplaySufficiencyRecordError`, naming the offending
        key, on a missing key, an extra key, or a key whose type is wrong --
        never a bare ``TypeError`` from the dataclass constructor pointing at
        a positional slot instead of a JSON key.
        """
        keys = set(payload)
        known_keys = _RECORD_FIELD_TYPES.keys() | _LIST_RECORD_FIELDS
        missing = known_keys - keys
        if missing:
            raise ReplaySufficiencyRecordError(
                f"replay_sufficiency record missing key(s): {sorted(missing)}"
            )
        extra = keys - known_keys
        if extra:
            raise ReplaySufficiencyRecordError(
                f"replay_sufficiency record has unexpected key(s): {sorted(extra)}"
            )
        excluded_fragments = _parse_excluded_fragments(payload["excluded_fragments"])
        for name, expected_type in _RECORD_FIELD_TYPES.items():
            value = payload[name]
            if value is None:
                if name in _NULLABLE_RECORD_FIELDS:
                    continue
                raise ReplaySufficiencyRecordError(f"{name!r} must not be null")
            # `bool` is a subclass of `int` in Python -- checked first so an
            # `int` field never silently accepts a bool, and a `bool` field
            # never silently accepts a plain int.
            is_bool_value = isinstance(value, bool)
            if expected_type is bool and not is_bool_value:
                raise ReplaySufficiencyRecordError(
                    f"{name!r} must be a bool, got {type(value).__name__}"
                )
            if expected_type is int and (not isinstance(value, int) or is_bool_value):
                raise ReplaySufficiencyRecordError(
                    f"{name!r} must be an int, got {type(value).__name__}"
                )
            if expected_type is float and not isinstance(value, float):
                raise ReplaySufficiencyRecordError(
                    f"{name!r} must be a float, got {type(value).__name__}"
                )
            if expected_type is str and not isinstance(value, str):
                raise ReplaySufficiencyRecordError(
                    f"{name!r} must be a str, got {type(value).__name__}"
                )
        return cls(
            schema_version=payload["schema_version"],  # type: ignore[arg-type]
            station=payload["station"],  # type: ignore[arg-type]
            climate_day=payload["climate_day"],  # type: ignore[arg-type]
            verdict=payload["verdict"],  # type: ignore[arg-type]
            reason=payload["reason"],  # type: ignore[arg-type]
            winner_instance_id=payload["winner_instance_id"],  # type: ignore[arg-type]
            depth_window_minutes=payload["depth_window_minutes"],  # type: ignore[arg-type]
            quote_window_minutes=payload["quote_window_minutes"],  # type: ignore[arg-type]
            distinct_instruments=payload["distinct_instruments"],  # type: ignore[arg-type]
            computed_day=payload["computed_day"],  # type: ignore[arg-type]
            window_start_ns=payload["window_start_ns"],  # type: ignore[arg-type]
            window_end_ns=payload["window_end_ns"],  # type: ignore[arg-type]
            winner_first_in_window_ns=payload["winner_first_in_window_ns"],  # type: ignore[arg-type]
            winner_last_in_window_ns=payload["winner_last_in_window_ns"],  # type: ignore[arg-type]
            window_complete=payload["window_complete"],  # type: ignore[arg-type]
            live_instance_count=payload["live_instance_count"],  # type: ignore[arg-type]
            coverage_kind=payload["coverage_kind"],  # type: ignore[arg-type]
            excluded_fragments=excluded_fragments,
        )


#: The closed, pinned JSON shape (AUD-09b amendment C4). Order is
#: documentation only -- JSON objects are unordered -- but mirrors
#: `to_dict`'s own emission order for legibility.
_RECORD_FIELD_TYPES: Final[dict[str, type]] = {
    "schema_version": int,
    "station": str,
    "climate_day": str,
    "verdict": str,
    "reason": str,
    "winner_instance_id": str,
    "depth_window_minutes": float,
    "quote_window_minutes": float,
    "distinct_instruments": int,
    "computed_day": str,
    "window_start_ns": int,
    "window_end_ns": int,
    "winner_first_in_window_ns": int,
    "winner_last_in_window_ns": int,
    "window_complete": bool,
    "live_instance_count": int,
    "coverage_kind": str,
}

#: `excluded_fragments` is a list, not a scalar -- validated separately by
#: :func:`_parse_excluded_fragments`, but still a required top-level key
#: (AUD-09b amendment Stage B, C4).
_LIST_RECORD_FIELDS: Final[frozenset[str]] = frozenset({"excluded_fragments"})

#: `FragmentSpan`'s own closed JSON shape (C4), nested inside each
#: `excluded_fragments` entry.
_FRAGMENT_FIELD_TYPES: Final[dict[str, type]] = {
    "instance_id": str,
    "first_in_window_ns": int,
    "last_in_window_ns": int,
}

#: Fields legitimately `None` -- an `INSUFFICIENT` row has no winner.
_NULLABLE_RECORD_FIELDS: Final[frozenset[str]] = frozenset(
    {"winner_instance_id", "winner_first_in_window_ns", "winner_last_in_window_ns"}
)


def _parse_excluded_fragments(payload: object) -> tuple[FragmentSpan, ...]:
    """Validate and reconstruct C4's pinned `excluded_fragments` shape.

    Raises :class:`ReplaySufficiencyRecordError` on anything but a list of
    objects carrying exactly `_FRAGMENT_FIELD_TYPES`'s keys with the right
    types -- never a bare `TypeError`/`KeyError`.
    """
    if not isinstance(payload, list):
        raise ReplaySufficiencyRecordError(
            f"'excluded_fragments' must be a list, got {type(payload).__name__}"
        )
    fragments: list[FragmentSpan] = []
    for entry in payload:
        if not isinstance(entry, Mapping):
            raise ReplaySufficiencyRecordError(
                f"'excluded_fragments' entry must be an object, got {type(entry).__name__}"
            )
        entry_keys = set(entry)
        expected_keys = _FRAGMENT_FIELD_TYPES.keys()
        if entry_keys != expected_keys:
            raise ReplaySufficiencyRecordError(
                "'excluded_fragments' entry has the wrong key(s): "
                f"missing {sorted(expected_keys - entry_keys)}, "
                f"extra {sorted(entry_keys - expected_keys)}"
            )
        for name, expected_type in _FRAGMENT_FIELD_TYPES.items():
            value = entry[name]
            is_bool_value = isinstance(value, bool)
            if expected_type is int and (not isinstance(value, int) or is_bool_value):
                raise ReplaySufficiencyRecordError(
                    f"'excluded_fragments' entry {name!r} must be an int, "
                    f"got {type(value).__name__}"
                )
            if expected_type is str and not isinstance(value, str):
                raise ReplaySufficiencyRecordError(
                    f"'excluded_fragments' entry {name!r} must be a str, "
                    f"got {type(value).__name__}"
                )
        fragments.append(
            FragmentSpan(
                instance_id=entry["instance_id"],  # type: ignore[arg-type]
                first_in_window_ns=entry["first_in_window_ns"],  # type: ignore[arg-type]
                last_in_window_ns=entry["last_in_window_ns"],  # type: ignore[arg-type]
            )
        )
    return tuple(fragments)


class ReplaySufficiencyRecordError(Exception):
    """``ReplaySufficiency.from_dict`` refuses a malformed payload.

    Raised on a missing key, an extra key, or a key whose type is wrong --
    named explicitly, never a bare ``TypeError`` from ``cls(**payload)``
    naming a positional slot instead of the JSON key that caused it.
    """


class UnknownReplaySufficiencySchemaError(Exception):
    """A ``replay_sufficiency.jsonl`` line names an unrecognised ``schema_version``.

    Refuses rather than silently reading a stale or future shape: "no work"
    and "unreadable work list" must never look alike (H0). A v1 line is
    refused by construction once :data:`REPLAY_SUFFICIENCY_SCHEMA_VERSION`
    reads 2 -- the meaning of the spans changed (AUD-09b amendment C2a).
    """


class DuplicateReplaySufficiencyRecordError(Exception):
    """Two lines in ``replay_sufficiency.jsonl`` share one ``(station,
    climate_day)`` key -- a hard error, never last-wins: a duplicate means two
    writers raced and the file cannot be trusted."""


def _window_complete(
    *, winner: InstanceSpan | None, window_start_ns: int, window_end_ns: int,
) -> bool:
    if winner is None or winner.first_in_window_ns is None or winner.last_in_window_ns is None:
        return False
    return (
        winner.first_in_window_ns - window_start_ns <= WINDOW_EDGE_TOLERANCE_NS
        and window_end_ns - winner.last_in_window_ns <= WINDOW_EDGE_TOLERANCE_NS
    )


def classify_station_day(
    *,
    station: str,
    climate_day: str,
    instances: Sequence[InstanceSpan],
    computed_day: str,
    window_start_ns: int = 0,
    window_end_ns: int = 0,
    live_instance_count: int = 0,
) -> ReplaySufficiency:
    """``SUFFICIENT``/``INSUFFICIENT`` verdict for one ``(station, climate_day)``.

    ``instances`` carries every :class:`InstanceSpan` the script found
    touching this station-day, regardless of verdict. ``LIVE`` instances are
    never a winner (the writer may still be appending) and, absent a
    ``CLEAN`` instance for the same day, fall into ``NO_CLEAN_INSTANCE``
    exactly like ``EMPTY``.

    ``window_start_ns``/``window_end_ns``/``live_instance_count`` default to
    ``0`` so every pre-AUD-09b-amendment call site keeps working unchanged;
    the real census script (``run_census``) always supplies the true values
    computed via :func:`decision_window_ns` and
    :func:`count_live_instances_in_window`.

    AUD-09b amendment Stage B (§3): eligibility for the overlap rule below is
    ``span_ns >= `` :data:`MIN_DEPTH_WINDOW_NS`, computed from
    ``first_in_window_ns``/``last_in_window_ns`` when both are set (the real,
    production shape) -- see :func:`_span_ns` for the minutes-based fallback
    that keeps a synthetic caller lacking ns fields at Stage A's unchanged
    behaviour (A3). Two eligible instances that overlap by more than
    :data:`OVERLAP_TOLERANCE_NS`, OR either of which lacks a real ns extent
    to check, stay ``AMBIGUOUS_WINNER_OVERLAPPING_CLEAN_GE_30MIN`` --
    disjointness is only ever claimed with ns evidence.
    """
    clean = [instance for instance in instances if instance.verdict == "CLEAN"]

    if not clean:
        if instances and all(instance.verdict == "CORRUPT" for instance in instances):
            reason = CORRUPT_ONLY
        else:
            reason = NO_CLEAN_INSTANCE
        return _insufficient(
            station=station,
            climate_day=climate_day,
            reason=reason,
            computed_day=computed_day,
            window_start_ns=window_start_ns,
            window_end_ns=window_end_ns,
            live_instance_count=live_instance_count,
        )

    eligible = [instance for instance in clean if _span_ns(instance) >= MIN_DEPTH_WINDOW_NS]

    if len(eligible) >= 2:
        overlapping = any(
            _pair_overlaps(a, b) for i, a in enumerate(eligible) for b in eligible[i + 1 :]
        )
        if overlapping:
            best = _longest_depth(eligible)
            return _insufficient(
                station=station,
                climate_day=climate_day,
                reason=AMBIGUOUS_WINNER_OVERLAPPING_CLEAN_GE_30MIN,
                computed_day=computed_day,
                depth_window_minutes=best.depth_window_minutes,
                quote_window_minutes=best.quote_window_minutes,
                distinct_instruments=best.distinct_instruments,
                window_start_ns=window_start_ns,
                window_end_ns=window_end_ns,
                live_instance_count=live_instance_count,
            )
        return _sufficient(
            station=station,
            climate_day=climate_day,
            winner=_pick_winner(eligible),
            clean=clean,
            computed_day=computed_day,
            window_start_ns=window_start_ns,
            window_end_ns=window_end_ns,
            live_instance_count=live_instance_count,
        )

    if eligible:
        return _sufficient(
            station=station,
            climate_day=climate_day,
            winner=eligible[0],
            clean=clean,
            computed_day=computed_day,
            window_start_ns=window_start_ns,
            window_end_ns=window_end_ns,
            live_instance_count=live_instance_count,
        )

    best = _longest_depth(clean)
    reason = DEPTH_WINDOW_UNDER_30MIN if best.depth_window_minutes > 0.0 else NO_IN_WINDOW_DEPTH
    return _insufficient(
        station=station,
        climate_day=climate_day,
        reason=reason,
        computed_day=computed_day,
        depth_window_minutes=best.depth_window_minutes,
        quote_window_minutes=best.quote_window_minutes,
        distinct_instruments=best.distinct_instruments,
        window_start_ns=window_start_ns,
        window_end_ns=window_end_ns,
        live_instance_count=live_instance_count,
    )


def _longest_depth(instances: Sequence[InstanceSpan]) -> InstanceSpan:
    """The instance with the longest depth span, ties broken by id for determinism."""
    return max(
        instances, key=lambda instance: (instance.depth_window_minutes, instance.instance_id)
    )


_NS_PER_MINUTE: Final[int] = 60_000_000_000


def _span_ns(instance: InstanceSpan) -> int:
    """AUD-09b amendment Stage B (§3): the ns-precision span `window_extent`
    would report for this instance's own in-window instants.

    When both edges are set (the real, production shape -- every
    `InstanceSpan` the census script builds), this IS that span. When either
    edge is unset -- a synthetic/legacy caller that only populated
    `depth_window_minutes` -- falls back to that derived value converted to
    ns, so a caller that never populates the ns fields keeps exactly Stage
    A's `depth_window_minutes`-based eligibility (unchanged, A3) rather than
    becoming spuriously ineligible.
    """
    if instance.first_in_window_ns is not None and instance.last_in_window_ns is not None:
        return instance.last_in_window_ns - instance.first_in_window_ns
    return int(instance.depth_window_minutes * _NS_PER_MINUTE)


def _first_ns_sort_key(instance: InstanceSpan) -> int:
    """`first_in_window_ns`, or `0` for a synthetic instance that never set
    it -- only reached when `_span_ns`'s minutes fallback already made it
    eligible; never raises comparing `None` against a real `int`."""
    return instance.first_in_window_ns if instance.first_in_window_ns is not None else 0


def _overlap_ns(a: InstanceSpan, b: InstanceSpan) -> int | None:
    """AUD-09b amendment Stage B (§3): `min(last, last) - max(first, first)`.

    `None` when either side lacks a REAL ns extent -- treated conservatively
    as an overlap (AMBIGUOUS) by the caller, exactly matching Stage A's
    original behaviour for any two eligible CLEAN instances (never a
    disjoint-fragment claim without the ns precision to back it).
    """
    if a.first_in_window_ns is None or a.last_in_window_ns is None:
        return None
    if b.first_in_window_ns is None or b.last_in_window_ns is None:
        return None
    return min(a.last_in_window_ns, b.last_in_window_ns) - max(
        a.first_in_window_ns, b.first_in_window_ns,
    )


def _pair_overlaps(a: InstanceSpan, b: InstanceSpan) -> bool:
    """`True` on a genuine overlap (> `OVERLAP_TOLERANCE_NS`) OR when either
    side lacks the ns evidence to prove disjointness (fail toward AMBIGUOUS)."""
    overlap = _overlap_ns(a, b)
    return overlap is None or overlap > OVERLAP_TOLERANCE_NS


def _pick_winner(eligible: Sequence[InstanceSpan]) -> InstanceSpan:
    """AUD-09b amendment Stage B (§3): `(-span_ns, first_ns, instance_id)`.

    The longest fragment wins; a tie goes to the earlier one; a tie on both
    goes to the lexicographically smaller `instance_id` -- identical for
    every permutation of the input (B22/B-e).
    """
    return min(
        eligible,
        key=lambda instance: (
            -_span_ns(instance),
            _first_ns_sort_key(instance),
            instance.instance_id,
        ),
    )


def _fragment_analysis(
    *, winner: InstanceSpan, clean: Sequence[InstanceSpan],
) -> tuple[str, tuple[FragmentSpan, ...]]:
    """AUD-09b amendment Stage B (§3): `coverage_kind` plus `excluded_fragments`.

    `"FRAGMENT"` iff some OTHER `CLEAN` instance has a date-scoped in-window
    event outside the winner's own `[first, last]` -- approximated from that
    instance's own extent (`first`/`last` are the only in-window instants
    this module tracks): its first is before the winner's first, or its last
    is after the winner's last. An instance with no in-window depth at all
    (`first_in_window_ns is None`) contributes nothing.
    """
    fragments = [
        FragmentSpan(
            instance_id=other.instance_id,
            first_in_window_ns=other.first_in_window_ns,
            last_in_window_ns=other.last_in_window_ns,
        )
        for other in clean
        if other.instance_id != winner.instance_id
        and other.first_in_window_ns is not None
        and other.last_in_window_ns is not None
        and winner.first_in_window_ns is not None
        and winner.last_in_window_ns is not None
        and (
            other.first_in_window_ns < winner.first_in_window_ns
            or other.last_in_window_ns > winner.last_in_window_ns
        )
    ]
    ordered = tuple(
        sorted(fragments, key=lambda fragment: (fragment.first_in_window_ns, fragment.instance_id))
    )
    coverage_kind = "FRAGMENT" if ordered else "WHOLE"
    return coverage_kind, ordered


def _sufficient(
    *,
    station: str,
    climate_day: str,
    winner: InstanceSpan,
    clean: Sequence[InstanceSpan],
    computed_day: str,
    window_start_ns: int,
    window_end_ns: int,
    live_instance_count: int,
) -> ReplaySufficiency:
    coverage_kind, excluded_fragments = _fragment_analysis(winner=winner, clean=clean)
    return ReplaySufficiency(
        schema_version=REPLAY_SUFFICIENCY_SCHEMA_VERSION,
        station=station,
        climate_day=climate_day,
        verdict="SUFFICIENT",
        reason="",
        winner_instance_id=winner.instance_id,
        depth_window_minutes=winner.depth_window_minutes,
        quote_window_minutes=winner.quote_window_minutes,
        distinct_instruments=winner.distinct_instruments,
        computed_day=computed_day,
        window_start_ns=window_start_ns,
        window_end_ns=window_end_ns,
        winner_first_in_window_ns=winner.first_in_window_ns,
        winner_last_in_window_ns=winner.last_in_window_ns,
        window_complete=_window_complete(
            winner=winner, window_start_ns=window_start_ns, window_end_ns=window_end_ns,
        ),
        live_instance_count=live_instance_count,
        coverage_kind=coverage_kind,
        excluded_fragments=excluded_fragments,
    )


def _insufficient(
    *,
    station: str,
    climate_day: str,
    reason: str,
    computed_day: str,
    depth_window_minutes: float = 0.0,
    quote_window_minutes: float = 0.0,
    distinct_instruments: int = 0,
    window_start_ns: int = 0,
    window_end_ns: int = 0,
    live_instance_count: int = 0,
) -> ReplaySufficiency:
    return ReplaySufficiency(
        schema_version=REPLAY_SUFFICIENCY_SCHEMA_VERSION,
        station=station,
        climate_day=climate_day,
        verdict="INSUFFICIENT",
        reason=reason,
        winner_instance_id=None,
        depth_window_minutes=depth_window_minutes,
        quote_window_minutes=quote_window_minutes,
        distinct_instruments=distinct_instruments,
        computed_day=computed_day,
        window_start_ns=window_start_ns,
        window_end_ns=window_end_ns,
        winner_first_in_window_ns=None,
        winner_last_in_window_ns=None,
        window_complete=False,
        live_instance_count=live_instance_count,
        coverage_kind="WHOLE",
        excluded_fragments=(),
    )


def write_replay_sufficiency(path: Path, records: Sequence[ReplaySufficiency]) -> None:
    """Atomic whole-file rewrite: one line per ``(station, climate_day)``.

    Sorted by ``(station, climate_day)`` so two consecutive runs over an
    unchanged tape are byte-identical (B3) regardless of discovery order --
    this is a derived VIEW of the tape, not an append-only ledger (H0).
    """
    ordered = sorted(records, key=lambda record: (record.station, record.climate_day))
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for record in ordered:
                handle.write(json.dumps(record.to_dict(), sort_keys=True))
                handle.write("\n")
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def read_replay_sufficiency(path: Path) -> tuple[ReplaySufficiency, ...]:
    """Parse ``replay_sufficiency.jsonl``.

    Refuses (never silently drops or last-wins) on an unrecognised
    ``schema_version`` or a duplicate ``(station, climate_day)`` key (H0).
    """
    records: list[ReplaySufficiency] = []
    seen: set[tuple[str, str]] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            payload = json.loads(line)
            version = payload.get("schema_version")
            if version != REPLAY_SUFFICIENCY_SCHEMA_VERSION:
                raise UnknownReplaySufficiencySchemaError(
                    f"{path}:{line_number}: unknown replay_sufficiency schema_version "
                    f"{version!r} (expected {REPLAY_SUFFICIENCY_SCHEMA_VERSION})"
                )
            record = ReplaySufficiency.from_dict(payload)
            key = (record.station, record.climate_day)
            if key in seen:
                raise DuplicateReplaySufficiencyRecordError(
                    f"{path}:{line_number}: duplicate (station, climate_day)={key!r}"
                )
            seen.add(key)
            records.append(record)
    return tuple(records)
