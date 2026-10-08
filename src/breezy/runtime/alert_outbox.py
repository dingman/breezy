"""Durable alert outbox and per-attempt delivery records (AUT-6 plan r15 §3.6.2-3.6.3, E-1).

Claim order is ``os.utime`` then ``os.rename`` into ``outbox/claimed/<drainer>/`` then a directory
fsync. Entry age is the filename ``ts_ns``; only claim staleness reads mtime. Every file is
published with ``mkstemp`` then ``os.link`` (write-once), 0600 in 0700 directories.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import re
import stat
import tempfile
import time
from pathlib import Path
from typing import Final, NamedTuple

from breezy.registry.health_model import AlertPayload

ALERT_CLAIM_STALE_S: Final[int] = 60
ALERT_OUTBOX_MAX: Final[int] = 128
ALERT_OUTBOX_CRITICAL_RESERVED: Final[int] = 16
NS: Final[int] = 1_000_000_000
_SCHEMA: Final[str] = "alert_delivery/v1"
_OUTBOX_SCHEMA: Final[str] = "alert_outbox/v1"
_FILE_MODE: Final[int] = 0o600
_DIR_MODE: Final[int] = 0o700
_WRITER_RE: Final[re.Pattern[str]] = re.compile(r"[a-z0-9_]{1,64}\Z")
_EVENT_SAFE: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9_]")
_ARMED_NAME: Final[str] = "armed.json"
_ARMED_SCHEMA: Final[str] = "alerts_armed/v1"
_ARMED_MODE: Final[int] = 0o444
_ARMED_MAX_BYTES: Final[int] = 4096
_ATTEMPTS: Final[frozenset[str]] = frozenset({"alert", "retry", "canary", "drain"})


def default_alerts_root() -> Path:
    """``~/.local/share/breezy/evidence/alerts``. Tests patch this; construction does not mkdir."""
    return Path.home() / ".local" / "share" / "breezy" / "evidence" / "alerts"


def validate_ids(writer: str, attempt_kind: str) -> None:
    if _WRITER_RE.fullmatch(writer) is None:
        raise ValueError("writer id must match [a-z0-9_]{1,64}")
    if attempt_kind not in _ATTEMPTS:
        raise ValueError("attempt_kind must be alert, retry, canary or drain")


def _day(ts_ns: int) -> str:
    return dt.datetime.fromtimestamp(ts_ns / NS, tz=dt.UTC).date().isoformat()


def ts_ns_of(path: Path) -> int | None:
    head = path.name.split("_", 1)[0]
    if not head.isdigit():
        return None
    return int(head)


def _fsync_dir(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _mkdir(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, _DIR_MODE)


def _publish(
    directory: Path, name: str, body: dict[str, object], *, mode: int = _FILE_MODE
) -> Path:
    """mkstemp, fsync, ``os.link`` onto ``name``. ``FileExistsError`` if ``name`` is taken."""
    _mkdir(directory)
    fd, tmp_name = tempfile.mkstemp(prefix=".", suffix=".partial", dir=directory)
    tmp = Path(tmp_name)
    dest = directory / name
    try:
        try:
            os.fchmod(fd, mode)
            data = memoryview(json.dumps(body, sort_keys=True).encode())
            while data:
                data = data[os.write(fd, data) :]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.link(tmp, dest)
    finally:
        # the temp name never outlives the call, on success or on any failure
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
    _fsync_dir(directory)
    return dest


def is_regular(path: Path) -> bool:
    """A regular file, never a symlink (C1): ``lstat`` and ``S_ISREG``, no following."""
    try:
        return stat.S_ISREG(os.lstat(path).st_mode)
    except OSError:
        return False


class AlertOutbox:
    """Write-once entries under ``<root>/outbox``. Claimed copies live in ``claimed/<drainer>/``."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def occupancy(self) -> int:
        """JSON files in ``outbox/`` and ``outbox/claimed/`` (the 128-slot bound)."""
        out = self.root / "outbox"
        if not out.is_dir():
            return 0
        return sum(1 for path in out.rglob("*.json") if is_regular(path))

    def refuses(self, severity: str) -> bool:
        """Non-CRITICAL stops at 112; CRITICAL stops at 128."""
        count = self.occupancy()
        if severity == "CRITICAL":
            return count >= ALERT_OUTBOX_MAX
        return count >= ALERT_OUTBOX_MAX - ALERT_OUTBOX_CRITICAL_RESERVED

    def write_entry(self, payload: AlertPayload, *, writer: str, drill: bool, ts_ns: int) -> Path:
        """Write ``<ts>_<event>.json``. A same-name collision retries at ``ts_ns + 1``."""
        validate_ids(writer, "alert")
        token = _EVENT_SAFE.sub("_", payload.event) or "event"
        stamp = ts_ns
        directory = self.root / "outbox"
        while True:
            body: dict[str, object] = {
                "schema": _OUTBOX_SCHEMA,
                "ts_ns": stamp,
                "severity": payload.severity,
                "event": payload.event,
                "site": payload.site,
                "detail": payload.detail,
                "writer": writer,
                "drill": drill,
            }
            try:
                return _publish(directory, f"{stamp}_{token}.json", body)
            except FileExistsError:
                stamp += 1

    def claim(self, entry: Path, drainer: str) -> Path | None:
        """E-1: utime, then rename into ``claimed/<drainer>/``, then directory fsyncs.

        ``None`` for the loser (``ENOENT``), for a non-regular file (never followed) and for a
        destination that already exists (never overwritten). Any other ``OSError`` propagates so a
        crash between utime and rename leaves the entry where it was.
        """
        if not is_regular(entry):
            return None
        try:
            os.utime(entry, follow_symlinks=False)
        except FileNotFoundError:
            return None
        dest_dir = self.root / "outbox" / "claimed" / drainer
        _mkdir(dest_dir)
        dest = dest_dir / entry.name
        if os.path.lexists(dest):
            return None
        try:
            os.rename(entry, dest)
        except FileNotFoundError:
            return None
        _fsync_dir(dest_dir)
        _fsync_dir(entry.parent)
        return dest

    def restamp(self, claimed: Path) -> bool:
        """Refresh the claim mtime. ``False`` on ENOENT: another drainer already took it."""
        try:
            os.utime(claimed, follow_symlinks=False)
        except FileNotFoundError:
            return False
        return True

    def reclaim_stale(self, drainer: str, now: float | None = None) -> list[Path]:
        """Reclaim other drainers' claims whose mtime age is strictly greater than 60 s."""
        clock = time.time() if now is None else now
        claimed_root = self.root / "outbox" / "claimed"
        if not claimed_root.is_dir():
            return []
        found: list[Path] = []
        for holder in sorted(claimed_root.iterdir()):
            if holder.is_symlink() or not holder.is_dir() or holder.name == drainer:
                continue
            for entry in sorted(holder.glob("*.json")):
                try:
                    age = clock - os.lstat(entry).st_mtime
                except FileNotFoundError:
                    continue
                if age <= ALERT_CLAIM_STALE_S or not is_regular(entry):
                    continue
                moved = self.claim(entry, drainer)
                if moved is not None:
                    found.append(moved)
        return found

    def complete(self, claimed: Path) -> None:
        """Remove a claimed entry only after a delivered record was written, then fsync.

        A claim reclaimed by another drainer during the POST is already gone from here: nothing
        to remove (at-least-once delivery, the reclaimer removes its own copy).
        """
        directory = claimed.parent
        try:
            os.unlink(claimed)
        except FileNotFoundError:
            return
        if directory.is_dir():
            _fsync_dir(directory)

    def quarantine(self, claimed: Path) -> Path | None:
        """Rename an unreadable claimed entry to ``<name>.bad`` so it is never retried."""
        bad = claimed.with_name(claimed.name + ".bad")
        try:
            os.rename(claimed, bad)
        except OSError:
            return None
        return bad


