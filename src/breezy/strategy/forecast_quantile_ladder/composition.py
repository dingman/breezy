"""Composition root helpers for ``forecast_quantile_ladder`` (SL-13).

Plan `FORECAST_NBP_PROBABILISTIC_FAMILY_Rev3_2026-09-29.md` §7 row SL-13,
hypothesis H-FC-NBP-EV-2026-09. One :class:`ForecastQuantileLadderStrategy`
per supported station (mirrors ``current_rung_hold.composition``'s
per-station shape), sharing ONE
:class:`~breezy.strategy.ladder_ev.forecast_subscriber.ForecastQuantileStateActor`
and ONE :class:`~breezy.ingest.nbm_quantile_actor.NbmQuantileActor`.

Reuses ``current_rung_hold.composition``'s own cross-cutting Phase 0/1
mechanics directly (never re-implemented): ``resolve_station_instrument_ids``
for catalog discovery, and the caller (``app/trade.py``) reuses
``family_halt_submit_veto``/``phase1_sending_permit``/``open_trial_day_latch``
unchanged -- ONE implementation of each, shared by every composition kind.

Unlike ``ContinuousRungHoldStrategy`` (which opens its OWN ``TrialDayLatch``
per station via an injected factory, at ``on_start``), a
``ForecastQuantileLadderStrategy``'s ``latch`` is a plain constructor value,
not a factory -- ``station``/``climate_day`` are call-time parameters of
``is_latched``/``latch`` (SL-12's ``latch.QuantileLadderLatch`` shape), so
ONE ``breezy.strategy.forecast_quantile_ladder.persistent_latch.
PersistentQuantileLadderLatch`` (wrapping ONE ``TrialDayLatch`` the caller
opens once) is shared by every composed station, never one per station.
"""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Final

from breezy.strategy.current_rung_hold.composition import resolve_station_instrument_ids
from breezy.strategy.current_rung_hold.continuous_strategy import Phase0PermitForbiddenError
from breezy.strategy.forecast_quantile_ladder.artefact_bounds import (
    ArtefactBoundsProvider,
    load_bounds_artefact_draws,
)
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import load_calibration_artefact
from breezy.strategy.forecast_quantile_ladder.config import ForecastQuantileLadderConfig
from breezy.strategy.forecast_quantile_ladder.persistent_latch import SupportsQuantileLatch
from breezy.strategy.forecast_quantile_ladder.strategy import (
    ForecastQuantileLadderStrategy,
    SupportsExpiresAtNs,
)
from breezy.strategy.ladder_ev.config import LadderEvConfig
from breezy.strategy.ladder_ev.forecast_state import ForecastQuantileVector
from breezy.strategy.ladder_ev.forecast_subscriber import ForecastQuantileStateActor
from breezy.strategy.ladder_ev.quantile_density import Percentiles

__all__ = [
    "NoTradableForecastInstrumentsError",
    "build_forecast_quantile_ladder_strategies",
    "strategy_component_id",
]

_VENUE: Final[str] = "polymarket_us"
_COMPONENT_ID_PREFIX: Final[str] = "FORECAST-QUANTILE-LADDER"


class NoTradableForecastInstrumentsError(RuntimeError):
    """Every composed station resolved zero catalog instruments today."""


def strategy_component_id(station: str) -> str:
    """Unique ``strategy_id`` per station -- ``Trader.add_strategy`` rejects a collision."""
    return f"{_COMPONENT_ID_PREFIX}-{station}"


def _percentiles_reader(
    quantile_actor: ForecastQuantileStateActor,
    station: str,
    now_ns_fn: Callable[[], int],
) -> Callable[[], Percentiles | None]:
    """Independently reads the SAME actor/station ``evaluate_snapshot``
    itself reads -- see ``artefact_bounds``'s module docstring for why the
    ``BoundsProvider`` Protocol needs this closure rather than the ``cdf``
    it is actually called with.
    """

    def _read() -> Percentiles | None:
        vector: ForecastQuantileVector | None = quantile_actor.state_for(station).value_at(
            now_ns_fn(),
        )
        if vector is None:
            return None
        return Percentiles(
            q10=vector.q10,
            q25=vector.q25,
            q50=vector.q50,
            q75=vector.q75,
            q90=vector.q90,
            mean=vector.mean,
            sd=vector.sd,
        )

    return _read


