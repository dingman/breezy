"""F-3 (STALL_FOLLOWUPS_F1_F4_2026-09-24.md): retention for the `decisions/`
sidecar directory (`offer_tape_<date>.jsonl`, `diagnostics_summary_<date>.
jsonl`).

Gzip only -- never a lossy transform. Every gzip is ATOMIC and VERIFIED
before the original is ever unlinked (Rev 3.1 exact order):

    1. write ``<name>.jsonl.gz.tmp``
    2. fsync the tmp file
    3. VERIFY the tmp (decompressed byte count and line count equal the
       original's) -- BEFORE any rename
    4. ``os.replace`` the tmp onto ``<name>.jsonl.gz``
    5. fsync the containing directory
    6. ``os.utime`` the ``.gz`` to the original's mtime
    7. unlink the original

Any failure before step 4 (write, fsync, or verify) removes the ``.tmp`` and
keeps the original untouched -- this file is simply skipped this run, and
the caller sees an OK exit for the OTHER eligible files (a single bad file
never aborts the batch). A crash between steps 4 and 7 can leave BOTH the
``.jsonl`` and ``.jsonl.gz`` on disk; the NEXT run treats that as a candidate
whose ``.gz`` already exists, re-verifies it against the original, and only
then unlinks the original -- idempotent, never re-writing a ``.gz`` that
already verifies. Every reader (the AUD-03 digest, `measured_slippage_
from_fills.py`, `band_decider_stage0b_screen.py`) prefers the ``.jsonl``
over the ``.gz`` for the same date, so a "both present" window never double
counts.

Scope is narrow and non-recursive by construction: only files DIRECTLY
inside `decisions_dir` whose name fully matches
``^(offer_tape|diagnostics_summary)_\\d{4}-\\d{2}-\\d{2}\\.jsonl$`` are
candidates -- `decisions_dir.iterdir()`, never `glob("**/*")`, so a sibling
directory (`observations/`, one level up from `decisions/` --
`observation_composition.py`'s `_OBSERVATIONS_DIRNAME`) is structurally
unreachable, not merely excluded by a check.

Age is judged by ACTIVITY (`stat().st_mtime`), never by the date embedded in
the filename: a file named with an old date but touched recently (a
backdated reprocessing run) is left alone by the 36h floor below, and the
N-day gzip threshold uses the same mtime clock -- never the name.

Pruning (deleting an aged `.jsonl.gz`) ships DISABLED: it exists only behind
an explicit `--prune-older-than DAYS` CLI flag, which the deployed
`ExecStart=` never passes. Enabling it is a separate, future, reviewed
change (R6).
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import logging
import os
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_GZIP_OLDER_THAN_DAYS",
    "MIN_MTIME_AGE_HOURS",
    "SUGGESTED_PRUNE_OLDER_THAN_DAYS",
    "RetentionOutcome",
    "gzip_eligible_files",
    "main",
    "prune_old_gz_files",
    "run_retention",
]

#: R7: exact-name match only -- no recursion, never `observations/`.
_JSONL_NAME_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:offer_tape|diagnostics_summary)_\d{4}-\d{2}-\d{2}\.jsonl$"
)
_GZ_NAME_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:offer_tape|diagnostics_summary)_\d{4}-\d{2}-\d{2}\.jsonl\.gz$"
)

#: R7: a file is never gzipped while it might still be the live day's
#: actively-written sidecar, regardless of what N (below) would otherwise
#: allow -- independent of the file's name.
MIN_MTIME_AGE_HOURS: Final[float] = 36.0

#: R6/R7: N >= 2 days, chosen from the 2026-09-25 disk measurement (peak
#: uncapped day ~141 MiB projected, 400 GB free) -- there is no pressure to
#: gzip sooner than a week, matching the plan's own stated default.
DEFAULT_GZIP_OLDER_THAN_DAYS: Final[int] = 7

#: R6: NOT a default -- pruning ships disabled (see module docstring). This
#: is only the plan's suggested value for an operator who later opts in via
#: `--prune-older-than` by hand; nothing in this module ever applies it.
SUGGESTED_PRUNE_OLDER_THAN_DAYS: Final[int] = 90

_READ_CHUNK_BYTES: Final[int] = 1024 * 1024


@dataclass(frozen=True, slots=True)
class RetentionOutcome:
    """One run's result -- filenames only, never a value/price/instrument."""

    gzipped: tuple[str, ...] = ()
    skipped_recent: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()
    pruned: tuple[str, ...] = ()


