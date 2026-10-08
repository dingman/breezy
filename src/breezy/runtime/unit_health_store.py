"""Atomic file store of the AUT-6 unit health pass (plan r15 sections 3.9 and 3.11).

Everything lives under ``evidence/unit_health`` (the health row's bind). Single writer: the
``breezy-autonomy-health`` pass, under ``.health.lock``. Two write shapes only:

* write-once (class, action and cursor-reset records, 0444): ``mkstemp``, fsync, ``os.link`` (an
  existing name is never replaced; ``False`` is returned instead), so a crash leaves either nothing
  or a complete file;
* atomic replace (``seen/<unit>.json``, ``cursor.json``, ``heartbeat.json``, ``day_<date>.json``,
  0600): ``mkstemp``, fsync, ``os.replace``;

plus the ``memavail_<date>.jsonl`` append (``O_APPEND``, fsync) and the lock file.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import json
import os
import re
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

NS: Final = 1_000_000_000
HEARTBEAT_STALE_S: Final = 1800
HEARTBEAT_UNKNOWN_STREAK_MAX: Final = 3
MEMAVAIL_MIN_SAMPLES: Final = 72
MEMAVAIL_WINDOW_S: Final = 24 * 3600
MEMAVAIL_INSUFFICIENT: Final = "memavail_samples_insufficient"
RECENT_INVOCATIONS_KEPT: Final = 32
CLASS_SUFFIX: Final = "__class.json"
ACTION_SUFFIX: Final = "__action.json"
CLASS_SCHEMA: Final = "unit_health_class/v1"
_KINDS: Final = frozenset({"unit_failure", "finding"})
_DAY_RE: Final = re.compile(r"\d{4}-\d{2}-\d{2}")
_DIR_MODE: Final = 0o700
_RECORD_MODE: Final = 0o444
_FILE_MODE: Final = 0o600
_ALERT_RECORD_RE: Final = re.compile(r"\d+_[a-z0-9_]{1,64}_d\.json")
_DELIVERY_SCHEMA: Final = "alert_delivery/v1"
_ALERT_DAYS: Final = 3


def day_of_ns(ts_ns: int) -> str:
    return dt.datetime.fromtimestamp(ts_ns / NS, tz=dt.UTC).date().isoformat()


def day_start_s(day: str) -> int:
    return int(dt.datetime.fromisoformat(day).replace(tzinfo=dt.UTC).timestamp())


def previous_day(day: str) -> str:
    return (dt.date.fromisoformat(day) - dt.timedelta(days=1)).isoformat()


def _fsync_dir(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _encode(body: Mapping[str, object]) -> bytes:
    return (json.dumps(body, sort_keys=True) + "\n").encode("utf-8")


def _stage(directory: Path, data: bytes, mode: int) -> Path:
    fd, name = tempfile.mkstemp(dir=directory, prefix=".tmp-")
    try:
        os.fchmod(fd, mode)
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view) :]
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        os.unlink(name)
        raise
    os.close(fd)
    return Path(name)


def write_once(path: Path, body: Mapping[str, object], mode: int = _RECORD_MODE) -> bool:
    """Publish ``body`` at ``path`` unless it exists. ``True`` when this call created it."""
    path.parent.mkdir(mode=_DIR_MODE, parents=True, exist_ok=True)
    tmp = _stage(path.parent, _encode(body), mode)
    try:
        os.link(tmp, path)
    except FileExistsError:
        return False
    finally:
        os.unlink(tmp)
    _fsync_dir(path.parent)
    return True


def replace_atomic(path: Path, body: Mapping[str, object], mode: int = _FILE_MODE) -> None:
    path.parent.mkdir(mode=_DIR_MODE, parents=True, exist_ok=True)
    tmp = _stage(path.parent, _encode(body), mode)
    try:
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise
    _fsync_dir(path.parent)


def read_json(path: Path) -> dict[str, Any] | None:
    """The parsed object, or ``None`` when the file is absent, unreadable or not an object."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


