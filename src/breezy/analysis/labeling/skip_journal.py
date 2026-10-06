"""Write-once AUT-2 journals and the lock-skip streak (AUT-2 r7 WP5, sections 3.2.2 and 3.7.3).

``write_json_once`` is the one primitive every AUT-2 evidence journal uses: directories 0700 through
``single_read.ensure_dir``, the file 0600 through ``single_read.write_once`` (a temp file linked
into place, then fsynced), and a second write with different bytes refused.

A lock-skip is journalled once per skipped slot at
``evidence/aut2/skips/<YYYY-MM-DD>/<now_ns>_<unit>.json``. ``consecutive`` is the unbroken run of
skip files for the unit since the newest marker or verdict, read from the journal and never from
process memory. A skip that cannot be recorded raises :class:`SkipJournalWriteFailed` and the
skip path exits 1 (L1): it never exits 0 with the streak unrecorded.
"""

from __future__ import annotations

import datetime as dt
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from breezy.analysis.labeling.constants import LOCK_SKIP_CRITICAL_CONSECUTIVE
from breezy.persistence.autonomy.canonical import canonical_json
from breezy.persistence.autonomy.single_read import (
    SingleReadReason,
    SingleReadRefused,
    ensure_dir,
    open_root,
    walk_dirs,
    write_once,
)

__all__ = [
    "JOURNAL_FILE_MODE",
    "SKIPS_DIR",
    "SKIP_SCHEMA",
    "SkipJournalWriteFailed",
    "SkipRecord",
    "consecutive_skips",
    "record_skip",
    "run_record_skip",
    "skip_is_critical",
    "utc_day",
    "write_json_once",
]

SKIPS_DIR: Final[tuple[str, ...]] = ("evidence", "aut2", "skips")
SKIP_SCHEMA: Final = "aut2_skip/v1"
JOURNAL_FILE_MODE: Final = 0o600
_UNIT_RE: Final = re.compile(r"\A[a-z0-9][a-z0-9_-]{0,63}\Z")
_NAME_RE: Final = re.compile(r"\A(\d+)_([a-z0-9][a-z0-9_-]{0,63})\.json\Z")
_SKIP_REASONS: Final = frozenset({"lock"})


class SkipJournalWriteFailed(Exception):
    """The skip file could not be created or fsynced."""


def utc_day(ns: int) -> str:
    return dt.datetime.fromtimestamp(ns / 1_000_000_000, tz=dt.UTC).strftime("%Y-%m-%d")


def write_json_once(data_root: Path, parts: Sequence[str], body: Mapping[str, Any]) -> Path:
    """Write ``body`` as canonical JSON at ``data_root/<parts>`` once (0600)."""
    rootfd = open_root(data_root)
    try:
        os.close(ensure_dir(rootfd, tuple(parts[:-1])))
    finally:
        os.close(rootfd)
    path = data_root.joinpath(*parts)
    write_once(path, canonical_json(dict(body)), root=data_root, mode=JOURNAL_FILE_MODE)
    return path


@dataclass(frozen=True)
class SkipRecord:
    unit: str
    slot_ns: int
    reason: str
    consecutive: int
    path: Path


def _skip_times(data_root: Path, unit: str) -> list[int]:
    """The ``now_ns`` of every skip file of ``unit``, ascending; an absent journal is empty."""
    rootfd = open_root(data_root)
    try:
        try:
            skips_fd = walk_dirs(rootfd, SKIPS_DIR)
        except SingleReadRefused as exc:
            if exc.reason is SingleReadReason.NOT_FOUND:
                return []
            raise
        try:
            times: list[int] = []
            for day in sorted(os.listdir(skips_fd)):
                dayfd = walk_dirs(rootfd, (*SKIPS_DIR, day))
                try:
                    for name in os.listdir(dayfd):
                        found = _NAME_RE.match(name)
                        if found is not None and found.group(2) == unit:
                            times.append(int(found.group(1)))
                finally:
                    os.close(dayfd)
            return sorted(times)
        finally:
            os.close(skips_fd)
    finally:
        os.close(rootfd)


def consecutive_skips(data_root: Path, unit: str, *, since_ns: int) -> int:
    """The unbroken run of skip files of ``unit`` newer than ``since_ns`` (the newest marker or
    verdict). A marker after a skip resets the run."""
    if _UNIT_RE.match(unit) is None:
        raise ValueError("unit is not a valid skip-journal unit name")
    return sum(1 for t in _skip_times(data_root, unit) if t > since_ns)


def record_skip(
    data_root: Path, unit: str, reason: str, now_ns: int, *, slot_ns: int, since_ns: int
) -> SkipRecord:
    """Write the skip file for this slot and return it with its ``consecutive`` count."""
    if _UNIT_RE.match(unit) is None:
        raise ValueError("unit is not a valid skip-journal unit name")
    if reason not in _SKIP_REASONS:
        raise ValueError("reason must be 'lock'")
    try:
        consecutive = consecutive_skips(data_root, unit, since_ns=since_ns) + 1
        path = write_json_once(
            data_root,
            (*SKIPS_DIR, utc_day(now_ns), f"{now_ns}_{unit}.json"),
            {
                "schema": SKIP_SCHEMA,
                "unit": unit,
                "slot_ns": slot_ns,
                "reason": reason,
                "consecutive": consecutive,
            },
        )
    except (OSError, SingleReadRefused) as exc:
        raise SkipJournalWriteFailed("the skip file could not be written") from exc
    return SkipRecord(unit=unit, slot_ns=slot_ns, reason=reason, consecutive=consecutive, path=path)


def skip_is_critical(consecutive: int) -> bool:
    """Two consecutive skipped slots raise the ``aut2.lock_skips_consecutive`` CRITICAL."""
    return consecutive >= LOCK_SKIP_CRITICAL_CONSECUTIVE


def run_record_skip(
    data_root: Path, unit: str, now_ns: int, *, slot_ns: int, since_ns: int
) -> tuple[int, str]:
    """The ``--record-skip`` path: ``(exit_code, line)``. A failed write is exit 1 and the
    ``AUT2 SKIP_JOURNAL_WRITE_FAILED`` line, never a silent exit 0 (L1)."""
    try:
        record = record_skip(data_root, unit, "lock", now_ns, slot_ns=slot_ns, since_ns=since_ns)
    except SkipJournalWriteFailed:
        return 1, f"AUT2 SKIP_JOURNAL_WRITE_FAILED unit={unit}"
    return 0, f"SKIPPED reason=lock unit={unit} consecutive={record.consecutive}"
