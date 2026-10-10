"""EXEC-PAR WP5a: the operator clear tool decodes the v2 slot table (plan r5 3.1, 3.6)."""

from __future__ import annotations

import errno
import hashlib
import io
import json
import os
import sqlite3
import stat
from collections.abc import Callable
from pathlib import Path

import pytest

from breezy.adapters.polymarket_us.factories import EXEC_STATE_DB_ENV_VAR
from breezy.runtime import clear_submit_intent_cli as cli
from breezy.runtime.clear_submit_intent_cli import (
    EXIT_NOTHING_OPEN,
    EXIT_OK,
    EXIT_REFUSED,
    OPERATOR_ACK_ENV_VAR,
    main,
)
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import (
    BREAKER_KEY,
    CURRENT_INTENT_KEY,
    SubmitIntent,
    SubmitIntentLatch,
    SubmitIntentMismatch,
    SubmitIntentState,
    history_key,
    open_submit_intent_latch,
)
from breezy.runtime.submit_intent_slots import BreakerRecord, encode_breaker, encode_v2

T = 1_790_000_000_000_000_000
FIXED_TS = 1_790_000_999_000_000_000
UNREADABLE_KEY = "odd.slot-1"


def _id(n: int) -> str:
    return f"{n:032x}"


def _open(n: int, slug: str = "slug-a") -> SubmitIntent:
    return SubmitIntent(
        intent_id=_id(n),
        fingerprint=f"{n:064x}",
        created_ns=T + n,
        state=SubmitIntentState.OPEN,
        retired_ns=None,
        retirement_reason=None,
        slug=slug,
    )


def _env(store_path: Path) -> dict[str, str]:
    return {EXEC_STATE_DB_ENV_VAR: str(store_path), OPERATOR_ACK_ENV_VAR: "1"}


def _evidence(tmp_path: Path) -> Path:
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps({"positions": {}, "fill_record": None}), encoding="utf-8")
    return path


class Run:
    def __init__(self, code: int, out: str, err: str) -> None:
        self.code = code
        self.out = out
        self.err = err


def _run(store_path: Path, argv: list[str], *, clock_ns: Callable[[], int] | None = None) -> Run:
    out, err = io.StringIO(), io.StringIO()
    code = main(argv, env=_env(store_path), stdout=out, stderr=err, clock_ns=clock_ns)
    return Run(code, out.getvalue(), err.getvalue())


def _seed(tmp_path: Path, raw: bytes) -> tuple[Path, bytes]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    store_path = tmp_path / "state.db"
    with SqliteStateStore(store_path) as store:
        store.set(CURRENT_INTENT_KEY, raw)
    return store_path, raw


def _table(store_path: Path) -> bytes | None:
    with SqliteStateStore(store_path) as store:
        return store.get(CURRENT_INTENT_KEY)


def _v2(slots: list[SubmitIntent], raw: dict[str, bytes] | None = None) -> bytes:
    return encode_v2({s.intent_id: s.to_payload() for s in slots}, raw or {}, {})


def _unreadable_only() -> bytes:
    return encode_v2({}, {UNREADABLE_KEY: b'{"junk":1}'}, {})


def _mixed() -> bytes:
    return _v2([_open(1), _open(2, "slug-b")], {UNREADABLE_KEY: b'{"junk":1}'})


def _slot_args(
    store_path: Path, key: str = UNREADABLE_KEY, *, ack: bool = True, evidence: bool = True
) -> list[str]:
    args = ["--yes", "--slot-key", key]
    if ack:
        args.append("--ack-unreadable-slot")
    if evidence:
        args += ["--resolution", "no-order-exists", "--evidence", str(_evidence(store_path.parent))]
    return args


def _evidence_files(store_path: Path) -> list[Path]:
    return sorted(store_path.parent.glob(f"{store_path.name}.unreadable_slot.*.bin"))


