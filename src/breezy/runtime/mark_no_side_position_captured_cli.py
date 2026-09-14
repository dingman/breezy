"""Operator tool to record the NO-side position-shape ruling (S5 plan, E2-1
(ii)/E3-6/E4-3).

Mirrors ``clear_submit_intent_cli.py``'s structure and safety exactly: an
EIGHTH process, never called from the trading process, never on a timer,
never at startup. Acquires the SAME exclusive flock as the node; if the
node holds it, this tool refuses (exit 2).

Writing :data:`NO_SIDE_POSITION_SHAPE_CAPTURED_KEY` ends the bounded
first-order containment window (amendment §8 item 4): it is the ONLY
sanctioned write site for that key -- see the E3-7 structural scan
(``tests/unit/test_no_side_keys.py``). This tool refuses to write it while
:data:`NO_SIDE_FIRST_LIVE_ORDER_KEY` is absent -- there is nothing to
terminate the containment window FOR.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Mapping
from typing import TextIO

from breezy.adapters.polymarket_us.exec.no_side_keys import (
    NO_SIDE_FIRST_LIVE_ORDER_KEY,
    NO_SIDE_POSITION_SHAPE_CAPTURED_KEY,
)
from breezy.runtime.exec_state_db_path import ExecStateDbNotConfiguredError, resolve_store_path
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import (
    SubmitIntentLockHeld,
    SubmitIntentLockNotHeld,
    open_submit_intent_latch,
)

EXIT_OK = 0
EXIT_REFUSED = 2
EXIT_NOT_PENDING = 3

OPERATOR_ACK_ENV_VAR = "BREEZY_MARK_NO_SIDE_POSITION_CAPTURED_ACK"
_ACK_VALUE = "1"


def mark_no_side_position_captured(
    argv: list[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    now_ns: int | None = None,
) -> int:
    """Run the tool. Returns 0 written / 2 refused / 3 not pending."""
    out = sys.stdout if stdout is None else stdout
    err = sys.stderr if stderr is None else stderr
    source = os.environ if env is None else env
    parser = argparse.ArgumentParser(prog="breezy-mark-no-side-position-captured")
    parser.add_argument("--yes", action="store_true", help="required confirmation")
    parser.add_argument(
        "--ruling-path",
        required=True,
        help="path (repo-relative) to the position-shape ruling artefact",
    )
    parser.add_argument(
        "--ruling-sha",
        required=True,
        help="git sha of the commit the ruling was reviewed at",
    )
    args = parser.parse_args(argv)

    if source.get(OPERATOR_ACK_ENV_VAR) != _ACK_VALUE:
        print(
            "breezy-mark-no-side-position-captured: operator ack is absent; refused",
            file=err,
        )
        return EXIT_REFUSED
    if not args.yes:
        print(
            "breezy-mark-no-side-position-captured: --yes is required; refused",
            file=err,
        )
        return EXIT_REFUSED

    try:
        store_path = resolve_store_path(source)
    except ExecStateDbNotConfiguredError as exc:
        print(f"breezy-mark-no-side-position-captured: {exc}; refused", file=err)
        return EXIT_REFUSED
    store = SqliteStateStore(store_path)
    try:
        try:
            with open_submit_intent_latch(store, store_path) as latch:
                shared_store, _lock = latch.shared_state_binding()
                if shared_store.get(NO_SIDE_FIRST_LIVE_ORDER_KEY) is None:
                    print(
                        "breezy-mark-no-side-position-captured: no first NO order "
                        "on record; nothing to terminate",
                        file=out,
                    )
                    return EXIT_NOT_PENDING
                if shared_store.get(NO_SIDE_POSITION_SHAPE_CAPTURED_KEY) is not None:
                    print(
                        "breezy-mark-no-side-position-captured: already captured",
                        file=out,
                    )
                    return EXIT_OK
                payload = {
                    "rulingPath": args.ruling_path,
                    "rulingSha": args.ruling_sha,
                    "tsNs": now_ns if now_ns is not None else time.time_ns(),
                }
                shared_store.set(
                    NO_SIDE_POSITION_SHAPE_CAPTURED_KEY,
                    json.dumps(payload, sort_keys=True).encode("utf-8"),
                )
        except SubmitIntentLockHeld:
            print(
                "breezy-mark-no-side-position-captured: the node holds the lock; refused",
                file=err,
            )
            return EXIT_REFUSED
        except SubmitIntentLockNotHeld:
            print("breezy-mark-no-side-position-captured: lock not held; refused", file=err)
            return EXIT_REFUSED
    finally:
        store.close()
    print("breezy-mark-no-side-position-captured: captured", file=out)
    return EXIT_OK


def main(
    argv: list[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Console-script entrypoint."""
    return mark_no_side_position_captured(argv, env=env, stdout=stdout, stderr=stderr)


if __name__ == "__main__":
    raise SystemExit(main())
