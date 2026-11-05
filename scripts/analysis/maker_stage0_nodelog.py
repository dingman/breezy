"""MAKER-S2 WP1: node-log scanning for the report-only overlay and the full-day-outage screen.

Plan r4 delta (d). Node logs are the node's Popen stdout FILES (never journald). Two line shapes
matter; both are the ``breezy.app.trade.boot`` logger's, formatted by ``_BOOT_LOG_FORMAT`` in
``src/breezy/app/trade.py:222`` (``%(asctime)s [%(levelname)s] %(name)s: %(message)s``):

* BOOT   ``boot_family_declared id=<family>`` -- the FIRST boot line (``trade.py:1316-1319``),
  emitted before either permit is minted, so a boot that dies at permit mint still carries it.
* PERMIT ``live-trading permit issued issued_at_ns=<n> expires_at_ns=<n> ttl_s=<n>``
  (``trade.py:1385-1390``; the supervisor's own matcher is ``_PERMIT_ISSUED_RE`` in
  ``runtime/trade_supervisor_core.py:794``, its marker ``PERMIT_ISSUED_MARKER`` :94).

``asctime`` is host-local, so it is READ as UTC and VERIFIED: a log whose first stamped line is
not within :data:`FILENAME_TOLERANCE_NS` (120 s) of the UTC stamp in its own name
(``breezy-trade-YYYYMMDDTHHMMSSZ.log``) -- or whose name carries no such stamp -- is rejected and
counts as ``NODE_LOG_ABSENT`` with a recorded reason. Permit instants come from the exact
``issued_at_ns`` / ``expires_at_ns`` fields. A log's SPAN uses every timestamped line (these, and
the Nautilus ``...Z`` lines through ``capture_node_log_io.ts_ns``).

Pinned readings of a trading-day window ``[start, end)``:

* ``NODE_LOG_ABSENT`` unless the merged spans of the usable files FULLY cover it. The supervisor's
  launch-window grace (``LAUNCH_WINDOW_END - LAUNCH``, 10 min) lets a span start that late after
  ``start`` ONLY when the file's first stamped line is the boot line;
* ``OUTAGE`` when covered and no usable boot line is inside the window, no permit's validity
  ``[issued, expires)`` meets it and no boot before the window sits in a file that runs to the
  window end (an orders-off node prints boot lines and no permit lines);
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
    "FILENAME_TOLERANCE_NS",
    "LOG_START_GRACE_NS",
    "PERMIT_LINE_RE",
    "LogStatus",
    "NodeLogScan",
    "PermitLine",
    "boot_minted_permit",
    "boot_to_permit_latencies_ns",
    "boots_in_window",
    "boots_without_permit",
    "classify_day",
    "covers_window",
    "node_up_at_start",
    "permit_meets_window",
    "scan_node_log",
    "usable",
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
_FILENAME_RE: Final[re.Pattern[str]] = re.compile(r"^breezy-trade-(\d{8}T\d{6})Z\.log$")
FILENAME_TOLERANCE_NS: Final[int] = 120 * NS
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
    first_is_boot: bool = False
    rejected: str | None = None


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


def _filename_ns(path: Path) -> int | None:
    match = _FILENAME_RE.match(path.name)
    if match is None:
        return None
    moment = dt.datetime.strptime(match.group(1), "%Y%m%dT%H%M%S").replace(tzinfo=dt.UTC)
    return int(moment.timestamp()) * NS


def _utc_rejection(path: Path, first_stamp: int | None) -> str | None:
    """Why the log's stamps cannot be trusted as UTC, or ``None`` (empty logs pass: no span)."""
    if first_stamp is None:
        return None
    named = _filename_ns(path)
    if named is None:
        return f"file name {path.name!r} carries no breezy-trade-YYYYMMDDTHHMMSSZ.log UTC stamp"
    if abs(first_stamp - named) > FILENAME_TOLERANCE_NS:
        offset_s = (first_stamp - named) / NS
        return f"first stamp is {offset_s:.0f} s from the file name's UTC stamp (> 120 s)"
    return None


def scan_node_log(path: Path) -> NodeLogScan:
    """Stream ``path`` (bounded memory): span, boot instants and permit lines."""
    first: int | None = None
    last: int | None = None
    first_is_boot = False
    boots: list[int] = []
    permits: list[PermitLine] = []
    for line in read_lines(path):
        stamp = _line_ns(line.raw)
        if stamp is None:
            continue
        text = line.raw.decode("utf-8", "replace")
        is_boot = BOOT_LINE_RE.match(text) is not None
        if first is None:
            first, first_is_boot = stamp, is_boot
        first = min(first, stamp)
        last = stamp if last is None else max(last, stamp)
        if is_boot:
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
        first_is_boot=first_is_boot,
        rejected=_utc_rejection(path, first),
    )


