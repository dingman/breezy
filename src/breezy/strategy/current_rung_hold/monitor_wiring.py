"""Factory for the read-only closures every ``PositionMonitor`` needs when
wired to a :class:`ContinuousRungHoldStrategy` instance.

Review finding F1 (DRY): the same ~9 read-only closures --
``positions_open``/``latch_record``/``rung_geometry``/``fee_coefficient_for``/
``leg_for``/``station_for``/``climate_day_for``/``hour_lst_for`` -- were
hand-copied three times: ``composition.py``'s ``_build_position_monitor_for``,
``scripts/analysis/current_rung_hold_paper_replay.py``'s
``install_position_monitor``, and the contract test's ``_wire_monitor``. This
module is the ONE place that wiring lives now; all three call sites build a
:class:`MonitorCallables` here instead of re-deriving the closures.

L-1: no gap here -- this is pure Breezy glue over an already-built strategy
object, not a Nautilus-adjacent wrapper.

M7 D3 pin (``position_monitor.py``'s own docstring, never violate): every
closure below only READS ``strategy``'s cache/latch/facts/accumulators
surface -- never its mutating one. None of them call
``_hunt_tick``/``_maybe_submit``, and none read or pop
``_decision_ask_by_station_day``.

Call sites still own ``buffer``, ``catalog_root``, ``summaries_dir``,
``clock_ns`` and ``report`` -- those genuinely vary by call site (a live
node's bare ``MarkBuffer()`` vs a replay run's JSONL sidecar; the live alert
sink vs a test's no-op reporter) and are deliberately NOT part of this
factory.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from nautilus_trader.model.identifiers import InstrumentId

from breezy.adapters.polymarket_us.symbology import leg_of
from breezy.strategy.current_rung_hold.monitor_evidence import Leg
from breezy.strategy.current_rung_hold.strategy import _local_hour

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nautilus_trader.model.position import Position

    from breezy.domain.weather_bucket_facts import WeatherBucketFacts
    from breezy.strategy.current_rung_hold.continuous_strategy import (
        ContinuousRungHoldStrategy,
    )
    from breezy.strategy.current_rung_hold.trial_day_latch import TrialDayRecord

__all__ = ["MonitorCallables", "build_monitor_callables"]


@dataclass(frozen=True, slots=True)
class MonitorCallables:
    """The eight read-only closures a ``PositionMonitor`` constructor call
    needs, bound to one already-constructed ``ContinuousRungHoldStrategy``
    (or a subclass, e.g. ``ContinuousRungHoldBacktestStrategy``). Field
    names match the corresponding ``PositionMonitor.__init__`` parameters
    exactly (``position_monitor.py``), so a call site passes each field
    straight through.
    """

    positions_open: Callable[[str], Sequence[Position]]
    latch_record: Callable[..., TrialDayRecord | None]
    rung_geometry: Callable[[str], WeatherBucketFacts | None]
    fee_coefficient_for: Callable[[str], Decimal]
    leg_for: Callable[[str], Leg]
    station_for: Callable[[str], str]
    climate_day_for: Callable[[str], str]
    hour_lst_for: Callable[[str, int], int]


def build_monitor_callables(strategy: ContinuousRungHoldStrategy) -> MonitorCallables:
    """Wire the eight read-only closures to ``strategy`` (F1 DRY extraction).

    Every closure resolves its state off ``strategy`` at CALL time, never at
    construction -- the same laziness the three original hand-copies relied
    on (``strategy.cache``/``strategy._facts``/``strategy._latch`` are only
    populated once ``on_start`` runs, so this factory may run either right
    after construction, live composition's convention, or bound then
    invoked much later, the paper-replay driver's convention).
    """

    def _positions_open(iid: str) -> Sequence[Position]:
        return strategy.cache.positions_open(  # type: ignore[no-any-return]
            instrument_id=InstrumentId.from_str(iid),
        )

    def _latch_record(
        station: str, climate_day: str, *, key_instrument_id: str | None = None,
    ) -> TrialDayRecord | None:
        if strategy._latch is None:
            return None
        return strategy._latch.record_with_legacy_fallback(
            station, climate_day, key_instrument_id=key_instrument_id,
        )

    def _rung_geometry(iid: str) -> WeatherBucketFacts | None:
        return strategy._facts.get(iid)

    def _fee_coefficient_for(iid: str) -> Decimal:
        instrument = strategy.cache.instrument(InstrumentId.from_str(iid))
        fee = strategy._guarded_fee_coefficient(instrument)
        if fee is None:
            raise ValueError(f"unknown fee schedule for {iid}")
        return fee

    def _leg_for(iid: str) -> Leg:
        return "NO" if leg_of(InstrumentId.from_str(iid)) == "no" else "YES"

    def _station_for(iid: str) -> str:
        return strategy._facts[iid].settlement_station

    def _climate_day_for(iid: str) -> str:
        return strategy._facts[iid].climate_day.isoformat()

    def _hour_lst_for(station: str, now_ns: int) -> int:
        offset = strategy._std_utc_offset_hours_by_station[station]
        return _local_hour(now_ns, offset)

    return MonitorCallables(
        positions_open=_positions_open,
        latch_record=_latch_record,
        rung_geometry=_rung_geometry,
        fee_coefficient_for=_fee_coefficient_for,
        leg_for=_leg_for,
        station_for=_station_for,
        climate_day_for=_climate_day_for,
        hour_lst_for=_hour_lst_for,
    )
