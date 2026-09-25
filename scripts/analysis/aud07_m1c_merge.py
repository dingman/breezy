#!/usr/bin/env python3
"""AUD-07 M1c/M2 Rev 2 execution amendment -- stage merge (amendment §3.3).

Merges the per-cell (per-substream, for the 80k stage) JSONL rows written by
`aud07_live_rule_crossing_sim.run_chunk` for ONE stage into a single sorted
JSONL file:

- dedupes identical rows (ignoring `wall_s`); raises on conflicting
  duplicates;
- raises on mixed stages, and on more than one `code_sha` or
  `eps_pin_sha256` across `{cal_c, 20k, 80k}`;
- checks coverage: 20k = cells 0..48; `--mixed-only` = cells 0..15 plus 48;
  80k = the caller-supplied INDETERMINATE cell set x 4 sub-streams;
- pools the 80k sub-streams from integer counts and raw sums
  (`sum_s_terminal`, `sum_s2_terminal`, `sum_look_count`);
- writes the sorted JSONL plus its sha256.

No network. No repo writes except `--out`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, Final

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"
sys.path.insert(0, str(_REPO_ROOT / "src"))
if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))

from aud06a_qty_envelope_sweep import clopper_pearson_lower, clopper_pearson_upper

__all__ = [
    "MergeConflictError",
    "MergeCoverageError",
    "MergeStageError",
    "dedupe_rows",
    "load_stage_rows",
    "merge_stage",
    "pool_80k_substreams",
]


class MergeStageError(RuntimeError):
    """A row's `stage` differs from the merge's expected stage, or more
    than one distinct value was found for a field that must be singular
    across the merge (`code_sha`, `eps_pin_sha256`)."""


class MergeConflictError(RuntimeError):
    """Two rows share a resume identity but disagree on some other field
    (ignoring `wall_s`) -- a genuine conflicting duplicate, never silently
    resolved."""


class MergeCoverageError(RuntimeError):
    """The merged rows do not cover exactly the expected cell set."""


def _row_identity(row: dict[str, Any]) -> tuple[Any, ...]:
    return (row.get("stage"), row.get("cell_index"), row.get("substream"))


def load_stage_rows(paths: Iterable[Path], *, stage: str) -> list[dict[str, Any]]:
    """Read and concatenate JSONL rows from `paths`, raising
    `MergeStageError` on any row whose `stage` differs from `stage`."""
    rows: list[dict[str, Any]] = []
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("stage") != stage:
                raise MergeStageError(
                    f"row stage {row.get('stage')!r} in {path} does not match "
                    f"the expected stage {stage!r}"
                )
            rows.append(row)
    return rows


def dedupe_rows(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dedupe rows sharing a `(stage, cell_index, substream)` identity,
    ignoring `wall_s`. Raises `MergeConflictError` if two rows with the
    SAME identity disagree on any other field."""
    by_identity: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        identity = _row_identity(row)
        comparable = {k: v for k, v in row.items() if k != "wall_s"}
        if identity in by_identity:
            existing_comparable = {k: v for k, v in by_identity[identity].items() if k != "wall_s"}
            if existing_comparable != comparable:
                raise MergeConflictError(
                    f"conflicting duplicate rows for {identity!r}: "
                    f"{existing_comparable!r} != {comparable!r}"
                )
            continue
        by_identity[identity] = row
    return list(by_identity.values())


def _assert_single_value(rows: Sequence[dict[str, Any]], field: str) -> None:
    values = {row.get(field) for row in rows}
    if len(values) > 1:
        raise MergeStageError(
            f"multiple distinct {field!r} values found across the merge: "
            f"{sorted(map(repr, values))}"
        )


def check_coverage_20k(rows: Sequence[dict[str, Any]], *, mixed_only: bool = False) -> None:
    expected = set(range(16)) | {48} if mixed_only else set(range(49))
    got = {row["cell_index"] for row in rows}
    missing = expected - got
    extra = got - expected if not mixed_only else set()
    if missing:
        raise MergeCoverageError(f"20k merge missing cell(s): {sorted(missing)}")
    if extra:
        raise MergeCoverageError(f"20k merge has unexpected cell(s): {sorted(extra)}")


