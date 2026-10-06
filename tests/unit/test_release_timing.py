"""F13 Phase B0/B1 release-timing primitives (pure; plan r3 + r3.1 R14/R16/R26).

No network, no catalog, no model or outcome value: every input is a literal.
"""

from __future__ import annotations

import ast
import datetime as dt
import math
from pathlib import Path
from statistics import NormalDist

import pytest

from breezy.analysis import release_timing as rt

_NS = 1_000_000_000
_MODULE = Path(rt.__file__)


def _q(rung: str, value: float, bid: float | None, ask: float | None) -> rt.RungQuote:
    return rt.RungQuote(rung, value, bid, ask)


# --------------------------------------------------------------- matched panel


def test_matched_panel_defined_at_t_only_missing_t_plus_delta_is_dropout() -> None:
    at_t = {"A": _q("A", 70.5, 0.20, 0.30), "B": _q("B", 71.5, 0.40, 0.50)}
    at_t_plus = {"A": _q("A", 70.5, 0.25, 0.35)}  # B missing at t+delta

    panel = rt.build_matched_panel(at_t, at_t_plus)

    assert [r.rung_id for r in panel.rungs] == ["A", "B"]  # B stays in the panel
    assert panel.dropout_rungs == ("B",)
    assert panel.dropout_count == 1
    by_id = {r.rung_id: r for r in panel.rungs}
    assert by_id["B"].carried_forward is True
    assert by_id["B"].p_t_plus == pytest.approx(0.45)  # last quote carried, not renormalised
    assert by_id["A"].p_t_plus == pytest.approx(0.30)


def test_rung_one_sided_at_t_plus_delta_is_dropout_and_carried() -> None:
    at_t = {"A": _q("A", 70.5, 0.20, 0.30)}
    at_t_plus = {"A": _q("A", 70.5, None, 0.35)}

    panel = rt.build_matched_panel(at_t, at_t_plus)

    assert panel.dropout_rungs == ("A",)
    assert panel.rungs[0].p_t_plus == pytest.approx(0.25)


def test_empty_bid_rungs_excluded_and_counted() -> None:
    at_t = {"A": _q("A", 70.5, 0.20, 0.30), "C": _q("C", 72.5, None, 0.10)}

    panel = rt.build_matched_panel(at_t, at_t)

    assert [r.rung_id for r in panel.rungs] == ["A"]
    assert panel.empty_side_excluded == ("C",)
    assert panel.empty_side_count == 1


def test_panel_membership_ignores_rungs_that_only_appear_at_t_plus() -> None:
    at_t = {"A": _q("A", 70.5, 0.20, 0.30)}
    at_t_plus = {"A": _q("A", 70.5, 0.20, 0.30), "Z": _q("Z", 90.5, 0.1, 0.2)}

    panel = rt.build_matched_panel(at_t, at_t_plus)

    assert [r.rung_id for r in panel.rungs] == ["A"]


def test_ladder_implied_mean_is_not_renormalised() -> None:
    at_t = {"A": _q("A", 70.0, 0.20, 0.20), "B": _q("B", 72.0, 0.30, 0.30)}
    panel = rt.build_matched_panel(at_t, at_t)

    # 0.2*70 + 0.3*72 = 35.6 ; dividing by the 0.5 mass would give 71.2.
    assert rt.ladder_implied_mean(panel, "t") == pytest.approx(35.6)


def test_signed_change_is_t_plus_minus_t_and_carries_dropouts_flat() -> None:
    at_t = {"A": _q("A", 70.0, 0.20, 0.20), "B": _q("B", 72.0, 0.30, 0.30)}
    at_t_plus = {"A": _q("A", 70.0, 0.30, 0.30)}  # B dropped out -> carried at 0.30

    panel = rt.build_matched_panel(at_t, at_t_plus)

    assert rt.signed_change(panel) == pytest.approx((0.30 - 0.20) * 70.0)
    at_t_plus_down = {"A": _q("A", 70.0, 0.10, 0.10), "B": _q("B", 72.0, 0.30, 0.30)}
    assert rt.signed_change(rt.build_matched_panel(at_t, at_t_plus_down)) < 0


