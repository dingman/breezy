"""Replay-sufficiency census core (AUD-09a).

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
span; two ``CLEAN`` instances each >= :data:`MIN_DEPTH_WINDOW_MINUTES` REFUSE
the pair -- no first-list, no stitch, no union.

**Coverage basis is DEPTH, not quotes**: v3 hunts Depth10 (L-35), and at
``L2_MBP`` the QuoteTick tape is inert for execution
(``BACKTEST_VENUE_CONFIG.md:144-150``). Both spans are reported on every row,
but the verdict decides on depth -- matching
``assert_decision_window_has_coverage(..., source="depth")``
(``scripts/analysis/current_rung_hold_paper_replay.py:257``).
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, Literal

__all__ = [
    "AMBIGUOUS_WINNER_TWO_CLEAN_GE_30MIN",
    "CANDIDATE_UNSUPPORTED_STATION",
    "CORRUPT_ONLY",
    "DEPTH_WINDOW_UNDER_30MIN",
    "INGEST_INSTANCE_REFUSED",
    "MIN_DEPTH_WINDOW_MINUTES",
    "NO_CLEAN_INSTANCE",
    "NO_IN_WINDOW_DEPTH",
    "REPLAY_SUFFICIENCY_REASONS",
    "REPLAY_SUFFICIENCY_SCHEMA_VERSION",
    "VENUE_NEVER_LISTED_UNCONFIRMED",
    "DuplicateReplaySufficiencyRecordError",
    "InstanceSpan",
    "InstanceVerdict",
    "ReplaySufficiency",
    "ReplaySufficiencyVerdict",
    "UnknownReplaySufficiencySchemaError",
    "classify_station_day",
    "read_replay_sufficiency",
    "write_replay_sufficiency",
]

#: Hand-off H0 (AUD-09 plan §6a): every writer/reader agrees on this version.
REPLAY_SUFFICIENCY_SCHEMA_VERSION: Final[int] = 1

#: Matches ``structural_dead_stop.py``'s own >=30 min afternoon-coverage rule
#: (``scripts/analysis/ma_prelock_winner_ask_study.MIN_AFTERNOON_COVERAGE_MINUTES``,
#: rule applied at ``structural_dead_stop.py:214``), so the census and the
#: KILL clock cannot disagree about "covered". Declared locally rather than
#: imported: that module lives in ``scripts/``, unimportable from
#: ``src/breezy/**`` -- the same reasoning :data:`InstanceVerdict` documents.
MIN_DEPTH_WINDOW_MINUTES: Final[float] = 30.0

#: The closed refusal-reason alphabet (AUD-09 plan §6a), each traceable to a
#: measured cause. Exactly one never-listed token exists --
#: ``VENUE_NEVER_LISTED_UNCONFIRMED`` -- because the census never probes the
#: venue; a bare ``VENUE_NEVER_LISTED`` would claim a fact only a by-slug
#: probe can establish (memory ``venue-skips-station-days``).
NO_CLEAN_INSTANCE: Final[str] = "NO_CLEAN_INSTANCE"
AMBIGUOUS_WINNER_TWO_CLEAN_GE_30MIN: Final[str] = "AMBIGUOUS_WINNER_TWO_CLEAN_GE_30MIN"
DEPTH_WINDOW_UNDER_30MIN: Final[str] = "DEPTH_WINDOW_UNDER_30MIN"
NO_IN_WINDOW_DEPTH: Final[str] = "NO_IN_WINDOW_DEPTH"
VENUE_NEVER_LISTED_UNCONFIRMED: Final[str] = "VENUE_NEVER_LISTED_UNCONFIRMED"
INGEST_INSTANCE_REFUSED: Final[str] = "INGEST_INSTANCE_REFUSED"
CORRUPT_ONLY: Final[str] = "CORRUPT_ONLY"
CANDIDATE_UNSUPPORTED_STATION: Final[str] = "CANDIDATE_UNSUPPORTED_STATION"

REPLAY_SUFFICIENCY_REASONS: Final[frozenset[str]] = frozenset(
    {
        NO_CLEAN_INSTANCE,
        AMBIGUOUS_WINNER_TWO_CLEAN_GE_30MIN,
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


@dataclass(frozen=True, slots=True, kw_only=True)
class InstanceSpan:
    """One instance's contribution to one ``(station, climate_day)``.

    A pure value the SCRIPT builds from real feather/catalog reads; this
    module never constructs one from disk.
    """

    instance_id: str
    verdict: InstanceVerdict
    depth_window_minutes: float
    quote_window_minutes: float
    distinct_instruments: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplaySufficiency:
    """One census row: whether ``(station, climate_day)`` can be replayed.

    ``reason`` is the empty string for a ``SUFFICIENT`` verdict; for
    ``INSUFFICIENT`` it is one member of :data:`REPLAY_SUFFICIENCY_REASONS`.
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


