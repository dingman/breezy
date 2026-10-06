"""AUT-2 r7 WP5 / section 3.6: position, settlement and cash legs.

The ledger side signs each fill by its leg BEFORE any compare (a NO holding is a short YES), the
venue side comes only from a ``venue_get`` snapshot, and every comparison is journalled once.
"""

from __future__ import annotations

import stat
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from breezy.analysis.labeling.constants import (
    INCONCLUSIVE_ALERT_DAYS,
    POSITION_SETTLE_GRACE_S,
    SNAPSHOT_MAX_AGE_MIN,
)
from breezy.analysis.labeling.fq_scorer import apply_prior
from breezy.analysis.labeling.legacy_crh_scorer import LEGACY_SCORER_ID
from breezy.analysis.labeling.reconcile import (
    CashSourceOverlap,
    CompareResult,
    ReconSource,
    SettlementEvidence,
    SlugCompare,
    StoredSnapshot,
    cash_leg_outcome,
    cash_records,
    daily_position_leg,
    fills_never_position_compared,
    governing_comparison,
    position_leg_for_family,
    read_position_compares,
    reconcile_labels,
    reconcile_positions,
    reconcile_settlement,
    streak_alert,
    write_position_compare,
)
from breezy.persistence.autonomy.label_schema import LabelRole, PSource
from breezy.persistence.autonomy.label_store import LabelRow
from breezy.persistence.autonomy.single_read import SingleReadReason, SingleReadRefused
from breezy.persistence.autonomy.verdict import VerdictOutcome
from breezy.runtime.venue_positions_read import PositionRow, ReadStatus, VenuePositionsRead
from tests.support.aut2_fixtures import durable_fill
from tests.unit.test_portfolio_roi_report import _prr

_S = 1_000_000_000
_H = 3_600 * _S
SNAP = 1_790_000_000 * _S
DEADLINE = SNAP + 10 * _H
SLUG_A = "tc-temp-laxhigh-2026-10-02-gte89lt90f"
SLUG_B = "tc-temp-sfohigh-2026-10-02-gte70lt71f"
A_YES = f"{SLUG_A}.POLYMARKET_US"
A_NO = f"{SLUG_A}^no.POLYMARKET_US"
B_YES = f"{SLUG_B}.POLYMARKET_US"


def _deadline(slug: str) -> int | None:
    return DEADLINE


def _fill(
    n: int = 1,
    *,
    instrument: str = A_YES,
    qty: str = "2",
    side: str = "BUY",
    age_s: int = 600,
    cost: str = "0.80",
    fee: str = "0.06",
) -> Any:
    return durable_fill(
        venue_order_id=f"vo-{n}",
        client_order_id=f"O-{n}",
        instrument_id=instrument,
        order_side=side,
        qty=Decimal(qty),
        cost=Decimal(cost),
        fee=Decimal(fee),
        ts_event=SNAP - age_s * _S,
    )


def _snap(
    rows: dict[str, str],
    *,
    complete: bool = True,
    status: ReadStatus = ReadStatus.OK,
    at: int = SNAP,
) -> VenuePositionsRead:
    return VenuePositionsRead(
        snapshot_ns=at,
        complete=complete,
        pages=1,
        read_status=status,
        rows=tuple(PositionRow(slug, Decimal(net), False) for slug, net in rows.items()),
    )


def _recon(snapshot: VenuePositionsRead | None, fills: list[Any], **kw: Any) -> Any:
    kw.setdefault("now_ns", SNAP + 60 * _S)
    kw.setdefault("deadline_ns", _deadline)
    return reconcile_positions(snapshot, fills, **kw)


def _results(leg: Any) -> dict[str, CompareResult]:
    return {c.base_slug: c.result for c in leg.compares}


# -- position leg -----------------------------------------------------------------------------


