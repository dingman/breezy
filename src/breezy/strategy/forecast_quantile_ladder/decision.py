"""Pure decision module for `forecast_quantile_ladder` (SL-12). No I/O.

Plan `FORECAST_NBP_PROBABILISTIC_FAMILY_Rev3_2026-09-29.md` §3.3: "The trial
is the first executable snapshot per (station-day, rung, side, variant) that
satisfies ``ev_net > margin`` under the latest available cycle. One latch;
qty 1... A decision outside [a live permit] is recorded as NOT_EXECUTABLE,
never latched and never counted as a trial... A new cycle never re-opens a
latched rung. Sizing never reads ``kelly_stake_fraction``, and no
operator-reserved value is read or assigned."

Deliberately does NOT import
:func:`breezy.strategy.ladder_ev.decision.exclusion_filter` /
:class:`breezy.strategy.ladder_ev.decision.ExclusionInputs` (the DEGRADED-mode
X-rule gate; this is a distinct forecast-mode decision path) nor
``breezy.strategy.current_rung_hold.archive_table``'s ``P_HOLD_LOWER`` /
``P_HOLD_UPPER`` (the closed model's collider cells -- plan §1.2 item 2:
"No dependence on the P_HOLD_* collider cells"). Pinned by
``tests/strategy/forecast_quantile_ladder/test_forbidden_imports.py``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

from breezy.strategy.forecast_quantile_ladder.calibration_artefact import CalibrationArtefact
from breezy.strategy.forecast_quantile_ladder.latch import QuantileLadderLatch
from breezy.strategy.ladder_ev.config import LadderEvConfig
from breezy.strategy.ladder_ev.forecast_state import ForecastQuantileVector
from breezy.strategy.ladder_ev.quantile_density import (
    Percentiles,
    Rung,
    apply_emos,
    build_cdf,
    rung_probabilities,
)
from breezy.strategy.ladder_ev.scoring import ev_net, ev_net_no, margin
from breezy.strategy.weather_common.costs import DepthAwareTradeCost, venue_fee_prob

__all__ = [
    "Decision",
    "NotExecutable",
    "Refuse",
    "Take",
    "evaluate",
]

#: Sizing is always exactly 1 contract (plan §3.3: "qty 1"). Never a config
#: field, never derived from `kelly_stake_fraction` -- there is no such input.
QTY: Literal[1] = 1


@dataclass(frozen=True, slots=True, kw_only=True)
class NotExecutable:
    """Outside a live order-permit window: never latched, never counted as a
    trial (plan §3.3)."""

    reason: str = "outside_permit_window"


@dataclass(frozen=True, slots=True, kw_only=True)
class Refuse:
    """Evaluated, but not taken; the latch is untouched."""

    reason: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Take:
    """The first qualifying snapshot for this (station-day, rung, side).

    ``qty`` is always :data:`QTY` -- present on the record for observability,
    never accepted as a caller input.
    """

    instrument_id: str
    station: str
    climate_day: date
    side: Literal["yes", "no"]
    rung_id: str
    qty: Literal[1]
    ev_net: float
    p_hat: float
    p_lower: float
    p_upper: float


Decision = NotExecutable | Refuse | Take


def evaluate(
    *,
    permit_covers: bool,
    vector: ForecastQuantileVector | None,
    station: str,
    climate_day: date,
    instrument_id: str,
    ladder: Sequence[Rung],
    rung_id: str,
    side: Literal["yes", "no"] = "yes",
    ask: float,
    fee_coefficient: float,
    slippage_floor_prob: float,
    h_hours: float,
    n_cell: int,
    cfg: LadderEvConfig,
    artefact: CalibrationArtefact,
    latch: QuantileLadderLatch,
) -> Decision:
    """Evaluate ONE rung at ONE snapshot. Pure; mutates only ``latch`` on a Take.

    Order of checks matches plan §3.3, permit first: a decision outside the
    permit is NEVER latched and NEVER counted as a trial, regardless of what
    the forecast or the ask would otherwise have supported.
    """
    if not permit_covers:
        return NotExecutable()

    if latch.is_latched(station=station, climate_day=climate_day, rung_id=rung_id, side=side):
        return Refuse(reason="already_latched")

    if vector is None:
        return Refuse(reason="forecast_unavailable")

    percentiles = Percentiles(
        q10=vector.q10,
        q25=vector.q25,
        q50=vector.q50,
        q75=vector.q75,
        q90=vector.q90,
        mean=vector.mean,
        sd=vector.sd,
    )
    base_cdf = build_cdf(artefact.cdf_method, percentiles)
    cdf = apply_emos(base_cdf, percentiles, artefact.emos)
    probabilities = rung_probabilities(cdf, ladder)
    if rung_id not in probabilities:
        raise ValueError(f"rung_id {rung_id!r} is not a member of `ladder`")
    p_hat = probabilities[rung_id]
    p_lower = max(0.0, p_hat - artefact.p_lower_haircut)
    p_upper = min(1.0, p_hat + artefact.p_upper_haircut)

    # V1 is qty 1 at a single quoted price -- no ladder walk, so the
    # executable/top-of-book/worst prices coincide and the fill is never
    # depth-exhausted. Depth-aware sizing beyond 1 contract is out of scope
    # for this slice (plan §3.3: "qty 1").
    fee_prob = venue_fee_prob(executable_price=ask, fee_coefficient=fee_coefficient)
    cost = DepthAwareTradeCost(
        executable_price=ask,
        top_of_book_price=ask,
        worst_price=ask,
        fee_prob=fee_prob,
        slippage_prob=slippage_floor_prob,
        total_prob=fee_prob + slippage_floor_prob,
        fillable_quantity=float(QTY),
        requested_quantity=float(QTY),
        depth_exhausted=False,
    )
    net = ev_net(p_lower, cost) if side == "yes" else ev_net_no(p_upper, cost)
    if net is None:
        return Refuse(reason="not_executable")

    buffer = margin(h_hours, n_cell, cfg)
    if buffer is None or not (net > buffer):
        return Refuse(reason="below_margin")

    latch.latch(station=station, climate_day=climate_day, rung_id=rung_id, side=side)
    return Take(
        instrument_id=instrument_id,
        station=station,
        climate_day=climate_day,
        side=side,
        rung_id=rung_id,
        qty=QTY,
        ev_net=net,
        p_hat=p_hat,
        p_lower=p_lower,
        p_upper=p_upper,
    )
