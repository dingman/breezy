"""MAKER design scoring: the per-fill X formula, the truth join, the writer shape, n_eff, the
day-block bootstrap wiring and the verdict label. Synthetic positions only; no capture."""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

import numpy as np
import pytest

from scripts.analysis import maker_design_score as sc
from scripts.analysis.maker_stage0_runio import PositionSeed

GRID = sc.Grid(theta=(0.0695, 0.08), slip=(0.01, 0.02))
FIRST_DAY, LAST_DAY = dt.date(2026, 9, 18), dt.date(2026, 10, 13)
NO_WINS = {("LAX", dt.date(2026, 10, 2)): 70}  # tmax 70F
RUNG_ABOVE = "tc-temp-laxhigh-2026-10-02-gte86f.POLYMARKET_US"  # NO wins at 70F
RUNG_AROUND = "tc-temp-laxhigh-2026-10-02-gte70lt71f.POLYMARKET_US"  # YES wins at 70F


def _seed(
    rung: str = RUNG_ABOVE, *, bid: float = 0.8, base: bool = True, stress: bool = True,
    station: str = "LAX", day: str = "2026-10-02",
) -> PositionSeed:  # fmt: skip
    return PositionSeed(station, day, "CONTRACTS", rung, bid, base, stress, None)


# --- X -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("win", "bid_c", "theta", "slip", "expected"),
    [
        (True, 80, 0.0695, 0.01, 0.18),  # fee round(0.0695*0.8*0.2 = 0.01112) = 0.01
        (True, 80, 0.0695, 0.02, 0.17),
        (True, 80, 0.08, 0.01, 0.18),  # 0.0128 -> 0.01
        (False, 80, 0.0695, 0.01, -0.82),
        (True, 84, 0.0695, 0.01, 0.14),
        (True, 70, 0.0695, 0.01, 0.28),  # 0.0695*0.7*0.3 = 0.0146 -> 0.01
        (True, 50, 0.1, 0.0, 0.48),  # 0.025 is a half-cent tie: banker's rounding gives 0.02
        (True, 50, 0.12, 0.0, 0.47),  # 0.03 exactly
    ],
)
def test_x_is_win_minus_bid_plus_half_even_cent_fee_plus_slip(
    win: bool, bid_c: int, theta: float, slip: float, expected: float
) -> None:
    assert sc.x_value(win=win, bid_cents=bid_c, theta=theta, slip=slip) == pytest.approx(expected)


def test_x_refuses_a_bid_outside_the_open_unit_interval() -> None:
    for bad in (0, 100, -5):
        with pytest.raises(ValueError, match="bid"):
            sc.x_value(win=True, bid_cents=bad, theta=0.0695, slip=0.01)


def test_grid_names_are_stable_and_ordered_theta_major() -> None:
    assert GRID.cells == (
        sc.Cell(0.0695, 0.01), sc.Cell(0.0695, 0.02), sc.Cell(0.08, 0.01), sc.Cell(0.08, 0.02),
    )  # fmt: skip
    assert [c.name for c in GRID.cells] == [
        "x_t0.0695_s0.01", "x_t0.0695_s0.02", "x_t0.08_s0.01", "x_t0.08_s0.02",
    ]  # fmt: skip
    assert GRID.base == sc.Cell(0.0695, 0.01)
    assert GRID.tick_stress == sc.Cell(0.0695, 0.02)
    assert GRID.fee_stress == sc.Cell(0.08, 0.01)


# --- truth and the rows ----------------------------------------------------------------------


def _truth_file(tmp_path: Path, rows: list[tuple[str, str, str, str, str]]) -> Path:
    path = tmp_path / "truth.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["station", "city", "climate_day", "tmax_f", "tmax_flag", "correction_flag",
             "issued_at_utc", "product_sha256", "revision_fetch_date", "revision_sha256"]
        )  # fmt: skip
        for station, day, tmax, flag, corrected in rows:
            writer.writerow([station, station, day, tmax, flag, corrected, "", "", "", ""])
    return path


def test_truth_reads_only_the_fenced_maker_station_days(tmp_path: Path) -> None:
    path = _truth_file(
        tmp_path,
        [
            ("LAX", "2026-10-02", "70", "", "False"),
            ("MDW", "2026-01-18", "40", "M", "False"),  # before the range: never even validated
            ("NYC", "2026-10-02", "55", "", "False"),  # not a maker station
            ("LAX", "2026-10-14", "99", "", "False"),  # second-look block: never loaded
            ("MIA", "2026-10-03", "", "", "False"),  # no FINAL value
        ],
    )
    truth = sc.load_truth(path, ("LAX", "MIA"), days=(FIRST_DAY, LAST_DAY))
    assert truth == {("LAX", dt.date(2026, 10, 2)): 70}


def test_truth_refuses_a_flagged_value(tmp_path: Path) -> None:
    path = _truth_file(tmp_path, [("LAX", "2026-10-02", "70", "M", "False")])
    with pytest.raises(ValueError, match="flag"):
        sc.load_truth(path, ("LAX",), days=(FIRST_DAY, LAST_DAY))


