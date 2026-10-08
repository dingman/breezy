"""AUT-6 node-local detectors (plan r15 sections 3.2 #4 and 3.3.2).

``PermitLapsedDetector`` judges one integer, the order permit's ``expires_at_ns`` handed in at
composition through ``read_expiry_ns``. It never holds, reads or builds the permit object that
authorises orders: a value that is not a plain non-negative ``int`` is an unreadable observation.
Its veto reason is ``permit_lapsed``; AUT-1's writer records the C1 ``DetectorEvent`` from the
state, and the page decision (``page_event``) is returned for the caller to deliver.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final, NamedTuple

from breezy.persistence.autonomy.pins import WATCH_TICK_STALE_S
from breezy.persistence.autonomy.plugin import DetectorKind
from breezy.persistence.autonomy.veto import VetoReason

__all__ = ["PermitLapsedDetector", "PermitObservation"]

_NS_PER_S: Final = 1_000_000_000
_SECONDS_PER_DAY: Final = 86_400
#: The B1 decision window, UTC: [17:10Z, 01:00Z). It spans midnight.
_WINDOW_START_S: Final = 17 * 3600 + 10 * 60
_WINDOW_END_S: Final = 3600
_PAGE_LAPSED: Final = "permit_lapsed"
_PAGE_UNKNOWN: Final = "aut6_detector_unknown_persistent"


class PermitObservation(NamedTuple):
    """One judgement: the C1 state, a detail, the veto (or ``None``) and the page to send."""

    state: str
    detail: str
    veto: VetoReason | None
    page_event: str | None


def _in_b1_window(now_ns: int) -> bool:
    second_of_day = (now_ns // _NS_PER_S) % _SECONDS_PER_DAY
    return second_of_day >= _WINDOW_START_S or second_of_day < _WINDOW_END_S


class PermitLapsedDetector:
    """NODE_LOCAL #4: the permit has lapsed (``now_ns > expiry``) => ``permit_lapsed`` veto."""

    id: Final = "permit_lapsed"
    kind: Final = DetectorKind.NODE_LOCAL

    def __init__(self, *, read_expiry_ns: Callable[[], int | None]) -> None:
        self._read_expiry_ns = read_expiry_ns
        self._lapsed = False
        self._unknown_since_ns: int | None = None
        self._unknown_paged = False

    def evaluate(self, now_ns: int) -> VetoReason | None:
        return self.observe(now_ns).veto

    def observe(self, now_ns: int) -> PermitObservation:
        try:
            expiry = self._read_expiry_ns()
        except Exception:  # noqa: BLE001 - any read failure is an UNKNOWN observation
            return self._unknown(now_ns)
        if expiry is not None and (type(expiry) is not int or expiry < 0):
            return self._unknown(now_ns)
        self._unknown_since_ns = None
        self._unknown_paged = False
        if expiry is None:
            self._lapsed = False
            return PermitObservation("AGREE", "no_permit", None, None)
        if now_ns <= expiry:
            self._lapsed = False
            return PermitObservation("AGREE", "valid", None, None)
        page = _PAGE_LAPSED if not self._lapsed and _in_b1_window(now_ns) else None
        self._lapsed = True
        return PermitObservation("DISAGREE", "lapsed", VetoReason.PERMIT_LAPSED, page)

    def _unknown(self, now_ns: int) -> PermitObservation:
        if self._unknown_since_ns is None:
            self._unknown_since_ns = now_ns
        if now_ns - self._unknown_since_ns <= WATCH_TICK_STALE_S * _NS_PER_S:
            return PermitObservation("UNKNOWN", "read_error", None, None)
        page = None if self._unknown_paged else _PAGE_UNKNOWN
        self._unknown_paged = True
        return PermitObservation("UNKNOWN", "persistent", VetoReason.PERMIT_LAPSED, page)