class DeliveryRecordWriter:
    """One ``<ts>_<writer>_<d|f>.json`` per attempt. Collision bumps ``ts_ns`` by 1."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def write(
        self,
        *,
        event: str,
        ts_ns: int,
        writer: str,
        delivered: bool,
        status_class: str,
        severity: str,
        attempt_kind: str,
        drill: bool,
        site: str,
        outbox_entry: str,
        outbox_write_failed: bool = False,
    ) -> Path:
        validate_ids(writer, attempt_kind)
        stamp = ts_ns
        suffix = "d" if delivered else "f"
        while True:
            body: dict[str, object] = {
                "event": event,
                "ts_ns": stamp,
                "delivered": delivered,
                "status_class": status_class,
                "severity": severity,
                "attempt_kind": attempt_kind,
                "drill": drill,
                "schema": _SCHEMA,
                "site": site,
                "outbox_entry": outbox_entry,
            }
            if outbox_write_failed:
                body["outbox_write_failed"] = True
            directory = self.root / _day(stamp)
            try:
                return _publish(directory, f"{stamp}_{writer}_{suffix}.json", body)
            except FileExistsError:
                stamp += 1


class ArmedMarker(NamedTuple):
    """The write-once arming marker: the first delivered canary record's basename and instant."""

    ts_ns: int
    record: str


def write_armed_marker(root: Path, *, record: str, ts_ns: int) -> bool:
    """Publish ``<root>/armed.json`` (0444) once. ``True`` if written, ``False`` if it existed.

    ``os.link`` is the ``O_EXCL`` step: ``EEXIST`` means an earlier canary armed the detector and
    is success. Nothing in this module rewrites or removes the marker.
    """
    body: dict[str, object] = {"schema": _ARMED_SCHEMA, "ts_ns": ts_ns, "record": record}
    try:
        _publish(root, _ARMED_NAME, body, mode=_ARMED_MODE)
    except FileExistsError:
        return False
    return True


def read_armed_marker(root: Path) -> ArmedMarker | None:
    """The marker, or ``None`` when it does not exist (ENOENT: unarmed).

    Any other failure raises: ``OSError`` for an unreadable or non-regular file, ``ValueError``
    for content that is not a valid ``alerts_armed/v1`` body.
    """
    path = root / _ARMED_NAME
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        raise OSError("armed marker is not a regular file")
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        raw = os.read(fd, _ARMED_MAX_BYTES + 1)
    finally:
        os.close(fd)
    if len(raw) > _ARMED_MAX_BYTES:
        raise ValueError("armed marker too large")
    body = json.loads(raw)
    if (
        not isinstance(body, dict)
        or body.get("schema") != _ARMED_SCHEMA
        or type(body.get("ts_ns")) is not int
        or not isinstance(body.get("record"), str)
    ):
        raise ValueError("armed marker is not alerts_armed/v1")
    return ArmedMarker(body["ts_ns"], body["record"])
