"""S2 follow-up (blast-radius review of 5bc3b6a, [HIGH]).

``resolve_station_instrument_ids``/``_facts_from_instrument`` bucket by
``info`` facts only, and the NO leg carries the SAME facts as its YES
sibling, so an unfiltered pass admits BOTH legs into one station's
``instrument_ids`` -- doubling every rung ``ContinuousRungHoldStrategy.
on_start`` hands to ``self._ladders``/``build_eligible_inputs``, and
subscribing the NO id (which the data client refuses with an ERROR log,
never a market data feed call).

Fixed at the source in ``composition.py``: only an instrument whose
``leg_of(instrument_id) == "yes"`` is admitted. Legacy instruments carrying
no composite suffix are still YES (``leg_of`` is purely id-derived).
"""

from __future__ import annotations

import contextlib
import datetime as dt
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

from nautilus_trader.common.component import TestClock
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import AssetClass
from nautilus_trader.model.identifiers import InstrumentId, Symbol, TraderId, Venue
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from nautilus_trader.portfolio import Portfolio
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.adapters.polymarket_us.symbology import no_leg_instrument_id
from breezy.domain.weather_bucket_facts import (
    CLIMATE_DAY_KEY,
    MEASURE_KEY,
    SETTLEMENT_STATION_KEY,
    STRIKE_LOWER_F_KEY,
    STRIKE_UPPER_F_KEY,
    WEATHER_FACTS_STATUS_KEY,
    WEATHER_FACTS_STATUS_KNOWN,
)
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import open_submit_intent_latch
from breezy.strategy.current_rung_hold.composition import (
    build_continuous_rung_hold_strategies,
    build_current_rung_hold_strategies,
    resolve_station_instrument_ids,
)
from breezy.strategy.current_rung_hold.config import SUPPORTED_STATIONS
from breezy.strategy.current_rung_hold.trial_day_latch import (
    CONTINUOUS_TRIAL_KEY_PREFIX,
    open_trial_day_latch,
)

_POLYMARKET_VENUE = Venue("POLYMARKET_US")
_DAY = dt.date(2026, 9, 4)
_ALL_STATIONS_TODAY = {station: _DAY for station in SUPPORTED_STATIONS}


def _known(*, station: str, day: dt.date, measure: str = "high") -> dict[str, object]:
    return {
        WEATHER_FACTS_STATUS_KEY: WEATHER_FACTS_STATUS_KNOWN,
        SETTLEMENT_STATION_KEY: station,
        CLIMATE_DAY_KEY: day.isoformat(),
        MEASURE_KEY: measure,
        STRIKE_LOWER_F_KEY: 80,
        STRIKE_UPPER_F_KEY: 81,
    }


def _binary(instrument_id: InstrumentId, slug: str, *, info: dict[str, object]) -> BinaryOption:
    increment = Price.from_str("0.01")
    size_increment = Quantity.from_str("1")
    return BinaryOption(
        instrument_id=instrument_id,
        raw_symbol=Symbol(slug),
        outcome="Yes",
        description="test",
        asset_class=AssetClass.ALTERNATIVE,
        currency=USD,
        price_precision=increment.precision,
        price_increment=increment,
        size_precision=size_increment.precision,
        size_increment=size_increment,
        activation_ns=0,
        expiration_ns=200 * 3_600_000_000_000,
        max_quantity=None,
        min_quantity=Quantity.from_int(1),
        maker_fee=Decimal("0.06"),
        taker_fee=Decimal("0.06"),
        ts_event=0,
        ts_init=0,
        info=info,
    )


def _write_both_legs(
    tmp_path: Path, *, slug: str, station: str
) -> tuple[InstrumentId, InstrumentId]:
    yes_id = InstrumentId(Symbol(slug), _POLYMARKET_VENUE)
    no_id = no_leg_instrument_id(slug)
    info = _known(station=station, day=_DAY)
    no_info = dict(info)
    no_info["leg"] = "no"
    ParquetDataCatalog(str(tmp_path)).write_data(
        [_binary(yes_id, slug, info=info), _binary(no_id, slug, info=no_info)]
    )
    return yes_id, no_id