def test_position_leg_exact_equality_both_legs() -> None:
    both = _recon(
        _snap({SLUG_A: "2", SLUG_B: "-3"}),
        [_fill(1), _fill(2, instrument=f"{SLUG_B}^no.POLYMARKET_US", qty="3")],
    )
    off = _recon(_snap({SLUG_A: "2.0001"}), [_fill(1)])

    assert _results(both) == {SLUG_A: CompareResult.MATCH, SLUG_B: CompareResult.MATCH}
    assert both.outcome is VerdictOutcome.PASS
    assert off.outcome is VerdictOutcome.FAIL and off.mismatches == (SLUG_A,)


def test_no_leg_venue_short_yes_sign_applied_before_compare() -> None:
    no_fill = _fill(1, instrument=A_NO, qty="3")

    short = _recon(_snap({SLUG_A: "-3"}), [no_fill])
    wrong_sign = _recon(_snap({SLUG_A: "3"}), [no_fill])

    assert _results(short) == {SLUG_A: CompareResult.MATCH}
    assert _results(wrong_sign) == {SLUG_A: CompareResult.MISMATCH}
    assert next(iter(short.compares)).ledger_net_qty == Decimal(-3)


def test_compared_set_is_ledger_union_page() -> None:
    leg = _recon(_snap({SLUG_B: "1"}), [_fill(1)])

    assert set(_results(leg)) == {SLUG_A, SLUG_B}


def test_venue_slug_without_ledger_fill_fails() -> None:
    leg = _recon(_snap({SLUG_A: "2", SLUG_B: "1"}), [_fill(1)])

    assert leg.outcome is VerdictOutcome.FAIL and leg.venue_only_slugs == (SLUG_B,)
    assert [(a.severity, a.code, a.subject) for a in leg.alerts] == [
        ("CRITICAL", "venue_only_slug", SLUG_B)
    ]


def test_open_ledger_slug_missing_from_page_compares_as_zero() -> None:
    leg = _recon(_snap({}), [_fill(1)])

    only = leg.compares[0]
    assert only.result is CompareResult.MISMATCH and only.venue_net_qty == Decimal(0)


def test_settled_away_slug_not_compared() -> None:
    past = _recon(_snap({}), [_fill(1)], deadline_ns=lambda slug: SNAP - _H)

    assert _results(past) == {SLUG_A: CompareResult.SETTLED_AWAY}
    assert past.outcome is VerdictOutcome.PASS and past.slugs_compared == 0


def test_incomplete_snapshot_inconclusive() -> None:
    leg = _recon(_snap({SLUG_A: "2"}, complete=False), [_fill(1)])

    assert leg.outcome is VerdictOutcome.INCONCLUSIVE
    assert leg.inconclusive_causes == ("incomplete_snapshot",) and leg.compares == ()


@pytest.mark.parametrize("status", [ReadStatus.QUOTA_REFUSED, ReadStatus.READ_FAILED])
def test_quota_refusal_is_inconclusive_never_pass(status: ReadStatus) -> None:
    leg = _recon(_snap({}, complete=False, status=status), [_fill(1)])

    assert leg.outcome is VerdictOutcome.INCONCLUSIVE
    assert leg.inconclusive_causes == (status.value.lower(),)


def test_node_belief_alone_is_inconclusive() -> None:
    leg = _recon(_snap({SLUG_A: "2"}), [_fill(1)], source=ReconSource.NODE_BELIEF)

    assert leg.outcome is VerdictOutcome.INCONCLUSIVE and leg.compares == ()
    assert leg.inconclusive_causes == ("node_belief_only",)


def test_open_intent_at_snapshot_is_unknown_not_pass() -> None:
    leg = _recon(_snap({SLUG_A: "2"}), [_fill(1)], open_intent_slugs={SLUG_A})

    assert _results(leg) == {SLUG_A: CompareResult.NOT_COMPARED_INTENT}
    assert leg.outcome is VerdictOutcome.INCONCLUSIVE


def test_fills_after_snapshot_fenced_out() -> None:
    later = _fill(2, age_s=-5)  # five seconds AFTER the snapshot

    leg = _recon(_snap({SLUG_A: "2"}), [_fill(1), later])

    assert _results(leg) == {SLUG_A: CompareResult.MATCH}


