"""AUT-1 node-log reading primitives (plan r12 section 3.11; build rulings WP5-R3, WP5-R4).

The bounded line reader, the timestamp reader and the report types shared by the node-log parser's
modules. Read-only, stdlib only.

``read_lines`` never holds more than ``MAX_LINE_BYTES`` of one line. A longer line is truncated to
its head and its remainder is drained in bounded chunks that are scanned for the writer-failure
markers (with an overlap, so a marker straddling a chunk edge is still found): a failure text must
never hide behind a long line.
"""

import calendar
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Final, NamedTuple

__all__ = [
    "CAUSE_BAD_FIELDS",
    "CAUSE_INVALID_LOG_NAME",
    "CAUSE_LINE_TOO_LONG",
    "CAUSE_NODE_LOG_MISSING",
    "CAUSE_NO_MATCH",
    "CAUSE_TORN_TAIL",
    "CAUSE_UNDECODABLE",
    "CAUSE_UNKNOWN_KIND",
    "CAUSE_UNMATCHED_LOG_IN_WINDOW",
    "FAILURE_RE",
    "MAX_LINE_BYTES",
    "MAX_STORED_REPORTS",
    "NS",
    "LogFinding",
    "NodeLogUnreadable",
    "RawLine",
    "UnparseableLine",
    "excerpt",
    "read_lines",
    "ts_matches",
    "ts_ns",
    "unparseable",
]

#: A line longer than this is not read whole; its head is classified and the rest drained.
MAX_LINE_BYTES: Final[int] = 1 << 20
#: Stored reports per category; the exact totals stay exact beyond it.
MAX_STORED_REPORTS: Final[int] = 1000
NS: Final[int] = 1_000_000_000
_EXCERPT_CHARS: Final[int] = 160

CAUSE_TORN_TAIL: Final[str] = "torn_tail"
CAUSE_LINE_TOO_LONG: Final[str] = "line_too_long"
CAUSE_UNDECODABLE: Final[str] = "undecodable"
CAUSE_NO_MATCH: Final[str] = "no_match"
CAUSE_BAD_FIELDS: Final[str] = "bad_fields"
CAUSE_UNKNOWN_KIND: Final[str] = "unknown_kind"
CAUSE_NODE_LOG_MISSING: Final[str] = "node_log_missing"
CAUSE_INVALID_LOG_NAME: Final[str] = "invalid_log_name"
CAUSE_UNMATCHED_LOG_IN_WINDOW: Final[str] = "unmatched_log_in_window"

#: The three writer-failure texts: Nautilus ``persistence/writer.py`` (``Failed to serialize``,
#: ``Can't find writer for cls``) and capture's own ``CAPTURE_PUBLISH_FAILED``.
FAILURE_RE: Final[re.Pattern[bytes]] = re.compile(
    rb"Failed to serialize|Can't find writer for cls|CAPTURE_PUBLISH_FAILED"
)
_FAILURE_OVERLAP: Final[int] = len(b"Can't find writer for cls") - 1
_ANSI_RE: Final[re.Pattern[str]] = re.compile(r"\x1b\[[0-9;]*m")
_TS_RE: Final[re.Pattern[bytes]] = re.compile(
    rb"^(?:\x1b\[1m)?(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(?:\.(\d{1,9}))?Z"
)


class NodeLogUnreadable(Exception):
    """A log could not be opened or read. ``cause`` is the OS error class name: no path, no text."""

    def __init__(self, path: Path, cause: str) -> None:
        super().__init__(cause)
        self.path = path
        self.cause = cause


@dataclass(frozen=True, slots=True)
class UnparseableLine:
    """A line the parser had to report instead of classify. ``excerpt`` is ANSI-stripped, capped."""

    line_no: int
    marker: str
    cause: str
    excerpt: str


@dataclass(frozen=True, slots=True)
class LogFinding:
    """A file-level finding. It names the file (basename only) and never a path."""

    name: str
    cause: str


class RawLine(NamedTuple):
    line_no: int
    #: The line without its terminator; if truncated, its first ``MAX_LINE_BYTES + 1`` bytes.
    raw: bytes
    terminated: bool
    truncated: bool
    #: Truncated lines only: the failure marker text found in the drained remainder, if any.
    tail_failure: bytes | None


def _drain(fh: BinaryIO, head: bytes) -> tuple[bool, bytes | None]:
    """Consume the rest of an overlong line; return ``(terminated, failure_marker_or_None)``."""
    carry = head[-_FAILURE_OVERLAP:]
    found: bytes | None = None
    while True:
        rest = fh.readline(MAX_LINE_BYTES)
        if not rest:
            return False, found
        if found is None:
            window = carry + rest
            hit = FAILURE_RE.search(window)
            found = hit.group(0) if hit else None
            carry = window[-_FAILURE_OVERLAP:]
        if rest.endswith(b"\n"):
            return True, found


def read_lines(path: Path) -> Iterator[RawLine]:
    """Yield the lines of ``path`` with bounded memory. Raises ``NodeLogUnreadable``."""
    try:
        with path.open("rb") as fh:
            line_no = 0
            while True:
                chunk = fh.readline(MAX_LINE_BYTES + 1)
                if not chunk:
                    return
                line_no += 1
                if len(chunk) > MAX_LINE_BYTES and not chunk.endswith(b"\n"):
                    terminated, found = _drain(fh, chunk)
                    yield RawLine(line_no, chunk, terminated, True, found)
                    continue
                yield RawLine(line_no, chunk.rstrip(b"\r\n"), chunk.endswith(b"\n"), False, None)
    except OSError as exc:
        raise NodeLogUnreadable(path, type(exc).__name__) from exc


def ts_matches(head: bytes) -> bool:
    """Whether ``head`` starts with a log timestamp."""
    return _TS_RE.match(head) is not None


def ts_ns(head: bytes) -> int | None:
    """The leading ``...Z`` timestamp as epoch nanoseconds, or None."""
    m = _TS_RE.match(head)
    if m is None:
        return None
    year, month, day, hour, minute, second = (int(g) for g in m.groups()[:6])
    try:
        seconds = calendar.timegm((year, month, day, hour, minute, second))
    except (ValueError, OverflowError):
        return None
    frac = (m.group(7) or b"0").ljust(9, b"0")
    return seconds * NS + int(frac)


def excerpt(raw: bytes) -> str:
    text = _ANSI_RE.sub("", raw[: _EXCERPT_CHARS * 4].decode("utf-8", "replace"))
    return text[:_EXCERPT_CHARS]


def unparseable(line_no: int, marker: str, cause: str, raw: bytes) -> UnparseableLine:
    return UnparseableLine(line_no, marker, cause, excerpt(raw))
