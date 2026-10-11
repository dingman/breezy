"""EXEC-PAR BG-5c WP-B (R7): durable gap spans and idempotent gappy-day marking (inert; unwired).

**Why a lapse record.** The breaker heartbeat is ONE overwritten row
(``write_breaker_heartbeat`` re-sets ``intent/breaker``), so the heartbeat series is not a durable
history: after the next beat the previous one is gone. This module therefore keeps an APPEND-ONLY
span series (``HeartbeatLapse`` rows, ``lapse/<start_ns>``) written by the watcher tick, and
:func:`mark_gaps` turns the unmarked spans into ``gappy/<day>`` marks.

**Two triggers, one marking path (R7.1).**

* In-run: the watcher calls :func:`record_lapse_if_any` BEFORE writing a heartbeat, passing its
  last written heartbeat (the epoch ``boot_ts`` until the first one).
* Boot: :func:`record_unclean_shutdowns` records, for every K>1 epoch without a ``stop_ts`` that a
  later boot superseded, the span from its last known heartbeat to that next boot.

Both then run :func:`mark_gaps` (boot: before the first counter ingest). Each span marks EVERY
governed open day it overlaps (``open_days_at``, instant-only, R7.2). A span is stamped
``marked_ts`` only once all its days are marked, so marking is idempotent: a later BG-1d rebuild
that deletes a day's mark is never undone by re-marking a span already handled.

**Failure semantics (R7.5), typed.** WP-E maps them: a :class:`GapMarkError` at BOOT refuses K>1
(force K=1 and raise a CRITICAL alert); IN-RUN it withholds the heartbeat, and the days named in
``pending_days`` stay non-PASS until the mark lands. Nothing here swallows a failure or turns it
into "no gaps".
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Final, Protocol

from breezy.runtime.exec_par_reconcile import HEARTBEAT_LAPSE_NS, GapKind, GapSpan, gappy_days
from breezy.runtime.exec_par_records import EpochRow, HeartbeatLapse

__all__ = [
    "GapLedgerPort",
    "GapMarkError",
    "GapMarkPort",
    "GapMarkResult",
    "GapMarkWriteError",
    "GapReadError",
    "LapseWriteError",
    "mark_gaps",
    "record_final_lapse_before_stop",
    "record_lapse_if_any",
    "record_unclean_shutdowns",
    "unclean_shutdown_lapses",
]

_HOUR_NS: Final[int] = 3_600 * 1_000_000_000
_KIND_BY_VALUE: Final[dict[str, GapKind]] = {kind.value: kind for kind in GapKind}


class GapMarkError(Exception):
    """Base of the typed gap-marking failures (messages never carry amounts)."""


class LapseWriteError(GapMarkError):
    """A lapse / unclean-shutdown span could not be recorded (``__cause__`` is the store error)."""


class GapReadError(GapMarkError):
    """The span ledger or the gappy marks could not be read: never read as "no gaps"."""


class GapMarkWriteError(GapMarkError):
    """A gappy mark (or a span's marked stamp) failed; ``pending_days`` stay unmarked."""

    def __init__(self, message: str, *, pending_days: frozenset[str]) -> None:
        super().__init__(message)
        self.pending_days = pending_days


class GapLedgerPort(Protocol):
    """The three latch methods that persist spans (``ExecParRecordsMixin``)."""

    def write_heartbeat_lapse(self, record: HeartbeatLapse) -> bool: ...
    def read_heartbeat_lapses(self) -> tuple[HeartbeatLapse, ...]: ...
    def set_lapse_marked(self, start_ns: int, end_ns: int, marked_ts: int) -> bool: ...


class GapMarkPort(Protocol):
    """The slice of ``CounterStorePort`` that marks days (first mark of a day wins)."""

    def read_gappy_days(self) -> frozenset[str]: ...
    def mark_gappy_day(self, day: str, kind: str) -> None: ...


@dataclass(frozen=True, slots=True)
class GapMarkResult:
    """Days newly marked by one call (ascending) and how many spans were stamped handled."""

    marked_days: tuple[str, ...]
    spans_stamped: int


# -- recording ---------------------------------------------------------------------


def record_lapse_if_any(
    ledger: GapLedgerPort,
    *,
    last_hb_ns: int | None,
    now_ns: int,
    bound_ns: int = HEARTBEAT_LAPSE_NS,
) -> HeartbeatLapse | None:
    """Append the span ``(last_hb_ns, now_ns)`` when it is strictly longer than ``bound_ns``.

    Call BEFORE the heartbeat write so a failure here withholds the heartbeat (R7.5). ``None``
    ``last_hb_ns`` means no baseline yet (the caller passes the epoch ``boot_ts`` for that);
    a clock that went backwards records nothing. Re-recording the same span is a no-op.
    """
    if last_hb_ns is None or now_ns - last_hb_ns <= bound_ns:
        return None
    row = HeartbeatLapse(start_ns=last_hb_ns, end_ns=now_ns, kind=GapKind.HEARTBEAT_LAPSE.value)
    _write(ledger, row)
    return row


def record_final_lapse_before_stop(
    ledger: GapLedgerPort, *, last_hb_ns: int | None, stop_ts_ns: int
) -> HeartbeatLapse | None:
    """Run the lapse check for the tail ``(last_hb_ns, stop_ts)`` BEFORE ``stop_ts`` is written.

    A clean stop closes the epoch, so a stall that ends in a clean stop would otherwise leave no
    span. WP-E calls this from ``_close_epoch`` ahead of ``record_clean_stop``; a
    :class:`LapseWriteError` must not block the stop itself (log it; the unclean path is the
    fallback).
    """
    return record_lapse_if_any(ledger, last_hb_ns=last_hb_ns, now_ns=stop_ts_ns)


def unclean_shutdown_lapses(
    epochs: Iterable[EpochRow], *, last_heartbeat_ns: int | None
) -> tuple[HeartbeatLapse, ...]:
    """Spans for K>1 epochs that never got a ``stop_ts`` and were followed by a later boot.

    The span runs from the last known heartbeat to the next boot. Only the epoch immediately
    before the latest boot can use ``last_heartbeat_ns`` (the surviving breaker row), and only if
    it lies inside that epoch; any other unclean epoch spans from its own ``boot_ts`` (a
    conservative superset, never a miss). K=1 epochs cannot hold K>1 counters and are skipped; the
    LAST epoch is the running one and is never unclean.
    """
    ordered = sorted(epochs, key=lambda e: e.boot_ts)
    rows: list[HeartbeatLapse] = []
    for index, epoch in enumerate(ordered[:-1]):
        if epoch.stop_ts is not None or epoch.effective_k <= 1:
            continue
        next_boot = ordered[index + 1].boot_ts
        is_latest_prior = index == len(ordered) - 2
        start = epoch.boot_ts
        if (
            is_latest_prior
            and last_heartbeat_ns is not None
            and epoch.boot_ts <= last_heartbeat_ns < next_boot
        ):
            start = last_heartbeat_ns
        if next_boot > start:
            rows.append(HeartbeatLapse(start, next_boot, GapKind.UNCLEAN_SHUTDOWN.value))
    return tuple(rows)


def record_unclean_shutdowns(
    ledger: GapLedgerPort, epochs: Sequence[EpochRow], last_heartbeat_ns: int | None
) -> tuple[HeartbeatLapse, ...]:
    """Record every unclean-shutdown span (idempotent). A write failure raises, partial or not."""
    rows = unclean_shutdown_lapses(epochs, last_heartbeat_ns=last_heartbeat_ns)
    for row in rows:
        _write(ledger, row)
    return rows


def _write(ledger: GapLedgerPort, row: HeartbeatLapse) -> None:
    try:
        ledger.write_heartbeat_lapse(row)
    except Exception as exc:
        raise LapseWriteError("lapse span write failed") from exc


# -- marking -----------------------------------------------------------------------


def mark_gaps(
    *,
    ledger: GapLedgerPort,
    counters: GapMarkPort,
    open_days_at: Callable[[int], frozenset[str]],
    wall_ns: Callable[[], int],
) -> GapMarkResult:
    """Gappy-mark every governed open day of every not-yet-handled span; idempotent.

    Safe to call on every reconcile pass and at boot. Raises :class:`GapReadError` when the ledger
    or the marks cannot be read, :class:`GapMarkWriteError` (naming ``pending_days``) when any
    mark or stamp fails; a failed span is left unstamped so the next call retries it, and the other
    spans and days are still attempted first.
    """
    try:
        pending = [row for row in ledger.read_heartbeat_lapses() if row.marked_ts is None]
        existing = counters.read_gappy_days()
    except Exception as exc:
        raise GapReadError("gap ledger or gappy marks unreadable") from exc
    marked: set[str] = set()
    failed: set[str] = set()
    unstamped_days: set[str] = set()
    stamped = 0
    first_error: Exception | None = None
    for row in sorted(pending, key=lambda r: (r.start_ns, r.end_ns)):
        span_failed = False
        try:
            days = gappy_days(
                [GapSpan(_kind_of(row), row.start_ns, row.end_ns)], open_days_at=open_days_at
            )
        except Exception as exc:  # noqa: BLE001 - typed GapMarkError below
            first_error = first_error or exc
            span_failed = True
            days = _resolvable_days(row, open_days_at)
            unstamped_days |= days  # the span is incomplete, so its resolvable days stay pending
        for day in sorted(days - existing - marked):
            try:
                counters.mark_gappy_day(day, row.kind)
            except Exception as exc:  # noqa: BLE001 - typed GapMarkError below
                first_error = first_error or exc
                failed.add(day)
                span_failed = True
            else:
                marked.add(day)
        if span_failed:
            continue
        try:
            ledger.set_lapse_marked(row.start_ns, row.end_ns, wall_ns())
            stamped += 1
        except Exception as exc:  # noqa: BLE001 - typed GapMarkError below
            first_error = first_error or exc
            unstamped_days |= days
    if first_error is not None:
        raise GapMarkWriteError(
            "gappy mark write failed",
            pending_days=frozenset((failed - marked - existing) | unstamped_days),
        ) from first_error
    return GapMarkResult(marked_days=tuple(sorted(marked)), spans_stamped=stamped)


def _resolvable_days(
    row: HeartbeatLapse, open_days_at: Callable[[int], frozenset[str]]
) -> frozenset[str]:
    """Best effort when ``gappy_days`` itself failed: every instant that still resolves."""
    found: set[str] = set()
    cursor = row.start_ns
    instants = [row.start_ns, row.end_ns]
    while cursor < row.end_ns:
        instants.append(cursor)
        cursor += _HOUR_NS
    for instant in instants:
        try:
            found |= open_days_at(instant)
        except Exception:  # noqa: BLE001, S112 - an unresolvable instant stays pending via the span
            continue
    return frozenset(found)


def _kind_of(row: HeartbeatLapse) -> GapKind:
    kind = _KIND_BY_VALUE.get(row.kind)
    if kind is None:
        raise ValueError("unknown gap kind")
    return kind