def test_regressor_is_source_value_minus_pre_release_ladder_implied_mean() -> None:
    at_t = {"A": _q("A", 70.0, 0.50, 0.50), "B": _q("B", 72.0, 0.50, 0.50)}
    panel = rt.build_matched_panel(at_t, at_t)
    pre_mean = rt.ladder_implied_mean(panel, "t")

    assert rt.regressor(73.0, pre_mean) == pytest.approx(73.0 - 71.0)


def test_empty_panel_has_no_mean() -> None:
    panel = rt.build_matched_panel({}, {})
    with pytest.raises(ValueError, match="empty panel"):
        rt.ladder_implied_mean(panel, "t")


# ------------------------------------------------------------------- bootstrap


def _events(slope: float, days: int = 10, per_day: int = 2) -> list[rt.EventObservation]:
    out = []
    for d in range(days):
        for k in range(per_day):
            x = float(d * per_day + k) - 5.0
            out.append(rt.EventObservation(dt.date(2026, 9, 1 + d), x, slope * x))
    return out


def test_slope_is_ols_through_the_data() -> None:
    assert rt.ols_slope([1.0, 2.0, 3.0], [2.0, 4.0, 6.0]) == pytest.approx(2.0)


def test_ols_slope_refuses_zero_regressor_variance() -> None:
    with pytest.raises(ValueError, match="variance"):
        rt.ols_slope([1.0, 1.0], [1.0, 2.0])


def test_b1_slope_ci_is_day_block_bootstrap() -> None:
    result = rt.day_block_bootstrap_slope_ci(_events(2.0), n_boot=200, alpha=0.05, seed=7)

    assert result.slope == pytest.approx(2.0)
    assert result.lo == pytest.approx(2.0)
    assert result.hi == pytest.approx(2.0)
    assert result.n_days == 10
    assert result.n_events == 20
    assert result.n_boot == 200


def test_bootstrap_resamples_whole_climate_days_not_events() -> None:
    events = [
        rt.EventObservation(dt.date(2026, 9, 1), 0.0, 0.0),
        rt.EventObservation(dt.date(2026, 9, 1), 1.0, 1.0),
        rt.EventObservation(dt.date(2026, 9, 2), 0.0, 0.0),
        rt.EventObservation(dt.date(2026, 9, 2), 1.0, 3.0),
    ]
    picked: list[list[dt.date]] = []

    class _Rng:
        def choices(self, population: list[dt.date], k: int) -> list[dt.date]:
            picked.append([population[1], population[1]])  # day 2 twice
            return picked[-1]

    result = rt.day_block_bootstrap_slope_ci(events, n_boot=1, alpha=0.5, seed=0, rng=_Rng())

    assert picked == [[dt.date(2026, 9, 2), dt.date(2026, 9, 2)]]
    assert result.lo == pytest.approx(3.0)  # both blocks are the day-2 pair: slope 3
    assert result.hi == pytest.approx(3.0)


def test_bootstrap_is_deterministic_for_a_seed_and_widens_with_noise() -> None:
    noisy = [
        rt.EventObservation(e.day, e.regressor, e.change + (0.9 if i % 3 == 0 else -0.4))
        for i, e in enumerate(_events(1.0))
    ]
    a = rt.day_block_bootstrap_slope_ci(noisy, n_boot=300, alpha=0.05, seed=11)
    b = rt.day_block_bootstrap_slope_ci(noisy, n_boot=300, alpha=0.05, seed=11)
    assert a == b
    assert a.lo < a.slope < a.hi


def test_bootstrap_needs_two_days() -> None:
    with pytest.raises(ValueError, match="at least 2"):
        rt.day_block_bootstrap_slope_ci(_events(1.0, days=1), n_boot=10, alpha=0.05, seed=1)


# ------------------------------------------------------------------ Holm / MDE


@pytest.mark.parametrize(("nbp_present", "size"), [(True, 2), (False, 1)])
def test_holm_family_size_equals_b0_fixed_size_1_or_2_at_alpha_0_025(
    nbp_present: bool, size: int
) -> None:
    assert rt.holm_family_size(nbp_vintages_present=nbp_present) == size
    assert rt.ALPHA == 0.025


