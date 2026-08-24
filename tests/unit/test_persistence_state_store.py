"""Unit tests for `breezy.persistence.state_store` -- the durable `StateStore`
backing the settlement gate's `ua_trap_blocked` latch and every other
cross-restart trading-safety fact.

Scope: round-trip durability, the `flock`+`fsync` discipline surviving a hard
process kill, per-value CRC32 corruption detection and isolation, concurrent
access (multi-process and multi-thread), path-safety refusal, and the
`assert_state_store_durable` gate. Nothing here touches the network.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from breezy.ingest.gate import InMemoryStateStore
from breezy.persistence.catalog import WriterLockFilesystemError
from breezy.persistence.state_store import (
    ConcurrentStateStoreError,
    FileStateStore,
    StateStoreCorruptError,
    StateStoreError,
    StateStoreLockError,
    StateStorePathError,
    assert_state_store_durable,
)

# ---------------------------------------------------------------------------
# 1. round trip through a fresh instance
# ---------------------------------------------------------------------------


def test_set_then_get_round_trips_through_a_fresh_instance(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    first = FileStateStore(path)
    try:
        first.set("gate:global", b"\x01\x02\x03")
    finally:
        first.close()

    second = FileStateStore(path)
    try:
        assert second.get("gate:global") == b"\x01\x02\x03"
    finally:
        second.close()


def test_get_returns_none_for_an_unknown_key(tmp_path: Path) -> None:
    store = FileStateStore(tmp_path / "state.json")
    try:
        assert store.get("nope") is None
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 2. the fsync proof
# ---------------------------------------------------------------------------

_SET_AND_HARD_EXIT_SCRIPT = """
import os
from pathlib import Path
from breezy.persistence.state_store import FileStateStore

store = FileStateStore(Path({path!r}))
store.set({key!r}, {value!r})
os._exit(0)
"""


def test_set_survives_a_hard_kill_of_the_writing_process(tmp_path: Path) -> None:
    """`set()` must complete its whole durability sequence -- flush, fsync,
    replace, directory fsync -- and return only once that sequence is done.
    Nothing may be deferred to `close()` or a background thread: the writer
    is killed with `os._exit` (skips atexit and Python-buffer flushing)
    immediately after `set()` returns, and the value must still be there.
    """
    path = tmp_path / "state.json"
    script = _SET_AND_HARD_EXIT_SCRIPT.format(path=str(path), key="gate:global", value=b"durable")
    script_path = tmp_path / "_writer.py"
    script_path.write_text(script)

    result = subprocess.run([sys.executable, str(script_path)], timeout=10, check=False)
    assert result.returncode == 0

    store = FileStateStore(path)
    try:
        assert store.get("gate:global") == b"durable"
    finally:
        store.close()


def test_set_calls_os_fsync_on_the_value_file_and_the_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The determinstic half of the fsync proof: this test fails immediately
    if the `os.fsync` call is ever removed from the durability sequence,
    independent of any OS page-cache behaviour a process-kill test cannot
    observe directly.
    """
    path = tmp_path / "state.json"
    store = FileStateStore(path)
    fsync_calls: list[int] = []
    real_fsync = os.fsync

    def spy_fsync(fd: int) -> None:
        fsync_calls.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", spy_fsync)
    try:
        store.set("k", b"v")
    finally:
        store.close()

    # At least two fsync calls: the temp value file, and the directory fd.
    assert len(fsync_calls) >= 2


def test_set_with_fsync_disabled_skips_fsync_but_still_replaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "state.json"
    store = FileStateStore(path, fsync=False)
    calls: list[int] = []
    monkeypatch.setattr(os, "fsync", lambda fd: calls.append(fd))
    try:
        store.set("k", b"v")
        assert calls == []
        assert store.get("k") == b"v"
    finally:
        store.close()
    assert path.exists()


# ---------------------------------------------------------------------------
# 3 & 4. per-value CRC32 corruption, and isolation between keys
# ---------------------------------------------------------------------------


def _flip_one_byte_of_value(path: Path, key: str) -> None:
    """Corrupt exactly one key's stored payload while keeping the JSON
    container itself well-formed, so any effect on OTHER keys is
    attributable only to the store's own (mis)handling, never to a broken
    JSON parse.
    """
    parsed = json.loads(path.read_text())
    original_b64: str = parsed[key]["data"]
    raw = bytearray(base64.b64decode(original_b64))
    raw[0] ^= 0xFF
    parsed[key]["data"] = base64.b64encode(bytes(raw)).decode("ascii")
    path.write_text(json.dumps(parsed))


