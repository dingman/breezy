"""EDGE-6b: memoized quote-tape preflight without freezing live files."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pytest
from nautilus_trader.model.data import QuoteTick

import breezy.runtime.quote_tape_ingest_cli as ingest_cli_module
import breezy.runtime.quote_tape_ingest_core as ingest_core_module
from breezy.persistence import feather_preflight, preflight_memo
from breezy.persistence.feather_preflight import (
    FeatherFileReport,
    FeatherStatus,
    PreflightReport,
    inspect_feather_file,
    inspect_feather_file_with_stat,
    scan_instance,
)
from breezy.persistence.preflight_memo import (
    MEMO_FILENAME,
    MEMO_VERSION,
    scan_instance_memoized,
)
from breezy.runtime.quote_tape_ingest_cli import run, run_ingest
from tests.unit.test_quote_tape_ingest_cli import INSTANCE, _never_active, _touch

INSTANCE_ID = "instance-1"
SCHEMA = pa.schema([pa.field("value", pa.int64()), pa.field("ts_init", pa.int64())])


def _write_stream(path: Path, *, batches: int, rows_per_batch: int = 10, close: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sink = pa.OSFile(str(path), "wb")
    writer = pa.ipc.new_stream(sink, SCHEMA)
    for index in range(batches):
        writer.write_batch(
            pa.record_batch(
                [
                    pa.array([index] * rows_per_batch),
                    pa.array(list(range(rows_per_batch))),
                ],
                schema=SCHEMA,
            )
        )
    if close:
        writer.close()
    sink.close()


def _tape(root: Path, name: str = "quote_tick_1.feather") -> Path:
    return root / "live" / INSTANCE_ID / name


def _memo_path(root: Path, instance_id: str = INSTANCE_ID) -> Path:
    return root / "live" / instance_id / MEMO_FILENAME


def _load_memo(root: Path, instance_id: str = INSTANCE_ID) -> dict:
    return json.loads(_memo_path(root, instance_id).read_text())


def _dump_memo(root: Path, payload: dict, instance_id: str = INSTANCE_ID) -> None:
    _memo_path(root, instance_id).write_text(json.dumps(payload, sort_keys=True))


def _report_payload(report: PreflightReport) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            file.path.relative_to(report.catalog_root / report.subdirectory / report.instance_id),
            file.status,
            file.size_bytes,
            file.readable_bytes,
            file.batches,
            file.rows,
            file.schema_readable,
            file.ended_mid_message,
            file.end_of_stream_marker,
            file.mtime_ns,
            file.failure,
        )
        for file in report.files
    )


def _counting_scan(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    calls: list[Path] = []
    real_scan_stream = feather_preflight._scan_stream

    def scan_stream(path: Path, *, collect: bool):  # type: ignore[no-untyped-def]
        calls.append(path)
        return real_scan_stream(path, collect=collect)

    monkeypatch.setattr(feather_preflight, "_scan_stream", scan_stream)
    return calls


def _single_cached_file(root: Path) -> Path:
    path = _tape(root)
    _write_stream(path, batches=2, close=True)
    scan_instance_memoized(root, INSTANCE_ID, open_files=frozenset())
    return path


def test_memo_report_equals_cold_scan_field_for_field(tmp_path: Path) -> None:
    intact = _tape(tmp_path, "quote_tick_1.feather")
    _write_stream(intact, batches=2, close=True)
    truncated = _tape(tmp_path, "trade_tick_1.feather")
    _write_stream(truncated, batches=2, close=False)
    with truncated.open("r+b") as handle:
        handle.truncate(truncated.stat().st_size - 64)
    empty_file = _tape(tmp_path, "instrument_close_1.feather")
    empty_file.parent.mkdir(parents=True, exist_ok=True)
    empty_file.write_bytes(b"")
    _write_stream(_tape(tmp_path, "instrument_status_1.feather"), batches=0, close=True)
    unreadable = _tape(tmp_path, "mark_price_update_1.feather")
    _write_stream(unreadable, batches=1, close=True)
    unreadable.chmod(0o000)
    try:
        memoized = scan_instance_memoized(tmp_path, INSTANCE_ID, open_files=frozenset())
        cold = scan_instance(tmp_path, INSTANCE_ID)
    finally:
        unreadable.chmod(0o600)

    assert _report_payload(memoized) == _report_payload(cold)


def test_memo_hit_performs_zero_stream_decodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _single_cached_file(tmp_path)
    calls = _counting_scan(monkeypatch)

    report = scan_instance_memoized(tmp_path, INSTANCE_ID, open_files=frozenset())

    assert report.total_rows == 20
    assert calls == []


def test_memo_invalidates_on_size_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _single_cached_file(tmp_path)
    path.write_bytes(path.read_bytes() + b" ")
    calls = _counting_scan(monkeypatch)

    scan_instance_memoized(tmp_path, INSTANCE_ID, open_files=frozenset())

    assert calls == [path]


def test_memo_invalidates_on_mtime_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _single_cached_file(tmp_path)
    os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 1_000_000))
    calls = _counting_scan(monkeypatch)

    scan_instance_memoized(tmp_path, INSTANCE_ID, open_files=frozenset())

    assert calls == [path]


def test_memo_invalidates_on_inode_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _single_cached_file(tmp_path)
    payload = _load_memo(tmp_path)
    entry = next(iter(payload["files"].values()))
    entry["stat"]["st_ino"] += 1
    _dump_memo(tmp_path, payload)
    calls = _counting_scan(monkeypatch)

    scan_instance_memoized(tmp_path, INSTANCE_ID, open_files=frozenset())

    assert calls == [path]


def test_memo_invalidates_on_device_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _single_cached_file(tmp_path)
    payload = _load_memo(tmp_path)
    entry = next(iter(payload["files"].values()))
    entry["stat"]["st_dev"] += 1
    _dump_memo(tmp_path, payload)
    calls = _counting_scan(monkeypatch)

    scan_instance_memoized(tmp_path, INSTANCE_ID, open_files=frozenset())

    assert calls == [path]


def test_live_open_file_never_memoized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _tape(tmp_path)
    _write_stream(path, batches=2, close=True)
    calls = _counting_scan(monkeypatch)

    scan_instance_memoized(tmp_path, INSTANCE_ID, open_files=frozenset({path}))
    scan_instance_memoized(tmp_path, INSTANCE_ID, open_files=frozenset({path}))

    payload = _load_memo(tmp_path)
    assert calls == [path, path]
    assert payload["files"] == {}

    scan_instance_memoized(tmp_path, INSTANCE_ID, open_files=frozenset())
    assert "quote_tick_1.feather" in _load_memo(tmp_path)["files"]
    calls.clear()
    scan_instance_memoized(tmp_path, INSTANCE_ID, open_files=frozenset({path}))

    assert calls == [path]
    assert "quote_tick_1.feather" not in _load_memo(tmp_path)["files"]


def test_memo_key_is_inspect_pre_scan_stat(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A file that mutates between the pre-scan stat and the decode finishing
    must never be memoized under a stale key.

    ``scan_instance_memoized`` takes a stat immediately before calling
    ``inspect_feather_file`` and another immediately after; a mismatch means
    the file changed mid-decode, so the run declines to write any memo entry
    for it rather than caching a key that is already wrong the moment it is
    written. The next run is then forced to rescan -- the same outcome the
    original design got from storing the stale pre-scan key (it would miss
    on the very next lookup), but without ever persisting an inaccurate
    entry.
    """
    path = _tape(tmp_path)
    _write_stream(path, batches=2, close=True)
    pre_size = path.stat().st_size
    real_scan_stream = feather_preflight._scan_stream
    calls = 0

    def growing_scan(path_arg: Path, *, collect: bool):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls == 1:
            path_arg.write_bytes(path_arg.read_bytes() + b"memo growth")
        return real_scan_stream(path_arg, collect=collect)

    monkeypatch.setattr(feather_preflight, "_scan_stream", growing_scan)

    scan_instance_memoized(tmp_path, INSTANCE_ID, open_files=frozenset())

    assert "quote_tick_1.feather" not in _load_memo(tmp_path)["files"]

    scan_instance_memoized(tmp_path, INSTANCE_ID, open_files=frozenset())

    assert path.stat().st_size > pre_size
    assert calls == 2


