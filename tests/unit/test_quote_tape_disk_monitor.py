"""Disk-headroom monitor for the venue quote-tape recorder."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from breezy.runtime.quote_tape_disk_monitor import (
    DiskUsage,
    QuoteTapeDiskMonitor,
    QuoteTapeDiskMonitorConfig,
)


def _config(root: Path) -> QuoteTapeDiskMonitorConfig:
    return QuoteTapeDiskMonitorConfig(
        catalog_root=root,
        min_free_bytes_warning=1_000,
        min_free_bytes_error=500,
        max_file_bytes_warning=2_000,
        max_file_bytes_error=3_000,
        check_interval_seconds=30,
    )


def _usage(free: int) -> DiskUsage:
    used = 10_000 - free
    return DiskUsage(total=10_000, used=used, free=free)


def _monitor(root: Path, *, free: int) -> QuoteTapeDiskMonitor:
    return QuoteTapeDiskMonitor(
        _config(root),
        disk_usage_probe=lambda path: _usage(free),
    )


def _messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records]


def test_monitor_is_quiet_with_normal_headroom(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "live" / "instance-1").mkdir(parents=True)
    (tmp_path / "live" / "instance-1" / "quote_tick.feather").write_bytes(b"x" * 100)
    monitor = _monitor(tmp_path, free=5_000)

    with caplog.at_level(logging.WARNING, logger="breezy.runtime.quote_tape_disk_monitor"):
        monitor.check_once()

    assert caplog.records == []


def test_low_free_space_warning_is_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    monitor = _monitor(tmp_path, free=800)

    with caplog.at_level(logging.WARNING, logger="breezy.runtime.quote_tape_disk_monitor"):
        monitor.check_once()

    assert any(record.levelno == logging.WARNING for record in caplog.records)
    assert any("free_space_warning" in message for message in _messages(caplog))


def test_low_free_space_error_is_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    monitor = _monitor(tmp_path, free=400)

    with caplog.at_level(logging.ERROR, logger="breezy.runtime.quote_tape_disk_monitor"):
        monitor.check_once()

    assert any(record.levelno == logging.ERROR for record in caplog.records)
    assert any("free_space_error" in message for message in _messages(caplog))


def test_large_current_tape_file_warning_is_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    stream_dir = tmp_path / "live" / "instance-1" / "quote_tick"
    stream_dir.mkdir(parents=True)
    active_file = stream_dir / "tc-temp_100.feather"
    active_file.write_bytes(b"x" * 2_500)
    monitor = _monitor(tmp_path, free=5_000)

    with caplog.at_level(logging.WARNING, logger="breezy.runtime.quote_tape_disk_monitor"):
        monitor.check_once()

    assert any(record.levelno == logging.WARNING for record in caplog.records)
    assert any("tape_file_size_warning" in message for message in _messages(caplog))
    assert any(active_file.name in message for message in _messages(caplog))


def test_large_current_tape_file_error_is_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    stream_dir = tmp_path / "live" / "instance-1" / "quote_tick"
    stream_dir.mkdir(parents=True)
    active_file = stream_dir / "tc-temp_100.feather"
    active_file.write_bytes(b"x" * 3_500)
    monitor = _monitor(tmp_path, free=5_000)

    with caplog.at_level(logging.ERROR, logger="breezy.runtime.quote_tape_disk_monitor"):
        monitor.check_once()

    assert any(record.levelno == logging.ERROR for record in caplog.records)
    assert any("tape_file_size_error" in message for message in _messages(caplog))


def test_recovery_is_logged_after_threshold_clears(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    free_values = iter([400, 5_000])
    monitor = QuoteTapeDiskMonitor(
        _config(tmp_path),
        disk_usage_probe=lambda path: _usage(next(free_values)),
    )

    with caplog.at_level(logging.INFO, logger="breezy.runtime.quote_tape_disk_monitor"):
        monitor.check_once()
        monitor.check_once()

    assert any("free_space_error" in message for message in _messages(caplog))
    assert any("recovered" in message for message in _messages(caplog))
