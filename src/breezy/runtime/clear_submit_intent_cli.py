"""Operator tool to retire an OPEN submit-intent latch (R-7) and recover a v2 slot table.

A SIXTH process. Never called from the trading process, never on a timer,
never at startup. Acquires the same exclusive flock as the node; if the node
holds it, this tool refuses (exit 2). Open-orders emptiness is never proof.

EXEC-PAR (plan r5 3.1, 3.6) adds, all node-down and never raising uncaught:

* ``--list`` the slots of a v1 or v2 table;
* ``--intent-id`` to clear one slot of a v2 table;
* ``--slot-key KEY --ack-unreadable-slot`` to drop an unreadable slot, only
  after the ORIGINAL table bytes were dumped (0600, fsynced with their
  directory) to ``<store>.unreadable_slot.<sha256(key)[:16]>.<ts>.bin``;
* ``--reset-entry-halt --ack-held-positions-reviewed`` to clear the breaker.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Final, TextIO

from breezy.runtime.exec_state_db_path import ExecStateDbNotConfiguredError, resolve_store_path
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import (
    CURRENT_INTENT_KEY,
    RetirementReason,
    SlotTable,
    SubmitIntent,
    SubmitIntentCorrupt,
    SubmitIntentLatch,
    SubmitIntentLockHeld,
    SubmitIntentLockNotHeld,
    decode_slot_table,
    open_submit_intent_latch,
)
from breezy.runtime.submit_intent_slots import is_valid_slot_key

__all__ = [
    "EXIT_NOTHING_OPEN",
    "EXIT_OK",
    "EXIT_REFUSED",
    "OPERATOR_ACK_ENV_VAR",
    "clear_submit_intent",
    "is_valid_slot_key",
    "main",
]

EXIT_OK = 0
EXIT_REFUSED = 2
EXIT_NOTHING_OPEN = 3

OPERATOR_ACK_ENV_VAR = "BREEZY_CLEAR_SUBMIT_INTENT_ACK"
_ACK_VALUE = "1"
_PREFIX: Final[str] = "breezy-clear-submit-intent"
_EVIDENCE_MODE: Final[int] = 0o600

_Action = Callable[[SubmitIntentLatch, SqliteStateStore], int]


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


def _slot_line(slot: SubmitIntent) -> str:
    return (
        f"slot intent_id={slot.intent_id} slug={slot.slug or '-'} "
        f"fingerprint={slot.fingerprint} created_ns={slot.created_ns} "
        f"is_exit={slot.is_exit}"
    )


def _fsync_directory(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_evidence(path: Path, content: bytes) -> None:
    """Create ``path`` exclusively (0600), write, fsync it and its directory.

    Raises ``OSError`` on any failure; a file this call created is removed, a
    pre-existing one (the ``O_EXCL`` refusal) is never touched.
    """
    fd = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        _EVIDENCE_MODE,
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            os.fchmod(handle.fileno(), _EVIDENCE_MODE)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_directory(path.parent)
    except OSError:
        path.unlink(missing_ok=True)
        raise


def _evidence_bytes(key: str, original: bytes, slot_text: bytes) -> bytes:
    """One header line, then the ORIGINAL table bytes verbatim to end of file."""
    header = {
        "key": key,
        "original_bytes_sha256": hashlib.sha256(original).hexdigest(),
        "slot_canonicalised_json_label": (
            "canonicalised (re-serialised) copy of the slot, for convenience; the "
            "ORIGINAL table bytes follow the first newline verbatim"
        ),
        "slot_canonicalised_json": slot_text.decode("utf-8", errors="replace"),
    }
    prefix = b"# breezy-unreadable-slot-evidence " + json.dumps(header).encode("utf-8")
    return prefix + b"\n" + original


def _evidence_path(store_path: Path, key: str, ts_ns: int) -> Path:
    """Named by a hash of the key, never the key itself (no path characters)."""
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return store_path.with_name(f"{store_path.name}.unreadable_slot.{digest}.{ts_ns}.bin")


def _read_table(store: SqliteStateStore) -> tuple[bytes | None, SlotTable]:
    raw = store.get(CURRENT_INTENT_KEY)
    return raw, decode_slot_table(raw)


def _list_action(out: TextIO) -> _Action:
    def run(_latch: SubmitIntentLatch, store: SqliteStateStore) -> int:
        _raw, table = _read_table(store)
        if not table.open and not table.unreadable:
            print(f"{_PREFIX}: nothing OPEN", file=out)
            return EXIT_NOTHING_OPEN
        print(
            f"{_PREFIX}: table version={table.version} open={len(table.open)} "
            f"unreadable={len(table.unreadable)}",
            file=out,
        )
        for slot in table.open:
            print(f"{_PREFIX}: {_slot_line(slot)}", file=out)
        for key, _text in table.unreadable:
            print(f"{_PREFIX}: unreadable key={key}", file=out)
        return EXIT_OK

    return run


def _clear_action(intent_id: str | None, out: TextIO, err: TextIO) -> _Action:
    def run(latch: SubmitIntentLatch, store: SqliteStateStore) -> int:
        _raw, table = _read_table(store)
        if not table.open and not table.unreadable:
            print(f"{_PREFIX}: nothing OPEN", file=out)
            return EXIT_NOTHING_OPEN
        if not table.open:
            print(f"{_PREFIX}: only unreadable slots remain; use --slot-key; refused", file=err)
            return EXIT_REFUSED
        if table.version == 2 and intent_id is None:
            print(f"{_PREFIX}: a v2 slot table needs --intent-id; refused", file=err)
            for slot in table.open:
                print(f"{_PREFIX}: {_slot_line(slot)}", file=err)
            return EXIT_REFUSED
        target = next((s for s in table.open if intent_id in (None, s.intent_id)), None)
        if target is None:
            print(f"{_PREFIX}: no OPEN slot with that --intent-id; refused", file=err)
            return EXIT_REFUSED
        print(
            f"{_PREFIX}: OPEN intent "
            f"intent_id={target.intent_id} fingerprint={target.fingerprint} "
            f"created_ns={target.created_ns} state={target.state.value}",
            file=out,
        )
        latch.retire(target.intent_id, RetirementReason.OPERATOR_CLEARED, now_ns=target.created_ns)
        print(f"{_PREFIX}: cleared", file=out)
        return EXIT_OK

    return run


def _slot_key_action(key: str, store_path: Path, now_ns: int, out: TextIO, err: TextIO) -> _Action:
    def run(latch: SubmitIntentLatch, store: SqliteStateStore) -> int:
        original, table = _read_table(store)
        unreadable = dict(table.unreadable)
        if original is None or key not in unreadable:
            print(f"{_PREFIX}: {key!r} is not an unreadable slot of the table; refused", file=err)
            return EXIT_REFUSED
        evidence = _evidence_path(store_path, key, now_ns)
        try:
            _write_evidence(evidence, _evidence_bytes(key, original, unreadable[key]))
        except OSError as exc:
            print(
                f"{_PREFIX}: evidence dump failed ({type(exc).__name__}); slot kept; refused",
                file=err,
            )
            return EXIT_REFUSED
        latch.discard_unreadable_slot(key, now_ns=now_ns)
        print(f"{_PREFIX}: removed unreadable slot key={key} evidence={evidence}", file=out)
        return EXIT_OK

    return run


def _reset_action(out: TextIO) -> _Action:
    def run(latch: SubmitIntentLatch, _store: SqliteStateStore) -> int:
        if not latch.reset_breaker_halt():
            print(f"{_PREFIX}: no halted breaker record", file=out)
            return EXIT_NOTHING_OPEN
        print(f"{_PREFIX}: entry halt reset", file=out)
        return EXIT_OK

    return run


def _run_under_lock(store_path: Path, action: _Action, err: TextIO) -> int:
    store = SqliteStateStore(store_path)
    try:
        with open_submit_intent_latch(store, store_path) as latch:
            return action(latch, store)
    except SubmitIntentLockHeld:
        print(f"{_PREFIX}: the node holds the lock; refused", file=err)
        return EXIT_REFUSED
    except SubmitIntentLockNotHeld:
        print(f"{_PREFIX}: lock not held; refused", file=err)
        return EXIT_REFUSED
    except SubmitIntentCorrupt:
        print(f"{_PREFIX}: the slot table is corrupt; refused", file=err)
        return EXIT_REFUSED
    finally:
        store.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="breezy-clear-submit-intent")
    parser.add_argument("--yes", action="store_true", help="required confirmation")
    parser.add_argument("--resolution", help="order-id=<id> or no-order-exists")
    parser.add_argument("--evidence", type=Path, help="path to a positions + fill-record artefact")
    parser.add_argument("--intent-id", help="the slot to clear (required for a v2 table)")
    parser.add_argument("--list", action="store_true", help="list the slots and exit")
    parser.add_argument("--slot-key", help="an unreadable slot to drop (node down)")
    parser.add_argument("--ack-unreadable-slot", action="store_true")
    parser.add_argument("--reset-entry-halt", action="store_true")
    parser.add_argument("--ack-held-positions-reviewed", action="store_true")
    return parser


def _clear_with_evidence(
    args: argparse.Namespace, store_path: Path, out: TextIO, err: TextIO
) -> int:
    evidence_path: Path = args.evidence
    if not evidence_path.is_file():
        print(f"{_PREFIX}: evidence file is missing; refused", file=err)
        return EXIT_REFUSED
    try:
        evidence = _load_evidence(evidence_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"{_PREFIX}: evidence unreadable ({exc}); refused", file=err)
        return EXIT_REFUSED
    evidence_reason = _evidence_is_sufficient(evidence, args.resolution)
    if evidence_reason is not None:
        print(f"{_PREFIX}: {evidence_reason}; refused", file=err)
        return EXIT_REFUSED
    return _run_under_lock(store_path, _clear_action(args.intent_id, out, err), err)


def _drop_unreadable(
    args: argparse.Namespace, store_path: Path, now_ns: int, out: TextIO, err: TextIO
) -> int:
    key: str | None = args.slot_key
    if key is None or not args.ack_unreadable_slot:
        print(f"{_PREFIX}: --slot-key and --ack-unreadable-slot go together; refused", file=err)
        return EXIT_REFUSED
    if not is_valid_slot_key(key):
        print(f"{_PREFIX}: --slot-key is not a valid slot key; refused", file=err)
        return EXIT_REFUSED
    return _run_under_lock(store_path, _slot_key_action(key, store_path, now_ns, out, err), err)


def clear_submit_intent(
    argv: list[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    clock_ns: Callable[[], int] | None = None,
) -> int:
    """Run the clear tool. Returns 0 cleared / 2 refused / 3 nothing OPEN."""
    out = sys.stdout if stdout is None else stdout
    err = sys.stderr if stderr is None else stderr
    source = os.environ if env is None else env
    now = time.time_ns if clock_ns is None else clock_ns
    parser = _build_parser()
    args = parser.parse_args(argv)
    slot_mode = args.slot_key is not None or args.ack_unreadable_slot
    modes = (args.list, args.reset_entry_halt, slot_mode)
    if sum(modes) > 1:
        parser.error("--list, --reset-entry-halt and --slot-key are mutually exclusive")
    if not any(modes) and (args.resolution is None or args.evidence is None):
        parser.error("the following arguments are required: --resolution, --evidence")

    if args.list:
        return _list_mode(source, out, err)
    if source.get(OPERATOR_ACK_ENV_VAR) != _ACK_VALUE:
        print(f"{_PREFIX}: operator ack is absent; refused", file=err)
        return EXIT_REFUSED
    if not args.yes:
        print(f"{_PREFIX}: --yes is required; refused", file=err)
        return EXIT_REFUSED
    if args.reset_entry_halt and not args.ack_held_positions_reviewed:
        print(f"{_PREFIX}: --ack-held-positions-reviewed is required; refused", file=err)
        return EXIT_REFUSED

    try:
        store_path = resolve_store_path(source)
    except ExecStateDbNotConfiguredError as exc:
        print(f"{_PREFIX}: {exc}; refused", file=err)
        return EXIT_REFUSED
    if args.reset_entry_halt:
        return _run_under_lock(store_path, _reset_action(out), err)
    if slot_mode:
        return _drop_unreadable(args, store_path, now(), out, err)
    return _clear_with_evidence(args, store_path, out, err)


def _list_mode(source: Mapping[str, str], out: TextIO, err: TextIO) -> int:
    try:
        store_path = resolve_store_path(source)
    except ExecStateDbNotConfiguredError as exc:
        print(f"{_PREFIX}: {exc}; refused", file=err)
        return EXIT_REFUSED
    return _run_under_lock(store_path, _list_action(out), err)


def main(
    argv: list[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    clock_ns: Callable[[], int] | None = None,
) -> int:
    """Console-script entrypoint. The B9-pinned one caller of clear_submit_intent."""
    return clear_submit_intent(argv, env=env, stdout=stdout, stderr=stderr, clock_ns=clock_ns)


if __name__ == "__main__":
    raise SystemExit(main())
