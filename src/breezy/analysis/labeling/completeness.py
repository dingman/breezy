"""The completeness identity: every durable fill in exactly one bucket (AUT-2 r7 WP2, section 3.12).

``coverage_partition`` places every fill the reader found in one of four buckets:

* ``C2_FINAL``: a C2 row that is admissible, carries a final ``excluded_reason``, or is settled
  with no exclusion (a venue-fallback or never-position-compared row, re-evaluated by the
  reconciliation, never by a missing label). The pre-epoch ``unattributed`` rows and the
  ``LegacyCrhScorer`` rows are counted separately inside it.
* ``C2_NONFINAL``: only non-final rows: ``window_incomplete``, a ``fee_unreconciled`` row still
  inside ``LABEL_LAG_MAX_H`` of the market's settlement instant, or an unsettled row. It is ``open``
  while ``now < settlement_deadline_ns``, else ``pending``.
* ``UNRESOLVED``: no unique identity (the caller's fill keys).
* ``MISSING_LABEL``: resolved, and no C2 row exists for it after this run's write. Every resolved
  fill gets at least a ``window_incomplete`` row, so a non-zero count is always a defect.

The identity holds, and the run is not FAILED_IDENTITY, only when ``UNRESOLVED == MISSING_LABEL ==
n_undecodable == 0`` and ``durable_fill_count`` did not fall below the previous marker's.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from typing import Final

from breezy.adapters.polymarket_us.exec.client import DurableFillRecord
from breezy.analysis.labeling.constants import LABEL_LAG_MAX_H
from breezy.persistence.autonomy.label_schema import ExcludedReason, LabelRole
from breezy.persistence.autonomy.label_store import LabelRow, RunOutcome

__all__ = [
    "BREACH_COUNT_DECREASED",
    "BREACH_MISSING_LABEL",
    "BREACH_PARTITION_SUM",
    "BREACH_UNDECODABLE",
    "BREACH_UNRESOLVED",
    "Coverage",
    "coverage_partition",
    "identity_breaches",
    "is_final_row",
    "run_outcome",
]

BREACH_UNRESOLVED: Final = "unresolved"
BREACH_MISSING_LABEL: Final = "missing_label"
BREACH_UNDECODABLE: Final = "undecodable_fill"
BREACH_COUNT_DECREASED: Final = "durable_fill_count_decreased"
BREACH_PARTITION_SUM: Final = "partition_sum"

_NS_PER_H: Final = 3_600_000_000_000
#: Final for every run (plan section 3.5). ``fee_unreconciled`` is final only past the horizon.
_FINAL_REASONS: Final = frozenset(
    {
        ExcludedReason.DUPLICATE_FILL,
        ExcludedReason.QTY_NOT_ONE,
        ExcludedReason.CANARY,
        ExcludedReason.DRILL,
        ExcludedReason.VOIDED_PAIR,
        ExcludedReason.SLIPPAGE_DEFECT,
        ExcludedReason.UNATTRIBUTED,
    }
)


@dataclass(frozen=True)
class Coverage:
    durable_fill_count: int
    c2_final: int
    open: int
    pending: int
    unresolved: int
    missing_label: int
    unattributed_pre_epoch: int
    legacy_labelled: int
    n_undecodable: int = 0

    @property
    def c2_nonfinal(self) -> int:
        return self.open + self.pending


def is_final_row(row: LabelRow, *, now_ns: int, deadline_ns: int) -> bool:
    """Whether ``row`` can no longer change the completeness identity."""
    if row.admissible:
        return True
    reason = row.excluded_reason
    if reason in _FINAL_REASONS:
        return True
    if reason is ExcludedReason.FEE_UNRECONCILED:
        return now_ns >= deadline_ns + LABEL_LAG_MAX_H * _NS_PER_H
    if reason is ExcludedReason.WINDOW_INCOMPLETE:
        return False
    return row.settled_outcome is not None


def _role_of(fill: DurableFillRecord) -> LabelRole:
    return LabelRole.ENTRY if fill.order_side == "BUY" else LabelRole.EXIT


def coverage_partition(
    fills: Sequence[DurableFillRecord],
    labels: Sequence[LabelRow],
    *,
    now_ns: int,
    deadline_ns: Callable[[LabelRow], int],
    unresolved_fill_keys: Collection[str] = frozenset(),
    n_undecodable: int = 0,
    legacy_scorer_ids: Collection[str] = frozenset(),
) -> Coverage:
    """Partition ``fills`` by the label rows that cover them.

    A fill is covered by the rows with its ``client_order_id`` and its role (BUY entry, SELL exit);
    ``unresolved_fill_keys`` holds the ``venue_order_id`` of every fill the caller could not
    identify. Raises ``ValueError`` for a negative ``n_undecodable``.
    """
    if n_undecodable < 0:
        raise ValueError("n_undecodable must not be negative")
    by_coid: dict[tuple[str, LabelRole], list[LabelRow]] = {}
    for row in labels:
        by_coid.setdefault((row.client_order_id, row.role), []).append(row)
    final = opened = pending = unresolved = missing = unattributed = legacy = 0
    for fill in fills:
        if fill.venue_order_id in unresolved_fill_keys:
            unresolved += 1
            continue
        rows = by_coid.get((fill.client_order_id, _role_of(fill)))
        if not rows:
            missing += 1
            continue
        nonfinal = [
            row
            for row in rows
            if not is_final_row(row, now_ns=now_ns, deadline_ns=deadline_ns(row))
        ]
        if nonfinal:
            if now_ns < deadline_ns(nonfinal[0]):
                opened += 1
            else:
                pending += 1
            continue
        final += 1
        if any(row.scorer_id in legacy_scorer_ids for row in rows):
            legacy += 1
        elif any(row.excluded_reason is ExcludedReason.UNATTRIBUTED for row in rows):
            unattributed += 1
    return Coverage(
        durable_fill_count=len(fills),
        c2_final=final,
        open=opened,
        pending=pending,
        unresolved=unresolved,
        missing_label=missing,
        unattributed_pre_epoch=unattributed,
        legacy_labelled=legacy,
        n_undecodable=n_undecodable,
    )


def identity_breaches(
    coverage: Coverage, *, durable_fill_count_prev: int | None
) -> tuple[str, ...]:
    """Every identity breach, in a fixed order; empty when the identity holds."""
    breaches: list[str] = []
    total = coverage.c2_final + coverage.c2_nonfinal + coverage.unresolved + coverage.missing_label
    if total != coverage.durable_fill_count:
        breaches.append(BREACH_PARTITION_SUM)
    if coverage.unresolved:
        breaches.append(BREACH_UNRESOLVED)
    if coverage.missing_label:
        breaches.append(BREACH_MISSING_LABEL)
    if coverage.n_undecodable:
        breaches.append(BREACH_UNDECODABLE)
    if (
        durable_fill_count_prev is not None
        and coverage.durable_fill_count < durable_fill_count_prev
    ):
        breaches.append(BREACH_COUNT_DECREASED)
    return tuple(breaches)


def run_outcome(
    coverage: Coverage, *, rows_written: int, durable_fill_count_prev: int | None
) -> RunOutcome:
    """FAILED_IDENTITY overrides everything; NO_INPUT only for zero rows with nothing open to
    resolve; zero rows with pending work is PENDING; otherwise LABELLED."""
    if identity_breaches(coverage, durable_fill_count_prev=durable_fill_count_prev):
        return RunOutcome.FAILED_IDENTITY
    if rows_written == 0:
        return RunOutcome.PENDING if coverage.pending > 0 else RunOutcome.NO_INPUT
    return RunOutcome.LABELLED
