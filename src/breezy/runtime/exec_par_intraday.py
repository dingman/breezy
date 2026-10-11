"""EXEC-PAR BG-6: the in-node intraday monitor (D-PREREG r4 1a, s5, s9; r4.1 K4, L1; r4.3 M3).

Run from the K>1 watcher's tick, on the loop thread, right after the BG-5b evaluator service. It
gathers the stage-window inputs from the BG-1 rows, applies the PURE predicates of
:mod:`breezy.runtime.exec_par_intraday_rules` and acts through the BG-5b evaluator's own writers,
never its own copies of them:

* a stop-class rule (s5 Clopper-Pearson, s5 burst, s9 station-day 0.25) goes through
  ``StageEvaluator.stop_class``: the ``stop_verdict`` marker FIRST, then the entries-only halt in
  ``BREAKER_KEY``, then the force-K1 flag (M3, r4 1a "Write order");
* an integrity condition (stale or never-written stamp, an unreadable stamp, a failed read, an
  unbound port, a predicate raise or non-bool) goes through ``StageEvaluator.integrity_halt``:
  a halt, no flag, no marker.

Window (D-PREREG s5): entries with ARM time at or after the latest ``stage_reset`` instant, with
excluded days skipped, over every label from the stage start through the latest OPEN label (BG-5c
N-C: open days are evaluated immediately). Labels come from the one day convention
(``entry_day``); the floor labels (``open_days_at(floor.ts)``) are read from the per-entry rows and
filtered by arm time, every later label from the BG-1 day counts. s9 counts ALL open positions of
each station-day, regardless of arm time or floor. AMBIGUOUS entries without a station-day
(``unattributed``) are not part of any window here; the daily evaluator reports them.

A condition is acted on when it STARTS (edge-triggered): the halt is sticky and the marker is
durable, so repeating them every 5 s tick would only flood the store. A pending halt write, a flag
write failure and a marker failure are carried by the evaluator (D3, M3). ``check`` never raises.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Protocol

from breezy.runtime.exec_par_counter_ingest import UNATTRIBUTED
from breezy.runtime.exec_par_days_port import DayConvention
from breezy.runtime.exec_par_intraday_rules import (
    BURST_MIN_AMBIGUOUS,
    IntradayInputError,
    IntradayInputs,
    IntradayPredicateError,
    OpenCostPort,
    burst_trips,
    intraday_stop_reasons,
    max_in_window,
)
from breezy.runtime.exec_par_reconcile import DayCounts
from breezy.runtime.exec_par_records import (
    AmbiguousRow,
    DayCountsDelta,
    EpochRow,
    ExcludedDay,
    OrderAnchor,
    StageEvalStamp,
    StageReset,
)
from breezy.runtime.exec_par_stage_snapshot import stage_day_labels
from breezy.runtime.exec_par_stamp_gate import (
    REASON_STAMP_STALE,
    REASON_STAMP_UNREADABLE,
    stamp_denial,
)

__all__ = [
    "REASON_INTRADAY_UNBOUND",
    "DayScanCache",
    "IntradayCounts",
    "IntradayMonitor",
    "IntradayPorts",
    "IntradayReads",
    "gather_intraday_inputs",
]

logger = logging.getLogger(__name__)

_FAIL_PREFIX: Final[str] = "stage_eval_fail:"
REASON_INTRADAY_UNBOUND: Final[str] = f"{_FAIL_PREFIX}intraday_unbound"
_REASON_INPUTS: Final[str] = f"{_FAIL_PREFIX}intraday_inputs"
_REASON_READ_PREFIX: Final[str] = f"{_FAIL_PREFIX}intraday_read:"


class IntradayReads(Protocol):
    """The latch reads the monitor uses (a subset of ``SubmitIntentLatch``; loop thread)."""

    def read_stage_reset(self) -> StageReset | None: ...
    def read_epoch_rows(self) -> tuple[EpochRow, ...]: ...
    def read_excluded_days(self) -> tuple[ExcludedDay, ...]: ...
    def read_order_anchors(self, day: str) -> tuple[OrderAnchor, ...]: ...
    def read_ambiguous(self, day: str) -> tuple[object, ...]: ...
    def read_counts_delta(self, day: str) -> DayCountsDelta | None: ...
    def read_stage_eval_stamp(self) -> StageEvalStamp | None: ...


class IntradayCounts(Protocol):
    """The slice of ``CounterStorePort`` the monitor reads."""

    def read_day_counts(self, day: str) -> DayCounts | None: ...
    def read_gappy_days(self) -> frozenset[str]: ...


@dataclass(frozen=True, slots=True)
class IntradayPorts:
    """The s9 inputs the node's wiring supplies (K6: aggregates in, a bool out).

    ``open_cost_by_station_day()`` returns the open cost of ALL open positions per
    ``<station>@<day>`` (summed Decimals; they never leave the port's caller and are never
    logged). ``open_cost_port`` is the ledger's ``open_cost_exceeds_budget_fraction``.
    """

    open_cost_port: OpenCostPort
    open_cost_by_station_day: Callable[[], Mapping[str, Decimal]]


def _ambiguous_rows(rows: tuple[object, ...]) -> tuple[AmbiguousRow, ...]:
    picked = tuple(row for row in rows if isinstance(row, AmbiguousRow))
    if len(picked) != len(rows):
        raise IntradayInputError("ambiguous rows are not AmbiguousRow")
    return picked


@dataclass(frozen=True, slots=True)
class _DayScan:
    """One label's contribution to the window (what a closed day caches)."""

    posted: int
    ambiguous: int
    arm_ns: tuple[int, ...]
    findings: tuple[str, ...]
    #: A rebuilt day whose AMBIGUOUS rows are fewer than its effective count: this many arm times
    #: are missing (the positive BG-1d delta). The burst is judged over the whole window.
    missing: int = 0