def test_holm_reject_steps_down_with_family_size_two() -> None:
    assert rt.holm_reject([0.01, 0.03], alpha=0.025) == (True, False)  # .01<=.0125, .03>.025
    assert rt.holm_reject([0.012, 0.024], alpha=0.025) == (True, True)
    assert rt.holm_reject([0.02, 0.2], alpha=0.025) == (False, False)
    assert rt.holm_reject([0.4], alpha=0.025) == (False,)
    assert rt.holm_reject([0.02], alpha=0.025) == (True,)


def test_holm_reject_preserves_input_order() -> None:
    assert rt.holm_reject([0.2, 0.001], alpha=0.025) == (False, True)


def test_mde_formula_is_z_alpha_plus_z_beta_times_sd_over_sqrt_n_eff() -> None:
    z = NormalDist().inv_cdf
    expected = (z(1 - 0.025) + z(0.8)) * 2.0 / math.sqrt(100)

    assert rt.mde(sd=2.0, n_eff=100, family_size=1) == pytest.approx(expected)


def test_mde_family_size_two_tightens_alpha_by_holm_first_step() -> None:
    z = NormalDist().inv_cdf
    expected = (z(1 - 0.025 / 2) + z(0.8)) * 2.0 / math.sqrt(100)

    assert rt.mde(sd=2.0, n_eff=100, family_size=2) == pytest.approx(expected)
    assert rt.mde(sd=2.0, n_eff=100, family_size=2) > rt.mde(sd=2.0, n_eff=100, family_size=1)


@pytest.mark.parametrize("bad", [0, -1, float("nan")])
def test_mde_refuses_non_positive_n_eff(bad: float) -> None:
    with pytest.raises(ValueError, match="n_eff"):
        rt.mde(sd=1.0, n_eff=bad, family_size=1)


def test_mde_refuses_family_size_outside_one_or_two() -> None:
    with pytest.raises(ValueError, match="family_size"):
        rt.mde(sd=1.0, n_eff=10, family_size=3)


def test_effective_n_clusters_by_climate_day() -> None:
    assert rt.effective_n([4, 4, 4]) == pytest.approx(3.0)  # fully clustered: the day count
    assert rt.effective_n([4, 4, 4], icc=0.0) == pytest.approx(12.0)
    assert rt.effective_n([2, 2], icc=0.5) == pytest.approx(4 / 1.5)
    assert rt.effective_n([]) == 0.0


def test_b0_sd_taken_from_placebo_and_pre_window_arms() -> None:
    sd = rt.pooled_sd({"placebo": [1.0, -1.0], "pre_window": [2.0, -2.0], "post": [100.0]})

    # only the placebo and pre-window arms contribute, never the post-release arm
    assert sd == pytest.approx(math.sqrt((1 + 1 + 4 + 4) / 3))
    with pytest.raises(ValueError, match="placebo"):
        rt.pooled_sd({"post": [1.0, 2.0]})
    with pytest.raises(ValueError, match="at least 2"):
        rt.pooled_sd({"placebo": [1.0], "pre_window": []})


def test_b0_stops_underpowered_when_mde_exceeds_plausible_slope() -> None:
    assert rt.is_underpowered(mde_value=0.5, plausible_effect=0.4) is True
    assert rt.is_underpowered(mde_value=0.4, plausible_effect=0.4) is False
    assert rt.is_underpowered(mde_value=0.4, plausible_effect=None) is None


# ----------------------------------------------------------- 50 % of the move


def test_time_to_half_move_uses_first_crossing_in_the_move_direction() -> None:
    t0 = 1_000 * _NS
    series = [
        (t0 + 10 * _NS, 70.0),
        (t0 + 30 * _NS, 70.4),
        (t0 + 90 * _NS, 70.9),
        (t0 + 3600 * _NS, 71.0),
    ]

    assert rt.time_to_fraction_of_move(series, t0, 70.0) == pytest.approx(90.0)


