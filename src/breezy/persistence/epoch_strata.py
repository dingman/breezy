"""EXEC-PAR BG-2: the ``epoch_strata.jsonl`` sidecar of the scored-trial store.

``score_live_trials`` records ONLY the fills whose ``ts_event`` falls in a
parallel (K>1, unforced) epoch, one line per ``trial_id``. An absent file means
every fill is single-slot, so a store that only ever ran at K=1 gains no file
and no byte. ``family_tally_v2`` reads it to report a separate stratum.
"""

from __future__ import annotations

import json
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


def parallel_trial_ids(store_dir: Path) -> frozenset[str]:
    """The ``trial_id`` of every recorded parallel-epoch fill; ``ValueError`` on a bad line."""
    path = store_dir / EPOCH_STRATA_FILENAME
    if not path.exists():
        return frozenset()
    ids: set[str] = set()
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            trial_id = row["trial_id"]
            stratum = row["stratum"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ValueError(f"malformed {path}:{lineno}") from exc
        if not isinstance(trial_id, str) or not trial_id or stratum != STRATUM_PARALLEL:
            raise ValueError(f"malformed {path}:{lineno}")
        ids.add(trial_id)
    return frozenset(ids)


def append_epoch_strata(store_dir: Path, filled_at_ns_by_trial_id: Mapping[str, int]) -> None:
    """Append the parallel-epoch fills, idempotent on ``trial_id``; no new fill writes nothing."""
    known = parallel_trial_ids(store_dir)
    new = [t for t in sorted(filled_at_ns_by_trial_id) if t not in known]
    if not new:
        return
    store_dir.mkdir(parents=True, exist_ok=True)
    path = store_dir / EPOCH_STRATA_FILENAME
    lead = "\n" if path.exists() and not path.read_text(encoding="utf-8").endswith("\n") else ""
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
    with path.open("a", encoding="utf-8") as fh:
        fh.write(lead + "\n".join(lines) + "\n")