class DayScanCache:
    """Closed-day scans, keyed by ``(label, floor_ts)``.

    A closed day only changes through a rebuild, a late ingest or a gappy event, each of which
    calls :meth:`invalidate` (the evaluator after its reconcile, the watcher after a late ingest);
    a day carrying a gappy mark is never cached. Open days are rescanned on every tick, so the
    per-tick work stays constant as the stage grows.
    """

    def __init__(self) -> None:
        self._scans: dict[tuple[str, int | None], _DayScan] = {}

    def get(self, day: str, floor_ts: int | None) -> _DayScan | None:
        return self._scans.get((day, floor_ts))

    def put(self, day: str, floor_ts: int | None, scan: _DayScan) -> None:
        self._scans[(day, floor_ts)] = scan

    def invalidate(self, days: Iterable[str] | None = None) -> None:
        if days is None:
            self._scans.clear()
            return
        gone = frozenset(days)
        for key in [k for k in self._scans if k[0] in gone]:
            del self._scans[key]


def _scan_floor_day(reads: IntradayReads, day: str, cutoff: int) -> _DayScan:
    """A floor label: post-floor rows only, plus the day's positive rebuild delta. A rebuild
    restores whole-day counts, not rows, so the delta cannot be split at the floor; it is added in
    full to the numerator (conservative) and counted as missing arm times."""
    anchors = reads.read_order_anchors(day)
    marks = tuple(r for r in _ambiguous_rows(reads.read_ambiguous(day)) if r.arm_ns >= cutoff)
    delta = reads.read_counts_delta(day)
    missing = 0 if delta is None else max(delta.ambiguous, 0)
    posted_allowance = 0 if delta is None else max(delta.posted_entries, 0)
    posted = sum(1 for a in anchors if a.arm_ns >= cutoff)
    ambiguous = len(marks) + missing
    findings = (f"ambiguous_exceeds_posted:{day}",) if ambiguous > posted + posted_allowance else ()
    return _DayScan(posted, ambiguous, tuple(r.arm_ns for r in marks), findings, missing)


def _scan_plain_day(reads: IntradayReads, counters: IntradayCounts, day: str) -> _DayScan:
    """A whole-day scan. ``counts`` are EFFECTIVE (rows plus the day's BG-1d rebuild delta); a
    rebuild restores counts, not rows, so rows are compared with ``counts - delta`` and only a
    mismatch the delta does not explain is an integrity finding. A positive delta means arm times
    are missing for that many marks (the CP numerator still uses the effective count). A negative
    delta needs no special case: rows count, so ``counts - delta == rows`` still holds."""
    counts = counters.read_day_counts(day)
    if counts is None:
        raise IntradayInputError("day counts missing")
    rows = _ambiguous_rows(reads.read_ambiguous(day))
    delta = reads.read_counts_delta(day)
    missing = 0 if delta is None else delta.ambiguous
    findings: list[str] = []
    if counts.ambiguous > counts.posted_entries:
        findings.append(f"ambiguous_exceeds_posted:{day}")
    if len(rows) != counts.ambiguous - missing:
        findings.append(f"ambiguous_rows_mismatch:{day}")
    return _DayScan(
        counts.posted_entries,
        counts.ambiguous,
        tuple(r.arm_ns for r in rows),
        tuple(findings),
        missing=max(missing, 0),
    )


def _stage_start(floor: StageReset | None, epochs: tuple[EpochRow, ...]) -> int | None:
    """The instant the window opens: the latest ``stage_reset``, else the first K>1 epoch's boot.
    ``None``: no K>1 epoch exists, so nothing can belong to a K>1 stage."""
    if floor is not None:
        return floor.ts
    boots = [e.boot_ts for e in epochs if e.effective_k > 1]
    return min(boots) if boots else None


