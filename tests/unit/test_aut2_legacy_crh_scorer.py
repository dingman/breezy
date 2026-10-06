"""AUT-2 r7 WP3 / section 3.3 (P2-6, P3): retired CRH kinds keep a real Scorer.

``LegacyCrhScorer`` maps each frozen CRH ``ScoredTrial`` joined to a durable BUY fill into one
unattributed C2 row. A SELL fill is never priced from ``ScoredTrial``. The cash of these rows stays
in the legacy reconciliation, so no row here emits a cash record.
"""

from __future__ import annotations

from dataclasses import fields
from decimal import Decimal
from typing import Any

from breezy.analysis.labeling import legacy_crh_scorer
from breezy.analysis.labeling.legacy_crh_scorer import (
    LEGACY_SCORER_ID,
    LegacyCrhScorer,
    LegacyFillInput,
    LegacyLabelResult,
    scorer_may_refuse,
)
from breezy.persistence.autonomy.label_schema import ExcludedReason, LabelRole, PSource
from breezy.settlement.trial_scorer import ScoredTrial
from tests.support.aut2_fixtures import HOUR_NS, RELEASE_NS, TS, YES, durable_fill

_FAMILY = "pm_us_crh_v4"
_TRIAL = "continuous_rung_hold/trial/LAX/2026-10-02"


def _scored(**over: Any) -> ScoredTrial:
    base: dict[str, Any] = {
        "trial_id": _TRIAL,
        "station": "LAX",
        "climate_day": "2026-10-02",
        "instrument_id": YES,
        "settlement_tmax_f": 89,
        "held": True,
        "pnl": Decimal("0.57"),
        "revision_seq": 1,
        "raw_sha256": "a" * 64,
        "scored_at_ns": RELEASE_NS,
        "score_seq": 0,
        "settlement_basis": "nws_final",
        "excluded_reason": None,
        "slippage": Decimal(0),
        "entry_ask": Decimal("0.40"),
        "fill_px": Decimal("0.40"),
        "fee": Decimal("0.03"),
    }
    base.update(over)
    return ScoredTrial(**base)


def _input(*, side: str = "BUY", scored: ScoredTrial | None = None, coid: str = "O-1") -> Any:
    fill = durable_fill(
        venue_order_id=f"vo-{coid}", client_order_id=coid, order_side=side, ts_event=TS
    )
    return LegacyFillInput(fill=fill, label_family=_FAMILY, trial_id=_TRIAL, scored=scored)


def _label(*inputs: Any, now_ns: int = RELEASE_NS + HOUR_NS) -> LegacyLabelResult:
    return LegacyCrhScorer(now_ns=now_ns, prior=()).label_with_counts(None, list(inputs), None)


def test_retired_kind_keeps_scorer_until_last_fill_labelled() -> None:
    for kind in ("current_rung_hold", "continuous_rung_hold"):
        assert scorer_may_refuse(kind, unlabelled_fills=3) is False
        assert scorer_may_refuse(kind, unlabelled_fills=0) is True
    assert scorer_may_refuse("forecast_quantile_ladder", unlabelled_fills=0) is False


def test_legacy_rows_are_unattributed_with_p_source_none() -> None:
    result = _label(_input(scored=_scored()))

    row = result.rows[0]
    assert row.decision_id is None and row.excluded_reason is ExcludedReason.UNATTRIBUTED
    assert (row.p_source, row.p_at_decision, row.p_raw_at_decision) == (PSource.NONE, None, None)
    assert row.admissible is False and row.scorer_id == LEGACY_SCORER_ID
    assert row.family_id == _FAMILY and row.trial_id == _TRIAL and row.role is LabelRole.ENTRY
    assert (row.settled_outcome, row.realized_pnl) == (True, Decimal("0.57"))


def test_a_legacy_buy_pnl_is_scored_trial_pnl_times_qty() -> None:
    fill = durable_fill(
        venue_order_id="vo-2",
        client_order_id="O-2",
        qty=Decimal(2),
        cost=Decimal("0.80"),
        ts_event=TS,
    )
    inp = LegacyFillInput(fill=fill, label_family=_FAMILY, trial_id=_TRIAL, scored=_scored())

    row = _label(inp).rows[0]

    assert row.realized_pnl == Decimal("1.14")


def test_an_unscored_legacy_buy_is_labelled_pending_with_null_pnl() -> None:
    row = _label(_input(scored=None)).rows[0]

    assert row.settled_outcome is None and row.realized_pnl is None
    assert row.excluded_reason is ExcludedReason.UNATTRIBUTED


def test_legacy_rows_emit_no_cash_record() -> None:
    names = {f.name for f in fields(LegacyLabelResult)}

    assert not any("cash" in name for name in names)
    assert not hasattr(LegacyCrhScorer, "cash_records")
    assert "reconcile" not in " ".join(vars(legacy_crh_scorer))


def test_forecast_ladder_scorer_may_refuse_with_no_fills() -> None:
    assert scorer_may_refuse("forecast_ladder", unlabelled_fills=0) is True
    assert scorer_may_refuse("forecast_ladder", unlabelled_fills=1) is False


def test_legacy_crh_sell_labelled_unattributed_with_null_pnl() -> None:
    result = _label(_input(side="SELL", scored=_scored()))

    row = result.rows[0]
    assert row.role is LabelRole.EXIT and row.excluded_reason is ExcludedReason.UNATTRIBUTED
    assert (row.realized_pnl, row.counterfactual_hold_pnl) == (None, None)
    assert row.p_source is PSource.NONE and row.admissible is False
    assert result.legacy_sell_rows == 1
    assert result.rows[0].label_seq == 0


def test_a_sell_row_is_final_for_completeness_and_never_missing() -> None:
    from breezy.analysis.labeling.completeness import is_final_row

    row = _label(_input(side="SELL", scored=None)).rows[0]

    assert is_final_row(row, now_ns=RELEASE_NS, deadline_ns=RELEASE_NS + 10 * HOUR_NS) is True


def test_a_correction_relabels_at_the_next_label_seq() -> None:
    first = _label(_input(scored=None)).rows[0]
    second = LegacyCrhScorer(now_ns=RELEASE_NS + 2 * HOUR_NS, prior=(first,)).label_with_counts(
        None, [_input(scored=_scored())], None
    )
    same = LegacyCrhScorer(
        now_ns=RELEASE_NS + 3 * HOUR_NS, prior=(second.rows[0],)
    ).label_with_counts(None, [_input(scored=_scored())], None)

    assert second.rows[0].label_seq == 1 and second.rows[0].realized_pnl == Decimal("0.57")
    assert same.rows == ()
