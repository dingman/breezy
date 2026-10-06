"""F13-C1 S4: the append-only poll ledger (the observed-availability record).

One JSON object per line at ``<root>/<source>/poll_ledger.jsonl``. Event kinds:

* ``miss``  -- a poll saw the product ABSENT at ``fetched_at_ns`` (the interval's lower bound);
* ``seen``  -- the first poll that saw a payload digest, with its computed availability;
* ``refused`` -- a payload failed validation (nothing was stored);
* ``stale_alert`` -- a stale-source alert was sent (dedupe marker).

A line is written with a single ``os.write`` of ``<json>\\n`` and fsynced. A process killed
mid-append leaves at most a torn FINAL line: readers skip it, and the next append starts on a
fresh line. All writes happen under the source's unit lock.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

__all__ = ["LEDGER_NAME", "PollLedger"]

LEDGER_NAME: Final[str] = "poll_ledger.jsonl"


class PollLedger:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._cache: dict[str, list[dict[str, Any]]] = {}

    def path(self, source: str) -> Path:
        return self._root / source / LEDGER_NAME

    def _load(self, source: str) -> list[dict[str, Any]]:
        try:
            raw = self.path(source).read_bytes()
        except FileNotFoundError:
            return []
        events: list[dict[str, Any]] = []
        for line in raw.split(b"\n"):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue  # a torn append (the writer starts the next event on a fresh line)
            if isinstance(event, dict):
                events.append(event)
        return events

    def events(self, source: str) -> list[dict[str, Any]]:
        """Every complete event in append order, read from disk ONCE per instance and then
        kept in step by :meth:`record` (one cycle holds the unit lock, so no one else writes)."""
        if source not in self._cache:
            self._cache[source] = self._load(source)
        return list(self._cache[source])

    def record(self, source: str, event: Mapping[str, Any]) -> None:
        path = self.path(source)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(dict(event), sort_keys=True, separators=(",", ":")).encode() + b"\n"
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o644)
        try:
            if os.fstat(fd).st_size and os.pread(fd, 1, os.fstat(fd).st_size - 1) != b"\n":
                line = b"\n" + line  # repair a torn tail so the new event starts cleanly
            os.write(fd, line)
            os.fsync(fd)
            if source in self._cache:
                self._cache[source].append(dict(event))
        finally:
            os.close(fd)

    # -- derived reads -----------------------------------------------------------

    def seen_events(self, source: str) -> list[dict[str, Any]]:
        return [e for e in self.events(source) if e.get("kind") == "seen"]

    def find_seen(
        self, source: str, station: str, run_ts_ns: int, sha256: str | None = None
    ) -> dict[str, Any] | None:
        for event in self.seen_events(source):
            if (
                event.get("station") == station
                and event.get("run_ts_ns") == run_ts_ns
                and (sha256 is None or event.get("sha256") == sha256)
            ):
                return event
        return None

    def last_miss_ns(self, source: str, station: str, run_ts_ns: int) -> int | None:
        stamps = [
            int(e["fetched_at_ns"])
            for e in self.events(source)
            if e.get("kind") == "miss"
            and e.get("station") == station
            and e.get("run_ts_ns") == run_ts_ns
        ]
        return max(stamps) if stamps else None

    def last_seen_ns(self, source: str) -> int | None:
        stamps = [int(e["fetched_at_ns"]) for e in self.seen_events(source)]
        return max(stamps) if stamps else None

    def last_alert_ns(self, source: str, kind: str = "stale_alert") -> int | None:
        stamps = [int(e["fetched_at_ns"]) for e in self.events(source) if e.get("kind") == kind]
        return max(stamps) if stamps else None