def usable(scans: Iterable[NodeLogScan]) -> list[NodeLogScan]:
    """The scans whose stamps passed the UTC check (rejected logs count as absent)."""
    return [scan for scan in scans if scan.rejected is None]


def _merged_spans(scans: Iterable[NodeLogScan]) -> list[tuple[int, int, bool]]:
    """Merged ``(first, last, grace_eligible)``; eligibility is the earliest file's boot-first."""
    spans = sorted(
        (s.first_ns, s.last_ns, s.first_is_boot)
        for s in usable(scans)
        if s.first_ns is not None and s.last_ns is not None
    )
    merged: list[tuple[int, int, bool]] = []
    for start, end, boot_first in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end), merged[-1][2])
        else:
            merged.append((start, end, boot_first))
    return merged


def covers_window(scans: Iterable[NodeLogScan], window: tuple[int, int]) -> bool:
    """The merged usable spans FULLY cover ``[start, end)``.

    The launch grace admits a span starting up to ``LOG_START_GRACE_NS`` after ``start`` only
    when that span's first stamped line is the boot line.
    """
    start, end = window
    return any(
        hi >= end and (lo <= start or (boot_first and lo <= start + LOG_START_GRACE_NS))
        for lo, hi, boot_first in _merged_spans(scans)
    )


def boots_in_window(scans: Iterable[NodeLogScan], window: tuple[int, int]) -> list[int]:
    return sorted({b for s in usable(scans) for b in s.boots if window[0] <= b < window[1]})


def permit_meets_window(permit: PermitLine, window: tuple[int, int]) -> bool:
    """Validity ``[issued, expires)`` meets ``[start, end)``."""
    return permit.issued_ns < window[1] and permit.expires_ns > window[0]


def node_up_at_start(scans: Iterable[NodeLogScan], window: tuple[int, int]) -> bool:
    """The node was already running when the window opened.

    Either a permit issued before ``start`` is still valid then, or a boot line precedes
    ``start`` in a file that runs through the window end (orders-off nodes print no permit).
    """
    start, end = window
    for scan in usable(scans):
        if any(p.issued_ns < start and permit_meets_window(p, window) for p in scan.permits):
            return True
        if scan.last_ns is not None and scan.last_ns >= end and any(b < start for b in scan.boots):
            return True
    return False


def classify_day(scans: Sequence[NodeLogScan], window: tuple[int, int]) -> LogStatus:
    """``NODE_LOG_ABSENT`` / ``OUTAGE`` / ``LIVE`` for one trading-day window."""
    live = usable(scans)
    if not covers_window(live, window):
        return LogStatus.NODE_LOG_ABSENT
    if boots_in_window(live, window) or node_up_at_start(live, window):
        return LogStatus.LIVE
    if any(permit_meets_window(p, window) for s in live for p in s.permits):
        return LogStatus.LIVE
    return LogStatus.OUTAGE


def boot_minted_permit(scans: Iterable[NodeLogScan], boot_ns: int) -> bool:
    """A permit line lands at or after ``boot_ns`` and before the next boot line (any file)."""
    live = usable(scans)
    later_boots = [b for s in live for b in s.boots if b > boot_ns]
    ceiling = min(later_boots, default=None)
    return any(
        p.line_ns >= boot_ns and (ceiling is None or p.line_ns < ceiling)
        for s in live
        for p in s.permits
    )


def boots_without_permit(scans: Iterable[NodeLogScan], window: tuple[int, int]) -> list[int]:
    """Report-only: in-window boots that died before minting a permit."""
    live = usable(scans)
    return [b for b in boots_in_window(live, window) if not boot_minted_permit(live, b)]


def boot_to_permit_latencies_ns(scans: Iterable[NodeLogScan]) -> list[int]:
    """Report-only: per boot line, the delay to the next permit line (never a schedule input)."""
    latencies: list[int] = []
    for scan in usable(scans):
        stamps = sorted(p.line_ns for p in scan.permits)
        for boot in scan.boots:
            nxt = next((p for p in stamps if p >= boot), None)
            if nxt is not None:
                latencies.append(nxt - boot)
    return latencies