def test_inspect_feather_file_unchanged_by_stat_seam(tmp_path: Path) -> None:
    paths = [
        _tape(tmp_path, "quote_tick_1.feather"),
        _tape(tmp_path, "trade_tick_1.feather"),
        _tape(tmp_path, "instrument_close_1.feather"),
        _tape(tmp_path, "instrument_status_1.feather"),
    ]
    _write_stream(paths[0], batches=2, close=True)
    _write_stream(paths[1], batches=2, close=False)
    with paths[1].open("r+b") as handle:
        handle.truncate(paths[1].stat().st_size - 64)
    paths[2].write_bytes(b"")
    _write_stream(paths[3], batches=0, close=True)

    for path in paths:
        report, stat = inspect_feather_file_with_stat(path)
        assert inspect_feather_file(path) == report
        assert stat.st_size == report.size_bytes
        assert stat.st_mtime_ns == report.mtime_ns


def test_memo_new_file_scanned_removed_file_dropped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = _single_cached_file(tmp_path)
    original.unlink()
    new_file = _tape(tmp_path, "trade_tick_1.feather")
    _write_stream(new_file, batches=1, close=True)
    calls = _counting_scan(monkeypatch)

    report = scan_instance_memoized(tmp_path, INSTANCE_ID, open_files=frozenset())

    assert calls == [new_file]
    assert [file.path for file in report.files] == [new_file]
    assert set(_load_memo(tmp_path)["files"]) == {"trade_tick_1.feather"}


