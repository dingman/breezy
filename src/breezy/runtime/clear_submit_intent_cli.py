"""Operator tool to retire an OPEN submit-intent latch (R-7).

A SIXTH process. Never called from the trading process, never on a timer,
never at startup. Acquires the same exclusive flock as the node; if the node
holds it, this tool refuses (exit 2). Open-orders emptiness is never proof.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import TextIO

from breezy.adapters.polymarket_us.factories import EXEC_STATE_DB_ENV_VAR
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import (
    RetirementReason,
    SubmitIntentLockHeld,
    SubmitIntentLockNotHeld,
    SubmitIntentState,
    open_submit_intent_latch,
)

EXIT_OK = 0
EXIT_REFUSED = 2
EXIT_NOTHING_OPEN = 3

OPERATOR_ACK_ENV_VAR = "BREEZY_CLEAR_SUBMIT_INTENT_ACK"
_ACK_VALUE = "1"


def _load_evidence(path: Path) -> dict[str, object]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TypeError("evidence artefact must be a JSON object")
    return raw


def _evidence_is_sufficient(payload: Mapping[str, object], resolution: str) -> str | None:
    """Return a refusal reason, or None if the artefact is acceptable.

    Open-orders emptiness is never proof. Positions plus a fill-record (or an
    explicit no-fill attestation for ``no-order-exists``) are required.
    """
    if "positions" not in payload:
        return "evidence must include a positions snapshot"
    if list(payload.keys()) == ["open_orders"] or (
        "open_orders" in payload and "positions" not in payload
    ):
        return "open-orders emptiness is never proof"
    if resolution.startswith("order-id="):
        if payload.get("fill_record") is None and payload.get("fills") is None:
            return "order-id resolution requires a fill-record in the evidence"
        return None
    if resolution == "no-order-exists":
        if payload.get("fill_record") not in (None, {}) and payload.get("fills") not in (
            None,
            [],
        ):
            return "no-order-exists requires an empty fill-record attestation"
        return None
    return f"unknown resolution {resolution!r}"


def clear_submit_intent(
    argv: list[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run the clear tool. Returns 0 cleared / 2 refused / 3 nothing OPEN."""
    out = sys.stdout if stdout is None else stdout
    err = sys.stderr if stderr is None else stderr
    source = os.environ if env is None else env
    parser = argparse.ArgumentParser(prog="breezy-clear-submit-intent")
    parser.add_argument("--yes", action="store_true", help="required confirmation")
    parser.add_argument(
        "--resolution",
        required=True,
        help="order-id=<id> or no-order-exists",
    )
    parser.add_argument(
        "--evidence",
        required=True,
        type=Path,
        help="path to a positions + fill-record artefact",
    )
    args = parser.parse_args(argv)

    if source.get(OPERATOR_ACK_ENV_VAR) != _ACK_VALUE:
        print("breezy-clear-submit-intent: operator ack is absent; refused", file=err)
        return EXIT_REFUSED
    if not args.yes:
        print("breezy-clear-submit-intent: --yes is required; refused", file=err)
        return EXIT_REFUSED

    evidence_path: Path = args.evidence
    if not evidence_path.is_file():
        print("breezy-clear-submit-intent: evidence file is missing; refused", file=err)
        return EXIT_REFUSED
    try:
        evidence = _load_evidence(evidence_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"breezy-clear-submit-intent: evidence unreadable ({exc}); refused", file=err)
        return EXIT_REFUSED
    evidence_reason = _evidence_is_sufficient(evidence, args.resolution)
    if evidence_reason is not None:
        print(f"breezy-clear-submit-intent: {evidence_reason}; refused", file=err)
        return EXIT_REFUSED

    raw_state_db = source.get(EXEC_STATE_DB_ENV_VAR, "").strip()
    if not raw_state_db:
        print("breezy-clear-submit-intent: exec state db is unset; refused", file=err)
        return EXIT_REFUSED
    store_path = Path(raw_state_db)
    store = SqliteStateStore(store_path)
    try:
        try:
            with open_submit_intent_latch(store, store_path) as latch:
                current = latch.current()
                if current is None or current.state is not SubmitIntentState.OPEN:
                    print("breezy-clear-submit-intent: nothing OPEN", file=out)
                    return EXIT_NOTHING_OPEN
                print(
                    "breezy-clear-submit-intent: OPEN intent "
                    f"intent_id={current.intent_id} fingerprint={current.fingerprint} "
                    f"created_ns={current.created_ns} state={current.state.value}",
                    file=out,
                )
                latch.retire(
                    current.intent_id,
                    RetirementReason.OPERATOR_CLEARED,
                    now_ns=current.created_ns,
                )
        except SubmitIntentLockHeld:
            print(
                "breezy-clear-submit-intent: the node holds the lock; refused",
                file=err,
            )
            return EXIT_REFUSED
        except SubmitIntentLockNotHeld:
            print("breezy-clear-submit-intent: lock not held; refused", file=err)
            return EXIT_REFUSED
    finally:
        store.close()
    print("breezy-clear-submit-intent: cleared", file=out)
    return EXIT_OK


def main(
    argv: list[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Console-script entrypoint. The B9-pinned one caller of clear_submit_intent."""
    return clear_submit_intent(argv, env=env, stdout=stdout, stderr=stderr)


if __name__ == "__main__":
    raise SystemExit(main())
