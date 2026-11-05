"""AUT-6 node-local detectors (plan r15 sections 3.2 #4, #5 and 3.3.2).

``PermitLapsedDetector`` judges one integer, the order permit's ``expires_at_ns`` handed in at
composition through ``read_expiry_ns``. It never holds, reads or builds the permit object that
authorises orders: a value that is not a plain non-negative ``int`` is an unreadable observation.
Its veto reason is ``permit_lapsed``; AUT-1's writer records the C1 ``DetectorEvent`` from the
state, and the page decision (``page_event``) is returned for the caller to deliver.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Final, NamedTuple

from breezy.persistence.autonomy.pins import ALERT_CANARY_MAX_AGE_H, WATCH_TICK_STALE_S
from breezy.persistence.autonomy.plugin import DetectorKind
from breezy.persistence.autonomy.veto import VetoReason
from breezy.runtime.alert_outbox import read_armed_marker

__all__ = ["AlertsUndeliverableDetector", "PermitLapsedDetector", "PermitObservation"]

_NS_PER_S: Final = 1_000_000_000
_SECONDS_PER_DAY: Final = 86_400
#: The B1 decision window, UTC: [17:10Z, 01:00Z). It spans midnight.
_WINDOW_START_S: Final = 17 * 3600 + 10 * 60
_WINDOW_END_S: Final = 3600
_PAGE_LAPSED: Final = "permit_lapsed"
_PAGE_UNKNOWN: Final = "aut6_detector_unknown_persistent"
_PAGE_UNDELIVERABLE: Final = "alerts_undeliverable"
_LISTING_CACHE_NS: Final = 600 * _NS_PER_S
_MAX_AGE_NS: Final = ALERT_CANARY_MAX_AGE_H * 3600 * _NS_PER_S
#: ``<ts_ns>_<writer>_<d|f>.json``: the only names a delivery record can have.
_RECORD_RE: Final = re.compile(r"(\d+)_[a-z0-9_]{1,64}_d\.json\Z")
_RECORD_MAX_BYTES: Final = 4096
#: A listing reads at most this many delivered records before it gives up (fail closed).
_MAX_RECORD_READS: Final = 512


class PermitObservation(NamedTuple):
    """One judgement: the C1 state, a detail, the veto (or ``None``) and the page to send."""

    state: str
    detail: str
    veto: VetoReason | None
    page_event: str | None


def _in_b1_window(now_ns: int) -> bool:
    second_of_day = (now_ns // _NS_PER_S) % _SECONDS_PER_DAY
    return second_of_day >= _WINDOW_START_S or second_of_day < _WINDOW_END_S


class _UnknownTracker:
    """UNKNOWN for at most ``WATCH_TICK_STALE_S``, then the veto, with one page per episode."""

    def __init__(self) -> None:
        self._since_ns: int | None = None
        self._paged = False

    def clear(self) -> None:
        self._since_ns = None
        self._paged = False

    def observe(self, now_ns: int, veto: VetoReason) -> PermitObservation:
        if self._since_ns is None:
            self._since_ns = now_ns
        if now_ns - self._since_ns <= WATCH_TICK_STALE_S * _NS_PER_S:
            return PermitObservation("UNKNOWN", "read_error", None, None)
        page = None if self._paged else _PAGE_UNKNOWN
        self._paged = True
        return PermitObservation("UNKNOWN", "persistent", veto, page)


class PermitLapsedDetector:
    """NODE_LOCAL #4: the permit has lapsed (``now_ns > expiry``) => ``permit_lapsed`` veto."""

    id: Final = "permit_lapsed"
    kind: Final = DetectorKind.NODE_LOCAL

    def __init__(self, *, read_expiry_ns: Callable[[], int | None]) -> None:
        self._read_expiry_ns = read_expiry_ns
        self._lapsed = False
        self._unknown = _UnknownTracker()

    def evaluate(self, now_ns: int) -> VetoReason | None:
        return self.observe(now_ns).veto

    def observe(self, now_ns: int) -> PermitObservation:
        try:
            expiry = self._read_expiry_ns()
        except Exception:  # noqa: BLE001 - any read failure is an UNKNOWN observation
            return self._unknown.observe(now_ns, VetoReason.PERMIT_LAPSED)
        if expiry is not None and (type(expiry) is not int or expiry < 0):
            return self._unknown.observe(now_ns, VetoReason.PERMIT_LAPSED)
        self._unknown.clear()
        if expiry is None:
            self._lapsed = False
            return PermitObservation("AGREE", "no_permit", None, None)
        if now_ns <= expiry:
            self._lapsed = False
            return PermitObservation("AGREE", "valid", None, None)
        page = _PAGE_LAPSED if not self._lapsed and _in_b1_window(now_ns) else None
        self._lapsed = True
        return PermitObservation("DISAGREE", "lapsed", VetoReason.PERMIT_LAPSED, page)


