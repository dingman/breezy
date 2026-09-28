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

FU-1 (``docs/plans`` backlog item "Position monitor KeyError on `^no` ids"):
``strategy._facts`` (``continuous_strategy.py:842``) is populated YES-only --
depth is subscribed only for YES instrument ids, so a NO-leg composite id is
NEVER a key in that mapping. Before this fix, ``_rung_geometry``/
``_station_for``/``_climate_day_for`` read ``strategy._facts`` directly and a
NO-leg fill's ``PositionMonitor._register`` (``position_monitor.py``) raised
``KeyError`` on every one of them, caught only by ``_guarded`` (D8) as a
``monitor_error`` -- the NO position was never actually monitored. Below,
:func:`_facts_for_either_leg` resolves a NO-leg id to its YES sibling's
already-registered facts (the two legs of one market share ONE rung/station/
climate-day geometry) with NO change to a YES id's own resolution -- a
YES-id miss still resolves to ``None`` exactly as before, and the sibling
probe never runs for one (a YES id can never satisfy ``leg_of(iid) ==
"no"``, so it is never even attempted).

Live behaviour table (this fix, both legs' facts source only -- everything
downstream, e.g. ``leg_for``/``monitor_decision``/``monitor_evidence``'s
DEAD/LOCKED swap and mark-price complement, is unchanged, already leg-aware,
and out of this module's scope):

============  =========================================  ==================
Leg           facts source                                Miss (neither leg)
============  =========================================  ==================
YES           ``strategy._facts[iid]`` directly            ``None``/``KeyError``
NO            YES sibling's ``strategy._facts[sibling]``   ``None``/``KeyError``
============  =========================================  ==================
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from nautilus_trader.model.identifiers import InstrumentId

from breezy.adapters.polymarket_us.errors import VenuePayloadError
from breezy.adapters.polymarket_us.symbology import leg_of, sibling_instrument_id
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


def _facts_for_either_leg(
    facts: Mapping[str, WeatherBucketFacts],
    iid: str,
) -> WeatherBucketFacts | None:
    """FU-1: resolve ``iid``'s rung geometry, falling back to its YES
    sibling's facts when ``iid`` is a NO-leg id absent from ``facts``.

    A direct hit always wins -- the sibling probe runs ONLY on a genuine
    miss, and only when ``iid`` actually parses as a NO-leg id; a YES-id
    miss (e.g. an unregistered instrument) never reaches
    :func:`sibling_instrument_id` and resolves to ``None``, byte-identical
    to the pre-fix behaviour. Never mutates ``facts`` (M7 D3). An
    unparseable ``iid`` (:class:`ValueError` from
    :meth:`InstrumentId.from_str`) or a foreign-venue NO-leg id
    (:class:`VenuePayloadError` from :func:`sibling_instrument_id`) also
    resolves to ``None`` -- never a raised error, never a guessed slug.
    """
    direct = facts.get(iid)
    if direct is not None:
        return direct
    try:
        instrument_id = InstrumentId.from_str(iid)
    except ValueError:
        return None
    if leg_of(instrument_id) != "no":
        return None
    try:
        sibling_id = sibling_instrument_id(instrument_id)
    except VenuePayloadError:
        return None
    return facts.get(str(sibling_id))


def _sibling_for(iid: str) -> str | None:
    """FU-1d (`RULING_FU-1b_no_leg_marks_2026-09-26.md`): resolve `iid`'s
    sibling instrument id for `PositionMonitor.on_depth`'s NO-leg routing.

    Mirrors `_facts_for_either_leg`'s own defence-in-depth shape: a
    malformed id (`InstrumentId.from_str` raises `ValueError`) resolves to
    `None`, never a raised error. A NO-leg id resolves to `None` too --
    routing only ever runs FORWARD, from a YES depth frame to its NO
    sibling, never the reverse (there is no NO-leg book to walk, and this
    also rules out a YES<->NO ping-pong if a NO-keyed frame somehow ever
    arrived here, which the subscribe path never produces). A foreign-venue
    sibling (`VenuePayloadError`) also resolves to `None`.
    """
    try:
        instrument_id = InstrumentId.from_str(iid)
    except ValueError:
        return None
    if leg_of(instrument_id) == "no":
        return None
    try:
        return str(sibling_instrument_id(instrument_id))
    except VenuePayloadError:
        return None


@dataclass(frozen=True, slots=True)
class MonitorCallables:
    """The nine read-only closures a ``PositionMonitor`` constructor call
    needs, bound to one already-constructed ``ContinuousRungHoldStrategy``
    (or a subclass, e.g. ``ContinuousRungHoldBacktestStrategy``). Field
    names match the corresponding ``PositionMonitor.__init__`` parameters
    exactly (``position_monitor.py``), so a call site passes each field
    straight through.

    L-44 (FU-1d): ``sibling_for`` is the NO leg's mark source -- the YES
    sibling's own depth frame, walking the asks (see
    ``position_monitor.PositionMonitor._on_sibling_depth`` and
    ``monitor_evidence.walk_exit_vwap``). There is no NO-leg book to
    subscribe to (`RULING_FU-1b_no_leg_marks_2026-09-26.md`).
    """

    positions_open: Callable[[str], Sequence[Position]]
    latch_record: Callable[..., TrialDayRecord | None]
    rung_geometry: Callable[[str], WeatherBucketFacts | None]
    fee_coefficient_for: Callable[[str], Decimal]
    leg_for: Callable[[str], Leg]
    station_for: Callable[[str], str]
    climate_day_for: Callable[[str], str]
    hour_lst_for: Callable[[str, int], int]
    sibling_for: Callable[[str], str | None]


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
        station: str,
        climate_day: str,
        *,
        key_instrument_id: str | None = None,
    ) -> TrialDayRecord | None:
        if strategy._latch is None:
            return None
        return strategy._latch.record_with_legacy_fallback(
            station,
            climate_day,
            key_instrument_id=key_instrument_id,
        )

    def _rung_geometry(iid: str) -> WeatherBucketFacts | None:
        return _facts_for_either_leg(strategy._facts, iid)

    def _fee_coefficient_for(iid: str) -> Decimal:
        instrument = strategy.cache.instrument(InstrumentId.from_str(iid))
        fee = strategy._guarded_fee_coefficient(instrument)
        if fee is None:
            raise ValueError(f"unknown fee schedule for {iid}")
        return fee

    def _leg_for(iid: str) -> Leg:
        return "NO" if leg_of(InstrumentId.from_str(iid)) == "no" else "YES"

    def _station_for(iid: str) -> str:
        facts = _facts_for_either_leg(strategy._facts, iid)
        if facts is None:
            raise KeyError(iid)
        return facts.settlement_station

    def _climate_day_for(iid: str) -> str:
        facts = _facts_for_either_leg(strategy._facts, iid)
        if facts is None:
            raise KeyError(iid)
        return facts.climate_day.isoformat()

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
        sibling_for=_sibling_for,
    )
