"""A per-run wall-clock budget for `breezy.runtime.quote_tape_ingest_cli`.

ING-2 S2. One native unit inside the ingest timer (a whole-feather read, or a
per-type/per-file conversion) can run long enough that the WHOLE unit
overruns its systemd `TimeoutStartSec`, taking every OTHER instance's
conversion down with it (S1 residual R1). `RunDeadline` bounds how many NEW
conversion units a single run may START, without touching the native
conversion call itself -- Nautilus Trader stays untouched (see the repo
CLAUDE.md's immutable-foundation rule).

Deliberately stateful and deliberately minimal: this module imports nothing
from the rest of `breezy` (not even `quote_tape_ingest_cli`'s result types),
so `count_deferred` below works by duck typing on whatever objects the
caller passes -- avoiding a circular import between the two modules.

Sticky expiry, one guaranteed unit
-----------------------------------
Every run gets exactly ONE guaranteed unit, consumed by the first gated
conversion regardless of the clock -- a run that starts already past its
budget (a long previous run, a slow host) still lands at least one thing,
so backlog drains monotonically rather than stalling forever at zero
throughput. The first time `admit()` or `can_admit()` would otherwise
return False, the deadline CLOSES for the rest of the run: every later call
returns False even if, by some clock quirk, elapsed time were to look
smaller again later.

The loop-top peek (`can_admit()`) is bounded to one no-work scan past
expiry when the guarantee is still unused: `run()` builds the deadline
BEFORE taking the liveness/inventory snapshot, so an already-expired run
that has not yet used its guarantee is allowed to scan exactly one instance
(never more) before deferring the rest -- see the module's `note_scan`.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Any

#: Written into a `TypeConversionResult`/`InstanceIngestResult` outcome when
#: a gate denies a unit the deadline budget. Value-free by contract, like
#: every other outcome string in `quote_tape_ingest_cli`.
DEFERRED_DEADLINE = "deferred-deadline"

#: `run()`'s argparse default. Chosen to clear ordinary per-run throughput
#: (S2 plan, "Trade-offs": ~1 minute wall clock for a typical run) with
#: comfortable margin, while leaving `STARTUP_AND_TAIL_ALLOWANCE_SECONDS` of
#: headroom under the unit's `TimeoutStartSec=1800`.
DEFAULT_DEADLINE_SECONDS = 600

#: Budgeted (not measured) wall time for interpreter startup, catalog
#: listing, and output -- the part of a run this module's clock never sees.
#: `DEFAULT_DEADLINE_SECONDS + STARTUP_AND_TAIL_ALLOWANCE_SECONDS` (780s)
#: stays comfortably under the unit's 900s early-warning margin.
STARTUP_AND_TAIL_ALLOWANCE_SECONDS = 180


class RunDeadline:
    """A sticky, one-guarantee wall-clock budget shared across one run.

    `admit()` is the CONSUMING check made immediately before a conversion
    unit starts real work; `can_admit()` is a non-consuming peek made at the
    top of the instance loop, before anything (not even a preflight scan)
    happens for that instance.
    """

    def __init__(
        self,
        *,
        budget_ns: int,
        clock_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self._budget_ns = budget_ns
        self._clock_ns = clock_ns
        self._start_ns = clock_ns()
        self._guarantee_used = False
        self._closed = False
        #: Preflight scans started while this deadline peeked past expiry
        #: with the guarantee still unused -- bounds the loop-top tail to
        #: exactly one no-work scan (see the module docstring).
        self.scans_started = 0
        #: Every `admit()` call that returned True (the guarantee call
        #: included).
        self.admitted = 0
        #: Populated by `record()`, once, from the run's raw (unmerged)
        #: results -- never incremented directly by `admit`/`can_admit`.
        self.deferred_units = 0
        self.deferred_instances = 0

    @property
    def elapsed_ns(self) -> int:
        return self._clock_ns() - self._start_ns

    def admit(self) -> bool:
        """Consuming check: True admits one conversion unit to start now.

        The first call of the run always succeeds (the guaranteed unit),
        whatever the clock says. After that, `elapsed_ns < budget_ns`
        decides -- and the first False is STICKY: this deadline never grants
        another `admit()` for the rest of the run.
        """
        if self._closed:
            return False
        if not self._guarantee_used:
            self._guarantee_used = True
            self.admitted += 1
            return True
        if self.elapsed_ns < self._budget_ns:
            self.admitted += 1
            return True
        self._closed = True
        return False

    def can_admit(self) -> bool:
        """Non-consuming loop-top peek: never itself uses the guarantee.

        True while still within budget. Once expired, True only while the
        guarantee is unused AND no preflight scan has run yet this run --
        exactly one no-work-scan tail, never more (see `note_scan`).
        """
        if self._closed:
            return False
        if self.elapsed_ns < self._budget_ns:
            return True
        if not self._guarantee_used and self.scans_started == 0:
            return True
        self._closed = True
        return False

    def note_scan(self) -> None:
        """Record that a preflight scan is about to run for one instance.

        Never consumes the guarantee -- only narrows how much further
        `can_admit()` will peek past an already-expired budget.
        """
        self.scans_started += 1

    def record(self, counts: tuple[int, int]) -> None:
        """Accumulate `(deferred_units, deferred_instances)` from one call
        to `count_deferred` over this run's raw, unmerged results."""
        units, instances = counts
        self.deferred_units += units
        self.deferred_instances += instances


def count_deferred(results: Sequence[Any]) -> tuple[int, int]:
    """`(deferred_units, deferred_instances)` over RAW, unmerged results.

    Duck-typed on `InstanceIngestResult`/`TypeConversionResult`-shaped
    objects (`.instance_id`, `.outcome`, `.reason`, `.type_results`,
    `.salvage_deferred`) so this module never imports
    `quote_tape_ingest_cli`.

    Units: every per-type result whose outcome is exactly
    :data:`DEFERRED_DEADLINE`, plus one for every instance row with
    ``salvage_deferred`` set. Instances: the number of DISTINCT instance ids
    carrying a loop-top "not evaluated" deferral in either pass -- raw
    results keep an in-instance (pass 1) deferral visible even when the
    SAME instance also has a pass-2 "not evaluated" row, so this never
    double-counts one instance across the two passes.
    """
    units = 0
    not_evaluated_ids: set[str] = set()
    for result in results:
        for type_result in result.type_results:
            if type_result.outcome == DEFERRED_DEADLINE:
                units += 1
        if getattr(result, "salvage_deferred", False):
            units += 1
        if result.outcome == DEFERRED_DEADLINE and result.reason == "not evaluated":
            not_evaluated_ids.add(result.instance_id)
    return units, len(not_evaluated_ids)