def test_position_rows_carry_win_and_x_only_for_stress_pass_fills() -> None:
    seeds = [
        _seed(RUNG_ABOVE),  # NO wins
        _seed(RUNG_AROUND),  # NO loses
        _seed(RUNG_ABOVE, stress=False, base=False),  # rested, never filled
    ]
    rows = sc.position_rows(seeds, NO_WINS, GRID)
    assert [r["win"] for r in rows] == [True, False, True]
    assert rows[0]["x_t0.0695_s0.01"] == pytest.approx(0.18)
    assert rows[1]["x_t0.0695_s0.01"] == pytest.approx(-0.82)
    assert rows[2]["x_t0.0695_s0.01"] is None  # not a stress-pass fill: no X
    assert [r["stress_pass"] for r in rows] == [True, True, False]
    assert [r["filled"] for r in rows] == [True, True, False]


def test_position_row_without_a_final_has_no_win_and_no_x() -> None:
    (row,) = sc.position_rows([_seed(day="2026-10-05")], NO_WINS, GRID)
    assert row["win"] is None
    assert row["x_t0.0695_s0.01"] is None


def test_position_csv_has_the_documented_columns_in_order(tmp_path: Path) -> None:
    rows = sc.position_rows([_seed()], NO_WINS, GRID)
    path = sc.write_rows(tmp_path / "positions.csv", sc.position_columns(GRID), rows)
    with path.open(encoding="utf-8", newline="") as handle:
        read = list(csv.DictReader(handle))
    assert list(read[0]) == [
        "arm", "station", "climate_day", "rung", "bid", "filled", "stress_pass", "win",
        "x_t0.0695_s0.01", "x_t0.0695_s0.02", "x_t0.08_s0.01", "x_t0.08_s0.02",
    ]  # fmt: skip
    assert read[0]["station"] == "LAX"
    assert read[0]["bid"] == "0.8"
    assert read[0]["stress_pass"] == "True"
    assert float(read[0]["x_t0.0695_s0.01"]) == pytest.approx(0.18)


def test_position_rows_take_the_arm_name_when_given() -> None:
    (row,) = sc.position_rows([_seed()], NO_WINS, GRID, arm="nbp_deep")
    assert row["arm"] == "nbp_deep"


# --- n_eff and the bootstrap -----------------------------------------------------------------


def test_n_eff_uses_the_assumed_rho_of_one_half_per_date() -> None:
    per_date = {dt.date(2026, 10, 2): 1, dt.date(2026, 10, 3): 2, dt.date(2026, 10, 4): 3}
    assert sc.n_eff(per_date) == pytest.approx(1 + 2 / 1.5 + 3 / 2)
    assert sc.n_eff({}) == 0.0


def _fills(n_days: int, per_day: int, *, win_every: int) -> list[dict[str, object]]:
    """``per_day`` stress fills on each of ``n_days`` dates; every ``win_every``-th fill loses."""
    rows: list[dict[str, object]] = []
    stations = ("LAX", "MDW", "MIA", "SFO")
    k = 0
    for d in range(n_days):
        day = dt.date(2026, 10, 2) + dt.timedelta(days=d)
        for _ in range(per_day):
            k += 1
            win = k % win_every != 0
            x = {
                c.name: sc.x_value(win=win, bid_cents=80, theta=c.theta, slip=c.slip)
                for c in GRID.cells
            }
            rows.append(
                {
                    "station": stations[k % 4], "climate_day": day.isoformat(), "stress_pass": True,
                    "win": win, **x,
                }
            )  # fmt: skip
    return rows


def _days(n: int) -> list[dt.date]:
    return [dt.date(2026, 10, 2) + dt.timedelta(days=d) for d in range(n)]


def test_stats_count_fills_wins_and_sum_x_per_cell() -> None:
    rows = _fills(10, 2, win_every=5)  # 20 fills, 4 losses
    stats = sc.arm_stats(rows, GRID, days=_days(10))
    assert stats["fills"] == 20
    assert stats["wins"] == 16
    base = stats["cells"]["x_t0.0695_s0.01"]
    assert base["sum_x"] == pytest.approx(16 * 0.18 + 4 * -0.82)
    assert base["mean_x"] == pytest.approx(base["sum_x"] / 20)
    assert stats["n_station_days"] == len({(r["station"], r["climate_day"]) for r in rows})
    assert stats["n_days"] == 10
    assert stats["n_eff"] == pytest.approx(10 * 2 / 1.5)


def test_stats_station_share_is_the_largest_station_part_of_the_total() -> None:
    rows = _fills(8, 1, win_every=99)
    for row in rows:
        row["station"] = "LAX"
    stats = sc.arm_stats(rows, GRID, days=_days(8))
    assert stats["station_share"] == pytest.approx(1.0)


