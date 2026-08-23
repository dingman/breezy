"""Contract: the Nautilus ``Cache`` facts that justify `breezy.runtime.sqlite_store`.

Pinned against **`nautilus-trader==1.231.0`** (asserted below). Every
assertion here was executed against the installed package before it was
written, and every one drives the REAL Nautilus objects -- a real `Cache`, a
real `CacheConfig`/`DatabaseConfig`, a real `NautilusKernel`. Nothing is
mocked. A mock would pin Breezy's *assumptions* about Nautilus rather than
Nautilus's behaviour, which is precisely the defect this file exists to
prevent.

Why this file exists
--------------------
`src/breezy/runtime/sqlite_store.py` justifies an entire parallel persistence
mechanism -- a second, non-native store -- on the claim that the native
`Cache` cannot hold durable state for this deployment. Repo CLAUDE.md's null
hypothesis ("assume Nautilus already provides it") makes that the single most
load-bearing "we cannot use the native facility" argument in the codebase, and
until now it was prose with no citation and no test.

**A failure in this file does NOT mean the test is broken.** It means Nautilus
changed a behaviour the `sqlite_store` justification rests on, and that
justification needs re-review -- possibly in favour of deleting
`SqliteStateStore` and moving back onto the native `Cache`. Read the failure;
do not weaken the assertion.

Verified `path:line` in the installed 1.231.0 (re-check on a version bump)
--------------------------------------------------------------------------
* `cache/cache.pyx:1704-1708` -- `Cache.add`: `self._general[key] = value`,
  then `if self._database is not None: self._database.add(key, value)`.
  Synchronous; no background task; no write at all when there is no database.
* `cache/cache.pyx:2853` -- `Cache.get`: `return self._general.get(key)`.
  Memory only, on every path.
* `cache/cache.pyx:289-299` -- `cache_general()`: loads from the database when
  present, else `self._general = {}`.
* `cache/cache.pyx:115` -- `self.has_backing = database is not None`.
* `system/kernel.py:310-311` -- falsy `config.cache.database` maps to
  `cache_db = None`.
* `system/kernel.py:312-329` -- only `type == "redis"` is accepted; every other
  value raises `ValueError`.
* `common/config.py:389` -- `DatabaseConfig.type` defaults to `"redis"`.

Scope guards
------------
No test here opens a socket or contacts a Redis server. The negative
database-type cases are rejected by kernel config validation *before* any
backing store is constructed, so they are pure offline assertions.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import nautilus_trader
import pytest
from nautilus_trader.cache.cache import Cache
from nautilus_trader.cache.config import CacheConfig
from nautilus_trader.common import Environment
from nautilus_trader.common.config import DatabaseConfig
from nautilus_trader.config import TradingNodeConfig
from nautilus_trader.system.kernel import NautilusKernel

PINNED_NAUTILUS_VERSION = "1.231.0"

# The exact config Breezy deploys (`breezy.runtime.node_config`). Restated
# literally rather than imported so that this file pins NAUTILUS' behaviour
# under that config even if Breezy's own config module is refactored; the
# separate `tests/unit/test_runtime_node_config.py` pins that Breezy still
# passes these values.
BREEZY_CACHE_CONFIG = CacheConfig(database=None, flush_on_start=False)

GENERAL_KEY = "breezy.contract.cursor"
GENERAL_VALUE = b"2026-08-23T06:27:00Z"


def test_pinned_nautilus_version() -> None:
    """Every citation in this module's docstring was read at this version."""
    assert nautilus_trader.__version__ == PINNED_NAUTILUS_VERSION, (
        f"These pins were verified against nautilus-trader "
        f"{PINNED_NAUTILUS_VERSION}, running against "
        f"{nautilus_trader.__version__}. Re-read every `path:line` cited in "
        f"this module's docstring and in `breezy/runtime/sqlite_store.py` "
        f"before updating this constant."
    )


