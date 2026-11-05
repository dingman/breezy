"""AUT-1 WP5 stage 2b, W3: host reads, the journals and the bus snapshot.

``run_journal`` runs one of the three ``journalctl`` argv templates (r8 section 3.10; only the two
time slots are substituted, each regex-validated; 30 s timeout) and raises
``AuditInputError("journal_failed")`` on a non-zero exit, a timeout, an unreadable launch or empty
output (an empty output carries ``detail == EMPTY_OUTPUT_DETAIL`` so a caller that tolerates a quiet
journal can tell it from a real failure). ``read_recorder_props`` and ``read_ingest_exit_ns`` read
seam B's bus snapshot (``bus_snapshot_missing`` / ``bus_snapshot_stale`` are ERRORs; S2-R8).

The snapshot is CONSUMED by the first read (seam B unlinks it), so the first outcome, a snapshot or
its error, is kept for the process: ``main`` reads it FIRST, before any scan or lock wait, and every
later read returns that same outcome. The argv templates and ``AUDIT_BUS_READS`` are CONSTANTS stage
3 copies into the unit and the bwrap row: a value may be corrected, a NAME may not.

Each template has its own ``subprocess.Popen`` call whose argv is the template with the two slot
values as bare names (``since``, ``until``): ``AUT1_WRITE_AUTHORITY`` matches that shape exactly.
"""

import calendar
import datetime as dt
import json
import os
import re
import select
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any, Final, Protocol

from breezy.analysis.capture_audit_input_types import RecorderJournalEntry, RecorderProps
from breezy.analysis.capture_audit_model import AuditInputError
from breezy.runtime.autonomy_sandbox.bus_handoff import (
    BusReadResult,
    BusSnapshot,
    BusSnapshotError,
    read_bus_snapshot,
)
from breezy.runtime.autonomy_sandbox.bwrap import default_roots
from breezy.runtime.autonomy_sandbox.table import AUTONOMY_BWRAP_TABLE, BwrapRow

__all__ = [
    "AUDIT_BUS_READS",
    "AUDIT_BUS_READ_NAMES",
    "AUDIT_ROW_NAME",
    "EMPTY_OUTPUT_DETAIL",
    "INGEST_JOURNAL_ARGV",
    "JOURNAL_TIMEOUT_S",
    "RECORDER_JOURNAL_ARGV",
    "SUPERVISOR_JOURNAL_ARGV",
    "journal_slot",
    "parse_recorder_journal",
    "read_ingest_exit_ns",
    "read_recorder_props",
    "run_journal",
]

JOURNAL_TIMEOUT_S: Final[float] = 30.0
EMPTY_OUTPUT_DETAIL: Final[str] = "empty_output"
#: Literal templates; ``{since}`` and ``{until}`` are the only substituted slots.
INGEST_JOURNAL_ARGV: Final[tuple[str, ...]] = (
    "/usr/bin/journalctl",
    "--user",
    "-u",
    "breezy-quote-tape-ingest",
    "-o",
    "cat",
    "--since",
    "{since}",
    "--until",
    "{until}",
)
SUPERVISOR_JOURNAL_ARGV: Final[tuple[str, ...]] = (
    "/usr/bin/journalctl",
    "--user",
    "-u",
    "breezy-trade-supervisor",
    "-o",
    "cat",
    "--since",
    "{since}",
    "--until",
    "{until}",
)
RECORDER_JOURNAL_ARGV: Final[tuple[str, ...]] = (
    "/usr/bin/journalctl",
    "--user",
    "-u",
    "breezy-quote-tape.service",
    "-o",
    "json",
    "--since",
    "{since}",
    "--until",
    "{until}",
)
#: The audit row's two bus reads (S2-R8): the recorder's watchdog properties and the ingest unit's
#: last exit time. The snapshot is read FIRST in ``main``, before any scan or lock wait.
AUDIT_BUS_READS: Final[tuple[tuple[str, ...], ...]] = (
    ("-p", "WatchdogUSec,NotifyAccess,Type", "--", "breezy-quote-tape.service"),
    ("-p", "ExecMainExitTimestamp", "--", "breezy-quote-tape-ingest.service"),
)
#: The ``BusRead`` names of the two reads above, in the same order (stage 3 builds the row).
AUDIT_BUS_READ_NAMES: Final[tuple[str, str]] = ("recorder_show", "ingest_show")
AUDIT_ROW_NAME: Final[str] = "breezy-capture-audit"