def _age_hours(path: Path, now: dt.datetime) -> float:
    mtime = dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.UTC)
    return (now - mtime).total_seconds() / 3600.0


def _candidate_jsonl_files(decisions_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in decisions_dir.iterdir()
        if path.is_file() and _JSONL_NAME_RE.fullmatch(path.name)
    )


def _line_and_byte_counts(
    opener: Callable[..., object], path: Path
) -> tuple[int, int]:
    """Streamed (bounded memory) byte and newline counts -- never loads the
    whole file, so verification stays cheap even on a 512 MiB sidecar."""
    lines = 0
    total_bytes = 0
    with opener(path, "rb") as handle:  # type: ignore[call-arg]
        while True:
            chunk = handle.read(_READ_CHUNK_BYTES)
            if not chunk:
                break
            total_bytes += len(chunk)
            lines += chunk.count(b"\n")
    return lines, total_bytes


def _verify_gzip_matches(original: Path, gz_path: Path) -> bool:
    """Step 3: the decompressed `.gz` must have IDENTICAL byte and line
    counts to the original -- the whole point of gzip-only retention (never
    a lossy transform)."""
    orig_lines, orig_bytes = _line_and_byte_counts(open, original)
    try:
        gz_lines, gz_bytes = _line_and_byte_counts(gzip.open, gz_path)
    except OSError:
        return False
    return orig_lines == gz_lines and orig_bytes == gz_bytes