class UnknownReplaySufficiencySchemaError(Exception):
    """A ``replay_sufficiency.jsonl`` line names an unrecognised ``schema_version``.

    Refuses rather than silently reading a stale or future shape: "no work"
    and "unreadable work list" must never look alike (H0).
    """


class DuplicateReplaySufficiencyRecordError(Exception):
    """Two lines in ``replay_sufficiency.jsonl`` share one ``(station,
    climate_day)`` key -- a hard error, never last-wins: a duplicate means two
    writers raced and the file cannot be trusted."""


def classify_station_day(
    *,
    station: str,
    climate_day: str,
    instances: Sequence[InstanceSpan],
    computed_day: str,
) -> ReplaySufficiency:
    """``SUFFICIENT``/``INSUFFICIENT`` verdict for one ``(station, climate_day)``.

    ``instances`` carries every :class:`InstanceSpan` the script found
    touching this station-day, regardless of verdict. ``LIVE`` instances are
    never a winner (the writer may still be appending) and, absent a
    ``CLEAN`` instance for the same day, fall into ``NO_CLEAN_INSTANCE``
    exactly like ``EMPTY``.
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
        )

    eligible = [
        instance for instance in clean if instance.depth_window_minutes >= MIN_DEPTH_WINDOW_MINUTES
    ]
    if len(eligible) >= 2:
        best = _longest_depth(eligible)
        return _insufficient(
            station=station,
            climate_day=climate_day,
            reason=AMBIGUOUS_WINNER_TWO_CLEAN_GE_30MIN,
            computed_day=computed_day,
            depth_window_minutes=best.depth_window_minutes,
            quote_window_minutes=best.quote_window_minutes,
            distinct_instruments=best.distinct_instruments,
        )

    best = _longest_depth(clean)
    if best.depth_window_minutes >= MIN_DEPTH_WINDOW_MINUTES:
        return ReplaySufficiency(
            schema_version=REPLAY_SUFFICIENCY_SCHEMA_VERSION,
            station=station,
            climate_day=climate_day,
            verdict="SUFFICIENT",
            reason="",
            winner_instance_id=best.instance_id,
            depth_window_minutes=best.depth_window_minutes,
            quote_window_minutes=best.quote_window_minutes,
            distinct_instruments=best.distinct_instruments,
            computed_day=computed_day,
        )

    reason = DEPTH_WINDOW_UNDER_30MIN if best.depth_window_minutes > 0.0 else NO_IN_WINDOW_DEPTH
    return _insufficient(
        station=station,
        climate_day=climate_day,
        reason=reason,
        computed_day=computed_day,
        depth_window_minutes=best.depth_window_minutes,
        quote_window_minutes=best.quote_window_minutes,
        distinct_instruments=best.distinct_instruments,
    )


def _longest_depth(instances: Sequence[InstanceSpan]) -> InstanceSpan:
    """The instance with the longest depth span, ties broken by id for determinism."""
    return max(
        instances, key=lambda instance: (instance.depth_window_minutes, instance.instance_id)
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
                handle.write(json.dumps(asdict(record), sort_keys=True))
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
            record = ReplaySufficiency(**payload)
            key = (record.station, record.climate_day)
            if key in seen:
                raise DuplicateReplaySufficiencyRecordError(
                    f"{path}:{line_number}: duplicate (station, climate_day)={key!r}"
                )
            seen.add(key)
            records.append(record)
    return tuple(records)