def build_forecast_quantile_ladder_strategies(
    *,
    catalog_root: Path,
    today_by_station: Mapping[str, dt.date],
    latch: SupportsQuantileLatch,
    calibration_artefact_path: str,
    calibration_artefact_sha256: str,
    bounds_artefact_path: str,
    bounds_artefact_sha256: str,
    ladder_cfg: LadderEvConfig | None = None,
    order_submission_permit: SupportsExpiresAtNs | None = None,
    phase0_permit_guard: bool = True,
    submit_veto: Callable[[], str | None] | None = None,
    fee_verified: Callable[[], bool] | None = None,
    required_fee_coefficient: float | None = None,
    now_ns_fn: Callable[[], int] = time.time_ns,
) -> tuple[tuple[ForecastQuantileLadderStrategy, ...], ForecastQuantileStateActor]:
    """One ``ForecastQuantileLadderStrategy`` per supported station.

    Returns ``(strategies, quantile_actor)`` -- the caller
    (``app/trade.py``) adds ``quantile_actor`` and its own
    ``NbmQuantileActor`` to ``extra_actors``; neither Actor is built here
    (``NbmQuantileActor``'s station-ICAO/transport wiring is a distinct,
    caller-owned concern -- this function only needs the ONE
    ``ForecastQuantileStateActor`` every composed strategy shares).

    ``phase0_permit_guard`` mirrors ``build_continuous_rung_hold_strategies``'s
    own parameter exactly: ``True`` (default) refuses a non-``None``
    ``order_submission_permit`` HERE, before any instrument resolution or
    strategy construction (reuses ``Phase0PermitForbiddenError``, never a
    second error type for the same invariant).
    """
    if phase0_permit_guard and order_submission_permit is not None:
        raise Phase0PermitForbiddenError(
            "build_forecast_quantile_ladder_strategies: Phase 0 forbids a "
            "non-None order_submission_permit",
        )

    resolved = resolve_station_instrument_ids(catalog_root, today_by_station)
    if all(len(ids) == 0 for ids in resolved.values()):
        raise NoTradableForecastInstrumentsError(
            "build_forecast_quantile_ladder_strategies: zero catalog "
            f"instruments resolved for {sorted(today_by_station)}",
        )

    artefact = load_calibration_artefact(
        calibration_artefact_path, expected_sha256=calibration_artefact_sha256,
    )
    bounds_draws = load_bounds_artefact_draws(
        bounds_artefact_path, expected_sha256=bounds_artefact_sha256,
    )
    resolved_ladder_cfg = ladder_cfg if ladder_cfg is not None else LadderEvConfig()

    quantile_actor = ForecastQuantileStateActor(stations=tuple(today_by_station))

    strategies: list[ForecastQuantileLadderStrategy] = []
    for station in today_by_station:
        instrument_ids = resolved[station]
        if not instrument_ids:
            continue
        config_kwargs: dict[str, object] = {
            "stations": (station,),
            "calibration_artefact_path": calibration_artefact_path,
            "calibration_artefact_sha256": calibration_artefact_sha256,
            "strategy_id": _COMPONENT_ID_PREFIX,
            "order_id_tag": station,
        }
        if required_fee_coefficient is not None:
            config_kwargs["required_fee_coefficient"] = required_fee_coefficient
        config = ForecastQuantileLadderConfig(**config_kwargs)  # type: ignore[arg-type]
        bounds_provider = ArtefactBoundsProvider(
            cdf_method=bounds_draws.cdf_method,
            draws=bounds_draws.draws,
            percentiles_fn=_percentiles_reader(quantile_actor, station, now_ns_fn),
        )
        strategies.append(
            ForecastQuantileLadderStrategy(
                config,
                quantile_actor=quantile_actor,
                artefact=artefact,
                ladder_cfg=resolved_ladder_cfg,
                bounds_provider=bounds_provider,
                latch=latch,
                order_submission_permit=order_submission_permit,
                submit_veto=submit_veto,
                fee_verified=fee_verified,
                instrument_ids=tuple(str(iid) for iid in instrument_ids),
            ),
        )
    return tuple(strategies), quantile_actor