def test_bootstrap_matches_the_market_calibration_scan_function_and_its_pinned_seed() -> None:
    from breezy.settlement.roi_bound import B_RESAMPLES, SEED
    from scripts.analysis.market_calibration_scan import _bootstrap_stats

    rows = _fills(12, 2, win_every=7)
    stats = sc.arm_stats(rows, GRID, days=_days(12))
    assert stats["resamples"] == B_RESAMPLES == 10_000
    assert stats["seed"] == SEED == 20260904
    s = np.zeros((12, 1))
    n = np.zeros((12, 1))
    for row in rows:
        i = (dt.date.fromisoformat(str(row["climate_day"])) - dt.date(2026, 10, 2)).days
        s[i, 0] += float(row["x_t0.0695_s0.01"])  # type: ignore[arg-type]
        n[i, 0] += 1
    ref = _bootstrap_stats(s, n, B_RESAMPLES, SEED)
    cell = stats["cells"]["x_t0.0695_s0.01"]
    assert cell["mean_x"] == pytest.approx(float(ref.observed[0]))
    assert cell["boot_se"] == pytest.approx(float(ref.se[0]))
    assert cell["boot_p"] == pytest.approx(float(ref.p_cell[0]))


def test_lower_bound_is_the_alpha_quantile_of_the_same_resampled_ratios() -> None:
    rows = _fills(30, 2, win_every=1_000)  # every fill wins: X > 0 everywhere
    stats = sc.arm_stats(rows, GRID, days=_days(30))
    cell = stats["cells"]["x_t0.0695_s0.01"]
    assert stats["alpha"] == 0.00625
    assert cell["lb"] == pytest.approx(0.18)  # no variance: every resample has the same ratio
    assert cell["lb"] <= cell["mean_x"]


def test_a_noisy_edge_has_a_lower_bound_below_its_point_estimate() -> None:
    rows = _fills(30, 2, win_every=10)  # 60 fills, 6 losses: a positive mean with real spread
    cell = sc.arm_stats(rows, GRID, days=_days(30))["cells"]["x_t0.0695_s0.01"]
    assert 0 < cell["mean_x"]
    assert cell["lb"] < cell["mean_x"]


def test_stats_with_no_fills_report_zero_and_skip_the_bootstrap() -> None:
    stats = sc.arm_stats([], GRID, days=_days(5))
    assert stats["fills"] == 0
    assert stats["n_eff"] == 0.0
    assert stats["cells"]["x_t0.0695_s0.01"]["lb"] is None
    assert stats["cells"]["x_t0.0695_s0.01"]["mean_x"] is None


def test_stats_ignore_positions_that_are_not_scored_fills() -> None:
    rows = _fills(3, 1, win_every=99)
    rows.append({"station": "LAX", "climate_day": "2026-10-02", "stress_pass": False, "win": True})
    rows.append({"station": "LAX", "climate_day": "2026-10-02", "stress_pass": True, "win": None})
    assert sc.arm_stats(rows, GRID, days=_days(3))["fills"] == 3


# --- the label -------------------------------------------------------------------------------


def _stats(
    *, n_eff: float = 40.0, share: float = 0.3, base: tuple[float, float] = (0.05, 0.02),
    tick: float = 0.01, fee: float = 0.01,
) -> dict[str, object]:  # fmt: skip
    def cell(mean: float, lb: float | None) -> dict[str, object]:
        return {"mean_x": mean, "lb": lb}

    return {
        "n_eff": n_eff,
        "station_share": share,
        "cells": {
            "x_t0.0695_s0.01": cell(base[0], base[1]),
            "x_t0.0695_s0.02": cell(base[0] - 0.01, tick),
            "x_t0.08_s0.01": cell(base[0] - 0.01, fee),
            "x_t0.08_s0.02": cell(base[0] - 0.02, 0.0),
        },
    }


@pytest.mark.parametrize(
    ("stats", "valid", "expected"),
    [
        (_stats(), True, "PASS-CANDIDATE"),
        (_stats(), False, "INVALID"),  # a control that failed to reproduce Stage 0
        (_stats(n_eff=29.99), True, "UNDERPOWERED"),
        (_stats(n_eff=30.0), True, "PASS-CANDIDATE"),
        (_stats(n_eff=10.0), False, "INVALID"),  # invalid outranks underpowered
        (_stats(base=(0.05, -0.001)), True, "NO-EDGE"),  # LB not above zero
        (_stats(base=(0.005, 0.001)), True, "NO-EDGE"),  # point below one cent
        (_stats(share=0.51), True, "NO-EDGE"),
        (_stats(share=0.50), True, "PASS-CANDIDATE"),
        (_stats(tick=-0.002), True, "NO-EDGE"),  # does not survive +1 tick
        (_stats(fee=-0.002), True, "NO-EDGE"),  # does not survive theta 0.08
    ],
)
def test_label_follows_the_fence_paragraph(
    stats: dict[str, object], valid: bool, expected: str
) -> None:
    assert sc.label(stats, GRID, valid=valid) == expected


def test_label_without_a_lower_bound_is_no_edge_once_powered() -> None:
    stats = _stats()
    cells = stats["cells"]
    assert isinstance(cells, dict)
    cells["x_t0.0695_s0.01"] = {"mean_x": None, "lb": None}
    assert sc.label(stats, GRID, valid=True) == "NO-EDGE"
