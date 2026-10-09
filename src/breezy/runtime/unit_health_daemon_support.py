"""Shared seams of the AUT-6 daemon and intraday rules (plan r15 sections 3.9 and 3.4.2; WP3 S4).

* the journal entry model and the unit-scoped journal reads (an argv list each, bounded by the
  pass budget like every S3 read);
* the host protocol the rules use to reach the health pass without importing it;
* the event names the rules page, so ``unexplained_for_day`` can count them.

No I/O at import. The reads never run a shell and never leave the user journal.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Protocol

from breezy.runtime.unit_health_journal import (
    JOURNALCTL,
    JournalError,
    Run,
    run_bounded,
)

MSG_STARTED: Final = "39f53479d3a045ac8e11786248231fbf"
MSG_EXIT: Final = "98e322203f7a4ed290d09fe03c09fe15"
MSG_STOPPING: Final = "de5b426a63be47a7b6ac3eaac82e2f6f"
MSG_SCHEDULED_RESTART: Final = "5eb03494b6584870a536b337290809b3"
MSG_FAILED: Final = "d9b373ed55a64feb8242e02dbe79a49c"
LIFECYCLE_IDS: Final = (MSG_STARTED, MSG_EXIT, MSG_STOPPING)

EVENT_AUTO_RESTARTED: Final = "daemon_auto_restarted"
EVENT_CRASHED: Final = "daemon_crashed"
EVENT_UNEXPLAINED: Final = "daemon_invocation_changed_unexplained"
EVENT_BUILDSIDE: Final = "daemon_restarted_buildside"
#: Daemon findings that page (and so must be explained by a delivered alert).
DAEMON_EVENTS: Final = (EVENT_AUTO_RESTARTED, EVENT_CRASHED, EVENT_UNEXPLAINED, EVENT_BUILDSIDE)

EVENT_BWRAP_UNAVAILABLE: Final = "bwrap_unavailable"
EVENT_DEMAND_TIMEOUT: Final = "demand_stage_timeout"
EVENT_DEMAND_DEADLINE: Final = "demand_stage_deadline_hit"
EVENT_DEMAND_FAILED: Final = "demand_stage_failed"
EVENT_DEMAND_INTEGRITY: Final = "demand_stage_integrity"
EVENT_EVAL_FAILED: Final = "evaluate_stage_failed"
EVENT_EVAL_TIMEOUT: Final = "evaluate_stage_timeout"
EVENT_EVAL_UNRECORDED: Final = "evaluate_stage_unrecorded"
#: Intraday findings that page. ``demand_stage_integrity`` is recorded only: the stage paged it.
INTRADAY_PAGED_EVENTS: Final = (
    EVENT_BWRAP_UNAVAILABLE,
    EVENT_DEMAND_TIMEOUT,
    EVENT_DEMAND_DEADLINE,
    EVENT_DEMAND_FAILED,
    EVENT_EVAL_FAILED,
    EVENT_EVAL_TIMEOUT,
    EVENT_EVAL_UNRECORDED,
)
PAGED_FINDING_EVENTS: Final = (*DAEMON_EVENTS, *INTRADAY_PAGED_EVENTS)

_INVOCATION_RE: Final = re.compile(r"[0-9a-f]{32}")
_UNIT_RE: Final = re.compile(r"[A-Za-z0-9@._-]+\.service")
_FIELDS: Final = ("COMMAND", "EXIT_CODE", "EXIT_STATUS", "JOB_TYPE", "JOB_RESULT", "UNIT_RESULT")
_US: Final = 1_000_000


@dataclass(frozen=True, slots=True)
class UnitEntry:
    """One journal entry of a unit, with the stdout and systemd id fields normalised."""

    message_id: str
    ts_us: int
    invocation_id: str
    unit: str
    message: str = ""
    fields: Mapping[str, str] = field(default_factory=dict)


class DaemonJournal(Protocol):
    def unit_entries(
        self, unit: str, *, since_us: int, until_us: int, lifecycle_only: bool, timeout_s: float
    ) -> tuple[UnitEntry, ...]: ...

    def invocation_entries(
        self, unit: str, invocation_id: str, *, lifecycle_only: bool, timeout_s: float
    ) -> tuple[UnitEntry, ...]: ...


@dataclass(frozen=True, slots=True)
class DaemonWiring:
    """The seams of the daemon rules. ``alerts_root`` defaults to the sibling of the store."""

    journal: DaemonJournal
    alerts_root: Path | None = None
    #: Where build-side markers live; ``None`` is ``<store root>/buildside_restart``.
    marker_root: Path | None = None


class PassHost(Protocol):
    """What the rules use of the health pass (``unit_health._Pass``)."""

    env: Any
    store: Any
    scan: Any
    now: int
    today: str

    def allowance(self) -> float: ...

    def check_budget(self) -> None: ...

    def block(self) -> None: ...

    def commit_finding(
        self,
        kind: str,
        unit: str,
        key: str,
        severity: str,
        detail: str,
        extra: Mapping[str, object] | None = None,
        *,
        page: bool = True,
    ) -> None: ...

    def commit_cited_finding(
        self,
        kind: str,
        unit: str,
        key: str,
        severity: str,
        cite_event: str,
        cite_site: str,
        extra: Mapping[str, object] | None = None,
    ) -> None: ...


# --------------------------------------------------------------------------- journal reads


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def parse_entry_line(line: str) -> UnitEntry:
    """One ``journalctl -o json`` line; ``JournalError("parse")`` when it cannot be read."""
    try:
        raw = json.loads(line)
    except ValueError:
        raise JournalError("parse") from None
    if not isinstance(raw, dict):
        raise JournalError("parse")
    ts = raw.get("__REALTIME_TIMESTAMP")
    if not (isinstance(ts, str) and ts.isdigit()):
        raise JournalError("parse")
    invocation = _text(raw.get("USER_INVOCATION_ID")) or _text(raw.get("_SYSTEMD_INVOCATION_ID"))
    unit = _text(raw.get("USER_UNIT")) or _text(raw.get("_SYSTEMD_USER_UNIT"))
    fields = {k: _text(raw.get(k)) for k in _FIELDS if isinstance(raw.get(k), str)}
    return UnitEntry(
        _text(raw.get("MESSAGE_ID")), int(ts), invocation, unit, _text(raw.get("MESSAGE")), fields
    )


def _parse_all(stdout: str) -> tuple[UnitEntry, ...]:
    return tuple(parse_entry_line(ln) for ln in stdout.splitlines() if ln.strip())


def _seconds_floor(us: int) -> int:
    return max(us, 0) // _US


def _seconds_ceil(us: int) -> int:
    return -(-max(us, 0) // _US)


class SubprocessDaemonJournal:
    """The production ``DaemonJournal``: ``journalctl --user -o json`` through ``run``."""

    def __init__(self, run: Run = run_bounded) -> None:
        self._run = run

    @staticmethod
    def _base() -> list[str]:
        return [JOURNALCTL, "--user", "-o", "json", "--no-pager"]

    def _checked(self, argv: Sequence[str], timeout_s: float) -> tuple[UnitEntry, ...]:
        result = self._run(argv, timeout_s)
        if result.timed_out:
            raise JournalError("timed_out")
        if result.oversize:
            raise JournalError("oversize")
        if result.rc != 0:
            raise JournalError(f"rc={result.rc}")
        return _parse_all(result.stdout)

    def unit_entries(
        self, unit: str, *, since_us: int, until_us: int, lifecycle_only: bool, timeout_s: float
    ) -> tuple[UnitEntry, ...]:
        if not _UNIT_RE.fullmatch(unit):
            raise JournalError("unit_name")
        argv = [
            *self._base(),
            f"--since=@{_seconds_floor(since_us)}",
            f"--until=@{_seconds_ceil(until_us)}",
        ]
        if lifecycle_only:
            # systemd's own entries only: a chatty daemon's stdout would blow the output cap.
            argv += [f"USER_UNIT={unit}", *(f"MESSAGE_ID={m}" for m in LIFECYCLE_IDS)]
        else:
            argv += [f"USER_UNIT={unit}", "+", f"_SYSTEMD_USER_UNIT={unit}"]
        return tuple(e for e in self._checked(argv, timeout_s) if since_us < e.ts_us <= until_us)

    def invocation_entries(
        self, unit: str, invocation_id: str, *, lifecycle_only: bool, timeout_s: float
    ) -> tuple[UnitEntry, ...]:
        if not _UNIT_RE.fullmatch(unit):
            raise JournalError("unit_name")
        if not _INVOCATION_RE.fullmatch(invocation_id):
            raise JournalError("invocation_id")
        argv = [*self._base(), f"USER_UNIT={unit}", f"USER_INVOCATION_ID={invocation_id}"]
        if not lifecycle_only:
            argv += [
                "+",
                f"_SYSTEMD_USER_UNIT={unit}",
                f"_SYSTEMD_INVOCATION_ID={invocation_id}",
            ]
        return self._checked(argv, timeout_s)