def _fsync_path(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_gzip_one(path: Path) -> bool:
    """Rev 3.1's exact 7-step order. Returns True iff the original was
    unlinked (success); False leaves the original untouched and removes any
    `.tmp` it created."""
    gz_path = path.with_name(path.name + ".gz")
    tmp_path = path.with_name(path.name + ".gz.tmp")

    if gz_path.is_file():
        # A prior run crashed between rename and unlink. Idempotent: only
        # re-verify the EXISTING .gz, never re-write it.
        if _verify_gzip_matches(path, gz_path):
            path.unlink()
            return True
        logger.error(
            "decisions_retention: existing %s does not verify against %s; "
            "keeping both untouched",
            gz_path,
            path,
        )
        return False

    try:
        with path.open("rb") as source, gzip.open(tmp_path, "wb") as dest:
            while True:
                chunk = source.read(_READ_CHUNK_BYTES)
                if not chunk:
                    break
                dest.write(chunk)
        _fsync_path(tmp_path)
    except OSError:
        logger.exception("decisions_retention: failed to write %s", tmp_path)
        tmp_path.unlink(missing_ok=True)
        return False

    if not _verify_gzip_matches(path, tmp_path):
        logger.error(
            "decisions_retention: verification failed for %s; keeping original", path
        )
        tmp_path.unlink(missing_ok=True)
        return False

    try:
        os.replace(tmp_path, gz_path)
    except OSError:
        # The rename itself never committed -- nothing has changed on disk
        # under the final `.gz` name, so this is exactly like a pre-rename
        # failure: clean up the tmp file and keep the original untouched.
        logger.exception("decisions_retention: failed to rename %s", tmp_path)
        tmp_path.unlink(missing_ok=True)
        return False

    try:
        _fsync_path(path.parent)
        stat = path.stat()
        os.utime(gz_path, (stat.st_atime, stat.st_mtime))
        path.unlink()
    except OSError:
        # The rename ALREADY committed -- both `path` and `gz_path` now
        # exist on disk (Rev 3.1's documented crash window). Never touch
        # either further here: the next run's "gz_path.is_file()" branch
        # above re-verifies and unlinks the original idempotently.
        logger.exception(
            "decisions_retention: failed to finalize %s after rename; both "
            "files left in place for the next run to reconcile",
            path,
        )
        return False
    return True


def gzip_eligible_files(
    decisions_dir: Path,
    *,
    older_than_days: int = DEFAULT_GZIP_OLDER_THAN_DAYS,
    now: dt.datetime | None = None,
) -> RetentionOutcome:
    """Gzip every eligible `decisions_dir` file, one at a time. A single
    file's failure is logged and skipped -- it never aborts the batch."""
    if older_than_days < 2:
        raise ValueError("older_than_days must be >= 2 (R7)")
    resolved_now = now if now is not None else dt.datetime.now(dt.UTC)
    gzipped: list[str] = []
    skipped_recent: list[str] = []
    failed: list[str] = []
    for path in _candidate_jsonl_files(decisions_dir):
        age_hours = _age_hours(path, resolved_now)
        if age_hours < MIN_MTIME_AGE_HOURS or age_hours < older_than_days * 24:
            skipped_recent.append(path.name)
            continue
        if _atomic_gzip_one(path):
            gzipped.append(path.name)
        else:
            failed.append(path.name)
    return RetentionOutcome(
        gzipped=tuple(gzipped), skipped_recent=tuple(skipped_recent), failed=tuple(failed)
    )


def prune_old_gz_files(
    decisions_dir: Path,
    *,
    older_than_days: int,
    now: dt.datetime | None = None,
) -> tuple[str, ...]:
    """R6: pruning is a distinct, explicit, opt-in action -- this function is
    never called by :func:`run_retention` unless the caller supplies
    `prune_older_than_days`."""
    resolved_now = now if now is not None else dt.datetime.now(dt.UTC)
    pruned: list[str] = []
    for path in sorted(decisions_dir.iterdir()):
        if not path.is_file() or not _GZ_NAME_RE.fullmatch(path.name):
            continue
        if _age_hours(path, resolved_now) >= older_than_days * 24:
            path.unlink()
            pruned.append(path.name)
    return tuple(pruned)


def run_retention(
    decisions_dir: Path,
    *,
    older_than_days: int = DEFAULT_GZIP_OLDER_THAN_DAYS,
    prune_older_than_days: int | None = None,
    now: dt.datetime | None = None,
) -> RetentionOutcome:
    """The one entry point the wrapper script's `ExecStart=` invokes.

    `prune_older_than_days=None` (the deployed default -- R6) means pruning
    never runs at all, not even a dry-run pass: `outcome.pruned` stays `()`.
    """
    resolved_now = now if now is not None else dt.datetime.now(dt.UTC)
    outcome = gzip_eligible_files(
        decisions_dir, older_than_days=older_than_days, now=resolved_now
    )
    pruned: tuple[str, ...] = ()
    if prune_older_than_days is not None:
        pruned = prune_old_gz_files(
            decisions_dir, older_than_days=prune_older_than_days, now=resolved_now
        )
    return RetentionOutcome(
        gzipped=outcome.gzipped,
        skipped_recent=outcome.skipped_recent,
        failed=outcome.failed,
        pruned=pruned,
    )


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--decisions-dir",
        type=Path,
        default=Path.home() / ".local/share/breezy/catalog/quote_tape/decisions",
    )
    parser.add_argument("--older-than-days", type=int, default=DEFAULT_GZIP_OLDER_THAN_DAYS)
    parser.add_argument(
        "--prune-older-than",
        type=int,
        default=None,
        dest="prune_older_than_days",
        help=(
            "DANGER: permanently deletes .jsonl.gz files older than this many "
            "days. Off by default (R6); the deployed unit's ExecStart= never "
            "passes this flag. Enabling it is a separate, reviewed change."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    outcome = run_retention(
        args.decisions_dir,
        older_than_days=args.older_than_days,
        prune_older_than_days=args.prune_older_than_days,
    )
    logger.info(
        "decisions_retention: gzipped=%d skipped_recent=%d failed=%d pruned=%d",
        len(outcome.gzipped),
        len(outcome.skipped_recent),
        len(outcome.failed),
        len(outcome.pruned),
    )
    return 1 if outcome.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