def _unattributed(reads: IntradayReads, start: int | None) -> _DayScan:
    """AMBIGUOUS marks BG-1b could not place on a day (arm time = the ingest instant). Those at
    or after the stage start count in the numerator and the burst; one with no usable arm time
    cannot be windowed, which is an integrity finding, never a silent drop."""
    arms: list[int] = []
    findings: list[str] = []
    for row in _ambiguous_rows(reads.read_ambiguous(UNATTRIBUTED)):
        arm = row.arm_ns
        if isinstance(arm, bool) or not isinstance(arm, int) or arm <= 0:
            if "ambiguous_unattributable" not in findings:
                findings.append("ambiguous_unattributable")
        elif start is not None and arm >= start:
            arms.append(arm)
    return _DayScan(0, len(arms), tuple(arms), tuple(findings))


def gather_intraday_inputs(
    *,
    reads: IntradayReads,
    counters: IntradayCounts,
    governed: DayConvention,
    intraday: IntradayPorts,
    now_ns: int,
    cache: DayScanCache | None = None,
) -> IntradayInputs:
    """The stage-window totals, AMBIGUOUS arm times and open costs (BG-4 ``--dry-eval`` reuses).

    With a ``cache``, labels strictly before the earliest open label (and without a gappy mark)
    are served from it after their first scan."""
    floor = reads.read_stage_reset()
    floor_ts = None if floor is None else floor.ts
    epochs = reads.read_epoch_rows()
    excluded = frozenset(row.day for row in reads.read_excluded_days())
    today = governed.today(now_ns)
    open_labels = {today, *governed.open_days_at(now_ns)}
    through = max(open_labels)
    labels = stage_day_labels(floor, epochs, governed, today, through)
    floor_labels = frozenset() if floor is None else governed.open_days_at(floor.ts)
    first_open = min(open_labels)
    gappy = frozenset() if cache is None else counters.read_gappy_days()
    scans: list[_DayScan] = []
    scan_days: list[str] = []
    for day in labels:
        if day in excluded:
            continue
        if cache is not None and day in gappy:
            cache.invalidate([day])  # never serve a scan taken before a later gappy clear
        cacheable = cache is not None and day < first_open and day not in gappy
        hit = cache.get(day, floor_ts) if cache is not None and cacheable else None
        if hit is None:
            if floor is not None and day in floor_labels:
                hit = _scan_floor_day(reads, day, floor.ts)
            else:
                hit = _scan_plain_day(reads, counters, day)
            if cache is not None and cacheable:
                cache.put(day, floor_ts, hit)
        scans.append(hit)
        scan_days.append(day)
    scans.append(_unattributed(reads, _stage_start(floor, epochs)))
    scan_days.append(UNATTRIBUTED)
    arm_times = tuple(t for x in scans for t in x.arm_ns)
    findings = [f for scan in scans for f in scan.findings]
    if not burst_trips(arm_times):  # missing arm times only matter if the rows do not trip it
        rebuilt = sorted(day for day, scan in zip(scan_days, scans, strict=True) if scan.missing)
        total_missing = sum(scan.missing for scan in scans)
        # Sound bound: every missing mark could fall inside the busiest known 60 minutes.
        if rebuilt and total_missing + max_in_window(arm_times) >= BURST_MIN_AMBIGUOUS:
            findings.append(f"burst_incomplete_rebuilt_day:{','.join(rebuilt)}")
    return IntradayInputs(
        posted=sum(x.posted for x in scans),
        ambiguous=sum(x.ambiguous for x in scans),
        ambiguous_arm_ns=arm_times,
        open_cost_by_station_day=dict(intraday.open_cost_by_station_day()),
        findings=tuple(dict.fromkeys(findings)),
        floor_ts=floor_ts,
    )


_UNSET: Final = object()
REASON_CHECK_RAISED: Final[str] = "intraday_check_raised"


