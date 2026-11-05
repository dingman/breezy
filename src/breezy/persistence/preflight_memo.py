"""Memoized feather preflight for quote-tape ingest."""

from __future__ import annotations

import contextlib
import json
import logging
import os
from pathlib import Path
from typing import Any

from breezy.persistence import feather_preflight
from breezy.persistence.feather_preflight import (
    DEFAULT_SUBDIRECTORY,
    FeatherFileReport,
    FeatherStatus,
    PreflightError,
    PreflightReport,
    _instance_dir,
    iter_feather_files,
    list_instance_ids,
)

logger = logging.getLogger(__name__)

MEMO_VERSION = 1
MEMO_FILENAME = ".preflight-memo-v1.json"

_STAT_FIELDS = ("st_dev", "st_ino", "st_size", "st_mtime_ns")


def _stat_key(stat: os.stat_result) -> dict[str, int]:
    return {field: int(getattr(stat, field)) for field in _STAT_FIELDS}


def _stat_matches(entry: object, stat: os.stat_result) -> bool:
    if not isinstance(entry, dict):
        return False
    return all(entry.get(field) == int(getattr(stat, field)) for field in _STAT_FIELDS)


def _report_to_json(report: FeatherFileReport) -> dict[str, object]:
    return {
        "status": report.status.value,
        "size_bytes": report.size_bytes,
        "readable_bytes": report.readable_bytes,
        "batches": report.batches,
        "rows": report.rows,
        "schema_readable": report.schema_readable,
        "ended_mid_message": report.ended_mid_message,
        "end_of_stream_marker": report.end_of_stream_marker,
        "mtime_ns": report.mtime_ns,
        "failure": report.failure,
    }


def _report_from_json(path: Path, payload: object) -> FeatherFileReport | None:
    if not isinstance(payload, dict):
        return None
    bool_fields = ("schema_readable", "ended_mid_message", "end_of_stream_marker")
    if not all(isinstance(payload.get(field), bool) for field in bool_fields):
        return None
    try:
        return FeatherFileReport(
            path=path,
            status=FeatherStatus(str(payload["status"])),
            size_bytes=int(payload["size_bytes"]),
            readable_bytes=int(payload["readable_bytes"]),
            batches=int(payload["batches"]),
            rows=int(payload["rows"]),
            schema_readable=payload["schema_readable"],
            ended_mid_message=payload["ended_mid_message"],
            end_of_stream_marker=payload["end_of_stream_marker"],
            mtime_ns=int(payload["mtime_ns"]),
            failure=None if payload["failure"] is None else str(payload["failure"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _empty_memo() -> dict[str, object]:
    return {"version": MEMO_VERSION, "files": {}}


def _load_memo(path: Path) -> tuple[dict[str, object], bool]:
    try:
        payload = json.loads(path.read_text())
    except FileNotFoundError:
        return _empty_memo(), False
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("ignoring preflight memo %s: %s", path, exc)
        return _empty_memo(), False
    if not isinstance(payload, dict) or payload.get("version") != MEMO_VERSION:
        logger.warning("ignoring preflight memo %s: unsupported version", path)
        return _empty_memo(), False
    if not isinstance(payload.get("files"), dict):
        logger.warning("ignoring preflight memo %s: malformed files map", path)
        return _empty_memo(), False
    return payload, True


def _fsync_dir_best_effort(directory: Path) -> None:
    """Fsync a directory entry after a rename. Best effort: never raises."""
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _write_memo(
    path: Path,
    payload: dict[str, object],
    previous: dict[str, object],
    *,
    previous_valid: bool,
) -> None:
    """Persist the memo atomically. The memo is an optimization only: a
    failure here is logged and swallowed, never allowed to fail ingest.
    """
    if previous_valid and path.exists() and payload == previous:
        return
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    try:
        with tmp.open("w") as handle:
            handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        _fsync_dir_best_effort(path.parent)
    except OSError as exc:
        logger.warning("failed to write preflight memo %s: %s", path, exc)
        with contextlib.suppress(OSError):
            tmp.unlink()


def _memo_entry(
    memo_files: dict[str, object],
    rel_path: str,
    path: Path,
    stat: os.stat_result,
) -> FeatherFileReport | None:
    entry = memo_files.get(rel_path)
    if not isinstance(entry, dict):
        return None
    if not _stat_matches(entry.get("stat"), stat):
        return None
    return _report_from_json(path, entry.get("report"))


def scan_instance_memoized(
    catalog_root: Path,
    instance_id: str,
    subdirectory: str = DEFAULT_SUBDIRECTORY,
    *,
    open_files: frozenset[Path],
) -> PreflightReport:
    """Inspect an instance, reusing reports only for unchanged closed files.

    Cold scans go through ``feather_preflight.inspect_feather_file`` by
    module attribute (not a bound import) so existing spies on that seam keep
    working unmodified. Files in ``open_files`` are always inspected cold and
    are deliberately left out of the rewritten memo, including when they
    were previously memoized. A closed file is only memoized when the stat
    taken immediately before the scan matches the stat taken immediately
    after: a mismatch means the file changed while being decoded, and caching
    it under either stat would be recording a key that is already wrong.
    """
    directory = _instance_dir(catalog_root, instance_id, subdirectory)
    if not directory.is_dir():
        raise PreflightError(
            f"no such run instance {instance_id!r} under "
            f"{catalog_root / subdirectory} (known: "
            f"{', '.join(list_instance_ids(catalog_root, subdirectory)) or 'none'})"
        )

    memo_path = directory / MEMO_FILENAME
    previous, previous_valid = _load_memo(memo_path)
    previous_files = previous["files"]
    assert isinstance(previous_files, dict)

    reports: list[FeatherFileReport] = []
    next_files: dict[str, dict[str, Any]] = {}

    for path in iter_feather_files(directory):
        rel_path = path.relative_to(directory).as_posix()
        if path in open_files:
            reports.append(feather_preflight.inspect_feather_file(path))
            continue

        try:
            stat_before = path.stat()
        except OSError as exc:
            raise PreflightError(f"cannot stat {path}: {exc}") from exc

        cached = _memo_entry(previous_files, rel_path, path, stat_before)
        if cached is not None:
            reports.append(cached)
            next_files[rel_path] = {
                "stat": _stat_key(stat_before),
                "report": _report_to_json(cached),
            }
            continue

        report = feather_preflight.inspect_feather_file(path)
        reports.append(report)

        try:
            stat_after = path.stat()
        except OSError as exc:
            raise PreflightError(f"cannot stat {path}: {exc}") from exc

        if _stat_key(stat_before) == _stat_key(stat_after):
            next_files[rel_path] = {
                "stat": _stat_key(stat_before),
                "report": _report_to_json(report),
            }
        # else: the file changed while being decoded. Never memoize a report
        # under a stat that no longer describes it; the next run rescans.

    if not reports:
        raise PreflightError(
            f"run instance {instance_id!r} holds no .feather files under {directory}; "
            f"refusing to report a clean pass over nothing"
        )

    next_payload: dict[str, object] = {"version": MEMO_VERSION, "files": next_files}
    _write_memo(memo_path, next_payload, previous, previous_valid=previous_valid)
    return PreflightReport(
        catalog_root=catalog_root,
        subdirectory=subdirectory,
        instance_id=instance_id,
        files=tuple(reports),
    )
