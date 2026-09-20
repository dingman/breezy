"""Realised post-fee PnL on the takes the WP-7 cheap screen actually made.

The registered §3 bar scores `p_fc - (price + fee)` -- MODEL-CLAIMED edge --
and never asks whether the forecast was RIGHT. These tests pin the two places
a realised-PnL falsification can silently lie:

* the RUNG BOUNDARY CONVENTION. The venue's `gte<A>lt<A+1>f` slug is a CLOSED
  integer-°F interval `[A, A+1]` (`h4_preliminary_economic_read.Rung`: "`upper_f`
  is INCLUSIVE: `gte78lt79f` settles YES on 78 and on 79"). A half-open
  `[A, A+1)` reading loses every settlement landing exactly on the upper bound,
  and under a half-open reading the ladder is not even a partition of the
  integers. Each boundary test below carries its own MUTATION check: it states
  the half-open answer and asserts it DIFFERS, so a silent flip to `<` cannot
  pass.
* the FEE. It must be the production `decision.fee_on_ask` reached through
  `forecast_tape_screen.venue_fee` -- banker's-rounded to the cent -- and never
  a flat `theta` subtraction, which is ~5x the real hurdle at mid prices.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"

DAY = dt.date(2026, 9, 10)
MIA = "tc-temp-miamihigh-2026-09-10-gte86lt87f.POLYMARKET_US"
TAIL_HIGH = "tc-temp-miamihigh-2026-09-10-gte90f.POLYMARKET_US"
TAIL_LOW = "tc-temp-miamihigh-2026-09-10-lt80f.POLYMARKET_US"


def _load_module(name: str) -> ModuleType:
    if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))
    path = _SCRIPTS_ANALYSIS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def fals() -> ModuleType:
    return _load_module("wp7_realised_pnl_falsification")


@pytest.fixture(scope="module")
def fee() -> ModuleType:
    return _load_module("forecast_tape_screen")


def _half_open_contains(*, lower: int, named_upper: int, value: int) -> bool:
    """The WRONG reading the boundary tests exist to exclude: `[lower, named_upper)`.

    Written out here so each mutation check compares against a real half-open
    evaluation rather than a hand-asserted constant.
    """
    return lower <= value < named_upper


def _outcome(fals: ModuleType, *, side: str, rung: str, tmax: int, price: float,
             claimed: float = 0.0, station: str = "MIA", day: dt.date = DAY):
    return fals.score_take(
        station=station,
        climate_day=day,
        variant_id="A1-B1-C1",
        side=side,
        rung_id=rung,
        price=price,
        claimed_margin=claimed,
        settled_tmax_f=tmax,
    )


# -- the boundary convention, with its mutation check -----------------------


def test_a_yes_take_wins_on_the_slugs_INCLUSIVE_upper_bound(fals: ModuleType) -> None:
    """`gte86lt87f` settles YES on 87. A half-open reading would call this a LOSS."""
    out = _outcome(fals, side="YES", rung=MIA, tmax=87, price=0.30)
    assert out.won is True
    # MUTATION CHECK: the half-open `[86, 87)` answer is the opposite verdict,
    # so a silent `<` in the bound test cannot pass this test.
    half_open_won = _half_open_contains(lower=86, named_upper=87, value=87)
    assert half_open_won is False
    assert half_open_won != out.won


def test_a_yes_take_wins_on_the_slugs_lower_bound_too(fals: ModuleType) -> None:
    out = _outcome(fals, side="YES", rung=MIA, tmax=86, price=0.30)
    assert out.won is True


def test_a_yes_take_loses_one_degree_above_the_inclusive_upper_bound(fals: ModuleType) -> None:
    out = _outcome(fals, side="YES", rung=MIA, tmax=88, price=0.30)
    assert out.won is False


def test_a_no_take_LOSES_on_the_inclusive_upper_bound(fals: ModuleType) -> None:
    """The NO leg is the exact complement, so the boundary flip costs it a win."""
    out = _outcome(fals, side="NO", rung=MIA, tmax=87, price=0.30)
    assert out.won is False
    half_open_no_won = not _half_open_contains(lower=86, named_upper=87, value=87)
    assert half_open_no_won is True
    assert half_open_no_won != out.won


def test_an_open_upper_tail_has_no_ceiling(fals: ModuleType) -> None:
    assert _outcome(fals, side="YES", rung=TAIL_HIGH, tmax=90, price=0.2).won is True
    assert _outcome(fals, side="YES", rung=TAIL_HIGH, tmax=140, price=0.2).won is True
    assert _outcome(fals, side="YES", rung=TAIL_HIGH, tmax=89, price=0.2).won is False


def test_an_open_lower_tail_reads_lt80f_as_at_most_79(fals: ModuleType) -> None:
    assert _outcome(fals, side="YES", rung=TAIL_LOW, tmax=79, price=0.2).won is True
    assert _outcome(fals, side="YES", rung=TAIL_LOW, tmax=80, price=0.2).won is False
    assert _outcome(fals, side="NO", rung=TAIL_LOW, tmax=80, price=0.2).won is True


# -- the fee, with its flat-fee mutation check ------------------------------


def test_realised_pnl_subtracts_the_production_banker_rounded_fee(
    fals: ModuleType, fee: ModuleType
) -> None:
    price = 0.30
    expected_fee = fee.venue_fee(ask_probability=price)
    out = _outcome(fals, side="YES", rung=MIA, tmax=86, price=price)
    assert out.fee == pytest.approx(expected_fee)
    assert out.realised_pnl == pytest.approx(1.0 - price - expected_fee)
    # MUTATION CHECK: a FLAT coefficient subtraction is a different number at
    # this price (0.01 rounded vs 0.0695 flat), so the flat variant cannot pass.
    flat = fee.DEFAULT_FEE_COEFFICIENT
    assert flat != pytest.approx(expected_fee)
    assert 1.0 - price - flat != pytest.approx(out.realised_pnl)


def test_the_fee_is_the_live_rules_function_byte_for_byte(fals: ModuleType) -> None:
    from breezy.strategy.current_rung_hold.decision import fee_on_ask

    assert fals.take_fee is not None
    for price in (0.01, 0.02, 0.14, 0.26, 0.50, 0.73, 0.99):
        from decimal import Decimal

        expected = float(fee_on_ask(Decimal(str(price)), Decimal(str(fals.FEE_COEFFICIENT))))
        assert fals.take_fee(price) == pytest.approx(expected)


def test_a_losing_take_realises_minus_price_minus_fee(fals: ModuleType, fee: ModuleType) -> None:
    price = 0.26
    out = _outcome(fals, side="YES", rung=MIA, tmax=99, price=price)
    assert out.won is False
    assert out.realised_pnl == pytest.approx(-price - fee.venue_fee(ask_probability=price))


def test_a_one_cent_ask_still_pays_its_rounded_fee(fals: ModuleType, fee: ModuleType) -> None:
    """At 0.01 the banker's-rounded fee is 0.00; the 1c subset must not be free
    of the fee by a different code path."""
    out = _outcome(fals, side="YES", rung=MIA, tmax=99, price=0.01)
    assert out.fee == pytest.approx(fee.venue_fee(ask_probability=0.01))
    assert out.realised_pnl == pytest.approx(-0.01 - out.fee)


# -- aggregation, the claimed-vs-realised gap, and the bootstrap ------------


def test_summary_reports_win_rate_mean_median_and_total(fals: ModuleType) -> None:
    outs = [
        _outcome(fals, side="YES", rung=MIA, tmax=86, price=0.30, claimed=0.10),
        _outcome(fals, side="YES", rung=MIA, tmax=99, price=0.30, claimed=0.10),
        _outcome(fals, side="YES", rung=MIA, tmax=99, price=0.30, claimed=0.10),
    ]
    summary = fals.summarise(outs)
    assert summary.n_takes == 3
    assert summary.win_rate == pytest.approx(1 / 3)
    realised = sorted(o.realised_pnl for o in outs)
    assert summary.mean_realised == pytest.approx(sum(realised) / 3)
    assert summary.median_realised == pytest.approx(realised[1])
    assert summary.total_realised == pytest.approx(sum(realised))
    assert summary.median_claimed_margin == pytest.approx(0.10)


def test_an_empty_variant_summarises_without_raising(fals: ModuleType) -> None:
    summary = fals.summarise([])
    assert summary.n_takes == 0
    assert summary.win_rate is None
    assert summary.mean_realised is None
    assert fals.cluster_bootstrap_mean_ci([], cluster=fals.CLUSTER_DATE) is None


def test_the_bootstrap_clusters_by_date_and_is_deterministic(fals: ModuleType) -> None:
    outs = [
        _outcome(fals, side="YES", rung=MIA, tmax=86 if i % 3 else 99, price=0.30,
                 day=DAY + dt.timedelta(days=i // 4), station=("MIA", "LAX")[i % 2])
        for i in range(24)
    ]
    first = fals.cluster_bootstrap_mean_ci(outs, cluster=fals.CLUSTER_DATE)
    again = fals.cluster_bootstrap_mean_ci(outs, cluster=fals.CLUSTER_DATE)
    assert first == again
    assert first is not None
    lo, hi = first
    assert lo <= fals.summarise(outs).mean_realised <= hi
    by_station = fals.cluster_bootstrap_mean_ci(outs, cluster=fals.CLUSTER_STATION)
    assert by_station is not None
    # Two clusters (station) vs six (date) is a genuinely different resample.
    assert by_station != first


def test_the_decisional_cluster_is_date(fals: ModuleType) -> None:
    assert fals.DECISIONAL_CLUSTER == fals.CLUSTER_DATE == "date"


def test_the_sub_two_cent_subset_is_selected_on_the_price_actually_lifted(
    fals: ModuleType,
) -> None:
    cheap = _outcome(fals, side="YES", rung=MIA, tmax=99, price=0.02, claimed=0.18)
    dear = _outcome(fals, side="YES", rung=MIA, tmax=99, price=0.03, claimed=0.18)
    subset = fals.sub_cent_subset([cheap, dear])
    assert [o.price for o in subset] == [0.02]
