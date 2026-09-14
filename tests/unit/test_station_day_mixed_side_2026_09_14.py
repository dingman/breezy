"""RED-first: mixed-side (YES/NO) station-day draw, S6a of
`docs/plans/NO_SIDE_EDGE_2026-09-14.md` SS3/SS4 (R3-5 item i, R3-7, R3-8).

`combine_station_day` gains a sign-aware H0 variance: `s_i = +1` (YES) /
`-1` (NO), `q_i = BE_i` (YES) / `1 - BE_i` (NO) is always `P(HIGH in
r_i)`, `held_i` is caller-supplied per-side truth. On an all-YES day this
must be byte-identical to today's formula -- pinned below against fixture
outputs captured from the pre-change code.
"""

from __future__ import annotations

import importlib.util
import math
import random
import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest

from breezy.settlement.current_rung_hold_v2 import (
    CombinedDraw,
    StationDayAdmissionRefusal,
    StratumRow,
    build_stratum_v2,
    combine_station_day,
    score,
)
from breezy.settlement.trial_scorer import ScoredTrial

FEE_THETA = Decimal("0.06")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"


def _load_family_tally_v2() -> ModuleType:
    """Mirrors `test_family_tally_v2.py::_load_module` -- the script has no
    package `__init__`, so it is loaded by file path, same as every other
    consumer of it in this test suite."""
    if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))
    path = _SCRIPTS_ANALYSIS_DIR / "family_tally_v2.py"
    spec = importlib.util.spec_from_file_location("family_tally_v2", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _scored_trial(*, ask: str, held: bool, station: str = "MIA") -> ScoredTrial:
    ask_d = Decimal(ask)
    fee = FEE_THETA * ask_d * (1 - ask_d)
    fill_px = ask_d
    pnl = (Decimal(1) if held else Decimal(0)) - fill_px - fee
    return ScoredTrial(
        trial_id=f"pm_us_crh_cont/{station}/2026-09-14/0",
        station=station,
        climate_day="2026-09-14",
        instrument_id="instrument-0",
        settlement_tmax_f=80,
        held=held,
        pnl=pnl,
        revision_seq=0,
        raw_sha256="deadbeef",
        scored_at_ns=1,
        score_seq=0,
        settlement_basis="nws_final",
        excluded_reason=None,
        slippage=Decimal(0),
        entry_ask=ask_d,
        fill_px=fill_px,
        fee=fee,
    )


def _row(
    entry_ask: str,
    held: bool,
    *,
    side: str = "yes",
    fee: Decimal | None = None,
    fee_theta: Decimal = FEE_THETA,
    station: str = "MIA",
    qty: Decimal = Decimal(1),
    rung: str | None = None,
) -> StratumRow:
    ask = Decimal(entry_ask)
    if fee is None:
        fee = fee_theta * ask * (1 - ask)
    return StratumRow(
        entry_ask=ask, fee=fee, held=held, station=station, side=side, qty=qty, rung=rung
    )


# ---------------------------------------------------------------------------
# (a) StratumRow accepts a `side`, default "yes"
# ---------------------------------------------------------------------------


def test_stratum_row_side_defaults_to_yes() -> None:
    row = StratumRow(entry_ask=Decimal("0.20"), fee=Decimal("0.01"), held=True, station="MIA")
    assert row.side == "yes"


def test_stratum_row_accepts_a_no_side() -> None:
    row = StratumRow(
        entry_ask=Decimal("0.20"), fee=Decimal("0.01"), held=True, station="MIA", side="no"
    )
    assert row.side == "no"


# ---------------------------------------------------------------------------
# (b) all-YES combine_station_day is BYTE-IDENTICAL to today's output.
#
# Fixtures captured from the pre-change code (fee_theta=0.06 for f1/f2, fee=0
# for f3) BEFORE this module was touched:
#   f1 = ((ask=0.35, held=True),)
#       -> CombinedDraw(x=0.63635, variance=0.23140867749999997, n_constituents=1)
#   f2 = ((ask=0.30, held=True, fee=0), (ask=0.20, held=False, fee=0))
#       -> CombinedDraw(x=0.4778, variance=0.24950715999999998, n_constituents=2)
#   f3 = ((ask=0.10, held=True, fee=0), (ask=0.30, held=False, fee=0),
#         (ask=0.50, held=True, fee=0))
#       -> CombinedDraw(x=1.1, variance=0.09000000000000002, n_constituents=3)
# ---------------------------------------------------------------------------


def test_all_yes_single_row_is_byte_identical_to_pinned_fixture() -> None:
    draw = combine_station_day((_row("0.35", True),))
    assert draw == CombinedDraw(x=0.63635, variance=0.23140867749999997, n_constituents=1)


def test_all_yes_two_row_is_byte_identical_to_pinned_fixture() -> None:
    draw = combine_station_day(
        (
            _row("0.30", True),
            _row("0.20", False),
        )
    )
    assert draw == CombinedDraw(x=0.4778, variance=0.24950715999999998, n_constituents=2)


def test_all_yes_three_row_is_byte_identical_to_pinned_fixture() -> None:
    draw = combine_station_day(
        (
            _row("0.10", True, fee=Decimal(0)),
            _row("0.30", False, fee=Decimal(0)),
            _row("0.50", True, fee=Decimal(0)),
        )
    )
    assert draw == CombinedDraw(x=1.1, variance=0.09000000000000002, n_constituents=3)


# ---------------------------------------------------------------------------
# (c) closed-form H0 variance checks for mixed pairs.
# ---------------------------------------------------------------------------


def test_yes_no_pair_variance_matches_the_sign_aware_closed_form() -> None:
    # YES leg A: ask 0.30, fee 0 -> BE_A = 0.30, q_A = 0.30, s_A = +1
    # NO  leg B: ask 0.85, fee 0 -> BE_B = 0.85, q_B = 1 - 0.85 = 0.15, s_B = -1
    # q_A + q_B = 0.45 <= 1, admissible. Distinct rungs (R3-7 mixed-day rule
    # requires a rung key on every row of a day containing a NO row).
    row_a = _row("0.30", True, side="yes", fee=Decimal(0), rung="R1")
    row_b = _row("0.85", True, side="no", fee=Decimal(0), rung="R2")

    draw = combine_station_day((row_a, row_b))

    q_a, q_b = 0.30, 0.15
    expected_variance = (
        q_a * (1.0 - q_a) + q_b * (1.0 - q_b) - 2.0 * (1.0) * (-1.0) * q_a * q_b
    )
    expected_x = (1.0 - 0.30) + (1.0 - 0.85)
    assert math.isclose(draw.variance, expected_variance, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(draw.x, expected_x, rel_tol=0, abs_tol=1e-12)


def test_no_no_pair_variance_matches_the_sign_aware_closed_form() -> None:
    # NO leg A: ask 0.85, fee 0 -> BE_A = 0.85, q_A = 1 - 0.85 = 0.15, s_A = -1
    # NO leg B: ask 0.75, fee 0 -> BE_B = 0.75, q_B = 1 - 0.75 = 0.25, s_B = -1
    # q_A + q_B = 0.40 <= 1, admissible. Distinct rungs.
    row_a = _row("0.85", False, side="no", fee=Decimal(0), rung="R1")
    row_b = _row("0.75", True, side="no", fee=Decimal(0), rung="R2")

    draw = combine_station_day((row_a, row_b))

    q_a, q_b = 0.15, 0.25
    expected_variance = (
        q_a * (1.0 - q_a) + q_b * (1.0 - q_b) - 2.0 * (-1.0) * (-1.0) * q_a * q_b
    )
    expected_x = (0.0 - 0.85) + (1.0 - 0.75)
    assert math.isclose(draw.variance, expected_variance, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(draw.x, expected_x, rel_tol=0, abs_tol=1e-12)


# ---------------------------------------------------------------------------
# (d) `held` for a NO leg is 1{HIGH not in r}.
# ---------------------------------------------------------------------------


def test_no_leg_held_true_means_high_landed_off_the_rung() -> None:
    """A NO row on a rung the HIGH landed IN scores 0 (held=False); off it,
    scores 1 (held=True). This is the caller's responsibility (family_tally_v2
    inverts the YES `held` truth when building a NO `StratumRow`); this test
    pins that `combine_station_day`/`StratumRow` treat `held` literally and
    make no further inversion of their own."""
    off_rung_no = _row("0.20", True, side="no", fee=Decimal(0), rung="R1")
    on_rung_no = _row("0.20", False, side="no", fee=Decimal(0), rung="R1")

    off_draw = combine_station_day((off_rung_no,))
    on_draw = combine_station_day((on_rung_no,))

    assert off_draw.x > 0  # held=True (HIGH missed the rung) scores positively
    assert on_draw.x < 0  # held=False (HIGH landed on the rung) scores negatively


# ---------------------------------------------------------------------------
# (e) admission gate: Sum over rungs of q_r <= 1.
# ---------------------------------------------------------------------------


def test_cheap_no_plus_a_yes_elsewhere_is_refused_by_the_q_gate() -> None:
    # NO leg: ask 0.20 -> BE=0.20, q=0.80 (cheap NO -- most of the mass).
    # YES leg on a distinct rung: ask 0.35 -> BE=q=0.35.
    # 0.80 + 0.35 = 1.15 > 1 -- refused.
    no_row = _row("0.20", True, side="no", fee=Decimal(0), station="MIA", rung="R1")
    yes_row = _row("0.35", True, side="yes", fee=Decimal(0), station="MIA", rung="R2")

    with pytest.raises(StationDayAdmissionRefusal):
        combine_station_day((no_row, yes_row))


def test_all_yes_day_under_the_edge_rule_is_never_refused_by_the_q_gate() -> None:
    # Regression: an all-YES day (q_i == BE_i) keeps today's Sum BE_i <= 1 gate.
    rows = (
        _row("0.30", True, fee=Decimal(0)),
        _row("0.20", False, fee=Decimal(0)),
    )
    draw = combine_station_day(rows)
    assert draw.n_constituents == 2


# ---------------------------------------------------------------------------
# (f) E[x] = 0 under H0 and Var(S) ~= 1 for a mixed day, by seeded simulation.
# ---------------------------------------------------------------------------


def _simulate_mixed_station_day_draw(rng: random.Random) -> CombinedDraw:
    """One station-day with a YES leg on one rung and a NO leg on another,
    each leg's `held` drawn from its own H0 cell probability `q_i`, exogenous
    to `BE_i` (R3-8's stated H0 assumption). `q_yes + q_no <= 1` by
    construction: `q_yes` is drawn on `[0.02, 0.40]` and the NO leg's ask is
    drawn high enough that `q_no = 1 - no_ask` never pushes the sum past 1.
    """
    q_yes = round(rng.uniform(0.02, 0.40), 4)
    q_no_max = 1.0 - q_yes
    q_no = round(rng.uniform(0.02, min(0.40, q_no_max)), 4)
    yes_ask = Decimal(str(q_yes))  # fee=0 for the simulation's clean closed form
    no_ask = Decimal(str(round(1.0 - q_no, 4)))
    # Distinct rungs are mutually exclusive: HIGH lands in AT MOST ONE of them,
    # so Y_yes/Y_no are drawn from a single categorical (not independent
    # Bernoullis) with Cov(Y_yes, Y_no) = -q_yes*q_no.
    u = rng.random()
    if u < q_yes:
        yes_held, no_held = True, True  # HIGH in the YES rung -> off the NO rung
    elif u < q_yes + q_no:
        yes_held, no_held = False, False  # HIGH in the NO rung -> on it
    else:
        yes_held, no_held = False, True  # HIGH elsewhere -> off both rungs
    rows = (
        StratumRow(
            entry_ask=yes_ask,
            fee=Decimal(0),
            held=yes_held,
            station="MIA",
            side="yes",
            rung="R_YES",
        ),
        StratumRow(
            entry_ask=no_ask,
            fee=Decimal(0),
            held=no_held,
            station="MIA",
            side="no",
            rung="R_NO",
        ),
    )
    return combine_station_day(rows)


def test_mixed_day_h0_simulation_has_zero_mean_and_unit_variance() -> None:
    rng = random.Random(20260914)
    n_reps = 20_000
    xs: list[float] = []
    variances: list[float] = []
    standardized: list[float] = []
    for _ in range(n_reps):
        draw = _simulate_mixed_station_day_draw(rng)
        xs.append(draw.x)
        variances.append(draw.variance)
        standardized.append(draw.x / math.sqrt(draw.variance))

    mean_x = sum(xs) / n_reps
    sigma_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs) / n_reps)
    se_mean = sigma_x / math.sqrt(n_reps)
    assert abs(mean_x) < 3 * se_mean

    # Derived Monte-Carlo SE bound (item 4, follow-up review), not a bare
    # literal tolerance: 3 * SE of the sample mean of the squared
    # standardised draws, computed from their own sample standard deviation.
    squared = [s * s for s in standardized]
    mean_standardized_sq = sum(squared) / n_reps
    sigma_sq = math.sqrt(sum((v - mean_standardized_sq) ** 2 for v in squared) / n_reps)
    se_sq = sigma_sq / math.sqrt(n_reps)
    assert abs(mean_standardized_sq - 1.0) < 3 * se_sq


# ---------------------------------------------------------------------------
# family_tally_v2._stratum_row wiring: `side` carried from the trial record
# if present (default "yes"); existing (no-`side`-attribute) records are
# byte-identical to today's output.
# ---------------------------------------------------------------------------


def test_stratum_row_wiring_defaults_to_yes_for_a_record_with_no_side_attribute() -> None:
    tally_mod = _load_family_tally_v2()
    trial = _scored_trial(ask="0.20", held=True)
    assert not hasattr(trial, "side")

    row = tally_mod._stratum_row(trial)

    assert row.side == "yes"
    assert row.held is True
    assert row.entry_ask == trial.entry_ask
    assert row.fee == trial.fee
    assert row.station == trial.station


def test_stratum_row_wiring_is_byte_identical_for_an_all_yes_fixture() -> None:
    """Pin: before/after this change, an all-YES `ScoredTrial` (no `side`
    attribute) produces the SAME `StratumRow` fields through `_stratum_row`."""
    tally_mod = _load_family_tally_v2()
    trial = _scored_trial(ask="0.35", held=False, station="SFO")

    row = tally_mod._stratum_row(trial)

    assert row == StratumRow(
        entry_ask=Decimal("0.35"),
        fee=FEE_THETA * Decimal("0.35") * (1 - Decimal("0.35")),
        held=False,
        station="SFO",
        side="yes",
    )


class _NoLegScoredTrial:
    """A minimal stand-in carrying a `side` attribute `ScoredTrial` itself
    does not have (the 17-column schema is out of scope for this slice;
    S5 is where a real NO-leg record lands on `ScoredTrial`). Exercises
    `_stratum_row`'s `getattr(trial, "side", "yes")` branch structurally."""

    def __init__(self, *, entry_ask: Decimal, fee: Decimal, held: bool, station: str) -> None:
        self.entry_ask = entry_ask
        self.fee = fee
        self.held = held
        self.station = station
        self.side = "no"


def test_stratum_row_wiring_carries_a_no_side_and_inverts_held() -> None:
    """A NO row on a rung the HIGH landed IN (`trial.held=True`, i.e. Y=1)
    must score held=False; off it (`trial.held=False`), held=True."""
    tally_mod = _load_family_tally_v2()
    on_rung = _NoLegScoredTrial(
        entry_ask=Decimal("0.20"), fee=Decimal("0.01"), held=True, station="MIA"
    )
    off_rung = _NoLegScoredTrial(
        entry_ask=Decimal("0.20"), fee=Decimal("0.01"), held=False, station="MIA"
    )

    on_row = tally_mod._stratum_row(on_rung)
    off_row = tally_mod._stratum_row(off_rung)

    assert on_row.side == "no"
    assert on_row.held is False
    assert off_row.side == "no"
    assert off_row.held is True


# ---------------------------------------------------------------------------
# Follow-up review fixes (two independent FIX-FIRST reviews of 87278dd).
# ---------------------------------------------------------------------------


# --- [HIGH] item 1: StratumRow.side is runtime-validated -------------------


def test_stratum_row_rejects_a_side_outside_yes_or_no() -> None:
    with pytest.raises(ValueError):
        StratumRow(
            entry_ask=Decimal("0.20"), fee=Decimal("0.01"), held=True, station="MIA", side="Yes"
        )


def test_stratum_row_rejects_a_none_side() -> None:
    with pytest.raises(ValueError):
        StratumRow(
            entry_ask=Decimal("0.20"),
            fee=Decimal("0.01"),
            held=True,
            station="MIA",
            side=None,  # type: ignore[arg-type]
        )


# --- [HIGH latent] item 2: rung-keyed folding and same-rung admission ------


def test_same_rung_same_side_duplicates_fold_qty_and_keep_one_rung_in_the_gate() -> None:
    """Two YES fills on the SAME rung (same entry_ask) fold into one qty=2
    row for the Sigma-q gate and the variance/x sums -- NOT two separate
    rung slots."""
    row_a = _row("0.30", True, fee=Decimal(0), rung="R1", qty=Decimal(1))
    row_b = _row("0.30", True, fee=Decimal(0), rung="R1", qty=Decimal(1))

    draw = combine_station_day((row_a, row_b))

    # Folded to qty=2 on a single q=0.30 rung: x = 2*(1-0.30), var = 4*0.30*0.70.
    assert math.isclose(draw.x, 2 * (1.0 - 0.30), rel_tol=0, abs_tol=1e-12)
    assert math.isclose(draw.variance, 4 * 0.30 * 0.70, rel_tol=0, abs_tol=1e-12)


def test_same_rung_same_side_duplicates_at_differing_ask_are_refused() -> None:
    row_a = _row("0.30", True, fee=Decimal(0), rung="R1")
    row_b = _row("0.32", True, fee=Decimal(0), rung="R1")

    with pytest.raises(StationDayAdmissionRefusal):
        combine_station_day((row_a, row_b))


def test_same_rung_opposite_sides_are_refused_before_the_q_gate() -> None:
    """A YES fill and a NO fill on the SAME rung is a same-instrument-day
    hedge -- forbidden regardless of whether Sigma-q would otherwise admit
    it (both asks cheap: 0.10 YES q=0.10, 0.10 NO q=0.90; same rung)."""
    yes_row = _row("0.10", True, side="yes", fee=Decimal(0), rung="R1")
    no_row = _row("0.10", True, side="no", fee=Decimal(0), rung="R1")

    with pytest.raises(StationDayAdmissionRefusal):
        combine_station_day((yes_row, no_row))


def test_a_no_row_missing_its_rung_key_refuses_the_whole_day() -> None:
    """A day containing a NO row where ANY row (YES or NO) lacks a `rung`
    key is inadmissible -- fold/opposite-side checks cannot run without it."""
    yes_row = _row("0.30", True, side="yes", fee=Decimal(0), rung=None)
    no_row = _row("0.20", True, side="no", fee=Decimal(0), rung="R2")

    with pytest.raises(StationDayAdmissionRefusal):
        combine_station_day((yes_row, no_row))


def test_all_yes_fixtures_without_rung_keys_are_unedited_and_still_pass() -> None:
    """Regression: the three S6a-pinned byte-identity fixtures never set
    `rung`, and an all-YES day with `rung=None` on every row is exactly
    today's mutually-exclusive-by-construction behaviour -- re-asserted
    here directly against the pinned values (no re-derivation)."""
    assert combine_station_day((_row("0.35", True),)) == CombinedDraw(
        x=0.63635, variance=0.23140867749999997, n_constituents=1
    )
    assert combine_station_day(
        (_row("0.30", True), _row("0.20", False))
    ) == CombinedDraw(x=0.4778, variance=0.24950715999999998, n_constituents=2)
    assert combine_station_day(
        (
            _row("0.10", True, fee=Decimal(0)),
            _row("0.30", False, fee=Decimal(0)),
            _row("0.50", True, fee=Decimal(0)),
        )
    ) == CombinedDraw(x=1.1, variance=0.09000000000000002, n_constituents=3)


def test_stratum_row_wiring_carries_a_rung_from_market_slug() -> None:
    """`_stratum_row` reads `rung` from `getattr(trial, "market_slug",
    None)` -- a dormant field on today's 17-column `ScoredTrial` (no
    schema change), same pattern as the existing `qty`/`side` gaps."""
    tally_mod = _load_family_tally_v2()

    class _WithSlug:
        def __init__(self) -> None:
            self.entry_ask = Decimal("0.20")
            self.fee = Decimal("0.01")
            self.held = True
            self.station = "MIA"
            self.side = "no"
            self.market_slug = "kxhighmia-26sep14"

    row = tally_mod._stratum_row(_WithSlug())
    assert row.rung == "kxhighmia-26sep14"


def test_stratum_row_wiring_rung_defaults_to_none_for_a_record_with_no_market_slug() -> None:
    tally_mod = _load_family_tally_v2()
    trial = _scored_trial(ask="0.20", held=True)
    assert not hasattr(trial, "market_slug")

    row = tally_mod._stratum_row(trial)

    assert row.rung is None


# --- [MEDIUM] item 3: score() / build_stratum_v2 are side-blind ------------


def test_score_refuses_any_no_side_row_until_side_aware() -> None:
    rows = (
        _row("0.10", True),
        _row("0.20", True, side="no", rung="R1"),
    )
    with pytest.raises(ValueError):
        score(rows)


def test_score_is_unchanged_for_all_yes_rows() -> None:
    rows = (_row("0.10", True), _row("0.50", False), _row("0.90", True))
    state = score(rows)
    assert state.n == 3


def test_build_stratum_v2_refuses_any_no_side_row_until_side_aware() -> None:
    rows = (
        _row("0.10", True),
        _row("0.20", True, side="no", rung="R1"),
    )
    with pytest.raises(ValueError):
        build_stratum_v2("station:MIA", rows)


def test_build_stratum_v2_is_unchanged_for_all_yes_rows() -> None:
    rows = (_row("0.10", True), _row("0.50", False), _row("0.90", True))
    stratum = build_stratum_v2("station:MIA", rows)
    assert stratum is not None
    assert stratum.n == 3
