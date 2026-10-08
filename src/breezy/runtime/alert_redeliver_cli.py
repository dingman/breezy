"""``breezy-autonomy-alert-redeliver``: drain the alert outbox under an inherited flock.

The coordinator creates ``evidence/alerts/.redeliver.lock`` at activation. This process opens
that file ``O_RDONLY|O_CLOEXEC`` and takes ``LOCK_EX|LOCK_NB``. It does not create the lock and
it does not put ``flock`` in ``ExecStart``. A missing lock is an integrity failure: one CRITICAL
attempt through the delivery proof, then exit 3, and no drain loop.
"""

from __future__ import annotations

import fcntl
import os
import sys
from collections.abc import Sequence

from breezy.registry.health_model import AlertPayload
from breezy.runtime.alert_delivery import (
    COUNTERS,
    REDELIVER_MIN_AGE_S,
    AlertOutbox,
    DeliveryRecordWriter,
    default_alerts_root,
    deliver_with_proof,
    drain_outbox,
)
from breezy.runtime.health import resolve_alert_sink

_LOCK_NAME = ".redeliver.lock"
_BUDGET_S = 40


def _close(sink: object) -> None:
    closer = getattr(sink, "close", None)
    if callable(closer):
        closer()


def _integrity_attempt() -> None:
    """One CRITICAL through §3.6. Delivery does not change the exit code."""
    root = default_alerts_root()
    sink = resolve_alert_sink()
    try:
        deliver_with_proof(
            sink,
            AlertPayload(
                severity="CRITICAL",
                event="REDELIVER_LOCK_MISSING",
                site="redeliver",
                detail="lock_file_missing",
            ),
            writer="redeliver",
            records=DeliveryRecordWriter(root),
            attempt_kind="alert",
            outbox=AlertOutbox(root),
        )
    finally:
        _close(sink)


def main(argv: Sequence[str] | None = None) -> int:
    """Drain once. Exit 0 if the lock is held elsewhere or the drain ends; 3 if it is missing."""
    del argv
    root = default_alerts_root()
    lock_path = root / _LOCK_NAME
    try:
        fd = os.open(lock_path, os.O_RDONLY | os.O_CLOEXEC)
    except FileNotFoundError:
        print("BREEZY_AUTONOMY_ALERT_REDELIVER INTEGRITY lock_file_missing")
        try:
            _integrity_attempt()
        except Exception as exc:  # noqa: BLE001 - integrity exit is 3 either way
            print(
                f"BREEZY_AUTONOMY_ALERT_REDELIVER INTEGRITY attempt_failed={type(exc).__name__}",
                file=sys.stderr,
            )
        return 3
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        print("BREEZY_AUTONOMY_ALERT_REDELIVER SKIPPED lock_held")
        return 0
    sink = resolve_alert_sink()
    try:
        summary = drain_outbox(
            drainer="redeliver",
            outbox=AlertOutbox(root),
            sink=sink,
            records=DeliveryRecordWriter(root),
            min_age_s=REDELIVER_MIN_AGE_S,
            budget_s=_BUDGET_S,
        )
    finally:
        _close(sink)
        os.close(fd)
    print(
        f"AUTONOMY_REDELIVER delivered={summary.delivered} attempted={summary.attempted} "
        f"reclaims={summary.reclaims} failures={summary.failures} "
        f"abandoned={len(summary.abandoned)} "
        f"journal_write_failures={COUNTERS.journal_write_failures} "
        f"outbox_write_failures={COUNTERS.outbox_write_failures}"
    )
    for name in summary.abandoned:
        print(f"AUTONOMY_REDELIVER abandoned_entry={name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