def test_time_to_half_move_handles_a_downward_move() -> None:
    t0 = 0
    series = [(20 * _NS, 70.0), (40 * _NS, 69.4), (3600 * _NS, 69.0)]

    assert rt.time_to_fraction_of_move(series, t0, 70.0) == pytest.approx(40.0)


def test_time_to_half_move_is_none_for_no_move_or_below_the_minimum_move() -> None:
    flat = [(5 * _NS, 70.0), (3600 * _NS, 70.0)]
    assert rt.time_to_fraction_of_move(flat, 0, 70.0) is None
    small = [(5 * _NS, 70.1), (3600 * _NS, 70.2)]
    assert rt.time_to_fraction_of_move(small, 0, 70.0, min_move=0.5) is None
    assert rt.time_to_fraction_of_move([], 0, 70.0) is None


# ----------------------------------------------------------------- cadence


def test_cadence_summary_reports_gaps_in_seconds() -> None:
    ts = [i * 10 * _NS for i in range(7)]  # 10 s cadence

    summary = rt.cadence_summary(ts)

    assert summary.n_rows == 7
    assert summary.median_gap_s == pytest.approx(10.0)
    assert summary.p90_gap_s == pytest.approx(10.0)
    assert summary.max_gap_s == pytest.approx(10.0)
    assert rt.resolves_resolution(summary, resolution_s=60) is True


def test_b0_reports_whether_depth10_cadence_resolves_60s() -> None:
    sparse = rt.cadence_summary([i * 300 * _NS for i in range(10)])  # 5 min cadence
    assert rt.resolves_resolution(sparse, resolution_s=60) is False
    assert rt.resolves_resolution(rt.cadence_summary([0]), resolution_s=60) is False
    assert rt.cadence_summary([]).n_rows == 0


# ------------------------------------------------------------- placebo pools


def test_placebo_same_clock_time_on_no_update_days() -> None:
    days = [dt.date(2026, 9, d) for d in (1, 2, 3, 4)]
    clock = 12 * 3600 + 51 * 60  # 12:51Z
    releases = [
        int(dt.datetime(2026, 9, d, 12, 51, tzinfo=dt.UTC).timestamp()) * _NS for d in (1, 2)
    ]

    pool = rt.same_clock_placebo_days(clock, releases, days, tolerance_s=300)

    assert pool == (dt.date(2026, 9, 3), dt.date(2026, 9, 4))


def test_empty_pfm_pool_is_empty_when_a_release_occurs_every_day() -> None:
    days = [dt.date(2026, 9, d) for d in (1, 2)]
    releases = [
        int(dt.datetime(2026, 9, d, 12, 51, tzinfo=dt.UTC).timestamp()) * _NS for d in (1, 2)
    ]
    assert rt.same_clock_placebo_days(12 * 3600 + 51 * 60, releases, days, tolerance_s=300) == ()


def test_placebo_matched_on_metar_minute_offset() -> None:
    day = dt.date(2026, 9, 1)
    release = int(dt.datetime(2026, 9, 1, 12, 51, tzinfo=dt.UTC).timestamp()) * _NS

    cands = rt.metar_offset_placebo_instants(
        minute_of_hour=51, releases_ns=[release], days=[day], exclusion_s=3600
    )

    hours = sorted(dt.datetime.fromtimestamp(t / _NS, tz=dt.UTC).hour for t in cands)
    assert all(dt.datetime.fromtimestamp(t / _NS, tz=dt.UTC).minute == 51 for t in cands)
    assert 12 not in hours and 11 not in hours and 13 not in hours  # +-60 min of the release
    assert hours[0] == 0 and hours[-1] == 23
    assert len(hours) == 21


# ----------------------------------------------------------------- purity


def test_module_is_pure_no_io_network_catalog_or_outcome_imports() -> None:
    tree = ast.parse(_MODULE.read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    forbidden = {"nautilus_trader", "httpx", "requests", "socket", "urllib", "pyarrow", "breezy"}
    assert not imported & forbidden


def test_event_study_uses_no_champion_output_cli_or_outcome_values() -> None:
    text = _MODULE.read_text().lower()
    for word in ("settle", "tmax", "champion", "cli_value", "outcome_f"):
        assert word not in text
