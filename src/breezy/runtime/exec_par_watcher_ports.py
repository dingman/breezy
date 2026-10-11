"""EXEC-PAR: the watcher's injected ports (split out of ``breaker_watcher``; no behaviour).

``breaker_watcher`` re-exports these names, so every existing import keeps working.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol, runtime_checkable

from breezy.runtime.exec_par_counter_ingest import IntentView
from breezy.runtime.exec_par_records import (
    AmbiguousRow,
    Amendment,
    CleanupDemotion,
    DenialRow,
    EpochRow,
    ExcludedDay,
    FillRow,
    ForceK1Cleared,
    ForceK1Flag,
    GappyMark,
    OpenCostFlag,
    OrderAnchor,
    SettledPnlDay,
    StageEvalDry,
    StageReset,
    StopVerdict,
    WindowPeak,
)

__all__ = ["AmendmentPort", "BreakerLatchPort", "ExecParStorePort", "LedgerPredicatePort"]


class BreakerLatchPort(Protocol):
    """The two single-writer breaker-record methods of ``SubmitIntentLatch``."""

    def write_breaker_heartbeat(self, *, hb_ns: int, resolver_pass_ns: int) -> None: ...
    def write_breaker_halt(self, reason: str, *, ts_ns: int) -> None: ...


@runtime_checkable
class AmendmentPort(Protocol):
    """BG-2: the one latch method the K>1 watcher uses to record a K-forced amendment."""

    def write_amendment(self, record: Amendment) -> None: ...


class ExecParStorePort(Protocol):
    """BG-1a store writer: the durable D-PREREG records (spec 10a, K9, M3, N4).

    Implemented by single-writer ``SubmitIntentLatch`` methods that each run
    under ``_require_held()`` and never nest the latch ``_mutex``. Readers on
    the latch (``read_*``) are not part of this write port. A write failure
    propagates (the caller maps it to ``telemetry_write_fail`` or, for the
    marker, ``stop_marker_write_fail``).
    """

    def write_stage_reset(self, record: StageReset) -> None: ...
    def add_excluded_day(self, record: ExcludedDay) -> bool: ...
    def write_epoch_row(self, record: EpochRow) -> None: ...
    def write_epoch_stop_ts(self, boot_ts: int, stop_ts: int) -> bool: ...
    def write_amendment(self, record: Amendment) -> None: ...
    def write_stage_eval_dry(self, record: StageEvalDry) -> None: ...
    def write_force_k1_cleared(self, record: ForceK1Cleared) -> None: ...
    def write_stop_verdict(self, record: StopVerdict) -> None: ...
    def write_cleanup_demotion(self, record: CleanupDemotion) -> None: ...
    def write_force_k1_flag(self, record: ForceK1Flag) -> None: ...
    def clear_force_k1_flag(self, cleared_ts_ns: int) -> None: ...
    def write_settled_pnl_day(self, record: SettledPnlDay) -> None: ...
    def mark_flag_write_failed(self) -> None: ...
    def clear_flag_write_failed(self) -> None: ...

    # BG-1b per-climate-day counter rows (event-sourced, exclusive, idempotent).
    def write_order_anchor(self, record: OrderAnchor) -> bool: ...
    def read_order_anchor(self, client_order_id: str) -> OrderAnchor | None: ...
    def read_intent(self, intent_id: str) -> IntentView | None: ...
    def write_denial(self, record: DenialRow) -> bool: ...
    def write_ambiguous(self, record: AmbiguousRow) -> bool: ...
    def write_fill(self, record: FillRow) -> bool: ...
    def write_open_cost_flag(self, record: OpenCostFlag) -> OpenCostFlag: ...
    def add_window_order(
        self, day: str, window_start_ns: int, notional: Decimal, client_order_id: str
    ) -> WindowPeak: ...
    def write_gappy_mark(self, record: GappyMark) -> bool: ...


class LedgerPredicatePort(Protocol):
    """Value-free ledger predicates (K6): aggregates in, ``bool`` only out.

    The caller (loop thread) passes already-aggregated Decimals; the port
    compares them against budget fractions and returns a bool. Currency
    values never leave the port's caller and are never logged. A raise or a
    non-bool return counts as tripped. ``DailySpendLedger`` implements this
    structurally (BG-1e). The 5 s window share and the 2-of-5 day counts are
    pure ratios / counts that need no budget, so the caller compares them
    itself and they are deliberately not on this port.
    """

    def pnl_breaches_budget_fraction(
        self, *, aggregate_pnl: Decimal, fraction: Decimal
    ) -> bool: ...
    def open_cost_exceeds_budget_fraction(
        self, *, aggregate_open_cost: Decimal, fraction: Decimal
    ) -> bool: ...
