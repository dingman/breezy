"""Tests for the startup durability guard on the gate's `StateStore`.

Replaces the Cache-persistence assertion this module's predecessor guarded
(`assert_cache_persistence_configured` / `cache_persistence_config_from` /
`CachePersistenceConfig`). That guard required ``CacheConfig.database is not
None``; ``system/kernel.py:311-329`` of the installed nautilus-trader 1.231.0
accepts only ``'redis'`` or ``None`` there, and this deployment has no Redis,
so **no Redis-free node config could ever satisfy it**. It also described the
wrong mechanism: Breezy's durable state is
:class:`breezy.runtime.sqlite_store.SqliteStateStore`, not the Nautilus
``Cache`` (that store's docstring records the measured evidence -- ``Cache.add``
returns before the write is durable, ``Cache.get`` never reads the database,
and ``Cache.reset()`` can launder a permanent trading halt).

The replacement asserts what actually matters now, and asserts it
**empirically**: it round-trips a probe value through the real store and
through an INDEPENDENT handle on the same backing medium. A declared flag is
worthless here, because the entire failure mode being defended against is
state that *claims* to persist and does not.

Nothing here constructs a Nautilus node, and nothing reaches the network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from breezy.ingest.gate import (
    DURABILITY_PROBE_KEY,
    InMemoryStateStore,
    StateStore,
    StateStoreNotDurableError,
    assert_state_store_durable,
)
from breezy.runtime.sqlite_store import SqliteStateStore


def shared_memory_store() -> tuple[InMemoryStateStore, object]:
    """A store plus an opener over the SAME backing dict.

    The in-process analogue of "reopen the SQLite file": an independent handle
    that can only observe a write if the write reached the shared medium.
    """
    backing: dict[str, bytes] = {}
    return InMemoryStateStore(backing), lambda: InMemoryStateStore(backing)


# ---------------------------------------------------------------------------
# The real store passes
# ---------------------------------------------------------------------------


def test_the_real_sqlite_store_is_certified_durable(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    with SqliteStateStore(path) as store:
        assert_state_store_durable(store, opener=lambda: SqliteStateStore(path))


def test_a_shared_backing_in_memory_store_passes() -> None:
    store, opener = shared_memory_store()
    assert_state_store_durable(store, opener=opener)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The guard is EMPIRICAL: each way a store can fake durability fails closed
# ---------------------------------------------------------------------------


def test_a_plain_in_memory_store_is_rejected() -> None:
    """`InMemoryStateStore()` with a private dict is the canonical
    not-actually-durable store: each opened handle starts empty.
    """
    store = InMemoryStateStore()
    with pytest.raises(StateStoreNotDurableError):
        assert_state_store_durable(store, opener=InMemoryStateStore)


def test_a_store_that_declares_durability_but_drops_writes_is_rejected() -> None:
    class LyingStore:
        """Reports success from `set` and persists nothing. `is_durable=True`
        is exactly the declared flag the guard refuses to trust.
        """

        is_durable = True

        def get(self, key: str) -> bytes | None:
            return None

        def set(self, key: str, value: bytes) -> None:
            return None

        def close(self) -> None:
            return None

    store = LyingStore()
    with pytest.raises(StateStoreNotDurableError):
        assert_state_store_durable(store, opener=LyingStore)  # type: ignore[arg-type]


def test_a_write_only_visible_to_the_writing_handle_is_rejected() -> None:
    """The `Cache.add` shape: the write "succeeds" and a sibling handle over
    the same medium cannot see it.
    """
    store, _shared_opener = shared_memory_store()
    with pytest.raises(StateStoreNotDurableError):
        assert_state_store_durable(store, opener=InMemoryStateStore)  # type: ignore[arg-type]


def test_a_store_that_never_re_reads_the_medium_is_rejected() -> None:
    """The `Cache.get` shape: reads are served from a private in-memory dict,
    so a value another handle committed is invisible forever.
    """
    backing: dict[str, bytes] = {}

    class WriteThroughReadCachedStore:
        def __init__(self) -> None:
            self._own: dict[str, bytes] = {}

        def get(self, key: str) -> bytes | None:
            return self._own.get(key)

        def set(self, key: str, value: bytes) -> None:
            self._own[key] = value
            backing[key] = value

        def close(self) -> None:
            return None

    class SharedView:
        def get(self, key: str) -> bytes | None:
            return backing.get(key)

        def set(self, key: str, value: bytes) -> None:
            backing[key] = value

        def close(self) -> None:
            return None

    store = WriteThroughReadCachedStore()
    with pytest.raises(StateStoreNotDurableError):
        assert_state_store_durable(store, opener=SharedView)  # type: ignore[arg-type]


def test_a_store_that_loses_state_when_a_handle_closes_is_rejected() -> None:
    """State must survive a handle's whole lifecycle, not merely coexist with
    two live handles.
    """
    backing: dict[str, bytes] = {}

    class VolatileOnCloseStore:
        def get(self, key: str) -> bytes | None:
            return backing.get(key)

        def set(self, key: str, value: bytes) -> None:
            backing[key] = value

        def close(self) -> None:
            backing.clear()

    with pytest.raises(StateStoreNotDurableError):
        assert_state_store_durable(
            VolatileOnCloseStore(),  # type: ignore[arg-type]
            opener=VolatileOnCloseStore,  # type: ignore[arg-type]
        )


def test_a_store_that_raises_on_set_fails_closed() -> None:
    class ExplodingStore(InMemoryStateStore):
        def set(self, key: str, value: bytes) -> None:
            raise OSError("disk full")

    with pytest.raises(StateStoreNotDurableError):
        assert_state_store_durable(ExplodingStore(), opener=ExplodingStore)


def test_an_opener_that_raises_fails_closed() -> None:
    store, _opener = shared_memory_store()

    def broken_opener() -> StateStore:
        raise OSError("cannot reopen")

    with pytest.raises(StateStoreNotDurableError):
        assert_state_store_durable(store, opener=broken_opener)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Namespacing and importability
# ---------------------------------------------------------------------------


def test_the_probe_key_cannot_collide_with_gate_or_index_keys() -> None:
    assert not DURABILITY_PROBE_KEY.startswith("gate:")
    assert not DURABILITY_PROBE_KEY.startswith("productidx:")


def test_the_guard_is_importable_without_a_live_nautilus_node() -> None:
    """`breezy.ingest.gate` imports no nautilus_trader; the guard must stay
    callable in complete isolation, exactly as its predecessor was.

    Structural (AST), not a substring search: the module docstring legitimately
    NAMES the package to state that it does not import it.
    """
    import ast
    import inspect

    from breezy.ingest import gate

    tree = ast.parse(inspect.getsource(gate))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert "nautilus_trader" not in imported


def test_the_old_cache_persistence_guard_is_gone() -> None:
    """The removed API must not come back: it asserted an unsatisfiable
    condition about a mechanism Breezy no longer uses.
    """
    from breezy.ingest import gate

    for removed in (
        "CachePersistenceConfig",
        "CachePersistenceMisconfiguredError",
        "assert_cache_persistence_configured",
        "cache_persistence_config_from",
    ):
        assert not hasattr(gate, removed), f"{removed} should have been removed"


# ---------------------------------------------------------------------------
# Every I/O failure inside the probe is reported as absent durability
#
# These are not cosmetic branches. The guard is the last thing standing between
# a crash-loop and a laundered trading halt, so an error raised WHILE trying to
# establish durability must be indistinguishable from proven non-durability --
# never from a pass.
# ---------------------------------------------------------------------------


def _raiser(method: str) -> type:
    """Build a shared-backing store class whose `method` raises on the Nth call."""
    backing: dict[str, bytes] = {}
    calls = {"get": 0, "set": 0}
    handles = {"n": 0}

    class Store:
        def __init__(self) -> None:
            handles["n"] += 1
            self.handle_index = handles["n"]

        def get(self, key: str) -> bytes | None:
            calls["get"] += 1
            if method == "view_get" and self.handle_index == 2:
                raise OSError("read failed on the second handle")
            if method == "survivor_get" and self.handle_index == 3:
                raise OSError("read failed on the third handle")
            if method == "store_reread" and self.handle_index == 1 and calls["get"] > 1:
                raise OSError("re-read failed on the original handle")
            return backing.get(key)

        def set(self, key: str, value: bytes) -> None:
            calls["set"] += 1
            if method == "view_set" and self.handle_index == 2:
                raise OSError("write failed on the second handle")
            backing[key] = value

        def close(self) -> None:
            return None

    return Store


@pytest.mark.parametrize(
    ("stage", "fragment"),
    [
        ("view_get", "raised while reading"),
        ("view_set", "raised while writing"),
        ("store_reread", "raised while re-reading"),
        ("survivor_get", "raised while confirming"),
    ],
)
def test_an_io_failure_at_any_probe_stage_fails_closed(stage: str, fragment: str) -> None:
    store_cls = _raiser(stage)
    store = store_cls()

    with pytest.raises(StateStoreNotDurableError) as excinfo:
        assert_state_store_durable(store, opener=store_cls)  # type: ignore[arg-type]

    assert fragment in str(excinfo.value)


def test_every_handle_the_probe_opens_is_closed() -> None:
    backing: dict[str, bytes] = {}
    opened: list[object] = []
    closed: list[object] = []

    class TrackingStore(InMemoryStateStore):
        def __init__(self) -> None:
            super().__init__(backing)
            opened.append(self)

        def close(self) -> None:
            closed.append(self)

    original = TrackingStore()
    opened.clear()  # the caller's own store is not the probe's to close

    assert_state_store_durable(original, opener=TrackingStore)

    # One cross-handle view, one survivor.
    assert len(opened) == 2
    assert closed == opened


def test_state_that_vanishes_from_a_freshly_opened_handle_is_rejected() -> None:
    """The last probe stage, isolated: writes are visible cross-handle AND the
    original re-reads them, yet a handle opened LATER sees nothing. That is a
    medium whose contents do not outlive a connection, so a restart would come
    up with every halt cleared.
    """
    backing: dict[str, bytes] = {}
    handles = {"n": 0}

    class FadesAfterTwoHandles(InMemoryStateStore):
        def __init__(self) -> None:
            handles["n"] += 1
            super().__init__({} if handles["n"] > 2 else backing)

    with pytest.raises(StateStoreNotDurableError, match="did not survive"):
        assert_state_store_durable(FadesAfterTwoHandles(), opener=FadesAfterTwoHandles)
