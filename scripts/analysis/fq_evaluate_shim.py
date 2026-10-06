"""One call of the shipped FQ take rule, shared by the F5 Monte-Carlo and the F13 veto.

``call_evaluate`` is the single place that invokes
``breezy.strategy.forecast_quantile_ladder.decision.evaluate`` with synthetic inputs. The only
injected piece is the bounds provider (``p_lower`` / ``p_upper`` is ``p_hat -/+
cfg.bound_halfwidth``); the vector, the calibration stub and the clock are inert placeholders the
rule does not read for the take decision. Promoted unchanged from
``fq_mc_livedata._call_evaluate`` (which re-exports it); the only additions are the explicit
``side`` check and the :class:`EvaluateConfig` protocol, which lets this module stay free of
``fq_mc_livedata`` (so that module can import it without a cycle).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Any, Literal, Protocol, get_args

from breezy.strategy.forecast_quantile_ladder.bounds import RungBounds
from breezy.strategy.forecast_quantile_ladder.decision import SidedAsk, evaluate
from breezy.strategy.forecast_quantile_ladder.latch import QuantileLadderLatch
from breezy.strategy.forecast_quantile_ladder.margin import hours_to_settlement
from breezy.strategy.ladder_ev.config import LadderEvConfig
from breezy.strategy.ladder_ev.forecast_state import ForecastQuantileVector
from breezy.strategy.ladder_ev.quantile_density import Rung

__all__ = ["EvaluateConfig", "Side", "call_evaluate"]

#: The strategy's side literal (``decision.SidedAsk.side`` / ``evaluate(side=...)``).
Side = Literal["yes", "no"]

_NS_PER_HOUR = 3_600_000_000_000


class EvaluateConfig(Protocol):
    """The ``LoopConfig`` fields :func:`call_evaluate` reads."""

    @property
    def std_utc_offset_hours(self) -> float: ...
    @property
    def theta(self) -> float: ...
    @property
    def slippage_floor_prob(self) -> float: ...
    @property
    def latitude_deg(self) -> float: ...
    @property
    def bound_halfwidth(self) -> float: ...


class _StubResolved:
    draws: tuple[()] = ()
    point = None


class _StubCalibration:
    """`evaluate` forwards only ``draws`` to the bounds provider, which ignores them."""

    def resolve(self, era: str, *, latitude_deg: float, climate_day: dt.date) -> _StubResolved:
        return _StubResolved()


def _vector(day: dt.date) -> ForecastQuantileVector:
    return ForecastQuantileVector(
        q10=0.0,
        q25=0.0,
        q50=0.0,
        q75=0.0,
        q90=0.0,
        mean=0.0,
        sd=1.0,
        available_at_ns=0,
        cycle_runtime_ns=0,
        climate_day=day,
        model_version="v4.0",
    )


def _now_ns(climate_day: dt.date, cfg: EvaluateConfig, h_hours: float) -> int:
    settle_ns = (
        hours_to_settlement(
            now_ns=0, climate_day=climate_day, std_utc_offset_hours=cfg.std_utc_offset_hours
        )
        * _NS_PER_HOUR
    )
    return int(settle_ns - h_hours * _NS_PER_HOUR)


def call_evaluate(
    *,
    climate_day: dt.date,
    station: str,
    ladder: Sequence[Rung],
    rung_id: str,
    side: Side,
    ask: SidedAsk,
    p_hat: float,
    cfg: EvaluateConfig,
    h_hours: float,
    latch: QuantileLadderLatch,
) -> Any:
    """ONE call of the shipped take rule. The only injected piece is the bounds provider."""
    if side not in get_args(Side):
        raise ValueError(f"side must be one of {get_args(Side)}, was {side!r}")

    def provider(**_kw: Any) -> RungBounds:
        return RungBounds(p_hat, p_hat - cfg.bound_halfwidth, p_hat + cfg.bound_halfwidth)

    return evaluate(
        now_ns=_now_ns(climate_day, cfg, h_hours),
        std_utc_offset_hours=cfg.std_utc_offset_hours,
        permit_covers=True,
        vector=_vector(climate_day),
        station=station,
        climate_day=climate_day,
        ladder=ladder,
        rung_id=rung_id,
        side=side,
        ask=ask,
        fee_coefficient=cfg.theta,
        slippage_floor_prob=cfg.slippage_floor_prob,
        h_hours=h_hours,
        cfg=LadderEvConfig(),
        calibration=_StubCalibration(),  # type: ignore[arg-type]
        latitude_deg=cfg.latitude_deg,
        bounds_provider=provider,
        latch=latch,
    )
