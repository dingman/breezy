"""Mechanics of the WP-7 pre-registered cheap screen.

These tests pin the parts of `PREREG_WP7_MULTIPLICITY_RULE_2026-09-20.md` that
are supposed to be UNFORGEABLE rather than merely documented:

* the enumerated variant space is closed at exactly 12 (§1(i), §1(iii));
* an hour table can never reach the selection gate (§2.0, amendment A1);
* the take threshold is `> 0`, not the 0.03 reporting bar (§2.2);
* the first-take tie-break is fully deterministic (§2.2);
* `no_bid_side` is a NO-TAKE, never a dropped day (§2.2);
* a cell below `n >= 20` is INSUFFICIENT-DATA and never a PASS or a KILL (§4);
* Holm runs across the ENTIRE set of 12, thin cells included (§1(ii)).
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
def wp7() -> ModuleType:
    return _load_module("forecast_cheap_screen_wp7")


def _variant(wp7: ModuleType, variant_id: str):
    return next(v for v in wp7.ALL_VARIANTS if v.variant_id == variant_id)


def _instant(wp7: ModuleType, *, ts: int, hour: int, ask=None, ask_size=0.0, bid=None,
             bid_size=0.0):
    return wp7.RungInstant(
        ts_ns=ts, hour_lst=hour, ask=ask, ask_size=ask_size, bid=bid, bid_size=bid_size
    )


def _tape(wp7: ModuleType, rung_id: str, lower: int, upper: int, instants):
    return wp7.RungTape(rung_id=rung_id, lower_f=lower, upper_f=upper, instants=tuple(instants))


def _trial(wp7: ModuleType, *, station="SFO", day=DAY, took=True, margin=0.05, no_bid_side=False):
    return wp7.StationDayTrial(
        station=station,
        climate_day=day,
        took=took,
        margin=margin,
        side="YES",
        rung="r",
        ask=0.30,
        hour_lst=10,
        no_bid_side=no_bid_side,
        reason="TAKE" if took else "NO_POSITIVE_EDGE",
    )


# ---------------------------------------------------------------------------
# §1(i)/§1(iii) -- bounded enumeration
# ---------------------------------------------------------------------------


def test_the_variant_space_is_closed_at_exactly_twelve(wp7: ModuleType) -> None:
    assert wp7.K_VARIANTS == 12
    assert len(wp7.ALL_VARIANTS) == 12
    assert {v.variant_id for v in wp7.ALL_VARIANTS} == {
        f"{a}-{b}-{c}"
        for a in ("A1", "A2", "A3")
        for b in ("B1", "B2")
        for c in ("C1", "C2")
    }


def test_every_registered_window_and_side_is_present(wp7: ModuleType) -> None:
    assert wp7.WINDOWS == {"A1": (9, 12), "A2": (12, 17), "A3": (10, 11)}
    assert _variant(wp7, "A1-B1-C1").sides == ("YES",)
    assert _variant(wp7, "A1-B2-C1").sides == ("YES", "NO")
    assert _variant(wp7, "A1-B1-C2").ask_screen is True
    assert _variant(wp7, "A1-B1-C1").ask_screen is False


# ---------------------------------------------------------------------------
# §2.0 amendment A1 -- the hour firewall, enforced by TYPE
# ---------------------------------------------------------------------------


def test_an_hour_table_can_never_reach_the_selection_gate(wp7: ModuleType) -> None:
    hour = wp7.HourDiagnostic(
        variant_id="A2-B1-C1",
        hour_lst=14,
        trials=tuple(_trial(wp7, day=DAY + dt.timedelta(days=i)) for i in range(40)),
    )
    with pytest.raises(wp7.HourSelectionRefused, match="DIAGNOSIS ONLY"):
        wp7.evaluate_gate(hour)


def test_the_gate_refuses_anything_that_is_not_a_pooled_cell(wp7: ModuleType) -> None:
    with pytest.raises(TypeError):
        wp7.evaluate_gate([_trial(wp7)])


# ---------------------------------------------------------------------------
# §3 / §4 -- the measurement gate
# ---------------------------------------------------------------------------


def test_a_thin_cell_is_insufficient_data_and_never_a_verdict(wp7: ModuleType) -> None:
    cell = wp7.PooledCell(
        variant_id="A3-B1-C2",
        trials=tuple(_trial(wp7, day=DAY + dt.timedelta(days=i)) for i in range(19)),
    )
    result = wp7.evaluate_gate(cell)
    assert result.verdict == wp7.VERDICT_INSUFFICIENT_DATA
    assert result.verdict not in (wp7.VERDICT_CLEARS, wp7.VERDICT_FAILS)


def test_a_cell_clears_only_on_all_three_registered_conditions(wp7: ModuleType) -> None:
    trials = tuple(
        _trial(wp7, day=DAY + dt.timedelta(days=i), took=True, margin=0.05) for i in range(25)
    )
    assert wp7.evaluate_gate(wp7.PooledCell("A1-B1-C1", trials)).verdict == wp7.VERDICT_CLEARS

    # Same n, same take rate, median margin just under the reporting bar.
    thin_margin = tuple(
        _trial(wp7, day=DAY + dt.timedelta(days=i), took=True, margin=0.029) for i in range(25)
    )
    failed = wp7.evaluate_gate(wp7.PooledCell("A1-B1-C1", thin_margin))
    assert failed.verdict == wp7.VERDICT_FAILS
    assert "median post-fee margin" in failed.reasons[0]


def test_a_bare_majority_of_takes_does_not_clear_the_strict_half(wp7: ModuleType) -> None:
    trials = tuple(
        _trial(wp7, day=DAY + dt.timedelta(days=i), took=i < 12, margin=0.05 if i < 12 else -0.02)
        for i in range(24)
    )
    result = wp7.evaluate_gate(wp7.PooledCell("A1-B1-C1", trials))
    assert result.positive_rate == pytest.approx(0.5)
    assert result.verdict == wp7.VERDICT_FAILS


# ---------------------------------------------------------------------------
# §2.2 -- take threshold, tie-break, no_bid_side
# ---------------------------------------------------------------------------


def test_the_take_threshold_is_strictly_positive_not_the_reporting_bar(wp7: ModuleType) -> None:
    """A 0.01 post-fee margin IS a take; the 0.03 median is a REPORTING gate."""
    tape = _tape(wp7, "r70", 70, 71, [_instant(wp7, ts=1, hour=10, ask=0.30, ask_size=5.0)])
    trial = wp7.screen_station_day(
        station="SFO",
        climate_day=DAY,
        rungs=[tape],
        variant=_variant(wp7, "A1-B1-C1"),
        p_yes_by_rung={"r70": 0.32},
    )
    assert trial.took is True
    assert 0.0 < trial.margin < 0.03


def test_a_zero_margin_is_not_a_take(wp7: ModuleType) -> None:
    tape = _tape(wp7, "r70", 70, 71, [_instant(wp7, ts=1, hour=10, ask=0.30, ask_size=5.0)])
    p = 0.30 + wp7.venue_fee(ask_probability=0.30)
    trial = wp7.screen_station_day(
        station="SFO",
        climate_day=DAY,
        rungs=[tape],
        variant=_variant(wp7, "A1-B1-C1"),
        p_yes_by_rung={"r70": p},
    )
    assert trial.took is False
    assert trial.margin == pytest.approx(0.0)


def test_the_tie_break_takes_the_greatest_margin_at_the_first_take_instant(
    wp7: ModuleType,
) -> None:
    cheap = _tape(wp7, "r70", 70, 71, [_instant(wp7, ts=5, hour=10, ask=0.30, ask_size=5.0)])
    richer = _tape(wp7, "r72", 72, 73, [_instant(wp7, ts=5, hour=10, ask=0.20, ask_size=5.0)])
    trial = wp7.screen_station_day(
        station="SFO",
        climate_day=DAY,
        rungs=[cheap, richer],
        variant=_variant(wp7, "A1-B1-C1"),
        p_yes_by_rung={"r70": 0.60, "r72": 0.60},
    )
    assert trial.rung == "r72"  # greatest post-fee margin wins


def test_the_first_take_is_the_earliest_instant_not_the_best_one(wp7: ModuleType) -> None:
    early = _tape(wp7, "r70", 70, 71, [_instant(wp7, ts=1, hour=10, ask=0.40, ask_size=5.0)])
    late = _tape(wp7, "r72", 72, 73, [_instant(wp7, ts=9, hour=10, ask=0.10, ask_size=5.0)])
    trial = wp7.screen_station_day(
        station="SFO",
        climate_day=DAY,
        rungs=[early, late],
        variant=_variant(wp7, "A1-B1-C1"),
        p_yes_by_rung={"r70": 0.60, "r72": 0.60},
    )
    assert trial.rung == "r70"


def test_a_quote_outside_the_window_is_never_taken(wp7: ModuleType) -> None:
    tape = _tape(wp7, "r70", 70, 71, [_instant(wp7, ts=1, hour=8, ask=0.10, ask_size=5.0)])
    trial = wp7.screen_station_day(
        station="SFO",
        climate_day=DAY,
        rungs=[tape],
        variant=_variant(wp7, "A1-B1-C1"),
        p_yes_by_rung={"r70": 0.90},
    )
    assert trial.took is False


def test_an_unliftable_ask_is_not_a_take(wp7: ModuleType) -> None:
    """Liftability is qty=1 L0-fillable; a zero-size L0 is not a price."""
    tape = _tape(wp7, "r70", 70, 71, [_instant(wp7, ts=1, hour=10, ask=0.10, ask_size=0.0)])
    trial = wp7.screen_station_day(
        station="SFO",
        climate_day=DAY,
        rungs=[tape],
        variant=_variant(wp7, "A1-B1-C1"),
        p_yes_by_rung={"r70": 0.90},
    )
    assert trial.took is False
    assert trial.reason == wp7.REASON_NO_LIFTABLE_QUOTE


def test_an_empty_bid_side_is_a_no_take_and_never_a_dropped_day(wp7: ModuleType) -> None:
    tape = _tape(wp7, "r70", 70, 71, [_instant(wp7, ts=1, hour=10, ask=0.90, ask_size=5.0)])
    trial = wp7.screen_station_day(
        station="SFO",
        climate_day=DAY,
        rungs=[tape],
        variant=_variant(wp7, "A1-B2-C1"),
        p_yes_by_rung={"r70": 0.10},
    )
    assert trial.no_bid_side is True
    assert trial.took is False
    # The day is STILL a trial -- it must reach the pooled cell.
    cell = wp7.PooledCell("A1-B2-C1", (trial,))
    assert len(cell.trials) == 1


def test_the_no_leg_is_priced_off_the_inverted_yes_bid(wp7: ModuleType) -> None:
    tape = _tape(
        wp7,
        "r70",
        70,
        71,
        [_instant(wp7, ts=1, hour=10, ask=0.95, ask_size=5.0, bid=0.20, bid_size=5.0)],
    )
    trial = wp7.screen_station_day(
        station="SFO",
        climate_day=DAY,
        rungs=[tape],
        variant=_variant(wp7, "A1-B2-C1"),
        p_yes_by_rung={"r70": 0.05},
    )
    assert trial.side == "NO"
    assert trial.ask == pytest.approx(0.80)
    assert trial.no_bid_side is False


def test_the_same_day_is_a_no_take_when_the_variant_is_yes_only(wp7: ModuleType) -> None:
    tape = _tape(
        wp7,
        "r70",
        70,
        71,
        [_instant(wp7, ts=1, hour=10, ask=0.95, ask_size=5.0, bid=0.20, bid_size=5.0)],
    )
    trial = wp7.screen_station_day(
        station="SFO",
        climate_day=DAY,
        rungs=[tape],
        variant=_variant(wp7, "A1-B1-C1"),
        p_yes_by_rung={"r70": 0.05},
    )
    assert trial.took is False


def test_c2_screens_the_live_ask_against_the_pre_window_ask(wp7: ModuleType) -> None:
    """The ask must have come DOWN since before the window to qualify."""
    instants = [
        _instant(wp7, ts=1, hour=8, ask=0.40, ask_size=5.0),  # pre-window reference
        _instant(wp7, ts=2, hour=10, ask=0.30, ask_size=5.0),  # repriced cheaper
    ]
    tape = _tape(wp7, "r70", 70, 71, instants)
    assert wp7.screen_station_day(
        station="SFO", climate_day=DAY, rungs=[tape],
        variant=_variant(wp7, "A1-B1-C2"), p_yes_by_rung={"r70": 0.60},
    ).took is True

    unmoved = _tape(
        wp7,
        "r70",
        70,
        71,
        [
            _instant(wp7, ts=1, hour=8, ask=0.30, ask_size=5.0),
            _instant(wp7, ts=2, hour=10, ask=0.30, ask_size=5.0),
        ],
    )
    assert wp7.screen_station_day(
        station="SFO", climate_day=DAY, rungs=[unmoved],
        variant=_variant(wp7, "A1-B1-C2"), p_yes_by_rung={"r70": 0.60},
    ).took is False


def test_a_missing_model_probability_is_a_trial_not_a_guess(wp7: ModuleType) -> None:
    tape = _tape(wp7, "r70", 70, 71, [_instant(wp7, ts=1, hour=10, ask=0.10, ask_size=5.0)])
    trial = wp7.screen_station_day(
        station="SFO",
        climate_day=DAY,
        rungs=[tape],
        variant=_variant(wp7, "A1-B1-C1"),
        p_yes_by_rung=None,
    )
    assert trial.took is False
    assert trial.margin is None
    assert trial.reason == wp7.REASON_NO_MODEL_PROBABILITY


# ---------------------------------------------------------------------------
# §1(ii) -- Holm-Bonferroni across the entire set
# ---------------------------------------------------------------------------


def test_holm_refuses_a_family_smaller_than_the_enumerated_set(wp7: ModuleType) -> None:
    with pytest.raises(ValueError, match="entire enumerated set"):
        wp7.holm_bonferroni({"A1-B1-C1": 0.001})


def test_holm_step_down_thresholds_are_alpha_over_k_minus_rank(wp7: ModuleType) -> None:
    p_values = {v.variant_id: 0.5 for v in wp7.ALL_VARIANTS}
    smallest = wp7.ALL_VARIANTS[0].variant_id
    p_values[smallest] = 0.0001
    out = wp7.holm_bonferroni(p_values)
    assert out[smallest]["threshold"] == pytest.approx(0.05 / 12)
    assert out[smallest]["rejected"] is True
    assert sum(1 for v in out.values() if v["rejected"]) == 1


def test_an_insufficient_data_cell_carries_p_one_and_stays_in_the_family(
    wp7: ModuleType,
) -> None:
    thin = wp7.evaluate_gate(wp7.PooledCell("A3-B2-C2", (_trial(wp7),)))
    assert thin.verdict == wp7.VERDICT_INSUFFICIENT_DATA
    assert wp7.variant_p_value(thin) == 1.0
