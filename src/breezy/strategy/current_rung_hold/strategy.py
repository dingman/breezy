"""``CurrentRungHoldStrategy`` -- Nautilus wiring only (build order step 6).

Consumes every landed piece: :class:`CurrentRungHoldConfig`,
:func:`evaluate_decision`/:class:`DecisionInputs`/:class:`Take`/
:class:`Refuse`, :class:`TrialDayLatch` (received via a factory so tests can
inject a temp-store latch -- see ``__init__``), :data:`P_HOLD_LOWER`
(indirectly, through ``decision.py``), :class:`RunningExtremeAccumulator`,
``StationObservation``/``station_observation_data_type`` (Seam B's publish
topic, subscribed natively via ``Actor.subscribe_data``), and
``WeatherBucketFacts``/``read_weather_bucket_facts`` for the venue ladder.

NO ORDER may be submittable from this increment (see the module's
``_maybe_submit``): ``CurrentRungHoldConfig.orders_enabled`` is refused
``True`` at construction (``config.py``, L-22 shape), so the ``submit_order``
call in ``_maybe_submit`` is unreachable code, defence in depth over the
config-level refusal, not the primary mechanism.

FIRST-EXECUTABLE-SNAPSHOT selection (blueprint correction, Grok rev 2 over
rev 1; ``mb_current_rung_edge_study.py:545-551``)
--------------------------------------------------------------------------
Per station-day, THE trial is the first quote, in the ``[12:00,17:00)`` LST
window, on an instrument that COULD be the current rung (``running_max.lower_f``
falls inside that instrument's own closed ``[lower_f, upper_f]`` facts -- the
same lower-bound resolution ``evaluate_decision`` itself uses against the full
ladder, so an ambiguous ``RunningMax`` spanning two rungs is still evaluated,
never pre-filtered away), with ``0.05 < ask < 0.95`` and displayed size
``>= 1``. That one quote is
evaluated through :func:`evaluate_decision` exactly ONCE and the verbatim
outcome (``"taken"`` or the refusal reason) is durably recorded to the
trial-day latch before this station-day is ever looked at again --
``on_quote_tick`` checks ``latch.is_consumed`` first, unconditionally, on
every call.

Restricting candidacy to the ladder's CURRENTLY-active-rung instrument (not
any subscribed instrument) mirrors the archive study reading its lagged
entry from ``depth.get(rung.instrument_id, ...)`` -- the rung the study
prices is always the SAME rung the running max just resolved to, never a
different instrument's book. A quote on a non-active-rung instrument is
silently skipped (not a counted refusal): it simply is not a decision
instant for that instrument yet.

Window and legal-cell derivation
---------------------------------
``season``/``hour_lst`` are derived from the LOCAL STANDARD time of the
quote's own ``ts_event`` at the station's fixed standard-time offset
(``breezy.registry.sites.toml``'s per-site ``std_utc_offset_hours``, mirrored
here as :data:`_STD_UTC_OFFSET_HOURS_BY_STATION` rather than imported --
``strategy.py`` trades exactly the four :data:`SUPPORTED_STATIONS`, a closed
set, so a private constant avoids pulling the full TOML-backed registry into
the trading path for four numbers). ``season_for`` re-derives (not imports;
``scripts/`` is unimportable from ``src/breezy``, see the layers contract)
the single lookup at ``scripts/analysis/pmr_climatology_study.py:258``.
``width_code``/``m_code`` are derived from the CURRENTLY-active-rung
instrument's own :class:`WeatherBucketFacts` bounds against
``running_max.lower_f`` -- ``width_code=0`` (interior) with
``m_code = running_max.lower_f - facts.lower_f``; ``width_code=1``
(open_upper, ``upper_f is None``) or ``width_code=2`` (open_lower,
``lower_f is None``) with ``m_code`` fixed at 0 (the open tails have no
margin axis -- ``archive_table.py``'s header). A key that cannot be derived
(no ``RunningMax`` yet) never reaches the table lookup at all: the strategy
returns before building one -- see ``on_quote_tick``.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from decimal import Decimal
from typing import TYPE_CHECKING, Final

from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy

from breezy.domain.station_observation import StationObservation
from breezy.domain.weather_bucket_facts import (
    Measure,
    WeatherBucketFacts,
    read_weather_bucket_facts,
)
from breezy.ingest.iem_observations import station_observation_data_type
from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
from breezy.strategy.current_rung_hold.decision import (
    DecisionInputs,
    Refuse,
    Take,
    evaluate_decision,
)
from breezy.strategy.current_rung_hold.trial_day_latch import TrialDayLatch
from breezy.strategy.weather_common.refusals import RefusalCounter
from breezy.strategy.weather_common.running_extreme import RunningExtremeAccumulator

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nautilus_trader.core.data import Data
    from nautilus_trader.model.data import QuoteTick

__all__ = [
    "CurrentRungHoldStrategy",
    "MissingTrialDayLatchError",
    "season_for",
]

_NS_PER_SECOND: Final[int] = 1_000_000_000
_WINDOW_START_HOUR_LST: Final[int] = 12
_WINDOW_END_HOUR_LST: Final[int] = 17  # exclusive
_WIDTH_INTERIOR: Final[int] = 0
_WIDTH_OPEN_UPPER: Final[int] = 1
_WIDTH_OPEN_LOWER: Final[int] = 2
#: Counted (``decision.REFUSAL_REASONS`` / ``risk.COUNTED_REFUSAL_REASONS``),
#: never emitted by ``evaluate_decision`` -- the window check runs here,
#: before a quote ever reaches that function.
_OUTSIDE_DECISION_WINDOW: Final[str] = "outside_decision_window"

#: Standard meteorological seasons -- mirrors
#: ``scripts/analysis/pmr_climatology_study.py:182-187`` (``_SEASON_BY_MONTH``),
#: re-derived rather than imported (``scripts/`` is unimportable from
#: ``src/breezy``).
_SEASON_BY_MONTH: Final[dict[int, str]] = {
    12: "DJF", 1: "DJF", 2: "DJF",
    3: "MAM", 4: "MAM", 5: "MAM",
    6: "JJA", 7: "JJA", 8: "JJA",
    9: "SON", 10: "SON", 11: "SON",
}

#: The IEM ASOS station id (``StationObservation.station``) for each of the
#: four :data:`~breezy.strategy.current_rung_hold.config.SUPPORTED_STATIONS`
#: -- mirrors ``breezy/registry/sites.toml``'s ``iem_asos_id`` (identical to
#: ``icao`` for all four: ``KLAX``/``KMDW``/``KMIA``/``KSFO``).
_ICAO_BY_STATION: Final[dict[str, str]] = {
    "LAX": "KLAX", "MDW": "KMDW", "MIA": "KMIA", "SFO": "KSFO",
}
_STATION_BY_ICAO: Final[dict[str, str]] = {
    icao: station for station, icao in _ICAO_BY_STATION.items()
}

#: The fixed standard-time UTC offset for each supported station -- mirrors
#: ``breezy/registry/sites.toml``'s ``std_utc_offset_hours`` for
#: ``polymarket_us.{LAX,MDW,MIA,SFO}``. NEVER DST-aware, matching the
#: registry's own field of the same name.
_STD_UTC_OFFSET_HOURS_BY_STATION: Final[dict[str, float]] = {
    "LAX": -8.0, "MDW": -6.0, "MIA": -5.0, "SFO": -8.0,
}


def season_for(climate_day: dt.date) -> str:
    """Standard meteorological season for ``climate_day``'s month."""
    return _SEASON_BY_MONTH[climate_day.month]


