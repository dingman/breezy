"""RED-first pure core for the FQ loss-stop floor (F5-pin-request r3 §4.10).

Covers r3's pure-core list, the r2 rows it names (L-40 formulas, the
YES-first shrink and its refusal, the NO instrument price, fee refusal,
exits and voids), and the step-2 additions: variance-epsilon, the BE̅ guard,
per-contract exit v, shrink drift, Σ_NO q > 1, shrunk variance against
an independent enumeration, and feasible variance equal to
``combine_station_day``.
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Literal

import pytest

from breezy.analysis.fq_loss_stop_core import (
    ALPHA_FLOOR_GRID,
    G3_FLOOR_MULTIPLIER,
    T_MIN_GRID,
    VARIANCE_EPS,
    BundleLeg,
    BuyFill,
    ClockStep,
    ExitFill,
    FqLossStopRefusal,
    LegSettlement,
    NettingShift,
    NormalisedDay,
    ReasonCode,
    ShrunkJoint,
    bundle_variance,
    first_crossing,
    normalise_station_day,
    per_contract_exit_v,
    shrunk_joint,
    step_clock,
)
from breezy.settlement.current_rung_hold_v2 import (
    StationDayAdmissionRefusal,
    StratumRow,
    combine_station_day,
)

Side = Literal["yes", "no"]
_STATION = "MIA"


def _buy(
    rung: str,
    side: Side,
    qty: str,
    cost: str,
    fee: str | None = "0",
    *,
    reconciled: bool = True,
) -> BuyFill:
    return BuyFill(
        rung=rung,
        side=side,
        qty=Decimal(qty),
        cost=Decimal(cost),
        fee=None if fee is None else Decimal(fee),
        fee_reconciled=reconciled,
    )


def _settle(rung: str, side: Side, *, held: bool, voided: bool = False) -> LegSettlement:
    return LegSettlement(rung=rung, side=side, held=held, voided=voided)


def _day(
    buys: tuple[BuyFill, ...],
    settlements: tuple[LegSettlement, ...],
    exits: tuple[ExitFill, ...] = (),
    unknown: tuple[str, ...] = (),
) -> NormalisedDay:
    return normalise_station_day(
        station=_STATION,
        buys=buys,
        settlements=settlements,
        exits=exits,
        unknown_netting_slugs=unknown,
    )


def _bare(*, variance: float, x_rand: float = 0.0, shift: float = 0.0) -> NormalisedDay:
    return NormalisedDay(
        station=_STATION,
        legs=(),
        shifts=(),
        rows=(),
        x_rand=x_rand,
        shift=shift,
        variance=variance,
    )


def test_pinned_constants_match_the_r3_grids() -> None:
    assert ALPHA_FLOOR_GRID == (0.10, 0.20, 0.30)
    assert G3_FLOOR_MULTIPLIER == 2.5
    assert T_MIN_GRID == (1, 2, 3, 5)
    assert isinstance(VARIANCE_EPS, float)
    assert VARIANCE_EPS > 0.0


def test_reason_codes_are_a_closed_set() -> None:
    assert tuple(ReasonCode) == (
        ReasonCode.BE_OUT_OF_RANGE,
        ReasonCode.FEE_UNRECONCILED,
        ReasonCode.MISSING_FEE,
        ReasonCode.UNKNOWN_NETTING,
        ReasonCode.SIGMA_NO_EXCEEDS_ONE,
        ReasonCode.NEGATIVE_VARIANCE,
        ReasonCode.INVALID_EXIT_FILL,
        ReasonCode.MISSING_SETTLEMENT,
        ReasonCode.ADMISSION_REFUSED,
        ReasonCode.ZERO_VARIANCE_REALISED,
    )


def test_paired_rung_enters_x_as_zero_variance_shift() -> None:
    day = _day(
        (
            _buy("pair", "yes", "2", "0.80"),
            _buy("pair", "no", "2", "1.40"),
            _buy("open", "yes", "1", "0.25"),
        ),
        (
            _settle("pair", "yes", held=False),
            _settle("pair", "no", held=True),
            _settle("open", "yes", held=False),
        ),
    )
    assert day.shifts == (NettingShift(rung="pair", delta_net=Decimal("-0.10")),)
    assert day.shift == pytest.approx(-0.10)
    assert len(day.rows) == 1
    assert day.rows[0].rung == "open"
    assert day.x_rand == pytest.approx(-0.25)
    unpaired = combine_station_day(day.rows)
    assert day.variance == pytest.approx(unpaired.variance)
    assert day.variance == pytest.approx(0.25 * 0.75)
    # The pair pays 1 - BE_y - BE_n whatever the venue says. Flipping its
    # held flags must not move x or σ.
    flipped = _day(
        (
            _buy("pair", "yes", "2", "0.80"),
            _buy("pair", "no", "2", "1.40"),
            _buy("open", "yes", "1", "0.25"),
        ),
        (
            _settle("pair", "yes", held=True),
            _settle("pair", "no", held=False),
            _settle("open", "yes", held=False),
        ),
    )
    assert flipped.x_rand == pytest.approx(day.x_rand)
    assert flipped.shift == pytest.approx(day.shift)
    assert flipped.variance == pytest.approx(day.variance)


def test_same_rung_yes_no_nets_out_as_deterministic() -> None:
    """r2: a same-rung YES+NO pair is the null's own constant, not a draw."""
    held_flags: tuple[tuple[bool, bool], ...] = (
        (False, False),
        (True, False),
        (False, True),
        (True, True),
    )
    shifts = [
        _day(
            (_buy("r", "yes", "1", "0.40"), _buy("r", "no", "1", "0.70")),
            (_settle("r", "yes", held=yes), _settle("r", "no", held=no)),
        ).shift
        for yes, no in held_flags
    ]
    assert shifts == pytest.approx([-0.10, -0.10, -0.10, -0.10])
    assert _day(
        (_buy("r", "yes", "1", "0.40"), _buy("r", "no", "1", "0.70")),
        (_settle("r", "yes", held=True), _settle("r", "no", held=False)),
    ).variance == pytest.approx(0.0)


