"""SL-13 fix-first review, follow-up -- ``build_forecast_quantile_ladder_strategies``
must resolve TOMORROW's instruments (D+1, in each station's own LST), never
today's -- this family trades D+1 only (``decision._is_d_plus_1``).

Boot instant: 2026-09-29T16:50:00Z (``_NOW_NS``, hand-computed below).
LAX is UTC-8 (``local_standard_date`` is never DST-aware): local standard
time 08:50 on 2026-09-29 -> D+1 = 2026-09-30. MIA is UTC-5: local standard
time 11:50 on 2026-09-29 -> D+1 = 2026-09-30. Both land on the same D+1
CALENDAR date at this particular boot instant (neither offset is large
enough to cross UTC midnight backwards from 16:50Z) -- each is computed
independently, per station, via the SAME ``local_standard_date`` helper
``decision._is_d_plus_1`` itself calls.

``resolve_station_instrument_ids`` (``current_rung_hold.composition``) is
NEVER modified or called with a changed default anywhere in this file --
every call here either goes through the untouched
``build_forecast_quantile_ladder_strategies`` (which now resolves D+1
internally) or calls the resolver directly with an EXPLICIT day mapping,
exactly as ``current_rung_hold``/``continuous_rung_hold`` already do.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import AssetClass
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from nautilus_trader.portfolio import Portfolio
from nautilus_trader.common.component import TestClock
from nautilus_trader.model.identifiers import TraderId
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.adapters.polymarket_us.symbology import sibling_instrument_id
from breezy.domain.weather_bucket_facts import (
    CLIMATE_DAY_KEY,
    MEASURE_KEY,
    SETTLEMENT_STATION_KEY,
    STRIKE_LOWER_F_KEY,
    STRIKE_UPPER_F_KEY,
    WEATHER_FACTS_STATUS_KEY,
    WEATHER_FACTS_STATUS_KNOWN,
)
from breezy.strategy.current_rung_hold.composition import resolve_station_instrument_ids
from breezy.strategy.forecast_quantile_ladder.composition import (
    NoTradableForecastInstrumentsError,
    build_forecast_quantile_ladder_strategies,
)
from breezy.strategy.forecast_quantile_ladder.latch import QuantileLadderLatch

_VENUE = Venue("POLYMARKET_US")
_NOW_NS = 1_790_700_600_000_000_000  # 2026-09-29T16:50:00Z
_BOOT_DAY = dt.date(2026, 9, 29)
_D_PLUS_1 = dt.date(2026, 9, 30)
_LAX = "LAX"
_MIA = "MIA"

_ARTEFACT_PAYLOAD: dict[str, Any] = {
    "schema_version": 1,
    "cdf_method": "normal",
    "recalibration": "emos",
    "correction_form": "additive",
    "delta": 1.0,
    "kappa": 1.0,
    "emos_params_by_version": {"v1": [0.0, 0.0]},
    "emos_draws_by_version": {"v1": [[0.0, 0.0], [0.05, 0.02], [-0.05, -0.01]]},
    "emos": {"a": 0.0, "gamma": 0.0, "delta": 1.0},
    "n_min": 30,
    "sigma_d": 1.0,
    "rung_probability_bounds": {},
}


def _facts_info(*, station: str, climate_day: dt.date) -> dict[str, object]:
    return {
        WEATHER_FACTS_STATUS_KEY: WEATHER_FACTS_STATUS_KNOWN,
        SETTLEMENT_STATION_KEY: station,
        CLIMATE_DAY_KEY: climate_day.isoformat(),
        MEASURE_KEY: "high",
        STRIKE_LOWER_F_KEY: 80,
        STRIKE_UPPER_F_KEY: 81,
    }


def _yes_instrument(*, station: str, climate_day: dt.date) -> BinaryOption:
    slug = f"{station.lower()}-d{climate_day.isoformat()}-80-81"
    instrument_id = InstrumentId(Symbol(slug), _VENUE)
    increment = Price.from_str("0.01")
    size_increment = Quantity.from_str("1")
    return BinaryOption(
        instrument_id=instrument_id,
        raw_symbol=instrument_id.symbol,
        outcome="Yes",
        description=f"{station} daily high",
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
        info=_facts_info(station=station, climate_day=climate_day),
    )


def _no_instrument(yes: BinaryOption) -> BinaryOption:
    """The NO leg's OWN catalog row -- shares its YES sibling's `info`
    byte-for-byte (NO-1/S2 review finding), distinct `id`."""
    no_id = sibling_instrument_id(yes.id)
    return BinaryOption(
        instrument_id=no_id,
        raw_symbol=no_id.symbol,
        outcome="No",
        description="no leg",
        asset_class=AssetClass.ALTERNATIVE,
        currency=USD,
        price_precision=yes.price_precision,
        price_increment=yes.price_increment,
        size_precision=yes.size_precision,
        size_increment=yes.size_increment,
        activation_ns=0,
        expiration_ns=yes.expiration_ns,
        max_quantity=None,
        min_quantity=Quantity.from_int(1),
        maker_fee=Decimal("0.06"),
        taker_fee=Decimal("0.06"),
        ts_event=0,
        ts_init=0,
        info=dict(yes.info),
    )


@pytest.fixture
def catalog_root(tmp_path: Path) -> Path:
    """D0 AND D+1 rows, YES AND NO legs, for BOTH LAX and MIA."""
    root = tmp_path / "catalog"
    catalog = ParquetDataCatalog(str(root))
    instruments: list[BinaryOption] = []
    for station in (_LAX, _MIA):
        for day in (_BOOT_DAY, _D_PLUS_1):
            yes = _yes_instrument(station=station, climate_day=day)
            instruments.append(yes)
            instruments.append(_no_instrument(yes))
    catalog.write_data(instruments)
    return root


def _artefact_files(tmp_path: Path) -> tuple[str, str]:
    import hashlib
    import json

    path = tmp_path / "density.json"
    raw = json.dumps(_ARTEFACT_PAYLOAD).encode("utf-8")
    path.write_bytes(raw)
    return str(path), hashlib.sha256(raw).hexdigest()


def test_d_plus_1_yes_and_no_instruments_are_resolved_for_lax_and_mia(
    catalog_root: Path, tmp_path: Path,
) -> None:
    artefact_path, artefact_sha = _artefact_files(tmp_path)

    strategies, _quantile_actor = build_forecast_quantile_ladder_strategies(
        catalog_root=catalog_root,
        today_by_station={_LAX: _BOOT_DAY, _MIA: _BOOT_DAY},
        latch=QuantileLadderLatch(),
        calibration_artefact_path=artefact_path,
        calibration_artefact_sha256=artefact_sha,
        bounds_artefact_path=artefact_path,
        bounds_artefact_sha256=artefact_sha,
        now_ns_fn=lambda: _NOW_NS,
    )

    assert {s.config.stations[0] for s in strategies} == {_LAX, _MIA}
    by_station = {s.config.stations[0]: s for s in strategies}
    for station in (_LAX, _MIA):
        strategy = by_station[station]
        # The composed strategy's own `instrument_ids` (built at on_start
        # via `_instrument_ids`) must carry the D+1 YES id -- register +
        # start it against a cache holding every catalog row so `on_start`
        # can resolve both legs.
        cache = TestComponentStubs.cache()
        for yes_id_str in strategy._instrument_ids:  # noqa: SLF001 - white-box check
            instrument_id = InstrumentId.from_str(yes_id_str)
            assert instrument_id.symbol.value.endswith(f"d{_D_PLUS_1.isoformat()}-80-81")
        clock = TestClock()
        clock.set_time(_NOW_NS)
        msgbus = TestComponentStubs.msgbus()
        for day in (_BOOT_DAY, _D_PLUS_1):
            yes = _yes_instrument(station=station, climate_day=day)
            cache.add_instrument(yes)
            cache.add_instrument(_no_instrument(yes))
        portfolio = Portfolio(msgbus=msgbus, cache=cache, clock=clock)
        strategy.register(
            trader_id=TraderId("BACKTEST-001"), portfolio=portfolio, msgbus=msgbus, cache=cache,
            clock=clock,
        )
        strategy.start()

        d_plus_1_key = (station, _D_PLUS_1.isoformat())
        matching = [key for key in strategy.rung_instruments if key[:2] == d_plus_1_key]
        assert matching, f"{station}: no D+1 rung resolved"
        yes_id, no_id = strategy.rung_instruments[matching[0]]
        assert _D_PLUS_1.isoformat() in yes_id
        assert no_id != yes_id

        d0_key = (station, _BOOT_DAY.isoformat())
        assert not [key for key in strategy.rung_instruments if key[:2] == d0_key], (
            f"{station}: a D0 rung was resolved; only D+1 may ever appear"
        )


def test_zero_d_plus_1_instruments_refuses_cleanly_never_substitutes_today(
    tmp_path: Path,
) -> None:
    """The venue has only listed TODAY's markets -- D+1 has not opened yet."""
    root = tmp_path / "catalog_today_only"
    catalog = ParquetDataCatalog(str(root))
    yes = _yes_instrument(station=_LAX, climate_day=_BOOT_DAY)
    catalog.write_data([yes, _no_instrument(yes)])
    artefact_path, artefact_sha = _artefact_files(tmp_path)

    with pytest.raises(NoTradableForecastInstrumentsError):
        build_forecast_quantile_ladder_strategies(
            catalog_root=root,
            today_by_station={_LAX: _BOOT_DAY},
            latch=QuantileLadderLatch(),
            calibration_artefact_path=artefact_path,
            calibration_artefact_sha256=artefact_sha,
            bounds_artefact_path=artefact_path,
            bounds_artefact_sha256=artefact_sha,
            now_ns_fn=lambda: _NOW_NS,
        )


def test_resolve_station_instrument_ids_called_directly_with_todays_day_is_unchanged(
    catalog_root: Path,
) -> None:
    """The SAME shared resolver, called the SAME way
    ``current_rung_hold``/``continuous_rung_hold`` already call it (an
    explicit today's-day mapping), still returns TODAY's ids -- proof this
    slice never altered ``resolve_station_instrument_ids`` or its default
    behaviour for those callers."""
    resolved = resolve_station_instrument_ids(catalog_root, {_LAX: _BOOT_DAY, _MIA: _BOOT_DAY})

    for station in (_LAX, _MIA):
        assert len(resolved[station]) == 1
        assert _BOOT_DAY.isoformat() in str(resolved[station][0])
        assert _D_PLUS_1.isoformat() not in str(resolved[station][0])
