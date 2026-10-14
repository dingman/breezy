"""MAKER-S2 WP1: node-log scanning for the report-only overlay and the full-day-outage screen.

Plan r4 delta (d). Node logs are the node's Popen stdout FILES (never journald). Two line shapes
matter; both are the ``breezy.app.trade.boot`` logger's, formatted by ``_BOOT_LOG_FORMAT`` in
``src/breezy/app/trade.py:222`` (``%(asctime)s [%(levelname)s] %(name)s: %(message)s``):

* BOOT   ``boot_family_declared id=<family>`` -- the FIRST boot line (``trade.py:1316-1319``),
  emitted before either permit is minted, so a boot that dies at permit mint still carries it.
* PERMIT ``live-trading permit issued issued_at_ns=<n> expires_at_ns=<n> ttl_s=<n>``
  (``trade.py:1385-1390``; the supervisor's own matcher is ``_PERMIT_ISSUED_RE`` in
  ``runtime/trade_supervisor_core.py:794``, its marker ``PERMIT_ISSUED_MARKER`` :94).

``asctime`` is host-local; the discovery_pull fixture shows UTC (the line at 16:50:40,787 carries
``issued_at_ns`` for 16:50:40Z), so boot instants are read as UTC and permit instants come from
the exact ``issued_at_ns`` / ``expires_at_ns`` fields. A log's SPAN uses every timestamped line
(these, and the Nautilus ``...Z`` lines through ``capture_node_log_io.ts_ns``).

Status of a trading-day window ``[start, end)``:

* ``NODE_LOG_ABSENT`` unless the merged spans of the supplied files FULLY cover it (a start grace
  of the supervisor's launch window absorbs the first line landing after 16:50:00);
* ``OUTAGE`` when covered and no boot line is inside the window and no permit's validity
  ``[issued, expires)`` meets it (a node booted before 16:50Z shows only its permit);
* ``LIVE`` otherwise.
"""

from __future__ import annotations

import datetime as dt
import enum
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from breezy.analysis.capture_node_log_io import read_lines, ts_ns
from breezy.runtime.trade_supervisor_core import LAUNCH_UTC, LAUNCH_WINDOW_END_UTC
from scripts.analysis.maker_stage0_inputs import sha256_file

__all__ = [
    "BOOT_LINE_RE",
    "LOG_START_GRACE_NS",
    "PERMIT_LINE_RE",
    "LogStatus",
    "NodeLogScan",
    "PermitLine",
    "boot_to_permit_latencies_ns",
    "boots_in_window",
    "classify_day",
    "covers_window",
    "permit_meets_window",
    "scan_node_log",
]

NS: Final[int] = 1_000_000_000
_BOOT_PREFIX: Final[str] = (
    r"^(?P<ts>\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3}) \[INFO\] breezy\.app\.trade\.boot: "
)
BOOT_LINE_RE: Final[re.Pattern[str]] = re.compile(
    _BOOT_PREFIX + r"boot_family_declared id=(?P<family>\S+)$"
)
PERMIT_LINE_RE: Final[re.Pattern[str]] = re.compile(
    _BOOT_PREFIX + r"live-trading permit issued issued_at_ns=(?P<issued>\d+) "
    r"expires_at_ns=(?P<expires>\d+) ttl_s=(?P<ttl>\d+)$"
)
_ASCTIME_RE: Final[re.Pattern[bytes]] = re.compile(
    rb"^(\d{4})-(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d),(\d{3}) \["
)
#: The supervisor's launch window (16:50Z..17:00Z): a log whose first line lands this late after
#: the window opens still holds the in-window boot line, so it covers the start.
LOG_START_GRACE_NS: Final[int] = (
    (
        (LAUNCH_WINDOW_END_UTC.hour * 60 + LAUNCH_WINDOW_END_UTC.minute)
        - (LAUNCH_UTC.hour * 60 + LAUNCH_UTC.minute)
    )
    * 60
    * NS
)


