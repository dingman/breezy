#!/usr/bin/env python3
"""AUD-07 M1c/M2 Rev 2 execution amendment -- automatic CAL acceptance
(amendment §4.4, §5 "CAL-c").

Checks, mechanically, that:
- every CAL-c row equals its matching CAL-a row on every RESULT field
  (i.e. every `M1cCellResult` field except the mode/provenance metadata
  that necessarily differs -- `boundary_mode`, `coarse_npts`, `eps`,
  `dt_min`, `eps_pin_sha256`, `refined_count`, `refine_reasons`,
  `audit_reps`, `audit_max_abs_delta_b`, `audit_disagreements`,
  `audit_every`);
- 0 audit disagreements across the CAL-c rows;
- reports the refine fraction `f` per cell.

Pass -> the 20k stage may start. Fail -> stop, write `FAILED`, no 20k run
(amendment §4.4).

No network. No repo writes except `--out`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Final

__all__ = ["CalCheckFailure", "check_cal_equality"]

#: Fields that necessarily differ between a pure CAL-a row and a refined
#: CAL-c row -- excluded from the byte-equality comparison.
_METADATA_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "boundary_mode",
        "coarse_npts",
        "eps",
        "dt_min",
        "eps_pin_sha256",
        "audit_every",
        "refined_count",
        "refine_reasons",
        "audit_reps",
        "audit_max_abs_delta_b",
        "audit_disagreements",
        "stage",
        "code_sha",
        "substream",
        "numpy_version",
        "scipy_version",
        "wall_s",
        "seed",
        "npts",
    }
)


class CalCheckFailure(RuntimeError):
    """CAL-c does not equal CAL-a on some result field, or an audit
    disagreement was recorded."""


def check_cal_equality(
    cal_a_rows: list[dict[str, Any]], cal_c_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """Returns a report dict on success; raises `CalCheckFailure` on any
    mismatch or audit disagreement."""
    by_cell_a = {row["cell_index"]: row for row in cal_a_rows}
    by_cell_c = {row["cell_index"]: row for row in cal_c_rows}

    if set(by_cell_a) != set(by_cell_c):
        raise CalCheckFailure(
            f"CAL-a covers cells {sorted(by_cell_a)}, CAL-c covers "
            f"{sorted(by_cell_c)} -- must match exactly"
        )

    per_cell_f: dict[int, float] = {}
    for cell_index, row_a in by_cell_a.items():
        row_c = by_cell_c[cell_index]
        if row_c.get("audit_disagreements", 0) != 0:
            raise CalCheckFailure(
                f"cell {cell_index}: {row_c['audit_disagreements']} audit "
                "disagreement(s) recorded"
            )
        for field, value_a in row_a.items():
            if field in _METADATA_FIELDS:
                continue
            value_c = row_c.get(field)
            if value_a != value_c:
                raise CalCheckFailure(
                    f"cell {cell_index}: field {field!r} differs: "
                    f"CAL-a={value_a!r} CAL-c={value_c!r}"
                )
        n_reps = row_c.get("n_reps") or 1
        per_cell_f[cell_index] = row_c.get("refined_count", 0) / n_reps

    return {"passed": True, "f_per_cell": per_cell_f}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cal-a", type=Path, required=True)
    parser.add_argument("--cal-c", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args(argv)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    cal_a_rows = _load_jsonl(args.cal_a)
    cal_c_rows = _load_jsonl(args.cal_c)
    try:
        report = check_cal_equality(cal_a_rows, cal_c_rows)
    except CalCheckFailure as exc:
        print(f"[aud07-m1c-cal-check] FAIL: {exc}", file=sys.stderr)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        failure_payload = json.dumps({"passed": False, "reason": str(exc)}, indent=2) + "\n"
        args.out.write_text(failure_payload, encoding="utf-8")
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"[aud07-m1c-cal-check] PASS: f_per_cell={report['f_per_cell']!r}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