#: ``YYYY-MM-DD HH:MM:SS UTC``: journalctl reads a bare time in the host zone, so every slot names
#: UTC explicitly.
_SLOT_RE: Final[re.Pattern[str]] = re.compile(
    r"\A[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2} UTC\Z"
)
_ARMED_KEYS: Final[tuple[str, ...]] = ("WatchdogUSec", "NotifyAccess", "Type")
_TIMESPAN_RE: Final[re.Pattern[str]] = re.compile(r"(\d+(?:\.\d+)?)\s*([a-zµ]*)")
_US_PER_UNIT: Final[Mapping[str, int]] = {
    "": 1,
    "us": 1,
    "µs": 1,
    "ms": 1_000,
    "s": 1_000_000,
    "sec": 1_000_000,
    "min": 60_000_000,
    "h": 3_600_000_000,
    "hr": 3_600_000_000,
    "d": 86_400_000_000,
    "w": 604_800_000_000,
}
_TIMESTAMP_RE: Final[re.Pattern[str]] = re.compile(
    r"\A(?:[A-Z][a-z]{2} )?(\d{4})-(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d)(?: (UTC|GMT))?\Z"
)
_US_NS: Final[int] = 1_000
_S_NS: Final[int] = 1_000_000_000
_MAX_JOURNAL_BYTES: Final[int] = 256 * 1024 * 1024
_READ_CHUNK_BYTES: Final[int] = 64 * 1024