def test_position_settle_grace_pinned() -> None:
    assert POSITION_SETTLE_GRACE_S == 60


def test_fill_inside_grace_not_compared() -> None:
    inside = _recon(_snap({SLUG_A: "2"}), [_fill(1, age_s=30)])
    on_edge = _recon(_snap({SLUG_A: "2"}), [_fill(1, age_s=POSITION_SETTLE_GRACE_S)])

    assert _results(inside) == {SLUG_A: CompareResult.NOT_COMPARED_GRACE}
    assert inside.not_compared_grace == 1 and inside.outcome is VerdictOutcome.PASS
    assert _results(on_edge) == {SLUG_A: CompareResult.MATCH}


def test_stale_snapshot_inconclusive_and_alerts() -> None:
    late = SNAP + (SNAPSHOT_MAX_AGE_MIN + 1) * 60 * _S

    leg = _recon(_snap({SLUG_A: "2"}), [_fill(1)], now_ns=late)

    assert leg.outcome is VerdictOutcome.INCONCLUSIVE
    assert leg.inconclusive_causes == ("stale_snapshot",)
    assert [(a.severity, a.code) for a in leg.alerts] == [("WARN", "stale_snapshot")]


def test_venue_only_slug_fails_every_family_on_venue() -> None:
    leg = _recon(_snap({SLUG_A: "2", SLUG_B: "5"}), [_fill(1)])

    fam_a = position_leg_for_family(leg, {SLUG_A})
    fam_other = position_leg_for_family(leg, {"tc-temp-miahigh-2026-10-02-gte80lt81f"})

    assert fam_a is VerdictOutcome.FAIL and fam_other is VerdictOutcome.FAIL


# -- the journal, the governing comparison and the labels -------------------------------------


def _stored(at: int, result: CompareResult, venue: str = "2", ledger: str = "2") -> StoredSnapshot:
    return StoredSnapshot(
        at, "intraday", (SlugCompare(SLUG_A, Decimal(venue), Decimal(ledger), result),)
    )


def _label(**over: Any) -> LabelRow:
    base: dict[str, Any] = {
        "label_id": "a" * 32,
        "decision_id": "d" * 64,
        "family_id": "pm_us_crh_fq_v1",
        "trial_id": "t",
        "client_order_id": "O-1",
        "trade_id": "T-1",
        "station": "LAX",
        "climate_day": "2026-10-02",
        "instrument_id": A_YES,
        "rung_id": "89_90",
        "leg": "yes",
        "role": LabelRole.ENTRY,
        "qty": Decimal(2),
        "fill_px": Decimal("0.40"),
        "entry_ask": Decimal("0.40"),
        "fee_reconciled": Decimal("0.06"),
        "slippage": Decimal(0),
        "p_at_decision": 0.6,
        "p_raw_at_decision": 0.6,
        "p_source": PSource.C1_DECISION,
        "settled_outcome": True,
        "settlement_tmax_f": Decimal(89),
        "settlement_basis": "nws_final",
        "realized_pnl": Decimal("1.14"),
        "counterfactual_hold_pnl": None,
        "reconciled": False,
        "reconciliation_delta": None,
        "reconciliation_source": "node_belief",
        "net_position_key": SLUG_A,
        "admissible": False,
        "excluded_reason": None,
        "labelled_at_ns": SNAP,
        "label_seq": 0,
        "scorer_id": "forecast_quantile_ladder/v1",
    }
    base.update(over)
    return LabelRow(**base)


