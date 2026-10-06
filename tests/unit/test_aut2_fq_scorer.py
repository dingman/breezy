"""AUT-2 r7 WP3 / sections 3.3 and 3.5: the FQ Scorer turns durable fills into C2 entry rows.

Realised P&L comes from the exec-store fill and the settlement record only. ``score_trial`` is the
single settlement oracle (reused unchanged); the label asserts its identity for q = 1 entries held
to settlement and never smooths a difference.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest

from breezy.analysis.labeling import fq_scorer
from breezy.analysis.labeling.attribution import Attribution, PreEpochAttribution
from breezy.analysis.labeling.completeness import is_final_row
from breezy.analysis.labeling.constants import LABEL_LAG_MAX_H, WINDOW_INCOMPLETE_MAX_H
from breezy.analysis.labeling.decision_link import BridgeMatch
from breezy.analysis.labeling.fq_scorer import (
    FQ_SCORER_ID,
    ForecastQuantileLadderScorer,
    FqFillInput,
    Reconciliation,
    ScorerIdentityError,
    label_id_of,
)
from breezy.analysis.labeling.settlement_source import SettlementSourceRefused
from breezy.domain.nws_climate_day import NwsClimateDay
from breezy.persistence.autonomy.label_schema import ExcludedReason, LabelRole, PSource
from breezy.persistence.autonomy.label_store import LabelRow, UnmappedScorerReason
from breezy.settlement.trial_scorer import ScoredTrial
from breezy.settlement.trial_scorer import score_trial as real_score_trial
from tests.contract.test_catalog_nws_records import make_climate_day
from tests.support.aut2_fixtures import durable_fill
from tests.unit.test_aut2_attribution import NO, TS, YES, _decision, _link

_DAY = dt.date(2026, 10, 2)
_H = 3_600_000_000_000
_REL = TS + 10 * _H
_FAMILY = "pm_us_crh_fq_v1"
_GOOD = Reconciliation(reconciled=True, delta=Decimal(0), source="venue_get")


class _Source:
    """A settlement source over a fixed record (or none)."""

    def __init__(self, record: NwsClimateDay | None) -> None:
        self._record = record

    def record(self, station: str, climate_day: dt.date) -> NwsClimateDay | None:
        return self._record


def _rec(tmax: int = 89, **over: Any) -> NwsClimateDay:
    return make_climate_day(station="LAX", climate_day=_DAY, tmax_f=tmax, **over)


def _attr(*, side: str = "yes", ask: str = "0.40", drill: bool = False, **over: Any) -> Attribution:
    instrument = YES if side == "yes" else NO
    decision = _decision(side=side, ask_px=ask, drill=drill, instrument_id=instrument, **over)
    return Attribution(
        family_id=_FAMILY,
        decision=decision,
        link=_link(instrument_id=instrument),
        drill=drill,
        voided_pair=False,
        alerts=(),
    )


def _inp(
    *,
    coid: str = "O-1",
    side: str = "yes",
    qty: int = 1,
    cost: str = "0.40",
    fee: str = "0.03",
    fee_reconciled: bool = True,
    venue_order_id: str = "vo-1",
    ask: str = "0.40",
    reconciliation: Reconciliation = _GOOD,
    attribution: Attribution | PreEpochAttribution | None = None,
    **over: Any,
) -> FqFillInput:
    instrument = YES if side == "yes" else NO
    fill = durable_fill(
        venue_order_id=venue_order_id,
        client_order_id=coid,
        instrument_id=instrument,
        qty=Decimal(qty),
        cost=Decimal(cost),
        fee=Decimal(fee),
        fee_reconciled=fee_reconciled,
        ts_event=TS,
    )
    return FqFillInput(
        fill=fill,
        attribution=attribution if attribution is not None else _attr(side=side, ask=ask),
        scheduled_release_at_ns=_REL,
        reconciliation=reconciliation,
        **over,
    )


def _label(
    inputs: list[FqFillInput],
    record: NwsClimateDay | None,
    *,
    now_ns: int = _REL + _H,
    prior: tuple[LabelRow, ...] = (),
) -> fq_scorer.LabelResult:
    scorer = ForecastQuantileLadderScorer(now_ns=now_ns, prior=prior)
    return scorer.label_with_alerts(_DAY, inputs, _Source(record))


def _only(result: fq_scorer.LabelResult) -> LabelRow:
    assert len(result.rows) == 1
    return result.rows[0]


# -- P&L, both legs ------------------------------------------------------------------------------


def test_yes_win_and_yes_loss_pnl_net_of_reconciled_fee() -> None:
    win = _only(_label([_inp()], _rec(89)))
    loss = _only(_label([_inp()], _rec(95)))

    assert (win.settled_outcome, win.realized_pnl) == (True, Decimal("0.57"))
    assert (loss.settled_outcome, loss.realized_pnl) == (False, Decimal("-0.43"))
    assert win.fee_reconciled == Decimal("0.03") and win.settlement_basis == "nws_final"
    assert win.admissible is True and win.excluded_reason is None
    assert win.p_source is PSource.C1_DECISION and win.p_at_decision == pytest.approx(0.62)


def test_no_leg_win_and_no_leg_loss_pnl() -> None:
    win = _only(_label([_inp(side="no")], _rec(95)))
    loss = _only(_label([_inp(side="no")], _rec(89)))

    assert (win.leg, win.settled_outcome, win.realized_pnl) == ("no", True, Decimal("0.57"))
    assert (loss.settled_outcome, loss.realized_pnl) == (False, Decimal("-0.43"))
    assert win.p_at_decision == pytest.approx(0.38) and win.p_raw_at_decision == pytest.approx(0.38)
    assert win.instrument_id == NO and win.net_position_key == YES.removesuffix(".POLYMARKET_US")


def test_realized_pnl_equals_score_trial_pnl_times_qty(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[ScoredTrial] = []
    real = real_score_trial

    def _spy(*args: Any, **kwargs: Any) -> Any:
        result = real(*args, **kwargs)
        assert isinstance(result, ScoredTrial)
        seen.append(result)
        return result

    monkeypatch.setattr(fq_scorer, "score_trial", _spy)
    row = _only(_label([_inp()], _rec(89)))

    assert len(seen) == 1
    assert row.realized_pnl == seen[0].pnl * Decimal(1) == Decimal("0.57")


def test_label_refuses_a_score_trial_identity_break(monkeypatch: pytest.MonkeyPatch) -> None:
    real = real_score_trial

    def _off(*args: Any, **kwargs: Any) -> Any:
        result = real(*args, **kwargs)
        assert isinstance(result, ScoredTrial)
        return replace(result, pnl=result.pnl + Decimal("0.01"))

    monkeypatch.setattr(fq_scorer, "score_trial", _off)

    with pytest.raises(ScorerIdentityError):
        _label([_inp()], _rec(89))


def test_score_trial_identity_scoped_to_q1_entries_held_to_settlement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = real_score_trial

    def _off(*args: Any, **kwargs: Any) -> Any:
        result = real(*args, **kwargs)
        assert isinstance(result, ScoredTrial)
        return replace(result, pnl=result.pnl + Decimal("0.01"))

    monkeypatch.setattr(fq_scorer, "score_trial", _off)

    # q = 2 is outside the identity (and excluded), and an exit row is never compared with it
    two = _only(_label([_inp(qty=2, cost="0.80", fee="0.06")], _rec(89)))
    sell = replace(
        _inp(venue_order_id="vo-2", coid="O-2"),
        fill=durable_fill(
            venue_order_id="vo-2", client_order_id="O-2", order_side="SELL", ts_event=TS + 1
        ),
    )
    exit_row = _only(_label([sell], _rec(89)))

    assert two.excluded_reason is ExcludedReason.QTY_NOT_ONE
    assert two.realized_pnl == Decimal("1.14")  # 2 x payoff - cost - fee, never smoothed
    assert exit_row.role is LabelRole.EXIT and exit_row.realized_pnl is None


# -- fees, slippage, exclusions -------------------------------------------------------------------


def test_fee_unreconciled_excluded_and_alerted() -> None:
    inside = _label([_inp(fee_reconciled=False)], _rec(89), now_ns=_REL + _H)
    after = _label([_inp(fee_reconciled=False)], _rec(89), now_ns=_REL + (LABEL_LAG_MAX_H + 1) * _H)

    row = _only(inside)
    assert row.excluded_reason is ExcludedReason.FEE_UNRECONCILED
    assert row.fee_reconciled is None and row.realized_pnl is None and row.admissible is False
    assert [(a.severity, a.code) for a in inside.alerts] == [("WARN", "fee_unreconciled")]
    assert is_final_row(row, now_ns=_REL + _H, deadline_ns=_REL) is False
    assert [(a.severity, a.code) for a in after.alerts] == [("CRITICAL", "fee_unreconciled")]
    assert (
        is_final_row(_only(after), now_ns=_REL + (LABEL_LAG_MAX_H + 1) * _H, deadline_ns=_REL)
        is True
    )


def test_preliminary_cli_never_settles() -> None:
    row = _only(_label([_inp()], _rec(89, is_final=False)))

    assert row.settled_outcome is None and row.settlement_basis is None
    assert row.settlement_tmax_f is None and row.realized_pnl is None
    assert row.excluded_reason is ExcludedReason.WINDOW_INCOMPLETE and row.admissible is False


def test_correction_relabels_with_next_label_seq() -> None:
    first = _only(_label([_inp()], _rec(89), now_ns=_REL + _H))
    corrected = _label([_inp()], _rec(95, revision_seq=2), now_ns=_REL + 2 * _H, prior=(first,))
    unchanged = _label([_inp()], _rec(89), now_ns=_REL + 3 * _H, prior=(first,))

    row = _only(corrected)
    assert (first.label_seq, row.label_seq) == (0, 1) and row.label_id == first.label_id
    assert row.settled_outcome is False and row.realized_pnl == Decimal("-0.43")
    assert unchanged.rows == ()


def test_window_incomplete_until_all_fills_settle() -> None:
    settled = _inp()
    blocker = _inp(coid="O-2", venue_order_id="vo-2", fee_reconciled=False)

    blocked = _label([settled, blocker], _rec(89), now_ns=_REL + _H)
    released = _label([settled, blocker], _rec(89), now_ns=_REL + (LABEL_LAG_MAX_H + 1) * _H)

    first = next(r for r in blocked.rows if r.client_order_id == "O-1")
    again = next(r for r in released.rows if r.client_order_id == "O-1")
    assert first.excluded_reason is ExcludedReason.WINDOW_INCOMPLETE and first.admissible is False
    assert first.settled_outcome is True and first.realized_pnl == Decimal("0.57")
    assert again.excluded_reason is None and again.admissible is True


def test_window_incomplete_older_than_48h_fails_label_lag() -> None:
    inside = _label([_inp()], None, now_ns=_REL + (WINDOW_INCOMPLETE_MAX_H - 1) * _H)
    past = _label([_inp()], None, now_ns=_REL + (WINDOW_INCOMPLETE_MAX_H + 1) * _H)

    assert _only(past).excluded_reason is ExcludedReason.WINDOW_INCOMPLETE
    assert inside.lag_breaches == ()
    assert [b.client_order_id for b in past.lag_breaches] == ["O-1"]


def test_fill_better_than_ask_persists_slippage_defect() -> None:
    row = _only(_label([_inp(cost="0.35")], _rec(89)))

    assert row.excluded_reason is ExcludedReason.SLIPPAGE_DEFECT and row.admissible is False
    assert row.slippage == Decimal("-0.05") and row.entry_ask == Decimal("0.4")


def test_fill_one_tick_better_than_ask_is_slippage_defect() -> None:
    result = _label([_inp(cost="0.39")], _rec(89))

    assert _only(result).excluded_reason is ExcludedReason.SLIPPAGE_DEFECT
    assert [(a.severity, a.code) for a in result.alerts] == [("WARN", "slippage_defect")]


def test_fill_at_ask_is_not_slippage_defect() -> None:
    row = _only(_label([_inp(cost="0.40")], _rec(89)))

    assert row.excluded_reason is None and row.slippage == Decimal(0)


# -- venue fallback --------------------------------------------------------------------------------

_DAYS = 24 * _H


def test_fallback_trigger_is_score_trial_basis() -> None:
    reading: dict[str, Any] = {"venue_settlement_tmax_f": 89}

    early = _only(_label([_inp(**reading)], None, now_ns=_REL + 7 * _DAYS - _H))
    no_reading = _only(_label([_inp()], None, now_ns=_REL + 7 * _DAYS))
    due = _only(_label([_inp(**reading)], None, now_ns=_REL + 7 * _DAYS))

    assert early.settled_outcome is None
    assert early.excluded_reason is ExcludedReason.WINDOW_INCOMPLETE
    assert no_reading.settled_outcome is None
    assert due.settlement_basis == "venue_last_fair_price_fallback"
    assert (due.settled_outcome, due.realized_pnl, due.excluded_reason) == (
        True,
        Decimal("0.57"),
        None,
    )


def test_fallback_basis_never_admissible() -> None:
    row = _only(_label([_inp(venue_settlement_tmax_f=89)], None, now_ns=_REL + 8 * _DAYS))

    assert row.settlement_basis == "venue_last_fair_price_fallback" and row.admissible is False
    assert is_final_row(row, now_ns=_REL + 8 * _DAYS, deadline_ns=_REL) is True


def test_fallback_pending_window_raises_label_lag_by_design() -> None:
    result = _label([_inp()], None, now_ns=_REL + 5 * _DAYS)

    assert [(b.client_order_id, b.cause) for b in result.lag_breaches] == [
        ("O-1", "awaiting_venue_fallback")
    ]


def test_an_unmapped_scorer_reason_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    real = real_score_trial

    def _weird(*args: Any, **kwargs: Any) -> Any:
        result = real(*args, **kwargs)
        assert isinstance(result, ScoredTrial)
        return replace(result, excluded_reason="something_new")

    monkeypatch.setattr(fq_scorer, "score_trial", _weird)

    with pytest.raises(UnmappedScorerReason):
        _label([_inp()], _rec(89))


def test_a_refusing_settlement_source_propagates() -> None:
    class _Refuses:
        def record(self, station: str, climate_day: dt.date) -> NwsClimateDay | None:
            raise SettlementSourceRefused("twc_reader_absent")

    scorer = ForecastQuantileLadderScorer(now_ns=_REL, prior=())
    with pytest.raises(SettlementSourceRefused):
        scorer.label(_DAY, [_inp()], _Refuses())


# -- canary, drill, pre-epoch ----------------------------------------------------------------------


def test_canary_and_drill_rows_never_admissible() -> None:
    canary = _only(_label([_inp(canary=True)], _rec(89)))
    drill = _only(_label([_inp(attribution=_attr(drill=True))], _rec(89)))

    assert (canary.excluded_reason, canary.admissible) == (ExcludedReason.CANARY, False)
    assert (drill.excluded_reason, drill.admissible) == (ExcludedReason.DRILL, False)


def test_pre_epoch_row_is_unattributed_with_artefact_p_and_per_fill_pnl() -> None:
    pre = PreEpochAttribution(storage_key=_FAMILY)
    bridge = BridgeMatch(p_at_decision=0.38, p_raw_at_decision=0.38, decision_now_ns=TS - 1)
    row = _only(_label([_inp(attribution=pre, bridge=bridge)], _rec(89)))
    unmatched = _only(_label([_inp(attribution=pre)], _rec(89)))

    assert row.family_id == _FAMILY and row.decision_id is None and row.admissible is False
    assert row.excluded_reason is ExcludedReason.UNATTRIBUTED
    assert row.p_source is PSource.ARTEFACT_RECOMPUTE and row.p_at_decision == pytest.approx(0.38)
    assert row.realized_pnl == Decimal("0.57")
    assert unmatched.p_source is PSource.NONE and unmatched.p_at_decision is None


def test_a_take_side_that_disagrees_with_the_fill_leg_is_critical_and_unreconciled() -> None:
    attribution = _attr(side="yes")
    result = _label([_inp(side="no", attribution=attribution)], _rec(95))

    row = _only(result)
    assert row.p_source is PSource.NONE and row.admissible is False and row.reconciled is False
    assert [(a.severity, a.code) for a in result.alerts] == [("CRITICAL", "side_leg_mismatch")]


def test_c1_alerts_pass_through_and_the_label_keeps_the_c1_family() -> None:
    attribution = replace(_attr(), alerts=("c1_fold_disagreement",))
    result = _label([_inp(attribution=attribution)], _rec(89))

    assert _only(result).family_id == _FAMILY
    assert ("CRITICAL", "c1_fold_disagreement") in [(a.severity, a.code) for a in result.alerts]


def test_metrics_count_null_p_and_non_c1_post_epoch_rows() -> None:
    pre = PreEpochAttribution(storage_key=_FAMILY)
    result = _label([_inp(attribution=pre), _inp(coid="O-2", venue_order_id="vo-2")], _rec(89))

    assert result.p_null_count == 1 and result.non_c1_post_epoch_count == 0


def test_label_id_is_the_pinned_digest_and_scorer_declares_legs_and_roles() -> None:
    import hashlib

    expected = hashlib.sha256(f"label/v1|{_FAMILY}|O-1|T-1|entry".encode()).hexdigest()[:32]

    assert label_id_of(_FAMILY, "O-1", "T-1", LabelRole.ENTRY) == expected
    assert (
        label_id_of(_FAMILY, "O-1", None, LabelRole.ENTRY)
        == hashlib.sha256(f"label/v1|{_FAMILY}|O-1||entry".encode()).hexdigest()[:32]
    )
    row = _only(_label([_inp()], _rec(89)))
    assert row.label_id == label_id_of(_FAMILY, "O-1", "T-1", LabelRole.ENTRY)
    assert row.scorer_id == FQ_SCORER_ID
    assert ForecastQuantileLadderScorer.legs == frozenset({"yes", "no"})
    assert ForecastQuantileLadderScorer.roles == frozenset({"entry", "exit"})
