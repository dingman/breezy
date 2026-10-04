"""AUT-1 ``CapturePublisher`` (plan r12 section 3.4.3).

The publisher is the one writer-facing seam of the capture path. ``write`` calls the stream
wrapper DIRECTLY (R-A: custom records never cross the message bus) and never raises (L-16). A
failed write sets ``health.ok=False``, logs ``CAPTURE_PUBLISH_FAILED``, and offers a CRITICAL of the
same name through the node outbox, deduplicated per cause per ``FAILURE_DEDUPE_S`` with the
suppressed counts logged (r8 H8). ``flush_for_submit`` is the guard's synchronous flush before
``super().submit_order`` (EM4) and is False after any dropped write since the previous call.

The stream, the alert offer, the log sink and the clock are all injected, so this module imports no
runtime, strategy or adapter code. It imports ``capture_records`` (for the heartbeat), so it reaches
Nautilus and is a contract-(b) permitted module.
"""

import logging
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final, Protocol

from breezy.persistence.autonomy.capture_alerts import CAPTURE_ALERT_SEVERITIES
from breezy.persistence.autonomy.capture_records import (
    HEARTBEAT_SCHEMA,
    CaptureHeartbeat,
    make_record,
)

__all__ = [
    "FAILURE_DEDUPE_S",
    "PUBLISH_FAILED_EVENT",
    "AlertOffer",
    "CaptureHealth",
    "CapturePublisher",
    "StreamCounters",
    "StreamLike",
]

FAILURE_DEDUPE_S: Final[int] = 300
PUBLISH_FAILED_EVENT: Final[str] = "CAPTURE_PUBLISH_FAILED"
_NS: Final[int] = 10**9
_FAMILY_RE: Final[re.Pattern[str]] = re.compile(r"\A[A-Za-z0-9_.-]{1,96}\Z")
_FALLBACK_CAUSE: Final[str] = "write_failed"

#: ``(event, severity, detail) -> accepted``: the node outbox's ``offer``, duck-typed.
AlertOffer = Callable[[str, str, str], bool]
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


@dataclass
class CaptureHealth:
    """The shared veto flag. ``capture_gap`` refuses BUYs while ``ok`` is False; it is cleared only
    by the publisher's positive control. ``cause`` is the latest failure's cause."""

    ok: bool = True
    cause: str = ""

    def mark_failed(self, cause: str) -> None:
        self.ok = False
        self.cause = cause

    def clear(self) -> None:
        self.ok = True
        self.cause = ""


@dataclass(frozen=True)
class StreamCounters:
    """Cumulative per-boot counters. ``written_by_type`` is keyed by table name."""

    written_by_type: Mapping[str, int]
    write_failures: int
    write_drops: int


class StreamLike(Protocol):
    health: CaptureHealth

    def write(self, obj: object) -> bool: ...

    def flush(self) -> bool: ...

    def consume_drops_since_submit_flush(self) -> int: ...

    def counters(self) -> StreamCounters: ...


@dataclass
class _Window:
    start_ns: int
    suppressed: int = 0