def _day_dir(root: Path, instant_ns: int) -> Path:
    day = dt.datetime.fromtimestamp(instant_ns / 1e9, tz=dt.UTC).date()
    return root / day.isoformat()


def _is_canary_or_critical(path: Path) -> bool:
    """A delivered record body with ``attempt_kind=canary`` or ``severity=CRITICAL``."""
    try:
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode) or info.st_size > _RECORD_MAX_BYTES:
            return False
        body = json.loads(path.read_bytes())
    except (OSError, ValueError):
        return False
    return (
        isinstance(body, dict)
        and body.get("delivered") is True
        and (body.get("attempt_kind") == "canary" or body.get("severity") == "CRITICAL")
    )


def _record_instants(directory: Path) -> list[tuple[int, Path]]:
    """Delivered-record names in ``directory`` as ``(ts_ns, path)``; absent or unreadable: none."""
    try:
        names = os.listdir(directory)
    except OSError:
        return []
    found = []
    for name in names:
        match = _RECORD_RE.match(name)
        if match is not None:
            found.append((int(match.group(1)), directory / name))
    return found


def _newest_delivery_ns(root: Path, now_ns: int) -> int | None:
    """The newest delivered canary or CRITICAL record in today's and yesterday's directories."""
    candidates = []
    for instant in (now_ns, now_ns - _SECONDS_PER_DAY * _NS_PER_S):
        candidates += _record_instants(_day_dir(root, instant))
    candidates.sort(key=lambda item: item[0], reverse=True)
    for ts_ns, path in candidates[:_MAX_RECORD_READS]:
        if _is_canary_or_critical(path):
            return ts_ns
    return None


class AlertsUndeliverableDetector:
    """NODE_LOCAL #5: no delivered canary or CRITICAL for 26 h => ``alerts_undeliverable`` veto.

    Armed by the write-once marker; the listing (and the marker read) is cached for 600 s. A
    delivered drill record counts, because the receiver really answered 2xx.
    """

    id: Final = "alerts_undeliverable"
    kind: Final = DetectorKind.NODE_LOCAL

    def __init__(self, *, alerts_root: Path) -> None:
        self._root = alerts_root
        self._fetched_ns: int | None = None
        self._armed = False
        self._newest_ns: int | None = None
        self._vetoed = False
        self._unknown = _UnknownTracker()

    def evaluate(self, now_ns: int) -> VetoReason | None:
        return self.observe(now_ns).veto

    def observe(self, now_ns: int) -> PermitObservation:
        try:
            self._refresh(now_ns)
        except Exception:  # noqa: BLE001 - any read failure is an UNKNOWN observation
            return self._unknown.observe(now_ns, VetoReason.ALERTS_UNDELIVERABLE)
        self._unknown.clear()
        if not self._armed:
            self._vetoed = False
            return PermitObservation("AGREE", "unarmed", None, None)
        newest = self._newest_ns
        if newest is not None and now_ns - newest < _MAX_AGE_NS:
            self._vetoed = False
            return PermitObservation("AGREE", "delivered", None, None)
        page = None if self._vetoed else _PAGE_UNDELIVERABLE
        self._vetoed = True
        return PermitObservation("DISAGREE", "undeliverable", VetoReason.ALERTS_UNDELIVERABLE, page)

    def _refresh(self, now_ns: int) -> None:
        if self._fetched_ns is not None and now_ns - self._fetched_ns < _LISTING_CACHE_NS:
            return
        marker = read_armed_marker(self._root)
        self._armed = marker is not None
        self._newest_ns = _newest_delivery_ns(self._root, now_ns) if self._armed else None
        self._fetched_ns = now_ns