def test_pairs_only_day_is_not_a_tick_and_carries() -> None:
    pair = _day(
        (_buy("r", "yes", "1", "0.40"), _buy("r", "no", "1", "0.70")),
        (_settle("r", "yes", held=False), _settle("r", "no", held=True)),
    )
    nxt = _day((_buy("open", "yes", "1", "0.25"),), (_settle("open", "yes", held=False),))
    first: ClockStep = step_clock(pair, 0.0)
    assert first.is_tick is False
    assert first.z is None
    assert first.carry_out == pytest.approx(-0.10)
    second = step_clock(nxt, first.carry_out)
    sigma = math.sqrt(nxt.variance)
    x = nxt.x_rand + nxt.shift + first.carry_out
    assert second.is_tick is True
    assert second.z == pytest.approx(x / sigma)
    assert second.carry_out == 0.0
    # The reset carry does not revive on the next zero-σ day.
    third = step_clock(pair, second.carry_out)
    assert third.is_tick is False
    assert third.carry_out == pytest.approx(-0.10)


def test_unknown_netting_slug_refuses() -> None:
    with pytest.raises(FqLossStopRefusal) as exc:
        _day(
            (_buy("r", "yes", "1", "0.40"),),
            (_settle("r", "yes", held=False),),
            unknown=("slug-a",),
        )
    assert exc.value.reason is ReasonCode.UNKNOWN_NETTING


def test_one_row_per_rung_side_qty1_ledger_be() -> None:
    """A 5-contract leg and a 1-contract leg with the same BE̅ match (D3)."""
    five = _day(
        (_buy("a", "yes", "5", "1.50", "0.10"),),
        (_settle("a", "yes", held=True),),
    )
    one = _day(
        (_buy("b", "yes", "1", "0.30", "0.02"),),
        (_settle("b", "yes", held=True),),
    )
    assert five.rows[0].entry_ask == Decimal("0.32")
    assert five.rows[0].fee == Decimal(0)
    assert five.rows[0].qty == Decimal(1)
    assert one.rows[0].entry_ask == Decimal("0.32")
    assert five.x_rand == one.x_rand
    assert five.variance == one.variance
    assert five.x_rand == pytest.approx(1.0 - 0.32)


