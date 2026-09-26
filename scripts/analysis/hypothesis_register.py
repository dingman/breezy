#!/usr/bin/env python3
"""AUD-18 Slice A step 7, and the AUD-18 remainder (2026-09-25): the I/O
wrapper around `breezy.analysis.hypothesis_ledger.register_hypothesis`.

See `docs/plans/backlog/AUDIT_2026-09-21/AUD-18-strategy-design-backtest-iterate-programme.md`
SS5(b), SS7 steps 7-8. Writes only under
`<derived_root>/hypothesis/hypothesis_ledger.jsonl` -- `derived_root` defaults
to `~/.local/share/breezy/derived` and is overridable via `BREEZY_DERIVED_ROOT`
or `--derived-root`, mirroring `whole_tape_paper_replay.default_derived_root`.
This module never reads or writes anywhere else.

**Forecast-taker CLOSED disposition (SS7 step 7).** Registers the
forecast-taker class's CLOSED, TERMINAL disposition as data, not prose:
`status=REJECTED`, `k_variants=12` matching `PREREG_WP7_MULTIPLICITY_RULE`,
zero alpha and zero slot (SS6.1's zero-look exemption). Once written, a future
registration attempt reusing that `hypothesis_id` is refused by
`register_hypothesis`'s own duplicate check -- never relying on a human
remembering the ruling.

**NO-side hunting UNDERPOWERED disposition (SS7 step 8, 2026-09-25).**
Registers `H-NO-SIDE-2026-09` per
`docs/evidence/RULING_H-NO-SIDE-2026-09_horizon_2026-09-25.md` §1/§4: MDE
0.0890 at the pre-registered `n=300` exceeds the ruling's `mde_plausibility_bound`
of 0.04, so `register_hypothesis` returns `UNDERPOWERED_NOT_REGISTERED`,
consuming no alpha and no slot. Every `NO_SIDE_*` constant below is pinned to
that ruling's numbered lines (cited inline) and its 2026-09-25 independent
peer pass appended in commit `329380f` (ENDORSED-WITH-NOTES).

**Archive-table recalibration UNDERPOWERED disposition (AUD-18a, 2026-09-26).**
Registers `H-ARCHIVE-RECAL-2026-09` per
`docs/evidence/RULING_H-ARCHIVE-RECAL-2026-09_horizon_2026-09-25.md` §1/§4:
MDE 0.0629 at the pre-registered `n=600` exceeds the ruling's
`mde_plausibility_bound` of 0.03, so `register_hypothesis` returns
`UNDERPOWERED_NOT_REGISTERED`, consuming no alpha and no slot. Every
`ARCHIVE_RECAL_*` constant below is pinned to that ruling's exact text (cited
inline); the ruling's own peer confirmation ("The :137 condition is closed.")
unblocked registration as this separate, later slice (see the AUD-18a plan
doc, `docs/plans/backlog/AUDIT_2026-09-21/AUD-18a_register_archive_recal_plan_r1_2026-09-26.md`).

**Never run against the real derived directory from a test.** Every test in
`tests/unit/test_hypothesis_register.py` passes an explicit
`--derived-root`/`path=` into a `tmp_path`. The real invocation this item
hands to the coordinator is named in that test module's docstring.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Final

from breezy.analysis.hypothesis_ledger import (
    EVIDENCED_FEE_THETA,
    MAX_HYPOTHESES,
    MAX_SINGLE_DAY_LEG_SHARE,
    PINNED_ORDER_QUANTITY,
    PROGRAMME_ALPHA,
    STATION_DAY_STATISTIC,
    VARIANCE_BOUND,
    DuplicateHypothesisIdError,
    HypothesisRecord,
    read_hypothesis_ledger,
    register_hypothesis,
    write_hypothesis_ledger,
)

__all__ = [
    "ARCHIVE_RECAL_FREEZE_COMMIT",
    "ARCHIVE_RECAL_HYPOTHESIS_CLASS",
    "ARCHIVE_RECAL_HYPOTHESIS_ID",
    "ARCHIVE_RECAL_K_VARIANTS",
    "ARCHIVE_RECAL_MDE",
    "ARCHIVE_RECAL_MIN_STATION_DAYS",
    "ARCHIVE_RECAL_PER_VARIANT_ALPHA",
    "ARCHIVE_RECAL_PLAUSIBILITY_BOUND",
    "ARCHIVE_RECAL_REFERENCE_ASK",
    "ARCHIVE_RECAL_RULING_DATE",
    "ARCHIVE_RECAL_SLIPPAGE_ALLOWANCE",
    "DERIVED_ROOT_ENV_VAR",
    "FORECAST_TAKER_HYPOTHESIS_CLASS",
    "FORECAST_TAKER_HYPOTHESIS_ID",
    "FORECAST_TAKER_K_VARIANTS",
    "NO_SIDE_FREEZE_COMMIT",
    "NO_SIDE_HYPOTHESIS_CLASS",
    "NO_SIDE_HYPOTHESIS_ID",
    "NO_SIDE_K_VARIANTS",
    "NO_SIDE_MDE",
    "NO_SIDE_MIN_STATION_DAYS",
    "NO_SIDE_PER_VARIANT_ALPHA",
    "NO_SIDE_PLAUSIBILITY_BOUND",
    "NO_SIDE_REFERENCE_ASK",
    "NO_SIDE_RULING_DATE",
    "NO_SIDE_SLIPPAGE_ALLOWANCE",
    "UnexpectedRegistrationStatusError",
    "default_derived_root",
    "ledger_path",
    "main",
    "register_and_persist",
    "register_archive_recal_underpowered",
    "register_forecast_taker_closed_disposition",
    "register_no_side_underpowered",
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

#: RULING_H-NO-SIDE-2026-09_horizon_2026-09-25.md §1 table (non-bold cells) --
#: `hypothesis_id`/`hypothesis_class`. The ruling's peer section (committed
#: same-commit as the draft, `05f272f`) is superseded as the evidential
#: signature of record by the independent pass appended in `329380f`
#: (ENDORSED-WITH-NOTES) -- see the AUD-18 plan doc's dated 2026-09-25
#: amendment.
NO_SIDE_HYPOTHESIS_ID: Final[str] = "H-NO-SIDE-2026-09"
NO_SIDE_HYPOTHESIS_CLASS: Final[str] = "no_side_hunting"
#: §1 -- one NO-side design, not a sweep.
NO_SIDE_K_VARIANTS: Final[int] = 1
#: §1 -- with-takes station-days at full 5-station accrual after NO-leg
#: capture exists (owned by AUD-02, currently PARKED).
NO_SIDE_MIN_STATION_DAYS: Final[int] = 300
#: §1/§2 -- `allocated_alpha = PROGRAMME_ALPHA / MAX_HYPOTHESES = 0.05/4 =
#: 0.0125`; `per_variant_alpha = 0.0125 / NO_SIDE_K_VARIANTS = 0.0125`.
NO_SIDE_PER_VARIANT_ALPHA: Final[float] = PROGRAMME_ALPHA / MAX_HYPOTHESES / NO_SIDE_K_VARIANTS
#: §2 -- "`3.08302/34.6410 = 0.0890`" at `n=300`; `recompute_mde` reproduces
#: this within `MDE_MISMATCH_TOLERANCE` (`hypothesis_ledger.py:469-482`).
NO_SIDE_MDE: Final[float] = 0.0890
#: §3 -- "`mde_plausibility_bound = 0.04`".
NO_SIDE_PLAUSIBILITY_BOUND: Final[float] = 0.04
#: §2 Market terms -- "Reference ask `a=0.30`".
NO_SIDE_REFERENCE_ASK: Final[float] = 0.30
#: §2 Market terms -- AUD-12's unmeasured placeholder.
NO_SIDE_SLIPPAGE_ALLOWANCE: Final[float] = 0.01
#: §0/§1 -- fixed before this ruling's issuance (independent-pass erratum,
#: `329380f`: `49261a5` precedes ruling commit `05f272f`, not the reverse).
NO_SIDE_FREEZE_COMMIT: Final[str] = "49261a5c2119fc621863ad7df05af1e2a96c6b55"
#: Peer section dated 2026-09-25; the independent pass appended the same date.
NO_SIDE_RULING_DATE: Final[str] = "2026-09-25"

#: RULING_H-ARCHIVE-RECAL-2026-09_horizon_2026-09-25.md §1 table --
#: `hypothesis_id`/`hypothesis_class`. The ruling's own peer confirmation
#: ("The :137 condition is closed.") unblocked registration as this
#: deliberately separate, later slice (AUD-18a).
ARCHIVE_RECAL_HYPOTHESIS_ID: Final[str] = "H-ARCHIVE-RECAL-2026-09"
ARCHIVE_RECAL_HYPOTHESIS_CLASS: Final[str] = "pm_us_crh_v4_archive_recalibration"
#: §1 -- one recalibration design, not a sweep ("| `k_variants` | **1** |").
ARCHIVE_RECAL_K_VARIANTS: Final[int] = 1
#: §1 -- with-takes station-days pooled across the design's registered
#: strata ("`min_station_days` (with-takes, §6.1 zero-take rule) | **600** |").
ARCHIVE_RECAL_MIN_STATION_DAYS: Final[int] = 600
#: §1/§2 -- `allocated_alpha = PROGRAMME_ALPHA / MAX_HYPOTHESES = 0.05/4 =
#: 0.0125`; `per_variant_alpha = 0.0125 / ARCHIVE_RECAL_K_VARIANTS = 0.0125`
#: ("`per_variant_alpha=0.0125`").
ARCHIVE_RECAL_PER_VARIANT_ALPHA: Final[float] = (
    PROGRAMME_ALPHA / MAX_HYPOTHESES / ARCHIVE_RECAL_K_VARIANTS
)
#: §2 -- "`3.08302/48.9898 = 0.0629`" at `n=600`; `recompute_mde` reproduces
#: this within `MDE_MISMATCH_TOLERANCE` (`hypothesis_ledger.py:469-482`).
ARCHIVE_RECAL_MDE: Final[float] = 0.0629
#: §3 -- "`mde_plausibility_bound = 0.03`".
ARCHIVE_RECAL_PLAUSIBILITY_BOUND: Final[float] = 0.03
#: §2 Market terms -- "reference ask `a = 0.30`".
ARCHIVE_RECAL_REFERENCE_ASK: Final[float] = 0.30
#: §2 Market terms -- AUD-12's unmeasured placeholder, restated PROVISIONAL
#: by the ruling's §6.
ARCHIVE_RECAL_SLIPPAGE_ALLOWANCE: Final[float] = 0.01
#: §0/§1 -- "`freeze_commit` | `49261a5c2119fc621863ad7df05af1e2a96c6b55`".
ARCHIVE_RECAL_FREEZE_COMMIT: Final[str] = "49261a5c2119fc621863ad7df05af1e2a96c6b55"
#: The ruling's own dated table date; the appended peer-confirmation pass
#: is the same date.
ARCHIVE_RECAL_RULING_DATE: Final[str] = "2026-09-25"

#: The 40-hex git sha shape. Lives ONLY at the CLI boundary (`main`) -- the
#: functions below (`register_forecast_taker_closed_disposition`,
#: `register_and_persist`) never validate `freeze_commit`'s format, so
#: existing direct-call tests using placeholder shas like `"deadbee"` stay
#: green.
_FREEZE_COMMIT_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")


class UnexpectedRegistrationStatusError(ValueError):
    """`register_and_persist` refuses to write when `register_hypothesis`'s
    outcome `status` does not match the caller's `require_status` -- catches
    an unexpected outcome (e.g. a design that unexpectedly powers up to
    `REGISTERED`) BEFORE any bytes reach the ledger file, rather than
    silently persisting a status the call site never intended."""


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


def register_and_persist(
    *, path: Path, require_status: str | None = None, **register_kwargs: object
) -> HypothesisRecord:
    """Read the ledger at `path` (empty if absent), register one hypothesis
    against it, then atomically rewrite the whole file with the new record
    appended. Duplicate detection is `register_hypothesis`'s own -- this
    function adds none of its own.

    `require_status`, when given, is checked BEFORE `write_hypothesis_ledger`
    is ever called: an outcome status that disagrees is a hard refusal
    (`UnexpectedRegistrationStatusError`), and the ledger file's bytes and
    mtime are left completely unchanged -- the write-order bug this function
    used to have (compute, then write unconditionally) is fixed by checking
    first.
    """
    existing = _read_existing(path)
    record = register_hypothesis(existing_records=existing, **register_kwargs)  # type: ignore[arg-type]
    if require_status is not None and record.status != require_status:
        raise UnexpectedRegistrationStatusError(
            f"expected status={require_status!r} for hypothesis_id="
            f"{record.hypothesis_id!r}, got status={record.status!r} -- refusing to write"
        )
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
        require_status="REJECTED",
    )


def register_no_side_underpowered(*, path: Path, registered_at: str) -> HypothesisRecord:
    """RULING_H-NO-SIDE-2026-09_horizon_2026-09-25.md §1/§4: registers the
    NO-side hunting hypothesis's pre-decided `UNDERPOWERED_NOT_REGISTERED`
    disposition (MDE 0.0890 > plausibility bound 0.04 at the pre-registered
    `n=300`, `hypothesis_ledger.py:648-673`).

    Every `NO_SIDE_*` input is referenced here as a module global, read at
    CALL time -- never bound as a default-argument value -- so a test can
    `monkeypatch.setattr` this module's constant (e.g.
    `NO_SIDE_PLAUSIBILITY_BOUND`) and observe the effect on the next call,
    including `register_and_persist`'s check-before-write refusal when that
    monkeypatched input would unexpectedly power the design up to
    `REGISTERED`.
    """
    return register_and_persist(
        path=path,
        hypothesis_id=NO_SIDE_HYPOTHESIS_ID,
        hypothesis_class=NO_SIDE_HYPOTHESIS_CLASS,
        registered_at=registered_at,
        k_variants=NO_SIDE_K_VARIANTS,
        freeze_commit=NO_SIDE_FREEZE_COMMIT,
        disposition="NORMAL",
        min_station_days=NO_SIDE_MIN_STATION_DAYS,
        max_single_day_leg_share_cap=MAX_SINGLE_DAY_LEG_SHARE,
        mde_at_allocated_alpha=NO_SIDE_MDE,
        mde_plausibility_bound=NO_SIDE_PLAUSIBILITY_BOUND,
        power_is_primary_only=True,
        mde_reference_ask=NO_SIDE_REFERENCE_ASK,
        mde_fee_theta=EVIDENCED_FEE_THETA,
        mde_slippage_allowance=NO_SIDE_SLIPPAGE_ALLOWANCE,
        mde_variance_bound=VARIANCE_BOUND,
        station_day_statistic=STATION_DAY_STATISTIC,
        order_quantity=PINNED_ORDER_QUANTITY,
        look_policy="SINGLE_LOOK",
        require_status="UNDERPOWERED_NOT_REGISTERED",
    )


def register_archive_recal_underpowered(*, path: Path, registered_at: str) -> HypothesisRecord:
    """RULING_H-ARCHIVE-RECAL-2026-09_horizon_2026-09-25.md §1/§4 (peer
    confirmation appended 2026-09-25, CONFIRMED-WITH-NOTES, closing the :137
    condition): registers the archive-table recalibration hypothesis's
    pre-decided `UNDERPOWERED_NOT_REGISTERED` disposition (MDE 0.0629 >
    plausibility bound 0.03 at the pre-registered `n=600`,
    `hypothesis_ledger.py:648-673`).

    Every `ARCHIVE_RECAL_*` input is referenced here as a module global, read
    at CALL time -- never bound as a default-argument value -- mirroring
    `register_no_side_underpowered`, so a test can `monkeypatch.setattr` this
    module's constant (e.g. `ARCHIVE_RECAL_PLAUSIBILITY_BOUND`) and observe
    the effect on the next call, including `register_and_persist`'s
    check-before-write refusal.
    """
    return register_and_persist(
        path=path,
        hypothesis_id=ARCHIVE_RECAL_HYPOTHESIS_ID,
        hypothesis_class=ARCHIVE_RECAL_HYPOTHESIS_CLASS,
        registered_at=registered_at,
        k_variants=ARCHIVE_RECAL_K_VARIANTS,
        freeze_commit=ARCHIVE_RECAL_FREEZE_COMMIT,
        disposition="NORMAL",
        min_station_days=ARCHIVE_RECAL_MIN_STATION_DAYS,
        max_single_day_leg_share_cap=MAX_SINGLE_DAY_LEG_SHARE,
        mde_at_allocated_alpha=ARCHIVE_RECAL_MDE,
        mde_plausibility_bound=ARCHIVE_RECAL_PLAUSIBILITY_BOUND,
        power_is_primary_only=True,
        mde_reference_ask=ARCHIVE_RECAL_REFERENCE_ASK,
        mde_fee_theta=EVIDENCED_FEE_THETA,
        mde_slippage_allowance=ARCHIVE_RECAL_SLIPPAGE_ALLOWANCE,
        mde_variance_bound=VARIANCE_BOUND,
        station_day_statistic=STATION_DAY_STATISTIC,
        order_quantity=PINNED_ORDER_QUANTITY,
        look_policy="SINGLE_LOOK",
        require_status="UNDERPOWERED_NOT_REGISTERED",
    )


#: `--register-underpowered`'s per-id dispatch table: maps a registrable
#: hypothesis_id to (registration function, its ruling's date gate, the
#: ruling file named in the CLI's date-gate error message). Replaces the
#: single `NO_SIDE_RULING_DATE` gate now that a second id is registrable.
_UNDERPOWERED_REGISTRATIONS: Final[
    dict[str, tuple[Callable[..., HypothesisRecord], str, str]]
] = {
    NO_SIDE_HYPOTHESIS_ID: (
        register_no_side_underpowered,
        NO_SIDE_RULING_DATE,
        "RULING_H-NO-SIDE-2026-09_horizon_2026-09-25.md",
    ),
    ARCHIVE_RECAL_HYPOTHESIS_ID: (
        register_archive_recal_underpowered,
        ARCHIVE_RECAL_RULING_DATE,
        "RULING_H-ARCHIVE-RECAL-2026-09_horizon_2026-09-25.md",
    ),
}


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
    parser.add_argument(
        "--freeze-commit",
        default=None,
        help="git sha of the freeze-date commit. Required only for "
        "--register-forecast-taker-closed; refused for --register-underpowered.",
    )
    action_group = parser.add_mutually_exclusive_group()
    action_group.add_argument(
        "--register-forecast-taker-closed",
        action="store_true",
        help="Register SS7 step 7's forecast-taker CLOSED disposition record.",
    )
    action_group.add_argument(
        "--register-underpowered",
        choices=list(_UNDERPOWERED_REGISTRATIONS),
        default=None,
        help="Register the named hypothesis's pre-decided "
        "UNDERPOWERED_NOT_REGISTERED disposition.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    derived_root = args.derived_root or default_derived_root()
    path = ledger_path(derived_root)

    if args.register_forecast_taker_closed:
        if not args.freeze_commit or not _FREEZE_COMMIT_RE.match(args.freeze_commit):
            print(
                "error: --freeze-commit must be a 40-hex git sha for "
                "--register-forecast-taker-closed",
                file=sys.stderr,
            )
            return 2
        try:
            record = register_forecast_taker_closed_disposition(
                path=path, registered_at=args.registered_at, freeze_commit=args.freeze_commit
            )
        except (DuplicateHypothesisIdError, UnexpectedRegistrationStatusError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"registered {record.hypothesis_id} status={record.status} at {path}")
        return 0

    if args.register_underpowered:
        if args.freeze_commit is not None:
            print(
                "error: --freeze-commit is only valid with "
                "--register-forecast-taker-closed",
                file=sys.stderr,
            )
            return 2
        register_fn, ruling_date, ruling_file = _UNDERPOWERED_REGISTRATIONS[
            args.register_underpowered
        ]
        if args.registered_at < ruling_date:
            print(
                f"error: --registered-at must be on or after {ruling_date} "
                f"({ruling_file}'s date)",
                file=sys.stderr,
            )
            return 2
        try:
            record = register_fn(path=path, registered_at=args.registered_at)
        except (DuplicateHypothesisIdError, UnexpectedRegistrationStatusError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"registered {record.hypothesis_id} status={record.status} at {path}")
        return 0

    print("error: no registration action requested (see --help)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
