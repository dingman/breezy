"""Contract tests pinning `Cache.add`/`Cache.get`'s in-memory-only semantics.

Every assertion here was observed by execution against the pinned install
(nautilus-trader 1.231.0), not inferred from documentation. Run these FIRST
on any version bump: a failure means the platform moved, not that Breezy is
wrong.

`Cache.add` (`cache/cache.pyx:1686-1708`) writes to the in-process
`self._general` dict UNCONDITIONALLY and FIRST (`:1704`), then -- only if a
`database` was configured -- forwards the same write to it (`:1706-1708`).
`Cache.get` (`cache/cache.pyx:2834-2853`) reads ONLY from `self._general`
(`:2853`); it never queries the configured database, even when one is
present. Both methods are declared `cpdef ... -> void`/`-> bytes` with no
acknowledgement channel for the DOWNSTREAM database write's outcome -- so a
`database.add` call that fails to actually persist (returns normally without
raising, e.g. a fire-and-forget pipelined write to a backing store) is
structurally undetectable through `Cache.add`'s return value. Breezy's
integrity design must therefore treat `Cache.add` as "committed to the
in-process cache, NOT confirmed durable" -- which is exactly why this file
pins the observable in-memory behaviour without requiring a live Redis: the
undetectable-failure claim is about the RETURN CHANNEL's shape (`void`), a
fact that holds whether or not a real backing store is attached.

What this file does NOT attempt: proving that a live Redis write can fail
silently underneath a real `RedisCacheDatabase`. That would require a live
Redis connection, which is out of scope for a no-network contract test --
skipped here deliberately (see the completion report).

Scope: `cache/cache.pyx` `Cache.add` (`:1686-1708`), `Cache.get`
(`:2834-2853`). No network access, no live Redis.
"""

from __future__ import annotations

import pytest
from nautilus_trader.cache.cache import Cache
from nautilus_trader.cache.config import CacheConfig
from nautilus_trader.cache.facade import CacheDatabaseFacade

pytestmark = pytest.mark.contract


class _RecordingDatabase(CacheDatabaseFacade):
    """A `CacheDatabaseFacade` double with no network: it records calls made
    to it and never talks to Redis. Used to observe what `Cache.add`/`.get`
    actually call, not to simulate a real backing store's failure modes."""

    def __init__(self) -> None:
        super().__init__()
        self.add_calls: list[tuple[str, bytes]] = []

    def add(self, key: str, value: bytes) -> None:
        self.add_calls.append((key, value))

    def load(self) -> dict[str, bytes]:
        raise AssertionError("Cache.get must never call database.load()")

    def keys(self, pattern: str = "*") -> list[str]:
        raise AssertionError("Cache.get must never call database.keys()")


class _SilentlyDroppingDatabase(CacheDatabaseFacade):
    """Simulates a downstream write that returns normally but never actually
    persists anything -- no raise, no acknowledgement, no record kept. This is
    the shape of failure `Cache.add`'s `void` return cannot distinguish from
    success."""

    def add(self, key: str, value: bytes) -> None:
        pass  # deliberately does nothing: the write vanishes without a trace


def test_add_writes_to_the_in_memory_general_dict_with_no_database_configured() -> None:
    """`cache/cache.pyx:1704` -- `self._general[key] = value` runs
    unconditionally. With `database=None`, `add` then `get` round-trips
    through memory alone.
    """
    cache = Cache(database=None, config=CacheConfig())

    cache.add("mykey", b"myvalue")

    assert cache.get("mykey") == b"myvalue"


def test_get_never_queries_the_database_even_when_one_is_configured() -> None:
    """`cache/cache.pyx:2853` -- `return self._general.get(key)` is the ENTIRE
    body's data access; no `self._database.load()`/`.keys()` call exists on
    this path. A database double whose `load`/`keys` raise `AssertionError`
    if ever called proves `get` never reaches them, for both a HIT and a MISS.
    """
    database = _RecordingDatabase()
    cache = Cache(database=database, config=CacheConfig())
    cache.add("present", b"value")  # goes through database.add, not load/keys

    hit = cache.get("present")
    miss = cache.get("absent-key")

    assert hit == b"value"
    assert miss is None
    assert database.add_calls == [("present", b"value")]


def test_add_forwards_to_the_database_when_one_is_configured() -> None:
    """`cache/cache.pyx:1706-1708` -- `if self._database is not None:
    self._database.add(key, value)` -- confirms the forwarding actually
    happens (not just that `get` ignores it), using the same no-network
    double.
    """
    database = _RecordingDatabase()
    cache = Cache(database=database, config=CacheConfig())

    cache.add("k1", b"v1")
    cache.add("k2", b"v2")

    assert database.add_calls == [("k1", b"v1"), ("k2", b"v2")]


def test_add_returns_none_regardless_of_whether_the_database_write_actually_persisted() -> None:
    """`cache/cache.pyx:1686` -- `cpdef void add(...)`. Documented literally
    in the compiled method's own signature line (`Cache.add.__doc__` begins
    `"Cache.add(self, str key, bytes value) -> void"`). Calling `add` against
    a database double that SILENTLY DROPS the write (no raise, no record, no
    acknowledgement -- `_SilentlyDroppingDatabase.add`) returns `None`
    identically to a database that actually persisted: the return channel
    carries no signal either way. The in-memory cache still reflects the
    value (`cache/cache.pyx:1704` ran first and unconditionally), so a caller
    inspecting only `cache.get(key)` would see the write as fully successful
    even though nothing downstream retained it.
    """
    assert Cache.add.__doc__ is not None
    assert Cache.add.__doc__.splitlines()[0] == "Cache.add(self, str key, bytes value) -> void"

    database = _SilentlyDroppingDatabase()
    cache = Cache(database=database, config=CacheConfig())

    outcome = cache.add("mykey", b"myvalue")

    assert outcome is None
    # The in-memory side looks identical to a fully-durable write -- this IS
    # the undetectable-failure hazard, not a bug in the double.
    assert cache.get("mykey") == b"myvalue"
