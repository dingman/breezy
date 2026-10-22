"""Pure pieces of the P2 NBP-vs-ask study. Thresholds are the r2.1 pre-registration.

The identity check, the null (p = ask ⇒ D_res exactly 0), the fee-by-date cash
rounding, and the 10-minute book rule. No tape and no NBP partition is read.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from scripts.analysis.p2_nbp_ask_murphy import (
    TEN_MINUTES_NS,
    BookSnapshot,
    IdentityError,
    assert_brier_identity,
    assert_null_dres,
    cash_taker_fee_usd,
    d_res,
    first_snapshot_in_window,
    gate_instant_ns,
    verdict,
    yes_taker_pnl_usd,
)

_NS = 1_000_000_000


def _ns(stamp: str) -> int:
    parsed = dt.datetime.fromisoformat(stamp)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return int(parsed.timestamp()) * _NS


def test_gate_instant_is_1650z_on_lst_date_d_minus_1() -> None:
    assert gate_instant_ns(dt.date(2026, 10, 5)) == _ns("2026-10-04T16:50:00+00:00")


def test_brier_identity_accepts_a_real_decomposition_and_rejects_a_gap() -> None:
    from breezy.analysis.brier_decomposition import (
        MurphyDecomposition,
        bin_by_edges,
        murphy_decomposition,
    )
    from breezy.analysis.nbp_calibration import RELIABILITY_BUCKET_EDGES

    probs = [0.05, 0.15, 0.42, 0.73, 0.91, 1.0]
    outcomes = [False, False, True, True, False, True]
    decomp = murphy_decomposition(probs, outcomes, bin_by_edges(RELIABILITY_BUCKET_EDGES))
    assert_brier_identity(decomp)

    broken = MurphyDecomposition(
        reliability=0.0,
        resolution=0.0,
        uncertainty=0.0,
        brier=1.0,
        within_bin_forecast_variance=0.0,
        within_bin_covariance=0.0,
    )
    with pytest.raises(IdentityError):
        assert_brier_identity(broken)


def test_null_p_equals_ask_gives_dres_exactly_zero() -> None:
    asks = [0.05, 0.15, 0.42, 0.73, 0.91]
    outcomes = [False, True, False, True, True]
    assert d_res(asks, asks, outcomes) == 0.0
    assert_null_dres(asks, outcomes)


def test_cash_fee_follows_the_dated_schedule_and_rounds_half_even_to_the_cent() -> None:
    pre = _ns("2026-09-16T16:50:00+00:00")
    ambiguous_open = _ns("2026-09-17T00:00:00+00:00")
    gate_on_drift_day = _ns("2026-09-17T16:50:00+00:00")
    post_open = _ns("2026-09-17T17:00:00+00:00")
    one_ns_before_post = post_open - 1

    # 0.06 * 0.50 * 0.50 = 0.015 exactly, halfway, half-even → 0.02 (cent digit 1 is odd).
    assert cash_taker_fee_usd(Decimal("0.50"), pre) == Decimal("0.02")
    # 0.06 * 0.40 * 0.60 = 0.0144 → 0.01.
    assert cash_taker_fee_usd(Decimal("0.40"), pre) == Decimal("0.01")
    assert cash_taker_fee_usd(Decimal("0.50"), ambiguous_open) is None
    assert cash_taker_fee_usd(Decimal("0.50"), gate_on_drift_day) is None
    assert cash_taker_fee_usd(Decimal("0.50"), one_ns_before_post) is None
    # 0.0695 * 0.45 * 0.55 = 0.01720125 → 0.02. The pre-drift 0.06 would round to 0.01.
    assert cash_taker_fee_usd(Decimal("0.45"), post_open) == Decimal("0.02")
    assert yes_taker_pnl_usd(outcome=1, ask=Decimal("0.45"), ts_event_ns=post_open) == Decimal(
        "0.53"
    )
    assert yes_taker_pnl_usd(outcome=0, ask=Decimal("0.50"), ts_event_ns=gate_on_drift_day) is None


def test_book_rule_keeps_the_first_snapshot_inside_a_closed_ten_minute_window() -> None:
    gate = _ns("2026-10-04T16:50:00+00:00")
    early = BookSnapshot(ts_ns=gate - 1, ask=0.10)
    at_gate = BookSnapshot(ts_ns=gate, ask=0.20)
    later = BookSnapshot(ts_ns=gate + 5 * 60 * _NS, ask=0.30)
    at_end = BookSnapshot(ts_ns=gate + TEN_MINUTES_NS, ask=0.40)
    past = BookSnapshot(ts_ns=gate + TEN_MINUTES_NS + 1, ask=0.50)

    assert first_snapshot_in_window([later, early, at_gate], gate) == at_gate
    assert first_snapshot_in_window([past, at_end], gate) == at_end
    assert first_snapshot_in_window([early, past], gate) is None
    assert first_snapshot_in_window([], gate) is None


def test_verdict_follows_the_r21_table_with_pass_first() -> None:
    assert (
        verdict(
            dres_evaluable=True, dres_lb=0.005, pnl_evaluable=False, pnl_lb=0.0, pnl_ub=0.0
        )
        == "PASS"
    )
    assert (
        verdict(
            dres_evaluable=False, dres_lb=0.0, pnl_evaluable=True, pnl_lb=0.01, pnl_ub=0.02
        )
        == "PASS"
    )
    # D_res can clear PASS while YES P&L clears FAIL. PASS is the first row.
    assert (
        verdict(
            dres_evaluable=True, dres_lb=0.005, pnl_evaluable=True, pnl_lb=-0.04, pnl_ub=-0.01
        )
        == "PASS"
    )
    assert (
        verdict(
            dres_evaluable=True, dres_lb=-0.02, pnl_evaluable=True, pnl_lb=-0.04, pnl_ub=-0.01
        )
        == "FAIL"
    )
    assert (
        verdict(
            dres_evaluable=True, dres_lb=-0.02, pnl_evaluable=True, pnl_lb=-0.04, pnl_ub=0.0
        )
        == "INCONCLUSIVE"
    )
    assert (
        verdict(
            dres_evaluable=True, dres_lb=0.004, pnl_evaluable=True, pnl_lb=0.0, pnl_ub=0.02
        )
        == "INCONCLUSIVE"
    )
    assert (
        verdict(
            dres_evaluable=False, dres_lb=0.0, pnl_evaluable=False, pnl_lb=-1.0, pnl_ub=-1.0
        )
        == "INCONCLUSIVE"
    )