def test_a_flipped_byte_in_a_stored_value_raises_corrupt_error(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    store = FileStateStore(path)
    store.set("gate:global", b"trustworthy")
    store.close()

    _flip_one_byte_of_value(path, "gate:global")

    reopened = FileStateStore(path)
    try:
        with pytest.raises(StateStoreCorruptError):
            reopened.get("gate:global")
    finally:
        reopened.close()


def test_corruption_never_decodes_to_a_successful_wrong_value(tmp_path: Path) -> None:
    """The failure mode this project cannot tolerate: `get()` returning
    corrupted bytes as though they were the value that was actually written.
    """
    path = tmp_path / "state.json"
    store = FileStateStore(path)
    original = b"the-real-value"
    store.set("gate:global", original)
    store.close()

    _flip_one_byte_of_value(path, "gate:global")

    reopened = FileStateStore(path)
    try:
        try:
            result = reopened.get("gate:global")
        except StateStoreCorruptError:
            pass
        else:
            assert result != original, "corrupted bytes must never be returned as valid"
            pytest.fail("expected StateStoreCorruptError, got a value instead")
    finally:
        reopened.close()


def test_corruption_of_one_key_leaves_other_keys_readable(tmp_path: Path) -> None:
    """The whole reason for per-VALUE CRC32 rather than one whole-file
    checksum: gate.py treats a corrupt site entry and a corrupt global entry
    with different blast radii, which depends on this isolation holding.
    """
    path = tmp_path / "state.json"
    store = FileStateStore(path)
    store.set("gate:site:NYC", b"site-data")
    store.set("gate:global", b"global-data")
    store.close()

    _flip_one_byte_of_value(path, "gate:site:NYC")

    reopened = FileStateStore(path)
    try:
        with pytest.raises(StateStoreCorruptError):
            reopened.get("gate:site:NYC")
        assert reopened.get("gate:global") == b"global-data"
    finally:
        reopened.close()


# ---------------------------------------------------------------------------
# 5. cross-process serialization, and SIGKILL does not wedge a new holder
# ---------------------------------------------------------------------------

_HOLD_LOCK_SCRIPT = """
import time
from pathlib import Path
from breezy.persistence.state_store import FileStateStore

store = FileStateStore(Path({path!r}))
time.sleep(30)
"""


def test_a_second_process_blocks_until_the_first_releases(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    script_path = tmp_path / "_holder.py"
    script_path.write_text(_HOLD_LOCK_SCRIPT.format(path=str(path)))

    holder = subprocess.Popen([sys.executable, str(script_path)])
    try:
        # Give the holder a real chance to have acquired the lock.
        _wait_until_lock_file_exists(path)
        time.sleep(0.3)

        opened_in_thread: list[FileStateStore] = []

        def open_second() -> None:
            store = FileStateStore(path)
            opened_in_thread.append(store)

        opener = threading.Thread(target=open_second)
        opener.start()
        opener.join(timeout=1)
        assert not opened_in_thread, "a second holder must block, not open immediately"

        holder.terminate()
        holder.wait(timeout=5)

        opener.join(timeout=10)
        assert opened_in_thread, "the second holder never unblocked after the first exited"
        opened_in_thread[0].close()
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait(timeout=5)


def test_a_sigkilled_holder_does_not_wedge_a_new_process(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    script_path = tmp_path / "_holder.py"
    script_path.write_text(_HOLD_LOCK_SCRIPT.format(path=str(path)))

    holder = subprocess.Popen([sys.executable, str(script_path)])
    try:
        _wait_until_lock_file_exists(path)
        time.sleep(0.3)

        holder.send_signal(signal.SIGKILL)
        holder.wait(timeout=5)

        store = FileStateStore(path)  # must not hang
        store.close()
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait(timeout=5)


def _wait_until_lock_file_exists(path: Path, timeout: float = 5.0) -> None:
    lock_path = path.with_name(path.name + ".lock")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if lock_path.exists():
            return
        time.sleep(0.02)
    pytest.fail(f"{lock_path} never appeared")


def test_a_second_instance_on_the_same_path_in_the_same_process_raises(tmp_path: Path) -> None:
    """The in-process hazard `flock` alone cannot cover: two blocking
    acquisitions on the same path in the same process would deadlock forever,
    since neither has an external actor left to release it for the other.
    """
    path = tmp_path / "state.json"
    first = FileStateStore(path)
    try:
        with pytest.raises(ConcurrentStateStoreError):
            FileStateStore(path)
    finally:
        first.close()

    # Once closed, the path is free again.
    second = FileStateStore(path)
    second.close()


# ---------------------------------------------------------------------------
# 6. concurrent set from many threads loses no key
# ---------------------------------------------------------------------------


def test_concurrent_set_from_eight_threads_loses_no_key(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    store = FileStateStore(path)
    try:
        keys = [f"key-{i}" for i in range(8)]

        def write(key: str) -> None:
            store.set(key, key.encode("ascii"))

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(write, keys))

        for key in keys:
            assert store.get(key) == key.encode("ascii")
    finally:
        store.close()

    reopened = FileStateStore(path)
    try:
        for i in range(8):
            key = f"key-{i}"
            assert reopened.get(key) == key.encode("ascii")
    finally:
        reopened.close()


# ---------------------------------------------------------------------------
# 7. symlinked path or lock file raises StateStorePathError
# ---------------------------------------------------------------------------


def test_a_symlinked_state_path_raises_state_store_path_error(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text("{}")
    linked = tmp_path / "state.json"
    linked.symlink_to(target)

    with pytest.raises(StateStorePathError):
        FileStateStore(linked)


def test_a_symlinked_lock_file_raises_state_store_path_error(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    lock_path = tmp_path / "state.json.lock"
    target = tmp_path / "elsewhere.lock"
    target.write_text("")
    lock_path.symlink_to(target)

    with pytest.raises(StateStorePathError):
        FileStateStore(path)


# ---------------------------------------------------------------------------
# 8. assert_state_store_durable rejects InMemoryStateStore, accepts a real one
# ---------------------------------------------------------------------------


def test_assert_state_store_durable_rejects_in_memory_store() -> None:
    with pytest.raises(StateStoreError):
        assert_state_store_durable(InMemoryStateStore())


def test_assert_state_store_durable_accepts_a_real_file_state_store(tmp_path: Path) -> None:
    store = FileStateStore(tmp_path / "state.json")
    try:
        assert_state_store_durable(store)  # must not raise
    finally:
        store.close()


def test_assert_state_store_durable_rejects_a_closed_store(tmp_path: Path) -> None:
    store = FileStateStore(tmp_path / "state.json")
    store.close()

    with pytest.raises(StateStoreLockError):
        assert_state_store_durable(store)


def test_assert_state_store_durable_rejects_an_unsupported_filesystem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from breezy.persistence import state_store as state_store_module

    store = FileStateStore(tmp_path / "state.json")
    try:
        monkeypatch.setattr(
            state_store_module,
            "probe_filesystem",
            lambda path: _network_probe(path),
        )
        with pytest.raises(WriterLockFilesystemError):
            assert_state_store_durable(store)
    finally:
        store.close()


def _network_probe(path: object) -> object:
    from breezy.persistence.catalog import FilesystemLocality, FilesystemProbe

    return FilesystemProbe(
        path=str(path),
        mount_point="/mnt/nfs",
        fs_type="nfs4",
        locality=FilesystemLocality.NETWORK,
        detail="forced for test",
    )


# ---------------------------------------------------------------------------
# 9. ENOSPC / read-only mount surfaces as StateStoreLockError
# ---------------------------------------------------------------------------


def test_set_surfaces_enospc_as_state_store_lock_error_not_a_silent_no_op(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "state.json"
    store = FileStateStore(path)
    try:
        store.set("existing", b"before")

        def explode(fd: int) -> None:
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(os, "fsync", explode)

        with pytest.raises(StateStoreLockError):
            store.set("new-key", b"after")

        monkeypatch.undo()
        # The failed write must not have corrupted or silently dropped the
        # previously-durable key.
        assert store.get("existing") == b"before"
    finally:
        store.close()


def test_set_surfaces_a_read_only_directory_as_state_store_lock_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "state.json"
    store = FileStateStore(path)

    def explode(*args: object, **kwargs: object) -> int:
        raise OSError(30, "Read-only file system")

    monkeypatch.setattr(os, "open", explode)
    try:
        with pytest.raises(StateStoreLockError):
            store.set("k", b"v")
    finally:
        monkeypatch.undo()
        store.close()


# ---------------------------------------------------------------------------
# 10. close() is idempotent and releases the lock
# ---------------------------------------------------------------------------


def test_close_is_idempotent(tmp_path: Path) -> None:
    store = FileStateStore(tmp_path / "state.json")
    store.close()
    store.close()  # must not raise


def test_close_releases_the_lock_for_a_new_instance(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    store = FileStateStore(path)
    store.close()

    second = FileStateStore(path)  # must not hang or raise
    second.close()


def test_get_and_set_after_close_raise(tmp_path: Path) -> None:
    store = FileStateStore(tmp_path / "state.json")
    store.close()

    with pytest.raises(StateStoreError):
        store.get("k")

    with pytest.raises(StateStoreError):
        store.set("k", b"v")


# ---------------------------------------------------------------------------
# per-value CRC32 sanity: what actually gets written on disk
# ---------------------------------------------------------------------------


def test_the_on_disk_record_carries_its_own_crc32(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    store = FileStateStore(path)
    try:
        store.set("k", b"hello")
    finally:
        store.close()

    parsed = json.loads(path.read_text())
    entry = parsed["k"]
    decoded = base64.b64decode(entry["data"])
    assert decoded == b"hello"
    assert entry["crc32"] == zlib.crc32(b"hello")


# ---------------------------------------------------------------------------
# 11. directory-identity gap: a symlink swapped in for the state directory
#
# `mkdir(parents=True, exist_ok=True)` catches `FileExistsError` and falls
# back to `is_dir()`, which FOLLOWS symlinks -- so a directory swapped for a
# symlink (before, or immediately after, `mkdir`) is silently accepted as
# "already exists and is a directory", and every subsequent `set()` --
# including the `ua_trap_blocked` halt latch -- writes into the symlink's
# target with no exception and no log. `catalog.py`'s `_require_real_directory`
# closes exactly this hole for the catalog; these tests hold `state_store.py`
# to the same discipline.
# ---------------------------------------------------------------------------


def test_set_raises_when_the_state_directory_is_swapped_for_a_symlink_after_construction(
    tmp_path: Path,
) -> None:
    """The core attack: construction succeeds normally, then the state
    directory is renamed aside and replaced with a symlink to an
    attacker-controlled directory. The `flock` is held on the original
    inode and never notices. The next `set()` must refuse -- raising
    `StateStorePathError` -- and must NOT write through the link.
    """
    state_dir = tmp_path / "state_dir"
    path = state_dir / "state.json"
    store = FileStateStore(path)
    try:
        store.set("gate:global", b"first")

        attacker_dir = tmp_path / "attacker_dir"
        attacker_dir.mkdir()
        shutil.rmtree(state_dir)
        state_dir.symlink_to(attacker_dir)

        with pytest.raises(StateStorePathError):
            store.set("gate:global", b"malicious-via-symlink")

        # Nothing was written through the link.
        assert list(attacker_dir.iterdir()) == []

        # The in-memory value from before the attack is untouched.
        assert store.get("gate:global") == b"first"
    finally:
        # `state_dir` is now a symlink, not the directory the lock file lives
        # in on the original inode; `close()` only touches the already-open
        # fd, so this remains safe regardless.
        store.close()


def test_init_raises_when_the_state_directory_is_already_a_symlink(tmp_path: Path) -> None:
    """The directory is swapped for a symlink BEFORE construction ever runs.
    `mkdir(exist_ok=True)`'s `is_dir()` fallback would otherwise accept it
    silently; `__init__` must raise instead.
    """
    attacker_dir = tmp_path / "attacker_dir"
    attacker_dir.mkdir()

    state_dir = tmp_path / "state_dir"
    state_dir.symlink_to(attacker_dir)

    path = state_dir / "state.json"

    with pytest.raises(StateStorePathError):
        FileStateStore(path)

    # Nothing was written through the link.
    assert list(attacker_dir.iterdir()) == []


def test_init_catches_a_symlink_planted_immediately_after_mkdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """As close to the real TOCTOU race as a deterministic test can get:
    `Path.mkdir` is patched to create the real directory and then, in the
    same call, replace it with a symlink -- simulating an attacker who wins
    the race in the window between `mkdir` returning and the identity check
    running. The check must still catch it.
    """
    state_dir = tmp_path / "state_dir"
    path = state_dir / "state.json"
    attacker_dir = tmp_path / "attacker_dir"
    attacker_dir.mkdir()

    real_mkdir = Path.mkdir
    triggered = False

    def racing_mkdir(self: Path, *args: object, **kwargs: object) -> None:
        nonlocal triggered
        real_mkdir(self, *args, **kwargs)  # type: ignore[arg-type]
        if self == state_dir and not triggered:
            triggered = True
            shutil.rmtree(self)
            self.symlink_to(attacker_dir)

    monkeypatch.setattr(Path, "mkdir", racing_mkdir)

    with pytest.raises(StateStorePathError):
        FileStateStore(path)

    assert list(attacker_dir.iterdir()) == []


def test_repeated_set_and_get_on_a_real_directory_still_works(tmp_path: Path) -> None:
    """The happy path is unaffected by the directory-identity check, and the
    per-write check does not meaningfully degrade a store that sits on the
    poll path. This is a sanity bound, not a strict perf-regression gate.
    """
    path = tmp_path / "sub" / "state.json"
    store = FileStateStore(path)
    try:
        started = time.monotonic()
        for i in range(50):
            store.set(f"key-{i}", f"value-{i}".encode("ascii"))
        elapsed = time.monotonic() - started

        for i in range(50):
            assert store.get(f"key-{i}") == f"value-{i}".encode("ascii")

        assert elapsed < 5.0, f"50 sets took {elapsed:.2f}s, suspiciously slow"
    finally:
        store.close()


# ---------------------------------------------------------------------------
# 12. fork safety: a forked child's close() must not release the parent's lock
#
# POSIX `flock` is associated with the OPEN FILE DESCRIPTION, not the
# process. A `fork()`ed child inherits a duplicate fd on the SAME lock, and
# an explicit `LOCK_UN` issued through ANY duplicate fd releases the lock for
# every holder immediately -- unlike a plain `close()`, which only releases
# it once every duplicate fd is closed. `FileStateStore.close()` calls
# `release_flock` (`LOCK_UN`), so a child that inherits a store and calls
# `close()` on it -- e.g. a `multiprocessing` fork-start-method worker
# tearing itself down -- silently breaks the parent's single-writer
# exclusivity, with no exception anywhere.
# ---------------------------------------------------------------------------

_FORK_SAFETY_PARENT_SCRIPT = """
import os
import sys
import time
from pathlib import Path
from breezy.persistence.state_store import FileStateStore

store = FileStateStore(Path({path!r}))

pid = os.fork()
if pid == 0:
    # Child: inherits a duplicate fd on the SAME flock. Its close() must be
    # a no-op that does not release the parent's lock.
    try:
        store.close()
    except BaseException:
        os._exit(2)
    os._exit(0)

_, status = os.waitpid(pid, 0)
if not (os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0):
    print("CHILD_FAILED", flush=True)
    sys.exit(1)

# Announce readiness, then hold the lock open so a third, unrelated process
# attempting the same path can be observed to block (proving the parent's
# lock survived the child's close()) rather than acquire immediately (which
# would prove it was silently released).
print("READY", flush=True)
time.sleep(5)
store.close()
"""

_TRY_ACQUIRE_SCRIPT = """
from pathlib import Path
from breezy.persistence.state_store import FileStateStore

store = FileStateStore(Path({path!r}))
print("ACQUIRED", flush=True)
store.close()
"""


def test_forked_childs_close_does_not_release_the_parents_lock(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    parent_script = tmp_path / "_fork_parent.py"
    parent_script.write_text(_FORK_SAFETY_PARENT_SCRIPT.format(path=str(path)))

    parent_proc = subprocess.Popen(
        [sys.executable, str(parent_script)],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert parent_proc.stdout is not None
        ready_line = parent_proc.stdout.readline()
        assert ready_line.strip() == "READY", (
            f"parent process never signalled readiness: {ready_line!r}"
        )

        acquire_script = tmp_path / "_try_acquire.py"
        acquire_script.write_text(_TRY_ACQUIRE_SCRIPT.format(path=str(path)))
        acquirer = subprocess.Popen(
            [sys.executable, str(acquire_script)],
            stdout=subprocess.PIPE,
            text=True,
        )
        try:
            out, _ = acquirer.communicate(timeout=1.5)
            pytest.fail(
                "a third, unrelated process acquired the state-store lock "
                "while the parent should still hold it -- the forked "
                f"child's close() silently released the parent's flock "
                f"(stdout: {out!r})"
            )
        except subprocess.TimeoutExpired:
            acquirer.kill()
            acquirer.wait(timeout=5)
    finally:
        if parent_proc.poll() is None:
            parent_proc.terminate()
            parent_proc.wait(timeout=5)
