"""MAKER-S2 second look (C2/C6): the v2 checks that must pass BEFORE the ledger claim.

A post-claim failure burns the one-shot ledger entry, so for a ``FROZEN_DATE_SET_V2`` verdict run
every pinned input is hashed, the trigger day is recomputed, and the full truth agreement (overlap,
``TruthConflict``, truth sha) and the frozen-set rule run here, against the same key set the
post-simulation ``score`` will use (``truth_keys`` is a superset of the replayed keys). v1 is never
routed here: ``needs_v2_checks`` is False for it.
"""

from __future__ import annotations

import datetime as dt
import tempfile
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import Final

from breezy.analysis.maker_tape_census import CensusedDay
from scripts.analysis.maker_stage0_frozen import FrozenDateSet, truth_keys, verify_set_matches_rule
from scripts.analysis.maker_stage0_inputs import InputRefused, load_truth, sha256_file
from scripts.analysis.maker_stage0_trigger_rule import (
    TriggerRow,
    counted,
    first_crossing,
    read_trigger_rows,
)

__all__ = ["check_v2_before_claim", "needs_v2_checks"]


V2_BLOCK: Final[int] = 2


def is_v2_block(fs: FrozenDateSet) -> bool:
    return fs.block == V2_BLOCK


def needs_v2_checks(fs: FrozenDateSet, mode: str) -> bool:
    return is_v2_block(fs) and mode == "verdict"


def _pinned(path: Path, expected: str | None, what: str) -> None:
    try:
        digest = sha256_file(path)
    except OSError as exc:
        raise InputRefused(f"{what} {path.name} unreadable ({type(exc).__name__})") from exc
    if digest != expected:
        raise InputRefused(f"{what} sha256 {digest} != the frozen block's {expected}")


def _trigger_path(repo_root: Path, relative: str | None) -> Path:
    pure = PurePosixPath(relative or "")
    if not relative or pure.is_absolute() or ".." in pure.parts:
        raise InputRefused(f"trigger_rows_path {relative!r} must be repo-relative")
    return repo_root / pure


def _check_trigger(fs: FrozenDateSet, repo_root: Path) -> list[TriggerRow]:
    path = _trigger_path(repo_root, fs.trigger_rows_path)
    _pinned(path, fs.trigger_rows_sha256, "trigger rows")
    rows = read_trigger_rows(path)
    recomputed = first_crossing(rows)
    if recomputed != fs.trigger_day:
        raise InputRefused(
            f"trigger_day {fs.trigger_day} != the pinned rows' first crossing {recomputed}"
        )
    return rows


def _check_direction(
    fs: FrozenDateSet, rows: list[TriggerRow], census: list[CensusedDay]
) -> list[tuple[str, dt.date]]:
    """Counted at trigger time => COVERED in the final census; the reverse is disclosed."""
    last = fs.trigger_day
    if last is None:
        raise InputRefused("a v2 frozen set needs a trigger_day")
    covered = {(r.station, r.climate_day) for r in census if r.reason == "COVERED"}
    seen = {(r.station, r.climate_day) for r in rows if counted(r) and r.climate_day <= last}
    lost = sorted(seen - covered)
    if lost:
        raise InputRefused(
            f"{len(lost)} station-days counted by the trigger rows are not COVERED in the final "
            f"census, e.g. {lost[:3]}"
        )
    return sorted(key for key in covered - seen if key[1] <= last)


def check_v2_before_claim(
    fs: FrozenDateSet,
    *,
    repo_root: Path,
    truth_csv: Path,
    cross_check: Path,
    census_days: Path,
    census: Iterable[CensusedDay],
) -> list[tuple[str, dt.date]]:
    """Refuse (typed, before the claim) any v2 pin that does not hold.

    Returns the disclosed (never refused) station-days that were not counted at trigger time but
    are COVERED in the final census.
    """
    census_rows = list(census)
    _pinned(cross_check, fs.cross_check_sha256, "truth cross-check")
    _pinned(census_days, fs.census_days_sha256, "census days")
    rows = _check_trigger(fs, repo_root)
    disclosed = _check_direction(fs, rows, census_rows)
    with tempfile.TemporaryDirectory(prefix="maker-v2-truth-") as scratch:
        truth = load_truth(
            truth_csv,
            cross_check,
            Path(scratch),
            keys=truth_keys(fs.stations, fs.dates),
            expected_csv_sha256=fs.truth_csv_sha256,
        )
        verify_set_matches_rule(fs, census_rows, truth)
    return disclosed
