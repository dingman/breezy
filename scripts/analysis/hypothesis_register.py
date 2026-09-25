#!/usr/bin/env python3
"""AUD-18 Slice A step 7: the I/O wrapper around
`breezy.analysis.hypothesis_ledger.register_hypothesis`.

See `docs/plans/backlog/AUDIT_2026-09-21/AUD-18-strategy-design-backtest-iterate-programme.md`
SS5(b), SS7 step 7. Writes only under
`<derived_root>/hypothesis/hypothesis_ledger.jsonl` -- `derived_root` defaults
to `~/.local/share/breezy/derived` and is overridable via `BREEZY_DERIVED_ROOT`
or `--derived-root`, mirroring `whole_tape_paper_replay.default_derived_root`.
This module never reads or writes anywhere else.

**This item's own use (SS7 step 7).** Registers the forecast-taker class's
CLOSED, TERMINAL disposition as data, not prose: `status=REJECTED`,
`k_variants=12` matching `PREREG_WP7_MULTIPLICITY_RULE`, zero alpha and zero
slot (SS6.1's zero-look exemption). Once written, a future registration
attempt reusing that `hypothesis_id` is refused by `register_hypothesis`'s
own duplicate check -- never relying on a human remembering the ruling.

**Never run against the real derived directory from a test.** Every test in
`tests/unit/test_hypothesis_register.py` passes an explicit
`--derived-root`/`path=` into a `tmp_path`. The real invocation this item
hands to the coordinator is named in that test module's docstring.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Final

from breezy.analysis.hypothesis_ledger import (
    DuplicateHypothesisIdError,
    HypothesisRecord,
    read_hypothesis_ledger,
    register_hypothesis,
    write_hypothesis_ledger,
)

__all__ = [
    "DERIVED_ROOT_ENV_VAR",
    "FORECAST_TAKER_HYPOTHESIS_CLASS",
    "FORECAST_TAKER_HYPOTHESIS_ID",
    "FORECAST_TAKER_K_VARIANTS",
    "default_derived_root",
    "ledger_path",
    "main",
    "register_and_persist",
    "register_forecast_taker_closed_disposition",
]

#: Shared with `scripts/analysis/whole_tape_paper_replay.py`'s own override
#: convention -- one env var name for "where derived artefacts live" repo-wide.
DERIVED_ROOT_ENV_VAR: Final[str] = "BREEZY_DERIVED_ROOT"

#: SS7 step 7's pre-decided closure: scored by `PREREG_WP7_MULTIPLICITY_RULE`,
#: never by this ledger -- registered here purely so a future duplicate
#: intake attempt is refused mechanically.
FORECAST_TAKER_HYPOTHESIS_ID: Final[str] = "H-FORECAST-TAKER-RUNG-SCREEN-2026-09-20"
FORECAST_TAKER_HYPOTHESIS_CLASS: Final[str] = "FORECAST_TAKER"
FORECAST_TAKER_K_VARIANTS: Final[int] = 12


def default_derived_root() -> Path:
    """`$BREEZY_DERIVED_ROOT` if set, else `~/.local/share/breezy/derived`."""
    override = os.environ.get(DERIVED_ROOT_ENV_VAR)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".local/share/breezy/derived"


def ledger_path(derived_root: Path) -> Path:
    return derived_root / "hypothesis" / "hypothesis_ledger.jsonl"


def _read_existing(path: Path) -> tuple[HypothesisRecord, ...]:
    if not path.exists():
        return ()
    return read_hypothesis_ledger(path)


def register_and_persist(*, path: Path, **register_kwargs: object) -> HypothesisRecord:
    """Read the ledger at `path` (empty if absent), register one hypothesis
    against it, then atomically rewrite the whole file with the new record
    appended. Duplicate detection is `register_hypothesis`'s own -- this
    function adds none of its own."""
    existing = _read_existing(path)
    record = register_hypothesis(existing_records=existing, **register_kwargs)  # type: ignore[arg-type]
    write_hypothesis_ledger(path, (*existing, record))
    return record


def register_forecast_taker_closed_disposition(
    *, path: Path, registered_at: str, freeze_commit: str
) -> HypothesisRecord:
    """SS7 step 7: register the forecast-taker class's CLOSED disposition."""
    return register_and_persist(
        path=path,
        hypothesis_id=FORECAST_TAKER_HYPOTHESIS_ID,
        hypothesis_class=FORECAST_TAKER_HYPOTHESIS_CLASS,
        registered_at=registered_at,
        k_variants=FORECAST_TAKER_K_VARIANTS,
        freeze_commit=freeze_commit,
        disposition="CLOSED",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--derived-root",
        type=Path,
        default=None,
        help=f"Overrides {DERIVED_ROOT_ENV_VAR} / the default derived root.",
    )
    parser.add_argument(
        "--registered-at", required=True, help="ISO date, pre-registration commit date."
    )
    parser.add_argument("--freeze-commit", required=True, help="git sha of the freeze-date commit.")
    parser.add_argument(
        "--register-forecast-taker-closed",
        action="store_true",
        help="Register SS7 step 7's forecast-taker CLOSED disposition record.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    derived_root = args.derived_root or default_derived_root()
    path = ledger_path(derived_root)
    if not args.register_forecast_taker_closed:
        print("error: no registration action requested (see --help)", file=sys.stderr)
        return 2
    try:
        record = register_forecast_taker_closed_disposition(
            path=path, registered_at=args.registered_at, freeze_commit=args.freeze_commit
        )
    except DuplicateHypothesisIdError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"registered {record.hypothesis_id} status={record.status} at {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
