"""AUT-1 supervisor spawn events and the boot census (plan r12 section 3.11; WP0-R7, WP5-R4).

Exactly four supervisor events spawn a node:

* ``launched pid=`` (``trade_supervisor.py:1300``) and ``boot_retry_launched pid=`` (``:1633``) are
  logged AFTER the spawn;
* ``relaunching attempt=`` (``:1377``) and ``midday_relaunching phase=midday_watch attempt=``
  (``:1972``) are logged BEFORE it.

``launch_spawn_failed`` (``:1296``) spawns nothing. A relaunch whose spawn then raises
(``:1380``) leaves a ``relaunching`` event with no log: it reads as ``node_log_missing``, which is
correct, because no node and no log exist for it.

``match_spawns_to_logs`` pairs events 1:1, in time order, with node logs by the log's filename stamp
(``node_log_path``'s ``now``). The window depends on the kind: a pre-spawn event takes a stamp in
``[ts, ts + LOG_STAMP_MAX_LAG_S]`` and a post-spawn event one in
``[ts - POST_SPAWN_EARLY_S, ts + POST_SPAWN_LATE_S]``. Among the unused stamps in the window the
NEAREST wins. The pid is never a join key. A log left over inside any event's window is a warning.
"""

import datetime as dt
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from breezy.analysis.capture_node_log_io import (
    CAUSE_BAD_FIELDS,
    CAUSE_INVALID_LOG_NAME,
    CAUSE_NODE_LOG_MISSING,
    CAUSE_TORN_TAIL,
    CAUSE_UNMATCHED_LOG_IN_WINDOW,
    MAX_STORED_REPORTS,
    LogFinding,
    NodeLogUnreadable,
    UnparseableLine,
    read_lines,
)

__all__ = [
    "LOG_STAMP_MAX_LAG_S",
    "NO_SPAWN_EVENTS",
    "POST_SPAWN_EARLY_S",
    "POST_SPAWN_LATE_S",
    "PRE_SPAWN_EARLY_S",
    "PRE_SPAWN_EVENTS",
    "SPAWN_EVENTS",
    "NodeLogListing",
    "SpawnCensus",
    "SpawnEvent",
    "SpawnMatch",
    "SupervisorScan",
    "list_node_logs",
    "match_spawns_to_logs",
    "parse_supervisor_lines",
    "scan_supervisor_log",
]

SPAWN_EVENTS: Final[tuple[str, ...]] = (
    "launched",
    "boot_retry_launched",
    "relaunching",
    "midday_relaunching",
)
#: Logged before ``ports.spawn``; the others are logged after it.
PRE_SPAWN_EVENTS: Final[frozenset[str]] = frozenset({"relaunching", "midday_relaunching"})
NO_SPAWN_EVENTS: Final[tuple[str, ...]] = ("launch_spawn_failed",)

#: Pre-spawn: the stamp is ``now`` taken a moment before the event line; both truncate to whole
#: seconds, so the stamp may sit one second under the event. It runs up to the lag after it.
PRE_SPAWN_EARLY_S: Final[int] = 1
LOG_STAMP_MAX_LAG_S: Final[int] = 300
#: Post-spawn: the stamp precedes the spawn and its line.
POST_SPAWN_EARLY_S: Final[int] = 30
POST_SPAWN_LATE_S: Final[int] = 5

_NODE_LOG_NAME_RE: Final[re.Pattern[str]] = re.compile(r"^breezy-trade-(\d{8}T\d{6}Z)\.log$")
_SUPERVISOR_LINE_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<ts>\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ) INFO breezy\.runtime\.trade_supervisor "
    r"(?P<event>[a-z_]+)(?P<fields>(?: \w+=\S+)*)$"
)
_SPAWN_TOKEN_RE: Final[re.Pattern[str]] = re.compile(
    r"trade_supervisor (?:launched|boot_retry_launched|relaunching|midday_relaunching"
    r"|launch_spawn_failed)(?: |$)"
)
_EXCERPT_CHARS: Final[int] = 160