class StoreRecordError(Exception):
    """A record that must exist is unreadable or malformed; ``reason`` is the pass reason."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


@dataclass(frozen=True, slots=True)
class CursorState:
    """``cursor`` is the journal position after the last committed entry; with no entry yet,
    ``since_us`` is where the next read starts."""

    cursor: str | None
    since_us: int | None
    ts_ns: int


@dataclass(frozen=True, slots=True)
class MemAvailWindow:
    minimum_free_kib: int | None
    minimum_available_kib: int | None
    count: int
    unknown_reason: str | None


class HealthStore:
    """The unit health directory. ``root`` is ``<data root>/evidence/unit_health``."""

    def __init__(self, root: Path) -> None:
        self.root = root

    # ------------------------------------------------------------------ lock

    @contextlib.contextmanager
    def lock(self) -> Iterator[bool]:
        """The health lock: ``True`` when held, ``False`` when another pass holds it."""
        self.root.mkdir(mode=_DIR_MODE, parents=True, exist_ok=True)
        fd = os.open(self.root / ".health.lock", os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, _FILE_MODE)
        held = False
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                held = True
            except BlockingIOError:
                held = False
            yield held
        finally:
            os.close(fd)

    # ------------------------------------------------------------------ records

    def _days_newest_first(self) -> list[Path]:
        try:
            names = [p for p in self.root.iterdir() if p.is_dir() and _DAY_RE.fullmatch(p.name)]
        except OSError:
            return []
        return sorted(names, reverse=True)

    def _find(self, unit: str, invocation_id: str, suffix: str) -> Path | None:
        for directory in self._days_newest_first():
            candidate = directory / f"{unit}__{invocation_id}{suffix}"
            if candidate.is_file():
                return candidate
        return None

    def write_class(
        self, day: str, unit: str, invocation_id: str, body: Mapping[str, object]
    ) -> bool:
        return write_once(self.root / day / f"{unit}__{invocation_id}{CLASS_SUFFIX}", body)

    def write_action(
        self, day: str, unit: str, invocation_id: str, body: Mapping[str, object]
    ) -> bool:
        return write_once(self.root / day / f"{unit}__{invocation_id}{ACTION_SUFFIX}", body)

    def read_class(self, unit: str, invocation_id: str) -> dict[str, Any] | None:
        """``None`` when absent; ``StoreRecordError`` when present but unreadable or malformed."""
        path = self._find(unit, invocation_id, CLASS_SUFFIX)
        if path is None:
            return None
        body = read_json(path)
        if body is None or body.get("schema") != CLASS_SCHEMA or body.get("kind") not in _KINDS:
            raise StoreRecordError("class_record_unreadable")
        return body

    def read_action(self, unit: str, invocation_id: str) -> dict[str, Any] | None:
        path = self._find(unit, invocation_id, ACTION_SUFFIX)
        return read_json(path) if path is not None else None

    def has_action(self, unit: str, invocation_id: str) -> bool:
        return self._find(unit, invocation_id, ACTION_SUFFIX) is not None

    def class_records_on(self, day: str) -> list[dict[str, Any]]:
        """Every unit-failure class record of ``day`` (findings excluded), in name order."""
        out: list[dict[str, Any]] = []
        for path in sorted((self.root / day).glob(f"*{CLASS_SUFFIX}")):
            body = read_json(path)
            if body is None or body.get("schema") != CLASS_SCHEMA or body.get("kind") not in _KINDS:
                unit, _, rest = path.name[: -len(CLASS_SUFFIX)].partition("__")
                # An unreadable record still counts: it is never explained.
                out.append(
                    {
                        "kind": "unit_failure",
                        "unit": unit,
                        "invocation_id": rest,
                        "unit_class": "UNREADABLE",
                    }
                )
            elif body.get("kind") == "unit_failure":
                out.append(body)
        return out

    def finding_records_on(self, day: str, finding: str) -> list[dict[str, Any]]:
        found = (read_json(p) for p in sorted((self.root / day).glob(f"*{CLASS_SUFFIX}")))
        return [
            b for b in found if b and b.get("kind") == "finding" and b.get("finding") == finding
        ]

    def oldest_unrolled_day(self) -> str | None:
        """The oldest day directory that has records but no ``day_<date>.json`` rollup."""
        unrolled = [
            d.name
            for d in self._days_newest_first()
            if not (self.root / f"day_{d.name}.json").exists()
        ]
        return min(unrolled) if unrolled else None

    def cursor_ts_hint(self) -> int | None:
        """``ts_ns`` of a cursor file that no longer validates, if it still parses."""
        raw = read_json(self.root / "cursor.json")
        ts = raw.get("ts_ns") if raw else None
        return ts if _is_int(ts) else None

    def class_records_for(self, unit: str, day: str) -> list[dict[str, Any]]:
        return [b for b in self.class_records_on(day) if b.get("unit") == unit]

    def write_cursor_reset(self, day: str, ts_ns: int, reason: str) -> bool:
        body = {"schema": "unit_health_cursor_reset/v1", "ts_ns": ts_ns, "reason": reason}
        return write_once(self.root / day / f"cursor_reset__{ts_ns}.json", body)

    def cursor_reset_records(self, day: str) -> list[dict[str, Any]]:
        found = (read_json(p) for p in sorted((self.root / day).glob("cursor_reset__*.json")))
        return [b for b in found if b is not None]

    # ------------------------------------------------------------------ replaced state

    def read_seen(self, unit: str) -> dict[str, Any] | None:
        return read_json(self.root / "seen" / f"{unit}.json")

    def write_seen(self, unit: str, body: Mapping[str, object]) -> None:
        replace_atomic(self.root / "seen" / f"{unit}.json", body)

    def read_cursor(self) -> CursorState | None:
        raw = read_json(self.root / "cursor.json")
        if raw is None or raw.get("schema") != "health_cursor/v1":
            return None
        cursor, since, ts = raw.get("cursor"), raw.get("since_us"), raw.get("ts_ns")
        if not isinstance(ts, int) or isinstance(ts, bool):
            return None
        if not (cursor is None or isinstance(cursor, str)):
            return None
        if cursor is None and not _is_int(since):
            return None
        return CursorState(cursor, since if _is_int(since) else None, ts)

    def write_cursor(self, cursor: str | None, ts_ns: int, since_us: int | None) -> None:
        body = {
            "schema": "health_cursor/v1",
            "cursor": cursor,
            "since_us": since_us,
            "ts_ns": ts_ns,
        }
        replace_atomic(self.root / "cursor.json", body)

    def read_heartbeat(self) -> dict[str, Any] | None:
        return read_json(self.root / "heartbeat.json")

    def write_heartbeat(self, body: Mapping[str, object]) -> None:
        replace_atomic(self.root / "heartbeat.json", body)

    def read_rollup(self, day: str) -> dict[str, Any] | None:
        return read_json(self.root / f"day_{day}.json")

    def write_rollup(self, day: str, body: Mapping[str, object]) -> None:
        replace_atomic(self.root / f"day_{day}.json", body)

    def latest_rollup_day(self) -> str | None:
        days = sorted(
            p.name[4:-5] for p in self.root.glob("day_*.json") if _DAY_RE.fullmatch(p.name[4:-5])
        )
        return days[-1] if days else None

    # ------------------------------------------------------------------ MemAvailable samples

    def append_memavail(self, ts_ns: int, available_kib: int, free_kib: int) -> None:
        """One sample line per completed pass (F10), appended and fsynced."""
        self.root.mkdir(mode=_DIR_MODE, parents=True, exist_ok=True)
        line = json.dumps(
            {
                "ts_ns": ts_ns,
                "mem_available_kib": available_kib,
                "mem_available_free_kib": free_kib,
            },
            sort_keys=True,
        )
        path = self.root / f"memavail_{day_of_ns(ts_ns)}.jsonl"
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC, _FILE_MODE)
        try:
            os.write(fd, (line + "\n").encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)

    def memavail_window(self, now_ns: int) -> MemAvailWindow:
        """The trailing-24 h minimum of the samples (F10); fewer than 72 samples is inconclusive."""
        floor = now_ns - MEMAVAIL_WINDOW_S * NS
        free: list[int] = []
        avail: list[int] = []
        for day in {day_of_ns(floor), day_of_ns(now_ns)}:
            path = self.root / f"memavail_{day}.jsonl"
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in lines:
                sample = _sample(line)
                if sample is not None and floor <= sample[0] <= now_ns:
                    avail.append(sample[1])
                    free.append(sample[2])
        if len(free) < MEMAVAIL_MIN_SAMPLES:
            return MemAvailWindow(None, None, len(free), MEMAVAIL_INSUFFICIENT)
        return MemAvailWindow(min(free), min(avail), len(free), None)


def _sample(line: str) -> tuple[int, int, int] | None:
    try:
        raw = json.loads(line)
        ts, avail, free = raw["ts_ns"], raw["mem_available_kib"], raw["mem_available_free_kib"]
    except (ValueError, KeyError, TypeError):
        return None
    if all(isinstance(v, int) and not isinstance(v, bool) for v in (ts, avail, free)):
        return ts, avail, free
    return None


# --------------------------------------------------------------------------- heartbeat helpers


def heartbeat_is_stale(heartbeat: Mapping[str, Any], now_ns: int) -> bool:
    """ARCH's dead-man rule: ``ts_ns`` older than 1800 s."""
    ts = heartbeat.get("ts_ns")
    return not isinstance(ts, int) or now_ns - ts > HEARTBEAT_STALE_S * NS


