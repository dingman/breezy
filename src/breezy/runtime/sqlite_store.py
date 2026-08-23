"""Durable, file-backed :class:`~breezy.ingest.gate.StateStore` on SQLite.

Why not the native Nautilus ``Cache``
-------------------------------------
Every claim below was verified by reading the installed
``nautilus-trader==1.231.0`` in ``.venv/`` at the cited ``path:line``, and is
pinned by ``tests/contract/test_nautilus_cache_durability_contract.py`` so it
fails loudly on a version bump instead of drifting. Paths are relative to
``nautilus_trader/``.

A previous revision of this docstring asserted three defects in ``Cache``.
**One of them was wrong and one was vacuous**; they are corrected here rather
than left standing, because the right conclusion reached through wrong
reasoning is not evidence. Corrections are recorded at the bottom.

The single sufficient reason, and it is configuration-dependent:

* **Under this deployment's configuration, ``Cache`` is memory-only.**
  ``Cache.add`` writes ``self._general[key] = value`` and then forwards to a
  database **only** ``if self._database is not None`` (``cache/cache.pyx:1704-1708``).
  ``Cache.get`` is ``return self._general.get(key)`` -- it never reads a
  database on any code path (``cache/cache.pyx:2853``). The database is read
  once, in bulk, by the ``cache_general()`` warm-load, which sets
  ``self._general = {}`` when there is no database (``cache/cache.pyx:289-299``).
  Breezy configures ``CacheConfig(database=None, flush_on_start=False)``
  (``breezy.runtime.node_config``), and ``NautilusKernel`` maps a falsy
  ``config.cache.database`` to ``cache_db = None`` (``system/kernel.py:310-311``),
  so ``Cache.has_backing`` is ``False`` (``cache/cache.pyx:115``) and nothing
  written to it survives process exit.

* **The alternative is Redis, and only Redis.** ``NautilusKernel`` accepts
  ``config.cache.database.type == "redis"`` and raises ``ValueError`` for
  every other value, case-sensitively (``system/kernel.py:312-329``);
  ``DatabaseConfig.type`` defaults to ``"redis"`` and is documented
  ``{'redis'}`` (``common/config.py:357,389``). The adapter unconditionally
  constructs ``nautilus_pyo3.RedisCacheDatabase``
  (``cache/database.pyx:162-166``). This deployment has no Redis and adding
  one to make an NWS poll cursor durable is a heavier dependency than a
  single local file.

So the honest statement is **not** "``Cache`` is not durable" -- with Redis it
is. It is: ``Cache`` is memory-only under the only configuration available to
this deployment, and the supported alternative is a Redis server this
deployment does not have.

What SQLite gives instead: ``set()`` ``COMMIT``\\ s before it returns, ``get()``
reads the same durable file, and there is no second in-memory copy to
desynchronise.

Corrections to the previous justification (1.231.0)
---------------------------------------------------
* **FALSE:** "``Cache.add`` queues its write to a background task and returns
  before the write is durable." There is no background task in this path.
  ``add`` mutates a dict synchronously and calls ``self._database.add``
  in-line when a database exists (``cache/cache.pyx:1704-1708``); with
  ``database=None`` it performs no write at all. The only deferral mechanism
  in the tree is the opt-in ``CacheConfig.buffer_interval_ms``, which defaults
  to ``None`` (``cache/config.py:67``) and applies to the Rust Redis backing,
  which is unreachable here.
* **TRUE but vacuous for us:** "``Cache.reset()`` clears the dict without
  clearing the database." ``reset`` does clear ``_general``
  (``cache/cache.pyx:1292``) while database flushing is the separate
  ``flush_db()`` (``cache/cache.pyx:1332-1344``). But the consequence claimed
  -- that this "resurrects ``ua_trap_blocked=False``" -- is backwards: after
  ``reset`` a ``get`` returns ``None``, it does not return a stale ``False``.
  And with ``database=None`` there is no database to desynchronise from.

This module is deliberately Nautilus-free, matching
``breezy.ingest.gate``'s own isolation stance.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from types import TracebackType
from typing import Self

_CREATE_TABLE_SQL = "CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value BLOB NOT NULL)"
_SELECT_SQL = "SELECT value FROM state WHERE key = ?"
_UPSERT_SQL = (
    "INSERT INTO state (key, value) VALUES (?, ?) "
    "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
)


class SqliteStateStore:
    """A durable :class:`~breezy.ingest.gate.StateStore` backed by a single
    SQLite file.

    Durability
    ----------
    ``PRAGMA journal_mode=WAL`` and ``PRAGMA synchronous=FULL`` are set at
    construction, and every :meth:`set` call ``COMMIT``\\ s before
    returning. The durability boundary therefore coincides exactly with the
    caller's success signal -- unlike ``Cache.add``, which under this
    deployment's ``database=None`` config never leaves memory at all (see the
    module docstring).

    Thread-safety
    --------------
    SQLite connections opened with the default ``check_same_thread=True``
    are usable only from the thread that created them. This class picks
    **confinement to a single thread** over the alternative
    (``check_same_thread=False`` plus an explicit ``threading.Lock`` around
    every operation) because every caller in this codebase -- the ingest
    Actors -- runs as a single-threaded asyncio task, matching Nautilus's
    own concurrency model; there is no legitimate cross-thread caller
    today. Confinement also fails LOUDLY (``RuntimeError``) the instant a
    cross-thread call happens, rather than silently serializing it behind
    a lock and hiding a threading bug that should not exist in the first
    place. Any access from a thread other than the constructing thread
    raises immediately.
    """

    def __init__(self, path: Path | str, *, timeout_s: float = 5.0) -> None:
        resolved = Path(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self._owner_thread = threading.get_ident()
        self._closed = False
        self._conn = sqlite3.connect(str(resolved), timeout=timeout_s, check_same_thread=True)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.execute(_CREATE_TABLE_SQL)
        self._conn.commit()

    def _check_thread(self) -> None:
        if threading.get_ident() != self._owner_thread:
            raise RuntimeError(
                "SqliteStateStore was constructed on a different thread than "
                "the one calling it now. This store deliberately confines "
                "access to its constructing thread rather than allowing "
                "cross-thread use behind a lock -- see the class docstring."
            )

    def _check_open(self) -> None:
        if self._closed:
            raise RuntimeError("SqliteStateStore is closed")

    def _query_pragma(self, name: str) -> str:
        """Read a PRAGMA value back off this store's own connection.

        Internal, and used by tests to verify the durability pragmas set at
        construction actually took effect -- ``synchronous`` in particular
        is a per-connection setting, not persisted to the database file, so
        it can only be observed through this connection.
        """
        self._check_thread()
        self._check_open()
        cursor = self._conn.execute(f"PRAGMA {name}")
        row = cursor.fetchone()
        return str(row[0])

    def get(self, key: str) -> bytes | None:
        if not isinstance(key, str):
            raise TypeError(f"key must be str, was {type(key).__name__}")
        self._check_thread()
        self._check_open()
        cursor = self._conn.execute(_SELECT_SQL, (key,))
        row = cursor.fetchone()
        if row is None:
            return None
        value = row[0]
        assert isinstance(value, bytes)
        return value

    def set(self, key: str, value: bytes) -> None:
        if not isinstance(key, str):
            raise TypeError(f"key must be str, was {type(key).__name__}")
        if not isinstance(value, bytes):
            raise TypeError(f"value must be bytes, was {type(value).__name__}")
        self._check_thread()
        self._check_open()
        self._conn.execute(_UPSERT_SQL, (key, value))
        self._conn.commit()

    def close(self) -> None:
        self._check_thread()
        if not self._closed:
            self._conn.close()
            self._closed = True

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