def journal_slot(epoch_s: int) -> str:
    """A time slot value for ``epoch_s`` (UTC seconds), in the one accepted shape."""
    return dt.datetime.fromtimestamp(epoch_s, dt.UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _journal_failed(detail: str) -> AuditInputError:
    return AuditInputError("journal_failed", detail)


def _checked_slots(since: str, until: str) -> None:
    if _SLOT_RE.fullmatch(since) is None or _SLOT_RE.fullmatch(until) is None:
        raise _journal_failed("bad_time_slot")


class _Process(Protocol):
    """The part of a launched ``journalctl`` this module drives."""

    stdout: Any

    def poll(self) -> int | None: ...
    def kill(self) -> None: ...
    def wait(self, timeout: float | None = None) -> int: ...


def _run_template(template: Sequence[str], since: str, until: str) -> _Process:
    """Run the one template ``template`` names. One call site per template: the lint row for each
    matches that call's argv exactly (the slots as bare names)."""
    key = tuple(template)
    if key == INGEST_JOURNAL_ARGV:
        return subprocess.Popen(
            [
                "/usr/bin/journalctl",
                "--user",
                "-u",
                "breezy-quote-tape-ingest",
                "-o",
                "cat",
                "--since",
                since,
                "--until",
                until,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    if key == SUPERVISOR_JOURNAL_ARGV:
        return subprocess.Popen(
            [
                "/usr/bin/journalctl",
                "--user",
                "-u",
                "breezy-trade-supervisor",
                "-o",
                "cat",
                "--since",
                since,
                "--until",
                until,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    if key == RECORDER_JOURNAL_ARGV:
        return subprocess.Popen(
            [
                "/usr/bin/journalctl",
                "--user",
                "-u",
                "breezy-quote-tape.service",
                "-o",
                "json",
                "--since",
                since,
                "--until",
                until,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    raise _journal_failed("unknown_template")


def _read_bounded(proc: _Process, timeout_s: float) -> bytes:
    """The child's stdout, read in chunks and counted in bytes: more than ``_MAX_JOURNAL_BYTES``
    raises ``oversize`` while reading (S2-R31), never after buffering the whole journal."""
    deadline = time.monotonic() + timeout_s
    stream = proc.stdout
    fd = stream.fileno()
    chunks: list[bytes] = []
    total = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([stream], [], [], remaining)[0]:
            raise _journal_failed("timeout")
        chunk = os.read(fd, _READ_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > _MAX_JOURNAL_BYTES:
            raise _journal_failed("oversize")
        chunks.append(chunk)
    try:
        returncode = proc.wait(timeout=max(deadline - time.monotonic(), 0.001))
    except Exception:  # noqa: BLE001 - a wait that does not finish is the timeout failure
        raise _journal_failed("timeout") from None
    if returncode != 0:
        raise _journal_failed(f"exit_{returncode}")
    return b"".join(chunks)


def _drive(proc: _Process, timeout_s: float) -> str:
    try:
        return _read_bounded(proc, timeout_s).decode("utf-8")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        proc.stdout.close()


def run_journal(
    template: Sequence[str], since: str, until: str, *, timeout_s: float = JOURNAL_TIMEOUT_S
) -> str:
    """The journal text for ``[since, until]`` through a literal argv template."""
    _checked_slots(since, until)
    try:
        text = _drive(_run_template(template, since, until), timeout_s)
    except AuditInputError:
        raise
    except Exception as exc:  # noqa: BLE001 - any launch or read failure is a journal failure
        raise _journal_failed(type(exc).__name__) from None
    if not text.strip():
        raise _journal_failed(EMPTY_OUTPUT_DETAIL)
    return text


def _micros(entry: Mapping[str, object], key: str) -> int | None:
    value = entry.get(key)
    return int(value) * _US_NS if isinstance(value, str) and value.isdigit() else None


def _text(entry: Mapping[str, object], *keys: str) -> str:
    for key in keys:
        value = entry.get(key)
        if isinstance(value, str):
            return value
    return ""


def parse_recorder_journal(text: str) -> tuple[RecorderJournalEntry, ...]:
    """The ``UNIT_RESULT`` entries of the recorder's ``-o json`` journal (the only ones leg W
    reads), in time order. An unparseable line is ``journal_failed``."""
    found: list[RecorderJournalEntry] = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        try:
            entry = json.loads(raw)
        except ValueError:
            raise _journal_failed("unparseable_json") from None
        if not isinstance(entry, dict):
            raise _journal_failed("unparseable_json")
        result = _text(entry, "UNIT_RESULT")
        ts_ns = _micros(entry, "__REALTIME_TIMESTAMP")
        if not result:
            continue
        if ts_ns is None:
            raise _journal_failed("missing_timestamp")
        # S3-R1: systemd's own ``UNIT_RESULT`` line carries ``USER_INVOCATION_ID`` (a unit's stdout
        # lines carry ``_SYSTEMD_INVOCATION_ID``); an entry with no id cannot be matched.
        invocation = _text(entry, "USER_INVOCATION_ID", "INVOCATION_ID", "_SYSTEMD_INVOCATION_ID")
        if not invocation:
            raise _journal_failed("missing_invocation_id")
        found.append(RecorderJournalEntry(ts_ns, invocation, result, _text(entry, "MESSAGE")))
    return tuple(sorted(found, key=lambda e: (e.ts_ns, e.invocation_id)))


# -- the bus snapshot ----------------------------------------------------------------------------

#: ``data_root -> the first outcome``: a snapshot, or the error raised reading it (seam B consumes
#: the file, so there is no second read).
_BUS_OUTCOMES: dict[Path, BusSnapshot | AuditInputError] = {}


def _audit_row() -> BwrapRow:
    row = AUTONOMY_BWRAP_TABLE.get(AUDIT_ROW_NAME)
    if row is None:
        raise AuditInputError("bus_snapshot_missing", "no_audit_row")
    return row


def _environment() -> Mapping[str, str]:
    return os.environ


def _consume_snapshot(data_root: Path, now_ns: int) -> BusSnapshot:
    row = _audit_row()
    roots = replace(default_roots(), data_root=data_root)
    try:
        return read_bus_snapshot(row, environ=_environment(), roots=roots, now_ns=lambda: now_ns)
    except BusSnapshotError as exc:
        cause = exc.code if exc.code in {"bus_snapshot_missing", "bus_snapshot_stale"} else ""
        raise AuditInputError(cause or "bus_snapshot_stale", "seam_b_refused") from None


def _snapshot(data_root: Path, now_ns: int) -> BusSnapshot:
    outcome = _BUS_OUTCOMES.get(data_root)
    if outcome is None:
        try:
            outcome = _consume_snapshot(data_root, now_ns)
        except AuditInputError as exc:
            outcome = exc
        _BUS_OUTCOMES[data_root] = outcome
    if isinstance(outcome, AuditInputError):
        raise AuditInputError(outcome.cause, outcome.detail)
    return outcome


def _read_named(snapshot: BusSnapshot, name: str) -> BusReadResult:
    for read in snapshot.reads:
        if read.name == name:
            if read.rc != 0 or read.timed_out or read.skipped or read.oversize:
                raise AuditInputError("bus_snapshot_missing", f"read_{name}_failed")
            return read
    raise AuditInputError("bus_snapshot_stale", f"read_{name}_absent")


def _properties(stdout: str) -> dict[str, str]:
    props: dict[str, str] = {}
    for line in stdout.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            props[key.strip()] = value.strip()
    return props


def _timespan_us(text: str) -> int:
    """A ``systemctl show`` time span (``0``, ``10min``, ``1min 30s``) in microseconds."""
    if text in {"", "0", "infinity"}:
        return 0
    rest = text.strip()
    total = 0.0
    while rest:
        match = _TIMESPAN_RE.match(rest)
        unit = match.group(2) if match else ""
        if match is None or unit not in _US_PER_UNIT:
            raise AuditInputError("bus_snapshot_stale", "unparseable_timespan")
        total += float(match.group(1)) * _US_PER_UNIT[unit]
        rest = rest[match.end() :].lstrip()
    return int(total)


def read_recorder_props(data_root: Path, *, now_ns: int) -> RecorderProps:
    """The recorder's watchdog properties from the bus snapshot."""
    read = _read_named(_snapshot(data_root, now_ns), AUDIT_BUS_READ_NAMES[0])
    props = _properties(read.stdout)
    if any(key not in props for key in _ARMED_KEYS):
        raise AuditInputError("bus_snapshot_stale", "recorder_property_absent")
    return RecorderProps(
        watchdog_usec=_timespan_us(props["WatchdogUSec"]),
        notify_access=props["NotifyAccess"],
        type=props["Type"],
    )


def _timestamp_ns(text: str) -> int | None:
    if text in {"", "n/a", "0"}:
        return None
    match = _TIMESTAMP_RE.fullmatch(text)
    if match is None or match.group(7) is None:
        raise AuditInputError("bus_snapshot_stale", "unparseable_timestamp")
    year, month, day, hour, minute, second = (int(g) for g in match.groups()[:6])
    return calendar.timegm((year, month, day, hour, minute, second)) * _S_NS


def read_ingest_exit_ns(data_root: Path, *, now_ns: int) -> int | None:
    """The ingest unit's ``ExecMainExitTimestamp`` (epoch ns) from the bus snapshot, or None."""
    read = _read_named(_snapshot(data_root, now_ns), AUDIT_BUS_READ_NAMES[1])
    props = _properties(read.stdout)
    if "ExecMainExitTimestamp" not in props:
        raise AuditInputError("bus_snapshot_stale", "exit_timestamp_absent")
    return _timestamp_ns(props["ExecMainExitTimestamp"])