def test_transient_mismatch_clears_on_next_snapshot() -> None:
    fills = [_fill(1)]
    k = SNAP
    k1 = SNAP + 30 * 60 * _S
    first = reconcile_labels(
        [_label()], [_stored(k, CompareResult.MISMATCH, venue="1")], fills, _deadline
    )
    seq_n = apply_prior(first, ())
    both = [_stored(k, CompareResult.MISMATCH, venue="1"), _stored(k1, CompareResult.MATCH)]
    second = apply_prior(reconcile_labels([_label()], both, fills, _deadline), seq_n)

    assert (seq_n[0].reconciled, seq_n[0].reconciliation_delta) == (False, Decimal(-1))
    assert len(second) == 1 and second[0].label_seq == 1
    assert (second[0].reconciled, second[0].reconciliation_delta) == (True, Decimal(0))
    assert second[0].reconciliation_source == "venue_get"
    leg = daily_position_leg(fills, both, _deadline, now_ns=k1 + _S)
    assert leg.outcome is VerdictOutcome.PASS and leg.position_mismatches_transient == 1


def test_standing_mismatch_fails_daily() -> None:
    snaps = [
        _stored(SNAP, CompareResult.MATCH),
        _stored(SNAP + _H, CompareResult.MISMATCH, venue="1"),
    ]

    leg = daily_position_leg([_fill(1)], snaps, _deadline, now_ns=SNAP + 2 * _H)

    assert leg.outcome is VerdictOutcome.FAIL and leg.standing_mismatches == (SLUG_A,)


def test_governing_comparison_reproducible_from_journal(tmp_path: Path) -> None:
    fills = [_fill(1)]
    snaps = [
        _stored(SNAP, CompareResult.MISMATCH, venue="1"),
        _stored(SNAP + _H, CompareResult.MATCH),
    ]
    for snap in snaps:
        write_position_compare(
            tmp_path, snap.snapshot_ns, snap.mode, list(snap.rows), snapshot_sha256="a" * 64
        )

    stored = read_position_compares(tmp_path)

    assert stored == tuple(snaps)
    assert governing_comparison(SLUG_A, stored, fills, _deadline) == governing_comparison(
        SLUG_A, snaps, fills, _deadline
    )
    assert governing_comparison(SLUG_A, stored, fills, _deadline) is not None


def test_per_snapshot_compare_results_written_once(tmp_path: Path) -> None:
    rows = list(_stored(SNAP, CompareResult.MATCH).rows)
    path = write_position_compare(tmp_path, SNAP, "intraday", rows, snapshot_sha256="a" * 64)

    again = write_position_compare(tmp_path, SNAP, "intraday", rows, snapshot_sha256="a" * 64)
    other = [replace(rows[0], result=CompareResult.MISMATCH)]
    with pytest.raises(SingleReadRefused) as caught:
        write_position_compare(tmp_path, SNAP, "intraday", other, snapshot_sha256="a" * 64)

    assert again == path and caught.value.reason is SingleReadReason.EXISTS_DIFFERENT
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert "evidence/aut2/position_compare/" in path.as_posix()


def test_every_fill_position_compared_before_settlement_else_fail() -> None:
    past = SNAP + 11 * _H  # after the deadline, nothing governing was ever journalled
    snaps = [_stored(SNAP - _H, CompareResult.MATCH)]  # taken before the fill settled

    leg = daily_position_leg([_fill(1, age_s=0)], snaps, _deadline, now_ns=past)

    assert leg.fills_never_position_compared == 1 and leg.outcome is VerdictOutcome.FAIL


def test_comparison_before_fill_does_not_reconcile_label() -> None:
    t = SNAP
    fill = durable_fill(
        venue_order_id="vo-1",
        client_order_id="O-1",
        instrument_id=A_YES,
        qty=Decimal(2),
        ts_event=t + _S,
    )

    rows = reconcile_labels([_label()], [_stored(t, CompareResult.MATCH)], [fill], _deadline)

    assert rows[0].reconciled is False and rows[0].reconciliation_delta is None
    assert rows[0].reconciliation_source == "node_belief"
    after = fills_never_position_compared(
        [fill], [_stored(t, CompareResult.MATCH)], _deadline, now_ns=DEADLINE + _S
    )
    assert after == 1


