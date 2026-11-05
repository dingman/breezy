"""EXEC-PAR BG-2: the ``epoch_strata.jsonl`` sidecar of the scored-trial store.

``score_live_trials`` records ONLY the fills whose ``ts_event`` falls in a
parallel (K>1, unforced) epoch, one line per ``trial_id``. An absent file means
every fill is single-slot, so a store that only ever ran at K=1 gains no file
and no byte. ``family_tally_v2`` reads it to report a separate stratum.

Appends are crash-safe: the whole new content is written to a temp file, fsynced
and swapped in with ``os.replace``, so the sidecar is either the old file or the
new one, never a torn line. The reader is therefore strict: any bad line raises,
naming the line and the field.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Final

__all__ = [
    "EPOCH_STRATA_FILENAME",
    "STRATUM_PARALLEL",
    "STRATUM_SINGLE",
    "append_epoch_strata",
    "parallel_trial_ids",
]

STRATUM_SINGLE: Final[str] = "single"
STRATUM_PARALLEL: Final[str] = "parallel"
EPOCH_STRATA_FILENAME: Final[str] = "epoch_strata.jsonl"


def _parse(text: str, path: Path) -> frozenset[str]:
    ids: set[str] = set()
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"malformed {path}:{lineno}: invalid JSON") from exc
        if not isinstance(row, dict):
            raise ValueError(f"malformed {path}:{lineno}: not an object")  # noqa: TRY004
        trial_id = row.get("trial_id")
        if not isinstance(trial_id, str) or not trial_id:
            raise ValueError(f"malformed {path}:{lineno}: field trial_id")
        filled_at_ns = row.get("filled_at_ns")
        if not isinstance(filled_at_ns, int) or isinstance(filled_at_ns, bool) or filled_at_ns < 0:
            raise ValueError(f"malformed {path}:{lineno}: field filled_at_ns")
        if row.get("stratum") != STRATUM_PARALLEL:
            raise ValueError(f"malformed {path}:{lineno}: field stratum")
        ids.add(trial_id)
    return frozenset(ids)


def parallel_trial_ids(store_dir: Path) -> frozenset[str]:
    """The ``trial_id`` of every recorded parallel-epoch fill; ``ValueError`` on a bad line."""
    path = store_dir / EPOCH_STRATA_FILENAME
    if not path.exists():
        return frozenset()
    return _parse(path.read_text(encoding="utf-8"), path)


def append_epoch_strata(store_dir: Path, filled_at_ns_by_trial_id: Mapping[str, int]) -> None:
    """Append the parallel-epoch fills, idempotent on ``trial_id``; no new fill writes nothing."""
    path = store_dir / EPOCH_STRATA_FILENAME
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    known = _parse(existing, path)
    new = [t for t in sorted(filled_at_ns_by_trial_id) if t not in known]
    if not new:
        return
    lines = [
        json.dumps(
            {
                "trial_id": trial_id,
                "filled_at_ns": filled_at_ns_by_trial_id[trial_id],
                "stratum": STRATUM_PARALLEL,
            }
        )
        for trial_id in new
    ]
    lead = "\n" if existing and not existing.endswith("\n") else ""
    content = existing + lead + "\n".join(lines) + "\n"
    store_dir.mkdir(parents=True, exist_ok=True)
    tmp = store_dir / (EPOCH_STRATA_FILENAME + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