@contextlib.contextmanager
def _unused_latch_factory() -> Iterator[object]:
    yield object()


def _real_continuous_latch_factory(store_path: Path) -> Iterator[object]:
    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
        yield open_trial_day_latch(
            intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX, family_id="pm_us_crh_v4",
        )


def test_resolve_station_instrument_ids_admits_only_the_yes_leg(tmp_path: Path) -> None:
    yes_id, no_id = _write_both_legs(
        tmp_path, slug="tc-temp-laxhigh-2026-09-04-gte80lt81f", station="LAX"
    )

    resolved = resolve_station_instrument_ids(tmp_path, {"LAX": _DAY})

    assert resolved["LAX"] == (yes_id,)
    assert no_id not in resolved["LAX"]


def test_v2_composition_receives_yes_only_ids_when_the_catalog_holds_both_legs(
    tmp_path: Path,
) -> None:
    """v2 `CurrentRungHoldStrategy` (byte-frozen -- not edited here) is
    composed through the SAME `resolve_station_instrument_ids` helper, so it
    must receive YES-only ids too.
    """
    yes_id, _no_id = _write_both_legs(
        tmp_path, slug="tc-temp-sfohigh-2026-09-04-gte70lt71f", station="SFO"
    )

    strategies = build_current_rung_hold_strategies(
        catalog_root=tmp_path,
        today_by_station=_ALL_STATIONS_TODAY,
        trial_day_latch_factory=_unused_latch_factory,
    )
    assert len(strategies) == 1
    assert strategies[0]._config.instrument_ids == (yes_id,)


def test_continuous_on_start_ladder_has_no_duplicate_rung_when_the_cache_holds_both_legs(
    tmp_path: Path,
) -> None:
    """End-to-end: a catalog holding both legs of one market must produce a
    `ContinuousRungHoldStrategy` whose `_ladders` has exactly ONE
    `(lower, upper)` entry for the station's climate day, and whose
    subscribe path is never called with the NO id -- even though the cache
    (mirroring a real boot after the S2 provider caches both legs) holds
    both instruments.
    """
    slug = "tc-temp-miahigh-2026-09-04-gte70lt71f"
    station = "MIA"
    yes_id, no_id = _write_both_legs(tmp_path, slug=slug, station=station)
    info = _known(station=station, day=_DAY)
    no_info = dict(info)
    no_info["leg"] = "no"

    store_path = tmp_path / "state.db"
    latch_factory = contextlib.contextmanager(_real_continuous_latch_factory)

    strategies = build_continuous_rung_hold_strategies(
        catalog_root=tmp_path,
        today_by_station=_ALL_STATIONS_TODAY,
        trial_day_latch_factory=lambda: latch_factory(store_path),
    )
    assert len(strategies) == 1
    strategy = strategies[0]
    assert strategy._config.instrument_ids == (yes_id,)

    clock = TestClock()
    msgbus = TestComponentStubs.msgbus()
    cache = TestComponentStubs.cache()
    cache.add_instrument(_binary(yes_id, slug, info=info))
    cache.add_instrument(_binary(no_id, slug, info=no_info))
    portfolio = Portfolio(msgbus=msgbus, cache=cache, clock=clock)
    strategy.register(
        trader_id=TraderId("BACKTEST-001"),
        portfolio=portfolio,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
    )
    subscribed: list[InstrumentId] = []
    strategy.subscribe_quote_ticks = subscribed.append  # type: ignore[method-assign]
    strategy.subscribe_order_book_depth = lambda *_a, **_kw: None  # type: ignore[method-assign]
    strategy.start()

    assert subscribed == [yes_id]
    assert no_id not in subscribed
    ladder_key = (station, _DAY.isoformat())
    assert len(strategy._ladders.get(ladder_key, [])) == 1