def test_clear_cli_never_raises_uncaught_on_v2(tmp_path: Path) -> None:
    store_path, raw = _seed(tmp_path, _mixed())
    ev = str(_evidence(tmp_path))
    plain = _run(store_path, ["--yes", "--resolution", "no-order-exists", "--evidence", ev])
    assert plain.code == EXIT_REFUSED  # a v2 table needs an explicit --intent-id
    assert "--intent-id" in plain.err
    assert _table(store_path) == raw

    corrupt, _ = _seed(tmp_path / "x", b'{"v":2,"slots":"x"}')
    result = _run(corrupt, ["--yes", "--resolution", "no-order-exists", "--evidence", ev])
    assert result.code == EXIT_REFUSED
    assert "corrupt" in result.err
    listed = _run(corrupt, ["--list"])
    assert listed.code == EXIT_REFUSED

    unreadable_only, _ = _seed(tmp_path / "y", _unreadable_only())
    only = _run(unreadable_only, ["--yes", "--resolution", "no-order-exists", "--evidence", ev])
    assert only.code == EXIT_REFUSED
    assert "--slot-key" in only.err


def test_clear_cli_lists_slots_and_clears_by_intent_id(tmp_path: Path) -> None:
    store_path, _ = _seed(tmp_path, _mixed())
    listed = _run(store_path, ["--list"])
    assert listed.code == EXIT_OK
    assert f"slot intent_id={_id(1)}" in listed.out
    assert f"slot intent_id={_id(2)}" in listed.out
    assert "slug=slug-b" in listed.out
    assert f"unreadable key={UNREADABLE_KEY}" in listed.out

    ev = str(_evidence(tmp_path))
    cleared = _run(
        store_path,
        ["--yes", "--resolution", "no-order-exists", "--evidence", ev, "--intent-id", _id(2)],
    )
    assert cleared.code == EXIT_OK
    assert f"intent_id={_id(2)}" in cleared.out
    after = _run(store_path, ["--list"])
    assert f"slot intent_id={_id(1)}" in after.out
    assert f"slot intent_id={_id(2)}" not in after.out
    assert f"unreadable key={UNREADABLE_KEY}" in after.out  # untouched

    wrong = _run(
        store_path,
        ["--yes", "--resolution", "no-order-exists", "--evidence", ev, "--intent-id", _id(9)],
    )
    assert wrong.code == EXIT_REFUSED


def test_clear_cli_rejects_slot_key_with_path_characters(tmp_path: Path) -> None:
    store_path, raw = _seed(tmp_path, _unreadable_only())
    for bad in ("../evil", "a/b", "..", "", "x" * 129, "?:zz", "a b", "a\nb"):
        result = _run(store_path, _slot_args(store_path, bad))
        assert result.code == EXIT_REFUSED, bad
    assert _table(store_path) == raw
    assert _evidence_files(store_path) == []


def test_clear_cli_unreadable_slot_requires_key_ack_and_dumps_original_bytes_0600_fsynced_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store_path, raw = _seed(tmp_path, _mixed())
    assert _run(store_path, _slot_args(store_path, ack=False)).code == EXIT_REFUSED  # no ack
    assert _run(store_path, ["--yes", "--ack-unreadable-slot"]).code == EXIT_REFUSED  # no key
    assert _table(store_path) == raw

    synced: list[tuple[str, bool]] = []
    real_fsync = os.fsync

    def spy_fsync(fd: int) -> None:
        target = os.readlink(f"/proc/self/fd/{fd}")
        synced.append((target, Path(target).is_dir()))
        real_fsync(fd)

    seen_at_removal: list[bytes | None] = []
    real_discard = SubmitIntentLatch.discard_unreadable_slot

    def watched_discard(self: SubmitIntentLatch, key: str, *, now_ns: int, **kwargs: str) -> None:
        files = _evidence_files(store_path)
        seen_at_removal.append(files[0].read_bytes() if files else None)
        real_discard(self, key, now_ns=now_ns, **kwargs)

    monkeypatch.setattr(os, "fsync", spy_fsync)
    monkeypatch.setattr(SubmitIntentLatch, "discard_unreadable_slot", watched_discard)
    result = _run(store_path, _slot_args(store_path), clock_ns=lambda: FIXED_TS)
    monkeypatch.undo()

    assert result.code == EXIT_OK, result.err
    files = _evidence_files(store_path)
    assert len(files) == 1
    dumped = files[0].read_bytes()
    header, _, body = dumped.partition(b"\n")
    assert body == raw  # the ORIGINAL bytes, not re-serialised
    parsed = json.loads(header.split(b" ", 2)[2])
    assert parsed["key"] == UNREADABLE_KEY
    assert "canonicalised" in parsed["slot_canonicalised_json_label"]
    resolution_file = (store_path.parent / "evidence.json").read_bytes()
    assert parsed["resolution_evidence_sha256"] == hashlib.sha256(resolution_file).hexdigest()
    assert parsed["resolution"] == "no-order-exists"
    assert stat.S_IMODE(files[0].stat().st_mode) == 0o600
    assert seen_at_removal == [dumped]  # the dump existed, complete, before the removal
    assert (str(files[0]), False) in synced
    assert (str(store_path.parent), True) in synced
    # the unreadable slot is gone, the readable slots are untouched
    listing = _run(store_path, ["--list"]).out
    assert "unreadable=0" in listing and "unreadable key=" not in listing
    assert f"slot intent_id={_id(1)}" in listing and f"slot intent_id={_id(2)}" in listing


