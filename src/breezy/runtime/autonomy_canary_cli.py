"""``breezy-autonomy-canary``: prove the alert path end to end (plan r15 sections 3.7, 3.7.1).

The canary delivers one INFO alert through the delivery proof (``deliver_with_proof``), writing
its normal ``attempt_kind=canary`` record. Scheduled slots (15:45Z, 16:30Z, 16:45Z) always send.
Every other firing (the remaining ``:45`` ones and 17:10Z) goes through the retry gate: it sends
only after a failed canary, or when the record directories cannot be read. No retry runs inside
the launch window ``[16:30Z, 17:10Z)``; a failed 16:30Z or 16:45Z canary is retried at 17:10Z.

A failed canary queues one CRITICAL ``autonomy_canary_undelivered`` through the outbox and the
process still exits 0. The first delivered canary writes the write-once ``armed.json`` marker.

``--suppress-drill`` is honoured only on a date in ``CANARY_SUPPRESSION_DRILL_DATES`` (empty:
ruling r3 withdrew the sender-armed dead-man, so no date is registered), only at the 15:45Z slot,
and only when the previous day's 16:45Z canary was delivered.

The URL arrives only through the environment and is read by the sink; this module never names it.
The ``httpx`` and ``httpcore`` loggers are pinned to WARNING so no request line is ever logged.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import logging
import os
import re
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final

from breezy.persistence.autonomy.pins import CANARY_SUPPRESSION_DRILL_DATES
from breezy.registry.health_model import AlertPayload
from breezy.runtime.alert_delivery import (
    COUNTERS,
    AlertOutbox,
    DeliveryRecordWriter,
    default_alerts_root,
    deliver_with_proof,
)
from breezy.runtime.alert_outbox import write_armed_marker
from breezy.runtime.health import resolve_alert_sink

_LOG = logging.getLogger(__name__)

_LOCK_NAME: Final = ".canary.lock"
_NS: Final = 1_000_000_000
_DAY_S: Final = 86_400
_SLOT_TOLERANCE_S: Final = 120  # systemd start latency; the timer itself is accurate to 1 s
_WINDOW_START_S: Final = 16 * 3600 + 30 * 60
_WINDOW_END_S: Final = 17 * 3600 + 10 * 60
_SCHEDULED: Final[dict[str, int]] = {
    "1545": 15 * 3600 + 45 * 60,
    "1630": 16 * 3600 + 30 * 60,
    "1645": 16 * 3600 + 45 * 60,
}
_DEFER_SLOTS: Final = frozenset({"1630", "1645"})
_DRILL_SLOT: Final = "1545"
_PRIOR_SLOT_START_S: Final = 16 * 3600 + 45 * 60
_PRIOR_SLOT_END_S: Final = 16 * 3600 + 50 * 60
_EVENT: Final = "autonomy_canary"
_CRITICAL_EVENT: Final = "autonomy_canary_undelivered"
_WRITER: Final = "canary"
_RECORD_RE: Final = re.compile(r"(\d+)_canary_([df])\.json\Z")
_RECORD_MAX_BYTES: Final = 4096
_PAYLOAD: Final = AlertPayload(severity="INFO", event=_EVENT, site="global", detail="canary_ok")
_PREFIX: Final = "AUTONOMY_CANARY"


def _second_of_day(now_ns: int) -> int:
    return (now_ns // _NS) % _DAY_S


def _slot_of(now_ns: int) -> str:
    """``1545|1630|1645`` (scheduled), ``1710`` or ``retry`` (gated), ``deferred`` (in window)."""
    second = _second_of_day(now_ns)
    for name, start in _SCHEDULED.items():
        if start <= second < start + _SLOT_TOLERANCE_S:
            return name
    if _WINDOW_END_S <= second < _WINDOW_END_S + _SLOT_TOLERANCE_S:
        return "1710"
    if _WINDOW_START_S <= second < _WINDOW_END_S:
        return "deferred"
    return "retry"


def _day_dir(root: Path, instant_ns: int) -> Path:
    return root / dt.datetime.fromtimestamp(instant_ns / _NS, tz=dt.UTC).date().isoformat()


def _canary_names(directory: Path) -> list[tuple[int, bool, Path]]:
    """``(ts_ns, delivered, path)`` of the canary writer's records, newest first.

    Raises ``OSError`` when the directory is absent or unreadable.
    """
    found = []
    for entry in directory.iterdir():
        match = _RECORD_RE.match(entry.name)
        if match is not None:
            found.append((int(match.group(1)), match.group(2) == "d", entry))
    return sorted(found, key=lambda item: item[0], reverse=True)


def _body(path: Path) -> dict[str, object] | None:
    try:
        if path.stat().st_size > _RECORD_MAX_BYTES:
            return None
        body = json.loads(path.read_bytes())
    except (OSError, ValueError):
        return None
    return body if isinstance(body, dict) else None


def _read_canary_records(
    directories: Sequence[Path], *, drills: bool
) -> list[tuple[int, bool, dict[str, object]]]:
    """Canary-kind records of ``directories``, newest first (``OSError`` if a directory is bad)."""
    names = []
    for directory in directories:
        names += _canary_names(directory)
    found = []
    for ts_ns, delivered, path in sorted(names, key=lambda item: item[0], reverse=True):
        body = _body(path)
        if body is None or body.get("attempt_kind") != "canary":
            continue
        if bool(body.get("drill")) and not drills:
            continue
        found.append((ts_ns, delivered, body))
    return found


def _retry_due(root: Path, now_ns: int) -> bool:
    """Send iff the newest canary attempt failed or the records cannot be read (fail to send)."""
    try:
        records = _read_canary_records(
            [_day_dir(root, now_ns), _day_dir(root, now_ns - _DAY_S * _NS)], drills=False
        )
    except OSError:
        return True
    return not records or not records[0][1]


def _previous_1645_delivered(root: Path, now_ns: int) -> bool:
    yesterday = now_ns - _DAY_S * _NS
    try:
        records = _read_canary_records([_day_dir(root, yesterday)], drills=False)
    except OSError:
        return False
    day = dt.datetime.fromtimestamp(yesterday / _NS, tz=dt.UTC).date()
    for ts_ns, delivered, _body_ in records:
        stamp = dt.datetime.fromtimestamp(ts_ns / _NS, tz=dt.UTC)
        second = stamp.hour * 3600 + stamp.minute * 60 + stamp.second
        if delivered and stamp.date() == day and _PRIOR_SLOT_START_S <= second < _PRIOR_SLOT_END_S:
            return True
    return False


def _drill_wanted(requested: bool, slot: str, now_ns: int, root: Path) -> bool:
    """Whether this run is the suppression drill. Journals why a requested drill did not run."""
    if not requested:
        return False
    today = dt.datetime.fromtimestamp(now_ns / _NS, tz=dt.UTC).date().isoformat()
    if slot != _DRILL_SLOT or today not in CANARY_SUPPRESSION_DRILL_DATES:
        print(f"{_PREFIX} drill_ignored")
        return False
    if not _previous_1645_delivered(root, now_ns):
        print(f"{_PREFIX} drill_skipped precondition")
        return False
    return True


def _record_drill(root: Path, now_ns: int) -> None:
    try:
        DeliveryRecordWriter(root).write(
            event=_EVENT,
            ts_ns=now_ns,
            writer=_WRITER,
            delivered=False,
            status_class="not_configured",
            severity=_PAYLOAD.severity,
            attempt_kind="canary",
            drill=True,
            site=_PAYLOAD.site,
            outbox_entry="",
        )
    except OSError:
        COUNTERS.journal_write_failures += 1
        _LOG.error("canary_drill_record_unwritable exception_type=OSError")


def _arm(root: Path, record_ts_ns: int, now_ns: int) -> None:
    """Write the marker after a delivered, recorded canary while it is absent. Never raises."""
    if os.path.lexists(root / "armed.json"):
        return
    try:
        write_armed_marker(root, record=f"{record_ts_ns}_canary_d.json", ts_ns=now_ns)
    except OSError:
        COUNTERS.journal_write_failures += 1
        _LOG.error("armed_marker_unwritable exception_type=OSError")


def _queue_critical(sink: object, root: Path, now_ns: int, status_class: str) -> None:
    deliver_with_proof(
        sink,
        AlertPayload(
            severity="CRITICAL",
            event=_CRITICAL_EVENT,
            site="global",
            detail=f"status_class={status_class}",
        ),
        writer=_WRITER,
        records=DeliveryRecordWriter(root),
        attempt_kind="alert",
        outbox=AlertOutbox(root),
        now_ns=lambda: now_ns,
    )


def _close(sink: object) -> None:
    closer = getattr(sink, "close", None)
    if callable(closer):
        closer()


def _lock_missing(root: Path, now_ns: int) -> int:
    """One CRITICAL attempt through the delivery proof; the exit code is 3 either way."""
    print(f"{_PREFIX} INTEGRITY lock_file_missing")
    sink = resolve_alert_sink()
    try:
        deliver_with_proof(
            sink,
            AlertPayload(
                severity="CRITICAL",
                event="CANARY_LOCK_MISSING",
                site="canary",
                detail="lock_file_missing",
            ),
            writer=_WRITER,
            records=DeliveryRecordWriter(root),
            attempt_kind="alert",
            outbox=AlertOutbox(root),
            now_ns=lambda: now_ns,
        )
    except Exception as exc:  # noqa: BLE001 - the integrity exit is 3 either way
        print(f"{_PREFIX} INTEGRITY attempt_failed={type(exc).__name__}", file=sys.stderr)
    finally:
        _close(sink)
    return 3


def _run_locked(root: Path, now_ns: int, requested_drill: bool) -> None:
    slot = _slot_of(now_ns)
    if slot == "deferred":
        print(f"{_PREFIX} retry_deferred until=17:10Z")
        return
    if slot in {"retry", "1710"} and not _retry_due(root, now_ns):
        print(f"{_PREFIX} skipped=not_due")
        return
    if _drill_wanted(requested_drill, slot, now_ns, root):
        _record_drill(root, now_ns)
        print(f"{_PREFIX} delivered=0 status_class=not_configured slot={slot}")
        return
    failures_before = COUNTERS.journal_write_failures
    sink = resolve_alert_sink()
    try:
        proof = deliver_with_proof(
            sink,
            _PAYLOAD,
            writer=_WRITER,
            records=DeliveryRecordWriter(root),
            attempt_kind="canary",
            outbox=AlertOutbox(root),
            now_ns=lambda: now_ns,
        )
        if proof.delivered and proof.recorded:
            _arm(root, proof.ts_ns, now_ns)
        elif not proof.delivered:
            _queue_critical(sink, root, now_ns, proof.status_class)
    finally:
        _close(sink)
    if COUNTERS.journal_write_failures != failures_before:
        print(
            f"{_PREFIX} journal_write_failures={COUNTERS.journal_write_failures - failures_before}"
        )
    print(
        f"{_PREFIX} delivered={int(proof.delivered)} status_class={proof.status_class} slot={slot}"
    )
    if not proof.delivered and slot in _DEFER_SLOTS:
        print(f"{_PREFIX} retry_deferred until=17:10Z")


def main(argv: Sequence[str] | None = None, *, now_ns: Callable[[], int] = time.time_ns) -> int:
    """Run one canary firing. Exit 0 either way; 3 only when the pre-created lock is missing."""
    parser = argparse.ArgumentParser(prog="breezy-autonomy-canary")
    parser.add_argument("--suppress-drill", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    now = now_ns()
    root = default_alerts_root()
    lock_path = root / _LOCK_NAME
    try:
        fd = os.open(lock_path, os.O_RDONLY | os.O_CLOEXEC)
    except FileNotFoundError:
        return _lock_missing(root, now)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        print(f"{_PREFIX} SKIPPED lock_held")
        return 0
    try:
        _run_locked(root, now, args.suppress_drill)
    finally:
        os.close(fd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