def _local_hour(now_ns: int, std_utc_offset_hours: float) -> int:
    seconds, nanoseconds = divmod(now_ns, _NS_PER_SECOND)
    instant = dt.datetime.fromtimestamp(seconds, tz=dt.UTC) + dt.timedelta(
        microseconds=nanoseconds // 1_000,
    )
    tz = dt.timezone(dt.timedelta(hours=std_utc_offset_hours))
    return instant.astimezone(tz).hour


class MissingTrialDayLatchError(RuntimeError):
    """Raised at ``on_start`` when no ``trial_day_latch_factory`` was supplied.

    Mirrors ``RunningExtremeLockStrategy``'s ``MissingObservationBoundError``
    posture: a mis-wired strategy fails LOUDLY at startup rather than
    silently never evaluating a single quote.
    """


class CurrentRungHoldStrategy(Strategy):
    """Buys LONG_YES, one contract, on the currently-active rung's first
    executable snapshot each station-day -- see the module docstring.
    """

    def __init__(
        self,
        config: CurrentRungHoldConfig,
        *,
        trial_day_latch_factory: Callable[[], TrialDayLatch] | None = None,
    ) -> None:
        super().__init__(config)
        self._config: CurrentRungHoldConfig = config
        self._latch_factory = trial_day_latch_factory
        self._latch: TrialDayLatch | None = None
        self._facts: dict[str, WeatherBucketFacts] = {}
        self._ladders: dict[tuple[str, str], list[tuple[int | None, int | None]]] = {}
        self._accumulators: dict[str, RunningExtremeAccumulator] = {}
        #: PUBLIC -- readable by an operator or a test asking "did this
        #: strategy do nothing, or was it stopped from doing something?"
        #: (mirrors every sibling weather strategy's ``self.refusals``).
        self.refusals = RefusalCounter()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def on_start(self) -> None:
        if self._latch_factory is None:
            raise MissingTrialDayLatchError(
                "CurrentRungHoldStrategy was constructed with no "
                "trial_day_latch_factory; see the module docstring."
            )
        self._latch = self._latch_factory()

        for instrument_id in self._config.instrument_ids:
            instrument = self.cache.instrument(instrument_id)
            if instrument is None:
                self.log.error(f"no instrument {instrument_id} in the cache; stopping")
                self.stop()
                return
            facts = read_weather_bucket_facts(instrument.info)
            if facts.measure is not Measure.HIGH:
                self.log.warning(
                    f"{instrument_id} measures {facts.measure.value!r}; this package "
                    "trades HIGH only, skipping subscription.",
                )
                continue
            if facts.settlement_station not in self._config.stations:
                self.log.warning(
                    f"{instrument_id} settles {facts.settlement_station!r}, outside "
                    f"{self._config.stations!r}; skipping subscription.",
                )
                continue
            iid = str(instrument_id)
            self._facts[iid] = facts
            key = (facts.settlement_station, facts.climate_day.isoformat())
            self._ladders.setdefault(key, []).append((facts.lower_f, facts.upper_f))
            self.subscribe_quote_ticks(instrument_id)
            self.log.info(f"CurrentRungHoldStrategy subscribed {instrument_id}")

        self.subscribe_data(station_observation_data_type())

    # ------------------------------------------------------------------
    # Data handlers
    # ------------------------------------------------------------------
    def on_data(self, data: Data) -> None:
        if type(data) is not StationObservation:
            return
        station = _STATION_BY_ICAO.get(data.station)
        if station is None or station not in self._config.stations:
            return
        offset = _STD_UTC_OFFSET_HOURS_BY_STATION[station]
        accumulator = self._accumulators.setdefault(
            station, RunningExtremeAccumulator(std_utc_offset_hours=offset),
        )
        accumulator.push(
            data.observed_at_ns,
            data.temp_c_tenths,
            data.precision_c_tenths,
            data.is_metar,
            data.received_at_ns,
        )

    def on_quote_tick(self, tick: QuoteTick) -> None:
        iid = str(tick.instrument_id)
        facts = self._facts.get(iid)
        if facts is None:
            return
        station = facts.settlement_station
        climate_day = facts.climate_day
        climate_day_key = climate_day.isoformat()

        assert self._latch is not None  # armed in on_start before any quote can arrive
        if self._latch.is_consumed(station, climate_day_key):
            return  # entry-only halt: this station-day already has its one trial

        now_ns = tick.ts_event
        offset = _STD_UTC_OFFSET_HOURS_BY_STATION[station]
        hour_lst = _local_hour(now_ns, offset)
        if not (_WINDOW_START_HOUR_LST <= hour_lst < _WINDOW_END_HOUR_LST):
            self.refusals.record(_OUTSIDE_DECISION_WINDOW)
            return

        ask = Decimal(str(tick.ask_price))
        size = int(tick.ask_size)
        raw_executable = (
            self._config.executable_ask_lower < ask < self._config.executable_ask_upper
            and size >= self._config.minimum_displayed_size
        )
        if not raw_executable:
            return  # in-window, not yet the candidate: wait, no latch (module docstring)

        accumulator = self._accumulators.get(station)
        running_max = None if accumulator is None else accumulator.value_at(now_ns)
        if running_max is None or accumulator is None:
            return  # no observation yet: not this instrument's decision instant
        if not facts.contains(running_max.lower_f):
            return  # this instrument's rung cannot be the current one

        if facts.upper_f is None:
            width_code, m_code = _WIDTH_OPEN_UPPER, 0
        elif facts.lower_f is None:
            width_code, m_code = _WIDTH_OPEN_LOWER, 0
        else:
            width_code, m_code = _WIDTH_INTERIOR, running_max.lower_f - facts.lower_f

        instrument = self.cache.instrument(tick.instrument_id)
        fee_coefficient = (
            instrument.maker_fee
            if instrument is not None and isinstance(instrument.maker_fee, Decimal)
            else Decimal(-1)
        )

        inputs = DecisionInputs(
            station=station,
            climate_day=climate_day,
            now_ns=now_ns,
            ladder=self._ladders[(station, climate_day_key)],
            fee_coefficient=fee_coefficient,
            ask=ask,
            size=size,
            running_max=running_max,
            staleness_ns=accumulator.staleness_ns(now_ns),
            config=self._config,
            season=season_for(climate_day),
            hour_lst=hour_lst,
            width_code=width_code,
            m_code=m_code,
            latch_consumed=False,
        )
        decision = evaluate_decision(inputs)
        reason = decision.reason if isinstance(decision, Refuse) else "taken"
        self._latch.consume(
            station,
            climate_day_key,
            latched_at_ns=self.clock.timestamp_ns(),
            instrument_id=iid,
            ask=ask,
            reason=reason,
        )
        if isinstance(decision, Refuse):
            self.refusals.record(decision.reason)
            return
        self._maybe_submit(iid, decision)

    # ------------------------------------------------------------------
    # Execution -- see the module docstring: unreachable in this increment.
    # ------------------------------------------------------------------
    def _maybe_submit(self, instrument_id: str, decision: Take) -> None:
        if not (
            self._config.orders_enabled
            and isinstance(self._config.stale_observation_hours, float)
        ):
            self.log.info(
                f"TAKE recorded, no submit (orders_enabled={self._config.orders_enabled}): "
                f"{instrument_id} qty={decision.quantity} px={decision.limit_price} "
                f"p_hold_lower={decision.p_hold_lower} break_even={decision.break_even}",
            )
            return
        nt_id = InstrumentId.from_str(instrument_id)  # pragma: no cover - unreachable
        instrument = self.cache.instrument(nt_id)  # pragma: no cover - unreachable
        if instrument is None:  # pragma: no cover - unreachable
            self.log.error(f"instrument vanished from cache: {instrument_id}")
            return
        order = self.order_factory.limit(  # pragma: no cover - unreachable
            instrument_id=nt_id,
            order_side=OrderSide.BUY,
            quantity=instrument.make_qty(decision.quantity),
            price=instrument.make_price(decision.limit_price),
            time_in_force=TimeInForce.IOC,
            post_only=False,
        )
        self.submit_order(order)  # pragma: no cover - unreachable