def heartbeat_unknown_streak(heartbeat: Mapping[str, Any]) -> int:
    streak = heartbeat.get("passes_unknown_streak")
    return streak if isinstance(streak, int) else 0


# --------------------------------------------------------------------------- delivered lookup


def alerts_delivered(
    alerts_root: Path, *, now_ns: Callable[[], int] = time.time_ns, days: int = _ALERT_DAYS
) -> Callable[[str, str], bool]:
    """``(event, site)`` is delivered when a ``..._d.json`` record of the last ``days`` days has
    both. A missing, unreadable or foreign-schema record proves nothing."""

    def delivered(event: str, site: str) -> bool:
        today = dt.datetime.fromtimestamp(now_ns() / NS, tz=dt.UTC).date()
        for back in range(days):
            directory = alerts_root / (today - dt.timedelta(days=back)).isoformat()
            try:
                names = sorted(os.listdir(directory))
            except OSError:
                continue
            for name in names:
                if not _ALERT_RECORD_RE.fullmatch(name):
                    continue
                body = read_json(directory / name)
                if (
                    body is not None
                    and body.get("schema") == _DELIVERY_SCHEMA
                    and body.get("delivered") is True
                    and body.get("event") == event
                    and body.get("site") == site
                ):
                    return True
        return False

    return delivered
