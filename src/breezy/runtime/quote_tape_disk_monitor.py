"""Disk-headroom monitoring for the quote-tape recorder runtime."""

from __future__ import annotations

import logging
import shutil
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DiskUsage:
    """Small, injectable subset of `shutil.disk_usage`."""

    total: int
    used: int
    free: int


DiskUsageProbe = Callable[[Path], DiskUsage]


@dataclass(frozen=True, slots=True)
class QuoteTapeDiskMonitorConfig:
    """Validated monitor settings for the quote-tape recorder."""

    catalog_root: Path
    min_free_bytes_warning: int
    min_free_bytes_error: int
    max_file_bytes_warning: int
    max_file_bytes_error: int
    check_interval_seconds: int


@dataclass(frozen=True, slots=True)
class _TapeFile:
    path: Path
    size_bytes: int


def disk_usage_probe(path: Path) -> DiskUsage:
    """Return disk usage for `path` using the real filesystem."""
    usage = shutil.disk_usage(path)
    return DiskUsage(total=usage.total, used=usage.used, free=usage.free)


class QuoteTapeDiskMonitor:
    """Monitors the quote-tape catalog root without reaching into Nautilus internals."""

    def __init__(
        self,
        config: QuoteTapeDiskMonitorConfig,
        *,
        disk_usage_probe: DiskUsageProbe = disk_usage_probe,
    ) -> None:
        self._config = config
        self._disk_usage_probe = disk_usage_probe
        self._active_events: set[str] = set()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start periodic monitoring after one synchronous startup check."""
        if self._thread is not None:
            return
        self.check_once()
        self._thread = threading.Thread(
            target=self._run,
            name="breezy-quote-tape-disk-monitor",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop periodic monitoring and wait briefly for the thread to exit."""
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5)
            self._thread = None

    def check_once(self) -> None:
        """Probe once and emit threshold transition logs."""
        active_events: set[str] = set()
        try:
            usage = self._disk_usage_probe(self._config.catalog_root)
            self._check_free_space(usage, active_events)
            self._check_largest_tape_file(active_events)
        except Exception as exc:  # noqa: BLE001 - monitor failures must be loud and non-fatal
            self._log_event(
                active_events,
                "disk_monitor_probe_failed",
                logging.ERROR,
                "quote_tape_disk_monitor event=disk_monitor_probe_failed error=%r",
                exc,
            )
        self._log_recovered(active_events)
        self._active_events = active_events

    def _run(self) -> None:
        while not self._stop.wait(self._config.check_interval_seconds):
            self.check_once()

    def _check_free_space(self, usage: DiskUsage, active_events: set[str]) -> None:
        if usage.free <= self._config.min_free_bytes_error:
            self._log_event(
                active_events,
                "free_space_error",
                logging.ERROR,
                "quote_tape_disk_monitor event=free_space_error free_bytes=%d "
                "threshold_bytes=%d total_bytes=%d used_bytes=%d catalog_root=%s",
                usage.free,
                self._config.min_free_bytes_error,
                usage.total,
                usage.used,
                self._config.catalog_root,
            )
        elif usage.free <= self._config.min_free_bytes_warning:
            self._log_event(
                active_events,
                "free_space_warning",
                logging.WARNING,
                "quote_tape_disk_monitor event=free_space_warning free_bytes=%d "
                "threshold_bytes=%d total_bytes=%d used_bytes=%d catalog_root=%s",
                usage.free,
                self._config.min_free_bytes_warning,
                usage.total,
                usage.used,
                self._config.catalog_root,
            )

    def _check_largest_tape_file(self, active_events: set[str]) -> None:
        tape_file = self._largest_tape_file()
        if tape_file is None:
            return

        relative_path = self._relative_path(tape_file.path)
        if tape_file.size_bytes >= self._config.max_file_bytes_error:
            self._log_event(
                active_events,
                "tape_file_size_error",
                logging.ERROR,
                "quote_tape_disk_monitor event=tape_file_size_error file=%s "
                "size_bytes=%d threshold_bytes=%d catalog_root=%s",
                relative_path,
                tape_file.size_bytes,
                self._config.max_file_bytes_error,
                self._config.catalog_root,
            )
        elif tape_file.size_bytes >= self._config.max_file_bytes_warning:
            self._log_event(
                active_events,
                "tape_file_size_warning",
                logging.WARNING,
                "quote_tape_disk_monitor event=tape_file_size_warning file=%s "
                "size_bytes=%d threshold_bytes=%d catalog_root=%s",
                relative_path,
                tape_file.size_bytes,
                self._config.max_file_bytes_warning,
                self._config.catalog_root,
            )

    def _largest_tape_file(self) -> _TapeFile | None:
        live_root = self._config.catalog_root / "live"
        if not live_root.exists():
            return None

        largest: _TapeFile | None = None
        for path in live_root.rglob("*.feather"):
            if not path.is_file():
                continue
            size = path.stat().st_size
            if largest is None or size > largest.size_bytes:
                largest = _TapeFile(path=path, size_bytes=size)
        return largest

    def _relative_path(self, path: Path) -> str:
        try:
            return path.relative_to(self._config.catalog_root).as_posix()
        except ValueError:  # pragma: no cover - defensive
            return path.as_posix()

    def _log_event(
        self,
        active_events: set[str],
        event: str,
        level: int,
        message: str,
        *args: object,
    ) -> None:
        active_events.add(event)
        if event not in self._active_events:
            logger.log(level, message, *args)

    def _log_recovered(self, active_events: set[str]) -> None:
        for event in self._active_events - active_events:
            logger.info("quote_tape_disk_monitor event=%s recovered", event)
