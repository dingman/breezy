"""Compose ``CurrentRungHoldStrategy`` instances for the trading process.

The composition ROOT (``breezy.app.trade``) is the sole opener of the
submit-intent latch for the process lifetime. This module never calls
``open_submit_intent_latch``. It binds each station strategy to the
already-opened latch via ``open_trial_day_latch`` (L-22: exclusion is
unforgeable, not offered).

Catalog-derived ids are advisory for the pre-build fast-fail only. The live
``PolymarketUSInstrumentProvider`` is authoritative; ``on_start`` re-resolves
from ``self.cache``. Per-station degradation (L-23): refuse to start only when
ALL stations resolve zero instruments; otherwise skip + count + log the rest.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import Final

from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

from breezy.adapters.polymarket_us.errors import VenuePayloadError
from breezy.adapters.polymarket_us.symbology import instrument_id_to_slug, parse_weather_slug
from breezy.domain.weather_bucket_facts import (
    Measure,
    WeatherFactsUnavailableError,
    read_weather_bucket_facts,
)
from breezy.runtime.component_health_watch import COMPONENT_STATE_TOPIC
from breezy.runtime.health import resolve_alert_sink
from breezy.runtime.settings import SettingsError
from breezy.runtime.submit_intent import SubmitIntentLatch
from breezy.strategy.current_rung_hold.config import SUPPORTED_STATIONS, CurrentRungHoldConfig
from breezy.strategy.current_rung_hold.strategy import CurrentRungHoldStrategy
from breezy.strategy.current_rung_hold.trial_day_latch import TrialDayLatch, open_trial_day_latch
from breezy.strategy.weather_common.refusals import RefusalAlerter

__all__ = [
    "NoTradableInstrumentsError",
    "build_current_rung_hold_strategies",
    "install_current_rung_hold_refusal_watch",
    "make_trial_day_latch_factory",
    "resolve_station_instrument_ids",
    "strategy_component_id",
]

logger = logging.getLogger(__name__)

_COMPONENT_ID_PREFIX: Final[str] = "CurrentRungHoldStrategy"


class NoTradableInstrumentsError(SettingsError):
    """Raised when every supported station resolves zero instruments.

    A ``SettingsError`` subclass so the trading process exits 2 via the
    existing configuration-error path.
    """


def strategy_component_id(station: str) -> str:
    """Unique ``strategy_id`` per station -- ``Trader.add_strategy`` rejects a collision."""
    return f"{_COMPONENT_ID_PREFIX}-{station}"


def make_trial_day_latch_factory(
    intent_latch: SubmitIntentLatch,
) -> Callable[[], AbstractContextManager[TrialDayLatch]]:
    """Return a factory that binds a ``TrialDayLatch`` to *intent_latch*.

    The factory's context manager does NOT close the intent latch: the
    composition root owns that flock for the process lifetime. Each strategy
    ``on_start`` enters this factory; ``on_stop`` exits it.
    """

    @contextmanager
    def _factory() -> Iterator[TrialDayLatch]:
        yield open_trial_day_latch(intent_latch)

    return _factory


def _facts_from_instrument(instrument: object) -> tuple[str, dt.date, Measure] | None:
    info = getattr(instrument, "info", None)
    try:
        facts = read_weather_bucket_facts(info)
    except WeatherFactsUnavailableError:
        facts = None
    if facts is not None:
        return facts.settlement_station, facts.climate_day, facts.measure

    instrument_id = getattr(instrument, "id", None)
    if not isinstance(instrument_id, InstrumentId):
        return None
    try:
        slug = instrument_id_to_slug(instrument_id)
    except VenuePayloadError:
        return None
    parsed = parse_weather_slug(slug)
    if parsed is None:
        return None
    try:
        measure = Measure(parsed.measure)
        climate_day = dt.date.fromisoformat(parsed.climate_date)
    except ValueError:
        return None
    return parsed.city.upper(), climate_day, measure


def resolve_station_instrument_ids(
    catalog_root: Path,
    today_by_station: Mapping[str, dt.date],
) -> dict[str, tuple[InstrumentId, ...]]:
    """Read the catalog UNFILTERED and keep today's HIGH markets per station.

    Identifier-filtered ``catalog.instruments(instrument_ids=[...])`` silently
    omits every flat-written row -- always call ``instruments()`` with no ids.
    """
    catalog = ParquetDataCatalog(str(catalog_root))
    raw = catalog.instruments()
    instruments = list(raw) if raw is not None else []

    buckets: dict[str, list[InstrumentId]] = {station: [] for station in SUPPORTED_STATIONS}
    for instrument in instruments:
        parsed = _facts_from_instrument(instrument)
        if parsed is None:
            continue
        station, climate_day, measure = parsed
        if measure is not Measure.HIGH:
            continue
        if station not in SUPPORTED_STATIONS:
            continue
        if climate_day != today_by_station.get(station):
            continue
        instrument_id = getattr(instrument, "id", None)
        if isinstance(instrument_id, InstrumentId):
            buckets[station].append(instrument_id)
    return {station: tuple(ids) for station, ids in buckets.items()}


def _zero_instruments_message(
    resolved: Mapping[str, tuple[InstrumentId, ...]],
    today_by_station: Mapping[str, dt.date],
) -> str:
    dates = sorted({day.isoformat() for day in today_by_station.values()})
    date_part = dates[0] if len(dates) == 1 else ",".join(dates)
    counts = " ".join(f"{station}={len(resolved[station])}" for station in SUPPORTED_STATIONS)
    return (
        f"current_rung_hold: resolved 0 instruments for {date_part} ({counts}); refusing to start"
    )


def build_current_rung_hold_strategies(
    *,
    catalog_root: Path,
    today_by_station: Mapping[str, dt.date],
    trial_day_latch_factory: Callable[[], AbstractContextManager[TrialDayLatch]],
) -> tuple[CurrentRungHoldStrategy, ...]:
    """One strategy per supported station that resolved at least one instrument.

    ``orders_enabled`` is never passed: the config default is False and
    constructing True is refused. ``strategy_id`` / ``order_id_tag`` are set
    per station so ``Trader.add_strategy`` uniqueness checks both pass.
    """
    resolved = resolve_station_instrument_ids(catalog_root, today_by_station)
    if all(len(ids) == 0 for ids in resolved.values()):
        raise NoTradableInstrumentsError(_zero_instruments_message(resolved, today_by_station))

    strategies: list[CurrentRungHoldStrategy] = []
    for station in SUPPORTED_STATIONS:
        instrument_ids = resolved[station]
        if not instrument_ids:
            logger.warning(
                "current_rung_hold: skipping %s; resolved 0 instruments for %s",
                station,
                today_by_station[station].isoformat(),
            )
            continue
        config = CurrentRungHoldConfig(
            instrument_ids=instrument_ids,
            stations=(station,),
            # Nautilus sets ``Strategy.id`` to ``f"{strategy_id}-{order_id_tag}"``
            # (``trading/strategy.pyx:148-149``). The prefix is the class name;
            # the tag is the station, so both uniqueness checks at
            # ``trader.py:400,416`` pass.
            strategy_id=_COMPONENT_ID_PREFIX,
            order_id_tag=station,
        )
        strategies.append(
            CurrentRungHoldStrategy(
                config, trial_day_latch_factory=trial_day_latch_factory
            )
        )
    return tuple(strategies)


def install_current_rung_hold_refusal_watch(
    node: object, strategies: Sequence[CurrentRungHoldStrategy]
) -> None:
    """Wire per-station refusal counts through the existing alert sink.

    PRIMARY path: attaches one ``RefusalAlerter`` per strategy to
    ``strategy.refusal_alerter``, so ``on_quote_tick`` reports its own
    updated count on the very tick that produced a refusal -- during a
    normal run, with no FSM degrade needed and no new ``LiveClock`` timer
    (L-16). Review fix: the previous wiring surfaced counts ONLY on
    ``COMPONENT_STATE_TOPIC``, which fires once at startup and otherwise
    only on a degrade transition, so per-station refusal counters never
    reached an operator during a normal live run.

    SECONDARY path (kept): the same alerters are re-evaluated on
    ``COMPONENT_STATE_TOPIC`` too, catching a station that degrades without
    ever seeing a fresh quote. A missing ``msgbus`` used to make this whole
    function return silently; it now logs a WARNING and still wires the
    primary (per-tick) path, since that path needs no ``msgbus`` at all.
    """
    sink = resolve_alert_sink()
    alerters = tuple(
        RefusalAlerter(strategy.refusals, site=str(strategy.id), sink=sink)
        for strategy in strategies
    )
    if not alerters:
        return

    for strategy, alerter in zip(strategies, alerters, strict=True):
        strategy.refusal_alerter = alerter

    def _on_event(_event: object) -> None:
        now_ns = time.time_ns()
        for alerter in alerters:
            try:
                alerter.report(now_ns=now_ns)
            except Exception:
                logger.exception("current_rung_hold refusal watch failed")

    msgbus = getattr(getattr(node, "kernel", None), "msgbus", None)
    if msgbus is None:
        logger.warning(
            "current_rung_hold refusal watch: no msgbus on node; the "
            "COMPONENT_STATE_TOPIC secondary refusal channel is disabled "
            "for this run (per-tick reporting via strategy.refusal_alerter "
            "is unaffected)"
        )
        return
    msgbus.subscribe(topic=COMPONENT_STATE_TOPIC, handler=_on_event)