@dataclass(frozen=True, slots=True)
class SpawnEvent:
    line_no: int
    ts: dt.datetime
    event: str
    pid: int | None = None
    attempt: int | None = None
    phase: str | None = None


@dataclass(frozen=True, slots=True)
class SupervisorScan:
    spawns: tuple[SpawnEvent, ...]
    no_spawn_count: int
    unparseable: tuple[UnparseableLine, ...]
    unparseable_total: int


def _int_field(fields: Mapping[str, str], name: str) -> int | None:
    value = fields.get(name, "")
    return int(value) if value.isdigit() else None


def _spawn_event(
    line_no: int, when: dt.datetime, event: str, fields: Mapping[str, str]
) -> SpawnEvent | None:
    pid, attempt = _int_field(fields, "pid"), _int_field(fields, "attempt")
    phase = fields.get("phase")
    valid = {
        "launched": pid is not None,
        "boot_retry_launched": pid is not None,
        "relaunching": attempt is not None,
        "midday_relaunching": attempt is not None and phase is not None,
    }.get(event, False)
    if not valid:
        return None
    return SpawnEvent(line_no, when, event, pid=pid, attempt=attempt, phase=phase)


def _stamp_of(text: str) -> dt.datetime | None:
    """A ``YYYYmmddTHHMMSSZ`` or ``YYYY-mm-ddTHH:MM:SSZ`` stamp as UTC, or None if not a date."""
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return dt.datetime.strptime(text, fmt).replace(tzinfo=dt.UTC)
        except ValueError:
            continue
    return None


def _parse_supervisor(items: Iterable[tuple[int, str, bool]]) -> SupervisorScan:
    spawns: list[SpawnEvent] = []
    bad: list[UnparseableLine] = []
    bad_total = no_spawn = 0
    for line_no, text, terminated in items:
        if _SPAWN_TOKEN_RE.search(text) is None:
            continue
        m = _SUPERVISOR_LINE_RE.match(text) if terminated else None
        when = _stamp_of(m["ts"]) if m is not None else None
        if m is not None and when is not None and m["event"] in NO_SPAWN_EVENTS:
            no_spawn += 1
            continue
        parsed: SpawnEvent | None = None
        if m is not None and when is not None:
            fields = dict(kv.split("=", 1) for kv in m["fields"].split())
            parsed = _spawn_event(line_no, when, m["event"], fields)
        if parsed is not None:
            spawns.append(parsed)
            continue
        bad_total += 1
        if len(bad) < MAX_STORED_REPORTS:
            cause = CAUSE_BAD_FIELDS if terminated else CAUSE_TORN_TAIL
            bad.append(UnparseableLine(line_no, "spawn_event", cause, text[:_EXCERPT_CHARS]))
    return SupervisorScan(tuple(spawns), no_spawn, tuple(bad), bad_total)


def parse_supervisor_lines(lines: Iterable[str]) -> SupervisorScan:
    """Extract spawn events from supervisor log text (one complete line per item). A spawn line
    whose fields or timestamp do not parse is reported as ``bad_fields``, never raised."""
    return _parse_supervisor((n, text, True) for n, text in enumerate(lines, start=1))


def scan_supervisor_log(path: Path) -> SupervisorScan:
    """Read a supervisor log file. Raises ``NodeLogUnreadable``. An unterminated last spawn line is
    reported as ``torn_tail``."""
    return _parse_supervisor(
        (rl.line_no, rl.raw.decode("utf-8", "replace"), rl.terminated) for rl in read_lines(path)
    )


@dataclass(frozen=True, slots=True)
class SpawnMatch:
    event: SpawnEvent
    log_path: Path | None

    @property
    def cause(self) -> str | None:
        return CAUSE_NODE_LOG_MISSING if self.log_path is None else None


