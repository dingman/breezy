"""AUT-1 ``CaptureStreamWriter``: an actor-owned native ``StreamingFeatherWriter`` behind a
catch-all wrapper (plan r12 section 3.4.2, ruling R-A: option B).

L-1 holds: the writer class, its Arrow schemas, its rotation and its file format are Nautilus's own.
This module adds only what the native writer cannot do:

* ``write`` never raises into a caller or a bus handler (L-16), including the ``serialize_batch``
  failure that sits outside the writer's own try block (``writer.py:259``);
* a per-write landing check (r11 GM2, r12 item 1): the native writer swallows its own write errors
  and drops silently in three places, so each judged write compares the table's
  ``(size, creation_time)`` pair from the native public ``get_current_file_info()`` before and
  after, and an unchanged pair is a counted drop. A table absent before the call additionally
  needs ``size > 0`` after it (the writer creates a ``custom_`` table's stream BEFORE it
  serialises). A rotation inside the call always sets a new ``creation_time``, so it is a success
  even when the size returns to its earlier value;
* ``table_bytes`` sums every ``<table>_*.feather`` file (closed and open), so the 00:00Z
  ``SCHEDULED_DATES`` rotation never reads as flat.

Not judged, never a drop, never counted: a class outside the include list, and a native event whose
``id`` is already in the wrapper's mirror of the writer's 10,000-id dedupe window.
"""

import datetime as dt
import os
import re
import stat
from collections import OrderedDict
from pathlib import Path
from typing import Any, Final

import pandas as pd
from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import Clock
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.model.events import OrderFilled, OrderInitialized, PositionEvent
from nautilus_trader.persistence.funcs import class_to_filename
from nautilus_trader.persistence.writer import RotationMode, StreamingFeatherWriter

from breezy.domain.forecast_point import ForecastPoint
from breezy.persistence.autonomy.capture_publish import CaptureHealth, StreamCounters
from breezy.persistence.autonomy.capture_records import (
    SOURCES,
    CaptureHeartbeat,
    DecisionRecord,
    DetectorEvent,
    FrameCopy,
    OrderEventRecord,
)
from breezy.persistence.autonomy.paths import venue_component
from breezy.persistence.autonomy.single_read import ensure_dir, open_root

__all__ = [
    "CAPTURE_INCLUDE_TYPES",
    "ROTATION_INTERVAL",
    "ROTATION_MODE",
    "ROTATION_TIME",
    "ROTATION_TIMEZONE",
    "CaptureStreamWriter",
    "capture_root",
]

CAPTURE_INCLUDE_TYPES: Final[list[type]] = [
    DecisionRecord,
    FrameCopy,
    OrderEventRecord,
    DetectorEvent,
    CaptureHeartbeat,
    ForecastPoint,
    OrderInitialized,
    OrderFilled,
    *PositionEvent.__subclasses__(),
]

#: The recorder's constants (``runtime/node_config.py`` ``QUOTE_TAPE_ROTATION_*``), restated because
#: persistence may not import runtime; ``test_rotation_matches_recorder_constants`` pins equality.
ROTATION_MODE: Final[RotationMode] = RotationMode.SCHEDULED_DATES
ROTATION_INTERVAL: Final[pd.Timedelta] = pd.Timedelta(days=1)
ROTATION_TIME: Final[dt.time] = dt.time(0, 0, 0, 0)
ROTATION_TIMEZONE: Final[str] = "UTC"

#: The native writer's dedupe window (``writer.py`` ``_seen_event_ids_maxlen``).
_DEDUPE_WINDOW: Final[int] = 10_000
_INSTANCE_DIR_MODE: Final[int] = 0o700
_INSTANCE_RE: Final[re.Pattern[str]] = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_FILE_RE: Final[re.Pattern[str]] = re.compile(r"\A(?P<table>.+)_\d+\.feather\Z")


def capture_root(data_root: Path, venue: str) -> Path:
    """``<data_root>/derived/capture_stream/<venue>``: never under the quote-tape catalog."""
    return data_root / "derived" / "capture_stream" / venue_component(venue)


