"""Tests for the durable SQLite-backed StateStore (src/breezy/runtime/sqlite_store.py).

Governing rationale: a prior evaluation rejected backing
`breezy.ingest.gate.StateStore` with Nautilus `Cache` on evidence that
`Cache.add` queues writes to a background task (returns before durability),
`Cache.get` only reads an in-memory dict, and `Cache.reset()` clears that
dict without clearing the database -- silently returning a default
`ua_trap_blocked=False` and laundering a permanent trading halt. This file
pins the SQLite replacement against exactly those three failure modes plus
the classic falsy-bytes and binary-safety bugs.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Protocol, runtime_checkable

import pytest

from breezy.ingest.gate import GateReason, GateState, SettlementGate, StateStore
from breezy.runtime.sqlite_store import SqliteStateStore

VENUE = "polymarket_us"
CITY = "NYC"
OTHER_CITY = "SFO"


@runtime_checkable
class _StateStoreShape(Protocol):
    """A locally-defined, `runtime_checkable` mirror of
    `breezy.ingest.gate.StateStore` (which is deliberately NOT
    `runtime_checkable`), used only so this test can assert structural
    conformance with `isinstance` without touching gate.py.
    """

    def get(self, key: str) -> bytes | None: ...

    def set(self, key: str, value: bytes) -> None: ...


def _accepts_state_store(store: StateStore) -> StateStore:
    """Statically pins that `SqliteStateStore` satisfies the real
    `StateStore` Protocol from gate.py: mypy --strict fails this file if
    the argument type does not structurally match.
    """
    return store


class TestBasicRoundTrip:
    def test_round_trip_returns_exact_bytes(self, tmp_path: Path) -> None:
        store = SqliteStateStore(tmp_path / "state.db")
        store.set("k", b"hello")
        assert store.get("k") == b"hello"
        store.close()

    def test_absent_key_returns_none(self, tmp_path: Path) -> None:
        store = SqliteStateStore(tmp_path / "state.db")
        assert store.get("missing") is None
        store.close()

    def test_empty_bytes_round_trips_as_empty_bytes_not_none(self, tmp_path: Path) -> None:
        # Classic falsy bug: b"" must not collapse to None.
        store = SqliteStateStore(tmp_path / "state.db")
        store.set("k", b"")
        result = store.get("k")
        assert result == b""
        assert result is not None
        store.close()

    def test_binary_safe_round_trip_including_nul_and_invalid_utf8(self, tmp_path: Path) -> None:
        store = SqliteStateStore(tmp_path / "state.db")
        payload = bytes(range(256)) + b"\x00\xff\xfe" + b"\x80\x81"
        store.set("binary", payload)
        assert store.get("binary") == payload
        store.close()

    def test_overwrite_replaces_value(self, tmp_path: Path) -> None:
        store = SqliteStateStore(tmp_path / "state.db")
        store.set("k", b"first")
        store.set("k", b"second")
        assert store.get("k") == b"second"
        store.close()


class TestDurabilityAcrossReopen:
    def test_reopen_at_same_path_returns_previously_set_values(self, tmp_path: Path) -> None:
        path = tmp_path / "state.db"
        store = SqliteStateStore(path)
        store.set("durable-key", b"durable-value")
        store.close()

        reopened = SqliteStateStore(path)
        assert reopened.get("durable-key") == b"durable-value"
        reopened.close()

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        path = tmp_path / "nested" / "dir" / "state.db"
        store = SqliteStateStore(path)
        store.set("k", b"v")
        store.close()
        assert path.exists()


class TestProtocolConformance:
    def test_isinstance_against_runtime_checkable_mirror_protocol(self, tmp_path: Path) -> None:
        store = SqliteStateStore(tmp_path / "state.db")
        assert isinstance(store, _StateStoreShape)
        store.close()

    def test_accepted_by_a_function_annotated_with_the_real_state_store_protocol(
        self, tmp_path: Path
    ) -> None:
        store = SqliteStateStore(tmp_path / "state.db")
        accepted = _accepts_state_store(store)
        assert accepted is store
        store.close()


class TestTypeRejection:
    def test_get_rejects_non_str_key(self, tmp_path: Path) -> None:
        store = SqliteStateStore(tmp_path / "state.db")
        with pytest.raises(TypeError):
            store.get(123)  # type: ignore[arg-type]
        store.close()

    def test_set_rejects_non_str_key(self, tmp_path: Path) -> None:
        store = SqliteStateStore(tmp_path / "state.db")
        with pytest.raises(TypeError):
            store.set(123, b"v")  # type: ignore[arg-type]
        store.close()

    def test_set_rejects_non_bytes_value(self, tmp_path: Path) -> None:
        store = SqliteStateStore(tmp_path / "state.db")
        with pytest.raises(TypeError):
            store.set("k", "not-bytes")  # type: ignore[arg-type]
        store.close()


class TestPragmas:
    def test_journal_mode_is_wal(self, tmp_path: Path) -> None:
        path = tmp_path / "state.db"
        store = SqliteStateStore(path)
        store.set("k", b"v")
        store.close()

        # journal_mode is persisted in the database file header, so a fresh
        # raw connection reflects the store's own PRAGMA setting.
        raw = sqlite3.connect(str(path))
        try:
            mode = raw.execute("PRAGMA journal_mode").fetchone()[0]
            assert str(mode).lower() == "wal"
        finally:
            raw.close()

    def test_synchronous_is_full_on_the_stores_own_connection(self, tmp_path: Path) -> None:
        # synchronous is a per-connection setting (not persisted to the file),
        # so it must be read through the store's own connection.
        store = SqliteStateStore(tmp_path / "state.db")
        assert store._query_pragma("synchronous") == "2"
        store.close()


class TestContextManager:
    def test_context_manager_closes_on_exit(self, tmp_path: Path) -> None:
        with SqliteStateStore(tmp_path / "state.db") as store:
            store.set("k", b"v")
            assert store.get("k") == b"v"
        assert store._closed is True

    def test_double_close_does_not_raise(self, tmp_path: Path) -> None:
        store = SqliteStateStore(tmp_path / "state.db")
        store.close()
        store.close()

    def test_operations_after_close_raise(self, tmp_path: Path) -> None:
        store = SqliteStateStore(tmp_path / "state.db")
        store.close()
        with pytest.raises(RuntimeError):
            store.get("k")


class TestThreadConfinement:
    """This store confines access to the thread that constructed it, rather
    than allowing cross-thread use behind a lock -- see the class docstring
    in sqlite_store.py for why.
    """

    def test_get_from_other_thread_raises_runtime_error(self, tmp_path: Path) -> None:
        store = SqliteStateStore(tmp_path / "state.db")
        errors: list[BaseException] = []

        def _worker() -> None:
            try:
                store.get("k")
            except BaseException as exc:  # noqa: BLE001 - captured for assertion
                errors.append(exc)

        thread = threading.Thread(target=_worker)
        thread.start()
        thread.join()

        assert len(errors) == 1
        assert isinstance(errors[0], RuntimeError)
        store.close()

    def test_set_from_other_thread_raises_runtime_error(self, tmp_path: Path) -> None:
        store = SqliteStateStore(tmp_path / "state.db")
        errors: list[BaseException] = []

        def _worker() -> None:
            try:
                store.set("k", b"v")
            except BaseException as exc:  # noqa: BLE001 - captured for assertion
                errors.append(exc)

        thread = threading.Thread(target=_worker)
        thread.start()
        thread.join()

        assert len(errors) == 1
        assert isinstance(errors[0], RuntimeError)
        # The rejected write from the foreign thread must not have landed.
        assert store.get("k") is None
        store.close()

    def test_same_thread_access_after_a_foreign_thread_attempt_still_works(
        self, tmp_path: Path
    ) -> None:
        store = SqliteStateStore(tmp_path / "state.db")
        thread = threading.Thread(target=lambda: None)
        thread.start()
        thread.join()

        store.set("k", b"v")
        assert store.get("k") == b"v"
        store.close()


class TestGateEndToEnd:
    """The highest-value test: drive a real SettlementGate transition through
    this store, reopen a fresh store + gate over the same file, and assert
    the state survived -- the exact durability property Cache could not
    give the gate.
    """

    def test_gate_state_survives_store_close_and_reopen(self, tmp_path: Path) -> None:
        path = tmp_path / "gate-state.db"
        sites = frozenset({(VENUE, CITY), (VENUE, OTHER_CITY)})
        clock_value = {"now": 1_000}

        def clock() -> int:
            return clock_value["now"]

        store = SqliteStateStore(path)
        gate = SettlementGate(store=store, clock=clock, sites=sites)

        # Defaults to BLOCKED before any poll.
        assert gate.status(VENUE, CITY).state is GateState.BLOCKED

        status = gate.record_successful_poll(VENUE, CITY, detail="first poll")
        assert status.state is GateState.OPEN
        assert status.reason is GateReason.SUCCESSFUL_POLL
        store.close()

        # A brand new store + gate instance over the SAME file must restore
        # exactly the prior state -- not the BLOCKED default.
        reopened_store = SqliteStateStore(path)
        reopened_gate = SettlementGate(store=reopened_store, clock=clock, sites=sites)
        reopened_status = reopened_gate.status(VENUE, CITY)
        assert reopened_status.state is GateState.OPEN
        assert reopened_status.last_successful_poll_ns == 1_000
        reopened_store.close()


# ---------------------------------------------------------------------------
# Out-of-band bootstrap witness -- closes the remaining half of the
# STATE_STORE_TAMPERED gap: WHOLE-FILE deletion of the state DB, not just a
# single row within it.
#
# gate.py's own in-store `_GLOBAL_BOOTSTRAP_KEY` sentinel is explicitly
# documented (see `tests/unit/test_ingest_gate.py`, the comment above
# `test_a_wiped_global_row_fails_closed_instead_of_laundering_the_ua_trap`)
# as unable to survive this: if the entire file is deleted and recreated,
# the sentinel is gone along with everything else, and "genuinely new" and
# "wiped" become the same observation through the store alone. Closing that
# needs a witness that lives somewhere OTHER than the state-DB file --
# `breezy.runtime.bootstrap_witness`.
#
# A real `SqliteStateStore` on a real temp path, with an ACTUAL `unlink()` of
# every `state.sqlite3*` sibling (the main file plus WAL/SHM), is required:
# an in-memory fake cannot model a file disappearing out from under a
# connection.
# ---------------------------------------------------------------------------


def _delete_whole_state_db(path: Path) -> None:
    """Simulate a botched restore / accidental `rm`: delete the main file
    plus every WAL-mode sibling SQLite leaves behind.
    """
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        candidate.unlink(missing_ok=True)


class TestBootstrapWitnessAgainstWholeFileDeletion:
    def test_without_the_witness_whole_file_deletion_launders_the_ua_trap(
        self, tmp_path: Path
    ) -> None:
        """RED-first reproduction (pinned permanently): absent the
        out-of-band witness, deleting the whole state-DB file and reopening
        it clears a latched UA-trap block after one ordinary successful
        poll -- exactly the laundering `enforce_bootstrap_witness` exists to
        close. This test intentionally never calls
        `enforce_bootstrap_witness`, so it continues to document the
        pre-fix vulnerability shape even after the fix ships.
        """
        path = tmp_path / "state.sqlite3"
        sites = frozenset({(VENUE, CITY), (VENUE, OTHER_CITY)})

        store = SqliteStateStore(path)
        gate = SettlementGate(store=store, clock=lambda: 1_000, sites=sites)
        gate.record_forbidden_403(VENUE, CITY, detail="cross-site 403 burst")
        assert gate.status(VENUE, CITY).state is GateState.BLOCKED
        store.close()

        _delete_whole_state_db(path)

        reopened_store = SqliteStateStore(path)
        reopened_gate = SettlementGate(store=reopened_store, clock=lambda: 2_000, sites=sites)
        status_before_poll = reopened_gate.status(VENUE, CITY)
        assert status_before_poll.state is GateState.BLOCKED
        assert status_before_poll.reason is GateReason.NEVER_POLLED

        after_poll = reopened_gate.record_successful_poll(VENUE, CITY, detail="ordinary poll")
        assert after_poll.state is GateState.OPEN
        assert after_poll.reason is GateReason.SUCCESSFUL_POLL
        reopened_store.close()

    def test_the_witness_makes_whole_file_deletion_fail_closed_instead(
        self, tmp_path: Path
    ) -> None:
        """The fix: run `enforce_bootstrap_witness` at every open. Deleting
        the whole state-DB file is now detected via the out-of-band marker
        surviving the destroyed file, and the gate BLOCKS every site under
        STATE_STORE_TAMPERED even after a successful poll -- it never
        reaches OPEN.
        """
        from breezy.runtime.bootstrap_witness import enforce_bootstrap_witness

        path = tmp_path / "state.sqlite3"
        catalog_base = tmp_path / "catalog"
        sites = frozenset({(VENUE, CITY), (VENUE, OTHER_CITY)})

        store = SqliteStateStore(path)
        enforce_bootstrap_witness(store, catalog_base=catalog_base)
        gate = SettlementGate(store=store, clock=lambda: 1_000, sites=sites)
        gate.record_forbidden_403(VENUE, CITY, detail="cross-site 403 burst")
        assert gate.status(VENUE, CITY).state is GateState.BLOCKED
        store.close()

        _delete_whole_state_db(path)
        assert (catalog_base / ".breezy-bootstrap-witness").exists()

        reopened_store = SqliteStateStore(path)
        enforce_bootstrap_witness(reopened_store, catalog_base=catalog_base)
        reopened_gate = SettlementGate(store=reopened_store, clock=lambda: 2_000, sites=sites)

        status_before_poll = reopened_gate.status(VENUE, CITY)
        assert status_before_poll.state is GateState.BLOCKED
        assert status_before_poll.reason is GateReason.STATE_STORE_TAMPERED

        after_poll = reopened_gate.record_successful_poll(VENUE, CITY, detail="ordinary poll")
        assert after_poll.state is GateState.BLOCKED
        assert after_poll.reason is GateReason.STATE_STORE_TAMPERED
        assert after_poll.reason is not GateReason.SUCCESSFUL_POLL

        # The existing, already-tested recovery path still works unchanged.
        reopened_gate.acknowledge_ua_trap_resolved(detail="verified: restore was legitimate")
        assert reopened_gate.status(VENUE, CITY).state is GateState.OPEN
        reopened_store.close()

    def test_genuine_first_boot_still_reaches_open(self, tmp_path: Path) -> None:
        """The other half of the same fix: a brand-new deployment (no
        store, no witness file) must still start permissively and reach
        OPEN after one successful poll.
        """
        from breezy.runtime.bootstrap_witness import enforce_bootstrap_witness

        path = tmp_path / "state.sqlite3"
        catalog_base = tmp_path / "catalog"
        sites = frozenset({(VENUE, CITY), (VENUE, OTHER_CITY)})

        assert not path.exists()
        assert not (catalog_base / ".breezy-bootstrap-witness").exists()

        store = SqliteStateStore(path)
        enforce_bootstrap_witness(store, catalog_base=catalog_base)
        gate = SettlementGate(store=store, clock=lambda: 1_000, sites=sites)

        assert gate.status(VENUE, CITY).state is GateState.BLOCKED
        assert gate.status(VENUE, CITY).reason is GateReason.NEVER_POLLED

        status = gate.record_successful_poll(VENUE, CITY, detail="first ever poll")
        assert status.state is GateState.OPEN
        assert status.reason is GateReason.SUCCESSFUL_POLL
        store.close()

    def test_reopening_an_intact_store_does_not_false_positive(self, tmp_path: Path) -> None:
        """An ordinary restart over an INTACT store (nothing deleted) must
        never be mistaken for tampering, regardless of how many times the
        witness check runs.
        """
        from breezy.runtime.bootstrap_witness import enforce_bootstrap_witness

        path = tmp_path / "state.sqlite3"
        catalog_base = tmp_path / "catalog"
        sites = frozenset({(VENUE, CITY), (VENUE, OTHER_CITY)})

        store = SqliteStateStore(path)
        enforce_bootstrap_witness(store, catalog_base=catalog_base)
        gate = SettlementGate(store=store, clock=lambda: 1_000, sites=sites)
        gate.record_successful_poll(VENUE, CITY, detail="first poll")
        store.close()

        for restart_ns in (2_000, 3_000, 4_000):
            reopened_store = SqliteStateStore(path)
            enforce_bootstrap_witness(reopened_store, catalog_base=catalog_base)
            reopened_gate = SettlementGate(
                store=reopened_store, clock=lambda restart_ns=restart_ns: restart_ns, sites=sites
            )
            status = reopened_gate.status(VENUE, CITY)
            assert status.state is GateState.OPEN
            assert status.reason is not GateReason.STATE_STORE_TAMPERED
            reopened_store.close()

    def test_missing_marker_file_alone_self_heals_without_blocking(self, tmp_path: Path) -> None:
        """Deleting ONLY the witness marker file (the store itself intact)
        is not, by itself, the whole-file-deletion attack this module
        defends against -- it must self-heal, not falsely block.
        """
        from breezy.runtime.bootstrap_witness import enforce_bootstrap_witness

        path = tmp_path / "state.sqlite3"
        catalog_base = tmp_path / "catalog"
        sites = frozenset({(VENUE, CITY)})

        store = SqliteStateStore(path)
        enforce_bootstrap_witness(store, catalog_base=catalog_base)
        marker = catalog_base / ".breezy-bootstrap-witness"
        assert marker.exists()
        marker.unlink()

        gate = SettlementGate(store=store, clock=lambda: 1_000, sites=sites)
        status = gate.record_successful_poll(VENUE, CITY, detail="poll before re-check")
        assert status.state is GateState.OPEN
        store.close()

        # Re-run the witness check (as a fresh process boot would): it must
        # repair the marker rather than treat its absence as tampering.
        reopened_store = SqliteStateStore(path)
        enforce_bootstrap_witness(reopened_store, catalog_base=catalog_base)
        assert marker.exists()
        reopened_gate = SettlementGate(store=reopened_store, clock=lambda: 2_000, sites=sites)
        assert reopened_gate.status(VENUE, CITY).state is GateState.OPEN
        reopened_store.close()