@dataclass(frozen=True, slots=True)
class SpawnCensus:
    matches: tuple[SpawnMatch, ...]
    unmatched_logs: tuple[Path, ...]
    #: Unmatched logs that lie inside some event's window (a likely mis-pairing): not errors.
    warnings: tuple[LogFinding, ...] = ()

    @property
    def missing(self) -> tuple[SpawnMatch, ...]:
        """Events with no log: each is ``ERROR node_log_missing``."""
        return tuple(m for m in self.matches if m.log_path is None)


@dataclass(frozen=True, slots=True)
class NodeLogListing:
    """The node logs of a directory, oldest first, and any name that looked like one but is not."""

    paths: tuple[Path, ...]
    findings: tuple[LogFinding, ...]


def _stamp(path: Path) -> dt.datetime | None:
    m = _NODE_LOG_NAME_RE.match(path.name)
    return _stamp_of(m[1]) if m is not None else None


def list_node_logs(log_dir: Path) -> NodeLogListing:
    """``breezy-trade-<stamp>.log`` files, oldest first. The supervisor's own logs share the prefix
    and never match. A name of that shape whose stamp is not a real date is an ``invalid_log_name``
    finding and is skipped. Raises ``NodeLogUnreadable`` if the directory cannot be listed."""
    try:
        names = sorted(p for p in log_dir.iterdir() if _NODE_LOG_NAME_RE.match(p.name))
    except OSError as exc:
        raise NodeLogUnreadable(log_dir, type(exc).__name__) from exc
    paths = tuple(p for p in names if _stamp(p) is not None)
    findings = tuple(LogFinding(p.name, CAUSE_INVALID_LOG_NAME) for p in names if _stamp(p) is None)
    return NodeLogListing(paths, findings)


def _window(event: SpawnEvent) -> tuple[dt.datetime, dt.datetime]:
    if event.event in PRE_SPAWN_EVENTS:
        return (
            event.ts - dt.timedelta(seconds=PRE_SPAWN_EARLY_S),
            event.ts + dt.timedelta(seconds=LOG_STAMP_MAX_LAG_S),
        )
    return (
        event.ts - dt.timedelta(seconds=POST_SPAWN_EARLY_S),
        event.ts + dt.timedelta(seconds=POST_SPAWN_LATE_S),
    )


def match_spawns_to_logs(events: Sequence[SpawnEvent], logs: Sequence[Path]) -> SpawnCensus:
    """Match each spawn event, in ``(ts, line_no)`` order, to the nearest unused node log in its
    per-kind window, 1:1. The pid is never consulted. Logs left over (a hand-launched node has no
    event) are reported; those inside an event's window are also warnings.

    Raises ``ValueError`` if a path is not a ``breezy-trade-<stamp>.log`` with a real stamp
    (``list_node_logs`` never returns one)."""
    stamped = [(s, p) for p in logs if (s := _stamp(p)) is not None]
    if len(stamped) != len(logs):
        raise ValueError("every path must be a breezy-trade-<stamp>.log node log")
    stamped.sort(key=lambda sp: sp[0])
    used = [False] * len(stamped)
    ordered = sorted(events, key=lambda e: (e.ts, e.line_no))
    matches: list[SpawnMatch] = []
    for event in ordered:
        low, high = _window(event)
        in_window = [i for i, (s, _p) in enumerate(stamped) if not used[i] and low <= s <= high]
        chosen: Path | None = None
        if in_window:
            best = min(in_window, key=lambda i: abs(stamped[i][0] - event.ts))
            used[best], chosen = True, stamped[best][1]
        matches.append(SpawnMatch(event, chosen))
    windows = [_window(e) for e in ordered]
    leftover = [(s, p) for i, (s, p) in enumerate(stamped) if not used[i]]
    warnings = tuple(
        LogFinding(p.name, CAUSE_UNMATCHED_LOG_IN_WINDOW)
        for s, p in leftover
        if any(low <= s <= high for low, high in windows)
    )
    return SpawnCensus(tuple(matches), tuple(p for _s, p in leftover), warnings)