class IntradayMonitor:
    """Evaluates the intraday rules and the stamp once per tick. Loop thread; never raises.

    Time base (coordinator ruling): the stamp and boot-pending ages are WALL-clock readings
    (stamps are wall-clock records). The only failure mode is a spurious integrity halt after a
    forward wall-clock jump of more than 26 h, which fails closed.
    """

    def __init__(
        self,
        *,
        reads: IntradayReads,
        counters: IntradayCounts,
        governed: DayConvention,
        boot_ns: int,
        intraday: IntradayPorts | None,
        stop: Callable[[str, int], bool],
        integrity: Callable[[str], None],
    ) -> None:
        self._reads = reads
        self._counters = counters
        self._governed = governed
        self._boot_ns = boot_ns
        self._intraday = intraday
        self._stop = stop
        self._integrity = integrity
        self._cache = DayScanCache()
        self._floor: object = _UNSET
        self._active_stops: frozenset[str] = frozenset()
        self._active_integrity: frozenset[str] = frozenset()

    def invalidate(self, days: Iterable[str] | None = None) -> None:
        """Forget cached closed-day scans (a rebuild, a late ingest or a gappy event)."""
        self._cache.invalidate(days)

    def check(self, now_ns: int) -> None:
        """One evaluation. Stop-class rules first (their reason wins the sticky halt), then the
        integrity conditions; each fresh condition is acted on once.

        At most ONE new stop-class reason is acted on per check; the others are picked up on the
        next tick (the first marker already forces the stop path, N1). A tick whose evaluation
        failed (``stops is None``) leaves the standing-stop bookkeeping unchanged, so a stop that
        is still true does not fire twice. A new ``stage_reset`` re-arms the edge: a condition
        that is still true after a reset must fire again.
        """
        try:
            stops, integrity, floor = self._evaluate(now_ns)
        except Exception as exc:  # noqa: BLE001 - total by contract; an unknown fault is a halt
            stops, integrity, floor = (
                None,
                (f"{_FAIL_PREFIX}intraday:{type(exc).__name__}",),
                _UNSET,
            )
        try:
            self._act(stops, integrity, floor, now_ns)
        except Exception as exc:  # noqa: BLE001 - an acting call raised: say so, never propagate
            logger.error("exec_par intraday acting failed: %s", type(exc).__name__)
            try:
                self._integrity(REASON_CHECK_RAISED)
            except Exception as inner:  # noqa: BLE001 - the last line of defence
                logger.error("exec_par intraday integrity halt failed: %s", type(inner).__name__)

    def _act(
        self, stops: tuple[str, ...] | None, integrity: tuple[str, ...], floor: object, now_ns: int
    ) -> None:
        if floor is not _UNSET:
            if self._floor is not _UNSET and floor != self._floor:
                self._active_stops = frozenset()
            self._floor = floor
        stop_error: Exception | None = None
        if stops is not None:
            self._active_stops &= frozenset(stops)
            fresh = [reason for reason in stops if reason not in self._active_stops]
            try:
                for reason in fresh[:1]:
                    self._stop(reason, now_ns)
                    self._active_stops |= {reason}
            except Exception as exc:  # noqa: BLE001 - the integrity loop still runs this tick
                stop_error = exc
            self._active_integrity &= frozenset(integrity)
        for reason in integrity:
            if reason not in self._active_integrity:
                self._integrity(reason)
                self._active_integrity |= {reason}
        if stop_error is not None:
            raise stop_error

    def _evaluate(self, now_ns: int) -> tuple[tuple[str, ...] | None, tuple[str, ...], object]:
        stops: tuple[str, ...] | None = None
        floor: object = _UNSET
        integrity: list[str] = []
        ports = self._intraday
        if ports is None:
            integrity.append(REASON_INTRADAY_UNBOUND)
        else:
            try:
                inputs = gather_intraday_inputs(
                    reads=self._reads,
                    counters=self._counters,
                    governed=self._governed,
                    intraday=ports,
                    now_ns=now_ns,
                    cache=self._cache,
                )
                floor = inputs.floor_ts
                integrity.extend(inputs.findings)
                stops = intraday_stop_reasons(inputs, ports.open_cost_port)
            except IntradayPredicateError as exc:
                integrity.append(exc.reason)
            except IntradayInputError:
                integrity.append(_REASON_INPUTS)
            except Exception as exc:  # noqa: BLE001 - only the TYPE is kept: no value in a reason
                logger.error("exec_par intraday read failed: %s", type(exc).__name__)
                integrity.append(f"{_REASON_READ_PREFIX}{type(exc).__name__}")
        stamp_reason = self._stamp_reason(now_ns)
        if stamp_reason is not None:
            integrity.append(stamp_reason)
        return stops, tuple(integrity), floor

    def _stamp_reason(self, now_ns: int) -> str | None:
        """Stale or never-written (after 26 h) and unreadable stamps are integrity; a pending
        boot pass is only an entry denial (the latch's), never a halt."""
        try:
            stamp = self._reads.read_stage_eval_stamp()
        except Exception as exc:  # noqa: BLE001 - an unreadable stamp is fail-closed
            logger.error("exec_par stamp read failed: %s", type(exc).__name__)
            return REASON_STAMP_UNREADABLE
        denial = stamp_denial(stamp, boot_ns=self._boot_ns, now_ns=now_ns)
        return denial if denial == REASON_STAMP_STALE else None
