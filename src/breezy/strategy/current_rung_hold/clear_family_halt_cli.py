"""Operator tool to clear a continuous-rung-hold family halt.

Mirrors ``breezy-clear-submit-intent`` (R-7, ``breezy.runtime.clear_submit_intent_cli``):
never called from the trading process, never on a timer, never at startup.
Acquires the same exclusive flock as the node (via ``open_submit_intent_latch``,
since ``TrialDayLatch`` shares R-7's store and flock); if the node holds it,
this tool refuses.

Lives in the ``strategy`` layer, not ``runtime``, because it touches
``TrialDayLatch`` -- the layers contract in ``pyproject.toml`` forbids
``runtime`` from ever importing ``strategy``.

There is no automated clear for the family halt by design (see
``TrialDayLatch.record_duplicate_fill`` / ``is_family_halted`` /
``clear_family_halt`` in ``breezy.strategy.current_rung_hold.trial_day_latch``):
clearing is a build-side decision made with evidence, never a heuristic the
bot applies to itself. This tool requires a non-trivial written reason and an
existing evidence artefact (its sha256 is recorded, never its content) before
it will touch the halt key, and it writes an audit record before clearing.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import TextIO

from breezy.runtime.exec_state_db_path import ExecStateDbNotConfiguredError, resolve_store_path
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import (
    SubmitIntentLockHeld,
    SubmitIntentLockNotHeld,
    open_submit_intent_latch,
)
from breezy.strategy.current_rung_hold.family_id_arg import (
    FamilyIdArgError,
    resolve_continuous_family_arg,
)
from breezy.strategy.current_rung_hold.trial_day_latch import (
    CONTINUOUS_TRIAL_KEY_PREFIX,
    LEGACY_HALT_ATTRIBUTED_FAMILY_ID,
    TrialDayLatchError,
    decode_family_halt_state,
    open_trial_day_latch,
    read_family_halt_rows_readonly,
)

EXIT_OK = 0
EXIT_REFUSED = 2
EXIT_NOTHING_TO_CLEAR = 3

#: Below this, a `--reason` is presumed to be a placeholder, not evidence.
MIN_REASON_LENGTH = 20


def _reason_type(value: str) -> str:
    stripped = value.strip()
    if len(stripped) < MIN_REASON_LENGTH:
        raise argparse.ArgumentTypeError(
            f"--reason must be at least {MIN_REASON_LENGTH} characters"
        )
    return stripped


def _evidence_path_type(value: str) -> Path:
    path = Path(value)
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"--evidence-path does not exist: {value}")
    return path


def clear_family_halt(
    argv: list[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run the clear tool. Returns 0 cleared / 2 refused / 3 nothing to clear."""
    out = sys.stdout if stdout is None else stdout
    err = sys.stderr if stderr is None else stderr
    source = os.environ if env is None else env
    parser = argparse.ArgumentParser(prog="breezy-clear-family-halt")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--family-id", help="continuous-rung-hold family id to clear")
    target.add_argument(
        "--legacy",
        action="store_true",
        help="clear only an unattributable legacy halt; refuses the pinned v4 halt",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="read-only: report family halt state without taking the submit-intent lock",
    )
    parser.add_argument(
        "--families-dir",
        type=Path,
        default=Path("deploy/families"),
        help="directory containing registered family manifests",
    )
    parser.add_argument(
        "--reason",
        type=_reason_type,
        help=f"non-trivial written justification, at least {MIN_REASON_LENGTH} characters",
    )
    parser.add_argument(
        "--evidence-path",
        type=_evidence_path_type,
        help="path to an existing evidence artefact; only its sha256 is recorded",
    )
    args = parser.parse_args(argv)
    if not args.status and (args.reason is None or args.evidence_path is None):
        parser.error("--reason and --evidence-path are required unless --status is given")
    if args.status and args.legacy:
        parser.error("--status requires --family-id")

    if args.family_id is not None:
        try:
            resolve_continuous_family_arg(args.family_id, args.families_dir)
        except FamilyIdArgError as exc:
            print(f"breezy-clear-family-halt: {exc}; refused", file=err)
            return EXIT_REFUSED

    try:
        store_path = resolve_store_path(source)
    except ExecStateDbNotConfiguredError as exc:
        print(f"breezy-clear-family-halt: {exc}; refused", file=err)
        return EXIT_REFUSED

    if args.status:
        assert args.family_id is not None
        try:
            legacy_raw, family_raw = read_family_halt_rows_readonly(store_path, args.family_id)
            reading = decode_family_halt_state(args.family_id, legacy_raw, family_raw)
        except Exception as exc:  # noqa: BLE001 - any read-only status failure REFUSES
            print(
                f"breezy-clear-family-halt: status unreadable ({type(exc).__name__}); refused",
                file=err,
            )
            return EXIT_REFUSED
        print(
            "breezy-clear-family-halt: "
            f"family_id={args.family_id} halted={reading.halted} "
            f"source={reading.source} legacy={reading.legacy}",
            file=out,
        )
        return EXIT_OK

    evidence_sha256 = hashlib.sha256(args.evidence_path.read_bytes()).hexdigest()

    store = SqliteStateStore(store_path)
    try:
        try:
            with open_submit_intent_latch(store, store_path) as intent_latch:
                trial_latch = open_trial_day_latch(
                    intent_latch,
                    key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX,
                    family_id=args.family_id if args.family_id is not None else None,
                )
                if args.legacy:
                    try:
                        trial_latch.clear_legacy_family_halt(
                            reason=args.reason,
                            evidence_sha256=evidence_sha256,
                            ts_ns=time.time_ns(),
                        )
                    except TrialDayLatchError:
                        print("breezy-clear-family-halt: nothing to clear", file=out)
                        return EXIT_NOTHING_TO_CLEAR
                    print("breezy-clear-family-halt: legacy cleared", file=out)
                    return EXIT_OK
                assert args.family_id is not None
                state = trial_latch.family_halt_state()
                if not state.halted:
                    print("breezy-clear-family-halt: nothing to clear", file=out)
                    return EXIT_NOTHING_TO_CLEAR
                try:
                    trial_latch.clear_family_halt(
                        reason=args.reason,
                        evidence_sha256=evidence_sha256,
                        ts_ns=time.time_ns(),
                    )
                except TrialDayLatchError:
                    # Raced with a concurrent clear between the check above
                    # and this call, under the SAME flock -- report the
                    # same outcome a fresh run would see.
                    print("breezy-clear-family-halt: nothing to clear", file=out)
                    return EXIT_NOTHING_TO_CLEAR
        except SubmitIntentLockHeld:
            print("breezy-clear-family-halt: the node holds the lock; refused", file=err)
            return EXIT_REFUSED
        except SubmitIntentLockNotHeld:
            print("breezy-clear-family-halt: lock not held; refused", file=err)
            return EXIT_REFUSED
    finally:
        store.close()
    if args.family_id == LEGACY_HALT_ATTRIBUTED_FAMILY_ID:
        print("breezy-clear-family-halt: cleared family and retired pinned legacy", file=out)
    else:
        print("breezy-clear-family-halt: cleared", file=out)
    return EXIT_OK


def main(
    argv: list[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Console-script entrypoint."""
    return clear_family_halt(argv, env=env, stdout=stdout, stderr=stderr)


if __name__ == "__main__":
    raise SystemExit(main())