def test_multi_fill_leg_never_hits_fold_refusal() -> None:
    day = _day(
        (_buy("r", "yes", "1", "0.20"), _buy("r", "yes", "1", "0.40", "0.02")),
        (_settle("r", "yes", held=False),),
    )
    assert len(day.rows) == 1
    assert day.rows[0].entry_ask == Decimal("0.31")
    assert day.rows[0].qty == Decimal(1)
    assert day.rows[0].fee == Decimal(0)
    with pytest.raises(StationDayAdmissionRefusal):
        combine_station_day(
            (
                StratumRow(
                    entry_ask=Decimal("0.20"),
                    fee=Decimal(0),
                    held=False,
                    station=_STATION,
                    qty=Decimal(1),
                    side="yes",
                    rung="r",
                ),
                StratumRow(
                    entry_ask=Decimal("0.42"),
                    fee=Decimal(0),
                    held=False,
                    station=_STATION,
                    qty=Decimal(1),
                    side="yes",
                    rung="r",
                ),
            )
        )


def test_l40_same_side_variance() -> None:
    yes = _day(
        (_buy("a", "yes", "1", "0.20"), _buy("b", "yes", "1", "0.30")),
        (_settle("a", "yes", held=True), _settle("b", "yes", held=False)),
    )
    no = _day(
        (_buy("a", "no", "1", "0.80"), _buy("b", "no", "1", "0.70")),
        (_settle("a", "no", held=False), _settle("b", "no", held=True)),
    )
    # S = Σ q = 0.5, Var = S(1-S) at qty ≡ 1.
    assert yes.variance == pytest.approx(0.25)
    assert no.variance == pytest.approx(0.25)
    assert yes.variance == pytest.approx(combine_station_day(yes.rows).variance)
    assert no.variance == pytest.approx(combine_station_day(no.rows).variance)


def test_l40_mixed_side_variance() -> None:
    day = _day(
        (_buy("a", "yes", "1", "0.20"), _buy("b", "no", "1", "0.70")),
        (_settle("a", "yes", held=False), _settle("b", "no", held=True)),
    )
    # q_y = 0.20, q_n = 0.30, Var = S - (q_y - q_n)².
    q_y, q_n = 0.20, 0.30
    total = q_y + q_n
    assert day.variance == pytest.approx(total - (q_y - q_n) ** 2)
    assert day.variance == pytest.approx(combine_station_day(day.rows).variance)


def test_feasible_variance_equals_combine_station_day(monkeypatch: pytest.MonkeyPatch) -> None:
    import breezy.analysis.fq_loss_stop_shrink as shrink

    seen: list[int] = []

    def _spy(rows: tuple[StratumRow, ...] | list[StratumRow]) -> object:
        seen.append(len(tuple(rows)))
        return combine_station_day(rows)

    monkeypatch.setattr(shrink, "combine_station_day", _spy)
    day = _day(
        (_buy("a", "yes", "1", "0.20"), _buy("b", "yes", "1", "0.30")),
        (_settle("a", "yes", held=True), _settle("b", "yes", held=False)),
    )
    assert seen == [2]
    assert day.variance == pytest.approx(combine_station_day(day.rows).variance)
    assert day.x_rand == pytest.approx(combine_station_day(day.rows).x)


def test_shrink_gives_every_leg_drift_at_most_zero() -> None:
    rows = (
        StratumRow(
            entry_ask=Decimal("0.50"),
            fee=Decimal(0),
            held=False,
            station=_STATION,
            side="yes",
            rung="y",
        ),
        StratumRow(
            entry_ask=Decimal("0.25"),
            fee=Decimal(0),
            held=False,
            station=_STATION,
            side="yes",
            rung="z",
        ),
        StratumRow(
            entry_ask=Decimal("0.50"),
            fee=Decimal(0),
            held=True,
            station=_STATION,
            side="no",
            rung="n",
        ),
    )
    joint = shrunk_joint(rows)
    assert joint.kappa == pytest.approx((1.0 - 0.50) / (0.50 + 0.25))
    assert all(drift <= 0.0 for drift in joint.drifts)
    assert joint.drifts[0] < 0.0
    assert joint.drifts[1] < 0.0
    assert joint.drifts[2] == pytest.approx(0.0)


