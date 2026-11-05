"""MAKER design scoring: per-fill X, the truth join, n_eff and the day-block bootstrap.

``X = win - (b + round_cent(theta * b * (1 - b)) + slip)`` per stress-pass fill, with the venue's
half-even cent rounding (``market_calibration_scan.venue_fee``) and the NO leg winning when the
rung's closed band does not contain the settled high. Truth is joined here and only here, after
the simulation has finished; the simulator never sees it.

Statistics reuse the repo's own pieces: ``n_eff_gov`` (rho 0.5 per date), and
``market_calibration_scan._bootstrap_stats`` (day-block ratio-of-sums, ``roi_bound``'s pinned
resample count and seed). ``_bootstrap_stats`` returns the observed ratio, its standard error and
the one-sided bootstrap p but not the resampled ratios, so the lower bound at ``ALPHA`` replays the
same multinomial draw (same seed, same count) to take the quantile.
"""

from __future__ import annotations

import csv
import datetime as dt
from collections import Counter, defaultdict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import numpy as np

from breezy.analysis.labeling.instrument_facts import bucket_facts_from_instrument_id
from breezy.settlement.roi_bound import B_RESAMPLES, SEED
from scripts.analysis.maker_stage0_inputs import is_underpowered, n_eff_gov
from scripts.analysis.maker_stage0_runio import PositionSeed
from scripts.analysis.market_calibration_scan import _bootstrap_stats, venue_fee

__all__ = [
    "ALPHA",
    "Cell",
    "Grid",
    "arm_stats",
    "label",
    "load_truth",
    "n_eff",
    "position_columns",
    "position_rows",
    "write_rows",
    "x_value",
]

ALPHA: Final[float] = 0.00625
MIN_POINT: Final[float] = 0.01
MAX_STATION_SHARE: Final[float] = 0.5
_CENTS: Final[int] = 100
Key = tuple[str, dt.date]


@dataclass(frozen=True, slots=True)
class Cell:
    theta: float
    slip: float

    @property
    def name(self) -> str:
        return f"x_t{self.theta}_s{self.slip}"


@dataclass(frozen=True, slots=True)
class Grid:
    """theta x slip cells, theta-major; the first value of each is the base, the second a stress."""

    theta: tuple[float, ...]
    slip: tuple[float, ...]

    @property
    def cells(self) -> tuple[Cell, ...]:
        return tuple(Cell(t, s) for t in self.theta for s in self.slip)

    @property
    def base(self) -> Cell:
        return Cell(self.theta[0], self.slip[0])

    @property
    def tick_stress(self) -> Cell:
        return Cell(self.theta[0], self.slip[1])

    @property
    def fee_stress(self) -> Cell:
        return Cell(self.theta[1], self.slip[0])


def x_value(*, win: bool, bid_cents: int, theta: float, slip: float) -> float:
    if not 0 < bid_cents < _CENTS:
        raise ValueError(f"bid {bid_cents} is outside 1..99 cents")
    price = Decimal(bid_cents) / _CENTS
    cost = price + venue_fee(price, Decimal(str(theta))) + Decimal(str(slip))
    return float(Decimal(int(win)) - cost)


def load_truth(
    path: Path, stations: Collection[str], *, days: tuple[dt.date, dt.date]
) -> dict[Key, int]:
    """CLI FINAL highs for ``stations`` within ``days`` (first, last); other days are skipped
    before they are validated, so a day beyond the fence is never loaded."""
    truth: dict[Key, int] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            day = dt.date.fromisoformat(row["climate_day"])
            outside = not days[0] <= day <= days[1]
            if row["station"] not in stations or outside or not row["tmax_f"].strip():
                continue
            if row["tmax_flag"].strip() or row["correction_flag"].strip().lower() == "true":
                raise ValueError(f"{row['station']} {day}: flagged or corrected value in truth")
            key, tmax = (row["station"], day), int(row["tmax_f"])
            if truth.setdefault(key, tmax) != tmax:
                raise ValueError(f"{key}: conflicting truth rows")
    return truth


def position_columns(grid: Grid) -> list[str]:
    head = ["arm", "station", "climate_day", "rung", "bid", "filled", "stress_pass", "win"]
    return [*head, *(c.name for c in grid.cells)]


def position_rows(
    seeds: Sequence[PositionSeed], truth: Mapping[Key, int], grid: Grid, arm: str = ""
) -> list[dict[str, object]]:
    """One row per posted rung; ``win`` needs a truth row, X only a stress-pass fill with a win."""
    rows: list[dict[str, object]] = []
    for seed in seeds:
        tmax = truth.get((seed.station, dt.date.fromisoformat(seed.climate_day)))
        win: bool | None = None
        if tmax is not None:
            facts = bucket_facts_from_instrument_id(seed.rung_id)
            if facts is None:
                raise ValueError(f"{seed.rung_id} has no rung facts; cannot settle it")
            win = not facts.contains(tmax)
        scored = seed.filled_stress and win is not None
        xs = {
            c.name: x_value(
                win=bool(win), bid_cents=round(seed.bid * _CENTS), theta=c.theta, slip=c.slip
            )
            if scored
            else None
            for c in grid.cells
        }
        rows.append(
            {
                "arm": arm, "station": seed.station, "climate_day": seed.climate_day,
                "rung": seed.rung_id, "bid": seed.bid, "filled": seed.filled_base,
                "stress_pass": seed.filled_stress, "win": win, **xs,
            }
        )  # fmt: skip
    return rows


