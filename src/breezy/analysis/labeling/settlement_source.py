"""The per-venue settlement source registry (AUT-2 r7 WP3, section 3.5).

``polymarket_us`` settles on the NWS CLI FINAL, read as the latest revision (the reused catalog
reader). ``kalshi`` settles on The Weather Company and no reader exists, so its source refuses and a
Kalshi family fails closed instead of being labelled from the wrong truth. An unknown venue refuses
the same way.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping
from typing import Final, Protocol

from nautilus_trader.persistence.catalog import ParquetDataCatalog

from breezy.domain.nws_climate_day import NwsClimateDay
from breezy.persistence.catalog import read_climate_day_including_corrections

__all__ = [
    "SETTLEMENT_SOURCES",
    "NwsCliFinal",
    "RefusingSettlementSource",
    "SettlementSource",
    "SettlementSourceRefused",
    "settlement_source_for",
]


class SettlementSourceRefused(Exception):
    """The venue has no settlement reader; ``args[0]`` is the machine-readable reason."""


class SettlementSource(Protocol):
    def record(self, station: str, climate_day: dt.date) -> NwsClimateDay | None: ...


class NwsCliFinal:
    """The latest stored NWS CLI record for a station-day. Grading (FINAL, not superseded, a real
    ``tmax_f``) stays with ``score_trial``; this source only supplies the record."""

    def __init__(self, catalog: ParquetDataCatalog) -> None:
        self._catalog = catalog

    def record(self, station: str, climate_day: dt.date) -> NwsClimateDay | None:
        return read_climate_day_including_corrections(
            self._catalog, station=station, climate_day=climate_day
        )


class RefusingSettlementSource:
    def __init__(self, reason: str) -> None:
        self._reason = reason

    def record(self, station: str, climate_day: dt.date) -> NwsClimateDay | None:
        raise SettlementSourceRefused(self._reason)


def _kalshi(catalog: ParquetDataCatalog) -> SettlementSource:
    return RefusingSettlementSource("twc_reader_absent")


SETTLEMENT_SOURCES: Final[Mapping[str, Callable[[ParquetDataCatalog], SettlementSource]]] = {
    "polymarket_us": NwsCliFinal,
    "kalshi": _kalshi,
}


def settlement_source_for(venue: str, catalog: ParquetDataCatalog) -> SettlementSource:
    factory = SETTLEMENT_SOURCES.get(venue)
    if factory is None:
        return RefusingSettlementSource("unknown_venue")
    return factory(catalog)