def test_mixed_overround_matches_hand_computed_moments() -> None:
    """YES on rung A at BE 0.8 and NO on rung B at BE 0.7.

    Σq = 0.8 + (1 − 0.7) = 1.1. κ = (1 − 0.3) / 0.8 = 0.875.
    Outcomes are x = +0.5 w.p. 0.7 and x = −1.5 w.p. 0.3, so
    E[x] = −0.1, E[x²] = 0.85 and variance = 0.84. Drifts are
    (E[H] − BE) = (−0.1, 0.0). Written out here, not via
    ``_brute_shrunk_variance``.
    """
    rows = (
        StratumRow(
            entry_ask=Decimal("0.8"),
            fee=Decimal(0),
            held=False,
            station=_STATION,
            side="yes",
            rung="A",
        ),
        StratumRow(
            entry_ask=Decimal("0.7"),
            fee=Decimal(0),
            held=False,
            station=_STATION,
            side="no",
            rung="B",
        ),
    )
    expect = 0.7 * 0.5 + 0.3 * -1.5
    second = 0.7 * 0.5**2 + 0.3 * (-1.5) ** 2
    assert expect == pytest.approx(-0.1)
    assert second == pytest.approx(0.85)
    assert second - expect**2 == pytest.approx(0.84)

    joint = shrunk_joint(rows)
    assert joint.kappa == pytest.approx(0.875, abs=1e-12)
    assert joint.variance == pytest.approx(0.84, abs=1e-12)
    assert joint.drifts == pytest.approx((-0.1, 0.0), abs=1e-12)


def test_sigma_no_above_one_refuses() -> None:
    rows = (
        StratumRow(
            entry_ask=Decimal("0.05"),
            fee=Decimal(0),
            held=False,
            station=_STATION,
            side="no",
            rung="a",
        ),
        StratumRow(
            entry_ask=Decimal("0.05"),
            fee=Decimal(0),
            held=False,
            station=_STATION,
            side="no",
            rung="b",
        ),
    )
    with pytest.raises(FqLossStopRefusal) as exc:
        shrunk_joint(rows)
    assert exc.value.reason is ReasonCode.SIGMA_NO_EXCEEDS_ONE
    with pytest.raises(FqLossStopRefusal) as via_day:
        _day(
            (_buy("a", "no", "1", "0.05"), _buy("b", "no", "1", "0.05")),
            (_settle("a", "no", held=False), _settle("b", "no", held=False)),
        )
    assert via_day.value.reason is ReasonCode.SIGMA_NO_EXCEEDS_ONE


def test_shrunk_variance_matches_brute_force_enumeration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import breezy.analysis.fq_loss_stop_shrink as shrink

    def _boom(rows: object) -> object:
        raise AssertionError("overround must not call combine_station_day")

    monkeypatch.setattr(shrink, "combine_station_day", _boom)
    day = _day(
        (
            _buy("a", "yes", "1", "0.50"),
            _buy("b", "yes", "1", "0.50"),
            _buy("c", "yes", "1", "0.50"),
        ),
        (
            _settle("a", "yes", held=False),
            _settle("b", "yes", held=True),
            _settle("c", "yes", held=False),
        ),
    )
    assert day.variance == pytest.approx(_brute_shrunk_variance(day.rows))
    joint: ShrunkJoint = shrunk_joint(day.rows)
    assert joint.variance == pytest.approx(day.variance)
    assert joint.kappa == pytest.approx(2.0 / 3.0)


def test_no_leg_be_is_the_instrument_price_not_the_wire() -> None:
    # A YES wire of 0.70 would price the NO at 0.30. The NO instrument
    # filled at 0.22, and that is the only price the core accepts.
    day = _day(
        (_buy("r", "no", "1", "0.22"),),
        (_settle("r", "no", held=False),),
    )
    assert day.rows[0].side == "no"
    assert day.rows[0].entry_ask == Decimal("0.22")
    assert day.rows[0].fee == Decimal(0)
    assert day.x_rand == pytest.approx(-0.22)


@pytest.mark.parametrize(
    ("reconciled", "fee"),
    [(False, "0.01"), (True, None)],
)
def test_fee_unreconciled_or_missing_refuses(reconciled: bool, fee: str | None) -> None:
    with pytest.raises(FqLossStopRefusal) as exc:
        _day(
            (_buy("r", "yes", "1", "0.40", fee, reconciled=reconciled),),
            (_settle("r", "yes", held=False),),
        )
    expected = ReasonCode.MISSING_FEE if fee is None else ReasonCode.FEE_UNRECONCILED
    assert exc.value.reason is expected


