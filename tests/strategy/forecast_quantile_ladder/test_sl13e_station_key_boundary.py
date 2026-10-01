"""SL-13e ITEM 1 -- ``ForecastQuantileStateActor`` must be keyed the SAME way
``NbmQuantileActor`` actually publishes ``ForecastPoint.station`` under.

Verifies a suspected real-boot bug by composing the REAL actor pair:

* a real :class:`~breezy.ingest.nbm_quantile_actor.NbmQuantileActor`, fed the
  REAL captured bulletin ``tests/fixtures/nbm/nbptx_t13z_excerpt.txt`` (never
  a synthetic point), publishing onto a real Nautilus message bus;
* the REAL :class:`~breezy.strategy.ladder_ev.forecast_subscriber.
  ForecastQuantileStateActor` :func:`~breezy.strategy.forecast_quantile_ladder.
  composition.build_forecast_quantile_ladder_strategies` itself builds (never
  a hand-rebuilt stand-in), registered on the SAME bus.

Before the SL-13e fix: composition built the shared actor keyed by the CITY
token ``today_by_station`` uses ("MIA"), while ``NbmQuantileActor`` (and every
real NBM capture) publishes the ICAO id ("KMIA") -- ``on_data`` never matched
a point (``unknown_station`` forever), so the vector never completed. This
test fails RED on that bug: ``quantile_actor.state_for("KMIA")`` either
KeyErrors (the pre-fix actor never served "KMIA" at all) or, if a caller
patched it to use "KMIA" as the served key, its state would stay forever
empty because the mismatched `on_data` lookup would drop the real point.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
from collections.abc import Callable
from pathlib import Path

import pytest
from nautilus_trader.common.component import TestClock
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.ingest.nbm_quantile_actor import NbmQuantileActor, NbmQuantileActorConfig
from breezy.ingest.nbm_quantile_transport import NbmQuantileFetchResult
from breezy.strategy.forecast_quantile_ladder.composition import (
    build_forecast_quantile_ladder_strategies,
)
from breezy.strategy.forecast_quantile_ladder.latch import QuantileLadderLatch
from tests.strategy.forecast_quantile_ladder.test_sl13c_d_plus_1_resolution import (
    _artefact_files,
    _no_instrument,
    _yes_instrument,
)

_STATION = "MIA"
_ICAO = "KMIA"
_FIXTURE_13Z = (
    Path(__file__).resolve().parents[2] / "fixtures" / "nbm" / "nbptx_t13z_excerpt.txt"
).read_text(encoding="utf-8")

NS = 1_000_000_000
#: The fixture's own 13Z cycle: 2026-09-28T13:00Z.
_CYCLE_NS = int(dt.datetime(2026, 9, 28, 13, tzinfo=dt.UTC).timestamp()) * NS
_LAG_NS = 65 * 60 * NS  # 65 min: above the 60 min NBM_NBP publication floor
_NOW_NS = _CYCLE_NS + _LAG_NS + 60 * NS
_LAST_MODIFIED = "Mon, 28 Sep 2026 14:05:00 GMT"  # _CYCLE_NS + _LAG_NS

#: MIA's LST offset is -5h: 2026-09-28T14:06Z LST is 2026-09-28T09:06, so
#: D+1 (what `build_forecast_quantile_ladder_strategies` resolves catalog
#: instruments for) is 2026-09-29.
_D_PLUS_1 = dt.date(2026, 9, 29)


class _FixtureFetcher:
    """Answers every fetch with the REAL 13Z capture -- never synthetic."""

    def __init__(self, clock: Callable[[], int]) -> None:
        self._clock = clock

    async def fetch_nbp_bulletin(
        self, *, cycle_date: dt.date, cycle_hour: int,
    ) -> NbmQuantileFetchResult:
        del cycle_date, cycle_hour
        now_ns = self._clock()
        return NbmQuantileFetchResult(
            text=_FIXTURE_13Z,
            source_host="noaa-nbm-grib2-pds.s3.amazonaws.com",
            last_modified=_LAST_MODIFIED,
            fetched_at_ns=now_ns,
            raw_sha256=hashlib.sha256(_FIXTURE_13Z.encode("utf-8")).hexdigest(),
            raw_bytes=len(_FIXTURE_13Z.encode("utf-8")),
        )


async def _drain(actor: NbmQuantileActor) -> None:
    for _ in range(5_000):
        if actor.inflight == 0:
            return
        await asyncio.sleep(0)
    raise AssertionError("NbmQuantileActor still has work in flight")


def _write_catalog(root: Path) -> None:
    from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

    catalog = ParquetDataCatalog(str(root))
    yes = _yes_instrument(station=_STATION, climate_day=_D_PLUS_1)
    catalog.write_data([yes, _no_instrument(yes)])


@pytest.mark.asyncio
async def test_the_real_nbm_actor_feeds_the_composed_quantile_actor(
    tmp_path: Path,
) -> None:
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    _write_catalog(catalog_root)
    artefact_path, artefact_sha = _artefact_files(tmp_path)

    # The REAL composition-root construction -- never a hand-rebuilt actor.
    _strategies, quantile_actor = build_forecast_quantile_ladder_strategies(
        catalog_root=catalog_root,
        today_by_station={_STATION: dt.date(2026, 9, 28)},
        latch=QuantileLadderLatch(),
        calibration_artefact_path=artefact_path,
        calibration_artefact_sha256=artefact_sha,
        now_ns_fn=lambda: _NOW_NS,
    )

    clock = TestClock()
    clock.set_time(_NOW_NS)
    msgbus = TestComponentStubs.msgbus()
    cache = TestComponentStubs.cache()
    portfolio = TestComponentStubs.portfolio()

    quantile_actor.register_base(portfolio=portfolio, msgbus=msgbus, cache=cache, clock=clock)
    quantile_actor.start()

    # The REAL producer, fed the REAL captured bulletin -- publishes
    # `ForecastPoint.station` as the ICAO id ("KMIA"), exactly as a live
    # NBM_NBP capture always does (`app/trade.py`'s own
    # `station_icaos = tuple(registry.settlement_site(_VENUE, station).icao
    # for station in today_by_station)`).
    nbm_actor = NbmQuantileActor(
        NbmQuantileActorConfig(station_icaos=(_ICAO,)),
        transport_factory=_FixtureFetcher,
    )
    nbm_actor.register_base(portfolio=portfolio, msgbus=msgbus, cache=cache, clock=clock)
    nbm_actor.start()
    await _drain(nbm_actor)

    assert nbm_actor.published_count > 0, "the real NBM actor published nothing at all"

    vector = quantile_actor.state_for(_ICAO).value_at(_NOW_NS)
    assert vector is not None, (
        "the composed ForecastQuantileStateActor never saw the real NBM "
        "actor's published points -- station-key mismatch (SL-13e item 1)"
    )