def test_fills_never_position_compared_counts_only_past_deadline() -> None:
    fill = _fill(1, age_s=0)

    before = fills_never_position_compared([fill], [], _deadline, now_ns=DEADLINE - _S)
    after = fills_never_position_compared([fill], [], _deadline, now_ns=DEADLINE + _S)

    assert (before, after) == (0, 1)


def test_two_consecutive_inconclusive_days_alert_critical() -> None:
    assert INCONCLUSIVE_ALERT_DAYS == 2
    assert streak_alert(["INCONCLUSIVE", "INCONCLUSIVE", "PASS"], "INCONCLUSIVE") is True
    assert streak_alert(["INCONCLUSIVE", "PASS", "INCONCLUSIVE"], "INCONCLUSIVE") is False
    assert streak_alert(["INCONCLUSIVE"], "INCONCLUSIVE") is False


def test_two_consecutive_balance_unknown_days_alert_critical() -> None:
    assert streak_alert(["BALANCE_UNKNOWN", "BALANCE_UNKNOWN"], "BALANCE_UNKNOWN") is True
    assert streak_alert(["BALANCE_UNKNOWN", "OK"], "BALANCE_UNKNOWN") is False


# -- settlement leg ---------------------------------------------------------------------------


def test_settlement_disagreement_unreconciles_and_never_adopts_venue() -> None:
    row = _label(reconciled=True, settled_outcome=True)

    leg = reconcile_settlement([row], {SLUG_A: SettlementEvidence(venue_yes_resolved=False)})

    assert leg.outcome is VerdictOutcome.FAIL and leg.mismatches == 1
    assert leg.rows[0].reconciled is False and leg.rows[0].settled_outcome is True
    assert [(a.severity, a.code) for a in leg.alerts] == [
        ("CRITICAL", "settlement_source_disagreement")
    ]


def test_no_leg_settlement_compare_inverts() -> None:
    no_win = _label(leg="no", settled_outcome=True, reconciled=True)

    agrees = reconcile_settlement([no_win], {SLUG_A: SettlementEvidence(venue_yes_resolved=False)})
    uninverted = reconcile_settlement(
        [no_win], {SLUG_A: SettlementEvidence(venue_yes_resolved=True)}
    )

    assert agrees.outcome is VerdictOutcome.PASS and agrees.rows[0].reconciled is True
    assert uninverted.outcome is VerdictOutcome.FAIL


def test_pending_settlement_leg_is_inconclusive_not_pass() -> None:
    leg = reconcile_settlement([_label()], {})
    unknown = reconcile_settlement([_label()], {SLUG_A: SettlementEvidence(None)})

    assert leg.outcome is VerdictOutcome.INCONCLUSIVE and leg.pending == 1
    assert unknown.outcome is VerdictOutcome.INCONCLUSIVE


def test_fallback_pending_settlement_leg_is_inconclusive() -> None:
    pending = _label(settled_outcome=None, settlement_basis=None, realized_pnl=None)

    leg = reconcile_settlement([pending], {SLUG_A: SettlementEvidence(True)})

    assert leg.outcome is VerdictOutcome.INCONCLUSIVE


def test_missing_venue_evidence_overdue_is_fail() -> None:
    leg = reconcile_settlement([_label()], {SLUG_A: SettlementEvidence(None, overdue=True)})

    assert leg.outcome is VerdictOutcome.FAIL


# -- cash leg -----------------------------------------------------------------------------------


_D0 = "2026-10-02"
_D1 = "2026-10-03"


def _ts(day: str, hour: int) -> int:
    import datetime as dt

    moment = dt.datetime.fromisoformat(f"{day}T{hour:02d}:00:00").replace(tzinfo=dt.UTC)
    return int(moment.timestamp()) * _S


_SETTLE_AT = _ts(_D1, 6)