def test_clear_cli_evidence_filename_uses_key_hash_not_key(tmp_path: Path) -> None:
    store_path, _ = _seed(tmp_path, _unreadable_only())
    result = _run(store_path, _slot_args(store_path), clock_ns=lambda: FIXED_TS)
    assert result.code == EXIT_OK, result.err
    digest = hashlib.sha256(UNREADABLE_KEY.encode()).hexdigest()[:16]
    files = _evidence_files(store_path)
    assert [f.name for f in files] == [f"state.db.unreadable_slot.{digest}.{FIXED_TS}.bin"]
    assert UNREADABLE_KEY not in files[0].name
    # the lone unreadable slot is gone and the table is a valid v1 RETIRED record
    raw = _table(store_path)
    assert raw is not None
    assert SubmitIntent.from_bytes(raw).state is SubmitIntentState.RETIRED


def test_clear_cli_aborts_if_evidence_dump_fails(tmp_path: Path) -> None:
    store_path, raw = _seed(tmp_path, _mixed())
    digest = hashlib.sha256(UNREADABLE_KEY.encode()).hexdigest()[:16]
    blocker = store_path.parent / f"state.db.unreadable_slot.{digest}.{FIXED_TS}.bin"
    blocker.write_bytes(b"pre-existing")  # O_EXCL creation must fail
    result = _run(store_path, _slot_args(store_path), clock_ns=lambda: FIXED_TS)
    assert result.code == EXIT_REFUSED
    assert "evidence" in result.err
    assert _table(store_path) == raw  # the slot was NOT removed
    assert blocker.read_bytes() == b"pre-existing"


def test_clear_cli_refuses_erasing_table_over_open_slots(tmp_path: Path) -> None:
    store_path, raw = _seed(tmp_path, _mixed())
    # naming a READABLE open slot (or an absent key) must never erase it
    for key in (_id(1), "nope"):
        result = _run(store_path, _slot_args(store_path, key), clock_ns=lambda: FIXED_TS)
        assert result.code == EXIT_REFUSED, key
    assert _table(store_path) == raw
    assert _evidence_files(store_path) == []
    # a v1 OPEN record is likewise not an unreadable slot
    v1_path, v1_raw = _seed(tmp_path / "v1", _open(7).to_bytes())
    assert _run(v1_path, _slot_args(v1_path, _id(7))).code == EXIT_REFUSED
    assert _table(v1_path) == v1_raw


def test_clear_cli_reset_entry_halt_requires_node_down_and_ack_held_positions(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "state.db"
    halted = encode_breaker(BreakerRecord("stuck_slots", T, hb_ns=11, resolver_pass_ns=22))
    with SqliteStateStore(store_path) as store:
        store.set(BREAKER_KEY, halted)
    base = ["--yes", "--reset-entry-halt"]

    assert _run(store_path, base).code == EXIT_REFUSED  # no --ack-held-positions-reviewed
    ack = [*base, "--ack-held-positions-reviewed"]
    store = SqliteStateStore(store_path)
    with open_submit_intent_latch(store, store_path):  # the node holds the flock
        held = _run(store_path, ack)
    store.close()
    assert held.code == EXIT_REFUSED
    assert "holds the lock" in held.err
    with SqliteStateStore(store_path) as check:
        assert check.get(BREAKER_KEY) == halted  # untouched

    done = _run(store_path, ack)
    assert done.code == EXIT_OK, done.err
    with SqliteStateStore(store_path) as check:
        record = json.loads(check.get(BREAKER_KEY) or b"{}")
    assert record["halted"] is None
    assert (record["hb_ns"], record["resolver_pass_ns"]) == (11, 22)
    assert _run(store_path, ack).code == EXIT_NOTHING_OPEN  # nothing left to reset


def test_module_exposes_the_slot_key_validator() -> None:
    assert cli.is_valid_slot_key("a.b_c-1")
    assert cli.is_valid_slot_key("?:" + "0" * 32)
    assert not cli.is_valid_slot_key("a/b")


def test_clear_cli_slot_key_requires_resolution_evidence_no_dump_when_absent(
    tmp_path: Path,
) -> None:
    store_path, raw = _seed(tmp_path, _mixed())
    missing = _run(store_path, _slot_args(store_path, evidence=False), clock_ns=lambda: FIXED_TS)
    assert missing.code == EXIT_REFUSED
    assert "evidence" in missing.err
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"open_orders": []}), encoding="utf-8")
    insufficient = _run(
        store_path,
        [
            *_slot_args(store_path, evidence=False),
            "--resolution",
            "no-order-exists",
            "--evidence",
            str(bad),
        ],
        clock_ns=lambda: FIXED_TS,
    )
    assert insufficient.code == EXIT_REFUSED
    assert _table(store_path) == raw
    assert _evidence_files(store_path) == []