def write_rows(path: Path, columns: Sequence[str], rows: Sequence[Mapping[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        writer.writerows(rows)
    return path


def n_eff(per_date: Mapping[dt.date, int]) -> float:
    return float(n_eff_gov(per_date))


def _lower_bounds(s_mat: np.ndarray, n_mat: np.ndarray) -> np.ndarray:
    """The ``ALPHA`` quantile of the day-block ratio of sums (``_bootstrap_stats``' own draw)."""
    n_days = s_mat.shape[0]
    rng = np.random.default_rng(SEED)
    weights = rng.multinomial(n_days, np.full(n_days, 1.0 / n_days), size=B_RESAMPLES).astype(float)
    num, den = weights @ s_mat, weights @ n_mat
    observed = s_mat.sum(axis=0) / n_mat.sum(axis=0)
    boot = np.where(den > 0, num / np.where(den > 0, den, 1.0), observed)
    return np.asarray(np.quantile(boot, ALPHA, axis=0))


def _empty_cells(grid: Grid) -> dict[str, dict[str, Any]]:
    keys = ("sum_x", "mean_x", "boot_se", "boot_p", "lb")
    return {c.name: dict.fromkeys(keys) for c in grid.cells}


def arm_stats(
    rows: Sequence[Mapping[str, Any]], grid: Grid, *, days: Sequence[dt.date]
) -> dict[str, Any]:
    """Per-cell sums, means and bootstrap, n_eff and the station share of one arm's positions.

    ``days`` is the resampling population: every date on which the arm had a bid-bearing
    station-day, so a date without a fill still counts as a draw.
    """
    fills = [r for r in rows if r["stress_pass"] and r["win"] is not None]
    per_date = Counter(dt.date.fromisoformat(str(r["climate_day"])) for r in fills)
    population = sorted(set(days))
    stats: dict[str, Any] = {
        "fills": len(fills),
        "wins": sum(bool(r["win"]) for r in fills),
        "n_station_days": len({(r["station"], r["climate_day"]) for r in fills}),
        "n_days": len(per_date),
        "n_resampled_days": len(population),
        "n_eff": n_eff(per_date),
        "alpha": ALPHA,
        "resamples": B_RESAMPLES,
        "seed": SEED,
        "station_share": None,
        "cells": _empty_cells(grid),
    }
    if not fills:
        return stats
    names = [c.name for c in grid.cells]
    where = {d: i for i, d in enumerate(population)}
    s_mat = np.zeros((len(population), len(names)))
    n_mat = np.zeros_like(s_mat)
    by_station: dict[str, float] = defaultdict(float)
    for r in fills:
        i = where[dt.date.fromisoformat(str(r["climate_day"]))]
        s_mat[i] += [float(r[name]) for name in names]
        n_mat[i] += 1.0
        by_station[str(r["station"])] += float(r[names[0]])
    boot = _bootstrap_stats(s_mat, n_mat, B_RESAMPLES, SEED)
    lower = _lower_bounds(s_mat, n_mat)
    for j, name in enumerate(names):
        total = float(s_mat[:, j].sum())
        stats["cells"][name] = {
            "sum_x": total, "mean_x": total / len(fills), "boot_se": float(boot.se[j]),
            "boot_p": float(boot.p_cell[j]), "lb": float(lower[j]),
        }  # fmt: skip
    total = sum(by_station.values())
    stats["station_share"] = max(by_station.values()) / total if total > 0 else None
    stats["station_sums"] = dict(sorted(by_station.items()))
    return stats


def label(stats: Mapping[str, Any], grid: Grid, *, valid: bool) -> str:
    """INVALID, UNDERPOWERED (n_eff < 30), PASS-CANDIDATE or NO-EDGE (the fence paragraph)."""
    if not valid:
        return "INVALID"
    if is_underpowered(stats["n_eff"]):
        return "UNDERPOWERED"
    cells = stats["cells"]
    base = cells[grid.base.name]
    share = stats["station_share"]
    survives = all(
        (cells[c.name]["lb"] or 0.0) > 0 for c in (grid.base, grid.tick_stress, grid.fee_stress)
    )
    passed = (
        survives
        and base["mean_x"] >= MIN_POINT
        and share is not None
        and share <= MAX_STATION_SHARE
    )
    return "PASS-CANDIDATE" if passed else "NO-EDGE"
