"""Builders for the AUT-6 daemon and intraday rules tests (WP3 S4): journal entries and a fake.

The entry shapes are the ones measured on the real journal (plan r15 section 0 and the LOW-r11-7
scratch-unit test): systemd's own entries carry ``USER_UNIT`` and ``USER_INVOCATION_ID``; a stage's
stdout lines carry ``_SYSTEMD_USER_UNIT`` and ``_SYSTEMD_INVOCATION_ID`` (normalised by the parser).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from breezy.runtime.unit_health_daemon_support import (
    MSG_EXIT,
    MSG_FAILED,
    MSG_SCHEDULED_RESTART,
    MSG_STARTED,
    MSG_STOPPING,
    UnitEntry,
)
from tests.support.unit_health_fixtures import NOW_NS

INTRADAY: Final = "breezy-autonomy-producer-intraday.service"
QUOTE_TAPE: Final = "breezy-quote-tape.service"
ROTATE: Final = "breezy-quote-tape-rotate.service"
EVAL_START: Final = "PRODUCER_INTRADAY START ts_ns=1"
DEMAND_START: Final = "PRODUCER_INTRADAY_DEMAND START"


def at_us(offset_s: float) -> int:
    """Journal time ``offset_s`` seconds from the test clock's 2026-10-08T12:00:00Z."""
    return NOW_NS // 1000 + int(offset_s * 1_000_000)


def systemd_ts(offset_s: float) -> str:
    """The ``systemctl show`` rendering of the same instant (the host runs in UTC)."""
    import datetime as dt

    moment = dt.datetime.fromtimestamp(at_us(offset_s) / 1_000_000, tz=dt.UTC)
    return moment.strftime("%a %Y-%m-%d %H:%M:%S UTC")


def entry(
    message_id: str, unit: str, invocation: str, offset_s: float, message: str = "", **fields: str
) -> UnitEntry:
    return UnitEntry(message_id, at_us(offset_s), invocation, unit, message, dict(fields))


def started(unit: str, invocation: str, t: float) -> UnitEntry:
    return entry(MSG_STARTED, unit, invocation, t, "Started", JOB_TYPE="start", JOB_RESULT="done")


def stopping(unit: str, invocation: str, t: float, job_type: str = "stop") -> UnitEntry:
    return entry(MSG_STOPPING, unit, invocation, t, "Stopping", JOB_TYPE=job_type)


def exited(
    unit: str,
    invocation: str,
    t: float,
    status: str = "0",
    code: str = "exited",
    command: str = "ExecStart",
) -> UnitEntry:
    return entry(
        MSG_EXIT,
        unit,
        invocation,
        t,
        "Main process exited",
        COMMAND=command,
        EXIT_CODE=code,
        EXIT_STATUS=status,
    )


def failed(unit: str, invocation: str, t: float, result: str = "exit-code") -> UnitEntry:
    return entry(MSG_FAILED, unit, invocation, t, "Failed", UNIT_RESULT=result)


def scheduled(unit: str, invocation: str, t: float) -> UnitEntry:
    return entry(MSG_SCHEDULED_RESTART, unit, invocation, t, "Scheduled restart job")


def line(unit: str, invocation: str, t: float, message: str) -> UnitEntry:
    return entry("", unit, invocation, t, message)


def crash_entries(unit: str, invocation: str, t: float, status: str = "1") -> list[UnitEntry]:
    """A daemon crash as measured on 09-29: exit, unit-failed and scheduled-restart entries."""
    return [
        started(unit, invocation, t - 10),
        exited(unit, invocation, t, status),
        failed(unit, invocation, t + 0.1),
        scheduled(unit, invocation, t + 0.2),
    ]


def rotate_stop_entries(unit: str, invocation: str, t: float) -> list[UnitEntry]:
    """A clean stop by systemd (the 09:00Z rotate): ``Stopping`` with no exit entry."""
    return [started(unit, invocation, t - 3600), stopping(unit, invocation, t)]


def intraday_run(
    invocation: str,
    t0: float,
    *,
    unit: str = INTRADAY,
    eval_summary: str | None = "PRODUCER_INTRADAY wrote=3 skipped=0 fold_ok=1 exit=0",
    eval_start: bool = True,
    eval_end_s: float = 20,
    demand_start: bool = True,
    demand_summary: str | None = (
        "PRODUCER_INTRADAY_DEMAND wrote=0 skipped_existing=0 invalid=0 "
        "integrity_demand_write_failures=0 journal_write_failures=0 outbox_write_failures=0 "
        "deadline_hit=0 unprocessed=0 evaluate_exit=0 exit=0"
    ),
    exit_status: int | None = 0,
    bwrap_line: bool = False,
    finish: bool = True,
) -> list[UnitEntry]:
    """One intraday invocation. ``None`` removes a line; ``finish=False`` leaves it in flight."""
    out = [
        entry(
            "7d4958e842da4a758f6c1cdc7b36dcc5", unit, invocation, t0, "Starting", JOB_TYPE="start"
        )
    ]
    if bwrap_line:
        out.append(
            line(unit, invocation, t0 + 0.2, "bwrap: Can't create file at /x: Permission denied")
        )
    if eval_start:
        out.append(line(unit, invocation, t0 + 0.5, EVAL_START))
    if eval_summary is not None:
        out.append(line(unit, invocation, t0 + eval_end_s, eval_summary))
    demand_t = t0 + eval_end_s + 1
    if demand_start:
        out.append(line(unit, invocation, demand_t, DEMAND_START))
    if demand_summary is not None:
        out.append(line(unit, invocation, demand_t + 2, demand_summary))
    if finish:
        end = demand_t + 3
        if exit_status is not None:
            out.append(exited(unit, invocation, end, str(exit_status)))
        if exit_status:
            out.append(failed(unit, invocation, end + 0.1))
        out.append(started(unit, invocation, end + 0.2))
    return out


class FakeDaemonJournal:
    """The ``DaemonJournal`` seam over a fixed list of entries (in journal order)."""

    def __init__(self, entries: Sequence[UnitEntry] = ()) -> None:
        self.entries: list[UnitEntry] = list(entries)
        self.calls: list[tuple[str, str]] = []
        self.fail_with: Exception | None = None
        self.unit_kwargs: list[dict[str, int | str | bool]] = []

    def add(self, *more: UnitEntry | Sequence[UnitEntry]) -> None:
        for item in more:
            if isinstance(item, UnitEntry):
                self.entries.append(item)
            else:
                self.entries.extend(item)

    def unit_entries(
        self, unit: str, *, since_us: int, until_us: int, lifecycle_only: bool, timeout_s: float
    ) -> tuple[UnitEntry, ...]:
        self.calls.append(("unit_entries", unit))
        self.unit_kwargs.append({"unit": unit, "since_us": since_us, "until_us": until_us})
        if self.fail_with is not None:
            raise self.fail_with
        lifecycle = {MSG_STARTED, MSG_EXIT, MSG_STOPPING}
        return tuple(
            e
            for e in self.entries
            if e.unit == unit
            and since_us < e.ts_us <= until_us
            and (not lifecycle_only or e.message_id in lifecycle)
        )

    def invocation_entries(
        self, unit: str, invocation_id: str, *, lifecycle_only: bool, timeout_s: float
    ) -> tuple[UnitEntry, ...]:
        self.calls.append(("invocation_entries", invocation_id))
        if self.fail_with is not None:
            raise self.fail_with
        return tuple(
            e
            for e in self.entries
            if e.unit == unit
            and e.invocation_id == invocation_id
            and (not lifecycle_only or e.message_id)
        )
