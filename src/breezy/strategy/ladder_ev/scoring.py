"""Unified cost, EV, margin, ranking, Kelly (spec §4–§7)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date

from breezy.strategy.ladder_ev.config import LadderEvConfig
from breezy.strategy.weather_common.costs import DepthAwareTradeCost
from breezy.strategy.weather_common.risk import edge_after_costs

__all__ = [
    "OpportunityRow",
    "ev_net",
    "kelly_stake_fraction",
    "margin",
    "rank_rows",
    "unified_cost",
]


@dataclass(frozen=True, slots=True, kw_only=True)
class OpportunityRow:
    """One scanned rung. Frozen dataclass — not a Nautilus ``Data`` type yet."""

    instrument_id: str
    station: str
    climate_day: date
    ev_net: float
    C: float
    h_hours: float
    fillable_qty: float
    p_hat: float
    p_lower: float
    score: float | None = None
    rank: int | None = None


def unified_cost(cost: DepthAwareTradeCost) -> float:
    """``C = top_of_book_price + total_prob`` (spec §4)."""
    return cost.top_of_book_price + cost.total_prob


def ev_net(p_lower: float, cost: DepthAwareTradeCost) -> float | None:
    """``P^L − C`` via the shipped :func:`edge_after_costs` call contract."""
    return edge_after_costs(
        model_p=p_lower,
        bid_p=None,
        ask_p=cost.top_of_book_price,
        intent_long_yes=True,
        cost=cost.total_prob,
    )


def margin(h_hours: float, n_cell: int, cfg: LadderEvConfig) -> float | None:
    """Horizon-aware policy buffer; ``None`` (infinite) when ``n_cell < n_min_cell``."""
    if n_cell < cfg.n_min_cell:
        return None
    span = 24.0 - float(cfg.margin_h0_hours)
    t = min(1.0, max(0.0, (h_hours - float(cfg.margin_h0_hours)) / span))
    return cfg.margin_m0 + (cfg.margin_m24 - cfg.margin_m0) * t


def kelly_stake_fraction(p_lower: float, cost: float, cfg: LadderEvConfig) -> float:
    """Returns ``κ·f*`` with ``f* = (P−C)/(1−C)``.

    When enabled this is ``κ·(P−C)/(1−C)`` (``cfg.kelly_fraction`` is κ).
    When ``kelly_enabled`` is False, returns 1 contract.
    """
    if not cfg.kelly_enabled:
        return 1.0
    return cfg.kelly_fraction * (p_lower - cost) / (1.0 - cost)


def _roi(row: OpportunityRow) -> float:
    if row.C <= 0.0:
        return float("-inf")
    return row.ev_net / row.C


def _sort_key(row: OpportunityRow) -> tuple[float, float, float, float, str]:
    score = row.score if row.score is not None else 0.0
    return (-score, -_roi(row), row.h_hours, -row.fillable_qty, row.instrument_id)


def rank_rows(rows: Sequence[OpportunityRow], cfg: LadderEvConfig) -> list[OpportunityRow]:
    """Primary score = ``ev_net·(1−λu·u)·(1−λc·c)``; city-day cap via ``c``."""
    lambda_u = cfg.uncertainty_penalty
    scored: list[OpportunityRow] = []
    for row in rows:
        u = 1.0 - (row.p_lower / row.p_hat) if row.p_hat > 0.0 else 1.0
        u = min(1.0, max(0.0, u))
        score = row.ev_net * (1.0 - lambda_u * u)
        scored.append(replace(row, score=score))
    scored.sort(key=_sort_key)
    seen: set[tuple[str, date]] = set()
    capped: list[OpportunityRow] = []
    for row in scored:
        city_day = (row.station, row.climate_day)
        if city_day in seen:
            capped.append(replace(row, score=0.0))
        else:
            seen.add(city_day)
            capped.append(row)
    capped.sort(key=_sort_key)
    return [replace(row, rank=index) for index, row in enumerate(capped, start=1)]
