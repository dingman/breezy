#!/usr/bin/env python
"""CLI: NBP weather-only skill study (SL-8; plan
`FORECAST_NBP_PROBABILISTIC_FAMILY_Rev3_2026-09-29.md` S7 row SL-8, S2).

Wires `breezy.analysis.nbp_calibration`'s pure gate machinery to real data:
NBP rows from `breezy.persistence.nbp_derived_store`, final-only CLI labels
via `settlement_truth_dataset.final_rows_for_gate`, and (for G2.0a) the IEM
ASOS daily-max instant. It runs the validation-stage method/recalibration
selection and writes the evidence-note skeleton plus the calibration
artefact (json + sha256).

**The holdout guard.** ``--stage validate`` (the default) never touches the
holdout. ``--stage holdout`` exists but this script is NOT the authority
that decides when the holdout may open -- it refuses outright unless
``--coordinator-authorized`` is passed explicitly. This mirrors
`nbp_calibration.open_holdout`'s own single-look refusal: a flag silently
defaulting to "on" would be exactly the kind of write-by-default footgun the
plan's S8 invariants and this repo's CLAUDE.md warn about.

This CLI's own wiring of the real NBP/CLI/IEM-ASOS join is intentionally
thin today -- SL-8's task is the module's presence, its stage guard, and its
plumbing into `nbp_calibration`; the real S1 data (SL-1..SL-5) this script
would read does not exist yet, and the plan is explicit that S2 build work
must not run the study on real data beyond a train/validate smoke test.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from breezy.analysis.nbp_calibration import DEFAULT_SPLITS

__all__ = [
    "HoldoutNotCoordinatorAuthorizedError",
    "build_arg_parser",
    "main",
]

_HOLDOUT_GUARD_FLAG: str = "--coordinator-authorized"


class HoldoutNotCoordinatorAuthorizedError(RuntimeError):
    """``--stage holdout`` was requested without the coordinator-only flag."""


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage",
        choices=("validate", "holdout"),
        default="validate",
        help="'validate' (default) never touches the holdout. 'holdout' needs "
        f"{_HOLDOUT_GUARD_FLAG}.",
    )
    parser.add_argument(
        "--coordinator-authorized",
        action="store_true",
        default=False,
        help="Required for --stage holdout. Never set this by default -- only "
        "an explicit coordinator call may open the holdout (plan S7 row SL-8).",
    )
    parser.add_argument("--nbp-derived-root", type=Path, default=None)
    parser.add_argument("--settlement-truth-root", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.stage == "holdout" and not args.coordinator_authorized:
        raise HoldoutNotCoordinatorAuthorizedError(
            f"--stage holdout needs {_HOLDOUT_GUARD_FLAG} -- only an explicit "
            "coordinator call may open it (plan S7 row SL-8)"
        )
    print(f"nbp_skill_study: stage={args.stage} splits={DEFAULT_SPLITS!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
