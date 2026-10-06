"""AUT-2 r7 WP2 / section 3.12: every durable fill lands in exactly one bucket, every run.

``C2_FINAL + C2_NONFINAL + UNRESOLVED + MISSING_LABEL == durable_fill_count`` and the last two
buckets are zero, or the run is FAILED_IDENTITY. ``LegacyCrhScorer`` rows count as final and as
``legacy_labelled`` (WP3).
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal
from typing import Any

import pytest

from breezy.analysis.labeling.completeness import (
    BREACH_COUNT_DECREASED,
    BREACH_MISSING_LABEL,
    BREACH_UNDECODABLE,
    BREACH_UNRESOLVED,
    Coverage,
    coverage_partition,
    identity_breaches,
    run_outcome,
)
from breezy.analysis.labeling.constants import LABEL_LAG_MAX_H
from breezy.analysis.labeling.epoch import UnresolvedCause, fill_epoch_class
from breezy.persistence.autonomy.label_schema import ExcludedReason, LabelRole, PSource
from breezy.persistence.autonomy.label_store import LabelRow, RunOutcome
from tests.support.aut2_fixtures import durable_fill

_H = 3_600_000_000_000
NOW = 1_790_000_000_000_000_000
DEADLINE = NOW - 2 * _H  # every fixture's market has settled two hours ago


def _deadline(row: LabelRow) -> int:
    return DEADLINE


def _row(coid: str, **over: Any) -> LabelRow:
    base: dict[str, Any] = {
        "label_id": coid * 4,
        "decision_id": "d" * 64,
        "family_id": "pm_us_crh_fq_v1",
        "trial_id": f"trial-{coid}",
        "client_order_id": coid,
        "trade_id": None,
        "station": "LAX",
        "climate_day": "2026-10-02",
        "instrument_id": "tc-temp-laxhigh-2026-10-02-gte89lt90f.POLYMARKET_US",
        "rung_id": "89_90",
        "leg": "yes",
        "role": LabelRole.ENTRY,
        "qty": Decimal(1),
        "fill_px": Decimal("0.40"),
        "entry_ask": Decimal("0.40"),
        "fee_reconciled": Decimal("0.03"),
        "slippage": Decimal(0),
        "p_at_decision": 0.6,
        "p_raw_at_decision": 0.6,
        "p_source": PSource.C1_DECISION,
        "settled_outcome": True,
        "settlement_tmax_f": Decimal(89),
        "settlement_basis": "nws_final",
        "realized_pnl": Decimal("0.57"),
        "counterfactual_hold_pnl": None,
        "reconciled": True,
        "reconciliation_delta": Decimal(0),
        "reconciliation_source": "venue_get",
        "net_position_key": "slug",
        "admissible": True,
        "excluded_reason": None,
        "labelled_at_ns": NOW,
        "label_seq": 0,
        "scorer_id": "forecast_quantile_ladder/v1",
    }
    base.update(over)
    return LabelRow(**base)


def _fills(n: int) -> list[Any]:
    return [
        durable_fill(venue_order_id=f"vo-{i}", client_order_id=f"O-{i}", ts_event=NOW - 5 * _H)
        for i in range(n)
    ]


def _four_labelled() -> tuple[list[Any], list[LabelRow]]:
    fills = _fills(4)
    labels = [
        _row("O-0"),
        _row("O-1", admissible=False, excluded_reason=ExcludedReason.CANARY),
        _row(
            "O-2",
            admissible=False,
            excluded_reason=ExcludedReason.UNATTRIBUTED,
            p_source=PSource.NONE,
            p_at_decision=None,
            p_raw_at_decision=None,
        ),
        _row("O-3", admissible=False, excluded_reason=ExcludedReason.WINDOW_INCOMPLETE),
    ]
    return fills, labels


def _partition(fills: list[Any], labels: list[LabelRow], **kw: Any) -> Coverage:
    return coverage_partition(fills, labels, now_ns=NOW, deadline_ns=_deadline, **kw)


def test_labelled_plus_excluded_equals_durable_count() -> None:
    fills, labels = _four_labelled()

    coverage = _partition(fills, labels)

    assert coverage.durable_fill_count == 4
    assert (coverage.c2_final, coverage.pending, coverage.open) == (3, 1, 0)
    assert coverage.unattributed_pre_epoch == 1
    assert (coverage.unresolved, coverage.missing_label) == (0, 0)
    assert (
        coverage.c2_final + coverage.c2_nonfinal + coverage.unresolved + coverage.missing_label
        == coverage.durable_fill_count
    )
    assert identity_breaches(coverage, durable_fill_count_prev=4) == ()


def test_deleting_one_label_fails_identity() -> None:
    fills, labels = _four_labelled()

    coverage = _partition(fills, labels[1:])  # the positive control: a label vanishes

    assert coverage.missing_label == 1
    assert BREACH_MISSING_LABEL in identity_breaches(coverage, durable_fill_count_prev=4)
    assert (
        run_outcome(coverage, rows_written=3, durable_fill_count_prev=4)
        is RunOutcome.FAILED_IDENTITY
    )


def test_scorer_silently_dropping_a_fill_is_missing_label() -> None:
    """P9: a Scorer returns rows for every fill but one. The omission is counted, never absorbed.

    The marker write and the delivered CRITICAL belong to the label run (WP6); here the partition
    must call the omission MISSING_LABEL and the run outcome must be FAILED_IDENTITY."""
    fills, labels = _four_labelled()

    class _DroppingScorer:
        refusing = False

        def label(self, capture_day: object, exec_fills: list[Any], settlements: object) -> Any:
            wanted = {f.client_order_id for f in exec_fills[:-1]}
            return tuple(row for row in labels if row.client_order_id in wanted)

    produced = list(_DroppingScorer().label(None, fills, None))
    coverage = _partition(fills, produced)

    assert coverage.missing_label == 1
    assert run_outcome(coverage, rows_written=len(produced), durable_fill_count_prev=4) is (
        RunOutcome.FAILED_IDENTITY
    )


def test_durable_fill_count_decrease_is_failed_identity() -> None:
    fills, labels = _four_labelled()
    coverage = _partition(fills, labels)

    breaches = identity_breaches(coverage, durable_fill_count_prev=5)

    assert breaches == (BREACH_COUNT_DECREASED,)
    assert (
        run_outcome(coverage, rows_written=4, durable_fill_count_prev=5)
        is RunOutcome.FAILED_IDENTITY
    )
    assert identity_breaches(coverage, durable_fill_count_prev=None) == ()  # the first run has none


def test_missing_label_bucket_counts_as_failure() -> None:
    fills, _labels = _four_labelled()

    coverage = _partition(fills, [])  # nothing labelled at all

    assert (coverage.missing_label, coverage.c2_final) == (4, 0)
    assert identity_breaches(coverage, durable_fill_count_prev=None) == (BREACH_MISSING_LABEL,)


def test_unresolved_fill_fails_identity() -> None:
    fills, labels = _four_labelled()
    unresolved = frozenset({fills[0].venue_order_id})

    coverage = _partition(fills, labels[1:], unresolved_fill_keys=unresolved)

    assert (coverage.unresolved, coverage.missing_label) == (1, 0)
    assert identity_breaches(coverage, durable_fill_count_prev=None) == (BREACH_UNRESOLVED,)
    assert run_outcome(coverage, rows_written=3, durable_fill_count_prev=None) is (
        RunOutcome.FAILED_IDENTITY
    )
    undecodable = dataclasses.replace(_partition(fills, labels), n_undecodable=1)
    assert BREACH_UNDECODABLE in identity_breaches(undecodable, durable_fill_count_prev=None)


def test_post_epoch_fill_without_order_link_is_unresolved() -> None:
    class _Reader:
        def epoch_start_ns(self) -> int | None:
            return NOW - 10 * _H

        def order_link(self, client_order_id: str) -> None:
            return None  # C1 invariant (ii) broken: a post-epoch fill with no link

        def earliest_order_link_ns(self) -> int | None:
            return None

    fill = durable_fill(venue_order_id="vo-x", client_order_id="O-x", ts_event=NOW - 5 * _H)
    outcome = fill_epoch_class(fill, _Reader())
    assert outcome.unresolved_cause is UnresolvedCause.POST_EPOCH_WITHOUT_ORDER_LINK

    coverage = _partition([fill], [], unresolved_fill_keys=frozenset({fill.venue_order_id}))

    assert coverage.unresolved == 1
    assert run_outcome(coverage, rows_written=0, durable_fill_count_prev=None) is (
        RunOutcome.FAILED_IDENTITY
    )


def test_run_outcome_vocabulary_and_open_versus_pending() -> None:
    fills = _fills(1)
    before_deadline = coverage_partition(
        fills,
        [_row("O-0", admissible=False, excluded_reason=ExcludedReason.WINDOW_INCOMPLETE)],
        now_ns=NOW,
        deadline_ns=lambda row: NOW + _H,
    )
    assert (before_deadline.open, before_deadline.pending) == (1, 0)
    clean = _partition(fills, [_row("O-0")])
    assert run_outcome(clean, rows_written=1, durable_fill_count_prev=1) is RunOutcome.LABELLED
    assert run_outcome(clean, rows_written=0, durable_fill_count_prev=1) is RunOutcome.NO_INPUT
    pending = _partition(
        fills, [_row("O-0", admissible=False, excluded_reason=ExcludedReason.WINDOW_INCOMPLETE)]
    )
    assert run_outcome(pending, rows_written=0, durable_fill_count_prev=1) is RunOutcome.PENDING
    # a fee still unreconciled inside the lag horizon is non-final; past it, it is final
    fee_row = _row("O-0", admissible=False, excluded_reason=ExcludedReason.FEE_UNRECONCILED)
    inside = coverage_partition(
        fills, [fee_row], now_ns=NOW, deadline_ns=lambda r: NOW - (LABEL_LAG_MAX_H - 1) * _H
    )
    past = coverage_partition(
        fills, [fee_row], now_ns=NOW, deadline_ns=lambda r: NOW - (LABEL_LAG_MAX_H + 1) * _H
    )
    assert (inside.c2_final, past.c2_final) == (0, 1)
    with pytest.raises(ValueError):
        coverage_partition(
            fills,
            [fee_row],
            now_ns=NOW,
            deadline_ns=_deadline,
            unresolved_fill_keys=frozenset({"x"}),
            n_undecodable=-1,
        )


def test_legacy_crh_fills_labelled_by_legacy_scorer() -> None:
    from breezy.analysis.labeling.legacy_crh_scorer import (
        LEGACY_SCORER_ID,
        LegacyCrhScorer,
        LegacyFillInput,
    )

    buys = [
        durable_fill(venue_order_id=f"vo-{n}", client_order_id=f"O-{n}", ts_event=NOW - 5 * _H)
        for n in (1, 2)
    ]
    sell = durable_fill(
        venue_order_id="vo-3", client_order_id="O-3", order_side="SELL", ts_event=NOW - 4 * _H
    )
    fills = [*buys, sell]
    inputs = [
        LegacyFillInput(fill=f, label_family="pm_us_crh_v4", trial_id=f"t-{i}", scored=None)
        for i, f in enumerate(fills)
    ]
    rows = LegacyCrhScorer(now_ns=NOW, prior=()).label(None, inputs, None)

    coverage = coverage_partition(
        fills, rows, now_ns=NOW, deadline_ns=_deadline, legacy_scorer_ids={LEGACY_SCORER_ID}
    )

    assert (coverage.c2_final, coverage.legacy_labelled, coverage.missing_label) == (3, 3, 0)
    assert identity_breaches(coverage, durable_fill_count_prev=None) == ()
