"""The recorder's evidence-only stop hook (AUT-1 plan r12 section 3.10.2, X-4).

Runs as ``ExecStopPost=`` of ``breezy-quote-tape.service`` through the shared sandbox wrapper
(row ``breezy-quote-tape.stop-hook``, which binds only ``evidence/capture/stall/`` and
``health/recorder_watchdog/``). On ``SERVICE_RESULT=watchdog`` it writes the write-once stall
record and rewrites the trading day's ``recorder_watchdog/v1`` count. On any other result (the
09:00Z rotate's clean ``try-restart`` is ``success``) it does nothing and exits 0.

It sends NO alert: the per-kill page is AUT-6's ``OnFailure=`` notifier (X-4) and the storm
escalation is AUT-6's (X-6). This module therefore imports no alert sender and no venue
adapter (a wrapped unit has no import path to them, E-7 rule 2). Every failure path logs
``RECORDER_HOOK_FAILED`` to stderr (the recorder's journal) and exits 0, because a hook outcome
may never change the unit's ``Result`` or its restart.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import sys
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

from breezy.persistence.autonomy.paths import default_data_root

UNIT: Final = "breezy-quote-tape.service"
RESULT_WATCHDOG: Final = "watchdog"
CAUSE_WATCHDOG: Final = "watchdog"
SCHEMA: Final = "recorder_watchdog/v1"
STALL_RELATIVE: Final = Path("evidence") / "capture" / "stall"
HEALTH_RELATIVE: Final = Path("health") / "recorder_watchdog"
HEALTH_FILE: Final = "polymarket_us.json"
LOCK_FILE: Final = "hook.lock"
STALL_SUFFIX: Final = "_recorder_watchdog.json"
#: The trading day runs [16:45Z, next 16:45Z) (ARCH 4.5).
TRADING_DAY_START_UTC: Final = (16, 45)
LOCK_TIMEOUT_S: Final = 5.0
_LOCK_POLL_S: Final = 0.05
_INVOCATION_ID_RE: Final = re.compile(r"[0-9a-f]{32}")
_NS: Final = 1_000_000_000
_FILE_MODE: Final = 0o600
_DIR_MODE: Final = 0o700

EX_OK: Final = 0


class HookError(Exception):
    """A hook failure with a stable ``cause`` token; always ends as a logged exit 0."""

    def __init__(self, cause: str) -> None:
        super().__init__(cause)
        self.cause = cause


def trading_day_bounds_ns(detected_ns: int) -> tuple[str, int, int]:
    """``(trading_date, start_ns, end_ns)`` of the trading day containing ``detected_ns``."""
    moment = datetime.fromtimestamp(detected_ns / _NS, tz=UTC)
    hour, minute = TRADING_DAY_START_UTC
    start = moment.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if moment < start:
        start -= timedelta(days=1)
    end = start + timedelta(days=1)
    return start.date().isoformat(), int(start.timestamp()) * _NS, int(end.timestamp()) * _NS


_DIR_FLAGS: Final = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _open_dir(path: Path) -> int:
    return os.open(path, _DIR_FLAGS)


def _open_child_dir(parent_fd: int, name: str) -> int:
    """Create ``name`` under ``parent_fd`` (``mkdir`` with ``dir_fd``), then open it nofollow."""
    try:
        os.mkdir(name, _DIR_MODE, dir_fd=parent_fd)
    except FileExistsError:
        pass
    return os.open(name, _DIR_FLAGS, dir_fd=parent_fd)


def _write_once(dir_fd: int, name: str, payload: bytes) -> bool:
    """Atomic write-once: temp file, ``os.link`` to the final name, unlink the temp.

    ``False`` when the record already exists (``EEXIST``). A crash leaves either no record or a
    complete one, never a partial file under the final name.
    """
    tmp = f".{name}.{os.getpid()}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(tmp, flags, _FILE_MODE, dir_fd=dir_fd)
    try:
        try:
            os.write(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)
        try:
            os.link(tmp, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd, follow_symlinks=False)
        except FileExistsError:
            return False
        os.fsync(dir_fd)
        return True
    finally:
        try:
            os.unlink(tmp, dir_fd=dir_fd)
        except FileNotFoundError:
            pass


def _atomic_replace(dir_fd: int, name: str, payload: bytes) -> None:
    tmp = f".{name}.{os.getpid()}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(tmp, flags, _FILE_MODE, dir_fd=dir_fd)
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.rename(tmp, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
    os.fsync(dir_fd)


def _acquire_lock(dir_fd: int, timeout_s: float, sleep: Callable[[float], None]) -> int:
    fd = os.open(
        LOCK_FILE, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, _FILE_MODE, dir_fd=dir_fd
    )
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except BlockingIOError:
            if time.monotonic() >= deadline:
                os.close(fd)
                raise HookError("lock_timeout") from None
            sleep(_LOCK_POLL_S)


def _observation(record: Mapping[str, object]) -> str:
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _stall_record(
    *, result: str, invocation_id: str, exit_code: str, exit_status: str, detected_ns: int
) -> dict[str, object]:
    fields: dict[str, object] = {
        "unit": UNIT,
        "cause": CAUSE_WATCHDOG,
        "result": result,
        "invocation_id": invocation_id,
        "exit_code": exit_code,
        "exit_status": exit_status,
        "detected_ns": detected_ns,
    }
    return {**fields, "observation_sha256": _observation(fields)}


def _count_trading_day(stall_root: Path, start_ns: int, end_ns: int) -> tuple[int, int, str]:
    """``(kills, last_ns, last_invocation_id)`` from the record NAMES in the day's two dates."""
    found: list[tuple[int, str]] = []
    first = datetime.fromtimestamp(start_ns / _NS, tz=UTC).date()
    for offset in (0, 1):
        day_dir = stall_root / (first + timedelta(days=offset)).isoformat()
        try:
            names = os.listdir(day_dir)
        except FileNotFoundError:
            continue
        for name in names:
            stamp, _, rest = name.partition("_")
            if not stamp.isdigit() or not rest.endswith(STALL_SUFFIX):
                continue
            if start_ns <= int(stamp) < end_ns:
                found.append((int(stamp), rest[: -len(STALL_SUFFIX)]))
    if not found:
        return 0, 0, ""
    last_ns, last_id = max(found)
    return len(found), last_ns, last_id


