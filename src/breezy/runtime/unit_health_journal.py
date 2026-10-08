"""The journal reads of the AUT-6 unit health pass (plan r15 section 3.9; F2, F6).

``journalctl --user -o json`` is the one in-row read that works inside the health bwrap (V-6). Every
call is an argv list (no shell), bounded by a subprocess timeout the caller derives from the pass
budget, and capped in output size. Any non-zero exit, timeout, oversize output or unparseable line
raises ``JournalError``: the pass turns that into UNKNOWN, never into "no failures".
"""

from __future__ import annotations

import json
import os
import re
import select
import signal
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final, Protocol

from breezy.runtime.unit_health_model import (
    MESSAGE_ID_UNIT_FAILED,
    MESSAGE_ID_UNIT_RESOURCES,
    FailureEntry,
    parse_failure_line,
)

JOURNALCTL: Final = "/usr/bin/journalctl"
#: A single call never runs longer than this, whatever budget is left (F6).
PER_CALL_CAP_S: Final = 20.0
#: Below this much remaining budget the pass stops instead of starting a call.
MIN_CALL_S: Final = 1.0
MAX_OUTPUT_BYTES: Final = 16 * 1024 * 1024
_CURSOR_PREFIX: Final = "-- cursor: "
_INVOCATION_RE: Final = re.compile(r"[0-9a-f]{32}")
_ENV: Final = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "SYSTEMD_PAGER": ""}
_CHUNK: Final = 1 << 16


class JournalError(Exception):
    """A journal read failed; ``reason`` is a short code (``rc=1``, ``timed_out`` ...)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class RunResult:
    rc: int
    stdout: str
    timed_out: bool
    oversize: bool


Run = Callable[[Sequence[str], float], RunResult]


@dataclass(frozen=True, slots=True)
class JournalBatch:
    entries: tuple[FailureEntry, ...]
    end_cursor: str | None


@dataclass(frozen=True, slots=True)
class Resources:
    """The per-invocation resource-usage entry: CPU time and the memory peaks."""

    cpu_usage_ns: int | None
    memory_peak: int | None
    memory_swap_peak: int | None


class JournalSource(Protocol):
    def failures(
        self, *, after_cursor: str | None, since_s: int | None, timeout_s: float
    ) -> JournalBatch: ...

    def failures_for_invocation(
        self, invocation_id: str, *, timeout_s: float
    ) -> tuple[FailureEntry, ...]: ...

    def resources_for_invocation(
        self, invocation_id: str, *, timeout_s: float
    ) -> Resources | None: ...


def _kill_group(pid: int) -> None:
    if pid <= 1 or pid == os.getpgrp():
        return
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass  # already gone


def run_bounded(argv: Sequence[str], timeout_s: float) -> RunResult:
    """Run ``argv`` in its own process group; on timeout or oversize output kill the group."""
    try:
        proc = subprocess.Popen(
            list(argv),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=_ENV,
            start_new_session=True,
            close_fds=True,
        )
    except OSError:
        return RunResult(127, "", False, False)
    assert proc.stdout is not None
    fd = proc.stdout.fileno()
    deadline = time.monotonic() + timeout_s
    chunks: list[bytes] = []
    total = 0
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([fd], [], [], remaining)[0]:
                _kill_group(proc.pid)
                proc.wait(timeout=1.0)
                return RunResult(-signal.SIGKILL, "", True, False)
            chunk = os.read(fd, _CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_OUTPUT_BYTES:
                _kill_group(proc.pid)
                proc.wait(timeout=1.0)
                return RunResult(-signal.SIGKILL, "", False, True)
            chunks.append(chunk)
        rc = proc.wait(timeout=max(deadline - time.monotonic(), 0.1))
    except subprocess.TimeoutExpired:
        _kill_group(proc.pid)
        return RunResult(-signal.SIGKILL, "", True, False)
    finally:
        proc.stdout.close()
    return RunResult(rc, b"".join(chunks).decode("utf-8", errors="replace"), False, False)


def _checked(result: RunResult) -> str:
    if result.timed_out:
        raise JournalError("timed_out")
    if result.oversize:
        raise JournalError("oversize")
    if result.rc != 0:
        raise JournalError(f"rc={result.rc}")
    return result.stdout


def _failure_entries(text: str) -> tuple[tuple[FailureEntry, ...], str | None]:
    entries: list[FailureEntry] = []
    end_cursor: str | None = None
    for line in text.splitlines():
        if not line.strip():
            continue
        if line.startswith(_CURSOR_PREFIX):
            end_cursor = line[len(_CURSOR_PREFIX) :].strip() or None
        elif line.startswith("-- "):
            continue  # "-- No entries --"
        else:
            try:
                entries.append(parse_failure_line(line))
            except ValueError:
                raise JournalError("parse") from None
    return tuple(entries), end_cursor


def _int_field(raw: dict[str, object], key: str) -> int | None:
    value = raw.get(key)
    return int(value) if isinstance(value, str) and value.isdigit() else None


class SubprocessJournal:
    """The production ``JournalSource``: ``journalctl --user -o json`` via ``run``."""

    def __init__(self, run: Run = run_bounded) -> None:
        self._run = run

    def _base(self) -> list[str]:
        return [JOURNALCTL, "--user", "-o", "json", "--no-pager"]

    def failures(
        self, *, after_cursor: str | None, since_s: int | None, timeout_s: float
    ) -> JournalBatch:
        argv = [*self._base(), "--show-cursor"]
        if after_cursor is not None:
            argv.append(f"--after-cursor={after_cursor}")
        elif since_s is not None:
            argv.append(f"--since=@{since_s}")
        argv.append(f"MESSAGE_ID={MESSAGE_ID_UNIT_FAILED}")
        entries, end_cursor = _failure_entries(_checked(self._run(argv, timeout_s)))
        return JournalBatch(entries, end_cursor)

    def failures_for_invocation(
        self, invocation_id: str, *, timeout_s: float
    ) -> tuple[FailureEntry, ...]:
        if not _INVOCATION_RE.fullmatch(invocation_id):
            raise JournalError("invocation_id")
        argv = [
            *self._base(),
            f"MESSAGE_ID={MESSAGE_ID_UNIT_FAILED}",
            f"USER_INVOCATION_ID={invocation_id}",
        ]
        entries, _ = _failure_entries(_checked(self._run(argv, timeout_s)))
        return entries

    def resources_for_invocation(self, invocation_id: str, *, timeout_s: float) -> Resources | None:
        if not _INVOCATION_RE.fullmatch(invocation_id):
            raise JournalError("invocation_id")
        argv = [
            *self._base(),
            f"MESSAGE_ID={MESSAGE_ID_UNIT_RESOURCES}",
            f"USER_INVOCATION_ID={invocation_id}",
        ]
        lines = [x for x in _checked(self._run(argv, timeout_s)).splitlines() if x.strip()]
        if not lines:
            return None
        try:
            raw = json.loads(lines[-1])
        except ValueError:
            raise JournalError("parse") from None
        if not isinstance(raw, dict):
            raise JournalError("parse")
        return Resources(
            _int_field(raw, "CPU_USAGE_NSEC"),
            _int_field(raw, "MEMORY_PEAK"),
            _int_field(raw, "MEMORY_SWAP_PEAK"),
        )