def test_missing_settlement_refuses() -> None:
    with pytest.raises(FqLossStopRefusal) as exc:
        _day((_buy("r", "yes", "1", "0.40"),), ())
    assert exc.value.reason is ReasonCode.MISSING_SETTLEMENT


def test_exit_blend_keeps_unexited_variance() -> None:
    proceeds_cost = Decimal("0.30")
    fee = Decimal("0.10")
    day = _day(
        (_buy("r", "yes", "4", "1.20"),),
        (_settle("r", "yes", held=True),),
        exits=(ExitFill(rung="r", side="yes", qty=Decimal(2), cost=proceeds_cost, fee=fee),),
    )
    v = (proceeds_cost - fee) / Decimal(2)
    # f = 2/4, h = 1 → h_eff = 0.5 * 1 + 0.5 * v
    h_eff = Decimal("0.5") * Decimal(1) + Decimal("0.5") * v
    leg: BundleLeg = day.legs[0]
    assert leg.h_eff == h_eff
    assert day.x_rand == pytest.approx(float(h_eff - Decimal("0.30")))
    assert day.variance == pytest.approx(0.30 * 0.70)


def test_voided_leg_adds_nothing_to_x_or_variance() -> None:
    both = _day(
        (_buy("void", "yes", "1", "0.40"), _buy("live", "yes", "1", "0.25")),
        (
            _settle("void", "yes", held=False, voided=True),
            _settle("live", "yes", held=False),
        ),
    )
    live = _day((_buy("live", "yes", "1", "0.25"),), (_settle("live", "yes", held=False),))
    assert len(both.rows) == 1
    assert both.rows[0].rung == "live"
    assert both.x_rand == pytest.approx(live.x_rand)
    assert both.variance == pytest.approx(live.variance)
    empty = _day(
        (_buy("void", "yes", "1", "0.40"),),
        (_settle("void", "yes", held=False, voided=True),),
    )
    assert empty.rows == ()
    assert empty.x_rand == pytest.approx(0.0)
    assert empty.variance == pytest.approx(0.0)
    assert step_clock(empty, 0.0).is_tick is False


def test_per_contract_exit_v_divides_total_proceeds() -> None:
    proceeds = Decimal("2.50")
    fee = Decimal("0.10")
    cost = proceeds + fee
    sold = Decimal(5)
    assert per_contract_exit_v(cost=cost, fee=fee, sold_qty=sold) == proceeds / sold
    day = _day(
        (_buy("r", "yes", "5", "2.00"),),
        (_settle("r", "yes", held=False),),
        exits=(ExitFill(rung="r", side="yes", qty=sold, cost=cost, fee=fee),),
    )
    assert day.legs[0].h_eff == proceeds / sold
    assert day.x_rand == pytest.approx(float(proceeds / sold - Decimal("0.40")))
    assert day.variance == pytest.approx(0.40 * 0.60)
    with pytest.raises(FqLossStopRefusal) as exc:
        per_contract_exit_v(cost=Decimal("1.00"), fee=Decimal("1.01"), sold_qty=sold)
    assert exc.value.reason is ReasonCode.INVALID_EXIT_FILL
    with pytest.raises(FqLossStopRefusal) as through_day:
        _day(
            (_buy("r", "yes", "5", "2.00"),),
            (_settle("r", "yes", held=False),),
            exits=(
                ExitFill(rung="r", side="yes", qty=sold, cost=Decimal("1.00"), fee=Decimal("1.01")),
            ),
        )
    assert through_day.value.reason is ReasonCode.INVALID_EXIT_FILL


@pytest.mark.parametrize(
    ("cost", "fee"),
    [("0", "0"), ("1", "0"), ("1.01", "0"), ("-0.01", "0"), ("0.50", "0.50")],
)
def test_be_bar_guard(cost: str, fee: str) -> None:
    with pytest.raises(FqLossStopRefusal) as exc:
        _day(
            (_buy("r", "yes", "1", cost, fee),),
            (_settle("r", "yes", held=False),),
        )
    assert exc.value.reason is ReasonCode.BE_OUT_OF_RANGE