class CapturePublisher:
    def __init__(
        self,
        stream: StreamLike,
        *,
        family_id: str,
        alert_offer: AlertOffer | None = None,
        log_error: Callable[[str], None] | None = None,
        now_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        if _FAMILY_RE.match(family_id) is None:
            raise ValueError("family_id must be a non-empty token")
        self._stream = stream
        self._family_id = family_id
        self._alert_offer = alert_offer
        self._log_error = log_error if log_error is not None else _LOGGER.error
        self._now_ns = now_ns
        self._windows: dict[str, _Window] = {}
        self._heartbeat_seq = 0
        self.alert_drops = 0

    @property
    def health(self) -> CaptureHealth:
        return self._stream.health

    def write(self, record: object) -> bool:
        """Write one record through the stream wrapper. False on any failure; never raises."""
        try:
            written = self._stream.write(record)
            cause = "" if written else (self._stream.health.cause or _FALLBACK_CAUSE)
        except Exception as exc:  # noqa: BLE001 - L-16: nothing escapes into a handler
            written = False
            cause = type(exc).__name__
            self._stream.health.mark_failed(cause)
        if not written:
            self._on_failure(type(record).__name__, cause)
        return written

    def flush_for_submit(self) -> bool:
        """The guard's synchronous flush (EM4). False on a flush failure, and False once after any
        judged write dropped since the previous call (r11 GM2); the drop counter is then reset."""
        try:
            flushed = self._stream.flush()
            cause = self._stream.health.cause or "flush_failed"
        except Exception as exc:  # noqa: BLE001 - L-16
            flushed = False
            cause = type(exc).__name__
            self._stream.health.mark_failed(cause)
        drops = self._stream.consume_drops_since_submit_flush()
        if not flushed:
            self._on_failure("flush", cause)
        return flushed and drops == 0

    def positive_control(
        self, *, heartbeat_written: bool, flush_ok: bool, per_type_passed: bool
    ) -> bool:
        """Clear the veto only on a tick where the heartbeat was written, the flush returned True
        and the per-type landing check passed. Returns ``health.ok`` afterwards."""
        if heartbeat_written and flush_ok and per_type_passed:
            self._stream.health.clear()
        return self._stream.health.ok

    def write_heartbeat(self, *, node_boot_id: str, final: bool, now_ns: int) -> bool:
        """Write one ``CaptureHeartbeat``. Its ``written_by_type`` is a snapshot taken immediately
        BEFORE its own write (r11 GL1), so it excludes itself."""
        counters = self._stream.counters()
        self._heartbeat_seq += 1
        record = make_record(
            CaptureHeartbeat,
            ts_event=now_ns,
            ts_init=now_ns,
            schema=HEARTBEAT_SCHEMA,
            node_boot_id=node_boot_id,
            seq=self._heartbeat_seq,
            final=final,
            records_written=sum(counters.written_by_type.values()),
            written_by_type=dict(counters.written_by_type),
            write_failures=counters.write_failures,
            write_drops=counters.write_drops,
            health_ok=self._stream.health.ok,
            health_cause=self._stream.health.cause,
        )
        return self.write(record)

    def on_tick(self) -> None:
        """Log the suppressed counts of every window that has ended (the 60 s tick)."""
        now = self._now_ns()
        for cause in [c for c, w in self._windows.items() if self._expired(w, now)]:
            self._close_window(cause)

    @staticmethod
    def _expired(window: _Window, now_ns: int) -> bool:
        return now_ns - window.start_ns >= FAILURE_DEDUPE_S * _NS

    def _close_window(self, cause: str) -> None:
        window = self._windows.pop(cause)
        if window.suppressed:
            self._log_error(
                f"CAPTURE_PUBLISH_FAILED_SUPPRESSED family={self._family_id} cause={cause} "
                f"count={window.suppressed} window_s={FAILURE_DEDUPE_S}"
            )

    def _on_failure(self, record_type: str, cause: str) -> None:
        self._log_error(
            f"CAPTURE_PUBLISH_FAILED family={self._family_id} type={record_type} cause={cause}"
        )
        now = self._now_ns()
        window = self._windows.get(cause)
        if window is not None and not self._expired(window, now):
            window.suppressed += 1
            return
        if window is not None:
            self._close_window(cause)
        self._windows[cause] = _Window(start_ns=now)
        self._offer(record_type, cause)

    def _offer(self, record_type: str, cause: str) -> None:
        if self._alert_offer is None:
            self.alert_drops += 1
            return
        try:
            accepted = self._alert_offer(
                PUBLISH_FAILED_EVENT,
                CAPTURE_ALERT_SEVERITIES[PUBLISH_FAILED_EVENT],
                f"family={self._family_id} type={record_type} cause={cause}",
            )
        except Exception:  # noqa: BLE001 - an outbox failure is counted, never raised
            accepted = False
        if not accepted:
            self.alert_drops += 1