def test_corrupt_memo_falls_back_to_cold_scan_and_warns_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    path = _tape(tmp_path)
    _write_stream(path, batches=1, close=True)
    _memo_path(tmp_path).write_text("{")
    calls = _counting_scan(monkeypatch)

    with caplog.at_level("WARNING", logger="breezy.persistence.preflight_memo"):
        report = scan_instance_memoized(tmp_path, INSTANCE_ID, open_files=frozenset())

    assert report.total_rows == 10
    assert calls == [path]
    assert sum("ignoring preflight memo" in record.message for record in caplog.records) == 1


def test_unknown_memo_version_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    path = _tape(tmp_path)
    _write_stream(path, batches=1, close=True)
    _memo_path(tmp_path).write_text(json.dumps({"version": MEMO_VERSION + 1, "files": {}}))
    calls = _counting_scan(monkeypatch)

    with caplog.at_level("WARNING", logger="breezy.persistence.preflight_memo"):
        report = scan_instance_memoized(tmp_path, INSTANCE_ID, open_files=frozenset())

    assert report.total_rows == 10
    assert calls == [path]
    assert sum("ignoring preflight memo" in record.message for record in caplog.records) == 1


def test_memo_write_is_atomic_and_skipped_when_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _single_cached_file(tmp_path)

    def fail_replace(*args: object, **kwargs: object) -> None:
        raise AssertionError("unchanged memo must not be rewritten")

    monkeypatch.setattr(preflight_memo.os, "replace", fail_replace)

    scan_instance_memoized(tmp_path, INSTANCE_ID, open_files=frozenset())


def test_memo_write_failure_does_not_fail_ingest_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _write_stream(_tape(tmp_path), batches=1, close=True)

    def fail_replace(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(preflight_memo.os, "replace", fail_replace)

    with caplog.at_level("WARNING", logger="breezy.persistence.preflight_memo"):
        report = scan_instance_memoized(tmp_path, INSTANCE_ID, open_files=frozenset())

    assert report.total_rows == 10
    assert not _memo_path(tmp_path).exists()
    assert sum("failed to write preflight memo" in record.message for record in caplog.records) == 1


def test_run_ingest_passes_open_files_to_memoized_scan_and_outcomes_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    open_path = _touch(tmp_path, INSTANCE, "quote_tick_0.feather", age_minutes=0)
    seen_open_files: list[frozenset[Path]] = []

    def spy_scan(
        catalog_root: Path,
        instance_id: str,
        subdirectory: str = "live",
        *,
        open_files: frozenset[Path],
    ) -> PreflightReport:
        seen_open_files.append(open_files)
        return PreflightReport(
            catalog_root=catalog_root,
            subdirectory=subdirectory,
            instance_id=instance_id,
            files=(
                FeatherFileReport(
                    path=open_path,
                    status=FeatherStatus.EMPTY_FILE,
                    size_bytes=0,
                    readable_bytes=0,
                    batches=0,
                    rows=0,
                    schema_readable=False,
                    ended_mid_message=False,
                    end_of_stream_marker=False,
                    mtime_ns=open_path.stat().st_mtime_ns,
                    failure=None,
                ),
            ),
        )

    monkeypatch.setattr(ingest_core_module, "scan_instance_memoized", spy_scan)

    results = run_ingest(
        tmp_path,
        data_types=(QuoteTick,),
        service_active_probe=_never_active,
        convert_fn=lambda *args: None,
    )

    assert seen_open_files == [frozenset({open_path})]
    assert results[0].outcome == "skipped-live"


def test_deadline_line_carries_rss_peak_mb_integer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(ingest_core_module, "run_ingest_definitions_first", lambda *a, **k: ())
    monkeypatch.setattr(
        ingest_cli_module.resource,
        "getrusage",
        lambda _who: SimpleNamespace(ru_maxrss=12_345),
    )

    assert run(["--catalog", str(tmp_path), "--deadline-seconds", "1"]) == 0

    out = capsys.readouterr().out
    assert "rss_peak_mb=12" in out
