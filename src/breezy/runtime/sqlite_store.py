"""Durable, file-backed :class:`~breezy.ingest.gate.StateStore` on SQLite.

A prior evaluation rejected backing ``StateStore`` with Nautilus ``Cache``
on concrete evidence: ``Cache.add`` queues its write to a background task
and returns before the write is durable; ``Cache.get`` reads only an
in-memory dict, never the database; and ``Cache.reset()`` clears that dict
without clearing the database, which silently resurrects
``ua_trap_blocked=False`` and can launder a permanent trading halt. SQLite
avoids all three: writes commit synchronously before ``set()`` returns,
reads always go through the same durable file, and there is no separate
in-memory cache to fall out of sync with it.

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
    caller's success signal -- unlike ``Cache.add``, whose write completes
    on a background task after the call already returned.

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
            raise TypeError(f"key must be str, got {type(key).__name__}")
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
            raise TypeError(f"key must be str, got {type(key).__name__}")
        if not isinstance(value, bytes):
            raise TypeError(f"value must be bytes, got {type(value).__name__}")
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