def _cash_fill(
    name: str,
    *,
    instrument: str = A_YES,
    side: str = "BUY",
    day: str = _D0,
    hour: int = 12,
    qty: str = "1",
    cost: str = "0.40",
    fee: str = "0.03",
) -> Any:
    return durable_fill(
        venue_order_id=f"vo-{name}",
        client_order_id=f"O-{name}",
        instrument_id=instrument,
        order_side=side,
        qty=Decimal(qty),
        cost=Decimal(cost),
        fee=Decimal(fee),
        ts_event=_ts(day, hour),
    )


def _cash_row(name: str, fill: Any, **over: Any) -> LabelRow:
    fields: dict[str, Any] = {
        "client_order_id": f"O-{name}",
        "label_id": name.ljust(32, "0"),
        "instrument_id": fill.instrument_id,
        "realized_pnl": fill.cumulative_qty - fill.cumulative_cost - fill.cumulative_fee,
        "qty": fill.cumulative_qty,
    }
    fields.update(over)
    return _label(**fields)


def _slug_deadline(slug: str) -> int | None:
    return _SETTLE_AT


def _residual(rec: Any) -> Any:
    return _prr.ResidualSettlement(
        trial_id=rec.trial_id,
        climate_day=rec.climate_day,
        payout=rec.payout,
        dated_at_ns=rec.dated_at_ns,
        settlement_basis=rec.settlement_basis,
        realised_pnl=rec.realised_pnl,
    )


def _mixed_day(perturb: Decimal = Decimal(0)) -> tuple[Any, ...]:
    """A held-to-settlement fill and an exited fill opened on D0, an open fill opened on D1."""
    settled = _cash_fill("A", day=_D0, instrument=A_YES)
    exited = _cash_fill("C", day=_D0, instrument=B_YES, cost="0.50", fee="0.03")
    sold = _cash_fill("S", day=_D1, hour=13, instrument=B_YES, side="SELL", cost="0.60", fee="0.02")
    still_open = _cash_fill(
        "B",
        day=_D1,
        hour=12,
        instrument="tc-temp-miahigh-2026-10-04-gte80lt81f.POLYMARKET_US",
        cost="0.30",
        fee="0.02",
    )
    rows = [
        _cash_row("A", settled, realized_pnl=Decimal("0.57") + perturb, net_position_key=SLUG_A),
        _cash_row(
            "S",
            sold,
            role=LabelRole.EXIT,
            realized_pnl=None,
            net_position_key=SLUG_B,
            instrument_id=B_YES,
            settled_outcome=None,
        ),
    ]
    return settled, exited, sold, still_open, rows


def _cash_leg(perturb: Decimal = Decimal(0), *, extra: tuple[Any, ...] = ()) -> Any:
    settled, exited, sold, still_open, rows = _mixed_day(perturb)
    fills = [settled, exited, sold, still_open]
    produced = cash_records(
        rows,
        fills,
        legacy_fill_keys=set(),
        deadline_ns=_slug_deadline,
        netting_ns=lambda slug: None,
    )
    capital_d1 = _prr.capital_deployed_for_fill(still_open)
    proceeds = Decimal("1.00") + Decimal("0.58")  # A pays 1, the exit nets 0.60 - 0.02
    balances = {_D0: Decimal("100.00"), _D1: Decimal("100.00") - capital_d1 + proceeds}
    daily = _prr.reconcile_daily(
        fills=fills,
        scored_trials=list(extra),
        daily_balances=balances,
        residual_settlements=[_residual(r) for r in produced.records],
    )
    return produced, _prr.cumulative_reconciliation(daily_rows=daily, settled_through=_D1), daily


def test_cash_leg_mixed_day_open_settled_exit() -> None:
    produced, cumulative, _ = _cash_leg()
    perturbed, bad, _ = _cash_leg(Decimal("0.02"))

    kinds = sorted(r.kind for r in produced.records)
    assert kinds == ["exit_proceeds", "settlement_payout"]
    assert cumulative.settled_cumulative_passes_net is True
    assert (
        cash_leg_outcome(
            settled_cumulative_passes_net=cumulative.settled_cumulative_passes_net,
            n_balance_unknown_days=cumulative.n_balance_unknown_days,
            external_flow_evidence_status="OK",
        )
        is VerdictOutcome.PASS
    )
    assert bad.settled_cumulative_passes_net is False
    assert (
        cash_leg_outcome(
            settled_cumulative_passes_net=bad.settled_cumulative_passes_net,
            n_balance_unknown_days=0,
            external_flow_evidence_status="OK",
        )
        is VerdictOutcome.FAIL
    )
    assert perturbed.records != produced.records