def test_discard_unreadable_slot_writes_history_with_dump_reference(tmp_path: Path) -> None:
    store_path, _ = _seed(tmp_path, _unreadable_only())
    result = _run(store_path, _slot_args(store_path), clock_ns=lambda: FIXED_TS)
    assert result.code == EXIT_OK, result.err
    dump = _evidence_files(store_path)[0]
    dump_sha = hashlib.sha256(dump.read_bytes()).hexdigest()
    slot_id = hashlib.sha256(UNREADABLE_KEY.encode()).hexdigest()[:32]
    with SqliteStateStore(store_path) as store:
        history = store.get(history_key(slot_id))
        current = store.get(CURRENT_INTENT_KEY)
    assert history is not None and current is not None
    record = SubmitIntent.from_bytes(history)  # history readers decode it
    assert record.state is SubmitIntentState.RETIRED
    assert record.fingerprint == dump_sha
    extra = json.loads(history)
    assert extra["evidence_path"] == str(dump)
    assert extra["evidence_sha256"] == dump_sha
    assert extra["unreadable_slot_key"] == UNREADABLE_KEY
    # the synthetic v1 RETIRED record references the same dump hash
    assert SubmitIntent.from_bytes(current).fingerprint == dump_sha


def test_clear_cli_slot_key_and_reset_paths_exit_2_on_store_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store_path, raw = _seed(tmp_path, _mixed())

    def mismatch(self: SubmitIntentLatch, key: str, **kwargs: str | int) -> None:
        raise SubmitIntentMismatch(key, None, None)

    monkeypatch.setattr(SubmitIntentLatch, "discard_unreadable_slot", mismatch)
    raced = _run(store_path, _slot_args(store_path), clock_ns=lambda: FIXED_TS)
    assert raced.code == EXIT_REFUSED and "refused" in raced.err

    def sqlite_boom(self: SubmitIntentLatch) -> bool:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(SubmitIntentLatch, "reset_breaker_halt", sqlite_boom)
    locked = _run(store_path, ["--yes", "--reset-entry-halt", "--ack-held-positions-reviewed"])
    assert locked.code == EXIT_REFUSED and "database is locked" in locked.err

    def os_boom(self: SubmitIntentLatch) -> bool:
        raise OSError(errno.EIO, "Input/output error", "/x/state.db")

    monkeypatch.setattr(SubmitIntentLatch, "reset_breaker_halt", os_boom)
    io_err = _run(store_path, ["--yes", "--reset-entry-halt", "--ack-held-positions-reviewed"])
    assert io_err.code == EXIT_REFUSED
    assert "EIO" in io_err.err and "/x/state.db" in io_err.err
    assert _table(store_path) == raw


def test_clear_cli_reset_rejects_stray_resolution_and_list_help_names_the_lock(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "state.db"
    ev = str(_evidence(tmp_path))
    stray = _run(
        store_path,
        ["--yes", "--reset-entry-halt", "--ack-held-positions-reviewed", "--resolution", "x"],
    )
    assert stray.code == EXIT_REFUSED
    stray_ev = _run(
        store_path,
        ["--yes", "--reset-entry-halt", "--ack-held-positions-reviewed", "--evidence", ev],
    )
    assert stray_ev.code == EXIT_REFUSED
    assert "refuses while the node is up" in cli._build_parser().format_help().replace("\n", " ")