def record_watchdog_kill(
    env: Mapping[str, str],
    *,
    data_root: Path,
    now_ns: int,
    lock_timeout_s: float = LOCK_TIMEOUT_S,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Write the stall record and the health count. Raises ``HookError`` on any failure."""
    invocation_id = env.get("INVOCATION_ID", "")
    if not invocation_id:
        raise HookError("missing_invocation_id")
    if not _INVOCATION_ID_RE.fullmatch(invocation_id):
        raise HookError("invalid_invocation_id")
    record = _stall_record(
        result=env["SERVICE_RESULT"],
        invocation_id=invocation_id,
        exit_code=env.get("EXIT_CODE", ""),
        exit_status=env.get("EXIT_STATUS", ""),
        detected_ns=now_ns,
    )
    trading_date, start_ns, end_ns = trading_day_bounds_ns(now_ns)
    stall_root = data_root / STALL_RELATIVE
    day = datetime.fromtimestamp(now_ns / _NS, tz=UTC).date().isoformat()
    try:
        root_fd = _open_dir(stall_root)
        try:
            day_fd = _open_child_dir(root_fd, day)
        finally:
            os.close(root_fd)
        try:
            _write_once(day_fd, f"{now_ns}_{invocation_id}{STALL_SUFFIX}", _dump(record))
        finally:
            os.close(day_fd)
        _rewrite_health(
            data_root, stall_root, trading_date, start_ns, end_ns, lock_timeout_s, sleep
        )
    except HookError:
        raise
    except OSError as exc:
        raise HookError(f"write_error_{type(exc).__name__}") from exc


def _dump(payload: Mapping[str, object]) -> bytes:
    return (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _rewrite_health(
    data_root: Path,
    stall_root: Path,
    trading_date: str,
    start_ns: int,
    end_ns: int,
    lock_timeout_s: float,
    sleep: Callable[[float], None],
) -> None:
    health_fd = _open_dir(data_root / HEALTH_RELATIVE)
    try:
        lock_fd = _acquire_lock(health_fd, lock_timeout_s, sleep)
        try:
            kills, last_ns, last_id = _count_trading_day(stall_root, start_ns, end_ns)
            health = {
                "schema": SCHEMA,
                "watchdog_kills_trading_day": kills,
                "last_watchdog_kill_ns": last_ns,
                "last_invocation_id": last_id,
                "trading_date": trading_date,
            }
            _atomic_replace(health_fd, HEALTH_FILE, _dump(health))
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
    finally:
        os.close(health_fd)


def _log_failure(cause: str, invocation_id: str) -> None:
    if not invocation_id:
        ident = "unknown"
    elif _INVOCATION_ID_RE.fullmatch(invocation_id):
        ident = invocation_id
    else:
        ident = "invalid"
    sys.stderr.write(f"ERROR RECORDER_HOOK_FAILED cause={cause} invocation_id={ident}\n")
    sys.stderr.flush()


def run_hook(
    env: Mapping[str, str],
    *,
    data_root: Path | None = None,
    now_ns: int | None = None,
    lock_timeout_s: float = LOCK_TIMEOUT_S,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """The hook body. Always returns 0: no outcome may change the unit's result."""
    result = env.get("SERVICE_RESULT", "")
    invocation_id = env.get("INVOCATION_ID", "")
    if not result:
        _log_failure("missing_service_result", invocation_id)
        return EX_OK
    if result != RESULT_WATCHDOG:
        return EX_OK
    try:
        record_watchdog_kill(
            env,
            data_root=default_data_root() if data_root is None else data_root,
            now_ns=time.time_ns() if now_ns is None else now_ns,
            lock_timeout_s=lock_timeout_s,
            sleep=sleep,
        )
    except HookError as exc:
        _log_failure(exc.cause, invocation_id)
    except Exception as exc:  # noqa: BLE001 - the hook must exit 0 whatever happens
        _log_failure(f"unexpected_{type(exc).__name__}", invocation_id)
    return EX_OK


def main() -> int:
    return run_hook(os.environ)


if __name__ == "__main__":
    sys.exit(main())
