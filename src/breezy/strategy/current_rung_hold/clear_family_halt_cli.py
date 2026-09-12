"""Operator tool to clear the ``pm_us_crh_cont`` family-wide halt.

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
from breezy.strategy.current_rung_hold.trial_day_latch import (
    CONTINUOUS_TRIAL_KEY_PREFIX,
    TrialDayLatchError,
    open_trial_day_latch,
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
    parser.add_argument(
        "--reason",
        required=True,
        type=_reason_type,
        help=f"non-trivial written justification, at least {MIN_REASON_LENGTH} characters",
    )
    parser.add_argument(
        "--evidence-path",
        required=True,
        type=_evidence_path_type,
        help="path to an existing evidence artefact; only its sha256 is recorded",
    )
    args = parser.parse_args(argv)

    try:
        store_path = resolve_store_path(source)
    except ExecStateDbNotConfiguredError as exc:
        print(f"breezy-clear-family-halt: {exc}; refused", file=err)
        return EXIT_REFUSED

    evidence_sha256 = hashlib.sha256(args.evidence_path.read_bytes()).hexdigest()

    store = SqliteStateStore(store_path)
    try:
        try:
            with open_submit_intent_latch(store, store_path) as intent_latch:
                trial_latch = open_trial_day_latch(
                    intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX
                )
                if not trial_latch.is_family_halted():
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
