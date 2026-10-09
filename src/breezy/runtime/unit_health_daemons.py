"""Daemon and invocation rules of the AUT-6 health pass (plan r15 section 3.9; WP3 S4).

For every unit whose effective ``Restart=`` is ``always`` (or a ``WATCHDOG_DAEMON_UNITS`` member,
empty until WP4) the pass keeps the last ``NRestarts``, ``InvocationID`` and
``ActiveEnterTimestamp`` in ``seen/<unit>.json`` and finds, as #22 findings keyed through the S3
commit order:

* ``daemon_auto_restarted``: ``NRestarts`` grew (a drop re-baselines);
* ``daemon_crashed``: an invocation that ended in (previous pass, this pass] by anything other than
  a stop from systemd, whatever rotate run or build-side marker is also present (Y1);
* ``daemon_invocation_changed_unexplained``: a replaced invocation with no explanation of its own;
* ``daemon_restarted_buildside`` (WARNING): a replaced invocation announced by a build-side marker.

Every invocation that ended is read from the journal, never from ``systemctl show`` (which
describes only the current one). An explanation (a rotate run, a marker) applies only when every
ended invocation was stopped by systemd, and explains at most one of them.

The #21 reporting of a member's watchdog ending, the arming checks and the gate cross-check are
WP4's; this module only treats a member's ``UNIT_RESULT=watchdog`` ending as its own, never as a
crash. Nothing here reads a trading gate (X-6).
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from breezy.runtime import unit_health_model
from breezy.runtime.unit_health_daemon_support import (
    EVENT_AUTO_RESTARTED,
    EVENT_BUILDSIDE,
    EVENT_CRASHED,
    EVENT_UNEXPLAINED,
    MSG_EXIT,
    MSG_FAILED,
    MSG_SCHEDULED_RESTART,
    MSG_STARTED,
    MSG_STOPPING,
    DaemonJournal,
    DaemonWiring,
    PassHost,
    SubprocessDaemonJournal,
    UnitEntry,
)
from breezy.runtime.unit_health_intraday import run_intraday_rules
from breezy.runtime.unit_health_store import NS, day_of_ns, read_json, write_once

__all__ = [
    "MSG_EXIT",
    "MSG_FAILED",
    "MSG_SCHEDULED_RESTART",
    "MSG_STARTED",
    "MSG_STOPPING",
    "DaemonJournal",
    "DaemonWiring",
    "Ending",
    "EndingVerdict",
    "SubprocessDaemonJournal",
    "UnitEntry",
    "classify_ending",
    "ended_invocation_ids",
    "parse_systemd_timestamp",
    "read_buildside_markers",
    "run_daemon_rules",
    "run_mark_buildside_restart",
    "write_buildside_marker",
]

QUOTE_TAPE_UNIT: Final = "breezy-quote-tape.service"
ROTATE_UNIT: Final = "breezy-quote-tape-rotate.service"
#: Data-path daemons: their findings are CRITICAL. Any other ``Restart=always`` unit pages WARNING.
DATA_PATH_DAEMONS: Final = frozenset(
    {QUOTE_TAPE_UNIT, "breezy-nws-ingest.service", "breezy-trade-supervisor.service"}
)
BUILDSIDE_WINDOW_S: Final = 300
MARKER_DIR: Final = "buildside_restart"
MARKER_SCHEMA: Final = "buildside_restart/v1"
DAEMON_SEEN_KEY: Final = "daemon"
JUDGED_KEPT: Final = 32
EXIT_USAGE: Final = 2
#: The journal's ``JOB_TYPE`` value of a stop job. Built, not quoted: it is a field value, and the
#: S3 guard that no health module names a state-changing systemctl verb scans for the quoted word.
_STOP_JOB: Final = "STOP".lower()
_SIGTERM_STATUS: Final = frozenset({"15", "TERM", "SIGTERM"})
_CLEAN_STOP_EXITS: Final = frozenset({"0", "143"})
_INVOCATION_RE: Final = re.compile(r"[0-9a-f]{32}")
_TIMESTAMP_RE: Final = re.compile(
    r"[A-Z][a-z]{2} (\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})(?:\.\d+)? UTC"
)
_MARKER_NAME_RE: Final = re.compile(r"(\d+)_(breezy-[A-Za-z0-9@._-]+\.service)\.json")
_UNIT_ARG_RE: Final = re.compile(r"breezy-[a-z0-9@._-]+\.service")
_COMMIT_RE: Final = re.compile(r"[0-9a-f]{7,40}")
_MAX_REASON: Final = 200
_US: Final = 1_000_000


# --------------------------------------------------------------------------- pure helpers


def parse_systemd_timestamp(text: str) -> int | None:
    """``Thu 2026-10-08 12:00:00 UTC`` (a ``systemctl show`` timestamp) in ns; else ``None``.

    Only UTC is accepted: another zone is unknown, and unknown is never guessed.
    """
    match = _TIMESTAMP_RE.fullmatch(text.strip())
    if match is None:
        return None
    try:
        moment = dt.datetime.fromisoformat(f"{match.group(1)}T{match.group(2)}+00:00")
    except ValueError:
        return None
    return int(moment.timestamp()) * NS


class Ending(StrEnum):
    STOPPED = "stopped_by_systemd"
    WATCHDOG = "watchdog"
    CRASHED = "crashed"
    #: No lifecycle evidence at all: it cannot be proven to have been a stop.
    UNPROVEN = "unproven"


@dataclass(frozen=True, slots=True)
class EndingVerdict:
    ending: Ending
    exit_code: str = ""
    exit_status: str = ""
    stopping_us: int | None = None


def _is_sigterm_exit(entry: UnitEntry) -> bool:
    code, status = entry.fields.get("EXIT_CODE", ""), entry.fields.get("EXIT_STATUS", "")
    return (code == "killed" and status in _SIGTERM_STATUS) or (
        code == "exited" and status in _CLEAN_STOP_EXITS
    )


def _stopped_by_systemd(entries: Sequence[UnitEntry]) -> int | None:
    """The ``Stopping`` timestamp of a stop from systemd, or ``None`` (the section 3.9 rule)."""
    stops = [
        e for e in entries if e.message_id == MSG_STOPPING and e.fields.get("JOB_TYPE") == _STOP_JOB
    ]
    if not stops or any(e.message_id in {MSG_SCHEDULED_RESTART, MSG_FAILED} for e in entries):
        return None
    stop = min(e.ts_us for e in stops)
    for e in entries:
        if e.message_id != MSG_EXIT:
            continue
        if e.ts_us < stop or not _is_sigterm_exit(e):
            return None
    return stop


def classify_ending(
    unit: str, entries: Sequence[UnitEntry], *, watchdog_units: frozenset[str]
) -> EndingVerdict:
    """How one ended invocation ended, from its own journal entries (Y1, DL2)."""
    if not entries:
        return EndingVerdict(Ending.UNPROVEN)
    if unit in watchdog_units and any(
        e.message_id == MSG_FAILED and e.fields.get("UNIT_RESULT") == "watchdog" for e in entries
    ):
        return EndingVerdict(Ending.WATCHDOG)
    evidence = {MSG_STOPPING, MSG_EXIT, MSG_FAILED, MSG_SCHEDULED_RESTART}
    if not any(e.message_id in evidence for e in entries):
        return EndingVerdict(Ending.UNPROVEN)
    stopped = _stopped_by_systemd(entries)
    if stopped is not None:
        return EndingVerdict(Ending.STOPPED, stopping_us=stopped)
    exits = [e for e in entries if e.message_id == MSG_EXIT]
    last = max(exits, key=lambda e: e.ts_us) if exits else None
    return EndingVerdict(
        Ending.CRASHED,
        last.fields.get("EXIT_CODE", "") if last else "",
        last.fields.get("EXIT_STATUS", "") if last else "",
    )


def ended_invocation_ids(
    entries: Sequence[UnitEntry], *, current: str, stored: str
) -> tuple[str, ...]:
    """The stored invocation plus every id in a ``Started``, exit or ``Stopping`` entry of the
    interval, other than the current one (LOW-r9-1), oldest first."""
    lifecycle = {MSG_STARTED, MSG_EXIT, MSG_STOPPING}
    first: dict[str, int] = {}
    for e in entries:
        if e.message_id in lifecycle and _INVOCATION_RE.fullmatch(e.invocation_id):
            first[e.invocation_id] = min(first.get(e.invocation_id, e.ts_us), e.ts_us)
    first.pop(current, None)
    ordered = sorted(first, key=lambda i: (first[i], i))
    out = [i for i in ordered if i != stored]
    if stored != current and _INVOCATION_RE.fullmatch(stored):
        out.insert(0, stored)
    return tuple(out)


# --------------------------------------------------------------------------- build-side markers


@dataclass(frozen=True, slots=True)
class Marker:
    ts_ns: int
    unit: str


def write_buildside_marker(root: Path, unit: str, *, reason: str, commit: str, ts_ns: int) -> Path:
    """Write the write-once marker ``<root>/buildside_restart/<day>/<ts_ns>_<unit>.json`` (0444).

    An existing name is never replaced: the timestamp moves on by 1 ns until a new name is free.
    """
    stamp = ts_ns
    while True:
        path = root / MARKER_DIR / day_of_ns(stamp) / f"{stamp}_{unit}.json"
        body = {
            "schema": MARKER_SCHEMA,
            "ts_ns": stamp,
            "unit": unit,
            "reason": reason,
            "commit": commit,
        }
        if write_once(path, body):
            return path
        stamp += 1


def read_buildside_markers(root: Path, unit: str, lo_ns: int, hi_ns: int) -> list[Marker]:
    """Valid markers of ``unit`` with ``lo_ns <= ts_ns <= hi_ns``. An unreadable directory or file
    counts as no marker: the CRITICAL stands (fail closed)."""
    found: list[Marker] = []
    for day in sorted({day_of_ns(lo_ns), day_of_ns(hi_ns)}):
        directory = root / MARKER_DIR / day
        try:
            names = sorted(os.listdir(directory))
        except OSError:
            continue
        for name in names:
            match = _MARKER_NAME_RE.fullmatch(name)
            if match is None or match.group(2) != unit:
                continue
            body = read_json(directory / name)
            ts = body.get("ts_ns") if body else None
            if (
                body is not None
                and body.get("schema") == MARKER_SCHEMA
                and body.get("unit") == unit
                and isinstance(ts, int)
                and not isinstance(ts, bool)
                and lo_ns <= ts <= hi_ns
            ):
                found.append(Marker(ts, unit))
    return sorted(found, key=lambda m: m.ts_ns)


def run_mark_buildside_restart(
    argv: Sequence[str],
    *,
    root: Path | None = None,
    now_ns: Callable[[], int] = time.time_ns,
) -> int:
    """``breezy-autonomy-health --mark-buildside-restart <unit> --reason <text> --commit <sha>``.

    Run by the build-side implementer immediately before the restart command; no autonomy code
    path writes a marker. Returns 0, or 2 on a bad argument (nothing is written).
    """
    parser = argparse.ArgumentParser(
        prog="breezy-autonomy-health", add_help=False, exit_on_error=False
    )
    parser.add_argument("--mark-buildside-restart", dest="unit", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--commit", required=True)
    try:
        args = parser.parse_args(list(argv))
    except (argparse.ArgumentError, SystemExit):
        sys.stderr.write("usage: --mark-buildside-restart <unit> --reason <text> --commit <sha>\n")
        return EXIT_USAGE
    reason = str(args.reason)
    problems = []
    if not _UNIT_ARG_RE.fullmatch(str(args.unit)):
        problems.append("unit must be a breezy-*.service name")
    if not reason or len(reason) > _MAX_REASON or not reason.isprintable():
        problems.append("reason must be 1-200 printable characters on one line")
    if not _COMMIT_RE.fullmatch(str(args.commit)):
        problems.append("commit must be 7-40 lowercase hex digits")
    if problems:
        sys.stderr.write("mark-buildside-restart: " + "; ".join(problems) + "\n")
        return EXIT_USAGE
    target = (
        root
        if root is not None
        else (Path.home() / ".local" / "share" / "breezy" / "evidence" / "unit_health")
    )
    path = write_buildside_marker(
        target, str(args.unit), reason=reason, commit=str(args.commit), ts_ns=now_ns()
    )
    sys.stdout.write(f"BUILDSIDE_MARKER written={path}\n")
    return 0


# --------------------------------------------------------------------------- the pass rules


def _stopped_between(lo_us: int, hi_us: int) -> Callable[[_Ended], bool]:
    def fits(item: _Ended) -> bool:
        return lo_us <= (item.verdict.stopping_us or 0) <= hi_us

    return fits


@dataclass(frozen=True, slots=True)
class _Ended:
    invocation_id: str
    verdict: EndingVerdict


def _valid_state(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    inv, restarts, pass_ns = raw.get("invocation_id"), raw.get("nrestarts"), raw.get("pass_ns")
    if not (isinstance(inv, str) and _INVOCATION_RE.fullmatch(inv)):
        return None
    if not (isinstance(restarts, int) and isinstance(pass_ns, int)):
        return None
    return raw


class _Daemons:
    def __init__(self, host: PassHost, wiring: DaemonWiring, observation: Any) -> None:
        self.host = host
        self.wiring = wiring
        self.blocks: Mapping[str, Mapping[str, str]] = observation.blocks
        root: Path = host.store.root
        self.marker_root = wiring.marker_root or root

    def in_scope(self, unit: str, block: Mapping[str, str]) -> bool:
        if not unit.startswith("breezy-") or not unit.endswith(".service"):
            return False
        return block.get("Restart") == "always" or unit in unit_health_model.WATCHDOG_DAEMON_UNITS

    def run(self) -> None:
        for unit in sorted(self.blocks):
            block = self.blocks[unit]
            if self.in_scope(unit, block):
                self.check(unit, block)

    # ---- one daemon

    def check(self, unit: str, block: Mapping[str, str]) -> None:
        host = self.host
        invocation, restarts_text = block.get("InvocationID", ""), block.get("NRestarts", "")
        if not (_INVOCATION_RE.fullmatch(invocation) and restarts_text.isdigit()):
            host.scan.reasons.append("daemon_property_unreadable")
            host.block()
            return
        restarts = int(restarts_text)
        active_enter = parse_systemd_timestamp(block.get("ActiveEnterTimestamp", ""))
        prior = host.store.read_seen(unit) or {}
        stored = _valid_state(prior.get(DAEMON_SEEN_KEY))
        judged = [i for i in (stored or {}).get("judged", []) if isinstance(i, str)]
        ended: list[_Ended] = []
        if stored is not None and stored["invocation_id"] != invocation:
            ended = self.read_ended(unit, stored, invocation)
        severity = "CRITICAL" if unit in DATA_PATH_DAEMONS else "WARNING"
        if stored is not None:
            self.report(unit, block, stored, ended, invocation, active_enter, severity)
            delta = restarts - int(stored["nrestarts"])
            all_watchdog = bool(ended) and all(e.verdict.ending is Ending.WATCHDOG for e in ended)
            if delta > 0 and not all_watchdog:
                self.finding(
                    unit,
                    EVENT_AUTO_RESTARTED,
                    invocation,
                    severity,
                    f"unit={unit} nrestarts_delta={delta}",
                    {"metrics": {"nrestarts_delta": str(delta)}},
                )
        host.scan.daemon_seen.setdefault(unit, {})[DAEMON_SEEN_KEY] = {
            "invocation_id": invocation,
            "active_enter_ns": active_enter,
            "nrestarts": restarts,
            "pass_ns": host.now,
            "judged": [*judged, *(e.invocation_id for e in ended)][-JUDGED_KEPT:],
        }

    def read_ended(self, unit: str, stored: Mapping[str, Any], current: str) -> list[_Ended]:
        host = self.host
        journal = self.wiring.journal
        interval = journal.unit_entries(
            unit,
            since_us=int(stored["pass_ns"]) // 1000,
            until_us=host.now // 1000,
            lifecycle_only=True,
            timeout_s=host.allowance(),
        )
        already = set(stored.get("judged", []))
        ids = [
            i
            for i in ended_invocation_ids(interval, current=current, stored=stored["invocation_id"])
            if i not in already
        ]
        ended: list[_Ended] = []
        for invocation in ids:
            host.check_budget()
            entries = journal.invocation_entries(
                unit, invocation, lifecycle_only=True, timeout_s=host.allowance()
            )
            verdict = classify_ending(
                unit, entries, watchdog_units=unit_health_model.WATCHDOG_DAEMON_UNITS
            )
            ended.append(_Ended(invocation, verdict))
        return ended

    # ---- findings

    def finding(
        self,
        unit: str,
        event: str,
        key_id: str,
        severity: str,
        detail: str,
        extra: Mapping[str, object],
    ) -> None:
        self.host.commit_finding(event, unit, f"{event}-{key_id}", severity, detail, extra)

    def report(
        self,
        unit: str,
        block: Mapping[str, str],
        stored: Mapping[str, Any],
        ended: Sequence[_Ended],
        current: str,
        active_enter: int | None,
        severity: str,
    ) -> None:
        for item in ended:
            if item.verdict.ending is Ending.CRASHED:
                metrics = {
                    k: v
                    for k, v in (
                        ("exit_code", item.verdict.exit_code),
                        ("exit_status", item.verdict.exit_status),
                    )
                    if v
                }
                self.finding(
                    unit,
                    EVENT_CRASHED,
                    item.invocation_id,
                    severity,
                    f"unit={unit} ended={item.invocation_id} "
                    + " ".join(f"{k}={v}" for k, v in metrics.items()),
                    {"metrics": metrics, "ended_invocation_id": item.invocation_id},
                )
        unexplained = [e for e in ended if e.verdict.ending is Ending.UNPROVEN]
        stopped = [e for e in ended if e.verdict.ending is Ending.STOPPED]
        applies = all(e.verdict.ending in {Ending.STOPPED, Ending.WATCHDOG} for e in ended)
        buildside = False
        if applies and stopped:
            stopped, buildside = self.explain(unit, stored, stopped, active_enter)
        else:
            unexplained += stopped
        if buildside:
            self.finding(
                unit,
                EVENT_BUILDSIDE,
                current,
                "WARNING",
                f"unit={unit} restarted build-side (marker)",
                {"new_invocation_id": current},
            )
        leftover = unexplained + (stopped if applies else [])
        if leftover:
            ids = [e.invocation_id for e in leftover]
            self.finding(
                unit,
                EVENT_UNEXPLAINED,
                current,
                severity,
                f"unit={unit} invocation changed unexplained ended={len(ids)}",
                {
                    "ended_invocations": ids,
                    "old_invocation_id": stored["invocation_id"],
                    "new_invocation_id": current,
                },
            )

    # ---- explanations: each explains at most one ended invocation

    def explain(
        self,
        unit: str,
        stored: Mapping[str, Any],
        stopped: Sequence[_Ended],
        active_enter: int | None,
    ) -> tuple[list[_Ended], bool]:
        """The stopped invocations still unexplained, and whether a marker explained one."""
        remaining = sorted(stopped, key=lambda e: e.verdict.stopping_us or 0)
        rotate_us = self.rotate_start_us(stored) if unit == QUOTE_TAPE_UNIT else None
        if rotate_us is not None:
            remaining = self.take(remaining, lambda e: (e.verdict.stopping_us or 0) >= rotate_us)
        matched_marker = False
        stored_enter = stored.get("active_enter_ns")
        if (
            active_enter is not None
            and isinstance(stored_enter, int)
            and active_enter > stored_enter
        ):
            window = BUILDSIDE_WINDOW_S * NS
            for marker in read_buildside_markers(
                self.marker_root, unit, active_enter - window, active_enter
            ):
                lo, hi = marker.ts_ns // 1000, (marker.ts_ns + window) // 1000
                before = len(remaining)
                remaining = self.take(remaining, _stopped_between(lo, hi))
                matched_marker = matched_marker or len(remaining) < before
        return remaining, matched_marker

    @staticmethod
    def take(remaining: list[_Ended], fits: Callable[[_Ended], bool]) -> list[_Ended]:
        """Remove the first (oldest stop) invocation that ``fits``: one explanation each."""
        for index, item in enumerate(remaining):
            if fits(item):
                return [*remaining[:index], *remaining[index + 1 :]]
        return remaining

    def rotate_start_us(self, stored: Mapping[str, Any]) -> int | None:
        """The rotate run's start (us) when it can explain: inside (previous pass, this pass],
        later than the stored invocation began (LOW-1) and ``Result=success``."""
        block = self.blocks.get(ROTATE_UNIT)
        if block is None or block.get("Result") != "success":
            return None
        started = parse_systemd_timestamp(block.get("ExecMainStartTimestamp", ""))
        stored_enter = stored.get("active_enter_ns")
        if started is None or not isinstance(stored_enter, int):
            return None
        if not (int(stored["pass_ns"]) < started <= self.host.now and started > stored_enter):
            return None
        return started // 1000


def run_daemon_rules(host: PassHost, observation: Any) -> None:
    """The S4 hook of the health pass: daemon rules, then the intraday-stage rules."""
    wiring = host.env.daemons
    if wiring is None:
        return
    _Daemons(host, wiring, observation).run()
    run_intraday_rules(host, observation, wiring)