class CaptureStreamWriter:
    def __init__(
        self,
        *,
        root: Path,
        instance_id: str,
        source: str = "live",
        include_types: list[type] | None = None,
        health: CaptureHealth | None = None,
    ) -> None:
        if _INSTANCE_RE.match(instance_id) is None:
            raise ValueError("instance_id must be a short alphanumeric token")
        if source not in SOURCES:
            raise ValueError("source must be live or canary")
        self._root = root
        self._instance_id = instance_id
        self._source = source
        self._include_types = list(
            CAPTURE_INCLUDE_TYPES if include_types is None else include_types
        )
        self._include = frozenset(self._include_types)
        self.health: CaptureHealth = CaptureHealth() if health is None else health
        self._writer: StreamingFeatherWriter | None = None
        self._mirror: OrderedDict[UUID4, None] = OrderedDict()
        self._written: dict[str, int] = {}
        self._write_failures = 0
        self._write_drops = 0
        self._drops_since_submit_flush = 0

    # -- identity ------------------------------------------------------------------------

    @property
    def stream_dir(self) -> Path:
        return self._root / self._source / self._instance_id

    @property
    def native_writer(self) -> StreamingFeatherWriter:
        """The native writer, for diagnostics and tests. Raises if the stream is not open."""
        if self._writer is None:
            raise RuntimeError("stream is not open")
        return self._writer

    @property
    def write_failures(self) -> int:
        return self._write_failures

    @property
    def write_drops(self) -> int:
        return self._write_drops

    def counters(self) -> StreamCounters:
        return StreamCounters(dict(self._written), self._write_failures, self._write_drops)

    def consume_drops_since_submit_flush(self) -> int:
        drops, self._drops_since_submit_flush = self._drops_since_submit_flush, 0
        return drops

    # -- lifecycle -----------------------------------------------------------------------

    def open(self, cache: Cache, clock: Clock) -> bool:
        """Create the private stream directory and the native writer. False (never raises) on
        failure, with ``health`` down; a later ``write`` then returns False.

        The instance directory must be newly created, or existing, EMPTY and mode 0700: a boot
        never reuses another boot's files (E-7 rule 4, one writer per directory). Any other state
        refuses with ``open_failed``. The trust boundary is the same uid: a process of this uid can
        always write the directory, so this guards against reuse and accident, not against it.
        """
        try:
            rootfd = open_root(self._root)
            try:
                dirfd = ensure_dir(rootfd, (self._source, self._instance_id))
            finally:
                os.close(rootfd)
            try:
                _require_fresh_directory(dirfd)
            finally:
                os.close(dirfd)
            self._writer = StreamingFeatherWriter(
                path=str(self.stream_dir),
                cache=cache,
                clock=clock,
                include_types=list(self._include_types),
                rotation_mode=ROTATION_MODE,
                rotation_interval=ROTATION_INTERVAL,
                rotation_time=ROTATION_TIME,
                rotation_timezone=ROTATION_TIMEZONE,
            )
        except Exception:  # noqa: BLE001 - composition must not crash the node on a bad root
            self._writer = None
            self.health.mark_failed("open_failed")
            return False
        return True

    def close(self) -> None:
        writer, self._writer = self._writer, None
        if writer is None:
            return
        try:
            writer.flush()
            writer.close()
        except Exception:  # noqa: BLE001 - close never raises; the veto records it
            self.health.mark_failed("close_exception")

    def flush(self) -> bool:
        if self._writer is None:
            self.health.mark_failed("flush_before_open")
            return False
        try:
            self._writer.flush()
        except Exception:  # noqa: BLE001 - L-16
            self.health.mark_failed("flush_exception")
            return False
        return True

    # -- writes --------------------------------------------------------------------------

    def write(self, obj: object) -> bool:
        """True when the object landed, or was not judged. False on a failure or a counted drop."""
        table = class_to_filename(type(obj))
        try:
            return self._judged_write(obj, table)
        except Exception:  # noqa: BLE001 - L-16: covers serialize_batch outside the native try
            self._write_failures += 1
            self.health.mark_failed(f"write_exception:{table}")
            return False

    def _judged_write(self, obj: object, table: str) -> bool:
        writer = self._writer
        if writer is None:
            self._write_failures += 1
            self.health.mark_failed("write_before_open")
            return False
        if type(obj) not in self._include or self._already_seen(obj):
            return True
        before = _file_pair(writer, table)
        writer.write(obj)
        after = _file_pair(writer, table)
        if not _landed(before, after):
            self._write_drops += 1
            self._drops_since_submit_flush += 1
            self.health.mark_failed(f"write_dropped:{table}")
            return False
        self._written[table] = self._written.get(table, 0) + 1
        return True

    def _already_seen(self, obj: object) -> bool:
        """Mirror of the native dedupe: inserts on exactly the writer's condition (a ``UUID4``
        ``id``), with the same bound, so a repeat is skipped by both.

        Called BEFORE the native write, on purpose: the native writer inserts the id before its own
        write too, so an event whose write then drops is never retried by either (a counted drop,
        not a second attempt) and the mirror stays exact."""
        event_id = getattr(obj, "id", None)
        if not isinstance(event_id, UUID4):
            return False
        if event_id in self._mirror:
            return True
        self._mirror[event_id] = None
        if len(self._mirror) > _DEDUPE_WINDOW:
            self._mirror.popitem(last=False)
        return False

    # -- bytes ---------------------------------------------------------------------------

    def table_bytes(self) -> dict[str, int]:
        """Per table, the summed ``lstat`` size of every regular ``<table>_*.feather`` file in the
        stream directory. Symlinks are never counted."""
        sizes: dict[str, int] = {}
        try:
            entries = list(os.scandir(self.stream_dir))
        except FileNotFoundError:
            return sizes
        for entry in entries:
            match = _FILE_RE.match(entry.name)
            if match is None:
                continue
            info = entry.stat(follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode):
                continue
            table = match.group("table")
            sizes[table] = sizes.get(table, 0) + info.st_size
        return sizes


def _require_fresh_directory(dirfd: int) -> None:
    """Raise unless the directory is empty and exactly mode 0700."""
    if stat.S_IMODE(os.fstat(dirfd).st_mode) != _INSTANCE_DIR_MODE:
        raise PermissionError("instance directory is not mode 0700")
    with os.scandir(dirfd) as entries:
        if next(entries, None) is not None:
            raise FileExistsError("instance directory is not empty")


def _file_pair(writer: StreamingFeatherWriter, table: str) -> tuple[int, Any] | None:
    info = writer.get_current_file_info().get(table)
    return None if info is None else (info["size"], info["creation_time"])


def _landed(before: tuple[int, Any] | None, after: tuple[int, Any] | None) -> bool:
    if after is None:
        return False  # the missing-writer path
    if before is None:
        return after[0] > 0  # first write: the writer created the key before it serialised
    return before != after
