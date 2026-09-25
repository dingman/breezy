#!/usr/bin/env python3
"""AUD-07 M2 ruling artefact gate (amendment §6.1) -- pure functions.

The gate literals and classification rule exist BEFORE any number does
(amendment §6 step 1). Reuses `clopper_pearson_upper`/`_lower`
(`aud06a_qty_envelope_sweep.py:393-404`, both one-sided); never
re-implements them.

No network. No repo writes.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final, Literal

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"
if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))

from aud06a_qty_envelope_sweep import clopper_pearson_lower, clopper_pearson_upper

__all__ = [
    "ALPHA",
    "I_CONF",
    "V_CONF",
    "V_THRESHOLD",
    "Verdict",
    "branch",
    "classify_cell",
    "final_class",
]

Verdict = Literal["V", "I", "INDETERMINATE"]

#: Amendment §4 M1c, "Unchanged" -- cited verbatim, never re-derived.
ALPHA: Final[float] = 0.025
#: V: one-sided 95% CP-upper <= 0.0283 (amendment "Unchanged").
V_THRESHOLD: Final[float] = 0.0283
V_CONF: Final[float] = 0.95
#: I: CP-lower at confidence 1 - 0.05/16 > alpha (amendment "Unchanged",
#: Bonferroni over the 16 mixed cells).
I_CONF: Final[float] = 1.0 - 0.05 / 16


def classify_cell(count: int, n: int) -> Verdict:
    """One cell's classification (amendment §6.1 `classify_cell`):
    `V` if the one-sided `V_CONF` CP-upper bound is <= `V_THRESHOLD`;
    else `I` if the one-sided `I_CONF` CP-lower bound is > `ALPHA`;
    else `INDETERMINATE`."""
    cp_upper = clopper_pearson_upper(count, n, confidence=V_CONF)
    if cp_upper <= V_THRESHOLD:
        return "V"
    cp_lower = clopper_pearson_lower(count, n, confidence=I_CONF)
    if cp_lower > ALPHA:
        return "I"
    return "INDETERMINATE"


def final_class(r20k: Verdict, r80k: Verdict | None) -> Verdict:
    """The 80k result REPLACES the 20k result and is never pooled with it
    (amendment "Unchanged"). A cell still `INDETERMINATE` at 80k counts as
    `I` (amendment "Unchanged")."""
    if r80k is None:
        return r20k
    if r80k == "INDETERMINATE":
        return "I"
    return r80k


def branch(mixed16: Sequence[Verdict]) -> Verdict:
    """`V` only if all 16 mixed cells are `V`; `I` if any is `I`
    (amendment §6.1 `branch`); otherwise `INDETERMINATE`."""
    if any(c == "I" for c in mixed16):
        return "I"
    if all(c == "V" for c in mixed16):
        return "V"
    return "INDETERMINATE"


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _classify_rows(rows: list[dict[str, Any]]) -> dict[int, Verdict]:
    return {row["cell_index"]: classify_cell(row["crossing_count"], row["n_reps"]) for row in rows}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--stage20k", action="store_true", help="emit the 80k rerun queue")
    mode.add_argument("--final", action="store_true", help="emit the final ruling table")
    parser.add_argument("--in-20k", type=Path, help="merged 20k JSONL (required for both modes)")
    parser.add_argument("--in-80k", type=Path, default=None, help="merged 80k JSONL (--final only)")
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI wrapper (amendment §6 steps 2-3). Never touches an operator
    control, an order, or the halt state (AC8) -- it only classifies
    already-merged JSONL rows."""
    args = _parse_args(argv)
    if args.in_20k is None:
        raise ValueError("--in-20k is required")
    rows_20k = _load_jsonl(args.in_20k)
    classes_20k = _classify_rows(rows_20k)

    args.out.parent.mkdir(parents=True, exist_ok=True)

    if args.stage20k:
        rerun_queue = sorted(
            cell_index for cell_index, verdict in classes_20k.items() if verdict == "INDETERMINATE"
        )
        payload = json.dumps({"rerun_queue": rerun_queue}, indent=2) + "\n"
        args.out.write_text(payload, encoding="utf-8")
        print(
            f"[aud07-m2-gate] {len(rerun_queue)} INDETERMINATE cell(s): {rerun_queue}",
            file=sys.stderr,
        )
        return 0

    classes_80k: dict[int, Verdict] = {}
    if args.in_80k is not None and args.in_80k.exists():
        classes_80k = _classify_rows(_load_jsonl(args.in_80k))

    final_by_cell = {
        cell_index: final_class(verdict, classes_80k.get(cell_index))
        for cell_index, verdict in classes_20k.items()
    }
    mixed16 = [final_by_cell[i] for i in range(16)]
    overall = branch(mixed16)
    report = {"per_cell": final_by_cell, "mixed16": mixed16, "branch": overall}
    args.out.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"[aud07-m2-gate] branch={overall!r}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