def test_sigma_eps_gates_ticks_and_refuses_negative_variance() -> None:
    carried = step_clock(_bare(variance=0.0, shift=-0.25), 0.10)
    assert carried.is_tick is False
    assert carried.z is None
    assert carried.carry_out == pytest.approx(-0.15)

    ticked = step_clock(_bare(variance=1.0, x_rand=-0.50), 0.25)
    assert ticked.is_tick is True
    assert ticked.z == pytest.approx(-0.25)
    assert ticked.carry_out == 0.0

    # Variance units: half the threshold must not tick. Its square root is
    # many orders above the threshold, so a σ-unit comparison would tick.
    dust = step_clock(_bare(variance=VARIANCE_EPS / 2, shift=0.5), 0.0)
    assert dust.is_tick is False
    assert dust.sigma == 0.0
    assert dust.carry_out == pytest.approx(0.5)

    with pytest.raises(FqLossStopRefusal) as exc:
        step_clock(_bare(variance=-VARIANCE_EPS), 0.0)
    assert exc.value.reason is ReasonCode.NEGATIVE_VARIANCE

    soft = step_clock(_bare(variance=-(VARIANCE_EPS / 2), shift=0.2), 0.0)
    assert soft.is_tick is False
    assert soft.carry_out == pytest.approx(0.2)


def test_variance_1e_17_does_not_tick() -> None:
    """1e-17 is under the variance threshold (σ would be about 3e-9)."""
    step = step_clock(_bare(variance=1e-17, shift=0.4), 0.0)
    assert step.is_tick is False
    assert step.sigma == 0.0
    assert step.z is None
    assert step.carry_out == pytest.approx(0.4)


def test_zero_variance_day_does_not_drop_x_rand() -> None:
    with pytest.raises(FqLossStopRefusal, match="realised P&L") as err:
        step_clock(_bare(variance=0.0, x_rand=-0.4, shift=0.1), 0.0)
    assert err.value.reason is ReasonCode.ZERO_VARIANCE_REALISED


def test_first_crossing_returns_the_first_t_or_none() -> None:
    # S = -1, -2, -3. Boundary at c=1: -1, -√2, -√3. Strict at t=2.
    assert first_crossing((-1.0, -1.0, -1.0), c=1.0, t_min=1) == 2
    assert first_crossing((-1.0, -1.0, -1.0), c=1.0, t_min=3) == 3
    assert first_crossing((0.0, 0.0, 0.0), c=1.0, t_min=1) is None
    # Equality is not a crossing.
    assert first_crossing((-1.0,), c=1.0, t_min=1) is None
    assert first_crossing((), c=1.0, t_min=1) is None


def test_same_rung_opposite_bundle_is_a_core_refusal() -> None:
    rows = (
        StratumRow(
            entry_ask=Decimal("0.40"),
            fee=Decimal(0),
            held=False,
            station=_STATION,
            side="yes",
            rung="same",
        ),
        StratumRow(
            entry_ask=Decimal("0.40"),
            fee=Decimal(0),
            held=False,
            station=_STATION,
            side="no",
            rung="same",
        ),
    )
    with pytest.raises(FqLossStopRefusal) as exc:
        bundle_variance(rows)
    assert exc.value.reason is ReasonCode.ADMISSION_REFUSED


def _brute_shrunk_variance(rows: tuple[StratumRow, ...]) -> float:
    """Independent k+1 enumeration. Not the module's implementation."""
    bes: list[float] = []
    sides: list[str] = []
    qs: list[float] = []
    for row in rows:
        be = float(row.entry_ask + row.fee)
        q = be if row.side == "yes" else 1.0 - be
        bes.append(be)
        sides.append(row.side)
        qs.append(q)
    sum_no = sum(q for q, side in zip(qs, sides, strict=True) if side == "no")
    sum_yes = sum(q for q, side in zip(qs, sides, strict=True) if side == "yes")
    kappa = (1.0 - sum_no) / sum_yes
    masses = [kappa * q if side == "yes" else q for q, side in zip(qs, sides, strict=True)]
    probs = masses + [1.0 - sum(masses)]
    k = len(rows)
    mean = 0.0
    second = 0.0
    for outcome in range(k + 1):
        x = 0.0
        for i in range(k):
            if sides[i] == "yes":
                h = 1.0 if outcome == i else 0.0
            else:
                h = 0.0 if outcome == i else 1.0
            x += h - bes[i]
        mean += probs[outcome] * x
        second += probs[outcome] * x * x
    return second - mean * mean
