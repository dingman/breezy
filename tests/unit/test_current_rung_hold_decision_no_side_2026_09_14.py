"""RED-first tests for the NO-side edge (S3, plan ``NO_SIDE_EDGE_2026-09-14.md``).

Mirror-image of ``test_current_rung_hold_decision.py``'s key YES cases,
using ``P_HOLD_UPPER`` on the SAME key and the bid ladder as the executable
floor. ``NO_ask = 1 - bid`` is the only inversion, and it must be exact at
0.01-tick prices (``Decimal`` only).

Also pins three existing YES fixtures' outputs BEFORE touching the module
(byte-identity guard for the shared ``evaluate_decision`` refactor) and
proves the executable gate rejects the measured p10 NO-side depth
(``0.1`` contracts, N2-11) against a 1-contract order without relaxing the
gate.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from decimal import Decimal

from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
from breezy.strategy.current_rung_hold.decision import (
    DecisionInputs,
    Refuse,
    Take,
    evaluate_decision,
)
from breezy.strategy.weather_common.running_extreme import RunningMax

_LADDER: tuple[tuple[int | None, int | None], ...] = ((None, 69), (70, 71), (72, None))

_STATION = "LAX"
_SEASON = "DJF"
_HOUR_LST = 12
_INTERIOR_WIDTH_CODE = 0
_M_ZERO = 0

#: ``(LAX, DJF, 12, 0, 0)`` -- ``P_HOLD_LOWER == 0.6585``, ``P_HOLD_UPPER ==
#: 0.7430`` (both read verbatim off ``archive_table.py``). NO estimand
#: ``p_miss_lower = 1 - 0.7430 == 0.2570``.
_P_HOLD_UPPER = Decimal("0.7430")
_P_MISS_LOWER = Decimal(1) - _P_HOLD_UPPER


def _exact_running_max(reading_f: int, *, source_observed_at_ns: int = 0) -> RunningMax:
    return RunningMax(
        lower_f=reading_f,
        upper_f=reading_f,
        exact_f=reading_f,
        source_observed_at_ns=source_observed_at_ns,
        source_received_at_ns=source_observed_at_ns,
    )


def _take_case_inputs(**overrides: object) -> DecisionInputs:
    """Same YES worked-example base as the YES test module (byte-for-byte)."""
    base = DecisionInputs(
        station=_STATION,
        climate_day=dt.date(2026, 1, 15),
        now_ns=1_000_000_000,
        ladder=_LADDER,
        fee_coefficient=Decimal("0.06"),
        ask=Decimal("0.40"),
        size=5,
        running_max=_exact_running_max(70),
        staleness_ns=0,
        config=CurrentRungHoldConfig(),
        season=_SEASON,
        hour_lst=_HOUR_LST,
        width_code=_INTERIOR_WIDTH_CODE,
        m_code=_M_ZERO,
        latch_consumed=False,
    )
    return dataclasses.replace(base, **overrides)  # type: ignore[arg-type]


def _no_case_inputs(**overrides: object) -> DecisionInputs:
    """A clean NO Take: ``bid=0.10`` -> ``NO_ask = 0.90``.

    ``0.06 * 0.90 * 0.10 == 0.0054`` -> banker's-rounded ``$0.01`` ->
    break-even ``0.91``. That is ABOVE ``p_miss_lower`` (``0.2570``), so a
    "clean Take" for NO instead needs a HIGH bid (cheap NO_ask). Use
    ``bid=0.75`` -> ``NO_ask=0.25``; fee ``0.06*0.25*0.75==0.01125`` ->
    ``$0.01`` -> break-even ``0.26``. ``p_miss_lower=0.2570 > 0.26`` is
    FALSE, so nudge the bid slightly higher: ``bid=0.78`` -> ``NO_ask=0.22``;
    fee ``0.06*0.22*0.78==0.010296`` -> ``$0.01`` -> break-even ``0.23``.
    ``0.2570 > 0.23`` -- clears.
    """
    base_overrides: dict[str, object] = {
        "side": "no",
        "bid": Decimal("0.78"),
        "bid_size": Decimal(5),
    }
    base_overrides.update(overrides)
    return dataclasses.replace(_take_case_inputs(), **base_overrides)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Byte-identity pin: three existing YES fixtures, unedited outputs, BEFORE
# any NO-side code runs on the same shared `evaluate_decision`.
# ---------------------------------------------------------------------------


def test_yes_worked_example_is_byte_identical_after_the_no_side_refactor() -> None:
    decision = evaluate_decision(_take_case_inputs())
    assert decision == Take(
        quantity=1,
        limit_price=Decimal("0.40"),
        p_hold_lower=Decimal("0.6585"),
        break_even=Decimal("0.41"),
        rung=(70, 71),
    )
    assert decision.side == "yes"
    assert decision.p_bound is None


def test_yes_consumed_trial_day_is_still_refused() -> None:
    assert evaluate_decision(_take_case_inputs(latch_consumed=True)) == Refuse(
        "trial_day_consumed"
    )


def test_yes_illegal_cell_is_still_refused() -> None:
    assert evaluate_decision(_take_case_inputs(width_code=2, m_code=0)) == Refuse(
        "illegal_cell"
    )


# ---------------------------------------------------------------------------
# NO-side mirror cases.
# ---------------------------------------------------------------------------


def test_a_clean_no_take_inverts_the_bid_and_reads_p_hold_upper() -> None:
    decision = evaluate_decision(_no_case_inputs())
    assert decision == Take(
        quantity=1,
        limit_price=Decimal("0.22"),
        p_hold_lower=_P_MISS_LOWER,
        break_even=Decimal("0.23"),
        rung=(70, 71),
        side="no",
        p_bound=_P_MISS_LOWER,
    )


def test_no_edge_below_break_even_is_refused() -> None:
    # bid=0.10 -> NO_ask=0.90, break_even~0.91, far above p_miss_lower=0.2570.
    decision = evaluate_decision(_no_case_inputs(bid=Decimal("0.10")))
    assert decision == Refuse("edge_below_break_even")


def test_no_missing_bid_is_not_executable() -> None:
    decision = evaluate_decision(_no_case_inputs(bid=None, bid_size=None))
    assert decision == Refuse("not_executable")


def test_no_cell_below_n_min_is_p_hold_undefined() -> None:
    # (LAX, DJF, 12, 1, 0) is a legal open-upper-tail cell absent from
    # P_HOLD_UPPER's DJF/12 rows in this test's key space -- reuse an
    # out-of-corpus hour instead, which both maps define as undefined.
    decision = evaluate_decision(_no_case_inputs(hour_lst=99))
    assert decision == Refuse("p_hold_undefined")


def test_no_illegal_cell_is_refused_before_the_no_side_gate() -> None:
    decision = evaluate_decision(_no_case_inputs(width_code=2, m_code=0))
    assert decision == Refuse("illegal_cell")


def test_no_non_current_rung_is_refused_observation_ambiguous() -> None:
    spanning = RunningMax(
        lower_f=69,
        upper_f=70,
        exact_f=69,
        source_observed_at_ns=0,
        source_received_at_ns=0,
    )
    decision = evaluate_decision(_no_case_inputs(running_max=spanning))
    assert decision == Refuse("observation_ambiguous")


def test_no_trial_day_consumed_is_refused_before_any_no_side_logic() -> None:
    decision = evaluate_decision(_no_case_inputs(latch_consumed=True))
    assert decision == Refuse("trial_day_consumed")


# ---------------------------------------------------------------------------
# N2-11: the executable gate compares the bid-ladder size against the order
# quantity in the SAME unit (contracts) -- never dollar notional -- so a
# 0.1-contract bid against a 1-contract order correctly refuses.
# ---------------------------------------------------------------------------


def test_n2_11_a_point_one_contract_bid_against_a_one_contract_order_is_not_executable() -> (
    None
):
    decision = evaluate_decision(_no_case_inputs(bid_size=Decimal("0.1")))
    assert decision == Refuse("not_executable")
    assert CurrentRungHoldConfig().order_quantity == 1
    assert CurrentRungHoldConfig().minimum_displayed_size == 1


def test_n2_11_a_bid_size_exactly_at_the_minimum_displayed_size_is_executable() -> None:
    decision = evaluate_decision(_no_case_inputs(bid_size=Decimal(1)))
    assert isinstance(decision, Take)


# ---------------------------------------------------------------------------
# Decimal inversion exactness at 0.01-tick prices.
# ---------------------------------------------------------------------------


def test_no_ask_inversion_is_exact_decimal_arithmetic_at_every_cent_tick() -> None:
    for cent in range(1, 100):
        bid = Decimal(cent) / Decimal(100)
        decision = evaluate_decision(_no_case_inputs(bid=bid))
        if isinstance(decision, Take):
            assert decision.limit_price == Decimal(1) - bid
            assert decision.limit_price.as_tuple().exponent >= -2