def test_cash_tolerance_counts_fills_opened_not_settled() -> None:
    _, _, daily = _cash_leg()

    day1 = next(r for r in daily if r.day == _D1)
    assert day1.tolerance == Decimal("0.01")  # one fill OPENED on D1; two cash events settle there


def test_balance_unknown_day_inconclusive() -> None:
    out = cash_leg_outcome(
        settled_cumulative_passes_net=True,
        n_balance_unknown_days=1,
        external_flow_evidence_status="OK",
    )
    flows = cash_leg_outcome(
        settled_cumulative_passes_net=True,
        n_balance_unknown_days=0,
        external_flow_evidence_status="NOT_CONFIGURED",
    )

    assert out is VerdictOutcome.INCONCLUSIVE and flows is VerdictOutcome.INCONCLUSIVE


def test_yes_and_no_same_rung_cash_timing() -> None:
    yes = _cash_fill("Y", instrument=A_YES, cost="0.40", fee="0.03")
    no = _cash_fill("N", instrument=A_NO, cost="0.55", fee="0.03")
    rows = [
        _cash_row("Y", yes, net_position_key=SLUG_A, leg="yes", settled_outcome=True),
        _cash_row(
            "N", no, net_position_key=SLUG_A, leg="no", settled_outcome=False, instrument_id=A_NO
        ),
    ]
    netting_at = _ts(_D0, 15)

    known = cash_records(
        rows,
        [yes, no],
        legacy_fill_keys=set(),
        deadline_ns=_slug_deadline,
        netting_ns=lambda slug: netting_at,
    )
    unknown = cash_records(
        rows,
        [yes, no],
        legacy_fill_keys=set(),
        deadline_ns=_slug_deadline,
        netting_ns=lambda slug: None,
    )

    assert [(r.kind, r.payout, r.dated_at_ns) for r in known.records] == [
        ("netting_offset", Decimal(1), netting_at)
    ]
    assert known.unknown_netting_slugs == ()
    assert unknown.records == () and unknown.unknown_netting_slugs == (SLUG_A,)
    assert (
        cash_leg_outcome(
            settled_cumulative_passes_net=True,
            n_balance_unknown_days=0,
            external_flow_evidence_status="OK",
            unknown_netting_slugs=unknown.unknown_netting_slugs,
        )
        is VerdictOutcome.INCONCLUSIVE
    )


def test_cash_leg_unions_legacy_proceeds_and_capital() -> None:
    legacy_fill = _cash_fill("L", day=_D1, hour=12, instrument=B_YES, cost="0.40", fee="0.03")
    legacy_trial = _prr_trial("legacy-1", scored_at_ns=_ts(_D1, 7))
    produced, cumulative, daily = _cash_leg_with_legacy(legacy_fill, legacy_trial)

    assert cumulative.settled_cumulative_passes_net is True
    assert {r.kind for r in produced.records} == {"exit_proceeds", "settlement_payout"}
    day1 = next(r for r in daily if r.day == _D1)
    assert day1.proceeds == Decimal("1.00") + Decimal("0.58") + _prr.settlement_payout(legacy_trial)


def _prr_trial(trial_id: str, *, scored_at_ns: int) -> Any:
    from breezy.settlement.trial_scorer import ScoredTrial

    return ScoredTrial(
        trial_id=trial_id,
        station="SFO",
        climate_day=_D0,
        instrument_id=B_YES,
        settlement_tmax_f=70,
        held=True,
        pnl=Decimal("0.57"),
        revision_seq=1,
        raw_sha256="a" * 64,
        scored_at_ns=scored_at_ns,
        score_seq=1,
        settlement_basis="nws_final",
        excluded_reason=None,
        slippage=Decimal(0),
        entry_ask=Decimal("0.40"),
        fill_px=Decimal("0.40"),
        fee=Decimal("0.03"),
    )