def check_coverage_80k(
    rows: Sequence[dict[str, Any]],
    *,
    indeterminate_cells: Sequence[int],
    n_substreams: int = 4,
) -> None:
    expected = {(cell, sub) for cell in indeterminate_cells for sub in range(n_substreams)}
    got = {(row["cell_index"], row["substream"]) for row in rows}
    missing = expected - got
    if missing:
        raise MergeCoverageError(f"80k merge missing (cell, substream) pair(s): {sorted(missing)}")


def merge_stage(
    paths: Iterable[Path],
    *,
    stage: str,
    mixed_only: bool = False,
    indeterminate_cells: Sequence[int] | None = None,
    n_substreams: int = 4,
) -> list[dict[str, Any]]:
    """Load, dedupe, validate provenance singularity and check coverage for
    ONE stage. Returns the merged rows sorted by `(cell_index, substream)`."""
    rows = load_stage_rows(paths, stage=stage)
    rows = dedupe_rows(rows)
    if stage in ("cal_c", "20k", "80k"):
        _assert_single_value(rows, "code_sha")
        _assert_single_value(rows, "eps_pin_sha256")

    if stage == "20k":
        check_coverage_20k(rows, mixed_only=mixed_only)
    elif stage == "80k":
        if indeterminate_cells is None:
            raise ValueError("stage='80k' requires indeterminate_cells")
        check_coverage_80k(rows, indeterminate_cells=indeterminate_cells, n_substreams=n_substreams)

    return sorted(rows, key=lambda r: (r["cell_index"], r.get("substream") or 0))


_INTEGER_SUM_FIELDS: Final[tuple[str, ...]] = (
    "crossing_count",
    "n_reps",
    "sum_look_count",
    "loss_stop_count",
)
_FLOAT_SUM_FIELDS: Final[tuple[str, ...]] = ("sum_s_terminal", "sum_s2_terminal")


def pool_80k_substreams(sub_rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Pool the 4 pinned 80k sub-streams into ONE result by exact integer
    and sum arithmetic (amendment §2.4 "80k as 4 pinned sub-streams", §3.3
    "pools ... from integer counts and raw sums"). Never pooled with the
    20k result (Rev 2.1 A)."""
    if not sub_rows:
        raise ValueError("cannot pool zero 80k sub-streams")

    pooled: dict[str, Any] = {
        field: sum(row[field] for row in sub_rows) for field in _INTEGER_SUM_FIELDS
    }
    for field in _FLOAT_SUM_FIELDS:
        pooled[field] = sum(row[field] for row in sub_rows)

    n_reps = pooled["n_reps"]
    mean_s_terminal = pooled["sum_s_terminal"] / n_reps
    var_s_terminal = pooled["sum_s2_terminal"] / n_reps - mean_s_terminal * mean_s_terminal
    crossing_count = pooled["crossing_count"]

    pooled["mean_s_terminal"] = mean_s_terminal
    pooled["var_s_terminal"] = var_s_terminal
    pooled["mean_look_count"] = pooled["sum_look_count"] / n_reps
    pooled["crossing_rate"] = crossing_count / n_reps
    pooled["cp_upper"] = clopper_pearson_upper(crossing_count, n_reps)
    pooled["cp_lower"] = clopper_pearson_lower(crossing_count, n_reps)
    return pooled


def _sha256_of_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, choices=("cal_a", "cal_b", "cal_c", "20k", "80k"))
    parser.add_argument("--in", dest="in_paths", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--mixed-only", action="store_true")
    parser.add_argument("--indeterminate-cells", type=int, nargs="*", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    rows = merge_stage(
        args.in_paths,
        stage=args.stage,
        mixed_only=args.mixed_only,
        indeterminate_cells=args.indeterminate_cells,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    print(
        f"[aud07-m1c-merge] wrote {len(rows)} row(s) to {args.out}: "
        f"sha256={_sha256_of_file(args.out)}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
