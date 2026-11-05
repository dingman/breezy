"""Shared point-in-time guard for backtest, replay, and study feeds.

Nautilus ``Data.ts_init`` is the UNIX nanosecond instant the instance was
created. Breezy weather records stamp that with ``retrieved_at_ns`` (when the
product was received). A record whose ``ts_init`` is strictly after the
decision instant was not available for that decision. Equal ``ts_init`` is the
decision instant itself and is available, not look-ahead.

One call scans every record and raises once. ``offending_records`` keeps input
order so the caller derives the count from the exception and does not re-filter.
A record with no integer ``ts_init`` fails closed and is an offender.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeGuard


class LookAheadRecordError(ValueError):
    """One or more records are not available at the decision instant.

    ``offending_records`` is every violator, in input order. The message names
    each offending ``ts_init`` and the decision boundary.
    """

    def __init__(
        self,
        *,
        offending_records: tuple[object, ...],
        decision_ts_init_ns: int,
        context: str,
    ) -> None:
        self.offending_records = offending_records
        self.decision_ts_init_ns = decision_ts_init_ns
        self.context = context
        rendered = ", ".join(_format_ts(record) for record in offending_records)
        super().__init__(
            f"{context}: {len(offending_records)} record(s) look ahead of "
            f"decision_ts_init_ns={decision_ts_init_ns} "
            f"(offending ts_init: {rendered})"
        )


def assert_available_before_decision(
    records: Sequence[object],
    *,
    decision_ts_init_ns: int,
    context: str,
) -> None:
    """Refuse records that were not available at ``decision_ts_init_ns``.

    Strict: ``ts_init > decision_ts_init_ns`` is look-ahead. Equal is available.
    A missing or non-integer ``ts_init`` is look-ahead too (fail closed).
    """
    if not _is_int_timestamp(decision_ts_init_ns):
        raise LookAheadRecordError(
            offending_records=tuple(records),
            decision_ts_init_ns=0,
            context=f"{context}: decision boundary is not an integer timestamp",
        )
    offending: list[object] = []
    for record in records:
        ts_init = getattr(record, "ts_init", None)
        if not _is_int_timestamp(ts_init) or ts_init > decision_ts_init_ns:
            offending.append(record)
    if offending:
        raise LookAheadRecordError(
            offending_records=tuple(offending),
            decision_ts_init_ns=decision_ts_init_ns,
            context=context,
        )


def _is_int_timestamp(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _format_ts(record: object) -> str:
    return str(getattr(record, "ts_init", None))