class LogStatus(enum.Enum):
    LIVE = "LIVE"
    OUTAGE = "OUTAGE"
    NODE_LOG_ABSENT = "NODE_LOG_ABSENT"


@dataclass(frozen=True, slots=True)
class PermitLine:
    line_ns: int
    issued_ns: int
    expires_ns: int


@dataclass(frozen=True, slots=True)
class NodeLogScan:
    path: Path
    size: int
    sha256: str
    first_ns: int | None
    last_ns: int | None
    boots: tuple[int, ...]
    permits: tuple[PermitLine, ...]


def _asctime_ns(raw: bytes) -> int | None:
    match = _ASCTIME_RE.match(raw)
    if match is None:
        return None
    year, month, day, hour, minute, second, millis = (int(g) for g in match.groups())
    try:
        moment = dt.datetime(year, month, day, hour, minute, second, tzinfo=dt.UTC)
    except ValueError:
        return None
    return int(moment.timestamp()) * NS + millis * 1_000_000


def _line_ns(raw: bytes) -> int | None:
    stamp = _asctime_ns(raw)
    return stamp if stamp is not None else ts_ns(raw)


def scan_node_log(path: Path) -> NodeLogScan:
    """Stream ``path`` (bounded memory): span, boot instants and permit lines."""
    first: int | None = None
    last: int | None = None
    boots: list[int] = []
    permits: list[PermitLine] = []
    for line in read_lines(path):
        stamp = _line_ns(line.raw)
        if stamp is None:
            continue
        first = stamp if first is None else min(first, stamp)
        last = stamp if last is None else max(last, stamp)
        text = line.raw.decode("utf-8", "replace")
        if BOOT_LINE_RE.match(text):
            boots.append(stamp)
            continue
        permit = PERMIT_LINE_RE.match(text)
        if permit is not None:
            permits.append(PermitLine(stamp, int(permit["issued"]), int(permit["expires"])))
    return NodeLogScan(
        path=path,
        size=path.stat().st_size,
        sha256=sha256_file(path),
        first_ns=first,
        last_ns=last,
        boots=tuple(sorted(boots)),
        permits=tuple(sorted(permits, key=lambda p: p.issued_ns)),
    )


def _merged_spans(scans: Iterable[NodeLogScan]) -> list[tuple[int, int]]:
    spans = sorted(
        (s.first_ns, s.last_ns) for s in scans if s.first_ns is not None and s.last_ns is not None
    )
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def covers_window(scans: Iterable[NodeLogScan], window: tuple[int, int]) -> bool:
    """The merged log spans FULLY cover ``[start, end)`` (start grace applies)."""
    start, end = window
    return any(lo <= start + LOG_START_GRACE_NS and hi >= end for lo, hi in _merged_spans(scans))


def boots_in_window(scans: Iterable[NodeLogScan], window: tuple[int, int]) -> list[int]:
    return sorted({b for s in scans for b in s.boots if window[0] <= b < window[1]})


def permit_meets_window(permit: PermitLine, window: tuple[int, int]) -> bool:
    return permit.issued_ns < window[1] and permit.expires_ns > window[0]


def classify_day(scans: Sequence[NodeLogScan], window: tuple[int, int]) -> LogStatus:
    """``NODE_LOG_ABSENT`` / ``OUTAGE`` / ``LIVE`` for one trading-day window."""
    if not covers_window(scans, window):
        return LogStatus.NODE_LOG_ABSENT
    if boots_in_window(scans, window):
        return LogStatus.LIVE
    if any(permit_meets_window(p, window) for s in scans for p in s.permits):
        return LogStatus.LIVE
    return LogStatus.OUTAGE


def boot_to_permit_latencies_ns(scans: Iterable[NodeLogScan]) -> list[int]:
    """Report-only: per boot line, the delay to the next permit line (never a schedule input)."""
    latencies: list[int] = []
    for scan in scans:
        stamps = sorted(p.line_ns for p in scan.permits)
        for boot in scan.boots:
            nxt = next((p for p in stamps if p >= boot), None)
            if nxt is not None:
                latencies.append(nxt - boot)
    return latencies