class TestCacheIsMemoryOnlyWithoutADatabase:
    """`cache/cache.pyx:1704-1708`, `:2853`, `:289-299`, `:115`."""

    def test_has_backing_is_false_under_breezys_config(self) -> None:
        cache = Cache(database=None, config=BREEZY_CACHE_CONFIG)

        assert cache.has_backing is False

    def test_value_written_is_readable_from_the_same_instance(self) -> None:
        """Control: the write itself works, so the next test isolates durability."""
        cache = Cache(database=None, config=BREEZY_CACHE_CONFIG)

        cache.add(GENERAL_KEY, GENERAL_VALUE)

        assert cache.get(GENERAL_KEY) == GENERAL_VALUE

    def test_value_is_invisible_to_a_fresh_cache_instance(self) -> None:
        """THE load-bearing pin: nothing written to `Cache` outlives the instance.

        A fresh `Cache` stands in for a fresh process. If this ever returns
        the value, `Cache` acquired out-of-process persistence without a
        database and `SqliteStateStore` may be redundant.
        """
        writer = Cache(database=None, config=BREEZY_CACHE_CONFIG)
        writer.add(GENERAL_KEY, GENERAL_VALUE)

        reader = Cache(database=None, config=BREEZY_CACHE_CONFIG)

        assert reader.get(GENERAL_KEY) is None

    def test_warm_load_recovers_nothing_without_a_database(self) -> None:
        """`cache_general()` is the ONLY database read path, and it is a no-op here."""
        cache = Cache(database=None, config=BREEZY_CACHE_CONFIG)
        cache.add(GENERAL_KEY, GENERAL_VALUE)

        cache.cache_general()  # `cache/cache.pyx:298` -> `self._general = {}`

        assert cache.get(GENERAL_KEY) is None

    def test_reset_clears_the_value_rather_than_stranding_a_stale_one(self) -> None:
        """Pins the CORRECTED reading of `reset` (`cache/cache.pyx:1292`).

        An earlier `sqlite_store` docstring claimed `reset()` could
        "resurrect" a stale prior value. It cannot: `reset` clears the dict,
        so the subsequent read is `None`. This asserts the real direction so
        the wrong claim cannot be reintroduced.
        """
        cache = Cache(database=None, config=BREEZY_CACHE_CONFIG)
        cache.add(GENERAL_KEY, GENERAL_VALUE)

        cache.reset()

        assert cache.get(GENERAL_KEY) is None


@pytest.fixture
def running_loop() -> Iterator[asyncio.AbstractEventLoop]:
    """A live loop: `NautilusKernel` requires one for any non-BACKTEST environment.

    `system/kernel.py:274-276` -- `self._loop = loop or asyncio.get_running_loop()`.
    Breezy runs `Environment.LIVE`, so the kernel pins below must too.
    """
    loop = asyncio.new_event_loop()
    try:
        yield loop
    finally:
        loop.close()


def _node_config(database: DatabaseConfig | None) -> TradingNodeConfig:
    return TradingNodeConfig(
        environment=Environment.LIVE,
        trader_id="BREEZY-001",
        cache=CacheConfig(database=database, flush_on_start=False),
        message_bus=None,
        catalogs=[],
        actors=[],
        data_clients={},
        exec_clients={},
    )


class TestKernelCacheDatabaseMapping:
    """`system/kernel.py:310-329`, `common/config.py:389`."""

    def test_database_none_yields_a_kernel_cache_with_no_backing(
        self,
        running_loop: asyncio.AbstractEventLoop,
    ) -> None:
        """`CacheConfig(database=None)` -> `cache_db = None` -> memory-only `Cache`.

        Asserted through a REAL kernel, not by re-reading the source, so the
        whole config-to-`Cache` path is covered rather than one branch of it.
        """
        kernel = NautilusKernel(
            name="breezy-cache-contract",
            config=_node_config(None),
            loop=running_loop,
        )

        assert kernel.cache.has_backing is False

    @pytest.mark.parametrize(
        "database_type",
        [
            "sqlite",  # what Breezy actually wants, and cannot have here
            "postgres",  # exists in the pyo3 layer but is NOT wired to the kernel
            "in-memory",  # accepted in older versions; rejected in 1.231.0
            "REDIS",  # the check is case-SENSITIVE
        ],
    )
    def test_only_lowercase_redis_is_an_accepted_database_type(
        self,
        database_type: str,
        running_loop: asyncio.AbstractEventLoop,
    ) -> None:
        """This is why "just turn the cache database on" is not available to us.

        Rejected at `system/kernel.py:325-329`, during config validation and
        before any backing store is constructed -- so this test performs no
        network I/O.
        """
        with pytest.raises(
            ValueError, match="The only database type currently supported is 'redis'"
        ):
            NautilusKernel(
                name="breezy-cache-contract",
                config=_node_config(DatabaseConfig(type=database_type)),
                loop=running_loop,
            )

    def test_database_config_defaults_to_redis(self) -> None:
        """`common/config.py:389`.

        Constructing a bare `DatabaseConfig()` to "enable persistence" opts
        into Redis silently. Breezy therefore passes `database=None`
        explicitly rather than omitting the field.
        """
        assert DatabaseConfig().type == "redis"