def _cash_leg_with_legacy(legacy_fill: Any, legacy_trial: Any) -> tuple[Any, Any, Any]:
    settled, exited, sold, still_open, rows = _mixed_day()
    fills = [settled, exited, sold, still_open, legacy_fill]
    produced = cash_records(
        rows,
        fills,
        legacy_fill_keys={legacy_fill.venue_order_id},
        deadline_ns=_slug_deadline,
        netting_ns=lambda slug: None,
    )
    capital = _prr.capital_deployed_for_fill(still_open) + _prr.capital_deployed_for_fill(
        legacy_fill
    )
    proceeds = Decimal("1.58") + _prr.settlement_payout(legacy_trial)
    balances = {_D0: Decimal("100.00"), _D1: Decimal("100.00") - capital + proceeds}
    daily = _prr.reconcile_daily(
        fills=fills,
        scored_trials=[legacy_trial],
        daily_balances=balances,
        residual_settlements=[_residual(r) for r in produced.records],
    )
    return produced, _prr.cumulative_reconciliation(daily_rows=daily, settled_through=_D1), daily


def test_fill_in_both_sources_refused() -> None:
    fill = _cash_fill("A")
    row = _cash_row("A", fill, net_position_key=SLUG_A)

    with pytest.raises(CashSourceOverlap):
        cash_records(
            [row],
            [fill],
            legacy_fill_keys={fill.venue_order_id},
            deadline_ns=_slug_deadline,
            netting_ns=lambda slug: None,
        )


def test_exit_proceeds_enter_cash_at_sell_ts_event() -> None:
    sold = _cash_fill("S", day=_D1, hour=13, side="SELL", cost="0.60", fee="0.02")
    row = _cash_row("S", sold, role=LabelRole.EXIT, realized_pnl=None, settled_outcome=None)

    produced = cash_records(
        [row],
        [sold],
        legacy_fill_keys=set(),
        deadline_ns=_slug_deadline,
        netting_ns=lambda slug: None,
    )

    only = produced.records[0]
    assert (only.kind, only.payout, only.dated_at_ns) == (
        "exit_proceeds",
        Decimal("0.58"),
        sold.ts_event,
    )


def test_legacy_rows_emit_no_cash_record() -> None:
    fill = _cash_fill("L")
    row = _cash_row("L", fill, scorer_id=LEGACY_SCORER_ID, net_position_key=SLUG_A)

    produced = cash_records(
        [row],
        [fill],
        legacy_fill_keys={fill.venue_order_id},
        deadline_ns=_slug_deadline,
        netting_ns=lambda slug: None,
    )

    assert produced.records == ()


def test_legacy_crh_sell_proceeds_reach_cash_leg() -> None:
    # the legacy cash source excludes SELLs, so the SELL's key is not a legacy key: its proceeds
    # come from the durable record, never from the null realized_pnl
    buy = _cash_fill("L", day=_D0)
    sell = _cash_fill("LS", day=_D1, hour=13, side="SELL", cost="0.55", fee="0.02")
    row = _cash_row(
        "LS",
        sell,
        scorer_id=LEGACY_SCORER_ID,
        role=LabelRole.EXIT,
        realized_pnl=None,
        settled_outcome=None,
    )

    produced = cash_records(
        [row],
        [buy, sell],
        legacy_fill_keys={buy.venue_order_id},
        deadline_ns=_slug_deadline,
        netting_ns=lambda slug: None,
    )

    assert [(r.kind, r.payout, r.dated_at_ns) for r in produced.records] == [
        ("exit_proceeds", Decimal("0.53"), sell.ts_event)
    ]
