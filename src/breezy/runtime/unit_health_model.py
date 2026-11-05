"""Pure model of the AUT-6 unit health pass (plan r15 section 3.9): classes, result map, scope.

No I/O. The failure source is the journal's unit-failed entry (``MESSAGE_ID`` ``d9b373ed...``);
``classify`` turns one such entry plus the facts known about that invocation into a class, the
detector it feeds (#22 ``aut6.unit_health_unhealable``, or #21 ``aut6.unit_health`` for a watchdog
ending of a ``WATCHDOG_DAEMON_UNITS`` member) and the action (always ``ALERT``: the health unit
restarts nothing, systemd's own watchdog does).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Final

_LOG = logging.getLogger(__name__)

HEALTH_PASS_BUDGET_S: Final = 90
#: The health row's bus-snapshot budget (15 s, ``table._AUTONOMY_HEALTH_ROW``) plus 60 s (E-7e(f)).
SNAPSHOT_BUDGET_S: Final = 15
SNAPSHOT_MAX_AGE_S: Final = SNAPSHOT_BUDGET_S + 60
MESSAGE_ID_UNIT_FAILED: Final = "d9b373ed55a64feb8242e02dbe79a49c"
MESSAGE_ID_UNIT_RESOURCES: Final = "ae8f7b866b0347b9af31fe1c80b127c0"
DETECTOR_UNHEALABLE: Final = "aut6.unit_health_unhealable"
DETECTOR_WATCHDOG: Final = "aut6.unit_health"
#: Filled by WP4 (the watchdog work package); empty until then (execution decisions, slice S4).
WATCHDOG_DAEMON_UNITS: Final[frozenset[str]] = frozenset()
FOREIGN_UNIT_PREFIXES: Final = ("jetbrains-remote-dev", "pressure-")
REPO_PREFIX: Final = "/home/jon/breezy/"
#: CPU time over wall time under which a timed-out unit was waiting, not computing (discovery-pull
#: 10-02: 13.86 s over 1800 s = 0.008).
LOW_CPU_RATIO: Final = 0.05

_INVOCATION_RE: Final = re.compile(r"[0-9a-f]{32}")
_BREEZY_UNIT_RE: Final = re.compile(
    r"(breezy-[a-z0-9@._-]+|us-source-collector@[a-z0-9._-]+)\.service"
)
_RUN_UNIT_RE: Final = re.compile(r"run-[A-Za-z0-9@._-]+\.service")
_TIMESPAN_PART: Final = re.compile(r"(\d+(?:\.\d+)?)\s*(us|ms|s|min|h|d|w|month|y)")
_TIMESPAN_S: Final[Mapping[str, float]] = {
    "us": 1e-6,
    "ms": 1e-3,
    "s": 1.0,
    "min": 60.0,
    "h": 3600.0,
    "d": 86400.0,
    "w": 604800.0,
    "month": 2629800.0,
    "y": 31557600.0,
}
_NS: Final = 1_000_000_000
_FAILED_ROW_MARKERS: Final = ("●", "*", "×")


class UnitClass(StrEnum):
    TIMEOUT = "TIMEOUT"
    MEMORY_CEILING_SUSPECT = "MEMORY_CEILING_SUSPECT"
    OOM = "OOM"
    NOFILE_EXHAUSTED = "NOFILE_EXHAUSTED"
    EXIT_CODE = "EXIT_CODE"
    SIGNAL = "SIGNAL"
    UNHEALABLE = "UNHEALABLE"
    TRANSIENT_ADHOC = "TRANSIENT_ADHOC"
    EXPECTED_FAILURE_SUSPECT = "EXPECTED_FAILURE_SUSPECT"
    WATCHDOG = "WATCHDOG"
    #: A ``run-*`` transient gone from the snapshot (``--collect``, reset, failed in between).
    UNRESOLVED_TRANSIENT = "UNRESOLVED_TRANSIENT"


#: G5, the journal's ``UNIT_RESULT`` to a class. Any other value is UNHEALABLE plus a WARN.
UNIT_RESULT_CLASS: Final[Mapping[str, UnitClass]] = {
    "exit-code": UnitClass.EXIT_CODE,
    "signal": UnitClass.SIGNAL,
    "core-dump": UnitClass.SIGNAL,
    "watchdog": UnitClass.WATCHDOG,
    "timeout": UnitClass.TIMEOUT,
    "oom-kill": UnitClass.OOM,
    "start-limit-hit": UnitClass.UNHEALABLE,
    "resources": UnitClass.UNHEALABLE,
}
_CRITICAL: Final = frozenset(
    {
        UnitClass.TIMEOUT,
        UnitClass.MEMORY_CEILING_SUSPECT,
        UnitClass.OOM,
        UnitClass.NOFILE_EXHAUSTED,
        UnitClass.EXIT_CODE,
        UnitClass.SIGNAL,
        UnitClass.UNHEALABLE,
        UnitClass.WATCHDOG,
    }
)


class Ownership(StrEnum):
    OWNED = "OWNED"
    FOREIGN = "FOREIGN"
    #: No show block to judge by: treated as ours (WARNING), never as foreign.
    UNRESOLVED = "UNRESOLVED"


class WorktreesUnavailable(Exception):
    """``git worktree list`` could not answer: ownership of a ``run-*`` unit is unknown."""


@dataclass(frozen=True, slots=True)
class FailureEntry:
    """One unit-failed journal entry."""

    unit: str
    invocation_id: str
    unit_result: str
    ts_us: int
    cursor: str


@dataclass(frozen=True, slots=True)
class UnitFacts:
    """What is known about the failed invocation; ``None`` is unknown, never zero."""

    wall_ns: int | None = None
    cpu_usage_ns: int | None = None
    memory_peak: int | None = None
    memory_swap_peak: int | None = None
    memory_high: int | None = None
    exit_status: int | None = None


@dataclass(frozen=True, slots=True)
class Classification:
    unit_class: UnitClass
    detector: str
    action: str
    severity: str
    warn: str


def parse_failure_line(line: str) -> FailureEntry:
    """One ``journalctl -o json`` line of a unit-failed entry; ``ValueError`` when malformed."""
    try:
        raw = json.loads(line)
    except ValueError:
        raise ValueError("journal line is not json") from None
    if not isinstance(raw, dict):
        raise ValueError("journal line is not an object")  # noqa: TRY004 - callers catch ValueError
    unit, inv = raw.get("USER_UNIT"), raw.get("USER_INVOCATION_ID")
    result, ts, cursor = (
        raw.get("UNIT_RESULT"),
        raw.get("__REALTIME_TIMESTAMP"),
        raw.get("__CURSOR"),
    )
    if raw.get("MESSAGE_ID", MESSAGE_ID_UNIT_FAILED) != MESSAGE_ID_UNIT_FAILED:
        raise ValueError("not a unit-failed entry")
    if not (isinstance(unit, str) and unit and isinstance(result, str) and result):
        raise ValueError("entry lacks USER_UNIT or UNIT_RESULT")
    if not (isinstance(ts, str) and ts.isdigit() and isinstance(cursor, str) and cursor):
        raise ValueError("entry lacks a timestamp or cursor")
    if not (isinstance(inv, str) and _INVOCATION_RE.fullmatch(inv)):
        # Never poison the batch: a stable synthetic key, so the entry is still classified.
        inv = "noinv-" + hashlib.sha256(cursor.encode()).hexdigest()[:16]
    return FailureEntry(unit, inv, result, int(ts), cursor)


# --------------------------------------------------------------------------- systemctl text


def parse_show_blocks(text: str) -> dict[str, dict[str, str]]:
    """``systemctl show`` output (blank-line separated blocks of ``Key=Value``) keyed by ``Id``."""
    blocks: dict[str, dict[str, str]] = {}
    for chunk in re.split(r"\n\s*\n", text):
        props: dict[str, str] = {}
        for line in chunk.splitlines():
            key, sep, value = line.partition("=")
            if sep and key:
                props[key] = value
        unit = props.get("Id")
        if unit:
            blocks[unit] = props
    return blocks


def parse_failed_list(text: str) -> tuple[str, ...]:
    """The unit names of ``list-units --failed --all --plain --no-legend`` output."""
    names: list[str] = []
    for line in text.splitlines():
        tokens = [t for t in line.split() if t not in _FAILED_ROW_MARKERS]
        if tokens:
            names.append(tokens[0])
    return tuple(names)


def parse_timespan_ns(text: str) -> int | None:
    """A ``systemctl`` timespan (``15min``, ``1h 30min``, ``900ms``) in ns; else ``None``."""
    value = text.strip()
    if not value or value == "infinity":
        return None
    parts = _TIMESPAN_PART.findall(value)
    if not parts or _TIMESPAN_PART.sub("", value).strip():
        return None
    return int(sum(float(n) * _TIMESPAN_S[unit] for n, unit in parts) * _NS)


def _int_or_none(text: str | None) -> int | None:
    if text is None or not text.strip().isdigit():
        return None
    return int(text.strip())


def facts_from_block(block: Mapping[str, str] | None, entry: FailureEntry) -> UnitFacts:
    """Facts for ``entry`` from the unit's show block.

    ``MemoryHigh`` and ``TimeoutStartUSec`` are unit configuration, valid for any invocation. The
    peaks and ``ExecMainStatus`` describe the *current* invocation only, so they count only when
    the block's ``InvocationID`` is the failed one.
    """
    if not block:
        return UnitFacts()
    facts = UnitFacts(
        wall_ns=parse_timespan_ns(block.get("TimeoutStartUSec", ""))
        if entry.unit_result == "timeout"
        else None,
        memory_high=_int_or_none(block.get("MemoryHigh")),
    )
    if block.get("InvocationID") != entry.invocation_id:
        return facts
    return replace(
        facts,
        exit_status=_int_or_none(block.get("ExecMainStatus")),
        memory_peak=_int_or_none(block.get("MemoryPeak")),
        memory_swap_peak=_int_or_none(block.get("MemorySwapPeak")),
    )


def memory_signal(facts: UnitFacts) -> bool:
    """Swap was used, or the peak reached 90 percent of ``MemoryHigh`` (L-49)."""
    if facts.memory_swap_peak is not None and facts.memory_swap_peak > 0:
        return True
    high, peak = facts.memory_high, facts.memory_peak
    return high is not None and peak is not None and peak * 10 >= high * 9


def low_cpu(facts: UnitFacts) -> bool:
    """CPU time was a small part of the wall time; unknown CPU counts as low (page, not hide)."""
    if facts.cpu_usage_ns is None or not facts.wall_ns:
        return True
    return facts.cpu_usage_ns / facts.wall_ns < LOW_CPU_RATIO


def classify(
    entry: FailureEntry,
    facts: UnitFacts | None,
    *,
    transient: bool = False,
    suspect: bool = False,
    unresolved: bool = False,
) -> Classification:
    """The class, detector, action and severity of one unit-failed entry."""
    known = facts if facts is not None else UnitFacts()
    warn = ""
    unit_class = UNIT_RESULT_CLASS.get(entry.unit_result)
    if unit_class is None:
        unit_class = UnitClass.UNHEALABLE
        warn = f"unknown_unit_result:{entry.unit_result}"
        _LOG.warning("unit_health unknown UNIT_RESULT %r for %s", entry.unit_result, entry.unit)
    detector = DETECTOR_UNHEALABLE
    action = "ALERT"
    if unit_class is UnitClass.WATCHDOG:
        if entry.unit in WATCHDOG_DAEMON_UNITS:
            detector = DETECTOR_WATCHDOG
        else:
            unit_class = UnitClass.SIGNAL
    elif unit_class is UnitClass.TIMEOUT and memory_signal(known) and low_cpu(known):
        unit_class = UnitClass.MEMORY_CEILING_SUSPECT
    severity = "CRITICAL" if unit_class in _CRITICAL else "WARNING"
    if suspect and unit_class is UnitClass.EXIT_CODE:
        unit_class, severity = UnitClass.EXPECTED_FAILURE_SUSPECT, "WARNING"
    if transient and unit_class not in {UnitClass.OOM, UnitClass.MEMORY_CEILING_SUSPECT}:
        unit_class, severity = UnitClass.TRANSIENT_ADHOC, "WARNING"
    if unresolved:
        unit_class, severity = UnitClass.UNRESOLVED_TRANSIENT, "WARNING"
    return Classification(unit_class, detector, action, severity, warn)


# --------------------------------------------------------------------------- scope


def _run_text(block: Mapping[str, str]) -> str:
    parts = (block.get(k, "") for k in ("Description", "ExecStart", "WorkingDirectory"))
    return " ".join(parts).strip()


def _in_repo(text: str) -> bool:
    padded = text + " "
    return REPO_PREFIX in padded or REPO_PREFIX.rstrip("/") + " " in padded


def needs_worktrees(unit: str, block: Mapping[str, str]) -> bool:
    """Only an undecided ``run-*`` unit with a non-repo path needs the worktree list."""
    if not _RUN_UNIT_RE.fullmatch(unit) or unit.startswith(FOREIGN_UNIT_PREFIXES):
        return False
    text = _run_text(block)
    return bool(text) and not _in_repo(text)


def ownership(unit: str, block: Mapping[str, str], worktrees: Sequence[str]) -> Ownership:
    """G13: ``breezy-*`` units are ours; a ``run-*`` transient is ours when its Description,
    ExecStart or WorkingDirectory names the repo path or a listed worktree. With no block (or no
    path property at all) it is ``UNRESOLVED``, never foreign. Everything else is foreign."""
    if unit.startswith(FOREIGN_UNIT_PREFIXES):
        return Ownership.FOREIGN
    if _BREEZY_UNIT_RE.fullmatch(unit):
        return Ownership.OWNED
    if _RUN_UNIT_RE.fullmatch(unit):
        text = _run_text(block)
        if not text:
            return Ownership.UNRESOLVED
        padded = text + " "
        roots = [w.rstrip("/") for w in worktrees if w.strip("/")]
        if _in_repo(text) or any(r + "/" in padded or r + " " in padded for r in roots):
            return Ownership.OWNED
    return Ownership.FOREIGN


def is_transient(unit: str, block: Mapping[str, str]) -> bool:
    return block.get("Transient") == "yes" or unit.startswith("run-")


def is_explained(
    class_body: Mapping[str, object] | None,
    action_body: Mapping[str, object] | None,
    delivered: Callable[[str, str], bool],
) -> bool:
    """Explained = a classification, a proven action, and never an EXPECTED_FAILURE_SUSPECT."""
    if class_body is None or action_body is None:
        return False
    if class_body.get("unit_class") in {UnitClass.EXPECTED_FAILURE_SUSPECT, "UNREADABLE"}:
        return False
    event, site = action_body.get("event"), action_body.get("site")
    return isinstance(event, str) and isinstance(site, str) and delivered(event, site)
